#!/usr/bin/env python3
"""test_titles.py — a failed title call is a real failure, not "(untitled)".

    python3 tests/test_titles.py

`D-13`: `generate_title` used to swallow every exception and return the
literal string `"(untitled)"`, which is also the placeholder `main.py` shows
before any title exists — so a caller had no way to tell "the request failed"
from "no title has been attempted yet" without comparing text. This pins the
replacement: `generate_title` returns a usable, normalised title or raises
`api.TitleGenerationError`, for the three ways a title call can fail —
transport, empty, and malformed — with `call_api` stubbed. No network, no API
key.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

import api

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def main_():
    print("\n--- a usable response normalises to a title ---")
    api.call_api = lambda messages, model=None, tools=None, read_timeout=None: {
        "choices": [{"message": {"content": '"A Chat About Cats"\n'}}]}
    title = api.generate_title("tell me about cats")
    ok("quotes are stripped", title == "A Chat About Cats", title)

    api.call_api = lambda *a, **k: {
        "choices": [{"message": {"content": "Trailing Punctuation..."}}]}
    ok("trailing punctuation is stripped",
       api.generate_title("x") == "Trailing Punctuation", api.generate_title("x"))

    api.call_api = lambda *a, **k: {
        "choices": [{"message": {"content": "x" * 80}}]}
    long_title = api.generate_title("x")
    ok("an overlong title is truncated to 60 chars with an ellipsis",
       len(long_title) == 60 and long_title.endswith("..."), long_title)

    print("\n--- transport failure becomes TitleGenerationError ---")
    def boom(*a, **k):
        raise ConnectionError("connection refused")
    api.call_api = boom
    try:
        api.generate_title("x")
        ok("a transport failure raises", False)
    except api.TitleGenerationError as e:
        ok("a transport failure raises TitleGenerationError", True)
        ok("...and preserves the underlying detail",
           "connection refused" in str(e), str(e))
    except Exception as e:
        ok("a transport failure raises TitleGenerationError, not something "
           "else", False, repr(e))

    print("\n--- an empty response becomes TitleGenerationError ---")
    api.call_api = lambda *a, **k: {
        "choices": [{"message": {"content": "   "}}]}
    try:
        api.generate_title("x")
        ok("whitespace-only content raises", False)
    except api.TitleGenerationError as e:
        ok("whitespace-only content raises TitleGenerationError", True, str(e))

    api.call_api = lambda *a, **k: {
        "choices": [{"message": {"content": "...\"\""}}]}
    try:
        api.generate_title("x")
        ok("content that normalises to nothing raises", False)
    except api.TitleGenerationError as e:
        ok("content that normalises to nothing raises TitleGenerationError",
           True, str(e))

    print("\n--- a malformed response shape becomes TitleGenerationError ---")
    for label, bad in (
        ("no choices", {"choices": []}),
        ("no message", {"choices": [{}]}),
        ("no content key", {"choices": [{"message": {}}]}),
        ("content is not a string", {"choices": [{"message": {"content": None}}]}),
        ("not even a dict", "not a response"),
    ):
        api.call_api = lambda *a, __bad=bad, **k: __bad
        try:
            api.generate_title("x")
            ok(f"malformed response ({label}) raises", False)
        except api.TitleGenerationError as e:
            ok(f"malformed response ({label}) raises TitleGenerationError",
               True, str(e))
        except Exception as e:
            ok(f"malformed response ({label}) raises TitleGenerationError, "
               "not something else", False, repr(e))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
