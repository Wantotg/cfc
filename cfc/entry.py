"""entry.py — the one check `cfc/__main__.py` runs before importing anything
else in this package.

Kept to names every interpreter back to Python 3.7 can execute (the module
uses `from __future__ import annotations` so the modern type-hint syntax
below is never evaluated, only parsed), and to nothing beyond the standard
library. `cfc/__main__.py` defers every other import until after
`check_interpreter()` has passed, so a module elsewhere in the package that
genuinely needs newer syntax still fails as "unsupported Python", not as a
`SyntaxError` pointing at a file the person running the command didn't write
and can't fix by editing.

3.10 is the floor: nothing in cfc needs it specifically yet, but it is a
deliberate floor rather than an accident of whatever wrote this file, so it
is named here once instead of discovered piecemeal.
"""
from __future__ import annotations

import sys

MIN_PYTHON = (3, 10)


def check_interpreter() -> str | None:
    """None if this interpreter satisfies `MIN_PYTHON`, else the message to
    print and exit on.
    """
    if sys.version_info[:2] >= MIN_PYTHON:
        return None
    have = ".".join(str(part) for part in sys.version_info[:2])
    want = ".".join(str(part) for part in MIN_PYTHON)
    return (
        f"cfc requires Python {want} or newer (this interpreter is "
        f"{have}). Install a supported Python and run this command with it."
    )
