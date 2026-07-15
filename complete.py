# complete.py — tab completion for ':attach <path>'.
#
# Only active when the line starts with ':attach '. Everything else falls back
# to no completion, which is what the REPL had before.
#
# Completions are scoped to ATTACH_ROOT and never offer a path outside it, or
# one path_guard would refuse. That's a courtesy, not a control: the guard in
# do_attach is what actually enforces the jail, and it runs regardless of what
# was typed or completed. Offering a path here that :attach would then refuse
# is just a way to waste someone's afternoon.
from pathlib import Path

try:
    import readline
except ImportError:
    readline = None

from paths import path_guard, PathError

try:
    from config import ATTACH_ROOT
except ImportError:
    ATTACH_ROOT = Path("~/projects").expanduser()
try:
    from config import ATTACH_EXTENSIONS
except ImportError:
    ATTACH_EXTENSIONS = {".md", ".txt", ".py", ".json", ".yaml", ".yml",
                         ".toml", ".csv", ".sql", ".sh"}

TRIGGER = ":attach "


def _candidates(fragment):
    """Paths under ATTACH_ROOT matching what's been typed so far."""
    root = Path(ATTACH_ROOT).expanduser()

    # Split the typed text into "directory so far" and "partial name".
    # Note the trailing-slash test happens on the raw fragment: Path() strips
    # it, so "~/projects/cfc/" would otherwise be read as the partial name
    # "cfc" and complete to itself instead of listing what's inside it.
    ends_in_slash = fragment.endswith("/")

    text = fragment
    if text.startswith("~"):
        text = str(Path(text).expanduser())

    if not text:
        base, stem = root, ""
    elif ends_in_slash:
        base, stem = Path(text), ""
    else:
        p = Path(text)
        base, stem = p.parent, p.name
    if not base.is_absolute():
        base = root / base

    try:
        base = base.expanduser().resolve()
    except OSError:
        return []
    if base != root and root.resolve() not in base.parents:
        return []          # typed their way out of the jail; offer nothing
    if not base.is_dir():
        return []

    out = []
    for child in sorted(base.iterdir()):
        if not child.name.startswith(stem):
            continue
        if child.name.startswith(".") and not stem.startswith("."):
            continue       # hidden files only on explicit request
        if child.is_dir():
            out.append(_present(child) + "/")
            continue
        if child.suffix.lower() not in ATTACH_EXTENSIONS:
            continue
        try:
            path_guard(child, root)
        except PathError:
            continue       # denied (config.py, keys); don't dangle it
        out.append(_present(child))
    return out


def _present(p):
    """Show what the user would have typed: tilde form under home."""
    try:
        return "~/" + str(p.relative_to(Path.home()))
    except ValueError:
        return str(p)


def _completer(text, state):
    try:
        line = readline.get_line_buffer()
        if not line.startswith(TRIGGER):
            return None
        fragment = line[len(TRIGGER):].lstrip()
        matches = _candidates(fragment)
        # readline replaces only the last word, so hand back the tail
        begin = readline.get_begidx()
        prefix_len = begin - (len(line) - len(fragment))
        if prefix_len > 0:
            matches = [m[prefix_len:] if len(m) > prefix_len else m
                       for m in matches]
        return matches[state] if state < len(matches) else None
    except Exception:
        return None        # a broken completer must never break the prompt


def install():
    """Wire the completer in. No-op where readline is unavailable."""
    if readline is None:
        return False
    readline.set_completer(_completer)
    readline.set_completer_delims(" \t\n")
    readline.parse_and_bind("tab: complete")
    return True
