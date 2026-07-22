#!/usr/bin/env python3
"""
test_complete.py — `:attach` tab completion. No API calls.

    python3 tests/test_complete.py

This suite exists because of how the last bug got in. `complete.py` wired
itself into **readline**; then input moved to prompt_toolkit, which implements
its own line editing and never consults readline. Completion stopped happening
on the interactive path and *nothing failed* — no error, no test, no warning,
just a Tab key that quietly did nothing for however long it took someone to
notice. So the first thing pinned here is the boring thing: the object the REPL
actually hands to prompt_toolkit produces completions.

The rest:
- **Vault before repo.** When a name exists in both, the vault copy is the one
  being reached for, and the first candidate is what Tab accepts without a
  second keystroke.
- **The jail holds.** A completer is a courtesy, not a control — `do_attach`'s
  guard is the boundary — but offering a path that `:attach` will then refuse
  wastes an afternoon, so denied and out-of-root paths are never offered.
- **MIN_CHARS.** Tab on a bare fragment must not dump a directory.

Everything runs against temp roots; `complete.ATTACH_ROOTS` and `WIKI_DIR` are
patched out, so this never scans the real vault.
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import complete

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


class Roots:
    """A temp repo and a temp vault, both holding a file of the same name."""

    def __init__(self, tmp):
        base = Path(tmp).resolve()
        assert str(base).startswith(tempfile.gettempdir()), base

        self.repo = base / "cfc"
        self.vault = base / "cooking for cats"
        self.wiki = self.vault / "03 resources" / "wiki db"
        self.inbox = self.vault / "00 inbox"
        for d in (self.repo, self.wiki, self.inbox):
            d.mkdir(parents=True, exist_ok=True)

        # The collision the ordering rule exists for.
        (self.repo / "notes.md").write_text("repo copy\n")
        (self.inbox / "notes.md").write_text("vault copy\n")

        (self.repo / "HANDOVER.md").write_text("x\n")
        (self.repo / "config.py").write_text("API_KEY = 'secret'\n")
        (self.repo / "picture.png").write_text("not text\n")
        (base / "outside.md").write_text("out of jail\n")

    def __enter__(self):
        self._saved = (complete.ATTACH_ROOTS, complete.WIKI_DIR)
        # Repo first, deliberately: that is the real config's order, and the
        # point of _ordered_roots is that it no longer decides the outcome.
        complete.ATTACH_ROOTS = (self.repo, self.vault)
        complete.WIKI_DIR = str(self.wiki)
        return self

    def __exit__(self, *exc):
        (complete.ATTACH_ROOTS, complete.WIKI_DIR) = self._saved


class Routines:
    """A temp ROUTINE_DIR holding one good routine and one broken one.

    `routines.routine_dir` is patched rather than config, so this never reads
    the real vault — and the broken one is broken the way the real one was
    (a non-slug id), because "still offered while unrunnable" is the property
    being pinned.
    """

    GOOD = ("---\nid: wiki-maintainer\nname: Wiki Maintainer Suggest\n"
            "prompt: x.md\ntrigger: command\non_failure: retry\n"
            "enabled: true\n---\n\nbody\n")
    BROKEN = ("---\nid: zz-broken\nname: zz broken\n"
              "prompt: nope.md\ntrigger: command\non_failure: retry\n"
              "enabled: true\n---\n\nbody\n")

    def __init__(self, tmp):
        self.dir = Path(tmp) / "routines"
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "wiki maintainer.md").write_text(self.GOOD)
        (self.dir / "zz broken.md").write_text(self.BROKEN)

    def __enter__(self):
        import routines
        self.mod = routines
        self._saved = routines.routine_dir
        routines.routine_dir = lambda: self.dir
        return self

    def __exit__(self, *exc):
        self.mod.routine_dir = self._saved


def completions(line):
    """What prompt_toolkit would actually offer for `line`."""
    from prompt_toolkit.document import Document
    c = complete.make_completer()
    if c is None:
        return None
    return [x.text for x in c.get_completions(Document(line, len(line)), None)]


def main():
    print("\n--- the front end the REPL actually uses ---")
    c = complete.make_completer()
    ok("make_completer returns a prompt_toolkit Completer", c is not None)
    if c is not None:
        from prompt_toolkit.completion import Completer
        ok("...and it really is one", isinstance(c, Completer), type(c))

    # ui.py must not import complete.py — invariant #4 puts ui at the bottom
    # of the dependency graph, which is why the completer is injected.
    ui_src = (ROOT / "ui.py").read_text()
    ok("ui.py does not import complete.py",
       "import complete" not in ui_src and "from complete" not in ui_src)
    ok("...and exposes set_completer for the injection",
       "def set_completer" in ui_src)
    ok("main.py wires the completer in",
       "set_completer(make_completer())" in (ROOT / "main.py").read_text())

    with tempfile.TemporaryDirectory() as tmp:
        with Roots(tmp) as r:
            print("\n--- vault before repo ---")
            roots = complete._ordered_roots()
            ok("the vault sorts first despite being second in config",
               roots[0] == r.vault.resolve(), roots)

            got = completions(":attach notes")
            ok("a name in both roots offers both", len(got) == 2, got)
            ok("...vault first, because Tab takes the first one",
               got and "cooking for cats" in got[0], got)

            print("\n--- matching ---")
            got = completions(":attach hando")
            ok("matching is case-insensitive",
               any("HANDOVER.md" in g for g in got), got)

            got = completions(":attach no")
            ok("a stem under MIN_CHARS offers nothing", got == [], got)

            got = completions("hello wor")
            ok("a line that isn't :attach offers nothing", got == [], got)

            print("\n--- what must never be offered ---")
            got = completions(":attach config")
            ok("config.py is never offered — it is on the deny list",
               got == [], got)

            got = completions(":attach pictu")
            ok("a non-attachable extension is not offered", got == [], got)

            got = completions(":attach outsi")
            ok("a file outside every root is not offered", got == [], got)

            print("\n--- directories ---")
            got = completions(":attach 00 in")
            ok("a directory is offered with a trailing slash",
               got and got[0].endswith("/"), got)

    print("\n--- ':routine' completion ---")
    with tempfile.TemporaryDirectory() as tmp:
        with Routines(tmp):
            got = completions(":routine ")
            ok("a bare Tab lists every routine — MIN_CHARS is a path rule",
               got == ["wiki-maintainer", "Wiki Maintainer Suggest",
                       "zz-broken", "zz broken"], got)

            got = completions(":routine wiki-")
            ok("an id prefix completes the id", got == ["wiki-maintainer"], got)

            got = completions(":routine Wiki M")
            ok("a display name completes too, spaces and all",
               got == ["Wiki Maintainer Suggest"], got)

            # The id sorts first: it is shorter to type, and the head of the
            # list is what Tab takes without a second keystroke.
            got = completions(":routine w")
            ok("the id is offered before the name",
               got[:2] == ["wiki-maintainer", "Wiki Maintainer Suggest"], got)

            got = completions(":routine ne")
            ok("':routine new' is offered", got == ["new"], got)

            # A routine you can't run is the one you're most likely reaching
            # for — to fix it. Hiding it would read as it having been deleted.
            ok("a broken routine is still offered",
               "zz-broken" in completions(":routine zz"),
               completions(":routine zz"))

    ok("a line that isn't a completable command is inert",
       completions(":help") == [], completions(":help"))

    print("\n--- the readline half still exists for the input() path ---")
    src = (ROOT / "complete.py").read_text()
    ok("install() is still defined", "def install(" in src)
    ok("both front ends share _dispatch",
       src.count("_dispatch(") >= 3, src.count("_dispatch("))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
