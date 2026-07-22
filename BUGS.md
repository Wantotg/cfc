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
