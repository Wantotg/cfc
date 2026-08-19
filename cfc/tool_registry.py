"""tool_registry.py — one `ToolRegistry` owning a `ToolDefinition` for each
included read-only file tool (Stage 6 loop 1): `list_dir`, `read_file`, and
literal `grep`.

A definition contains the provider schema, its capability/authority
requirement, the availability check derived from immutable
`cfc.settings.FileToolSettings`, the argument validator and execution
handler, and the non-visual description of a pending request. The
service's request-plan builder obtains offered schemas from this registry
and places them on the immutable plan the adapter serialises; the service
uses the same returned definition to describe and execute an accepted
call. An unknown name has no definition and is never dispatched by a
name-based `if` chain elsewhere — a caller that finds nothing here already
has everything it needs to build one `unavailable` result.

`PendingToolCall` and `ApprovalPort` live here, not in
`cfc.conversation_types`, for the same reason `cfc.provider_wire.Responder`
does not live there either: they type on this module's own vocabulary
(`ToolDefinition`, parsed/validated arguments), which `conversation_types`
deliberately does not know about. `PendingToolCall` carries no widget,
callback into a screen, SQLite connection, or mutable executor object —
only identities, the tool name, validated arguments, a plain-language
description, and the capability that will be checked.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from cfc.conversation_types import ApprovalDecision, ToolCallId, TurnId
from cfc.provider_wire import WireToolSchema
from cfc.settings import FileToolSettings
from cfc.tool_authority import FileAuthority
from cfc.tool_executor import ExecutionOutcome, IsCancelled, grep, list_dir, read_file


class ToolCapability(Enum):
    """The authority class a tool call's execution will be checked
    against. One member today — every included tool needs only
    `READ_FILES` — but a typed enum rather than a bare string, so a later
    write/network capability is a new member here, not a second
    vocabulary.
    """
    READ_FILES = "read_files"


ArgumentsOrError = tuple[Mapping[str, object], str | None]
Arguments = Mapping[str, object]


@dataclass(frozen=True)
class ToolDefinition:
    """One tool's complete, presentation-free description. `parameters` is
    already the plain JSON Schema dict the provider sees, verbatim.
    `availability(file_tools)` returns `None` when usable, else a bounded
    unavailable reason. `validate_arguments(raw)` parses a provider call's
    raw argument string into `(parsed, None)` or `({}, error)` — schema
    validation only; execution-time authority is `execute`'s own concern,
    checked again regardless of what validation already found usable.
    """
    name: str
    description: str
    parameters: Mapping[str, object]
    capability: ToolCapability
    availability: Callable[[FileToolSettings], str | None]
    validate_arguments: Callable[[str], ArgumentsOrError]
    describe_pending: Callable[[Arguments], str]
    execute: Callable[[Arguments, FileAuthority, FileToolSettings, IsCancelled], ExecutionOutcome]

    def schema(self) -> WireToolSchema:
        return WireToolSchema(name=self.name, description=self.description,
                               parameters=self.parameters)


class ToolRegistry:
    """The one owner of every included `ToolDefinition`. A name switch
    that lives anywhere else (a description layer, a status surface) is
    drift this registry is meant to make visible, not a second inventory.
    """

    def __init__(self, definitions: tuple[ToolDefinition, ...]):
        self._by_name = {definition.name: definition for definition in definitions}

    def get(self, name: str) -> ToolDefinition | None:
        return self._by_name.get(name)

    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._by_name.values())

    def offered_schemas(
        self, file_tools: FileToolSettings, model_is_tool_capable: bool,
    ) -> tuple[WireToolSchema, ...]:
        """The schemas a request plan offers for this turn: every
        definition's schema when file tools are usable and the selected
        model is declared tool-capable, otherwise none. This is a
        capability switch, not approval — every concrete call still
        reaches `ApprovalPort` regardless of how the schemas were offered.
        """
        if not file_tools.usable or not model_is_tool_capable:
            return ()
        return tuple(definition.schema() for definition in self._by_name.values())


@dataclass(frozen=True)
class PendingToolCall:
    """One accepted call awaiting an `ApprovalPort` decision. `arguments`
    is already parsed and schema-validated — never the raw provider
    string, and never re-validated by the port. Carries no widget,
    callback into a screen, SQLite connection, or mutable executor object.
    """
    turn_id: TurnId
    tool_call_id: ToolCallId
    provider_call_id: str
    name: str
    arguments: Arguments
    description: str
    capability: ToolCapability


class ApprovalPort(Protocol):
    """The injected asynchronous boundary `ConversationService.send_turn`
    awaits for each accepted call, sequentially. Approval records intent on
    that one call; it carries no roots and cannot alter the authority later
    given to `ToolDefinition.execute`.
    """

    async def decide(self, pending: PendingToolCall) -> ApprovalDecision:
        ...


# --- argument parsing shared by every definition ---------------------------

def _parse_json_object(raw: str) -> ArgumentsOrError:
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}, "arguments must be valid JSON"
    if not isinstance(parsed, dict):
        return {}, "arguments must be a JSON object"
    return parsed, None


def _require_nonempty_string_field(parsed: Mapping[str, object], field_name: str) -> str | None:
    value = parsed.get(field_name)
    if not isinstance(value, str) or not value:
        return f"{field_name} is required and must be a non-empty string"
    return None


def _unexpected_fields(parsed: Mapping[str, object], allowed: frozenset[str]) -> str | None:
    extra = set(parsed) - allowed
    if extra:
        return f"unexpected argument(s): {', '.join(sorted(extra))}"
    return None


def _file_tools_availability(file_tools: FileToolSettings) -> str | None:
    return None if file_tools.usable else file_tools.unavailable_reason


# --- list_dir ----------------------------------------------------------

_LIST_DIR_PARAMETERS: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Absolute directory path to list."},
    },
    "required": ["path"],
    "additionalProperties": False,
}


def _validate_list_dir_arguments(raw: str) -> ArgumentsOrError:
    parsed, error = _parse_json_object(raw)
    if error is not None:
        return {}, error
    error = _require_nonempty_string_field(parsed, "path")
    if error is not None:
        return {}, error
    error = _unexpected_fields(parsed, frozenset({"path"}))
    if error is not None:
        return {}, error
    return {"path": parsed["path"]}, None


def _describe_list_dir(args: Arguments) -> str:
    return f"List the contents of {args['path']}"


def _execute_list_dir(
    args: Arguments, authority: FileAuthority, settings: FileToolSettings,
    is_cancelled: IsCancelled,
) -> ExecutionOutcome:
    return list_dir(args["path"], authority, settings, is_cancelled)


# --- read_file ----------------------------------------------------------

_READ_FILE_PARAMETERS: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Absolute regular-file path to read."},
        "start_line": {"type": "integer",
                        "description": "1-based first line to include (optional)."},
        "end_line": {"type": "integer",
                      "description": "1-based inclusive last line to include (optional)."},
    },
    "required": ["path"],
    "additionalProperties": False,
}

_READ_FILE_FIELDS = frozenset({"path", "start_line", "end_line"})


def _validate_read_file_arguments(raw: str) -> ArgumentsOrError:
    parsed, error = _parse_json_object(raw)
    if error is not None:
        return {}, error
    error = _require_nonempty_string_field(parsed, "path")
    if error is not None:
        return {}, error
    error = _unexpected_fields(parsed, _READ_FILE_FIELDS)
    if error is not None:
        return {}, error
    result: dict[str, object] = {"path": parsed["path"]}
    for key in ("start_line", "end_line"):
        if key in parsed:
            value = parsed[key]
            if isinstance(value, bool) or not isinstance(value, int):
                return {}, f"{key} must be an integer"
            result[key] = value
    return result, None


def _describe_read_file(args: Arguments) -> str:
    if "start_line" in args or "end_line" in args:
        lo = args.get("start_line", 1)
        hi = args.get("end_line", "end")
        return f"Read {args['path']} (lines {lo}-{hi})"
    return f"Read {args['path']}"


def _execute_read_file(
    args: Arguments, authority: FileAuthority, settings: FileToolSettings,
    is_cancelled: IsCancelled,
) -> ExecutionOutcome:
    return read_file(args["path"], authority, settings,
                      start_line=args.get("start_line"), end_line=args.get("end_line"),
                      is_cancelled=is_cancelled)


# --- literal grep ---------------------------------------------------------

_GREP_PARAMETERS: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string",
                     "description": "Literal text to search for. No regex, glob, or shell."},
        "path": {"type": "string",
                  "description": "Absolute regular-file or directory path to search."},
    },
    "required": ["pattern", "path"],
    "additionalProperties": False,
}


def _validate_grep_arguments(raw: str) -> ArgumentsOrError:
    parsed, error = _parse_json_object(raw)
    if error is not None:
        return {}, error
    error = _require_nonempty_string_field(parsed, "pattern")
    if error is not None:
        return {}, error
    error = _require_nonempty_string_field(parsed, "path")
    if error is not None:
        return {}, error
    error = _unexpected_fields(parsed, frozenset({"pattern", "path"}))
    if error is not None:
        return {}, error
    return {"pattern": parsed["pattern"], "path": parsed["path"]}, None


def _describe_grep(args: Arguments) -> str:
    return f"Search for {args['pattern']!r} under {args['path']}"


def _execute_grep(
    args: Arguments, authority: FileAuthority, settings: FileToolSettings,
    is_cancelled: IsCancelled,
) -> ExecutionOutcome:
    return grep(args["pattern"], args["path"], authority, settings, is_cancelled)


def default_registry() -> ToolRegistry:
    """The one `ToolRegistry` this loop ships: `list_dir`, `read_file`, and
    literal `grep`, each requiring `ToolCapability.READ_FILES` and sharing
    the same `FileToolSettings`-derived availability check.
    """
    return ToolRegistry(definitions=(
        ToolDefinition(
            name="list_dir",
            description="List the entries of one directory, without recursing.",
            parameters=_LIST_DIR_PARAMETERS, capability=ToolCapability.READ_FILES,
            availability=_file_tools_availability, validate_arguments=_validate_list_dir_arguments,
            describe_pending=_describe_list_dir, execute=_execute_list_dir,
        ),
        ToolDefinition(
            name="read_file",
            description="Read a range of lines from one text file, strict UTF-8.",
            parameters=_READ_FILE_PARAMETERS, capability=ToolCapability.READ_FILES,
            availability=_file_tools_availability, validate_arguments=_validate_read_file_arguments,
            describe_pending=_describe_read_file, execute=_execute_read_file,
        ),
        ToolDefinition(
            name="grep",
            description="Search for a literal string in one file, or recursively under one "
                        "directory. No regex.",
            parameters=_GREP_PARAMETERS, capability=ToolCapability.READ_FILES,
            availability=_file_tools_availability, validate_arguments=_validate_grep_arguments,
            describe_pending=_describe_grep, execute=_execute_grep,
        ),
    ))
