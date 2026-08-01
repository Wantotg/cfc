#!/usr/bin/env python3
"""test_ui.py — the shared console prints chat content literally. No network.

    python3 tests/test_ui.py

`B-06`: `ui.console` was built `Console(markup=False)` so a model's own
`[dim]...[/dim]`-shaped text could never be reinterpreted as markup — but
rich's emoji substitution (`:key:` -> the glyph) is a separate switch,
`emoji=True` by default, and it was still live. Two settings implement one
decision ("chat content is never reinterpreted"); this pins both halves
through the one console everything prints through, so a future rich upgrade
that flips a default back can't silently reopen either half.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

import io

from ui import console

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def rendered(text):
    buf = io.StringIO()
    saved = console.file
    console.file = buf
    try:
        console.print(text)
    finally:
        console.file = saved
    return buf.getvalue()


def main_():
    print("\n--- rich shortcodes survive literally ---")
    out = rendered("run :new:")
    ok("':new:' is not substituted for its emoji", "🆕" not in out, out)
    ok("...and the shortcode text is still there", ":new:" in out, out)

    out = rendered(":key: :lock: :books: :100:")
    ok("none of a run of known shortcodes are substituted",
       not any(g in out for g in ("🔑", "🔒", "📚", "💯")), out)
    ok("...and all four shortcodes survive verbatim",
       all(s in out for s in (":key:", ":lock:", ":books:", ":100:")), out)

    print("\n--- a code-shaped string keeps its shortcodes too ---")
    code = "```\nconfig:\n  icon: :key:\n```"
    out = rendered(code)
    ok("a shortcode inside a fenced code block is not substituted",
       "🔑" not in out, out)
    ok("...and prints verbatim", ":key:" in out, out)

    print("\n--- markup still prints literally (the existing guarantee) ---")
    out = rendered("[dim]recall cancelled.[/dim]")
    ok("a bracketed style tag is not consumed as markup",
       "[dim]recall cancelled.[/dim]" in out, out)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
