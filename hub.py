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
# **The picker shows chats; `/list` shows everything.** A session's `provider`
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

import models
from db import PROVIDER_MAIN, PROVIDER_ROUTINE, PROVIDER_WIKI
from ui import (connection_light, CONNECTION_STYLE, console,
                context_style, format_ts)

# Columns are Tags- and Model-free on purpose. Both were near-permanently empty
# (a tag is rare, and Model only ever printed when a session overrode the
# default), and every column they occupied came out of Title's budget — which is
# the one field you actually pick a session by. Dropping them also drops the
# GROUP_CONCAT subquery that fed Tags. `/tags` still shows a session's tags.

HUB_CHATS = 10     # chats on the picker
HUB_ROUTINES = 7   # routines on the picker

# Not a chat: excluded from the picker, still visible in `/list`.
_NON_CHAT = (PROVIDER_WIKI, PROVIDER_ROUTINE)

# Everything the flexible three don't get: ID, Latest message, Messages, Ctx,
# plus Rich's per-column padding and the vertical rules. The ID column is 4
# wide for every view now — it used to be declared 3 here and then widened to
# 4 in `list_sessions`/`show_recent_chats` *after* `_widths()` had already
# divided up the terminal, so those two tables were quietly one column over
# budget.
_CHROME = 4 + 17 + 8 + 7 + (7 * 2) + 8

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
    table.add_column("Messages", justify="right", width=8)
    table.add_column("Ctx", justify="right", width=7)
    table.add_column("Title", no_wrap=True, overflow="ellipsis",
                     width=title_w)
    table.add_column("Prompt", style="magenta", no_wrap=True,
                     overflow="ellipsis", width=prompt_w)
    table.add_column("Persona", style="green", no_wrap=True,
                     overflow="ellipsis", width=persona_w)
    return table


# tokens_in/tokens_out of the last message that recorded any: the same "current
# context" definition db.get_context_info uses, so the hub and `/tokens` cannot
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
    f"{_LAST_TOKENS}, {_LAST_TOKENS_OUT}, "
    # The frozen opening is visible conversation but not a `messages` row
    # (Concept.md's First Message section) — counted here so the picker's
    # Messages column agrees with /status and the export's total_messages.
    "(s.first_message_text IS NOT NULL) as has_first_message, "
    # So the tables below can render Main distinctly by identity rather than
    # by its (user-editable, in principle collidable) title — Concept.md.
    "s.provider "
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

    ctx = (tok_in or 0) + (tok_out or 0)
    if not ctx:
        return Text("—", style="dim")
    limit = models.context_limit(model)
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
         model, tok_in, tok_out, has_first_message, provider) in rows:
        # Rendered distinctly by identity, not by title text — a title is
        # user-editable everywhere else and could in principle read "Main"
        # by coincidence, which is exactly why Concept.md asks for this to
        # key off `provider` rather than the string on screen.
        title_cell = (Text(title, style="bold cyan")
                     if provider == PROVIDER_MAIN else title)
        table.add_row(
            str(sid),
            format_ts(ts),
            str(msg_count + (1 if has_first_message else 0)),
            _context_cell(model, tok_in, tok_out),
            title_cell,
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


def _freshness(routine, ts_text, now=None):
    """(label, style) for a routine's Last run cell.

    **The colour says whether this routine is owed a run. It renders
    `schedule.why_not_due()` and forms no opinion of its own** — standing
    decision 16, applied one panel up the screen from the connection light and
    for the same reason. Until v0.9.2 this was hours-since-last-run against the
    v0.4 thresholds, which is a *proxy* for "is anything owed" and a poor one:
    `weekly` landed three days after those thresholds were written, so a weekly
    job that absorbed its week on schedule showed red for five days in seven,
    and a `command` routine — four of six on Cas's machine — can never be
    overdue at all yet aged into red like everything else.

    What the same function costs the old one could not buy: **if the OS tick
    stops firing, every scheduled routine goes orange and stays orange.** No
    threshold over a timestamp can say that.

    The order of the branches is the whole of it.

    1. An **unparseable** timestamp is the raw string, dim, and it must be
       decided before anything consults `why_not_due` — that function refuses
       to run on a log line it cannot read, and its refusal reads as *not due*.
       A naive mapping paints a broken log green, which is exactly the "green
       over a dead server" failure decision 16 exists to prevent.
    2. **Never run** stays `never`, dim. The cell's *text* already carries the
       fact, so a colour would add alarm and no information, and it would cry
       wolf on the day you write a routine.
    3. **Dim also means "cannot be owed a run"** — disabled, or a trigger
       `parse_trigger` won't read. Green would claim nothing is owed, which is a
       different and stronger thing to say about a routine that will never fire.
       Note this puts `trigger: command` and a *malformed* trigger in the same
       cell; the conflation is real and is the hub's broken-routine blind spot
       (`D-10`), not something a colour here can fix.

       **That blind spot is bigger than this branch, and `D-10`'s `BACKLOG.md`
       entry is the body** (written v1.0, after driving it). A routine that
       parses but fails `validate()` — a prompt file that moved, a renamed read
       root — never reaches this branch at all and renders **green**, identical
       to a healthy one, because nothing here consults `validate()`. Green over
       a routine that cannot run is decision 16's own failure shape one panel up
       from the light it was written for. Read the entry before changing this
       function; the cost of checking is measured there and it is not small.
    4. Otherwise the answer is `why_not_due(...) is None`: orange for owed,
       green for nothing owed.

    **The reason string stays unparsed.** `why_not_due` returns prose because
    that is what makes "why didn't this fire" answerable, and this function uses
    only `is None`. Matching on its wording would add a seventh row to
    `HANDOVER.md`'s producer/parser table inside the fix for a bug caused by a
    signal forming its own opinion. `trigger: command` is detected with
    `parse_trigger`, which returns `(None, None)`, for the same reason.

    **Red is deliberately gone from this column.** "How badly overdue" is not a
    fact `why_not_due` knows — a daily job is due from its trigger until
    midnight and then due again — and reconstructing severity from that means
    inventing the threshold this design was chosen to avoid. `failed` is still
    red in the Status column, where it belongs.

    `now` is injectable so the due cases are writable without freezing the clock.
    """
    if not ts_text:
        return "never", "dim"
    try:
        when = datetime.datetime.strptime(ts_text, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(ts_text), "dim"

    label = when.strftime("%Y-%m-%d %H:%M")

    # Local, like `routines`: `schedule` shells nothing out, but it reaches the
    # agent stack (db, backup, runner) inside `_run`, and hub.py is imported by
    # the golden harness. A hub render must not pay for that at import time.
    from schedule import parse_trigger, why_not_due

    if not routine.enabled:
        return label, "dim"
    _kind, at = parse_trigger(routine.trigger)
    if at is None:
        return label, "dim"
    if why_not_due(routine, now or datetime.datetime.now()) is None:
        return label, "orange3"
    return label, "green"


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

    # One clock for the whole panel, so two rows rendered a millisecond apart
    # can never disagree about whether the same trigger time has passed.
    now = datetime.datetime.now()
    out = []
    for r in good:
        # **`_freshness` goes inside the per-routine `try`, never the outer
        # one.** `pick_session` renders this panel under `if routines:`, so `[]`
        # and "no routines configured" are the same screen — one routine that
        # upsets `why_not_due` in the outer handler would delete the whole panel
        # silently, which is this project's signature failure shape one
        # indentation level away. Here the cost is confined to its own row, and
        # the row still appears: a dim `?` rather than a vanished routine, the
        # same call `ui.connection_light` makes for an unmapped state, because
        # taking a row off the "is everything still running" panel is the worse
        # failure of the two.
        try:
            status, ts, review = last_run(r.id)
            label, style = _freshness(r, ts, now)
        except Exception:
            status, ts, review = None, None, False
            label, style = "?", "dim"
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
    # **Printed only when a row is actually orange** (Cas's call, 2026-07-28).
    # The connection light gets away with a bare colour because
    # `print_connection` prints dot *plus* sentence — "the dot is the signal,
    # the sentence is the content" — and this column has no content half: a
    # colour on a cell headed *Last run* has no sentence beside it to say what
    # it means. A legend that is always there is furniture you stop reading; one
    # that appears exactly when it applies is the sentence arriving with its
    # signal. It says what is happening rather than what is wrong, because
    # orange here is not a fault — it is the normal state of a routine between
    # its trigger and the next tick.
    if any(style == "orange3" for _, _, style, _, _ in rows):
        console.print("  orange: due, waiting for the next scheduled tick",
                      style="dim")
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
    """`/list chats` — the picker's view, printed from inside a session.

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


# What the hub accepts, and what each key means. **One table, read by the
# dispatch and by the help screen**, because a hand-written help screen is a
# fourth list with nothing checking it — and the day it disagrees it teaches the
# wrong command confidently. Invariant 13 keeps the session's three lists in
# agreement by asserting rather than remembering; this is the same move one
# level up, and `tests/test_hub.py` fails if a key exists that the help does not
# describe.
#
# A chat id is deliberately not in here. It is not a key, it is data off the
# screen in front of you, and the help says so in its own line.
_SHOW_HELP = object()       # print the help and stay at the prompt

HUB_KEYS = (
    (("n", "new"), None, "start a new chat"),
    (("m", "main"), "main",
     "open Main — one durable, vault-configured chat"),
    (("p", "private"), "private",
     "start a private chat — in memory, nothing written to disk"),
    (("h", "?", "help"), _SHOW_HELP, "this screen"),
    (("q", "quit"), "quit", "leave cooking for cats"),
)

# Typed key → what pick_session returns. Built from the table rather than
# written beside it, so the two cannot disagree.
_HUB_DISPATCH = {key: value for keys, value, _ in HUB_KEYS for key in keys}


def print_hub_help():
    """`h` at the hub — what can be typed here, derived from what is accepted.

    **Everything on this screen is generated.** The keys come from `HUB_KEYS`,
    which is also the dispatch, and the light's legend comes from
    `ui.CONNECTION_STYLE`, which is also what the light renders. A help screen is
    exactly the artefact nobody re-reads, so the only safe kind is one that
    cannot be wrong.

    The one hand-written line is the pointer to `/help`, and it is prose because
    it is a fact about where the session's commands are documented, not a list
    of them. Repeating twenty-four verbs here would be the fourth list this
    design exists to avoid.
    """
    console.print()
    console.print("At the hub", style="bold")
    width = max(len(" / ".join(k)) for k, _, _ in HUB_KEYS) + 2
    for keys, _, what in HUB_KEYS:
        line = Text(f"  {' / '.join(keys):<{width}}", style="cyan")
        line.append(what, style="dim")
        console.print(line)
    line = Text(f"  {'<number>':<{width}}", style="cyan")
    line.append("resume that chat — the ids in the table above", style="dim")
    console.print(line)

    console.print()
    console.print("The connection light", style="bold")
    for state in CONNECTION_STYLE:
        mark, style, text = connection_light(state)
        line = Text("  ")
        line.append(mark, style=style)
        line.append(f" {text}", style="dim")
        console.print(line)

    console.print()
    console.print("Inside a chat", style="bold")
    # highlight=False: rich's auto-highlighter reads `/help` as a path and
    # colours the slash separately, which makes the one line about how to type
    # commands look like a rendering fault.
    console.print("  Commands start with /. /help lists all of them; "
                  "/status says what this chat is carrying.",
                  style="dim", highlight=False)
    console.print()


def _routine_problem_count():
    """Distinct routines with a problem: malformed files plus anything that
    fails `validate()`. Closes `D-10` without touching `_freshness` — this is
    a *validation* signal, deliberately separate from "is a run owed".

    Never raises: the routine folder is a vault path over the /mnt/c bridge,
    and a broken hub is a worse failure than a missing nudge.
    """
    try:
        from routines import list_routines
        good, bad = list_routines()
    except Exception:
        return 0
    n = len(bad)
    for r in good:
        try:
            if r.validate():
                n += 1
        except Exception:
            n += 1
    return n


def _print_routine_problem_nudge():
    """`! N routines have problems — open a chat and type /routine`, only
    when there's something to say. This is the hub's only mention of the
    command screens — no shortcut key, no health dashboard, just the pointer
    the D-10 finding asked for."""
    n = _routine_problem_count()
    if n:
        plural, verb = ("", "has") if n == 1 else ("s", "have")
        console.print(f"! {n} routine{plural} {verb} problems "
                      f"— open a chat and type /routine", style="red")


def pick_session(conn):
    """Show recent chats and routine health, and let the user pick one or
    start new.

    An empty hub gets the same prompt and choices as a populated one
    (Concept.md) — it used to auto-create an ordinary chat before any input
    was possible, which meant a first-ever action could never be `m` or `p`.
    """
    rows = recent_chats(conn)

    routines = _routine_rows()

    if rows:
        table = _session_table("Recent chats")
        _add_rows(table, rows)
        console.print(table)
        console.print()
    else:
        console.print("\nNo sessions yet.\n")
    if routines:
        _print_routines(routines)
    _print_routine_problem_nudge()
    print_connection()
    console.print("Type a chat ID to resume, 'n' for new session, 'm' for "
                  "Main, 'p' for private, 'h' for help, 'q' to quit.")
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
        # The dispatch *is* `HUB_KEYS`. A key that works and isn't on the help
        # screen is now impossible rather than merely unlikely.
        if choice in _HUB_DISPATCH:
            value = _HUB_DISPATCH[choice]
            if value is _SHOW_HELP:
                print_hub_help()
                continue
            return value
        try:
            idx = int(choice)
        except ValueError:
            console.print("Type a chat ID, or one of: "
                          + ", ".join(k[0] for k, _, _ in HUB_KEYS)
                          + "  ('h' explains them).")
            continue
        if idx in listed:
            return idx
        console.print("That isn't one of the IDs listed. "
                      "'/list sessions' inside a session shows every one.")
