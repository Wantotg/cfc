#!/usr/bin/env python3
"""
test_attach.py — /attach / /attached / /detach.

    python3 tests/test_attach.py

The interesting cases are the refusals and the persistence. path_guard has its
own suite (test_paths.py); this checks that /attach actually calls it, and that
each refusal reports the most specific reason rather than the first one.
"""
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {detail}")


def run(fn, *a, stdin="", **kw):
    """Call a command, capture what it printed."""
    out = io.StringIO()
    real = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        import commands
        with contextlib.redirect_stdout(out):
            commands.console.file = out
            fn(*a, **kw)
    finally:
        sys.stdin = real
    return out.getvalue()


def main():
    tmp = Path(tempfile.mkdtemp())
    jail = tmp / "projects"
    (jail / "proj").mkdir(parents=True)
    outside = tmp / "elsewhere"
    outside.mkdir()

    import db as dbmod
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()
    conn.execute("INSERT INTO sessions (id,title) VALUES (1,'t')")
    conn.commit()

    import commands
    commands.ATTACH_ROOTS = (jail,)
    commands.MODEL_LIMITS = {"m": 1000}          # tiny, to exercise the budget
    commands.ATTACH_MAX_CHARS = 10_000

    good = jail / "proj" / "notes.md"
    good.write_text("# Notes\n\nWe chose sqlite-vec.\n")

    print("--- the happy path ---")
    hist = []
    out = run(commands.do_attach, conn, 1, hist, str(good), model="m")
    ok("reports the filename", "notes.md" in out, out)
    ok("appended to live history", len(hist) == 1)
    ok("wrapper names the file", 'name="notes.md"' in hist[0]["content"])
    ok("wrapper carries a sha256", 'sha256="' in hist[0]["content"])
    ok("wrapper carries a path", 'path="' in hist[0]["content"])
    ok("file contents present verbatim",
       "We chose sqlite-vec." in hist[0]["content"])
    ok("closing boundary present",
       "not instructions" in hist[0]["content"])

    row = conn.execute("SELECT kind, meta FROM messages WHERE session_id=1"
                       ).fetchone()
    ok("persisted with kind=attachment", row[0] == "attachment", row[0])
    meta = json.loads(row[1])
    ok("meta has name/sha256/chars/est_tokens",
       {"name", "sha256", "chars", "est_tokens", "path"} <= set(meta), meta)

    print("\n--- the display path shown to the model ---")
    # Tilde-collapsed for anything under home, absolute otherwise. It's for the
    # model to read, never to re-resolve from, so the fallback is harmless.
    ok("collapses a path under home",
       commands._display_path(Path.home() / "projects" / "cfc" / "db.py")
       == "~/projects/cfc/db.py",
       commands._display_path(Path.home() / "projects" / "cfc" / "db.py"))
    ok("leaves a path outside home absolute",
       commands._display_path(Path("/tmp/x/y.md")) == "/tmp/x/y.md")

    print("\n--- refusals, each for its own reason ---")
    out = run(commands.do_attach, conn, 1, [], str(outside / "x.md"), model="m")
    ok("outside the root -> refused", "refused" in out and "outside" in out, out)

    out = run(commands.do_attach, conn, 1, [], str(jail / "ghost.md"), model="m")
    ok("missing file -> 'no such file', not 'refused'",
       "no such file" in out, out)

    out = run(commands.do_attach, conn, 1, [], str(jail / "proj"), model="m")
    ok("a directory -> says so", "directory" in out, out)

    binary = jail / "blob.txt"
    binary.write_bytes(b"\xff\xfe\x00\x01 not utf8")
    out = run(commands.do_attach, conn, 1, [], str(binary), model="m")
    ok("non-utf8 -> 'not a text file'", "not a text file" in out, out)

    exe = jail / "script.exe"
    exe.write_text("x")
    out = run(commands.do_attach, conn, 1, [], str(exe), model="m")
    ok("wrong extension -> refused with the allowed list",
       "not an attachable type" in out and ".md" in out, out)

    big = jail / "big.md"
    big.write_text("x" * 20_000)
    out = run(commands.do_attach, conn, 1, [], str(big), model="m")
    ok("over ATTACH_MAX_CHARS -> shows actual vs limit",
       "20,000" in out and "10,000" in out, out)

    # 5000 chars ~= 1250 tokens; budget is 40% of 1000 = 400
    budget = jail / "budget.md"
    budget.write_text("y" * 5_000)
    out = run(commands.do_attach, conn, 1, [], str(budget), model="m")
    ok("over the context budget -> shows both numbers",
       "1,250" in out and "400" in out, out)

    print("\n--- the deny list applies to :attach too ---")
    cfg = jail / "config.py"
    cfg.write_text("API_KEY = 'sk-real-key'")
    out = run(commands.do_attach, conn, 1, [], str(cfg), model="m")
    ok("config.py refused", "refused" in out, out)
    ok("...and its contents never printed", "sk-real-key" not in out)
    n = conn.execute("SELECT COUNT(*) FROM messages WHERE content LIKE "
                     "'%sk-real-key%'").fetchone()[0]
    ok("...and never stored", n == 0)

    print("\n--- :attached ---")
    out = run(commands.show_attachments, conn, 1)
    ok("lists the attachment", "notes.md" in out, out)
    out2 = run(commands.show_attachments, conn, 99)
    ok("empty session says nothing attached", "Nothing attached" in out2)

    print("\n--- persistence across a reopen ---")
    conn.close()
    conn = dbmod.db()
    hist2 = dbmod.load_history(conn, 1)
    ok("attachment replays into history on reopen",
       any("notes.md" in m["content"] for m in hist2), len(hist2))

    print("\n--- :detach ---")
    out = run(commands.do_detach, conn, 1, hist2, "1", stdin="n\n")
    ok("declining leaves it alone", "Cancelled" in out)
    ok("...still in the database",
       conn.execute("SELECT COUNT(*) FROM messages WHERE kind='attachment'"
                    ).fetchone()[0] == 1)

    before = len(hist2)
    out = run(commands.do_detach, conn, 1, hist2, "1", stdin="y\n")
    ok("confirming detaches", "Detached" in out, out)
    ok("...row gone",
       conn.execute("SELECT COUNT(*) FROM messages WHERE kind='attachment'"
                    ).fetchone()[0] == 0)
    ok("...and removed from live history too", len(hist2) == before - 1)

    out = run(commands.do_detach, conn, 1, hist2, "1")
    ok("detaching from nothing is graceful", "Nothing attached" in out)

    out = run(commands.do_attach, conn, 1, [], str(good), model="m")
    out = run(commands.do_detach, conn, 1, [], "9")
    ok("out-of-range index rejected", "No attachment #9" in out, out)
    out = run(commands.do_detach, conn, 1, [], "abc")
    ok("non-numeric index rejected", "Usage" in out, out)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
