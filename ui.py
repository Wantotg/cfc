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
import sys

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

# markup=False so existing [...] strings print literally.
# highlight=True (default) gives subtle coloring of numbers/paths.
console = Console(markup=False)


# ── palette ──────────────────────────────────────────────────────────
# The turn's colours live here, next to the console everything shares. Not in
# config.py: these are the app's look, not a deployment knob. Tuned for a black
# terminal background.
AI_REASON_BORDER = "#3a3f5c"  # dark slate-grey — reasoning is demoted
AI_ANSWER_BORDER = "#a01a6d"  # deep magenta — the answer is the loud frame
HUMAN_BORDER = "#1a2456"      # deep navy
AI_NAME = "#ff4fd8"           # hot pink — speaker label, brighter than its frame
HUMAN_NAME = "#5fb3e8"        # softer blue
SPINNER_COLOR = "#22e0ff"     # electric cyan


def _speaker_panel(body, name, name_color, border):
    """A titled box whose label is coloured independently of its border — the
    'dark frame, bright name' pattern. `body` is any renderable (Markdown while
    streaming, Text on the reasoning tail or a human line)."""
    return Panel(
        body,
        title=Text(name, style=f"bold {name_color}"),
        title_align="left",
        border_style=border,
        box=box.SQUARE,
        padding=(0, 1),
    )


def ai_answer_panel(body):
    return _speaker_panel(body, "AI", AI_NAME, AI_ANSWER_BORDER)


def ai_reasoning_panel(body):
    return _speaker_panel(body, "AI · reasoning", AI_NAME, AI_REASON_BORDER)


def human_panel(text):
    return _speaker_panel(Text(text), "You", HUMAN_NAME, HUMAN_BORDER)


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


# Created lazily on first read and reused for the life of the process.
# Building a PromptSession re-probes the terminal (size, cursor position), so
# one shared session avoids paying that on every prompt.
_prompt_session = None


# The `:attach` completer, injected by main.py via set_completer(). It is not
# imported here: ui.py sits at the bottom of the dependency graph (see the
# module header) and complete.py pulls in paths + config, so importing it would
# put a cycle where the invariant says there is none. ui.py holds it as an
# opaque object and never looks inside.
_completer = None


def set_completer(completer):
    """Give the line editor a prompt_toolkit Completer. Call before the first
    read_input(); the session is built once and cached."""
    global _completer
    _completer = completer


def _mouse_enabled():
    """Whether to let the terminal's mouse position the cursor.

    Off by default, and that is not timidity. prompt_toolkit's mouse support
    puts the terminal in a reporting mode that captures clicks and drags for
    the whole window while the prompt is live — so click-to-position costs you
    ordinary click-drag text selection of the conversation scrolled above,
    which is the more common gesture by a distance. Most terminals still allow
    selection with Shift held, but a feature that silently changes what the
    mouse does everywhere else should be opt-in.
    """
    try:
        from config import MOUSE_INPUT
        return bool(MOUSE_INPUT)
    except ImportError:
        return False


def _make_prompt_session():
    from prompt_toolkit import PromptSession
    from prompt_toolkit.key_binding import KeyBindings

    kb = KeyBindings()

    @kb.add("enter")
    def _submit(event):
        # Enter sends. With multiline=True the default is the opposite (Enter
        # inserts a newline, Meta+Enter accepts), so we override it.
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    def _newline(event):
        # Alt+Enter inserts a newline. This is *the* newline key: Shift+Enter
        # can't be bound (see read_input docstring), so Alt+Enter is what we
        # document.
        event.current_buffer.insert_text("\n")

    # erase_when_done wipes the "you> <text>" line once Enter is hit; the caller
    # re-echoes it in the bordered human_panel, so without this the message shows
    # twice — once raw, once framed.
    #
    # complete_while_typing is off: completion is Tab-triggered on purpose, to
    # match complete.py's MIN_CHARS rule. A menu that opens as you type would
    # pop up over the conversation on every ':attach ~/p' keystroke, and the
    # candidate list is a directory scan across /mnt/c, which is slow enough
    # that doing it per keypress would be felt.
    return PromptSession(multiline=True, key_bindings=kb, erase_when_done=True,
                         completer=_completer, complete_while_typing=False,
                         mouse_support=_mouse_enabled())


def read_input(prompt="you> "):
    """Read one submission with full line editing, arrow navigation, and
    multi-line paste. Returns the entered text (unstripped — the caller
    strips).

    Enter sends. Alt+Enter inserts a newline. A bracketed paste lands in the
    buffer intact, embedded newlines and all — it does not submit early, which
    is the whole reason the old ``\"\"\"`` heredoc mode is gone.

    Ctrl-C abandons the current line and reprompts, staying in the session.
    Ctrl-D on an empty line raises EOFError, which the caller reads as "leave
    session." (The old reader left on both; Ctrl-C no longer leaves.)

    Shift+Enter is deliberately unbound: prompt_toolkit maps the terminal
    sequence for Shift+Enter back to plain Enter, so it can't insert a newline
    without also breaking Enter. Windows Terminal users who want the Shift+Enter
    reflex can remap it to send Alt+Enter (ESC + CR) in settings.
    """
    if not sys.stdin.isatty():
        # Non-interactive stdin — piped input, or the golden harness feeding a
        # StringIO. prompt_toolkit needs a real terminal (it wants a tty fd),
        # so fall back to plain input(). This also keeps the characterisation
        # tests reading exactly as they did before. EOFError still propagates
        # as "leave session."
        return input(prompt)

    global _prompt_session
    if _prompt_session is None:
        _prompt_session = _make_prompt_session()
    while True:
        try:
            return _prompt_session.prompt(prompt)
        except KeyboardInterrupt:
            # Ctrl-C: drop the current line, draw a fresh prompt. Never leaves.
            continue
