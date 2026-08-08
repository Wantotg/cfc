#!/usr/bin/env python3
"""test_model_revert.py — a model switch that the provider rejects is backed
out of, instead of stranding the session on a dead id. No network.

    python3 tests/test_model_revert.py

`/model X` sets whatever you type, verified or not (MODELS is not exhaustive),
then persists it — so before this, a nonsense name 400ed on every turn and
survived reopening the session, and you only found out by running `/list
models` and not seeing it selected. The fix arms an auto-revert on **every**
switch: the *first* turn that errors on the new model backs out to the model
you were on, unless that error is a status-coded transient (429/502/503/504,
`W-1.1-03`) — a provider hiccup doesn't mean the id is dead, so it leaves the
new model selected and the revert still armed for a following failure. A turn
that succeeds disarms it (the model is real), so a known-good model never
reverts later on a transient hiccup either.

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
import models

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def drive(conn, sid, keys, model=None):
    """Run one session. `model` sets the process-wide selection
    (W-1.3.1-03) before driving — a reopened session no longer reads its own
    stored `model` column, so every scenario in this file that used to rely
    on `new_session(..., model=X)` to choose its starting model now has to
    say so here instead."""
    if model is not None:
        main.set_process_model(model)
    out = io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(keys)
    saved_file = main.console._file
    try:
        with contextlib.redirect_stdout(out):
            main.console.file = out
            main.run_session(conn, sid, auto_export=False, private=False)
    finally:
        sys.stdin = real_stdin
        main.console.file = saved_file
    return out.getvalue()


def main_():
    tmp = Path(tempfile.mkdtemp())
    assert "tmp" in str(tmp), tmp
    dbmod.DB_PATH = tmp / "chat.db"

    # This file drives the real `run_session`, so the four fabricated provider
    # errors below reach `errorlog.log_error` unpatched — and that writes to the
    # live `~/.cfc/errors.log`, which is the whole of `B-01`'s evidence. One of
    # that bug's closing routes is *absence across the 0.9 → 1.0 window*, so a
    # test run drops convincing provider errors inside the window somebody will
    # read to decide whether the bug came back. The watcher poisoning the thing
    # it watches.
    #
    # **The assertion is the durable half, not the redirect.** A redirect that
    # gets refactored away is silent; the assertion is what makes it loud. Same
    # pattern and same wording as `tests/test_private.py`.
    import errorlog
    errorlog.LOG_PATH = tmp / "errors.log"
    assert "tmp" in str(errorlog.LOG_PATH), "refusing to touch the real log"

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

    text = drive(conn, sid, "/tools off\n/model shanhaig\nhello\n/model\n/q\n",
                model="good-model")
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
    text2 = drive(conn, sid2, "/tools off\nhello\n/q\n", model="good-model")
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
    text4 = drive(conn, sid4, "/tools off\n/model broken-but-listed\nhello\n/q\n",
                 model="good-model")
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
    text3 = drive(conn, sid3, "/tools off\n/model custom-x\nhello\nhello\n/q\n",
                 model="good-model")
    ok("a working unlisted model is not reverted on a later error",
       "switched back" not in text3 and "upstream 500" in text3, text3)
    ok("...and stays selected", dbmod.get_session_model(conn, sid3) == "custom-x",
       dbmod.get_session_model(conn, sid3))

    print("\n--- a status-coded transient right after a switch does not revert "
          "(W-1.1-03) ---")
    sid5 = dbmod.new_session(conn, title="t5", model="good-model")
    calls5 = {"n": 0}

    def transient_then_rejected(messages, model=None):
        calls5["n"] += 1
        if calls5["n"] == 1:
            error = httpx.HTTPError("upstream 503")
            error.status_code = 503
            raise error
        raise httpx.HTTPError("no such model: flaky-model")
    main.stream_response = transient_then_rejected

    text5 = drive(conn, sid5, "/tools off\n/model flaky-model\nhello\nhello\n/q\n",
                 model="good-model")
    ok("the transient prints as an ordinary error", "upstream 503" in text5,
       text5)
    ok("...and the revert stays armed, so the SECOND error still reverts",
       "provider rejected 'flaky-model'" in text5
       and "switched back to good-model" in text5, text5)
    ok("...in that order: the transient did not revert before the rejection did",
       text5.index("upstream 503") < text5.index("switched back to good-model"),
       text5)
    ok("...and the session ends on the reverted model, not the dead id",
       dbmod.get_session_model(conn, sid5) == "good-model",
       dbmod.get_session_model(conn, sid5))

    print("\n--- /model <n> picks straight off the displayed list (W-1.1-10) ---")
    # model_by_number is the pure lookup under test in test_model.py; here the
    # session-level claim is what matters — a valid number switches and
    # persists with no second picker, and an invalid one leaves the model
    # alone with its own message rather than falling through to select_model.
    main.model_by_number = lambda n: {1: "good-model", 2: "custom-y"}.get(n)

    sid6 = dbmod.new_session(conn, title="t6", model="good-model")
    main.stream_response = lambda messages, model=None: (
        "an answer", {"prompt_tokens": 1, "completion_tokens": 1}, "")
    text6 = drive(conn, sid6, "/tools off\n/model 2\n/model\n/q\n",
                 model="good-model")
    ok("a valid number switches to the full configured id",
       "Switched to model: custom-y" in text6, text6)
    ok("...with no numbered picker in between",
       "matches" not in text6 and "pick a number" not in text6, text6)
    ok("...and the choice persists",
       dbmod.get_session_model(conn, sid6) == "custom-y",
       dbmod.get_session_model(conn, sid6))

    sid7 = dbmod.new_session(conn, title="t7", model="good-model")
    text7 = drive(conn, sid7, "/tools off\n/model 9\n/model\n/q\n",
                  model="good-model")
    ok("an out-of-range number explains digits pick a row and points at "
       "/list models",
       "doesn't pick a row" in text7 and "/list models" in text7
       and "Switched to model" not in text7, text7)
    ok("...and zero is treated the same way",
       "doesn't pick a row" in
       drive(conn, dbmod.new_session(conn, title="t8", model="good-model"),
             "/tools off\n/model 0\n/q\n", model="good-model"))
    ok("...and the session stays on the model it started with",
       dbmod.get_session_model(conn, sid7) == "good-model",
       dbmod.get_session_model(conn, sid7))

    print("\n--- B-1.2-04: a revert never lands on a model the provider "
          "already rejected ---")
    # The bug: 'flaky-a' 400s once (recorded as rejected; reverts cleanly to
    # good-model, which was never rejected) and then SUCCEEDS on a second try
    # — a real shape (a flaky endpoint, or a model the provider briefly
    # doesn't serve). Switching from flaky-a to 'flaky-b', which 400s, arms a
    # revert back to flaky-a — exactly the model already proven dead this
    # session, regardless of its one later success. `revert_bad_model` must
    # refuse instead of reporting that as a recovery.
    def make_reject_a_once_then_b():
        # A fresh counter per scenario run — `drive_ab_scenario` is called
        # twice (normal chat, then private), and a shared counter would let
        # the second run's flaky-a skip straight to "already succeeded once",
        # never 400ing there at all and silently testing nothing.
        calls = {"a": 0}

        def stub(messages, model=None):
            if model == "flaky-a":
                calls["a"] += 1
                if calls["a"] == 1:
                    e = httpx.HTTPError("no such model: flaky-a")
                    e.status_code = 400
                    raise e
                return ("recovered", {"prompt_tokens": 1, "completion_tokens": 1}, "")
            if model == "flaky-b":
                e = httpx.HTTPError("no such model: flaky-b")
                e.status_code = 400
                raise e
            return ("an answer", {"prompt_tokens": 1, "completion_tokens": 1}, "")
        return stub

    def drive_ab_scenario(conn_, model_start, title):
        main.stream_response = make_reject_a_once_then_b()
        sid_ = dbmod.new_session(conn_, title=title, model=model_start)
        return sid_, drive(conn_, sid_,
                          "/tools off\n"
                          "/model flaky-a\nhello\n"        # 400 -> reverts
                          "/model flaky-a\nhello\n"        # succeeds
                          "/model flaky-b\nhello\n/q\n",    # 400 -> would
                                                              # revert onto
                                                              # flaky-a
                          model=model_start)

    sid9, text9 = drive_ab_scenario(conn, "good-model", "t9")
    ok("the first flaky-a 400 reverts normally",
       "provider rejected 'flaky-a' — switched back to good-model" in text9,
       text9)
    # The stub renders nothing on success (that's `stream_response`'s own
    # job, bypassed by the stub) — a clean retry shows up as *no* error
    # between the second switch and the next one, not as visible text.
    retry_segment = text9.split("Switched to model: flaky-a")[2].split(
        "Switched to model: flaky-b")[0]
    ok("the second flaky-a turn succeeds — no error, no revert",
       "[error]" not in retry_segment, retry_segment)
    ok("flaky-b's 400 refuses to revert onto flaky-a despite its "
       "later success",
       "flaky-b was rejected too" in text9
       and "flaky-a" in text9.split("flaky-b was rejected too")[1][:160],
       text9)
    ok("...names neither id as known-good",
       "switched back to flaky-a" not in text9, text9)
    ok("...and points at /model as the next step",
       "pick a different model with" in text9 and "/model" in text9, text9)
    ok("...and the session is left on flaky-b, not silently reverted",
       dbmod.get_session_model(conn, sid9) == "flaky-b",
       dbmod.get_session_model(conn, sid9))

    print("\n--- B-1.2-04: same, on the tool-calling path ---")
    saved_tools_enabled, saved_supports = main.TOOLS_ENABLED, models.supports_tools
    main.TOOLS_ENABLED = True
    models.supports_tools = lambda m: True
    calls_tools = {"a": 0}

    def reject_a_once_then_b_tools(prefix, history, model, conn, session_id,
                                   ctx=None, max_calls=None, touched=None,
                                   first_message=None, instruction=None):
        if model == "flaky-a":
            calls_tools["a"] += 1
            if calls_tools["a"] == 1:
                e = httpx.HTTPError("no such model: flaky-a")
                e.status_code = 400
                raise e
            return {"content": "recovered"}
        if model == "flaky-b":
            e = httpx.HTTPError("no such model: flaky-b")
            e.status_code = 400
            raise e
        return {"content": "an answer"}
    main.agent_turn = reject_a_once_then_b_tools

    try:
        sid10 = dbmod.new_session(conn, title="t10", model="good-model")
        text10 = drive(conn, sid10,
                       "/model flaky-a\nhello\n"
                       "/model flaky-a\nhello\n"
                       "/model flaky-b\nhello\n/q\n",
                       model="good-model")
        ok("tool path: the first flaky-a 400 reverts normally",
           "provider rejected 'flaky-a' — switched back to good-model"
           in text10, text10)
        ok("tool path: the later success doesn't save flaky-a from a "
           "refusal",
           "flaky-b was rejected too" in text10
           and "switched back to flaky-a" not in text10, text10)
        ok("tool path: the session is left on flaky-b",
           dbmod.get_session_model(conn, sid10) == "flaky-b",
           dbmod.get_session_model(conn, sid10))
    finally:
        main.TOOLS_ENABLED = saved_tools_enabled
        models.supports_tools = saved_supports

    print("\n--- B-1.2-04: a private chat carries the same in-memory "
          "refusal set ---")
    # `run_session` builds `rejected_models` fresh per call, never off disk —
    # a private chat's throwaway `conn` carries it exactly the same way. Same
    # scenario, driven through a `:memory:` connection instead of the picker,
    # which private chats don't use.
    priv_conn = dbmod.db(":memory:")
    sid_priv, text_priv = drive_ab_scenario(priv_conn, "good-model", "p")
    priv_conn.close()
    ok("a private chat refuses the same way as a normal one",
       "flaky-b was rejected too" in text_priv
       and "switched back to flaky-a" not in text_priv, text_priv)

    print("\n--- B-1.2-04: a transient status does not poison the set ---")
    # 'flaky-c' 503s (transient) rather than 400s — must NOT be recorded as
    # rejected, so a later switch that lands back on it still reverts
    # normally instead of refusing.
    def transient_c_then_reject_d(messages, model=None):
        if model == "flaky-c":
            e = httpx.HTTPError("upstream 503")
            e.status_code = 503
            raise e
        if model == "flaky-d":
            e = httpx.HTTPError("no such model: flaky-d")
            e.status_code = 400
            raise e
        return ("an answer", {"prompt_tokens": 1, "completion_tokens": 1}, "")
    main.stream_response = transient_c_then_reject_d

    sid12 = dbmod.new_session(conn, title="t12", model="flaky-c")
    # No switch yet, so nothing is armed — the transient prints raw and does
    # NOT get added to rejected_models (status 503, not 400).
    drive(conn, sid12, "/tools off\nhello\n/q\n", model="flaky-c")

    sid13 = dbmod.new_session(conn, title="t13", model="good-model")
    text13 = drive(conn, sid13,
                   "/tools off\n/model flaky-c\nhello\n/model flaky-d\n"
                   "hello\n/q\n", model="good-model")
    ok("switching onto flaky-c and it 503ing again does not revert "
       "(no armed switch reached a 400 yet)",
       "upstream 503" in text13.split("flaky-d")[0], text13)
    ok("flaky-d's 400 reverts cleanly onto flaky-c — the 503 never "
       "poisoned it",
       "provider rejected 'flaky-d' — switched back to flaky-c" in text13,
       text13)

    print("\n--- W-1.1-02: a 500 doesn't poison the set either, even "
          "though it isn't in TRANSIENT_STATUS_CODES ---")
    # 'flaky-e' 500s — not one of the four transient codes, so a routine
    # would not retry it — but it is still the provider's own failure, not
    # evidence the id is bad, so it must behave exactly like flaky-c's 503
    # above: no revert, and the armed switch survives for a real 400 later.
    def server_error_e_then_reject_f(messages, model=None):
        if model == "flaky-e":
            e = httpx.HTTPError("upstream 500")
            e.status_code = 500
            raise e
        if model == "flaky-f":
            e = httpx.HTTPError("no such model: flaky-f")
            e.status_code = 400
            raise e
        return ("an answer", {"prompt_tokens": 1, "completion_tokens": 1}, "")
    main.stream_response = server_error_e_then_reject_f

    sid13b = dbmod.new_session(conn, title="t13b", model="good-model")
    text13b = drive(conn, sid13b,
                    "/tools off\n/model flaky-e\nhello\n/model flaky-f\n"
                    "hello\n/q\n", model="good-model")
    ok("switching onto flaky-e and it 500ing does not revert",
       "upstream 500" in text13b.split("flaky-f")[0], text13b)
    ok("...and does not print 'provider rejected' either",
       "provider rejected 'flaky-e'" not in text13b, text13b)
    ok("flaky-f's 400 reverts cleanly onto flaky-e — the 500 never "
       "poisoned it, same as the transient case above",
       "provider rejected 'flaky-f' — switched back to flaky-e" in text13b,
       text13b)

    print("\n--- W-08: a suspicious multiple-slash id arms and reverts "
          "exactly like any other — the warning is cosmetic ---")
    def raise_for_suspicious(messages, model=None):
        if model == "vendor/typo/concatenated":
            raise httpx.HTTPError("no such model: vendor/typo/concatenated")
        return ("an answer", {"prompt_tokens": 1, "completion_tokens": 1}, "")
    main.stream_response = raise_for_suspicious
    sid14 = dbmod.new_session(conn, title="t14", model="good-model")
    text14 = drive(conn, sid14,
                   "/tools off\n/model vendor/typo/concatenated\nhello\n"
                   "/model\n/q\n", model="good-model")
    ok("the suspicious-shaped id is accepted by the switch, not refused",
       "provider rejected 'vendor/typo/concatenated'" in text14
       and "switched back to" in text14 and "good-model" in text14, text14)
    ok("the session ends back on the known-good model",
       dbmod.get_session_model(conn, sid14) == "good-model",
       dbmod.get_session_model(conn, sid14))

    conn.close()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
