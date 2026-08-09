"""conversation_service.py — the one provider-independent owner of a turn's
lifecycle: creating and reopening ordinary chats, atomically starting a
turn, invoking the injected responder, and requesting the repository's one
terminal transition.

No CLI, REPL, or provider adapter calls the repository directly for any of
this — `conversation_store.ConversationStore` is a dependency of this
module alone. A later HTTP adapter supplies a `Responder`
(`conversation_types.Responder`); it does not gain its own path to
`cfc_turns`/`cfc_messages`.
"""
from __future__ import annotations

from cfc.conversation_store import ConversationStore, open_store
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

    def send_turn(self, chat_id: ChatId, model: str, user_content: str,
                  responder: Responder) -> Turn:
        """Start a turn, hand the responder exactly the stored canonical
        history plus the model, and finalise the one result it returns.

        The responder receives a `ConversationSnapshot` and a model string —
        nothing that could let it reach `cfc_turns`/`cfc_messages` itself.
        An exception the responder raises is caught here, converted to a
        typed internal failure, and used to end the active turn before this
        method returns; it never propagates past this call, so a caller
        never has to separately handle "the responder raised" as distinct
        from "the responder returned Failure".
        """
        turn, _user_message = self._store.start_turn(chat_id, model, user_content)
        snapshot = self._store.snapshot(chat_id)

        try:
            result: ResponderResult = responder.respond(snapshot, model)
        except Exception as exc:  # noqa: BLE001 — deliberately broad: any responder failure
            evidence = FailureEvidence(
                FailureKind.INTERNAL, f"{type(exc).__name__}: {exc}",
            )
            return self._store.fail_turn(turn.id, evidence)

        return self._apply_result(turn.id, result)

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
