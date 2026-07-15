# ui.py — the shared console and small presentation helpers.
#
# Everything that prints imports `console` from here. It is a single shared
# object rather than one per module because Rich tracks terminal state (width,
# live regions) per Console, and two of them writing to the same terminal
# interleave badly during streaming.
#
# This module must not import any other cfc module: it sits at the bottom of
# the dependency graph so db/api/export/commands can all rely on it without a
# cycle.
import datetime

from rich.console import Console
from rich.text import Text

# markup=False so existing [...] strings print literally.
# highlight=True (default) gives subtle coloring of numbers/paths.
console = Console(markup=False)


def format_ts(iso_str):
    """Convert ISO timestamp to readable YYYY-MM-DD HH:MM."""
    try:
        dt = datetime.datetime.fromisoformat(iso_str)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str


def make_bar(pct, width=24, ctx=None, limit=None):
    """Build a styled progress bar as a Rich Text.
    Color shifts: green < 60%, yellow 60-80%, red > 80%.
    """
    filled = int(width * pct / 100)
    if pct > 80:
        fill_style = "red"
    elif pct > 60:
        fill_style = "yellow"
    else:
        fill_style = "green"

    bar = Text()
    bar.append("█" * filled, style=fill_style)
    bar.append("░" * (width - filled), style="dim")
    if ctx is not None and limit is not None:
        bar.append(f"  {ctx:,} / {limit:,} tokens "
                   f"({pct:.1f}%)")
    else:
        bar.append(f"  {pct:.1f}%")
    return bar


def make_snippet(content, query, context=40):
    """Extract a snippet around the first match of query in
    content."""
    content_flat = content.replace("\n", " ")
    pos = content_flat.lower().find(query.lower())

    if pos == -1:
        if len(content_flat) <= context * 2:
            return content_flat
        return content_flat[:context * 2] + "..."

    start = max(0, pos - context)
    end = min(len(content_flat), pos + len(query) + context)

    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content_flat) else ""
    return prefix + content_flat[start:end] + suffix


def read_multiline():
    """Read multi-line input until closing triple-quote.
    Returns the joined text, or None if cancelled."""
    lines = []
    console.print("Multi-line mode. Type \"\"\" to send, "
                  ":cancel to abort.")
    while True:
        try:
            line = input("...> ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[cancelled]")
            return None
        if line == ":cancel":
            console.print("[cancelled]")
            return None
        if line == '"""':
            break
        lines.append(line)
    return "\n".join(lines)
