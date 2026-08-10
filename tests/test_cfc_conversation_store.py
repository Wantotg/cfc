"""test_cfc_conversation_store.py — cfc/conversation_store.py: opening,
ownership, schema/version enforcement, and the repository operations the
conversation service needs. Every database lives under `tmp_path`; nothing
here imports `config.py`, touches a configured or legacy path, or reaches
the network.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from cfc import conversation_store as store_mod
from cfc.conversation_types import (
    CancelledOutcome,
    ChatId,
    CompletedOutcome,
    ContextCategory,
    ContextManifestEntry,
    FailedOutcome,
    FailureEvidence,
    FailureKind,
    OpeningMessage,
    ProviderProblem,
    Role,
    TimeoutPhase,
    TurnId,
    Usage,
    utc_now,
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
    chat = store.create_chat("first session", "fixture-model")
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


def _write_foreign_wal_sqlite(path: Path, application_id) -> None:
    """A foreign-application target left in WAL mode. Closing a connection
    that is the only one open on a WAL database checkpoints and removes its
    `-wal`/`-shm` sidecars, but the header's journal-mode bytes and pragmas
    remain correctly committed — this reproduces the steady-state WAL target
    B-2.0-34 is about, not a live writer's in-flight state.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA application_id = {application_id}")
        conn.execute("CREATE TABLE unrelated (x INTEGER)")
        conn.execute("INSERT INTO unrelated VALUES (1)")
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("build,expected_problem", [
    (lambda p: _write_bytes(p, b"not a sqlite database, just some bytes" * 4),
     store_mod.DatabaseProblem.CORRUPT),
    (lambda p: _write_foreign_sqlite(p, application_id=0x11111111, user_version=0),
     store_mod.DatabaseProblem.FOREIGN_APPLICATION),
    (lambda p: _write_foreign_sqlite(p, application_id=store_mod.APPLICATION_ID, user_version=0),
     store_mod.DatabaseProblem.SCHEMA_TOO_OLD),
    (lambda p: _write_foreign_sqlite(p, application_id=store_mod.APPLICATION_ID, user_version=99),
     store_mod.DatabaseProblem.SCHEMA_TOO_NEW),
], ids=["corrupt", "foreign-application", "schema-too-old", "schema-too-new"])
def test_incompatible_targets_refuse_without_mutation(tmp_path, build, expected_problem):
    """The empty target's own wording is D-2.0-42's differently-worded case,
    proved separately below — every other incompatible target still gets the
    shared move-or-remove recovery hint."""
    path = db_path(tmp_path)
    build(path)
    before = path.read_bytes()

    with pytest.raises(store_mod.DatabaseIncompatible) as exc_info:
        store_mod.open_store(path)

    assert exc_info.value.problem is expected_problem
    assert "move or remove" in exc_info.value.detail
    assert path.read_bytes() == before
    for suffix in (".lock", "-journal", "-wal", "-shm"):
        assert not (path.parent / (path.name + suffix)).exists()


# --- B-2.0-34: refusing a WAL-mode target grows no sidecars beside it ------

def test_a_foreign_wal_mode_target_refuses_without_growing_sidecars(tmp_path):
    path = db_path(tmp_path)
    _write_foreign_wal_sqlite(path, application_id=0x11111111)
    before = path.read_bytes()
    before_entries = sorted(p.name for p in path.parent.iterdir())

    with pytest.raises(store_mod.DatabaseIncompatible) as exc_info:
        store_mod.open_store(path)

    assert exc_info.value.problem is store_mod.DatabaseProblem.FOREIGN_APPLICATION
    assert path.read_bytes() == before
    assert sorted(p.name for p in path.parent.iterdir()) == before_entries


def test_a_wal_target_with_sidecars_already_present_keeps_them_untouched(tmp_path):
    """Sidecars another process legitimately owns are never deleted on
    refusal: 'do not delete them while another process may own the WAL.'
    """
    path = db_path(tmp_path)
    _write_foreign_wal_sqlite(path, application_id=0x11111111)
    wal_path = path.parent / (path.name + "-wal")
    shm_path = path.parent / (path.name + "-shm")
    wal_path.write_bytes(b"not really a wal file, just standing in for one")
    shm_path.write_bytes(b"stands in for a live -shm file")
    wal_before = wal_path.read_bytes()
    shm_before = shm_path.read_bytes()

    with pytest.raises(store_mod.DatabaseIncompatible):
        store_mod.open_store(path)

    assert wal_path.read_bytes() == wal_before
    assert shm_path.read_bytes() == shm_before


# --- B-2.0-27: a genuinely empty target differs from an unclaimed populated one --

def test_a_zero_page_target_is_called_empty(tmp_path):
    path = db_path(tmp_path)
    _write_bytes(path, b"")

    with pytest.raises(store_mod.DatabaseIncompatible) as exc_info:
        store_mod.open_store(path)

    assert exc_info.value.problem is store_mod.DatabaseProblem.EMPTY_OR_ARBITRARY


# --- D-2.0-42: a zero-byte target's own recovery wording ---------------

def test_an_empty_targets_wording_states_it_may_be_cfcs_own_leftover(tmp_path):
    """The truthful fact this wording adds over the generic recovery hint:
    cfc itself creates the zero-byte file before it finishes opening it, so
    an interrupted first start is a real, nameable explanation — not the
    only one, so cfc still does not act on it (below)."""
    path = db_path(tmp_path)
    _write_bytes(path, b"")

    with pytest.raises(store_mod.DatabaseIncompatible) as exc_info:
        store_mod.open_store(path)

    detail = exc_info.value.detail
    assert "interrupted first start" in detail
    assert "move" in detail and "aside or remove it and restart" in detail
    assert "preserve" in detail and "DATABASE_PATH" in detail


def test_an_empty_target_is_neither_adopted_nor_deleted_and_grows_no_sidecars(tmp_path):
    path = db_path(tmp_path)
    _write_bytes(path, b"")
    before = path.read_bytes()

    with pytest.raises(store_mod.DatabaseIncompatible):
        store_mod.open_store(path)

    assert path.exists()
    assert path.read_bytes() == before  # not adopted: still exactly the empty file it was
    for suffix in (".lock", "-journal", "-wal", "-shm"):
        assert not (path.parent / (path.name + suffix)).exists()

    # refuses identically on a second attempt — no automatic remediation happened
    with pytest.raises(store_mod.DatabaseIncompatible) as second:
        store_mod.open_store(path)
    assert second.value.problem is store_mod.DatabaseProblem.EMPTY_OR_ARBITRARY
    assert path.read_bytes() == before


def test_an_interrupted_first_start_leaves_exactly_the_empty_target_this_wording_describes(tmp_path):
    """Reproduces the real D-2.0-42 scenario: `_acquire_target_lock` creates
    the absent target with `O_CREAT | O_EXCL` before `_initialise_fresh` ever
    runs, so a process that dies in between leaves exactly a zero-byte file
    at the configured path — simulated directly here since killing the real
    process mid-open is not reproducible in-process. The *next* `open_store`
    call must meet exactly the wording proved above, not a generic message.
    """
    path = db_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o644)
    os.close(fd)
    assert path.stat().st_size == 0

    with pytest.raises(store_mod.DatabaseIncompatible) as exc_info:
        store_mod.open_store(path)

    assert exc_info.value.problem is store_mod.DatabaseProblem.EMPTY_OR_ARBITRARY
    assert "interrupted first start" in exc_info.value.detail


def test_a_markerless_populated_target_is_not_called_empty(tmp_path):
    path = db_path(tmp_path)
    _write_foreign_sqlite(path, application_id=None, user_version=0)
    before = path.read_bytes()

    with pytest.raises(store_mod.DatabaseIncompatible) as exc_info:
        store_mod.open_store(path)

    assert exc_info.value.problem is store_mod.DatabaseProblem.POPULATED_UNCLAIMED
    detail = exc_info.value.detail
    assert "may contain data from something other than cfc" in detail
    assert "move or remove" not in detail  # not told to delete someone else's data
    assert path.read_bytes() == before
    for suffix in ("-journal", "-wal", "-shm"):
        assert not (path.parent / (path.name + suffix)).exists()


def test_empty_and_populated_unclaimed_recovery_wording_differ(tmp_path):
    empty_path = db_path(tmp_path)
    _write_bytes(empty_path, b"")
    with pytest.raises(store_mod.DatabaseIncompatible) as empty_exc:
        store_mod.open_store(empty_path)

    populated_path = tmp_path / "other" / "chat.db"
    _write_foreign_sqlite(populated_path, application_id=None, user_version=0)
    with pytest.raises(store_mod.DatabaseIncompatible) as populated_exc:
        store_mod.open_store(populated_path)

    assert empty_exc.value.problem is not populated_exc.value.problem
    assert empty_exc.value.detail != populated_exc.value.detail


def test_a_schema_version_one_database_refuses_as_too_old(tmp_path):
    """A pre-2.0-loop database (schema version 1) must still take the
    existing visible refusal route under the current, higher SCHEMA_VERSION.
    """
    path = db_path(tmp_path)
    _write_foreign_sqlite(path, application_id=store_mod.APPLICATION_ID, user_version=1)
    before = path.read_bytes()

    with pytest.raises(store_mod.DatabaseIncompatible) as exc_info:
        store_mod.open_store(path)

    assert exc_info.value.problem is store_mod.DatabaseProblem.SCHEMA_TOO_OLD
    assert path.read_bytes() == before


def test_a_schema_version_two_database_refuses_as_too_old(tmp_path):
    """This loop bumps `SCHEMA_VERSION` from 2 to 3 (the named-context
    foundation: chat selections, one frozen opening per chat, and per-turn
    context provenance — no migration). A real database created by the
    prior build must take the existing visible refusal route, not be
    silently reinterpreted, `ALTER`ed, or have its sidecars touched.
    """
    path = db_path(tmp_path)
    _write_foreign_sqlite(path, application_id=store_mod.APPLICATION_ID, user_version=2)
    before = path.read_bytes()

    with pytest.raises(store_mod.DatabaseIncompatible) as exc_info:
        store_mod.open_store(path)

    assert exc_info.value.problem is store_mod.DatabaseProblem.SCHEMA_TOO_OLD
    assert path.read_bytes() == before
    for suffix in ("-journal", "-wal", "-shm"):
        assert not (path.parent / (path.name + suffix)).exists()


# --- a header-valid target still owes SQLite's own integrity check --------

def test_a_header_valid_current_database_with_a_corrupted_body_still_refuses(tmp_path):
    """The header alone proves the marker and version, never the page
    content: a legitimate cfc database whose body is corrupted after the
    header must still be caught by SQLite's own `quick_check`, not waved
    through because its header classified as current.
    """
    path = db_path(tmp_path)
    store_mod.open_store(path).close()
    size = path.stat().st_size
    assert size > store_mod._HEADER_SIZE

    # corrupt the back half of the file: the header (and its marker/version)
    # stays perfectly valid, but the page content it describes does not.
    with open(path, "r+b") as f:
        f.seek(size // 2)
        f.write(b"\xff" * (size - size // 2))

    with pytest.raises(store_mod.DatabaseIncompatible) as exc_info:
        store_mod.open_store(path)

    assert exc_info.value.problem is store_mod.DatabaseProblem.CORRUPT


def test_a_legitimate_current_database_reopens_cleanly(tmp_path):
    path = db_path(tmp_path)
    store_mod.open_store(path).close()
    reopened = store_mod.open_store(path)
    reopened.close()


# --- a stale sibling .lock is inert, not ownership evidence -----------------

def test_a_preexisting_stale_sibling_lock_file_is_inert(tmp_path):
    path = db_path(tmp_path)
    stale_lock = path.parent / (path.name + ".lock")
    stale_lock.parent.mkdir(parents=True, exist_ok=True)
    stale_lock.write_bytes(b"leftover from an earlier build")
    before = stale_lock.read_bytes()

    store = store_mod.open_store(path)
    store.close()

    assert stale_lock.read_bytes() == before  # neither read nor rewritten


# --- pathname revalidation: refuse rather than follow a replaced target ----

def test_a_disappeared_target_during_classification_is_refused(tmp_path, monkeypatch):
    path = db_path(tmp_path)
    store_mod.open_store(path).close()
    before = path.read_bytes()

    monkeypatch.setattr(store_mod, "_target_identity", lambda p: None)
    with pytest.raises(store_mod.TargetUnusable):
        store_mod.open_store(path)

    assert path.read_bytes() == before  # never touched, let alone reopened


def test_a_replaced_target_during_classification_is_refused_not_followed(tmp_path, monkeypatch):
    path = db_path(tmp_path)
    store_mod.open_store(path).close()
    before = path.read_bytes()

    monkeypatch.setattr(store_mod, "_target_identity", lambda p: (999999, 999999))
    with pytest.raises(store_mod.TargetUnusable):
        store_mod.open_store(path)

    assert path.read_bytes() == before


def test_a_pathname_swap_during_fresh_creation_is_refused_without_deleting_it(tmp_path, monkeypatch):
    """The empty file this invocation atomically claimed is left in place
    when ownership becomes uncertain — deleting `path` here could delete
    whatever now occupies that name instead of the file this call created.
    """
    path = db_path(tmp_path)
    assert not path.exists()

    monkeypatch.setattr(store_mod, "_target_identity", lambda p: None)
    with pytest.raises(store_mod.TargetUnusable):
        store_mod.open_store(path)

    assert path.exists()
    assert path.stat().st_size == 0


# --- B-2.0-41: a target cfc cannot open read-write is refused in its own
# --- vocabulary, not as a bare OSError -------------------------------------

#: Every permission check below is meaningless as root, which bypasses the
#: file mode entirely and would open all three targets successfully.
_needs_unprivileged = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="file permission bits do not restrict root",
)


@_needs_unprivileged
def test_an_unreadable_writable_foreign_target_is_refused_as_unusable(tmp_path):
    """Ownership is now the target's own descriptor, so classifying a
    foreign database needs to open it read-write. When the filesystem says
    no, that is still a refusal this module names — a caller catching
    `ConversationStoreError` must not have a bare `PermissionError` come
    past it — and the target is left exactly as it was.
    """
    path = db_path(tmp_path)
    _write_foreign_sqlite(path, application_id=0x11111111, user_version=0)
    before = path.read_bytes()
    path.chmod(0o444)

    with pytest.raises(store_mod.TargetUnusable) as exc_info:
        store_mod.open_store(path)

    assert "reading and writing" in exc_info.value.reason
    path.chmod(0o644)
    assert path.read_bytes() == before
    for suffix in (".lock", "-journal", "-wal", "-shm"):
        assert not (path.parent / (path.name + suffix)).exists()


@_needs_unprivileged
def test_a_read_only_current_cfc_database_is_refused_not_opened(tmp_path):
    """A cfc database restored without write permission — from a snapshot,
    or off a read-only mount — is this module's own file and classifies
    perfectly, but a store that cannot record a turn's ending is not a
    store. Refused, with the reason, before any connection exists.
    """
    path = db_path(tmp_path)
    store_mod.open_store(path).close()
    path.chmod(0o444)

    with pytest.raises(store_mod.TargetUnusable) as exc_info:
        store_mod.open_store(path)

    assert "reading and writing" in exc_info.value.reason


@_needs_unprivileged
def test_an_absent_target_in_an_unwritable_directory_is_refused_as_unusable(tmp_path):
    """The other half: nothing exists to open, and the directory will not
    accept the file cfc would create. `usable_target_reason` cannot see
    this — it never writes — so the create attempt is where it surfaces.
    """
    directory = tmp_path / "readonly"
    directory.mkdir()
    directory.chmod(0o555)
    path = directory / "chat.db"

    try:
        with pytest.raises(store_mod.TargetUnusable) as exc_info:
            store_mod.open_store(path)
        assert "could not create" in exc_info.value.reason
        assert not path.exists()
    finally:
        directory.chmod(0o755)


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
    chat = store.create_chat("t", "fixture-model")
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
    chat = store.create_chat("t", "fixture-model")
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
        chat = store.create_chat("c", "fixture-model")
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
        chat = store.create_chat("c", "fixture-model")
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
        chat = store.create_chat("c", "fixture-model")
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
    chat = store.create_chat("round trip", "fixture-model")
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


def test_snapshot_carries_ordered_turns_alongside_messages(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        turn1, _ = store.start_turn(chat.id, "m1", "q1")
        store.complete_turn(turn1.id, "a1")
        turn2, _ = store.start_turn(chat.id, "m2", "q2")
        store.fail_turn(turn2.id, FailureEvidence(FailureKind.RESPONDER, "declined"))
        turn3, _ = store.start_turn(chat.id, "m3", "q3")  # left active

        snapshot = store.snapshot(chat.id)
        assert [t.id for t in snapshot.turns] == [turn1.id, turn2.id, turn3.id]
        assert isinstance(snapshot.turns[0].outcome, CompletedOutcome)
        assert isinstance(snapshot.turns[1].outcome, FailedOutcome)
        assert snapshot.turns[2].outcome is None
    finally:
        store.close()


def test_provider_wire_failure_detail_round_trips_through_a_new_connection(tmp_path):
    path = db_path(tmp_path)
    store = store_mod.open_store(path)
    chat = store.create_chat("c", "fixture-model")

    timeout_turn, _ = store.start_turn(chat.id, "m", "q1")
    store.fail_turn(timeout_turn.id, FailureEvidence(
        FailureKind.RESPONDER, "read timed out",
        problem=ProviderProblem.TIMEOUT, timeout_phase=TimeoutPhase.READ,
    ))

    http_turn, _ = store.start_turn(chat.id, "m", "q2")
    store.fail_turn(http_turn.id, FailureEvidence(
        FailureKind.RESPONDER, "provider refused",
        problem=ProviderProblem.HTTP_STATUS, status_code=429,
    ))

    connection_turn, _ = store.start_turn(chat.id, "m", "q3")
    store.fail_turn(connection_turn.id, FailureEvidence(
        FailureKind.RESPONDER, "connection refused", problem=ProviderProblem.CONNECTION,
    ))

    internal_turn, _ = store.start_turn(chat.id, "m", "q4")
    store.fail_turn(internal_turn.id, FailureEvidence(FailureKind.INTERNAL, "boom"))
    store.close()

    reopened = store_mod.open_store(path)
    try:
        timeout_evidence = reopened.get_turn(timeout_turn.id).outcome.evidence
        assert timeout_evidence.problem is ProviderProblem.TIMEOUT
        assert timeout_evidence.timeout_phase is TimeoutPhase.READ
        assert timeout_evidence.status_code is None

        http_evidence = reopened.get_turn(http_turn.id).outcome.evidence
        assert http_evidence.problem is ProviderProblem.HTTP_STATUS
        assert http_evidence.status_code == 429
        assert http_evidence.timeout_phase is None

        connection_evidence = reopened.get_turn(connection_turn.id).outcome.evidence
        assert connection_evidence.problem is ProviderProblem.CONNECTION
        assert connection_evidence.timeout_phase is None
        assert connection_evidence.status_code is None

        internal_evidence = reopened.get_turn(internal_turn.id).outcome.evidence
        assert internal_evidence.problem is None
        assert internal_evidence.timeout_phase is None
        assert internal_evidence.status_code is None
    finally:
        reopened.close()


def test_failed_and_cancelled_turns_remain_distinct_and_carry_no_assistant_row(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")

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
        chat = store.create_chat("c", "fixture-model")
        turn, _ = store.start_turn(chat.id, "m", "q1")
        finalize(store, turn.id)
        turn2, _ = store.start_turn(chat.id, "m", "q2")
        assert turn2.position == turn.position + 1
        assert turn2.outcome is None
    finally:
        store.close()


# --- D-2.0-36: one active turn per chat, refused atomically -----------------

def test_starting_a_second_turn_in_the_same_chat_before_the_first_ends_refuses(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        first, _ = store.start_turn(chat.id, "m", "q1")

        with pytest.raises(store_mod.ActiveTurnExists) as exc_info:
            store.start_turn(chat.id, "m", "q2")

        assert exc_info.value.chat_id == chat.id
        assert exc_info.value.active_turn_id == first.id
        # refused before any write: no second turn or message row exists
        turn_count = store._conn.execute(
            "SELECT COUNT(*) FROM cfc_turns WHERE chat_id = ?", (chat.id.value,)
        ).fetchone()[0]
        message_count = store._conn.execute(
            "SELECT COUNT(*) FROM cfc_messages WHERE chat_id = ?", (chat.id.value,)
        ).fetchone()[0]
        assert turn_count == 1
        assert message_count == 1
    finally:
        store.close()


def test_a_terminal_turn_no_longer_blocks_starting_another(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        turn, _ = store.start_turn(chat.id, "m", "q1")
        store.cancel_turn(turn.id)

        second, _ = store.start_turn(chat.id, "m", "q2")
        assert second.position == turn.position + 1
    finally:
        store.close()


def test_different_chats_may_each_have_one_independent_active_turn(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat_a = store.create_chat("a", "fixture-model")
        chat_b = store.create_chat("b", "fixture-model")
        turn_a, _ = store.start_turn(chat_a.id, "m", "qa")
        turn_b, _ = store.start_turn(chat_b.id, "m", "qb")
        assert turn_a.chat_id == chat_a.id
        assert turn_b.chat_id == chat_b.id
    finally:
        store.close()


# --- finalisation: repeated observes, conflicting refuses -------------------

def test_repeated_identical_finalisation_is_idempotent(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
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
        chat = store.create_chat("c", "fixture-model")
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
        chat = store.create_chat("c", "fixture-model")
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


# --- context selection: persisted, contained per chat -----------------------

def manifest(*, persona="muse.md") -> tuple[ContextManifestEntry, ...]:
    return (
        ContextManifestEntry(category=ContextCategory.SYSTEM_INSTRUCTIONS,
                              name="cfc-system-instructions-v1", order=0,
                              character_count=42, fingerprint="sysfp"),
        ContextManifestEntry(category=ContextCategory.PERSONA, name=persona, order=1,
                              character_count=12, fingerprint="personafp"),
    )


def test_create_chat_stores_the_initial_model_and_no_other_selection(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        assert chat.context_selection.model == "fixture-model"
        assert chat.context_selection.user_preferences is None
        assert chat.context_selection.persona is None
        assert chat.context_selection.traits == ()
        assert chat.opening is None
    finally:
        store.close()


def test_set_user_preferences_persists_and_returns_the_updated_chat(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        updated = store.set_user_preferences(chat.id, "prefs.md")
        assert updated.context_selection.user_preferences == "prefs.md"
        assert store.get_chat(chat.id).context_selection.user_preferences == "prefs.md"

        cleared = store.set_user_preferences(chat.id, None)
        assert cleared.context_selection.user_preferences is None
    finally:
        store.close()


def test_set_persona_without_opening_leaves_opening_absent(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        updated = store.set_persona(chat.id, "muse.md")
        assert updated.context_selection.persona == "muse.md"
        assert updated.opening is None
    finally:
        store.close()


def test_set_persona_with_opening_freezes_it_atomically(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        opening = OpeningMessage(source_name="muse.md", content="Hello, I am Muse.",
                                  created_at=utc_now(), fingerprint="fp1")
        updated = store.set_persona(chat.id, "muse.md", opening=opening)
        assert updated.context_selection.persona == "muse.md"
        assert updated.opening == opening
        assert store.get_chat(chat.id).opening == opening
    finally:
        store.close()


def test_set_persona_after_a_turn_never_adds_an_opening_retroactively(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        turn, _ = store.start_turn(chat.id, "m", "hello")
        store.complete_turn(turn.id, "hi there")  # a turn now exists and has finished

        late_opening = OpeningMessage(source_name="muse.md", content="too late",
                                       created_at=utc_now(), fingerprint="fp2")
        updated = store.set_persona(chat.id, "muse.md", opening=late_opening)
        assert updated.context_selection.persona == "muse.md"
        assert updated.opening is None
    finally:
        store.close()


def test_an_existing_opening_is_never_rewritten_by_a_later_persona_change(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        first_opening = OpeningMessage(source_name="muse.md", content="original",
                                        created_at=utc_now(), fingerprint="fp-original")
        store.set_persona(chat.id, "muse.md", opening=first_opening)

        replacement_opening = OpeningMessage(source_name="sage.md", content="replacement",
                                              created_at=utc_now(), fingerprint="fp-replacement")
        updated = store.set_persona(chat.id, "sage.md", opening=replacement_opening)
        assert updated.context_selection.persona == "sage.md"  # selection did change
        assert updated.opening == first_opening  # opening did not
    finally:
        store.close()


def test_traits_preserve_add_order_and_are_independently_removable(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        store.add_trait(chat.id, "dry.md")
        store.add_trait(chat.id, "warm.md")
        updated = store.add_trait(chat.id, "curious.md")
        assert updated.context_selection.traits == ("dry.md", "warm.md", "curious.md")

        after_remove = store.remove_trait(chat.id, "warm.md")
        assert after_remove.context_selection.traits == ("dry.md", "curious.md")
    finally:
        store.close()


def test_re_adding_an_already_selected_trait_is_idempotent(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        store.add_trait(chat.id, "dry.md")
        updated = store.add_trait(chat.id, "dry.md")
        assert updated.context_selection.traits == ("dry.md",)
    finally:
        store.close()


def test_set_model_updates_the_chats_default_model(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        updated = store.set_model(chat.id, "other-model")
        assert updated.context_selection.model == "other-model"
    finally:
        store.close()


@pytest.mark.parametrize("mutator_name,args", [
    ("set_user_preferences", ("prefs.md",)),
    ("set_persona", ("muse.md",)),
    ("add_trait", ("dry.md",)),
    ("remove_trait", ("dry.md",)),
    ("set_model", ("other-model",)),
])
def test_selection_changes_refuse_while_a_turn_is_active(tmp_path, mutator_name, args):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        store.start_turn(chat.id, "m", "hello")
        mutator = getattr(store, mutator_name)
        with pytest.raises(store_mod.ActiveTurnExists):
            mutator(chat.id, *args)
    finally:
        store.close()


def test_selection_changes_on_an_unknown_chat_raise_unknown_chat(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        with pytest.raises(store_mod.UnknownChat):
            store.set_model(ChatId.new(), "other-model")
    finally:
        store.close()


# --- per-turn context manifest: ordered, no vault body, all-or-nothing -----

def test_start_turn_persists_and_returns_the_context_manifest(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        entries = manifest()
        turn, _ = store.start_turn(chat.id, "m", "hi", context_manifest=entries)
        assert turn.context_manifest == entries

        reread = store.get_turn(turn.id)
        assert reread.context_manifest == entries
    finally:
        store.close()


def test_context_manifest_never_stores_a_source_body(tmp_path):
    path = db_path(tmp_path)
    store = store_mod.open_store(path)
    chat = store.create_chat("c", "fixture-model")
    store.start_turn(chat.id, "m", "hi", context_manifest=manifest())

    raw = sqlite3.connect(str(path))
    try:
        columns = [row[1] for row in raw.execute("PRAGMA table_info(cfc_turn_context)")]
        assert "body" not in columns
        row = raw.execute(
            "SELECT category, name, character_count, fingerprint FROM cfc_turn_context "
            "ORDER BY position ASC"
        ).fetchall()
        assert row[1] == ("persona", "muse.md", 12, "personafp")
    finally:
        raw.close()
        store.close()


def test_context_manifest_is_scoped_to_its_own_turn(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        turn1, _ = store.start_turn(chat.id, "m", "q1", context_manifest=manifest(persona="a.md"))
        store.complete_turn(turn1.id, "a1")
        turn2, _ = store.start_turn(chat.id, "m", "q2", context_manifest=manifest(persona="b.md"))

        assert store.get_turn(turn1.id).context_manifest[1].name == "a.md"
        assert store.get_turn(turn2.id).context_manifest[1].name == "b.md"
    finally:
        store.close()


def test_starting_a_turn_is_all_or_nothing_on_a_late_failure(tmp_path):
    """The manifest insert happens inside `start_turn`'s own transaction —
    a failure there must leave no turn, no user message, and no partial
    manifest row behind, the same all-or-nothing guarantee `start_turn`
    already gave its turn+message insert.
    """
    store = store_mod.open_store(db_path(tmp_path))
    try:
        chat = store.create_chat("c", "fixture-model")
        store._conn = _FailOnce(store._conn, "INSERT INTO cfc_turn_context")
        with pytest.raises(sqlite3.OperationalError):
            store.start_turn(chat.id, "m", "hi", context_manifest=manifest())

        snapshot = store.snapshot(chat.id)
        assert snapshot.turns == ()
        assert snapshot.messages == ()
    finally:
        store.close()


# --- two chats, distinct selections, round trip through a reopened store ---

def test_two_chats_round_trip_distinct_selections_opening_and_manifests(tmp_path):
    path = db_path(tmp_path)
    store = store_mod.open_store(path)

    chat_a = store.create_chat("chat a", "model-a")
    store.set_user_preferences(chat_a.id, "prefs-a.md")
    opening_a = OpeningMessage(source_name="muse.md", content="Hello from A",
                                created_at=utc_now(), fingerprint="fp-a")
    store.set_persona(chat_a.id, "muse.md", opening=opening_a)
    store.add_trait(chat_a.id, "dry.md")
    store.add_trait(chat_a.id, "warm.md")
    turn_a, _ = store.start_turn(chat_a.id, "model-a", "hi from a",
                                  context_manifest=manifest(persona="muse.md"))

    chat_b = store.create_chat("chat b", "model-b")
    store.set_persona(chat_b.id, "sage.md")  # no opening companion for sage
    store.add_trait(chat_b.id, "warm.md")
    store.add_trait(chat_b.id, "dry.md")  # reverse order from chat a
    turn_b, _ = store.start_turn(chat_b.id, "model-b", "hi from b",
                                  context_manifest=manifest(persona="sage.md"))
    store.close()

    reopened = store_mod.open_store(path)
    try:
        got_a = reopened.get_chat(chat_a.id)
        assert got_a.context_selection.user_preferences == "prefs-a.md"
        assert got_a.context_selection.persona == "muse.md"
        assert got_a.context_selection.traits == ("dry.md", "warm.md")
        assert got_a.context_selection.model == "model-a"
        assert got_a.opening == opening_a

        got_b = reopened.get_chat(chat_b.id)
        assert got_b.context_selection.user_preferences is None
        assert got_b.context_selection.persona == "sage.md"
        assert got_b.context_selection.traits == ("warm.md", "dry.md")
        assert got_b.context_selection.model == "model-b"
        assert got_b.opening is None

        assert reopened.get_turn(turn_a.id).context_manifest[1].name == "muse.md"
        assert reopened.get_turn(turn_b.id).context_manifest[1].name == "sage.md"
    finally:
        reopened.close()


# --- appearance: the one durable singleton override (Stage 5 loop 2) -------

def test_a_fresh_database_has_no_appearance_override(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        assert store.get_appearance_override() is None
    finally:
        store.close()


def test_save_appearance_override_round_trips_through_a_new_connection(tmp_path):
    path = db_path(tmp_path)
    store = store_mod.open_store(path)
    store.save_appearance_override("light")
    store.close()

    reopened = store_mod.open_store(path)
    try:
        assert reopened.get_appearance_override() == "light"
    finally:
        reopened.close()


def test_save_appearance_override_replaces_a_previous_choice(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        store.save_appearance_override("dark")
        store.save_appearance_override("light")
        assert store.get_appearance_override() == "light"
    finally:
        store.close()


def test_clear_appearance_override_returns_to_absent_and_round_trips(tmp_path):
    path = db_path(tmp_path)
    store = store_mod.open_store(path)
    store.save_appearance_override("dark")
    store.clear_appearance_override()
    store.close()

    reopened = store_mod.open_store(path)
    try:
        assert reopened.get_appearance_override() is None
    finally:
        reopened.close()


def test_save_appearance_override_rejects_an_out_of_vocabulary_value(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        with pytest.raises(ValueError):
            store.save_appearance_override("purple")
        assert store.get_appearance_override() is None
    finally:
        store.close()


def test_get_appearance_override_rejects_an_impossible_stored_value(tmp_path):
    """The schema's own `CHECK` constraint makes this unreachable through
    this module's own writes; simulating it directly (bypassing the CHECK
    on this live connection, the same way a hand-edited file could) proves
    the read path validates independently rather than trusting the schema
    alone."""
    store = store_mod.open_store(db_path(tmp_path))
    try:
        store._conn.execute("PRAGMA ignore_check_constraints=1")
        store._conn.execute("UPDATE cfc_appearance SET override = 'purple' WHERE id = 1")
        store._conn.commit()
        with pytest.raises(store_mod.AppearanceOverrideInvalid) as exc_info:
            store.get_appearance_override()
        assert exc_info.value.value == "purple"
    finally:
        store._conn.execute("PRAGMA ignore_check_constraints=1")
        store._conn.execute("UPDATE cfc_appearance SET override = NULL WHERE id = 1")
        store._conn.commit()
        store.close()


def test_appearance_save_failure_does_not_report_a_changed_value(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        store.save_appearance_override("dark")
        store._conn = _FailOnce(store._conn, "INSERT INTO cfc_appearance")
        with pytest.raises(sqlite3.OperationalError):
            store.save_appearance_override("light")
        assert store.get_appearance_override() == "dark"
    finally:
        store.close()


def test_appearance_clear_failure_does_not_report_a_changed_value(tmp_path):
    store = store_mod.open_store(db_path(tmp_path))
    try:
        store.save_appearance_override("light")
        store._conn = _FailOnce(store._conn, "INSERT INTO cfc_appearance")
        with pytest.raises(sqlite3.OperationalError):
            store.clear_appearance_override()
        assert store.get_appearance_override() == "light"
    finally:
        store.close()


# --- appearance: schema bump refuses the loop-one (version 3) schema -------

def test_a_schema_version_three_database_refuses_as_too_old(tmp_path):
    """This loop bumps `SCHEMA_VERSION` from 3 to 4 (`cfc_appearance`, the
    one durable appearance override). A real loop-one database must take
    the existing visible refusal route, not be silently reinterpreted,
    `ALTER`ed, or have its sidecars touched.
    """
    path = db_path(tmp_path)
    _write_foreign_sqlite(path, application_id=store_mod.APPLICATION_ID, user_version=3)
    before = path.read_bytes()

    with pytest.raises(store_mod.DatabaseIncompatible) as exc_info:
        store_mod.open_store(path)

    assert exc_info.value.problem is store_mod.DatabaseProblem.SCHEMA_TOO_OLD
    assert path.read_bytes() == before
    for suffix in ("-journal", "-wal", "-shm"):
        assert not (path.parent / (path.name + suffix)).exists()


# --- inspect_appearance_override: read-only, never creates or blocks -------

def test_inspect_appearance_override_absent_target_creates_nothing(tmp_path):
    path = db_path(tmp_path)
    inspection = store_mod.inspect_appearance_override(path)
    assert inspection.state is store_mod.AppearanceInspectionState.ABSENT
    assert not path.exists()
    assert not path.parent.exists()


def test_inspect_appearance_override_reports_no_saved_override(tmp_path):
    path = db_path(tmp_path)
    store_mod.open_store(path).close()
    inspection = store_mod.inspect_appearance_override(path)
    assert inspection.state is store_mod.AppearanceInspectionState.READY
    assert inspection.override is None


def test_inspect_appearance_override_reports_a_saved_override(tmp_path):
    path = db_path(tmp_path)
    store = store_mod.open_store(path)
    store.save_appearance_override("light")
    store.close()

    inspection = store_mod.inspect_appearance_override(path)
    assert inspection.state is store_mod.AppearanceInspectionState.READY
    assert inspection.override == "light"


def test_inspect_appearance_override_locked_while_another_owner_holds_it(tmp_path):
    path = db_path(tmp_path)
    owner = store_mod.open_store(path)
    try:
        inspection = store_mod.inspect_appearance_override(path)
        assert inspection.state is store_mod.AppearanceInspectionState.LOCKED
    finally:
        owner.close()

    # released the instant the owner closes — not a stale-file heuristic
    inspection_after = store_mod.inspect_appearance_override(path)
    assert inspection_after.state is store_mod.AppearanceInspectionState.READY


def test_inspect_appearance_override_foreign_database_is_incompatible(tmp_path):
    path = db_path(tmp_path)
    _write_foreign_sqlite(path, application_id=0x11111111, user_version=0)
    inspection = store_mod.inspect_appearance_override(path)
    assert inspection.state is store_mod.AppearanceInspectionState.INCOMPATIBLE
    assert inspection.problem is store_mod.DatabaseProblem.FOREIGN_APPLICATION
    assert inspection.override is None


def test_inspect_appearance_override_corrupt_database_is_incompatible(tmp_path):
    path = db_path(tmp_path)
    _write_bytes(path, b"not a sqlite database, just some bytes" * 4)
    inspection = store_mod.inspect_appearance_override(path)
    assert inspection.state is store_mod.AppearanceInspectionState.INCOMPATIBLE
    assert inspection.problem is store_mod.DatabaseProblem.CORRUPT


def test_inspect_appearance_override_old_schema_is_incompatible(tmp_path):
    path = db_path(tmp_path)
    _write_foreign_sqlite(path, application_id=store_mod.APPLICATION_ID, user_version=3)
    inspection = store_mod.inspect_appearance_override(path)
    assert inspection.state is store_mod.AppearanceInspectionState.INCOMPATIBLE
    assert inspection.problem is store_mod.DatabaseProblem.SCHEMA_TOO_OLD


def test_inspect_appearance_override_never_creates_a_target_or_sidecars(tmp_path):
    path = db_path(tmp_path)
    store_mod.open_store(path).close()
    before_entries = sorted(p.name for p in path.parent.iterdir())

    store_mod.inspect_appearance_override(path)

    assert sorted(p.name for p in path.parent.iterdir()) == before_entries


def test_inspect_appearance_override_on_a_directory_target_is_incompatible(tmp_path):
    path = tmp_path / "adir"
    path.mkdir()
    inspection = store_mod.inspect_appearance_override(path)
    assert inspection.state is store_mod.AppearanceInspectionState.INCOMPATIBLE


# --- explicit temporary targets only ----------------------------------------

def test_module_touches_no_config_or_legacy_path():
    import inspect
    source = inspect.getsource(store_mod)
    for banned in ("import config", "from config", "DB_PATH", "import db"):
        assert banned not in source
