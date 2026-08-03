# Changelog

What changed and when. Most recent at the top. **Entries through v1.0 are frozen
in [`legacy/CHANGELOG-pre-1.0.md`](legacy/CHANGELOG-pre-1.0.md)**; entries older
than the 2026-08-01 triage boundary are frozen in
[`legacy/CHANGELOG-post-1.0.md`](legacy/CHANGELOG-post-1.0.md).

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

## 2026-08-03 — Correct the stale vault-key reference (`D-14`)
`ui.vault_relative`'s docstring still named `config.VAULT_PATH` as the thing
it avoids reading — stale since the `W-0.9.1-01` rename made `VAULT_ROOT` the
actual vault key. Wording only: the function, its callers, and `export.py`'s
intentional legacy `VAULT_PATH` fallback are untouched.
- Files: ui.py
- Status: shipped
- Commit: df2995c

---

## 2026-08-03 — Record chat turn kind in provider errors (`D-17`)
`errors.log`'s `chat` origin said a failure happened during a chat turn, but
not which action — an ordinary send, `/swipe`, `/continue` or an OOC
direction all wrote the same header. `_run_turn`'s own `kind` is now threaded
through `handle_turn_error` into `errorlog.log_error`'s new optional `kind`
argument, which renders as a separate `turn <kind>` header component for
exactly those four actions. Title (`where="title"`) and routine
(`where="routine <id>"`) failures are untouched — they have no invented
chat-turn kind. `errorlog.py` stays dependency-free and append-only, and a
private chat's refusal (at the write, before any of this) now also covers the
new field.
- Files: main.py, errorlog.py, tests/test_turn_paths.py, tests/test_private.py
- Status: shipped
- Commit: e391ef7

---

## 2026-08-03 — Name skipped wiki pages in `/update db` (`B-1.6.2-01a`)
A missing-id skip warned with a count only, so knowing *which* top-level page
to fix meant opening the wiki directory and guessing. `import_wiki._import_pages`
now returns every skipped filename (relative to the configured wiki directory)
alongside the count, and `commands.do_updatedb` names all of them in its
existing yellow partial-import warning. Eligible pages still import and the
chat-index pass still runs — this is diagnostic evidence, not a new fatal or
repair path.
- Files: import_wiki.py, commands.py, tests/test_memory_states.py
- Status: shipped
- Commit: 64d995a

---

## 2026-08-03 — v1.6.2 triage — The hub says what its `Ctx` column means (`B-10`)
The one finding that blocked the v1.6.2 tag, and it came from reading the
version's own `Concept.md` against the shipped code rather than from the
playtest. Step 3 asks for the narrow `N / ?` cell **and** for the hub to
explain that it means the token count is known and the model's limit is not.
Only the cell shipped: `h` at the hub documented the keys and the connection
light and said nothing about the column, so the one screen that renders the
new state in an abbreviated form was also the one screen that never defined it.

`hub.print_hub_help` now carries a `Ctx` legend beside the light's. Its example
cells are rendered by `_context_cell` itself — the same function the table's
cells come from, the way the light's legend is rendered by `connection_light`
— so this is a producer/parser pair closed by construction rather than a
seventh row on `HANDOVER.md`'s hazard table. Both examples are computed against
an unknown model id, which has no configured limit, so the legend is identical
on every machine and pins nothing from `MODELS` into the golden baseline
(`B-1.6-05`'s scar); the percentage state, which would need a real configured
model, is described in words that name no format. `tests/test_hub.py`
round-trips the legend against the renderer instead of against the literal
`8 / ?`, verified by printing a literal in the help and changing the cell's
format.

The entry lands one commit after the change rather than in it: the fix was
committed and pushed before the changelog was written.
- Files: hub.py, tests/test_hub.py
- Status: shipped
- Commit: 86a089e

---

## 2026-08-03 — v1.6.2 — Truthful boundaries (`B-1.7-05`, `B-1.7-01`, `D-1.7-02`, `D-1.7-04`)
Four independent repairs, each correcting an existing boundary rather than
adding new surface.

`mover._ensure_id` used to serialise an empty frontmatter `id:` beside the one
it generated, so a filed wiki page carried two id lines and `import_wiki` —
reading the later, empty one — silently skipped it out of the index. The
empty key is now dropped before the generated id is written; a filing-to-import
test drives the real boundary against a real db rather than mover's own
frontmatter.

`api.stream_response()` drew a reasoning panel for whitespace-only
`delta.reasoning`, unreadable and indistinguishable on screen from a real
think. The panel now gates on readable content, the same check
`agent._render_reasoning` already used on the tool path; the raw `reasoning`
string returned to the caller is untouched, since it's still what tells a
reasoning-only completion apart from a truly empty one.

An unconfigured model's context usage used to read differently on every
screen: a bare count in the header and `/status`, nothing at all post-turn.
All three now say the same thing — `N tokens · limit unknown` — through a
shared `commands._context_value` helper for the two full-width views and
`print_context_bar`'s own third branch for the post-turn line; the hub's Ctx
column says `N / ?` for the same case. `models.context_limit()` stays the one
source of whether a limit exists.

`/move` and `/outbox` described the same top-level file as two unrelated
things — "loose" was never defined, so a shared file read as the two screens
disagreeing rather than answering different questions about it. Both screens
now name what they list, and `/outbox` explains once that a top-level
Markdown file can appear in both because `/file` follows its proposed
destination while `/move` asks you to choose one. `mover.loose_files()` and
`list_proposals()` are unchanged — display only.
- Files: mover.py, api.py, commands.py, hub.py, README.md,
  tests/test_mover.py, tests/test_api_stream.py (new), tests/test_hub.py,
  tests/test_turn_paths.py, tests/test_private.py, tests/golden_baseline.txt
- Status: shipped
- Commit: 0f3c122

---

## 2026-08-02 — v1.6.1 — Wiki reads refuse leftovers; the first model-context experiment (`B-1.6-01`, `D-1.6-03`)
Three contained changes. `/wiki diff` and `/wiki status` now refuse a
remainder they cannot use, on both the chat quick form and the wiki screen,
before any git call — a typo like `diff al;;` used to run against the default
scope and print a correct-looking answer about the wrong corpus. Both readers
now share one acceptance decision (`commands._wiki_diff_accept` /
`_wiki_status_accept`); the screen's diff handler reads the scope back from
`show_wiki_diff`'s return instead of re-parsing the same argument a second
time to decide whether to arm its review. `commit` is untouched — its
remainder is still the free-text message.

`/update db`'s hidden-wiki notice now names both outcomes in the one line
before the index spinner: the wiki re-import was skipped by the configured
vault scope, and eligible chat messages will still be indexed. It used to name
only the skip, one line before a spinner and a chunk count that looked like
they contradicted it.

The first model-context experiment: `recall.py` compacts a run of more than
one blank line to one, but only in the local excerpt text used to build
`/recall`'s dedicated, tool-free synthesis request — never in the hit dicts,
never anywhere else. It is fail-open: any fenced or indented code, or
Markdown block structure (headings, lists, blockquotes, tables), or a fence
that isn't cleanly closed, leaves the whole excerpt exact rather than guess.
`/remember`'s envelope and every stored or retrieved representation are
unaffected — this is the one narrow boundary in `Concept.md`'s inventory.
- Files: commands.py, screens.py, recall.py, tests/test_screens.py,
  tests/test_memory_states.py, tests/test_recall.py
- Status: shipped
- Commit: 2c4df49

---

## 2026-08-02 — Stop v1.6's two new config lines pinning config.py (`B-1.6-05`)
The `config.py` scar, twice, in the release that added the surfaces: `/config`
grew a `Vault scopes` row and a `Names` row, and `tests/golden.py` pinned
neither — so the baseline described whoever's `config.py` recorded it, and
`check` went red the moment Cas declared his own scopes and display names, on
two lines that say nothing about the source. `capture()` now pins
`VAULT_SCOPES` empty and both display names absent, beside the `VAULT_ROOT`
and `AUTO_EXPORT` pins that already exist for this reason. Scopes are pinned
*empty* rather than to a fixture set because `capture()` repoints `VAULT_ROOT`
at the fixture vault, so any real declaration resolves to directories that
don't exist there and renders as invalid — the scope display is pinned
directly in `tests/test_screens.py` instead, which is where a policy rendering
belongs. Same defect in `tests/test_pools.py`: the new First Message test
patched `USER_DISPLAY_NAME` only while asserting on the `{{AI}}` default, so
it read the live config for half its expectation. Both restore the recorded
baseline untouched, which is the evidence they were leaks rather than
intended changes.
- Files: tests/golden.py, tests/test_pools.py
- Status: shipped
- Commit: 20d4e14

---

## 2026-08-02 — v1.6 — A governed view of shared vault material (`D-16`)
A new `vault.py` is the one authority for two things that share a frontmatter
reader: an optional, named partition of the vault (`VAULT_SCOPES`, resolved
against `VAULT_ROOT`) deciding what a model-facing surface may reach, and a
read-only frontmatter `title` label for cfc's own file pickers. No setting
preserves today's fully-open behaviour; a hidden ancestor always wins over a
nested exposed scope, checked against both the caller's literal request and
its fully resolved destination, so a symlink can't launder access either
direction. `paths.py` remains the filesystem jail — this is a narrower,
separate question, enforced inside `tools.dispatch`'s `list_dir`/`read_file`/
`grep`/`write_file` (chat and routine contexts alike, since a routine's
`ToolContext` is ungated and reaches the same dispatcher), `commands.do_attach`,
and the `/recall`/`/remember`/`/update db` wiki-corpus seam — which reports the
policy state rather than letting a hidden corpus look merely empty. An invalid
scope declaration fails closed only for paths actually inside `VAULT_ROOT`;
`/wiki`, `/file`, `/move` and notes maintenance are human-only and untouched.
`/config` gains a scope-count row and a `scopes` detail view; the title label
reaches every picker that already showed a filename (attachment completion and
`/status`, outbox/filing, `/move`'s loose files, the wiki screen's changed-file
picker) without any of them learning frontmatter separately — a path remains
the only thing ever inserted, stored, or accepted back.

A second, independent module (`names.py`) adds `{{user}}`/`{{AI}}`
personalisation: two exact, case-sensitive tokens, substituted in one pass over
the source text so a configured name's own braces can never be read as a second
placeholder. Applied only at the loaders that already own a shared,
model-facing instruction file — `pools.load`/`load_first_message` (system
prompts, personas, traits, First Messages), `mainchat._read` (Main's live
profile and creation bundle), and `runner.py`'s routine task prompt, composed
with `fill_placeholders` so `{{user}}`/`{{AI}}` are known tokens excluded from
its unfilled-placeholder warning rather than two competing scans. Live layers
(traits, Main's profile) are re-personalised every read; existing snapshot
surfaces (a First Message, a routine transcript) keep what they froze. An
invalid configured name is a visible `/config` error and leaves its token
literal rather than guessing.

Also `D-16`: `runner._mark_transcript` now rolls the connection back when its
best-effort marker save fails, before swallowing the error — previously the
marker's own partial INSERT/UPDATE could sit uncommitted on the connection and
ride along on whichever unrelated `save_message` committed next. Verified by
disabling the rollback and watching a stray row survive a later save.
- Files: vault.py, names.py, tools.py, commands.py, complete.py, screens.py,
  pools.py, mainchat.py, runner.py, config.example.py, tests/test_vault.py,
  tests/test_tools.py, tests/test_attach.py, tests/test_complete.py,
  tests/test_mover.py, tests/test_memory_states.py, tests/test_screens.py,
  tests/test_pools.py, tests/test_first_message.py, tests/test_mainchat.py,
  tests/test_routines.py, tests/golden_baseline.txt
- Status: shipped
- Commit: d73b7ec

---

## 2026-08-02 — The NULL-kind backfill commits the write it makes (`B-09`)
The guards added earlier today stopped `_migrate_messages` writing when it
had nothing to write, but the commit stayed gated on `added or wrote_marker`
— which does not include the NULL-kind backfill. A database whose `kind`
column already exists while some rows still hold NULL therefore ran the
`UPDATE` and never committed it: the write rolled back on close, every
subsequent `db()` re-ran it, and the connection was returned holding an open
write transaction for its whole life. That is B-1.5.1-01a's retained writer,
surviving inside its own fix, on the one fixture the fix's test claimed to
cover. One `wrote` flag now tracks all three writes. The test failed to catch
it because it read the backfilled value back on the connection that made it,
which sees its own uncommitted transaction — so the new assertions check
`conn.in_transaction` and re-read after a reconnect, and the same pair was
added to the legacy-routine-session fixture, which had the identical blind
spot without the identical bug.
- Files: db.py, tests/test_schema.py
- Status: shipped
- Commit: f93b341

## 2026-08-02 — The routines screen shows each routine's scheduler state (`D-1.5.1-01c`)
`/config` could report a due routine and point at the routines screen, but
that screen only ever showed last-run status and review state — it couldn't
answer the question `/config` raised unless you already knew which routine
to `show`. `screens._render_routines` now captures one clock per render and
passes `schedule.assess(routine, now).state` — the assessment's compact
state, verbatim, never `reason` text, a timestamp comparison, or a
re-derivation of trigger logic — into a new `Schedule` column on the wide
table and a `schedule` line on the narrow layout. This is deliberately
separate from the hub's compact, coloured Schedule light (`B-0.9.1-04`):
this screen has no colour of its own to keep in step with it, and `show
<routine>` remains the one place for `Assessment.reason`'s full sentence.
- Files: screens.py, tests/test_screens.py
- Status: shipped
- Commit: 49e8df2

## 2026-08-02 — Headless scheduling gets bounded lock patience and per-routine containment (`B-1.5.1-01a`, `B-1.5.1-01b`)
`db.db()` now takes an explicit `timeout=` (SQLite's busy-wait), defaulting
to the same 5s every interactive and `:memory:` caller always had.
`schedule._run()` opens the shared routine connection with a 30-second
timeout — only once due work is already known, so the idle `--run-due` tick
stays database-free — because a scheduled tick is exactly the moment an
ordinary chat session is most likely to be holding the write lock, and
nobody is sitting at a REPL waiting on it. If that open still fails, every
selected routine gets its own `failed` run-log record naming the database
error (no provider call is made), and if the run-log append itself fails
too, that is reported plainly rather than implied. Each call to
`run_routine()` is now individually contained: an unexpected escape (the
outcome boundary from the previous entry doesn't cover, by construction,
anything that isn't itself) rolls back the shared connection, gets one
fallback log record from the scheduler, and lets the tick continue to later
selected routines rather than ending it — a normal return from
`run_routine()`, including its own `failed`, is never double-logged. The
whole-tick lock, the existing retry policy, and the final non-zero CLI exit
on any failure are all unchanged.
- Files: db.py, schedule.py, tests/test_schedule.py
- Status: shipped
- Commit: 4e747bb

## 2026-08-02 — The routine run log is authoritative across every runner exit (`B-1.5.1-01b`)
`runner.run_routine` used to leave session creation and task persistence
outside any try/except, and its failure/cancellation handlers tried to save
an explanatory transcript marker *before* appending the run-log record —
so a second SQLite error at either point escaped uncaught (setup) or
silently swallowed the run record (the marker), and a routine that had done
real work looked identical to one that never ran. The whole run — session
creation, task persistence, the tool turn, and final persistence — is now
one outcome boundary: exactly one `append_log` call happens on every path
out, using whatever `touched`/`session_id` evidence is already known, and
the transcript marker (`[routine failed]`/`[routine cancelled]`) is written
only afterward, best-effort, with its own failure swallowed. On success, the
final transcript is committed before `ok` is appended; if that commit fails,
the run is logged `failed` with the known touched-file evidence rather than
leaving an `ok` record for a transcript that never made it to disk.
`errors.log` stays narrowed to provider HTTP errors, unchanged.
- Files: runner.py, tests/test_routines.py
- Status: shipped
- Commit: 076c806

## 2026-08-02 — A current-schema database open no longer retains a writer (`B-1.5.1-01a`)
`db.py`'s two migrations ran an `UPDATE`/`ALTER TABLE` on every connect
regardless of whether anything needed changing — and SQLite takes the write
lock the moment an `UPDATE` opens, whether or not its `WHERE` matches a row.
On a populated, current-schema database (the overwhelmingly common connect)
that meant every `db()` call briefly contended for a lock it had no use for,
which is what let a scheduled tick opening the database while a chat held it
exhaust its five-second wait and die with no routine run at all. Session
columns are now added only when `PRAGMA table_info` says they're missing; the
NULL-kind backfill and the legacy-routine-session backfill are each preceded
by a `SELECT` probe and only run (and commit) when there is real work. A
legacy database still gets both columns and both backfills unchanged; a
current populated one now opens with `conn.in_transaction` false throughout.
- Files: db.py, tests/test_schema.py
- Status: shipped
- Commit: eb8db69

## 2026-08-02 — Runtime prose says Cooking for Cats; a private chat's own claims are honest (`W-0.9.1-03`, `W-0.9.1-04`)
`ui.DISPLAY_NAME` is the one source every human-facing "cfc" now reads
from — the hub's quit line, the config/wiki/routines screen titles, the
wiki commit notice, the governor's dim nudge line, the headless CLI's usage
banner and lock message, a startup config warning, and `/recall`'s
standalone-script message. `preflight.py` and `errorlog.py` keep their own
local literals on purpose (their import boundaries exist precisely to stay
clear of `ui.py`); `[cfc direction]`, the tool-loop budget notes, a
routine's own system prompt, and every path/identifier/CLI/config name are
untouched. A source-inventory test (`tests/test_ui.py`) derives every
literal "cfc" left in source and checks it against a two-entry allowlist —
both explicitly reasoned, both re-verified as still-matching rather than
trusted — so a new one slipping in fails loudly.

The hub's private-chat line drops "in memory, nothing written to disk" for
the compact claim that actually matters: "temporary, not saved locally."
The full entry notice (printed on opening one) now states five things
plainly — the local destruction boundary, that this is *local* privacy
only and the selected provider still sees the same messages any other chat
sends it, blocked model file-writes, the one explicit `/export` exception,
and that `/database on` is read-only for this chat (`/recall` reaches
existing memory; nothing said here is added to it). Copy only — no private-
chat path, permission or hand-off behaviour changed.
- Files: ui.py, hub.py, screens.py, commands.py, main.py, models.py,
  recall.py, runner.py, schedule.py, tests/test_ui.py,
  tests/test_private.py, tests/test_turn_paths.py, tests/golden_baseline.txt
- Status: shipped
- Commit: 9369233

## 2026-08-02 — Routine surfaces teach a routine-run reference, never a chat session number (`W-0.9.1-07`)
`history`, a completed `/routine` command, the routines screen's generated
help and `open` all named a run by its backing chat session number —
`session #45` — which is what it is internally, not what a person reading a
routine surface should have to learn. Every one of them now shows
`<routine-id>/<run-number>` instead, and `open` resolves it through the
named routine's own parsed log record (`routines.find_run`) before
`db.routine_session` makes the final provider-level check. The reference is
threaded through as data — `routines.append_log` returns the `run_number`
it allocated, and `runner.run_routine` hands it back as a fourth return
value — so no presenter reconstructs it by re-reading the log.

The old bare numeric session id still opens a transcript — unadvertised,
provider-checked compatibility only, for anything typed from before this
existed. Nothing new ever prints that form.
- Files: routines.py, runner.py, commands.py, schedule.py, screens.py,
  main.py, tests/test_routines.py, tests/test_screens.py,
  tests/golden_baseline.txt
- Status: shipped
- Commit: 68d89fd

## 2026-08-02 — A retry-limited routine no longer reads green in the one column a person checks first (`W-0.9.2-02`)
`schedule.assess()` is the one place that now decides a routine's schedule
state — `due`, `settled`, `not yet`, `command`, `disabled`, `invalid`,
`unreadable`, `held` or `retry limit` — with `why_not_due()` kept as an exact
compatibility view over its `.reason` for `due_routines`. Before this, the
hub's `Last run` cell was coloured by "is anything owed", so a routine that
had spent its whole retry budget on failures read the same reassuring green
as one that had simply settled cleanly — the actual bug is that "owed" and
"healthy" were one colour.

The hub's Routines panel now renders three separate fields instead of one:
`Last run` (a timestamp, never coloured), `Result` (the recorded outcome,
including review — failed still red), and `Schedule` (the compact
assessment, coloured by due-ness alone). A retry-limited routine now shows
`failed` in red under Result and `retry limit` in Schedule — an honest,
separable pair, rather than one cell trying to say both. `show <routine>`
prints the full reason sentence, and the config screen's routine-attention
count reads `assess(...).due` directly instead of its own due check.
- Files: schedule.py, hub.py, screens.py, tests/test_schedule.py,
  tests/test_hub.py, tests/test_screens.py
- Status: shipped
- Commit: 31ae418

## 2026-08-02 — A routine's run log carries active elapsed time and a stable run number (`W-0.9.2-01`, `W-0.9.1-07`)
A machine suspend used to inflate a run's logged elapsed time to the length of
the outage — `runner.py` measured `datetime.now() - started`, and a frozen
laptop counts as elapsed exactly like real work does. `runner._active_clock`
(monotonic, injectable) now feeds one `elapsed_seconds` field to `append_log`
from the success, failure and Ctrl-C paths alike, instead of three branches
each formatting `"({elapsed:.0f}s)"` into `detail` by hand; the wall clock
still stamps the title, the log timestamp, the prompt date and every
scheduler calculation.

Every run also gets a `run_number`, allocated inside `append_log`'s own
atomic append — never from a caller's separate read of history, which is
what would let two callers race to the same number. A log written before
this field existed derives its numbers oldest-first on read, and a fresh
append continues from the highest number already on file, explicit or
derived, so a log that transitions from old lines to new ones never repeats
or skips a reference. `session_id` stays an internal field; the `<routine-
id>/<run-number>` a routine surface will show a person is next.
- Files: routines.py, runner.py, tests/test_routines.py
- Status: shipped
- Commit: 040d2ab

## 2026-08-01 — `preset_params` is a list of parameter names, and said otherwise (`B-1.5-02`)
`config.example.py` and `models.py`'s field table both described
`preset_params` as "the `PARAMETER_PRESETS` keys verified for this id" — it
holds `"temperature"`/`"top_p"`, the parameter names, never a preset name.
A reader following the shipped instruction writes `preset_params=["creative"]`
and cfc refuses to launch: `models.load()` runs at import, nothing catches
`ModelConfigError`, so the only documented way into v1.5's presets is a
traceback. Loud rather than silent, which is the one thing that went right.

Blocked the tag. `Concept.md`'s *Named Parameter presets* gives
`config.example.py` the job of teaching the new record, and the private
roadmap's preset entry turns on the declaration being writable at all; the
feature was reachable only by ignoring its own documentation. Both comments
now say *parameter names, not preset names*, and the config file carries a
two-line worked pair — a model declaring `temperature`, a preset setting it —
driven through `models.compatible_presets` before being written down, along
with what stops working when the preset grows a second parameter.

Nothing checks prose, and no test could have caught this: the shipped
`MODELS` records declare no `preset_params` at all, so the file's *code* was
always valid. Second time `config.example.py` has shipped wrong instructions
(`B-0.9.1-02`, twelve retired `:` commands) — standing decision 13's note
that it is the only shipped file that instructs a human, and that nothing
verifies it, now has a second instance under it.

- Files: config.example.py, models.py
- Status: shipped
- Commit: f37fe95

## 2026-08-01 — v1.5 — Conversation control (`W-1.3-02`, `W-1.3-03`, `W-1.4-03`, `W-1.3.1-05`)
`/swipe` re-answers the latest ordinary chat turn — same user row, current
model/tools/preset — and `/undo` retracts it entirely. Both classify the
turn from stored rows and ids only (`db.classify_latest_turn`), refuse a
turn with no user row or one a later `/continue`/OOC already answered
twice, and refuse — never silently drop — a turn that requested a mutating
tool (`tools.is_mutating`), since deleting the record can't undo a real
write. Pruning is index-first and atomic (`db.prune_turn`, sharing
`db._atomic_delete` with a refactored `delete_session`), and streaming and
tool turns end through the one shared path (`main._run_turn`'s new `"swipe"`
kind), so neither can drift from the other.

Chat ids are now choosable: `c` at the hub and `/new <id>` create an
ordinary chat at a caller-picked positive id, refusing any occupied
`sessions.id` — every session kind shares the namespace, so a hidden wiki
or routine row collides too. `d` at the hub joins `/delete chat [<id>|main]`
on one resolver (`db.resolve_delete_target`, identity-based — Main is never
matched by its editable title) and one confirmation that requires typing
the target back, not a bare y/n.

Named sampling presets (`temperature`, `top_p`) are configured in
`PARAMETER_PRESETS` and declared per model via `MODELS[id].preset_params` —
a verified fact like `tools`, never guessed, validated at startup
(`models.py`). `/preset [name|default]` selects one for the open chat;
selection is session-local, shown in `/status`, and cleared with a reason on
a model switch that doesn't declare every key it uses. The selected dict
reaches every call in `agent.agent_turn`'s tool loop and `api.stream_response`
alike, and nothing else — title generation, recall synthesis and routines
are structurally unreachable from it.

- Files: db.py, hub.py, main.py, commands.py, tools.py, models.py, api.py,
  agent.py, parse.py, complete.py, config.example.py, tests/test_schema.py,
  tests/test_hub.py, tests/test_models.py, tests/test_complete.py,
  tests/test_turn_repair.py, tests/golden.py, tests/test_mainchat_turns.py,
  tests/test_parse.py
- Status: shipped
- Commit: 979370b

---

## 2026-08-01 — A chat whose first turn never answered can still be titled (`B-07`, `B-08`, 1.4.1 triage)
Both findings are v1.4.1's own, both were found by reading rather than
reported, and neither blocked the tag — Cas's call to fix them here rather
than carry them.

**`B-07`.** `_finish_turn`'s title gate was `turn_count == 1` alone. The user
row is written *before* the request goes out, so a provider error on the first
turn advanced that count without anything being said back, and the chat could
never be titled afterwards — session 185 of the playtest, a 503 eighteen
seconds in, is `(untitled)` permanently. The rule it was implementing is *the
first ordinary chat turn that produced an answer*, which needs a second
durable count: `db.count_chat_answers`. The gate now reads
`turn_count == 1 or count_chat_answers(...) == 1`, and both clauses are
load-bearing in opposite directions — the first is the only one that survives
a session opening with `/continue` or an OOC direction off a First Message
(they answer without a user row), the second is what a failed turn costs
otherwise. Neither can reopen `D-13`'s retry: when a title *request* fails,
turn one still answered, so both counts have moved by the next turn. Each
clause was verified by deleting the other and watching the matching
assertions fail.

**`B-08`.** `tests/test_turn_paths.py` drives real turns through
`main._run_turn`, and two of its paths reach `errorlog.log_error` on their own
— a failed title and a provider error. Nothing redirected `errorlog.LOG_PATH`,
so four fabricated `· title / boom` records reached the live
`~/.cfc/errors.log` while v1.4.1 was being built. That log is the evidence base
for `B-01`'s absence watch, so a test writing to it manufactures the thing
being watched for. This is `D-08` reopened, one file over: the redirect and its
`assert "tmp" in ...` guard now match `test_model_revert.py`'s, verified by
removing it and watching the records land. The four records were deleted from
the live log by hand. One older artefact is deliberately left in place and
named here instead: a real nano-gpt 503 at 09:23:59 on 2026-08-01 attributed
to `model stub-model`, which the current suite cannot reproduce — deleting a
genuine provider body on a guess is the worse trade.

- Files: main.py, db.py, tests/test_turn_paths.py
- Status: shipped
- Commit: 196ed88

---
