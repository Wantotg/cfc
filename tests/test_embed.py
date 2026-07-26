#!/usr/bin/env python3
"""
test_embed.py — the embedding call's timeouts and retry budgets. No network.

    python3 tests/test_embed.py

This exists because of a four-minute hang. `/recall` with LM Studio's server
off sat on a spinner for ~240s before failing: `_post` passed a single
`timeout=60` to httpx, which sets *connect*, *read*, *write* and *pool* alike,
so every one of four attempts waited out the full read budget just to discover
that nothing was listening.

Two things are pinned here, and they are the fix:

  1. **The two timeouts are different numbers.** Connect answers "is anything
     there" and read answers "is it finished yet"; a 100-chunk batch or a cold
     model load legitimately needs the long one, and collapsing them back into
     one value is how the hang returns. The assertion is on the *pair*, not on
     either number, so retuning stays free and merging does not.
  2. **A refused connection is not retried like a busy server.** 429/503 is a
     transient and waiting is the right answer; nothing listening on the port
     is a state, and asking four times gets the same answer four times.

httpx is faked wholesale rather than pointed at a closed port: the real thing
would make this suite take eleven seconds and behave differently depending on
whether the OS refuses or drops. What is being tested is the classification,
which is ours.
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


# --- the fake provider ------------------------------------------------------

class _HTTPError(Exception):
    pass


class _ConnectError(_HTTPError):
    pass


class _ConnectTimeout(_HTTPError):
    pass


class _Response:
    def __init__(self, status, payload=None):
        self.status_code = status
        self.text = "upstream said no"
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise _HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeHttpx:
    """Enough httpx to drive `_post`, and a log of how it was called."""
    HTTPError = _HTTPError
    ConnectError = _ConnectError
    ConnectTimeout = _ConnectTimeout

    def __init__(self, script):
        self.script = list(script)   # each item: a _Response or an exception
        self.calls = 0
        self.timeouts = []

    def Timeout(self, read, connect=None):
        self.timeouts.append((read, connect))
        return ("timeout", read, connect)

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls += 1
        step = self.script.pop(0) if self.script else self.script_default()
        if isinstance(step, Exception):
            raise step
        return step

    def script_default(self):
        return _ConnectError("connection refused")


def run(script):
    """Drive embed._post against a scripted provider. Returns
    (result_or_exception, fake, retries_seen, sleeps)."""
    import embed
    fake = FakeHttpx(script)
    sleeps, retries = [], []
    saved_httpx = sys.modules.get("httpx")
    saved_sleep = time.sleep
    sys.modules["httpx"] = fake
    time.sleep = lambda s: sleeps.append(s)
    embed.time.sleep = time.sleep
    try:
        try:
            out = embed._post(["hello"],
                              on_retry=lambda a, n, d: retries.append((a, n, d)))
        except Exception as e:                       # noqa: BLE001
            out = e
    finally:
        time.sleep = saved_sleep
        embed.time.sleep = saved_sleep
        if saved_httpx is None:
            sys.modules.pop("httpx", None)
        else:
            sys.modules["httpx"] = saved_httpx
    return out, fake, retries, sleeps


VEC = {"data": [{"index": 0, "embedding": [0.5] * 1024}]}


def main():
    import embed

    print("--- connect and read are two different budgets ---")
    out, fake, _, _ = run([_Response(200, VEC)])
    read, connect = fake.timeouts[0]
    ok("httpx is given a split timeout, not one number",
       connect is not None and connect != read, fake.timeouts)
    ok("connect is the short one — it only asks whether anything is there",
       connect < read, (connect, read))
    ok("a good call returns its vectors", isinstance(out, list) and len(out[0]) == 1024)

    print("\n--- a dead server is a state, not a transient ---")
    out, fake, retries, sleeps = run([_ConnectError("refused")] * 6)
    ok("it stops after the short budget, not the long one",
       fake.calls == embed._DOWN_RETRIES, fake.calls)
    ok("it still tries twice, in case it caught a restart", fake.calls == 2)
    ok("the error names the endpoint and says what is wrong",
       "is the embedding server running?" in str(out)
       and embed.EMBED_BASE in str(out), out)
    ok("the caller is told once, before the last attempt", len(retries) == 1, retries)
    ok("no sleep on the way out — the old loop backed off then gave up anyway",
       len(sleeps) == fake.calls - 1, sleeps)

    print("\n--- a connect *timeout* is the same story as a refusal ---")
    out, fake, _, _ = run([_ConnectTimeout("timed out")] * 6)
    ok("a hung connect uses the short budget too",
       fake.calls == embed._DOWN_RETRIES, fake.calls)

    print("\n--- a busy server gets the patience it was written for ---")
    out, fake, retries, sleeps = run([_Response(503)] * 6)
    ok("503 is retried the full number of times",
       fake.calls == embed._RETRIES, fake.calls)
    ok("the budgets are actually different, or none of this matters",
       embed._RETRIES > embed._DOWN_RETRIES)
    ok("backoff grows", sleeps == sorted(sleeps) and len(set(sleeps)) > 1, sleeps)
    ok("the caller hears about each retry", len(retries) == fake.calls - 1, retries)

    print("\n--- recovery ---")
    out, fake, retries, _ = run([_Response(429), _Response(200, VEC)])
    ok("a transient that clears returns vectors",
       isinstance(out, list) and len(out[0]) == 1024, out)
    ok("...and said something while it was waiting", len(retries) == 1, retries)

    print("\n--- silence is the default ---")
    # Routines and imports run headless. embed.py has no console and must not
    # grow one: on_retry is how a caller opts in to being told.
    import embed as _e
    fake = FakeHttpx([_ConnectError("refused")] * 6)
    saved = sys.modules.get("httpx")
    saved_sleep = _e.time.sleep
    sys.modules["httpx"] = fake
    _e.time.sleep = lambda s: None
    try:
        try:
            _e._post(["hello"])          # no on_retry
        except RuntimeError:
            pass
        ok("no callback, no output, no crash", True)
    except Exception as e:                            # noqa: BLE001
        ok("no callback, no output, no crash", False, e)
    finally:
        _e.time.sleep = saved_sleep
        if saved is None:
            sys.modules.pop("httpx", None)
        else:
            sys.modules["httpx"] = saved

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
