#!/usr/bin/env python3
"""
test_wikigit.py — the vault repo seen from the REPL. No API calls, no network.

    python3 tests/test_wikigit.py

The case worth having is **scope containment**: `:wiki commit` must produce a
commit holding wiki changes and nothing else, *even when something outside the
wiki is already staged*. `git add -- <spec>` alone does not give you that — the
subsequent `git commit` would sweep up whatever was in the index already. Only
passing the pathspec to `commit` too closes it, and the only way to know that
stayed true is to stage something outside the scope and check it survived.

Second: paths in this vault all contain spaces (`03 resources/wiki db/...`),
so `git status --porcelain` quotes them and the quoted form is the *normal*
case here, not the exotic one. The `-z` parse is pinned against real paths with
spaces and non-ASCII, because a parser that only ever saw `foo.md` would look
fine and break on every real file.

Everything runs in a temp git repo. `wikigit.wiki_dir` is patched out, and
**every fixture asserts its path is under tempdir before writing anything** —
invariant #1, the same reason backup.py checks before it acts rather than
after. The real vault is never touched: a bug in this file must not be able to
commit, stage or rewrite Cas's notes.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import wikigit

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def git(repo, *args):
    """Raw git, for arranging fixtures — deliberately not wikigit's own _git,
    so a bug in the module under test cannot also break the setup and hide
    itself behind a passing assertion."""
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout


class Repo:
    """A temp vault repo: a wiki dir, an `02 areas` dir, one baseline commit.

    Mirrors the real vault's shape closely enough for the parsing to be real —
    spaces in every path, a numbered-folder layout, one page with a non-ASCII
    name.
    """

    def __init__(self, tmp):
        self.root = Path(tmp).resolve() / "cooking for cats"
        self.wiki = self.root / "03 resources" / "wiki db"
        self.areas = self.root / "02 areas"

        # Invariant #1: assert the path before anything writes to it. A test
        # that checks afterwards is how the real database got deleted once.
        assert str(self.root).startswith(tempfile.gettempdir()), self.root

        self.wiki.mkdir(parents=True)
        self.areas.mkdir(parents=True)

        git(self.root.parent, "init", "-q", str(self.root))
        git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "config", "user.name", "Test")
        (self.wiki / "20260101000000.md").write_text("# page one\n")
        (self.wiki / "20260101000001.md").write_text("# page two\n")
        (self.areas / "medical notes.md").write_text("# private\n")
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "baseline")

    def __enter__(self):
        self._saved = wikigit.wiki_dir
        wikigit.wiki_dir = lambda: self.wiki
        return self

    def __exit__(self, *exc):
        wikigit.wiki_dir = self._saved

    def files_in_head(self):
        return set(git(self.root, "show", "--name-only", "--pretty=",
                       "HEAD").strip().splitlines())

    def subjects(self):
        return git(self.root, "log", "--pretty=%s").strip().splitlines()


def main():
    print("\n--- discovery and containment ---")
    with tempfile.TemporaryDirectory() as tmp:
        with Repo(tmp) as r:
            ok("repo_root finds the repo from WIKI_DIR",
               wikigit.repo_root() == r.root, wikigit.repo_root())
            ok("tracked_count counts wiki pages only",
               wikigit.tracked_count() == 2, wikigit.tracked_count())
            ok("...and the whole repo under 'all'",
               wikigit.tracked_count(wikigit.ALL) == 3)

    # The cwd trap: cfc runs inside its own git repo, so a module that
    # discovered the repo from the process cwd would diff and commit cfc's
    # source while calling it the wiki. Discovery must anchor at WIKI_DIR.
    with tempfile.TemporaryDirectory() as tmp:
        with Repo(tmp) as r:
            saved = os.getcwd()
            try:
                os.chdir(ROOT)
                ok("repo discovery ignores the process cwd",
                   wikigit.repo_root() == r.root, wikigit.repo_root())
            finally:
                os.chdir(saved)

    with tempfile.TemporaryDirectory() as tmp:
        loose = Path(tmp).resolve() / "not a repo"
        loose.mkdir()
        saved = wikigit.wiki_dir
        wikigit.wiki_dir = lambda: loose
        try:
            try:
                wikigit.repo_root()
                ok("a WIKI_DIR outside any repo is refused", False)
            except wikigit.GitError as e:
                ok("a WIKI_DIR outside any repo is refused", True, e)

            missing = Path(tmp).resolve() / "gone"
            wikigit.wiki_dir = lambda: missing
            try:
                wikigit.repo_root()
                ok("a missing WIKI_DIR is refused, not created", False)
            except wikigit.GitError:
                ok("a missing WIKI_DIR is refused, not created",
                   not missing.exists())
        finally:
            wikigit.wiki_dir = saved

    print("\n--- status: scoping and the -z parse ---")
    with tempfile.TemporaryDirectory() as tmp:
        with Repo(tmp) as r:
            (r.wiki / "20260101000000.md").write_text("# page one, edited\n")
            (r.wiki / "a new page.md").write_text("# new\n")
            (r.wiki / "20260101000001.md").unlink()
            (r.areas / "medical notes.md").write_text("# private, edited\n")

            wiki = wikigit.status()
            paths = [c.path for c in wiki]
            ok("status is scoped to the wiki by default",
               all(p.startswith("03 resources/wiki db/") for p in paths), paths)
            ok("...and sees all three change kinds", len(wiki) == 3, paths)

            labels = {c.label for c in wiki}
            ok("modified / new / deleted are all labelled",
               labels == {"modified", "new", "deleted"}, labels)

            # The whole reason for -z. Every path in this vault has a space.
            ok("paths with spaces survive the parse",
               "03 resources/wiki db/a new page.md" in paths, paths)

            everything = [c.path for c in wikigit.status(wikigit.ALL)]
            ok("'all' widens to the rest of the vault",
               "02 areas/medical notes.md" in everything, everything)
            ok("...and the default scope excluded it",
               "02 areas/medical notes.md" not in paths)

            w, other = wikigit.summary()
            ok("summary splits wiki from the rest", len(w) == 3 and len(other) == 1,
               (len(w), len(other)))

            text = wikigit.diff()
            ok("diff shows tracked edits", "page one, edited" in text)
            ok("...and deletions", "page two" in text)
            ok("...but not untracked files, which have no baseline",
               "a new page.md" not in text)
            ok("an untracked file is still reported by status",
               any(c.untracked for c in wiki))

    print("\n--- diff never mutates ---")
    with tempfile.TemporaryDirectory() as tmp:
        with Repo(tmp) as r:
            (r.wiki / "untracked.md").write_text("# nope\n")
            before = git(r.root, "status", "--porcelain")
            wikigit.diff()
            wikigit.diff(wikigit.ALL)
            wikigit.status()
            ok("looking does not stage anything",
               git(r.root, "status", "--porcelain") == before)

    print("\n--- commit: scope containment ---")
    with tempfile.TemporaryDirectory() as tmp:
        with Repo(tmp) as r:
            (r.wiki / "20260101000000.md").write_text("# edited in wiki\n")
            (r.areas / "medical notes.md").write_text("# edited outside\n")

            # The load-bearing case. Something outside the wiki is already
            # staged when the commit runs — as it would be if a terminal
            # session had been left half-finished.
            git(r.root, "add", "02 areas/medical notes.md")

            short, subject = wikigit.commit("wiki only")
            files = r.files_in_head()
            ok("commit contains the wiki change",
               "03 resources/wiki db/20260101000000.md" in files, files)
            ok("...and NOT the staged file outside the scope",
               "02 areas/medical notes.md" not in files, files)
            ok("...which is still uncommitted afterwards",
               "02 areas/medical notes.md" in
               [c.path for c in wikigit.status(wikigit.ALL)])
            ok("commit returns the short hash and subject",
               len(short) >= 7 and subject == "wiki only", (short, subject))

    print("\n--- commit: deletions, refusals, 'all' ---")
    with tempfile.TemporaryDirectory() as tmp:
        with Repo(tmp) as r:
            (r.wiki / "20260101000001.md").unlink()
            wikigit.commit("drop a page")
            ok("a deleted page is committed as a deletion",
               "03 resources/wiki db/20260101000001.md" in r.files_in_head())
            ok("...and the wiki is clean afterwards", wikigit.status() == [])

            try:
                wikigit.commit("nothing doing")
                ok("an empty commit is refused", False)
            except wikigit.GitError as e:
                ok("an empty commit is refused", "nothing to commit" in str(e), e)

            (r.wiki / "20260101000000.md").write_text("# again\n")
            for bad in ("", "   ", None):
                try:
                    wikigit.commit(bad)
                    ok(f"a blank message is refused ({bad!r})", False)
                    break
                except wikigit.GitError:
                    pass
            else:
                ok("a blank message is refused", True)
            ok("...and nothing was committed by the attempt",
               r.subjects()[0] == "drop a page", r.subjects())

    with tempfile.TemporaryDirectory() as tmp:
        with Repo(tmp) as r:
            (r.wiki / "20260101000000.md").write_text("# w\n")
            (r.areas / "medical notes.md").write_text("# a\n")
            wikigit.commit("everything", wikigit.ALL)
            files = r.files_in_head()
            ok("'all' commits outside the wiki too",
               "02 areas/medical notes.md" in files and
               "03 resources/wiki db/20260101000000.md" in files, files)
            ok("...leaving the repo clean",
               wikigit.status(wikigit.ALL) == [])

    print("\n--- there is no push ---")
    # Read off the AST rather than grepping the source, so the assertion is
    # about the git subcommands the module can actually issue and not about
    # whether the word appears in a comment. The prose here says "there is no
    # push" a dozen times; a substring check would fail on its own explanation.
    import ast

    tree = ast.parse((ROOT / "wikigit.py").read_text())
    subcommands = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name != "_git":
            continue
        # args[0] is the repo; the subcommand is the one after it.
        for a in node.args[1:]:
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                subcommands.add(a.value)
                break

    ok("the module issues only known git subcommands",
       subcommands == {"rev-parse", "status", "diff", "ls-files", "add",
                       "commit", "log"}, sorted(subcommands))
    ok("...so there is no push", "push" not in subcommands)
    ok("...and no remote is ever configured", "remote" not in subcommands)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
