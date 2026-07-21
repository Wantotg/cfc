# wikigit.py — reviewing and committing vault changes from inside the REPL.
#
# The Obsidian vault is a git repo (its .git is a `gitdir:` pointer to
# ~/vaults/wiki.git, so git stays off the /mnt/c bridge and out of Obsidian's
# explorer). This module is the REPL's window onto it.
#
# It is the same shape as mover.py, and for the same reasons:
#
#   1. **This is not an LLM tool.** Committing has a correct answer, so it is
#      code — deterministic, auditable, free. The model never calls it and
#      there is no tool schema for it anywhere. Use a model for judgement under
#      ambiguity; use code for anything with a right answer.
#
#   2. **Scoped by default, widened only on the word `all`.** The wiki corpus
#      is what recall reads, so it is what `:wiki` watches. The rest of the
#      vault — `02 areas` holds medical material — is reachable, but only when
#      you type the extra word. A narrow default that can be widened
#      deliberately beats a wide default nobody remembers is wide.
#
#   3. **Refused, not guessed at.** No repo → an error, never `git init`. Wiki
#      dir outside the repo → an error, never "commit what we found instead".
#
# **There is no push.** The vault repo has no remote: its history lives on ext4
# outside the Windows backup, and whether the medical material goes to someone
# else's server is a decision parked at v1.0. A push that silently no-ops today
# is a push that silently starts working the day a remote appears, which is
# exactly the wrong way for that decision to get made.
import subprocess
from pathlib import Path

# /mnt/c is slow and git has to stat a few thousand files across the bridge. A
# generous ceiling that still guarantees a hung git cannot wedge the REPL —
# there is no background thread here, so this blocks the input loop while it
# runs (invariant #4: nothing else may be driving the terminal, and nothing is).
_TIMEOUT = 120

WIKI = "wiki"
ALL = "all"


class GitError(Exception):
    """A git operation could not be carried out. Carries the human-facing why."""


def _cfg(key, default=None):
    try:
        import config
        return getattr(config, key, default)
    except ImportError:
        return default


def wiki_dir():
    d = _cfg("WIKI_DIR", "")
    return Path(d).expanduser().resolve() if d else None


def _git(repo, *args, check=True):
    """Run one git command in `repo`. Returns stdout.

    Arguments are a list and there is no shell, so a path containing a space,
    a quote or a semicolon is an argument and can never become syntax. Every
    caller that passes a path passes it after `--` as well; see `_pathspec`.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=_TIMEOUT,
        )
    except FileNotFoundError:
        raise GitError("git is not installed, or not on PATH")
    except subprocess.TimeoutExpired:
        raise GitError(f"git timed out after {_TIMEOUT}s — is /mnt/c awake?")
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise GitError(detail[0] if detail else f"git exited {proc.returncode}")
    return proc.stdout


def repo_root():
    """The vault repo, discovered from WIKI_DIR — never from the process cwd.

    This is the sharp edge in the whole module. cfc runs with its cwd in
    ~/projects/cfc, which is *itself* a git repo, so a plain `git -C .` here
    would happily diff and commit cfc's own source tree while calling it the
    wiki. Anchoring discovery at WIKI_DIR means the answer cannot depend on
    where the process happened to be started.
    """
    wiki = wiki_dir()
    if not wiki:
        raise GitError("WIKI_DIR is not configured")
    if not wiki.is_dir():
        raise GitError(f"WIKI_DIR does not exist: {wiki}")

    out = _git(wiki, "rev-parse", "--show-toplevel").strip()
    if not out:
        raise GitError(f"{wiki} is not inside a git repository")
    root = Path(out).resolve()

    # Containment, checked rather than assumed. rev-parse walks *upward*, so a
    # misconfigured WIKI_DIR could resolve to some unrelated ancestor repo.
    if root != wiki and root not in wiki.parents:
        raise GitError(f"{wiki} is not contained by the repo at {root}")
    return root


def _pathspec(scope, root):
    """The `--` arguments limiting a command to `scope`. [] means whole repo.

    Returned as a list so it splices into an argv, and always introduced by
    `--`: without it git would be free to read a path that happens to look like
    a revision as one.

    `root` is passed in rather than looked up. Every caller has already paid
    for one `repo_root()` — which is a subprocess across the /mnt/c bridge —
    and calling it again here would quietly double the cost of every command.
    """
    if scope == ALL:
        return []
    wiki = wiki_dir()
    rel = wiki.relative_to(root) if wiki != root else Path(".")
    return ["--", str(rel)]


class Change:
    """One changed path, as git sees it."""

    def __init__(self, code, path, orig=None):
        self.code = code          # two-char porcelain XY
        self.path = path
        self.orig = orig          # rename source, if any

    @property
    def untracked(self):
        return self.code == "??"

    @property
    def label(self):
        """The porcelain code as a word. Index and worktree collapse into one
        because this is a review screen, not a staging UI — `:wiki commit` adds
        everything in scope anyway, so 'staged or not' is not a distinction the
        human has to act on."""
        if self.untracked:
            return "new"
        letters = set(self.code.replace(" ", ""))
        for letter, word in (("D", "deleted"), ("R", "renamed"),
                             ("A", "added"), ("M", "modified")):
            if letter in letters:
                return word
        return "changed"

    def __repr__(self):
        return f"<Change {self.code} {self.path}>"


def _parse_status(raw):
    """Parse `git status --porcelain -z` into Changes.

    `-z` rather than plain porcelain: without it git quotes and escapes any
    path containing a space or a non-ASCII byte, and this vault's paths are
    `03 resources/wiki db/...`. Every path here has a space in it, so the
    quoted form is the normal case rather than the exotic one.
    """
    fields = [f for f in raw.split("\0") if f]
    changes, i = [], 0
    while i < len(fields):
        entry = fields[i]
        code, path = entry[:2], entry[3:]
        i += 1
        orig = None
        # A rename emits its source as the *next* NUL-separated field.
        if "R" in code or "C" in code:
            if i < len(fields):
                orig = fields[i]
                i += 1
        changes.append(Change(code, path, orig))
    return changes


def status(scope=WIKI, root=None):
    """Changed paths in `scope`. Sorted by path."""
    root = root or repo_root()
    raw = _git(root, "status", "--porcelain", "-z", *_pathspec(scope, root))
    return sorted(_parse_status(raw), key=lambda c: c.path)


def summary():
    """(wiki_changes, other_changes) — what `:wiki` prints with no argument.

    The vault count is computed as everything minus the wiki's own, so the two
    lines can never disagree with each other the way two separate git calls
    could if a file changed between them.
    """
    root = repo_root()
    everything = status(ALL, root)
    wiki_paths = {c.path for c in status(WIKI, root)}
    wiki = [c for c in everything if c.path in wiki_paths]
    other = [c for c in everything if c.path not in wiki_paths]
    return wiki, other


def diff(scope=WIKI):
    """The textual diff for `scope`, tracked files only.

    Untracked files are deliberately absent: they have no baseline to diff
    against, and the alternative — `git add --intent-to-add` — mutates the
    index as a side effect of *looking*, which a read command must not do.
    `status()` reports them, so nothing is hidden; it just isn't a diff.
    """
    root = repo_root()
    spec = _pathspec(scope, root)
    # HEAD rather than the index, so staged and unstaged changes both appear.
    # A vault edited from Obsidian is never staged, but a half-finished
    # terminal session can leave it that way and the diff must still be true.
    return _git(root, "diff", "HEAD", *spec)


def tracked_count(scope=WIKI):
    root = repo_root()
    raw = _git(root, "ls-files", "-z", *_pathspec(scope, root))
    return len([f for f in raw.split("\0") if f])


def commit(message, scope=WIKI):
    """Stage and commit everything in `scope`. Returns (short_hash, subject).

    Both halves carry the pathspec, and the second one is the load-bearing
    half: `git add -- <spec>` alone would still let a `git commit` sweep up
    anything already staged elsewhere in the vault. Passing the pathspec to
    `commit` too means the resulting commit contains scope and nothing else,
    whatever state the index was left in by something other than cfc.
    """
    message = (message or "").strip()
    if not message:
        raise GitError("a commit needs a message")

    root = repo_root()
    spec = _pathspec(scope, root)
    if not status(scope, root):
        raise GitError("nothing to commit")

    # -A so deletions count. Within the pathspec, a page removed from the wiki
    # is as much a change as one added, and a commit that silently skipped
    # deletions would leave the repo claiming pages that are gone.
    _git(root, "add", "-A", *(spec or ["--", "."]))
    _git(root, "commit", "-m", message, *spec)

    line = _git(root, "log", "-1", "--pretty=%h %s").strip()
    short, _, subject = line.partition(" ")
    return short, subject


def log(limit=5, scope=WIKI):
    """Recent commits touching `scope`, newest first, as (hash, when, subject)."""
    root = repo_root()
    raw = _git(root, "log", f"-{int(limit)}",
               "--pretty=%h\x1f%ad\x1f%s", "--date=short", *_pathspec(scope, root))
    out = []
    for line in raw.strip().splitlines():
        parts = line.split("\x1f")
        if len(parts) == 3:
            out.append(tuple(parts))
    return out
