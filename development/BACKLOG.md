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

## D-2.0-05 · A guard-shaped line at column zero inside a triple-quoted string still counts

**Found:** 2026-08-08, by reading during v2.0 Stage 1 loop two.

`tests/test_entry_gate.py` recognises a legacy suite with a line-anchored
regular expression. A line with the guard shape inside a multi-line
triple-quoted string therefore counts as a suite even though it is only test
fixture text:

```python
SRC = """
if __name__ == "__main__":
    main()
"""
```

The frozen-list comparison fails loudly on a false positive, which is safer
than the old substring test, but it invites adding a non-suite to the list.
That child process can import a module, do nothing, and exit successfully,
leaving the gate green while checking nothing.

When the entry gate is next touched, recognise the guard structurally with
`ast.parse` and an `ast.If` whose test compares `__name__` with `"__main__"`.
String literals and comments cannot produce that statement shape. This is
small enough to ride with the next gate change and does not earn a loop of its
own.

## D-2.0-04 · The one complete check cannot run without a personal `config.py`

**Found:** 2026-08-08, by reading during v2.0 Stage 1 loop one.

The entry gate depends on the ignored, personal `config.py`. With that file
absent, 28 test modules fail during collection and pytest runs no tests. The
test content itself is not the problem — the run leaves live data untouched —
but the one command claiming to be the complete v1.9.1 preservation gate is
not usable from a fresh clone.

This belongs to Stage 2, where `python -m cfc doctor` must diagnose validated
settings and availability, beside `W-11`'s `config.example.py` rewrite. The
fresh-clone route and the usable example are the same gap seen from opposite
sides.

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
