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

## D-2.0-119 · Context-modal buttons and rows disagree about the available action

**Found:** 2026-08-22, during the v2.0 Stage 6 loop one diagnosis.

The Context modal mixes rows that act with buttons that act on the highlighted
row. An empty Persona offers **Change** while **Add** is disabled, and an
existing Trait cannot use the visible Add button. Choose one coherent
interaction model before the next Context-modal work.

## D-2.0-117 · The Chat status line and Context modal use different source names

**Found:** 2026-08-22, during the v2.0 Stage 6 loop one diagnosis.

The same context sources appear as `prefs:` and `opening:` in the status line
but as `User Preferences` and `First Message` in the Context modal. Centralise
or reconcile the vocabulary so a person does not have to learn two names for
one source.

## D-2.0-116 · Tool operational evidence is incomplete and has no result-hash producer

**Found:** 2026-08-22, during the v2.0 Stage 6 loop one diagnosis.

The evidence table is body-free and structurally sound, but rows are written
only after an approved executor returns. Refused, unavailable, invalid,
cancelled, interrupted, and repaired calls leave no evidence, and the real
service never supplies `result_hash`. Extend evidence through the interactive
approval and lifecycle paths without storing sensitive result bodies.

## D-2.0-115 · An in-flight provider exchange leaves no interruption evidence

**Found:** 2026-08-22, during the v2.0 Stage 6 loop one diagnosis.

If cancellation or process interruption occurs while the responder is still
waiting, the turn is stored but no provider-exchange row records what happened.
Give the in-flight exchange a durable interrupted representation and prove it
through cancellation and reopen recovery.

## D-2.0-114 · File-tool execution runs on the event-loop thread

**Found:** 2026-08-22, during the v2.0 Stage 6 loop one diagnosis.

The synchronous executor blocks the event loop, so a Textual cancellation
cannot arrive during a long read or grep. Move execution off the event loop and
provide a cancellation token the worker can observe before loop two's approval
surface depends on responsive cancellation.

---

## D-2.0-105 · Driven widget tests do not prove painted terminal output

**Found:** 2026-08-19, during the v2.0 Stage 5 loop four second-run diagnosis.

The driven TUI tests asserted widget content but did not assert the rows Textual
actually painted, so a status bar could be present in memory while the Footer
covered it for an entire loop. One painted-output helper now exists; audit the
remaining important status and layout claims against the terminal surface.

## D-2.0-103 · Context rows cannot clear Persona or User Preferences directly

**Found:** 2026-08-19, during the v2.0 Stage 5 loop four second-run playtest.

The Context modal enables **Remove** only for selected Trait and Attachment
rows. Clearing a selected Persona or User Preferences value therefore requires
opening **Change** and navigating to its final **None (clear selection)** row.
Decide whether the row-level **Remove** action should clear those two categories
directly while keeping the deliberate no-accidental-clear picker rule.

## D-2.0-101 · Turn details shows the full fingerprint in the compact modal

**Found:** 2026-08-19, during the v2.0 Stage 5 loop four second-run playtest.

Turn details now correctly shows frozen size and fingerprint evidence, but the
full 64-character value makes ordinary reading harder and directly contributes
to modal overflow. A Designer decision is needed on the compact display; the
full value can remain in the export for cross-checking.

## D-2.0-99 · Attachment picker count needs a noun

**Found:** 2026-08-19, during the v2.0 Stage 5 loop four second-run diagnosis.

The filtered attachment picker says only `12 of 506`, while its other states
name Markdown files explicitly. Choose wording such as `12 of 506 files` so
the count remains understandable without relying on surrounding context.

## D-2.0-88 · Export confirmation shows an unnecessarily long absolute path

**Found:** 2026-08-19, during the v2.0 Stage 5 loop four second-run diagnosis.

Manual export succeeds, but the confirmation exposes a 105-character absolute
path instead of the filename a person needs to recognise. Keep the confirmation
visible and shorten its useful identity to the exported filename.

## D-2.0-87 · A leading slash is sent to the model as ordinary text

**Found:** 2026-08-19, during the v2.0 Stage 5 loop four second-run playtest.

A leading `/` reaches the model, which can respond as though cfc performed an
action it never performed. Decide whether this surface should reject or
reserve leading slash input before it reaches the provider.

## D-2.0-61 · Keyboard help reads as a specification, not sentences

**Found:** 2026-08-10, during the v2.0 Stage 5 loop one playtest; raised again
in the v2.0 Stage 5 loop four second-run playtest.

The interaction works, but the `Esc` line still reads as a precedence chain
(`else`) in a list whose neighbouring lines use mixed voices. Rewrite the copy
as short, consistent sentences while retaining the tested key behaviour and
terminal requirement. The repeated sighting confirms this remains owed; it was
not satisfied by the loop-four wording pass.

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
