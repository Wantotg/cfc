#!/usr/bin/env python3
"""
test_first_message.py — the frozen opening a persona may carry (1.3).

    python3 tests/test_first_message.py

The db-level plumbing (columns, get/set, has_chat_messages,
count_chat_user_turns) is pinned in tests/test_schema.py; the loader
(pools.load_first_message) in tests/test_pools.py; the request envelope in
tests/test_governor.py; and private-chat isolation in tests/test_private.py.
This file is what's left: the session-open behaviour that makes it a visible
frozen assistant turn rather than a database column nobody sees —

  * a persona with a matching companion, attached in an empty session, opens
    with it
  * an existing conversation never gains one retroactively
  * an edit to the companion file changes only a *new* session's opening; an
    existing session keeps the words it actually opened with
  * it is shown again on every reopen
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

import db as dbmod
import main
import pools

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def drive(conn, sid, keys):
    out = io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(keys)
    try:
        with contextlib.redirect_stdout(out):
            main.console.file = out
            main.run_session(conn, sid, private=False)
    finally:
        sys.stdin = real_stdin
        main.console.file = sys.stdout
    return out.getvalue()


def main_():
    tmp = Path(tempfile.mkdtemp())
    assert "tmp" in str(tmp), "refusing to touch a real db"
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()

    persona_dir = Path(tempfile.mkdtemp())
    fm_dir = Path(tempfile.mkdtemp())
    (persona_dir / "muse.md").write_text("You are Muse.\n", encoding="utf-8")
    (fm_dir / "muse.md").write_text("Good morning — where should we start?\n",
                                    encoding="utf-8")
    saved_persona_dir = pools.POOLS["persona"].configured
    saved_fm_dir = pools.FIRST_MESSAGES_DIR
    pools.POOLS["persona"].configured = str(persona_dir)
    pools.FIRST_MESSAGES_DIR = str(fm_dir)

    main.stream_response = lambda messages, model=None: (
        "an answer", {"prompt_tokens": 3, "completion_tokens": 2}, "")
    main.generate_title = lambda *a, **k: "(untitled)"
    main.auto_embed = lambda: None
    main.AUTO_EXPORT = False

    try:
        print("--- attaching a persona with a companion opens with it ---")
        sid = dbmod.new_session(conn, title="fresh")
        out = drive(conn, sid, "/add persona muse\n/q\n")
        ok("the opening text is rendered",
           "Good morning — where should we start?" in out, out)
        snap = dbmod.get_first_message(conn, sid)
        ok("the snapshot is frozen onto the session",
           snap is not None and snap["name"] == "muse.md", snap)
        ok("it is not a messages row",
           conn.execute(
               "SELECT COUNT(*) FROM messages WHERE session_id=? AND "
               "content LIKE '%where should we start%'",
               (sid,)).fetchone()[0] == 0)

        print("\n--- it is shown again on every reopen ---")
        out2 = drive(conn, sid, "/q\n")
        ok("reopening renders the same frozen text",
           "Good morning — where should we start?" in out2, out2)

        print("\n--- editing the companion changes only a NEW session ---")
        (fm_dir / "muse.md").write_text("A completely different opening.\n",
                                        encoding="utf-8")
        out3 = drive(conn, sid, "/q\n")
        ok("the existing session keeps the words it actually opened with",
           "Good morning — where should we start?" in out3
           and "A completely different opening." not in out3, out3)

        new_sid = dbmod.new_session(conn, title="fresh-two")
        out4 = drive(conn, new_sid, "/add persona muse\n/q\n")
        ok("a brand new session gets the edited text",
           "A completely different opening." in out4, out4)
        ok("...not the old one", "where should we start" not in out4, out4)

        print("\n--- no retroactive opening for a non-empty chat ---")
        chatty_sid = dbmod.new_session(conn, title="already talking")
        drive(conn, chatty_sid, "hello there\n/q\n")   # one ordinary turn first
        out5 = drive(conn, chatty_sid, "/add persona muse\n/q\n")
        ok("attaching a persona to a chat that already has turns opens "
           "nothing retroactively",
           "A completely different opening." not in out5
           and "where should we start" not in out5, out5)
        ok("...and no snapshot was frozen",
           dbmod.get_first_message(conn, chatty_sid) is None)

        print("\n--- absent vs unreadable companions ---")
        empty_sid = dbmod.new_session(conn, title="no-companion")
        (persona_dir / "silent.md").write_text("You are Silent.\n",
                                                encoding="utf-8")
        out6 = drive(conn, empty_sid, "/add persona silent\n/q\n")
        ok("a persona with no companion file attaches normally, silently",
           "added silent" in out6 and "unavailable" not in out6.lower(), out6)
        ok("...and no snapshot exists",
           dbmod.get_first_message(conn, empty_sid) is None)

        broken_sid = dbmod.new_session(conn, title="broken-companion")
        (fm_dir / "broken.md").mkdir()   # a directory where a file belongs
        (persona_dir / "broken.md").write_text("You are Broken.\n",
                                               encoding="utf-8")
        out7 = drive(conn, broken_sid, "/add persona broken\n/q\n")
        ok("an unreadable companion is a visible failure, not silence",
           "First Message unavailable" in out7, out7)
        ok("...but the persona itself still attached",
           "added broken" in out7, out7)
    finally:
        pools.POOLS["persona"].configured = saved_persona_dir
        pools.FIRST_MESSAGES_DIR = saved_fm_dir

    conn.close()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
