#!/usr/bin/env python3
"""
test_vault.py — the vault-policy and display-label authority (v1.6).

    python3 tests/test_vault.py

Plain script, no pytest. Two things get pinned down:

  * `vault.exposed()` — normalisation of VAULT_SCOPES, the hidden-ancestor-
    always-wins nesting rule, declaration-order independence, every invalid
    declaration class, and the requested-vs-resolved symlink checks.
  * `vault.title_for()` — read-only frontmatter title with a filename
    fallback on every failure shape.

VAULT_ROOT/VAULT_SCOPES are monkeypatched directly on the module (read
through the attribute at call time, never captured at import — see
pools.py's `configured` for the same discipline), so nothing here touches
the real config.py.
"""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import vault

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def _mkvault():
    root = Path(tempfile.mkdtemp(prefix="vault-root-")).resolve()
    (root / "01 personal").mkdir()
    (root / "01 personal" / "secret.md").write_text("shh", encoding="utf-8")
    (root / "01 personal" / "public").mkdir()
    (root / "01 personal" / "public" / "note.md").write_text(
        "n", encoding="utf-8")
    (root / "03 resources").mkdir()
    (root / "03 resources" / "wiki db").mkdir()
    (root / "03 resources" / "wiki db" / "page.md").write_text(
        "p", encoding="utf-8")
    (root / "unscoped").mkdir()
    (root / "unscoped" / "sibling.md").write_text("s", encoding="utf-8")
    return root


def main():
    root = _mkvault()
    vault.VAULT_ROOT = str(root)

    print("\n--- no-config compatibility ---")
    vault.VAULT_SCOPES = ()
    ok("nothing configured: everything exposed",
       vault.exposed(str(root / "01 personal" / "secret.md"),
                     root / "01 personal" / "secret.md"))
    kind, scopes, problems = vault.state()
    ok("state is OK with no scopes", kind == vault.OK and not scopes
       and not problems)

    print("\n--- valid nested scopes, declaration-order independence ---")
    scopes_a = (
        dict(name="personal", path="01 personal", exposed=False),
        dict(name="personal-public", path="01 personal/public", exposed=True),
        dict(name="wiki", path="03 resources/wiki db", exposed=True),
    )
    scopes_b = tuple(reversed(scopes_a))  # same set, opposite declared order

    for label, decl in (("declared parent-first", scopes_a),
                        ("declared child-first", scopes_b)):
        vault.VAULT_SCOPES = decl
        kind, scopes, problems = vault.state()
        ok(f"{label}: state is OK", kind == vault.OK and not problems,
           problems)
        secret = root / "01 personal" / "secret.md"
        ok(f"{label}: hidden scope's own file is hidden",
           not vault.exposed(str(secret), secret))
        pub = root / "01 personal" / "public" / "note.md"
        ok(f"{label}: exposed nested scope stays hidden — ancestor wins",
           not vault.exposed(str(pub), pub))
        wiki = root / "03 resources" / "wiki db" / "page.md"
        ok(f"{label}: an unrelated exposed scope is exposed",
           vault.exposed(str(wiki), wiki))
        sib = root / "unscoped" / "sibling.md"
        ok(f"{label}: an unscoped sibling stays exposed",
           vault.exposed(str(sib), sib))

    print("\n--- requested-versus-resolved path checks ---")
    vault.VAULT_SCOPES = scopes_a
    secret = root / "01 personal" / "secret.md"
    # A route through a hidden ancestor: requested and resolved agree, no
    # symlink involved, and it's still refused.
    ok("a direct route through a hidden ancestor is refused",
       not vault.exposed(str(secret), secret))

    if hasattr(os, "symlink"):
        try:
            link_in = root / "unscoped" / "peek"
            link_in.symlink_to(secret)
            ok("resolved target crosses a hidden ancestor via a symlink "
               "sitting OUTSIDE it — refused",
               not vault.exposed(str(link_in), link_in.resolve()))
        except OSError:
            pass  # platform without symlink permission; skip, don't fail

        try:
            outward = root / "01 personal" / "escape"
            target = root / "03 resources" / "wiki db" / "page.md"
            outward.symlink_to(target)
            ok("a symlink named INSIDE a hidden dir stays refused even "
               "though it resolves to exposed material",
               not vault.exposed(str(outward), outward.resolve()))
        except OSError:
            pass

    print("\n--- all invalid declaration classes ---")

    def invalid(label, decl, needle=None):
        vault.VAULT_SCOPES = decl
        kind, scopes, problems = vault.state()
        ok(f"{label}: state is INVALID", kind == vault.INVALID, problems)
        if needle:
            ok(f"{label}: names the problem",
               any(needle in p for p in problems), problems)

    invalid("absolute path", (dict(name="x", path=str(root / "01 personal"),
                                   exposed=False),), "absolute")
    invalid("escaping path", (dict(name="x", path="../elsewhere",
                                   exposed=False),), "..")
    invalid("missing directory", (dict(name="x", path="does not exist",
                                       exposed=False),), "does not exist")
    invalid("duplicate name",
            (dict(name="dup", path="01 personal", exposed=False),
             dict(name="dup", path="03 resources", exposed=True)),
            "duplicate")

    if hasattr(os, "symlink"):
        try:
            outside = Path(tempfile.mkdtemp(prefix="outside-vault-"))
            escape_link = root / "escape-link"
            escape_link.symlink_to(outside)
            invalid("symlink-escape declaration",
                    (dict(name="x", path="escape-link", exposed=False),),
                    "escape")
        except OSError:
            pass

    print("\n--- invalid config fails closed only for model-facing vault "
          "access ---")
    vault.VAULT_SCOPES = (dict(name="x", path="does not exist",
                               exposed=False),)
    secret = root / "01 personal" / "secret.md"
    ok("a vault-rooted path is refused while the declaration is invalid",
       not vault.exposed(str(secret), secret))
    outside = Path(tempfile.mkdtemp(prefix="outside-vault-2-"))
    unrelated = outside / "readme.md"
    unrelated.write_text("x", encoding="utf-8")
    ok("a path outside VAULT_ROOT is unaffected by an invalid declaration",
       vault.exposed(str(unrelated), unrelated))

    print("\n--- VAULT_SCOPES set but VAULT_ROOT is not ---")
    vault.VAULT_ROOT = ""
    vault.VAULT_SCOPES = (dict(name="x", path="01 personal", exposed=False),)
    kind, scopes, problems = vault.state()
    ok("no VAULT_ROOT with scopes configured is INVALID",
       kind == vault.INVALID and problems, problems)
    vault.VAULT_ROOT = str(root)

    # Restore for the title tests below.
    vault.VAULT_SCOPES = ()

    print("\n--- title_for: fallbacks ---")
    d = Path(tempfile.mkdtemp(prefix="titles-"))

    titled = d / "titled.md"
    titled.write_text("---\ntitle: Aquarium Nitrogen Cycle\n---\n\nbody\n",
                      encoding="utf-8")
    ok("a real title reads back", vault.title_for(titled) ==
       "Aquarium Nitrogen Cycle")

    absent = d / "absent.md"
    absent.write_text("no frontmatter here\n", encoding="utf-8")
    ok("no frontmatter falls back to the filename",
       vault.title_for(absent) == "absent.md")

    empty_fm = d / "empty-fm.md"
    empty_fm.write_text("---\n---\n\nbody\n", encoding="utf-8")
    ok("frontmatter with no title falls back to the filename",
       vault.title_for(empty_fm) == "empty-fm.md")

    non_string = d / "non-string.md"
    non_string.write_text("---\ntitle:\n  - a\n  - b\n---\n\nbody\n",
                          encoding="utf-8")
    ok("a non-string title falls back to the filename",
       vault.title_for(non_string) == "non-string.md")

    malformed = d / "malformed.md"
    malformed.write_text('---\ntitle: "unterminated\n---\n\nbody\n',
                         encoding="utf-8")
    ok("malformed YAML falls back to the filename",
       vault.title_for(malformed) == "malformed.md")

    blank_title = d / "blank-title.md"
    blank_title.write_text("---\ntitle: \"   \"\n---\n\nbody\n",
                           encoding="utf-8")
    ok("a blank/whitespace title falls back to the filename",
       vault.title_for(blank_title) == "blank-title.md")

    missing = d / "does-not-exist.md"
    ok("an unreadable (missing) file falls back to the filename",
       vault.title_for(missing) == "does-not-exist.md")

    bad_encoding = d / "bad-encoding.md"
    bad_encoding.write_bytes(b"---\ntitle: \xff\xfe bad\n---\n\nbody\n")
    ok("an encoding failure falls back to the filename",
       vault.title_for(bad_encoding) == "bad-encoding.md")

    non_dict_fm = d / "non-dict-fm.md"
    non_dict_fm.write_text("---\n- a\n- b\n---\n\nbody\n", encoding="utf-8")
    ok("non-mapping frontmatter falls back to the filename",
       vault.title_for(non_dict_fm) == "non-dict-fm.md")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
