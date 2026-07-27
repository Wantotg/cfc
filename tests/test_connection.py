#!/usr/bin/env python3
"""test_connection.py — the connection state machine and its one rendering.

Two things are worth pinning here and they are different in kind.

**The state function's branches**, driven by forcing each underlying answer.
`connection_state()` is the only thing that decides what state we are in, so a
test that drives it with a fake probe covers every consumer at once — which is
the point of there being one function.

**The producer/parser pair.** `preflight.py` writes state strings, `ui.py` maps
them to a colour, and the two modules cannot import each other (`ui.py` imports
no cfc module at all). That is the recurring hazard `HANDOVER.md` tabulates, so
it is pinned by round-trip rather than against literals: every state preflight
can return must have a rendering, and every rendering must correspond to a
state. A new state with no colour renders as a dim `?` at runtime rather than
crashing the hub — this test is what stops that reaching a release.

No network, no LM Studio, no API key.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import preflight
import ui


def check(label, got, want):
    assert got == want, f"{label}: got {got!r}, want {want!r}"
    print(f"  ok  {label}")


def with_fakes(probe_ok, running, local=True):
    """Run connection_state() with its three inputs forced.

    Patches the seam (`preflight.probe`, `preflight.app_running`) rather than
    the network or config, for the reason `test_routines` patches
    `routines.routine_dir`: patching config misses anything that read the value
    at import time.
    """
    orig = preflight.probe, preflight.app_running, preflight.is_local
    preflight.probe = lambda *a, **k: (probe_ok, "detail")
    preflight.app_running = lambda: running
    preflight.is_local = lambda base: local
    try:
        return preflight.connection_state()[0]
    finally:
        preflight.probe, preflight.app_running, preflight.is_local = orig


def test_states():
    print("connection_state covers every branch")
    check("embeddings answer -> connected",
          with_fakes(True, None), preflight.CONNECTED)
    check("down, app up -> no server",
          with_fakes(False, True), preflight.NO_SERVER)
    check("down, app down -> not running",
          with_fakes(False, False), preflight.NOT_RUNNING)
    # The one that matters most: we could not read the process list, so we do
    # not get to claim anything about the process. Reporting NO_SERVER here
    # would be a confident wrong answer about the thing the user is about to
    # act on, which is the failure this whole feature exists to remove.
    check("down, process state unknown -> down",
          with_fakes(False, None), preflight.DOWN)
    # A hosted endpoint must never produce a red light telling you to start an
    # application that has nothing to do with it.
    check("hosted and unreachable -> hosted",
          with_fakes(False, False, local=False), preflight.HOSTED)
    # ...and a working hosted endpoint is just connected.
    check("hosted and working -> connected",
          with_fakes(True, None, local=False), preflight.CONNECTED)


def test_rendering_round_trip():
    print("every state has exactly one rendering")
    states, styles = set(preflight.STATES), set(ui.CONNECTION_STYLE)
    check("no state is missing a colour", states - styles, set())
    check("no colour is orphaned", styles - states, set())
    for state in preflight.STATES:
        mark, style, text = ui.connection_light(state)
        assert mark and style and text, f"{state} renders empty"
        # The light exists to say what to do *next*, so every non-connected
        # state owes an action. A colour alone is a puzzle. `hosted` is the one
        # state whose next step is not a cfc command — nothing here can start
        # someone else's endpoint — so what it owes is saying that, and this
        # test insists on it rather than exempting the state and forgetting.
        if state == preflight.HOSTED:
            assert "not cfc's to start" in text, text
        elif state != preflight.CONNECTED:
            assert "/connect" in text, f"{state} does not name the fix: {text}"
    print(f"  ok  {len(preflight.STATES)} states render")
    # An unknown state degrades rather than raising. The hub is not worth
    # taking down over a light.
    mark, style, text = ui.connection_light("something new")
    check("unknown state degrades", (mark, style), ("?", "dim"))


def test_probe_timeouts_are_a_pair():
    print("connect and read stay two numbers")
    # Pinned as a pair, exactly as tests/test_embed.py pins embed.py's. The bug
    # is merging them into one `timeout=`, not the values: one number has to
    # serve the slower quantity, which is what made a dead port cost the full
    # read budget. Retuning stays free; merging fails here.
    assert preflight.PROBE_CONNECT < preflight.PROBE_READ, (
        "connect must be the shorter of the two — a local port answers at once "
        "or is not there, while a cold model load legitimately needs the read")
    assert preflight.PROBE_CONNECT <= 1.0, (
        "the hub asks this on every render; a slow connect timeout is a stall "
        "in front of the picker every time the embedder is down")
    check("both timeouts still exist",
          (hasattr(preflight, "PROBE_CONNECT"), hasattr(preflight, "PROBE_READ")),
          (True, True))


def test_terminal_report_direction():
    print("the terminal check fails in the safe direction")
    # Under a test there is no terminal, so there is no splash to band and the
    # honest answer is "nothing to report" rather than a warning nobody can act
    # on. A false positive here would fire on every non-interactive run and
    # teach the line to be ignored.
    ok, detail = preflight.terminal_report()
    check("no terminal -> no warning", ok, True)
    assert "COLORTERM" in detail and "rich=" in detail, detail
    print(f"  ok  reports what it measured: {detail}")


if __name__ == "__main__":
    test_states()
    test_rendering_round_trip()
    test_probe_timeouts_are_a_pair()
    test_terminal_report_direction()
    print("\nall connection tests passed")
