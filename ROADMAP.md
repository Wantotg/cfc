# Roadmap

Where cfc is going, and in what order. Cas's document — a session may *propose*
changes here, it doesn't make them.

`BACKLOG.md` is what's owed; this says which version owns which item. A feature
session is not obliged to clear unrelated debt, but debt that's genuinely
adjacent to the version's work gets swept in it.

Each version gets a short note from Cas, in his own words, about what landed and
what it opened up. That note is the point of numbering this at all.

**This file is public — it ships with the repo.** A shipped version gets its
full entry here: what landed, the completion date, Cas's note. A version still
ahead gets only its number and title, as a placeholder — the actual planning
(design reasoning, ordering, dependencies) lives in `ROADMAP_PRIVATE.md`,
gitignored, and moves over here in full the day the version ships.

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

> *Note: more work on the pipeline. Fixed completion which was never functional. Added private chat to v0.4, obvious to create that in the overhaul of the chat select screen. To be added to the roadmap: removing the need for holding shit to restore scrolling in the terminal.*
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

## v0.41 — Private chat — **complete, 2026-07-22**

Its own version and its own session, because it is the one thing in this stretch
that isn't cosmetic and it should not share a session with work that is.

- **Private chat.** `p` instead of `n` on the selection screen. Behaves like a
  normal chat — same model, prompts, personas, read tools — but **nothing is
  written down.** It runs against an in-memory database, so `:q`, Ctrl-D, or
  quitting the app ends it for good; there is no restore, and it never appears
  in the hub. Two deliberate carve-outs: **model file-writes are blocked** (a
  private chat leaves zero disk artifacts), and an **explicit `:export` is
  honoured** (a user-typed command, unlike a model-proposed write). No title is
  generated — a chat that can't be restored has nothing to label.
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

> *Note: Learning what tagging actually means, so I could finally fix a typo in note V0.3. Balthazar alerted me to an actual mouse during development; he hasn't caught it and I haven't trapped it yet. Signs from above? Added v0.8 to the roadmap with staged expansion beyond 1.0 as small quality of life features.*
```
               )\._.,--....,'``.    'VIOLENCE: REQUIRED. VIOLENCE: ACQUIRED. '  
 .b--.        /;   _.. \   _\  (`._ ,.
`=,-,-'~~~   `----(,_..'--(,_..'`-.;.'
```
---

## v0.5 — The scheduler — **complete, 2026-07-23**

Routines can now run without anyone typing anything. Plus the fix for the 400s
that were making tool turns unreliable — which went **first**, because routines
run through the same tool loop with a larger budget, and a loop that
intermittently 400s is not a thing to put under a job that fires at 03:00 with
nobody watching.

**The tool turn's two budgets.** Three separate faults were wearing one
symptom: a provider 400 mid-turn, only ever when the model was let loose on a
tree of files.

- **An interrupted tool turn poisoned the session in place.** The assistant
  message carrying the tool calls goes into the live history *before* they're
  dispatched, so Ctrl-C at the approval prompt left calls with no results — a
  conversation the API rejects forever after. Reopening the session repaired
  it, which is exactly what made this look intermittent and provider-shaped
  rather than local and deterministic. Every call now gets exactly one result
  on every path out of the loop, exceptions included.
- **The call ceiling counted loop iterations, not calls.** A model asking for
  four reads in one message spent one of eight, so eight iterations could be
  thirty reads at 30,000 characters each — around 225k tokens, re-sent on every
  subsequent call. That is where the 400s complaining about `max_tokens` (a
  setting cfc doesn't send) came from.
- **Nothing bounded a turn's total tool output**, which is the thing that
  actually grows the request. Now 120,000 characters. Spending it withdraws the
  tools for one final call rather than cutting the turn off, so the model
  answers in its own words.

Raising the ceiling *alone* — the obvious fix — would have made it worse. The
two budgets had to land together, and the ceiling is generous (25, up from 8)
precisely because the second one makes it affordable. Roam widely, read
narrowly. The model is now told both budgets up front and nudged when its calls
run low, as riders on the request rather than lines in the conversation.

The third fault is provider-side and still open — see `BUGS.md`. What changed
is that it's now *distinguishable*: a failed request reports what was in flight
beside the provider's own words, where before all three arrived as one
indistinguishable `HTTP 400`.

**The scheduler.** `main.py --run-due` on a fixed tick, from Windows Task
Scheduler.

- **One OS entry covers every routine, forever.** cfc decides what's due from
  each routine's own `trigger:` field and its run log. One entry per routine
  was the rejected alternative: it makes `trigger:` decorative and puts the
  real schedule outside the vault, free to drift from the file that claims to
  hold it.
- **The run log is the only state** — no "last tick" file, no table. A
  scheduled run is a fresh process with nothing to remember, and a second
  source of truth is a second thing to get out of step.
- **Catch-up is same-day only.** Off at 03:00, back at 10:00: runs once, late.
  Off for three days: runs once, not three times.
- **`on_failure` is honoured at last**, bounded at 3 retries a day. Without the
  bound, a routine failing for a permanent reason retries every 15 minutes
  until midnight at full API cost, unattended — the one failure a scheduler can
  cause that's worse than not running.
- **The idle tick is silent, cheap and exits 0.** It runs ~90 times a day.
- Not cron in WSL: Windows shuts idle WSL instances down and cron dies with
  them, so a 03:00 job would run only if a terminal happened to be open.

**Not done here, and deliberately:** the Task Scheduler entry itself, and
setting a trigger on a routine. Both are Cas's to do — the README has the
command — and until then a tick correctly finds nothing due.

> *Note: 0.5 is a small update, but came with bug fixes and small improvements, tool calling in chat is now more generous. More documentation and planning, the road to 1.0 is clear and most routine templates are functinoal and low on tokens.*
```
ᓚᘏᗢ 'Small update'
```
## v0.6 — Wiki automation

## v0.7 — Tiered memory

## v0.8 — Prompts, personas, traits, and one way to add them

## v1.0 — Hardening, and a decision

---
