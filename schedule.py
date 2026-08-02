# schedule.py — deciding which routines are due, and the headless entry point.
#
# The OS scheduler owns one entry, forever:
#
#     */15 * * * *   main.py --run-due
#
# and cfc works out what that means. The alternative — one OS entry per
# routine, firing `--run-routine <name>` at its own time — was rejected
# deliberately: it makes `trigger:` in the routine file decorative, so the real
# schedule lives outside the vault, in a second place, free to drift from the
# file that claims to hold it. "A routine is fully reconstructable from its
# file" is the invariant this module exists to preserve, and a new routine
# needs no change to the OS scheduler at all.
#
# Three properties are load-bearing:
#
#   1. **The run log is the only state.** There is no "last tick" file and no
#      DB table. Whether a routine already ran today is answered by reading the
#      log it already writes, because a scheduled run is a fresh process with
#      nothing to remember and a second source of truth is a second thing to
#      get out of step.
#   2. **Catch-up is same-day only.** A machine that was off at 03:00 runs the
#      job when it comes back, if it is still that day. It never replays three
#      days of missed runs at once — a backlog that fires all at the same time
#      is not the schedule anyone wrote down.
#   3. **The idle tick is silent and cheap.** It reads a few files and exits 0.
#      That path runs ninety-odd times a day and must not open the database,
#      write a backup, or print anything, or the log it writes to becomes the
#      noise you stop reading.
import datetime
import fcntl
import sys
from pathlib import Path

import routines
from routines import (RoutineError, last_settled, last_success,
                      list_routines, load_routine)
from ui import DISPLAY_NAME

# How many times a failing routine may be retried within one day.
#
# `on_failure: retry` means "try again on the next tick", and the next tick is
# fifteen minutes away — so a routine that fails for a *permanent* reason (a
# provider outage, a prompt file someone renamed) would otherwise run every
# quarter of an hour until midnight, at full API cost, unattended. That is the
# one failure this module could cause that is worse than not running at all.
# After this many failures today, it waits for tomorrow's trigger like a
# `skip` would.
MAX_RETRIES_PER_DAY = 3

_TS_FMT = "%Y-%m-%d %H:%M:%S"


def lock_path():
    """Where the tick's lock file lives — beside the database.

    Derived from `db.DB_PATH` rather than configured separately, so a test that
    redirects the database redirects this too. That is not a convenience: a
    lock file left pointing at the real `~/.cfc` while everything else is in a
    temp dir is a test that interferes with the machine it runs on.
    """
    import db
    return Path(db.DB_PATH).expanduser().parent / "scheduler.lock"


def parse_trigger(trigger):
    """`trigger:` as (kind, time). kind is 'daily' | 'weekly', or (None, None).

    'command' — the default — means "only when a human types /routine", and is
    the reason a tick can read every routine in the folder without running the
    ones that were never meant to be scheduled.

    'weekly HHMM' is not "Mondays at HHMM". See `_weekly_not_due`.
    """
    text = str(trigger or "").strip()
    kind = "daily"
    if text.lower().startswith("weekly"):
        kind, text = "weekly", text[len("weekly"):].strip()
    if len(text) != 4 or not text.isdigit():
        return None, None
    hh, mm = int(text[:2]), int(text[2:])
    if hh > 23 or mm > 59:
        return None, None
    return kind, datetime.time(hh, mm)


def _parse_ts(ts):
    try:
        return datetime.datetime.strptime(ts, _TS_FMT)
    except (TypeError, ValueError):
        return None


def _runs_today(routine_id, since):
    """(status, timestamp) for every logged run at or after `since`."""
    path = routines.log_path(routine_id)
    if not path.exists():
        return []
    out = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        m = routines._LOG_RE.match(line.strip())
        if not m:
            continue
        when = _parse_ts(m.group("ts"))
        if when is not None and when >= since:
            out.append((m.group("status"), when))
    return out


def _weekly_not_due(now, last):
    """Why a weekly routine has nothing owed yet, or None if it has.

    The rule is **not** "it is Monday". A weekly job is due when a completed
    calendar week exists that it has not yet absorbed:

        last_completed_week(today) > last_completed_week(last run)

    Two things this buys, and both were the point:

    - **Catch-up is free.** Miss Monday and it fires Tuesday, still absorbing
      the same week. A day-of-week check would simply skip it, and the missed
      week would then never be processed by anything — the silent kind of
      failure, since the file it feeds just quietly holds less.
    - **The cadence cannot drift.** Anchoring to the calendar rather than to
      "seven days since the last run" means a late run absorbs the week it was
      always going to absorb, instead of shifting every future week to a new
      day of the week and never shifting back.

    It is also indifferent to how much material the week holds. A week with
    three entries is still a finished week; "is there enough" is a judgement
    about content and belongs to the model, not to the scheduler.
    """
    owed_mon, owed_sun = routines.last_completed_week(now.date())
    had_mon, _ = routines.last_completed_week(last.date())
    if owed_mon <= had_mon:
        return (f"the week of {owed_mon:%d-%m} to {owed_sun:%d-%m} was already "
                f"absorbed on {last:%Y-%m-%d} — nothing new has completed")
    return None


class Assessment:
    """The one structured answer to "is this routine due, and why".

    `state` is a fixed, compact vocabulary — `due`, `settled`, `not yet`,
    `command`, `disabled`, `invalid`, `unreadable`, `held`, `retry limit` — a
    renderer switches on, never a prose match against `reason`. `due` is the
    fact a scheduler decides against; it is `True` for exactly one state,
    `due`. `reason` is the full sentence `why_not_due` used to return on its
    own, worth reading when a job you expected didn't fire — `None` only when
    `due` is `True`, since there is nothing to explain about "run it".

    A hub, a screen and `due_routines` all want a different *slice* of the
    same decision — a colour, a sentence, a bool — and before this each read
    its own thing off `why_not_due`'s prose or re-derived a piece of it (the
    hub's old `_freshness` re-ran `parse_trigger` itself). One function
    computes the whole assessment once; every consumer reads a field.
    """

    def __init__(self, state, due, reason=None):
        self.state = state
        self.due = due
        self.reason = reason

    def __repr__(self):
        return f"<Assessment {self.state} due={self.due}>"

    def __eq__(self, other):
        if not isinstance(other, Assessment):
            return NotImplemented
        return ((self.state, self.due, self.reason) ==
                (other.state, other.due, other.reason))


def assess(routine, now):
    """The full `Assessment` for this routine at `now`.

    Every branch is unchanged from the `why_not_due` this replaces as the
    real logic — same order, same conditions, same reason strings — so a
    caller of the compatibility view below sees no difference at all. What's
    new is that each branch also names its own compact `state`, most of them
    previously indistinguishable from one another once reduced to "not
    None": `held` (an `on_failure: skip` waiting for tomorrow) and `retry
    limit` (a retry budget spent on failures) used to both collapse into
    "not due", the same bucket as a routine that simply ran cleanly today —
    which is `W-0.9.2-02`: a routine that spent its whole retry budget on
    failures still read green on the hub, in the one column a person
    actually looks at first.
    """
    def not_due(state, reason):
        return Assessment(state, False, reason)

    def is_due():
        return Assessment("due", True, None)

    if not routine.enabled:
        return not_due("disabled", "disabled")

    kind, at = parse_trigger(routine.trigger)
    if at is None:
        if str(routine.trigger).strip() == "command":
            return not_due("command",
                           "trigger is 'command' — runs only from /routine")
        return not_due("invalid",
                       f"trigger {routine.trigger!r} is not 'command', HHMM "
                       f"or 'weekly HHMM'")

    today_at = datetime.datetime.combine(now.date(), at)
    if now < today_at:
        return not_due("not yet", f"not yet — due at {at.strftime('%H:%M')}")

    # `last_settled`, not `last_run`: a Ctrl-C cancellation absorbed nothing,
    # so due-ness looks past it to the latest `ok`/`failed` run — otherwise a
    # manual cancel today would make a due routine look done for the day.
    status, ts, _ = last_settled(routine.id)
    if status is None:
        return is_due()                   # never settled: due

    when = _parse_ts(ts)
    if when is None:
        # A log line we wrote and cannot read back. Refusing to run is the safe
        # direction: the alternative reads as "never run" and fires on every
        # tick for the rest of the day.
        return not_due("unreadable",
                       f"last run timestamp {ts!r} is unreadable — not running")

    if kind == "weekly":
        # Against the last *success*, not `when` — a failed run absorbed
        # nothing, and treating it as if it had would skip the week for good.
        success = last_success(routine.id)
        weekly = _weekly_not_due(now, success) if success else None
        if weekly:
            return not_due("settled", weekly)
        # A completed week is unabsorbed, so it is owed. Fall through to the
        # failure rules below — the retry bound applies to a weekly job for the
        # same reason it applies to a daily one.
        if status != "failed":
            return is_due()
    elif when < today_at:
        # Includes the machine having been off since before the trigger. Runs
        # once, late, today. Yesterday's missed run is not replayed.
        return is_due()

    if status != "failed":
        return not_due("settled", f"already ran today at {when.strftime('%H:%M')}")

    if routine.on_failure != "retry":
        return not_due("held",
                       f"failed at {when.strftime('%H:%M')} and on_failure is "
                       f"{routine.on_failure!r} — waiting for tomorrow")

    failures = [r for r in _runs_today(routine.id, today_at)
                if r[0] == "failed"]
    if len(failures) >= MAX_RETRIES_PER_DAY:
        return not_due("retry limit",
                       f"failed {len(failures)} times today, the retry limit — "
                       f"waiting for tomorrow")
    return is_due()


def why_not_due(routine, now):
    """Why this routine should not run at `now`, or None if it should.

    A **compatibility view over `assess()`** — every existing caller
    (`due_routines`, and formerly the hub and the routines screen) only ever
    tested this against `is None`, never against its wording, so that
    contract is kept exactly. `assess()` is where the state is actually
    decided now; this is a one-line projection of its `reason`.
    """
    return assess(routine, now).reason


def due_routines(now=None):
    """[(routine, None)] for what should run now, plus everything skipped.

    Returns (due, skipped) where skipped is [(routine_or_name, reason)], so a
    caller reporting "nothing ran" can say why for each one. Malformed files
    come back in `skipped` too rather than being dropped: a routine that
    stopped parsing is the one most likely to be the thing you are looking for.
    """
    now = now or datetime.datetime.now()
    good, bad = list_routines()
    due, skipped = [], [(name, f"does not parse: {err}") for name, err in bad]
    for r in good:
        reason = why_not_due(r, now)
        if reason is None:
            due.append(r)
        else:
            skipped.append((r.id, reason))
    return due, skipped


class _Lock:
    """A whole-tick lock, so two ticks can never run the same routine twice.

    `flock` rather than a lock file's existence: the kernel releases it when
    the process dies, so a run killed mid-turn does not leave a stale lock that
    silently stops every future tick. That failure would look exactly like the
    scheduler having been switched off.
    """

    def __init__(self, path):
        self.path = path
        self.fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.path, "w")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.fh.close()
            self.fh = None
            return False
        return True

    def __exit__(self, *exc):
        if self.fh is not None:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()
        return False


def _run(keys, model=None, verbose=True):
    """Run each routine in turn. Returns the number that failed.

    Everything the runner needs is opened here and not before: the idle tick —
    the overwhelmingly common case — must not pay for a database connection or
    a backup just to discover it has nothing to do.
    """
    from backup import safe_backup
    from db import db
    from runner import run_routine

    safe_backup()
    conn = db()
    failed = 0
    try:
        for key in keys:
            name = getattr(key, "id", key)
            print(f"[{datetime.datetime.now().strftime(_TS_FMT)}] {name}: "
                  f"starting")
            status, summary, _session_id, _run_number = run_routine(
                key, conn, model=model,
                on_event=(lambda m, n=name: print(f"  {n}: {m}"))
                if verbose else None)
            print(f"[{datetime.datetime.now().strftime(_TS_FMT)}] {name}: "
                  f"{'FAILED' if status == 'failed' else status} — {summary}")
            # `cancelled` has no human at the wheel on this path — a scheduled
            # tick has nobody to press Ctrl-C — but the exit code only ever
            # meant "did something fail", and cancelled isn't that.
            if status == "failed":
                failed += 1
    finally:
        conn.close()
    return failed


USAGE = f"""{DISPLAY_NAME} — headless entry points

  python main.py --run-due               run every routine whose trigger is due
  python main.py --run-routine <name>    run one routine now, due or not
  python main.py --due                   report what is due, run nothing
  python main.py [session_id]            the REPL

--run-due is what the OS scheduler calls, on a fixed tick. {DISPLAY_NAME}
decides what is due from each routine's own `trigger:` field and its run
log; the scheduler needs one entry and never needs changing when a routine
is added.

Exit codes: 0 nothing to do or everything succeeded, 1 a run failed,
2 the arguments were wrong."""


def cli(argv):
    """The `--`-flag entry point. Returns a process exit code.

    Deliberately separate from `repl()`: this path has no human, no terminal to
    assume, and no splash. It is the same shape as `runner.run_routine` being
    the headless entry point for one routine — this is the headless entry point
    for the schedule.
    """
    if not argv or argv[0] in ("-h", "--help"):
        print(USAGE)
        return 0 if argv else 2

    flag = argv[0]

    if flag == "--due":
        due, skipped = due_routines()
        for r in due:
            print(f"due     {r.id} ({r.trigger})")
        for name, reason in skipped:
            print(f"        {name}: {reason}")
        if not due:
            print("nothing due")
        return 0

    if flag == "--run-routine":
        if len(argv) < 2:
            print("usage: main.py --run-routine <name>", file=sys.stderr)
            return 2
        key = " ".join(argv[1:])
        try:
            routine = load_routine(key)
        except RoutineError as e:
            print(str(e), file=sys.stderr)
            return 2
        with _Lock(lock_path()) as held:
            if not held:
                print(f"another {DISPLAY_NAME} run is in progress — "
                      f"skipping", file=sys.stderr)
                return 1
            return 1 if _run([routine]) else 0

    if flag == "--run-due":
        with _Lock(lock_path()) as held:
            if not held:
                # Not an error. A previous tick is still working, which is the
                # normal state of affairs for a routine that takes longer than
                # the interval, and the log should not fill with alarm about it.
                return 0
            due, _ = due_routines()
            if not due:
                return 0          # the silent, common case
            return 1 if _run(due) else 0

    print(f"unknown option {flag!r}\n\n{USAGE}", file=sys.stderr)
    return 2
