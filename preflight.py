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

**It is also the one place that answers "what state is the connection in".**
`connection_state()` is read by three callers — this file's own launch report,
the hub's traffic light, and `/connect embedding` — and the rule is that they
*render* its answer and never form one of their own. A light that decides for
itself is a second opinion, and the failure mode of a second opinion here is
green over a dead server: the one output nobody double-checks, because it is
the reassurance that stops you checking. Everything below the fixer is
read-only and cheap enough to ask on every hub render (see the timings on
`PROBE_CONNECT`), which is what removes the temptation to cache an answer and
then have to reason about how stale it is.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from glob import glob
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# **Connect and read are two different quantities, and they are pinned as a
# pair** — the same lesson `embed.py` learned in v0.8.2, one layer up. httpx's
# single `timeout=` sets both, so one number has to serve the slower one, and
# the old `PROBE_TIMEOUT = 8.0` therefore made a *dead* port cost the full read
# budget just to learn nothing was listening. Measured on this machine
# (2026-07-27): a live local embedder answers a real /embeddings POST in
# **0.157s**, and a dead local port on WSL hangs rather than refusing, so it
# costs exactly the connect timeout.
#
# That measurement is what makes the hub's light affordable — 0.16s healthy,
# 0.5s when the server is gone — so there is no cache anywhere in this file and
# no staleness to reason about. **Re-measure before raising either number**, and
# keep them a pair: merging them back into one is the bug, not the tuning.
PROBE_CONNECT = 0.5     # a local port answers instantly or is not there
PROBE_READ = 8.0        # a cold model load legitimately needs this
LMS_TIMEOUT = 90        # a cold `server start` has to bring up the app
LOAD_TIMEOUT = 180      # loading a model off disk, possibly cold cache
PS_TIMEOUT = 10         # a process listing; it either answers at once or is broken

# The connection's states. Strings rather than an enum because `ui.py` maps them
# to a colour and must not import this module (it imports no cfc module at all),
# so this is a producer/parser pair across a module boundary — the recurring
# hazard `HANDOVER.md` tabulates. It is pinned by round-trip in
# `tests/test_connection.py`: every constant here must have a rendering there.
#
# The four failure states are deliberately not one "down". We report the process
# state only when we actually measured it — claiming "LM Studio is running, its
# server isn't" without having looked is the kind of confident wrong answer this
# whole feature exists to stop.
CONNECTED = "connected"        # a real embedding call just worked
NO_SERVER = "no server"        # LM Studio is running; embeddings don't answer
NOT_RUNNING = "not running"    # LM Studio is not running at all
DOWN = "down"                  # embeddings don't answer and we can't tell why
HOSTED = "hosted"              # not a local embedder; not ours to start
STATES = (CONNECTED, NO_SERVER, NOT_RUNNING, DOWN, HOSTED)

GREEN, YELLOW, RED, DIM, RESET = (
    "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m")

# Levels a step can report at, and this file's own rendering of them. `ensure()`
# takes a `say` callback rather than printing directly, because it is run both
# by `launch.sh` (before rich exists, and deliberately without importing it) and
# by `/connect embedding` (inside a session, where raw ANSI beside rich panels
# looks like a bug). Same move as `embed.py`'s `on_retry` in v0.8.2: a callback,
# not a console, because this module must not grow one.
_MARKS = {"ok": ("✓", GREEN), "warn": ("…", YELLOW),
          "fail": ("✗", RED), "info": (" ", DIM)}


def _say(level, msg):
    mark, colour = _MARKS.get(level, (" ", ""))
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


def probe(connect=PROBE_CONNECT, read=PROBE_READ):
    """One real embedding request. Returns (ok, detail).

    Deliberately an /embeddings POST and not a GET on /v1/list models: the model
    list reports what LM Studio has on *disk*, so it answers about storage while
    the thing cfc needs may still fail. Test what you need, not a proxy for it —
    this is the same call `embed_texts` makes, minus the batching and retries.

    A side effect worth knowing rather than discovering: because this is the
    real call, it **JIT-loads the model** the way any other request would. So a
    probe against a freshly restarted server is slow (1.71s measured) rather
    than failing, and the answer it gives is the true one — the embedder does
    work, it just had to wake up first.

    Two timeouts, never one. See `PROBE_CONNECT`.
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
            timeout=httpx.Timeout(read, connect=connect),
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
    """Run one lms command. Returns (ok, output). Never raises.

    **On success the output is stdout; on failure it is stderr.** That
    asymmetry is the point. `lms` prints its JSON to stdout and its reasons to
    stderr, so returning stdout unconditionally meant every failure reported an
    empty string — `could not start the server: ` with nothing after it, while
    `lms` had been saying "Timed out waiting for LM Studio daemon to start" the
    whole time. Found by running the acceptance test, in the one module whose
    entire job is making a silent failure loud.

    Callers that parse JSON only do so when `ok`, so they never see stderr.
    """
    try:
        p = subprocess.run([cli, *args], capture_output=True, text=True,
                           timeout=timeout)
        if p.returncode == 0:
            return True, p.stdout
        return False, (p.stderr.strip() or p.stdout.strip()
                       or f"exit {p.returncode}, no output")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


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


def app_running():
    """True / False / None — is the LM Studio *application* up?

    `None` means we could not find out, and it is a real third answer rather
    than a pessimistic False. The whole point of separating red from orange is
    to tell you which thing to go and start; guessing that from a process
    listing we never managed to read would be the confident-wrong-answer shape
    this module exists to remove.

    On WSL the app is a Windows process, so this crosses the interop boundary to
    `tasklist.exe` (~0.15s). On a native Linux install it is an ordinary process
    and `pgrep` answers. Neither is asked to be clever: absence of the tool is
    None, not False.
    """
    if os.name == "nt" or Path("/mnt/c/Windows").exists():
        exe = shutil.which("tasklist.exe") or "/mnt/c/Windows/System32/tasklist.exe"
        if not Path(exe).exists():
            return None
        try:
            p = subprocess.run(
                [exe, "/FI", "IMAGENAME eq LM Studio.exe", "/NH"],
                capture_output=True, text=True, timeout=PS_TIMEOUT)
        except Exception:
            return None
        if p.returncode != 0:
            return None
        # tasklist says "INFO: No tasks are running…" rather than printing
        # nothing, so match on the image name and not on emptiness.
        return "LM Studio.exe" in p.stdout

    if not shutil.which("pgrep"):
        return None
    try:
        p = subprocess.run(["pgrep", "-f", "LM Studio"],
                           capture_output=True, text=True, timeout=PS_TIMEOUT)
    except Exception:
        return None
    return p.returncode == 0


def connection_state():
    """(state, detail) — the single answer. One of `STATES`.

    **Every consumer renders this and none of them re-decides it.** The launch
    report, the hub's traffic light and `/connect embedding` all land here; if a
    fourth caller appears that forms its own opinion, that is the drift the
    whole design is against.

    Cheap by construction: the happy path is one real embedding call (~0.16s
    measured) and nothing else. The process listing is only reached once we
    already know something is wrong, which is where the cost belongs.
    """
    base, _, _ = embed_target()
    ok, detail = probe()
    if ok:
        return CONNECTED, detail
    # A hosted endpoint is not ours to start, so it never gets a red light
    # telling you to launch an app that has nothing to do with it.
    if not is_local(base):
        return HOSTED, detail
    running = app_running()
    if running is True:
        return NO_SERVER, detail
    if running is False:
        return NOT_RUNNING, detail
    return DOWN, detail


def terminal_report():
    """(ok, detail) — will this console render the splash as it was baked?

    The splash background is a box-average resample, which pushes colours off
    the baked 40-colour palette; that is invisible on truecolor and bands
    visibly at 256. So a degraded terminal produces a worse-looking app with no
    error anywhere — `HANDOVER.md`'s "prefer the failure that is visible", in
    the one place cfc had left it silent.

    **Fails in the safe direction.** A false positive is loud and
    self-correcting: you are looking at a good splash while being told it will
    band, and you ignore the line. A false negative is exactly today's
    behaviour, which is already understood. So it warns on doubt.

    rich is imported here and nowhere else in this file, inside a try — this
    module must stay launchable when the UI stack is broken, since it runs
    before the app does.
    """
    colorterm = os.environ.get("COLORTERM", "")
    term = os.environ.get("TERM", "")
    try:
        from rich.console import Console
        console = Console()
        system, is_terminal = console.color_system, console.is_terminal
    except Exception as e:
        return True, f"could not ask rich ({type(e).__name__})"
    detail = (f"COLORTERM={colorterm or '(unset)'} TERM={term or '(unset)'} "
              f"rich={system or '(none)'}")
    # Not a terminal at all — piped, redirected, or under a test. rich reports
    # `color_system=None` there, which is not a degraded terminal; there is no
    # splash to band, so there is nothing to warn about. Without this the
    # warning fires on every non-interactive run, and a line that cries wolf in
    # a log is a line that gets filtered out of the one place it's true.
    if not is_terminal:
        return True, detail + " (not a terminal)"
    return system == "truecolor", detail


def ensure(say=_say, fix=True):
    """Check, and fix what can be fixed. Returns True if embedding works.

    `say(level, msg)` with level in `_MARKS` — the caller owns the rendering, so
    `launch.sh` gets raw ANSI and `/connect embedding` gets rich. `fix=False`
    reports without touching anything.

    The order is: ask `connection_state()` first, act only on its answer. The
    happy path is one HTTP round trip to a local process; everything below the
    first branch is the cost of things being broken, which is where it belongs.
    """
    base, model, _ = embed_target()
    state, detail = connection_state()

    if state == CONNECTED:
        say("ok", f"embedder ready — {detail}")
        return True
    if state == HOSTED:
        say("fail", f"hosted embedder unreachable — {detail}")
        say("info", "not something cfc can start; memory will be degraded.")
        return False
    if not fix:
        say("fail", f"embedder not answering — {detail}")
        return False

    cli = find_lms()
    if not cli:
        say("fail", f"embedder down and no `lms` CLI found — {detail}")
        say("info", "start LM Studio by hand, or set LMS_CLI in config.py.")
        return False

    acted = False       # did we actually change anything worth re-probing for?

    # **Red tries, and it works.** Verified 2026-07-27 by Cas, from a genuinely
    # cold machine via the desktop shortcut: this branch ran, `lms server start`
    # brought LM Studio up, and the probe came back green.
    #
    # That is worth a comment because an earlier commit the same day returned
    # here instead, on the strength of my measuring `lms server start` from an
    # interactive shell and watching it die after 62s with "Timed out waiting
    # for LM Studio daemon to start". It really did fail that way. It also
    # works from the launcher. **Three failures in one afternoon were not
    # enough to conclude "impossible" about something that had been observed
    # working** — the early return removed a capability Cas relied on, and he
    # noticed within the hour.
    #
    # Why the direct invocation failed is still unexplained (see `legacy/BUGS.md`
    # for what was tried). It does not block anything: the path a user takes is
    # this one, and this one works.
    if state == NOT_RUNNING:
        say("warn", "LM Studio is not running — starting it. This is the slow "
                    "path; give it up to a minute.")

    running, port = server_state(cli)

    if running is not True:
        say("warn", "LM Studio server is off — starting it")
        want = urlparse(base).port or 1233
        # --bind 0.0.0.0 is LM Studio's "serve on local network" toggle. The
        # handover records it as required, and it costs nothing to be explicit
        # here rather than inheriting whatever the GUI was last left on.
        started, out = _lms(cli, "server", "start", "-p", str(want),
                            "--bind", "0.0.0.0")
        if not started:
            say("fail", f"could not start the server: {out.strip()[:160]}")
            return False
        acted = True
        ok, detail = probe(read=20)
        if ok:
            say("ok", f"embedder ready — {detail}")
            return True

    # **Rarely reached, and kept deliberately.** LM Studio JIT-loads a model
    # when a request names it, so an unloaded model does not fail the probe —
    # measured 2026-07-27: with the model unloaded, `connection_state()` still
    # returned CONNECTED, taking 1.71s instead of 0.15s because the POST itself
    # did the loading. So in the normal configuration this branch never fires.
    #
    # It stays because JIT loading is a *setting*, not a guarantee, and the
    # branch is the correct fallback when it is off. What that measurement
    # really pins down is `PROBE_READ`: a cold load happens inside the read
    # budget, so 8.0s is not slack, it is the thing that stops a first probe
    # after a restart reporting a false "down".
    if model not in loaded_keys(cli):
        say("warn", f"server up, {model} not loaded — loading it")
        # -y because without it `lms load` drops into an interactive picker
        # when the key is ambiguous, and a launcher that stops to ask a
        # question is a launcher that hangs behind a splash screen.
        got, out = _lms(cli, "load", "-y", model, timeout=LOAD_TIMEOUT)
        if not got:
            say("fail", f"could not load {model}: {out.strip()[:160]}")
            return False
        acted = True
        time.sleep(1.0)     # the model is loaded slightly before it serves

    # Only re-probe if something was actually changed. When the server is up
    # and the model is loaded and it *still* doesn't answer, a second probe
    # tests nothing and costs another timeout.
    if acted:
        ok, detail = probe(read=20)
        if ok:
            say("ok", f"embedder ready — {detail}")
            return True

    say("fail", f"embedder not answering — {detail}")
    if state == NOT_RUNNING:
        # We tried and it did not come up. Say the one thing that always works
        # rather than leaving it at "failed" — this is the state a human can
        # clear in five seconds if they are told to.
        #
        # **"in a chat" for `B-0.9.1-03`'s reason, in the place that has it
        # worst** (v1.0). `ui.CONNECTION_STYLE`'s advice was naming a command
        # two of its three screens would refuse; this line is read by
        # `launch.sh` *before the hub exists at all*, so it named one the reader
        # is two steps away from being able to type. Free where it is
        # redundant: the other caller is `/connect embedding` itself, where a
        # reader who is already in a chat has just proved they know.
        say("info", "start LM Studio on Windows, then run /connect embedding "
                    "in a chat — everything after that, cfc can do.")
    elif not acted:
        say("info", f"server is up on port {port} and {model} is loaded, so "
                    "this is not a startup problem.")
    say("info", "cfc will start; /recall and auto-embed will not work.")
    return False


if __name__ == "__main__":
    # Always exit 0. The exit code is not a gate — launch.sh starts cfc either
    # way, and a non-zero status here would make `set -e` in some future
    # wrapper silently turn a degraded embedder into a refusal to launch.
    base, _, _ = embed_target()
    print(f"{DIM}  embedder: {base}{RESET}", flush=True)
    ensure()
    term_ok, term_detail = terminal_report()
    if not term_ok:
        _say("warn", "this terminal is not truecolor — the splash will band")
        _say("info", f"{term_detail}. Launch from Windows Terminal for the "
                     "real thing; see README.")
    sys.exit(0)
