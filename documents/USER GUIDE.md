# Cooking for Cats user guide

This is the practical guide to using cfc after installation. The short version
is in the repository [README](../README.md); this guide covers the screens,
commands, memory, routines, journal, and notes workflow in more detail.

## Start cfc

From the repository:

```bash
python main.py
```

The optional launcher checks the embedding service first:

```bash
./launch.sh
```

`python main.py 5` opens session 5 directly. From the hub, type a chat id to
open it, `n` for a new chat, `p` for a private chat, or `q` to quit.

The hub also shows recent chats and routines. `/q` returns to the hub from a
chat; cfc exits from the hub.

## Input

- Enter sends the current line.
- Alt+Enter inserts a newline.
- Ctrl+C clears the prompt; during a streamed answer it cancels the request.
- Ctrl+D exits the current input when the prompt is empty.
- Tab completes commands, pool names, routines, and permitted paths.

`MOUSE_INPUT` is off by default. When enabled, clicking positions the cursor;
hold Shift when selecting text from the conversation scrollback.

## Commands

Commands have the general form:

```text
/verb [kind] [target] [message]
```

Use `/help` when in doubt. `/list` answers what exists, and `/status` answers
what is active in the current session. A bare integer means a chat id; `#n`
means attachment number `n`.

### Context

| Command | Purpose |
|---|---|
| `/add <name>` | Attach a prompt, persona, or trait |
| `/add <kind> <name>` | Attach one from a named pool |
| `/add <path>` | Attach an external file |
| `/add tag <name>` | Add a session tag |
| `/remove <name>` | Remove a named attachment |
| `/remove #<n>` | Remove attachment number `n` |
| `/remove excerpts` | Remove the latest memory injection |
| `/status` | Show active context and session state |
| `/status <kind>` | Show the text of an attached prompt, persona, or trait |
| `/model <name or number>` | Change model |
| `/preset <name>` | Apply a configured sampling preset |
| `/tools on` / `/tools off` | Enable or disable tools for this session |
| `/database on` / `/database off` | Enable or disable memory commands |
| `/connect` | Report embedding-service status |
| `/connect embedding` | Try to start and verify the local embedder |

Prompts and personas are singular. Traits stack in attachment order. Names are
case-insensitive and unique partial matches are accepted; ambiguous matches
are shown for you to choose rather than guessed.

### Sessions and data

| Command | Purpose |
|---|---|
| `/new` | Start a new session in place |
| `/new p` | Start a private chat |
| `/title <n> <name>` | Rename session `n` |
| `/export` | Export the current session |
| `/export chat 5` | Export session 5 |
| `/delete chat [<id>]` | Delete a chat after confirmation |
| `/search <word>` | Search stored messages |
| `/swipe` | Ask for a different answer to the last message |
| `/undo` | Remove the last user message and its answer |
| `/continue` | Ask the model to continue its last answer |
| `/q` | Return to the hub |

A private chat uses an in-memory database. It leaves no transcript, index,
title, or hub entry when it closes. An explicit `/export` typed by you is the
exception; model file writes remain blocked.

### Memory

Memory searches the indexed Obsidian wiki, not the raw chat history.

```text
/recall <question>    answer with page citations, without changing the session
/remember <question>  inject matching excerpts into the current context
/update db            import, chunk, and index the wiki
/update db prune      also remove stale index rows
```

`/recall` does not alter the conversation. `/remember` is temporary; use
`/remove excerpts` to drop the latest injection. New chats are indexed after
turns when `AUTO_EMBED` is enabled, but chat rows are not yet included in
recall answers.

If memory reports that the embedder was not answering, the search did not run.
If it says memory is empty, run `/update db`. A genuine “nothing comes close”
means the indexed wiki was searched and did not contain a close match.

### Routines

A routine is a model task with its own declared read and write roots. Create and
edit it in the vault with `/routine`; run it manually with `/routine <name>`.

The trigger is either `command`, a daily time, or a completed weekly span:

```yaml
trigger: "0300"
```

Quote hand-written times with a leading zero. An unquoted YAML value such as
`0300` can be interpreted as octal.

The operating system calls cfc periodically:

```bash
python main.py --due
python main.py --run-due
python main.py --run-routine <name>
```

`--due` reports without running anything. A daily routine runs once for that
day, including same-day catch-up after a missed time. A missed day is not
replayed later. Weekly routines process a week after it has finished. Two
ticks cannot overlap. Failures can retry according to the routine's
`on_failure` setting.

On Windows, use Task Scheduler to call `run-due.sh`; do not rely on cron inside
WSL, because WSL may stop when no session is open. Scheduled activity is logged
to `~/.cfc/schedule.log`.

### Filing and the vault

The model proposes files in the outbox; it does not silently file them. Review
proposals with `/list outbox`, then use `/file` to approve one or `/file <n>
decline <why>` to reject it. `/move` is the human-directed path for moving an
outbox file to a destination you choose.

Useful commands include:

```text
/list outbox
/file
/move
/wiki status
/wiki diff
/wiki commit
/clear notes
```

`00 inbox/notes` is input for memory routines and is not cleared automatically.
`/clear notes` shows what will move and archives the notes into a dated folder;
it is an undoable archive, not deletion.

The journal is separate from recall. Daily and weekly routines draft replacements
in `99 outbox/journal/`. Filing a journal replacement requires the vault journal
to be committed first, so Git can provide recovery.

## First message and small input controls

Put an optional Markdown file named after a persona in `FIRST_MESSAGES_DIR` to
give new sessions for that persona an opening message. The text is copied into
the new session and does not change when the source file is later edited.

A line containing only `((direction))` is an out-of-character instruction for
that turn. It is not saved as a chat message. `/continue` uses the same kind of
temporary direction.

## More detail

Read [Operations and Security](OPERATIONS%20AND%20SECURITY.md) before enabling
tools or unattended routines. It explains the path boundaries, approval gate,
storage, backups, and known limitations.
