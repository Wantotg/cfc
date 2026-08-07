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
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import agent
import api
import commands
import db as dbmod
import errorlog
import governor
import httpx
import import_wiki
import main
import models
import pools
import wikigit

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
        main.print_context_bar = real_bar
        main.console.file = saved_main_file
        commands.console.file = saved_commands_file
        agent.console.file = saved_agent_file
    return out.getvalue(), seen


def drive_private(conn, sid, keys):
    """Same idiom as `drive`, against a private chat — decision 15's "chat
    means both chats", so W-1.6.3-01b needs its own proof against a session
    that runs on `db(':memory:')` rather than assuming the normal-chat proof
    above covers it."""
    out = io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(keys)
    saved_main_file = main.console.file
    try:
        with contextlib.redirect_stdout(out):
            main.console.file = out
            main.run_session(conn, sid, auto_export=False, private=True)
    finally:
        sys.stdin = real_stdin
        main.console.file = saved_main_file
    return out.getvalue()


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

    # Same guard, one file over (`D-08`, `B-07`'s companion). This file drives
    # *real* turns through `main._run_turn`, and two of the paths below reach
    # `errorlog.log_error` on their own — a failed title and a provider error.
    # Without this redirect they append to `~/.cfc/errors.log`, and four
    # fabricated `title` records reached the live log that way during v1.4.1.
    # That log is the evidence base for `B-01`'s absence watch, so a test that
    # writes to it is manufacturing the thing being watched for.
    errorlog.LOG_PATH = tmp / "errors.log"
    assert "tmp" in str(errorlog.LOG_PATH), "refusing to touch the real log"

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
    # The process-wide selection (W-1.3.1-03), not each session's own stored
    # `model` — run_session no longer reads that at open. Every scenario in
    # this file drives the same MODEL throughout and never types /model, so
    # setting it once here is the whole of what `new_session(..., model=MODEL)`
    # used to buy on its own.
    main.set_process_model(MODEL)

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

    print("\n--- the post-turn bar states an honest count when the limit "
          "isn't known (D-1.7-02) ---")
    # Same shared ending, a model with no configured limit. print_context_bar
    # must not go silent the way it used to (nothing at all) or invent a
    # percentage — it says the count and that the limit is unknown, exactly
    # once, on both paths.
    UNLIMITED_MODEL = "stub-model-nolimit"
    models.MODELS = [models._spec(MODEL, tools=True, limit=128_000),
                     models._spec(UNLIMITED_MODEL, tools=True)]
    main.set_process_model(UNLIMITED_MODEL)
    try:
        u_stream_sid = dbmod.new_session(conn, title="streaming-nolimit",
                                         model=UNLIMITED_MODEL)
        u_stream_out, u_stream_bars = drive(conn, u_stream_sid,
                                            "/tools off\nhello\n/q\n")
        u_tool_sid = dbmod.new_session(conn, title="tools-nolimit",
                                       model=UNLIMITED_MODEL)
        u_tool_out, u_tool_bars = drive(conn, u_tool_sid, "hello\n/q\n")
    finally:
        main.set_process_model(MODEL)

    for label, out, bars in (("streaming", u_stream_out, u_stream_bars),
                             ("tools", u_tool_out, u_tool_bars)):
        ok(f"{label}: the bar is still reached with the usage",
           len(bars) == 1 and bars[0][0] == UNLIMITED_MODEL, bars)
        ok(f"{label}: it says the count and that the limit is unknown",
           "tokens · limit unknown" in out, out[-300:])
        ok(f"{label}: no percentage bar is drawn", not bar_lines(out),
           out[-300:])

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

    boundary = ("this direction is cfc control text, not a message in the "
               "conversation")
    ok("the streaming envelope's direction carries the unanswerable boundary",
       boundary in stream_calls[-1][-1]["content"], stream_calls[-1][-1])
    ok("the tool envelope's direction carries the same boundary",
       boundary in tool_calls_seen[-1][-1]["content"], tool_calls_seen[-1][-1])

    print("\n--- the boundary survives a cadence turn, alongside a trait ---")
    # B-1.6.3-01a: the boundary is written into TONE_INSTRUCTION itself, so
    # ordinary_instruction's combined tone-and-trait reminder inherits it
    # automatically. Proven here against a real envelope, not just the
    # governor unit, and on a cadence turn so the trait text is actually
    # riding alongside it rather than absent.
    trait_dir = tmp / "traits"
    trait_dir.mkdir()
    (trait_dir / "relax.md").write_text("Be calm.")
    pools.POOLS["trait"].configured = str(trait_dir)
    stream_calls.clear()
    trait_sid = dbmod.new_session(conn, title="gov-trait", model=MODEL)
    drive(conn, trait_sid,
         "/tools off\n/add trait relax\nhi\nhi\nhi\nhi\nhi\nhi\n/q\n")
    last_req = stream_calls[-1]
    directions = [m for m in last_req
                 if m.get("content", "").startswith(governor.DIRECTION_OPEN)]
    ok("exactly one direction message on the cadence turn", len(directions) == 1,
       last_req)
    ok("it carries the boundary and the trait reminder together",
       bool(directions) and boundary in directions[0]["content"]
       and "Be calm." in directions[0]["content"], directions)
    pools.POOLS["trait"].configured = ""

    print("\n--- the dim governor line names what it added ---")
    out, _ = drive(conn, dbmod.new_session(conn, title="gov-line", model=MODEL),
                   "/tools off\nhi again\n/q\n")
    ok("an ordinary turn prints 'Cooking for Cats -> tone check'",
       "Cooking for Cats -> tone check" in out, out)

    print("\n--- W-1.6.3-01b: GOVERNOR_TONE_CHECK off — tone and trait ride "
          "independently ---")
    saved_tone_check = governor.GOVERNOR_TONE_CHECK
    try:
        governor.GOVERNOR_TONE_CHECK = False

        stream_calls.clear()
        off_sid = dbmod.new_session(conn, title="tone-off", model=MODEL)
        out, _ = drive(conn, off_sid, "/tools off\nhello\n/q\n")
        ok("off-cadence, tone off: no governor label at all",
           "Cooking for Cats ->" not in out, out)
        ok("...and no direction message rides in the request",
           not any(m.get("content", "").startswith(governor.DIRECTION_OPEN)
                   for m in stream_calls[-1]), stream_calls[-1])

        pools.POOLS["trait"].configured = str(trait_dir)
        stream_calls.clear()
        cadence_sid = dbmod.new_session(conn, title="tone-off-cadence",
                                        model=MODEL)
        out, _ = drive(conn, cadence_sid,
                       "/tools off\n/add trait relax\nhi\nhi\nhi\nhi\nhi\nhi\n/q\n")
        last_req = stream_calls[-1]
        directions = [m for m in last_req
                     if m.get("content", "").startswith(governor.DIRECTION_OPEN)]
        ok("cadence turn, tone off: exactly one direction, the trait alone",
           len(directions) == 1 and "Be calm." in directions[0]["content"],
           directions)
        ok("...with no tone boundary riding alongside it",
           bool(directions) and boundary not in directions[0]["content"],
           directions)
        ok("the dim line names only the trait, never tone check",
           "trait: relax" in out and "tone check" not in out, out)
        pools.POOLS["trait"].configured = ""

        print("\n--- W-1.6.3-01b: OOC, /continue and /swipe are unaffected "
              "by the switch ---")
        local_ooc_wrapped = "[cfc direction]\nbe gentler\n[/cfc direction]"
        local_continue_wrapped = (f"[cfc direction]\n"
                                  f"{governor.CONTINUE_INSTRUCTION}\n"
                                  f"[/cfc direction]")

        stream_calls.clear()
        ooc_off_sid = dbmod.new_session(conn, title="ooc-tone-off", model=MODEL)
        out, _ = drive(conn, ooc_off_sid, "/tools off\n((be gentler))\n/q\n")
        ok("OOC still sends its own direction with tone off",
           any(m.get("content") == local_ooc_wrapped for m in stream_calls[0]),
           stream_calls[0])
        ok("the dim line still names 'ooc', not a governor label",
           "Cooking for Cats -> ooc" in out, out)

        stream_calls.clear()
        cont_off_sid = dbmod.new_session(conn, title="continue-tone-off",
                                         model=MODEL)
        drive(conn, cont_off_sid, "/tools off\nhello\n/q\n")
        stream_calls.clear()
        out, _ = drive(conn, cont_off_sid, "/tools off\n/continue\n/q\n")
        ok("/continue still sends its own direction with tone off",
           any(m.get("content") == local_continue_wrapped
               for m in stream_calls[0]),
           stream_calls[0])
        ok("the dim line still names 'continue'",
           "Cooking for Cats -> continue" in out, out)

        stream_calls.clear()
        swipe_off_sid = dbmod.new_session(conn, title="swipe-tone-off",
                                          model=MODEL)
        drive(conn, swipe_off_sid, "/tools off\nhello\n/q\n")
        stream_calls.clear()
        out, _ = drive(conn, swipe_off_sid, "/tools off\n/swipe\n/q\n")
        ok("/swipe on an off-cadence turn with tone off: no governor label "
           "either — it earns the same ordinary cadence as a fresh send",
           "Cooking for Cats ->" not in out, out)
        ok("...and no direction rides in the regenerated request",
           not any(m.get("content", "").startswith(governor.DIRECTION_OPEN)
                   for m in stream_calls[-1]), stream_calls[-1])

        print("\n--- W-1.6.3-01b: the switch applies identically in a "
              "private chat (decision 15) ---")
        stream_calls.clear()
        priv_conn = dbmod.db(":memory:")
        priv_sid = dbmod.new_session(priv_conn, title="(untitled)")
        priv_out = drive_private(priv_conn, priv_sid, "/tools off\nhello\n/q\n")
        ok("private chat, tone off, off-cadence: no governor label either",
           "Cooking for Cats ->" not in priv_out, priv_out)
        priv_conn.close()
    finally:
        governor.GOVERNOR_TONE_CHECK = saved_tone_check

    print("\n--- W-1.6.3-01b: tone-on compatibility — restoring the switch "
          "restores the exact original line ---")
    out, _ = drive(conn, dbmod.new_session(conn, title="tone-restored",
                                           model=MODEL),
                   "/tools off\nhello\n/q\n")
    ok("with the switch back on, the tone-check label reappears unchanged",
       "Cooking for Cats -> tone check" in out, out)

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
    ok("the dim line names it", "Cooking for Cats -> continue" in out, out)

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
    ok("the dim line names it", "Cooking for Cats -> ooc" in out, out)

    stream_calls.clear()
    empty_ooc_sid = dbmod.new_session(conn, title="ooc-empty", model=MODEL)
    out, _ = drive(conn, empty_ooc_sid, "/tools off\n(( ))\n/q\n")
    ok("an empty OOC marker refuses without a provider call",
       "Empty OOC direction" in out, out)
    ok("...and really makes no call", stream_calls == [])

    print("\n--- W-1.6.4-02: one shared finisher — transient status, order, "
          "titling (B-1.3.1-02, D-13) ---")
    # `main.stream_response`/`agent.call_api` were left as capturing stubs by
    # the governor section above; put back a plain answering one so what's
    # under test here is `_finish_turn`, not the request capture.
    main.stream_response = lambda messages, model=None: (ANSWER, dict(USAGE), "")
    agent.call_api = lambda messages, model=None, tools=None: {
        "choices": [{"message": {"role": "assistant", "content": ANSWER}}],
        "usage": dict(USAGE),
    }

    def drive_finish(sid, keys, title_result=None, title_error=None,
                     embed_error=None, private=False):
        """Like `drive`, but spies on `generate_title`/`auto_embed` and on
        `console.status` itself — the wording only ever reaches a real
        terminal (Rich's Live rendering is a no-op against a redirected,
        non-tty stream, same as `agent.py`'s "Thinking..." status already
        is), so the seam to patch for the *wording* is `console.status`,
        not the captured text. `calls` is one ordered timeline — a
        ("status", wording) entry on entry, then ("title", snapshot) /
        ("embed", snapshot) — so list order alone proves the finisher's
        sequencing, and the snapshots still prove neither job sees the next
        prompt boundary before the finisher returns."""
        calls = []
        real_title, real_embed = main.generate_title, main.auto_embed
        real_status = main.console.status

        def title_spy(user_text):
            calls.append(("title", out.getvalue()))
            if title_error is not None:
                raise title_error
            return title_result if title_result is not None else "A Title"

        def embed_spy():
            calls.append(("embed", out.getvalue()))
            if embed_error is not None:
                # commands.auto_embed() never raises out of a real failure —
                # it prints this line itself and swallows the exception. The
                # spy mirrors that shape rather than propagating.
                main.console.print(f"[auto-embed skipped: {embed_error}]")

        class _FakeStatus:
            """Records the wording `_finish_turn` chose and behaves as a
            no-op context manager — proving what cfc *decided* to show
            without depending on Rich's terminal-only rendering."""

            def __init__(self, wording, **_kw):
                self.wording = wording

            def __enter__(self):
                calls.append(("status", self.wording))
                return self

            def __exit__(self, *exc):
                return False

        out = io.StringIO()
        real_stdin = sys.stdin
        sys.stdin = io.StringIO(keys)
        main.generate_title = title_spy
        main.auto_embed = embed_spy
        main.console.status = lambda wording, **kw: _FakeStatus(wording, **kw)
        saved_main_file = main.console.file
        saved_commands_file = commands.console.file
        saved_agent_file = agent.console.file
        try:
            with contextlib.redirect_stdout(out):
                main.console.file = out
                commands.console.file = out
                agent.console.file = out
                main.run_session(conn, sid, auto_export=False,
                                 private=private)
        finally:
            sys.stdin = real_stdin
            main.generate_title = real_title
            main.auto_embed = real_embed
            main.console.status = real_status
            main.console.file = saved_main_file
            commands.console.file = saved_commands_file
            agent.console.file = saved_agent_file
        return out.getvalue(), calls

    print("  (first-turn success: title plus embed, in order)")
    fin_sid = dbmod.new_session(conn, title="(untitled)")
    out, calls = drive_finish(fin_sid, "/tools off\nhello\n/q\n",
                              title_result="First Turn Title")
    ok("the status wording names both jobs",
       calls[0] == ("status", "Titling chat and updating memory..."), calls)
    ok("...entered exactly once", sum(1 for c in calls if c[0] == "status") == 1,
       calls)
    ok("...before title, and title before embed",
       [c[0] for c in calls] == ["status", "title", "embed"], calls)
    title_snap = next(c[1] for c in calls if c[0] == "title")
    embed_snap = next(c[1] for c in calls if c[0] == "embed")
    # Three input() calls in the script ("/tools off", "hello", "/q") each
    # print "you> "; the finisher's work happens between the second and
    # third, so neither spy should see the third prompt yet.
    ok("neither spy sees the next prompt boundary",
       title_snap.count("you> ") == 2 and embed_snap.count("you> ") == 2,
       (title_snap.count("you> "), embed_snap.count("you> ")))
    ok("...and the boundary prints only once the finisher is done",
       out.count("you> ") == 3, out)
    ok("a successful title is persisted",
       dbmod.get_session_title(conn, fin_sid) == "First Turn Title")
    ok("the transient wording never becomes conversation history",
       not any("Titling chat" in (m.get("content") or "")
              or "Updating memory" in (m.get("content") or "")
              for m in dbmod.load_history(conn, fin_sid)),
       dbmod.load_history(conn, fin_sid))

    print("  (title-only: embed disabled this turn, so the wording names "
          "just the one job)")
    saved_auto_embed = commands.AUTO_EMBED
    commands.AUTO_EMBED = False
    try:
        title_only_sid = dbmod.new_session(conn, title="(untitled)")
        out, calls = drive_finish(title_only_sid, "/tools off\nhi\n/q\n",
                                  title_result="Title Only")
    finally:
        commands.AUTO_EMBED = saved_auto_embed
    ok("wording names titling alone",
       calls[0] == ("status", "Titling chat..."), calls)
    ok("...and embed never fires", not any(c[0] == "embed" for c in calls),
       calls)

    print("  (embed-only: a later turn, so titling doesn't run — the "
          "wording names just the one job)")
    embed_only_sid = dbmod.new_session(conn, title="(untitled)")
    drive_finish(embed_only_sid, "/tools off\nfirst\n/q\n",
                title_result="Embed Only Setup")
    out, calls = drive_finish(embed_only_sid, "/tools off\nsecond\n/q\n",
                              title_result="Should Not Land")
    ok("wording names embedding alone",
       calls[0] == ("status", "Updating memory..."), calls)
    ok("...and title never fires", not any(c[0] == "title" for c in calls),
       calls)

    print("  (neither job: a later turn with embed off too — no status at "
          "all)")
    saved_auto_embed = commands.AUTO_EMBED
    commands.AUTO_EMBED = False
    try:
        neither_sid = dbmod.new_session(conn, title="(untitled)")
        drive_finish(neither_sid, "/tools off\nfirst\n/q\n",
                    title_result="Neither Setup")
        out, calls = drive_finish(neither_sid, "/tools off\nsecond\n/q\n",
                                  title_result="Should Not Land")
    finally:
        commands.AUTO_EMBED = saved_auto_embed
    ok("no status, no title, no embed — the turn still ends cleanly",
       calls == [], calls)

    print("  (title failure: the wording still named the attempt, and the "
          "failure line is durable)")
    saved_auto_embed = commands.AUTO_EMBED
    commands.AUTO_EMBED = False
    try:
        tfail_sid = dbmod.new_session(conn, title="(untitled)")
        out, calls = drive_finish(
            tfail_sid, "/tools off\nhi\n/q\n",
            title_error=main.TitleGenerationError("boom"))
    finally:
        commands.AUTO_EMBED = saved_auto_embed
    ok("wording still said titling was attempted",
       calls[0] == ("status", "Titling chat..."), calls)
    ok("a title failure prints exactly one concise yellow line",
       out.count("[title unavailable]") == 1, out)
    ok("the session stays displayed as untitled after a failed attempt",
       dbmod.get_session_title(conn, tfail_sid) == "(untitled)")

    print("  (embed failure: the wording still named the attempt, and the "
          "failure line is durable)")
    efail_sid = dbmod.new_session(conn, title="(untitled)")
    drive_finish(efail_sid, "/tools off\nfirst\n/q\n", title_result="T0")
    out, calls = drive_finish(efail_sid, "/tools off\nsecond\n/q\n",
                              title_result="Should Not Land",
                              embed_error="embedder unreachable")
    ok("wording still said embedding was attempted",
       calls[0] == ("status", "Updating memory..."), calls)
    ok("an embed failure prints exactly one concise line",
       out.count("[auto-embed skipped: embedder unreachable]") == 1, out)

    print("  (private: neither job runs, so there is no status at all)")
    priv_conn = dbmod.db(":memory:")
    priv_sid = dbmod.new_session(priv_conn, title="(untitled)")
    real_title, real_embed = main.generate_title, main.auto_embed
    real_status = main.console.status
    priv_calls = []
    main.generate_title = lambda user_text: priv_calls.append("title") or "X"
    main.auto_embed = lambda: priv_calls.append("embed")
    main.console.status = lambda wording, **kw: priv_calls.append(
        ("status", wording)) or contextlib.nullcontext()
    out = io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO("/tools off\nhello\n/q\n")
    saved_main_file = main.console.file
    try:
        with contextlib.redirect_stdout(out):
            main.console.file = out
            main.run_session(priv_conn, priv_sid, auto_export=False,
                             private=True)
    finally:
        sys.stdin = real_stdin
        main.generate_title = real_title
        main.auto_embed = real_embed
        main.console.status = real_status
        main.console.file = saved_main_file
        priv_conn.close()
    ok("a private turn never enters a status, never titles, never embeds",
       priv_calls == [], priv_calls)

    print("  (failure once, no retry on a later turn — D-13)")
    fail_sid = dbmod.new_session(conn, title="(untitled)")
    out, calls = drive_finish(
        fail_sid, "/tools off\nhi\n/q\n",
        title_error=main.TitleGenerationError("boom"))
    ok("a title failure prints exactly one concise yellow line",
       out.count("[title unavailable]") == 1, out)
    ok("...alongside the one status naming both jobs",
       calls[0] == ("status", "Titling chat and updating memory..."), calls)
    ok("the session stays displayed as untitled after a failed attempt",
       dbmod.get_session_title(conn, fail_sid) == "(untitled)")
    # A second run_session against the same id is a reopen. turn_count is now
    # 2, so eligibility must not retry — even though this spy would succeed.
    out2, calls2 = drive_finish(fail_sid, "/tools off\nagain\n/q\n",
                                title_result="Should Never Land")
    ok("no later turn (after reopen) retries a failed title",
       not any(c[0] == "title" for c in calls2), calls2)
    ok("...though auto-embed still runs for that turn",
       any(c[0] == "embed" for c in calls2), calls2)
    ok("...and the title is still exactly what it was",
       dbmod.get_session_title(conn, fail_sid) == "(untitled)")

    print("  (a first turn that never answered still titles later — B-07)")
    # The reported shape: a provider error on turn one. The user row is
    # written before the request goes out, so `turn_count` has already moved
    # by the time an answer finally lands — and gating on that alone left the
    # chat permanently untitled. Driven as two real turns, the first through
    # the same `except httpx.HTTPError` a 503 takes.
    def refuses(messages, model=None):
        raise httpx.ConnectError("provider is having a day")

    late_sid = dbmod.new_session(conn, title="(untitled)")
    main.stream_response = refuses
    out, calls = drive_finish(late_sid, "/tools off\nheya\n/q\n",
                              title_result="Should Not Land Yet")
    ok("a failed first turn never reaches the finisher",
       calls == [], calls)
    ok("...but its user row is durable, so the turn count has moved",
       dbmod.count_chat_user_turns(conn, late_sid) == 1)

    main.stream_response = lambda messages, model=None: (ANSWER, dict(USAGE), "")
    out, calls = drive_finish(late_sid, "/tools off\nsecond try\n/q\n",
                              title_result="Late Title")
    ok("the first turn that actually answers titles the chat",
       any(c[0] == "title" for c in calls), calls)
    ok("...and it lands", dbmod.get_session_title(conn, late_sid) == "Late Title")
    # The other half of the same gate: having titled once, it must not title
    # again — the clause added for this bug must not reopen `D-13`'s retry.
    out, calls = drive_finish(late_sid, "/tools off\nthird\n/q\n",
                              title_result="Should Never Land")
    ok("...once, and no later turn tries again",
       not any(c[0] == "title" for c in calls), calls)
    ok("...leaving the title exactly as it was",
       dbmod.get_session_title(conn, late_sid) == "Late Title")

    print("  (/continue and OOC: the finisher runs, titling never does)")
    cont_sid = dbmod.new_session(conn, title="(untitled)")
    drive_finish(cont_sid, "/tools off\nfirst\n/q\n", title_result="T1")
    out, calls = drive_finish(cont_sid, "/tools off\n/continue\n/q\n",
                              title_result="Should Not Land")
    ok("/continue reaches the shared finisher, wording naming embed alone",
       calls[0] == ("status", "Updating memory..."), calls)
    ok("...but never titles", not any(c[0] == "title" for c in calls), calls)
    ok("...and still runs auto-embed",
       any(c[0] == "embed" for c in calls), calls)

    ooc_sid = dbmod.new_session(conn, title="(untitled)")
    out, calls = drive_finish(ooc_sid, "/tools off\n((be nicer))\n/q\n",
                              title_result="Should Not Land")
    ok("an OOC turn reaches the shared finisher too, same wording",
       calls[0] == ("status", "Updating memory..."), calls)
    ok("...but never titles, even on the session's first turn",
       not any(c[0] == "title" for c in calls), calls)
    ok("...and still runs auto-embed",
       any(c[0] == "embed" for c in calls), calls)
    # And this is why the gate keeps `turn_count == 1` rather than reducing to
    # "the session's first answer": that answer has already been given, by a
    # direction the person never typed as a message.
    out, calls = drive_finish(ooc_sid, "/tools off\nnow a real one\n/q\n",
                              title_result="After OOC")
    ok("...leaving the first typed turn after it still able to title",
       any(c[0] == "title" for c in calls)
       and dbmod.get_session_title(conn, ooc_sid) == "After OOC", calls)

    print("  (empty and cancelled turns never reach the finisher)")
    main.stream_response = lambda messages, model=None: ("", {}, "")
    empty_sid = dbmod.new_session(conn, title="(untitled)")
    out, calls = drive_finish(empty_sid, "/tools off\nhello\n/q\n",
                              title_result="Should Not Land")
    ok("an empty completion never enters a status, titles, or embeds",
       calls == [], calls)

    def raises_interrupt(messages, model=None):
        raise KeyboardInterrupt

    main.stream_response = raises_interrupt
    cancel_sid = dbmod.new_session(conn, title="(untitled)")
    out, calls = drive_finish(cancel_sid, "/tools off\nhello\n/q\n",
                              title_result="Should Not Land")
    ok("a cancelled turn never enters a status, titles, or embeds",
       calls == [], calls)
    main.stream_response = lambda messages, model=None: (ANSWER, dict(USAGE), "")

    print("\n--- D-17: a chat-turn provider error records its action, not "
          "just 'chat' ---")
    # `errorlog.LOG_PATH` is already redirected above. Each scenario snapshots
    # the log before and after driving, and checks only the appended tail —
    # the same before/after shape `test_private.py` uses — so one scenario's
    # entry can't be mistaken for another's.

    def log_tail():
        return errorlog.LOG_PATH.read_text() if errorlog.LOG_PATH.exists() else ""

    def raise_http(msg):
        def _raiser(messages, model=None):
            raise httpx.HTTPError(msg)
        return _raiser

    def raise_http_tools(msg):
        def _raiser(prefix, history, model, conn, session_id, ctx=None,
                    max_calls=None, touched=None, first_message=None,
                    instruction=None):
            raise httpx.HTTPError(msg)
        return _raiser

    print("  (streaming path: chat, swipe, continue, ooc)")
    main.stream_response = raise_http("boom-chat")
    before = log_tail()
    chat_err_sid = dbmod.new_session(conn, title="(untitled)")
    drive(conn, chat_err_sid, "/tools off\nhello\n/q\n")
    new = log_tail()[len(before):]
    ok("an ordinary send's error names both the chat origin and its action",
       "chat" in new and "turn chat" in new, new)

    main.stream_response = lambda messages, model=None: (ANSWER, dict(USAGE), "")
    swipe_sid = dbmod.new_session(conn, title="(untitled)")
    drive(conn, swipe_sid, "/tools off\nhello\n/q\n")
    main.stream_response = raise_http("boom-swipe")
    before = log_tail()
    drive(conn, swipe_sid, "/tools off\n/swipe\n/q\n")
    new = log_tail()[len(before):]
    ok("a /swipe's error names both the chat origin and swipe",
       "chat" in new and "turn swipe" in new, new)

    main.stream_response = lambda messages, model=None: (ANSWER, dict(USAGE), "")
    cont_err_sid = dbmod.new_session(conn, title="(untitled)")
    drive(conn, cont_err_sid, "/tools off\nhello\n/q\n")
    main.stream_response = raise_http("boom-continue")
    before = log_tail()
    drive(conn, cont_err_sid, "/tools off\n/continue\n/q\n")
    new = log_tail()[len(before):]
    ok("a /continue's error names both the chat origin and continue",
       "chat" in new and "turn continue" in new, new)

    main.stream_response = raise_http("boom-ooc")
    before = log_tail()
    ooc_err_sid = dbmod.new_session(conn, title="(untitled)")
    drive(conn, ooc_err_sid, "/tools off\n((be gentler))\n/q\n")
    new = log_tail()[len(before):]
    ok("an OOC turn's error names both the chat origin and ooc",
       "chat" in new and "turn ooc" in new, new)

    print("  (tool path: the other exception site tags kind the same way)")
    main.stream_response = lambda messages, model=None: (ANSWER, dict(USAGE), "")
    agent.call_api = lambda messages, model=None, tools=None: {
        "choices": [{"message": {"role": "assistant", "content": ANSWER}}],
        "usage": dict(USAGE),
    }
    main.agent_turn = agent.agent_turn

    main.agent_turn = raise_http_tools("boom-chat-tools")
    before = log_tail()
    chat_tool_sid = dbmod.new_session(conn, title="(untitled)")
    drive(conn, chat_tool_sid, "hello\n/q\n")
    new = log_tail()[len(before):]
    ok("tool path: an ordinary send's error names chat and its action",
       "chat" in new and "turn chat" in new, new)

    main.agent_turn = lambda *a, **k: {"content": ANSWER}
    swipe_tool_sid = dbmod.new_session(conn, title="(untitled)")
    drive(conn, swipe_tool_sid, "hello\n/q\n")
    main.agent_turn = raise_http_tools("boom-swipe-tools")
    before = log_tail()
    drive(conn, swipe_tool_sid, "/swipe\n/q\n")
    new = log_tail()[len(before):]
    ok("tool path: a /swipe's error names chat and swipe",
       "chat" in new and "turn swipe" in new, new)

    main.agent_turn = lambda *a, **k: {"content": ANSWER}
    main.stream_response = lambda messages, model=None: (ANSWER, dict(USAGE), "")

    print("\n--- W-10: /title <id> <new title> shares commands.rename_chat "
          "with the hub's 'r' ---")
    driver_sid = dbmod.new_session(conn, title="driver")

    title_sid = dbmod.new_session(conn, title="before")
    out, _ = drive(conn, driver_sid, f"/title {title_sid} after\n/q\n")
    ok("/title <id> <new title> renames through the shared operation",
       dbmod.get_session_title(conn, title_sid) == "after",
       dbmod.get_session_title(conn, title_sid))
    ok("...reporting the exact wording rename_chat prints",
       f'Renamed chat #{title_sid}: "before" -> "after"' in out, out)

    main_sid, _ = dbmod.get_or_create_main(conn, "muse.md", "hi")
    out, _ = drive(conn, driver_sid, f"/title {main_sid} renamed?\n/q\n")
    ok("/title refuses Main through the same operation the hub's 'r' uses",
       "Main can't be renamed" in out, out)
    ok("...untouched",
       dbmod.get_session_title(conn, main_sid) == dbmod.MAIN_TITLE)

    wiki_sid = dbmod.new_session(conn, title="a wiki page",
                                 provider=dbmod.PROVIDER_WIKI)
    out, _ = drive(conn, driver_sid, f"/title {wiki_sid} renamed?\n/q\n")
    ok("/title refuses a wiki row the same way 'r' does",
       "isn't a chat" in out, out)
    ok("...untouched",
       dbmod.get_session_title(conn, wiki_sid) == "a wiki page")

    routine_sid = dbmod.new_session(conn, title="a routine run",
                                    provider=dbmod.PROVIDER_ROUTINE)
    out, _ = drive(conn, driver_sid, f"/title {routine_sid} renamed?\n/q\n")
    ok("/title refuses a routine transcript the same way 'r' does",
       "isn't a chat" in out, out)
    ok("...untouched",
       dbmod.get_session_title(conn, routine_sid) == "a routine run")

    missing_id = 999999
    out, _ = drive(conn, driver_sid, f"/title {missing_id} renamed?\n/q\n")
    ok("/title refuses a missing id the same way 'r' does",
       f"No session #{missing_id}." in out, out)

    print("\n--- W-1.6.4-05: a wiki page and a routine transcript open "
          "through the same run_session path, take a continuation, never "
          "re-title and never rerun a routine ---")
    import runner as _runner
    routine_calls = []

    def _spy_run_routine(*a, **k):
        routine_calls.append((a, k))
        raise AssertionError(
            "run_routine must never be called from an opened chat turn")

    real_run_routine = _runner.run_routine
    _runner.run_routine = _spy_run_routine
    try:
        wiki_sid2 = dbmod.new_session(conn, title="a wiki page",
                                      provider=dbmod.PROVIDER_WIKI)
        dbmod.save_message(conn, wiki_sid2, "user", "the imported page content")
        out, _ = drive(conn, wiki_sid2, "/tools off\na typed continuation\n/q\n")
        ok("the wiki notice prints on open",
           "Wiki page" in out and "does not edit the vault page" in out, out)
        ok("the continuation persists as an ordinary reply",
           any(r[1] == "a typed continuation" for r in
               conn.execute("SELECT role, content FROM messages WHERE "
                            "session_id=?", (wiki_sid2,)).fetchall()))
        ok("opening and chatting in it never re-titles the page",
           dbmod.get_session_title(conn, wiki_sid2) == "a wiki page",
           dbmod.get_session_title(conn, wiki_sid2))

        routine_sid2 = dbmod.new_session(conn, title="routine: Nightly",
                                         provider=dbmod.PROVIDER_ROUTINE)
        dbmod.save_message(conn, routine_sid2, "assistant", "the routine's own answer")
        out, _ = drive(conn, routine_sid2, "/tools off\na typed continuation\n/q\n")
        ok("the routine-transcript notice prints on open",
           "Routine transcript" in out and "does not run the routine again" in out,
           out)
        ok("the continuation persists as an ordinary reply",
           any(r[1] == "a typed continuation" for r in
               conn.execute("SELECT role, content FROM messages WHERE "
                            "session_id=?", (routine_sid2,)).fetchall()))
        ok("opening and chatting in it never re-titles the transcript",
           dbmod.get_session_title(conn, routine_sid2) == "routine: Nightly",
           dbmod.get_session_title(conn, routine_sid2))
        ok("neither session ever reached run_routine",
           routine_calls == [], routine_calls)
    finally:
        _runner.run_routine = real_run_routine

    print("\n--- W-1.9-01c: a wiki session's opening notice and bare "
          "/status name the same resolved source file, live rather than "
          "stored ---")
    wiki_dir = Path(tempfile.mkdtemp(prefix="wiki-source-live-"))
    (wiki_dir / "original-name.md").write_text(
        "---\nid: 20260101000099\ntitle: Live Source Test\n---\n"
        "some real content, long enough to import.\n", encoding="utf-8")
    import_wiki.run_import(str(wiki_dir), str(dbmod.DB_PATH))
    live_wiki_sid = conn.execute(
        "SELECT id FROM sessions WHERE provider=? AND source_uuid=?",
        (dbmod.PROVIDER_WIKI, "20260101000099")).fetchone()[0]

    real_wiki_dir_fn = wikigit.wiki_dir
    wikigit.wiki_dir = lambda: wiki_dir
    try:
        out, _ = drive(conn, live_wiki_sid, "/status\n/q\n")
        ok("the opening notice names the file it was actually imported "
           "under", "original-name.md" in out, out)
        ok("...and bare /status's Wiki source row names the same file, "
           "not a second, disagreeing parse",
           out.count("original-name.md") >= 2, out)

        # The identity is the frontmatter id (standing decision 9), not the
        # filename — renaming the file on disk with the id untouched must
        # still resolve, live, to the new name on the *next* open, without
        # anything having been written back to the stored session.
        (wiki_dir / "original-name.md").rename(wiki_dir / "renamed-name.md")
        out2, _ = drive(conn, live_wiki_sid, "/status\n/q\n")
        ok("a rename with no id change is picked up live on reopen",
           "renamed-name.md" in out2 and "original-name.md" not in out2,
           out2)
        ok("...named identically by the notice and by /status",
           out2.count("renamed-name.md") >= 2, out2)
    finally:
        wikigit.wiki_dir = real_wiki_dir_fn

    print("\n--- W-1.6.4-04: /status request shows the real captured wire "
          "bodies ---")
    # The real stream_response/call_api, restored — every other scenario in
    # this file stubs one or both away, which is exactly what would make the
    # capture invisible: it fires inside api.py's own payload construction,
    # immediately before handing it to httpx, never at the call_api/
    # stream_response boundary a caller can replace. Faked one level lower
    # instead, at httpx.Client itself, the same technique test_agent.py uses
    # for the same reason.
    real_stream_response, real_call_api = api.stream_response, api.call_api
    real_generate_title = api.generate_title
    # The D-17 section just above leaves `main.agent_turn` permanently
    # stubbed (its last reassignment, line ~805) — restore the real one so
    # the tool-turn scenario below actually reaches `agent.call_api`.
    main.agent_turn = agent.agent_turn

    class _FakeErrorResponse:
        def __init__(self, status_code, body):
            self.is_error = True
            self.status_code = status_code
            self.text = body
            class _Req:
                url = "http://fake.test/chat/completions"
            self.request = _Req()

        def json(self):
            raise ValueError("not json")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            pass

    class _FakeStreamResponse:
        def __init__(self, content, prompt_tokens=10, completion_tokens=5):
            self.is_error = False
            self._lines = [
                "data: " + json.dumps(
                    {"choices": [{"delta": {"content": content}}]}),
                "data: " + json.dumps({"usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens}}),
                "data: [DONE]",
            ]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self):
            return iter(self._lines)

        def read(self):
            pass

    _post_script = []
    _stream_script = []

    class _FakeHTTPXClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers=None, json=None):
            item = _post_script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        def stream(self, method, url, headers=None, json=None):
            item = _stream_script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    def _reply(content=None, calls=None):
        msg = {"role": "assistant", "content": content}
        if calls:
            msg["tool_calls"] = [
                {"id": f"call_{i}", "type": "function",
                 "function": {"name": n, "arguments": json.dumps(a)}}
                for i, (n, a) in enumerate(calls)]
        return type("R", (), {
            "is_error": False,
            "json": lambda self, msg=msg: {
                "choices": [{"message": msg}], "usage": USAGE},
        })()

    main.stream_response = real_stream_response
    agent.call_api = real_call_api
    main.generate_title = real_generate_title
    real_httpx_client = api.httpx.Client
    api.httpx.Client = _FakeHTTPXClient
    try:
        print("  (streaming turn: one captured body, and a title attempt "
              "right after it cannot replace it)")
        stream_sid = dbmod.new_session(conn, title="(untitled)")
        _post_script[:] = [_reply("A Title")]
        _stream_script[:] = [_FakeStreamResponse("a real streamed answer")]
        out, _ = drive(conn, stream_sid,
                       "/tools off\nhello\n/status request\n/q\n")
        ok("exactly one body captured for a plain streaming turn",
           "Call 1 of 1" in out and "Call 2" not in out, out)
        ok("the captured body is the real wire shape",
           '"stream": true' in out and '"hello"' in out, out)
        ok("the title's own call never joined the capture",
           '"A Title"' not in out, out)

        print("  (a second turn on the same session replaces the capture, "
              "not adds to it)")
        _post_script[:] = [_reply("Should Not Land As A New Title")]
        _stream_script[:] = [_FakeStreamResponse("a second real answer")]
        out, _ = drive(conn, stream_sid,
                       "/tools off\nsecond message\n/status request\n/q\n")
        # A growing conversation legitimately carries "hello" forward inside
        # the second turn's own request `messages` — that's real history,
        # not a leftover capture. What proves the *capture* was reset rather
        # than appended to is the call count: one body, not two, even though
        # this is the session's second attempted turn.
        request_json = out.rsplit("Call 1 of 1", 1)[-1]
        ok("exactly one body captured, replacing the first turn's",
           out.count("Call 1 of 1") == 1 and "Call 2" not in out, out)
        ok("the captured body is this turn's request",
           '"second message"' in request_json, request_json)

        print("  (a multi-call tool turn: order, and every body shown, not "
              "a reconstructed final one)")
        tool_sid = dbmod.new_session(conn, title="(untitled)")
        _post_script[:] = [
            _reply(None, calls=[("list_dir", {"path": "/tmp"})]),
            _reply("done after one tool round trip"),
        ]
        out, _ = drive(conn, tool_sid,
                       "please read the directory\n/status request\n/q\n")
        ok("both calls captured", "Call 1 of 2" in out and "Call 2 of 2" in out,
           out)
        ok("...in order",
           "Call 1 of 2" in out and "Call 2 of 2" in out
           and out.index("Call 1 of 2") < out.index("Call 2 of 2"), out)
        ok("both calls still offered tools (budget not spent)",
           out.count('"tools":') == 2, out)
        ok("the second call's messages carry the first call's tool result, "
           "not just the final answer",
           '"role": "tool"' in out, out)

        print("  (an oversize refusal leaves the capture empty)")
        oversize_sid = dbmod.new_session(conn, title="(untitled)")
        saved_models = models.MODELS
        models.MODELS = [models._spec(MODEL, tools=True, limit=1)]
        try:
            out, _ = drive(conn, oversize_sid,
                           "a message that is now oversize\n"
                           "/status request\n/q\n")
        finally:
            models.MODELS = saved_models
        ok("no provider request was sent for an oversize-refused turn",
           "No provider request was sent" in out, out)

        print("  (a pre-network 400 still leaves the attempted request "
              "inspectable)")
        err_sid = dbmod.new_session(conn, title="(untitled)")
        _stream_script[:] = [_FakeErrorResponse(400, "provider says no")]
        out, _ = drive(conn, err_sid,
                       "/tools off\nthis will 400\n/status request\n/q\n")
        ok("the failed turn's own request is still shown",
           "Call 1 of 1" in out and '"this will 400"' in out, out)
    finally:
        api.httpx.Client = real_httpx_client

    # --- Work Order.md v1.9: discard only a known untouched automatic ---
    # --- chat on its controlled exit ------------------------------------
    #
    # `main._provisional` is process-local, so these tests drive it the same
    # way hub 'n' and bare '/new' do — `main._mark_provisional` — rather than
    # going through `main.repl()`'s hub loop, which nothing else in this file
    # exercises either. `drive()` still runs the real `run_session` and the
    # real `db.discard_provisional_chat` boundary; only the provider is ever
    # stubbed (this file's own rule, stated at the top).
    print("\n--- discard: a marked row is removed on its own controlled "
          "exit ---")
    # A fresh provider stub, un-scripted: every scenario below either sends
    # no turn at all or is asserting that a real turn *blocks* the discard,
    # never that one succeeds.
    main.stream_response = lambda messages, model=None: (ANSWER, dict(USAGE), "")
    main.set_process_model(MODEL)

    def _fresh_provisional():
        sid = dbmod.new_session(conn, title="(untitled)", model=MODEL)
        main._mark_provisional(sid, MODEL)
        return sid

    sid_q = _fresh_provisional()
    out, _ = drive(conn, sid_q, "/q\n")
    ok("/q discards an untouched marked row",
       f"Discarded empty chat #{sid_q}." in out, out)
    ok("...and it's really gone",
       conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid_q,)).fetchone()
       is None)

    sid_eof = _fresh_provisional()
    out, _ = drive(conn, sid_eof, "")   # empty stdin: read_input hits EOF at once
    ok("EOF discards an untouched marked row",
       f"Discarded empty chat #{sid_eof}." in out, out)
    ok("...and it's really gone",
       conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid_eof,)).fetchone()
       is None)

    print("\n--- discard: bare /new discards the row it replaces, and the "
          "replacement becomes the next provisional row ---")
    sid_a = _fresh_provisional()
    # Only "/new\n" is scripted. Its own EOF right afterwards is not a second
    # scenario stitched on for convenience — it's what proves B, not just A,
    # is now marked: nothing but the provisional record makes an empty,
    # unmodified row eligible for this, so B being gone by the end is B
    # having been marked, not a coincidence of also being empty.
    out, _ = drive(conn, sid_a, "/new\n")
    ok("bare /new discards the row it replaces",
       f"Discarded empty chat #{sid_a}." in out, out)
    ok("...and it's really gone",
       conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid_a,)).fetchone()
       is None)
    started = out.rsplit("Started session #", 1)[-1].split()[0].rstrip(".")
    sid_b = int(started)
    ok("the replacement is a different row", sid_b != sid_a, (sid_a, sid_b))
    ok("...and it was itself discarded at the EOF right after",
       f"Discarded empty chat #{sid_b}." in out, out)
    ok("...gone too",
       conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid_b,)).fetchone()
       is None)

    print("\n--- discard: entering a command screen discards first ---")
    sid_screen = _fresh_provisional()
    real_screens_enter = main.screens.enter
    # The screen controller's own behaviour is screens.py's business (see
    # tests/test_screens.py) — patched at the seam `_enter_screens` calls
    # through, the same rule this file states for the provider ("Only the
    # provider is stubbed"), applied to the one other subsystem a scenario
    # here needs to cross without re-testing it.
    main.screens.enter = lambda *a, **k: None
    try:
        out, _ = drive(conn, sid_screen, "/config\n")
    finally:
        main.screens.enter = real_screens_enter
    ok("entering a screen discards the marked row first",
       f"Discarded empty chat #{sid_screen}." in out, out)
    ok("...and it's really gone",
       conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid_screen,)
                    ).fetchone() is None)

    print("\n--- discard: a nested private chat's screen bubbling a "
          "session id counts as this row's own departure too ---")
    sid_outer = _fresh_provisional()
    real_screens_enter = main.screens.enter
    # Any non-None return from screens.enter reads as "a screen asked to
    # open this session id" to `_enter_screens` — the value itself is never
    # opened by this test, so an arbitrary sentinel proves the plumbing
    # without needing a real routine transcript to exist.
    main.screens.enter = lambda *a, **k: 424242
    try:
        out, _ = drive(conn, sid_outer, "/new p\n/config\n")
    finally:
        main.screens.enter = real_screens_enter
    ok("the outer row is discarded once the nested private chat's screen "
       "bubbles an outcome up",
       f"Discarded empty chat #{sid_outer}." in out, out)
    ok("...and it's really gone",
       conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid_outer,)
                    ).fetchone() is None)

    print("\n--- discard: forcing an index-delete failure keeps the row, "
          "rolls back, and reports loudly (verify the guard by disabling "
          "it) ---")
    sid_fail = _fresh_provisional()
    import chunk as chunkmod
    import sqlite_vec
    chunkmod.ensure_table(conn, rebuild=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
                "chunk_id integer primary key, embedding float[4])")
    # A chunk with no message, pointed at this session directly — the same
    # shape `_delete_session_cascade`'s own comment names as how an orphan
    # first happens, used here on purpose so there is something in the
    # index for the forced failure to leave behind.
    cur = conn.execute(
        "INSERT INTO chunks (message_id,session_id,kind,ordinal,text,"
        "token_est,source) VALUES (NULL,?,'message',0,'ghost',1,'chat')",
        (sid_fail,))
    ghost_cid = cur.lastrowid
    conn.execute("INSERT INTO vec_chunks (chunk_id,embedding) VALUES (?,?)",
                (ghost_cid, sqlite_vec.serialize_float32([0.1, 0.2, 0.3, 0.4])))
    conn.commit()
    real_drop_chunks = dbmod.drop_chunks
    dbmod.drop_chunks = lambda conn, ids: (_ for _ in ()).throw(
        RuntimeError("simulated index failure"))
    try:
        out, _ = drive(conn, sid_fail, "/q\n")
    finally:
        dbmod.drop_chunks = real_drop_chunks
    ok("a forced index failure never claims success",
       f"Discarded empty chat #{sid_fail}." not in out, out)
    ok("...and visibly reports the failure instead",
       "cleanup failed" in out and str(sid_fail) in out, out)
    ok("the session row survives — retained, not half-deleted",
       conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid_fail,)
                    ).fetchone() is not None)
    ok("the ghost chunk survives too — rolled back, not half-deleted",
       conn.execute("SELECT 1 FROM chunks WHERE id=?", (ghost_cid,)
                    ).fetchone() is not None)
    ok("...and its vector",
       conn.execute("SELECT 1 FROM vec_chunks WHERE chunk_id=?",
                    (ghost_cid,)).fetchone() is not None)

    print("\n--- keepers: a chosen id is never marked, even though it "
          "still discards the provisional row it replaces ---")
    sid_old = _fresh_provisional()
    out, _ = drive(conn, sid_old, "/new 55501\n/q\n")
    ok("the old provisional row is discarded when a chosen id replaces it",
       f"Discarded empty chat #{sid_old}." in out, out)
    ok("...and it's gone",
       conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid_old,)
                    ).fetchone() is None)
    ok("the chosen-id row itself is never discarded, empty or not",
       "Discarded empty chat #55501" not in out, out)
    ok("...it survives",
       conn.execute("SELECT 1 FROM sessions WHERE id=?", (55501,)
                    ).fetchone() is not None)

    print("\n--- keeper: a resumed row that was never marked is never "
          "auto-discarded, even when it's empty ---")
    main._provisional = None
    sid_resumed = dbmod.new_session(conn, title="(untitled)", model=MODEL)
    out, _ = drive(conn, sid_resumed, "/q\n")
    ok("no discard line for an unmarked, resumed row",
       "Discarded empty chat" not in out, out)
    ok("...it survives",
       conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid_resumed,)
                    ).fetchone() is not None)

    print("\n--- keepers: any one real difference from the opening "
          "snapshot blocks the discard ---")

    def _keeper(label, mutate):
        sid = _fresh_provisional()
        mutate(sid)
        out, _ = drive(conn, sid, "/q\n")
        ok(f"keeper — {label}: not discarded",
           "Discarded empty chat" not in out, out)
        ok(f"keeper — {label}: the row survives",
           conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)
                        ).fetchone() is not None)

    _keeper("a chat message",
            lambda sid: dbmod.save_message(conn, sid, "user", "hi",
                                           kind="chat"))
    _keeper("a non-chat message row (an attachment)",
            lambda sid: dbmod.save_message(conn, sid, "user", "x",
                                           kind="attachment"))
    _keeper("a frozen First Message",
            lambda sid: dbmod.set_first_message(conn, sid, "muse.md",
                                                "Good morning."))
    _keeper("a changed title",
            lambda sid: dbmod.set_session_title(conn, sid, "renamed"))
    _keeper("a tag",
            lambda sid: dbmod.add_tag(conn, sid, "sometag"))
    _keeper("an attached prompt",
            lambda sid: dbmod.set_system_prompt(conn, sid, "body",
                                                "formal.md"))
    _keeper("an attached persona",
            lambda sid: dbmod.set_persona(conn, sid, "body", "muse.md"))
    _keeper("an attached trait",
            lambda sid: dbmod.set_traits(conn, sid, ["relax"]))

    # The model column is re-synced to the process selection on every open
    # (`W-1.3.1-03`), so a direct write would be overwritten before the
    # discard check ever ran — a real customisation here is a `/model`
    # switch made *before* departure, exactly what this reproduces.
    sid_model = _fresh_provisional()
    main.set_process_model("a-model-the-snapshot-never-saw")
    try:
        out, _ = drive(conn, sid_model, "/q\n")
    finally:
        main.set_process_model(MODEL)
    ok("keeper — a model switch before departure: not discarded",
       "Discarded empty chat" not in out, out)
    ok("keeper — a model switch before departure: the row survives",
       conn.execute("SELECT 1 FROM sessions WHERE id=?", (sid_model,)
                    ).fetchone() is not None)

    conn.close()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
