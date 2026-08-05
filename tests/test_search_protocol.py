#!/usr/bin/env python3
"""
test_search_protocol.py — the v1.9 web-search wire format. No API calls, no
subprocess, no sandbox: this is the protocol module in isolation, proving the
field limits and state-combination rules fire on their own before anything
crosses a process boundary.

    python3 tests/test_search_protocol.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import search_protocol as proto

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def rejects(fn, *args, **kwargs):
    """True if fn(*args, **kwargs) raises ProtocolError."""
    try:
        fn(*args, **kwargs)
        return False
    except proto.ProtocolError:
        return True


def parse_rejects(raw):
    """parse_response never raises; True if it reports a failure."""
    parsed, reason = proto.parse_response(raw)
    return parsed is None and bool(reason)


def main():
    print("--- valid responses are accepted ---")
    ok("complete with evidence",
       proto.build_response(
           "complete",
           evidence=[{"title": "A", "url": "https://x/y", "excerpt": "z"}])
       ["status"] == "complete")
    ok("truthful complete-empty",
       proto.build_response("complete")["evidence"] == [])
    ok("unavailable with a failure",
       proto.build_response(
           "unavailable",
           failures=[{"stage": "host", "code": "sandbox_unavailable"}])
       ["status"] == "unavailable")
    ok("partial with both evidence and a failure",
       proto.build_response(
           "partial",
           evidence=[{"title": "A", "url": "http://x", "excerpt": "z"}],
           failures=[{"stage": "parse", "code": "result_omitted"}])
       ["status"] == "partial")
    ok("failed with a failure and no evidence",
       proto.build_response(
           "failed",
           failures=[{"stage": "parse", "code": "markup_unrecognized"}])
       ["status"] == "failed")
    ok("http url accepted",
       not rejects(proto.build_response, "complete",
                  evidence=[{"title": "A", "url": "http://x", "excerpt": "z"}]))
    ok("no failure item carries a retryable field any more — v1.8 makes at "
       "most one attempt, so there is nothing left to flag as retryable",
       "retryable" not in proto.build_response(
           "failed", failures=[{"stage": "request",
                               "code": "connection_failed"}])["failures"][0])

    print("\n--- round trip: build -> dumps -> parse ---")
    dumped = proto.dumps_response(
        "partial",
        evidence=[{"title": "A", "url": "https://x", "excerpt": "e"}],
        failures=[{"stage": "parse", "code": "result_omitted"}])
    parsed, reason = proto.parse_response(dumped)
    ok("parses back to the same shape", parsed == proto.build_response(
        "partial",
        evidence=[{"title": "A", "url": "https://x", "excerpt": "e"}],
        failures=[{"stage": "parse", "code": "result_omitted"}]),
       (parsed, reason))
    ok("reason is None on success", reason is None)

    print("\n--- unknown protocol version ---")
    ok("build_response rejects it",
       rejects(proto.validate_response,
              {"protocol": 1, "status": "complete", "evidence": [],
               "failures": []}))
    ok("parse_response rejects it",
       parse_rejects('{"protocol": 1, "status": "complete", "evidence": [], '
                    '"failures": []}'))
    ok("parse_response rejects a missing version",
       parse_rejects('{"status": "complete", "evidence": [], "failures": []}'))

    print("\n--- extra / missing fields ---")
    ok("an extra top-level field is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "complete", "evidence": [],
               "failures": [], "extra": "field"}))
    ok("a missing top-level field is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "complete", "evidence": []}))
    ok("an extra evidence field is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "complete",
               "evidence": [{"title": "A", "url": "http://x",
                             "excerpt": "z", "score": 9}],
               "failures": []}))
    ok("a failure item still carrying 'retryable' is rejected — that field "
       "left the wire in v1.8",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "failed", "evidence": [],
               "failures": [{"stage": "request", "code": "x",
                             "retryable": False}]}))
    ok("an extra failure field is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "failed", "evidence": [],
               "failures": [{"stage": "request", "code": "x",
                             "raw": "trace"}]}))

    print("\n--- invalid types ---")
    ok("non-dict response is rejected",
       rejects(proto.validate_response, ["not", "a", "dict"]))
    ok("non-list evidence is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "complete", "evidence": "nope",
               "failures": []}))
    ok("unknown stage is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "failed", "evidence": [],
               "failures": [{"stage": "fetch", "code": "x"}]}))
    ok("a retired v1.7 stage name is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "failed", "evidence": [],
               "failures": [{"stage": "search", "code": "x"}]}))
    ok("a url that isn't http(s) is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "complete",
               "evidence": [{"title": "A", "url": "ftp://x",
                             "excerpt": "z"}],
               "failures": []}))
    ok("unknown status is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "pending", "evidence": [],
               "failures": []}))

    print("\n--- oversized fields, at v1.8's live limits ---")
    ok("an oversized title is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "complete",
               "evidence": [{"title": "x" * (proto.MAX_TITLE_CHARS + 1),
                             "url": "http://x", "excerpt": "z"}],
               "failures": []}))
    ok("an oversized excerpt is rejected (600 chars — DuckDuckGo's own "
       "snippet bound, not v1.7's placeholder 2000)",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "complete",
               "evidence": [{"title": "A", "url": "http://x",
                             "excerpt": "x" * (proto.MAX_EXCERPT_CHARS + 1)}],
               "failures": []}))
    ok("more than five evidence items is rejected — v1.8 bounds evidence to "
       "the first five organic results, not v1.7's placeholder ten",
       proto.MAX_EVIDENCE_ITEMS == 5 and
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "complete",
               "evidence": [{"title": "A", "url": "http://x", "excerpt": "z"}]
                            * (proto.MAX_EVIDENCE_ITEMS + 1),
               "failures": []}))
    ok("too many failures is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "failed", "evidence": [],
               "failures": [{"stage": "request", "code": "x"}]
                            * (proto.MAX_FAILURES + 1)}))
    ok("build_request rejects an oversized query",
       rejects(proto.build_request, "x" * (proto.MAX_QUERY_CHARS + 1)))
    ok("parse_response rejects oversized raw output",
       parse_rejects("x" * (proto.MAX_RAW_CHARS + 1)))

    print("\n--- v1.9: http_status on request/source_refused ---")

    def _refusal(http_status=None, **overrides):
        item = {"stage": "request", "code": "source_refused"}
        if http_status is not None:
            item["http_status"] = http_status
        item.update(overrides)
        return {"protocol": proto.PROTOCOL_VERSION, "status": "failed",
                "evidence": [], "failures": [item]}

    ok("a valid refusal round-trips with its http_status intact",
       proto.validate_response(_refusal(403))
       ["failures"][0]["http_status"] == 403)
    ok("the boundary low end (100) is accepted",
       not rejects(proto.validate_response, _refusal(100)))
    ok("the boundary high end (599) is accepted",
       not rejects(proto.validate_response, _refusal(599)))
    dumped = proto.dumps_response(
        "failed", failures=[{"stage": "request", "code": "source_refused",
                             "http_status": 429}])
    parsed, reason = proto.parse_response(dumped)
    ok("build -> dumps -> parse keeps the integer, not a stringified one",
       parsed is not None
       and parsed["failures"][0]["http_status"] == 429
       and reason is None, (parsed, reason))

    ok("missing http_status on a refusal is rejected",
       rejects(proto.validate_response, _refusal(None)))
    ok("a string http_status is rejected",
       rejects(proto.validate_response, _refusal("403")))
    ok("a boolean http_status is rejected — bool is an int subclass",
       rejects(proto.validate_response, _refusal(True)))
    ok("...False too",
       rejects(proto.validate_response, _refusal(False)))
    ok("an out-of-range http_status (99) is rejected",
       rejects(proto.validate_response, _refusal(99)))
    ok("an out-of-range http_status (600) is rejected",
       rejects(proto.validate_response, _refusal(600)))

    ok("http_status on a non-refusal request failure is rejected — "
       "redirects carry no status",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "failed",
               "evidence": [],
               "failures": [{"stage": "request", "code": "source_redirected",
                             "http_status": 302}]}))
    ok("http_status on a host-stage failure is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "failed",
               "evidence": [],
               "failures": [{"stage": "host", "code": "protocol_error",
                             "http_status": 500}]}))
    ok("http_status on a parse-stage failure is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "failed",
               "evidence": [],
               "failures": [{"stage": "parse", "code": "markup_unrecognized",
                             "http_status": 500}]}))
    ok("every other failure keeps the plain two-field shape untouched",
       set(proto.build_response(
           "unavailable",
           failures=[{"stage": "host", "code": "sandbox_unavailable"}]
       )["failures"][0]) == {"stage", "code"})

    ok("a v2 reply (this refusal's own shape, minus http_status, at the old "
       "protocol number) fails closed on the version alone",
       parse_rejects(json.dumps(
           {"protocol": 2, "status": "failed", "evidence": [],
            "failures": [{"stage": "request", "code": "source_refused"}]})))

    print("\n--- invalid state combinations ---")
    ok("complete with a failure is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "complete", "evidence": [],
               "failures": [{"stage": "parse", "code": "x"}]}))
    ok("partial with no evidence is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "partial", "evidence": [],
               "failures": [{"stage": "parse", "code": "x"}]}))
    ok("partial with no failure is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "partial",
               "evidence": [{"title": "A", "url": "http://x",
                             "excerpt": "z"}],
               "failures": []}))
    ok("unavailable with evidence is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "unavailable",
               "evidence": [{"title": "A", "url": "http://x",
                             "excerpt": "z"}],
               "failures": [{"stage": "host", "code": "x"}]}))
    ok("unavailable with no failure is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "unavailable", "evidence": [],
               "failures": []}))
    ok("failed with evidence is rejected (that's partial, not failed)",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "failed",
               "evidence": [{"title": "A", "url": "http://x",
                             "excerpt": "z"}],
               "failures": [{"stage": "parse", "code": "x"}]}))
    ok("failed with no failure is rejected",
       rejects(proto.validate_response,
              {"protocol": proto.PROTOCOL_VERSION, "status": "failed", "evidence": [],
               "failures": []}))

    print("\n--- parse_response: malformed wire text never raises ---")
    ok("invalid JSON", parse_rejects("{not json"))
    ok("empty output", parse_rejects(""))
    ok("empty output (whitespace only)", parse_rejects("   \n  "))
    ok("None input", parse_rejects(None))
    ok("trailing output after a valid JSON value",
       parse_rejects(proto.dumps_response("complete") + "\nextra garbage"))
    ok("a JSON array instead of an object",
       parse_rejects("[1, 2, 3]"))
    ok("a bare JSON string",
       parse_rejects('"just a string"'))

    print("\n--- requests ---")
    ok("build_request accepts a bounded query",
       proto.build_request("cats")["query"] == "cats")
    ok("build_request rejects an empty query",
       rejects(proto.build_request, ""))
    ok("build_request rejects whitespace-only",
       rejects(proto.build_request, "   "))
    ok("build_request rejects a non-string query",
       rejects(proto.build_request, 42))

    q, err = proto.parse_request(proto.dumps_request("best cat food"))
    ok("parse_request round-trips a real request",
       q == "best cat food" and err is None, (q, err))
    q, err = proto.parse_request('{"protocol": 1, "operation": "search", '
                                 '"query": "x"}')
    ok("parse_request rejects the wrong (v1.7) version", q is None and err, err)
    q, err = proto.parse_request(
        f'{{"protocol": {proto.PROTOCOL_VERSION}, "operation": "fetch", '
        f'"query": "x"}}')
    ok("parse_request rejects the wrong operation", q is None and err, err)
    q, err = proto.parse_request(
        f'{{"protocol": {proto.PROTOCOL_VERSION}, "operation": "search"}}')
    ok("parse_request rejects a missing query", q is None and err, err)
    q, err = proto.parse_request("not even json")
    ok("parse_request never raises on garbage", q is None and err, err)
    q, err = proto.parse_request(
        f'{{"protocol": {proto.PROTOCOL_VERSION}, "operation": "search", '
        f'"query": "{"x" * (proto.MAX_QUERY_CHARS + 1)}"}}')
    ok("parse_request rejects an oversized query", q is None and err, err)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
