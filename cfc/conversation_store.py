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
directly on the database target's own file descriptor for the connection's
whole lifetime — never a sidecar `.lock` file, which this module neither
creates nor treats as ownership evidence; a leftover one from an earlier
build is inert. The kernel releases the lock the moment the owning process
exits or dies, so a later process's `open_store` call either finds the
target genuinely free or genuinely held — never a lock file whose age it has
to guess about.

**Classification never opens the target through SQLite.** An existing
target's application identity, schema version, and page presence are read
from the header bytes of the same locked descriptor, before SQLite ever
sees the file. This is what keeps a refused target's directory entry set
unchanged: only a target whose header already carries cfc's exact marker
and schema version proceeds to `sqlite3.connect` and SQLite's own integrity
check, so a foreign or incompatible WAL-mode target is never opened in a
way that would grow it `-wal`/`-shm` sidecars.
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
    ProviderProblem,
    Role,
    TimeoutPhase,
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
#:
#: 2 (this build): `cfc_turns` grows `failure_problem`, `failure_timeout_phase`,
#: and `failure_status_code` to persist the extended provider-wire failure
#: vocabulary. A version-1 database takes the existing `SCHEMA_TOO_OLD`
#: refusal route — there is no migration from 1 to 2.
SCHEMA_VERSION = 2

_RECOVERY_HINT = (
    "preserve anything wanted from it, then move or remove {path} so cfc "
    "can create a fresh database there"
)

#: B-2.0-27: a target with no cfc application identity but real page content
#: is not a placeholder to remove — it may be someone else's data. This hint
#: never tells the reader to delete or move it; it says inspect it first.
_POPULATED_UNCLAIMED_HINT = (
    "it may contain data from something other than cfc; preserve and "
    "inspect {path} before touching it, or point DATABASE_PATH at a "
    "different file"
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
        failure_problem TEXT CHECK (failure_problem IN
            ('connection', 'timeout', 'http_status', 'malformed_response')),
        failure_timeout_phase TEXT CHECK (failure_timeout_phase IN
            ('connect', 'write', 'pool', 'read')),
        failure_status_code INTEGER,
        usage_input INTEGER,
        usage_output INTEGER,
        usage_total INTEGER,
        UNIQUE (chat_id, position),
        CHECK (
            (outcome_kind IS NULL AND finished_at IS NULL
                AND failure_kind IS NULL AND failure_reason IS NULL
                AND failure_problem IS NULL)
            OR (outcome_kind = 'completed' AND finished_at IS NOT NULL
                AND failure_kind IS NULL AND failure_reason IS NULL
                AND failure_problem IS NULL)
            OR (outcome_kind = 'failed' AND finished_at IS NOT NULL
                AND failure_kind IS NOT NULL AND failure_reason IS NOT NULL)
            OR (outcome_kind = 'cancelled' AND finished_at IS NOT NULL
                AND failure_kind IS NULL AND failure_reason IS NULL
                AND failure_problem IS NULL)
        ),
        -- failure_timeout_phase/failure_status_code narrow failure_problem;
        -- `IS` rather than `=` so a NULL failure_problem compares as false,
        -- not NULL, and cannot vacuously satisfy the check either way.
        CHECK ((failure_problem IS 'timeout') = (failure_timeout_phase IS NOT NULL)),
        CHECK ((failure_problem IS 'http_status') = (failure_status_code IS NOT NULL))
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
    POPULATED_UNCLAIMED = "populated_unclaimed"
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
    def __init__(self, fd: int):
        self._fd: int | None = fd

    def release(self) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None


def _acquire_target_lock(path: Path) -> tuple[int, bool]:
    """Open `path`, becoming this process's kernel-tracked owner of it.

    Returns `(fd, created_fresh)`. `created_fresh` is true when this call's
    own exclusive create won the race for an absent target — the caller
    then owns initialising it and, on failure, removing exactly the file
    this invocation claimed. `O_CREAT | O_EXCL` first (never a separate
    existence check beforehand) is what makes a concurrent arrival a
    `FileExistsError` here rather than a silently duplicated fresh init:
    losing that race falls back to an ordinary open of what is now an
    existing target.

    Raises `DatabaseInUse` if another live process already holds this
    target's lock, or `TargetUnusable` if the filesystem refuses the open
    itself — a target cfc cannot read and write is refused in this module's
    own vocabulary, with the reason the operating system gave, rather than
    leaving `open_store` as a bare `OSError` no caller of a store expects
    (B-2.0-41). Classification needs write access now that ownership is
    the target's own descriptor, so "cannot open it" is decided here,
    before any header is read.
    """
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
        created_fresh = True
    except FileExistsError:
        try:
            fd = os.open(str(path), os.O_RDWR)
        except OSError as exc:
            raise TargetUnusable(
                path,
                f"cfc could not open it for reading and writing "
                f"({exc.strerror}); cfc owns and writes its own database, so "
                f"read access alone is not enough"
            ) from exc
        created_fresh = False
    except OSError as exc:
        raise TargetUnusable(
            path,
            f"cfc could not create a database file there ({exc.strerror}); "
            f"check that {path.parent} exists and is writable"
        ) from exc
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(fd)
        raise DatabaseInUse(path) from exc
    return fd, created_fresh


def _target_identity(path: Path) -> tuple[int, int] | None:
    """`(st_dev, st_ino)` for whatever `path` names right now, or `None` if
    nothing exists there. A dedicated seam — not a bare `os.stat` call
    inline — so pathname-swap revalidation can be simulated deterministically
    in tests without disturbing every other stat this module performs.
    """
    try:
        st = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    return (st.st_dev, st.st_ino)


def _revalidate_locked_target(path: Path, fd: int) -> None:
    """Confirm `path` still names the exact file this process just locked.
    A concurrent replace-or-remove between the lock and this check means
    the lock is no longer evidence of ownership over whatever now sits at
    `path` — refuse rather than classify or open that other file. Ownership
    of the locked descriptor itself is untouched; the caller still releases
    it normally.
    """
    current = _target_identity(path)
    fd_stat = os.fstat(fd)
    if current is None or current != (fd_stat.st_dev, fd_stat.st_ino):
        raise TargetUnusable(
            path,
            "the file at this path changed identity while cfc was "
            "establishing ownership of it; refusing rather than opening a "
            "different file"
        )


# --- opening: fresh initialisation ------------------------------------

def _initialise_fresh(path: Path) -> sqlite3.Connection:
    """`path` already exists as the empty file `_acquire_target_lock`
    exclusively created for this invocation. On failure, remove exactly
    that file — never a target this invocation did not itself claim.
    """
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

#: The fixed-size leading portion of every SQLite file that carries the
#: facts this module classifies against — magic string, page size, and the
#: `application_id`/`user_version` pragmas' own storage. Reading exactly
#: this many bytes from the locked descriptor never requires SQLite itself
#: to open the file.
_HEADER_SIZE = 100
_SQLITE_MAGIC = b"SQLite format 3\x00"


def _page_size_from_header(header: bytes) -> int | None:
    raw = int.from_bytes(header[16:18], "big")
    size = 65536 if raw == 1 else raw
    if size < 512 or (size & (size - 1)) != 0:
        return None  # not a power of two in SQLite's supported range
    return size


def _int32_from_header(header: bytes, offset: int) -> int:
    return int.from_bytes(header[offset:offset + 4], "big", signed=True)


def _classify_header(
    size: int, header: bytes, path: Path,
) -> tuple[DatabaseProblem | None, str | None]:
    """Classify an existing target from its raw byte size and leading
    `_HEADER_SIZE` bytes alone — no SQLite connection, so a foreign or
    incompatible target is never opened in a way that could grow it
    `-journal`, `-wal`, or `-shm` sidecars (B-2.0-34). A target that passes
    still owes SQLite's own integrity check before it is trusted; a valid
    header only proves the marker and version, never the page content.
    """
    hint = _RECOVERY_HINT.format(path=path)

    if size == 0:
        return DatabaseProblem.EMPTY_OR_ARBITRARY, f"is empty (no application identity); {hint}"
    if len(header) < _HEADER_SIZE or not header.startswith(_SQLITE_MAGIC):
        return DatabaseProblem.CORRUPT, f"is not a valid SQLite file: bad header; {hint}"
    page_size = _page_size_from_header(header)
    if page_size is None:
        return DatabaseProblem.CORRUPT, f"is not a valid SQLite file: invalid page size; {hint}"
    if size < page_size:
        return (DatabaseProblem.CORRUPT,
                f"is truncated (smaller than its own declared page size); {hint}")

    app_id = _int32_from_header(header, 68)
    user_version = _int32_from_header(header, 60)

    if app_id == 0:
        unclaimed_hint = _POPULATED_UNCLAIMED_HINT.format(path=path)
        return (DatabaseProblem.POPULATED_UNCLAIMED,
                f"already contains data cfc did not create (no application "
                f"identity, but {size // page_size} page(s) of content); {unclaimed_hint}")
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


def _open_existing(path: Path, fd: int) -> sqlite3.Connection:
    """Classify the target from the locked descriptor's own header bytes,
    then — only once that header carries cfc's exact marker and schema
    version — connect normally and let SQLite's own integrity check have
    the final word. No read-only or URI-mode connection is ever opened
    against an incompatible target.
    """
    size = os.fstat(fd).st_size
    header = os.pread(fd, _HEADER_SIZE, 0)
    problem, detail = _classify_header(size, header, path)
    if problem is not None:
        raise DatabaseIncompatible(path, problem, detail)

    hint = _RECOVERY_HINT.format(path=path)
    conn = sqlite3.connect(str(path), isolation_level=None)
    try:
        check = conn.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError as exc:
        conn.close()
        raise DatabaseIncompatible(
            path, DatabaseProblem.CORRUPT, f"is not a valid SQLite file: {exc}; {hint}",
        ) from exc
    if check is None or check[0] != "ok":
        conn.close()
        raise DatabaseIncompatible(
            path, DatabaseProblem.CORRUPT, f"failed its integrity check: {check}; {hint}",
        )
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
     outcome_kind, failure_kind, failure_reason,
     failure_problem, failure_timeout_phase, failure_status_code,
     usage_input, usage_output, usage_total) = row

    outcome: TurnOutcome | None = None
    if outcome_kind == "completed":
        usage = None
        if usage_input is not None or usage_output is not None or usage_total is not None:
            usage = Usage(input_tokens=usage_input, output_tokens=usage_output,
                           total_tokens=usage_total)
        outcome = CompletedOutcome(usage=usage)
    elif outcome_kind == "failed":
        evidence = FailureEvidence(
            FailureKind(failure_kind), failure_reason,
            problem=ProviderProblem(failure_problem) if failure_problem is not None else None,
            timeout_phase=(TimeoutPhase(failure_timeout_phase)
                           if failure_timeout_phase is not None else None),
            status_code=failure_status_code,
        )
        outcome = FailedOutcome(evidence)
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
    """`(outcome_kind, failure_kind, failure_reason, failure_problem,
    failure_timeout_phase, failure_status_code, usage_input, usage_output,
    usage_total)` for `UPDATE cfc_turns`.
    """
    if isinstance(outcome, CompletedOutcome):
        usage = outcome.usage
        if usage is None:
            return "completed", None, None, None, None, None, None, None, None
        return ("completed", None, None, None, None, None,
                usage.input_tokens, usage.output_tokens, usage.total_tokens)
    if isinstance(outcome, FailedOutcome):
        evidence = outcome.evidence
        problem = evidence.problem.value if evidence.problem is not None else None
        phase = evidence.timeout_phase.value if evidence.timeout_phase is not None else None
        return ("failed", evidence.kind.value, evidence.reason,
                problem, phase, evidence.status_code, None, None, None)
    if isinstance(outcome, CancelledOutcome):
        return "cancelled", None, None, None, None, None, None, None, None
    raise TypeError(f"not a TurnOutcome: {outcome!r}")


_TURN_COLUMNS = (
    "id, chat_id, position, model, started_at, finished_at, "
    "outcome_kind, failure_kind, failure_reason, "
    "failure_problem, failure_timeout_phase, failure_status_code, "
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
        turn_rows = self._conn.execute(
            f"SELECT {_TURN_COLUMNS} FROM cfc_turns WHERE chat_id = ? ORDER BY position ASC",
            (chat_id.value,),
        ).fetchall()
        message_rows = self._conn.execute(
            "SELECT m.id, m.chat_id, m.turn_id, m.turn_position, m.role, "
            "m.content, m.created_at "
            "FROM cfc_messages m JOIN cfc_turns t ON t.id = m.turn_id "
            "WHERE m.chat_id = ? ORDER BY t.position ASC, m.turn_position ASC",
            (chat_id.value,),
        ).fetchall()
        return ConversationSnapshot(
            chat_id=chat_id,
            turns=tuple(_row_to_turn(row) for row in turn_rows),
            messages=tuple(_row_to_message(row) for row in message_rows),
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
             failure_problem, failure_timeout_phase, failure_status_code,
             usage_input, usage_output, usage_total) = _outcome_columns(outcome)
            conn.execute(
                "UPDATE cfc_turns SET finished_at = ?, outcome_kind = ?, "
                "failure_kind = ?, failure_reason = ?, failure_problem = ?, "
                "failure_timeout_phase = ?, failure_status_code = ?, "
                "usage_input = ?, usage_output = ?, usage_total = ? WHERE id = ?",
                (_dt_to_text(finished_at), outcome_kind, failure_kind, failure_reason,
                 failure_problem, failure_timeout_phase, failure_status_code,
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
    if the path shape itself is not usable or the filesystem refuses to
    open it for reading and writing, `DatabaseInUse` if another live
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
    fd, created_fresh = _acquire_target_lock(path)
    lock = _OwnerLock(fd)
    try:
        _revalidate_locked_target(path, fd)
        conn = _initialise_fresh(path) if created_fresh else _open_existing(path, fd)
        try:
            _recover_interrupted_turns(conn)
        except BaseException:
            conn.close()
            raise
    except BaseException:
        lock.release()
        raise
    return ConversationStore(conn, lock)
