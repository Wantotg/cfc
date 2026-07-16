# complete.py — tab completion for ':attach <path>'.
#
# Only active when the line starts with ':attach '. Everything else falls back
# to no completion, which is what the REPL had before.
#
# Completions are scoped to ATTACH_ROOTS and never offer a path outside them, or
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
    from config import ATTACH_ROOTS
except ImportError:
    ATTACH_ROOTS = (Path("~/projects").expanduser(),)
try:
    from config import ATTACH_EXTENSIONS
except ImportError:
    ATTACH_EXTENSIONS = {".md", ".txt", ".py", ".json", ".yaml", ".yml",
                         ".toml", ".csv", ".sql", ".sh"}

TRIGGER = ":attach "

# Stay silent until at least this many characters of a name have been typed.
# Tab on an empty or barely-started fragment would otherwise dump a whole
# directory — and with several roots that have no common parent, "list
# everything" has no sensible base anyway.
MIN_CHARS = 3


def _candidates(fragment):
    """Paths under any of ATTACH_ROOTS matching what's been typed so far.

    Returns nothing until MIN_CHARS of a name are typed. A relative fragment is
    tried under every root; an absolute one resolves to the single place it
    names. Duplicates (same tilde form from two roots) collapse.
    """
    roots = [Path(r).expanduser().resolve() for r in ATTACH_ROOTS]

    # Split the typed text into "directory so far" and "partial name".
    # Note the trailing-slash test happens on the raw fragment: Path() strips
    # it, so "~/projects/cfc/" would otherwise be read as the partial name
    # "cfc" and complete to itself instead of listing what's inside it.
    ends_in_slash = fragment.endswith("/")

    text = fragment
    if text.startswith("~"):
        text = str(Path(text).expanduser())

    if not text:
        rel_base, stem = None, ""
    elif ends_in_slash:
        rel_base, stem = Path(text), ""
    else:
        p = Path(text)
        rel_base, stem = p.parent, p.name

    if len(stem) < MIN_CHARS:
        return []          # wait until more is typed; never dump a full list

    # Where to look. An absolute base resolves to one place; a relative one is
    # tried under every root.
    if rel_base is not None and rel_base.is_absolute():
        bases = [rel_base]
    elif rel_base is not None:
        bases = [root / rel_base for root in roots]
    else:
        bases = list(roots)

    out, seen = [], set()
    for base in bases:
        try:
            base = base.expanduser().resolve()
        except OSError:
            continue
        if not any(base == r or r in base.parents for r in roots):
            continue       # outside every jail; offer nothing
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.name.startswith(stem):
                continue
            if child.name.startswith(".") and not stem.startswith("."):
                continue   # hidden files only on explicit request
            if child.is_dir():
                item = _present(child) + "/"
            elif child.suffix.lower() not in ATTACH_EXTENSIONS:
                continue
            else:
                try:
                    path_guard(child, roots)
                except PathError:
                    continue    # denied (config.py, keys); don't dangle it
                item = _present(child)
            if item not in seen:
                seen.add(item)
                out.append(item)
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
