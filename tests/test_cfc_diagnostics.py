"""test_cfc_diagnostics.py — cfc/diagnostics.py: the seven-row inventory
doctor renders, and required_rows_ok's exit-code decision.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from cfc import conversation_store, diagnostics, entry, settings

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


@pytest.fixture(autouse=True)
def isolated_default_database(tmp_path, monkeypatch):
    """B-2.0-65. The appearance row is the first row that opens the
    configured 2.0 database, and a fixture body without `DATABASE_PATH`
    falls through to `settings.DEFAULT_DATABASE_PATH` — Cas's own live
    `~/.cfc/2.0/chat.db`. Reading it is a retained failure class ("tests do
    not touch personal configuration or live data") and it makes a row's
    content depend on whatever he last saved there. Every test in this file
    resolves that default under its own `tmp_path` instead; `settings`
    reads the module global at call time, so replacing it here reaches
    `build_database_path` and everything downstream of it.
    """
    monkeypatch.setattr(
        settings, "DEFAULT_DATABASE_PATH", tmp_path / "resolved-default" / "chat.db",
    )


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
    row = by_name(rows, "chat provider")
    assert row.state == diagnostics.State.ERROR
    assert row.next_step is not None
    assert "API_KEY" in row.next_step
    assert diagnostics.required_rows_ok(rows) is False


# --- D-2.0-19: every missing required provider field named together --------

def test_one_missing_provider_field_names_only_that_field(tmp_path):
    body = "API_BASE = 'https://provider.invalid/v1'\nMODEL = 'm'\n"  # API_KEY absent
    rows = diagnostics.diagnose(write_config(tmp_path, body))
    row = by_name(rows, "chat provider")
    assert row.state == diagnostics.State.ERROR
    assert "API_KEY" in row.detail
    assert "API_BASE" not in row.detail
    assert "MODEL" not in row.detail
    assert row.next_step is not None
    assert "API_KEY" in row.next_step


def test_two_missing_provider_fields_are_named_together_in_stable_order(tmp_path):
    body = "MODEL = 'm'\n"  # API_BASE and API_KEY both absent
    rows = diagnostics.diagnose(write_config(tmp_path, body))
    row = by_name(rows, "chat provider")
    assert row.state == diagnostics.State.ERROR
    base_pos = row.detail.index("API_BASE")
    key_pos = row.detail.index("API_KEY")
    assert base_pos < key_pos  # REQUIRED_PROVIDER_FIELD_NAMES's own order
    assert "MODEL" not in row.detail
    assert "API_BASE" in row.next_step
    assert "API_KEY" in row.next_step


def test_every_provider_field_missing_names_all_three_in_order(tmp_path):
    rows = diagnostics.diagnose(write_config(tmp_path, ""))
    row = by_name(rows, "chat provider")
    assert row.state == diagnostics.State.ERROR
    positions = [row.detail.index(name) for name in settings.REQUIRED_PROVIDER_FIELD_NAMES]
    assert positions == sorted(positions)
    assert diagnostics.required_rows_ok(rows) is False


def test_missing_provider_fields_row_names_no_configuration_value(tmp_path):
    marker = "SECRET-MARKER-DO-NOT-LEAK-onlykey-91af"
    body = f"API_KEY = {marker!r}\n"  # API_BASE and MODEL absent
    rows = diagnostics.diagnose(write_config(tmp_path, body))
    row = by_name(rows, "chat provider")
    assert marker not in row.detail
    assert marker not in (row.next_step or "")


def test_present_but_empty_provider_field_still_fails_one_field_at_a_time(tmp_path):
    """Once every required name exists, the aggregated path is not taken —
    ordinary per-field validation (unchanged) is what reports this."""
    body = "API_BASE = 'https://provider.invalid/v1'\nAPI_KEY = '   '\nMODEL = 'm'\n"
    rows = diagnostics.diagnose(write_config(tmp_path, body))
    row = by_name(rows, "chat provider")
    assert row.state == diagnostics.State.ERROR
    assert "API_KEY" in str(row.next_step)
    assert "missing required setting(s)" not in row.detail


def test_present_but_wrong_type_provider_field_still_fails_one_field_at_a_time(tmp_path):
    body = "API_BASE = 'https://provider.invalid/v1'\nAPI_KEY = 5\nMODEL = 'm'\n"
    rows = diagnostics.diagnose(write_config(tmp_path, body))
    row = by_name(rows, "chat provider")
    assert row.state == diagnostics.State.ERROR
    assert "API_KEY" in str(row.next_step)
    assert "missing required setting(s)" not in row.detail


def test_present_but_invalid_url_provider_field_still_fails_one_field_at_a_time(tmp_path):
    body = "API_BASE = 'not-a-url'\nAPI_KEY = 'k'\nMODEL = 'm'\n"
    rows = diagnostics.diagnose(write_config(tmp_path, body))
    row = by_name(rows, "chat provider")
    assert row.state == diagnostics.State.ERROR
    assert "API_BASE" in str(row.next_step)
    assert "missing required setting(s)" not in row.detail


def test_database_target_error_carries_a_next_step(tmp_path):
    path = write_config(
        tmp_path, VALID_BODY + f"DATABASE_PATH = {str(settings.LEGACY_DATABASE_PATH)!r}\n",
    )
    rows = diagnostics.diagnose(path)
    row = by_name(rows, "2.0 database target")
    assert row.state == diagnostics.State.ERROR
    assert row.next_step is not None
    assert "DATABASE_PATH" in row.next_step


def test_missing_config_file_gives_one_error_and_five_not_checked_rows(tmp_path):
    """D-2.0-07. Downstream rows that never actually ran a check must not
    be `ERROR` — that state is reserved for a row this module diagnosed and
    found broken. The configuration row alone carries the cure; the five
    dependent rows explain only that their prerequisite failed, with no
    `next_step` of their own (no duplicate cure) — and every one of them
    still fails `required_rows_ok` where it matters (the two required ones).
    """
    path = tmp_path / "does_not_exist.py"
    rows = diagnostics.diagnose(path)

    assert by_name(rows, "runtime").state == diagnostics.State.READY

    config_row = by_name(rows, "configuration")
    assert config_row.state == diagnostics.State.ERROR
    assert config_row.next_step is not None
    assert "config.example.py" in config_row.next_step
    assert "config.py" in config_row.next_step

    dependent_names = diagnostics.REQUIRED_ROW_NAMES[2:] + diagnostics.OPTIONAL_ROW_NAMES
    assert len(dependent_names) == 11
    for name in dependent_names:
        row = by_name(rows, name)
        assert row.state == diagnostics.State.NOT_CHECKED, name
        assert row.next_step is None, name
        assert row.detail
        assert row.next_step != config_row.next_step

    assert diagnostics.required_rows_ok(rows) is False


def test_not_checked_required_row_fails_required_rows_ok_even_without_error():
    """A synthetic row set proving `required_rows_ok`'s exact allow-list
    directly: no row here is `ERROR`, but a required row left `NOT_CHECKED`
    must still fail readiness — the old rule (`state != ERROR`) would have
    wrongly accepted this, which was D-2.0-07's actual bug.
    """
    rows = (
        diagnostics.Row("runtime", diagnostics.State.READY),
        diagnostics.Row("configuration", diagnostics.State.READY),
        diagnostics.Row("chat provider", diagnostics.State.NOT_CHECKED, "prerequisite failed"),
        diagnostics.Row("2.0 database target", diagnostics.State.READY),
    )
    assert diagnostics.required_rows_ok(rows) is False


# --- a config that exists and failed is never told to copy over itself -------

BROKEN_BODIES = {
    "syntax": VALID_BODY + "MODEL = (\n",
    "import": VALID_BODY + "import cfc_no_such_module_here\n",
    "exec": VALID_BODY + "raise ValueError('boom')\n",
}


@pytest.mark.parametrize("kind", sorted(BROKEN_BODIES))
def test_existing_config_that_failed_is_not_told_to_copy_the_example_over_it(tmp_path, kind):
    """B-2.0-18. A `config.py` that is present but will not load holds an
    API key and every configured path on the machine, and is gitignored —
    so copy-and-fill is not a cure here, it is unrecoverable data loss.
    The row still carries a next step; it just names correcting the file.
    """
    path = write_config(tmp_path, BROKEN_BODIES[kind])
    row = by_name(diagnostics.diagnose(path), "configuration")

    assert row.state == diagnostics.State.ERROR
    assert row.next_step is not None
    assert row.next_step != diagnostics._CONFIG_MISSING_NEXT_STEP
    assert "Copy config.example.py to config.py" not in row.next_step
    assert path.name in row.next_step
    assert path.read_text(encoding="utf-8") == BROKEN_BODIES[kind]


def test_missing_config_still_gets_the_copy_and_fill_cure(tmp_path):
    """The other half of B-2.0-18: nothing to lose, so the copy-and-fill
    route D-2.0-07 shipped is still exactly right.
    """
    row = by_name(diagnostics.diagnose(tmp_path / "absent.py"), "configuration")
    assert row.next_step == diagnostics._CONFIG_MISSING_NEXT_STEP


def test_config_path_that_is_a_directory_is_not_told_to_copy_over_it(tmp_path):
    """`load_snapshot` reports a directory under the same `"missing"` kind
    as an absent file, so the choice cannot be made on `kind` alone — it is
    made on whether anything is already at that path.
    """
    path = tmp_path / "config.py"
    path.mkdir()
    row = by_name(diagnostics.diagnose(path), "configuration")
    assert row.state == diagnostics.State.ERROR
    assert "Copy config.example.py to config.py" not in (row.next_step or "")


# --- D-2.0-20: the ready runtime row reports version and MIN_PYTHON floor ---

def test_ready_runtime_row_reports_the_running_version_and_the_real_floor(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    row = by_name(diagnostics.diagnose(path), "runtime")
    assert row.state == diagnostics.State.READY
    assert re.fullmatch(r"\d+\.\d+\.\d+ \(floor \d+\.\d+\)", row.detail)
    expected_version = ".".join(str(part) for part in sys.version_info[:3])
    expected_floor = ".".join(str(part) for part in entry.MIN_PYTHON)
    assert row.detail == f"{expected_version} (floor {expected_floor})"


def test_ready_runtime_row_floor_tracks_min_python_not_a_duplicated_literal(tmp_path, monkeypatch):
    """A hardcoded `"3.14.x (floor 3.14)"` string would pass the previous
    test by coincidence. Moving the real floor this interpreter still
    satisfies and checking the row's floor half moves with it proves the
    detail is actually read from `entry.MIN_PYTHON`, not copied.
    """
    monkeypatch.setattr(entry, "MIN_PYTHON", (3, 5))
    path = write_config(tmp_path, VALID_BODY)
    row = by_name(diagnostics.diagnose(path), "runtime")
    assert row.state == diagnostics.State.READY
    assert row.detail.endswith("(floor 3.5)")


# --- vault: not configured / locally invalid / ready -------------------------

def test_vault_not_configured(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "vault").state == diagnostics.State.UNAVAILABLE


def test_vault_placeholder_counts_as_not_configured(tmp_path):
    path = write_config(tmp_path, VALID_BODY + "VAULT_ROOT = 'PLACEHOLDER'\n")
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "vault").state == diagnostics.State.UNAVAILABLE


def test_vault_ready_when_directory_exists(tmp_path):
    vault_dir = tmp_path / "vault"
    vault_dir.mkdir()
    path = write_config(tmp_path, VALID_BODY + f"VAULT_ROOT = {str(vault_dir)!r}\n")
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "vault").state == diagnostics.State.READY
    assert str(vault_dir) in by_name(rows, "vault").detail


def test_vault_error_when_directory_does_not_exist_yet_even_though_parent_does(tmp_path):
    """B-2.0-11. Unlike the 2.0 database target, cfc never creates the
    vault root, so a missing directory is a visible, non-blocking error —
    not `READY` merely because its parent exists.
    """
    vault_dir = tmp_path / "not_yet_created"
    path = write_config(tmp_path, VALID_BODY + f"VAULT_ROOT = {str(vault_dir)!r}\n")
    rows = diagnostics.diagnose(path)
    row = by_name(rows, "vault")
    assert row.state == diagnostics.State.ERROR
    assert str(vault_dir) in row.detail
    assert not vault_dir.exists()
    assert row.next_step is not None
    assert "VAULT_ROOT" in row.next_step
    assert diagnostics.required_rows_ok(rows) is True


def test_vault_error_when_configured_root_is_a_file(tmp_path):
    vault_file = tmp_path / "vault-is-actually-a-file"
    vault_file.write_text("x", encoding="utf-8")
    path = write_config(tmp_path, VALID_BODY + f"VAULT_ROOT = {str(vault_file)!r}\n")
    rows = diagnostics.diagnose(path)
    row = by_name(rows, "vault")
    assert row.state == diagnostics.State.ERROR
    assert "not a directory" in row.detail
    assert row.next_step is not None


def test_vault_error_when_blocked_by_a_file(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    vault_dir = blocker / "vault"
    path = write_config(tmp_path, VALID_BODY + f"VAULT_ROOT = {str(vault_dir)!r}\n")
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "vault").state == diagnostics.State.ERROR


def test_chat_export_dir_is_not_the_vault(tmp_path):
    """B-2.0-01: the row is named for `VAULT_ROOT`, and an export directory
    — under either of its two names — must not answer for it. Both are set
    here to real directories, so a row reading the wrong one still looks
    ready; only the path it names gives it away.
    """
    export_dir = tmp_path / "chat-export"
    export_dir.mkdir()
    path = write_config(
        tmp_path,
        VALID_BODY
        + f"CHAT_EXPORT_DIR = {str(export_dir)!r}\n"
        + f"VAULT_PATH = {str(export_dir)!r}\n",
    )
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "vault").state == diagnostics.State.UNAVAILABLE
    assert str(export_dir) not in by_name(rows, "vault").detail


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


# --- Stage 5 vault category rows: shared readiness with Context ------------

_CATEGORY_ROWS = (
    ("user preferences", "USER_PREFERENCES_DIR"),
    ("personas", "PERSONAS_DIR"),
    ("traits", "TRAITS_DIR"),
    ("first messages", "FIRST_MESSAGES_DIR"),
)


@pytest.mark.parametrize("row_name,field_name", _CATEGORY_ROWS)
def test_vault_category_row_unavailable_when_unconfigured(tmp_path, row_name, field_name):
    path = write_config(tmp_path, VALID_BODY)
    row = by_name(diagnostics.diagnose(path), row_name)
    assert row.state == diagnostics.State.UNAVAILABLE
    assert field_name in row.detail


@pytest.mark.parametrize("row_name,field_name", _CATEGORY_ROWS)
def test_vault_category_row_ready_empty_for_a_real_empty_directory(tmp_path, row_name, field_name):
    vault_root = tmp_path / "vault"
    category_dir = vault_root / row_name.replace(" ", "_")
    category_dir.mkdir(parents=True)
    path = write_config(
        tmp_path,
        VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\n{field_name} = {str(category_dir)!r}\n",
    )
    row = by_name(diagnostics.diagnose(path), row_name)
    assert row.state == diagnostics.State.READY
    assert "empty" in row.detail
    assert "0" in row.detail


@pytest.mark.parametrize("row_name,field_name", _CATEGORY_ROWS)
def test_vault_category_row_ready_with_a_selectable_count(tmp_path, row_name, field_name):
    vault_root = tmp_path / "vault"
    category_dir = vault_root / row_name.replace(" ", "_")
    category_dir.mkdir(parents=True)
    (category_dir / "one.md").write_text("one", encoding="utf-8")
    (category_dir / "two.md").write_text("two", encoding="utf-8")
    path = write_config(
        tmp_path,
        VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\n{field_name} = {str(category_dir)!r}\n",
    )
    row = by_name(diagnostics.diagnose(path), row_name)
    assert row.state == diagnostics.State.READY
    assert "2" in row.detail
    assert "empty" not in row.detail


@pytest.mark.parametrize("row_name,field_name", _CATEGORY_ROWS)
def test_vault_category_row_error_when_configured_directory_does_not_exist(
    tmp_path, row_name, field_name,
):
    vault_root = tmp_path / "vault"
    category_dir = vault_root / "missing"
    path = write_config(
        tmp_path,
        VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\n{field_name} = {str(category_dir)!r}\n",
    )
    row = by_name(diagnostics.diagnose(path), row_name)
    assert row.state == diagnostics.State.ERROR
    assert str(category_dir) in row.detail
    assert row.next_step is not None
    assert field_name in row.next_step
    assert not category_dir.exists()


def test_vault_category_rows_never_affect_required_rows_ok(tmp_path):
    vault_root = tmp_path / "vault"
    path = write_config(
        tmp_path,
        VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\nPERSONAS_DIR = {str(vault_root / 'missing')!r}\n",
    )
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "personas").state == diagnostics.State.ERROR
    assert diagnostics.required_rows_ok(rows) is True


# --- model catalogue row: absent/empty unavailable, malformed an error -----

def test_model_catalogue_row_unavailable_when_unset(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    row = by_name(diagnostics.diagnose(path), "model catalogue")
    assert row.state == diagnostics.State.UNAVAILABLE


def test_model_catalogue_row_unavailable_when_no_entry_is_selectable(tmp_path):
    path = write_config(
        tmp_path, VALID_BODY + "MODELS = [dict(id='m/one', listed=False)]\n",
    )
    row = by_name(diagnostics.diagnose(path), "model catalogue")
    assert row.state == diagnostics.State.UNAVAILABLE


def test_model_catalogue_row_ready_with_selectable_count(tmp_path):
    path = write_config(
        tmp_path,
        VALID_BODY + "MODELS = [dict(id='m/one'), dict(id='m/two', listed=False)]\n",
    )
    row = by_name(diagnostics.diagnose(path), "model catalogue")
    assert row.state == diagnostics.State.READY
    assert "1" in row.detail


def test_model_catalogue_row_error_when_malformed(tmp_path):
    path = write_config(
        tmp_path, VALID_BODY + "MODELS = [dict(id='a'), dict(id='a')]\n",
    )
    row = by_name(diagnostics.diagnose(path), "model catalogue")
    assert row.state == diagnostics.State.ERROR
    assert row.next_step is not None
    assert "MODELS" in row.next_step
    assert diagnostics.required_rows_ok(diagnostics.diagnose(path)) is True


def test_model_catalogue_row_never_prints_the_configuration_record(tmp_path):
    marker = "SECRET-MARKER-DO-NOT-LEAK-model-9c31"
    path = write_config(
        tmp_path, VALID_BODY + f"MODELS = [dict(id={marker!r})]\n",
    )
    row = by_name(diagnostics.diagnose(path), "model catalogue")
    assert marker not in row.detail
    assert marker not in (row.next_step or "")


# --- appearance row: effective value, source, and safe non-inspection ------

def test_appearance_row_reports_the_bootstrap_default_when_no_database_exists_yet(tmp_path):
    db_target = tmp_path / "store" / "chat.db"
    path = write_config(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(db_target)!r}\n")
    row = by_name(diagnostics.diagnose(path), "appearance")
    assert row.state == diagnostics.State.READY
    assert "dark" in row.detail
    assert not db_target.exists()


def test_appearance_row_reports_the_configured_default_when_tui_theme_is_light(tmp_path):
    db_target = tmp_path / "store" / "chat.db"
    path = write_config(
        tmp_path,
        VALID_BODY + f"DATABASE_PATH = {str(db_target)!r}\nTUI_THEME = 'light'\n",
    )
    row = by_name(diagnostics.diagnose(path), "appearance")
    assert row.state == diagnostics.State.READY
    assert "light" in row.detail


def test_appearance_row_reports_a_saved_override_when_the_database_is_inspectable(tmp_path):
    db_target = tmp_path / "store" / "chat.db"
    store = conversation_store.open_store(db_target)
    store.save_appearance_override("light")
    store.close()

    path = write_config(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(db_target)!r}\n")
    row = by_name(diagnostics.diagnose(path), "appearance")
    assert row.state == diagnostics.State.READY
    assert "light" in row.detail
    assert "saved override" in row.detail


def test_appearance_row_reports_configured_default_when_database_has_no_override(tmp_path):
    db_target = tmp_path / "store" / "chat.db"
    conversation_store.open_store(db_target).close()

    path = write_config(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(db_target)!r}\n")
    row = by_name(diagnostics.diagnose(path), "appearance")
    assert row.state == diagnostics.State.READY
    assert "dark" in row.detail
    assert "configured default" in row.detail


def test_appearance_row_falls_back_to_bootstrap_when_database_is_locked(tmp_path):
    db_target = tmp_path / "store" / "chat.db"
    owner = conversation_store.open_store(db_target)
    try:
        path = write_config(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(db_target)!r}\n")
        row = by_name(diagnostics.diagnose(path), "appearance")
        assert row.state == diagnostics.State.READY
        assert "dark" in row.detail
        assert "not inspected" in row.detail
    finally:
        owner.close()


def test_appearance_row_falls_back_to_bootstrap_when_database_is_the_wrong_schema(tmp_path):
    import sqlite3
    db_target = tmp_path / "store" / "chat.db"
    db_target.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_target))
    conn.execute(f"PRAGMA application_id = {conversation_store.APPLICATION_ID}")
    conn.execute("PRAGMA user_version = 1")
    conn.execute("CREATE TABLE placeholder (x INTEGER)")
    conn.commit()
    conn.close()

    path = write_config(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(db_target)!r}\n")
    row = by_name(diagnostics.diagnose(path), "appearance")
    assert row.state == diagnostics.State.READY
    assert "dark" in row.detail
    assert "not inspected" in row.detail


def test_appearance_row_falls_back_to_bootstrap_when_the_database_path_is_unresolvable(tmp_path):
    path = write_config(
        tmp_path,
        VALID_BODY + f"DATABASE_PATH = {str(settings.LEGACY_DATABASE_PATH)!r}\n",
    )
    row = by_name(diagnostics.diagnose(path), "appearance")
    assert row.state == diagnostics.State.READY
    assert "dark" in row.detail
    assert "2.0 database target" in row.detail


def test_appearance_row_never_affects_required_rows_ok(tmp_path):
    db_target = tmp_path / "store" / "chat.db"
    path = write_config(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(db_target)!r}\n")
    rows = diagnostics.diagnose(path)
    assert by_name(rows, "appearance").state == diagnostics.State.READY
    assert diagnostics.required_rows_ok(rows) is True


def test_appearance_row_falls_back_to_bootstrap_when_the_database_is_malformed(tmp_path):
    """B-2.0-63 through doctor's own surface: a database carrying cfc's
    header but malformed pages made `diagnose` raise `sqlite3.DatabaseError`
    instead of building a row, so `python -m cfc doctor` — the one command
    whose job is explaining what is wrong — died on the corruption it exists
    to report.
    """
    db_target = tmp_path / "store" / "chat.db"
    conversation_store.open_store(db_target).close()
    data = bytearray(db_target.read_bytes())
    page_size = int.from_bytes(data[16:18], "big") or 65536
    for index in range(page_size, len(data)):
        data[index] = 0x41
    db_target.write_bytes(bytes(data))

    path = write_config(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(db_target)!r}\n")
    rows = diagnostics.diagnose(path)
    row = by_name(rows, "appearance")
    assert row.state == diagnostics.State.READY
    assert "dark" in row.detail
    assert "not inspected" in row.detail
    assert diagnostics.required_rows_ok(rows) is True


# --- a rejected TUI_THEME is its own source, with its own correction route --

def test_appearance_row_names_the_built_in_fallback_when_tui_theme_is_invalid(tmp_path):
    """B-2.0-64: `build_theme` returns `dark` for an unset `TUI_THEME` and a
    rejected one alike, so reporting both as "configured default" told Cas
    his value had been honoured when it had not.
    """
    db_target = tmp_path / "store" / "chat.db"
    path = write_config(
        tmp_path,
        VALID_BODY + f"DATABASE_PATH = {str(db_target)!r}\nTUI_THEME = 'solarized'\n",
    )
    row = by_name(diagnostics.diagnose(path), "appearance")
    assert row.state == diagnostics.State.READY
    assert "dark" in row.detail
    assert "configured default" not in row.detail
    assert "TUI_THEME" in row.detail
    assert row.next_step is not None
    assert "TUI_THEME" in row.next_step


def test_appearance_row_carries_no_correction_route_for_an_accepted_tui_theme(tmp_path):
    db_target = tmp_path / "store" / "chat.db"
    for body in ("", "TUI_THEME = 'dark'\n", "TUI_THEME = 'light'\n"):
        path = write_config(
            tmp_path,
            VALID_BODY + f"DATABASE_PATH = {str(db_target)!r}\n" + body,
        )
        row = by_name(diagnostics.diagnose(path), "appearance")
        assert row.next_step is None, body
        assert "configured default" in row.detail, body


def test_invalid_tui_theme_keeps_its_correction_route_behind_a_saved_override(tmp_path):
    """The override decides the effective value; the rejected setting is
    still a real misconfiguration, and it is what a later reset falls back
    to — so the route stays even though the colour shown is not from it.
    """
    db_target = tmp_path / "store" / "chat.db"
    store = conversation_store.open_store(db_target)
    store.save_appearance_override("light")
    store.close()

    path = write_config(
        tmp_path,
        VALID_BODY + f"DATABASE_PATH = {str(db_target)!r}\nTUI_THEME = 'solarized'\n",
    )
    row = by_name(diagnostics.diagnose(path), "appearance")
    assert "light (saved override)" in row.detail
    assert row.next_step is not None


def test_a_config_without_a_database_path_inspects_only_the_resolved_default(tmp_path, monkeypatch):
    """The mechanism behind B-2.0-65, pinned: with no `DATABASE_PATH` set,
    the one target the appearance row opens is whatever
    `settings.DEFAULT_DATABASE_PATH` currently resolves to — so a test
    file that does not redirect that constant reads the real one.
    """
    seen = []
    real_inspect = conversation_store.inspect_appearance_override

    def recording_inspect(path):
        seen.append(Path(path))
        return real_inspect(path)

    monkeypatch.setattr(conversation_store, "inspect_appearance_override", recording_inspect)
    path = write_config(tmp_path, VALID_BODY)
    diagnostics.diagnose(path)

    assert seen == [settings.DEFAULT_DATABASE_PATH.expanduser().resolve()]
    assert tmp_path in seen[0].parents


def test_appearance_row_never_prints_the_rejected_tui_theme_value(tmp_path):
    marker = "SECRET-MARKER-DO-NOT-LEAK-theme-4b8d"
    path = write_config(tmp_path, VALID_BODY + f"TUI_THEME = {marker!r}\n")
    row = by_name(diagnostics.diagnose(path), "appearance")
    assert marker not in row.detail
    assert marker not in (row.next_step or "")


def test_appearance_row_never_creates_the_database_target(tmp_path):
    db_target = tmp_path / "store" / "chat.db"
    path = write_config(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(db_target)!r}\n")
    diagnostics.diagnose(path)
    assert not db_target.exists()
    assert not db_target.parent.exists()


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
        assert api_marker not in (row.next_step or "")
        assert embed_marker not in (row.next_step or "")
        assert api_marker not in repr(row)
        assert embed_marker not in repr(row)


# --- no filesystem mutation, across every row --------------------------------

def test_diagnose_creates_nothing_on_disk(tmp_path):
    vault_dir = tmp_path / "vault_not_yet_created"
    db_dir = tmp_path / "db_not_yet_created"
    path = write_config(
        tmp_path,
        VALID_BODY
        + f"VAULT_ROOT = {str(vault_dir)!r}\n"
        + f"DATABASE_PATH = {str(db_dir / 'chat.db')!r}\n"
        + "TOOLS_ENABLED = True\n",
    )
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    diagnostics.diagnose(path)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after
    assert not vault_dir.exists()
    assert not db_dir.exists()
