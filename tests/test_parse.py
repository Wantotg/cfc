#!/usr/bin/env python3
"""
test_parse.py — the command grammar. No API calls, no database, no terminal.

    python3 tests/test_parse.py

`parse.py` is the one place that decides what a typed line means, and it
replaced a chain of `user.startswith(":foo")` tests whose correctness depended
on the *order* the tests were written in. The assertions worth reading here are
the ones about that: a verb that is a prefix of another verb no longer needs a
comment explaining which one has to be checked first, because exact matching
cannot have the bug at all.

The rest is the free-text tail — the one part of the grammar that cannot be
recovered by splitting and rejoining, because a commit message and a session
title are allowed to contain runs of spaces.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from parse import (parse, Cmd, PREFIX, LEGACY_PREFIX, ALIASES,
                   RETIRED, VERBS, RESERVED)

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def p(line):
    """Parse a line written with whatever prefix is current, so these tests
    survive the flip without a rewrite."""
    return parse(line.replace("/", PREFIX, 1) if line.startswith("/") else line)


def main():
    print("--- what is and isn't a command ---")
    ok("prose is not a command", p("hello there") is None)
    ok("a bare prefix is not a command", p("/") is None,
       "':' alone is a typo, not a verb named ''")
    ok("prefix plus spaces is not a command", p("/   ") is None)
    ok("empty input is not a command", parse("") is None)
    ok("None is not a command", parse(None) is None)
    ok("a mid-line prefix is not a command", p("see the :help output") is None,
       "only a leading prefix addresses cfc")

    print("\n--- the trap that made this module exist ---")
    # ":attached".startswith(":attach") is true, so the old chain had to test
    # :attached first and said so in a comment. Nothing declares that order;
    # it comes back every time a command is added whose name prefixes another.
    ok("':attached' is its own verb, not an attach of 'ed'",
       p("/attached").verb == "attached")
    ok("':attach' is unaffected", p("/attach ~/notes.md").verb == "attach")
    ok("':helper' does not run help",
       p("/helper").verb == "helper",
       "the old chain needed a trailing space in the test to avoid an "
       "IndexError that took the app down")
    # This was ':routines' until 0.8.2, when 'routines' became a deliberate
    # alias for 'routine' (see the alias section below). The trap this line
    # guards is a *word that happens to start with a verb* being swallowed by
    # it; an alias is the opposite — an intended mapping, declared in one
    # place. Moved to a word that must never become an alias so the guard keeps
    # meaning what it says.
    ok("':tagfoo' is not ':tag'", p("/tagfoo").verb == "tagfoo")
    ok("':dbfoo' is not ':db'", p("/dbfoo").verb == "dbfoo")

    print("\n--- verbs, case and aliases ---")
    ok("the verb is lowercased", p("/HELP").verb == "help")
    ok("'h' aliases help", p("/h").verb == "help")
    ok("'?' aliases help", p("/?").verb == "help")
    ok("'db' aliases database", p("/db off").verb == "database")
    ok("'routines' aliases routine", p("/routines").verb == "routine",
       "an unrecognised verb falls through to the model, so the plural cost "
       "an API call and a confused answer rather than an error")
    ok("an alias keeps its arguments", p("/db off").raw == "off")
    ok("every alias target is a plain word",
       all(v.isalpha() for v in ALIASES.values()), ALIASES)

    print("\n--- arguments ---")
    c = p("/wiki commit journal file a message")
    ok("args are the tokens after the verb",
       c.args == ("commit", "journal", "file", "a", "message"), c.args)
    ok("arg(i) reads a token", c.arg(1) == "journal")
    ok("arg past the end is empty, not an error", c.arg(99) == "")
    ok("arg past the end takes a default", c.arg(99, "wiki") == "wiki")
    ok("no arguments is an empty tuple", p("/help").args == ())
    ok("raw is empty when nothing follows", p("/help").raw == "")

    print("\n--- the greedy tail ---")
    ok("tail(0) is the whole remainder",
       p("/title 5 Some Name").tail(0) == "5 Some Name")
    ok("tail(1) drops one token",
       p("/title 5 Some Name").tail(1) == "Some Name")
    ok("tail past the end is empty", p("/title 5").tail(1) == "")
    # This is the reason tail() re-splits the raw string instead of joining
    # args: a title or a commit message is free text and owns its own spacing.
    ok("tail preserves internal spacing",
       p("/title 5 two  spaces").tail(1) == "two  spaces",
       p("/title 5 two  spaces").tail(1))
    ok("trailing whitespace is stripped once, at the edge",
       p("/grep vector  ").raw == "vector")

    print("\n--- integer arguments ---")
    ok("a number reads as one", p("/delete chat 5").int_arg(1) == 5)
    ok("a non-number returns the default, it does not raise",
       p("/title abc").int_arg(0) is None,
       "a bare int() here used to take the whole REPL down on a typo")
    ok("a missing token returns the default",
       p("/title").int_arg(0, -1) == -1)
    ok("a negative number still parses", p("/delete -1").int_arg(0) == -1)

    print("\n--- the prefix is one constant ---")
    ok("parse takes the prefix as a parameter",
       parse("!add relax", prefix="!") is not None
       and parse("!add relax", prefix="!").verb == "add",
       "the v0.8 flip is this constant, not thirty-five edits")
    ok("a prefix that isn't current doesn't parse",
       parse("%add relax", prefix="!", legacy=None) is None)

    print("\n--- the retired prefix, for one version ---")
    ok("the old prefix still runs the command",
       parse(f"{LEGACY_PREFIX}add relax").verb == "add",
       "a migration that breaks what it migrates teaches only that the "
       "upgrade was a mistake")
    ok("...and is flagged as legacy so the REPL can say so",
       parse(f"{LEGACY_PREFIX}add relax").legacy is True)
    ok("the current prefix is not flagged",
       parse(f"{PREFIX}add relax").legacy is False)
    ok("the legacy prefix can be switched off in one place",
       parse(f"{LEGACY_PREFIX}add relax", legacy=None) is None,
       "removing it next minor is deleting a constant")
    ok("the two prefixes are different characters",
       PREFIX != LEGACY_PREFIX, (PREFIX, LEGACY_PREFIX))
    ok("Cmd is immutable", isinstance(p("/help"), Cmd)
       and _frozen(p("/help")),
       "handlers receive the parse, they don't edit it")

    print("\n--- the surface: three lists that have to agree ---")
    ok("twenty-two verbs", len(VERBS) == 22, len(VERBS))
    ok("no verb is listed twice", len(set(VERBS)) == len(VERBS))
    ok("every retired verb points at a live one",
       all(r.split()[0] in VERBS for r in RETIRED.values()),
       [r for r in RETIRED.values() if r.split()[0] not in VERBS])
    ok("no retired verb is also a live one",
       not (set(RETIRED) & set(VERBS)), set(RETIRED) & set(VERBS))
    ok("no alias collides with a live verb",
       not (set(ALIASES) & set(VERBS)), set(ALIASES) & set(VERBS))
    ok("every alias resolves to a live verb",
       all(v in VERBS for v in ALIASES.values()), ALIASES)
    ok("nothing reserved is spent",
       not (set(RESERVED) & set(VERBS)), set(RESERVED) & set(VERBS))
    # main.py asserts its handler table equals VERBS at session start; this is
    # the same guarantee from the other side, without needing a session.
    ok("a retired verb still parses, so the REPL can correct it",
       parse(f"{PREFIX}prompts").verb == "prompts",
       "otherwise it falls through and is sent to the model as a message")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


def _frozen(cmd):
    try:
        cmd.verb = "nope"
    except Exception:
        return True
    return False


if __name__ == "__main__":
    sys.exit(main())
