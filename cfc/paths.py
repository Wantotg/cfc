"""paths.py — the one path-shape check the bootstrap core needs, shared by
the database target and the vault diagnosis.

Deliberately not `paths.py` at the repository root (the v1.9.1 tool jail) —
importing that would pull in a flat runtime module, which this package
never does. This is smaller and does something different: it never opens,
creates, or writes anything, only asks whether a path *could* be used
without anything else changing first.
"""
from __future__ import annotations

from pathlib import Path


def nearest_existing_parent(path: Path) -> Path:
    """Walk up from `path` to the first ancestor that exists. `path` itself,
    if it exists. The filesystem root always exists, so this always
    terminates.
    """
    candidate = path
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            return candidate
        candidate = parent
    return candidate


def usable_target_reason(path: Path) -> str | None:
    """None if `path` could be created or opened as a file without anything
    else changing first: either it already exists and is a file, or its
    nearest existing ancestor is a real directory. Otherwise the reason it
    could not.

    Never creates, opens, or writes anything — existence is checked with
    `Path.exists()`/`Path.is_dir()` only.
    """
    if path.exists():
        if path.is_dir():
            return f"{path} is a directory, not a file"
        return None

    parent = nearest_existing_parent(path.parent)
    if not parent.exists():
        return f"no existing ancestor directory found above {path}"
    if not parent.is_dir():
        return f"{parent} exists but is not a directory"
    return None


def usable_directory_reason(path: Path) -> str | None:
    """None if `path` already is a directory, or does not exist yet but its
    nearest existing ancestor is a real directory (so it could become one
    without anything else changing first). Otherwise the reason it could
    not — see `usable_target_reason` for the file-target equivalent this
    mirrors.
    """
    if path.exists():
        if path.is_dir():
            return None
        return f"{path} exists but is not a directory"

    parent = nearest_existing_parent(path.parent)
    if not parent.exists():
        return f"no existing ancestor directory found above {path}"
    if not parent.is_dir():
        return f"{parent} exists but is not a directory"
    return None
