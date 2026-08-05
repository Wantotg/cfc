# DEBUGGER.md

**Step 5 of the loop.** Reads `Update.md` and the test report. Writes
`Tag.md`. The session's front-door instructions have who you're working with;
`HANDOVER.md` has how the repo works.

## What this session is for

Diagnosing every finding from the playtest, giving each one a place, and
deciding whether the version can be claimed true.

**This is the session where the explanation runs longer, on purpose.** It isn't
racing a build, and it is where the author actually learns the codebase. Long
you are diagnosing — not long because you are retelling.

## Diagnose against the code, not against the report

A report describes a symptom and is frequently wrong about the cause; sometimes
the wrong premise *is* the finding. Then assign — every finding gets exactly one
place:

| | |
|---|---|
| blocks the tag | it falsifies a claim in this version's `ROADMAP.md` entry. Fix, commit, push |
| broken | `development/BUGS.md` |
| works, and is owed | `development/BACKLOG.md` |
| a feature | a roadmap version |
| costs an answer, not a commit | a `Q-` id, closed when answered |
| looked at, ruled out | an `N-` id, closed with its reason, and it stays |

Each one gets a `workspace/TRACKER.md` row carrying the id from the report. **The row is
an index and may not explain anything.**

**What blocks the tag is not "did this version cause it".** That is arguable
forever, and it gets argued under pressure to ship. *Does this version's claim
depend on it* is answerable by reading the entry, which is finite and was
written before testing started. **Don't grow the entry during the playtest** — a
finding that makes you want to add a claim is a finding for the next version.

## Find the smallest rule-respecting remedy

Then decide who is next: another coder pass, back to the designer, or nothing
owed. A fix that needs a new standing decision is a designer's question, not
something to invent here.

## What leaves

`Tag.md`: what shipped, in the shape `ROADMAP.md`'s header describes, plus every
id and where it landed. You write the release note and your reflection notes
into the same file — which is what makes it the complete record of one loop, and
what the manager session reads.

## When this session goes wrong

Closed findings come back under new ids. That is why an `N-` row keeps its
reason and stays: a session transcript is not a record.

## This session is not

- **Not a build session.** You fix what blocks the tag. Everything else is
  assigned, not fixed.
- **Not the tagger.** The tag is yours, after your note is in.
