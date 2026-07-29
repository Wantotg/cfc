# DESIGNER.md

**Step 2 of the loop.** Reads `Idea.md`. Writes `Concept.md`. `CLAUDE.md` has
who you're working with; `HANDOVER.md` has how the repo works.

## What this session is for

One decided shape, and how it fails. The direction is already chosen — your job
is to make it specific enough to be *wrong* about.

## What leaves

`Concept.md`, feature-specific:

- **The shape.** What gets built, in terms of what the user sees and what the
  code has to grow.
- **How it fails.** Named failure modes, not a caveat paragraph. This is what
  makes a concept falsifiable, and it is the half that gets skipped.
- **What it costs.** Which modules it touches, which standing decision it leans
  on, and whether it opens a producer/parser pair.
- **What it is not.** The adjacent thing it will be mistaken for.

**Read the code** — not to write it, but to know whether the shape you're
proposing fits the one that exists. `HANDOVER.md`'s **Shape** table is the map;
the standing decisions are constraints you aren't free to break without saying
that you are.

## Three questions worth asking of any shape

- **Does it separate states that are separable?** An unreachable server and an
  empty result are the same silence by the time they reach a console, and one of
  them is a confident lie. They're distinct at the exception and nowhere later.
- **Which direction does its failure point?** Prefer the visible failure. Nearly
  every entry in `HANDOVER.md`'s Scars is a silent false negative — nothing
  raised, something quietly returned "there's nothing here".
- **Does it hold in every mode the product has?** Where a feature can only work
  by breaking one of them — a privacy mode, an offline mode, an unattended run —
  say so and leave that half unbuilt. A feature that silently doesn't hold is
  worse than not having it.

## When this session goes wrong

Progress halts as complexity increases. The tell is your own reaction: were you
looking forward to the build, or to the next brainstorm.

## This session is not

- **Not a work order.** Ordering, the scope of the whole update, and which
  tracker ids ride along belong to `DRAFTER.md`.
- **Not a build.** You read code; you don't write it.
