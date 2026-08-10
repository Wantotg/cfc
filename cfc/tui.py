"""tui.py — the 2.0 Textual presentation layer: the Hub, the Chat screen,
their modals, the composer, and the `App` that wires them to the real Stage 3
conversation service, store, and provider adapter.

Textual alone owns terminal input and rendering (`HANDOVER.md`'s live rules).
This module is the only place that imports `textual` inside `cfc/` — every
module it depends on (`cfc.conversation_service`, `cfc.conversation_types`,
`cfc.settings`, `cfc.provider_adapter`) stays presentation-free, so a later
screen or a headless script can use them without pulling in a terminal
framework.

`build_app` is the one composition seam this module offers: it resolves
configuration, opens the store, builds the responder, and returns a ready
`App` — either a working `CfcApp` or a `StartupFailureApp` that explains why
real chat is unavailable. `python -m cfc` and the test suite both call it;
neither constructs a fake or partial application of its own (Work Order
Step 3's "same app construction seam in tests as runtime").

Turn state lives on `CfcApp`, not on any `Screen`: `_TurnRun` records what
the most recent `send_turn` call for a chat is doing or did, keyed by
`ChatId.value`, independent of whether that chat's `ChatScreen` is currently
mounted. A `ChatScreen` always renders by re-reading the store's canonical
snapshot plus this run state — never an optimistic local copy — so
background completion while a person is elsewhere is never lost and never
invented (Concept.md's "optimistic drift" failure mode).
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Static
from textual.widgets import TextArea
from textual.worker import Worker

from cfc import config_loader, diagnostics, provider_adapter, settings
from cfc import context as context_mod
from cfc.context import FirstMessageState, SourceOption
from cfc.conversation_service import CategoryState, ConversationService, ContextRows, open_service
from cfc import conversation_store
from cfc.conversation_store import ConversationStoreError
from cfc.conversation_types import (
    CancelledOutcome,
    Chat,
    ChatId,
    CompletedOutcome,
    ContextCategory,
    ContextManifestEntry,
    ConversationSnapshot,
    FailedOutcome,
    Message as StoredMessage,
    OpeningMessage,
    Role,
    Turn,
    TurnId,
)
from cfc.provider_wire import Responder
from cfc.settings import ModelCatalogueEntry

#: At this width and wider, `ChatScreen` keeps the stored-chat switcher
#: docked beside the conversation; below it, the switcher is removed from
#: the layout and the same choices move to `ChatsModal` (the first
#: interaction slice's own breakpoint decision — see the TUI contract).
_WIDE_BREAKPOINT = 80

#: B-2.0-33's rule extends to this layer: a worker exception this module did
#: not expect (typically `conversation_service.TurnEndingFailed`, a real
#: store failure) is never shown as `str(exc)` — one bounded, cfc-authored
#: sentence, the same discipline `conversation_service` already applies to
#: what gets stored.
_WORKER_FAILURE_MESSAGE = (
    "cfc could not record how this turn ended. Reopening this chat will show "
    "its true stored state."
)

_BLANK_DRAFT_NOTICE = "A message can't be blank."
_CHAT_BUSY_NOTICE = "A request is already in progress in this chat; wait or press Esc to cancel it."


def _context_unavailable_notice(exc: context_mod.SourceUnavailable) -> str:
    """Concept.md's "Selected source disappears": a selected file that is
    missing, unreadable, blank, invalid UTF-8, or otherwise unusable blocks
    the turn *before* anything is sent or stored, keeps the draft, and
    names the category and source with a correction route back to Context.
    """
    category_label = exc.category.value.replace("_", " ")
    return (
        f"cfc could not use the selected {category_label} ({exc.name}): {exc.reason}. "
        f"Open Context to change or fix the selection."
    )

#: What an omitted (failed or cancelled) turn's outcome line says about its
#: future — never that the provider certainly never received the original
#: request, since a timeout or an HTTP failure can happen after delivery
#: (Concept.md's "False delivery claim" failure mode; B-2.0-55/D-2.0-53).
_OMISSION_NOTICE = (
    "cfc will not include this message in later requests, so later replies "
    "cannot see it. Use Restore to composer to send it again."
)
_RESTORE_LABEL = "Restore to composer"
_RESTORE_BUSY_NOTICE = (
    "The composer already has a draft; clear or send it before restoring "
    "an omitted message."
)
_RESTORE_MISSING_NOTICE = (
    "cfc could not find that turn's stored message; nothing was restored."
)


# --- per-chat turn run state, owned by the App, not any Screen --------------

@dataclass
class _TurnRun:
    """What the most recent `send_turn` call for one chat is doing or did.
    `status` is `"running"`, `"completed"`, `"failed"`, or `"cancelled"`.
    `turn` is the real stored `Turn` when one exists; `message` is set only
    for a failure this module intercepted before `conversation_service`
    could produce a `Turn` at all (B-2.0-32's `TurnEndingFailed`, or any
    other worker-level exception this loop did not foresee).
    """
    status: str
    turn: Turn | None = None
    message: str | None = None


# --- the composer: Enter submits, Shift+Enter inserts a literal newline ----

class Composer(TextArea):
    """A `TextArea` bound the opposite way most multiline editors bind these
    two keys, because this loop's chat client sends on Enter (Concept.md,
    the user-visible shape). Overriding `_on_key` rather than a binding is
    what `TextArea` itself does for its own Enter-inserts-newline default
    (see `textual.widgets._text_area.TextArea._on_key`) — there is no public
    "submit key" hook to redirect instead.
    """

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    async def _on_key(self, event: events.Key) -> None:
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.post_message(self.Submitted(self.text))
            return
        if event.key == "shift+enter":
            event.prevent_default()
            event.stop()
            start, end = self.selection
            self.replace("\n", start, end)
            return
        await super()._on_key(event)


# --- modals ------------------------------------------------------------

class NewChatModal(ModalScreen[str | None]):
    """A non-blank submitted title dismisses with that title; `Esc` or
    Cancel dismisses with `None` and creates nothing (Concept.md).
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="new-chat-dialog"):
            yield Label("New chat title")
            yield Input(placeholder="Title", id="new-chat-title")
            yield Static("", id="new-chat-error", markup=False)
            with Horizontal():
                yield Button("Create", id="new-chat-create", variant="primary")
                yield Button("Cancel", id="new-chat-cancel")

    def on_mount(self) -> None:
        self.query_one("#new-chat-title", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "new-chat-create":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        field = self.query_one("#new-chat-title", Input)
        title = field.value
        if not title.strip():
            self.query_one("#new-chat-error", Static).update("Title can't be blank.")
            field.focus()
            return
        self.dismiss(title)


class ChatsModal(ModalScreen[ChatId | None]):
    """The narrow-terminal equivalent of the wide layout's docked switcher —
    the same stored chats, the same selection action, reached through a
    modal instead of a permanent pane (Concept.md).
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="chats-modal-dialog"):
            yield Label("Chats")
            yield ListView(id="chats-modal-list")

    async def on_mount(self) -> None:
        list_view = self.query_one("#chats-modal-list", ListView)
        for chat in self.app.service.list_chats():
            item = ListItem(Static(chat.title, markup=False))
            item.chat_id = chat.id
            await list_view.append(item)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.chat_id)


#: Stage 4's complete interaction vocabulary, shown by `KeyboardHelpModal`
#: (Concept.md's "Keyboard help lives in the interface").
_KEYBOARD_HELP_LINES = (
    "Enter — send the composer's text as a new turn",
    "Shift+Enter — insert a newline in the composer",
    "Esc — closes an open modal, else cancels an active turn, else returns to the Hub",
    "F2 — opens the stored-chats switcher",
    "Ctrl+P — opens this command palette",
    "Ctrl+Q — quits cfc",
)

_KEYBOARD_HELP_TERMINAL_NOTE = (
    "Shift+Enter needs a terminal that reports modified Enter through the "
    "Kitty keyboard protocol. Without one, Shift+Enter behaves like Enter — "
    "cfc adds no fallback newline key."
)

#: The literal, tested Windows Terminal mapping. Its escape spelling is
#: shown as text, exactly as it must appear in settings.json - never as a
#: live escape character (Work Order Step 4).
_KEYBOARD_HELP_WINDOWS_TERMINAL = (
    "Windows Terminal — add this entry to settings.json's \"actions\" array:\n"
    '{ "command": { "action": "sendInput", "input": "\\u001b[13;2u" }, "keys": "shift+enter" }'
)


class KeyboardHelpModal(ModalScreen[None]):
    """Opened from the cfc command palette's **Keyboard help** command.
    Follows the same `Esc`-first layering as every other modal here: closing
    this modal is all one `Esc` press does.
    """

    BINDINGS = [Binding("escape", "dismiss_help", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="keyboard-help-dialog"):
            yield Label("Keyboard help")
            for line in _KEYBOARD_HELP_LINES:
                yield Static(line, markup=False)
            yield Static(_KEYBOARD_HELP_TERMINAL_NOTE, markup=False)
            yield Static(
                _KEYBOARD_HELP_WINDOWS_TERMINAL,
                id="keyboard-help-windows-terminal", markup=False,
            )
            yield Button("Close", id="keyboard-help-close")

    def action_dismiss_help(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "keyboard-help-close":
            self.dismiss(None)


# --- Context: selection, inspection, and one literal preview route --------

class _ClearSelection:
    """Sentinel `SourcePickerModal` dismisses with when a person explicitly
    picks **None (clear selection)** — distinct from `None`, this module's
    existing "closed without choosing anything" meaning (`NewChatModal`,
    `ChatsModal`, this same picker's own Cancel/Esc route).
    """


_CLEAR_SELECTION = _ClearSelection()

_FINGERPRINT_DISPLAY_CHARS = 12


def _short_fingerprint(fingerprint: str) -> str:
    return fingerprint[:_FINGERPRINT_DISPLAY_CHARS]


def _source_record_text(record) -> str:
    return f"{record.display_name}, {record.character_count} chars, {_short_fingerprint(record.fingerprint)}"


#: What a row says after naming why a category cannot be used at all — the
#: correction route for every `settings.VaultCategorySettings` reason, all of
#: which are `config.py` fields (B-2.0-62). Distinct from a broken selected
#: file's route, which is the vault itself.
_CATEGORY_CONFIG_ROUTE = "correct config.py to use this category"


def _category_state_text(state: CategoryState) -> str:
    """One category row's text. A category with no usable configured
    directory says so first (B-2.0-62): `none selected` alone would report
    an ordinary empty choice for something cfc already knows cannot be
    chosen, which is what sent a whole playtest looking for a selector that
    was never going to appear.
    """
    if state.category_unavailable_reason is not None:
        prefix = f"unavailable ({state.category_unavailable_reason}) — {_CATEGORY_CONFIG_ROUTE}"
        if state.selected_name is None:
            return prefix
        return f"{prefix}; {state.selected_name} stays selected until you clear it"
    if state.selected_name is None:
        return "none selected"
    if state.source is not None:
        return _source_record_text(state.source)
    return f"unavailable ({state.unavailable_reason}) — open to correct"


def _first_message_row_text(
    opening: OpeningMessage | None, lookup, category_unavailable_reason: str | None = None,
) -> str:
    """The First Message row. A frozen opening always wins — it is stored
    conversation content and no later configuration change can unsay it. An
    unusable First Messages directory is named with the `config.py` route
    (B-2.0-62); a companion that exists but cannot be read keeps the vault
    route it always had.
    """
    if opening is not None:
        return (f"{opening.source_name}, {len(opening.content)} chars, "
                f"{_short_fingerprint(opening.fingerprint)}")
    if category_unavailable_reason is not None:
        return f"unavailable ({category_unavailable_reason}) — {_CATEGORY_CONFIG_ROUTE}"
    if lookup is None:
        return "none for no persona selected"
    if lookup.state is FirstMessageState.ABSENT:
        return "none for this persona"
    if lookup.state is FirstMessageState.UNAVAILABLE:
        return f"unavailable ({lookup.reason}) — open to correct"
    return "not used — this chat already had turns when the persona was selected"


class SourcePreviewModal(ModalScreen[None]):
    """One source's literal text, Textual markup disabled — reached by
    selecting any Context row, never editable here (Concept.md: "System
    Instructions is inspectable but not user-editable in cfc").
    """

    BINDINGS = [Binding("escape", "close", "Close", show=False)]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="source-preview-dialog"):
            yield Label(self._title, markup=False)
            with VerticalScroll(id="source-preview-scroll"):
                yield Static(self._body, id="source-preview-body", markup=False)
            yield Button("Close", id="source-preview-close")

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "source-preview-close":
            self.dismiss(None)


class SourcePickerModal(ModalScreen[object]):
    """A Change/Add picker: `available_sources`' unambiguous candidates,
    plus an explicit **None (clear selection)** entry when `allow_clear`
    (Change only — Add always adds something). Dismisses with the chosen
    exact filename, `_CLEAR_SELECTION`, or `None` for Cancel/Esc.

    `notice`, when given, is why this category has nothing to offer
    (B-2.0-62). A picker that opens on one bare **None (clear selection)**
    row and no explanation is what a person reads as "cfc doesn't do this",
    so an unusable category says why it is empty, and still offers the clear
    route for a selection made while it worked.
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, title: str, options: tuple[SourceOption, ...], *,
                 allow_clear: bool, notice: str | None = None) -> None:
        super().__init__()
        self._title = title
        self._options = options
        self._allow_clear = allow_clear
        self._notice = notice

    def compose(self) -> ComposeResult:
        with Vertical(id="source-picker-dialog"):
            yield Label(self._title, markup=False)
            yield ListView(id="source-picker-list")
            if self._notice is not None:
                yield Static(self._notice, id="source-picker-notice", markup=False)
            elif not self._options and not self._allow_clear:
                yield Static("Nothing available to select.", id="source-picker-empty", markup=False)
            yield Button("Cancel", id="source-picker-cancel")

    async def on_mount(self) -> None:
        list_view = self.query_one("#source-picker-list", ListView)
        if self._allow_clear:
            item = ListItem(Static("None (clear selection)", markup=False))
            item.picked_value = _CLEAR_SELECTION
            await list_view.append(item)
        for option in self._options:
            item = ListItem(Static(option.display_name, markup=False))
            item.picked_value = option.name
            await list_view.append(item)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.picked_value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "source-picker-cancel":
            self.dismiss(None)


class ContextModal(ModalScreen[None]):
    """The selector and inspection route for one chat's named context
    (Concept.md's "Context is part of Chat, not a hidden startup choice").
    Lists System Instructions, User Preferences, Persona, each selected
    Trait, an Add-trait row, and First Message, in request order. Selecting
    a row opens its literal preview; Change/Add/Remove act on whichever row
    is currently highlighted, kept in sync by keyboard and mouse alike since
    both drive the same `ListView` highlight.
    """

    BINDINGS = [Binding("escape", "close", "Close", show=False)]

    def __init__(self, chat_id: ChatId) -> None:
        super().__init__()
        self.chat_id = chat_id

    def compose(self) -> ComposeResult:
        with Vertical(id="context-modal-dialog"):
            yield Label("Context", markup=False)
            yield ListView(id="context-modal-list")
            yield Static("", id="context-modal-error", markup=False)
            with Horizontal(id="context-modal-actions"):
                yield Button("Change", id="context-action-change", disabled=True)
                yield Button("Add", id="context-action-add", disabled=True)
                yield Button("Remove", id="context-action-remove", disabled=True)
                yield Button("Close", id="context-action-close")

    async def on_mount(self) -> None:
        await self.refresh_rows()

    def _mutate_selection(self, mutate: Callable[[], None]) -> bool:
        """Runs one selection-changing store call, catching the one refusal
        a concurrent active turn can raise (Concept.md: "refused while that
        chat has an active turn") — an unhandled `ActiveTurnExists` here
        would otherwise crash the app rather than showing a bounded notice.
        Returns whether it actually applied.
        """
        try:
            mutate()
        except conversation_store.ActiveTurnExists:
            self.query_one("#context-modal-error", Static).update(
                "This chat has a request in progress; wait or cancel it before "
                "changing its context."
            )
            return False
        self.query_one("#context-modal-error", Static).update("")
        return True

    async def _append_row(self, list_view: ListView, kind: object, text: str) -> None:
        item = ListItem(Static(text, markup=False))
        item.row_kind = kind
        await list_view.append(item)

    async def refresh_rows(self) -> None:
        list_view = self.query_one("#context-modal-list", ListView)
        previous_index = list_view.index
        await list_view.clear()
        chat = self.app.service.get_chat(self.chat_id)
        rows: ContextRows = self.app.service.context_rows(self.chat_id)

        await self._append_row(
            list_view, "system_instructions",
            f"System Instructions: {_source_record_text(rows.system_instructions)}",
        )
        await self._append_row(
            list_view, "user_preferences",
            f"User Preferences: {_category_state_text(rows.user_preferences)}",
        )
        await self._append_row(list_view, "persona", f"Persona: {_category_state_text(rows.persona)}")
        for trait in rows.traits:
            await self._append_row(
                list_view, ("trait", trait.selected_name),
                f"Trait: {_category_state_text(trait)}",
            )
        await self._append_row(list_view, "add_trait", self._add_trait_row_text())
        await self._append_row(
            list_view, "first_message",
            "First Message: " + _first_message_row_text(
                chat.opening, rows.first_message,
                self.app.service.category_unavailable_reason(ContextCategory.FIRST_MESSAGE),
            ),
        )

        if previous_index is not None and list_view.children and previous_index < len(list_view.children):
            list_view.index = previous_index
        self._update_actions()

    def _add_trait_row_text(self) -> str:
        """The Add-trait row names an unusable Traits category itself
        (B-2.0-62), rather than offering an action whose only outcome is an
        empty picker.
        """
        reason = self.app.service.category_unavailable_reason(ContextCategory.TRAIT)
        if reason is None:
            return "Add trait…"
        return f"Add trait… unavailable ({reason}) — {_CATEGORY_CONFIG_ROUTE}"

    def _current_kind(self) -> object:
        list_view = self.query_one("#context-modal-list", ListView)
        item = list_view.highlighted_child
        return getattr(item, "row_kind", None) if item is not None else None

    def _update_actions(self) -> None:
        kind = self._current_kind()
        self.query_one("#context-action-change", Button).disabled = kind not in (
            "user_preferences", "persona",
        )
        self.query_one("#context-action-add", Button).disabled = kind != "add_trait"
        self.query_one("#context-action-remove", Button).disabled = not (
            isinstance(kind, tuple) and kind[0] == "trait"
        )

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        self._update_actions()

    async def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Selecting (Enter or click) a row previews it — the same one
        operation regardless of input device (Work Order Step 4). The
        Add-trait row's own "preview" is opening its picker, since it has
        no source of its own to show literal text for.
        """
        kind = getattr(event.item, "row_kind", None)
        if kind == "add_trait":
            self._begin_add()
            return
        chat = self.app.service.get_chat(self.chat_id)
        rows: ContextRows = self.app.service.context_rows(self.chat_id)
        if kind == "system_instructions":
            self._open_preview("System Instructions", rows.system_instructions.body)
        elif kind == "user_preferences":
            self._open_category_preview("User Preferences", rows.user_preferences)
        elif kind == "persona":
            self._open_category_preview("Persona", rows.persona)
        elif isinstance(kind, tuple) and kind[0] == "trait":
            filename = kind[1]
            state = next((t for t in rows.traits if t.selected_name == filename), None)
            self._open_category_preview(f"Trait: {filename}", state)
        elif kind == "first_message":
            if chat.opening is not None:
                self._open_preview("First Message", chat.opening.content)
            else:
                self._open_preview(
                    "First Message", _first_message_row_text(None, rows.first_message),
                )

    def _open_category_preview(self, title: str, state: CategoryState | None) -> None:
        if state is not None and state.category_unavailable_reason is not None and (
            state.source is None
        ):
            self._open_preview(
                title,
                f"unavailable: {state.category_unavailable_reason}\n\n{_CATEGORY_CONFIG_ROUTE}.",
            )
        elif state is None or state.selected_name is None:
            self._open_preview(title, "none selected")
        elif state.source is not None:
            self._open_preview(title, state.source.body)
        else:
            self._open_preview(title, f"unavailable: {state.unavailable_reason}")

    def _open_preview(self, title: str, body: str) -> None:
        self.app.push_screen(SourcePreviewModal(title, body))

    def _begin_change(self) -> None:
        kind = self._current_kind()
        if kind not in ("user_preferences", "persona"):
            return
        category = (ContextCategory.USER_PREFERENCES if kind == "user_preferences"
                    else ContextCategory.PERSONA)
        title = "Change User Preferences" if kind == "user_preferences" else "Change Persona"
        options = self.app.service.available_sources(category)
        notice = self.app.service.category_unavailable_reason(category)
        if notice is not None:
            notice = f"{notice} — {_CATEGORY_CONFIG_ROUTE}."

        async def handle_result(result: object) -> None:
            if result is None:
                return
            filename = None if result is _CLEAR_SELECTION else result
            if category is ContextCategory.USER_PREFERENCES:
                self._mutate_selection(lambda: self.app.service.set_user_preferences(
                    self.chat_id, filename))
            else:
                self._mutate_selection(lambda: self.app.service.set_persona(self.chat_id, filename))
            await self.refresh_rows()

        self.app.push_screen(
            SourcePickerModal(title, options, allow_clear=True, notice=notice), handle_result)

    def _begin_add(self) -> None:
        already_selected = {t.selected_name for t in self.app.service.context_rows(self.chat_id).traits}
        options = tuple(
            option for option in self.app.service.available_sources(ContextCategory.TRAIT)
            if option.name not in already_selected
        )
        notice = self.app.service.category_unavailable_reason(ContextCategory.TRAIT)
        if notice is not None:
            notice = f"{notice} — {_CATEGORY_CONFIG_ROUTE}."

        async def handle_result(result: object) -> None:
            if result is None or result is _CLEAR_SELECTION:
                return
            self._mutate_selection(lambda: self.app.service.add_trait(self.chat_id, result))
            await self.refresh_rows()

        self.app.push_screen(
            SourcePickerModal("Add trait", options, allow_clear=False, notice=notice), handle_result)

    async def _handle_remove(self) -> None:
        kind = self._current_kind()
        if not (isinstance(kind, tuple) and kind[0] == "trait"):
            return
        self._mutate_selection(lambda: self.app.service.remove_trait(self.chat_id, kind[1]))
        await self.refresh_rows()

    def action_close(self) -> None:
        self.dismiss(None)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "context-action-close":
            self.dismiss(None)
        elif button_id == "context-action-change":
            self._begin_change()
        elif button_id == "context-action-add":
            self._begin_add()
        elif button_id == "context-action-remove":
            await self._handle_remove()


# --- Model: chat state, the required default always usable ----------------

class ModelModal(ModalScreen[object]):
    """The available chat-model picker (Concept.md's "Model choice is chat
    state"). Lists every catalogue entry marked chat-selectable, always
    including the required default (`MODEL`) even when it is absent from
    the catalogue, and always including the chat's current model even when
    it is no longer listed — labelled `not in the current catalogue` rather
    than hidden (Concept.md: "cfc never silently changes a conversation's
    model"). Dismisses with the chosen exact provider id, or `None` for
    Cancel/Esc — choosing the row already marked current is a legitimate,
    harmless "no-op change".
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel", show=False)]

    def __init__(self, current_model: str, default_model: str, models: "settings.ModelCatalogue") -> None:
        super().__init__()
        self._current_model = current_model
        self._default_model = default_model
        self._models = models

    def _candidate_ids(self) -> list[str]:
        ids = [entry.id for entry in self._models.selectable_entries()]
        if self._default_model not in ids:
            ids.insert(0, self._default_model)
        if self._current_model not in ids:
            ids.append(self._current_model)
        return ids

    def compose(self) -> ComposeResult:
        with Vertical(id="model-modal-dialog"):
            yield Label("Model", markup=False)
            yield ListView(id="model-modal-list")
            if self._models.unavailable_reason:
                yield Static(self._models.unavailable_reason, id="model-modal-notice", markup=False)
            yield Button("Cancel", id="model-modal-cancel")

    async def on_mount(self) -> None:
        list_view = self.query_one("#model-modal-list", ListView)
        for model_id in self._candidate_ids():
            parts = [model_id]
            if model_id == self._current_model:
                parts.append("(current)")
                if self._models.entry_for(model_id) is None:
                    parts.append("(not in the current catalogue)")
            item = ListItem(Static(" ".join(parts), markup=False))
            item.model_id = model_id
            await list_view.append(item)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.model_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "model-modal-cancel":
            self.dismiss(None)


# --- the Hub -------------------------------------------------------------

class HubScreen(Screen):
    """The complete overview: every stored chat, an honest empty state, and
    ordinary new-chat creation. Refreshed on mount and every time it becomes
    the active screen again (`on_screen_resume`) — a chat created or
    completed while this screen was not on top must still be current the
    next time a person sees it.
    """

    BINDINGS = [Binding("n", "new_chat", "New chat")]

    def compose(self) -> ComposeResult:
        with Vertical(id="hub-body"):
            yield Static(
                "No stored chats yet. Select New chat to start one.",
                id="hub-empty", markup=False,
            )
            yield ListView(id="hub-chat-list")
            yield Button("New chat", id="hub-new-chat-button")
        yield Footer()

    async def on_mount(self) -> None:
        await self.refresh_chats()

    async def on_screen_resume(self) -> None:
        await self.refresh_chats()

    async def refresh_chats(self) -> None:
        chats = self.app.service.list_chats()
        list_view = self.query_one("#hub-chat-list", ListView)
        await list_view.clear()
        empty = self.query_one("#hub-empty", Static)
        empty.display = not chats
        list_view.display = bool(chats)
        for chat in chats:
            item = ListItem(Static(chat.title, markup=False))
            item.chat_id = chat.id
            await list_view.append(item)

    def action_new_chat(self) -> None:
        self.app.push_screen(NewChatModal(), self._handle_new_chat_result)

    def _handle_new_chat_result(self, title: str | None) -> None:
        if title is None:
            return
        chat = self.app.service.create_chat(title, self.app.default_model)
        self.app.open_chat(chat.id)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.app.open_chat(event.item.chat_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "hub-new-chat-button":
            self.action_new_chat()


# --- Chat ------------------------------------------------------------------

class ChatScreen(Screen):
    """One chat's title/back route, independently scrollable transcript,
    status/action line, and fixed composer (Concept.md's four persistent
    regions).

    A fresh instance is built every `open_chat` call — Textual's own screen
    stack destroys a non-installed screen's widget tree on `pop_screen`
    (`App._replace_screen`), so caching the `Screen` object itself would not
    have preserved anything. The transcript and status are always rebuilt
    from canonical state anyway (`refresh_from_service`); only the draft has
    nowhere else to live, so `CfcApp` carries it explicitly
    (`save_draft`/`get_draft`), saved on `on_screen_suspend` — the message
    Textual posts before removal — and restored on mount.
    """

    BINDINGS = [
        Binding("escape", "handle_escape", "Back", show=True),
        Binding("f2", "show_chats", "Chats", show=True),
    ]

    def __init__(self, chat_id: ChatId, chat_title: str) -> None:
        super().__init__()
        self.chat_id = chat_id
        self.chat_title = chat_title
        self._notice: str = ""
        self._refresh_lock = asyncio.Lock()

    def compose(self) -> ComposeResult:
        yield Static(self.chat_title, id="chat-title-bar", markup=False)
        yield Static("", id="chat-context-bar", markup=False)
        with Horizontal(id="chat-body"):
            yield VerticalScroll(id="chat-transcript")
            yield ListView(id="chat-switcher")
        yield Static("", id="chat-status", markup=False)
        yield Composer(id="chat-composer")
        yield Footer()

    async def on_mount(self) -> None:
        self._apply_breakpoint()
        await self.refresh_from_service()
        self.query_one(Composer).text = self.app.get_draft(self.chat_id)
        self.query_one(Composer).focus()

    async def on_screen_resume(self) -> None:
        await self.refresh_from_service()
        self.query_one(Composer).focus()

    async def on_screen_suspend(self) -> None:
        self.app.save_draft(self.chat_id, self.query_one(Composer).text)

    def on_resize(self, event: events.Resize) -> None:
        self._apply_breakpoint()

    def _apply_breakpoint(self) -> None:
        wide = self.size.width >= _WIDE_BREAKPOINT
        self.query_one("#chat-switcher", ListView).display = wide

    # -- rendering from canonical state ----------------------------------

    async def refresh_from_service(self) -> None:
        """Re-read the store's chat record and snapshot and this chat's run
        state, and rebuild the transcript, context bar, and status line from
        them — never an optimistic patch. Called on mount, on resume, and
        whenever the app-owned worker for this chat changes state.

        One rebuild at a time (B-2.0-60). Three callers reach this method
        from three different asyncio tasks: `on_screen_resume` and
        `on_mount` run on this screen's own message pump; a dismissed
        modal's result callback (`_handle_context_result`,
        `_handle_model_result`) runs on the App's pump, because
        `App.push_screen` records the App as the callback's requester; and
        `notify_run_changed` is awaited directly from the turn worker's
        task. Without this lock two of them interleave across the `await`
        inside `_render_transcript`, both clear the transcript and both
        mount their own widgets, and the second mount crashes on the first's
        already-mounted `restore-<turn>` button. Serialising is correct
        rather than merely safe: every rebuild re-reads canonical state, so
        a queued second pass renders the newer truth, not a stale repeat.
        """
        async with self._refresh_lock:
            chat = self.app.service.get_chat(self.chat_id)
            snapshot = self.app.service.snapshot(self.chat_id)
            await self._render_transcript(chat, snapshot)
            self._render_context_bar(chat)
            self._render_status()
            await self._render_switcher()

    async def _render_transcript(self, chat: Chat, snapshot: ConversationSnapshot) -> None:
        transcript = self.query_one("#chat-transcript", VerticalScroll)
        was_at_bottom = transcript.is_vertical_scroll_end
        await transcript.remove_children()
        await transcript.mount_all(self._build_transcript_widgets(chat, snapshot))
        if was_at_bottom:
            transcript.scroll_end(animate=False)

    def _build_transcript_widgets(self, chat: Chat, snapshot: ConversationSnapshot) -> list[Widget]:
        return _transcript_widgets(snapshot, chat.opening, self.app.service, self.app._models)

    def _render_context_bar(self, chat: Chat) -> None:
        bar = self.query_one("#chat-context-bar", Static)
        bar.update(_context_bar_text(chat))

    def _render_status(self) -> None:
        status_widget = self.query_one("#chat-status", Static)
        status_widget.update(self._notice or _status_text(self.app.turn_status(self.chat_id)))

    async def _render_switcher(self) -> None:
        switcher = self.query_one("#chat-switcher", ListView)
        await switcher.clear()
        for chat in self.app.service.list_chats():
            item = ListItem(Static(chat.title, markup=False))
            item.chat_id = chat.id
            if chat.id == self.chat_id:
                item.add_class("chat-switcher-current")
            await switcher.append(item)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """The docked switcher's own selection route (B-2.0-47). A
        `ListView.Selected` message bubbles to the screen from any list it
        contains, so this only acts on one raised by `#chat-switcher` itself
        — guarding against a future second list on this screen catching the
        same handler. Selecting the chat already open is an explicit no-op:
        it must not push a duplicate screen, disturb the draft or focus, or
        add an `Esc` step, since a person is already looking at that chat.
        """
        if event.list_view.id != "chat-switcher":
            return
        chat_id = event.item.chat_id
        if chat_id == self.chat_id:
            return
        self.app.open_chat(chat_id)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Routes a transcript **Restore to composer** press — the only
        `Button`s this screen mounts carry a `turn_id` attribute
        (`_restore_button`); anything else is ignored rather than assumed.
        """
        turn_id = getattr(event.button, "turn_id", None)
        if turn_id is not None:
            self._restore_turn(turn_id)

    def _restore_turn(self, turn_id: TurnId) -> None:
        """**Restore to composer**'s handler (Concept.md's "An omitted
        message is visible and recoverable"). Local and manual: it never
        calls the responder and never mutates, reopens, or marks handled
        `turn_id`'s own turn — it only copies that turn's real stored user
        message into the composer. Re-reads the canonical snapshot rather
        than anything this rendering pass cached, so it identifies the exact
        stored message for `turn_id` even if the mounted transcript is
        stale. A non-blank composer is protected: restoring refuses and
        leaves both the draft and the stored omitted message untouched,
        since cfc cannot guess which text a person meant to keep.
        """
        composer = self.query_one(Composer)
        if composer.text.strip():
            self._notice = _RESTORE_BUSY_NOTICE
            self._render_status()
            return
        snapshot = self.app.service.snapshot(self.chat_id)
        user_message = next(
            (m for m in snapshot.messages if m.turn_id == turn_id and m.role is Role.USER),
            None,
        )
        if user_message is None:
            self._notice = _RESTORE_MISSING_NOTICE
            self._render_status()
            return
        composer.text = user_message.content
        composer.focus()
        self._notice = ""
        self._render_status()

    async def notify_run_changed(self) -> None:
        """Called by `CfcApp` — awaited from inside its worker's own
        `finally` — after that worker reaches a terminal state, but only
        when this screen is the one currently on top; a background
        completion while elsewhere is picked up by the canonical re-read in
        `on_screen_resume` instead (never lost, never pushed onto a screen
        that is not looking). Awaited rather than deferred with
        `call_later`: `CfcApp.shutdown` awaits every worker before closing
        the service, and only an in-worker await gives that guarantee —
        anything scheduled for "later" could still be pending, and then run
        against an already-closed store, after shutdown proceeds.
        """
        self._notice = ""
        await self.refresh_from_service()
        self.query_one(Composer).focus()

    # -- composing and sending -------------------------------------------

    def on_composer_submitted(self, event: Composer.Submitted) -> None:
        text = event.text
        if not text.strip():
            self._notice = _BLANK_DRAFT_NOTICE
            self._render_status()
            return
        if self.app.is_chat_busy(self.chat_id):
            self._notice = _CHAT_BUSY_NOTICE
            self._render_status()
            return
        try:
            self.app.service.preview_context(self.chat_id)
        except context_mod.SourceUnavailable as exc:
            self._notice = _context_unavailable_notice(exc)
            self._render_status()
            return
        self.app.start_turn(self.chat_id, text)
        self.query_one(Composer).text = ""
        self._notice = ""
        self._render_status()

    # -- the layered Esc route --------------------------------------------

    def action_handle_escape(self) -> None:
        if self.app.is_chat_busy(self.chat_id):
            self.app.cancel_turn(self.chat_id)
            return
        self.app.pop_screen()

    def action_show_chats(self) -> None:
        self.app.push_screen(ChatsModal(), self._handle_chats_result)

    def _handle_chats_result(self, chat_id: ChatId | None) -> None:
        if chat_id is not None and chat_id != self.chat_id:
            self.app.open_chat(chat_id)

    # -- Context: cfc-owned command palette only, never a dedicated key -----

    def action_show_context(self) -> None:
        self.app.push_screen(ContextModal(self.chat_id), self._handle_context_result)

    async def _handle_context_result(self, _result: None) -> None:
        await self.refresh_from_service()
        self.query_one(Composer).focus()

    # -- Model: chat state, cfc-owned command palette only -------------------

    def action_show_model(self) -> None:
        chat = self.app.service.get_chat(self.chat_id)
        self.app.push_screen(
            ModelModal(chat.context_selection.model, self.app.default_model, self.app._models),
            self._handle_model_result,
        )

    async def _handle_model_result(self, model_id: str | None) -> None:
        if model_id is not None:
            try:
                self.app.service.set_model(self.chat_id, model_id)
            except conversation_store.ActiveTurnExists:
                self._notice = (
                    "This chat has a request in progress; wait or cancel it "
                    "before changing its model."
                )
        await self.refresh_from_service()
        self.query_one(Composer).focus()


def _usage_text(usage) -> str:
    """Independent input/output/total counts — `not reported` for each
    missing value, explicit `0` shown unchanged (Concept.md: "Missing
    counts say `not reported`; explicit zero remains `0`").
    """
    def one(value: int | None) -> str:
        return "not reported" if value is None else str(value)
    if usage is None:
        return "usage — input: not reported, output: not reported, total: not reported"
    return (f"usage — input: {one(usage.input_tokens)}, "
            f"output: {one(usage.output_tokens)}, total: {one(usage.total_tokens)}")


def _limit_text(usage, model: str, models: "settings.ModelCatalogue") -> str | None:
    """The reported input count against this model's configured context
    limit, when both are known — descriptive only (Concept.md's "Model
    metadata becomes authority": never a truncation or safety claim).
    """
    if usage is None or usage.input_tokens is None:
        return None
    entry = models.entry_for(model)
    if entry is None or entry.context_limit is None:
        return None
    return f"reported input {usage.input_tokens} of configured limit {entry.context_limit}"


def _context_provenance_text(
    manifest: tuple[ContextManifestEntry, ...], service: ConversationService,
) -> str:
    """This turn's recorded context sources, in order — category, name, and
    a `*` marker (with a trailing footnote) on any entry whose live vault
    fingerprint no longer matches what this turn actually used (Concept.md:
    "it says that the live source differs... instead of presenting the new
    words as what an old turn received").
    """
    if not manifest:
        return "context: none"
    parts = []
    changed = False
    for entry in manifest:
        label = f"{entry.category.value}:{entry.name}"
        if service.context_entry_fingerprint_changed(entry):
            label += "*"
            changed = True
        parts.append(label)
    text = "context: " + ", ".join(parts)
    if changed:
        text += " (* the live source has changed since this turn)"
    return text


def _transcript_widgets(
    snapshot: ConversationSnapshot, opening: OpeningMessage | None,
    service: ConversationService, models: "settings.ModelCatalogue",
) -> list[Widget]:
    """One `Static` per stored message plus one status line for a turn that
    is active, failed, or cancelled — literal content only, never
    Rich/Textual markup, so a message containing `[bold]` or an ANSI-looking
    string stays inert content (Concept.md's "markup execution" failure
    mode; every `Static` here is built with `markup=False`).

    A frozen `opening`, when present, renders first — history, not a
    synthetic turn (Concept.md's "First Message is an opening"). A
    completed turn additionally renders its actual model, independent
    usage counts, an optional configured-limit comparison, and its recorded
    context provenance. A failed or cancelled turn gets the omission notice
    and its own turn-specific **Restore to composer** button (Concept.md's
    "An omitted message is visible and recoverable"; B-2.0-55/D-2.0-53) —
    never a generic "retry latest", since several omissions in one chat
    must stay independently restorable.
    """
    by_turn: dict[str, list[StoredMessage]] = {t.id.value: [] for t in snapshot.turns}
    for message in snapshot.messages:
        by_turn[message.turn_id.value].append(message)

    widgets: list[Widget] = []
    if opening is not None:
        widgets.append(Static(f"cfc: {opening.content}", markup=False, classes="opening-message"))
    for turn in snapshot.turns:
        for message in by_turn[turn.id.value]:
            speaker = "You" if message.role is Role.USER else "cfc"
            widgets.append(Static(f"{speaker}: {message.content}", markup=False))
        if turn.outcome is None:
            widgets.append(Static("… cfc is working on this turn …", markup=False))
        elif isinstance(turn.outcome, CompletedOutcome):
            widgets.append(Static(f"model: {turn.model}", markup=False, classes="turn-evidence"))
            widgets.append(Static(_usage_text(turn.outcome.usage), markup=False,
                                   classes="turn-evidence"))
            limit_text = _limit_text(turn.outcome.usage, turn.model, models)
            if limit_text is not None:
                widgets.append(Static(limit_text, markup=False, classes="turn-evidence"))
            widgets.append(Static(_context_provenance_text(turn.context_manifest, service),
                                   markup=False, classes="turn-evidence"))
        elif isinstance(turn.outcome, FailedOutcome):
            widgets.append(Static(f"[turn failed: {turn.outcome.evidence.reason}]", markup=False))
            widgets.append(Static(_OMISSION_NOTICE, markup=False))
            widgets.append(_restore_button(turn.id))
        elif isinstance(turn.outcome, CancelledOutcome):
            widgets.append(Static("[turn cancelled]", markup=False))
            widgets.append(Static(_OMISSION_NOTICE, markup=False))
            widgets.append(_restore_button(turn.id))
    return widgets


def _restore_button(turn_id: TurnId) -> Button:
    button = Button(_RESTORE_LABEL, id=f"restore-{turn_id.value}", classes="restore-button")
    button.turn_id = turn_id
    return button


def _context_bar_text(chat: Chat) -> str:
    """The Chat screen's always-visible model id and compact context
    summary (Concept.md: "The Chat screen always shows the selected model
    by its exact provider ID and a compact context summary" — the exact
    provider ID, literal, never a friendly label standing in for it).
    """
    selection = chat.context_selection
    parts = [f"model: {selection.model}"]
    parts.append(f"prefs: {selection.user_preferences or 'none'}")
    parts.append(f"persona: {selection.persona or 'none'}")
    trait_count = len(selection.traits)
    parts.append(f"traits: {trait_count if trait_count else 'none'}")
    parts.append(f"opening: {'yes' if chat.opening is not None else 'no'}")
    return " · ".join(parts)


def _status_text(run: _TurnRun | None) -> str:
    if run is None:
        return ""
    if run.status == "running":
        return "Sending… (Esc cancels)"
    if run.status == "completed":
        return "Completed."
    if run.status == "cancelled":
        return "Cancelled."
    if run.status == "failed":
        reason = run.message
        if reason is None and run.turn is not None and isinstance(run.turn.outcome, FailedOutcome):
            reason = run.turn.outcome.evidence.reason
        return f"Failed: {reason or 'unknown reason'}"
    return ""  # pragma: no cover — exhaustive over _TurnRun.status's own values


# --- theme, screenshot export, and the cfc-owned Ctrl+P command set --------

#: `TUI_THEME`'s two accepted values, mapped to the built-in Textual themes
#: cfc actually applies (`settings.ACCEPTED_TUI_THEMES` owns the accepted
#: value spelling; this module owns what each one means visually).
_TEXTUAL_THEME_NAMES = {"dark": "textual-dark", "light": "textual-light"}

#: The fixed, cfc-owned screenshot destination (Concept.md's "Screenshot
#: destination and recovery" — explicitly not user-configurable). A test
#: constructs `CfcApp`/`StartupFailureApp` with an explicit `screenshots_dir`
#: instead of touching this real path.
_DEFAULT_SCREENSHOTS_DIR = Path.home() / ".cfc" / "2.0" / "screenshots"


class ScreenshotError(Exception):
    """A bounded, cfc-authored screenshot failure reason. `str(exc)` never
    carries a raw exception string, provider text, or a configuration value
    (Concept.md's "Screenshot false success" failure mode) — it is always
    safe to show directly.
    """


def _screenshot_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")


def _quietly_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:  # noqa: BLE001 — best-effort cleanup after an already-reported failure
        pass


def _write_screenshot(svg: str, directory: Path, *, timestamp: str | None = None) -> Path:
    """Validates/creates `directory`, writes `svg` to a temporary file
    inside it, and renames that file to its final path only after the write
    succeeds — a failed capture never leaves a plausible partial file under
    a final-looking name (Concept.md). The final name is collision-resistant:
    an already-occupied timestamped name gets a numbered suffix rather than
    overwriting whatever is already there. Raises `ScreenshotError` naming
    `directory` on any failure; never lets a raw `OSError` escape.

    `timestamp`, when given, replaces the real clock — the seam a test uses
    to make a filename collision deterministic rather than a matter of
    hitting the same microsecond twice.
    """
    stamp = timestamp if timestamp is not None else _screenshot_timestamp()

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise ScreenshotError(
            f"cfc could not create the screenshot folder {directory}. "
            "Create it or correct its permissions, then try again."
        )

    final_path = directory / f"cfc-{stamp}.svg"
    suffix = 1
    while final_path.exists():
        suffix += 1
        final_path = directory / f"cfc-{stamp}-{suffix}.svg"
    temp_path = directory / f".{final_path.name}.tmp"

    try:
        temp_path.write_text(svg, encoding="utf-8")
    except OSError:
        _quietly_unlink(temp_path)
        raise ScreenshotError(
            f"cfc could not write a screenshot into {directory}. "
            "Correct its permissions, then try again."
        )

    try:
        temp_path.replace(final_path)
    except OSError:
        _quietly_unlink(temp_path)
        raise ScreenshotError(
            f"cfc could not finish saving the screenshot to {final_path}. "
            "Correct the folder's permissions, then try again."
        )

    return final_path


class CfcCommandsProvider(Provider):
    """cfc's complete `Ctrl+P` command set: **Keyboard help**, **Save
    screenshot**, **Quit cfc** everywhere, plus **Context** and **Model**
    only when the active screen is an ordinary `ChatScreen` (Work Order Step
    4: "Context appears only on an ordinary Chat's cfc-owned command
    palette"). Installed in place of (never alongside) Textual's inherited
    system-commands provider, so Theme, Keys, Maximize/Minimize, generic
    Screenshot, and immediate Quit are absent by construction rather than
    filtered out (Concept.md's "cfc owns Ctrl+P"). Shared by `CfcApp` and
    `StartupFailureApp` — only a later private-chat screen is deliberately
    excluded from the chat-only pair.
    """

    def _commands(self) -> tuple[tuple[str, Callable, str], ...]:
        app = self.app
        commands: list[tuple[str, Callable, str]] = [
            ("Keyboard help", app.action_show_keyboard_help,
             "Stage 4's keys and the Shift+Enter terminal requirement"),
            ("Save screenshot", app.action_save_screenshot,
             "Export an SVG of the current screen"),
        ]
        if isinstance(self.screen, ChatScreen):
            commands.append(("Context", self.screen.action_show_context,
                              "Select and inspect this chat's context"))
            commands.append(("Model", self.screen.action_show_model,
                              "Choose this chat's model"))
        commands.append(("Quit cfc", app.action_quit, "Close cfc"))
        return tuple(commands)

    async def discover(self) -> Hits:
        for name, callback, help_text in self._commands():
            yield DiscoveryHit(name, callback, help=help_text)

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for name, callback, help_text in self._commands():
            score = matcher.match(name)
            if score > 0:
                yield Hit(score, matcher.highlight(name), callback, help=help_text)


class _CommandSurfaceMixin:
    """`action_show_keyboard_help`/`action_save_screenshot` shared by every
    `App` subclass that installs `CfcCommandsProvider`. Each concrete class
    still supplies its own `_screenshots_dir` (set in `__init__`) and its
    own `action_quit` — this mixin only owns the two commands that are
    identical everywhere they appear.
    """

    def action_show_keyboard_help(self) -> None:
        self.push_screen(KeyboardHelpModal())

    async def action_save_screenshot(self) -> None:
        try:
            svg = self.export_screenshot()
            final_path = _write_screenshot(svg, self._screenshots_dir)
        except ScreenshotError as exc:
            self.notify(str(exc), title="Screenshot failed", severity="error", markup=False, timeout=10)
            return
        self.notify(f"Screenshot saved to {final_path}", title="Screenshot saved", markup=False)


# --- the startup-failure app: never a raw traceback, never a mock Hub ------

class StartupFailureApp(_CommandSurfaceMixin, App):
    """Rendered instead of `CfcApp` when configuration or store startup
    refuses real chat (Concept.md's "Startup refusal" section). `message`
    is the safe, already-bounded text the failing call itself produced
    (`ConfigLoadError`/`SettingsError`/`ConversationStoreError` never embed
    a credential — see their own modules); `next_step`, when given, is
    separate recovery guidance, mirroring how `doctor.render` shows a row's
    detail and next step as two lines rather than one blended sentence.
    """

    CSS_PATH = "tui.tcss"
    BINDINGS = [Binding("q", "quit", "Quit", show=True, priority=True)]
    COMMANDS = {CfcCommandsProvider}

    def __init__(
        self, message: str, next_step: str | None = None, *,
        screenshots_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self._message = message
        self._next_step = next_step
        self._screenshots_dir = screenshots_dir or _DEFAULT_SCREENSHOTS_DIR

    def compose(self) -> ComposeResult:
        with Vertical(id="startup-failure"):
            yield Static("cfc could not start real chat.", markup=False)
            yield Static(self._message, id="startup-failure-message", markup=False)
            if self._next_step:
                yield Static(self._next_step, id="startup-failure-next-step", markup=False)
        yield Footer()


# --- the real app ------------------------------------------------------

class CfcApp(_CommandSurfaceMixin, App):
    """The working ordinary-chat client. Constructed with an already-open
    `ConversationService` and a `Responder` this app does not construct
    itself (`build_app` does that) — the same constructor tests use with a
    temporary store and a deterministic responder (Work Order Step 3).
    """

    CSS_PATH = "tui.tcss"
    BINDINGS = [Binding("ctrl+q", "quit", "Quit", show=True, priority=True)]
    COMMANDS = {CfcCommandsProvider}

    def __init__(
        self, service: ConversationService, responder: Responder, model: str, *,
        theme: settings.ThemeSettings | None = None,
        screenshots_dir: Path | None = None,
        models: settings.ModelCatalogue | None = None,
    ) -> None:
        super().__init__()
        self.service = service
        self._responder = responder
        #: `model`'s only remaining job is seeding a *new* chat's initial
        #: selection (`HubScreen._handle_new_chat_result`) — an existing
        #: chat's model lives in its own stored `context_selection.model`
        #: and is never overridden by this default (Concept.md: "Model
        #: choice is chat state").
        self._model = model
        self._models = models if models is not None else settings.ModelCatalogue()
        self._theme_settings = theme or settings.ThemeSettings(settings.DEFAULT_TUI_THEME)
        self._screenshots_dir = screenshots_dir or _DEFAULT_SCREENSHOTS_DIR
        self._chat_workers: dict[str, Worker] = {}
        self._turn_runs: dict[str, _TurnRun] = {}
        self._drafts: dict[str, str] = {}
        self._shut_down = False

    @property
    def default_model(self) -> str:
        return self._model

    def on_mount(self) -> None:
        self.theme = _TEXTUAL_THEME_NAMES[self._theme_settings.name]
        if self._theme_settings.invalid_value_notice:
            self.notify(
                self._theme_settings.invalid_value_notice,
                title="Theme", severity="warning", markup=False, timeout=10,
            )
        self.push_screen(HubScreen())

    # -- navigation --------------------------------------------------------

    def open_chat(self, chat_id: ChatId) -> None:
        """Opens `chat_id`'s `ChatScreen`. Pushed from the Hub, preserving
        the existing one-`Esc`-back route; replaced in place when a
        `ChatScreen` is already active, so switching between stored chats
        does not grow the screen stack (B-2.0-55, Concept.md's "one chat
        screen at a time"). `switch_screen` suspends the outgoing screen
        before removing it — the same `on_screen_suspend` hook `pop_screen`
        already relies on for `save_draft` — so a switched-away draft is
        never lost. Selecting the chat already displayed is a no-op;
        callers already guard this (`ChatScreen.on_list_view_selected`,
        `ChatsModal`'s dismiss handler) and this repeats the guard so no
        future caller can skip it.
        """
        if isinstance(self.screen, ChatScreen) and self.screen.chat_id == chat_id:
            return
        chat = self.service.get_chat(chat_id)
        new_screen = ChatScreen(chat_id, chat.title)
        if isinstance(self.screen, ChatScreen):
            self.switch_screen(new_screen)
        else:
            self.push_screen(new_screen)

    # -- the draft a chat's composer held when last left, read and written
    # -- only by ChatScreen's own mount/suspend hooks ------------------------

    def get_draft(self, chat_id: ChatId) -> str:
        return self._drafts.get(chat_id.value, "")

    def save_draft(self, chat_id: ChatId, text: str) -> None:
        self._drafts[chat_id.value] = text

    # -- per-chat turn state, read by ChatScreen ----------------------------

    def turn_status(self, chat_id: ChatId) -> _TurnRun | None:
        return self._turn_runs.get(chat_id.value)

    def is_chat_busy(self, chat_id: ChatId) -> bool:
        worker = self._chat_workers.get(chat_id.value)
        return worker is not None and not worker.is_finished

    def start_turn(self, chat_id: ChatId, text: str) -> bool:
        """Starts one app-owned worker for `chat_id`. Returns `False`
        without starting anything if that chat already has one running —
        `ChatScreen` checks this first for its own message, but this call
        re-checks itself so no caller can race past it (D-2.0-36's UI
        mirror; the real refusal is `ConversationService`/`ConversationStore`'s
        own atomic guard, reached inside `_run_turn` below).
        """
        if self.is_chat_busy(chat_id):
            return False
        key = chat_id.value
        self._turn_runs[key] = _TurnRun(status="running")
        worker = self.run_worker(
            self._run_turn(chat_id, text),
            group=f"chat-{key}", exclusive=True, exit_on_error=False,
        )
        self._chat_workers[key] = worker
        return True

    def cancel_turn(self, chat_id: ChatId) -> None:
        worker = self._chat_workers.get(chat_id.value)
        if worker is not None and not worker.is_finished:
            worker.cancel()

    async def _run_turn(self, chat_id: ChatId, text: str) -> None:
        """The worker body. Every way out updates `_turn_runs` before
        returning or re-raising, and a `CancelledError` is deliberately not
        swallowed here — `Worker._run` already treats that as the ordinary
        cancelled state, not an app-crashing error; only an unexpected
        `Exception` needs interception so it never reaches Textual's default
        worker-error handling as a raw traceback (Concept.md's "Frozen
        prompt"/crash failure modes; B-2.0-33's bounded-reason discipline
        extended to this layer).
        """
        key = chat_id.value
        try:
            try:
                turn = await self.service.send_turn(chat_id, text, self._responder)
            except asyncio.CancelledError:
                self._turn_runs[key] = _TurnRun(status="cancelled")
                raise
            except Exception:  # noqa: BLE001 — see docstring: never a raw traceback
                self._turn_runs[key] = _TurnRun(status="failed", message=_WORKER_FAILURE_MESSAGE)
            else:
                self._turn_runs[key] = _TurnRun(status=_status_of(turn), turn=turn)
        finally:
            await self._notify_if_active(chat_id)

    async def _notify_if_active(self, chat_id: ChatId) -> None:
        screen = self.screen
        if isinstance(screen, ChatScreen) and screen.chat_id == chat_id:
            await screen.notify_run_changed()

    # -- shutdown: cancel and await every worker before closing anything ---

    async def action_quit(self) -> None:
        await self.shutdown()
        self.exit()

    async def shutdown(self) -> None:
        """Idempotent: safe to call from `action_quit` and again, as a
        safety net, from the outer `run()` wrapper after `App.run()`
        returns by any route. Cancels and awaits every app-owned worker,
        then closes the responder, then the service — quitting cannot close
        SQLite underneath a finalisation already in progress (Concept.md).
        """
        if self._shut_down:
            return
        self._shut_down = True
        workers = list(self._chat_workers.values())
        for worker in workers:
            worker.cancel()
        for worker in workers:
            try:
                await worker.wait()
            except Exception:  # noqa: BLE001 — WorkerCancelled/WorkerFailed; already recorded
                pass
        aclose = getattr(self._responder, "aclose", None)
        if aclose is not None:
            await aclose()
        self.service.close()


def _status_of(turn: Turn) -> str:
    if isinstance(turn.outcome, CompletedOutcome):
        return "completed"
    if isinstance(turn.outcome, FailedOutcome):
        return "failed"
    return "cancelled"


# --- composition seam: config -> settings -> store -> responder -> App -----

def build_app(
    config_path: Path | None = None, *,
    responder_factory: Callable[[settings.ProviderSettings], Responder] | None = None,
) -> App:
    """Resolve configuration, open the 2.0 store, and build the responder —
    returning a `CfcApp` ready to `run()`, or a `StartupFailureApp` carrying
    the exact safe reason and next step when a known refusal prevents real
    chat. Never raises for a refusal this loop names; an unrecognised
    exception is still allowed to propagate rather than be hidden, since
    hiding an unknown failure is worse than a traceback for one this module
    cannot yet explain.

    `config_path` and `responder_factory` exist for tests: a temporary
    config path avoids ever touching `config.py`, the default database, or
    the vault, and an injected deterministic responder avoids the network —
    both use this exact function, not a parallel test-only construction path.
    """
    try:
        snapshot = config_loader.load_snapshot(config_path)
    except config_loader.ConfigLoadError as exc:
        return StartupFailureApp(str(exc), diagnostics._config_load_next_step(exc))

    try:
        built = settings.build_settings(snapshot)
    except settings.SettingsError as exc:
        return StartupFailureApp(str(exc), diagnostics._settings_error_next_step(exc))

    try:
        service = open_service(built.database_path, built.vault)
    except ConversationStoreError as exc:
        return StartupFailureApp(str(exc))

    if responder_factory is not None:
        responder = responder_factory(built.provider)
    else:
        responder = provider_adapter.OpenAICompatibleAdapter(built.provider)

    return CfcApp(service, responder, built.provider.model, theme=built.theme, models=built.models)


def run(config_path: Path | None = None) -> int:
    """`python -m cfc`'s no-argument entry point. Returns a process exit
    code: `0` after a real chat session ends normally, `1` if startup itself
    refused and the person only ever saw `StartupFailureApp`.
    """
    app = build_app(config_path)
    try:
        app.run()
    finally:
        if isinstance(app, CfcApp):
            asyncio.run(app.shutdown())
    return 1 if isinstance(app, StartupFailureApp) else 0
