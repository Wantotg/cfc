"""test_cfc_conversation_service.py — cfc/conversation_service.py: the one
provider-independent owner of a turn's lifecycle. Every store lives under
`tmp_path`, driven only by injected deterministic async responders; no
config, no flat v1.9.1 module, no vault, and no network.

`send_turn` is a coroutine, so every call below goes through `run()`
(`asyncio.run`) rather than an async test plugin — the repo has none, and
this loop's Work Order asks for plain `asyncio` fixtures.
"""
from __future__ import annotations

import asyncio
import inspect
import sqlite3
from pathlib import Path

import pytest

from cfc import conversation_service as service_mod
from cfc import conversation_store
from cfc import provider_wire
from cfc.conversation_types import (
    Cancellation,
    CancelledOutcome,
    Completion,
    Failure,
    FailureEvidence,
    FailureKind,
    Role,
    TurnState,
    Usage,
)


def run(coro):
    return asyncio.run(coro)


class FixedResponder:
    """Returns the same result every time and records every call it saw."""

    def __init__(self, result):
        self._result = result
        self.calls = []

    async def respond(self, snapshot, model):
        self.calls.append((snapshot, model))
        return self._result


class RaisingResponder:
    """`BaseException`, not `Exception`: a `KeyboardInterrupt` during a live
    turn is one of the cases `send_turn` has to end the turn for.
    """

    def __init__(self, exc: BaseException):
        self._exc = exc

    async def respond(self, snapshot, model):
        raise self._exc


class SlowResponder:
    """Never returns on its own — `started` fires once `respond` is under
    way, so a test can cancel the awaiting task deterministically instead of
    racing a real clock.
    """

    def __init__(self):
        self.started = asyncio.Event()

    async def respond(self, snapshot, model):
        self.started.set()
        await asyncio.Event().wait()  # waits forever; the test cancels us
        return Completion(content="too late")  # pragma: no cover


class RaceResponder:
    """Simulates the completion-then-cancellation race: completes the turn
    through a back channel a real adapter is never given (`store` directly),
    then raises `CancelledError` — as if the awaiting task's cancellation
    were delivered in the instant right after a result already committed.
    """

    def __init__(self, store: conversation_store.ConversationStore, content: str):
        self._store = store
        self._content = content

    async def respond(self, snapshot, model):
        turn_id = snapshot.messages[-1].turn_id
        self._store.complete_turn(turn_id, self._content)
        raise asyncio.CancelledError()


class OpenStoreResponder:
    """A treacherous responder that tries to open the same database path
    itself. It has no legitimate way to know that path — this class is
    handed it only to prove the attempt fails, not to model real usage.
    """

    def __init__(self, path: Path):
        self._path = path
        self.observed_error = None

    async def respond(self, snapshot, model):
        try:
            conversation_store.open_store(self._path)
        except conversation_store.ConversationStoreError as exc:
            self.observed_error = exc
        return Cancellation()


class _FailOnceConn:
    """Wraps a real `sqlite3.Connection` and raises once, on the first
    `execute` call whose SQL contains `trigger`, then behaves normally for
    everything else — the service-level twin of the proxy
    `test_cfc_conversation_store.py` uses at the repository boundary,
    injected here at `service._store._conn` to simulate the store's own
    SQLite raising while `conversation_service` is trying to end a turn.
    """

    def __init__(self, real, trigger: str):
        self._real = real
        self._trigger = trigger
        self._fired = False

    def execute(self, sql, *args, **kwargs):
        if not self._fired and self._trigger in sql:
            self._fired = True
            raise sqlite3.OperationalError(f"simulated failure: {self._trigger}")
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


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

        turn = run(service.send_turn(chat.id, "fixture-model", "the question", responder))

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
        turn = run(service.send_turn(chat.id, "fixture-model", "q", responder))
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

        turn = run(service.send_turn(chat.id, "fixture-model", "q", responder))

        assert turn.outcome.evidence == evidence
        snapshot = service.snapshot(chat.id)
        assert [m.role for m in snapshot.messages] == [Role.USER]
    finally:
        service.close()


def test_declared_cancellation_is_recorded_and_distinct_from_failure(tmp_path):
    """A responder returning `Cancellation()` deterministically — not a
    cancelled `asyncio` task — remains a supported case."""
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = FixedResponder(Cancellation())
        turn = run(service.send_turn(chat.id, "fixture-model", "q", responder))

        assert isinstance(turn.outcome, CancelledOutcome)
        snapshot = service.snapshot(chat.id)
        assert [m.role for m in snapshot.messages] == [Role.USER]
    finally:
        service.close()


# --- task cancellation: a distinct path from a declared Cancellation -------

def test_cancelling_the_awaiting_task_finalises_cancelled_outcome_and_reraises(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = SlowResponder()

        async def scenario():
            task = asyncio.ensure_future(
                service.send_turn(chat.id, "fixture-model", "q", responder)
            )
            await responder.started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        run(scenario())

        turn_id = service.snapshot(chat.id).messages[0].turn_id
        turn = service.get_turn(turn_id)
        assert isinstance(turn.outcome, CancelledOutcome)
        assert [m.role for m in service.snapshot(chat.id).messages] == [Role.USER]
    finally:
        service.close()


def test_a_later_turn_is_permitted_after_task_cancellation(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = SlowResponder()

        async def scenario():
            task = asyncio.ensure_future(
                service.send_turn(chat.id, "fixture-model", "q1", responder)
            )
            await responder.started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return await service.send_turn(
                chat.id, "fixture-model", "q2", FixedResponder(Completion(content="ok")),
            )

        second = run(scenario())
        assert second.position == 1
        assert second.outcome.__class__.__name__ == "CompletedOutcome"
    finally:
        service.close()


def test_cancellation_never_overwrites_a_stored_outcome_that_already_won(tmp_path):
    """The completion-versus-cancellation race: if a result was already
    committed by the time cancellation handling runs, that stored outcome
    stands — cancellation must not overwrite it.
    """
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = RaceResponder(service._store, content="raced answer")

        with pytest.raises(asyncio.CancelledError):
            run(service.send_turn(chat.id, "fixture-model", "q", responder))

        turn_id = service.snapshot(chat.id).messages[0].turn_id
        turn = service.get_turn(turn_id)
        assert turn.outcome.__class__.__name__ == "CompletedOutcome"
        snapshot = service.snapshot(chat.id)
        assert [(m.role, m.content) for m in snapshot.messages] == [
            (Role.USER, "q"), (Role.ASSISTANT, "raced answer"),
        ]
    finally:
        service.close()


# --- unexpected exception: converted, turn ended before it is reported -----

def test_unexpected_responder_exception_becomes_typed_internal_failure(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = RaisingResponder(RuntimeError("boom"))

        turn = run(service.send_turn(chat.id, "fixture-model", "q", responder))

        assert turn.outcome.evidence.kind is FailureKind.INTERNAL
        assert turn.outcome.evidence.reason == service_mod._INTERNAL_FAILURE_REASON
        # ended, not left dangling: re-reading the store shows the same
        # terminal outcome, and a later turn is immediately permitted
        assert service.get_turn(turn.id).outcome == turn.outcome
    finally:
        service.close()


# --- B-2.0-33: internal evidence is one bounded, cfc-authored reason -------

def test_internal_failure_reason_never_carries_the_exception_text(tmp_path):
    """A future adapter's exception could contain a provider body, a
    request detail, or a credential — none of that may reach storage."""
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        secret = "sk-super-secret-credential-marker"
        responder = RaisingResponder(RuntimeError(secret))

        turn = run(service.send_turn(chat.id, "fixture-model", "q", responder))

        assert secret not in turn.outcome.evidence.reason
        assert "RuntimeError" not in turn.outcome.evidence.reason
        assert turn.outcome.evidence.reason == service_mod._INTERNAL_FAILURE_REASON
    finally:
        service.close()


def test_unrecognised_result_reason_never_carries_its_repr(tmp_path):
    class _LeaksIfPrinted:
        def __repr__(self):
            return "CREDENTIAL_LEAK_MARKER"

    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        turn = run(service.send_turn(
            chat.id, "fixture-model", "q", FixedResponder(_LeaksIfPrinted()),
        ))
        assert turn.outcome.evidence.kind is FailureKind.INTERNAL
        assert "CREDENTIAL_LEAK_MARKER" not in turn.outcome.evidence.reason
        assert turn.outcome.evidence.reason == service_mod._INTERNAL_FAILURE_REASON
    finally:
        service.close()


def test_every_internal_failure_path_shares_the_one_bounded_reason(tmp_path):
    service = open_service(tmp_path)
    try:
        exception_chat = service.create_chat("c1")
        exception_turn = run(service.send_turn(
            exception_chat.id, "m", "q", RaisingResponder(RuntimeError("x")),
        ))
        unrecognised_chat = service.create_chat("c2")
        unrecognised_turn = run(service.send_turn(
            unrecognised_chat.id, "m", "q", FixedResponder(None),
        ))
        assert (exception_turn.outcome.evidence.reason
                == unrecognised_turn.outcome.evidence.reason
                == service_mod._INTERNAL_FAILURE_REASON)
    finally:
        service.close()


def test_unexpected_exception_never_propagates_out_of_send_turn(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = RaisingResponder(ValueError("should not escape"))
        run(service.send_turn(chat.id, "fixture-model", "q", responder))  # must not raise
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
        turn = run(service.send_turn(
            chat.id, "fixture-model", "q", FixedResponder(None),  # not a result
        ))

        assert turn.outcome.evidence.kind is FailureKind.INTERNAL
        assert turn.outcome.evidence.reason == service_mod._INTERNAL_FAILURE_REASON
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
            run(service.send_turn(chat.id, "fixture-model", "q", responder))

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
            run(service.send_turn(
                chat.id, "fixture-model", "q1", RaisingResponder(KeyboardInterrupt()),
            ))

        later = run(service.send_turn(
            chat.id, "fixture-model", "q2", FixedResponder(Completion(content="ok")),
        ))
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
        first = run(service.send_turn(chat.id, "fixture-model", "q1", responder_factory()))
        second = run(service.send_turn(
            chat.id, "fixture-model", "q2", FixedResponder(Completion(content="fine")),
        ))
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
        next_turn = run(service.send_turn(
            chat.id, "fixture-model", "q2", FixedResponder(Completion(content="ok")),
        ))
        assert next_turn.position == turn.position + 1
    finally:
        service.close()


# --- the responder sees exactly the stored canonical history ---------------

def test_responder_observes_exactly_the_stored_canonical_history(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        run(service.send_turn(
            chat.id, "fixture-model", "first question",
            FixedResponder(Completion(content="first answer")),
        ))

        spy = FixedResponder(Completion(content="second answer"))
        run(service.send_turn(chat.id, "fixture-model", "second question", spy))

        assert len(spy.calls) == 1
        seen_snapshot, seen_model = spy.calls[0]
        assert seen_model == "fixture-model"
        assert seen_snapshot.chat_id == chat.id
        assert [(m.role, m.content) for m in seen_snapshot.messages] == [
            (Role.USER, "first question"),
            (Role.ASSISTANT, "first answer"),
            (Role.USER, "second question"),
        ]
        assert [t.position for t in seen_snapshot.turns] == [0, 1]
    finally:
        service.close()


def test_responder_snapshot_matches_an_independent_repository_read(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        spy = FixedResponder(Completion(content="answer"))
        run(service.send_turn(chat.id, "fixture-model", "question", spy))
        seen_snapshot, _ = spy.calls[0]
        # independently re-read: only the user message existed at call time
        assert [(m.role, m.content) for m in seen_snapshot.messages] == [
            (Role.USER, "question"),
        ]
    finally:
        service.close()


# --- D-2.0-39: a real stored snapshot passes through the real converter ----

def test_a_real_stored_snapshot_joins_the_real_wire_converter(tmp_path):
    """The hand-built fixtures in `test_cfc_provider_wire.py` still own
    contradictory snapshots the real store cannot produce; this proves the
    producer (`ConversationStore`, via `ConversationService`) and the
    converter (`provider_wire.build_request_plan`) agree through their real
    implementations, not just that each accepts a hand-built fixture. It
    manufactures no snapshot, uses no responder-under-test provider, loads
    no configuration, and touches no network — the deterministic responder
    below only forwards the snapshot it was actually handed.
    """
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        completed = run(service.send_turn(
            chat.id, "fixture-model", "first question",
            FixedResponder(Completion(content="first answer"))))
        failed = run(service.send_turn(
            chat.id, "fixture-model", "declared failure question",
            FixedResponder(Failure(FailureEvidence(FailureKind.RESPONDER, "declined")))))
        cancelled = run(service.send_turn(
            chat.id, "fixture-model", "declared cancel question",
            FixedResponder(Cancellation())))

        captured_plans = []

        class PlanCapturingResponder:
            async def respond(self, snapshot, model):
                captured_plans.append(provider_wire.build_request_plan(snapshot, model))
                return Completion(content="final answer")

        run(service.send_turn(chat.id, "fixture-model", "current question",
                               PlanCapturingResponder()))

        assert len(captured_plans) == 1
        plan = captured_plans[0]

        assert [(m.role, m.content) for m in plan.messages] == [
            ("user", "first question"), ("assistant", "first answer"),
            ("user", "current question"),
        ]
        assert set(plan.omitted) == {
            provider_wire.OmittedTurn(turn_id=failed.id, state=TurnState.FAILED),
            provider_wire.OmittedTurn(turn_id=cancelled.id, state=TurnState.CANCELLED),
        }
        assert completed.id not in {o.turn_id for o in plan.omitted}
    finally:
        service.close()


# --- the responder cannot acquire a repository handle -----------------------

def test_responder_cannot_open_the_store_itself_while_a_turn_is_active(tmp_path):
    path = db_path(tmp_path)
    service = service_mod.open_service(path)
    try:
        chat = service.create_chat("c")
        responder = OpenStoreResponder(path)
        run(service.send_turn(chat.id, "fixture-model", "q", responder))

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
    assert inspect.iscoroutinefunction(Responder.respond)


def test_send_turn_is_a_coroutine_function():
    assert inspect.iscoroutinefunction(service_mod.ConversationService.send_turn)


# --- D-2.0-36: one active turn per chat, refused before a responder --------

def test_a_second_send_in_the_same_active_chat_refuses_before_reaching_a_responder(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        first_responder = SlowResponder()
        second_responder = FixedResponder(Completion(content="must not be reached"))

        async def scenario():
            task = asyncio.ensure_future(
                service.send_turn(chat.id, "fixture-model", "q1", first_responder)
            )
            await first_responder.started.wait()
            with pytest.raises(conversation_store.ActiveTurnExists):
                await service.send_turn(chat.id, "fixture-model", "q2", second_responder)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        run(scenario())

        # the refused draft invoked no responder and wrote nothing: the
        # presentation layer, not the service, owns keeping "q2" around
        assert second_responder.calls == []
        snapshot = service.snapshot(chat.id)
        assert [m.content for m in snapshot.messages if m.role is Role.USER] == ["q1"]
    finally:
        service.close()


def test_the_refusal_names_the_chat_and_the_active_turn(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = SlowResponder()

        async def scenario():
            task = asyncio.ensure_future(
                service.send_turn(chat.id, "fixture-model", "q1", responder)
            )
            await responder.started.wait()
            with pytest.raises(conversation_store.ActiveTurnExists) as exc_info:
                await service.send_turn(chat.id, "fixture-model", "q2", responder)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return exc_info.value

        error = run(scenario())
        active_turn_id = service.snapshot(chat.id).messages[0].turn_id
        assert error.chat_id == chat.id
        assert error.active_turn_id == active_turn_id
    finally:
        service.close()


def test_two_different_chats_each_run_one_independent_active_turn(tmp_path):
    """Cas's clarification: different chats may each have one active request
    at the same time — this is not a promise of concurrent turns *in* one
    chat, which the test above proves refused."""
    service = open_service(tmp_path)
    try:
        chat_a = service.create_chat("a")
        chat_b = service.create_chat("b")
        responder_a = SlowResponder()
        responder_b = SlowResponder()

        async def scenario():
            task_a = asyncio.ensure_future(
                service.send_turn(chat_a.id, "fixture-model", "qa", responder_a))
            task_b = asyncio.ensure_future(
                service.send_turn(chat_b.id, "fixture-model", "qb", responder_b))
            await responder_a.started.wait()
            await responder_b.started.wait()  # both under way at once: neither refused the other
            task_a.cancel()
            task_b.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task_a
            with pytest.raises(asyncio.CancelledError):
                await task_b

        run(scenario())

        assert [m.content for m in service.snapshot(chat_a.id).messages] == ["qa"]
        assert [m.content for m in service.snapshot(chat_b.id).messages] == ["qb"]
    finally:
        service.close()


def test_a_terminal_outcome_reopens_the_chat_for_another_turn(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        run(service.send_turn(
            chat.id, "fixture-model", "q1", FixedResponder(Completion(content="ok"))))
        # no ActiveTurnExists: the prior turn is terminal, not active
        second = run(service.send_turn(
            chat.id, "fixture-model", "q2", FixedResponder(Completion(content="ok2"))))
        assert second.position == 1
    finally:
        service.close()


# --- B-2.0-32: a store failure while ending a turn is never raw and never --
# --- masks the interruption or cancellation it happens alongside -----------

def test_a_store_failure_ending_an_internal_failure_raises_bounded_error_not_raw_sqlite(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        service._store._conn = _FailOnceConn(
            service._store._conn, "UPDATE cfc_turns SET finished_at",
        )
        responder = RaisingResponder(RuntimeError("boom"))

        with pytest.raises(service_mod.TurnEndingFailed):
            run(service.send_turn(chat.id, "fixture-model", "q", responder))
    finally:
        service.close()


def test_a_store_failure_while_ending_an_interruption_does_not_mask_it(tmp_path):
    """The bug: the guards caught `ConversationStoreError`, not the store's
    real `sqlite3.Error`, so a store failure while recording the ending
    could propagate instead of the `KeyboardInterrupt` it was ending —
    silently turning an interrupt into a database error."""
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        service._store._conn = _FailOnceConn(
            service._store._conn, "UPDATE cfc_turns SET finished_at",
        )
        responder = RaisingResponder(KeyboardInterrupt())

        with pytest.raises(KeyboardInterrupt):
            run(service.send_turn(chat.id, "fixture-model", "q", responder))
    finally:
        service.close()


def test_a_store_failure_while_ending_a_cancelled_task_does_not_mask_the_cancellation(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c")
        responder = SlowResponder()

        async def scenario():
            task = asyncio.ensure_future(
                service.send_turn(chat.id, "fixture-model", "q", responder))
            await responder.started.wait()
            service._store._conn = _FailOnceConn(
                service._store._conn, "UPDATE cfc_turns SET finished_at",
            )
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        run(scenario())  # must not raise sqlite3.Error or TurnEndingFailed instead
    finally:
        service.close()


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
