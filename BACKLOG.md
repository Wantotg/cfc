# Backlog

Things found in passing and deliberately not fixed, so they don't get lost.
Nothing here is urgent — this is a hobby project and it all still works.

Add to this rather than fixing on the spot when something turns up mid-task.
`CLAUDE.md` is for how the project works; this is for what's still owed.

`TRACKER.md` (gitignored) indexes this file, `BUGS.md` and the roadmaps in one
line each, with the version an entry is assigned to. It says *where* and
*when*; the entries below say *what*. Each one carries its tracker id in the
heading — the id the playtest report gave it, unchanged thereafter.

## When an entry closes

**It moves to [`legacy/BACKLOG.md`](legacy/BACKLOG.md), whole, and leaves
nothing behind here.** This file holds open entries only. Full reasoning for the
rule is in [`BUGS.md`](BUGS.md), which changed the same way on the same day
(2026-07-27) — the short version is that `CHANGELOG.md` is the index of what
shipped, and the archive is where an entry's **original report** survives, which
`CHANGELOG.md` never carried.

**Closed at the split, so it is in the archive and not below:** *Retire the
`:`-command `startswith` chain for an exact-match table* — closed on
inspection, not by work. v0.8's `parse.py` already did it: `main.py` contains
zero `startswith(":` and asserts `set(HANDLERS) == set(VERBS)`.

**Partly carried over:** *Model selection is too generous* has shipped in
pieces (routine model selection, auto-revert, the near-miss picker). What is
left of it is the `[esc]` entry below, rewritten to be about the open half only.
The full entry with all its history is in the archive.

---

## D-11 · `/tools` puts two more config values in the golden baseline. 1.0, 29-07-2026

**Found:** 2026-07-29, immediately after fixing `D-01` — the re-recorded
baseline still carried two lines of Cas's config:

```
  read roots: <ROOT>, /mnt/c/Users/disse/cooking for cats
  write roots: /mnt/c/Users/disse/cooking for cats/99 outbox
```

**Same class as `D-01` and as the `config.py` scar it descends from:** *anything
a baseline pins that lives in config rather than in source is this bug.* Edit
your own `TOOLS_ROOTS` and `check` fails on lines that say nothing about the
code, which trains the habit of skipping a hunk in a `record` diff — and that is
the habit that one day carries a real regression past you.

**The obvious fix was tried and is wrong, which is why this is an entry rather
than a commit.** Repointing `WRITE_ROOTS` at a fixture under `tests/` raises
`ScopeError`: standing decision 4 refuses a write root that overlaps the cfc
source tree. The guard is right and the fix was wrong. Note the asymmetry with
`D-01`, because it is the thing to understand before trying again — `mover`
validates against its own `MOVE_ROOTS`, deliberately not `WRITE_ROOTS`, so a
fixture *inside* the repo is fine for the outbox and cannot be for this.

**So a fixture write root has to live outside the working tree**, which means a
temp directory in `golden.py`'s lifecycle. That is not hard, but it is a new
kind of thing for that file — every other fixture it owns is a path under
`tests/` it creates and deletes — and `SCRUB` already collapses `/tmp/...` to
`<TMP>`, so the determinism is free once the directory exists.

**Do not fix it by scrubbing.** `/tools` is in `SCRIPT` because its output is a
statement about the permission model rather than a status dump, and
read-roots-are-not-write-roots is the load-bearing half of that. A `SCRUB` rule
would keep the baseline stable while making the line say nothing, which is the
worse of the two failures: `D-01`'s cost was a diff you learn to skip, and this
would be a line you can no longer read.

**Not urgent.** It fails loudly, in the good direction, exactly like `D-01`.

## D-04 · `[esc]` doesn't back out of prompts, and can't while they're `input()`. 0.8.2 remnant

**Found:** 2026-07-26, Cas's 0.8.1 testing pass, as half of the `/model`
strictness ask. The other half shipped in v0.8.2 (the near-miss picker, the
dropped vendor prefix, lowercase `[enter]`); this is what was left.

Description: every prompt in cfc is built on plain `input()`, which reads a
*line* — it cannot see a bare Esc at all. Detecting one needs a keypress reader,
and Esc is the ambiguous key to pick for it: terminals send it as the prefix of
every arrow key, so a bare Esc is only distinguishable by a timeout. So decline
keys are still `[c]`/`[n]`.

**Worth doing properly or not at all**, because the value is *consistency across
every prompt* and not any one of them: the hub picker, `/file`, `/wiki`'s
pickers and the model prompts should all back out the same way.

**Where it lands (2026-07-27):** it is a terminal-stack change, and standing
decision 6 — prompt_toolkit and rich never drive the terminal at once — puts
that at **2.0**, alongside mouse support, scrollwheel and select-and-copy, which
the roadmap already says are one decision rather than a series of tweaks.
The knock-on: any 1.x screen that wants "Esc returns" backs out on a **typed
word** (`esc`, `back`, `q`) instead. Costs nothing, works today, and is honest —
those screens are command-driven already.

## D-02 · Processed notes stay in "00 inbox/notes" forever. 0.8, 24-07-2026
**Found:** 2026-07-24, wiring the journal cadence. Cas had already hit it — it's
in `st memory.md` for the 22nd: "routine read a stale note from the 24th because
it was still in inbox/notes."
Description: nothing removes a note from `00 inbox/notes` after a routine has
processed it, so the folder grows without bound and every run re-reads material
it has already written up.
Mitigated, not fixed: the ST prompt now tells the model a note belongs to a date
by its own `created:` field and to ignore anything outside the dates it was
handed, so a stale note no longer produces a duplicate entry. That is a *prompt*
holding the line, which is the weaker half of every pair in this project — and
the cost is still real, since every run pays to read the whole folder.

**Cas's call (2026-07-26): manual trigger, `/clear notes`.** Explicitly **not**
the automatic post-run move this entry originally suggested, and the reason is
ownership — **`00 inbox/notes` is read by more than one routine**, so "covered
by that run" isn't a claim any single run can make. The first routine to finish
would move notes the second hasn't read yet, and the second would be silently
short of input, which is exactly this project's worst failure shape. A human
command sidesteps the question entirely: by the time you type it, the loop and
the script have already dealt with the outbox, so nothing is still owed the
notes. `notes` needs no qualifier — the inbox one is the only one that means
anything.

Leaves open, and worth deciding when it's built: what `/clear` does with a note
no routine ever read, and whether "clear" moves or deletes (it should move —
`LOSER_DIR` set the precedent that a discarded thing keeps its body).

## W-05a · "/file" takes a number, not a title. 0.7 leftover, 24-07-2026
**Found:** Cas's 0.6.2 testing pass.
Description: `/outbox` now shows each proposal's frontmatter title beside its
filename, which fixes the "list of bare timestamps" half of the report. Typing
one is still `/file 3`.
Suggestion: accept `/file Aquarium Nitrogen Cycle` as well, matching the title
case-insensitively, refusing an ambiguous match rather than guessing. Pairs with
the `/move` entry below — both are "name the thing instead of counting rows" —
so decide the argument-parsing shape once, for both.
**Where it lands:** past 1.0. `ROADMAP_BEYOND.md`'s proposed 1.1 holds it.

## W-05b · "/move" — a file selector over the outbox. 0.8, 24-07-2026
**Found:** in the note-reader workflow brief.
Description: a command to move a file out of `99 outbox` (top level only, not the
subfolders) into the vault, driven like `/attach`: list filenames, arrow-select,
Enter to confirm, Esc to leave. The terminal states what will move and asks for a
destination (default `00 inbox`, arrow-select subfolders — today only
`00 inbox/notes` exists). A single Enter confirms — moving files, not replacing,
so no y/n. If a same-named file exists at the target, warn and offer: replace /
rename-the-new-one (timestamp appended?) / cancel; typing `replace` rather than
picking it is the protection against a careless clobber.
Where it fits: it's a filing command, closest to the existing `/outbox`/`/file`
pair rather than the taxonomy's attach/remove verbs — decide whether it's a
third filing command or an extension of that pair before naming it, so it lands
under the right prefix.
**Where it lands:** past 1.0. `ROADMAP_BEYOND.md`'s proposed 1.1 holds it. Note
its "Esc to leave" depends on the `[esc]` entry above, which is 2.0 — a typed
word until then.

## D-09 · The `reflection` routine cannot read what its prompt reads. 0.9.1, 28-07-2026

**Found:** 2026-07-28, reading the run logs to confirm the report's *"routines
— scheduled, on a real tick"* tick. Its 12:31 run logged `ok (review)`:

> All 12 atomic notes written. **Processed 3 source files** from
> `/06 metadata/reflection/` (the only readable root; the inbox at
> `/00 inbox/notes` was outside my allowed roots and ina…

**Vault, not code.** `reflection.md` borrows `note writer.md` as its prompt —
the prompt whose job is to read `00 inbox/notes` and write atomic notes — while
its own `read_roots` are `06 metadata/reflection` and `99 outbox/journal`. The
routine did useful work on the roots it had and correctly reported that it
could not reach the one its instructions name. Fix is a line in the routine
file; cfc owes nothing, exactly like `D-03` (closed the same day, in
[`legacy/BACKLOG.md`](legacy/BACKLOG.md)).

**Two things worth keeping from it anyway.** This is the first time the
`review` flag has fired in the wild, on precisely the case the scar was written
for — a run whose loop completed while the model's own words said it could not
do the task — so the second, orthogonal signal works as specified. And the
routine in question is the one Cas built during this playtest, immediately
after `D-0.9.1-03` made him retype the entire creation from scratch.

## D-0.9.2-01 · A transient provider status kills an unattended run outright. 0.9.2, 29-07-2026

**Found:** 2026-07-29, from *"every single routine is giving me 503 errors"*.
The provider (nano-gpt) was returning `HTTP 503 managed_mode_misconfigured —
"Managed edge assertion configuration is missing"` intermittently across every
model and every payload shape for roughly three hours. That part is theirs and
nothing is owed for it (`N-0.9.2-01`). What the outage exposed is ours.

**`_turn_with_retry` re-rolls an empty completion twice and a 503 zero times.**
Its own docstring calls an empty completion *"a provider hiccup, not a size
limit, and the same context usually answers on a re-roll"* — which is a
description of a 503 with the word for it left out. An `httpx.HTTPError` raised
inside `agent_turn` passes straight through the retry loop, out to
`run_routine`'s broad handler, and the run is logged `failed`. Every one of the
six failures today died at **call 0 of 30**, before a single tool call: the
cheapest possible point to have tried again.

**The cost is not the failed run, it is the day.** `MAX_RETRIES_PER_DAY = 3`
spends one budget slot per failed *run*, so three 503s fifteen minutes apart at
06:19, 06:30 and 06:45 exhausted `short-term-memory`'s retries for the whole of
29-07 — and the provider was healthy again by 08:47, when the same routine ran
by hand and succeeded first time. A retry ladder that had absorbed the 503 in
process would have cost one extra request and no budget at all. The cap itself
is right and stays (`N-0.9.2-02`); it is a bound on *runs*, and a transient
status is not a run's worth of failure.

**Why it is deferred rather than done.** The shape needs deciding before it
gets written, and there are three questions in it that this session should not
answer by itself:

- **Where it lives.** In `api.py`, where the status code is, it protects both
  paths and the chat turn inherits a silent retry a human didn't ask for. In
  `_turn_with_retry`, where the existing re-roll is, it is routine-only and
  matches the "batch job, nobody watching" reasoning already written there —
  but it retries a whole turn rather than a call.
- **Which statuses.** 503, 502 and 429 are transient by definition; 400 and 401
  are not, and retrying a 400 would be retrying `BUGS.md`'s open bug three times
  at full cost. The provider's own status code is the signal, so this does not
  add a row to `HANDOVER.md`'s producer/parser table — but only if it matches on
  the code and never on the wording.
- **What it costs when it is wrong.** The bound exists for the same reason
  `EMPTY_COMPLETION_RETRIES` is 2: "retry until it works" against a sick
  provider is a large bill discovered late.

## D-10 · The hub's Routines panel cannot say a routine is broken. 1.0, 29-07-2026

**Found:** as a one-line tracker row while v0.9.2 was being written — *"the hub
hides a routine file that won't parse"* — and written up here on 2026-07-29
because v1.0 listed it as a **drafting** step precisely so it would not get
built from that one line. Which was the right call: the row names the smaller
half.

**Driven, not read.** A temp routine folder with one healthy routine and one of
each breakage, rendered through `hub._routine_rows` and `hub._print_routines`:

| the file | `/routine` says | the hub's cell |
|---|---|---|
| healthy, `trigger: 0300`, ran 03:00 | `healthy` | **green** |
| prompt file deleted, otherwise fine | `! ghost: prompt file not found` | **green** |
| `trigger: tuesdays` | `! badtrig: trigger 'tuesdays' is not…` | dim |
| `trigger: command` | `onhand` | dim |
| no frontmatter at all | `! broken.md: has no frontmatter` | **absent** |

**So there are three tiers, and the tracker row names the third.** A file that
will not parse is dropped: `list_routines()` returns `(good, bad)` and
`hub._routine_rows` does `good, _bad = list_routines()`. A malformed *trigger*
parses fine and lands in the dim cell beside `command` and `disabled`, which is
the conflation `_freshness`' own docstring already flags. And in the middle sits
the one nobody had written down.

**The middle tier is the finding, and it is the inverse of the other two.** A
routine that parses but fails `validate()` — a prompt file that moved, a read
root that was renamed, a non-slug id — is not hidden and is not dim. It renders
**green, identical to a healthy routine**, because `_freshness` never consults
`validate()`. Green is the strongest thing this column says: *nothing is owed*.
It is being said over a routine that cannot run at all.

That is standing decision 16's own failure shape — green over a dead server, the
one output nobody double-checks because it is the reassurance that stops you
checking — reproduced one panel up the screen from the light that decision was
written for. The colour is not wrong about what it measures, and that is the
whole trap: **the column answers *is a run owed*, and the panel is read as *is
this still working*.** `_routine_rows`' own docstring says the useful question is
"is each of these still running". Those two questions agree on every routine
except a broken one.

**Two things make it survivable today, and neither is a defence.** `/routine`
does show all three tiers, marked `!` with the reason — the screen exists, it is
just not the screen you are looking at when you launch. And a broken routine
that has *failed* still shows red in the Status column; the green case is a
routine that succeeded before it broke, or that has never run. Which is the
common shape: you rename a prompt file in Obsidian and nothing tells you until
03:00, or later.

**A fourth way to be invisible, worth knowing before designing:** `HUB_ROUTINES`
is 5 and never-run routines sort last, so a brand-new broken routine is both the
most likely to be never-run and the first to fall off the panel. Confirmed with
nine routines — the never-run one was the row that vanished.

### The two questions this entry exists to hold open

**1. Is "cannot be owed a run" allowed to stay one colour with "cannot be
read"?** Dim currently means `command`, `disabled`, *and* a trigger
`parse_trigger` won't take. The first two are deliberate states of a working
routine; the third is a fault. The argument for leaving them together is
`hub.py`'s own — the dot is the signal, the sentence is the content — except
that this column **has no sentence**, which is exactly why v0.9.2 printed the
orange legend only when an orange row exists. The argument against a new colour
is `D-0.9.1-01`'s, settled at the connection light: re-assigning colours is
free, adding one widens a pair. Note this column is *not* a producer/parser pair
across a boundary — `_freshness` returns its own style strings — so the
constraint is weaker here than it was there, and the entry should say so rather
than inherit a rule it doesn't need.

**2. What should the hub show, given what checking costs?** This is the question
with a number attached, measured 2026-07-29 on the real vault (six routines, 21
roots, over `/mnt/c`):

| | |
|---|---|
| `list_routines()` — what the panel already pays | **22 ms** |
| ...plus `validate()` on all six | **~205 ms** |
| `prompt_path()` alone | ~58 ms |
| root `exists()` alone | ~32 ms |

The rest is `denial_reason()` per root. **The hub already pays ~0.16s for the
connection light**, so full validation roughly doubles the wait in front of the
picker — and `show_routines`' own comment blesses that cost with *"this screen
is on demand"*, which the hub is not. Three shapes, and the cheapest is not the
weakest:

- **Show the `bad` list the hub already computes and throws away.** Free — it is
  the second element of a tuple that is already unpacked and discarded. Closes
  the third tier alone, and closes it completely.
- **A line under the panel when anything is wrong**, the way the orange legend
  appears only when an orange row exists: `! 2 routines have problems —
  /routine`. Keeps the colour answering one question and puts the detail on the
  screen that already renders it well. Costs whatever the check costs.
- **Fold `validate()` into `_freshness`.** Most direct, most expensive, and it
  makes the colour answer two questions at once — which is what
  `B-0.9.1-04` was: a column with an opinion of its own about a second thing.
  Worth being suspicious of for that reason and not only for the milliseconds.

**Why here and not `BUGS.md`, and the honest caveat.** Nothing claims the column
means "this routine works" — it is headed `Last run`, and decision 16 documents
it as rendering `why_not_due()`, which it does faithfully. The specification is
too narrow rather than unmet, which is this file's definition. **The middle tier
is the one that could be argued across**, and if it is ever seen in the wild
costing a real run, that is the argument. It has not been.

**Not scheduled.** v1.0's obligation was this entry. The build wants deciding
with whoever next touches `_freshness`, the way `D-0.9.1-01` waited for
`preflight.STATES` and was better for it.
