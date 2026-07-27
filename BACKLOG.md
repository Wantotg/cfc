# Backlog

Things found in passing and deliberately not fixed, so they don't get lost.
Nothing here is urgent — this is a hobby project and it all still works.

Add to this rather than fixing on the spot when something turns up mid-task.
`CLAUDE.md` is for how the project works; this is for what's still owed.

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

## The golden baseline pins the live vault outbox. 0.9.1, 27-07-2026

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

## `[esc]` doesn't back out of prompts, and can't while they're `input()`. 0.8.2 remnant

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

## Obsidian's template syntax and cfc's placeholders are both "{{ }}". 0.8-adjacent, 24-07-2026
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

## "/file" takes a number, not a title. 0.7 leftover, 24-07-2026
**Found:** Cas's 0.6.2 testing pass.
Description: `/outbox` now shows each proposal's frontmatter title beside its
filename, which fixes the "list of bare timestamps" half of the report. Typing
one is still `/file 3`.
Suggestion: accept `/file Aquarium Nitrogen Cycle` as well, matching the title
case-insensitively, refusing an ambiguous match rather than guessing. Pairs with
the `/move` entry below — both are "name the thing instead of counting rows" —
so decide the argument-parsing shape once, for both.
**Where it lands:** past 1.0. `ROADMAP_BEYOND.md`'s proposed 1.1 holds it.

## "/move" — a file selector over the outbox. 0.8, 24-07-2026
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
