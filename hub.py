# hub.py — the session browser: what you see before you're in a conversation.
#
# list_sessions() is the :list command's table. pick_session() is the launcher
# prompt at startup, and returns one of:
#   an int   — resume that session id
#   None     — start a new session
#   "quit"   — leave without opening anything
#
# The three-way return is why callers can't just test truthiness: session id 0
# would be falsy, and None and "quit" mean different things.
#
# **The picker shows chats; `:list` shows everything.** A session's `provider`
# is the kind discriminator (see db.py), and the picker excludes wiki pages and
# routine runs — the wiki alone is already 20 rows and grows every import, and
# routine runs arrive one per trigger forever once the scheduler lands. Both
# were crowding real conversations off a 20-row list.
#
# The exclusion is a **deny list, not an allow list**, and that is deliberate:
# an unrecognised provider shows up as a chat. Getting an extra row is a
# visible, correctable mistake; silently hiding someone's conversation is not.
import datetime

from rich.table import Table

from db import PROVIDER_ROUTINE, PROVIDER_WIKI
from ui import console, context_style, format_ts

# Columns are Tags- and Model-free on purpose. Both were near-permanently empty
# (a tag is rare, and Model only ever printed when a session overrode the
# default), and every column they occupied came out of Title's budget — which is
# the one field you actually pick a session by. Dropping them also drops the
# GROUP_CONCAT subquery that fed Tags. `:tags` still shows a session's tags.

HUB_CHATS = 10     # chats on the picker
HUB_ROUTINES = 5   # routines on the picker

# Not a chat: excluded from the picker, still visible in `:list`.
_NON_CHAT = (PROVIDER_WIKI, PROVIDER_ROUTINE)

# Everything the flexible three don't get: #, Updated, Msgs, Ctx, plus Rich's
# per-column padding and the vertical rules.
_CHROME = 3 + 17 + 4 + 7 + (7 * 2) + 8

_TITLE_MIN = 20     # below this a title stops being recognisable
_TITLE_ENOUGH = 50  # past this, slack is worth more to Prompt/Persona
_NAME_MIN = 8
_NAME_MAX = 14


def _strip_md(name):
    """Prompt and persona files are always Markdown, so the extension carries
    no information in a table — it just eats width. Display-only: the stored
    name keeps its extension, and everywhere else still shows it."""
    if name and name.endswith(".md"):
        return name[:-3]
    return name or ""


def _widths():
    """(title, prompt, persona) for the current terminal.

    Computed, but still *fixed* widths when the table is built, which is the
    point. Rich grants a no_wrap column whatever its longest row asks for and
    takes it out of the flexible columns — one 58-char title once starved #,
    Msgs, Prompt and Persona to zero width and printed a table of empty
    verticals. A flexible Title reproduces it from the other side by claiming
    all the slack. Measuring the terminal instead gets long titles on a wide
    window without either failure mode.

    Past `_TITLE_ENOUGH` the slack goes to Prompt and Persona instead: a title
    with 70 columns to spread over is mostly trailing space, while at width 8
    every prompt name reads 'medium …' and tells you nothing. Truncating the
    field that distinguishes rows is the more expensive mistake."""
    avail = console.size.width - _CHROME
    prompt = persona = _NAME_MIN
    title = max(_TITLE_MIN, avail - prompt - persona)
    if title > _TITLE_ENOUGH:
        shift = min(title - _TITLE_ENOUGH, (_NAME_MAX - _NAME_MIN) * 2)
        title -= shift
        prompt += shift - shift // 2
        persona += shift // 2
    return title, prompt, persona


def _session_table(title):
    """Both views are the same table at different limits; building them in one
    place is what stops them drifting apart again.

    Title is no_wrap + ellipsis rather than wrapping: a wrapped title stacked a
    single row four lines high and pushed the rest of the list off the screen,
    which is worse than a truncated one you can still read."""
    title_w, prompt_w, persona_w = _widths()
    table = Table(title=title, border_style="dim")
    table.add_column("#", style="cyan", justify="right", width=3)
    table.add_column("Updated", width=17)
    table.add_column("Msgs", justify="right", width=4)
    table.add_column("Ctx", justify="right", width=7)
    table.add_column("Title", no_wrap=True, overflow="ellipsis",
                     width=title_w)
    table.add_column("Prompt", style="magenta", no_wrap=True,
                     overflow="ellipsis", width=prompt_w)
    table.add_column("Persona", style="green", no_wrap=True,
                     overflow="ellipsis", width=persona_w)
    return table


# tokens_in/tokens_out of the last message that recorded any: the same "current
# context" definition db.get_context_info uses, so the hub and `:tokens` cannot
# disagree about how full a session is.
_LAST_TOKENS = (
    "(SELECT m.tokens_in FROM messages m WHERE m.session_id = s.id "
    " AND m.tokens_in IS NOT NULL ORDER BY m.id DESC LIMIT 1)"
)
_LAST_TOKENS_OUT = (
    "(SELECT m.tokens_out FROM messages m WHERE m.session_id = s.id "
    " AND m.tokens_in IS NOT NULL ORDER BY m.id DESC LIMIT 1)"
)

_SELECT = (
    "SELECT s.id, s.title, s.updated_at, "
    "(SELECT COUNT(*) FROM messages m "
    "WHERE m.session_id = s.id) as msg_count, "
    "s.system_prompt_name, "
    "s.persona_name, "
    "s.model, "
    f"{_LAST_TOKENS}, {_LAST_TOKENS_OUT} "
    "FROM sessions s"
)
_ORDER = " ORDER BY s.updated_at DESC"


def _context_cell(model, tok_in, tok_out):
    """The Ctx column: how full this session's context is, coloured.

    Percent of the model's claimed limit, through the same `context_style` the
    token bar uses. Falls back to a raw count when the model has no known limit
    — a number with no denominator is still worth showing, and inventing a
    denominator would not be."""
    from rich.text import Text
    from config import MODEL_LIMITS

    ctx = (tok_in or 0) + (tok_out or 0)
    if not ctx:
        return Text("—", style="dim")
    limit = MODEL_LIMITS.get(model)
    if not limit:
        # No denominator, so no colour — an uncoloured raw count says "this is
        # a size, not a verdict". Abbreviated only once it's long enough for
        # the abbreviation to be true: 8 tokens rendered as "0k" reads as zero.
        return Text(f"{ctx:,}" if ctx < 1000 else f"{ctx / 1000:.0f}k",
                    style="dim")
    pct = ctx / limit * 100
    return Text(f"{pct:.1f}%", style=context_style(pct))


def _add_rows(table, rows, numbering):
    """`numbering` is 'id' for :list (open it by that number) or 'index' for the
    picker (1..n against what's on screen). They are different numbers and
    conflating them is how you open the wrong session."""
    for i, (sid, title, ts, msg_count, prompt_name, persona_name,
            model, tok_in, tok_out) in enumerate(rows, 1):
        table.add_row(
            str(sid if numbering == "id" else i),
            format_ts(ts),
            str(msg_count),
            _context_cell(model, tok_in, tok_out),
            title,
            _strip_md(prompt_name),
            _strip_md(persona_name),
        )


def list_sessions(conn):
    """Every session, routine runs and wiki pages included. This is the
    'show me everything' view — the picker is the curated one, and keeping
    this unfiltered is what stops a routine transcript becoming unreachable."""
    rows = conn.execute(_SELECT + _ORDER).fetchall()
    if not rows:
        console.print("No sessions yet.")
        return

    table = _session_table("Sessions")
    table.columns[0].header = "ID"
    table.columns[0].width = 4
    _add_rows(table, rows, numbering="id")
    console.print(table)
    console.print()


def _freshness(ts_text):
    """(label, style) for when a routine last ran.

    Green under 24h, orange to 48h, red past that — the roadmap's thresholds.
    A routine that has never run is dim rather than red: 'never' is a different
    fact from 'overdue', and colouring it as failure would cry wolf on the day
    you write one.

    An unparseable timestamp shows the raw string rather than being dropped. A
    log line this code can't read is worth seeing, not hiding."""
    if not ts_text:
        return "never", "dim"
    try:
        when = datetime.datetime.strptime(ts_text, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(ts_text), "dim"
    hours = (datetime.datetime.now() - when).total_seconds() / 3600
    if hours < 24:
        style = "green"
    elif hours < 48:
        style = "orange3"
    else:
        style = "red"
    return when.strftime("%Y-%m-%d %H:%M"), style


def _routine_rows(limit=HUB_ROUTINES):
    """(name, last-run label, style, status) for the most recently run
    routines, newest first.

    One row per *routine*, not per run: the useful question is 'is each of
    these still running', and five rows of the same nightly job would answer
    nothing. Its last run is the freshness signal.

    Returns [] on any failure. The routine folder lives in the vault behind a
    config path, so it can be missing, unmounted or unreadable — and none of
    that is a reason the session picker shouldn't open."""
    try:
        from routines import last_run, list_routines
        good, _bad = list_routines()
    except Exception:
        return []

    out = []
    for r in good:
        try:
            status, ts, review = last_run(r.id)
        except Exception:
            status, ts, review = None, None, False
        label, style = _freshness(ts)
        out.append((r.name, label, style, status or "", ts or "", bool(review)))
    # Never-run routines sort last; among the rest, most recent first.
    out.sort(key=lambda row: row[4], reverse=True)
    return [(n, l, s, st, rv) for n, l, s, st, _, rv in out[:limit]]


def _print_routines(rows):
    table = Table(title="Routines", border_style="dim")
    table.add_column("Routine", no_wrap=True, overflow="ellipsis", width=24)
    table.add_column("Last run", width=17)
    table.add_column("Status", width=8)
    from rich.text import Text
    for name, label, style, status, review in rows:
        # Two signals, one cell: a failed loop is red, a loop that finished but
        # whose output looks off is a yellow 'review' (the run WORKED — it just
        # wants a glance), everything else the dim status. 'review' shadows 'ok'
        # here only because the cell is narrow; the log keeps both facts.
        if status == "failed":
            st_text, st_style = "failed", "red"
        elif review:
            st_text, st_style = "review", "yellow"
        else:
            st_text, st_style = status, "dim"
        table.add_row(name, Text(label, style=style), Text(st_text, style=st_style))
    console.print(table)
    console.print()


def recent_chats(conn, limit=HUB_CHATS):
    """The picker's rows: recent sessions that are conversations.

    A function rather than an inline query so there is exactly one definition
    of "is a chat" and a test can call the same code the picker does. The test
    for this originally rebuilt the SQL itself and therefore proved nothing —
    it passed against a deliberately broken filter."""
    placeholders = ",".join("?" * len(_NON_CHAT))
    return conn.execute(
        f"{_SELECT} WHERE COALESCE(s.provider,'') NOT IN ({placeholders})"
        f"{_ORDER} LIMIT ?",
        (*_NON_CHAT, limit),
    ).fetchall()


def pick_session(conn):
    """Show recent chats and routine health, and let the user pick one or
    start new."""
    rows = recent_chats(conn)

    routines = _routine_rows()

    if not rows:
        if routines:
            _print_routines(routines)
        console.print("\nNo sessions yet. Starting a new "
                      "one.\n")
        return None

    table = _session_table("Recent chats")
    _add_rows(table, rows, numbering="index")
    console.print(table)
    console.print()
    if routines:
        _print_routines(routines)
    console.print("Type a number to resume, 'n' for new "
                  "session, 'p' for private, 'q' to quit.")
    console.print("':list' inside a session shows every session, "
                  "routine runs included.", style="dim")

    while True:
        choice = input("\n> ").strip().lower()
        if choice == "q":
            return "quit"
        if choice in ("n", "new"):
            return None
        if choice in ("p", "private"):
            return "private"
        try:
            idx = int(choice)
            if 1 <= idx <= len(rows):
                return rows[idx - 1][0]
            console.print(f"Enter a number between 1 and "
                          f"{len(rows)}.")
        except ValueError:
            console.print("Type a number, 'n' for new, 'p' for "
                          "private, or 'q' to quit.")
