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
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import mover
from parse import PREFIX
import wikigit


def git(cwd, *args):
    return subprocess.run(("git",) + args, cwd=str(cwd), check=True,
                          capture_output=True, text=True).stdout

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
        self.journal_out = self.outbox / "journal"    # the journal proposal folder
        self.areas = self.root / "02 areas" / "daily"
        self.wiki = self.root / "03 resources" / "wiki db"
        self.journal = self.root / "03 resources" / "journal"
        self.losers = self.root / "03 resources" / "loser corner"
        self.outside = Path(tmp) / "elsewhere"
        for d in (self.outbox, self.wiki_out, self.journal_out, self.areas,
                  self.wiki, self.journal, self.losers, self.outside):
            d.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        self._saved = (mover.move_roots, mover.outbox_roots, mover.wiki_dir,
                       mover.journal_dir, mover.loser_dir,
                       wikigit.wiki_dir, wikigit.journal_dir)
        mover.move_roots = lambda: (self.root.resolve(),)
        mover.outbox_roots = lambda: (self.outbox.resolve(),)
        mover.wiki_dir = lambda: self.wiki.resolve()
        mover.journal_dir = lambda: self.journal.resolve()
        # Invariant #1, applied to a folder rather than a db: without this the
        # drop tests would move fixture files into the *real* losers' corner,
        # because loser_dir() reads config like every other path here.
        mover.loser_dir = lambda: self.losers.resolve()
        # The journal guard asks wikigit for the corpus's git state, and
        # wikigit anchors repo discovery at WIKI_DIR — so both have to point
        # into this temp vault or the guard would consult the *real* repo.
        wikigit.wiki_dir = lambda: self.wiki.resolve()
        wikigit.journal_dir = lambda: self.journal.resolve()
        return self

    def __exit__(self, *exc):
        (mover.move_roots, mover.outbox_roots, mover.wiki_dir,
         mover.journal_dir, mover.loser_dir,
         wikigit.wiki_dir, wikigit.journal_dir) = self._saved

    def git_init(self):
        """Make the vault a git repo with everything committed — the state a
        journal move requires. Returns nothing; call `commit_all` to re-clean."""
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "config", "user.name", "Test")
        self.commit_all("baseline")

    def commit_all(self, msg="wip"):
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", msg)

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

        print("\n--- the journal: filing REPLACES a live file ---")
        # This is the one place the mover's "a target that exists is a refusal"
        # rule cannot hold — replacing the live file *is* a rollover. What
        # stands in for it is git: the corpus must be committed, so the move is
        # inspectable and revertable. These assertions are the negative half of
        # that trade and matter more than the happy path.
        v.journal.mkdir(parents=True, exist_ok=True)
        live = v.journal / "st memory.md"
        live.write_text("# short term\n\noriginal content\n", encoding="utf-8")
        v.git_init()

        draft = v.propose("st memory.md", body="# short term\n\nrolled over\n",
                          folder=v.journal_out)
        p = mover.plan(draft)
        ok("a journal draft is filable against a clean corpus", p.ok, p.reason)
        ok("...routed as a journal proposal", p.into_journal)
        ok("...targeting the live file of the same name",
           p.target == live.resolve(), p.target)
        ok("...and flagged as replacing, not merely moving", p.replaces)
        ok("...found by list_proposals from the subfolder",
           any(x.into_journal and x.name == "st memory.md"
               for x in mover.list_proposals()))

        print("\n--- an uncommitted journal refuses the move ---")
        stray = v.journal / "hand edit.md"
        stray.write_text("edited by hand\n", encoding="utf-8")
        p_dirty = mover.plan(draft)
        ok("a dirty corpus is refused", not p_dirty.ok, p_dirty.reason)
        ok("...and the refusal names the fix",
           f"{PREFIX}wiki commit journal" in p_dirty.reason,
           p_dirty.reason)
        ok("...the live file is untouched",
           live.read_text(encoding="utf-8").endswith("original content\n"))
        try:
            mover.commit(p_dirty)
            ok("...and committing it raises", False)
        except mover.MoveError:
            ok("...and committing it raises", True)
        stray.unlink()

        print("\n--- the git check is re-run at write time, not just at plan ---")
        # The plan-time check drew the screen; this is the one that guards the
        # write. A corpus that goes dirty between listing and filing has lost
        # the undo the whole overwrite rests on.
        fresh = mover.plan(draft)
        ok("clean again, so it plans ok", fresh.ok, fresh.reason)
        race = v.journal / "appeared between plan and commit.md"
        race.write_text("late\n", encoding="utf-8")
        try:
            mover.commit(fresh)
            ok("a corpus that went dirty mid-review is refused", False)
        except mover.MoveError:
            ok("a corpus that went dirty mid-review is refused", True)
        ok("...the live file survived the refusal",
           live.read_text(encoding="utf-8").endswith("original content\n"))
        ok("...and the draft is still in the outbox", draft.exists())
        race.unlink()

        print("\n--- an unverifiable git state fails CLOSED ---")
        # Failing open here would perform an unrecoverable overwrite. Note this
        # is the opposite direction from the run-log rule in tools.py, which
        # fails open — there, not resolving a path can only narrow what is
        # writable; here, not checking can only widen what is destroyed.
        saved_status = wikigit.status

        def explode(*a, **kw):
            raise wikigit.GitError("no repo here")

        wikigit.status = explode
        try:
            p_blind = mover.plan(draft)
            ok("git unavailable refuses the move", not p_blind.ok, p_blind.reason)
            ok("...and says the state could not be checked",
               "git state" in p_blind.reason, p_blind.reason)
        finally:
            wikigit.status = saved_status

        print("\n--- the replacement itself ---")
        good = mover.plan(draft)
        target = mover.commit(good)
        ok("the move returns the live path", target == live.resolve(), target)
        ok("...the live file now holds the draft's content",
           "rolled over" in live.read_text(encoding="utf-8"))
        ok("...the draft has left the outbox", not draft.exists())
        ok("...and git can still see what changed",
           any("st memory.md" in c.path
               for c in wikigit.status(wikigit.JOURNAL)),
           wikigit.status(wikigit.JOURNAL))
        v.commit_all("filed")

        print("\n--- a journal draft cannot name a path out of the corpus ---")
        # The target is built from the *filename* alone, so directory parts in
        # a draft's name are structurally unable to escape. Pinned because the
        # alternative (trusting a destination: key here) is the bug this whole
        # module exists to prevent.
        sneaky = v.journal_out / "sneaky.md"
        sneaky.write_text("---\ndestination: /etc/\n---\n\nx\n", encoding="utf-8")
        ps = mover.plan(sneaky)
        ok("a destination: key in a journal draft is ignored",
           ps.target == (v.journal / "sneaky.md").resolve(), ps.target)
        sneaky.unlink()

        print("\n--- with no JOURNAL_DIR there is no journal filing ---")
        saved_jd = mover.journal_dir
        mover.journal_dir = lambda: None
        try:
            d2 = v.propose("lt memory.md", body="x\n", folder=v.journal_out)
            p2 = mover.plan(d2)
            ok("an unconfigured journal refuses rather than guessing",
               not p2.ok and "JOURNAL_DIR" in p2.reason, p2.reason)
            d2.unlink()
        finally:
            mover.journal_dir = saved_jd

        print("\n--- the outbox's own readme is not a proposal ---")
        # It has no destination and never will, so it sat permanently at the
        # top of :outbox reading REFUSED, and ':file 1 drop' would bin the
        # folder's own documentation.
        readme = v.outbox / "99 readme.md"
        readme.write_text("Outbox readme\n\nWhat this folder is for.\n",
                          encoding="utf-8")
        ok("it is not listed as a proposal",
           not any(x.name == "99 readme.md" for x in mover.list_proposals()))
        pr = mover.plan(readme)
        ok("...and planning it directly still refuses", not pr.ok, pr.reason)
        try:
            mover.drop(pr)
            ok("...and it cannot be dropped", False)
        except mover.MoveError:
            ok("...and it cannot be dropped", True)
        ok("...so it is still there", readme.exists())
        for variant in ("readme.md", "00 readme.md", "README.md"):
            ok(f"the convention covers {variant}", mover.is_reserved(variant))
        ok("an ordinary draft is not reserved",
           not mover.is_reserved("st memory.md"))

        print("\n--- dropping ---")
        p = mover.plan(v.outbox / "b-bad.md")
        dropped = mover.drop(p)
        ok("a dropped file leaves the outbox",
           not (v.outbox / "b-bad.md").exists())
        ok("...but still exists — rejecting is not destroying", dropped.exists())
        ok("...timestamped so two drops don't collide",
           "b-bad.md" in dropped.name and dropped.name != "b-bad.md",
           dropped.name)
        ok("...and lands in the losers' corner, under its corpus",
           dropped.parent == (v.losers / "notes").resolve(), dropped.parent)

        print("\n--- a declined draft is filed by corpus, not pooled ---")
        # The reason to keep a declined draft is to debug the prompt that wrote
        # it, and that is a per-routine question — a flat folder means sorting
        # them by hand later.
        jd = v.propose("mt memory.md", body="declined\n", folder=v.journal_out)
        jdrop = mover.drop(mover.plan(jd))
        ok("a journal draft goes to the journal corner",
           jdrop.parent == (v.losers / "journal").resolve(), jdrop.parent)
        wd = v.propose("draft.md", body="declined\n", folder=v.wiki_out)
        wdrop = mover.drop(mover.plan(wd))
        ok("a wiki draft goes to the wiki corner",
           wdrop.parent == (v.losers / "wiki").resolve(), wdrop.parent)

        print("\n--- declining records why, on the draft itself ---")
        # A folder of near-identical rejected drafts is close to useless for
        # debugging a prompt if nothing says what was wrong with each one, and
        # a reason kept in a separate log is a join you have to make later from
        # a filename and a timestamp.
        rich_fm = ("---\nid: \"20260721080410\"\ntitle: Short term memory\n"
                   "related:\n  - \"[[mt memory]]\"\n---\n\n# Body\n")
        d3 = v.journal_out / "st memory.md"
        d3.write_text(rich_fm, encoding="utf-8")
        when = __import__("datetime").datetime(2026, 7, 24, 23, 30)
        out = mover.decline(mover.plan(d3), "invented a day: no notes existed",
                            when=when)
        text = out.read_text(encoding="utf-8")
        ok("the draft leaves the outbox", not d3.exists())
        ok("...and is stamped with the date it was declined",
           "declined: 2026-07-24" in text, text)
        ok("...and with the reason",
           "invented a day" in text, text)
        # A reason is free text typed at a prompt. An unquoted colon would make
        # the block unparseable and cost the file its frontmatter entirely.
        import yaml as _y
        fm_back, _, _ = mover.split_frontmatter(text)
        ok("a colon in the reason does not break the frontmatter",
           fm_back.get("declined_reason") == "invented a day: no notes existed",
           fm_back)
        # The vault's own conventions must survive: an unquoted digit id and a
        # wikilink both get mangled by a yaml round-trip, so the block is
        # edited by hand rather than re-dumped.
        ok("...the original frontmatter is preserved verbatim",
           'id: "20260721080410"' in text and "[[mt memory]]" in text, text)
        ok("...and the body is untouched", text.rstrip().endswith("# Body"), text)

        print("\n--- declining with no reason, and a file with no frontmatter ---")
        bare = v.journal_out / "bare.md"
        bare.write_text("just a body, no frontmatter\n", encoding="utf-8")
        out2 = mover.decline(mover.plan(bare), "", when=when)
        t2 = out2.read_text(encoding="utf-8")
        ok("frontmatter is created when there was none",
           t2.startswith("---\ndeclined: 2026-07-24"), t2)
        ok("...with no empty reason key", "declined_reason" not in t2, t2)
        ok("...and the body survives", "just a body" in t2, t2)
        ok("'drop' still works as the terse form",
           callable(mover.drop))

        print("\n--- with no LOSER_DIR, drops fall back to the outbox ---")
        saved_ld = mover.loser_dir
        mover.loser_dir = lambda: None
        try:
            old = v.propose("legacy.md", "02 areas/daily/")
            legacy = mover.drop(mover.plan(old))
            ok("an unconfigured losers' corner still drops safely",
               legacy.parent == (v.outbox / "dropped").resolve(), legacy.parent)
        finally:
            mover.loser_dir = saved_ld

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
