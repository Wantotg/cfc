#!/usr/bin/env python3
"""
test_turn_paths.py — the streaming turn and the tool turn end identically.

    python3 tests/test_turn_paths.py

**Standing decision 7, pinned for the first time** (v1.0, `W-02`). A chat turn
takes one of two paths, chosen per turn by
`TOOLS_ENABLED and tools_on and models.supports_tools(model)`: `api.stream_response`
or `agent.agent_turn`. They must end a turn the same way, and they drifted once
already — when tools became the default, the spinner and the token bar silently
vanished and usage was discarded, which blanked `/status`. Nothing failed. The
turn worked. Only the *ending* was gone, and it was gone for a whole release.

**The assertions compare the two paths against each other, never against a
literal.** That is the whole design of this file. A test that asserted "the bar
says 18 tokens" would pass forever while both paths drifted together, and would
have to be rewritten every time the rendering changed; a test that asserts *the
tool path ends exactly as the streaming path does* cannot pass while they
disagree and never needs touching when they agree differently. Same discipline
as `tests/test_tools.py`' producer/parser pairs, applied to two code paths
instead of two modules.

**Behavioural, not schema** — which is deliberate, because the DB layer is
expected to be rebuilt (`W-07`, 2.0). What is pinned here is *the assistant turn
is persisted with its usage, and the post-turn bar is reached with that usage*.
Nothing here names a column type or a table shape, so the rework inherits these
tests rather than deleting them, and that is what makes the rework safe to
attempt.

**Only the provider is stubbed.** The streaming path gets a fake
`stream_response`; the tool path gets a fake `agent.call_api` so the *real*
`agent_turn` runs, persists and records usage the way it does in a session. A
stub any higher up would be testing the stub. No API key, no network.
"""
import contextlib
import io
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
import governor
import main
import models

PASS, FAIL = [], []

MODEL = "stub-model"
# The same completion from both providers. Different numbers per path would
# make every comparison below vacuous — the point is that identical input
# through two paths leaves identical state.
ANSWER = "an answer from the stub"
USAGE = {"prompt_tokens": 1100, "completion_tokens": 640}


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:220]}")


def drive(conn, sid, keys):
    """Run one session to completion, returning (stdout, bar calls).

    The spy wraps `print_context_bar` rather than replacing it: what the turn
    *passed* to the bar is the thing that was discarded in the original drift,
    and what it *printed* is what vanished. Both are wanted, so it records the
    arguments and then calls through.
    """
    seen = []
    real_bar = main.print_context_bar

    def spy(model, tok_in, tok_out):
        seen.append((model, tok_in, tok_out))
        return real_bar(model, tok_in, tok_out)

    out = io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(keys)
    main.print_context_bar = spy
    try:
        with contextlib.redirect_stdout(out):
            main.console.file = out
            commands.console.file = out
            agent.console.file = out
            main.run_session(conn, sid, private=False)
    finally:
        sys.stdin = real_stdin
        main.print_context_bar = real_bar
        main.console.file = sys.stdout
        commands.console.file = sys.stdout
        agent.console.file = sys.stdout
    return out.getvalue(), seen


def assistant_row(conn, sid):
    """The turn as it was persisted. Behaviour, not schema: four values a
    caller actually reads back, not the shape of the table holding them."""
    return conn.execute(
        "SELECT role, content, tokens_in, tokens_out, model FROM messages "
        "WHERE session_id=? AND role='assistant' ORDER BY id DESC LIMIT 1",
        (sid,)).fetchone()


def main_():
    tmp = Path(tempfile.mkdtemp())
    # Invariant #1: check the path before anything writes to it.
    assert "tmp" in str(tmp), "refusing to touch a real db"
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()

    # Only the provider is faked. `stream_response` is the streaming path's
    # wire call; `agent.call_api` is the tool path's, so the real agent_turn
    # runs above it.
    main.stream_response = lambda messages, model=None: (ANSWER, dict(USAGE), "")
    agent.call_api = lambda messages, model=None, tools=None: {
        "choices": [{"message": {"role": "assistant", "content": ANSWER}}],
        "usage": dict(USAGE),
    }
    main.generate_title = lambda *a, **k: "(untitled)"
    main.auto_embed = lambda: None
    main.safe_export = lambda *a, **k: None

    # The switch that chooses the path. `tools_on` defaults True in the
    # session, so `models.supports_tools(MODEL)` is what actually decides
    # here — which is the real dispatch, not a test-only flag. The same
    # record carries the known limit the context bar needs (below).
    main.TOOLS_ENABLED = True
    models.MODELS = [models._spec(MODEL, tools=True, limit=128_000)]

    print("\n--- one turn down each path, same stub, same question ---")
    stream_sid = dbmod.new_session(conn, title="streaming", model=MODEL)
    stream_out, stream_bars = drive(conn, stream_sid, "/tools off\nhello\n/q\n")
    tool_sid = dbmod.new_session(conn, title="tools", model=MODEL)
    tool_out, tool_bars = drive(conn, tool_sid, "hello\n/q\n")

    ok("both paths ran a turn and left the session",
       "hello" in stream_out and "hello" in tool_out, (len(stream_out), len(tool_out)))
    # **Rendering the answer is NOT one of the shared endings, and finding that
    # out is what this assertion is for.** The tool path calls
    # `agent.render_answer` from `main.py`; the streaming path renders *inside*
    # `api.stream_response`, delta by delta, because it has to paint as it
    # arrives. So stubbing at the provider boundary — the right place — takes
    # the streaming render with it, and no honest comparison of the two answer
    # panels is possible from here.
    #
    # That is not a gap this file should paper over with a lower stub. Standing
    # decision 7 names `print_context_bar`, and it is exactly right to: the
    # *ending* is shared and is what drifted, while the rendering is two
    # different jobs (a live region vs a finished string) that only look alike.
    # Everything below compares the ending. The panels stay hand-verified, and
    # `HANDOVER.md`'s Testing section says so.
    ok("the tool path rendered its answer through the shared helper",
       ANSWER in tool_out, tool_out[-300:])

    print("\n--- the turn is persisted the same way ---")
    s_row, t_row = assistant_row(conn, stream_sid), assistant_row(conn, tool_sid)
    ok("both paths persisted an assistant turn", bool(s_row) and bool(t_row),
       (s_row, t_row))
    ok("...identically", s_row == t_row, f"{s_row} != {t_row}")
    # Named separately, because this is the half that actually broke: the row
    # existed, the conversation worked, and the numbers were None.
    ok("...and neither discarded the usage",
       (s_row[2], s_row[3]) == (USAGE["prompt_tokens"], USAGE["completion_tokens"]),
       s_row)

    print("\n--- the post-turn bar is reached with that usage ---")
    ok("the streaming path called it once", len(stream_bars) == 1, stream_bars)
    ok("the tool path called it once", len(tool_bars) == 1, tool_bars)
    # The tool path reads its numbers back out of the row `agent_turn` wrote;
    # the streaming path has them in hand from `usage`. Two mechanisms, and
    # this is the assertion that they arrive at the same answer.
    ok("...with identical arguments", stream_bars == tool_bars,
       f"{stream_bars} != {tool_bars}")

    print("\n--- and it is rendered, not merely called ---")
    # The drift was invisible precisely because nothing raised: a bar that is
    # called with the right numbers and prints nothing is the same blank screen.
    bar_lines = lambda out: [l for l in out.splitlines() if "%" in l and "[" in l]
    ok("the streaming path printed a bar", bar_lines(stream_out),
       stream_out[-300:])
    ok("the tool path printed one too", bar_lines(tool_out), tool_out[-300:])
    ok("...and they are the same bar",
       bar_lines(stream_out) == bar_lines(tool_out),
       (bar_lines(stream_out), bar_lines(tool_out)))

    print("\n--- the next turn replays what the last one left ---")
    # `history` is rebuilt from the db on reopen, so this is the check that a
    # turn is not merely rendered but usable as context afterwards — the
    # property `/status` reads and the next request depends on.
    for label, sid in (("streaming", stream_sid), ("tools", tool_sid)):
        replayed = dbmod.load_history(conn, sid)
        ok(f"{label}: the answer is in the replayed history",
           any(m.get("role") == "assistant" and m.get("content") == ANSWER
               for m in replayed), replayed)
    s_ctx = commands.get_context_info(conn, stream_sid, MODEL)
    t_ctx = commands.get_context_info(conn, tool_sid, MODEL)
    ok("both sessions report the same context afterwards", s_ctx == t_ctx,
       f"{s_ctx} != {t_ctx}")

    print("\n--- the governor's envelope, captured from both paths ---")
    # Capturing stubs — same shape as test_agent.py's FakeAPI, but recording
    # what each path was actually asked, so the direction can be found in
    # the real assembled request rather than inferred from behaviour.
    stream_calls, tool_calls_seen = [], []

    def capturing_stream(messages, model=None):
        stream_calls.append([dict(m) for m in messages])
        return ANSWER, dict(USAGE), ""

    def capturing_call_api(messages, model=None, tools=None):
        tool_calls_seen.append([dict(m) for m in messages])
        return {"choices": [{"message": {"role": "assistant",
                                         "content": ANSWER}}],
               "usage": dict(USAGE)}

    main.stream_response = capturing_stream
    agent.call_api = capturing_call_api

    tone_wrapped = f"[cfc direction]\n{governor.TONE_INSTRUCTION}\n" \
                  f"[/cfc direction]"

    s_sid = dbmod.new_session(conn, title="gov-stream", model=MODEL)
    drive(conn, s_sid, "/tools off\nhello\n/q\n")
    t_sid = dbmod.new_session(conn, title="gov-tools", model=MODEL)
    drive(conn, t_sid, "hello\n/q\n")

    ok("the streaming path's request carries the tone-check direction",
       any(m.get("content") == tone_wrapped for m in stream_calls[-1]),
       stream_calls[-1])
    ok("the tool path's request carries the same direction",
       any(m.get("content") == tone_wrapped for m in tool_calls_seen[-1]),
       tool_calls_seen[-1])
    ok("both requests carry exactly one direction message",
       sum(1 for m in stream_calls[-1] if m.get("content") == tone_wrapped)
       == 1 == sum(1 for m in tool_calls_seen[-1]
                   if m.get("content") == tone_wrapped))

    print("\n--- the dim governor line names what it added ---")
    out, _ = drive(conn, dbmod.new_session(conn, title="gov-line", model=MODEL),
                   "/tools off\nhi again\n/q\n")
    ok("an ordinary turn prints 'cfc -> tone check'",
       "cfc -> tone check" in out, out)

    print("\n--- /continue: usage, refusal, and a real directed turn ---")
    stream_calls.clear()
    bare_sid = dbmod.new_session(conn, title="continue-bare", model=MODEL)
    out, _ = drive(conn, bare_sid, "/tools off\n/continue extra args\n/q\n")
    ok("/continue with arguments is a usage error, not a turn",
       "Usage: /continue" in out, out)
    ok("...and makes no API call", stream_calls == [])

    empty_sid = dbmod.new_session(conn, title="continue-empty", model=MODEL)
    out, _ = drive(conn, empty_sid, "/tools off\n/continue\n/q\n")
    ok("/continue with nothing to continue from refuses visibly",
       "Nothing to continue yet" in out, out)
    ok("...and makes no API call either", stream_calls == [])

    cont_sid = dbmod.new_session(conn, title="continue-real", model=MODEL)
    drive(conn, cont_sid, "/tools off\nhello\n/q\n")   # one ordinary turn first
    stream_calls.clear()
    before_rows = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id=?",
        (cont_sid,)).fetchone()[0]
    out, _ = drive(conn, cont_sid, "/tools off\n/continue\n/q\n")
    after_rows = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id=?",
        (cont_sid,)).fetchone()[0]
    ok("/continue makes exactly one API call", len(stream_calls) == 1,
       stream_calls)
    continue_wrapped = (f"[cfc direction]\n{governor.CONTINUE_INSTRUCTION}\n"
                        f"[/cfc direction]")
    ok("...whose request carries the continue direction, not tone/trait",
       any(m.get("content") == continue_wrapped for m in stream_calls[0])
       and not any(m.get("content") == tone_wrapped for m in stream_calls[0]),
       stream_calls[0])
    ok("...and adds exactly one durable row (the answer), no user row",
       after_rows - before_rows == 1, (before_rows, after_rows))
    last_two = conn.execute(
        "SELECT role FROM messages WHERE session_id=? ORDER BY id DESC LIMIT 2",
        (cont_sid,)).fetchall()
    ok("...leaving two consecutive assistant rows in durable history",
       [r[0] for r in last_two] == ["assistant", "assistant"], last_two)
    ok("the dim line names it", "cfc -> continue" in out, out)

    print("\n--- OOC: exact grammar, no user row, suppresses tone/trait ---")
    stream_calls.clear()
    ooc_sid = dbmod.new_session(conn, title="ooc", model=MODEL)
    before_rows = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id=?",
        (ooc_sid,)).fetchone()[0]
    out, _ = drive(conn, ooc_sid, "/tools off\n((be gentler))\n/q\n")
    after_rows = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id=?",
        (ooc_sid,)).fetchone()[0]
    ooc_wrapped = "[cfc direction]\nbe gentler\n[/cfc direction]"
    ok("OOC makes exactly one API call", len(stream_calls) == 1, stream_calls)
    ok("...whose request carries the typed text as the whole direction",
       any(m.get("content") == ooc_wrapped for m in stream_calls[0]),
       stream_calls[0])
    ok("...and no tone-check direction rides alongside it",
       not any(m.get("content") == tone_wrapped for m in stream_calls[0]),
       stream_calls[0])
    ok("no user row for the OOC marker itself — only the answer is durable",
       after_rows - before_rows == 1, (before_rows, after_rows))
    ok("the marker text was never saved as a message",
       conn.execute("SELECT COUNT(*) FROM messages WHERE session_id=? AND "
                    "content LIKE '%be gentler%' AND role='user'",
                    (ooc_sid,)).fetchone()[0] == 0)
    ok("the dim line names it", "cfc -> ooc" in out, out)

    stream_calls.clear()
    empty_ooc_sid = dbmod.new_session(conn, title="ooc-empty", model=MODEL)
    out, _ = drive(conn, empty_ooc_sid, "/tools off\n(( ))\n/q\n")
    ok("an empty OOC marker refuses without a provider call",
       "Empty OOC direction" in out, out)
    ok("...and really makes no call", stream_calls == [])

    conn.close()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
