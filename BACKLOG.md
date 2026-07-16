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

## The "Thinking..." spinner no longer shows

**Found:** 2026-07-16, reported by Cas.

The chat turn used to show a cyan `Thinking...` spinner while waiting for the
first token. It no longer appears. The code is still there and looks intact —
`api.py:92` opens a `Live(Spinner("dots", text="Thinking...", ...))` before the
stream and replaces it with the answer panel on the first content delta — so
this is a runtime regression, not deleted code. Cause not investigated.

Everything works without it; parked deliberately to batch with the other
cosmetic items rather than chase now. The `:recall` and `:grep` spinners
(`commands.py:442`, `commands.py:510`) are separate `Live` blocks and weren't
checked — worth confirming whether they still show when this is picked up.

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
