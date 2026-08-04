# websearch.py — the host side of the v1.8 live web-search boundary: the
# Bubblewrap sandbox, the one-attempt launch, and the human-readable summary.
#
# tools.py calls search() and never anything lower in this file — every
# other name here is this module's own business. search() always returns a
# validated result dict (search_protocol.build_response's shape) and never
# raises: a bug in this module's own subprocess handling becomes a typed
# `failed` result, the same as a bug in the worker would, rather than an
# exception escaping into the tool dispatcher.
#
# The sandbox, once, so nothing here has to argue with itself twice:
#
#   * fresh process/user/mount/IPC/UTS namespaces (--unshare-all), but the
#     network namespace is explicitly SHARED with the host (--share-net) —
#     the one guarantee v1.8 changes. Everything else v1.7 proved stays true.
#   * an empty root — only /usr (read-only) plus the /lib, /lib64, /bin
#     symlinks a Python interpreter (and curl) need to resolve their own
#     dynamic linker, and nothing under /home, /mnt, the cfc source tree,
#     the vault or ~/.cfc ever enters the mount table to begin with
#   * three small runtime files HTTPS needs, read-only: the resolver config,
#     the name-service switch config, and the CA certificate bundle — see
#     RUNTIME_MOUNTS below for why these three and not, say, all of /etc
#   * search_worker.py and search_protocol.py bind-mounted read-only into
#     their own directory — the *only* files from this project the sandbox
#     ever sees
#   * a tmpfs /tmp as the sole writable (and in-memory) location — curl's own
#     header/body scratch files live here and vanish with the worker
#   * a cleared environment (--clearenv) plus -E -S at the interpreter, so
#     no provider key, PATH entry or user-site package is inherited
#   * stdin/stdout as the only application channel; stderr and the exit
#     code are diagnostics, read and discarded, never surfaced to the model
#     or a log
#   * --die-with-parent, so killing the one process this module holds a
#     handle to (bwrap itself) tears the whole sandbox down with it —
#     bwrap holds the new pid namespace open, so nothing survives it
#
# This is not a domain firewall. At the OS level, a worker with a shared
# network namespace can connect anywhere the host can — the destination
# limit is closed in code, not in the sandbox: search_worker.py's only
# executable request target is the literal DDG_URL constant, curl is invoked
# without a shell and with redirects disabled, and returned links are parsed
# as data and never requested. See search_worker.py's own header.
#
# `-I` (Python's own isolated mode) was tried first and rejected: it also
# implies -P, which stops Python prepending the script's own directory to
# sys.path — and that is exactly how search_worker.py finds
# search_protocol.py next to it with no cfc import and no PYTHONPATH (which
# --clearenv has removed anyway). -E -S gets the same "ignore the
# environment, no site-packages" property without breaking that import.
import shutil
import subprocess
from pathlib import Path

import search_protocol as proto

CODE_ROOT = Path(__file__).resolve().parent
WORKER_PATH = CODE_ROOT / "search_worker.py"
PROTOCOL_PATH = CODE_ROOT / "search_protocol.py"

# Bare names/paths, resolved at call time rather than once at import — so a
# test can point these at something that does not exist ("verify a guard by
# disabling it", HANDOVER.md's testing habit) and watch sandbox_unavailable
# come back, then restore it, without this module ever caching a stale
# answer.
BWRAP_BINARY = "bwrap"
# The system Python bound into the sandbox — deliberately not cfc's own
# interpreter (sys.executable): cfc runs from a venv under ~/projects, which
# the sandbox never mounts. Any stdlib-only Python3 can run the worker; this
# is the fixed path this WSL install's system Python lives at, under /usr,
# which the sandbox does mount.
SANDBOX_PYTHON = "/usr/bin/python3"
# Mirrors search_worker.py's own CURL_BINARY constant exactly. Not imported
# from there — the worker's module can only depend on the stdlib and
# search_protocol.py once inside the sandbox (see its own header), so the
# host keeps its own copy of the one fact both sides need to agree on.
SANDBOX_CURL = "/usr/bin/curl"

# The three host files search_worker.py's one HTTPS request needs and
# nothing else does: DNS resolution (resolv.conf), the lookup order that
# tells glibc to actually consult it (nsswitch.conf), and the trust store
# TLS verification checks against (the CA bundle). All three are read-only
# and none of them is a directory a model could browse — binding a specific
# file, not a parent directory, is what keeps this from becoming a second,
# wider read root. resolv.conf is commonly a symlink (WSL points it at
# /mnt/wsl/resolv.conf); `--ro-bind` follows that resolution on the host
# side, before the sandbox's own mount table exists, so the target need not
# be reachable from inside the sandbox itself.
RUNTIME_MOUNTS = (
    Path("/etc/resolv.conf"),
    Path("/etc/nsswitch.conf"),
    Path("/etc/ssl/certs/ca-certificates.crt"),
)

HOST_TIMEOUT = 20.0     # seconds allowed for the whole worker process — a
                        # backstop above search_worker.py's own curl timeout
                        # (connect 5s + total 12s), not the primary clock
# Diagnostics only (see the module docstring) — capped so a future debug
# path that does inspect this can't itself become an unbounded sink.
MAX_STDERR_CHARS = 2000


def _sandbox_reason(worker_path, protocol_path):
    """Why the sandbox can't run right now, or None if it can. Checked fresh
    before every attempt, not cached — bwrap or curl disappearing mid-session
    must degrade to a typed result immediately, not on the next restart."""
    if shutil.which(BWRAP_BINARY) is None:
        return f"{BWRAP_BINARY!r} is not on PATH"
    if not Path(SANDBOX_PYTHON).exists():
        return f"{SANDBOX_PYTHON} does not exist"
    if not Path(SANDBOX_CURL).exists():
        return f"{SANDBOX_CURL} does not exist"
    if not Path(worker_path).exists():
        return f"worker script missing: {worker_path}"
    if not Path(protocol_path).exists():
        return f"protocol module missing: {protocol_path}"
    for p in RUNTIME_MOUNTS:
        if not p.exists():
            return f"{p} does not exist"
    return None


def sandbox_status():
    """'ready', or the specific reason it is not — /tools' own words for the
    web_search row: 'live via DuckDuckGo HTML: ready', or a sandbox
    failure naming bwrap, curl or a missing runtime file specifically."""
    reason = _sandbox_reason(WORKER_PATH, PROTOCOL_PATH)
    return "ready" if reason is None else reason


def _bwrap_args(worker_path, protocol_path):
    args = [
        BWRAP_BINARY,
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/lib64", "/lib64",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/bin", "/bin",
        "--dev", "/dev",
        "--proc", "/proc",
        "--tmpfs", "/tmp",
    ]
    for p in RUNTIME_MOUNTS:
        args += ["--ro-bind", str(p), str(p)]
    args += [
        "--ro-bind", str(protocol_path), "/app/search_protocol.py",
        "--ro-bind", str(worker_path), "/app/search_worker.py",
        "--chdir", "/app",
        "--unshare-all",
        "--share-net",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--setenv", "PATH", "/usr/bin",
        SANDBOX_PYTHON, "-E", "-S", "-B", "/app/search_worker.py",
    ]
    return args


def _failure(code):
    # Every failure this module (as opposed to the worker) produces is a
    # host-stage one: bwrap/worker lifecycle, or the host's own validation
    # of what the worker printed. Codes the *worker* originates carry
    # "request" or "parse" instead, and arrive already built by
    # proto.parse_response — this function is never the one naming those.
    #
    # Never sandbox_unavailable — that code means the attempt never
    # started, which is _unavailable()'s status, not this one's.
    return proto.build_response(
        "failed", failures=[{"stage": "host", "code": code}])


def _unavailable(code):
    # The pre-start state: nothing was launched, so nothing was sent.
    # sandbox_unavailable is the only code that ever reaches this — a local
    # prerequisite missing, or bwrap itself refusing to start (OSError from
    # Popen) — never a worker that ran and then failed.
    return proto.build_response(
        "unavailable", failures=[{"stage": "host", "code": code}])


def _launch_one(request_json, worker_path, protocol_path):
    """The one worker attempt v1.8 ever makes for an approved call. Always
    returns a validated response dict and never raises.

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
        # start. Nothing was launched, so this is the pre-start state, same
        # as the pre-flight check finds — there is no fallback to a raw
        # subprocess on either path.
        return _unavailable("sandbox_unavailable")

    outcome = None
    try:
        try:
            out, _err = proc.communicate(
                input=request_json.encode("utf-8"), timeout=HOST_TIMEOUT)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            outcome = _failure("worker_timeout")
        except BaseException:
            # Anything else going wrong while talking to the child — a
            # KeyboardInterrupt included — still has to leave exactly one
            # typed result and no live child (HANDOVER.md standing decision
            # 2: every call gets one result, on every exit).
            outcome = _failure("interrupted")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    if outcome is not None:
        return outcome
    if code != 0:
        return _failure("worker_crash")

    raw = out.decode("utf-8", errors="replace")
    parsed, _reason = proto.parse_response(raw)
    if parsed is None:
        return _failure("protocol_error")
    return parsed


def search(query, worker_path=None, protocol_path=None):
    """Run the v1.8 live search boundary for one query. Always returns a
    validated dict — protocol/status/evidence/failures — and never raises.

    One approval, one worker, one curl request: there is no retry loop here
    any more (v1.7 had one; Concept.md replaces it with this rule). A
    caller that wants another attempt makes another approved call.

    `worker_path`/`protocol_path` are the test harness's injection point: a
    fixture worker substitutes for the production one by path, never through
    the request itself, which is why `search()` takes no `scenario` argument
    and the public tool schema carries only `query`.
    """
    worker_path = Path(worker_path) if worker_path else WORKER_PATH
    protocol_path = Path(protocol_path) if protocol_path else PROTOCOL_PATH

    reason = _sandbox_reason(worker_path, protocol_path)
    if reason:
        return _unavailable("sandbox_unavailable")

    try:
        request_json = proto.dumps_request(query)
    except proto.ProtocolError:
        return _failure("protocol_error")

    return _launch_one(request_json, worker_path, protocol_path)


# Failure codes after which the UI notes the query may already have left the
# machine — everything from here down is rendering, and this is the one
# piece of judgement it carries: these four all mean the worker got at least
# as far as attempting the network call before things went wrong, unlike
# sandbox_unavailable (never launched) or protocol_error (launched, but the
# failure is about the reply's shape, not the request).
_MAY_HAVE_SENT = {"connection_failed", "request_timeout", "worker_timeout",
                  "worker_crash"}


def summarize(result):
    """One line for the human, built from the validated result dict — never
    the raw JSON, which is what the model reads instead. Stable across
    everything search() can return, including a result this module never
    actually named above (an unrecognised status renders rather than
    raising, since this is a rendering path, not another validator)."""
    status = result.get("status")
    evidence = result.get("evidence") or []
    failures = result.get("failures") or []
    code = failures[0]["code"] if failures else None
    note = " — the query may already have been sent" if code in _MAY_HAVE_SENT \
        else ""

    if status == "unavailable":
        return f"web_search unavailable — {code or 'unavailable'}"
    if status == "complete":
        if not evidence:
            return "web_search complete — no results"
        return (f"web_search complete — {len(evidence)} untrusted "
                f"result(s) from DuckDuckGo")
    if status == "partial":
        return (f"web_search partial — {len(evidence)} untrusted "
                f"result(s) from DuckDuckGo, {code}{note}")
    if status == "failed":
        return f"web_search failed — {code or 'failed'}{note}"
    return f"web_search {status}"


def evidence_lines(result):
    """Numbered title/url/excerpt blocks for every evidence item — the human
    reader's own copy of exactly what the model receives, never the raw
    protocol JSON. Empty when there is no evidence, so a caller can always
    append this after summarize() with no extra conditional."""
    lines = []
    for i, item in enumerate(result.get("evidence") or [], start=1):
        lines.append(f"{i}. {item['title']}")
        lines.append(f"   {item['url']}")
        lines.append(f"   {item['excerpt']}")
    return lines
