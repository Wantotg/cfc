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

## D-2.0-61 · Keyboard help reads as a specification, not sentences

**Found:** 2026-08-10, during the v2.0 Stage 5 loop one playtest.

Keyboard help lists bindings as reference rows and drops a raw Windows Terminal
JSON fragment into the middle of them. The interaction works, but the requested
overview is not readable normal-language guidance. Rewrite the copy as short
sentences while retaining the tested key behaviour and terminal requirement.
This is wording work for the Stage 10 release-facing documentation pass, not a
reason to reopen the shipped Stage 4 interaction.

## D-25 · `cfc doctor` says nothing about the vault categories or model catalogue

**Found:** 2026-08-10, by reading during the v2.0 Stage 5 loop one diagnosis.

`cfc doctor` reports the provider, database, and interpreter, but not the four
vault categories or the model catalogue. A person therefore cannot use the
diagnostic command to learn which context sources and models cfc can use before
opening a chat. Add bounded readiness information for those optional surfaces,
including a useful correction route without exposing credentials or vault
content. This belongs to the remaining Stage 5 vault work.

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

## D-2.0-59 · `TUI_THEME` has no visible confirmation, and one surface ignores it

**Found:** 2026-08-10, by reading during v2.0 Stage 4 loop three diagnosis.

The optional `TUI_THEME` setting is not reported by `doctor`, so a commented-out
setting and a working default are indistinguishable from the outside. The
startup-failure screen also ignores the configured theme and always uses the
dark theme. Add bounded confirmation of the resolved theme and carry the
setting through the startup-failure surface. This is v2.0 Stage 4 or later;
it does not block the completed Stage 4 claim.

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
