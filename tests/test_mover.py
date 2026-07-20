#!/usr/bin/env python3
"""
test_mover.py — filing proposals out of the outbox. No API calls.

    python3 tests/test_mover.py

The case the handover explicitly asked for is here: **a `destination` outside
the vault roots is refused, not guessed at.** No nearest-match, no fallback to
a default folder. A silently-wrong path is worse than an error, because nobody
re-reads a file that was filed successfully.

The rest of the suite defends the same idea from other angles: the model's
suggestion is text, re-validated from scratch, and every way of writing a bad
one has to come back as a refusal with a reason.

Everything runs against temp directories — config's real vault paths are
patched out, so this never touches the real outbox or vault.
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import mover

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


class Vault:
    """A temp vault: an outbox, some destination folders, and a wiki."""

    def __init__(self, tmp):
        self.root = Path(tmp) / "vault"
        self.outbox = self.root / "99 outbox"
        self.areas = self.root / "02 areas" / "daily"
        self.wiki = self.root / "03 resources" / "wiki db"
        self.outside = Path(tmp) / "elsewhere"
        for d in (self.outbox, self.areas, self.wiki, self.outside):
            d.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        self._saved = (mover.move_roots, mover.outbox_roots, mover.wiki_dir)
        mover.move_roots = lambda: (self.root.resolve(),)
        mover.outbox_roots = lambda: (self.outbox.resolve(),)
        mover.wiki_dir = lambda: self.wiki.resolve()
        return self

    def __exit__(self, *exc):
        (mover.move_roots, mover.outbox_roots, mover.wiki_dir) = self._saved

    def propose(self, name, destination=None, body="Some content.", extra=""):
        """Write a file into the outbox, optionally with a destination."""
        fm = ""
        if destination is not None or extra:
            lines = []
            if destination is not None:
                lines.append(f"destination: {destination}")
            if extra:
                lines.append(extra)
            fm = "---\n" + "\n".join(lines) + "\n---\n\n"
        p = self.outbox / name
        p.write_text(fm + body, encoding="utf-8")
        return p


def main():
    with tempfile.TemporaryDirectory() as tmp, Vault(tmp) as v:

        print("\n--- a good proposal ---")
        src = v.propose("digest.md", "02 areas/daily/")
        p = mover.plan(src)
        ok("plans as filable", p.ok, p.reason)
        ok("target keeps the filename",
           p.target == (v.areas / "digest.md").resolve(), p.target)

        print("\n--- OUTSIDE THE ROOTS IS REFUSED, NOT GUESSED AT ---")
        for label, dest in (
            ("absolute path outside the vault", str(v.outside)),
            ("traversal out of the vault", "../elsewhere/"),
            ("traversal via a real folder", "02 areas/../../elsewhere/"),
            ("an absolute system path", "/etc/"),
            ("home directory", "~/"),
        ):
            bad = v.propose(f"bad-{abs(hash(label))}.md", dest)
            pp = mover.plan(bad)
            ok(f"refused: {label}", not pp.ok and bool(pp.reason), pp.reason)
            ok(f"...and nothing was moved: {label}", bad.exists())
        # The refusal must not silently become a different, valid path.
        pp = mover.plan(v.propose("nofallback.md", "/etc/"))
        ok("no fallback target is invented", pp.target is None, pp.target)

        print("\n--- a symlink out of the vault is judged as its target ---")
        escape = v.outbox / "escape"
        try:
            escape.symlink_to(v.outside, target_is_directory=True)
            pp = mover.plan(v.propose("sym.md", "99 outbox/escape/"))
            ok("symlinked destination is refused", not pp.ok, pp.reason)
        except (OSError, NotImplementedError):
            ok("symlinked destination is refused (skipped: no symlink support)",
               True)

        print("\n--- the wiki is refused outright ---")
        for label, dest in (("the wiki folder", "03 resources/wiki db/"),
                            ("a file in the wiki", "03 resources/wiki db/cats.md"),
                            ("a subfolder of the wiki",
                             "03 resources/wiki db/sources/")):
            pp = mover.plan(v.propose(f"wiki-{abs(hash(label))}.md", dest))
            ok(f"refused: {label}", not pp.ok, pp.reason)
            ok(f"...and says why: {label}",
               "import_wiki" in pp.reason, pp.reason)

        print("\n--- other things that are not filable ---")
        pp = mover.plan(v.propose("nodest.md", None))
        ok("no destination at all", not pp.ok and pp.reason == "no destination",
           pp.reason)
        pp = mover.plan(v.propose("emptydest.md", ""))
        ok("empty destination", not pp.ok, pp.reason)

        (v.areas / "clash.md").write_text("already here", encoding="utf-8")
        pp = mover.plan(v.propose("clash.md", "02 areas/daily/"))
        ok("an existing target is refused, not clobbered",
           not pp.ok and "exists" in pp.reason, pp.reason)
        ok("...and the original is untouched",
           (v.areas / "clash.md").read_text() == "already here")

        pp = mover.plan(v.propose("denied.md", "02 areas/daily/config.py"))
        ok("the deny list still applies to the target",
           not pp.ok and "deny list" in pp.reason, pp.reason)

        print("\n--- rename-on-move ---")
        src = v.propose("draft.md", "02 areas/daily/final-name.md")
        pp = mover.plan(src)
        ok("a destination naming a file renames it",
           pp.ok and pp.target.name == "final-name.md", pp.target)

        print("\n--- committing the move ---")
        src = v.propose("commitme.md", "02 areas/daily/",
                        body="# Real content\n\nBody here.")
        pp = mover.plan(src)
        target = mover.commit(pp)
        ok("the file arrives", target.exists() and target == v.areas.resolve() / "commitme.md")
        ok("...and leaves the outbox", not src.exists())
        text = target.read_text(encoding="utf-8")
        ok("the body survives", "Body here." in text, text)
        ok("the destination key is stripped", "destination:" not in text, text)
        ok("no temp debris",
           not any(f.name.startswith(".") for f in v.areas.iterdir()),
           list(v.areas.iterdir()))

        print("\n--- other frontmatter is preserved ---")
        src = v.propose("keepfm.md", "02 areas/daily/",
                        extra="title: Keep me\ntags: [a, b]")
        target = mover.commit(mover.plan(src))
        text = target.read_text(encoding="utf-8")
        ok("unrelated frontmatter survives", "title: Keep me" in text, text)
        ok("...and its destination is gone", "destination:" not in text, text)

        print("\n--- commit refuses what plan refused ---")
        pp = mover.plan(v.propose("nope.md", "/etc/"))
        try:
            mover.commit(pp)
            ok("committing a refused proposal raises", False, "it moved")
        except mover.MoveError as e:
            ok("committing a refused proposal raises", True)

        # The list you are looking at may be minutes old. commit() re-plans and
        # refuses if the answer changed — this is the check that actually
        # guards the write, not the one that drew the screen.
        src = v.propose("stale.md", "02 areas/daily/")
        pp = mover.plan(src)
        (v.areas / "stale.md").write_text("appeared later", encoding="utf-8")
        try:
            mover.commit(pp)
            ok("a stale plan is re-checked at commit time", False, "it clobbered")
        except mover.MoveError:
            ok("a stale plan is re-checked at commit time", True)
        ok("...and the file that appeared is intact",
           (v.areas / "stale.md").read_text() == "appeared later")

        print("\n--- listing ---")
        for f in list(v.outbox.glob("*.md")):
            f.unlink()
        v.propose("a-good.md", "02 areas/daily/")
        v.propose("b-bad.md", "/etc/")
        v.propose("c-none.md", None)
        (v.outbox / "routine logs").mkdir(exist_ok=True)
        (v.outbox / "routine logs" / "log.md").write_text("x", encoding="utf-8")
        listed = mover.list_proposals()
        ok("lists every top-level file", len(listed) == 3, [p.name for p in listed])
        ok("...and not the run logs",
           "log.md" not in [p.name for p in listed])
        ok("verdicts are computed at list time",
           [p.ok for p in listed] == [True, False, False],
           [(p.name, p.ok) for p in listed])

        print("\n--- dropping ---")
        p = mover.plan(v.outbox / "b-bad.md")
        dropped = mover.drop(p)
        ok("a dropped file leaves the outbox",
           not (v.outbox / "b-bad.md").exists())
        ok("...but still exists — rejecting is not destroying", dropped.exists())
        ok("...timestamped so two drops don't collide",
           "b-bad.md" in dropped.name and dropped.name != "b-bad.md",
           dropped.name)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
