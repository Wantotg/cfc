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
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import db as dbmod
import import_wiki
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

        # An `id:` key present but empty (`id:` with nothing after it) must be
        # treated as no id at all — filed once, under one generated id — not
        # serialised beside the generated one (B-1.7-05).
        blank = v.propose("blank id.md", extra="id:", body="Blank.",
                          folder=v.wiki_out)
        pp = mover.plan(blank)
        ok("a blank id plans as needing one, not honoured",
           pp.ok and pp.needs_id and pp.wiki_id is None,
           (pp.ok, pp.needs_id, pp.wiki_id))
        target = mover.commit(pp)
        stamped = target.read_text(encoding="utf-8")
        ok("...named <id>.md for the one id generated",
           target.stem.isdigit() and len(target.stem) == 14, target.name)
        ok("...exactly one id line is written, matching the filename",
           stamped.count("id:") == 1 and f"id: {target.stem}" in stamped,
           stamped)

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

        print("\n--- title matching for /file ---")
        for f in v.outbox.glob("*.md"):
            f.unlink()
        v.propose("no-title.md", "02 areas/daily/", body="no title here")
        v.propose("titled-a.md", "02 areas/daily/", extra="title: Aquarium Notes")
        v.propose("titled-b.md", "02 areas/daily/", extra="title: AQUARIUM NOTES")
        v.propose("unique.md", "02 areas/daily/", extra="title: Unique One")
        broken = v.outbox / "broken-fm.md"
        broken.write_text('---\ntitle: "unterminated\n---\n\nbody\n',
                          encoding="utf-8")
        proposals = mover.list_proposals()

        ok("title reads from readable frontmatter",
           mover.proposal_title(v.outbox / "titled-a.md") == "Aquarium Notes")
        ok("a missing title reads as empty, not raising",
           mover.proposal_title(v.outbox / "no-title.md") == "")
        ok("malformed frontmatter reads as empty, not raising",
           mover.proposal_title(broken) == "")

        matches = mover.match_title("Aquarium Notes", proposals)
        ok("case folded and trimmed, an exact match finds every holder",
           {p.name for p in matches} == {"titled-a.md", "titled-b.md"}, matches)
        matches = mover.match_title("  Unique One  ", proposals)
        ok("outside whitespace on the query is trimmed too",
           [p.name for p in matches] == ["unique.md"], matches)
        ok("no match returns nothing",
           mover.match_title("Nothing Like This", proposals) == [])
        ok("an empty title matches nothing",
           mover.match_title("", proposals) == [])
        ok("a title is not a substring match",
           mover.match_title("Aquarium", proposals) == [])

        # The round trip, not the punctuation: whatever `/list outbox` prints
        # after the dash has to be a title `/file` accepts. Pinning the exact
        # label would pass while the two drifted, which is the whole `W-1.1-07`
        # failure — the tag used to sit *after* the title, so the visible line
        # was not a usable argument for a command that takes the remainder.
        import commands
        tagged = v.propose("20260730113101.md", body="Fact.",
                           folder=v.wiki_out, extra="title: Agentic Risk Standards")
        tagged_p = mover.plan(tagged)
        label = commands._proposal_label(tagged_p)
        shown = label.split("  —  ")[-1]
        ok("a tagged proposal's title is the last thing on its line",
           shown == "Agentic Risk Standards", label)
        ok("...and pasting that back is what /file matches",
           [p.name for p in mover.match_title(shown, mover.list_proposals())]
           == ["20260730113101.md"], label)
        tagged.unlink()

        for f in (broken, v.outbox / "no-title.md", v.outbox / "titled-a.md",
                 v.outbox / "titled-b.md", v.outbox / "unique.md"):
            f.unlink()

        print("\n--- v1.6: the wiki screen's changed-file picker shows a "
              "title beside the path ---")
        import contextlib
        import io
        import commands

        wiki_change = v.wiki / "20260801000000.md"
        wiki_change.write_text(
            "---\nid: 20260801000000\ntitle: Aquarium Nitrogen Cycle\n"
            "---\n\nbody\n", encoding="utf-8")
        changes = wikigit.status(wikigit.WIKI)
        ok("the fixture actually produced a change to pick from",
           any(c.path.endswith("20260801000000.md") for c in changes),
           changes)

        out = io.StringIO()
        real_stdin = sys.stdin
        sys.stdin = io.StringIO("1\n")
        saved_file = commands.console._file
        try:
            with contextlib.redirect_stdout(out):
                commands.console.file = out
                picked = commands._pick_change(changes)
        finally:
            sys.stdin = real_stdin
            commands.console.file = saved_file
        shown = " ".join(out.getvalue().split())
        ok("the picker shows the title beside the path",
           "Aquarium Nitrogen Cycle" in shown, shown)
        ok("...the real relative path is still on the same line",
           "20260801000000.md" in shown, shown)
        ok("the returned Change still carries the real path — a label is "
           "never a key", picked is not None and
           picked.path.endswith("20260801000000.md"), picked)

        wiki_change.unlink()

        print("\n--- /move: top-level loose inventory ---")
        for f in list(v.outbox.iterdir()):
            if f.is_file():
                f.unlink()
        (v.outbox / "loose-a.md").write_text("A", encoding="utf-8")
        (v.outbox / "loose-b.txt").write_text("B", encoding="utf-8")
        (v.outbox / "99 readme.md").write_text("doc", encoding="utf-8")
        (v.outbox / "routine logs").mkdir(exist_ok=True)
        (v.outbox / "routine logs" / "log.md").write_text("x", encoding="utf-8")
        (v.wiki_out / "wdraft.md").write_text("x", encoding="utf-8")
        loose = mover.loose_files()
        names = {f.name for f in loose}
        ok("offers a loose file regardless of extension",
           {"loose-a.md", "loose-b.txt"} <= names, names)
        ok("excludes the outbox's own readme", "99 readme.md" not in names, names)
        ok("excludes subfolder contents (run logs)", "log.md" not in names, names)
        ok("excludes subfolder contents (wiki proposals)",
           "wdraft.md" not in names, names)
        (v.wiki_out / "wdraft.md").unlink()
        (v.outbox / "routine logs" / "log.md").unlink()

        print("\n--- v1.6: /move's loose-file picker shows a title too ---")
        titled_loose = v.outbox / "titled-loose.md"
        titled_loose.write_text("---\ntitle: A Loose Draft\n---\n\nbody\n",
                                encoding="utf-8")
        out = io.StringIO()
        real_stdin = sys.stdin
        sys.stdin = io.StringIO("\n")  # blank line at the file prompt: cancel
        saved_file = commands.console._file
        try:
            with contextlib.redirect_stdout(out):
                commands.console.file = out
                commands.do_move()
        finally:
            sys.stdin = real_stdin
            commands.console.file = saved_file
        shown = out.getvalue()
        ok("the loose-file picker shows the title beside the filename",
           "titled-loose.md  —  A Loose Draft" in shown, shown)
        titled_loose.unlink()

        print("\n--- /move: resolving a typed destination ---")
        ok("a relative folder under a move root resolves",
           mover.resolve_move_destination("02 areas/daily")
           == v.areas.resolve())
        for label, dest in (
            ("outside every move root", str(v.outside)),
            ("inside the outbox itself", "99 outbox"),
        ):
            try:
                mover.resolve_move_destination(dest)
                ok(f"refused: {label}", False)
            except mover.MoveError:
                ok(f"refused: {label}", True)
        (v.areas / "a-file.md").write_text("x", encoding="utf-8")
        try:
            mover.resolve_move_destination("02 areas/daily/a-file.md")
            ok("refused: a file, not a folder", False)
        except mover.MoveError:
            ok("refused: a file, not a folder", True)
        try:
            mover.resolve_move_destination("02 areas/nope-nope")
            ok("refused: a missing folder, not created", False)
        except mover.MoveError:
            ok("refused: a missing folder, not created", True)
        ok("...and nothing was created",
           not (v.root / "02 areas" / "nope-nope").exists())

        print("\n--- /move: a symlinked destination is judged as its target ---")
        esc_dest = v.root / "escapedest"
        try:
            esc_dest.symlink_to(v.outside, target_is_directory=True)
            try:
                mover.resolve_move_destination("escapedest")
                ok("a symlinked destination out of the vault is refused", False)
            except mover.MoveError:
                ok("a symlinked destination out of the vault is refused", True)
        except (OSError, NotImplementedError):
            ok("symlinked destination refused (skipped: no symlink support)",
               True)

        print("\n--- /move: the deny list still applies to the target name ---")
        denied_src = v.outbox / "id_rsa"
        denied_src.write_text("fake key", encoding="utf-8")
        try:
            mover.plan_move(denied_src, v.areas)
            ok("a denied filename is refused even as a plain move target", False)
        except mover.MoveError:
            ok("a denied filename is refused even as a plain move target", True)
        denied_src.unlink()

        print("\n--- /move: collisions, and whether replace is available ---")
        no_collide = v.outbox / "loose-a.md"
        plan_clean = mover.plan_move(no_collide, v.areas)
        ok("no collision plans cleanly",
           not plan_clean.collides and not plan_clean.replace_reason,
           plan_clean.replace_reason)

        (v.areas / "tracked-clean.md").write_text("already here",
                                                   encoding="utf-8")
        v.commit_all("area: tracked-clean")
        plan_tc = mover.plan_move(v.outbox / "tracked-clean.md", v.areas)
        ok("a tracked, clean target collides", plan_tc.collides)
        ok("...and replace is available",
           plan_tc.replace_ok, plan_tc.replace_reason)

        (v.areas / "tracked-dirty.md").write_text("committed", encoding="utf-8")
        v.commit_all("area: tracked-dirty")
        (v.areas / "tracked-dirty.md").write_text("edited by hand, uncommitted",
                                                   encoding="utf-8")
        plan_td = mover.plan_move(v.outbox / "tracked-dirty.md", v.areas)
        ok("a dirty tracked target collides but replace is refused",
           plan_td.collides and not plan_td.replace_ok, plan_td.replace_reason)
        ok("...and the reason names it uncommitted",
           "uncommitted" in plan_td.replace_reason, plan_td.replace_reason)
        v.commit_all("area: settle tracked-dirty")

        (v.areas / "untracked.md").write_text("never committed",
                                               encoding="utf-8")
        plan_ut = mover.plan_move(v.outbox / "untracked.md", v.areas)
        ok("an untracked existing target collides but replace is refused",
           plan_ut.collides and not plan_ut.replace_ok, plan_ut.replace_reason)
        ok("...distinguished from 'no changes': not tracked at all",
           "not tracked" in plan_ut.replace_reason, plan_ut.replace_reason)

        print("\n--- /move: an unverifiable git state fails CLOSED ---")
        saved_wd = wikigit.wiki_dir
        wikigit.wiki_dir = lambda: None
        try:
            plan_nowiki = mover.plan_move(v.outbox / "tracked-clean.md", v.areas)
            ok("no WIKI_DIR to anchor discovery refuses replace",
               plan_nowiki.collides and not plan_nowiki.replace_ok
               and "cannot determine" in plan_nowiki.replace_reason,
               plan_nowiki.replace_reason)
        finally:
            wikigit.wiki_dir = saved_wd

        saved_status = wikigit.status

        def _explode(*a, **kw):
            raise wikigit.GitError("no repo here")

        wikigit.status = _explode
        try:
            plan_explode = mover.plan_move(v.outbox / "tracked-clean.md", v.areas)
            ok("git unavailable mid-check refuses replace, not silently allows",
               plan_explode.collides and not plan_explode.replace_ok
               and "cannot check" in plan_explode.replace_reason,
               plan_explode.replace_reason)
        finally:
            wikigit.status = saved_status

        print("\n--- /move: suggest_rename avoids the collision ---")
        renamed = mover.suggest_rename(v.areas / "tracked-clean.md")
        ok("a suggested rename does not collide", not renamed.exists())
        ok("...keeps the extension", renamed.suffix == ".md", renamed.name)
        ok("...and keeps the original stem, with a suffix",
           renamed.stem.startswith("tracked-clean-"), renamed.name)

        print("\n--- /move: committing an ordinary move ---")
        loose_c = v.outbox / "move-me.md"
        loose_c.write_text("payload\n", encoding="utf-8")
        target_c = v.areas / "move-me.md"
        result = mover.commit_move(loose_c, target_c)
        ok("the file arrives byte for byte",
           target_c.read_text(encoding="utf-8") == "payload\n")
        ok("...and leaves the outbox", not loose_c.exists())
        ok("...at exactly the resolved target", result == target_c.resolve())

        print("\n--- /move: commit_move re-validates the source ---")
        loose_s = v.outbox / "stale-source.md"
        loose_s.write_text("x", encoding="utf-8")
        target_s = v.areas / "stale-source.md"
        loose_s.unlink()
        try:
            mover.commit_move(loose_s, target_s)
            ok("a vanished source is refused at commit", False)
        except mover.MoveError:
            ok("a vanished source is refused at commit", True)

        nested = v.wiki_out / "nested.md"
        nested.write_text("x", encoding="utf-8")
        try:
            mover.commit_move(nested, v.areas / "nested.md")
            ok("a source inside a subfolder is refused, not top-level", False)
        except mover.MoveError:
            ok("a source inside a subfolder is refused, not top-level", True)
        nested.unlink()

        readme_src = v.outbox / "99 readme.md"
        try:
            mover.commit_move(readme_src, v.areas / "99 readme.md")
            ok("the outbox's own readme cannot be /move'd", False)
        except mover.MoveError:
            ok("the outbox's own readme cannot be /move'd", True)

        print("\n--- /move: a target that appeared after the plan is refused ---")
        loose_t = v.outbox / "appeared-target.md"
        loose_t.write_text("incoming", encoding="utf-8")
        target_t = v.areas / "appeared-target.md"
        target_t.write_text("appeared after the plan was drawn",
                            encoding="utf-8")
        try:
            mover.commit_move(loose_t, target_t)
            ok("appeared target refused without allow_replace", False)
        except mover.MoveError:
            ok("appeared target refused without allow_replace", True)
        ok("...the file that appeared is untouched",
           target_t.read_text(encoding="utf-8")
           == "appeared after the plan was drawn")
        ok("...and the source is still in the outbox", loose_t.exists())
        target_t.unlink()
        loose_t.unlink()

        print("\n--- /move: the deny list is re-checked at commit too ---")
        loose_d = v.outbox / "id_rsa"
        loose_d.write_text("fake key", encoding="utf-8")
        try:
            mover.commit_move(loose_d, v.areas / "id_rsa")
            ok("commit_move refuses a denied target too", False)
        except mover.MoveError:
            ok("commit_move refuses a denied target too", True)
        loose_d.unlink()

        print("\n--- /move: the replace guard is re-run at commit, not just plan ---")
        (v.areas / "race-target.md").write_text("clean version",
                                                 encoding="utf-8")
        v.commit_all("area: race-target")
        loose_r = v.outbox / "race-target.md"
        loose_r.write_text("incoming", encoding="utf-8")
        plan_r = mover.plan_move(loose_r, v.areas)
        ok("clean at plan time, replace looks available",
           plan_r.replace_ok, plan_r.replace_reason)
        (v.areas / "race-target.md").write_text("edited after the plan",
                                                 encoding="utf-8")
        try:
            mover.commit_move(loose_r, plan_r.target, allow_replace=True)
            ok("a target gone dirty between plan and commit is refused", False)
        except mover.MoveError:
            ok("a target gone dirty between plan and commit is refused", True)
        ok("...the hand edit survived the refusal",
           (v.areas / "race-target.md").read_text(encoding="utf-8")
           == "edited after the plan")
        ok("...and the source is still in the outbox", loose_r.exists())
        v.commit_all("area: settle race-target")
        loose_r.unlink()

        print("\n--- /move: a verified replacement ---")
        (v.areas / "replace-me.md").write_text("old content", encoding="utf-8")
        v.commit_all("area: replace-me")
        loose_rep = v.outbox / "replace-me.md"
        loose_rep.write_text("new content", encoding="utf-8")
        plan_rep = mover.plan_move(loose_rep, v.areas)
        ok("a clean tracked target allows replace",
           plan_rep.replace_ok, plan_rep.replace_reason)
        result = mover.commit_move(loose_rep, plan_rep.target, allow_replace=True)
        ok("the replacement lands",
           result.read_text(encoding="utf-8") == "new content")
        ok("...and the source left the outbox", not loose_rep.exists())
        v.commit_all("area: replace-me done")

    print("\n--- outbox_inventory: a bounded, read-only listing "
          "(D-1.7-02b / W-1.7-02c) ---")
    with tempfile.TemporaryDirectory() as tmp, Vault(tmp) as v:
        second_root = Path(tmp) / "second-outbox"
        second_root.mkdir()
        saved_roots = mover.outbox_roots
        mover.outbox_roots = lambda: (v.outbox.resolve(), second_root.resolve())
        try:
            (v.outbox / "loose-a.md").write_text("A", encoding="utf-8")
            (v.outbox / "99 readme.md").write_text("doc", encoding="utf-8")
            (v.wiki_out / "wdraft.md").write_text("x", encoding="utf-8")
            logs = v.outbox / "routine logs" / "2026-08"
            logs.mkdir(parents=True)
            (logs / "run.md").write_text("x", encoding="utf-8")
            (v.outbox / "empty-dir").mkdir()
            symlink_supported = True
            try:
                (v.outbox / "escape-link").symlink_to(
                    v.outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                symlink_supported = False
            (second_root / "other.md").write_text("y", encoding="utf-8")

            configured, roots = mover.outbox_inventory()
            ok("configured is True once a root exists", configured is True)
            ok("both roots come back, never folded into one",
               len(roots) == 2, roots)

            first = next(r for r in roots if r.root == v.outbox.resolve())
            second = next(r for r in roots if r.root == second_root.resolve())
            names = {e.relpath for e in first.entries}
            kinds = {e.relpath: e.kind for e in first.entries}

            ok("an ordinary top-level file is listed",
               "loose-a.md" in names, names)
            ok("the outbox's own readme is listed too — this is not the "
               "proposal filter", "99 readme.md" in names, names)
            ok("a proposal-folder file is listed, with its folder prefix",
               "wiki/wdraft.md" in names, names)
            ok("a nested routine log is listed at its full relative depth",
               "routine logs/2026-08/run.md" in names, names)
            ok("its parent directories are listed too, marked as directories",
               kinds.get("routine logs") == mover.DIR
               and kinds.get("routine logs/2026-08") == mover.DIR, kinds)
            ok("an empty directory is included",
               "empty-dir" in names and kinds["empty-dir"] == mover.DIR, kinds)
            ok("a plain file is marked FILE",
               kinds.get("loose-a.md") == mover.FILE, kinds)

            if symlink_supported:
                ok("the outward symlink is listed as a symlink, never "
                   "resolved to what it points at",
                   kinds.get("escape-link") == mover.SYMLINK, kinds)
                ok("...and nothing beyond it is listed — it was never "
                   "followed", not any(r.startswith("escape-link/")
                                       for r in names), names)

            ok("every displayed path stays relative to its own root",
               all(not e.relpath.startswith("/") for e in first.entries),
               first.entries)
            ok("the second root's file is listed under it, not merged "
               "into the first",
               {e.relpath for e in second.entries} == {"other.md"},
               second.entries)

            order = [e.relpath for e in first.entries]
            ok("entries come back sorted case-insensitively, deterministically",
               order == sorted(order, key=lambda s: (s.lower(), s)), order)

            print("\n--- capping: at most 200 shown, the real count and "
                  "the omission both named ---")
            big_root = Path(tmp) / "big-outbox"
            big_root.mkdir()
            for i in range(215):
                (big_root / f"file-{i:03d}.md").write_text("x", encoding="utf-8")
            mover.outbox_roots = lambda: (big_root.resolve(),)
            _, big_roots = mover.outbox_inventory()
            big = big_roots[0]
            ok("215 real entries, all counted", big.total == 215, big.total)
            ok("display is capped at 200", len(big.entries) == 200,
               len(big.entries))
            ok("omitted names exactly what the cap left out",
               big.omitted == 15, big.omitted)

            print("\n--- a missing root and an unreadable root each get "
                  "their own row; neither erases the working root's "
                  "entries ---")
            missing_root = Path(tmp) / "does-not-exist"
            unreadable_root = Path(tmp) / "unreadable-outbox"
            unreadable_root.mkdir()
            (unreadable_root / "hidden.md").write_text("x", encoding="utf-8")
            mover.outbox_roots = lambda: (
                v.outbox.resolve(), missing_root, unreadable_root.resolve())
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                print("  skip  unreadable-root case (running as root)")
            else:
                os.chmod(unreadable_root, 0o000)
                try:
                    _, roots3 = mover.outbox_inventory()
                finally:
                    os.chmod(unreadable_root, 0o755)
                by_root = {r.root: r for r in roots3}
                ok("three rows for three configured roots",
                   len(roots3) == 3, roots3)
                ok("the missing root is reported missing, not dropped",
                   by_root[missing_root].status == mover.INV_MISSING, roots3)
                ok("the unreadable root is reported unreadable",
                   by_root[unreadable_root.resolve()].status
                   == mover.INV_UNREADABLE, roots3)
                ok("...with no entries leaked from a chmod'd directory",
                   by_root[unreadable_root.resolve()].entries == [], roots3)
                ok("the working root's own entries survive both "
                   "neighbours failing",
                   len(by_root[v.outbox.resolve()].entries) > 0, roots3)

            print("\n--- a subdirectory that turns unreadable mid-walk "
                  "keeps its siblings, and its own listing, but loses its "
                  "own contents ---")
            partial_root = Path(tmp) / "partial-outbox"
            partial_root.mkdir()
            (partial_root / "ok-sibling.md").write_text("x", encoding="utf-8")
            blocked = partial_root / "blocked"
            blocked.mkdir()
            (blocked / "inside.md").write_text("x", encoding="utf-8")
            mover.outbox_roots = lambda: (partial_root.resolve(),)
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                print("  skip  subdirectory-turns-unreadable case "
                      "(running as root)")
            else:
                os.chmod(blocked, 0o000)
                try:
                    _, roots4 = mover.outbox_inventory()
                finally:
                    os.chmod(blocked, 0o755)
                partial = roots4[0]
                entries4 = {e.relpath for e in partial.entries}
                ok("the root itself is still walked whole (status ok)",
                   partial.status == mover.INV_OK, partial.status)
                ok("the sibling at the top level survives",
                   "ok-sibling.md" in entries4, entries4)
                ok("the blocked directory itself is still listed — its "
                   "own stat, from the parent, succeeded",
                   "blocked" in entries4, entries4)
                ok("...but nothing inside it is, since scanning it failed",
                   "blocked/inside.md" not in entries4, entries4)

            print("\n--- an entry that vanishes between being listed and "
                  "being stat'd costs only itself ---")
            vanish_root = Path(tmp) / "vanish-outbox"
            vanish_root.mkdir()
            (vanish_root / "keeps.md").write_text("x", encoding="utf-8")
            (vanish_root / "vanishes.md").write_text("x", encoding="utf-8")

            class _VanishingEntry:
                def __init__(self, real):
                    self._real = real
                    self.name = real.name
                    self.path = real.path

                def is_symlink(self):
                    if self.name == "vanishes.md":
                        raise FileNotFoundError(self.name)
                    return self._real.is_symlink()

                def is_dir(self, follow_symlinks=True):
                    return self._real.is_dir(follow_symlinks=follow_symlinks)

            real_scandir = mover.os.scandir

            def fake_scandir(path):
                class _Ctx:
                    def __enter__(self_):
                        return [_VanishingEntry(e) for e in real_scandir(path)]

                    def __exit__(self_, *exc):
                        return False
                return _Ctx()

            mover.os.scandir = fake_scandir
            try:
                vanish_entries = mover._walk_root(vanish_root)
            finally:
                mover.os.scandir = real_scandir
            vanish_names = {e.relpath for e in vanish_entries}
            ok("the entry that raised mid-stat is simply absent, not a crash",
               "vanishes.md" not in vanish_names, vanish_names)
            ok("...its sibling still made it through",
               "keeps.md" in vanish_names, vanish_names)
        finally:
            mover.outbox_roots = saved_roots

        print("\n--- unconfigured: no WRITE_ROOTS at all ---")
        mover.outbox_roots = lambda: ()
        try:
            configured, roots = mover.outbox_inventory()
            ok("configured is False with no roots", configured is False,
               configured)
            ok("...and no rows to reconcile with it", roots == [], roots)
        finally:
            mover.outbox_roots = saved_roots

    print("\n--- /list outbox, /list outbox contents, /file and /move drive "
          "the command layer honestly, and none of them reaches an action "
          "path (D-1.7-02b / W-1.7-02c) ---")
    with tempfile.TemporaryDirectory() as tmp, Vault(tmp) as v:
        import contextlib
        import io
        import commands
        import mover as movermod

        def captured(fn, *a, **k):
            out = io.StringIO()
            real_file = commands.console._file
            commands.console.file = out
            try:
                with contextlib.redirect_stdout(out):
                    fn(*a, **k)
            finally:
                commands.console.file = real_file
            return out.getvalue()

        # The guard: neither an inventory screen nor a "nothing to do" refusal
        # is an action surface. Verified by disabling every write path mover
        # exposes and asserting none of them fires — the same discipline
        # HANDOVER.md's testing notes ask for ("verify a guard by disabling
        # it"), applied to "this screen never writes" instead of a permission
        # check.
        def _boom(*a, **k):
            raise AssertionError(
                "a /list outbox / /file / /move refusal reached a write path")
        saved_writes = (movermod.commit, movermod.decline, movermod.commit_move)
        movermod.commit = movermod.decline = movermod.commit_move = _boom
        saved_outbox_roots = movermod.outbox_roots

        try:
            print("\n--- no-proposal/other-content: nothing filable, but "
                  "the outbox isn't empty ---")
            (v.outbox / "99 readme.md").write_text("doc", encoding="utf-8")
            (v.outbox / "loose.txt").write_text("x", encoding="utf-8")
            out = captured(commands.show_outbox)
            ok("no filing proposals pending is stated plainly",
               "no filing proposals pending" in out, out)
            ok("...and points at the contents screen for the rest",
               f"{PREFIX}list outbox contents" in out, out)
            out = captured(commands.do_file, "")
            ok("/file with nothing to file says so, not 'the outbox is "
               "empty'", "No filing proposals are pending" in out, out)
            ok("...and points at the contents command too",
               f"{PREFIX}list outbox contents" in out, out)
            (v.outbox / "loose.txt").unlink()
            (v.outbox / "99 readme.md").unlink()

            print("\n--- only-nested-content: nothing at the top level "
                  "either, just a nested routine log ---")
            logs = v.outbox / "routine logs" / "2026-08"
            logs.mkdir(parents=True)
            (logs / "run.md").write_text("x", encoding="utf-8")
            out = captured(commands.show_outbox_contents)
            ok("the nested log is listed at its full relative depth",
               "routine logs/2026-08/run.md" in out, out)
            ok("its parent directories render with the / marker",
               "routine logs/" in out, out)
            out2 = captured(commands.do_move)
            ok("/move with nothing loose names that subset, not 'no "
               "outbox files'",
               "No loose top-level files are available to move" in out2,
               out2)
            ok("...and points at the contents command too",
               f"{PREFIX}list outbox contents" in out2, out2)

            print("\n--- multiple-root partial failure: one root's "
                  "failure doesn't erase another's rows ---")
            second_root = Path(tmp) / "second-outbox"
            second_root.mkdir()
            (second_root / "extra.md").write_text("x", encoding="utf-8")
            missing_root = Path(tmp) / "missing-outbox"
            movermod.outbox_roots = lambda: (
                v.outbox.resolve(), missing_root, second_root.resolve())
            try:
                out = captured(commands.show_outbox_contents)
            finally:
                movermod.outbox_roots = saved_outbox_roots
            ok("the working first root's own entries still render",
               "routine logs/2026-08/run.md" in out, out)
            ok("the missing root is named, not silently skipped",
               "missing" in out and str(missing_root) in out, out)
            ok("the second, working root's entry still renders alongside it",
               "extra.md" in out, out)

            print("\n--- capped-inventory: the screen names the cap and "
                  "the real total, never a silent truncation ---")
            big_root = Path(tmp) / "big-outbox"
            big_root.mkdir()
            for i in range(215):
                (big_root / f"f-{i:03d}.md").write_text("x", encoding="utf-8")
            movermod.outbox_roots = lambda: (big_root.resolve(),)
            try:
                out = captured(commands.show_outbox_contents)
            finally:
                movermod.outbox_roots = saved_outbox_roots
            ok("the omission names both what was left out and the real total",
               "15 more not shown" in out and "215" in out, out)

            print("\n--- D-21: a failed root makes /list outbox's count say "
                  "so, never a silent zero ---")
            missing_root = Path(tmp) / "d21-missing"
            movermod.outbox_roots = lambda: (missing_root,)
            try:
                out = captured(commands.show_outbox)
            finally:
                movermod.outbox_roots = saved_outbox_roots
            ok("a missing root with no proposals still says the count is "
               "incomplete, not that the outbox is simply empty",
               "Outbox count is incomplete" in out, out)
            ok("...and points at the per-root contents view",
               f"{PREFIX}list outbox contents" in out, out)
            ok("...never the counted-total wording, which would claim a "
               "known number", "entries in the outbox in total" not in out, out)

            unreadable_root = Path(tmp) / "d21-unreadable"
            unreadable_root.mkdir()
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                print("  skip  unreadable-root case (running as root)")
            else:
                movermod.outbox_roots = lambda: (unreadable_root.resolve(),)
                os.chmod(unreadable_root, 0o000)
                try:
                    out = captured(commands.show_outbox)
                finally:
                    os.chmod(unreadable_root, 0o755)
                    movermod.outbox_roots = saved_outbox_roots
                ok("an unreadable root reads exactly the same as a missing "
                   "one from this screen — both are 'could not be inspected'",
                   "Outbox count is incomplete" in out, out)

            print("\n--- D-21: one readable-empty root plus one failed root "
                  "still says incomplete, not zero ---")
            readable_empty = Path(tmp) / "d21-readable-empty"
            readable_empty.mkdir()
            movermod.outbox_roots = lambda: (
                readable_empty.resolve(), missing_root)
            try:
                out = captured(commands.show_outbox)
            finally:
                movermod.outbox_roots = saved_outbox_roots
            ok("a zero readable total does not mask the other root's failure",
               "Outbox count is incomplete" in out, out)

            print("\n--- D-21: every root readable and empty keeps the "
                  "existing quiet behaviour — no pointer at all ---")
            movermod.outbox_roots = lambda: (readable_empty.resolve(),)
            try:
                out = captured(commands.show_outbox)
            finally:
                movermod.outbox_roots = saved_outbox_roots
            ok("no failure and nothing to add beyond the proposal list: "
               "neither pointer wording appears",
               "Outbox count is incomplete" not in out
               and "entries in the outbox in total" not in out, out)

            print("\n--- D-21: every root readable, more entries than "
                  "proposals: the existing counted pointer still fires ---")
            counted_root = Path(tmp) / "d21-counted"
            counted_root.mkdir()
            (counted_root / "a-proposal.md").write_text("x", encoding="utf-8")
            (counted_root / "not-a-proposal.txt").write_text("x",
                                                              encoding="utf-8")
            movermod.outbox_roots = lambda: (counted_root.resolve(),)
            try:
                out = captured(commands.show_outbox)
            finally:
                movermod.outbox_roots = saved_outbox_roots
            ok("an all-readable outbox with extra content keeps the counted "
               "pointer, not the incomplete one",
               "entries in the outbox in total" in out
               and "Outbox count is incomplete" not in out, out)
        finally:
            movermod.commit, movermod.decline, movermod.commit_move = saved_writes
            movermod.outbox_roots = saved_outbox_roots

    print("\n--- the real filing-to-import boundary (B-1.7-05) ---")
    # An empty `id:` used to survive the write as a second, empty id line,
    # which import_wiki's frontmatter-id-only rule (`fm.get("id") is None`)
    # then skipped — the page filed cleanly but never reached the index. This
    # drives the actual importer against a real db, not just mover's own
    # frontmatter.
    with tempfile.TemporaryDirectory() as tmp, Vault(tmp) as v:
        draft = v.propose("blank id.md", extra="id:", body="Indexed fact.",
                          folder=v.wiki_out)
        target = mover.commit(mover.plan(draft))

        dbfile = Path(tmp) / "chat.db"
        dbmod.db(str(dbfile)).close()
        stats = import_wiki.run_import(str(v.wiki), str(dbfile))
        ok("the filed page imports as one new page, not skipped",
           stats["pages_new"] == 1 and stats["skipped_no_id"] == 0,
           dict(stats))

        conn = dbmod.db(str(dbfile))
        row = conn.execute(
            "SELECT source_uuid FROM sessions WHERE provider='wiki'").fetchone()
        conn.close()
        ok("...imported under the id the mover generated",
           row is not None and row[0] == target.stem, (row, target.stem))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
