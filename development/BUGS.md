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

## B-2.0-32 · The store's own errors defeat the turn-ending guards

**Found:** 2026-08-09, during the v2.0 Stage 3 loop two playtest.

`send_turn`'s recovery guards catch `ConversationStoreError`, but SQLite
errors such as a closed connection, full disk, or an external write failure
arrive as `sqlite3.Error`. An ordinary store failure can therefore escape and
leave the started turn active; the same mismatch can hide a `KeyboardInterrupt`
while its ending is being attempted.

**Shape of the remedy:** catch the store's actual database-error boundary when
ending an unfinished turn, and preserve interruption propagation even when the
ending write cannot be recorded. This is owed before Stage 4 background work;
reopen recovery remains the route when the store itself cannot accept a write.

---

## B-2.0-33 · An internal failure stores arbitrary exception text

**Found:** 2026-08-09, during the v2.0 Stage 3 loop two playtest.

The service stores `f"{type(exc).__name__}: {exc}"` for unexpected responder
errors, including the `repr` of an unrecognised responder result. A future
adapter could therefore persist a provider body, request detail, or credential
in `failure_reason`, which Stage 4 will render.

**Shape of the remedy:** make the service's internal evidence bounded and
cfc-authored, with no arbitrary exception or returned-object representation.
Keep provider-specific safe evidence typed at the adapter boundary.

---

## B-2.0-34 · Refusing a WAL-mode target leaves SQLite sidecars beside it

**Found:** 2026-08-09, during the v2.0 Stage 3 loop two playtest.

The read-only refusal classifier preserves the main database bytes, but opening
an existing WAL-mode target creates `-wal` and `-shm` beside it. The current
refusal tests use only rollback-journal databases and therefore do not see the
sidecars.

**Shape of the remedy:** decide whether classification reads the SQLite header
without opening the WAL database or whether the contract accepts these
sidecars. Do not delete them while another process may own the WAL.

---

## B-2.0-35 · A non-2xx response below 400 is reported as malformed JSON

**Found:** 2026-08-09, during the v2.0 Stage 3 loop two playtest.

The adapter treats only status `>= 400` as an HTTP failure. A redirect or other
non-success status below 400 falls through to JSON parsing and is stored as a
malformed-response failure, losing the status that explains the refusal.

**Shape of the remedy:** classify every non-success status as typed HTTP
evidence; reserve malformed-response evidence for a successful status whose
body cannot be used. Keep redirects disabled so a bearer header is not resent
to an unexpected destination.

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
