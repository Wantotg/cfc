# cfc — Cooking for Cats

A terminal-based AI chat client written in Python. It connects to any OpenAI-compatible API (built against [nano-gpt](https://nano-gpt.com)), stores every conversation in a local SQLite database, and exports sessions to an Obsidian vault as Markdown.

The name comes from a book cover. It means nothing, intentionally.

For the internals — architecture, data model, invariants, and the reasoning behind the non-obvious choices — see [`HANDOVER.md`](HANDOVER.md).

## Features

- **Rich terminal UI** — a mascot splash at launch, live Markdown rendering, colour-coded speaker panels (you, AI reasoning, AI answer), spinners, styled tables, progress bars
- **Streaming responses** rendered as Markdown in real time — with a live view of thinking models' reasoning, and a re-roll when a model returns an empty completion — it asks you if you're there, and retries on its own if you're not. Reasoning shows on the tool path too (rendered per step, not streamed)
- **Local SQLite storage** — every session and message, fully queryable, single portable file
- **Obsidian export** — auto-exports sessions to Markdown with YAML frontmatter
- **Per-session models** — switch models mid-project; each message records what generated it
- **System prompts & personas** — Markdown files injected as system messages, editable in Obsidian
- **Tagging** — many-to-many tags, exported to Obsidian frontmatter
- **Search** — case-insensitive substring search across all messages
- **Semantic memory** — a knowledge wiki (Obsidian Markdown) embedded locally; ask it a question and get an answer cited by page, or pull the raw excerpts into the live context. New chats are indexed as they happen
- **File attachments** — inject a local text file into a session; it persists and comes back on reopen
- **Local file tools** — let the model request `list_dir` / `read_file` / `grep` itself, behind an approval gate. It can also `write_file`, but only into one narrow write root that cannot reach your code
- **Token tracking** — live context-usage bar with warnings as the window fills
- **Rolling backups** — the database is snapshotted on startup, automatically

## Requirements

- Python 3.10+
- `httpx`, `rich`, `prompt_toolkit`, [`sqlite-vec`](https://github.com/asg017/sqlite-vec), and `PyYAML` — see `requirements.txt`
- An API key for an OpenAI-compatible chat provider
- An embedding endpoint for the memory layer — either the provider's hosted `bge-m3`, or a self-hosted one (this setup runs it locally on LM Studio)

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
pip install -r requirements.txt
```

**3. Create your config**

The repo ships a `config.example.py` with placeholder values. Copy it to `config.py` and fill in your real settings:

```bash
cp config.example.py config.py
```

Then edit `config.py` and set:

- `API_KEY` — your provider's API key
- `API_BASE` — the provider's base URL
- `VAULT_PATH` — folder where exported chats are written; anywhere you like, in your Obsidian vault or outside it
- `PROMPTS_DIR` / `PERSONAS_DIR` — folders for your system-prompt and persona Markdown files
- `MODELS` / `MODEL_LIMITS` — the models your plan supports and their context sizes
- `EMBED_BASE` / `EMBED_MODEL` / `EMBED_KEY` — the embedding endpoint; defaults to the hosted `bge-m3`, or point it at a local server to self-host
- `AUTO_EMBED` — index new chat messages into memory after each turn (default on)
- `SPLASH_FRAME` — which mascot frame the launch splash shows (default `"serious.1"`)

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

Launch shows the **splash** — the mascot, once per run. **Enter** continues,
**Esc** quits. It's skipped entirely when input isn't a terminal, so piping into
cfc behaves exactly as it did before it existed.

Past it is the **hub**, listing your 20 most recent sessions with their id, last
update, message count, title, system prompt and persona. From there:

| Key | Action |
|-----|--------|
| number | Open that session |
| `n` | New session |
| `q` | Quit |

The hub is home base: `:q` inside a session brings you back here rather than
quitting, so the program only exits from the hub (`q`, or Ctrl-D/Ctrl-C). The
splash does **not** reappear on the way back — it's a launch screen, not a menu.

`python main.py 5` opens session 5 directly, skipping the hub — but its `:q`
still returns to the hub.

### In-session commands

| Command | Action |
|---------|--------|
| `:q` | Back to the hub (auto-exports if enabled) |
| `:new` | Start a new session in place |
| `:list` | Every session, not just the recent 20 |
| `:delete [n]` | Delete a session (this one by default), after a confirmation |
| `:model <name>` | Switch the current session's model |
| `:model` | Show the current model |
| `:models` | List configured models |
| `:persona <name>` | Load a persona from `PERSONAS_DIR` |
| `:persona off` | Remove the persona |
| `:personas` | List available personas |
| `:prompt <name>` | Load a system prompt from `PROMPTS_DIR` |
| `:prompt off` | Remove the system prompt |
| `:prompts` | List available system prompts |
| `:tag <name>` | Add a tag (auto-lowercased) |
| `:untag <name>` | Remove a tag |
| `:tags` / `:taglist` | Show tags / all tags with counts |
| `:grep <keyword>` | Substring search across all messages |
| `:recall <question>` | Ask the wiki a question; answer cited by page, no session effect |
| `:remember <query>` | Pull matching excerpts into the live context (ephemeral) |
| `:forget` | Drop the most recently injected excerpts |
| `:updatedb` | Index any not-yet-embedded messages into memory now |
| `:attach <path>` | Attach a local text file to the session (persistent) |
| `:attached` | List attachments in this session |
| `:detach <n>` | Remove an attachment by its `:attached` index |
| `:tools` | Show whether tools are active, and why |
| `:tools on` / `:tools off` | Toggle tools for this session |
| `:routine` | List routines, with the outcome of each one's last run |
| `:routine new` | Create a routine (name, prompt, roots, trigger) |
| `:routine <name>` | Run a routine now |
| `:outbox` | List files the model has proposed, and where each would go |
| `:file <n>` | File one proposal at its destination |
| `:file all` | File every valid proposal |
| `:file <n> drop` | Discard a proposal — moved aside, not deleted |
| `:tokens` | Detailed context-usage breakdown |
| `:export [n]` | Export a session to Obsidian (this one by default) |
| `:config` | Show current configuration (key masked) |
| `:title` | Show the current title |
| `:title <n>` | Show session `n`'s title |
| `:title <n> <name>` | Rename session `n` |

**Multi-line input:** just type or paste. Enter sends; **Alt+Enter** inserts a
newline. A pasted block keeps its line breaks and doesn't submit early. Ctrl+C
at the prompt clears the current line (it no longer leaves the session — use
`:q` or Ctrl-D for that); Ctrl+C during streaming cancels the request.

`:attach` completes paths on Tab, scoped to `ATTACH_ROOTS`. Completion stays
quiet until you've typed a few characters of a name rather than dumping a whole
directory.

## How it works

The flow:

```
main.py → splash() → repl() ┬→ pick_session() → run_session() ─┐
          Esc → exit         └───────────← :q ←─────────────────┘
                              q at the hub → quit
```

The splash sits outside `repl()` deliberately, which is why it shows once per
launch rather than every time you return to the hub.

- **SQLite** (`~/.cfc/chat.db`) holds sessions, messages, tags, and a session↔tag junction table. Schema and migrations run automatically on start — safe to re-run on an existing database.
- **API layer** streams from an OpenAI-compatible `/chat/completions` endpoint, prepending persona and system prompt as system messages.
- **Rich** drives the terminal UI with `markup=False` (so `[...]` in strings isn't treated as formatting).
- **Export** writes one Markdown file per session, overwriting on re-export — version history lives in the database, not in duplicate files.
- **Message kinds** — every row is tagged `chat`, `attachment`, `recall_marker`, `tool_call` or `tool_result`, with a JSON `meta` blob whose shape follows the kind. That's what lets an attachment export as a one-line reference instead of dumping the whole file, and lets a tool exchange replay in the right order.

## Memory

Recall runs over a **knowledge wiki** — Obsidian Markdown pages, each with a stable id in YAML frontmatter — distilled from past work. Pages are imported, chunked (500 tokens, 75 overlap, never crossing a message boundary), embedded with `bge-m3`, and stored in `sqlite-vec`.

```
python import_wiki.py <wiki_dir> ~/.cfc/chat.db   # import wiki pages (idempotent by id)
python chunk.py ~/.cfc/chat.db                     # chunk
python backfill.py ~/.cfc/chat.db                  # embed
```

Editing a page and re-importing re-chunks and re-embeds it under the same id, so a page's identity survives edits. New in-app chats are indexed automatically after each turn (`AUTO_EMBED`), or on demand with `:updatedb`; they're tagged `source='chat'` and accumulate for a future wiki+chat hybrid, while recall stays wiki-only for now.

`:recall` synthesises an answer cited by page title and id, and leaves the session untouched. `:remember` injects the raw excerpts into the live context and is ephemeral — only a marker row persists, so an export can still tell a grounded claim from an invented one. `:forget` drops the last injection.

The embedder is self-hosted here (`bge-m3` on LM Studio) but any OpenAI-compatible `/embeddings` endpoint works — set `EMBED_BASE` / `EMBED_MODEL` / `EMBED_KEY`, or leave them to fall back to the chat provider's hosted copy.

Retrieval has a floor (`MAX_DISTANCE`, currently `1.08`): if nothing is within it, memory says it has no answer rather than returning eight mediocre excerpts. It is deliberately **loose**. Measured over 32 probes, the questions this wiki can answer and the questions it can't overlap so thoroughly that no threshold tells them apart — a question about guitar tuning scores better against the corpus than a real question about its own contents. So the floor only rejects obvious lint, and the model reading the excerpts decides whether they actually answer anything, which it is told to say. Setting it tighter doesn't buy precision, it just loses good questions silently.

The number is specific to `bge-m3` **and** this corpus, including how the corpus is chunked — re-measure if any of those change.

## Security

Read this before turning tools on.

- **Reads and writes have separate scopes.** `ATTACH_ROOTS`/`TOOLS_ROOTS` bound what can be read; `WRITE_ROOTS` — a standalone setting, never derived from the read roots — bounds what can be written, and is one folder (an outbox). Being able to read a file says nothing about being able to write next to it. `WRITE_ROOTS = ()` keeps the model read-only.
- **The code is structurally unwritable.** A write root that overlaps the cfc source tree is refused when the context is built, checked in both directions. The model isn't stopped from editing the scripts by a deny-list entry — the scripts aren't in the writable universe at all.
- **Writes are atomic and don't clobber.** `write_file` writes to a temp file and moves it into place, so an interrupted write leaves the original intact. Replacing an existing file needs an explicit `overwrite`, and the approval panel says so in red before you agree.
- **Everything is jailed.** Every file operation resolves inside *any* configured root for its direction — a path passes if it resolves inside *any* configured root. Paths are **resolved before** they're checked, which is what defeats `../` traversal and symlink escape — a symlink named `notes.md` pointing at `~/.ssh/id_rsa` is judged as what it resolves to, not what it's called.
- **Some files are refused inside the jail.** A root like `~/projects` contains cfc, which contains `config.py`, which holds your API key — and `.py` is an attachable type. Containment alone is not enough. The deny list is root-agnostic: it runs on the resolved path no matter which root allowed it, so adding a root never un-denies anything. `paths.py` refuses `config.py`, `.env*`, `*.pem`, `*.key`, `id_rsa`, `.ssh/`, and friends. `config.py` may **add** to that list via `ATTACH_DENY_EXTRA`; nothing removes from it.
- **The approval gate, with no way to switch it off.** Every tool call is shown — resolved path, real file size — and confirmed before dispatch. There is no auto-approve setting: it was removed deliberately, because "pre-clear these tools permanently" is one config line away from becoming "everything runs unattended and unwatched". `A` allows the rest of one turn and dies with it, and it never covers writes — those are asked one at a time.
- **Approval does not bypass validation.** `path_guard` runs inside the dispatcher regardless of what was approved. You can approve a call that then fails the guard; that's correct. The gate is where *you* decide. The guard is what holds when you've stopped reading the gate carefully — which is what a gate that fires on every call eventually becomes.
- **`TOOLS_ENABLED = False` by default.** Opt-in, not opt-out.
- **A small surface.** `list_dir`, `read_file`, `grep`, `write_file`, and nothing else. No shell, no delete, no move.
- **Denial is data.** A denied, skipped or refused call returns `{"error": ...}` to the model as a tool result. It reads it and adapts; it doesn't crash the turn. Asked to fetch `API_KEY`, the model gets `config.py is on the deny list` and moves on — the key never reaches it.
- **The model proposes where a file should go; it doesn't put it there.** A routine writes into the outbox with a suggested `destination:` in the frontmatter. `:outbox` shows you each suggestion and what would happen; `:file <n>` carries it out. The mover re-validates the destination from scratch against its own `MOVE_ROOTS` — the suggestion is **data, not authority** — and refuses anything outside them rather than guessing at a near-miss. It may write outside `WRITE_ROOTS` precisely *because it is not the model*, which is why it stays a separate step instead of widening what the model can reach. Wiki destinations are refused outright: a page written there would leave the recall index stale with no signal that it's stale.
- **Routines are the one ungated path, and that is the whole reason they declare their own roots.** A chat has two guardrails: the roots, and you at the gate. A routine that runs at 03:00 has no human, so the gate cannot function and its roots are the only thing left. That is why a routine names its own read and write roots in its file, why those are validated when it is created rather than when it runs, and why a routine whose write root overlaps the source **cannot be saved at all**. The safety is the narrow root — never a pre-cleared tool. Every run appends to a log, so an unattended run that failed can't look like one that had nothing to do.

The tests that back this up are worth keeping green: `tests/test_paths.py` covers traversal, symlink escape, the deny list, and the write jail; `tests/test_gate.py` asserts that approving a call still doesn't bypass the guard, that writes are never auto-approved, and that a readable path is not a writable one.

## Known limitations

- **Routines run on command, not on a schedule** — `:routine <name>` runs one now. There's no scheduler yet; the run path is built so an OS scheduler can call the same entry point unchanged, and deliberately isn't an in-process timer thread.
- **Recall is wiki-only** — the semantic index answers from the distilled wiki, which states each decision once. Raw chat logs are indexed (`source='chat'`) but not yet folded into recall; that hybrid is a future additive step. This sidesteps the old "resolution staleness" problem, where searching raw transcripts surfaced the messages where a decision was being *argued* over the one where it was settled.
- **Streaming is off when tools are active** — tool-call deltas arrive fragmented and the `arguments` string has to be reassembled across chunks by index. Not worth it; these responses are fast. The normal chat path still streams. (Reasoning still shows on the tool path — it just arrives all at once per step rather than streaming in.)
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
| `tools.py` | the tools and the dispatcher |
| `context.py` | what a given run may read, write, and whether it's gated |
| `paths.py` | the jail: containment and the deny list |
| `routines.py` | the routine object, its file store, and the run log |
| `runner.py` | running one routine — the headless entry point in all but name |
| `mover.py` | filing a proposal out of the outbox: re-validates the destination, or refuses |
| `complete.py` | Tab completion for `:attach` |
| `hub.py` | the session browser and picker |
| `db.py` | connection, schema, every query |
| `api.py` | streaming and non-streaming calls to the endpoint |
| `export.py` | writing a session out to the vault |
| `backup.py` | rolling snapshots of the database |
| `ui.py` | the shared console, presentation helpers, the line editor, and the splash |
| `config.py` | settings — gitignored |

The memory layer is separate: `import_wiki.py` (and `import_anthropic.py`), `chunk.py`, `embed.py`, `backfill.py`, `search.py`, `recall.py`.

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
python tests/test_routines.py    # the routine file round-trip, scope refusal, run log
python tests/test_mover.py       # filing: destination re-validation, refusals, atomicity
python tests/test_empty.py       # empty completions: ask a human, or re-roll and give up
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

Those snapshots have already earned their keep beyond disaster recovery: v0.2 resolved a retrieval mystery by measuring the same query against five months of daily snapshots and proving the corpus had never changed. A rolling backup is also a record of what used to be true.

## The vault, and why it's a git repo

cfc's memory is not stored in cfc. The corpus is an Obsidian vault on the Windows side (`/mnt/c/...` from WSL), and the app reads it, indexes it, and writes into one folder of it. Understanding that split explains most of the path handling in `config.py`.

```
<vault>/03 resources/wiki db   the distilled pages that recall answers from
<vault>/00 inbox               Cas writes, the model reads
<vault>/99 outbox              the model writes, Cas reads  (the only writable path)
```

As of 2026-07-21 the vault is a git repo. Obsidian has no real diff or rollback of its own, and the daily file backup answers "what does this note say now" but never "what did it say last week, and what changed it." More to the point, it's the plumbing the wiki automation needs: before a model is allowed to propose edits to the corpus, there has to be a way to see exactly what it changed and refuse it.

Two setup decisions are worth recording, because both are easy to get wrong and neither is obvious.

**`.git` does not live in the vault.** It was moved to native Linux storage and replaced with a one-line pointer:

```bash
git init                                  # inside the vault
mv .git ~/vaults/wiki.git
echo "gitdir: /home/<user>/vaults/wiki.git" > .git
```

`gitdir:` is a standard git redirect — the same mechanism worktrees and submodules use — so every `git` command run from inside the vault works unchanged. It buys two things. Git's internals stop being read and written across the `/mnt/c` bridge, which is markedly slower than ext4; and `.git` becomes a 36-byte file rather than a folder full of objects, which keeps Obsidian's file explorer, search and graph clear of it. (Obsidian hides dotfiles anyway — this was confirmed by looking, not assumed.)

The tradeoff, stated plainly: the history now lives outside the Windows daily backup that covers the notes themselves. A WSL reinstall would keep every note and lose every commit. A remote would close that, and is parked at v1.0 alongside the question of whether the vault's medical reference material belongs on someone else's server.

**Binaries are not tracked.** `.gitignore` excludes PDFs and images, which drops the repo from 131 MB to about 7. They're static reference material that never gets edited, they're already backed up, and a committed blob is in the history permanently. The extracted Markdown of those PDFs *is* tracked, so the content is versioned even where the source file isn't. Also ignored: `.obsidian/workspace.json` and `.claude/settings.local.json` (per-device state that rewrites itself every session — a repo that's always dirty is a repo whose `git status` you stop reading), and everything in `99 outbox` except its readme, since a scratch folder has no meaningful clean state.

**One git config that matters.** `core.autocrlf` is pinned to `false` and `.gitattributes` sets `* text=auto eol=lf`. Windows git and WSL git normalize line endings differently, and a file written under one then diffed under the other shows as *entirely rewritten* with no visible change. The vault is worked on from Ubuntu only; the `.gitattributes` is belt-and-braces in case that ever slips.

## License

Personal project. No license specified.
