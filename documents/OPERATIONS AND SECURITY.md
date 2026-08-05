# Cooking for Cats operations and security

This guide explains where cfc can reach, what it stores, what it backs up, and
which limits are deliberate. Read it before enabling model tools or unattended
routines.

## Tool safety

Tools are disabled by default. When enabled, the model has a small tool surface:
`list_dir`, `read_file`, `grep`, and `write_file`.

- Read access is bounded by `ATTACH_ROOTS` and `TOOLS_ROOTS`.
- Write access is separately bounded by `WRITE_ROOTS`, which may be one narrow
  folder or empty. Read access does not imply write access.
- The source tree cannot be a write root.
- Paths are resolved before validation, preventing `..` traversal and symlink
  escapes.
- A deny list refuses secrets and sensitive shapes such as `config.py`, `.env*`,
  private keys, `.ssh/`, and compiled bytecode. `ATTACH_DENY_EXTRA` can add
  entries but cannot remove the built-in denials.
- Writes are atomic. Replacing an existing file requires an explicit overwrite
  request and approval.
- Every tool call passes through a visible approval gate. Approval does not
  bypass path validation, and approval never covers writes automatically.
- Tools cannot delete files, run shell commands, or move files.

The model can propose a destination for filing, but the destination is treated
as data and checked again against `MOVE_ROOTS`. `/move` is a human-directed
operation. It does not give the model a broader write scope.

Routines are different: they run without a person at the approval gate. Their
declared roots are therefore validated when the routine is created, and a
routine whose write root overlaps the source tree cannot be saved. The run log
is closed to the model because it is both audit trail and scheduling state.

## Private chats and provider traffic

A private chat keeps its local database in memory. Closing it removes its
transcript, index, title, and hub entry. It still sends messages to the selected
chat provider. An explicit `/export` typed by you can write it to disk; model
file writes remain blocked.

## What lives where

cfc normally runs in WSL2 on a Windows host. The important storage boundaries
are:

| Data | Location | What happens on a WSL reset |
|---|---|---|
| Source code | `~/projects/cfc` | Lost locally, recoverable from GitHub |
| Chat database, snapshots, logs | `~/.cfc/` | Lost locally unless separately copied |
| Vault files | Windows storage under `/mnt/c/...` | Survive the WSL reset |
| Vault Git history | Native Linux storage | Lost locally unless pushed separately |
| Exported chats | `CHAT_EXPORT_DIR` | Depends on its configured location |

The vault is intentionally split: its files remain visible to Windows and
Obsidian, while its Git internals live on native Linux storage for reliability
and speed. Losing Windows and losing WSL affect different halves, but neither
half should be treated as a complete backup by itself.

The chat provider and embedding provider are separate. Chat uses an
OpenAI-compatible endpoint. The default embedding setup uses `bge-m3` through
LM Studio on Windows at `localhost:1233`, though any compatible embeddings
endpoint can be configured.

## Backups

cfc keeps up to ten integrity-checked SQLite snapshots in `~/.cfc/backups/`.
Snapshots are made at startup at most once every six hours when the database has
changed.

```bash
python backup.py
python backup.py --force
python backup.py --list
python backup.py --restore latest
```

The backup uses SQLite's online backup API rather than copying the live database.
A restore first protects the current database with another snapshot.

These snapshots protect against a bad write, migration, or local mistake. They
are on the same disk as the database. cfc does not create an off-machine copy,
commit the vault, or push anything to GitHub.

For an off-machine database copy, create a fresh snapshot and copy that snapshot
yourself:

```bash
python backup.py --force
# copy the resulting snapshot to a private drive or another machine
```

Never copy the live database while it may be changing.

## The vault and Git

The vault commonly contains:

```text
03 resources/wiki db   indexed pages used by recall
00 inbox               material you provide for routines
99 outbox              model proposals and routine drafts
```

The vault is a Git repository so proposed edits can be reviewed and recovered.
cfc can inspect status, show diffs, and make a local commit through `/wiki`; it
does not push. Push the vault manually when you choose.

Journal replacements are the special case: cfc refuses to file one unless the
journal is committed, because overwriting a live journal without a recoverable
Git state would be a poor trick disguised as automation.

## Memory boundaries

Recall searches imported and embedded wiki pages. It does not yet answer from
raw chat history, even though new chat messages may be indexed for later use.
The embedding model, corpus, and chunking strategy affect retrieval quality;
changing any of them can require re-measuring the configured distance floor.

Deleting a session deletes its indexed material in cfc's normal path. Older
databases may contain stale index rows; `/update db prune` removes those rows.

## Scheduler behaviour

The operating system must call cfc periodically. cfc decides what is due from
each routine's trigger and run log. It does not install a scheduler entry for
you.

Scheduled routines catch up on the same day but do not replay several missed
days. A retry policy can retry failures, with a daily limit. Provider responses
such as 429, 502, 503, and empty completions receive limited immediate retries;
other failures are not made temporary by their wording.

The scheduler is designed to be quiet when nothing is due. `run-due.sh` writes
heartbeat and failure information to `~/.cfc/schedule.log`, so a hidden task is
still diagnosable.

## Known limits

- Recall is wiki-only; journal text is not automatically part of recall.
- Sessions are linear; cfc does not branch conversations.
- Search is substring search rather than full-text search.
- Streaming is disabled while tools are active.
- Tool calling requires a model configured for tool use; unattended routines
  require a model configured for routines.
- Streaming token counts require provider support for
  `stream_options: {"include_usage": true}`.
- Traits are attached per session; there is no global always-on trait.
- The scheduler needs one operating-system entry, created by you.

## Tests and source map

The no-API characterization check is:

```bash
python tests/golden.py check
```

Focused suites cover the path jail and approval gate in `tests/test_paths.py`
and `tests/test_gate.py`. Real provider turns, retrieval quality, and terminal
rendering still need practical verification.

The main seams are `main.py` (REPL), `parse.py` (grammar), `commands.py`
(commands), `agent.py` (tool-calling turn), `paths.py` (path jail), `db.py`
(SQLite), `runner.py` and `schedule.py` (unattended work), and `mover.py`
(filing).
