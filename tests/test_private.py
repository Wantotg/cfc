#!/usr/bin/env python3
"""test_private.py — a private chat leaves nothing on disk. No API calls.

    python3 tests/test_private.py

The guarantee is silent-failure-shaped: miss one write path and the whole
conversation is sitting on disk with nothing to say it shouldn't be. So the
test asserts the *negative* — the real database is untouched, auto-embed and
auto-export never fire, model file-writes are refused — against a **control**
(a normal chat) that exercises every one of those, proving the assertions can
fail. A negative test with no control passes just as happily when the feature
is a no-op.

The isolation itself is structural, not a pile of `if private` checks: a private
chat runs against an in-memory database (`db(":memory:")`), so every conn-driven
write — including the ones agent_turn makes on its own — lands in a throwaway db
that dies with the connection. `private=True` only gates the two paths that
escape the connection (auto-embed reads the real db by path; auto-export writes
a file) and strips the write scope so model file-writes are refused.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import context
import db as dbmod
import main
import models
import tools

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def count_msgs(conn):
    return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]


def _never_raises(errorlog):
    """Point the log at a path that cannot exist and check both writers return
    False instead of propagating. Verified by breaking it, which is the habit
    that caught the journal's git guard: an exception swallowed by a bare
    `except` is indistinguishable from one that never happened until you make
    one happen."""
    from pathlib import Path as _P
    keep = errorlog.LOG_PATH
    try:
        # A directory component that is a regular file — mkdir and open both
        # fail, and neither is allowed to reach the caller mid-turn.
        errorlog.LOG_PATH = _P("/etc/passwd/nope/errors.log")
        return (errorlog.log_launch() is False
                and errorlog.log_error(Exception("x"), session_id=1) is False)
    except Exception:      # noqa: BLE001 — the thing under test is that this is unreachable
        return False
    finally:
        errorlog.LOG_PATH = keep


def drive(conn, sid, private, keys):
    """Run one session to completion. `:tools off` takes the streaming path
    rather than agent_turn; the stubbed stream returns a real answer so the turn
    persists, and the title call is a no-op so nothing reaches the network."""
    out = io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(keys)
    try:
        with contextlib.redirect_stdout(out):
            main.console.file = out
            # auto_export=True always: the control (private=False) needs its
            # export path armed to prove the spy can fire at all, and every
            # private=True call needs it armed the same way to prove privacy's
            # gate — not a False auto_export — is what's blocking it.
            main.run_session(conn, sid, auto_export=True, private=private)
    finally:
        sys.stdin = real_stdin
    return out.getvalue()


def main_():
    tmp = Path(tempfile.mkdtemp())
    # Invariant #1: assert the path BEFORE anything writes to it. A guard that
    # ran after its destructive step once deleted the real database.
    assert "tmp" in str(tmp) and not str(tmp).startswith(
        str(Path("~/.cfc").expanduser())), "refusing to touch a real db"
    dbmod.DB_PATH = tmp / "chat.db"

    # The stand-in for ~/.cfc/chat.db — what a private chat must never write to.
    real = dbmod.db()

    # Stubs: no network, and the two disk side effects we're measuring are
    # replaced by spies so a real export never lands in the real vault.
    embeds, exports = [], []
    main.stream_response = lambda messages, model=None: (
        "an answer", {"prompt_tokens": 3, "completion_tokens": 2}, "")
    main.generate_title = lambda *a, **k: "(untitled)"   # guarded out, no call
    main.auto_embed = lambda: embeds.append(1)
    main.safe_export = lambda *a, **k: exports.append(1)

    script = "/tools off\nhello\n/q\n"

    print("\n--- a normal chat: writes to disk (the control) ---")
    real_sid = dbmod.new_session(real, title="normal")
    embeds.clear(); exports.clear()
    drive(real, real_sid, private=False, keys=script)
    ok("the turn is persisted", count_msgs(real) >= 2, count_msgs(real))
    ok("auto-embed runs", embeds == [1], embeds)
    ok("auto-export runs on :q", exports == [1], exports)

    print("\n--- a private chat: nothing reaches the real db ---")
    before = count_msgs(real)
    priv = dbmod.db(":memory:")
    priv_sid = dbmod.new_session(priv, title="(untitled)")
    embeds.clear(); exports.clear()
    # Forced True regardless of the real config.py's default, so the entry
    # notice's db_on branch below is deterministic rather than depending on
    # whatever this machine happens to be configured with.
    saved_db_active = main.DATABASE_ACTIVE
    main.DATABASE_ACTIVE = True
    # D-1.7-02's post-turn context line goes through the same shared finisher
    # every chat uses — decision 15's "every feature is specified for private
    # chat too" — so it's exercised here rather than assumed. Pinned against a
    # model with no configured limit rather than whatever the real config.py
    # happens to say, or the assertion below would depend on this machine.
    saved_models = models.MODELS
    models.MODELS = [models._spec(main.current_process_model(), tools=False)]
    try:
        out = drive(priv, priv_sid, private=True, keys=script)
    finally:
        main.DATABASE_ACTIVE = saved_db_active
        models.MODELS = saved_models
    ok("the conversation is live in the private db",
       count_msgs(priv) >= 2, count_msgs(priv))
    ok("the real db is untouched", count_msgs(real) == before,
       (before, count_msgs(real)))
    ok("auto-embed is skipped", embeds == [], embeds)
    ok("auto-export is skipped on :q", exports == [], exports)
    ok("a private turn still shows an honest context line through the "
       "shared post-turn path",
       "tokens · limit unknown" in out, out)

    print("\n--- W-0.9.1-04: the entry notice states the local boundary, the "
          "provider boundary, and the read-only db choice ---")
    # The rewrite this pins: "in memory" told you a mechanism, not what it
    # means for your data. Every clause below is one of the five things the
    # notice now states plainly (main.py's `if private:` block).
    ok("states the local destruction boundary",
       "destroys it for good" in out and "no restore" in out, out)
    ok("states this is local privacy only — the provider still sees it",
       "local privacy only" in out and "selected chat" in out
       and "provider" in out, out)
    ok("states model file-writes are blocked",
       "Model file writes are blocked" in out, out)
    ok("states the one explicit exception",
       "/export" in out and "asked for it by name" in out, out)
    ok("states /database on is read-only for this chat",
       "read-only for this chat" in out, out)
    ok("...and does not repeat the old, less specific 'in memory' claim",
       "in memory, nothing written to disk" not in out, out)

    saved_db_active = main.DATABASE_ACTIVE
    main.DATABASE_ACTIVE = False
    try:
        priv_off = dbmod.db(":memory:")
        p_off = dbmod.new_session(priv_off, title="(untitled)")
        out_off = drive(priv_off, p_off, private=True, keys=script)
        priv_off.close()
    finally:
        main.DATABASE_ACTIVE = saved_db_active
    ok("with the database off, the notice still names read-only access "
       "as what turning it on would give",
       "read-only access to existing memory" in out_off, out_off)

    priv.close()   # and with the connection gone, so is the conversation

    print("\n--- the v0.8 surface adds a session field; it goes nowhere ---")
    # Invariant #10: a new disk-writing path has to be routed through `conn` or
    # it silently defeats the isolation. `traits` is the first column added
    # since private chat landed, so the negative is pinned rather than assumed.
    import pools
    tdir = Path(tempfile.mkdtemp())
    (tdir / "quiet.md").write_text("be quiet\n", encoding="utf-8")
    saved_trait_dir = pools.POOLS["trait"].configured
    pools.POOLS["trait"].configured = str(tdir)
    try:
        real_before = dbmod.get_traits(real, real_sid)
        priv3 = dbmod.db(":memory:")
        p3 = dbmod.new_session(priv3, title="(untitled)")
        drive(priv3, p3, private=True, keys="/add trait quiet\n/q\n")
        ok("a trait attaches in a private chat",
           dbmod.get_traits(priv3, p3) == ["quiet"],
           dbmod.get_traits(priv3, p3))
        ok("...and the real db never hears about it",
           dbmod.get_traits(real, real_sid) == real_before,
           dbmod.get_traits(real, real_sid))
        priv3.close()
    finally:
        pools.POOLS["trait"].configured = saved_trait_dir

    print("\n--- but an explicit :export is still honoured ---")
    priv2 = dbmod.db(":memory:")
    p2 = dbmod.new_session(priv2, title="(untitled)")
    exports.clear()
    # export_session is the explicit path (not safe_export); spy on it too.
    calls = []
    main.export_session = lambda conn, target, quiet=False: calls.append(target)
    drive(priv2, p2, private=True, keys="/tools off\nhello\n/export\n/q\n")
    ok("typing :export runs an export in a private chat", calls == [p2], calls)
    ok("...while auto-export on :q still does not", exports == [], exports)
    priv2.close()

    print("\n--- the database read toggle (recall/remember) ---")
    recalls = []
    main.do_recall = lambda q, **k: recalls.append(q)

    def recall_run(private, keys, db_active=False):
        saved = main.DATABASE_ACTIVE
        main.DATABASE_ACTIVE = db_active
        recalls.clear()
        c = dbmod.db(":memory:")
        s = dbmod.new_session(c, title="t")
        try:
            out = drive(c, s, private=private, keys=keys)
        finally:
            c.close()
            main.DATABASE_ACTIVE = saved
        return list(recalls), out

    r, out = recall_run(True, "/recall who is cas\n/q\n", db_active=False)
    ok("a private chat seals recall by default", r == [], r)
    ok("...and says the database is off", "Database is off" in out, out[-200:])

    r, _ = recall_run(True, "/database on\n/recall who is cas\n/q\n",
                      db_active=False)
    ok("/database on opens recall in a private chat", r == ["who is cas"], r)

    r, _ = recall_run(True, "/recall who is cas\n/q\n", db_active=True)
    ok("DATABASE_ACTIVE=True lets a private chat recall from the start",
       r == ["who is cas"], r)

    r, _ = recall_run(False, "/recall who is cas\n/q\n")
    ok("a normal chat recalls by default", r == ["who is cas"], r)

    print("\n--- model file-writes are blocked in a private chat ---")
    priv_ctx = context.chat_context(private=True)
    open_ctx = context.chat_context(private=False)
    _, cfg_write = context._config_roots()
    ok("a private chat has no write scope", priv_ctx.write_roots == ())
    ok("a normal chat keeps its configured write scope",
       tuple(open_ctx.write_roots) == tuple(context._norm(cfg_write)),
       open_ctx.write_roots)
    # precheck returns a tool-result string (json), or None to let the call run.
    refusal = tools.precheck(
        "write_file", {"path": str(tmp / "x.md"), "content": "hi"}, priv_ctx)
    ok("write_file is refused before it runs",
       refusal is not None and "writing is not enabled" in refusal, refusal)

    print("\n--- the provider error log is a fourth escape path; it is shut ---")
    # v0.9.1 added ~/.cfc/errors.log, which opens a file *by path* and so
    # bypasses the in-memory connection exactly as auto-embed and auto-export
    # do. What makes it worse than those two is its payload:
    # `api._error_detail` carries up to 800 characters of the **provider's own
    # body**, and providers echo request fragments back inside a 400. So the
    # negative here is not just "no line was written" but "the conversation's
    # words are not in that file" — asserted against a marker planted in the
    # error itself, because a test that only counts lines passes while leaking.
    import httpx
    import errorlog

    errorlog.LOG_PATH = tmp / "errors.log"
    assert "tmp" in str(errorlog.LOG_PATH), "refusing to touch the real log"
    SECRET = "zx-private-payload-must-not-land"

    def boom(messages, model=None):
        raise httpx.HTTPError(f"HTTP 400 from https://x/v1: {SECRET}")

    main.stream_response = boom

    # The control first, for the usual reason: an assertion that cannot fail is
    # not a test, and "the file has no line in it" is the passing state of a
    # logger that was never called at all.
    err_sid = dbmod.new_session(real, title="errors")
    drive(real, err_sid, private=False, keys=script)
    logged = errorlog.LOG_PATH.read_text() if errorlog.LOG_PATH.exists() else ""
    ok("a normal chat records a provider error", "error" in logged, logged[-200:])
    ok("...with the provider's own words", SECRET in logged, logged[-200:])

    before_log = logged
    priv2 = dbmod.db(":memory:")
    priv2_sid = dbmod.new_session(priv2, title="(untitled)")
    drive(priv2, priv2_sid, private=True, keys=script)
    priv2.close()
    after_log = errorlog.LOG_PATH.read_text()
    ok("a private chat records nothing", after_log == before_log,
       after_log[len(before_log):][:200])
    # D-17 added a second field to the same write — `kind`, the chat-turn
    # action. Same guard, so the same two-assertion shape: no line at all,
    # and the new field's own marker isn't the one line that snuck through.
    ok("...and the new turn-kind field isn't in the nothing that was written",
       "turn chat" not in after_log[len(before_log):], after_log[len(before_log):][:200])
    ok("...and log_error refuses it at the write, not at the call site",
       errorlog.log_error(Exception(SECRET), session_id=1, private=True,
                          kind="chat") is False)

    # The launch line is what makes an empty log mean "never written" rather
    # than "no errors" — the distinction the whole absence-watch rests on.
    ok("a launch line is written outside any session", errorlog.log_launch() is True)
    ok("...and logging never raises, whatever the path is",
       _never_raises(errorlog))

    print("\n--- v1.4.1: a title failure is a fifth escape path; it is shut "
          "too ---")
    # B-1.3.1-02 / D-13: main._finish_turn logs a title-specific failure with
    # `where="title"`, going through the same `errorlog.log_error` — so it
    # inherits property 3 (nothing from a private chat reaches it) for free
    # *if* the call site passes `private` through. That "if" is exactly the
    # kind of thing a caller forgets, so it gets its own control/private pair
    # rather than being assumed from the provider-error pair above.
    TITLE_SECRET = "zx-title-payload-must-not-land"

    def boom_title(*a, **k):
        raise main.TitleGenerationError(f"HTTP 400: {TITLE_SECRET}")

    main.generate_title = boom_title
    main.stream_response = lambda messages, model=None: (
        "an answer", {"prompt_tokens": 3, "completion_tokens": 2}, "")

    before_title_log = errorlog.LOG_PATH.read_text()
    title_ctl_sid = dbmod.new_session(real, title="(untitled)")
    drive(real, title_ctl_sid, private=False, keys=script)
    after_ctl_log = errorlog.LOG_PATH.read_text()
    new_ctl = after_ctl_log[len(before_title_log):]
    ok("a normal chat's failed title reaches the error log",
       "title" in new_ctl and TITLE_SECRET in new_ctl, new_ctl[:300])

    priv9 = dbmod.db(":memory:")
    p9 = dbmod.new_session(priv9, title="(untitled)")
    drive(priv9, p9, private=True, keys=script)
    priv9.close()
    after_priv_log = errorlog.LOG_PATH.read_text()
    ok("a private chat's failed title never reaches the error log",
       after_priv_log == after_ctl_log,
       after_priv_log[len(after_ctl_log):][:300])

    main.generate_title = lambda *a, **k: "(untitled)"   # guarded out again

    print("\n--- /clear notes: an explicit vault op, same in a private chat ---")
    # decision 15's exception is privacy itself — a feature that only works by
    # writing something down or phoning something home stays unbuilt for a
    # private chat. /clear notes isn't that: it never touches `conn` at all
    # (do_clear takes no session argument), so it is structurally outside the
    # isolation this file is otherwise testing, the same way /file already is.
    # The proof here is two-sided: privacy must not silently block the vault
    # operation, and the vault operation must not silently leak into the
    # channels privacy is sealing (db, embed, export).
    import notes
    tmp_notes = Path(tempfile.mkdtemp())
    inbox = tmp_notes / "notes"
    archive = tmp_notes / "archive"
    inbox.mkdir()
    inbox_cfg = {"NOTES_DIR": str(inbox), "NOTES_ARCHIVE_DIR": str(archive)}
    saved_notes_cfg = notes._cfg
    saved_notes_roots = notes.move_roots
    notes._cfg = lambda key, default=None: inbox_cfg.get(key, default)
    notes.move_roots = lambda: (tmp_notes.resolve(),)
    try:
        (inbox / "one.md").write_text("hello\n", encoding="utf-8")
        real_before = count_msgs(real)
        priv4 = dbmod.db(":memory:")
        p4 = dbmod.new_session(priv4, title="(untitled)")
        embeds.clear(); exports.clear()
        out = drive(priv4, p4, private=True, keys="/clear notes\n\n/q\n")
        ok("a private chat can still clear notes — privacy doesn't block "
           "an explicit vault operation", "archived 1 note" in out, out[-400:])
        ok("...and the note actually moved", not (inbox / "one.md").exists())
        ok("...without turning auto-embed on", embeds == [], embeds)
        ok("...without turning auto-export on", exports == [], exports)
        ok("...and nothing landed in the real db",
           count_msgs(real) == real_before, (real_before, count_msgs(real)))
        priv4.close()
    finally:
        notes._cfg = saved_notes_cfg
        notes.move_roots = saved_notes_roots

    print("\n--- 1.2: a screen entered from a private chat sees none of "
          "its history ---")
    # A command screen (bare /config, /wiki, /routine) is handed app_conn —
    # the durable connection repl() carries in — never the private chat's
    # own in-memory one, and it opens a routine transcript straight off
    # app_conn. The marked payload proves the private chat's own history
    # cannot reach either: not the durable database in general, and not the
    # specific transcript the screen opens.
    import routines
    tmp_routines = Path(tempfile.mkdtemp())
    saved_rdir = routines.routine_dir
    routines.routine_dir = lambda: tmp_routines
    SECRET2 = "zx-private-screen-payload-must-not-land"

    # A real routine transcript, sitting on the durable db already — what
    # the routines screen's 'open' is supposed to find.
    routine_sid = dbmod.new_session(
        real, title="routine: nightly", provider=dbmod.PROVIDER_ROUTINE)
    dbmod.save_message(real, routine_sid, "assistant",
                       "the routine's own transcript")
    real_before = count_msgs(real)

    priv6 = dbmod.db(":memory:")
    p6 = dbmod.new_session(priv6, title="(untitled)")
    dbmod.save_message(priv6, p6, "user", SECRET2)
    try:
        stdin = io.StringIO(f"/routine\nopen {routine_sid}\n")
        buf = io.StringIO()
        real_stdin = sys.stdin
        sys.stdin = stdin
        try:
            with contextlib.redirect_stdout(buf):
                main.console.file = buf
                outcome = main.run_session(priv6, p6, auto_export=False,
                                           private=True, app_conn=real)
        finally:
            sys.stdin = real_stdin
        ok("the routines screen resolved the transcript on the durable db",
           outcome == routine_sid, outcome)
        durable_text = " ".join(
            r[0] for r in real.execute(
                "SELECT content FROM messages").fetchall())
        ok("the marked private message never reaches the durable database",
           SECRET2 not in durable_text, durable_text[-300:])
        transcript_text = " ".join(
            r[0] for r in real.execute(
                "SELECT content FROM messages WHERE session_id=?",
                (routine_sid,)).fetchall())
        ok("...nor the specific transcript the screen opened",
           SECRET2 not in transcript_text, transcript_text)
        ok("...and the durable db gained nothing but what the screen wrote",
           count_msgs(real) == real_before, (real_before, count_msgs(real)))
    finally:
        priv6.close()
        routines.routine_dir = saved_rdir

    print("\n--- 1.3: First Message snapshots through conn, private "
          "included ---")
    # decision 10: private isolation is the connection, not a flag. Attaching
    # a persona with a matching companion in a private chat should freeze the
    # opening exactly as a normal chat does — into the private in-memory row,
    # never the real db — with no `if private` branch anywhere in the path
    # that does it (main.py has none).
    import pools
    persona_dir = Path(tempfile.mkdtemp())
    fm_dir = Path(tempfile.mkdtemp())
    (persona_dir / "muse.md").write_text("You are Muse.\n", encoding="utf-8")
    (fm_dir / "muse.md").write_text("Good evening — shall we begin?\n",
                                    encoding="utf-8")
    saved_persona_dir = pools.POOLS["persona"].configured
    saved_fm_dir = pools.FIRST_MESSAGES_DIR
    pools.POOLS["persona"].configured = str(persona_dir)
    pools.FIRST_MESSAGES_DIR = str(fm_dir)
    try:
        priv8 = dbmod.db(":memory:")
        p8 = dbmod.new_session(priv8, title="(untitled)")
        real_before = count_msgs(real)
        drive(priv8, p8, private=True, keys="/add persona muse\n/q\n")
        snap = dbmod.get_first_message(priv8, p8)
        ok("the private chat's own row got the snapshot",
           snap is not None and snap["text"] == "Good evening — shall we "
           "begin?", snap)
        ok("...and the real db never heard about it",
           count_msgs(real) == real_before, (real_before, count_msgs(real)))
        priv8.close()
    finally:
        pools.POOLS["persona"].configured = saved_persona_dir
        pools.FIRST_MESSAGES_DIR = saved_fm_dir

    print("\n--- 1.3: the governor's direction is request-only, in both "
          "chats ---")
    # Adding the governor must not create a fifth path around private-chat
    # isolation (Concept.md's own words). The marker rides on an OOC turn —
    # the trigger most likely to be typed with something worth keeping
    # private in it — and the proof is the standard one this file already
    # uses: a normal chat as the control (the marker reaches the request but
    # never durable storage either), then the same drive against a private
    # connection, plus the two channels 1.3 adds beyond `messages`: replay
    # and export.
    import export as exportmod
    MARK = "zx-governor-direction-must-not-persist"
    main.stream_response = lambda messages, model=None: (
        "an ordinary answer", {"prompt_tokens": 3, "completion_tokens": 2}, "")

    def _no_marker_anywhere(conn, sid, label):
        rows = conn.execute(
            "SELECT content FROM messages WHERE session_id=?",
            (sid,)).fetchall()
        joined = " ".join(r[0] or "" for r in rows)
        ok(f"{label}: the direction never lands in messages",
           MARK not in joined, joined)
        ok(f"{label}: ...nor in replay",
           all(MARK not in (m.get("content") or "")
              for m in dbmod.load_history(conn, sid)),
           dbmod.load_history(conn, sid))
        ok(f"{label}: the answer itself is still there",
           "an ordinary answer" in joined, joined)

    ooc_script = f"/tools off\n(({MARK}))\n/q\n"

    print("  (control: a normal chat)")
    ctl_sid = dbmod.new_session(real, title="gov-control")
    drive(real, ctl_sid, private=False, keys=ooc_script)
    _no_marker_anywhere(real, ctl_sid, "normal chat")

    vault_tmp = Path(tempfile.mkdtemp())
    saved_vault = exportmod.CHAT_EXPORT_DIR
    exportmod.CHAT_EXPORT_DIR = str(vault_tmp)
    try:
        exportmod.export_session(real, ctl_sid, quiet=True)
        exported_text = "\n".join(
            p.read_text(encoding="utf-8") for p in vault_tmp.glob("*.md"))
        ok("normal chat: the direction never reaches an export either",
           MARK not in exported_text, exported_text)
        ok("...though the answer does", "an ordinary answer" in exported_text,
           exported_text)
    finally:
        exportmod.CHAT_EXPORT_DIR = saved_vault

    print("  (a private chat, driving the identical OOC turn)")
    priv7 = dbmod.db(":memory:")
    p7 = dbmod.new_session(priv7, title="(untitled)")
    drive(priv7, p7, private=True, keys=ooc_script)
    _no_marker_anywhere(priv7, p7, "private chat")
    ok("...and it never reached the real db either",
       MARK not in " ".join(
           r[0] or "" for r in real.execute(
               "SELECT content FROM messages").fetchall()))
    priv7.close()

    print("\n--- W-1.6.4-04: the request capture is private-session-local "
          "too — visible while it's alive, absent from every escape path ---")
    import api
    import json as jsonmod

    MARKER_REQ = "zx-request-capture-marker-9f3"

    class _FakeStreamResponse:
        def __init__(self, content):
            self.is_error = False
            self._lines = [
                "data: " + jsonmod.dumps(
                    {"choices": [{"delta": {"content": content}}]}),
                "data: [DONE]",
            ]

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self):
            return iter(self._lines)

        def read(self):
            pass

    _stream_script = [_FakeStreamResponse("an ordinary private answer")]

    class _FakeHTTPXClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, headers=None, json=None):
            return _stream_script.pop(0)

    # The real stream_response, restored — this file stubs it to a lambda at
    # the top, which never reaches api.py's own payload construction and so
    # never populates the capture at all. Faked one level lower, at
    # httpx.Client, the same technique test_agent.py and test_turn_paths.py
    # use for the same reason.
    real_stream_response = api.stream_response
    real_httpx_client = api.httpx.Client
    main.stream_response = real_stream_response
    api.httpx.Client = _FakeHTTPXClient
    priv9 = dbmod.db(":memory:")
    p9 = dbmod.new_session(priv9, title="(untitled)")
    try:
        out9 = drive(priv9, p9, private=True,
                    keys=f"/tools off\n{MARKER_REQ}\n/status request\n/q\n")
    finally:
        api.httpx.Client = real_httpx_client
    ok("the marker is visible in /status request while the session is alive",
       MARKER_REQ in out9 and "Call 1 of 1" in out9, out9)

    # The marker itself is the ordinary chat text of this turn, so it's
    # *supposed* to land in the private connection's own messages row and in
    # an explicit export of that same session (decision 10/15) — proving its
    # absence there would be proving the wrong thing. What must never reach
    # any of the four surfaces below is the *capture's own rendering* —
    # "Call 1 of", the literal wire-shaped JSON dump `/status request`
    # prints — since nothing else in cfc ever writes that phrase anywhere.
    CAPTURE_MARK = "Call 1 of"
    ok("...but the capture's own rendering never reached the real database",
       CAPTURE_MARK not in " ".join(
           r[0] or "" for r in real.execute(
               "SELECT content FROM messages").fetchall()))
    ok("...nor the private connection's own database (it's a process-local "
       "list, not a row — even the session that produced it never got a "
       "row for it)",
       CAPTURE_MARK not in " ".join(
           r[0] or "" for r in priv9.execute(
               "SELECT content FROM messages").fetchall()))

    vault_tmp9 = Path(tempfile.mkdtemp())
    saved_vault9 = exportmod.CHAT_EXPORT_DIR
    exportmod.CHAT_EXPORT_DIR = str(vault_tmp9)
    try:
        exportmod.export_session(priv9, p9, quiet=True)
        exported9 = "\n".join(
            p.read_text(encoding="utf-8") for p in vault_tmp9.glob("*.md"))
        ok("the marker's own text does reach an explicit export — that "
           "escape hatch is unaffected by this feature",
           MARKER_REQ in exported9, exported9)
        ok("...but the capture's own rendering never does",
           CAPTURE_MARK not in exported9, exported9)
    finally:
        exportmod.CHAT_EXPORT_DIR = saved_vault9

    ok("...nor the error log",
       CAPTURE_MARK not in (errorlog.LOG_PATH.read_text()
                            if errorlog.LOG_PATH.exists() else ""))
    priv9.close()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
