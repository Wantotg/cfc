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
- **Semantic memory** — ask past conversations a question and get a cited answer, or pull the raw excerpts into the live context
- **File attachments** — inject a local text file into a session; it persists and comes back on reopen
- **Local file tools** — let the model request `list_dir` / `read_file` / `grep` itself, read-only, behind an approval gate
- **Token tracking** — live context-usage bar with warnings as the window fills
- **Rolling backups** — the database is snapshotted on startup, automatically

## Requirements

- Python 3.10+
- [`httpx`](https://www.python-httpx.org/) and [`rich`](https://rich.readthedocs.io/)
- [`sqlite-vec`](https://github.com/asg017/sqlite-vec) for the memory layer
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
pip install httpx rich sqlite-vec
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

`config.py` is gitignored and will never be committed — it holds your key and stays local. It's also on the deny list in `paths.py`, so `:attach` and the file tools refuse to read it even though it sits inside the project.

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
| number | Open that session |
| `n` | New session |
| `q` | Quit |

The hub is home base: `:q` inside a session brings you back here rather than
quitting, so the program only exits from the hub (`q`, or Ctrl-D/Ctrl-C).

`python main.py 5` opens session 5 directly, skipping the hub — but its `:q`
still returns to the hub.

### In-session commands

| Command | Action |
|---------|--------|
| `:q` | Back to the hub (auto-exports if enabled) |
| `:new` | Start a new session in place |
| `:model <name>` | Switch the current session's model |
| `:models` | List configured models |
| `:persona <name>` | Load a persona from `PERSONAS_DIR` |
| `:persona off` | Remove the persona |
| `:prompt <name>` | Load a system prompt from `PROMPTS_DIR` |
| `:prompt off` | Remove the system prompt |
| `:tag <name>` | Add a tag (auto-lowercased) |
| `:untag <name>` | Remove a tag |
| `:tags` / `:taglist` | Show tags / all tags with counts |
| `:grep <keyword>` | Substring search across all messages |
| `:recall <question>` | Ask your history a question; cited answer, no session effect |
| `:remember <query>` | Pull matching excerpts into the live context (ephemeral) |
| `:forget` | Drop the most recently injected excerpts |
| `:attach <path>` | Attach a local text file to the session (persistent) |
| `:attached` | List attachments in this session |
| `:detach <n>` | Remove an attachment by its `:attached` index |
| `:tools` | Show whether tools are active, and why |
| `:tools on` / `:tools off` | Toggle tools for this session |
| `:tokens` | Detailed context-usage breakdown |
| `:export` | Manually export the session to Obsidian |
| `:config` | Show current configuration (key masked) |
| `:title <n> <name>` | Rename a session |

**Multi-line input:** type `"""` to open, `"""` again to send, `:cancel` to abort. `Ctrl+C` during streaming cancels the request.

`:attach` completes paths on Tab, scoped to `ATTACH_ROOTS`. Completion stays
quiet until you've typed a few characters of a name rather than dumping a whole
directory.

## How it works

The flow:

```
main.py → repl() ┬→ pick_session() → run_session() ─┐
                 └───────────← :q ←─────────────────┘
                   q at the hub → quit
```

- **SQLite** (`~/.cfc/chat.db`) holds sessions, messages, tags, and a session↔tag junction table. Schema and migrations run automatically on start — safe to re-run on an existing database.
- **API layer** streams from an OpenAI-compatible `/chat/completions` endpoint, prepending persona and system prompt as system messages.
- **Rich** drives the terminal UI with `markup=False` (so `[...]` in strings isn't treated as formatting).
- **Export** writes one Markdown file per session, overwriting on re-export — version history lives in the database, not in duplicate files.
- **Message kinds** — every row is tagged `chat`, `attachment`, `recall_marker`, `tool_call` or `tool_result`, with a JSON `meta` blob whose shape follows the kind. That's what lets an attachment export as a one-line reference instead of dumping the whole file, and lets a tool exchange replay in the right order.

## Memory

Past conversations — including an imported Anthropic export — are chunked (500 tokens, 75 overlap, never crossing a message boundary), embedded with `BAAI/bge-m3`, and stored in `sqlite-vec`.

```
python import_anthropic.py <export.json> ~/.cfc/chat.db   # import
python chunk.py ~/.cfc/chat.db                            # chunk
python backfill.py ~/.cfc/chat.db                         # embed
python backfill.py ~/.cfc/chat.db --prune                 # drop litter vectors
```

`:recall` synthesises a cited answer and leaves the session untouched. `:remember` injects the raw excerpts into the live context and is ephemeral — only a marker row persists, so an export can still tell a grounded claim from an invented one. `:forget` drops the last injection.

Retrieval has a relevance floor: if nothing is within `MAX_DISTANCE` of the question, memory says it has no answer rather than returning eight mediocre excerpts. The threshold was measured against this corpus (answerable questions land at 0.53–0.89, questions it has never discussed at 0.97–1.09) and is specific to `bge-m3` — re-measure if the embedding model changes.

## Security

Read this before enabling write tools.

- **Everything is jailed.** `ATTACH_ROOTS` and `TOOLS_ROOTS` bound every file operation — a path passes if it resolves inside *any* configured root. Paths are **resolved before** they're checked, which is what defeats `../` traversal and symlink escape — a symlink named `notes.md` pointing at `~/.ssh/id_rsa` is judged as what it resolves to, not what it's called.
- **Some files are refused inside the jail.** A root like `~/projects` contains cfc, which contains `config.py`, which holds your API key — and `.py` is an attachable type. Containment alone is not enough. The deny list is root-agnostic: it runs on the resolved path no matter which root allowed it, so adding a root never un-denies anything. `paths.py` refuses `config.py`, `.env*`, `*.pem`, `*.key`, `id_rsa`, `.ssh/`, and friends. `config.py` may **add** to that list via `ATTACH_DENY_EXTRA`; nothing removes from it.
- **The approval gate.** Every tool call is shown — resolved path, real file size — and confirmed before dispatch. `TOOLS_AUTO_APPROVE` is empty by default, so nothing runs unasked.
- **Approval does not bypass validation.** `path_guard` runs inside the dispatcher regardless of what was approved. You can approve a call that then fails the guard; that's correct. The gate is where *you* decide. The guard is what holds when you've stopped reading the gate carefully — which is what a gate that fires on every call eventually becomes.
- **`TOOLS_ENABLED = False` by default.** Opt-in, not opt-out.
- **Read-only by design.** `list_dir`, `read_file`, `grep`, and nothing else. No writes, no shell.
- **Denial is data.** A denied, skipped or refused call returns `{"error": ...}` to the model as a tool result. It reads it and adapts; it doesn't crash the turn. Asked to fetch `API_KEY` with every tool auto-approved, the model gets `config.py is on the deny list` and moves on — the key never reaches it.

The tests that back this up are worth keeping green: `tests/test_paths.py` covers traversal, symlink escape, and the deny list; `tests/test_gate.py` asserts that approving a call still doesn't bypass the guard.

## Roadmap

- **Phase 2.5** — bulk export (`:export all`), hub tag filtering, global `:stats`
- **Write tools** — the gate exists so that adding them later is small. Not now.

## Known limitations

- **Recall staleness** — semantic search matches on topic, so a question about a decision tends to surface the messages where you were *struggling* with it rather than the one where you settled it. The struggle is longer and uses the topic's vocabulary more.
- **Streaming is off when tools are active** — tool-call deltas arrive fragmented and the `arguments` string has to be reassembled across chunks by index. Not worth it; these responses are fast. The normal chat path still streams.
- **Tool calling needs a model in `TOOLS_MODELS`** — not every provider's models handle it. The list was verified against nano-gpt rather than assumed; `:tools` tells you whether the active model qualifies.
- Streaming token counts depend on the provider supporting `stream_options: {"include_usage": true}`. Without it, the post-response bar is skipped, but `:tokens` still works from stored data.
- Search is substring (`LIKE`), not full-text. Fine at current scale; FTS5 is a possible upgrade.
- Sessions are linear — no branching.
- Single user, local machine.

Known rough edges live in `BACKLOG.md`.

## Project structure

| File | Holds |
|---|---|
| `main.py` | the REPL: dispatch, and the live session state |
| `commands.py` | what each `:` command does, and the approval gate |
| `agent.py` | the tool-calling turn |
| `tools.py` | the read-only tools and the dispatcher |
| `paths.py` | the jail: containment and the deny list |
| `complete.py` | Tab completion for `:attach` |
| `hub.py` | the session browser and picker |
| `db.py` | connection, schema, every query |
| `api.py` | streaming and non-streaming calls to the endpoint |
| `export.py` | writing a session out to the vault |
| `backup.py` | rolling snapshots of the database |
| `ui.py` | the shared console and presentation helpers |
| `config.py` | settings — gitignored |

The memory layer is separate: `import_anthropic.py`, `chunk.py`, `embed.py`, `backfill.py`, `search.py`, `recall.py`.

## Tests

```bash
python tests/golden.py check     # the REPL's exact output, for every no-API command
python tests/test_paths.py       # the jail
python tests/test_tools.py       # tools and dispatcher
python tests/test_gate.py        # the approval gate
python tests/test_agent.py       # the agent loop and tool replay
python tests/test_attach.py      # :attach / :attached / :detach
python tests/test_schema.py      # the kind/meta migration
python tests/test_litter.py      # the litter filter's marker coupling
```

None of them need an API key. `golden.py record` re-baselines the output once a change to it is intended — check the diff first; it's there to catch the changes you *didn't* intend.

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
