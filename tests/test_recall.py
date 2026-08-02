#!/usr/bin/env python3
"""test_recall.py — the one place `/recall` compacts excess blank lines in
retrieved wiki excerpts before its tool-free synthesis request, and nowhere
else touches the source text.

    python3 tests/test_recall.py

Concept.md's inventory is the claim under test: this is eligible because the
request built here is a dedicated model call whose text is never parsed back,
stored, or quoted. Everything else — the hit dict itself, `/remember`'s
envelope, stored messages — stays exact. No network, no API key.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import recall

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def hit(text, **over):
    base = dict(chunk_id=1, text=text, kind="message", session_id=1,
                session_title="a page", created_at="2026-08-01T00:00:00+00:00",
                distance=0.5, source_uuid="wiki-1", source="wiki")
    base.update(over)
    return base


# --- _compact_spacing / _is_plain_prose: the pure helper --------------------

def test_compacts_ordinary_prose():
    print("\n--- ordinary prose: excess blank lines collapse to one ---")
    text = "First paragraph.\n\n\n\nSecond paragraph."
    out = recall._compact_spacing(text)
    ok("three blank lines become one",
       out == "First paragraph.\n\nSecond paragraph.", out)

    single = "First paragraph.\n\nSecond paragraph."
    ok("a single blank line is left alone",
       recall._compact_spacing(single) == single, recall._compact_spacing(single))

    none_blank = "First paragraph.\nSecond paragraph."
    ok("no blank line, nothing to do",
       recall._compact_spacing(none_blank) == none_blank)

    multi = "One.\n\n\nTwo.\n\n\n\n\nThree."
    ok("more than one run, each collapses independently",
       recall._compact_spacing(multi) == "One.\n\nTwo.\n\nThree.",
       recall._compact_spacing(multi))


def test_leaves_non_empty_lines_untouched():
    print("\n--- non-empty lines: order and characters survive ---")
    text = "alpha\n\n\nbeta — em dash, 'quote', naïve\n\n\ngamma!"
    out = recall._compact_spacing(text)
    for line in ("alpha", "beta — em dash, 'quote', naïve", "gamma!"):
        ok(f"{line!r} survives byte for byte", line in out.splitlines())
    ok("order is preserved",
       [l for l in out.splitlines() if l] == ["alpha",
        "beta — em dash, 'quote', naïve", "gamma!"], out)


def test_fenced_code_is_exact():
    print("\n--- fenced code: the whole excerpt stays exact ---")
    text = ("Some prose.\n\n\n\n"
            "```python\n"
            "def f():\n"
            "\n\n"
            "    return 1\n"
            "```\n\n\n"
            "More prose.")
    out = recall._compact_spacing(text)
    ok("a fenced block leaves the excerpt untouched", out == text, out)


def test_indented_code_is_exact():
    print("\n--- indented code: the whole excerpt stays exact ---")
    text = "Prose.\n\n\n    indented code line\n\n\nMore prose."
    out = recall._compact_spacing(text)
    ok("an indented-code line leaves the excerpt untouched", out == text, out)


def test_markdown_structure_is_exact():
    print("\n--- Markdown structure: the whole excerpt stays exact ---")
    cases = {
        "heading": "# A heading\n\n\nSome text.",
        "list": "- one\n\n\n- two",
        "ordered list": "1. one\n\n\n2. two",
        "blockquote": "> quoted\n\n\n> more",
        "table": "| a | b |\n\n\n| c | d |",
    }
    for name, text in cases.items():
        out = recall._compact_spacing(text)
        ok(f"{name}: untouched", out == text, out)


def test_unclosed_fence_is_exact():
    print("\n--- an unpaired fence leaves the whole excerpt exact ---")
    text = "Prose before.\n\n\n```python\ndef f():\n\n\n    return 1\n\nProse after, never closed."
    out = recall._compact_spacing(text)
    ok("an unclosed fence is not compacted at all", out == text, out)


# --- build_context / recall(): the request boundary -------------------------

def test_build_context_uses_compacted_text_only():
    print("\n--- build_context: the request text is compacted, hits are not ---")
    hits = [hit("First.\n\n\n\nSecond.")]
    ctx = recall.build_context(hits)
    ok("the request text has the excess blank lines removed",
       "First.\n\nSecond." in ctx and "First.\n\n\n\nSecond." not in ctx, ctx)
    ok("the hit dict itself is untouched",
       hits[0]["text"] == "First.\n\n\n\nSecond.", hits[0]["text"])


def test_recall_request_boundary(monkeypatch=None):
    print("\n--- recall(): the provider request is compacted, the returned "
          "hits are exact ---")
    prose_hit = hit("Paragraph one.\n\n\n\nParagraph two.", session_title="prose page")
    code_hit = hit("Text.\n\n\n```\ncode line\n\n\nmore code\n```\n\n\nTail.",
                   chunk_id=2, source_uuid="wiki-2", session_title="code page")
    given_hits = [prose_hit, code_hit]

    real_search = recall.search
    recall.search = lambda *a, **k: given_hits

    import httpx
    real_post = httpx.post
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "an answer"}}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return FakeResponse()

    httpx.post = fake_post
    try:
        answer, hits = recall.recall("unused.db", "a question")
    finally:
        recall.search = real_search
        httpx.post = real_post

    ok("recall() reached the provider call", answer == "an answer", answer)
    user_content = captured["json"]["messages"][1]["content"]
    ok("the prose excerpt's excess blank lines are compacted in the request",
       "Paragraph one.\n\nParagraph two." in user_content
       and "Paragraph one.\n\n\n\nParagraph two." not in user_content,
       user_content)
    ok("the fenced excerpt reaches the request exactly, blank lines and all",
       "code line\n\n\nmore code" in user_content, user_content)

    ok("the returned hits are the exact objects search() gave back",
       hits[0]["text"] == "Paragraph one.\n\n\n\nParagraph two."
       and hits[1]["text"] == "Text.\n\n\n```\ncode line\n\n\nmore code\n```\n\n\nTail.",
       [h["text"] for h in hits])


# --- the boundary is single: /remember never compacts -----------------------

def test_remember_envelope_stays_exact():
    print("\n--- /remember's envelope never compacts ---")
    import commands
    hits = [hit("First.\n\n\n\nSecond.")]
    envelope = commands.build_envelope("a query", hits)
    ok("build_envelope carries the excess blank lines through unchanged",
       "First.\n\n\n\nSecond." in envelope, envelope)


def main():
    test_compacts_ordinary_prose()
    test_leaves_non_empty_lines_untouched()
    test_fenced_code_is_exact()
    test_indented_code_is_exact()
    test_markdown_structure_is_exact()
    test_unclosed_fence_is_exact()
    test_build_context_uses_compacted_text_only()
    test_recall_request_boundary()
    test_remember_envelope_stays_exact()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
