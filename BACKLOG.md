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

---

## ~~Local embedding endpoint IP is not stable across reboots~~ — FIXED

**Found:** 2026-07-19, wiring bge-m3 on LM Studio (Windows) for the wiki migration.
**Fixed:** 2026-07-20. `networkingMode=mirrored` in `.wslconfig` + `wsl --shutdown`.
`EMBED_BASE` is now `http://localhost:1233/v1`; the old gateway IP no longer
resolves at all, so a stale config fails closed rather than drifting. Verified
end-to-end (`embed_texts` returns 1024-d). LM Studio's "serve on local network"
toggle must still be ON, and the model id is still
`text-embedding-baai-bge-m3-568m`, not plain `bge-m3`. Kept for the record
below because the failure mode — embedding calls erroring like a dead server
when the address merely moved — is worth recognising if it ever recurs.

`embed.py` reaches LM Studio at `http://172.27.0.1:1233/v1` — the WSL2 NAT
gateway to the Windows host. That gateway IP is **not guaranteed stable**; it
can change on a WSL or Windows reboot, at which point embedding calls fail with
a connection error that looks like a dead server but is really a moved address.

Fix when it bites (or proactively): set `networkingMode=mirrored` in
`C:\Users\<user>\.wslconfig`, then `wsl --shutdown` once. After that
`localhost:1233` works from WSL and the IP stops mattering. The zero-setup
alternative is to re-run `ip route show default` and update the base URL when it
breaks. Also note LM Studio's "serve on local network" toggle must stay ON
(it's the 0.0.0.0 bind) and the model id is `text-embedding-baai-bge-m3-568m`,
not plain `bge-m3`.

---

## Reasoning on the tool path is printed in full — may drown the answer

**Found:** 2026-07-18, wiring reasoning into the tool path.

The streaming path tail-limits live reasoning to the last 12 lines
(`_REASONING_TAIL_LINES`) so the live region doesn't jump. The tool path
(`agent._render_reasoning`) prints each step's reasoning **in full**, because
it's a one-shot print into scrollback with no live region to keep still — and a
tool turn can print several such panels (one per loop iteration). On a verbose
thinking model that can bury the actual answer under walls of reasoning.

Left in full deliberately, to see how it reads in real use. If it's too much,
tail it there too (reuse `_REASONING_TAIL_LINES`, or a larger cap), or add a
config toggle to collapse/hide reasoning. Purely cosmetic — reasoning is never
persisted or replayed either way.


---

## MAX_DISTANCE no longer separates: measured gap collapsed 0.111 → 0.025

**Found:** 2026-07-20, smoke-testing recall after the vault restructure.

`:recall` / `:remember` return nothing for some good queries. Re-measured over
30 probes on the unchanged wiki corpus (20 answerable, 10 unanswerable):

    answerable    0.734 – 1.036   (20/20 returned the CORRECT page at rank 1)
    unanswerable  1.061 – 1.203
    gap 0.025, vs the 0.111 recorded in HANDOVER

The floor (1.024) now sits *below* the top of the answerable band, so
`"who is Cas"` (1.036) is rejected outright while
`"orchestrator specialist architecture"` (1.023) passes by 0.001.

**Unresolved:** HANDOVER records `"who is Cas"` at **0.969**. It now measures
1.036 on the same query, same corpus, same embedder. Verified, not assumed:
re-embedding a stored chunk and comparing to its stored vector gives cosine
1.000000 (embedder identical); all 20 pages are byte-identical to their files
(corpus identical); the vectors are valid and ranking is correct. Distance is a
pure function of query vector and chunk vector, both verified unchanged — so the
number should reproduce and does not. No explanation fits the evidence yet.
Ruled out: the vault restructure, which touches none of this.

**Do not just nudge the floor.** ~1.048 would admit both borderline queries, but
a 0.025 gap is too thin to tune against with confidence, and the discrepancy
above suggests the recorded baseline itself may not be trustworthy. Resolve the
0.969-vs-1.036 question first — a floor built on a number that doesn't reproduce
is a floor that will fail again silently.

Note also: `search()` over-fetches `k*4` before applying the provider filter, so
a low `k` with `provider='wiki'` can return zero rows purely because the fetch
window filled with `source='chat'` chunks. Hit this at k=1 while probing. Not
the cause of the above, but a sharp edge worth widening the window for.

---

## Routine runs clutter the session hub

**Found:** 2026-07-20, session 2 of the routines work.

Every routine run creates its own session, so the transcript is inspectable
afterwards like any other — that's deliberate and worth keeping. The side
effect is that `:list` and the hub picker fill up with
`routine: Heartbeat — 2026-07-20 19:18` rows, and a routine on a nightly
trigger will produce one per day forever.

Nothing is broken; it's noise. Options, roughly in order of appeal: filter the
hub to hide sessions whose title/provider marks them as routine runs (needs a
marker — probably a `provider='routine'` or a `kind` on the session, not a
title prefix, which is not data); or prune routine sessions older than N days
on startup like the backup rotation does; or give routines a single long-lived
session per routine rather than one per run — cheapest, but then a run's
transcript is buried in a growing log and the token cost of replay grows.

Worth deciding before the scheduler lands, since that's when the volume
arrives. Note `chunk.py` derives `source` from the session's provider, so
anything that touches provider has to consider what routine transcripts should
do to the memory index — probably `source='chat'` as now, but say so on purpose.

---

## `write_file` refuses relative paths, and only the prompt prevents it

**Found:** 2026-07-20, first end-to-end routine run.

A relative path handed to `write_file` is resolved against the **process
working directory**, which is not one of the roots and is not predictable on a
scheduled run. The model tried `heartbeat.md` on the first two runs, got
`outside the allowed roots`, and recovered — correctly, because the guard
returns the real reason rather than "denied". But it cost a full API round trip
each time.

Currently fixed at the **prompt** level: `runner.SYSTEM` names the roots and
says "always pass absolute paths". That worked (one-shot writes since), but a
prompt is a suggestion and this is the one tool where a near-miss writes a file
somewhere unintended — or rather, would, if containment weren't holding.

The alternative is resolving a relative path against the write root inside
`write_file` when there is exactly one. Not done, deliberately: it makes the
tool's behaviour depend on how many roots are configured, and "the path you
passed is not the path that was written" is a bad property for the one tool
that mutates the filesystem. Explicit refusal is defensible. Revisit only if a
model turns up that doesn't take the hint — and if so, prefer failing with a
better error over silently reinterpreting the path.
