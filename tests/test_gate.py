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

import inspect

import commands
import config
import tools
from context import ToolContext

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
    outbox = tmp / "outbox"
    outbox.mkdir()
    tools.TOOLS_ROOTS = (jail,)

    # The read jail and the write jail are deliberately different folders:
    # every "can read but not write" assertion below depends on that.
    chat_ctx = ToolContext.for_chat(read_roots=(jail,), write_roots=(outbox,))

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

    print("\n--- there is no per-tool auto-approve, by construction ---")
    # The property Cas asked for: no config line can pre-clear a tool in a
    # normal chat. TurnApproval takes no auto-approve argument any more, and
    # config exposes nothing to feed it.
    ok("TurnApproval takes no auto_approve argument",
       "auto_approve" not in inspect.signature(A.__init__).parameters)
    ok("config exposes no TOOLS_AUTO_APPROVE",
       not hasattr(config, "TOOLS_AUTO_APPROVE"))
    ok("commands exposes no TOOLS_AUTO_APPROVE",
       not hasattr(commands, "TOOLS_AUTO_APPROVE"))
    # keys="" means an empty stdin: anything that prompts comes back "deny".
    v, out = drive(commands.gate, call("list_dir", path=str(jail)), A(),
                   chat_ctx, keys="")
    ok("an ordinary tool is still gated in chat", v == "deny", v)
    ok("...and the panel was shown", "Tool call" in out)

    print("\n--- a chat context cannot be made ungated ---")
    ok("for_chat is gated", chat_ctx.gated)
    try:
        chat_ctx.gated = False
        ok("gated has no setter", False)
    except AttributeError:
        ok("gated has no setter", True)
    ok("...still gated after the attempt", chat_ctx.gated)

    print("\n--- an ungated context is only reachable via for_routine ---")
    rt = ToolContext.for_routine("nightly", read_roots=(jail,),
                                 write_roots=(outbox,))
    ok("for_routine is ungated", not rt.gated)
    v, out = drive(commands.gate, call("read_file", path=str(jail / "notes.md")),
                   A(), rt, keys="")
    ok("a routine call is not prompted", v == "allow", v)
    ok("...and no panel is shown", "Tool call" not in out, out)
    # The load-bearing half: ungated does NOT mean unguarded. Its roots are the
    # only guardrail left, so they had better still hold.
    r, _ = drive(commands.gate_and_dispatch,
                 call("read_file", path=str(outside / "secret.txt")), A(), rt,
                 keys="")
    ok("an ungated routine is still bound by its roots", is_err(r, "outside"), r)
    ok("...and the secret never appears", "PRIVATE" not in r)
    r, _ = drive(commands.gate_and_dispatch,
                 call("read_file", path=str(jail / "config.py")), A(), rt,
                 keys="")
    ok("...and by the deny list", is_err(r, "deny list"), r)

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

    print("\n--- writes: always prompted, never covered by allow-all ---")
    ap = A()
    ap.allow_all = True
    v, out = drive(commands.gate, call("write_file", path=str(outbox / "a.md"),
                                       content="hi"), ap, chat_ctx, keys="a\n")
    ok("'A' does not pre-approve a write", "Tool call" in out, out)
    ok("...the write still had to be allowed by hand", v == "allow", v)
    ok("...and the panel says WRITE", "WRITE" in out, out)
    ok("...and does not offer [A]", "[A]llow all" not in out, out)

    v, out = drive(commands.gate, call("write_file", path=str(outbox / "a.md"),
                                       content="hi"), A(), chat_ctx, keys="A\na\n")
    ok("typing 'A' at a write prompt is not accepted",
       "Type a, d or s" in out, out)

    print("\n--- writes go to the write roots, not the read roots ---")
    r, _ = drive(commands.gate_and_dispatch,
                 call("write_file", path=str(outbox / "note.md"),
                      content="hello\n"), A(), chat_ctx, keys="a\n")
    ok("a write inside the write root succeeds", "wrote" in r, r)
    ok("...and the file is really there",
       (outbox / "note.md").read_text() == "hello\n")

    # The split, stated as a test: readable is not writable.
    r, out = drive(commands.gate_and_dispatch,
                   call("write_file", path=str(jail / "evil.md"),
                        content="x"), A(), chat_ctx, keys="")
    ok("a write into the READ root is refused", is_err(r, "outside"), r)
    ok("...auto-denied, the user was never asked", "[a]llow" not in out, out)
    ok("...and nothing was created", not (jail / "evil.md").exists())

    r, _ = drive(commands.gate_and_dispatch,
                 call("write_file", path=str(outside / "evil.md"),
                      content="x"), A(), chat_ctx, keys="a\n")
    ok("an approved write outside every root is still refused",
       is_err(r, "outside"), r)
    ok("...and nothing was created", not (outside / "evil.md").exists())

    print("\n--- overwrite is an explicit capability ---")
    r, _ = drive(commands.gate_and_dispatch,
                 call("write_file", path=str(outbox / "note.md"),
                      content="clobbered"), A(), chat_ctx, keys="a\n")
    ok("writing over an existing file is refused by default",
       is_err(r, "already exists"), r)
    ok("...and the original is intact",
       (outbox / "note.md").read_text() == "hello\n")
    r, _ = drive(commands.gate_and_dispatch,
                 call("write_file", path=str(outbox / "note.md"),
                      content="clobbered", overwrite=True), A(), chat_ctx,
                 keys="a\n")
    ok("overwrite=true replaces it", "replaced" in r, r)
    ok("...and the content changed",
       (outbox / "note.md").read_text() == "clobbered")

    print("\n--- a context with no write scope fails closed ---")
    ro = ToolContext.for_chat(read_roots=(jail,))
    r, out = drive(commands.gate_and_dispatch,
                   call("write_file", path=str(outbox / "b.md"), content="x"),
                   A(), ro, keys="")
    ok("write refused when no write roots are configured",
       is_err(r, "writing is not enabled"), r)
    ok("...without prompting", "[a]llow" not in out, out)
    ok("...and nothing was created", not (outbox / "b.md").exists())

    print("\n--- doomed calls are auto-refused without ever prompting ---")
    # keys="" means stdin is empty: if the gate asked anything, input() raises
    # EOFError and the result comes back as "user denied". Getting the *guard's*
    # reason instead proves no prompt was shown.
    r, out = drive(commands.gate_and_dispatch,
                   call("read_file", path=str(jail / "config.py")), A(), jail,
                   keys="")
    ok("read of config.py auto-denied, no prompt",
       is_err(r, "deny list"), r)
    ok("...the user was not asked", "[a]llow" not in out, out)
    ok("...but it is reported, not silent", "auto-denied" in out, out)
    ok("...and the key never appears", "sk-LEAK" not in r)

    r, out = drive(commands.gate_and_dispatch,
                   call("list_dir", path=str(outside)), A(), jail, keys="")
    ok("listing outside the roots auto-denied, no prompt",
       is_err(r, "outside"), r)
    ok("...the user was not asked", "[a]llow" not in out, out)

    # The pre-filter must not swallow legitimate calls: an allowed path still
    # reaches the human. Deny it by hand to prove the prompt happened.
    r, out = drive(commands.gate_and_dispatch,
                   call("read_file", path=str(jail / "notes.md")), A(), jail,
                   keys="d\n")
    ok("an allowed path is still gated by the human", "[a]llow" in out, out)
    ok("...and 'd' reads as the user's own denial",
       is_err(r, "user denied"), r)

    print("\n--- list_dir hides denied entries rather than listing them ---")
    listing = tools.list_dir(str(jail), jail)
    ok("config.py absent from the listing", "config.py" not in listing, listing)
    ok("...while ordinary files remain", "notes.md" in listing, listing)

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
