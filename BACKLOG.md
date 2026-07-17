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

## `:q` quits instead of returning to the hub

**Found:** 2026-07-15, while rewriting the README.

The README claimed, in Features and in the command table, that `:q` returns to
the hub instead of quitting, and that the hub takes `s` (search), `l` (list)
and `t` (tags). None of that is true, and none of it ever was — checked against
the pre-split baseline `e4ada29`: `repl()` has always ended by returning to
`__main__`, which then exits, and `pick_session` has only ever accepted a
number, `n` or `q`.

The README now describes what the program does. But the described version is
arguably the better one — a hub you return to is the reason a hub exists, and
`:new` already covers "start another session" from inside a session.

Left undone because it's a design decision, not a bug fix: making `:q` return
to the hub means wrapping `repl()` in a loop in `__main__`, and deciding what
then quits for real (`:quit`? `q` at the hub?). Cheap to build, but it should
be chosen rather than inferred from a stale README.

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

---

## `pick_session` has an unreachable duplicate loop

**Found:** 2026-07-15, while extracting `hub.py`.

The `while True:` input loop in `pick_session` appears twice, identically. The
first one only ever exits by `return`, so the second is dead code. Presumably a
bad paste that never caused a symptom.

Left in place deliberately: it was found during a pure move, and deleting it
there would have meant a move that changed the code. It does nothing, so it can
go whenever `hub.py` is next touched. Verified all four paths ('q', 'n', a
number, junk) behave correctly with it present.

---

## `is_litter` marker regex is coupled to two other files

**Found:** 2026-07-15.

`backfill.py`'s `_MARKER_LINE` hard-codes the marker formats written by
`import_anthropic.py` (`[tool_use: ...]`, `[tool_result]`) and `commands.py`
(`[:remember ... (ephemeral)]`). Change a marker format in either file and
litter silently starts getting embedded again — which is exactly the bug that
was just fixed (the old regex matched one marker against the whole chunk, so
concatenated markers leaked through).

The comment says "if the marker format in commands.py changes, change this too",
which is a comment doing a test's job. The split has since moved the markers
from `chat.py` to `commands.py` and the comment had to be chased by hand —
exactly the failure it warns about, just caught this time.

A test asserting `is_litter("[:remember x (ephemeral)]") is True` against the
string `commands.py` actually writes would make this self-enforcing.
