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

    script = ":tools off\nhello\n:q\n"

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

    print("\n--- but an explicit :export is still honoured ---")
    priv2 = dbmod.db(":memory:")
    p2 = dbmod.new_session(priv2, title="(untitled)")
    exports.clear()
    # export_session is the explicit path (not safe_export); spy on it too.
    calls = []
    main.export_session = lambda conn, target, quiet=False: calls.append(target)
    drive(priv2, p2, private=True, keys=":tools off\nhello\n:export\n:q\n")
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

    r, out = recall_run(True, ":recall who is cas\n:q\n", db_active=False)
    ok("a private chat seals recall by default", r == [], r)
    ok("...and says the database is off", "Database is off" in out, out[-200:])

    r, _ = recall_run(True, ":database on\n:recall who is cas\n:q\n",
                      db_active=False)
    ok(":database on opens recall in a private chat", r == ["who is cas"], r)

    r, _ = recall_run(True, ":recall who is cas\n:q\n", db_active=True)
    ok("DATABASE_ACTIVE=True lets a private chat recall from the start",
       r == ["who is cas"], r)

    r, _ = recall_run(False, ":recall who is cas\n:q\n")
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

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
