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
            system_prompt_name TEXT, persona TEXT, persona_name TEXT);
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
    ok(":list still shows the routine run", any("routine:" in t for t in everything))
    ok(":list still shows the wiki page", "A wiki page" in everything)

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

    # A count with no denominator gets no colour — an uncoloured number reads
    # as a size, a coloured one reads as a verdict the code can't actually make.
    cell = hub._context_cell("unknown-model", 8, 0)
    ok("no known limit -> raw count, dim", cell.plain == "8" and "dim" in str(cell.style),
       (cell.plain, cell.style))
    ok("8 tokens does not render as '0k'", cell.plain != "0k", cell.plain)
    ok("a big count abbreviates",
       hub._context_cell("unknown-model", 40000, 0).plain == "40k")
    ok("no tokens at all -> em dash",
       hub._context_cell("unknown-model", 0, 0).plain == "—")

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

    print("\n--- routine freshness ---")
    now = datetime.datetime.now()

    def at(hours_ago):
        return (now - datetime.timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S")

    ok("1h ago is green", hub._freshness(at(1))[1] == "green")
    ok("23h ago is green", hub._freshness(at(23))[1] == "green")
    ok("30h ago is orange", hub._freshness(at(30))[1] == "orange3")
    ok("60h ago is red", hub._freshness(at(60))[1] == "red")
    # "never" is a different fact from "overdue". Colouring it red would cry
    # wolf on the day you write a routine.
    ok("never run is dim, not red", hub._freshness(None) == ("never", "dim"))
    ok("an unparseable timestamp is shown, not dropped",
       hub._freshness("garbage")[0] == "garbage")

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
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
