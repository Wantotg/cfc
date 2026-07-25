# CLAUDE.md — example

A sanitised copy of the private `CLAUDE.md` that guides Claude Code in this
repo. The real file is gitignored because it carries personal context, names and
local filepaths. Copy this to `CLAUDE.md` and adapt it.

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

**If you split brainstorming, design and building across separate sessions, say
so** — it changes what a session should do with a half-formed idea. It also
creates one failure worth naming: a brief written at the end of one session, by
a model, tends to promote "they mentioned doing X first" into "X must come
first, they were explicit." Usually they weren't. **Treat a brief's ordering and
scope as proposals** unless the human confirms them in conversation; the fixed
things are the invariants in the technical doc, which say that they are fixed.

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

## Versions and tags (a suggested standard)

If you tag releases, a little discipline keeps the tags trustworthy:

- **Annotated, `vMAJOR.MINOR.PATCH`** (semver). A version that exists only in
  markdown can't be checked out. Minor is a planned feature version, patch is a
  fix or QoL release between features. Avoid two-digit "point releases" like
  `v0.41` — ambiguous against `v0.4.1`, and they stop sorting past 9.
- **Write the version's note into the tracked docs before you tag**, then tag.
  Tag first and the tag points at a commit that doesn't contain its own note, so
  `git checkout vX.Y` shows a roadmap that doesn't mention that version.
- **A pushed tag is immutable.** It is the snapshot of that version, typos and
  all. A mistake found after tagging is fixed in the next ordinary commit, never
  by deleting and recreating the tag — someone may already have the old one.
- Tags don't ride a normal `git push`; `git push --tags` sends them.
- If a roadmap or release note is the human's to write, say so here. A model
  offering the three commands at the end of a version is the right hand-off.

## Things to remember

- Don't reformat working code you weren't asked to touch.
- Anything that writes to a database must check the path *before* the write.
- `README.md` (human-facing) and `HANDOVER.md` (model-facing) are coupled — a
  rewrite of one is a rewrite of the other.
- Log every shipped change in `CHANGELOG.md`, in the same commit as the change,
  most recent at the top. Write the hash as `pending` and backfill it on the
  next commit — don't amend to self-reference, since a commit can't contain its
  own final hash. `HANDOVER.md` stays invariants, not a log.
