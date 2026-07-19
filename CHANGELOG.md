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

## 2026-07-19 — Point embeddings at self-hosted bge-m3 (LM Studio)
Split the embedding endpoint from chat (EMBED_BASE/EMBED_MODEL/EMBED_KEY) so the
RAG layer runs on local bge-m3 via LM Studio instead of nano-gpt's hosted copy;
verified parity (cosine ≥ 0.9993 over 6 probes, pooling + normalization match).
Falls back to the hosted defaults when the new keys are absent. Step 1 of the
wiki-DB migration.
- Files: embed.py, config.py (gitignored), config.example.py, BACKLOG.md
- Status: shipped
- Commit: pending

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
