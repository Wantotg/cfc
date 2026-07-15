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
        refuses(f"{name} refused inside root", jail / name, jail, expect="refused")

    for name in ["server.pem", "private.key", "backup.kdbx", ".env.production",
                 "deploy_ed25519"]:
        (jail / name).write_text("SECRET")
        refuses(f"{name} refused by pattern", jail / name, jail, expect="refused")

    ssh = jail / ".ssh"
    ssh.mkdir()
    (ssh / "known_hosts").write_text("x")
    refuses(".ssh/ component refused", ssh / "known_hosts", jail, expect="refused")

    print("\n--- deny list is case-insensitive ---")
    (jail / "Config.PY").write_text("SECRET")
    refuses("Config.PY refused", jail / "Config.PY", jail, expect="refused")

    print("\n--- deny list survives a rename (checks the resolved target) ---")
    sneaky = jail / "totally_fine_notes.md"
    sneaky.symlink_to(jail / "config.py")
    refuses("symlink named .md -> config.py", sneaky, jail, expect="refused")

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
                real_cfg, real_root, expect="refused")
    allows("but main.py is attachable", ROOT / "main.py", real_root)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
