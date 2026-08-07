# Backlog

Things found in passing and deliberately not fixed, so they don't get lost.
Nothing here is urgent — this is a hobby project and it all still works.

Each entry carries its tracker id in the heading — the id the playtest report
gave it, unchanged thereafter.

## When an entry closes

**It moves to [`legacy/BACKLOG.md`](../legacy/BACKLOG.md), whole, and leaves
nothing behind here.** This file holds open entries only. The reasoning is in
`HANDOVER.md`, *Which file owns what*.

---

## D-21 · An unreadable outbox root leaves the proposal screen silent

**Found:** 2026-08-06, v1.9 loop 2 debugger pass.

`_print_outbox_contents_pointer` counts only roots whose status is `INV_OK`.
With every configured root unreadable or missing, the total is 0, the pointer
stays silent, and bare `/list outbox` prints `(no filing proposals pending)`
with nothing after it — the screen implies an empty outbox at the one moment it
cannot know. The contents view renders this state correctly, per root, in red.

**Owed:** when a root is not `OK`, say that the count is partial and point at the
contents command. A sentence, not a design.

---

## D-19 · Twelve test suites pin the shared console, and the damage is silent

**Found:** 2026-08-06, v1.9 loop 2 debugger pass. The pattern predates this
loop: `N-1.6.4-10` fixed it in one test, but the eleven other files were never
swept.

Twelve files under `tests/` end a capture with `console.file = sys.stdout`
instead of restoring what was there. `ui.console` is one shared Rich console,
and assigning `sys.stdout` pins it. Every later `redirect_stdout` in the same
process then captures an empty string while still looking like it worked.

The house runner is one process per file, which hides the problem. Running the
whole suite in one process reproduces it: `test_empty_retry.py` fails while
pytest's own captured stdout shows the line was printed. Four collected suites
reproduce it individually.

**Owed:** restore the saved console file, or restore `None`, at all twelve sites.
This is a bounded v1.9.1 maintenance row.

---


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
