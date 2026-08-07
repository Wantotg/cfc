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
# migration in development/CHANGELOG.md, which does choose to list every id).
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

    print("\n--- MODELS[id].preset_params: which sampling keys are "
          "declared, never guessed ---")
    spec = models._spec("x", preset_params=("temperature", "top_p"))
    ok("valid two-key declaration", spec.preset_params == ("temperature", "top_p"))
    spec = models._spec("x", preset_params=("temperature",))
    ok("valid one-key declaration", spec.preset_params == ("temperature",))
    spec = models._spec("x")
    ok("unset preset_params declares nothing", spec.preset_params == ())
    spec = models._spec("x", preset_params=None)
    ok("explicit None declares nothing too", spec.preset_params == ())

    msg = raises(lambda: models._spec("x", preset_params=("wobble",)))
    ok("an unknown preset_params key is refused",
       msg and "'x'" in msg and "wobble" in msg, msg)
    msg = raises(lambda: models._spec(
        "x", preset_params=("temperature", "temperature")))
    ok("a duplicate preset_params key is refused",
       msg and "temperature" in msg, msg)
    msg = raises(lambda: models._spec("x", preset_params="temperature"))
    ok("a bare string (not a list/tuple) is refused",
       msg and "preset_params" in msg, msg)

    print("\n--- legacy translation declares no preset support ---")
    legacy2 = models.load(LEGACY_CFG, warn=_silent_warn)
    ok("every legacy-translated record declares nothing",
       all(m.preset_params == () for m in legacy2), legacy2)

    print("\n--- PARAMETER_PRESETS: validated at load, same discipline as "
          "MODELS ---")
    cfg = SimpleNamespace(PARAMETER_PRESETS={
        "creative": dict(temperature=1.1, top_p=0.95),
        "precise": dict(temperature=0.2),
    })
    presets = models.load_presets(cfg)
    ok("both presets load, one and two keys",
       presets == {"creative": {"temperature": 1.1, "top_p": 0.95},
                  "precise": {"temperature": 0.2}}, presets)

    ok("no PARAMETER_PRESETS attribute is empty, not an error",
       models.load_presets(SimpleNamespace()) == {})
    ok("PARAMETER_PRESETS = {} is empty too",
       models.load_presets(SimpleNamespace(PARAMETER_PRESETS={})) == {})

    def preset_raises(presets_dict):
        return raises(lambda: models.load_presets(
            SimpleNamespace(PARAMETER_PRESETS=presets_dict)))

    msg = preset_raises({"loud": dict(temperature=2.5)})
    ok("temperature above 2 is refused", msg and "loud" in msg, msg)
    msg = preset_raises({"loud": dict(temperature=-0.1)})
    ok("temperature below 0 is refused", msg and "loud" in msg, msg)
    msg = preset_raises({"loud": dict(top_p=1.5)})
    ok("top_p above 1 is refused", msg and "loud" in msg, msg)
    msg = preset_raises({"loud": dict(top_p=-0.5)})
    ok("top_p below 0 is refused", msg and "loud" in msg, msg)
    ok("temperature at the boundary (0 and 2) is fine",
       models.load_presets(SimpleNamespace(PARAMETER_PRESETS={
           "lo": dict(temperature=0), "hi": dict(temperature=2)})) ==
       {"lo": {"temperature": 0.0}, "hi": {"temperature": 2.0}})
    ok("top_p at the boundary (0 and 1) is fine",
       models.load_presets(SimpleNamespace(PARAMETER_PRESETS={
           "lo": dict(top_p=0), "hi": dict(top_p=1)})) ==
       {"lo": {"top_p": 0.0}, "hi": {"top_p": 1.0}})

    msg = preset_raises({"loud": dict(temperature=True)})
    ok("a boolean value is refused, not read as 0/1", msg and "loud" in msg, msg)
    msg = preset_raises({"loud": dict(temperature=float("nan"))})
    ok("NaN is refused", msg and "loud" in msg, msg)
    msg = preset_raises({"loud": dict(temperature=float("inf"))})
    ok("infinity is refused", msg and "loud" in msg, msg)
    msg = preset_raises({"loud": dict(wobble=0.5)})
    ok("an unknown key is refused", msg and "wobble" in msg, msg)
    msg = preset_raises({"loud": dict()})
    ok("an empty params dict is refused", msg and "loud" in msg, msg)
    msg = preset_raises({"": dict(temperature=0.5)})
    ok("a blank name is refused", msg is not None, msg)
    msg = preset_raises({"default": dict(temperature=0.5)})
    ok("a preset literally named 'default' is refused — that word means "
       "'clear' at /preset default", msg and "default" in msg, msg)
    msg = preset_raises({"Default": dict(temperature=0.5)})
    ok("...case-insensitively", msg and "default" in msg, msg)
    msg = raises(lambda: models.load_presets(
        SimpleNamespace(PARAMETER_PRESETS="not-a-dict")))
    ok("PARAMETER_PRESETS itself must be a dict", msg is not None, msg)

    print("\n--- compatibility filtering: callers never inspect records "
          "directly ---")
    models.MODELS = [
        models._spec("both", preset_params=("temperature", "top_p")),
        models._spec("temp-only", preset_params=("temperature",)),
        models._spec("none-declared"),
    ]
    models.PARAMETER_PRESETS = {
        "creative": {"temperature": 1.1, "top_p": 0.95},
        "precise": {"temperature": 0.2},
    }
    ok("preset_names lists every configured preset",
       set(models.preset_names()) == {"creative", "precise"})
    ok("preset_params returns the validated dict",
       models.preset_params("precise") == {"temperature": 0.2})
    ok("an unknown preset name returns None",
       models.preset_params("ghost-preset") is None)
    ok("a model declaring both keys is compatible with both presets",
       set(models.compatible_presets("both")) == {"creative", "precise"})
    ok("a model declaring only temperature is compatible with the "
       "single-key preset only",
       models.compatible_presets("temp-only") == ["precise"])
    ok("a model declaring nothing is compatible with nothing",
       models.compatible_presets("none-declared") == [])
    ok("an unknown model is compatible with nothing",
       models.compatible_presets("totally-unheard-of") == [])
    ok("preset_compatible agrees with compatible_presets",
       models.preset_compatible("both", "creative") is True
       and models.preset_compatible("none-declared", "creative") is False)

    print("\n--- a model switch clears an incompatible preset (main.py's "
          "own rule, pinned here at the boundary it reads) ---")
    # main.py's h_model clears `active_preset` when the new model doesn't
    # declare every key the active preset uses — this is the exact check it
    # runs, proven against the compatibility helper it calls.
    active = "creative"
    ok("switching onto a fully-compatible model preserves it",
       models.preset_compatible("both", active) is True)
    ok("switching onto a partially-compatible model clears it",
       models.preset_compatible("temp-only", active) is False)

    print("\n--- W-08: a suspicious multiple-slash id is marked, never "
          "judged ---")
    ok("a plain single-slash id is not suspicious",
       models.has_suspicious_slashes("vendor/model") is False)
    ok("no slash at all is not suspicious",
       models.has_suspicious_slashes("plainmodel") is False)
    ok("exactly two slashes is suspicious",
       models.has_suspicious_slashes("vendor/model/extra") is True)
    ok("three slashes is suspicious too — the rule is 'more than one', "
       "not 'exactly two'",
       models.has_suspicious_slashes("a/b/c/d") is True)

    saved_models, saved_startup = models.MODELS, models._startup_warnings
    try:
        models.MODELS = [
            models._spec("vendor/ok-model", tools=True, limit=10),
            models._spec("vendor/typo/concatenated", tools=True,
                        routine=True, limit=10),
        ]
        models._startup_warnings = []
        warnings = models.startup_warnings()
        ok("the suspicious id is named in startup_warnings()",
           any("vendor/typo/concatenated" in w for w in warnings), warnings)
        ok("the clean id is not", not any("vendor/ok-model" in w
                                          for w in warnings), warnings)
        ok("the wording says it *may* be a typo, never that it's invalid",
           any("may be a typo" in w for w in warnings), warnings)
        ok("startup_warnings recomputes live from the current MODELS, not "
           "a snapshot taken at import",
           len(warnings) == 1, warnings)

        models._startup_warnings = ["config.py's MODELS is still a plain "
                                    "list — see config.example.py"]
        combined = models.startup_warnings()
        ok("the legacy-shape notice and the slash warning coexist",
           len(combined) == 2, combined)

        print("\n--- W-08: the predicate never touches selection or "
              "capability paths ---")
        ok("a suspicious id still supports tools if it's declared to",
           models.supports_tools("vendor/typo/concatenated") is True)
        ok("...and is still routine-vetted",
           models.is_routine_vetted("vendor/typo/concatenated") is True)
        ok("...and is still known and listed",
           "vendor/typo/concatenated" in models.known_ids()
           and "vendor/typo/concatenated" in models.listed_ids())
        ok("...and by_id still returns its real record",
           models.by_id("vendor/typo/concatenated").tools is True)
    finally:
        models.MODELS = saved_models
        models._startup_warnings = saved_startup

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
