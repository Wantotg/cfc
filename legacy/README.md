# legacy/

Frozen documents. Nothing here is current, nothing here is maintained, and
nothing here should be worked from.

| | |
|---|---|
| [`BUGS.md`](BUGS.md) | closed entries from `../BUGS.md`, frozen 2026-07-27 |
| [`BACKLOG.md`](BACKLOG.md) | closed entries from `../BACKLOG.md`, frozen 2026-07-27 |
| [`CHANGELOG-pre-1.0.md`](CHANGELOG-pre-1.0.md) | every entry up to the v1.0 tag, frozen 2026-07-29 |
| [`CHANGELOG-post-1.0.md`](CHANGELOG-post-1.0.md) | entries older than the 2026-08-01 triage boundary, frozen 2026-08-03 |
| [`HANDOVER.md`](HANDOVER.md) | the pre-repo-access handover, frozen at v0.8, 2026-07-25 |
| [`CLAUDE.example.md`](CLAUDE.example.md) | the six-session arrangement that preceded the loop, frozen 2026-07-29. Superseded by [`../templates/`](../templates/) |

## Why keep them

Two different reasons, and they're worth separating.

**The bug and backlog archives keep the original report.** `CHANGELOG.md`
records every fix and the reasoning behind it, but never the symptom as first
written — and that half is frequently the valuable one. The `MAX_DISTANCE` entry
in `BACKLOG.md` is the case in point: the report's *wrong* premise is the
finding, and a changelog entry describing the fix would have lost it. Live
`BUGS.md` and `BACKLOG.md` hold open entries only; a closed entry moves here
whole and leaves no stub behind.

**The changelog archives are here for length alone.** Nothing was cut from them
and nothing in them was rewritten — the pre-1.0 archive holds the log through
the v1.0 tag, and the post-1.0 archive holds the older entries removed from the
live file at the 2026-08-01 triage boundary. `CHANGELOG.md` remains the index of
what shipped and links to both archives.

**The old handover keeps the long-form reasoning.** It was written for a model
working without the source, so it re-describes a lot you can now just go and
read — but the arguments behind most of the current handover's one-liners are
here, and deleting the record of why something was decided is how it gets
re-decided.

## Reading order when the current docs disagree

The code wins, then `../HANDOVER.md`, then this folder.
