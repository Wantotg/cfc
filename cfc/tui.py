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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, Static
from textual.widgets import TextArea
from textual.worker import Worker

from cfc import config_loader, diagnostics, provider_adapter, settings
from cfc.conversation_service import ConversationService, open_service
from cfc.conversation_store import ConversationStoreError
from cfc.conversation_types import (
    CancelledOutcome,
    ChatId,
    CompletedOutcome,
    ConversationSnapshot,
    FailedOutcome,
    Message as StoredMessage,
    Responder,
    Role,
    Turn,
)

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
        chat = self.app.service.create_chat(title)
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

    def compose(self) -> ComposeResult:
        yield Static(self.chat_title, id="chat-title-bar", markup=False)
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
        """Re-read the store's snapshot and this chat's run state, and
        rebuild the transcript and status line from them — never an
        optimistic patch. Called on mount, on resume, and whenever the
        app-owned worker for this chat changes state.
        """
        snapshot = self.app.service.snapshot(self.chat_id)
        await self._render_transcript(snapshot)
        self._render_status()
        await self._render_switcher()

    async def _render_transcript(self, snapshot: ConversationSnapshot) -> None:
        transcript = self.query_one("#chat-transcript", VerticalScroll)
        was_at_bottom = transcript.is_vertical_scroll_end
        await transcript.remove_children()
        await transcript.mount_all(Static(text, markup=False) for text in _transcript_lines(snapshot))
        if was_at_bottom:
            transcript.scroll_end(animate=False)

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


def _transcript_lines(snapshot: ConversationSnapshot) -> list[str]:
    """One line per stored message plus one status line for a turn that is
    active, failed, or cancelled — literal content only, never Rich/Textual
    markup, so a message containing `[bold]` or an ANSI-looking string stays
    inert content (Concept.md's "markup execution" failure mode; every
    caller renders these with `Static(..., markup=False)`).
    """
    by_turn: dict[str, list[StoredMessage]] = {t.id.value: [] for t in snapshot.turns}
    for message in snapshot.messages:
        by_turn[message.turn_id.value].append(message)

    lines: list[str] = []
    for turn in snapshot.turns:
        for message in by_turn[turn.id.value]:
            speaker = "You" if message.role is Role.USER else "cfc"
            lines.append(f"{speaker}: {message.content}")
        if turn.outcome is None:
            lines.append("… cfc is working on this turn …")
        elif isinstance(turn.outcome, FailedOutcome):
            lines.append(f"[turn failed: {turn.outcome.evidence.reason}]")
        elif isinstance(turn.outcome, CancelledOutcome):
            lines.append("[turn cancelled]")
    return lines


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


# --- the startup-failure app: never a raw traceback, never a mock Hub ------

class StartupFailureApp(App):
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

    def __init__(self, message: str, next_step: str | None = None) -> None:
        super().__init__()
        self._message = message
        self._next_step = next_step

    def compose(self) -> ComposeResult:
        with Vertical(id="startup-failure"):
            yield Static("cfc could not start real chat.", markup=False)
            yield Static(self._message, id="startup-failure-message", markup=False)
            if self._next_step:
                yield Static(self._next_step, id="startup-failure-next-step", markup=False)
        yield Footer()


# --- the real app ------------------------------------------------------

class CfcApp(App):
    """The working ordinary-chat client. Constructed with an already-open
    `ConversationService` and a `Responder` this app does not construct
    itself (`build_app` does that) — the same constructor tests use with a
    temporary store and a deterministic responder (Work Order Step 3).
    """

    CSS_PATH = "tui.tcss"
    BINDINGS = [Binding("ctrl+q", "quit", "Quit", show=True, priority=True)]

    def __init__(self, service: ConversationService, responder: Responder, model: str) -> None:
        super().__init__()
        self.service = service
        self._responder = responder
        self._model = model
        self._chat_workers: dict[str, Worker] = {}
        self._turn_runs: dict[str, _TurnRun] = {}
        self._drafts: dict[str, str] = {}
        self._shut_down = False

    def on_mount(self) -> None:
        self.push_screen(HubScreen())

    # -- navigation --------------------------------------------------------

    def open_chat(self, chat_id: ChatId) -> None:
        chat = self.service.get_chat(chat_id)
        self.push_screen(ChatScreen(chat_id, chat.title))

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
                turn = await self.service.send_turn(chat_id, self._model, text, self._responder)
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
        service = open_service(built.database_path)
    except ConversationStoreError as exc:
        return StartupFailureApp(str(exc))

    if responder_factory is not None:
        responder = responder_factory(built.provider)
    else:
        responder = provider_adapter.OpenAICompatibleAdapter(built.provider)

    return CfcApp(service, responder, built.provider.model)


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
