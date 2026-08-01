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
import contextlib
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import commands
import hub
import preflight
import screens
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
        # state owes an action. A colour alone is a puzzle. Every one of them
        # — `hosted` included, since `W-0.9.1-05` — now names `/connect
        # embedding` as a *retry*, driven cold from a machine that never
        # installed LM Studio at all: checking your own half (connectivity,
        # `EMBED_BASE`/`EMBED_KEY`, the provider's status) and then re-asking
        # the same probe is a real next step even though cfc has nothing
        # local to start.
        if state != preflight.CONNECTED:
            assert "/connect" in text, f"{state} does not name the fix: {text}"
            # ...**and says where it can be typed** (`B-0.9.1-03`). Two of the
            # three renderings are at the hub, which accepts n/p/h/q and a chat
            # id and refuses everything else — so an unqualified `/connect
            # embedding` is advice the screen printing it would not take. Not
            # pinned against the exact phrase: any wording that names a chat
            # passes, because the finding is the missing context and not the
            # three words that supply it.
            assert "chat" in text, (
                f"{state} names a command with no place to type it: {text}")
            # ...and, since v1.2.1 (`B-04`), the config screen's own location
            # too — `_render_config` renders this same text and refuses the
            # chat form outright (decision 17: command screens are not chat
            # loops). Both markers, not just "connect embedding" bare, because
            # that phrase is already a substring of "/connect embedding" and
            # would pass even with the config location missing entirely.
            assert "in a chat" in text and "in config" in text, (
                f"{state} does not name both locations: {text}")
        # `hosted` is still the one state that owes no *local* fix — it must
        # never suggest starting a service cfc has no business starting.
        if state == preflight.HOSTED:
            assert "LM Studio" not in text, text
            assert "EMBED_BASE" in text or "EMBED_KEY" in text, text
    print(f"  ok  {len(preflight.STATES)} states render")
    # An unknown state degrades rather than raising. The hub is not worth
    # taking down over a light.
    mark, style, text = ui.connection_light("something new")
    check("unknown state degrades", (mark, style), ("?", "dim"))


def test_colour_follows_what_cfc_can_do():
    """The dot carries recoverability, not severity (`D-0.9.1-01`).

    Severity cannot discriminate here — every non-green state means memory is
    off, equally — so the colour says whether `preflight.ensure` actually
    *attempts* a local fix for this state (starting LM Studio, loading the
    model) versus only advising and returning early. `hosted` names
    `/connect embedding` too now (`W-0.9.1-05`, a retry, not a fix), which
    retires the old text-based split — "does the advice mention /connect" no
    longer distinguishes the two groups, so this drives the real thing that
    does: whether `find_lms()` gets called at all. Verified by disabling it
    (HANDOVER's "verify a guard by disabling it") and watching which states
    reach for it.
    """
    print("the colour says what cfc can do about it")
    fixable, unfixable = set(), set()
    fixable_states, unfixable_states = set(), set()
    orig_find_lms, orig_state = preflight.find_lms, preflight.connection_state
    tried = []
    preflight.find_lms = lambda: (tried.append(1) or None)
    try:
        for state in preflight.STATES:
            if state == preflight.CONNECTED:
                continue
            tried.clear()
            preflight.connection_state = lambda s=state: (s, "test detail")
            preflight.ensure(say=lambda level, msg: None)
            _, style, _ = ui.connection_light(state)
            if tried:
                fixable.add(style)
                fixable_states.add(state)
            else:
                unfixable.add(style)
                unfixable_states.add(state)
    finally:
        preflight.find_lms = orig_find_lms
        preflight.connection_state = orig_state
    check("every state cfc actively tries shares one colour", len(fixable), 1)
    check("the state it only advises on shares none of that colour",
          fixable & unfixable, set())
    check("hosted is the one that never reaches the local fixer",
          preflight.HOSTED in unfixable_states, True)
    # Green is working, and it is nobody else's colour. Without this the rule
    # above is satisfied by painting the whole light one colour.
    green = ui.connection_light(preflight.CONNECTED)[1]
    check("connected keeps a colour of its own",
          green not in fixable | unfixable, True)


def _rendered(fn, *a, **kw):
    """Capture what `fn` prints through the shared `ui.console`, whichever
    module it was imported into — hub, screens and commands all hold the
    same object (`from ui import console`), so redirecting the one on `ui`
    covers every caller."""
    buf = io.StringIO()
    saved = ui.console.file
    ui.console.file = buf
    try:
        with contextlib.redirect_stdout(buf):
            fn(*a, **kw)
    finally:
        ui.console.file = saved
    return buf.getvalue()


def test_advice_renders_identically_on_all_three_screens():
    """`B-04`: the hub, the config screen and chat's `/connect` all render
    `ui.CONNECTION_STYLE` verbatim — driven here rather than inferred from
    the table, so a screen that started building its own copy (the failure
    `B-04` names as the second obvious repair) would show up as a mismatch
    here even though the shared table stayed correct.
    """
    print("the hub, config screen and chat show the same advice")
    # `hosted` is in this same loop now (`W-0.9.1-05`) — its advice is
    # actionable like the other three, so there is no separate "offers
    # nothing" case left to test differently; only the wording differs, and
    # that is `test_rendering_round_trip`'s job.
    for state in (preflight.NO_SERVER, preflight.NOT_RUNNING, preflight.DOWN,
                 preflight.HOSTED):
        orig_state = preflight.connection_state
        preflight.connection_state = lambda s=state: (s, "test detail")
        try:
            hub_out = _rendered(hub.print_connection, state=state)
            config_out = _rendered(screens._render_config)
            chat_out = _rendered(commands.connect_status)
        finally:
            preflight.connection_state = orig_state

        _, _, text = ui.connection_light(state)
        # Rich wraps long lines to the console width, so the raw phrase can
        # land split across a newline in the captured output — collapse
        # whitespace on both sides rather than pin an exact substring match.
        flat_text = " ".join(text.split())
        for label, out in (("hub", hub_out), ("config screen", config_out),
                          ("chat", chat_out)):
            flat_out = " ".join(out.split())
            assert flat_text in flat_out, (
                f"{label} did not render the shared text for {state}: {out!r}")
        check(f"{state}: identical wording on all three screens", True, True)


def test_connect_embedding_hosted_fallback():
    """`commands.connect_embedding()`'s own fallback line — `not preflight.
    find_lms()` used to fire regardless of state, so a machine using a
    hosted embedder (and therefore never installing LM Studio, so `find_lms`
    is also None there) got told to "start LM Studio yourself" for a
    connection that was never local at all (`W-0.9.1-05`). It must fire for
    an ordinary local failure and stay silent for `hosted`, whose own
    `ensure()` message already carried the real next step.
    """
    print("connect_embedding's fallback line only fires for a local failure")
    orig_ensure, orig_find_lms, orig_state = (
        preflight.ensure, preflight.find_lms, preflight.connection_state)
    preflight.ensure = lambda say: (say("fail", "embedder not answering"),
                                    False)[1]
    preflight.find_lms = lambda: None
    try:
        preflight.connection_state = lambda: (preflight.DOWN, "test detail")
        local_out = _rendered(commands.connect_embedding)
        check("a local failure still gets the LM Studio fallback",
              "start LM Studio yourself" in local_out, True)

        preflight.connection_state = lambda: (preflight.HOSTED, "test detail")
        hosted_out = _rendered(commands.connect_embedding)
        check("hosted gets no such fallback",
              "start LM Studio yourself" not in hosted_out, True)
    finally:
        preflight.ensure = orig_ensure
        preflight.find_lms = orig_find_lms
        preflight.connection_state = orig_state


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
    test_colour_follows_what_cfc_can_do()
    test_advice_renders_identically_on_all_three_screens()
    test_connect_embedding_hosted_fallback()
    test_probe_timeouts_are_a_pair()
    test_terminal_report_direction()
    print("\nall connection tests passed")
