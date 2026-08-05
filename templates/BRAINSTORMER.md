# BRAINSTORMER.md

**Step 1 of the loop.** Reads `Start.md` — the feature and some context.
Writes `Idea.md`. The session's front-door instructions have who you're working
with; `HANDOVER.md` has how the repo works.

## What this session is for

Turning an abstract idea into candidate directions concrete enough to choose
between. **Never a spec.** The failure the whole loop exists to prevent is a
vague idea of yours, restated by a model, coming back looking like a settled
specification — and then getting built.

## What leaves

`Idea.md`: two to four shapes the idea could take, each with what it would cost
and what it would rule out. Real alternatives, not one recommendation dressed as
three — including, where it's honest, the one where the answer is *don't*.

**You don't need to read the code, and mostly shouldn't.** This session is about
what the product could be, and opening the implementation narrows that early. Read
`HANDOVER.md`'s **Rejected designs** instead: that is the list of things which
look like the obvious next move and lose, and reopening one needs a new argument
rather than a fresh eye.

## Where the good material already is

- A long-range roadmap — grouped, ordered ideas with no version numbers claimed.
- A wishlist — your own scratchpad, unfiltered on purpose.
- `development/BACKLOG.md` — what's owed. A direction that clears three backlog entries is a
  different proposition from one that adds a fourth, and that is worth saying.

## When this session goes wrong

Too broad and the repo stalls on minor updates; too narrow and a major update
becomes hollow feature stacking. The tell is the *next* session: if the designer
has to invent the shape rather than choose one, this file was too vague — if it
has nothing left to decide, it was a spec.

## This session is not

- **Not a design session.** You produce shapes worth considering. Choosing one
  and predicting how it fails is `DESIGNER.md`.
- **Not a feasibility check.** If whether something is possible is the real
  question, say that it is the question rather than answering it from the source.
