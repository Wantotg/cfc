#!/usr/bin/env python3
"""test_ui.py — the shared console prints chat content literally. No network.

    python3 tests/test_ui.py

`B-06`: `ui.console` was built `Console(markup=False)` so a model's own
`[dim]...[/dim]`-shaped text could never be reinterpreted as markup — but
rich's emoji substitution (`:key:` -> the glyph) is a separate switch,
`emoji=True` by default, and it was still live. Two settings implement one
decision ("chat content is never reinterpreted"); this pins both halves
through the one console everything prints through, so a future rich upgrade
that flips a default back can't silently reopen either half.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.dont_write_bytecode = True

import ast
import contextlib
import io
import re

from ui import console, DISPLAY_NAME

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def rendered(text):
    buf = io.StringIO()
    saved = console._file
    console.file = buf
    try:
        console.print(text)
    finally:
        console.file = saved
    return buf.getvalue()


# --- W-0.9.1-03: every human-facing "cfc" routes through DISPLAY_NAME -----
#
# Derived from source rather than trusted, same discipline as
# `test_system_injections.py`: this walks every top-level module's AST for a
# literal, bare "cfc" and fails in both directions — a new one that slipped
# past the sweep, or an allowlist entry that no longer matches anything.
#
# "Bare" excludes two technical shapes that are not the program's name in
# prose and are explicitly out of scope (`Work Order.md` step 4): a
# hidden-directory path fragment (`~/.cfc/...`) and a bracket-wrapped wire
# marker (`[cfc direction]`, `[/cfc direction]`, the tool-loop budget notes
# `[cfc: ...]` / `[cfc] ...`). Both are stripped before the bare-word check
# runs, so a genuinely new bare "cfc" on the same line can't hide behind one.
#
# Docstrings are excluded structurally — they are never printed to anyone,
# and the AST already keeps ordinary `#` comments out of this entirely.
ROOT = Path(__file__).resolve().parent.parent

# preflight.py and errorlog.py keep their own local "cfc" literals — see
# `ui.DISPLAY_NAME`'s own docstring for why. config.py is gitignored and
# machine-specific; config.example.py is a template of settings, not code
# that prints — same exclusions `test_system_injections.py` makes.
_SKIP_MODULES = {"preflight", "errorlog", "config", "config.example"}

_TECHNICAL_RE = re.compile(r"~?/?\.cfc\b|\[/?cfc\b[^\]]*\]")
_BARE_CFC_RE = re.compile(r"\bcfc\b")

# The two deliberate exceptions this sweep's own scope would otherwise flag.
# Both named by (module, lineno-bearing snippet) rather than just module, so
# a *new*, different "cfc" landing anywhere else in the same file still
# fails loudly instead of hiding behind a whole-file exemption.
_ALLOWLIST = {
    # context.py: "the cfc source tree" — a path/identifier reference (the
    # git checkout directory), not the program's name in conversational
    # prose. Pinned verbatim by three tests/test_routines.py assertions.
    ("context", "overlaps the cfc source tree"),
    # runner.py: SYSTEM is a routine's system prompt — model input, out of
    # scope by the work order's own words ("Do not change ... model input").
    ("runner", "unattended cfc routine"),
    # governor.py: TONE_INSTRUCTION is the compiled [cfc direction] sent to
    # the model (B-1.6.3-01a) — never rendered to the human, who sees only
    # the dim "Cooking for Cats -> tone check" label main.py prints
    # alongside it. Same exception as runner.py's SYSTEM, one line up.
    ("governor", "cfc control text"),
    # search_worker.py: the HTTP User-Agent search_worker.py sends to
    # DuckDuckGo (Concept.md's own "the honest user-agent
    # `cfc-web-search/1.8`") — a wire-level identifier a third party reads,
    # not prose shown to Cas. Same shape as context.py's "the cfc source
    # tree": an identifier, not the program's name in conversation.
    ("search_worker", "cfc-web-search/1.8"),
}


def _literal_text(node):
    """The literal (non-interpolated) text of a str Constant or an f-string
    JoinedStr — what a reader actually sees, ignoring `{expr}` slots."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values
                       if isinstance(v, ast.Constant) and isinstance(v.value, str))
    return ""


def _has_bare_cfc(text):
    return bool(_BARE_CFC_RE.search(_TECHNICAL_RE.sub("", text)))


def _docstring_ids(tree):
    """id() of every Constant node that IS a docstring — the first statement
    of the module or of a function/class body."""
    out = set()
    holders = [tree] + [n for n in ast.walk(tree)
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                          ast.ClassDef))]
    for h in holders:
        body = getattr(h, "body", [])
        if body and isinstance(body[0], ast.Expr):
            v = body[0].value
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.add(id(v))
    return out


def _joinedstr_child_ids(tree):
    """id() of every Constant that is a *part* of an f-string — visited
    through its parent JoinedStr instead, which is the only node whose
    literal text is the whole, correctly-concatenated string. Without this,
    an f-string split across `{...}` slots is checked one fragment at a
    time, and a closing `]` two fragments away from the opening `[cfc` never
    gets to strip it — a false positive on exactly the budget-note shape
    this sweep must not flag."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for v in node.values:
                out.add(id(v))
    return out


def _bare_cfc_hits():
    """[(module, lineno, text)] for every literal string this sweep can see
    — a print()/console.print() call or any other string constant, module-
    wide — whose text has a bare "cfc" nobody routed through DISPLAY_NAME."""
    hits = []
    for path in sorted(ROOT.glob("*.py")):
        modname = path.stem
        if modname in _SKIP_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        skip_ids = _docstring_ids(tree) | _joinedstr_child_ids(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Constant, ast.JoinedStr)):
                continue
            if id(node) in skip_ids:
                continue
            if isinstance(node, ast.Constant) and not isinstance(node.value, str):
                continue
            text = _literal_text(node)
            if text and _has_bare_cfc(text):
                hits.append((modname, node.lineno, text))
    return hits


def test_display_name_sweep():
    print("\n--- W-0.9.1-03: no bare 'cfc' outside the technical allowlist ---")
    hits = _bare_cfc_hits()
    matched_allowlist = set()
    unexpected = []
    for modname, lineno, text in hits:
        found = next((entry for entry in _ALLOWLIST
                     if entry[0] == modname and entry[1] in text), None)
        if found:
            matched_allowlist.add(found)
        else:
            unexpected.append((modname, lineno, text))
    ok("every bare 'cfc' left in source is an allowlisted, reasoned exception",
       not unexpected, unexpected)
    ok("...and every allowlist entry still matches something real — a stale "
       "entry means the exception it justified is gone too",
       matched_allowlist == _ALLOWLIST, _ALLOWLIST - matched_allowlist)

    print("\n--- the shared name itself ---")
    ok("ui.DISPLAY_NAME is the one source of the name",
       DISPLAY_NAME == "Cooking for Cats", DISPLAY_NAME)

    print("\n--- spot checks: the producers this pass actually rewrote ---")
    import commands
    import hub
    import schedule
    import screens

    quit_help = next(what for keys, _, what in hub.HUB_KEYS if keys[0] == "q")
    ok("the hub's quit line uses the shared name",
       quit_help == f"leave {DISPLAY_NAME}", quit_help)

    private_help = next(what for keys, _, what in hub.HUB_KEYS
                        if keys[0] == "p")
    ok("the hub's private-chat line makes the compact claim (W-0.9.1-04)",
       private_help == "start a private chat — temporary, not saved locally",
       private_help)

    ok("the routines/config/wiki screen titles use the shared name",
       all(DISPLAY_NAME in screens._title(m)
           for m in ("config", "wiki", "routine")), screens._title("config"))

    ok("the wiki commit notice uses the shared name",
       commands._LOCAL_ONLY == f"  committed locally — {DISPLAY_NAME} "
       "does not push", commands._LOCAL_ONLY)

    ok("the headless USAGE banner uses the shared name",
       schedule.USAGE.startswith(DISPLAY_NAME), schedule.USAGE[:40])


def test_capture_restore_preserves_nested_capture():
    """D-19: a capture that finishes by restoring the *file it found* keeps a
    surrounding capture intact; one that finishes with `console.file =
    sys.stdout` does not, because the outer capture's real destination was
    never `sys.stdout` in the first place — it was set directly on
    `console.file`, the same way every one of the repaired twelve test files
    captures output. `sys.stdout` itself is untouched by that, so restoring
    it silently redirects the console back to the real terminal, and the
    outer capture's own buffer stops receiving anything from that point on —
    invisible in a one-file run because the process exits before anyone
    reads the buffer again, live within a shared process because a later,
    unrelated capture is what actually notices the missing line.

    Read `console._file`, never `console.file`: the property getter falls
    back to the live `sys.stdout` when the console holds nothing of its own,
    so a save through it can never see "unset" and restoring it pins the
    console — which is the leak itself, wearing the fix's clothes. See
    `test_capture_restore_leaves_an_unset_console_unset` below."""
    print("\n--- D-19: restore the file found, not sys.stdout ---")
    saved = console._file
    try:
        outer = io.StringIO()
        console.file = outer
        console.print("outer before")

        # The now-repaired idiom: save what's there, restore that exact object.
        inner = io.StringIO()
        inner_saved = console._file
        console.file = inner
        console.print("inner line")
        console.file = inner_saved

        console.print("outer after")
        ok("restoring the saved file keeps the outer capture intact",
           "outer before" in outer.getvalue() and "outer after" in outer.getvalue(),
           outer.getvalue())
        ok("...and the inner capture still got its own line",
           "inner line" in inner.getvalue(), inner.getvalue())
    finally:
        console.file = saved

    saved = console._file
    try:
        outer = io.StringIO()
        console.file = outer
        console.print("outer before")

        # The bug this row repairs: restoring to sys.stdout instead of the
        # saved object.
        inner = io.StringIO()
        console.file = inner
        console.print("inner line")
        console.file = sys.stdout

        console.print("outer after")
        ok("disabling the fix reproduces the leak: the outer capture loses "
           "everything printed after the inner one restores to sys.stdout",
           "outer after" not in outer.getvalue(), outer.getvalue())
    finally:
        console.file = saved

    print("\n--- ...and a later, unrelated capture receives a real line ---")
    later = io.StringIO()
    console.file = later
    try:
        console.print("a later capture")
    finally:
        console.file = saved
    ok("a fresh capture after the above still receives real Rich output",
       "a later capture" in later.getvalue(), later.getvalue())


def test_capture_restore_leaves_an_unset_console_unset():
    """D-19, the ordinary case: the console usually holds no file of its own
    and resolves `sys.stdout` at print time, which is what makes a plain
    `redirect_stdout` capture Rich output at all. A capture must hand it back
    in that state.

    `console.file` cannot tell you it is in that state — the getter answers
    with the live `sys.stdout` — so a save-and-restore written through the
    property pins the console to a real terminal handle, and every later
    `redirect_stdout` in the process reads empty while the output goes to the
    screen. That is the same leak D-19 set out to close, which is why every
    capture helper in `tests/` saves `console._file`.
    """
    print("\n--- D-19: an unset console is handed back unset ---")
    saved = console._file
    try:
        console.file = None
        ok("the getter never reports the unset state",
           console._file is None and console.file is sys.stdout)

        out = io.StringIO()
        found = console._file
        try:
            with contextlib.redirect_stdout(out):
                console.file = out
                console.print("captured line")
        finally:
            console.file = found
        ok("the capture itself received its line",
           "captured line" in out.getvalue(), out.getvalue())
        ok("the console is unset again, not pinned to a terminal handle",
           console._file is None, console._file)

        later = io.StringIO()
        with contextlib.redirect_stdout(later):
            console.print("later line")
        ok("so a later plain redirect_stdout still receives Rich output",
           "later line" in later.getvalue(), later.getvalue())
    finally:
        console.file = saved


def main_():
    print("\n--- rich shortcodes survive literally ---")
    out = rendered("run :new:")
    ok("':new:' is not substituted for its emoji", "🆕" not in out, out)
    ok("...and the shortcode text is still there", ":new:" in out, out)

    out = rendered(":key: :lock: :books: :100:")
    ok("none of a run of known shortcodes are substituted",
       not any(g in out for g in ("🔑", "🔒", "📚", "💯")), out)
    ok("...and all four shortcodes survive verbatim",
       all(s in out for s in (":key:", ":lock:", ":books:", ":100:")), out)

    print("\n--- a code-shaped string keeps its shortcodes too ---")
    code = "```\nconfig:\n  icon: :key:\n```"
    out = rendered(code)
    ok("a shortcode inside a fenced code block is not substituted",
       "🔑" not in out, out)
    ok("...and prints verbatim", ":key:" in out, out)

    print("\n--- markup still prints literally (the existing guarantee) ---")
    out = rendered("[dim]recall cancelled.[/dim]")
    ok("a bracketed style tag is not consumed as markup",
       "[dim]recall cancelled.[/dim]" in out, out)

    test_display_name_sweep()
    test_capture_restore_preserves_nested_capture()
    test_capture_restore_leaves_an_unset_console_unset()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
