#!/usr/bin/env python3
"""
test_assemble.py — the system layers of a request. No API, no db, no terminal.

    python3 tests/test_assemble.py

`assemble_system` is a pure function over bodies, so this suite is a table of
calls. What is worth pinning is not that it concatenates — it is the two things
a future edit is likely to get wrong:

  * the *order* the layers land in, which was inherited from the inline code it
    replaced and is a property of every request cfc sends, and
  * that an empty layer is an absent one, not a blank system message. A blank
    `system` turn is not free — it is a message the model reads as deliberate.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from assemble import assemble_system

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def bodies(msgs):
    return [m["content"] for m in msgs]


def main():
    print("--- the extraction changed nothing ---")
    # Byte-for-byte what main.py built inline before this function existed:
    # persona first, then the system prompt, each as its own system message.
    old = [{"role": "system", "content": "PERSONA"},
           {"role": "system", "content": "SYSTEM"}]
    ok("two layers assemble exactly as the inline code did",
       assemble_system("SYSTEM", "PERSONA") == old,
       assemble_system("SYSTEM", "PERSONA"))

    print("\n--- order ---")
    ok("persona comes before the system prompt",
       bodies(assemble_system("SYSTEM", "PERSONA")) == ["PERSONA", "SYSTEM"])
    ok("traits come last",
       bodies(assemble_system("SYSTEM", "PERSONA", ["T1", "T2"]))
       == ["PERSONA", "SYSTEM", "T1", "T2"])
    ok("traits keep attach order, they are not sorted",
       bodies(assemble_system(traits=["zeta", "alpha", "mu"]))
       == ["zeta", "alpha", "mu"],
       "attach order is the only order the user controls")
    ok("one message per trait, no joining",
       len(assemble_system(traits=["a", "b", "c"])) == 3)

    print("\n--- absent layers ---")
    ok("nothing attached is an empty prefix", assemble_system() == [])
    ok("None layers contribute nothing",
       assemble_system(None, None, None) == [])
    ok("an empty string is an absent layer, not a blank message",
       assemble_system("", "") == [])
    ok("a whitespace-only body is absent too",
       assemble_system("   \n  ") == [],
       "a blank system message reads to the model as deliberate")
    ok("an empty trait list is fine", assemble_system("S", traits=[]) ==
       [{"role": "system", "content": "S"}])
    ok("a blank trait drops out without shifting the others",
       bodies(assemble_system(traits=["a", "", "c"])) == ["a", "c"])
    ok("only the system prompt still works",
       bodies(assemble_system("SYSTEM")) == ["SYSTEM"])
    ok("only a persona still works",
       bodies(assemble_system(persona="PERSONA")) == ["PERSONA"])

    print("\n--- shape ---")
    msgs = assemble_system("S", "P", ["T"])
    ok("every layer is a system-role message",
       all(m["role"] == "system" for m in msgs), msgs)
    ok("nothing but role and content is emitted",
       all(set(m) == {"role", "content"} for m in msgs), msgs)
    ok("bodies are passed through untouched",
       assemble_system("  leading and trailing  ")[0]["content"]
       == "  leading and trailing  ",
       "the assembler decides order, not content")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
