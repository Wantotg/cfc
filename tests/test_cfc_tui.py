"""test_cfc_tui.py — cfc/tui.py: the Textual Hub/Chat client over the real
Stage 3 conversation service, store, and injected deterministic responders.

Every test drives the real keyboard/mouse/resize input stack through
Textual's `Pilot` (`App.run_test()`), never calling an action method
directly — the Work Order's own proof requirement, because a call like
`screen.action_handle_escape()` proves the method exists, not that the key
actually reaches it through focus and the screen stack. Every store lives
under `tmp_path`; `build_app` is always given an explicit `config_path` or a
`responder_factory`, so nothing here reads `config.py`, opens the default
database, touches the vault, or contacts a network.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cfc import conversation_store, settings, tui
from cfc.conversation_service import open_service
from cfc.conversation_types import (
    Cancellation,
    Completion,
    Failure,
    FailureEvidence,
    FailureKind,
    Role,
    Usage,
)


# --- deterministic responders (the async twins of the service test's own) --

class FixedResponder:
    def __init__(self, result):
        self._result = result
        self.calls = []

    async def respond(self, plan):
        self.calls.append(plan)
        return self._result


class SlowResponder:
    """Never returns on its own; `started` fires once `respond` is under
    way, so a test can drive a cancellation deterministically."""

    def __init__(self):
        self.started = asyncio.Event()
        self.released = asyncio.Event()
        self.result = Completion(content="released")

    async def respond(self, plan):
        self.started.set()
        await self.released.wait()
        return self.result


class RaisingResponder:
    def __init__(self, exc: Exception):
        self._exc = exc

    async def respond(self, plan):
        raise self._exc


class ManualResponder:
    """Each `respond()` call waits on its own event, released independently
    by call order — lets a test drive two chats' turns concurrently and
    complete them in either order (`test_two_different_chats_run_independent
    _workers_at_once`)."""

    def __init__(self):
        self.calls = []
        self._events: dict[int, asyncio.Event] = {}
        self._results: dict[int, object] = {}

    async def respond(self, plan):
        index = len(self.calls)
        self.calls.append(plan)
        event = asyncio.Event()
        self._events[index] = event
        await event.wait()
        return self._results[index]

    def release(self, index: int, result) -> None:
        self._results[index] = result
        self._events[index].set()


class _FailOnceConn:
    """Wraps a real `sqlite3.Connection` and raises once, on the first
    `execute` call whose SQL contains `trigger` — the same injection seam
    `test_cfc_conversation_service.py` uses, reused here to reach
    `conversation_service.TurnEndingFailed` from inside a running worker.
    """

    def __init__(self, real, trigger: str):
        self._real = real
        self._trigger = trigger
        self._fired = False

    def execute(self, sql, *args, **kwargs):
        if not self._fired and self._trigger in sql:
            self._fired = True
            import sqlite3
            raise sqlite3.OperationalError(f"simulated failure: {self._trigger}")
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


# --- config fixtures ---------------------------------------------------

VALID_BODY = (
    "API_BASE = 'https://provider.invalid/v1'\n"
    "API_KEY = 'fixture-key'\n"
    "MODEL = 'fixture-model'\n"
)


def write_config(tmp_path: Path, body: str, db_subdir: str = "store") -> Path:
    path = tmp_path / "config.py"
    db_path = tmp_path / db_subdir / "chat.db"
    path.write_text(body + f"DATABASE_PATH = {str(db_path)!r}\n", encoding="utf-8")
    return path


def _no_network_responder_factory(provider_settings):
    """`build_app`'s injection seam, used everywhere in this file instead of
    the real `OpenAICompatibleAdapter` — proves the same construction path
    without ever building an `httpx` client aimed at a real endpoint."""
    return FixedResponder(Completion(content="unused"))


def empty_vault() -> settings.VaultSettings:
    unavailable = settings.VaultCategorySettings(unavailable_reason="not configured")
    return settings.VaultSettings(root=None, user_preferences=unavailable, personas=unavailable,
                                   traits=unavailable, first_messages=unavailable)


def real_vault(tmp_path: Path, *, prefs=None, personas=None, traits=None,
                first_messages=None) -> settings.VaultSettings:
    def cat(path):
        if path is None:
            return settings.VaultCategorySettings(unavailable_reason="not configured")
        return settings.VaultCategorySettings(path=path)
    return settings.VaultSettings(root=tmp_path, user_preferences=cat(prefs), personas=cat(personas),
                                   traits=cat(traits), first_messages=cat(first_messages))


def write_source(directory: Path, name: str, body: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(body, encoding="utf-8")


def open_test_service(tmp_path: Path, vault: settings.VaultSettings | None = None):
    return open_service(tmp_path / "direct" / "chat.db", vault or empty_vault())


def make_app(
    tmp_path: Path, responder=None, model: str = "fixture-model", *,
    theme: settings.ThemeSettings | None = None,
    screenshots_dir: Path | None = None,
    vault: settings.VaultSettings | None = None,
    models: settings.ModelCatalogue | None = None,
) -> tui.CfcApp:
    service = open_test_service(tmp_path, vault)
    if responder is None:
        responder = FixedResponder(Completion(content="the answer"))
    return tui.CfcApp(
        service, responder, model,
        theme=theme, screenshots_dir=screenshots_dir or (tmp_path / "screenshots"),
        models=models,
    )


async def run_command(pilot, query: str) -> None:
    """Drives cfc's Ctrl+P palette through its real keyboard route: open it,
    type an exact command name so only that command matches, then Enter to
    select the highlighted (top) hit — the same route a person uses, never a
    direct call to the command's own action method (Work Order Step 4).
    """
    await pilot.press("ctrl+p")
    await pilot.pause()
    await pilot.press(*query)
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()


# === build_app: the composition seam ========================================

def test_build_app_returns_a_startup_failure_app_for_a_missing_config(tmp_path):
    app = tui.build_app(tmp_path / "does-not-exist.py")
    assert isinstance(app, tui.StartupFailureApp)
    assert "no configuration file" in app._message


def test_build_app_returns_a_startup_failure_app_for_an_invalid_setting(tmp_path):
    path = tmp_path / "config.py"
    path.write_text("API_BASE = 'not-a-url'\n", encoding="utf-8")
    app = tui.build_app(path)
    assert isinstance(app, tui.StartupFailureApp)
    assert "API_BASE" in app._message
    assert app._next_step is not None


def test_build_app_returns_a_startup_failure_app_for_an_incompatible_database(tmp_path):
    db_path = tmp_path / "store" / "chat.db"
    db_path.parent.mkdir(parents=True)
    db_path.write_bytes(b"not a sqlite database, just some bytes" * 4)
    path = write_config(tmp_path, VALID_BODY)
    # rewrite pointing at the pre-existing corrupt file rather than the
    # fresh subdir write_config already wrote a path for
    path.write_text(VALID_BODY + f"DATABASE_PATH = {str(db_path)!r}\n", encoding="utf-8")

    app = tui.build_app(path)

    assert isinstance(app, tui.StartupFailureApp)
    assert "not a valid SQLite file" in app._message


def test_build_app_never_falls_through_to_a_mock_hub_on_refusal(tmp_path):
    """Named failure mode in Concept.md: a startup refusal must render its
    own bounded failure state, never a Hub with fixture or absent data."""
    app = tui.build_app(tmp_path / "missing.py")
    assert not isinstance(app, tui.CfcApp)


def test_build_app_with_valid_config_and_injected_responder_builds_a_working_app(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    app = tui.build_app(path, responder_factory=_no_network_responder_factory)
    try:
        assert isinstance(app, tui.CfcApp)
        assert app._model == "fixture-model"
    finally:
        app.service.close()


async def test_a_real_default_responder_is_constructed_without_a_factory(tmp_path):
    """The default path builds the real `OpenAICompatibleAdapter` — proven
    by type alone; no network call is made in this test."""
    from cfc.provider_adapter import OpenAICompatibleAdapter

    path = write_config(tmp_path, VALID_BODY)
    app = tui.build_app(path)
    try:
        assert isinstance(app._responder, OpenAICompatibleAdapter)
    finally:
        await app._responder.aclose()
        app.service.close()


# === startup failure rendering: bounded, never a raw traceback =============

async def test_startup_failure_renders_the_safe_message_and_next_step(tmp_path):
    path = tmp_path / "config.py"
    path.write_text("", encoding="utf-8")  # loads, but every required field missing
    app = tui.build_app(path)
    assert isinstance(app, tui.StartupFailureApp)

    async with app.run_test() as pilot:
        message = app.query_one("#startup-failure-message", tui.Static)
        assert "API_BASE" in message.content
        next_step = app.query_one("#startup-failure-next-step", tui.Static)
        assert "config.py" in next_step.content
        # quit is bound and visible, never a crash or a hang
        await pilot.press("q")
    assert app.return_code == 0


# === Hub: empty state, creation, selection ==================================

async def test_hub_shows_an_honest_empty_state_with_no_stored_chats(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            hub = app.screen
            assert isinstance(hub, tui.HubScreen)
            empty = hub.query_one("#hub-empty", tui.Static)
            assert empty.display is True
            assert hub.query_one("#hub-chat-list", tui.ListView).display is False
    finally:
        await app.shutdown()


async def test_new_chat_modal_creates_and_opens_a_chat_on_a_non_blank_title(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            await pilot.press("n")
            assert isinstance(app.screen, tui.NewChatModal)
            title_field = app.screen.query_one("#new-chat-title", tui.Input)
            title_field.value = "first chat"
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, tui.ChatScreen)
            assert app.screen.chat_title == "first chat"
            assert [c.title for c in app.service.list_chats()] == ["first chat"]
    finally:
        await app.shutdown()


async def test_esc_closes_the_new_chat_modal_without_creating_anything(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            await pilot.press("n")
            assert isinstance(app.screen, tui.NewChatModal)
            await pilot.press("escape")
            await pilot.pause()

            assert isinstance(app.screen, tui.HubScreen)
            assert app.service.list_chats() == ()
    finally:
        await app.shutdown()


async def test_a_blank_title_refuses_visibly_and_creates_nothing(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            await pilot.press("n")
            await pilot.press("enter")  # blank field
            await pilot.pause()

            assert isinstance(app.screen, tui.NewChatModal)
            error = app.screen.query_one("#new-chat-error", tui.Static)
            assert "blank" in str(error.content)
            assert app.service.list_chats() == ()
    finally:
        await app.shutdown()


async def test_duplicate_titles_remain_distinct_stored_chats(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            for _ in range(2):
                await pilot.press("n")
                app.screen.query_one("#new-chat-title", tui.Input).value = "same title"
                await pilot.press("enter")
                await pilot.pause()
                await app.pop_screen()  # back to Hub for the next creation
                await pilot.pause()

            chats = app.service.list_chats()
            assert [c.title for c in chats] == ["same title", "same title"]
            assert chats[0].id != chats[1].id
    finally:
        await app.shutdown()


async def test_selecting_a_hub_row_opens_the_same_stored_chat(tmp_path):
    app = make_app(tmp_path)
    try:
        chat = app.service.create_chat("existing", "fixture-model")
        async with app.run_test() as pilot:
            await pilot.pause()
            list_view = app.screen.query_one("#hub-chat-list", tui.ListView)
            list_view.index = 0
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, tui.ChatScreen)
            assert app.screen.chat_id == chat.id
    finally:
        await app.shutdown()


async def test_mouse_selection_of_a_hub_row_does_the_same_as_keyboard(tmp_path):
    app = make_app(tmp_path)
    try:
        chat = app.service.create_chat("existing", "fixture-model")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("ListItem")
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.ChatScreen)
            assert app.screen.chat_id == chat.id
    finally:
        await app.shutdown()


async def test_mouse_click_on_new_chat_button_opens_the_same_modal_as_the_key(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            await pilot.click("#hub-new-chat-button")
            assert isinstance(app.screen, tui.NewChatModal)
    finally:
        await app.shutdown()


async def test_mouse_click_on_modal_cancel_button_dismisses_without_creating(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            await pilot.press("n")
            await pilot.click("#new-chat-cancel")
            await pilot.pause()
            assert isinstance(app.screen, tui.HubScreen)
            assert app.service.list_chats() == ()
    finally:
        await app.shutdown()


# === Chat: helpers ==========================================================

def transcript_lines(screen) -> list[str]:
    return [str(s.content) for s in screen.query("#chat-transcript Static")]


async def type_text(pilot, text: str) -> None:
    await pilot.press(*text)


async def open_new_chat(app, pilot, title: str = "c") -> tui.ChatScreen:
    await pilot.press("n")
    await type_text(pilot, title)
    await pilot.press("enter")
    await pilot.pause()
    assert isinstance(app.screen, tui.ChatScreen)
    return app.screen


# === Composer: Enter sends, Shift+Enter inserts a literal newline ==========

async def test_enter_sends_a_non_blank_draft_and_clears_only_the_composer(tmp_path):
    responder = FixedResponder(Completion(content="the answer"))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "hello there")
            await pilot.press("enter")
            await pilot.pause()

            assert responder.calls  # the responder was reached exactly once
            lines = transcript_lines(screen)
            assert "You: hello there" in lines
            assert "cfc: the answer" in lines
            assert screen.query_one(tui.Composer).text == ""
    finally:
        await app.shutdown()


async def test_shift_enter_inserts_a_newline_and_does_not_submit(tmp_path):
    responder = FixedResponder(Completion(content="unused"))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "line one")
            await pilot.press("shift+enter")
            await type_text(pilot, "line two")
            await pilot.pause()

            assert responder.calls == []
            composer = screen.query_one(tui.Composer)
            assert composer.text == "line one\nline two"
    finally:
        await app.shutdown()


async def test_a_blank_or_whitespace_draft_refuses_visibly_and_stays_in_the_composer(tmp_path):
    responder = FixedResponder(Completion(content="unused"))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "   ")
            await pilot.press("enter")
            await pilot.pause()

            assert responder.calls == []
            assert screen.query_one(tui.Composer).text == "   "
            status = screen.query_one("#chat-status", tui.Static)
            assert "blank" in str(status.content)
    finally:
        await app.shutdown()


async def test_literal_hostile_looking_text_stays_content_never_markup(tmp_path):
    responder = FixedResponder(Completion(content="[bold]cfc[/bold] says [red]hi[/red]"))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "[bold]not a style[/bold]")
            await pilot.press("enter")
            await pilot.pause()

            lines = transcript_lines(screen)
            assert "You: [bold]not a style[/bold]" in lines
            assert "cfc: [bold]cfc[/bold] says [red]hi[/red]" in lines
    finally:
        await app.shutdown()


# === one active turn per chat: refusal, progress, independent chats ========

async def test_a_second_send_while_busy_refuses_visibly_without_clearing_the_new_draft(tmp_path):
    responder = SlowResponder()
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "first")
            await pilot.press("enter")
            await pilot.pause()
            status = screen.query_one("#chat-status", tui.Static)
            assert "Sending" in str(status.content)  # visible progress

            await type_text(pilot, "second draft")
            await pilot.press("enter")
            await pilot.pause()

            assert "already in progress" in str(status.content)
            assert screen.query_one(tui.Composer).text == "second draft"

            responder.released.set()
            await pilot.pause()
    finally:
        await app.shutdown()


async def test_two_different_chats_run_independent_workers_at_once(tmp_path):
    responder = ManualResponder()
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen_a = await open_new_chat(app, pilot, "chat a")
            await type_text(pilot, "qa")
            await pilot.press("enter")
            await pilot.pause()

            await app.pop_screen()
            await pilot.pause()
            screen_b = await open_new_chat(app, pilot, "chat b")
            await type_text(pilot, "qb")
            await pilot.press("enter")
            await pilot.pause()

            assert len(responder.calls) == 2  # neither refused the other

            responder.release(1, Completion(content="answer b"))
            await pilot.pause()
            assert "cfc: answer b" in transcript_lines(screen_b)

            await app.pop_screen()  # back to Hub
            await pilot.pause()
            app.open_chat(screen_a.chat_id)
            await pilot.pause()
            responder.release(0, Completion(content="answer a"))
            await pilot.pause()
            assert "cfc: answer a" in transcript_lines(app.screen)
    finally:
        await app.shutdown()


async def test_a_background_completion_is_picked_up_when_the_chat_is_reopened(tmp_path):
    """Navigating away while a turn runs does not cancel it; returning shows
    the current persisted state (Concept.md)."""
    responder = SlowResponder()
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            chat_id = screen.chat_id
            await type_text(pilot, "q")
            await pilot.press("enter")
            await pilot.pause()

            await app.pop_screen()  # leave for the Hub while the turn runs
            await pilot.pause()
            assert isinstance(app.screen, tui.HubScreen)

            responder.result = Completion(content="finished while away")
            responder.released.set()
            await pilot.pause()

            app.open_chat(chat_id)
            await pilot.pause()
            assert "cfc: finished while away" in transcript_lines(app.screen)
    finally:
        await app.shutdown()


# === failure and cancellation rendering =====================================

async def test_a_declared_failure_shows_its_reason_and_no_synthetic_answer(tmp_path):
    evidence = FailureEvidence(FailureKind.RESPONDER, "the provider declined")
    responder = FixedResponder(Failure(evidence))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "q")
            await pilot.press("enter")
            await pilot.pause()

            lines = transcript_lines(screen)
            assert any("the provider declined" in line for line in lines)
            assert not any(line.startswith("cfc: ") for line in lines)
            status = screen.query_one("#chat-status", tui.Static)
            assert "the provider declined" in str(status.content)
    finally:
        await app.shutdown()


async def test_an_internal_failure_shows_a_bounded_reason_never_exception_text(tmp_path):
    responder = RaisingResponder(RuntimeError("sk-super-secret-marker"))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "q")
            await pilot.press("enter")
            await pilot.pause()

            lines = transcript_lines(screen)
            assert not any("sk-super-secret-marker" in line for line in lines)
            assert not any("RuntimeError" in line for line in lines)
            status = screen.query_one("#chat-status", tui.Static)
            assert "sk-super-secret-marker" not in str(status.content)
    finally:
        await app.shutdown()


async def test_a_store_failure_ending_a_turn_shows_the_one_bounded_worker_message(tmp_path):
    """Reaches `conversation_service.TurnEndingFailed` — the worker's own
    exception path, not a declared/internal `Turn` outcome — and proves the
    UI intercepts it rather than crashing (Concept.md's crash failure mode).
    """
    responder = RaisingResponder(RuntimeError("boom"))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            real_conn = app.service._store._conn
            app.service._store._conn = _FailOnceConn(real_conn, "UPDATE cfc_turns SET finished_at")

            await type_text(pilot, "q")
            await pilot.press("enter")
            await pilot.pause()

            status = screen.query_one("#chat-status", tui.Static)
            assert str(status.content) == f"Failed: {tui._WORKER_FAILURE_MESSAGE}"
            # the app is still usable: navigation still works
            await app.pop_screen()
            await pilot.pause()
            assert isinstance(app.screen, tui.HubScreen)
    finally:
        await app.shutdown()


async def test_esc_cancels_the_active_request_first_then_returns_to_hub(tmp_path):
    responder = SlowResponder()
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "q")
            await pilot.press("enter")
            await pilot.pause()

            await pilot.press("escape")  # layer 1: cancel, stay on Chat
            await pilot.pause()
            assert isinstance(app.screen, tui.ChatScreen)
            assert "Cancelled" in str(screen.query_one("#chat-status", tui.Static).content)
            assert not app.is_chat_busy(screen.chat_id)

            await pilot.press("escape")  # layer 2: no active request, go back
            await pilot.pause()
            assert isinstance(app.screen, tui.HubScreen)
    finally:
        await app.shutdown()


async def test_esc_closes_a_modal_before_it_ever_reaches_cancel_or_back(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await pilot.press("f2")  # open the Chats modal
            assert isinstance(app.screen, tui.ChatsModal)
            await pilot.press("escape")  # layer 0: closes the modal only
            await pilot.pause()
            assert app.screen is screen
    finally:
        await app.shutdown()


# === reopening, draft/focus preservation, responsive breakpoint ============

async def test_reopening_a_chat_shows_its_persisted_history(tmp_path):
    responder = FixedResponder(Completion(content="stored answer"))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            chat_id = screen.chat_id
            await type_text(pilot, "q")
            await pilot.press("enter")
            await pilot.pause()

            await app.pop_screen()
            await pilot.pause()
            app.open_chat(chat_id)
            await pilot.pause()

            lines = transcript_lines(app.screen)
            assert "You: q" in lines
            assert "cfc: stored answer" in lines
    finally:
        await app.shutdown()


async def test_draft_and_focus_are_preserved_across_navigation(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "an unsent draft")

            await app.pop_screen()
            await pilot.pause()
            app.open_chat(screen.chat_id)
            await pilot.pause()

            composer = app.screen.query_one(tui.Composer)
            assert composer.text == "an unsent draft"
            assert composer.has_focus
    finally:
        await app.shutdown()


async def test_the_switcher_is_visible_at_80_columns_and_hidden_below_it(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            screen = await open_new_chat(app, pilot)
            assert screen.query_one("#chat-switcher", tui.ListView).display is True

            await pilot.resize_terminal(60, 24)
            await pilot.pause()
            assert screen.query_one("#chat-switcher", tui.ListView).display is False

            await pilot.resize_terminal(80, 24)
            await pilot.pause()
            assert screen.query_one("#chat-switcher", tui.ListView).display is True
    finally:
        await app.shutdown()


async def test_the_chats_action_opens_the_same_switcher_choices_as_a_modal(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test(size=(60, 24)) as pilot:
            screen = await open_new_chat(app, pilot, "only chat")
            await app.pop_screen()
            await pilot.pause()
            other = await open_new_chat(app, pilot, "second chat")

            await pilot.press("f2")
            assert isinstance(app.screen, tui.ChatsModal)
            titles = [str(w.content) for w in app.screen.query("ListItem Static")]
            assert set(titles) == {"only chat", "second chat"}
            await pilot.press("escape")
    finally:
        await app.shutdown()


# === wide docked switcher: guarded selection route (B-2.0-47, D-2.0-50) ====

def switcher_items(screen) -> list[tui.ListItem]:
    return list(screen.query_one("#chat-switcher", tui.ListView).query(tui.ListItem))


async def open_three_chats(app, pilot) -> list[tui.ChatId]:
    """Creates three stored chats and returns their ids in creation order,
    ending back on the Hub."""
    ids = []
    for title in ("chat one", "chat two", "chat three"):
        screen = await open_new_chat(app, pilot, title)
        ids.append(screen.chat_id)
        await app.pop_screen()
        await pilot.pause()
    return ids


async def test_keyboard_selection_of_another_docked_row_opens_that_chat(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            chat_ids = await open_three_chats(app, pilot)
            app.open_chat(chat_ids[0])
            await pilot.pause()

            items = switcher_items(app.screen)
            other_index = next(i for i, item in enumerate(items) if item.chat_id != chat_ids[0])
            target_id = items[other_index].chat_id

            switcher = app.screen.query_one("#chat-switcher", tui.ListView)
            switcher.focus()
            switcher.index = other_index
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            assert isinstance(app.screen, tui.ChatScreen)
            assert app.screen.chat_id == target_id
    finally:
        await app.shutdown()


async def test_mouse_selection_reaches_the_same_route_and_result(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            chat_ids = await open_three_chats(app, pilot)
            app.open_chat(chat_ids[0])
            await pilot.pause()

            items = switcher_items(app.screen)
            other_index = next(i for i, item in enumerate(items) if item.chat_id != chat_ids[0])
            target_id = items[other_index].chat_id

            await pilot.click(items[other_index])
            await pilot.pause()

            assert isinstance(app.screen, tui.ChatScreen)
            assert app.screen.chat_id == target_id
    finally:
        await app.shutdown()


async def test_selecting_the_current_row_leaves_screen_stack_and_screen_unchanged(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            chat_ids = await open_three_chats(app, pilot)
            app.open_chat(chat_ids[0])
            await pilot.pause()
            screen = app.screen
            screen_count_before = len(app.screen_stack)

            current_index = next(
                i for i, item in enumerate(switcher_items(screen)) if item.chat_id == chat_ids[0]
            )
            switcher = screen.query_one("#chat-switcher", tui.ListView)
            switcher.focus()
            switcher.index = current_index
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            assert app.screen is screen
            assert len(app.screen_stack) == screen_count_before
    finally:
        await app.shutdown()


async def test_an_unrelated_list_view_selected_event_is_rejected(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            chat_ids = await open_three_chats(app, pilot)
            app.open_chat(chat_ids[0])
            await pilot.pause()
            screen = app.screen

            other_id = next(item.chat_id for item in switcher_items(screen) if item.chat_id != chat_ids[0])
            foreign_list = tui.ListView(id="not-the-chat-switcher")
            foreign_item = tui.ListItem()
            foreign_item.chat_id = other_id
            screen.post_message(tui.ListView.Selected(foreign_list, foreign_item, 0))
            await pilot.pause()

            assert app.screen is screen
            assert app.screen.chat_id == chat_ids[0]
    finally:
        await app.shutdown()


async def test_current_switcher_item_has_the_current_class_and_a_distinct_style(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            chat_ids = await open_three_chats(app, pilot)
            app.open_chat(chat_ids[0])
            await pilot.pause()

            items = switcher_items(app.screen)
            current = next(item for item in items if item.chat_id == chat_ids[0])
            ordinary = next(item for item in items if item.chat_id != chat_ids[0])
            assert current.has_class("chat-switcher-current")
            assert not ordinary.has_class("chat-switcher-current")
            assert current.styles.color != ordinary.styles.color
            assert current.styles.text_style != ordinary.styles.text_style

            # switch to a different chat: the class and style follow the
            # displayed screen's chat_id, not whatever was highlighted
            other_index = next(i for i, item in enumerate(items) if item.chat_id != chat_ids[0])
            switcher = app.screen.query_one("#chat-switcher", tui.ListView)
            switcher.focus()
            switcher.index = other_index
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            new_items = switcher_items(app.screen)
            new_current = next(item for item in new_items if item.chat_id == app.screen.chat_id)
            new_ordinary = next(item for item in new_items if item.chat_id != app.screen.chat_id)
            assert new_current.has_class("chat-switcher-current")
            assert new_current.styles.color != new_ordinary.styles.color
    finally:
        await app.shutdown()


async def test_quit_cancels_running_workers_then_closes_responder_and_service(tmp_path):
    responder = SlowResponder()
    responder.aclose_called = False

    async def aclose():
        responder.aclose_called = True

    responder.aclose = aclose

    app = make_app(tmp_path, responder=responder)
    async with app.run_test() as pilot:
        screen = await open_new_chat(app, pilot)
        await type_text(pilot, "q")
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_chat_busy(screen.chat_id)

        await pilot.press("ctrl+q")

    assert responder.aclose_called is True
    assert app.service._store._closed is True


# === chat replacement: one chat screen at a time (B-2.0-55) =================

async def test_wide_switcher_replaces_the_screen_and_preserves_both_drafts(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            screen_a = await open_new_chat(app, pilot, "chat a")
            await type_text(pilot, "draft a")
            await app.pop_screen()
            await pilot.pause()
            screen_b = await open_new_chat(app, pilot, "chat b")
            await type_text(pilot, "draft b")
            await pilot.pause()

            stack_before = len(app.screen_stack)

            def switch_via_docked_row(target_id):
                items = switcher_items(app.screen)
                index = next(i for i, item in enumerate(items) if item.chat_id == target_id)
                switcher = app.screen.query_one("#chat-switcher", tui.ListView)
                switcher.focus()
                switcher.index = index

            switch_via_docked_row(screen_a.chat_id)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            assert len(app.screen_stack) == stack_before  # replaced, never pushed
            assert app.screen.chat_id == screen_a.chat_id
            assert app.screen.query_one(tui.Composer).text == "draft a"
            assert app.screen.query_one(tui.Composer).has_focus

            switch_via_docked_row(screen_b.chat_id)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            assert len(app.screen_stack) == stack_before
            assert app.screen.chat_id == screen_b.chat_id
            assert app.screen.query_one(tui.Composer).text == "draft b"

            # one Esc from a switched chat reaches the Hub — no screen left behind
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, tui.HubScreen)
    finally:
        await app.shutdown()


async def test_narrow_chats_modal_replaces_the_screen_and_preserves_both_drafts(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test(size=(60, 24)) as pilot:
            screen_a = await open_new_chat(app, pilot, "chat a")
            await type_text(pilot, "draft a")
            await app.pop_screen()
            await pilot.pause()
            screen_b = await open_new_chat(app, pilot, "chat b")
            await type_text(pilot, "draft b")
            await pilot.pause()

            stack_before = len(app.screen_stack)
            await pilot.press("f2")
            assert isinstance(app.screen, tui.ChatsModal)
            list_view = app.screen.query_one("#chats-modal-list", tui.ListView)
            items = list(list_view.query(tui.ListItem))
            target_index = next(i for i, item in enumerate(items) if item.chat_id == screen_a.chat_id)
            list_view.index = target_index
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            assert len(app.screen_stack) == stack_before
            assert isinstance(app.screen, tui.ChatScreen)
            assert app.screen.chat_id == screen_a.chat_id
            assert app.screen.query_one(tui.Composer).text == "draft a"
            assert app.screen.query_one(tui.Composer).has_focus

            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, tui.HubScreen)
    finally:
        await app.shutdown()


async def test_a_completion_while_its_screen_is_replaced_is_visible_on_return(tmp_path):
    """Concept.md's "Optimistic chat state" failure mode: a replaced screen's
    worker keeps running app-owned, and reopening renders the canonical
    snapshot rather than a stale or lost screen-local guess."""
    responder = SlowResponder()
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test(size=(80, 24)) as pilot:
            screen_a = await open_new_chat(app, pilot, "chat a")
            await app.pop_screen()
            await pilot.pause()
            screen_b = await open_new_chat(app, pilot, "chat b")
            await app.pop_screen()
            await pilot.pause()

            app.open_chat(screen_a.chat_id)
            await pilot.pause()
            await type_text(pilot, "q")
            await pilot.press("enter")
            await pilot.pause()
            assert app.is_chat_busy(screen_a.chat_id)

            def switch_via_docked_row(target_id):
                items = switcher_items(app.screen)
                index = next(i for i, item in enumerate(items) if item.chat_id == target_id)
                switcher = app.screen.query_one("#chat-switcher", tui.ListView)
                switcher.focus()
                switcher.index = index

            # replace chat a (turn still running) with chat b
            switch_via_docked_row(screen_b.chat_id)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert app.screen.chat_id == screen_b.chat_id
            assert app.is_chat_busy(screen_a.chat_id)

            responder.result = Completion(content="finished while replaced")
            responder.released.set()
            await pilot.pause()

            # switch back to chat a — its own screen was gone the whole time
            switch_via_docked_row(screen_a.chat_id)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            assert app.screen.chat_id == screen_a.chat_id
            assert "cfc: finished while replaced" in transcript_lines(app.screen)
    finally:
        await app.shutdown()


# === omitted-turn recovery: honest wording plus per-turn restore ===========
# (B-2.0-55, D-2.0-53)

def restore_button_for(screen, turn_id) -> tui.Button:
    return screen.query_one(f"#restore-{turn_id.value}", tui.Button)


def latest_turn(app, chat_id):
    return app.service.snapshot(chat_id).turns[-1]


async def test_a_failed_turns_wording_omits_without_claiming_non_delivery(tmp_path):
    evidence = FailureEvidence(FailureKind.RESPONDER, "the provider declined")
    responder = FixedResponder(Failure(evidence))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "q")
            await pilot.press("enter")
            await pilot.pause()

            lines = transcript_lines(screen)
            assert any(tui._OMISSION_NOTICE in line for line in lines)
            assert not any("never received" in line.lower() for line in lines)
            assert not any("did not reach" in line.lower() for line in lines)

            turn = latest_turn(app, screen.chat_id)
            assert restore_button_for(screen, turn.id).label.plain == tui._RESTORE_LABEL
    finally:
        await app.shutdown()


async def test_a_cancelled_turns_wording_omits_without_claiming_non_delivery(tmp_path):
    responder = SlowResponder()
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "q")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("escape")  # cancels the active turn
            await pilot.pause()

            lines = transcript_lines(screen)
            assert "[turn cancelled]" in lines
            assert any(tui._OMISSION_NOTICE in line for line in lines)
            assert not any("never received" in line.lower() for line in lines)

            turn = latest_turn(app, screen.chat_id)
            assert restore_button_for(screen, turn.id) is not None
    finally:
        await app.shutdown()


async def test_a_later_request_omits_the_failed_turns_user_message(tmp_path):
    """Uses the real `provider_wire` converter — untouched by this loop — to
    interpret the raw canonical snapshot the responder received, proving the
    settled omission rule still holds end to end through the new wording and
    restore control, without re-testing `provider_wire.py`'s own unit proof.
    """
    evidence = FailureEvidence(FailureKind.RESPONDER, "declined")
    responder = ManualResponder()
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "first, will fail")
            await pilot.press("enter")
            await pilot.pause()
            responder.release(0, Failure(evidence))
            await pilot.pause()

            await type_text(pilot, "second, will succeed")
            await pilot.press("enter")
            await pilot.pause()
            responder.release(1, Completion(content="ok"))
            await pilot.pause()

            plan = responder.calls[1]
            wire_user_texts = [m.content for m in plan.messages if m.role == "user"]
            assert "first, will fail" not in wire_user_texts
            assert "second, will succeed" in wire_user_texts
            assert len(plan.omitted) == 1
    finally:
        await app.shutdown()


async def test_restoring_copies_the_exact_stored_message_and_focuses_the_composer(tmp_path):
    evidence = FailureEvidence(FailureKind.RESPONDER, "declined")
    responder = FixedResponder(Failure(evidence))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "the exact stored text")
            await pilot.press("enter")
            await pilot.pause()
            assert screen.query_one(tui.Composer).text == ""

            turn = latest_turn(app, screen.chat_id)
            button = restore_button_for(screen, turn.id)
            button.focus()
            await pilot.pause()
            await pilot.press("enter")  # keyboard route: a focused Button
            await pilot.pause()

            composer = screen.query_one(tui.Composer)
            assert composer.text == "the exact stored text"
            assert composer.has_focus
    finally:
        await app.shutdown()


async def test_restore_activates_by_mouse_click_the_same_as_keyboard(tmp_path):
    evidence = FailureEvidence(FailureKind.RESPONDER, "declined")
    responder = FixedResponder(Failure(evidence))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "click me back")
            await pilot.press("enter")
            await pilot.pause()

            turn = latest_turn(app, screen.chat_id)
            button = restore_button_for(screen, turn.id)
            await pilot.click(button)
            await pilot.pause()

            composer = screen.query_one(tui.Composer)
            assert composer.text == "click me back"
    finally:
        await app.shutdown()


async def test_restore_does_not_contact_the_responder(tmp_path):
    evidence = FailureEvidence(FailureKind.RESPONDER, "declined")
    responder = FixedResponder(Failure(evidence))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "q")
            await pilot.press("enter")
            await pilot.pause()
            calls_before = len(responder.calls)

            turn = latest_turn(app, screen.chat_id)
            await pilot.click(restore_button_for(screen, turn.id))
            await pilot.pause()

            assert len(responder.calls) == calls_before
    finally:
        await app.shutdown()


async def test_multiple_omissions_each_restore_their_own_message(tmp_path):
    evidence = FailureEvidence(FailureKind.RESPONDER, "declined")
    responder = FixedResponder(Failure(evidence))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "omission one")
            await pilot.press("enter")
            await pilot.pause()
            turn_one = latest_turn(app, screen.chat_id)

            await type_text(pilot, "omission two")
            await pilot.press("enter")
            await pilot.pause()
            turn_two = latest_turn(app, screen.chat_id)
            assert turn_one.id != turn_two.id

            await pilot.click(restore_button_for(screen, turn_two.id))
            await pilot.pause()
            assert screen.query_one(tui.Composer).text == "omission two"

            screen.query_one(tui.Composer).text = ""
            await pilot.pause()
            await pilot.click(restore_button_for(screen, turn_one.id))
            await pilot.pause()
            assert screen.query_one(tui.Composer).text == "omission one"
    finally:
        await app.shutdown()


async def test_restore_refuses_and_preserves_state_when_the_composer_has_a_draft(tmp_path):
    evidence = FailureEvidence(FailureKind.RESPONDER, "declined")
    responder = FixedResponder(Failure(evidence))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "q")
            await pilot.press("enter")
            await pilot.pause()
            turn = latest_turn(app, screen.chat_id)

            await type_text(pilot, "an unrelated draft")
            await pilot.pause()
            await pilot.click(restore_button_for(screen, turn.id))
            await pilot.pause()

            assert screen.query_one(tui.Composer).text == "an unrelated draft"
            status = screen.query_one("#chat-status", tui.Static)
            assert "already" in str(status.content) or "draft" in str(status.content)

            stored = app.service.snapshot(screen.chat_id)
            stored_user_texts = [m.content for m in stored.messages if m.role is Role.USER]
            assert "q" in stored_user_texts
    finally:
        await app.shutdown()


async def test_restore_refuses_with_a_bounded_notice_when_the_stored_message_is_missing(tmp_path):
    """The stored-user-message-gone case is not reachable through ordinary
    use; the store row is removed directly to exercise cfc's own defensive
    refusal, then restore is still driven through its real mouse route."""
    evidence = FailureEvidence(FailureKind.RESPONDER, "declined")
    responder = FixedResponder(Failure(evidence))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "q")
            await pilot.press("enter")
            await pilot.pause()
            turn = latest_turn(app, screen.chat_id)

            app.service._store._conn.execute(
                "DELETE FROM cfc_messages WHERE turn_id = ?", (turn.id.value,)
            )

            await pilot.click(restore_button_for(screen, turn.id))
            await pilot.pause()

            assert screen.query_one(tui.Composer).text == ""
            status = screen.query_one("#chat-status", tui.Static)
            assert tui._RESTORE_MISSING_NOTICE == str(status.content)
    finally:
        await app.shutdown()


async def test_a_submitted_restored_copy_is_a_new_turn_and_the_original_is_unchanged(tmp_path):
    evidence = FailureEvidence(FailureKind.RESPONDER, "declined")
    responder = ManualResponder()
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "try again please")
            await pilot.press("enter")
            await pilot.pause()
            responder.release(0, Failure(evidence))
            await pilot.pause()
            original_turn = latest_turn(app, screen.chat_id)

            await pilot.click(restore_button_for(screen, original_turn.id))
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            responder.release(1, Completion(content="second time worked"))
            await pilot.pause()

            snapshot = app.service.snapshot(screen.chat_id)
            assert len(snapshot.turns) == 2
            unchanged_original = next(t for t in snapshot.turns if t.id == original_turn.id)
            assert isinstance(unchanged_original.outcome, tui.FailedOutcome)
            new_turn = next(t for t in snapshot.turns if t.id != original_turn.id)
            assert new_turn.id != original_turn.id
            assert isinstance(new_turn.outcome, tui.CompletedOutcome)

            lines = transcript_lines(screen)
            # the original turn's message and the resubmitted copy are two
            # separately stored user messages, not one merged/deduped line
            assert lines.count("You: try again please") == 2
            assert "cfc: second time worked" in lines
            assert any(tui._OMISSION_NOTICE in line for line in lines)  # still marked omitted
    finally:
        await app.shutdown()


# === theme: optional durable startup preference (D-2.0-49) =================

async def test_build_app_applies_the_default_dark_theme_when_unset(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    app = tui.build_app(path, responder_factory=_no_network_responder_factory)
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme == "textual-dark"
            assert list(app._notifications) == []
    finally:
        await app.shutdown()


async def test_build_app_applies_the_light_theme_when_configured(tmp_path):
    path = write_config(tmp_path, VALID_BODY + "TUI_THEME = 'light'\n")
    app = tui.build_app(path, responder_factory=_no_network_responder_factory)
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme == "textual-light"
            assert list(app._notifications) == []
    finally:
        await app.shutdown()


async def test_build_app_falls_back_to_dark_with_a_visible_notice_for_an_invalid_theme(tmp_path):
    path = write_config(tmp_path, VALID_BODY + "TUI_THEME = 'purple'\n")
    app = tui.build_app(path, responder_factory=_no_network_responder_factory)
    try:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.theme == "textual-dark"  # still reaches ordinary chat
            notices = [n.message for n in app._notifications]
            assert any("TUI_THEME" in message and "purple" in message for message in notices)
    finally:
        await app.shutdown()


async def test_build_app_never_mutates_config_py_for_an_invalid_theme(tmp_path):
    path = write_config(tmp_path, VALID_BODY + "TUI_THEME = 'purple'\n")
    before = path.read_text(encoding="utf-8")
    app = tui.build_app(path, responder_factory=_no_network_responder_factory)
    try:
        assert path.read_text(encoding="utf-8") == before
    finally:
        await app.shutdown()


def test_cfc_app_defaults_to_dark_without_an_explicit_theme_argument(tmp_path):
    app = make_app(tmp_path, theme=None)
    assert app._theme_settings.name == "dark"
    app.service.close()


# === the cfc-owned Ctrl+P command set (D-2.0-49, D-2.0-56) ==================

async def command_palette_option_names(app) -> list[str]:
    from textual.command import CommandList
    await asyncio.sleep(0)
    command_list = app.screen.query_one(CommandList)
    return sorted(
        str(command_list.get_option_at_index(i).prompt).splitlines()[0]
        for i in range(command_list.option_count)
    )


async def test_ctrl_p_reaches_exactly_the_cfc_command_set_on_the_hub(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            await pilot.press("ctrl+p")
            await pilot.pause()
            await pilot.pause()
            assert await command_palette_option_names(app) == [
                "Keyboard help", "Quit cfc", "Save screenshot",
            ]
    finally:
        await app.shutdown()


async def test_ctrl_p_reaches_exactly_the_cfc_command_set_on_a_chat_screen(tmp_path):
    """An ordinary Chat's palette gains Context and Model on top of the
    three commands every screen shares (Work Order Steps 4 and 5)."""
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            await pilot.press("ctrl+p")
            await pilot.pause()
            await pilot.pause()
            assert await command_palette_option_names(app) == [
                "Context", "Keyboard help", "Model", "Quit cfc", "Save screenshot",
            ]
    finally:
        await app.shutdown()


async def test_ctrl_p_reaches_exactly_the_cfc_command_set_on_startup_failure(tmp_path):
    app = tui.StartupFailureApp(
        "cfc could not start.", screenshots_dir=tmp_path / "screenshots",
    )
    async with app.run_test() as pilot:
        await pilot.press("ctrl+p")
        await pilot.pause()
        await pilot.pause()
        assert await command_palette_option_names(app) == [
            "Keyboard help", "Quit cfc", "Save screenshot",
        ]


async def test_keyboard_help_command_opens_with_the_literal_mapping_and_escape_closes_it(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            await run_command(pilot, "Keyboard help")
            assert isinstance(app.screen, tui.KeyboardHelpModal)

            mapping = app.screen.query_one("#keyboard-help-windows-terminal", tui.Static)
            rendered = str(mapping.content)
            assert '\\u001b[13;2u' in rendered  # the literal JSON spelling
            assert "\x1b" not in rendered       # never a live escape byte
            assert "sendInput" in rendered
            assert "shift+enter" in rendered

            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, tui.KeyboardHelpModal)
    finally:
        await app.shutdown()


async def test_quit_command_follows_the_existing_orderly_shutdown(tmp_path):
    responder = SlowResponder()
    responder.aclose_called = False

    async def aclose():
        responder.aclose_called = True

    responder.aclose = aclose

    app = make_app(tmp_path, responder=responder)
    async with app.run_test() as pilot:
        screen = await open_new_chat(app, pilot)
        await type_text(pilot, "q")
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_chat_busy(screen.chat_id)

        await run_command(pilot, "Quit cfc")

    assert responder.aclose_called is True
    assert app.service._store._closed is True


async def test_save_screenshot_command_reports_an_exact_path_and_writes_a_complete_svg(tmp_path):
    target = tmp_path / "screenshots"
    app = make_app(tmp_path, screenshots_dir=target)
    try:
        async with app.run_test() as pilot:
            await run_command(pilot, "Save screenshot")

            files = list(target.glob("*.svg"))
            assert len(files) == 1
            content = files[0].read_text(encoding="utf-8")
            assert content.startswith("<svg") or "<svg" in content[:200]
            assert content.rstrip().endswith("</svg>")

            notices = [n.message for n in app._notifications]
            assert any(str(files[0]) in message for message in notices)
    finally:
        await app.shutdown()


async def test_save_screenshot_refuses_when_the_directory_is_blocked_by_a_file(tmp_path):
    target = tmp_path / "screenshots"
    target.write_text("not a directory", encoding="utf-8")
    app = make_app(tmp_path, screenshots_dir=target)
    try:
        async with app.run_test() as pilot:
            await run_command(pilot, "Save screenshot")

            assert target.is_file()  # untouched — never replaced or removed
            notices = [n.message for n in app._notifications]
            assert any(str(target) in message for message in notices)
            assert not any(
                "Traceback" in message or "NotADirectoryError" in message for message in notices
            )
    finally:
        await app.shutdown()


async def test_save_screenshot_refuses_on_a_permission_failure_writing(tmp_path):
    target = tmp_path / "screenshots"
    target.mkdir()
    target.chmod(0o500)  # read + execute, no write
    app = make_app(tmp_path, screenshots_dir=target)
    try:
        async with app.run_test() as pilot:
            await run_command(pilot, "Save screenshot")

            assert list(target.glob("*.svg")) == []
            assert list(target.glob(".*")) == []  # no leftover temp file either
            notices = [n.message for n in app._notifications]
            assert any(str(target) in message for message in notices)
    finally:
        await app.shutdown()
        target.chmod(0o700)


def test_write_screenshot_is_collision_resistant(tmp_path):
    directory = tmp_path / "shots"
    stamp = "20260101T000000000000"
    first = tui._write_screenshot("<svg>one</svg>", directory, timestamp=stamp)
    second = tui._write_screenshot("<svg>two</svg>", directory, timestamp=stamp)

    assert first != second
    assert first.name == f"cfc-{stamp}.svg"
    assert second.name == f"cfc-{stamp}-2.svg"
    assert first.read_text(encoding="utf-8") == "<svg>one</svg>"
    assert second.read_text(encoding="utf-8") == "<svg>two</svg>"


def test_write_screenshot_refuses_on_a_replacement_failure_and_leaves_no_partial_file(
    tmp_path, monkeypatch,
):
    directory = tmp_path / "shots"
    stamp = "20260101T000000000000"
    real_replace = Path.replace

    def failing_replace(self, target):
        if self.suffix == ".tmp":
            raise OSError("simulated replacement failure")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(tui.ScreenshotError) as exc_info:
        tui._write_screenshot("<svg/>", directory, timestamp=stamp)

    assert str(directory) in str(exc_info.value)
    assert list(directory.glob("*.svg")) == []
    assert list(directory.glob(".*")) == []


# === Context modal: selector, inspector, and one literal preview route =====

def context_modal_row_texts(app) -> list[str]:
    modal = app.screen
    assert isinstance(modal, tui.ContextModal)
    return [str(s.content) for s in modal.query("#context-modal-list Static")]


async def open_context_modal(pilot) -> tui.ContextModal:
    await run_command(pilot, "Context")
    return pilot.app.screen


async def select_row(pilot, index: int) -> None:
    list_view = pilot.app.screen.query_one("#context-modal-list", tui.ListView)
    list_view.index = index
    await pilot.pause()


def configured_empty_vault(tmp_path: Path) -> settings.VaultSettings:
    """All four categories configured and usable, every directory empty —
    the "you have chosen nothing yet" vault, as distinct from `empty_vault`,
    where nothing is configured at all (B-2.0-62).
    """
    directories = {}
    for name in ("prefs", "personas", "traits", "first_messages"):
        directory = tmp_path / f"vault-{name}"
        directory.mkdir(parents=True, exist_ok=True)
        directories[name] = directory
    return real_vault(
        tmp_path, prefs=directories["prefs"], personas=directories["personas"],
        traits=directories["traits"], first_messages=directories["first_messages"],
    )


async def test_context_modal_lists_rows_in_request_order_with_nothing_selected(tmp_path):
    app = make_app(tmp_path, vault=configured_empty_vault(tmp_path))
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            modal = await open_context_modal(pilot)
            assert isinstance(modal, tui.ContextModal)
            rows = context_modal_row_texts(app)
            assert rows[0].startswith("System Instructions:")
            assert rows[1] == "User Preferences: none selected"
            assert rows[2] == "Persona: none selected"
            assert rows[3] == "Add trait…"
            assert rows[4].startswith("First Message:")
    finally:
        await app.shutdown()


# --- B-2.0-60: one transcript rebuild at a time ----------------------------

async def test_closing_context_while_a_turn_finishes_does_not_crash_the_transcript(tmp_path):
    """The playtest crash, by its real route. A failed turn puts an
    id-carrying **Restore to composer** button in the transcript; closing
    the Context modal starts a rebuild on the App's pump (the dismiss
    callback) and another on this screen's own pump (`on_screen_resume`),
    and a worker finishing at that moment starts a third from its own task.
    Interleaved, two of them mount the same button id and Textual raises
    `DuplicateIds`, which ends the app.
    """
    traits_dir = tmp_path / "traits"
    write_source(traits_dir, "dry.md", "dry")
    responder = SlowResponder()
    app = make_app(tmp_path, responder, vault=real_vault(tmp_path, traits=traits_dir))
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            app.service.add_trait(screen.chat_id, "dry.md")

            await type_text(pilot, "first")
            await pilot.press("enter")
            await responder.started.wait()
            await pilot.pause()
            await pilot.press("escape")  # cancel: leaves one restore button
            await pilot.pause()
            assert len(screen.query(".restore-button")) == 1

            responder.started.clear()
            await type_text(pilot, "second")
            await pilot.press("enter")
            await responder.started.wait()
            await pilot.pause()

            await open_context_modal(pilot)
            # while here: a selection change during an active turn refuses
            # visibly instead of escaping a Textual callback (the guard
            # `Update.md` shipped without end-to-end proof)
            rows = context_modal_row_texts(app)
            await select_row(pilot, next(i for i, r in enumerate(rows) if r.startswith("Trait:")))
            await pilot.click("#context-action-remove")
            await pilot.pause()
            assert "request in progress" in str(
                app.screen.query_one("#context-modal-error", tui.Static).content)
            assert app.service.get_chat(screen.chat_id).context_selection.traits == ("dry.md",)

            responder.released.set()   # the worker finishes as the modal closes
            await pilot.press("escape")
            await pilot.pause()
            await pilot.pause()

            assert isinstance(app.screen, tui.ChatScreen)
            assert len(screen.query(".restore-button")) == 1
    finally:
        await app.shutdown()


async def test_concurrent_refreshes_render_once_rather_than_twice(tmp_path):
    """The same contract without the timing: two rebuilds started at once
    from two tasks produce one transcript and one switcher, not two. Called
    directly on purpose — this proves the concurrency rule itself, which no
    single keypress can express.
    """
    responder = FixedResponder(Failure(evidence=FailureEvidence(
        kind=FailureKind.RESPONDER, reason="the provider refused the request (HTTP 503)")))
    app = make_app(tmp_path, responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "hello")
            await pilot.press("enter")
            await pilot.pause()
            assert len(screen.query(".restore-button")) == 1

            await asyncio.gather(
                screen.refresh_from_service(),
                screen.refresh_from_service(),
                screen.refresh_from_service(),
            )
            assert len(screen.query(".restore-button")) == 1
            assert len(screen.query("#chat-switcher ListItem")) == 1
    finally:
        await app.shutdown()


# --- B-2.0-62: an unusable category says so, everywhere it appears ---------

async def test_an_unconfigured_category_row_names_its_reason_not_none_selected(tmp_path):
    """The playtest's own route: `USER_PREFERENCES_DIR` unset while Traits
    work. `none selected` on that row reads as an ordinary empty choice and
    sends a person looking for a selector that cannot exist.
    """
    traits_dir = tmp_path / "traits"
    write_source(traits_dir, "dry.md", "dry")
    vault = settings.VaultSettings(
        root=tmp_path,
        user_preferences=settings.VaultCategorySettings(
            unavailable_reason="USER_PREFERENCES_DIR is not set"),
        personas=settings.VaultCategorySettings(unavailable_reason="PERSONAS_DIR is not set"),
        traits=settings.VaultCategorySettings(path=traits_dir),
        first_messages=settings.VaultCategorySettings(
            unavailable_reason="FIRST_MESSAGES_DIR is not set"),
    )
    app = make_app(tmp_path, vault=vault)
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            await open_context_modal(pilot)
            rows = context_modal_row_texts(app)

            assert rows[1] == (
                "User Preferences: unavailable (USER_PREFERENCES_DIR is not set) "
                "— correct config.py to use this category"
            )
            assert rows[2] == (
                "Persona: unavailable (PERSONAS_DIR is not set) "
                "— correct config.py to use this category"
            )
            assert rows[3] == "Add trait…"  # the one category that works stays ordinary
            assert rows[4] == (
                "First Message: unavailable (FIRST_MESSAGES_DIR is not set) "
                "— correct config.py to use this category"
            )
    finally:
        await app.shutdown()


async def test_an_unconfigured_categorys_change_picker_says_why_it_is_empty(tmp_path):
    """The picker that stopped the playtest: one bare `None (clear
    selection)` row and no explanation.
    """
    app = make_app(tmp_path, vault=empty_vault())
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            await open_context_modal(pilot)
            await select_row(pilot, 1)  # User Preferences
            await pilot.click("#context-action-change")
            await pilot.pause()

            assert isinstance(app.screen, tui.SourcePickerModal)
            notice = app.screen.query_one("#source-picker-notice", tui.Static)
            assert "not configured" in str(notice.content)
            assert "correct config.py" in str(notice.content)
            # the clear route survives, for a selection made while it worked
            options = list(app.screen.query("#source-picker-list ListItem"))
            assert len(options) == 1
    finally:
        await app.shutdown()


async def test_an_unconfigured_traits_category_says_so_on_the_add_row(tmp_path):
    app = make_app(tmp_path, vault=empty_vault())
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            await open_context_modal(pilot)
            rows = context_modal_row_texts(app)
            add_row = next(r for r in rows if r.startswith("Add trait…"))
            assert add_row == (
                "Add trait… unavailable (not configured) "
                "— correct config.py to use this category"
            )

            await select_row(pilot, rows.index(add_row))
            await pilot.click("#context-action-add")
            await pilot.pause()
            assert isinstance(app.screen, tui.SourcePickerModal)
            notice = app.screen.query_one("#source-picker-notice", tui.Static)
            assert "correct config.py" in str(notice.content)
    finally:
        await app.shutdown()


async def test_a_configured_but_empty_traits_directory_stays_an_ordinary_empty_picker(tmp_path):
    """The third state, and the reason the other two need separating: the
    directory is configured and readable, it just holds nothing yet. That is
    the vault's business, not `config.py`'s.
    """
    app = make_app(tmp_path, vault=configured_empty_vault(tmp_path))
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            await open_context_modal(pilot)
            await select_row(pilot, 3)  # Add trait
            await pilot.click("#context-action-add")
            await pilot.pause()
            assert isinstance(app.screen, tui.SourcePickerModal)
            assert not app.screen.query("#source-picker-notice")
            empty = app.screen.query_one("#source-picker-empty", tui.Static)
            assert str(empty.content) == "Nothing available to select."
    finally:
        await app.shutdown()


async def test_an_unconfigured_categorys_preview_names_the_configuration_route(tmp_path):
    app = make_app(tmp_path, vault=empty_vault())
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            await open_context_modal(pilot)
            await select_row(pilot, 2)  # Persona
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.SourcePreviewModal)
            body = str(app.screen.query_one("#source-preview-body", tui.Static).content)
            assert "unavailable: not configured" in body
            assert "correct config.py" in body
    finally:
        await app.shutdown()


async def test_an_unconfigured_first_messages_directory_says_so_instead_of_none(tmp_path):
    """A persona is selected and readable; only the companion directory is
    missing. `none for this persona` would blame the persona for a setting.
    """
    personas_dir = tmp_path / "personas"
    write_source(personas_dir, "muse.md", "You are Muse.")
    vault = real_vault(tmp_path, personas=personas_dir)  # first_messages unset
    app = make_app(tmp_path, vault=vault)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            app.service.set_persona(screen.chat_id, "muse.md")
            await open_context_modal(pilot)
            rows = context_modal_row_texts(app)
            first_message_row = next(r for r in rows if r.startswith("First Message:"))
            assert first_message_row == (
                "First Message: unavailable (not configured) "
                "— correct config.py to use this category"
            )
    finally:
        await app.shutdown()


async def test_a_frozen_opening_outlives_its_categorys_configuration(tmp_path):
    """An opening is stored conversation content: unsetting the directory it
    came from cannot turn what a chat actually opened with into an
    unavailability notice.
    """
    personas_dir = tmp_path / "personas"
    first_messages_dir = tmp_path / "first_messages"
    write_source(personas_dir, "muse.md", "You are Muse.")
    write_source(first_messages_dir, "muse.md", "Hello, I am Muse.")
    app = make_app(tmp_path, vault=real_vault(
        tmp_path, personas=personas_dir, first_messages=first_messages_dir))
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            app.service.set_persona(screen.chat_id, "muse.md")
            assert app.service.get_chat(screen.chat_id).opening is not None
            # the directory goes away from configuration afterwards
            app.service._vault = real_vault(tmp_path, personas=personas_dir)

            await open_context_modal(pilot)
            rows = context_modal_row_texts(app)
            first_message_row = next(r for r in rows if r.startswith("First Message:"))
            assert first_message_row.startswith("First Message: muse.md, 17 chars, ")
    finally:
        await app.shutdown()


async def test_selecting_a_row_via_keyboard_opens_its_literal_preview(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            await open_context_modal(pilot)
            await select_row(pilot, 0)  # System Instructions
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.SourcePreviewModal)
            body = app.screen.query_one("#source-preview-body", tui.Static)
            from cfc import context as context_mod
            assert str(body.content) == context_mod.SYSTEM_INSTRUCTIONS_TEXT
    finally:
        await app.shutdown()


async def test_selecting_a_row_via_mouse_does_the_same_as_keyboard(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            await open_context_modal(pilot)
            items = list(app.screen.query("#context-modal-list ListItem"))
            await pilot.click(items[0])
            await pilot.pause()
            assert isinstance(app.screen, tui.SourcePreviewModal)
    finally:
        await app.shutdown()


async def test_esc_closes_only_the_top_modal_through_preview_then_picker_then_context(tmp_path):
    """Nested-Escape (Work Order Step 4): Preview -> Context -> Chat, and
    Picker -> Context -> Chat, each Esc closing exactly one layer.
    """
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await open_context_modal(pilot)
            context_screen = app.screen

            await select_row(pilot, 0)  # System Instructions
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.SourcePreviewModal)
            await pilot.press("escape")  # layer 0: closes the preview only
            await pilot.pause()
            assert app.screen is context_screen

            await select_row(pilot, 1)  # User Preferences
            await pilot.click("#context-action-change")
            await pilot.pause()
            assert isinstance(app.screen, tui.SourcePickerModal)
            await pilot.press("escape")  # layer 0: closes the picker only
            await pilot.pause()
            assert app.screen is context_screen

            await pilot.press("escape")  # layer 1: closes Context, back to Chat
            await pilot.pause()
            assert app.screen is screen
    finally:
        await app.shutdown()


async def test_change_is_disabled_for_a_row_it_does_not_apply_to(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            await open_context_modal(pilot)
            await select_row(pilot, 0)  # System Instructions: not user-editable
            assert app.screen.query_one("#context-action-change", tui.Button).disabled is True
            await select_row(pilot, 1)  # User Preferences: editable
            assert app.screen.query_one("#context-action-change", tui.Button).disabled is False
    finally:
        await app.shutdown()


async def test_changing_user_preferences_persists_and_survives_reopen(tmp_path):
    prefs_dir = tmp_path / "prefs"
    write_source(prefs_dir, "formal.md", "Be formal.")
    vault = real_vault(tmp_path, prefs=prefs_dir)
    app = make_app(tmp_path, vault=vault)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            chat_id = screen.chat_id
            await open_context_modal(pilot)
            await select_row(pilot, 1)  # User Preferences
            await pilot.click("#context-action-change")
            await pilot.pause()
            assert isinstance(app.screen, tui.SourcePickerModal)
            options = list(app.screen.query("#source-picker-list ListItem"))
            await pilot.click(options[-1])  # the real "formal" option, after "None"
            await pilot.pause()

            rows = context_modal_row_texts(app)
            assert rows[1] == "User Preferences: formal, 10 chars, " + \
                app.service.context_rows(chat_id).user_preferences.source.fingerprint[:12]

            await pilot.press("escape")  # close Context
            await pilot.pause()
            assert app.service.get_chat(chat_id).context_selection.user_preferences == "formal.md"

            await app.pop_screen()
            await pilot.pause()
            app.open_chat(chat_id)
            await pilot.pause()
            assert app.service.get_chat(chat_id).context_selection.user_preferences == "formal.md"
    finally:
        await app.shutdown()


async def test_change_can_clear_a_selection_with_the_none_option(tmp_path):
    prefs_dir = tmp_path / "prefs"
    write_source(prefs_dir, "formal.md", "Be formal.")
    vault = real_vault(tmp_path, prefs=prefs_dir)
    app = make_app(tmp_path, vault=vault)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            app.service.set_user_preferences(screen.chat_id, "formal.md")

            await open_context_modal(pilot)
            await select_row(pilot, 1)
            await pilot.click("#context-action-change")
            await pilot.pause()
            options = list(app.screen.query("#source-picker-list ListItem"))
            await pilot.click(options[0])  # "None (clear selection)"
            await pilot.pause()

            rows = context_modal_row_texts(app)
            assert rows[1] == "User Preferences: none selected"
            assert app.service.get_chat(screen.chat_id).context_selection.user_preferences is None
    finally:
        await app.shutdown()


async def test_add_and_remove_trait_updates_the_row_list_and_selection_order(tmp_path):
    traits_dir = tmp_path / "traits"
    write_source(traits_dir, "dry.md", "dry")
    write_source(traits_dir, "warm.md", "warm")
    vault = real_vault(tmp_path, traits=traits_dir)
    app = make_app(tmp_path, vault=vault)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await open_context_modal(pilot)

            await select_row(pilot, 3)  # Add trait row, before any trait exists
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, tui.SourcePickerModal)
            first_options = list(app.screen.query("#source-picker-list ListItem"))
            assert len(first_options) == 2  # no "None" option for Add
            await pilot.click(first_options[0])
            await pilot.pause()

            rows = context_modal_row_texts(app)
            assert any(r.startswith("Trait: dry,") for r in rows)
            assert app.service.get_chat(screen.chat_id).context_selection.traits == ("dry.md",)

            trait_index = next(i for i, r in enumerate(rows) if r.startswith("Trait: dry,"))
            await select_row(pilot, trait_index)
            await pilot.click("#context-action-remove")
            await pilot.pause()
            assert app.service.get_chat(screen.chat_id).context_selection.traits == ()
    finally:
        await app.shutdown()


async def test_persona_selection_freezes_a_usable_first_message_and_renders_it_as_history(tmp_path):
    personas_dir = tmp_path / "personas"
    first_messages_dir = tmp_path / "first_messages"
    write_source(personas_dir, "muse.md", "You are Muse.")
    write_source(first_messages_dir, "muse.md", "Hello, I am Muse.")
    vault = real_vault(tmp_path, personas=personas_dir, first_messages=first_messages_dir)
    app = make_app(tmp_path, vault=vault)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await open_context_modal(pilot)
            await select_row(pilot, 2)  # Persona
            await pilot.click("#context-action-change")
            await pilot.pause()
            options = list(app.screen.query("#source-picker-list ListItem"))
            await pilot.click(options[-1])  # the real "muse" persona
            await pilot.pause()

            rows = context_modal_row_texts(app)
            first_message_row = next(r for r in rows if r.startswith("First Message:"))
            assert "Hello, I am Muse." not in first_message_row  # row shows metadata, not the body
            assert "chars" in first_message_row

            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is screen
            lines = transcript_lines(screen)
            assert "cfc: Hello, I am Muse." in lines

            chat = app.service.get_chat(screen.chat_id)
            assert chat.opening is not None
            assert chat.opening.content == "Hello, I am Muse."
    finally:
        await app.shutdown()


async def test_persona_selection_with_no_companion_leaves_first_message_absent(tmp_path):
    """A configured First Messages directory that simply holds no companion
    for this persona — `none for this persona`. The unconfigured-directory
    case is a different row and a different route (B-2.0-62), proved in
    `test_an_unconfigured_first_messages_directory_says_so_instead_of_none`.
    """
    personas_dir = tmp_path / "personas"
    first_messages_dir = tmp_path / "first_messages"
    write_source(personas_dir, "muse.md", "You are Muse.")
    first_messages_dir.mkdir()
    vault = real_vault(tmp_path, personas=personas_dir, first_messages=first_messages_dir)
    app = make_app(tmp_path, vault=vault)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            app.service.set_persona(screen.chat_id, "muse.md")
            assert app.service.get_chat(screen.chat_id).opening is None

            await open_context_modal(pilot)
            rows = context_modal_row_texts(app)
            first_message_row = next(r for r in rows if r.startswith("First Message:"))
            assert first_message_row == "First Message: none for this persona"
    finally:
        await app.shutdown()


async def test_a_bad_selected_source_blocks_send_and_keeps_the_draft(tmp_path):
    personas_dir = tmp_path / "personas"
    personas_dir.mkdir()  # "ghost.md" does not exist inside it
    vault = real_vault(tmp_path, personas=personas_dir)
    responder = FixedResponder(Completion(content="must not be sent"))
    app = make_app(tmp_path, responder=responder, vault=vault)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            app.service.set_persona(screen.chat_id, "ghost.md")

            await type_text(pilot, "hello there")
            await pilot.press("enter")
            await pilot.pause()

            composer = screen.query_one(tui.Composer)
            assert composer.text == "hello there"  # draft kept intact
            assert responder.calls == []
            status = str(screen.query_one("#chat-status", tui.Static).content)
            assert "persona" in status
            assert "ghost.md" in status
            assert "Context" in status
            assert app.service.snapshot(screen.chat_id).turns == ()
    finally:
        await app.shutdown()


async def test_context_modal_renders_hostile_names_and_bodies_as_literal_text(tmp_path):
    personas_dir = tmp_path / "personas"
    hostile_name = "[bold red]evil.md"  # no literal "/" — that is not a legal POSIX filename
    write_source(personas_dir, hostile_name, "[red]not a colour[/red]")
    vault = real_vault(tmp_path, personas=personas_dir)
    app = make_app(tmp_path, vault=vault)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            app.service.set_persona(screen.chat_id, hostile_name)

            await open_context_modal(pilot)
            rows = context_modal_row_texts(app)
            persona_row = next(r for r in rows if r.startswith("Persona:"))
            assert "[bold red]evil" in persona_row  # the display name, literal text

            await select_row(pilot, 2)
            await pilot.press("enter")
            await pilot.pause()
            body = app.screen.query_one("#source-preview-body", tui.Static)
            assert str(body.content) == "[red]not a colour[/red]"
    finally:
        await app.shutdown()


async def test_composer_regains_focus_after_closing_context_modal(tmp_path):
    app = make_app(tmp_path)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await open_context_modal(pilot)
            await pilot.press("escape")
            await pilot.pause()
            assert screen.query_one(tui.Composer).has_focus
    finally:
        await app.shutdown()


async def test_the_outbound_plan_matches_the_context_modal_preview_exactly(tmp_path):
    personas_dir = tmp_path / "personas"
    write_source(personas_dir, "muse.md", "You are Muse.")
    vault = real_vault(tmp_path, personas=personas_dir)
    responder = FixedResponder(Completion(content="ok"))
    app = make_app(tmp_path, responder=responder, vault=vault)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            app.service.set_persona(screen.chat_id, "muse.md")
            preview = app.service.preview_context(screen.chat_id)

            await type_text(pilot, "hi")
            await pilot.press("enter")
            await pilot.pause()

            plan = responder.calls[0]
            preview_bodies = [s.body for s in preview.ordered_sources()]
            plan_prefix = [m.content for m in plan.messages[:len(preview_bodies)]]
            assert plan_prefix == preview_bodies
    finally:
        await app.shutdown()


# === Model modal: chat state, the required default always usable ===========

def catalogue(*entries: settings.ModelCatalogueEntry) -> settings.ModelCatalogue:
    return settings.ModelCatalogue(entries=entries)


def model_modal_labels(app) -> list[str]:
    modal = app.screen
    assert isinstance(modal, tui.ModelModal)
    return [str(s.content) for s in modal.query("#model-modal-list Static")]


async def test_model_modal_marks_the_current_model_and_offers_the_default(tmp_path):
    models = catalogue(
        settings.ModelCatalogueEntry(id="fixture-model", selectable=True),
        settings.ModelCatalogueEntry(id="other-model", selectable=True),
    )
    app = make_app(tmp_path, models=models)
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            await run_command(pilot, "Model")
            assert isinstance(app.screen, tui.ModelModal)
            labels = model_modal_labels(app)
            assert "fixture-model (current)" in labels
            assert "other-model" in labels
    finally:
        await app.shutdown()


async def test_selecting_a_model_via_keyboard_persists_and_updates_the_context_bar(tmp_path):
    models = catalogue(settings.ModelCatalogueEntry(id="other-model", selectable=True))
    app = make_app(tmp_path, models=models)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await run_command(pilot, "Model")
            list_view = app.screen.query_one("#model-modal-list", tui.ListView)
            list_view.index = 1  # "fixture-model (current)" is offered first as the default
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            assert app.screen is screen
            assert app.service.get_chat(screen.chat_id).context_selection.model == "other-model"
            bar = str(screen.query_one("#chat-context-bar", tui.Static).content)
            assert "model: other-model" in bar
    finally:
        await app.shutdown()


async def test_selecting_a_model_via_mouse_does_the_same_as_keyboard(tmp_path):
    models = catalogue(settings.ModelCatalogueEntry(id="other-model", selectable=True))
    app = make_app(tmp_path, models=models)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await run_command(pilot, "Model")
            items = list(app.screen.query("#model-modal-list ListItem"))
            other_item = next(i for i in items if "other-model" in str(i.query_one(tui.Static).content))
            await pilot.click(other_item)
            await pilot.pause()
            assert app.service.get_chat(screen.chat_id).context_selection.model == "other-model"
    finally:
        await app.shutdown()


async def test_esc_cancels_the_model_modal_without_changing_the_selection(tmp_path):
    models = catalogue(settings.ModelCatalogueEntry(id="other-model", selectable=True))
    app = make_app(tmp_path, models=models)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await run_command(pilot, "Model")
            assert isinstance(app.screen, tui.ModelModal)
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is screen
            assert app.service.get_chat(screen.chat_id).context_selection.model == "fixture-model"
    finally:
        await app.shutdown()


async def test_model_modal_labels_an_out_of_catalogue_current_model(tmp_path):
    models = catalogue(settings.ModelCatalogueEntry(id="other-model", selectable=True))
    app = make_app(tmp_path, models=models)
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            await run_command(pilot, "Model")
            labels = model_modal_labels(app)
            assert "fixture-model (current) (not in the current catalogue)" in labels
    finally:
        await app.shutdown()


async def test_model_modal_renders_a_literal_hostile_provider_id(tmp_path):
    hostile_id = "[bold red]evil-model"
    models = catalogue(settings.ModelCatalogueEntry(id=hostile_id, selectable=True))
    app = make_app(tmp_path, models=models)
    try:
        async with app.run_test() as pilot:
            await open_new_chat(app, pilot)
            await run_command(pilot, "Model")
            labels = model_modal_labels(app)
            assert any(hostile_id in label for label in labels)
    finally:
        await app.shutdown()


async def test_changing_the_model_does_not_relabel_past_turns(tmp_path):
    models = catalogue(settings.ModelCatalogueEntry(id="other-model", selectable=True))
    responder = FixedResponder(Completion(content="ok"))
    app = make_app(tmp_path, responder=responder, models=models)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "hi")
            await pilot.press("enter")
            await pilot.pause()

            await run_command(pilot, "Model")
            list_view = app.screen.query_one("#model-modal-list", tui.ListView)
            list_view.index = 1
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

            turn = app.service.snapshot(screen.chat_id).turns[0]
            assert turn.model == "fixture-model"  # the model it actually used, unchanged
            assert app.service.get_chat(screen.chat_id).context_selection.model == "other-model"
            lines = transcript_lines(screen)
            assert any(line == "model: fixture-model" for line in lines)
    finally:
        await app.shutdown()


# === completed-turn evidence: model, usage, limit, context provenance ======

async def test_turn_evidence_shows_not_reported_for_absent_usage_and_explicit_zero(tmp_path):
    responder = FixedResponder(Completion(
        content="ok", usage=Usage(input_tokens=0, output_tokens=None, total_tokens=5),
    ))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "hi")
            await pilot.press("enter")
            await pilot.pause()

            lines = transcript_lines(screen)
            assert "usage — input: 0, output: not reported, total: 5" in lines
    finally:
        await app.shutdown()


async def test_turn_evidence_shows_all_not_reported_when_usage_is_entirely_absent(tmp_path):
    responder = FixedResponder(Completion(content="ok", usage=None))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "hi")
            await pilot.press("enter")
            await pilot.pause()

            lines = transcript_lines(screen)
            assert "usage — input: not reported, output: not reported, total: not reported" in lines
    finally:
        await app.shutdown()


async def test_turn_evidence_shows_a_limit_comparison_when_the_catalogue_has_one(tmp_path):
    models = catalogue(settings.ModelCatalogueEntry(
        id="fixture-model", selectable=True, context_limit=128000,
    ))
    responder = FixedResponder(Completion(content="ok", usage=Usage(input_tokens=42)))
    app = make_app(tmp_path, responder=responder, models=models)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "hi")
            await pilot.press("enter")
            await pilot.pause()

            lines = transcript_lines(screen)
            assert "reported input 42 of configured limit 128000" in lines
    finally:
        await app.shutdown()


async def test_turn_evidence_has_no_limit_line_without_a_configured_limit(tmp_path):
    responder = FixedResponder(Completion(content="ok", usage=Usage(input_tokens=42)))
    app = make_app(tmp_path, responder=responder)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            await type_text(pilot, "hi")
            await pilot.press("enter")
            await pilot.pause()

            lines = transcript_lines(screen)
            assert not any(line.startswith("reported input") for line in lines)
    finally:
        await app.shutdown()


async def test_turn_evidence_context_provenance_lists_categories_in_order(tmp_path):
    personas_dir = tmp_path / "personas"
    write_source(personas_dir, "muse.md", "You are Muse.")
    vault = real_vault(tmp_path, personas=personas_dir)
    responder = FixedResponder(Completion(content="ok"))
    app = make_app(tmp_path, responder=responder, vault=vault)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            app.service.set_persona(screen.chat_id, "muse.md")
            await type_text(pilot, "hi")
            await pilot.press("enter")
            await pilot.pause()

            lines = transcript_lines(screen)
            provenance = next(line for line in lines if line.startswith("context:"))
            assert provenance == "context: system_instructions:cfc-system-instructions-v1, persona:muse.md"
    finally:
        await app.shutdown()


async def test_turn_evidence_flags_a_context_source_that_changed_since_the_turn(tmp_path):
    personas_dir = tmp_path / "personas"
    write_source(personas_dir, "muse.md", "version one")
    vault = real_vault(tmp_path, personas=personas_dir)
    responder = FixedResponder(Completion(content="ok"))
    app = make_app(tmp_path, responder=responder, vault=vault)
    try:
        async with app.run_test() as pilot:
            screen = await open_new_chat(app, pilot)
            app.service.set_persona(screen.chat_id, "muse.md")
            await type_text(pilot, "hi")
            await pilot.press("enter")
            await pilot.pause()

            unchanged_provenance = next(
                line for line in transcript_lines(screen) if line.startswith("context:")
            )
            assert "*" not in unchanged_provenance

            write_source(personas_dir, "muse.md", "version two")
            await app.pop_screen()
            await pilot.pause()
            app.open_chat(screen.chat_id)
            await pilot.pause()

            changed_provenance = next(
                line for line in transcript_lines(app.screen) if line.startswith("context:")
            )
            assert "persona:muse.md*" in changed_provenance
            assert "live source has changed" in changed_provenance
    finally:
        await app.shutdown()
