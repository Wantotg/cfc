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

## 2026-07-29 — The instruction files ship, as templates
Post-1.0 doc rewrite, step 7, and the last of it. `templates/` carries the seven
files cfc actually runs on with the personal half removed — six specialists, the
auto-loaded root file, and a README for the pattern itself.

**They are the real files, not a description of them.** `CLAUDE.example.md` was
a single-file *composite* of six, which meant the public copy and the working
copies were prose about the same decisions rather than the same prose — a diff
between them helped nobody, and it was on `HANDOVER.md`'s hazard list for
exactly that reason. Copying the working files and stripping the personal half
removes the second home instead of maintaining it.

The README carries what a template can't: why the split exists, the two ways of
handling the shared sections that don't work and the one that does, and the
one-home-per-fact rule without which six sessions is just more paperwork. It
also states the cost — each session starts without what the last one knew — as a
property rather than an omission.

`CLAUDE.example.md` moves to `legacy/` with a frozen header, since it is the
only description of the six-session arrangement that preceded the loop.
`README.md` links `templates/` from the top.

**The `.gitignore` patterns added in 6b are now anchored** (`/CLAUDE.md`, not
`CLAUDE.md`). Unanchored, they matched at any depth and silently swallowed seven
of the eight new templates — `git add -A` staged only the README and reported
nothing wrong. Caught by reading what got staged rather than by trusting it.

- Files: templates/ (new, 8 files), legacy/CLAUDE.example.md (was CLAUDE.example.md), legacy/README.md, README.md, .gitignore
- Status: shipped
- Commit: pending

## 2026-07-29 — Six sessions become a loop, and `D-05` closes by deletion
Post-1.0 doc rewrite, step 6b. The six `* CLAUDE.md` files are replaced by six
specialist files — one per step of a loop that goes round once per update, each
reading the file the previous step wrote and writing the next.

**`D-05` closes because the duplication is gone, not because something checks
it.** The shared half went to `HANDOVER.md` in 6a; the human context and the
loop table go in `CLAUDE.md`, which the harness loads automatically, so neither
costs a hop. What is left in a specialist file is only what makes that session
different from the other five — which is why they are 40 to 60 lines each
instead of 220 to 390.

The loop is six files and six specialists, one each. Cas's call: the earlier
sketch had a seventh (`Plan.md`) that two of his own notes assigned to different
specialists, and the update-wide scoping it named is already the drafter's job
and lands in the work order.

`.gitignore` covers the new names and the loop files. The old six are kept
locally, ignored, and are no longer read by anything.

- Files: .gitignore, TRACKER.md, CHANGELOG.md
- Status: shipped
- Commit: 9070509

## 2026-07-29 — The repo rules stop living only in gitignored files
Post-1.0 doc rewrite, step 6a. `Versions and releases` and `"Chat" means both
chats` move into `HANDOVER.md`, which every session already reads. They were
duplicated word-for-word across six gitignored instruction files, and the
release order — how this project ships anything — was reachable only by someone
who had those files.

Cas's call between three options for `D-05`. Duplication has already drifted
once; a shared file the instruction files point at is a pointer chain, and a
pointer chain is how instructions get skipped. `HANDOVER.md` is neither: it is
read in full by every session anyway, so the shared half costs no extra hop and
the instruction files keep only what makes each specialist different.

Standing decision 15 said *see `CLAUDE.md`* for its own content, which is a
public file citing a gitignored one. It is now self-contained. `HANDOVER.md` and
`README.md` no longer reference the instruction files at all.

Still duplicated until step 6b replaces them: the six `* CLAUDE.md` files carry
these sections too.

- Files: HANDOVER.md
- Status: shipped
- Commit: ddd41aa

## 2026-07-29 — The README stops claiming two things that stopped being true
Post-1.0 doc rewrite, step 5. Checked against the code rather than read for
tone, which is what turned up both errors.

**The picker was listed as hand-verified and has been covered since v0.9** —
`tests/test_hub.py` drives `pick_session` with a scripted keyboard.
`HANDOVER.md` caught this at v1.0 (`W-02`) and the README never did, which is
the coupling between the two files failing in the direction it always fails:
the human-facing copy keeps the old claim. **And the suite count said 25; there
are 30.** Both files were wrong about that one, so both are fixed.

The README now links `ROADMAP.md` and `CHANGELOG.md` from the top. It never
linked either — the file made the front door in step 3 was not reachable from
the front page.

Also documents the transient-status retry from `8b83d97`, which is user-visible
behaviour in the scheduler section: a 429/502/503 is re-rolled in place and does
not spend the day's retry budget, decided by status code and never by error text.

- Files: README.md, HANDOVER.md
- Status: shipped
- Commit: 65804cf

## 2026-07-29 — HANDOVER.md loses the retelling
Post-1.0 doc rewrite, step 4 — the *say it once* rule applied to the file that
states it. 903 → 795 lines with **no decision, rejected design, constant,
measurement or scar removed.**

What went: the connection light's two stories told at the length of the
investigation rather than the conclusion (90 lines → 50); `embed.py`'s and
`preflight.py`'s timeout pairs, which explained the same lesson twice and are
now one table with both rows; and *Open threads*, which had become the place
closed threads went to be described (82 → 38). A closed thread is a `TRACKER.md`
row and a changelog entry — the section says so now.

Two factual corrections while in there: *Two rules that generated most of the
above* listed four, and the `Q-01` and `W-07` ids were missing from the
paragraphs that are their bodies.

**It did not reach the ~600 lines estimated.** The remaining length is reference
— 16 standing decisions, 8 constants with their measurements, 12 scars — not
narrative, and cutting further would remove content rather than retelling.

- Files: HANDOVER.md
- Status: shipped
- Commit: 563bb48

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
- Commit: 99c3510

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
- Commit: 99c3510

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
- Commit: 99c3510

