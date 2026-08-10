"""test_cfc_context.py — cfc/context.py: the shared vault Markdown reader
and the System Instructions plus selection resolver that builds one fresh
`ContextPlan`. Every fixture here is a temporary directory; nothing reads
Cas's live vault.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from cfc import context
from cfc.conversation_types import ContextCategory, ContextSelection
from cfc.settings import VaultCategorySettings, VaultSettings


def category(path: Path | None) -> VaultCategorySettings:
    return VaultCategorySettings(path=path)


def vault_settings(
    tmp_path: Path, *, prefs=None, personas=None, traits=None, first_messages=None,
) -> VaultSettings:
    return VaultSettings(
        root=tmp_path,
        user_preferences=category(prefs),
        personas=category(personas),
        traits=category(traits),
        first_messages=category(first_messages),
    )


def write(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


# --- System Instructions: always available, versioned, fingerprinted -------

def test_system_instructions_is_always_available_and_fingerprinted():
    record = context.system_instructions_record()
    assert record.category is ContextCategory.SYSTEM_INSTRUCTIONS
    assert record.body == context.SYSTEM_INSTRUCTIONS_TEXT
    assert record.character_count == len(context.SYSTEM_INSTRUCTIONS_TEXT)
    assert record.fingerprint == hashlib.sha256(
        context.SYSTEM_INSTRUCTIONS_TEXT.encode("utf-8")
    ).hexdigest()
    assert context.SYSTEM_INSTRUCTIONS_VERSION in record.name


def test_system_instructions_is_stable_across_calls():
    first = context.system_instructions_record()
    second = context.system_instructions_record()
    assert first == second


# --- read_source: the happy path --------------------------------------------

def test_read_source_returns_literal_body_and_fingerprint(tmp_path):
    directory = tmp_path / "personas"
    write(directory, "muse.md", "You are Muse.\n")
    record = context.read_source(ContextCategory.PERSONA, category(directory), "muse.md")
    assert record.name == "muse.md"
    assert record.display_name == "muse"
    assert record.body == "You are Muse.\n"
    assert record.character_count == len("You are Muse.\n")
    assert record.fingerprint == hashlib.sha256("You are Muse.\n".encode("utf-8")).hexdigest()


def test_read_source_display_name_strips_exact_md_suffix(tmp_path):
    directory = tmp_path / "traits"
    write(directory, "Dry Wit.md", "dry\n")
    record = context.read_source(ContextCategory.TRAIT, category(directory), "Dry Wit.md")
    assert record.display_name == "Dry Wit"


# --- read_source: every bad-source class ------------------------------------

def test_read_source_missing_category_directory_is_unavailable():
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_source(ContextCategory.PERSONA, category(None), "muse.md")
    assert exc_info.value.category is ContextCategory.PERSONA
    assert exc_info.value.name == "muse.md"


def test_read_source_nonexistent_file_is_unavailable(tmp_path):
    directory = tmp_path / "personas"
    directory.mkdir()
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_source(ContextCategory.PERSONA, category(directory), "ghost.md")
    assert "does not exist" in exc_info.value.reason


def test_read_source_blank_file_is_unavailable(tmp_path):
    directory = tmp_path / "personas"
    write(directory, "empty.md", "   \n\n  ")
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_source(ContextCategory.PERSONA, category(directory), "empty.md")
    assert "blank" in exc_info.value.reason


def test_read_source_non_utf8_file_is_unavailable(tmp_path):
    directory = tmp_path / "personas"
    directory.mkdir()
    (directory / "bad.md").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_source(ContextCategory.PERSONA, category(directory), "bad.md")
    assert "UTF-8" in exc_info.value.reason


def test_read_source_directory_target_is_unavailable(tmp_path):
    directory = tmp_path / "personas"
    (directory / "notreal.md").mkdir(parents=True)
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_source(ContextCategory.PERSONA, category(directory), "notreal.md")
    assert "regular file" in exc_info.value.reason


def test_read_source_symlink_escape_is_unavailable(tmp_path):
    directory = tmp_path / "personas"
    directory.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    (directory / "link.md").symlink_to(outside)
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_source(ContextCategory.PERSONA, category(directory), "link.md")
    assert "symlink" in exc_info.value.reason


def test_read_source_non_md_file_is_unavailable(tmp_path):
    directory = tmp_path / "personas"
    write(directory, "muse.txt", "text")
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_source(ContextCategory.PERSONA, category(directory), "muse.txt")
    assert ".md" in exc_info.value.reason


def test_read_source_path_traversal_filename_is_unavailable(tmp_path):
    directory = tmp_path / "personas"
    directory.mkdir()
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_source(ContextCategory.PERSONA, category(directory), "../escape.md")
    assert "plain filename" in exc_info.value.reason


def test_read_source_duplicate_display_name_is_unavailable(tmp_path):
    directory = tmp_path / "personas"
    write(directory, "Muse.md", "one")
    write(directory, "Muse.MD", "two")
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_source(ContextCategory.PERSONA, category(directory), "Muse.md")
    assert "display name" in exc_info.value.reason


# --- available_sources: listing, collisions excluded ------------------------

def test_available_sources_lists_unambiguous_files_by_display_name(tmp_path):
    directory = tmp_path / "traits"
    write(directory, "b.md", "b")
    write(directory, "a.md", "a")
    options = context.available_sources(category(directory))
    assert [o.display_name for o in options] == ["a", "b"]
    assert [o.name for o in options] == ["a.md", "b.md"]


def test_available_sources_omits_a_colliding_pair_entirely(tmp_path):
    directory = tmp_path / "traits"
    write(directory, "Kit.md", "one")
    write(directory, "Kit.MD", "two")
    write(directory, "solo.md", "solo")
    options = context.available_sources(category(directory))
    assert [o.display_name for o in options] == ["solo"]


def test_available_sources_with_no_directory_is_empty():
    assert context.available_sources(category(None)) == ()


# --- first message lookup: absent vs unavailable vs usable ------------------

def test_first_message_absent_when_no_companion_file(tmp_path):
    directory = tmp_path / "first_messages"
    directory.mkdir()
    lookup = context.look_up_first_message(category(directory), "muse.md")
    assert lookup.state is context.FirstMessageState.ABSENT
    assert lookup.record is None


def test_first_message_unavailable_when_category_unconfigured():
    """B-2.0-62: an unconfigured directory is not the same fact as "this
    persona has no companion", and carries the settings reason so a caller
    can name the field to correct.
    """
    settings = VaultCategorySettings(unavailable_reason="FIRST_MESSAGES_DIR is not set")
    lookup = context.look_up_first_message(settings, "muse.md")
    assert lookup.state is context.FirstMessageState.UNAVAILABLE
    assert lookup.reason == "FIRST_MESSAGES_DIR is not set"
    assert lookup.record is None


def test_first_message_unavailable_when_category_settings_carry_no_reason():
    """The same state without a settings reason to borrow — cfc still says
    something bounded rather than `None`.
    """
    lookup = context.look_up_first_message(category(None), "muse.md")
    assert lookup.state is context.FirstMessageState.UNAVAILABLE
    assert "no First Messages directory is configured" in lookup.reason


def test_first_message_usable_reads_exact_filename_not_display_name(tmp_path):
    directory = tmp_path / "first_messages"
    write(directory, "muse.md", "Hello, I am Muse.")
    lookup = context.look_up_first_message(category(directory), "muse.md")
    assert lookup.state is context.FirstMessageState.USABLE
    assert lookup.record.body == "Hello, I am Muse."
    assert lookup.record.category is ContextCategory.FIRST_MESSAGE


def test_first_message_unavailable_when_present_but_blank(tmp_path):
    directory = tmp_path / "first_messages"
    write(directory, "muse.md", "   ")
    lookup = context.look_up_first_message(category(directory), "muse.md")
    assert lookup.state is context.FirstMessageState.UNAVAILABLE
    assert "blank" in lookup.reason


def test_first_message_lookup_ignores_display_name_collisions(tmp_path):
    """A First Message is joined by exact filename, not selected from a
    list — a sibling collision in the same directory must not block it."""
    directory = tmp_path / "first_messages"
    write(directory, "Muse.md", "primary")
    write(directory, "Muse.MD", "other")
    lookup = context.look_up_first_message(category(directory), "Muse.md")
    assert lookup.state is context.FirstMessageState.USABLE
    assert lookup.record.body == "primary"


# --- build_context_plan: ordering, optional absence, fail-fast -------------

def test_build_context_plan_with_nothing_selected_still_has_system_instructions(tmp_path):
    vault = vault_settings(tmp_path)
    plan = context.build_context_plan(vault, ContextSelection())
    assert plan.system_instructions.category is ContextCategory.SYSTEM_INSTRUCTIONS
    assert plan.user_preferences is None
    assert plan.persona is None
    assert plan.traits == ()
    assert plan.ordered_sources() == (plan.system_instructions,)


def test_build_context_plan_resolves_full_selection_in_request_order(tmp_path):
    prefs_dir = tmp_path / "prefs"
    personas_dir = tmp_path / "personas"
    traits_dir = tmp_path / "traits"
    write(prefs_dir, "prefs.md", "prefs body")
    write(personas_dir, "muse.md", "persona body")
    write(traits_dir, "dry.md", "dry body")
    write(traits_dir, "warm.md", "warm body")
    vault = vault_settings(tmp_path, prefs=prefs_dir, personas=personas_dir, traits=traits_dir)
    selection = ContextSelection(
        user_preferences="prefs.md", persona="muse.md", traits=("dry.md", "warm.md"),
    )
    plan = context.build_context_plan(vault, selection)
    ordered = plan.ordered_sources()
    assert [s.category for s in ordered] == [
        ContextCategory.SYSTEM_INSTRUCTIONS,
        ContextCategory.USER_PREFERENCES,
        ContextCategory.PERSONA,
        ContextCategory.TRAIT,
        ContextCategory.TRAIT,
    ]
    assert [s.name for s in ordered[3:]] == ["dry.md", "warm.md"]


def test_build_context_plan_preserves_trait_selection_order(tmp_path):
    traits_dir = tmp_path / "traits"
    write(traits_dir, "z.md", "z")
    write(traits_dir, "a.md", "a")
    vault = vault_settings(tmp_path, traits=traits_dir)
    plan = context.build_context_plan(vault, ContextSelection(traits=("z.md", "a.md")))
    assert [t.name for t in plan.traits] == ["z.md", "a.md"]


def test_build_context_plan_raises_on_first_unavailable_selected_source(tmp_path):
    personas_dir = tmp_path / "personas"
    personas_dir.mkdir()
    vault = vault_settings(tmp_path, personas=personas_dir)
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.build_context_plan(vault, ContextSelection(persona="ghost.md"))
    assert exc_info.value.category is ContextCategory.PERSONA


def test_a_fresh_plan_differs_after_a_vault_edit(tmp_path):
    personas_dir = tmp_path / "personas"
    write(personas_dir, "muse.md", "version one")
    vault = vault_settings(tmp_path, personas=personas_dir)
    selection = ContextSelection(persona="muse.md")

    first = context.build_context_plan(vault, selection)
    write(personas_dir, "muse.md", "version two")
    second = context.build_context_plan(vault, selection)

    assert first.persona.body == "version one"
    assert second.persona.body == "version two"
    assert first.persona.fingerprint != second.persona.fingerprint
