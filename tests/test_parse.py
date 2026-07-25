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

from parse import parse, Cmd, PREFIX, ALIASES

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
    ok("':routines' does not run the routine dispatcher",
       p("/routines").verb == "routines",
       "the old chain needed a trailing space in the test to avoid an "
       "IndexError that took the app down")
    ok("':tagfoo' is not ':tag'", p("/tagfoo").verb == "tagfoo")
    ok("':dbfoo' is not ':db'", p("/dbfoo").verb == "dbfoo")

    print("\n--- verbs, case and aliases ---")
    ok("the verb is lowercased", p("/HELP").verb == "help")
    ok("'h' aliases help", p("/h").verb == "help")
    ok("'?' aliases help", p("/?").verb == "help")
    ok("'db' aliases database", p("/db off").verb == "database")
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
       parse("/add relax", prefix="/") is not None
       and parse("/add relax", prefix="/").verb == "add",
       "the v0.8 flip is this constant, not thirty-five edits")
    ok("the other prefix stops parsing when it isn't current",
       parse(":add relax", prefix="/") is None)
    ok("Cmd is immutable", isinstance(p("/help"), Cmd)
       and _frozen(p("/help")),
       "handlers receive the parse, they don't edit it")

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
