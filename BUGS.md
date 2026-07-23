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

## The desktop shortcut renders a low-quality splash background

**Found:** 2026-07-22, flagged by Cas.

Launching cfc from the **desktop shortcut** shows the splash with a visibly
low-quality background image. Launching the *same build* from an Ubuntu terminal
(`launch.sh`, or `python main.py`) shows the real, high-quality one. So the app
works and is reachable — it just doesn't look right on its *designed* entry
path, which is the one a non-Cas user would take.

Not diagnosed yet. Leading hypothesis, from how the splash is drawn: the art is
truecolor box-average resampling sized to the terminal at render time
(`splash.py`), and it needs both truecolor and the terminal's real dimensions.
A shortcut-spawned terminal that reports a smaller size, or that falls back to
256-colour because `COLORTERM`/`TERM` aren't set the way an interactive login
shell sets them, would degrade the image in exactly this way while the
interactive terminal looks fine.

Where to look:
- `launch.sh` — what terminal the shortcut spawns, and whether it inherits
  `COLORTERM=truecolor` / a sane `TERM`. An interactive login shell sets these;
  a bare shortcut invocation may not.
- `splash.py` — the resampling path and how it reads terminal size and colour
  depth. Confirm it's degrading gracefully rather than mis-detecting.

Cheap to confirm: launch from the shortcut and print `COLORTERM`, `TERM` and the
detected `console.size` before the splash draws; compare to the Ubuntu-terminal
values. If truecolor or the size differs, that's the cause and the fix is in
`launch.sh`, not the renderer.

Not urgent — the app opens and runs; only the launch screen looks wrong.
