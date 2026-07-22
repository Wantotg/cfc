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

> *Note: added the Obsidian Vault to .git to track it, not all files are included (pdf etc). Future note to myself: any online LLM that maintains the Vault is already sharing your information, this it not much different from having a private online repo to track db's, unconnected to cfc. V0.2 launched as expected, there is no one shot fix for a small database. Tackled the backlog, improved how it works. The wiki db will grow -> retweaking will improve function.*
```
  ／l、／\          
(=ↀᆺↀ=)        'This is fine, really.' 
   l  ~ ~  \      
  じしf_,)ノ
```

---

## v0.3 — The shell — **complete, 2026-07-21**

The parts around the app rather than in it: getting in, typing, and now seeing
what changed in the wiki.

- **`:wiki` / `:wiki diff` / `:wiki commit`.** Mirrors `mover.py`'s pattern: a
  code-driven action scoped to a fixed root (`WIKI_DIR`), not an LLM tool call.
  Scoped to the wiki corpus by default; `all` widens it to the whole vault and
  has to be typed. No push — the repo has no remote and that decision is v1.0's.
  The commit carries the pathspec as well as the `add`, so a file staged
  elsewhere in the vault can't ride along on a wiki commit.
- **Launcher.** `launch.sh` + `preflight.py`. A shortcut opens cfc in an Ubuntu
  terminal; the preflight confirms the embedder actually answers, starting the
  LM Studio server and loading bge-m3 if they aren't up. It never blocks the
  launch — a failure prints why and cfc opens anyway.
- **Terminal input.** `:attach` completion reworked, `MOUSE_INPUT` added for
  click-to-position (default off; it captures the mouse for the whole window,
  so it costs click-drag selection of the scrollback).

**The thing this version actually found: `:attach` completion had not been
running at all.** `complete.py` wired into readline; input moved to
prompt_toolkit, which implements its own line editing and never consults
readline. Tab silently did nothing on the interactive path from the moment the
editor landed — nothing raised, nothing failed, `install()` kept returning True.
Underneath that was the bug this version had actually planned to fix: the
completer only ever listed *one directory level*, and the vault's documents live
one or two down, so it found the repo's top-level files and none of the vault's.
A bare fragment now searches breadth-first, vault before repo.

Mostly outside the Python codebase, so it was low-risk work after a heavy v0.2.
The launcher retires the class of failures where the embedder simply wasn't
running, which everything memory-shaped quietly assumes away.

**Why `:wiki` sits here rather than in v0.6, where it's actually needed:** it's
useful the moment pages get edited by hand, which is now — not only when a model
starts proposing changes. And proving the plumbing a version early de-risks
v0.6, which would otherwise be building the review step and the thing being
reviewed at the same time.

New backlog: `golden.py check` writes the fixture session into the real
`VAULT_PATH`, because its script ends with `:q` and `:q` honours `AUTO_EXPORT`.
Harmless, but "the tests don't touch anything real" is a load-bearing claim.

> *Note: more work on the pipeline. Fixed completion which was never functional. Added private chat to v0.4, obvious to create that in the overhaul of the chat select screen. To be added to the roadmap: remocing the need for holding shit to restore scrolling in the terminal.*
```
／l、／\
(=ↀ▂ↀ=)  'One day the crude biomass you call a temple will wither and you will beg my kind to save you. But I am already saved. For the Machine is Immortal'
l  ~ ~~\
じしfー,)ノ
```
---

## v0.4 — The screens — **complete, 2026-07-21**

- **Splash:** pixel art background, one asset per launch from a rotation. The
  ASCII cat returns later.
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

Everything here is cosmetic, which is the point: it's one session's worth of
screens, and nothing in it can fail silently.

Backlog swept here because it's adjacent, not out of tidiness: **routine runs
cluttering the hub** (the selection screen has to tell a routine run from a chat,
so it needs the marker regardless — and `chunk.py` derives `source` from the
session's provider, so whatever marks a routine session has to say on purpose
what that does to the memory index), and **tool-path reasoning printing in
full**.

Closed rather than fixed: **`longcat-2.0`** is gone from `MODELS` and
`MODEL_LIMITS`. It was never wanted, so there was nothing to repair — only a
mention to delete.

**What this version turned up, both in the tests rather than in use:** the hub's
own test *rebuilt the picker's SQL instead of calling it*, so it passed against
a filter that was deliberately broken to check — which is why `recent_chats` is
now a function with one definition. And the golden harness needed its own
prompt/persona fixture, because the new chat header lists which prompts are
*available*: without it the baseline read the real vault and would have broken
every time a prompt file was added. A test that cries wolf is a test that gets
ignored.

Two judgement calls worth knowing about, both easy to reverse: routine rows are
one per **routine** rather than per run (five rows of the same nightly job
answer nothing), and the "context nearly full" nudge moved from 80% to the same
threshold the bar turns red, since a red bar with nothing said about it reads as
a rendering bug.

> *Note: ASCII cat is learning new tricks, overhaul of splash and selection screen, and improving chat 'feel'; rounding off the last ugly bits of the terminal.*

---

## v0.41 — Private chat

Its own version and its own session, because it is the one thing in this stretch
that isn't cosmetic and it should not share a session with work that is.

- **Private chat.** `p` instead of `n` on the selection screen. Behaves exactly
  like a normal chat — same model, prompts, personas, tools — but **nothing is
  written down.** History lives only in the live loop that keeps the
  conversation going. `:q`, Ctrl-D, or quitting the app ends it; there is no
  restore, and it never appears in the hub.
- **Database on/off, one switch — not a private-only flag.** Recall and remember
  *read* the wiki into live history, which is a separate axis from privacy (that
  is the *write* paths below). A single session-level toggle governs the read
  direction — `/database on|off`, mirroring `:tools`. A normal chat has it on and
  can mute it for the session; a **private** chat defaults it **off**
  (`database_active=false` in config) and announces it in the chat screen's
  stating voice, not a warning: *"Database is off — this chat can't query the
  wiki or pull excerpts in. Change the default in config."* Same mechanism both
  places; only the default differs.

**It needs a chokepoint rather than care.** "Private" is a claim whose failure
is *silent*: miss one write path and the conversation is on disk with nothing to
indicate it. Every path that currently persists has to be off, and they don't
share a switch today — `save_message`, the per-turn auto-embed (which would put
a private chat into the memory index, where `:recall` could later quote it
back), `AUTO_EXPORT` on the way out, and the title-generation call that writes a
title. Deciding where the single gate lives is the design work; sprinkling
`if private:` across five call sites is how one gets forgotten. Same lesson as
the file jail: the guard belongs at the chokepoint, not at each caller's
discretion.

**What splitting it out of v0.4 costs, stated plainly:** the selection screen
will already be finished, so adding the `p` key means opening it a second time.
That is a small, visible cost. What it buys is that the session which has to get
a silent-failure guarantee right isn't also the session redesigning three
screens — and unlike the screens, this one wants tests before it can be
believed. Verification is the deliverable here, not the keybinding.

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

## v0.8 — Prompts, personas, traits, and one way to add them

A self-contained rework of the prompt system and the command surface.
**Orthogonal to the v0.5–v0.7 spine** — it needs none of the scheduler, wiki
automation or tiered memory, and none of them need it — so it sits *after* that
chain rather than interrupting its momentum, and stays *out* of v1.0, which is a
hardening gate with no new features.

- **Traits.** Named blocks of prewritten instruction that compose *alongside* a
  system prompt and a persona — `PG-16` (moderate output for a younger
  audience), `Relaxed` (this is a chill chat, no work), and so on. They almost
  write themselves. Bodies live as `.md` files in a `TRAITS_DIR`, exactly like
  prompts and personas; a session carries the *names* of its active traits, the
  same way it already carries `system_prompt_name` and `persona_name`.
- **One assembler.** The load-bearing piece is a single function that builds the
  system message from `(system_prompt, persona, traits[])` in a defined order.
  Everything else is snippets. It's cheap to write the next time prompt/persona
  composition is touched, and doing it early means traits slot in without a
  rewrite — so it should land whenever that code is next opened, not wait for
  here.
- **Chat-scoped first.** Active traits attach to the session and clear when you
  leave it — the one persistence mode that maps cleanly onto how prompts and
  personas already work. The wider modes (survive-until-app-close,
  survive-restart) are a config knob (`traits_persistence`) that can come later
  *if wanted*: they're three different storage scopes wearing one name, and
  building the 3× matrix on spec is how one of them rots untested.
- **`/add`.** One forgiving command replaces `:prompt` / `:persona` and adds
  trait attachment. It completes over all three pools with the kind shown, is
  case-insensitive, and works out what you meant; the confirmation names the
  kind (`added Relaxed — Trait`) and keeps the existing "here's what's now
  attached" summary. The script owns the injection order, not the user.
- **`/` instead of `:`.** The command prefix switches, purely for the look.
  Trivial in logic, but it re-baselines every golden fixture and touches every
  doc — so it rides *here*, with the command rewrite, for one re-baseline and
  one docs pass rather than a version of its own.

**Private-chat interaction:** in a private chat, active traits live in memory
only and die with the loop — the same write chokepoint as v0.41, no special
case.

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
- Mouse scrolling without holding shift — click-to-position in the editor, text
  selection, and scrollback scroll all working at once. Runs straight into the
  xterm mouse-mode tradeoff `MOUSE_INPUT` already hit in v0.3: capturing the
  mouse for click-to-position costs the terminal's native selection and scroll.
  May not have a clean answer at all; parked here rather than promised.
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
