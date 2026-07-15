#!/usr/bin/env python3
"""
search.py — pure semantic retrieval over cfc's chunk vectors. No synthesis.

    from search import search
    hits = search(db_path, "what did we decide about sqlite-vec", k=8, kind=None)

Returns list of dicts: chunk_id, text, kind, session_id, session_title,
created_at, distance — ranked nearest-first.

kind: None (all) | 'message' | 'thinking'  — filter what gets retrieved.
"""
import sqlite3, os, struct
import sqlite_vec
from embed import embed_texts

def _connect(db_path):
    db = sqlite3.connect(os.path.expanduser(db_path))
    db.enable_load_extension(True); sqlite_vec.load(db); db.enable_load_extension(False)
    db.row_factory = sqlite3.Row
    return db

def search(db_path, query, k=8, kind=None, provider=None):
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
    for h in search(db_path, query, k=k):
        d = h["distance"]
        print(f"[{d:.3f}] ({h['kind']}) {h['session_title'][:40]} — {h['text'][:90]!r}")
