# Known bugs

Things that **don't work as intended** and haven't been fixed yet. Not debt, not
a design choice — a defect, flagged on purpose so it's fixed deliberately rather
than rediscovered.

The line between this and the neighbours:

- **BUGS.md** (this file) — it's *broken*. The behaviour is wrong, or a feature
  doesn't do what it says. Fix is owed; the entry records the symptom, where to
  look, and any leading hypothesis.
- **BACKLOG.md** — found in passing, deliberately deferred, and *still works*.
  Debt with reasoning, not a defect.
- **CHANGELOG.md** — what already shipped.

Each entry carries its **tracker id** in the heading — the id the playtest
report gave it, unchanged thereafter, so this file, the report and
`CHANGELOG.md` name one finding without three descriptions of it.

## When an entry closes

**Delete it whole and leave nothing behind here.** This file holds open entries
only. `workspace/TRACKER.md` keeps the resolution, `development/CHANGELOG.md`
records a shipped change, and Git history retains the deleted body. The
reasoning is in `HANDOVER.md`, *Which file owns what*.

---

## B-2.0-118 · An unselected context row opens an empty preview

**Found:** 2026-08-22, during the v2.0 Stage 6 loop one diagnosis.

Selecting a Persona or other category row with no current value opens a modal
whose entire body says `none selected`. The row already communicates that
state, so the preview adds no information. Choose the intended picker or
empty-state action while reconciling the related Context-modal interaction
design.

## B-2.0-113 · Direct-file grep ignores cancellation

**Found:** 2026-08-22, during the v2.0 Stage 6 loop one diagnosis.

The direct-file `grep` path accepts an already-cancelled callback and still
reads and scans the file. Add cancellation checks between bounded reads and
line units, then prove the real service path can deliver the signal while the
executor is running.

## B-2.0-112 · A repeated provider call ID is classified as an internal failure

**Found:** 2026-08-22, during the v2.0 Stage 6 loop one diagnosis.

A call ID repeated in a later provider batch reaches SQLite's uniqueness
constraint and becomes an internal cfc failure instead of malformed provider
evidence. Whitespace-only IDs and function names are also accepted. Validate
the complete turn before persistence and reject stripped-empty envelope fields.

## B-2.0-111 · Tool character ceilings are not hard bounds

**Found:** 2026-08-22, during the v2.0 Stage 6 loop one diagnosis.

The truncation notice is appended after the per-result ceiling, and the
aggregate budget is checked before rather than reserved for the result. A
bounded result can therefore exceed the promised per-result or turn-wide
character limit. Reserve space for the notice and pass each call the smaller
of its own allowance and the remaining turn budget.

---

## B-2.0-97 · Four readable-vault dialogs can hide their Close or Cancel action

**Found:** 2026-08-19, during the v2.0 Stage 5 loop four second-run diagnosis.

`SourcePreviewModal`, `ContextModal`, `SourcePickerModal`, and
`AttachmentPickerModal` use the same height-capped, non-scrolling dialog shape.
At a small terminal, a long source or a sufficiently large picker can place
the Close or Cancel row outside the visible dialog with no scrolling owner.
Give the outer dialog the bounded scrolling and keyboard ownership needed to
keep both its content and exit action reachable.

## B-2.0-96 · An unreadable vault parent is reported as a missing vault

**Found:** 2026-08-19, during the v2.0 Stage 5 loop four second-run diagnosis.

When the configured vault's parent directory is unreadable,
`Path.exists()` returns `False` and discovery reports that `VAULT_ROOT` does not
exist. The vault is present; the refusal names the wrong cause and tells Cas to
create something that is already there. Probe the configured root with an
operation that distinguishes `ENOENT` from permission failure, then keep the
bounded refusal and its real correction route.

---
---

## B-11 · A wiki page deleted from the vault stays in the recall index

**Found:** 2026-08-03, by reading during the v1.6.3 triage. Live on the
database when found.

**Symptom:** none. That is the entry. `/recall` can return and cite a wiki page
that no longer exists in the vault, and nothing anywhere says so.

**Cause:** `import_wiki.run_import` only inserts and updates. It walks the wiki
directory and writes a row per frontmatter id; there is no reverse direction.
The only deletion path in the module is `--wipe`, which drops the whole corpus,
and `/update db` never calls it. So a page deleted, renamed to a new id, or
moved out of the top level keeps its `provider='wiki'` session, its message, its
chunks and its vectors forever.

**Three live examples**, all added during earlier playtests and later deleted or
moved (each traceable in the vault's own git history), eight chunks and eight
vectors between them:

| id | title still in the index |
|---|---|
| `20260730113100` | cfc Silent Bug Catalogue (Scars) |
| `20260731094644` | *(untitled)* |
| `20260801140001` | CFC Splash Screen Architecture |

**Nothing detects it, and the thing that looks like it would does not.**
`/update db`'s stale-chunk check (`db.find_stale_chunks`) looks for chunks whose
*message row* is gone or mis-attributed. Here the message row is healthy — only
the file behind it is gone — so it sees nothing and `/update db prune` will not
touch them. `backfill.clear_wiki_stale` only removes a marker file.

Recall is wiki-only by standing decision 9, so these rows are not in a corpus
nobody reads: they are in the one corpus `/recall` searches.

**Shape of the remedy.** `_import_pages` already walks every live page, so it
already knows the full set of ids that should exist — the same function
`B-1.6.2-01a` taught to carry skipped filenames forward can carry the
disappeared ids forward the same way, with `commands.do_updatedb` rendering
them. It belongs there rather than in `db.find_stale_chunks`, which has no
business knowing what a vault is.

**One decision sits on top of it, unmade:** whether `/update db` removes those
rows or only reports them, leaving `/update db prune` to remove them. The
existing stale-chunk path already chose report-then-prune, and matching it is
the conservative answer — a delete reaching the vector index is standing
decision 14's territory, and doing it silently inside a routinely-run command is
what this project writes scars about. Proposed, not settled.

**Parked to v2.0 with `W-07`, deliberately.** This is chunk/vector-schema code
that the DB-layer rework replaces, `HANDOVER.md` already says to treat that
schema as in flux, and real `ON DELETE CASCADE` sits in *rejected designs* for
the same reason. Nothing about the symptom is felt in use — the fix protects
retrieval quality on a corpus that is being rebuilt.

**The transferable half, which is why the entry exists at all:** an importer
that only ever adds is a one-way sync, and a one-way sync accumulates rows for
things that no longer exist without ever failing. That is true of whatever
store replaces this one. Carry the sentence, not the patch.

---
