# cfc — Cooking for Cats

A terminal-based AI chat client written in Python. It connects to any OpenAI-compatible API (built against [nano-gpt](https://nano-gpt.com)), stores every conversation in a local SQLite database, and exports sessions to an Obsidian vault as Markdown.

The name comes from a book cover. It means nothing, intentionally.

## Features

- **Rich terminal UI** — live Markdown rendering, panels, spinners, styled tables, colour-coded progress bars
- **Streaming responses** rendered as Markdown in real time
- **Local SQLite storage** — every session and message, fully queryable, single portable file
- **Obsidian export** — auto-exports sessions to Markdown with YAML frontmatter
- **Per-session models** — switch models mid-project; each message records what generated it
- **System prompts & personas** — Markdown files injected as system messages, editable in Obsidian
- **Tagging** — many-to-many tags, exported to Obsidian frontmatter
- **Search** — case-insensitive substring search across all messages
- **Token tracking** — live context-usage bar with warnings as the window fills
- **A hub** — start-up page listing recent sessions; `:q` returns here instead of quitting

## Requirements

- Python 3.10+
- [`httpx`](https://www.python-httpx.org/) and [`rich`](https://rich.readthedocs.io/)
- An API key for an OpenAI-compatible provider

## Setup

**1. Clone and enter the project**

```bash
git clone git@github.com:Wantotg/cfc.git
cd cfc
```

**2. Create a virtual environment and install dependencies**

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install httpx rich
```

**3. Create your config**

The repo ships a `config.example.py` with placeholder values. Copy it to `config.py` and fill in your real settings:

```bash
cp config.example.py config.py
```

Then edit `config.py` and set:

- `API_KEY` — your provider's API key
- `API_BASE` — the provider's base URL
- `VAULT_PATH` — folder in your Obsidian vault for exported chats
- `PROMPTS_DIR` / `PERSONAS_DIR` — folders for your system-prompt and persona Markdown files
- `MODELS` / `MODEL_LIMITS` — the models your plan supports and their context sizes

`config.py` is gitignored and will never be committed — it holds your key and stays local.

**4. Run**

```bash
python main.py
```

Optional shell alias for convenience:

```bash
alias cfc='cd ~/projects/cfc && source .venv/bin/activate && python main.py'
```

## Usage

Launch to land on the **hub**, listing your 20 most recent sessions. From there:

| Key | Action |
|-----|--------|
| `n` | New session |
| `s` | Search |
| `l` | List all sessions |
| `t` | Tags |
| number | Open that session |
| `q` | Quit |

`python main.py 5` opens session 5 directly, skipping the hub.

### In-session commands

| Command | Action |
|---------|--------|
| `:q` | Return to hub (auto-exports if enabled) |
| `:new` | Start a new session in place |
| `:model <name>` | Switch the current session's model |
| `:models` | List configured models |
| `:persona <name>` | Load a persona from `PERSONAS_DIR` |
| `:persona off` | Remove the persona |
| `:tag <name>` | Add a tag (auto-lowercased) |
| `:untag <name>` | Remove a tag |
| `:tags` / `:taglist` | Show tags / all tags with counts |
| `:grep <keyword>` | Substring search across all messages |
| `:recall <question>` | Ask your history a question; cited answer, no session effect |
| `:remember <query>` | Pull matching excerpts into the live context (ephemeral) |
| `:forget` | Drop the most recently injected excerpts |
| `:tokens` | Detailed context-usage breakdown |
| `:export` | Manually export the session to Obsidian |
| `:config` | Show current configuration (key masked) |
| `:title <n> <name>` | Rename a session |

**Multi-line input:** type `"""` to open, `"""` again to send, `:cancel` to abort. `Ctrl+C` during streaming cancels the request.

## How it works

The flow:

```
main.py → pick_session() → repl() → ... → quit
```

- **SQLite** (`~/.cfc/chat.db`) holds sessions, messages, tags, and a session↔tag junction table. Schema and migrations run automatically on start — safe to re-run on an existing database.
- **API layer** streams from an OpenAI-compatible `/chat/completions` endpoint, prepending persona and system prompt as system messages.
- **Rich** drives the terminal UI with `markup=False` (so `[...]` in strings isn't treated as formatting).
- **Export** writes one Markdown file per session, overwriting on re-export — version history lives in the database, not in duplicate files.

## Roadmap

- **Phase 2.5** — bulk export (`:export all`), hub tag filtering, global `:stats`
- **Phase 3** — browser UI (FastAPI/Flask) over the same database and export logic
- **Phase 4** — lightweight RAG: embed past messages, retrieve relevant history as context

## Known limitations

- Streaming token counts depend on the provider supporting `stream_options: {"include_usage": true}`. Without it, the post-response bar is skipped, but `:tokens` still works from stored data.
- Search is substring (`LIKE`), not full-text. Fine at current scale; FTS5 is a possible upgrade.
- Sessions are linear — no branching.
- Single user, local machine.

## Project structure

| File | Holds |
|---|---|
| `main.py` | the REPL: dispatch, and the live session state |
| `commands.py` | what each `:` command does |
| `hub.py` | the session browser and picker |
| `db.py` | connection, schema, every query |
| `api.py` | streaming and non-streaming calls to the endpoint |
| `export.py` | writing a session out to the vault |
| `ui.py` | the shared console and presentation helpers |
| `backup.py` | rolling snapshots of the database |
| `config.py` | settings — gitignored |

The memory layer is separate again: `import_anthropic.py`, `chunk.py`, `embed.py`, `backfill.py`, `search.py`, `recall.py`.

`tests/golden.py` pins the REPL's output for every command that makes no API call. Run `python tests/golden.py check` after touching any of the above; `record` re-baselines it once a change to the output is intended.

## Backups

cfc snapshots the database to `~/.cfc/backups/` on startup — at most once every 6 hours, skipped entirely when nothing has changed, keeping the newest 10.

```
python backup.py                  # snapshot now (skips if unchanged)
python backup.py --force          # snapshot regardless
python backup.py --list           # show what's kept
python backup.py --restore latest # roll back to the newest snapshot
```

Snapshots use SQLite's online backup API rather than a file copy, so they're safe to take while the database is in use, and each is integrity-checked before it's kept. A restore backs up the current database first — restoring the wrong one is recoverable.

## License

Personal project. No license specified.
