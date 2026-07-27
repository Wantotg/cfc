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

## When an entry closes

**It moves to [`legacy/BUGS.md`](legacy/BUGS.md), whole, and leaves nothing
behind here.** This file holds open entries only.

That is a change of rule, made at the v0.9 archive split (2026-07-27). The old
rule left a struck-through stub with the fix date, which is why this file had
grown to 283 lines of which three entries were live and `BACKLOG.md` to 897 of
which five were. A file nobody can read is a file nobody checks.

Two things make the move safe rather than lossy, and both have to hold:

- **`CHANGELOG.md` is the index.** Every shipped fix is logged there in the same
  commit, so "was this ever fixed, and why that way" is answered without opening
  the archive.
- **The archive keeps the original report**, which `CHANGELOG.md` does not. The
  symptom as first written is frequently the valuable half — sometimes the
  report's *wrong* premise is the finding. That is what makes it an archive and
  not a delete.

---

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

**The theory that survived has since had its structural fix, and is spent.**
The trigger Cas reports — *only* when the model opens several files in one
turn — is literally the multi-tool-call batch, and the orphaned-call bug fixed
in v0.5 is a batch-only phenomenon. The thing that exits mid-batch is Ctrl-C at
the approval prompt, precisely what a human does when the model starts opening
files they did not ask for. **But `agent.py` now wraps the batch in a
`try/finally` that answers every call on every exit, interrupt included.** So
the interrupt path can no longer poison a session, and there is nothing left of
this theory to build. If it recurs on a turn where nothing was cancelled, that
falsifies it outright and is a genuinely new finding.

**The suspect nothing has addressed yet.** `agent.py` normalises a missing
`content` to `""` on the assistant message carrying `tool_calls`. Some
OpenAI-compatible providers want that field null or absent rather than an empty
string, and reject the replay on the next call. Also size-independent, also
tool-turns-only.

It is **not** a one-character change, and the next session should know that
going in: the normalised value is read three lines later by `save_message` and
again at the render. The fix keeps it for persistence and rendering while the
*API payload* omits the key — which means `history` and the request stop being
literally the same object on this path. `history` is what gets replayed, and
standing decision 2 lives there, so it wants a test.

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

**The absence-watch has started.** Cas play-tested v0.8.2 on 2026-07-27: every
previously reported issue fixed, nothing new, and no 400. That is one clean
pass, not a window — but it is the first datapoint, and it means the count
starts here rather than at the 0.9 tag.

**How this entry is allowed to close, decided 2026-07-27 rather than at the
gate.** Nothing identified remains to fix, so it cannot be closed by fixing it.
It closes one of three ways: the next occurrence's error line settles it; it
recurs on an uninterrupted turn and becomes a new finding; or it **is not
observed across the whole 0.9 → 1.0 window and closes on absence**. The third is
accepted. It is a weaker claim than "fixed", and v1.0's note has to say which
one happened rather than let an empty `BUGS.md` imply the stronger one.
