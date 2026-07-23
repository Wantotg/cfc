#!/usr/bin/env python3
"""
test_schedule.py — which routines are due, and when they are not.

    python3 tests/test_schedule.py

No API calls and no clock dependence: `now` is passed in, and the run log is
written by hand. That is the whole point — the scheduler's decisions are pure
functions of (routine file, run log, now), and a scheduler you can only test by
waiting until 03:00 is a scheduler nobody tests.

The properties worth the most here are the *negatives*: a job that fires twice,
or retries a permanent failure ninety times a day, costs real money while
nobody is watching.
"""
import datetime
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import routines
import schedule
from routines import Routine

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:220]}")


def at(day, hhmm):
    return datetime.datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H%M")


def log(rid, status, when):
    """One run log line, written the way routines.append_log writes it."""
    p = routines.log_path(rid)
    p.parent.mkdir(parents=True, exist_ok=True)
    head = "" if p.exists() else f"# Run log — {rid}\n\n"
    prev = p.read_text(encoding="utf-8") if p.exists() else ""
    ts = when.strftime("%Y-%m-%d %H:%M:%S")
    p.write_text(prev + head + f"- **{ts}** — {status} — detail\n",
                 encoding="utf-8")


def main():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "routines").mkdir()
    (tmp / "prompts").mkdir()
    (tmp / "logs").mkdir()
    (tmp / "prompts" / "task.md").write_text("do the thing\n")
    # Patch the three directory functions, not config — that is the single seam
    # every routines function goes through, and patching config would miss a
    # caller that read the value at import time. Same discipline as
    # test_routines.
    routines.routine_dir = lambda: tmp / "routines"
    routines.prompt_dir = lambda: tmp / "prompts"
    routines.log_dir = lambda: tmp / "logs"

    def make(rid, trigger="0300", on_failure="retry", enabled=True):
        return Routine(id=rid, name=rid, prompt="task.md", trigger=trigger,
                       on_failure=on_failure, enabled=enabled)

    print("--- trigger parsing ---")
    ok("HHMM is a time", schedule.parse_trigger("0300") ==
       datetime.time(3, 0))
    ok("'command' is not a time", schedule.parse_trigger("command") is None)
    ok("2400 is refused", schedule.parse_trigger("2400") is None)
    ok("0360 is refused", schedule.parse_trigger("0360") is None)
    ok("three digits are refused", schedule.parse_trigger("300") is None)
    ok("empty is refused", schedule.parse_trigger("") is None)

    print("\n--- the basic gate ---")
    r = make("never-run")
    ok("before its time, not due",
       schedule.why_not_due(r, at("2026-07-23", "0200")) is not None)
    ok("after its time and never run, due",
       schedule.why_not_due(r, at("2026-07-23", "0301")) is None)
    ok("exactly at its time, due",
       schedule.why_not_due(r, at("2026-07-23", "0300")) is None)

    ok("a 'command' routine is never due on a tick",
       schedule.why_not_due(make("c", trigger="command"),
                            at("2026-07-23", "2359")) is not None)
    ok("...and says so in the reason",
       "command" in schedule.why_not_due(make("c2", trigger="command"),
                                         at("2026-07-23", "1200")))
    ok("a disabled routine is never due",
       schedule.why_not_due(make("d", enabled=False),
                            at("2026-07-23", "0301")) == "disabled")
    ok("an unparseable trigger does not fire",
       schedule.why_not_due(make("bad", trigger="9999"),
                            at("2026-07-23", "0301")) is not None)

    print("\n--- it runs once a day, not once a tick ---")
    r = make("daily")
    log("daily", "ok", at("2026-07-23", "0300"))
    ok("already ran today: not due",
       schedule.why_not_due(r, at("2026-07-23", "0315")) is not None)
    ok("...still not due much later the same day",
       schedule.why_not_due(r, at("2026-07-23", "2300")) is not None)
    ok("due again tomorrow",
       schedule.why_not_due(r, at("2026-07-24", "0301")) is None)

    print("\n--- catch-up is same-day only ---")
    # The machine was off at 03:00 and came back at 10:00. The job should run,
    # once, late — not be skipped, and not fire once per missed day.
    r = make("caught-up")
    log("caught-up", "ok", at("2026-07-20", "0300"))
    ok("a run missed this morning still fires today",
       schedule.why_not_due(r, at("2026-07-23", "1000")) is None)
    log("caught-up", "ok", at("2026-07-23", "1000"))
    ok("...and having caught up, does not fire again",
       schedule.why_not_due(r, at("2026-07-23", "1015")) is not None)
    ok("three days off does not queue three runs",
       # the single catch-up above is the whole backlog: after it, nothing.
       schedule.why_not_due(r, at("2026-07-23", "2359")) is not None)

    print("\n--- on_failure ---")
    r = make("retrier", on_failure="retry")
    log("retrier", "failed", at("2026-07-23", "0300"))
    ok("a failed run with on_failure=retry is due again",
       schedule.why_not_due(r, at("2026-07-23", "0315")) is None)

    s = make("skipper", on_failure="skip")
    log("skipper", "failed", at("2026-07-23", "0300"))
    reason = schedule.why_not_due(s, at("2026-07-23", "0315"))
    ok("a failed run with on_failure=skip waits for tomorrow",
       reason is not None, reason)
    ok("...and the reason names the setting", "skip" in (reason or ""), reason)
    ok("...but it does run tomorrow",
       schedule.why_not_due(s, at("2026-07-24", "0301")) is None)

    print("\n--- the retry limit ---")
    # The failure this bound exists for: a routine failing for a permanent
    # reason, on a 15-minute tick, retrying until midnight at full API cost
    # with nobody watching.
    r = make("doomed", on_failure="retry")
    for i in range(schedule.MAX_RETRIES_PER_DAY):
        log("doomed", "failed", at("2026-07-23", "0300") +
            datetime.timedelta(minutes=15 * i))
    reason = schedule.why_not_due(r, at("2026-07-23", "0400"))
    ok("stops retrying after the daily limit", reason is not None, reason)
    ok("...and says how many times it failed",
       str(schedule.MAX_RETRIES_PER_DAY) in (reason or ""), reason)
    ok("a new day resets the count",
       schedule.why_not_due(r, at("2026-07-24", "0301")) is None)

    print("\n--- a corrupt log does not cause a run storm ---")
    # Reading an unparseable timestamp as "never run" would fire on every tick
    # for the rest of the day. Refusing is the safe direction.
    p = routines.log_path("corrupt")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# Run log — corrupt\n\n- **not a timestamp** — ok — x\n",
                 encoding="utf-8")
    reason = schedule.why_not_due(make("corrupt"), at("2026-07-23", "0301"))
    ok("an unreadable timestamp refuses to run", reason is not None, reason)
    ok("...and says why", "unreadable" in (reason or ""), reason)

    print("\n--- due_routines reads the folder ---")
    for f in (tmp / "routines").glob("*.md"):
        f.unlink()
    routines.save_routine(make("morning", trigger="0300"))
    routines.save_routine(make("evening", trigger="2100"))
    routines.save_routine(make("manual", trigger="command"))
    (tmp / "routines" / "broken.md").write_text("no frontmatter here\n")

    due, skipped = schedule.due_routines(at("2026-07-23", "0400"))
    ok("only the one whose time has passed is due",
       [r.id for r in due] == ["morning"], [r.id for r in due])
    names = {n for n, _ in skipped}
    ok("the others are reported, not dropped",
       {"evening", "manual"} <= names, names)
    ok("a malformed file is reported too", "broken.md" in names, names)
    ok("...with the parse error as its reason",
       any("does not parse" in why for n, why in skipped
           if n == "broken.md"), skipped)

    due, _ = schedule.due_routines(at("2026-07-23", "2200"))
    ok("both are due once both times have passed",
       sorted(r.id for r in due) == ["evening", "morning"],
       [r.id for r in due])

    print("\n--- the tick lock ---")
    import db as dbmod
    dbmod.DB_PATH = tmp / "chat.db"
    ok("the lock lives beside the database",
       schedule.lock_path().parent == tmp, schedule.lock_path())

    with schedule._Lock(schedule.lock_path()) as first:
        ok("the first holder gets the lock", first)
        with schedule._Lock(schedule.lock_path()) as second:
            ok("a second tick is refused while it is held", not second)
    with schedule._Lock(schedule.lock_path()) as third:
        ok("...and gets it once released", third)

    print("\n--- the cli ---")
    ok("no arguments is a usage error", schedule.cli([]) == 2)
    ok("--help is not", schedule.cli(["--help"]) == 0)
    ok("an unknown flag is a usage error", schedule.cli(["--nope"]) == 2)
    ok("--run-routine with no name is a usage error",
       schedule.cli(["--run-routine"]) == 2)
    ok("--run-routine with an unknown name is a usage error",
       schedule.cli(["--run-routine", "does-not-exist"]) == 2)
    ok("--due reports without running", schedule.cli(["--due"]) == 0)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
