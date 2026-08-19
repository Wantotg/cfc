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
from enum import Enum

from cfc import chat_export
from cfc import context as context_mod
from cfc.conversation_store import (
    ActiveTurnExists,
    ConflictingFinalisation,
    ConflictingToolResult,
    ConversationStore,
    ConversationStoreError,
    open_store,
)
from cfc.conversation_types import (
    ApprovalDecision,
    Cancellation,
    Chat,
    ChatId,
    ChatKind,
    Completion,
    ContextCategory,
    ContextManifestEntry,
    ContextPlan,
    ConversationSnapshot,
    ExchangeEnding,
    Failure,
    FailureEvidence,
    FailureKind,
    OpeningMessage,
    ProviderProblem,
    SourceRecord,
    ToolCall,
    ToolCallBatch,
    ToolCallEvidence,
    ToolOutcomeKind,
    Turn,
    TurnId,
    Usage,
    utc_now,
)
from cfc.context import FirstMessageLookup, SourceOption
from cfc.provider_wire import Responder, ResponderResult, build_request_plan
from cfc.settings import (
    DisplayNameSettings,
    FileToolProblem,
    FileToolSettings,
    ModelCatalogue,
    VaultCategorySettings,
    VaultSettings,
)
from cfc.tool_authority import FileAuthority
from cfc.tool_registry import ApprovalPort, PendingToolCall, ToolRegistry, default_registry


class ContextEntryStatus(Enum):
    """`context_entry_status`'s tri-state result (B-2.0-82): a completed
    turn's frozen manifest entry, compared against a fresh read of the same
    source right now, is either still exactly what it was, has changed, or
    can no longer be read at all — three distinct facts `Turn details` must
    show as such rather than folding "changed" and "unavailable" into one
    generic blame.
    """
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class CategoryState:
    """One optional context category's current resolved state, for display —
    never fail-fast the way `build_context_plan` is: a broken Persona must
    not hide whether Traits are fine.

    Two independent kinds of unavailability, because a person corrects them
    in two different places (B-2.0-62):

    - `category_unavailable_reason` is set whenever this category has no
      usable configured directory at all, selection or no selection. It is
      `settings.VaultCategorySettings`'s own bounded reason, and it is
      corrected in `config.py`. Nothing in this category can be selected
      while it is set.
    - `unavailable_reason` is set only when `selected_name` names a file
      this category cannot currently read, and is corrected in the vault.

    `source` and `unavailable_reason` are both absent when nothing is
    selected; `category_unavailable_reason` is independent of all three.
    """
    category: ContextCategory
    selected_name: str | None
    source: SourceRecord | None = None
    unavailable_reason: str | None = None
    category_unavailable_reason: str | None = None


@dataclass(frozen=True)
class AttachmentRow:
    """One selected attachment's current resolved state, for the Context
    modal's Attachments section — the same independent-of-everything-else
    resolution `CategoryState` gives Traits, so one broken attachment cannot
    hide whether the others are fine.
    """
    relative_path: str
    source: SourceRecord | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class ContextRows:
    """Every row `tui.py`'s Context modal renders, resolved together in one
    call so the modal never shows independently stale reads. `traits`
    preserves selection order; `first_message` is `None` once a chat already
    has a frozen `opening` — nothing further to look up once an opening
    exists. `main_system_prompt`/`main_persona` are set only for a Main
    chat's rows; `attachments` (Stage 5 loop 3) is set for either chat kind,
    in selection order.
    """
    system_instructions: SourceRecord
    user_preferences: CategoryState
    persona: CategoryState
    traits: tuple[CategoryState, ...] = field(default_factory=tuple)
    first_message: FirstMessageLookup | None = None
    main_system_prompt: CategoryState | None = None
    main_persona: CategoryState | None = None
    attachments: tuple[AttachmentRow, ...] = field(default_factory=tuple)


#: B-2.0-33: the one stored reason for every internal failure — a responder
#: exception this module did not expect, or a responder result this module
#: does not recognise. Never `str(exc)` or `repr(result)`: either could carry
#: a provider body, a request detail, or a credential a future adapter's
#: exception happened to include.
_INTERNAL_FAILURE_REASON = "an internal error interrupted this turn before it could finish"

#: A well-formed, genuinely unusable `FileToolSettings` — the default when a
#: caller (an older test, a harness that predates this loop) constructs
#: `ConversationService` without passing one. Built with `problem` set
#: explicitly rather than the bare `FileToolSettings()` default, which would
#: read as *usable* (`problem=None`) despite `enabled=False` and no
#: roots — `FileToolSettings`'s own fields do not enforce that invariant by
#: themselves; only `cfc.settings.build_file_tool_settings` does.
_TOOLS_NOT_CONFIGURED = FileToolSettings(
    problem=FileToolProblem.DISABLED,
    unavailable_reason="file tools are not configured for this service",
)

#: Work Order Step 5's retained per-turn budgets, used only when no
#: `FileToolSettings` was supplied at all — production callers always pass
#: `cfc.settings.build_file_tool_settings`'s own resolved values instead.
_DEFAULT_MAX_CALLS_PER_TURN = 25
_DEFAULT_MAX_TURN_RESULT_CHARS = 120_000

#: The one reason a further tool-call response is malformed once tools are
#: not currently offered — whether they were never offered this turn or
#: were withdrawn after the turn's budget was spent. Named once so both
#: routes read identically in stored evidence.
_UNSOLICITED_TOOL_CALL_REASON = (
    "the provider proposed tool calls when none were offered for this request"
)


def _sum_usage(usages: list[Usage | None]) -> Usage | None:
    """The field-by-field sum of every exchange's independently optional
    usage counts (Work Order: "preserving explicit zero and absence"). A
    field is `None` only if every exchange left it unreported; one exchange
    reporting a real count (including `0`) makes that field's sum a real
    count, never discarded because a sibling exchange said nothing about
    it. `None` overall only when no exchange reported any usage at all.
    """
    totals: dict[str, int | None] = {"input_tokens": None, "output_tokens": None,
                                       "total_tokens": None}
    for usage in usages:
        if usage is None:
            continue
        for field_name in totals:
            value = getattr(usage, field_name)
            if value is None:
                continue
            totals[field_name] = value if totals[field_name] is None else totals[field_name] + value
    if all(value is None for value in totals.values()):
        return None
    return Usage(**totals)


def _current_task_cancel_requested() -> bool:
    """Whether this coroutine's own task has a pending cancellation —
    checked without an `await`, since `ToolDefinition.execute` is a
    synchronous, cooperatively-bounded call (Concept.md: "checks
    cancellation between bounded units of work") that asyncio cannot
    interrupt at an await point it never reaches. `Task.cancelling()`
    (3.11+) reports a requested-but-not-yet-delivered cancellation; the
    real `asyncio.CancelledError` still arrives at this coroutine's next
    real `await`, which is what actually unwinds `send_turn`.
    """
    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


#: `ResponderResult` type -> the tool-free `ExchangeEnding` it records —
#: `ToolCallBatch` is deliberately absent: `send_turn` never reaches this
#: mapping for one, since a batch is persisted through `persist_tool_call_
#: batch` instead of `record_exchange`.
_EXCHANGE_ENDING = {
    Completion: ExchangeEnding.COMPLETION,
    Failure: ExchangeEnding.FAILURE,
    Cancellation: ExchangeEnding.CANCELLED,
}


class _AutoRefusePort:
    """The `ApprovalPort` used when a caller configured file tools without
    also configuring a real port — refuses every call rather than silently
    approving or raising. Structurally reachable only if a caller wires
    `file_tools`/`registry` without `approval_port`; production callers
    always supply all three together.
    """

    async def decide(self, pending: PendingToolCall) -> ApprovalDecision:
        return ApprovalDecision.REFUSE


class MainPersonaNotSelectable(ConversationStoreError):
    """`ConversationService.set_persona` refused: `chat_id` is Main, whose
    Persona is its own fixed `persona.md` profile file, never a
    user-selected shared Persona (B-2.0-77). Refused before any store
    write — a set and a clear alike — so a caller that bypasses the Context
    modal (which already hides this action for Main) cannot persist a
    stored shared Persona on Main even once. The UI hiding the picker is
    therefore not the only authority boundary; this is the one that still
    holds if that hiding is ever wrong or bypassed.
    """

    def __init__(self, chat_id: ChatId):
        self.chat_id = chat_id
        super().__init__(f"chat {chat_id} is Main; it has no selectable shared Persona")


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

    def __init__(
        self, store: ConversationStore, vault: VaultSettings, export_dir=None,
        display_names: DisplayNameSettings | None = None,
        file_tools: FileToolSettings | None = None,
        models: ModelCatalogue | None = None,
        registry: ToolRegistry | None = None,
        approval_port: ApprovalPort | None = None,
    ):
        self._store = store
        self._vault = vault
        #: `cfc.settings.ExportSettings.path` — a `Path | None`, resolved
        #: independently of `vault` (Concept.md: "It is independent of
        #: `VAULT_ROOT`"). Threaded through the constructor rather than
        #: read from a config snapshot: this module never resolves its own
        #: settings, the same discipline `vault` already follows.
        self._export_dir = export_dir
        #: `cfc.settings.DisplayNameSettings` or `None` — `None` (the
        #: default) means every named template source below is read
        #: literally, exactly as before this setting existed; production
        #: callers (`open_service`, from `built.display_names`) always pass
        #: a real, resolved value. Never applied to attachments, which
        #: `cfc.context` reads literally regardless of what is passed here.
        self._display_names = display_names
        #: Stage 6 loop 1: the read-only tool lifecycle's four collaborators
        #: — resolved once, immutable for this service's lifetime, and never
        #: re-resolved by `send_turn` itself (the same discipline `vault`
        #: already follows). `file_tools`/`models` default to genuinely
        #: unusable/empty values rather than a permissive guess, so an older
        #: caller that constructs this class without them gets ordinary
        #: tool-free chat, never silent tool access.
        self._file_tools = file_tools if file_tools is not None else _TOOLS_NOT_CONFIGURED
        self._models = models if models is not None else ModelCatalogue()
        self._registry = registry if registry is not None else default_registry()
        self._approval_port: ApprovalPort = (
            approval_port if approval_port is not None else _AutoRefusePort()
        )

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

    # -- export: one manual, standalone Markdown snapshot --------------------

    def export_chat(self, chat_id: ChatId):
        """Reads `chat_id`'s canonical metadata, opening, and snapshot and
        publishes one standalone Markdown export through `cfc.chat_export`.

        Refuses with `conversation_store.ActiveTurnExists` while this chat
        has an active turn — reusing the same typed refusal every other
        active-turn-guarded selection change already raises, so a caller
        (`tui.py`) needs no second exception type to catch for "wait or
        cancel" guidance (Concept.md: "An active turn refuses export
        visibly... the person waits or cancels"). Every other refusal
        (unset/invalid `CHAT_EXPORT_DIR`, a missing or unwritable
        destination, a name-collision exhaustion, or a write/publish
        failure) is `cfc.chat_export.ExportError` and its subclasses.

        Never writes SQLite, calls the provider, or touches embeddings or
        Qdrant — `chat_export.export_chat` is pure rendering plus one
        atomic filesystem publish.
        """
        chat = self._store.get_chat(chat_id)
        snapshot = self._store.snapshot(chat_id)
        active_turn = next((t for t in snapshot.turns if t.outcome is None), None)
        if active_turn is not None:
            raise ActiveTurnExists(chat_id, active_turn.id)
        return chat_export.export_chat(self._export_dir, chat, chat.opening, snapshot)

    # -- context: preview and selection, through the resolver dependency ----

    def preview_context(self, chat_id: ChatId) -> ContextPlan:
        """The exact ordered prefix a new turn would use *right now* — a
        fresh resolution against this chat's current selection, never a
        cached one. Raises `cfc.context.SourceUnavailable` exactly as
        `send_turn` would for the same selection (Concept.md's "Inspection
        describes the next turn").
        """
        chat = self._store.get_chat(chat_id)
        return context_mod.build_context_plan(
            self._vault, chat.context_selection, chat.kind, self._display_names,
        )

    def _category_settings(self, category: ContextCategory) -> VaultCategorySettings:
        return getattr(self._vault, _CATEGORY_VAULT_FIELD[category])

    def category_unavailable_reason(self, category: ContextCategory) -> str | None:
        """Why this category has no usable configured directory, or `None`
        when it has one. Straight from `settings.VaultCategorySettings`,
        which already words every case (`VAULT_ROOT` unset, the category's
        own setting unset or not a string, a directory outside `VAULT_ROOT`)
        — this module adds no second vocabulary for the same fact.
        """
        return self._category_settings(category).unavailable_reason

    def _resolve_category_state(
        self, category: ContextCategory, filename: str | None,
    ) -> CategoryState:
        unusable = self.category_unavailable_reason(category)
        if filename is None:
            return CategoryState(category, None, category_unavailable_reason=unusable)
        try:
            source = context_mod.read_source(
                category, self._category_settings(category), filename, self._display_names,
            )
            return CategoryState(category, filename, source=source,
                                  category_unavailable_reason=unusable)
        except context_mod.SourceUnavailable as exc:
            return CategoryState(category, filename, unavailable_reason=exc.reason,
                                  category_unavailable_reason=unusable)

    def _resolve_main_profile_state(
        self, category: ContextCategory, filename: str, resolver,
    ) -> CategoryState:
        """One Main profile row's state — reuses `CategoryState`'s shape
        even though nothing is "selected" here: `filename` is always
        Main's own fixed identity (`system prompt.md`/`persona.md`), never
        a person's choice, so `selected_name` is never `None` for a Main
        chat's own profile rows.
        """
        unusable = self._vault.main_chat.unavailable_reason
        try:
            source = resolver(self._vault.main_chat, self._display_names)
            return CategoryState(category, filename, source=source,
                                  category_unavailable_reason=unusable)
        except context_mod.SourceUnavailable as exc:
            return CategoryState(category, filename, unavailable_reason=exc.reason,
                                  category_unavailable_reason=unusable)

    def _resolve_attachment_row(self, relative_path: str) -> AttachmentRow:
        try:
            source = context_mod.read_attachment(self._vault.root, relative_path)
            return AttachmentRow(relative_path, source=source)
        except context_mod.SourceUnavailable as exc:
            return AttachmentRow(relative_path, unavailable_reason=exc.reason)

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
                self._vault.first_messages, selection.persona, self._display_names,
            )
        main_system_prompt = None
        main_persona = None
        if chat.kind is ChatKind.MAIN:
            main_system_prompt = self._resolve_main_profile_state(
                ContextCategory.MAIN_SYSTEM_PROMPT, context_mod.MAIN_SYSTEM_PROMPT_FILENAME,
                context_mod.resolve_main_system_prompt,
            )
            main_persona = self._resolve_main_profile_state(
                ContextCategory.MAIN_PERSONA, context_mod.MAIN_PERSONA_FILENAME,
                context_mod.resolve_main_persona,
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
            main_system_prompt=main_system_prompt,
            main_persona=main_persona,
            attachments=tuple(
                self._resolve_attachment_row(path) for path in selection.attachments
            ),
        )

    def _resolve_entry_fresh_source(self, entry: ContextManifestEntry) -> SourceRecord:
        """A fresh read of whatever live source `entry` names, resolved the
        same way `build_context_plan` would resolve it right now. Raises
        `context_mod.SourceUnavailable` exactly when that live source can no
        longer be read at all — the one comparison point both
        `context_entry_fingerprint_changed` and `context_entry_status` share.
        """
        if entry.category is ContextCategory.MAIN_SYSTEM_PROMPT:
            return context_mod.resolve_main_system_prompt(self._vault.main_chat, self._display_names)
        if entry.category is ContextCategory.MAIN_PERSONA:
            return context_mod.resolve_main_persona(self._vault.main_chat, self._display_names)
        if entry.category is ContextCategory.ATTACHMENT:
            return context_mod.read_attachment(self._vault.root, entry.name)
        return context_mod.read_source(
            entry.category, self._category_settings(entry.category), entry.name, self._display_names,
        )

    def context_entry_fingerprint_changed(self, entry: ContextManifestEntry) -> bool:
        """`True` if `entry` names a vault-owned or Main-profile source and
        a fresh read no longer matches the fingerprint this turn actually
        used — including a source that has since become entirely
        unavailable. Always `False` for `SYSTEM_INSTRUCTIONS`, which this
        build ships fixed.
        """
        if entry.category is ContextCategory.SYSTEM_INSTRUCTIONS:
            return False
        try:
            fresh = self._resolve_entry_fresh_source(entry)
        except context_mod.SourceUnavailable:
            return True
        return fresh.fingerprint != entry.fingerprint

    def context_entry_status(self, entry: ContextManifestEntry) -> ContextEntryStatus:
        """B-2.0-82: the tri-state comparison `Turn details` renders — a
        fresh read of `entry`'s live source is either still the same
        fingerprint (`UNCHANGED`), a different one (`CHANGED`), or currently
        unreadable at all (`UNAVAILABLE`). Unlike
        `context_entry_fingerprint_changed`, "changed" and "unavailable"
        stay distinct facts rather than one collapsed boolean, so the modal
        never blames "the source" generically for both. Always `UNCHANGED`
        for `SYSTEM_INSTRUCTIONS`, which this build ships fixed.
        """
        if entry.category is ContextCategory.SYSTEM_INSTRUCTIONS:
            return ContextEntryStatus.UNCHANGED
        try:
            fresh = self._resolve_entry_fresh_source(entry)
        except context_mod.SourceUnavailable:
            return ContextEntryStatus.UNAVAILABLE
        if fresh.fingerprint != entry.fingerprint:
            return ContextEntryStatus.CHANGED
        return ContextEntryStatus.UNCHANGED

    def available_sources(self, category: ContextCategory) -> tuple[SourceOption, ...]:
        """Every currently unambiguous filename this category's configured
        vault directory offers, for a Context modal's Add/Change picker.
        """
        return context_mod.available_sources(self._category_settings(category))

    def available_attachments(self) -> tuple[SourceOption, ...]:
        """Every currently selectable Markdown attachment beneath
        `VAULT_ROOT`, for the Context modal's Attachments **Add** picker —
        reuses `SourceOption`'s shape exactly like `available_sources`
        (Work Order: "reuses the existing list-selection modal").
        """
        return context_mod.discover_attachments(self._vault.root)

    def attachments_unavailable_reason(self) -> str | None:
        """Why attachments cannot be discovered at all right now, or `None`
        when `VAULT_ROOT` is usable — the same "name the `config.py` field
        to correct" shape `category_unavailable_reason` already gives every
        other vault category (B-2.0-62), applied to the whole-vault root
        attachments are discovered under rather than one category directory.
        """
        if self._vault.root is not None:
            return None
        return "VAULT_ROOT is not set"

    def add_attachment(self, chat_id: ChatId, relative_path: str) -> Chat:
        """Validates and canonicalises `relative_path` before it ever
        reaches the store (B-2.0-76): `context_mod.read_attachment` proves
        it is a readable, in-boundary Markdown file and reduces it to its
        one canonical vault-relative identity, and only that identity is
        persisted. Raises `context_mod.SourceUnavailable` on refusal,
        leaving the current selection and store untouched — the same
        refusal a broken selection already raises at turn time, just moved
        to the moment of selection instead of being saved unvalidated and
        discovered later. Re-adding an equivalent spelling of an
        already-selected file canonicalises to the same identity, so the
        store's own duplicate-free `add_attachment` still treats it as an
        idempotent no-op.
        """
        record = context_mod.read_attachment(self._vault.root, relative_path)
        return self._store.add_attachment(chat_id, record.name)

    def remove_attachment(self, chat_id: ChatId, relative_path: str) -> Chat:
        return self._store.remove_attachment(chat_id, relative_path)

    def set_user_preferences(self, chat_id: ChatId, filename: str | None) -> Chat:
        return self._store.set_user_preferences(chat_id, filename)

    def set_persona(self, chat_id: ChatId, filename: str | None) -> Chat:
        """Sets `chat_id`'s Persona selection. When `filename` names a
        Persona with a usable First Messages companion, that companion is
        offered to the store as a candidate opening — `ConversationStore.
        set_persona` remains the sole, atomic authority on whether this
        chat is still eligible to freeze it (Concept.md: "Only the first
        eligible Persona selection may freeze it").

        Raises `MainPersonaNotSelectable` before any store write when
        `chat_id` is Main — a set (`filename` given) and a clear
        (`filename=None`) alike (B-2.0-77): Main's persona is its own fixed
        `persona.md` profile, never a stored shared selection.
        """
        chat = self._store.get_chat(chat_id)
        if chat.kind is ChatKind.MAIN:
            raise MainPersonaNotSelectable(chat_id)
        opening: OpeningMessage | None = None
        if filename is not None:
            lookup = context_mod.look_up_first_message(
                self._vault.first_messages, filename, self._display_names,
            )
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

    # -- Main: get-or-create, resolving its creation bundle only when needed

    def get_or_create_main(self, model: str) -> Chat:
        """Returns the singleton Main chat, creating it if this is the
        first time anything has asked for it.

        Checks `find_main` first so an *existing* Main never re-resolves
        `MAIN_CHAT_DIR`'s three files just to reopen — Concept.md: "that
        action reopens it even when its live profile is currently broken."
        Only when Main does not exist yet does this method resolve the
        complete creation bundle (`cfc.context.resolve_main_creation_bundle`)
        and freeze its First Message into an `OpeningMessage`; a
        `cfc.context.SourceUnavailable` here propagates straight to the
        caller, exactly like `send_turn`'s own context resolution, and no
        row is created (`ConversationStore.get_or_create_main` is never even
        called).

        A race with another call that creates Main in between this method's
        own resolution and its call into the store is not a problem this
        method needs to prevent: `ConversationStore.get_or_create_main` is
        itself race-safe, and simply discards this call's freshly resolved
        bundle in favour of the winner's already-stored one when that
        happens (Concept.md: "Both callers resolve and return that same
        canonical Main identity").
        """
        existing = self._store.find_main()
        if existing is not None:
            return existing
        _system_prompt, _persona, first_message = context_mod.resolve_main_creation_bundle(
            self._vault.main_chat, self._display_names,
        )
        opening = OpeningMessage(
            source_name=first_message.name, content=first_message.body,
            created_at=utc_now(), fingerprint=first_message.fingerprint,
        )
        return self._store.get_or_create_main(model, opening)

    # -- appearance: the one durable override, never a raw connection ------

    def get_appearance_override(self) -> str | None:
        """`None` when no override is saved, else `'dark'` or `'light'` —
        straight from `conversation_store.ConversationStore`, the narrow
        seam that lets `tui.py` reach this one durable record without ever
        holding a SQLite connection of its own.
        """
        return self._store.get_appearance_override()

    def save_appearance_override(self, value: str) -> None:
        self._store.save_appearance_override(value)

    def clear_appearance_override(self) -> None:
        self._store.clear_appearance_override()

    # -- the turn lifecycle -------------------------------------------------

    async def send_turn(self, chat_id: ChatId, user_content: str,
                         responder: Responder) -> Turn:
        """Resolve this chat's fresh context plan and current model, start a
        turn, and drive the provider continuation loop to the turn's one
        terminal outcome (Stage 6 loop 1): each request plan offers the
        registry's schemas (when file tools are usable and the selected
        model is declared tool-capable); a tool-call-batch reply is
        persisted before any `ApprovalPort` decision, its calls are
        processed sequentially through the registry, and the loop asks the
        provider to continue until a plain completion, failure, or
        cancellation ends the turn. A tool-free turn takes the identical
        path with zero batches.

        The context plan is resolved, and the request plan built, from
        `chat` as read once at the top of this call — before `start_turn`.
        A `cfc.context.SourceUnavailable` here propagates straight to the
        caller: no turn is started, so there is nothing for this method to
        end (mirrors `ActiveTurnExists`, below).

        The responder receives only the finished `RequestPlan` — nothing
        that could let it reach `cfc_turns`/`cfc_messages`, the vault, or a
        source body outside what is already on that plan. `ApprovalPort`
        similarly receives only a `PendingToolCall` — no store, roots, or
        mutable executor object.

        **Once this method has started a turn, that turn ends before this
        method does.** Every way out of the body below is covered:

        - an ordinary exception (from the responder, or from a result this
          module doesn't recognise) becomes one bounded, cfc-authored
          internal failure and is returned rather than raised, so a caller
          never handles "the responder raised" separately from "the
          responder returned Failure" — never `str(exc)` or `repr(result)`,
          which could carry a provider body, a request detail, or a
          credential (B-2.0-33);
        - cancellation of the task ends the turn as `CancelledOutcome` and
          then re-raises. Preserving what already committed is call-level,
          not just turn-level: cancellation delivered while a call awaits
          `ApprovalPort`, or noticed cooperatively during a call's own
          bounded execution, writes a cancellation result for that call and
          every later call in its batch, then finalises the turn — any call
          whose real outcome already committed stands untouched;
        - an interruption that is neither of those — `KeyboardInterrupt`,
          `SystemExit` — ends the turn as a typed interrupted failure and
          then keeps travelling, because swallowing those would make cfc
          un-interruptible; and
        - a store failure — `sqlite3.Error`, not `ConversationStoreError`,
          so the ordinary guards above cannot see it on their own
          (B-2.0-32) — mid-batch repairs the current and every later
          unanswered call in that batch with one typed failure result, as
          far as the store remains reachable, before re-raising so the turn
          still receives its terminal failure the same way. While ending
          the turn itself: never leaks a raw SQLite exception and never
          masks a `KeyboardInterrupt`/`SystemExit`/cancellation it happens
          alongside — ending an internal failure raises `TurnEndingFailed`
          instead of returning a `Turn` this module cannot honestly
          produce; ending an interruption or cancellation swallows it,
          since the original interruption or cancellation is the one thing
          this call must still deliver.

        `ActiveTurnExists` from `self._store.start_turn` is deliberately not
        caught here (D-2.0-36): it means this call never started a turn at
        all, so there is nothing for this method to end — it propagates
        straight to the caller as the typed refusal a presentation layer
        renders, before any responder is ever reached.

        Only a process that dies outright leaves an active turn or an
        unresolved call behind, and `open_store`'s reopen recovery is that
        case's route.
        """
        chat = self._store.get_chat(chat_id)
        context_plan = context_mod.build_context_plan(
            self._vault, chat.context_selection, chat.kind, self._display_names,
        )
        model = chat.context_selection.model
        manifest = context_plan.to_manifest()

        turn, _user_message = self._store.start_turn(chat_id, model, user_content, manifest)

        model_entry = self._models.entry_for(model)
        model_is_tool_capable = model_entry is not None and model_entry.tools
        schemas = self._registry.offered_schemas(self._file_tools, model_is_tool_capable)
        authority = FileAuthority.from_settings(self._file_tools)
        max_calls = (self._file_tools.max_calls_per_turn if self._file_tools.usable
                     else _DEFAULT_MAX_CALLS_PER_TURN)
        max_turn_chars = (self._file_tools.max_turn_result_chars if self._file_tools.usable
                          else _DEFAULT_MAX_TURN_RESULT_CHARS)

        exchange_usages: list[Usage | None] = []
        calls_used = 0
        turn_chars_used = 0

        try:
            while True:
                snapshot = self._store.snapshot(chat_id)
                plan = build_request_plan(context_plan, chat.opening, snapshot, model,
                                           schemas=schemas)
                result: ResponderResult = await responder.respond(plan)

                if isinstance(result, ToolCallBatch) and not schemas:
                    # Concept.md: "A further unsolicited tool-call response
                    # then fails as malformed instead of starting an
                    # endless tool loop" — applies identically whether
                    # schemas were never offered this turn or were
                    # withdrawn after the budget was spent.
                    result = Failure(FailureEvidence(
                        FailureKind.RESPONDER, _UNSOLICITED_TOOL_CALL_REASON,
                        problem=ProviderProblem.MALFORMED_RESPONSE,
                    ))

                if isinstance(result, ToolCallBatch):
                    exchange_usages.append(result.usage)
                    _exchange, calls = self._store.persist_tool_call_batch(
                        turn.id, model, result.calls, result.assistant_content, result.usage,
                    )
                    calls_used, turn_chars_used = await self._process_tool_call_batch(
                        turn.id, calls, authority, calls_used, turn_chars_used,
                        max_calls, max_turn_chars,
                    )
                    if calls_used >= max_calls or turn_chars_used >= max_turn_chars:
                        schemas = ()
                    continue

                usage = result.usage if isinstance(result, Completion) else None
                exchange_usages.append(usage)
                self._store.record_exchange(turn.id, model, _EXCHANGE_ENDING[type(result)],
                                             usage=usage)
                return self._apply_result(turn.id, result, _sum_usage(exchange_usages))
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

    async def _process_tool_call_batch(
        self, turn_id: TurnId, calls: tuple[ToolCall, ...], authority: FileAuthority,
        calls_used: int, turn_chars_used: int, max_calls: int, max_turn_chars: int,
    ) -> tuple[int, int]:
        """Processes one persisted batch's calls sequentially, in provider
        order. A refused, invalid, unavailable, or failed call never
        suppresses a later call in the same batch. Returns the turn's
        updated call/output budget counters.

        Cancellation noticed before a call is reached, or delivered while
        awaiting its `ApprovalPort` decision, marks that call and every
        later call in this batch as cancelled, then re-raises so
        `send_turn`'s own handler finalises the turn — any earlier call in
        this batch whose real outcome already committed stands untouched.
        A store failure while resolving a call is repaired the same way,
        with a typed failure instead of a cancellation, then re-raised.
        """
        for index, call in enumerate(calls):
            if _current_task_cancel_requested():
                self._repair_remaining_calls(
                    calls[index:], ToolOutcomeKind.CANCELLATION,
                    "cancelled before this call was reached",
                )
                return calls_used, turn_chars_used
            try:
                calls_used, turn_chars_used = await self._process_one_call(
                    turn_id, call, authority, calls_used, turn_chars_used,
                    max_calls, max_turn_chars,
                )
            except asyncio.CancelledError:
                self._repair_remaining_calls(
                    calls[index:], ToolOutcomeKind.CANCELLATION,
                    "cancelled while awaiting approval",
                )
                raise
            except sqlite3.Error:
                self._repair_remaining_calls(
                    calls[index:], ToolOutcomeKind.FAILURE,
                    "cfc's store failed before this call could be resolved",
                )
                raise
        return calls_used, turn_chars_used

    async def _process_one_call(
        self, turn_id: TurnId, call: ToolCall, authority: FileAuthority,
        calls_used: int, turn_chars_used: int, max_calls: int, max_turn_chars: int,
    ) -> tuple[int, int]:
        """One call's full lifecycle: registry lookup, availability,
        argument validation, budget, approval, execution, and its exactly-
        one committed result plus operational evidence. Any `sqlite3.Error`
        or `asyncio.CancelledError` here is deliberately left to propagate
        to `_process_tool_call_batch`'s own repair-and-reraise handling.
        """
        definition = self._registry.get(call.name)
        if definition is None:
            self._store.record_tool_result(
                call.id, ToolOutcomeKind.UNAVAILABLE, f"unknown tool {call.name!r}", "")
            return calls_used, turn_chars_used

        unavailable_reason = definition.availability(self._file_tools)
        if unavailable_reason is not None:
            self._store.record_tool_result(
                call.id, ToolOutcomeKind.UNAVAILABLE, unavailable_reason, "")
            return calls_used, turn_chars_used

        parsed_args, argument_error = definition.validate_arguments(call.arguments)
        if argument_error is not None:
            self._store.record_tool_result(call.id, ToolOutcomeKind.FAILURE, argument_error, "")
            return calls_used, turn_chars_used

        if calls_used >= max_calls:
            self._store.record_tool_result(
                call.id, ToolOutcomeKind.REFUSAL,
                f"the turn's {max_calls}-call budget is spent", "")
            return calls_used, turn_chars_used
        if turn_chars_used >= max_turn_chars:
            self._store.record_tool_result(
                call.id, ToolOutcomeKind.REFUSAL,
                f"the turn's {max_turn_chars:,}-character output budget is spent", "")
            return calls_used, turn_chars_used

        pending = PendingToolCall(
            turn_id=turn_id, tool_call_id=call.id, provider_call_id=call.provider_call_id,
            name=call.name, arguments=parsed_args,
            description=definition.describe_pending(parsed_args), capability=definition.capability,
        )
        decision = await self._approval_port.decide(pending)
        decided_at = utc_now()

        if decision is not ApprovalDecision.APPROVE:
            self._store.record_tool_result(
                call.id, ToolOutcomeKind.REFUSAL, "declined", "",
                decision=ApprovalDecision.REFUSE, decided_at=decided_at,
            )
            return calls_used, turn_chars_used

        started_at = utc_now()
        outcome = definition.execute(
            parsed_args, authority, self._file_tools, _current_task_cancel_requested,
        )
        finished_at = utc_now()

        self._store.record_tool_result(
            call.id, outcome.kind, outcome.reason, outcome.content,
            decision=ApprovalDecision.APPROVE, decided_at=decided_at, truncated=outcome.truncated,
        )
        self._store.record_tool_call_evidence(ToolCallEvidence(
            tool_call_id=call.id, definition_name=call.name,
            started_at=started_at, finished_at=finished_at, outcome_kind=outcome.kind,
            reason=outcome.reason, character_count=len(outcome.content),
            root=outcome.root, canonical_target=outcome.canonical_target,
            counts=outcome.counts, truncated=outcome.truncated,
        ))
        return calls_used + 1, turn_chars_used + len(outcome.content)

    def _repair_remaining_calls(
        self, calls: tuple[ToolCall, ...], kind: ToolOutcomeKind, reason: str,
    ) -> None:
        """Best-effort typed repair for calls this turn never got to
        resolve — tolerates a still-broken store (B-2.0-32's "reopen
        recovery remains" discipline) and a call whose real outcome already
        committed (`ConflictingToolResult`, left untouched: that commit
        already won).
        """
        for call in calls:
            try:
                self._store.record_tool_result(call.id, kind, reason, "")
            except ConflictingToolResult:
                pass
            except (ConversationStoreError, sqlite3.Error):
                pass  # the store itself is unreachable; reopen recovery remains

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

    def _apply_result(
        self, turn_id: TurnId, result: ResponderResult, summed_usage: Usage | None,
    ) -> Turn:
        """Finalises the turn for a tool-free `ResponderResult` (never a
        `ToolCallBatch`, which `send_turn`'s own loop always continues past
        rather than finalising). `summed_usage` is the whole turn's
        field-by-field usage sum across every exchange (`_sum_usage`) — used
        only for `Completion`; a single-exchange tool-free turn's sum is
        exactly that exchange's own usage.
        """
        if isinstance(result, Completion):
            return self._store.complete_turn(turn_id, result.content, summed_usage)
        if isinstance(result, Failure):
            return self._store.fail_turn(turn_id, result.evidence)
        if isinstance(result, Cancellation):
            return self._store.cancel_turn(turn_id)
        raise TypeError(f"responder returned an unrecognised result: {result!r}")


def open_service(
    path, vault: VaultSettings, export_dir=None,
    display_names: DisplayNameSettings | None = None,
    file_tools: FileToolSettings | None = None,
    models: ModelCatalogue | None = None,
    registry: ToolRegistry | None = None,
    approval_port: ApprovalPort | None = None,
) -> ConversationService:
    """Open the store at `path` and wrap it, with `vault`, `export_dir`,
    `display_names`, and the Stage 6 loop 1 tool-lifecycle collaborators,
    in a `ConversationService`. `path` must already be resolved, exactly
    like `conversation_store.open_store`; `vault` is `cfc.settings.
    build_vault_settings`'s own already-resolved output, `export_dir` is
    `cfc.settings.ExportSettings.path`, `display_names` is `cfc.settings.
    build_display_name_settings`'s own already-resolved output, `file_tools`
    is `cfc.settings.build_file_tool_settings`'s own already-resolved
    output, and `models` is `cfc.settings.build_model_catalogue`'s own
    already-resolved output — this module never resolves a config snapshot
    itself. `registry` defaults to `cfc.tool_registry.default_registry()`;
    `approval_port` has no safe default that approves anything, so an
    omitted one refuses every call rather than guessing.
    """
    return ConversationService(
        open_store(path), vault, export_dir, display_names,
        file_tools=file_tools, models=models, registry=registry, approval_port=approval_port,
    )
