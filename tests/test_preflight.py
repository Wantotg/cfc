#!/usr/bin/env python3
"""
test_preflight.py — the launcher's embedder check. No network beyond localhost.

    python3 tests/test_preflight.py

Two properties are worth real assertions here and the rest is I/O plumbing:

**The dimension guard.** `vec_chunks` is declared `float[1024]`. An embedder
answering with a different width is the worst failure in this codebase's
catalogue — it does not raise, it inserts, and the damage shows up weeks later
as slightly worse ranking with no event to trace it to. The check exists to
turn that into a message at launch, so it is pinned against a stub that serves
768-d vectors.

**`lms load` is invoked with `-y`.** Without it the CLI drops into an
interactive model picker, and a launcher that stops to ask a question hangs
behind a terminal nobody is looking at. Same shape as test_wikigit's "there is
no push": read off the AST, because the property is about the argv the module
can construct.

The probe is exercised against a stub HTTP server on a loopback port, so
nothing here needs LM Studio, an API key or the internet.
"""
import ast
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import preflight

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


class Stub:
    """A fake /v1/embeddings that serves whatever width it is told to."""

    def __init__(self, dim=1024, status=200):
        self.dim, self.status = dim, status
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                if outer.status != 200:
                    self.send_response(outer.status)
                    self.end_headers()
                    self.wfile.write(b"nope")
                    return
                body = json.dumps({
                    "data": [{"embedding": [0.0] * outer.dim, "index": 0}]
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_port

    def __enter__(self):
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()
        self._saved = preflight.embed_target
        preflight.embed_target = lambda: (
            f"http://127.0.0.1:{self.port}/v1", "stub-model", "k")
        return self

    def __exit__(self, *exc):
        preflight.embed_target = self._saved
        self.server.shutdown()
        self.server.server_close()


def main():
    print("\n--- the dimension guard ---")
    with Stub(dim=1024):
        good, detail = preflight.probe(read=5)
        ok("a 1024-d embedder passes", good, detail)
        ok("...and the detail names the width", "1024" in detail, detail)

    with Stub(dim=768):
        good, detail = preflight.probe(read=5)
        ok("a 768-d embedder is REFUSED, not accepted", not good, detail)
        ok("...and the reason names vec_chunks",
           "1024" in detail and "vec_chunks" in detail, detail)

    with Stub(status=503):
        good, detail = preflight.probe(read=5)
        ok("a 5xx is a failure, not a crash", not good, detail)
        ok("...carrying the status code", "503" in detail, detail)

    print("\n--- probe never raises ---")
    saved = preflight.embed_target
    try:
        # Port 1 on loopback: nothing can be listening, and it is refused
        # rather than routed, so this stays fast on every platform.
        preflight.embed_target = lambda: ("http://127.0.0.1:1/v1", "m", "k")
        good, detail = preflight.probe(read=3)
        ok("a dead endpoint returns False rather than raising", not good, detail)
        ok("...with a usable reason", bool(detail.strip()), detail)
    finally:
        preflight.embed_target = saved

    print("\n--- local vs hosted ---")
    for base, expect in (("http://localhost:1233/v1", True),
                         ("http://127.0.0.1:1233/v1", True),
                         ("https://api.nano-gpt.com/v1", False),
                         ("https://localhost.example.com/v1", False)):
        ok(f"is_local({base}) == {expect}",
           preflight.is_local(base) is expect)

    print("\n--- config is the single source of the endpoint ---")
    base, model, key = preflight.embed_target()
    try:
        import config
        ok("embed_target reads EMBED_BASE from config",
           base == getattr(config, "EMBED_BASE", base), base)
        ok("...and EMBED_MODEL",
           model == getattr(config, "EMBED_MODEL", model), model)
    except ImportError:
        ok("embed_target falls back without config", bool(base and model))

    src = (ROOT / "preflight.py").read_text()
    ok("the endpoint is not hard-coded a second time",
       src.count("localhost:1233") <= 1, src.count("localhost:1233"))

    print("\n--- the launcher cannot hang on a prompt ---")
    tree = ast.parse(src)
    load_calls = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (getattr(node.func, "id", None) or
                getattr(node.func, "attr", None)) != "_lms":
            continue
        args = [a.value for a in node.args
                if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if "load" in args:
            load_calls.append(args)

    ok("`lms load` is actually invoked somewhere", bool(load_calls), load_calls)
    ok("...always with -y, so it can never open a picker",
       all("-y" in a for a in load_calls), load_calls)

    print("\n--- ensure() never blocks the launch ---")
    ok("__main__ exits 0 regardless of the check",
       "sys.exit(0)" in src and "sys.exit(1)" not in src)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
