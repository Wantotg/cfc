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
        self.wiki_out = self.outbox / "wiki"          # the wiki proposal folder
        self.areas = self.root / "02 areas" / "daily"
        self.wiki = self.root / "03 resources" / "wiki db"
        self.outside = Path(tmp) / "elsewhere"
        for d in (self.outbox, self.wiki_out, self.areas, self.wiki,
                  self.outside):
            d.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        self._saved = (mover.move_roots, mover.outbox_roots, mover.wiki_dir)
        mover.move_roots = lambda: (self.root.resolve(),)
        mover.outbox_roots = lambda: (self.outbox.resolve(),)
        mover.wiki_dir = lambda: self.wiki.resolve()
        return self

    def __exit__(self, *exc):
        (mover.move_roots, mover.outbox_roots, mover.wiki_dir) = self._saved

    def propose(self, name, destination=None, body="Some content.", extra="",
                folder=None):
        """Write a file into the outbox, optionally with a destination.

        `folder` overrides where it lands — used to drop a draft straight into
        the wiki proposal subfolder.
        """
        fm = ""
        if destination is not None or extra:
            lines = []
            if destination is not None:
                lines.append(f"destination: {destination}")
            if extra:
                lines.append(extra)
            fm = "---\n" + "\n".join(lines) + "\n---\n\n"
        p = (folder or self.outbox) / name
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

        print("\n--- the wiki is now filable, id stamped at approval time ---")
        # A draft in the outbox wiki/ subfolder is wiki-bound by location and
        # needs no destination key. With no id yet, it is filable — the id is
        # stamped on commit, so the target isn't known until then.
        draft = v.propose("new page.md", body="# Cats\n\nA fact.",
                          folder=v.wiki_out)
        pp = mover.plan(draft)
        ok("a wiki draft with no id is filable", pp.ok, pp.reason)
        ok("...flagged as wiki-bound", pp.into_wiki)
        ok("...and marked as needing an id", pp.needs_id and pp.wiki_id is None)

        target = mover.commit(pp)
        ok("...it lands in the wiki corpus", target.parent == v.wiki.resolve(),
           target)
        ok("...named <id>.md (14-digit timestamp)",
           target.stem.isdigit() and len(target.stem) == 14, target.name)
        ok("...and leaves the outbox", not draft.exists())
        stamped = target.read_text(encoding="utf-8")
        ok("...with the id stamped into the frontmatter",
           f"id: {target.stem}" in stamped, stamped)
        ok("...the body preserved", "A fact." in stamped, stamped)

        # A draft that already carries an id keeps it, and is named for it.
        keep = v.propose("with id.md", extra="id: 20260101120000",
                         body="Body.", folder=v.wiki_out)
        pp = mover.plan(keep)
        ok("an existing id is honoured, not restamped",
           pp.ok and pp.wiki_id == "20260101120000" and not pp.needs_id,
           (pp.wiki_id, pp.needs_id))
        target = mover.commit(pp)
        ok("...and names the file for it", target.name == "20260101120000.md",
           target.name)

        # Re-filing a page whose id already exists is an edit, not a new file —
        # refused rather than clobbered.
        dup = v.propose("dup.md", extra="id: 20260101120000", body="Other.",
                        folder=v.wiki_out)
        pp = mover.plan(dup)
        ok("a page whose id already exists is refused",
           not pp.ok and "already exists" in pp.reason, pp.reason)
        ok("...and the existing wiki page is untouched",
           "Body." in (v.wiki / "20260101120000.md").read_text()
           and "Other." not in (v.wiki / "20260101120000.md").read_text())

        # A same-second batch must get distinct ids, or import_wiki would treat
        # two pages as one.
        b1 = v.propose("batch one.md", body="One.", folder=v.wiki_out)
        b2 = v.propose("batch two.md", body="Two.", folder=v.wiki_out)
        t1 = mover.commit(mover.plan(b1))
        t2 = mover.commit(mover.plan(b2))
        ok("a same-second batch gets distinct ids", t1.name != t2.name,
           (t1.name, t2.name))

        # A top-level file may still target the wiki via destination:, and is
        # handled the same way.
        topdest = v.propose("via dest.md", "03 resources/wiki db/", body="Z.")
        pp = mover.plan(topdest)
        ok("a top-level destination into the wiki is filable too",
           pp.ok and pp.into_wiki, (pp.ok, pp.into_wiki, pp.reason))

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
        for f in list(v.outbox.glob("*.md")) + list(v.wiki_out.glob("*.md")):
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

        # The wiki proposal subfolder is a second source; a draft there lists
        # alongside the top-level ones and is wiki-bound.
        v.propose("wiki draft.md", body="Fact.", folder=v.wiki_out)
        listed = mover.list_proposals()
        names = [p.name for p in listed]
        ok("a wiki-subfolder draft is listed too", "wiki draft.md" in names, names)
        wp = next(p for p in listed if p.name == "wiki draft.md")
        ok("...and is flagged wiki-bound", wp.into_wiki and wp.ok, wp.reason)
        for f in v.wiki_out.glob("*.md"):
            f.unlink()

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
