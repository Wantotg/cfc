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

## D-2.0-50 · The switcher's current-chat class has no style

**Found:** 2026-08-09, by reading during the v2.0 Stage 4 loop one playtest.

`ChatScreen._render_switcher` adds `chat-switcher-current` to the current
chat's item, but `cfc/tui.tcss` has no rule for that class. The wide switcher
therefore gives no visual indication of which chat is open.

Add one stylesheet rule and prove that the current item is visibly distinct.
This is separate from `B-2.0-47` so the visual defect cannot disappear if the
selection fix is split from the same pass.

---

## D-2.0-49 · cfc inherits Textual's whole command palette without deciding what is in it

**Found:** 2026-08-09, during the v2.0 Stage 4 loop one playtest.

`Ctrl+P` exposes Textual's built-in command palette because cfc has not chosen
its own command provider. Its Screenshot command can fail when the platform's
downloads directory does not exist, and its theme choice is only in memory.

Later Stage 4 work should decide which commands cfc owns, give screenshot a
created destination with a recovery route, and decide where interface
preferences such as the chosen theme belong. This is ownership and product
design work, not a request to copy Textual's default command list.

---

## D-2.0-43 · Provider evidence checks can discard a usable answer, and one malformed usage shape walks past them

**Found:** 2026-08-09, during the v2.0 Stage 3 loop three playtest.

A response with a usable assistant message is rejected when a proper `usage`
object contains an invalid count or when a top-level `error` object is present.
By contrast, a non-object `usage` value is treated as if usage was not reported.
These three cases disagree about whether an unrecognised provider field may veto
otherwise usable content.

The body remains untrusted and unpersisted. Revisit the veto and absent-usage
decisions when a real gateway supplies evidence, keeping the adapter's stored
reason bounded and provider-independent. This is watching work for Stage 4,
not a reopening of `D-2.0-37` or `D-2.0-38`.

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

## D-04 · Future prompt surfaces still need the shared Escape behaviour

**Found:** 2026-07-26, during Cas's 0.8.1 testing pass.

The old obstacle is retired: Textual now owns live terminal input, and the
layered `Esc` route is implemented and proved for the Stage 4 Hub and Chat
surfaces. The remaining debt is applying that same contract consistently as
the other prompt surfaces are built — including the hub picker, `/file`,
`/wiki` pickers, and model prompts named by the original finding.

Keep this open until those surfaces exist and each one closes a modal, cancels
an active prompt, or returns to the Hub at the correct layer.
