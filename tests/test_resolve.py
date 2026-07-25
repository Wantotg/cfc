#!/usr/bin/env python3
"""
test_resolve.py — the shared name resolver behind /add and /remove. No API.

    python3 tests/test_resolve.py

The pure core (`pools.match`, `pools.match_active`, `pools.fill`) carries the
weight; `commands.resolve_layer` / `resolve_attached` are thin I/O shells and
are exercised with a scripted `input()`. Same split as
`resolve_model`/`select_model`, for the same reason: matching is testable
without a terminal, so it is.

The assertions that matter are the ones about **not guessing**:

  * tiers don't mix, so an exact name never loses to a near miss;
  * two different names matching equally well is a question, not a decision;
  * `/remove` searches what is attached, not what exists, so naming a prompt
    you never attached fails loudly instead of succeeding at nothing;
  * the collision walk compares like with like. It silently stopped advancing
    once because `sessions.system_prompt_name` holds `relax.md` and a pool
    resolves `relax` — the reason `pools.stem` exists.
"""
import builtins
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import pools
import commands

PASS, FAIL = [], []

# One name in all three pools (relax), one unique per pool, and a name that
# shares a substring with two others (cas / muse / terse all contain "s").
FIXTURE = {
    "prompt": {"cas", "relax"},
    "persona": {"muse", "relax"},
    "trait": {"relax", "terse", "bad#name"},
}


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def build(root):
    for kind, items in FIXTURE.items():
        d = root / kind
        d.mkdir(parents=True, exist_ok=True)
        for n in items:
            (d / f"{n}.md").write_text(f"body of {kind} {n}", encoding="utf-8")
        pools.POOLS[kind].configured = str(d)


def scripted(answers):
    queue = list(answers)

    def _input(prompt=""):
        return queue.pop(0) if queue else ""
    return _input


def run(fn, *args, answers=(), **kw):
    """Call an I/O shell with scripted input, returning (result, output)."""
    saved_input, saved_file = builtins.input, commands.console.file
    builtins.input = scripted(answers)
    out = io.StringIO()
    commands.console.file = out
    try:
        with redirect_stdout(out):
            res = fn(*args, **kw)
    finally:
        builtins.input = saved_input
        commands.console.file = saved_file
    return res, out.getvalue()


def main():
    with tempfile.TemporaryDirectory() as tmp:
        build(Path(tmp))

        print("--- tiers don't mix ---")
        ok("an exact name resolves to itself",
           pools.match("relax") == [("prompt", "relax"),
                                    ("persona", "relax"),
                                    ("trait", "relax")],
           pools.match("relax"))
        ok("an exact hit hides near misses",
           {n for _, n in pools.match("terse")} == {"terse"},
           "typing a name in full always does what it says")
        ok("a prefix resolves", {n for _, n in pools.match("rel")} == {"relax"})
        ok("a substring resolves",
           {n for _, n in pools.match("erse")} == {"terse"})
        ok("case never matters",
           {n for _, n in pools.match("RELAX")} == {"relax"},
           "these are filenames in a vault; capitalisation is a display choice")
        ok("nothing matching is [], not a guess", pools.match("wombat") == [])
        ok("an empty query matches nothing rather than everything",
           pools.match("") == [])
        ok("a reserved name is never offered",
           pools.match("bad") == [],
           "'#' is the attachment namespace, so a name carrying it can't be "
           "typed — it is reported where the pool is listed, not here")

        print("\n--- results come back in priority order ---")
        ok("System, then Persona, then Trait",
           [k for k, _ in pools.match("relax")]
           == ["prompt", "persona", "trait"], pools.match("relax"))
        ok("restricting to one pool searches only that pool",
           pools.match("relax", kinds=["trait"]) == [("trait", "relax")])

        print("\n--- the collision walk ---")
        empty = {"prompt": None, "persona": None, "trait": []}
        ok("nothing attached: the highest priority pool takes it",
           pools.fill(pools.match("relax"), empty) == ("prompt", "relax"))
        # The bug this pins: the session stores the *filename*, the pool
        # resolves the *stem*. Compared raw, the walk never advances and
        # /add relax fills the system prompt forever.
        carrying_prompt = {"prompt": "relax.md", "persona": None, "trait": []}
        ok("a pool already carrying the name is skipped",
           pools.fill(pools.match("relax"), carrying_prompt)
           == ("persona", "relax"),
           "compared filename against stem, this silently stayed on 'prompt'")
        two = {"prompt": "relax.md", "persona": "relax.md", "trait": []}
        ok("the walk continues to the third pool",
           pools.fill(pools.match("relax"), two) == ("trait", "relax"))
        all_three = {"prompt": "relax.md", "persona": "relax.md",
                     "trait": ["relax"]}
        ok("with every pool carrying it, the walk lands back at the top",
           pools.fill(pools.match("relax"), all_three) == ("prompt", "relax"),
           "an overwrite of the same thing, which is a no-op in effect")
        ok("an unrelated name attached doesn't block the walk",
           pools.fill(pools.match("relax"),
                      {"prompt": "cas.md", "persona": None, "trait": []})
           == ("prompt", "relax"))
        ok("no matches fills nothing", pools.fill([], empty) is None)

        print("\n--- stem: one place normalises the two spellings ---")
        ok("a filename becomes a name", pools.stem("relax.md") == "relax")
        ok("a name is left alone", pools.stem("relax") == "relax")
        ok("case-insensitive suffix", pools.stem("Relax.MD") == "Relax")
        ok("only the suffix goes", pools.stem("notes.md.md") == "notes.md")
        ok("None is empty, not a crash", pools.stem(None) == "")

        print("\n--- /remove searches what is attached, not what exists ---")
        active = {"prompt": "cas.md", "persona": None, "trait": ["terse"]}
        ok("attached layers flatten to stems in priority order",
           pools.active_layers(active) == [("prompt", "cas"),
                                           ("trait", "terse")],
           pools.active_layers(active))
        ok("a partial peels an attached layer",
           pools.match_active("ter", active) == [("trait", "terse")])
        ok("a real name that is NOT attached does not match",
           pools.match_active("relax", active) == [],
           "otherwise removing something you never added reads as success")
        ok("nothing attached matches nothing",
           pools.match_active("cas", {"prompt": None}) == [])

        print("\n--- resolve_layer: the shell ---")
        res, out = run(commands.resolve_layer, "relax", empty)
        ok("an unambiguous name needs no question",
           res == ("prompt", "relax") and "pick a number" not in out, out)
        res, out = run(commands.resolve_layer, "s", empty, answers=["2"])
        ok("several different names are listed and picked by number",
           res == ("persona", "muse"), (res, out))
        ok("the list names the pool of every candidate",
           "System prompt" in out and "Trait" in out, out)
        res, out = run(commands.resolve_layer, "s", empty, answers=[""])
        ok("Enter cancels the pick", res is None, out)
        res, out = run(commands.resolve_layer, "s", empty, answers=["9"])
        ok("out of range cancels rather than wrapping",
           res is None and "out of range" in out, out)
        res, out = run(commands.resolve_layer, "s", empty, answers=["two"])
        ok("a non-number cancels", res is None and "not a number" in out, out)
        res, out = run(commands.resolve_layer, "wombat", empty)
        ok("a failure names the forms and the pools it searched",
           res is None and "exact, prefix or substring" in out
           and "prompts" in out and "traits" in out, out)
        res, out = run(commands.resolve_layer, "relax", empty,
                       kinds=["trait"])
        ok("an explicit kind restricts the search",
           res == ("trait", "relax"), (res, out))

        print("\n--- resolve_attached: the shell ---")
        res, out = run(commands.resolve_attached, "ter", active)
        ok("a partial resolves an attached layer",
           res == ("trait", "terse"), (res, out))
        res, out = run(commands.resolve_attached, "relax", active)
        ok("naming something not attached fails and says what is",
           res is None and "carrying" in out and "cas" in out, out)
        res, out = run(commands.resolve_attached, "cas",
                       {"prompt": None, "persona": None, "trait": []})
        ok("with nothing attached it says exactly that",
           res is None and "nothing attached" in out, out)
        both = {"prompt": "relax.md", "persona": "relax.md", "trait": []}
        res, out = run(commands.resolve_attached, "relax", both)
        ok("one name in two pools peels the highest priority one",
           res == ("prompt", "relax") and "pick a number" not in out,
           (res, out))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
