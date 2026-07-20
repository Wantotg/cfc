#!/usr/bin/env python3
"""
test_paths.py — path_guard() is the entire security boundary for file access.
Every other safety property depends on it, so it gets tested properly.

    python3 tests/test_paths.py

Plain script, no pytest: the project has no test dependencies and this needs
none. Exits non-zero on any failure.
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from context import ScopeError, ToolContext, as_context
from paths import path_guard, PathError

PASS, FAIL = [], []


def ok(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def allows(name, path, root):
    try:
        path_guard(path, root)
        ok(name, True)
    except PathError as e:
        ok(name, False)
        print(f"       unexpected refusal: {e}")


def refuses(name, path, root, expect=None):
    try:
        p = path_guard(path, root)
        ok(name, False)
        print(f"       LET THROUGH -> {p}")
    except PathError as e:
        if expect and expect not in str(e):
            ok(name, False)
            print(f"       refused, but for the wrong reason: {e}")
        else:
            ok(name, True)


def main():
    jail = Path(tempfile.mkdtemp(prefix="jail-"))
    outside = Path(tempfile.mkdtemp(prefix="outside-"))
    (jail / "sub").mkdir()
    (jail / "notes.md").write_text("hello")
    (jail / "sub" / "deep.txt").write_text("deep")
    (outside / "secret.txt").write_text("PRIVATE")

    print("\n--- containment (the handoff's required set) ---")
    allows("plain child inside root", jail / "notes.md", jail)
    allows("nested child inside root", jail / "sub" / "deep.txt", jail)
    allows("the root itself", jail, jail)
    allows("non-existent path inside root", jail / "nope.md", jail)
    refuses("../ traversal out of root", jail / ".." / "etc" / "passwd", jail)
    refuses("absolute path outside root", outside / "secret.txt", jail)
    refuses("/etc/passwd", "/etc/passwd", jail)

    # ~ expansion: the root itself given as a tilde string must resolve
    home_jail = Path.home()
    allows("~ expansion resolves", "~", home_jail)
    ok("~ resolves to home", path_guard("~", home_jail) == Path.home().resolve())

    print("\n--- sibling directory sharing the root's name as a prefix ---")
    # A containment check written as str(p).startswith(str(root)) passes every
    # other test in this file and still lets this through: "/tmp/jail-evil"
    # starts with "/tmp/jail". Caught by mutation testing, not by inspection.
    evil = Path(str(jail) + "-evil")
    evil.mkdir(exist_ok=True)
    (evil / "loot.txt").write_text("PRIVATE")
    refuses("sibling '<root>-evil' outside root", evil / "loot.txt", jail)
    refuses("the sibling directory itself", evil, jail)

    refuses("nested path under the prefix-sibling",
            evil / "sub" / "x.txt", jail)

    # The mirror image: a genuine child whose name merely extends a sibling's
    # must still be allowed, so the fix can't just be a blunter string test.
    (jail / "subterm").mkdir(exist_ok=True)
    (jail / "subterm" / "fine.txt").write_text("fine")
    allows("real child 'subterm' inside root", jail / "subterm" / "fine.txt", jail)

    print("\n--- symlink escape (the reason we resolve before checking) ---")
    link = jail / "innocent.md"
    link.symlink_to(outside / "secret.txt")
    refuses("symlink inside root -> outside root", link, jail)

    dirlink = jail / "backdoor"
    dirlink.symlink_to(outside)
    refuses("symlinked directory -> outside root", dirlink / "secret.txt", jail)

    # a symlink that stays inside is fine
    inner = jail / "alias.md"
    inner.symlink_to(jail / "notes.md")
    allows("symlink inside root -> inside root", inner, jail)

    print("\n--- deny list (inside the jail, still refused) ---")
    for name in ["config.py", ".env", ".netrc", "id_rsa", "credentials.json"]:
        (jail / name).write_text("SECRET")
        refuses(f"{name} refused inside root", jail / name, jail, expect="deny list")

    for name in ["server.pem", "private.key", "backup.kdbx", ".env.production",
                 "deploy_ed25519"]:
        (jail / name).write_text("SECRET")
        refuses(f"{name} refused by pattern", jail / name, jail, expect="denied pattern")

    ssh = jail / ".ssh"
    ssh.mkdir()
    (ssh / "known_hosts").write_text("x")
    refuses(".ssh/ component refused", ssh / "known_hosts", jail, expect="never readable")

    print("\n--- deny list is case-insensitive ---")
    (jail / "Config.PY").write_text("SECRET")
    refuses("Config.PY refused", jail / "Config.PY", jail, expect="deny list")

    print("\n--- deny list survives a rename (checks the resolved target) ---")
    sneaky = jail / "totally_fine_notes.md"
    sneaky.symlink_to(jail / "config.py")
    refuses("symlink named .md -> config.py", sneaky, jail, expect="deny list")

    print("\n--- copies of config.py escape an exact-name match ---")
    for name in ["config.py.bak", "config.py.old", "config.py.save",
                 "config.py.orig", "config.py.swp"]:
        (jail / name).write_text("API_KEY = 'sk-LEAK'")
        refuses(f"{name} refused", jail / name, jail, expect="denied pattern")

    print("\n--- compiled bytecode embeds the source's string literals ---")
    cache = jail / "__pycache__"
    cache.mkdir(exist_ok=True)
    (cache / "config.cpython-314.pyc").write_bytes(b"\x00sk-LEAK")
    refuses("__pycache__/config.*.pyc refused",
            cache / "config.cpython-314.pyc", jail, expect="never readable")
    (jail / "loose.pyc").write_bytes(b"\x00sk-LEAK")
    refuses("a .pyc outside __pycache__ too",
            jail / "loose.pyc", jail, expect="denied pattern")

    print("\n--- lookalikes that must still be allowed ---")
    for name in ["config.example.py", "configuration.py", "environment.md",
                 "keyboard.py", "monkey.txt"]:
        (jail / name).write_text("fine")
        allows(f"{name} allowed", jail / name, jail)

    print("\n--- the real thing: cfc's own config.py is inside ~/projects ---")
    real_root = Path("~/projects").expanduser()
    real_cfg = ROOT / "config.py"
    if real_cfg.exists():
        refuses("the actual config.py holding API_KEY",
                real_cfg, real_root, expect="deny list")
    allows("but main.py is attachable", ROOT / "main.py", real_root)

    print("\n--- the write jail is a separate, narrower universe ---")
    # The point of the split: a path being readable says nothing about it
    # being writable. These use the same path_guard, against a different set.
    outbox = Path(tempfile.mkdtemp(prefix="outbox-"))
    allows("a path inside the write root passes", outbox / "note.md", outbox)
    refuses("a READABLE path is not writable",
            jail / "notes.md", outbox, expect="outside")
    refuses("the cfc source is not writable",
            ROOT / "main.py", outbox, expect="outside")
    refuses("traversal out of the write root is refused",
            outbox / ".." / "escape.md", outbox, expect="outside")
    # The deny list is root-agnostic: it applies to writes too, so a write
    # root can never be used to *create* a file the read jail would refuse.
    refuses("deny list still applies inside the write root",
            outbox / "config.py", outbox, expect="deny list")

    print("\n--- a write root may not overlap the source tree ---")
    # Enforced at construction rather than by a deny-list entry: the scripts
    # simply do not exist in the writable universe.
    for bad, why in [(ROOT, "the source dir itself"),
                     (ROOT / "sub", "a dir inside the source"),
                     (ROOT.parent, "a dir containing the source")]:
        try:
            ToolContext.for_chat(read_roots=(jail,), write_roots=(bad,))
            ok(f"write root rejected: {why}", False)
            print(f"       LET THROUGH -> {bad}")
        except ScopeError:
            ok(f"write root rejected: {why}", True)
    try:
        ToolContext.for_chat(read_roots=(jail,), write_roots=(outbox,))
        ok("an unrelated write root is fine", True)
    except ScopeError as e:
        ok("an unrelated write root is fine", False)
        print(f"       unexpected refusal: {e}")

    print("\n--- read roots never imply write access ---")
    bare = as_context((jail,))
    ok("a bare roots value yields no write scope", bare.write_roots == ())
    ok("...and cannot write", not bare.can_write)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
