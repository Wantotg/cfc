# cfc — RAG Memory Layer

Semantic memory over past AI conversations. Everything lives inside the existing
`~/.cfc/chat.db` — no separate vector service, no sidecar directory, single portable file.

Built on top of cfc's existing `sessions` / `messages` schema. Additive: existing
GLM chat data is untouched.

## What this does

Imports an Anthropic data export into cfc's database, slices the messages into
retrievable chunks, embeds them as vectors, and lets you ask your own history
questions in plain language and get grounded, cited answers.

## The stack

| Layer | File | Role |
|-------|------|------|
| **Ingest** | `import_anthropic.py` | Anthropic export JSON → `sessions` / `messages` |
| **Ingest** | `chunk.py` | messages → `chunks` table |
| **Ingest** | `backfill.py` | chunks → `vec_chunks` vectors |
| **Library** | `embed.py` | text → 1024-dim vectors (nano-gpt API) |
| **Library** | `search.py` | query → ranked relevant chunks (pure retrieval) |
| **Library** | `recall.py` | query → grounded prose answer with citations |

The **ingest** trio is a one-shot pipeline, run in order. The **library** trio is
imported by other code and used repeatedly.

## Configuration

Everything reads from the existing `config.py`. No separate credentials — embeddings
use the same `API_KEY` / `API_BASE` as chat, just a different endpoint.

```python
API_KEY  = "..."                          # same key as chat
API_BASE = "https://api.nano-gpt.com/v1"  # both this and nano-gpt.com/api/v1 work
RECALL_MODEL = "..."                      # optional; falls back to MODEL
```

**Embedding model:** `BAAI/bge-m3`, 1024 dimensions. Chosen for multilingual
strength (the corpus mixes English and Dutch) and small vectors. Pinned in `embed.py`
as `EMBED_MODEL` / `EMBED_DIM` — changing it means re-running the backfill, since
vector dimension is fixed at table creation.

**Recall model:** set `RECALL_MODEL` in `config.py` to switch. This model only reads
excerpts and summarises them — it doesn't need to be smart, it needs to be fast and
obedient. Fast instruct models (e.g. Qwen3 30B A3B Instruct) give concise, factual
answers; thinking models (e.g. GLM 5.2) give richer, more narrative ones but are slower.

## Schema additions

```
sessions.source_uuid   -- added; Anthropic conversation UUID (idempotency)
messages.source_uuid   -- added; Anthropic message UUID (idempotency)

chunks(
  id, message_id, session_id,
  kind,        -- 'message' | 'thinking'
  ordinal,     -- position within the message
  text, token_est,
  UNIQUE(message_id, kind, ordinal)
)

vec_chunks   -- sqlite-vec virtual table (vec0)
  chunk_id INTEGER PRIMARY KEY, embedding float[1024]
```

`chunks` is the human-readable truth; `vec_chunks` is the math. They join on
`chunks.id = vec_chunks.chunk_id`. The vector table is **derived and rebuildable** —
delete it and re-run `backfill.py` and nothing is lost.

## The pipeline

Run inside the venv (`source .venv/bin/activate`).

```bash
# 1. Import an Anthropic export (--wipe = clean reload of anthropic rows only)
python3 import_anthropic.py claude_export/conversations.json ~/.cfc/chat.db --wipe

# 2. Slice into chunks (--rebuild = drop and rebuild chunks table)
python3 chunk.py ~/.cfc/chat.db --rebuild

# 3. Embed everything missing a vector (idempotent; re-run to resume)
python3 backfill.py ~/.cfc/chat.db [--limit N]
```

## Usage

```bash
# Pure retrieval — see what the vectors actually match
python3 search.py ~/.cfc/chat.db "the memory system we're building" 8

# Grounded synthesis — memory that talks
python3 recall.py ~/.cfc/chat.db "what did we decide about the vector db?"
```

As a library:

```python
from search import search
from recall import recall

hits = search(db_path, "query", k=8, kind=None, provider=None)
answer, hits = recall(db_path, "question", k=8, kind=None)
```

`kind` filters retrieval to `'message'` (conclusions) or `'thinking'` (reasoning);
`None` returns both.

## Design decisions worth remembering

**Thinking blocks are kept, but tagged — not blended.** Anthropic exports include
extended-thinking blocks. They're preserved as separate chunks with `kind='thinking'`
rather than concatenated into message bodies, so retrieval can weight or filter
reasoning separately from conclusions. Blending them makes it impossible to tell a
tentative musing from an actual answer.

**Chunks never span message boundaries.** Mixing a question and its answer into one
vector makes retrieval mush. Message boundary is a hard wall. Long messages slice at
~500 tokens with ~75 token overlap; short ones stay whole.

**Tool markers are stored but not embedded.** `[tool_use: ...]` markers stay in the
chunk text for context, but chunks that are *only* a marker get no vector — they'd
match nothing useful and add noise. Filtered at embed time in `backfill.py`.

**Retrieval and synthesis are separate layers.** `search.py` has no model in it. If a
recall answer is wrong, you can check whether retrieval pulled bad chunks or the model
misread good ones. Merging them creates an undebuggable black box.

**Grounding discipline is the whole point.** `recall.py`'s system prompt forbids
outside knowledge and requires admitting gaps. Seeing it say "the excerpts don't cover
that" is it *working*. Citations are by conversation title + date — the context
deliberately contains no excerpt numbers, so there's no wrong handle for the model to
grab.

**Everything is idempotent.** The importer keys on Anthropic UUIDs, the chunker on
`(message_id, kind, ordinal)`, the backfill on existing `chunk_id`s. Re-run any stage
safely; the backfill resumes if interrupted.

## Known limitations

- **Branching not handled.** Anthropic stores messages as a tree
  (`parent_message_uuid`); the importer flattens by `created_at`. Correct for linear
  conversations, which is nearly all of them. Branched chats linearise slightly wrong.
- **Empty messages skipped.** Messages with no text content are dropped at import
  (counted in the summary). Keep the raw export — it's the only way back.
- **Chunk sizes are untuned defaults.** 500/75 is a sane starting point, not a
  measured optimum. `chunk.py --rebuild` + `backfill.py` re-does everything for cents
  if you want to experiment.
- **`tool_result` content is dropped**, only counted. Fine for a memory system that
  cares about decisions, not raw tool output.

## Cost

Negligible, and this is not a hedge. Embedding the entire 4,580-chunk corpus cost
**~$0.01**. Ongoing per-recall usage is roughly 1,300 tokens in / 500 out. Pick models
on quality; cost is not a design constraint here.

## Requirements

```bash
pip install httpx rich sqlite-vec
```

`sqlite-vec` is a loadable SQLite extension. Requires a Python whose `sqlite3` has
`enable_load_extension` (verify: `hasattr(sqlite3.connect(':memory:'), 'enable_load_extension')`).
On Debian/Ubuntu/WSL, install inside a venv — PEP 668 blocks pip against system Python.
