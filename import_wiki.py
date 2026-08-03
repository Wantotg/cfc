#!/usr/bin/env python3
"""
import_wiki.py — importer for the Obsidian wiki_db into cfc's SQLite db.

Usage:
    python3 import_wiki.py /path/to/wiki_db ~/.cfc/chat.db [--wipe]

--wipe : delete existing provider='wiki' rows (and their chunks/vectors) first,
         for a clean re-import. Leaves chat/anthropic corpora untouched.

The wiki is markdown files with a stable integer `id` in YAML frontmatter
(YYYYMMDDHHMMSS). That id — not the filename or a text hash — is the identity
that survives edits: a page maps to one session (provider='wiki',
source_uuid=id) holding one message, keyed by id. Re-importing an edited page
updates that message and drops its chunks/vectors so chunk.py + backfill.py
rebuild under the same id.

Same output contract as import_anthropic.py: writes sessions + messages that
chunk.py consumes. Only the top-level *.md are pages; sources/ is provenance,
files without an `id` (e.g. CLAUDE.md) and type: index are skipped.
"""
import json, sqlite3, sys, os, re, glob
from collections import Counter
import yaml

PROVIDER = "wiki"

# Everything from the first "## Related" / "## Sources" heading onward is
# navigation + provenance (wikilinks, source paths) — low retrieval value and a
# bit litter-like, so it's dropped. Title + summary + Body is what gets embedded.
_TAIL_HEADING = re.compile(r"^\s*##\s+(Related|Sources)\s*$", re.IGNORECASE)


def migrate(db):
    """Ensure the source_uuid columns exist (shared with import_anthropic)."""
    cols_s = {r[1] for r in db.execute("PRAGMA table_info(sessions)")}
    cols_m = {r[1] for r in db.execute("PRAGMA table_info(messages)")}
    if "source_uuid" not in cols_s:
        db.execute("ALTER TABLE sessions ADD COLUMN source_uuid TEXT")
    if "source_uuid" not in cols_m:
        db.execute("ALTER TABLE messages ADD COLUMN source_uuid TEXT")
    db.commit()


def split_frontmatter(text):
    """Return (frontmatter_dict, body). ({}, text) if there's no frontmatter."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)          # ['', frontmatter, body]
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}, text
    return (fm if isinstance(fm, dict) else {}), parts[2]


def extract_content(body):
    """Title + summary + Body; drop the Related/Sources tail sections."""
    out = []
    for line in body.splitlines():
        if _TAIL_HEADING.match(line):
            break
        out.append(line)
    return "\n".join(out).strip()


def clear_chunks_for_message(db, mid):
    """Drop a message's chunks and their vectors so they rebuild under the same
    page id. Vectors live in a vec0 table needing the sqlite-vec extension, and
    only exist once backfill has run — both are handled defensively."""
    has_chunks = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='chunks'"
    ).fetchone()
    if not has_chunks:
        return
    cids = [r[0] for r in db.execute("SELECT id FROM chunks WHERE message_id=?", (mid,))]
    if not cids:
        return
    has_vec = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_chunks'"
    ).fetchone()
    if has_vec:
        try:
            import sqlite_vec
            db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
            db.executemany("DELETE FROM vec_chunks WHERE chunk_id=?", [(c,) for c in cids])
        except Exception as e:
            print(f"  warn: could not drop stale vectors for message {mid}: {e}")
    db.execute("DELETE FROM chunks WHERE message_id=?", (mid,))


def wipe_wiki(db):
    sids = [r[0] for r in db.execute("SELECT id FROM sessions WHERE provider=?", (PROVIDER,))]
    if not sids:
        return
    mids = [r[0] for r in db.execute(
        "SELECT id FROM messages WHERE session_id IN (%s)" % ",".join("?"*len(sids)), sids)]
    for mid in mids:
        clear_chunks_for_message(db, mid)   # no dangling session_id on chunks (see BACKLOG)
    db.executemany("DELETE FROM messages WHERE session_id=?", [(s,) for s in sids])
    db.execute("DELETE FROM sessions WHERE provider=?", (PROVIDER,))
    db.commit()
    print(f"wiped {len(sids)} existing wiki pages")


def run_import(wiki_dir, db_path, wipe=False):
    """Import the wiki corpus into the db and return the stats Counter.

    The importable core of main(): opens its own connection, migrates, imports
    every top-level page idempotently by frontmatter id, commits, and closes.
    Callable from `:updatedb` so a page just filed into the wiki can be picked
    up without shelling out. Does NOT embed — that is backfill's job, run after.
    """
    wiki_dir, db_path = os.path.expanduser(str(wiki_dir)), os.path.expanduser(str(db_path))
    if not os.path.isdir(wiki_dir):
        raise NotADirectoryError(wiki_dir)

    db = sqlite3.connect(db_path)
    try:
        migrate(db)
        if wipe:
            wipe_wiki(db)
        stats = _import_pages(db, wiki_dir)
        db.commit()
    finally:
        db.close()
    return stats


def _import_pages(db, wiki_dir):
    stats = Counter()
    skipped_no_id_names = []
    # Top-level *.md only — sources/ is one level deeper and stays out.
    for path in sorted(glob.glob(os.path.join(wiki_dir, "*.md"))):
        raw = open(path, encoding="utf-8").read()
        fm, body = split_frontmatter(raw)
        wid = fm.get("id")
        if wid is None:
            stats["skipped_no_id"] += 1
            skipped_no_id_names.append(os.path.relpath(path, wiki_dir))
            continue
        if str(fm.get("type", "")).lower() == "index":
            stats["skipped_index"] += 1; continue
        wid = str(wid)
        title = fm.get("title") or os.path.splitext(os.path.basename(path))[0]
        content = extract_content(body)
        if not content:
            stats["skipped_empty"] += 1; continue
        created = str(fm.get("created") or "")
        updated = str(fm.get("updated") or created)

        row = db.execute("SELECT id FROM sessions WHERE provider=? AND source_uuid=?",
                         (PROVIDER, wid)).fetchone()
        if row:
            sid = row[0]
            db.execute("UPDATE sessions SET title=?, updated_at=? WHERE id=?",
                       (title, updated, sid))
        else:
            cur = db.execute(
                "INSERT INTO sessions (title, provider, created_at, updated_at, source_uuid) "
                "VALUES (?,?,?,?,?)", (title, PROVIDER, created, updated, wid))
            sid = cur.lastrowid
            stats["pages_new"] += 1

        # One message per page, keyed by the same id.
        mrow = db.execute(
            "SELECT id, content FROM messages WHERE session_id=? AND source_uuid=?",
            (sid, wid)).fetchone()
        if mrow is None:
            db.execute(
                "INSERT INTO messages (session_id, role, content, created_at, source_uuid) "
                "VALUES (?,?,?,?,?)", (sid, "user", content, created, wid))
            stats["messages_new"] += 1
        elif mrow[1] != content:
            db.execute("UPDATE messages SET content=? WHERE id=?", (content, mrow[0]))
            clear_chunks_for_message(db, mrow[0])   # force re-chunk + re-embed
            stats["messages_updated"] += 1
        else:
            stats["messages_unchanged"] += 1
    stats["skipped_no_id_names"] = skipped_no_id_names
    return stats


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    wipe = "--wipe" in sys.argv
    if len(args) != 2:
        print("usage: python3 import_wiki.py /path/to/wiki_db /path/to/chat.db [--wipe]")
        sys.exit(1)
    wiki_dir, db_path = os.path.expanduser(args[0]), os.path.expanduser(args[1])
    if not os.path.isdir(wiki_dir):
        print(f"not a directory: {wiki_dir}"); sys.exit(1)

    stats = run_import(wiki_dir, db_path, wipe=wipe)

    print("\n=== wiki import summary ===")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    db = sqlite3.connect(db_path)
    print(f"\n  db totals: "
          f"{db.execute('SELECT COUNT(*) FROM sessions WHERE provider=?', (PROVIDER,)).fetchone()[0]} wiki sessions, "
          f"{db.execute('SELECT COUNT(*) FROM messages m JOIN sessions s ON s.id=m.session_id WHERE s.provider=?', (PROVIDER,)).fetchone()[0]} wiki messages")
    db.close()


if __name__ == "__main__":
    main()
