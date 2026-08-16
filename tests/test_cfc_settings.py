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


# --- the shared required-field ordering (D-2.0-19) ---------------------------

def test_required_provider_field_names_is_api_base_key_model_in_that_order():
    assert settings.REQUIRED_PROVIDER_FIELD_NAMES == ("API_BASE", "API_KEY", "MODEL")


@pytest.mark.parametrize("index", range(3))
def test_a_field_missing_only_from_the_shared_list_is_still_reported_missing(tmp_path, index):
    """Proves `build_provider` really reads `REQUIRED_PROVIDER_FIELD_NAMES`
    rather than a second, independently-spelled literal: dropping each name
    the tuple names, in the tuple's own order, is what this test drives.
    """
    field_name = settings.REQUIRED_PROVIDER_FIELD_NAMES[index]
    lines = [ln for ln in VALID_BODY.splitlines() if not ln.startswith(field_name)]
    snapshot = snapshot_from(tmp_path, "\n".join(lines) + "\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_provider(snapshot)
    assert exc_info.value.field_name == field_name
    assert exc_info.value.kind == "missing"


# --- database target: default, override, protected targets ------------------

def test_unset_database_path_uses_the_2_0_default(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY)
    resolved = settings.build_database_path(snapshot)
    assert resolved == settings.DEFAULT_DATABASE_PATH.expanduser().resolve()


def test_blank_database_path_uses_the_2_0_default(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "DATABASE_PATH = '   '\n")
    resolved = settings.build_database_path(snapshot)
    assert resolved == settings.DEFAULT_DATABASE_PATH.expanduser().resolve()


def test_db_path_only_config_falls_back_to_the_2_0_default(tmp_path):
    """`DB_PATH` is the legacy flat runtime's own field (`db.py`). A
    `config.py` that sets only that spelling and no `DATABASE_PATH` must
    resolve to the ordinary 2.0 default, not be quietly read as if it had
    set the 2.0 field — `DB_PATH` is not a hidden alias.
    """
    legacy_target = tmp_path / "legacy-only-target" / "chat.db"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DB_PATH = {str(legacy_target)!r}\n")
    resolved = settings.build_database_path(snapshot)
    assert resolved == settings.DEFAULT_DATABASE_PATH.expanduser().resolve()
    assert resolved != legacy_target.resolve()


def test_database_path_override_is_expanded_and_resolved(tmp_path):
    target = tmp_path / "nested" / "chat.db"
    target.parent.mkdir()
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(target)!r}\n")
    resolved = settings.build_database_path(snapshot)
    assert resolved == target.resolve()


def test_database_path_accepts_a_nonexistent_file_with_a_usable_parent(tmp_path):
    parent = tmp_path / "usable"
    parent.mkdir()
    target = parent / "chat.db"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(target)!r}\n")
    resolved = settings.build_database_path(snapshot)
    assert resolved == target.resolve()
    assert not target.exists()


def test_database_path_accepts_several_missing_levels_above_an_existing_root(tmp_path):
    """Only the *nearest existing* ancestor has to look usable — the work
    order is explicit that intermediate missing levels are accepted, not a
    reason to refuse.
    """
    target = tmp_path / "does" / "not" / "exist" / "chat.db"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(target)!r}\n")
    resolved = settings.build_database_path(snapshot)
    assert resolved == target.resolve()
    assert not target.parent.exists()


def test_database_path_rejects_an_ancestor_blocked_by_a_file(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    target = blocker / "chat.db"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(target)!r}\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_database_path(snapshot)
    assert exc_info.value.field_name == "DATABASE_PATH"
    assert exc_info.value.kind == "value"


def test_database_path_rejects_a_directory_target(tmp_path):
    target = tmp_path / "a_directory"
    target.mkdir()
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(target)!r}\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_database_path(snapshot)
    assert exc_info.value.field_name == "DATABASE_PATH"


def test_database_path_rejects_the_legacy_database(tmp_path):
    snapshot = snapshot_from(
        tmp_path, VALID_BODY + f"DATABASE_PATH = {str(settings.LEGACY_DATABASE_PATH)!r}\n"
    )
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_database_path(snapshot)
    assert exc_info.value.field_name == "DATABASE_PATH"
    assert "legacy" in exc_info.value.detail


def test_database_path_rejects_config_py_itself(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "DATABASE_PATH = __file__\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_database_path(snapshot)
    assert exc_info.value.field_name == "DATABASE_PATH"


def test_database_path_rejects_a_target_inside_the_repository(tmp_path):
    inside_repo = settings.REPOSITORY_ROOT / "some" / "nested" / "chat.db"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"DATABASE_PATH = {str(inside_repo)!r}\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_database_path(snapshot)
    assert exc_info.value.field_name == "DATABASE_PATH"
    assert "repository" in exc_info.value.detail


def test_database_path_wrong_type_is_reported_as_type(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "DATABASE_PATH = 5\n")
    with pytest.raises(settings.SettingsError) as exc_info:
        settings.build_database_path(snapshot)
    assert exc_info.value.field_name == "DATABASE_PATH"
    assert exc_info.value.kind == "type"


# --- theme: optional, defaulted, bounded invalid-value recovery -------------

def test_unset_tui_theme_defaults_to_dark(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY)
    theme = settings.build_theme(snapshot)
    assert theme.name == "dark"
    assert theme.invalid_value_notice is None


@pytest.mark.parametrize("value", settings.ACCEPTED_TUI_THEMES)
def test_each_accepted_tui_theme_value_is_used_as_is(tmp_path, value):
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"TUI_THEME = {value!r}\n")
    theme = settings.build_theme(snapshot)
    assert theme.name == value
    assert theme.invalid_value_notice is None


def test_an_invalid_tui_theme_falls_back_to_dark_with_a_bounded_notice(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "TUI_THEME = 'purple'\n")
    theme = settings.build_theme(snapshot)
    assert theme.name == "dark"
    assert theme.invalid_value_notice is not None
    assert "TUI_THEME" in theme.invalid_value_notice
    assert "purple" in theme.invalid_value_notice
    for accepted in settings.ACCEPTED_TUI_THEMES:
        assert accepted in theme.invalid_value_notice


def test_a_non_string_tui_theme_also_falls_back_to_dark_with_a_bounded_notice(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "TUI_THEME = 5\n")
    theme = settings.build_theme(snapshot)
    assert theme.name == "dark"
    assert theme.invalid_value_notice is not None
    assert "TUI_THEME" in theme.invalid_value_notice


# --- display names: optional, defaulted, per-field bounded diagnostics ------

def test_unset_display_names_use_documented_defaults(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY)
    names = settings.build_display_name_settings(snapshot)
    assert names.user_name == settings.DEFAULT_USER_DISPLAY_NAME
    assert names.ai_name == settings.DEFAULT_AI_DISPLAY_NAME
    assert names.user_invalid_notice is None
    assert names.ai_invalid_notice is None


def test_valid_display_names_are_used_as_configured(tmp_path):
    snapshot = snapshot_from(
        tmp_path, VALID_BODY + "USER_DISPLAY_NAME = 'Cas'\nAI_DISPLAY_NAME = 'Balthazar'\n",
    )
    names = settings.build_display_name_settings(snapshot)
    assert names.user_name == "Cas"
    assert names.ai_name == "Balthazar"
    assert names.user_invalid_notice is None
    assert names.ai_invalid_notice is None


@pytest.mark.parametrize("field_name,token", [
    ("USER_DISPLAY_NAME", "{{user}}"), ("AI_DISPLAY_NAME", "{{AI}}"),
])
@pytest.mark.parametrize("bad_literal", [
    "''", "'  '", "5", "'a\\nb'", "'" + "x" * 41 + "'",
])
def test_an_invalid_display_name_leaves_that_name_none_with_a_bounded_notice(
    tmp_path, field_name, token, bad_literal,
):
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"{field_name} = {bad_literal}\n")
    names = settings.build_display_name_settings(snapshot)
    name = names.user_name if field_name == "USER_DISPLAY_NAME" else names.ai_name
    notice = names.user_invalid_notice if field_name == "USER_DISPLAY_NAME" else names.ai_invalid_notice
    assert name is None
    assert notice is not None
    assert field_name in notice
    assert token in notice


def test_an_invalid_user_display_name_does_not_affect_a_valid_ai_display_name(tmp_path):
    snapshot = snapshot_from(
        tmp_path, VALID_BODY + "USER_DISPLAY_NAME = ''\nAI_DISPLAY_NAME = 'Balthazar'\n",
    )
    names = settings.build_display_name_settings(snapshot)
    assert names.user_name is None
    assert names.user_invalid_notice is not None
    assert names.ai_name == "Balthazar"
    assert names.ai_invalid_notice is None


def test_display_name_at_the_length_limit_is_valid(tmp_path):
    exactly_max = "x" * settings.DISPLAY_NAME_MAX_LEN
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"USER_DISPLAY_NAME = {exactly_max!r}\n")
    names = settings.build_display_name_settings(snapshot)
    assert names.user_name == exactly_max
    assert names.user_invalid_notice is None


def test_build_settings_carries_display_names_through(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "USER_DISPLAY_NAME = 'Cas'\n")
    built = settings.build_settings(snapshot)
    assert built.display_names.user_name == "Cas"
    assert built.display_names.ai_name == settings.DEFAULT_AI_DISPLAY_NAME


# --- build_settings: all three parts together --------------------------------

def test_build_settings_combines_provider_and_database(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY)
    built = settings.build_settings(snapshot)
    assert built.provider.model == "fixture-model"
    assert built.database_path == settings.DEFAULT_DATABASE_PATH.expanduser().resolve()
    assert built.theme.name == "dark"


def test_build_settings_carries_an_accepted_theme_value_through(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "TUI_THEME = 'light'\n")
    built = settings.build_settings(snapshot)
    assert built.theme.name == "light"
    assert built.theme.invalid_value_notice is None


def test_build_settings_never_mutates_config_py(tmp_path):
    path = tmp_path / "config.py"
    path.write_text(VALID_BODY + "TUI_THEME = 'not-a-real-theme'\n", encoding="utf-8")
    before = path.read_text(encoding="utf-8")
    snapshot = config_loader.load_snapshot(path)
    settings.build_settings(snapshot)
    assert path.read_text(encoding="utf-8") == before


# --- no mutation: this module never touches the filesystem beyond reading ---

def test_building_settings_creates_nothing_on_disk_even_when_accepted(tmp_path):
    target_dir = tmp_path / "would_be_created"
    snapshot = snapshot_from(
        tmp_path, VALID_BODY + f"DATABASE_PATH = {str(target_dir / 'chat.db')!r}\n"
    )
    resolved = settings.build_database_path(snapshot)
    assert resolved == (target_dir / "chat.db").resolve()
    assert not target_dir.exists()


# --- no 2.0 DB_PATH alias is taught anywhere (D-2.0-16) ----------------------

def test_no_2_0_db_path_alias_is_taught_in_settings_module():
    """`db.py`'s own legacy `DB_PATH` constant is untouched and unrelated —
    this only checks the 2.0 package itself never re-reads that spelling
    from a config snapshot as if it were `DATABASE_PATH`.
    """
    source = Path(settings.__file__).read_text(encoding="utf-8")
    assert 'get("DB_PATH")' not in source
    assert "get('DB_PATH')" not in source


def test_no_2_0_db_path_alias_is_taught_in_the_example_bootstrap_section():
    """`config.example.py`'s 2.0 bootstrap portion — everything before the
    v1.9.1 `CHAT_EXPORT_DIR` section starts — must teach `DATABASE_PATH` and
    never offer a `DB_PATH = ...` example line under that heading.
    """
    example_path = settings.REPOSITORY_ROOT / "config.example.py"
    text = example_path.read_text(encoding="utf-8")
    bootstrap_section, _, _ = text.partition("CHAT_EXPORT_DIR")
    assert "DATABASE_PATH" in bootstrap_section
    assert "DB_PATH" not in bootstrap_section


# --- vault category settings: optional, contained, never raising ------------

def test_unset_vault_root_leaves_every_category_unavailable(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY)
    vault = settings.build_vault_settings(snapshot)
    assert vault.root is None
    for category in (vault.user_preferences, vault.personas, vault.traits, vault.first_messages):
        assert category.path is None
        assert category.unavailable_reason is not None


def test_placeholder_vault_root_is_treated_as_unset(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "VAULT_ROOT = 'PLACEHOLDER'\n")
    vault = settings.build_vault_settings(snapshot)
    assert vault.root is None


def test_a_category_dir_inside_vault_root_is_usable(tmp_path):
    vault_root = tmp_path / "vault"
    personas = vault_root / "personas"
    snapshot = snapshot_from(
        tmp_path,
        VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\nPERSONAS_DIR = {str(personas)!r}\n",
    )
    vault = settings.build_vault_settings(snapshot)
    assert vault.root == vault_root.resolve()
    assert vault.personas.path == personas.resolve()
    assert vault.personas.unavailable_reason is None


def test_a_category_dir_outside_vault_root_is_unavailable(tmp_path):
    vault_root = tmp_path / "vault"
    outside = tmp_path / "elsewhere"
    snapshot = snapshot_from(
        tmp_path,
        VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\nPERSONAS_DIR = {str(outside)!r}\n",
    )
    vault = settings.build_vault_settings(snapshot)
    assert vault.personas.path is None
    assert "does not resolve inside" in vault.personas.unavailable_reason


def test_a_category_dir_set_without_vault_root_is_unavailable(tmp_path):
    personas = tmp_path / "personas"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"PERSONAS_DIR = {str(personas)!r}\n")
    vault = settings.build_vault_settings(snapshot)
    assert vault.personas.path is None
    assert "VAULT_ROOT" in vault.personas.unavailable_reason


def test_an_unconfigured_category_is_unavailable_but_others_are_unaffected(tmp_path):
    vault_root = tmp_path / "vault"
    personas = vault_root / "personas"
    snapshot = snapshot_from(
        tmp_path,
        VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\nPERSONAS_DIR = {str(personas)!r}\n",
    )
    vault = settings.build_vault_settings(snapshot)
    assert vault.personas.path is not None
    assert vault.traits.path is None
    assert vault.user_preferences.path is None


def test_user_preferences_dir_is_its_own_2_0_setting_not_prompts_dir(tmp_path):
    """A config.py that still only sets the legacy PROMPTS_DIR must not make
    USER_PREFERENCES_DIR usable — the 2.0 field is its own name."""
    vault_root = tmp_path / "vault"
    prompts = vault_root / "prompts"
    snapshot = snapshot_from(
        tmp_path,
        VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\nPROMPTS_DIR = {str(prompts)!r}\n",
    )
    vault = settings.build_vault_settings(snapshot)
    assert vault.user_preferences.path is None


def test_non_string_category_dir_is_unavailable_not_raising(tmp_path):
    vault_root = tmp_path / "vault"
    snapshot = snapshot_from(
        tmp_path, VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\nTRAITS_DIR = 5\n",
    )
    vault = settings.build_vault_settings(snapshot)
    assert vault.traits.path is None
    assert "must be a string" in vault.traits.unavailable_reason


def test_build_vault_settings_never_raises_and_never_touches_disk(tmp_path):
    vault_root = tmp_path / "does" / "not" / "exist"
    personas = vault_root / "personas"
    snapshot = snapshot_from(
        tmp_path,
        VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\nPERSONAS_DIR = {str(personas)!r}\n",
    )
    vault = settings.build_vault_settings(snapshot)
    assert vault.personas.path == personas.resolve()
    assert not vault_root.exists()


# --- MAIN_CHAT_DIR: shape-only, same containment rule as a vault category ---

def test_unset_main_chat_dir_is_unavailable(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY)
    vault = settings.build_vault_settings(snapshot)
    assert vault.main_chat.path is None
    assert vault.main_chat.unavailable_reason is not None


def test_main_chat_dir_inside_vault_root_is_usable(tmp_path):
    vault_root = tmp_path / "vault"
    main_chat = vault_root / "main"
    snapshot = snapshot_from(
        tmp_path,
        VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\nMAIN_CHAT_DIR = {str(main_chat)!r}\n",
    )
    vault = settings.build_vault_settings(snapshot)
    assert vault.main_chat.path == main_chat.resolve()
    assert vault.main_chat.unavailable_reason is None


def test_main_chat_dir_outside_vault_root_is_unavailable(tmp_path):
    vault_root = tmp_path / "vault"
    outside = tmp_path / "elsewhere"
    snapshot = snapshot_from(
        tmp_path,
        VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\nMAIN_CHAT_DIR = {str(outside)!r}\n",
    )
    vault = settings.build_vault_settings(snapshot)
    assert vault.main_chat.path is None
    assert "does not resolve inside" in vault.main_chat.unavailable_reason


def test_main_chat_dir_set_without_vault_root_is_unavailable(tmp_path):
    main_chat = tmp_path / "main"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"MAIN_CHAT_DIR = {str(main_chat)!r}\n")
    vault = settings.build_vault_settings(snapshot)
    assert vault.main_chat.path is None
    assert "VAULT_ROOT" in vault.main_chat.unavailable_reason


def test_main_chat_dir_is_independent_of_other_vault_categories(tmp_path):
    vault_root = tmp_path / "vault"
    main_chat = vault_root / "main"
    personas = vault_root / "personas"
    snapshot = snapshot_from(
        tmp_path,
        VALID_BODY + f"VAULT_ROOT = {str(vault_root)!r}\nMAIN_CHAT_DIR = {str(main_chat)!r}\n"
        f"PERSONAS_DIR = {str(personas)!r}\n",
    )
    vault = settings.build_vault_settings(snapshot)
    assert vault.main_chat.path is not None
    assert vault.personas.path is not None
    assert vault.traits.path is None


# --- CHAT_EXPORT_DIR: shape-only, independent of VAULT_ROOT -----------------

def test_unset_chat_export_dir_is_unavailable(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY)
    export = settings.build_export_settings(snapshot)
    assert export.path is None
    assert export.unavailable_reason is not None


def test_blank_chat_export_dir_is_unavailable(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "CHAT_EXPORT_DIR = '   '\n")
    export = settings.build_export_settings(snapshot)
    assert export.path is None


def test_placeholder_chat_export_dir_is_unavailable(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "CHAT_EXPORT_DIR = 'PLACEHOLDER'\n")
    export = settings.build_export_settings(snapshot)
    assert export.path is None


def test_chat_export_dir_is_resolved_without_touching_disk(tmp_path):
    destination = tmp_path / "does" / "not" / "exist" / "exports"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"CHAT_EXPORT_DIR = {str(destination)!r}\n")
    export = settings.build_export_settings(snapshot)
    assert export.path == destination.resolve()
    assert export.unavailable_reason is None
    assert not destination.exists()


def test_chat_export_dir_needs_no_vault_root_at_all(tmp_path):
    """Concept.md: "It is independent of VAULT_ROOT" — no VAULT_ROOT set at
    all still leaves CHAT_EXPORT_DIR independently usable."""
    destination = tmp_path / "exports"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"CHAT_EXPORT_DIR = {str(destination)!r}\n")
    export = settings.build_export_settings(snapshot)
    vault = settings.build_vault_settings(snapshot)
    assert export.path == destination.resolve()
    assert vault.root is None


def test_non_string_chat_export_dir_is_unavailable_not_raising(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "CHAT_EXPORT_DIR = 5\n")
    export = settings.build_export_settings(snapshot)
    assert export.path is None
    assert "must be a string" in export.unavailable_reason


# --- model catalogue: listed/limit reused, malformed is bounded -------------

def test_unset_models_is_an_empty_catalogue(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY)
    catalogue = settings.build_model_catalogue(snapshot)
    assert catalogue.entries == ()
    assert catalogue.unavailable_reason is None


def test_models_entries_default_selectable_true_when_listed_unset(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "MODELS = [dict(id='m/one')]\n")
    catalogue = settings.build_model_catalogue(snapshot)
    assert catalogue.entries == (settings.ModelCatalogueEntry(id="m/one", selectable=True),)


def test_models_entry_reads_listed_and_limit(tmp_path):
    snapshot = snapshot_from(
        tmp_path,
        VALID_BODY + "MODELS = [dict(id='m/one', listed=False, limit=128000)]\n",
    )
    catalogue = settings.build_model_catalogue(snapshot)
    entry = catalogue.entry_for("m/one")
    assert entry.selectable is False
    assert entry.context_limit == 128000
    assert catalogue.selectable_entries() == ()


def test_models_preserves_declared_order(tmp_path):
    snapshot = snapshot_from(
        tmp_path, VALID_BODY + "MODELS = [dict(id='b'), dict(id='a')]\n",
    )
    catalogue = settings.build_model_catalogue(snapshot)
    assert [e.id for e in catalogue.entries] == ["b", "a"]


@pytest.mark.parametrize("bad_models", [
    "not-a-list",
    "[dict(id='a')]",  # a string, not an actual list — config_loader freezes real lists only
])
def test_models_wrong_top_level_type_is_malformed(tmp_path, bad_models):
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"MODELS = {bad_models!r}\n")
    catalogue = settings.build_model_catalogue(snapshot)
    assert catalogue.entries == ()
    assert catalogue.unavailable_reason is not None


def test_models_entry_not_a_dict_is_malformed(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "MODELS = ['bare-string-id']\n")
    catalogue = settings.build_model_catalogue(snapshot)
    assert catalogue.unavailable_reason is not None


def test_models_missing_id_is_malformed(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "MODELS = [dict(listed=True)]\n")
    catalogue = settings.build_model_catalogue(snapshot)
    assert catalogue.unavailable_reason is not None


def test_models_blank_id_is_malformed(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "MODELS = [dict(id='   ')]\n")
    catalogue = settings.build_model_catalogue(snapshot)
    assert catalogue.unavailable_reason is not None


def test_models_duplicate_id_is_malformed(tmp_path):
    snapshot = snapshot_from(
        tmp_path, VALID_BODY + "MODELS = [dict(id='a'), dict(id='a')]\n",
    )
    catalogue = settings.build_model_catalogue(snapshot)
    assert catalogue.unavailable_reason is not None


def test_models_non_bool_listed_is_malformed(tmp_path):
    snapshot = snapshot_from(
        tmp_path, VALID_BODY + "MODELS = [dict(id='a', listed='yes')]\n",
    )
    catalogue = settings.build_model_catalogue(snapshot)
    assert catalogue.unavailable_reason is not None


@pytest.mark.parametrize("bad_limit", [0, -1, 1.5, True])
def test_models_invalid_limit_is_malformed(tmp_path, bad_limit):
    snapshot = snapshot_from(
        tmp_path, VALID_BODY + f"MODELS = [dict(id='a', limit={bad_limit!r})]\n",
    )
    catalogue = settings.build_model_catalogue(snapshot)
    assert catalogue.unavailable_reason is not None


def test_malformed_models_never_raises_and_leaves_default_model_untouched(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "MODELS = [dict(id='a'), dict(id='a')]\n")
    built = settings.build_settings(snapshot)
    assert built.provider.model == "fixture-model"
    assert built.models.unavailable_reason is not None


# --- effective-appearance precedence vocabulary (Stage 5 loop 2) -----------

def test_resolve_effective_appearance_with_no_override_uses_the_bootstrap_theme():
    theme = settings.ThemeSettings("light")
    effective = settings.resolve_effective_appearance(theme, None)
    assert effective.name == "light"
    assert effective.source is settings.AppearanceSource.CONFIGURED_DEFAULT


@pytest.mark.parametrize("override", settings.ACCEPTED_TUI_THEMES)
def test_resolve_effective_appearance_with_an_override_wins_over_the_bootstrap_theme(override):
    theme = settings.ThemeSettings("dark" if override == "light" else "light")
    effective = settings.resolve_effective_appearance(theme, override)
    assert effective.name == override
    assert effective.source is settings.AppearanceSource.OVERRIDE


def test_resolve_effective_appearance_never_reimplements_precedence_independently():
    """An override always wins regardless of whether it happens to equal
    the bootstrap value — proves the function reads `override is not None`,
    not `override != theme.name`."""
    theme = settings.ThemeSettings("dark")
    effective = settings.resolve_effective_appearance(theme, "dark")
    assert effective.source is settings.AppearanceSource.OVERRIDE


# --- build_settings: vault and models included -------------------------------

def test_build_settings_includes_vault_and_models(tmp_path):
    snapshot = snapshot_from(tmp_path, VALID_BODY + "MODELS = [dict(id='fixture-model')]\n")
    built = settings.build_settings(snapshot)
    assert built.vault.root is None
    assert built.models.entries == (
        settings.ModelCatalogueEntry(id="fixture-model", selectable=True),
    )


def test_build_settings_includes_chat_export(tmp_path):
    destination = tmp_path / "exports"
    snapshot = snapshot_from(tmp_path, VALID_BODY + f"CHAT_EXPORT_DIR = {str(destination)!r}\n")
    built = settings.build_settings(snapshot)
    assert built.chat_export.path == destination.resolve()
