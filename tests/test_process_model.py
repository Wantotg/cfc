#!/usr/bin/env python3
"""test_process_model.py — one selected model for cfc's whole run
(W-1.3.1-03), not one per session. No network.

    python3 tests/test_process_model.py

Before this, `run_session` read a session's own stored `model` column at
open — so leaving one chat for another (or back) could silently change what
"the selected model" meant. This is the boundary this file drives:
`/model`'s selection has to survive `/q`, `/new`, reopening a *different*
existing session, a private side trip (in either direction — a switch made
inside it carries back out), and a round trip through a command screen. A
fresh process always starts at configured `MODEL`.
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

import db as dbmod
import main

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def drive(conn, sid, keys, private=False, app_conn=None):
    out = io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(keys)
    saved_file = main.console._file
    try:
        with contextlib.redirect_stdout(out):
            main.console.file = out
            outcome = main.run_session(conn, sid, auto_export=False,
                                       private=private, app_conn=app_conn)
    finally:
        sys.stdin = real_stdin
        main.console.file = saved_file
    return out.getvalue(), outcome


def main_():
    tmp = Path(tempfile.mkdtemp())
    assert "tmp" in str(tmp), "refusing to touch a real db"
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()

    main.stream_response = lambda messages, model=None: (
        "an answer", {"prompt_tokens": 1, "completion_tokens": 1}, "")
    main.generate_title = lambda *a, **k: "(untitled)"
    main.auto_embed = lambda: None
    main.safe_export = lambda *a, **k: None
    main.select_model = lambda q: q       # whatever's typed, verbatim
    main.known_models = lambda: []        # nothing configured to match against

    print("--- a fresh process starts at configured MODEL ---")
    ok("current_process_model() is main.MODEL before anything switches",
       main.current_process_model() == main.MODEL,
       (main.current_process_model(), main.MODEL))

    print("\n--- /model persists across /q and a reopen ---")
    sid_a = dbmod.new_session(conn, title="a", model="old-model-on-a")
    out, _ = drive(conn, sid_a, "/tools off\n/model switched-1\n/q\n")
    ok("the switch is confirmed", "Switched to model: switched-1" in out, out)
    ok("the process now carries it",
       main.current_process_model() == "switched-1",
       main.current_process_model())

    out2, _ = drive(conn, sid_a, "/tools off\n/status\n/q\n")
    ok("reopening the SAME session starts on the switched model",
       "switched-1" in out2.split("\n")[1], out2[:200])

    print("\n--- reopening a DIFFERENT existing session ignores its own "
          "stored model ---")
    sid_b = dbmod.new_session(conn, title="b", model="old-model-on-b")
    out3, _ = drive(conn, sid_b, "/tools off\n/status\n/q\n")
    ok("session b opens on the process model, not the one it was created "
       "with", "switched-1" in out3 and "old-model-on-b" not in out3, out3)

    print("\n--- /new does not reset it ---")
    out4, _ = drive(conn, sid_b, "/tools off\n/new\n/status\n/q\n")
    ok("a fresh /new session still opens on the process model",
       out4.count("switched-1") >= 2, out4)

    print("\n--- a nested private chat's switch carries back out ---")
    out5, _ = drive(conn, sid_b,
                    "/tools off\n/new p\n/tools off\nswitch me\n"
                    "/model switched-2\n/q\n/status\n/q\n")
    ok("the private side trip is entered and left",
       "Private session" in out5, out5)
    ok("the outer session sees the private chat's switch after it returns",
       "switched-2" in out5.split("Private session")[-1], out5)
    ok("the process now carries the private chat's choice",
       main.current_process_model() == "switched-2",
       main.current_process_model())

    print("\n--- the hub's own private branch: same carry, the other "
          "direction ---")
    # repl()'s 'p' path hands run_session an isolated priv connection and,
    # separately, the durable app_conn — simulated here the same way
    # tests/test_private.py drives it, without going through repl() itself.
    priv = dbmod.db(":memory:")
    out6, outcome6 = drive(priv, dbmod.new_session(priv), "/model switched-3\n"
                           "/q\n", private=True, app_conn=conn)
    priv.close()
    ok("the private chat's own switch is process-wide too",
       main.current_process_model() == "switched-3",
       main.current_process_model())
    sid_c = dbmod.new_session(conn, title="c", model="old-model-on-c")
    out7, _ = drive(conn, sid_c, "/tools off\n/status\n/q\n")
    ok("a durable chat opened AFTER a private switch sees it",
       "switched-3" in out7, out7)

    print("\n--- a round trip through a command screen preserves it ---")
    out8, outcome8 = drive(conn, sid_c,
                           "/tools off\n/model switched-4\n/config\nq\n/q\n")
    ok("the screen was entered and left back to the chat",
       "config" in out8.lower(), out8[-2000:])
    ok("the model switched before the screen trip is still current after it",
       main.current_process_model() == "switched-4",
       main.current_process_model())
    sid_d = dbmod.new_session(conn, title="d", model="old-model-on-d")
    out9, _ = drive(conn, sid_d, "/tools off\n/status\n/q\n")
    ok("a chat opened after the screen round trip carries the same model",
       "switched-4" in out9, out9)

    conn.close()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
