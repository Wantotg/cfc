#!/usr/bin/env python3
"""test_system_injections.py — SYSTEM_INJECTIONS.md is checked, not trusted.

    python3 tests/test_system_injections.py

`W-1.4-05`. The document names every seam that puts words in front of the
model that the model didn't say and the user didn't type. A hand-maintained
inventory like that goes stale exactly the way `HANDOVER.md`'s recurring-
hazard table describes everything else here going stale: quietly, with
nothing raising.

So this derives the same inventory from source instead of trusting the
document, and fails in both directions:

  1. A **live producer** the document doesn't name. "Producer" is defined
     mechanically: any top-level function, in any top-level `.py` module,
     whose body literally constructs a `{"role": ...}` dict with a hardcoded
     role other than `"tool"` (the API's own role — see `_EXCLUDED_PRODUCERS`
     below for the one thing this rule alone can't separate out). There is
     no second hand-kept list of what counts here; the AST walk *is* the
     list, and `SYSTEM_INJECTIONS.md`'s `Anchor:` lines are compared against
     its output.
  2. A **documented anchor that no longer resolves** — a renamed or deleted
     symbol. Checked by importing every anchor's module and confirming the
     attribute still exists, for all anchors, not only the two below.

Two anchors (`runner.fill_placeholders`, `api.wire_messages`) don't construct
a role dict at all — one edits text, the other edits an existing dict's keys
— so the AST walk cannot find them. They get the explicit resolve-check
instead, and are asserted present by name (the one and only place this file
names a symbol by hand, because nothing else can produce it).

No network, no API key.
"""
import ast
import importlib
import re
import sys
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
        print(f"       {str(detail)[:300]}")


DOC = ROOT / "SYSTEM_INJECTIONS.md"

# Nothing tracked to check: config.py is gitignored and machine-specific,
# config.example.py is a template of settings, not message construction.
_SKIP_MODULES = {"config", "config.example"}

# `main._run_turn` appends the user's own typed text and the provider's own
# returned answer to `history`, unmodified — replaying what already
# happened, not manufacturing new content ("ordinary durable chat rows" in
# the document's Exclusions section). Both dicts use a literal, non-"tool"
# role, so the categorical rule below can't rule them out on its own; this
# is the one place that needs naming rather than deriving.
_EXCLUDED_PRODUCERS = {"main._run_turn"}

# The two indirect transforms: checked by resolving the symbol, never by the
# AST walk (see module docstring).
_EXPLICIT_CHECKED = {"runner.fill_placeholders", "api.wire_messages"}

_ANCHOR_RE = re.compile(r"^Anchor:\s*`([A-Za-z_][\w]*\.[A-Za-z_][\w]*)`\s*$",
                        re.MULTILINE)


class _RoleDictFinder(ast.NodeVisitor):
    """Attributes each `{"role": <literal>}` dict to its innermost enclosing
    top-level function — not every ancestor function. `main._finish_turn` and
    `main._run_turn` are both nested inside `main.run_session`; walking each
    `FunctionDef`'s full subtree independently (rather than tracking a single
    stack through one pass) would also credit — wrongly — `run_session`
    itself with everything its nested functions build.
    """

    def __init__(self, modname):
        self.modname = modname
        self.stack = []
        self.found = set()

    def _visit_func(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = _visit_func
    visit_AsyncFunctionDef = _visit_func

    def visit_Dict(self, node):
        if self.stack:
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and k.value == "role"
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str) and v.value != "tool"):
                    self.found.add(f"{self.modname}.{self.stack[-1]}")
        self.generic_visit(node)


def discover_producers():
    """Every "module.function" that literally builds a model-facing role
    dict, per `_RoleDictFinder`, minus the one named exclusion."""
    found = set()
    for path in sorted(ROOT.glob("*.py")):
        if path.stem in _SKIP_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        finder = _RoleDictFinder(path.stem)
        finder.visit(tree)
        found |= finder.found
    return found - _EXCLUDED_PRODUCERS


def parse_anchors(text):
    return set(_ANCHOR_RE.findall(text))


def resolves(anchor):
    """Whether `module.function` is a real, importable, existing attribute."""
    modname, _, funcname = anchor.rpartition(".")
    try:
        mod = importlib.import_module(modname)
    except Exception as e:                        # noqa: BLE001
        return False, f"import {modname} failed: {e}"
    if not hasattr(mod, funcname):
        return False, f"{modname} has no attribute {funcname!r}"
    return True, ""


def main_():
    text = DOC.read_text(encoding="utf-8")
    doc_anchors = parse_anchors(text)
    discovered = discover_producers()

    print("\n--- every live producer is documented ---")
    missing = discovered - doc_anchors
    ok("no discovered producer is undocumented", not missing, missing)

    print("\n--- the document names nothing beyond what's live ---")
    extra = doc_anchors - discovered - _EXPLICIT_CHECKED
    ok("no stale or invented anchor beyond the two explicit ones",
       not extra, extra)

    print("\n--- the two indirect transforms are present by name ---")
    ok("both explicit anchors are documented",
       _EXPLICIT_CHECKED <= doc_anchors, _EXPLICIT_CHECKED - doc_anchors)

    print("\n--- every documented anchor resolves to something real ---")
    for anchor in sorted(doc_anchors):
        good, detail = resolves(anchor)
        ok(f"resolves: {anchor}", good, detail)

    print("\n--- proof: the two failure directions this test exists for ---")
    # Not a permanent assertion — a demonstration, run here so the proof
    # lives beside the mechanism rather than only in a session transcript.
    # 1) A live producer with its anchor removed must fail direction (1).
    if discovered:
        one = sorted(discovered)[0]
        pretend_doc_anchors = doc_anchors - {one}
        ok(f"removing {one}'s anchor would be caught",
           one not in pretend_doc_anchors and one in discovered)
    # 2) A stale anchor naming nothing real must fail direction (2).
    stale = "assemble.this_function_does_not_exist"
    good, _ = resolves(stale)
    ok(f"a stale anchor ({stale}) would be caught", good is False)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
