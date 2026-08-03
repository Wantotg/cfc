# Backlog

Things found in passing and deliberately not fixed, so they don't get lost.
Nothing here is urgent — this is a hobby project and it all still works.

Each entry carries its tracker id in the heading — the id the playtest report
gave it, unchanged thereafter.

## When an entry closes

**It moves to [`legacy/BACKLOG.md`](legacy/BACKLOG.md), whole, and leaves
nothing behind here.** This file holds open entries only. The reasoning is in
`HANDOVER.md`, *Which file owns what*.

---

## D-14 · `ui.vault_relative`'s docstring names the retired export key

**Found:** 2026-07-31, during the v1.3.1 config-key rename. The docstring says
`config.VAULT_PATH`, but the function's caller passes `VAULT_ROOT` and the
function never reads config. The behaviour is correct; the one-word reference
is stale after `CHAT_EXPORT_DIR` replaced the old export-destination name.

**Owed:** correct the docstring when that file is next touched. No code change
is needed for the current release.

## D-17 · `errorlog` records the turn's module, never its kind

**Found:** 2026-08-02, while answering whether `/swipe` is luckier than sending
a second message. `errorlog` records a chat error as `chat`, but does not say
whether the turn was a send, `/swipe`, `/continue`, or OOC turn, so the question
cannot be counted from the log.

**Owed:** pass the turn kind from `_run_turn` to `errorlog` at its call site,
preserving the existing module context while making those paths measurable.

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
