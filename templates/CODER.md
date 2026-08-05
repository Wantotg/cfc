# CODER.md

**Step 4 of the loop.** Reads `Work Order.md`. Writes the code, and `Update.md`.
The session's front-door instructions have who you're working with;
`HANDOVER.md` has how the repo works.

## What this session is for

Implementing the order and proving it proportionately. **The order's scope is
the scope.** Something outside it that turns up goes to `development/BACKLOG.md` or
`development/BUGS.md` with an id — not into this commit.

## What leaves

- The code, committed and pushed, with its `development/CHANGELOG.md` entry **in the same
  commit** (hash `pending`, backfilled on the next one).
- `Update.md`, a technical handover for the debugger: what changed, which claims
  are now testable, what you could not verify yourself, and anything you did
  differently from the order **with the reason**.

## Before you write

- `HANDOVER.md`'s **standing decisions** are constraints. Breaking one takes an
  argument, said out loud.
- **Check the producer/parser table before adding a pair** — and check the
  import graph first, because a pair that *can* be closed by an import should be
  closed rather than pinned.
- Read `development/BACKLOG.md` before touching the memory layer.
- A feature is specified for every mode the product has, and a mode with a
  guarantee to keep owes a test that the guarantee still holds.

## Proof

Match what the order called for. Three habits, all learned here: **verify a
guard by disabling it** and watching the assertions fail; **patch the seam, not
`config`**, since patching config misses whatever read the value at import; and
**compare two implementations to each other rather than to a literal** where
there are two.

Don't reformat working code you weren't asked to touch.

## When this session goes wrong

The repo gets stuck in bug fixing. The lever for that is upstream — the
constraints the designer and drafter set — so an underspecified order is worth
saying in `Update.md` rather than absorbing silently.

## This session is not

- **Not a design session.** A better idea arriving mid-build is a note in
  `Update.md`, not a change of direction.
- **Not the tagger.** You commit and push in-session. You never tag.
