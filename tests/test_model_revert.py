#!/usr/bin/env python3
"""test_model_revert.py — an unverified model that the provider rejects is
backed out of, instead of stranding the session on a dead id. No network.

    python3 tests/test_model_revert.py

`:model X` for an X that isn't in your configured models sets it anyway (MODELS
is not exhaustive), but then persists it — so before this, a nonsense name 400ed
on every turn and survived reopening the session, and you only found out by
running `:models` and not seeing it selected. The fix arms an auto-revert when
switching to an unverified model: the *first* turn that errors on it backs out
to the model you were on. The scope is what makes it non-magical — it is armed
only on a just-set unverified model, so it needs no "is this a model-not-found
400?" string match, and a turn that succeeds disarms it (the model is real), so
a known-good unlisted model never reverts later on a transient hiccup.

Driven through `run_session` with a stubbed stream, the same harness shape as
test_private. `select_model` is stubbed to pass the raw query through (the user
picking an arbitrary id) and `known_models` to a fixed pool, so the arming
decision is what's under test, not the resolver.
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

import httpx

import db as dbmod
import main

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def drive(conn, sid, keys):
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
    assert "tmp" in str(tmp), tmp
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()

    # The resolver is not what's under test: whatever you type, you get it.
    # The pool that decides "verified" is fixed to one known model.
    main.select_model = lambda q: q
    main.known_models = lambda: ["good-model"]
    main.generate_title = lambda *a, **k: "(untitled)"
    main.auto_embed = lambda: None
    # Stay on the streaming path (:tools off) throughout.

    print("\n--- an unverified model that errors is reverted ---")
    sid = dbmod.new_session(conn, title="t", model="good-model")

    def raise_for_bad(messages, model=None):
        if model == "shanhaig":
            raise httpx.HTTPError("no such model: shanhaig")
        return ("an answer", {"prompt_tokens": 1, "completion_tokens": 1}, "")
    main.stream_response = raise_for_bad

    text = drive(conn, sid, "/tools off\n/model shanhaig\nhello\n/model\n/q\n")
    ok("the error names the rejected model and the revert target",
       "provider rejected 'shanhaig'" in text
       and "switched back to good-model" in text, text)
    ok("the raw provider error is NOT shown in its place",
       "no such model: shanhaig" not in text, text)
    ok("the session is left on the reverted model, not the dead id",
       dbmod.get_session_model(conn, sid) == "good-model",
       dbmod.get_session_model(conn, sid))

    print("\n--- no switch means nothing armed, so an error prints raw ---")
    sid2 = dbmod.new_session(conn, title="t2", model="good-model")
    # Arming happens on a *switch*. This session never switched, so there is no
    # previous model to fall back to and a transient prints raw.
    main.stream_response = lambda messages, model=None: (
        (_ for _ in ()).throw(httpx.HTTPError("upstream 503")))
    text2 = drive(conn, sid2, "/tools off\nhello\n/q\n")
    ok("an unswitched session's error is shown raw", "upstream 503" in text2, text2)
    ok("...and does not trigger a revert",
       "switched back" not in text2, text2)
    ok("...and the model is unchanged",
       dbmod.get_session_model(conn, sid2) == "good-model")

    print("\n--- the longcat class: a KNOWN but broken id now reverts ---")
    # The case the revert was built for and used to skip. Arming was gated on
    # `new_model not in known_models()`, so a dead id that IS in your MODELS
    # switched cleanly, armed nothing, and 400ed every turn thereafter with a
    # provider error that never names the model. Dropping longcat from the
    # config removed the instance and left the class; this is the class.
    sid4 = dbmod.new_session(conn, title="t4", model="good-model")
    main.known_models = lambda: ["good-model", "broken-but-listed"]
    main.stream_response = lambda messages, model=None: (
        (_ for _ in ()).throw(httpx.HTTPError("no such model: broken-but-listed")))
    text4 = drive(conn, sid4, "/tools off\n/model broken-but-listed\nhello\n/q\n")
    ok("a listed-but-dead model is reverted",
       "provider rejected 'broken-but-listed'" in text4
       and "switched back to good-model" in text4, text4)
    ok("...and the session is left usable, not stranded",
       dbmod.get_session_model(conn, sid4) == "good-model",
       dbmod.get_session_model(conn, sid4))
    main.known_models = lambda: ["good-model"]

    print("\n--- a first-turn success disarms the revert ---")
    sid3 = dbmod.new_session(conn, title="t3", model="good-model")
    calls = {"n": 0}

    def ok_then_fail(messages, model=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return ("hi", {"prompt_tokens": 1, "completion_tokens": 1}, "")
        raise httpx.HTTPError("upstream 500")
    main.stream_response = ok_then_fail

    # Switch to an unlisted-but-VALID model: turn 1 succeeds (disarms), turn 2
    # errors and must print raw rather than reverting a model that just worked.
    text3 = drive(conn, sid3, "/tools off\n/model custom-x\nhello\nhello\n/q\n")
    ok("a working unlisted model is not reverted on a later error",
       "switched back" not in text3 and "upstream 500" in text3, text3)
    ok("...and stays selected", dbmod.get_session_model(conn, sid3) == "custom-x",
       dbmod.get_session_model(conn, sid3))

    conn.close()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
