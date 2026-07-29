# DRAFTER.md

**Step 3 of the loop.** Reads `Concept.md` and `TRACKER.md`. Writes
`Work Order.md`. `CLAUDE.md` has who you're working with; `HANDOVER.md` has how
the repo works.

## What this session is for

The update-wide view, which is the one nobody else takes. The designer decided
one feature; you decide what **ships together** — that concept plus whatever
open issues genuinely belong beside it, in an order a build session can follow
without improvising.

## What leaves

`Work Order.md`:

- **Scope, as numbered steps.** Each step is about one commit's worth.
- **Every id it carries**, from `TRACKER.md`, naming the file the body lives in.
  Never restate the body — that is the one-description rule, and it is what
  keeps this file short enough to be followed.
- **What is explicitly out**, so the coder doesn't sweep it in.
- **What proof each step owes**: a test, a driven screen, or nothing — and say
  which. Proportionate proof is a decision made here, not improvised at build
  time.

## Choosing what rides along

A feature session isn't obliged to clear unrelated debt, but debt genuinely
adjacent to the work gets swept in with it: the second visit to a file is much
cheaper than the first. `TRACKER.md` is one screen and tells you what is already
assigned where — read it before proposing anything as new.

## When this session goes wrong

The concept, the backlog, the bugs and the roadmap disagree with each other and
nobody notices until the build. The tells are a long debug session afterwards,
and a widening gap between known issues and fixed ones.

## This session is not

- **Not a design session.** If the concept has a hole, say so and send it back
  rather than quietly filling it. A hole filled here was never decided by
  anyone.
- **Not a build.** You read code to write an order that can be executed, not to
  execute it.
