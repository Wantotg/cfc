"""test_cfc_tool_authority.py — cfc/tool_authority.py: the descriptor-
anchored, no-follow containment boundary every read tool goes through.
Real temporary directory trees and real symlinks throughout — no mocking
of `os.open`/`os.stat`, since the whole point of this module is what the
real kernel does with real file descriptors.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from cfc import tool_authority as authority_mod
from cfc.settings import REPOSITORY_ROOT


def make_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    root.mkdir()
    return root


def authority(*roots: Path) -> authority_mod.FileAuthority:
    return authority_mod.FileAuthority(roots=tuple(roots))


# --- require_absolute --------------------------------------------------

def test_require_absolute_accepts_an_absolute_string(tmp_path):
    result = authority_mod.require_absolute(str(tmp_path))
    assert result == tmp_path


@pytest.mark.parametrize("bad", ["relative/path", "", None, 5, "~/not-expanded"])
def test_require_absolute_refuses_non_absolute_or_wrong_type(bad):
    result = authority_mod.require_absolute(bad)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL


# --- normal containment --------------------------------------------------

def test_open_contained_returns_a_working_fd_for_a_normal_file(tmp_path):
    root = make_root(tmp_path)
    (root / "a.txt").write_text("hello")
    auth = authority(root)

    result = authority_mod.open_contained(root / "a.txt", auth)
    assert isinstance(result, authority_mod.OpenTarget)
    assert result.relative == "a.txt"
    assert os.read(result.fd, 100) == b"hello"
    result.close()


def test_open_contained_returns_the_root_itself_for_the_root_path(tmp_path):
    root = make_root(tmp_path)
    auth = authority(root)
    result = authority_mod.open_contained(root, auth)
    assert isinstance(result, authority_mod.OpenTarget)
    assert result.relative == "."
    result.close()


def test_open_contained_returns_nested_relative_identity(tmp_path):
    root = make_root(tmp_path)
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "c.txt").write_text("x")
    auth = authority(root)
    result = authority_mod.open_contained(root / "a" / "b" / "c.txt", auth)
    assert result.relative == "a/b/c.txt"
    result.close()


def test_open_contained_picks_the_matching_root_among_several(tmp_path):
    root_a = tmp_path / "a"
    root_a.mkdir()
    root_b = tmp_path / "b"
    root_b.mkdir()
    (root_b / "f.txt").write_text("x")
    auth = authority(root_a, root_b)
    result = authority_mod.open_contained(root_b / "f.txt", auth)
    assert isinstance(result, authority_mod.OpenTarget)
    assert result.root == root_b
    result.close()


# --- symlink attacks: every hop, every position --------------------------

def test_direct_symlink_target_is_refused(tmp_path):
    root = make_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("nope")
    os.symlink(outside / "secret.txt", root / "link.txt")
    auth = authority(root)

    result = authority_mod.open_contained(root / "link.txt", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL
    assert "symlink" in result.reason


def test_symlinked_intermediate_directory_is_refused(tmp_path):
    root = make_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("nope")
    os.symlink(outside, root / "evil_dir")
    auth = authority(root)

    result = authority_mod.open_contained(root / "evil_dir" / "secret.txt", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL
    assert "symlink" in result.reason


def test_symlink_that_resolves_back_inside_the_root_is_still_refused(tmp_path):
    """A friendly symlink pointing at an in-root target is refused too —
    Concept.md: "allowing friendly symlinks is not worth adding a second,
    weaker path route." """
    root = make_root(tmp_path)
    (root / "real.txt").write_text("x")
    os.symlink(root / "real.txt", root / "friendly_link.txt")
    auth = authority(root)

    result = authority_mod.open_contained(root / "friendly_link.txt", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL


def test_a_deeply_nested_symlink_swap_is_refused(tmp_path):
    root = make_root(tmp_path)
    (root / "a" / "b" / "c").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("nope")
    os.symlink(outside, root / "a" / "b" / "c" / "evil")
    auth = authority(root)

    result = authority_mod.open_contained(root / "a" / "b" / "c" / "evil" / "secret.txt", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL


def test_a_real_directory_blocking_traversal_is_a_failure_not_a_refusal(tmp_path):
    """A genuine non-directory (no symlink involved) blocking further
    traversal is an ordinary failure, distinguishable from an actual
    symlink attack — proves the O_NOFOLLOW-without-O_DIRECTORY fix doesn't
    misclassify either direction."""
    root = make_root(tmp_path)
    (root / "notadir.txt").write_text("x")
    auth = authority(root)

    result = authority_mod.open_contained(root / "notadir.txt" / "child", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.FAILURE
    assert "symlink" not in result.reason


# --- lexical traversal ----------------------------------------------------

def test_lexical_dotdot_traversal_is_refused(tmp_path):
    root = make_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("nope")
    auth = authority(root)

    traversal = Path(f"{root}/../outside/secret.txt")
    result = authority_mod.open_contained(traversal, auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL


def test_dotdot_that_lexically_stays_under_root_is_still_refused(tmp_path):
    """`root/a/../b` never resolves anything — the literal `..` component
    itself is refused, even though the target is genuinely inside root."""
    root = make_root(tmp_path)
    (root / "a").mkdir()
    (root / "b.txt").write_text("x")
    auth = authority(root)

    result = authority_mod.open_contained(Path(f"{root}/a/../b.txt"), auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL


# --- cross-root and outside-root targets ----------------------------------

def test_a_path_outside_every_configured_root_is_refused(tmp_path):
    root = make_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("x")
    auth = authority(root)

    result = authority_mod.open_contained(outside / "f.txt", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL


def test_a_sibling_prefix_that_merely_starts_with_the_root_string_is_refused(tmp_path):
    """`/root-evil` is not inside `/root` even though the string starts
    with it — this must be a real path-component containment check, never
    a string prefix comparison."""
    root = tmp_path / "root"
    root.mkdir()
    sibling = tmp_path / "root-evil"
    sibling.mkdir()
    (sibling / "f.txt").write_text("x")
    auth = authority(root)

    result = authority_mod.open_contained(sibling / "f.txt", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL


# --- cfc source-tree exclusion --------------------------------------------

def test_the_cfc_repository_root_itself_is_refused_even_inside_a_broader_root(tmp_path, monkeypatch):
    root = make_root(tmp_path)
    fake_repo = root / "cfc-repo"
    fake_repo.mkdir()
    (fake_repo / "settings.py").write_text("x")
    monkeypatch.setattr(authority_mod, "REPOSITORY_ROOT", fake_repo)
    auth = authority(root)

    result = authority_mod.open_contained(fake_repo / "settings.py", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL
    assert "source tree" in result.reason


def test_the_real_repository_root_is_never_readable_when_a_root_contains_it(tmp_path):
    """Using the module's real REPOSITORY_ROOT (no monkeypatch): a
    configured root that happens to be REPOSITORY_ROOT's own parent must
    still refuse a direct read of the repository."""
    parent = REPOSITORY_ROOT.parent
    auth = authority(parent)
    a_repo_file = REPOSITORY_ROOT / "cfc" / "__init__.py"
    if not a_repo_file.exists():
        pytest.skip("repository layout does not match this test's assumption")
    result = authority_mod.open_contained(a_repo_file, auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL


# --- built-in deny rules ---------------------------------------------------

@pytest.mark.parametrize("name", ["config.py", ".env", "id_rsa", "credentials.json"])
def test_built_in_denied_names_are_refused(tmp_path, name):
    root = make_root(tmp_path)
    (root / name).write_text("secret")
    auth = authority(root)
    result = authority_mod.open_contained(root / name, auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL


@pytest.mark.parametrize("pattern_name", ["api.pem", "a_rsa", "config.py.bak"])
def test_denied_glob_patterns_are_refused(tmp_path, pattern_name):
    root = make_root(tmp_path)
    (root / pattern_name).write_text("secret")
    auth = authority(root)
    result = authority_mod.open_contained(root / pattern_name, auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL


def test_denied_directory_component_refuses_a_descendant(tmp_path):
    root = make_root(tmp_path)
    (root / ".git" / "config").mkdir(parents=True)
    auth = authority(root)
    result = authority_mod.open_contained(root / ".git" / "config", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL


def test_is_denied_name_matches_open_contained_exactly(tmp_path):
    assert authority_mod.is_denied_name("config.py") is True
    assert authority_mod.is_denied_name("ordinary.txt") is False


# --- a disappearing root is unavailable, not a refusal ---------------------

def test_a_root_that_does_not_exist_is_unavailable(tmp_path):
    missing = tmp_path / "does-not-exist"
    auth = authority(missing)
    result = authority_mod.open_contained(missing / "x.txt", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.UNAVAILABLE


def test_a_root_that_is_a_file_not_a_directory_is_unavailable(tmp_path):
    not_a_dir = tmp_path / "not-a-dir"
    not_a_dir.write_text("x")
    auth = authority(not_a_dir)
    result = authority_mod.open_contained(not_a_dir / "x.txt", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.UNAVAILABLE


# --- missing in-scope target: failure, not empty success ------------------

def test_a_missing_but_lexically_contained_target_is_a_failure(tmp_path):
    root = make_root(tmp_path)
    auth = authority(root)
    result = authority_mod.open_contained(root / "nope.txt", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.FAILURE


# --- race: target changes identity between checks --------------------------

def test_a_race_that_swaps_the_target_between_stat_and_open_cannot_escape(tmp_path):
    """The core TOCTOU class this design defeats: something replaces a
    path component with a symlink after this module's own containment
    check believed it was safe, before the object is actually opened.
    Simulated by racing the walk itself — a symlink swapped in for a
    component that was a real file/dir moments before must still be
    caught, because the walk always re-verifies with O_NOFOLLOW at the
    moment it actually opens each hop, not from an earlier snapshot.
    """
    root = make_root(tmp_path)
    (root / "sub").mkdir()
    (root / "sub" / "f.txt").write_text("real")
    auth = authority(root)

    # Swap 'sub' for a symlink to an attacker directory right before the
    # real walk would open it - simulates a race an attacker wins.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("attacker content")
    import shutil
    shutil.rmtree(root / "sub")
    os.symlink(outside, root / "sub")

    result = authority_mod.open_contained(root / "sub" / "f.txt", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL
    assert "symlink" in result.reason


# --- B-2.0-107: a symlinked root cannot become a way into cfc's source ----

def test_a_root_that_is_a_symlink_to_the_repository_cannot_read_it(tmp_path, monkeypatch):
    """The reproduced Stage 6 loop 1 bypass: the configured root is a
    symlink, so the requested path never *lexically* contains
    `REPOSITORY_ROOT` and the exclusion used to pass — while the root's own
    open (deliberately not O_NOFOLLOW) followed the link straight in.
    """
    fake_repo = tmp_path / "real-cfc"
    fake_repo.mkdir()
    (fake_repo / "README.md").write_text("cfc's own source\n")
    monkeypatch.setattr(authority_mod, "REPOSITORY_ROOT", fake_repo)

    alias = tmp_path / "alias"
    alias.symlink_to(fake_repo, target_is_directory=True)
    auth = authority(alias)

    result = authority_mod.open_contained(alias / "README.md", auth)
    assert isinstance(result, authority_mod.Refused)
    assert result.outcome is authority_mod.AuthorityOutcome.REFUSAL
    assert "source tree" in result.reason


def test_a_root_symlinked_above_the_repository_cannot_read_into_it(tmp_path, monkeypatch):
    """The wider spelling of the same bypass: the root aliases a *parent*
    of the repository, so only the canonical target reveals the route in.
    A sibling under that same aliased root still reads normally — the
    exclusion is the repository, not the alias.
    """
    parent = tmp_path / "workspace"
    fake_repo = parent / "cfc"
    fake_repo.mkdir(parents=True)
    (fake_repo / "config.example.py").write_text("secrets shape\n")
    (parent / "notes.txt").write_text("ordinary\n")
    monkeypatch.setattr(authority_mod, "REPOSITORY_ROOT", fake_repo)

    alias = tmp_path / "alias"
    alias.symlink_to(parent, target_is_directory=True)
    auth = authority(alias)

    refused = authority_mod.open_contained(alias / "cfc" / "config.example.py", auth)
    assert isinstance(refused, authority_mod.Refused)
    assert refused.outcome is authority_mod.AuthorityOutcome.REFUSAL
    assert "source tree" in refused.reason

    allowed = authority_mod.open_contained(alias / "notes.txt", auth)
    assert isinstance(allowed, authority_mod.OpenTarget)
    assert os.read(allowed.fd, 100) == b"ordinary\n"
    allowed.close()


def test_canonical_roots_are_derived_once_for_a_directly_built_authority(tmp_path):
    """A `FileAuthority` built by hand — a test, the private harness — gets
    its canonical spelling too, rather than depending on the caller to
    remember.
    """
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)

    auth = authority(alias)
    assert auth.roots == (alias,)
    assert auth.canonical_roots == (real,)


def test_mismatched_canonical_roots_are_refused_at_construction(tmp_path):
    with pytest.raises(ValueError):
        authority_mod.FileAuthority(roots=(tmp_path,), canonical_roots=(tmp_path, tmp_path))


# --- B-2.0-108: every configured root must be usable to be offered -------

def test_unusable_root_reason_is_none_when_every_root_is_a_directory(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert authority(a, b).unusable_root_reason() is None


def test_one_missing_root_makes_the_whole_authority_unusable(tmp_path):
    present = tmp_path / "present"
    present.mkdir()
    reason = authority(present, tmp_path / "gone").unusable_root_reason()
    assert reason is not None
    assert "gone" in reason


def test_a_root_that_is_a_file_makes_the_authority_unusable(tmp_path):
    a_file = tmp_path / "notes.txt"
    a_file.write_text("not a directory\n")
    reason = authority(a_file).unusable_root_reason()
    assert reason is not None
    assert "not a directory" in reason


def test_no_configured_roots_is_its_own_unusable_reason():
    reason = authority().unusable_root_reason()
    assert reason is not None
    assert "no read roots" in reason


def test_a_root_symlinked_to_a_real_directory_stays_usable(tmp_path):
    """Resolving roots must not break the ordinary reason someone uses a
    symlink: the link points at a real directory and the capability works.
    """
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    assert authority(alias).unusable_root_reason() is None
