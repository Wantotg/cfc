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


# sqlite3.connect's own default busy-wait, named so a caller passing its own
# `timeout` (schedule.py's 30s, once due work is known) is a deliberate
# departure from a known value rather than a guess at what "the default" was.
DEFAULT_BUSY_TIMEOUT = 5.0


def db(path=None, timeout=None):
    # `path` is the seam private chat uses: db(":memory:") gets an isolated
    # connection with byte-identical schema and migrations, so every conn-driven
    # write (save_message, titles, agent_turn's own saves) lands in a throwaway
    # database that dies when the connection closes.
    #
    # Default is None, not DB_PATH: a default argument is captured once at
    # definition time, so `path=DB_PATH` would freeze the value the module had at
    # import — and the tests that redirect the database by patching db.DB_PATH
    # would silently hit the real ~/.cfc/chat.db. Read the global at call time.
    #
    # `timeout` is SQLite's busy-wait, in seconds, before a locked database
    # raises `sqlite3.OperationalError`. Every interactive and `:memory:`
    # caller gets `DEFAULT_BUSY_TIMEOUT` unchanged — a human at the REPL
    # should not sit through a 30-second stall the moment they open a chat.
    # `schedule._run` is the one caller that opts into a longer wait, and only
    # after it already knows there is due work to run (B-1.5.1-01a).
    conn = sqlite3.connect(
        DB_PATH if path is None else path,
        timeout=DEFAULT_BUSY_TIMEOUT if timeout is None else timeout,
    )
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
        CREATE TABLE IF NOT EXISTS session_id_seq (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mark INTEGER NOT NULL
        );
    """)
    # Checked before writing, not caught after — an ALTER TABLE that already
    # applies still takes a write lock while SQLite discovers the column is
    # there, and a current, fully-migrated database is the overwhelmingly
    # common connect. See B-1.5.1-01a.
    session_cols = {r[1] for r in conn.execute("PRAGMA table_info(sessions)")}
    for col in ["system_prompt", "system_prompt_name",
                "persona", "persona_name", "traits",
                "first_message_name", "first_message_text",
                "first_message_at"]:
        if col not in session_cols:
            conn.execute(
                f"ALTER TABLE sessions ADD COLUMN {col} TEXT"
            )
    # The one-row rule for Main lives in SQLite itself, not only in
    # get_or_create_main's own check: a partial UNIQUE index on the singleton
    # value means a second 'main' row can never be inserted, race or no race.
    # Every other provider is unrestricted, so this can't be a plain UNIQUE
    # column constraint.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sessions_main_singleton "
        "ON sessions(provider) WHERE provider='main'"
    )
    _migrate_messages(conn)
    _migrate_routine_sessions(conn)
    ensure_session_id_seq(conn)
    return conn


# What a session's `provider` says about where it came from. It is not purely
# "which API answered" and never has been — wiki pages are not an API provider
# either. It is the session-kind discriminator, which is why the routine marker
# lives here rather than in a new column.
PROVIDER_CHAT = "nano-gpt"
PROVIDER_WIKI = "wiki"
PROVIDER_ROUTINE = "routine"
PROVIDER_MAIN = "main"

# Main's fixed, non-editable title (Concept.md: "the session header says Main
# chat rather than relying on a user-editable title to carry the
# distinction" — the title is the other half of that: it is set once, at
# creation, and /title refuses to touch it).
MAIN_TITLE = "Main"

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
    provider — plus, for a wiki session, whether the individual message
    carries the imported page's own source identity (`W-1.6.4-05`) — and a
    routine transcript's provider is never `'wiki'`, so it keeps indexing as
    source='chat', exactly as it did before this marker existed. That is the
    intended behaviour, not a coincidence of the rule — a routine's
    transcript is chat-shaped, and recall filters to the wiki anyway.

    A plain `UPDATE` takes SQLite's write lock the moment it opens a write
    cursor, whether or not its `WHERE` matches anything — so this checks with
    a `SELECT` first, on every connect, and only issues the `UPDATE` (and
    commits) when a legacy row is actually there to backfill (B-1.5.1-01a).
    """
    if not conn.execute(
        "SELECT 1 FROM sessions WHERE provider=? AND title LIKE ? LIMIT 1",
        (PROVIDER_CHAT, _ROUTINE_TITLE_LIKE),
    ).fetchone():
        return
    conn.execute(
        "UPDATE sessions SET provider=? WHERE provider=? AND title LIKE ?",
        (PROVIDER_ROUTINE, PROVIDER_CHAT, _ROUTINE_TITLE_LIKE),
    )
    conn.commit()


def _migrate_messages(conn):
    """Add kind/meta to messages, and classify the rows already there.

    SQLite backfills a new column with its DEFAULT for existing rows, so every
    pre-existing message becomes kind='chat' for free. Only the :remember
    markers need reclassifying, and that runs once: the WHERE clause finds
    nothing on later starts.

    Every write here is guarded by a check first — column existence via
    `PRAGMA table_info`, the NULL backfill via a `SELECT` probe — because a
    plain `ALTER TABLE` or `UPDATE` takes SQLite's write lock as soon as it
    opens, whether or not it ends up changing anything. A current, populated
    database is the overwhelmingly common connect, and on that path this
    function must do no writing at all (B-1.5.1-01a).
    """
    # One flag for all three writes below, not one per kind of write. The
    # guards decide *whether* to write; this decides whether to commit, and
    # the two questions have the same answer for every write in this function
    # — so a flag that tracks only some of them leaves the others open in a
    # transaction that never ends, which is the very failure the guards were
    # added to remove (B-09).
    wrote = False
    cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
    for col, ddl in (
        ("kind", "ALTER TABLE messages ADD COLUMN kind TEXT DEFAULT 'chat'"),
        ("meta", "ALTER TABLE messages ADD COLUMN meta TEXT"),
    ):
        if col not in cols:
            conn.execute(ddl)
            wrote = True

    # Older rows may predate the DEFAULT and hold NULL.
    if conn.execute(
        "SELECT 1 FROM messages WHERE kind IS NULL LIMIT 1"
    ).fetchone():
        conn.execute("UPDATE messages SET kind='chat' WHERE kind IS NULL")
        wrote = True

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
        wrote = True
    if wrote:
        conn.commit()


def ensure_session_id_seq(conn):
    """Seed the durable session-id high-water mark once, from the greatest
    existing `sessions.id` — the same call on a brand-new database (seeds 0)
    and an old one predating this table (seeds its current max). Guarded like
    every other migration here (B-1.5.1-01a): an already-seeded database is
    read, never written, on later connects.

    `Q-1.6-02`: before this mark existed, an automatic id was just SQLite's
    own `MAX(rowid)+1` over `sessions` — so a single chosen high id
    (`/new 900`, the hub's `c`) became the floor every later automatic
    wiki/routine/Main/chat id started from, because that reused rowid was
    oblivious to *why* 900 was the max. The mark is the automatic sequence's
    own position, advanced only by `alloc_session_id`, instead of being
    re-derived from whatever `sessions` currently contains.

    **Seeding from the max is the one place a chosen id still shows through,
    and it is deliberate.** On a database predating this table there is no
    way to tell which ids were allocated and which were picked by hand, so
    the only seed that cannot collide is the greatest one present. A
    migrating database that contains a hand-picked high id therefore inherits
    it once, at its first connect under this build, and never again.
    """
    if conn.execute("SELECT 1 FROM session_id_seq WHERE id=1").fetchone():
        return
    high = conn.execute("SELECT COALESCE(MAX(id), 0) FROM sessions").fetchone()[0]
    conn.execute("INSERT INTO session_id_seq(id, mark) VALUES (1, ?)", (high,))
    conn.commit()


def alloc_session_id(conn):
    """Advance the automatic sequence to the next *free* id and return it, as
    a write inside the caller's own transaction.

    The first `UPDATE` is the seam: SQLite takes its write lock the moment
    that statement runs, so a second connection's own allocation blocks until
    this one commits or rolls back — that is what serialises simultaneous
    allocators, not an explicit `BEGIN`. The caller commits (keeping the mark
    and whatever row it inserted against it) or rolls back (undoing both,
    since they share the one transaction) as a single unit.

    Every automatic session creation — wiki, routine, Main and ordinary chat
    — goes through this, so `import_wiki.py`'s standalone connection uses it
    too rather than its own `cur.lastrowid`.

    **The skip is what keeps a chosen id out of this sequence** (`B-1.6.4-01`).
    `create_chat` no longer moves the mark, so the only thing standing between
    the automatic sequence and a hand-picked id is this loop: it steps over
    anything already occupied instead of the chooser having to push the mark
    up past it. It terminates because every step it takes is over an existing
    `sessions` row and that table is finite — the bound below is that fact
    written down, not a policy, and reaching it means the invariant broke
    rather than that someone chose too many ids.
    """
    def _advance():
        conn.execute("UPDATE session_id_seq SET mark = mark + 1 WHERE id=1")
        return conn.execute(
            "SELECT mark FROM session_id_seq WHERE id=1").fetchone()[0]

    mark = _advance()
    ceiling = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] + 1
    for _ in range(ceiling):
        if not conn.execute(
            "SELECT 1 FROM sessions WHERE id=?", (mark,)
        ).fetchone():
            return mark
        mark = _advance()
    raise RuntimeError(
        f"session id allocation stepped over {ceiling} occupied ids; "
        f"the mark ({mark}) and the sessions table disagree")


def new_session(conn, title="(untitled)", model=None,
                provider=PROVIDER_CHAT):
    """Create a session. `provider` is the session-kind discriminator — pass
    PROVIDER_ROUTINE for a routine run so the hub can tell it from a chat
    without parsing its title."""
    model = model or MODEL
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    new_id = alloc_session_id(conn)
    try:
        conn.execute(
            "INSERT INTO sessions(id, title, model, provider, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (new_id, title, model, provider, now, now),
        )
    except sqlite3.IntegrityError:
        conn.rollback()
        raise
    conn.commit()
    return new_id


class ChatIdTaken(Exception):
    """The chosen id for `create_chat` already names a session — of any
    kind, not just a visible chat. Every session kind shares one primary-key
    namespace (Concept.md's "Chosen durable chat ids"), so a hidden wiki page
    or routine transcript collides exactly like another chat would. Raised
    rather than silently falling back to `new_session`'s auto-increment,
    which would open, rename or replace the occupant instead of refusing."""


def create_chat(conn, chat_id, title="(untitled)", model=None):
    """Create an ordinary durable chat at a caller-chosen positive id.

    The existing auto-id path (`new_session`) is untouched — this is the
    second, narrower creation path chosen-id `/new <id>` and the hub's `c`
    share. The occupancy check and the insert are not two separate races to
    worry about: SQLite's own PRIMARY KEY constraint is the actual guard, so
    a collision from a concurrent insert between the SELECT and the INSERT
    still raises IntegrityError and is reported the same way as an ordinary
    pre-existing row.

    `B-1.6.4-01`: **a chosen id never moves the automatic sequence.** It did
    for one release, which made a mistyped number at the hub's `c` prompt
    permanent: the mark rose to it, `d` deleted the row without lowering the
    mark again, and every session created afterwards carried a sixteen-digit
    id. Deleting the mistake used to be the whole undo (`N-1.5-01`), and
    tying the two together took that away. `alloc_session_id` steps over an
    occupied id instead, so the two id spaces coexist without either one
    dragging the other.
    """
    if isinstance(chat_id, bool) or not isinstance(chat_id, int) or chat_id <= 0:
        raise ValueError(f"chat_id must be a positive int, got {chat_id!r}")
    if conn.execute(
        "SELECT 1 FROM sessions WHERE id=?", (chat_id,)
    ).fetchone():
        raise ChatIdTaken(chat_id)
    model = model or MODEL
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO sessions(id, title, model, provider, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (chat_id, title, model, PROVIDER_CHAT, now, now),
        )
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ChatIdTaken(chat_id)
    conn.commit()
    return chat_id


class DeleteTargetError(Exception):
    """Why a delete target could not be resolved — a missing id, or a row
    that exists but isn't a chat or Main (a wiki page or routine transcript,
    refused even though its id is real)."""


def resolve_delete_target(conn, token):
    """An ordinary chat or Main, resolved by identity and never by an
    editable title (Concept.md's "Delete from the hub, including Main").

    `token` is a positive int chat id, or the literal string 'main'
    (case-insensitive) — the two shapes `/delete chat [<id>|main]` and the
    hub's `d` both accept. Returns a dict: id, title, is_main, message_count.
    Raises DeleteTargetError, with a reason fit to show directly, when
    nothing resolves or the row is real but not a chat.
    """
    if isinstance(token, str) and token.strip().lower() == "main":
        sid = main_session_id(conn)
        if sid is None:
            raise DeleteTargetError(
                "Main hasn't been created yet — nothing to delete.")
    else:
        sid = token
        if not conn.execute(
            "SELECT 1 FROM sessions WHERE id=?", (sid,)
        ).fetchone():
            raise DeleteTargetError(f"No session #{sid}.")
    provider = get_session_provider(conn, sid)
    if provider not in (PROVIDER_CHAT, PROVIDER_MAIN):
        raise DeleteTargetError(
            f"#{sid} isn't a chat (it's a {provider or 'unknown'} session) "
            f"— nothing was deleted.")
    return {
        "id": sid,
        "title": get_session_title(conn, sid),
        "is_main": provider == PROVIDER_MAIN,
        "message_count": conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=?",
            (sid,)).fetchone()[0],
    }


class ChatTargetError(Exception):
    """Why a target could not be resolved for a given verb — a missing id,
    Main, or (rename only, since `W-1.6.4-05`) a row that exists but isn't
    an ordinary chat. The two subclasses below say which verb was refused,
    and no longer share the same refusal set."""


class RenameTargetError(ChatTargetError):
    """Why a rename target could not be resolved — a missing id, Main
    (whose title is fixed, not just usually left alone), or a row that
    exists but isn't an ordinary chat (a wiki page or routine transcript)."""


class OpenTargetError(ChatTargetError):
    """Why a row could not be opened by id from the hub — a missing id, or
    Main (whose fixed profile only loads through 'm'). A wiki page or a
    routine transcript is not a refusal any more (`W-1.6.4-05`) — either
    opens, as the kind of session it actually is."""


def _resolve_chat_target(conn, chat_id, error, main_reason, tail):
    """An ordinary durable chat's (id, title), resolved by identity — never
    Main, a wiki page or a routine transcript.

    One resolver with two wordings rather than two resolvers, which is the
    `lead`-argument shape standing decision 17 already settled on for
    `commands.show_wiki_status`: the refusals differ only in which verb did
    not happen, and a second copy of the provider check is a second thing to
    keep true. `error` is the subclass to raise, `main_reason` the whole
    sentence for Main (whose reason is not just a different verb), and
    `tail` the clause that closes the not-a-chat refusal.
    """
    if not conn.execute(
        "SELECT 1 FROM sessions WHERE id=?", (chat_id,)
    ).fetchone():
        raise error(f"No session #{chat_id}.")
    provider = get_session_provider(conn, chat_id)
    if provider == PROVIDER_MAIN:
        raise error(main_reason)
    if provider != PROVIDER_CHAT:
        raise error(
            f"#{chat_id} isn't a chat (it's a {provider or 'unknown'} "
            f"session) — {tail}.")
    return {"id": chat_id, "title": get_session_title(conn, chat_id)}


def resolve_rename_target(conn, chat_id):
    """`W-10`: the hub's `r` and `/title <id> <new title>` both resolve
    through this before writing anything, so a numeric id that isn't a
    renameable chat is refused identically from either surface.

    Raises RenameTargetError, with a reason fit to show directly. Unlike
    `resolve_delete_target`, Main is refused rather than accepted — a
    rename has no `is_main` branch to take.
    """
    return _resolve_chat_target(
        conn, chat_id, RenameTargetError,
        "Main can't be renamed — its title is fixed.",
        "nothing was renamed")


def resolve_open_target(conn, chat_id):
    """`B-1.6.4-01`, widened by `W-1.6.4-05`: the hub's picker resolves a
    typed id through this instead of checking it against the ten rows it
    happened to print.

    The picker used to accept only what was on screen, so a chat older than
    the ten most recent could not be opened from the hub at all — while `r`
    and `d`, two keys along, had always resolved any id. It then went
    further and refused a wiki page or a routine transcript outright, on the
    reasoning that neither was a conversation to resume — which stopped
    being true the moment `run_session` learned to open either as the kind
    of session it actually is. This resolver's job is narrower now: does the
    id exist, and is it Main (whose fixed profile only loads through `m`,
    never by id — reaching it here would skip `_open_main`'s bundle load).
    Everything else, `run_session` derives itself from the row's `provider`.

    Returns `{"id", "title", "provider"}` rather than refusing a non-chat
    kind — the caller no longer needs to know *what* it is beyond Main to
    decide whether to open it, only `run_session` does, and it reads the
    row itself.
    """
    if not conn.execute(
        "SELECT 1 FROM sessions WHERE id=?", (chat_id,)
    ).fetchone():
        raise OpenTargetError(f"No session #{chat_id}.")
    provider = get_session_provider(conn, chat_id)
    if provider == PROVIDER_MAIN:
        raise OpenTargetError(
            "Main is opened with 'm' at the hub, not by its id.")
    return {"id": chat_id, "title": get_session_title(conn, chat_id),
            "provider": provider}


# --- the last-turn repair boundary (Concept.md's "One latest ordinary turn") -
#
# /swipe and /undo act on the latest durable kind='chat', role='user' row and
# everything caused by it — tool calls, their results, empty retry artefacts,
# and at most one non-empty final answer. Attachments and recall markers are
# context, not sends, and classify_latest_turn never includes them in the
# answer-side ids it returns; the two repair commands must not remove them.

TURN_NOTHING_SENT = "nothing_sent"   # no ordinary user row exists
TURN_UNANSWERED = "unanswered"       # no non-empty final answer yet
TURN_COMPLETED = "completed"         # exactly one non-empty final answer
TURN_AMBIGUOUS = "ambiguous"         # more than one — a later /continue/OOC
                                     # has already built on this send

# What "answer side" means for the walk below: tool calls, their results, and
# ordinary chat rows (empty retry artefacts and the final answer). Attachments
# and recall markers are excluded on purpose — they are context, not sends.
_ANSWER_KINDS = ("tool_call", "tool_result", "chat")


def classify_latest_turn(conn, session_id):
    """Classify the latest ordinary chat turn and return its row ids.

    Returns `(state, user_row_id, answer_row_ids)`:

    - `state` is one of the four TURN_* constants above;
    - `user_row_id` is the latest `kind='chat', role='user'` message id, or
      `None` when `state` is TURN_NOTHING_SENT;
    - `answer_row_ids` is every row after that user row classified as
      answer-side (see `_ANSWER_KINDS`), in id order — never attachments or
      recall markers.

    Uses stored rows and ids only — never rendered text, a message count, or
    a second interpretation of tool-call JSON (Concept.md).
    """
    row = conn.execute(
        "SELECT id FROM messages WHERE session_id=? AND kind='chat' "
        "AND role='user' ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    if not row:
        return TURN_NOTHING_SENT, None, []
    user_id = row[0]

    placeholders = ",".join("?" * len(_ANSWER_KINDS))
    rows = conn.execute(
        f"SELECT id, role, kind, content FROM messages "
        f"WHERE session_id=? AND id>? AND kind IN ({placeholders}) "
        f"ORDER BY id",
        (session_id, user_id, *_ANSWER_KINDS),
    ).fetchall()
    answer_ids = [r[0] for r in rows]
    final_answers = [r[0] for r in rows
                     if r[2] == "chat" and r[1] == "assistant"
                     and (r[3] or "").strip()]
    if not final_answers:
        return TURN_UNANSWERED, user_id, answer_ids
    if len(final_answers) == 1:
        return TURN_COMPLETED, user_id, answer_ids
    return TURN_AMBIGUOUS, user_id, answer_ids


def turn_tool_names(conn, answer_row_ids):
    """The function names of every tool call requested by these answer-side
    rows, in id order. What /swipe and /undo ask, through `tools.is_mutating`,
    to decide whether a classified turn touched a mutating tool — reads the
    persisted `tool_call` meta, never rendered text or a command-local name
    list."""
    if not answer_row_ids:
        return []
    placeholders = ",".join("?" * len(answer_row_ids))
    rows = conn.execute(
        f"SELECT meta FROM messages WHERE id IN ({placeholders}) "
        f"AND kind='tool_call'",
        answer_row_ids,
    ).fetchall()
    names = []
    for (meta,) in rows:
        if not meta:
            continue
        try:
            info = json.loads(meta)
        except json.JSONDecodeError:
            continue
        for call in info.get("tool_calls") or []:
            name = call.get("function", {}).get("name")
            if name:
                names.append(name)
    return names


def prune_turn(conn, user_row_id, answer_row_ids, keep_user):
    """Delete a classified turn's answer side, atomically with its index
    rows. `keep_user=True` is /swipe (the user row survives so the same send
    can be re-answered); `keep_user=False` is /undo (both go).

    Shares `_atomic_delete` with `delete_session` — index rows go first, in
    the same transaction as the message rows they point at (decision 14), and
    a vector-delete failure rolls back the whole prune rather than leaving
    some answer-side rows gone with their old chunks still searchable.
    """
    ids = list(answer_row_ids)
    if not keep_user:
        ids.append(user_row_id)

    def _work(conn):
        drop_chunks_for_messages(conn, ids)
        if ids:
            conn.executemany(
                "DELETE FROM messages WHERE id=?", [(i,) for i in ids])

    _atomic_delete(conn, _work)


class MainCorruption(Exception):
    """More than one Main row exists. `idx_sessions_main_singleton` should
    make this unreachable outside a hand-edited database; when it happens
    anyway, lookup reports it rather than picking the newest row and making
    every other one a convincing impostor."""


def _main_rows(conn):
    return [r[0] for r in conn.execute(
        "SELECT id FROM sessions WHERE provider=? ORDER BY id",
        (PROVIDER_MAIN,)).fetchall()]


def main_session_id(conn):
    """The existing Main row's id, or None. The read-only half of
    get_or_create_main, for a caller that needs to know whether Main already
    exists before deciding whether to run the (more expensive) creation-
    bundle check at all. Raises MainCorruption on more than one row, exactly
    as get_or_create_main does."""
    ids = _main_rows(conn)
    if len(ids) > 1:
        raise MainCorruption(f"{len(ids)} Main rows exist: {ids}")
    return ids[0] if ids else None


def get_or_create_main(conn, first_message_name, first_message_text,
                       model=None):
    """Get-or-create for the one durable Main session identity.

    Returns (session_id, created) — `created` is True only the call that
    actually inserts the row; every later call, from any caller, reopens the
    same one. `first_message_name`/`first_message_text` are the caller's
    already-validated creation bundle (mainchat.load_creation_bundle()) —
    this function is DB-only and does no file I/O, so a caller that hasn't
    validated the bundle yet must do that first and never reach here on
    failure.

    The check and the insert run against one connection's transaction, and
    `idx_sessions_main_singleton` (a partial UNIQUE index on provider='main',
    created in db()) is the actual guard: if another caller's insert lands
    between this function's SELECT and its own INSERT, the INSERT fails with
    IntegrityError rather than producing a second row. That failure is read
    back as "someone else just created it" — not corruption, which is what
    *more than one row already existing* means, and is checked separately,
    both before attempting the insert and again if the insert is refused.
    """
    model = model or MODEL
    ids = _main_rows(conn)
    if len(ids) > 1:
        raise MainCorruption(f"{len(ids)} Main rows exist: {ids}")
    if ids:
        return ids[0], False
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    new_id = alloc_session_id(conn)
    try:
        conn.execute(
            "INSERT INTO sessions(id, title, model, provider, created_at, "
            "updated_at, first_message_name, first_message_text, "
            "first_message_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (new_id, MAIN_TITLE, model, PROVIDER_MAIN, now, now,
             first_message_name, first_message_text, now),
        )
    except sqlite3.IntegrityError:
        conn.rollback()
        ids = _main_rows(conn)
        if len(ids) == 1:
            return ids[0], False
        raise MainCorruption(
            f"{len(ids)} Main rows exist after a create race: {ids}")
    conn.commit()
    return new_id, True


def routine_session(conn, session_id):
    """(id, title) if `session_id` exists and is a routine run, else None.

    The narrow check the routines screen's `open <id>` needs before it hands a
    number to `run_session`: a stale or hand-typed log reference must be
    refused visibly rather than opening whatever chat happens to hold that id.
    Provider-checked, not merely existence-checked — `open 3` on a wiki page's
    id would otherwise resume it as if it were a conversation.
    """
    row = conn.execute(
        "SELECT id, title FROM sessions WHERE id=? AND provider=?",
        (session_id, PROVIDER_ROUTINE),
    ).fetchone()
    return row if row else None


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


# --- the memory index is downstream of messages, and deletes must reach it ---
#
# `chunks` and `vec_chunks` are an index over `messages`, but nothing enforces
# that: there are no foreign keys (`PRAGMA foreign_keys` is 0 and the tables
# were never declared with them), so a delete here does not cascade on its own.
# Deleting a session used to leave both behind, which is three bugs, not one:
#
#   1. **The deleted conversation stays in the retrieval index.** Its vectors
#      are still there, so `search` can still return its text. A delete that
#      leaves the content answering questions is not a delete.
#   2. **Orphaned rows** — a chunk pointing at a session that no longer exists.
#      This is the symptom that got reported; it is the least of it.
#   3. **Mis-attribution, which is the dangerous one.** SQLite reuses rowids
#      at the top of a table, so a later message can take a deleted message's
#      id — and the stale chunk then *joins* cleanly to an unrelated live
#      message. `search` reports it under that message's session and title, so
#      a citation points at a conversation the text never came from. Silent,
#      and indistinguishable from a correct hit.
#
# Explicit cascade rather than real foreign keys: SQLite cannot add one to an
# existing table without rebuilding it, and the chunk/vector schema is already
# flagged as in flux. Revisit at the DB-layer rework — this is the smaller,
# reversible half.


def _has_table(conn, name):
    return bool(conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone())


def drop_chunks(conn, chunk_ids):
    """Delete these chunks and their vectors. Returns (chunks, vectors).

    Does NOT commit — the caller owns the transaction, so the index and the
    messages it indexes go away together or not at all.

    **Vectors first, and a failure here raises rather than continuing.** A
    chunk row without its vector is merely stale; a vector without its chunk
    row is text still in the index that nothing can inspect or attribute. If
    sqlite-vec can't be loaded, the honest outcome is a loud failure, not a
    half-delete of the exact kind this function exists to prevent.

    (import_wiki.clear_chunks_for_message does the same dance for the same
    reason. Kept separate deliberately: that one is part of a bulk importer
    and reports through its own progress output. If you change the deletion
    rules, change both.)
    """
    cids = [(c,) for c in chunk_ids]
    if not cids:
        return 0, 0

    vectors = 0
    if _has_table(conn, "vec_chunks"):
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        vectors = sum(
            conn.execute("SELECT COUNT(*) FROM vec_chunks WHERE chunk_id=?",
                         c).fetchone()[0] for c in cids)
        conn.executemany("DELETE FROM vec_chunks WHERE chunk_id=?", cids)

    conn.executemany("DELETE FROM chunks WHERE id=?", cids)
    return len(cids), vectors


def drop_chunks_for_messages(conn, message_ids):
    """Drop the index rows for these messages. Returns (chunks, vectors)."""
    if not _has_table(conn, "chunks") or not message_ids:
        return 0, 0
    ids = []
    for mid in message_ids:
        ids += [r[0] for r in conn.execute(
            "SELECT id FROM chunks WHERE message_id=?", (mid,))]
    return drop_chunks(conn, ids)


def delete_message(conn, message_id):
    drop_chunks_for_messages(conn, [message_id])
    conn.execute("DELETE FROM messages WHERE id=?", (message_id,))
    conn.commit()


def find_stale_chunks(conn):
    """Chunk ids left behind by a delete that didn't cascade. Read-only.

    Two rules, both exact rather than heuristic:

    * **The message is gone.** Nothing can attribute this chunk to anything.
    * **`chunks.session_id` disagrees with `messages.session_id`.** `chunk_new`
      copies the session id straight off the message row it is chunking, and
      `messages.session_id` is never reassigned anywhere in the codebase — so a
      disagreement cannot be produced by normal operation. It is proof that
      this chunk was written for a *different* message that has since been
      deleted and had its rowid reused. These are the mis-attributed ones, and
      they are the reason a count of orphans understates the damage.

    Returns (gone, misattributed) as two lists of chunk ids.
    """
    if not _has_table(conn, "chunks"):
        return [], []
    gone = [r[0] for r in conn.execute(
        "SELECT c.id FROM chunks c LEFT JOIN messages m ON m.id = c.message_id "
        "WHERE m.id IS NULL ORDER BY c.id")]
    mis = [r[0] for r in conn.execute(
        "SELECT c.id FROM chunks c JOIN messages m ON m.id = c.message_id "
        "WHERE m.session_id != c.session_id ORDER BY c.id")]
    return gone, mis


def prune_stale_chunks(conn):
    """Delete what find_stale_chunks finds. Returns (chunks, vectors).

    The repair half of the missing cascade. Safe to run repeatedly; on a clean
    database it finds nothing. Deleting is the right move rather than
    re-pointing: the text belongs to a conversation that was deleted on
    purpose, so there is nothing to re-point it *at*.
    """
    gone, mis = find_stale_chunks(conn)
    n, v = drop_chunks(conn, sorted(set(gone) | set(mis)))
    conn.commit()
    return n, v


def get_session_title(conn, session_id):
    row = conn.execute(
        "SELECT title FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    return row[0] if row else "(untitled)"


def get_session_provider(conn, session_id):
    """The session-kind discriminator (see the PROVIDER_* constants above),
    or None if the session doesn't exist. What lets a numeric resume tell a
    Main row apart from an ordinary chat by identity rather than by title —
    a user-editable field must never be what selects fixed-profile
    behaviour."""
    row = conn.execute(
        "SELECT provider FROM sessions WHERE id=?", (session_id,)
    ).fetchone()
    return row[0] if row else None


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


def get_traits(conn, session_id):
    """The trait *names* this session carries, in attach order.

    Names, never bodies — the bodies are re-read from the pool on load, so
    editing a trait file updates every session carrying that name instead of
    leaving copies of an old draft frozen in rows nobody would think to look
    at. Same reason a routine keeps `prompt:` as a reference rather than
    inlining the prompt.

    A row that is NULL, empty or unparseable reads as no traits. This is a
    *display and prompt-assembly* field, and the safe direction for a value we
    can't read is the one that carries less into the request — never a crash on
    the way into a session.
    """
    row = conn.execute(
        "SELECT traits FROM sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    if not row or not row[0]:
        return []
    try:
        names = json.loads(row[0])
    except (ValueError, TypeError):
        return []
    return [n for n in names if isinstance(n, str)] \
        if isinstance(names, list) else []


def set_traits(conn, session_id, names):
    """Replace this session's trait list. Stored as a JSON array so the order
    survives; `[]` is written as NULL, so "no traits" has one representation
    in the column rather than two that have to agree."""
    names = [n for n in (names or []) if n]
    conn.execute(
        "UPDATE sessions SET traits=? WHERE id=?",
        (json.dumps(names) if names else None, session_id),
    )
    conn.commit()


def get_first_message(conn, session_id):
    """The frozen opening snapshot for this session, or None if it never got
    one — {"name", "text", "at"}. A dict rather than a tuple: the readers
    (governor, export, hub) are far from here, and a positional tuple would
    make each guess which field is which.
    """
    row = conn.execute(
        "SELECT first_message_name, first_message_text, first_message_at "
        "FROM sessions WHERE id=?",
        (session_id,),
    ).fetchone()
    if not row or not row[1]:
        return None
    return {"name": row[0], "text": row[1], "at": row[2]}


def set_first_message(conn, session_id, name, text, at=None):
    """Freeze a persona's opening onto this session. Meant to be called
    once — the caller (main.py) has already checked the session carries no
    chat turns yet and has no snapshot of its own; this just writes, the same
    division `set_persona` draws between deciding and doing.

    `at` defaults to now in UTC, matching the only other place this module
    stores a timestamp (`new_session`, `save_message`) — see HANDOVER's "two
    time bases" note. A caller passing its own `at` is what lets a test freeze
    the moment without patching the clock.
    """
    at = at or datetime.datetime.now(datetime.timezone.utc).isoformat()
    conn.execute(
        "UPDATE sessions SET first_message_name=?, first_message_text=?, "
        "first_message_at=? WHERE id=?",
        (name, text, at, session_id),
    )
    conn.commit()


def has_chat_messages(conn, session_id):
    """Whether this session has any ordinary chat turn yet.

    First Message eligibility and `/continue`'s refusal both key off this
    rather than a bare row count: an attachment or a recall marker is
    machinery, not a chat turn, and must not count as one.
    """
    row = conn.execute(
        "SELECT 1 FROM messages WHERE session_id=? AND kind='chat' LIMIT 1",
        (session_id,),
    ).fetchone()
    return row is not None


def count_chat_user_turns(conn, session_id):
    """Durable user chat turns in this session — the governor's trait-cadence
    clock (`governor.trait_refresh`).

    `kind='chat', role='user'` only: OOC and `/continue` add no user row
    (governor.py), and attachments/recall markers are their own kinds — so
    none of them can advance a count meant to answer "how many times has the
    person actually spoken". Reopening a session costs nothing either, since
    this is read straight from durable rows rather than kept in memory.
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM messages "
        "WHERE session_id=? AND kind='chat' AND role='user'",
        (session_id,),
    ).fetchone()
    return row[0] if row else 0


def count_chat_answers(conn, session_id):
    """Durable answers in this session — the other half of the title gate
    (`main._finish_turn`, `B-07`).

    The user count above cannot answer *did an earlier turn actually produce
    an answer*: a turn whose provider call fails has already written its user
    row, so a 503 on turn one advances that clock without anything being said
    back. This counts what came back instead. `/continue` and OOC answers are
    indistinguishable from an ordinary one here — they are the same
    `kind='chat', role='assistant'` row — which is why the gate reads both
    counts rather than replacing one with the other.
    """
    row = conn.execute(
        "SELECT COUNT(*) FROM messages "
        "WHERE session_id=? AND kind='chat' AND role='assistant'",
        (session_id,),
    ).fetchone()
    return row[0] if row else 0


def _atomic_delete(conn, do_work):
    """Run `do_work(conn)` and commit, or roll back on any exception and
    re-raise. The one place that owns "index rows before message/session
    rows, and a vector-delete failure rolls back the whole operation" —
    shared by `delete_session` and `prune_turn` so a vector/index failure
    can't leave either one half-completed.
    """
    try:
        do_work(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _delete_session_cascade(conn, session_id):
    """The shared cascade body: index rows first, while the messages that
    identify them still exist, then session_tags, messages, sessions.
    Chunks are also swept by `session_id` directly: a chunk whose message
    was already deleted separately has no other way back to this session,
    and leaving it is how the orphans in the first place happened.

    Shared by `delete_session` and `discard_provisional_chat` — both run it
    inside their own `_atomic_delete`, which is what "the same transaction
    as the existing complete delete_session cascade" (Work Order.md v1.9)
    means: one cascade definition, not a second copy pinned to a chat that
    happens to be empty.
    """
    if _has_table(conn, "chunks"):
        mids = [r[0] for r in conn.execute(
            "SELECT id FROM messages WHERE session_id=?", (session_id,))]
        ids = []
        for mid in mids:
            ids += [r[0] for r in conn.execute(
                "SELECT id FROM chunks WHERE message_id=?", (mid,))]
        ids += [r[0] for r in conn.execute(
            "SELECT id FROM chunks WHERE session_id=?", (session_id,))]
        drop_chunks(conn, sorted(set(ids)))

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


def delete_session(conn, session_id):
    """Delete a session, its messages, and everything indexing them."""
    _atomic_delete(conn, lambda c: _delete_session_cascade(c, session_id))


# --- the provisional automatic chat (Work Order.md v1.9) -------------------
#
# "Discard only a known untouched automatic chat on its controlled exit."
# `main.py` carries a process-local record — {"id", "title", "model",
# "system_prompt_name", "persona_name", "traits"} — for the one ordinary row
# created by hub 'n' or bare '/new', and asks `discard_provisional_chat` to
# re-derive the truth from the row itself at every controlled departure from
# that row's visit. Never trusts the caller's belief that nothing happened
# (standing decision 1's discipline, one level up): a chosen id, a resumed
# row, or a row that picked up a real turn or a customisation is refused
# here regardless of what main.py's own bookkeeping still believes.


def discard_provisional_chat(conn, session_id, opening):
    """Discard `session_id` if it is still exactly the empty, unchanged row
    `opening` describes — the process-local snapshot taken when it was
    created. Returns True if it was discarded.

    Proves, before touching anything: the row still exists and is still an
    ordinary chat (PROVIDER_CHAT — covers both "already deleted" and "this
    id now names something else", though nothing in this codebase ever
    changes a row's provider after creation); it carries no message row of
    any kind and no First Message; it has no tags; and its title, model,
    system prompt name, persona name and traits all still match `opening`.

    Any of those *not* holding is the ordinary outcome for a chat that was
    actually used, resumed, or created at a chosen id — nothing is printed,
    the row is kept, and this returns False silently. Only a row this
    function has just proven empty and unchanged, and that *then* fails to
    delete (an index or vector error), is the exceptional case: the partial
    work is rolled back, the row is kept, and this prints a visible failure
    instead — deleting through the index-aware cascade is not allowed to
    fail silently just because the failure is rare.

    Never touches `session_id_seq`: the cascade doesn't, and this function
    adds nothing on top of it, so a discarded id is never freed for reuse.
    """
    if get_session_provider(conn, session_id) != PROVIDER_CHAT:
        return False
    if get_first_message(conn, session_id) is not None:
        return False
    if get_session_title(conn, session_id) != opening["title"]:
        return False
    if get_session_model(conn, session_id) != opening["model"]:
        return False
    if get_system_prompt_name(conn, session_id) != opening["system_prompt_name"]:
        return False
    if get_persona_name(conn, session_id) != opening["persona_name"]:
        return False
    if get_traits(conn, session_id) != opening["traits"]:
        return False
    if conn.execute(
        "SELECT 1 FROM messages WHERE session_id=? LIMIT 1", (session_id,)
    ).fetchone():
        return False
    if conn.execute(
        "SELECT 1 FROM session_tags WHERE session_id=? LIMIT 1", (session_id,)
    ).fetchone():
        return False

    try:
        _atomic_delete(conn, lambda c: _delete_session_cascade(c, session_id))
    except Exception as e:
        console.print(
            f"[cleanup failed — could not discard empty chat #{session_id}: "
            f"{e}. The chat was kept.]", style="red")
        return False
    console.print(f"Discarded empty chat #{session_id}.")
    return True
