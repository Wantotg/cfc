"""test_cfc_settings.py — cfc/settings.py: the required bootstrap fields
(chat provider, 2.0 database target) built from a config snapshot.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cfc import config_loader, settings


def snapshot_from(tmp_path: Path, body: str, name: str = "config.py"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return config_loader.load_snapshot(path)


VALID_BODY = (
    "API_BASE = 'https://provider.invalid/v1'\n"
    "API_KEY = 'fixture-key'\n"
    "MODEL = 'fixture-model'\n"
)


# --- provider: required, missing/type/value distinctions --------------------

def test_valid_provider_builds(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY)
    provider = settings.build_provider(snapshot)
    assert provider.api_base == "https://provider.invalid/v1"
    assert provider.api_key == "fixture-key"
    assert provider.model == "fixture-model"


@pytest.mark.parametrize("field_name", ["API_BASE", "API_KEY", "MODEL"])
def test_missing_required_field_is_reported_as_missing(tmp_path, field_name):
    lines = [ln for ln in VALID_BODY.splitlines() if not ln.startswith(field_name)]
    snapshot = snapshot_from(tmp_path, "\n".join(lines) + "\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_provider(snapshot)
    assert exc_info.value.field_name == field_name
    assert exc_info.value.kind == "missing"


@pytest.mark.parametrize("field_name", ["API_BASE", "API_KEY", "MODEL"])
def test_wrong_type_required_field_is_reported_as_type(tmp_path, field_name):
    lines = [ln for ln in VALID_BODY.splitlines() if not ln.startswith(field_name)]
    lines.append(f"{field_name} = 5")
    snapshot = snapshot_from(tmp_path, "\n".join(lines) + "\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_provider(snapshot)
    assert exc_info.value.field_name == field_name
    assert exc_info.value.kind == "type"


@pytest.mark.parametrize("field_name", ["API_BASE", "API_KEY", "MODEL"])
def test_empty_required_field_is_reported_as_value(tmp_path, field_name):
    lines = [ln for ln in VALID_BODY.splitlines() if not ln.startswith(field_name)]
    lines.append(f"{field_name} = '   '")
    snapshot = snapshot_from(tmp_path, "\n".join(lines) + "\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_provider(snapshot)
    assert exc_info.value.field_name == field_name
    assert exc_info.value.kind == "value"


@pytest.mark.parametrize("bad_url", [
    "not-a-url", "ftp://provider.invalid/v1", "//provider.invalid/v1", "https://",
])
def test_api_base_url_shape_is_validated(tmp_path, bad_url):
    lines = [ln for ln in VALID_BODY.splitlines() if not ln.startswith("API_BASE")]
    lines.append(f"API_BASE = {bad_url!r}")
    snapshot = snapshot_from(tmp_path, "\n".join(lines) + "\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_provider(snapshot)
    assert exc_info.value.field_name == "API_BASE"
    assert exc_info.value.kind == "value"


def test_provider_repr_never_shows_the_key(tmp_path):
    marker = "SECRET-MARKER-DO-NOT-LEAK-b71c"
    lines = [ln for ln in VALID_BODY.splitlines() if not ln.startswith("API_KEY")]
    lines.append(f"API_KEY = {marker!r}")
    snapshot = snapshot_from(tmp_path, "\n".join(lines) + "\n")
    provider = settings.build_provider(snapshot)
    assert provider.api_key == marker
    assert marker not in repr(provider)
    assert marker not in str(provider)


# --- database target: default, override, protected targets ------------------

def test_unset_db_path_uses_the_2_0_default(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY)
    resolved = settings.build_database_path(snapshot)
    assert resolved == settings.DEFAULT_DATABASE_PATH.expanduser().resolve()


def test_blank_db_path_uses_the_2_0_default(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "DB_PATH = '   '\n")
    resolved = settings.build_database_path(snapshot)
    assert resolved == settings.DEFAULT_DATABASE_PATH.expanduser().resolve()


def test_db_path_override_is_expanded_and_resolved(tmp_path):
    target = tmp_path / "nested" / "chat.db"
    target.parent.mkdir()
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DB_PATH = {str(target)!r}\n")
    resolved = settings.build_database_path(snapshot)
    assert resolved == target.resolve()


def test_db_path_accepts_a_nonexistent_file_with_a_usable_parent(tmp_path):
    parent = tmp_path / "usable"
    parent.mkdir()
    target = parent / "chat.db"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DB_PATH = {str(target)!r}\n")
    resolved = settings.build_database_path(snapshot)
    assert resolved == target.resolve()
    assert not target.exists()


def test_db_path_accepts_several_missing_levels_above_an_existing_root(tmp_path):
    """Only the *nearest existing* ancestor has to look usable — the work
    order is explicit that intermediate missing levels are accepted, not a
    reason to refuse.
    """
    target = tmp_path / "does" / "not" / "exist" / "chat.db"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DB_PATH = {str(target)!r}\n")
    resolved = settings.build_database_path(snapshot)
    assert resolved == target.resolve()
    assert not target.parent.exists()


def test_db_path_rejects_an_ancestor_blocked_by_a_file(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    target = blocker / "chat.db"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DB_PATH = {str(target)!r}\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_database_path(snapshot)
    assert exc_info.value.field_name == "DB_PATH"
    assert exc_info.value.kind == "value"


def test_db_path_rejects_a_directory_target(tmp_path):
    target = tmp_path / "a_directory"
    target.mkdir()
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DB_PATH = {str(target)!r}\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_database_path(snapshot)
    assert exc_info.value.field_name == "DB_PATH"


def test_db_path_rejects_the_legacy_database(tmp_path):
    snapshot = snapshot_from(
        tmp_path, VALID_BODY + f"DB_PATH = {str(settings.LEGACY_DATABASE_PATH)!r}\n"
    )
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_database_path(snapshot)
    assert exc_info.value.field_name == "DB_PATH"
    assert "legacy" in exc_info.value.detail


def test_db_path_rejects_config_py_itself(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "DB_PATH = __file__\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_database_path(snapshot)
    assert exc_info.value.field_name == "DB_PATH"


def test_db_path_rejects_a_target_inside_the_repository(tmp_path):
    inside_repo = settings.REPOSITORY_ROOT / "some" / "nested" / "chat.db"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DB_PATH = {str(inside_repo)!r}\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_database_path(snapshot)
    assert exc_info.value.field_name == "DB_PATH"
    assert "repository" in exc_info.value.detail


def test_db_path_wrong_type_is_reported_as_type(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "DB_PATH = 5\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_database_path(snapshot)
    assert exc_info.value.field_name == "DB_PATH"
    assert exc_info.value.kind == "type"


# --- build_settings: both halves together ------------------------------------

def test_build_settings_combines_provider_and_database(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY)
    built = settings.build_settings(snapshot)
    assert built.provider.model == "fixture-model"
    assert built.database_path == settings.DEFAULT_DATABASE_PATH.expanduser().resolve()


# --- no mutation: this module never touches the filesystem beyond reading ---

def test_building_settings_creates_nothing_on_disk_even_when_accepted(tmp_path):
    target_dir = tmp_path / "would_be_created"
    snapshot = snapshot_from(
        tmp_path, VALID_BODY + f"DB_PATH = {str(target_dir / 'chat.db')!r}\n"
    )
    resolved = settings.build_database_path(snapshot)
    assert resolved == (target_dir / "chat.db").resolve()
    assert not target_dir.exists()
