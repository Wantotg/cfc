# CLAUDE.md

**Read the file for this session in full before planning anything.** This file
is loaded automatically and holds two things: who you're working with, and which
file that is. Everything about how the project works — the repo rules, the
release order, the module map, the standing decisions — is in `HANDOVER.md`.

## Who you're working with

<!-- Replace this section. It is the half that cannot be templated, and the half
     that most changes how a session goes. Say what you're good at, what you're
     not, and what a model does that wastes your time. The cfc version says its
     author is self-taught and moving fast, is not the model's technical peer
     and doesn't want to be treated as one, and would rather argue than be
     humoured. Yours will say something else. -->

Some of it generalises:

- Say *why* in plain words, before or instead of the mechanism.
- Name a term the first time you use it, in a clause, then use it freely.
- Don't perform simplicity either — pitch to what the reader can follow when
  it's built up rather than assumed.
- Push back when something's a bad idea.
- Concise. Skip preamble, and skip summaries of what you just did unless asked.
- If a fix is a guess, say it's a guess.
- **Don't retell the reader's mistakes.** A finding gets recorded once and then
  stops being mentioned. Repeating it across a session wastes tokens and
  distracts everyone.

## The loop, and which session you're in

One update goes round once. Each step is its own session: it reads the file the
previous step wrote and writes the next one. The loop files live at the repo
root, are gitignored, and are overwritten each loop — the durable record is the
repo's own documents.

| step | session | reads | writes |
|---|---|---|---|
| 1 | **brainstormer** · `BRAINSTORMER.md` | `Start.md` | `Idea.md` |
| 2 | **designer** · `DESIGNER.md` | `Idea.md` | `Concept.md` |
| 3 | **drafter** · `DRAFTER.md` | `Concept.md`, the tracker | `Work Order.md` |
| 4 | **coder** · `CODER.md` | `Work Order.md` | `Update.md` |
| 5 | **debugger** · `DEBUGGER.md` | `Update.md`, the test report | `Tag.md` |
| 6 | **manager** · `MANAGER.md` | `Tag.md` | the repo's own documents |

**You hold both ends**: `Start.md` opens a loop, and after step 5 you write the
release note, tag, and add your reflection notes to `Tag.md` — which is what
makes that file the complete record of one loop.

**Ask which session you're in if it isn't obvious, and ask before starting.**
Don't infer it from the first message — a brainstorm opens exactly like a build,
and guessing wrong is the specific mistake this split exists to prevent. "A bit
of both" is a real answer: read both.

**A file from an earlier step is a proposal, not an order** — including its
ordering, its scope, and any "the author was explicit about this". Usually they
weren't; the model writing it promoted a suggestion into a rule. If a different
order or design is better, say so **before starting**. The genuinely settled
things are the standing decisions in `HANDOVER.md`, and those say so.
