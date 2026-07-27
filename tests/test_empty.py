#!/usr/bin/env python3
"""
test_empty.py — what happens when the model returns nothing. No API calls.

    python3 tests/test_empty.py

Thinking models return the occasional empty completion: a handful of tokens,
`finish_reason=stop`, no content. A provider hiccup rather than a size limit —
the same context usually answers on a re-roll.

Who decides whether to re-roll depends on whether anyone is there, and that is
the whole job of `ToolContext.interactive`. With a human at a terminal, ask.
Driven from a pipe or a scheduler, asking means blocking on a keypress that
never comes, so re-roll a bounded number of times and then give up loudly.

The routine half of this lives in test_routines.py, where the failure was
sharper: an empty completion used to be logged as a successful run.
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

import context
import db as dbmod
import main

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def main_():
    tmp = Path(tempfile.mkdtemp())
    # Invariant #1: assert the path BEFORE anything writes to it. A guard that
    # ran after its destructive step once deleted the real database.
    assert "tmp" in str(tmp) and not str(tmp).startswith(
        str(Path("~/.cfc").expanduser())), "refusing to touch a real db"
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()
    sid = dbmod.new_session(conn, title="t")

    calls = []
    real_stream = main.stream_response

    def empty_stream(messages, model=None):
        calls.append(1)
        return "", {}, ""

    def drive(interactive, keys):
        """Run one session to completion with a stubbed, always-empty stream.

        '/tools off' comes first in every script: the session defaults to
        tools ON, which takes agent_turn instead of the streaming path and
        never reaches the handler under test. That cost a confusing round of
        "why is this zero attempts".
        """
        calls.clear()
        main.stream_response = empty_stream
        main.chat_context = lambda private=False: context.ToolContext.for_chat(
            read_roots=(tmp,), interactive=interactive)
        out = io.StringIO()
        real_stdin = sys.stdin
        sys.stdin = io.StringIO(keys)
        try:
            with contextlib.redirect_stdout(out):
                main.console.file = out
                main.run_session(conn, sid)
        finally:
            sys.stdin = real_stdin
            main.stream_response = real_stream
        return len(calls), out.getvalue()

    expected = main.EMPTY_COMPLETION_RETRIES + 1

    print("\n--- no human: re-roll a bounded number of times, then give up ---")
    n, out = drive(False, "/tools off\nhello\n/q\n")
    ok(f"tries {expected} times in total", n == expected, n)
    ok("says why it is retrying", "no human to ask" in out, out[-400:])
    ok("gives up loudly rather than silently", "gave up after" in out,
       out[-400:])
    ok("never asks a question nobody can answer", "retry?" not in out)
    ok("the empty answer is not persisted",
       conn.execute("SELECT COUNT(*) FROM messages WHERE role='assistant' "
                    "AND TRIM(content)=''").fetchone()[0] == 0)

    print("\n--- a human: ask, and honour the answer ---")
    n, out = drive(True, "/tools off\nhello\ny\nn\n/q\n")
    ok("asks the human", "retry?" in out)
    ok("'y' re-rolls once, 'n' stops", n == 2, n)
    ok("...and does not use the unattended path",
       "no human to ask" not in out)

    n, _ = drive(True, "/tools off\nhello\nn\n/q\n")
    ok("an immediate 'n' costs exactly one call", n == 1, n)

    n, out = drive(True, "/tools off\nhello\n")
    ok("EOF at the prompt is read as 'no', not a crash", n == 1, n)

    print("\n--- the bound is the constant, not a magic number ---")
    saved = main.EMPTY_COMPLETION_RETRIES
    try:
        main.EMPTY_COMPLETION_RETRIES = 4
        n, _ = drive(False, "/tools off\nhello\n/q\n")
        ok("raising the constant raises the attempts", n == 5, n)
        main.EMPTY_COMPLETION_RETRIES = 0
        n, _ = drive(False, "/tools off\nhello\n/q\n")
        ok("zero retries means one attempt", n == 1, n)
    finally:
        main.EMPTY_COMPLETION_RETRIES = saved

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
