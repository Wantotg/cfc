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

## What "feature complete" means here

**`BUGS.md` is empty.** Every claim made up to and including that version does
what it says. `BACKLOG.md` does *not* have to be empty — that file is, by its
own definition, things that still work and are merely owed.

It's a line in the sand rather than a promise to stop adding features. cfc has
shipped features that weren't fully functional as intended; a feature-complete
version is where that stops being true. Two are planned: **v1.0**, minimal cfc,
and **v1.9**, cfc as wanted. **v2.0** rebuilds on what the first two taught.

Past v1.0 the arc is planned but not committed to numbers, so it isn't stubbed
here yet.

## The vault is a separate project

The Obsidian vault cfc reads and writes has its own repo and its own roadmap.
The seam: **cfc ships the mechanism, the vault ships the words** — safe code
defaults, gate text and chat mechanics here; templates, structure and
walkthrough material there. The two are not worked on equally. When a version
lines up with something on the vault side, its note says so.

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
## v0.6 — Wiki automation — **complete, 2026-07-23**

The drafting pipeline's last mile: a page the model proposes can now be filed
into the wiki corpus, with the recall index kept honest.

- **The mover files into the wiki now, where it refused outright before.** The
  refusal existed for a real reason — a page landing in the corpus while the
  index is unaware makes recall answer from a stale copy with no signal it's
  stale — so it was *replaced*, not deleted. `99 outbox/wiki/` is a proposal
  folder: a draft there is wiki-bound by location, no `destination:` needed.
  Filing stamps a `YYYYMMDDhhmmss` id (by code, at approval — never the model's
  job), names the page `<id>.md` to match the vault, and refuses a page whose
  id already exists rather than clobbering it.
- **The staleness is loud, with a one-command fix.** Filing sets a marker that
  `:file`, `:outbox` and `:wiki` all surface; `:updatedb` re-imports the wiki
  and clears it. "Move, then explicit `:updatedb`" — the reindex is a visible
  step, not something hidden inside the move.
- **Routines are hand-authorable again.** An id is coerced to a slug at load
  instead of failing validation, so `id: note reader` typed in Obsidian just
  works — the file is left as written, the runtime handle is the slug.
- **`:wiki commit` says how.** The `<message>` placeholder read as if it wanted
  special syntax; the empty-message case and the loop's hints now show a worked
  example.

The full approve-at-each-stage loop: the writer drafts atomic notes, you
approve them into the reader's inbox, the reader suggests wiki pages, you
`:file` them in and `:updatedb`. The mover does the deterministic half; the
model only ever proposes.

**Not done here:** the routine task-prompts are still being finished, and the
full loop against the live embedder is verified in use rather than in tests.

> *(the entry's there, note-shaped hole at the end where the cat goes) Ahh found it! 0.6 completes the first version of the wiki db. The models write, the human (dis)approves and the script timestamps and moves the files.*
```
 /\_/\   'PLUS ULTRA'
( o.o ) 
 > ^ <
```

## v0.6.1 — Routine models, and a forgiving `:model` — **complete, 2026-07-24**

A small reliability release that came straight out of using v0.6's routines in
anger. One thinking model (`glm-5.2:thinking`) turned out to stall on this
provider's current quantization — it returns an empty completion every time and
the run fails loudly, which is v0.6's re-roll working, not a new bug. Other
thinking models run routines fine, so the fix isn't to retry harder; it's to
stop an unattended job from ever landing on a model that stalls, and to make a
loose model name forgiving so a typo doesn't masquerade as a provider fault.

- **`ROUTINE_MODELS` — a vetted list, and the default a scheduled run uses.**
  Its first entry is what `--run-due` runs on when no model is passed, closing
  the hole where a scheduled routine silently inherited the *interactive* chat
  default (which may be the very model that stalls). An on-command `:routine`
  still uses the session model but nudges (y/n) when it's off-list. Membership,
  not a "thinking-model" guess — some thinking models are fine, so the list is
  the judgement and the code trusts it. Unset ⇒ falls back to the old default,
  no nudge.
- **A failed routine's log line now names its session** (elapsed + `session N`),
  matching the success line. A scheduled failure used to leave the session id
  only on the terminal, so the transcript of the run you most wanted to open was
  unfindable — and three distinct failures read as one repeated session number.
- **`:model` forgives a loose query.** An exact id switches silently; a single
  strong match asks "did you mean X?"; several offer a numbered pick; a
  near-miss is caught by a fuzzy nearest, so a one-character slip
  (`kimi-2.6` → `kimi-k2.6`) is offered rather than 400ing at the provider a
  turn later; only a genuinely unrecognised id is set raw, with a note. Matches
  your configured models only — no live catalogue — and an unlisted model is
  still reachable by typing it in full.

Deferred, not forgotten: a **per-routine `model:` field** (a routine declaring
its own model in frontmatter) is the tidier long-term shape but touches the
routine round-trip and its tests, so it's parked for a future feature rather
than bolted on here.

> *(note-shaped hole for Cas) Almost trapped by my version conventions. Testing different models on the same task was promising, routine functionning improved with some fixes and quality of life features. Testing continues before the small update to 0.7, preparing for the consolidation of mechanics and a smoother user experience in 0.8*
```
 /\⠀⠀/\  'There are 2 r's in strawberry.'
( ◍•⩊•◍)
/ ⊃🍓⊂\
```
## v0.6.2 — Groundwork for tiered memory — **complete, 2026-07-24**

A patch release that clears the ground v0.7 builds on: tiered memory reuses the
wiki review-and-move pipeline and runs as an unattended routine, so the edges of
both got sharpened first. Most of it came out of using v0.6.1 in anger.

- **`:wiki` grew a `<scope> <granularity>` grammar.** Scope picks the corpus
  (`wiki` default, `journal` reserved for v0.7, `vault` replacing `all`);
  granularity `file` diffs or commits a single picked file, not the whole set —
  the per-file review v0.7's approve step needs. `:wiki commit vault` now asks
  before the whole-repo sweep. Filing (`:file`) stays separate from committing,
  so the `:updatedb` re-import still sits between them.
- **A routine can pin its own model** (`model:` frontmatter) — the tidier shape
  that v0.6.1 deferred. Resolves routine pin › session model › vetted default, so
  a scheduled job no longer has to run on the single global default.
- **`:model` backs out of a model the provider rejects.** Switching to an
  unlisted id that then errors on its first turn reverts to the model you were
  on, instead of stranding the session on a dead id that 400s every turn.
- **The scheduler tick is logged and the window defaults hidden.** `run-due.sh`
  writes to `~/.cfc/schedule.log` (rotated, one heartbeat per tick), so a failure
  before cfc even starts isn't lost with the console; the README now defaults the
  Task Scheduler entry to run with no window, which the log makes safe.
- **A routine reports two outcomes, not one.** `ok`/`failed` is loop health; a
  separate `review` flag marks a run that finished but whose own words say it hit
  a wall ("outside my allowed roots"). The hub and `:routine` show a yellow
  *review* — a job that logged a clean `ok` while doing nothing is no longer
  invisible.

> *(note-shaped hole for Cas) some quality of life improvements to help with routines, and the management of the flow of information in a established vault. Keeping it running shouldn't be a chore.*
```
  |\__/,|   (`\ "More notes on catnip! Grow the wiki db!"
  |_ _  |.--.) )
  ( T   )     /
 (((^_(((/(((_>
```
## v0.7 — Tiered memory **complete, 2026-07-24**
Same mechanics, but editing a rolling journal, diary style: short term,
medium term, long term. The LLM drafts suggestions, the human approves,
a script moves. 
Keeping a journal that references the days correctly, rotates correctly,
and corrects for pauses in activity was quit a logig puzzle. 
Further testing will demonstrate where it fails, so we can improve it.

Last of the feature work because it depends on all three of v0.2 (recall
actually working), v0.5 (it's a nightly job) and v0.6 (the same draft → approve
→ move shape, proven once already).

> *New Opus right at the start of the session was nice, considering we ended up redesigning, discussing, tweaking and testing before shipping, good start.*
```
  /\_/\
 ( o_o ) 'OPUS POCUS PILATUS PAS'
  (>x<)
```
## v0.8 — The command surface **Complete, 2026-07-25.**

A rework of the command surface. The prompt/persona/trait composition system
rides along as the vehicle, not the headline — success measured in verbs
removed, not features added. **33 verbs → 21**, one grammar, and a new
attachable feature now costs no new verb.

```
/verb [kind] [target] [message]
```

- **Three questions, three commands.** `/help` (what can I type), `/list <kind>`
  (what exists), `/status` (what's active right now). Everything else changes
  something. `/status` alone absorbed eight bare commands, `/list` seven
  listings.
- **`/add` and `/remove`, across five mechanisms.** Four verbs used to put
  something on a session — `:prompt`, `:persona`, `:attach`, `:tag` — and five
  took it off. Now two do, over one resolver: case-insensitive, a unique partial
  resolves, and ambiguity is a numbered pick rather than a guess. A bare name
  walks the pools by priority (System > Persona > Trait); a path-shaped argument
  is an external file.
- **Traits.** The third pool — small named blocks that compose *alongside* a
  system prompt and a persona, and unlike those two they stack. One `.md` file
  each, exactly like prompts and personas: the filename is the name, no id, no
  combined file. The session stores the *names*, so editing a trait file changes
  what every session carrying it sends.
- **One assembler.** `assemble_system(system_prompt, persona, traits)` builds the
  request's system layers in one place, so the fourth layer is added there and
  not in each turn path. Extracted first on purpose: it is what made unifying the
  three pools safe instead of writing the duplication a third time.
- **The dispatcher, rewritten first.** `parse(line) → Cmd` plus a verb→handler
  table replaced a chain of `startswith` tests whose correctness depended on the
  order they were written in — the trap that made `:attached` read as attaching a
  file called "ed", and `:routines` take the whole app down. Exact matching
  cannot have either bug.
- **`/` instead of `:`.** One constant in the parser, and it touched no handler —
  which was the argument for rewriting the dispatcher first rather than last. The
  old prefix still works for this version and says so once per session; retired
  verbs tell you what replaced them instead of being sent to the model as a chat
  message.
- **Private chat inherits all of it with no `if private` branch** — the test that
  the design holds. `/new p` starts one from inside a session.

> *(note-shaped hole for Cas) Roadmap gives me rerolling energy "why not start again and do it right from the ground up, now that you know what to do?" I don't know what I'm doing. Feature complete first, before looking back or ahead.*

```
ฅ^•ﻌ•^ฅ 'Re-roll! Re-roll! Re-roll!'
``` 

## v0.8.1 — Four things that were simply wrong — **complete, 2026-07-26**

A patch release out of the v0.8 testing pass, and the first one where the list
came from a scratchpad kept *while using the thing* rather than from reading the
code. Nothing new: four defects, each of which looked fine in isolation and was
wrong the moment you compared it to something next to it. The rest of that
scratchpad adds claims and waits for v0.9.

- **The clock was two hours out, and two panels on one screen disagreed.**
  `db.py` is the only module that stores UTC; routines, the scheduler, the mover
  and the backup rotation all store local time. The hub stacks Recent chats
  (from the db) directly above Routines (from the run log), so the two panels ran
  two hours apart — and neither looked wrong on its own, which is why it survived
  eight versions. One conversion point now, `ui.format_ts`, converting only when
  the stored value carries an offset: a naive timestamp is left alone, because
  assuming UTC would move the one set of times that was already right.
- **One numbering, everywhere.** The picker counted rows 1..n while `/list`,
  `/delete chat` and `/export chat` take a session id. The code even carried a
  comment warning that these were different numbers and that conflating them was
  how you opened the wrong session — which is exactly what happened, from the
  other direction: a row read as "3" typed at `/delete chat 3`, a command that
  destroys data. The picker shows and accepts ids now, and an id that exists but
  isn't listed is refused rather than resumed, since the hub shows chats only.
- **The token bar's empty state read as full.** The trough was `░`, which is a
  *fill* character — two dozen of them look like a bar with something in it, so a
  session 0.1% into a million-token context appeared meaningfully used. The
  arithmetic was right the whole time; only the empty state lied. Now bracketed
  whitespace, which cannot be misread.
- **An exact model name no longer opens a picker.** Model ids are
  `vendor/model` and nobody types the vendor, but only the full id counted as
  exact — so `deepseek-v4-pro`, which *is* a whole model name, matched three
  things and asked which one. An exact name now beats a prefix of a longer name,
  so `glm-5.2` means the non-thinking one rather than a question. Two vendors
  shipping the same model name still get the picker, which is what it's for.

Also here, and the reason this is a patch rather than a footnote: **the desktop
shortcuts are diagnosed.** Both were broken and it is one story — the shortcut
that works launches in the legacy Windows console, which isn't truecolor, and the
splash's box-average resample is only clean *on* truecolor by its own design; the
shortcut that would use Windows Terminal was losing its quotes before it ever
started. Written up in `BUGS.md` with the corrected command line. Not closed:
that needs a Windows shell, and it stays open until it has actually run.

> *(note-shaped hole for Cas) some more quality of life improvements and fixes that have 0.9 in mind.* 
```
⚞^. .^⚟ “The bureaucracy is expanding to meet the needs of the expanding bureaucracy.”
``` 
## v0.8.2 — The embedder answers, or says why — **complete, 2026-07-26**

The second patch off a scratchpad, and the pattern is now the point: both v0.8.1
and this one came from notes taken *while using cfc*, not from reading the code.
Two defects and four papercuts. Nothing new is claimed, which is what makes it a
patch.

- **`/recall` took four minutes to admit the embedding server was off.** One
  number was answering two different questions. httpx's `timeout=` sets
  *connect*, *read*, *write* and *pool* alike, and those measure "is anything
  there" against "is it finished yet" — so a single `timeout=60` made every one
  of four attempts wait out the full read budget just to discover nothing was
  listening. Connect is 5s now and read stays 60s: **11.1s instead of ~240s**,
  while a hundred-chunk import keeps the patience it genuinely needs. The live
  endpoint answers in 0.18s, so the short budget has 27× headroom.
- **A dead server stopped being retried like a busy one.** A 429 is a transient
  and waiting is the right answer; nothing listening on a port is a *state*, and
  asking four times gets one answer four times. Two budgets, two attempts rather
  than one only because a call can catch a restart.
- **And the spinner says so.** A spinner alone cannot distinguish "thinking"
  from "nothing is there", which is exactly what made an honest wait read as a
  hang. It's a callback rather than a print, because `embed.py` has no console
  and must not grow one — routines and imports run headless.
- **Ctrl-C during a recall exited cfc.** `KeyboardInterrupt` isn't an
  `Exception`, so a guard catching the latter never saw it, and it escaped the
  spinner and the session loop. Fixed at all three spinner sites rather than the
  one that was reported.
- **An unrecognised model offers the near misses.** `/model minimax 3` used to
  print "setting it anyway", 400 on the next turn, and auto-revert. It lists
  what you probably meant, with `[enter]` to force the raw name through anyway —
  because `MODELS` is not exhaustive and a valid unlisted id is a legitimate
  thing to type. This closes a question `BACKLOG.md` had been holding since
  v0.6.2, and closes it with neither of the two options that entry offered.
- **`/routines` was reaching the model.** An unrecognised verb doesn't error —
  it falls through as prose — so the plural cost an API call and a confused
  answer about routines. One line.

Also here, and larger than the display fix that found it: **`VAULT_PATH` is not
the vault.** Chasing "`/list routine` prints the whole mount path" turned up that
there was no vault-root setting anywhere in cfc. `ROUTINE_DIR`, `WIKI_DIR`,
`JOURNAL_DIR` and `MOVE_ROOTS` are each configured separately, every one of them
commented `<vault>/…`, describing a root that existed in the documentation and
nowhere in the code — while `VAULT_PATH`, which `/config` had labelled "Vault
path:" since v0.1, is the export destination and isn't inside the vault at all.
`VAULT_ROOT` now exists, display-only, and `/config` names both for what they
are.

> *(note-shaped hole for Cas) cleaning up known issues and bugs, fixing my dreadful version naming, again. Tying loose ends before getting tangled again.*
``` 
ฅᨐฅ "praise Ziu"
``` 
---

## v0.9 — Say which state you're in — **complete, 2026-07-27**

Planned as *The connection*: three items about the embedder, plus the hub help
screen and deleting `LEGACY_PREFIX`/`RETIRED`. It shipped as ten, because the
version was re-scoped around a different goal — **v1.0's window should inherit
an empty desk, so that its "only fixes, never adds" property is a real claim
rather than a backlog being cleared.** Every open item across `BUGS.md` and
`BACKLOG.md` was either fixed or explicitly assigned.

The widening is disciplined by a theme rather than a list, and it is
`HANDOVER.md`'s *"prefer the failure that is visible"* turned into a version:

> The traffic light, `/connect embedding`, the terminal-capability line, and
> zero-hit recall are the same sentence — cfc says which state it is in instead
> of returning a plausible nothing.

- **The connection, as one state machine.** A light on the hub, `/connect
  embedding`, and the launch check are three renderings of one function,
  `preflight.connection_state()`. No consumer forms its own opinion, because the
  failure worth designing against is a **green light over a dead server** — the
  one output nobody double-checks, since it is precisely the reassurance that
  stops you checking.

  It has **no cache**, and that came out of measuring rather than assuming: a
  real embedding call answers in 0.157s, and the 8s that made a live light look
  unaffordable was `probe` handing one number to httpx, which sets *connect* and
  *read* alike. Split into 0.5s and 8.0s — the same lesson `embed.py` learned in
  v0.8.2, one layer up — a dead port costs 0.5s, so the light can just ask. An
  answer you can always re-ask is one you never have to age.

  Five states, not three. `hosted` never shows a red light telling you to launch
  an app that has nothing to do with your endpoint, and `down` exists for when
  the process check itself could not be read — saying "LM Studio is running, its
  server isn't" without having looked is the confident wrong answer the whole
  feature exists to delete.

- **The two `preflight.py` fix paths that had never once run.** Open in
  `HANDOVER.md` since v0.7. All three states were driven: orange took `lms
  server start` to green in 1.4s, and red worked from a genuinely cold machine.
  `lms load` turns out to be near-unreachable, because LM Studio JIT-loads on
  demand — which is what proves `PROBE_READ = 8.0` is load-bearing and not
  slack: a cold load happens *inside* the read budget, so trimming it would turn
  every cold start into a confident red light over a working embedder.

- **Preflight says when the splash will band.** `COLORTERM`, `TERM` and rich's
  `color_system`, with a warning when they don't add up. Fails in the safe
  direction: the false positive is loud and self-correcting, the false negative
  is the status quo.

- **Recall says which kind of nothing it found.** Three outcomes used to produce
  one silence and only one meant "memory has no answer". They are separated at
  the exception, which is the only place they are cleanly separable — `embed.py`
  records which failure it saw *while catching it* and raises a type. The test
  that matters pins an error whose **message** is a perfect copy of the
  unreachable one and must not be reported as unreachable. A fourth state turned
  up while reading: an empty index is not a failed search.

- **The tool path offers the retry the streaming path offers.** It used to paint
  a blank answer panel. The policy is now one function both call, and it takes
  no argument identifying its caller — a shared helper that branches on who
  called it is two helpers wearing one name.

- **The model auto-revert arms on every switch.** It armed only for models *not*
  in `MODELS`, so it skipped the exact case it was built for: a dead id that
  *is* listed switched cleanly, armed nothing, and 400ed every turn with an
  error naming no model. Dropping `longcat` in v0.4 deleted the instance and
  left the class. `MODEL_LIMITS` and `TOOLS_MODELS` are also checked against
  `known_models()` at startup — a typo there is the genuinely silent one, since
  tools simply never turn on for a model you believe is covered.

- **`LEGACY_PREFIX` and `RETIRED` come out, and the old words become aliases.**
  The deletion and the promotion had to be one commit: `RETIRED` was what caught
  `/models`, `/prompts`, `/tags` and a dozen more, and an unrecognised verb is
  not an error — it falls through **to the model**, an API call and a confused
  answer each. That needed a grammar change nobody had anticipated: an alias
  value may now be a *phrase*, because `models` has to become `list models`,
  which a verb-for-verb alias cannot express. `detach` is the one word let go,
  its replacement taking `#<n>` and so changing the argument's shape.

- **Hub help (`h`), generated rather than written.** `HUB_KEYS` is the dispatch
  *and* the help's source, and the light's legend comes from the same mapping
  the light renders. A help screen is the artefact nobody re-reads, so the only
  safe kind is one that cannot be wrong.

- **The last three UTC timestamp sites read local time.** They survived v0.8.1
  because `format_ts` returns `YYYY-MM-DD HH:MM` and a site wanting only a date
  could not call it — so the fix is a second helper, `ui.format_date`, not a
  substitution. `[:10]` was never a cheap version of it: session #24 on the real
  database stores `2026-07-19` and is locally `2026-07-20`.

- **The archive split.** `BUGS.md` was 283 lines holding three live entries;
  `BACKLOG.md` 897 holding five. Closed entries now move to `legacy/` whole and
  leave no stub. Archived rather than deleted because `CHANGELOG.md` carries
  every fix but never the **original report**, and the symptom as first written
  is frequently the valuable half — sometimes its *wrong* premise is the finding.

- **The last provider-400 suspect, spent.** `api.wire_messages` drops an empty
  `content` from a tool-call message at the **wire boundary**, so both replay
  paths get it and neither has to remember. There is no test that it works and
  there cannot be: the bug has no reproduction. What it buys is that the list of
  things left to try is empty, which is a more honest position than a fix.

**What the version taught, which is not in the list above.** Four things the
plan had wrong were found by building or driving rather than reading: recall's
"routine half" does not exist, because no routine can reach recall; retiring the
old command words needed a grammar change; `lms load` is near-unreachable; and
`launch.sh`'s own comment claiming a cold `server start` brings up the app had
never been tested. Two live defects turned up that were on no list — four
`console.print` calls printing their own markup tags, one of them shipped in
v0.8.2 in the very line that release was named for, and a session in the real
database misdated by a day.

And one that cost something: `lms server start` failing three times in an
afternoon was written up as *"LM Studio cannot be started from WSL"* and filed
under **Rejected designs** — the section whose entire function is to stop the
next person trying. It removed a capability Cas relied on, and he noticed within
the hour. Three failures are not proof of impossibility about something that has
been observed working.

*[Cas's note goes here.] Added some, fixed some, broke some, fixed them again, ready to playtest to test weird things*
```
/•᷅‎‎•᷄\੭ "I"m not a cat, I'm a database."
```

## v1.0 — Hardening, and a decision

---
