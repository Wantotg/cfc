# paths.py — the jail. Every path that :attach or a tool touches comes through
# path_guard() first.
#
# This module is the entire security boundary for file access, so it does two
# separate jobs and does both unconditionally:
#
#   1. containment — the path must resolve inside the configured root
#   2. denial      — some files are refused even inside the root
#
# Both checks run on the *resolved* path. Resolving first is what defeats
# ../ traversal and symlinks: a symlink called notes.md pointing at
# ~/.ssh/id_rsa resolves to the real target before anything is decided, so it
# is judged as what it is rather than what it is named.
#
# The denial list exists because the root is ~/projects, which contains cfc,
# which contains config.py, which contains the API key — and .py is an
# attachable extension. Containment alone would hand the key to any model that
# asked for it. The approval gate is not a substitute: a gate that fires on
# every call is a gate that gets rubber-stamped.
#
# Denial is deliberately not configurable downward. config.py may add to the
# list via ATTACH_DENY_EXTRA; it cannot remove from it.
import fnmatch
from pathlib import Path


class PathError(Exception):
    """Raised when a path is outside the root, or is refused outright."""


# Exact filenames, matched case-insensitively against the resolved name.
_DENY_NAMES = {
    "config.py",              # cfc's own — holds API_KEY
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

# Glob patterns, matched case-insensitively against the resolved name.
_DENY_GLOBS = (
    ".env.*",                 # .env.local, .env.production
    "*.pem", "*.key", "*.pfx", "*.p12", "*.jks", "*.keystore",
    "*_rsa", "*_dsa", "*_ecdsa", "*_ed25519",
    "*.kdbx",
)

# Any path with one of these as a directory component is refused entirely.
_DENY_DIRS = {
    ".ssh", ".gnupg", ".aws", ".kube", ".docker", ".password-store",
}

try:
    from config import ATTACH_DENY_EXTRA
except ImportError:
    ATTACH_DENY_EXTRA = ()


def _denied(resolved):
    """Why this path is refused, or None. Takes an already-resolved Path."""
    name = resolved.name.lower()

    for part in resolved.parts:
        if part.lower() in _DENY_DIRS:
            return f"{part}/ is never readable"

    if name in _DENY_NAMES:
        return f"{resolved.name} is on the deny list (secrets)"

    for pattern in tuple(_DENY_GLOBS) + tuple(ATTACH_DENY_EXTRA):
        if fnmatch.fnmatch(name, pattern.lower()):
            return f"{resolved.name} matches denied pattern {pattern!r}"

    return None


def _as_roots(roots):
    """Normalise a single root or an iterable of them to a list of Paths."""
    if isinstance(roots, (str, Path)):
        roots = [roots]
    return [Path(r).expanduser().resolve() for r in roots]


def path_guard(path, roots):
    """Resolve path and assert it is inside a root and not denied.

    `roots` may be a single path or an iterable of them; the path passes if it
    is inside *any* of them. The deny list is root-agnostic — it runs on the
    resolved path regardless of which root allowed it, so adding a root widens
    containment without ever un-denying config.py or a private key.

    Resolves before checking, which defeats ../ traversal and symlink escape.
    Returns the resolved Path. Raises PathError otherwise.

    Existence is NOT checked here: a non-existent path inside a root passes,
    and callers report "no such file" themselves, so that "outside the jail"
    and "not there" stay distinguishable in the error the user sees.
    """
    roots = _as_roots(roots)
    p = Path(path).expanduser().resolve()

    if not any(p == r or r in p.parents for r in roots):
        joined = ", ".join(str(r) for r in roots)
        raise PathError(f"{p} is outside the allowed roots ({joined})")

    why = _denied(p)
    if why:
        raise PathError(why)

    return p
