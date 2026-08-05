# cfc — cooking for cats

Cooking for Cats is a terminal AI chat client in Python. It talks to any
OpenAI-compatible chat provider, keeps conversations in a local SQLite
database, searches an Obsidian knowledge wiki, and can run narrow, declared
tasks against your filesystem.

The project is designed around local control: tools are off by default, model
writes require approval, and unattended routines are restricted to their own
declared roots.

## What it does

- Terminal chat with Markdown, coloured speaker panels, a splash screen, and a
  context-usage display.
- Prompts, personas, and stackable traits stored as Markdown files.
- Local semantic memory over an Obsidian wiki, with cited recall answers.
- Private in-memory chats that are not saved unless you explicitly export one.
- Model tools for carefully bounded listing, reading, searching, and writing.
- Routines that run manually or on a schedule against declared roots.
- A reviewable outbox for model filing proposals and journal drafts.
- Local vault Git commands for status, diffs, and commits.

## Requirements

- Python 3.10 or newer
- The packages in [`requirements.txt`](requirements.txt)
- An API key and endpoint for an OpenAI-compatible chat provider
- An embedding endpoint for the memory layer; the default setup uses `bge-m3`
  through LM Studio

## Install

```bash
git clone git@github.com:Wantotg/cfc.git
cd cfc
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.py config.py
```

Edit `config.py` with your provider, models, prompt/persona/trait folders,
embedding endpoint, and vault paths. `config.py` is local configuration and is
never committed.

## Run

```bash
python main.py
```

Or use the launcher, which checks the embedding service before opening cfc:

```bash
./launch.sh
```

From the hub, type a chat id to open a conversation, `n` for a new chat, `p`
for a private chat, or `q` to quit. Inside a chat, `/q` returns to the hub.
Type `/help` for the command list.

## Read next

- [`User guide`](documents/USER%20GUIDE.md) — setup details, input, commands,
  memory, routines, the journal, and the vault workflow.
- [`Operations and security`](documents/OPERATIONS%20AND%20SECURITY.md) — tool
  boundaries, private data, storage, backups, scheduling, limits, and tests.
- [`ROADMAP.md`](ROADMAP.md) — public version history and direction.
- [`development/CHANGELOG.md`](development/CHANGELOG.md) — detailed changes.
- [`SYSTEM_INJECTIONS.md`](documents/SYSTEM_INJECTIONS.md) — the system-layer text cfc
  sends around a turn.
- [`HANDOVER.md`](HANDOVER.md) — settled technical decisions and architecture.

## License

AGPL-3.0. See [`LICENSE.md`](LICENSE.md).
