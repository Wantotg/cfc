"""provider_adapter.py — the bounded OpenAI-compatible responder
(`cfc.conversation_types.Responder`) that makes the Stage 3 kernel usable
with one real, non-streaming chat provider over `httpx`.

`OpenAICompatibleAdapter` is constructed from immutable `ProviderSettings`
(`cfc.settings`) and, in tests only, an injected `httpx` transport — never a
store, a database path, a configuration module, the vault, an authority
object, or a UI callback. It makes exactly one attempt per `respond` call:
no retry, no model fallback, no provider discovery, and no request editing
beyond what `cfc.provider_wire.build_request_plan` already decided.

Every way a call can end becomes one of `Completion`, `Failure`, or an
`asyncio.CancelledError` left to propagate — never a raw `httpx` exception,
a provider dictionary, a header, a full request, or a full response body
reaching the caller or (later) stored evidence. `FailureEvidence.problem`
narrows what went wrong (`CONNECTION`, `TIMEOUT` with `timeout_phase`,
`HTTP_STATUS` with `status_code`, or `MALFORMED_RESPONSE`); `reason` is
always a short, cfc-authored phrase, never the provider's or `httpx`'s own
message text.
"""
from __future__ import annotations

import httpx

from cfc.conversation_types import (
    Completion,
    Failure,
    FailureEvidence,
    FailureKind,
    ProviderProblem,
    ResponderResult,
    TimeoutPhase,
    Usage,
)
from cfc.provider_wire import RequestPlan, build_request_plan
from cfc.settings import ProviderSettings

#: Distinct timeout budgets per `httpx` phase. `READ` is longer than the
#: others: a model may legitimately take longer to answer than a dead
#: endpoint needs to prove it is unreachable.
_CONNECT_TIMEOUT_S = 10.0
_WRITE_TIMEOUT_S = 10.0
_POOL_TIMEOUT_S = 10.0
_READ_TIMEOUT_S = 90.0

_CHAT_COMPLETIONS_PATH = "/chat/completions"


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


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _extract_usage(body: dict) -> Usage | None:
    """`None` unless at least one count is present and numeric — an
    all-missing or entirely absent usage object must not attempt to build a
    `Usage` (B-2.0-26: that spelling is not constructible).
    """
    raw = body.get("usage")
    if not isinstance(raw, dict):
        return None
    input_tokens = _int_or_none(raw.get("prompt_tokens"))
    output_tokens = _int_or_none(raw.get("completion_tokens"))
    total_tokens = _int_or_none(raw.get("total_tokens"))
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    return Usage(input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens)


def _extract_content(body: dict) -> str | None:
    """The literal assistant text, or `None` if the shape is not one this
    loop can use — missing/empty content, a tool call, or anything else
    that is not a plain string message.
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
    if message.get("tool_calls"):
        return None
    content = message.get("content")
    if not isinstance(content, str) or content == "":
        return None
    return content


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
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OpenAICompatibleAdapter":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def respond(self, snapshot, model: str) -> ResponderResult:
        """Build the request plan, make exactly one HTTP attempt, and
        translate the outcome. `provider_wire.MalformedSnapshot` — the
        stored history itself is incoherent — is deliberately not caught
        here: it is not a provider-wire failure, so it propagates to
        `conversation_service`'s generic internal-failure handling instead
        of being reported as if the provider had refused something.

        Task cancellation while `self._client.post` is in flight is
        likewise not caught: it propagates so `conversation_service` can
        finalise the turn as `CancelledOutcome` itself.
        """
        plan: RequestPlan = build_request_plan(snapshot, model)
        body = {
            "model": plan.model,
            "messages": [{"role": message.role, "content": message.content}
                         for message in plan.messages],
            "stream": plan.stream,
        }
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

        if response.status_code >= 400:
            return Failure(_http_status_evidence(response.status_code))

        try:
            data = response.json()
        except ValueError:
            return Failure(_malformed_evidence("the provider's response body was not valid JSON"))

        if not isinstance(data, dict):
            return Failure(_malformed_evidence("the provider's response was not a JSON object"))

        content = _extract_content(data)
        if content is None:
            return Failure(_malformed_evidence(
                "the provider's response carried no usable assistant text"
            ))

        return Completion(content=content, usage=_extract_usage(data))
