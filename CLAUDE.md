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

Next: **retrieval quality**, not features. 286 embedded chunks are under 20 tokens — including single-token vectors for `yes`, `green`, `7`. Short content-free chunks sit near the centre of embedding space and match every query mediocrely, so they crowd the top-k of *anything*. Observed live: `:remember "what did we decide about chunking"` returned 7 junk hits of 8, all distances within 3% of each other (1.034–1.061) — a flat spread means the ranking isn't ranking. Likely fix: a `token_est` floor in `backfill.py`'s `is_litter`, then re-run the backfill (~1 cent, ~6% of vectors). Not yet diagnosed properly — one query is an anecdote.

This is adjacent to the resolution-staleness problem in the memory design doc, but distinct: staleness is about matching topics over outcomes, this is about content-free chunks matching everything.

Also pending: the `chat.py` split into `db.py` / `api.py` / `export.py` / `commands.py` / `hub.py` / `main.py`. Clean baseline to reset to is `e4ada29`.

## Things to remember

- Don't reformat working code you weren't asked to touch.
- If a fix is a guess, say it's a guess.