"""test_cfc_provider_wire.py — cfc/provider_wire.py: the pure conversion
from a stored `ConversationSnapshot` to an OpenAI-compatible request plan
(Q-2.0-29). Fixtures build turns and messages directly — no store, no
adapter, no network — so a deliberately contradictory snapshot can be
constructed and proven to refuse before any HTTP work.
"""
from __future__ import annotations

import datetime

import pytest

from cfc import provider_wire as wire
from cfc.conversation_types import (
    CancelledOutcome,
    ChatId,
    CompletedOutcome,
    ContextCategory,
    ContextPlan,
    ConversationSnapshot,
    FailedOutcome,
    FailureEvidence,
    FailureKind,
    Message,
    MessageId,
    OpeningMessage,
    Role,
    SourceRecord,
    Turn,
    TurnId,
    TurnState,
    Usage,
)


def aware() -> datetime.datetime:
    return datetime.datetime(2026, 8, 9, 12, 0, 0, tzinfo=datetime.timezone.utc)


def make_source(category, body="body", name="source") -> SourceRecord:
    return SourceRecord(category=category, name=name, display_name=name,
                         body=body, character_count=len(body), fingerprint="fp")


def empty_context() -> ContextPlan:
    """A `ContextPlan` with nothing selected — the minimum every fixture
    needs, since `build_request_plan` always reads `context.ordered_sources()`.
    """
    return ContextPlan(system_instructions=make_source(
        ContextCategory.SYSTEM_INSTRUCTIONS, body="sys", name="sys",
    ))


def make_opening(content="opening text") -> OpeningMessage:
    return OpeningMessage(source_name="muse.md", content=content,
                           created_at=aware(), fingerprint="fp")


#: What `empty_context()` alone contributes to `plan.messages` — one leading
#: `system` message, always, since a `ContextPlan` always resolves at least
#: System Instructions. Every assertion below that predates the context
#: prefix (Stage 5 loop 1) is unrelated to it and just needs this prepended;
#: the prefix's own exact shape and ordering are proven separately below.
_CONTEXT_PREFIX = (wire.WireMessage(role="system", content="sys"),)


def user_message(chat_id, turn_id, content="q") -> Message:
    return Message(id=MessageId.new(), chat_id=chat_id, turn_id=turn_id, turn_position=0,
                   role=Role.USER, content=content, created_at=aware())


def assistant_message(chat_id, turn_id, content="a") -> Message:
    return Message(id=MessageId.new(), chat_id=chat_id, turn_id=turn_id, turn_position=1,
                   role=Role.ASSISTANT, content=content, created_at=aware())


def completed(chat_id, position, user="q", assistant="a"):
    turn_id = TurnId.new()
    turn = Turn(id=turn_id, chat_id=chat_id, position=position, model="m",
                started_at=aware(), finished_at=aware(), outcome=CompletedOutcome())
    return turn, [user_message(chat_id, turn_id, user), assistant_message(chat_id, turn_id, assistant)]


def failed(chat_id, position, user="q", kind=FailureKind.RESPONDER):
    turn_id = TurnId.new()
    turn = Turn(id=turn_id, chat_id=chat_id, position=position, model="m",
                started_at=aware(), finished_at=aware(),
                outcome=FailedOutcome(FailureEvidence(kind, "x")))
    return turn, [user_message(chat_id, turn_id, user)]


def cancelled(chat_id, position, user="q"):
    turn_id = TurnId.new()
    turn = Turn(id=turn_id, chat_id=chat_id, position=position, model="m",
                started_at=aware(), finished_at=aware(), outcome=CancelledOutcome())
    return turn, [user_message(chat_id, turn_id, user)]


def active(chat_id, position, user="q"):
    turn_id = TurnId.new()
    turn = Turn(id=turn_id, chat_id=chat_id, position=position, model="m", started_at=aware())
    return turn, [user_message(chat_id, turn_id, user)]


def build_snapshot(chat_id, turn_message_pairs) -> ConversationSnapshot:
    turns = tuple(t for t, _ in turn_message_pairs)
    messages = tuple(m for _, msgs in turn_message_pairs for m in msgs)
    return ConversationSnapshot(chat_id=chat_id, turns=turns, messages=messages)


# --- the inclusion/omission rule --------------------------------------------

def test_both_messages_of_a_completed_turn_go_on_the_wire():
    chat_id = ChatId.new()
    turn, msgs = completed(chat_id, 0, user="the question", assistant="the answer")
    snapshot = build_snapshot(chat_id, [(turn, msgs)])

    plan = wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")

    assert plan.model == "fixture-model"
    assert plan.stream is False
    assert plan.messages == _CONTEXT_PREFIX + (
        wire.WireMessage(role="user", content="the question"),
        wire.WireMessage(role="assistant", content="the answer"),
    )
    assert plan.omitted == ()


@pytest.mark.parametrize("build,expected_state", [
    (lambda chat_id: failed(chat_id, 0, kind=FailureKind.RESPONDER), TurnState.FAILED),
    (lambda chat_id: failed(chat_id, 0, kind=FailureKind.INTERNAL), TurnState.FAILED),
    (lambda chat_id: failed(chat_id, 0, kind=FailureKind.INTERRUPTED), TurnState.FAILED),
    (lambda chat_id: cancelled(chat_id, 0), TurnState.CANCELLED),
], ids=["responder-failed", "internal-failed", "interrupted-failed", "cancelled"])
def test_the_user_only_message_of_an_unsuccessful_turn_is_omitted_not_sent(build, expected_state):
    chat_id = ChatId.new()
    turn, msgs = build(chat_id)
    snapshot = build_snapshot(chat_id, [(turn, msgs)])

    plan = wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")

    assert plan.messages == _CONTEXT_PREFIX
    assert plan.omitted == (wire.OmittedTurn(turn_id=turn.id, state=expected_state),)


def test_the_current_active_turns_user_message_is_included():
    chat_id = ChatId.new()
    turn, msgs = active(chat_id, 0, user="what now")
    snapshot = build_snapshot(chat_id, [(turn, msgs)])

    plan = wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")

    assert plan.messages == _CONTEXT_PREFIX + (wire.WireMessage(role="user", content="what now"),)
    assert plan.omitted == ()


def test_when_every_earlier_turn_failed_the_request_is_one_message_not_empty_or_refused():
    chat_id = ChatId.new()
    failed1_turn, failed1_msgs = failed(chat_id, 0, user="q1")
    failed2_turn, failed2_msgs = cancelled(chat_id, 1, user="q2")
    active_turn, active_msgs = active(chat_id, 2, user="q3")
    snapshot = build_snapshot(chat_id, [
        (failed1_turn, failed1_msgs), (failed2_turn, failed2_msgs), (active_turn, active_msgs),
    ])

    plan = wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")

    assert plan.messages == _CONTEXT_PREFIX + (wire.WireMessage(role="user", content="q3"),)
    assert plan.omitted == (
        wire.OmittedTurn(turn_id=failed1_turn.id, state=TurnState.FAILED),
        wire.OmittedTurn(turn_id=failed2_turn.id, state=TurnState.CANCELLED),
    )


def test_a_mixed_history_produces_the_exact_expected_plan_and_omission_order():
    chat_id = ChatId.new()
    t0, m0 = completed(chat_id, 0, user="q0", assistant="a0")
    t1, m1 = failed(chat_id, 1, user="q1")
    t2, m2 = completed(chat_id, 2, user="q2", assistant="a2")
    t3, m3 = cancelled(chat_id, 3, user="q3")
    t4, m4 = active(chat_id, 4, user="q4")
    snapshot = build_snapshot(chat_id, [(t0, m0), (t1, m1), (t2, m2), (t3, m3), (t4, m4)])

    plan = wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")

    assert plan.messages == _CONTEXT_PREFIX + (
        wire.WireMessage(role="user", content="q0"),
        wire.WireMessage(role="assistant", content="a0"),
        wire.WireMessage(role="user", content="q2"),
        wire.WireMessage(role="assistant", content="a2"),
        wire.WireMessage(role="user", content="q4"),
    )
    assert plan.omitted == (
        wire.OmittedTurn(turn_id=t1.id, state=TurnState.FAILED),
        wire.OmittedTurn(turn_id=t3.id, state=TurnState.CANCELLED),
    )


def test_an_empty_history_produces_an_empty_plan_with_no_omissions():
    chat_id = ChatId.new()
    snapshot = ConversationSnapshot(chat_id=chat_id)
    plan = wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")
    assert plan.messages == _CONTEXT_PREFIX
    assert plan.omitted == ()


# --- purity: the snapshot is read, never mutated ----------------------------

def test_conversion_does_not_mutate_the_snapshot():
    chat_id = ChatId.new()
    turn, msgs = completed(chat_id, 0)
    snapshot = build_snapshot(chat_id, [(turn, msgs)])
    before_turns, before_messages = snapshot.turns, snapshot.messages

    wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")

    assert snapshot.turns == before_turns
    assert snapshot.messages == before_messages


# --- refusal: a malformed or incoherent snapshot never reaches an adapter --

def test_an_orphaned_message_referencing_an_unknown_turn_refuses():
    chat_id = ChatId.new()
    turn, msgs = active(chat_id, 0)
    orphan = user_message(chat_id, TurnId.new(), "orphan")
    snapshot = ConversationSnapshot(chat_id=chat_id, turns=(turn,), messages=(*msgs, orphan))

    with pytest.raises(wire.MalformedSnapshot):
        wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")


def test_a_message_from_a_different_chat_refuses():
    chat_id = ChatId.new()
    other_chat_id = ChatId.new()
    turn, msgs = active(chat_id, 0)
    stray = user_message(other_chat_id, turn.id, "stray")
    snapshot = ConversationSnapshot(chat_id=chat_id, turns=(turn,), messages=(msgs[0], stray))

    with pytest.raises(wire.MalformedSnapshot):
        wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")


def test_a_completed_turn_missing_its_assistant_message_refuses():
    chat_id = ChatId.new()
    turn_id = TurnId.new()
    turn = Turn(id=turn_id, chat_id=chat_id, position=0, model="m",
                started_at=aware(), finished_at=aware(), outcome=CompletedOutcome())
    snapshot = ConversationSnapshot(
        chat_id=chat_id, turns=(turn,), messages=(user_message(chat_id, turn_id),),
    )

    with pytest.raises(wire.MalformedSnapshot):
        wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")


def test_a_failed_turn_with_an_unexpected_assistant_message_refuses():
    chat_id = ChatId.new()
    turn_id = TurnId.new()
    turn = Turn(id=turn_id, chat_id=chat_id, position=0, model="m",
                started_at=aware(), finished_at=aware(),
                outcome=FailedOutcome(FailureEvidence(FailureKind.RESPONDER, "x")))
    snapshot = ConversationSnapshot(
        chat_id=chat_id, turns=(turn,),
        messages=(user_message(chat_id, turn_id), assistant_message(chat_id, turn_id)),
    )

    with pytest.raises(wire.MalformedSnapshot):
        wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")


def test_two_active_turns_refuse():
    chat_id = ChatId.new()
    t0, m0 = active(chat_id, 0, user="q0")
    t1, m1 = active(chat_id, 1, user="q1")
    snapshot = build_snapshot(chat_id, [(t0, m0), (t1, m1)])

    with pytest.raises(wire.MalformedSnapshot):
        wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")


def test_an_active_turn_that_is_not_the_most_recent_refuses():
    chat_id = ChatId.new()
    active_turn, active_msgs = active(chat_id, 0, user="q0")
    later_completed, later_msgs = completed(chat_id, 1, user="q1", assistant="a1")
    snapshot = build_snapshot(chat_id, [(active_turn, active_msgs), (later_completed, later_msgs)])

    with pytest.raises(wire.MalformedSnapshot):
        wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")


def test_turns_out_of_position_order_refuse():
    chat_id = ChatId.new()
    t0, m0 = completed(chat_id, 1, user="q0", assistant="a0")
    t1, m1 = active(chat_id, 0, user="q1")
    snapshot = ConversationSnapshot(chat_id=chat_id, turns=(t0, t1), messages=(*m0, *m1))

    with pytest.raises(wire.MalformedSnapshot):
        wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")


def test_duplicate_turn_positions_refuse():
    chat_id = ChatId.new()
    t0, m0 = completed(chat_id, 0, user="q0", assistant="a0")
    t1, m1 = active(chat_id, 0, user="q1")
    snapshot = ConversationSnapshot(chat_id=chat_id, turns=(t0, t1), messages=(*m0, *m1))

    with pytest.raises(wire.MalformedSnapshot):
        wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")


def test_messages_out_of_canonical_order_refuse():
    chat_id = ChatId.new()
    turn, msgs = completed(chat_id, 0, user="q0", assistant="a0")
    reversed_msgs = tuple(reversed(msgs))
    snapshot = ConversationSnapshot(chat_id=chat_id, turns=(turn,), messages=reversed_msgs)

    with pytest.raises(wire.MalformedSnapshot):
        wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")


# --- the named context prefix and frozen opening (Stage 5 loop 1) ----------

def full_context() -> ContextPlan:
    return ContextPlan(
        system_instructions=make_source(ContextCategory.SYSTEM_INSTRUCTIONS, body="sys", name="sys"),
        user_preferences=make_source(ContextCategory.USER_PREFERENCES, body="prefs", name="prefs.md"),
        persona=make_source(ContextCategory.PERSONA, body="persona", name="muse.md"),
        traits=(
            make_source(ContextCategory.TRAIT, body="dry", name="dry.md"),
            make_source(ContextCategory.TRAIT, body="warm", name="warm.md"),
        ),
    )


def test_context_prefix_is_system_instructions_prefs_persona_traits_in_order():
    chat_id = ChatId.new()
    turn, msgs = active(chat_id, 0, user="hi")
    snapshot = build_snapshot(chat_id, [(turn, msgs)])

    plan = wire.build_request_plan(full_context(), None, snapshot, "fixture-model")

    assert plan.messages[:4] == (
        wire.WireMessage(role="system", content="sys"),
        wire.WireMessage(role="system", content="prefs"),
        wire.WireMessage(role="system", content="persona"),
        wire.WireMessage(role="system", content="dry"),
    )
    assert plan.messages[4] == wire.WireMessage(role="system", content="warm")
    assert plan.messages[5] == wire.WireMessage(role="user", content="hi")


def test_a_blank_optional_category_emits_no_message_never_a_blank_one():
    chat_id = ChatId.new()
    turn, msgs = active(chat_id, 0, user="hi")
    snapshot = build_snapshot(chat_id, [(turn, msgs)])

    plan = wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")

    assert plan.messages == (
        wire.WireMessage(role="system", content="sys"),
        wire.WireMessage(role="user", content="hi"),
    )
    for message in plan.messages:
        assert message.content != ""


def test_frozen_opening_lands_as_one_assistant_message_after_context():
    chat_id = ChatId.new()
    turn, msgs = active(chat_id, 0, user="hi")
    snapshot = build_snapshot(chat_id, [(turn, msgs)])
    opening = make_opening("Hello, I am Muse.")

    plan = wire.build_request_plan(empty_context(), opening, snapshot, "fixture-model")

    assert plan.messages == (
        wire.WireMessage(role="system", content="sys"),
        wire.WireMessage(role="assistant", content="Hello, I am Muse."),
        wire.WireMessage(role="user", content="hi"),
    )


def test_no_opening_means_no_extra_assistant_message():
    chat_id = ChatId.new()
    turn, msgs = active(chat_id, 0, user="hi")
    snapshot = build_snapshot(chat_id, [(turn, msgs)])

    plan = wire.build_request_plan(empty_context(), None, snapshot, "fixture-model")

    assert all(m.role != "assistant" for m in plan.messages)


def test_full_context_plus_opening_precedes_stored_turn_history_exactly():
    chat_id = ChatId.new()
    t0, m0 = completed(chat_id, 0, user="q0", assistant="a0")
    snapshot = build_snapshot(chat_id, [(t0, m0)])
    opening = make_opening("opening")

    plan = wire.build_request_plan(full_context(), opening, snapshot, "fixture-model")

    assert plan.messages == (
        wire.WireMessage(role="system", content="sys"),
        wire.WireMessage(role="system", content="prefs"),
        wire.WireMessage(role="system", content="persona"),
        wire.WireMessage(role="system", content="dry"),
        wire.WireMessage(role="system", content="warm"),
        wire.WireMessage(role="assistant", content="opening"),
        wire.WireMessage(role="user", content="q0"),
        wire.WireMessage(role="assistant", content="a0"),
    )


def test_malformed_snapshot_refuses_before_context_or_opening_matter():
    """A malformed stored history refuses the same way regardless of what
    context or opening would otherwise have been prepended — validation
    happens before any of that is even read.
    """
    chat_id = ChatId.new()
    turn, msgs = active(chat_id, 0)
    orphan = user_message(chat_id, TurnId.new(), "orphan")
    snapshot = ConversationSnapshot(chat_id=chat_id, turns=(turn,), messages=(*msgs, orphan))

    with pytest.raises(wire.MalformedSnapshot):
        wire.build_request_plan(full_context(), make_opening(), snapshot, "fixture-model")


def test_context_and_opening_are_not_mutated():
    chat_id = ChatId.new()
    turn, msgs = active(chat_id, 0, user="hi")
    snapshot = build_snapshot(chat_id, [(turn, msgs)])
    context = full_context()
    opening = make_opening()

    wire.build_request_plan(context, opening, snapshot, "fixture-model")

    assert context == full_context()
    assert opening == make_opening()


# --- module boundary: no network, no SQLite, no config ----------------------

def test_module_touches_no_network_sqlite_or_config():
    import inspect
    source = inspect.getsource(wire)
    for banned in ("import httpx", "import sqlite3", "import config", "from config", "open("):
        assert banned not in source
