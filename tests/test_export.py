#!/usr/bin/env python3
"""
test_export.py — First Message in an export (1.3). No API calls.

    python3 tests/test_export.py

`/export`'s general behaviour is a known gap (HANDOVER's Testing section) and
out of this file's scope. What 1.3 owes a test is narrower and is what this
file covers: the frozen opening is written at the head of the transcript,
before the ordinary turns, and is counted in `total_messages` even though it
is not a `messages` row.
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import db as dbmod
import export as exportmod

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def main():
    tmp = Path(tempfile.mkdtemp())
    assert "tmp" in str(tmp), "refusing to touch a real db"
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()

    vault = Path(tempfile.mkdtemp())
    exportmod.VAULT_PATH = str(vault)

    print("--- a session with no First Message exports as before ---")
    plain_sid = dbmod.new_session(conn, title="plain")
    dbmod.save_message(conn, plain_sid, "user", "hi", model="m")
    dbmod.save_message(conn, plain_sid, "assistant", "hello", model="m")
    exportmod.export_session(conn, plain_sid, quiet=True)
    plain_file = sorted(vault.glob(f"*Session-{plain_sid}_*.md"))[0]
    plain_text = plain_file.read_text(encoding="utf-8")
    ok("total_messages counts only the two real rows",
       "total_messages: 2" in plain_text, plain_text)

    print("\n--- a First Message is at the head, before the ordinary turns ---")
    fm_sid = dbmod.new_session(conn, title="with-opening")
    dbmod.set_first_message(conn, fm_sid, "muse.md", "Where should we begin?",
                            at="2026-07-31T09:00:00+00:00")
    dbmod.save_message(conn, fm_sid, "user", "let's start", model="m")
    dbmod.save_message(conn, fm_sid, "assistant", "sure thing", model="m")
    exportmod.export_session(conn, fm_sid, quiet=True)
    fm_file = sorted(vault.glob(f"*Session-{fm_sid}_*.md"))[0]
    fm_text = fm_file.read_text(encoding="utf-8")

    ok("the opening text is in the export",
       "Where should we begin?" in fm_text, fm_text)
    ok("total_messages counts it: 2 real rows + 1 opening = 3",
       "total_messages: 3" in fm_text, fm_text)
    ok("the opening comes before the first ordinary turn",
       fm_text.index("Where should we begin?")
       < fm_text.index("let's start"), fm_text)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
