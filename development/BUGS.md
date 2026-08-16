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

## B-2.0-79 · An interrupted turn exports as failed

**Found:** 2026-08-16, during the v2.0 Stage 5 loop three diagnosis.

An interrupted turn is exported with `status: failed`, even though the export
contract distinguishes failed, cancelled, and interrupted turns. The reason
text still says that cfc restarted while the turn was active, so the detail is
present but the status is flattened. Map `FailureKind.INTERRUPTED` to its own
export status while preserving the existing failed and cancelled output.

## B-2.0-78 · Export publication can replace a file created after name selection

**Found:** 2026-08-16, during the v2.0 Stage 5 loop three diagnosis.

Export destination selection checks that a generated name is free, but does not
reserve it before writing. A second writer can create that path before
publication, and `os.replace` then overwrites it. Claim the final name
exclusively before publishing the temporary file, so a collision refuses rather
than destroying another file.

## B-2.0-77 · Main can receive the shared Persona through the service boundary

**Found:** 2026-08-16, during the v2.0 Stage 5 loop three diagnosis.

The Context modal hides the shared Persona picker for Main, but
`ConversationService.set_persona` accepts a Main chat and the resulting plan
contains both the fixed Main persona and the shared Persona. Enforce the Main
rule in the service and make context-plan assembly ignore a stored shared
Persona for Main, so the UI is not the only authority boundary.

## B-2.0-76 · Attachment selection saves an unvalidated, non-canonical path

**Found:** 2026-08-16, during the v2.0 Stage 5 loop three diagnosis.

The attachment service persists a relative path without first proving that it is
a readable, in-boundary Markdown file or reducing equivalent paths to one
canonical identity. A later turn refuses a missing file, but the invalid
selection has already been saved. Validate and canonicalise before saving.

## B-2.0-74 · Export filenames use UTC instead of the promised local time

**Found:** 2026-08-16, during the v2.0 Stage 5 loop three diagnosis.

Export filenames use UTC while the product contract promises a local timestamp.
The export document already carries an offset-bearing time; use local time for
the filename as well, keeping the full offset-bearing value inside the document.

## B-2.0-72 · Adding an attachment freezes the interface while the vault is scanned

**Found:** 2026-08-16, during the v2.0 Stage 5 loop three diagnosis.

Pressing **Add attachment…** walks the whole WSL-mounted vault synchronously on
the Textual event loop. In the real vault this took about 2.7 seconds and gave
no progress indication. Move discovery off the event loop or otherwise keep the
interface responsive while the list is built.

## B-2.0-71 · Main sends `{{user}}` and `{{AI}}` literally

**Found:** 2026-08-16, during the v2.0 Stage 5 loop three diagnosis.

The example configuration promises substitution of `{{user}}` and `{{AI}}` in
Main's live profile, but the 2.0 package preserves and sends those tokens
literally. Decide whether personalisation belongs in 2.0; then either implement
the documented behaviour or correct the public configuration documentation.

## B-2.0-70 · A picker opens with a live choice under the cursor

**Found:** 2026-08-16, during the v2.0 Stage 5 loop three diagnosis.

Textual highlights the first picker row automatically. For Persona and User
Preferences that row is **None (clear selection)**, so pressing Enter without
moving clears a live choice. Add Trait and Add attachment similarly select the
first available file without an explicit choice. Opening a picker should not
silently perform a destructive or arbitrary selection.

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
