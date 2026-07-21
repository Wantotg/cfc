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
#
# **Two front ends, because the REPL has two readers.** `read_input` uses
# prompt_toolkit on a real terminal and plain `input()` when stdin is a pipe.
# prompt_toolkit implements its own line editing and never consults readline —
# so when the editor landed, the readline completer below silently stopped
# running and `:attach` had no completion at all on the interactive path. It
# did not break; it just quietly stopped existing, which is why nothing
# failed. `AttachCompleter` is the prompt_toolkit half; `install()` is the
# readline half and still covers the `input()` fallback. Both call
# `_candidates`, so there is one definition of what may be offered.
import os
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
try:
    from config import WIKI_DIR
except ImportError:
    WIKI_DIR = ""

TRIGGER = ":attach "

# Stay silent until at least this many characters of a name have been typed.
# Tab on an empty or barely-started fragment would otherwise dump a whole
# directory — and with several roots that have no common parent, "list
# everything" has no sensible base anyway.
MIN_CHARS = 3


def _ordered_roots():
    """ATTACH_ROOTS with the vault first, the rest in configured order.

    The vault is where notes, briefs and wiki pages live; the repo root is
    where `.py` files live. When a name matches in both, the vault copy is
    almost always the one being reached for — but the repo sorts first in
    ATTACH_ROOTS (it is the read jail's natural head) and so won the list.

    The vault is identified as the root containing WIKI_DIR rather than by a
    new config key: the vault is already defined, once, by where the wiki
    lives, and a second definition is a second thing to keep in sync. Falls
    back to configured order when WIKI_DIR is unset, so a config without a
    wiki behaves exactly as before.
    """
    roots = [Path(r).expanduser().resolve() for r in ATTACH_ROOTS]
    if not WIKI_DIR:
        return roots
    try:
        wiki = Path(WIKI_DIR).expanduser().resolve()
    except OSError:
        return roots
    # Stable sort: only the vault moves, everything else keeps its order.
    return sorted(roots, key=lambda r: 0 if (r == wiki or r in wiki.parents)
                  else 1)


def _candidates(fragment):
    """Paths under any of ATTACH_ROOTS matching what's been typed so far.

    Returns nothing until MIN_CHARS of a name are typed. A relative fragment is
    tried under every root; an absolute one resolves to the single place it
    names. Duplicates (same tilde form from two roots) collapse.

    Result order follows `_ordered_roots()` — vault before repo — because the
    first entry is the one Tab accepts without a second keystroke.
    """
    roots = _ordered_roots()

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

    # A bare name means "find this", not "list this directory". The vault's
    # documents all live a level or two down — `00 inbox/`, `03 resources/wiki
    # db/` — so a one-level scan found the repo's top-level files and none of
    # the vault's, which read as the vault being missed entirely. Typing a
    # slash still means navigation, and takes the flat path below.
    if "/" not in fragment:
        return _search(stem, roots)

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
            item = _offer(child, stem, roots)
            if item and item not in seen:
                seen.add(item)
                out.append(item)
    return out


def _offer(child, stem, roots):
    """The string to offer for `child`, or None if it must not be offered."""
    # Case-insensitive: the vault's folders are '00 inbox', the repo's files
    # are 'HANDOVER.md', and remembering which is which is not something a
    # completer should charge you for. Matching stays a prefix match —
    # substring matching would offer half the tree.
    if not child.name.lower().startswith(stem.lower()):
        return None
    if child.name.startswith(".") and not stem.startswith("."):
        return None        # hidden files only on explicit request
    if child.is_dir():
        return _present(child) + "/"
    if child.suffix.lower() not in ATTACH_EXTENSIONS:
        return None
    try:
        path_guard(child, roots)
    except PathError:
        return None        # denied (config.py, keys); don't dangle it
    return _present(child)


# Bounds on the by-name search. The vault is ~430 files and a full walk of it
# measures 0.6s across /mnt/c; depth 4 covers everything that matters at about
# half that. These are caps against a pathological tree (a node_modules
# appearing under a root), not tuning — and the search only runs on an explicit
# Tab, never while typing, so the cost is paid when it was asked for.
MAX_DEPTH = 4
MAX_RESULTS = 50


def _search(stem, roots):
    """Find files by name under the roots, breadth-first, vault first.

    Shallow before deep within each root: a page sitting in `00 inbox` is a
    better guess than one buried four levels down, and the first candidate is
    what Tab takes without a second keystroke.
    """
    lowered = stem.lower()
    out, seen = [], set()
    for root in roots:
        if not root.is_dir():
            continue
        frontier = [root]
        for _ in range(MAX_DEPTH):
            nxt = []
            for base in sorted(frontier):
                try:
                    # scandir, not iterdir: it carries the file-type flag back
                    # from the directory read, so recursing costs no extra
                    # stat per entry. Across /mnt/c that is the difference
                    # between ~0.9s and ~0.2s on this vault — one stat per
                    # file over a Windows bridge is not cheap, and there are
                    # several hundred of them.
                    entries = sorted(os.scandir(base), key=lambda e: e.name)
                except OSError:
                    continue   # unreadable dir is skipped, never fatal
                for entry in entries:
                    hidden = entry.name.startswith(".")
                    try:
                        is_dir = entry.is_dir()
                    except OSError:
                        continue
                    if is_dir and not hidden:
                        nxt.append(Path(entry.path))
                    # Name test before anything that touches the filesystem:
                    # this runs on every file under every root, and the vast
                    # majority do not match.
                    if not entry.name.lower().startswith(lowered):
                        continue
                    item = _offer(Path(entry.path), stem, roots)
                    if item and item not in seen:
                        seen.add(item)
                        out.append(item)
                        if len(out) >= MAX_RESULTS:
                            return out
            frontier = nxt
            if not frontier:
                break
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
    """Wire the readline completer in. No-op where readline is unavailable.

    Only reaches the `input()` fallback path now — prompt_toolkit ignores
    readline entirely. Kept rather than deleted because that path is still
    live (piped stdin, and any terminal prompt_toolkit refuses to drive).
    """
    if readline is None:
        return False
    readline.set_completer(_completer)
    readline.set_completer_delims(" \t\n")
    readline.parse_and_bind("tab: complete")
    return True


def make_completer():
    """A prompt_toolkit Completer for `:attach`, or None if it isn't installed.

    Handed to `ui.set_completer()` by main.py rather than imported by ui.py:
    ui sits at the bottom of the dependency graph and must not import a cfc
    module (invariant #4), and this one pulls in `paths` and `config`.
    """
    try:
        from prompt_toolkit.completion import Completer, Completion
    except ImportError:
        return None

    class AttachCompleter(Completer):
        def get_completions(self, document, complete_event):
            line = document.text_before_cursor
            if not line.startswith(TRIGGER):
                return
            fragment = line[len(TRIGGER):].lstrip()
            try:
                matches = _candidates(fragment)
            except Exception:
                return      # a broken completer must never break the prompt

            # Replace the whole fragment, not the last word. prompt_toolkit
            # lets us say how far back to overwrite, so unlike readline there
            # is no need to slice the candidate to a word boundary — which is
            # what made the readline version fragile on paths with spaces, and
            # every path in the vault has a space in it.
            start = -len(fragment)
            for m in matches:
                yield Completion(m, start_position=start,
                                 display=Path(m).name + ("/" if m.endswith("/")
                                                         else ""),
                                 display_meta=str(Path(m).parent))

    return AttachCompleter()
