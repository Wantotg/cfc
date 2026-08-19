"""test_cfc_tool_registry.py — cfc/tool_registry.py: the one `ToolRegistry`
owning `list_dir`/`read_file`/`grep`'s schemas, availability, argument
validation, and execution handlers. Narrow by design: the tool
implementations themselves are proven in `test_cfc_tool_executor.py`; this
file proves the registry wiring, argument-schema validation, and the
capability-switch offering rule.

`FileToolSettings` fixtures are built through the real producer,
`cfc.settings.build_file_tool_settings`, rather than constructed by hand —
`usable`/`problem` is an invariant that producer enforces, not something
this module's dataclass constructor checks for itself.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cfc import config_loader, settings as settings_mod
from cfc import tool_registry as registry_mod


def usable_settings(tmp_path: Path) -> settings_mod.FileToolSettings:
    config_path = tmp_path / "config.py"
    root = tmp_path / "root"
    root.mkdir()
    config_path.write_text(
        "API_BASE = 'https://provider.invalid/v1'\nAPI_KEY = 'k'\nMODEL = 'm'\n"
        f"TOOLS_ENABLED = True\nTOOLS_ROOTS = ({str(root)!r},)\n"
    )
    snapshot = config_loader.load_snapshot(config_path)
    return settings_mod.build_file_tool_settings(snapshot)


def disabled_settings(tmp_path: Path) -> settings_mod.FileToolSettings:
    config_path = tmp_path / "config.py"
    config_path.write_text(
        "API_BASE = 'https://provider.invalid/v1'\nAPI_KEY = 'k'\nMODEL = 'm'\n"
    )
    snapshot = config_loader.load_snapshot(config_path)
    return settings_mod.build_file_tool_settings(snapshot)


# --- default_registry: shape and consistency --------------------------

def test_default_registry_has_all_three_tools():
    registry = registry_mod.default_registry()
    assert {d.name for d in registry.definitions()} == {"list_dir", "read_file", "grep"}


def test_unknown_tool_name_has_no_definition():
    registry = registry_mod.default_registry()
    assert registry.get("write_file") is None
    assert registry.get("nonsense") is None


def test_every_definition_requires_read_files_capability():
    registry = registry_mod.default_registry()
    for definition in registry.definitions():
        assert definition.capability is registry_mod.ToolCapability.READ_FILES


def test_every_definition_schema_matches_its_own_name(tmp_path):
    registry = registry_mod.default_registry()
    for definition in registry.definitions():
        schema = definition.schema()
        assert schema.name == definition.name
        assert schema.parameters is definition.parameters


# --- offered_schemas: the capability switch ----------------------------

def test_offered_schemas_empty_when_file_tools_unusable(tmp_path):
    registry = registry_mod.default_registry()
    schemas = registry.offered_schemas(disabled_settings(tmp_path), model_is_tool_capable=True)
    assert schemas == ()


def test_offered_schemas_empty_when_model_not_tool_capable(tmp_path):
    registry = registry_mod.default_registry()
    schemas = registry.offered_schemas(usable_settings(tmp_path), model_is_tool_capable=False)
    assert schemas == ()


def test_offered_schemas_all_three_when_usable_and_model_capable(tmp_path):
    registry = registry_mod.default_registry()
    schemas = registry.offered_schemas(usable_settings(tmp_path), model_is_tool_capable=True)
    assert {s.name for s in schemas} == {"list_dir", "read_file", "grep"}


def test_offered_schemas_never_approval_only_capability(tmp_path):
    """A true capability switch offers schemas; whether each concrete call
    is approved is a separate, later question this function never
    answers."""
    registry = registry_mod.default_registry()
    schemas = registry.offered_schemas(usable_settings(tmp_path), model_is_tool_capable=True)
    assert len(schemas) == 3  # offered regardless of any approval state


# --- list_dir argument validation --------------------------------------

def test_list_dir_valid_arguments():
    definition = registry_mod.default_registry().get("list_dir")
    parsed, error = definition.validate_arguments('{"path": "/tmp"}')
    assert error is None
    assert parsed == {"path": "/tmp"}


@pytest.mark.parametrize("raw", [
    "not json", "5", "[]", '{"path": 5}', '{"path": ""}', "{}",
    '{"path": "/tmp", "extra": true}',
])
def test_list_dir_invalid_arguments(raw):
    definition = registry_mod.default_registry().get("list_dir")
    parsed, error = definition.validate_arguments(raw)
    assert error is not None
    assert parsed == {}


def test_list_dir_describe_pending():
    definition = registry_mod.default_registry().get("list_dir")
    assert definition.describe_pending({"path": "/tmp"}) == "List the contents of /tmp"


# --- read_file argument validation --------------------------------------

def test_read_file_valid_arguments_with_range():
    definition = registry_mod.default_registry().get("read_file")
    parsed, error = definition.validate_arguments(
        '{"path": "/tmp/a", "start_line": 2, "end_line": 5}'
    )
    assert error is None
    assert parsed == {"path": "/tmp/a", "start_line": 2, "end_line": 5}


def test_read_file_valid_arguments_without_range():
    definition = registry_mod.default_registry().get("read_file")
    parsed, error = definition.validate_arguments('{"path": "/tmp/a"}')
    assert error is None
    assert parsed == {"path": "/tmp/a"}


@pytest.mark.parametrize("raw", [
    '{"path": "/tmp/a", "start_line": "two"}',
    '{"path": "/tmp/a", "start_line": true}',
    '{"path": "/tmp/a", "end_line": 1.5}',
    '{"start_line": 1}',
    '{"path": "/tmp/a", "bogus": 1}',
])
def test_read_file_invalid_arguments(raw):
    definition = registry_mod.default_registry().get("read_file")
    parsed, error = definition.validate_arguments(raw)
    assert error is not None


def test_read_file_describe_pending_with_and_without_range():
    definition = registry_mod.default_registry().get("read_file")
    assert definition.describe_pending({"path": "/tmp/a"}) == "Read /tmp/a"
    assert "lines 2-5" in definition.describe_pending(
        {"path": "/tmp/a", "start_line": 2, "end_line": 5}
    )


# --- grep argument validation --------------------------------------------

def test_grep_valid_arguments():
    definition = registry_mod.default_registry().get("grep")
    parsed, error = definition.validate_arguments('{"pattern": "TODO", "path": "/tmp"}')
    assert error is None
    assert parsed == {"pattern": "TODO", "path": "/tmp"}


@pytest.mark.parametrize("raw", [
    '{"pattern": "", "path": "/tmp"}',
    '{"path": "/tmp"}',
    '{"pattern": "TODO"}',
    '{"pattern": "TODO", "path": "/tmp", "extra": 1}',
])
def test_grep_invalid_arguments(raw):
    definition = registry_mod.default_registry().get("grep")
    parsed, error = definition.validate_arguments(raw)
    assert error is not None


# --- execute: wired to the real tool_executor functions --------------------

def test_list_dir_execute_runs_the_real_executor(tmp_path):
    from cfc.tool_authority import FileAuthority
    from cfc.conversation_types import ToolOutcomeKind

    file_tools = usable_settings(tmp_path)
    root = file_tools.roots[0]
    (root / "f.txt").write_text("x")
    definition = registry_mod.default_registry().get("list_dir")
    authority = FileAuthority(roots=(root,))

    outcome = definition.execute({"path": str(root)}, authority, file_tools, lambda: False)
    assert outcome.kind is ToolOutcomeKind.SUCCESS
    assert "f.txt" in outcome.content


def test_read_file_execute_respects_line_range(tmp_path):
    from cfc.tool_authority import FileAuthority

    file_tools = usable_settings(tmp_path)
    root = file_tools.roots[0]
    (root / "f.txt").write_text("a\nb\nc\n")
    definition = registry_mod.default_registry().get("read_file")
    authority = FileAuthority(roots=(root,))

    outcome = definition.execute(
        {"path": str(root / "f.txt"), "start_line": 2, "end_line": 2}, authority, file_tools,
        lambda: False,
    )
    assert "b" in outcome.content
    assert "a" not in outcome.content


def test_grep_execute_finds_matches(tmp_path):
    from cfc.tool_authority import FileAuthority

    file_tools = usable_settings(tmp_path)
    root = file_tools.roots[0]
    (root / "f.txt").write_text("hello TODO world\n")
    definition = registry_mod.default_registry().get("grep")
    authority = FileAuthority(roots=(root,))

    outcome = definition.execute(
        {"pattern": "TODO", "path": str(root)}, authority, file_tools, lambda: False,
    )
    assert outcome.counts["matches"] == 1
