#!/usr/bin/env python3
"""
backfill.py — embed all chunks lacking a vector, store in sqlite-vec table.

Usage:
    python3 backfill.py ~/.cfc/chat.db [--limit N] [--prune]

--limit N : only embed N chunks this run (for a cautious first live test).
--prune   : delete vectors for chunks that now count as litter. Needed after
            tightening the litter rules, since embedding is otherwise
            additive and old vectors would survive the rule change.

Idempotent: only embeds chunks not already in vec_chunks. Re-run to resume.
Skips marker-only and content-free chunks (litter) — they get no vector.
"""
import sqlite3, sys, os, re, struct
import sqlite_vec
from embed import embed_texts, EMBED_DIM

# A chunk that is ONLY a marker is litter — skip embedding it.
#   [tool_use: ...] / [tool_result]  — written by import_anthropic.py
#   [:remember ... (ephemeral)]      — written by commands.py's :remember
# The :remember marker is persisted deliberately: it's the only record that
# recalled excerpts were injected at that point, so an export can distinguish a
# grounded claim from an invented one. Embedding it would put a row that
# describes a search into the results of future searches. Keep the row, skip
# the vector. If the marker format in commands.py changes, change this too.
_MARKER_LINE = re.compile(
    r"^\s*(\[tool_use:[^\]]*\]"
    r"|\[tool_result\]"
    r"|\[:remember\b.*\(ephemeral\)\])\s*$"
)

# Consecutive tool calls chunk together, so a chunk is frequently several
# markers and nothing else. Matching the whole string against one marker missed
# every one of those.
def _markers_only(text):
    lines = [l for l in text.splitlines() if l.strip()]
    return bool(lines) and all(_MARKER_LINE.match(l) for l in lines)

# Content-free chunks ("Yes!", "Confirmed.", "/condense") embed to near the
# centre of the space and sit mediocrely close to every query, so they crowd
# top-k for questions they have nothing to do with. Measured on the corpus:
# chunks under 20 tokens are 9.4% of chunks but 29% of top-8 hits.
#
# The floor is 5 rather than 20 because the 7-20 band is real material — "Help
# me set up MCP for LocalAI" is 8 tokens and worth retrieving. Below 5 is
# acknowledgements and slash commands, with no topic to match on.
MIN_TOKENS = 5

def is_litter(text, token_est=None):
    if _markers_only(text):
        return True
    return token_est is not None and token_est < MIN_TOKENS

def connect(db_path):
    db = sqlite3.connect(os.path.expanduser(db_path))
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db

def ensure_vec_table(db):
    db.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
            chunk_id INTEGER PRIMARY KEY,
            embedding float[{EMBED_DIM}]
        )""")
    db.commit()

def pack(vec):
    """sqlite-vec accepts raw float32 bytes."""
    return struct.pack(f"{len(vec)}f", *vec)

def main():
    limit = None
    argv = sys.argv[1:]
    if "--limit" in argv:
        i = argv.index("--limit")
        limit = int(argv[i+1])
        del argv[i:i+2]          # remove both --limit and its value
    prune = "--prune" in argv
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print("usage: python3 backfill.py /path/to/chat.db [--limit N] "
              "[--prune]"); sys.exit(1)

    db = connect(args[0])
    ensure_vec_table(db)

    embedded = {r[0] for r in db.execute("SELECT chunk_id FROM vec_chunks")}
    rows = db.execute("SELECT id, text, token_est FROM chunks").fetchall()

    # Embedding is additive, so tightening is_litter leaves the vectors written
    # under the old rules in place, still polluting top-k. Prune them here or
    # the rule change only applies to chunks that don't exist yet.
    stale = [cid for cid, txt, te in rows
             if cid in embedded and is_litter(txt, te)]
    if stale:
        if prune:
            db.executemany("DELETE FROM vec_chunks WHERE chunk_id = ?",
                           [(c,) for c in stale])
            db.commit()
            embedded -= set(stale)
            print(f"pruned {len(stale)} litter vectors")
        else:
            print(f"note: {len(stale)} embedded vectors are now litter "
                  f"— re-run with --prune to drop them")

    todo = [(cid, txt) for cid, txt, te in rows
            if cid not in embedded and not is_litter(txt, te)]
    skipped_litter = sum(1 for cid, txt, te in rows
                         if cid not in embedded and is_litter(txt, te))

    if limit:
        todo = todo[:limit]

    print(f"chunks total: {len(rows)}")
    print(f"already embedded: {len(embedded)}")
    print(f"litter skipped: {skipped_litter}")
    print(f"to embed this run: {len(todo)}")
    if not todo:
        print("nothing to embed."); return

    BATCH = 100
    done = 0
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i+BATCH]
        vecs = embed_texts([t for _, t in batch])
        db.executemany(
            "INSERT OR REPLACE INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
            [(cid, pack(v)) for (cid, _), v in zip(batch, vecs)])
        db.commit()
        done += len(batch)
        print(f"  embedded {done}/{len(todo)}")
    print(f"done. vec_chunks now holds {db.execute('SELECT COUNT(*) FROM vec_chunks').fetchone()[0]} vectors")
    db.close()

if __name__ == "__main__":
    main()
