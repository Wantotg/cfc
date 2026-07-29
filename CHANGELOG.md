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

## 2026-07-29 — The hub's broken-routine blind spot gets written up
v1.0 step 5, `D-10`. **A drafting step, not a build**, and it was listed as one
so this wouldn't get built from a one-line tracker row. That was the right call:
the row named the smallest of three tiers.

**Driven rather than read.** A temp routine folder with one healthy routine and
one of each breakage, rendered through the real `_routine_rows` /
`_print_routines`. A file that won't parse is **absent** from the panel —
`_routine_rows` unpacks `list_routines()` and discards `bad`. A malformed
*trigger* is **dim**, beside `command` and `disabled`, which is the conflation
`_freshness`' docstring already flagged.

**And in the middle, the one nobody had written down: a routine that parses but
fails `validate()` renders green.** Prompt file deleted, everything else fine —
green, byte-identical to a healthy row, because nothing in `_freshness` consults
`validate()`. Green is the strongest thing that column says, *nothing is owed*,
and it was being said over a routine that cannot run.

That is standing decision 16's own failure shape — green over a dead server —
one panel up the screen from the light the decision was written for, reached
through a column that obeys it exactly. The colour is not wrong about what it
measures, and that is the trap: **it answers *is a run owed* while the panel is
read as *is this still working*.** The two questions agree on every routine
except a broken one.

**The entry holds two questions open rather than answering them**, which is what
a drafting step is for: whether *cannot be owed a run* and *cannot be read* may
stay one colour, and what the hub should show given what checking costs. The
second has a measurement attached, taken on the real vault (six routines, 21
roots, over `/mnt/c`): `list_routines()` is 22 ms, which the panel already pays;
adding `validate()` to all six is ~205 ms, against a connection light that costs
~0.16 s — so full validation roughly doubles the wait in front of the picker.
`show_routines`' own comment blesses that cost with *"this screen is on
demand"*, which the hub is not. Three shapes are written up, and the cheapest —
showing the `bad` list already computed and thrown away — closes the third tier
completely for nothing.

Also recorded: `HUB_ROUTINES` is 5 and never-run routines sort last, so a
brand-new broken routine is both the likeliest to be never-run and the first to
fall off the panel. Confirmed with nine routines.

`hub._freshness` and standing decision 16 both said the blind spot was the dim
conflation. Both now point at the entry and name the green case — a correction,
not a restyle. No behaviour changed in this commit.

- Files: BACKLOG.md, HANDOVER.md, hub.py (docstring), CHANGELOG.md; TRACKER.md
  (gitignored)
- Status: shipped
- Commit: pending

## 2026-07-29 — `/routine new` stops discarding itself
v1.0 step 4, `D-0.9.1-03`. Typing `hhmm` at the trigger threw away the name, the
prompt, the roots and the model — six answers — and then returned to the REPL
without saying so, which turned the next line typed into a chat message.

**Early *and* late, never early instead of late.** `Routine.validate()` and
`save_routine`'s refusal are untouched: standing decision 8 rests on an invalid
routine being unsaveable, and a file hand-edited in Obsidian never passes
through the creation flow at all. What changed is that `trigger` and
`on_failure` now re-prompt against `routines.trigger_problem` and
`on_failure_problem` — **the same functions `validate()` calls**, lifted out of
it rather than written beside it. A field accepted as you type it therefore
cannot be rejected at save. Two checks maintained separately would have
disagreed the first time `weekly` grew a variant, and the disagreement would
have surfaced as this same bug in a different hat.

**Four holes, and the fourth was the one that wrote a file.** `select_model`
returns `None` only when the human backed out of its picker, and that was read
as *no model pin* while every other `None` in the flow returns — so cancelling
there saved the routine you were in the middle of abandoning. Confirmed by
reverting the fix and watching `cancelled-model.md` land on disk. The other
three: the two raw fields above, and a taken id, which is now caught at the name
prompt and re-asked rather than raising `<id>.md already exists` after every
question has been answered. `save_routine` keeps its own id check — the early
one can lose a race with a second cfc, and the late one is the guarantee.

**The exit was the half that actually bit, and the entry said so.** A prompt
flow that returns silently is decision 13's failure shape (unrecognised input is
not an error, it is an API call and a confidently wrong answer) reached through
an abandoned form instead of a missing verb. Every way out of `create_routine`
now announces itself: *"No routine created — back in the chat, so the next line
you type is a message."* Nothing enforces this for prompt flows added later,
which is noted at standing decision 8.

**The placeholder was read as a placeholder, and that was fair.** `trigger
(command, or HHMM)` against a default of the literal word `command` makes `HHMM`
a consistent reading of the screen, which is exactly what was typed back. It now
reads `(command, 0300, or weekly 0330)`.

Driven rather than reasoned about: `tests/test_routines.py` scripts `input()`
and runs the reported flow, the duplicate name, the cancelled picker and an
abandoned exit. Each of the four assertions was verified by reverting its own
fix and watching that one fail.

- Files: commands.py, routines.py, tests/test_routines.py, README.md,
  HANDOVER.md, BACKLOG.md, legacy/BACKLOG.md, CHANGELOG.md; TRACKER.md
  (gitignored)
- Status: shipped
- Commit: b63f3d7

## 2026-07-29 — A denied tool call stops reading as a fault
v1.0 step 3, `B-0.9.1-01`. Denying a call printed `← error: user denied`, which
is the model's payload echoed at the person who did the denying.

**Fixed at the render, never at the payload.** `{"error": "user denied"}` still
reaches the model unchanged, because `gate`'s design is that a refusal arriving
as an error is what makes refusing a normal move in the conversation rather than
an abort — changing the payload would have quietly told the model a human's
decision was a system fault. `agent._render_result` recognises the two verdicts
that are yours and prints `← read_file denied at the prompt` in plain dim,
keeping dim red for errors that are errors. The tool name is passed in, as the
report asked; that is the signature change `BUGS.md` flagged so it wouldn't be
discovered mid-fix.

**"at the prompt" earns its words.** `gate_and_dispatch` already prints
`auto-denied <tool>: <why>` when the jail refuses a call before you are asked,
and that one is a real error and stays red. Two refusals a line apart have to be
tellable apart, and "denied" alone doesn't do it.

**The producer/parser pair was closed rather than tabulated, and that is the
part worth keeping.** `agent.py` reading a string `commands.py` writes is a
matched literal at each end across a module boundary — a seventh row in
`HANDOVER.md`'s table. But `agent.py` already imports from `commands.py` and
nothing imports back, so the strings became `commands.DENIED` / `SKIPPED` and
there is nothing left to drift. That table's own first rule is *keep producer
and parser in the same module where the dependency graph allows*, and this is
the first time it has been the reason a row was **not** added. Noted at the
table, because a pair that could have been closed and was merely pinned is one
that drifts eventually. (The line under it said *add a sixth* while the table
already had six; corrected to seventh.)

**The guard's direction is the inverse of the report, and it is the one that
matters.** A real tool error styled as a polite decline reads as something you
chose, so a run that should have stopped keeps going and looks fine doing it.
The match is the two constants and nothing else — no prefix test, no "looks like
a verdict" heuristic. `tests/test_agent.py` pins both directions and runs the
real `gate_and_dispatch` into the real renderer for both verdicts with no
literal between them. Verified by breaking it two ways: reverting the render
fails the denial assertions, widening the match to a default fails the error
ones. Both existing payload pins in `test_gate.py` and `test_agent.py` were
untouched and still pass, which is the evidence that nothing the model sees
changed.

- Files: agent.py, commands.py, tests/test_agent.py, README.md, HANDOVER.md,
  BUGS.md, legacy/BUGS.md, CHANGELOG.md; TRACKER.md (gitignored)
- Status: shipped
- Commit: 6ffa248

## 2026-07-29 — The light says what to do where you are standing
v1.0 step 2, `B-0.9.1-03` and `D-0.9.1-01` — two findings against one table,
`ui.CONNECTION_STYLE`, closed in one decision because doing them apart means
opening the same table twice.

**The advice named a command the screen printing it would refuse.** The string
is rendered three times and only one of those is inside a session: the hub's
light and the `h` legend are both at the picker, which takes `n`/`p`/`h`/`q` and
a chat id and answers everything else with *"Type a chat ID, or one of…"*. So
the two screens most likely to be the first thing after launch were saying
`/connect embedding`. **The clause now carries its own context** — *"in a
chat"* — which is true in all three renderings at the cost of three redundant
words in the one place they aren't needed. Cas's call between the two shapes
`BUGS.md` left open; the alternative, splitting *what is wrong* from *what to
do*, would have put three advice literals on the far side of the `ui.py`
boundary that standing decision 6 will not let close.

**The report's own third option was declined on scope**: teaching the hub to
accept `/connect embedding` would make the advice true rather than qualified,
but a new hub key is a new feature and v1.0's claim is that what cfc already
says is true. It also only moves the wording problem, since a hub key is not the
same string as an in-chat command.

**A fourth rendering turned up during the fix.** `commands.connect_status`
(bare `/connect`) kept its own trailing line offering the command for every
state but `connected` — a fork of the table written as prose, and it had already
drifted the way a fork does: it offered `/connect embedding` for `hosted`, four
lines under a light saying *not cfc's to start*, against a `preflight.ensure`
that returns early without trying. Deleted, not corrected.

**The colour now says what cfc can do about it, not how bad it is.** Orange
where `/connect embedding` will try, red where it isn't cfc's to fix — so
`hosted` and `not running` swapped, which is exactly what *"either this is where
I find out that I'm colourblind, or two of these lights are the same"* was
pointing at. Severity was never the axis: every non-green state means memory is
off, equally, which is why the old pairing could be wrong for two releases with
nobody able to say what it should have been. Recoverability discriminates, and
it is the split `ensure()` already makes, so the colour and the behaviour cannot
drift apart. Three states share orange now — a class, not a collision. No colour
was invented; that would widen a producer/parser pair across a boundary that
cannot close.

**`README.md` was carrying a disproven claim** (`B-02`), found reading the
section that documents the light: *"Red is where it stops — LM Studio itself
can't be started from WSL."* That is the entry `HANDOVER.md` keeps in *rejected
designs* as its one deliberately-preserved mistake — three failures in one
afternoon written up as impossible, then driven successfully by Cas from a cold
machine on 2026-07-27. `preflight.py`'s comment was corrected that day; the
README and a `ui.py` comment were not. A correction of something factually
wrong, not a restyle.

**Both new properties are pinned against the mapping, never against literals.**
Every state naming a command must name a place to type it (matched on *"chat"*,
not the phrase — the finding is the missing context, not the words supplying
it); every state that offers the command shares one colour, the state that
doesn't shares none of it, and green is nobody else's. Verified by breaking all
three, including painting the whole light one colour. `tests/test_hub.py`'s
legend check follows the table for free. Golden's only diff is the known `D-01`
outbox hunk — read, not skipped.

- Files: ui.py, commands.py, tests/test_connection.py, README.md, HANDOVER.md,
  BUGS.md, BACKLOG.md, legacy/BUGS.md, legacy/BACKLOG.md, CHANGELOG.md;
  TRACKER.md (gitignored)
- Status: shipped
- Commit: 2b4513c

## 2026-07-29 — `CLAUDE.example.md` learns the split and the release order
v1.0 step 1, `D-06` and `D-07`, one edit to the one tracked file that could
carry either. **The release order had existed only in gitignored files**, so
nothing public said how a version ships — and the file that should have said it
still described the single-`CLAUDE.md` arrangement that stopped being true on
2026-07-28. Its *Versions and tags* section stopped at "write the note, then
tag": true, and written before the 2026-07-27 amendment that put the playtest
**inside** the order and made the tag last.

**Not a rewrite, and deliberately not a copy.** The six-session split is a
private arrangement; the example says *that a project can split its sessions and
why*, with the three things worth knowing before trying it — that a boundary can
exist on paper and nowhere else, that the two hardest boundaries were both a
session happening in the wrong file, and that the shared half is copies with
nothing checking them. The release order ships as five steps, the reasoning for
each, the tag-blocking test (*does this version's entry claim something the
finding falsifies*) and its corollary that the entry doesn't grow during the
pass.

**It names no model and no reasoning level**, on Cas's call. The workflow is
about to stop being one setting for every session, and an example written now
that encoded the current one would ship stale within a version — so the version
that changes it starts from a clean cut instead of a correction.

**The count of shared sections was wrong, and had been since the split.** The
paragraph announcing *change them in all six or in none* said **four** and
listed four; **five** are identical. The missing one is *Six kinds of session*
— the section that paragraph is inside, which is what its own *"this one
included"* had been pointing at all along. Found by checking the number rather
than repeating it, because this edit was about to publish it. Corrected in all
six by script, plus the pointer `CLAUDE.md`; a correction of something factually
wrong, not a restyling. It does not close `D-05`, it is the first evidence in
it: the drift landed in the *description* of the shared block rather than the
block, so every session since the split read correct instructions with a wrong
count in the middle of them. Nothing would have caught the other kind.

- Files: CLAUDE.example.md, CHANGELOG.md; CLAUDE.md and
  BRAINSTORM/CODER/DESIGNER/DRAFT/DEBUG/MANAGER CLAUDE.md, TRACKER.md (all
  gitignored)
- Status: shipped
- Commit: c29443c

## 2026-07-29 — A transient provider status kills an unattended run
Triage of *"every single routine is giving me 503 errors"*, written up rather
than fixed. Most of it turned out to be nano-gpt's:
`managed_mode_misconfigured` intermittently across every model and payload
shape for about three hours, reproduced from outside cfc with a bare
one-message request and recovered by 09:52 (`N-0.9.2-01`).

**The cfc-owned half is `D-0.9.2-01`, and it is an asymmetry.**
`_turn_with_retry` re-rolls an empty completion twice and a 503 zero times —
while its own docstring describes an empty completion as *"a provider hiccup,
not a size limit, and the same context usually answers on a re-roll"*, which is
a description of a 503 with the word for it left out. All six failures died at
call 0 of 30, before a single tool call: the cheapest possible point to have
tried again.

**The cost was the day, not the run.** `MAX_RETRIES_PER_DAY = 3` spends a slot
per failed *run*, so three 503s fifteen minutes apart exhausted
`short-term-memory`'s budget for all of 29-07 — and the provider was healthy by
08:47, when the same routine ran by hand and succeeded first time. The cap
stays (`N-0.9.2-02`): it bounds runs, and a transient status is not a run's
worth of failure. Deferred to v1.1 because three questions want deciding first
— where the ladder lives, which statuses it matches (**the code, never the
wording**, or it becomes a row in `HANDOVER.md`'s producer/parser table), and
what it costs when it is wrong.

Two more from the same logs, both nothing owed. A routine that logged
`10148s` against a 600s read timeout was a **machine suspend** at 03:30 mid-request,
resumed at 06:19 — httpx's read clock is the guest's and was paused with it, so
the timeout never ran, and standing decision 12 held because the date had been
computed and injected before the suspend (`N-0.9.2-03`). The misleading elapsed
figure is `W-0.9.2-01`.

- Files: BACKLOG.md; TRACKER.md (gitignored)
- Status: shipped
- Commit: 57d1b47

## 2026-07-28 — v0.9.2's body moves to the public roadmap
Release-order step 1, the half the model owns: the version's body moves out of
`ROADMAP_PRIVATE.md` and into `ROADMAP.md`, trimmed to what actually shipped
rather than what was planned, and is deleted from the private file — the split's
whole point is that a shipped version is described in exactly one place.

**The note is a hole, deliberately.** It gets written by Cas after the playtest,
from use, and the completion date lands with it. v0.9's note — *"ready to
playtest to test weird things"* — is what a note written before use can be.

Two things the public entry says that the plan did not, both because they were
measured during the build rather than predicted: five of six routine rows were
mis-coloured rather than one, and five of the twelve retired config commands are
aliases whose real command is a different word rather than four.

- Files: ROADMAP.md, ROADMAP_PRIVATE.md (gitignored), CHANGELOG.md
- Status: shipped
- Commit: 85fe0bf

## 2026-07-28 — The routine column stops having an opinion
`B-0.9.1-04`, and the last of v0.9.2's three claims. `hub._freshness` renders
`schedule.why_not_due()` instead of deciding for itself — standing decision 16,
applied one panel up the same screen from the connection light. Cas's call
between the entry's two options: **the colour means *is this routine due*, not
*how long ago it ran*.**

**The old column was an independent opinion about a question the scheduler
already answers, and it was therefore free to disagree with it. It did.**
Measured on the live routine folder before and after, and the report understated
the damage — five of six rows were saying something untrue, not one:

| routine | trigger | was | now |
|---|---|---|---|
| medium-term-memory | `weekly 0330` | orange | green — absorbed its week on schedule |
| note-reader, note-writer | `command` | orange | dim — can never be owed a run |
| long-term-memory, reflection | `command` | green | dim — right answer, no reason |
| short-term-memory | `0300` | green | green — the one that was actually right |

**What the same function buys that no threshold could:** if the Task Scheduler
tick stops firing, every scheduled routine goes orange and stays orange.
Hours-since-last-run is only ever a proxy for that, and a bad one.

**The failure mode inverts, which is the argument for the design.** The column
can now say green when `schedule.py` is wrong — but the function deciding the
colour *is* the function deciding whether the run happens, so a wrong green is a
routine that genuinely isn't running and a run log that stops growing. The light
and the behaviour fail together and cannot disagree. The old column's failure
was the silent one: two opinions, one of them decorative.

**Branch order is the whole of it**, and the first branch is the load-bearing
one: an unparseable timestamp is decided *before* anything consults
`why_not_due`, because that function refuses to read a log line it can't parse
and the refusal reads as *not due* — so a naive mapping paints a broken log
green. Decision 16's "green over a dead server", one row up.

Red left the column: "how badly overdue" is not a fact `why_not_due` knows.
`failed` is still red in **Status**. Dim now means *cannot be owed a run*, which
puts `trigger: command` and a *malformed* trigger in the same cell — noted
against `D-10`, the hub's broken-routine blind spot, rather than papered over.

**The legend line** (Cas's call): one dim line under the table, printed **only
when a row is orange** — `orange: due, waiting for the next scheduled tick`.
The connection light gets away with a bare colour because it prints dot *plus*
sentence; this column has no content half, and a legend that is always there is
furniture you stop reading.

**Tests.** `tests/test_hub.py`'s four threshold assertions were statements about
a rule that no longer exists and are gone; the two about the *label* survive
unchanged, because they were never about the rule. What replaces them is one
assertion per branch — and two that actually discriminate, since most of the
others pass under the old rule too (they cover cases it never reached): a weekly
routine that absorbed its week reads green where v0.4's thresholds said red, and
three days overdue is orange rather than red. Plus one for the panel: a routine
whose `why_not_due` explodes costs its own row and not the table, degrading to a
dim `?`. The seam patched is `schedule.last_run`, not `routines.last_run` —
`schedule` binds it at import, so patching the other one would have left every
due assertion silently reading the real run logs.

`tests/golden.py` drives `run_session`, not the picker: no re-record, and its
diff is unchanged.

`README.md` stated the old rule out loud and is rewritten. `ROADMAP.md`'s v0.4
entry stays exactly as written — it promised the thresholds and the thresholds
are what shipped; documentation changes apply going forward only.

- Files: hub.py, tests/test_hub.py, README.md, HANDOVER.md, BUGS.md,
  legacy/BUGS.md, CHANGELOG.md, TRACKER.md (gitignored)
- Status: shipped
- Commit: 4a642ef

## 2026-07-28 — `config.example.py` becomes a form again
`B-0.9.1-02` and `D-0.9.1-02` in one pass over both config files, as both
entries asked. The second of v0.9.2's three claims: the file a stranger opens
first names only commands that exist, in the form the app documents them.

**The sweep is not `:` → `/`, and the count of exceptions was one higher than
the entry had.** It listed four retired names whose canonical verb is a
different word (`:tokens`→`/status`, `:updatedb`→`/update db`, `:attach`→`/add`,
`:outbox`→`/list outbox`). There are five: `parse.py` has
`ALIASES["models"] = "list models"`, so `:models` becomes **`/list models`**.
Writing `/models` would have been the exact mistake the entry warns about —
teaching the alias instead of the command, which is how a retired word comes
back one generation later.

**Checked by running each command through the parser rather than by reading
it.** Every `/command` in both files is extracted and passed to `parse.parse`,
and the result must be a canonical `VERBS` entry with the verb unchanged. Zero
aliases, zero unparseable. That check is the only thing standing here — decision
13 sends an unrecognised verb to the model, so the failure mode is a confident
wrong answer and there is no test that can catch it from the outside.

`[:remember …]` keeps its colon, as `HANDOVER.md`'s scar requires: it is a
storage format, not prose, and a sweep nearly renamed it once already.

**The trim, and the rule that did the work.** *If a comment's first clause is a
date or a version, that is the tell* found three: the `TOOLS_MAX_*` block's
`Until v0.5 …` in both files (better written in `HANDOVER.md` under *Constants
with provenance*), and in `config.py` alone `(Until v0.6 these destinations were
refused outright …)` and `(set 2026-07-20)`. What stayed is the other half of
the rule — `WRITE_ROOTS`' *deliberately NOT derived*, the `TOOLS_AUTO_APPROVE`
note, `MOUSE_INPUT`'s trade — all *what a wrong value costs*.

**Two additions the version asked for**, both factual and both about a wrong
value that fails silently: `EMBED_BASE` now leads with mirrored networking and
says a stale NAT gateway IP does not resolve at all, and `EMBED_MODEL` records
that LM Studio's id is `text-embedding-baai-bge-m3-568m` rather than `bge-m3`.
The shipped file is 239 → 244 lines; shorter was never the claim.

**Two factual errors found in `config.py` while sweeping**, neither about `:` —
its tools comment said *"Read-only tools the model can request"* while
`write_file` has existed since v0.6 and that file's own `WRITE_ROOTS` is
populated, and its `TOOLS_MODELS` note described three ids for a list of eight.

`HANDOVER.md` decision 13 gains the consequence: retiring a verb means grepping
`config.example.py`, and writing the canonical verb there rather than the alias.

- Files: config.example.py, config.py (gitignored), HANDOVER.md, BUGS.md,
  BACKLOG.md, legacy/BUGS.md, legacy/BACKLOG.md, CHANGELOG.md,
  TRACKER.md (gitignored)
- Status: shipped
- Commit: cba36e7

## 2026-07-28 — The suite stops writing to the evidence file
`D-08`, and the first of v0.9.2's three claims. `~/.cfc/errors.log` is the whole
of `B-01`'s evidence, and one of that bug's three closing routes is *absence
across the 0.9 → 1.0 window* — so a test that writes convincing provider errors
into it is the watcher poisoning the thing it watches.

**Three files, not the one the entry predicted, and the reason is which surface
a test drives rather than which test misbehaves today.** `errorlog.log_error`
has exactly two call sites, `main.py`'s `run_session` handler and `runner.py`'s
`run_routine` handler, so the question is which harnesses reach one:

- `tests/test_model_revert.py` — the actual leak. Drives `run_session` with
  stubbed streams that raise `httpx.HTTPError`.
- `tests/test_routines.py` — drives `run_routine`. Nothing lands today, because
  its crash fixture raises `TimeoutError` and `runner` narrows the log to
  `httpx.HTTPError` on purpose. One fixture away from being untrue, and it is
  the *unattended* path.
- `tests/golden.py` — drives `run_session`, provokes no provider error today,
  and is the script most likely to grow a new command test. Guarded beside its
  existing refusals for the real database and the real vault.

`tests/test_agent.py` was checked as the entry asks and needs nothing: it drives
`agent.agent_turn` directly, and `agent.py` does not import `errorlog` at all.
Recorded here rather than left as an absence, because "we looked" is the half
that otherwise gets re-derived next time.

**The assertion is the durable half, not the redirect** — a redirect that gets
refactored away is silent. All three were verified by breaking them: with the
redirect line removed each one raises before anything is written, which is the
`HANDOVER.md` habit of proving a guard by disabling it. Golden's needed its own
rather than `assert_not_real`, which compares against the real *database* and
would have passed forever no matter where the log pointed — a decorative
assertion, which is the failure that file's own docstring is about.

**The evidence file was edited by hand, and this is the record of it.** 32
fabricated error entries (64 lines) were deleted, in eight batches from
`2026-07-27 20:35:16` to `21:07:10` — eight runs of `test_model_revert.py`
during v0.9.1's build, all four fixture models each time (`shanhaig`,
`good-model`, `broken-but-listed`, `custom-x`). `D-08` was written against the
last batch alone and said four; the count is the only thing about the entry that
was wrong. The 13 `launch` lines are real and stay, and the file now carries
zero errors — which is the state the absence-watch actually needs.

- Files: tests/test_model_revert.py, tests/test_routines.py, tests/golden.py,
  BACKLOG.md, legacy/BACKLOG.md, CHANGELOG.md, TRACKER.md (gitignored)
- Status: shipped
- Commit: 864e46b

## 2026-07-28 — Five findings get a place, and the scheduler stops being a claim
The v0.9.1 **post-tag** playtest, triaged. Nothing fixed here, per the debug
session's rule: the fix belongs to a build session working from the written
entry, and ten findings fixed in passing leave no record of why nine of them
were ordered the way they were. First pass to use the report template from
`fba699c`, and the template earned itself twice — once through the coverage
checklist and once through the wants/questions split.

**Two of the three reported findings are the same shape, and it is the shape
this project keeps producing: a signal that was correct when it was written.**

`B-0.9.1-03` — the connection light's advice, seen at the hub. The string lives
once in `ui.CONNECTION_STYLE`, which is right, and its own comment states the
rule it is written to: *say what to do, not what is wrong*. What it cannot know
is **where** it is being rendered. Two of its three call sites are the hub,
where `pick_session` takes `n`/`p`/`h`/`q` and a chat id and nothing else — so
the first screen after launch names a command that screen refuses. Nothing
drifted and the round-trip test is doing its job; the mapping is simply blind
to context. Same family as `B-0.9.1-01`, and the two go in one pass.

`B-0.9.1-04` — the hub's routine freshness. Green under 24h, orange to 48h, red
beyond is the **v0.4 spec of 2026-07-21**, written when a routine was daily or
on command. `trigger: weekly HHMM` landed three days later in `f58d1af` and
nothing revisited the column, so a weekly job that absorbed its week on schedule
shows red for five days in seven. It is wider than the report: of six routines
here, four are `command` and can never be overdue, and they redden too. The real
fault is that the column **forms an opinion** — `schedule.why_not_due()` already
answers "is this due", including weekly absorption and the never-run case, and
`_routine_rows` has the `Routine` in hand while passing `_freshness` a bare
timestamp. That is standing decision 16 (the connection light renders
`connection_state()` and never decides for itself) not applied to the row above
it, and the reason it survived is the direction: it cries wolf rather than
reassuring, and nobody double-checks a gloomy light. Cas's call to put it in
`BUGS.md` knowing that gates v1.0.

`D-0.9.1-03` — `/routine new` is half reject-as-you-type and half
all-or-nothing. Read roots re-prompt per line; `trigger` and `on_failure` reach
validation only at `save_routine`, six answers later, where the whole creation
is discarded. The half that actually bit is the exit: the flow returns to the
REPL without saying so, so the next line typed is a chat message — standing
decision 13's failure shape reached through an abandoned prompt rather than a
missing verb. Same hole in `on_failure`, in an id that already exists, and in
the model prompt, where a cancel is read as "use the default".

**Two more came from reading around the report, and neither was in it.**
`D-08`: `tests/test_model_revert.py` drives the real `run_session` and reaches
`errorlog.log_error` unpatched, so four fabricated provider errors are in the
live `~/.cfc/errors.log`, dated inside `B-01`'s absence-watch window. That file
is the whole of `B-01`'s evidence, its header says *nothing parses this file* on
purpose, and the reader is therefore a human with no way to tell the fixtures
from the thing being watched for. `tests/test_private.py` redirects `LOG_PATH`
to a temp file and asserts *"refusing to touch the real log"*; the fix is that
line, one file over. `D-09`: the `reflection` routine borrows `note writer.md`
as its prompt and lacks the inbox root that prompt reads — vault, no code owed.

**`HANDOVER.md`'s scheduled-run thread closes on evidence rather than on a
tick in a report.** Both runs are in `~/.cfc/schedule.log` under a `run-due
tick` header, which is what makes them unattended: `short-term-memory`
(`trigger: 0300`) at 05:45 on 28-07 — the machine off at 03:00, so
`why_not_due`'s "runs once, late, today" branch taken for real — and
`medium-term-memory` (`weekly 0330`) at 03:30 on 27-07. v0.5's scheduler claim
and v0.7's cadence are both driven now. Reading those logs is also where
`B-0.9.1-04` came from, and where the **`review` flag was seen firing in the
wild for the first time**: `reflection` logged `ok (review)` because the model's
own summary said a root it was told to read was outside its jail, which is
exactly the scar it was built for. What stays open is that a tick firing and a
routine doing the right thing are two claims, and only the first is settled.

Two entries close on Cas's own report. `D-03` (Obsidian's `{{ }}` colliding with
`runner.PLACEHOLDERS`) closed by the vault edit it always asked for, moved whole
to `legacy/BACKLOG.md`; `PLACEHOLDERS` is unchanged, which was the point.
`W-04`, the public-repo decision, is decided: **AGPL-3.0, and the repo goes
public with the v1.0 tag.**
- Files: BUGS.md, BACKLOG.md, legacy/BACKLOG.md, HANDOVER.md, CHANGELOG.md,
  TRACKER.md (gitignored)
- Status: shipped
- Commit: ee2a4dd

## 2026-07-28 — One place to describe a finding, one line everywhere else
A documentation-workflow change, from the v0.9.1 triage. Cas's problem, in his
words: *"a bug that has descriptions in three different documents means every
change has to be documented at least thrice."*

**Two new artefacts.** `TRACKER.md` (gitignored) is one line per open issue —
id, one line, the file its body lives in, the version it's assigned to, a state.
It is an **index**, and the rule that keeps it one is that a row may not explain
anything. And a **playtest report template** in the vault, which is where the
ids are allocated: a finding numbered `0.9.1-03` during the pass is
`B-0.9.1-03` in `BUGS.md`, in the tracker, and in this file when it ships.
Nothing gets re-described in order to be referred to.

The template also splits three things that were one list before: **findings**
(what broke), **wants** (works, would rather it were different — these never
reach `BUGS.md`), and **questions** (cost an answer, not a commit). Plus a
coverage checklist, so what a pass *didn't* touch is written down for once —
`HANDOVER.md`'s open threads exist because "one clean pass" read as "tested".

Three findings from the pass are recorded rather than fixed, per the debug
session's rule: `B-0.9.1-01` (denying a tool call renders as `error: user
denied` — the string is right for the model, which is its real reader, so the
fix is at the render), `B-0.9.1-02` (`config.example.py` still documents twelve
retired `:` commands, found by reading around the first one), and two backlog
entries on the connection light's colour pairing and the config files' length.

**The session split goes from four files to six**, both new ones taken out of
sessions that were already happening inside the wrong file. **Brainstorm** left
`DESIGNER CLAUDE.md`, which Cas had been using for it — a design file asks "what
is the shape", and asked too early that question turns a passing thought into a
specification with nobody having decided anything, which is the exact failure
the split exists to prevent, happening inside the split. **Manage** left
`DEBUG CLAUDE.md`, which had spent half of 2026-07-28 on documentation
architecture; the two halves kept wanting different things from the same file.

Reading the four before adding two turned up the reason the boundary hadn't been
working: **`DESIGNER` and `CODER` had never diverged at all.** Both were still
`LEGACY_CLAUDE.md` plus the debug paragraph, with no section describing their own
session — so brainstorm-vs-design wasn't split across two files, it was one file
with two names. Both now say what their session is for, and `DEBUG` states the
explaining half as a deliverable rather than leaving it as a tone, which is what
Cas said made him pick that file in the first place.

The five shared sections are now **named** rather than implied, in every file
and in the pointer, with the rule that they change in all six or in none.
Nothing checks that, which is why it's `D-05` in the tracker along with two
neighbours the same read turned up: the release order exists only in gitignored
files, so nothing public says how a version ships, and `CLAUDE.example.md` still
describes the single-file arrangement.

**Documentation changes apply going forward only**, now written into
`HANDOVER.md` as a rule rather than living inside one v1.0 note. Old entries are
records of what was true when they were written; restyling them to a convention
invented afterwards destroys the only property they have. This deliberately
covers the *reasoning* and not just the prose — "we used to do it the other way,
and here is what it cost" is the half most projects delete, and it is the half
worth reading.

`README.md`'s memory bullet was wrong in the reading rather than in the facts:
*"new chats index themselves as they happen"* is true, and chats are embedded
into an index `recall.py` deliberately doesn't read (`provider='wiki'`). It now
says both halves. `.gitignore` stopped carrying changelog-shaped prose about the
`CLAUDE.md` split, which is what this file is for.
- Files: README.md, BUGS.md, BACKLOG.md, HANDOVER.md, CHANGELOG.md, .gitignore,
  TRACKER.md (gitignored), ROADMAP_PRIVATE.md / ROADMAP_BEYOND.md (gitignored),
  CLAUDE.md and BRAINSTORM/CODER/DESIGNER/DRAFT/DEBUG/MANAGER CLAUDE.md (all
  gitignored)
- Status: shipped
- Commit: fba699c

## 2026-07-27 — The playtest moves inside the release order
A process change, not a code change, and it is here because it changes what a
tag means. **The playtest now happens between the push and the tag** rather than
after it.

It had never been decided — the release order was three steps (push → note →
tag) and said nothing about when to test, so testing landed after the tag by
default. The cost is visible in the history: three of the four releases before
v0.9.1 were patch releases named for what a testing pass caught, which had
quietly made PATCH the mechanism for *the version was never tested* instead of
*found after the version was genuinely done*. It also meant every version note
was written from the plan rather than from use — v0.9's note says "ready to
playtest to test weird things", because at the time that was all it could say.

**What decides when a version is finished**, which is the half Cas was worried
about: a finding blocks the tag if it **falsifies a claim in that version's
`ROADMAP.md` entry**. Not "did this version cause it" — that is arguable
forever and gets argued under pressure to ship. The entry is finite and written
before the testing starts, so the finish line can't move while you are leaning
on it. Everything else is assigned to `BUGS.md`, `BACKLOG.md` or a roadmap
version and does not block.

Nothing about the git layout changed, and that is worth recording: the order was
the problem, not the tooling. The DEV-area question Cas raised alongside it
stays open and undesigned in `ROADMAP_BEYOND.md`.

Also adds a fourth session type, `DEBUG CLAUDE.md` — where Cas arrives with
testing notes, findings get diagnosed and assigned, and the build brief gets
drafted. Deliberately the one session that explains at length: it is the one not
racing a build, so it is where the codebase actually gets learned. The other
three stay lean. All four now carry the same five-step release order, because a
stale copy of it in one file is the producer/parser hazard `HANDOVER.md` keeps a
table of.
- Files: .gitignore, CLAUDE.md, CODER/DESIGNER/DRAFT/DEBUG CLAUDE.md (all
  gitignored), ROADMAP_BEYOND.md (gitignored)
- Status: shipped
- Commit: cbe6d68

## 2026-07-27 — v0.9.1 ships: the roadmap body moves over
Per the release order: the v0.9.1 body moves from `ROADMAP_PRIVATE.md` to
`ROADMAP.md` with its completion date and is deleted from the private file. The
note-shaped hole is left for Cas, and the tag comes after the note is in — a tag
whose own version's note isn't in it would be that way permanently, because a
pushed tag never moves.

Also corrected three pointers in v1.0's private section that v0.9/v0.9.1 had
made stale, since a forward plan citing archived entries is worse than one that
is merely incomplete: the desktop-shortcut splash (closed as *audible*), the
interactive empty-completion retry (shipped in `b423d30`), and `longcat-2.0` —
which came out of `MODELS` back in v0.4 and is not in `config.py` today, so what
was actually re-opened was the class, and both of Cas's calls on that shipped.

And recorded an open question in `ROADMAP_BEYOND.md`, deliberately undesigned:
**how versions actually get shipped, and where testing happens.** Raised by Cas
at this tag. Today "shipped" and "on Cas's machine" are the same event — the
model commits and pushes to `main`, and testing happens after, on the working
copy the next version is built in. That is *why* v0.8.1, v0.8.2 and v0.9.1
exist: each is a testing pass finding what the release should have caught. It
gets a design session rather than a plan appended by whoever reads it next.
- Files: ROADMAP.md
- Status: shipped
- Commit: ea6ab5a

## 2026-07-27 — Three closed entries reach the archive, four days late
Not work — the archive rule is four days old and had already been missed once,
which is about the rate you'd expect from a rule that only fires when something
*else* finishes. Three entries were closed and still sitting in the live files.

- **`BUGS.md`, the plain-console splash banding.** Closes as **audible rather
  than fixed**, and the distinction is the entry: cfc's share shipped in v0.9
  (`preflight.terminal_report()`), and it stayed open on purpose until the
  warning had been *seen*, because closing a defect on unverified work is the
  mistake the file exists to prevent. Cas launched from the bare `wsl.exe`
  shortcut and got the line verbatim. The remaining repair is a `~/.bashrc`
  gate — a personal dotfile, never this repo's to encode.
- **`BACKLOG.md`, the interactive empty-completion retry.** Shipped in
  `b423d30` as `commands.empty_completion_decision`, shared by both turn paths,
  which is what the entry asked for in its last line.
- **`BACKLOG.md`, nothing validates that a model in `MODELS` can be chatted
  with.** Both of Cas's calls shipped in the same commit. What survives —
  `ROUTINE_MODELS[0]` having nothing to revert *to* — was **let go rather than
  carried forward**: it is audible (the run logs `failed`, the hub's freshness
  column shows it), and this file is for what is owed, not for what works and
  could be worded better.

That leaves `BUGS.md` holding **one** entry between here and the v1.0 gate, and
it is the one that can only close on absence — which is why the error log above
was worth a patch release rather than a wait.
- Files: BUGS.md, BACKLOG.md, legacy/BUGS.md, legacy/BACKLOG.md
- Status: shipped
- Commit: 95de5e6

## 2026-07-27 — Five papercuts, four of them a screen contradicting itself
All from Cas's testing notes, all small, and four share a shape worth naming:
the app printing two things that cannot both be the useful one.

**`/add <path>` said it found nothing, then attached the file.** The pool search
runs before the path check *by design* — a pool item named like a file has to
win — so it fails and says so, and then `looks_like_path` attaches it on the
next line. The ordering is the deliberate part and does not move; the miss
message is now held back when the query looks like a path. Suppressed whenever
it looks like a path rather than only when the attach then works, because
`do_attach` reports its own refusals and every one is more specific than the
pool miss: outside the jail, no such file, a directory, wrong extension, not
UTF-8, too big. There is no silent branch for it to have been covering.

**Traits had no row in the session header.** The other two pools had one each,
and traits is the pool you can carry several of — the one whose state is hardest
to hold in your head. Deliberately thinner than `/status`'s row, which loads
each file to mark a missing one: this header prints on every session open, and
"which of these has lost its file" is what `/status` is for.

**The line count was printed twice, off by one.** `tools.read_file` returns
`<path> (115 lines)` and `agent._render_result` printed that as the head and
then counted the result, header included, at 116. It now counts the lines
*below* the head, which makes the two agree without either module knowing about
the other — the alternative, the renderer noticing the head already carries a
count, would be a producer here and a parser there. It also stays honest when
`_truncate` has cut the body, where the numbers *should* differ.

**`/wiki diff` never named its scope.** `where = _scope_label(scope)` was
computed and then used only in the *nothing changed* branch, so a diff with
content named nothing. Driven on the real vault after the fix: `wiki db: nothing
changed`, `journal: 1 change(s)`, `the vault: 12 change(s)` — three different
true answers one command apart, which is how a review step ends up approving one
scope and committing another.

**And `/wiki commit` said the vault has no remote, which it now does.** The
vault went to a private GitHub on 2026-07-27, closing the ext4-only exposure
that v1.0 called the most urgent chore in the project. The line's failure ran
opposite to this project's usual one: an unpushed commit really is local only,
so its conclusion survived while its reason went false — and the false reason
was the half saying nothing could be done, at the moment the thing to do had
become available. Now `_LOCAL_ONLY`, one constant across both commit paths:
`committed locally — cfc does not push`. It says what cfc did rather than what
the repo has, so it cannot go stale. `wikigit.py`'s header and `README.md`'s
vault-git section were rewritten to match — cfc still never pushes, but that is
now a choice with its own reasons rather than a description of the environment.
- Files: main.py, commands.py, agent.py, wikigit.py, README.md, HANDOVER.md,
  tests/golden_baseline.txt
- Status: shipped
- Commit: 9f063fc

## 2026-07-27 — `/remove excerpts` drops every block, so the hint stops lying
Reported by Cas against the hint `/remember` prints itself, which is the worst
place for a command to be wrong. The code path was intact and the report pointed
somewhere else, so this was settled by reading rather than reproducing:
`injected.append` happens in exactly one place, once per `do_remember`, and each
call builds exactly one envelope with one closing boundary line. **Two closing
lines is therefore necessarily two `/remember` calls**, which is what the
testing note described — so the single-block case could not have been broken,
and `do_forget` popping one of two was the whole of it.

That made it a legibility question rather than a bug in the pop, and Cas's call
was to make the command match its hint rather than shrink the hint: `(ephemeral
— /remove excerpts to drop)` reads as *all of them*, and nobody injects two
blocks meaning to keep one. `do_forget` now clears the list and removes every
block from `history` by identity, and says how many it dropped.

Worth keeping in view: the failure this fixes was **silent and in the direction
that costs money** — dropped excerpts leave the screen, surviving ones are
invisible until the model quotes something you thought you had removed. There is
no signal that it happened. `/status`'s live count stays and is now the only
place the number lives.

Also re-recorded `tests/golden_baseline.txt`: the help line changed, and the
diff carried an unrelated hunk (the outbox's two journal proposals had been
filed since the last record). That second hunk is the `config.py` baseline scar
in a new place — a baseline pinning the environment rather than the source — and
is written up in `BACKLOG.md` rather than fixed here.
- Files: commands.py, tests/golden_baseline.txt, BACKLOG.md
- Status: shipped
- Commit: c7faee7

## 2026-07-27 — Somewhere for a provider error to land
`BUGS.md`'s surviving entry closes either when the next 400 settles it or on
absence across the 0.9 → 1.0 window, and both need the error line to still exist
when someone looks. Until now the only place it existed was the scrollback — on
a tool turn, the kind that fills a screen. `errorlog.py` appends the whole line
to `~/.cfc/errors.log` with the session, the model, and how many turns were
cancelled in that session, which `BUGS.md` asks for and nothing tracked.

Three things this is really made of, none of them the file write:

**The error is recorded before anything decides how to render it.** A defect
found while planning v0.9.1: `revert_bad_model()` prints `provider rejected 'X'
— switched back to Y` *instead of* the provider's words, so the one line we want
was discarded exactly when a model switch preceded the failure — an ordinary
session, not an exotic one. Both turn paths now call one nested
`handle_turn_error`, which logs and then lets the console decide. One helper and
not two `log_error(e)` calls, because standing decision 7 exists precisely
because these two paths drifted once already.

**A launch writes a line.** Otherwise "the log is empty" and "cfc has never
managed to write to the log" are the same artefact — this project's signature
failure shape aimed at the mechanism built to catch it. With the launch line, an
empty file means *never written*, which is audibly different from *no errors*.

**A private chat writes nothing, and the refusal is at the write.**
`api._error_detail` carries up to 800 characters of the provider's body and
providers echo request fragments back inside a 400, so this is a **fourth** path
out of a private session — invariant 10 named three. Gated inside `log_error`
rather than at the call sites: a caller that forgets is the failure the gate
exists to prevent. `tests/test_private.py` pins it with a marker planted in the
error text, so "no line was written" and "the words did not leak" are separate
assertions; verified by disabling the gate and watching both fail.

Routines log too, narrowed to `httpx.HTTPError`. The bug is a *tool-turn* bug
and routines are the heaviest tool users in the system, so excluding them puts
the hole exactly where the tool turns are. `append_log` is unchanged and is not
a duplicate of this — it is a per-routine status that `on_failure`, `last_run`
and the hub read; errors.log is one human's evidence trail across time.

Nothing parses errors.log, deliberately: the recurring hazard is a producer here
and a parser elsewhere, and the way not to add a seventh row to that table is
not to create the pair.
- Files: errorlog.py (new), main.py, runner.py, tests/test_private.py
- Status: shipped
- Commit: 7fa831d

## 2026-07-27 — v0.9 ships: cold start settled, and the roadmap body moves over
Cas ran the case that had never once been exercised — the desktop shortcut on a
genuinely cold machine — and **red worked**: the branch ran, `lms server start`
brought LM Studio up, and the probe came back green.

So the `BUGS.md` entry opened this morning closes, and it closes as a mistake of
mine rather than a defect of cfc's. I measured `lms server start` dying after
62s from an interactive shell, plus two GUI launch methods doing nothing, and
wrote "LM Studio cannot be started from WSL" into `HANDOVER.md` under *Rejected
designs* — the section whose entire function is to stop the next person trying.
Three failures in one afternoon, about something that had been observed working.
The early return that came with it removed a capability Cas relied on, and he
noticed within the hour. Why the direct invocation timed out is still
unexplained; it blocks nothing, because the path a user takes is the one that
works.

The v0.9 body moves from `ROADMAP_PRIVATE.md` to `ROADMAP.md` with its
completion date, per the release order, and the private entry is deleted. It is
rewritten rather than copied: the planned version was five items called *The
connection*, and what shipped was ten under *Say which state you're in*. The
entry says what actually happened, including the four things the plan had wrong
and the two live defects that were on no list.

`ROADMAP.md`'s note is Cas's and is left as a placeholder.
- Files: preflight.py, BUGS.md, legacy/BUGS.md, HANDOVER.md, ROADMAP.md,
  ROADMAP_PRIVATE.md
- Status: shipped
- Commit: fd44d95

## 2026-07-27 — Hub help, generated rather than written
`h` at the hub prints what can be typed there. The point of the entry is that
none of it is written down twice.

The hub's keys were a hard-coded `if` chain, so a help screen beside it would
have been a fourth list with nothing checking it — and the day it disagrees it
teaches the wrong command confidently. `hub.HUB_KEYS` is now the dispatch *and*
the help's source, and `tests/test_hub.py` fails if a key is dispatched that the
help does not describe. Verified by breaking it: smuggling a working key into
the dispatch is caught by name.

The light's legend is generated from `ui.CONNECTION_STYLE` — the same mapping
the light itself renders — so a connection state cannot exist without appearing
in the help. The one hand-written line points at `/help`, which is a fact about
where the session's commands are documented rather than a copy of twenty-two
verbs, and copying them here would be the fourth list all over again.

The error line for an unrecognised key is built from the table too, so it can no
longer list a different set of keys from the ones that work — which it already
did: it offered `n`, `p` and `q` and never mentioned that `new`, `private` and
`quit` also worked.
- Files: hub.py, tests/test_hub.py, HANDOVER.md, README.md
- Status: shipped
- Commit: eb19924

## 2026-07-27 — Spend the last provider-400 suspect, at the wire boundary
`agent.py` normalises a missing `content` to `""` on the assistant message
carrying `tool_calls`, because `history`, `save_message` and the renderer all
expect the key. Some OpenAI-compatible providers want it **absent** and reject
the replay on the next request — which fits the reported symptom exactly: tool
turns only, size-independent, and every *subsequent* message failing rather than
the one that misbehaved.

**Where the fix lives is the whole of it.** The normalised value has to stay in
`history`, so `history` and the request are no longer the same object on this
path. The transform is therefore `api.wire_messages`, applied inside `call_api`
and `stream_response` — at the wire boundary, not at either call site. Both
paths replay history, and the streaming one is the easy one to forget precisely
*because* it has no tools: a session that made tool calls and then switched to a
non-tools model replays those same messages through it. A transform a caller has
to remember is one a caller will not.

It never mutates its input. Standing decision 2 lives in `history` — every tool
call keeping exactly one result — and a wire-format fix that edited those dicts
in place would reach back into the record of the conversation. It drops the key
rather than sending `null`, because absent is what the schema means by "no
content" and `null` is a third state some providers reject.

`tests/test_wire.py` pins the transform and, more importantly, pins that the
input is untouched. **There is no test that the fix works, and there cannot be:
the bug has no reproduction.** What this buys is that the list of things left to
try is now empty, which is a different and more honest position than a fix.

The diagnostics `BUGS.md` specifies were **confirmed rather than rebuilt**, as
that entry asked: `_request_shape` renders its rider, `_error_detail` truncates
at 800 characters as documented, and `_is_empty_completion_400` still recognises
the empty-response 400 while letting a context-overflow 400 through to the raise
path — the fail-safe direction that makes matching on a provider's wording
tolerable at all.
- Files: api.py, tests/test_wire.py, BUGS.md, HANDOVER.md
- Status: shipped
- Commit: 334025c

## 2026-07-27 — The last three timestamp sites read local time
`db.py` is the only module that stores UTC, and three sites still read the
stored string directly: `export.py`'s filename date, `export.py`'s per-message
timestamp, and the recall excerpt's date label in `commands.py` and `recall.py`.

They survived v0.8.1's fix for a specific reason worth keeping: `format_ts`
returns `YYYY-MM-DD HH:MM`, so a site that wants only a date **cannot call it**
— which is why they went on slicing `created_at[:10]`. The fix is therefore a
second helper and not a substitution: `ui.format_date`, beside `format_ts`, one
implementation at the bottom of the dependency graph, taking its input rather
than importing config. Same shape as `ui.vault_relative` in v0.8.2.

`[:10]` was never a cheap version of this — it reads the **stored** date, so a
session created after 22:00 local was filed and labelled under tomorrow. Silent,
off by one, and only in the evenings, which reads as a misremembered date rather
than a bug. Confirmed live rather than reasoned about: session #24 on the real
db stores `2026-07-19` and is locally `2026-07-20`.

Cas's call (2026-07-27) was to localise all three, `export.py`'s full timestamp
included. An export is a data file and an absolute timestamp is defensible in
one, but it was the only thing in the vault in a different time base, and that
inconsistency is itself the trap.

Pinned in `tests/test_hub.py` **against an offset computed from the host's**,
never a literal — a test written against `+00:00` passes on a UTC machine
whether or not the conversion exists, which is exactly how the two-hour hub bug
survived.
- Files: ui.py, export.py, commands.py, recall.py, tests/test_hub.py,
  HANDOVER.md, BACKLOG.md
- Status: shipped
- Commit: f0c3c17

## 2026-07-27 — Undo the red-path early return, and demote a claim I overstated
Cas tested the connection light end to end (green with LM Studio up, red at
launch and at the hub with it quit, `/connect embedding` working) and reported
one loss: **the desktop shortcut used to start LM Studio, and no longer does.**

That is a regression this version introduced. The earlier commit today returned
as soon as it saw "LM Studio not running", on the strength of measuring three
ways to start it from WSL and watching all three fail. The early return removed
a path the old code reached **by accident**: when `lms` cannot contact a daemon,
`server_state` returns `(None, None)` rather than `(False, …)`, so the old
`ensure()` skipped the server-start branch entirely and fell through to
`lms load` — a different command, a 180s budget rather than 90s, and the one
thing never tried cold. `lms server start` may never have been what worked.

So red attempts the sequence again, says it is trying and that it may not work,
and ends with the instruction to start LM Studio by hand. Nothing is worse than
before v0.9.

**The write-up was the real error.** "LM Studio cannot be started from WSL" went
into `HANDOVER.md` under *Rejected designs*, which is the section whose whole
function is to stop the next person trying. Three failures in one afternoon do
not establish impossibility about something that has been observed working. It
is now an open question in `BUGS.md` with the measurements, the untested
candidate, and the one command that would settle it.
- Files: preflight.py, ui.py, tests/test_connection.py, HANDOVER.md, BUGS.md
- Status: shipped
- Commit: 30ca264

## 2026-07-27 — LEGACY_PREFIX and RETIRED come out, and the old words become aliases
The `:` prefix was accepted for one version with a once-per-session nudge, and
it was self-removing by design: deleting the constant is all it took. A `:` line
is ordinary text again and goes to the model, exactly as before v0.8.

**The deletion and the promotion had to be one commit, and this is the whole
point of the entry.** `RETIRED` was what caught `/models`, `/prompts`, `/tags`
and a dozen more. Deleting it would have turned each of them back into prose —
and an unrecognised verb is not an error message, it **falls through to the
model**, costing an API call and returning a confused answer. That is precisely
what `/routines` did until v0.8.2 fixed it with one line in `ALIASES`. So the
retired words moved into `ALIASES` in the same change that removed the dict, and
they are now real synonyms rather than corrections: `/prompts` lists prompts
instead of printing the name of the command that lists prompts.

That needed one grammar change: **an `ALIASES` value may be a phrase.**
`models` has to become `list models`, which a verb-for-verb alias cannot
express — which is why these lived in a deprecation table doing a synonym's job
in the first place. `parse` expands the phrase once and appends the user's own
arguments after it, so `/grep foo` is `/search foo` and nothing downstream knows
`grep` was ever a word.

**`detach` is the one word let go, and the bar it failed is worth recording.**
Its replacement is `/remove #<n>` — the `#` is the attachment namespace — so the
argument changes shape and no verb-level alias can carry `1` across to `#1`.
Widening `/remove` to accept a bare number would have changed a deliberate
namespace to rescue a retired word. It had its version of correction.

Three test files were still driving the REPL with `:` commands, which now go to
the model — so the golden harness was attempting real API calls and hanging.
That is the same class the change is about, caught in the tests rather than in
use. The baseline moves 293 → 354 lines: the retired-verb corrections are
replaced by the commands actually running.
- Files: parse.py, main.py, commands.py, README.md, HANDOVER.md,
  tests/test_parse.py, tests/test_empty.py, tests/test_model_revert.py,
  tests/test_private.py, tests/golden.py, tests/golden_baseline.txt
- Status: shipped
- Commit: bfa1f40

## 2026-07-27 — Recall says which kind of nothing it found
Three outcomes used to produce one silence, and only one of them meant "memory
has no answer". The embedder never answering, nothing being indexed, and a real
miss all printed the same line — so a broken lookup was indistinguishable from a
truthful one, which is this project's signature failure sitting in the memory
layer.

**Separated at the exception, which is the only place they are cleanly
separable.** `embed.py` now records which kind of failure it saw *while it is
catching it* and raises `EmbedUnavailable` (a subclass of the new `EmbedError`,
which is still a `RuntimeError` — every existing `except` keeps working). The
caller branches on the class. Re-deriving the state further up by matching
words would be the recurring hazard rebuilt, and
`tests/test_memory_states.py` pins exactly that: an `EmbedError` whose *message*
is a perfect copy of the unreachable one must not be reported as unreachable.

**A fourth state turned up while reading: an empty index is not a failed
search.** `search.why_empty` separates "there was nothing to search" from "the
corpus was searched and missed", scoped by provider — because a db full of chat
chunks answers "yes, I have content" to a wiki-scoped search that had nothing to
look at. It fails open to `EMPTY_INDEX`, which sends you to `/update db`
(harmless if wrong) rather than asserting a search happened over content that
isn't there.

`recall()` now returns `answer=None` on zero hits instead of the sentence "No
relevant excerpts found in memory." — which the caller had been rendering in the
answer panel exactly as if a model had written it. The unreachable case points
at `/connect embedding`, so this block and the connection block compose.

**The routine half of this was scoped out, and the reason is worth keeping:
no routine can reach recall.** The four tools are `list_dir`, `read_file`,
`grep` and `write_file`, and `commands.py` is the only module that imports
`search` or `recall`. The draft assumed otherwise. So the distinction is built
where it originates; a future recall tool inherits a typed exception rather than
needing one retrofitted.

**Also fixed, and pre-existing: four `console.print` calls printed their own
markup tags.** `ui.console` is `Console(markup=False)`, so `[dim]…[/dim]`
renders the brackets. One was the embedder retry note **shipped in v0.8.2** —
the release named for that note — visible on every slow embedder since. It
survived a testing pass because a wrong-looking line still tells you the true
thing.
- Files: embed.py, search.py, recall.py, commands.py,
  tests/test_memory_states.py, HANDOVER.md, README.md
- Status: shipped
- Commit: 4d1a9ab

## 2026-07-27 — The connection says which state it is in
v0.9's first two blocks, and they are one job: cfc now reports the state of its
embedder instead of degrading quietly into "memory has nothing on that".

**One state function, three renderings.** `preflight.connection_state()` returns
one of five states and every consumer renders it — the launch report, the hub's
new traffic light, and the new `/connect embedding`. The failure being designed
against is a **green light over a dead server**, which is the one output nobody
double-checks, so the rule is that no consumer forms its own opinion. Recorded
as standing decision 16.

**The measurement is what made a live light possible.** A real `/embeddings`
POST answers in 0.157s, so `preflight.probe` was split into `PROBE_CONNECT=0.5`
/ `PROBE_READ=8.0` — the same connect-vs-read lesson `embed.py` learned in
v0.8.2, one layer up. That drops a dead local port from 8s to 0.5s, which is
what makes asking on every hub render affordable: **there is no cache anywhere
in this feature**, so there is no staleness to reason about and no age to
display.

Red and orange are separated by an actual process check (`tasklist.exe` on WSL,
`pgrep` otherwise, ~0.15s), and there is a fifth state — `DOWN` — for when that
check could not be read. Claiming "LM Studio is running, its server isn't"
without having looked would be the confident wrong answer this whole feature
exists to remove. `HOSTED` never shows a red light telling you to start an
application that has nothing to do with your endpoint.

`/connect embedding` calls `preflight.ensure()` rather than reimplementing it;
`ensure` grew a `say(level, msg)` callback so the same code prints raw ANSI
under `launch.sh` and rich inside a session — the same move as `embed.py`'s
`on_retry`, because preflight has no console and must not grow one. It was
written with no separate "launch the GUI" path on the assumption that `lms
server start` brings the app up cold — see the correction below, which is what
running the acceptance test was for.

**Preflight also says when the splash will band** — `COLORTERM`, `TERM` and
rich's `color_system`, with a warning when they don't add up. Fails in the safe
direction: a false positive is loud and self-correcting, a false negative is
today's behaviour. It stays quiet when there is no terminal at all, so it can't
cry wolf in a log. `launch.sh` still must not force `COLORTERM=truecolor` —
conhost cannot render 24-bit escapes and claiming it can trades banding for
garbage.

`connect` came out of `parse.RESERVED`, where it had been held since v0.8 for
exactly this. `ui.CONNECTION_STYLE` is the single mapping from state to colour,
and because `ui.py` imports no cfc module it is a producer/parser pair across a
boundary that cannot be closed — **the sixth row of the recurring-hazard
table**, pinned by round-trip in the new `tests/test_connection.py` rather than
against literals. An unmapped state degrades to a dim `?`; taking the hub down
over a decorative light is the worse failure.

Two defects were found by driving it rather than reading it, which is the habit
that keeps earning: `ui.console` is `Console(markup=False)`, so `[green]●[/green]`
printed its own tags verbatim — every styled line here is a `Text` — and bare
`/connect` offered to fix a connection that was already green.

**The acceptance test was then run, and it failed — which is the whole reason
it existed.** With LM Studio genuinely quit, `lms server start` waits 62 seconds
and dies with "Timed out waiting for LM Studio daemon to start": it wakes a
daemon that only exists once the GUI has run, and there is no headless flag.
`cmd.exe /c start` returns 0 and launches nothing; a direct exec of the .exe
does nothing at all. **So `LMS_TIMEOUT`'s comment — "a cold `server start` has
to bring up the app" — was an assumption nobody had tested, and it was wrong**,
including in the first draft of this entry.

Red therefore prints an instruction and returns **in 0.8s instead of failing for
62**, and the light says "start it on Windows" rather than naming a command that
cannot work. Recorded under Rejected designs so the next session doesn't spend
an evening on the same three attempts.

That run also exposed a defect in the module whose entire job is making silent
failures loud: **`_lms` returned only stdout**, and `lms` prints its reasons to
stderr — so every failure reported `could not start the server: ` with nothing
after it while the real message sat in a pipe nobody read. Success still returns
stdout (callers parse JSON from it); failure now returns stderr.

**Then the orange path was driven too, and all three states are now proven.**
With LM Studio running and its server stopped, `lms server start` fired for the
first time since it was written and took the connection to green in 1.4s.

`lms load` turned out to be **near-unreachable**, which is a better answer than
the test was looking for: LM Studio JIT-loads a model when a request names it,
so with the model explicitly unloaded the probe still succeeded — it just took
**1.71s instead of 0.15s**, because the POST did the loading. The branch is kept
(JIT is a setting, not a guarantee), and what that measurement really pins is
`PROBE_READ`: a cold load happens *inside* the read budget, so 8.0s is not slack
— it is what stops the first probe after a restart reporting a confident red
light over a working embedder.

That closes the `preflight.py` open thread that had been in `HANDOVER.md` since
v0.7. **Still open:** the splash warning has not been seen firing from the bare
`wsl.exe` shortcut, so its `BUGS.md` entry stays open — closing a defect on
unverified work is the mistake that file exists to prevent.
- Files: preflight.py, ui.py, hub.py, parse.py, main.py, commands.py,
  tests/test_connection.py, tests/test_parse.py, tests/test_preflight.py,
  tests/golden_baseline.txt, HANDOVER.md, README.md, BUGS.md
- Status: shipped
- Commit: 6fe526b

## 2026-07-27 — Split the closed entries out of BUGS.md and BACKLOG.md
`BUGS.md` was 283 lines holding three live entries and `BACKLOG.md` was 897
holding five; the rest was struck-through history, each entry carrying its full
original report. A list nobody can read is a list nobody checks, and it was
blocking the v1.0 documentation pass. Same move the roadmap already made: the
working file holds what's live, the history lives elsewhere.

Both files were moved into `legacy/` **unedited** and new ones written with the
open entries only. Archive rather than delete, because `CHANGELOG.md` carries
every fix and its reasoning but **not the original report** — and the symptom as
first written is frequently the valuable half, sometimes for its wrong premise
(`MAX_DISTANCE`). Tracked in git rather than gitignored, for the reason
`HANDOVER.md` already gives against `inbox/` at the repo root: a gitignored file
in the repo is invisible to clones, outside every backup, and destroyed by a
fresh checkout.

This is a **rule change, not a tidy**, so the rule moved with it — a closed
entry now leaves no stub behind, and that is written into both files' headers
and `HANDOVER.md` in this commit rather than left as folklore.

Two entries changed state while being carried across, both recorded in the new
files: *retire the `:`-command `startswith` chain* **closes on inspection** —
v0.8's `parse.py` already did it, `main.py` has zero `startswith(":` and asserts
`set(HANDLERS) == set(VERBS)` — and *model selection is too generous* was cut
down to the `[esc]` remnant that is actually still open. Decisions Cas made on
the v0.9 draft were written into the entries they belong to rather than kept in
the draft: localise all three UTC timestamp sites, arm the model auto-revert on
every switch, check `TOOLS_MODELS`/`MODEL_LIMITS` against `known_models()` at
startup, and let the provider 400 close on absence if it doesn't recur.
`HANDOVER-legacy.md` moved to `legacy/HANDOVER.md` in the same pass — same kind
of document, and it was the last frozen file at the repo root. `legacy/README.md`
says what the folder is, since GitHub renders it in the listing.

Also recorded, from Cas's v0.8.2 play-test the same day: everything previously
reported fixed, nothing new, no provider 400. That starts the absence-watch on
the 400 rather than leaving it to begin at the tag. It explicitly does **not**
cover the model auto-revert's open case — the pass exercised an id *not* in
`MODELS`, which is the path that already worked.
- Files: BUGS.md, BACKLOG.md, HANDOVER.md, README.md, legacy/BUGS.md,
  legacy/BACKLOG.md, legacy/HANDOVER.md (was HANDOVER-legacy.md),
  legacy/README.md
- Status: shipped
- Commit: a1901dc

## 2026-07-26 — v0.8.2: the embedder fails fast, and four papercuts from the testing pass
Everything here came out of Cas's 0.8.1 testing pass. Two were defects and the
rest were polish; nothing new is claimed, which is the point of a patch.
- Files: embed.py, search.py, recall.py, commands.py, parse.py, ui.py,
  config.example.py, tests/test_embed.py, tests/test_model.py,
  tests/test_hub.py, tests/test_parse.py, tests/golden.py
- Status: shipped
- Commit: a26877b

**`/recall` with the embedding server off took four minutes to say so.**
`embed._post` passed a single `timeout=60` to httpx — which sets *connect*,
*read*, *write* and *pool* to the same value. Those measure different things:
"is anything there" against "is it finished yet". One number has to serve the
slower of the two, so every one of four attempts sat out the full read budget
just to discover nothing was listening. Split now: **connect 5s, read 60s**, so
a big import keeps the patience it needs and a dead server is found in seconds.
Measured end to end against a closed port: **11.1s, down from ~240s.** The live
endpoint answers in 0.18s, so the connect budget is generous by 27×.

**And a refused connection is no longer retried like a busy one.** A 429 or a
503 is a transient and waiting is the right answer; nothing listening on the
port is a *state*, and asking four times gets the same answer four times. Two
budgets: `_RETRIES = 4` for a server that is there, `_DOWN_RETRIES = 2` for one
that isn't — two rather than one because a call can catch a restart. The old
loop also slept on its way out, backing off after the final attempt before
raising; it doesn't now.

**The spinner says something.** A spinner alone cannot distinguish "thinking"
from "nothing is listening", which is what made an honest wait read as a hang.
`embed_texts` takes an optional `on_retry` callback, threaded through `search`
and `recall`, and the interactive commands pass one. It is a callback rather
than a print because **embed.py has no console and must not grow one** —
routines and imports run headless. Same shape as `agent_turn`'s `touched`
collector, for the same reason: the signature stays honest about who cares.

**Ctrl-C during a recall no longer takes the app with it.** `do_recall` caught
`Exception`; `KeyboardInterrupt` derives from `BaseException`, so it escaped the
`Live` context and the session loop. All three spinner sites now catch it and
return to the prompt — `/recall`, `/remember` and `/update db`. The last one
says the index can be finished by running it again, which is true and worth
saying: `backfill.embed_new` commits per batch and re-derives its work list from
chunks lacking vectors, so an interrupted index is partial, not corrupt.
Verified by sending a real SIGINT mid-call rather than raising one.

**An unrecognised model now offers the near misses.** `/model minimax 3` used to
print "setting it anyway", 400 on the next turn and auto-revert. It lists what
you probably meant, with `[enter]` to force the raw query through anyway —
forcing has to stay possible, because `MODELS` is not exhaustive and a valid
unlisted id is a legitimate thing to type. This closes the "should `/model` be
stricter?" question `BACKLOG.md` parked for Cas, and neither of the two options
that entry offered is what he chose.

`suggest_models` is separate from `resolve_model` and looser (0.6 vs 0.7),
because a suggestion is offered rather than acted on. Two strategies, because
difflib alone misses the obvious case: `minimax 3` folds to `minimax3` and
scores below any usable cutoff against `minimaxminimaxm3` — a short query
against a long id always does — but the word `minimax` is a plain substring of
every minimax id. So words first, difflib's near-misses second. The cutoff was
measured over the eight ids in the live `MODELS`: real near-misses land at
0.67–0.69, pure noise reaches 0.47, and 0.6 sits in the gap with room on both
sides. **An empty list stays a real answer** — `shanhaig` resembles nothing in
the pool and still passes through, because a picker that invents a suggestion
for input matching nothing is one people stop reading.

**`/routines` reached the model.** It wasn't an alias, and an unrecognised verb
doesn't error — it falls through to the model, so the plural cost an API call
and a confused answer. One line. `tests/test_parse.py` used `/routines` as its
example of the prefix trap (`/tagfoo` is not `/tag`); the guard is kept and its
example moved to `/helper`, since a deliberate alias is the opposite of an
accidental prefix match.

**`VAULT_PATH` is not the vault, and now something is.** Chasing "`/list
routine` prints the whole mount path" turned up that there is no vault-root
setting at all: `ROUTINE_DIR`, `WIKI_DIR`, `JOURNAL_DIR` and `MOVE_ROOTS` are
each configured independently with a `<vault>/…` comment describing a root that
existed only in the docs, and `VAULT_PATH` — which `/config` labelled "Vault
path:" — is the *export destination*, on this machine not even inside the vault.
New `VAULT_ROOT`, **display only**, read with `getattr` so a config written
before today keeps working, and empty means "print paths in full". `/config`
now prints both lines under their real names.

`ui.vault_relative` does the trimming, next to `format_ts` and for the same
reason — `ui.py` is the bottom of the dependency graph, so it takes the root as
an argument rather than importing config. It shortens relative to the vault's
*parent*, keeping the vault's own name, and **leaves a path outside the root
alone**: a directory configured somewhere unexpected should look different
rather than be trimmed until it reads as local.

**Testing.** A new `tests/test_embed.py` (16 assertions) fakes httpx wholesale
rather than pointing at a closed port — eleven seconds per run, and the OS
decides whether a dead port refuses or drops, while what is being tested is our
classification. It pins the timeouts *as a pair* rather than as two numbers, so
retuning stays free and merging them back into one does not. Both halves were
confirmed to fail with the fix disabled: 2 assertions on the merged timeout, 4
on the removed dead-server branch. `test_model.py` gained the near-miss list and
all four of its exits, `test_hub.py` gained `vault_relative` beside `format_ts`.

The golden baseline moved by exactly two lines, both intended (`Vault path:` →
`Vault root:` + `Export path:`), and `VAULT_ROOT` is now **pinned to the fixture
vault** in `golden.py`. That is not hypothetical tidiness: unpinned, the
baseline said `(not set)` and would have failed the moment Cas filled his config
in — the same class as the API key and the model lists, a `check` failure on a
line that says nothing about the source.

---

## 2026-07-26 — Fix the Windows shortcut splash quality and wt.exe launch failure
Both desktop shortcuts were broken as one story: the shortcut in the wrong
terminal worked, the shortcut in the right terminal didn't launch. Root-caused
both with measurements rather than guesses; fixed launch.sh and the shortcut
target, no application code touched.
- Files: launch.sh
- Status: shipped
- Commit: 203f8a8

**The splash bands because `launch.sh` runs before `.bashrc` ever does.** The
shortcut execs `launch.sh` directly via its shebang — no login shell, no rc
file — so `COLORTERM` is unset even when the real terminal is Windows
Terminal, which is genuinely truecolor-capable. Rich then falls back to
256-colour detection from `TERM=xterm-256color` alone, and `splash._resize`'s
box-average resample bands on a 256-colour palette exactly as its own
docstring predicts for a non-truecolor console.

Measured, not assumed, through the actual shortcut-invocation path (a
throwaway `diag.sh` printing `COLORTERM`/`TERM`/`WT_SESSION`/
`rich.console.Console().color_system`, deleted after use):

| | COLORTERM | color_system |
|---|---|---|
| shortcut (bare exec, before fix) | *(unset)* | `256` |
| shortcut (bare exec, after fix) | `truecolor` | `truecolor` |

`WT_SESSION` is set by Windows Terminal itself and survives through `wsl.exe`
regardless of login/non-login shell — confirmed present in the bare-exec
shortcut path — so it's a safe signal that the terminal really can render
truecolor, unlike forcing `COLORTERM=truecolor` unconditionally (which would
produce garbage on a genuinely non-truecolor console, e.g. legacy conhost
without Windows Terminal in front of it). `launch.sh` now exports it only when
`WT_SESSION` is present and `COLORTERM` isn't already set.

**The `wt.exe` launch failure was a WSL profile collision, not a cfc bug.**
`wt.exe -p Ubuntu -- wsl.exe -d Ubuntu ...` pairs a WSL-backed Windows
Terminal profile (which does its own internal distro activation) with a
manually specified `wsl.exe -d Ubuntu` override; the two lookups collide and
the manual one fails with `WSL_E_DISTRO_NOT_FOUND`. Fix: front the explicit
`wsl.exe` commandline with a non-WSL profile instead (`-p "Command Prompt"`)
— tab chrome is cosmetic and doesn't affect what actually runs. Also needed
`--` before the trailing commandline, since `wt.exe` parses its own argument
line before handing the remainder to `CreateProcess`, and will otherwise
strip quoting meant for the inner command.

**Not fixed, and machine-specific rather than a repo defect:** the *other*
shortcut (bare `wsl.exe -d Ubuntu --cd ~ -- bash -lc "..."`, no Windows
Terminal) still bands. That one *does* run a login shell, so `~/.bashrc`'s
own unconditional `export COLORTERM=truecolor` (line ~126, not part of this
repo) fires — but in whatever console actually hosts that shortcut, forcing
truecolor may be the same lie in the other direction: asserting a capability
the host can't actually render. Whether that console is legacy conhost or
gets silently upgraded by Windows 11's default-terminal-host delegation
wasn't established, and isn't worth chasing — the Windows Terminal shortcut
above is the documented, working entry path.

## 2026-07-26 — Fix four defects from the 0.8 testing pass
Four unrelated things that were all wrong rather than merely owed, from Cas's
`00 inbox/testing 0.8` scratchpad. No new claims — the v0.8.1 half of that list.
- Files: ui.py, hub.py, commands.py, tests/test_hub.py, tests/test_model.py,
  tests/golden_baseline.txt
- Status: shipped
- Commit: a8b7e8f

**The clock was two hours out, and two panels on one screen disagreed.**
`db.py` is the only module that stores UTC (`new_session`, `save_message` write
`datetime.now(timezone.utc)`); routines, the scheduler, the mover, the backup
rotation and `hub._freshness` all write local naive time. `ui.format_ts` parsed
the stored string and formatted it **without converting**, so every session
timestamp printed in UTC — and since the hub stacks Recent chats (from the db)
directly above Routines (from the run log), the two panels ran two hours apart
in the Netherlands. Now converted when the value carries an offset, and left
alone when it is naive, because everything naive here is already local and
assuming UTC would move the one set of times that was right.

The golden harness cannot catch this — `SCRUB` normalises timestamps on both
sides — so it is pinned in `tests/test_hub.py` instead, against an offset
computed five hours from *this* machine's. A test written against a literal
`+00:00` passes without the conversion on a UTC box.

**The token bar's empty state read as full.** The trough was `░` (U+2591 LIGHT
SHADE), which is a *fill* character; twenty-four of them look like a bar with
something in it, so a session 0.1% into a 1M context appeared meaningfully
used. Reported as "the bar starts out 1/6 full" — the 1/6 was the widget's
share of the terminal width, and the arithmetic was correct throughout. Only
the empty state lied. Now `[████        ]`: whitespace cannot be misread as
fill, and the brackets keep the one thing `░` was good for, which is showing
where the end of the bar is.

**One numbering, everywhere.** The picker numbered rows 1..n while `/list`,
`/delete chat` and `/export chat` all take a session id. `hub._add_rows`
carried a comment warning that these were different numbers and that conflating
them was how you opened the wrong session — which is what happened, from the
other side: a row read off the picker as "3" typed at `/delete chat 3`, where
3 is an id, and that command destroys data. The picker now shows and accepts
ids, the `numbering=` fork is gone, and an id that exists but **isn't listed**
is refused rather than resumed — the picker's rows are filtered to chats, so
accepting any id would let a wiki page or a routine transcript open as a
conversation. Four assertions confirmed to fail with that check removed.

Two smaller things fell out of it. The `#` column became `ID` for every view,
which fixed a latent width bug: it was declared 3 in `_CHROME` and then widened
to 4 in `list_sessions`/`show_recent_chats` *after* `_widths()` had already
divided up the terminal, so those two tables were quietly one column over
budget. And `Updated` is now `Latest message`, which is what the column has
always actually meant.

**An exact model name no longer opens a picker.** Ids are `vendor/model` and
nobody types the vendor, but only the full id counted as exact — so
`deepseek-v4-pro`, which *is* a whole model name, fell through to the substring
tier and matched three (`…-v4-pro`, `…-v4-pro:thinking`,
`…-v4-pro-cheaper:thinking`). `resolve_model` gained a bare-name tier between
exact and substring: the segment after the last `/`, folded. Split before
folding, since `_norm` eats the slash. An exact name beats a prefix of a longer
name, so `glm-5.2` now means the non-thinking one rather than a question, and
two vendors shipping one model name still falls through to the picker — which
is what the picker is for.

## 2026-07-25 — Rewrite the handover for a reader who has the repo
`HANDOVER.md` was written for a model working *without* the source — Claude App,
or any session with no file access — so it re-described a great deal that is now
simply readable. That reader no longer exists here, and the cost of carrying the
old shape was paid at the top of every session: 1558 lines, 150 KB, most of it
derivable from one file.

The new one is 407 lines and holds only what reading the code cannot produce:
the settled decisions and the failure behind each, the rejected designs that
will look like good ideas again (the timer thread, one scheduler entry per
routine, widening `WRITE_ROOTS`), the provenance of the tuned constants, the
producer/parser drift table, the scars — bugs that were live and silent — and
what is still unverified. Cut wholesale: the splash compositor's arithmetic, the
schema listings, the command grammar, the module-by-module narrative, the test
suites enumerated by name. All of that is in the code, and a second copy is a
copy that goes stale — which this file had already done once.

Two ideas that had generated about a third of the old document are now stated
once, near the top, so they can be re-derived rather than looked up: **model for
judgement under ambiguity, code for anything with a right answer**, and **prefer
the failure that is visible** — with the note that a new guard should fail open
or closed deliberately, because `tools.reserved_write_reason` and the journal's
git guard point in opposite directions on purpose.

The old file is kept as `HANDOVER-legacy.md`, frozen at v0.8 with a header
saying so, and is out of the update loop from here. It holds the long-form
reasoning behind most of the new file's one-liners; deleting a record of why
things are the way they are is how they get re-decided.

`README.md` is rewritten with it, per the coupling: the operational half kept in
full (setup, the command tables, the Task Scheduler entry, the Windows shortcut,
the vault's git setup) and the design essays that now live once in HANDOVER cut
to a line each. 46 KB → 34 KB, at the same line count — the prose that went was
replaced by tables, which is the trade a reference document wants. One stale
claim fixed on the way: README still said wiki destinations were "refused
outright", which v0.6 replaced with filing plus a loud staleness marker. Also a
garbled example of the retired-verb notice, and two things missing from README
entirely — the routine `review` flag, and the run log being closed to
`write_file`.

The "Where to read" paragraph no longer says HANDOVER wins on every point of
detail. It doesn't, deliberately: on mechanism, the code wins. Changed in both
`CLAUDE.example.md` (tracked) and the local `CLAUDE.md` (gitignored, so it isn't
in this commit).
- Files: HANDOVER.md (new), HANDOVER-legacy.md (was HANDOVER.md), README.md, CLAUDE.example.md
- Status: shipped
- Commit: 93585e2

## 2026-07-25 — Documentation for v0.8
`README.md` and `HANDOVER.md` rewritten together, as they are coupled. README's
in-session command section is now built around the grammar rather than a 47-row
table — the three questions first, then the verbs grouped by what they do — plus
traits as the third pool, the resolver's forgiveness, the `/remove`-vs-`/delete`
line (whether retyping gets it back), the two deliberate grammar exceptions, and
what happens to the `:` commands.

HANDOVER replaces the recorded-early taxonomy section with what was built and
what reversed on the way, and gains five: `parse.py` and the `startswith` trap it
closes structurally, `pools.py` and why the assembler had to come first, the
resolver's never-guess rule, traits, and short model names being display-only.
New invariant #13 — the surface is three lists that must agree, checked rather
than maintained, because an unrecognised verb goes to *the model*, so a
documented verb missing from the table is an API call rather than an error
message.

The v0.8 body moves from `ROADMAP_PRIVATE.md` into `ROADMAP.md` with its
completion date, per the split; Cas's note is his to write.
- Files: README.md, HANDOVER.md, ROADMAP.md, tests/test_private.py
- Status: shipped
- Commit: 524c006

## 2026-07-25 — /status, /list, the renames, and the flip
v0.8, blocks 6 to 9. `:status` and `:list` are the two absorbing verbs and the
biggest single cut: eight bare commands (`:title`, `:tokens`, `:prompt`,
`:persona`, `:tags`, `:attached`, `:model`, `:tools`) collapse into one screen of
session state, and seven listings into `/list <kind>`. The line between `/status`
and `/config` is ownership — session state versus deployment settings — which is
why "routine model" stays in `/config`.

Two things the brief routed to `/status` would have been quietly lost, so they
are kept: `/status prompt` prints the attached prompt's *text* (bare `:prompt`
was the only way to read one without opening the file), and bare `/tools` keeps
the three-switch diagnostic rather than the one-line summary.

Then the renames — `/delete chat`, `/search`, `/update db`, `/export chat 5`,
`/new p` — and the flip. `:` → `/` was one constant in the parser and touched no
handler, which was the whole argument for rewriting the dispatcher first. The old
prefix still works for this version and says so **once per session**, not once
per command; removing it next minor is deleting a constant.

Three things came out of doing it rather than planning it:

- **Retired verbs are corrected, not swallowed.** An unrecognised verb falls
  through to the model, so without a `RETIRED` map `:prompts` would have been
  *sent as a chat message* — an API call and a confused answer in place of a
  one-line correction. It echoes the prefix you typed, since "/prompts is now …"
  names a command that never existed.
- **The surface is three lists that have to agree** (the handler table,
  `parse.VERBS`, `RETIRED`), which is the drift hazard `HANDOVER.md` already has
  a table for. `main.py` asserts the table equals `VERBS`, and `test_parse` pins
  the rest: no alias collides with a verb, every retired verb points at a live
  one, nothing reserved is spent.
- **The `[:remember …]` marker keeps its colon.** It is a persisted storage
  format parsed by `db._MARKER_RE` and `backfill._MARKER_LINE`, not part of the
  command surface. Flipping it would have silently stopped every existing marker
  row from parsing — the exact failure that table exists to name.

Completion follows the surface: `/add` and `/remove` offer pool names in priority
order and switch to the filesystem via the same `parse.looks_like_path` dispatch
uses, so the two cannot disagree about one line — the failure `complete.py` has
already had once. `/list` completes its kinds. `test_complete` now points the
pools at a fixture rather than reading Cas's vault.

Golden re-baselined **once**, at the end, and the script rewritten to drive the
new surface — including the paths that print and act on nothing (`/delete` and
`/update` without a kind, `/add` with no match, a retired verb), because those
are the ones a rename quietly breaks. 213 → 290 lines.
- Files: parse.py, main.py, commands.py, hub.py, ui.py, complete.py, and the
  prose sweep across agent/backfill/mover/schedule/wikigit/preflight,
  tests/golden.py, tests/golden_baseline.txt, tests/test_parse.py,
  tests/test_complete.py, tests/test_mover.py
- Status: shipped
- Commit: 3d0c3d0

## 2026-07-25 — /add and /remove: two verbs across five mechanisms
v0.8, blocks 4 and 5, built together because they are two halves of one
resolver. `:prompt name`, `:persona name`, `:attach path` and `:tag name` were
four verbs for one idea — put this on the session — and `:prompt off`,
`:persona off`, `:detach n`, `:untag` and `:forget` were five for taking it off
again. They are now `:add` and `:remove`, still `:`-prefixed until block 8. The
old verbs still work; nothing is removed until the flip.

The shared resolver lives in `pools.py` as a pure core with a thin I/O shell in
`commands.py`, the same split `resolve_model`/`select_model` uses. It is
case-insensitive, resolves a unique partial, and **never judges under
ambiguity**: two different names matching equally well is a numbered pick, not a
guess. Tiers don't mix, so an exact name never loses to a near miss. A failure
names the forms and the pools it searched, so "typed it wrong" and "the thing is
broken" stay distinguishable.

`/add` searches what the pools *hold*; `/remove` searches what the session is
*carrying* — naming a real prompt you never attached has to fail rather than
succeed at nothing. A bare name walks the pools by priority (System > Persona >
Trait) and skips a pool already carrying that name, so repeating `:add relax`
walks down. That walk silently didn't advance at first: `sessions.system_prompt_name`
holds `relax.md` while a pool resolves `relax`, and comparing them raw meant the
name never looked attached. `pools.stem` normalises in one place — doing it per
call site is exactly how it broke.

`:remove excerpts` replaces `:forget`, reversing the standing decision's
"`:forget` becomes `/delete`": `:forget` never deleted anything, and the line
between the two verbs is whether retyping the command gets it back. A pool file
whose name contains `#` is refused and flagged in the listing — `#n` is the
attachment namespace, and a file that silently never resolves is the failure
shape this codebase keeps naming.
- Files: pools.py, parse.py, commands.py, main.py, tests/test_resolve.py
- Status: shipped
- Commit: 1114408

## 2026-07-25 — One assembler, three pools, and traits behind them
v0.8, blocks 2 and 3. `assemble.py` takes the system layers (persona → system
prompt → traits, one message each, empty layers absent) out of the chat path and
into one function, so a fourth layer is added there and not in each turn path.
Order is preserved rather than chosen: it is what shipped, and moving it changes
the bytes of every request for no argued reason.

`pools.py` then makes prompts, personas and traits **one mechanism**. All three
were already the same thing on disk — a folder of `.md` files where the filename
is the identity — and `commands.py` held three near-identical copies of the list
and load code. Writing a fourth for traits was exactly what extracting the
assembler was meant to prevent, so the three collapse to one `Pool` table and the
listing keeps its wording parameterised: golden is unchanged, character for
character. `Pool.dir()` reads `configured` at call time and is the single seam —
`golden.py` re-points the pools there instead of patching `commands`, which would
have missed anything reading the value at import.

Traits themselves: `TRAITS_DIR`, one file per trait (no id — the file is the id;
a combined file would need a parser, and that hazard has a five-row table in
`HANDOVER.md`), and a `traits` JSON column on `sessions` via the existing
on-connect `ALTER TABLE`. **Names are stored, never bodies** — bodies are re-read
from the pool every turn, so editing a trait file changes what every session
carrying that name sends. A name whose file has gone is skipped rather than
warned about per turn; `/status` is where that gap will show. Nothing is wired to
a command yet — that is block 4.
- Files: assemble.py, pools.py, db.py, commands.py, main.py, config.example.py,
  tests/test_assemble.py, tests/test_pools.py, tests/golden.py
- Status: shipped
- Commit: 4a6020e

## 2026-07-25 — Parse a command line once, dispatch from a table
v0.8, block 1 of 9. Command dispatch was a chain of `user.startswith(":foo")`
tests whose correctness depended on the order they were written in:
`":attached".startswith(":attach")` is true, so `:attached` had to be tested
first or it read as attaching a file called "ed" — a trap patched with a comment
rather than structurally, and one that returns every time a command is added
whose name prefixes another. `parse.py` now turns a line into a `Cmd`
(verb · args · raw) once, and `run_session` holds a verb→handler table. Exact
verb matching cannot have that bug; `:routines` and `:dbfoo` are simply not
commands.

The prefix is one constant in the parser, which is what makes block 8's `:` → `/`
flip a one-character change rather than thirty-five edits. Aliases (`h`, `?`,
`db`) resolve in the parser, so dispatch and completion cannot disagree about the
surface.

Behaviour is unchanged — `tests/golden.py check` passes byte-for-byte, which is
the harness's whole purpose — with one exception it could not cover: `:title abc`
reached a bare `int()` and took the REPL down. `Cmd.int_arg` returns a default
instead, and the affected commands print a usage line. Same class as the
`:routines` IndexError, fixed at the parser this time rather than per command.
- Files: parse.py, main.py, tests/test_parse.py
- Status: shipped
- Commit: 5ef0ba2

## 2026-07-24 — Documentation for v0.7
`README.md` and `HANDOVER.md` rewritten together, as they are coupled. README
gains a "The journal" section (the three tiers, why `REPLACES` is rendered
differently from `→`, why filing needs a committed corpus, and that missing days
is the intended outcome rather than a gap to paper over), a `trigger:` table
covering `weekly HHMM`, and the YAML-octal warning where someone writing a
trigger by hand will actually meet it. HANDOVER gains four sections — the
journal and its git guard, the cadence and what is never inferred, weekly
due-ness, and declining — plus two new invariants (an overwriting move owes a
*verified* undo; nothing in a routine infers its own date), a fifth row in the
producer/parser table (`append_log`'s status word ↔ `last_success`), and the
generalised version of the golden-baseline lesson.

Also cleared from the 0.6.2 testing pass: the whole-vault commit prompt reads
`(y/n)` rather than `[y/N]`. `BACKLOG.md` strikes the `:diff decline` entry and
gains three: notes are never removed from the inbox after processing (mitigated
by prompt, which is the weak half), Obsidian's template syntax collides with the
placeholder braces (latent, not live), and `:file` still takes a number rather
than a title.
- Files: README.md, HANDOVER.md, BACKLOG.md, commands.py
- Status: shipped
- Commit: a2a41af

## 2026-07-24 — Say what an unrecognised placeholder means
The unfilled-placeholder warning fired on its first real run — `{{content}}`
and `{{path}}` in the note-writer prompt — and the reasonable reading of it was
"something wants filling in by hand". It doesn't: an unrecognised `{{…}}`
reaches the model as literal characters in the middle of its instructions. The
warning now says so and names the set cfc *does* know, which turns "what is
this" into "ah, dead text" without opening the source.

Vault side: the `<note path="{{path}}">{{content}}</note>` block is deleted
from the note-writer prompt. It was a stub from a design where note content
would be injected inline; the routine reads the notes itself through the tool
loop, so nothing ever substituted it and the model had been reading the braces
verbatim every run. Found by the warning, which is what it is for.
- Files: runner.py (+ vault prompt)
- Status: shipped
- Commit: 19fb6cb

## 2026-07-24 — `:file <n> decline [why]` — reject a draft and record why
The other half of the review step, and the `BACKLOG` entry that asked for a
losers' folder. Declining moves a draft to `LOSER_DIR/<corpus>` — declined is
not deleted, and the draft that turns out to have been the good one has to be
recoverable — and stamps `declined:` / `declined_reason:` into its own
frontmatter.

**The reason lives on the draft, not in a log.** These pile up in one folder
and look alike; a reason kept anywhere else is a join you have to make a week
later from a filename and a timestamp, at which point you are re-deriving what
was wrong with the prompt instead of reading it. This is the one place the
mover edits frontmatter for its own purposes and the exception is deliberate:
*filing* deliberately adds no provenance keys, because a filed document is the
user's content, whereas a declined draft has left the pipeline and the
annotation is the entire reason it is kept rather than binned.

Written by hand rather than re-dumped through `yaml`, for the same reason
`_ensure_id` is — a `safe_dump` round trip re-quotes an unquoted digit id and
mangles a wikilink, and this vault's frontmatter is full of both. The reason is
quoted and escaped on the way in, since it is free text typed at a prompt and
an unquoted colon would cost the file its whole frontmatter block.

No new command verb: it is an argument to the existing `:file`, so it inherits
the numbering you are already looking at and the v0.8 `/` flip stays a pure
prefix change. `:file <n> drop` still works as the terse no-reason form.
- Files: mover.py, commands.py, tests/test_mover.py, tests/golden_baseline.txt
- Status: shipped
- Commit: f982eb5

## 2026-07-24 — Cadence: weekly triggers, computed dates, and a YAML octal trap
The journal's cadence, designed with Cas this session. Three parts.

**`trigger: weekly HHMM`**, and it does *not* mean "on Mondays". A weekly
routine is due when a completed calendar week exists that it hasn't absorbed —
`last_completed_week(today) > last_completed_week(last success)`. Two things
that buys: catch-up is free (miss Monday, it fires Tuesday absorbing the same
week, where a day-of-week check would skip the week entirely and nothing would
ever process it), and the cadence can't drift (a late run absorbs the week it
was always going to, instead of shifting every future week a day forward and
never back). It keys off the last **success**, not the last run — the first
version used the latest run of any kind, which let a *failure* mark the week
absorbed and skip it permanently; that bug is now a test.

**Dates are computed and injected, never inferred.** `{{dates}}` is the list of
days a daily routine owes entries for (today, or every day since the last
success after a gap, capped at 7 so a month's outage can't ask for thirty
entries in one turn); `{{week}}` is the Mon–Sun span a weekly one should
condense, always one that has ended. The rejected alternative was letting the
model infer the date from the file ("last entry is Thursday, so write Friday"):
self-consistent, and therefore permanently and silently wrong after a single
missed run.

**`trigger: 0300` was being read as 192.** YAML 1.1 types a leading-zero digit
string as octal, so the obvious way to write 03:00 arrived from `safe_load` as
an integer, and validation then rejected a trigger nobody had written. It bites
0000–0777 only — which is to say early-morning times, exactly when these jobs
run. `trigger:` is now re-read from the raw frontmatter whenever YAML returns a
non-string; narrow on purpose, since YAML stays the parser for everything else.
`safe_dump` already quotes it, so cfc-authored files were never affected —
only the hand-written ones, which is most of them.

Vault side: the three maintainer prompts rewritten for the new cadence (ST
daily against `{{dates}}` and keeping two calendar weeks rather than a count of
five days; MT weekly against `{{week}}`, condensing a whole week at once —
which it structurally could not do before, seeing one day per run while being
told to group thematically; LT on command, proposing what long term is missing
rather than rotating), and triggers set to `0300` / `weekly 0330` / `command`.
- Files: routines.py, schedule.py, runner.py, tests/test_routines.py,
  tests/test_schedule.py (+ vault prompts and routines)
- Status: shipped
- Commit: f58d1af

## 2026-07-24 — File journal drafts, with git as the undo
The v0.7 approve step. `99 outbox/journal/` becomes a second corpus subfolder
alongside `wiki/`, so the memory routines' drafts are reviewable by `:outbox`
at all — they were invisible, the outbox scanning only top-level files and
`wiki/`. The destination is the **filename**: `st memory.md` replaces
`st memory.md`, location declaring the corpus and the name declaring which file
in it, so nothing is taken from a model-written `destination:` key.

The hard part is that filing here **overwrites a live file** — that is what a
rollover is — and "a target that exists is a refusal" is one of the three
properties `mover.py` exists for. What replaces it is git: the journal is in
the vault repo, so the move is inspectable (`:wiki diff journal`) and
revertable (`git checkout`) — but only if the corpus was clean beforehand,
because against a dirty corpus the diff mixes the move with hand edits and
there is no commit to return to. So the clean check *is* the undo path, run at
plan time (so `:outbox` shows the refusal before you type `:file`) and again
inside `commit` (the one that guards the write). It fails **closed**: if git
can't be consulted, the move is refused rather than performed unrecoverably —
the opposite direction from the run-log rule in `tools.py`, and for the
opposite reason. Verified by disabling the guard: seven assertions fail.

Folded in from Cas's 0.6.2 testing pass, all on the same screen: `:file` and
`:file … drop` now **reprint the outbox**, because filing shifts every number
after it and a stale list means the next `:file 3` is a different file than the
verdict you just read; the outbox's own readme is **reserved** — not listed, not
droppable (a named rule beside containment, same shape as the run log, since
"has no frontmatter" would also hide a malformed proposal); proposals show
their frontmatter **title** beside the filename, so a list of wiki drafts stops
being a list of bare timestamps; and a declined draft goes to
`LOSER_DIR/<corpus>` rather than `99 outbox/dropped/`, split by corpus because
the reason to keep one is to debug the prompt that wrote it.
- Files: mover.py, commands.py, config.py, config.example.py,
  tests/test_mover.py
- Status: shipped
- Commit: 2cfa844

## 2026-07-24 — Inject `{{date}}` into routine prompts, and repoint them at the journal
The three memory prompts all said "Today's date is **{{date}}**, injected by
script" and nothing was injecting — the model read the literal braces and was
free to guess, which is the exact failure `SYSTEM`'s date line exists to
prevent. `runner.fill_placeholders` substitutes it from the run's own
timestamp, and *reports* any `{{…}}` it doesn't recognise through `on_event`,
because a misspelled placeholder left in the text is a silent false negative.
`str.replace`, never `str.format`: a prompt is hand-written markdown and a JSON
example or code fence would make `.format` raise, turning a nicety into a run
that never starts. Vault side (not in this repo): `03 resources/tiered memory`
had already been renamed to `journal` and `99 outbox/tiered memory` follows it,
so all three routines' roots and all three prompts' paths were pointing at a
folder that no longer exists — the failure already recorded in `BACKLOG.md` as
the one that motivated the `review` flag. Verified through `tools.dispatch`
under each routine's real context: the live journal is readable and *not*
writable, the outbox is writable, the dead path is refused.
- Files: runner.py, tests/test_routines.py (+ vault routines and prompts)
- Status: shipped
- Commit: bce703b

## 2026-07-24 — Configure the journal corpus, and stop the baseline pinning config
v0.7 groundwork, plus two faults it turned up. `JOURNAL_DIR` is now a real
config key, so `:wiki … journal` — reserved but unusable since v0.6.2 — resolves;
the mover will file journal drafts there next. Turning it on failed
`test_wikigit`, which asserted "an unconfigured corpus is refused" against
*this machine's* config rather than a forced value: the property is real, the
test was reading the wrong source. Same bug, larger, in `golden.py` — `:config`,
`:models` and `:tools` print `MODELS`/`TOOLS_MODELS`/`MODEL`/`API_BASE`
verbatim, so editing your own config failed `check` on lines that say nothing
about the code, exactly the tripwire the API-key scrub exists to prevent. Both
now pin fixture values instead. Scrubbing was the wrong tool for the model
lists: `:models` renders a table whose column width is the longest id, so the
layout is config-derived too. Re-recorded; the diff also lit up the
`<-- current` row, which no real config had been exercising.
- Files: config.py, config.example.py, tests/golden.py,
  tests/golden_baseline.txt, tests/test_wikigit.py
- Status: shipped
- Commit: 032dc66

## 2026-07-24 — Stop `:routine` taking the app down on a typo
`:routines` (or any `:routineX`) matched the bare `startswith(":routine")`
branch, then indexed `[1]` of a one-element split — an uncaught `IndexError`
out through `repl()` to the shell, losing the session. The dispatch now matches
`":routine "` with the trailing space, the same guard `":wiki "` already had, so
a near-miss falls through to the unknown-command message. Found in Cas's 0.6.2
testing pass.
- Files: main.py
- Status: shipped
- Commit: 032dc66

## 2026-07-24 — Fix a missing comma that silently disabled two models' tools
`TOOLS_MODELS` had `"minimax/minimax-m3:thinking"` and `"minimax/minimax-m3"` on
adjacent lines with no comma between them, so Python concatenated the literals
into one nonexistent id and *neither* minimax model was in the list. `:tools`
duly reported "NOT in TOOLS_MODELS" with nothing to suggest why. Config-only
(gitignored); recorded here because the failure mode — adjacent string literals
in a list — is silent and will happen again.
- Files: config.py
- Status: shipped
- Commit: 032dc66

## 2026-07-24 — Split a routine's outcome into two signals
A run's log status was one ok/failed bit, but it was carrying two facts: did the
loop mechanically complete, and did the model actually do the task. A run that
finished saying "I cannot perform this task, those files are outside my allowed
roots" logged a clean `ok` — a nightly job doing nothing, invisibly. `status`
now stays loop-health only; a second, orthogonal `review` flag rides alongside
it (`ok (review)` in the log), set by `runner.looks_unclear` from the model's
final message (first-person / jail-block phrases, biased to over-flag). `last_run`
returns `(status, ts, review)`; the hub panel and `:routine` show a yellow
`review` distinct from red `failed`, and `do_routine` flags it live. Kept out of
`status` so `on_failure` never retries a run that didn't fail.
- Files: runner.py, routines.py, hub.py, commands.py, schedule.py,
  tests/test_routines.py, HANDOVER.md, BACKLOG.md
- Status: shipped
- Commit: 2688e47

## 2026-07-24 — Log the scheduler tick, and default its window hidden
`run-due.sh` now redirects its own stdout/stderr to `~/.cfc/schedule.log`
(rotated by size) with a dated heartbeat per tick, so a failure *before* cfc's
per-routine logging — a vanished venv, a bad cd, a traceback, the embedder down —
is no longer discarded along with a hidden console window. The README's Task
Scheduler recipe now defaults to "run whether logged on or not" (`/RP *`, no
window), with the reasoning: a window popping up every 15 minutes gets the task
disabled or the interval stretched until routines batch-fire, defeating
per-routine trigger times. Hidden is safe because the output now has somewhere
to go.
- Files: run-due.sh, README.md, HANDOVER.md
- Status: shipped
- Commit: 2688e47

## 2026-07-24 — Auto-revert off a model the provider rejects
`:model X` for an unlisted X sets it anyway (MODELS isn't exhaustive) but used to
*persist* it, so a nonsense name 400ed every turn and survived reopening the
session — you only noticed via `:models`. Switching to a model not in
`known_models()` now arms a revert: the first turn that errors on it backs out to
the model you were on, printing `provider rejected 'X' — switched back to Y`
instead of the raw error. Scoped to a just-set unverified model, so no provider-
wording match is needed and a turn that succeeds disarms it — a valid unlisted
model is never reverted on a later hiccup, a known model is never armed. Both turn
paths call the one `revert_bad_model` helper. Inherited by private chat.
- Files: main.py, tests/test_model_revert.py, HANDOVER.md, BACKLOG.md
- Status: shipped
- Commit: bd4a887

## 2026-07-24 — Let a routine pin its own model
Routines gained an optional `model:` frontmatter field, so a routine can declare
the model it runs on instead of every scheduled run inheriting the single vetted
default. `runner.effective_model` resolves one order everywhere — routine pin ›
caller's (session) model › vetted default — and both `do_routine` (the y/n nudge)
and `run_routine` go through it, so the warning names the model that actually
runs. The field stays an opaque string in `routines.py` (which imports no config)
and is omitted from the file when unset. `:routine new` offers a model pick
(blank = no pin); `:routine` shows a model column.
- Files: routines.py, runner.py, commands.py, tests/test_routines.py,
  HANDOVER.md, BACKLOG.md
- Status: shipped
- Commit: 1d50e45

## 2026-07-24 — Per-corpus, per-file `:wiki` — and a guard on the vault sweep
`:wiki diff`/`:wiki commit` grew a grammar: `:wiki <action> <scope> <granularity>`.
Scope picks the corpus (`wiki` default, `journal` for v0.7's tiered memory,
`vault` replacing the old `all` — kept as a soft alias), granularity picks whole
-folder (default) or `file` — a numbered picker over the changed files that
diffs or commits **only** the one you choose. That's the BACKLOG top entry:
inspect one file's diff, commit that one, not the whole set. `:wiki commit vault`
now asks `[y/N]` — it's the whole-repo sweep that once committed 202 files at
once. Scope resolves through `wikigit.scope_dir`, a registry v0.7 extends with a
single line rather than a new branch. Short forms (`:wiki diff`, `:wiki commit
<msg>`) are unchanged. No move/commit merge — filing (`:file`) stays separate, so
the `:updatedb` re-import still sits between move and commit.
- Files: wikigit.py, commands.py, main.py, tests/test_wikigit.py,
  tests/golden_baseline.txt, HANDOVER.md, BACKLOG.md
- Status: shipped
- Commit: cb2ad1f

## 2026-07-24 — Forgive loose `:model` queries
`:model` used to set whatever string you typed, so a one-character slip
(`kimi-2.6` for `kimi-k2.6`) went through and came back as an opaque provider
400 a turn later. It now resolves the query against the models you've configured
(MODELS ∪ ROUTINE_MODELS): an exact id switches silently; a single strong match
asks "did you mean X?"; several matches offer a numbered pick (the hub picker's
idiom, not a new arrow-key mode); a near-miss is caught by a fuzzy nearest;
only a genuinely unrecognised id is set raw, with a note so a typo can't pass
as intent. `resolve_model` is a pure, tested core; `select_model` is the I/O
shell. Inherited by private chat for free — it's the same `:model` dispatch.
- Files: commands.py, main.py, tests/test_model.py
- Status: shipped
- Commit: b94666f

## 2026-07-24 — Guard routines against models that stall
Add a `ROUTINE_MODELS` config list of models vetted for unattended runs. Its
first entry is the default a scheduled `--run-due` uses when no model is passed
— closing the hole where a scheduled routine silently inherited the interactive
chat default (`MODEL`), which may be a model that stalls on empty completions
(GLM-5.2:thinking did, repeatedly). An on-command `:routine` still uses the
session model but nudges (y/n) when it isn't in the list. Membership, not a
"thinking-model" guess — the list is the judgement, since some thinking models
run routines fine. Unset/empty ⇒ fall back to `MODEL`, no nudge.
- Files: runner.py, commands.py, config.py, config.example.py, tests/test_routines.py
- Status: shipped
- Commit: 6826e92

## 2026-07-24 — Record the session id in a failed routine's log line
A failed run's session id lived only on the ephemeral terminal line; the durable
log recorded it for `ok` runs but not failures — so on the scheduled path (no
terminal) the transcript of the run you most want to open was unfindable. Both
failure paths in `run_routine` now append `(elapsed, session N)` to the log,
matching the `ok` line.
- Files: runner.py
- Status: shipped
- Commit: 6826e92

## 2026-07-24 — Re-roll the empty-completion 400 on the tool path
A thinking model's occasional empty completion arrives as an HTTP 400 (`The
model returned an empty response`) on the non-streaming tool path, not as a 200
with empty content — so it escaped through the exception door and neither the
stream re-roll nor `runner._turn_with_retry` (both keyed off an empty *return*)
ever saw it, and a routine died on a transient the retry machinery exists to
absorb. `agent_turn` now recognises that specific 400 by its wording and returns
an empty message, mapping it back onto the empty-completion path: routines
re-roll and fail only if it persists, chat drops the turn. Only that 400 is
caught — every other 400, oversize above all, still raises. Inherited by private
chat for free.
- Files: agent.py, tests/test_agent.py, HANDOVER.md
- Status: shipped
- Commit: 7c14235

## 2026-07-23 — Record the v0.8 command taxonomy as a standing decision
Settled the verb spine ahead of the work that implements it, so a command added
before v0.8's `:` → `/` flip is named by the verb it will carry after — keeping
the flip a pure prefix change instead of a rename. `/add` (internal attach),
`/attach` (external files), `/connect` (reserved), `/remove` (universal detach),
`/delete` (memory, replacing `:forget`), `/import`·`/export` (sessions). `/swap`
deliberately deferred. Docs only, no code — the build itself is v0.8.
- Files: HANDOVER.md, CLAUDE.example.md
- Status: shipped
- Commit: 7c41537

## 2026-07-23 — File proposed pages into the wiki, id stamped at approval
The mover refused wiki destinations outright, because a page landing in the
corpus while the recall index is unaware makes recall answer from a stale copy
with **no signal it is stale** — a silent failure that arrives weeks later.
v0.6 resolves that rather than deleting the guard: the move is allowed, and the
staleness is made *loud* with a one-command fix.
- **`99 outbox/wiki/` is a second proposal source.** A draft dropped there is
  wiki-bound by location and needs no `destination:` key — the folder is the
  signal. The top-level "*.md only" rule (which keeps run logs out) is intact;
  the wiki subfolder is an explicit addition, not a recursion.
- **The id is stamped at approval, by code, never by the model.** A wiki page
  is keyed by a frontmatter id and named `<id>.md`; import_wiki silently skips
  one that has none — the same silent staleness by another door. Rather than
  refuse a draft without an id (a dead end), `:file` stamps
  `id: YYYYMMDDhhmmss`, monotonic so a `:file all` batch in one second can't
  collide (which would make import_wiki treat two pages as one). A draft that
  already carries an id keeps it; a page whose id already exists is refused as
  an edit, not clobbered.
- **Loud staleness replaces the refusal.** Filing into the wiki sets a marker
  (`~/.cfc/wiki_reindex_needed`, a file so it survives the session with no
  schema change); `:file`, `:outbox` and `:wiki` all say "recall index stale —
  run `:updatedb`". `:updatedb` now re-imports the wiki (idempotent, keyed by
  id) before embedding, then clears the marker — the explicit reindex step,
  kept out of per-turn auto-embed on purpose.
- **`:wiki commit` discoverability.** The `<message>` placeholder read as if it
  wanted special syntax; the empty-message case and the diff/updatedb hints now
  show a worked example (`:wiki commit tidied the aquarium pages`).
- `import_wiki.run_import()` extracted from `main()` so `:updatedb` can call it
  without shelling out.
- Verified against the real config: a draft in the actual `99 outbox/wiki/`
  plans as wiki-bound needing an id; `run_import` pulls the real 21 pages and
  is idempotent on a second pass; the marker round-trips under a redirected db.
- Files: `mover.py`, `import_wiki.py`, `backfill.py`, `commands.py`,
  `tests/test_mover.py`, `HANDOVER.md`
- Status: shipped
- Commit: 5f8c7f7

## 2026-07-23 — Normalise routine ids to slugs at load, not reject them
Routines are hand-authored in Obsidian, where `id: note reader` is what you
naturally type — and the strict slug check turned every hand-made routine into
a validation failure it could not run past. The id is now coerced to a slug at
the one construction chokepoint (`Routine.__init__`), the same place `body` is
stripped, so it is a clean handle everywhere it is used (log filename, session
lookup, `:routine <id>`) while the *file* keeps whatever was written until cfc
itself next saves it. The name stays free text; only the id coerces.
- The only cost: a routine that had been logging under a spaced id starts a
  fresh log under the slug. All current routines are fresh, so this is moot now.
- `validate()` no longer reports "not a slug" (unreachable after coercion); it
  still catches an id that slugifies to nothing as "id is empty".
- Files: `routines.py`, `tests/test_routines.py`
- Status: shipped
- Commit: 5f8c7f7

## 2026-07-23 — Run routines on a schedule, from one OS entry
`main.py --run-due` is the headless entry point an OS scheduler calls on a
fixed tick; cfc works out what is actually due from each routine's own
`trigger:` field and its run log. The rejected alternative was one scheduler
entry per routine — that makes `trigger:` decorative and puts the real
schedule outside the vault, free to drift from the file that claims to hold
it. A new routine now needs no change to the OS scheduler at all.
- **The run log is the only state.** No "last tick" file, no DB table: whether
  something already ran today is answered by reading the log it already
  writes. A scheduled run is a fresh process with nothing to remember, and a
  second source of truth is a second thing to get out of step.
- **Catch-up is same-day only.** A machine that was off at 03:00 runs the job
  when it comes back, if it is still that day; three days off does not queue
  three runs.
- **`on_failure` is honoured at last** — `retry` means "again on the next
  tick", `skip` means "wait for tomorrow" — and bounded by
  `MAX_RETRIES_PER_DAY` (3). Without the bound, a routine failing for a
  permanent reason retries every 15 minutes until midnight at full API cost,
  unattended. That is the one failure this module could cause that is worse
  than not running.
- **The idle tick is silent, cheap and exits 0**: it reads a few files, opens
  no database and writes no backup. It runs ninety-odd times a day, and a
  scheduler log full of "nothing due" is a log nobody reads.
- `flock` on `~/.cfc/scheduler.lock` so two ticks can't overlap; the kernel
  releases it if a run is killed, so there is no stale lock to look exactly
  like the scheduler having been switched off.
- Also `--run-routine <name>` (force one now) and `--due` (report, run
  nothing). `python main.py 5` is unchanged; the flags branch before the
  backup and the splash.
- Verified end to end against the real config: an idle tick is silent and
  exits 0; a routine with a past trigger runs, writes its file, logs `ok` with
  the `touched` field, and is not due again on the next tick.
- Files: `schedule.py` (new), `run-due.sh` (new), `main.py`,
  `tests/test_schedule.py` (new, 43 assertions), `README.md`, `HANDOVER.md`
- Status: shipped
- Commit: 7dfc4de

## 2026-07-23 — Bound a tool turn by calls and by output, and never leave a call unanswered
Three faults were wearing one symptom: a provider 400, mid-turn, whenever the
model was let loose on a tree of files.
- **An interrupted tool turn poisoned the session in place.** `agent_turn`
  appends the assistant message carrying `tool_calls` to `history` *before*
  dispatching them, so Ctrl-C at the approval prompt left calls with no
  results — a conversation the API rejects forever after. `db.load_history`
  drops such orphans on *replay*, so `:q` and reopen silently repaired it,
  which is exactly what made this look intermittent and provider-shaped. Every
  call now gets exactly one result on every path out of the loop, exceptions
  included, in live history and the DB together.
- **The call ceiling counted loop iterations, not calls.** A model asking for
  four reads in one message spent one of eight, so eight iterations could be
  thirty reads at up to 30,000 chars each — a ~225k-token request, re-sent on
  every subsequent call. That is where the 400s about `max_tokens` (a
  parameter cfc does not even send) came from. It counts calls now, and the
  ceiling is 25 for chat, 30 for routines.
- **Nothing bounded a turn's total tool output**, which is what actually grows
  the request. `TOOLS_MAX_TURN_RESULT_CHARS` (120,000) does. Spending it
  withdraws the tools for one final call rather than truncating the turn, so
  the model answers in its own words — deliberately *not* the `LIMIT_MESSAGE`
  exit, which `runner.py` reads by identity to log a truncated run as failed.
- Raising the ceiling alone would have made the 400s **worse**; the two
  budgets had to land together. Roam widely, read narrowly.
- The model is told both budgets up front and nudged at 75% of its calls, as
  riders on the request rather than lines in the conversation — so nothing
  about cfc's budgets is persisted, exported or replayed.
- A failed request now reports what was in flight (call n/m, message count,
  estimated tokens, chars of tool output) beside the provider's own words. The
  three causes above were indistinguishable without it, and the third —
  content-filter refusals — is provider-side and still open; see `BUGS.md`.
- Applies to **both chats**: the fix is in the shared turn path, so private
  chat inherits it with no flag.
- Files: `agent.py`, `main.py`, `runner.py`, `commands.py`,
  `config.example.py`, `tests/test_agent.py`, `tests/golden_baseline.txt`
- Status: shipped
- Commit: 2a9661c

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
- Commit: ce75730

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
- Commit: d085678

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
- Commit: 947dbf0

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
