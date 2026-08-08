"""conftest.py — one fixed render width for the whole entry gate.

Rich reads `COLUMNS`/`LINES` when it constructs a `Console` and, for output
that is not a terminal, falls back to 80x25 when neither is set. Nothing the
gate runs is a terminal: pytest captures the native suite, and every legacy
suite is a child process whose stdout is a pipe. So the render width comes
from whoever happened to run `python -m pytest` — and the legacy suites check
their output by searching the rendered text for a phrase. A different width
wraps the line in a different place, splits the phrase, and fails a suite
whose behaviour is entirely correct.

That made the gate's result a property of the terminal rather than of the
code. Measured across widths, the same command on the same checkout gave 116
passed at 80, 5 failures at 100, 2 at 111, 4 at 140 and 10 at 60 — and 111
was a VS Code panel that changes size when its owner drags it.

80x25 is Rich's own no-`COLUMNS` fallback, which is the width every one of
these assertions was written against. Pinned here rather than in
`tests/test_entry_gate.py` for two reasons: a root `conftest.py` is imported
before any test module, so this lands before the first `import ui` constructs
the shared `Console`; and child processes inherit `os.environ`, so one pin
covers both halves of the gate.

**This buys a reproducible gate, not a claim about other widths.** `python -m
pytest` proves the rendering at 80 columns and says nothing about 111 or 200.
Narrow- and wide-terminal rendering stays playtest work.

`tests/golden.py` still pins its own width under its `__main__` guard. That
pin is for the developer running `python3 tests/golden.py check` by hand,
where this file is not loaded at all.
"""
import os

os.environ["COLUMNS"] = "80"
os.environ["LINES"] = "25"
