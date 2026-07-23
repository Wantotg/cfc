#!/usr/bin/env python3
"""
test_agent.py — the agent loop and tool-row replay. No API calls: call_api is
replaced with a scripted fake, so the loop's behaviour is provable for free.

    python3 tests/test_agent.py

The two properties worth the most here:
  - every message in the loop is persisted, so replay and export don't break
  - an interrupted turn doesn't leave a session that can never be reopened
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
import tools
from context import ToolContext

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:220]}")


def reply(content=None, calls=None):
    msg = {"role": "assistant", "content": content}
    if calls:
        msg["tool_calls"] = [
            {"id": f"call_{i}", "type": "function",
             "function": {"name": n, "arguments": json.dumps(a)}}
            for i, (n, a) in enumerate(calls)]
    return {"choices": [{"message": msg}]}


class FakeAPI:
    """Scripted responses, and a record of what it was asked."""

    def __init__(self, script):
        self.script = list(script)
        self.seen = []

    def __call__(self, messages, model=None, tools=None):
        self.seen.append({"messages": [dict(m) for m in messages],
                          "tools": tools})
        return self.script.pop(0) if self.script else reply("fallback")


def drive(fn, *a, keys="", **kw):
    out = io.StringIO()
    real = sys.stdin
    sys.stdin = io.StringIO(keys)
    try:
        with contextlib.redirect_stdout(out):
            agent.console.file = out
            commands.console.file = out
            r = fn(*a, **kw)
    finally:
        sys.stdin = real
    return r, out.getvalue()


def main():
    tmp = Path(tempfile.mkdtemp())
    jail = tmp / "projects"
    jail.mkdir(parents=True)
    (jail / "notes.md").write_text("alpha\nbeta\ngamma\n")
    tools.TOOLS_ROOTS = (jail,)
    # agent builds its context from config; point it at the temp jail instead.
    agent.chat_context = lambda: ToolContext.for_chat(read_roots=(jail,))

    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()
    conn.execute("INSERT INTO sessions (id,title) VALUES (1,'t')")
    conn.commit()

    real_call = agent.call_api

    print("--- a turn with no tool calls is just a turn ---")
    agent.call_api = FakeAPI([reply("Just answering.")])
    hist = [{"role": "user", "content": "hi"}]
    final, out = drive(agent.agent_turn, [], hist, "m", conn, 1)
    ok("returns the assistant message", final["content"] == "Just answering.")
    ok("appended to history", hist[-1]["content"] == "Just answering.")
    ok("persisted as kind=chat",
       conn.execute("SELECT kind FROM messages WHERE content='Just answering.'"
                    ).fetchone()[0] == "chat")

    print("\n--- tools are offered to the model ---")
    fake = FakeAPI([reply("done")])
    agent.call_api = fake
    drive(agent.agent_turn, [], [{"role": "user", "content": "x"}], "m", conn, 1)
    names = {t["function"]["name"] for t in fake.seen[0]["tools"]}
    ok("schemas passed to call_api",
       names == {"list_dir", "read_file", "grep", "write_file"},
       names)

    print("\n--- call -> approve -> result -> answer ---")
    conn.execute("DELETE FROM messages")
    conn.commit()
    agent.call_api = FakeAPI([
        reply(None, [("read_file", {"path": str(jail / "notes.md")})]),
        reply("The file says alpha, beta, gamma."),
    ])
    hist = [{"role": "user", "content": "read notes.md"}]
    final, out = drive(agent.agent_turn, [], hist, "m", conn, 1, keys="a\n")
    ok("final answer returned",
       "alpha, beta, gamma" in final["content"], final)
    ok("the chain is visible: the call", "read_file" in out, out)
    ok("the chain is visible: the result", "←" in out, out)

    roles = [m["role"] for m in hist]
    ok("history holds user, assistant(call), tool, assistant(answer)",
       roles == ["user", "assistant", "tool", "assistant"], roles)
    ok("the tool message carries tool_call_id",
       hist[2].get("tool_call_id") == "call_0", hist[2])
    ok("the assistant call carries tool_calls", "tool_calls" in hist[1])
    ok("the tool result contains the file", "alpha" in hist[2]["content"])

    kinds = [r[0] for r in conn.execute(
        "SELECT kind FROM messages ORDER BY id")]
    ok("every message persisted with its kind",
       kinds == ["tool_call", "tool_result", "chat"], kinds)

    print("\n--- the model sees the tool result on the next call ---")
    fake = FakeAPI([reply(None, [("read_file", {"path": str(jail / "notes.md")})]),
                    reply("ok")])
    agent.call_api = fake
    drive(agent.agent_turn, [{"role": "system", "content": "SYS"}],
          [{"role": "user", "content": "go"}], "m", conn, 1, keys="a\n")
    second = fake.seen[1]["messages"]
    ok("second call includes the tool result",
       any(m.get("role") == "tool" for m in second), [m["role"] for m in second])
    ok("system prefix present on every call",
       second[0].get("content") == "SYS", second[0])

    print("\n--- denial reaches the model as data ---")
    fake = FakeAPI([reply(None, [("read_file", {"path": str(jail / "notes.md")})]),
                    reply("Understood, I won't read it.")])
    agent.call_api = fake
    hist = [{"role": "user", "content": "go"}]
    final, out = drive(agent.agent_turn, [], hist, "m", conn, 1, keys="d\n")
    tool_msg = [m for m in hist if m["role"] == "tool"][0]
    ok("denied call yields an error result",
       "user denied" in tool_msg["content"], tool_msg)
    ok("the loop continues after a denial",
       final["content"] == "Understood, I won't read it.", final)
    ok("...and the file was never read", "alpha" not in tool_msg["content"])

    print("\n--- several calls in one message ---")
    agent.call_api = FakeAPI([
        reply(None, [("list_dir", {"path": str(jail)}),
                     ("read_file", {"path": str(jail / "notes.md")})]),
        reply("both done"),
    ])
    hist = [{"role": "user", "content": "go"}]
    final, out = drive(agent.agent_turn, [], hist, "m", conn, 1, keys="a\na\n")
    tool_msgs = [m for m in hist if m["role"] == "tool"]
    ok("one result per call", len(tool_msgs) == 2, len(tool_msgs))
    ok("ids line up", {m["tool_call_id"] for m in tool_msgs} == {"call_0", "call_1"})

    print("\n--- the touched collector ---")
    # The run log's fourth field. Only the runner reads it, so chat passes
    # nothing and this is the only place that exercises it.
    box = tmp / "outbox"
    box.mkdir()
    W = ToolContext.for_chat(read_roots=(jail,), write_roots=(box,))

    agent.call_api = FakeAPI([
        reply(None, [("write_file", {"path": str(box / "a.md"),
                                     "content": "one\n"}),
                     ("read_file", {"path": str(jail / "notes.md")})]),
        reply("wrote it"),
    ])
    touched = []
    drive(agent.agent_turn, [], [{"role": "user", "content": "go"}], "m",
          conn, 1, keys="a\na\n", ctx=W, touched=touched)
    ok("a successful write is collected", touched == [box / "a.md"], touched)
    ok("...and a read is not", len(touched) == 1, touched)

    # The negative that matters: a refused write must not be reported as one
    # that happened. A log naming a file the run never produced sends you
    # looking for it.
    agent.call_api = FakeAPI([
        reply(None, [("write_file", {"path": str(jail / "nope.md"),
                                     "content": "x"})]),
        reply("refused"),
    ])
    touched = []
    drive(agent.agent_turn, [], [{"role": "user", "content": "go"}], "m",
          conn, 1, keys="a\n", ctx=W, touched=touched)
    ok("a refused write is not collected", touched == [], touched)
    ok("...and really wasn't written", not (jail / "nope.md").exists())

    # Same file twice is one entry: the log answers "which files", not "how
    # many calls" — the transcript already answers that.
    agent.call_api = FakeAPI([
        reply(None, [("write_file", {"path": str(box / "b.md"),
                                     "content": "1"})]),
        reply(None, [("write_file", {"path": str(box / "b.md"),
                                     "content": "2", "overwrite": True})]),
        reply("done"),
    ])
    touched = []
    drive(agent.agent_turn, [], [{"role": "user", "content": "go"}], "m",
          conn, 1, keys="a\na\n", ctx=W, touched=touched)
    ok("the same file written twice is listed once",
       touched == [box / "b.md"], touched)

    # The case the backlog entry is actually about: the run stops halfway, so
    # the return value is the ceiling message and the only record of what got
    # written is this list.
    agent.TOOLS_MAX_CALLS_PER_TURN = 2
    agent.call_api = FakeAPI([
        reply(None, [("write_file", {"path": str(box / f"c{i}.md"),
                                     "content": "x"})]) for i in range(5)])
    touched = []
    final, out = drive(agent.agent_turn, [], [{"role": "user", "content": "go"}],
                       "m", conn, 1, keys="a\na\n", ctx=W, touched=touched)
    ok("writes survive the call-ceiling exit",
       final["content"] == agent.LIMIT_MESSAGE and
       touched == [box / "c0.md", box / "c1.md"], (final, touched))
    agent.TOOLS_MAX_CALLS_PER_TURN = 8

    print("\n--- the loop breaker ---")
    agent.TOOLS_MAX_CALLS_PER_TURN = 3
    agent.call_api = FakeAPI([reply(None, [("list_dir", {"path": str(jail)})])
                             for _ in range(10)])
    hist = [{"role": "user", "content": "loop forever"}]
    final, out = drive(agent.agent_turn, [], hist, "m", conn, 1, keys="A\n")
    ok("stops at the limit", final["content"] == agent.LIMIT_MESSAGE, final)
    ok("the limit is a real assistant message, not silence",
       hist[-1]["content"] == agent.LIMIT_MESSAGE)
    ok("it made exactly the allowed number of calls",
       sum(1 for m in hist if m["role"] == "tool") == 3,
       [m["role"] for m in hist])
    agent.TOOLS_MAX_CALLS_PER_TURN = 8

    print("\n--- replay: tool rows rebuild with their fields ---")
    conn.execute("DELETE FROM messages")
    conn.commit()
    agent.call_api = FakeAPI([
        reply(None, [("read_file", {"path": str(jail / "notes.md")})]),
        reply("answer"),
    ])
    drive(agent.agent_turn, [], [{"role": "user", "content": "go"}],
          "m", conn, 1, keys="a\n")
    conn.close()
    conn = dbmod.db()
    replayed = dbmod.load_history(conn, 1)
    ok("tool_calls survive the round trip",
       replayed[0].get("tool_calls") and
       replayed[0]["tool_calls"][0]["function"]["name"] == "read_file",
       replayed[0])
    ok("tool_call_id survives", replayed[1].get("tool_call_id") == "call_0",
       replayed[1])
    ok("order preserved: result immediately after its call",
       [m["role"] for m in replayed] == ["assistant", "tool", "assistant"],
       [m["role"] for m in replayed])

    print("\n--- an interrupted turn must not poison the session ---")
    # A call saved with no result — Ctrl-C between dispatch and save. The API
    # rejects that shape, so a session containing it could never be reopened.
    conn.execute("DELETE FROM messages")
    dbmod.save_message(conn, 1, "user", "go", kind="chat")
    dbmod.save_message(conn, 1, "assistant", "", kind="tool_call",
                       meta={"tool_calls": [
                           {"id": "orphan", "type": "function",
                            "function": {"name": "read_file",
                                         "arguments": "{}"}}]})
    conn.commit()
    replayed = dbmod.load_history(conn, 1)
    ok("orphaned tool_call dropped from replay",
       not any(m.get("tool_calls") for m in replayed), replayed)
    ok("the rest of the history survives",
       [m["role"] for m in replayed] == ["user"], replayed)

    # prose alongside an orphaned call is kept, minus the call
    conn.execute("DELETE FROM messages")
    dbmod.save_message(conn, 1, "assistant", "Let me look.", kind="tool_call",
                       meta={"tool_calls": [
                           {"id": "orphan2", "type": "function",
                            "function": {"name": "grep", "arguments": "{}"}}]})
    conn.commit()
    replayed = dbmod.load_history(conn, 1)
    ok("prose kept when its call is orphaned",
       len(replayed) == 1 and replayed[0]["content"] == "Let me look."
       and "tool_calls" not in replayed[0], replayed)

    # partially answered: keep the answered call, drop the orphan
    conn.execute("DELETE FROM messages")
    dbmod.save_message(conn, 1, "assistant", "", kind="tool_call",
                       meta={"tool_calls": [
                           {"id": "a1", "type": "function",
                            "function": {"name": "grep", "arguments": "{}"}},
                           {"id": "a2", "type": "function",
                            "function": {"name": "grep", "arguments": "{}"}}]})
    dbmod.save_message(conn, 1, "tool", "result", kind="tool_result",
                       meta={"tool": "grep", "tool_call_id": "a1"})
    conn.commit()
    replayed = dbmod.load_history(conn, 1)
    calls = replayed[0].get("tool_calls") or []
    ok("answered call kept, orphan dropped",
       len(calls) == 1 and calls[0]["id"] == "a1", calls)

    agent.call_api = real_call
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
