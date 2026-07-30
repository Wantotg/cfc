# REVIEWER.md

**Not part of the loop.** Run on its own cadence, whenever you decide
`HANDOVER.md` needs checking rather than at a fixed step in the loop. Reads
`HANDOVER.md`, the code, and every other doc in the set. Writes `HANDOVER.md`,
in place. `CLAUDE.md` has who you're working with.

## What this session is for

`HANDOVER.md` is the one fact the rest of the loop trusts without checking —
every specialist reads it once at the top of its session and takes it as true.
Nothing downstream re-verifies it against the repo it describes, which is
exactly the condition that produces the recurring hazard `HANDOVER.md` itself
names: something written in one place goes stale, and nothing notices because
nothing looks. This session is the thing that looks.

Two deliverables, and neither is optional:

1. **The audit.** Read `HANDOVER.md` end to end against the code and against
   every other doc, and find:
   - **Missing** — a standing decision, constant, or scar that the code or
     another doc clearly reflects and `HANDOVER.md` doesn't.
   - **Contradicting** — a claim the code has moved past. `HANDOVER.md`'s own
     rule is that the code wins when they disagree; find where that needs
     invoking, and say so rather than quietly working around it.
   - **Duplicated** — the same fact recorded twice, inside `HANDOVER.md` or
     spilled into another doc. One fact, one home is the rule this file states
     for everyone else, so it's the one worth checking here.
   - **Doesn't belong** — content that's drifted into `BUGS.md`, `BACKLOG.md`,
     or `CHANGELOG.md` territory per the ownership table this file itself
     keeps.

2. **The structural call.** Compress in place, split into more than one file,
   or leave it as it is — decided here, not deferred to "someday." Say which
   and do it in the same session; a verdict nobody acts on is a paragraph
   nobody reads twice.

## Why not the manager session

`MANAGER.md` already patrols staleness across the whole document set, and its
own stated boundary is "not a licence to tidy" — a document that's long but
working is left alone there, on purpose, and its whole frame is one loop's
`Tag.md` against the docs that loop touched. `HANDOVER.md`'s rot is cumulative
across many loops and rarely visible in any single one; catching it means
reading the whole file against the whole repo, which is a different-shaped job
than reflecting on what one loop taught. Folding it into `MANAGER.md` would
mean either skipping it most loops — which is what happens to any unscheduled
work — or growing that session past the size it's built for.

## The one rule that overrides "read the whole thing"

`HANDOVER.md`'s own distinction holds with full force here: **records are
frozen, rules are maintained.** A rejected design, a scar, a constant's
provenance — these record what was true when they were written, and restyling
them to a convention invented this session is exactly the harm that rule names.
Compress or split the *structure*; don't rewrite prose that's carrying a
specific, dated finding. If an entry is factually wrong rather than merely
long or awkwardly placed, say which of the two you're doing — same as anywhere
else in this file.

## When this session goes wrong

It turns into an open-ended rewrite: reformatting settled entries, inventing
tidier phrasing for a scar that was fine, or "improving" a rejected design's
argument instead of checking whether the design still loses. The tell is the
diff — if it touches more lines than the findings justify, it went past
auditing into tidying, and tidying an already-working file is what this
session exists to *not* do casually.

## This session is not

- **Not `MANAGER.md`.** No `Tag.md`, no per-loop cadence, no reflection on the
  other five specialists. It has one subject and one file it's allowed to
  restructure.
- **Not a design or debug session.** A genuine contradiction between
  `HANDOVER.md` and the code is a finding about the *record*, not licence to
  change the code or revisit the decision. The code stays right; the text
  catches up.
- **Not free to split silently.** `HANDOVER.md` is cross-referenced by every
  specialist file and by `CLAUDE.md` itself. A split that moves a section to a
  new file means grepping the set for anyone pointing at the old one and fixing
  every reference in the same pass — the same discipline `MANAGER.md` names for
  its own edits.
