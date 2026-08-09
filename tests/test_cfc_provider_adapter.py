"""test_cfc_provider_adapter.py — cfc/provider_adapter.py: the bounded
OpenAI-compatible `Responder`. Every HTTP exchange goes through an injected
`httpx.MockTransport` — the explicit, deterministic seam this loop's Work
Order asks for — so connection, timeout-phase, HTTP-status, and malformed-
response translation are all proven without a real provider or a real
socket. The one cancellation test drives the real `conversation_service`
against a temporary store to prove the store-level consequence, not just
the adapter's own return value.
"""
from __future__ import annotations

import asyncio
import datetime
import inspect
import json

import httpx
import pytest

from cfc import conversation_service as service_mod
from cfc import provider_adapter
from cfc.conversation_types import (
    CancelledOutcome,
    ChatId,
    Completion,
    ConversationSnapshot,
    Failure,
    MessageId,
    ProviderProblem,
    Role,
    Message,
    Turn,
    TurnId,
    Usage,
)
from cfc.settings import ProviderSettings

API_KEY = "sk-test-do-not-leak-me"


def settings(**overrides) -> ProviderSettings:
    fields = dict(api_base="https://provider.example.test/v1", api_key=API_KEY,
                  model="fixture-model")
    fields.update(overrides)
    return ProviderSettings(**fields)


def aware() -> datetime.datetime:
    return datetime.datetime(2026, 8, 9, 12, 0, 0, tzinfo=datetime.timezone.utc)


def active_snapshot(content: str = "hello") -> ConversationSnapshot:
    chat_id = ChatId.new()
    turn_id = TurnId.new()
    turn = Turn(id=turn_id, chat_id=chat_id, position=0, model="fixture-model",
                started_at=aware())
    message = Message(id=MessageId.new(), chat_id=chat_id, turn_id=turn_id, turn_position=0,
                       role=Role.USER, content=content, created_at=aware())
    return ConversationSnapshot(chat_id=chat_id, turns=(turn,), messages=(message,))


def json_response(status_code: int, body: dict) -> httpx.Response:
    return httpx.Response(status_code, json=body)


def run(coro):
    return asyncio.run(coro)


# --- the request shape: endpoint, method, headers, exact JSON --------------

def test_sends_exactly_one_post_to_chat_completions_with_bearer_auth_and_plan_json():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return json_response(200, {
            "choices": [{"message": {"role": "assistant", "content": "hi there"}}],
        })

    transport = httpx.MockTransport(handler)

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot("hello"), "fixture-model")

    result = run(scenario())

    assert isinstance(result, Completion)
    assert result.content == "hi there"
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    assert json.loads(request.content) == {
        "model": "fixture-model",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": False,
    }


def test_makes_exactly_one_attempt_no_retry(tmp_path):
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("refused", request=request)

    transport = httpx.MockTransport(handler)

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Failure)
    assert call_count == 1


# --- successful completion: usage variants ----------------------------------

@pytest.mark.parametrize("usage_body,expected_usage", [
    ({"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
     Usage(input_tokens=4, output_tokens=6, total_tokens=10)),
    ({"prompt_tokens": 4}, Usage(input_tokens=4)),
    ({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
     Usage(input_tokens=0, output_tokens=0, total_tokens=0)),
    (None, None),
    ({}, None),
    ({"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}, None),
], ids=["complete", "partial", "zero", "omitted-key", "empty-object", "all-null"])
def test_usage_translation_covers_complete_partial_zero_and_omitted(usage_body, expected_usage):
    body = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
    if usage_body is not None:
        body["usage"] = usage_body
    transport = httpx.MockTransport(lambda request: json_response(200, body))

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Completion)
    assert result.usage == expected_usage


# --- HTTP refusal ------------------------------------------------------------

@pytest.mark.parametrize("status_code", [400, 401, 429, 500, 503])
def test_an_http_refusal_becomes_typed_status_evidence_with_no_body_stored(status_code):
    transport = httpx.MockTransport(
        lambda request: json_response(status_code, {"error": {"message": "top secret detail"}})
    )

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Failure)
    assert result.evidence.problem is ProviderProblem.HTTP_STATUS
    assert result.evidence.status_code == status_code
    assert "top secret detail" not in result.evidence.reason


# --- B-2.0-35: every non-2xx status is typed HTTP evidence, never parsed ---

@pytest.mark.parametrize("status_code", [200, 201, 204, 299])
def test_every_2xx_status_is_eligible_for_success(status_code):
    body = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}

    def handler(request: httpx.Request) -> httpx.Response:
        if status_code == 204:
            return httpx.Response(204)
        return json_response(status_code, body)

    transport = httpx.MockTransport(handler)

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    if status_code == 204:
        # transport-successful, but no completion body to parse
        assert isinstance(result, Failure)
        assert result.evidence.problem is ProviderProblem.MALFORMED_RESPONSE
    else:
        assert isinstance(result, Completion)


@pytest.mark.parametrize("status_code", [300, 301, 302, 307, 308])
def test_a_3xx_status_is_typed_http_evidence_not_malformed(status_code):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            status_code, headers={"Location": "https://attacker.example.test/steal"},
            content=b'{"choices": [{"message": {"role": "assistant", "content": "nope"}}]}',
        )

    transport = httpx.MockTransport(handler)

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Failure)
    assert result.evidence.problem is ProviderProblem.HTTP_STATUS
    assert result.evidence.status_code == status_code
    assert len(seen) == 1  # no redirect follow despite a tempting Location


# --- D-2.0-37: an in-band error envelope is named distinctly ---------------

def test_an_object_error_envelope_gets_distinct_wording_and_no_provider_text():
    transport = httpx.MockTransport(
        lambda request: json_response(200, {"error": {"message": "quota exceeded", "code": "x"}})
    )

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Failure)
    assert result.evidence.problem is ProviderProblem.MALFORMED_RESPONSE
    assert result.evidence.reason == provider_adapter._ERROR_ENVELOPE_REASON
    assert "quota exceeded" not in result.evidence.reason


@pytest.mark.parametrize("error_value", ["a string, not an object", 42, None, ["nope"]])
def test_a_non_object_error_key_falls_back_to_the_generic_unsupported_route(error_value):
    transport = httpx.MockTransport(
        lambda request: json_response(200, {"error": error_value})
    )

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Failure)
    assert result.evidence.problem is ProviderProblem.MALFORMED_RESPONSE
    assert result.evidence.reason != provider_adapter._ERROR_ENVELOPE_REASON


def test_an_ordinary_unsupported_shape_is_still_distinct_from_the_error_envelope():
    transport = httpx.MockTransport(lambda request: json_response(200, {"choices": []}))

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Failure)
    assert result.evidence.reason != provider_adapter._ERROR_ENVELOPE_REASON


# --- D-2.0-38: usage counts as whole floats or decimal strings are kept ----

@pytest.mark.parametrize("usage_body,expected_usage", [
    ({"prompt_tokens": 4.0, "completion_tokens": 6.0, "total_tokens": 10.0},
     Usage(input_tokens=4, output_tokens=6, total_tokens=10)),
    ({"prompt_tokens": "4", "completion_tokens": "6", "total_tokens": "10"},
     Usage(input_tokens=4, output_tokens=6, total_tokens=10)),
    ({"prompt_tokens": "0"}, Usage(input_tokens=0)),
    ({"prompt_tokens": 0.0}, Usage(input_tokens=0)),
    ({"prompt_tokens": 4, "completion_tokens": "6"}, Usage(input_tokens=4, output_tokens=6)),
], ids=["all-whole-floats", "all-decimal-strings", "zero-string", "zero-float", "mixed-int-and-string"])
def test_whole_floats_and_decimal_strings_are_accepted_usage_spellings(usage_body, expected_usage):
    body = {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": usage_body}
    transport = httpx.MockTransport(lambda request: json_response(200, body))

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Completion)
    assert result.usage == expected_usage


@pytest.mark.parametrize("usage_body", [
    {"prompt_tokens": True},
    {"prompt_tokens": False},
    {"prompt_tokens": -1},
    {"prompt_tokens": 2**63},
    {"prompt_tokens": 4.5},
    {"prompt_tokens": float("inf")},
    {"prompt_tokens": float("nan")},
    {"prompt_tokens": "4.0"},
    {"prompt_tokens": "-4"},
    {"prompt_tokens": " 4"},
    {"prompt_tokens": "4a"},
    {"prompt_tokens": ""},
    {"prompt_tokens": [4]},
    {"prompt_tokens": {"n": 4}},
], ids=["true", "false", "negative-int", "over-sqlite-max", "fractional-float",
        "positive-infinity", "nan", "float-shaped-string", "negative-string",
        "leading-space", "trailing-garbage", "empty-string", "list", "dict"])
def test_an_invalid_usage_count_rejects_the_whole_response_as_malformed(usage_body):
    body = {"choices": [{"message": {"role": "assistant", "content": "ok"}}], "usage": usage_body}
    # httpx's own `json=` encoding refuses non-finite floats outright
    # (`allow_nan=False`); build the body with the stdlib encoder instead so
    # inf/nan reach the adapter exactly as some non-conformant provider body
    # could send them.
    content = json.dumps(body, allow_nan=True).encode("utf-8")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=content, headers={"content-type": "application/json"})
    )

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Failure)
    assert result.evidence.problem is ProviderProblem.MALFORMED_RESPONSE
    assert result.evidence.reason == provider_adapter._INVALID_USAGE_REASON


def test_all_absent_usage_still_remains_none():
    body = {"choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}}
    transport = httpx.MockTransport(lambda request: json_response(200, body))

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Completion)
    assert result.usage is None


# --- malformed / unsupported response shape ----------------------------------

def test_invalid_json_body_is_a_malformed_response_failure():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"not json at all")
    )

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Failure)
    assert result.evidence.problem is ProviderProblem.MALFORMED_RESPONSE


@pytest.mark.parametrize("body", [
    {"choices": []},
    {"choices": [{"message": {"role": "assistant", "content": ""}}]},
    {"choices": [{"message": {"role": "assistant"}}]},
    {"choices": [{"message": {"role": "assistant", "tool_calls": [{"id": "1"}]}}]},
    {"nope": "not a chat completion shape"},
    [],
    "a bare string, not an object",
], ids=["empty-choices", "empty-content", "missing-content", "tool-call",
        "wrong-shape", "top-level-list", "top-level-string"])
def test_valid_json_with_no_usable_assistant_content_is_malformed_not_a_completion(body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=json.dumps(body).encode("utf-8"),
                               headers={"content-type": "application/json"})

    transport = httpx.MockTransport(handler)

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Failure)
    assert result.evidence.problem is ProviderProblem.MALFORMED_RESPONSE


# --- connection and phase-specific timeout translation ----------------------

@pytest.mark.parametrize("raise_exc,expected_phase", [
    (httpx.ConnectTimeout, "connect"),
    (httpx.WriteTimeout, "write"),
    (httpx.PoolTimeout, "pool"),
    (httpx.ReadTimeout, "read"),
], ids=["connect-timeout", "write-timeout", "pool-timeout", "read-timeout"])
def test_each_timeout_phase_is_translated_distinctly(raise_exc, expected_phase):
    def handler(request: httpx.Request) -> httpx.Response:
        raise raise_exc("simulated", request=request)

    transport = httpx.MockTransport(handler)

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Failure)
    assert result.evidence.problem is ProviderProblem.TIMEOUT
    assert result.evidence.timeout_phase.value == expected_phase


def test_a_connection_failure_is_translated_distinctly_from_a_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Failure)
    assert result.evidence.problem is ProviderProblem.CONNECTION
    assert result.evidence.timeout_phase is None
    assert result.evidence.status_code is None


def test_the_configured_timeouts_give_read_a_longer_budget_than_connect():
    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(
            settings(), transport=httpx.MockTransport(lambda r: json_response(200, {}))
        ) as adapter:
            timeout = adapter._client.timeout
            return timeout

    timeout = run(scenario())
    assert timeout.read > timeout.connect
    assert timeout.connect is not None and timeout.write is not None and timeout.pool is not None


# --- redaction: no secret, header, or body ever reaches stored evidence ----

@pytest.mark.parametrize("scenario_name", ["http-status", "malformed", "timeout", "connection"])
def test_no_evidence_ever_contains_the_api_key_or_a_response_body(scenario_name):
    if scenario_name == "http-status":
        transport = httpx.MockTransport(
            lambda r: json_response(401, {"error": f"bad key {API_KEY}"})
        )
    elif scenario_name == "malformed":
        transport = httpx.MockTransport(lambda r: httpx.Response(200, content=b"{not json"))
    elif scenario_name == "timeout":
        def handler(request):
            raise httpx.ReadTimeout("simulated", request=request)
        transport = httpx.MockTransport(handler)
    else:
        def handler(request):
            raise httpx.ConnectError(f"failed with key {API_KEY}", request=request)
        transport = httpx.MockTransport(handler)

    async def scenario():
        async with provider_adapter.OpenAICompatibleAdapter(settings(), transport=transport) as adapter:
            return await adapter.respond(active_snapshot(), "fixture-model")

    result = run(scenario())
    assert isinstance(result, Failure)
    evidence_text = repr(result.evidence)
    assert API_KEY not in evidence_text


# --- cancellation: proven at the service/store level, not just the adapter -

def test_cancellation_in_flight_is_stored_as_cancelled_with_no_partial_message_and_reraises(tmp_path):
    in_flight = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        in_flight.set()
        await asyncio.Event().wait()  # hangs until the awaiting task is cancelled
        return json_response(200, {  # pragma: no cover
            "choices": [{"message": {"role": "assistant", "content": "too late"}}],
        })

    transport = httpx.MockTransport(handler)

    async def scenario():
        service = service_mod.open_service(tmp_path / "chat.db")
        try:
            chat = service.create_chat("c")
            async with provider_adapter.OpenAICompatibleAdapter(
                settings(), transport=transport
            ) as adapter:
                task = asyncio.ensure_future(
                    service.send_turn(chat.id, "fixture-model", "hello", adapter)
                )
                await in_flight.wait()
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task

            turn_id = service.snapshot(chat.id).messages[0].turn_id
            turn = service.get_turn(turn_id)
            assert isinstance(turn.outcome, CancelledOutcome)
            assert [m.role for m in service.snapshot(chat.id).messages] == [Role.USER]
        finally:
            service.close()

    run(scenario())


# --- module boundary: no SQLite, config, or provider SDK -------------------

def test_module_touches_no_sqlite_config_or_provider_sdk():
    source = inspect.getsource(provider_adapter)
    for banned in ("import sqlite3", "import config", "from config", "import openai"):
        assert banned not in source


def test_respond_is_a_coroutine_function():
    assert inspect.iscoroutinefunction(provider_adapter.OpenAICompatibleAdapter.respond)
