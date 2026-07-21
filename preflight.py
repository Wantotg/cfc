#!/usr/bin/env python3
"""
preflight.py — make sure the embedder is up before cfc starts.

Everything memory-shaped in cfc quietly assumes LM Studio is running with
bge-m3 loaded: `:recall`, `:remember`, `:updatedb`, and the per-turn auto-embed
hook. When it isn't, none of them say "the embedder is down" — auto-embed is
best-effort and warns quietly by design, and recall just comes back empty,
which is indistinguishable from "memory has nothing on that". This retires that
whole class of failure by checking once, out loud, at launch.

Run by `launch.sh`, not by `main.py`. Two reasons: `python main.py` stays
instant for anyone who knows the embedder is up, and the golden tests keep
driving the REPL without a network call appearing under them.

**It never blocks the launch.** A failed check prints what is wrong and returns
False; the caller starts cfc anyway. Chat works fine without an embedder, and a
launcher that refuses to open the app because a subsystem is down is worse than
the thing it is protecting against.

Talks to LM Studio through its `lms` CLI, which has `--json` on the two
commands that matter — parsed, not scraped. Only stdlib plus httpx (already a
cfc dependency); no rich, so a broken UI import can't stop the app opening.
"""
import json
import shutil
import subprocess
import sys
import time
from glob import glob
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Short. This is a liveness check on a local process, not a workload — every
# second here is a second of staring at a terminal that hasn't opened yet.
# embed.py's own 60s timeout and 4 retries are right for a real batch and
# wrong for this.
PROBE_TIMEOUT = 8.0
LMS_TIMEOUT = 90        # a cold `server start` has to bring up the app
LOAD_TIMEOUT = 180      # loading a model off disk, possibly cold cache

GREEN, YELLOW, RED, DIM, RESET = (
    "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m")


def _say(mark, msg, colour=""):
    print(f"  {colour}{mark}{RESET} {msg}", flush=True)


def _cfg(key, default=None):
    try:
        import config
        return getattr(config, key, default)
    except Exception:
        return default


def embed_target():
    """(base_url, model, key) — read from config, never duplicated here.

    The launcher must not carry its own copy of the endpoint. A second copy is
    a second thing to update, and the failure when they disagree is the
    launcher cheerfully reporting a healthy embedder that cfc cannot reach.
    """
    base = _cfg("EMBED_BASE") or _cfg("API_BASE", "https://api.nano-gpt.com/v1")
    model = _cfg("EMBED_MODEL", "BAAI/bge-m3")
    key = _cfg("EMBED_KEY") or _cfg("API_KEY") or "lm-studio"
    return base, model, key


def is_local(base):
    """Whether the embedder is something we could plausibly start.

    A hosted endpoint (the nano-gpt fallback) is not ours to manage: if that is
    down the answer is to wait, not to run `lms`. Checking this rather than
    assuming keeps the launcher honest on a config that has fallen back.
    """
    host = (urlparse(base).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


def probe(timeout=PROBE_TIMEOUT):
    """One real embedding request. Returns (ok, detail).

    Deliberately an /embeddings POST and not a GET on /v1/models: the model
    list reports what LM Studio has on *disk*, so it answers happily while the
    model is unloaded and the thing cfc needs still fails. Test what you need,
    not a proxy for it — this is the same call `embed_texts` makes, minus the
    batching and the retries.
    """
    base, model, key = embed_target()
    try:
        import httpx
    except ImportError:
        return False, "httpx is not installed — is the venv active?"

    url = base.rstrip("/") + "/embeddings"
    try:
        r = httpx.post(
            url,
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"},
            json={"model": model, "input": ["preflight"]},
            timeout=timeout,
        )
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text[:160]}"
    try:
        dim = len(r.json()["data"][0]["embedding"])
    except Exception as e:
        return False, f"unexpected response shape: {e}"

    # The dimension is checked because vec_chunks is declared float[1024]. A
    # model that answers with a different width would insert garbage rather
    # than fail, and the damage would only surface as slightly worse ranking
    # weeks later — the exact silent-failure shape this file exists to prevent.
    if dim != 1024:
        return False, (f"{model} returned {dim}-d vectors, expected 1024 — "
                       "vec_chunks is float[1024]; wrong model loaded?")
    return True, f"{model} ({dim}-d)"


def find_lms():
    """The `lms` CLI, or None. config.LMS_CLI wins if set."""
    override = _cfg("LMS_CLI")
    if override and Path(override).exists():
        return override
    found = shutil.which("lms")          # a native Linux LM Studio
    if found:
        return found
    # WSL: LM Studio installs its CLI under the Windows user profile. Globbed
    # rather than hard-coded to a username, so this file stays checked-in-able.
    for hit in sorted(glob("/mnt/c/Users/*/.lmstudio/bin/lms.exe")):
        return hit
    return None


def _lms(cli, *args, timeout=LMS_TIMEOUT):
    """Run one lms command. Returns (ok, stdout). Never raises."""
    try:
        p = subprocess.run([cli, *args], capture_output=True, text=True,
                           timeout=timeout)
        return p.returncode == 0, p.stdout
    except Exception as e:
        return False, str(e)


def server_state(cli):
    """(running, port) from `lms server status --json`, or (None, None)."""
    ok, out = _lms(cli, "server", "status", "--json", timeout=30)
    if not ok:
        return None, None
    try:
        data = json.loads(out.strip().splitlines()[-1])
        return bool(data.get("running")), data.get("port")
    except Exception:
        return None, None


def loaded_keys(cli):
    """Model keys currently in memory, from `lms ps --json`."""
    ok, out = _lms(cli, "ps", "--json", timeout=30)
    if not ok:
        return set()
    try:
        return {m.get("modelKey") for m in json.loads(out)}
    except Exception:
        return set()


def ensure():
    """Check, and fix what can be fixed. Returns True if embedding works.

    The order is: probe first, diagnose only on failure. The happy path is one
    HTTP round trip to a local process — everything below the first branch is
    the cost of things being broken, which is where it belongs.
    """
    base, model, _ = embed_target()
    print(f"{DIM}  embedder: {base}{RESET}", flush=True)

    ok, detail = probe()
    if ok:
        _say("✓", f"embedder ready — {detail}", GREEN)
        return True

    if not is_local(base):
        _say("✗", f"hosted embedder unreachable — {detail}", RED)
        _say(" ", "not something the launcher can start; memory will be "
                  "degraded.", DIM)
        return False

    cli = find_lms()
    if not cli:
        _say("✗", f"embedder down and no `lms` CLI found — {detail}", RED)
        _say(" ", "start LM Studio by hand, or set LMS_CLI in config.py.", DIM)
        return False

    running, port = server_state(cli)
    acted = False       # did we actually change anything worth re-probing for?

    if running is False:
        _say("…", "LM Studio server is off — starting it", YELLOW)
        want = urlparse(base).port or 1233
        # --bind 0.0.0.0 is LM Studio's "serve on local network" toggle. The
        # handover records it as required, and it costs nothing to be explicit
        # here rather than inheriting whatever the GUI was last left on.
        started, out = _lms(cli, "server", "start", "-p", str(want),
                            "--bind", "0.0.0.0")
        if not started:
            _say("✗", f"could not start the server: {out.strip()[:160]}", RED)
            return False
        acted = True
        ok, detail = probe(timeout=20)
        if ok:
            _say("✓", f"embedder ready — {detail}", GREEN)
            return True

    if model not in loaded_keys(cli):
        _say("…", f"server up, {model} not loaded — loading it", YELLOW)
        # -y because without it `lms load` drops into an interactive picker
        # when the key is ambiguous, and a launcher that stops to ask a
        # question is a launcher that hangs behind a splash screen.
        got, out = _lms(cli, "load", "-y", model, timeout=LOAD_TIMEOUT)
        if not got:
            _say("✗", f"could not load {model}: {out.strip()[:160]}", RED)
            return False
        acted = True
        time.sleep(1.0)     # the model is loaded slightly before it serves

    # Only re-probe if something was actually changed. When the server is up
    # and the model is loaded and it *still* doesn't answer, a second probe
    # tests nothing and costs another timeout — and on WSL a dead local port
    # hangs until the timeout rather than refusing, so that is 20 wasted
    # seconds in front of an app that hasn't opened yet.
    if acted:
        ok, detail = probe(timeout=20)
        if ok:
            _say("✓", f"embedder ready — {detail}", GREEN)
            return True

    _say("✗", f"embedder not answering — {detail}", RED)
    if not acted:
        _say(" ", f"server is up on port {port} and {model} is loaded, so "
                  "this is not a startup problem.", DIM)
    _say(" ", "cfc will start; :recall and auto-embed will not work.", DIM)
    return False


if __name__ == "__main__":
    # Always exit 0. The exit code is not a gate — launch.sh starts cfc either
    # way, and a non-zero status here would make `set -e` in some future
    # wrapper silently turn a degraded embedder into a refusal to launch.
    ensure()
    sys.exit(0)
