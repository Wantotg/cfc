"""doctor.py — `python -m cfc doctor`'s renderer and command body.

Prints the ordered inventory `diagnostics.diagnose()` produces and exits
non-zero exactly when a required row is not ready. Never prints a
credential value, a configuration dump, or a traceback — every string here
comes from `Row.detail` or `Row.next_step`, and `diagnostics.py` is what
keeps those safe to print (see its module docstring). A row's `next_step`,
when present, renders as a subordinate line directly below it. It validates
provider and embedding settings locally; it never claims they are reachable.
"""
from __future__ import annotations

import sys

from cfc import diagnostics

_CLOSING = (
    "A clean report means only that this bootstrap is ready — it is not a "
    "claim that the provider, vault, or embedder are reachable right now."
)


def run(args: list[str]) -> int:
    if args:
        print(f"Usage: python -m cfc doctor (takes no arguments; got "
              f"{' '.join(args)!r})", file=sys.stderr)
        return 2

    rows = diagnostics.diagnose()
    print(render(rows))
    return 0 if diagnostics.required_rows_ok(rows) else 1


def render(rows) -> str:
    name_width = max(len(row.name) for row in rows)
    state_width = max(len(row.state.value) for row in rows)

    lines = ["cfc doctor — 2.0 bootstrap readiness", ""]
    for row in rows:
        line = f"  {row.name.ljust(name_width)}   {row.state.value.ljust(state_width)}"
        if row.detail:
            line += f"   {row.detail}"
        lines.append(line.rstrip())
        if row.next_step:
            lines.append(f"      -> {row.next_step}")
    lines.append("")
    lines.append(_CLOSING)
    return "\n".join(lines)
