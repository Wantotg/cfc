#!/usr/bin/env python3
"""
search.py — pure semantic retrieval over cfc's chunk vectors. No synthesis.

    from search import search
    hits = search(db_path, "what did we decide about sqlite-vec", k=8, kind=None)

Returns list of dicts: chunk_id, text, kind, session_id, session_title,
created_at, distance — ranked nearest-first. May return fewer than k, or
none at all, when nothing is close enough to be worth reading.

kind: None (all) | 'message' | 'thinking'  — filter what gets retrieved.
"""
import sqlite3, os, struct
import sqlite_vec
from embed import embed_texts

# KNN always returns k rows, however bad they are, so a question the corpus
# can't answer still came back with eight confident-looking excerpts of lint.
# The distance says so plainly. Measured over 36 probes against this corpus
# (24 questions with a known answer, 12 on topics it has never discussed):
#
#   answerable:   distance 0.531 - 0.892   (median 0.788)
#   unanswerable: distance 0.973 - 1.094   (median 1.029)
#
# Separation was total, so anything in 0.90-0.97 scores identically; 0.93 sits
# mid-gap for the widest margin either side. bge-m3 specific — re-measure if
# the embedding model changes, as this is a property of its geometry, not a
# universal constant.
MAX_DISTANCE = 0.93

def _connect(db_path):
    db = sqlite3.connect(os.path.expanduser(db_path))
    db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
    db.row_factory = sqlite3.Row
    return db

def search(db_path, query, k=8, kind=None, provider=None,
           max_distance=MAX_DISTANCE):
    """max_distance=None disables the relevance cutoff (returns raw KNN)."""
    db = _connect(db_path)
    qvec = embed_texts([query])[0]
    qblob = struct.pack(f"{len(qvec)}f", *qvec)

    # sqlite-vec KNN must run as its own step, THEN join to metadata.
    # (vec0 MATCH doesn't compose with arbitrary WHERE on joined tables,
    #  so we over-fetch then filter — fetch extra when filtering by kind.)
    fetch = k * 4 if (kind or provider) else k
    knn = db.execute("""
        SELECT chunk_id, distance
        FROM vec_chunks
        WHERE embedding MATCH ? ORDER BY distance LIMIT ?
    """, (qblob, fetch)).fetchall()

    results = []
    for row in knn:
        if max_distance is not None and row["distance"] > max_distance:
            break              # KNN is sorted, so everything after is worse too
        c = db.execute("""
            SELECT c.id AS chunk_id, c.text, c.kind, c.session_id,
                   s.title AS session_title, s.created_at, s.provider
            FROM chunks c JOIN sessions s ON s.id = c.session_id
            WHERE c.id = ?
        """, (row["chunk_id"],)).fetchone()
        if c is None:
            continue
        if kind and c["kind"] != kind:
            continue
        if provider and c["provider"] != provider:
            continue
        results.append({
            "chunk_id": c["chunk_id"], "text": c["text"], "kind": c["kind"],
            "session_id": c["session_id"], "session_title": c["session_title"],
            "created_at": c["created_at"], "distance": row["distance"],
        })
        if len(results) >= k:
            break
    db.close()
    return results

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print('usage: python3 search.py /path/to/chat.db "your query" [k]'); sys.exit(1)
    db_path, query = sys.argv[1], sys.argv[2]
    k = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    hits = search(db_path, query, k=k)
    if not hits:
        print(f"nothing within {MAX_DISTANCE} of that query — memory has no answer.")
        sys.exit(0)
    for h in hits:
        d = h["distance"]
        print(f"[{d:.3f}] ({h['kind']}) {h['session_title'][:40]} — {h['text'][:90]!r}")
