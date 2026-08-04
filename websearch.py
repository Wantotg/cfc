# websearch.py — the host side of the v1.7 web-search boundary: the
# Bubblewrap sandbox, the launch/retry loop, and the human-readable summary.
#
# tools.py calls search() and never anything lower in this file — every
# other name here is this module's own business. search() always returns a
# validated result dict (search_protocol.build_response's shape plus
# `attempts`) and never raises: a bug in this module's own subprocess
# handling becomes a typed `failed` result, the same as a bug in the worker
# would, rather than an exception escaping into the tool dispatcher.
#
# The sandbox, once, so nothing here has to argue with itself twice:
#
#   * fresh process/user/mount/network/IPC/UTS namespaces (--unshare-all)
#   * an empty root — only /usr (read-only) plus the /lib, /lib64, /bin
#     symlinks a Python interpreter needs to resolve its own dynamic linker,
#     and nothing under /home, /mnt, the cfc source tree, the vault or
#     ~/.cfc ever enters the mount table to begin with
#   * search_worker.py and search_protocol.py bind-mounted read-only into
#     their own directory — the *only* files from this project the sandbox
#     ever sees
#   * a tmpfs /tmp as the sole writable (and in-memory) location
#   * a cleared environment (--clearenv) plus -E -S at the interpreter, so
#     no provider key, PATH entry or user-site package is inherited
#   * no network route out (the network namespace has no configured
#     interface, not merely an unconnected one)
#   * stdin/stdout as the only application channel; stderr and the exit
#     code are diagnostics, read and discarded, never surfaced to the model
#     or a log
#   * --die-with-parent, so killing the one process this module holds a
#     handle to (bwrap itself) tears the whole sandbox down with it —
#     bwrap holds the new pid namespace open, so nothing survives it
#
# `-I` (Python's own isolated mode) was tried first and rejected: it also
# implies -P, which stops Python prepending the script's own directory to
# sys.path — and that is exactly how search_worker.py finds
# search_protocol.py next to it with no cfc import and no PYTHONPATH (which
# --clearenv has removed anyway). -E -S gets the same "ignore the
# environment, no site-packages" property without breaking that import.
import json
import shutil
import subprocess
from pathlib import Path

import search_protocol as proto

CODE_ROOT = Path(__file__).resolve().parent
WORKER_PATH = CODE_ROOT / "search_worker.py"
PROTOCOL_PATH = CODE_ROOT / "search_protocol.py"

# A bare name, resolved via PATH at call time rather than once at import —
# so a test can point this at a binary that does not exist ("verify a guard
# by disabling it", HANDOVER.md's testing habit) and watch sandbox_unavailable
# come back, then restore it, without this module ever caching a stale answer.
BWRAP_BINARY = "bwrap"

# The system Python bound into the sandbox — deliberately not cfc's own
# interpreter (sys.executable): cfc runs from a venv under ~/projects, which
# the sandbox never mounts. Any stdlib-only Python3 can run the worker; this
# is the fixed path this WSL install's system Python lives at, under /usr,
# which the sandbox does mount.
SANDBOX_PYTHON = "/usr/bin/python3"

HOST_TIMEOUT = 10.0     # seconds allowed per worker attempt
MAX_ATTEMPTS = 3        # this launch plus up to two retries
# Diagnostics only (see the module docstring) — capped so a future debug
# path that does inspect this can't itself become an unbounded sink.
MAX_STDERR_CHARS = 2000


def _sandbox_reason(worker_path, protocol_path):
    """Why the sandbox can't run right now, or None if it can. Checked fresh
    before every attempt, not cached — bwrap disappearing mid-session must
    degrade to a typed result immediately, not on the next restart."""
    if shutil.which(BWRAP_BINARY) is None:
        return f"{BWRAP_BINARY!r} is not on PATH"
    if not Path(SANDBOX_PYTHON).exists():
        return f"{SANDBOX_PYTHON} does not exist"
    if not Path(worker_path).exists():
        return f"worker script missing: {worker_path}"
    if not Path(protocol_path).exists():
        return f"protocol module missing: {protocol_path}"
    return None


def sandbox_status():
    """'ready', or the specific reason it is not — /tools' own words for the
    web_search row (Concept.md: 'offline stub: ready' or a sandbox failure)."""
    reason = _sandbox_reason(WORKER_PATH, PROTOCOL_PATH)
    return "ready" if reason is None else reason


def _bwrap_args(worker_path, protocol_path):
    return [
        BWRAP_BINARY,
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/lib64", "/lib64",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/bin", "/bin",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
        "--ro-bind", str(protocol_path), "/app/search_protocol.py",
        "--ro-bind", str(worker_path), "/app/search_worker.py",
        "--chdir", "/app",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--setenv", "PATH", "/usr/bin",
        SANDBOX_PYTHON, "-E", "-S", "-B", "/app/search_worker.py",
    ]


def _failure(code, retryable):
    return proto.build_response(
        "failed",
        failures=[{"stage": "search", "code": code, "retryable": retryable}])


def _launch_one(request_json, worker_path, protocol_path):
    """One worker attempt: launch, feed the request, collect the response.
    Always returns a validated response dict (no `attempts` field — the
    caller owns that count) and never raises.

    Every exit path below — a clean answer, a timeout, a nonzero exit, or an
    exception (including KeyboardInterrupt: Ctrl-C during the wait) — reaches
    the `finally` and reaps the child before returning. bwrap holds the
    sandbox's pid namespace open, so killing this one process is killing the
    whole sandbox; nothing here trusts the worker to exit on its own.
    """
    try:
        proc = subprocess.Popen(
            _bwrap_args(worker_path, protocol_path),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, start_new_session=True)
    except OSError:
        # bwrap vanished between the pre-flight check and now, or refused to
        # start. Same typed result as the pre-flight check finds — there is
        # no fallback to a raw subprocess on either path.
        return _failure("sandbox_unavailable", retryable=False)

    outcome = None
    try:
        try:
            out, _err = proc.communicate(
                input=request_json.encode("utf-8"), timeout=HOST_TIMEOUT)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            outcome = _failure("timeout", retryable=True)
        except BaseException:
            # Anything else going wrong while talking to the child — a
            # KeyboardInterrupt included — still has to leave exactly one
            # typed result and no live child (HANDOVER.md standing decision
            # 2: every call gets one result, on every exit).
            outcome = _failure("interrupted", retryable=False)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    if outcome is not None:
        return outcome
    if code != 0:
        return _failure("worker_crash", retryable=True)

    raw = out.decode("utf-8", errors="replace")
    parsed, _reason = proto.parse_response(raw)
    if parsed is None:
        return _failure("protocol_error", retryable=False)
    return parsed


def _retryable(result):
    # `failed` is the only status this can ever be true for — validate_response
    # refuses evidence on a `failed` result, so "no evidence came back" is
    # automatic whenever this function is even asked the question.
    return result["status"] == "failed" and any(
        f["retryable"] for f in result["failures"])


def search(query, worker_path=None, protocol_path=None):
    """Run the v1.7 search boundary for one query. Always returns a
    validated dict — protocol/status/evidence/failures/attempts — and never
    raises.

    `worker_path`/`protocol_path` are the test harness's injection point
    (Work Order step 6): a fixture worker substitutes for the production one
    by path, never through the request itself, which is why `search()` takes
    no `scenario` argument and the public tool schema carries only `query`.
    """
    worker_path = Path(worker_path) if worker_path else WORKER_PATH
    protocol_path = Path(protocol_path) if protocol_path else PROTOCOL_PATH

    reason = _sandbox_reason(worker_path, protocol_path)
    if reason:
        result = _failure("sandbox_unavailable", retryable=False)
        result["attempts"] = 0
        return result

    try:
        request_json = proto.dumps_request(query)
    except proto.ProtocolError:
        result = _failure("protocol_error", retryable=False)
        result["attempts"] = 0
        return result

    attempts = 0
    result = None
    while attempts < MAX_ATTEMPTS:
        attempts += 1
        result = _launch_one(request_json, worker_path, protocol_path)
        # complete/partial/unavailable are all final on first sight: partial
        # already carries the evidence it found, and throwing that away to
        # chase a perfect retry is the wrong failure direction (Concept.md).
        # Only `failed` — which never carries evidence — is a candidate to
        # retry, and only when the worker itself typed it retryable.
        if not _retryable(result):
            break

    result["attempts"] = attempts
    return result


def summarize(result):
    """One line for the human, built from the validated result dict — never
    the raw JSON, which is what the model reads instead (Concept.md). Stable
    across everything search() can return, including a result this module
    never actually named above (an unrecognised status renders rather than
    raising, since this is a rendering path, not another validator)."""
    status = result.get("status")
    evidence = result.get("evidence") or []
    failures = result.get("failures") or []
    code = failures[0]["code"] if failures else None

    if status == "unavailable" and code == "not_available_yet":
        return ("web_search unavailable — not available yet; no network "
                "request was made")
    if status == "unavailable":
        return f"web_search unavailable — {code or 'unavailable'}"
    if status == "complete":
        if not evidence:
            return "web_search complete — no results"
        return f"web_search complete — {len(evidence)} result(s)"
    if status == "partial":
        codes = ", ".join(f["code"] for f in failures)
        return f"web_search partial — {len(evidence)} result(s), {codes}"
    if status == "failed":
        return f"web_search failed — {code or 'failed'}"
    return f"web_search {status}"
