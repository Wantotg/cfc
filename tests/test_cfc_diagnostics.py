"""test_cfc_diagnostics.py — cfc/diagnostics.py: the seven-row inventory
doctor renders, and required_rows_ok's exit-code decision.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cfc import diagnostics

VALID_BODY = (
    "API_BASE = 'https://provider.invalid/v1'\n"
    "API_KEY = 'fixture-key'\n"
    "MODEL = 'fixture-model'\n"
)


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.py"
    path.write_text(body, encoding="utf-8")
    return path


def by_name(rows, name):
    return next(r for r in rows if r.name == name)


# --- row order is stable -----------------------------------------------------

def test_row_order_matches_row_order_constant(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    rows = diagnostics.diagnose(path)
    assert tuple(r.name for r in rows) == diagnostics.ROW_ORDER


# --- the minimal valid config: everything required is ready -----------------

def test_minimal_valid_config_is_ready_and_ok(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    rows = diagnostics.diagnose(path)
    for name in diagnostics.REQUIRED_ROW_NAMES:
        assert by_name(rows, name).state == diagnostics.State.READY, name
    assert diagnostics.required_rows_ok(rows) is True


def test_unset_optional_settings_are_unavailable_not_error(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "vault").state == diagnostics.State.UNAVAILABLE
    assert by_name(rows, "embeddings").state == diagnostics.State.UNAVAILABLE
    assert by_name(rows, "file tools").state == diagnostics.State.UNAVAILABLE
    assert diagnostics.required_rows_ok(rows) is True


# --- required-field failure -> error, non-ok, cascades sensibly -------------

def test_missing_required_field_is_error_and_not_ok(tmp_path):
    path = write_config(tmp_path, "API_BASE = 'https://provider.invalid/v1'\nMODEL='m'\n")
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "chat provider").state == diagnostics.State.ERROR
    assert diagnostics.required_rows_ok(rows) is False


def test_missing_config_file_cascades_to_every_row_but_runtime(tmp_path):
    path = tmp_path / "does_not_exist.py"
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "runtime").state == diagnostics.State.READY
    assert by_name(rows, "configuration").state == diagnostics.State.ERROR
    for name in diagnostics.REQUIRED_ROW_NAMES[2:] + diagnostics.OPTIONAL_ROW_NAMES:
        assert by_name(rows, name).state == diagnostics.State.ERROR, name
    assert diagnostics.required_rows_ok(rows) is False


# --- vault: not configured / locally invalid / ready -------------------------

def test_vault_not_configured(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "vault").state == diagnostics.State.UNAVAILABLE


def test_vault_placeholder_counts_as_not_configured(tmp_path):
    path = write_config(tmp_path, VALID_BODY + "CHAT_EXPORT_DIR = 'PLACEHOLDER'\n")
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "vault").state == diagnostics.State.UNAVAILABLE


def test_vault_ready_when_directory_exists(tmp_path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    path = write_config(tmp_path, VALID_BODY + f"CHAT_EXPORT_DIR = {str(vault_dir)!r}\n")
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "vault").state == diagnostics.State.READY


def test_vault_ready_when_directory_does_not_exist_yet_but_parent_does(tmp_path):
    vault_dir = tmp_path / "not_yet_created"
    path = write_config(tmp_path, VALID_BODY + f"CHAT_EXPORT_DIR = {str(vault_dir)!r}\n")
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "vault").state == diagnostics.State.READY
    assert not vault_dir.exists()


def test_vault_error_when_blocked_by_a_file(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    vault_dir = blocker / "vault"
    path = write_config(tmp_path, VALID_BODY + f"CHAT_EXPORT_DIR = {str(vault_dir)!r}\n")
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "vault").state == diagnostics.State.ERROR


def test_vault_legacy_name_is_honoured(tmp_path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    path = write_config(tmp_path, VALID_BODY + f"VAULT_PATH = {str(vault_dir)!r}\n")
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "vault").state == diagnostics.State.READY


# --- embeddings: not configured / locally invalid / ready -------------------

def test_embeddings_not_configured(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "embeddings").state == diagnostics.State.UNAVAILABLE


def test_embeddings_ready(tmp_path):
    path = write_config(
        tmp_path,
        VALID_BODY + "EMBED_BASE = 'https://embed.invalid/v1'\n"
                      "EMBED_MODEL = 'embed-model'\n"
                      "EMBED_KEY = 'embed-key'\n",
    )
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "embeddings").state == diagnostics.State.READY


@pytest.mark.parametrize("missing", ["EMBED_MODEL", "EMBED_KEY"])
def test_embeddings_invalid_when_base_set_but_a_field_missing(tmp_path, missing):
    fields = {
        "EMBED_BASE": "'https://embed.invalid/v1'",
        "EMBED_MODEL": "'embed-model'",
        "EMBED_KEY": "'embed-key'",
    }
    del fields[missing]
    body = VALID_BODY + "\n".join(f"{k} = {v}" for k, v in fields.items()) + "\n"
    path = write_config(tmp_path, body)
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "embeddings").state == diagnostics.State.ERROR


def test_embeddings_invalid_url(tmp_path):
    path = write_config(
        tmp_path,
        VALID_BODY + "EMBED_BASE = 'not-a-url'\n"
                      "EMBED_MODEL = 'embed-model'\n"
                      "EMBED_KEY = 'embed-key'\n",
    )
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "embeddings").state == diagnostics.State.ERROR


# --- file tools: not configured / not built ----------------------------------

def test_file_tools_not_configured_when_disabled(tmp_path):
    path = write_config(tmp_path, VALID_BODY + "TOOLS_ENABLED = False\n")
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "file tools").state == diagnostics.State.UNAVAILABLE


def test_file_tools_not_built_when_enabled(tmp_path):
    path = write_config(tmp_path, VALID_BODY + "TOOLS_ENABLED = True\n")
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "file tools").state == diagnostics.State.NOT_BUILT


# --- secret markers never leak into any row's detail -------------------------

def test_no_row_ever_shows_the_api_key_or_embed_key(tmp_path):
    api_marker = "SECRET-MARKER-DO-NOT-LEAK-api-77e1"
    embed_marker = "SECRET-MARKER-DO-NOT-LEAK-embed-c402"
    path = write_config(
        tmp_path,
        "API_BASE = 'https://provider.invalid/v1'\n"
        f"API_KEY = {api_marker!r}\n"
        "MODEL = 'fixture-model'\n"
        "EMBED_BASE = 'https://embed.invalid/v1'\n"
        "EMBED_MODEL = 'embed-model'\n"
        f"EMBED_KEY = {embed_marker!r}\n",
    )
    rows = diagnostics.diagnose(path)
    for row in rows:
        assert api_marker not in row.detail
        assert embed_marker not in row.detail
        assert api_marker not in repr(row)
        assert embed_marker not in repr(row)


# --- no filesystem mutation, across every row --------------------------------

def test_diagnose_creates_nothing_on_disk(tmp_path):
    vault_dir = tmp_path / "vault_not_yet_created"
    db_dir = tmp_path / "db_not_yet_created"
    path = write_config(
        tmp_path,
        VALID_BODY
        + f"CHAT_EXPORT_DIR = {str(vault_dir)!r}\n"
        + f"DB_PATH = {str(db_dir / 'chat.db')!r}\n"
        + "TOOLS_ENABLED = True\n",
    )
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    diagnostics.diagnose(path)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after
    assert not vault_dir.exists()
    assert not db_dir.exists()
