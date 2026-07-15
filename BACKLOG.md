# Backlog

Things found in passing and deliberately not fixed, so they don't get lost.
Nothing here is urgent — this is a hobby project and it all still works.

Add to this rather than fixing on the spot when something turns up mid-task.
CLAUDE.md is for how the project works; this is for what's still owed.

---

## Three chunks are invisible to recall (dangling `session_id`)

**Found:** 2026-07-15, while verifying the distance threshold.

Chunks 4578, 4579 and 4580 have `session_id=364`, and no session 364 exists
(`sessions` holds 187 rows with ids 1–366, so there are gaps). `search.py`
joins chunks to sessions to get the title and date, so these three are dropped
by the JOIN and can never be returned — the `if c is None: continue` in the
result loop swallows them silently.

They are embedded and do match queries, so KNN finds them and then throws them
away. That is why a `k=8` search sometimes returns 7 hits.

Why it's mildly annoying: these are the three newest chunks in the corpus and
they're the *only* cfc-architecture material in it ("SQLite stays the source of
truth and handles metadata/exact filters"). They'd still fall outside
`MAX_DISTANCE = 0.93` (they score 0.97–1.06), so fixing this rescues nothing
today, but it's real data loss and it'll silently eat future imports.

Suspect `import_anthropic.py` writes chunks with a session id that isn't
committed, or the session row was deleted without cascading. Not investigated.

Worth deciding: should `search.py` drop these silently at all? A `LEFT JOIN`
with a placeholder title would surface the content instead of hiding it.

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

## `is_litter` marker regex is coupled to two other files

**Found:** 2026-07-15.

`backfill.py`'s `_MARKER_LINE` hard-codes the marker formats written by
`import_anthropic.py` (`[tool_use: ...]`, `[tool_result]`) and `chat.py`
(`[:remember ... (ephemeral)]`). Change a marker format in either file and
litter silently starts getting embedded again — which is exactly the bug that
was just fixed (the old regex matched one marker against the whole chunk, so
concatenated markers leaked through).

The comment says "if the marker format in chat.py changes, change this too",
which is a comment doing a test's job. When the `chat.py` split happens and
markers move to `commands.py`, this will break quietly.
