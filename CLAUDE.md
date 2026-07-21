# CLAUDE.md

## Who you're working with

Cas. Not a professional developer — self-taught, learns by building. "Jump and see if you float."

Talk to him as a peer. Direct, no hand-holding, no false enthusiasm. He has a dry wit and will meet yours.

## Communication

- Concise. Skip preamble, skip summaries of what you just did unless asked.
- English primary. French for emphasis or a joke — sparingly, naturally.
- Explain *why* when the reasoning isn't obvious, not *what* when the code says it.
- Push back when something's a bad idea. He'd rather argue than be humoured.
- No all-lowercase corporate voice. Ever.

## How he works

- Iterative. Small blocks, verify, next block. Don't dump 400 lines and hope.
- Git: commit at working states, push at end of session, imperative messages.
- Ambiguity is fine — he'll steer. Ask when genuinely blocked, not to cover yourself.
- **Handover briefs harden his suggestions into rules. Don't treat them as
  settled.** A brief written at the end of a session is usually written by the
  model, and it tends to promote "Cas mentioned doing X first" into "Build this
  last, only once 1–4 are solid — Cas was explicit about this ordering." He
  usually wasn't. Ordering, scope and bonus objectives in a brief are proposals
  unless he says otherwise *in the conversation*. If a different order or design
  makes more sense, say so **before starting**, not after. The genuinely fixed
  things are the invariants in `HANDOVER.md` and the standing decisions — those
  are recorded precisely because they're settled, and they say so.

## Environment

- WSL2 / Ubuntu on Windows. Projects live in `~/projects/`.
- Some project files (Obsidian markdown, notes) live on the Windows side.
- Obsidian is the text environment for everything not code.
- **Session handovers live in the vault, at `<vault>/00 inbox`.** That's where
  Cas leaves the brief for the next session — check it at the start of a session
  when he says he's left one, and read it before planning. `99 outbox` is the
  return direction (model → Cas) — and as of 2026-07-20 it is the **only**
  writable path in the whole system (`WRITE_ROOTS`). Everything the model
  produces lands there.
  `CLAUDE.md` and `HANDOVER.md` are *not* part of this — they stay in
  `~/projects/cfc` as the permanent project docs. The inbox carries the
  per-session, disposable briefs.
- **A rewritten `HANDOVER.md` is written straight to `~/projects/cfc/`, next to
  `CLAUDE.md` — the repo root you are already working in.** Not the vault, not
  `99 outbox`, not anywhere else. It is a versioned project doc and belongs in
  git; a copy in the outbox is a copy that goes stale and gets read as current
  (that has already happened once). The outbox is for *output* — briefs,
  drafts, generated notes — not for the permanent docs. Same for `README.md`,
  `BACKLOG.md` and `CHANGELOG.md`. If a handover already exists there, edit it
  in place rather than writing a second one beside it.
- Don't create `inbox/`/`outbox/` in the project tree — that was tried and
  removed; reasoning is in `HANDOVER.md`.
- Python: SQLite, httpx, rich are familiar territory. sqlite-vec for vectors.
- `config.py` is gitignored. Keep it that way.

## Current project

**cfc** ("Cooking for Cats") — terminal Python AI chat client, nano-gpt
OpenAI-compatible API, SQLite backend, `rich` for the REPL. Private repo
`Wantotg/cfc`. Entry point is `python main.py [session_id]`.

**This section is orientation, not truth.** `HANDOVER.md` is the technical
document and wins on every point of detail — architecture, invariants, tuned
constants, why a thing is the way it is. `CHANGELOG.md` is the history.
`BACKLOG.md` is what's owed. If this section and one of those disagree, this
one is stale; fix it.

What exists, in one pass:

- **The REPL**, split across `main.py` (hub + session loop + dispatch),
  `commands.py`, `hub.py`, `db.py`, `api.py`, `agent.py`, `export.py`,
  `ui.py`, `config.py`. A launch splash, a session picker, colored speaker
  panels, a `prompt_toolkit` line editor.
- **Memory / RAG over a distilled Obsidian wiki** — `import_wiki.py`,
  `chunk.py`, `embed.py`, `backfill.py`, `search.py`, `recall.py`. Embeddings
  run on **self-hosted `bge-m3` via LM Studio** (`EMBED_*` in config), stored
  in `sqlite-vec`. REPL commands: `:recall`, `:remember`, `:forget`,
  `:updatedb`, plus per-turn auto-embed. `import_anthropic.py` survives for the
  old export format; that corpus is archived out of the live db.
- **Tool calling and the file jail** — `tools.py`, `paths.py`, `context.py`.
  Four tools (`list_dir`, `read_file`, `grep`, `write_file`). `WRITE_ROOTS` is
  the vault outbox and nothing else. There is no auto-approve flag and
  reintroducing one is a broken invariant.
- **Routines** — `routines.py` + `runner.py`, run on command via `:routine`.
  No scheduler yet; that's deliberate, and `run_routine()` is the entry point
  it will call.
- **Filing** — `mover.py`, `:outbox` / `:file`. A routine proposes a
  destination; code re-validates it and carries it out.
- **`backup.py`** snapshots `~/.cfc/chat.db` on startup. It exists because a
  test guard that checked its path *after* a destructive step deleted the whole
  database. **Anything that writes to a database checks the path before the
  write, not after.**
- **Tests** — `tests/golden.py` pins the REPL's exact output for every command
  that makes no API call; run `check` after touching those modules, `record`
  to re-baseline an intended change. Plus ten unit suites. None need an API
  key. Not covered: the chat turn, `:recall`/`:remember`, `:export`, the
  picker, `:routine` — those are verified by hand.

### Versions and the roadmap

As of **v0.1 (2026-07-21)** the project is versioned and has a roadmap
(`ROADMAP.md`). v0.1 means "the state of things on that date" — everything
above works and Cas has used it. It does **not** claim the test suite covers
it. Don't read the tag as a verification claim.

Each version gets a human-written note from Cas about what landed and what's
next. The roadmap addresses `BACKLOG.md` at chosen points rather than all at
once — a feature session is not obliged to clear unrelated debt, but the
roadmap says which version owns which item.

### The one live blocker

**`MAX_DISTANCE` no longer separates.** The measured gap between answerable and
unanswerable queries collapsed 0.111 → 0.025, and the floor now sits below the
top of the answerable band, so good queries return nothing. Worse: a recorded
baseline (`"who is Cas"` at 0.969) now measures 1.036 on the same corpus with
the same embedder, and that discrepancy has no explanation that fits the
evidence. **Don't just nudge the floor** — a floor built on a number that
doesn't reproduce will fail again silently. Full write-up in `BACKLOG.md`; this
blocks anything that depends on recall being trustworthy, including the tiered
memory work.

Read `BACKLOG.md` before touching the memory layer.

## Things to remember

- Don't reformat working code you weren't asked to touch.
- If a fix is a guess, say it's a guess.
- `README.md` (human-facing) and `HANDOVER.md` (LLM-facing technical doc) are
  coupled. A rewrite of one requires a rewrite of the other — if I ask you to
  redo the README, redo the handover too.
- Log every shipped change in `CHANGELOG.md` — add the entry in the same commit
  as the change, most recent at the top. Write the hash as `pending` and
  backfill it on the next commit; don't amend to self-reference (a commit can't
  hold its own final hash). Format is at the head of that file. This is the
  running history; `HANDOVER.md` stays invariants and design reasoning, not a log.
- `ROADMAP.md` is **Cas's document, not yours.** Propose changes to it, don't
  make them unasked — an LLM editing the roadmap mid-session is exactly how
  "Cas mentioned X" becomes "X was decided." Finishing a version's work means
  saying so and offering to update it, and the per-version note is written by
  Cas in his own words.