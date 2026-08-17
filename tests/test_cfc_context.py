"""test_cfc_context.py — cfc/context.py: the shared vault Markdown reader
and the System Instructions plus selection resolver that builds one fresh
`ContextPlan`. Every fixture here is a temporary directory; nothing reads
Cas's live vault.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from cfc import context
from cfc.conversation_types import ChatKind, ContextCategory, ContextSelection
from cfc.settings import DisplayNameSettings, VaultCategorySettings, VaultSettings

#: Permission bits do not restrict root, which would make the unreadable-
#: directory case below silently readable instead of refused.
_needs_unprivileged = pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="file permission bits do not restrict root",
)


def category(path: Path | None) -> VaultCategorySettings:
    return VaultCategorySettings(path=path)


def vault_settings(
    tmp_path: Path, *, prefs=None, personas=None, traits=None, first_messages=None,
    main_chat=None,
) -> VaultSettings:
    return VaultSettings(
        root=tmp_path,
        user_preferences=category(prefs),
        personas=category(personas),
        traits=category(traits),
        first_messages=category(first_messages),
        main_chat=category(main_chat),
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


# --- {{user}}/{{AI}} substitution: named template sources only -------------

def test_read_source_substitutes_display_name_tokens(tmp_path):
    directory = tmp_path / "prefs"
    write(directory, "p.md", "hello {{user}}, this is {{AI}}")
    names = DisplayNameSettings(user_name="Cas", ai_name="Balthazar")
    record = context.read_source(ContextCategory.USER_PREFERENCES, category(directory), "p.md", names)
    assert record.body == "hello Cas, this is Balthazar"
    assert record.character_count == len(record.body)
    assert record.fingerprint == hashlib.sha256(record.body.encode("utf-8")).hexdigest()


def test_read_source_leaves_tokens_literal_with_no_display_names_given(tmp_path):
    directory = tmp_path / "prefs"
    write(directory, "p.md", "hello {{user}}")
    record = context.read_source(ContextCategory.USER_PREFERENCES, category(directory), "p.md")
    assert record.body == "hello {{user}}"


def test_read_source_leaves_only_the_invalid_names_own_token_literal(tmp_path):
    directory = tmp_path / "prefs"
    write(directory, "p.md", "hello {{user}}, {{AI}}")
    names = DisplayNameSettings(user_name=None, ai_name="Balthazar")
    record = context.read_source(ContextCategory.USER_PREFERENCES, category(directory), "p.md", names)
    assert record.body == "hello {{user}}, Balthazar"


def test_apply_display_names_is_a_single_non_recursive_pass():
    """A configured name containing the other token's literal text is never
    rescanned as a second substitution — the single-walk discipline the flat
    `names.apply` already uses.
    """
    names = DisplayNameSettings(user_name="{{AI}}", ai_name="Balthazar")
    assert context.apply_display_names("{{user}} and {{AI}}", names) == "{{AI}} and Balthazar"


def test_resolve_main_system_prompt_substitutes_display_names(tmp_path):
    directory = tmp_path / "main"
    write(directory, "system prompt.md", "You are {{AI}}, talking to {{user}}.")
    names = DisplayNameSettings(user_name="Cas", ai_name="Balthazar")
    record = context.resolve_main_system_prompt(category(directory), names)
    assert record.body == "You are Balthazar, talking to Cas."


def test_resolve_main_persona_substitutes_display_names(tmp_path):
    directory = tmp_path / "main"
    write(directory, "persona.md", "{{AI}} speaking to {{user}}")
    names = DisplayNameSettings(user_name="Cas", ai_name="Balthazar")
    record = context.resolve_main_persona(category(directory), names)
    assert record.body == "Balthazar speaking to Cas"


def test_look_up_first_message_substitutes_display_names(tmp_path):
    directory = tmp_path / "first_messages"
    write(directory, "muse.md", "Hello {{user}}!")
    names = DisplayNameSettings(user_name="Cas", ai_name="Balthazar")
    lookup = context.look_up_first_message(category(directory), "muse.md", names)
    assert lookup.state is context.FirstMessageState.USABLE
    assert lookup.record.body == "Hello Cas!"


def test_read_attachment_never_substitutes_display_name_tokens(tmp_path):
    write(tmp_path, "note.md", "hello {{user}}")
    record = context.read_attachment(tmp_path, "note.md")
    assert record.body == "hello {{user}}"


def test_build_context_plan_substitutes_every_named_source_but_not_attachments(tmp_path):
    write(tmp_path / "prefs", "p.md", "prefs for {{user}}")
    write(tmp_path / "personas", "muse.md", "persona of {{AI}}")
    write(tmp_path / "traits", "warm.md", "warm with {{user}}")
    write(tmp_path, "note.md", "attachment for {{user}}")
    vault = vault_settings(
        tmp_path, prefs=tmp_path / "prefs", personas=tmp_path / "personas",
        traits=tmp_path / "traits",
    )
    selection = ContextSelection(
        user_preferences="p.md", persona="muse.md", traits=("warm.md",),
        attachments=("note.md",), model="fixture-model",
    )
    names = DisplayNameSettings(user_name="Cas", ai_name="Balthazar")
    plan = context.build_context_plan(vault, selection, ChatKind.ORDINARY, names)
    assert plan.user_preferences.body == "prefs for Cas"
    assert plan.persona.body == "persona of Balthazar"
    assert plan.traits[0].body == "warm with Cas"
    assert plan.attachments[0].body == "attachment for {{user}}"


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


# --- category_readiness: doctor's shared-with-Context readiness rules ------

def test_category_readiness_unavailable_when_unconfigured():
    settings_obj = VaultCategorySettings(unavailable_reason="TRAITS_DIR is not set")
    readiness = context.category_readiness(settings_obj)
    assert readiness.state is context.CategoryReadinessState.UNAVAILABLE
    assert readiness.reason == "TRAITS_DIR is not set"
    assert readiness.count is None


def test_category_readiness_unavailable_with_no_settings_object_at_all():
    readiness = context.category_readiness(None)
    assert readiness.state is context.CategoryReadinessState.UNAVAILABLE
    assert readiness.reason is not None


def test_category_readiness_error_when_configured_directory_is_missing(tmp_path):
    directory = tmp_path / "does_not_exist"
    readiness = context.category_readiness(category(directory))
    assert readiness.state is context.CategoryReadinessState.ERROR
    assert str(directory) in readiness.reason
    assert not directory.exists()


def test_category_readiness_error_when_configured_path_is_a_file(tmp_path):
    path = tmp_path / "not_a_directory"
    path.write_text("x", encoding="utf-8")
    readiness = context.category_readiness(category(path))
    assert readiness.state is context.CategoryReadinessState.ERROR
    assert "not a directory" in readiness.reason


@_needs_unprivileged
def test_category_readiness_error_when_directory_is_unreadable(tmp_path):
    directory = tmp_path / "locked"
    directory.mkdir()
    write(directory, "one.md", "one")
    directory.chmod(0o000)
    try:
        readiness = context.category_readiness(category(directory))
        assert readiness.state is context.CategoryReadinessState.ERROR
        assert readiness.reason is not None
    finally:
        directory.chmod(0o755)


def test_category_readiness_ready_empty_when_directory_has_no_selectable_files(tmp_path):
    directory = tmp_path / "empty"
    directory.mkdir()
    readiness = context.category_readiness(category(directory))
    assert readiness.state is context.CategoryReadinessState.READY
    assert readiness.count == 0


def test_category_readiness_ready_counts_selectable_files(tmp_path):
    directory = tmp_path / "traits"
    write(directory, "a.md", "a")
    write(directory, "b.md", "b")
    readiness = context.category_readiness(category(directory))
    assert readiness.state is context.CategoryReadinessState.READY
    assert readiness.count == 2


def test_category_readiness_count_matches_available_sources_not_raw_entries(tmp_path):
    """A colliding pair is excluded from both `available_sources` and this
    count — pinning that doctor and Context read the exact same fact."""
    directory = tmp_path / "traits"
    write(directory, "Kit.md", "one")
    write(directory, "Kit.MD", "two")
    write(directory, "solo.md", "solo")
    readiness = context.category_readiness(category(directory))
    assert readiness.state is context.CategoryReadinessState.READY
    assert readiness.count == len(context.available_sources(category(directory)))
    assert readiness.count == 1


def test_category_readiness_never_creates_or_repairs_a_directory(tmp_path):
    directory = tmp_path / "does_not_exist"
    context.category_readiness(category(directory))
    assert not directory.exists()


def test_category_readiness_never_exposes_a_filename_or_body(tmp_path):
    directory = tmp_path / "traits"
    write(directory, "secret-name.md", "secret body")
    readiness = context.category_readiness(category(directory))
    assert "secret-name" not in repr(readiness)
    assert "secret body" not in repr(readiness)


# --- Main's fixed profile bundle: system prompt.md, persona.md, first
# --- message.md (Stage 5 loop 3) --------------------------------------------

def test_resolve_main_system_prompt_reads_the_fixed_filename(tmp_path):
    directory = tmp_path / "main"
    write(directory, "system prompt.md", "You are Main.")
    record = context.resolve_main_system_prompt(category(directory))
    assert record.category is ContextCategory.MAIN_SYSTEM_PROMPT
    assert record.name == "system prompt.md"
    assert record.body == "You are Main."


def test_resolve_main_persona_reads_the_fixed_filename(tmp_path):
    directory = tmp_path / "main"
    write(directory, "persona.md", "Main's persona.")
    record = context.resolve_main_persona(category(directory))
    assert record.category is ContextCategory.MAIN_PERSONA
    assert record.name == "persona.md"


def test_resolve_main_first_message_reads_the_fixed_filename(tmp_path):
    directory = tmp_path / "main"
    write(directory, "first message.md", "Hello from Main.")
    record = context.resolve_main_first_message(category(directory))
    assert record.category is ContextCategory.FIRST_MESSAGE
    assert record.body == "Hello from Main."


def test_main_profile_reader_unavailable_when_category_unconfigured():
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.resolve_main_system_prompt(category(None))
    assert "MAIN_CHAT_DIR" in exc_info.value.reason


def test_main_profile_reader_unavailable_when_file_missing(tmp_path):
    directory = tmp_path / "main"
    directory.mkdir()
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.resolve_main_persona(category(directory))
    assert "does not exist" in exc_info.value.reason


def test_main_profile_reader_unavailable_when_blank(tmp_path):
    directory = tmp_path / "main"
    write(directory, "persona.md", "   ")
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.resolve_main_persona(category(directory))
    assert "blank" in exc_info.value.reason


def test_main_profile_reader_unavailable_when_symlinked(tmp_path):
    directory = tmp_path / "main"
    directory.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    (directory / "system prompt.md").symlink_to(outside)
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.resolve_main_system_prompt(category(directory))
    assert "symlink" in exc_info.value.reason


def test_main_profile_reader_unavailable_when_not_utf8(tmp_path):
    directory = tmp_path / "main"
    directory.mkdir()
    (directory / "system prompt.md").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.resolve_main_system_prompt(category(directory))
    assert "UTF-8" in exc_info.value.reason


def test_main_profile_reader_unavailable_when_not_a_regular_file(tmp_path):
    directory = tmp_path / "main"
    (directory / "persona.md").mkdir(parents=True)
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.resolve_main_persona(category(directory))
    assert "regular file" in exc_info.value.reason


def test_resolve_main_creation_bundle_reads_all_three_in_order(tmp_path):
    directory = tmp_path / "main"
    write(directory, "system prompt.md", "sp")
    write(directory, "persona.md", "p")
    write(directory, "first message.md", "fm")
    system_prompt, persona, first_message = context.resolve_main_creation_bundle(category(directory))
    assert (system_prompt.body, persona.body, first_message.body) == ("sp", "p", "fm")


def test_resolve_main_creation_bundle_names_the_first_bad_file(tmp_path):
    """Concept.md: "The first bad fixed file is named with its precise
    condition" — system prompt.md, then persona.md, then first message.md,
    in that fixed order."""
    directory = tmp_path / "main"
    write(directory, "system prompt.md", "sp")
    # persona.md missing entirely; first message.md is fine
    write(directory, "first message.md", "fm")
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.resolve_main_creation_bundle(category(directory))
    assert exc_info.value.category is ContextCategory.MAIN_PERSONA


# --- attachments: discovery and reading (Stage 5 loop 3) --------------------

def test_discover_attachments_lists_md_files_by_vault_relative_path(tmp_path):
    write(tmp_path, "notes.md", "n")
    write(tmp_path / "sub", "deep.md", "d")
    write(tmp_path, "ignore.txt", "not markdown")
    options = context.discover_attachments(tmp_path)
    assert sorted(o.name for o in options) == ["notes.md", "sub/deep.md"]
    assert all(o.name == o.display_name for o in options)


def test_discover_attachments_excludes_symlinked_files(tmp_path):
    outside = tmp_path.parent / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    write(tmp_path, "real.md", "real")
    (tmp_path / "link.md").symlink_to(outside)
    options = context.discover_attachments(tmp_path)
    assert [o.name for o in options] == ["real.md"]


def test_discover_attachments_does_not_descend_into_symlinked_directories(tmp_path):
    outside_dir = tmp_path.parent / "outside_dir"
    write(outside_dir, "secret.md", "secret")
    (tmp_path / "linked").symlink_to(outside_dir)
    write(tmp_path, "real.md", "real")
    options = context.discover_attachments(tmp_path)
    assert [o.name for o in options] == ["real.md"]


def test_discover_attachments_prunes_a_hidden_directory_before_descent(tmp_path):
    write(tmp_path / ".obsidian", "workspace.md", "hidden")
    write(tmp_path, "real.md", "real")
    options = context.discover_attachments(tmp_path)
    assert [o.name for o in options] == ["real.md"]


def test_discover_attachments_never_scans_inside_a_hidden_directory(tmp_path, monkeypatch):
    """Proves the hidden directory is pruned from `os.walk`'s own descent
    (W-2.0-73) rather than merely filtered out of the result afterwards: a
    tool working directory like `.git` is often the single largest and
    slowest-to-scan subtree in a real vault, and every entry beneath it
    must go unstatted, not just unlisted.
    """
    hidden = tmp_path / ".git"
    write(hidden, "config.md", "never read")
    write(tmp_path, "real.md", "real")

    real_scandir = os.scandir
    visited: list[str] = []

    def spying_scandir(path="."):
        visited.append(os.fspath(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", spying_scandir)
    options = context.discover_attachments(tmp_path)

    assert [o.name for o in options] == ["real.md"]
    assert str(hidden) not in visited


def test_discover_attachments_with_no_vault_root_is_empty():
    assert context.discover_attachments(None) == ()


def test_discover_attachments_with_empty_vault_root_is_empty(tmp_path):
    assert context.discover_attachments(tmp_path) == ()


def test_discover_attachments_raises_when_configured_root_is_missing(tmp_path):
    """B-2.0-83: a *configured* `VAULT_ROOT` that does not exist on disk
    must not read back as the same empty tuple an honestly empty vault
    returns — the misconfiguration has to be a visible, bounded failure
    naming `VAULT_ROOT`, distinct from `vault_root=None` (unconfigured,
    still legitimately empty above).
    """
    missing = tmp_path / "does_not_exist"
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.discover_attachments(missing)
    assert exc_info.value.category is ContextCategory.ATTACHMENT
    assert exc_info.value.name == "VAULT_ROOT"
    assert str(missing) in exc_info.value.reason


def test_discover_attachments_raises_when_configured_root_is_a_file(tmp_path):
    not_a_directory = tmp_path / "not_a_directory"
    not_a_directory.write_text("x", encoding="utf-8")
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.discover_attachments(not_a_directory)
    assert "not a directory" in exc_info.value.reason


@_needs_unprivileged
def test_discover_attachments_raises_when_configured_root_is_unreadable(tmp_path):
    directory = tmp_path / "locked"
    directory.mkdir()
    write(directory, "one.md", "one")
    directory.chmod(0o000)
    try:
        with pytest.raises(context.SourceUnavailable) as exc_info:
            context.discover_attachments(directory)
        assert exc_info.value.category is ContextCategory.ATTACHMENT
        assert exc_info.value.name == "VAULT_ROOT"
    finally:
        directory.chmod(0o755)


@_needs_unprivileged
def test_discover_attachments_raises_when_an_unreadable_subtree_is_found(tmp_path):
    """A missing/unreadable *subtree* is a bounded failure exactly like a
    missing/unreadable root (Concept.md: "If VAULT_ROOT becomes unavailable
    or the walk itself fails, the picker reports that bounded failure...
    it does not show a partial list as if discovery completed normally") —
    a real sibling file elsewhere must not make the failure disappear as a
    partial, silently-truncated result.
    """
    write(tmp_path, "real.md", "real")
    locked = tmp_path / "locked"
    locked.mkdir()
    write(locked, "hidden.md", "hidden")
    locked.chmod(0o000)
    try:
        with pytest.raises(context.SourceUnavailable) as exc_info:
            context.discover_attachments(tmp_path)
        assert exc_info.value.category is ContextCategory.ATTACHMENT
        assert exc_info.value.name == "VAULT_ROOT"
    finally:
        locked.chmod(0o755)


def test_read_attachment_returns_literal_body_and_fingerprint(tmp_path):
    write(tmp_path / "notes", "idea.md", "an idea\n")
    record = context.read_attachment(tmp_path, "notes/idea.md")
    assert record.category is ContextCategory.ATTACHMENT
    assert record.name == "notes/idea.md"
    assert record.display_name == "notes/idea.md"
    assert record.body == "an idea\n"


def test_read_attachment_canonicalizes_redundant_separators_to_one_identity(tmp_path):
    write(tmp_path / "notes", "idea.md", "an idea\n")
    record = context.read_attachment(tmp_path, "notes//idea.md")
    assert record.name == "notes/idea.md"
    assert record.display_name == "notes/idea.md"


def test_read_attachment_unavailable_with_no_vault_root():
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_attachment(None, "notes.md")
    assert "VAULT_ROOT" in exc_info.value.reason


def test_read_attachment_rejects_traversal(tmp_path):
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_attachment(tmp_path, "../escape.md")
    assert "contained" in exc_info.value.reason


def test_read_attachment_rejects_absolute_path(tmp_path):
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_attachment(tmp_path, "/etc/passwd.md")
    assert "contained" in exc_info.value.reason


def test_read_attachment_rejects_non_md_file(tmp_path):
    write(tmp_path, "notes.txt", "text")
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_attachment(tmp_path, "notes.txt")
    assert ".md" in exc_info.value.reason


def test_read_attachment_rejects_symlink(tmp_path):
    outside = tmp_path.parent / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    (tmp_path / "link.md").symlink_to(outside)
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_attachment(tmp_path, "link.md")
    assert "symlink" in exc_info.value.reason


def test_read_attachment_rejects_a_symlinked_ancestor_directory(tmp_path):
    outside_dir = tmp_path.parent / "outside_dir"
    write(outside_dir, "secret.md", "secret")
    (tmp_path / "linked").symlink_to(outside_dir)
    with pytest.raises(context.SourceUnavailable):
        context.read_attachment(tmp_path, "linked/secret.md")


def test_read_attachment_rejects_missing_file(tmp_path):
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_attachment(tmp_path, "ghost.md")
    assert "does not exist" in exc_info.value.reason


def test_read_attachment_rejects_a_directory_target(tmp_path):
    (tmp_path / "notreal.md").mkdir()
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_attachment(tmp_path, "notreal.md")
    assert "regular file" in exc_info.value.reason


def test_read_attachment_rejects_blank_content(tmp_path):
    write(tmp_path, "empty.md", "   ")
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_attachment(tmp_path, "empty.md")
    assert "blank" in exc_info.value.reason


def test_read_attachment_rejects_non_utf8(tmp_path):
    (tmp_path / "bad.md").write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.read_attachment(tmp_path, "bad.md")
    assert "UTF-8" in exc_info.value.reason


def test_resolve_attachments_reads_in_stored_order(tmp_path):
    write(tmp_path, "a.md", "a-body")
    write(tmp_path, "b.md", "b-body")
    records = context.resolve_attachments(tmp_path, ("b.md", "a.md"))
    assert [r.body for r in records] == ["b-body", "a-body"]


def test_resolve_attachments_raises_on_first_unusable(tmp_path):
    write(tmp_path, "a.md", "a-body")
    with pytest.raises(context.SourceUnavailable) as exc_info:
        context.resolve_attachments(tmp_path, ("a.md", "ghost.md"))
    assert exc_info.value.name == "ghost.md"


# --- build_context_plan: Main profile and attachments (Stage 5 loop 3) -----

def test_build_context_plan_for_main_resolves_profile_before_shared_selection(tmp_path):
    main_dir = tmp_path / "main"
    write(main_dir, "system prompt.md", "sp body")
    write(main_dir, "persona.md", "p body")
    vault = vault_settings(tmp_path, main_chat=main_dir)
    plan = context.build_context_plan(vault, ContextSelection(), kind=ChatKind.MAIN)
    assert plan.main_system_prompt.body == "sp body"
    assert plan.main_persona.body == "p body"
    ordered = plan.ordered_sources()
    assert [s.category for s in ordered] == [
        ContextCategory.SYSTEM_INSTRUCTIONS,
        ContextCategory.MAIN_SYSTEM_PROMPT,
        ContextCategory.MAIN_PERSONA,
    ]


def test_build_context_plan_for_ordinary_never_resolves_main_profile(tmp_path):
    vault = vault_settings(tmp_path, main_chat=None)
    plan = context.build_context_plan(vault, ContextSelection())
    assert plan.main_system_prompt is None
    assert plan.main_persona is None


def test_build_context_plan_appends_attachments_last_and_excludes_them_from_ordered_sources(tmp_path):
    write(tmp_path, "attach.md", "attachment body")
    vault = vault_settings(tmp_path)
    selection = ContextSelection(attachments=("attach.md",))
    plan = context.build_context_plan(vault, selection)
    assert plan.attachments[0].body == "attachment body"
    assert plan.attachments[0].category is ContextCategory.ATTACHMENT
    assert ContextCategory.ATTACHMENT not in [s.category for s in plan.ordered_sources()]
    assert plan.all_sources()[-1] is plan.attachments[0]


def test_context_plan_to_manifest_never_carries_a_body(tmp_path):
    write(tmp_path, "attach.md", "attachment body")
    vault = vault_settings(tmp_path)
    plan = context.build_context_plan(vault, ContextSelection(attachments=("attach.md",)))
    manifest = plan.to_manifest()
    assert manifest[-1].category is ContextCategory.ATTACHMENT
    assert manifest[-1].name == "attach.md"
    assert not any(hasattr(entry, "body") for entry in manifest)


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
