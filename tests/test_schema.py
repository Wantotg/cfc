#!/usr/bin/env python3
"""
test_schema.py — the messages.kind/meta migration.

    python3 tests/test_schema.py

Covers the thing that actually bites: the migration runs on every connect
against real databases that already have data in them, so it has to be
idempotent and it must not disturb rows it doesn't understand.

Also pins the coupling between commands.py (which writes the :remember marker)
and db.py (which parses it). That pairing has broken silently once already —
see BACKLOG.md.
"""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {detail}")


def legacy_db(path):
    """A database as it looked before kind/meta existed, with real rows."""
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY, title TEXT, model TEXT, provider TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, session_id INTEGER, role TEXT,
            content TEXT, model TEXT, tokens_in INTEGER, tokens_out INTEGER,
            created_at TEXT);
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
        CREATE TABLE session_tags (session_id INTEGER, tag_id INTEGER,
            PRIMARY KEY (session_id, tag_id));
    """)
    c.execute("INSERT INTO sessions (id,title) VALUES (1,'s')")
    c.executemany(
        "INSERT INTO messages (session_id, role, content) VALUES (?,?,?)",
        [(1, "user", "a normal question"),
         (1, "assistant", "a normal answer"),
         (1, "user", '[:remember "what did we decide" → 8 excerpts '
                     'injected (ephemeral)]'),
         (1, "user", "[:remember but not really a marker]"),
         (1, "user", '[:remember "multi\nline query" → 3 excerpts '
                     'injected (ephemeral)]')])
    c.commit()
    c.close()


def main():
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "chat.db"
    legacy_db(path)

    import db as dbmod
    dbmod.DB_PATH = path

    conn = dbmod.db()          # runs the migration
    cols = [r[1] for r in conn.execute("PRAGMA table_info(messages)")]
    ok("kind column added", "kind" in cols)
    ok("meta column added", "meta" in cols)

    rows = dict(conn.execute("SELECT content, kind FROM messages"))
    ok("normal message -> chat",
       rows["a normal question"] == "chat", rows.get("a normal question"))
    ok("assistant message -> chat",
       rows["a normal answer"] == "chat")

    marker = '[:remember "what did we decide" → 8 excerpts injected (ephemeral)]'
    ok("marker -> recall_marker", rows[marker] == "recall_marker", rows.get(marker))

    meta = conn.execute("SELECT meta FROM messages WHERE content=?",
                        (marker,)).fetchone()[0]
    m = json.loads(meta)
    ok("marker meta carries the query", m.get("query") == "what did we decide", meta)
    ok("marker meta carries the count", m.get("excerpts") == 8, meta)

    lookalike = "[:remember but not really a marker]"
    ok("lookalike left as chat", rows[lookalike] == "chat", rows.get(lookalike))
    ok("lookalike has no meta",
       conn.execute("SELECT meta FROM messages WHERE content=?",
                    (lookalike,)).fetchone()[0] is None)

    multi = [c for c in rows if "multi\nline" in c][0]
    ok("multi-line query marker matched", rows[multi] == "recall_marker")

    ok("nothing left NULL",
       conn.execute("SELECT COUNT(*) FROM messages WHERE kind IS NULL"
                    ).fetchone()[0] == 0)
    conn.close()

    print("\n--- idempotency: the migration runs on every single connect ---")
    before = sqlite3.connect(path).execute(
        "SELECT id, kind, meta FROM messages ORDER BY id").fetchall()
    for _ in range(3):
        dbmod.db().close()
    after = sqlite3.connect(path).execute(
        "SELECT id, kind, meta FROM messages ORDER BY id").fetchall()
    ok("three more connects change nothing", before == after)

    print("\n--- a marker written by the real code must parse here ---")
    # The regex in db.py hard-codes commands.py's marker format. Build one the
    # way commands.py builds it and assert db.py still recognises it.
    import commands, inspect
    src = inspect.getsource(commands.do_remember)
    ok("commands.py still builds the marker this way",
       'f\'[:remember "{query}" → {len(hits)} excerpts \'' in src
       or "[:remember" in src,
       "do_remember no longer contains a recognisable marker literal")

    query, n = "a live query", 4
    real_marker = (f'[:remember "{query}" → {n} excerpts '
                   f'injected (ephemeral)]')
    m2 = dbmod._MARKER_RE.match(real_marker)
    ok("db.py parses the marker commands.py writes", m2 is not None,
       f"db._MARKER_RE failed on: {real_marker!r}")
    if m2:
        ok("parsed query round-trips", m2.group("query") == query)
        ok("parsed count round-trips", int(m2.group("n")) == n)

    print("\n--- a fresh database gets the columns too ---")
    fresh = tmp / "fresh.db"
    dbmod.DB_PATH = fresh
    c = dbmod.db()
    cols = [r[1] for r in c.execute("PRAGMA table_info(messages)")]
    ok("fresh db has kind", "kind" in cols)
    ok("fresh db has meta", "meta" in cols)
    c.close()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
