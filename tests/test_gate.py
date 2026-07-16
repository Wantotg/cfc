#!/usr/bin/env python3
"""
test_gate.py — the approval gate. No API calls.

    python3 tests/test_gate.py

The property that matters most is the last one: approving a call does not
bypass path_guard. The gate decides whether a call runs; tools.dispatch
decides whether it is allowed. A user can approve a call that then fails
validation, and that is correct.
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import commands
import tools

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def call(name, **args):
    return {"id": "c1", "function": {"name": name, "arguments": json.dumps(args)}}


def drive(fn, *a, keys="", **kw):
    out = io.StringIO()
    real = sys.stdin
    sys.stdin = io.StringIO(keys)
    try:
        with contextlib.redirect_stdout(out):
            commands.console.file = out
            r = fn(*a, **kw)
    finally:
        sys.stdin = real
    return r, out.getvalue()


def is_err(s, contains=None):
    try:
        d = json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return False
    return "error" in d and (contains is None or contains in d["error"])


def main():
    tmp = Path(tempfile.mkdtemp())
    jail = tmp / "projects"
    jail.mkdir(parents=True)
    outside = tmp / "outside"
    outside.mkdir()
    (jail / "notes.md").write_text("alpha\nbeta\n")
    (outside / "secret.txt").write_text("PRIVATE")
    (jail / "config.py").write_text("API_KEY='sk-LEAK'")
    tools.TOOLS_ROOTS = (jail,)

    A = commands.TurnApproval

    print("--- the four keys ---")
    v, out = drive(commands.gate, call("read_file", path=str(jail / "notes.md")),
                   A(), jail, keys="a\n")
    ok("'a' allows", v == "allow", v)
    ok("panel shows the tool name", "read_file" in out, out)
    ok("panel shows the resolved path", "notes.md" in out, out)
    ok("panel shows the size before deciding", "lines," in out, out)

    v, _ = drive(commands.gate, call("read_file", path="x"), A(), jail, keys="d\n")
    ok("'d' denies", v == "deny", v)
    v, _ = drive(commands.gate, call("read_file", path="x"), A(), jail, keys="s\n")
    ok("'s' skips", v == "skip", v)
    v, _ = drive(commands.gate, call("read_file", path="x"), A(), jail, keys="A\n")
    ok("'A' allows", v == "allow", v)

    print("\n--- 'A' allows the rest of the turn, and only this turn ---")
    ap = A()
    v, _ = drive(commands.gate, call("read_file", path="x"), ap, jail, keys="A\n")
    ok("first call allowed", v == "allow")
    ok("allow_all is now set", ap.allow_all)
    # no keys at all: if it prompts, input() raises EOF and we'd get 'deny'
    v, out = drive(commands.gate, call("grep", pattern="x"), ap, jail, keys="")
    ok("second call allowed without prompting", v == "allow", v)
    ok("...and nothing was printed for it", "Tool call" not in out, out)

    fresh = A()
    v, _ = drive(commands.gate, call("grep", pattern="x"), fresh, jail, keys="d\n")
    ok("a new turn prompts again", v == "deny" and not fresh.allow_all)

    print("\n--- auto-approve ---")
    ap = A(auto_approve={"list_dir"})
    v, out = drive(commands.gate, call("list_dir", path=str(jail)), ap, jail, keys="")
    ok("auto-approved tool never prompts", v == "allow", v)
    ok("...and prints no panel", "Tool call" not in out)
    v, _ = drive(commands.gate, call("read_file", path="x"), ap, jail, keys="d\n")
    ok("other tools still gated", v == "deny")

    print("\n--- bad input at the prompt ---")
    v, out = drive(commands.gate, call("read_file", path="x"), A(),
                   jail, keys="q\nzz\na\n")
    ok("re-prompts until valid", v == "allow", v)
    ok("says what's valid", "Type a, d, A or s" in out)
    v, _ = drive(commands.gate, call("read_file", path="x"), A(), jail, keys="")
    ok("EOF at the prompt denies rather than crashes", v == "deny", v)

    print("\n--- denial is data ---")
    r, _ = drive(commands.gate_and_dispatch,
                 call("read_file", path=str(jail / "notes.md")), A(), jail,
                 keys="d\n")
    ok("deny -> {'error': 'user denied'}", is_err(r, "user denied"), r)
    r, _ = drive(commands.gate_and_dispatch,
                 call("read_file", path=str(jail / "notes.md")), A(), jail,
                 keys="s\n")
    ok("skip -> {'error': 'user skipped'}", is_err(r, "user skipped"), r)
    ok("both are strings the model can read", isinstance(r, str))

    r, _ = drive(commands.gate_and_dispatch,
                 call("read_file", path=str(jail / "notes.md")), A(), jail,
                 keys="a\n")
    ok("allow -> the actual result", "alpha" in r, r)

    print("\n--- approving does NOT bypass path_guard ---")
    # The load-bearing one. The user says yes; the guard still says no.
    r, _ = drive(commands.gate_and_dispatch,
                 call("read_file", path=str(outside / "secret.txt")), A(), jail,
                 keys="a\n")
    ok("approved call outside the root is still refused",
       is_err(r, "outside"), r)
    ok("...and the secret never appears", "PRIVATE" not in r)

    r, _ = drive(commands.gate_and_dispatch,
                 call("read_file", path=str(jail / "config.py")), A(), jail,
                 keys="a\n")
    ok("approved read of config.py is still refused", is_err(r, "deny list"), r)
    ok("...and the key never appears", "sk-LEAK" not in r)

    ap = A(auto_approve={"read_file"})
    r, _ = drive(commands.gate_and_dispatch,
                 call("read_file", path=str(outside / "secret.txt")), ap, jail,
                 keys="")
    ok("auto-approve doesn't bypass the guard either", is_err(r, "outside"), r)

    print("\n--- unknown tools and junk still gate cleanly ---")
    r, _ = drive(commands.gate_and_dispatch,
                 {"function": {"name": "rm_rf", "arguments": "{}"}}, A(), jail,
                 keys="a\n")
    ok("unknown tool -> error, not a crash", is_err(r, "unknown tool"), r)
    v, out = drive(commands.gate,
                   {"function": {"name": "read_file", "arguments": "{oops"}},
                   A(), jail, keys="a\n")
    ok("unparseable args still render a panel", v == "allow" and "unparseable" in out,
       out)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
