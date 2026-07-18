# Changelog

What changed and when. Most recent at the top. This is the running log so
`HANDOVER.md` can stay what it is — invariants and design reasoning, not history.

One entry per change. Keep it to what a future reader needs: the date, a title,
a one-line what/why, the files touched, and status. The **commit** hash is the
ID — it links straight to GitHub, so there's no separate numbering to maintain.
Fill it in after committing (`git rev-parse --short HEAD`); leave it `pending`
for uncommitted work.

Template:

```
## YYYY-MM-DD — Title in the imperative
One line: what changed and why it mattered.
- Files: a.py, b.py
- Status: shipped | wip | reverted
- Commit: <short-hash>
```

---

## 2026-07-18 — Erase the input line so the human turn isn't shown twice
The bordered human panel duplicated the raw `you>` line prompt_toolkit leaves on
screen; `erase_when_done` on the PromptSession wipes it so only the panel shows.
- Files: ui.py
- Status: shipped
- Commit: 25a24c6
