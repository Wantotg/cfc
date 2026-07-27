#!/usr/bin/env python3
"""test_empty_retry.py — one re-roll policy, reached from both turn paths.

Standing decision 7: the streaming path and the tool path must end a turn
identically. They drifted once — when tools became the default the spinner and
token bar silently vanished — and the tool path silently *not* offering the
`retry? (y/n)` the stream path offers was the same drift, caught small: an empty
tool turn painted a blank answer panel and moved on.

So the policy is one function and this pins two things about it:

  - it reaches the same decision for both callers, because it cannot tell them
    apart — a shared helper that branches on who called it is two helpers
    wearing one name;
  - the non-interactive branch retries a bounded number of times rather than
    asking, because asking a pipe means blocking on a keypress that never
    comes. That exact bug turned every piped hiccup into a lost turn.

No network, no API key.
"""
import builtins
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent
import commands


def check(label, got, want):
    assert got == want, f"{label}: got {got!r}, want {want!r}"
    print(f"  ok  {label}")


def decide(interactive, attempts, max_retries=2, typed=None):
    """Run the decision with stdout captured and `input()` scripted."""
    orig = builtins.input
    builtins.input = lambda *a: (_ for _ in ()).throw(EOFError()) if typed is None \
        else typed
    try:
        with redirect_stdout(io.StringIO()):
            return commands.empty_completion_decision(
                interactive, attempts, max_retries)
    finally:
        builtins.input = orig


def test_interactive_asks():
    print("with a human, it asks and obeys")
    check("y retries", decide(True, 0, typed="y"), (True, 0))
    check("n does not", decide(True, 0, typed="n"), (False, 0))
    check("anything else is not a yes", decide(True, 0, typed="maybe"),
          (False, 0))
    # The bug this replaced: the old code asked unconditionally, and a pipe
    # answered EOFError, which was read as "no". Here EOF still means no — but
    # only because a human was claimed to be present, which is the caller's
    # error, not this function's.
    check("EOF is a no", decide(True, 0, typed=None), (False, 0))


def test_piped_retries_without_asking():
    print("with no human, it retries a bounded number of times")
    # Never calls input(): `typed=None` makes input() raise EOFError, so if
    # this branch ever asked, these would come back (False, …) instead.
    check("first empty retries", decide(False, 0), (True, 1))
    check("second empty retries", decide(False, 1), (True, 2))
    check("past the budget it gives up", decide(False, 2), (False, 3))


def test_policy_is_caller_blind():
    print("the two paths cannot get different answers")
    # The strongest form of decision 7 available to a test: the function takes
    # no argument identifying its caller, so the tool path and the stream path
    # are provably asking the same question. If someone adds a `path=` or a
    # `use_tools=` parameter to "just handle one case", this fails.
    import inspect
    params = list(inspect.signature(
        commands.empty_completion_decision).parameters)
    check("signature carries no caller identity",
          params, ["interactive", "attempts", "max_retries"])


def test_both_empty_exits_announce():
    print("both of the tool path's empty exits say so")
    # The 200-with-empty-content used to return silently while the 400 said
    # "provider hiccup", so one event looked like two bugs depending on the
    # door it came through. Both now go through _say_empty.
    buf = io.StringIO()
    with redirect_stdout(buf):
        agent._say_empty()
    said = buf.getvalue()
    assert "no answer" in said, said
    print(f"  ok  announces: {said.strip()[:60]}")


if __name__ == "__main__":
    test_interactive_asks()
    test_piped_retries_without_asking()
    test_policy_is_caller_blind()
    test_both_empty_exits_announce()
    print("\nall empty-retry tests passed")
