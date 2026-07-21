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
from rich.table import Table

from ui import console, format_ts

# Columns are Tags- and Model-free on purpose. Both were near-permanently empty
# (a tag is rare, and Model only ever printed when a session overrode the
# default), and every column they occupied came out of Title's budget — which is
# the one field you actually pick a session by. Dropping them also drops the
# GROUP_CONCAT subquery that fed Tags. `:tags` still shows a session's tags.


def _strip_md(name):
    """Prompt and persona files are always Markdown, so the extension carries
    no information in a table — it just eats width. Display-only: the stored
    name keeps its extension, and everywhere else still shows it."""
    if name and name.endswith(".md"):
        return name[:-3]
    return name or ""


def _session_table(title):
    """Both views are the same table at different limits; building them in one
    place is what stops them drifting apart again.

    Title is no_wrap + ellipsis rather than wrapping: a wrapped title stacked a
    single row four lines high and pushed the rest of the list off the screen,
    which is worse than a truncated one you can still read."""
    table = Table(title=title, border_style="dim")
    table.add_column("#", style="cyan", justify="right", width=3)
    table.add_column("Updated", width=17)
    table.add_column("Msgs", justify="right", width=4)
    # Every column here carries an explicit width, and that is deliberate.
    # Rich grants a no_wrap column whatever its longest row asks for and takes
    # it out of the flexible columns — one 58-char title starved #, Msgs,
    # Prompt and Persona to zero width, printing a table of empty verticals.
    # Fixing widths first reserves them, so Title truncates instead of bullying.
    # width, not min_width: a flexible Title claims all the slack and starves
    # the fixed columns back to zero, which is the bug this whole block exists
    # to avoid. A fixed 32 keeps every column visible from 80 cols up.
    table.add_column("Title", no_wrap=True, overflow="ellipsis",
                     width=32)
    table.add_column("Prompt", style="magenta", no_wrap=True,
                     overflow="ellipsis", width=8)
    table.add_column("Persona", style="green", no_wrap=True,
                     overflow="ellipsis", width=8)
    return table


_SELECT = (
    "SELECT s.id, s.title, s.updated_at, "
    "(SELECT COUNT(*) FROM messages m "
    "WHERE m.session_id = s.id) as msg_count, "
    "s.system_prompt_name, "
    "s.persona_name "
    "FROM sessions s ORDER BY s.updated_at DESC"
)


def list_sessions(conn):
    rows = conn.execute(_SELECT).fetchall()
    if not rows:
        console.print("No sessions yet.")
        return

    table = _session_table("Sessions")
    table.columns[0].header = "ID"
    table.columns[0].width = 4
    for sid, title, ts, msg_count, prompt_name, persona_name in rows:
        table.add_row(
            str(sid),
            format_ts(ts),
            str(msg_count),
            title,
            _strip_md(prompt_name),
            _strip_md(persona_name),
        )
    console.print(table)
    console.print()


def pick_session(conn):
    """Show recent sessions and let the user pick one or
    start new."""
    rows = conn.execute(_SELECT + " LIMIT 20").fetchall()

    if not rows:
        console.print("\nNo sessions yet. Starting a new "
                      "one.\n")
        return None

    table = _session_table("Recent sessions")
    for i, (sid, title, ts, msg_count,
            prompt_name, persona_name) in enumerate(rows, 1):
        table.add_row(
            str(i),
            format_ts(ts),
            str(msg_count),
            title,
            _strip_md(prompt_name),
            _strip_md(persona_name),
        )
    console.print(table)
    console.print()
    console.print("Type a number to resume, 'n' for new "
                  "session, 'q' to quit.")

    while True:
        choice = input("\n> ").strip().lower()
        if choice == "q":
            return "quit"
        if choice in ("n", "new"):
            return None
        try:
            idx = int(choice)
            if 1 <= idx <= len(rows):
                return rows[idx - 1][0]
            console.print(f"Enter a number between 1 and "
                          f"{len(rows)}.")
        except ValueError:
            console.print("Type a number, 'n' for new, or "
                          "'q' to quit.")
