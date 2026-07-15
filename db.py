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
import sqlite3
from pathlib import Path

from config import MODEL

from ui import console

DB_PATH = Path.home() / ".cfc" / "chat.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def db():
    conn = sqlite3.connect(DB_PATH)
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
    return conn


def new_session(conn, title="(untitled)", model=None):
    model = model or MODEL
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO sessions(title, model, provider, "
        "created_at, updated_at) VALUES (?,?,?,?,?)",
        (title, model, "nano-gpt", now, now),
    )
    conn.commit()
    return cur.lastrowid


def save_message(conn, session_id, role, content,
                 tok_in=None, tok_out=None, model=None):
    model = model or MODEL
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO messages(session_id, role, content, "
        "model, tokens_in, tokens_out, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (session_id, role, content, model,
         tok_in, tok_out, now),
    )
    conn.execute(
        "UPDATE sessions SET updated_at=? WHERE id=?",
        (now, session_id),
    )
    conn.commit()


def load_history(conn, session_id):
    rows = conn.execute(
        "SELECT role, content FROM messages "
        "WHERE session_id=? ORDER BY id",
        (session_id,),
    ).fetchall()
    return [{"role": r, "content": c} for r, c in rows]


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
