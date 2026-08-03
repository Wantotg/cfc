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
            source TEXT DEFAULT 'chat',  -- 'chat' | 'wiki'; lets hybrid recall filter/weight by corpus
            UNIQUE(message_id, kind, ordinal)
        )""")
    # Migrate an older chunks table that predates the source column.
    cols = {r[1] for r in db.execute("PRAGMA table_info(chunks)")}
    if "source" not in cols:
        db.execute("ALTER TABLE chunks ADD COLUMN source TEXT DEFAULT 'chat'")
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

# Where a chunk may end, best first. A paragraph break is a better seam than a
# line break, which is better than a sentence end, which beats a bare space.
_END_BOUNDARIES = ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ")
# How much of the window we're willing to give up to reach a better seam. At
# 0.6 a chunk is never shorter than 60% of target, so seeking can't collapse
# chunk sizes on prose that happens to lack paragraph breaks.
_MIN_FILL = 0.6
# How far to scan forward for a word boundary when opening the overlap.
_SEEK_WINDOW = 120

_WS = re.compile(r"\s")

def _end_at(text, start, hard_end):
    """Best place to end a chunk at or before hard_end. Falls back to a hard cut
    when the span holds no boundary at all (one enormous unbroken token)."""
    if hard_end >= len(text):
        return len(text)
    floor = start + int((hard_end - start) * _MIN_FILL)
    for sep in _END_BOUNDARIES:
        idx = text.rfind(sep, floor, hard_end)
        if idx != -1:
            return idx + len(sep)
    return hard_end

def _open_at(text, pos):
    """Nudge pos forward to the next whitespace so the overlap doesn't open
    mid-word. Deliberately minimal — preferring a *better* boundary here would
    silently eat the overlap it exists to preserve."""
    m = _WS.search(text, pos, min(len(text), pos + _SEEK_WINDOW))
    return m.end() if m else pos

def slice_text(text):
    """Return list of chunk strings. Whole if short; sliding window if long.

    The window seeks to a boundary at both edges. It used to be a flat
    fixed-char cut, which sliced mid-word at both ends — a chunk opening
    `'ne that decides when the AC stops...'` embeds a fragment, and the leading
    garbage is dead weight in the vector.
    """
    if est_tokens(text) <= TARGET_TOKENS:
        return [text]
    target_chars = TARGET_TOKENS * CHARS_PER_TOK
    overlap_chars = OVERLAP_TOKENS * CHARS_PER_TOK
    out, i = [], 0
    while i < len(text):
        end = _end_at(text, i, i + target_chars)
        piece = text[i:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        # Step back by the overlap, then forward to a clean word boundary.
        # max(i+1, ...) guarantees forward progress: without it a pathological
        # seam could put the next start at or before this one and spin forever.
        i = max(i + 1, _open_at(text, max(i + 1, end - overlap_chars)))
    return out

def chunk_new(db):
    """Chunk any messages not yet chunked; returns (made, per_kind). The caller
    owns the connection. Incremental and idempotent — keyed by
    (message_id, kind, ordinal), so repeated calls only add what's new. Used by
    the CLI, by :updatedb, and by the per-turn auto-embed hook."""
    ensure_table(db, rebuild=False)
    done = {(r[0], r[1], r[2]) for r in db.execute("SELECT message_id, kind, ordinal FROM chunks")}
    # A wiki session is chattable now (`W-1.6.4-05`), so its provider alone no
    # longer says which of its messages is the imported page and which is an
    # ordinary reply typed later — only the imported page's own message
    # carries the frontmatter id as `source_uuid`, matching the session's own.
    # `source_uuid` only exists once an import has run against this db at
    # least once (import_wiki.migrate adds it standalone); a db that has
    # never seen one has no wiki rows to misclassify either, so falling back
    # to the old provider-only rule is exactly as correct there as it always
    # was.
    msg_cols = {r[1] for r in db.execute("PRAGMA table_info(messages)")}
    has_source_uuid = "source_uuid" in msg_cols
    uuid_select = "m.source_uuid, s.source_uuid" if has_source_uuid else "NULL, NULL"
    # LEFT JOIN so a message whose session row is missing still chunks (source
    # falls back to 'chat'); provider (plus, for wiki, the source identity)
    # drives the corpus tag.
    rows = db.execute(f"""
        SELECT m.id, m.session_id, m.content, s.provider, {uuid_select}
        FROM messages m LEFT JOIN sessions s ON s.id = m.session_id
        WHERE m.content IS NOT NULL
    """).fetchall()

    made = 0
    per_kind = {"message":0, "thinking":0}
    for mid, sid, content, provider, msg_uuid, sess_uuid in rows:
        if provider != "wiki":
            source = "chat"
        elif not has_source_uuid:
            source = "wiki"   # no per-message identity to check — old rule
        else:
            source = "wiki" if msg_uuid is not None and msg_uuid == sess_uuid \
                else "chat"
        ordinal = 0
        for kind, seg in split_kinds(content):
            for piece in slice_text(seg):
                key = (mid, kind, ordinal)
                if key in done:
                    ordinal += 1; continue
                db.execute(
                    "INSERT OR IGNORE INTO chunks (message_id, session_id, kind, ordinal, text, token_est, source) VALUES (?,?,?,?,?,?,?)",
                    (mid, sid, kind, ordinal, piece, est_tokens(piece), source))
                made += 1; per_kind[kind] = per_kind.get(kind,0)+1
                ordinal += 1
    db.commit()
    return made, per_kind

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rebuild = "--rebuild" in sys.argv
    if len(args) != 1:
        print("usage: python3 chunk.py /path/to/chat.db [--rebuild]"); sys.exit(1)
    db = sqlite3.connect(os.path.expanduser(args[0]))
    if rebuild:
        ensure_table(db, rebuild=True)

    made, per_kind = chunk_new(db)

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
