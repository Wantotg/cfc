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

## D-2.0-56 · Nothing tells a person `Shift+Enter` needs a configured terminal

**Found:** 2026-08-09, during the v2.0 Stage 4 loop two playtest.

The Composer correctly handles Textual's `shift+enter` event, but a terminal
that does not send Kitty keyboard-protocol sequences can deliver the same
carriage return for `Shift+Enter` as for `Enter`. cfc currently gives no
guidance for that environment requirement.

Document the supported terminal requirement and the Windows Terminal mapping
that restores the natural key. If the interaction contract chooses a fallback
key, document that route and expose it consistently in cfc as well.

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

## D-2.0-53 · A failed turn's message is never sent, and nothing says so

**Found:** 2026-08-09, during the v2.0 Stage 4 loop two playtest.

The provider-wire history rule correctly omits a failed or cancelled turn's
orphaned user message from every later request. The transcript only says that
the turn failed, so a person is not told that the message was never sent and
that later replies will not see it.

Make the failed and cancelled transcript lines state the omission. Prove both
outcomes with a later completed turn and verify that the stored message remains
unchanged while the provider request omits it.

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
