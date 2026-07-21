# splash.py — the launch screen: pixel art composited under the title.
#
# Shown once per launch from main.py's __main__, between safe_backup() and
# repl(). Enter continues, Esc quits before repl() is ever called.
#
# This lives outside ui.py on purpose. `ui` is the bottom of the dependency
# graph and imports no other cfc module, so it cannot reach for config or an
# asset loader; and a whole screen with a binary format behind it is a feature,
# not a presentation primitive. So the dependency runs this way: splash imports
# ui, like mover and wikigit do.
#
# ── how the art is drawn ──────────────────────────────────────────────
# Each terminal cell is painted as `▀` (upper half block) with the foreground
# set to the top pixel and the background to the bottom one, so one text row
# carries two pixel rows and the result is roughly square on a normal font.
#
# The art is 2:3 portrait and the terminal is landscape, so it *cannot* bleed to
# a left and right edge without cropping off the cat's ears and feet. It doesn't
# need to: the source's background is pure black, so the screen is painted black
# and the cat composited into the middle of it. The letterboxing is the artwork.
# This is also why the screen is painted rather than left as the terminal's own
# background — a terminal whose background isn't exactly #000 would otherwise
# show the art as a visible rectangle.
import glob
import os
import random
import struct
import sys

from rich.cells import cell_len
from rich.text import Text

from ui import AI_NAME, console

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
_DEFAULT_ART = "balthazar"

TITLE = "COOKING FOR CATS"
PROMPT = "Enter to continue · Esc to quit"
PROMPT_COLOR = "#9aa0b0"  # explicit grey, not "dim": dim over a coloured
                          # background renders inconsistently across terminals.

# Rows reserved at the bottom for the text block: gap, title, gap, prompt.
_TEXT_ROWS = 4
# Rows kept clear above the art. The art is height-bound on any normal terminal,
# so without this it scales to fill the area exactly and the cat's ears sit on
# row 0, touching the top edge.
_TOP_MARGIN = 2

_POLL = 0.25        # how often the key wait looks for a terminal resize
_ESC_WINDOW = 0.03  # how long a bare Esc waits to prove it isn't a sequence

_HALF = "▀"
_CONSUMED = object()  # second cell of a double-width glyph; emits nothing


def _load_asset(name):
    """Read a baked asset → (width, height, rgb_bytes).

    Format (see dev/bake_splash.py): uint16 LE width, uint16 LE height, then
    width*height*3 raw RGB bytes, row-major. Deliberately not PNG — decoding
    PNG means Pillow, and the splash is not worth a runtime image dependency.
    """
    path = os.path.join(ASSET_DIR, f"splash_{name}.raw")
    with open(path, "rb") as fh:
        data = fh.read()
    w, h = struct.unpack_from("<HH", data, 0)
    expected = 4 + w * h * 3
    if len(data) < expected:
        raise ValueError(f"{path}: truncated ({len(data)} bytes, want {expected})")
    return w, h, data[4:expected]


def _available():
    """Every baked asset in assets/, by name, sorted.

    Sorted so "*" has a defined candidate list rather than whatever order the
    filesystem hands back — the pick is random, the pool shouldn't be.
    """
    found = glob.glob(os.path.join(ASSET_DIR, "splash_*.raw"))
    return sorted(os.path.basename(p)[len("splash_"):-len(".raw")] for p in found)


def _choose(spec):
    """Resolve a SPLASH_ART setting to one asset name.

    A string is that asset; "*" is everything in assets/; a list or tuple is a
    pool to pick from. The rotation is here rather than at the call site so
    dropping a new .raw into assets/ joins it with no code change and, under
    "*", no config change either.
    """
    if spec is None:
        spec = _DEFAULT_ART
    if isinstance(spec, str):
        names = _available() if spec == "*" else [spec]
    else:
        names = [str(n) for n in spec]
    return random.choice(names) if names else _DEFAULT_ART


def _resize(pixels, sw, sh, dw, dh):
    """Box-average resample. Pure stdlib — no Pillow at runtime.

    Averaging rather than nearest-neighbour, and the reason is specific to this
    art: it is a one-pixel rim light on black. The asset is baked at 96x144 and
    a 140x40 terminal displays it at about 48x72, so it halves on a normal
    launch — and nearest-neighbour halving drops every other pixel, which breaks
    the rim into dashes along the tail and the spine. Verified by eye against
    both.

    The trade: averaged colours fall outside the baked 40-colour palette, so
    this is not strictly palette-pure pixel art. Invisible on truecolor; a
    dashed outline is not.

    Upscaling is safe here — the source box collapses to a single pixel and this
    degenerates to nearest, which is what you want when enlarging pixel art.
    """
    out = bytearray(dw * dh * 3)
    for dy in range(dh):
        y0 = dy * sh // dh
        y1 = max(y0 + 1, (dy + 1) * sh // dh)
        for dx in range(dw):
            x0 = dx * sw // dw
            x1 = max(x0 + 1, (dx + 1) * sw // dw)
            r = g = b = 0
            n = (y1 - y0) * (x1 - x0)
            for y in range(y0, y1):
                row = y * sw * 3
                for x in range(x0, x1):
                    i = row + x * 3
                    r += pixels[i]
                    g += pixels[i + 1]
                    b += pixels[i + 2]
            i = (dy * dw + dx) * 3
            out[i] = r // n
            out[i + 1] = g // n
            out[i + 2] = b // n
    return bytes(out)


def _fit(sw, sh, max_cols, max_rows):
    """Largest (pixel_w, pixel_h) fitting max_cols x max_rows *text* cells at
    the source aspect ratio. Height is always even — two pixel rows per cell."""
    avail_h = max_rows * 2
    pw = max_cols
    ph = round(pw * sh / sw)
    if ph > avail_h:
        ph = avail_h
        pw = max(1, round(ph * sw / sh))
    return max(1, pw), max(2, ph - ph % 2)


def _stamp(glyphs, row, col, text, color):
    """Write `text` into the glyph layer at (row, col).

    Advances by `cell_len` per character and marks the trailing cell of a
    double-width glyph as consumed, so a CJK character in the title shifts
    nothing. The mascot art taught this lesson once already — full-width
    characters measured with len() shear the whole block off the right edge.
    """
    cols = len(glyphs[row])
    for ch in text:
        if col >= cols:
            return
        w = cell_len(ch)
        glyphs[row][col] = (ch, color)
        for k in range(1, w):
            if col + k < cols:
                glyphs[row][col + k] = _CONSUMED
        col += w


def _compose(art, cols, rows):
    """Build the whole screen as one Text: black buffer, cat centred above the
    text block, title and prompt stamped over it."""
    sw, sh, pixels = art

    art_rows = max(1, rows - _TEXT_ROWS - _TOP_MARGIN)
    pw, ph = _fit(sw, sh, cols, art_rows)
    px = _resize(pixels, sw, sh, pw, ph)

    # The screen as pixels: two rows per text cell, black.
    buf = bytearray(cols * rows * 2 * 3)
    off_x = (cols - pw) // 2
    # Even offset: the art must start on a cell boundary, or every row of it
    # straddles two cells and the half-block pairing is off by one.
    off_y = (_TOP_MARGIN + (art_rows - ph // 2) // 2) * 2
    for y in range(ph):
        dst = ((off_y + y) * cols + off_x) * 3
        src = y * pw * 3
        buf[dst:dst + pw * 3] = px[src:src + pw * 3]

    glyphs = [[None] * cols for _ in range(rows)]
    title_row = rows - 3
    prompt_row = rows - 1
    _stamp(glyphs, title_row, max(0, (cols - cell_len(TITLE)) // 2), TITLE,
           f"bold {AI_NAME}")
    _stamp(glyphs, prompt_row, max(0, (cols - cell_len(PROMPT)) // 2), PROMPT,
           PROMPT_COLOR)

    # Emit, merging runs of identical style. A 140x40 screen is 5600 cells and
    # one styled span each would make Rich do real work for nothing; the art is
    # mostly flat black, so runs collapse it by more than an order of magnitude.
    text = Text()
    run, run_style = [], None
    for r in range(rows):
        top = r * 2 * cols * 3
        bot = (r * 2 + 1) * cols * 3
        for c in range(cols):
            g = glyphs[r][c]
            if g is _CONSUMED:
                continue
            ti, bi = top + c * 3, bot + c * 3
            if g is None:
                ch = _HALF
                style = (f"rgb({buf[ti]},{buf[ti + 1]},{buf[ti + 2]}) "
                         f"on rgb({buf[bi]},{buf[bi + 1]},{buf[bi + 2]})")
            else:
                # A stamped cell covers both pixel rows, so its background is
                # their average — using one row would drop the other.
                ch, color = g
                bg = tuple((buf[ti + k] + buf[bi + k]) // 2 for k in range(3))
                style = f"{color} on rgb({bg[0]},{bg[1]},{bg[2]})"
            if style != run_style:
                if run:
                    text.append("".join(run), style=run_style)
                run, run_style = [], style
            run.append(ch)
        if r + 1 < rows:
            run.append("\n")
    if run:
        text.append("".join(run), style=run_style)
    return text


def _draw(art):
    """Paint one full screen. Returns the size it was drawn for.

    `rows` is one short of the terminal height: printing exactly `height` lines
    pushes the cursor past the last row and scrolls the top of the screen away.
    """
    cols, height = console.size
    rows = max(1, height - 1)
    console.clear()
    console.print(_compose(art, cols, rows))
    return (cols, height)


def _wait_key(art, drawn_size):
    """Block until Enter or Esc, redrawing if the terminal is resized.

    Returns "continue" or "quit".

    Raw cbreak mode rather than input(), because a bare Escape never arrives
    through a line-buffered read — it isn't a line. The poll timeout is what
    makes resize handling possible at all: the screen is drawn once and then
    blocks, so without this a window resize would leave a torn image up until
    the user pressed something.

    Escape *sequences* (arrow keys, function keys) also start with \\x1b. They
    arrive as one burst, so a byte still waiting just after means this is a
    sequence, not a bare Esc — drain it and carry on rather than quitting the
    app because someone pressed Down.

    Bytes are read from the file descriptor with os.read, never sys.stdin.read.
    sys.stdin is buffered: reading one character off it pulls the whole waiting
    burst into Python's buffer, leaving the fd empty, so the select that
    distinguishes a sequence from a bare Esc sees nothing and every arrow key
    quits the app. That bug was live until it was tested.
    """
    try:
        import select
        import termios
        import tty
    except ImportError:
        # Not a POSIX terminal. Degrade to Enter-only rather than failing to
        # boot; Esc simply isn't available.
        input()
        return "continue"

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            if select.select([fd], [], [], _POLL)[0]:
                if os.read(fd, 1) != b"\x1b":
                    return "continue"
                # Small window, not zero: over ssh or a slow terminal the rest
                # of a sequence can lag the Esc by a few milliseconds. The cost
                # when it really is a bare Esc is one imperceptible pause.
                if not select.select([fd], [], [], _ESC_WINDOW)[0]:
                    return "quit"
                while select.select([fd], [], [], 0)[0]:
                    os.read(fd, 1024)
                continue
            if console.size != drawn_size:
                drawn_size = _draw(art)
    finally:
        # Restore unconditionally. Leaving the terminal in cbreak would break
        # every prompt_toolkit read for the rest of the session.
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def splash(name=None):
    """Show the launch screen once. Returns "continue" or "quit".

    `name` overrides the config setting; it exists for trying an asset out
    without editing config.

    No-op on a non-TTY stdin (piped input, tests/golden.py): a headless run must
    never block on a keypress, and the golden output must stay byte-for-byte.

    A missing or malformed asset skips the splash instead of raising. The
    launch screen is decoration; it must never be the reason cfc won't boot.
    """
    if not sys.stdin.isatty():
        return "continue"

    if name is None:
        try:
            from config import SPLASH_ART
        except ImportError:
            # config.py is gitignored; an existing one predates this setting.
            SPLASH_ART = _DEFAULT_ART
        name = _choose(SPLASH_ART)

    try:
        art = _load_asset(name)
    except (OSError, ValueError, struct.error):
        return "continue"

    return _wait_key(art, _draw(art))


if __name__ == "__main__":
    # `python splash.py [name]` — look at an asset without launching cfc.
    print(splash(sys.argv[1] if len(sys.argv) > 1 else None))
