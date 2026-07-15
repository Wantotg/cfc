# CLAUDE.md

## Who you're working with

Cas. Not a professional developer — self-taught, learns by building. "Jump and see if you float."

Talk to him as a peer. Direct, no hand-holding, no false enthusiasm. He has a dry wit and will meet yours.

## Communication

- Concise. Skip preamble, skip summaries of what you just did unless asked.
- English primary. French for emphasis or a joke — sparingly, naturally.
- Explain *why* when the reasoning isn't obvious, not *what* when the code says it.
- Push back when something's a bad idea. He'd rather argue than be humoured.
- No all-lowercase corporate voice. Ever.

## How he works

- Iterative. Small blocks, verify, next block. Don't dump 400 lines and hope.
- Git: commit at working states, push at end of session, imperative messages.
- Ambiguity is fine — he'll steer. Ask when genuinely blocked, not to cover yourself.

## Environment

- WSL2 / Ubuntu on Windows. Projects live in `~/projects/`.
- Some project files (Obsidian markdown, notes) live on the Windows side.
- Obsidian is the text environment for everything not code.
- Python: SQLite, httpx, rich are familiar territory. sqlite-vec for vectors.
- `config.py` is gitignored. Keep it that way.

## Current project

**cfc** ("Cooking for Cats") — terminal Python AI chat client, nano-gpt OpenAI-compatible API, SQLite backend, `rich` for the REPL. Private repo `Wantotg/cfc`.

RAG memory layer in progress: Anthropic exports imported → chunked (500 tokens, 75 overlap, never crossing message boundaries) → embedded via `BAAI/bge-m3` into `sqlite-vec`. Modules: `import_anthropic.py`, `chunk.py`, `backfill.py`, `embed.py`, `search.py`, `recall.py`.

REPL commands are wired and working: `:recall` (cited synthesis, no session effect), `:remember` (raw chunk injection, ephemeral, marker row persisted), `:forget` (drops the last injected block). The old `:search` is now `:grep`.

Retrieval quality: **done**, and the original diagnosis was wrong. Recorded because the wrong version is intuitive and will otherwise get re-derived:

- The junk in top-k wasn't crowding by content-free chunks. `:remember "what did we decide about chunking"` scored 1.034 — statistically identical to a control query about the mating habits of the Patagonian toothfish. The corpus is the *Anthropic export*; cfc's own chunking decisions were made in Claude Code and were never in it. Retrieval was working. There was simply nothing to find, and KNN returns k rows regardless.
- Real fix: `MAX_DISTANCE = 0.93` in `search.py`. Measured over 36 probes — answerable 0.531–0.892, unanswerable 0.973–1.094, total separation. bge-m3 specific.
- Flat spread is a *symptom* of an unanswerable query, not a cause, and is a poor discriminator: a good query scored 1.4% spread. Don't build on it.
- The litter floor shipped too (`is_litter` also had a real bug — it matched a single marker against the whole chunk, so concatenated markers were embedded). Worth having, but it moved junk-in-top-8 only 28.9% → 24.4%. Floor is 5 tokens, not 20: the 7–20 band is real material.

Retrieval is good when the answer exists: 24/24 probes returned the right session in top-8, 18/24 at rank 1.

Still open, and distinct from the above: **resolution staleness** (semantic search matches struggle messages over the resolution) per the memory design doc.

Smaller findings park in `BACKLOG.md` — read it before touching the memory layer.

The `chat.py` split is **done**. `main.py` (REPL + dispatch + session state), `commands.py`, `hub.py`, `db.py`, `api.py`, `export.py`, `ui.py` (shared console), `config.py`. Entry point is now `python main.py [session_id]`.

`tests/golden.py` pins the REPL's exact output for every command that makes no API call — it's what made the split safe. Run `check` after touching any of those modules; `record` re-baselines when a change to the output is intended. It doesn't cover the chat turn, `:recall`/`:remember`, `:export` or the picker; those were verified by hand.

Next: the attach/tools handoff (`cfc-attach-tools-handoff.md`). Note its Step 7 README rewrite is partly done already — structure and entry point are current, the roadmap and Security section aren't.

## Things to remember

- Don't reformat working code you weren't asked to touch.
- If a fix is a guess, say it's a guess.