#!/usr/bin/env python3
"""
test_hub.py — the v0.4 screens: what the picker shows, and in what colour.

    python3 tests/test_hub.py

Four properties, each one a thing that fails quietly rather than loudly:


**The picker hides routine runs and wiki pages; `:list` does not.** Seven of
twenty hub rows were routine transcripts and the wiki was about to take the
rest. But hiding is the dangerous direction — so the filter is a *deny list*,
and an unrecognised provider must still show up as a chat. A conversation that
silently stops appearing in the picker is indistinguishable from one that was
deleted.

**Colour thresholds come from one place.** The bar, the hub's Ctx column and
the post-turn nudge all read `ui.context_style`. They were three separate
literals away from disagreeing about whether a session is nearly full.

**Freshness buckets.** A routine's last run drives a traffic light, and "never
run" must not read as "failed" — they are different facts and only one is a
problem.

**The reasoning elision keeps both ends.** Middle-elided, not truncated: on the
tool path the opening lines say what the model is about to do, which is the part
worth reading next to the tool call it explains.

Plus `ui.py`'s two display conversions, which live here because the hub is what
made them necessary. `format_ts` converts a stored timestamp to local time —
the hub stacks Recent chats (UTC, from the db) directly above Routines (local,
from the run log), so an unconverted string put two adjacent panels two hours
apart. `vault_relative` trims the machine's mount prefix off a printed path.
Both are **display only**: nothing may store or reopen what they return, and
the assertions that matter are the ones about what they leave alone.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def build(path):
    """A db with one of everything the picker has to sort out."""
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY, title TEXT, model TEXT, provider TEXT,
            created_at TEXT, updated_at TEXT, system_prompt TEXT,
            system_prompt_name TEXT, persona TEXT, persona_name TEXT,
            first_message_name TEXT, first_message_text TEXT,
            first_message_at TEXT);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, session_id INTEGER, role TEXT,
            content TEXT, model TEXT, tokens_in INTEGER, tokens_out INTEGER,
            created_at TEXT, kind TEXT DEFAULT 'chat', meta TEXT);
    """)
    rows = [
        (1, "A real chat", "nano-gpt", "2026-07-21T10:00"),
        (2, "routine: Heartbeat — 2026-07-20 19:13", "routine", "2026-07-20T19:13"),
        (3, "A wiki page", "wiki", "2026-07-19T10:00"),
        (4, "Another chat", "nano-gpt", "2026-07-18T10:00"),
        (5, "From some new provider", "openai", "2026-07-17T10:00"),
        (6, "Provider is NULL", None, "2026-07-16T10:00"),
    ]
    for sid, title, prov, ts in rows:
        c.execute("INSERT INTO sessions (id,title,model,provider,updated_at) "
                  "VALUES (?,?,?,?,?)", (sid, title, "m", prov, ts))
    c.execute("INSERT INTO messages (session_id, role, content, tokens_in, "
              "tokens_out) VALUES (1,'user','hi',1000,500)")
    c.commit()
    return c


def main():
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "hub.db"
    assert "/.cfc/" not in str(path)   # invariant #1: assert before writing
    conn = build(path)

    import hub

    print("--- the picker shows chats; :list shows everything ---")
    # hub.recent_chats, not a copy of its query: an earlier version of this
    # test rebuilt the SQL here and passed against a deliberately broken
    # filter, which is worse than having no test at all.
    titles = [r[1] for r in hub.recent_chats(conn)]
    everything = [r[1] for r in conn.execute(hub._SELECT + hub._ORDER).fetchall()]

    ok("routine runs are out of the picker",
       not any("routine:" in t for t in titles), titles)
    ok("wiki pages are out of the picker", "A wiki page" not in titles, titles)
    ok("real chats survive", "A real chat" in titles and "Another chat" in titles)
    ok("/list still shows the routine run", any("routine:" in t for t in everything))
    ok("/list still shows the wiki page", "A wiki page" in everything)

    # The whole point of a deny list. An allow list would hide both of these,
    # and hiding a real conversation is the failure that cannot be noticed.
    ok("an UNKNOWN provider still shows as a chat",
       "From some new provider" in titles, titles)
    ok("a NULL provider still shows as a chat",
       "Provider is NULL" in titles, titles)

    print("\n--- the picker returns the id you typed, and only a listed one ---")
    # There is one numbering in the app now. The picker used to show 1..n, so a
    # row read as "3" was typed at `/delete chat 3`, where 3 is an id — and in
    # this very fixture id 3 is the wiki page. Typing a real-but-unlisted id
    # must be refused rather than resumed: `recent_chats` filtered it out, so
    # opening it would resume something the user was not looking at.
    import builtins
    import contextlib
    import io

    def pick(*typed):
        """Drive pick_session with a scripted keyboard. Returns its value."""
        feed = iter(typed)
        real_input = builtins.input
        builtins.input = lambda *a, **k: next(feed)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return hub.pick_session(conn)
        finally:
            builtins.input = real_input

    # No routine rows: the folder is a vault path and this test isn't about it.
    import routines as _routines
    _saved_dir = _routines.routine_dir
    _routines.routine_dir = lambda: tmp / "no-routines"
    try:
        ok("typing a listed chat id resumes that id", pick("4") == 4)
        ok("the newest chat's id works too", pick("1") == 1)
        ok("the wiki page's id (3) is refused, not opened",
           pick("3", "1") == 1)
        ok("the routine run's id (2) is refused, not opened",
           pick("2", "1") == 1)
        ok("an id that doesn't exist is refused", pick("99", "1") == 1)
        # 2 is a live session id, and under the old 1..n scheme "2" was a valid
        # row. It must no longer be read as "the second row".
        ok("a positional 1..n guess no longer selects by position",
           pick("2", "q") == "quit")
        ok("'n' still means new", pick("n") is None)
        ok("'p' still means private", pick("p") == "private")
        ok("'q' still quits", pick("q") == "quit")
        ok("garbage reprompts rather than raising", pick("banana", "q") == "quit")
    finally:
        _routines.routine_dir = _saved_dir

    print("\n--- the Ctx column ---")
    from ui import context_style, context_thresholds
    green_max, orange_max = context_thresholds()
    ok("thresholds are green<orange", green_max < orange_max,
       (green_max, orange_max))
    ok(f"just under {green_max}% is green", context_style(green_max - 0.1) == "green")
    ok(f"just over {green_max}% is orange", context_style(green_max + 0.1) == "orange3")
    ok(f"just over {orange_max}% is red", context_style(orange_max + 0.1) == "red")
    ok("0% is green", context_style(0) == "green")

    # A count with no denominator gets no colour — an uncoloured "N / ?" reads
    # as a size, a coloured one reads as a verdict the code can't actually
    # make. "/ ?" matches the header/status wording (D-1.7-02) rather than
    # looking like a shorter, different fact.
    cell = hub._context_cell("unknown-model", 8, 0)
    ok("no known limit -> 'N / ?', dim", cell.plain == "8 / ?" and "dim" in str(cell.style),
       (cell.plain, cell.style))
    ok("8 tokens does not render as '0k'", cell.plain != "0k / ?", cell.plain)
    ok("a big count abbreviates",
       hub._context_cell("unknown-model", 40000, 0).plain == "40k / ?")
    ok("no tokens at all -> em dash",
       hub._context_cell("unknown-model", 0, 0).plain == "—")

    # A known limit still gets the coloured percentage — the "N / ?" fallback
    # above must not have swallowed this branch.
    import models as models_mod
    saved_limit = models_mod.context_limit
    models_mod.context_limit = lambda model: 1000
    try:
        known = hub._context_cell("known-model", 250, 0)
        ok("a known limit -> coloured percentage, not 'N / ?'",
           known.plain == "25.0%" and "dim" not in str(known.style),
           (known.plain, known.style))
    finally:
        models_mod.context_limit = saved_limit

    print("\n--- timestamps are shown in local time ---")
    # `db.py` stores UTC; every other module writes local naive time. The hub
    # prints both — Recent chats from the db, Routines from the run log — one
    # panel above the other, so an unconverted UTC string put two adjacent
    # panels two hours apart. The golden harness cannot catch this: SCRUB
    # normalises timestamps on both sides, so it is invisible there.
    import datetime
    from ui import format_ts

    # Built against an offset five hours from *this* machine's, so the
    # assertion has teeth in every timezone including UTC itself. A test using
    # a literal '+00:00' would pass without the conversion on a UTC box.
    local_off = datetime.datetime.now().astimezone().utcoffset()
    far = datetime.timezone(local_off + datetime.timedelta(hours=5))
    wall = datetime.datetime(2026, 7, 26, 20, 30, tzinfo=far)
    ok("an offset-carrying timestamp is converted to local",
       format_ts(wall.isoformat()) == "2026-07-26 15:30",
       format_ts(wall.isoformat()))

    # Naive means local here, in every module that writes one. Assuming UTC
    # would move the one set of times that was already right.
    ok("a naive timestamp is left exactly as it is",
       format_ts("2026-07-26 20:30:00") == "2026-07-26 20:30")
    ok("an unparseable value survives rather than raising",
       format_ts("not a timestamp") == "not a timestamp")

    print("\n--- vault paths are shown without the machine's prefix ---")
    # ui.vault_relative's sibling property to format_ts: a display conversion
    # that must not be mistaken for a real one. Nothing may build a path out of
    # what this returns, which is why the interesting assertions are the two
    # about *not* shortening.
    from ui import vault_relative
    root = "/mnt/c/Users/you/my vault"
    ok("a path under the root loses the mount prefix, keeps the vault name",
       vault_relative(f"{root}/06 metadata/routines", root)
       == "/my vault/06 metadata/routines",
       vault_relative(f"{root}/06 metadata/routines", root))
    ok("a trailing slash on the root changes nothing",
       vault_relative(f"{root}/06 metadata", root + "/") == "/my vault/06 metadata")
    # Both directions of "leave it alone", and both are the point. A directory
    # configured outside the vault should *look* different rather than be
    # trimmed until it reads as local; and an unset root is a valid config, not
    # an error to paper over.
    ok("a path outside the root is left in full",
       vault_relative("/home/you/elsewhere/routines", root)
       == "/home/you/elsewhere/routines")
    ok("an unset root leaves every path in full",
       vault_relative(f"{root}/06 metadata", "") == f"{root}/06 metadata")

    print("\n--- the routine column answers 'is anything owed' ---")
    # Rewritten in v0.9.2 (`B-0.9.1-04`) and again in v1.5.1 (`W-0.9.2-02`).
    # v0.9.2 replaced hours-since-last-run thresholds with `why_not_due()`
    # itself, so the assertions that pinned those thresholds are gone — that
    # rule no longer exists, and they were statements about nothing.
    #
    # v1.5.1 splits what used to be one coloured `_freshness` cell into two:
    # `_last_run_cell` (a plain timestamp, never coloured) and
    # `_schedule_cell` (over `schedule.assess()`, which is what actually
    # carries the due-ness colour now). The reason is the bug itself: a
    # routine that had spent its whole retry budget on failures still read
    # green in the one cell a person looks at first, because "is anything
    # owed" and "did the last run go well" had been folded into one colour.
    #
    # `schedule` binds `last_settled`/`last_success` at import
    # (`from routines import ... last_settled`), so the seam to patch is
    # `schedule.last_settled`/`schedule.last_success`/`schedule._runs_today`,
    # never `routines.last_run` or `routines.last_settled`. Patching the
    # latter is the mistake `HANDOVER.md` names under "patch the seam, not
    # config", and it would leave every due assertion silently reading
    # Cas's real run logs.
    import schedule as sched
    from routines import Routine

    now = datetime.datetime.now()

    def at(hours_ago):
        return (now - datetime.timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")

    def routine(trigger="0300", enabled=True, rid="r"):
        return Routine(id=rid, name=rid, prompt="p", trigger=trigger,
                       enabled=enabled)

    def with_last_run(ts, fn):
        """Run `fn` with `schedule.last_settled` pinned to one settled run."""
        saved = sched.last_settled
        try:
            sched.last_settled = lambda _id: ("ok", ts, False)
            return fn()
        finally:
            sched.last_settled = saved

    def schedule_style(routine_obj, now_):
        return hub._schedule_cell(sched.assess(routine_obj, now_))[1]

    # --- Last run: formatting only, never coloured by due-ness ---
    ok("never run is dim, not red",
       hub._last_run_cell(None) == ("never", "dim"))
    ok("an unparseable timestamp is shown, not dropped",
       hub._last_run_cell("garbage")[0] == "garbage")
    ok("...and is dim", hub._last_run_cell("garbage")[1] == "dim")

    # --- Schedule: dim means "cannot be owed a run", whatever the timestamp
    # says. The four-in-six case that made this bug wider than the report: a
    # command routine has no honest threshold, so its age must not colour
    # anything.
    ok("a command routine is dim however old its last run",
       with_last_run(at(500), lambda: schedule_style(
           routine(trigger="command"), now)) == "dim")
    ok("...and however fresh",
       with_last_run(at(1), lambda: schedule_style(
           routine(trigger="command"), now)) == "dim")
    ok("a disabled routine is dim, not green",
       schedule_style(routine(enabled=False), now) == "dim")
    # Detected via parse_trigger inside assess(), so a trigger nobody can
    # read lands here too rather than falling through to green. See the
    # docstring on D-10.
    ok("a malformed trigger is dim, not green",
       schedule_style(routine(trigger="nonsense"), now) == "dim")

    # --- the colour flips across the trigger time, not across a duration ---
    today_late = now.replace(hour=12, minute=0, second=0, microsecond=0)
    ran_today = today_late.replace(hour=3, minute=5).strftime("%Y-%m-%d %H:%M:%S")
    ran_yesterday = (today_late - datetime.timedelta(days=1)).replace(
        hour=3, minute=5).strftime("%Y-%m-%d %H:%M:%S")

    ok("a daily routine that already ran today is green",
       with_last_run(ran_today,
                     lambda: schedule_style(routine(), today_late)) == "green")
    ok("...and is orange once today's trigger has passed unserved",
       with_last_run(ran_yesterday,
                     lambda: schedule_style(routine(), today_late)) == "orange3")
    # Before its trigger, nothing is owed yet — the same routine, the same last
    # run, an earlier clock. This is the assertion that would fail if anything
    # went back to measuring elapsed hours.
    early = today_late.replace(hour=1, minute=0)
    ok("...and green again before today's trigger comes round",
       with_last_run(ran_yesterday,
                     lambda: schedule_style(routine(), early)) == "green")

    # --- the two that pin the *reported* bug (B-0.9.1-04), and the only
    # ones here that would fail against the old thresholds ---
    #
    # A weekly job that absorbed its week on schedule, looked at six days later
    # — the report's own words were "red for five days in seven". Fixed dates,
    # because a weekly assertion derived from `today` changes meaning depending
    # on the weekday the suite runs. 27-07-2026 is a Monday, 02-08 the Sunday
    # after; both sit in the week whose last completed week is 20–26 July, so
    # the week is absorbed and nothing is owed.
    weekly_ran = "2026-07-27 03:30:00"
    weekly_now = datetime.datetime(2026, 8, 2, 12, 0)
    saved_success = sched.last_success
    try:
        sched.last_success = lambda _id: datetime.datetime(2026, 7, 27, 3, 30)
        ok("a weekly routine that absorbed its week is green six days on",
           with_last_run(weekly_ran,
                         lambda: schedule_style(routine(trigger="weekly 0330"),
                                                weekly_now)) == "green",
           "was red under the v0.4 thresholds — this is B-0.9.1-04 itself")
    finally:
        sched.last_success = saved_success

    # And the other direction: badly overdue is still only orange. Red left
    # this column deliberately — "how badly overdue" is not a fact assess()
    # knows, and inventing it means reinventing the threshold.
    long_ago = (today_late - datetime.timedelta(days=3)).replace(
        hour=3, minute=5).strftime("%Y-%m-%d %H:%M:%S")
    ok("three days overdue is orange, not red — red is gone from this column",
       with_last_run(long_ago,
                     lambda: schedule_style(routine(), today_late)) == "orange3")

    print("\n--- W-0.9.2-02: a retry-limited routine reads 'retry limit', "
          "not green reassurance ---")
    # The bug this whole split exists for: `Last run` used to be coloured by
    # due-ness, so a routine that had spent its retry budget on failures —
    # genuinely "not due until tomorrow" — read exactly like a routine that
    # had simply settled cleanly. Splitting the columns doesn't need the
    # Schedule colour to change: green here is still an honest answer to
    # "is a run owed" (no, not until tomorrow). What changes is that `Last
    # run` no longer borrows that colour, and `Result` — driven by the
    # routine's real last-run status — says `failed`, in red, right beside
    # it, so the row as a whole cannot be misread as fine.
    import routines as routines_mod
    saved_list, saved_lr = routines_mod.list_routines, routines_mod.last_run
    saved_settled = sched.last_settled
    saved_runs_today = sched._runs_today
    try:
        # A midnight trigger is always "at or after" by the time this test
        # runs, so the retry-limit branch is reached regardless of the
        # wall-clock hour the suite happens to run at.
        limited = routine(rid="limited", trigger="0000")
        ran_ts = datetime.datetime.now().replace(
            hour=0, minute=1, second=0, microsecond=0
        ).strftime("%Y-%m-%d %H:%M:%S")
        routines_mod.list_routines = lambda: ([limited], [])
        routines_mod.last_run = lambda _id: ("failed", ran_ts, False)
        sched.last_settled = lambda _id: ("failed", ran_ts, False)
        sched._runs_today = lambda rid, since: (
            [("failed", None)] * sched.MAX_RETRIES_PER_DAY)
        rows = hub._routine_rows()
        ok("one row for the retry-limited routine", len(rows) == 1, rows)
        (_name, last_label, last_style, sched_label, sched_style,
         status, review) = rows[0]
        ok("Schedule names the retry limit specifically",
           sched_label == "retry limit", sched_label)
        ok("...and it is not red — the alarm belongs to Result, not here",
           sched_style == "green", sched_style)
        ok("Last run stays dim regardless — no due-ness colour leaks into it",
           last_style == "dim", last_style)
        ok("Result still carries the real failure, in its own field",
           status == "failed", status)
    finally:
        routines_mod.list_routines, routines_mod.last_run = saved_list, saved_lr
        sched.last_settled, sched._runs_today = saved_settled, saved_runs_today

    print("\n--- one bad routine costs its row, never the panel ---")
    # pick_session renders the panel under `if routines:`, so [] and "no
    # routines configured" are the same screen. A routine that upsets
    # assess() must not be able to empty it.
    saved_list, saved_lr = routines_mod.list_routines, routines_mod.last_run
    try:
        rs = [routine(rid="good"), routine(rid="bad")]
        routines_mod.list_routines = lambda: (rs, [])
        def boom(rid):
            if rid == "bad":
                raise RuntimeError("this routine's log is on fire")
            return ("ok", at(1), False)
        routines_mod.last_run = boom
        rows = hub._routine_rows()
        ok("both rows survive one exploding routine", len(rows) == 2, rows)
        ok("...and the broken one degrades to a dim '?' in both cells, not "
           "a vanished row",
           any(r[1] == "?" and r[2] == "dim" and r[3] == "?" and r[4] == "dim"
               for r in rows), rows)
    finally:
        routines_mod.list_routines, routines_mod.last_run = saved_list, saved_lr

    print("\n--- the picker never dies on the routine folder ---")
    # It is a vault path over the /mnt/c bridge: missing, unmounted and
    # unreadable are all normal, and none is a reason a session picker
    # shouldn't open.
    import routines
    saved = routines.routine_dir
    try:
        routines.routine_dir = lambda: Path("/nonexistent/nowhere")
        ok("a missing routine folder yields no rows, no exception",
           hub._routine_rows() == [])
    finally:
        routines.routine_dir = saved

    print("\n--- the picker shows all seven current routines (W-1.1-04) ---")
    # The cap was 5; a seventh routine used to fall off the panel with no
    # signal it existed. Bumped to 7 — still a bounded display limit, not
    # derived from however many routines the vault holds.
    ok("the cap itself is 7, not 5", hub.HUB_ROUTINES == 7)
    try:
        ids = [f"r{i}" for i in range(1, 8)]
        rs = [routine(rid=rid) for rid in ids]
        routines_mod.list_routines = lambda: (rs, [])
        # Newest-first: r1 ran most recently, r7 longest ago.
        stamps = {rid: at(i) for i, rid in enumerate(ids, start=1)}
        routines_mod.last_run = lambda rid: ("ok", stamps[rid], False)
        rows = hub._routine_rows()
        ok("all seven routines appear, none dropped by the old cap",
           len(rows) == 7, rows)
        ok("...newest-first order is preserved",
           [r[0] for r in rows] == ids, rows)
    finally:
        routines_mod.list_routines, routines_mod.last_run = saved_list, saved_lr

    print("\n--- never-run routines still sort last, even at the new cap ---")
    try:
        ids = [f"s{i}" for i in range(1, 7)]  # six ever-run
        rs = [routine(rid=rid) for rid in ids] + [routine(rid="never")]
        routines_mod.list_routines = lambda: (rs, [])
        stamps = {rid: at(i) for i, rid in enumerate(ids, start=1)}

        def lr(rid):
            if rid == "never":
                raise RuntimeError("no log for a routine that never ran")
            return ("ok", stamps[rid], False)
        routines_mod.last_run = lr
        rows = hub._routine_rows()
        ok("the seven fit under the new cap with the never-run one last",
           [r[0] for r in rows] == ids + ["never"], rows)
    finally:
        routines_mod.list_routines, routines_mod.last_run = saved_list, saved_lr

    print("\n--- column widths stay fixed, never flexible ---")
    from ui import console
    saved_w = console.width
    try:
        for w in (80, 100, 140, 200):
            console.width = w
            title, prompt, persona = hub._widths()
            ok(f"{w} cols: title>={hub._TITLE_MIN}, names>={hub._NAME_MIN}",
               title >= hub._TITLE_MIN and prompt >= hub._NAME_MIN
               and persona >= hub._NAME_MIN, (title, prompt, persona))
        console.width = 200
        t200, p200, _ = hub._widths()
        console.width = 80
        t80, p80, _ = hub._widths()
        ok("a wider terminal gives Prompt more room, not just Title",
           p200 > p80, (p80, p200))
        ok("every column carries an explicit width (none flexible)",
           all(c.width for c in hub._session_table("x").columns))
    finally:
        console.width = saved_w

    print("\n--- tool-path reasoning is middle-elided, keeping both ends ---")
    import agent
    short = "\n".join(f"line {i}" for i in range(5))
    ok("short reasoning is untouched", agent._elide(short) == short)
    long_text = "\n".join(f"line {i}" for i in range(100))
    out = agent._elide(long_text)
    ok("long reasoning shrinks", len(out.splitlines()) < 100)
    ok("the head is kept", "line 0" in out)
    ok("the tail is kept", "line 99" in out)
    ok("the middle is gone", "line 50" not in out)
    ok("it says how much it hid", "more lines of reasoning" in out)
    # Eliding one line to insert one "…" line saves nothing and loses content.
    edge = "\n".join(f"l{i}" for i in range(agent.REASONING_HEAD_LINES
                                            + agent.REASONING_TAIL_LINES + 1))
    ok("never elides when it wouldn't save a line", agent._elide(edge) == edge)

    print("\n--- runner marks its own session at insert ---")
    # The backfill would eventually catch an unmarked routine session by its
    # title, which is exactly the title-parsing this replaced. Assert the call
    # site passes the marker, so the backfill stays a migration rather than
    # quietly becoming the mechanism.
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(__import__("runner")))
    marked = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", "") == "new_session"
        and any(kw.arg == "provider" for kw in n.keywords)
    ]
    ok("runner.py calls new_session(provider=...)", bool(marked))
    ok("...with PROVIDER_ROUTINE",
       any(getattr(kw.value, "id", "") == "PROVIDER_ROUTINE"
           for n in marked for kw in n.keywords if kw.arg == "provider"))

    conn.close()
    test_format_date_localises()
    test_hub_help_is_derived()
    test_first_message_counts()
    test_hub_lifecycle()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


def test_first_message_counts():
    """1.3: a frozen opening is not a `messages` row, but the picker's
    Messages column counts it anyway — the same human-facing total
    `/status` and an export show (tests/test_export.py pins the export
    half)."""
    print("\n--- the Messages column counts a First Message too ---")
    import db as dbmod
    tmp = Path(tempfile.mkdtemp())
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()

    plain = dbmod.new_session(conn, title="plain")
    dbmod.save_message(conn, plain, "user", "hi")
    dbmod.save_message(conn, plain, "assistant", "hello")

    opened = dbmod.new_session(conn, title="opened")
    dbmod.set_first_message(conn, opened, "muse.md", "Good morning.")
    dbmod.save_message(conn, opened, "user", "hi")
    dbmod.save_message(conn, opened, "assistant", "hello")

    import hub
    rows = {r[0]: r for r in conn.execute(hub._SELECT + hub._ORDER).fetchall()}
    ok("a session with no First Message: msg_count is the raw row count",
       rows[plain][3] == 2, rows[plain])
    # -2, not -1: `s.provider` (1.4, for rendering Main distinctly) was added
    # after has_first_message, which is no longer the last column.
    ok("has_first_message is false for it",
       rows[plain][-2] == 0, rows[plain])
    ok("a session with a First Message: has_first_message is true",
       rows[opened][-2] == 1, rows[opened])

    class _T:
        def add_row(self, *a):
            self.last = a
    t_plain, t_opened = _T(), _T()
    hub._add_rows(t_plain, [rows[plain]])
    hub._add_rows(t_opened, [rows[opened]])
    ok("the rendered Messages cell is the raw count for a plain session",
       t_plain.last[2] == "2", t_plain.last)
    ok("...and raw+1 for a session with a First Message",
       t_opened.last[2] == "3", t_opened.last)
    conn.close()


def test_format_date_localises():
    """`ui.format_date` — the three `[:10]` sites Block 9 replaced.

    `db.py` is the only module that stores UTC, so slicing the first ten
    characters off `created_at` reads the *stored* date: a session created after
    22:00 local is filed and labelled under tomorrow. Silent, off by one, and
    only in the evenings.

    **Pinned against an offset computed from the host's, never a literal.**
    A test written against `+00:00` passes on a UTC machine whether or not the
    conversion exists — which is exactly how the two-hour hub bug survived. Same
    trick as the `format_ts` test above, and for the same reason.
    """
    import datetime as _dt
    from ui import format_date, format_ts

    print("\n--- format_date reads the local date, not the stored one ---")
    # Five hours the other side of wherever this is running, so the date must
    # differ from a naive slice for at least one instant of the day.
    here = _dt.datetime.now().astimezone().utcoffset() or _dt.timedelta(0)
    far = _dt.timezone(here + _dt.timedelta(hours=-5))

    # An instant that is late evening locally and already tomorrow in the
    # stored zone — the exact shape of the bug.
    local_now = _dt.datetime(2026, 3, 14, 23, 30, tzinfo=_dt.datetime.now().astimezone().tzinfo)
    stored = local_now.astimezone(_dt.timezone.utc).isoformat()
    ok("the local date wins over the stored one",
       format_date(stored) == "2026-03-14", (stored, format_date(stored)))
    ok("...and a naive [:10] slice is what would have been wrong",
       format_date(stored) == format_ts(stored)[:10],
       (format_date(stored), format_ts(stored)))

    # A naive timestamp is left alone: everything naive in this codebase is
    # already local, so attaching a zone would move the times that were right.
    ok("a naive timestamp is not shifted",
       format_date("2026-03-14T23:30:00") == "2026-03-14")
    # And the two helpers must agree, or a filename and its own header drift.
    aware = _dt.datetime(2026, 7, 1, 12, 0, tzinfo=far).isoformat()
    ok("format_date is format_ts's date half",
       format_date(aware) == format_ts(aware)[:10],
       (format_date(aware), format_ts(aware)))
    ok("junk degrades to the old slice rather than raising",
       format_date("not a date") == "not a date"[:10])

def test_hub_help_is_derived():
    """`h` at the hub — the help screen and the dispatch are one table.

    A hand-written help screen is a fourth list with nothing checking it, and
    the day it disagrees it teaches the wrong command confidently. Invariant 13
    keeps the session's lists in agreement by asserting rather than
    remembering; this is the same move one level up.
    """
    import io
    from contextlib import redirect_stdout
    import hub as hubmod
    from ui import CONNECTION_STYLE

    print("\n--- hub help is generated, not written ---")
    # The dispatch is built from the table, so every documented key works.
    for keys, value, _ in hubmod.HUB_KEYS:
        for key in keys:
            ok(f"'{key}' is dispatched",
               hubmod._HUB_DISPATCH.get(key) is value
               or hubmod._HUB_DISPATCH[key] == value,
               key)
    # ...and nothing is dispatched that the table doesn't declare. This is the
    # assertion that makes the help trustworthy: a key cannot exist without a
    # description, because the description is where the key comes from.
    declared = {k for keys, _, _ in hubmod.HUB_KEYS for k in keys}
    ok("no key is dispatched that the help doesn't describe",
       set(hubmod._HUB_DISPATCH) == declared,
       set(hubmod._HUB_DISPATCH) ^ declared)

    buf = io.StringIO()
    with redirect_stdout(buf):
        hubmod.console.file = buf
        hubmod.print_hub_help()
        hubmod.console.file = sys.stdout
    out = buf.getvalue()
    for keys, _, what in hubmod.HUB_KEYS:
        ok(f"'{keys[0]}' appears on the help screen", keys[0] in out, out[:200])
        ok(f"...with its description", what[:20] in out, what)
    ok("a chat id is explained, since it isn't a key", "number" in out, out[:200])

    # The light's legend comes from the same mapping the light renders, so a
    # new connection state cannot be missing from the help. Whitespace is
    # collapsed on both sides before comparing: Rich wraps a long advice
    # string (the v1.2.1 wording names both the chat and the config-screen
    # command) to the console width, which can land a newline mid-phrase.
    flat_out = " ".join(out.split())
    for _, _, text in CONNECTION_STYLE.values():
        flat_text = " ".join(text.split())
        ok(f"the legend carries: {text[:28]}", flat_text in flat_out, text)

    # The Ctx legend is rendered by `_context_cell`, the same function the
    # table's cells come from, so the shape in the help cannot drift from the
    # shape on screen (Concept.md, v1.6.2: the hub explains what `number / ?`
    # means). Round-tripped rather than compared to the literal "8 / ?" —
    # a test written against the literal passes forever while the pair drifts.
    ok("the Ctx legend names the column", "Ctx column" in flat_out, out[:400])
    for tok in (0, 8):
        cell = str(hubmod._context_cell("", tok, 0))
        ok(f"the Ctx legend renders the cell for {tok} tokens",
           cell in flat_out, cell)
    ok("...and says the unknown state is a missing config limit",
       "no 'limit' in config.py" in flat_out, out[:400])


def test_hub_lifecycle():
    """`c`/`d` at the hub: create at a chosen id, delete by identity,
    redrawing after either — driven end to end through `hub.pick_session`,
    the real `db.py` schema, and the shared `commands.create_chat_with_id` /
    `commands.delete_chat` operations (Concept.md's chat lifecycle).

    A raw hand-built fixture (see `build()` above) has no `session_tags`
    table and can't run `delete_session`, so this uses a real `db.db(":memory:")`
    connection instead — the schema `c`/`d` actually run against.
    """
    import builtins
    import contextlib
    import io

    import db as dbmod
    import hub as hubmod

    def pick(*typed):
        feed = iter(typed)
        real_input = builtins.input
        builtins.input = lambda *a, **k: next(feed)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return hubmod.pick_session(conn)
        finally:
            builtins.input = real_input

    conn = dbmod.db(":memory:")
    dbmod.new_session(conn, title="an ordinary chat")

    print("\n--- 'c' creates at a chosen id, then the id opens ---")
    ok("'c' with a fresh id creates and enters it",
       pick("c", "777") == 777)
    ok("the row is really there, as an ordinary chat",
       conn.execute("SELECT provider FROM sessions WHERE id=777"
                    ).fetchone() == (dbmod.PROVIDER_CHAT,))

    print("\n--- collision refuses and redraws rather than opening it ---")
    # After the refusal there is nothing left to do but redraw, so the script
    # continues into a fresh prompt — proven by the next keystroke ('q')
    # being read by the *redrawn* hub rather than being swallowed.
    ok("creating at an occupied id refuses, and the hub comes back",
       pick("c", "777", "q") == "quit")

    print("\n--- 'd' deletes by id, with exact confirmation ---")
    target_id = dbmod.new_session(conn, title="to be deleted")
    ok("a wrong confirmation cancels and redraws",
       pick("d", str(target_id), "nope", "q") == "quit")
    ok("...and the session survived the cancelled attempt",
       conn.execute("SELECT 1 FROM sessions WHERE id=?",
                    (target_id,)).fetchone() is not None)
    ok("the exact id confirms deletion, then redraws",
       pick("d", str(target_id), str(target_id), "q") == "quit")
    ok("...and it is really gone",
       conn.execute("SELECT 1 FROM sessions WHERE id=?",
                    (target_id,)).fetchone() is None)

    print("\n--- 'd' refuses a wiki/routine row as not-a-chat ---")
    wiki_id = dbmod.new_session(conn, title="a wiki page",
                               provider=dbmod.PROVIDER_WIKI)
    ok("a wiki row's id refuses, and the hub redraws",
       pick("d", str(wiki_id), "q") == "quit")
    ok("...and it is untouched",
       conn.execute("SELECT 1 FROM sessions WHERE id=?",
                    (wiki_id,)).fetchone() is not None)

    print("\n--- 'd main' resolves Main by identity, not an edited title ---")
    main_id, _ = dbmod.get_or_create_main(conn, "muse.md", "hi")
    dbmod.set_session_title(conn, main_id, "not actually Main")
    ok("'main' still resolves the real Main row despite the edited title",
       pick("d", "main", "main", "q") == "quit")
    ok("...and Main is really gone",
       dbmod.main_session_id(conn) is None)

    print("\n--- deleting a chat with chunks and vectors is index-clean ---")
    import sqlite_vec
    import chunk as chunkmod
    chunkmod.ensure_table(conn, rebuild=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
                "chunk_id integer primary key, embedding float[4])")
    indexed_id = dbmod.new_session(conn, title="indexed chat")
    dbmod.save_message(conn, indexed_id, "user", "hello", kind="chat")
    mid = conn.execute("SELECT id FROM messages WHERE session_id=?",
                       (indexed_id,)).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO chunks (message_id,session_id,kind,ordinal,text,"
        "token_est,source) VALUES (?,?,'message',0,'hello',1,'chat')",
        (mid, indexed_id))
    cid = cur.lastrowid
    conn.execute("INSERT INTO vec_chunks (chunk_id,embedding) VALUES (?,?)",
                (cid, sqlite_vec.serialize_float32([0.1, 0.2, 0.3, 0.4])))
    conn.commit()
    ok("delete through 'd' removes the chat",
       pick("d", str(indexed_id), str(indexed_id), "q") == "quit")
    ok("...and its chunk",
       conn.execute("SELECT COUNT(*) FROM chunks WHERE message_id=?",
                    (mid,)).fetchone()[0] == 0)
    ok("...and its vector",
       conn.execute("SELECT COUNT(*) FROM vec_chunks WHERE chunk_id=?",
                    (cid,)).fetchone()[0] == 0)

    print("\n--- cancelling create with a blank id redraws too ---")
    ok("an empty id at 'c' cancels, and the hub comes back",
       pick("c", "", "q") == "quit")

    conn.close()


if __name__ == "__main__":
    sys.exit(main())
