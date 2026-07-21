#!/usr/bin/env python3
"""
test_splash.py — the launch screen's compositor. No terminal, no API, no DB.

    python3 tests/test_splash.py

The splash is decoration, so most of it doesn't warrant assertions. Four
properties do, and each of them failed at least once while it was being built:

**The escape-sequence read is unbuffered.** `sys.stdin.read(1)` pulls the whole
waiting burst into Python's buffer, so the `select` that distinguishes a bare
Esc from an arrow key sees an empty fd and calls every sequence a bare Esc —
i.e. pressing Down quits the app. Read off the AST, the same way test_wikigit
pins "there is no push": the property is about which call the module makes, and
reproducing it live needs a pty.

**Aspect ratio survives the fit.** The art is 2:3 in a landscape terminal. If
`_fit` ever returns something that doesn't preserve the source ratio, the cat
is squashed and nothing raises — it just looks slightly wrong forever.

**Nothing overflows the grid.** A composed screen must be exactly the requested
number of rows, and a double-width character in the title must not shift the
cells after it. The mascot art already taught this lesson once by measuring
full-width CJK with len() and shearing the block off the right edge.

**A bad asset must not stop cfc booting.** Missing, truncated, or a name that
doesn't exist — all of it skips the splash. It is the first thing that runs at
launch, so anything it raises is a total failure to start.
"""
import ast
import os
import struct
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import splash

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def fake_art(w=8, h=12, fill=(10, 20, 30)):
    return w, h, bytes(bytearray(fill * (w * h)))


def main():
    print("--- the fit preserves the source aspect ratio ---")
    worst = 0.0
    # (20,60) and (30,50) are load-bearing: every landscape size is *height*
    # bound, so the clamp branch recomputes the width and restores the ratio
    # even if the first branch got it wrong. Only a tall narrow terminal
    # exercises the width-bound path. A mutation dropping the aspect from that
    # branch passed the whole suite until these two were added.
    for cols, rows in [(80, 24), (140, 39), (200, 60), (240, 80), (40, 12),
                       (300, 20), (20, 60), (30, 50)]:
        pw, ph = splash._fit(96, 144, cols, rows)
        drift = abs((ph / pw) - 1.5) / 1.5
        worst = max(worst, drift)
        ok(f"{cols}x{rows}: {pw}x{ph} fits and keeps 2:3", pw <= cols and ph <= rows * 2 and drift < 0.05,
           f"aspect {ph / pw:.3f}, want 1.500")
    ok("worst aspect drift across all sizes under 5%", worst < 0.05, f"{worst:.3%}")
    ok("pixel height is always even (two rows per cell)",
       all(splash._fit(96, 144, c, r)[1] % 2 == 0
           for c, r in [(80, 24), (140, 39), (37, 11), (1, 1)]))

    print("\n--- box-average resampling, not nearest ---")
    # A single bright pixel in a dark field must survive a 2:1 downscale as a
    # blend. Nearest-neighbour would either keep it at full value or drop it
    # entirely; averaging is what stops the rim light breaking into dashes.
    px = bytearray(4 * 4 * 3)
    px[(1 * 4 + 1) * 3:(1 * 4 + 1) * 3 + 3] = b"\xff\xff\xff"
    out = splash._resize(bytes(px), 4, 4, 2, 2)
    tl = out[0]
    ok("a lone bright pixel blends rather than vanishing or staying full",
       0 < tl < 255, f"got {tl}")
    ok("upscaling degenerates to nearest (values stay in the source set)",
       set(splash._resize(bytes(px), 4, 4, 8, 8)) <= {0, 255})
    ok("output length is exactly dw*dh*3",
       len(splash._resize(bytes(px), 4, 4, 5, 7)) == 5 * 7 * 3)

    print("\n--- the composed screen fits the grid exactly ---")
    # Measured in *cells* (cell_len), not characters. That is the unit the
    # terminal lays out in, and it is the whole difference the wide-glyph case
    # below turns on — a row can hold `cols` characters and still render one
    # cell too wide.
    from rich.cells import cell_len
    for cols, rows in [(80, 24), (140, 39), (60, 10), (200, 60)]:
        text = splash._compose(fake_art(), cols, rows)
        lines = text.plain.split("\n")
        widths = {cell_len(line) for line in lines}
        ok(f"{cols}x{rows}: {len(lines)} rows, every row {cols} cells wide",
           len(lines) == rows and widths == {cols}, f"rows={len(lines)} widths={widths}")

    print("\n--- a double-width glyph in the title shifts nothing ---")
    saved = splash.TITLE
    try:
        splash.TITLE = "猫 COOKING"  # full-width, two cells
        text = splash._compose(fake_art(), 80, 24)
        lines = text.plain.split("\n")
        ok("wide glyph consumes two cells, so the row still measures 80 cells",
           len(lines) == 24 and {cell_len(x) for x in lines} == {80},
           {cell_len(x) for x in lines})
        ok("...and it is one character shorter, proving the cell was consumed",
           any(len(x) == 79 for x in lines), {len(x) for x in lines})
        ok("the title actually made it onto the screen", "猫" in text.plain)
    finally:
        splash.TITLE = saved

    print("\n--- asset selection ---")
    ok("a plain string is that asset", splash._choose("balthazar") == "balthazar")
    ok("a list picks from the pool",
       {splash._choose(["a", "b"]) for _ in range(50)} == {"a", "b"})
    ok("None falls back to the default", splash._choose(None) == splash._DEFAULT_ART)
    ok("an empty pool falls back rather than raising",
       splash._choose([]) == splash._DEFAULT_ART)
    ok('"*" resolves to something that exists on disk',
       splash._choose("*") in splash._available())
    ok("the shipped asset is discoverable", "balthazar" in splash._available())

    print("\n--- a bad asset never stops the boot ---")
    with tempfile.TemporaryDirectory() as tmp:
        real = splash.ASSET_DIR
        try:
            splash.ASSET_DIR = tmp
            bad = os.path.join(tmp, "splash_torn.raw")
            with open(bad, "wb") as fh:
                fh.write(struct.pack("<HH", 96, 144))
                fh.write(b"\x00" * 100)  # nowhere near w*h*3
            raised = None
            try:
                splash._load_asset("torn")
            except Exception as exc:
                raised = exc
            ok("a truncated asset raises ValueError, not IndexError/silence",
               isinstance(raised, ValueError), repr(raised))
            try:
                splash._load_asset("does_not_exist")
                missing = None
            except Exception as exc:
                missing = exc
            ok("a missing asset raises OSError", isinstance(missing, OSError), repr(missing))
        finally:
            splash.ASSET_DIR = real

    src = (ROOT / "splash.py").read_text()
    tree = ast.parse(src)
    caught = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                names = []
                if isinstance(handler.type, ast.Tuple):
                    names = [n.id for n in handler.type.elts if isinstance(n, ast.Name)]
                elif isinstance(handler.type, ast.Name):
                    names = [handler.type.id]
                elif isinstance(handler.type, ast.Attribute):
                    names = [handler.type.attr]
                caught.update(names)
    ok("splash() catches OSError and ValueError so a bad asset is skipped",
       {"OSError", "ValueError"} <= caught, sorted(caught))

    print("\n--- the key read is unbuffered ---")
    # The property: bytes come off the fd, never through sys.stdin's buffer.
    # Buffered reads swallow the rest of an escape sequence and every arrow key
    # then reads as a bare Esc, quitting the app.
    # Checked on the AST, not the text: the docstring explains the bug and
    # names the very call it forbids, so a substring search finds its own
    # documentation and fails.
    def reads_stdin_buffered(node):
        return (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "read"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "stdin")

    ok("reads use os.read", "os.read(fd" in src)
    ok("no sys.stdin.read call, which would buffer away the sequence",
       not any(reads_stdin_buffered(n) for n in ast.walk(tree)))
    ok("select polls the raw fd, not the stdin object",
       "select.select([fd]" in src and "select.select([sys.stdin]" not in src)
    ok("cbreak is restored in a finally",
       any(isinstance(n, ast.Try) and n.finalbody and "tcsetattr" in ast.dump(n)
           for n in ast.walk(tree)))

    print("\n--- ui.py stayed at the bottom of the dependency graph ---")
    # The invariant is about *module-level* imports, which is what can form a
    # cycle. ui.py has always reached for config lazily inside a function
    # (MOUSE_INPUT, and the old splash frame) — that is a deliberate exception,
    # not a leak, because it happens after both modules are fully loaded.
    ui_tree = ast.parse((ROOT / "ui.py").read_text())
    ui_src = (ROOT / "ui.py").read_text()
    top_level = {n.module for n in ui_tree.body
                 if isinstance(n, ast.ImportFrom) and n.module}
    top_level |= {a.name for n in ui_tree.body if isinstance(n, ast.Import)
                  for a in n.names}
    cfc = {p.stem for p in ROOT.glob("*.py")} - {"ui"}
    ok("ui.py imports no cfc module at module level (splash depends on ui, not the reverse)",
       not (top_level & cfc), sorted(top_level & cfc))
    ok("splash.py is the one that depends on ui",
       "from ui import" in src)
    ok("the ASCII frames are gone from ui.py",
       "SPLASH_FRAMES" not in ui_src and "_render_frame" not in ui_src)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
