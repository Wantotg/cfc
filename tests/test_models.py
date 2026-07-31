#!/usr/bin/env python3
"""test_models.py — the model-config boundary. No network, no config.py.

    python3 tests/test_models.py

Before 1.2.1 a model's properties were spread across four collections
(MODELS, TOOLS_MODELS, ROUTINE_MODELS, MODEL_LIMITS) that nothing forced to
agree — a typo in TOOLS_MODELS just meant tools silently never turned on.
`models.load()` replaces them with one ordered list of records; this file
drives it directly, off injected fixtures rather than the real config.py.

The load-bearing claim: a legacy fixture (the old four-collection shape) and
an equivalent new-shape fixture must answer every accessor identically. That
is what makes the translation in `models._from_legacy` trustworthy rather
than merely plausible.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import models
from models import ModelConfigError

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def raises(fn, exc=ModelConfigError):
    try:
        fn()
    except exc as e:
        return str(e)
    return None


# --- the fixture: Cas's real shape, in miniature ---------------------------
#
# Mirrors config.py's actual pattern: a routine variant (the non-thinking id)
# that is a *different string* from its chat, thinking-suffixed sibling, so
# ROUTINE_MODELS names an id MODELS never lists. deepseek-cheap is the
# ROUTINE_MODELS[0] case: the default is NOT the first routine-vetted id in
# combined order (that would be minimax-m3), it is this one.
LEGACY_CFG = SimpleNamespace(
    MODELS=[
        "vendor/glm:thinking",
        "vendor/deepseek:thinking",
        "vendor/minimax:thinking",
        "vendor/minimax",
    ],
    ROUTINE_MODELS=[
        "vendor/deepseek",          # not in MODELS at all — its own record
        "vendor/minimax",           # already in MODELS
    ],
    TOOLS_MODELS=[
        "vendor/glm:thinking",
        "vendor/deepseek:thinking",
        "vendor/minimax:thinking",
        "vendor/minimax",
    ],
    MODEL_LIMITS={
        "vendor/glm:thinking": 1_000_000,
        "vendor/deepseek:thinking": 1_000_000,
        "vendor/minimax:thinking": 512_000,
        "vendor/minimax": 512_000,
        # deliberately no entry for vendor/deepseek (routine-only, non-thinking)
    },
)

# The equivalent hand-written 1.2.1 shape — same records the legacy
# translation above would produce, written directly. `vendor/deepseek` stays
# `listed=False` here on purpose, to match what the legacy fixture produces;
# a real migration can choose to list it, but that is a separate decision
# from whether the two shapes describe the same models (see config.py's own
# migration in CHANGELOG.md, which does choose to list every id).
NEW_CFG = SimpleNamespace(MODELS=[
    dict(id="vendor/glm:thinking", tools=True, limit=1_000_000),
    dict(id="vendor/deepseek:thinking", tools=True, limit=1_000_000),
    dict(id="vendor/minimax:thinking", tools=True, limit=512_000),
    dict(id="vendor/minimax", tools=True, routine=True, limit=512_000),
    dict(id="vendor/deepseek", listed=False, routine=True,
        routine_default=True),
])


def _silent_warn(msg):
    pass


def main():
    print("\n--- legacy and new fixtures agree through every accessor ---")
    legacy = models.load(LEGACY_CFG, warn=_silent_warn)
    new = models.load(NEW_CFG)

    def snapshot(specs):
        saved = models.MODELS
        models.MODELS = specs
        try:
            return {
                "listed": models.listed_ids(),
                "known": models.known_ids(),
                "tools": [models.supports_tools(m.id) for m in specs],
                "tool_capable": models.tool_capable_ids(),
                "routine": [models.is_routine_vetted(m.id) for m in specs],
                "routine_ids": models.routine_ids(),
                "default": models.routine_default_id(),
                "limits": [models.context_limit(m.id) for m in specs],
            }
        finally:
            models.MODELS = saved

    ok("both fixtures produce the same 5 records",
       len(legacy) == len(new) == 5, (legacy, new))
    snap_legacy, snap_new = snapshot(legacy), snapshot(new)
    for key in snap_legacy:
        ok(f"...{key} agrees", snap_legacy[key] == snap_new[key],
           (key, snap_legacy[key], snap_new[key]))

    models.MODELS = legacy
    ok("legacy: the routine-only id is known but not displayed",
       "vendor/deepseek" in models.known_ids()
       and "vendor/deepseek" not in models.listed_ids())
    ok("legacy: the default is ROUTINE_MODELS[0], not combined-order-first",
       models.routine_default_id() == "vendor/deepseek")
    ok("legacy: a routine-only id with no MODEL_LIMITS entry is unknown, "
       "not zero",
       models.context_limit("vendor/deepseek") is None)

    print("\n--- missing MODELS is empty, not an error ---")
    ok("no MODELS attribute at all",
       models.load(SimpleNamespace()) == [])
    ok("MODELS = []",
       models.load(SimpleNamespace(MODELS=[])) == [])

    print("\n--- the legacy warning fires exactly once, only for legacy ---")
    seen = []
    models.load(LEGACY_CFG, warn=lambda m: seen.append(m))
    ok("one warning, naming config.example.py",
       len(seen) == 1 and "config.example.py" in seen[0], seen)
    seen2 = []
    models.load(NEW_CFG, warn=lambda m: seen2.append(m))
    ok("the new shape prints nothing", seen2 == [], seen2)

    print("\n--- invalid records are loud, and name the id and field ---")
    msg = raises(lambda: models.load(SimpleNamespace(
        MODELS=[dict(tools=True)])))
    ok("a record with no id names its position",
       msg and "MODELS[0]" in msg, msg)

    msg = raises(lambda: models.load(SimpleNamespace(
        MODELS=[dict(id="x", tools="yes")])))
    ok("a non-bool field names the id and the field",
       msg and "'x'" in msg and "tools" in msg, msg)

    msg = raises(lambda: models.load(SimpleNamespace(
        MODELS=[dict(id="x", limit=0)])))
    ok("a zero limit is invalid (must be positive or None)",
       msg and "'x'" in msg and "limit" in msg, msg)

    msg = raises(lambda: models.load(SimpleNamespace(
        MODELS=[dict(id="x", limit="big")])))
    ok("a non-int limit is invalid",
       msg and "'x'" in msg and "limit" in msg, msg)

    msg = raises(lambda: models.load(SimpleNamespace(
        MODELS=[dict(id="x", routine_default=True)])))
    ok("routine_default without routine is invalid",
       msg and "'x'" in msg and "routine_default" in msg, msg)

    msg = raises(lambda: models.load(SimpleNamespace(
        MODELS=[dict(id="x", routine=True, routine_default=True),
               dict(id="y", routine=True, routine_default=True)])))
    ok("two routine_default records is invalid",
       msg and "x" in msg and "y" in msg, msg)

    msg = raises(lambda: models.load(SimpleNamespace(
        MODELS=[dict(id="dup"), dict(id="dup")])))
    ok("a duplicate id is invalid",
       msg and "dup" in msg, msg)

    msg = raises(lambda: models.load(SimpleNamespace(MODELS=[dict(id="")])))
    ok("a blank id is invalid", msg is not None, msg)

    msg = raises(lambda: models.load(SimpleNamespace(MODELS=["not-a-dict"])))
    ok("legacy detection is by first-item type: a mixed list still reads "
       "as legacy and 'not-a-dict' is just an id string",
       msg is None)

    print("\n--- accessors on an unknown id degrade quietly ---")
    models.MODELS = [models._spec("known", tools=True, limit=10)]
    ok("an id not in MODELS supports no tools",
       models.supports_tools("ghost") is False)
    ok("...is not routine-vetted", models.is_routine_vetted("ghost") is False)
    ok("...has no context limit", models.context_limit("ghost") is None)
    ok("...by_id returns None", models.by_id("ghost") is None)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
