"""test_cfc_config_loader.py — cfc/config_loader.py: the seam that executes
a trusted config file once and hands back an immutable snapshot.

Native pytest test module (no __main__ guard) — not one of the legacy
suites test_entry_gate.py inventories.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from cfc import config_loader


def write_config(tmp_path: Path, body: str, name: str = "config.py") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# --- one execution, an immutable snapshot -----------------------------------

def test_loads_a_minimal_config(tmp_path):
    path = write_config(tmp_path, "API_BASE = 'https://x.invalid/v1'\nMODEL = 'm'\n")
    snapshot = config_loader.load_snapshot(path)
    assert snapshot.path == path
    assert snapshot.values["API_BASE"] == "https://x.invalid/v1"
    assert snapshot.values["MODEL"] == "m"


def test_dunder_names_are_not_in_the_public_snapshot(tmp_path):
    path = write_config(tmp_path, "X = 1\n")
    snapshot = config_loader.load_snapshot(path)
    assert "__file__" not in snapshot.values
    assert "__name__" not in snapshot.values


def test_nested_collections_are_frozen(tmp_path):
    path = write_config(
        tmp_path,
        "MODELS = [dict(id='a'), dict(id='b')]\n"
        "SCOPES = ({'name': 'x'},)\n"
        "DENY = {'a', 'b'}\n",
    )
    snapshot = config_loader.load_snapshot(path)
    assert isinstance(snapshot.values["MODELS"], tuple)
    assert isinstance(snapshot.values["MODELS"][0], types.MappingProxyType)
    assert isinstance(snapshot.values["SCOPES"], tuple)
    assert isinstance(snapshot.values["SCOPES"][0], types.MappingProxyType)
    assert isinstance(snapshot.values["DENY"], tuple)
    assert set(snapshot.values["DENY"]) == {"a", "b"}

    with pytest.raises(TypeError):
        snapshot.values["MODELS"][0]["id"] = "changed"


def test_a_second_load_is_independent_of_the_first(tmp_path):
    """The loader executes the file once per call; two calls on the same
    path must not share mutable state with each other.
    """
    path = write_config(tmp_path, "ITEMS = [1, 2, 3]\n")
    first = config_loader.load_snapshot(path)
    second = config_loader.load_snapshot(path)
    assert first.values["ITEMS"] == second.values["ITEMS"]
    assert first is not second


# --- root-relative discovery -------------------------------------------------

def test_default_config_path_is_the_repository_root(tmp_path, monkeypatch):
    """Anchored on cfc/config_loader.py's own location, not the working
    directory — must resolve to the same path regardless of cwd.
    """
    from_repo = config_loader.default_config_path()
    monkeypatch.chdir(tmp_path)
    from_elsewhere = config_loader.default_config_path()
    assert from_repo == from_elsewhere
    assert from_repo.name == "config.py"
    assert from_repo.parent == Path(config_loader.__file__).resolve().parent.parent


def test_resolve_config_path_defaults_to_the_repository_root(monkeypatch):
    monkeypatch.delenv(config_loader.CONFIG_PATH_ENV_VAR, raising=False)
    assert config_loader.resolve_config_path() == config_loader.default_config_path()


def test_resolve_config_path_honours_the_override_env_var(tmp_path, monkeypatch):
    override = tmp_path / "elsewhere.py"
    monkeypatch.setenv(config_loader.CONFIG_PATH_ENV_VAR, str(override))
    assert config_loader.resolve_config_path() == override


def test_load_snapshot_with_no_path_goes_through_resolve_config_path(tmp_path, monkeypatch):
    override = write_config(tmp_path, "MODEL = 'from-override'\n")
    monkeypatch.setenv(config_loader.CONFIG_PATH_ENV_VAR, str(override))
    snapshot = config_loader.load_snapshot()
    assert snapshot.path == override
    assert snapshot.values["MODEL"] == "from-override"


# --- missing / syntax / import / exec distinctions --------------------------

def test_missing_file_is_reported_as_missing(tmp_path):
    path = tmp_path / "does_not_exist.py"
    with pytest.raises(config_loader.ConfigLoadError) as exc_info:
        config_loader.load_snapshot(path)
    assert exc_info.value.kind == "missing"


def test_directory_at_the_path_is_reported_as_missing(tmp_path):
    path = tmp_path / "config.py"
    path.mkdir()
    with pytest.raises(config_loader.ConfigLoadError) as exc_info:
        config_loader.load_snapshot(path)
    assert exc_info.value.kind == "missing"


def test_syntax_error_is_reported_as_syntax(tmp_path):
    path = write_config(tmp_path, "def broken(:\n")
    with pytest.raises(config_loader.ConfigLoadError) as exc_info:
        config_loader.load_snapshot(path)
    assert exc_info.value.kind == "syntax"


def test_failed_import_is_reported_as_import(tmp_path):
    path = write_config(tmp_path, "import this_module_does_not_exist_anywhere\n")
    with pytest.raises(config_loader.ConfigLoadError) as exc_info:
        config_loader.load_snapshot(path)
    assert exc_info.value.kind == "import"


def test_other_runtime_error_is_reported_as_exec(tmp_path):
    path = write_config(tmp_path, "X = 1 / 0\n")
    with pytest.raises(config_loader.ConfigLoadError) as exc_info:
        config_loader.load_snapshot(path)
    assert exc_info.value.kind == "exec"


def test_config_load_error_never_prints_the_files_contents(tmp_path):
    """A secret in a broken config must not surface in the loader's own
    exception text — only the path and the underlying error's message.
    """
    marker = "SECRET-MARKER-DO-NOT-LEAK-9f3a"
    path = write_config(tmp_path, f'API_KEY = "{marker}"\nX = 1 / 0\n')
    with pytest.raises(config_loader.ConfigLoadError) as exc_info:
        config_loader.load_snapshot(path)
    assert marker not in str(exc_info.value)
    assert marker not in repr(exc_info.value)
