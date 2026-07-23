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
# launch.sh is anything interactive — no preflight, no `read -p`, no window to
# hold open. Nobody is watching, so every path out of here has to be an exit
# code and a line on stdout.
#
# Deliberately silent when there is nothing to do: this runs ninety-odd times a
# day, and a scheduler log full of "nothing due" is a log nobody reads.

set -u   # not -e: the exit code below is the report, and it is not always 0.

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
# exists to make visible. It never blocks, and its output goes to the same log.
python preflight.py

exec python main.py --run-due "$@"
