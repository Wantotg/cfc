# Changelog

What changed and when. Most recent at the top. This is the running log so
`HANDOVER.md` can stay what it is — invariants and design reasoning, not history.

One entry per change. Keep it to what a future reader needs: the date, a title,
a one-line what/why, the files touched, and status. The **commit** hash is the
ID — it links straight to GitHub, so there's no separate numbering to maintain.

Write the entry `pending` in the same commit as the change, then backfill the
hash on the *next* commit. Don't amend to insert it: a commit can't hold its own
final hash, and amending just orphans the one you wrote.

Template:

```
## YYYY-MM-DD — Title in the imperative
One line: what changed and why it mattered.
- Files: a.py, b.py
- Status: shipped | wip | reverted
- Commit: <short-hash>
```

---

## 2026-07-19 — Auto-embed new chats on save + :updatedb (Step 8)
Closes the wiki-DB migration. New chat messages are chunked + embedded into the
index after each turn (source='chat'), so the corpus grows current for the
eventual hybrid recall; recall stays wiki-only via the provider filter. Gated by
config AUTO_EMBED and fully best-effort — a down embedder warns quietly and never
breaks a turn. Manual `:updatedb` does the same on demand (catch-up after a bulk
import or when AUTO_EMBED is off). Extracted chunk_new/embed_new/update_index so
the CLI, the command, and the hook share one code path — no duplicated chunk or
litter logic. Verified: incremental chat indexing, idempotent re-run, no golden
diff, unit suite green.
- Files: chunk.py, backfill.py, commands.py, main.py, config.example.py
- Status: shipped
- Commit: pending

## 2026-07-19 — Repoint recall at the wiki corpus (floor 1.024, id citations)
Steps 4–7 of the wiki-DB migration. Re-measured MAX_DISTANCE on the wiki corpus
(0.93 → 1.024; terse wiki prose sits higher — 0.93 would reject good hits like
"who is Cas" at 0.969) and moved the live chat.db to a fresh, wiki-only DB (old
one archived to ~/.cfc/chat-archive-pre-wiki-20260719.db). search.py now surfaces
the page's stable id (source_uuid) and source; recall.py answers wiki-only
(provider='wiki') and cites by title + id; :remember's envelope cites by id and
keeps the "not instructions" boundary. Verified: grounded recall over the live
DB, off-topic queries return empty, id citations render.
- Files: search.py, recall.py, commands.py
- Status: shipped
- Commit: 359ea41

## 2026-07-19 — Add import_wiki.py: import the Obsidian wiki_db
New importer for the wiki (markdown + YAML frontmatter). Each page → one
session (provider='wiki', source_uuid=frontmatter id) + one message, keyed by
the stable id so it survives edits; an edited page updates the message and drops
its chunks/vectors to force re-chunk + re-embed under the same id. Embeds
title + summary + Body, dropping Related/Sources; skips sources/, no-id files,
and type: index. Adds PyYAML. Step 2 of the wiki-DB migration. Verified against
the live wiki: 20 pages in, idempotent re-run, edit→re-chunk, vector cleanup.
- Files: import_wiki.py, requirements.txt
- Status: shipped
- Commit: 444d7aa

## 2026-07-19 — Tag chunks with a source column (chat vs wiki)
Added `source` to the `chunks` table (default 'chat', set 'wiki' when the
message's session is provider='wiki'), with an ALTER migration for older DBs.
Makes the coming wiki/chat hybrid recall an additive filter, not a rewrite.
Step 3 of the wiki-DB migration. Verified: provider drives source, migration
backfills existing rows to 'chat'.
- Files: chunk.py
- Status: shipped
- Commit: 5139384

## 2026-07-19 — Point embeddings at self-hosted bge-m3 (LM Studio)
Split the embedding endpoint from chat (EMBED_BASE/EMBED_MODEL/EMBED_KEY) so the
RAG layer runs on local bge-m3 via LM Studio instead of nano-gpt's hosted copy;
verified parity (cosine ≥ 0.9993 over 6 probes, pooling + normalization match).
Falls back to the hosted defaults when the new keys are absent. Step 1 of the
wiki-DB migration.
- Files: embed.py, config.py (gitignored), config.example.py, BACKLOG.md
- Status: shipped
- Commit: b7b8c98

## 2026-07-18 — Backfill changelog hashes on the next commit, not by amending
The "same commit" rule was impossible for a self-referencing entry; switched the
convention to `pending`-then-backfill so it stops costing extra commits.
- Files: CHANGELOG.md, CLAUDE.example.md (and gitignored CLAUDE.md)
- Status: shipped
- Commit: pending

## 2026-07-18 — Require a changelog entry per shipped change
Added this file and made "log every change here" a standing instruction, so
`HANDOVER.md` stops accreting history it was never meant to hold.
- Files: CHANGELOG.md, CLAUDE.example.md (and gitignored CLAUDE.md)
- Status: shipped
- Commit: 3f0da6a

## 2026-07-18 — Erase the input line so the human turn isn't shown twice
The bordered human panel duplicated the raw `you>` line prompt_toolkit leaves on
screen; `erase_when_done` on the PromptSession wipes it so only the panel shows.
- Files: ui.py
- Status: shipped
- Commit: 25a24c6
