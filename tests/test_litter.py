#!/usr/bin/env python3
"""
test_litter.py — backfill.is_litter's coupling to the marker formats.

    python3 tests/test_litter.py

is_litter() decides which chunks get no embedding. Its regex hard-codes the
marker strings written by commands.py (:remember) and import_anthropic.py
(tool_use). Those have drifted before: the chat.py split moved the :remember
marker and the "change this too" comment had to be chased by hand — exactly the
failure it warned about (see development/BACKLOG.md).

This makes the coupling self-enforcing. A marker built the way the source
builds it must still be recognised as litter, so a format change over there
fails here instead of silently re-embedding markers into the search space.

Mirrors test_schema.py's approach for the db.py side of the same markers:
rebuild the marker + assert the consumer recognises it + an inspect guard that
the source still writes it that way.
"""
import inspect
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import commands
import import_anthropic
from backfill import is_litter, MIN_TOKENS

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {detail}")


# Built exactly as the source builds them. If you change a format in
# commands.py or import_anthropic.py, change it here too — the assertions below
# then confirm backfill.py's regex was changed to match.
def remember_marker(query, n):
    return f'[:remember "{query}" → {n} excerpts injected (ephemeral)]'


def tool_use_marker(name):
    return f"[tool_use: {name}]"


def main():
    print("--- markers the source writes are litter ---")
    rm = remember_marker("what did we decide about chunking", 8)
    ok("/remember marker is litter", is_litter(rm), rm)

    tu = tool_use_marker("read_file")
    ok("tool_use marker is litter", is_litter(tu), tu)

    ok("[tool_result] is litter", is_litter("[tool_result]"))

    print("\n--- concatenated markers are litter (the bug that shipped) ---")
    # Consecutive tool calls chunk together, so a chunk is often several markers
    # and nothing else. The old regex matched one marker against the whole
    # string and let every one of those through.
    concat = "\n".join([tool_use_marker("list_dir"),
                        tool_use_marker("read_file"),
                        tool_use_marker("grep")])
    ok("several tool_use markers, one chunk", is_litter(concat), concat)

    mixed = "\n".join([tool_use_marker("read_file"),
                       remember_marker("x", 2)])
    ok("mixed markers, one chunk", is_litter(mixed), mixed)

    print("\n--- real content is NOT litter ---")
    # The floor is 5 tokens; a real 8-token question must survive it.
    real = "Help me set up MCP for LocalAI"
    ok("short real content survives", not is_litter(real, token_est=8), real)
    ok("a near-marker line is not litter",
       not is_litter("[:remember but not really a marker]", token_est=10))
    ok(f"below {MIN_TOKENS} tokens is litter",
       is_litter("Yes!", token_est=2))

    print("\n--- the source still builds markers the tested way ---")
    # A weak guard: if these literals leave the source, the builders above have
    # gone stale even while they still pass. Same check test_schema.py runs.
    rsrc = inspect.getsource(commands.do_remember)
    ok("commands.py still builds the :remember marker",
       "[:remember" in rsrc and "(ephemeral)]" in rsrc,
       "do_remember no longer contains a recognisable marker literal")
    isrc = inspect.getsource(import_anthropic)
    ok("import_anthropic.py still builds the tool_use marker",
       "[tool_use:" in isrc,
       "import_anthropic no longer writes a recognisable tool_use marker")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
