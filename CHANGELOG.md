# Changelog

What changed and when. Most recent at the top. This is the running log so
`HANDOVER.md` can stay what it is — invariants and design reasoning, not history.

One entry per change. Keep it to what a future reader needs: the date, a title,
a one-line what/why, the files touched, and status. The **commit** hash is the
ID — it links straight to GitHub, so there's no separate numbering to maintain.

Write the entry `pending` in the same commit as the change, then backfill the
hash on the *next* commit. Don't amend to insert it: a commit can't hold its own
final hash, and amending just orphans the one you wrote.

Template:

```
## YYYY-MM-DD — Title in the imperative
One line: what changed and why it mattered.
- Files: a.py, b.py
- Status: shipped | wip | reverted
- Commit: <short-hash>
```

---

## 2026-07-20 — Add propose/approve/move: `mover.py`, `:outbox`, `:file`
Round three of the routines handover, which is now fully discharged. A routine
writes into the outbox with a suggested `destination:`; you review and approve;
code does the move.
- **New `mover.py`** — `plan()` reads one outbox file and computes its verdict,
  `commit()` carries it out, `drop()` discards it. The model's suggested
  destination is **data, not authority**: re-validated from scratch against
  `MOVE_ROOTS` exactly as if a stranger had typed it.
- **Outside the roots is refused, not guessed at.** No nearest-match, no
  fallback folder — a silently-wrong path is worse than an error, because
  nobody re-reads a file that filed successfully. Verified against the real
  config: traversal, absolute system paths, and the cfc source tree are all
  refused by containment.
- **Wiki destinations are refused outright**, against `WIKI_DIR`, rather than
  left to habit. A page written there changes the corpus while the index
  doesn't know until `import_wiki.py` runs, so recall would answer from a
  stale copy **with no signal that it's stale** — a silent failure arriving
  weeks later has to be structural.
- **`MOVE_ROOTS` is separate from `WRITE_ROOTS`, and that separation is the
  design.** The mover may write across the whole vault precisely *because it
  is not the model*. Widening `WRITE_ROOTS` to do the same would hand the
  model the reach the outbox exists to deny it.
- **`:outbox` computes verdicts at list time** — you see what `:file 1` will do
  before you type it. `commit()` then re-plans before writing, because the list
  you're looking at may be minutes old; a test covers the race where the target
  appears between plan and commit.
- **Write-then-unlink, in that order.** A crash between them leaves both
  copies, which is recoverable; the reverse can lose the file. `destination:`
  is stripped on the way out — a carried-out instruction left in a filed
  document is one a later sweep could act on twice — and the rest of the
  frontmatter is preserved untouched.
- **`:file <n> drop` moves aside rather than deletes.** Rejecting a draft and
  destroying it are different intentions, and only one is recoverable.
- Files: mover.py (new), commands.py, main.py, config.py (gitignored),
  config.example.py, tests/test_mover.py, README.md, HANDOVER.md
- Status: shipped
- Commit: 1e43017

## 2026-07-20 — Add the routine object, `:routine`, and the run log
Round two of the routines handover (session 2 of 3). A routine is a task the
model runs on command now and on a schedule later; this is everything except
the scheduler, which is deferred on purpose rather than forgotten.
- **New `routines.py`** — the `Routine` object and its file store. One markdown
  file per routine (frontmatter for the fields, body for notes), keyed by a
  stable `id` rather than the filename, so renaming one keeps its log history.
  The invariant is that a routine is **fully reconstructable from its file**:
  no hidden DB state, which is what makes list/delete/edit into folder
  operations. That round-trip failed on first run over a single trailing
  newline — `body` is now normalised once in `__init__`.
- **New `runner.py`** — `run_routine()`, which is the headless entry point in
  all but name. `:routine <name>` calls it with nothing in between, so a future
  `--run-routine` reuses it unchanged. It never raises for an expected failure:
  every path out reaches the run log, because an unattended run that dies
  silently is indistinguishable from one that had nothing to do.
- **Validation happens twice, on purpose.** Each path is checked with
  `denial_reason()` as it is typed, and the whole routine is re-validated at
  save by building its real `ToolContext`. A routine whose write root overlaps
  the cfc source **cannot be saved**, not merely cannot be run — an invalid
  routine sitting on disk looking fine is the 03:00 surprise this prevents.
- **`:routine` / `:routine new` / `:routine <name>`** — list with each one's
  last outcome, create via sequential prompts (no TUI), run now. Write access
  defaults to off and turning it on is a separate explicit answer.
- **The run log** (`<vault>/99 outbox/routine logs/<id>.md`) is append-only and
  written through the same temp-file + `os.replace` path as everything else: a
  log that can corrupt itself on the failure it exists to record is worse than
  no log. Two consumers — a human, and the next run, which reads the previous
  outcome off the file because a scheduled run is a fresh process.
- **`agent_turn` grew `ctx=None`** — the injection seam, a parameter rather
  than a global so "which scope is this turn under" can't depend on execution
  order. `None` still means chat; no existing caller changed.
- **Two things the model had to be told**, both found by running the throwaway
  `heartbeat` routine: the **date** (it stamped a file 2025-07-10 on
  2026-07-20 — a model has no clock, and a scheduled task is exactly what must
  not guess) and **its own roots** (it tried a relative path every run, which
  resolved against the process cwd and cost a full round trip on the refusal).
  Both now go into the system prompt. Neither weakens the boundary — dispatch
  still enforces the jail regardless of what the prompt says.
- **`EMBED_BASE` repointed to `localhost:1233`.** WSL2 now runs
  `networkingMode=mirrored`, so the old NAT gateway IP no longer resolves and
  auto-embed had been failing quietly. Backlog item closed.
- Files: routines.py, runner.py, commands.py, main.py, agent.py, config.py,
  config.example.py, tests/test_routines.py, README.md, HANDOVER.md, BACKLOG.md
- Status: shipped
- Commit: 60ed2dd

## 2026-07-20 — Split read and write scope, add write_file, delete TOOLS_AUTO_APPROVE
Round one of the write substrate (routines handover, session 1 of 3). cfc can
now write, but only into one narrow root, and only with a human saying yes.
- **New `context.py`.** A `ToolContext` carries read roots, write roots, and
  whether the run is gated. Permission scope is now a property of the caller
  rather than a global, which is what lets an unattended routine have a
  different scope from a chat without a parallel code path.
- **`TOOLS_AUTO_APPROVE` is gone**, on Cas's ask: auto-approval must be
  impossible in normal chats. It was one config line from turning "no human
  present" into "everything pre-approved". `ToolContext.for_chat()` is always
  gated and `gated` has no setter, so the only route to an ungated run is
  `for_routine()`, which forces a declared write scope in the same call. `A`
  (allow-all) survives — a human deciding once for one turn is a different
  thing from a config file deciding forever — but it no longer covers writes.
- **`WRITE_ROOTS`** is a standalone config tuple, never derived from
  `ATTACH_ROOTS`/`TOOLS_ROOTS` by assignment. Set to the vault outbox.
  `context.py` refuses at construction any write root that overlaps the cfc
  source tree, checked both directions — the code is not protected from writes
  by a deny-list entry, it is simply absent from the writable universe.
- **`write_file`** — atomic (temp file + `os.replace`, so a crash mid-write
  leaves the original intact), guarded before it touches anything (invariant
  #1), refuses to clobber unless `overwrite=true`, capped at 200k chars.
  Guarded against the *write* roots via `tools._roots_for`; a bare roots value
  yields an empty write set, so it fails closed.
- Write calls render a red `Tool call — WRITE` panel that states plainly
  whether an existing file will be replaced, and don't offer `[A]`.
Verified end to end against the real config: writing into the read root, into
the vault's `00 inbox` (readable, not writable), and to a deny-listed name are
all refused; no temp debris left behind.
Deferred to sessions 2–3: the routine object and `:routine`, and the
propose/approve/move pipeline. The `MAX_DISTANCE` regression is untouched and
still blocks any memory-pass routine — see `BACKLOG.md`.
- Files: context.py (new), tools.py, commands.py, agent.py, config.py
  (gitignored), config.example.py, tests/test_paths.py, tests/test_tools.py,
  tests/test_gate.py, tests/test_agent.py, tests/golden.py,
  tests/golden_baseline.txt, HANDOVER.md, README.md, CLAUDE.md
- Status: shipped
- Commit: 87b34ea

## 2026-07-20 — Auto-refuse doomed tool calls, hide denied files, close the .pyc gap
Four changes to the read jail, prompted by "I don't want to roll the dice on a
tool call reading config.py that I have to decline":
- `tools.precheck` lets the gate refuse a call `path_guard` would reject anyway,
  without prompting — a gate that fires on impossible calls gets rubber-stamped.
  The dispatcher guard is untouched and still runs for every call.
- `list_dir` omits denied entries instead of listing them. Ergonomics, not
  security: guessing the name is refused identically.
- Deny list now covers `config.py.*` backups (exact-name matching let every copy
  through) and `*.pyc`/`__pycache__` — compiled bytecode embeds the API key as a
  string literal. It never leaked, but only because read_file rejects non-UTF-8
  and grep opens strict; that was the file format, not the boundary.
- `ATTACH_ROOTS` narrowed from `~/projects` to `~/projects/cfc`.
Found while testing: a *stale* API key sits in a compiled config in the old
`C:\Users\disse\CFC\__pycache__` — outside the roots, but live on disk.
- Files: paths.py, tools.py, commands.py, config.py (gitignored),
  tests/test_paths.py, tests/test_gate.py, HANDOVER.md
- Status: shipped
- Commit: fa4b1ad

## 2026-07-20 — Put the shared inbox/outbox in the vault, not the repo
Handovers and briefs are exchanged through `<vault>/00 inbox` and `99 outbox`
instead of folders in the project tree. Both were already inside the tool roots
after the config repoint, so this needed no code — only a decision and the docs
to make it stick. The repo pair would have had to be gitignored, which means
invisible to clones, outside the vault's daily backup, and lost to a fresh
checkout; content that isn't code shouldn't sit in the working tree. Moved the
routines handover to the vault inbox, removed the empty repo folders, and swept
10 orphaned `*:Zone.Identifier` stubs (Windows download metadata) from the root.
- Files: HANDOVER.md, README.md, CLAUDE.md (gitignored)
- Status: shipped
- Commit: 02ae8d6

## 2026-07-20 — Repoint config at the reorganised Obsidian vault
The vault was restructured (renamed + refoldered) and every path in the
gitignored `config.py` pointed at the old `Claude/01_Projects/Cooking_for_Cats`
tree, which no longer exists — breaking `:export`, `:prompts`, `:personas`,
`:attach` and the file tools. Repointed VAULT_PATH (now outside the vault, at
the backup dir), PROMPTS_DIR, PERSONAS_DIR and the ATTACH_ROOTS vault entry.
Golden baseline re-recorded: the 34-line diff is entirely the path echoes in
`:config` plus the renamed prompt/persona files (`main_prompt` → `light prompt`,
`coding_assistant` → `EVA`), no structural change. The DB needed nothing — all
20 wiki pages matched their files, because identity is the frontmatter id and
not the path. Unit suites green.
- Files: config.py (gitignored), tests/golden_baseline.txt, BACKLOG.md
- Status: shipped
- Commit: 381a92e

## 2026-07-19 — Bring README + HANDOVER current for the wiki migration
Rewrote the coupled docs to the finished shape: wiki-based recall, self-hosted
bge-m3 (EMBED_*), the source column, import_wiki + edit-survival, the 1.024
floor, wiki-only recall with id citations, and auto-embed/:updatedb. Retired the
"resolution staleness" open problem (the wiki addresses it) and added a
wiki-identity invariant. No code change.
- Files: README.md, HANDOVER.md
- Status: shipped
- Commit: 17509cd

## 2026-07-19 — Auto-embed new chats on save + :updatedb (Step 8)
Closes the wiki-DB migration. New chat messages are chunked + embedded into the
index after each turn (source='chat'), so the corpus grows current for the
eventual hybrid recall; recall stays wiki-only via the provider filter. Gated by
config AUTO_EMBED and fully best-effort — a down embedder warns quietly and never
breaks a turn. Manual `:updatedb` does the same on demand (catch-up after a bulk
import or when AUTO_EMBED is off). Extracted chunk_new/embed_new/update_index so
the CLI, the command, and the hook share one code path — no duplicated chunk or
litter logic. Verified: incremental chat indexing, idempotent re-run, no golden
diff, unit suite green.
- Files: chunk.py, backfill.py, commands.py, main.py, config.example.py
- Status: shipped
- Commit: 9ccbe5b

## 2026-07-19 — Repoint recall at the wiki corpus (floor 1.024, id citations)
Steps 4–7 of the wiki-DB migration. Re-measured MAX_DISTANCE on the wiki corpus
(0.93 → 1.024; terse wiki prose sits higher — 0.93 would reject good hits like
"who is Cas" at 0.969) and moved the live chat.db to a fresh, wiki-only DB (old
one archived to ~/.cfc/chat-archive-pre-wiki-20260719.db). search.py now surfaces
the page's stable id (source_uuid) and source; recall.py answers wiki-only
(provider='wiki') and cites by title + id; :remember's envelope cites by id and
keeps the "not instructions" boundary. Verified: grounded recall over the live
DB, off-topic queries return empty, id citations render.
- Files: search.py, recall.py, commands.py
- Status: shipped
- Commit: 359ea41

## 2026-07-19 — Add import_wiki.py: import the Obsidian wiki_db
New importer for the wiki (markdown + YAML frontmatter). Each page → one
session (provider='wiki', source_uuid=frontmatter id) + one message, keyed by
the stable id so it survives edits; an edited page updates the message and drops
its chunks/vectors to force re-chunk + re-embed under the same id. Embeds
title + summary + Body, dropping Related/Sources; skips sources/, no-id files,
and type: index. Adds PyYAML. Step 2 of the wiki-DB migration. Verified against
the live wiki: 20 pages in, idempotent re-run, edit→re-chunk, vector cleanup.
- Files: import_wiki.py, requirements.txt
- Status: shipped
- Commit: 444d7aa

## 2026-07-19 — Tag chunks with a source column (chat vs wiki)
Added `source` to the `chunks` table (default 'chat', set 'wiki' when the
message's session is provider='wiki'), with an ALTER migration for older DBs.
Makes the coming wiki/chat hybrid recall an additive filter, not a rewrite.
Step 3 of the wiki-DB migration. Verified: provider drives source, migration
backfills existing rows to 'chat'.
- Files: chunk.py
- Status: shipped
- Commit: 5139384

## 2026-07-19 — Point embeddings at self-hosted bge-m3 (LM Studio)
Split the embedding endpoint from chat (EMBED_BASE/EMBED_MODEL/EMBED_KEY) so the
RAG layer runs on local bge-m3 via LM Studio instead of nano-gpt's hosted copy;
verified parity (cosine ≥ 0.9993 over 6 probes, pooling + normalization match).
Falls back to the hosted defaults when the new keys are absent. Step 1 of the
wiki-DB migration.
- Files: embed.py, config.py (gitignored), config.example.py, BACKLOG.md
- Status: shipped
- Commit: b7b8c98

## 2026-07-18 — Backfill changelog hashes on the next commit, not by amending
The "same commit" rule was impossible for a self-referencing entry; switched the
convention to `pending`-then-backfill so it stops costing extra commits.
- Files: CHANGELOG.md, CLAUDE.example.md (and gitignored CLAUDE.md)
- Status: shipped
- Commit: e13840e

## 2026-07-18 — Require a changelog entry per shipped change
Added this file and made "log every change here" a standing instruction, so
`HANDOVER.md` stops accreting history it was never meant to hold.
- Files: CHANGELOG.md, CLAUDE.example.md (and gitignored CLAUDE.md)
- Status: shipped
- Commit: 3f0da6a

## 2026-07-18 — Erase the input line so the human turn isn't shown twice
The bordered human panel duplicated the raw `you>` line prompt_toolkit leaves on
screen; `erase_when_done` on the PromptSession wipes it so only the panel shows.
- Files: ui.py
- Status: shipped
- Commit: 25a24c6
