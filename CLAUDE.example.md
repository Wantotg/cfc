# CLAUDE.md — example

This is a sanitised copy of the private `CLAUDE.md` that guides Claude Code in
this repo. The real file is gitignored because it carries personal context,
names, and local filepaths. Copy this to `CLAUDE.md` and adapt it — the private
version is where you put anything you wouldn't publish.

## Who you're working with

One developer, working solo on a personal project. Talk to them as a peer:
direct, concise, no false enthusiasm, no hand-holding. Push back when something
is a bad idea rather than humouring it.

## Communication

- Concise. Skip preamble, skip summaries of what you just did unless asked.
- Explain *why* when the reasoning isn't obvious, not *what* when the code says it.
- If a fix is a guess, say it's a guess.

## How the work goes

- Iterative. Small blocks, verify, next block. Don't dump 400 lines and hope.
- Git: commit at working states, push at end of session, imperative messages.
- Ask when genuinely blocked, not to cover yourself.

## Environment

- Local single-user setup. `config.py` holds the API key and is gitignored —
  keep it that way (`config.example.py` is the committed template).
- Python: SQLite, httpx, rich. sqlite-vec for vectors.

## The project

**cfc** ("Cooking for Cats") — a terminal Python AI chat client against an
OpenAI-compatible API (nano-gpt), SQLite backend, `rich` for the REPL,
`prompt_toolkit` for the input editor.

Entry point: `python main.py [session_id]`. The codebase is split by concern —
`main.py` (REPL + dispatch + session state), `commands.py`, `hub.py`, `db.py`,
`api.py`, `agent.py`, `tools.py`, `paths.py`, `export.py`, `backup.py`,
`ui.py` (shared console + input), `config.py` (gitignored).

A RAG memory layer sits over an imported chat history: chunked, embedded via
`bge-m3` into `sqlite-vec`, surfaced through `:recall`, `:remember`, `:grep`.

**`HANDOVER.md` is the technical doc** — read it before touching the memory
layer, the tool-calling jail, or the DB schema. It records the invariants and
the reasons behind non-obvious choices. `BACKLOG.md` holds smaller parked
findings.

## Testing

- `tests/golden.py` pins the REPL's exact stdout for every no-API command.
  Run `check` after touching REPL/dispatch/UI code; `record` re-baselines when
  an output change is intended (inspect the diff first).
- Unit suites (`test_paths`, `test_gate`, `test_agent`, `test_schema`,
  `test_litter`, …) need no API key.

## Versions and tags (a suggested standard)

If you tag releases, a small amount of discipline keeps the tags trustworthy:

- **Tags are annotated and named `vX.Y`.** A version that only exists in
  markdown can't be checked out.
- **Write the version's note into the tracked docs (e.g. `ROADMAP.md`) *before*
  you tag**, then tag. Tag first and the tag points at a commit that doesn't
  contain its own note — `git checkout vX.Y` then shows a roadmap that doesn't
  mention that version.
- **A pushed tag is immutable.** It's the snapshot of that version, typos and
  all. A mistake found *after* tagging is fixed in the next ordinary commit —
  never by deleting and recreating the tag. `git checkout vX.Y` is supposed to
  show exactly what shipped; moving the tag to tidy it breaks that, and someone
  may already have the old one.
- Tags don't ride a normal `git push` — `git push --tags` sends them.

## Things to remember

- Don't reformat working code you weren't asked to touch.
- Anything that writes to a database must check the path *before* the write.
- `README.md` (human-facing) and `HANDOVER.md` (LLM-facing) are coupled — a
  rewrite of one is a rewrite of the other.
- Log every shipped change in `CHANGELOG.md`, in the same commit as the change,
  most recent at the top. Write the hash as `pending` and backfill it on the
  next commit — don't amend to self-reference. `HANDOVER.md` stays invariants,
  not a log.
