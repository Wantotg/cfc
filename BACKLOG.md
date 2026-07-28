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
