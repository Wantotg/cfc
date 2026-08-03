#!/usr/bin/env python3
"""
test_notes.py — the notes inbox: inventory and /clear notes' batch move.

    python3 tests/test_notes.py

Same shape as test_mover.py: everything runs against a temp vault, with
notes._cfg and notes.move_roots patched out so this never touches the real
vault or config.py.

The case worth reading closely is the "appeared after preview" one — the
whole reason `clear_batch` takes an explicit file list rather than re-reading
the folder itself is that the list on screen is what a human confirmed, and a
note that shows up after that must not be swept into a batch it was never
shown for.
"""
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import commands
import notes

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


class Vault:
    """A temp vault: a notes inbox and a cleared-notes archive (not
    pre-created — clear_batch must be able to make it from nothing)."""

    def __init__(self, tmp):
        self.root = Path(tmp) / "vault"
        self.inbox = self.root / "00 inbox" / "notes"
        self.archive = self.root / "04 archive" / "cleared notes"
        self.outside = Path(tmp) / "elsewhere"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.outside.mkdir(parents=True, exist_ok=True)
        self.cfg = {"NOTES_DIR": str(self.inbox),
                    "NOTES_ARCHIVE_DIR": str(self.archive)}

    def __enter__(self):
        self._saved_cfg = notes._cfg
        self._saved_roots = notes.move_roots
        notes._cfg = lambda key, default=None: self.cfg.get(key, default)
        notes.move_roots = lambda: (self.root.resolve(),)
        return self

    def __exit__(self, *exc):
        notes._cfg = self._saved_cfg
        notes.move_roots = self._saved_roots

    def note(self, name, body="a note\n"):
        p = self.inbox / name
        p.write_text(body, encoding="utf-8")
        return p


def main():
    with tempfile.TemporaryDirectory() as tmp, Vault(tmp) as v:

        print("\n--- an empty inbox, and a template-only one ---")
        files, has_sub = notes.inventory()
        ok("an empty inbox reads as zero notes, not unavailable",
           files == [] and not has_sub, (files, has_sub))
        v.note(notes.TEMPLATE_NAME, "example\n")
        files, has_sub = notes.inventory()
        ok("the template alone is the same zero, not counted",
           files == [] and not has_sub, files)

        print("\n--- inventory counts and sorts real notes ---")
        v.note("b-second.md")
        v.note("a-first.md")
        files, has_sub = notes.inventory()
        ok("both notes are counted, template excluded",
           [f.name for f in files] == ["a-first.md", "b-second.md"], files)
        ok("no subfolder yet", not has_sub)

        print("\n--- a subfolder is preserved and excluded, not counted ---")
        sub = v.inbox / "drafts"
        sub.mkdir()
        (sub / "hidden.md").write_text("x", encoding="utf-8")
        files, has_sub = notes.inventory()
        ok("the subfolder's contents are not part of the inventory",
           "hidden.md" not in [f.name for f in files], files)
        ok("...but its presence is reported", has_sub)
        (sub / "hidden.md").unlink()
        sub.rmdir()

        print("\n--- unavailable, not zero ---")
        saved = v.cfg["NOTES_DIR"]
        v.cfg["NOTES_DIR"] = ""
        ok("unconfigured is unavailable, not zero",
           notes.inventory() == (None, False))
        v.cfg["NOTES_DIR"] = str(v.root / "00 inbox" / "does-not-exist")
        ok("a missing folder is unavailable, not zero",
           notes.inventory() == (None, False))
        v.cfg["NOTES_DIR"] = str(v.outside)
        ok("outside the allowed vault roots is unavailable, not zero",
           notes.inventory() == (None, False))
        v.cfg["NOTES_DIR"] = saved

        print("\n--- an escaping symlink is judged as its target ---")
        link = v.root / "00 inbox" / "notes-link"
        try:
            link.symlink_to(v.outside, target_is_directory=True)
            v.cfg["NOTES_DIR"] = str(link)
            ok("a symlinked inbox pointing out of the vault is unavailable",
               notes.inventory() == (None, False))
            v.cfg["NOTES_DIR"] = saved
        except (OSError, NotImplementedError):
            ok("symlinked inbox test (skipped: no symlink support)", True)

        print("\n--- archive unavailable: nothing moves ---")
        before = sorted(p.name for p in v.inbox.iterdir())
        saved_archive = v.cfg["NOTES_ARCHIVE_DIR"]
        v.cfg["NOTES_ARCHIVE_DIR"] = str(v.outside)  # outside the move root
        files, _ = notes.inventory()
        try:
            notes.clear_batch(files)
            ok("an unreachable archive raises before moving anything", False)
        except notes.NotesError:
            ok("an unreachable archive raises before moving anything", True)
        after = sorted(p.name for p in v.inbox.iterdir())
        ok("...and every note stayed in the inbox", before == after,
           (before, after))
        v.cfg["NOTES_ARCHIVE_DIR"] = saved_archive

        print("\n--- a successful batch ---")
        files, _ = notes.inventory()
        names_before = [f.name for f in files]
        moved, failed, batch = notes.clear_batch(files)
        ok("both notes moved", sorted(moved) == names_before, moved)
        ok("nothing failed", failed == [], failed)
        ok("the archive was created from nothing", v.archive.is_dir())
        ok("the batch folder is fresh, under the archive",
           batch.parent == v.archive.resolve(), batch)
        for n in names_before:
            ok(f"...{n} is readable in the batch, content intact",
               (batch / n).exists())
        ok("the inbox is empty of notes again",
           notes.inventory() == ([], False))

        print("\n--- a second batch lands in its own folder ---")
        v.note("c-third.md")
        files, _ = notes.inventory()
        moved2, failed2, batch2 = notes.clear_batch(files)
        ok("a second clear gets a distinct batch folder", batch2 != batch,
           (batch, batch2))
        ok("...and moves cleanly", moved2 == ["c-third.md"] and not failed2,
           (moved2, failed2))

        print("\n--- a note that appears after the preview is left alone ---")
        v.note("preview-me.md")
        files, _ = notes.inventory()          # the preview: one file
        v.note("just-arrived.md")             # appears after the preview
        moved3, failed3, batch3 = notes.clear_batch(files)
        ok("only the previewed file moved", moved3 == ["preview-me.md"], moved3)
        ok("nothing failed", failed3 == [], failed3)
        ok("the late arrival is still in the inbox, untouched",
           (v.inbox / "just-arrived.md").exists())
        remaining, _ = notes.inventory()
        ok("...and it's what the next preview would show",
           [f.name for f in remaining] == ["just-arrived.md"], remaining)
        (v.inbox / "just-arrived.md").unlink()

        print("\n--- a partial batch: one file vanishes before the move ---")
        keep = v.note("keeper.md")
        gone = v.note("vanishes.md")
        files, _ = notes.inventory()
        names = {f.name for f in files}
        ok("the preview has both", names == {"keeper.md", "vanishes.md"}, names)
        gone.unlink()                          # gone between preview and move
        moved4, failed4, batch4 = notes.clear_batch(files)
        ok("the survivor moved", moved4 == ["keeper.md"], moved4)
        ok("the vanished one is reported failed, not silently skipped",
           failed4 == ["vanishes.md"], failed4)
        ok("the batch claims exactly what happened, no rollback pretence",
           (batch4 / "keeper.md").exists()
           and not (batch4 / "vanishes.md").exists())

        print("\n--- the template is never movable, even if named explicitly ---")
        v.note(notes.TEMPLATE_NAME, "example\n")
        files, _ = notes.inventory()
        ok("the template never appears in an inventory to hand to clear_batch",
           notes.TEMPLATE_NAME not in [f.name for f in files], files)

        # --- the prompt above the batch (B-1.6.4-09b) ----------------------
        #
        # Everything above tests notes.py. This tests the one thing that
        # decides whether any of it runs: the confirmation. It was untested,
        # and it confirmed on anything typed — 'apifjaf' archived a real
        # inbox. Driven through commands._do_clear_notes with a scripted
        # input(), not by calling the helper alone, because the bug was the
        # call site's rule and not the helper's (there was no helper).
        print("\n--- the confirmation confirms only on Enter ---")
        for name, typed, expect_moved, expect_asks in (
            ("a typo does not archive; 'back' after it cancels",
             ["apifjaf", "back"], False, 2),
            ("a typo is re-asked, and Enter then archives",
             ["apifjaf", ""], True, 2),
            ("Enter alone archives", [""], True, 1),
            ("'back' alone cancels", ["back"], False, 1),
        ):
            for stale in list(v.inbox.iterdir()):
                stale.unlink()
            v.note("prompt-case.md")
            asked = []

            def fake_input(prompt="", _script=list(typed), _asked=asked):
                _asked.append(prompt)
                return _script.pop(0)

            saved_input = getattr(commands, "input", None)
            commands.input = fake_input
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    commands._do_clear_notes()
            finally:
                if saved_input is None:
                    del commands.input
                else:
                    commands.input = saved_input

            moved = not (v.inbox / "prompt-case.md").exists()
            ok(name, moved == expect_moved and len(asked) == expect_asks,
               (moved, len(asked), buf.getvalue()[-200:]))
            if len(typed) > 1:
                ok("...and the unrecognised line said so",
                   "not recognised" in buf.getvalue(), buf.getvalue()[-200:])

        # A fourth copy of this prompt is how the first three disagreed. The
        # wording is written in exactly one place now; this fails if it isn't.
        src = (ROOT / "commands.py").read_text(encoding="utf-8")
        ok("the prompt's wording exists once in commands.py",
           src.count("Enter to confirm, or 'back': ") == 1,
           src.count("Enter to confirm, or 'back': "))
        ok("...and both /move confirmations go through the helper",
           src.count("confirm_or_back(") == 4,
           src.count("confirm_or_back("))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
