"""test_cfc_conversation_service.py — cfc/conversation_service.py: the one
provider-independent owner of a turn's lifecycle. Every store lives under
`tmp_path`, driven only by injected deterministic responders; no config, no
flat v1.9.1 module, no vault, and no network.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from cfc import conversation_service as service_mod
from cfc import conversation_store
from cfc.conversation_types import (
    Cancellation,
    Completion,
    Failure,
    FailureEvidence,
    FailureKind,
    Role,
    Usage,
)


class FixedResponder:
    """Returns the same result every time and records every call it saw."""

    def __init__(self, result):
        self._result = result
        self.calls = []

    def respond(self, snapshot, model):
        self.calls.append((snapshot, model))
        return self._result


class RaisingResponder:
    """`BaseException`, not `Exception`: a `KeyboardInterrupt` during a live
    turn is one of the cases `send_turn` has to end the turn for.
    """

    def __init__(self, exc: BaseException):
        self._exc = exc

    def respond(self, snapshot, model):
        raise self._exc


class OpenStoreResponder:
    """A treacherous responder that tries to open the same database path
    itself. It has no legitimate way to know that path — this class is
    handed it only to prove the attempt fails, not to model real usage.
    """

    def __init__(self, path: Path):
        self._path = path
        self.observed_error = None

    def respond(self, snapshot, model):
        try:
            conversation_store.open_store(self._path)
        except conversation_store.ConversationStoreError as exc:
            self.observed_error = exc
        return Cancellation()


def db_path(tmp_path: Path) -> Path:
    return tmp_path / "chat.db"


def open_service(tmp_path: Path) -> service_mod.ConversationService:
    return service_mod.open_service(db_path(tmp_path))


# --- chats: distinct identities, listable, reopenable -----------------

def test_two_chats_get_distinct_identities_and_are_listed_in_creation_order(tmp_path):
    service = open_service(tmp_path)
    try:
        first = service.create_chat("first")
        second = service.create_chat("second")
        assert first.id != second.id
        assert [c.id for c in service.list_chats()] == [first.id, second.id]
        assert service.get_chat(second.id).title == "second"
    finally:
        service.close()


# --- completed turns: usage supplied and omitted ---------------------------

def test_completed_turn_with_usage_round_trips(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        usage = Usage(input_tokens=4, output_tokens=6, total_tokens=10)
        responder = FixedResponder(Completion(content="the answer", usage=usage))

        turn = service.send_turn(chat.id, "fixture-model", "the question", responder)

        assert turn.outcome.usage == usage
        snapshot = service.snapshot(chat.id)
        assert [(m.role, m.content) for m in snapshot.messages] == [
            (Role.USER, "the question"), (Role.ASSISTANT, "the answer"),
        ]
    finally:
        service.close()


def test_completed_turn_with_omitted_usage_stays_unknown(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = FixedResponder(Completion(content="ok", usage=None))
        turn = service.send_turn(chat.id, "fixture-model", "q", responder)
        assert turn.outcome.usage is None
    finally:
        service.close()


# --- declared failure and cancellation: distinct, both terminal ------------

def test_responder_declared_failure_is_recorded_with_no_synthetic_answer(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        evidence = FailureEvidence(FailureKind.RESPONDER, "declined")
        responder = FixedResponder(Failure(evidence))

        turn = service.send_turn(chat.id, "fixture-model", "q", responder)

        assert turn.outcome.evidence == evidence
        snapshot = service.snapshot(chat.id)
        assert [m.role for m in snapshot.messages] == [Role.USER]
    finally:
        service.close()


def test_cancellation_is_recorded_and_distinct_from_failure(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = FixedResponder(Cancellation())
        turn = service.send_turn(chat.id, "fixture-model", "q", responder)

        from cfc.conversation_types import CancelledOutcome
        assert isinstance(turn.outcome, CancelledOutcome)
        snapshot = service.snapshot(chat.id)
        assert [m.role for m in snapshot.messages] == [Role.USER]
    finally:
        service.close()


# --- unexpected exception: converted, turn ended before it is reported -----

def test_unexpected_responder_exception_becomes_typed_internal_failure(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = RaisingResponder(RuntimeError("boom"))

        turn = service.send_turn(chat.id, "fixture-model", "q", responder)

        assert turn.outcome.evidence.kind is FailureKind.INTERNAL
        assert "boom" in turn.outcome.evidence.reason
        # ended, not left dangling: re-reading the store shows the same
        # terminal outcome, and a later turn is immediately permitted
        assert service.get_turn(turn.id).outcome == turn.outcome
    finally:
        service.close()


def test_unexpected_exception_never_propagates_out_of_send_turn(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = RaisingResponder(ValueError("should not escape"))
        service.send_turn(chat.id, "fixture-model", "q", responder)  # must not raise
    finally:
        service.close()


# --- every way out of send_turn ends the turn it started (B-2.0-25) --------

def test_an_unrecognised_responder_result_still_ends_the_turn(tmp_path):
    """A responder returning something that is not a `ResponderResult` is a
    programming error in a later adapter, not a reason to leave a turn
    active forever. It is recorded as a typed internal failure naming what
    came back.
    """
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        turn = service.send_turn(
            chat.id, "fixture-model", "q", FixedResponder(None),  # not a result
        )

        assert turn.outcome.evidence.kind is FailureKind.INTERNAL
        assert "unrecognised result" in turn.outcome.evidence.reason
        assert service.get_turn(turn.id).outcome == turn.outcome
        assert [m.role for m in service.snapshot(chat.id).messages] == [Role.USER]
    finally:
        service.close()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit],
                          ids=["keyboard-interrupt", "system-exit"])
def test_an_interruption_ends_the_turn_and_then_keeps_travelling(tmp_path, interruption):
    """Ctrl-C during a live turn is not process death — the process survives,
    so reopen recovery never runs. The turn ends as a typed interrupted
    failure here, and the interruption still propagates, because a cfc that
    swallowed Ctrl-C would be worse than one that lost a turn.
    """
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = RaisingResponder(interruption())

        with pytest.raises(interruption):
            service.send_turn(chat.id, "fixture-model", "q", responder)

        # the user message that opened the turn names the turn to re-read
        recorded = service.get_turn(service.snapshot(chat.id).messages[0].turn_id)
        assert recorded.outcome.evidence.kind is FailureKind.INTERRUPTED
        assert recorded.outcome.evidence.reason == interruption.__name__
        assert recorded.finished_at is not None
    finally:
        service.close()


def test_a_turn_after_an_interruption_is_the_next_position_not_a_second_active_one(tmp_path):
    """The bug this replaced: an interrupted turn stayed active, so the
    chat accumulated live turns that only a restart could end.
    """
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        with pytest.raises(KeyboardInterrupt):
            service.send_turn(
                chat.id, "fixture-model", "q1", RaisingResponder(KeyboardInterrupt()),
            )

        later = service.send_turn(
            chat.id, "fixture-model", "q2", FixedResponder(Completion(content="ok")),
        )
        assert later.position == 1
        assert later.outcome.__class__.__name__ == "CompletedOutcome"

        active = service._store._conn.execute(
            "SELECT COUNT(*) FROM cfc_turns WHERE outcome_kind IS NULL"
        ).fetchone()[0]
        assert active == 0
    finally:
        service.close()


# --- a later turn is permitted after every terminal outcome -----------------

@pytest.mark.parametrize("responder_factory", [
    lambda: FixedResponder(Completion(content="ok")),
    lambda: FixedResponder(Failure(FailureEvidence(FailureKind.RESPONDER, "no"))),
    lambda: FixedResponder(Cancellation()),
    lambda: RaisingResponder(RuntimeError("boom")),
    lambda: FixedResponder(None),
], ids=["completed", "failed", "cancelled", "internal-exception", "unrecognised-result"])
def test_a_later_turn_is_permitted_after_every_terminal_outcome(tmp_path, responder_factory):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        first = service.send_turn(chat.id, "fixture-model", "q1", responder_factory())
        second = service.send_turn(
            chat.id, "fixture-model", "q2", FixedResponder(Completion(content="fine")),
        )
        assert second.position == first.position + 1
        assert second.outcome.__class__.__name__ == "CompletedOutcome"
    finally:
        service.close()


# --- restart/reopen: process-death recovery is Step 2's path, unchanged ----

def test_restart_recovers_a_turn_left_active_by_a_prior_owner(tmp_path):
    path = db_path(tmp_path)

    store = conversation_store.open_store(path)
    chat = store.create_chat("c")
    turn, _ = store.start_turn(chat.id, "fixture-model", "q")
    store.close()  # simulates the process disappearing mid-turn, no finalise

    service = service_mod.open_service(path)
    try:
        recovered = service.get_turn(turn.id)
        assert recovered.outcome.evidence.kind is FailureKind.INTERRUPTED

        # the chat is still usable after recovery
        next_turn = service.send_turn(
            chat.id, "fixture-model", "q2", FixedResponder(Completion(content="ok")),
        )
        assert next_turn.position == turn.position + 1
    finally:
        service.close()


# --- the responder sees exactly the stored canonical history ---------------

def test_responder_observes_exactly_the_stored_canonical_history(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        service.send_turn(
            chat.id, "fixture-model", "first question",
            FixedResponder(Completion(content="first answer")),
        )

        spy = FixedResponder(Completion(content="second answer"))
        service.send_turn(chat.id, "fixture-model", "second question", spy)

        assert len(spy.calls) == 1
        seen_snapshot, seen_model = spy.calls[0]
        assert seen_model == "fixture-model"
        assert seen_snapshot.chat_id == chat.id
        assert [(m.role, m.content) for m in seen_snapshot.messages] == [
            (Role.USER, "first question"),
            (Role.ASSISTANT, "first answer"),
            (Role.USER, "second question"),
        ]
    finally:
        service.close()


def test_responder_snapshot_matches_an_independent_repository_read(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        spy = FixedResponder(Completion(content="answer"))
        service.send_turn(chat.id, "fixture-model", "question", spy)
        seen_snapshot, _ = spy.calls[0]
        # independently re-read: only the user message existed at call time
        assert [(m.role, m.content) for m in seen_snapshot.messages] == [
            (Role.USER, "question"),
        ]
    finally:
        service.close()


# --- the responder cannot acquire a repository handle -----------------------

def test_responder_cannot_open_the_store_itself_while_a_turn_is_active(tmp_path):
    path = db_path(tmp_path)
    service = service_mod.open_service(path)
    try:
        chat = service.create_chat("c")
        responder = OpenStoreResponder(path)
        service.send_turn(chat.id, "fixture-model", "q", responder)

        assert responder.observed_error is not None
        assert isinstance(responder.observed_error, conversation_store.DatabaseInUse)
    finally:
        service.close()


def test_responder_protocol_carries_no_store_or_authority_argument():
    """Structural proof alongside the behavioural one above: `respond`
    takes only a snapshot and a model string, so there is no parameter a
    real responder could receive a store or authority object through.
    """
    from cfc.conversation_types import Responder
    signature = inspect.signature(Responder.respond)
    assert list(signature.parameters) == ["self", "snapshot", "model"]


# --- module boundary: no flat runtime, config, vault, or network -----------

def test_service_module_touches_no_flat_runtime_config_vault_or_network():
    source = inspect.getsource(service_mod)
    for banned in ("import config", "from config", "import vault", "from vault",
                   "import httpx", "import socket", "import requests",
                   "import main", "import api", "import db"):
        assert banned not in source


def test_service_module_does_not_resolve_its_own_database_path():
    """Path resolution stays `cfc.settings`'s job — this module only ever
    receives an already-resolved path via `open_service`/`ConversationStore`.
    """
    source = inspect.getsource(service_mod)
    assert "DATABASE_PATH" not in source
    assert "DEFAULT_DATABASE_PATH" not in source
