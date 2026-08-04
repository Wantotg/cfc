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

import routines
import tools
from context import ToolContext

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
    ok("missing write content -> error",
       is_err(tools.dispatch("write_file", json.dumps({"path": "x"}), R),
              "requires 'content'"))
    ok("null arguments -> error, not a crash",
       is_err(tools.dispatch("read_file", None, R), "requires 'path'"))
    ok("empty arguments string -> error",
       is_err(tools.dispatch("read_file", "", R), "requires 'path'"))

    print("\n--- write_file ---")
    box = Path(tempfile.mkdtemp(prefix="outbox-"))
    W = ToolContext.for_chat(read_roots=(jail,), write_roots=(box,))

    r = tools.dispatch("write_file",
                       json.dumps({"path": str(box / "a.md"),
                                   "content": "one\ntwo\n"}), W)
    ok("writes a new file", "wrote" in r, r)
    ok("content is exact", (box / "a.md").read_text() == "one\ntwo\n")
    ok("reports size and lines", "chars" in r and "lines" in r, r)

    r = tools.dispatch("write_file",
                       json.dumps({"path": str(box / "sub/deep/c.md"),
                                   "content": "x"}), W)
    ok("creates missing parent dirs inside the root", "wrote" in r, r)

    # Atomicity is visible in what it leaves behind: no .tmp- debris on the
    # happy path, and nothing partial on the unhappy one.
    leftovers = [p.name for p in box.rglob("*") if ".tmp-" in p.name]
    ok("no temp files left behind", not leftovers, leftovers)

    r = tools.dispatch("write_file",
                       json.dumps({"path": str(box / "a.md"),
                                   "content": "no"}), W)
    ok("refuses to clobber by default", is_err(r, "already exists"), r)
    ok("original untouched", (box / "a.md").read_text() == "one\ntwo\n")

    r = tools.dispatch("write_file",
                       json.dumps({"path": str(box / "a.md"), "content": "new",
                                   "overwrite": True}), W)
    ok("overwrite=true replaces", "replaced" in r, r)
    ok("...with the new content", (box / "a.md").read_text() == "new")

    r = tools.dispatch("write_file",
                       json.dumps({"path": str(jail / "nope.md"),
                                   "content": "x"}), W)
    ok("cannot write into a read-only root", is_err(r, "outside"), r)
    ok("...nothing created", not (jail / "nope.md").exists())

    r = tools.dispatch("write_file",
                       json.dumps({"path": str(box / "config.py"),
                                   "content": "x"}), W)
    ok("deny list applies to writes", is_err(r, "deny list"), r)

    r = tools.dispatch("write_file",
                       json.dumps({"path": str(box / "big.md"),
                                   "content": "x" * (tools.WRITE_MAX_CHARS + 1)}),
                       W)
    ok("oversized content refused, not truncated", is_err(r, "over the"), r)
    ok("...and no partial file written", not (box / "big.md").exists())

    r = tools.dispatch("write_file",
                       json.dumps({"path": str(box / "d.md"), "content": "x"}), R)
    ok("bare read roots grant no write access",
       is_err(r, "writing is not enabled"), r)
    ok("...nothing created", not (box / "d.md").exists())

    # --- the run log is inside the write root and must still be unwritable ---
    #
    # ROUTINE_LOG_DIR lives under WRITE_ROOTS in the real config, so
    # containment cannot express this: it takes its own refusal. The log is
    # the audit trail and what the next run reads to honour on_failure, so a
    # clobber destroys the record of the failure it exists to preserve — and
    # nothing would notice, since nobody diffs the log against what the runner
    # wrote. Tested against a control, because this is a negative.
    print("\n--- the routine run log is not writable ---")
    logs = box / "routine logs"
    logs.mkdir()
    (logs / "heartbeat.md").write_text("- 2026-07-22 03:00 ok\n")
    real_log_dir = routines.log_dir
    routines.log_dir = lambda: logs
    try:
        # This goes through dispatch, not the gate: dispatch is reachable with
        # no gate at all, so it has to be the layer that refuses.
        r = tools.dispatch("write_file",
                           json.dumps({"path": str(logs / "heartbeat.md"),
                                       "content": "clobbered",
                                       "overwrite": True}), W)
        ok("dispatch refuses a write into the log dir",
           is_err(r, "run log"), r)
        ok("...the log is untouched",
           (logs / "heartbeat.md").read_text() == "- 2026-07-22 03:00 ok\n")

        r = tools.dispatch("write_file",
                           json.dumps({"path": str(logs / "sub" / "new.md"),
                                       "content": "x"}), W)
        ok("...and so is a write below it", is_err(r, "run log"), r)
        ok("...nothing created", not (logs / "sub").exists())

        # Resolution happens before the check, so a link out of the ordinary
        # outbox into the log dir is judged as its target. Same property that
        # defeats ../ traversal in path_guard.
        link = box / "shortcut.md"
        try:
            link.symlink_to(logs / "heartbeat.md")
        except OSError:
            link = None
        if link is not None:
            r = tools.dispatch("write_file",
                               json.dumps({"path": str(link),
                                           "content": "via a symlink",
                                           "overwrite": True}), W)
            ok("a symlink into the log dir is refused too", is_err(r, "run log"), r)
            ok("...the log is still untouched",
               (logs / "heartbeat.md").read_text() == "- 2026-07-22 03:00 ok\n")

        # Reads are untouched: this blocks recording, not looking.
        r = tools.dispatch("read_file",
                           json.dumps({"path": str(logs / "heartbeat.md")}),
                           ToolContext.for_chat(read_roots=(jail, box),
                                                write_roots=(box,)))
        ok("reading the run log is still allowed", "03:00 ok" in r, r)

        # The pre-filter mirrors the boundary, so the gate never prompts for a
        # call that cannot succeed.
        blocked = tools.precheck("write_file",
                                 json.dumps({"path": str(logs / "x.md"),
                                             "content": "x"}), W)
        ok("precheck refuses it before the gate",
           blocked is not None and is_err(blocked, "run log"), blocked)
        ok("precheck still passes an ordinary outbox write",
           tools.precheck("write_file",
                          json.dumps({"path": str(box / "fine.md"),
                                      "content": "x"}), W) is None)

        # The control: the refusal is this one directory, not writes in general.
        r = tools.dispatch("write_file",
                           json.dumps({"path": str(box / "proposal.md"),
                                       "content": "x"}), W)
        ok("an ordinary outbox write still works", "wrote" in r, r)
    finally:
        routines.log_dir = real_log_dir

    # With no routines config reachable, the extra rule simply doesn't apply —
    # it can only ever narrow the write scope, never widen it, so failing open
    # here still leaves every write bounded by the roots.
    routines.log_dir = lambda: (_ for _ in ()).throw(RuntimeError("no config"))
    try:
        ok("a broken log-dir lookup narrows nothing",
           tools.reserved_write_reason(box / "a.md") is None)
    finally:
        routines.log_dir = real_log_dir

    print("\n--- written_path reads write_file's own result ---")
    # Pinned by round-trip, never against a hand-written string: the whole
    # hazard is that rewording write_file's success line silently turns this
    # into None forever, which reads in the run log as "the run wrote nothing".
    # A literal here would keep passing while the real pair drifted apart.
    spacey = box / "a note with spaces.md"
    r = tools.dispatch("write_file",
                       json.dumps({"path": str(spacey), "content": "x\ny\n"}), W)
    ok("a real write result parses back to its path",
       tools.written_path("write_file", r) == spacey,
       (r, tools.written_path("write_file", r)))

    r2 = tools.dispatch("write_file",
                        json.dumps({"path": str(spacey), "content": "z",
                                    "overwrite": True}), W)
    ok("...and so does an overwrite ('replaced', not 'wrote')",
       tools.written_path("write_file", r2) == spacey, (r2,))

    r3 = tools.dispatch("write_file",
                        json.dumps({"path": str(jail / "no.md"),
                                    "content": "x"}), W)
    ok("a refused write yields no path",
       tools.written_path("write_file", r3) is None, r3)
    ok("a read result yields no path",
       tools.written_path("read_file",
                          tools.dispatch("read_file",
                                         json.dumps({"path": str(jail / "readme.md")}),
                                         W)) is None)
    ok("a non-write tool name is never credited with a write",
       tools.written_path("read_file", r) is None, r)
    ok("junk in, None out",
       tools.written_path("write_file", None) is None and
       tools.written_path("write_file", "") is None and
       tools.written_path("write_file", "wrote something") is None)

    print("\n--- v1.6: the vault-scope boundary, at the dispatcher ---")
    import vault
    vroot = Path(tempfile.mkdtemp(prefix="vault-root-"))
    (vroot / "01 personal").mkdir()
    (vroot / "01 personal" / "diary.md").write_text("private")
    (vroot / "01 personal" / "sub").mkdir()
    (vroot / "01 personal" / "sub" / "deep.md").write_text("deep private")
    (vroot / "unscoped.md").write_text("fine")
    saved_root, saved_scopes = vault.VAULT_ROOT, vault.VAULT_SCOPES
    vault.VAULT_ROOT = str(vroot)
    vault.VAULT_SCOPES = (dict(name="personal", path="01 personal",
                               exposed=False),)
    try:
        V = ToolContext.for_chat(read_roots=(vroot,), write_roots=(vroot,))

        print("  -- listing --")
        r = tools.dispatch("list_dir", json.dumps({"path": str(vroot)}), V)
        ok("a hidden directory is omitted from a listing",
           "01 personal" not in r, r)
        ok("an unscoped sibling still lists",
           "unscoped.md" in r, r)

        print("  -- direct reads --")
        r = tools.dispatch("read_file",
                           json.dumps({"path": str(vroot / "01 personal" /
                                                   "diary.md")}), V)
        ok("a directly-named hidden path is refused",
           is_err(r, "exposed vault view"), r)
        ok("...its content is not in the refusal", "private" not in r)

        print("  -- full-tree grep prunes hidden subtrees --")
        r = tools.dispatch("grep", json.dumps({"pattern": "private"}), V)
        ok("grep across the whole read root finds nothing hidden",
           "no matches" in r or "private" not in r, r)
        r = tools.dispatch("grep",
                           json.dumps({"pattern": "fine", "path": str(vroot)}),
                           V)
        ok("...but still finds an unscoped hit", "unscoped.md" in r, r)

        print("  -- direct writes --")
        r = tools.dispatch("write_file",
                           json.dumps({"path": str(vroot / "01 personal" /
                                                   "new.md"),
                                       "content": "x"}), V)
        ok("a write into a hidden scope is refused",
           is_err(r, "exposed vault view"), r)
        ok("...nothing was created",
           not (vroot / "01 personal" / "new.md").exists())

        print("  -- a guessed or symlinked path --")
        r = tools.dispatch("read_file",
                           json.dumps({"path": str(vroot / "01 personal" /
                                                   "sub" / "deep.md")}), V)
        ok("a route through a hidden ancestor is refused even unlisted",
           is_err(r, "exposed vault view"), r)
        if hasattr(__import__("os"), "symlink"):
            try:
                link = vroot / "peek.md"
                link.symlink_to(vroot / "01 personal" / "diary.md")
                r = tools.dispatch("read_file",
                                   json.dumps({"path": str(link)}), V)
                ok("a symlink resolving into a hidden scope is refused",
                   is_err(r, "exposed vault view"), r)
            except OSError:
                pass

        print("  -- precheck refuses before the gate asks --")
        blocked = tools.precheck(
            "read_file",
            json.dumps({"path": str(vroot / "01 personal" / "diary.md")}), V)
        ok("precheck itself refuses a hidden read",
           blocked is not None and is_err(blocked, "exposed vault view"),
           blocked)

        print("  -- routine contexts get the same boundary, ungated --")
        RC = ToolContext.for_routine("nightly", read_roots=(vroot,),
                                     write_roots=(vroot,))
        r = tools.dispatch("read_file",
                           json.dumps({"path": str(vroot / "01 personal" /
                                                   "diary.md")}), RC)
        ok("an ungated routine context is refused too — no interactive gate "
           "is what would have skipped this", is_err(r, "exposed vault view"),
           r)
        r = tools.dispatch("list_dir", json.dumps({"path": str(vroot)}), RC)
        ok("...and a routine's own listing omits it too",
           "01 personal" not in r, r)
    finally:
        vault.VAULT_ROOT, vault.VAULT_SCOPES = saved_root, saved_scopes

    print("\n  -- invalid scopes fail closed only for model-facing vault "
          "access --")
    vault.VAULT_ROOT = str(vroot)
    vault.VAULT_SCOPES = (dict(name="typo", path="does not exist",
                               exposed=False),)
    try:
        V = ToolContext.for_chat(read_roots=(vroot,), write_roots=(vroot,))
        r = tools.dispatch("read_file",
                           json.dumps({"path": str(vroot / "unscoped.md")}),
                           V)
        ok("a vault-rooted read fails closed while VAULT_SCOPES is invalid",
           is_err(r, "exposed vault view"), r)

        RJ = ToolContext.for_chat(read_roots=(jail,), write_roots=(box,))
        r = tools.dispatch("read_file",
                           json.dumps({"path": str(jail / "readme.md")}), RJ)
        ok("an unrelated read root outside the vault is unaffected",
           "alpha" in r, r)
    finally:
        vault.VAULT_ROOT, vault.VAULT_SCOPES = saved_root, saved_scopes

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
    ok("exactly the four tools",
       names == {"list_dir", "read_file", "grep", "write_file"}, names)
    # write_file is the only mutating tool, and it only creates files. Nothing
    # that deletes, moves or executes has crept in — that stays out of scope
    # deliberately, not by oversight.
    ok("no delete/move/exec tool has crept in",
       not any(w in n for n in names
               for w in ("delete", "remove", "move", "run", "exec", "shell")))
    ok("write_file is the only tool guarded against the write roots",
       tools.WRITE_TOOLS == {"write_file"}, tools.WRITE_TOOLS)
    for s in tools.TOOL_SCHEMAS:
        f = s["function"]
        ok(f"{f['name']} schema has description+params",
           bool(f.get("description")) and "properties" in f["parameters"])

    print("\n--- v1.8: web_search, per-context schemas, the one registry ---")
    # web_search is deliberately not in TOOL_SCHEMAS (the assertion just
    # above still holds unchanged) — it lives in the one registry
    # (tools.CHAT_ONLY_TOOLS / tools.NETWORK_TOOLS / tools._ALL_SCHEMAS) that
    # schemas_for(), _tool_allowed() and commands.show_tools_state's /tools
    # row all read, so a tool added there and nowhere else is offered,
    # dispatchable and listed together rather than drifting apart.
    chat_ctx = ToolContext.for_chat(read_roots=(jail,), write_roots=())
    priv_ctx = ToolContext.for_chat(read_roots=(jail,), write_roots=(),
                                    interactive=True, external_network=False)
    routine_ctx = ToolContext.for_routine("nightly", read_roots=(jail,))

    ok("web_search is offered to a normal chat context",
       "web_search" in {s["function"]["name"]
                        for s in tools.schemas_for(chat_ctx)})
    ok("web_search is withheld from a private chat context (v1.8: gated "
       "alone is no longer enough — it also needs external_network)",
       "web_search" not in {s["function"]["name"]
                            for s in tools.schemas_for(priv_ctx)})
    ok("...but the four file tools are unaffected by that same private "
       "context — external_network only ever narrows NETWORK_TOOLS",
       {s["function"]["name"] for s in tools.schemas_for(priv_ctx)} ==
       {"list_dir", "read_file", "grep", "write_file"})
    ok("web_search is withheld from a routine context",
       "web_search" not in {s["function"]["name"]
                            for s in tools.schemas_for(routine_ctx)})
    ok("the four file tools are still offered to a routine",
       {s["function"]["name"] for s in tools.schemas_for(routine_ctx)} ==
       {"list_dir", "read_file", "grep", "write_file"})

    ok("the dispatcher refuses web_search from a routine context even "
       "though the schema was never offered — the guard is the dispatcher, "
       "not the schema list (HANDOVER.md standing decision 5)",
       is_err(tools.dispatch("web_search", '{"query": "x"}', routine_ctx),
             "not available"))
    ok("precheck refuses it too, before the gate would even ask",
       tools.precheck("web_search", '{"query": "x"}', routine_ctx) is not None
       and is_err(tools.precheck("web_search", '{"query": "x"}', routine_ctx),
                  "not available"))
    ok("the dispatcher refuses web_search from a private context the same "
       "way, for the same reason — a call the schema never offered still "
       "can't reach the sandbox if one arrives anyway",
       is_err(tools.dispatch("web_search", '{"query": "x"}', priv_ctx),
             "not available")
       and is_err(tools.precheck("web_search", '{"query": "x"}', priv_ctx),
                 "not available"))
    ok("a routine's file tools are unaffected by the new registry",
       "readme.md" in tools.dispatch(
           "list_dir", json.dumps({"path": str(jail)}), routine_ctx))

    ok("web_search is consequential (never covered by 'allow all this turn')",
       tools.is_consequential("web_search"))
    ok("...but it is not a WRITE_TOOL — it touches no filesystem root",
       "web_search" not in tools.WRITE_TOOLS)

    ok("dispatch requires 'query'",
       is_err(tools.dispatch("web_search", "{}", chat_ctx), "requires 'query'"))
    ok("describe() shows the query and the live-request marker",
       tools.describe("web_search", '{"query": "best cat food"}', chat_ctx) ==
       ["query: 'best cat food'",
        "LIVE NETWORK REQUEST — sends this exact query to DuckDuckGo",
        "one approval = one request attempt; no automatic retry"])

    print("  (a real dispatched call is covered by tests/test_websearch.py "
         "and tests/test_search_worker.py, not here — this file stays "
         "network-independent)")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
