#!/usr/bin/env python3
"""
test_routines.py — the routine object, its store, and the run log. No API calls.

    python3 tests/test_routines.py

Three properties carry the weight here, and they are the ones the handover
called for:

  1. A routine round-trips through its file. Write it, read it back, get an
     equal object. This is the "fully reconstructable from its file" invariant
     — the thing that makes list/delete/edit into folder operations. It failed
     on first run over a single trailing newline, which is exactly the kind of
     technicality that quietly turns an invariant into a nearly-invariant.

  2. A routine whose declared write root overlaps the cfc source **cannot be
     saved**, not merely cannot be run. An invalid routine that sits on disk
     looking fine is a 03:00 surprise waiting to happen.

  3. The run log survives a failed run, and the next run can read that failure
     back. It is a log rather than a print precisely because on_failure has to
     be decided by a fresh process that has no memory of last night.

Everything runs against temp directories: config's real vault paths are
monkeypatched out, so this never touches the real routine store or log.
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import routines
from context import ScopeError, ToolContext

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


class Store:
    """Redirect the three directories at temp dirs for the duration of a test.

    Patches the module-level accessors rather than config, because that is the
    single seam every function in routines.py goes through — patching config
    would miss a caller that imported the value at module load.
    """

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.rdir = self.tmp / "routines"
        self.pdir = self.tmp / "prompts"
        self.ldir = self.tmp / "logs"
        for d in (self.rdir, self.pdir, self.ldir):
            d.mkdir(parents=True, exist_ok=True)
        (self.pdir / "task.md").write_text("Do the thing.", encoding="utf-8")

    def __enter__(self):
        self._saved = (routines.routine_dir, routines.prompt_dir,
                       routines.log_dir)
        routines.routine_dir = lambda: self.rdir
        routines.prompt_dir = lambda: self.pdir
        routines.log_dir = lambda: self.ldir
        return self

    def __exit__(self, *exc):
        (routines.routine_dir, routines.prompt_dir,
         routines.log_dir) = self._saved


def make(**kw):
    kw.setdefault("id", "nightly")
    kw.setdefault("name", "Nightly")
    kw.setdefault("prompt", "task.md")
    return routines.Routine(**kw)


def main():
    print("\n--- slugify ---")
    ok("spaces to hyphens", routines.slugify("Nightly Digest") == "nightly-digest")
    ok("punctuation collapses", routines.slugify("Cas's  digest!") == "cas-s-digest")
    ok("already a slug is unchanged", routines.slugify("nightly") == "nightly")

    with tempfile.TemporaryDirectory() as tmp, Store(tmp) as store:

        print("\n--- round-trip through the file (the invariant) ---")
        r = make(read_roots=[str(store.pdir)], body="Notes about this routine.")
        dest = routines.save_routine(r)
        ok("saved as <id>.md", dest.name == "nightly.md", dest)
        back = routines.load_routine("nightly")
        ok("re-read object is equal", back == r,
           f"{back.__dict__} != {r.__dict__}")
        ok("re-serialising is byte-identical",
           back.to_markdown() == r.to_markdown())

        # The failure that actually happened: a trailing newline in the file
        # body made the round-trip unequal while everything looked correct.
        trailing = routines.Routine.from_markdown(
            r.to_markdown().rstrip() + "\n\n\n")
        ok("trailing whitespace is not part of identity", trailing == r)

        print("\n--- load by id and by name ---")
        ok("by id", routines.load_routine("nightly").id == "nightly")
        ok("by display name", routines.load_routine("Nightly").id == "nightly")
        ok("by name, case-insensitive",
           routines.load_routine("NIGHTLY").id == "nightly")
        try:
            routines.load_routine("nope")
            ok("unknown routine raises", False)
        except routines.RoutineError as e:
            ok("unknown routine raises, and lists what exists", "nightly" in str(e))

        print("\n--- a write root over the source cannot be SAVED ---")
        bad = make(id="bad", write_roots=[str(ROOT)])
        problems = bad.validate()
        ok("validate() reports the overlap",
           any("overlaps the cfc source" in p for p in problems), problems)
        try:
            routines.save_routine(bad)
            ok("save is refused", False, "it saved")
        except routines.RoutineError as e:
            ok("save is refused", "overlaps the cfc source" in str(e), e)
        ok("...and no file was left behind",
           not (store.rdir / "bad.md").exists())
        # Both directions: a root that *contains* the source is equally bad.
        containing = make(id="bad2", write_roots=[str(ROOT.parent)])
        ok("a root containing the source is refused too",
           any("overlaps the cfc source" in p for p in containing.validate()))

        print("\n--- validation catches the 03:00 mistakes ---")
        ok("missing prompt file",
           any("prompt file not found" in p
               for p in make(prompt="nope.md").validate()))
        ok("nonexistent read root",
           any("does not exist" in p
               for p in make(read_roots=["/no/such/place"]).validate()))
        ok("denied path as a root",
           any("deny list" in p for p in
               make(read_roots=[str(ROOT / "config.py")]).validate()))
        ok("bad trigger",
           any("not 'command' or HHMM" in p
               for p in make(trigger="3am").validate()))
        ok("out-of-range trigger",
           any("not a valid time" in p for p in make(trigger="2599").validate()))
        ok("HHMM trigger is fine", not make(trigger="0300").validate())
        ok("bad on_failure",
           any("retry|skip" in p for p in make(on_failure="explode").validate()))
        ok("non-slug id",
           any("is not a slug" in p for p in make(id="Not A Slug").validate()))

        print("\n--- context ---")
        ctx = make(read_roots=[str(store.pdir)],
                   write_roots=[str(store.ldir)]).context()
        ok("routine context is ungated", ctx.gated is False)
        ok("...and carries its write scope", ctx.can_write)
        ok("...labelled with the routine id", ctx.label == "routine:nightly")
        ok("gated has no setter",
           not _settable(ctx, "gated", True))
        ok("no write roots -> cannot write", not make().context().can_write)
        ok("default is non-interactive", ctx.interactive is False)

        print("\n--- malformed files are skipped, not fatal ---")
        (store.rdir / "junk.md").write_text("no frontmatter here", encoding="utf-8")
        (store.rdir / "half.md").write_text("---\nid: half\n---\n", encoding="utf-8")
        found, bad_files = routines.list_routines()
        ok("the good routine still lists", [x.id for x in found] == ["nightly"])
        ok("both bad files are reported", len(bad_files) == 2, bad_files)
        ok("the reason comes with them",
           all(why for _, why in bad_files), bad_files)

        print("\n--- the run log survives failure, and the next run reads it ---")
        ok("no log yet", routines.last_run("nightly") == (None, None))
        routines.append_log("nightly", "failed", "provider timed out")
        status, ts = routines.last_run("nightly")
        ok("a failed run is recorded", status == "failed", status)
        ok("...with a timestamp", bool(ts), ts)

        routines.append_log("nightly", "ok", "wrote the digest",
                            touched=["digest.md"])
        status, _ = routines.last_run("nightly")
        ok("the latest run wins", status == "ok", status)

        text = routines.log_path("nightly").read_text(encoding="utf-8")
        ok("the log is append-only — the failure is still there",
           "provider timed out" in text, text)
        ok("...and both runs are present", text.count("- **") == 2, text)
        ok("what was touched is recorded", "digest.md" in text, text)
        ok("the header is written once", text.count("# Run log") == 1, text)

        print("\n--- disabled routines ---")
        off = make(id="off", enabled=False, read_roots=[str(store.pdir)])
        routines.save_routine(off)
        ok("enabled=False round-trips",
           routines.load_routine("off").enabled is False)

        print("\n--- the runner logs every way out, including a crash ---")
        # A real temp database. Invariant #1: check the path before writing,
        # never after — a test guard that asserted after its destructive step
        # once deleted the live database.
        import db as dbmod
        assert "tmp" in str(store.tmp) and not str(store.tmp).startswith(
            str(Path("~/.cfc").expanduser())), "refusing to touch a real db"
        saved_path = dbmod.DB_PATH
        dbmod.DB_PATH = store.tmp / "chat.db"
        conn = dbmod.db()
        try:
            import runner
            real_turn = runner.agent_turn

            # A provider blowing up mid-run must still reach the log: an
            # unattended run that dies silently is indistinguishable from one
            # that had nothing to do.
            def explode(*a, **kw):
                raise TimeoutError("provider went away")

            runner.agent_turn = explode
            good = make(id="crash", read_roots=[str(store.pdir)])
            routines.save_routine(good)
            ok2, summary, sid = runner.run_routine("crash", conn, model="m")
            ok("a crashing run returns False, not an exception", ok2 is False)
            ok("...names the failure", "provider went away" in summary, summary)
            ok("...still opened a session to read afterwards", sid is not None)
            status, _ = routines.last_run("crash")
            ok("...and is recorded as failed", status == "failed", status)

            # The next run is a fresh process with no memory — it must learn
            # the previous failure from the file.
            events = []
            runner.agent_turn = lambda *a, **kw: {"role": "assistant",
                                                  "content": "done"}
            ok3, summary, _ = runner.run_routine("crash", conn, model="m",
                                                 on_event=events.append)
            ok("the next run reads the failure from the log",
               any("last run failed" in e for e in events), events)
            ok("...and can then succeed", ok3 is True, summary)
            ok("the log now ends ok", routines.last_run("crash")[0] == "ok")

            print("\n--- a routine that cannot run is refused before the API ---")
            invalid = routines.Routine(id="broken", name="Broken",
                                       prompt="gone.md")
            # Written directly, bypassing save_routine, because save_routine
            # would refuse it — this is the hand-edited-in-Obsidian case, where
            # a file on disk stopped being valid after it was saved.
            (store.rdir / "broken.md").write_text(
                invalid.to_markdown(), encoding="utf-8")
            runner.agent_turn = explode          # would raise if reached
            ok4, summary, sid = runner.run_routine("broken", conn, model="m")
            ok("an invalid routine fails without calling the model",
               ok4 is False and "prompt file not found" in summary, summary)
            ok("...is logged as failed", routines.last_run("broken")[0] == "failed")
            ok("...and never opened a session", sid is None)

            disabled = runner.run_routine("off", conn, model="m")
            ok("a disabled routine does not run", disabled[0] is False)
            ok("...and says so in the log",
               routines.last_run("off")[0] == "skipped")
        finally:
            runner.agent_turn = real_turn
            conn.close()
            dbmod.DB_PATH = saved_path

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


def _settable(obj, attr, value):
    try:
        setattr(obj, attr, value)
        return True
    except AttributeError:
        return False


if __name__ == "__main__":
    sys.exit(main())
