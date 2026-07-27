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
