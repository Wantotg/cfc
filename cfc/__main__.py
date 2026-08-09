"""python -m cfc — the 2.0 parallel entry point.

Checks the interpreter before importing anything else in this package (see
`entry.py`), so an unsupported Python gets one clear line instead of a
`SyntaxError` partway through an import. Every other import in this file is
deferred into a function for the same reason: importing `cfc.doctor` at
module level would compile it — and everything it imports — before the
version check ever ran.
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from cfc import entry

    problem = entry.check_interpreter()
    if problem is not None:
        print(problem, file=sys.stderr)
        return 1

    return _dispatch(sys.argv[1:] if argv is None else argv)


def _dispatch(args: list[str]) -> int:
    if not args:
        from cfc import tui
        return tui.run()

    command, rest = args[0], args[1:]
    if command == "doctor":
        from cfc import doctor
        return doctor.run(rest)

    print(f"Unknown command: {command!r}. Usage: python -m cfc [doctor]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
