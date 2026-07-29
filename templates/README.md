# templates/

The instruction files cfc actually runs on, with the personal half taken out.
Copy the ones you want, fill in the placeholders, and delete the rest.

They describe **one update going round a loop once.** Each step is its own
session: it reads the file the previous step wrote, does one job, and writes the
next file. A model never plans, builds and reviews the same change in one
sitting.

| step | session | reads | writes |
|---|---|---|---|
| 1 | brainstormer | `Start.md` (yours) | `Idea.md` |
| 2 | designer | `Idea.md` | `Concept.md` |
| 3 | drafter | `Concept.md`, your tracker | `Work Order.md` |
| 4 | coder | `Work Order.md` | `Update.md` |
| 5 | debugger | `Update.md`, your test report | `Tag.md` |
| 6 | manager | `Tag.md` | the repo's own documents |

You hold both ends: you write `Start.md` to open a loop, and after step 5 you
write the release note, tag, and add your reflection notes to `Tag.md`.

## Why bother splitting them

**The failure being prevented is specific.** A vague idea of yours, restated by
a model, comes back looking like a settled specification — and then gets built.
One session that brainstorms and builds will do exactly this, because the same
context that generated the idea is the context that implements it, and nothing
in between ever asked whether it was a good idea.

Splitting costs something and it's worth naming: **the model starts each session
without what the last one knew.** That is the point — the handover is a file you
can read, disagree with, and correct — but it means the files have to be good,
and a step that writes a bad one poisons everything downstream. The tell is the
*next* session: if it has to invent what the previous file should have decided,
that file was too vague; if it has nothing left to decide, that file was a spec.

## Where the shared rules go, and where they don't

The trap this arrangement walks into is duplication. Six instruction files each
want the same section on how you release, what the repo rules are, and how the
documents relate — and six copies drift, silently, because nothing checks them.

Two things that don't work:

- **Six copies with a rule that says keep them in sync.** cfc tried this. The
  copies stayed identical; the *paragraph describing* them went wrong, and every
  session for a week read correct instructions with a wrong count inside them.
- **A shared file the six point at.** A pointer chain is how instructions get
  skipped, which is the failure the split existed to prevent.

What works is putting the shared half in **the document every session already
reads in full** — for cfc that's `HANDOVER.md`, the internal handover — plus a
root instruction file your harness loads automatically. Then a specialist file
holds only what makes that session different from the others, and it's short
enough that people read it.

## A suggested release order

Not part of the loop, but the loop assumes something like it. The property worth
keeping is that **the tag is last and the testing is inside the order, not after
it.**

1. Build, commit and push — in the session, by the model.
2. You test the pushed version. Nothing is tagged; the branch carries the
   version and does not yet claim it works.
3. Triage. Every finding gets a place. Whatever blocks the tag gets fixed.
4. You write the release note, from use rather than from the plan.
5. You pull and tag.

**What blocks a tag: a finding that falsifies a claim the release note makes.**
Not "did this version cause it" — that's arguable forever and gets argued under
pressure to ship. Whether a claim depends on it is answerable by reading the
note, which is finite and was written before testing started.

The reason the tag goes last is that a tag is a public claim that a version is
done. While cfc tagged first, "done" quietly came to mean "written": three of
four consecutive releases were patch releases named for what a testing pass
caught.

## One rule that makes all of it affordable

**One home per fact; everywhere else names an id.** A finding written up in your
bug file, again in a release entry, and again in a session brief has to be
*maintained* in three places, so one change costs three edits and the three
drift. Give every finding an id the first time it's reported, never reallocate
it, and let every other file cite the id instead of restating the body.

Without that, splitting into six sessions just multiplies the paperwork.
