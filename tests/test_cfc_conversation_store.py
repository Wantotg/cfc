"""test_cfc_conversation_store.py — cfc/conversation_store.py: opening,
ownership, schema/version enforcement, and the repository operations the
conversation service needs. Every database lives under `tmp_path`; nothing
here imports `config.py`, touches a configured or legacy path, or reaches
the network.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cfc import conversation_store as store_mod
from cfc.conversation_types import (
    CancelledOutcome,
    CompletedOutcome,
    FailedOutcome,
    FailureEvidence,
    FailureKind,
    Role,
    TurnId,
    Usage,
)

CHILD_SCRIPT = Path(__file__).resolve().parent / "fixtures" / "conversation_store_child.py"


def db_path(tmp_path: Path) -> Path:
    return tmp_path / "nested" / "chat.db"


class _FailOnce:
    """Wraps a real `sqlite3.Connection` and raises once, on the first
    `execute` call whose SQL contains `trigger`, then behaves normally for
    everything else. `sqlite3.Connection` is a C type and cannot be
    monkeypatched directly (`execute` is a read-only attribute on both the
    class and any instance), so this proxy is the injection seam instead —
    `store._conn` is a plain attribute this module's own code owns.
    """

    def __init__(self, real, trigger: str):
        self._real = real
        self._trigger = trigger
        self._fired = False

    def execute(self, sql, *args, **kwargs):
        if not self._fired and self._trigger in sql:
            self._fired = True
            raise sqlite3.OperationalError(f"simulated failure: {self._trigger}")
        return self._real.execute(sql, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _dump_schema(path: Path) -> list[str]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return sorted(
            row[0] for row in conn.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")
        )
    finally:
        conn.close()


# --- fresh initialisation and reopen through real separate connections -----

def test_fresh_open_creates_a_current_database(tmp_path):
    path = db_path(tmp_path)
    store = store_mod.open_store(path)
    try:
        assert path.exists()
    finally:
        store.close()

    raw = sqlite3.connect(str(path))
    try:
        assert raw.execute("PRAGMA application_id").fetchone()[0] == store_mod.APPLICATION_ID
        assert raw.execute("PRAGMA user_version").fetchone()[0] == store_mod.SCHEMA_VERSION
        tables = {r[0] for r in raw.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"cfc_chats", "cfc_turns", "cfc_messages"} <= tables
    finally:
        raw.close()


def test_reopen_through_a_new_connection_sees_the_same_database(tmp_path):
    path = db_path(tmp_path)
    store = store_mod.open_store(path)
    chat = store.create_chat("first session")
    store.close()

    reopened = store_mod.open_store(path)
    try:
        chats = reopened.list_chats()
        assert [c.id for c in chats] == [chat.id]
        assert chats[0].title == "first session"
    finally:
        reopened.close()


def test_current_database_reopen_performs_no_schema_write(tmp_path):
    path = db_path(tmp_path)
    store_mod.open_store(path).close()
    schema_before = _dump_schema(path)

    reopened = store_mod.open_store(path)
    reopened.close()

    assert _dump_schema(path) == schema_before


# --- existing-target inspection: refuse before any mutation -----------------

def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_foreign_sqlite(path: Path, application_id, user_version: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        if application_id is not None:
            conn.execute(f"PRAGMA application_id = {application_id}")
        conn.execute(f"PRAGMA user_version = {user_version}")
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("build,expected_problem", [
    (lambda p: _write_bytes(p, b"not a sqlite database, just some bytes" * 4),
     store_mod.DatabaseProblem.CORRUPT),
    (lambda p: _write_bytes(p, b""),
     store_mod.DatabaseProblem.EMPTY_OR_ARBITRARY),
    (lambda p: _write_foreign_sqlite(p, application_id=None, user_version=0),
     store_mod.DatabaseProblem.EMPTY_OR_ARBITRARY),
    (lambda p: _write_foreign_sqlite(p, application_id=0x11111111, user_version=0),
     store_mod.DatabaseProblem.FOREIGN_APPLICATION),
    (lambda p: _write_foreign_sqlite(p, application_id=store_mod.APPLICATION_ID, user_version=0),
     store_mod.DatabaseProblem.SCHEMA_TOO_OLD),
    (lambda p: _write_foreign_sqlite(p, application_id=store_mod.APPLICATION_ID, user_version=99),
     store_mod.DatabaseProblem.SCHEMA_TOO_NEW),
], ids=["corrupt", "empty", "arbitrary-sqlite", "foreign-application", "schema-too-old",
        "schema-too-new"])
def test_incompatible_targets_refuse_without_mutation(tmp_path, build, expected_problem):
    path = db_path(tmp_path)
    build(path)
    before = path.read_bytes()

    with pytest.raises(store_mod.DatabaseIncompatible) as exc_info:
        store_mod.open_store(path)

    assert exc_info.value.problem is expected_problem
    assert "move or remove" in exc_info.value.detail
    assert path.read_bytes() == before
    for suffix in ("-journal", "-wal", "-shm"):
        assert not (path.parent / (path.name + suffix)).exists()


def test_directory_target_is_refused_before_locking(tmp_path):
    path = tmp_path / "adir"
    path.mkdir()
    with pytest.raises(store_mod.TargetUnusable):
        store_mod.open_store(path)


# --- fresh initialisation failure: rollback and cleanup ownership ----------

def test_fresh_initialisation_failure_removes_only_the_file_it_created(tmp_path, monkeypatch):
    path = db_path(tmp_path)
    assert not path.exists()

    real_connect = sqlite3.connect

    def fake_connect(*args, **kwargs):
        return _FailOnce(real_connect(*args, **kwargs), "CREATE TABLE cfc_messages")

    monkeypatch.setattr(store_mod.sqlite3, "connect", fake_connect)

    with pytest.raises(sqlite3.OperationalError):
        store_mod.open_store(path)

    monkeypatch.undo()
    assert not path.exists()
    assert path.parent.exists()  # the parent it had to create is harmless residue


def test_fresh_initialisation_failure_does_not_touch_a_preexisting_file(tmp_path):
    """The cleanup path is scoped to a file this invocation itself created —
    it must never fire when initialisation was never attempted because the
    target already existed (and was, say, incompatible).
    """
    path = db_path(tmp_path)
    _write_bytes(path, b"garbage, not sqlite")

    with pytest.raises(store_mod.DatabaseIncompatible):
        store_mod.open_store(path)

    assert path.exists()
    assert path.read_bytes() == b"garbage, not sqlite"


# --- recovery of an earlier owner's active turn -----------------------------

def test_reopen_recovers_a_single_active_turn_to_interrupted_failure(tmp_path):
    path = db_path(tmp_path)
    store = store_mod.open_store(path)
    chat = store.create_chat("t")
    turn, _msg = store.start_turn(chat.id, model="m", user_content="hi")
    store.close()  # simulates the process disappearing mid-turn

    reopened = store_mod.open_store(path)
    try:
        recovered = reopened.get_turn(turn.id)
        assert isinstance(recovered.outcome, FailedOutcome)
        assert recovered.outcome.evidence.kind is FailureKind.INTERRUPTED
        assert reopened._stored_assistant_content(turn.id) is None

        turn2, _ = reopened.start_turn(chat.id, model="m", user_content="again")
        assert turn2.position == turn.position + 1
    finally:
        reopened.close()


def test_recovery_does_not_repeat_on_a_later_uneventful_reopen(tmp_path):
    path = db_path(tmp_path)
    store = store_mod.open_store(path)
    chat = store.create_chat("t")
    turn, _ = store.start_turn(chat.id, model="m", user_content="hi")
    store.close()

    once = store_mod.open_store(path)
    recovered_once = once.get_turn(turn.id)
    once.close()

    twice = store_mod.open_store(path)
    recovered_twice = twice.get_turn(turn.id)
    twice.close()

    assert recovered_once.finished_at == recovered_twice.finished_at
    assert recovered_once.outcome == recovered_twice.outcome


# --- single-process ownership refusal ---------------------------------------

def test_a_second_open_refuses_while_the_first_still_owns_it(tmp_path):
    path = db_path(tmp_path)
    first = store_mod.open_store(path)
    try:
        with pytest.raises(store_mod.DatabaseInUse):
            store_mod.open_store(path)
    finally:
        first.close()

    second = store_mod.open_store(path)
    second.close()


# --- real cross-process ownership: kernel-released, not a stale heuristic --

def _wait_for(path: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.02)
    raise TimeoutError(f"{path} never appeared within {timeout}s")


def test_a_real_child_process_owns_the_store_until_it_dies(tmp_path):
    path = db_path(tmp_path)
    ready = tmp_path / "ready"
    info = tmp_path / "info"

    proc = subprocess.Popen(
        [sys.executable, str(CHILD_SCRIPT), str(path), str(ready), str(info)],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        _wait_for(ready, 10.0)
        chat_id_value, turn_id_value = info.read_text(encoding="utf-8").splitlines()

        with pytest.raises(store_mod.DatabaseInUse):
            store_mod.open_store(path)

        # the refusal never touched anything: the child's turn is untouched
        raw = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = raw.execute(
                "SELECT outcome_kind FROM cfc_turns WHERE id = ?", (turn_id_value,)
            ).fetchone()
            assert row == (None,)
        finally:
            raw.close()

        proc.kill()
        proc.wait(timeout=5)

        # kernel-released, not a stale-file heuristic: a new owner opens
        # immediately and recovers exactly the turn the child left active
        reopened = store_mod.open_store(path)
        try:
            recovered = reopened.get_turn(TurnId(turn_id_value))
            assert isinstance(recovered.outcome, FailedOutcome)
            assert recovered.outcome.evidence.kind is FailureKind.INTERRUPTED
        finally:
            reopened.close()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


# --- foreign keys and constraints ------------------------------------------

def test_foreign_keys_are_enforced_for_turns(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "INSERT INTO cfc_turns (id, chat_id, position, model, started_at) "
                "VALUES ('x', 'does-not-exist', 0, 'm', '2026-01-01T00:00:00+00:00')"
            )
    finally:
        store.close()


def test_foreign_keys_are_enforced_for_messages(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "INSERT INTO cfc_messages "
                "(id, chat_id, turn_id, turn_position, role, content, created_at) "
                "VALUES ('x', ?, 'no-such-turn', 0, 'user', 'hi', "
                "'2026-01-01T00:00:00+00:00')",
                (chat.id.value,),
            )
    finally:
        store.close()


def test_chat_kind_constraint_rejects_non_ordinary(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "INSERT INTO cfc_chats (id, kind, title, created_at, updated_at) "
                "VALUES ('x', 'private', 't', '2026-01-01T00:00:00+00:00', "
                "'2026-01-01T00:00:00+00:00')"
            )
    finally:
        store.close()


def test_turn_position_uniqueness_is_enforced_per_chat(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c")
        turn, _ = store.start_turn(chat.id, "m", "q")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "INSERT INTO cfc_turns (id, chat_id, position, model, started_at) "
                "VALUES ('dup', ?, ?, 'm', '2026-01-01T00:00:00+00:00')",
                (chat.id.value, turn.position),
            )
    finally:
        store.close()


def test_message_turn_position_uniqueness_is_enforced_per_turn(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c")
        turn, _ = store.start_turn(chat.id, "m", "q")
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "INSERT INTO cfc_messages "
                "(id, chat_id, turn_id, turn_position, role, content, created_at) "
                "VALUES ('dup', ?, ?, 0, 'user', 'again', '2026-01-01T00:00:00+00:00')",
                (chat.id.value, turn.id.value),
            )
    finally:
        store.close()


# --- durable reads/writes: round trip, ordering, terminal outcomes ---------

def test_round_trip_through_a_new_connection_preserves_everything(tmp_path):
    path = db_path(tmp_path)
    store = store_mod.open_store(path)
    chat = store.create_chat("round trip")
    turn1, _ = store.start_turn(chat.id, model="m1", user_content="first question")
    store.complete_turn(turn1.id, "first answer",
                         Usage(input_tokens=3, output_tokens=5, total_tokens=8))
    turn2, _ = store.start_turn(chat.id, model="m2", user_content="second question")
    store.complete_turn(turn2.id, "second answer", usage=None)
    store.close()

    reopened = store_mod.open_store(path)
    try:
        snapshot = reopened.snapshot(chat.id)
        contents = [(m.role, m.content) for m in snapshot.messages]
        assert contents == [
            (Role.USER, "first question"), (Role.ASSISTANT, "first answer"),
            (Role.USER, "second question"), (Role.ASSISTANT, "second answer"),
        ]

        t1 = reopened.get_turn(turn1.id)
        t2 = reopened.get_turn(turn2.id)
        assert t1.outcome.usage == Usage(input_tokens=3, output_tokens=5, total_tokens=8)
        assert t2.outcome.usage is None  # omitted usage stays unknown, not zero
        assert (t1.position, t2.position) == (0, 1)
        assert t1.id != t2.id and t1.id != turn2.id
    finally:
        reopened.close()


def test_failed_and_cancelled_turns_remain_distinct_and_carry_no_assistant_row(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c")

        t1, _ = store.start_turn(chat.id, "m", "q1")
        failed = store.fail_turn(t1.id, FailureEvidence(FailureKind.RESPONDER, "declared"))
        assert isinstance(failed.outcome, FailedOutcome)
        assert store._stored_assistant_content(t1.id) is None

        t2, _ = store.start_turn(chat.id, "m", "q2")
        cancelled = store.cancel_turn(t2.id)
        assert isinstance(cancelled.outcome, CancelledOutcome)
        assert store._stored_assistant_content(t2.id) is None

        assert type(failed.outcome) is not type(cancelled.outcome)
    finally:
        store.close()


@pytest.mark.parametrize("finalize", [
    lambda store, turn_id: store.complete_turn(turn_id, "ok"),
    lambda store, turn_id: store.fail_turn(turn_id, FailureEvidence(FailureKind.RESPONDER, "x")),
    lambda store, turn_id: store.cancel_turn(turn_id),
], ids=["completed", "failed", "cancelled"])
def test_a_later_turn_is_permitted_after_every_terminal_state(tmp_path, finalize):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c")
        turn, _ = store.start_turn(chat.id, "m", "q1")
        finalize(store, turn.id)
        turn2, _ = store.start_turn(chat.id, "m", "q2")
        assert turn2.position == turn.position + 1
        assert turn2.outcome is None
    finally:
        store.close()


# --- finalisation: repeated observes, conflicting refuses -------------------

def test_repeated_identical_finalisation_is_idempotent(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c")
        turn, _ = store.start_turn(chat.id, "m", "q")
        usage = Usage(input_tokens=1, output_tokens=2, total_tokens=3)

        first = store.complete_turn(turn.id, "answer", usage)
        second = store.complete_turn(turn.id, "answer", usage)

        assert first.outcome == second.outcome
        assert first.finished_at == second.finished_at
        count = store._conn.execute(
            "SELECT COUNT(*) FROM cfc_messages WHERE turn_id = ?", (turn.id.value,)
        ).fetchone()[0]
        assert count == 2  # the user message and one assistant answer, not two
    finally:
        store.close()


def test_conflicting_finalisation_refuses_and_leaves_the_original_outcome(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c")
        turn, _ = store.start_turn(chat.id, "m", "q")
        original = store.complete_turn(turn.id, "first answer")

        with pytest.raises(store_mod.ConflictingFinalisation):
            store.complete_turn(turn.id, "a different answer")
        with pytest.raises(store_mod.ConflictingFinalisation):
            store.cancel_turn(turn.id)

        still = store.get_turn(turn.id)
        assert still.outcome == original.outcome
        assert store._stored_assistant_content(turn.id) == "first answer"
    finally:
        store.close()


def test_finalising_an_unknown_turn_refuses(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        with pytest.raises(store_mod.UnknownTurn):
            store.complete_turn(TurnId.new(), "answer")
    finally:
        store.close()


# --- persistence-exception rollback: never a partial answer -----------------

def test_final_write_failure_leaves_the_turn_recoverable(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c")
        turn, _ = store.start_turn(chat.id, "m", "q")

        store._conn = _FailOnce(store._conn, "UPDATE cfc_turns SET finished_at")
        with pytest.raises(sqlite3.OperationalError):
            store.complete_turn(turn.id, "answer")

        still_active = store.get_turn(turn.id)
        assert still_active.outcome is None
        assert still_active.finished_at is None
        assert store._stored_assistant_content(turn.id) is None

        finalised = store.complete_turn(turn.id, "answer")
        assert isinstance(finalised.outcome, CompletedOutcome)
    finally:
        store.close()


# --- explicit temporary targets only ----------------------------------------

def test_module_touches_no_config_or_legacy_path():
    import inspect
    source = inspect.getsource(store_mod)
    for banned in ("import config", "from config", "DB_PATH", "import db"):
        assert banned not in source
