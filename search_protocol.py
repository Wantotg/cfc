# search_protocol.py — the v1.8 live web-search wire format, owned once.
#
# Stdlib-only, on purpose: this file is mounted read-only *inside* the
# sandbox beside search_worker.py (which imports it) and imported normally by
# the host (websearch.py, which also imports it). A third-party dependency
# here would have to be vendored into the sandbox or the boundary would need
# a second, poorer copy of this module — sharing the one definition is what
# keeps both sides honest about the same shape.
#
# Sharing the definition is a drift guard, not a trust boundary. The host
# still calls validate_response()/parse_response() on every worker reply
# (websearch.py) — a worker importing this module tells you nothing about
# whether the worker is honest, only that when it tries to lie about its own
# shape, the same function that will reject it also wrote it.
#
# Two request fields (`protocol`, `operation`) and four response fields
# (`protocol`, `status`, `evidence`, `failures`) are the whole wire. Nothing
# else may be present — parse_response and parse_request both reject unknown
# fields rather than ignore them, because an ignored field is exactly what
# lets a later, careless writer smuggle something extra past a reader that
# never learned to look for it.
#
# v1.8 bumps the version rather than reusing it: a v1.7 host or worker must
# never silently pair with a v1.8 counterpart and misread failure.stage or
# expect a `retryable` field that no longer exists. `retryable` and the
# host-added `attempts` field are gone outright — v1.8 makes at most one
# curl request per approval, so a per-failure "try again" flag and a count of
# tries would both be describing a policy that no longer exists (Concept.md).
import json

PROTOCOL_VERSION = 2

# --- field limits ------------------------------------------------------
#
# Bounds, not budgets: these exist so a malformed or hostile response cannot
# make its way into conversation history at any size, not to tune result
# quality. MAX_EVIDENCE_ITEMS and MAX_EXCERPT_CHARS are tied to the live
# source now — five organic results and DuckDuckGo's own snippet length —
# where v1.7's offline stub had nothing to measure them against.
MAX_QUERY_CHARS = 500
MAX_TITLE_CHARS = 300
MAX_URL_CHARS = 2000
MAX_EXCERPT_CHARS = 600
MAX_EVIDENCE_ITEMS = 5
MAX_FAILURES = 5
MAX_CODE_CHARS = 100
# The whole worker stdout payload, decoded text. Bounds a hostile or broken
# worker's output before it is even handed to json.loads, not just the
# fields inside a value that already parsed. Separate from search_worker.py's
# own MAX_HTML_BYTES, which bounds the *page* it reads before parsing it —
# this bounds the *response* it prints afterward.
MAX_RAW_CHARS = 65_536

STATUSES = frozenset({"complete", "partial", "unavailable", "failed"})
# Where in a live search a failure happened. Fixed and small on purpose — an
# open string here is a field a later worker could use to smuggle arbitrary
# text past validation one word at a time.
#
#   host    — Bubblewrap/worker lifecycle and host<->worker protocol
#             validation (either direction of that wire, not the page).
#   request — the one HTTPS search-page request: DNS/TLS/connect, the HTTP
#             status DuckDuckGo answered with, or its content type.
#   parse   — recognising and normalising whatever HTML came back.
#
# Replaces v1.7's `search | fetch | extract`, which were speculative names
# for stages nothing yet produced. These three are what the live path
# actually has.
STAGES = frozenset({"host", "request", "parse"})


class ProtocolError(Exception):
    """A request or response does not match the wire format. Raised by the
    *_build*/validate_* functions, which assume Python values already in
    hand; the parse_* functions catch this internally and never raise — see
    their own docstrings."""


# --- shared field validators ---------------------------------------------

def _bounded_str(value, max_chars, field):
    if not isinstance(value, str):
        raise ProtocolError(f"{field} must be a string")
    if not value:
        raise ProtocolError(f"{field} must not be empty")
    if len(value) > max_chars:
        raise ProtocolError(
            f"{field} is {len(value)} chars, over the {max_chars} limit")
    return value


def _no_extra_fields(obj, allowed, what):
    extra = set(obj) - allowed
    if extra:
        raise ProtocolError(f"{what} has unexpected fields: {sorted(extra)}")
    missing = allowed - set(obj)
    if missing:
        raise ProtocolError(f"{what} missing fields: {sorted(missing)}")


def _validate_evidence_item(item):
    if not isinstance(item, dict):
        raise ProtocolError("evidence item must be an object")
    _no_extra_fields(item, {"title", "url", "excerpt"}, "evidence item")
    title = _bounded_str(item["title"], MAX_TITLE_CHARS, "evidence.title")
    url = _bounded_str(item["url"], MAX_URL_CHARS, "evidence.url")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ProtocolError("evidence.url must be http:// or https://")
    excerpt = _bounded_str(item["excerpt"], MAX_EXCERPT_CHARS,
                           "evidence.excerpt")
    return {"title": title, "url": url, "excerpt": excerpt}


def _validate_failure_item(item):
    if not isinstance(item, dict):
        raise ProtocolError("failure item must be an object")
    _no_extra_fields(item, {"stage", "code"}, "failure item")
    stage = item["stage"]
    if stage not in STAGES:
        raise ProtocolError(
            f"failure.stage must be one of {sorted(STAGES)}, got {stage!r}")
    code = _bounded_str(item["code"], MAX_CODE_CHARS, "failure.code")
    return {"stage": stage, "code": code}


# --- responses -------------------------------------------------------------
#
# The state-combination rules are the point of this section, not the field
# shapes above. `complete` may carry empty evidence — the search ran and
# found nothing (DuckDuckGo's own explicit no-results page), a fact distinct
# from `unavailable` (could not even start). `partial` requires both
# evidence and a failure — it is what "some of it worked" looks like:
# fewer than the requested results parsed cleanly, at least one did.
# `unavailable` and `failed` both carry no evidence: `unavailable` is the
# boundary refusing to try (Bubblewrap, curl, the resolver or the CA bundle
# missing — nothing was sent); `failed` is an attempt that produced nothing
# usable. A response that claims evidence *and* `failed`, or a failure-free
# `partial`, is not a state for a reader to interpret — it's a protocol
# error, same as a bad type.

def validate_response(obj):
    """Validate an already-parsed response dict against every field limit
    and state-combination rule. Returns a normalized dict (key order fixed)
    on success, or raises ProtocolError naming the first problem found —
    used directly by the worker and the host's own synthetic failures, both
    of which start from trusted Python values, not text off a wire."""
    if not isinstance(obj, dict):
        raise ProtocolError("response must be a JSON object")
    _no_extra_fields(obj, {"protocol", "status", "evidence", "failures"},
                     "response")
    if obj["protocol"] != PROTOCOL_VERSION:
        raise ProtocolError(f"unknown protocol version: {obj['protocol']!r}")

    status = obj["status"]
    if status not in STATUSES:
        raise ProtocolError(
            f"status must be one of {sorted(STATUSES)}, got {status!r}")

    evidence_raw = obj["evidence"]
    if not isinstance(evidence_raw, list):
        raise ProtocolError("evidence must be a list")
    if len(evidence_raw) > MAX_EVIDENCE_ITEMS:
        raise ProtocolError(f"evidence has {len(evidence_raw)} items, over "
                            f"the {MAX_EVIDENCE_ITEMS} limit")
    evidence = [_validate_evidence_item(e) for e in evidence_raw]

    failures_raw = obj["failures"]
    if not isinstance(failures_raw, list):
        raise ProtocolError("failures must be a list")
    if len(failures_raw) > MAX_FAILURES:
        raise ProtocolError(f"failures has {len(failures_raw)} items, over "
                            f"the {MAX_FAILURES} limit")
    failures = [_validate_failure_item(f) for f in failures_raw]

    if status == "complete":
        if failures:
            raise ProtocolError("complete must carry no failures")
    elif status == "partial":
        if not evidence:
            raise ProtocolError("partial requires at least one evidence item")
        if not failures:
            raise ProtocolError("partial requires at least one failure")
    elif status == "unavailable":
        if evidence:
            raise ProtocolError("unavailable must carry no evidence")
        if not failures:
            raise ProtocolError("unavailable requires at least one failure")
    elif status == "failed":
        if evidence:
            raise ProtocolError(
                "failed must carry no evidence — that combination is partial")
        if not failures:
            raise ProtocolError("failed requires at least one failure")

    return {"protocol": PROTOCOL_VERSION, "status": status,
            "evidence": evidence, "failures": failures}


def build_response(status, evidence=None, failures=None):
    """Construct and validate a response from Python values. What the worker,
    and the host's own synthetic failures (timeout, crash, protocol error),
    use to guarantee they can only ever emit a shape this same module would
    also accept from the wire."""
    return validate_response({"protocol": PROTOCOL_VERSION, "status": status,
                              "evidence": evidence or [],
                              "failures": failures or []})


def dumps_response(status, evidence=None, failures=None):
    return json.dumps(build_response(status, evidence, failures))


def parse_response(raw):
    """Untrusted text (a worker's real stdout) -> (dict, None) on a fully
    valid response, or (None, reason) — never raises. This is the boundary
    function: the host calls this on every attempt, whatever the worker
    actually sent, because sharing search_protocol.py with the worker proves
    nothing about whether the worker used it honestly (see the module
    docstring).

    Checked in this order because each check assumes the previous one held:
    size, then syntax, then trailing bytes after the one JSON value, then
    shape. A worker that prints a valid response and then keeps writing is
    caught here rather than by json.loads silently reading only the prefix.
    """
    if raw is None:
        return None, "empty output"
    if len(raw) > MAX_RAW_CHARS:
        return None, f"output is over the {MAX_RAW_CHARS} char limit"
    stripped = raw.strip()
    if not stripped:
        return None, "empty output"
    try:
        obj, end = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    if stripped[end:].strip():
        return None, "trailing output after the JSON response"
    try:
        return validate_response(obj), None
    except ProtocolError as e:
        return None, str(e)


# --- requests ----------------------------------------------------------

def build_request(query):
    if not isinstance(query, str) or not query.strip():
        raise ProtocolError("query must be a non-empty string")
    if len(query) > MAX_QUERY_CHARS:
        raise ProtocolError(
            f"query is {len(query)} chars, over the {MAX_QUERY_CHARS} limit")
    return {"protocol": PROTOCOL_VERSION, "operation": "search",
            "query": query}


def dumps_request(query):
    return json.dumps(build_request(query))


def parse_request(raw):
    """Worker-side counterpart to parse_response: (query, None) or
    (None, reason), never raises. The host never sends anything invalid —
    this exists so the worker's own boundary is defined the same way the
    host's is, and so a test can drive the worker directly without a
    sandbox."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None, "invalid JSON"
    if not isinstance(obj, dict):
        return None, "request must be a JSON object"
    if obj.get("protocol") != PROTOCOL_VERSION:
        return None, f"unknown protocol version: {obj.get('protocol')!r}"
    if obj.get("operation") != "search":
        return None, f"unknown operation: {obj.get('operation')!r}"
    query = obj.get("query")
    if not isinstance(query, str) or not query.strip():
        return None, "query must be a non-empty string"
    if len(query) > MAX_QUERY_CHARS:
        return None, f"query is {len(query)} chars, over the " \
                     f"{MAX_QUERY_CHARS} limit"
    return query, None
