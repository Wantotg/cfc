"""test_cfc_conversation_types.py — cfc/conversation_types.py: the
provider-independent conversation vocabulary and the injected responder
boundary. Generated values and in-memory objects only — no config, no flat
v1.9.1 module, no provider, no filesystem.
"""
from __future__ import annotations

import dataclasses
import datetime

import pytest

from cfc import conversation_types as ct


def aware(offset_hours: int = 0) -> datetime.datetime:
    tz = datetime.timezone(datetime.timedelta(hours=offset_hours))
    return datetime.datetime(2026, 8, 9, 12, 0, 0, tzinfo=tz)


def make_chat(**overrides) -> ct.Chat:
    fields = dict(
        id=ct.ChatId.new(),
        kind=ct.ChatKind.ORDINARY,
        title="a chat",
        created_at=aware(),
        updated_at=aware(),
    )
    fields.update(overrides)
    return ct.Chat(**fields)


def make_turn(**overrides) -> ct.Turn:
    fields = dict(
        id=ct.TurnId.new(),
        chat_id=ct.ChatId.new(),
        position=0,
        model="fixture-model",
        started_at=aware(),
    )
    fields.update(overrides)
    return ct.Turn(**fields)


def make_message(**overrides) -> ct.Message:
    fields = dict(
        id=ct.MessageId.new(),
        chat_id=ct.ChatId.new(),
        turn_id=ct.TurnId.new(),
        turn_position=0,
        role=ct.Role.USER,
        content="hello",
        created_at=aware(),
    )
    fields.update(overrides)
    return ct.Message(**fields)


# --- identities: opaque, stable, distinct -----------------------------------

def test_ids_are_distinct_and_stable():
    a, b = ct.ChatId.new(), ct.ChatId.new()
    assert a != b
    assert a == ct.ChatId(a.value)


@pytest.mark.parametrize("id_type", [ct.ChatId, ct.TurnId, ct.MessageId])
def test_id_types_cannot_be_confused_for_each_other(id_type):
    other_types = [t for t in (ct.ChatId, ct.TurnId, ct.MessageId) if t is not id_type]
    made = id_type.new()
    for other in other_types:
        assert not isinstance(made, other)


# --- immutability -------------------------------------------------------

@pytest.mark.parametrize("build,attr,value", [
    (make_chat, "title", "changed"),
    (make_turn, "model", "changed"),
    (make_message, "content", "changed"),
])
def test_records_are_frozen(build, attr, value):
    record = build()
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(record, attr, value)


def test_ids_are_frozen():
    chat_id = ct.ChatId.new()
    with pytest.raises(dataclasses.FrozenInstanceError):
        chat_id.value = "changed"  # noqa


# --- literal content: stored and returned byte-for-byte ---------------------

@pytest.mark.parametrize("content", [
    "",
    "plain text",
    "line one\nline two\n",
    "  leading and trailing whitespace  ",
    "<script>alert(1)</script>",
    "unicode: café ☃ \U0001f600",
    "a very long line " * 200,
])
def test_message_content_is_literal(content):
    message = make_message(content=content)
    assert message.content == content


def test_role_has_exactly_user_and_assistant():
    assert {member.value for member in ct.Role} == {"user", "assistant"}


# --- explicit ordering fields ---------------------------------------------

def test_turn_position_is_explicit_and_not_negative():
    turn = make_turn(position=3)
    assert turn.position == 3
    with pytest.raises(ValueError):
        make_turn(position=-1)


def test_message_turn_position_is_explicit_and_not_negative():
    message = make_message(turn_position=1)
    assert message.turn_position == 1
    with pytest.raises(ValueError):
        make_message(turn_position=-1)


# --- UTC-offset timestamps: aware only --------------------------------------

def test_naive_timestamps_are_rejected_everywhere():
    naive = datetime.datetime(2026, 8, 9, 12, 0, 0)
    with pytest.raises(ValueError):
        make_chat(created_at=naive)
    with pytest.raises(ValueError):
        make_turn(started_at=naive)
    with pytest.raises(ValueError):
        make_message(created_at=naive)


def test_non_utc_offsets_are_accepted_as_is():
    turn = make_turn(started_at=aware(offset_hours=5))
    assert turn.started_at.utcoffset() == datetime.timedelta(hours=5)


# --- optional usage: each count independently distinguishable --------------

@pytest.mark.parametrize("usage,expected", [
    (ct.Usage(input_tokens=10), (10, None, None)),
    (ct.Usage(input_tokens=10, output_tokens=5), (10, 5, None)),
    (ct.Usage(input_tokens=10, output_tokens=5, total_tokens=15), (10, 5, 15)),
    (ct.Usage(total_tokens=0), (None, None, 0)),
])
def test_usage_counts_are_independently_optional(usage, expected):
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == expected


def test_absent_usage_is_none_not_a_zeroed_object():
    turn = make_turn(
        finished_at=aware(),
        outcome=ct.CompletedOutcome(usage=None),
    )
    assert turn.outcome.usage is None


# --- B-2.0-26: all-absent Usage is not a second spelling of no usage --------

@pytest.mark.parametrize("usage_kwargs", [
    {},
    dict(input_tokens=None, output_tokens=None, total_tokens=None),
])
def test_all_absent_usage_is_not_constructible(usage_kwargs):
    with pytest.raises(ValueError):
        ct.Usage(**usage_kwargs)


def test_usage_with_at_least_one_zero_count_is_constructible():
    usage = ct.Usage(input_tokens=0, output_tokens=0, total_tokens=0)
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (0, 0, 0)


# --- terminal outcomes: exactly one per turn, three distinct shapes --------

def test_turn_outcome_variants_are_mutually_exclusive_types():
    completed = ct.CompletedOutcome()
    failed = ct.FailedOutcome(ct.FailureEvidence(ct.FailureKind.RESPONDER, "no"))
    cancelled = ct.CancelledOutcome()
    variants = [completed, failed, cancelled]
    for a in variants:
        for b in variants:
            if a is not b:
                assert type(a) is not type(b)


def test_active_turn_has_no_outcome_and_no_finish_time():
    turn = make_turn()
    assert turn.outcome is None
    assert turn.finished_at is None
    assert turn.state is ct.TurnState.ACTIVE


@pytest.mark.parametrize("outcome,expected_state", [
    (ct.CompletedOutcome(), ct.TurnState.COMPLETED),
    (ct.FailedOutcome(ct.FailureEvidence(ct.FailureKind.INTERNAL, "boom")),
     ct.TurnState.FAILED),
    (ct.CancelledOutcome(), ct.TurnState.CANCELLED),
])
def test_finished_turn_state_matches_its_outcome(outcome, expected_state):
    turn = make_turn(finished_at=aware(), outcome=outcome)
    assert turn.state is expected_state


def test_a_turn_cannot_hold_an_outcome_without_a_finish_time():
    with pytest.raises(ValueError):
        make_turn(outcome=ct.CancelledOutcome())


def test_a_turn_cannot_hold_a_finish_time_without_an_outcome():
    with pytest.raises(ValueError):
        make_turn(finished_at=aware())


def test_a_turn_record_has_exactly_one_outcome_field():
    """The type itself has no second slot a caller could use to attach a
    conflicting outcome — `Turn` carries one `outcome` attribute, not a
    list or a pair.
    """
    field_names = {f.name for f in dataclasses.fields(ct.Turn)}
    outcome_fields = {name for name in field_names if "outcome" in name}
    assert outcome_fields == {"outcome"}


# --- failure evidence: typed, no raw payload dumping ------------------------

def test_failure_kinds_are_distinct():
    assert {member.value for member in ct.FailureKind} == {
        "responder", "internal", "interrupted",
    }


def test_failure_evidence_carries_kind_and_a_short_reason():
    evidence = ct.FailureEvidence(ct.FailureKind.RESPONDER, "declared failure")
    assert evidence.kind is ct.FailureKind.RESPONDER
    assert evidence.reason == "declared failure"
    assert evidence.problem is None
    assert evidence.timeout_phase is None
    assert evidence.status_code is None


# --- failure evidence: the provider-wire taxonomy narrows RESPONDER --------

def test_provider_problems_are_distinct():
    assert {member.value for member in ct.ProviderProblem} == {
        "connection", "timeout", "http_status", "malformed_response",
    }


def test_timeout_phases_are_distinct():
    assert {member.value for member in ct.TimeoutPhase} == {
        "connect", "write", "pool", "read",
    }


def test_connection_and_malformed_problems_carry_no_extra_field():
    for problem in (ct.ProviderProblem.CONNECTION, ct.ProviderProblem.MALFORMED_RESPONSE):
        evidence = ct.FailureEvidence(ct.FailureKind.RESPONDER, "x", problem=problem)
        assert evidence.timeout_phase is None
        assert evidence.status_code is None


def test_timeout_problem_requires_a_phase():
    evidence = ct.FailureEvidence(
        ct.FailureKind.RESPONDER, "read timed out",
        problem=ct.ProviderProblem.TIMEOUT, timeout_phase=ct.TimeoutPhase.READ,
    )
    assert evidence.timeout_phase is ct.TimeoutPhase.READ
    with pytest.raises(ValueError):
        ct.FailureEvidence(ct.FailureKind.RESPONDER, "x", problem=ct.ProviderProblem.TIMEOUT)


def test_timeout_phase_is_rejected_without_the_timeout_problem():
    with pytest.raises(ValueError):
        ct.FailureEvidence(ct.FailureKind.RESPONDER, "x", timeout_phase=ct.TimeoutPhase.READ)


def test_http_status_problem_requires_a_status_code():
    evidence = ct.FailureEvidence(
        ct.FailureKind.RESPONDER, "refused",
        problem=ct.ProviderProblem.HTTP_STATUS, status_code=429,
    )
    assert evidence.status_code == 429
    with pytest.raises(ValueError):
        ct.FailureEvidence(ct.FailureKind.RESPONDER, "x", problem=ct.ProviderProblem.HTTP_STATUS)


def test_status_code_is_rejected_without_the_http_status_problem():
    with pytest.raises(ValueError):
        ct.FailureEvidence(ct.FailureKind.RESPONDER, "x", status_code=500)


# --- ChatKind: cannot express a private durable chat ------------------------

def test_chat_kind_has_exactly_one_member():
    assert list(ct.ChatKind) == [ct.ChatKind.ORDINARY]


def test_chat_kind_has_no_private_value():
    with pytest.raises(ValueError):
        ct.ChatKind("private")
    assert not hasattr(ct.ChatKind, "PRIVATE")


# --- responder protocol: each allowed result shape --------------------------

def test_completion_carries_content_and_optional_usage():
    result = ct.Completion(content="hi", usage=ct.Usage(input_tokens=1))
    assert isinstance(result, ct.Completion)
    assert result.content == "hi"
    assert result.usage.input_tokens == 1


def test_failure_result_carries_typed_evidence():
    result = ct.Failure(ct.FailureEvidence(ct.FailureKind.RESPONDER, "nope"))
    assert isinstance(result, ct.Failure)
    assert result.evidence.kind is ct.FailureKind.RESPONDER


def test_cancellation_result_carries_nothing_else():
    result = ct.Cancellation()
    assert isinstance(result, ct.Cancellation)
    assert dataclasses.fields(ct.Cancellation) == ()


def test_responder_protocol_is_structural_and_minimal():
    import asyncio
    import inspect

    class FixedResponder:
        async def respond(self, snapshot, model):
            return ct.Completion(content=f"echo:{model}")

    responder: ct.Responder = FixedResponder()
    assert inspect.iscoroutinefunction(responder.respond)
    snapshot = ct.ConversationSnapshot(chat_id=ct.ChatId.new(), messages=())
    result = asyncio.run(responder.respond(snapshot, "fixture-model"))
    assert result == ct.Completion(content="echo:fixture-model")


def test_conversation_snapshot_holds_ordered_turns_and_messages():
    chat_id = ct.ChatId.new()
    turn_id = ct.TurnId.new()
    turn = make_turn(id=turn_id, chat_id=chat_id, position=0)
    first = make_message(chat_id=chat_id, turn_id=turn_id, turn_position=0,
                          role=ct.Role.USER, content="hi")
    second = make_message(chat_id=chat_id, turn_id=turn_id, turn_position=1,
                           role=ct.Role.ASSISTANT, content="hello")
    snapshot = ct.ConversationSnapshot(chat_id=chat_id, turns=(turn,), messages=(first, second))
    assert snapshot.turns == (turn,)
    assert snapshot.messages == (first, second)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.chat_id = ct.ChatId.new()  # noqa


def test_conversation_snapshot_turns_default_to_empty():
    snapshot = ct.ConversationSnapshot(chat_id=ct.ChatId.new())
    assert snapshot.turns == ()
    assert snapshot.messages == ()


# --- context vocabulary: pure values, no I/O (Stage 5 loop 1) ---------------

def aware_dt() -> datetime.datetime:
    return aware()


def make_source(**overrides) -> ct.SourceRecord:
    fields = dict(
        category=ct.ContextCategory.PERSONA,
        name="muse.md",
        display_name="muse",
        body="hello",
        character_count=5,
        fingerprint="deadbeef",
    )
    fields.update(overrides)
    return ct.SourceRecord(**fields)


def test_context_category_has_exactly_five_members():
    assert {m.value for m in ct.ContextCategory} == {
        "system_instructions", "user_preferences", "persona", "trait", "first_message",
    }


def test_source_record_character_count_must_match_body_length():
    make_source(body="hello", character_count=5)  # does not raise
    with pytest.raises(ValueError):
        make_source(body="hello", character_count=4)


def test_source_record_is_frozen():
    record = make_source()
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.body = "changed"  # noqa


def test_context_selection_defaults_are_all_absent():
    selection = ct.ContextSelection()
    assert selection.user_preferences is None
    assert selection.persona is None
    assert selection.traits == ()
    assert selection.model is None


def test_context_selection_preserves_trait_order():
    selection = ct.ContextSelection(traits=("b.md", "a.md"))
    assert selection.traits == ("b.md", "a.md")


def test_opening_message_requires_aware_created_at():
    naive = datetime.datetime(2026, 8, 9, 12, 0, 0)
    with pytest.raises(ValueError):
        ct.OpeningMessage(source_name="muse.md", content="hi",
                           created_at=naive, fingerprint="x")
    opening = ct.OpeningMessage(source_name="muse.md", content="hi",
                                 created_at=aware_dt(), fingerprint="x")
    assert opening.content == "hi"


def test_context_plan_ordered_sources_with_nothing_selected_is_just_system_instructions():
    system = make_source(category=ct.ContextCategory.SYSTEM_INSTRUCTIONS,
                          name="sys", display_name="System Instructions")
    plan = ct.ContextPlan(system_instructions=system)
    assert plan.ordered_sources() == (system,)


def test_context_plan_ordered_sources_follows_request_order():
    system = make_source(category=ct.ContextCategory.SYSTEM_INSTRUCTIONS)
    prefs = make_source(category=ct.ContextCategory.USER_PREFERENCES, name="prefs.md")
    persona = make_source(category=ct.ContextCategory.PERSONA, name="muse.md")
    trait_a = make_source(category=ct.ContextCategory.TRAIT, name="a.md")
    trait_b = make_source(category=ct.ContextCategory.TRAIT, name="b.md")
    plan = ct.ContextPlan(
        system_instructions=system, user_preferences=prefs, persona=persona,
        traits=(trait_a, trait_b),
    )
    assert plan.ordered_sources() == (system, prefs, persona, trait_a, trait_b)


def test_context_plan_is_frozen():
    plan = ct.ContextPlan(system_instructions=make_source())
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.persona = make_source()  # noqa


# --- module boundary: no flat runtime, config, provider, or filesystem -----

def test_module_touches_no_flat_runtime_config_or_filesystem():
    import inspect
    source = inspect.getsource(ct)
    for banned in ("import sqlite3", "import config", "from config",
                   "import httpx", "open(", "Path("):
        assert banned not in source
