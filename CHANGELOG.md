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

## 2026-07-23 — Add ROADMAP_BEYOND.md, a third planning tier
`WISHLIST.md`'s raw capture now has a step between it and `ROADMAP_PRIVATE.md`:
a gitignored `ROADMAP_BEYOND.md` groups related wishlist ideas into clusters
(what actually depends on or shares a mechanism with what) and orders within
a cluster, deliberately without version numbers — that's still a decision for
after v1.0. Ideas that were ready moved out of `WISHLIST.md` and got struck
there, including the file's whole former "Beyond v1.0" section, which is now
fully represented in the new file. A couple of wishlist ideas that actually
read as v0.8 scope (pre-1.0) were flagged rather than migrated, so they don't
get lost in the shuffle.
- Files: `.gitignore`; `WISHLIST.md` and `ROADMAP_BEYOND.md` are both
  gitignored, so they don't appear in this commit.
- Status: shipped
- Commit: pending

## 2026-07-23 — Split ROADMAP.md into public and private
`ROADMAP.md` now carries full detail (title, completion date, what shipped,
Cas's note) only for versions that have shipped; anything still ahead is a
bare title-only stub. The planning detail for v0.5–v1.0 moved to a new
`ROADMAP_PRIVATE.md`, gitignored — so a session no longer has to load design
reasoning for versions nobody's started yet just to get oriented, and the
repo's public copy is ready for the day it goes public. `CLAUDE.md`'s release
order now folds the private→public backfill into step 1 (commit and push).
- Files: `ROADMAP.md`, `.gitignore`; `ROADMAP_PRIVATE.md` and `CLAUDE.md`
  updated too but both are gitignored, so they don't appear in this commit.
- Status: shipped
- Commit: pending

## 2026-07-23 — Write down that "chat" means both chats
Cas's standing decision, recorded properly in `CLAUDE.md` and stated again at
the head of `HANDOVER.md`'s Private chat section so it reaches an LLM reading
the handover outside the repo.
- **A feature specified for chat is specified for private chat**, unless scoped
  to one explicitly. The point is not symmetry: it's that the alternative is two
  pipelines that diverge a little per feature and cost more to reconcile the
  longer they run apart.
- **The exception is privacy itself, and it is a refusal rather than a
  compromise.** A "mostly private" implementation is the worst available
  outcome, because its failure is invisible from the inside. Name the conflict,
  leave the private half unbuilt, let Cas decide.
- **The tell:** a feature that writes through the session's `conn` inherits the
  isolation for free. One that reaches for `DB_PATH`, a vault path or the
  network directly is the one to stop on — not to add an `if private` branch to.
- Files: CLAUDE.md, HANDOVER.md
- Status: shipped
- Commit: pending

## 2026-07-23 — Bring the docs up to the code after the backlog session
`BACKLOG.md` has no open entries left for the first time. Docs updated to match
rather than rewritten — the architecture didn't change, five specific things did.
- **`HANDOVER.md`**: a new section on the index being downstream of `messages`
  with nothing but code enforcing it; a new invariant (#11, deletes reach the
  index); the run-log collector; and **a new standing-hazard section** naming the
  format-written-here-parsed-there shape, which now has four instances and one
  failure mode — a silent false negative. Table included; add to it if you make a
  fifth.
- **`CLAUDE.md`**: the run log sits inside the write root and is refused
  separately; deletes cascade in code; `:updatedb prune`; suite count.
- **`README.md`**: `:updatedb prune` in the command table, and a paragraph in
  Memory on why deleting a session has to reach the index.
- Files: HANDOVER.md, CLAUDE.md, README.md, CHANGELOG.md
- Status: shipped
- Commit: a11fe7f

## 2026-07-23 — Say when a refused path was relative
`write_file` refuses a relative path — it resolves against the process working
directory, which is not a write root and is not predictable on a scheduled run.
Correct, but the message named a path the caller never typed
(`…/cfc/heartbeat.md is outside the allowed roots`), which reads as the jail
being misconfigured rather than the path being relative, and cost a full API
round trip per routine run to recover from.
- **The refusal is unchanged.** Resolving a relative path against the write root
  would make the tool's behaviour depend on how many roots are configured, and
  "the path you passed is not the path that was written" is the worst property
  the one mutating tool could have. The backlog entry asked for a better error
  over a reinterpretation; this is that.
- **The note is added only when the input was relative**, so an absolute path
  that misses the roots is not told it is relative.
- **A blanket refusal of relative paths would have broken working behaviour** —
  checked, not assumed: the cwd is inside a *read* root, so relative reads
  resolve and succeed today. It is not inside a write root, which is why this
  only ever bit `write_file`.
- Files: paths.py, tests/test_paths.py, BACKLOG.md
- Status: shipped
- Commit: 9afb646

## 2026-07-23 — Make deleting a session delete what indexes it
`delete_session`/`delete_message` removed messages and left `chunks` and
`vec_chunks` behind. No foreign keys enforce that link (`PRAGMA foreign_keys`
is 0), so nothing caught it. The reported symptom — a chunk with a dangling
`session_id` — was the least of three bugs.
- **A deleted conversation stayed in the retrieval index.** 143 vectors of
  deleted content were still searchable on the live db. A delete that leaves
  the text answering questions is not a delete.
- **Mis-attribution, the dangerous one.** SQLite reuses rowids at the top of a
  table, so a later message takes a deleted message's id and the stale chunk
  joins cleanly to it — `search` then cites it under a conversation the text
  never came from. 55 such rows, silent and indistinguishable from a real hit.
- **The backlog's two guesses were both wrong**: not `import_anthropic.py`, and
  not moot on the wiki db. The second is why it sat for eight days.
- **Fixed:** index rows dropped first, while the messages identifying them still
  exist; `delete_session` also sweeps chunks by `session_id` for ones whose
  message went separately. Vectors before chunks, and a failure there raises —
  a vector without its chunk is text in the index nothing can attribute.
- **Repair:** `find_stale_chunks`/`prune_stale_chunks`, surfaced as
  `:updatedb prune`. Plain `:updatedb` reports and removes nothing. Detection is
  exact, not heuristic: the message is gone, or `chunks.session_id` disagrees
  with `messages.session_id` — impossible in normal operation, since `chunk_new`
  copies it off the message and nothing ever reassigns it.
- Verified on a **copy** of the live db: 207 chunks and 195 vectors removed,
  idempotent, zero wiki rows touched, messages and sessions untouched. Six
  assertions confirmed to fail with the cascade removed.
- Real `ON DELETE CASCADE` is left to the DB-layer rework — SQLite can't add one
  without rebuilding the table.
- Files: db.py, commands.py, main.py, tests/test_schema.py, BACKLOG.md
- Status: shipped
- Commit: 8c69ef5

## 2026-07-23 — Make the run log say what a run wrote
`append_log(…, touched=())` rendered its fourth argument and no caller passed
one, so every line read as though the run touched nothing. When a run fails
halfway — a real, logged outcome since the ceiling fix — the first question is
which files it got to, and only the transcript could answer it.
- **A collector, not a second return value.** `agent_turn` takes an optional
  `touched` list; a routine passes one, chat passes nothing. Both of the turn's
  failure exits leave by *raising*, so a returned value couldn't carry the
  answer out of the case this is for. `run_routine` owns the list, which is
  also what lets it span a re-roll: history is rebuilt per attempt, files
  already written are not.
- **`tools.written_path()`** reads `write_file`'s own success line, so the tool
  loop needs no knowledge of tools and a refused write is never counted as one
  that happened. Producer and parse live together — same coupling hazard as
  `db._MARKER_RE` — and are pinned by round-trip rather than a literal, so
  rewording the message fails a test instead of silently emptying the field.
- **Rendering reworked after looking at a real line.** Names rather than full
  paths (every write shares the same 47-char root) and the list moved **last**:
  fields are separated by ` — ` and this vault's filenames contain that exact
  string, so a mid-line list had no findable end. `last_run()` is unaffected;
  `_LOG_RE` anchors at the head.
- Verified by breaking each link in turn — reworded result, disabled collector,
  runner not threading it, runner not logging it — each fails its own
  assertions.
- Files: agent.py, runner.py, routines.py, tools.py, tests/test_agent.py,
  tests/test_tools.py, tests/test_routines.py, HANDOVER.md, BACKLOG.md
- Status: shipped
- Commit: e194450

## 2026-07-23 — Stop `golden.py` exporting into the real vault
The script ends with `:q`, `:q` honours `AUTO_EXPORT`, so every `check` wrote
the fixture session into Cas's actual export folder. Nothing was corrupted, but
"the tests don't touch anything real" is load-bearing for how freely the suite
gets run, and it was false.
- **`VAULT_PATH` redirected on every module that holds one**, the same loop as
  `DB_PATH` — `export.py` and `commands.py` each have a copy, so patching one
  leaves the other on the real folder. Redirected rather than disabled: turning
  `AUTO_EXPORT` off would fix the side effect by making the export path
  untested.
- **`AUTO_EXPORT` is pinned on** instead of read from config, so the baseline
  covers the same code on every machine.
- **The baseline was pinning the real vault path** on `:config`'s output —
  the same class of bug as the API-key line that earned the `SCRUB` paragraph.
  Now `<ROOT>/tests/_fixture_vault`. One line changed; re-recorded.
- **`assert_not_real_vault`**, checked before the write like every other guard
  here. Written first to re-read config *after* the patch loop, which compared
  the fixture against itself — the guard caught its own bug; `REAL_VAULT` is
  now frozen at import.
- The harness now asserts a document actually landed, not just that the
  `[auto-exported: …]` line printed — `safe_export` swallows its own errors.
- Verified: two consecutive runs leave the real folder's mtimes unchanged.
- Files: tests/golden.py, tests/golden_baseline.txt, BACKLOG.md
- Status: shipped
- Commit: 08a9641

## 2026-07-23 — Close the run log to `write_file`
`ROUTINE_LOG_DIR` sits *inside* `WRITE_ROOTS` (`<vault>/99 outbox/routine logs/`
under `<vault>/99 outbox`), so containment alone let a model overwrite the
append-only log `runner.append_log` owns — the audit trail *and* what the next
run reads via `last_run()` to honour `on_failure`. A clobber destroys the record
of the failure the log exists to preserve, silently, since nothing compares the
file against what the runner wrote.
- **`tools.reserved_write_reason()`** refuses a write resolving inside the log
  dir. **Containment, not a name pattern** — the deny list is the weaker tool
  (filename-based, open-ended: every `config.py.bak` shape escaped it once)
  and this wants the closed form. Same shape and reason as
  `mover._reject_wiki`.
- **Enforced in `write_file`, mirrored in `precheck`.** `dispatch()` is
  reachable with no gate at all, so a check that lived only in the pre-filter
  would be advice; the pre-filter copy exists so the gate never prompts for a
  call that cannot succeed.
- **Writes only.** Reading a run log stays allowed — this blocks recording, not
  looking. Resolution happens first, so a symlink out of the outbox into the
  log dir is judged as its target.
- `gate_and_dispatch` now prints the *real* refusal reason instead of a fixed
  "outside the jail", which is no longer true of every pre-filter denial.
- Verified against the real config as well as the fixture: the live
  `heartbeat.md` is refused and unchanged. Assertions confirmed to fail with
  the guard disabled.
- Files: tools.py, commands.py, tests/test_tools.py, HANDOVER.md, BACKLOG.md
- Status: shipped
- Commit: 1d1f7da

## 2026-07-22 — Read `prompt:` as an Obsidian link, not just a filename
Routine files are authored *and linked* in Obsidian, so `prompt:` arrives as
`[[wiki draft writer prompt]]` as readily as `heartbeat.md`. Only the filename
resolved, and the error — `prompt file not found: …/[[wiki draft writer
prompt]]` — read as a missing file while the file was sitting right there.
- **`prompt_candidates()`** unwraps the wikilink, drops an `|alias` and a
  `#heading`, and offers a vault-relative link's basename too. `Routine
  .prompt_path()` resolves **by existence**, first hit wins.
- **`.md` is a candidate, never an assumption** — the suffixed form is tried
  first (Obsidian links carry no extension), the bare form second, so a prompt
  genuinely named `.txt` still resolves.
- **The stored string is not rewritten.** Resolution is read-time only, so
  `to_markdown()` still emits what the file said. Normalising `[[…]]` on save
  would round-trip fine and then break the first time Obsidian renamed the
  prompt — its link-update pass would have no link left to update.
- **Containment in `ROUTINE_PROMPT_DIR` is checked**, since `prompt:` is a
  string in a hand-edited file and `[[../../.ssh/id_rsa]]` is writable. Not the
  file jail (`paths.path_guard` is that) — a closed commitment next to it.
- `validate()` now names every form it tried, so "the file is gone" and "the
  link syntax went unread" stay distinguishable.
- Files: routines.py, tests/test_routines.py, HANDOVER.md
- Status: shipped
- Commit: 952ca64

## 2026-07-22 — Make a broken routine look broken, and Tab-complete `:routine`
A hand-written routine file carried `id: wiki maintainer`, which isn't a slug.
`:routine` listed it as available, `load_routine` *found* it, and `validate()`
then refused it — so a broken **routine** read as a mistyped **command**, and
several minutes went into quoting the argument different ways. Three fixes,
none of which relax the slug rule (identity has to stay typeable).
- **`:routine` marks what it can't run.** The listing validates each routine and
  prefixes a `!` on the broken ones, with the reason underneath. A screen that
  lists something as available and then refuses it is worse than no screen.
- **The "known:" list names ids *and* display names.** The id is what you type,
  the name is what it's called in Obsidian; printing one of them is what made
  the available/unrunnable contradiction invisible.
- **`load_routine` gained a third pass:** id, then display name, then the *slug*
  of what was typed — so `:routine Wiki Maintainer` finds `wiki-maintainer` and
  a name can be a sentence while an id stays a handle. Slugged match runs last,
  so an exact id or name always wins.
- **Tab completion for `:routine <name>`**, both ids and display names, sharing
  `complete.py`'s two front ends through a new `_dispatch()`. `MIN_CHARS` stays
  a path rule — a bare Tab lists every routine, which is the whole point when
  the thing you can't remember is the name. Broken routines are still offered:
  that's the one you're reaching for when you're fixing it.
- Also fixed in the vault (not this repo): the two hand-written routine files
  had non-slug ids, and `wiki draft writer` pointed at `/mnt/c/User/…/01 inbox`
  for a folder that is `/mnt/c/Users/…/00 inbox`.
- Files: routines.py, commands.py, complete.py, tests/test_routines.py,
  tests/test_complete.py, HANDOVER.md
- Status: shipped
- Commit: 03b0e19

## 2026-07-22 — A routine that runs out of tool calls fails instead of reporting ok
Found by running the wiki-draft routine in chat: it wrote all five drafts, then
hit the 8-call ceiling. In chat that's recoverable — you type "continue".
Unattended it was worse than it looked.
- **The silent-success bug.** `LIMIT_MESSAGE` is non-empty content, so it sailed
  past `_turn_with_retry`'s empty check, `_summarise` rendered it as a
  respectable log line, and the run was logged **`ok`**. A task that stopped
  halfway was indistinguishable from one that finished — the same shape as the
  empty-completion bug, through a third door. Now raises `CallLimitReached`,
  checked *before* the truthiness test that it used to pass.
- **Not retried, unlike an empty completion.** An empty completion is a hiccup
  the same request survives; an exhausted budget exhausts again identically, so
  a re-roll buys nothing and costs another full ceiling.
- **Routines get their own ceiling:** `ROUTINE_MAX_CALLS_PER_TURN = 15` vs 8 for
  chat, via a new `agent_turn(max_calls=…)`. The number bounds how long a
  runaway loop runs before a human interrupts it — and a routine has no human.
  A parameter, not a field on `ToolContext`: that object is the permission
  boundary, and a call count is capacity, not permission.
- **`LIMIT_MESSAGE` interpolates nothing now** (was naming the config constant).
  It's compared by identity, so embedding the count would break the check
  silently the moment the two paths diverged — which is exactly what they just
  did. Tests pin the constant's shape as well as the behaviour, verified by
  disabling the guard and watching the assertions fail.
- Backlog gains two entries found while reading the logging path: `append_log`'s
  `touched=()` is never passed by any caller, and the run log directory sits
  inside `WRITE_ROOTS` so a model can clobber the audit trail.
- Files: agent.py, runner.py, config.py, config.example.py,
  tests/test_routines.py, HANDOVER.md, BACKLOG.md
- Status: shipped
- Commit: 5d8e29c

## 2026-07-22 — Stop the golden baseline tripping on an API key rotation
`golden check` had been failing on `API key: ...64dd` — the last 4 of a key
that had since been rotated. Not a leak (it's what a provider dashboard shows)
but it made the baseline a property of *this machine's `config.py`*, and a
tripwire that fires on something the code cannot cause is one that gets
rubber-stamped. This harness is the one that has to be trusted after a refactor.
- **Fixed in `SCRUB`, not by re-recording.** `check` normalises both sides, so
  the rule repaired the existing baseline with no re-record needed. Re-recorded
  anyway so the raw tail stops living in a tracked file — a one-line diff.
- **Scrubs only the `...abcd` form.** With no key set the line reads `not set`,
  which still diffs against `<KEY>`; a config that lost its key is a real
  finding. Both directions verified by temporarily rotating and then blanking
  the key: rotation passes, blanking fails.
- Handover gains the per-phase timeout reasoning from the previous entry (the
  two paths' read timeouts are not the same quantity) plus a `SCRUB` note
  generalising the rule: anything a baseline pins that lives in `config.py`
  rather than in the source is this same bug.
- Files: tests/golden.py, tests/golden_baseline.txt, HANDOVER.md
- Status: shipped
- Commit: a035198

## 2026-07-22 — Give the non-streaming path a read timeout that fits a thinking model
A routine run died with `[error] The read operation timed out` — client-side,
not the provider. `call_api` had a flat `timeout=120`, and it is the path every
tools-on turn and every routine takes. Non-streaming means no bytes arrive until
the model has finished reasoning, so a thinking model working through several
wiki pages is silent for minutes and the request was killed mid-thought.
- **A scalar timeout was the wrong shape.** httpx applies it to connect, read,
  write and pool alike, so tuning for a slow model also means waiting that long
  on a dead socket — opposite requirements. Now per-phase: connect/pool 10s,
  write 60s, read long.
- **Read is 600s on the agent path** (`API_READ_TIMEOUT`, overridable in
  `config.py`), 60s for title generation — a throwaway 3-5 word call must not
  inherit the agent path's patience, especially since `generate_title` swallows
  the exception and would just go quiet for ten minutes.
- **The streaming path keeps read=300 and that number means something else:**
  httpx resets the read clock per chunk, so it's the gap between deltas, not the
  length of the turn. It got the same short connect/write bounds.
- Also untracked `CLAUDE.md` (`git rm --cached`) — it was in `.gitignore` but
  already in the index, so the ignore rule never applied. `CLAUDE.example.md` is
  the version that ships.
- Files: api.py, .gitignore
- Status: shipped
- Commit: 3e7133f

## 2026-07-22 — Private chat (v0.41)
`p` at the hub opens a chat that leaves nothing on disk. The isolation is
structural, not a scatter of `if private` checks.
- **The chokepoint is the connection.** A private chat runs against
  `db(":memory:")`, so every conn-driven write — including the ones `agent_turn`
  makes on its own — lands in a throwaway db and dies with it. No changes to the
  persist call sites. It's structurally invisible to the picker too.
- **`private=True` gates only what escapes the connection:** auto-embed (opens
  the real db by path), auto-export (writes a file), and model file-writes
  (`chat_context(private=True)` → empty write roots → `precheck` refuses
  `write_file`). Title generation is off too — nothing to label.
- **An explicit `:export` is still honoured** — the contract is "nothing is
  written down unless you ask for it by name". Model-proposed writes aren't
  asking.
- **Database read toggle:** `:database on|off` (alias `:db`), config
  `DATABASE_ACTIVE` (default off in a private chat). Gates `:recall`/`:remember`,
  a *read* axis kept separate from privacy (the write paths).
- **`db()` takes a `path`** (default None → real `DB_PATH`, read at call time so
  tests that patch `DB_PATH` still redirect it). `run_session` now passes
  `ctx=chat_ctx` into `agent_turn` so the private (write-less) scope actually
  reaches the tool path.
- `tests/test_private.py` pins the negative against a writing control; golden
  re-baselined for the `:database` help line.
- Files: db.py, main.py, hub.py, context.py, commands.py, config.example.py,
  tests/test_private.py, tests/test_empty.py, tests/golden_baseline.txt
- Status: shipped
- Commit: c9460ba

## 2026-07-22 — Document that a pushed tag is immutable
Close the gap the v0.4 note-typo turned up: a correction found after tagging
lands in a later commit, never a re-tag. Added to `CLAUDE.md`'s release-order
section and, as a generic suggested standard, to `CLAUDE.example.md`.
- Files: CLAUDE.md, CLAUDE.example.md, CHANGELOG.md
- Status: shipped
- Commit: e25a750

## 2026-07-22 — Add a known-bugs log and a v0.8 roadmap slot
Project hygiene, no code. New `BUGS.md` for defects (distinct from `BACKLOG.md`,
which is deferred-but-working debt), opened with the desktop-shortcut splash
background bug. Roadmap gains v0.8 (traits, `/add`, `:`→`/` — the prompt/command
cluster, kept orthogonal to the v0.5–v0.7 spine and out of v1.0), a `/database`
on/off bullet on v0.41, and a mouse-scroll item under Beyond v1.0.
- Files: BUGS.md, ROADMAP.md, CHANGELOG.md
- Status: shipped
- Commit: e4b7890

---

## 2026-07-21 — The screens: filtered hub, chat status, context colours
Rest of v0.4. The picker, the session header, and what the token bar's colours
actually mean.
- **The picker shows chats; `:list` shows everything.** `provider` is the
  session-kind discriminator (`db.PROVIDER_CHAT/WIKI/ROUTINE`), and routine runs
  and wiki pages are filtered out of `hub.recent_chats`. Seven of twenty hub
  rows were routine transcripts, and the wiki — 20 sessions, growing every
  import — was about to take the rest.
- **The filter is a deny list.** An unrecognised or NULL provider still shows as
  a chat. An extra row is visible and correctable; a conversation that silently
  stops appearing is indistinguishable from a deleted one.
- **Routine sessions are marked at insert**, with a one-shot migration for the
  ones that predate it, matched on the exact generated title shape rather than a
  bare `routine:` prefix — a chat called "routine: ideas" has to survive.
  Routine transcripts keep indexing as `source='chat'`; `test_schema.py` pins
  that coupling to `chunk.py`.
- **The hub grew a routine panel** — one row per routine, not per run, with
  freshness from the run log (green <24h, orange <48h, red beyond). Never-run is
  dim, not red: "never" and "overdue" are different facts.
- **Chat screen.** The forty-line command dump is gone — it scrolled the session
  header off the screen every time you opened a conversation, so the thing it
  existed to tell you was the thing it hid. Nine commands on entry, `:help` for
  the rest. The header *states* rather than warns: no system prompt is a fact,
  printed in the same voice as one that is set, followed by what is available.
- **Context colours** are now 15/35 (`CONTEXT_GREEN_MAX`/`CONTEXT_ORANGE_MAX`),
  from one `ui.context_style` read by the bar, the hub column and the post-turn
  nudge — three literals away from disagreeing. Percentages are unchanged and
  still honest; only the colour is opinionated. The nudge moved to the red
  threshold, because a red bar with nothing said about it reads as a bug.
- **Tool-path reasoning is middle-elided** (6 head + 10 tail). Head as well as
  tail: the opening lines say what the model is about to do, next to the tool
  call they explain.
- **`golden.py` now pins its own prompt/persona fixture.** The new header lists
  *available* prompts, so without it the baseline depended on the contents of
  the vault and would have broken every time a prompt file was added — a test
  that cries wolf is a test that gets ignored. Baseline re-recorded, 176 → 213
  lines (`:help` added to the script).
- **`tests/test_hub.py`**, 38 assertions, checked against five mutations. Two
  survived the first pass: the picker test **rebuilt hub's SQL instead of
  calling it**, so it passed against a deliberately broken filter — which is
  what `hub.recent_chats` now exists for.
- Files: hub.py, db.py, runner.py, agent.py, commands.py, main.py, ui.py,
  config.py, config.example.py, tests/test_hub.py, tests/test_schema.py,
  tests/golden.py, tests/golden_baseline.txt, HANDOVER.md, README.md, BACKLOG.md
- Status: shipped
- Commit: 77bff61

---

## 2026-07-21 — Replace the ASCII mascot splash with pixel art
First piece of v0.4. The launch screen is now a baked pixel-art image
composited under the title, instead of the four-line ASCII cat.
- **New `splash.py`.** The screen is painted black edge to edge and the art
  centred into it, with the title and prompt stamped into the same render pass.
  The art is 2:3 portrait and terminals are landscape, so it cannot bleed
  sideways without cropping the cat — but the source background is pure black,
  so the letterboxing is invisible and the screen reads as one image.
- **Assets are `assets/splash_<name>.raw`** — width, height, raw RGB. Not PNG,
  because decoding PNG means Pillow and a splash screen isn't worth a runtime
  image dependency. `dev/bake_splash.py` makes them and is the only thing that
  needs Pillow; it's in a new `requirements-dev.txt`, kept out of
  `requirements.txt` so a clean checkout proves the runtime is stdlib.
- **`SPLASH_ART`** replaces `SPLASH_FRAME`: a name, a list to pick from at
  random, or `"*"` for everything in `assets/`. Groundwork for a rotation.
- **The ASCII cats are gone from `ui.py`** — `SPLASH_FRAMES`, `_resolve_frame`
  and `_render_frame`. **They are coming back later**; retrieve them with
  `git log -S SPLASH_FRAMES -- ui.py` rather than retyping them. They are also
  in the archive.
- **Box-average resampling, not nearest.** The art is a one-pixel rim light on
  black and halves on a normal launch; nearest-neighbour halving broke the rim
  into dashes along the tail and the spine.
- **Two bugs found by testing, not by reading.** Arrow keys quit the app:
  `sys.stdin.read(1)` is buffered, so it swallowed the rest of an escape
  sequence and the `select` meant to tell a sequence from a bare Esc saw an
  empty fd. Reads the raw fd now. And the cat's ears sat on row 0, because the
  art is height-bound on any normal terminal and scaled to fill exactly.
- **`test_splash.py`**, 36 assertions, checked against four deliberate
  mutations. Two of them survived the first version of the tests — the aspect
  check only used height-bound terminal sizes, and the wide-glyph check counted
  characters where the bug is about cells.
- Files: splash.py, ui.py, main.py, config.py, config.example.py,
  tests/test_splash.py, dev/bake_splash.py, assets/splash_balthazar.raw,
  requirements-dev.txt, HANDOVER.md, README.md, CLAUDE.md
- Status: shipped
- Commit: 42e9605

---

## 2026-07-21 — Split private chat into v0.41; drop `longcat-2.0`
Roadmap restructure, Cas's call, plus the one backlog item that turned out to
need deleting rather than fixing.
- **Private chat moves out of v0.4 into its own version, v0.41**, to be its own
  session. It's the only non-cosmetic item in that stretch and the only one
  whose failure mode is silent, so it shouldn't share a session with three
  screen redesigns. The cost is recorded in the roadmap rather than glossed:
  the selection screen will already be built, so adding the `p` key means
  opening it a second time.
- **`longcat-2.0` removed** from `MODELS`, `MODEL_LIMITS` and the
  `TOOLS_MODELS` comment, in both `config.py` and `config.example.py`. It was
  never wanted; there was nothing to repair, only a mention to delete. The
  backlog entry is closed, not fixed, and says so.
- The observation underneath it — nothing validates that a model in `MODELS`
  can actually be chatted with — is deliberately **not** carried forward as
  work. A bad name fails at the first message with a provider 400, which is
  loud and immediate.
- **`golden.py` re-baselined**, 177 → 176 lines. The harness reads the real
  `config.py`, so dropping a model legitimately changes `:config` and
  `:models` output. Diff inspected first: three lines, all longcat, nothing
  else — which is the entire reason that harness exists.
- Files: ROADMAP.md, BACKLOG.md, config.py, config.example.py,
  tests/golden_baseline.txt
- Status: shipped
- Commit: 42e9605

---

## 2026-07-21 — Rework `:attach` completion; add MOUSE_INPUT
v0.3's third piece. Started as "vault before repo" and turned up that
completion **had not been running at all**.
- **`complete.py` wired into readline; input moved to prompt_toolkit, which
  never consults readline.** Tab silently did nothing on the interactive path
  from the moment the editor landed. Nothing raised, nothing failed, and
  `install()` kept returning True. It didn't break — it stopped existing.
- Two front ends over one `_candidates()` now: `AttachCompleter` for
  prompt_toolkit, `install()` still covering the `input()` fallback. The
  completer is **injected** via `ui.set_completer()` rather than imported —
  `ui.py` sits at the bottom of the dependency graph (invariant #4) and
  `complete.py` pulls in `paths` + `config`.
- **A slash navigates, a bare name searches.** The old code listed one
  directory level, and the vault's documents live a level or two down, so it
  found the repo's top-level files and none of the vault's — which is what
  "misses vault items" was. Bare fragments now search breadth-first, depth 4,
  capped at 50 results.
- **Vault before repo**, identified as the root containing `WIKI_DIR` rather
  than by a new config key. The first candidate is what Tab takes.
- `os.scandir` instead of `iterdir`: the file-type flag comes back with the
  directory read, so recursing costs no extra stat. 0.9s → 0.2s across /mnt/c.
- Matching is case-insensitive now — the vault has `00 inbox`, the repo has
  `HANDOVER.md`, and remembering which is which isn't the user's job.
- `MOUSE_INPUT` (default off) enables click-to-position in the input line. Off
  by default because it captures the mouse for the whole window while the
  prompt is live, costing click-drag selection of the scrollback. On in Cas's
  config to be judged in use. Note it collides with "select text in chat,
  right-click to copy" in the Beyond-v1.0 pile — same events.
- `tests/test_complete.py` pins the front end the REPL actually uses, the
  ordering, and that the jail still holds.
- Files: complete.py, ui.py, main.py, config.example.py, config.py,
  tests/test_complete.py (new), README.md, HANDOVER.md, CLAUDE.md
- Status: shipped
- Commit: 9431ada

## 2026-07-21 — Add a launcher that checks the embedder before opening cfc
v0.3's second piece. Retires the class of failure where LM Studio simply wasn't
running — which everything memory-shaped quietly assumes away, and which shows
up as recall returning nothing rather than as an error.
- `launch.sh` — finds the repo from its own location (a Windows shortcut starts
  in an unpredictable cwd), activates the venv, runs the preflight, starts cfc.
  Holds the window open on a non-zero exit only, so a crash is readable.
- `preflight.py` — probes the embedder with a real `/embeddings` POST rather
  than a GET on `/v1/models`: the model list reports what LM Studio has on
  *disk*, so it answers happily while the model is unloaded and the thing cfc
  needs still fails. Server off → `lms server start`; model not loaded →
  `lms load -y`. `-y` matters, since without it the CLI opens an interactive
  picker and a launcher that asks a question is a launcher that hangs.
- **It checks the vector width against `vec_chunks`'s `float[1024]`.** A
  wrong-sized embedder doesn't raise, it inserts — the damage would surface
  weeks later as slightly worse ranking with no event to trace it to.
- **It never blocks the launch.** Any failure prints why and starts cfc anyway;
  chat works fine without an embedder. `__main__` always exits 0 so a future
  `set -e` wrapper can't turn a degraded embedder into a refusal to open.
- Reads the endpoint from `config.py` rather than carrying a second copy — a
  launcher reporting a healthy embedder that cfc can't reach is the failure
  that duplication buys you. Optional `LMS_CLI` override; otherwise the CLI is
  found on PATH or globbed from `/mnt/c/Users/*/.lmstudio/bin/lms.exe`.
- Only re-probes when something was actually changed. On WSL a dead local port
  hangs to the timeout rather than refusing, so a pointless second probe cost
  20s in front of an app that hadn't opened; the failure path is 8.7s now.
- README gains Windows shortcut instructions (plain console and Windows
  Terminal) and a Usage section explaining what the preflight is for.
- Files: launch.sh (new), preflight.py (new), tests/test_preflight.py (new),
  config.example.py, README.md
- Status: shipped
- Commit: 7cd6447

## 2026-07-21 — Add `:wiki` — review and commit the vault repo from the REPL
v0.3's first piece. The vault became a git repo in v0.2; this is the window
onto it, so hand-edited pages can be reviewed and committed without leaving
cfc. Same shape as `mover.py`: code-driven, scoped to a fixed root, no model
anywhere near it and no tool schema.
- `:wiki` — status. Wiki changes listed, the rest of the vault *counted* with a
  pointer to `all`. The count exists so "wiki db: clean" can't be misread as
  "the vault is clean", which is its usual state.
- `:wiki diff [all]` / `:wiki commit [all] <message>`. Default scope is the
  wiki corpus; `all` widens to the whole repo and has to be typed.
- **The commit carries the pathspec too, not just the `add`.** `git add --
  <spec>` alone still lets the following `git commit` sweep up anything already
  staged elsewhere in the vault. Pinned by a test that stages a file outside
  the scope and asserts it survives — and verified by breaking it on purpose.
- Repo discovery anchors at `WIKI_DIR`, never the process cwd: cfc runs inside
  its *own* git repo, so a cwd-relative git would diff and commit cfc's source
  while calling it the wiki.
- Status parses `--porcelain -z`. Every path in this vault contains a space, so
  git's quoted form is the normal case, not the exotic one.
- No push, and it says "local only" after every commit. The repo has no remote;
  whether the `02 areas` medical material goes to someone else's server is a
  v1.0 decision, and a push that silently no-ops today is one that silently
  starts working the day a remote appears.
- Untracked files are listed by name rather than diffed — the alternative
  (`--intent-to-add`) mutates the index as a side effect of looking.
- Files: wikigit.py (new), commands.py, main.py, tests/test_wikigit.py (new)
- Status: shipped
- Commit: c1e1681

## 2026-07-21 — Put the vault under git; document it
Infrastructure on the Obsidian vault, not cfc code — no module changes.
- The vault is a git repo. `.git` relocated to `~/vaults/wiki.git` with a
  `gitdir:` pointer left in its place: keeps git off the slow `/mnt/c` bridge
  and out of Obsidian's explorer, search and graph (confirmed by looking).
- Text tracked, binaries not — 131 MB → 7 MB. PDFs and images never change and a
  committed blob is permanent; their extracted Markdown is tracked, so the
  content is versioned even where the source file isn't. Also ignored:
  `.obsidian/workspace.json`, `.claude/settings.local.json`, and `99 outbox`
  except its readme.
- `core.autocrlf=false` + `.gitattributes` (`* text=auto eol=lf`), so the
  whole-file-rewritten diff can't happen if Windows git ever touches it.
- Known gap, parked at v1.0: the history lives on ext4, outside the Windows
  daily backup. A WSL reinstall keeps every note and loses every commit.
- `README.md` gains a "The vault, and why it's a git repo" section — the first
  piece of the "document the skeleton around cfc" work v1.0 now owns.
- `ROADMAP.md` rewritten: v0.2 marked complete, `:wiki diff`/`:wiki commit`
  scheduled into v0.3 (unblocked by the repo existing), v1.0 gains the skeleton
  docs and the vault remote.
- Files: README.md, ROADMAP.md, CHANGELOG.md (+ the vault repo itself)
- Status: shipped
- Commit: b8e38db

## 2026-07-21 — Make retrieval trustworthy (v0.2)
Recall returned nothing for good queries. The cause was not what the backlog
thought, and the fix is a change of role rather than a change of number.
- **The 0.969-vs-1.036 discrepancy is explained.** `MAX_DISTANCE = 1.024` and its
  "0.111-wide gap" were measured on the **Anthropic export** and recorded as wiki
  numbers. `"Who is Cas"` reproduces at 0.970 there, and has measured 1.036 on
  every wiki snapshot since the corpus was created (checked against the rolling
  backups, chunk text byte-identical). Nothing regressed; the baseline was
  mislabelled. Embedder, endpoint and corpus drift each ruled out by measurement.
- **The floor is now a lint filter, not a relevance judge** — `1.08`. The
  answerable and unanswerable bands interleave (a guitar-tuning question scores
  1.055; a real question needs 1.065), so no threshold separates them and a
  relative metric doesn't either. Set to admit generously, because a rejected
  good hit is silent while an admitted bad one is caught by recall's synthesis.
  The old value was losing 4 of 20 real query phrasings.
- **`search()`'s over-fetch window widens** until it has k results, crosses the
  floor, or exhausts the table. The flat `k*4` could return zero wiki hits purely
  because the window filled with `source='chat'` chunks — worsening daily.
- **`chunk.py` seeks to word boundaries at both edges.** It was a fixed-char cut:
  22 of 26 chunks opened on a fragment. Corpus re-chunked and re-embedded (519
  chunks, 512 vectors, 0 orphans); snapshot kept at `~/.cfc/chat-prechunk-*.db`.
- **`tests/test_chunk.py`** added — 24 assertions, verified to fail against the
  old chunker. Suite is now 435 assertions across 11 suites.
- Files: search.py, chunk.py, tests/test_chunk.py, HANDOVER.md, BACKLOG.md,
  README.md, CLAUDE.md
- Status: shipped
- Commit: b2acf03

## 2026-07-21 — Tag versions in git, starting at v0.1
Documentation only, no behaviour change.
- Versions are **annotated git tags** named `vX.Y`. A version number that lives
  only in markdown can't be checked out, so "what did this look like at v0.2"
  had no answer.
- `v0.1` tags this commit — the docs that declare v0.1 exists are part of it.
- Convention recorded in `CLAUDE.md`: tag the commit that completes a version's
  work, after its docs are in; `git push --tags` is a separate step from a normal
  push; don't move a published tag; don't tag on Cas's behalf unasked, since a
  tag is a public claim that a version is done.
- Also backfills 4dc416e.
- Files: CLAUDE.md, CHANGELOG.md
- Status: shipped
- Commit: 0e2e596

---

## 2026-07-21 — Add ROADMAP.md; reconcile CLAUDE.md with reality
Documentation only, no behaviour change. The project is versioned from here.
- **`ROADMAP.md`** — v0.1 (today) through v1.0, with each version owning named
  `BACKLOG.md` items rather than deferring all debt to one cleanup. v0.1 means
  "the state of things on 2026-07-21", explicitly *not* a verification claim.
  Numbering leaves room above v0.2 for versions not yet foreseen.
- Ordering rationale worth keeping: v0.2 bundles the `chunk.py` overlap fix with
  the `MAX_DISTANCE` re-measurement because re-chunking changes the corpus, and
  the floor is a property of the corpus as well as the embedding geometry —
  splitting them costs a second measurement run.
- v1.0 also carries the **public-repo decision** (solid enough? sanitized
  enough?), parked there deliberately so it stops taking up room now.
- **`CLAUDE.md`'s Current project section was stale** — it still described the
  Anthropic export as the corpus, `MAX_DISTANCE = 0.93`, the `chat.py` split and
  wiki migration as pending work, and the README roadmap as unfinished. Rewritten
  to point at `HANDOVER.md` / `CHANGELOG.md` / `BACKLOG.md` as the authorities
  instead of restating them, and to carry the one live blocker (the collapsed
  `MAX_DISTANCE` gap).
- Added: `ROADMAP.md` is Cas's document — a session proposes changes, it doesn't
  make them.
- Files: ROADMAP.md, CLAUDE.md, CHANGELOG.md
- Status: shipped
- Commit: 4dc416e

---

## 2026-07-21 — Make the README accurate; drop the roadmap
Documentation only, no behaviour change.
- Documents the splash (Enter/Esc, once per launch, skipped on a non-TTY) and
  the hub's trimmed columns; adds `SPLASH_FRAME` to the config list and the
  splash to the flow diagram.
- The command table had drifted: `:list`, `:delete`, `:prompts`, `:personas`,
  bare `:model` and `:file all` existed but weren't listed, `:title` has three
  forms rather than one, and `:export` takes an optional session id.
- **Roadmap removed** rather than updated — it described work that was never
  actually planned. A real one comes with the first tagged version. The one
  genuine item in it (routines run on command, no scheduler yet) moved to
  Known limitations, where it belongs.
- Verified against the source rather than trusted: command dispatch in
  `main.py`, `backup.py`'s flags, the test list, and `requirements.txt`.
- Files: README.md
- Status: shipped
- Commit: 6a64057

---

## 2026-07-21 — Add the launch splash; trim the hub tables
A mascot screen at startup, and the session list stops spending its width on
columns that were almost always empty.
- **`ui.splash()`** renders once per launch from `__main__`, between
  `safe_backup()` and `repl()` — deliberately not inside `repl()`, so returning
  from a session to the hub doesn't re-show it. **Enter continues, Esc quits**
  (`sys.exit(0)`, `repl()` never runs). It is safe under invariant #4 only
  because nothing is driving the terminal yet at that point.
- **The art lives in `ui.py`**, the choice of frame in `config.py`
  (`SPLASH_FRAME = "serious.1"`) — the same look-vs-knob split as the palette.
  `SPLASH_FRAMES` is an ordered list per mood ("serious", "chilling", three
  frames each) and `_render_frame()` is its own function, so animating this is
  swapping one call for a loop, not a re-architecture. An unrecognised
  `SPLASH_FRAME` falls back to the default rather than raising, and a missing
  one is caught — `config.py` is gitignored, so an existing one predates this.
- Frames are **raw strings**: three of them end a line in a backslash, which in
  a normal string splices the next line on and eats the cat's flank.
- Layout maths uses **`rich.cells.cell_len`, not `len`** — the art is full-width
  CJK, so `len` under-measures every line and shears the block off the right
  edge. The block is right-aligned as a block (one shared left pad), so the
  whisker spacing survives. Filler targets `height - 1`; exactly `height` lines
  scrolls the title off the top.
- **Esc needs raw mode** — a bare Escape never arrives through a line-buffered
  read, because it isn't a line. `_wait_key()` reads one byte under
  `tty.setcbreak` and restores the terminal in a `finally`; leaving it in cbreak
  would break every prompt_toolkit read for the rest of the session. No
  `termios` (non-POSIX) degrades to Enter-only instead of failing to boot.
- **No-op on a non-TTY** — a piped or headless run must never block on a
  keypress, and `tests/golden.py` output must stay byte-for-byte. Verified both
  ways: piped runs show no splash, and the splash's own TTY paths were driven
  through a real pty (Esc → no hub, exit 0; Enter → hub).
- **`hub.py`**: dropped the Tags and Model columns from both tables (and the
  `GROUP_CONCAT` subquery that fed Tags), and `.md` is stripped from prompt and
  persona names — display only, the stored name keeps its extension. Both views
  now build from one `_session_table()` helper so they can't drift apart again.
- Title is `no_wrap` + ellipsis at a **fixed** width. This is the fiddly bit: a
  `no_wrap` column is granted whatever its longest row asks for, taken out of
  the flexible columns — one 58-char title starved #, Msgs, Prompt and Persona
  to zero and printed a table of empty verticals. `min_width` reproduces it from
  the other direction. Fixed widths reserve the space, so Title truncates
  instead of bullying.
- Golden re-baselined (177 lines); the diff was one hunk, exactly the dropped
  columns. All 10 unit suites pass.
- Files: ui.py, hub.py, main.py, config.py, config.example.py,
  tests/golden_baseline.txt
- Status: shipped
- Commit: c3194c8

---

## 2026-07-20 — Consume `ToolContext.interactive`; stop logging empty runs as `ok`
Wiring the flag turned up a worse bug than the one it was reserved for.
- **`for_chat` defaults `interactive` to `sys.stdin.isatty()`** instead of
  hard-coding True, which was a lie the moment input was piped. It is a
  separate question from `gated`: a chat is always gated, but a chat driven
  from a pipe has nobody to ask about a re-roll.
- **`main.py`'s empty-completion handler consults it.** Human present: ask
  `retry? (y/n)` as before. Nobody there: re-roll up to
  `api.EMPTY_COMPLETION_RETRIES` (2), then give up loudly. The old code asked
  unconditionally and read the `EOFError` as "no", so every piped hiccup
  silently cost a turn.
- **The routine bug was not the predicted hang.** The handover expected an
  unattended run to block on that prompt; it couldn't, because routines take
  the `agent_turn` path, which has no prompt. Instead `agent_turn` returned
  the empty message, `_summarise("")` gave `""`, and the run was logged **`ok`
  with a blank summary** — a routine that did nothing looked exactly like one
  that had nothing to do. Same failure mode standing decision #4 flags for
  zero-hit recall, through a different door. `runner._turn_with_retry` now
  re-rolls and raises `EmptyCompletion`, which the broad `except` logs as a
  failure.
- **That retry deliberately does NOT consult `interactive`.** A routine is a
  batch job whether or not somebody is watching; gating it on the flag would
  have made an on-command run give up on the first hiccup while an unattended
  one re-rolled twice — exactly backwards. Caught while writing it, and now
  pinned by a test that asserts both paths re-roll identically.
- Files: context.py, api.py, main.py, runner.py, tests/test_empty.py (new),
  tests/test_gate.py, tests/test_routines.py, README.md, HANDOVER.md, CLAUDE.md
- Status: shipped
- Commit: 2af708a

## 2026-07-20 — Add propose/approve/move: `mover.py`, `:outbox`, `:file`
Round three of the routines handover, which is now fully discharged. A routine
writes into the outbox with a suggested `destination:`; you review and approve;
code does the move.
- **New `mover.py`** — `plan()` reads one outbox file and computes its verdict,
  `commit()` carries it out, `drop()` discards it. The model's suggested
  destination is **data, not authority**: re-validated from scratch against
  `MOVE_ROOTS` exactly as if a stranger had typed it.
- **Outside the roots is refused, not guessed at.** No nearest-match, no
  fallback folder — a silently-wrong path is worse than an error, because
  nobody re-reads a file that filed successfully. Verified against the real
  config: traversal, absolute system paths, and the cfc source tree are all
  refused by containment.
- **Wiki destinations are refused outright**, against `WIKI_DIR`, rather than
  left to habit. A page written there changes the corpus while the index
  doesn't know until `import_wiki.py` runs, so recall would answer from a
  stale copy **with no signal that it's stale** — a silent failure arriving
  weeks later has to be structural.
- **`MOVE_ROOTS` is separate from `WRITE_ROOTS`, and that separation is the
  design.** The mover may write across the whole vault precisely *because it
  is not the model*. Widening `WRITE_ROOTS` to do the same would hand the
  model the reach the outbox exists to deny it.
- **`:outbox` computes verdicts at list time** — you see what `:file 1` will do
  before you type it. `commit()` then re-plans before writing, because the list
  you're looking at may be minutes old; a test covers the race where the target
  appears between plan and commit.
- **Write-then-unlink, in that order.** A crash between them leaves both
  copies, which is recoverable; the reverse can lose the file. `destination:`
  is stripped on the way out — a carried-out instruction left in a filed
  document is one a later sweep could act on twice — and the rest of the
  frontmatter is preserved untouched.
- **`:file <n> drop` moves aside rather than deletes.** Rejecting a draft and
  destroying it are different intentions, and only one is recoverable.
- Files: mover.py (new), commands.py, main.py, config.py (gitignored),
  config.example.py, tests/test_mover.py, README.md, HANDOVER.md
- Status: shipped
- Commit: 1e43017

## 2026-07-20 — Add the routine object, `:routine`, and the run log
Round two of the routines handover (session 2 of 3). A routine is a task the
model runs on command now and on a schedule later; this is everything except
the scheduler, which is deferred on purpose rather than forgotten.
- **New `routines.py`** — the `Routine` object and its file store. One markdown
  file per routine (frontmatter for the fields, body for notes), keyed by a
  stable `id` rather than the filename, so renaming one keeps its log history.
  The invariant is that a routine is **fully reconstructable from its file**:
  no hidden DB state, which is what makes list/delete/edit into folder
  operations. That round-trip failed on first run over a single trailing
  newline — `body` is now normalised once in `__init__`.
- **New `runner.py`** — `run_routine()`, which is the headless entry point in
  all but name. `:routine <name>` calls it with nothing in between, so a future
  `--run-routine` reuses it unchanged. It never raises for an expected failure:
  every path out reaches the run log, because an unattended run that dies
  silently is indistinguishable from one that had nothing to do.
- **Validation happens twice, on purpose.** Each path is checked with
  `denial_reason()` as it is typed, and the whole routine is re-validated at
  save by building its real `ToolContext`. A routine whose write root overlaps
  the cfc source **cannot be saved**, not merely cannot be run — an invalid
  routine sitting on disk looking fine is the 03:00 surprise this prevents.
- **`:routine` / `:routine new` / `:routine <name>`** — list with each one's
  last outcome, create via sequential prompts (no TUI), run now. Write access
  defaults to off and turning it on is a separate explicit answer.
- **The run log** (`<vault>/99 outbox/routine logs/<id>.md`) is append-only and
  written through the same temp-file + `os.replace` path as everything else: a
  log that can corrupt itself on the failure it exists to record is worse than
  no log. Two consumers — a human, and the next run, which reads the previous
  outcome off the file because a scheduled run is a fresh process.
- **`agent_turn` grew `ctx=None`** — the injection seam, a parameter rather
  than a global so "which scope is this turn under" can't depend on execution
  order. `None` still means chat; no existing caller changed.
- **Two things the model had to be told**, both found by running the throwaway
  `heartbeat` routine: the **date** (it stamped a file 2025-07-10 on
  2026-07-20 — a model has no clock, and a scheduled task is exactly what must
  not guess) and **its own roots** (it tried a relative path every run, which
  resolved against the process cwd and cost a full round trip on the refusal).
  Both now go into the system prompt. Neither weakens the boundary — dispatch
  still enforces the jail regardless of what the prompt says.
- **`EMBED_BASE` repointed to `localhost:1233`.** WSL2 now runs
  `networkingMode=mirrored`, so the old NAT gateway IP no longer resolves and
  auto-embed had been failing quietly. Backlog item closed.
- Files: routines.py, runner.py, commands.py, main.py, agent.py, config.py,
  config.example.py, tests/test_routines.py, README.md, HANDOVER.md, BACKLOG.md
- Status: shipped
- Commit: 60ed2dd

## 2026-07-20 — Split read and write scope, add write_file, delete TOOLS_AUTO_APPROVE
Round one of the write substrate (routines handover, session 1 of 3). cfc can
now write, but only into one narrow root, and only with a human saying yes.
- **New `context.py`.** A `ToolContext` carries read roots, write roots, and
  whether the run is gated. Permission scope is now a property of the caller
  rather than a global, which is what lets an unattended routine have a
  different scope from a chat without a parallel code path.
- **`TOOLS_AUTO_APPROVE` is gone**, on Cas's ask: auto-approval must be
  impossible in normal chats. It was one config line from turning "no human
  present" into "everything pre-approved". `ToolContext.for_chat()` is always
  gated and `gated` has no setter, so the only route to an ungated run is
  `for_routine()`, which forces a declared write scope in the same call. `A`
  (allow-all) survives — a human deciding once for one turn is a different
  thing from a config file deciding forever — but it no longer covers writes.
- **`WRITE_ROOTS`** is a standalone config tuple, never derived from
  `ATTACH_ROOTS`/`TOOLS_ROOTS` by assignment. Set to the vault outbox.
  `context.py` refuses at construction any write root that overlaps the cfc
  source tree, checked both directions — the code is not protected from writes
  by a deny-list entry, it is simply absent from the writable universe.
- **`write_file`** — atomic (temp file + `os.replace`, so a crash mid-write
  leaves the original intact), guarded before it touches anything (invariant
  #1), refuses to clobber unless `overwrite=true`, capped at 200k chars.
  Guarded against the *write* roots via `tools._roots_for`; a bare roots value
  yields an empty write set, so it fails closed.
- Write calls render a red `Tool call — WRITE` panel that states plainly
  whether an existing file will be replaced, and don't offer `[A]`.
Verified end to end against the real config: writing into the read root, into
the vault's `00 inbox` (readable, not writable), and to a deny-listed name are
all refused; no temp debris left behind.
Deferred to sessions 2–3: the routine object and `:routine`, and the
propose/approve/move pipeline. The `MAX_DISTANCE` regression is untouched and
still blocks any memory-pass routine — see `BACKLOG.md`.
- Files: context.py (new), tools.py, commands.py, agent.py, config.py
  (gitignored), config.example.py, tests/test_paths.py, tests/test_tools.py,
  tests/test_gate.py, tests/test_agent.py, tests/golden.py,
  tests/golden_baseline.txt, HANDOVER.md, README.md, CLAUDE.md
- Status: shipped
- Commit: 87b34ea

## 2026-07-20 — Auto-refuse doomed tool calls, hide denied files, close the .pyc gap
Four changes to the read jail, prompted by "I don't want to roll the dice on a
tool call reading config.py that I have to decline":
- `tools.precheck` lets the gate refuse a call `path_guard` would reject anyway,
  without prompting — a gate that fires on impossible calls gets rubber-stamped.
  The dispatcher guard is untouched and still runs for every call.
- `list_dir` omits denied entries instead of listing them. Ergonomics, not
  security: guessing the name is refused identically.
- Deny list now covers `config.py.*` backups (exact-name matching let every copy
  through) and `*.pyc`/`__pycache__` — compiled bytecode embeds the API key as a
  string literal. It never leaked, but only because read_file rejects non-UTF-8
  and grep opens strict; that was the file format, not the boundary.
- `ATTACH_ROOTS` narrowed from `~/projects` to `~/projects/cfc`.
Found while testing: a *stale* API key sits in a compiled config in the old
`C:\Users\disse\CFC\__pycache__` — outside the roots, but live on disk.
- Files: paths.py, tools.py, commands.py, config.py (gitignored),
  tests/test_paths.py, tests/test_gate.py, HANDOVER.md
- Status: shipped
- Commit: fa4b1ad

## 2026-07-20 — Put the shared inbox/outbox in the vault, not the repo
Handovers and briefs are exchanged through `<vault>/00 inbox` and `99 outbox`
instead of folders in the project tree. Both were already inside the tool roots
after the config repoint, so this needed no code — only a decision and the docs
to make it stick. The repo pair would have had to be gitignored, which means
invisible to clones, outside the vault's daily backup, and lost to a fresh
checkout; content that isn't code shouldn't sit in the working tree. Moved the
routines handover to the vault inbox, removed the empty repo folders, and swept
10 orphaned `*:Zone.Identifier` stubs (Windows download metadata) from the root.
- Files: HANDOVER.md, README.md, CLAUDE.md (gitignored)
- Status: shipped
- Commit: 02ae8d6

## 2026-07-20 — Repoint config at the reorganised Obsidian vault
The vault was restructured (renamed + refoldered) and every path in the
gitignored `config.py` pointed at the old `Claude/01_Projects/Cooking_for_Cats`
tree, which no longer exists — breaking `:export`, `:prompts`, `:personas`,
`:attach` and the file tools. Repointed VAULT_PATH (now outside the vault, at
the backup dir), PROMPTS_DIR, PERSONAS_DIR and the ATTACH_ROOTS vault entry.
Golden baseline re-recorded: the 34-line diff is entirely the path echoes in
`:config` plus the renamed prompt/persona files (`main_prompt` → `light prompt`,
`coding_assistant` → `EVA`), no structural change. The DB needed nothing — all
20 wiki pages matched their files, because identity is the frontmatter id and
not the path. Unit suites green.
- Files: config.py (gitignored), tests/golden_baseline.txt, BACKLOG.md
- Status: shipped
- Commit: 381a92e

## 2026-07-19 — Bring README + HANDOVER current for the wiki migration
Rewrote the coupled docs to the finished shape: wiki-based recall, self-hosted
bge-m3 (EMBED_*), the source column, import_wiki + edit-survival, the 1.024
floor, wiki-only recall with id citations, and auto-embed/:updatedb. Retired the
"resolution staleness" open problem (the wiki addresses it) and added a
wiki-identity invariant. No code change.
- Files: README.md, HANDOVER.md
- Status: shipped
- Commit: 17509cd

## 2026-07-19 — Auto-embed new chats on save + :updatedb (Step 8)
Closes the wiki-DB migration. New chat messages are chunked + embedded into the
index after each turn (source='chat'), so the corpus grows current for the
eventual hybrid recall; recall stays wiki-only via the provider filter. Gated by
config AUTO_EMBED and fully best-effort — a down embedder warns quietly and never
breaks a turn. Manual `:updatedb` does the same on demand (catch-up after a bulk
import or when AUTO_EMBED is off). Extracted chunk_new/embed_new/update_index so
the CLI, the command, and the hook share one code path — no duplicated chunk or
litter logic. Verified: incremental chat indexing, idempotent re-run, no golden
diff, unit suite green.
- Files: chunk.py, backfill.py, commands.py, main.py, config.example.py
- Status: shipped
- Commit: 9ccbe5b

## 2026-07-19 — Repoint recall at the wiki corpus (floor 1.024, id citations)
Steps 4–7 of the wiki-DB migration. Re-measured MAX_DISTANCE on the wiki corpus
(0.93 → 1.024; terse wiki prose sits higher — 0.93 would reject good hits like
"who is Cas" at 0.969) and moved the live chat.db to a fresh, wiki-only DB (old
one archived to ~/.cfc/chat-archive-pre-wiki-20260719.db). search.py now surfaces
the page's stable id (source_uuid) and source; recall.py answers wiki-only
(provider='wiki') and cites by title + id; :remember's envelope cites by id and
keeps the "not instructions" boundary. Verified: grounded recall over the live
DB, off-topic queries return empty, id citations render.
- Files: search.py, recall.py, commands.py
- Status: shipped
- Commit: 359ea41

## 2026-07-19 — Add import_wiki.py: import the Obsidian wiki_db
New importer for the wiki (markdown + YAML frontmatter). Each page → one
session (provider='wiki', source_uuid=frontmatter id) + one message, keyed by
the stable id so it survives edits; an edited page updates the message and drops
its chunks/vectors to force re-chunk + re-embed under the same id. Embeds
title + summary + Body, dropping Related/Sources; skips sources/, no-id files,
and type: index. Adds PyYAML. Step 2 of the wiki-DB migration. Verified against
the live wiki: 20 pages in, idempotent re-run, edit→re-chunk, vector cleanup.
- Files: import_wiki.py, requirements.txt
- Status: shipped
- Commit: 444d7aa

## 2026-07-19 — Tag chunks with a source column (chat vs wiki)
Added `source` to the `chunks` table (default 'chat', set 'wiki' when the
message's session is provider='wiki'), with an ALTER migration for older DBs.
Makes the coming wiki/chat hybrid recall an additive filter, not a rewrite.
Step 3 of the wiki-DB migration. Verified: provider drives source, migration
backfills existing rows to 'chat'.
- Files: chunk.py
- Status: shipped
- Commit: 5139384

## 2026-07-19 — Point embeddings at self-hosted bge-m3 (LM Studio)
Split the embedding endpoint from chat (EMBED_BASE/EMBED_MODEL/EMBED_KEY) so the
RAG layer runs on local bge-m3 via LM Studio instead of nano-gpt's hosted copy;
verified parity (cosine ≥ 0.9993 over 6 probes, pooling + normalization match).
Falls back to the hosted defaults when the new keys are absent. Step 1 of the
wiki-DB migration.
- Files: embed.py, config.py (gitignored), config.example.py, BACKLOG.md
- Status: shipped
- Commit: b7b8c98

## 2026-07-18 — Backfill changelog hashes on the next commit, not by amending
The "same commit" rule was impossible for a self-referencing entry; switched the
convention to `pending`-then-backfill so it stops costing extra commits.
- Files: CHANGELOG.md, CLAUDE.example.md (and gitignored CLAUDE.md)
- Status: shipped
- Commit: e13840e

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
