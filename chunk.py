#!/usr/bin/env python3
"""
chunk.py — slice messages in cfc's db into a `chunks` table for RAG.

Usage:
    python3 chunk.py ~/.cfc/chat.db [--rebuild]

--rebuild : drop and rebuild the chunks table from scratch.

Rules:
  - Never chunk across message boundaries.
  - Split each message into kind='thinking' and kind='message' segments,
    using the sentinels the importer wrote.
  - Long segments sliced to ~TARGET tokens with OVERLAP; short ones kept whole.
  - Idempotent-ish: keyed by (message_id, kind, ordinal). --rebuild for clean slate.

Token estimate is chars/4 — good enough for sizing; real counts come at embed time.
"""
import sqlite3, sys, os, re

THINK_OPEN, THINK_CLOSE = "\u2402THINK\u2402", "\u2402/THINK\u2402"
TARGET_TOKENS = 500
OVERLAP_TOKENS = 75
CHARS_PER_TOK = 4  # rough

def est_tokens(s): return max(1, len(s)//CHARS_PER_TOK)

def ensure_table(db, rebuild):
    if rebuild:
        db.execute("DROP TABLE IF EXISTS chunks")
    db.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            message_id INTEGER,
            session_id INTEGER,
            kind TEXT,           -- 'message' | 'thinking'
            ordinal INTEGER,     -- position within the message
            text TEXT,
            token_est INTEGER,
            UNIQUE(message_id, kind, ordinal)
        )""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_chunks_session ON chunks(session_id)")
    db.commit()

def split_kinds(content):
    """Yield (kind, text) segments in order, separating thinking from message."""
    segments = []
    pos = 0
    pattern = re.compile(re.escape(THINK_OPEN) + "(.*?)" + re.escape(THINK_CLOSE), re.DOTALL)
    for m in pattern.finditer(content):
        if m.start() > pos:
            pre = content[pos:m.start()].strip()
            if pre: segments.append(("message", pre))
        think = m.group(1).strip()
        if think: segments.append(("thinking", think))
        pos = m.end()
    tail = content[pos:].strip()
    if tail: segments.append(("message", tail))
    return segments

def slice_text(text):
    """Return list of chunk strings. Whole if short; sliding window if long."""
    if est_tokens(text) <= TARGET_TOKENS:
        return [text]
    target_chars = TARGET_TOKENS * CHARS_PER_TOK
    overlap_chars = OVERLAP_TOKENS * CHARS_PER_TOK
    step = target_chars - overlap_chars
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i+target_chars])
        i += step
    return out

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rebuild = "--rebuild" in sys.argv
    if len(args) != 1:
        print("usage: python3 chunk.py /path/to/chat.db [--rebuild]"); sys.exit(1)
    db = sqlite3.connect(os.path.expanduser(args[0]))
    ensure_table(db, rebuild)

    done = {(r[0], r[1], r[2]) for r in db.execute("SELECT message_id, kind, ordinal FROM chunks")}
    rows = db.execute("SELECT id, session_id, content FROM messages WHERE content IS NOT NULL").fetchall()

    made = 0
    per_kind = {"message":0, "thinking":0}
    for mid, sid, content in rows:
        ordinal = 0
        for kind, seg in split_kinds(content):
            for piece in slice_text(seg):
                key = (mid, kind, ordinal)
                if key in done:
                    ordinal += 1; continue
                db.execute(
                    "INSERT OR IGNORE INTO chunks (message_id, session_id, kind, ordinal, text, token_est) VALUES (?,?,?,?,?,?)",
                    (mid, sid, kind, ordinal, piece, est_tokens(piece)))
                made += 1; per_kind[kind] = per_kind.get(kind,0)+1
                ordinal += 1
    db.commit()

    total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print(f"created {made} new chunks this run")
    print(f"  by kind: {per_kind}")
    print(f"  total chunks in db: {total}")
    print("\n  sample chunks:")
    for r in db.execute("SELECT kind, ordinal, token_est, substr(text,1,60) FROM chunks ORDER BY message_id, ordinal LIMIT 6"):
        print(f"    [{r[0]:8s} #{r[1]} ~{r[2]}tok] {r[3]!r}")
    db.close()

if __name__ == "__main__":
    main()
