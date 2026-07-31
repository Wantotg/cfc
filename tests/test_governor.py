#!/usr/bin/env python3
"""
test_governor.py — the active conversation governor. No API, no db, no
terminal: `governor.py` is a pure request compiler over bodies and counts its
caller already has, the same discipline `assemble.py` holds and for the same
reason — two turn paths (streaming, tools) must build byte-identical
envelopes, so nothing here may read config, a file or a clock on its own.

What is worth pinning:

  * the wrapper format has exactly one producer (`compile_messages`) — no
    cfc-side parser exists to drift from it.
  * the request order: prefix, First Message, durable history, at most one
    direction — and `split` is what keeps a tool loop's direction pinned at
    its original position across a growing `history`.
  * trait rotation is a pure function of a durable count, not of memory, so
    it recomputes the same answer across a reopen.
  * OOC and /continue suppress the automatic tone/trait sources entirely.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import governor

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def main():
    print("--- the wrapper: one producer, no parser ---")
    ok("wrap() puts the marker around the text",
       governor.wrap("do X") ==
       "[cfc direction]\ndo X\n[/cfc direction]",
       governor.wrap("do X"))

    print("\n--- compile_messages: the request order ---")
    prefix = [{"role": "system", "content": "SYS"}]
    history = [{"role": "user", "content": "hi"},
              {"role": "assistant", "content": "hello"}]
    msgs = governor.compile_messages(prefix, None, history, None)
    ok("no first message, no direction: prefix + history, unchanged",
       msgs == prefix + history, msgs)

    fm = {"name": "muse.md", "text": "Good morning.", "at": "2026-01-01"}
    msgs = governor.compile_messages(prefix, fm, history, None)
    ok("First Message lands as an assistant turn, right after the prefix",
       msgs == prefix + [{"role": "assistant", "content": "Good morning."}]
       + history, msgs)

    msgs = governor.compile_messages(prefix, None, history, "be gentler")
    ok("a direction is wrapped and lands after history, in a user slot",
       msgs == prefix + history +
       [{"role": "user", "content": governor.wrap("be gentler")}], msgs)
    ok("at most one direction message ever appears",
       sum(1 for m in msgs if m["content"].startswith(governor.DIRECTION_OPEN))
       == 1, msgs)

    msgs = governor.compile_messages(prefix, fm, history, "be gentler")
    ok("First Message, history, then direction — all four positions at once",
       msgs == prefix
       + [{"role": "assistant", "content": "Good morning."}]
       + history
       + [{"role": "user", "content": governor.wrap("be gentler")}], msgs)

    print("\n--- split: pinning a direction during a growing tool loop ---")
    # Simulates what agent_turn does: `history` grows call by call, but the
    # direction must stay at the position it had when the loop started —
    # never re-appended after a tool result, never drifting to the end.
    original = [{"role": "user", "content": "do the task"}]
    split = len(original)
    history = list(original)
    msgs1 = governor.compile_messages(prefix, None, history, "stay focused",
                                      split=split)
    ok("first call: direction right after the original history",
       msgs1 == prefix + original +
       [{"role": "user", "content": governor.wrap("stay focused")}], msgs1)

    # The loop appends its own assistant/tool messages onto `history`.
    history.append({"role": "assistant", "content": "",
                    "tool_calls": [{"id": "1"}]})
    history.append({"role": "tool", "tool_call_id": "1", "content": "ok"})
    msgs2 = governor.compile_messages(prefix, None, history, "stay focused",
                                      split=split)
    ok("direction stays pinned at the original split, not re-appended at "
       "the end",
       msgs2 == prefix + original
       + [{"role": "user", "content": governor.wrap("stay focused")}]
       + history[split:], msgs2)
    ok("...so it comes before the whole tool loop's own messages",
       msgs2.index({"role": "user",
                   "content": governor.wrap("stay focused")})
       < msgs2.index(history[split]), msgs2)
    ok("exactly one direction message survives a multi-call sequence",
       sum(1 for m in msgs2
          if m.get("content", "").startswith(governor.DIRECTION_OPEN)) == 1,
       msgs2)

    print("\n--- trait_refresh: a pure function of a durable count ---")
    ok("0 disables automatic refresh",
       governor.trait_refresh(["a", "b"], 6, interval=0) is None)
    ok("a negative interval disables it too",
       governor.trait_refresh(["a", "b"], 6, interval=-1) is None)
    ok("no traits, nothing to refresh",
       governor.trait_refresh([], 6, interval=6) is None)
    ok("not yet a cadence turn", governor.trait_refresh(["a"], 5, 6) is None)
    ok("turn 0 never refreshes (no turns yet)",
       governor.trait_refresh(["a"], 0, 6) is None)
    ok("the first cadence turn rotates to the first trait",
       governor.trait_refresh(["a", "b", "c"], 6, 6) == "a")
    ok("the second cadence turn rotates to the second trait",
       governor.trait_refresh(["a", "b", "c"], 12, 6) == "b")
    ok("the third cadence turn rotates to the third",
       governor.trait_refresh(["a", "b", "c"], 18, 6) == "c")
    ok("rotation wraps back to the first",
       governor.trait_refresh(["a", "b", "c"], 24, 6) == "a")
    ok("a positive custom interval is honoured",
       governor.trait_refresh(["a"], 3, interval=3) == "a")
    ok("...and off-cadence with that interval is None",
       governor.trait_refresh(["a"], 4, interval=3) is None)
    # Same durable count in, same answer out — a reopen just re-derives this
    # rather than needing anything remembered in the process.
    ok("recomputing from the same count is idempotent (survives a reopen)",
       governor.trait_refresh(["a", "b"], 12, 6)
       == governor.trait_refresh(["a", "b"], 12, 6) == "b")

    print("\n--- ordinary_instruction: tone always, trait on cadence only ---")
    instr, labels = governor.ordinary_instruction([], 1, {})
    ok("tone applies to every ordinary turn",
       governor.TONE_INSTRUCTION in instr, instr)
    ok("labels always carry at least tone check", labels == ["tone check"])

    instr, labels = governor.ordinary_instruction(["relax"], 6, {"relax": "Be calm."})
    ok("a cadence turn adds one trait reminder to the same instruction",
       governor.TONE_INSTRUCTION in instr and "Be calm." in instr, instr)
    ok("...and exactly one instruction string (never two directions)",
       isinstance(instr, str))
    ok("labels name both the tone check and the rotated trait",
       labels == ["tone check", "trait: relax"], labels)

    instr, labels = governor.ordinary_instruction(["relax"], 6, {"relax": None})
    ok("a trait whose body has gone missing contributes no text",
       "Be calm." not in instr and instr.strip() == governor.TONE_INSTRUCTION,
       instr)
    ok("...but is still named, and flagged missing",
       labels == ["tone check", "trait: relax (missing)"], labels)

    instr, labels = governor.ordinary_instruction(["relax"], 5, {"relax": "Be calm."})
    ok("off-cadence turns carry tone only, no trait at all",
       labels == ["tone check"], labels)

    print("\n--- /continue and OOC suppress the automatic sources ---")
    instr, labels = governor.continue_instruction()
    ok("/continue's instruction names nothing about tone or traits",
       "tone" not in instr.lower() and "trait" not in instr.lower(), instr)
    ok("its label is just 'continue'", labels == ["continue"])

    instr, labels = governor.ooc_instruction("be more playful")
    ok("OOC's instruction is the typed text, verbatim",
       instr == "be more playful")
    ok("its label is just 'ooc'", labels == ["ooc"])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
