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

from cfc import conversation_store, tui
from cfc.conversation_service import open_service
from cfc.conversation_types import (
    Cancellation,
    Completion,
    Failure,
    FailureEvidence,
    FailureKind,
)


# --- deterministic responders (the async twins of the service test's own) --

class FixedResponder:
    def __init__(self, result):
        self._result = result
        self.calls = []

    async def respond(self, snapshot, model):
        self.calls.append((snapshot, model))
        return self._result


class SlowResponder:
    """Never returns on its own; `started` fires once `respond` is under
    way, so a test can drive a cancellation deterministically."""

    def __init__(self):
        self.started = asyncio.Event()
        self.released = asyncio.Event()
        self.result = Completion(content="released")

    async def respond(self, snapshot, model):
        self.started.set()
        await self.released.wait()
        return self.result


class RaisingResponder:
    def __init__(self, exc: Exception):
        self._exc = exc

    async def respond(self, snapshot, model):
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

    async def respond(self, snapshot, model):
        index = len(self.calls)
        self.calls.append((snapshot, model))
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


def open_test_service(tmp_path: Path):
    return open_service(tmp_path / "direct" / "chat.db")


def make_app(tmp_path: Path, responder=None, model: str = "fixture-model") -> tui.CfcApp:
    service = open_test_service(tmp_path)
    if responder is None:
        responder = FixedResponder(Completion(content="the answer"))
    return tui.CfcApp(service, responder, model)


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
        chat = app.service.create_chat("existing")
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
        chat = app.service.create_chat("existing")
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


# === quit: cancels and awaits workers, then closes adapter and service ======

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
