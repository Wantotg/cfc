# Backlog — archive

**Everything below the split line is `BACKLOG.md` as it stood on 2026-07-27,
immediately before the v0.9 archive split, kept whole.** The live file is
[`../BACKLOG.md`](../BACKLOG.md), which holds open entries only.

It is kept rather than deleted for one specific reason: `CHANGELOG.md` carries
every fix and its reasoning, but **not the original report**, and the symptom as
first written is frequently the valuable half — the `MAX_DISTANCE` entry below
is the case in point, where the report's wrong premise is the finding.

**Nothing below is edited, and nothing below is current.** Read it for the trail
behind a fix, not for what is still owed.

**This file is not closed.** It is where a closed entry goes from now on:
newest at the top, in the *Closed since the split* section directly below,
moved whole rather than summarised. "Archive" is the ongoing rule, not a
one-time snapshot — the original text below the split line is what is frozen,
not the file.

---

# Closed since the split

## ~~D-1.6-03 · `/update db`'s hidden-wiki notice doesn't say what still ran~~ — CLOSED (v1.6.1, 2026-08-03)

**Closed 2026-08-03**, v1.6.1 — the notice now names both halves: the hidden
wiki re-import was skipped and eligible chat messages will still be indexed.
`TRACKER.md`, `CHANGELOG.md`, `2c4df49`.

The entry as it stood:

---

## D-1.6-03 · `/update db`'s hidden-wiki notice doesn't say what still ran

**Found:** 2026-08-02, v1.6 playtest. With `WIKI_DIR` inside a hidden scope,
`/update db` printed the skip notice and then went on to index 39 chunks. Cas
read the two lines as contradicting each other and expected the command to
stop at the notice.

The behaviour is the specified one and the chunks were clean — checked
read-only against the live db, where the newest `source='wiki'` chunk is id
4547 and everything above it is `source='chat'`. `Concept.md` scopes it
exactly: *"`/update db` does not re-import a hidden `WIKI_DIR`"*, and nothing
more. The chat half of the index never reads the vault, so a vault scope has
no opinion about it, and stopping the whole command would make a scope quietly
turn off an unrelated feature.

**What is actually wrong is the sentence.** `[… — wiki re-import skipped]`
names the half that did not run and leaves the reader to infer the half that
did, one line before a spinner and a chunk count arrive to contradict the
inference. The two are only reconcilable by someone who knows the corpus split
already.

**Owed:** say both halves in the one notice — the wiki re-import is skipped,
the chat index still updates. One string, at the same call site; no behaviour
change. `/recall` and `/remember` need nothing: they refuse outright, so their
notice is the whole answer.

## ~~D-16 · `runner._mark_transcript` swallows a failed marker write without rolling the connection back~~ — CLOSED (v1.6, 2026-08-02)

**Closed 2026-08-02**, v1.6 — `_mark_transcript` now rolls the connection back
before swallowing a failed best-effort marker write. The fix was verified by
disabling the rollback and watching a partial marker INSERT ride along on the
next save and survive. `TRACKER.md`, `CHANGELOG.md`.

The entry as it stood:

---

## D-16 · `runner._mark_transcript` swallows a failed marker write without rolling the connection back

**Found:** 2026-08-02, while reviewing v1.5.2's routine failure paths.
`runner._mark_transcript` correctly treats a failed transcript marker as
best-effort because the authoritative run log already exists, but it swallows
the failure without rolling back. A failed `save_message` therefore leaves
`conn.in_transaction` true; the next save commits that stale transaction along
with its own work. It is a dangling transaction rather than a retained writer,
but the two best-effort paths in the same function should not clean up
differently.

**Owed:** roll back the connection before swallowing a failed marker write, and
test that the connection is clean afterward.

## ~~D-1.5.1-01c · The routines screen cannot say which routine is due~~ — CLOSED (v1.5.2, 2026-08-02)

**Closed 2026-08-02**, v1.5.2 — the routines screen now renders the scheduler's
own assessment in a `Schedule` column and narrow-layout line. The playtest
drove real triggers and cross-read the hub and screen; both agreed.
`TRACKER.md`, `CHANGELOG.md`, `49e8df2`.

The entry as it stood:

---

## D-1.5.1-01c · The routines screen cannot say which routine is due

**Found:** 2026-08-02, in the v1.5.1 playtest. `/config` correctly reports a
due routine and points to the routines screen, but that screen shows last-run
status and review state rather than due-ness. The count is right; the screen it
opens cannot answer the question it raised unless the user already knows which
routine to inspect with `show`.

**Owed:** give the on-demand routines screen a due/schedule column based on the
same assessment the scheduler uses. This is deliberately separate from the
hub's compact schedule light: the screen can afford the fuller check and can
show the routine-specific reason.

## ~~D-10 · The hub's Routines panel cannot say a routine is broken. 1.0, 29-07-2026~~ — CLOSED (v1.5.1, 2026-08-02)

**Closed 2026-08-02**, against the shipped code rather than by new work, as
`Concept.md` scoped it. The hub's validation nudge covers the middle tier and
the routine panel now prints the schedule state in text, so the entry's
conflation is resolved without a new colour. `D-1.5.1-01c` was the separate
due-ness gap in the on-demand routines screen; it shipped in v1.5.2. See the
newer closed entry above. `TRACKER.md`, `CHANGELOG.md`.

The entry as it stood:

---

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

---

## ~~D-1.4-02 · The routines screen labels a routine by its id; everything else uses its name~~ — CLOSED (v1.4.1, 2026-08-01)

**Closed 2026-08-01**, v1.4.1 — the routines screen and its validation lines
now show `Routine.name`, using the same row data at both widths.
`tests/test_screens.py`, `CHANGELOG.md`, a59d97e.

The entry as it stood:

---

## D-1.4-02 · The routines screen labels a routine by its id; everything else uses its name

**Found:** 2026-08-01, v1.4 playtest. The routines screen's `Routine` column
shows `short-term-memory` where the file, the hub's Routines panel and `show`'s
own heading all say `short term memory`.

**Not a mismatch and not a leftover, which is the half worth knowing.** The
routine file really does say `id: short term memory`; `Routine.__init__`
slugifies the id at construction (`routines.py:266`) because these files are
hand-authored in Obsidian, where spaces are what you naturally type, and a
strict slug check would have failed every hand-made routine. The slug is then
the handle everywhere it has to be one — the log filename, the session lookup,
`/routine <id>`. The file is never rewritten; only `to_markdown()` emits the
slug, so a routine cfc itself saves normalises and one you wrote by hand does
not. `screens._routine_row` is simply the only surface that prints the handle
instead of the display name.

**Owed:** show the name in that column, since `load_routine` resolves by id,
name *or* the slug of what was typed — so the name is a usable handle too, and
nothing on the screen depends on the id being visible. Two things move with it,
which is why this is an entry rather than a one-word edit: `_render_routines`
prints its problem lines as `! {r.id}: {why}` *below* the table, so a name in
the column and an id underneath would label one routine two ways on one screen;
and the narrow renderer uses the same row dict. Consider printing the id beside
the name where they differ rather than replacing it — `show` already does
exactly that, name in bold with `id` as its first field.

## ~~D-13 · A failed title call is silent and the next turn inherits the titling~~ — CLOSED (v1.4.1, 2026-08-01)

**Closed 2026-08-01**, v1.4.1 — title failures now raise, log one `title`
record and print one visible warning; a later turn cannot inherit the work.
`tests/test_titles.py`, `tests/test_turn_paths.py`, `CHANGELOG.md`, 0cc952e.

The entry as it stood:

---

## D-13 · A failed title call is silent and the next turn inherits the titling

**Found:** 2026-07-31, in the v1.3.1 diagnosis. `generate_title()` swallows
every exception and falls back to `(untitled)`. A failed title request is not
shown in the console or written to `errors.log`, and the guard retries on the
next message, so the next turn can receive the stale title job. The user-visible
freeze and accidental input are `B-1.3.1-02`; this is the separate observability
debt in the title path.

**Owed:** make a failed title call visible and keep it from silently handing the
work to whatever message comes next. It is not a v1.3.1 defect claim and is not
a tag blocker.

## ~~D-11 · `/tools` puts two more config values in the golden baseline. 1.0, 29-07-2026~~ — CLOSED (v1.3, 2026-07-31)

**Closed 2026-07-31**, v1.3 — the golden fixture now uses a temporary write root
outside the checkout, with the path scrubbed in the baseline.
`tests/test_golden_fixture.py`, `CHANGELOG.md`.

The entry as it stood:

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

## ~~D-1.1-05 · `TRANSIENT_STATUS_CODES` omits 504~~ — CLOSED (2026-07-30)

**Closed 2026-07-30**, v1.1.1 — 504 added to the frozenset alongside 429/502/503;
408 considered and declined in the same pass, since resending a request the
client itself timed out proves nothing. `CHANGELOG.md`. Original entry:

**Found:** 2026-07-30, v1.1 playtest.

Description: `api.py:179` treats 429/502/503 as the temporary admission and
availability failures an unattended routine can reasonably outwait —
`D-0.9.2-01`'s own comment says so word for word — but 504 (gateway timeout,
same class as 502: the upstream didn't answer in time) was never added.
Omitted, not excluded: `D-0.9.2-01` shipped "429/502/503 by status code alone"
and never claimed 504.

**Fix:** add 504 to the frozenset. One entry, and it gets a routine two more
re-rolls on the shared `EMPTY_COMPLETION_RETRIES` budget. Worth deciding 408
(client timeout) at the same time, and probably declining it — 408 is the
*client* being slow, and resending an identical request that was too slow once
buys nothing.

**Where it lands:** v1.1.1.

## ~~D-1.1-08 · `/clear notes` doesn't look like cfc~~ — CLOSED (2026-07-30)

**Closed 2026-07-30**, v1.1.1 — the preview now names the guarded notes-inbox
path and the cleared-notes archive root, and the confirmation prompt is no
longer indented into the filename list. `CHANGELOG.md`. Original entry:

**Found:** 2026-07-30, v1.1 playtest.

Description: the confirm prompt renders indented into the note list, at the
same indent as the filenames — six notes, then a seventh line that isn't a
note. `/move` gets away with the same layout because its list is numbered, so
the prompt can't be mistaken for a row; this list isn't. And it names no
paths — every other filing screen in cfc says which folder it means
(`Outbox (/mnt/c/...)`), and `/move` shows `source → target` before Enter;
`/clear notes` is about to move six files and says where neither, even though
`notes.py` already knows both.

Not a work-order fault. `Concept.md` specified "shows the count and every
filename that will move" and the build met it exactly — the concept
under-specified it, and the guarded-move pattern used everywhere else in this
codebase is the better answer here too.

**Where it lands:** v1.1.1.

## ~~D-1.1-09 · retired `:` commands survive in ~25 source comments~~ — CLOSED (2026-07-30)

**Closed 2026-07-30**, v1.1.1 — swept from source comments and four test
docstrings; `agent.py:509`'s restated invariant cut to three lines and a
pointer to `HANDOVER.md` standing decision 2. The two runtime strings the
sweep didn't reach — the private-chat banner and `_session_arg`'s fallback —
are `B-03`, `CHANGELOG.md`. Original entry:

**Found:** 2026-07-30, v1.1 playtest — one instance (`main.py`) of a class
`B-0.9.1-02`'s fix didn't reach. That sweep covered `config.example.py`
because it's the one shipped file that instructs a human; source comments were
never swept. About 25 survive across `main.py`, `commands.py`, `hub.py`,
`mover.py`, `runner.py`, `wikigit.py`, `preflight.py`, `complete.py`, `ui.py`
and four test docstrings. Most are harmless prose colour; three are docstrings
naming the wrong key for the behaviour they document (`main.py:108,110,151`,
all `:q`).

Nobody types from a comment, so the original bug's argument doesn't carry —
but a model reading `commands.py` to write the next feature does, and
reproducing `:status` in new output is exactly how a retired prefix comes
back.

Carries one more fix found in the same pass: `agent.py:509`'s comment restates
standing decision 2 and its scar in full, in a file that owns neither. Three
lines and a pointer is the version that survives — it earns *some* length,
since it's the invariant the `try/finally` directly below exists for, and a
shorter comment is what let that `finally` look optional once.

**Where it lands:** v1.1.1.

## ~~D-12 · three files still described the pre-v1.0 auto-revert~~ — CLOSED (2026-07-30)

**Closed 2026-07-30**, v1.1.1, alongside `W-1.1-03` — the remaining stale
claim, `tests/test_model_revert.py`'s docstring, corrected in the same edit.
`CHANGELOG.md`. Original entry:

**Found:** 2026-07-30, diagnosing `W-1.1-03`. `HANDOVER.md`'s *Open threads*
carried a bullet — auto-revert arms only for ids it doesn't recognise, so a
broken id still *in* `MODELS` goes unhandled — that was already fixed in
`44d91a7`; `main.py:527` arms on every switch, and the comment above it
documents the change and its cost. Removed from `HANDOVER.md` on 2026-07-30 as
a factual correction, under its own first rule (code right, file stale). Its
pointer to this file was also dead — no such entry existed here, so a reader
following it found nothing and couldn't tell whether the entry was closed or
never written; moot now that the bullet is gone.

Still open: `tests/test_model_revert.py`'s docstring describes the old scope —
*"a known-good unlisted model never reverts later on a transient hiccup"* — the
exact property `W-1.1-03` is asking to have back. The assertions pass; only the
docstring lies.

**Where it lands:** v1.1.1, alongside `W-1.1-03` — same sentence either way.

## ~~D-09 · The `reflection` routine cannot read what its prompt reads~~ — CLOSED (2026-07-30)

**Closed 2026-07-30**, vault-side, Cas's fix — the routine's read/write roots
now cover what its prompt reads. Original entry:

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
file; cfc owed nothing, exactly like `D-03` (closed the same day, above).

**Two things worth keeping from it anyway.** This was the first time the
`review` flag fired in the wild, on precisely the case the scar was written
for — a run whose loop completed while the model's own words said it could not
do the task — so the second, orthogonal signal worked as specified. And the
routine in question is the one Cas built during that playtest, immediately
after `D-0.9.1-03` made him retype the entire creation from scratch.

## ~~D-02 · Processed notes stay in "00 inbox/notes" forever~~ — CLOSED (2026-07-30)

**Closed 2026-07-30**, v1.1, in `9ac48d6` — `/clear notes`. Original entry:

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

Left open at the time, and settled by the build: what `/clear` does with a note
no routine ever read (it moves, not deletes — `LOSER_DIR` set the precedent
that a discarded thing keeps its body), into a dated batch folder under
`00 inbox/notes`. The UX gap the build left — no paths shown, prompt reads as a
list row — is `D-1.1-08`.

## ~~W-05a · "/file" takes a number, not a title~~ — CLOSED (2026-07-30)

**Closed 2026-07-30**, v1.1, in `9ac48d6` and `53a7f1e` — `/file <title>`.
Original entry:

**Found:** Cas's 0.6.2 testing pass.
Description: `/outbox` now shows each proposal's frontmatter title beside its
filename, which fixes the "list of bare timestamps" half of the report. Typing
one is still `/file 3`.
Suggestion: accept `/file Aquarium Nitrogen Cycle` as well, matching the title
case-insensitively, refusing an ambiguous match rather than guessing. Pairs with
the `/move` entry below — both are "name the thing instead of counting rows" —
so decide the argument-parsing shape once, for both.

Shipped as designed: the whole remainder of the line, matched case-insensitively
after folding case. `W-1.1-07` found and fixed the one thing the entry couldn't
have anticipated — `/list outbox`'s own line let the corpus tag trail the title
with nothing marking the boundary, so a title read straight off the screen
carried it along and never matched. Fixed by reordering the line, not the
matcher.

## ~~W-05b · "/move" — a file selector over the outbox~~ — CLOSED (2026-07-30)

**Closed 2026-07-30**, v1.1, in `9ac48d6`. Original entry:

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

Shipped as scoped, with a typed word (`back`) standing in for the deferred Esc
key (`D-04`, still 2.0), and a verified-replace guard on collisions rather than
a bare `replace`/`rename`/`cancel` choice.

## ~~D-0.9.2-01 · A transient provider status kills an unattended run outright~~ — CLOSED (2026-07-29)

**Closed 2026-07-29**, post-v1.0, by Codex (`8b83d97`). The entry deferred this
on three questions and each was answered the way it framed them:

- **Where it lives:** `_turn_with_retry`, so it is routine-only. An interactive
  chat gets no silent retry a human didn't ask for.
- **Which statuses:** 429, 502 and 503 only, matched on the code. `api.py`
  attaches `status_code` to the `HTTPError` at the HTTP boundary and
  `agent_turn` preserves it while adding request context, so nothing anywhere
  reads the provider's wording — which is what keeps this off `HANDOVER.md`'s
  producer/parser table, as the entry required. A transport failure carries no
  status and is deliberately not guessed at.
- **What it costs when wrong:** nothing new. The retry shares
  `EMPTY_COMPLETION_RETRIES`' budget rather than opening a second one, so a
  provider alternating 503s and empty completions gets the same two extra calls
  an all-empty provider already got.

`tests/test_routines.py` pins that a 503 does not spend the day's failure
budget, and that 400, 401 and 500 stay non-retryable *including* when their
text contains the string `503`.

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

## ~~D-01 · The golden baseline pins the live vault outbox~~ — CLOSED (v1.0, 2026-07-29)

**Closed 2026-07-29**, v1.0 step 7. Cas's call between the entry's two options:
**redirect, don't drop.** `capture()` now points `mover.outbox_roots` at a
fixture, so `/outbox` stays in the characterization sweep and a refactor that
changes its rendering is still caught — which the other option would have given
up. The mechanism is the one `capture()` already uses for `DB_PATH`,
`VAULT_PATH`, `errorlog.LOG_PATH` and the model lists, so this is one more piece
of environment the harness knows about rather than a second way of doing the
same thing. The entry's own sentence is what decided it: *"the harness already
knows it must not pin the environment; the outbox is environment it doesn't yet
know about."* That argues for teaching it, not for removing a command.

**Patched at the seam.** `mover._cfg` re-reads config on every call, so setting
`config.WRITE_ROOTS` would have worked today and stopped working the moment
anything cached it — the reason `test_routines` patches `routines.routine_dir`.
Four functions are the whole surface `list_proposals` consults, and
`wiki_dir`/`journal_dir` are pinned to `None` deliberately: a corpus subfolder
reaches `wikigit` and the vault's real git state, which is environment of
exactly the kind this was fixing.

**The fixture carries one filable proposal and one refusal**, because both have
their own rendering and the refusal's has a rule attached — the destination that
was *asked for* is printed beside the reason, so the model's suggestion stays
auditable. A fixture of only filable proposals would have left that untested and
looked complete.

**A bonus and a finding.** The baseline stopped carrying a real vault path,
which is one of the six tracked files `N-0.9.1-01` ruled on. And re-recording
showed the same bug one line over — `/tools` prints `TOOLS_ROOTS` and
`WRITE_ROOTS` verbatim — now `D-11`, written up rather than forced through
because the obvious fix raises `ScopeError` against standing decision 4. The
entry as it stood:

---

## D-01 · The golden baseline pins the live vault outbox. 0.9.1, 27-07-2026

**Found:** 2026-07-27, re-recording the baseline for a one-line help-text
change. The diff carried a second, unrelated hunk: `/outbox`'s two journal
proposals had been filed since the last record, so the baseline said
`2 of 2 can be filed` and the run said `(nothing pending)`.

**This is the `config.py` scar in a new place.** That one is in `HANDOVER.md`:
*"Anything a baseline pins that lives in config rather than in source is this
bug"* — adding a model to your own config failed `check` on lines that say
nothing about the code. Same shape here, with the vault standing in for config.
`SCRUB` normalises timestamps, paths and the key digest, so the harness already
knows it must not pin the environment; the outbox is environment it doesn't yet
know about.

**Why it is not urgent, and what it costs anyway.** It fails *loudly* — a diff
you have to read — which is the good direction, and the harness's whole job is
to make you read diffs. The cost is that it trains the habit this file's
neighbour scar was written about: a `record` whose diff has a hunk you learn to
skip is a `record` that will one day carry a real regression past you. It cost
exactly that here, twice in one session, and both times the reasoning was "that
one's not mine".

**Two fixes and neither is obviously right**, which is why it's deferred rather
than done: scrub the outbox listing to a fixture the way `capture()` forces
config values, or drop `/outbox` from the golden script and cover it in a unit
test with a temp directory. The first keeps the command in the characterization
sweep and pins less of it; the second pins more and takes it out of the sweep.
Decide with whoever is next in `golden.py`, not on its own.

---

## ~~D-0.9.1-03 · `/routine new` checks the trigger only at the end, and drops the whole creation~~ — CLOSED (v1.0, 2026-07-29)

**Closed 2026-07-29**, v1.0 step 4. All three holes plus the fourth the entry
listed separately, and the entry's own reading was right: **the fix is as much
*announce the exit* as it is *re-prompt*.**

**Early and late, never early instead of late.** `Routine.validate()` and
`save_routine`'s refusal are untouched — standing decision 8 rests on them and
a hand-edited file never passes through the creation flow at all. What changed
is that the two raw fields are now checked against `routines.trigger_problem`
and `on_failure_problem`, **the same functions `validate()` calls**, lifted out
of it rather than copied beside it. A field accepted as you type it therefore
cannot be rejected at save; two checks written separately would have disagreed
the first time `weekly` grew a variant, and the disagreement would have shown
up as this exact bug wearing a different hat.

**Four holes closed:**

- `trigger` and `on_failure` re-prompt per field, via `_ask_until`, which is
  `_ask_paths`' shape — the loop the entry pointed out was already in the file
  and had simply never been given to these two.
- A **taken id** is caught at the name prompt and re-asks for one, rather than
  raising `<id>.md already exists` after every question has been answered.
  `save_routine` keeps its own check: the early one can lose a race with a
  second cfc, and the late one is the guarantee.
- **Cancelling the model picker no longer saves the routine you were
  abandoning.** This was the one that wrote a file. `select_model` returns
  `None` only when the human backed out, and that was read as *no pin* while
  every other `None` in the flow returns. Confirmed by reverting the fix and
  watching `cancelled-model.md` land on disk.
- Every exit now says it is one. The flow returned to the REPL silently, so the
  next line typed became a chat message — decision 13's failure shape reached
  through an abandoned prompt rather than a missing verb.

**The placeholder was read as a placeholder, and that was fair.** The prompt
said `trigger (command, or HHMM)` against a default of the literal word
`command`, so `HHMM` typed back is a consistent reading of the screen. It is
now `(command, 0300, or weekly 0330)` — a concrete time cannot be mistaken for
a form to fill in.

Driven, not reasoned about: `tests/test_routines.py` scripts `input()` and runs
the reported flow, the duplicate name, the cancelled picker and an abandoned
exit. Each of the four assertions was verified by reverting its fix and
watching that one fail. The entry as it stood:

---

## D-0.9.1-03 · `/routine new` checks the trigger only at the end, and drops the whole creation. 0.9.1, 28-07-2026

**Found:** 2026-07-28, Cas's post-tag v0.9.1 playtest. The report, verbatim:

```
trigger (command, or HHMM) [command]: hhmm
on failure (retry/skip) [retry]: retry
model (blank = routine default):
Not saved: trigger 'hhmm' is not 'command', HHMM or 'weekly HHMM'
You: HHMM

expected: to stay in routine creation and correct my mistake, instead of
          sending a message
guess:    user error, but we could make it more friendly and not leave
          routine creation.
```

**Not user error.** `commands.create_routine` is half reject-as-you-type and
half all-or-nothing, and the trigger is in the second half. Read roots go
through `_ask_paths`, which validates each line and re-prompts — its docstring
says *"exactly the shape a reject-and-re-prompt loop wants"* — and the task
prompt is checked against the directory listing inline. `trigger` and
`on_failure` are taken raw and reach validation only at `save_routine` →
`Routine.validate()`, six answers later, where a `RoutineError` prints
`Not saved:` and returns. Name, prompt, roots and model go with it.

**The half that actually bit is the exit, not the validation.** The flow
returns to the session REPL without saying it has, so the next line typed is a
chat message — standing decision 13's failure shape (unrecognised input is not
an error, it is an API call and a confidently wrong answer) reached through an
abandoned prompt flow rather than through a missing verb. `create_routine`
announces only one way out: *"Ctrl-C at any point abandons it."*

**Three holes, one shape**, and a fix that closes one should close all three:

- `on_failure` — anything but `retry`/`skip` discards the same six answers.
- An id that already exists — `save_routine` raises `<id>.md already exists` at
  the same late point, after every question has been answered.
- Cancelling the **model** prompt is read as "use the routine default": every
  other `None` in `create_routine` returns, but `select_model` returns `None`
  both for *cancelled* and is then treated as *no pin*, so a Ctrl-C there
  silently saves a routine rather than abandoning one.

**Where a fix goes.** The per-field loop already exists in `_ask_paths`;
`Routine.validate()` is non-raising and exhaustive by design (*"the creation
flow wants to show all the problems at once"*), so the pieces are in place and
the change is a re-prompt around the two raw fields rather than new
machinery. Worth deciding at the same time: whether the prompt's `HHMM` reads
as a placeholder — it was typed back literally here, and `0300` in the example
would cost nothing. **Do not** move validation *out* of `save_routine`; that is
what makes an invalid routine unsaveable, which is the invariant standing
decision 8 rests on. Add the early check, keep the late one.

**Why here and not `BUGS.md`:** nothing claims the flow re-prompts, and the
routine that was eventually saved is correct. It is a form that discards itself,
which is debt.

---

## ~~D-0.9.1-01 · Two connection states share a colour, and the pairing looks swapped~~ — CLOSED (v1.0, 2026-07-29)

**Closed 2026-07-29**, v1.0 step 2, in one pass with `B-0.9.1-03` — the entry
asked to be decided with whoever next touched `preflight.STATES`, and that was
the same session.

**The entry's own framing is what decided it.** It says the pairing is the
question rather than the count, and that `hosted` being orange while cfc cannot
act on it, and `not running` being red while it is one `lms server start` away,
look swapped against what the colours mean everywhere else in cfc. They were.
Cas's call: **the dot carries recoverability, not severity** — orange where
`/connect embedding` will try, red where it is not cfc's to fix.

**Severity was never the axis it looked like.** Every non-green state means the
same thing — memory is off — so sorting five states by how bad they are sorts
them by nothing, which is why the old pairing could be wrong for two releases
without anyone being able to say what it should have been instead. Recoverability
discriminates, and it discriminates the way `preflight.ensure` already behaves:
`hosted` returns early, the other three fall through to the fixer. So the colour
and the code cannot drift apart, which is standing decision 16's own argument
applied to the colour rather than to the state.

Three states share orange now, one more than the two that shared it before. That
is the entry's *"the colour carries severity and the sentence carries identity"*
kept intact, with the collision demoted from an accident to a class: orange is
not five states running out of colours, it is the set of things one command
tries.

**The one thing a fix must not do, which it did not do:** no colour was
invented. `ui.py` imports no cfc module, the mapping is a producer/parser pair
across a boundary that cannot close, and re-assigning leaves it the size it was.
`tests/test_connection.py` pins the rule rather than the colours — every state
that offers the command shares one style, the state that does not shares none of
it, and green is nobody else's — so re-styling stays free and un-pairing the
colour from the behaviour fails. Verified by breaking it three ways, including
painting the whole light one colour. The entry as it stood:

---

## D-0.9.1-01 · Two connection states share a colour, and the pairing looks swapped. 0.9.1, 28-07-2026

**Found:** 2026-07-27, Cas's v0.9.1 playtest, reported as *"either this is where
I find out that I'm actually colourblind, or two of these lights are the same"*
— against the `h` help screen's legend, which prints all five states at once.

**He is right about the observation and it is not a defect.** `ui.CONNECTION_STYLE`
maps five states onto three colours, so two pairs collide: `no server` and
`hosted` are both `orange3`; `not running` and `down` are both `red`. Five
distinct states over a traffic light was always going to collapse somewhere.

**Why nothing is broken.** The dot is never printed alone. `hub.print_connection`
emits dot *plus sentence*, and so do `/connect embedding` and
`preflight.terminal_report()` — all three render one `connection_state()` and
none of them abbreviates it. So the colour carries **severity** and the sentence
carries **identity**, and the state is always legible. This is the light doing
what standing decision 16 says it must; the legend is simply the one screen
where all five appear together, which is what made the collision visible.

**What is actually worth deciding, and it is the pairing rather than the count.**
`hosted` is orange — the actionable colour — while its own text says it is the
one state cfc *cannot* act on, and it is the only entry with no `/connect`
offered. `not running` is red — the terminal colour — while it is the most
trivially recoverable state on the list, one `lms server start` away, and
`preflight.py`'s orange path is exactly the one that fixes it. Those two look
swapped against what the colours mean everywhere else in cfc.

**Not urgent, and the reason to write it down rather than just doing it:** the
counter-argument is in `hub.py`'s own comment — *"the dot is the signal, the
sentence is the content"* — and a fix has to either agree with that and accept
that the signal is severity-only, or disagree and explain what a fourth colour
would mean. Cheap to change, so the cost of getting it wrong is a second
opinion later; decide it with whoever next touches `preflight.STATES`, not on
its own.

**One thing a fix must not do:** invent a colour per state. `ui.py` imports no
cfc module (decision 6), the mapping is already a producer/parser pair across a
boundary that cannot be closed, and `tests/test_connection.py` pins it by
round-trip. Adding colours widens that pair; re-assigning existing ones does not.

---

## ~~D-0.9.1-02 · The config files carry the whole origin story~~ — CLOSED (v0.9.2, 2026-07-28)

**Closed 2026-07-28**, in one pass with `B-0.9.1-02` exactly as the entry asks.
The rule it proposed — *if a comment's first clause is a date or a version,
that is the tell* — held up as a filter and found three: the `TOOLS_MAX_*`
block's `Until v0.5 …` paragraph in both files (already better written in
`HANDOVER.md` under *Constants with provenance*), `config.py`'s `(Until v0.6
these destinations were refused outright …)`, and its `(set 2026-07-20)` on
mirrored networking.

**What stayed, and it is the more useful half of the rule.** `WRITE_ROOTS`'
*"deliberately NOT derived from ATTACH_ROOTS/TOOLS_ROOTS"*, the
`TOOLS_AUTO_APPROVE` note explaining why a knob somebody will look for is not
there, and `MOUSE_INPUT`'s trade — all *what a wrong value costs*, none of them
history. The shipped file went 239 → 244 lines, which is the outcome rather
than a miss: the trim removed three paragraphs and the two factual additions
the version asked for (mirrored networking before the NAT gateway IP, and the
`text-embedding-baai-bge-m3-568m` id) put four back. Shorter was never the
claim; *a form somebody fills in* was. The entry as it stood:

---

## D-0.9.1-02 · The config files carry the whole origin story. 0.9.1, 28-07-2026

**Found:** 2026-07-27, Cas's v0.9.1 playtest: *"does it need the whole origin
story? we have it in changelog, roadmap and probably handover as well."*

Description: `config.py` and `config.example.py` are 230 and 239 lines, and a
large fraction of both is reasoning rather than settings — why `WRITE_ROOTS` is
not derived from `TOOLS_ROOTS`, why the mover has its own `MOVE_ROOTS`, why
`TOOLS_MODELS` was verified rather than assumed. All of it is true and most of
it is duplicated in `HANDOVER.md`'s standing decisions.

**Agreed, and the distinction that makes it decidable:** `config.example.py` is
a **form somebody fills in**, and a form's comment should say what the field
does and what a wrong value costs. The *history* of how the field came to exist
belongs in `HANDOVER.md`, which is written for a reader who has time. A comment
that must be re-read on every edit to find the one live sentence is the same
unreadable-list problem the `legacy/` archive split was made to fix.

**Where the line goes**, and it is not "delete the comments": keep the sentence
that stops a wrong edit — *"deliberately NOT derived from TOOLS_ROOTS — an alias
is how a read root becomes a write root by accident later"* is load-bearing and
stays. Cut the paragraph that recounts when it was discovered. If a comment's
first clause is a date or a version, that is the tell.

**Do this together with `B-0.9.1-02`**, which is a sweep of the same two files
for retired `:` commands. Two passes over one file is one pass more than the
change deserves, and the second pass would be re-reading prose the first pass
already deleted.

## ~~D-08 · The test suite writes to the live `~/.cfc/errors.log`~~ — CLOSED (v0.9.2, 2026-07-28)

**Closed 2026-07-28.** Fixed in three files rather than the one the entry
predicted — `test_model_revert.py` (the leak), `test_routines.py` and
`golden.py` — chosen by which surface a harness drives, since `log_error` has
exactly two call sites (`run_session`, `run_routine`). `test_agent.py` was
checked as the entry asks and needed nothing: it drives `agent.agent_turn`, and
`agent.py` does not import `errorlog`. All three guards verified by breaking
them.

**The entry's one wrong fact, kept because the archive exists for exactly
this.** It says four fabricated lines dated `21:07:10`. There were **32** error
entries in eight batches, `20:35:16` through `21:07:10` — the entry was written
from the last batch and generalised from it, which is a fair reading of a log
you are seeing for the first time and still an undercount by a factor of eight.
The pattern to take from it is that a count read off the tail of an append-only
file is a sample, not a total. All 32 were deleted by hand; the 13 `launch`
lines are real and stayed. The entry as it stood:

---

## D-08 · The test suite writes to the live `~/.cfc/errors.log`. 0.9.1, 28-07-2026

**Found:** 2026-07-28, reading the error log to check `B-01`'s absence-watch —
not from use. Four entries were already in it that no provider ever sent:

```
2026-07-27 21:07:10  error  session 1 · model shanhaig · nothing interrupted this session · chat
    no such model: shanhaig
2026-07-27 21:07:10  error  session 2 · model good-model · … upstream 503
2026-07-27 21:07:10  error  session 3 · model broken-but-listed · … no such model
2026-07-27 21:07:10  error  session 4 · model custom-x · … upstream 500
```

**Cause:** `tests/test_model_revert.py` drives the real `run_session` with a
stubbed stream that raises `httpx.HTTPError`, which reaches `main.py`'s handler
and `errorlog.log_error`. `errorlog.LOG_PATH` is a module constant
(`~/.cfc/errors.log`) and that test never redirects it.

**Why it is worse than clutter.** That file is the whole of `B-01`'s evidence,
and one of that entry's three closing routes is **absence across the 0.9 → 1.0
window**. `errorlog.py`'s header is explicit that *nothing parses this file* —
it is read by a human, deliberately, so as not to create a seventh
producer/parser pair. A human reading four fabricated `session 1 · model
shanhaig` lines cold has no way to tell them from the thing being watched for,
and they are dated inside the watch window. It is the same class as the scar
where a test guard that asserted *after* an `unlink()` deleted the real
database, and as `D-01`, where the golden baseline pins the live vault outbox:
the suite reaching live state.

**The fix is one line and the pattern is already in the next file over.**
`tests/test_private.py` redirects `errorlog.LOG_PATH` to a temp path and then
asserts on it — `assert "tmp" in str(errorlog.LOG_PATH), "refusing to touch the
real log"`. `test_model_revert.py` wants the same, and while in there it is
worth checking `test_agent.py`, which also drives error paths. The four
existing lines can be deleted by hand; say so in the commit, because *editing
the evidence file* is exactly the kind of thing the next reader deserves to
find written down rather than infer.

---

## ~~D-03 · Obsidian's template syntax and cfc's placeholders are both "{{ }}"~~ — CLOSED (vault edit, 2026-07-28)

**Closed 2026-07-28**, reported done in Cas's post-tag v0.9.1 playtest: *"done,
removed all tags from both vaults."* Closed by the vault, not by a commit —
this entry always said cfc's side of it was nothing, and it stayed open only
because the trap was live until the edit happened. `PLACEHOLDERS` is unchanged
and still exact-matching, which is the outcome the entry asked for. The entry
as it stood:

---

## D-03 · Obsidian's template syntax and cfc's placeholders are both "{{ }}". 0.8-adjacent, 24-07-2026
**Found:** 2026-07-24, adding the cadence placeholders.
Description: `runner.PLACEHOLDERS` substitutes `{{date}}`, `{{dates}}`,
`{{week}}` in a routine prompt. Obsidian's own templates use the same braces —
this vault's `note template.md` has `{{date:YYYY-MM-DD}}` in it.
Not live: matching is exact, so `{{date:…}}` is untouched, and the prompts point
at the template by path rather than quoting it. But a bare `{{date}}` pasted
into a prompt from an Obsidian template *would* be substituted, and the model
would then write today's date into a new note where the placeholder belongs.

**Cas's call (2026-07-26): change the vault, not the code.** The Obsidian
properties are there to be inspected, not templated, so converting them to plain
text is a small one-time edit of a handful of markdown files and it removes the
collision at the source. Cheaper than an escape syntax nobody would remember,
and it belongs to the vault repo rather than this one — cfc ships the mechanism,
the vault ships the words. **cfc's side of this is nothing**, which is the
point: leave `PLACEHOLDERS` exact-matching as it is. The entry stays open until
the vault edit has actually happened, because until then the trap is live —
but there is no code owed, and 0.9 owes it nothing.

---

## ~~Nothing validates that a model in `MODELS` can be chatted with~~ — FIXED (v0.9, 2026-07-27)

**Closed 2026-07-27, in the v0.9.1 bookkeeping.** Both of Cas's calls shipped in
`b423d30`: the auto-revert now arms on **every** switch — the `not in
known_models()` condition is gone, which was the backwards trust this entry was
re-opened to name — and the `MODEL_LIMITS`/`TOOLS_MODELS` startup check landed
at `commands.py:324`, the silent half, where a typo means tools never turn on
for a model you believe is covered.

**What survives was deliberately let go rather than carried forward.**
`ROUTINE_MODELS[0]` still has nothing to revert *to*, because a scheduled run
has no previous model. It is **audible** — the run logs `failed` and the hub's
freshness column shows it — and this file is for what is *owed*, not for what
works and could be worded better. If that provider error ever proves too vague
to act on, it comes back as a new report with a real symptom behind it.

**The original report follows.**

**Found:** 2026-07-15, as `longcat-2.0` is in MODELS but can't chat.
**Closed 2026-07-21 (v0.4), re-opened by Cas:** dropping `longcat-2.0` from
`MODELS`, `MODEL_LIMITS` and the `TOOLS_MODELS` comment deleted the *instance*
and left the *class*. `ROADMAP.md`'s v0.4 note ("closed rather than fixed…
there was nothing to repair") is true about longcat and not true about this.

**The class is live, and the auto-revert's trust is backwards.**
`main.py:483-485`:

```python
revert_model = (prev_model
                if new_model not in known_models()
                and new_model != prev_model else None)
```

The safety net arms **only for models that are not in your config** — so the
one case it was built for, a broken id that *is* in `MODELS`, switches cleanly,
arms nothing, and 400s every turn with a raw provider error that never names the
model, until you work it out and switch back by hand.

**Cas's call (2026-07-27): arm on every switch.** Delete the `not in
known_models()` condition, keep `new_model != prev_model`, keep "a working turn
disarms". Accepted tradeoff: a genuine transient on the first turn after any
switch now bounces you back with `provider rejected 'X' — switched back to Y`
and you switch again. One annoying line against a session stranded on a dead id
with an error naming no model. If it grates, the refinement is to revert only on
rejections and not on the known-transient shapes the codebase already
recognises.

**Also called (2026-07-27): check `MODEL_LIMITS` and `TOOLS_MODELS` against
`known_models()` at startup.** They are separate lists that can name ids nothing
verifies, and a typo in `TOOLS_MODELS` means tools silently never turn on for a
model you believe is covered. That one is *silent*, unlike a bad `MODELS` id,
which is why it earns the line. It checks a claim already made rather than
adding one.

**Not covered by the 0.8.2 play-test (2026-07-27),** which confirmed that an
id *not* in `MODELS` is accepted and falls back correctly. That is the path that
already worked. The open case is a broken id that **is** in `MODELS`, which
arms nothing — so a green result on the first is not evidence about the second.

**Deliberately not doing:** validating `MODELS` by pinging each id at startup.
API calls on every launch, and a new claim.

**Still unresolved, and audible rather than silent:** `ROUTINE_MODELS[0]` has no
revert available at all — a scheduled run has no previous model to fall back to,
so a bad id there is a nightly `failed` forever. It is logged and the hub's
freshness column shows it. The only question is whether cfc should say *why*
more clearly than the provider error does.

---

## ~~The interactive tool path drops an empty-completion turn without offering a retry~~ — FIXED (v0.9, 2026-07-27)

**Closed 2026-07-27, in the v0.9.1 bookkeeping.** Shipped in `b423d30` as
`commands.empty_completion_decision`, called by *both* turn paths — which is
exactly what the entry's last line asked for. It reused the streaming path's
handler rather than forking it, so the drift this entry **was** got closed
rather than mirrored.

**The original report follows.**

**Found:** 2026-07-24, fixing the empty-completion 400 on the tool path.
Description: `agent_turn` now maps a thinking-model empty-completion 400 onto the
empty-completion path — it returns an empty message. Routines re-roll it
(`runner._turn_with_retry`); the **interactive** chat tool path (`main.py`, the
`use_tools` branch) just takes the empty return, prints the "provider hiccup"
note, renders an **empty answer panel**, and moves on.
Problem: the streaming path in the same situation *asks* `retry? (y/n)` (see the
empty-completion handler around `main.py:700`). The tool path offers no such
prompt and paints a blank panel. Not broken — a human can retype — but the two
paths handle the identical event differently, and the empty panel reads as a
render bug.
Suggestion: on an empty return from `agent_turn` in the interactive branch, skip
the empty panel and offer the same `retry? (y/n)` the stream path does. **Reuse
the handler, don't fork it** — standing decision 7 exists because these two
paths drifted once already, and this entry *is* that drift, caught small.

---

## ~~Three timestamp sites still print UTC~~ — FIXED (v0.9, 2026-07-27)

**Fixed:** all three localised via the new `ui.format_date`, beside `format_ts`. See `CHANGELOG.md`, 2026-07-27. Cas's call was to localise `export.py`'s full timestamp too. Original entry below.

## Three timestamp sites still print UTC. v0.8.1, 26-07-2026
**Found:** 2026-07-26, fixing the hub's clock (`CHANGELOG.md`). `ui.format_ts`
now converts, and `hub.py` was its only caller — these three read the db
directly and were left alone rather than swept, because two of them are
arguably correct and the third is a one-day edge.
Description:
- **`export.py:186`** writes the message timestamp into the exported markdown as
  the raw stored ISO string, offset and all. Defensible: an export is a data
  file and an unambiguous absolute timestamp is the right thing in one. It is
  also the only place in the vault that isn't local time, which is the argument
  the other way.
- **`export.py:108`** takes `created_at[:10]` for the export filename's date
  part. A session created after 22:00 local gets tomorrow's date in its
  filename.
- **`commands.py:1022` and `recall.py:40`** take `(created_at or "")[:10]` for
  the date label on a recall excerpt. Same one-day edge, display only.

Deliberately not swept: `format_ts` returns `YYYY-MM-DD HH:MM`, so none of the
three can just call it — the two `[:10]` sites want a date and `export.py` wants
a full timestamp, so this is three small decisions and not one substitution.
See `HANDOVER.md`, "Two time bases, and one conversion point".

**Cas's call (2026-07-27): localise all three.** The first one was the genuine
judgement call and it goes the same way as the other two — an export living in
the vault in a different time base from everything else in the vault is itself
the trap, and consistency beats the absolute timestamp's precision here.

The two `[:10]` sites want a *date*, so the shape is a `ui.format_date` beside
`format_ts`: one implementation, at the bottom of the dependency graph, taking
its input rather than importing config. Same reasoning that produced
`ui.vault_relative` in v0.8.2. **Any test here needs `test_hub.py`'s trick** —
an offset computed from the host's rather than a literal `+00:00` — or it passes
on a UTC machine without the conversion existing.

---

# The pre-split snapshot

Everything from here down is the file as frozen on 2026-07-27. Entries that
were still *open* at the split appear here too, and their closed versions are
above — the copy above is the current one.

---

Things found in passing and deliberately not fixed, so they don't get lost.
Nothing here is urgent — this is a hobby project and it all still works.

Add to this rather than fixing on the spot when something turns up mid-task.
CLAUDE.md is for how the project works; this is for what's still owed.

---

## ~~`/routines` isn't an alias, so it reaches the model.~~ — FIXED (v0.8.2, 2026-07-26)

**Fixed:** one line in `parse.ALIASES`. The other verbs were checked for the
same trap while it was open — the remaining plurals a hand reaches for
(`prompts`, `models`, `tags`) are already caught by `RETIRED`, which is due for
deletion in v0.9. **Worth a thought when it goes:** those words stop being
commands and become prose again, so `/models` will start reaching the model
exactly the way `/routines` did. This entry is the argument for promoting a
couple of them to aliases rather than simply deleting the dict.

Also note `tests/test_parse.py` used `/routines` as its example of the prefix
trap (`":attached".startswith(":attach")`). The guard is kept; its example moved
to `/helper`, because a deliberate alias is the opposite of the accidental
prefix match it was guarding against.

Original report below.

**Found:** 2026-07-26, Cas's 0.8.1 testing pass.
Description: `parse.ALIASES` has three entries and `routines` is not one of
them, so `/routines` is an unrecognised verb — which by invariant 13 is not an
error message but a **fall-through to the model**. Typing the plural costs an
API call and returns a confused answer about routines rather than the list.
Working as designed and still the wrong outcome for an obvious plural.
Suggestion: one line in `ALIASES`. Worth a glance at the other verbs for plurals
a hand reaches for by reflex while it's open.

## ~~`/list routine` prints the vault's absolute path.~~ — FIXED (v0.8.2, 2026-07-26)

**Fixed, and it turned up something bigger than the display.** This entry said
to decide once whether cfc shows paths relative to `VAULT_PATH`. It can't:
**`VAULT_PATH` is the export destination, not the vault** — on Cas's machine
`/mnt/c/Users/disse/backup/cfc/cfc_chat_backup`, not under the vault at all —
and `/config` was labelling it "Vault path:". There was no vault-root setting
anywhere. `ROUTINE_DIR`, `WIKI_DIR`, `JOURNAL_DIR` and `MOVE_ROOTS` are each
configured independently, every one of them commented `<vault>/…`, describing a
root that existed in the documentation and nowhere in the code.

So: a new **`VAULT_ROOT`**, display-only, read with `getattr` so an older
`config.py` keeps working, empty meaning "print in full". `ui.vault_relative`
does the trimming — one implementation, as this entry asked, living next to
`format_ts` because `ui.py` is the bottom of the dependency graph and takes the
root as an argument rather than importing config. `/config` prints both lines
under their real names now.

**Still only used in one place**, deliberately. Every other path cfc prints was
left alone rather than swept: some of them are the answer to "where exactly is
this", where the full path is the point. The helper is there when a site wants
it.

Original report below.

**Found:** 2026-07-26, Cas's 0.8.1 testing pass.
Description: the header reads
`Routines (/mnt/c/Users/disse/cooking for cats/06 metadata/routines)` — the
whole WSL mount prefix for a path whose only informative part is the tail. Cas
asked for `(/cooking for cats/06 metadata/routines)`.
Suggestion: display vault-relative. Note this is display only and there is more
than one such header — decide once whether cfc shows paths relative to
`VAULT_PATH` generally, and if so put the shortener somewhere shared rather than
formatting at each site. A second copy of "trim the prefix" is how one gets fixed
and the other doesn't.

## Three timestamp sites still print UTC. v0.8.1, 26-07-2026
**Found:** 2026-07-26, fixing the hub's clock (`CHANGELOG.md`). `ui.format_ts`
now converts, and `hub.py` was its only caller — these three read the db
directly and were left alone rather than swept, because two of them are
arguably correct and the third is a one-day edge.
Description:
- **`export.py:186`** writes the message timestamp into the exported markdown as
  the raw stored ISO string, offset and all. Defensible: an export is a data
  file and an unambiguous absolute timestamp is the right thing in one. It is
  also the only place in the vault that isn't local time, which is the argument
  the other way.
- **`export.py:108`** takes `created_at[:10]` for the export filename's date
  part. A session created after 22:00 local gets tomorrow's date in its
  filename.
- **`commands.py:1022` and `recall.py:40`** take `(created_at or "")[:10]` for
  the date label on a recall excerpt. Same one-day edge, display only.
Not urgent, and the first one may be a decision rather than a fix. Deliberately
not swept: `format_ts` returns `YYYY-MM-DD HH:MM`, so none of the three can just
call it — the two `[:10]` sites want a date and `export.py` wants a full
timestamp, so this is three small decisions and not one substitution.
See `HANDOVER.md`, "Two time bases, and one conversion point".

## ~~":wiki commit <message>" commits all changes, even when inspecting a specific diff.~~ — FIXED (2026-07-24)

**Fixed:** `:wiki` grew a `<action> <scope> <granularity>` grammar. Granularity
`file` runs a numbered picker over the changed files in scope and diffs/commits
**only** the chosen one, via a `paths=[…]` pathspec — the same containment as the
scope pathspec, one level finer, pinned in `test_wikigit.py` (commit one wiki
file, assert the other stays uncommitted). And `:wiki commit vault` (formerly
`all`) now asks `[y/N]` at folder granularity — the whole-repo sweep that
committed 202 files at once. Both halves of this entry, in one change.

Note the framing shifted during the fix: the move/stamp step is `:file` (the
mover), not `:wiki commit` (git). "Timestamp and move the files" was never
`:wiki commit`'s job — it commits what's already in the corpus. Per-file *commit*
is the git half; per-file *filing* stays `:outbox`/`:file`, and the two are kept
separate so the `:updatedb` re-import still sits between them.

Original report below.

Description: The command :wiki diff "file" allows user to inspect the diff on file level vs wiki db level, but the commit is wiki db level, not file.
Problem: user is viewing a single view, a commit there implies a commit on for the diff that is being inspected, not the entire wiki db. Start with file #1 and commiting that, means that now rest of the diff is NOT inspected, and commited -> script timestamps and moves the files.
Suggestion: inspecting individual diff -> commit -> commits only that diff. Confirms the timestamp, and accapted changes.
Also: :wiki commit all should give a (y/n) warning 'are you sure'. (may be implemented, was no diff to test this yet.)

## ~~chat selection screen shows routines that failed at their task, but performed their routine:: "ok - timestamp."~~ — FIXED (2026-07-24)

**Fixed:** the realisation underneath it — one ok/failed bit can't carry two
facts (did the loop run + did the model actually do the task) — is now two
signals. `status` stays loop-health (ok/failed); a second, orthogonal `review`
flag rides alongside it in the run log (`ok (review)`), computed by
`runner.looks_unclear` from the model's final message (first-person / jail-block
phrases like "I cannot", "outside my allowed roots", biased to over-flag).
`last_run` returns `(status, ts, review)`; the hub panel and `:routine` show a
yellow **review** distinct from red **failed** and dim **ok**, and `do_routine`
says so live. Kept out of `status` on purpose: the run didn't fail, so
`on_failure` must not retry it. Heuristic and fail-safe — reword the refusals and
it degrades to a plain `ok`, never a false `failed`. Pinned in
`tests/test_routines.py`.

Original report below.

Transcript: **2026-07-24 12:20:36** — ok — I cannot perform this task. The `mt memory.md` and `lt memory.md` files live in `/mnt/c/Users/disse/cooking for cats/03 resources/tiered memory/`, which is outside my allowed readable roots (`99 outbo… (42s, session 87)
That is good and bad, report of the model came through, so that's ok. But the script needs to read the models message and flag certain keywords/phrases. Routine overview should show that the routine worked (the ok) but also flag the user that the log shows something irregular, to be inspected. "last routine performed at *timestamp*, result unclear?" 

## Model selection is too generous, accepts anything. ~~No routine model selection possible.~~

**Routine model selection — FIXED (2026-07-24).** Routines gained an optional
`model:` frontmatter field. `runner.effective_model` resolves routine pin ›
caller/session model › vetted default, everywhere (both the `do_routine` nudge
and `run_routine` use it). `:routine new` prompts for one, `:routine` shows a
model column, and it round-trips through the file (omitted when unset). Before,
every scheduled routine could only run on `ROUTINE_MODELS[0]`.

**The blind-error symptom — FIXED (2026-07-24) with auto-revert.** The real
damage wasn't that `:model shanhaig` set a bad id; it's that it *persisted* it, so
every turn 400ed and it survived reopening the session — you found out only via
`:models`. Switching to a model not in `known_models()` now arms a revert: the
first turn that errors on it backs out to the model you were on, with
`provider rejected 'X' — switched back to Y`. A working turn disarms it, so a
valid unlisted model is untouched. See `main.py:revert_bad_model` /
`tests/test_model_revert.py`.

**Should `:model` be stricter? — CALLED BY CAS, BUILT IN v0.8.2 (2026-07-26).**
Shipped as described below, with two notes worth keeping. The suggestion list
is a **separate function from `resolve_model`** and a looser one (0.6 against
0.7), because a suggestion is offered rather than acted on — and it needs two
strategies, since difflib alone scores `minimax3` below any usable cutoff
against `minimaxminimaxm3`. The `[esc]` half of the ask was **not** built: see
the note at the end of this entry.


Neither of the two options this entry offered. Rather than rejecting an
unrecognised id or silently setting it, **show the near misses and let the
unrecognised one through on a deliberate keypress**:

```
"minimax 3" is not a recognized model. Did you mean:
  [1] minimax-m3
  [2] minimax-m3:thinking
Press [enter] to use "minimax 3" anyway
```

That keeps the escape hatch a valid-but-unlisted model needs — which is why
strict rejection was never right — while making the typo case one keystroke
instead of a 400 and an auto-revert. The auto-revert stays as the backstop for
what gets through.

Two wording fixes ride with it, same testing pass:
- The existing confirm reads
  `did you mean deepseek/deepseek-v4-pro? [Enter] yes / [n] no:`. Drop the
  vendor prefix — nobody types it and it doubles the length of the line — and
  make the decline key `[esc]` rather than `[n]`, so the two prompts agree
  about how you back out.
- Lowercase `[enter]` consistently.

**`[esc]` is still open, and it is not a wording change.** The vendor prefix is
gone and `[enter]` is lowercased, but every prompt in cfc is built on plain
`input()`, which reads a *line* — it cannot see a bare Esc at all. Detecting one
needs a keypress reader, and Esc is the ambiguous key to pick for it: terminals
send it as the prefix of every arrow key, so a bare Esc is only distinguishable
by a timeout. So the decline key is still `[c]`/`[n]`.

Worth doing properly or not at all, because the value is **consistency across
every prompt**, not this one: the hub picker, `/file`, `/wiki`'s pickers and the
model prompts should all back out the same way. That makes it a v0.9-or-later
job with `read_input` in `ui.py`, and it has to respect the standing decision
that prompt_toolkit and rich never drive the terminal at once. Recorded here so
the ask isn't lost.

`'deepseek pro'` / `'shanhaig'` below are typos that also missed the fuzzy
cutoff; the numbered list is what they should have got.

Original report below.

**deepseek pro' isn't in your configured models — setting it anyway
Switched to model: deepseek pro
Current model: deepseek pro
 'shanhaig' isn't in your configured models — setting it anyway
Switched to model: shanhaig
Current model: shanhaig**

## Processed notes stay in "00 inbox/notes" forever. 0.8, 24-07-2026
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
Suggestion: a code-driven move, same shape as the mover. After a successful run,
notes whose `created:` date is covered by that run move to a processed folder.
Deliberately not the model's job (it has a right answer) and deliberately not
part of v0.7, which had enough moving parts.

**Cas's call (2026-07-26): manual trigger first, `/clear notes`.** Not the
automatic post-run move above, and the reason is the one thing that entry
missed — **`00 inbox/notes` is read by more than one routine**, so "covered by
that run" isn't ownership. The first routine to finish would move notes the
second one hasn't read yet, and the second would then be silently short of
input, which is exactly this project's worst failure shape. A human command
sidesteps the whole question: by the time you type it, the loop and the script
have already dealt with the outbox, so nothing is still owed the notes.
`notes` needs no qualifier — the inbox one is the only one that means anything.
Leaves open, and worth deciding when it's built: what `/clear` does with a note
no routine ever read, and whether "clear" moves or deletes (it should move —
`LOSER_DIR` set the precedent that a discarded thing keeps its body).

## Obsidian's template syntax and cfc's placeholders are both "{{ }}". 0.8-adjacent, 24-07-2026
**Found:** 2026-07-24, adding the cadence placeholders.
Description: `runner.PLACEHOLDERS` substitutes `{{date}}`, `{{dates}}`,
`{{week}}` in a routine prompt. Obsidian's own templates use the same braces —
this vault's `note template.md` has `{{date:YYYY-MM-DD}}` in it.
Not live: matching is exact, so `{{date:…}}` is untouched, and the prompts point
at the template by path rather than quoting it. But a bare `{{date}}` pasted
into a prompt from an Obsidian template *would* be substituted, and the model
would then write today's date into a new note where the placeholder belongs.
Suggestion: an escape (`\{{date}}`), or confine substitution to a marked region.
Don't build it on spec — the failure is visible the first time it happens and
the fix is one line. Recorded so it isn't a surprise.

**Cas's call (2026-07-26): change the vault, not the code.** The Obsidian
properties are there to be inspected, not templated, so converting them to plain
text is a small one-time edit of a handful of markdown files and it removes the
collision at the source. Cheaper than an escape syntax nobody would remember,
and it belongs to the vault repo rather than this one — `cfc ships the
mechanism, the vault ships the words`. **cfc's side of this is nothing**, which
is the point: leave `PLACEHOLDERS` exact-matching as it is. Keep the entry until
the vault edit has actually happened, because until then the trap is live.

## ":file" takes a number, not a title. 0.7 leftover, 24-07-2026
**Found:** Cas's 0.6.2 testing pass.
Description: `:outbox` now shows each proposal's frontmatter title beside its
filename, which fixes the "list of bare timestamps" half of the report. Typing
one is still `:file 3`.
Suggestion: accept `:file Aquarium Nitrogen Cycle` as well, matching the title
case-insensitively, refusing an ambiguous match rather than guessing. Pairs with
the `:move` entry below — both are "name the thing instead of counting rows" —
so decide the argument-parsing shape once, for both.

## The interactive tool path drops an empty-completion turn without offering a retry. 0.8-adjacent, 24-07-2026
**Found:** 2026-07-24, fixing the empty-completion 400 on the tool path.
Description: `agent_turn` now maps a thinking-model empty-completion 400 onto the
empty-completion path — it returns an empty message. Routines re-roll it
(`runner._turn_with_retry`); the **interactive** chat tool path (`main.py`, the
`use_tools` branch) just takes the empty return, prints the "provider hiccup"
note, renders an **empty answer panel**, and moves on.
Problem: the streaming path in the same situation *asks* `retry? (y/n)` (see the
empty-completion handler around `main.py:700`). The tool path offers no such
prompt and paints a blank panel. Not broken — a human can retype — but the two
paths handle the identical event differently, and the empty panel reads as a
render bug.
Suggestion: on an empty return from `agent_turn` in the interactive branch, skip
the empty panel and offer the same `retry? (y/n)` the stream path does (reuse the
handler, don't fork it). Low priority; symmetry, not a fault.

## ~~":diff decline <file>" — send a declined draft to a losers' folder.~~ — FIXED (v0.7, 2026-07-24)

**Fixed**, as `:file <n> decline [why]` rather than `:diff decline <title>`. The
verb changed on purpose: decline is an argument to the existing filing command,
so it inherits the numbering `:outbox` already put on screen and needs no new
command name — which matters because the v0.8 taxonomy has no slot for a
`/decline`, and the `:`→`/` flip has to stay a pure prefix change. Built once
and pointed at both corpora, as the entry asked: `LOSER_DIR/<corpus>`
(`wiki/`, `journal/`, `notes/`), split by corpus because the reason to keep a
declined draft is to debug the prompt that produced it, which is a per-routine
question.

Beyond the original ask: the **reason is recorded on the draft itself**
(`declined:` / `declined_reason:` in its frontmatter). A folder of near-identical
rejects with nothing saying what was wrong with each is close to useless a week
later — you end up re-deriving the fault instead of reading it. Frontmatter is
edited by hand rather than re-dumped through `yaml`, since a round trip
re-quotes unquoted digit ids and mangles wikilinks; the reason is quoted and
escaped, because free text with a colon would otherwise cost the file its whole
frontmatter block. Pinned in `test_mover.py`.

Also landed with it: `99 outbox/dropped/` retires (still the fallback when no
`LOSER_DIR` is configured), and the outbox's own readme became undroppable.

Original report below.

**Found:** in the note-reader workflow rewrite (00 inbox/400-error brief).
Description: the wiki-review loop lets you inspect a proposed page's diff, but
there's no way to *reject* one from there. A decline should move that draft to
`03 resources/loser corner` rather than leaving it in the proposal folder or
silently dropping it — declined ≠ deleted, and the losers' corner is managed
later in a chat session (model reads on approval, output to `99 outbox`).
Suggestion: `:diff decline <file title>` (the diff display should show the title
so there's something to type). Code-driven move, same shape as the mover — the
command names the target, code re-validates and carries it out. v0.7's tiered
memory wants the same behaviour for declined journal entries (see the v0.7
draft), so build the move once and point both at it.
Note: pairs with the top entry — per-file `:wiki commit` and per-file decline are
the two halves of "act on the draft you're looking at, not the whole set."

## ":move" — a file selector over the outbox. 0.8, 24-07-2026
**Found:** in the note-reader workflow brief.
Description: a command to move a file out of `99 outbox` (top level only, not the
subfolders) into the vault, driven like `:attach`: list filenames, arrow-select,
Enter to confirm, Esc to leave. The terminal states what will move and asks for a
destination (default `00 inbox`, arrow-select subfolders — today only
`00 inbox/notes` exists). A single Enter confirms — moving files, not replacing,
so no y/n. If a same-named file exists at the target, warn and offer: replace /
rename-the-new-one (timestamp appended?) / cancel; typing `replace` rather than
picking it is the protection against a careless clobber.
Where it fits: it's a filing command, closest to the existing `:outbox`/`:file`
pair rather than the taxonomy's attach/remove verbs — decide during v0.8 whether
it's a third filing command or an extension of that pair before naming it, so it
lands under the right prefix.

## Retire the ":"-command "startswith" chain for an exact-match table. 0.8-adjacent, 24-07-2026
**Found:** 2026-07-24, planning the v0.8 command flip.
Description: dispatch in `main.py` is a long `if user.startswith(":x")` chain, and
the branch order is load-bearing — `":attached".startswith(":attach")` is true,
which `main.py:368` carries a comment about. The v0.8 `:`→`/` flip is a *prefix
change* by decision, so it preserves the trap rather than fixing it.
Suggestion: after the flip settles, replace the chain with an exact-match command
table + argument split, which kills the ordering trap structurally. Deliberately
**not** bundled into the flip — that would break the "one re-baseline, pure
prefix change" property that makes the flip safe. Its own session. See the v0.8
build draft, block 5.


## ~~The run log sits inside the model's write scope~~ — FIXED (2026-07-23)

**Fixed:** `tools.reserved_write_reason()` refuses any write resolving inside
`ROUTINE_LOG_DIR`. Containment against the one directory, as this entry asked,
not a filename pattern. Enforced in `write_file` — **the boundary, because
`dispatch()` is reachable with no gate at all** — and mirrored in `precheck` so
the gate never prompts for a call that cannot succeed. Writes only; reading a
log is still allowed. Resolution happens before the check, so a symlink out of
the outbox into the log dir is judged as its target. Verified against the real
config (the live `heartbeat.md` is refused and unchanged), and the new
assertions were confirmed to fail with the guard disabled.

One thing this deliberately does *not* do: it makes no attempt to be a general
"reserved paths" mechanism. There is one such directory, so there is one check.
A second one is the point at which it should become a list.

Original report below.

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

## ~~`append_log`'s `touched=()` is never passed~~ — FIXED (2026-07-23)

**Fixed:** the collector, as this entry preferred — `agent_turn` takes an
optional `touched` list and appends each successful write to it. A routine
passes one, chat passes nothing, and the signature stays honest about who
cares.

- **The collector is owned by `run_routine`, not by the turn.** Both of the
  turn's failure exits leave by raising (`CallLimitReached`, `EmptyCompletion`),
  so a value returned *from* the turn cannot carry the answer out of exactly
  the case the entry is about. The caller holds the list, so the `except`
  branch logs it. It also spans re-rolls: `history` is rebuilt per attempt,
  but files an earlier attempt wrote are on disk and stay there.
- **`tools.written_path()` reads `write_file`'s own result**, so the tool loop
  never has to understand tools and a *refused* write is never reported as one
  that happened. The producer and the parse live together, with the same hazard
  as `commands.py`'s markers and `db._MARKER_RE`: reword the success line and
  this returns None forever, which reads as "the run wrote nothing". Pinned by
  round-trip — a real write, parsed from its real result — so a reworded
  message fails a test instead of silently emptying a log field. Verified by
  rewording it: 4 assertions fail.
- **The rendering changed too, which the entry didn't foresee.** The first real
  line was unreadable: full paths repeat the 47-char write root per file, and
  the ` — ` field separator collides with the em-dashes *inside* this vault's
  filenames (`wiki draft — chunking.md`), so the list had no findable end. Now
  names rather than paths, and the list goes **last**, where everything after
  the colon is the list:

```
- **2026-07-23 07:09** — failed — TimeoutError: provider went away — wrote 2 files: wiki draft — sqlite-vec.md, wiki draft — chunking.md
- **2026-07-23 07:09** — ok — Nothing to do. (8s, session 392)
```

`last_run()` is unaffected — `_LOG_RE` is anchored at the head of the line.
A run that wrote nothing grows no `wrote` clause at all.

Original report below.

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

## ~~`golden.py check` writes a file into VAULT_PATH~~ — FIXED (2026-07-23)

**Fixed:** redirected, not disabled, as this entry asked — `VAULT_PATH` is now
patched on every cfc module that holds one (the same loop shape as `DB_PATH`,
and for the same reason: `export.py` and `commands.py` each hold a copy, so
patching one leaves the other pointing at the real folder). Exports land in
`tests/_fixture_vault` and are removed at the end of the run.

Three things came out of it that the entry didn't anticipate:

- **The baseline was pinning Cas's real vault path** on the `:config` line —
  the same class of bug as the API-key line that earned the `SCRUB` paragraph
  in `HANDOVER.md`. It now reads `<ROOT>/tests/_fixture_vault`, exactly like
  the `Prompts dir` line above it. That was the only line that changed;
  re-recorded.
- **`AUTO_EXPORT` is pinned on** rather than read from config. The script's
  `:q` only takes the export path when it's true, so leaving it to config
  meant the baseline covered a different amount of code on different machines.
- **The new guard caught the fix's own bug.** `assert_not_real_vault` first
  re-read `config.VAULT_PATH` at call time — after the loop had patched
  config's own copy — so it compared the fixture against itself. `REAL_VAULT`
  is now frozen at import, before anything is rewritten.

Verified: two consecutive `check` runs leave the real folder's mtimes
unchanged, and the guard was confirmed to fire when pointed at the real vault.
The harness also now asserts a document actually landed — the baseline pins
the `[auto-exported: …]` *message*, and `safe_export` swallows its own errors,
so those are not the same claim.

Left alone: the two stale `…_Renamed By Golden.md` files this bug already
wrote into the export folder. They are Cas's to delete.

Original report below.

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

## ~~A chunk with a dangling `session_id` — where does it come from?~~ — ROOT CAUSE FOUND, FIXED (2026-07-23)

**It was not `import_anthropic.py`, and it was not moot on the wiki db.** Both
guesses in the original report were wrong, and the second one is why this sat
here: the entry said the current corpus was unaffected, so nobody looked.

**Root cause: `db.delete_session` and `db.delete_message` never cascaded to
`chunks` or `vec_chunks`.** There are no foreign keys (`PRAGMA foreign_keys`
is 0 and the tables were never declared with any), so nothing enforced it.
Measured on the live db before the fix:

```
chunks 1011 · 152 whose message row is gone · 143 of those still had vectors
             ·  55 whose session_id disagrees with their message's
sessions 41 and 49 — deleted, their chunks still present
```

That is **three** bugs, and the reported one is the least of them:

1. **A deleted conversation stays in the retrieval index.** 143 vectors of
   deleted content were still searchable. A delete that leaves the text
   answering questions is not a delete. (Recall filters `provider='wiki'`, so
   they weren't reaching `:recall` today — but `search()` returns them, and
   the planned wiki+chat hybrid is precisely the thing that would surface
   them.)
2. **Orphaned rows** — the dangling `session_id` that was reported.
3. **Mis-attribution, the dangerous one.** SQLite reuses rowids at the top of
   a table, so a later message takes a deleted message's id and the stale
   chunk *joins cleanly* to it. Chunk 885's text is a routine log path; the
   message it now joins to reads `:wik commit all`. `search` reports such a
   chunk under that message's session, date and title — a citation pointing at
   a conversation the text never came from, silently.

**Fixed:** `delete_session`/`delete_message` now drop the index rows first,
while the messages that identify them still exist; `delete_session` also
sweeps chunks by `session_id` directly, for ones whose message was already
deleted separately. Vectors go before chunks and a failure there raises rather
than continuing — a chunk without its vector is stale, but a vector without
its chunk is text in the index that nothing can inspect or attribute.

**Repair for databases already damaged:** `db.find_stale_chunks()` /
`prune_stale_chunks()`, surfaced as `:updatedb prune`. Plain `:updatedb`
*reports* a stale count and removes nothing — this is the one maintenance path
that deletes, and a command run casually should not quietly drop rows. Both
detection rules are exact, not heuristic:

- the message row is gone; or
- `chunks.session_id != messages.session_id`, which **cannot happen in normal
  operation** — `chunk_new` copies the session id straight off the message row
  it is chunking, and `messages.session_id` is never reassigned anywhere in
  the codebase. A disagreement is proof of a reused rowid.

Verified on a **copy** of the live db: 207 stale chunks and 195 vectors
removed, idempotent on a second run, zero `source='wiki'` rows touched (every
stale row was `source='chat'`), messages and sessions untouched, no vector
left without a chunk. Six assertions confirmed to fail with the cascade
removed.

**Still open, deliberately:** real foreign keys with `ON DELETE CASCADE`.
SQLite cannot add one to an existing table without rebuilding it, and the
chunk/vector schema is already flagged as in flux — this belongs to the
DB-layer rework. The code cascade is the smaller, reversible half.

Also noted: `import_wiki.clear_chunks_for_message` does the same
vector-then-chunk dance for the same reason, and is still a second copy of it.
Left alone rather than merged mid-fix, but two implementations of a delete are
how one gets fixed and the other doesn't.

Original report below.

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

## ~~`write_file` refuses relative paths, and only the prompt prevents it~~ — CLOSED (2026-07-23)

**Closed the way this entry asked to close it: a better error, not a
reinterpretation.** The refusal is unchanged — resolving a relative path
against the write root would make the tool's behaviour depend on how many
roots are configured, and "the path you passed is not the path that was
written" remains the worst property the one mutating tool could have.

What changed is the explanation. The old message named a path the caller never
typed:

```
/home/disse/projects/cfc/heartbeat.md is outside the allowed roots (…/99 outbox)
```

which reads as the jail being misconfigured rather than the path being
relative. Now:

```
… is outside the allowed roots (…/99 outbox) — 'heartbeat.md' is a relative
path, resolved against the working directory /home/disse/projects/cfc. Pass an
absolute path.
```

**The note is added only when the input was relative**, so an absolute path
that misses the roots is not told it is relative. `runner.SYSTEM` keeps saying
"always pass absolute paths" — the prompt avoids the error, the message
recovers from it, and neither is the boundary.

**What a blanket refusal of relative paths would have broken, checked rather
than assumed:** the process cwd (`~/projects/cfc`) *is* inside a read root, so
relative **reads** currently resolve and succeed. Refusing them outright would
have removed working behaviour to fix a message. It is not inside a write root,
which is why every relative *write* fails and this only ever bit `write_file`.

Original report below.

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
