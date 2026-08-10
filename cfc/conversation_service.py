"""conversation_service.py — the one provider-independent owner of a turn's
lifecycle: creating and reopening ordinary chats, resolving a chat's named
context, atomically starting a turn, awaiting the injected responder, and
requesting the repository's one terminal transition.

No CLI, REPL, or provider adapter calls the repository directly for any of
this — `conversation_store.ConversationStore` is a dependency of this
module alone. An HTTP adapter (`cfc.provider_adapter`) supplies a
`Responder` (`cfc.provider_wire.Responder`); it does not gain its own path
to `cfc_turns`/`cfc_messages`, the vault, or the context resolver.

This module owns the one explicit, presentation-free context-resolver
dependency (`cfc.context`, driven by an already-resolved `VaultSettings`):
`preview_context` and every selection/model operation resolve or persist
through it, and `send_turn` resolves one fresh `ContextPlan` before it
starts a durable turn — a context refusal therefore causes no provider
request and no orphaned durable user message. The TUI, the store, and the
adapter never independently reread a vault file or rebuild context.

`send_turn` is a coroutine. Only the responder await can take real time —
`start_turn`, the pre-await `snapshot` read, and every finalising call
remain the same short synchronous SQLite transitions `conversation_store`
always performed; this module still does not run its own executor or
background task.
"""
from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field

from cfc import context as context_mod
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
    ContextCategory,
    ContextManifestEntry,
    ContextPlan,
    ConversationSnapshot,
    Failure,
    FailureEvidence,
    FailureKind,
    OpeningMessage,
    SourceRecord,
    Turn,
    TurnId,
    utc_now,
)
from cfc.context import FirstMessageLookup, SourceOption
from cfc.provider_wire import Responder, ResponderResult, build_request_plan
from cfc.settings import VaultCategorySettings, VaultSettings


@dataclass(frozen=True)
class CategoryState:
    """One optional context category's current resolved state, for display —
    never fail-fast the way `build_context_plan` is: a broken Persona must
    not hide whether Traits are fine. At most one of `source`/
    `unavailable_reason` is set, and only when `selected_name` is not
    `None`; all three are absent together for "nothing selected".
    """
    category: ContextCategory
    selected_name: str | None
    source: SourceRecord | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class ContextRows:
    """Every row `tui.py`'s Context modal renders, resolved together in one
    call so the modal never shows five independently stale reads. `traits`
    preserves selection order; `first_message` is `None` once a chat already
    has a frozen `opening` — nothing further to look up once an opening
    exists.
    """
    system_instructions: SourceRecord
    user_preferences: CategoryState
    persona: CategoryState
    traits: tuple[CategoryState, ...] = field(default_factory=tuple)
    first_message: FirstMessageLookup | None = None


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


#: `ContextCategory` -> the `VaultSettings` field the resolver reads for it.
#: Named once here so `available_sources`/`set_persona` cannot drift onto two
#: different mappings.
_CATEGORY_VAULT_FIELD = {
    ContextCategory.USER_PREFERENCES: "user_preferences",
    ContextCategory.PERSONA: "personas",
    ContextCategory.TRAIT: "traits",
    ContextCategory.FIRST_MESSAGE: "first_messages",
}


class ConversationService:
    """Construct with an already-open `ConversationStore` and an already-
    resolved `VaultSettings` — this module never resolves a database path
    or a config snapshot itself. `open_service` is the convenience
    constructor for the common case of owning the store too.
    """

    def __init__(self, store: ConversationStore, vault: VaultSettings):
        self._store = store
        self._vault = vault

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "ConversationService":
        return self

    def __exit__(self, *exc_info) -> bool:
        self.close()
        return False

    # -- chats -----------------------------------------------------------

    def create_chat(self, title: str, model: str) -> Chat:
        return self._store.create_chat(title, model)

    def list_chats(self) -> tuple[Chat, ...]:
        return self._store.list_chats()

    def get_chat(self, chat_id: ChatId) -> Chat:
        return self._store.get_chat(chat_id)

    def snapshot(self, chat_id: ChatId) -> ConversationSnapshot:
        return self._store.snapshot(chat_id)

    def get_turn(self, turn_id: TurnId) -> Turn:
        return self._store.get_turn(turn_id)

    # -- context: preview and selection, through the resolver dependency ----

    def preview_context(self, chat_id: ChatId) -> ContextPlan:
        """The exact ordered prefix a new turn would use *right now* — a
        fresh resolution against this chat's current selection, never a
        cached one. Raises `cfc.context.SourceUnavailable` exactly as
        `send_turn` would for the same selection (Concept.md's "Inspection
        describes the next turn").
        """
        chat = self._store.get_chat(chat_id)
        return context_mod.build_context_plan(self._vault, chat.context_selection)

    def _category_settings(self, category: ContextCategory) -> VaultCategorySettings:
        return getattr(self._vault, _CATEGORY_VAULT_FIELD[category])

    def _resolve_category_state(
        self, category: ContextCategory, filename: str | None,
    ) -> CategoryState:
        if filename is None:
            return CategoryState(category, None)
        try:
            source = context_mod.read_source(category, self._category_settings(category), filename)
            return CategoryState(category, filename, source=source)
        except context_mod.SourceUnavailable as exc:
            return CategoryState(category, filename, unavailable_reason=exc.reason)

    def context_rows(self, chat_id: ChatId) -> ContextRows:
        """Every row the Context modal renders, resolved independently —
        never `preview_context`'s fail-fast plan, so one broken selection
        cannot hide the state of every other row (Concept.md's "The Context
        modal is both the selector and the inspection route").
        """
        chat = self._store.get_chat(chat_id)
        selection = chat.context_selection
        first_message = None
        if chat.opening is None and selection.persona is not None:
            first_message = context_mod.look_up_first_message(
                self._vault.first_messages, selection.persona,
            )
        return ContextRows(
            system_instructions=context_mod.system_instructions_record(),
            user_preferences=self._resolve_category_state(
                ContextCategory.USER_PREFERENCES, selection.user_preferences),
            persona=self._resolve_category_state(ContextCategory.PERSONA, selection.persona),
            traits=tuple(
                self._resolve_category_state(ContextCategory.TRAIT, filename)
                for filename in selection.traits
            ),
            first_message=first_message,
        )

    def context_entry_fingerprint_changed(self, entry: ContextManifestEntry) -> bool:
        """`True` if `entry` names a vault-owned source and a fresh read no
        longer matches the fingerprint this turn actually used — including
        a source that has since become entirely unavailable. Always `False`
        for `SYSTEM_INSTRUCTIONS`, which this build ships fixed.
        """
        if entry.category is ContextCategory.SYSTEM_INSTRUCTIONS:
            return False
        try:
            fresh = context_mod.read_source(
                entry.category, self._category_settings(entry.category), entry.name,
            )
        except context_mod.SourceUnavailable:
            return True
        return fresh.fingerprint != entry.fingerprint

    def available_sources(self, category: ContextCategory) -> tuple[SourceOption, ...]:
        """Every currently unambiguous filename this category's configured
        vault directory offers, for a Context modal's Add/Change picker.
        """
        return context_mod.available_sources(self._category_settings(category))

    def set_user_preferences(self, chat_id: ChatId, filename: str | None) -> Chat:
        return self._store.set_user_preferences(chat_id, filename)

    def set_persona(self, chat_id: ChatId, filename: str | None) -> Chat:
        """Sets `chat_id`'s Persona selection. When `filename` names a
        Persona with a usable First Messages companion, that companion is
        offered to the store as a candidate opening — `ConversationStore.
        set_persona` remains the sole, atomic authority on whether this
        chat is still eligible to freeze it (Concept.md: "Only the first
        eligible Persona selection may freeze it").
        """
        opening: OpeningMessage | None = None
        if filename is not None:
            lookup = context_mod.look_up_first_message(self._vault.first_messages, filename)
            if lookup.state is context_mod.FirstMessageState.USABLE:
                record = lookup.record
                opening = OpeningMessage(
                    source_name=record.name, content=record.body,
                    created_at=utc_now(), fingerprint=record.fingerprint,
                )
        return self._store.set_persona(chat_id, filename, opening=opening)

    def add_trait(self, chat_id: ChatId, filename: str) -> Chat:
        return self._store.add_trait(chat_id, filename)

    def remove_trait(self, chat_id: ChatId, filename: str) -> Chat:
        return self._store.remove_trait(chat_id, filename)

    def set_model(self, chat_id: ChatId, model: str) -> Chat:
        return self._store.set_model(chat_id, model)

    # -- the turn lifecycle -------------------------------------------------

    async def send_turn(self, chat_id: ChatId, user_content: str,
                         responder: Responder) -> Turn:
        """Resolve this chat's fresh context plan and current model, start a
        turn, hand the responder exactly the resulting request plan, and
        finalise the one result it returns.

        The context plan is resolved, and the request plan built, from
        `chat` as read once at the top of this call — before `start_turn`.
        A `cfc.context.SourceUnavailable` here propagates straight to the
        caller: no turn is started, so there is nothing for this method to
        end (mirrors `ActiveTurnExists`, below).

        The responder receives only the finished `RequestPlan` — nothing
        that could let it reach `cfc_turns`/`cfc_messages`, the vault, or a
        source body outside what is already on that plan.

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
        chat = self._store.get_chat(chat_id)
        context_plan = context_mod.build_context_plan(self._vault, chat.context_selection)
        model = chat.context_selection.model
        manifest = context_plan.to_manifest()

        turn, _user_message = self._store.start_turn(chat_id, model, user_content, manifest)

        try:
            snapshot = self._store.snapshot(chat_id)
            plan = build_request_plan(context_plan, chat.opening, snapshot, model)
            result: ResponderResult = await responder.respond(plan)
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


def open_service(path, vault: VaultSettings) -> ConversationService:
    """Open the store at `path` and wrap it, with `vault`, in a
    `ConversationService`. `path` must already be resolved, exactly like
    `conversation_store.open_store`; `vault` is `cfc.settings.build_vault_
    settings`'s own already-resolved output — this module never resolves
    a config snapshot itself.
    """
    return ConversationService(open_store(path), vault)
