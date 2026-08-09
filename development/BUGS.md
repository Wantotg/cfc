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

## B-2.0-26 · An identical completion carrying an all-absent `Usage` refuses as a conflict

**Found:** 2026-08-09, during the v2.0 Stage 3 loop one playtest.

**Symptom:** `Usage(None, None, None)` and `usage=None` both round-trip from
SQLite as no usage, but an identical repeat of the first spelling is refused
as a conflicting finalisation. Repeating the second spelling is accepted.

**Cause:** the three optional usage counts deliberately distinguish absent
counts from reported zeroes, but the all-absent `Usage` value is stored as
three `NULL` columns and read back as `usage=None`. Content-exact idempotency
then compares the submitted value with a representation that has lost the
distinction.

**Shape of the remedy:** preserve whether usage was supplied, or decide that
an all-absent `Usage` is not constructible. Pull this into the loop that makes
the HTTP adapter reachable, where a real response naturally produces the
value through three optional fields. Content-exact finalisation remains the
chosen rule; a conflicting answer must not be silently discarded.

---

## B-2.0-27 · A populated non-cfc database is diagnosed as empty

**Found:** 2026-08-09, during the v2.0 Stage 3 loop one playtest.

**Symptom:** an existing SQLite target with tables but no `application_id` is
classified as `EMPTY_OR_ARBITRARY` and receives the same advice as a truly
empty file: preserve anything wanted, then move or remove it so cfc can create
a fresh database.

**Cause:** the refusal classifier treats a missing application marker as the
empty-or-arbitrary case. Most SQLite files never set `application_id`, so the
branch combines a zero-byte file with a populated database whose ownership is
unknown. The foreign-application branch catches only files that voluntarily
set a non-zero marker.

**Boundary:** Stage 2's database-path validation prevents the live v1.9.1
database from reaching this code; the reachable case is a copy or a database
pointed at explicitly. The diagnosis is still wrong, and moving a populated
database has a different recovery consequence from moving an empty file.

**Shape of the remedy:** inspect whether the target contains meaningful SQLite
content and give populated unknown databases their own refusal and recovery
advice without weakening the validate-before-mutation rule.

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
