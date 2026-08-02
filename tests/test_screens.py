#!/usr/bin/env python3
"""
test_screens.py — the command-screen controller: config, wiki, routines.
No API calls, no network.

    python3 tests/test_screens.py

1.2's whole claim is a boundary: on a command screen, a submitted line is
either a recognised action or a visible refusal — never a model message.
`screens.classify()` is where that boundary lives, and it is tested directly
rather than through a terminal, which is also what makes a "pasted multi-line
string" testable at all: a real paste only stays one input under prompt_toolkit
with a live tty, which nothing here has.

Everything runs against temp directories — routines.routine_dir/prompt_dir/
log_dir and wikigit.wiki_dir/journal_dir are patched, never config.py — and a
temp sqlite db, never ~/.cfc/chat.db.
"""
import builtins
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import db as dbmod
import routines
import screens
import wikigit

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


class Store:
    """Redirect routines' three directories at temp dirs. Same seam
    test_routines.py patches, and for the same reason: config would miss a
    caller that already imported the value."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.rdir = self.tmp / "routines"
        self.pdir = self.tmp / "prompts"
        self.ldir = self.tmp / "logs"
        for d in (self.rdir, self.pdir, self.ldir):
            d.mkdir(parents=True, exist_ok=True)
        (self.pdir / "task.md").write_text("Do the thing.", encoding="utf-8")

    def __enter__(self):
        self._saved = (routines.routine_dir, routines.prompt_dir,
                       routines.log_dir)
        routines.routine_dir = lambda: self.rdir
        routines.prompt_dir = lambda: self.pdir
        routines.log_dir = lambda: self.ldir
        return self

    def __exit__(self, *exc):
        (routines.routine_dir, routines.prompt_dir,
         routines.log_dir) = self._saved


class NoWiki:
    """wikigit with no configured corpus — the deterministic 'unavailable'
    state, without touching a real git repo."""

    def __enter__(self):
        self._saved = (wikigit.wiki_dir, wikigit.journal_dir)
        wikigit.wiki_dir = lambda: None
        wikigit.journal_dir = lambda: None
        return self

    def __exit__(self, *exc):
        wikigit.wiki_dir, wikigit.journal_dir = self._saved


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout


class WikiRepo:
    """A temp git repo standing in for the wiki corpus."""

    def __init__(self, tmp):
        self.root = Path(tmp).resolve()
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@example.invalid")
        git(self.root, "config", "user.name", "Test")
        (self.root / "a.md").write_text("hello\n", encoding="utf-8")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "baseline")

    def __enter__(self):
        self._saved = (wikigit.wiki_dir, wikigit.journal_dir)
        wikigit.wiki_dir = lambda: self.root
        wikigit.journal_dir = lambda: None
        return self

    def __exit__(self, *exc):
        wikigit.wiki_dir, wikigit.journal_dir = self._saved

    def edit(self, text="hello again\n", name="a.md"):
        (self.root / name).write_text(text, encoding="utf-8")


def scripted(answers):
    """Replace input() with a script for the duration of the `with` block.
    Same idiom test_routines.py uses for create_routine(): running out of
    answers is read as Ctrl-C (the human gave up), not a bare StopIteration —
    that's what lets a script deliberately abandon a flow by simply ending."""
    class _Ctx:
        def __enter__(self2):
            self2.real = builtins.input
            it = iter(answers)

            def fake(*a, **k):
                try:
                    return next(it)
                except StopIteration:
                    raise KeyboardInterrupt
            builtins.input = fake
            return self2

        def __exit__(self2, *exc):
            builtins.input = self2.real
    return _Ctx()


def drive(mode, answers, conn):
    """Run screens.enter() end to end against a scripted keyboard."""
    with scripted(answers):
        return screens.enter(conn, mode=mode)


# --- classify(): the three outcomes -----------------------------------------


def test_classify():
    print("\n--- classify(): blank, recognised, invalid ---")
    table = screens.build_table("config")

    for blank in ("", "   ", "/", " / "):
        outcome, payload = screens.classify(table, blank)
        ok(f"{blank!r} is blank", outcome == "blank" and payload is None)

    outcome, payload = screens.classify(table, "please run short term memory")
    ok("prose with no matching verb is invalid",
       outcome == "bad" and payload == "please run short term memory")

    outcome, payload = screens.classify(table, "/frobnicate")
    ok("an unknown slash command is invalid, not blank or recognised",
       outcome == "bad" and payload == "frobnicate")

    multi = "please\ndo the routine thing\nfor me"
    outcome, payload = screens.classify(table, multi)
    ok("a multi-line paste is classified once, as a whole",
       outcome == "bad" and payload == multi, (outcome, payload))

    outcome, payload = screens.classify(table, "refresh")
    ok("a real verb dispatches", outcome == "ok" and payload[0] is not None)
    outcome2, payload2 = screens.classify(table, "REFRESH")
    ok("verbs are case-insensitive", outcome2 == "ok" and
       payload2[0] is payload[0])
    outcome3, _ = screens.classify(table, "/refresh")
    ok("one leading slash is stripped", outcome3 == "ok")
    outcome4, payload4 = screens.classify(table, "//refresh")
    ok("a second slash is not — chat muscle memory only goes so far",
       outcome4 == "bad" and payload4 == "/refresh", (outcome4, payload4))

    # Case and spacing in the *argument* must survive untouched.
    outcome, (handler, rest) = screens.classify(table, "connect Embedding")
    ok("arguments keep their case", rest == "Embedding", rest)

    print("\n--- phrase aliases (wiki's diff synonyms) ---")
    wtable = screens.build_table("wiki")
    for phrase in ("show diff", "inspect diff", "review diff", "diff"):
        outcome, (handler, rest) = screens.classify(wtable, f"{phrase} vault")
        ok(f"'{phrase} vault' dispatches to diff with rest 'vault'",
           outcome == "ok" and rest == "vault" and
           handler is wtable.dispatch["diff"], (outcome, rest))


# --- help / dispatch: one table, walked both ways ---------------------------


def test_help_matches_dispatch():
    print("\n--- every table: help and dispatch are the same table ---")
    import io
    from contextlib import redirect_stdout

    for mode in ("config", "wiki", "routine"):
        table = screens.build_table(mode)
        buf = io.StringIO()
        screens.console.file = buf
        screens._print_help(table)
        screens.console.file = sys.stdout
        out = buf.getvalue()

        for name, aliases, help_text, handler in table.entries:
            ok(f"[{mode}] '{name}' is in the dispatch table",
               table.dispatch.get(name) is handler)
            for a in aliases:
                ok(f"[{mode}] alias '{a}' dispatches to the same handler",
                   table.dispatch.get(a) is handler)
            ok(f"[{mode}] '{name}' appears on its own help screen",
               name in out, out)

        # And the reverse: nothing dispatched that help doesn't print. Every
        # dispatch key is a name or an alias of some entry.
        declared = {name for name, *_ in table.entries}
        declared |= {a for _n, aliases, *_ in table.entries for a in aliases}
        ok(f"[{mode}] no dispatch key is undeclared",
           set(table.dispatch) == declared,
           set(table.dispatch) ^ declared)

        # Common navigation is present everywhere it should be, and switching
        # to the current screen is deliberately absent.
        ok(f"[{mode}] q/quit/back all leave", all(
            table.dispatch[k](None, None, table) is screens.TO_HUB
            for k in ("q", "quit", "back")))
        for target in ("config", "wiki", "routine"):
            if target == mode:
                ok(f"[{mode}] switching to itself is not offered",
                   target not in table.dispatch or mode == "config")
            else:
                ok(f"[{mode}] '{target}' switches screens",
                   table.dispatch[target](None, None, table) ==
                   ("switch", target))


# --- navigation: no recursion, no stack -------------------------------------


def test_navigation():
    print("\n--- config -> wiki -> routine -> q returns to the hub ---")
    with tempfile.TemporaryDirectory() as tmp, Store(tmp), NoWiki():
        conn = dbmod.db(":memory:")
        result = drive("config", ["wiki", "routine", "q"], conn)
        ok("the walk ends at the hub (None)", result is None, result)

    print("\n--- EOF at a screen prompt leaves to the hub ---")
    with tempfile.TemporaryDirectory() as tmp, Store(tmp), NoWiki():
        conn = dbmod.db(":memory:")

        def raises_eof(*a, **k):
            raise EOFError
        with scripted([]):
            builtins.input = raises_eof
            result = screens.enter(conn, mode="config")
        ok("EOF is read as 'leave'", result is None, result)

    print("\n--- per-visit state does not survive leaving a screen ---")
    with tempfile.TemporaryDirectory() as tmp, WikiRepo(tmp) as repo:
        conn = dbmod.db(":memory:")
        repo.edit()
        # Arm a review in wiki; switching away is itself an exit route, so it
        # asks once ('y' confirms leaving the armed review behind). Back in
        # wiki, the table is rebuilt fresh, so a plain 'q' this time must NOT
        # ask again — that is the property under test.
        result = drive("wiki", ["diff", "config", "y", "wiki", "q"], conn)
        ok("a re-entered wiki screen starts with no armed review",
           result is None, result)


# --- prose / unknown commands / paste: no message save, no API call --------


def test_no_side_effects_on_invalid_input():
    print("\n--- invalid input never reaches a save or a model ---")
    saved = []
    real_save = dbmod.save_message
    dbmod.save_message = lambda *a, **k: saved.append((a, k))
    try:
        with tempfile.TemporaryDirectory() as tmp, Store(tmp), NoWiki():
            conn = dbmod.db(":memory:")
            multi = "line one\nline two\nline three"
            drive("config", ["please run short term memory", multi,
                             "/nope", "q"], conn)
    finally:
        dbmod.save_message = real_save
    ok("no message was ever saved while driving invalid input",
       saved == [], saved)


# --- config screen -----------------------------------------------------


def test_config_render():
    import io
    from contextlib import redirect_stdout

    def rendered():
        buf = io.StringIO()
        screens.console.file = buf
        screens._render_config()
        screens.console.file = sys.stdout
        return buf.getvalue()

    print("\n--- config: the API key never appears ---")
    with tempfile.TemporaryDirectory() as tmp, Store(tmp), NoWiki():
        out = rendered()
        import config as _config
        real_key = getattr(_config, "API_KEY", "")
        if real_key:
            ok("the API key string is not printed", real_key not in out, out)
        ok("key state is reported as set/not set, not the key itself",
           "key set" in out or "key not set" in out, out)

    print("\n--- config: a stale marker reads 'update required', "
          "an absent one 'no update flagged' — never 'current' ---")
    import backfill
    saved_marker = backfill._wiki_marker_path
    with tempfile.TemporaryDirectory() as tmp:
        marker = Path(tmp) / "wiki_reindex_needed"
        backfill._wiki_marker_path = lambda: str(marker)
        try:
            with tempfile.TemporaryDirectory() as tmp2, Store(tmp2), NoWiki():
                out = rendered()
                ok("no marker -> 'no update flagged'",
                   "no update flagged" in out, out)
                ok("...and never claims to be current",
                   "current" not in out.lower().replace("no update flagged",
                                                        ""), out)
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text("x", encoding="utf-8")
                out = rendered()
                ok("a set marker -> 'update required'",
                   "update required" in out, out)
        finally:
            backfill._wiki_marker_path = saved_marker

    print("\n--- config: an unreadable wiki corpus is 'unavailable', "
          "not silently clean ---")
    with tempfile.TemporaryDirectory() as tmp, Store(tmp), NoWiki():
        out = rendered()
        ok("Wiki row reports unavailable when WIKI_DIR is unset",
           "unavailable — WIKI_DIR is not configured" in out, out)

    print("\n--- config: distinct routine-attention counts ---")
    with tempfile.TemporaryDirectory() as tmp, Store(tmp) as store, NoWiki():
        out = rendered()
        ok("no routines -> nothing needs attention",
           "nothing needs attention" in out, out)

        clean = routines.Routine(id="clean", name="Clean", prompt="task.md",
                                 read_roots=[str(store.pdir)])
        routines.save_routine(clean)
        out = rendered()
        ok("one healthy routine -> still nothing needs attention",
           "nothing needs attention" in out, out)

        routines.append_log("clean", "failed", "boom")
        out = rendered()
        ok("one failed routine -> 1 needs attention",
           "1 needs attention" in out, out)
        ok("...naming the reason", "1 failed" in out, out)

        invalid = routines.Routine(id="broken", name="Broken", prompt="gone.md")
        (store.rdir / "broken.md").write_text(invalid.to_markdown(),
                                              encoding="utf-8")
        out = rendered()
        ok("a second routine needing attention -> 2 need attention",
           "2 need attention" in out, out)
        ok("...summing both reasons", "1 invalid" in out and "1 failed" in out,
           out)

        # W-0.9.2-02: the "due" bucket now reads schedule.assess(...).due
        # rather than its own `why_not_due(...) is None` check — a
        # never-run, past-its-trigger-time routine must still count. A
        # trigger of 00:01 is "past" for virtually any wall-clock time this
        # suite runs at, with no date-rollover arithmetic to get wrong.
        overdue = routines.Routine(id="overdue", name="Overdue",
                                   prompt="task.md", trigger="0001",
                                   read_roots=[str(store.pdir)])
        routines.save_routine(overdue)
        out = rendered()
        ok("a due, never-run routine adds to the count",
           "3 need attention" in out, out)
        ok("...naming 'due' among the reasons", "1 due" in out, out)


def test_config_paths_and_connect():
    print("\n--- config: 'paths' names every path, or 'not configured' ---")
    import io
    with tempfile.TemporaryDirectory() as tmp, Store(tmp), NoWiki():
        conn = dbmod.db(":memory:")
        table = screens.build_table("config")
        buf = io.StringIO()
        screens.console.file = buf
        table.dispatch["paths"]("", conn, table)
        screens.console.file = sys.stdout
        out = buf.getvalue()
        ok("the routine store shows up", "Routine definitions" in out, out)
        ok("an unconfigured path says so", "not configured" in out, out)

    print("\n--- config: 'connect' without 'embedding' is refused, not run ---")
    with tempfile.TemporaryDirectory() as tmp, Store(tmp), NoWiki():
        conn = dbmod.db(":memory:")
        table = screens.build_table("config")
        called = []
        import commands
        real = commands.connect_embedding
        commands.connect_embedding = lambda: called.append(1)
        try:
            table.dispatch["connect"]("nonsense", conn, table)
            ok("a bad argument does not run the connection flow",
               called == [], called)
            table.dispatch["connect"]("embedding", conn, table)
            ok("'connect embedding' does", called == [1], called)
        finally:
            commands.connect_embedding = real


# --- wiki screen -------------------------------------------------------


def test_screens_never_print_chat_syntax():
    """`B-1.2-01`: a screen printed `/wiki diff all` and then refused it.

    The general shape is that commands.py's wiki output was written for one
    reader (a chat) and v1.2 gave it a second (the screen), so this asserts the
    property rather than the five call sites that had it wrong: **nothing
    printed on a screen names a chat command.** `/wiki`, `/routine` and
    `/config` are the three, since those are the screens.

    The lookbehind is what keeps a *path* out of it — the config screen prints
    `03 resources/wiki db`, which is not an instruction to type anything.
    """
    import io
    import re

    print("\n--- no screen prints a chat command line ---")
    chat_syntax = re.compile(r"(?<![\w/])/(?:wiki|routine|config)\b")

    def captured(fn):
        """`screens.console.file = buf`, the idiom the rest of this file uses.
        `redirect_stdout` does not work here: ui.py's Console is built once at
        import and every module shares that one object (decision 6), so the
        capture has to go through it."""
        buf = io.StringIO()
        screens.console.file = buf
        try:
            fn()
        except Exception:
            pass
        finally:
            screens.console.file = sys.stdout
        return buf.getvalue()

    def leaks(mode, answers, conn):
        out = captured(lambda: drive(mode, answers, conn))
        return sorted({line.strip() for line in out.splitlines()
                       if chat_syntax.search(line)})

    with tempfile.TemporaryDirectory() as tmp, WikiRepo(tmp) as repo:
        conn = dbmod.db(":memory:")
        repo.edit()
        (repo.root / "new page.md").write_text("fresh\n", encoding="utf-8")
        found = leaks("wiki", ["status", "diff", "commit", "diff vault",
                               "commit vault", "q", "y"], conn)
        ok("the wiki screen never suggests /wiki", found == [], found)
        conn.close()

    with tempfile.TemporaryDirectory() as tmp, Store(tmp) as store:
        conn = dbmod.db(":memory:")
        found = leaks("routine", ["help", "q"], conn)
        ok("the routine screen never suggests /routine", found == [], found)
        found = leaks("config", ["help", "paths", "refresh", "q"], conn)
        ok("the config screen never suggests /config", found == [], found)
        conn.close()

    # The other half, and it compares the two renderings to each other rather
    # than to a literal — `test_turn_paths.py`'s idiom. The screen form must be
    # the chat form with `/wiki ` taken out and nothing else: that fails the
    # moment a site hardcodes the prefix again, and needs no edit when the
    # wording changes. Whitespace is normalised because dropping six characters
    # moves rich's wrapping.
    print("\n--- the screen form is the chat form minus its prefix ---")
    import commands

    def rendered(fn, **kw):
        return " ".join(captured(lambda: fn(**kw)).split())

    with tempfile.TemporaryDirectory() as tmp, WikiRepo(tmp) as repo:
        repo.edit()
        for name, fn, arg in (
                ("status", commands.show_wiki_status, {}),
                ("diff", commands.show_wiki_diff, {"arg": ""}),
                ("commit (no message)", commands.do_wiki_commit, {"arg": ""})):
            chat = rendered(fn, lead="/wiki ", **arg)
            screen = rendered(fn, lead="", **arg)
            ok(f"{name}: chat output minus '/wiki ' is the screen output",
               " ".join(chat.replace("/wiki ", "").split()) == screen,
               (chat[:160], screen[:160]))


def test_wiki_review():
    print("\n--- wiki: a successful diff arms review; leaving asks ---")
    with tempfile.TemporaryDirectory() as tmp, WikiRepo(tmp) as repo:
        conn = dbmod.db(":memory:")
        repo.edit()
        result = drive("wiki", ["diff", "q", "n", "q", "y"], conn)
        ok("'n' stays, 'y' leaves", result is None, result)

    print("\n--- wiki: status alone never arms the question ---")
    with tempfile.TemporaryDirectory() as tmp, WikiRepo(tmp) as repo:
        conn = dbmod.db(":memory:")
        repo.edit()
        result = drive("wiki", ["status", "q"], conn)
        ok("status doesn't arm — q leaves with no prompt", result is None)

    print("\n--- wiki: a failed diff does not arm review ---")
    with tempfile.TemporaryDirectory() as tmp, WikiRepo(tmp) as repo:
        conn = dbmod.db(":memory:")
        repo.edit()
        # An unconfigured journal scope raises inside show_wiki_diff/status.
        result = drive("wiki", ["diff journal", "q"], conn)
        ok("a diff that hits a GitError leaves nothing armed",
           result is None, result)

    print("\n--- wiki: commit resolves the review for that scope ---")
    with tempfile.TemporaryDirectory() as tmp, WikiRepo(tmp) as repo:
        conn = dbmod.db(":memory:")
        repo.edit()
        result = drive("wiki", ["diff", "commit a real message", "q"], conn)
        ok("committing the reviewed scope clears it — q leaves with no ask",
           result is None, result)

    print("\n--- wiki: files changing after the diff says so distinctly ---")
    with tempfile.TemporaryDirectory() as tmp, WikiRepo(tmp) as repo:
        conn = dbmod.db(":memory:")
        repo.edit()
        table = screens.build_table("wiki")
        table.dispatch["diff"]("", conn, table)
        review = table.state["wiki_review"]
        ok("the review snapshot carries the diffed paths",
           review["paths"] == {"a.md"}, review)
        (repo.root / "b.md").write_text("new file\n", encoding="utf-8")
        seen = []
        real_input = builtins.input
        builtins.input = lambda *a, **k: (seen.append(a[0] if a else ""),
                                          "y")[1]
        try:
            ok_leave = screens._leave_ok(table, "the session picker")
        finally:
            builtins.input = real_input
        ok("leaving after a file changed says 'changed since the diff'",
           any("changed since the diff" in s for s in seen), seen)
        ok("'y' still defers and lets you leave", ok_leave is True)

    print("\n--- wiki: zero changes after a commit needs no prompt at all ---")
    with tempfile.TemporaryDirectory() as tmp, WikiRepo(tmp) as repo:
        conn = dbmod.db(":memory:")
        repo.edit()
        table = screens.build_table("wiki")
        table.dispatch["diff"]("", conn, table)
        table.dispatch["commit"]("a message here", conn, table)
        ok("the review key is gone once the scope is clean",
           "wiki_review" not in table.state, table.state)


def test_wiki_quick_forms_unaffected():
    """The existing chat quick forms (`/wiki diff ...`, `/wiki commit ...`)
    call straight into commands.py and never touch screens.py at all — this
    just pins that the functions screens.py calls are the same ones the
    quick forms already used, so there is one implementation, not two."""
    print("\n--- wiki: the screen reuses the quick forms' own functions ---")
    import commands
    wtable = screens.build_table("wiki")
    with tempfile.TemporaryDirectory() as tmp, WikiRepo(tmp) as repo:
        conn = dbmod.db(":memory:")
        repo.edit()
        calls = []
        real = commands.show_wiki_diff
        commands.show_wiki_diff = lambda arg, lead=None: calls.append((arg, lead))
        try:
            wtable.dispatch["diff"]("vault", conn, wtable)
        finally:
            commands.show_wiki_diff = real
        ok("the screen's diff handler calls commands.show_wiki_diff",
           calls == [("vault", "")], calls)


# --- routines screen -----------------------------------------------------


def test_routines_show_history_open():
    print("\n--- routines: show / history / open ---")
    with tempfile.TemporaryDirectory() as tmp, Store(tmp) as store:
        conn = dbmod.db(":memory:")
        table = screens.build_table("routine")

        r = routines.Routine(id="nightly", name="Nightly", prompt="task.md",
                             read_roots=[str(store.pdir)])
        routines.save_routine(r)
        routines.append_log("nightly", "ok", "did the thing", session_id=99)

        import io
        buf = io.StringIO()
        screens.console.file = buf
        table.dispatch["show"]("nightly", conn, table)
        screens.console.file = sys.stdout
        out = buf.getvalue()
        ok("show prints the full detail, model included",
           "nightly" in out and "id" in out and "valid" in out, out)
        # W-0.9.2-02: `show` is the one screen with room for assess()'s full
        # reason rather than a compact word — this routine's default
        # trigger is 'command', so its schedule is never due and says so.
        ok("...and the full schedule reason, not just a compact word",
           "schedule" in out and "runs only from /routine" in out, out)

        buf = io.StringIO()
        screens.console.file = buf
        table.dispatch["history"]("nightly", conn, table)
        screens.console.file = sys.stdout
        out = buf.getvalue()
        ok("history names the session id", "session #99" in out, out)

        # 'open' is provider-checked, using db.routine_session — a chat
        # session id is refused, only a real routine session opens.
        chat_sid = dbmod.new_session(conn, title="a chat")
        result = table.dispatch["open"](str(chat_sid), conn, table)
        ok("open refuses a non-routine session id", result is None)

        routine_sid = dbmod.new_session(conn, title="routine: Nightly",
                                        provider=dbmod.PROVIDER_ROUTINE)
        result = table.dispatch["open"](str(routine_sid), conn, table)
        ok("open accepts a real routine session",
           result == ("transcript", routine_sid), result)

        result = table.dispatch["open"]("99999", conn, table)
        ok("open refuses a session id that doesn't exist", result is None)

        result = table.dispatch["open"]("not-a-number", conn, table)
        ok("open refuses a non-numeric argument, not raise", result is None)

        print("\n--- routines: legacy and current records share one history ---")
        # Prepended, not appended: a legacy line is an *older* run, so it
        # belongs before the current one in file order — matching how a real
        # log actually accumulates, oldest write first.
        legacy_path = routines.log_path("nightly")
        text = legacy_path.read_text(encoding="utf-8")
        header, _, rest = text.partition("\n\n")
        legacy_path.write_text(
            f"{header}\n\n"
            "- **2020-01-01 00:00:00** — ok — an old run (session 1)\n"
            f"{rest}", encoding="utf-8")
        buf = io.StringIO()
        screens.console.file = buf
        table.dispatch["history"]("nightly", conn, table)
        screens.console.file = sys.stdout
        out = buf.getvalue()
        lines = [l.strip() for l in out.splitlines()
                if l.strip().startswith("20")]
        ok("newest first", lines[0].startswith("2026") and
           lines[1].startswith("2020"), lines)


def test_routines_run_and_new():
    print("\n--- routines: 'run' goes through the existing runner seam ---")
    import commands
    with tempfile.TemporaryDirectory() as tmp, Store(tmp) as store:
        conn = dbmod.db(":memory:")
        table = screens.build_table("routine")
        calls = []
        real = commands.do_routine
        commands.do_routine = lambda c, name, model=None: calls.append(name)
        try:
            table.dispatch["run"]("nightly", conn, table)
        finally:
            commands.do_routine = real
        ok("run dispatches through commands.do_routine, not a new call path",
           calls == ["nightly"], calls)

    print("\n--- routines: 'new' lands back in routines, not chat ---")
    with tempfile.TemporaryDirectory() as tmp, Store(tmp):
        conn = dbmod.db(":memory:")
        table = screens.build_table("routine")
        import io
        buf = io.StringIO()
        import commands
        commands.console.file = buf
        with scripted([]):   # nothing typed -> Ctrl-C on the first prompt
            table.dispatch["new"]("", conn, table)
        commands.console.file = sys.stdout
        out = buf.getvalue()
        ok("an abandoned 'new' from the screen names the screen, not chat",
           "back in routines" in out, out)
        ok("...and never claims the next line is a chat message",
           "next line you type is a message" not in out, out)


def test_chat_model_threading():
    print("\n--- B-05: 'run' resolves like /routine <name> would, from the "
          "chat that opened this screen ---")
    import commands
    with tempfile.TemporaryDirectory() as tmp, Store(tmp):
        conn = dbmod.db(":memory:")
        real = commands.do_routine
        calls = []
        commands.do_routine = lambda c, name, model=None: calls.append(
            (name, model))
        try:
            # Entered straight from the hub: no chat model to carry.
            table = screens.build_table("routine")
            table.dispatch["run"]("nightly", conn, table)
            ok("no chat_model given -> do_routine sees model=None",
               calls[-1] == ("nightly", None), calls[-1])

            # Entered from a chat pinned to a specific model.
            table = screens.build_table("routine",
                                        chat_model="deepseek/deepseek-v4-pro")
            table.dispatch["run"]("nightly", conn, table)
            ok("the opening chat's model reaches do_routine",
               calls[-1] == ("nightly", "deepseek/deepseek-v4-pro"),
               calls[-1])

            # Switching screens must not drop it.
            table2 = screens.build_table(
                "config", chat_model=table.chat_model)
            ok("the model survives a screen switch",
               table2.chat_model == "deepseek/deepseek-v4-pro")
        finally:
            commands.do_routine = real

    print("\n--- W-1.2.1-02: entering a screen says help exists ---")
    with tempfile.TemporaryDirectory() as tmp, Store(tmp):
        conn = dbmod.db(":memory:")
        table = screens.build_table("config")
        import io
        buf = io.StringIO()
        screens.console.file = buf
        screens.render(table, conn)
        screens.console.file = sys.stdout
        out = buf.getvalue()
        ok("the config screen names 'help' on the way in, unprompted",
           "help" in out.lower(), out)


def test_routines_narrow_and_wide():
    print("\n--- routines: neither width elides a value ---")
    long_model = "provider/deepseek-v4-pro-cheaper-and-considerably-longer:thinking"
    long_error = ("prompt file not found in /some/very/long/configured/path/"
                 "that/keeps/going/for/a/while: gone.md")
    with tempfile.TemporaryDirectory() as tmp, Store(tmp) as store:
        r = routines.Routine(id="longid", name="Long", prompt="task.md",
                             model=long_model, read_roots=[str(store.pdir)])
        routines.save_routine(r)
        # D-1.4-02: a routine whose name and slug differ. The file is
        # hand-authored id: short term memory, which Routine.__init__
        # slugifies to short-term-memory — the row must still show the name.
        named = routines.Routine(id="short term memory",
                                 name="Short Term Memory", prompt="task.md",
                                 read_roots=[str(store.pdir)])
        routines.save_routine(named)
        ok("the slug and the name really do differ",
           named.id != named.name, (named.id, named.name))
        # A routine that fails validate(), whose name and slug also differ —
        # the case that shows whether the validation line agrees with the row.
        broken = routines.Routine(id="broken routine", name="Broken Routine",
                                  prompt="x.md")
        (store.rdir / "broken-routine.md").write_text(
            broken.to_markdown().replace("prompt: x.md", "prompt: gone.md"),
            encoding="utf-8")

        conn = dbmod.db(":memory:")
        import io
        saved_w = screens.console.width
        try:
            for width in (80, 140):
                screens.console.width = width
                buf = io.StringIO()
                screens.console.file = buf
                screens._render_routines(conn)
                screens.console.file = sys.stdout
                out = buf.getvalue()
                ok(f"width {width}: the full model id survives",
                   long_model in out, out)
                ok(f"width {width}: the row shows the routine's name, "
                   "not its slug id", "Short Term Memory" in out, out)
                ok(f"width {width}: ...and never the bare slug",
                   "short-term-memory" not in out, out)
                ok(f"width {width}: the validation line below the table "
                   "names the same display name as the row",
                   "! Broken Routine:" in out, out)
                ok(f"width {width}: ...never the slug id",
                   "broken-routine:" not in out, out)
        finally:
            screens.console.width = saved_w


# --- private chat entering a screen reaches the durable conn ----------------


def test_private_screen_uses_app_conn():
    print("\n--- a screen entered from a private chat uses app_conn, "
          "never the private connection ---")
    import main as chatmain

    with tempfile.TemporaryDirectory() as tmp, Store(tmp):
        durable = dbmod.db(":memory:")
        durable_sid = dbmod.new_session(durable, title="routine: Nightly",
                                        provider=dbmod.PROVIDER_ROUTINE)
        priv = dbmod.db(":memory:")
        priv_sid = dbmod.new_session(priv, title="(untitled)")

        script = f"/routine\nopen {durable_sid}\n"
        import io, contextlib
        out = io.StringIO()
        real_stdin = sys.stdin
        sys.stdin = io.StringIO(script)
        try:
            with contextlib.redirect_stdout(out):
                chatmain.console.file = out
                outcome = chatmain.run_session(priv, priv_sid, private=True,
                                               app_conn=durable)
        finally:
            sys.stdin = real_stdin
        ok("the routines screen found the session on the durable conn",
           outcome is not None and outcome.session_id == durable_sid,
           outcome)
        ok("...and labelled it a routine transcript",
           outcome.routine_transcript is True)
        priv.close()
        durable.close()


def main():
    test_classify()
    test_help_matches_dispatch()
    test_navigation()
    test_no_side_effects_on_invalid_input()
    test_config_render()
    test_config_paths_and_connect()
    test_screens_never_print_chat_syntax()
    test_wiki_review()
    test_wiki_quick_forms_unaffected()
    test_routines_show_history_open()
    test_routines_run_and_new()
    test_chat_model_threading()
    test_routines_narrow_and_wide()
    test_private_screen_uses_app_conn()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
