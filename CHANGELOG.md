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

## 2026-08-01 — One honest finisher ends every successful turn, and a failed title call is a real failure (`B-1.3.1-02`, `D-13`, 1.4.1 part 2)
`api.generate_title` no longer swallows every exception into the `"(untitled)"`
sentinel — the same string `main.py` shows before any title has ever been
attempted, which made a failed request indistinguishable from one never
tried. It now raises `TitleGenerationError`, preserving the transport error,
or naming an empty or malformed response, and the caller decides what to
show.

The caller is new too: `main._run_turn`'s streaming and tool paths now hand
their successful answer to one shared `_finish_turn`, which owns the context
bar, a visible `finishing turn` marker, the eligible title attempt, automatic
embedding, and only then the blank line that used to print *before* that
work — which is the bug. cfc looked ready for the next line while it was
still silently titling and indexing, and anything typed in that window could
be echoed straight into the chat as a message nobody wrote. Eligibility to
title is now the durable `count_chat_user_turns()` value already read for the
governor (`turn_count == 1`), not the `"(untitled)"` string, so a reopen or an
earlier failed attempt never hands the job to a later turn — closing `D-13`'s
second half along with the display fix. A title failure logs once, through
`errorlog.log_error(..., where="title")`, gated out of a private chat exactly
like auto-embed already is.

- Files: api.py, main.py, tests/test_titles.py, tests/test_turn_paths.py, tests/test_private.py
- Status: shipped
- Commit: pending

---

## 2026-08-01 — A checked inventory of every system-layer injection seam (`W-1.4-05`, 1.4.1 part 1)
`SYSTEM_INJECTIONS.md` names every seam that puts words in front of the model
the model didn't say and the user didn't type: assembled prompt/persona/traits
and tool guidance, First Message and the governor's direction, the tool turn's
advisory rider and its synthetic stand-ins (`LIMIT_MESSAGE` and friends), a
routine's own opening turn and assembled system context, recall's grounded
synthesis, title generation, `/remember`'s excerpt block, an attachment's
envelope, and the two indirect transforms (`runner.fill_placeholders`,
`api.wire_messages`).

It's checked rather than trusted: `tests/test_system_injections.py` derives
the same inventory from source — an AST walk finds every top-level function
that literally builds a `{"role": ...}` message dict with a hardcoded role
other than `"tool"` (the API's own role, `agent._answer`'s alone to build) —
and fails if a live producer has no anchor, or a documented anchor no longer
resolves. One function, `main._run_turn`, is excluded by name: it replays the
user's own typed text and the model's own returned answer, not new content —
everything else in the document is discovered, not hand-listed. Proved by
disabling it both ways while developing: an anchor removed, and a stale one
added, each fails a distinct assertion.

- Files: SYSTEM_INJECTIONS.md, tests/test_system_injections.py
- Status: shipped
- Commit: a6e8e38

---

## 2026-08-01 — `/add <path>` works again in Main chat (`B-1.4-01`, 1.4 triage)
Main's fixed profile was enforced by a guard over the whole of `/add`, placed
above the branch that attaches a file — so `/add <path>` in Main never reached
`do_attach` and answered with the profile refusal instead. The refusal now sits
at the *layer*: an explicit `/add prompt|persona|trait …` refuses, a bare name
that resolves to a pool item refuses, and everything else takes the ordinary
path. The pool search still runs first for Main, so `/add relax.md` still means
the trait rather than a file that isn't there — it ends in the refusal, not in
"no such file". `/remove`'s guard is unchanged and still covers its whole tail,
because everything below it only ever detaches a pool layer; `#n`, tags and
excerpts were already handled above it. The refusal string is now one function
with the verb as its argument, since it had reached three call sites.

Blocked the tag: the version's own work order claims attachments remain
available on Main, and `tests/test_mainchat_turns.py` asserted that facility
using a tag, which is the one part of `/add` that was never behind the guard.
It now drives a real file attachment through Main end to end.
- Files: main.py, tests/test_mainchat_turns.py
- Status: shipped
- Commit: c3650df

---

## 2026-08-01 — Actionable advice for an unreachable hosted embedder (`W-0.9.1-05`, 1.4 part 5)
`hosted`'s diagnosis stayed distinct — cfc still has no local service to
start for a remote endpoint, so `preflight.ensure()` still returns early
rather than reaching the `lms` fixer — but its message was the diagnosis and
nothing else: "not something cfc can start; memory will be degraded." now
says to check the connection, `EMBED_BASE`/`EMBED_KEY` in `config.py`, and
the provider's status, then retry `/connect embedding`. `ui.CONNECTION_STYLE`
carries the same actionable text to the hub light, `/connect` and the config
screen — one shared mapping, so wording can't fork per renderer — and stays
the one red state, since `ensure()` genuinely never runs its local fixer on
it; only the wording changed, not the recoverability split decision 16 pins
the colour to. `commands.connect_embedding()`'s own fallback line ("start LM
Studio yourself") used to fire whenever `find_lms()` came back empty, which
is also true on a machine using a hosted embedder that never installed LM
Studio at all — now gated on the state actually being local.
- Files: preflight.py, ui.py, commands.py, tests/test_connection.py,
  tests/golden_baseline.txt
- Status: shipped
- Commit: 283a6fa

---

## 2026-08-01 — `/model` says when the switch turns tools off (`W-1.3.1-01`, 1.4 part 4)
The header and `/tools` already knew a model couldn't use tools; `/model` —
the one command that actually changes the active model — was the one switch
that hid the consequence, so the first sign used to be a later turn quietly
not offering them. `/model` now prints `Note: <tools_unsupported_reason(...)>`
immediately after a successful switch, through the exact seam the header and
`/tools on` already read — no second capability list. Only when there was
something new to say: a session with tools already off, or `TOOLS_ENABLED`
off deployment-wide, keeps its own message and prints nothing extra here.
Doesn't touch the switch/revert policy at all.
- Files: main.py, tests/test_model_tools_notice.py (new)
- Status: shipped
- Commit: c88e0dd

---

## 2026-08-01 — Main chat: the hub doorway and the turn pipeline (1.4, part 3)
`m` at the hub now opens one durable Main chat: the first `m` validates the
vault bundle (`mainchat.load_creation_bundle()`) and creates it via
`db.get_or_create_main`; every later `m`, or typing its numeric id, reopens
the same row through the identical fixed-profile path — the session's
`provider` selects Main's behaviour, never the entry key. A bundle problem
prints exactly what's wrong and leaves the hub as it was: no blank row, no
ordinary-chat fallback. The empty-hub branch no longer auto-creates a chat
before any input is possible, so a first-ever action can be `m`, `p` or `n`.

Inside Main, `system prompt.md` and `persona.md` are read live and reassembled
immediately before every request — never cached on the session row, per
Concept.md's "no rewriting database metadata" — so a vault edit reaches the
very next turn. A broken live file refuses the turn before anything is
persisted. The frozen First Message (from `first message.md`, once, at
creation) is untouched by later edits or removal of that file; a Main row
missing it is corruption and refuses to open, recoverable only by deleting
and recreating. `/add`, `/remove` and `/title` refuse to touch Main's
identity; tags, attachments, export, search, `/model`, `/tools` and
`/database` all still work, because none of them change what Main *is*.

The hub renders Main's row distinctly (`hub._add_rows`, keyed on `provider`,
not the title string, since a title is user-editable everywhere else and
could coincidentally read "Main"). No new turn implementation, transcript
format or deletion path — Main rides `assemble_system`/`governor` and the
existing chat-shaped delete/index cleanup exactly as any other session does.
- Files: main.py, hub.py, commands.py, tests/test_hub.py,
  tests/test_mainchat_turns.py (new)
- Status: shipped
- Commit: 3b534d2

---

## 2026-08-01 — The selected model is process-wide, not per session (`W-1.3.1-03`, 1.4 part 2)
`run_session` used to read a session's own stored `model` column at open, so
leaving one chat for another (or back) could silently change what "the
selected model" meant. `/model` now sets one selection — `main._process_model`
— that starts at configured `MODEL` and every entry into `run_session` reads:
a fresh chat, a reopened one (its own stored value is no longer consulted),
`/new` (deliberately doesn't reset it), a private side trip in either
direction, and a return from a command screen. A session's `model` column is
still written on every switch and on every open — it records what the process
was using while that session was active, so nothing reading it back
(header, export) contradicts itself — but it no longer chooses what a reopen
starts on. Routine model precedence (own pin, caller model, routine default)
is untouched — routines run headless through `runner.py`, never through this.

Required alongside Main chat rather than after it: Main cannot honestly claim
a single "process model" while the same value still meant something different
every time the conversation on screen changed.

`tests/golden.py`'s `capture()` needed one more explicit reset
(`chat.set_process_model(FIXTURE_MODEL)`) — the generic per-module attribute
loop patches `main.MODEL` but not the value computed from it at import time,
which is the exact "golden baseline pinning config.py" bug class HANDOVER's
Scars section already names.
- Files: main.py, tests/golden.py, tests/test_model_revert.py,
  tests/test_turn_paths.py, tests/test_process_model.py (new)
- Status: shipped
- Commit: b927d79

---

## 2026-08-01 — Main chat: the profile bundle loader and database identity (1.4, part 1)
Foundation for the durable Main chat: a new `mainchat.py` owns the vault
bundle's fixed filenames, path resolution and validation (creation needs all
three files; reopening/a turn needs only the two live ones, never rereading
`first message.md`), and `db.py` gains `PROVIDER_MAIN`, a get-or-create
operation, and a partial `UNIQUE` index that makes a second Main row
unrepresentable rather than merely unlikely. Not yet reachable from the hub
or a session — that's the next commit.
- Files: mainchat.py, db.py, config.example.py, tests/test_mainchat.py,
  tests/test_main_identity.py
- Status: shipped
- Commit: d705440

---

## 2026-07-31 — First Message visibility, export confidence, an honest path name (1.3.1)
A light patch carrying one v1.3 finding and closing two open tracker rows: a
First Message now has somewhere to be seen, the export destination has a name
that says what it is, and `/export`/`/routine`'s listing were quietly already
mostly tested but the docs still called them hand-verified.

**`/status` names the First Message state (`W-09`).** One row, shown only
when a persona is attached — the ordinary no-persona case stays quiet rather
than growing a fourth inactive row. `pools.first_message_status()` shares its
lookup with `load_first_message` (`pools._first_message_lookup`), so the row
can't drift from what a session actually opens with: `ready`, `none for
<persona>`, `not configured`, or `unavailable — <reason>` for an unreadable
directory or file, which stays a visible failure rather than folding into
"none". This was the finding underneath v1.3's `1.3-01`: the playtest lost
half its time to a silently unconfigured feature with nowhere to check.

**`CHAT_EXPORT_DIR` replaces `VAULT_PATH` as the export-destination key
(`W-0.9.1-01`).** The old name was the one naming trap in the layout —
indistinguishable at a glance from `VAULT_ROOT`, the actual vault, three
lines below it. `export.chat_export_dir()` is the one seam that resolves it:
the new key if set, else the legacy name, so an existing `config.py` that
still only defines `VAULT_PATH` keeps exporting with no forced edit.
`screens.py`'s two `/config` renderings read through the same function, so
export and `/config` cannot disagree about which folder is configured.

**`/export` and `/routine`'s listing are covered, not hand-verified
(`W-02`).** `tests/test_export.py` now drives a representative exported
document — system prompt, persona, tags, an attachment and a tool call/result
pair — read back from a temp db and vault: frontmatter totals, transcript
order, a title-safe filename that replaces rather than duplicates on
re-export, and an absent session that creates nothing. `tests/test_routines.py`
adds `show_routines()` coverage: an empty store, and a mixed one (healthy,
disabled, invalid-but-parseable, and a file that doesn't parse at all) —
`do_routine` and `run_routine` were already covered, which the stale
`HANDOVER.md`/`README.md` claim had stopped reflecting.

- Files: pools.py, commands.py, export.py, screens.py, config.example.py,
  README.md, HANDOVER.md, tests/test_pools.py, tests/test_first_message.py,
  tests/test_export.py, tests/test_private.py, tests/test_routines.py,
  tests/golden.py, tests/golden_baseline.txt
- Status: shipped
- Commit: 011d604

---

## 2026-07-31 — The active conversation governor (1.3)
One request envelope (`governor.py`) now carries every cfc-authored direction
that must reach the model without becoming a line in the conversation —
First Message, `/continue`, OOC, periodic trait refresh and the bounded tone
cue are five triggers over that one primitive, not five prompt formats. A
directed turn prints one dim line naming what cfc added
(`cfc -> tone check · trait: relax`) immediately before the answer; the
direction itself never touches `messages`, replay, export or the memory
index, in both a normal chat and a private one.

**The envelope and its order.** `governor.compile_messages(prefix,
first_message, history, instruction, split=...)` builds the request in one
place for both turn paths: persona/system/traits, the session's frozen First
Message as an assistant turn, durable history, then at most one wrapped
`[cfc direction]…[/cfc direction]` message in a `user` slot. `split` is what
keeps the direction pinned at its original position across a growing tool
loop — `agent_turn` computes it once at entry, so a multi-call turn never
re-appends the direction after a tool result. Tone applies to every ordinary
turn; a trait reminder joins it on a cadence turn (`GOVERNOR_TRAIT_INTERVAL`,
default 6, a pure function of `db.count_chat_user_turns` so it re-derives the
same answer across a reopen); OOC and `/continue` suppress both and carry
their own single instruction instead. Driven against the real configured
provider (nano-gpt, GLM-5.2:thinking): an ordinary directed turn, OOC,
`/continue` after a First Message, and a later replay with two consecutive
assistant rows all round-tripped cleanly — the shape is accepted.

**First Message.** A persona with a matching `.md` file in
`FIRST_MESSAGES_DIR` freezes that text onto a session the first time it opens
with no chat turns yet — a name, text and opening time snapshot, never a
`messages` row, so editing the source file only ever changes a *new*
session's opening. Shown on every reopen, inserted before durable history on
every request, counted in the hub's Messages column and an export's
`total_messages`, and included at the export's head. An unreadable companion
is a visible failure; a missing one is silent, and the two must not read the
same.

**`/continue`** spends its reserved verb: one direction asking the model to
continue its last substantive answer (the First Message counts), no new user
row, no title generation, no tone/trait. Refuses visibly with no API call
when there is nothing to continue from, or when given arguments.

**OOC** has exactly one grammar (`parse.parse_ooc`): a whole line of the form
`((direction))`, start to end. Inline markers, unmatched parens and trailing
text are ordinary prose — the failure mode this guards is a sentence that
happens to contain double parentheses silently vanishing from the
transcript. An empty `(( ))` refuses without a provider call.

**Five smaller fixes travelled with it, all from the carried tracker rows.**
`run` from the routines screen now resolves like `/routine <name>` would —
the chat model that opened the screen, an unpinned routine's own pin still
winning (`B-05`). Ctrl-C during a routine records `cancelled` rather than
crashing the REPL uncaught, keeps the transcript and touched-file evidence,
skips `on_failure`, and — via `routines.last_settled`, which schedule.py now
reads instead of `last_run` — cannot make a due routine look satisfied for
the day or spend a retry slot a real failure would have (`W-0.9.1-06`). The
golden harness's `/tools` fixture points `commands.TOOLS_ROOTS`/`WRITE_ROOTS`
at a real temp directory outside the checkout instead of Cas's own configured
roots, guarded by a new `assert_not_repo_or_real_roots` (`D-11`); a prior
attempt at this had repointed the *real* `config.WRITE_ROOTS` at a path
inside the repo and hit `ScopeError` for exactly the right reason, which is
why this version patches the display copy at its own seam instead. The
picker's `Msgs` column is `Messages` (`W-0.9.1-02`); `/connect embed` is
accepted alongside `embedder`/`embeddings` (`W-0.9.1-08`); an unknown
`/connect` target says "connection" and "available connections"
(`W-1.1.1-01`); entering a command screen says `help` exists, the same
pointer the screen's own refusal already gives (`W-1.2.1-02`).
- Files: governor.py (new), main.py, agent.py, parse.py, db.py, pools.py,
  export.py, hub.py, commands.py, screens.py, routines.py, runner.py,
  schedule.py, config.example.py, tests/test_governor.py (new),
  tests/test_first_message.py (new), tests/test_export.py (new),
  tests/test_golden_fixture.py (new), tests/test_schema.py, tests/test_pools.py,
  tests/test_agent.py, tests/test_turn_paths.py, tests/test_private.py,
  tests/test_parse.py, tests/test_routines.py, tests/test_schedule.py,
  tests/test_screens.py, tests/test_hub.py, tests/test_model_revert.py,
  tests/golden.py, tests/golden_baseline.txt
- Status: shipped
- Commit: pending

## 2026-07-31 — Honest model recovery and repairable advice (1.2.1)
Three changes, all about a model config or a recovery path saying more than it
actually knows.

**One model-config boundary replaces four collections.** `MODELS`,
`TOOLS_MODELS`, `ROUTINE_MODELS` and `MODEL_LIMITS` used to be four separate
lists nothing forced to agree — a typo in `TOOLS_MODELS` failed by doing
nothing at all, which is what `commands.unknown_model_ids()` existed to catch.
The new `models.py` reads one ordered `MODELS = [dict(id=..., tools=...,
routine=..., routine_default=..., limit=...), ...]` list instead, validates
every record at import (a malformed one raises `ModelConfigError` naming the
id and field, never silently reads as unsupported), and answers every question
a caller used to ask three collections: `listed_ids`, `known_ids`,
`supports_tools`, `is_routine_vetted`, `routine_default_id`, `context_limit`.
A config.py still in the old shape is translated automatically, with one
warning naming `config.example.py`, printed after the splash the same way the
old typo warning was. `commands.unknown_model_ids`/`warn_unknown_model_ids`
are gone — there is nothing left to cross-check. `config.example.py` and
Cas's `config.py` are both migrated; the real config's four previously-hidden
non-thinking routine variants (`ROUTINE_MODELS` entries that were never in
`MODELS`) now get their own listed records instead of being invisible to
`/list models`, and `deepseek-v4-pro-cheaper` keeps `routine_default` — that
was `ROUTINE_MODELS[0]`, unchanged.

**Tool-capability wording stopped naming a config attribute that no longer
exists as a separate list.** The session header, `/status`, `/tools` and the
one-time `/tools on` notice all said "not in TOOLS_MODELS"; they now say a
model doesn't support tools and name the tool-capable ones, through one shared
`commands.tools_unsupported_reason`. An out-of-range `/model <n>` now explains
that digits pick a row off `/list models` rather than setting a raw id.

**The connection advice names both places it can be typed** (`B-04`). Every
fixable `ui.CONNECTION_STYLE` row named only `/connect embedding in a chat` —
true at the hub and in chat, wrong on the config screen, which is
command-driven (decision 17) and refuses the chat form outright while its own
`connect embedding` does the same thing. The string now names both; no
`where=` parameter, no second copy — the shape `B-04` argued a producer/parser
fork would be.

**A model revert no longer lands on a model already proven dead**
(`B-1.2-04`). `run_session` keeps a `rejected_models` set beside
`revert_model`, adding the current model on an HTTP 400 (never a transient or
a transport failure) before deciding how to recover. If the fallback
`revert_bad_model()` would switch back to is itself in that set, it disarms
instead of reverting, leaves the just-rejected model selected, and says
plainly that neither id is known-good — rather than printing "switched back
to X" over an X the same session already had refused. In-memory only, so it
resets every session and a private chat's throwaway connection carries it the
same way.
- Files: models.py, commands.py, main.py, agent.py, hub.py, runner.py, ui.py,
  routines.py, config.py, config.example.py, tests/test_models.py,
  tests/test_model.py, tests/test_model_revert.py, tests/test_attach.py,
  tests/test_turn_paths.py, tests/test_routines.py, tests/test_connection.py,
  tests/test_hub.py, tests/golden.py, tests/golden_baseline.txt
- Status: shipped
- Commit: pending

## 2026-07-31 — The wiki screen stops telling you to type `/wiki` (B-1.2-01)
The wiki screen printed `/wiki diff [all] | /wiki commit [all] <message>` and
then refused that exact line — commands.py's wiki output was written for a
chat, and 1.2 gave it a second reader. `show_wiki_status`, `show_wiki_diff` and
`do_wiki_commit` take a `lead` (`/wiki ` in a chat, empty on the screen); it
defaults to the chat form so a screen call site that forgets reproduces a
visible refusal rather than telling a chat user to type a word that goes to the
model. The same lines said `all` where `vault` is the canonical scope word —
decision 13's rule against re-teaching a retired word, in a suggested command
line rather than in `config.example.py`.
- Files: commands.py, screens.py, tests/test_screens.py
- Status: shipped
- Commit: eafbbdd

## 2026-07-31 — Command screens: config, wiki, routines (1.2)
Bare `/config`, `/wiki` and `/routine` now open a command screen instead of a
one-shot print or, for `/wiki`/`/routine`, the direct-run form. A screen is a
small REPL of its own: every submitted line is either a recognised action or
a visible `Not a <screen> command: …` refusal, never a chat message — free
text cannot start a model turn from inside one. The existing quick forms
(`/wiki diff ...`, `/wiki commit ...`, `/routine <name>`, `/routine new`)
are unchanged and still run straight from chat.

`screens.py` owns the three command tables (parsing, generated help,
navigation, rendering); the table is the only source both help and dispatch
read, so a command can't be typeable-but-undocumented or documented-but-dead.
Switching screens (`config`/`wiki`/`routine`) replaces the current one rather
than nesting, so there is no stack to unwind and no way to recurse back into
a chat. `main.py`'s session loop grew a small return protocol
(`run_session()` now returns `None` or an `_Open`) so a screen can hand back
either "to the hub" or "open this persisted routine transcript", without
`screens.py` ever calling `run_session()` itself. A screen entered from a
private chat is handed the durable connection, never the private one — the
private chat's own history never reaches it.

The wiki screen adds one piece of state beyond what already existed: a
transient, per-visit review, armed by a successful `diff` and re-checked on
every way out (`q`, a screen switch, or EOF) against the same scope. Zero
changes clears it silently; the same changes ask whether to leave them for
later; changed files say so distinctly (`reviewed changes have changed since
the diff`). Nothing is written or judged — git remains the truth, same
`wikigit` calls the existing quick forms already used.

The routines screen closes `D-10` (a routine that fails `validate()` used to
read identically to a healthy one on the hub) — the hub itself is untouched;
it gains one conditional line (`! N routines have problems — open a chat and
type /routine`) when `hub._routine_problem_count()` finds anything, computed
separately from the freshness light so a validation problem can never bend
what that light means. `routines.py` gained `RunRecord`/`parse_log_line`,
making a run's session id an explicit field `append_log` writes rather than
prose `runner.py` spliced in by hand — old `(session N)` log lines still
read, since the shape didn't change, only how it gets there. `db.py` gained
`routine_session()`, a provider-checked lookup so the screen's `open <id>`
refuses a stale or non-routine reference rather than opening whatever chat
happens to hold that id.

`commands.show_config` is gone — superseded by the config screen, and its
field set never matched what the new screen needed. `create_routine()` and
`_routine_abandoned()` take a `return_to` so the same creation flow, reused
by the screen, says where it actually lands rather than always claiming
"back in the chat."

- Files: screens.py (new), main.py, commands.py, routines.py, runner.py,
  db.py, hub.py, tests/test_screens.py (new), tests/test_routines.py,
  tests/test_private.py, tests/golden.py, tests/golden_baseline.txt
- Status: shipped
- Commit: 1a91f21

## 2026-07-30 — Two retired `:` spellings that reached a user, not a comment
`D-1.1-09` swept comments and docstrings; these two are runtime strings and
were out of that scope on purpose, flagged by the coder rather than absorbed.
The private-chat banner told every private session that *"an explicit
`:export`"* is the one thing reaching disk — printed on screen, naming a verb
retired in v0.9 — and `_session_arg`'s fallback usage line built itself as
`f":{cmd.verb} <session id>"`, so `/export abc` or `/delete chat abc` answered
a typo with a second one. Same class as `B-0.9.1-02` (`config.example.py`'s
twelve retired `:` commands) and it fails the same way standing decision 13
describes: an unrecognised verb is an API call, not an error, so a user typing
what cfc told them gets a confused answer rather than a correction. `B-03`.

Neither string is in the golden baseline, so the fix is baseline-neutral and
the 379-line check is identical either side of it.

- Files: main.py
- Status: shipped
- Commit: 43c5843

## 2026-07-30 — v1.1.1: a status-coded hiccup no longer costs a model switch, and four playtest fixes
The v1.1 playtest patch. Six fixes, no new roadmap capability.

**`W-1.1-03`: auto-revert now tells a hiccup from a rejection.**
`api.TRANSIENT_STATUS_CODES` gains 504 alongside 429/502/503 (`D-1.1-05`; 408
stays out — resending a request the client itself timed out proves nothing).
`handle_turn_error` now checks `api.is_transient_status` before reverting a
just-switched model: a transient leaves the new model selected and the revert
armed for a real rejection, while only a rejection or an untyped error backs
out to the model you were on. `D-12`'s remaining stale claim — a
`tests/test_model_revert.py` docstring that still described arming as scoped
to unverified models rather than every switch — is corrected in the same edit.

**`/clear notes` says where it's moving things (`D-1.1-08`).** The preview
now names the guarded notes-inbox path and the cleared-notes archive root, and
the confirmation prompt is no longer indented into the filename list, where a
seventh line could read as an eighth note.

**The hub picker shows all seven current routines (`W-1.1-04`).**
`hub.HUB_ROUTINES` was 5; a seventh routine fell off the panel with no signal
it existed. Still a bounded display cap, not derived from the vault.

**`/model` takes a number as well as a name (`W-1.1-10`).** `/list models`
numbers its rows in displayed order; `/model <n>` switches straight to that
id, with no second picker, and an out-of-range number leaves the model
unchanged with its own message.

**Retired `:` command spellings are swept from source comments and four test
docstrings (`D-1.1-09`)** — about 25 instances across nine modules.
`agent.py`'s long invariant comment above the tool-loop `try/finally` is cut
to three lines and a pointer to `HANDOVER.md` standing decision 2, which is
what it was restating in full.

- Files: api.py, main.py, commands.py, hub.py, mover.py, runner.py, wikigit.py,
  preflight.py, complete.py, ui.py, agent.py, README.md,
  tests/test_routines.py, tests/test_model_revert.py, tests/test_model.py,
  tests/test_hub.py, tests/test_attach.py, tests/test_complete.py,
  tests/test_wikigit.py, tests/golden_baseline.txt
- Status: shipped
- Commit: a2062cd

## 2026-07-30 — Put the proposal's title last on its line
The v1.1 playtest's one tag-blocking finding (`W-1.1-07`). `/file <title>`
matched correctly the whole time; the screen it was read off did not let you
tell where the title ended. `/list outbox` printed
`20260730113101.md  —  Agentic Risk Standards for cfc   [wiki]`, and five
attempts at pasting that line back all failed — the corpus tag trailed the
title with nothing marking the boundary. The tag now leads
(`[wiki]  20260730113101.md  —  Agentic Risk Standards for cfc`), so the title
runs to end-of-line and a select-to-EOL is exactly the argument `/file` takes.

`tests/test_mover.py` pins the **round trip**, not the punctuation: it renders
a tagged proposal's label, slices whatever follows the dash, and asserts
`match_title` finds it. A test against the literal label would have passed
throughout the failure. Verified by reverting the render and watching both
assertions fail.

- Files: commands.py, tests/test_mover.py
- Status: shipped
- Commit: 53a7f1e

## 2026-07-30 — Name it, don't count it: /move, /clear notes, and title filing
v1.1. Three focused commands close three pieces of workflow that had been
number-only or manual: `/file` now also takes a proposal's exact title,
`/move` guides one loose outbox file to a human-picked destination, and
`/clear notes` archives the notes inbox in one confirmed batch — closing
`D-02` and `W-05`.

**They share filesystem facts, not an abstraction.** Title extraction and
matching (`mover.proposal_title`/`match_title`) live beside proposal
discovery, so `/list outbox`'s title and `/file <title>`'s match are one read,
not two frontmatter parses that can drift. `/move`'s destination resolution,
collision handling and the write itself reuse the same `path_guard`/deny-list
machinery `/file` already validates a suggested `destination:` against — `/move`
adds a **verified-replace guard**: typing `replace` in full is intent, and
git proving the target is tracked and unmodified (`wikigit.is_tracked`, new)
is the recoverability half; neither substitutes for the other, and both are
re-checked at the write, not only at the plan the human read on screen.

**A small `notes.py` owns the notes inbox** — validation against `MOVE_ROOTS`,
one-level inventory, the backstage `note template.md` exclusion, and the
batch move — so `/status`'s new row and `/clear notes` share one inventory and
cannot disagree about the count. `NOTES_DIR`/`NOTES_ARCHIVE_DIR` are new,
optional `config.py` settings, explicit rather than derived from `VAULT_ROOT`.
`/status` also stops rendering "Last turn" in the same dim grey as an inactive
state (`W-0.9.1-09`) — ordinary workflow information, not a warning.

**`Q-01` closes by documentation, not a feature.** cfc's database durability
stays local-only: verified rolling snapshots, no off-machine copy of cfc's
own making. `README.md`'s *Backups* section gains the optional, user-run
pattern (`backup.py --force`, then copy the snapshot yourself); `HANDOVER.md`
states the same boundary as settled.

- Files: mover.py, wikigit.py, notes.py (new), commands.py, main.py, parse.py,
  hub.py, config.py, config.example.py, README.md, HANDOVER.md,
  tests/test_mover.py, tests/test_notes.py (new), tests/test_parse.py,
  tests/test_private.py, tests/golden.py, tests/golden_baseline.txt
- Status: shipped
- Commit: 9ac48d6

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
- Commit: 80cb0cd

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

