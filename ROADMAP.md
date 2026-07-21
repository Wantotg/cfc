# Roadmap

Where cfc is going, and in what order. Cas's document — a session may *propose*
changes here, it doesn't make them.

`BACKLOG.md` is what's owed; this says which version owns which item. A feature
session is not obliged to clear unrelated debt, but debt that's genuinely
adjacent to the version's work gets swept in it.

Each version gets a short note from Cas, in his own words, about what landed and
what it opened up. That note is the point of numbering this at all.

---

## v0.1 — 2026-07-21

The state of things on that date. Everything in `CLAUDE.md`'s Current project
section works and has been used in anger.

**It is not a verification claim.** `tests/golden.py` plus ten unit suites cover
a lot, but not the chat turn, `:recall`/`:remember`, `:export`, the picker or
`:routine` — those are verified by hand. v1.0 is where that changes.

Chat client, wiki-backed RAG memory, tool calling behind a file jail, routines
that run on command, a filing pipeline, and a cat on the splash screen.

> *Note: Created the first roadmap to coordinate cfc going forward. Declared v0.1 and started using Git Tag. Previous changes were too random in direction, scope and planning; the roadmap is created to fix that before it breaks cfc. There is room for delay before V1.0 and plenty of ideas past that.*
```
／l、／\
(=ↀ▂ↀ=)  'it hurts, please make v1.0 come quickly'
l  ~ ~~\
じしfー,)ノ
```
---

## v0.2 — Retrieval you can trust — **complete, 2026-07-21**

Recall returned nothing for good queries. Nothing that depends on memory was
trustworthy until that was fixed, which is why it went first.

- **The 0.969-vs-1.036 discrepancy is resolved, and the premise was wrong.**
  `MAX_DISTANCE = 1.024` and its "0.111-wide gap" were measured on the
  **Anthropic export** and recorded as wiki numbers. Nothing had regressed — the
  wiki corpus has measured the same distances since it was created, verified
  against the rolling backups. The lesson kept: **a tuned constant must record
  which corpus it was measured on.**
- **The floor was reframed rather than re-tuned.** It turns out it cannot judge
  relevance at all: on this corpus, answerable and unanswerable questions
  interleave — a guitar-tuning question scores better than a real question about
  the wiki's own contents. There is no threshold, and a relative metric doesn't
  rescue it either. So the floor is a **lint filter** now (1.08), set to admit
  generously, and `recall.py`'s grounded synthesis does the judging. The old
  value was losing 4 of 20 real query phrasings.
- `search()`'s over-fetch window widens until it is provably deep enough. The
  flat `k*4` could return zero wiki hits purely because the window filled with
  chat chunks — and that got worse every day the chat log grew.
- `chunk.py` seeks to word boundaries at both edges; corpus re-chunked and
  re-embedded. 22 of 26 chunks used to open mid-word.
- `tests/test_chunk.py` added, and checked against the old chunker to confirm it
  actually fails on the bug.

**Why the chunker fix belonged here and not later:** the floor is a property of
the embedding geometry *and* the corpus. Re-chunking changes the corpus, so
fixing the chunker later would have invalidated this version's floor and bought
a second measurement run. It landed first, and the floor was measured after it.

Backlog cleared: mid-word overlap, `MAX_DISTANCE`, the over-fetch edge.

**Also this session, outside the codebase:** the Obsidian vault is now a git
repo — text tracked, binaries ignored, `.git` relocated to `~/vaults/wiki.git`
via a `gitdir:` pointer so Obsidian never sees it and git isn't crawling the
`/mnt/c` bridge. That's what unblocks `:wiki diff` in v0.3. The README explains
the setup; it has no local-only history backup yet (see v1.0).

> *Note: to be written.*

---

## v0.3 — The shell

The parts around the app rather than in it: getting in, typing, and now seeing
what changed in the wiki.

- **`:wiki diff` / `:wiki commit`.** Mirrors `mover.py`'s pattern: a code-driven
  action scoped to a fixed root (`WIKI_DIR`), not an LLM tool call. Shows what
  changed in the vault repo and commits it from inside the REPL.
- **Launcher.** A shortcut on the taskbar/desktop opens cfc in an Ubuntu
  terminal. Checks LM Studio: not running → start it; running without the
  embedding server → tell it to serve.
- **Terminal input.** Click to position the cursor. Rework `:attach`
  autocompletion, including making it look in the vault first and the repo
  second — it currently misses vault items it would find under the same name in
  the repo.

Mostly outside the Python codebase, so it's low-risk work after a heavy v0.2.
The launcher retires the class of failures where the embedder simply wasn't
running, which everything memory-shaped quietly assumes away.

**Why `:wiki` sits here rather than in v0.6, where it's actually needed:** it's
useful the moment pages get edited by hand, which is now — not only when a model
starts proposing changes. And proving the plumbing a version early de-risks
v0.6, which would otherwise be building the review step and the thing being
reviewed at the same time.

---

## v0.4 — The screens

- **Splash:** animate the cat across its three frames, add more pixel art.
- **Selection screen:** 10 most recent chats and the last 5 routine runs. Chats
  show name, attached prompt, token usage, message count. Routines show a
  freshness signal from their log — green <24h, orange 24–48h, red >48h. Only
  the commands that belong on that screen.
- **Chat screen:** a curated command list, not all of them. A new chat states
  (not warns) that no system prompt or persona is attached and lists what's
  available. A continued chat shows the attached prompt, persona, attached
  files, and tokens so far against the context window.
- **Token counter colours:** green <15%, orange 15–35%, red >35%. Thresholds in
  `config.py`. Percentages stay honest; only the colours change — a 1M-token
  context claim isn't trusted.

Backlog swept here because it's adjacent, not out of tidiness: **routine runs
cluttering the hub** (the selection screen has to tell a routine run from a chat,
so it needs the marker regardless — and `chunk.py` derives `source` from the
session's provider, so whatever marks a routine session has to say on purpose
what that does to the memory index), **tool-path reasoning printing in full**,
and **`longcat-2.0`** sitting in `MODELS` unable to chat.

---

## v0.5 — The scheduler

Wire an OS scheduler to a `--run-routine <name>` flag on `main.py`.
`run_routine()` is already the entry point it calls. `trigger` (HHMM) and
`on_failure` are already stored and parsed, waiting to be honoured.

**No in-process timer thread** — see `HANDOVER.md`. Needs the routine-session
marker from v0.4, because this is when the volume arrives. Blocks both remaining
feature versions, which is why it sits ahead of them.

---

## v0.6 — Wiki automation

Tested automation for writing and moving wiki pages.

- A drafter writes new pages from notes in atomic template style.
- It **suggests**: which pages to add in full, which to split, which in part,
  what needs relinking, what needs a different title.
- Human approves or declines. The mover carries it out, from tags and proposed
  location.

**The design problem this version has to solve properly:** `mover.py` refuses
wiki destinations outright today, and for a good reason — writing a page there
changes the corpus while the index doesn't know, so recall keeps answering from
a stale copy with no signal that it's stale. v0.6 is the version that resolves
that (most likely: a move into the wiki triggers a re-import). It is not the
version that quietly deletes the refusal.

Builds on `:wiki diff` from v0.3 — reviewing a proposed page as a diff before
accepting it is the whole approval step, and by here it should already work on
pages Cas edited by hand.

---

## v0.7 — Tiered memory

Same mechanics, but editing a rolling journal, diary style: days 1–5 short term,
6–25 medium term, >25 long term. The LLM drafts suggestions, the human approves,
a script moves.

Last of the feature work because it depends on all three of v0.2 (recall
actually working), v0.5 (it's a nightly job) and v0.6 (the same draft → approve
→ move shape, proven once already).

---

## v1.0 — Hardening, and a decision

No new features.

- The remaining backlog: the dangling `session_id` root cause in
  `import_anthropic.py`, and the `write_file` relative-path question.
- **Document the skeleton around cfc**, not just the app: the vault and its
  repo, the inbox/outbox convention, where the embedder lives, what backs up
  what and what doesn't. The README's vault-git section is the first piece of
  this. The gap it closes: cfc is understandable from its own source, but the
  system it sits in — three storage locations, two machines' worth of paths, a
  backup that covers files and not history — is currently only in Cas's head and
  in `HANDOVER.md`'s asides.
- **A remote for the vault repo.** `~/vaults/wiki.git` sits on ext4, outside the
  Windows daily backup, so a WSL reinstall keeps every note and loses every
  commit. Wants a decision on whether the `02 areas` medical material is going
  to someone else's server, private repo or not.
- The DB-layer rework `HANDOVER.md` has been anticipating. The intended shape is
  recorded there: SQLite stays the source of truth, sqlite-vec is an index over
  it.
- Test coverage for the paths currently verified by hand — the chat turn,
  `:recall`/`:remember`, `:export`, the picker, `:routine`.
- **Embedding server:** local, every backlog issue closed, updating the SQL and
  wiki db frequently. Smooth rather than smart — the pipeline correct, tweaked
  later. A system that absorbs a small daily stream of information, recalibrates,
  and keeps working.

**And the decision, parked here on purpose:** whether the repo goes public. Two
questions, both answered at v1.0 and not before — is it solid enough, and is it
sanitized enough (`config.py` is gitignored, but that's a claim to verify, not
assume). Deliberately deferred so it stops taking up room in the meantime.

---

## Beyond v1.0

Not scheduled, not ordered — the pile of things worth wanting.

- Vision for the model.
- Drag documents and files into the terminal to share them.
- Select text in chat, right-click to copy.
- A custom spinner.
- More borders and divisions in the chat. Treat reasoning that follows a tool
  call differently from ordinary reasoning — tool reasoning is the useful kind.
- After an AI turn completes (all tool calls, full message), refresh and stack
  the AI messages in borders, with the tool calls and reasoning shown alongside
  but smaller.
- STT and TTS.
- Agentic reach: email, Discord, Telegram. Think through the use case for giving
  it keyboard and mouse control.
- Let the model search the internet, then use a browser.
