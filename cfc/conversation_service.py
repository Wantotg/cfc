"""conversation_service.py — the one provider-independent owner of a turn's
lifecycle: creating and reopening ordinary chats, atomically starting a
turn, awaiting the injected responder, and requesting the repository's one
terminal transition.

No CLI, REPL, or provider adapter calls the repository directly for any of
this — `conversation_store.ConversationStore` is a dependency of this
module alone. An HTTP adapter (`cfc.provider_adapter`) supplies a
`Responder` (`conversation_types.Responder`); it does not gain its own path
to `cfc_turns`/`cfc_messages`.

`send_turn` is a coroutine. Only the responder await can take real time —
`start_turn`, the pre-await `snapshot` read, and every finalising call
remain the same short synchronous SQLite transitions `conversation_store`
always performed; this module still does not run its own executor or
background task.
"""
from __future__ import annotations

import asyncio
import sqlite3

from cfc.conversation_store import (
    ConflictingFinalisation,
    ConversationStore,
    ConversationStoreError,
    open_store,
)
from cfc.conversation_types import (
    Cancellation,
    Chat,
    ChatId,
    Completion,
    ConversationSnapshot,
    Failure,
    FailureEvidence,
    FailureKind,
    Responder,
    ResponderResult,
    Turn,
    TurnId,
)


#: B-2.0-33: the one stored reason for every internal failure — a responder
#: exception this module did not expect, or a responder result this module
#: does not recognise. Never `str(exc)` or `repr(result)`: either could carry
#: a provider body, a request detail, or a credential a future adapter's
#: exception happened to include.
_INTERNAL_FAILURE_REASON = "an internal error interrupted this turn before it could finish"


class TurnEndingFailed(ConversationStoreError):
    """B-2.0-32: the store's own SQLite boundary raised while this call was
    trying to record a turn's ending — a closed connection, full disk, or
    another real database failure, not `ConflictingFinalisation` or
    `UnknownTurn`, which stay their own typed vocabulary. The turn this call
    was ending remains active in storage; a later `open_store` reopen is the
    honest recovery route, not a fabricated `Turn` this call cannot produce.

    Subclasses `ConversationStoreError` so existing "the store itself is
    unreachable" handling that already catches that base class needs no
    separate case for this.
    """

    def __init__(self, turn_id: TurnId, detail: str):
        self.turn_id = turn_id
        self.detail = detail
        super().__init__(
            f"turn {turn_id}: the store could not record its ending ({detail}); "
            f"reopen recovery is the route"
        )


class ConversationService:
    """Construct with an already-open `ConversationStore` — this module
    never resolves a database path itself. `open_service` is the
    convenience constructor for the common case of owning that store too.
    """

    def __init__(self, store: ConversationStore):
        self._store = store

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "ConversationService":
        return self

    def __exit__(self, *exc_info) -> bool:
        self.close()
        return False

    # -- chats -----------------------------------------------------------

    def create_chat(self, title: str) -> Chat:
        return self._store.create_chat(title)

    def list_chats(self) -> tuple[Chat, ...]:
        return self._store.list_chats()

    def get_chat(self, chat_id: ChatId) -> Chat:
        return self._store.get_chat(chat_id)

    def snapshot(self, chat_id: ChatId) -> ConversationSnapshot:
        return self._store.snapshot(chat_id)

    def get_turn(self, turn_id: TurnId) -> Turn:
        return self._store.get_turn(turn_id)

    # -- the turn lifecycle -------------------------------------------------

    async def send_turn(self, chat_id: ChatId, model: str, user_content: str,
                         responder: Responder) -> Turn:
        """Start a turn, hand the responder exactly the stored canonical
        history plus the model, and finalise the one result it returns.

        The responder receives a `ConversationSnapshot` and a model string —
        nothing that could let it reach `cfc_turns`/`cfc_messages` itself.

        **Once this method has started a turn, that turn ends before this
        method does.** Every way out of the body below is covered:

        - an ordinary exception (from the responder, or from a result this
          module doesn't recognise) becomes one bounded, cfc-authored
          internal failure and is returned rather than raised, so a caller
          never handles "the responder raised" separately from "the
          responder returned Failure" — never `str(exc)` or `repr(result)`,
          which could carry a provider body, a request detail, or a
          credential (B-2.0-33);
        - cancellation of the task awaiting the responder ends the turn as
          `CancelledOutcome` and then re-raises — if a terminal outcome
          already won that race (the store committed a result and then the
          awaiting task was cancelled), that stored outcome is preserved,
          never overwritten;
        - an interruption that is neither of those — `KeyboardInterrupt`,
          `SystemExit` — ends the turn as a typed interrupted failure and
          then keeps travelling, because swallowing those would make cfc
          un-interruptible; and
        - a store failure while ending a turn — `sqlite3.Error`, not
          `ConversationStoreError`, so the ordinary guards above cannot see
          it on their own (B-2.0-32) — never leaks a raw SQLite exception
          and never masks a `KeyboardInterrupt`/`SystemExit`/cancellation it
          happens alongside: ending an internal failure raises
          `TurnEndingFailed` instead of returning a `Turn` this module
          cannot honestly produce; ending an interruption or cancellation
          swallows it, since the original interruption or cancellation is
          the one thing this call must still deliver.

        `ActiveTurnExists` from `self._store.start_turn` is deliberately not
        caught here (D-2.0-36): it means this call never started a turn at
        all, so there is nothing for this method to end — it propagates
        straight to the caller as the typed refusal a presentation layer
        renders, before any responder is ever reached.

        Only a process that dies outright leaves an active turn behind, and
        `open_store`'s reopen recovery is that case's route.
        """
        turn, _user_message = self._store.start_turn(chat_id, model, user_content)

        try:
            snapshot = self._store.snapshot(chat_id)
            result: ResponderResult = await responder.respond(snapshot, model)
            return self._apply_result(turn.id, result)
        except asyncio.CancelledError:
            self._end_unfinished_as_cancelled(turn.id)
            raise
        except Exception:  # noqa: BLE001 — deliberately broad: any responder failure
            return self._end_unfinished(turn.id, FailureKind.INTERNAL, _INTERNAL_FAILURE_REASON)
        except BaseException as exc:
            try:
                self._end_unfinished(
                    turn.id, FailureKind.INTERRUPTED, type(exc).__name__,
                )
            except ConversationStoreError:
                pass  # the store itself is unreachable; reopen recovery remains
            raise

    def _end_unfinished(self, turn_id: TurnId, kind: FailureKind, reason: str) -> Turn:
        """End a turn that is still active. If it already ended — the store
        committed its outcome and then something later in `send_turn` went
        wrong — the stored ending stands and is returned untouched.

        Raises `TurnEndingFailed` if the store's own SQLite boundary fails
        while recording this ending (B-2.0-32): there is no honest `Turn` to
        return in that case, and reopen recovery is the real route.
        """
        try:
            return self._store.fail_turn(turn_id, FailureEvidence(kind, reason))
        except ConflictingFinalisation:
            return self._store.get_turn(turn_id)
        except sqlite3.Error as exc:
            raise TurnEndingFailed(turn_id, str(exc)) from exc

    def _end_unfinished_as_cancelled(self, turn_id: TurnId) -> None:
        """End a still-active turn as `CancelledOutcome`. If a terminal
        outcome already won — the responder finished and the store
        committed its result in the instant before this task's cancellation
        was delivered — that stored outcome stands untouched: cancellation
        never overwrites a completion or failure that already happened.

        A store failure while recording the ending (`sqlite3.Error`) is
        swallowed the same as an unreachable store: the cancellation this
        call exists to preserve must still reach the caller, and reopen
        recovery remains the honest route for the ending that could not be
        written (B-2.0-32).
        """
        try:
            self._store.cancel_turn(turn_id)
        except ConflictingFinalisation:
            pass
        except (ConversationStoreError, sqlite3.Error):
            pass  # the store itself is unreachable; reopen recovery remains

    def _apply_result(self, turn_id: TurnId, result: ResponderResult) -> Turn:
        if isinstance(result, Completion):
            return self._store.complete_turn(turn_id, result.content, result.usage)
        if isinstance(result, Failure):
            return self._store.fail_turn(turn_id, result.evidence)
        if isinstance(result, Cancellation):
            return self._store.cancel_turn(turn_id)
        raise TypeError(f"responder returned an unrecognised result: {result!r}")


def open_service(path) -> ConversationService:
    """Open the store at `path` and wrap it in a `ConversationService`.
    `path` must already be resolved, exactly like `conversation_store.open_store`.
    """
    return ConversationService(open_store(path))
