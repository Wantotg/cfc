"""test_cfc_chat_export.py — cfc/chat_export.py: pure Markdown rendering
plus safe, atomic publication to a configured destination directory. Every
destination lives under `tmp_path`; nothing here touches SQLite, the vault,
the provider, or a real `CHAT_EXPORT_DIR`.
"""
from __future__ import annotations

import datetime
import os

import pytest

from cfc import chat_export
from cfc.conversation_types import (
    CancelledOutcome,
    Chat,
    ChatId,
    ChatKind,
    CompletedOutcome,
    ContextCategory,
    ContextManifestEntry,
    ConversationSnapshot,
    FailedOutcome,
    FailureEvidence,
    FailureKind,
    Message,
    MessageId,
    OpeningMessage,
    Role,
    Turn,
    TurnId,
    Usage,
)


def aware(offset_seconds: int = 0) -> datetime.datetime:
    base = datetime.datetime(2026, 8, 9, 12, 0, 0, tzinfo=datetime.timezone.utc)
    return base + datetime.timedelta(seconds=offset_seconds)


def make_chat(*, kind=ChatKind.ORDINARY, title="My Chat") -> Chat:
    return Chat(id=ChatId.new(), kind=kind, title=title,
                created_at=aware(), updated_at=aware())


def make_opening(content="Hello.") -> OpeningMessage:
    return OpeningMessage(source_name="first message.md", content=content,
                           created_at=aware(), fingerprint="opening-fp")


def user_message(chat_id, turn_id, content="q") -> Message:
    return Message(id=MessageId.new(), chat_id=chat_id, turn_id=turn_id, turn_position=0,
                   role=Role.USER, content=content, created_at=aware())


def assistant_message(chat_id, turn_id, content="a") -> Message:
    return Message(id=MessageId.new(), chat_id=chat_id, turn_id=turn_id, turn_position=1,
                   role=Role.ASSISTANT, content=content, created_at=aware(1))


def completed_turn(chat_id, position, *, user="q", assistant="a", usage=None, manifest=()):
    turn_id = TurnId.new()
    turn = Turn(id=turn_id, chat_id=chat_id, position=position, model="fixture-model",
                started_at=aware(), finished_at=aware(2), outcome=CompletedOutcome(usage=usage),
                context_manifest=manifest)
    return turn, [user_message(chat_id, turn_id, user), assistant_message(chat_id, turn_id, assistant)]


def failed_turn(chat_id, position, *, user="q", reason="boom"):
    turn_id = TurnId.new()
    evidence = FailureEvidence(FailureKind.RESPONDER, reason)
    turn = Turn(id=turn_id, chat_id=chat_id, position=position, model="fixture-model",
                started_at=aware(), finished_at=aware(2), outcome=FailedOutcome(evidence))
    return turn, [user_message(chat_id, turn_id, user)]


def interrupted_turn(chat_id, position, *, user="q", reason="cfc restarted while this turn was active"):
    turn_id = TurnId.new()
    evidence = FailureEvidence(FailureKind.INTERRUPTED, reason)
    turn = Turn(id=turn_id, chat_id=chat_id, position=position, model="fixture-model",
                started_at=aware(), finished_at=aware(2), outcome=FailedOutcome(evidence))
    return turn, [user_message(chat_id, turn_id, user)]


def cancelled_turn(chat_id, position, *, user="q"):
    turn_id = TurnId.new()
    turn = Turn(id=turn_id, chat_id=chat_id, position=position, model="fixture-model",
                started_at=aware(), finished_at=aware(2), outcome=CancelledOutcome())
    return turn, [user_message(chat_id, turn_id, user)]


def active_turn(chat_id, position, *, user="q"):
    turn_id = TurnId.new()
    turn = Turn(id=turn_id, chat_id=chat_id, position=position, model="fixture-model",
                started_at=aware())
    return turn, [user_message(chat_id, turn_id, user)]


def build_snapshot(chat_id, turn_pairs) -> ConversationSnapshot:
    turns = tuple(t for t, _ in turn_pairs)
    messages = tuple(m for _, msgs in turn_pairs for m in msgs)
    return ConversationSnapshot(chat_id=chat_id, turns=turns, messages=messages)


# --- render_markdown: exact readable content ---------------------------

def test_render_includes_export_metadata():
    chat = make_chat(title="My Chat")
    snapshot = build_snapshot(chat.id, [])
    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())

    assert chat_export.EXPORT_FORMAT_VERSION in body
    assert chat.id.value in body
    assert "chat kind: ordinary" in body
    assert "title: My Chat" in body
    assert "opening: none" in body


def test_export_format_version_is_v2():
    assert chat_export.EXPORT_FORMAT_VERSION == "v2"


def test_render_includes_the_frozen_opening_before_any_turn():
    chat = make_chat()
    opening = make_opening("Hello, I am Main.")
    turn, msgs = completed_turn(chat.id, 0)
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, opening, snapshot, exported_at=aware())

    opening_index = body.index("Hello, I am Main.")
    turn_index = body.index("## Turn 0")
    assert opening_index < turn_index
    assert "opening: first message.md" in body


def test_render_includes_literal_user_and_assistant_content():
    chat = make_chat()
    turn, msgs = completed_turn(chat.id, 0, user="what is cfc?", assistant="a local AI workspace")
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())

    assert "what is cfc?" in body
    assert "a local AI workspace" in body


def test_render_marks_a_failed_turn_with_no_assistant_reply():
    chat = make_chat()
    turn, msgs = failed_turn(chat.id, 0, reason="connection refused")
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())

    assert "status: failed (connection refused)" in body


def test_render_marks_an_interrupted_turn_distinctly_from_failed():
    """B-2.0-79: `FailureKind.INTERRUPTED` gets its own status word, not
    `failed` — the export contract distinguishes failed, cancelled, and
    interrupted turns, and the reason text alone was not enough.
    """
    chat = make_chat()
    turn, msgs = interrupted_turn(chat.id, 0)
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())

    assert "status: interrupted (cfc restarted while this turn was active)" in body
    assert "status: failed" not in body


def test_render_marks_a_cancelled_turn():
    chat = make_chat()
    turn, msgs = cancelled_turn(chat.id, 0)
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())

    assert "status: cancelled" in body


def test_render_marks_an_active_turn():
    chat = make_chat()
    turn, msgs = active_turn(chat.id, 0)
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())

    assert "status: active" in body


def test_render_reports_model_and_full_usage():
    chat = make_chat()
    usage = Usage(input_tokens=10, output_tokens=5, total_tokens=15)
    turn, msgs = completed_turn(chat.id, 0, usage=usage)
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())

    assert "model: fixture-model" in body
    assert "usage: input 10, output 5, total 15" in body


def test_render_reports_partial_usage_as_not_reported():
    chat = make_chat()
    usage = Usage(input_tokens=10)
    turn, msgs = completed_turn(chat.id, 0, usage=usage)
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())

    assert "usage: input 10, output not reported, total not reported" in body


def test_render_reports_zero_usage_explicitly_not_as_not_reported():
    chat = make_chat()
    usage = Usage(input_tokens=0, output_tokens=0, total_tokens=0)
    turn, msgs = completed_turn(chat.id, 0, usage=usage)
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())

    assert "usage: input 0, output 0, total 0" in body


def test_render_reports_no_usage_at_all_as_not_reported():
    chat = make_chat()
    turn, msgs = completed_turn(chat.id, 0, usage=None)
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())

    assert "usage: not reported" in body


def test_render_reports_ordered_provenance_without_a_source_body():
    chat = make_chat()
    manifest = (
        ContextManifestEntry(category=ContextCategory.SYSTEM_INSTRUCTIONS, name="sys",
                              order=0, character_count=42, fingerprint="sysfp"),
        ContextManifestEntry(category=ContextCategory.ATTACHMENT, name="notes/a.md",
                              order=1, character_count=7, fingerprint="attachfp"),
    )
    turn, msgs = completed_turn(chat.id, 0, manifest=manifest)
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())

    assert "system_instructions: sys" in body
    assert "attachment: notes/a.md" in body
    assert "attachfp" in body
    assert "secret attachment body" not in body  # never copied in


def test_render_provenance_is_one_valid_nested_markdown_list():
    """D-2.0-75: every metadata line in a turn's block, `context:` included,
    shares the same `-` marker, and a non-empty manifest's own entries are
    indented as a proper nested sub-list under `- context:` rather than a
    bare unlisted line that split one list into two.
    """
    chat = make_chat()
    manifest = (
        ContextManifestEntry(category=ContextCategory.SYSTEM_INSTRUCTIONS, name="sys",
                              order=0, character_count=42, fingerprint="sysfp"),
        ContextManifestEntry(category=ContextCategory.ATTACHMENT, name="notes/a.md",
                              order=1, character_count=7, fingerprint="attachfp"),
    )
    turn, msgs = completed_turn(chat.id, 0, manifest=manifest)
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())
    lines = body.splitlines()

    model_index = lines.index("- model: fixture-model")
    assert lines[model_index + 1].startswith("- status:")
    assert lines[model_index + 2].startswith("- usage:")
    context_index = model_index + 3
    assert lines[context_index] == "- context:"
    assert lines[context_index + 1] == (
        "  - system_instructions: sys (42 chars, fingerprint sysfp)"
    )
    assert lines[context_index + 2] == (
        "  - attachment: notes/a.md (7 chars, fingerprint attachfp)"
    )
    assert lines[context_index + 3] == ""  # the list ends cleanly before the next section


def test_render_with_no_context_manifest_says_none_as_a_bulleted_line():
    chat = make_chat()
    turn, msgs = completed_turn(chat.id, 0, manifest=())
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())

    assert "- context: none" in body.splitlines()


def test_render_main_chat_kind_is_literal():
    chat = make_chat(kind=ChatKind.MAIN, title="Main")
    snapshot = build_snapshot(chat.id, [])
    body = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())
    assert "chat kind: main" in body


def test_render_is_deterministic_given_the_same_inputs():
    chat = make_chat()
    turn, msgs = completed_turn(chat.id, 0)
    snapshot = build_snapshot(chat.id, [(turn, msgs)])
    first = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())
    second = chat_export.render_markdown(chat, None, snapshot, exported_at=aware())
    assert first == second


# --- validate_destination: bounded refusals, no filesystem mutation --------

def test_validate_destination_unset_is_unusable():
    with pytest.raises(chat_export.DestinationUnusable) as exc_info:
        chat_export.validate_destination(None)
    assert "CHAT_EXPORT_DIR" in str(exc_info.value)


def test_validate_destination_missing_is_unusable(tmp_path):
    missing = tmp_path / "does_not_exist"
    with pytest.raises(chat_export.DestinationUnusable):
        chat_export.validate_destination(missing)
    assert not missing.exists()


def test_validate_destination_a_file_is_unusable(tmp_path):
    target = tmp_path / "not_a_directory"
    target.write_text("x", encoding="utf-8")
    with pytest.raises(chat_export.DestinationUnusable) as exc_info:
        chat_export.validate_destination(target)
    assert "not a directory" in str(exc_info.value)


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                     reason="file permission bits do not restrict root")
def test_validate_destination_unwritable_is_unusable(tmp_path):
    directory = tmp_path / "locked"
    directory.mkdir()
    directory.chmod(0o500)
    try:
        with pytest.raises(chat_export.DestinationUnusable):
            chat_export.validate_destination(directory)
    finally:
        directory.chmod(0o700)


def test_validate_destination_never_creates_anything(tmp_path):
    missing = tmp_path / "gone"
    with pytest.raises(chat_export.DestinationUnusable):
        chat_export.validate_destination(missing)
    assert list(tmp_path.iterdir()) == []


# --- export_chat: atomic publication, naming, collisions -------------------

def test_export_chat_publishes_a_readable_file_and_returns_its_path(tmp_path):
    chat = make_chat(title="My First Chat!")
    turn, msgs = completed_turn(chat.id, 0, user="hi", assistant="hello")
    snapshot = build_snapshot(chat.id, [(turn, msgs)])

    path = chat_export.export_chat(tmp_path, chat, None, snapshot)

    assert path.exists()
    assert path.parent == tmp_path
    content = path.read_text(encoding="utf-8")
    assert "hello" in content


def test_export_chat_filename_is_filesystem_safe_and_carries_kind_title_and_id(tmp_path):
    chat = make_chat(title="Weird / Title *?")
    snapshot = build_snapshot(chat.id, [])

    path = chat_export.export_chat(tmp_path, chat, None, snapshot)

    assert chat.id.value in path.name
    assert "ordinary" in path.name
    assert "/" not in path.name.replace(str(tmp_path), "")
    for forbidden in "*?\"<>|":
        assert forbidden not in path.name


def test_export_chat_never_overwrites_and_advances_a_numeric_suffix(tmp_path):
    chat = make_chat()
    snapshot = build_snapshot(chat.id, [])
    fixed_now = aware()

    first, first_fd = chat_export._reserve_destination(
        tmp_path, chat_export._export_filename("ordinary", chat.title, chat.id.value, fixed_now),
    )
    os.close(first_fd)
    first.write_text("existing export, must not be touched", encoding="utf-8")

    second, second_fd = chat_export._reserve_destination(
        tmp_path, chat_export._export_filename("ordinary", chat.title, chat.id.value, fixed_now),
    )
    os.close(second_fd)
    assert second != first
    assert second.stem.endswith("-2")
    second.write_text("second export", encoding="utf-8")

    assert first.read_text(encoding="utf-8") == "existing export, must not be touched"


def test_export_chat_filename_uses_local_time_metadata_matches_same_instant(tmp_path):
    """B-2.0-74: one timezone-aware local instant feeds both the filename
    (its local wall-clock form) and the document metadata (that exact
    instant, with its offset) — a fixed non-UTC offset here proves the
    filename is not silently converted to UTC first.
    """
    chat = make_chat()
    snapshot = build_snapshot(chat.id, [])
    fixed = datetime.datetime(
        2026, 8, 16, 23, 30, 45, tzinfo=datetime.timezone(datetime.timedelta(hours=5, minutes=30)),
    )

    path = chat_export.export_chat(tmp_path, chat, None, snapshot, now=fixed)

    assert path.name.startswith("20260816T233045-")  # local wall clock, not shifted to UTC
    content = path.read_text(encoding="utf-8")
    assert f"export time: {fixed.isoformat()}" in content
    assert "+05:30" in content


def test_export_chat_repeated_local_hour_advances_a_numeric_suffix(tmp_path):
    """The same local wall-clock second, requested twice for the same chat
    (e.g. two exports in the same second, or a clock that repeats across a
    DST fold), advances the suffix rather than colliding.
    """
    chat = make_chat()
    snapshot = build_snapshot(chat.id, [])
    fixed = datetime.datetime(2026, 8, 16, 10, 0, 0, tzinfo=datetime.timezone.utc)

    first = chat_export.export_chat(tmp_path, chat, None, snapshot, now=fixed)
    second = chat_export.export_chat(tmp_path, chat, None, snapshot, now=fixed)

    assert first != second
    assert second.stem.endswith("-2")
    assert first.exists() and second.exists()


def test_export_chat_racing_creator_gets_a_later_suffix_not_overwritten(tmp_path, monkeypatch):
    """B-2.0-78: a competing writer that claims the exact target name in
    the instant between this invocation choosing it and claiming it must
    not have its file silently replaced by `os.replace` — either this
    invocation gets a later owned suffix, or a typed refusal, and the
    competitor's file is untouched either way with nothing leaked.
    """
    chat = make_chat()
    snapshot = build_snapshot(chat.id, [])
    fixed_now = aware()
    filename = chat_export._export_filename("ordinary", chat.title, chat.id.value, fixed_now)
    competitor_path = tmp_path / filename
    competitor_content = "a competitor's real export, must survive untouched"
    real_claim = chat_export._claim_destination

    def racing_claim(candidate):
        if candidate.name == filename and not competitor_path.exists():
            competitor_path.write_text(competitor_content, encoding="utf-8")
        return real_claim(candidate)

    monkeypatch.setattr(chat_export, "_claim_destination", racing_claim)

    path = chat_export.export_chat(tmp_path, chat, None, snapshot, now=fixed_now)

    assert path != competitor_path
    assert path.stem.endswith("-2")
    assert competitor_path.read_text(encoding="utf-8") == competitor_content
    leftover = sorted(p.name for p in tmp_path.iterdir())
    assert leftover == sorted([competitor_path.name, path.name])  # nothing else leaked


def _install_competitor_over(path, content: str) -> None:
    """What a *real* competing writer does at the publication boundary: an
    atomic `os.replace` of their own finished file onto the name — a new
    inode at that pathname, not a truncating write into the placeholder cfc
    already created there (which would still be cfc's own inode and prove
    nothing).
    """
    incoming = path.parent / ".competitor-incoming"
    incoming.write_text(content, encoding="utf-8")
    os.replace(incoming, path)


def test_export_chat_refuses_to_publish_over_a_competitor_that_took_the_claim(
    tmp_path, monkeypatch,
):
    """B-2.0-78's real boundary: `O_EXCL` proves ownership at *claim* time,
    but `os.replace` acts on a pathname, so a writer who replaces the claim
    while cfc is still rendering used to have their finished file silently
    overwritten by cfc's temp file. Ownership is now re-checked immediately
    before publication; losing it is a typed refusal, and the competitor's
    file survives byte-for-byte.
    """
    chat = make_chat()
    snapshot = build_snapshot(chat.id, [])
    competitor_content = "a competitor's real export, must survive untouched"
    real_render = chat_export.render_markdown

    def render_then_lose_the_claim(chat_, opening, snapshot_, **kwargs):
        body = real_render(chat_, opening, snapshot_, **kwargs)
        claimed = next(p for p in tmp_path.iterdir() if p.suffix == ".md")
        _install_competitor_over(claimed, competitor_content)
        return body

    monkeypatch.setattr(chat_export, "render_markdown", render_then_lose_the_claim)

    with pytest.raises(chat_export.ExportWriteFailed) as caught:
        chat_export.export_chat(tmp_path, chat, None, snapshot)

    assert "another writer replaced" in str(caught.value)
    survivor = next(p for p in tmp_path.iterdir() if p.suffix == ".md")
    assert survivor.read_text(encoding="utf-8") == competitor_content
    assert [p.name for p in tmp_path.iterdir()] == [survivor.name]  # no leaked temp


def test_export_chat_failure_cleanup_never_deletes_a_competitors_file(tmp_path, monkeypatch):
    """The same ownership check guards the *cleanup* half: an export that
    fails after losing its claim must remove its own temporary material and
    nothing else. Previously cleanup unlinked the final pathname
    unconditionally, so a render failure deleted the competitor's file
    outright.
    """
    chat = make_chat()
    snapshot = build_snapshot(chat.id, [])
    competitor_content = "a competitor's real export, must survive a failed export"

    def lose_the_claim_then_fail(chat_, opening, snapshot_, **kwargs):
        claimed = next(p for p in tmp_path.iterdir() if p.suffix == ".md")
        _install_competitor_over(claimed, competitor_content)
        raise MemoryError("rendering blew up after the claim was taken")

    monkeypatch.setattr(chat_export, "render_markdown", lose_the_claim_then_fail)

    with pytest.raises(MemoryError):
        chat_export.export_chat(tmp_path, chat, None, snapshot)

    survivor = next(p for p in tmp_path.iterdir() if p.suffix == ".md")
    assert survivor.read_text(encoding="utf-8") == competitor_content
    assert [p.name for p in tmp_path.iterdir()] == [survivor.name]


def test_export_chat_collision_exhausted_raises_named_error(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_export, "_MAX_COLLISION_SUFFIX", 2)
    chat = make_chat()
    filename = chat_export._export_filename("ordinary", chat.title, chat.id.value, aware())
    (tmp_path / filename).write_text("x", encoding="utf-8")
    stem = (tmp_path / filename).stem
    suffix = (tmp_path / filename).suffix
    (tmp_path / f"{stem}-2{suffix}").write_text("x", encoding="utf-8")

    with pytest.raises(chat_export.CollisionExhausted):
        chat_export._reserve_destination(tmp_path, filename)


def test_export_chat_write_failure_never_leaves_a_temp_file_or_reports_success(tmp_path, monkeypatch):
    chat = make_chat()
    snapshot = build_snapshot(chat.id, [])

    def boom(*args, **kwargs):
        raise OSError("disk full")
    monkeypatch.setattr("builtins.open", boom)

    with pytest.raises(chat_export.ExportWriteFailed):
        chat_export.export_chat(tmp_path, chat, None, snapshot)

    assert list(tmp_path.iterdir()) == []


def test_export_chat_publish_failure_cleans_up_the_temp_file(tmp_path, monkeypatch):
    chat = make_chat()
    snapshot = build_snapshot(chat.id, [])

    def boom(*args, **kwargs):
        raise OSError("publish failed")
    monkeypatch.setattr(chat_export.os, "replace", boom)

    with pytest.raises(chat_export.ExportWriteFailed):
        chat_export.export_chat(tmp_path, chat, None, snapshot)

    assert list(tmp_path.iterdir()) == []


def test_export_chat_refuses_before_writing_when_destination_is_unusable(tmp_path):
    chat = make_chat()
    snapshot = build_snapshot(chat.id, [])
    missing = tmp_path / "nowhere"

    with pytest.raises(chat_export.DestinationUnusable):
        chat_export.export_chat(missing, chat, None, snapshot)

    assert not missing.exists()


def test_export_chat_never_mutates_the_chat_or_snapshot(tmp_path):
    chat = make_chat()
    turn, msgs = completed_turn(chat.id, 0)
    snapshot = build_snapshot(chat.id, [(turn, msgs)])
    before_chat, before_snapshot = chat, snapshot

    chat_export.export_chat(tmp_path, chat, None, snapshot)

    assert chat == before_chat
    assert snapshot == before_snapshot


# --- module boundary: no network, sqlite, or config -------------------------

def test_module_touches_no_network_sqlite_or_config():
    import inspect
    source = inspect.getsource(chat_export)
    for banned in ("import sqlite3", "import config", "from config",
                   "import httpx", "import socket", "import requests"):
        assert banned not in source
