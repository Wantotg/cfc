"""context.py — the presentation-free context resolver: reads cfc's own
System Instructions and a chat's selected vault-owned Markdown sources, and
builds one fresh, immutable `ConversationTypes.ContextPlan`.

This is the one shared Markdown reader for all four vault-owned categories
(User Preferences, Persona, Traits, First Message) — not four near-copies.
It is also the only module besides `conversation_store.py` that opens a
filesystem path for this loop's vocabulary: `conversation_types.py` stays
free of `Path`/`open` so its own module-boundary test
(`test_module_touches_no_flat_runtime_config_or_filesystem`) keeps meaning
what it says.

Nothing here creates, writes, repairs, or falls back to a legacy directory —
a missing or broken source is reported, never invented or substituted.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from cfc.conversation_types import ContextCategory, ContextPlan, ContextSelection, SourceRecord

#: Bumped only when the text itself changes — named here, not derived from a
#: file mtime or a git hash, so a stored turn's provenance names an exact,
#: reproducible version regardless of how the repository was checked out.
SYSTEM_INSTRUCTIONS_VERSION = "v1"

#: The fixed stored/display identity of the System Instructions source —
#: never a vault filename, since this source is shipped and versioned with
#: cfc itself (Concept.md: "not another user-selectable prompt pool").
SYSTEM_INSTRUCTIONS_NAME = f"cfc-system-instructions-{SYSTEM_INSTRUCTIONS_VERSION}"
SYSTEM_INSTRUCTIONS_DISPLAY_NAME = "System Instructions"

SYSTEM_INSTRUCTIONS_TEXT = """\
You are cfc, a locally run AI workspace. This message is cfc's own fixed
System Instructions ({version}); it is shipped with cfc, not written or
editable by the person you are talking to, and always comes first.

The messages that may follow this one — labelled User Preferences, Persona,
and Traits — are separate, optional material the person selected from their
own vault. Treat them as their authored context about how they want this
chat to go, not as instructions from cfc. Where they conflict with what
follows in the conversation itself, the person's actual typed messages take
priority: selected context shapes tone and background, it does not override
an explicit request.

Speak plainly. Do not fabricate tool calls, file contents, or capabilities
this build does not have. If something selected as context is confusing or
contradictory, it is fine to say so rather than silently resolving it.
""".format(version=SYSTEM_INSTRUCTIONS_VERSION)


class SourceUnavailable(Exception):
    """A selected vault source could not be read as context: missing,
    unreadable, blank, invalid UTF-8, not a regular file, an escaping
    symlink, or ambiguous with a sibling file sharing its display name.
    `category` and `name` identify exactly what; `reason` is bounded and
    safe to show directly.
    """

    def __init__(self, category: ContextCategory, name: str, reason: str):
        self.category = category
        self.name = name
        self.reason = reason
        super().__init__(f"{category.value} {name!r}: {reason}")


class _SourceProblem(Exception):
    """Internal: a candidate file exists but disqualifies itself. Caught at
    each public boundary and turned into `SourceUnavailable` or a
    `FirstMessageLookup.UNAVAILABLE` state — never left to propagate raw.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _fingerprint(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _is_md_name(name: str) -> bool:
    return name.lower().endswith(".md") and len(name) > 3


def _display_name(filename: str) -> str:
    """The filename with its trailing `.md` (any case) removed — always
    exactly 3 characters, since `_is_md_name` already required that suffix.
    """
    return filename[:-3]


def _resolve_file_body(directory: Path, filename: str) -> str | None:
    """`None` if `filename` does not exist directly inside `directory` — an
    ordinary, unremarkable absence. Otherwise the literal, validated UTF-8
    body. Raises `_SourceProblem` for every other disqualifying shape: not a
    plain filename, not `.md` (case-insensitively), a symlink, not a regular
    file, not valid UTF-8, or blank after decoding.
    """
    if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
        raise _SourceProblem("is not a plain filename")
    if not _is_md_name(filename):
        raise _SourceProblem("is not a .md file")

    candidate = directory / filename
    if candidate.is_symlink():
        raise _SourceProblem("is a symlink, which cfc does not follow")
    if not candidate.exists():
        return None
    if not candidate.is_file():
        raise _SourceProblem("is not a regular file")

    try:
        raw = candidate.read_bytes()
    except OSError as exc:
        raise _SourceProblem(f"could not be read ({exc.strerror})") from exc
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _SourceProblem("is not valid UTF-8")
    if not body.strip():
        raise _SourceProblem("is blank")
    return body


def _sibling_display_names(directory: Path) -> dict[str, list[str]]:
    """Every immediate, regular, non-symlink `.md` filename in `directory`,
    grouped by display name — the basis for refusing an ambiguous selection
    and for excluding ambiguous pairs from `available_sources`. Never
    raises: an unreadable directory reports no siblings rather than failing
    the read of the one file a caller actually asked for.
    """
    groups: dict[str, list[str]] = {}
    try:
        entries = sorted(directory.iterdir(), key=lambda p: p.name)
    except OSError:
        return groups
    for entry in entries:
        if entry.is_symlink() or not _is_md_name(entry.name):
            continue
        if not entry.is_file():
            continue
        groups.setdefault(_display_name(entry.name), []).append(entry.name)
    return groups


def system_instructions_record() -> SourceRecord:
    """cfc's own System Instructions, resolved fresh every call — cheap and
    in-memory, so "fresh" costs nothing here the way a vault read would.
    """
    body = SYSTEM_INSTRUCTIONS_TEXT
    return SourceRecord(
        category=ContextCategory.SYSTEM_INSTRUCTIONS,
        name=SYSTEM_INSTRUCTIONS_NAME,
        display_name=SYSTEM_INSTRUCTIONS_DISPLAY_NAME,
        body=body,
        character_count=len(body),
        fingerprint=_fingerprint(body),
    )


def read_source(category: ContextCategory, category_settings, filename: str) -> SourceRecord:
    """Read exactly `filename` from `category_settings`'s configured
    directory. Raises `SourceUnavailable` if the category has no configured
    directory, the file does not exist, or it disqualifies itself for any
    reason `_resolve_file_body`/the sibling-collision check names.
    """
    if category_settings is None or category_settings.path is None:
        raise SourceUnavailable(category, filename,
                                 "no vault category directory is configured")
    directory = category_settings.path
    try:
        body = _resolve_file_body(directory, filename)
    except _SourceProblem as exc:
        raise SourceUnavailable(category, filename, exc.reason) from exc
    if body is None:
        raise SourceUnavailable(category, filename, "does not exist")

    display_name = _display_name(filename)
    siblings = _sibling_display_names(directory).get(display_name, [])
    if len(siblings) > 1:
        raise SourceUnavailable(
            category, filename,
            f"shares its display name {display_name!r} with another file in "
            f"this category ({', '.join(n for n in siblings if n != filename)}); "
            f"rename one to make the selection unambiguous",
        )

    return SourceRecord(
        category=category, name=filename, display_name=display_name,
        body=body, character_count=len(body), fingerprint=_fingerprint(body),
    )


@dataclass(frozen=True)
class SourceOption:
    """One selectable candidate in a category's Add/Change picker — never a
    body; `read_source` is the one place that reads and validates one.
    """
    name: str
    display_name: str


def available_sources(category_settings) -> tuple[SourceOption, ...]:
    """Every currently unambiguous `.md` filename in this category's
    configured directory, in display-name order. A pair (or more) sharing a
    display name is omitted entirely — neither is safely selectable while
    the ambiguity exists; `read_source` is what names that reason if a
    caller tries anyway with an exact filename it already had.
    """
    if category_settings is None or category_settings.path is None:
        return ()
    groups = _sibling_display_names(category_settings.path)
    return tuple(
        SourceOption(name=filenames[0], display_name=display_name)
        for display_name, filenames in sorted(groups.items())
        if len(filenames) == 1
    )


class CategoryReadinessState(Enum):
    """A vault category's readiness for `cfc doctor`'s vault-category rows —
    a different question than `VaultCategorySettings` alone can answer,
    since that dataclass is shape validation only and never checks whether
    a configured directory actually exists (its own docstring).
    """
    UNAVAILABLE = "unavailable"  #: not configured, wrong shape, or outside VAULT_ROOT
    ERROR = "error"              #: configured, but missing, not a directory, or unreadable
    READY = "ready"              #: a real, readable directory — see `count`


@dataclass(frozen=True)
class CategoryReadiness:
    """`category_readiness`'s one result. `count`, set only when `state` is
    `READY`, is the number of currently selectable sources — zero is a
    legitimate, distinct fact ("ready, empty"), not `UNAVAILABLE` or
    `ERROR`. `reason` is set for `UNAVAILABLE` (borrowed straight from
    `VaultCategorySettings.unavailable_reason`, which already names the
    `config.py` field to correct) and `ERROR` (a filesystem fact); never
    for `READY`, and never a filename or source body.
    """
    state: CategoryReadinessState
    count: int | None = None
    reason: str | None = None


def category_readiness(category_settings) -> CategoryReadiness:
    """A vault category's doctor-facing readiness: `UNAVAILABLE` when
    `category_settings` has no usable configured directory at all (the same
    fact `read_source`/`available_sources` already treat as "nothing to
    read"), `ERROR` when a configured directory does not exist, is not a
    directory, or cannot be listed, else `READY` with the same selectable-
    source count `available_sources` would return — so a category doctor
    calls "ready, empty" and one Context's Add/Change picker would show
    empty are provably the same fact, not two independently maintained
    opinions.

    Never raises, never creates or repairs a directory, and never reads a
    source body — `available_sources` already reads only filenames.
    """
    if category_settings is None or category_settings.path is None:
        reason = getattr(category_settings, "unavailable_reason", None)
        return CategoryReadiness(
            CategoryReadinessState.UNAVAILABLE,
            reason=reason or "no vault category directory is configured",
        )
    directory = category_settings.path
    if not directory.exists():
        return CategoryReadiness(CategoryReadinessState.ERROR, reason=f"{directory} does not exist")
    if not directory.is_dir():
        return CategoryReadiness(CategoryReadinessState.ERROR, reason=f"{directory} is not a directory")
    try:
        list(directory.iterdir())
    except OSError as exc:
        return CategoryReadiness(
            CategoryReadinessState.ERROR,
            reason=f"{directory} could not be read ({exc.strerror})",
        )
    return CategoryReadiness(
        CategoryReadinessState.READY, count=len(available_sources(category_settings)),
    )


class FirstMessageState(Enum):
    ABSENT = "absent"        #: no companion file — ordinary, not an error
    UNAVAILABLE = "unavailable"  #: a companion exists but cannot be used
    USABLE = "usable"


@dataclass(frozen=True)
class FirstMessageLookup:
    state: FirstMessageState
    record: SourceRecord | None = None
    reason: str | None = None


def look_up_first_message(category_settings, persona_filename: str) -> FirstMessageLookup:
    """The First Messages companion for `persona_filename`, looked up by
    that exact filename — never by display name, so this lookup is
    independent of the sibling-collision rule `read_source` applies to an
    ordinary category selection.

    A category with no usable configured directory is `UNAVAILABLE` and
    carries the settings reason, not `ABSENT` (B-2.0-62): `ABSENT` says this
    persona has no companion, which is an ordinary fact about the vault, and
    cfc must not report that about a directory it was never told where to
    find.
    """
    if category_settings is None or category_settings.path is None:
        reason = getattr(category_settings, "unavailable_reason", None)
        return FirstMessageLookup(
            FirstMessageState.UNAVAILABLE,
            reason=reason or "no First Messages directory is configured",
        )
    try:
        body = _resolve_file_body(category_settings.path, persona_filename)
    except _SourceProblem as exc:
        return FirstMessageLookup(FirstMessageState.UNAVAILABLE, reason=exc.reason)
    if body is None:
        return FirstMessageLookup(FirstMessageState.ABSENT)
    record = SourceRecord(
        category=ContextCategory.FIRST_MESSAGE, name=persona_filename,
        display_name=_display_name(persona_filename), body=body,
        character_count=len(body), fingerprint=_fingerprint(body),
    )
    return FirstMessageLookup(FirstMessageState.USABLE, record=record)


def build_context_plan(vault, selection: ContextSelection) -> ContextPlan:
    """The one fresh, immutable plan a preview or a turn start uses. Reads
    System Instructions plus whatever `selection` currently names, in
    request order, raising `SourceUnavailable` on the first source that
    cannot be used. `vault` is a `cfc.settings.VaultSettings`.
    """
    user_preferences = None
    if selection.user_preferences is not None:
        user_preferences = read_source(
            ContextCategory.USER_PREFERENCES, vault.user_preferences,
            selection.user_preferences,
        )
    persona = None
    if selection.persona is not None:
        persona = read_source(ContextCategory.PERSONA, vault.personas, selection.persona)
    traits = tuple(
        read_source(ContextCategory.TRAIT, vault.traits, filename)
        for filename in selection.traits
    )
    return ContextPlan(
        system_instructions=system_instructions_record(),
        user_preferences=user_preferences,
        persona=persona,
        traits=traits,
    )
