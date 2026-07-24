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
from routines import (RoutineError, last_run, last_success, list_routines,
                      load_routine)

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

    'command' — the default — means "only when a human types :routine", and is
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


def why_not_due(routine, now):
    """Why this routine should not run at `now`, or None if it should.

    Returns the *reason* rather than a bool because every one of these is worth
    reading when a job you expected didn't fire, and "not due" alone sends you
    to the code to find out which of six rules applied.
    """
    if not routine.enabled:
        return "disabled"

    kind, at = parse_trigger(routine.trigger)
    if at is None:
        if str(routine.trigger).strip() == "command":
            return "trigger is 'command' — runs only from :routine"
        return (f"trigger {routine.trigger!r} is not 'command', HHMM or "
                f"'weekly HHMM'")

    today_at = datetime.datetime.combine(now.date(), at)
    if now < today_at:
        return f"not yet — due at {at.strftime('%H:%M')}"

    status, ts, _ = last_run(routine.id)
    if status is None:
        return None                       # never run: due

    when = _parse_ts(ts)
    if when is None:
        # A log line we wrote and cannot read back. Refusing to run is the safe
        # direction: the alternative reads as "never run" and fires on every
        # tick for the rest of the day.
        return f"last run timestamp {ts!r} is unreadable — not running"

    if kind == "weekly":
        # Against the last *success*, not `when` — a failed run absorbed
        # nothing, and treating it as if it had would skip the week for good.
        success = last_success(routine.id)
        weekly = _weekly_not_due(now, success) if success else None
        if weekly:
            return weekly
        # A completed week is unabsorbed, so it is owed. Fall through to the
        # failure rules below — the retry bound applies to a weekly job for the
        # same reason it applies to a daily one.
        if status != "failed":
            return None
    elif when < today_at:
        # Includes the machine having been off since before the trigger. Runs
        # once, late, today. Yesterday's missed run is not replayed.
        return None

    if status != "failed":
        return f"already ran today at {when.strftime('%H:%M')}"

    if routine.on_failure != "retry":
        return (f"failed at {when.strftime('%H:%M')} and on_failure is "
                f"{routine.on_failure!r} — waiting for tomorrow")

    failures = [r for r in _runs_today(routine.id, today_at)
                if r[0] == "failed"]
    if len(failures) >= MAX_RETRIES_PER_DAY:
        return (f"failed {len(failures)} times today, the retry limit — "
                f"waiting for tomorrow")
    return None


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
            ok, summary, session_id = run_routine(
                key, conn, model=model,
                on_event=(lambda m, n=name: print(f"  {n}: {m}"))
                if verbose else None)
            print(f"[{datetime.datetime.now().strftime(_TS_FMT)}] {name}: "
                  f"{'ok' if ok else 'FAILED'} — {summary}")
            if not ok:
                failed += 1
    finally:
        conn.close()
    return failed


USAGE = """cfc — headless entry points

  python main.py --run-due               run every routine whose trigger is due
  python main.py --run-routine <name>    run one routine now, due or not
  python main.py --due                   report what is due, run nothing
  python main.py [session_id]            the REPL

--run-due is what the OS scheduler calls, on a fixed tick. cfc decides what is
due from each routine's own `trigger:` field and its run log; the scheduler
needs one entry and never needs changing when a routine is added.

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
                print("another cfc run is in progress — skipping",
                      file=sys.stderr)
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
