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
from pathlib import Path

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
    """An ISO timestamp as readable **local** `YYYY-MM-DD HH:MM`.

    It converts when the value carries a UTC offset, and that is the whole
    point of the function. `db.py` is the only module in the codebase that
    stores UTC — `new_session` and `save_message` write
    `datetime.now(timezone.utc).isoformat()`. Routines, the scheduler, the
    mover and the backup rotation all write local naive time. Formatting the
    stored string without converting printed every session two hours off in
    the Netherlands, and put the hub's *Recent chats* panel and its *Routines*
    panel — one directly above the other, on the same screen — in two
    different time bases.

    A **naive** timestamp is left exactly as it is, rather than being assumed
    to be UTC. Everything naive here is already local, so attaching a zone to
    it would move the one set of times that was right.
    """
    try:
        dt = datetime.datetime.fromisoformat(iso_str)
    except Exception:
        return iso_str
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M")


def vault_relative(path, root):
    """A vault path for *display*, without its machine-specific prefix.

        /mnt/c/Users/disse/cooking for cats/06 metadata/routines
        →                 /cooking for cats/06 metadata/routines

    Relative to the vault's **parent**, not the vault itself, so the vault's own
    name survives — on a machine with more than one vault, which folder you are
    looking at is the informative half and the WSL mount point is the noise.

    A path that is *not* inside the vault comes back unchanged, deliberately. A
    routine directory configured somewhere else should look different from one
    in the vault; trimming it to look local would hide exactly the surprise
    worth seeing.

    Takes the root as an argument rather than reading `config.VAULT_PATH`,
    because this module imports no other cfc module and is the bottom of the
    dependency graph — see `format_ts` above, which takes the same shape for
    the same reason. Display only: never build a real path out of this.
    """
    if not root:
        return str(path)          # unset is a valid answer: print it in full
    try:
        return "/" + str(Path(str(path)).relative_to(Path(str(root)).parent))
    except (ValueError, OSError):
        return str(path)


# Context-usage thresholds, as a percentage of the model's claimed limit.
# Deliberately far below the old 60/80: a 1M-token context window is a vendor
# claim, not a promise that the last 900k tokens are as well attended to as the
# first. The *percentages stay honest* — they are computed against the claimed
# limit exactly as before. Only the colour is opinionated, and the opinion is
# that a third of a claimed million is already a lot of conversation.
_CTX_GREEN_MAX = 15   # green below this
_CTX_ORANGE_MAX = 35  # orange up to this, red above


def short_model(model):
    """A model id trimmed to what a human reads: `zai-org/glm-5.2:thinking`
    becomes `glm-5.2:thinking`.

    **Display only.** The full id is what goes on the wire, into the sessions
    table, and into the `in` checks against `TOOLS_MODELS`, `MODEL_LIMITS` and
    `ROUTINE_MODELS` — all of which are exact. Store or send the short form and
    tool calling silently stops firing while the context bar goes uncoloured,
    with no error raised anywhere. So there is exactly one of these, it is
    called at the moment of printing, and nothing keeps its result.
    """
    m = (model or "").strip()
    return m.rsplit("/", 1)[-1] if "/" in m else m


def context_thresholds():
    """(green_max, orange_max), from config if it says otherwise.

    One function so the bar, the hub's token column and the "nearly full" nudge
    cannot drift apart — they were three separate literals away from doing
    exactly that."""
    try:
        from config import CONTEXT_GREEN_MAX, CONTEXT_ORANGE_MAX
        return float(CONTEXT_GREEN_MAX), float(CONTEXT_ORANGE_MAX)
    except (ImportError, TypeError, ValueError):
        return float(_CTX_GREEN_MAX), float(_CTX_ORANGE_MAX)


def context_style(pct):
    """The colour for a context percentage. The single source of that mapping."""
    green_max, orange_max = context_thresholds()
    if pct > orange_max:
        return "red"
    if pct > green_max:
        return "orange3"
    return "green"


# The connection light's rendering, keyed by the state strings `preflight.py`
# returns. **Deliberately here and not there**, for the reason `context_style`
# is here: one mapping read by every consumer, rather than three literals a
# refactor away from disagreeing. This module imports no cfc module, so the
# keys are plain strings — a producer/parser pair across a boundary, which is
# the recurring hazard `HANDOVER.md` tabulates, and it is pinned by round-trip
# in `tests/test_connection.py`: every state preflight can return must have a
# row here. Adding a state without a rendering fails that test rather than
# rendering a blank light.
#
# The wording says what to *do*, not what is wrong. "no server" as a bare label
# is a diagnosis nobody asked for; "run /connect embedding" is the next move.
CONNECTION_STYLE = {
    "connected":   ("●", "green",   "embedder connected"),
    "no server":   ("●", "orange3", "LM Studio is up, embedder is not — "
                                    "/connect embedding"),
    "not running": ("●", "red",     "LM Studio is not running — "
                                    "/connect embedding"),
    "down":        ("●", "red",     "embedder not answering — "
                                    "/connect embedding"),
    # No `/connect` here, and that is the honest answer rather than an
    # omission: a hosted endpoint is not something cfc can start, so offering a
    # command that cannot help would be worse than saying so.
    "hosted":      ("●", "orange3", "hosted embedder unreachable — "
                                    "not cfc's to start"),
}


def connection_light(state):
    """(mark, style, text) for a connection state. The single source.

    An unknown state renders as a dim question mark rather than raising: a
    light is decoration on someone else's screen, and taking the hub down
    because a new state string appeared is a worse failure than showing that we
    don't recognise it. The test is what stops one shipping.
    """
    return CONNECTION_STYLE.get(state, ("?", "dim", f"connection: {state}"))


def make_bar(pct, width=24, ctx=None, limit=None):
    """Build a styled progress bar as a Rich Text.

    Colour comes from context_style, so it matches the hub's token column and
    the post-turn nudge without repeating the thresholds.

    **The trough is bracketed whitespace, not a shade block.** It used to be
    `░` (U+2591 LIGHT SHADE), which is a *fill* character — twenty-four of them
    read as a bar with something in it, so a session 0.1% into a 1M context
    looked meaningfully used. The report was "the bar starts out 1/6 full",
    and the arithmetic was right the whole time; only the empty state lied.
    Whitespace cannot be misread as fill, and the brackets keep what `░` was
    genuinely good for — showing where the end of the bar is, so a short run of
    blocks is legible as a fraction of something.
    """
    filled = int(width * pct / 100)
    fill_style = context_style(pct)

    bar = Text()
    bar.append("[", style="dim")
    bar.append("█" * filled, style=fill_style)
    bar.append(" " * (width - filled))
    bar.append("]", style="dim")
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
