# vault.py — the vault-policy and display-label authority (v1.6).
#
# Two unrelated-looking jobs share this module because they share one
# ingredient: parsed frontmatter YAML under VAULT_ROOT. Splitting them into
# two modules would have meant two frontmatter readers, which is exactly the
# producer/parser drift HANDOVER.md keeps a table of.
#
#   1. named vault scopes — an optional, named partition of the vault into
#      directories a model-facing surface may or may not reach.
#   2. a read-only title label — a Markdown file's frontmatter `title`, or
#      its filename on any failure to read one.
#
# This module is an authority, not a second filesystem jail: `paths.py`
# still owns ordinary containment and the deny list. Every scope-aware
# consumer (commands.py, complete.py, tools.py, screens.py, the wiki
# import/recall seam) asks THIS module rather than re-parsing VAULT_SCOPES or
# re-walking ancestry, so there is one place the nesting rule lives.
import os
from pathlib import Path

import yaml

try:
    from config import VAULT_ROOT
except ImportError:
    VAULT_ROOT = ""
try:
    from config import VAULT_SCOPES
except ImportError:
    VAULT_SCOPES = ()

OK = "ok"
INVALID = "invalid"


class Scope:
    """One normalised, valid scope declaration."""

    __slots__ = ("name", "path", "exposed", "resolved")

    def __init__(self, name, path, exposed, resolved):
        self.name = name
        self.path = path            # as configured, vault-relative
        self.exposed = exposed
        self.resolved = resolved    # absolute, symlinks followed

    def __repr__(self):
        return (f"<Scope {self.name!r} "
                f"{'exposed' if self.exposed else 'hidden'} {self.resolved}>")


def _vault_root():
    """VAULT_ROOT resolved, or None when it isn't configured. Read through
    the module attribute at call time (not captured at import) so a test can
    repoint it the way tests/golden.py repoints pools.py's directories."""
    return Path(VAULT_ROOT).expanduser().resolve() if VAULT_ROOT else None


def _normalize():
    """(scopes, problems).

    `scopes` is every valid declaration, as `Scope` objects, sorted shallow
    to deep. `problems` is one human-readable string per invalid record —
    empty when there are none. Declaration order never affects the result:
    `exposed()` ORs hidden-ness across every matching scope regardless of
    which order they were declared or processed in, so sorting here is for a
    readable /config display, not correctness.
    """
    raw = VAULT_SCOPES or ()
    if not raw:
        return (), []

    root = _vault_root()
    if root is None:
        return (), ["VAULT_SCOPES is configured but VAULT_ROOT is not — "
                     "cannot resolve scope paths"]

    problems = []
    scopes = []
    seen_names = set()

    for i, rec in enumerate(raw):
        tag = f"scope #{i + 1}"
        try:
            name = str(rec["name"]).strip()
            rel = rec["path"]
            exposed = bool(rec["exposed"])
        except (KeyError, TypeError, IndexError):
            problems.append(f"{tag}: malformed record — needs name, path, "
                            f"exposed")
            continue
        if not name:
            problems.append(f"{tag}: empty name")
            continue
        tag = f"scope {name!r}"
        if name in seen_names:
            problems.append(f"{tag}: duplicate name")
            continue

        rel_path = Path(str(rel))
        if rel_path.is_absolute():
            problems.append(f"{tag}: path must be relative to VAULT_ROOT, "
                            f"not absolute ({rel})")
            continue
        if ".." in rel_path.parts:
            problems.append(f"{tag}: path must not contain '..' ({rel})")
            continue

        candidate = root / rel_path
        try:
            resolved = candidate.resolve()
        except OSError as e:
            problems.append(f"{tag}: cannot resolve {rel}: {e}")
            continue
        if not (resolved == root or root in resolved.parents):
            problems.append(f"{tag}: {rel} resolves outside VAULT_ROOT "
                            f"(symlink escape)")
            continue
        if not resolved.is_dir():
            problems.append(f"{tag}: {rel} does not exist or is not a "
                            f"directory")
            continue

        seen_names.add(name)
        scopes.append(Scope(name, str(rel), exposed, resolved))

    scopes.sort(key=lambda s: len(s.resolved.parts))
    return tuple(scopes), problems


def state():
    """(OK|INVALID, scopes, problems) — the whole policy's current state."""
    scopes, problems = _normalize()
    return (INVALID if problems else OK), scopes, problems


def _touches_hidden(path, scopes):
    """True if `path` sits inside, or is, any hidden scope's directory.

    A hidden ancestor always wins: once any matching scope along the chain
    is hidden, a deeper *exposed* scope cannot clear that — the loop only
    ever turns `hidden` on, never off. That is what makes an exposed child
    unable to punch a hole back through a hidden parent, and it is why
    processing order doesn't matter (see `_normalize`).
    """
    hidden = False
    for s in scopes:
        if path == s.resolved or s.resolved in path.parents:
            if not s.exposed:
                hidden = True
    return hidden


def _literal(path):
    """`path`, expanded and lexically normalised — `..` collapsed, but no
    symlink is followed. `None` when it isn't absolute, since there is
    nothing under VAULT_ROOT to compare a relative fragment against.

    This is the "requested route" half of `exposed()`: a symlink SITTING
    inside a hidden directory and pointing somewhere ordinarily exposed must
    still be refused, because the request named the hidden directory
    directly — resolving the symlink's target away is not the same question
    as whether the hidden boundary was crossed to reach it.
    """
    try:
        p = Path(str(path)).expanduser()
    except (TypeError, ValueError):
        return None
    if not p.is_absolute():
        return None
    return Path(os.path.normpath(str(p)))


def exposed(requested, resolved):
    """Whether a vault path may reach a model, given both the caller's
    literal request and that same path fully resolved (symlinks and `..`
    followed).

    True unconditionally when no scope is configured — the "no setting
    preserves today's behaviour" rule. While a declared scope set is
    invalid, this fails closed, but ONLY for a path actually inside
    VAULT_ROOT: an unrelated read root (the repo, another attach root) is
    not vault material and a typo in VAULT_SCOPES must not blind it too.

    Checks two things, either of which refuses:
      * the fully resolved destination touching a hidden scope (a symlink or
        `..` that lands inside hidden material), and
      * the literal requested path touching one (a symlink placed INSIDE a
        hidden directory, whatever it points at).
    """
    # `not VAULT_SCOPES` (nothing was ever declared) is distinct from `not
    # scopes` (something was declared but every record turned out invalid,
    # leaving zero VALID scopes) — the latter must still fail closed. Only
    # the former is "no setting preserves today's behaviour".
    if not VAULT_SCOPES:
        return True

    kind, scopes, _ = state()
    resolved = Path(resolved)
    if kind == INVALID:
        root = _vault_root()
        return not (root and (resolved == root or root in resolved.parents))

    if _touches_hidden(resolved, scopes):
        return False
    lit = _literal(requested)
    if lit is not None and _touches_hidden(lit, scopes):
        return False
    return True


def exposed_path(path):
    """Single-path convenience for a caller with only one form of a path —
    a resolved WIKI_DIR, a directory-listing entry already read from disk.
    Resolves internally. Not a substitute for `exposed()` when the caller
    genuinely has an unresolved request to check against its resolution.
    """
    p = Path(path).expanduser()
    try:
        resolved = p.resolve()
    except OSError:
        resolved = p
    return exposed(str(p), resolved)


def scope_rows():
    """([(name, 'exposed'|'hidden', resolved_path), ...], problems) — for
    /config's `scopes` detail view. Declared state, not a reachability
    answer for any particular path."""
    _, scopes, problems = state()
    rows = [(s.name, "exposed" if s.exposed else "hidden", str(s.resolved))
            for s in scopes]
    return rows, problems


def scope_counts():
    """(exposed, hidden, invalid) — for /config's overview line. `invalid`
    counts *problems*, not scopes: one malformed record is one problem
    regardless of how many valid scopes sit beside it."""
    _, scopes, problems = state()
    n_exposed = sum(1 for s in scopes if s.exposed)
    n_hidden = sum(1 for s in scopes if not s.exposed)
    return n_exposed, n_hidden, len(problems)


# --- the title label ---------------------------------------------------
#
# Read-only, and read-only in the stronger sense too: nothing anywhere
# resolves a title back to a path. A caller keeps the path it already had and
# uses this only to decide what to print beside it.


def title_for(path):
    """The frontmatter `title` of a Markdown file, or its filename.

    Never raises. Missing, non-string, malformed YAML, an unreadable file,
    or a decoding failure all fall back to `Path(path).name` — a display
    improvement must never make a working file unavailable.
    """
    p = Path(path)
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError):
        return p.name
    if not text.startswith("---"):
        return p.name
    parts = text.split("---", 2)
    if len(parts) < 3:
        return p.name
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return p.name
    if not isinstance(fm, dict):
        return p.name
    title = fm.get("title")
    if not isinstance(title, str):
        return p.name
    title = title.strip()
    return title if title else p.name
