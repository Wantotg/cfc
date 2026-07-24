#!/usr/bin/env bash
# run-due.sh — what the OS scheduler runs, on a fixed tick.
#
# Windows Task Scheduler calls:
#
#     wsl.exe -d Ubuntu -- /home/<you>/projects/cfc/run-due.sh
#
# every N minutes. cfc then decides which routines are actually due from each
# routine's own `trigger:` field — see schedule.py. Setup is in README.md.
#
# Same shape as launch.sh and for the same reason: it lands here with an
# unpredictable working directory and a non-login shell, so it assumes nothing
# and finds the repo from its own location. What it does NOT share with
# launch.sh is anything interactive — no preflight prompt, no `read -p`, no
# window to hold open. Nobody is watching, so every path out of here has to be
# an exit code and a line in the log.
#
# **Everything below is logged to ~/.cfc/schedule.log.** With "run whether the
# user is logged on or not" (the README default) there is no console window to
# watch, so a failure *before* cfc's own per-routine logging — a vanished venv,
# a bad cd, a Python traceback, the embedder being down — would disappear with
# the window and leave a routine silently never running. This is the catch-all
# *beneath* runner.py's logging, which only covers runs that actually reach a
# routine. cfc's own stdout stays deliberately quiet on an idle tick; this log
# is the meta-layer, and a dated header per tick is the heartbeat that proves
# the scheduler is even firing — "it never ran" is the failure with no other
# trace.

set -u   # not -e: the exit code below is the report, and it is not always 0.

# --- scheduler-level logging, set up before anything that can fail ----------
#
# Placed first so the cd and venv checks below are captured too — those are
# exactly the "before cfc starts" failures the window used to swallow. Rotated
# by size in plain bash because logrotate is not present on a stock WSL: past
# ~1 MB (months, at a few lines per tick) the current log becomes .log.1 — one
# generation kept — and a fresh log starts, so it cannot grow without bound on
# a machine nobody is administering.
LOG_DIR="${HOME}/.cfc"
LOG="${LOG_DIR}/schedule.log"
mkdir -p "$LOG_DIR" 2>/dev/null
if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt 1048576 ]; then
    mv -f "$LOG" "${LOG}.1" 2>/dev/null || true
fi
exec >>"$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') run-due tick ==="

SCRIPT="${BASH_SOURCE[0]}"
while [ -L "$SCRIPT" ]; do SCRIPT="$(readlink -f "$SCRIPT")"; done
REPO="$(cd "$(dirname "$SCRIPT")" && pwd)"
cd "$REPO" || { echo "cfc: cannot enter $REPO" >&2; exit 1; }

if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    . .venv/bin/activate
else
    echo "cfc: no .venv in $REPO" >&2
    exit 1
fi

# The embedder is not required for a routine to run, but a routine that writes
# a page and cannot index it is exactly the silent half-failure preflight.py
# exists to make visible. It never blocks, and its output now genuinely lands
# in the log above rather than a discarded stdout.
python preflight.py

# exec inherits the redirected stdout/stderr, so cfc's own output joins the log
# and its exit code is what Task Scheduler sees.
exec python main.py --run-due "$@"
