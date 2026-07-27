# errorlog.py — a durable record of provider errors, for a bug that only
# reproduces by waiting.
#
# `BUGS.md`'s surviving entry — a provider 400 on tool turns — has no
# reproduction. It closes when the next occurrence's error line settles it, or
# on absence across the 0.9 → 1.0 window. Both of those need the error line to
# still exist when someone comes looking, and until now **the only place it
# existed was the scrollback** — on a tool turn, which is the kind that fills a
# screen. One long turn later the evidence was gone. An absence-watch whose
# evidence depends on a human noticing in real time is not a watch.
#
# Four properties, each of which is the whole point of a line of code below:
#
#   1. **It never raises.** A logging failure that broke a turn would be a
#      worse bug than the one it exists to catch. Every public function here
#      swallows everything, and returns False rather than saying so loudly.
#
#   2. **It imports no cfc module.** Same reason `ui.py` doesn't: this is
#      called from inside exception handlers, and a logger that can fail to
#      import is one that fails exactly when it is needed. It takes what it
#      needs as arguments.
#
#   3. **Nothing from a private chat reaches it.** This is a *fourth* path out
#      of a private session — invariant 10 in `HANDOVER.md` names three
#      (auto-embed, auto-export, model file-writes) and this one opens a file
#      by path, so it escapes the in-memory connection the same way they do.
#      `agent._request_shape`'s rider would be harmless, but `api._error_detail`
#      carries up to 800 characters of the *provider's body*, and providers do
#      echo request fragments back inside a 400. That is the one thing a private
#      chat promises never reaches disk. Cas's call (2026-07-27): log nothing
#      from a private chat. The refusal is here, at the write, and not at the
#      call sites — a caller that forgets is the failure this file exists to
#      make impossible. `tests/test_private.py` holds the negative.
#
#   4. **A launch writes a line.** Without it, "the log is empty" and "cfc has
#      never successfully written to the log" are the same artefact — which is
#      this project's signature failure shape aimed directly at the mechanism
#      built to catch it. With it, an empty file means *never written*, which is
#      a different and audible fact from *no errors*, and the last line always
#      says when cfc last ran.
#
# **Nothing parses this file.** It is written here and read by a human, and that
# is deliberate: `HANDOVER.md`'s recurring hazard is a producer here and a
# parser somewhere else, and the way to not add a seventh row to that table is
# to not create the pair. If something ever needs to *read* this log, it gets a
# reader in this module, beside the writer.
#
# No rotation. Errors are rare by construction and a launch line is one line a
# day; a year of ordinary use is a few hundred lines. Rotation would be a second
# mechanism guarding against a size this file cannot reach.
import datetime
from pathlib import Path

# Beside the db and the backups, not in the vault. This is diagnostic output
# about cfc, not content — the vault is for things you would miss.
LOG_PATH = Path.home() / ".cfc" / "errors.log"

# Local naive, like everything outside `db.py` (see HANDOVER, "Two time bases").
# A log you read next to a terminal you were sitting at wants the clock on the
# wall, and there is no offset here to convert later.
_STAMP = "%Y-%m-%d %H:%M:%S"


def _write(line):
    """Append one line. Returns True if it landed. Raises nothing, ever."""
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        return True
    except Exception:      # noqa: BLE001 — see property 1 in the header
        return False


def _now():
    return datetime.datetime.now().strftime(_STAMP)


def log_launch():
    """One line per launch, so an empty log means 'never written'."""
    return _write(f"{_now()}  launch   cfc started")


def log_error(err, *, session_id=None, model=None, interrupted=0,
              private=False, where="chat"):
    """Record a provider error. Returns True if it was written.

    `err` is the exception (or any object): its `str()` is the whole error
    line, which on the tool path already carries `agent._request_shape`'s
    rider. It is written verbatim and not summarised — the entry in `BUGS.md`
    asks for the provider's own words, and a summariser is a thing that can be
    wrong about the one message nobody has seen yet.

    `interrupted` is the count of turns cancelled in this session so far, which
    `BUGS.md` asks for and nothing tracked before. It is a count rather than a
    flag because 'was anything interrupted' and 'how much' are the same cost to
    record and not the same finding.

    A private chat writes nothing and reports False — see property 3.
    """
    if private:
        return False
    head = f"{_now()}  error    " + " · ".join(str(x) for x in (
        f"session {session_id}" if session_id is not None else "no session",
        f"model {model}" if model else "model unknown",
        f"{interrupted} turn(s) interrupted this session"
        if interrupted else "nothing interrupted this session",
        where,
    ))
    # The error line is indented onto its own line rather than appended: it can
    # be 800 characters of provider body plus the shape rider, and a header you
    # can scan is worth more than a single greppable line here — there is no
    # parser to keep happy.
    return _write(head + "\n    " + str(err).replace("\n", "\n    "))
