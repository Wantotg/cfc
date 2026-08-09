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

## D-2.0-36 · Nothing serialises two turns in one chat now that `send_turn` is awaitable

**Found:** 2026-08-09, during the v2.0 Stage 3 loop two playtest.

Two concurrent sends can start in one chat. Both turns end and retain explicit
positions, but the second snapshot can contain another active turn, so the
provider either sees an unfinished conversation or the converter refuses it.

This becomes live Stage 4 debt when the composer remains available during a
background turn. The service needs one-turn-per-chat serialisation or a visible
queue/refusal decision; the converter is right to refuse the incoherent
snapshot.

---

## D-2.0-37 · An in-band provider error is indistinguishable from an unrecognised shape

**Found:** 2026-08-09, during the v2.0 Stage 3 loop two playtest.

Some OpenAI-compatible gateways return a successful HTTP status with an
`error` object instead of `choices`. The adapter currently reports the same
generic malformed-response evidence as an empty or unsupported response.

The body must remain untrusted and unpersisted, but cfc can name the observed
error-envelope shape with its own bounded reason. This is Stage 3 follow-up
work, not permission to store provider text.

---

## D-2.0-38 · Usage counts arriving as floats or numeric strings are dropped

**Found:** 2026-08-09, during the v2.0 Stage 3 loop two playtest.

The adapter accepts plain integer counts and deliberately rejects booleans, but
it also drops whole-number floats and numeric strings by treating them as
missing usage. The completion succeeds, while `usage=None` now conflates no
usage with an unaccepted spelling of reported usage.

Decide and test the supported provider spellings at the adapter boundary;
preserve explicit zero and partial-count semantics.

---

## D-2.0-39 · No test joins the store's real snapshot to the converter

**Found:** 2026-08-09, during the v2.0 Stage 3 loop two playtest.

The converter tests construct snapshots by hand, which is necessary for
contradiction refusals, but no automated test passes a snapshot produced by the
real store through the real converter. The producer/reader pair was probed
manually and worked; the missing regression belongs in a Stage 3 follow-up.

---

## D-2.0-28 · A refused target keeps the `.lock` sidecar cfc created beside it

**Found:** 2026-08-09, during the v2.0 Stage 3 loop one playtest.

`open_store` acquires the ownership lock before classifying the existing
target. If the target is corrupt, foreign, or empty, cfc refuses it after
creating `<path>.lock`, and that sidecar remains beside a database cfc has
declared incompatible. The target bytes are unchanged.

Deleting the lock file on refusal is not a safe quick fix: another process may
already hold it open, and unlinking it could let later processes lock a new
inode while the first process still believes it owns the old one. The existing
`schedule.py` lock accepts the same lifecycle. The design choices are to
inspect before locking, reopening a time-of-check gap, or to keep the lock in
another location. This is owed design work, not a cleanup deletion.

---

## D-2.0-20 · The runtime row reports no version when it passes

**Found:** 2026-08-09, during the v2.0 Stage 2 loop two playtest.

`_runtime_row` returns `ready` without saying which interpreter it checked or
what floor it enforces. The passing row should report the state the behaviour
uses, just as the other healthy rows report their path or provider details.
Include the running version and the 3.14 floor, for example `3.14.4 (floor
3.14)`.

## D-2.0-19 · The chat provider row names one missing field per run

**Found:** 2026-08-09, during the v2.0 Stage 2 loop two playtest.

With an empty `config.py`, doctor names only `API_BASE`. After that is set, it
names only `API_KEY`, and then only `MODEL`. The settings builder deliberately
raises on the first missing provider field, but the diagnostic row is the
fresh-clone surface a person uses to learn what needs filling.

Collect the missing required provider fields in `diagnostics._provider_row` and
name them together. Keep `settings.build_provider` fail-fast for callers that
need one actionable exception rather than a list.

---

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
