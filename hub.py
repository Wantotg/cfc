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

from config import MODEL

from ui import console, format_ts


def list_sessions(conn):
    rows = conn.execute(
        "SELECT s.id, s.title, s.model, s.updated_at, "
        "(SELECT COUNT(*) FROM messages m "
        "WHERE m.session_id = s.id) as msg_count, "
        "(SELECT GROUP_CONCAT(t.name, ', ') "
        "FROM session_tags st JOIN tags t "
        "ON t.id = st.tag_id "
        "WHERE st.session_id = s.id) as tags, "
        "s.system_prompt_name, "
        "s.persona_name "
        "FROM sessions s ORDER BY s.updated_at DESC"
    ).fetchall()
    if not rows:
        console.print("No sessions yet.")
        return
    table = Table(
        title="Sessions",
        show_lines=False,
        border_style="dim",
    )
    table.add_column("ID", style="cyan", justify="right",
                     width=4)
    table.add_column("Updated", width=17)
    table.add_column("Msgs", justify="right", width=4)
    table.add_column("Title")
    table.add_column("Tags", style="dim")
    table.add_column("Prompt", style="magenta")
    table.add_column("Persona", style="green")
    table.add_column("Model", style="dim")

    for sid, title, model, ts, msg_count, tags, \
            prompt_name, persona_name in rows:
        tag_str = tags or ""
        prompt_str = prompt_name or ""
        model_str = model if model and model != MODEL \
            else ""
        table.add_row(
            str(sid),
            format_ts(ts),
            str(msg_count),
            title,
            tag_str,
            prompt_str,
            persona_name or "",
            model_str,
        )
    console.print(table)
    console.print()


def pick_session(conn):
    """Show recent sessions and let the user pick one or
    start new."""
    rows = conn.execute(
        "SELECT s.id, s.title, s.model, s.updated_at, "
        "(SELECT COUNT(*) FROM messages m "
        "WHERE m.session_id = s.id) as msg_count, "
        "(SELECT GROUP_CONCAT(t.name, ', ') "
        "FROM session_tags st JOIN tags t "
        "ON t.id = st.tag_id "
        "WHERE st.session_id = s.id) as tags, "
        "s.system_prompt_name, "
        "s.persona_name "
        "FROM sessions s ORDER BY s.updated_at DESC "
        "LIMIT 20"
    ).fetchall()

    if not rows:
        console.print("\nNo sessions yet. Starting a new "
                      "one.\n")
        return None

    table = Table(title="Recent sessions", border_style="dim")
    table.add_column("#", style="cyan", justify="right",
                     width=3)
    table.add_column("Updated", width=17)
    table.add_column("Msgs", justify="right", width=4)
    table.add_column("Title")
    table.add_column("Tags", style="dim")
    table.add_column("Prompt", style="magenta")
    table.add_column("Persona", style="green")
    table.add_column("Model", style="dim")

    for i, (sid, title, model, ts, msg_count, tags,
            prompt_name, persona_name) in enumerate(
            rows, 1):
        tag_str = tags or ""
        prompt_str = prompt_name or ""
        model_str = model if model and model != MODEL \
            else ""
        table.add_row(
            str(i),
            format_ts(ts),
            str(msg_count),
            title,
            tag_str,
            prompt_str,
            persona_name or "",
            model_str,
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
