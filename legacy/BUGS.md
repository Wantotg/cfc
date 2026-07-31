# Known bugs — archive

**Everything below the split line is `BUGS.md` as it stood on 2026-07-27,
immediately before the v0.9 archive split, kept whole.** The live file is
[`../BUGS.md`](../BUGS.md), which holds open entries only.

**This file is not closed.** It is where a closed entry goes from now on:
newest at the top, under a *Closed since the split* heading above the snapshot,
moved whole rather than summarised — see `legacy/BACKLOG.md`, which has one.
"Archive" is the ongoing rule, not a one-time snapshot: the text below the
split line is what is frozen, not the file.

---

# Closed since the split

## ~~B-1.2-04 · A model revert lands on a model the provider already rejected~~ — CLOSED (v1.2.1, 2026-07-31)

**Closed 2026-07-31.** `run_session` now keeps a `rejected_models` set beside
`revert_model`, fed on an HTTP 400 only (never a transient or transport
failure) before deciding how to recover. If the fallback `revert_bad_model()`
would switch back to an id already in that set, it disarms instead of
reverting and says plainly that neither id is known-good, rather than
printing "switched back to X" over an X the same session already had refused.
In-memory only, so it resets every session; a private chat's throwaway
connection carries it the same way. Pinned in `tests/test_model_revert.py`,
32 assertions across both turn paths. `CHANGELOG.md`, 2026-07-31.

The entry as it stood:

---

## B-1.2-04 · A model revert lands on a model the provider already rejected

**Found:** 2026-07-31, v1.2 playtest, reported by Cas.

**Symptom:** two lines from one session, in this order —

```
[error] HTTP 400 from https://api.nano-gpt.com/v1/chat/completions:
        Model moonseek is not supported on /v1/chat/completions.
LATER
[error] provider rejected 'deepkseek' — switched back to moonseek
```

So the session was on `moonseek`, which the provider had already refused;
`/model deepkseek` was also refused; and `revert_bad_model()` put the session
back on `moonseek` and reported it as a recovery.

**Where to look:** `main.py`'s `revert_bad_model()` and the `revert_model`
local it reads. Arming happens at every model switch and holds exactly one id —
the previous session model — with no record of whether that id has already
failed. Nothing there is wrong on its own terms: it backs out the switch you
just made, which is what it says it does.

**What is wrong is the sentence over the outcome.** `switched back to moonseek`
reads as *fixed*, and cfc knows enough to know it isn't: the 400 naming
`moonseek` went through `handle_turn_error` in the same session and was written
to `errors.log`. This is the shape `HANDOVER.md` calls green over a dead
server — the reassurance that stops you checking.

**Leading hypothesis, and it is small:** the session already collects what it
needs; it just doesn't keep it. A set of ids the provider rejected during this
session, consulted before reverting onto one, is enough — either decline the
revert and say the previous model was refused too, or revert and say so. Which
of those it should be is a wording question, not a structural one.
`tests/test_model_revert.py` is where it would be pinned.

**Not in scope here:** *"fall back to a model in `config.py`"*, which is what
the report asked for. `MODELS` is a list of ids config asserts, not a list of
ids known to work — `moonseek` was in it. A fallback needs a source of truth
about which models the provider actually serves, and cfc has none. That is
`W-08` and `Q-1.1-12`, and building a fallback before either is answered would
pick the next unverified id instead of this one.

## ~~B-04 · The connection advice tells you to go to a chat, from a screen that can do it~~ — CLOSED (v1.2.1, 2026-07-31)

**Closed 2026-07-31.** Every fixable `ui.CONNECTION_STYLE` row now names both
places the command can be typed: *"/connect embedding in a chat or connect
embedding in config"*. One string, still standing decision 16's single source
of truth — no `where=` parameter, no producer/parser fork on the screen's
side. Driven through all three real renderers. `CHANGELOG.md`, 2026-07-31.

The entry as it stood:

---

## B-04 · The connection advice tells you to go to a chat, from a screen that can do it

**Found:** 2026-07-31, by reading during the v1.2 triage, not by use. Never
observed live: it needs a non-green embedder while the config screen is open,
and both the coder and the playtest had a healthy one.

**Symptom:** the v1.2 config screen renders `preflight.connection_state()`
through `ui.connection_light()`, so its Embedding row prints, verbatim:

```
Embedding    ● LM Studio is not running — start it, or /connect embedding
             in a chat
```

The config screen's own command for this is `connect embedding`, listed on its
help screen and three lines below the row saying to go elsewhere. Typing
`/connect embedding` there works exactly as typed — `classify` strips one
leading slash, and `_config_connect` requires the `embedding` argument — so
every word of the advice is right except the two that send you away.

**Same class as `B-1.2-01`, and that is the reason to record it rather than
patch it:** a string written for one reader, given a second reader by v1.2.
`B-1.2-01` closed because the producer and the new reader were both in cfc's
own modules and a parameter could reach across. This one cannot take that fix.

**Why it is a designer's question.** Standing decision 16 puts the advice in
`ui.CONNECTION_STYLE` precisely so there is one copy — the last time a second
copy existed (`commands.connect_status`) it had already gone wrong, and it was
deleted rather than corrected. But `ui.py` imports no cfc module, so the advice
cannot know where it is being rendered, and the two obvious repairs both cost
something a standing decision protects:

- **a `where=` parameter on `connection_light()`** — one copy still, but every
  caller now asserts its own context, and a caller that forgets gets the
  current bug back silently.
- **the screen rewriting the string** — a producer/parser pair on prose, which
  is the shape `HANDOVER.md`'s recurring-hazard table exists to stop.

A third option is that the advice simply stops naming a place (*"start it, or
run connect embedding"*), which is true at all four renderings and costs the
one thing `B-0.9.1-03` added it for. That is a judgement about which reader
matters more, and it belongs to whoever owns decision 16, not to a triage pass.

## ~~B-0.9.1-01 · Denying a tool call is reported as an error~~ — CLOSED (v1.0, 2026-07-29)

**Closed 2026-07-29**, v1.0 step 3, exactly where the entry said to put it: at
the render, never at the payload. `{"error": "user denied"}` still goes to the
model unchanged, because `gate`'s whole design is that a refusal arriving as an
error is what makes refusing a normal move in the conversation rather than an
abort. `agent._render_result` now recognises the two verdicts that are yours and
prints `← read_file denied at the prompt` in plain dim, keeping dim red for
errors that are actually errors. The tool name is passed in, as the report
asked and as the entry warned would be a signature change.

**"at the prompt" is doing a job.** `gate_and_dispatch` already prints
`auto-denied <tool>: <why>` when the jail refuses a call before you are asked,
and that one *is* an error and stays red. Two refusals a line apart needed to be
tellable apart, and "denied" alone does not do it.

**The producer/parser pair this could have created was closed instead of
tabulated**, which is the interesting half. `agent.py` reads a string
`commands.py` writes, in two modules — a matched literal at each end and a
seventh row in `HANDOVER.md`'s table. But `agent.py` already imports from
`commands.py` and nothing imports back, so the strings became `commands.DENIED`
and `commands.SKIPPED` and there is nothing left to drift. The table's own first
rule is *keep producer and parser in the same module where the dependency graph
allows*; this is the first time that rule has been the reason a row was **not**
added. `HANDOVER.md` says so at the table, because a pair that could have been
closed and was merely pinned is one that drifts eventually.

**The guard's direction was the thing to get right, and it is the inverse of
the report.** A real tool error styled as a polite human decline reads as
something you chose, so a run that should have stopped keeps going and looks
fine doing it. The match is against the two constants and nothing else — no
prefix test, no "looks like a verdict" heuristic. `tests/test_agent.py` pins
both directions and runs the real `gate_and_dispatch` into the real renderer
for both verdicts, with no literal in between. Verified by breaking it two ways:
reverting the render fails the two denial assertions, widening the match to a
default fails the two error assertions. The entry as it stood:

---

## B-0.9.1-01 · Denying a tool call is reported as an error

**Found:** 2026-07-27, Cas's v0.9.1 playtest. The report, verbatim:

```
─ Tool call  list_dir                          path: ~/projects/cfc
[a]llow  [d]eny  [A]llow all this turn  [s]kip
d
  ← error: user denied
```

*Suggestion: print "Tool call list_dir cancelled by user".*

**Diagnosis: one string with two audiences, and it is right for the other
one.** `commands.gate_and_dispatch` returns `{"error": "user denied"}`, and that
JSON is the **tool result sent to the model**. It has to be an error there —
`gate`'s docstring is explicit that reading a denial as data is the whole point,
so that refusing is a normal move in the conversation rather than an abort. Both
`tests/test_gate.py` and `tests/test_agent.py` pin the string.

What puts it on screen is `agent._render_result`, which unwraps any
`{"error": …}` and prints it in dim red. The console is echoing the model's
payload. So the word is correct for its reader and wrong for the one watching.

**Fix at the render, not at the payload.** `_render_result` should special-case
the two verdicts that are the human's own (`user denied`, `user skipped`) and
say so in a neutral style rather than dim red. The JSON is untouched, nothing
the model receives changes, and both existing tests still pass. Changing the
payload instead would be the reported location taken at face value — it would
also quietly tell the model that a refusal was a system fault, which is the one
thing the gate's design says it must not do.

**Where the tool name comes from:** `_render_result` receives only the result
string, so printing `list_dir` by name (as the report asks) means passing the
call's name in, not parsing it back out. Worth doing — a batch of calls renders
several of these in a row and "cancelled" without a name is ambiguous — but it
is a signature change, so note it rather than discovering it mid-fix.

**Not a v0.9.1 blocker.** That version's entry claims nothing about the gate.

---

## ~~B-0.9.1-03 · The connection light tells the hub to type a command the hub won't take~~ — CLOSED (v1.0, 2026-07-29)

**Closed 2026-07-29**, v1.0 step 2, in one pass with `D-0.9.1-01` because both
were one decision about `ui.CONNECTION_STYLE` seen from two angles — which is
what the entry below asked for.

**Cas's call between the entry's two shapes: the advice names its own context.**
So the string is *"— /connect embedding in a chat"*, true at the hub, in the `h`
legend and inside a session alike, at the cost of three redundant words in the
one place they are not needed. The alternative — splitting *what is wrong* from
*what to do* and letting each caller render the second half — was rejected for
the reason the entry names: it puts three advice literals on the far side of the
`ui.py` boundary that standing decision 6 will not let close, which is a wider
pair than the one it started with.

**A third option was on the table and was not taken.** Cas's own report offered
it — *"OR the reverse, that the command worked"* — i.e. teach the hub to accept
`/connect embedding`. It loses on scope rather than on merit: v1.0's claim is
that everything cfc already says is true, and a new hub key is a new feature.
It also would not have removed the wording problem, only moved it: a hub key is
not the same string as an in-chat command, so the table would still have needed
to know where it was being rendered. Worth reopening if the hub ever grows
commands for another reason.

**Fixing the table found a fourth rendering nobody had counted.**
`commands.connect_status` (bare `/connect`) kept its own trailing line offering
`/connect embedding` for every state but `connected` — a fork of the table
written as prose, and it had already drifted the way a fork does: it offered the
command for `hosted`, four lines below a light saying *not cfc's to start* and
against a `preflight.ensure` that returns early without trying. Deleted rather
than corrected, because the table now carries the command in every state that
has one.

`tests/test_connection.py` gained the pin: any state naming a command must also
name a place to type it. Deliberately matched on *"chat"* and not on the exact
phrase — the finding is the missing context, not the three words supplying it,
and a test against the literal would be the producer/parser hazard rebuilt
inside the test that exists to prevent it. Verified by breaking it. The entry as
it stood:

---

## B-0.9.1-03 · The connection light tells the hub to type a command the hub won't take

**Found:** 2026-07-28, Cas's post-tag v0.9.1 playtest. The report, verbatim:

```
saw:      ● LM Studio is not running — /connect embedding, or start it yourself
expected: ● LM Studio is not running — /connect embedding inside a chat, or
          start it yourself   (OR the reverse, that the command worked)
```

Confirmed with Cas the same session: he was **at the hub**, not in a chat.

**Diagnosis: one string with three renderings, and it is right in one of
them.** The text lives once, in `ui.CONNECTION_STYLE`, whose own comment states
the rule it is written to — *"the wording says what to **do**, not what is
wrong"*. It is rendered by `hub.print_connection` (the light above the picker),
by `hub.print_hub_help`'s legend, and by `commands.connect_status` (`/connect`
inside a session). Only the third is somewhere `/connect embedding` can be
typed: `hub.pick_session` accepts `n`/`p`/`h`/`q` and a listed chat id, and
answers anything else with *"Type a chat ID, or one of…"*.

So the one screen whose job is to tell you what to do next names a command that
screen cannot accept, and it does so in the two renderings that are *most*
likely to be the first thing seen after launch.

**This is `B-0.9.1-01`'s shape, one level out** — a single string correct for
one audience and wrong for another, which is why the two belong in the same
pass. It is not the recurring producer/parser hazard: nothing has drifted, and
`tests/test_connection.py`'s round-trip is doing its job. The mapping is simply
blind to *where* it is rendered, because it never had to know.

**Where a fix goes, and the one thing it must not do.** Do not fork the table
per caller — that is three literals a refactor away from disagreeing, which is
the reason the mapping is centralised in the first place. Two shapes survive
that:

- The advice clause names its context (`/connect embedding, inside a chat`),
  which is true everywhere including inside a chat, at the cost of a few words
  where they are not needed.
- Or `CONNECTION_STYLE` splits *what is wrong* from *what to do*, and each
  caller renders the second half in its own words. More faithful, more code,
  and it widens a producer/parser pair across the `ui.py` boundary — see
  `D-0.9.1-01`, which is already open against the same table and should be
  decided with this one.

**Not a v0.9.1 blocker** — the tag was already cut when this was found, and
that version's entry claims nothing about where the light is legible.

---

## ~~B-0.9.1-04 · The routines light applies a daily rule to every trigger kind~~ — CLOSED (v0.9.2, 2026-07-28)

**Closed 2026-07-28.** `hub._freshness` stopped deciding anything for itself and
now renders `schedule.why_not_due()` — standing decision 16, applied one panel
up the screen from the connection light. Cas's call between the entry's two
options: the colour means *is this routine due*, not *how long ago it ran*.

**Measured on the live routine folder before and after, and the entry
understated it.** Five of six rows were saying something untrue, not one:
`medium-term-memory` (`weekly 0330`) had absorbed its week on schedule and read
**orange**; `note-reader` and `note-writer` (`command`) read **orange** for
routines that can never be owed a run at all; `long-term-memory` and
`reflection` read green for the same non-reason. Only `short-term-memory`, the
one daily job, was accidentally right.

**What the same function buys that no threshold could:** if the OS tick stops
firing, every scheduled routine goes orange and stays orange.

Red left the column; dim now means *cannot be owed a run*, which puts
`trigger: command` and a malformed trigger in one cell — recorded against
`D-10`. The entry as it stood:

---

## B-0.9.1-04 · The routines light applies a daily rule to every trigger kind

**Found:** 2026-07-28, Cas's post-tag v0.9.1 playtest. The report, verbatim:

```
where:    routines overview
saw:      orange light because the weekly schedule happened >24h ago
expected: green light, last routine happened and there were no issue
guess:    working as designed, not as intended.
```

**The guess is right, and it is datable.** `hub._freshness` colours green under
24h, orange to 48h, red past that — the v0.4 spec of 2026-07-21, written when a
routine was daily or on command and nothing else existed. **`trigger: weekly
HHMM` landed 2026-07-24** (`f58d1af`) and nothing revisited the light. The
column has been wrong about weekly routines since the day weeklies shipped.

**It is wider than the case that was reported.** Of the six routines on Cas's
machine, one is `0300`, one is `weekly 0330`, and **four are `command`**. A
command routine cannot be overdue — it runs when a human asks — yet it goes
orange after a day and red after two exactly like a nightly job that has
stopped firing. So the rule is correct for one routine in six, and the
reported weekly case is the *quietest* of the wrong ones: `medium term memory`
absorbed the week of 20–26 July on schedule and will show red for five days out
of every seven.

**What is actually wrong is that the light forms an opinion.** Standing
decision 16 says the connection light renders `preflight.connection_state()`
and never decides for itself, because a light that decides can disagree with
the thing it describes. The routine column is the same screen doing the
opposite: `schedule.why_not_due()` already answers "is this routine due",
including weekly absorption, the never-run case and the retry rules — and
`hub._routine_rows` has the `Routine` in hand and passes `_freshness` a bare
timestamp. The failure direction is the friendly one (red over a healthy
routine, not green over a dead server), which is why it survived: it cries
wolf rather than reassuring, and nobody checks a light that is merely gloomy.

**One thing must be decided before it is fixed, not during.** *Does the colour
mean "how long ago" or "is this overdue"?* Today it means the first and is read
as the second, and every plausible fix picks one:

- Render `schedule.why_not_due()` the way the connection light renders
  `connection_state()`. Most faithful to decision 16, and it needs an answer
  for the window where a routine is legitimately due-and-not-yet-run — a `0300`
  job is "overdue" from 03:00 until the tick collects it.
- Or keep the staleness reading and scale the thresholds to the trigger — 24/48h
  daily, a week and a fortnight for weekly, **no staleness colour at all for
  `command`**, which is the case with no honest threshold.

The second is smaller and does not import `schedule` into `hub`. The first is
the one this codebase's own rule points at. Cheap either way; the cost of
guessing is a third reading of the same column.

**Not a v0.9.1 blocker, and it does not falsify v0.4 either** — that entry
promises *"green <24h, orange 24–48h, red >48h"* and that is precisely what the
code does. It is in this file rather than `BACKLOG.md` because the signal is
wrong about the thing it signals, which is Cas's call (2026-07-28) knowing it
gates v1.0.

## ~~B-0.9.1-02 · `config.example.py` documents twelve commands that no longer exist~~ — CLOSED (v0.9.2, 2026-07-28)

**Closed 2026-07-28.** Swept together with `D-0.9.1-02` over both config files,
as both entries asked. Every command in the shipped example now parses to a
**canonical** verb, checked by running each one through `parse.parse` rather
than by reading.

**The entry's count was right and its grouping was one out.** The draft split
the twelve into eight that keep their word behind `/` and four aliases whose
canonical verb differs (`:tokens`→`/status`, `:updatedb`→`/update db`,
`:attach`→`/add`, `:outbox`→`/list outbox`). There are **five**: `models` is
`ALIASES["models"] = "list models"` (`parse.py`), so `:models` became
`/list models`, not `/models`. Writing `/models` would have been the exact
mistake the entry warns about one generation later — teaching the alias
instead of the command. Worth knowing that the alias table is the thing to
check, not intuition about which words feel like verbs.

**Two factual errors found in `config.py` while sweeping**, neither of them
about `:` — its tools comment said *"Read-only tools the model can request"*
while `write_file` has existed since v0.6 and its own `WRITE_ROOTS` is
populated, and the `(Until v0.6 …)` and `(set 2026-07-20)` asides went with
the trim. The entry as it stood:

---

## B-0.9.1-02 · `config.example.py` documents twelve commands that no longer exist

**Found:** 2026-07-28, reading around the report above rather than from use, so
there is no symptom — which is the reason it survived a `:`→`/` sweep and three
releases.

**Symptom, if anyone ever hits it:** the file a new user copies to `config.py`
and reads while filling in tells them to type `:tools on`, `:recall`,
`:updatedb`, `:remember`, `:attach`, `:routine`, `:outbox`, `:file <n>`,
`:wiki` and `:wiki diff journal`. Every one of those was retired at v0.8.

**Why it is worse than a stale comment.** Standing decision 13: an unrecognised
verb does not error, it **falls through to the model**. So someone following
their own config file gets an API call and a confidently wrong answer, not "no
such command" — the exact failure that decision was written about, arriving
through documentation instead of through a deleted table entry.

**Scope, measured rather than assumed.** `README.md` is clean. The remaining
`:`-prefixed residue across the tree is in docstrings and comments — `parse.py`
explaining why `:attached` had to be tested before `:attach`, `hub.py` on
`:list`, `commands.py` on `:status` — which is developer prose about history and
harms nobody. `config.example.py` is the only shipped file that instructs a
human. The likely reason it was missed is that `config.py` is gitignored and the
example went with it in whoever swept.

**One thing not to sweep**, and `HANDOVER.md` already carries the scar: the
persisted `[:remember …]` marker keeps its colon. It is a storage format, not
prose, and renaming it stops every existing marker row from parsing.

**Not a v0.9.1 blocker.** Nothing in that entry concerns config.

## ~~The plain-console Windows shortcut still bands the splash~~ — CLOSED, cfc's share shipped and was seen working (v0.9, 2026-07-27)

**Closed 2026-07-27, in the v0.9.1 bookkeeping.** cfc's share of this shipped in
v0.9 — `preflight.terminal_report()` — and this entry deliberately stayed open
until the warning had been *seen*, because closing a defect on unverified work
is the mistake this file exists to prevent. Cas launched from the bare `wsl.exe`
shortcut on 2026-07-27 and got exactly what it was built to say:

```
this terminal is not truecolor — the splash will band
COLORTERM=(unset) TERM=xterm-256color rich=256
```

So it closes as **audible rather than fixed**, and that distinction is the whole
entry. The remaining repair is gating `~/.bashrc`'s unconditional
`export COLORTERM=truecolor` on `WT_SESSION` — a personal dotfile, never this
repo's to encode, and the entry said so from the start. Turning a silent
degradation into a loud one was cfc's entire share, and it did that.

**The original report follows.**

**Found:** 2026-07-22, reported by Cas. Fixed for the Windows Terminal
shortcut (see `CHANGELOG.md`, 2026-07-26); this entry is the other one.

**Symptom:** `wsl.exe -d Ubuntu --cd ~ -- bash -lc "~/projects/cfc/launch.sh"`
(no Windows Terminal in front of it) draws the splash background at visibly
degraded colour depth. The Windows Terminal shortcut in `README.md` draws it
correctly.

**Why this one wasn't chased down:** `bash -lc` here is a login shell, so
`~/.bashrc`'s own unconditional `export COLORTERM=truecolor` (not part of this
repo) already fires — unlike the Windows Terminal shortcut, which needed
`launch.sh` to set it. So this shortcut's problem is plausibly the opposite
of that one: truecolor is being asserted onto a console that may not
genuinely support it (legacy conhost), producing the same banding symptom
from the other direction. Whether that's really conhost, or Windows 11's
default-terminal-host delegation silently substituting something else, was
never measured for this path.

**Not urgent:** the Windows Terminal shortcut is the documented entry path.
If this one gets revisited, the fix is almost certainly gating `~/.bashrc`'s
`COLORTERM` export on `WT_SESSION` the same way `launch.sh` now does — but
that's a personal dotfile change, not something to encode in this repo.

**cfc's share shipped in v0.9, and this entry stays open until it is seen
working.** `preflight.terminal_report()` now prints `COLORTERM`, `TERM` and
rich's `color_system` and says "this terminal is not truecolor — the splash will
band" when they don't add up. That is the whole of what this repo can do; the
remaining fix is a dotfile. **It has not been run from the bare `wsl.exe`
shortcut yet** — the acceptance test is launching from that shortcut and
checking the line appears — and closing a defect on unverified work is the
mistake this file exists to prevent. Close it when the warning has actually
fired there.

**The original reasoning, carried forward from the closed shortcuts entry:**
this is a silent degradation with a real cause and a real fix, which is the
shape `HANDOVER.md` says to make visible. `preflight.py` already runs on every
launch and v0.9 is rewiring it for the connection light — a "this terminal is
256-colour, the splash will band" line belongs there, added with that work
rather than beside it. And `launch.sh` must **not** force `COLORTERM=truecolor`
to make the symptom go away: conhost genuinely cannot render 24-bit escapes, so
claiming it can trades banding for garbage.

---

## ~~Cold-starting LM Studio from WSL~~ — FIXED and SETTLED (v0.9, 2026-07-27)

**Settled by Cas the same day, from a genuinely cold machine via the desktop
shortcut:** the red branch ran, `lms server start` brought LM Studio up, and the
probe came back green. The capability was never lost to anything but my own
early return, and restoring the attempt restored it.

**The lesson is the entry, not the fix.** I measured `lms server start` failing
after 62s from an interactive shell, plus two GUI launch methods doing nothing,
and wrote "LM Studio cannot be started from WSL" into `HANDOVER.md` under
*Rejected designs* — the section whose entire function is to stop the next
person trying. Three failures in one afternoon, about something that had been
observed working. Cas noticed the loss within the hour.

Still unexplained: why the direct invocation timed out when the launcher's does
not. It blocks nothing — the path a user takes is the one that works — and
`lms load -y <model>` from cold remains untried.

Original entry below.

## Cold-starting LM Studio from WSL: it used to work, and now it doesn't

**Found:** 2026-07-27, by Cas, testing v0.9's connection light. **A regression
introduced during v0.9 and partly undone the same day** — the entry stays open
because the underlying question is unanswered, not because the code is broken.

**Symptom:** the desktop shortcut used to bring LM Studio up when it wasn't
running. It no longer does. Cas has the handover from the `cmd` Claude Code
session that set the shortcuts up and will check what it actually did.

**What was measured** (2026-07-27, LM Studio genuinely quit), all three failing:

| attempt | result |
|---|---|
| `lms server start -p 1233 --bind 0.0.0.0` | 62s, then "Timed out waiting for LM Studio daemon to start" |
| `cmd.exe /c start "" "C:\Program Files\LM Studio\LM Studio.exe"` | returns 0 at once, nothing launches |
| direct exec of the `.exe` from WSL | no process, no output |

`lms server start --help` has no headless flag; the daemon it waits for appears
to exist only once the GUI has run.

**Why that measurement was not enough, and this is the lesson.** It was written
up as "LM Studio cannot be started from WSL" and put in `HANDOVER.md` under
*Rejected designs* — a note whose whole function is to stop the next person
trying. Three failures in one afternoon do not establish impossibility about
something that has been **observed working**. The claim has been demoted to
this entry.

**The untested candidate, and the likely mechanism.** The early v0.9 code
returned as soon as it saw "LM Studio not running", which removed a path the
old code reached by accident: when `lms` cannot contact a daemon,
`server_state` returns `(None, None)` rather than `(False, …)`, so the old
`ensure()` **skipped the server-start branch entirely** and fell through to
`lms load -y <model>` — a different command, with a 180s budget rather than 90s,
and the one thing never tried against a cold machine. `lms server start` may
never have been what worked.

**Current behaviour:** the early return is gone. Red attempts the same sequence
it always did, says it is trying and that it may not work, and finishes with the
instruction to start LM Studio by hand. So nothing is worse than before v0.9;
what is missing is the answer.

**To settle it:** quit LM Studio entirely, run `lms load -y
text-embedding-baai-bge-m3-568m` from WSL by hand, and watch whether the app
comes up. That is one command and it decides the whole question.

It is kept rather than deleted for one specific reason: `CHANGELOG.md` carries
every fix and its reasoning, but **not the original report**, and the symptom as
first written is frequently the valuable half — the `MAX_DISTANCE` entry in
`legacy/BACKLOG.md` is the case in point, where the report's wrong premise is
the finding.

**Nothing below is edited, and nothing below is current** — including the
"leave a struck-through stub" rule in the header, which this split replaced.
Read it for the trail behind a fix, not for what is broken.

---

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

An entry moves to CHANGELOG when it's fixed (leave a struck-through stub here
with the fix date, same as BACKLOG does, so the history stays readable).

Some entries in BACKLOG predate this file and are arguably bugs (the dangling
`session_id`, `write_file` and relative paths). They're left where they are for
now; migrate them if it ever matters which list they're on.

---

## ~~`/recall` and `/remember` hang for minutes when the embedding server is down~~ — FIXED (v0.8.2, 2026-07-26)

**Fixed:** connect and read are two timeouts now, not one — 5s and 60s — so a
dead server is found in **11.1s instead of ~240s** while a big import keeps the
patience it needs. A refused connection also stops being retried like a busy
one: 2 attempts rather than 4, because nothing listening on the port is a state
and asking again gets the same answer. And the spinner says something, via an
`on_retry` callback threaded through `search`/`recall` — a callback rather than
a print, because `embed.py` has no console and must not grow one. Pinned in
`tests/test_embed.py`, which pins the two timeouts **as a pair** so merging them
back into one number fails a test. See `CHANGELOG.md`.

Original report below.

**Found:** 2026-07-26, Cas's 0.8.1 testing pass (`00 inbox/0.8.1 testing.md`).

**Symptom:** with `EMBED_BASE` configured but LM Studio's server off, `/recall`
and `/remember` sit on a spinning `Recalling...` for minutes and then fail.
Reported as "the spinner keeps spinning", which is what an honest four-minute
wait looks like from the outside.

**Cause, read off the code rather than guessed.** `embed._post` retries
`_RETRIES = 4` times with `timeout=_TIMEOUT` (60s) and `time.sleep(2 ** attempt)`
between them. A single `timeout=` float sets httpx's *connect*, *read*, *write*
and *pool* timeouts to the same value, so a connection that hangs rather than
refuses costs the full 60s **per attempt** — 4×60s plus 1+2+4s of backoff, ~4
minutes, before `do_recall`'s `except Exception` prints `[recall failed]`.

**Two things are wrong, and they are different.** The *budget* is one: four
minutes is not a wait anybody sits through. The *shape* is the other: nothing is
printed between the first attempt and the last, so a wait that is working as
designed is indistinguishable from a hang. Both halves are the fix; raising the
timeout floor alone just makes it fail faster and still silently.

**Note the retry loop is not wrong for the case it was written for** — a busy or
rate-limited endpoint, where waiting longer genuinely helps. A refused
connection is a *state*, not a transient, and retrying it four times asks the
same question four times. The two cases are distinguishable at the exception.

**Not the fix:** caching preflight's launch-time verdict and refusing before the
call. `preflight.py` already knows at startup, but the server can come up
mid-session and a cached "down" would then be wrong in the silent direction.
v0.9 puts the live check behind one shared state function; until then the call
itself is the check.

Pairs with the entry below — the message that says "still trying" is only
honest if the interrupt it advertises works.

---

## ~~Ctrl-C during a recall crashes the app~~ — FIXED (v0.8.2, 2026-07-26)

**Fixed:** all three spinner sites catch `KeyboardInterrupt` explicitly and
return to the prompt — `/recall`, `/remember` and `/update db`. Swept rather
than fixed at the one site, as this entry asked. Verified with a real SIGINT
mid-call, not a raised exception.

**The remaining member of the class is the interrupt at the approval prompt**
(the provider-400 entry below), which is a different fix: there the damage is a
half-answered tool-call batch, not a lost process. Left where it is.

Original report below.

**Found:** 2026-07-26, Cas's 0.8.1 testing pass, while interrupting the wait above.

**Symptom:** Ctrl-C while `Recalling...` is on screen exits cfc rather than
cancelling the command and returning to the prompt.

**Cause is exact and one line.** `commands.do_recall` wraps the call in
`try/except Exception` (`commands.py:1010`). `KeyboardInterrupt` derives from
`BaseException`, **not** `Exception`, so it is not caught — it escapes the
`rich.Live` context and the session loop and takes the process with it.

**The class, not the incident:** this is the third time an interrupt at a
blocking point has done damage (see the provider-400 entry below, where Ctrl-C
at the approval prompt leaves a tool-call batch half-answered). An interrupt is a
normal way to leave a long operation and every blocking point owes it a clean
exit. Worth sweeping the other `except Exception` guards around long calls at the
same time rather than fixing this one site.

---

## The plain-console Windows shortcut still bands the splash

**Found:** 2026-07-22, reported by Cas. Fixed for the Windows Terminal
shortcut (see `CHANGELOG.md`, 2026-07-26); this entry is the other one.

**Symptom:** `wsl.exe -d Ubuntu --cd ~ -- bash -lc "~/projects/cfc/launch.sh"`
(no Windows Terminal in front of it) draws the splash background at visibly
degraded colour depth. The Windows Terminal shortcut in `README.md` draws it
correctly.

**Why this one wasn't chased down:** `bash -lc` here is a login shell, so
`~/.bashrc`'s own unconditional `export COLORTERM=truecolor` (not part of this
repo) already fires — unlike the Windows Terminal shortcut, which needed
`launch.sh` to set it. So this shortcut's problem is plausibly the opposite
of that one: truecolor is being asserted onto a console that may not
genuinely support it (legacy conhost), producing the same banding symptom
from the other direction. Whether that's really conhost, or Windows 11's
default-terminal-host delegation silently substituting something else, was
never measured for this path.

**Not urgent:** the Windows Terminal shortcut is the documented entry path.
If this one gets revisited, the fix is almost certainly gating `~/.bashrc`'s
`COLORTERM` export on `WT_SESSION` the same way `launch.sh` now does — but
that's a personal dotfile change, not something to encode in this repo.

---

## A provider 400 on tool turns, cause not yet established

**Found:** 2026-07-23, reported by Cas. Two candidate causes were fixed in v0.5
(see `CHANGELOG.md`). Whether either was *the* one is unproven, and this entry
exists so the next occurrence settles it instead of restarting the argument.

**Symptom:** while letting the model roam a tree of files, a turn comes back as
an HTTP 400. Reported variously as complaining about `max_tokens`, as a
tool-handling error, and as something that read like a content filter — while
the model was doing nothing more exotic than reading README files.

**Two theories are already weak, and one of them was mine:**

- **Context overflow is unlikely.** Cas's files were small. The turn's total
  tool output is bounded now regardless, which is worth having on its own
  merits, but it probably was not the cause.
- **A content filter is unlikely.** Ordinary README files, repeatedly.

**The theory that survives, and it is size-independent.** The trigger condition
Cas reports — *only* when the model opens several files in one turn — is
literally the multi-tool-call batch, and the orphaned-call bug fixed in v0.5 is
a batch-only phenomenon. With one call per assistant message you either get the
result or you don't; with a batch, anything that exits mid-batch leaves some
calls answered and some not, which the API rejects for the rest of the session.
The thing that exits mid-batch is **Ctrl-C at the approval prompt** — precisely
what a human does when the model starts opening files they did not ask for. So:
roam, interrupt, and every subsequent message 400s until the session is
reopened, which repairs it silently. That matches "*keep* getting 400s" better
than anything about size.

**It needs an interrupt somewhere to be the answer.** If it recurs on turns
where nothing was cancelled, it is not this.

**The suspect nothing has addressed yet.** `agent.py` normalises a missing
`content` to `""` on the assistant message carrying `tool_calls`. Some
OpenAI-compatible providers want that field null or absent rather than an empty
string, and reject the replay on the next call. Also size-independent, also
tool-turns-only, and cheap to test: send `None` instead and see if it stops.

**What to capture when it next fires.** The whole error line — the provider's
message is verbatim in it, and cfc's own request shape is appended:

```
[error] HTTP 400 from …: <provider's message> [cfc: call 3/25, 14 messages,
        ~9,100 tokens, 41,200 chars of tool output this turn, model …]
```

plus **whether anything was interrupted in that session**, and which model. A
low call number with a small token estimate means the conversation's *shape* is
being rejected, which after v0.5 would be a real finding rather than the known
bug. Note `api._error_detail` truncates the body at 800 characters; a message
cut off mid-sentence is that, not the provider being terse.

---

## ~~Both desktop shortcuts are broken, and it is one story~~ — HALF FIXED (2026-07-26)

**The Windows Terminal shortcut works.** Both halves were root-caused by
measurement rather than guessing; see `CHANGELOG.md`, 2026-07-26, and the
handover note in `00 inbox/CFC_Shortcuts_Handover.md` for the full trail.

- **Part 2, the `wt.exe` launch failure — FIXED.** It was a Windows Terminal
  profile collision, not a quoting problem as this entry originally claimed:
  `-p Ubuntu` does its own distro activation and collides with an explicit
  `wsl.exe -d Ubuntu` after `--`. Any non-WSL profile fixes it. Working target
  is in `README.md`.
- **Part 1, the splash banding — FIXED for this shortcut, and the diagnosis
  below was wrong about why.** It was never the console host: the shortcut execs
  `launch.sh` straight off its shebang, so `.bashrc` never runs and `COLORTERM`
  is unset even under Windows Terminal, which *is* truecolor. `launch.sh` now
  sets it when `WT_SESSION` is present.

**Still open:** the bare `wsl.exe` shortcut, which has the opposite problem and
is a dotfile question rather than a repo one. It is the entry at the top of this
file. The original text below is kept because its reasoning about the resample
is still correct, and its confident wrong guess about the console host is worth
seeing next to what turned out to be true.

### 1. `wsl.exe` directly → low-quality splash background

```
C:\Windows\System32\wsl.exe -d Ubuntu --cd ~ -- bash -lc "~/projects/cfc/launch.sh"
```

Opens, runs, and draws the splash with a visibly low-quality background. The
same build from an Ubuntu terminal draws the real one.

**Mechanism, and it is no longer a guess about which half is at fault.**
`wsl.exe` invoked with no terminal of its own gets the **legacy console host**
(conhost), which is not truecolor and does not set `COLORTERM`. Rich then falls
back to 256 colours — and `splash._resize` is a **box-average** resample whose
own docstring records the trade: averaging pushes colours outside the baked
40-colour palette, which is *"invisible on truecolor"*. On a 256-colour console
it is the opposite of invisible: neighbouring averaged pixels quantize onto the
same slot and the gradient bands. So the degradation is colour depth, not
terminal size, and it is caused by the resample being correct for the terminal
it was designed against.

**This means the fix is the shortcut, not `launch.sh` and not the renderer** —
the earlier note in this file guessed `launch.sh`, which was wrong. And
`launch.sh` must **not** force `COLORTERM=truecolor`: conhost genuinely cannot
render 24-bit escapes, so claiming it can trades banding for garbage. Launch in
Windows Terminal instead, which is what shortcut 2 was trying to do.

**Still a hypothesis until measured**, and the measurement is two minutes:
launch from the shortcut and print `COLORTERM`, `TERM` and
`rich.console.Console().color_system` before the splash draws. Compare against
the Ubuntu terminal. If `color_system` is `256` or `standard` there and
`truecolor` here, that is the cause.

### 2. `wt.exe` → `0x80070002`, file not found

```
C:\Users\disse\AppData\Local\Microsoft\WindowsApps\wt.exe -p Ubuntu wsl.exe -d Ubuntu --cd ~ -- bash -lc "~/projects/cfc/launch.sh"

[error 2147942402 (0x80070002) when launching `"wsl.exe -d Ubuntu --cd ~ -- bash -lc ~/projects/cfc/launch.sh"']
The system cannot find the file specified.
```

**Quoting, not cfc.** Note what the error quotes back: the *entire* remainder as
one string, with the inner quotes around `~/projects/cfc/launch.sh` **gone**.
Windows Terminal parses its own command line first — it strips those quotes and
hands the whole thing to CreateProcess as a single executable name, which of
course does not exist. `wt` needs `--` to stop parsing and treat what follows as
a command line (it also treats `;` as a command separator, which is worth
knowing before any argument grows one).

Two candidate forms, both untested from this side — no Windows shell here:

```
wt.exe -p Ubuntu -- wsl.exe -d Ubuntu --cd ~ -- bash -lc "~/projects/cfc/launch.sh"
wt.exe -p Ubuntu -- wsl.exe -d Ubuntu --cd ~ -- ~/projects/cfc/launch.sh
```

**Prefer the second.** It has no quotes left to lose, and `bash -lc` was never
needed: `launch.sh` is executable, carries a shebang, and its header says it
assumes nothing about the working directory or a login shell — which is exactly
so that it can be invoked bare.

**If shortcut 2 works, shortcut 1's splash problem is moot** rather than fixed:
Windows Terminal is truecolor, so the resample lands as designed. Worth saying
because it means the two entries close together or not at all — and worth
checking `color_system` from the fixed shortcut to confirm the mechanism above
rather than just observing that it looks better.

Related, for v0.9: this is a silent degradation with a real cause and a real
fix, which is the shape `HANDOVER.md` says to make visible. `preflight.py`
already runs on every launch and v0.9 is rewiring it for the traffic light —
a "this terminal is 256-colour, the splash will band" line belongs there, added
with that work rather than just before it.
