# CLAUDE.md — example

A sanitised copy of the instructions that guide Claude Code in this repo. The
real thing is gitignored, because it carries personal context, names and local
filepaths — and because it is no longer one file. It is a set, one per kind of
session, for reasons set out below. This is a single-file composite of it. Copy
it to `CLAUDE.md` and adapt it.

**Keep it short.** The strongest thing this file can do is describe the working
relationship and the handful of rules that live in nobody's code. Everything
about how the project *works* belongs in the technical docs, and a second copy
here goes stale — this file's own inventory of features was out of date within a
day of the commands being renamed. Point at the docs instead; a model can read
them when it needs them.

## Who you're working with

Say what the working relationship actually is, in the terms that change how you
should be spoken to — not a self-assessed skill level.

"Treat them as a peer" is the usual advice and it is a blunt instrument in both
directions: aimed too low it produces condescension, aimed too high it produces
sessions where the human nods along at unexplained jargon instead of deciding.
If the person is the one making the decisions and writing the documentation,
then **the explanation is part of the work**, not a courtesy wrapped around it —
a change they can't explain back is a change they can't maintain.

Worth stating explicitly, whatever the answer:

- How much explanation, and of what: the *why* in plain words, or just the
  mechanism?
- Whether to name an unfamiliar term the first time it appears.
- That pushback is wanted rather than agreement.
- Tone. (Here: concise, dry, no preamble, no false enthusiasm, and never the
  all-lowercase corporate voice.)
- That a guess should be labelled a guess.

## How the work goes

- Iterative. Small blocks, verify, next block. Don't dump 400 lines and hope.
- Git: commit at working states, push at the end of a session, imperative
  messages.
- Ask when genuinely blocked, not to cover yourself.

## One kind of session per file

**The failure this prevents:** a half-formed idea of the human's, restated back
to them by a model, comes back looking like a settled specification — and then
gets built. Nobody decided anything; the writing-up did the deciding.

The defence that worked here is structural rather than a rule about tone. The
instruction file is split into one file per *kind of session*, and a session
reads the one that matches it, in full, before planning anything. What arrives
and what leaves are different for each:

| session | what arrives | what leaves |
|---|---|---|
| brainstorm | a half-formed idea, or nothing | shapes worth considering. **Never a spec** |
| design | a direction already chosen | one decided shape, and how it fails |
| draft | a decided shape | the words — a roadmap entry, a brief |
| build | a spec | code, a commit, a changelog entry |
| debug | a report from someone using it | a diagnosis and a place for every finding |
| manage | a question about the project's own documents | a change to how the project records itself |

Six is this project's answer and not a recommendation. What generalises is that
it is more than one, and that the split lines which earned their place were the
ones where two kinds of session kept wanting different things from the same
file.

**Ask which one you're in rather than inferring it, and ask before starting.** A
brainstorm opens exactly like a build. Guessing is the specific mistake the
split exists to prevent, and "a bit of both" is a real answer — read both.

Three things worth knowing before trying it:

- **A boundary can exist on paper and nowhere else.** Reading these files in
  order to extend them turned up that two of them had never diverged at all:
  identical text under two names. That is not a split, it is one file being read
  twice. Each file has to say what its own session is *for*, or it isn't one.
- **The two hardest boundaries were both a session happening in the wrong
  file.** Brainstorming inside a design file asks "what shape is this" while the
  idea is still an idea, which manufactures the specification the split exists
  to prevent — inside the split. And diagnosing a bug is not the same job as
  deciding where findings should go in general, though they arrive together.
- **Whatever the files share, they share by copy, and nothing checks it.** Five
  sections here are word-for-word identical across all six, under a rule that
  they change in all six or in none. That is a real cost, paid for the property
  that a session reads one file in full — a pointer chain is how instructions
  get skipped. It is not obviously the right trade, and it is unresolved here.
  The paragraph stating that rule had itself miscounted the sections since the
  day it was written, which is the whole argument in one line.

One failure the split creates on its own is worth naming. **A brief written at
the end of one session, by a model, is a proposal and not an order** — including
its ordering, its scope, and its "they were explicit about this". Usually they
weren't; the brief promoted a passing suggestion into a rule. The genuinely
fixed things are the invariants in the technical doc, which say that they are
fixed. If a different order or design is better, say so before starting.

## Environment

- Local single-user setup. `config.py` holds the API key and is gitignored —
  keep it that way (`config.example.py` is the committed template).
- Python: SQLite, httpx, rich. sqlite-vec for vectors.
- If files are exchanged with the model through a folder pair (an inbox it reads
  and an outbox it writes), say where they are, and say which permanent files
  must **not** go there — versioned docs belong in the repo, and a copy in an
  outbox is a copy that goes stale.

## The project

**cfc** ("Cooking for Cats") — a terminal Python AI chat client against an
OpenAI-compatible API (nano-gpt), SQLite backend, `rich` for the REPL,
`prompt_toolkit` for the input editor. Entry point: `python main.py
[session_id]`.

**`HANDOVER.md` is what the code can't tell you** — the settled decisions, the
designs already tried and rejected, the provenance of the tuned constants, and
the bugs that were quiet enough that nothing failed while they were live. On any
point of mechanism, read the code. Read the handover before touching the memory
layer, the tool-calling jail, or the DB schema. `CHANGELOG.md` is the history,
`BACKLOG.md` is what's owed, `README.md` is how a human uses it.

Don't restate their contents here.

## Decide a command taxonomy before you need one

If the app grows a command surface, settle the *verb* each kind of command gets
up front and hold every new command to it. Otherwise the surface accretes
synonyms for one action — `:unpersona`, `:dropfile`, `:forget` — that all have
to be reconciled later, when there are more of them and each is somebody's
muscle memory. The spine this project settled on:

- **`/add`** — attach anything: something the app owns (a prompt, a persona, a
  trait), an external file, a tag. An early draft split internal from external
  across two verbs; the argument's *shape* turned out to carry that distinction
  perfectly well, so they collapsed into one.
- **`/remove`** — the universal detach. Every attachable feature sheds through
  it, and nothing it does is destructive.
- **`/delete`** — destroys durable data, and always requires a kind
  (`/delete chat`). The line between this and `/remove` is not
  memory-versus-the-rest; it is **whether retyping the command gets it back.**
- **`/status`** — what's active now. **`/list <kind>`** — what exists.
  **`/help`** — what can I type. Between them they absorbed fifteen commands.
- **`/connect`**, `/swap`, `/import` — held, unspent. Reserving costs nothing;
  spending a verb does.

**What it bought, measured:** the later cosmetic change — switching the prefix
from `:` to `/` — was one constant in the parser and touched no handler. What it
did *not* cover is worth knowing too: retired verbs still needed a map from old
name to new (an unrecognised command falls through to the model, so without one
`:prompts` gets *sent to it* as a chat message), and prose in comments and help
text still needed a sweep. Budget for both.

**One trap when you do sweep.** A prefix that appears inside a *persisted* format
— a marker written into the database and parsed elsewhere — is not prose.
Renaming it silently stops every existing row from parsing. Storage formats and
command names look identical in a regex and are not the same thing.

## Testing

- `tests/golden.py` pins the REPL's exact stdout for every no-API command. Run
  `check` after touching REPL/dispatch/UI code; `record` re-baselines when an
  output change is intended — inspect the diff first, since it exists to catch
  the changes you *didn't* intend.
- Drive the paths that print and act on nothing: a command with no argument, a
  name that matches nothing, a retired verb. Those are what a rename quietly
  breaks — they still exit cleanly and still print *something*, so nothing fails.
- Unit suites (`test_paths`, `test_gate`, `test_agent`, `test_schema`,
  `test_parse`, …) need no API key.

## Versions and releases (a suggested standard)

If you tag releases, a little discipline keeps the tags trustworthy:

- **Annotated, `vMAJOR.MINOR.PATCH`** (semver). A version that exists only in
  markdown can't be checked out. Minor is a planned feature version, patch is a
  fix or QoL release between features. Avoid two-digit "point releases" like
  `v0.41` — ambiguous against `v0.4.1`, and they stop sorting past 9.
- **A pushed tag is immutable.** It is the snapshot of that version, typos and
  all. A mistake found after tagging is fixed in the next ordinary commit, never
  by deleting and recreating the tag — someone may already have the old one.
- Tags don't ride a normal `git push`; `git push --tags` sends them.

**The order matters more than the format, the testing pass is inside it, and the
tag is always last:**

1. **Build, commit and push** — in the session, by the model.
2. **The human uses the pushed version.** Nothing is tagged yet; the main branch
   carries the version and does not yet claim that it works.
3. **Triage what that pass found**, in its own session. Every finding gets a
   place. Whatever blocks the tag gets fixed, committed and pushed.
4. **The human writes the version's note** into the tracked docs — written from
   use rather than from the plan.
5. **Tag, locally, after the note is in.**

```
git pull
git tag -a v0.9 -m "<one line>"
git push --tags          # tags do NOT ride along on a normal push
```

This project ran its testing pass *after* the tag for its first nine releases,
by default rather than by decision. Three things the current order protects:

- **The note lives in a file in the repo.** Tag first and the tag points at a
  commit that doesn't contain its own note — permanently, because a pushed tag
  must never move. `git checkout vX.Y` then shows a roadmap that doesn't mention
  that version.
- **A tag is a public claim that a version is done.** While the testing came
  after it, "done" meant "written": three of the four releases before the change
  were patch releases named for what a testing pass caught, which had quietly
  made PATCH the mechanism for *this version was never tested*. It should mean
  something found after a version was genuinely finished.
- **The note gets written from use.** One note in this repo reads *"ready to
  playtest to test weird things"*, which is what a note written before use can
  be.

**Decide what blocks a tag in advance, because otherwise you decide it under
pressure to ship.** The test here is *does this version's roadmap entry claim
something the finding falsifies?* — not *did this version cause it*, which is
arguable forever and gets argued by whoever wants to ship. The first question is
answerable by reading the entry, which is finite and was written before the
testing started. Everything else is assigned — a bug list if it's broken, a
backlog if it works and is merely owed, a later version if it's a feature — and
does not block.

Its corollary: **don't grow the entry during the testing pass.** A finding that
makes you want to add a claim is a finding for the *next* version. The entry is
the finish line, and a finish line that can be moved is not one.

**If the release note is the human's to write, say so here.** A model offering
the three commands at the end of a version is the right hand-off; a model
tagging on their behalf is not.

## Things to remember

- Don't reformat working code you weren't asked to touch.
- Anything that writes to a database must check the path *before* the write.
- `README.md` (human-facing) and `HANDOVER.md` (model-facing) are coupled — a
  rewrite of one is a rewrite of the other.
- Log every shipped change in `CHANGELOG.md`, in the same commit as the change,
  most recent at the top. Write the hash as `pending` and backfill it on the
  next commit — don't amend to self-reference, since a commit can't contain its
  own final hash. `HANDOVER.md` stays invariants, not a log.
