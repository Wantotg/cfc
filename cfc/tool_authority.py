"""tool_authority.py — the descriptor-anchored containment boundary for
read-only file tools (Stage 6 loop 1).

`Path.resolve()` is an early classification, not the operation's authority
(Concept.md, "Execution-time containment"): a checked path can be replaced
before a later reopen-by-name reads it, and a symlink that happens to
resolve back inside a root is still a route this loop refuses outright.
`open_contained` is the one entry point every read tool goes through
instead. It classifies a requested absolute path against the turn's
immutable `FileAuthority`, then walks the requested path's components one
at a time from an already-open directory descriptor — `os.open(...,
dir_fd=...)` — refusing a symlink at any hop with `O_NOFOLLOW`. The
returned `OpenTarget` carries the already-opened, already-verified file
descriptor a caller reads or lists from directly; it never re-opens by
pathname afterward, so nothing between this call and the caller's read can
swap the target out from under it.

This module never imports the flat `paths.py` (the v1.9.1 jail) — a fresh,
narrower deny list and containment rule live here, matching `cfc.settings`'s
own "never import a flat runtime module" discipline. The built-in deny
rules are the same secret-shaped names/patterns that jail already proved
matter (config.py, private keys, `.env` and its shapes); they are add-only
and applied after containment, exactly like that jail's own rule.

The cfc repository itself is never readable through these tools, even when
a broader configured root happens to contain it — checked against
`cfc.settings.REPOSITORY_ROOT`, the same value `settings.build_database_path`
already refuses to place a database inside.
"""
from __future__ import annotations

import errno
import fnmatch
import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from cfc.settings import REPOSITORY_ROOT, FileToolSettings

#: Exact filenames, matched case-insensitively against a single path
#: component — never the whole path, so a denied name is refused no matter
#: how deep it sits under a configured root.
_DENY_NAMES = {
    "config.py",
    ".env",
    ".netrc",
    ".pgpass",
    ".htpasswd",
    ".pypirc",
    ".npmrc",
    "credentials",
    "credentials.json",
    "service-account.json",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
}

#: Glob patterns, matched case-insensitively against a single component.
_DENY_GLOBS = (
    ".env.*",
    "*.pem", "*.key", "*.pfx", "*.p12", "*.jks", "*.keystore",
    "*_rsa", "*_dsa", "*_ecdsa", "*_ed25519",
    "*.kdbx",
    "config.py.*",
    "*.pyc", "*.pyo",
)

#: Directory component names refused entirely, wherever they appear in a
#: requested path — matched case-insensitively.
_DENY_DIRS = {
    ".git", ".ssh", ".gnupg", ".aws", ".kube", ".docker", ".password-store",
    "__pycache__",
}


def _denied_component(name: str) -> str | None:
    """Why a single path component is refused, or `None`. Checked against
    every walked component, not only the final target — a denied ancestor
    directory refuses the whole path, the same rule the retired flat jail
    used for its own deny list.
    """
    lowered = name.lower()
    if lowered in _DENY_DIRS:
        return f"{name!r} is never readable through these tools"
    if lowered in _DENY_NAMES:
        return f"{name!r} is on the built-in deny list (secrets)"
    for pattern in _DENY_GLOBS:
        if fnmatch.fnmatch(lowered, pattern):
            return f"{name!r} matches a denied pattern ({pattern!r})"
    return None


def is_denied_name(name: str) -> bool:
    """Whether a bare filename/directory name is denied — the same rule
    `_denied_component` checks during containment, exposed for a caller
    (`tool_executor`'s `list_dir`/`grep`) that wants to silently omit a
    denied child while enumerating a directory rather than refuse a direct
    request for it.
    """
    return _denied_component(name) is not None


class AuthorityOutcome(Enum):
    """Which of the three non-success containment states applies —
    Concept.md's "A disappearing root is unavailable. An outside,
    traversing, symlinked, denied, or source-tree target is refusal. A
    missing in-scope target ... or ordinary filesystem error is failure."
    """
    UNAVAILABLE = "unavailable"
    REFUSAL = "refusal"
    FAILURE = "failure"


@dataclass(frozen=True)
class Refused:
    """`open_contained`'s non-success result: which of the three states,
    and a bounded, cfc-authored reason — never a raw `OSError` message
    beyond `strerror`, never a stack trace.
    """
    outcome: AuthorityOutcome
    reason: str


@dataclass(frozen=True)
class FileAuthority:
    """One turn's immutable read authority: the resolved roots from
    `FileToolSettings`, unchanged for the turn's whole lifetime. Resolving
    roots again for each call would let a root that changed mid-turn
    silently grant different authority to different calls within the same
    turn (Work Order: "Resolve the roots once for a turn's immutable
    authority; the later execution boundary rechecks them").
    """
    roots: tuple[Path, ...]

    @staticmethod
    def from_settings(settings: FileToolSettings) -> "FileAuthority":
        return FileAuthority(roots=settings.roots)


class OpenTarget:
    """A fully walked, no-follow-verified filesystem object: its open file
    descriptor, its canonical root-relative identity string
    (forward-slash-joined, `"."` for the root itself), and the configured
    `root` it was walked from (for reporting and further exclusion checks
    on its own children). The fd is this object's to close — use as a
    context manager or call `close()` directly. Never re-opened by
    pathname: every read a caller performs uses this exact descriptor.
    """

    __slots__ = ("fd", "relative", "root", "_closed")

    def __init__(self, fd: int, relative: str, root: Path):
        self.fd = fd
        self.relative = relative
        self.root = root
        self._closed = False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            os.close(self.fd)

    def __enter__(self) -> "OpenTarget":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self.close()
        return False


def require_absolute(path_str: object) -> Path | Refused:
    """Every argument these tools accept a path from must be a required
    absolute string (Concept.md: "All paths are required absolute
    strings... Relative paths are refused rather than silently choosing a
    root"). Never touches the filesystem.
    """
    if not isinstance(path_str, str) or not path_str:
        return Refused(AuthorityOutcome.REFUSAL, "path must be a non-empty absolute string")
    if not path_str.startswith("/"):
        return Refused(AuthorityOutcome.REFUSAL, f"{path_str!r} is not an absolute path")
    return Path(path_str)


def _select_root(path: Path, roots: tuple[Path, ...]) -> Path | None:
    for root in roots:
        if path == root or root in path.parents:
            return root
    return None


def _relative_parts(path: Path, root: Path) -> tuple[str, ...] | None:
    """`path`'s components relative to `root`, purely lexically — `None` if
    `path` is not lexically under `root`, or if any component is `.`/`..`
    (a lexical traversal attempt, refused outright rather than resolved:
    Concept.md, "lexical `..` traversal ... [is] refused even when [it]
    happen[s] to resolve back inside").
    """
    try:
        relative = path.relative_to(root)
    except ValueError:
        return None
    parts = relative.parts
    if any(part in (".", "..") for part in parts):
        return None
    return parts


def _classify_walk_error(exc: OSError, part: str) -> Refused:
    if isinstance(exc, FileNotFoundError):
        return Refused(AuthorityOutcome.FAILURE, f"{part!r} does not exist")
    if isinstance(exc, NotADirectoryError):
        return Refused(AuthorityOutcome.FAILURE, f"{part!r} is not a directory")
    if exc.errno == errno.ELOOP:
        return Refused(AuthorityOutcome.REFUSAL,
                        f"{part!r} is a symlink; these tools never follow one")
    return Refused(AuthorityOutcome.FAILURE, f"{part!r} could not be opened ({exc.strerror})")


def open_contained(requested: Path, authority: FileAuthority) -> "OpenTarget | Refused":
    """Classify `requested` against `authority.roots`, then walk it from an
    opened root descriptor with no-follow semantics, checking the built-in
    deny rules and the cfc-repository exclusion against every walked
    component along the way. Returns an already-opened, already-verified
    `OpenTarget`, or a typed `Refused`.

    Existence is not pre-checked by any earlier resolve — a target that
    turns out not to exist surfaces as `Refused(FAILURE, ...)` from the
    walk itself, the one place this can be known without a second,
    unguarded lookup.
    """
    root = _select_root(requested, authority.roots)
    if root is None:
        return Refused(AuthorityOutcome.REFUSAL,
                        f"{requested} is outside the configured read roots")

    parts = _relative_parts(requested, root)
    if parts is None:
        return Refused(AuthorityOutcome.REFUSAL,
                        f"{requested} is not a lexically contained path under {root}")

    for part in parts:
        why = _denied_component(part)
        if why is not None:
            return Refused(AuthorityOutcome.REFUSAL, why)

    absolute_target = root.joinpath(*parts)
    if absolute_target == REPOSITORY_ROOT or REPOSITORY_ROOT in absolute_target.parents:
        return Refused(AuthorityOutcome.REFUSAL,
                        f"{absolute_target} is inside cfc's own source tree, which these "
                        f"tools never read")

    try:
        # The root itself is operator-trusted configuration, not a
        # caller-supplied route — opened without O_NOFOLLOW so a root that
        # is itself a symlink (an ordinary filesystem arrangement) still
        # works. Every component walked *from* it below is O_NOFOLLOW.
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except FileNotFoundError:
        return Refused(AuthorityOutcome.UNAVAILABLE,
                        f"the configured root {root} no longer exists")
    except NotADirectoryError:
        return Refused(AuthorityOutcome.UNAVAILABLE,
                        f"the configured root {root} is not a directory")
    except OSError as exc:
        return Refused(AuthorityOutcome.UNAVAILABLE,
                        f"the configured root {root} could not be opened ({exc.strerror})")

    try:
        for index, part in enumerate(parts):
            is_last = index == len(parts) - 1
            try:
                # Deliberately *not* combined with O_DIRECTORY: on Linux,
                # O_DIRECTORY|O_NOFOLLOW against a symlink-to-directory
                # raises ENOTDIR, not ELOOP, which would misclassify a real
                # symlink-route attempt as an ordinary "wrong type" failure
                # instead of a refusal. O_NOFOLLOW alone reliably raises
                # ELOOP for *any* symlink regardless of its target's type;
                # the directory-or-not question for an intermediate hop is
                # answered afterward, on the already-opened, already
                # not-a-symlink descriptor.
                child = os.open(part, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
            except OSError as exc:
                os.close(fd)
                return _classify_walk_error(exc, part)
            if not is_last:
                try:
                    is_dir = stat.S_ISDIR(os.fstat(child).st_mode)
                except OSError as exc:
                    os.close(fd)
                    os.close(child)
                    return Refused(AuthorityOutcome.FAILURE,
                                    f"{part!r} could not be inspected ({exc.strerror})")
                if not is_dir:
                    os.close(fd)
                    os.close(child)
                    return Refused(AuthorityOutcome.FAILURE, f"{part!r} is not a directory")
            os.close(fd)
            fd = child
    except BaseException:
        os.close(fd)
        raise

    relative = "/".join(parts) if parts else "."
    return OpenTarget(fd=fd, relative=relative, root=root)
