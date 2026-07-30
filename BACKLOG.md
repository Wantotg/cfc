# Backlog

Things found in passing and deliberately not fixed, so they don't get lost.
Nothing here is urgent — this is a hobby project and it all still works.

Add to this rather than fixing on the spot when something turns up mid-task.
`HANDOVER.md` is why the code is shaped as it is; this is what's still owed.

Each entry carries its tracker id in the heading — the id the playtest report
gave it, unchanged thereafter.

## When an entry closes

**It moves to [`legacy/BACKLOG.md`](legacy/BACKLOG.md), whole, and leaves
nothing behind here.** This file holds open entries only. The reasoning is in
`HANDOVER.md`, *Which file owns what*.

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
