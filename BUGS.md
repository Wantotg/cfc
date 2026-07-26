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

An entry moves to CHANGELOG when it's fixed (leave a struck-through stub here
with the fix date, same as BACKLOG does, so the history stays readable).

Some entries in BACKLOG predate this file and are arguably bugs (the dangling
`session_id`, `write_file` and relative paths). They're left where they are for
now; migrate them if it ever matters which list they're on.

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

## Both desktop shortcuts are broken, and it is one story

**Found:** 2026-07-22 (the splash) and 2026-07-26 (the `wt.exe` error), both
flagged by Cas — the second in `00 inbox/testing 0.8`. Filed together on
2026-07-26 because they are the same problem seen twice: **the shortcut that
works launches in the wrong terminal, and the shortcut that uses the right
terminal doesn't launch.** Cas stopped using both shortly after they were added.

Neither is urgent — `launch.sh` from an Ubuntu terminal is fine — but this is
the *designed* entry path, and the one a non-Cas user would take.

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
