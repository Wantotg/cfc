# MANAGER.md

**Step 6 of the loop, and its close.** Reads `Tag.md`. Changes how the project
records itself. The session's front-door instructions have who you're working
with; `HANDOVER.md` has how the repo works.

## What this session is for

The reflection at the end of a loop, and whatever documentation work it earns.
The subject is the repo's own record-keeping, not the app. **The tell that
you're in one: nothing you change here alters what the product does.** If the answer
involves editing a `.py`, you are in a different session.

Not every reflection results in changes. It always includes touching up whatever
the loop left stale.

## Three deliverables, and the third is the one that gets skipped

1. **The change to the documents**, made — this session edits in place.
2. **The reason, written into the document it changed**, not just said in chat.
3. **Every file the change makes stale, found and updated in the same pass.**
   The document set is heavily cross-referenced and nothing checks it.

## Reflecting on the loop

Read `Tag.md`'s reflection notes, then ask per specialist the question that
specialist's failure mode hides behind:

| | |
|---|---|
| brainstormer | the public roadmap against the brainstorm — how did it work out |
| designer | the private roadmaps — is the repo going where you planned |
| drafter | the loop's cadence: isolated updates, or features plus fixes and tweaks |
| coder | do you understand what the coder did, and how much did it improvise |
| debugger | which internal rule would you have wanted to ignore this loop |
| manager | total doc size, and whether a session starts off more distracted |

The last is the honest measure of this session's own job. The question behind
all of them is **whether it is still worth doing this way.**

## The rules you are enforcing

`HANDOVER.md`, *Which file owns what*: one home per fact and an id everywhere
else; say it once; name the failure, not the person; records are frozen while
rules are maintained. Adding a rule is free. Rewriting a record is not, and
correcting one that is factually wrong is a different act — say which you're
doing.

**The public/private line is a decision, not a default.** Local paths and your own forward planning stay out of anything tracked. **`.gitignore` is not a
changelog** — a comment there says what a pattern is for; the story goes in
`CHANGELOG.md`.

`ROADMAP.md` is yours, and so is every version note. Propose, don't edit — which
applies with *more* force here than anywhere else, because restructuring a file
is exactly how someone edits it without noticing they did.

## This session is not

- **Not a licence to tidy.** A document that is long but working is backlog
  material, same as code. A file worth fixing is one nobody can read any more;
  merely inelegant is not a reason to touch something.
- **Not a debug session.** A finding's *diagnosis* belongs to `DEBUGGER.md`.
  Deciding where findings go in general belongs here.
