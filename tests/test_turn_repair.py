#!/usr/bin/env python3
"""
test_turn_repair.py — /swipe and /undo: the latest-turn repair boundary.

    python3 tests/test_turn_repair.py

Concept.md's "One latest ordinary turn": both commands classify the latest
durable `kind='chat', role='user'` row and everything it caused, refuse the
two states neither may touch (nothing sent, ambiguous), refuse a turn that
requested a mutating tool, and otherwise prune atomically with the index.
`/swipe` keeps the user row and re-enters the ordinary turn path under the
session's *current* state — including v1.5's active sampling preset, which is
why this file also carries the preset request-capture proof (Concept.md's
"Named Parameter presets", `api.py`/`agent.py` §5): a swipe is the one place a
preset selected after the original send still has to reach the request.

Only the provider is stubbed — `main.stream_response` for the streaming path,
`agent.call_api` for the tool path, so the real `agent_turn` and `main.py`
command handlers run exactly as they do in a session. No API key, no network.
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import agent
import commands
import db as dbmod
import errorlog
import httpx
from context import chat_context as _real_chat_context, ToolContext
import main
import models

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


MODEL = "stub-model"


def drive(conn, sid, keys):
    """Run one session to completion, returning stdout. Same shape as
    test_turn_paths.py's helper — the real `run_session`, a scripted stdin,
    console output captured across every module it prints through."""
    out = io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(keys)
    saved_main_file = main.console.file
    saved_commands_file = commands.console.file
    saved_agent_file = agent.console.file
    try:
        with contextlib.redirect_stdout(out):
            main.console.file = out
            commands.console.file = out
            agent.console.file = out
            main.run_session(conn, sid, auto_export=False, private=False)
    finally:
        sys.stdin = real_stdin
        main.console.file = saved_main_file
        commands.console.file = saved_commands_file
        agent.console.file = saved_agent_file
    return out.getvalue()


def drive_private(conn, sid, keys):
    out = io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(keys)
    saved_main_file = main.console.file
    saved_commands_file = commands.console.file
    saved_agent_file = agent.console.file
    try:
        with contextlib.redirect_stdout(out):
            main.console.file = out
            commands.console.file = out
            agent.console.file = out
            main.run_session(conn, sid, auto_export=False, private=True)
    finally:
        sys.stdin = real_stdin
        main.console.file = saved_main_file
        commands.console.file = saved_commands_file
        agent.console.file = saved_agent_file
    return out.getvalue()


def reply(content=None, calls=None, usage=None):
    """One tool-path response, agent.call_api's shape."""
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [
            {"id": f"call_{i}", "type": "function",
             "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(calls)]
    out = {"choices": [{"message": msg}]}
    if usage:
        out["usage"] = usage
    return out


class ScriptedCallAPI:
    """agent.call_api's shape, popping one scripted response (or raising)
    per call, and recording every (messages, model, tools, params) it saw."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def __call__(self, messages, model=None, tools=None, params=None):
        self.seen.append({"messages": [dict(m) for m in messages],
                          "model": model, "tools": tools, "params": params})
        item = self.script.pop(0) if self.script else reply("fallback")
        if isinstance(item, Exception):
            raise item
        return item


class ScriptedStream:
    """main.stream_response's shape, same discipline."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def __call__(self, messages, model=None, params=None):
        self.seen.append({"messages": [dict(m) for m in messages],
                          "model": model, "params": params})
        item = self.script.pop(0) if self.script else ("fallback", {}, "")
        if isinstance(item, Exception):
            raise item
        return item


def user_rows(conn, sid):
    return conn.execute(
        "SELECT id, content FROM messages WHERE session_id=? AND "
        "kind='chat' AND role='user' ORDER BY id", (sid,)).fetchall()


def all_rows(conn, sid):
    return conn.execute(
        "SELECT role, kind, content FROM messages WHERE session_id=? "
        "ORDER BY id", (sid,)).fetchall()


def main_():
    tmp = Path(tempfile.mkdtemp())
    assert "tmp" in str(tmp), "refusing to touch a real db"
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()
    errorlog.LOG_PATH = tmp / "errors.log"
    assert "tmp" in str(errorlog.LOG_PATH), "refusing to touch the real log"

    main.TOOLS_ENABLED = True
    models.MODELS = [models._spec(MODEL, tools=True, limit=128_000,
                                  preset_params=("temperature", "top_p"))]
    models.PARAMETER_PRESETS = {"warm": {"temperature": 0.9}}
    main.set_process_model(MODEL)
    main.generate_title = lambda *a, **k: "(untitled)"
    main.auto_embed = lambda: None
    main.safe_export = lambda *a, **k: None

    USAGE = {"prompt_tokens": 10, "completion_tokens": 5}

    print("\n--- nothing sent: /swipe and /undo both refuse, no API call ---")
    sid = dbmod.new_session(conn, title="empty", model=MODEL)
    stream = ScriptedStream([])
    main.stream_response = stream
    out = drive(conn, sid, "/tools off\n/swipe\n/undo\n/q\n")
    ok("swipe refuses", "Nothing to swipe" in out, out)
    ok("undo refuses", "Nothing to undo" in out, out)
    ok("neither made a request", stream.seen == [], stream.seen)
    ok("nothing was written", all_rows(conn, sid) == [])

    print("\n--- ambiguous: a later /continue blocks both commands ---")
    sid = dbmod.new_session(conn, title="ambiguous", model=MODEL)
    stream = ScriptedStream([("first answer", dict(USAGE), ""),
                             ("continued", dict(USAGE), "")])
    main.stream_response = stream
    out = drive(conn, sid, "/tools off\nhello\n/continue\n/swipe\n/undo\n/q\n")
    flat = " ".join(out.split())   # Rich wraps long lines; compare unwrapped
    ok("swipe refuses on ambiguity",
       "Can't swipe" in flat and "already built on this send" in flat, out)
    ok("undo refuses on ambiguity", "Can't undo" in flat, out)
    before = all_rows(conn, sid)
    ok("two assistant rows exist (the ambiguity itself)",
       sum(1 for r in before if r[0] == "assistant") == 2, before)

    print("\n--- completed turn, streaming path: swipe regenerates, keeps "
          "the user row, advances no cadence, skips the title ---")
    sid = dbmod.new_session(conn, title="swipe-stream", model=MODEL)
    stream = ScriptedStream([("first answer", dict(USAGE), ""),
                             ("second answer", dict(USAGE), "")])
    main.stream_response = stream
    title_calls = []
    main.generate_title = lambda text: (title_calls.append(text) or "T")
    turns_before = None

    # The streaming path renders its answer live, inside api.stream_response
    # delta by delta (HANDOVER's Testing note) — a stub returns the text
    # without ever printing it, so success here is read off the database,
    # never off `out`. `test_turn_paths.py` makes the same call.
    out = drive(conn, sid, "/tools off\nhello\n/swipe\n/q\n")
    rows = all_rows(conn, sid)
    ok("exactly one user row, unchanged content",
       [r for r in rows if r[0] == "user"] == [("user", "chat", "hello")], rows)
    ok("exactly one assistant row, the new answer",
       [r for r in rows if r[0] == "assistant"] ==
       [("assistant", "chat", "second answer")], rows)
    ok("the governor's user-turn count is unchanged (still 1)",
       dbmod.count_chat_user_turns(conn, sid) == 1)
    ok("title generation ran once (the original turn), never for the swipe",
       title_calls == ["hello"], title_calls)
    print("\n--- swipe uses CURRENT state, not the original request "
          "(preset selected between the send and the swipe) ---")
    sid = dbmod.new_session(conn, title="swipe-preset", model=MODEL)
    stream = ScriptedStream([("plain answer", dict(USAGE), ""),
                             ("warm answer", dict(USAGE), "")])
    main.stream_response = stream
    out = drive(conn, sid,
               "/tools off\nhello\n/preset warm\n/swipe\n/q\n")
    ok("the ORIGINAL request carried no preset params",
       stream.seen[0]["params"] is None, stream.seen[0])
    ok("the SWIPE request carried the preset selected afterward",
       stream.seen[1]["params"] == {"temperature": 0.9}, stream.seen[1])

    print("\n--- an active preset reaches EVERY call inside one multi-round "
          "tool loop, not just the first ---")
    sid = dbmod.new_session(conn, title="preset-tool-loop", model=MODEL)
    jail2 = tmp / "projects2"
    jail2.mkdir(exist_ok=True)
    (jail2 / "a.md").write_text("a\n")
    main.chat_context = lambda private=False: ToolContext.for_chat(
        read_roots=(jail2,))
    call_api = ScriptedCallAPI([
        reply(None, calls=[("read_file",
                            {"path": str(jail2 / "a.md")})], usage=USAGE),
        reply(None, calls=[("read_file",
                            {"path": str(jail2 / "a.md")})], usage=USAGE),
        reply("done reading", usage=USAGE),
    ])
    agent.call_api = call_api
    drive(conn, sid, "/preset warm\nplease read twice\na\na\n/q\n")
    ok("every one of the three calls in the loop carried the preset",
       len(call_api.seen) == 3
       and all(c["params"] == {"temperature": 0.9} for c in call_api.seen),
       [c["params"] for c in call_api.seen])
    main.chat_context = _real_chat_context

    print("\n--- an active preset never reaches title generation ---")
    sid = dbmod.new_session(conn, title="preset-title", model=MODEL)
    stream = ScriptedStream([("an answer", dict(USAGE), "")])
    main.stream_response = stream
    real_call_api = agent.call_api

    def title_spy(messages, model=None, tools=None, read_timeout=None,
                 **kwargs):
        title_spy.calls.append(kwargs)
        return {"choices": [{"message": {"role": "assistant",
                                         "content": "A Title"}}]}
    title_spy.calls = []
    import api as apimod
    real_api_call_api = apimod.call_api
    apimod.call_api = title_spy
    main.generate_title = apimod.generate_title
    try:
        drive(conn, sid, "/preset warm\nhello\n/q\n")
    finally:
        apimod.call_api = real_api_call_api
        agent.call_api = real_call_api
        # Restore the fast stub — leaving the *real* generate_title bound
        # would make a later block's title attempt a genuine network call.
        main.generate_title = lambda *a, **k: "(untitled)"
    ok("title generation's own call_api never received a 'params' kwarg",
       title_spy.calls and all("params" not in c for c in title_spy.calls),
       title_spy.calls)

    print("\n--- no-preset payloads are byte-for-byte the existing shape, "
          "at api.py's own wire boundary ---")
    import api as apimod

    class _FakeResponse:
        is_error = False
        status_code = 200

        def __init__(self, body):
            self._body = body

        def json(self):
            return self._body

    class _FakeClient:
        captured = []

        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            _FakeClient.captured.append(json)
            return _FakeResponse({"choices": [{"message": {
                "role": "assistant", "content": "x"}}]})

    real_httpx_client = apimod.httpx.Client
    apimod.httpx.Client = _FakeClient
    try:
        _FakeClient.captured = []
        apimod.call_api([{"role": "user", "content": "hi"}], model=MODEL)
        no_preset_payload = _FakeClient.captured[-1]
        apimod.call_api([{"role": "user", "content": "hi"}], model=MODEL,
                        params={"temperature": 0.9})
        with_preset_payload = _FakeClient.captured[-1]
    finally:
        apimod.httpx.Client = real_httpx_client

    ok("no params -> the payload has no sampling keys at all",
       "temperature" not in no_preset_payload
       and "top_p" not in no_preset_payload, no_preset_payload)
    ok("a preset -> exactly its keys are merged in, nothing else changes",
       with_preset_payload == dict(no_preset_payload, temperature=0.9),
       (no_preset_payload, with_preset_payload))

    print("\n--- undo removes both rows, makes no request ---")
    sid = dbmod.new_session(conn, title="undo-stream", model=MODEL)
    stream = ScriptedStream([("an answer", dict(USAGE), "")])
    main.stream_response = stream
    out = drive(conn, sid, "/tools off\nhello\n/undo\n/q\n")
    ok("undo says what it removed",
       "Removed the last message and its answer" in out, out)
    ok("both rows are gone", all_rows(conn, sid) == [])
    ok("undo made no request of its own",
       len(stream.seen) == 1)  # only the original "hello" turn

    print("\n--- unanswered (streaming): a provider failure leaves no "
          "answer row, and both commands still act on it ---")
    sid = dbmod.new_session(conn, title="unanswered-stream", model=MODEL)
    fails_then_answers = ScriptedStream(
        [httpx.ConnectError("provider is having a day"),
         ("recovered answer", dict(USAGE), "")])
    main.stream_response = fails_then_answers
    out = drive(conn, sid, "/tools off\nhello\n/swipe\n/q\n")
    rows_after_fail_and_swipe = all_rows(conn, sid)
    ok("the failed turn left only the user row, then swipe answered it",
       [r for r in rows_after_fail_and_swipe if r[0] == "user"] ==
       [("user", "chat", "hello")], rows_after_fail_and_swipe)
    ok("...with exactly the recovered answer",
       [r for r in rows_after_fail_and_swipe if r[0] == "assistant"] ==
       [("assistant", "chat", "recovered answer")], rows_after_fail_and_swipe)

    print("\n--- unanswered (tool path, empty-completion 400): /undo prunes "
          "the empty retry artefact too ---")
    sid = dbmod.new_session(conn, title="unanswered-tool", model=MODEL)
    call_api = ScriptedCallAPI([httpx.HTTPError("empty response from provider")])
    agent.call_api = call_api
    out = drive(conn, sid, "hello\n/undo\n/q\n")
    ok("the model hiccup was announced",
       "provider hiccup" in out or "no answer" in out, out)
    ok("the session is fully clean again", all_rows(conn, sid) == [])

    print("\n--- completed turn, tool path: swipe cleans up the old "
          "tool_call/tool_result rows, not just the final answer ---")
    sid = dbmod.new_session(conn, title="swipe-tools", model=MODEL)
    jail = tmp / "projects"
    jail.mkdir(exist_ok=True)
    (jail / "notes.md").write_text("alpha\n")
    call_api = ScriptedCallAPI([
        reply(None, calls=[("read_file",
                            {"path": str(jail / "notes.md")})], usage=USAGE),
        reply("first tool answer", usage=USAGE),
        reply("second tool answer", usage=USAGE),
    ])
    agent.call_api = call_api
    # The read tool needs somewhere real to read from, and an approval ('a')
    # for the one call the original turn makes.
    main.chat_context = lambda private=False: ToolContext.for_chat(
        read_roots=(jail,))
    out = drive(conn, sid, "hello\na\n/swipe\n/q\n")
    rows = all_rows(conn, sid)
    ok("no tool_call or tool_result rows survive from the pruned turn "
       "(the swipe made none of its own, since it answered without a call)",
       not any(k in ("tool_call", "tool_result") for _, k, _ in rows), rows)
    ok("exactly one user row and one assistant row remain",
       [r[0] for r in rows] == ["user", "assistant"], rows)

    print("\n--- write refusal: a requested (even if never approved) "
          "mutating tool call blocks both commands ---")
    # No write roots are configured for this ToolContext, so the call is
    # auto-denied at dispatch with no interactive gate prompt — proving the
    # refusal keys off the *request*, never off whether it succeeded or was
    # approved (Concept.md: "whether the old write succeeded is deliberately
    # not inferred from its result prose").
    sid = dbmod.new_session(conn, title="write-refusal", model=MODEL)
    call_api = ScriptedCallAPI([
        reply(None, calls=[("write_file", {"path": "out.md",
                                           "content": "x"})], usage=USAGE),
        reply("wrote it (or so it claims)", usage=USAGE),
    ])
    agent.call_api = call_api
    out = drive(conn, sid, "please write a file\n/swipe\n/undo\n/q\n")
    flat = " ".join(out.split())
    ok("the write call was auto-denied, no roots configured",
       "auto-denied write_file" in flat, out)
    ok("swipe refuses because a write was requested",
       "Can't swipe" in flat and "write a file" in flat, out)
    ok("undo refuses for the same reason",
       "Can't undo" in flat and "write a file" in flat, out)
    rows_before = all_rows(conn, sid)
    ok("nothing was pruned by either refusal",
       any(k == "tool_call" for _, k, _ in rows_before), rows_before)
    main.chat_context = _real_chat_context

    print("\n--- private chat: swipe/undo work entirely on the in-memory "
          "connection, never touching the real db ---")
    priv = dbmod.db(":memory:")
    psid = dbmod.new_session(priv, title="(untitled)")
    stream = ScriptedStream([("private first", {}, ""),
                             ("private second", {}, "")])
    main.stream_response = stream
    out = drive_private(priv, psid, "/tools off\nhello\n/swipe\n/undo\n/q\n")
    ok("swipe made its request through the private connection's turn path "
       "(a second request went out, even though its render is unstubbed)",
       len(stream.seen) == 2, stream.seen)
    ok("undo cleared the private connection entirely",
       all_rows(priv, psid) == [])
    real_conn = dbmod.db()
    ok("the real, durable database gained no session from any of this",
       real_conn.execute(
           "SELECT COUNT(*) FROM messages WHERE content LIKE '%private%'"
       ).fetchone()[0] == 0)
    real_conn.close()
    priv.close()

    print("\n--- W-1.6.4-05: /swipe and /undo refuse on wiki and routine, "
          "before any classification ---")
    # Neither session needs an answered turn to prove the point — the guard
    # fires before `classify_latest_turn` ever runs, so a bare user-role row
    # (a wiki page's own imported message; a routine transcript's first
    # line) is enough. What matters is that nothing about either row changes.
    wiki_sid = dbmod.new_session(conn, title="A wiki page",
                                 provider=dbmod.PROVIDER_WIKI)
    dbmod.save_message(conn, wiki_sid, "user", "the imported page content")
    routine_sid = dbmod.new_session(conn, title="routine: Nightly",
                                    provider=dbmod.PROVIDER_ROUTINE)
    dbmod.save_message(conn, routine_sid, "assistant", "the routine's own answer")

    for sid, kind in ((wiki_sid, "wiki page"), (routine_sid, "routine transcript")):
        before = all_rows(conn, sid)
        out = drive(conn, sid, "/swipe\n/undo\n/q\n")
        ok(f"{kind}: /swipe refuses, naming what it is",
           f"Can't swipe — this is a {kind}" in out, out)
        ok(f"{kind}: /undo refuses, naming what it is",
           f"Can't undo — this is a {kind}" in out, out)
        ok(f"{kind}: neither command changed a row",
           all_rows(conn, sid) == before, (before, all_rows(conn, sid)))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    conn.close()
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
