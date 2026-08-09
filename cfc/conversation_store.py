"""conversation_store.py — the 2.0 SQLite opening and repository boundary
for the ordinary-chat conversation ledger.

Two responsibilities live here because they share one connection's lifetime:

1. **Opening** (`open_store`): revalidate the target, become its one
   kernel-tracked owner, accept only a readable database carrying cfc's own
   application identity and the exact supported schema version (or an
   absent target, which may become a fresh one), and recover any turn an
   earlier owner left active.
2. **Repository operations** (`ConversationStore`): create/list chats, start
   a turn, read the stored snapshot, and finalise a turn's one terminal
   outcome — translating SQLite rows to `conversation_types` records only at
   this boundary.

This module never imports `config.py`, `db.py`, or `cfc.settings` — it
receives an already-resolved path and does not know where that path came
from. Resolving the configured database target, including the legacy
flat-runtime spelling, is `cfc.settings`'s job, not this module's.

**The ownership lock is not a stale-file heuristic.** `fcntl.flock` is held
on a sidecar file for the connection's whole lifetime; the kernel releases
it the moment the owning process exits or dies, so a later process's
`open_store` call either finds the lock genuinely free or genuinely held —
never a lock file whose age it has to guess about. `schedule.py`'s `_Lock`
uses the same primitive for the same reason.
"""
from __future__ import annotations

import dataclasses
import datetime
import fcntl
import os
import sqlite3
from enum import Enum
from pathlib import Path

from cfc import paths
from cfc.conversation_types import (
    CancelledOutcome,
    Chat,
    ChatId,
    ChatKind,
    CompletedOutcome,
    ConversationSnapshot,
    FailedOutcome,
    FailureEvidence,
    FailureKind,
    Message,
    MessageId,
    Role,
    Turn,
    TurnId,
    TurnOutcome,
    Usage,
    utc_now,
)

#: This repository's fixed SQLite `application_id` marker (ASCII "cfc2" read
#: as a big-endian 32-bit int) — distinguishes a cfc 2.0 database from any
#: other SQLite file at the configured path, including v1.9.1's `chat.db`,
#: which never sets this pragma and so always reads back as `0`.
APPLICATION_ID = 0x63666332

#: The one schema version this build understands. Bumped only alongside a
#: real migration path; there is none yet, so an older or newer value both
#: refuse rather than guess.
SCHEMA_VERSION = 1

_RECOVERY_HINT = (
    "preserve anything wanted from it, then move or remove {path} so cfc "
    "can create a fresh database there"
)

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE cfc_chats (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL CHECK (kind = 'ordinary'),
        title TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE cfc_turns (
        id TEXT PRIMARY KEY,
        chat_id TEXT NOT NULL REFERENCES cfc_chats(id),
        position INTEGER NOT NULL,
        model TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        outcome_kind TEXT CHECK (outcome_kind IN ('completed', 'failed', 'cancelled')),
        failure_kind TEXT CHECK (failure_kind IN ('responder', 'internal', 'interrupted')),
        failure_reason TEXT,
        usage_input INTEGER,
        usage_output INTEGER,
        usage_total INTEGER,
        UNIQUE (chat_id, position),
        CHECK (
            (outcome_kind IS NULL AND finished_at IS NULL
                AND failure_kind IS NULL AND failure_reason IS NULL)
            OR (outcome_kind = 'completed' AND finished_at IS NOT NULL
                AND failure_kind IS NULL AND failure_reason IS NULL)
            OR (outcome_kind = 'failed' AND finished_at IS NOT NULL
                AND failure_kind IS NOT NULL AND failure_reason IS NOT NULL)
            OR (outcome_kind = 'cancelled' AND finished_at IS NOT NULL
                AND failure_kind IS NULL AND failure_reason IS NULL)
        )
    )
    """,
    """
    CREATE TABLE cfc_messages (
        id TEXT PRIMARY KEY,
        chat_id TEXT NOT NULL REFERENCES cfc_chats(id),
        turn_id TEXT NOT NULL REFERENCES cfc_turns(id),
        turn_position INTEGER NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE (turn_id, turn_position)
    )
    """,
    "CREATE INDEX idx_cfc_turns_chat ON cfc_turns(chat_id)",
    "CREATE INDEX idx_cfc_messages_chat ON cfc_messages(chat_id)",
    "CREATE INDEX idx_cfc_messages_turn ON cfc_messages(turn_id)",
)


class ConversationStoreError(Exception):
    """Base for every error this module raises, so a caller that wants one
    catch-all for "the store refused" has one.
    """


class TargetUnusable(ConversationStoreError):
    """The path-shape revalidation, repeated at this boundary because Stage
    2 diagnosis may be stale by the time a chat actually starts, failed.
    """

    def __init__(self, path: Path, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


class DatabaseInUse(ConversationStoreError):
    """Another live cfc process already owns this database. Its active
    turns are untouched — this is not evidence they are dead.
    """

    def __init__(self, path: Path):
        self.path = path
        super().__init__(
            f"{path}: already open by another cfc process; wait for it to "
            f"exit, then try again"
        )


class DatabaseProblem(Enum):
    CORRUPT = "corrupt"
    EMPTY_OR_ARBITRARY = "empty_or_arbitrary"
    FOREIGN_APPLICATION = "foreign_application"
    SCHEMA_TOO_OLD = "schema_too_old"
    SCHEMA_TOO_NEW = "schema_too_new"


class DatabaseIncompatible(ConversationStoreError):
    """An existing target failed read-only inspection. Raised before any
    pragma, journal, or schema write touches it.
    """

    def __init__(self, path: Path, problem: DatabaseProblem, detail: str):
        self.path = path
        self.problem = problem
        self.detail = detail
        super().__init__(f"{path}: {detail}")


class UnknownChat(ConversationStoreError):
    def __init__(self, chat_id: ChatId):
        self.chat_id = chat_id
        super().__init__(f"no stored chat with id {chat_id}")


class UnknownTurn(ConversationStoreError):
    def __init__(self, turn_id: TurnId):
        self.turn_id = turn_id
        super().__init__(f"no stored turn with id {turn_id}")


class ConflictingFinalisation(ConversationStoreError):
    """`turn_id` already carries a different terminal outcome than the one
    just submitted. The stored outcome is left exactly as it was.
    """

    def __init__(self, turn_id: TurnId):
        self.turn_id = turn_id
        super().__init__(
            f"turn {turn_id}: a different terminal outcome is already stored"
        )


# --- timestamp round-trip ----------------------------------------------

def _dt_to_text(value: datetime.datetime) -> str:
    return value.isoformat()


def _text_to_dt(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value)


# --- the ownership lock ---------------------------------------------------

class _OwnerLock:
    def __init__(self, handle):
        self._handle = handle

    def release(self) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle, fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


def _lock_path_for(db_path: Path) -> Path:
    return db_path.with_name(db_path.name + ".lock")


def _acquire_owner_lock(db_path: Path) -> _OwnerLock:
    lock_path = _lock_path_for(db_path)
    handle = open(lock_path, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise DatabaseInUse(db_path) from exc
    return _OwnerLock(handle)


# --- opening: fresh initialisation ------------------------------------

def _claim_new_file(path: Path) -> None:
    """Atomically create an empty file at `path`, refusing to overwrite one
    that appeared since the caller last checked. Raises `FileExistsError`
    on that race — the caller falls back to treating `path` as existing.
    """
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
    os.close(fd)


def _initialise_fresh(path: Path) -> sqlite3.Connection:
    _claim_new_file(path)
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(f"PRAGMA application_id = {APPLICATION_ID}")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        for statement in _SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.commit()
    except BaseException:
        conn.rollback()
        conn.close()
        path.unlink(missing_ok=True)
        raise
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# --- opening: existing-target inspection --------------------------------

def _classify_existing(path: Path) -> tuple[DatabaseProblem | None, str | None]:
    """Read-only classification of an existing target. Never opens it
    writable, so a corrupt or foreign file is never touched.
    """
    hint = _RECOVERY_HINT.format(path=path)

    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.OperationalError as exc:
        return DatabaseProblem.CORRUPT, f"could not be opened as SQLite: {exc}; {hint}"

    try:
        try:
            check = conn.execute("PRAGMA quick_check").fetchone()
        except sqlite3.DatabaseError as exc:
            return DatabaseProblem.CORRUPT, f"is not a valid SQLite file: {exc}; {hint}"
        if check is None or check[0] != "ok":
            return DatabaseProblem.CORRUPT, f"failed its integrity check: {check}; {hint}"

        app_id = conn.execute("PRAGMA application_id").fetchone()[0]
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()

    if app_id == 0:
        return (DatabaseProblem.EMPTY_OR_ARBITRARY,
                f"is empty or not a cfc database (no application identity); {hint}")
    if app_id != APPLICATION_ID:
        return (DatabaseProblem.FOREIGN_APPLICATION,
                f"belongs to a different application (application_id={app_id}); {hint}")
    if user_version < SCHEMA_VERSION:
        return (DatabaseProblem.SCHEMA_TOO_OLD,
                f"is schema version {user_version}, older than the {SCHEMA_VERSION} "
                f"this build supports and cannot migrate; {hint}")
    if user_version > SCHEMA_VERSION:
        return (DatabaseProblem.SCHEMA_TOO_NEW,
                f"is schema version {user_version}, newer than the {SCHEMA_VERSION} "
                f"this build supports; use a newer cfc build, or {hint}")
    return None, None


def _inspect_existing_or_raise(path: Path) -> None:
    problem, detail = _classify_existing(path)
    if problem is not None:
        raise DatabaseIncompatible(path, problem, detail)


def _open_writable(path: Path) -> sqlite3.Connection:
    """Reopen an already-verified-current database. No pragma, journal, or
    schema write happens beyond the ordinary per-connection `foreign_keys`
    session setting.
    """
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _open_validated_connection(path: Path) -> sqlite3.Connection:
    if not path.exists():
        try:
            return _initialise_fresh(path)
        except FileExistsError:
            pass  # a concurrent, non-cfc arrival: fall through and inspect it
    _inspect_existing_or_raise(path)
    return _open_writable(path)


# --- opening: recovery of an earlier owner's active turns ------------------

def _recover_interrupted_turns(conn: sqlite3.Connection) -> None:
    """Every turn still active when this connection becomes the store's
    owner belonged to a process that never finished it — this call, or an
    earlier one that never completed. Recovered atomically, once, before
    the store is handed back to a caller.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = conn.execute(
            "SELECT id FROM cfc_turns WHERE outcome_kind IS NULL"
        ).fetchall()
        if rows:
            now = _dt_to_text(utc_now())
            reason = "cfc restarted while this turn was active"
            conn.executemany(
                "UPDATE cfc_turns SET finished_at = ?, outcome_kind = 'failed', "
                "failure_kind = 'interrupted', failure_reason = ? WHERE id = ?",
                [(now, reason, row[0]) for row in rows],
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


# --- row <-> record translation (only here) -----------------------------

def _row_to_chat(row) -> Chat:
    id_, kind, title, created_at, updated_at = row
    return Chat(
        id=ChatId(id_),
        kind=ChatKind(kind),
        title=title,
        created_at=_text_to_dt(created_at),
        updated_at=_text_to_dt(updated_at),
    )


def _row_to_message(row) -> Message:
    id_, chat_id, turn_id, turn_position, role, content, created_at = row
    return Message(
        id=MessageId(id_),
        chat_id=ChatId(chat_id),
        turn_id=TurnId(turn_id),
        turn_position=turn_position,
        role=Role(role),
        content=content,
        created_at=_text_to_dt(created_at),
    )


def _row_to_turn(row) -> Turn:
    (id_, chat_id, position, model, started_at, finished_at,
     outcome_kind, failure_kind, failure_reason, usage_input,
     usage_output, usage_total) = row

    outcome: TurnOutcome | None = None
    if outcome_kind == "completed":
        usage = None
        if usage_input is not None or usage_output is not None or usage_total is not None:
            usage = Usage(input_tokens=usage_input, output_tokens=usage_output,
                           total_tokens=usage_total)
        outcome = CompletedOutcome(usage=usage)
    elif outcome_kind == "failed":
        outcome = FailedOutcome(FailureEvidence(FailureKind(failure_kind), failure_reason))
    elif outcome_kind == "cancelled":
        outcome = CancelledOutcome()

    return Turn(
        id=TurnId(id_),
        chat_id=ChatId(chat_id),
        position=position,
        model=model,
        started_at=_text_to_dt(started_at),
        finished_at=_text_to_dt(finished_at) if finished_at is not None else None,
        outcome=outcome,
    )


def _outcome_columns(outcome: TurnOutcome):
    """`(outcome_kind, failure_kind, failure_reason, usage_input,
    usage_output, usage_total)` for `UPDATE cfc_turns`.
    """
    if isinstance(outcome, CompletedOutcome):
        usage = outcome.usage
        if usage is None:
            return "completed", None, None, None, None, None
        return ("completed", None, None,
                usage.input_tokens, usage.output_tokens, usage.total_tokens)
    if isinstance(outcome, FailedOutcome):
        return ("failed", outcome.evidence.kind.value, outcome.evidence.reason,
                None, None, None)
    if isinstance(outcome, CancelledOutcome):
        return "cancelled", None, None, None, None, None
    raise TypeError(f"not a TurnOutcome: {outcome!r}")


_TURN_COLUMNS = (
    "id, chat_id, position, model, started_at, finished_at, "
    "outcome_kind, failure_kind, failure_reason, "
    "usage_input, usage_output, usage_total"
)


# --- the repository ---------------------------------------------------

class ConversationStore:
    """An opened, owned SQLite repository for the ordinary-chat ledger.
    Construct through `open_store`, never directly.
    """

    def __init__(self, connection: sqlite3.Connection, lock: _OwnerLock):
        self._conn = connection
        self._lock = lock
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._conn.close()
        self._lock.release()

    def __enter__(self) -> "ConversationStore":
        return self

    def __exit__(self, *exc_info) -> bool:
        self.close()
        return False

    # -- chats -----------------------------------------------------------

    def create_chat(self, title: str) -> Chat:
        chat_id = ChatId.new()
        now = utc_now()
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT INTO cfc_chats (id, kind, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (chat_id.value, ChatKind.ORDINARY.value, title,
                 _dt_to_text(now), _dt_to_text(now)),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return Chat(id=chat_id, kind=ChatKind.ORDINARY, title=title,
                    created_at=now, updated_at=now)

    def list_chats(self) -> tuple[Chat, ...]:
        rows = self._conn.execute(
            "SELECT id, kind, title, created_at, updated_at FROM cfc_chats "
            "ORDER BY rowid ASC"
        ).fetchall()
        return tuple(_row_to_chat(row) for row in rows)

    def get_chat(self, chat_id: ChatId) -> Chat:
        row = self._conn.execute(
            "SELECT id, kind, title, created_at, updated_at FROM cfc_chats WHERE id = ?",
            (chat_id.value,),
        ).fetchone()
        if row is None:
            raise UnknownChat(chat_id)
        return _row_to_chat(row)

    # -- turns and messages -----------------------------------------------

    def snapshot(self, chat_id: ChatId) -> ConversationSnapshot:
        self.get_chat(chat_id)
        rows = self._conn.execute(
            "SELECT m.id, m.chat_id, m.turn_id, m.turn_position, m.role, "
            "m.content, m.created_at "
            "FROM cfc_messages m JOIN cfc_turns t ON t.id = m.turn_id "
            "WHERE m.chat_id = ? ORDER BY t.position ASC, m.turn_position ASC",
            (chat_id.value,),
        ).fetchall()
        return ConversationSnapshot(
            chat_id=chat_id, messages=tuple(_row_to_message(row) for row in rows),
        )

    def get_turn(self, turn_id: TurnId) -> Turn:
        turn = self._get_turn_or_none(turn_id)
        if turn is None:
            raise UnknownTurn(turn_id)
        return turn

    def _get_turn_or_none(self, turn_id: TurnId) -> Turn | None:
        row = self._conn.execute(
            f"SELECT {_TURN_COLUMNS} FROM cfc_turns WHERE id = ?",
            (turn_id.value,),
        ).fetchone()
        return _row_to_turn(row) if row is not None else None

    def start_turn(self, chat_id: ChatId, model: str, user_content: str) -> tuple[Turn, Message]:
        self.get_chat(chat_id)
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(position), -1) + 1 FROM cfc_turns WHERE chat_id = ?",
                (chat_id.value,),
            ).fetchone()
            position = row[0]
            turn_id = TurnId.new()
            started_at = utc_now()
            conn.execute(
                "INSERT INTO cfc_turns (id, chat_id, position, model, started_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (turn_id.value, chat_id.value, position, model, _dt_to_text(started_at)),
            )
            message_id = MessageId.new()
            message_created_at = utc_now()
            conn.execute(
                "INSERT INTO cfc_messages "
                "(id, chat_id, turn_id, turn_position, role, content, created_at) "
                "VALUES (?, ?, ?, 0, 'user', ?, ?)",
                (message_id.value, chat_id.value, turn_id.value, user_content,
                 _dt_to_text(message_created_at)),
            )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        turn = Turn(id=turn_id, chat_id=chat_id, position=position, model=model,
                    started_at=started_at)
        message = Message(id=message_id, chat_id=chat_id, turn_id=turn_id,
                           turn_position=0, role=Role.USER, content=user_content,
                           created_at=message_created_at)
        return turn, message

    # -- finalisation: one terminal outcome per turn -----------------------

    def complete_turn(self, turn_id: TurnId, content: str, usage: Usage | None = None) -> Turn:
        return self._finalize(turn_id, CompletedOutcome(usage=usage), assistant_content=content)

    def fail_turn(self, turn_id: TurnId, evidence: FailureEvidence) -> Turn:
        return self._finalize(turn_id, FailedOutcome(evidence))

    def cancel_turn(self, turn_id: TurnId) -> Turn:
        return self._finalize(turn_id, CancelledOutcome())

    def _stored_assistant_content(self, turn_id: TurnId) -> str | None:
        row = self._conn.execute(
            "SELECT content FROM cfc_messages WHERE turn_id = ? AND turn_position = 1",
            (turn_id.value,),
        ).fetchone()
        return row[0] if row is not None else None

    def _finalize(self, turn_id: TurnId, outcome: TurnOutcome,
                   assistant_content: str | None = None) -> Turn:
        conn = self._conn
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = self._get_turn_or_none(turn_id)
        except BaseException:
            conn.rollback()
            raise
        if current is None:
            conn.rollback()
            raise UnknownTurn(turn_id)

        if current.outcome is not None:
            existing_content = (
                self._stored_assistant_content(turn_id)
                if isinstance(current.outcome, CompletedOutcome) else None
            )
            conn.rollback()
            if current.outcome == outcome and existing_content == assistant_content:
                return current
            raise ConflictingFinalisation(turn_id)

        finished_at = utc_now()
        try:
            (outcome_kind, failure_kind, failure_reason,
             usage_input, usage_output, usage_total) = _outcome_columns(outcome)
            conn.execute(
                "UPDATE cfc_turns SET finished_at = ?, outcome_kind = ?, "
                "failure_kind = ?, failure_reason = ?, usage_input = ?, "
                "usage_output = ?, usage_total = ? WHERE id = ?",
                (_dt_to_text(finished_at), outcome_kind, failure_kind, failure_reason,
                 usage_input, usage_output, usage_total, turn_id.value),
            )
            if assistant_content is not None:
                message_id = MessageId.new()
                message_created_at = utc_now()
                conn.execute(
                    "INSERT INTO cfc_messages "
                    "(id, chat_id, turn_id, turn_position, role, content, created_at) "
                    "VALUES (?, ?, ?, 1, 'assistant', ?, ?)",
                    (message_id.value, current.chat_id.value, turn_id.value,
                     assistant_content, _dt_to_text(message_created_at)),
                )
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        return dataclasses.replace(current, finished_at=finished_at, outcome=outcome)


def open_store(path: Path | str) -> ConversationStore:
    """Open the 2.0 conversation ledger at `path`, becoming its owner for
    this process's lifetime.

    `path` must already be resolved — this function does not consult
    `config.py` or any legacy fallback path. Raises `TargetUnusable`
    if the path shape itself is not usable, `DatabaseInUse` if another live
    cfc process already owns it, or `DatabaseIncompatible` if an existing
    target is corrupt, empty/arbitrary, belongs to another application, or
    is an unsupported schema version. An absent target becomes a fresh,
    current database. Any turn left active by an earlier owner is recovered
    to a typed interrupted failure before this call returns.
    """
    path = Path(path)
    reason = paths.usable_target_reason(path)
    if reason is not None:
        raise TargetUnusable(path, reason)

    path.parent.mkdir(parents=True, exist_ok=True)
    lock = _acquire_owner_lock(path)
    try:
        conn = _open_validated_connection(path)
        try:
            _recover_interrupted_turns(conn)
        except BaseException:
            conn.close()
            raise
    except BaseException:
        lock.release()
        raise
    return ConversationStore(conn, lock)
