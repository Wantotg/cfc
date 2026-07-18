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

## Things to remember

- Don't reformat working code you weren't asked to touch.
- Anything that writes to a database must check the path *before* the write.
- `README.md` (human-facing) and `HANDOVER.md` (LLM-facing) are coupled — a
  rewrite of one is a rewrite of the other.
- Log every shipped change in `CHANGELOG.md`, in the same commit as the change
  (hash `pending` for WIP), most recent at the top. Format is at the head of
  that file. `HANDOVER.md` stays invariants, not a log.
