# export.py — write a session out to the Obsidian vault as markdown.
#
# The database is the source of truth; an export is a readable copy. Exports
# are overwritten by filename, so re-exporting a session updates it in place
# rather than accumulating duplicates.
#
# safe_export() is the auto-export-on-exit path: it must never take the REPL
# down on the way out, so it swallows everything and reports.
import json
from pathlib import Path

try:
    from config import CHAT_EXPORT_DIR
except ImportError:
    CHAT_EXPORT_DIR = ""
try:
    # W-0.9.1-01: the pre-1.3.1 name for the same directory. Kept only so a
    # config.py written before CHAT_EXPORT_DIR existed keeps exporting
    # without a mandatory hand edit — see chat_export_dir() below. Never
    # written to or renamed by cfc itself; that is the user's own file.
    from config import VAULT_PATH
except ImportError:
    VAULT_PATH = ""

from ui import console, format_date, format_ts
from db import get_session_tags, get_first_message


def chat_export_dir():
    """Where exported chats are written. `CHAT_EXPORT_DIR` if the config
    sets it, else the legacy `VAULT_PATH` name for the same directory — the
    one seam both `export_session` and `/config`'s rendering resolve
    through, so the two can't disagree about which folder is configured.
    """
    return CHAT_EXPORT_DIR or VAULT_PATH


def _attachment_line(content, meta):
    """One-line reference for an attached file.

    Falls back to counting the wrapper itself if meta is missing or unreadable
    — an export should degrade to something truthful rather than raise.
    """
    try:
        info = json.loads(meta) if meta else {}
    except json.JSONDecodeError:
        info = {}
    name = info.get("name") or "attachment"
    chars = info.get("chars")
    if chars is None:
        chars = len(content or "")
    digest = (info.get("sha256") or "")[:8]
    lines = (content or "").count("\n") + 1
    kb = chars / 1024
    ref = f"> **Attached:** `{name}` — {lines:,} lines, {kb:,.0f} KB"
    return ref + (f", `sha256:{digest}`" if digest else "")


def _tool_line(kind, content, meta):
    """Compact reference for a tool call or its result.

    Raw JSON dumps of arguments and 30k-char file reads would drown the
    transcript. The database has the detail; the export is a readable record
    of what happened.
    """
    try:
        info = json.loads(meta) if meta else {}
    except json.JSONDecodeError:
        info = {}

    if kind == "tool_call":
        names = []
        for c in info.get("tool_calls") or []:
            fn = (c.get("function") or {})
            arg = ""
            try:
                a = json.loads(fn.get("arguments") or "{}")
                arg = a.get("path") or a.get("pattern") or ""
            except json.JSONDecodeError:
                pass
            names.append(f"`{fn.get('name')}`" + (f" — `{arg}`" if arg else ""))
        return "> **Tool call:** " + ", ".join(names or ["(none)"])

    name = info.get("tool") or "tool"
    try:
        d = json.loads(content or "")
        if isinstance(d, dict) and "error" in d:
            return f"> **Tool:** `{name}` — {d['error']}"
    except (json.JSONDecodeError, TypeError):
        pass
    n = len((content or "").splitlines())
    return f"> **Tool:** `{name}` — approved, {n:,} lines returned"


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
        "created_at, kind, meta FROM messages "
        "WHERE session_id=? ORDER BY id",
        (session_id,),
    ).fetchall()

    total_in = sum(m[2] or 0 for m in messages)
    total_out = sum(m[3] or 0 for m in messages)

    first_message = get_first_message(conn, sid)
    # Counted in the human-facing total: it is visible conversation (an
    # opening AI turn), just not a `messages` row — see Concept.md's First
    # Message section. It carries no tokens of its own, so total_in/total_out
    # above are unaffected.
    total_message_count = len(messages) + (1 if first_message else 0)

    tags = get_session_tags(conn, sid)

    bad_chars = '\\/:*?"<>|'
    safe_title = "".join(
        c for c in title if c not in bad_chars
    ).strip() or "untitled"

    # The **local** date, not the stored one. `created_at` is UTC (db.py is the
    # only module that stores it), so slicing `[:10]` filed a session created
    # after 22:00 local under tomorrow's date — silent, off by one, and only in
    # the evenings.
    date_part = format_date(created_at) if created_at else "unknown"
    filename = f"{date_part}_Session-{sid}_{safe_title}.md"

    vault = Path(chat_export_dir()).expanduser()
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
    lines.append(f"total_messages: {total_message_count}")
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

    if first_message:
        # At the head of the transcript, not the appendices above: it is the
        # conversation's opening turn, unlike the persona/system-prompt bodies
        # it sits below, which are configuration rather than something said.
        lines.append("## AI")
        lines.append(f"*{format_ts(first_message['at'])}*")
        lines.append("")
        lines.append(first_message["text"])
        lines.append("")
        lines.append("---")
        lines.append("")

    for role, content, tok_in, tok_out, created, kind, meta in messages:
        # An attachment's content is the whole file. Writing that into the
        # vault would double the export for nothing: the database already
        # holds it, and the export is a reference, not a second copy.
        if kind == "attachment":
            lines.append(_attachment_line(content, meta))
            lines.append("")
            lines.append("---")
            lines.append("")
            continue

        if kind in ("tool_call", "tool_result"):
            lines.append(_tool_line(kind, content, meta))
            lines.append("")
            continue

        if role == "user":
            label = "You"
        elif role == "assistant":
            label = "AI"
        else:
            label = role.capitalize()

        lines.append(f"## {label}")
        # Local time, like everything else in the vault. Cas's call
        # (2026-07-27): an export is a data file and an absolute timestamp is
        # defensible in one, but it was the only thing in the vault in a
        # different time base, and that inconsistency is itself the trap.
        lines.append(f"*{format_ts(created)}*")
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
