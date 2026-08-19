"""test_cfc_tool_executor.py — cfc/tool_executor.py: the three bounded
read-only file tools (`list_dir`, `read_file`, literal `grep`). Real
temporary directory trees throughout, driven only through
`cfc.tool_authority.FileAuthority` and `cfc.settings.FileToolSettings` —
the same two inputs the real registry (Stage 6 loop 1, Step 4) supplies.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from cfc import tool_authority as authority_mod
from cfc import tool_executor as executor
from cfc.conversation_types import ToolOutcomeKind
from cfc.settings import FileToolSettings


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    return root


def authority(*roots: Path) -> authority_mod.FileAuthority:
    return authority_mod.FileAuthority(roots=tuple(roots))


def settings(**overrides) -> FileToolSettings:
    fields = dict(enabled=True, max_result_chars=30_000, max_turn_result_chars=120_000,
                  max_calls_per_turn=25)
    fields.update(overrides)
    return FileToolSettings(**fields)


# --- list_dir: normal results ----------------------------------------------

def test_list_dir_lists_files_and_directories_sorted_by_name(tmp_path):
    root = make_root(tmp_path)
    (root / "b.txt").write_text("x")
    (root / "a_dir").mkdir()
    (root / "c.txt").write_text("yy")
    auth = authority(root)

    result = executor.list_dir(str(root), auth, settings())

    assert result.kind is ToolOutcomeKind.SUCCESS
    assert result.counts["entries_returned"] == 3
    lines = result.content.splitlines()
    names_in_order = [line.split()[-1] for line in lines if line and not line.startswith("[") and "entr" not in line]
    assert names_in_order == ["a_dir", "b.txt", "c.txt"]


def test_list_dir_never_follows_a_child_symlink_for_kind_or_size(tmp_path):
    root = make_root(tmp_path)
    target_dir = tmp_path / "elsewhere"
    target_dir.mkdir()
    os.symlink(target_dir, root / "link")
    auth = authority(root)

    result = executor.list_dir(str(root), auth, settings())
    assert "symlink" in result.content
    assert result.kind is ToolOutcomeKind.SUCCESS


def test_list_dir_a_missing_path_is_a_failure(tmp_path):
    root = make_root(tmp_path)
    result = executor.list_dir(str(root / "nope"), authority(root), settings())
    assert result.kind is ToolOutcomeKind.FAILURE


def test_list_dir_a_file_target_is_a_failure(tmp_path):
    root = make_root(tmp_path)
    (root / "f.txt").write_text("x")
    result = executor.list_dir(str(root / "f.txt"), authority(root), settings())
    assert result.kind is ToolOutcomeKind.FAILURE


def test_list_dir_empty_directory_is_a_genuine_success(tmp_path):
    root = make_root(tmp_path)
    result = executor.list_dir(str(root), authority(root), settings())
    assert result.kind is ToolOutcomeKind.SUCCESS
    assert result.counts["entries_returned"] == 0


def test_list_dir_excludes_denied_and_hidden_with_a_count(tmp_path):
    root = make_root(tmp_path)
    (root / "config.py").write_text("x")
    (root / ".hidden").write_text("x")
    (root / "visible.txt").write_text("x")
    result = executor.list_dir(str(root), authority(root), settings())
    assert result.counts["entries_returned"] == 1
    assert result.counts["entries_excluded"] == 2
    assert "excluded" in result.content


def test_list_dir_omission_is_distinguishable_from_a_truly_empty_directory(tmp_path):
    root = make_root(tmp_path)
    (root / ".hidden").write_text("x")
    result = executor.list_dir(str(root), authority(root), settings())
    assert result.counts["entries_returned"] == 0
    assert result.counts["entries_excluded"] == 1
    assert "excluded" in result.content  # not silently "0 entries" with no explanation


def test_list_dir_the_cfc_repository_is_omitted_when_a_broader_root_contains_it(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    fake_repo = root / "cfc"
    fake_repo.mkdir()
    (root / "other").mkdir()
    monkeypatch.setattr(executor, "REPOSITORY_ROOT", fake_repo)
    result = executor.list_dir(str(root), authority(root), settings())
    assert result.counts["entries_returned"] == 1
    assert result.counts["entries_excluded"] == 1


def test_list_dir_respects_the_configured_character_limit(tmp_path):
    root = make_root(tmp_path)
    for i in range(200):
        (root / f"file_{i:04d}.txt").write_text("x")
    result = executor.list_dir(str(root), authority(root), settings(max_result_chars=200))
    assert result.truncated is True
    assert len(result.content) <= 260  # bounded, plus the truncation note


def test_list_dir_scan_and_visible_bounds_are_enforced(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    for i in range(50):
        (root / f"f_{i:03d}.txt").write_text("x")
    monkeypatch.setattr(executor, "_LIST_DIR_MAX_RAW_ENTRIES", 10)
    monkeypatch.setattr(executor, "_LIST_DIR_MAX_VISIBLE_ENTRIES", 5)
    result = executor.list_dir(str(root), authority(root), settings())
    assert result.counts["entries_returned"] <= 5
    assert "stopped after" in result.content


def test_list_dir_is_cancelled_between_entries(tmp_path):
    root = make_root(tmp_path)
    for i in range(50):
        (root / f"f_{i:03d}.txt").write_text("x")
    calls = {"n": 0}

    def cancel_soon():
        calls["n"] += 1
        return calls["n"] > 3

    result = executor.list_dir(str(root), authority(root), settings(), is_cancelled=cancel_soon)
    assert result.kind is ToolOutcomeKind.CANCELLATION


# --- read_file --------------------------------------------------------------

def test_read_file_returns_the_whole_file_with_line_numbers(tmp_path):
    root = make_root(tmp_path)
    (root / "f.txt").write_text("one\ntwo\nthree\n")
    result = executor.read_file(str(root / "f.txt"), authority(root), settings())
    assert result.kind is ToolOutcomeKind.SUCCESS
    assert "1| one" in result.content
    assert "3| three" in result.content


def test_read_file_a_requested_range_returns_only_that_range(tmp_path):
    root = make_root(tmp_path)
    (root / "f.txt").write_text("\n".join(f"line{i}" for i in range(1, 11)) + "\n")
    result = executor.read_file(str(root / "f.txt"), authority(root), settings(),
                                 start_line=3, end_line=5)
    assert "line3" in result.content
    assert "line5" in result.content
    assert "line1" not in result.content
    assert "line6" not in result.content


@pytest.mark.parametrize("start,end", [(0, None), (-1, None), (3, 2)])
def test_read_file_invalid_range_is_a_failure(tmp_path, start, end):
    root = make_root(tmp_path)
    (root / "f.txt").write_text("a\nb\nc\n")
    result = executor.read_file(str(root / "f.txt"), authority(root), settings(),
                                 start_line=start, end_line=end)
    assert result.kind is ToolOutcomeKind.FAILURE


def test_read_file_start_line_past_end_is_a_failure(tmp_path):
    root = make_root(tmp_path)
    (root / "f.txt").write_text("a\nb\n")
    result = executor.read_file(str(root / "f.txt"), authority(root), settings(), start_line=99)
    assert result.kind is ToolOutcomeKind.FAILURE
    assert "past the end" in result.reason


def test_read_file_a_directory_target_is_a_failure(tmp_path):
    root = make_root(tmp_path)
    (root / "sub").mkdir()
    result = executor.read_file(str(root / "sub"), authority(root), settings())
    assert result.kind is ToolOutcomeKind.FAILURE


def test_read_file_invalid_utf8_is_a_failure_not_partial_success(tmp_path):
    root = make_root(tmp_path)
    (root / "bin.dat").write_bytes(b"valid text\xff\xfe more")
    result = executor.read_file(str(root / "bin.dat"), authority(root), settings())
    assert result.kind is ToolOutcomeKind.FAILURE
    assert result.content == ""


def test_read_file_missing_file_is_a_failure(tmp_path):
    root = make_root(tmp_path)
    result = executor.read_file(str(root / "nope.txt"), authority(root), settings())
    assert result.kind is ToolOutcomeKind.FAILURE


def test_read_file_truncates_at_the_character_limit_and_says_so(tmp_path):
    root = make_root(tmp_path)
    (root / "f.txt").write_text("\n".join(f"line number {i}" for i in range(1, 2000)) + "\n")
    result = executor.read_file(str(root / "f.txt"), authority(root), settings(max_result_chars=100))
    assert result.truncated is True
    assert result.kind is ToolOutcomeKind.SUCCESS
    assert len(result.content) < 300


def test_read_file_a_far_away_range_hits_the_scan_cap_rather_than_scanning_forever(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    with open(root / "big.txt", "w") as f:
        for i in range(1, 2_000_000):
            f.write(f"l{i}\n")
    monkeypatch.setattr(executor, "_READ_FAR_RANGE_SCAN_CAP", 1024)
    result = executor.read_file(str(root / "big.txt"), authority(root), settings(),
                                 start_line=1_900_000)
    assert result.kind is ToolOutcomeKind.FAILURE
    assert "scanned" in result.reason
    assert result.counts["bytes_scanned"] >= 1024


def test_read_file_is_cancelled_between_chunks(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    with open(root / "big.txt", "w") as f:
        for i in range(1, 200_000):
            f.write(f"line {i}\n")
    monkeypatch.setattr(executor, "_READ_CHUNK_SIZE", 100)
    calls = {"n": 0}

    def cancel_soon():
        calls["n"] += 1
        return calls["n"] > 2

    result = executor.read_file(str(root / "big.txt"), authority(root),
                                 settings(max_result_chars=10_000_000),
                                 is_cancelled=cancel_soon)
    assert result.kind is ToolOutcomeKind.CANCELLATION


# --- grep: literal, bounded, containment-respecting -------------------------

def test_grep_finds_literal_matches_in_a_single_file(tmp_path):
    root = make_root(tmp_path)
    (root / "f.txt").write_text("alpha\nTODO: fix\nbeta\n")
    result = executor.grep("TODO", str(root / "f.txt"), authority(root), settings())
    assert result.kind is ToolOutcomeKind.SUCCESS
    assert "TODO: fix" in result.content
    assert result.counts["matches"] == 1


def test_grep_recurses_a_directory_without_following_symlinks(tmp_path):
    root = make_root(tmp_path)
    (root / "sub").mkdir()
    (root / "sub" / "a.txt").write_text("needle here\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "b.txt").write_text("needle should not be found\n")
    os.symlink(outside, root / "sub" / "escape")

    result = executor.grep("needle", str(root), authority(root), settings())
    assert result.counts["matches"] == 1
    assert "sub/a.txt" in result.content
    assert "should not be found" not in result.content


def test_grep_prunes_the_cfc_source_tree(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    fake_repo = root / "cfc"
    (fake_repo).mkdir()
    (fake_repo / "secret.py").write_text("TODO leak\n")
    (root / "ok.txt").write_text("TODO visible\n")
    monkeypatch.setattr(executor, "REPOSITORY_ROOT", fake_repo)

    result = executor.grep("TODO", str(root), authority(root), settings())
    assert "secret.py" not in result.content
    assert "ok.txt" in result.content


def test_grep_prunes_hidden_denied_and_non_text_files(tmp_path):
    root = make_root(tmp_path)
    (root / ".hidden.txt").write_text("TODO hidden\n")
    (root / "config.py").write_text("TODO secret\n")
    (root / "binary.exe").write_text("TODO binary\n")
    (root / "ok.txt").write_text("TODO ok\n")
    result = executor.grep("TODO", str(root), authority(root), settings())
    assert result.counts["matches"] == 1
    assert "ok.txt" in result.content


def test_grep_literal_pattern_is_not_treated_as_regex(tmp_path):
    root = make_root(tmp_path)
    (root / "f.txt").write_text("a.b\naxb\n")
    result = executor.grep("a.b", str(root / "f.txt"), authority(root), settings())
    assert result.counts["matches"] == 1  # "axb" must not match a literal "a.b"


def test_grep_empty_pattern_is_a_failure(tmp_path):
    root = make_root(tmp_path)
    result = executor.grep("", str(root), authority(root), settings())
    assert result.kind is ToolOutcomeKind.FAILURE


def test_grep_over_long_pattern_is_a_failure(tmp_path):
    root = make_root(tmp_path)
    result = executor.grep("x" * 2000, str(root), authority(root), settings())
    assert result.kind is ToolOutcomeKind.FAILURE


def test_grep_no_matches_in_a_fully_searched_scope_is_a_genuine_empty_success(tmp_path):
    root = make_root(tmp_path)
    (root / "f.txt").write_text("nothing interesting\n")
    result = executor.grep("ZZZNEVER", str(root), authority(root), settings())
    assert result.kind is ToolOutcomeKind.SUCCESS
    assert "no matches" in result.content
    assert "incomplete" not in result.content


def test_grep_match_limit_marks_the_result_incomplete(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    (root / "f.txt").write_text("\n".join("needle" for _ in range(50)) + "\n")
    monkeypatch.setattr(executor, "_GREP_MAX_MATCHES", 5)
    result = executor.grep("needle", str(root), authority(root), settings())
    assert result.counts["matches"] == 5
    assert "incomplete" in result.content


def test_grep_file_examined_limit_marks_the_result_incomplete(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    for i in range(20):
        (root / f"f_{i}.txt").write_text("no match here\n")
    monkeypatch.setattr(executor, "_GREP_MAX_FILES_EXAMINED", 5)
    result = executor.grep("needle", str(root), authority(root), settings())
    assert result.counts["files_examined"] <= 5
    assert "incomplete" in result.content


def test_grep_a_non_utf8_file_is_skipped_and_counted_not_silently_ignored(tmp_path):
    root = make_root(tmp_path)
    (root / "bin.txt").write_bytes(b"needle\xff\xfe")
    (root / "ok.txt").write_text("needle ok\n")
    result = executor.grep("needle", str(root), authority(root), settings())
    assert result.counts["files_skipped"] == 1
    assert result.counts["matches"] == 1


def test_grep_cancellation_between_files(tmp_path):
    root = make_root(tmp_path)
    for i in range(30):
        (root / f"f_{i}.txt").write_text("x\n")
    calls = {"n": 0}

    def cancel_soon():
        calls["n"] += 1
        return calls["n"] > 5

    result = executor.grep("x", str(root), authority(root), settings(), is_cancelled=cancel_soon)
    assert result.kind is ToolOutcomeKind.CANCELLATION


def test_grep_a_direct_symlink_target_is_refused(tmp_path):
    root = make_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("needle\n")
    os.symlink(outside / "f.txt", root / "link.txt")
    result = executor.grep("needle", str(root / "link.txt"), authority(root), settings())
    assert result.kind is ToolOutcomeKind.REFUSAL


def test_grep_respects_the_configured_character_limit(tmp_path):
    root = make_root(tmp_path)
    (root / "f.txt").write_text("\n".join(f"needle {i}" for i in range(500)) + "\n")
    result = executor.grep("needle", str(root), authority(root), settings(max_result_chars=100))
    assert result.truncated is True
    assert len(result.content) < 250
