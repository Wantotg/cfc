#!/usr/bin/env python3
"""
test_model.py — the forgiving `:model` selector. No API calls.

    python3 tests/test_model.py

`:model` used to set whatever string you typed, verbatim. A one-character slip
(`moonshotai/kimi-2.6:thinking` for `…kimi-k2.6…`) sailed straight through and
came back as an opaque provider 400 a turn later. The selector resolves a loose
query against the models you've configured (MODELS ∪ ROUTINE_MODELS) and either
switches, confirms, offers a numbered pick, or — only when nothing is
recognisable — passes the raw query through so an unlisted model is still
reachable.

`resolve_model` is the pure core and carries the weight here; `select_model` is
a thin I/O shell over it, exercised with a scripted `input()`.
"""
import builtins
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import commands

PASS, FAIL = [], []

POOL = [
    "zai-org/glm-5.2:thinking",
    "zai-org/glm-5.2",
    "deepseek/deepseek-v4-pro:thinking",
    "deepseek/deepseek-v4-pro",
    "moonshotai/kimi-k2.6:thinking",
    "moonshotai/kimi-k2.6",
    "minimax/minimax-m3",
]


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def scripted(answers):
    """A stand-in for input() that pops from a fixed list of answers."""
    queue = list(answers)

    def _input(prompt=""):
        return queue.pop(0) if queue else ""
    return _input


def run_select(query, pool, answers):
    """Drive select_model with a scripted input and the given config pool.
    Returns (result, output)."""
    saved_models = commands.MODELS
    saved_routine = commands.ROUTINE_MODELS
    saved_input = builtins.input
    saved_file = commands.console.file
    commands.MODELS = list(pool)
    commands.ROUTINE_MODELS = []
    builtins.input = scripted(answers)
    out = io.StringIO()
    commands.console.file = out
    try:
        with redirect_stdout(out):
            result = commands.select_model(query)
    finally:
        commands.MODELS = saved_models
        commands.ROUTINE_MODELS = saved_routine
        builtins.input = saved_input
        commands.console.file = saved_file
    return result, out.getvalue()


def main():
    print("\n--- resolve_model: the pure tiers ---")
    ok("an exact id resolves outright",
       commands.resolve_model("zai-org/glm-5.2", POOL) == ("exact",
                                                           "zai-org/glm-5.2"))
    # Case and spacing still don't matter — and this now lands on 'exact'
    # rather than 'one', because `minimax-m3` is the model's whole name and not
    # merely a substring of it. Nobody types the vendor, so a bare name that
    # matches a whole model name switches with no question asked.
    ok("case and spacing don't matter",
       commands.resolve_model("MiniMax M3", POOL) == ("exact",
                                                      "minimax/minimax-m3"))

    # The report this tier exists for: `deepseek-v4-pro` opened a numbered
    # picker of three, because only the full `vendor/model` id counted as exact
    # and the substring tier matched every id containing the name.
    ok("a bare model name is exact, not a picker",
       commands.resolve_model("deepseek-v4-pro", POOL) == (
           "exact", "deepseek/deepseek-v4-pro"))
    ok("...and does not lose to its own :thinking sibling",
       commands.resolve_model("glm-5.2", POOL) == ("exact",
                                                   "zai-org/glm-5.2"))
    ok("the :thinking sibling is still nameable in full",
       commands.resolve_model("glm-5.2:thinking", POOL) == (
           "exact", "zai-org/glm-5.2:thinking"))

    # Two vendors, one model name: the tier must decline rather than pick a
    # side. It falls through to the substring tier, which is the picker.
    two_vendors = ["alpha/gpt-9", "beta/gpt-9"]
    kind, data = commands.resolve_model("gpt-9", two_vendors)
    ok("a bare name shipped by two vendors goes to the picker",
       kind == "many" and sorted(data) == two_vendors, (kind, data))

    ok("a unique substring is a single candidate",
       commands.resolve_model("minimax", POOL) == ("one",
                                                   "minimax/minimax-m3"))
    kind, data = commands.resolve_model("deepseek", POOL)
    ok("an ambiguous stem returns every match, in pool order",
       kind == "many" and data == ["deepseek/deepseek-v4-pro:thinking",
                                    "deepseek/deepseek-v4-pro"], (kind, data))
    ok("an unknown model is 'none' (the raw query survives upstream)",
       commands.resolve_model("openai/gpt-4", POOL) == ("none", None))
    ok("an empty query is 'none', never a crash",
       commands.resolve_model("   ", POOL) == ("none", None))

    print("\n--- resolve_model: the typo path is why this exists ---")
    # The exact slip from the 0.6 trials: kimi-2.6 for kimi-k2.6. No substring
    # hit, so the fuzzy nearest has to catch it — offering the k2.6 pair rather
    # than letting the typo reach the provider as a 400.
    kind, data = commands.resolve_model("moonshotai/kimi-2.6:thinking", POOL)
    ok("a one-character slip is caught, not passed through",
       kind in ("one", "many") and all("kimi-k2.6" in m for m in
                                        ([data] if kind == "one" else data)),
       (kind, data))

    print("\n--- select_model: exact needs no prompt ---")
    res, out = run_select("zai-org/glm-5.2", POOL, [])
    ok("an exact id switches with no question",
       res == "zai-org/glm-5.2" and "did you mean" not in out, out)

    print("\n--- select_model: confirm a single candidate ---")
    res, _ = run_select("minimax", POOL, [""])      # Enter = yes
    ok("Enter confirms the suggestion", res == "minimax/minimax-m3", res)
    res, _ = run_select("minimax", POOL, ["y"])
    ok("'y' confirms too", res == "minimax/minimax-m3", res)
    res, out = run_select("minimax", POOL, ["n"])
    ok("'n' cancels, returning None", res is None, res)

    print("\n--- select_model: pick from several ---")
    res, out = run_select("deepseek", POOL, ["2"])
    ok("a number picks that option",
       res == "deepseek/deepseek-v4-pro", res)
    ok("...the list is shown to choose from", "matches 2 models" in out, out)
    res, _ = run_select("deepseek", POOL, [""])     # Enter = cancel
    ok("Enter cancels the pick", res is None, res)
    res, _ = run_select("deepseek", POOL, ["9"])
    ok("an out-of-range number cancels", res is None, res)
    res, _ = run_select("deepseek", POOL, ["two"])
    ok("a non-number cancels rather than crashing", res is None, res)

    print("\n--- select_model: an unlisted model still goes through ---")
    res, out = run_select("openai/gpt-4o", POOL, [])
    ok("an unrecognised id is set raw", res == "openai/gpt-4o", res)
    ok("...but flagged, so a typo isn't mistaken for intent",
       "isn't in your configured models" in out, out)

    print("\n--- select_model: no configured models, no fuss ---")
    res, out = run_select("anything/at-all", [], [])
    ok("an empty pool passes the query through untouched",
       res == "anything/at-all" and out.strip() == "", (res, out))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
