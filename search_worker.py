# search_worker.py — the v1.8 live search worker.
#
# Runs *inside* the Bubblewrap sandbox websearch.py builds: no filesystem
# beyond its own read-only mounts, a cleared environment, and — new in
# v1.8 — the host's network namespace, shared rather than isolated (the one
# guarantee websearch.py's own header calls out as changed). Depends on
# nothing but the stdlib and search_protocol.py, mounted beside it at the
# same sandboxed path — no other cfc import exists to reach for, since
# nothing else is mounted.
#
# One request, once: read the request from stdin, make exactly one curl call
# to DuckDuckGo's documented non-JS results page, parse what came back into
# the shared protocol shape, print it, exit. There is no retry in here and
# none in websearch.py either — Concept.md's one-approval/one-attempt rule
# means this file gets one chance to be honest about what happened.
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlsplit

import search_protocol as proto

DDG_URL = "https://html.duckduckgo.com/html/"
# Absolute, like websearch.py's SANDBOX_PYTHON — this file never imports
# anything of cfc's own to resolve a path, and `/usr` is exactly what the
# sandbox ro-binds, so this is the same binary on both sides of the boundary.
CURL_BINARY = "/usr/bin/curl"
USER_AGENT = "cfc-web-search/1.8"

CONNECT_TIMEOUT = 5          # seconds curl is given to establish the TCP+TLS
                              # connection
TOTAL_TIMEOUT = 12           # seconds curl is given for the whole exchange
# The host's own subprocess timeout (websearch.HOST_TIMEOUT) is set longer
# than this, so a curl that is behaving — even right up to its own limit —
# is never the thing that trips the host's separate worker_timeout.
SUBPROCESS_MARGIN = 3

# A defense-in-depth wire-level cap, generous on purpose: curl aborts a
# transfer that exceeds this before decompression even finishes. The
# authoritative limit Concept.md actually specifies — 64 KiB of *decompressed*
# HTML — is enforced below in Python, after curl hands back a real byte
# count, because --max-filesize cannot see through gzip on its own.
MAX_TRANSFER_BYTES = 1_048_576
MAX_HTML_BYTES = 65_536

MAX_RESULTS = proto.MAX_EVIDENCE_ITEMS

# Bidirectional-override and other formatting control characters: safe to
# delete outright, never meaningful in a title or snippet, and exactly the
# class of character that can make displayed text lie about its own content.
_BIDI_STRIP = dict.fromkeys(
    [0x200E, 0x200F, 0x061C, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E,
     0x2066, 0x2067, 0x2068, 0x2069], None)


def _clean_text(text, max_chars):
    """Collapse whitespace, drop C0 controls and bidi overrides, bound the
    length. Applied to every title and excerpt before it is ever considered
    for the response — text.HTMLParser already decodes entities
    (convert_charrefs=True), so this is purely about what a hostile or
    merely messy page could still smuggle through as "plain" text."""
    text = "".join(ch for ch in text if ch == " " or ch == "\n"
                   or ch == "\t" or ord(ch) >= 0x20)
    text = text.translate(_BIDI_STRIP)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _clean_url(href):
    """A result's href, resolved and validated, or None if it cannot be
    trusted as a destination. Handles DuckDuckGo's own `/l/?uddg=...`
    redirect-through-us link, if the page ever serves one, by decoding the
    destination rather than requesting it — the whole point of the no-
    second-request rule (Concept.md) is that a returned link is data, never
    a fetch instruction.

    Validation runs on the final destination, after any `uddg` decoding: a
    URL carrying login credentials (`user:pass@host`) or any of the same C0
    control / bidi-override characters stripped from title and snippet text
    is rejected outright rather than cleaned — this function never repairs
    a bad URL into an apparently safe one, it only ever returns the
    original or nothing."""
    if not href:
        return None
    href = href.strip()
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlsplit(href)
    if parsed.path == "/l/" and (
            parsed.netloc == "" or "duckduckgo.com" in parsed.netloc):
        dest = parse_qs(parsed.query).get("uddg", [None])[0]
        if not dest:
            return None
        href = unquote(dest)
        parsed = urlsplit(href)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if any(ord(c) < 0x20 or ord(c) in _BIDI_STRIP for c in href):
        return None
    if len(href) > proto.MAX_URL_CHARS:
        return None
    return href


class _ResultParser(HTMLParser):
    """Extracts DuckDuckGo's html.duckduckgo.com/html/ result cards.

    A producer/parser pair across a boundary this codebase cannot close
    (HANDOVER.md) — this class recognises the `result__*` class names and
    the `no-results` marker measured live against the real page on
    2026-08-04. A markup change degrades to `parse/markup_unrecognized`,
    never to a false empty list: an unrecognised page and a truthful zero
    are different claims and must stay distinguishable.

    One result card is: an outer `<div class="result ...">` container,
    containing exactly one `<a class="result__a" href=...>title</a>` and one
    `<a class="result__snippet" href=...>excerpt</a>`. Cards are delimited by
    tracking `<div>` nesting depth from the outer container back to zero,
    since nothing in this page gives a result an explicit end marker of its
    own.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []      # completed {"title", "url", "excerpt"}
        self.omitted = 0       # result-shaped containers that didn't parse
        self.saw_no_results = False
        self._in_result = False
        self._depth = 0
        self._href = None
        self._title_parts = None
        self._snippet_parts = None
        self._in_title = False
        self._in_snippet = False

    @staticmethod
    def _classes(attrs):
        for k, v in attrs:
            if k == "class":
                return (v or "").split()
        return []

    def handle_starttag(self, tag, attrs):
        classes = self._classes(attrs)
        if not self._in_result:
            if tag == "div" and "result" in classes:
                # Sponsored cards carry a "result--ad" token alongside
                # "result" itself. Concept.md promises organic results only,
                # so an ad card is never entered — not a card, not an
                # omission, simply not there as far as this parser is
                # concerned.
                if any(c.startswith("result--ad") for c in classes):
                    return
                self._in_result = True
                self._depth = 1
                self._href = None
                self._title_parts = []
                self._snippet_parts = []
            return

        if tag == "div":
            self._depth += 1
        if "no-results" in classes:
            self.saw_no_results = True
        elif tag == "a" and "result__a" in classes:
            self._in_title = True
            self._href = dict(attrs).get("href")
        elif tag == "a" and "result__snippet" in classes:
            self._in_snippet = True

    def handle_endtag(self, tag):
        if not self._in_result:
            return
        if tag == "a":
            self._in_title = False
            self._in_snippet = False
        elif tag == "div":
            self._depth -= 1
            if self._depth <= 0:
                self._close_result()

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)
        elif self._in_snippet:
            self._snippet_parts.append(data)

    def _close_result(self):
        self._in_result = False
        title = _clean_text("".join(self._title_parts), proto.MAX_TITLE_CHARS)
        excerpt = _clean_text("".join(self._snippet_parts),
                              proto.MAX_EXCERPT_CHARS)
        url = _clean_url(self._href)
        if title and excerpt and url:
            self.results.append({"title": title, "url": url,
                                 "excerpt": excerpt})
        elif self._href or self._title_parts or self._snippet_parts:
            # A result-shaped container that didn't yield a complete card —
            # the no-results container also lands here (empty parts, no
            # href), which is why saw_no_results is checked ahead of
            # `omitted` by the caller rather than folded into this count.
            self.omitted += 1


def _parse_page(html_text):
    """(status, evidence, failures) for one page of HTML, already decoded
    and size-checked. Never raises — a parser exception is itself a shape
    this page didn't match, which is what markup_unrecognized means."""
    parser = _ResultParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:
        return "failed", [], [{"stage": "parse", "code": "markup_unrecognized"}]

    if parser._in_result:
        # The HTML ended with a result container still open. HTMLParser
        # never synthesizes the missing closing tag, so _close_result was
        # never called for it — counted as omitted here instead,
        # unconditionally, rather than through _close_result: a card that
        # happens to look complete except for its missing closing tag is
        # still truncated, not a small truthful complete.
        parser.omitted += 1

    results = parser.results[:MAX_RESULTS]
    if len(results) >= MAX_RESULTS:
        return "complete", results, []
    if results and not parser.omitted:
        # Fewer than the cap, but nothing was malformed — the page simply
        # doesn't have more. A truthful smaller complete, not a partial.
        return "complete", results, []
    if results:
        return "partial", results, [{"stage": "parse", "code": "result_omitted"}]
    if parser.saw_no_results:
        return "complete", [], []
    return "failed", [], [{"stage": "parse", "code": "markup_unrecognized"}]


def _content_type_ok(content_type):
    return content_type.split(";", 1)[0].strip().lower() == "text/html"


def _http_failure_code(http_code):
    """None if this status should be parsed, else the request-stage code."""
    if http_code == 200:
        return None
    if 300 <= http_code < 400:
        return "source_redirected"
    return "source_refused"


def _run_curl(query):
    """One curl attempt. Returns (http_code, content_type, body_text, None)
    on a completed HTTP exchange (whatever the status), or
    (None, None, None, code) on a transport-level failure that never
    produced a usable HTTP response at all."""
    with tempfile.TemporaryDirectory() as tmp:
        body_path = f"{tmp}/body"
        headers_path = f"{tmp}/headers"
        args = [
            CURL_BINARY,
            "-q",                      # first arg: ignore any .curlrc
            "--silent", "--show-error",
            "--connect-timeout", str(CONNECT_TIMEOUT),
            "--max-time", str(TOTAL_TIMEOUT),
            "--max-filesize", str(MAX_TRANSFER_BYTES),
            "--compressed",
            "-A", USER_AGENT,
            "-D", headers_path,
            "-o", body_path,
            "-w", "%{http_code}",
            "--data-urlencode", "q@-",
            DDG_URL,
        ]
        try:
            proc = subprocess.run(
                args, input=query.encode("utf-8"), capture_output=True,
                timeout=TOTAL_TIMEOUT + SUBPROCESS_MARGIN)
        except subprocess.TimeoutExpired:
            return None, None, None, "request_timeout"
        except OSError:
            return None, None, None, "connection_failed"

        # curl exit codes: https://curl.se/libcurl/c/libcurl-errors.html
        if proc.returncode == 28:
            return None, None, None, "request_timeout"
        if proc.returncode == 63:
            return None, None, None, "response_too_large"
        if proc.returncode != 0:
            return None, None, None, "connection_failed"

        try:
            http_code = int(proc.stdout.decode("ascii", "replace").strip())
        except ValueError:
            return None, None, None, "connection_failed"
        if not (proto.MIN_HTTP_STATUS <= http_code <= proto.MAX_HTTP_STATUS):
            # curl prints 000 when the write-out never got a real status —
            # the connection was reset, TLS failed, or the transfer never
            # completed a response line at all. That's the same "nothing
            # usable came back" as the transport failures above, not a
            # status DuckDuckGo actually sent, so it stays a transport
            # failure rather than becoming a refusal with http_status=0.
            return None, None, None, "connection_failed"

        try:
            with open(body_path, "rb") as f:
                raw_body = f.read(MAX_HTML_BYTES + 1)
        except OSError:
            return None, None, None, "connection_failed"
        if len(raw_body) > MAX_HTML_BYTES:
            return None, None, None, "response_too_large"

        content_type = ""
        try:
            with open(headers_path, "r", errors="replace") as f:
                for line in f:
                    if line.lower().startswith("content-type:"):
                        content_type = line.split(":", 1)[1].strip()
        except OSError:
            pass

        return http_code, content_type, raw_body.decode("utf-8", "replace"), None


def main():
    raw = sys.stdin.read()
    query, err = proto.parse_request(raw)
    if err is not None:
        # The host never sends a malformed request — this exists so the
        # worker's own boundary can be driven directly, without a sandbox,
        # the same way search_protocol.parse_request's own docstring
        # describes for the host side.
        print(proto.dumps_response(
            "failed", failures=[{"stage": "host", "code": "protocol_error"}]))
        return 0

    http_code, content_type, body, err_code = _run_curl(query)
    if err_code is not None:
        print(proto.dumps_response(
            "failed", failures=[{"stage": "request", "code": err_code}]))
        return 0

    http_err = _http_failure_code(http_code)
    if http_err is not None:
        # http_status rides only on source_refused (search_protocol.py's own
        # rule) — a redirect's 3xx is real, but Concept.md's carried-status
        # claim is specifically about a refusal, and _run_curl has already
        # bounded http_code to 100-599 above.
        failure = {"stage": "request", "code": http_err}
        if http_err == "source_refused":
            failure["http_status"] = http_code
        print(proto.dumps_response("failed", failures=[failure]))
        return 0

    if not _content_type_ok(content_type):
        print(proto.dumps_response(
            "failed",
            failures=[{"stage": "request", "code": "unexpected_content"}]))
        return 0

    status, evidence, failures = _parse_page(body)
    print(proto.dumps_response(status, evidence=evidence, failures=failures))
    return 0


if __name__ == "__main__":
    sys.exit(main())
