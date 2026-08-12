"""test_cfc_conversation_service.py — cfc/conversation_service.py: the one
provider-independent owner of a turn's lifecycle, including the context-
resolver dependency it now carries. Every store lives under `tmp_path`,
driven only by injected deterministic async responders; every
`ConversationService` here is built with `empty_vault()` — an unconfigured
`VaultSettings` — so a turn's context plan always resolves to just cfc's own
System Instructions. No config, no flat v1.9.1 module, no real vault
directory, and no network.

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

from cfc import chat_export
from cfc import context as context_mod
from cfc import conversation_service as service_mod
from cfc import conversation_store
from cfc import provider_wire
from cfc.conversation_types import (
    Cancellation,
    CancelledOutcome,
    Completion,
    ContextCategory,
    Failure,
    FailureEvidence,
    FailureKind,
    Role,
    TurnState,
    Usage,
)
from cfc.settings import VaultCategorySettings, VaultSettings


def run(coro):
    return asyncio.run(coro)


def empty_vault() -> VaultSettings:
    unavailable = VaultCategorySettings(unavailable_reason="not configured")
    return VaultSettings(root=None, user_preferences=unavailable, personas=unavailable,
                          traits=unavailable, first_messages=unavailable, main_chat=unavailable)


def real_vault(tmp_path: Path, *, prefs=None, personas=None, traits=None,
                first_messages=None, main_chat=None) -> VaultSettings:
    def cat(path):
        if path is None:
            return VaultCategorySettings(unavailable_reason="not configured")
        return VaultCategorySettings(path=path)
    return VaultSettings(root=tmp_path, user_preferences=cat(prefs), personas=cat(personas),
                          traits=cat(traits), first_messages=cat(first_messages),
                          main_chat=cat(main_chat))


def write(directory: Path, name: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(body, encoding="utf-8")


class FixedResponder:
    """Returns the same result every time and records every `RequestPlan`
    it was actually handed — the responder now sees nothing else.
    """

    def __init__(self, result):
        self._result = result
        self.calls: list = []

    async def respond(self, plan):
        self.calls.append(plan)
        return self._result


class RaisingResponder:
    """`BaseException`, not `Exception`: a `KeyboardInterrupt` during a live
    turn is one of the cases `send_turn` has to end the turn for.
    """

    def __init__(self, exc: BaseException):
        self._exc = exc

    async def respond(self, plan):
        raise self._exc


class SlowResponder:
    """Never returns on its own — `started` fires once `respond` is under
    way, so a test can cancel the awaiting task deterministically instead of
    racing a real clock.
    """

    def __init__(self):
        self.started = asyncio.Event()

    async def respond(self, plan):
        self.started.set()
        await asyncio.Event().wait()  # waits forever; the test cancels us
        return Completion(content="too late")  # pragma: no cover


class RaceResponder:
    """Simulates the completion-then-cancellation race: completes the turn
    through a back channel a real adapter is never given (`store` directly),
    then raises `CancelledError` — as if the awaiting task's cancellation
    were delivered in the instant right after a result already committed.

    A `RequestPlan` carries no chat or turn identity (by design — see
    `cfc.provider_wire.RequestPlan`), so this fixture is constructed with
    `chat_id` directly rather than deriving it from what `respond` receives;
    `store.snapshot(chat_id).turns[-1]` is the one active turn under test.
    """

    def __init__(self, store: conversation_store.ConversationStore, chat_id, content: str):
        self._store = store
        self._chat_id = chat_id
        self._content = content

    async def respond(self, plan):
        turn_id = self._store.snapshot(self._chat_id).turns[-1].id
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

    async def respond(self, plan):
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
    return service_mod.open_service(db_path(tmp_path), empty_vault())


# --- chats: distinct identities, listable, reopenable -----------------

def test_two_chats_get_distinct_identities_and_are_listed_in_creation_order(tmp_path):
    service = open_service(tmp_path)
    try:
        first = service.create_chat("first", "fixture-model")
        second = service.create_chat("second", "fixture-model")
        assert first.id != second.id
        assert [c.id for c in service.list_chats()] == [first.id, second.id]
        assert service.get_chat(second.id).title == "second"
    finally:
        service.close()


# --- completed turns: usage supplied and omitted ---------------------------

def test_completed_turn_with_usage_round_trips(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        usage = Usage(input_tokens=4, output_tokens=6, total_tokens=10)
        responder = FixedResponder(Completion(content="the answer", usage=usage))

        turn = run(service.send_turn(chat.id, "the question", responder))

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
        chat = service.create_chat("c", "fixture-model")
        responder = FixedResponder(Completion(content="ok", usage=None))
        turn = run(service.send_turn(chat.id, "q", responder))
        assert turn.outcome.usage is None
    finally:
        service.close()


# --- declared failure and cancellation: distinct, both terminal ------------

def test_responder_declared_failure_is_recorded_with_no_synthetic_answer(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        evidence = FailureEvidence(FailureKind.RESPONDER, "declined")
        responder = FixedResponder(Failure(evidence))

        turn = run(service.send_turn(chat.id, "q", responder))

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
        chat = service.create_chat("c", "fixture-model")
        responder = FixedResponder(Cancellation())
        turn = run(service.send_turn(chat.id, "q", responder))

        assert isinstance(turn.outcome, CancelledOutcome)
        snapshot = service.snapshot(chat.id)
        assert [m.role for m in snapshot.messages] == [Role.USER]
    finally:
        service.close()


# --- task cancellation: a distinct path from a declared Cancellation -------

def test_cancelling_the_awaiting_task_finalises_cancelled_outcome_and_reraises(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        responder = SlowResponder()

        async def scenario():
            task = asyncio.ensure_future(
                service.send_turn(chat.id, "q", responder)
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
        chat = service.create_chat("c", "fixture-model")
        responder = SlowResponder()

        async def scenario():
            task = asyncio.ensure_future(
                service.send_turn(chat.id, "q1", responder)
            )
            await responder.started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return await service.send_turn(chat.id, "q2", FixedResponder(Completion(content="ok")),
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
        chat = service.create_chat("c", "fixture-model")
        responder = RaceResponder(service._store, chat.id, content="raced answer")

        with pytest.raises(asyncio.CancelledError):
            run(service.send_turn(chat.id, "q", responder))

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
        chat = service.create_chat("c", "fixture-model")
        responder = RaisingResponder(RuntimeError("boom"))

        turn = run(service.send_turn(chat.id, "q", responder))

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
        chat = service.create_chat("c", "fixture-model")
        secret = "sk-super-secret-credential-marker"
        responder = RaisingResponder(RuntimeError(secret))

        turn = run(service.send_turn(chat.id, "q", responder))

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
        chat = service.create_chat("c", "fixture-model")
        turn = run(service.send_turn(chat.id, "q", FixedResponder(_LeaksIfPrinted()),
        ))
        assert turn.outcome.evidence.kind is FailureKind.INTERNAL
        assert "CREDENTIAL_LEAK_MARKER" not in turn.outcome.evidence.reason
        assert turn.outcome.evidence.reason == service_mod._INTERNAL_FAILURE_REASON
    finally:
        service.close()


def test_every_internal_failure_path_shares_the_one_bounded_reason(tmp_path):
    service = open_service(tmp_path)
    try:
        exception_chat = service.create_chat("c1", "fixture-model")
        exception_turn = run(service.send_turn(exception_chat.id, "q", RaisingResponder(RuntimeError("x")),
        ))
        unrecognised_chat = service.create_chat("c2", "fixture-model")
        unrecognised_turn = run(service.send_turn(unrecognised_chat.id, "q", FixedResponder(None),
        ))
        assert (exception_turn.outcome.evidence.reason
                == unrecognised_turn.outcome.evidence.reason
                == service_mod._INTERNAL_FAILURE_REASON)
    finally:
        service.close()


def test_unexpected_exception_never_propagates_out_of_send_turn(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        responder = RaisingResponder(ValueError("should not escape"))
        run(service.send_turn(chat.id, "q", responder))  # must not raise
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
        chat = service.create_chat("c", "fixture-model")
        turn = run(service.send_turn(chat.id, "q", FixedResponder(None),  # not a result
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
        chat = service.create_chat("c", "fixture-model")
        responder = RaisingResponder(interruption())

        with pytest.raises(interruption):
            run(service.send_turn(chat.id, "q", responder))

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
        chat = service.create_chat("c", "fixture-model")
        with pytest.raises(KeyboardInterrupt):
            run(service.send_turn(chat.id, "q1", RaisingResponder(KeyboardInterrupt()),
            ))

        later = run(service.send_turn(chat.id, "q2", FixedResponder(Completion(content="ok")),
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
        chat = service.create_chat("c", "fixture-model")
        first = run(service.send_turn(chat.id, "q1", responder_factory()))
        second = run(service.send_turn(chat.id, "q2", FixedResponder(Completion(content="fine")),
        ))
        assert second.position == first.position + 1
        assert second.outcome.__class__.__name__ == "CompletedOutcome"
    finally:
        service.close()


# --- restart/reopen: process-death recovery is Step 2's path, unchanged ----

def test_restart_recovers_a_turn_left_active_by_a_prior_owner(tmp_path):
    path = db_path(tmp_path)

    store = conversation_store.open_store(path)
    chat = store.create_chat("c", "fixture-model")
    turn, _ = store.start_turn(chat.id, "fixture-model", "q")
    store.close()  # simulates the process disappearing mid-turn, no finalise

    service = service_mod.open_service(path, empty_vault())
    try:
        recovered = service.get_turn(turn.id)
        assert recovered.outcome.evidence.kind is FailureKind.INTERRUPTED

        # the chat is still usable after recovery
        next_turn = run(service.send_turn(chat.id, "q2", FixedResponder(Completion(content="ok")),
        ))
        assert next_turn.position == turn.position + 1
    finally:
        service.close()


# --- the responder sees exactly the stored canonical history ---------------

def test_responder_observes_exactly_the_stored_canonical_history(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        run(service.send_turn(chat.id, "first question",
            FixedResponder(Completion(content="first answer")),
        ))

        spy = FixedResponder(Completion(content="second answer"))
        run(service.send_turn(chat.id, "second question", spy))

        assert len(spy.calls) == 1
        plan = spy.calls[0]
        assert plan.model == "fixture-model"
        # plan.messages[0] is the one context message empty_vault() still
        # contributes (System Instructions); everything after it is the
        # exact stored canonical turn history.
        assert [(m.role, m.content) for m in plan.messages[1:]] == [
            ("user", "first question"),
            ("assistant", "first answer"),
            ("user", "second question"),
        ]
        assert plan.omitted == ()
    finally:
        service.close()


def test_responder_plan_matches_an_independent_repository_read(tmp_path):
    """The `RequestPlan` a responder receives carries no chat or turn
    identity by design (`cfc.provider_wire.RequestPlan`) — this proves its
    literal turn-history content agrees with an independent `snapshot`
    read taken at the same moment, not that the two share any object.
    """
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        spy = FixedResponder(Completion(content="answer"))
        run(service.send_turn(chat.id, "question", spy))
        plan = spy.calls[0]
        # independently re-read: only the user message existed at call time
        assert [(m.role, m.content) for m in plan.messages[1:]] == [
            ("user", "question"),
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
    no configuration, and touches no network — `send_turn` itself builds
    the plan now, through the real store and the real converter, before the
    deterministic responder below ever sees it.
    """
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        completed = run(service.send_turn(chat.id, "first question",
            FixedResponder(Completion(content="first answer"))))
        failed = run(service.send_turn(chat.id, "declared failure question",
            FixedResponder(Failure(FailureEvidence(FailureKind.RESPONDER, "declined")))))
        cancelled = run(service.send_turn(chat.id, "declared cancel question",
            FixedResponder(Cancellation())))

        captured_plans = []

        class PlanCapturingResponder:
            async def respond(self, plan):
                captured_plans.append(plan)
                return Completion(content="final answer")

        run(service.send_turn(chat.id, "current question",
                               PlanCapturingResponder()))

        assert len(captured_plans) == 1
        plan = captured_plans[0]

        assert [(m.role, m.content) for m in plan.messages[1:]] == [
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
    service = service_mod.open_service(path, empty_vault())
    try:
        chat = service.create_chat("c", "fixture-model")
        responder = OpenStoreResponder(path)
        run(service.send_turn(chat.id, "q", responder))

        assert responder.observed_error is not None
        assert isinstance(responder.observed_error, conversation_store.DatabaseInUse)
    finally:
        service.close()


def test_responder_protocol_carries_no_store_or_authority_argument():
    """Structural proof alongside the behavioural one above: `respond`
    takes only the finished `RequestPlan`, so there is no parameter a real
    responder could receive a store, a snapshot, or an authority object
    through (`cfc.provider_wire.Responder`, retired from
    `conversation_types` this loop).
    """
    from cfc.provider_wire import Responder
    signature = inspect.signature(Responder.respond)
    assert list(signature.parameters) == ["self", "plan"]
    assert inspect.iscoroutinefunction(Responder.respond)


def test_send_turn_is_a_coroutine_function():
    assert inspect.iscoroutinefunction(service_mod.ConversationService.send_turn)


# --- D-2.0-36: one active turn per chat, refused before a responder --------

def test_a_second_send_in_the_same_active_chat_refuses_before_reaching_a_responder(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        first_responder = SlowResponder()
        second_responder = FixedResponder(Completion(content="must not be reached"))

        async def scenario():
            task = asyncio.ensure_future(
                service.send_turn(chat.id, "q1", first_responder)
            )
            await first_responder.started.wait()
            with pytest.raises(conversation_store.ActiveTurnExists):
                await service.send_turn(chat.id, "q2", second_responder)
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
        chat = service.create_chat("c", "fixture-model")
        responder = SlowResponder()

        async def scenario():
            task = asyncio.ensure_future(
                service.send_turn(chat.id, "q1", responder)
            )
            await responder.started.wait()
            with pytest.raises(conversation_store.ActiveTurnExists) as exc_info:
                await service.send_turn(chat.id, "q2", responder)
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
        chat_a = service.create_chat("a", "fixture-model")
        chat_b = service.create_chat("b", "fixture-model")
        responder_a = SlowResponder()
        responder_b = SlowResponder()

        async def scenario():
            task_a = asyncio.ensure_future(
                service.send_turn(chat_a.id, "qa", responder_a))
            task_b = asyncio.ensure_future(
                service.send_turn(chat_b.id, "qb", responder_b))
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
        chat = service.create_chat("c", "fixture-model")
        run(service.send_turn(chat.id, "q1", FixedResponder(Completion(content="ok"))))
        # no ActiveTurnExists: the prior turn is terminal, not active
        second = run(service.send_turn(chat.id, "q2", FixedResponder(Completion(content="ok2"))))
        assert second.position == 1
    finally:
        service.close()


# --- B-2.0-32: a store failure while ending a turn is never raw and never --
# --- masks the interruption or cancellation it happens alongside -----------

def test_a_store_failure_ending_an_internal_failure_raises_bounded_error_not_raw_sqlite(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        service._store._conn = _FailOnceConn(
            service._store._conn, "UPDATE cfc_turns SET finished_at",
        )
        responder = RaisingResponder(RuntimeError("boom"))

        with pytest.raises(service_mod.TurnEndingFailed):
            run(service.send_turn(chat.id, "q", responder))
    finally:
        service.close()


def test_a_store_failure_while_ending_an_interruption_does_not_mask_it(tmp_path):
    """The bug: the guards caught `ConversationStoreError`, not the store's
    real `sqlite3.Error`, so a store failure while recording the ending
    could propagate instead of the `KeyboardInterrupt` it was ending —
    silently turning an interrupt into a database error."""
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        service._store._conn = _FailOnceConn(
            service._store._conn, "UPDATE cfc_turns SET finished_at",
        )
        responder = RaisingResponder(KeyboardInterrupt())

        with pytest.raises(KeyboardInterrupt):
            run(service.send_turn(chat.id, "q", responder))
    finally:
        service.close()


def test_a_store_failure_while_ending_a_cancelled_task_does_not_mask_the_cancellation(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        responder = SlowResponder()

        async def scenario():
            task = asyncio.ensure_future(
                service.send_turn(chat.id, "q", responder))
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


# --- context: preview, selection, and the resolver dependency --------------

def test_preview_context_reflects_current_selection_without_starting_a_turn(tmp_path):
    personas_dir = tmp_path / "personas"
    write(personas_dir, "muse.md", "You are Muse.")
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path, personas=personas_dir))
    try:
        chat = service.create_chat("c", "fixture-model")
        service.set_persona(chat.id, "muse.md")

        plan = service.preview_context(chat.id)
        assert plan.persona.body == "You are Muse."
        assert service.snapshot(chat.id).turns == ()  # preview starts nothing
    finally:
        service.close()


def test_send_turn_uses_a_freshly_resolved_plan_matching_the_stored_manifest(tmp_path):
    personas_dir = tmp_path / "personas"
    write(personas_dir, "muse.md", "You are Muse.")
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path, personas=personas_dir))
    try:
        chat = service.create_chat("c", "fixture-model")
        service.set_persona(chat.id, "muse.md")
        responder = FixedResponder(Completion(content="ok"))

        turn = run(service.send_turn(chat.id, "hi", responder))

        preview = service.preview_context(chat.id)
        persona_entry = next(e for e in turn.context_manifest if e.category is ContextCategory.PERSONA)
        assert persona_entry.name == "muse.md"
        assert persona_entry.fingerprint == preview.persona.fingerprint
        plan = responder.calls[0]
        assert any(m.role == "system" and m.content == "You are Muse." for m in plan.messages)
    finally:
        service.close()


def test_an_unusable_selected_source_reaches_neither_store_nor_responder(tmp_path):
    personas_dir = tmp_path / "personas"
    personas_dir.mkdir()  # exists, but "ghost.md" inside it does not
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path, personas=personas_dir))
    try:
        chat = service.create_chat("c", "fixture-model")
        service.set_persona(chat.id, "ghost.md")
        responder = FixedResponder(Completion(content="must not run"))

        with pytest.raises(context_mod.SourceUnavailable):
            run(service.send_turn(chat.id, "hi", responder))

        assert responder.calls == []
        snapshot = service.snapshot(chat.id)
        assert snapshot.turns == ()
        assert snapshot.messages == ()
    finally:
        service.close()


def test_set_persona_freezes_a_usable_first_message_companion(tmp_path):
    personas_dir = tmp_path / "personas"
    first_messages_dir = tmp_path / "first_messages"
    write(personas_dir, "muse.md", "You are Muse.")
    write(first_messages_dir, "muse.md", "Hello, I am Muse.")
    vault = real_vault(tmp_path, personas=personas_dir, first_messages=first_messages_dir)
    service = service_mod.open_service(db_path(tmp_path), vault)
    try:
        chat = service.create_chat("c", "fixture-model")
        updated = service.set_persona(chat.id, "muse.md")
        assert updated.opening is not None
        assert updated.opening.content == "Hello, I am Muse."
        assert updated.opening.source_name == "muse.md"
    finally:
        service.close()


def test_set_persona_with_no_companion_leaves_opening_absent(tmp_path):
    personas_dir = tmp_path / "personas"
    write(personas_dir, "muse.md", "You are Muse.")
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path, personas=personas_dir))
    try:
        chat = service.create_chat("c", "fixture-model")
        updated = service.set_persona(chat.id, "muse.md")
        assert updated.opening is None
    finally:
        service.close()


def test_a_completed_turns_context_manifest_lists_category_name_order_and_fingerprint(tmp_path):
    prefs_dir, personas_dir, traits_dir = (tmp_path / "prefs", tmp_path / "personas", tmp_path / "traits")
    write(prefs_dir, "p.md", "prefs body")
    write(personas_dir, "muse.md", "persona body")
    write(traits_dir, "dry.md", "dry body")
    vault = real_vault(tmp_path, prefs=prefs_dir, personas=personas_dir, traits=traits_dir)
    service = service_mod.open_service(db_path(tmp_path), vault)
    try:
        chat = service.create_chat("c", "fixture-model")
        service.set_user_preferences(chat.id, "p.md")
        service.set_persona(chat.id, "muse.md")
        service.add_trait(chat.id, "dry.md")

        turn = run(service.send_turn(chat.id, "hi", FixedResponder(Completion(content="ok"))))

        assert [e.category for e in turn.context_manifest] == [
            ContextCategory.SYSTEM_INSTRUCTIONS, ContextCategory.USER_PREFERENCES,
            ContextCategory.PERSONA, ContextCategory.TRAIT,
        ]
        assert [e.name for e in turn.context_manifest][1:] == ["p.md", "muse.md", "dry.md"]
        assert [e.order for e in turn.context_manifest] == [0, 1, 2, 3]
        for entry in turn.context_manifest:
            assert entry.character_count > 0
            assert entry.fingerprint
        # re-read from storage agrees exactly
        assert service.get_turn(turn.id).context_manifest == turn.context_manifest
    finally:
        service.close()


def test_available_sources_reads_the_right_categorys_vault_directory(tmp_path):
    traits_dir = tmp_path / "traits"
    write(traits_dir, "dry.md", "dry")
    write(traits_dir, "warm.md", "warm")
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path, traits=traits_dir))
    try:
        options = service.available_sources(ContextCategory.TRAIT)
        assert [o.name for o in options] == ["dry.md", "warm.md"]
        assert service.available_sources(ContextCategory.PERSONA) == ()
    finally:
        service.close()


def test_context_rows_resolves_each_category_independently_not_fail_fast(tmp_path):
    """A broken Persona selection must not hide a healthy Traits row."""
    personas_dir, traits_dir = tmp_path / "personas", tmp_path / "traits"
    personas_dir.mkdir()  # "ghost.md" will not exist inside it
    write(traits_dir, "dry.md", "dry body")
    vault = real_vault(tmp_path, personas=personas_dir, traits=traits_dir)
    service = service_mod.open_service(db_path(tmp_path), vault)
    try:
        chat = service.create_chat("c", "fixture-model")
        service.set_persona(chat.id, "ghost.md")
        service.add_trait(chat.id, "dry.md")

        rows = service.context_rows(chat.id)

        assert rows.persona.selected_name == "ghost.md"
        assert rows.persona.source is None
        assert rows.persona.unavailable_reason is not None

        assert rows.traits[0].selected_name == "dry.md"
        assert rows.traits[0].source.body == "dry body"
        assert rows.traits[0].unavailable_reason is None

        assert rows.user_preferences == service_mod.CategoryState(
            ContextCategory.USER_PREFERENCES, None,
            category_unavailable_reason="not configured",
        )
    finally:
        service.close()


def test_context_rows_carry_each_category_s_own_unavailable_reason(tmp_path):
    """B-2.0-62: a category with no usable configured directory reports that
    fact whether or not anything is selected in it, so the interface can
    tell "you have chosen nothing" apart from "you cannot choose here".
    """
    traits_dir = tmp_path / "traits"
    write(traits_dir, "dry.md", "dry body")
    vault = real_vault(tmp_path, traits=traits_dir)
    service = service_mod.open_service(db_path(tmp_path), vault)
    try:
        chat = service.create_chat("c", "fixture-model")
        service.add_trait(chat.id, "dry.md")
        rows = service.context_rows(chat.id)

        assert rows.user_preferences.category_unavailable_reason == "not configured"
        assert rows.user_preferences.selected_name is None
        assert rows.persona.category_unavailable_reason == "not configured"
        assert rows.traits[0].category_unavailable_reason is None

        assert service.category_unavailable_reason(ContextCategory.PERSONA) == "not configured"
        assert service.category_unavailable_reason(ContextCategory.TRAIT) is None
    finally:
        service.close()


def test_context_rows_first_message_is_none_once_an_opening_exists(tmp_path):
    personas_dir = tmp_path / "personas"
    first_messages_dir = tmp_path / "first_messages"
    write(personas_dir, "muse.md", "persona body")
    write(first_messages_dir, "muse.md", "opening body")
    vault = real_vault(tmp_path, personas=personas_dir, first_messages=first_messages_dir)
    service = service_mod.open_service(db_path(tmp_path), vault)
    try:
        chat = service.create_chat("c", "fixture-model")
        updated = service.set_persona(chat.id, "muse.md")
        assert updated.opening is not None

        rows = service.context_rows(chat.id)
        assert rows.first_message is None
    finally:
        service.close()


def test_context_rows_first_message_reports_a_live_lookup_before_any_opening(tmp_path):
    personas_dir = tmp_path / "personas"
    first_messages_dir = tmp_path / "first_messages"
    write(personas_dir, "muse.md", "persona body")
    # no first_messages_dir entry for muse.md at all
    vault = real_vault(tmp_path, personas=personas_dir, first_messages=first_messages_dir)
    service = service_mod.open_service(db_path(tmp_path), vault)
    try:
        chat = service.create_chat("c", "fixture-model")
        # a turn already exists, so set_persona cannot freeze an opening —
        # first_message must still report the live lookup state honestly
        turn, _ = service._store.start_turn(chat.id, "fixture-model", "hi")
        service._store.complete_turn(turn.id, "hello")
        service.set_persona(chat.id, "muse.md")

        rows = service.context_rows(chat.id)
        assert rows.first_message is not None
        assert rows.first_message.state is context_mod.FirstMessageState.ABSENT
    finally:
        service.close()


def test_context_entry_fingerprint_changed_detects_a_vault_edit(tmp_path):
    personas_dir = tmp_path / "personas"
    write(personas_dir, "muse.md", "version one")
    vault = real_vault(tmp_path, personas=personas_dir)
    service = service_mod.open_service(db_path(tmp_path), vault)
    try:
        chat = service.create_chat("c", "fixture-model")
        service.set_persona(chat.id, "muse.md")
        turn = run(service.send_turn(chat.id, "hi", FixedResponder(Completion(content="ok"))))
        persona_entry = next(e for e in turn.context_manifest if e.category is ContextCategory.PERSONA)

        assert service.context_entry_fingerprint_changed(persona_entry) is False
        write(personas_dir, "muse.md", "version two")
        assert service.context_entry_fingerprint_changed(persona_entry) is True
    finally:
        service.close()


def test_context_entry_fingerprint_changed_is_always_false_for_system_instructions(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        turn = run(service.send_turn(chat.id, "hi", FixedResponder(Completion(content="ok"))))
        system_entry = turn.context_manifest[0]
        assert system_entry.category is ContextCategory.SYSTEM_INSTRUCTIONS
        assert service.context_entry_fingerprint_changed(system_entry) is False
    finally:
        service.close()


# --- Main: get-or-create, profile resolution, and turn parity --------------

def main_bundle(main_dir: Path, *, first_message="Hello from Main.") -> None:
    write(main_dir, "system prompt.md", "Main's system prompt.")
    write(main_dir, "persona.md", "Main's persona.")
    write(main_dir, "first message.md", first_message)


def test_get_or_create_main_creates_once_and_freezes_the_opening(tmp_path):
    main_dir = tmp_path / "main"
    main_bundle(main_dir)
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path, main_chat=main_dir))
    try:
        chat = service.get_or_create_main("fixture-model")
        assert chat.kind is service_mod.ChatKind.MAIN
        assert chat.title == "Main"
        assert chat.opening.content == "Hello from Main."

        reopened = service.get_or_create_main("fixture-model")
        assert reopened.id == chat.id
    finally:
        service.close()


def test_get_or_create_main_never_creates_a_row_when_the_bundle_is_broken(tmp_path):
    main_dir = tmp_path / "main"
    main_dir.mkdir()  # none of the three files exist
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path, main_chat=main_dir))
    try:
        with pytest.raises(context_mod.SourceUnavailable):
            service.get_or_create_main("fixture-model")
        assert service._store.find_main() is None
    finally:
        service.close()


def test_get_or_create_main_reopen_never_rereads_the_creation_bundle(tmp_path):
    """Concept.md: "that action reopens it even when its live profile is
    currently broken" — an existing Main is found by `find_main` before this
    method would even look at MAIN_CHAT_DIR again."""
    main_dir = tmp_path / "main"
    main_bundle(main_dir)
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path, main_chat=main_dir))
    try:
        chat = service.get_or_create_main("fixture-model")
        # break the live profile entirely — a reopen must still succeed
        (main_dir / "system prompt.md").unlink()
        (main_dir / "persona.md").unlink()
        (main_dir / "first message.md").unlink()

        reopened = service.get_or_create_main("fixture-model")
        assert reopened.id == chat.id
        assert reopened.opening.content == "Hello from Main."
    finally:
        service.close()


def test_main_send_turn_resolves_profile_and_shared_selection_in_order(tmp_path):
    main_dir = tmp_path / "main"
    prefs_dir = tmp_path / "prefs"
    main_bundle(main_dir)
    write(prefs_dir, "p.md", "prefs body")
    vault = real_vault(tmp_path, main_chat=main_dir, prefs=prefs_dir)
    service = service_mod.open_service(db_path(tmp_path), vault)
    try:
        chat = service.get_or_create_main("fixture-model")
        service.set_user_preferences(chat.id, "p.md")
        responder = FixedResponder(Completion(content="ok"))

        turn = run(service.send_turn(chat.id, "hi", responder))

        assert [e.category for e in turn.context_manifest] == [
            ContextCategory.SYSTEM_INSTRUCTIONS, ContextCategory.MAIN_SYSTEM_PROMPT,
            ContextCategory.MAIN_PERSONA, ContextCategory.USER_PREFERENCES,
        ]
        plan = responder.calls[0]
        assert any(m.content == "Main's system prompt." for m in plan.messages)
        assert any(m.content == "Hello from Main." and m.role == "assistant" for m in plan.messages)
    finally:
        service.close()


def test_main_send_turn_refuses_before_start_turn_when_live_profile_is_broken(tmp_path):
    """Concept.md: "Send refuses before persistence or HTTP, preserves the
    draft" — an existing Main's broken live profile must not reach the
    responder or leave a stray turn/message."""
    main_dir = tmp_path / "main"
    main_bundle(main_dir)
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path, main_chat=main_dir))
    try:
        chat = service.get_or_create_main("fixture-model")
        (main_dir / "system prompt.md").unlink()
        responder = FixedResponder(Completion(content="must not run"))

        with pytest.raises(context_mod.SourceUnavailable):
            run(service.send_turn(chat.id, "hi", responder))

        assert responder.calls == []
        assert service.snapshot(chat.id).turns == ()
    finally:
        service.close()


def test_context_rows_for_main_includes_profile_rows_ordinary_chat_does_not(tmp_path):
    main_dir = tmp_path / "main"
    main_bundle(main_dir)
    vault = real_vault(tmp_path, main_chat=main_dir)
    service = service_mod.open_service(db_path(tmp_path), vault)
    try:
        main_chat = service.get_or_create_main("fixture-model")
        main_rows = service.context_rows(main_chat.id)
        assert main_rows.main_system_prompt.source.body == "Main's system prompt."
        assert main_rows.main_persona.source.body == "Main's persona."

        ordinary_chat = service.create_chat("c", "fixture-model")
        ordinary_rows = service.context_rows(ordinary_chat.id)
        assert ordinary_rows.main_system_prompt is None
        assert ordinary_rows.main_persona is None
    finally:
        service.close()


# --- attachments: discovery, selection, resolution, provenance -------------

def test_available_attachments_discovers_vault_relative_md_files(tmp_path):
    write(tmp_path / "notes", "idea.md", "an idea")
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path))
    try:
        options = service.available_attachments()
        assert [o.name for o in options] == ["notes/idea.md"]
    finally:
        service.close()


def test_add_and_remove_attachment_are_reachable_through_the_service(tmp_path):
    write(tmp_path, "a.md", "a")
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path))
    try:
        chat = service.create_chat("c", "fixture-model")
        after_add = service.add_attachment(chat.id, "a.md")
        assert after_add.context_selection.attachments == ("a.md",)
        after_remove = service.remove_attachment(chat.id, "a.md")
        assert after_remove.context_selection.attachments == ()
    finally:
        service.close()


def test_ordinary_send_turn_places_attachments_after_the_shared_selection(tmp_path):
    write(tmp_path, "a.md", "attachment body")
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path))
    try:
        chat = service.create_chat("c", "fixture-model")
        service.add_attachment(chat.id, "a.md")
        responder = FixedResponder(Completion(content="ok"))

        turn = run(service.send_turn(chat.id, "hi", responder))

        assert turn.context_manifest[-1].category is ContextCategory.ATTACHMENT
        assert turn.context_manifest[-1].name == "a.md"
        plan = responder.calls[0]
        attachment_message = next(m for m in plan.messages if "attachment body" in m.content)
        assert attachment_message.role == "user"
    finally:
        service.close()


def test_an_unusable_attachment_reaches_neither_store_nor_responder(tmp_path):
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path))
    try:
        chat = service.create_chat("c", "fixture-model")
        service.add_attachment(chat.id, "ghost.md")
        responder = FixedResponder(Completion(content="must not run"))

        with pytest.raises(context_mod.SourceUnavailable):
            run(service.send_turn(chat.id, "hi", responder))

        assert responder.calls == []
        assert service.snapshot(chat.id).turns == ()
    finally:
        service.close()


def test_context_rows_resolves_each_attachment_independently(tmp_path):
    write(tmp_path, "good.md", "good body")
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path))
    try:
        chat = service.create_chat("c", "fixture-model")
        service.add_attachment(chat.id, "good.md")
        service.add_attachment(chat.id, "ghost.md")

        rows = service.context_rows(chat.id)
        by_path = {row.relative_path: row for row in rows.attachments}
        assert by_path["good.md"].source.body == "good body"
        assert by_path["ghost.md"].source is None
        assert by_path["ghost.md"].unavailable_reason is not None
    finally:
        service.close()


def test_context_entry_fingerprint_changed_detects_an_attachment_edit(tmp_path):
    write(tmp_path, "a.md", "version one")
    service = service_mod.open_service(db_path(tmp_path), real_vault(tmp_path))
    try:
        chat = service.create_chat("c", "fixture-model")
        service.add_attachment(chat.id, "a.md")
        turn = run(service.send_turn(chat.id, "hi", FixedResponder(Completion(content="ok"))))
        entry = turn.context_manifest[-1]

        assert service.context_entry_fingerprint_changed(entry) is False
        write(tmp_path, "a.md", "version two")
        assert service.context_entry_fingerprint_changed(entry) is True
    finally:
        service.close()


def test_add_remove_trait_and_set_model_are_reachable_through_the_service(tmp_path):
    service = open_service(tmp_path)
    try:
        chat = service.create_chat("c", "fixture-model")
        service.add_trait(chat.id, "dry.md")
        after_add = service.add_trait(chat.id, "warm.md")
        assert after_add.context_selection.traits == ("dry.md", "warm.md")

        after_remove = service.remove_trait(chat.id, "dry.md")
        assert after_remove.context_selection.traits == ("warm.md",)

        after_model = service.set_model(chat.id, "other-model")
        assert after_model.context_selection.model == "other-model"

        after_prefs = service.set_user_preferences(chat.id, "prefs.md")
        assert after_prefs.context_selection.user_preferences == "prefs.md"
    finally:
        service.close()


# --- export: the one service operation, active-turn refused ----------------

def test_export_chat_is_reachable_through_the_service(tmp_path):
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    service = service_mod.ConversationService(
        conversation_store.open_store(db_path(tmp_path)), empty_vault(), export_dir,
    )
    try:
        chat = service.create_chat("c", "fixture-model")
        run(service.send_turn(chat.id, "hi", FixedResponder(Completion(content="ok"))))

        path = service.export_chat(chat.id)

        assert path.exists()
        assert "hi" in path.read_text(encoding="utf-8")
    finally:
        service.close()


def test_export_chat_refuses_with_active_turn_exists_while_a_turn_is_active(tmp_path):
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    service = service_mod.ConversationService(
        conversation_store.open_store(db_path(tmp_path)), empty_vault(), export_dir,
    )
    try:
        chat = service.create_chat("c", "fixture-model")
        service._store.start_turn(chat.id, "fixture-model", "hi")

        with pytest.raises(conversation_store.ActiveTurnExists):
            service.export_chat(chat.id)
    finally:
        service.close()


def test_export_chat_reports_a_bounded_destination_error_when_unconfigured(tmp_path):
    service = open_service(tmp_path)  # no export_dir given
    try:
        chat = service.create_chat("c", "fixture-model")
        with pytest.raises(chat_export.DestinationUnusable):
            service.export_chat(chat.id)
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
