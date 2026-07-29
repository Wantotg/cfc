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

import httpx

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
    # **One string, two audiences** (`B-0.9.1-01`). The payload above must stay
    # an error, because that is what lets the model treat a refusal as a normal
    # move; the line the human reads must not, because they are the one who
    # refused. Both are asserted off the same run, since the bug was that they
    # were the same string and fixing either alone re-breaks the other.
    ok("...but the screen doesn't call your own decision an error",
       "error" not in out, out[-200:])
    ok("...it says what happened, and to which tool",
       "read_file denied at the prompt" in out, out[-200:])

    print("\n--- a real tool error still reads as one ---")
    # The inverse guard, and the direction that matters more. A genuine failure
    # styled as a polite decline reads as something you chose, so a run that
    # should have stopped keeps going and looks fine doing it. `_render_result`
    # matches `commands.DENIED`/`SKIPPED` and nothing else — no prefix test, no
    # "looks like a verdict" heuristic — and this is what holds that line.
    fake = FakeAPI([reply(None, [("read_file", {"path": "/etc/passwd"})]),
                    reply("blocked, then.")])
    agent.call_api = fake
    hist = [{"role": "user", "content": "go"}]
    final, out = drive(agent.agent_turn, [], hist, "m", conn, 1, keys="a\n")
    ok("a jail refusal is still rendered as an error", "error" in out, out[-200:])
    ok("...and is not dressed up as a human verdict",
       "at the prompt" not in out, out[-200:])

    print("\n--- both verdicts, producer to renderer, no literal between ---")
    # `gate_and_dispatch` writes the verdict and `_render_result` reads it, in
    # two modules. They share `commands.DENIED`/`SKIPPED` rather than a matched
    # pair of strings — the graph allows the import, so the pair is closed
    # instead of pinned — and this runs the real producer into the real
    # renderer so that stays true rather than merely being true today. Asserting
    # against "user denied" here would be the thing HANDOVER.md warns about: a
    # test that passes forever while the two ends drift apart.
    for key, verdict in (("d", "denied"), ("s", "skipped")):
        call = {"id": "v", "type": "function",
                "function": {"name": "read_file",
                             "arguments": json.dumps({"path": str(jail / "notes.md")})}}
        approval = commands.TurnApproval()
        result, out = drive(commands.gate_and_dispatch, call, approval,
                            ToolContext.for_chat(read_roots=(jail,)), keys=f"{key}\n")
        shown = io.StringIO()
        agent.console.file = shown
        agent._render_result(result, "read_file")
        agent.console.file = sys.stdout
        ok(f"'{key}' -> the model reads an error",
           json.loads(result).get("error"), result)
        ok(f"...and you read a decision", "error" not in shown.getvalue(),
           shown.getvalue())
        ok(f"...naming the tool and what you did",
           f"read_file {verdict} at the prompt" in shown.getvalue(),
           shown.getvalue())

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

    print("\n--- the budget counts calls, not loop iterations ---")
    # The bug: `for _ in range(max_calls)` bounded trips round the loop, so a
    # model asking for four reads in one message spent one of eight. Eight
    # iterations could be thirty calls, and the number a user tunes bounded
    # neither the work nor the size of the request.
    agent.TOOLS_MAX_CALLS_PER_TURN = 3
    agent.call_api = FakeAPI([
        reply(None, [("list_dir", {"path": str(jail)}),
                     ("list_dir", {"path": str(jail)}),
                     ("list_dir", {"path": str(jail)}),
                     ("list_dir", {"path": str(jail)})]),
        reply("should never be reached"),
    ])
    hist = [{"role": "user", "content": "read everything"}]
    final, out = drive(agent.agent_turn, [], hist, "m", conn, 1, keys="A\n")
    results = [m for m in hist if m["role"] == "tool"]
    ok("four calls in one message spend four of the budget",
       final["content"] == agent.LIMIT_MESSAGE, final)
    ok("...every one of them still gets a result", len(results) == 4,
       len(results))
    ok("...but only the budgeted three actually ran",
       sum(1 for m in results if "notes.md" in m["content"]) == 3,
       [m["content"][:40] for m in results])
    ok("the over-budget call says why it didn't run",
       "budget" in results[3]["content"], results[3]["content"])
    agent.TOOLS_MAX_CALLS_PER_TURN = 25

    print("\n--- an interrupt leaves no unanswered call in LIVE history ---")
    # The one that poisoned sessions in place. load_history repairs orphans on
    # replay, so reopening a session fixed it and it looked intermittent — but
    # the live `history` the REPL replays from was never repaired, so every
    # later message in that session 400ed.
    boom = {"n": 0}

    def explode(call, approval, ctx=None):
        boom["n"] += 1
        if boom["n"] == 2:
            raise KeyboardInterrupt          # Ctrl-C at the approval prompt
        return json.dumps({"ok": True})

    real_gate = agent.gate_and_dispatch
    agent.gate_and_dispatch = explode
    agent.call_api = FakeAPI([
        reply(None, [("list_dir", {"path": str(jail)}),
                     ("list_dir", {"path": str(jail)}),
                     ("list_dir", {"path": str(jail)})]),
    ])
    hist = [{"role": "user", "content": "go"}]
    try:
        drive(agent.agent_turn, [], hist, "m", conn, 1)
        interrupted = False
    except KeyboardInterrupt:
        interrupted = True
    agent.gate_and_dispatch = real_gate

    ok("the interrupt still reaches the caller", interrupted)
    asked = [c["id"] for m in hist if m.get("tool_calls")
             for c in m["tool_calls"]]
    got = [m.get("tool_call_id") for m in hist if m["role"] == "tool"]
    ok("every requested call has a result in live history",
       sorted(asked) == sorted(got), (asked, got))
    ok("...and the filler says it was interrupted",
       any("interrupted" in m["content"] for m in hist
           if m["role"] == "tool"), [m for m in hist if m["role"] == "tool"])
    ok("the same is true of what was persisted",
       dbmod._drop_orphan_tool_calls(list(hist)) == hist,
       "orphan drop changed the history, so something was unanswered")

    print("\n--- the turn's total tool output is bounded ---")
    # The call ceiling bounds round trips; it does not bound how large the
    # request grows, and every call re-sends every result. This is the budget
    # that does. Spending it withdraws the tools for one final call rather than
    # truncating the turn, so the model answers in its own words.
    big = jail / "big.md"
    big.write_text("x" * 5000 + "\n")
    agent.TURN_RESULT_CHARS = 4000
    agent.call_api = FakeAPI([
        reply(None, [("read_file", {"path": str(big)})]),
        reply(None, [("read_file", {"path": str(big)})]),
        reply("I read the first one and ran out of room."),
    ])
    fake = agent.call_api
    hist = [{"role": "user", "content": "read it"}]
    final, out = drive(agent.agent_turn, [], hist, "m", conn, 1, keys="A\n")
    ok("the turn ends with the model's own answer, not a stub",
       final["content"] == "I read the first one and ran out of room.", final)
    ok("the second read was refused for budget",
       "budget" in [m for m in hist if m["role"] == "tool"][1]["content"],
       hist)
    ok("tools were withdrawn for the final call",
       fake.seen[-1]["tools"] is None,
       [bool(s["tools"]) for s in fake.seen])
    ok("...and the model was told why",
       any("output budget" in (m.get("content") or "")
           for m in fake.seen[-1]["messages"]),
       fake.seen[-1]["messages"][-1])
    agent.TURN_RESULT_CHARS = 120_000

    print("\n--- a failed request says what was in flight ---")
    # Every provider 400 arrived as one indistinguishable line. These numbers
    # are what separate a context overflow from a malformed conversation from
    # a content filter.
    def refuse(messages, model=None, tools=None):
        raise httpx.HTTPError("HTTP 400 from provider: max_tokens too small")

    agent.call_api = refuse
    try:
        drive(agent.agent_turn, [], [{"role": "user", "content": "go"}],
              "m", conn, 1)
        raised = ""
    except httpx.HTTPError as e:
        raised = str(e)
    ok("the provider's own words survive", "max_tokens too small" in raised,
       raised)
    ok("...with our side of the request appended",
       "cfc:" in raised and "tokens" in raised and "messages" in raised,
       raised)
    ok("still an httpx.HTTPError, so every existing catch matches",
       raised != "")

    # The routine runner may retry a provider response, but only by its actual
    # status code.  agent_turn adds request context before the error reaches
    # it, so this pins that the structured code survives the wrapper.
    def unavailable(messages, model=None, tools=None):
        error = httpx.HTTPError("provider unavailable")
        error.status_code = 503
        raise error

    agent.call_api = unavailable
    try:
        drive(agent.agent_turn, [], [{"role": "user", "content": "go"}],
              "m", conn, 1)
    except httpx.HTTPError as e:
        status_code = getattr(e, "status_code", None)
    else:
        status_code = None
    ok("the provider status survives request-context enrichment",
       status_code == 503, status_code)

    print("\n--- an empty-completion 400 re-rolls instead of failing ---")
    # nano-gpt surfaces a thinking model's empty completion as a 400 on the
    # non-streaming path. It is the same benign hiccup the stream path re-rolls,
    # so the tool loop must not let it out as a hard error — it returns an empty
    # message, which is exactly what runner._turn_with_retry re-rolls on. The
    # discrimination is the whole point: this must NOT catch the max_tokens 400
    # above, or an oversize request would re-roll forever.
    conn.execute("DELETE FROM messages")
    conn.commit()

    def empty_400(messages, model=None, tools=None):
        raise httpx.HTTPError(
            "HTTP 400 from provider: The model returned an empty response. "
            "No charge was applied.")

    agent.call_api = empty_400
    hist = [{"role": "user", "content": "go"}]
    raised = ""
    try:
        final, out = drive(agent.agent_turn, [], hist, "m", conn, 1)
    except httpx.HTTPError as e:
        raised = str(e)
    ok("an empty-completion 400 does not raise", raised == "", raised)
    ok("...it returns an empty message the caller can re-roll",
       final.get("content") == "", final)
    ok("...and says what happened", "provider hiccup" in out, out[-200:])
    ok("...persisted as an empty row, like any empty completion",
       conn.execute("SELECT COUNT(*) FROM messages WHERE role='assistant' "
                    "AND TRIM(content)=''").fetchone()[0] == 1)
    ok("the max_tokens 400 is still recognised as a real failure, not this one",
       not agent._is_empty_completion_400(
           httpx.HTTPError("HTTP 400 from provider: max_tokens too small")))

    print("\n--- the model is told the budgets up front ---")
    guidance = agent.tools_guidance(max_calls=9)
    ok("guidance is one system message",
       len(guidance) == 1 and guidance[0]["role"] == "system", guidance)
    ok("...naming both budgets",
       "9 tool calls" in guidance[0]["content"]
       and f"{agent.TURN_RESULT_CHARS:,}" in guidance[0]["content"],
       guidance[0]["content"])

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
