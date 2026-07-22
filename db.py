# db.py — SQLite connection, schema, and every query cfc makes.
#
# The schema is created and migrated on every connect: CREATE TABLE IF NOT
# EXISTS plus ALTER TABLE guarded by OperationalError. That's what makes it
# safe to open an old database with a new build.
#
# Note these functions are not pure data access — the tag and prompt helpers
# print to the console as well as touching the database. That's how they were
# written and this module was split out by moving them verbatim; separating
# the printing from the SQL is a later job, and a behavioural one, so it isn't
# mixed into a move that is supposed to change nothing.
import datetime
import json
import re
import sqlite3
from pathlib import Path

from config import MODEL

from ui import console

DB_PATH = Path.home() / ".cfc" / "chat.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# What a messages row is. 'chat' is the default and covers everything written
# before this column existed.
#
#   chat          a normal user/assistant message
#   attachment    a file injected by :attach
#   recall_marker the note left behind by :remember (see commands.py)
#   tool_call     an assistant message carrying tool_calls
#   tool_result   a role='tool' response
#
# meta is JSON whose shape depends on kind, or NULL for 'chat'.
KINDS = ("chat", "attachment", "recall_marker", "tool_call", "tool_result")

# The marker :remember leaves behind, e.g.
#   [:remember "what did we decide" → 8 excerpts injected (ephemeral)]
# Kept in step with commands.py by tests/test_schema.py, which asserts a marker
# built by the real code parses here.
_MARKER_RE = re.compile(
    r'^\[:remember "(?P<query>.*)" → (?P<n>\d+) excerpts '
    r'injected \(ephemeral\)\]$',
    re.DOTALL,
)


def db(path=None):
    # `path` is the seam private chat uses: db(":memory:") gets an isolated
    # connection with byte-identical schema and migrations, so every conn-driven
    # write (save_message, titles, agent_turn's own saves) lands in a throwaway
    # database that dies when the connection closes.
    #
    # Default is None, not DB_PATH: a default argument is captured once at
    # definition time, so `path=DB_PATH` would freeze the value the module had at
    # import — and the tests that redirect the database by patching db.DB_PATH
    # would silently hit the real ~/.cfc/chat.db. Read the global at call time.
    conn = sqlite3.connect(DB_PATH if path is None else path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY,
            title TEXT,
            model TEXT,
            provider TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            session_id INTEGER,
            role TEXT,
            content TEXT,
            model TEXT,
            tokens_in INTEGER,
            tokens_out INTEGER,
            created_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session
            ON messages(session_id);
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE
        );
        CREATE TABLE IF NOT EXISTS session_tags (
            session_id INTEGER,
            tag_id INTEGER,
            PRIMARY KEY (session_id, tag_id),
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (tag_id) REFERENCES tags(id)
        );
    """)
    for col in ["system_prompt", "system_prompt_name",
                "persona", "persona_name"]:
        try:
            conn.execute(
                f"ALTER TABLE sessions ADD COLUMN {col} TEXT"
            )
        except sqlite3.OperationalError:
            pass
    _migrate_messages(conn)
    _migrate_routine_sessions(conn)
    return conn


# What a session's `provider` says about where it came from. It is not purely
# "which API answered" and never has been — wiki pages are not an API provider
# either. It is the session-kind discriminator, which is why the routine marker
# lives here rather than in a new column.
PROVIDER_CHAT = "nano-gpt"
PROVIDER_WIKI = "wiki"
PROVIDER_ROUTINE = "routine"

# The title runner.py generates: "routine: <name> — <YYYY-MM-DD HH:MM>".
# Used *once*, to backfill runs that predate the marker. Deliberately narrow —
# a hand-written chat called "routine: ideas" must not be swept up, so the
# timestamp shape has to match too.
_ROUTINE_TITLE_LIKE = "routine: % — ____-__-__ __:__"


def _migrate_routine_sessions(conn):
    """Mark pre-existing routine runs with provider='routine'.

    Routine sessions were created with provider='nano-gpt' and told apart only
    by a title prefix, which is not data. This backfills them once; the WHERE
    clause finds nothing on later starts.

    Note what this does to the memory index, because it is easy to change by
    accident: `chunk.py` derives a chunk's `source` from the session's
    provider, and its rule is 'wiki' if provider == 'wiki' else 'chat'. So a
    routine transcript keeps indexing as source='chat', exactly as it did
    before this marker existed. That is the intended behaviour, not a
    coincidence of the rule — a routine's transcript is chat-shaped, and recall
    filters to the wiki anyway.
    """
    n = conn.execute(
        "UPDATE sessions SET provider=? WHERE provider=? AND title LIKE ?",
        (PROVIDER_ROUTINE, PROVIDER_CHAT, _ROUTINE_TITLE_LIKE),
    ).rowcount
    if n:
        conn.commit()


def _migrate_messages(conn):
    """Add kind/meta to messages, and classify the rows already there.

    SQLite backfills a new column with its DEFAULT for existing rows, so every
    pre-existing message becomes kind='chat' for free. Only the :remember
    markers need reclassifying, and that runs once: the WHERE clause finds
    nothing on later starts.
    """
    added = False
    for ddl in ("ALTER TABLE messages ADD COLUMN kind TEXT DEFAULT 'chat'",
                "ALTER TABLE messages ADD COLUMN meta TEXT"):
        try:
            conn.execute(ddl)
            added = True
        except sqlite3.OperationalError:
            pass          # column already there

    # Older rows may predate the DEFAULT and hold NULL.
    conn.execute("UPDATE messages SET kind='chat' WHERE kind IS NULL")

    rows = conn.execute(
        "SELECT id, content FROM messages "
        "WHERE kind='chat' AND content LIKE '[:remember %'"
    ).fetchall()
    for mid, content in rows:
        m = _MARKER_RE.match(content or "")
        if not m:
            continue      # a real message that merely starts that way
        meta = json.dumps({"query": m.group("query"),
                           "excerpts": int(m.group("n"))})
        conn.execute(
            "UPDATE messages SET kind='recall_marker', meta=? WHERE id=?",
            (meta, mid),
        )
    if added or rows:
        conn.commit()


def new_session(conn, title="(untitled)", model=None,
                provider=PROVIDER_CHAT):
    """Create a session. `provider` is the session-kind discriminator — pass
    PROVIDER_ROUTINE for a routine run so the hub can tell it from a chat
    without parsing its title."""
    model = model or MODEL
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO sessions(title, model, provider, "
        "created_at, updated_at) VALUES (?,?,?,?,?)",
        (title, model, provider, now, now),
    )
    conn.commit()
    return cur.lastrowid


def save_message(conn, session_id, role, content,
                 tok_in=None, tok_out=None, model=None,
                 kind="chat", meta=None):
    """Insert a message. kind/meta default to a plain chat row, so callers
    that predate the column need no changes. meta may be a dict or JSON str."""
    model = model or MODEL
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    if meta is not None and not isinstance(meta, str):
        meta = json.dumps(meta)
    conn.execute(
        "INSERT INTO messages(session_id, role, content, "
        "model, tokens_in, tokens_out, created_at, kind, meta) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (session_id, role, content, model,
         tok_in, tok_out, now, kind, meta),
    )
    conn.execute(
        "UPDATE sessions SET updated_at=? WHERE id=?",
        (now, session_id),
    )
    conn.commit()


def load_history(conn, session_id):
    """Rebuild the message list for the API.

    Tool rows need more than role+content: an assistant message that made
    calls carries `tool_calls`, and each result carries the `tool_call_id` it
    answers. ORDER BY id preserves the order they were written in, which is
    what keeps results immediately after the call that asked for them.

    Orphaned calls are dropped — see _drop_orphan_tool_calls.
    """
    rows = conn.execute(
        "SELECT role, content, kind, meta FROM messages "
        "WHERE session_id=? ORDER BY id",
        (session_id,),
    ).fetchall()
    out = []
    for role, content, kind, meta in rows:
        m = {"role": role, "content": content}
        info = {}
        if meta:
            try:
                info = json.loads(meta)
            except json.JSONDecodeError:
                info = {}
        if kind == "tool_call" and info.get("tool_calls"):
            m["tool_calls"] = info["tool_calls"]
        elif kind == "tool_result":
            m["tool_call_id"] = info.get("tool_call_id")
        out.append(m)
    return _drop_orphan_tool_calls(out)


def _drop_orphan_tool_calls(messages):
    """Remove assistant tool_calls that have no matching tool result.

    The API rejects a conversation where an assistant message requests a call
    that is never answered. That happens for real: Ctrl-C during a tool turn,
    or a crash between saving the call and saving its result. Without this,
    one interrupted turn would make a session permanently unopenable — every
    later message would 400 on history the user can't see or edit.

    Dropping is safe: a call with no result contributed nothing anyway.
    """
    answered = {m.get("tool_call_id") for m in messages
                if m.get("role") == "tool"}
    out = []
    for m in messages:
        calls = m.get("tool_calls")
        if not calls:
            out.append(m)
            continue
        kept = [c for c in calls if c.get("id") in answered]
        if len(kept) == len(calls):
            out.append(m)
            continue
        if kept:
            m = dict(m, tool_calls=kept)
            out.append(m)
        elif (m.get("content") or "").strip():
            # keep any prose it said alongside the dropped calls
            m = {k: v for k, v in m.items() if k != "tool_calls"}
            out.append(m)
        # else: nothing but unanswered calls — drop the message entirely
    return out


def list_attachments(conn, session_id):
    """Attachments in this session, oldest first. Returns dicts with the meta
    already decoded. The index a user types at :detach is this list's 1-based
    position, so ordering must stay stable — hence ORDER BY id."""
    rows = conn.execute(
        "SELECT id, meta FROM messages "
        "WHERE session_id=? AND kind='attachment' ORDER BY id",
        (session_id,),
    ).fetchall()
    out = []
    for mid, meta in rows:
        try:
            info = json.loads(meta) if meta else {}
        except json.JSONDecodeError:
            info = {}
        info["message_id"] = mid
        out.append(info)
    return out


def delete_message(conn, message_id):
    conn.execute("DELETE FROM messages WHERE id=?", (message_id,))
    conn.commit()


def get_session_title(conn, session_id):
    row = conn.execute(
        "SELECT title FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    return row[0] if row else "(untitled)"


def set_session_title(conn, session_id, title):
    conn.execute(
        "UPDATE sessions SET title=? WHERE id=?",
        (title, session_id),
    )
    conn.commit()


def get_session_model(conn, session_id):
    row = conn.execute(
        "SELECT model FROM sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    return row[0] if row and row[0] else MODEL


def set_session_model(conn, session_id, model):
    conn.execute(
        "UPDATE sessions SET model=? WHERE id=?",
        (model, session_id),
    )
    conn.commit()


def get_context_info(conn, session_id, model):
    """Get current context size from the last message pair."""
    row = conn.execute(
        "SELECT tokens_in, tokens_out FROM messages "
        "WHERE session_id=? AND tokens_in IS NOT NULL "
        "ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if not row:
        return 0, 0, 0
    tok_in = row[0] or 0
    tok_out = row[1] or 0
    return tok_in, tok_out, tok_in + tok_out


def add_tag(conn, session_id, tag_name):
    tag_name = tag_name.lower().strip()
    if not tag_name:
        console.print("Tag name cannot be empty.")
        return
    row = conn.execute(
        "SELECT id FROM tags WHERE name=?", (tag_name,)
    ).fetchone()
    if row:
        tag_id = row[0]
    else:
        cur = conn.execute(
            "INSERT INTO tags(name) VALUES (?)", (tag_name,)
        )
        tag_id = cur.lastrowid
    try:
        conn.execute(
            "INSERT INTO session_tags(session_id, tag_id) "
            "VALUES (?,?)",
            (session_id, tag_id),
        )
        conn.commit()
        console.print(f"Tagged session #{session_id} with "
                      f"'{tag_name}'.")
    except sqlite3.IntegrityError:
        console.print(f"Session #{session_id} already has tag "
                      f"'{tag_name}'.")


def remove_tag(conn, session_id, tag_name):
    tag_name = tag_name.lower().strip()
    row = conn.execute(
        "SELECT id FROM tags WHERE name=?", (tag_name,)
    ).fetchone()
    if not row:
        console.print(f"Tag '{tag_name}' doesn't exist.")
        return
    tag_id = row[0]
    conn.execute(
        "DELETE FROM session_tags "
        "WHERE session_id=? AND tag_id=?",
        (session_id, tag_id),
    )
    conn.commit()
    console.print(f"Removed tag '{tag_name}' from session "
                  f"#{session_id}.")


def get_session_tags(conn, session_id):
    rows = conn.execute(
        "SELECT t.name FROM tags t "
        "JOIN session_tags st ON st.tag_id = t.id "
        "WHERE st.session_id=? ORDER BY t.name",
        (session_id,),
    ).fetchall()
    return [r[0] for r in rows]


def get_system_prompt(conn, session_id):
    row = conn.execute(
        "SELECT system_prompt FROM sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    return row[0] if row and row[0] else None


def get_system_prompt_name(conn, session_id):
    row = conn.execute(
        "SELECT system_prompt_name FROM sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    return row[0] if row and row[0] else None


def set_system_prompt(conn, session_id, content, name):
    conn.execute(
        "UPDATE sessions SET system_prompt=?, "
        "system_prompt_name=? WHERE id=?",
        (content, name, session_id),
    )
    conn.commit()


def clear_system_prompt(conn, session_id):
    conn.execute(
        "UPDATE sessions SET system_prompt=NULL, "
        "system_prompt_name=NULL WHERE id=?",
        (session_id,),
    )
    conn.commit()


def get_persona(conn, session_id):
    row = conn.execute(
        "SELECT persona FROM sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    return row[0] if row and row[0] else None


def get_persona_name(conn, session_id):
    row = conn.execute(
        "SELECT persona_name FROM sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    return row[0] if row and row[0] else None


def set_persona(conn, session_id, content, name):
    conn.execute(
        "UPDATE sessions SET persona=?, "
        "persona_name=? WHERE id=?",
        (content, name, session_id),
    )
    conn.commit()


def clear_persona(conn, session_id):
    conn.execute(
        "UPDATE sessions SET persona=NULL, "
        "persona_name=NULL WHERE id=?",
        (session_id,),
    )
    conn.commit()


def delete_session(conn, session_id):
    """Delete a session and all its messages from the
    database."""
    conn.execute(
        "DELETE FROM session_tags WHERE session_id=?",
        (session_id,),
    )
    conn.execute(
        "DELETE FROM messages WHERE session_id=?",
        (session_id,),
    )
    conn.execute(
        "DELETE FROM sessions WHERE id=?", (session_id,)
    )
    conn.commit()
