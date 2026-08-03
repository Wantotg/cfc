#!/usr/bin/env python3
"""
test_api_stream.py — api.stream_response()'s live reasoning panel. No API calls.

    python3 tests/test_api_stream.py

B-1.7-01: a thinking model that streams reasoning containing only whitespace
used to draw an `AI · reasoning` panel with nothing readable in it. The fix is
a readable-content check that gates *drawing the panel* only — the raw
`reasoning` string returned to the caller must stay exactly what the provider
sent, whitespace and all, because it's what tells a reasoning-only completion
apart from a truly empty one (see main.py's empty-completion retry path).

httpx is stubbed at the `api.httpx.Client` seam so this drives the real SSE
parsing loop, not a re-implementation of it.
"""
import contextlib
import io
import json as jsonmod
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import api as apimod
import ui

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def _sse(deltas):
    """SSE lines for a sequence of `delta` dicts, terminated by [DONE]."""
    lines = [f"data: {jsonmod.dumps({'choices': [{'delta': d}]})}"
             for d in deltas]
    lines.append("data: [DONE]")
    return lines


class _FakeResponse:
    is_error = False

    def __init__(self, lines):
        self._lines = lines

    def iter_lines(self):
        return iter(self._lines)

    def read(self):
        pass


class _FakeStreamCtx:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return _FakeResponse(self._lines)

    def __exit__(self, *a):
        return False


class _FakeClient:
    lines = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def stream(self, method, url, headers=None, json=None):
        return _FakeStreamCtx(_FakeClient.lines)


def _run_stream(deltas):
    """Drive api.stream_response over scripted deltas, off-screen.

    Returns (full_text, reasoning, panel_calls) — panel_calls counts how many
    times the reasoning panel was actually built, which is the thing under
    test, not just the count of reasoning deltas received.
    """
    _FakeClient.lines = _sse(deltas)
    real_client = apimod.httpx.Client
    real_panel = apimod.ai_reasoning_panel
    apimod.httpx.Client = _FakeClient
    calls = []
    apimod.ai_reasoning_panel = lambda body: calls.append(1) or real_panel(body)
    real_file = ui.console.file
    ui.console.file = io.StringIO()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            full_text, usage, reasoning = apimod.stream_response(
                [{"role": "user", "content": "hi"}], model="test-model")
    finally:
        apimod.httpx.Client = real_client
        apimod.ai_reasoning_panel = real_panel
        ui.console.file = real_file
    return full_text, reasoning, len(calls)


def main():
    print("\n--- whitespace-only reasoning draws no panel ---")
    full_text, reasoning, panel_calls = _run_stream([
        {"reasoning": "   "},
        {"reasoning": "\n  \n"},
        {"content": "ok"},
    ])
    ok("no reasoning panel is built", panel_calls == 0, panel_calls)
    ok("the answer still streams", full_text == "ok", full_text)
    ok("the raw whitespace reasoning is returned unstripped, not blanked",
       reasoning == "   \n  \n", repr(reasoning))

    print("\n--- readable reasoning still draws the panel ---")
    full_text, reasoning, panel_calls = _run_stream([
        {"reasoning": "Let me think"},
        {"content": "Answer"},
    ])
    ok("the reasoning panel is built", panel_calls >= 1, panel_calls)
    ok("the answer still streams", full_text == "Answer", full_text)
    ok("reasoning is returned unchanged", reasoning == "Let me think", reasoning)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
