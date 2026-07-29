# Changelog

What changed and when. Most recent at the top. **Everything up to and including
the v1.0 tag is frozen in [`legacy/CHANGELOG.md`](legacy/CHANGELOG.md)**
(2026-07-29): this file had reached 3,418 lines, past the point where a session
reads it in one pass rather than sampling it.

One entry per change: the date, a title, what changed and why it mattered, the
files touched, and status. The **commit** hash is the ID — it links straight to
GitHub, so there's no separate numbering to maintain. What belongs here rather
than in `HANDOVER.md`, and how long an entry gets, is in `HANDOVER.md`, *Which
file owns what*.

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

## 2026-07-29 — The roadmap becomes the front office
Post-1.0 doc rewrite, step 3. `W-06`, closed. `ROADMAP.md` was trying to be a
roadmap, a changelog, a backlog and a bug report at once — reasonable, since it
was the only one of the four that existed at v0.1 and the others were added
underneath it. It now carries what a release *does*, and points at the other
three for why.

The entry shape from v1.1: two or three sentences, **Added**, **Fixed** at one
patch-note line per fix carrying its tracker id, and Cas's note last as the
signature on the release. The id is what makes a one-line fix affordable — the
description already exists in `legacy/BUGS.md`, the reasoning here, the
assignment in `TRACKER.md`.

v0.1–v1.0 stay exactly as written, behind a boundary line that says so, and
v1.1 is stubbed with number and title only. Cas's call on both halves: **Fixed**
stays visible rather than being tidied out of the front door, and the note stays
at the bottom.

- Files: ROADMAP.md, TRACKER.md
- Status: shipped
- Commit: pending

## 2026-07-29 — The pre-1.0 changelog is frozen
Post-1.0 doc rewrite, step 2. Every entry up to and including the v1.0 tag moves
whole to `legacy/CHANGELOG.md`; the live file keeps the header and starts at
step 1. Nothing was rewritten or dropped — this is the archive rule applied to a
third file, for length rather than for closure.

**The measurement, since "too long" is otherwise an opinion.** At 3,418 lines it
was past a session's default read limit, so no model had read the whole file for
some time; they sampled it and could not have said which part they missed.

The archive gets a two-line frontispiece instead of a copy of the header. Cas's
call between the two options: a template in a frozen file is an instruction
nobody should follow.

- Files: CHANGELOG.md, legacy/CHANGELOG.md, legacy/README.md, HANDOVER.md
- Status: shipped
- Commit: pending

## 2026-07-29 — cx · A transient provider status stops killing an unattended run
`D-0.9.2-01`, closed. A 503 from the provider used to pass straight through
`_turn_with_retry` and log the run `failed`, spending one of the day's three
retry slots — three of them fifteen minutes apart cost `short-term-memory` the
whole of 29-07 while the provider recovered in between.

The retry now covers 429, 502 and 503, **matched on the status code and never
on the wording**: `api._provider_error` attaches `status_code` at the HTTP
boundary and `agent_turn` preserves it while adding request context. That is
what keeps this off `HANDOVER.md`'s producer/parser table rather than adding a
seventh row to it. It is routine-only, and it shares
`EMPTY_COMPLETION_RETRIES`' budget rather than opening a second one.

Shipped by Codex in `8b83d97` **without this entry, the `BACKLOG.md` close or
the tracker row** — written here after the fact, which is why the commit hash is
real rather than `pending`. Both affected suites run green.

- Files: agent.py, api.py, runner.py, tests/test_agent.py, tests/test_routines.py, BACKLOG.md, legacy/BACKLOG.md, TRACKER.md
- Status: shipped
- Commit: 8b83d97

## 2026-07-29 — One home per fact, and a length rule
Post-1.0 doc rewrite, step 1. `HANDOVER.md`'s *The other documents* becomes
*Which file owns what*: the table gains a **must not carry** column, and three
writing rules land under it — say it once, name the failure rather than the
person, and records are frozen while rules are maintained.

The ownership split it makes explicit was already the design (`CHANGELOG.md`'s
own header states it); entries had drifted into carrying the design reasoning as
well, which is what made this file 3,418 lines. The operable test is new: *will
it still be true in three versions* decides between the two files.

Written first because every later step applies it rather than deciding it. The
section replaces 65 lines with 55 while adding two rules, which is the rule
demonstrated on itself.

- Files: HANDOVER.md, CHANGELOG.md
- Status: shipped
- Commit: pending

