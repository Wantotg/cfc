"""test_cfc_diagnostics.py — cfc/diagnostics.py: the seven-row inventory
doctor renders, and required_rows_ok's exit-code decision.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from cfc import diagnostics, entry, settings

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
    assert len(dependent_names) == 5
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
