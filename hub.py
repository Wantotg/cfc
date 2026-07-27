# hub.py — the session browser: what you see before you're in a conversation.
#
# list_sessions() is the /list command's table. pick_session() is the launcher
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
from rich.text import Text

from db import PROVIDER_ROUTINE, PROVIDER_WIKI
from ui import connection_light, console, context_style, format_ts

# Columns are Tags- and Model-free on purpose. Both were near-permanently empty
# (a tag is rare, and Model only ever printed when a session overrode the
# default), and every column they occupied came out of Title's budget — which is
# the one field you actually pick a session by. Dropping them also drops the
# GROUP_CONCAT subquery that fed Tags. `:tags` still shows a session's tags.

HUB_CHATS = 10     # chats on the picker
HUB_ROUTINES = 5   # routines on the picker

# Not a chat: excluded from the picker, still visible in `:list`.
_NON_CHAT = (PROVIDER_WIKI, PROVIDER_ROUTINE)

# Everything the flexible three don't get: ID, Latest message, Msgs, Ctx, plus
# Rich's per-column padding and the vertical rules. The ID column is 4 wide for
# every view now — it used to be declared 3 here and then widened to 4 in
# `list_sessions`/`show_recent_chats` *after* `_widths()` had already divided up
# the terminal, so those two tables were quietly one column over budget.
_CHROME = 4 + 17 + 4 + 7 + (7 * 2) + 8

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
    table.add_column("ID", style="cyan", justify="right", width=4)
    table.add_column("Latest message", width=17)
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


def _add_rows(table, rows):
    """Every view numbers by **session id**, and there is no second numbering.

    There used to be: `/list` showed ids, the picker showed 1..n against what
    was on screen, and this function took a `numbering` argument to serve both.
    The comment here warned that they were different numbers and that
    conflating them was how you opened the wrong session — which is exactly
    what happened, from the other side. A row read off the picker as "7" was
    typed at `/delete chat 7`, where 7 is an id, and that is a destructive
    command. One number everywhere costs a little more typing and removes the
    class."""
    for (sid, title, ts, msg_count, prompt_name, persona_name,
         model, tok_in, tok_out) in rows:
        table.add_row(
            str(sid),
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
    _add_rows(table, rows)
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


def show_recent_chats(conn):
    """`:list chats` — the picker's view, printed from inside a session.

    Deliberately the same rows as `pick_session` (`recent_chats`), not a second
    query: "which conversations do I have" must have one answer whether it is
    asked from the hub or from a session — and since the picker started
    numbering by id too, the same numbers as well.
    """
    rows = recent_chats(conn)
    if not rows:
        console.print("No chats yet.")
        return
    table = _session_table("Recent chats")
    _add_rows(table, rows)
    console.print(table)
    console.print()


def print_connection(state=None):
    """The traffic light. One line, above the picker's prompt.

    **It renders `preflight.connection_state()` and never forms its own
    opinion.** That is the whole design and it is the reason this function is
    four lines: a light that decided anything for itself could disagree with
    the thing it describes, and the failure mode is green over a dead server —
    the one output nobody double-checks, because it is what stops you checking.

    Asking costs ~0.16s when the embedder is up and ~0.5s when it is gone (see
    `preflight.PROBE_CONNECT`), which is what makes a live answer affordable and
    a cache unnecessary. `state` is injectable so a test can drive every
    rendering without a server.

    Import is local: `preflight` shells out to `lms` and `tasklist`, and hub.py
    is imported by the golden harness, which must not acquire a subprocess
    dependency at import time.
    """
    if state is None:
        from preflight import connection_state
        state, _ = connection_state()
    mark, style, text = connection_light(state)
    # `ui.console` is `Console(markup=False)` — chat content must never be
    # reinterpreted as markup — so a styled line is built as a Text, never as
    # square brackets in a string. Found by driving it: the bracket form prints
    # the tags verbatim, which is exactly the kind of thing a test asserting on
    # the mapping would have passed straight through.
    # The mark carries the colour; the words stay at normal weight. `Text(...,
    # style=)` would tint the whole line, because append inherits the base
    # style — which makes a healthy connection a green sentence and a broken
    # one a red paragraph. The dot is the signal, the sentence is the content.
    line = Text()
    line.append(mark, style=style)
    line.append(f" {text}")
    console.print(line)
    return state


def pick_session(conn):
    """Show recent chats and routine health, and let the user pick one or
    start new."""
    rows = recent_chats(conn)

    routines = _routine_rows()

    if not rows:
        if routines:
            _print_routines(routines)
        print_connection()
        console.print("\nNo sessions yet. Starting a new "
                      "one.\n")
        return None

    table = _session_table("Recent chats")
    _add_rows(table, rows)
    console.print(table)
    console.print()
    if routines:
        _print_routines(routines)
    print_connection()
    console.print("Type a chat ID to resume, 'n' for new "
                  "session, 'p' for private, 'q' to quit.")
    console.print("'/list sessions' inside a session shows every session, "
                  "routine runs included.", style="dim")

    # The ids actually on screen. An id that exists but isn't listed is
    # refused rather than opened: the picker's rows are filtered to chats
    # (`recent_chats`), so accepting any id would let a wiki page or a routine
    # transcript be resumed as a conversation — and the number would have come
    # from somewhere other than what the user was looking at.
    listed = {row[0] for row in rows}

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
        except ValueError:
            console.print("Type a chat ID, 'n' for new, 'p' for "
                          "private, or 'q' to quit.")
            continue
        if idx in listed:
            return idx
        console.print("That isn't one of the IDs listed. "
                      "'/list sessions' inside a session shows every one.")
