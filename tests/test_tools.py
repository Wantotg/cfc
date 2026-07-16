#!/usr/bin/env python3
"""
test_tools.py — the read-only tools and the dispatcher. No API calls.

    python3 tests/test_tools.py

The dispatcher is a pure function from (name, args) to a string, which is the
whole reason it can be tested this thoroughly. Two properties matter more than
the rest:

  - it never raises, whatever it's handed
  - every path is guarded inside the dispatcher, so approval can't bypass it
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import tools

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def is_err(result, contains=None):
    try:
        d = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return False
    if "error" not in d:
        return False
    return contains is None or contains in d["error"]


def main():
    tmp = Path(tempfile.mkdtemp())
    jail = tmp / "projects"
    (jail / "pkg").mkdir(parents=True)
    outside = tmp / "elsewhere"
    outside.mkdir()
    (outside / "secret.txt").write_text("PRIVATE STUFF")

    (jail / "readme.md").write_text("# Title\nalpha\nbeta\ngamma\ndelta\n")
    (jail / "pkg" / "code.py").write_text(
        "\n".join(f"line {i} needle" if i == 3 else f"line {i}"
                  for i in range(1, 11)))
    (jail / "config.py").write_text("API_KEY = 'sk-LEAKED-SECRET'\n")
    (jail / ".env").write_text("TOKEN=sk-ALSO-LEAKED\n")
    (jail / "blob.bin").write_bytes(b"\x00\xff\xfe binary needle")

    tools.TOOLS_ROOTS = (jail,)
    R = jail

    print("--- list_dir ---")
    out = tools.list_dir(str(jail), R)
    ok("lists files and dirs", "readme.md" in out and "pkg" in out, out)
    ok("marks directories", "dir " in out, out)
    ok("shows sizes", any(c.isdigit() for c in out))
    ok("does not recurse", "code.py" not in out, out)
    ok("outside root -> error", is_err(tools.list_dir(str(outside), R), "outside"))
    ok("missing dir -> error",
       is_err(tools.list_dir(str(jail / "ghost"), R), "no such directory"))
    ok("a file -> error",
       is_err(tools.list_dir(str(jail / "readme.md"), R), "not a directory"))
    (jail / "empty").mkdir()
    ok("empty dir says so", "empty" in tools.list_dir(str(jail / "empty"), R))

    print("\n--- read_file ---")
    out = tools.read_file(str(jail / "readme.md"), R)
    ok("returns contents", "gamma" in out, out)
    ok("line numbered", "1| # Title" in out or "1| " in out, out)
    ok("reports total lines", "5 lines" in out, out)
    ok("outside root -> error",
       is_err(tools.read_file(str(outside / "secret.txt"), R), "outside"))
    ok("...and the secret never appears", "PRIVATE STUFF" not in
       tools.read_file(str(outside / "secret.txt"), R))
    ok("missing file -> error",
       is_err(tools.read_file(str(jail / "ghost.md"), R), "no such file"))
    ok("directory -> error",
       is_err(tools.read_file(str(jail / "pkg"), R), "is a directory"))
    ok("binary -> error",
       is_err(tools.read_file(str(jail / "blob.bin"), R), "not a text file"))

    print("\n--- read_file line ranges ---")
    out = tools.read_file(str(jail / "pkg" / "code.py"), R, 3, 5)
    ok("range returns just those lines",
       "line 3" in out and "line 5" in out and "line 6" not in out, out)
    ok("range noted in the header", "showing 3-5" in out, out)
    out = tools.read_file(str(jail / "pkg" / "code.py"), R, 8, None)
    ok("start only runs to the end", "line 10" in out and "line 7" not in out)
    out = tools.read_file(str(jail / "pkg" / "code.py"), R, None, 2)
    ok("end only starts at 1", "line 1" in out and "line 3" not in out)
    ok("end past EOF is clamped, not an error",
       "line 10" in tools.read_file(str(jail / "pkg" / "code.py"), R, 9, 999))
    ok("start past EOF -> graceful error",
       is_err(tools.read_file(str(jail / "pkg" / "code.py"), R, 99, 100),
              "past the end"))
    ok("start < 1 -> graceful error",
       is_err(tools.read_file(str(jail / "pkg" / "code.py"), R, 0, 5),
              "1 or greater"))
    ok("end before start -> graceful error",
       is_err(tools.read_file(str(jail / "pkg" / "code.py"), R, 5, 2),
              "before start_line"))
    ok("non-integer range -> graceful error",
       is_err(tools.read_file(str(jail / "readme.md"), R, "abc", None),
              "must be integers"))

    print("\n--- grep ---")
    out = tools.grep("needle", R)
    ok("finds the match", "needle" in out and "code.py" in out, out)
    ok("prefixes file:line:", ":3: " in out, out)
    ok("no matches says so", "no matches" in tools.grep("zzzznope", R))
    ok("outside root -> error",
       is_err(tools.grep("PRIVATE", R, str(outside)), "outside"))
    ok("empty pattern -> error", is_err(tools.grep("", R), "required"))
    ok("skips binary files", "blob.bin" not in tools.grep("needle", R))

    print("\n--- grep must not leak denied files ---")
    # The dangerous one: grep walks directories and reads whole files. If the
    # deny list only applied to the path it was pointed at, this prints the key.
    out = tools.grep("sk-", R)
    ok("grep over the root does not surface config.py's key",
       "sk-LEAKED-SECRET" not in out, out)
    ok("...nor .env's token", "sk-ALSO-LEAKED" not in out, out)
    ok("grep aimed straight at config.py -> error",
       is_err(tools.grep("API_KEY", R, str(jail / "config.py")), "deny list"))
    ok("read_file of config.py -> error",
       is_err(tools.read_file(str(jail / "config.py"), R), "deny list"))
    ok("...and no key in that error",
       "sk-LEAKED-SECRET" not in tools.read_file(str(jail / "config.py"), R))

    print("\n--- grep match cap ---")
    many = jail / "many.txt"
    many.write_text("\n".join("needle" for _ in range(250)))
    out = tools.grep("needle", R, str(many))
    ok(f"caps at {tools.GREP_MAX_MATCHES}",
       out.count("needle:") <= tools.GREP_MAX_MATCHES + 1
       and len([l for l in out.splitlines() if ": needle" in l])
       == tools.GREP_MAX_MATCHES,
       len([l for l in out.splitlines() if ": needle" in l]))
    ok("says it stopped", "stopped at" in out)

    print("\n--- truncation ---")
    tools.TOOLS_MAX_RESULT_CHARS = 500
    huge = jail / "huge.md"
    huge.write_text("x" * 5000)
    out = tools.read_file(str(huge), R)
    ok("truncation marker present", "[truncated," in out, out[-80:])
    ok("says how much was dropped", "chars omitted]" in out)
    ok("result actually shortened", len(out) < 800, len(out))
    tools.TOOLS_MAX_RESULT_CHARS = 30_000

    print("\n--- dispatcher ---")
    ok("dispatches list_dir",
       "readme.md" in tools.dispatch("list_dir", '{"path": "%s"}' % jail, R))
    ok("dispatches read_file",
       "gamma" in tools.dispatch(
           "read_file", json.dumps({"path": str(jail / "readme.md")}), R))
    ok("dispatches grep",
       "needle" in tools.dispatch("grep", '{"pattern": "needle"}', R))
    ok("accepts a dict as well as a string",
       "readme.md" in tools.dispatch("list_dir", {"path": str(jail)}, R))

    ok("unknown tool -> error",
       is_err(tools.dispatch("rm_rf", "{}", R), "unknown tool: rm_rf"))
    ok("malformed JSON -> error",
       is_err(tools.dispatch("read_file", "{not json", R),
              "could not parse arguments"))
    ok("JSON that isn't an object -> error",
       is_err(tools.dispatch("read_file", "[1,2,3]", R),
              "could not parse arguments"))
    ok("missing required arg -> error",
       is_err(tools.dispatch("read_file", "{}", R), "requires 'path'"))
    ok("missing grep pattern -> error",
       is_err(tools.dispatch("grep", "{}", R), "requires 'pattern'"))
    ok("null arguments -> error, not a crash",
       is_err(tools.dispatch("read_file", None, R), "requires 'path'"))
    ok("empty arguments string -> error",
       is_err(tools.dispatch("read_file", "", R), "requires 'path'"))

    print("\n--- the dispatcher never raises ---")
    junk = [("read_file", '{"path": null}'), ("read_file", '{"path": 42}'),
            ("list_dir", '{"path": ""}'), ("grep", '{"pattern": 5}'),
            ("read_file", '{"path": "x", "start_line": "abc"}'),
            (None, "{}"), ("", ""), ("read_file", '{"path": "../../../etc/passwd"}')]
    raised = []
    for name, args in junk:
        try:
            r = tools.dispatch(name, args, R)
            if not isinstance(r, str):
                raised.append((name, args, "non-string result"))
        except Exception as e:
            raised.append((name, args, f"{type(e).__name__}: {e}"))
    ok("survives every malformed call", not raised, raised)

    print("\n--- schemas are well formed ---")
    names = {s["function"]["name"] for s in tools.TOOL_SCHEMAS}
    ok("exactly the three read-only tools",
       names == {"list_dir", "read_file", "grep"}, names)
    ok("no write tool has crept in",
       not any(w in n for n in names for w in ("write", "delete", "run", "exec")))
    for s in tools.TOOL_SCHEMAS:
        f = s["function"]
        ok(f"{f['name']} schema has description+params",
           bool(f.get("description")) and "properties" in f["parameters"])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
