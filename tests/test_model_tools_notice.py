#!/usr/bin/env python3
"""test_model_tools_notice.py — `/model` says immediately when the model it
switches to can't use tools (`W-1.3.1-01`). No network.

    python3 tests/test_model_tools_notice.py

Before this, the header and `/tools` both knew a model couldn't use tools,
but `/model` — the one command that actually changes which model is active —
said nothing, so the first sign was a *later* turn quietly not offering
tools. The fix reuses `commands.tools_unsupported_reason`, the same seam the
header and `/tools on` already read, rather than adding a second capability
list — pinned here by comparing the two against each other, not against a
literal string.
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

import commands
import db as dbmod
import main
import models

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def drive(conn, sid, keys, model=None):
    if model is not None:
        main.set_process_model(model)
    out = io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(keys)
    try:
        with contextlib.redirect_stdout(out):
            main.console.file = out
            main.run_session(conn, sid, private=False)
    finally:
        sys.stdin = real_stdin
        main.console.file = sys.stdout
    return out.getvalue()


def main_():
    tmp = Path(tempfile.mkdtemp())
    assert "tmp" in str(tmp), "refusing to touch a real db"
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()

    main.select_model = lambda q: q
    main.known_models = lambda: ["tool-model", "plain-model"]
    models.MODELS = [
        models._spec("tool-model", tools=True, limit=100_000),
        models._spec("plain-model", tools=False, limit=100_000),
    ]

    print("--- switching to a non-tool-capable model says so immediately ---")
    main.TOOLS_ENABLED = True
    sid = dbmod.new_session(conn, title="t")
    out = drive(conn, sid, "/model plain-model\n/q\n", model="tool-model")
    reason = commands.tools_unsupported_reason("plain-model")
    ok("the switch confirms", "Switched to model: plain-model" in out, out)
    ok("the notice reuses tools_unsupported_reason verbatim, not a copy",
       reason in out, (reason, out))
    ok("...and names it as a Note", f"Note: {reason}" in out, out)

    print("\n--- switching to a tool-capable model says nothing extra ---")
    sid2 = dbmod.new_session(conn, title="t2")
    out2 = drive(conn, sid2, "/model tool-model\n/q\n", model="plain-model")
    ok("the switch confirms", "Switched to model: tool-model" in out2, out2)
    ok("no tools note is printed", "Note:" not in out2, out2)

    print("\n--- tools already off for this session: nothing new to say ---")
    sid3 = dbmod.new_session(conn, title="t3")
    out3 = drive(conn, sid3, "/tools off\n/model plain-model\n/q\n",
                model="tool-model")
    ok("the switch confirms", "Switched to model: plain-model" in out3, out3)
    ok("no /model-triggered note — /tools off already said the session's "
       "own state", "Note:" not in out3, out3)

    print("\n--- TOOLS_ENABLED off globally: nothing new to say either ---")
    main.TOOLS_ENABLED = False
    sid4 = dbmod.new_session(conn, title="t4")
    out4 = drive(conn, sid4, "/model plain-model\n/q\n", model="tool-model")
    ok("the switch confirms", "Switched to model: plain-model" in out4, out4)
    ok("no note when tools are off for the whole deployment",
       "Note:" not in out4, out4)
    main.TOOLS_ENABLED = True

    print("\n--- the notice names the configured tool-capable choices ---")
    sid5 = dbmod.new_session(conn, title="t5")
    out5 = drive(conn, sid5, "/model plain-model\n/q\n", model="tool-model")
    ok("the same choices tools_unsupported_reason would name are present",
       "tool-model" in out5.split("Note:")[1], out5)

    conn.close()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
