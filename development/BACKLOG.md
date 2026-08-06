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

## D-1.7-02b · Three outbox screens describe the same folder three ways, and one of them says something false

**Found:** 2026-08-04, v1.7 playtest, with 24 files in the outbox and 0 pending
proposals.

`/file`'s empty state prints `Nothing in the outbox.` The outbox held 15 notes,
9 routine logs and a readme. The sentence means *no pending proposals*; what it
says is wider and false, and the wider claim is what sends someone looking for
a bug.

Two neighbours share the shape. `/move`'s `No outbox files are available to
move` drops the *top-level* that `D-1.7-04` exists to teach (already recorded as
`N-06`, which judged the omission harmless — this entry is the reason to revisit
that, since the three strings are being read together, not separately). And
`/list outbox`'s header — *top level, plus the wiki/ and journal/ proposal
folders* — doesn't say those folders are inside the outbox path printed one line
above, which is ambiguous against cfc's own vocabulary, where *the wiki* is the
corpus `/wiki` acts on.

**Leading hypothesis:** all three in one pass, since the defect is that they are
read as a set. `/file` names proposals rather than the outbox; `/move` gets its
adjective back; the header says *inside*. Third time this family has come up
(`D-1.7-04`, `N-06`, this) — worth asking whether the three empty states should
share one function the way `commands.confirm_or_back` closed the three
confirmation prompts.

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
