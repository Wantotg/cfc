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
            main.run_session(conn, sid, private=private)
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
    main.AUTO_EXPORT = True   # force the control's export path on, deterministically

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
    drive(priv, priv_sid, private=True, keys=script)
    ok("the conversation is live in the private db",
       count_msgs(priv) >= 2, count_msgs(priv))
    ok("the real db is untouched", count_msgs(real) == before,
       (before, count_msgs(real)))
    ok("auto-embed is skipped", embeds == [], embeds)
    ok("auto-export is skipped on :q", exports == [], exports)
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
    ok("...and log_error refuses it at the write, not at the call site",
       errorlog.log_error(Exception(SECRET), session_id=1, private=True) is False)

    # The launch line is what makes an empty log mean "never written" rather
    # than "no errors" — the distinction the whole absence-watch rests on.
    ok("a launch line is written outside any session", errorlog.log_launch() is True)
    ok("...and logging never raises, whatever the path is",
       _never_raises(errorlog))

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

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
