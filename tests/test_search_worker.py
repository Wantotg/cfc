#!/usr/bin/env python3
"""
test_search_worker.py — search_worker.py's own logic, in isolation: text
cleanup, URL validation, HTTP-status/content-type classification, and the
HTML parser. No network, no subprocess, no sandbox — this file drives the
pure functions directly with fixture HTML, which is what lets it run
anywhere and stay fast.

The fixtures below are trimmed, structurally faithful copies of markup
captured live against https://html.duckduckgo.com/html/ on 2026-08-04 (the
same date Concept.md's own evidence was gathered) — real class names
(`result__a`, `result__snippet`, `result--ad`, `no-results`), not guesses.
That is also this file's stated limit: it proves search_worker.py parses
*this* markup correctly, not that DuckDuckGo will keep serving it — see
Concept.md's "not a claim that the public page will remain compatible" and
HANDOVER.md's producer/parser table.

    python3 tests/test_search_worker.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import search_protocol as proto
import search_worker as worker

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


# --- fixture builders --------------------------------------------------
#
# Real result cards nest a few layers of markup that never matters to the
# parser (icon spans, the displayed-URL line) — trimmed here to the layers
# that do, which is also what keeps a fixture from silently overfitting to
# the parser's own implementation instead of the real page's shape.

def _card(href, title, snippet, ad=False):
    ad_class = " result--ad" if ad else ""
    return f'''
    <div class="result results_links results_links_deep web-result{ad_class}">
      <div class="links_main links_deep result__body">
        <h2 class="result__title">
          <a rel="nofollow" class="result__a" href="{href}">{title}</a>
        </h2>
        <div class="result__extras">
          <div class="result__extras__url">
            <a class="result__url" href="{href}">{href}</a>
          </div>
        </div>
        <a class="result__snippet" href="{href}">{snippet}</a>
        <div class="clear"></div>
      </div>
    </div>
    '''


def _card_no_snippet(href, title):
    """A result-shaped card missing its snippet — the malformed case."""
    return f'''
    <div class="result results_links results_links_deep web-result">
      <div class="links_main links_deep result__body">
        <h2 class="result__title">
          <a rel="nofollow" class="result__a" href="{href}">{title}</a>
        </h2>
        <div class="clear"></div>
      </div>
    </div>
    '''


_NO_RESULTS_CARD = '''
    <div class="result results_links results_links_deep web-result result--no-result">
      <div class="links_main links_deep result__body">
        <div class="no-results__container result__title">
          <span class='no-results'>
            <div class="no-results__message">
              <h1>No results found for <strong>query</strong></h1>
            </div>
          </span>
        </div>
        <div class="clear"></div>
      </div>
    </div>
    '''


def _page(*cards):
    return ('<html><body><div id="links" class="results">'
            + "".join(cards) + "</div></body></html>")


def main():
    print("--- _clean_text: whitespace, control chars, bidi overrides, "
          "length bound ---")
    ok("collapses internal whitespace",
       worker._clean_text("a   b\n\tc", 100) == "a b c")
    ok("strips a C0 control character",
       worker._clean_text("a\x07b", 100) == "ab")
    ok("strips a bidirectional-override character",
       worker._clean_text("a‮b", 100) == "ab")
    ok("bounds the length",
       len(worker._clean_text("x" * 50, 10)) == 10)
    ok("keeps ordinary unicode text",
       worker._clean_text("café ☕", 100) == "café ☕")

    print("\n--- _clean_url: what a result href is allowed to become ---")
    ok("a plain https url is accepted",
       worker._clean_url("https://example.com/a") == "https://example.com/a")
    ok("a plain http url is accepted",
       worker._clean_url("http://example.com/a") == "http://example.com/a")
    ok("a protocol-relative url is upgraded to https",
       worker._clean_url("//example.com/a") == "https://example.com/a")
    ok("ftp is rejected",
       worker._clean_url("ftp://example.com/a") is None)
    ok("javascript: is rejected",
       worker._clean_url("javascript:alert(1)") is None)
    ok("empty/missing href is rejected",
       worker._clean_url(None) is None and worker._clean_url("") is None)
    ok("a control character in the url is rejected",
       worker._clean_url("https://example.com/\x07") is None)
    ok("an oversized url is rejected",
       worker._clean_url("https://example.com/" + "x" * proto.MAX_URL_CHARS)
       is None)
    ok("DuckDuckGo's own /l/?uddg= redirect link is decoded to its "
       "destination, never requested",
       worker._clean_url(
           "/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FCat&rut=x")
       == "https://en.wikipedia.org/wiki/Cat")
    ok("a /l/ link with no uddg param is rejected rather than guessed at",
       worker._clean_url("/l/?rut=x") is None)

    print("\n--- _content_type_ok / _http_failure_code ---")
    ok("text/html is accepted",
       worker._content_type_ok("text/html; charset=UTF-8"))
    ok("bare text/html is accepted",
       worker._content_type_ok("text/html"))
    ok("application/json is rejected",
       not worker._content_type_ok("application/json"))
    ok("empty content-type is rejected",
       not worker._content_type_ok(""))
    ok("200 needs no failure code", worker._http_failure_code(200) is None)
    ok("301 is a redirect",
       worker._http_failure_code(301) == "source_redirected")
    ok("302 is a redirect",
       worker._http_failure_code(302) == "source_redirected")
    for code in (202, 403, 429, 500):
        ok(f"{code} is source_refused, not treated as success",
           worker._http_failure_code(code) == "source_refused")

    print("\n--- _parse_page: a normal page ---")
    page = _page(
        _card("https://en.wikipedia.org/wiki/Cat", "Cat - Wikipedia",
             "The cat is a small domesticated <b>carnivorous</b> mammal."),
        _card("https://example.com/breeds", "Cat Breeds",
             "A list of cat breeds."))
    status, evidence, failures = worker._parse_page(page)
    ok("status is complete", status == "complete", status)
    ok("both cards parsed, in page order",
       [e["title"] for e in evidence] == ["Cat - Wikipedia", "Cat Breeds"],
       evidence)
    ok("the snippet's nested <b> tag contributes text, not markup",
       "carnivorous" in evidence[0]["excerpt"]
       and "<b>" not in evidence[0]["excerpt"], evidence[0])
    ok("no failures on a clean page", failures == [], failures)

    print("\n--- _parse_page: sponsored cards are excluded, not counted "
          "as an omission ---")
    page = _page(
        _card("https://ads.example/1", "Sponsored", "buy now", ad=True),
        _card("https://en.wikipedia.org/wiki/Cat", "Cat - Wikipedia",
             "the real result"))
    status, evidence, failures = worker._parse_page(page)
    ok("status is complete — excluding an ad is not an omission",
       status == "complete", status)
    ok("only the organic result is returned",
       [e["title"] for e in evidence] == ["Cat - Wikipedia"], evidence)
    ok("no result_omitted failure from the excluded ad",
       failures == [], failures)

    print("\n--- _parse_page: more than five results is a truthful "
          "complete, capped — not a failure ---")
    cards = [_card(f"https://example.com/{i}", f"Title {i}", f"Snippet {i}")
             for i in range(8)]
    status, evidence, failures = worker._parse_page(_page(*cards))
    ok("status is complete", status == "complete", status)
    ok("evidence is capped at five",
       len(evidence) == proto.MAX_EVIDENCE_ITEMS == 5, len(evidence))
    ok("the first five, in order",
       [e["title"] for e in evidence] == [f"Title {i}" for i in range(5)],
       evidence)

    print("\n--- _parse_page: a malformed card alongside a good one is "
          "partial, with the evidence that did parse ---")
    page = _page(
        _card("https://en.wikipedia.org/wiki/Cat", "Cat - Wikipedia",
             "a real result"),
        _card_no_snippet("https://example.com/broken", "Missing Snippet"))
    status, evidence, failures = worker._parse_page(page)
    ok("status is partial", status == "partial", status)
    ok("the good card is kept",
       len(evidence) == 1 and evidence[0]["title"] == "Cat - Wikipedia",
       evidence)
    ok("failures name the omission",
       failures == [{"stage": "parse", "code": "result_omitted"}], failures)

    print("\n--- _parse_page: DuckDuckGo's own explicit no-results page ---")
    status, evidence, failures = worker._parse_page(_page(_NO_RESULTS_CARD))
    ok("status is complete", status == "complete", status)
    ok("evidence is truthfully empty", evidence == [], evidence)
    ok("no failure — an explicit empty result is not an error",
       failures == [], failures)

    print("\n--- _parse_page: unrecognised markup never becomes a false "
          "empty result ---")
    status, evidence, failures = worker._parse_page(
        "<html><body><p>this page matches no known state</p></body></html>")
    ok("status is failed, not complete-with-nothing",
       status == "failed", status)
    ok("evidence is empty", evidence == [], evidence)
    ok("failure names the real cause",
       failures == [{"stage": "parse", "code": "markup_unrecognized"}],
       failures)

    print("\n--- _parse_page never raises, even on a parser exception ---")
    status, evidence, failures = worker._parse_page("<div class=result>"
                                                     "<div><div><div>")
    ok("an unbalanced page still returns a typed result",
       status in proto.STATUSES, status)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
