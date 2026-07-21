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

> *Note: to be written.*

---

## v0.2 — Retrieval you can trust

Recall currently returns nothing for good queries. Nothing that depends on
memory is trustworthy until this is fixed, which is why it goes first.

- Resolve the **0.969-vs-1.036 discrepancy** in `BACKLOG.md`. First, before any
  tuning. A floor built on a number that doesn't reproduce will fail again
  silently.
- Re-establish `MAX_DISTANCE` on a measurement that holds.
- Widen `search()`'s `k*4` over-fetch window so a low `k` with a provider filter
  can't return zero rows just because the window filled with `source='chat'`.
- Fix `chunk.py`'s mid-word overlap slicing, re-chunk, re-embed.

**Why the chunker fix belongs here and not later:** the floor is a property of
the embedding geometry *and* the corpus. Re-chunking changes the corpus. Fixing
the chunker in a later version invalidates whatever floor this version
establishes and buys a second measurement run. Re-embedding is cheap now that
the embedder is local — it wasn't when that backlog entry was written.

Backlog cleared: mid-word overlap, `MAX_DISTANCE`, the over-fetch edge.

---

## v0.3 — The shell

The parts around the app rather than in it: getting in, and typing.

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
