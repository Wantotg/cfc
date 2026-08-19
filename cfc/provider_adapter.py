"""provider_adapter.py — the bounded OpenAI-compatible responder
(`cfc.provider_wire.Responder`) that makes the Stage 3+5 kernel usable with
one real, non-streaming chat provider over `httpx`.

`OpenAICompatibleAdapter` is constructed from immutable `ProviderSettings`
(`cfc.settings`) and, in tests only, an injected `httpx` transport — never a
store, a database path, a configuration module, the vault, an authority
object, or a UI callback. `respond` receives only the finished, immutable
`RequestPlan` `conversation_service` already built through
`cfc.provider_wire.build_request_plan` — this module never builds one
itself, never sees a `ConversationSnapshot` or `ContextPlan`, and never
reads a source body outside what is already serialised into that plan. It
makes exactly one attempt per `respond` call: no retry, no model fallback,
no provider discovery, and no request editing beyond what the plan already
decided.

Every way a call can end becomes one of `Completion`, `Failure`,
`ToolCallBatch` (Stage 6 loop 1), or an `asyncio.CancelledError` left to
propagate — never a raw `httpx` exception, a provider dictionary, a header,
a full request, or a full response body reaching the caller or (later)
stored evidence. `FailureEvidence.problem` narrows what went wrong
(`CONNECTION`, `TIMEOUT` with `timeout_phase`, `HTTP_STATUS` with
`status_code`, or `MALFORMED_RESPONSE`); `reason` is always a short,
cfc-authored phrase, never the provider's or `httpx`'s own message text.

A `tool_calls` envelope is parsed into cfc's own `ProposedToolCall`
vocabulary rather than treated as malformed: a missing/blank id, a missing
function name, a missing arguments string, or a repeated id anywhere in the
batch is what makes it malformed (`MALFORMED_RESPONSE`), not the mere
presence of tool calls. Which names are actually known or currently
available is not this module's question — that is the registry's, at
execution time; this boundary only proves the envelope's own shape.
"""
from __future__ import annotations

import math

import httpx

from cfc.conversation_types import (
    Completion,
    Failure,
    FailureEvidence,
    FailureKind,
    ProposedToolCall,
    ProviderProblem,
    ResponderResult,
    TimeoutPhase,
    ToolCallBatch,
    Usage,
)
from cfc.provider_wire import RequestPlan, WireMessage
from cfc.settings import ProviderSettings

#: Distinct timeout budgets per `httpx` phase. `READ` is longer than the
#: others: a model may legitimately take longer to answer than a dead
#: endpoint needs to prove it is unreachable.
_CONNECT_TIMEOUT_S = 10.0
_WRITE_TIMEOUT_S = 10.0
_POOL_TIMEOUT_S = 10.0
_READ_TIMEOUT_S = 90.0

_CHAT_COMPLETIONS_PATH = "/chat/completions"

#: SQLite's `INTEGER` storage class is a signed 64-bit value; a usage count
#: outside this range cannot be stored exactly, so it is rejected rather
#: than silently truncated (D-2.0-38).
_SQLITE_INT_MAX = 2**63 - 1

#: Distinct fixed wording so a caller can tell "the provider sent an
#: in-band error object" (D-2.0-37) apart from every other unusable-body
#: shape — never the envelope's own message, code, or nested fields.
_ERROR_ENVELOPE_REASON = "the provider returned an in-band error instead of a completion"

_INVALID_USAGE_REASON = "the provider reported a usage count cfc could not store exactly"


def _timeout_evidence(phase: TimeoutPhase) -> FailureEvidence:
    return FailureEvidence(
        FailureKind.RESPONDER,
        f"the provider did not respond within its {phase.value} budget",
        problem=ProviderProblem.TIMEOUT, timeout_phase=phase,
    )


def _connection_evidence(exc: Exception) -> FailureEvidence:
    return FailureEvidence(
        FailureKind.RESPONDER, f"could not reach the provider ({type(exc).__name__})",
        problem=ProviderProblem.CONNECTION,
    )


def _http_status_evidence(status_code: int) -> FailureEvidence:
    return FailureEvidence(
        FailureKind.RESPONDER, f"the provider refused the request (HTTP {status_code})",
        problem=ProviderProblem.HTTP_STATUS, status_code=status_code,
    )


def _malformed_evidence(reason: str) -> FailureEvidence:
    return FailureEvidence(FailureKind.RESPONDER, reason, problem=ProviderProblem.MALFORMED_RESPONSE)


class _InvalidUsageCount(Exception):
    """Raised internally when a present usage count is not one of the
    accepted spellings — caught at the `respond` boundary and turned into
    typed malformed evidence, never left to propagate as an internal
    failure.
    """


def _normalized_usage_count(value: object) -> int | None:
    """A present usage count, normalised to a plain `int` SQLite can store
    exactly, or `None` if `value` itself means "not reported" (absent or
    JSON `null`).

    Accepted spellings (D-2.0-38): a JSON integer other than a boolean (JSON
    `true`/`false` decode to `bool`, which is an `int` subclass — excluded
    explicitly so a stray boolean is never read as `0`/`1`), a finite
    whole-number float, or a non-empty ASCII decimal-digit string. Each is
    rejected outright if negative or past `_SQLITE_INT_MAX`.

    Raises `_InvalidUsageCount` for anything else present — a fractional or
    non-finite float, a malformed string, a container, or an out-of-range
    number — rather than silently dropping a count the provider did report.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise _InvalidUsageCount(value)
    if isinstance(value, int):
        count = value
    elif isinstance(value, float):
        if not math.isfinite(value) or value != int(value):
            raise _InvalidUsageCount(value)
        count = int(value)
    elif isinstance(value, str) and value != "" and all(c in "0123456789" for c in value):
        count = int(value)
    else:
        raise _InvalidUsageCount(value)
    if count < 0 or count > _SQLITE_INT_MAX:
        raise _InvalidUsageCount(value)
    return count


def _extract_usage(body: dict) -> Usage | None:
    """`None` unless at least one count is present and valid — an
    all-missing or entirely absent usage object must not attempt to build a
    `Usage` (B-2.0-26: that spelling is not constructible). Unknown usage
    keys are ignored. Raises `_InvalidUsageCount` if a present count is not
    one of the accepted spellings; the caller rejects the whole response
    rather than committing a completion with a dropped or guessed count.
    """
    raw = body.get("usage")
    if not isinstance(raw, dict):
        return None
    input_tokens = _normalized_usage_count(raw.get("prompt_tokens"))
    output_tokens = _normalized_usage_count(raw.get("completion_tokens"))
    total_tokens = _normalized_usage_count(raw.get("total_tokens"))
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens)


def _extract_message(body: dict) -> dict | None:
    """The response's first choice's `message` object, or `None` if the
    shape does not even reach that far — used by both the plain-completion
    and the tool-call-batch parsing paths so they agree on what "no usable
    message at all" means.
    """
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    return message


def _extract_content(message: dict) -> str | None:
    """The literal assistant text on an already-extracted `message` object,
    or `None` for missing, empty, or non-string content — used both for a
    plain completion's required text and a tool-call batch's optional
    accompanying text.
    """
    content = message.get("content")
    if not isinstance(content, str) or content == "":
        return None
    return content


class _InvalidToolCallBatch(Exception):
    """Raised internally when a provider's `tool_calls` envelope is
    malformed — caught at the `respond` boundary and turned into typed
    malformed evidence, never left to propagate as an internal failure.
    """


def _extract_tool_call_batch(raw: object) -> tuple[ProposedToolCall, ...]:
    """Parses a provider's `tool_calls` array into cfc's own
    `ProposedToolCall` vocabulary, preserving each call's raw argument
    string verbatim for replay. A missing/blank id, a missing or non-dict
    `function`, a missing/blank function name, a missing arguments string,
    or a repeated id anywhere in the batch raises `_InvalidToolCallBatch` —
    the Work Order's "a missing/blank ID or a repeated ID makes the provider
    reply malformed and fails the turn before any call is accepted". Two
    calls with equivalent names/arguments but different ids are two real
    calls, not a duplicate.
    """
    if not isinstance(raw, list):
        raise _InvalidToolCallBatch("tool_calls must be a list")

    calls: list[ProposedToolCall] = []
    seen_ids: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise _InvalidToolCallBatch("a tool call must be a JSON object")
        call_id = entry.get("id")
        if not isinstance(call_id, str) or not call_id:
            raise _InvalidToolCallBatch("a tool call has no usable id")
        if call_id in seen_ids:
            raise _InvalidToolCallBatch(f"tool call id {call_id!r} is repeated in the batch")
        seen_ids.add(call_id)

        function = entry.get("function")
        if not isinstance(function, dict):
            raise _InvalidToolCallBatch(f"tool call {call_id!r} has no usable function")
        name = function.get("name")
        if not isinstance(name, str) or not name:
            raise _InvalidToolCallBatch(f"tool call {call_id!r} has no usable function name")
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            raise _InvalidToolCallBatch(f"tool call {call_id!r} has no usable arguments string")

        calls.append(ProposedToolCall(provider_call_id=call_id, name=name, arguments=arguments))

    return tuple(calls)


def _wire_message_dict(message: WireMessage) -> dict:
    """One `WireMessage` as the provider-shaped JSON dict `respond` sends —
    the boundary where cfc's own tool-call/result vocabulary becomes the
    OpenAI-compatible `tool_calls`/`tool_call_id` fields, added only when
    the message actually carries them.
    """
    entry: dict = {"role": message.role, "content": message.content}
    if message.tool_calls is not None:
        entry["tool_calls"] = [
            {
                "id": call.provider_call_id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in message.tool_calls
        ]
    if message.tool_call_id is not None:
        entry["tool_call_id"] = message.tool_call_id
    return entry


class OpenAICompatibleAdapter:
    """A `Responder` bounded to one non-streaming
    `POST {api_base}/chat/completions` per `respond` call."""

    def __init__(self, settings: ProviderSettings, *,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.api_base,
            timeout=httpx.Timeout(
                connect=_CONNECT_TIMEOUT_S, write=_WRITE_TIMEOUT_S,
                pool=_POOL_TIMEOUT_S, read=_READ_TIMEOUT_S,
            ),
            transport=transport,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OpenAICompatibleAdapter":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def respond(self, plan: RequestPlan) -> ResponderResult:
        """Serialise `plan` — already built and validated by
        `conversation_service` through `provider_wire.build_request_plan`
        — and make exactly one HTTP attempt, translating the outcome.

        Task cancellation while `self._client.post` is in flight is not
        caught: it propagates so `conversation_service` can finalise the
        turn as `CancelledOutcome` itself.
        """
        body = {
            "model": plan.model,
            "messages": [_wire_message_dict(message) for message in plan.messages],
            "stream": plan.stream,
        }
        if plan.schemas:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": schema.name,
                        "description": schema.description,
                        "parameters": dict(schema.parameters),
                    },
                }
                for schema in plan.schemas
            ]
        headers = {"Authorization": f"Bearer {self._settings.api_key}"}

        try:
            response = await self._client.post(_CHAT_COMPLETIONS_PATH, json=body, headers=headers)
        except httpx.ConnectTimeout:
            return Failure(_timeout_evidence(TimeoutPhase.CONNECT))
        except httpx.WriteTimeout:
            return Failure(_timeout_evidence(TimeoutPhase.WRITE))
        except httpx.PoolTimeout:
            return Failure(_timeout_evidence(TimeoutPhase.POOL))
        except httpx.ReadTimeout:
            return Failure(_timeout_evidence(TimeoutPhase.READ))
        except httpx.ConnectError as exc:
            return Failure(_connection_evidence(exc))
        except httpx.HTTPError as exc:
            # Any other transport-level httpx failure this loop does not
            # name individually (protocol errors, DNS failures surfaced
            # differently, ...) is still a connection-shaped problem, not a
            # secret-carrying exception left to propagate as INTERNAL.
            return Failure(_connection_evidence(exc))

        if not (200 <= response.status_code <= 299):
            # Every non-2xx status, including a 3xx this client never
            # follows (B-2.0-35), becomes typed status evidence; its body is
            # never parsed or retained.
            return Failure(_http_status_evidence(response.status_code))

        try:
            data = response.json()
        except ValueError:
            # Also the route a 204's empty body takes: transport-successful,
            # but with no completion to parse.
            return Failure(_malformed_evidence("the provider's response body was not valid JSON"))

        if not isinstance(data, dict):
            return Failure(_malformed_evidence("the provider's response was not a JSON object"))

        if isinstance(data.get("error"), dict):
            return Failure(_malformed_evidence(_ERROR_ENVELOPE_REASON))

        message = _extract_message(data)
        if message is None:
            return Failure(_malformed_evidence(
                "the provider's response carried no usable assistant message"
            ))

        tool_calls_raw = message.get("tool_calls")
        if tool_calls_raw:
            try:
                calls = _extract_tool_call_batch(tool_calls_raw)
            except _InvalidToolCallBatch as exc:
                return Failure(_malformed_evidence(str(exc)))
            try:
                usage = _extract_usage(data)
            except _InvalidUsageCount:
                return Failure(_malformed_evidence(_INVALID_USAGE_REASON))
            return ToolCallBatch(
                calls=calls, assistant_content=_extract_content(message), usage=usage,
            )

        content = _extract_content(message)
        if content is None:
            return Failure(_malformed_evidence(
                "the provider's response carried no usable assistant text"
            ))

        try:
            usage = _extract_usage(data)
        except _InvalidUsageCount:
            return Failure(_malformed_evidence(_INVALID_USAGE_REASON))

        return Completion(content=content, usage=usage)
