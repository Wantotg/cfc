# export.py — write a session out to the Obsidian vault as markdown.
#
# The database is the source of truth; an export is a readable copy. Exports
# are overwritten by filename, so re-exporting a session updates it in place
# rather than accumulating duplicates.
#
# safe_export() is the auto-export-on-exit path: it must never take the REPL
# down on the way out, so it swallows everything and reports.
from pathlib import Path

from config import VAULT_PATH

from ui import console
from db import get_session_tags


def export_session(conn, session_id, quiet=False):
    session = conn.execute(
        "SELECT id, title, model, provider, "
        "created_at, updated_at, system_prompt, "
        "system_prompt_name, persona, persona_name "
        "FROM sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    if not session:
        console.print(f"No session #{session_id} found.")
        return False

    sid, title, model, provider, \
        created_at, updated_at, sys_prompt, sys_prompt_name, \
        persona, persona_name = session

    messages = conn.execute(
        "SELECT role, content, tokens_in, tokens_out, "
        "created_at FROM messages "
        "WHERE session_id=? ORDER BY id",
        (session_id,),
    ).fetchall()

    total_in = sum(m[2] or 0 for m in messages)
    total_out = sum(m[3] or 0 for m in messages)

    tags = get_session_tags(conn, sid)

    bad_chars = '\\/:*?"<>|'
    safe_title = "".join(
        c for c in title if c not in bad_chars
    ).strip() or "untitled"

    date_part = created_at[:10] if created_at else "unknown"
    filename = f"{date_part}_Session-{sid}_{safe_title}.md"

    vault = Path(VAULT_PATH).expanduser()
    vault.mkdir(parents=True, exist_ok=True)
    filepath = vault / filename

    lines = []
    lines.append("---")
    lines.append(f"session_id: {sid}")
    lines.append(f'title: "{title}"')
    lines.append(f"model: {model}")
    lines.append(f"provider: {provider}")
    lines.append(f"created_at: {created_at}")
    lines.append(f"updated_at: {updated_at}")
    lines.append(f"total_messages: {len(messages)}")
    lines.append(f"total_tokens_in: {total_in}")
    lines.append(f"total_tokens_out: {total_out}")
    if sys_prompt_name:
        lines.append(f'system_prompt: "{sys_prompt_name}"')
    else:
        lines.append("system_prompt: null")
    if persona_name:
        lines.append(f'persona: "{persona_name}"')
    else:
        lines.append("persona: null")        
    if tags:
        lines.append("tags:")
        for tag in tags:
            lines.append(f"  - {tag}")
    else:
        lines.append("tags: []")
    lines.append("---")
    lines.append("")
    lines.append(f"# Session #{sid} - {title}")
    lines.append("")
    if persona:
        lines.append(f"## Persona")
        lines.append(f"*{persona_name}*")
        lines.append("")
        lines.append(persona)
        lines.append("")
        lines.append("---")
        lines.append("")
    
    if sys_prompt:
        lines.append(f"## System Prompt")
        lines.append(f"*{sys_prompt_name}*")
        lines.append("")
        lines.append(sys_prompt)
        lines.append("")
        lines.append("---")
        lines.append("")

    for role, content, tok_in, tok_out, created in messages:
        if role == "user":
            label = "You"
        elif role == "assistant":
            label = "AI"
        else:
            label = role.capitalize()

        lines.append(f"## {label}")
        lines.append(f"*{created}*")
        lines.append("")
        lines.append(content)
        lines.append("")
        lines.append("---")
        lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    if quiet:
        console.print(f"[auto-exported: {filename}]")
    else:
        console.print(f"Exported to: {filepath}")
    return True


def safe_export(conn, session_id):
    """Auto-export with error handling."""
    try:
        export_session(conn, session_id, quiet=True)
    except Exception as e:
        console.print(f"[auto-export failed: {e}]")
