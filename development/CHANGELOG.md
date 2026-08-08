# Changelog

What changed and when. Most recent at the top. Older entries removed from the
current checkout remain available in Git history.

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

## 2026-08-08 — A capture hands an unset console back unset
`D-19`, second pass, from the v1.9.1 triage. The first pass had every capture
helper save `console.file` and restore that exact object. Rich's `file` getter
cannot report the unset state: a console holding no file of its own resolves
`sys.stdout` at print time, and the getter answers with it — so the save reads
back a live terminal handle and the restore pins the console to it. That is
the leak `D-19` exists to close, wearing the fix's clothes. It was live:
`python -m pytest tests/` failed
`test_empty_retry.py::test_both_empty_exits_announce`, whose assertion read an
empty buffer while the line it wanted went to the screen, pinned there by
`test_connection.py`'s helper — one of the four the pass had named as already
correct. Every capture helper in `tests/` now saves `console._file`, the
attribute that is `None` when nothing is set, so an unset console is handed
back unset and a later plain `redirect_stdout` still receives Rich output.
`tests/test_ui.py` gains that case beside the nested one, which is the half
the first pass proved. Verified by disabling: putting `console.file` back in
`test_connection.py` reproduces the failure.
- Files: tests/test_agent.py, tests/test_api_stream.py,
  tests/test_connection.py, tests/test_first_message.py, tests/test_hub.py,
  tests/test_mainchat_turns.py, tests/test_memory_states.py,
  tests/test_model.py, tests/test_model_revert.py,
  tests/test_model_tools_notice.py, tests/test_mover.py,
  tests/test_process_model.py, tests/test_resolve.py, tests/test_routines.py,
  tests/test_screens.py, tests/test_turn_paths.py, tests/test_turn_repair.py,
  tests/test_ui.py
- Status: shipped
- Commit: 8614d32

## 2026-08-07 — Remove duplicate workflow copies and archives

Removed the public specialist templates and the checked-out legacy records.
The private specialist files are the only maintained workflow instructions;
closed issue bodies leave the live BUGS and BACKLOG files, while the tracker,
this changelog, and Git history preserve what happened. Removed the empty
`workflow/` placeholder and kept `workspace/` as the one private planning area.

- Files: `templates/` and `legacy/` (removed), `HANDOVER.md`, `ROADMAP.md`,
  `development/BACKLOG.md`, `development/BUGS.md`, `development/CHANGELOG.md`,
  `preflight.py`, `CLAUDE.md`, `agents/MANAGER.md`,
  `agents/MANAGERS_HANDBOOK.md`, `agents/OVERSEERS_HANDBOOK.md`,
  `workspace/TRACKER.md`
- Status: shipped
- Commit: pending

## 2026-08-07 — An untracked wiki file previews as the addition it would make
`D-1.6.2-02`: `/wiki diff [scope] file`'s per-file picker used to offer a
brand-new untracked *directory* as a single, undiffable row ("no diff to
show"). `wikigit.expand_for_picker` now expands an untracked directory to its
leaf files at pick time; choosing one runs `wikigit.diff_untracked_file`, a
read-only `git diff --no-index` against `/dev/null` — every line an addition,
never `git add --intent-to-add`, never touching the index. Revalidated
immediately before the git call: a vanished path, a directory, or a symlink
resolving outside the chosen scope is a refusal, not a fallback to reading
the file directly. `commands._wiki_diff_file` renders it through the same
Rich `Syntax` path tracked diffs use and keeps the separate, explicit
per-file commit suggestion — review grants no trust, and folder-wide diff is
unchanged (tracked text plus untracked names, nothing new dumped).
- Files: wikigit.py, commands.py, tests/test_wikigit.py, tests/test_screens.py
- Status: shipped
- Commit: c9091d6

## 2026-08-07 — A 5xx is a provider failure, not a raw-body puzzle
`W-1.1-02`: `api._provider_error` now gives status 500–599 alone a cfc-owned
message — `Provider failed this request (HTTP <status>). Try again; if it
keeps happening, check the provider's status.` — used by streaming, tool
chat, titles and routines alike, since both API paths build their error at
that one boundary. 400 keeps the provider's own detail (where a malformed
message, context overflow or bad model id is actually distinguished);
401/403/429 and transport failures are untouched. New `api.is_server_failure`
widens `main.handle_turn_error`'s non-revert treatment from the four
`TRANSIENT_STATUS_CODES` to every 5xx: a 500 isn't retried automatically, but
it's no more evidence a newly switched model is bad than a 503 is, so it
leaves an armed revert in place and never enters the rejected-models set. A
later, real 400 still reverts normally. Retry policy itself is unchanged —
`TRANSIENT_STATUS_CODES` and `runner.py`'s retry set are exactly what they
were.
- Files: api.py, main.py, tests/test_api_stream.py, tests/test_turn_paths.py,
  tests/test_model_revert.py
- Status: shipped
- Commit: 8df6924

## 2026-08-07 — A suspicious model id is marked, not judged
`W-08`: a configured model id with more than one `/` — the shape left behind
when two adjacent quoted ids in `config.py`'s `MODELS` list are missing a
comma and silently concatenate into one string — went unremarked until it
400ed at a provider. New `models.has_suspicious_slashes()` predicate feeds
both the post-splash `startup_warnings()` notice and `/list models`'s Status
column, so the two can't disagree about which ids look like a typo. It never
raises, never changes the record, and never removes an id from a list or
blocks a switch — exact and numbered selection, tool support, routine
vetting, presets and auto-revert all still accept a marked id exactly as
before.
- Files: models.py, commands.py, tests/test_models.py, tests/test_model.py,
  tests/test_model_revert.py
- Status: shipped
- Commit: f66cc76

## 2026-08-07 — The slash prefix becomes an owned command boundary
`W-1.4.1-02`: an unrecognised `/`-addressed line used to fall through to the
model as ordinary chat — standing decision 13's fallthrough, now deliberately
closed. After parsing and alias expansion, `main.run_session` refuses a bare
`/` ("Empty command — nothing after '/'.") and any verb that survives
expansion but still isn't in the handler table ("Unknown command '/<verb>' —
/help lists the commands"), before OOC or a chat turn — no message row,
request capture, title attempt, memory action or provider call. Ordinary
prose and the retired `:` prefix are unaffected; no fuzzy correction, no
alias revival.
- Files: main.py, tests/test_parse.py, tests/test_turn_paths.py
- Status: shipped
- Commit: cddc7af

## 2026-08-07 — Tone is a deployment choice, traits stay independent
`W-1.6.3-01b`: `governor.ordinary_instruction()` sent the automatic tone cue
on every ordinary turn unconditionally, with a due trait riding alongside
when one was owed. New `GOVERNOR_TONE_CHECK` config switch (default True,
matching every existing install) turns the tone cue off without touching the
trait reminder, an explicit OOC direction, `/continue`, or `/swipe`'s own
cadence — the function now composes zero, one or two automatic sources
instead of assuming tone is always the first one. Off-cadence with tone off
sends no instruction and prints no governor label at all.
- Files: governor.py, config.example.py, tests/test_governor.py,
  tests/test_turn_paths.py
- Status: shipped
- Commit: 05044bf

## 2026-08-07 — An uncertain outbox count says it is uncertain
`D-21`: `/list outbox`'s "N entries in total" pointer summed only the readable
roots, so a root that was missing or unreadable just dropped out of the
total — including reading as a clean, empty outbox when the one configured
root couldn't be inspected at all. Now any failed root forces "Outbox count
is incomplete — one or more configured roots could not be inspected", even
when the readable roots' own total is zero; an all-readable outbox keeps its
existing total-and-pointer behaviour. The detailed per-root failure stays
exclusively in `/list outbox contents`; this is a projection change only,
no new filesystem walk.
- Files: commands.py, tests/test_mover.py
- Status: shipped
- Commit: ad95082

## 2026-08-07 — A test capture restores the console it found, not sys.stdout
`D-19`: twelve test files finished a shared-console capture with
`console.file = sys.stdout` instead of restoring the object they found there.
Harmless in a one-file run, since process exit hides it — but pin the console
to a stale destination and a later, unrelated capture in the same process
loses everything printed after that point, invisible to the test that
actually asserts on it. Fixed to save-then-restore in all twelve; added a
same-process test proving the mechanism directly (an inner capture that
restores `sys.stdout` drops the outer capture's later output; one that
restores the saved object does not).
- Files: tests/test_agent.py, tests/test_first_message.py,
  tests/test_mainchat_turns.py, tests/test_memory_states.py,
  tests/test_model_revert.py, tests/test_model_tools_notice.py,
  tests/test_mover.py, tests/test_process_model.py, tests/test_routines.py,
  tests/test_screens.py, tests/test_turn_paths.py, tests/test_turn_repair.py,
  tests/test_ui.py
- Status: shipped
- Commit: f05602f

## 2026-08-06 — Every existing door tells the truth
v1.9's second small honesty pass: three more places where a screen already
said something that wasn't quite the whole story.

Recent chats already excluded routine transcripts from the picker by
`provider` alone, never by what the messages looked like — pinned now, so a
routine session someone kept chatting in can never quietly read as an
ordinary continued chat.

A wiki session's opening notice and its bare `/status` now resolve where the
imported page actually lives on disk right now, not just what it was
imported as: found under its current filename (even after a rename that left
the frontmatter id untouched), missing, ambiguous between several pages
sharing an id, or the wiki directory itself unreadable/unconfigured — the
same one resolved value both screens print, never a second parse.
`import_wiki.resolve_wiki_source` is read-only: it never imports, writes, or
picks a winner among duplicates.

The outbox's three surfaces now each say which subset of it they handle.
`/list outbox` is the filing-proposal screen and says so in its own heading;
a new `/list outbox contents` is a bounded, read-only inventory of
everything under every configured root — every file, directory and symlink,
capped at 200 displayed per root with the real count and the omission named,
grouped by root so one root's failure never erases another's. `/file` and
`/move`'s empty states now name what they're actually missing ("no filing
proposals pending" / "no loose top-level files") instead of claiming the
outbox itself is empty, and both point at the new contents command.

- Files: commands.py, db.py, import_wiki.py, main.py, mover.py,
  tests/test_hub.py, tests/test_memory_states.py, tests/test_mover.py,
  tests/test_turn_paths.py, tests/golden.py, tests/golden_baseline.txt
- Status: shipped
- Commit: ef2f3ad

---

## 2026-08-05 — The hub tells the truth about getting in and getting out
v1.9 is three small honesty fixes bundled into one release.

The hub's numeric help now says what a number actually does: any non-Main
session id opens even when it's missing from *Recent chats* (`/list sessions`
inside a chat shows the complete list, wiki pages and routine transcripts
included), and Main only opens with 'm' because its numeric id would skip the
bundle check that builds it. The short hub hint and the fuller `h` screen now
share that one sentence instead of two that could drift, and the `c` prompt
names Enter as its own cancellation.

An ordinary chat created by hub 'n' or bare `/new` is now discarded if it's
still empty and unchanged — no message of any kind, no First Message, no tag,
no changed title/model/prompt/persona/traits — at the moment you leave it
(`/q`, EOF, `/new` replacing it, entering a screen, or a nested private
chat's screen bubbling a session id out). A chosen id (`c`, `/new <id>`) or a
resumed row is never a candidate. `db.discard_provisional_chat` re-derives
the predicate from the row itself rather than trusting a flag, and only a
proven-empty row that then fails to delete gets a loud report — an ordinary
chat you actually used is left alone, silently, exactly as before.

`search_protocol.py` bumps to v3: a `source_refused` failure (DuckDuckGo
answered with a non-redirect, non-200 status) now carries that real HTTP
status end to end, from `search_worker.py`'s curl call through to
`websearch.summarize()`'s human trace — `web_search failed — source_refused
(HTTP 403; DuckDuckGo received the query)` — a definite claim rather than the
weaker "may already have been sent" hedge every other request failure still
gets. Every other failure keeps the plain two-field shape.

- Files: hub.py, main.py, db.py, search_protocol.py, search_worker.py,
  websearch.py, tests/test_hub.py, tests/test_turn_paths.py,
  tests/test_search_protocol.py, tests/test_search_worker.py,
  tests/test_websearch.py
- Status: shipped
- Commit: 2fc9914

---

## 2026-08-04 — The window is open
v1.8 makes `web_search` do something: one approved call sends the model's
query to `https://html.duckduckgo.com/html/` and returns up to five organic
results — title, destination URL, snippet — already parsed and bounded.
cfc never opens a result page, never impersonates a browser, and makes no
automatic retry; one approval is one attempt.

`unavailable` and `failed` split on whether the attempt itself ever started.
A missing Bubblewrap, system Python, `curl`, either worker file, resolver/
name-service support or the CA bundle — and Bubblewrap itself failing to
start — is `unavailable / host/sandbox_unavailable`: no worker exists, no
query was sent, no raw-subprocess fallback. Once Bubblewrap has been
created, a worker timeout, crash or malformed reply is `failed` instead —
cfc cannot know whether curl already reached DuckDuckGo, so the human sees
a warning that the query may already have been sent.

The v1.7 sandbox gains one changed guarantee: `--share-net` replaces the
isolated network namespace, and three small host files (`resolv.conf`,
`nsswitch.conf`, the CA bundle) are read-only-mounted so TLS actually works.
Everything else — no home, vault, repo, `.cfc`, config or inherited
environment; a fresh worker per approved call; the filesystem canaries — is
unchanged and re-proven under the new mount. The destination limit is
enforced in `search_worker.py`'s own code, not by the namespace: one literal
request target, `curl` invoked directly (no shell, HTTPS only, redirects
off, the query supplied over stdin so it never reaches argv or the URL), and
a returned link is decoded as data, never requested.

Protocol bumps to v2. `failure.stage` becomes `host | request | parse`
(replacing the placeholder `search | fetch | extract`), `retryable` and the
host-added `attempts` count are gone — v1.8 makes at most one attempt, so a
retry-policy field would be fiction. Evidence bounds move from placeholders
to the live source's own limits: five results, 600-character snippets.

`ToolContext` gains `external_network`, a second fail-closed capability
alongside `gated`. A private chat is gated exactly like an ordinary one
(decision 15), so its `web_search` refusal couldn't be read off `gated` —
it needed its own property. `chat_context(private=True)` is the one caller
that sets it False; routines never get it either. `/tools` tells a private
chat the real reason (`would send the query off the machine`) without
sending anything itself.

The tool trace is now inspectable rather than a count: the human sees every
title, URL and snippet the model received, in the same order, never the raw
protocol JSON.

Deliberately not built: a domain firewall, a second search provider, result-
page fetching, or a claim that DuckDuckGo's markup — or its terms — will
still hold at the next look.

- Files: search_protocol.py, search_worker.py, websearch.py, context.py,
  tools.py, agent.py, commands.py, main.py
- Status: shipped
- Commit: 679828c

## 2026-08-04 — A web-search boundary before web search
v1.7 gives the chat model a fifth tool, `web_search`, that crosses a real
process sandbox and always answers `unavailable` — there is no search
provider yet, and this version deliberately stops at the first testable
boundary rather than build one. The point is proving the boundary works
before anything lives behind it.

Three new modules. `search_protocol.py` (stdlib-only) owns protocol version
1: request/response shapes, field limits, and the state-combination rules
(`partial` needs both evidence and a failure; `complete` may be empty;
`unavailable`/`failed` never carry evidence). `search_worker.py` is the
worker itself — reads one request, answers `not_available_yet`, exits — and
depends on nothing but the stdlib and the protocol module, because both are
mounted read-only *inside* the sandbox `websearch.py` builds with
Bubblewrap: fresh process/user/mount/network namespaces, an empty root
holding only `/usr` (for a Python interpreter) plus the two mounted files, a
tmpfs `/tmp`, a cleared environment, no route out of the network namespace,
stdin/stdout as the only channel, and `die-with-parent` so a timeout, a
crash or Ctrl-C during launch all still reap the child and return exactly
one typed result. Bubblewrap missing, or the worker unmountable, is the
typed result `sandbox_unavailable` — there is no fallback to a raw
subprocess. The host owns a small bounded retry loop: only a failure typed
retryable, and only when no evidence came back, is retried; `partial`
returns at once rather than risking real evidence on a retry.

Wiring touches `tools.py`, `context.py`, `agent.py` and `commands.py`. Schema
offering, dispatcher permission and the `/tools` listing all read one
registry (`tools.CHAT_ONLY_TOOLS` / `schemas_for()` / `_tool_allowed()`) —
gated off `ToolContext.gated`, the same property that already distinguished
an attended chat from an unattended routine, so a routine never sees or can
reach `web_search` without a second field to keep in sync. The call is
classed consequential (`tools.CONSEQUENTIAL_TOOLS`) and excluded from "allow
all this turn"; its approval panel shows the exact query and `OFFLINE
STUB — no network request`; the model gets the canonical JSON, the human
gets one rendered line (`websearch.summarize`).

Proof: `test_search_protocol.py` (field limits and state rules, no process
involved), `test_websearch.py` (a new boundary suite — canaries planted
under `/home`, the cfc source tree and a vault stand-in, all unreadable and
unwritable from inside the sandbox; a real socket attempt blocked by the
absent network namespace; `sandbox_unavailable` verified by disabling the
`bwrap` guard; a real timeout, crash and simulated Ctrl-C each cleaned up
with no orphan process; the retry budget exhausted against a real,
stateless "always-503" worker; five malformed-response shapes each
collapsing to one `protocol_error`; adversarial evidence text — a forged
tool-call, injected system/XML/Markdown — proven to stay inert history
content, never a second dispatched call; and a private-chat run proving the
launcher writes nothing to disk), plus extensions to `test_tools.py` and
`test_agent.py` for the per-context registry and the schema list a chat turn
now offers. `tests/golden_baseline.txt` re-recorded for the new `/tools`
row — a one-line diff, checked by hand before recording.

What v1.7 does not claim: that web search is safe or working, that
structured evidence text is inert against a live model reading it, or that
any of this extends to routines. `ROADMAP_PRIVATE.md`'s current entry is
stale against this scope (it still says "results come back") and was left
untouched — that edit is Cas's, not this session's.
- Files: agent.py, commands.py, context.py, tools.py, search_protocol.py
  (new), search_worker.py (new), websearch.py (new), tests/test_agent.py,
  tests/test_tools.py, tests/test_search_protocol.py (new),
  tests/test_websearch.py (new), tests/golden_baseline.txt
- Status: shipped
- Commit: 6e228cd

## 2026-08-03 — A confirmation prompt confirms only on Enter (`B-1.6.4-09b`)
`/clear notes` and `/move` both printed `Enter to confirm, or 'back'` and then
compared the typed line to `back` only, falling through to the action for
anything else — so a typo, a stray paste or a half-typed command read as yes.
Found in the v1.6.4 round-2 playtest by typing `apifjaf` at `/clear notes` and
watching four notes archive. The wording was written three times and the third
copy, `/move`'s rename confirmation, was the one that enforced what it printed.

`commands.confirm_or_back` is now the single reader: Enter returns True, `back`
returns False, anything else prints `not recognised` and asks again. All three
sites call it, so the wording and the rule cannot drift apart. `/move`'s rename
confirmation keeps its meaning — `back` there steps back to the collision
prompt, not out of `/move`.

The files are recoverable in both cases (a clear lands in a dated archive
folder, a move states its target first), but `/clear notes` exists so that a
*human* declares the batch closed once the routines have read the inbox; an
accidental clear takes that inbox away from a routine that had not read it yet,
and nothing reports it. The prompt seam had no test at all — `test_notes.py`
covered `notes.py` and `test_mover.py` covered `mover.py`, while the `input()`
shell deciding whether either ran was reachable only by typing. It now drives
`_do_clear_notes` with a scripted `input()` across all four cases, verified by
restoring the old behaviour and watching the typo archive again.
- Files: commands.py, tests/test_notes.py
- Status: shipped
- Commit: 362d4e1

## 2026-08-03 — Show what cfc actually sent on a turn (`W-1.6.4-04`)
A provider 400 always arrived as one opaque `[error] HTTP 400` line, and
nothing else in cfc could show what the request actually looked like —
`api.wire_messages`' transform, an active preset, a tool budget note, tools
being withdrawn, all invisible after the fact. `run_session` now keeps a
process-local `request_capture` list, reset to empty at the start of every
attempted turn (including one refused before any provider call, so an
oversize turn or Main's broken-profile refusal correctly leaves it empty).
`api.call_api` and `api.stream_response` append the real wire payload —
model, `wire_messages`-transformed messages, stream fields, offered tools,
active preset values — to a sink the moment before handing it to httpx,
whenever one is live.

The sink is set only via `api.capture_requests`, a context manager
`run_session` wraps around the streaming and tool-call retry loops — never
a parameter added to `call_api`/`stream_response`/`agent_turn` themselves,
which is what let every existing caller (title generation, `/recall`,
routine execution) and every existing test stub of either function stay
completely unchanged. `agent_turn`'s own internal loop needs no parameter
either: every iteration's `call_api` call happens inside the same context,
so a multi-call tool turn captures every one of them, in order, automatically.

`/status request` renders the capture as `Call N of M`, and a compact
`/status` row says how many calls were captured or `none sent`. The capture
is genuinely process-local — a plain list living in `run_session`'s own call
frame, never a schema field, export field, or error-log field — so a
private chat's request is visible in `/status request` while the session is
alive and gone with it, the same way its messages are.
- Files: api.py, main.py, commands.py, tests/test_agent.py, tests/test_turn_paths.py, tests/test_private.py
- Status: shipped
- Commit: 9d1ca1e

## 2026-08-03 — Open a listed session as the provider kind it actually is (`W-1.6.4-05`)
A wiki page and a routine transcript were listed by `/list sessions` but
could never be opened — `db.resolve_open_target` refused any provider but
an ordinary chat, on the reasoning that neither was a conversation to
resume. That reasoning no longer holds once `run_session` can tell the two
apart on its own: the resolver now refuses only a missing id and Main
(whose fixed profile still only loads through `m`), and returns the row's
own `provider` alongside its id and title. `run_session` derives
`is_main`/`is_wiki`/`is_routine` once, at open, straight off the durable
row — so a numeric hub resume, `m`, and the routines screen's `open <id>`
all reach identical behaviour, and there is no second, caller-supplied flag
carrying that identity between one `run_session` call and the next (the old
`_Open` wrapper and its `routine_transcript` field are gone; a session id
to open next is now a bare int).

A wiki session now prints a settled notice on open — typing continues a
conversation grounded in the imported page, never edits the vault page
itself, and a later re-import may refresh its opening message but nothing
typed after it. Both a wiki page and a routine transcript accept ordinary
free text and persist it in their own session like any other chat; neither
auto-titles (titling is now provider-based and ordinary-chat-only, closing
a latent path that could have silently retitled Main, a wiki page or a
routine transcript the first time someone chatted in one), and neither can
ever rerun the routine or edit the vault — nothing in `main.py` imports
`runner` at all. `/swipe` and `/undo` now refuse visibly on an open wiki or
routine session, checked before any turn classification, since either would
otherwise be able to delete part of the imported page or the routine's own
audit record. `/title` and `/delete chat` already refused these providers
and are unchanged.

`/list sessions` gains a `Kind` column (`Chat`/`Main`/`Wiki`/`Routine`, off
the same provider constants everywhere else uses) and a footer stating
every non-Main id can be opened from the hub; an unrecognised provider
reads as `Chat`, matching the picker's existing fail-open bias. The
picker's own curated table is unchanged and carries no Kind column.

`chunk.py`'s `chunk_new` and `import_wiki.py` now track wiki source
identity at message level rather than session level: a wiki session's
imported-page message is the only one that chunks as `source='wiki'` — a
typed continuation chunks as ordinary chat — determined by the message's
own `source_uuid` matching the session's, with the old provider-only rule
kept as a fallback on a database that has never run an import (no
`source_uuid` column to check, and therefore no wiki rows to misclassify
either). Re-importing an edited page updates only the message carrying its
frontmatter id, never a continuation row, and takes whichever of the page's
own `updated` timestamp and the session's existing `updated_at` sorts
later — so a re-import can no longer walk a chatted-in wiki session's
recency backwards over real conversation activity.
- Files: main.py, db.py, hub.py, chunk.py, import_wiki.py, tests/test_hub.py, tests/test_schema.py, tests/test_screens.py, tests/test_turn_paths.py, tests/test_turn_repair.py, tests/test_private.py
- Status: shipped
- Commit: 4e9b0b7

## 2026-08-03 — Name the post-turn work, and let it leave (`W-1.6.4-02`)
`finishing turn` printed permanently after every non-private turn, whether or
not a title attempt or auto-embed was about to run, and never said when they
were done — the only signal that cfc was still busy was the *absence* of the
next `you>` prompt. `_finish_turn` now decides, before either job starts,
which of them are actually about to run (`will_title`, `will_embed` off
`commands.AUTO_EMBED`) and shows a Rich transient status naming exactly
those — `Titling chat and updating memory...`, `Titling chat...`, `Updating
memory...`, or no status at all when neither runs. The status is the same
kind `agent.py`'s "Thinking..." spinner already uses (standing decision 6):
it clears itself when the `with` block ends, before `_finish_turn` returns
and therefore before the next `read_input()`. Title success and the title/
embed failure lines are unaffected — both still print as durable output.
Private chats stay quiet, unchanged. Rich's status rendering is a no-op
against a redirected non-tty stream, so `tests/test_turn_paths.py` proves
the wording by patching `console.status` itself to a recording no-op context
manager rather than by reading captured text.
- Files: main.py, tests/test_turn_paths.py
- Status: shipped
- Commit: 674dc3d

## 2026-08-03 — Automatic export is an explicit decision, not a config read mid-session (`D-1.6.4-08`)
`run_session` used to read `config.AUTO_EXPORT` itself at every automatic
export point (leaving, `/new`, entering a screen), which is exactly what let
the test suite's own driven sessions fall through to whatever `AUTO_EXPORT`
happened to be and, unnoticed, write fabricated exports into the real
`CHAT_EXPORT_DIR`. `run_session` now takes a required keyword-only
`auto_export` argument with no default, so a caller that forgets it fails
immediately instead of silently choosing either way; `repl()` is the one
production caller and always passes its configured `AUTO_EXPORT`, including
for a nested private side trip and the session a screen hands back.
Explicit `/export` is a different code path and is unaffected. Every direct
test caller now says what it means: ordinary driven tests pass
`auto_export=False`, `test_private.py`'s normal-chat/private-chat control
pair both pass `auto_export=True` (so the private gate, not a false
`auto_export`, is what proves the export never fires), and `golden.py`
passes `auto_export=True` only after redirecting `CHAT_EXPORT_DIR` to its
fixture.
- Files: main.py, tests/golden.py, tests/test_private.py, tests/test_turn_paths.py, tests/test_turn_repair.py, tests/test_process_model.py, tests/test_mainchat_turns.py, tests/test_empty.py, tests/test_screens.py, tests/test_model_tools_notice.py, tests/test_first_message.py, tests/test_model_revert.py
- Status: shipped
- Commit: 7c1f441

## 2026-08-03 — Explain the final v1.6.4 hub behavior (`B-1.6.4-01`, `B-1.6.4-07`, `W-1.6.4-06`)
The v1.6.4 triage corrected three hub boundaries. Automatic allocation no
longer treats a manually chosen chat id as a new floor: the durable sequence
mark stays where it is, and automatic allocation steps over an occupied id.
The hub picker now resolves any ordinary chat by id rather than only the ten
rows it printed, while still refusing wiki pages and routine transcripts. The
session-table ID column measures the ids it contains, and rename feedback names
the old and new titles and says when the redrawn table cannot show the renamed
chat.
- Files: db.py, hub.py, main.py, commands.py, tests/test_schema.py, tests/test_hub.py, tests/test_turn_paths.py
- Status: shipped in the v1.6.4 triage
- Commit: 36e6c69, 1b1ef63, e24b320, f4ba189

## 2026-08-03 — Rename a chat from the hub, through the same operation as `/title` (`W-10`)
`/title <id> <new title>` could rename any session by id from inside a chat,
but the hub had no rename at all — and `/title`'s own write had no refusal
for a missing id, a wiki page or a routine transcript, only for Main.
`db.resolve_rename_target` now resolves an ordinary durable chat by
identity — refusing a missing id, Main, a wiki page or a routine transcript,
without changing a row — and `commands.rename_chat` is the one write-and-
report operation built on it. The hub's new `r` / `rename` (added to
`hub.HUB_KEYS`, so dispatch and help derive from the same table) prompts for
an id, resolves it even when it's outside the ten displayed rows, shows the
current title, then asks for the replacement — a blank at either prompt
cancels. `main.py`'s `h_title` now calls the same operation for its
mutating form; the automatic first-turn title write and `/title`'s
non-mutating forms (bare, `/title <id>`) are unchanged.
- Files: db.py, commands.py, main.py, hub.py, tests/test_hub.py, tests/test_turn_paths.py
- Status: shipped
- Commit: 3129e45

---

## 2026-08-03 — One durable high-water mark for every automatic session id (`Q-1.6-02`)
An automatic id used to be plain SQLite `MAX(rowid)+1` over `sessions`, so a
single chosen high id (`/new 900`, the hub's `c`) permanently became the
floor every later automatic wiki, routine, Main or chat id started from —
oblivious to *why* it was the max, and immune to the row being deleted
afterwards. `db.py` now keeps an explicit one-row `session_id_seq` table,
seeded once from the greatest existing `sessions.id` on a new or old
database and otherwise read-only on connect. `new_session` and
`get_or_create_main` allocate through it — advance, insert, one
transaction, rolled back together on failure; `create_chat` raises it only
when its own successfully-inserted chosen id lands above it, in the same
transaction, so a vacant low id or a refused collision never touches it and
deletion never lowers it. `import_wiki.py`'s standalone connection shares
the same two functions rather than re-deriving the allocation, so a wiki
import allocates through the identical mark. No change to `sessions` and no
`AUTOINCREMENT`.
- Files: db.py, import_wiki.py, tests/test_schema.py
- Status: shipped
- Commit: 3a6fc18

---

## 2026-08-03 — Make the tone direction unanswerable as conversation control (`B-1.6.3-01a`)
A user turn with nothing to answer (`ok`) could come back as the model
acknowledging cfc's own tone direction instead of the conversation — the
direction sits in the request as the last `user`-role message, and nothing in
its text said it wasn't part of the conversation. `governor.TONE_INSTRUCTION`
now states the boundary directly: the direction is cfc control text, never
acknowledged, quoted, summarised or answered, and the real answer is to the
user's preceding message. It rides through unchanged for every caller that
compiles it, including the combined tone-and-trait cadence reminder; position,
`split`, `/continue`, OOC and provider routing are untouched. The playtest
could not prove the boundary — a model behaving and a direction never arriving
produce the same screen — so the triage rebuilt the real `ok` envelope through
the governor, assembly and wire paths and sent it to `google/gemma-4-31b-it`
under both tone texts. The old envelope reproduced the reported answer 3/3;
the v1.6.4 envelope answered the user 3/3, including one reply byte-identical
to the playtest.
- Files: governor.py, tests/test_governor.py, tests/test_turn_paths.py
- Status: shipped
- Commit: 8444ea5

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
