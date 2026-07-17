# Backlog

Things found in passing and deliberately not fixed, so they don't get lost.
Nothing here is urgent — this is a hobby project and it all still works.

Add to this rather than fixing on the spot when something turns up mid-task.
CLAUDE.md is for how the project works; this is for what's still owed.

---

## A chunk with a dangling `session_id` — where does it come from?

**Found:** 2026-07-15, while verifying the distance threshold.
**Retrieval side fixed:** 2026-07-17.

Chunks 4578, 4579 and 4580 have `session_id=364`, and no session 364 exists
(`sessions` holds 187 rows with ids 1–366, so there are gaps).

The retrieval-side symptom is fixed: `search.py` now `LEFT JOIN`s chunks to
sessions and surfaces an orphan with a `(missing session N)` placeholder title
and a null date, instead of the inner join silently dropping it (which is why a
`k=8` search sometimes returned 7 hits). Verified: 4579 and 4580 now come back
on a raw-KNN probe of their own content. They still fall outside
`MAX_DISTANCE = 0.93`, so a normal query won't reach them — but they're no
longer *invisible*, and a future import can't lose data this way unnoticed.

Still open, and the actual root cause: **why does a chunk point at a session
that was never written?** Suspect `import_anthropic.py` writes chunks with a
session id that isn't committed, or a session row was deleted without cascading.
Not investigated — belongs with the DB-layer rework.

---

## `chunk.py` overlap cuts mid-word

**Found:** 2026-07-15, reading top-k output.

Chunk 1034 begins `'ne that decides when the AC stops being optional tonight.'`
— the 75-token overlap is slicing inside a word, so the chunk starts on a word
fragment. Presumably the overlap counts tokens/characters without seeking to a
boundary.

Cosmetic in most cases, but a chunk that opens on `'ne that...'` is
embedding a fragment, and it *did* score 1.034 on an unrelated query — right at
the top of a junk result set. Not proven to affect ranking; noted because it's
cheap to fix at the next chunker change.

Fixing means re-chunking and re-embedding the affected chunks (real money this
time, unlike the litter prune, which only deleted).

---

## `longcat-2.0` is in MODELS but can't chat

**Found:** 2026-07-15, while verifying which models do tool calling.

`longcat-2.0` is listed in `config.py`'s `MODELS` and `MODEL_LIMITS`, so
`:model longcat-2.0` switches to it happily — and then every message fails:

```
HTTP 400: Model longcat-2.0 is not supported on /v1/chat/completions.
```

Pre-existing; nothing to do with tools. It presumably lives on a different
nano-gpt endpoint, or the name has changed. Either drop it from `MODELS` or
find the right endpoint. Nothing validates that a model in `MODELS` can
actually be chatted with, which is why this sat there unnoticed.

