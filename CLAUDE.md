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

Next: `:remember` / `:forget` commands in the REPL. Decisions already settled — raw chunk injection, not synthesis; ephemeral, never persisted to corpus; marker row for export archaeology; closing boundary line so injected text isn't read as instruction.

## Things to remember

- Don't reformat working code you weren't asked to touch.
- If a fix is a guess, say it's a guess.