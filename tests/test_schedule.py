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
    ok("HHMM is a daily time", schedule.parse_trigger("0300") ==
       ("daily", datetime.time(3, 0)))
    ok("'weekly HHMM' is a weekly time", schedule.parse_trigger("weekly 0300")
       == ("weekly", datetime.time(3, 0)))
    ok("'command' is not a time",
       schedule.parse_trigger("command") == (None, None))
    ok("2400 is refused", schedule.parse_trigger("2400") == (None, None))
    ok("0360 is refused", schedule.parse_trigger("0360") == (None, None))
    ok("three digits are refused",
       schedule.parse_trigger("300") == (None, None))
    ok("empty is refused", schedule.parse_trigger("") == (None, None))
    ok("'weekly' with no time is refused",
       schedule.parse_trigger("weekly") == (None, None))

    print("\n--- calendar weeks ---")
    # A week is complete only once its Sunday is past: on Sunday the 26th the
    # week 20-26 is still running. Getting this off by one day would make a
    # weekly job absorb a week that hasn't finished.
    import routines as _r
    ok("on Monday 27th, the last complete week is 20-26",
       _r.last_completed_week(datetime.date(2026, 7, 27)) ==
       (datetime.date(2026, 7, 20), datetime.date(2026, 7, 26)),
       _r.last_completed_week(datetime.date(2026, 7, 27)))
    ok("on Sunday 26th, it is still 13-19",
       _r.last_completed_week(datetime.date(2026, 7, 26)) ==
       (datetime.date(2026, 7, 13), datetime.date(2026, 7, 19)),
       _r.last_completed_week(datetime.date(2026, 7, 26)))
    ok("mid-week gives the same answer as its Monday",
       _r.last_completed_week(datetime.date(2026, 7, 29)) ==
       _r.last_completed_week(datetime.date(2026, 7, 27)))

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

    print("\n--- weekly: due when a completed week is unabsorbed ---")
    # The rule is NOT "it is Monday". These assertions are the difference:
    # a day-of-week check passes the first two and fails the third, and the
    # third is the one that matters — a missed Monday must not mean the week
    # is never absorbed by anything.
    wk = make("weekly-mt", trigger="weekly 0300")

    log("weekly-mt", "ok", at("2026-07-20", "0305"))   # absorbed 13-19
    ok("mid-week with nothing newly completed, not due",
       schedule.why_not_due(wk, at("2026-07-24", "0301")) is not None)
    ok("...and the reason names the week it already absorbed",
       "13-07" in (schedule.why_not_due(wk, at("2026-07-24", "0301")) or ""),
       schedule.why_not_due(wk, at("2026-07-24", "0301")))
    ok("on Sunday the running week is still not owed",
       schedule.why_not_due(wk, at("2026-07-26", "0301")) is not None)
    ok("on Monday, the week that just ended is owed",
       schedule.why_not_due(wk, at("2026-07-27", "0301")) is None,
       schedule.why_not_due(wk, at("2026-07-27", "0301")))
    ok("before the trigger time on that Monday, not yet",
       schedule.why_not_due(wk, at("2026-07-27", "0259")) is not None)

    # The catch-up case: Monday and Tuesday missed entirely. A day-of-week
    # scheduler skips the week; this one still owes it.
    ok("a missed Monday is still owed on Wednesday",
       schedule.why_not_due(wk, at("2026-07-29", "0301")) is None,
       schedule.why_not_due(wk, at("2026-07-29", "0301")))

    # And once it does run, late, it goes quiet again for that week rather
    # than firing on every remaining tick.
    log("weekly-mt", "ok", at("2026-07-29", "0305"))
    ok("having run late, it is quiet for the rest of the week",
       schedule.why_not_due(wk, at("2026-07-31", "0301")) is not None,
       schedule.why_not_due(wk, at("2026-07-31", "0301")))
    ok("...and owed again once the next week completes",
       schedule.why_not_due(wk, at("2026-08-03", "0301")) is None,
       schedule.why_not_due(wk, at("2026-08-03", "0301")))

    # The cadence must not walk forward because a run was late: absorbing
    # 20-26 on Wednesday the 29th still leaves 27-02 owed on Monday the 3rd,
    # not on the following Wednesday.
    ok("a late run does not shift the cadence",
       schedule.why_not_due(wk, at("2026-08-03", "0301")) is None)

    print("\n--- weekly: never run, and the retry bound still applies ---")
    fresh_wk = make("weekly-fresh", trigger="weekly 0300")
    ok("a weekly routine that never ran is due",
       schedule.why_not_due(fresh_wk, at("2026-07-24", "0301")) is None)
    fail_wk = make("weekly-fail", trigger="weekly 0300")
    for h in ("0305", "0320", "0335"):
        log("weekly-fail", "failed", at("2026-07-27", h))
    reason = schedule.why_not_due(fail_wk, at("2026-07-27", "0350"))
    ok("a weekly routine respects the daily retry limit",
       reason is not None and "retry limit" in reason, reason)

    # A failed run absorbed nothing. Keying "have I done this week" off the
    # latest run of any kind — the first version of this — marked the week done
    # on a failure and skipped it permanently: ST would later drop that week's
    # entries with nothing having condensed them, and no signal anywhere.
    absorb = make("weekly-absorb", trigger="weekly 0300")
    log("weekly-absorb", "failed", at("2026-07-27", "0305"))
    ok("a failed run does not count as absorbing the week",
       schedule.why_not_due(absorb, at("2026-07-28", "0301")) is None,
       schedule.why_not_due(absorb, at("2026-07-28", "0301")))
    log("weekly-absorb", "ok", at("2026-07-28", "0305"))
    ok("...but the success that follows it does",
       schedule.why_not_due(absorb, at("2026-07-29", "0301")) is not None)
    # 'ok (review)' is a completed run whose *result* wants a glance. The file
    # was written, so re-running would condense the same week twice.
    review = make("weekly-review", trigger="weekly 0300")
    log("weekly-review", "ok (review)", at("2026-07-27", "0305"))
    ok("a reviewed run still counts as absorbed",
       schedule.why_not_due(review, at("2026-07-29", "0301")) is not None,
       schedule.why_not_due(review, at("2026-07-29", "0301")))

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
