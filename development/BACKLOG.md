# Backlog

Things found in passing and deliberately not fixed, so they don't get lost.
Nothing here is urgent — this is a hobby project and it all still works.

Each entry carries its tracker id in the heading — the id the playtest report
gave it, unchanged thereafter.

## When an entry closes

**Delete it whole and leave nothing behind here.** This file holds open entries
only. `workspace/TRACKER.md` keeps the resolution, `development/CHANGELOG.md`
records a shipped change, and Git history retains the deleted body. The
reasoning is in `HANDOVER.md`, *Which file owns what*.

---

## D-2.0-17 · The 2.0 interpreter floor is lower than the supported baseline

**Found:** 2026-08-09, during the v2.0 Stage 2 loop one playtest.

`cfc/entry.py` refuses interpreters below 3.10, while the 2.0 design and
refactor roadmap name Python 3.14 as the supported baseline. cfc 2.0 has only
been run on 3.14.4, so claiming that four older minor versions are supported
would be broader than the evidence. Raise the 2.0 floor to 3.14 and state it
in the 2.0 bootstrap instructions in `config.example.py`. The README's
3.10 requirement describes v1.9.1 and remains unchanged until cutover.

## D-2.0-16 · The 2.0 database field should be `DATABASE_PATH`, not `DB_PATH`

**Found:** 2026-08-09, during the v2.0 Stage 2 loop one playtest.

`cfc/settings.py` currently exposes the new 2.0 database target as `DB_PATH`,
while the 2.0 design named it `DATABASE_PATH`. `DB_PATH` is also the legacy
database constant in `db.py` and the name patched by the characterization
tests, so the same spelling now points at two different databases. Nothing
consumes the new field yet. Rename it in `cfc/settings.py` and
`config.example.py` before Stage 3 opens a real database through it.

## D-2.0-07 · Doctor gives no next step, and no state for a row it never checked

**Found:** 2026-08-09, during the v2.0 Stage 2 loop one playtest.

The 2.0 design gives each diagnostic a canonical state, a safe explanation,
and an actionable next step. `Row` currently has only a name, state and detail.
When configuration fails, downstream rows are marked `error` even though they
were not diagnosed, which also conflicts with the diagnostic module's rule that
optional rows are never `ERROR`. The required-row check asks only whether any
required row is `ERROR`, so it would also accept a required row that was never
examined.

Add a `not checked` state for dependent rows, make required readiness mean that
every required row is `READY`, and give known failure cases a `next_step` that
renders as a readable second line. The missing-configuration route is the
first concrete case: copy `config.example.py` to `config.py`, then fill the
required provider settings. Keep the downstream explanation local to those
rows, while the configuration row owns the cure.

## D-2.0-02 · The forged-text assertion passes only because 80 columns wraps the string

**Found:** 2026-08-08, by reading during v2.0 Stage 1 loop one.

`tests/test_websearch.py:685` asserts that `forged_call` is not in the
captured output under the label that raw forged-tool-call text never reaches
the console a human reads. The search result snippet is printed verbatim as
inert result content, so the text does reach the console at every width. It
only disappears from the assertion because the 96-character string wraps at
80 columns and is no longer contiguous.

The behaviour is correct and the surrounding assertions carry the real
claims: the text remains inert result content and exactly two provider round
trips occur. The old assertion is debt in the legacy suite, not an application
bug. It should wait for Stage 7, when web search is rebuilt through the new
tool lifecycle and the legacy suite retires; correcting the old assertion
first would do the work twice.

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
