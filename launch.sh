#!/usr/bin/env bash
# launch.sh — start cfc from a desktop/taskbar shortcut.
#
# The Windows shortcut runs `wsl.exe -d Ubuntu -- .../launch.sh`, which lands
# here with an unpredictable working directory (whatever Windows felt like) and
# a non-login shell. So this script assumes nothing: it finds the repo from its
# own location, activates the venv explicitly, and never relies on PATH holding
# anything but the basics.
#
# It exists mostly to run preflight.py — everything memory-shaped in cfc
# assumes LM Studio is up, and when it isn't, the symptom is recall quietly
# returning nothing rather than an error. See preflight.py.
#
# Setup instructions for the Windows side are in README.md.

set -u   # not -e: a failing preflight must not stop cfc from opening.

# A bare, non-login exec (the shortcut path) never sources .bashrc, so
# COLORTERM is unset even though the real terminal is Windows Terminal —
# rich then under-detects 256-color and splash._resize's box-average
# resample bands. WT_SESSION is set by Windows Terminal itself and survives
# through wsl.exe regardless of shell type, so it's a safe signal that the
# terminal really is truecolor-capable (unlike forcing this unconditionally,
# which would produce garbage on legacy conhost).
if [ -n "${WT_SESSION:-}" ] && [ -z "${COLORTERM:-}" ]; then
    export COLORTERM=truecolor
fi

# The repo is wherever this script lives, resolved through symlinks so the
# shortcut can point at a link in ~/bin if that's tidier.
SCRIPT="${BASH_SOURCE[0]}"
while [ -L "$SCRIPT" ]; do SCRIPT="$(readlink -f "$SCRIPT")"; done
REPO="$(cd "$(dirname "$SCRIPT")" && pwd)"
cd "$REPO" || { echo "cannot enter $REPO"; read -r -p "enter to close"; exit 1; }

if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    . .venv/bin/activate
else
    echo "no .venv in $REPO — run: python3 -m venv .venv && pip install -r requirements.txt"
    read -r -p "enter to close"
    exit 1
fi

python preflight.py

python main.py "$@"
rc=$?

# A shortcut-launched terminal closes the instant the process exits, taking
# the traceback with it. On a clean exit that's what you want; on a crash it
# means the one thing you needed to read is the one thing you can't. So the
# window is only held open when something actually went wrong.
if [ $rc -ne 0 ]; then
    echo
    echo "cfc exited with status $rc"
    read -r -p "enter to close"
fi
exit $rc
