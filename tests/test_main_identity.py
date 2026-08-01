#!/usr/bin/env python3
"""test_main_identity.py — Main's one durable database identity (db.py).
No network.

    python3 tests/test_main_identity.py

Main is an ordinary chat-shaped `sessions` row with `provider='main'`, a
fixed title, and its frozen First Message in the existing snapshot columns.
What's worth pinning here, separately from the profile loader
(tests/test_mainchat.py) and the hub/turn wiring (tests/test_hub.py,
tests/test_mainchat_turns.py): the get-or-create operation itself, the
database's own uniqueness guard, and that a Main row rides the existing
delete/index-cleanup machinery rather than a second path.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import db as dbmod

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def main_():
    tmp = Path(tempfile.mkdtemp())
    assert "tmp" in str(tmp), "refusing to touch a real db"
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()

    print("--- the migration creates the singleton index idempotently ---")
    # db() runs its schema/migration block on every connect; reconnecting
    # must not raise on the second CREATE UNIQUE INDEX IF NOT EXISTS.
    conn.close()
    conn = dbmod.db()
    ok("reconnecting is a no-op, not an error", True)

    print("\n--- first creation ---")
    ok("no Main row yet", dbmod.main_session_id(conn) is None)
    sid, created = dbmod.get_or_create_main(
        conn, "main", "Hello — where should we start?")
    ok("the first call creates a row", created, (sid, created))
    ok("the row has the fixed title",
       dbmod.get_session_title(conn, sid) == dbmod.MAIN_TITLE,
       dbmod.get_session_title(conn, sid))
    ok("the row carries the Main provider",
       dbmod.get_session_provider(conn, sid) == dbmod.PROVIDER_MAIN,
       dbmod.get_session_provider(conn, sid))
    fm = dbmod.get_first_message(conn, sid)
    ok("the First Message is frozen onto the row",
       fm is not None and fm["text"] == "Hello — where should we start?", fm)

    print("\n--- repeat get-or-create reopens, never re-creates ---")
    sid2, created2 = dbmod.get_or_create_main(conn, "main", "a different text")
    ok("the same row comes back", sid2 == sid, (sid2, sid))
    ok("created is False on reopen", created2 is False, created2)
    fm2 = dbmod.get_first_message(conn, sid2)
    ok("the frozen opening is untouched by a reopen's own arguments",
       fm2["text"] == "Hello — where should we start?", fm2)
    ok("main_session_id agrees", dbmod.main_session_id(conn) == sid,
       dbmod.main_session_id(conn))

    print("\n--- the database enforces uniqueness itself ---")
    # Bypass get_or_create_main entirely and try to insert a second 'main'
    # row directly — the partial unique index must refuse it regardless of
    # which code path attempts the insert. Verified by disabling the guard's
    # own caller and hitting the constraint straight on.
    try:
        conn.execute(
            "INSERT INTO sessions(title, provider, created_at, updated_at) "
            "VALUES ('Main', 'main', 'x', 'x')")
        ok("a second insert raises IntegrityError", False)
    except sqlite3.IntegrityError:
        ok("a second insert raises IntegrityError", True)
    conn.rollback()

    print("\n--- a hand-made duplicate is reported as corruption ---")
    # Two Main rows can only exist by going around the index (a hand-edited
    # or pre-migration database) — build that state directly and confirm
    # lookup refuses to pick one rather than silently choosing.
    corrupt = dbmod.db(":memory:")
    corrupt.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_main_singleton "
        "ON sessions(provider) WHERE provider='main'")
    # Two independent inserts before the index exists on this connection's
    # data — simulate by dropping the index, inserting twice, no re-add.
    corrupt.execute("DROP INDEX idx_sessions_main_singleton")
    corrupt.execute(
        "INSERT INTO sessions(title, provider, created_at, updated_at) "
        "VALUES ('Main', 'main', 'x', 'x')")
    corrupt.execute(
        "INSERT INTO sessions(title, provider, created_at, updated_at) "
        "VALUES ('Main', 'main', 'y', 'y')")
    corrupt.commit()
    try:
        dbmod.main_session_id(corrupt)
        ok("main_session_id refuses two rows", False)
    except dbmod.MainCorruption:
        ok("main_session_id refuses two rows", True)
    try:
        dbmod.get_or_create_main(corrupt, "main", "text")
        ok("get_or_create_main refuses two rows", False)
    except dbmod.MainCorruption:
        ok("get_or_create_main refuses two rows", True)
    corrupt.close()

    print("\n--- deletion followed by one fresh creation ---")
    dbmod.delete_session(conn, sid)
    ok("Main is gone after delete", dbmod.main_session_id(conn) is None)
    ok("...and the ordinary sessions row is really gone",
       conn.execute("SELECT COUNT(*) FROM sessions WHERE id=?",
                    (sid,)).fetchone()[0] == 0)
    new_sid, created3 = dbmod.get_or_create_main(
        conn, "main", "A brand new opening.")
    # SQLite reuses a freed low rowid (HANDOVER's "Scars" note on this exact
    # behaviour), so new_sid may legitimately equal the old sid — the thing
    # worth pinning is that this is a genuine *creation*, not a reopen of
    # data that should have been gone.
    ok("the next get-or-create is a genuine first creation", created3,
       (created3, new_sid, sid))
    fm3 = dbmod.get_first_message(conn, new_sid)
    ok("...with the newly frozen opening",
       fm3["text"] == "A brand new opening.", fm3)

    print("\n--- Main rides the existing chat-shaped paths ---")
    dbmod.save_message(conn, new_sid, "user", "hello")
    dbmod.save_message(conn, new_sid, "assistant", "hi there")
    history = dbmod.load_history(conn, new_sid)
    ok("ordinary message save/load works on a Main row",
       [m["content"] for m in history] == ["hello", "hi there"], history)
    dbmod.add_tag(conn, new_sid, "test")
    ok("tags work on a Main row",
       dbmod.get_session_tags(conn, new_sid) == ["test"],
       dbmod.get_session_tags(conn, new_sid))
    dbmod.delete_session(conn, new_sid)
    ok("delete_session removes a Main row's messages too",
       conn.execute("SELECT COUNT(*) FROM messages WHERE session_id=?",
                    (new_sid,)).fetchone()[0] == 0)
    ok("...and no second Main-only deletion path was needed to get here",
       dbmod.main_session_id(conn) is None)

    conn.close()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
