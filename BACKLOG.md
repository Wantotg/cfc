# Backlog

Things found in passing and deliberately not fixed, so they don't get lost.
Nothing here is urgent — this is a hobby project and it all still works.

Add to this rather than fixing on the spot when something turns up mid-task.
CLAUDE.md is for how the project works; this is for what's still owed.

---

## The run log sits inside the model's write scope

**Found:** 2026-07-22, when a routine spent its last tool call reading its own
run log in order to update it.

`ROUTINE_LOG_DIR` is `<vault>/99 outbox/routine logs/`, and `WRITE_ROOTS` is
`<vault>/99 outbox`. Containment is checked, so the log directory is **inside
the writable universe** — verified, not assumed:

```
log dir   : …/99 outbox/routine logs
write root: …/99 outbox          -> log inside? True
```

So `write_file` will happily let a model overwrite the append-only log that
`runner.append_log` owns. That log is the audit trail *and* what the next run
reads via `last_run()` to honour `on_failure`, so a clobber destroys the record
of the failure it exists to preserve — and does it silently, since nothing
compares the file against what the runner wrote.

The trigger this time was a prompt asking the model to log its actions, which
is fixable by deleting the instruction (the runner logs every run
unconditionally, so the rule was redundant anyway). But the prompt is not the
boundary anywhere else in this system and shouldn't be here: a model can decide
to tidy its log without being asked.

Fix: refuse writes under `ROUTINE_LOG_DIR` in `tools.precheck`, the same shape
as `mover._reject_wiki` — which exists for the identical reason, a write whose
damage is silent and arrives later. Note the deny list is the *weaker* tool here
(name-based, open-ended) and this wants the containment form: a path check
against the one directory, not a filename pattern.

Related: **`mover.py` already special-cases this folder** — only top-level
`*.md` in the outbox count as proposals, so the logs are excluded from filing.
The precedent for "the log subfolder is not ordinary outbox content" exists;
the write path just never got it.

---

## `append_log`'s `touched=()` is never passed — the run log can't say what a run wrote

**Found:** 2026-07-22, reading the logging path after a routine hit the tool
ceiling mid-task.

`routines.append_log(routine_id, status, detail="", touched=())` renders the
fourth argument as `— wrote a.md, b.md` in the log line. **No caller passes
it.** All five `append_log` call sites in `runner.py` supply a status and a
detail and nothing else, so the slot is dead and every line reads as though the
run touched nothing.

It matters more than a cosmetic gap because of what the log is *for*. The two
consumers are a human asking "did the nightly thing work" and the next run
reading `last_run()`. When a run fails halfway — which is now a real, logged
outcome rather than a silent `ok` — the first question is **which files it got
to before it stopped**, and the log is the only place that could answer it
without reading the whole transcript back. Right now you diff the outbox by eye.

Fix: `agent_turn` already sees every dispatched call, so the write targets are
knowable at the point they succeed. Thread the successful `write_file` paths
back out of the tool loop and hand them to `append_log`. The seam is real but
not free — `agent_turn` currently returns just the final message, so it needs a
second return value or a small mutable collector passed in, and the chat path
must not start paying for something only the runner reads. Prefer the collector:
a routine passes one, chat passes nothing, and the signature stays honest about
who cares.

Not urgent. The transcript has the full truth today; this is about making the
one-line summary answer the question you actually ask it.

---

## `golden.py check` writes a file into VAULT_PATH

**Found:** 2026-07-21, driving `:wiki` through the real dispatch for v0.3.

The harness ends its script with `:q`, and `:q` honours `AUTO_EXPORT` — so
every `golden.py check` exports the fixture session into the **real**
`VAULT_PATH`, leaving files like
`2026-01-01_Session-1_Renamed By Golden.md` in Cas's export folder. They
overwrite each other, so it's one or two files rather than a growing pile, and
nothing is corrupted: the fixture DB itself is correctly isolated.

But it is a test harness with a side effect outside its fixture, which is the
category invariant #1 exists for. The DB got the full assert-before-touch
treatment; the export path was never considered, because `:q` reads as a
navigation command rather than a write.

Fix: patch `AUTO_EXPORT` to False for the harness run, or redirect
`export.VAULT_PATH` to a temp dir the same way `DB_PATH` is redirected (the
loop that finds `DB_PATH` on every cfc module is the obvious place). Prefer
redirecting over disabling — the export path then stays exercised instead of
becoming untested.

Not urgent: it writes one predictable file to a backup folder. Noted because
"the tests don't touch anything real" is currently a slightly false claim, and
that claim is load-bearing for how freely the suite gets run.

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

## ~~`chunk.py` overlap cuts mid-word~~ — FIXED (v0.2, 2026-07-21)

**Fixed:** `slice_text` now seeks to a boundary at both edges — `_end_at`
(paragraph > line > sentence > space, never surrendering more than 40% of the
window) and `_open_at` (next whitespace only, so the overlap isn't eaten).
Measured against the old implementation on the same input: **22 of 26 chunks
opened on a fragment; now 0.** Corpus re-chunked and re-embedded (519 chunks,
512 vectors, 0 orphans), which is why `MAX_DISTANCE` was re-measured *after*
this landed rather than before. `tests/test_chunk.py` pins it.

Original report below.

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

## `longcat-2.0` is in MODELS but can't chat — ~~CLOSED~~ re-opened

**Found:** 2026-07-15, while verifying which models do tool calling.
**Closed:** 2026-07-21, v0.4. Dropped from `MODELS`, `MODEL_LIMITS` and the
`TOOLS_MODELS` comment in both `config.py` and `config.example.py`. Cas's call:
the model isn't wanted, so there was nothing to fix — only a mention to remove.

The observation underneath it is still true and is *not* tracked as work:
**nothing validates that a model in `MODELS` can actually be chatted with.**
A wrong name fails at the first message with a provider 400, which is loud and
immediate, so it doesn't need a guard.

Edit by Cas: even with longcat gone, we still need to fix the underlying issue.

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

## ~~Reasoning on the tool path is printed in full~~ — FIXED (v0.4, 2026-07-21)

**Found:** 2026-07-18, wiring reasoning into the tool path.

The streaming path tail-limits live reasoning to the last 12 lines
(`_REASONING_TAIL_LINES`) so the live region doesn't jump. The tool path
(`agent._render_reasoning`) prints each step's reasoning **in full**, because
it's a one-shot print into scrollback with no live region to keep still — and a
tool turn can print several such panels (one per loop iteration). On a verbose
thinking model that can bury the actual answer under walls of reasoning.

**Fixed:** middle-elided to `agent.REASONING_HEAD_LINES` + `REASONING_TAIL_LINES`
(6 + 10) with a "… N more lines …" marker. Head *and* tail rather than just the
tail: on this path the opening lines are usually "what am I about to do", which
is the part worth reading next to the tool call it explains. Larger than the
live panel's 12 because scrollback doesn't jump. Purely cosmetic either way —
reasoning is never persisted or replayed.


---

## ~~MAX_DISTANCE no longer separates~~ — RESOLVED (v0.2, 2026-07-21)

**The premise of this entry was wrong, and that turned out to be the finding.**

Nothing collapsed and nothing regressed. The old 1.024, and the "0.111-wide gap,
total separation" it was built on, were measured against the **Anthropic export**
and written into `HANDOVER.md` as if they were wiki numbers. Evidence:

- `"Who is Cas"` (capitalised, no question mark) measures **0.970 on the
  Anthropic corpus** — that is the recorded 0.969, to rounding.
- The same query has measured **1.036 on every wiki snapshot**, back to the first
  wiki-only db (`chat-20260719-151026.db`), with byte-identical chunk text
  throughout. The rolling backups made this checkable rather than arguable.
- So the wiki corpus never had a 0.111 gap to lose. Its gap has always been thin.

Ruled out first, each by measurement rather than reasoning: **the embedder**
(re-embedding a stored chunk reproduces its stored vector at L2 = 0.000000);
**the endpoint** (hosted vs self-hosted bge-m3 differ by 0.003 on the same query
— note that the "cosine ≥ 0.999 equivalence" in HANDOVER is a much weaker claim
than it sounds, since cosine is magnitude-blind and `vec0` ranks by **L2**);
**corpus drift** (none, per the snapshots).

**Lesson, and the reason this cost a session:** a tuned constant must record
*which corpus it was measured on*. Without that, a number outlives the thing it
described and the next person measures a "regression" that never happened.

**What replaced it:** the floor is no longer a relevance judge at all — the
answerable and unanswerable bands genuinely interleave (`"what was agentmail
about"` needs 1.065; `"How do I tune a guitar to drop D?"` scores 1.055), so no
threshold can separate them, and a relative metric doesn't either. It is now a
lint filter at **1.08**, set to admit generously because the two failures are
asymmetric: a rejected good hit is silent, an admitted bad one is caught by
recall's grounded synthesis. Full reasoning is in `search.py` and `HANDOVER.md`.
The old 1.024 was losing **4 of 20** real query phrasings.

Also fixed here: `search()`'s `k*4` over-fetch (noted at the foot of the original
report) now widens until it has k results, crosses the floor, or exhausts the
table — a low `k` with `provider='wiki'` could return zero rows purely because
the window filled with `source='chat'` chunks, and that got worse every day the
chat log grew.

Original report below, kept because the reasoning it prompted is worth the room.

---

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

## ~~Routine runs clutter the session hub~~ — FIXED (v0.4, 2026-07-21)

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

**Fixed:** the first option. Routine sessions carry `provider='routine'`
(`db.PROVIDER_ROUTINE`), set at insert by `runner.py`, with a one-shot migration
backfilling the runs that predate it — matched on the exact generated title
shape, so a chat called "routine: ideas" survives. The picker filters them out;
`:list` still shows them, so no transcript becomes unreachable. The hub grew a
routine panel of its own, one row per routine, with freshness from the run log.

Saying it on purpose, as this entry asked: `chunk.py`'s rule is `'wiki' if
provider == 'wiki' else 'chat'`, so **routine transcripts keep indexing as
`source='chat'`**, unchanged. `tests/test_schema.py` pins that coupling.

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
