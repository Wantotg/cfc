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

# KNN always returns k rows however bad they are, so a question the corpus can't
# answer still comes back with k confident-looking excerpts of lint. This floor
# rejects the obvious junk — and ONLY the obvious junk. It is deliberately not
# trying to decide relevance.
#
# Measured 2026-07-21 over 32 probes on the re-chunked wiki corpus (20 phrasings
# of Cas's real questions, 12 unanswerable — 6 far-field, 6 project-shaped
# near-misses). Distance recorded is that of the chunk which HOLDS the answer,
# not merely rank-1, since rank-1 is sometimes the wrong page:
#
#   answerable    0.696 - 1.065     unanswerable   0.995 - 1.194
#
# THE BANDS INTERLEAVE, and that is the finding this constant is built on. Not
# "overlap slightly at the edges" — interleave. "what was agentmail about" needs
# 1.065; "How do I tune a guitar to drop D?" scores 1.055. A guitar question is
# closer to this corpus than a real question about its own contents. No threshold
# exists that admits every good query and rejects every bad one, and none ever
# will on a corpus this small and this topically uniform.
#
# Relative metrics don't rescue it either — rank-1 against the query's own corpus
# mean was measured, cancels ~70% of phrasing noise, and lands on the same error
# rate. The signal isn't there to be extracted.
#
# So the floor stops pretending to judge relevance and becomes a lint filter.
# The choice is asymmetric on purpose: a rejected good hit is a silent, confident
# "memory has no answer" (the exact failure that blocked v0.2), while an admitted
# bad hit is read by recall.py's grounded synthesis, which is told to say when the
# excerpts don't cover the question. One failure is invisible, the other corrects
# itself. So admit generously.
#
#   floor   good lost   junk admitted
#   1.024      4/20          3/12      <- the old value; lost 20% of real queries
#   1.050      1/20          3/12
#   1.070      0/20          6/12      <- first value that loses nothing
#   1.080      0/20          7/12      <- chosen: 0.015 headroom over worst good
#   1.150      0/20         11/12
#
# 1.08 still rejects the genuinely unrelated (Paraguay 1.194, Anna Karenina
# 1.137, the Thirty Years War 1.134) and hands everything arguable to the model.
# Judgement under ambiguity is a model's job; a number's job is catching lint.
#
# NOTE ON THE HISTORY HERE, because it cost a session to work out: the previous
# value (1.024) and its "0.111-wide gap, total separation" were measured on the
# ANTHROPIC export and recorded as if they were wiki numbers. The wiki corpus has
# never separated that cleanly. The much-cited "who is Cas at 0.969" reproduces
# as 0.970 on the Anthropic corpus and has measured 1.036 on every wiki snapshot
# since the corpus was created. Nothing regressed; the baseline was mislabelled.
#
# Phrasing matters more than you would expect: 'Who is Cas?' / 'who is cas' span
# 0.053 on the same corpus — twice the width of the band this used to try to
# discriminate inside. Any future floor must have more headroom than that.
#
# The floor is a property of the embedding geometry AND the corpus. Re-measure
# (self-hosted bge-m3) when either changes — including a re-chunk.
MAX_DISTANCE = 1.08

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

    # sqlite-vec KNN must run as its own step, THEN join to metadata: vec0 MATCH
    # doesn't compose with an arbitrary WHERE on joined tables. So we over-fetch
    # and filter in Python — and the size of that window is load-bearing.
    #
    # It used to be a flat k*4, which silently returns too little: with
    # provider='wiki' on a db whose chunks are mostly source='chat', the window
    # can fill entirely with chat rows and the search returns ZERO for a query
    # the wiki answers fine. Hit at k=1 while probing; it gets worse as the chat
    # log grows, i.e. every day. Widen until one of three things is true — we
    # have k results, we've crossed the floor (KNN is sorted, so everything
    # beyond it is worse too), or we've read the whole table.
    total = db.execute("SELECT count(*) FROM vec_chunks").fetchone()[0]
    fetch = min(k * 4 if (kind or provider) else k, total) or k

    while True:
        knn = db.execute("""
            SELECT chunk_id, distance
            FROM vec_chunks
            WHERE embedding MATCH ? ORDER BY distance LIMIT ?
        """, (qblob, fetch)).fetchall()

        results, hit_floor = [], False
        for row in knn:
            if max_distance is not None and row["distance"] > max_distance:
                hit_floor = True
                break          # KNN is sorted, so everything after is worse too
            # LEFT JOIN, not JOIN: a chunk whose session_id points at a row that
            # no longer exists (deleted session, half-committed import) is real
            # embedded data. An inner join dropped it silently — the vector
            # matched, then the row vanished, and a k=8 search quietly returned
            # 7. Surface it with a placeholder instead of hiding it.
            c = db.execute("""
                SELECT c.id AS chunk_id, c.text, c.kind, c.session_id, c.source,
                       s.title AS session_title, s.created_at, s.provider,
                       s.source_uuid
                FROM chunks c LEFT JOIN sessions s ON s.id = c.session_id
                WHERE c.id = ?
            """, (row["chunk_id"],)).fetchone()
            if c is None:
                continue
            if kind and c["kind"] != kind:
                continue
            if provider and c["provider"] != provider:
                continue
            title = c["session_title"] or f"(missing session {c['session_id']})"
            results.append({
                "chunk_id": c["chunk_id"], "text": c["text"], "kind": c["kind"],
                "session_id": c["session_id"], "session_title": title,
                "created_at": c["created_at"], "distance": row["distance"],
                "source_uuid": c["source_uuid"], "source": c["source"],
            })
            if len(results) >= k:
                break

        if len(results) >= k or hit_floor or fetch >= total:
            break
        fetch = min(fetch * 4, total)

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
