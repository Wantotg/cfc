#!/usr/bin/env python3
"""
test_pools.py — the three pools, and a session's trait list. No API calls.

    python3 tests/test_pools.py

Two halves:

* **`pools.py`** — prompts, personas and traits as one mechanism. The suite
  leans on the property that made unifying them safe: a pool is a folder of
  `.md` files where the filename is the identity, so the three differ only in
  which folder and what they are called on screen.
* **`db.get_traits`/`set_traits`** — the session's trait list, stored as
  *names*. What is pinned is that a body is never stored: editing a trait file
  has to change what every session carrying that name sends, or the pool stops
  being the source of truth and old drafts live on in rows nobody inspects.

Every path here goes through `Pool.dir()`, so the suite re-points the pools at
a temp folder rather than patching `config` — patching config would miss
anything that read the value at import time, which is the mistake
`test_routines` records for the routine dirs.
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

import pools
import db as dbmod

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def point_pools(root):
    """Re-point all three pools inside a temp root and return their paths."""
    dirs = {}
    for kind in ("prompt", "persona", "trait"):
        d = root / f"{kind}s"
        d.mkdir(parents=True, exist_ok=True)
        pools.POOLS[kind].configured = str(d)
        dirs[kind] = d
    return dirs


def temp_db(path):
    """A database at an explicit path, asserted not to be the real one
    *before* anything is written to it (invariant #1)."""
    real = (Path.home() / ".cfc" / "chat.db").expanduser()
    assert path.resolve() != real, f"refusing to touch the real db at {path}"
    return dbmod.db(str(path))


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dirs = point_pools(root)

        print("--- a pool is a folder of .md files ---")
        (dirs["trait"] / "relax.md").write_text("# Relax\nbe brief\n",
                                                encoding="utf-8")
        (dirs["trait"] / "terse.md").write_text("say less\n", encoding="utf-8")
        (dirs["prompt"] / "relax.md").write_text("prompt body\n",
                                                 encoding="utf-8")
        ok("names lists the stems, sorted",
           pools.names("trait") == ["relax", "terse"], pools.names("trait"))
        ok("load returns body and filename",
           pools.load("trait", "terse") == ("say less", "terse.md"),
           pools.load("trait", "terse"))
        ok("the body is stripped, like prompts and personas always were",
           pools.load("trait", "relax")[0] == "# Relax\nbe brief")
        ok("a missing name is (None, None)",
           pools.load("trait", "nope") == (None, None))
        ok("an empty name is (None, None), not the whole folder",
           pools.load("trait", "") == (None, None))
        ok("the same name in two pools loads two different bodies",
           pools.load("trait", "relax")[0] != pools.load("prompt", "relax")[0],
           "the filename is the identity *within* a pool")

        print("\n--- .md is a candidate, never an assumption ---")
        (dirs["trait"] / "plain.txt").write_text("txt body\n",
                                                 encoding="utf-8")
        ok("an explicit .md name loads",
           pools.load("trait", "relax.md")[0] == "# Relax\nbe brief")
        ok("a file that isn't .md still loads by its full name",
           pools.load("trait", "plain.txt") == ("txt body", "plain.txt"),
           "the same rule routines.prompt_candidates follows")
        ok("names only lists .md, so the pool listing stays the pool",
           "plain" not in pools.names("trait"), pools.names("trait"))

        print("\n--- kinds ---")
        ok("a kind resolves", pools.pool("trait").kind == "trait")
        ok("the plural resolves to the same pool",
           pools.pool("traits") is pools.pool("trait"))
        ok("case doesn't matter", pools.pool("Traits") is pools.pool("trait"))
        ok("an unknown kind is None, not a guess",
           pools.pool("wombat") is None)
        ok("None is not a kind", pools.pool(None) is None)
        ok("all three kinds exist",
           set(pools.POOLS) == {"prompt", "persona", "trait"}, set(pools.POOLS))
        ok("priority is System > Persona > Trait",
           pools.PRIORITY == ("prompt", "persona", "trait"), pools.PRIORITY)

        print("\n--- bodies() ---")
        ok("bodies come back in the order asked for",
           pools.bodies("trait", ["terse", "relax"])
           == ["say less", "# Relax\nbe brief"])
        ok("no names is no bodies", pools.bodies("trait", []) == [])
        ok("None is no bodies", pools.bodies("trait", None) == [])
        # A renamed or deleted trait file leaves a session carrying a name with
        # nothing behind it. Skipping keeps the turn working; /status is where
        # the gap is reported, because a per-turn warning is one that gets
        # trained out.
        ok("a name whose file is gone drops out without shifting the rest",
           pools.bodies("trait", ["terse", "vanished", "relax"])
           == ["say less", "# Relax\nbe brief"])

        print("\n--- an unconfigured pool is empty, not an error ---")
        saved = pools.POOLS["trait"].configured
        pools.POOLS["trait"].configured = str(root / "does-not-exist")
        ok("names of a missing folder is []", pools.names("trait") == [])
        ok("load from a missing folder is (None, None)",
           pools.load("trait", "relax") == (None, None))
        pools.POOLS["trait"].configured = saved

        print("\n--- First Message: not a fourth pool, but the same shape ---")
        fm_dir = root / "first_messages"
        saved_fm = pools.FIRST_MESSAGES_DIR
        pools.FIRST_MESSAGES_DIR = str(fm_dir)
        try:
            ok("no folder yet: absent, not an error",
               pools.load_first_message("muse.md") is None)

            fm_dir.mkdir(parents=True, exist_ok=True)
            ok("a folder with no matching file is absent too",
               pools.load_first_message("muse.md") is None)

            (fm_dir / "muse.md").write_text("Good morning.\n",
                                            encoding="utf-8")
            ok("the persona filename's stem is the key",
               pools.load_first_message("muse.md") == "Good morning.")
            ok("a bare name (no .md) resolves the same way",
               pools.load_first_message("muse") == "Good morning.")
            ok("an empty name is absent, not every file in the folder",
               pools.load_first_message("") is None)
            ok("a persona with no companion file is absent",
               pools.load_first_message("other.md") is None)

            print("\n--- optional and broken must not look identical ---")
            # A missing companion (above) returns None, silently. A directory
            # that exists but can't be listed, or a file that can't be read,
            # must be a visible failure instead — Concept.md's named failure
            # mode. Simulated with a directory in place of the expected file,
            # which IsADirectoryError makes unreadable as text.
            (fm_dir / "broken.md").mkdir()
            try:
                pools.load_first_message("broken.md")
                ok("an unreadable companion raises FirstMessageError", False,
                   "did not raise")
            except pools.FirstMessageError as e:
                ok("an unreadable companion raises FirstMessageError", True)
                ok("...naming the path", "broken.md" in str(e), e)
        finally:
            pools.FIRST_MESSAGES_DIR = saved_fm

        print("\n--- a session's traits are names, never bodies ---")
        conn = temp_db(root / "traits.db")
        sid = dbmod.new_session(conn)
        ok("a fresh session carries no traits",
           dbmod.get_traits(conn, sid) == [])
        dbmod.set_traits(conn, sid, ["relax", "terse"])
        ok("names round-trip in attach order",
           dbmod.get_traits(conn, sid) == ["relax", "terse"],
           dbmod.get_traits(conn, sid))
        stored = conn.execute("SELECT traits FROM sessions WHERE id=?",
                              (sid,)).fetchone()[0]
        ok("the column holds a JSON array of names",
           json.loads(stored) == ["relax", "terse"], stored)
        ok("no body is anywhere in the row",
           "be brief" not in (stored or ""),
           "bodies are re-read from the pool, so editing a file updates "
           "every session carrying its name")

        # The point of storing names: edit the file, every session that carries
        # it sends the new text on the next turn. No migration, no stale copy.
        (dirs["trait"] / "relax.md").write_text("EDITED\n", encoding="utf-8")
        ok("editing a trait file changes what the session sends",
           pools.bodies("trait", dbmod.get_traits(conn, sid))
           == ["EDITED", "say less"],
           pools.bodies("trait", dbmod.get_traits(conn, sid)))

        print("\n--- the column reads safely when it can't be read ---")
        dbmod.set_traits(conn, sid, [])
        ok("an empty list clears to NULL, so 'no traits' has one spelling",
           conn.execute("SELECT traits FROM sessions WHERE id=?",
                        (sid,)).fetchone()[0] is None)
        ok("...and reads back as []", dbmod.get_traits(conn, sid) == [])
        conn.execute("UPDATE sessions SET traits=? WHERE id=?",
                     ("{not json", sid))
        ok("unparseable JSON reads as no traits, it does not raise",
           dbmod.get_traits(conn, sid) == [],
           "the safe direction for a value we can't read is the one that "
           "carries less into the request")
        conn.execute("UPDATE sessions SET traits=? WHERE id=?",
                     (json.dumps({"relax": True}), sid))
        ok("a JSON object where a list belongs reads as no traits",
           dbmod.get_traits(conn, sid) == [])
        conn.execute("UPDATE sessions SET traits=? WHERE id=?",
                     (json.dumps(["ok", 7, None]), sid))
        ok("non-string entries are dropped, the rest survive",
           dbmod.get_traits(conn, sid) == ["ok"])
        dbmod.set_traits(conn, sid, ["a", "", None, "b"])
        ok("empty names never make it into the column",
           dbmod.get_traits(conn, sid) == ["a", "b"])

        print("\n--- the migration is idempotent ---")
        conn.close()
        conn = temp_db(root / "traits.db")
        ok("reopening an existing db still finds the traits",
           dbmod.get_traits(conn, sid) == ["a", "b"],
           "the ALTER TABLE is guarded by OperationalError and runs on "
           "every connect")
        conn.close()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
