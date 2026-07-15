# tools.py — the read-only tools a model may ask for, and the dispatcher.
#
# Read-only by design: list_dir, read_file, grep, and nothing else. No writes,
# no shell. The approval gate (main.py) decides *whether* a call runs; this
# module decides what it does and, crucially, whether it is allowed to at all.
#
# Two rules hold this together:
#
#   1. Every path goes through path_guard() HERE, inside the dispatcher, not
#      at the call site and never on the model's say-so. Approval does not
#      bypass validation: a user can approve a call that then fails the guard,
#      and that is correct. Models guess paths — during testing one asked for
#      /home/user/projects/cfc/README.md, a directory that doesn't exist.
#
#   2. Failures come back as tool results, never as exceptions. The model sees
#      {"error": ...}, reads it, and adapts. Denial is data. Raising into the
#      agent loop would turn a refusal into a crash.
import json
import os
from pathlib import Path

from paths import path_guard, PathError

try:
    from config import TOOLS_ROOT
except ImportError:
    try:
        from config import ATTACH_ROOT as TOOLS_ROOT
    except ImportError:
        TOOLS_ROOT = Path("~/projects").expanduser()
try:
    from config import TOOLS_MAX_RESULT_CHARS
except ImportError:
    TOOLS_MAX_RESULT_CHARS = 30_000

GREP_MAX_MATCHES = 100

# Directories that are never worth walking: huge, generated, or not source.
# Skipped by grep so a search doesn't spend a minute in .venv and return
# matches from third-party code the user didn't write.
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__",
              ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
              ".tox", ".idea", ".vscode"}

# Files grep will read. Anything else is skipped as presumed binary. Kept
# broader than ATTACH_EXTENSIONS: grep only ever emits matching lines, so the
# blast radius of an odd file type is one line, not the whole file.
_TEXT_SUFFIXES = {
    ".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml", ".csv", ".sql",
    ".sh", ".cfg", ".ini", ".conf", ".rst", ".js", ".ts", ".html", ".css",
    ".c", ".h", ".cpp", ".rs", ".go", ".java", ".rb", ".lua", ".vim", "",
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": (
                "List the contents of one directory. Does not recurse. "
                "Returns each entry's name, whether it is a file or "
                "directory, and its size in bytes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory to list.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read a text file, with line numbers. Optionally read only a "
                "range of lines. Long results are truncated."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string",
                             "description": "File to read."},
                    "start_line": {
                        "type": "integer",
                        "description": "First line to read, 1-based. "
                                       "Optional.",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to read, inclusive. "
                                       "Optional.",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": (
                "Search files for a literal substring, recursively. Returns "
                "matching lines prefixed with file and line number, capped "
                f"at {GREP_MAX_MATCHES} matches."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string",
                                "description": "Literal text to search for."},
                    "path": {
                        "type": "string",
                        "description": "File or directory to search. "
                                       "Defaults to the project root.",
                    },
                },
                "required": ["pattern"],
            },
        },
    },
]


def _err(msg):
    return json.dumps({"error": msg})


def _truncate(text):
    if len(text) <= TOOLS_MAX_RESULT_CHARS:
        return text
    omitted = len(text) - TOOLS_MAX_RESULT_CHARS
    return (text[:TOOLS_MAX_RESULT_CHARS]
            + f"\n\n[truncated, {omitted:,} chars omitted]")


def _guard(path, root):
    """path_guard, but returning the error string instead of raising."""
    try:
        return path_guard(path, root), None
    except PathError as e:
        return None, _err(str(e))


def list_dir(path, root):
    p, err = _guard(path, root)
    if err:
        return err
    if not p.exists():
        return _err(f"no such directory: {p}")
    if not p.is_dir():
        return _err(f"not a directory: {p}")

    rows = []
    for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name)):
        try:
            size = child.stat().st_size if child.is_file() else 0
        except OSError:
            size = 0
        kind = "dir" if child.is_dir() else "file"
        rows.append(f"{kind:<4} {size:>10,}  {child.name}")
    if not rows:
        return f"{p} is empty"
    return _truncate(f"{p}\n" + "\n".join(rows))


def read_file(path, root, start_line=None, end_line=None):
    p, err = _guard(path, root)
    if err:
        return err
    if not p.exists():
        return _err(f"no such file: {p}")
    if p.is_dir():
        return _err(f"{p} is a directory, not a file")

    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _err(f"{p.name} is not a text file (not valid UTF-8)")
    except OSError as e:
        return _err(f"could not read {p.name}: {e}")

    lines = text.splitlines()
    total = len(lines)

    if start_line is None and end_line is None:
        lo, hi = 1, total
    else:
        try:
            lo = int(start_line) if start_line is not None else 1
            hi = int(end_line) if end_line is not None else total
        except (TypeError, ValueError):
            return _err("start_line and end_line must be integers")
        if lo < 1:
            return _err(f"start_line must be 1 or greater, got {lo}")
        if lo > total:
            return _err(f"start_line {lo} is past the end of the file "
                        f"({total} lines)")
        hi = min(hi, total)
        if hi < lo:
            return _err(f"end_line {hi} is before start_line {lo}")

    width = len(str(hi))
    body = "\n".join(f"{n:>{width}}| {lines[n - 1]}" for n in range(lo, hi + 1))
    header = f"{p} ({total} lines"
    header += f", showing {lo}-{hi})" if (lo, hi) != (1, total) else ")"
    return _truncate(f"{header}\n{body}")


def _searchable(p, root):
    if p.suffix.lower() not in _TEXT_SUFFIXES:
        return False
    try:
        path_guard(p, root)
    except PathError:
        return False       # denied files are not grep-able either
    return True


def grep(pattern, root, path=None):
    if not pattern:
        return _err("pattern is required")

    target, err = _guard(path if path else root, root)
    if err:
        return err
    if not target.exists():
        return _err(f"no such path: {target}")

    if target.is_file():
        files = [target]
    else:
        files = []
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in sorted(filenames):
                files.append(Path(dirpath) / fn)

    out, hit_cap = [], False
    for f in files:
        # grep reads whole files looking for matches, so the deny list has to
        # apply per file, not just to the directory it was pointed at.
        # Otherwise grep("API_KEY", "~/projects") prints config.py's key.
        if not _searchable(f, root):
            continue
        try:
            with open(f, "r", encoding="utf-8", errors="strict") as fh:
                for n, line in enumerate(fh, 1):
                    if pattern in line:
                        rel = f
                        out.append(f"{rel}:{n}: {line.rstrip()}")
                        if len(out) >= GREP_MAX_MATCHES:
                            hit_cap = True
                            break
        except (UnicodeDecodeError, OSError):
            continue
        if hit_cap:
            break

    if not out:
        return f"no matches for {pattern!r} in {target}"
    body = "\n".join(out)
    if hit_cap:
        body += f"\n\n[stopped at {GREP_MAX_MATCHES} matches]"
    return _truncate(body)


def dispatch(name, arguments, root=None):
    """(tool name, arguments) -> result string. Never raises.

    `arguments` is whatever the model sent: a JSON string in practice, a dict
    if a caller already parsed it.
    """
    root = root if root is not None else TOOLS_ROOT

    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return _err("could not parse arguments")
    elif arguments is None:
        args = {}
    else:
        args = arguments
    if not isinstance(args, dict):
        return _err("could not parse arguments")

    try:
        if name == "list_dir":
            if "path" not in args:
                return _err("list_dir requires 'path'")
            return list_dir(args["path"], root)
        if name == "read_file":
            if "path" not in args:
                return _err("read_file requires 'path'")
            return read_file(args["path"], root,
                             args.get("start_line"), args.get("end_line"))
        if name == "grep":
            if "pattern" not in args:
                return _err("grep requires 'pattern'")
            return grep(args["pattern"], root, args.get("path"))
        return _err(f"unknown tool: {name}")
    except Exception as e:
        # A tool bug must not take the agent loop down with it.
        return _err(f"{name} failed: {type(e).__name__}: {e}")


def describe(name, arguments, root=None):
    """A human-readable summary of a call, for the approval gate.

    Shows the resolved path and, for read_file, the real size — so the cost of
    approving is visible before the decision, not after. Deliberately does not
    validate: this is what the model *asked for*, and a call that will be
    refused should still be shown honestly rather than pre-filtered.
    """
    root = root if root is not None else TOOLS_ROOT
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return [f"arguments: {arguments[:60]}", "(unparseable)"]
    else:
        args = arguments or {}
    if not isinstance(args, dict):
        return [f"arguments: {str(args)[:60]}", "(unparseable)"]

    lines = []
    raw = args.get("path")
    if raw is not None:
        try:
            p = Path(str(raw)).expanduser().resolve()
            lines.append(f"path: {_tilde(p)}")
        except (OSError, ValueError):
            lines.append(f"path: {raw}")
            p = None
    else:
        p = None

    if name == "grep":
        lines.insert(0, f"pattern: {args.get('pattern')!r}")
        if raw is None:
            lines.append(f"path: {_tilde(Path(root))} (whole tree)")

    if name == "read_file":
        lo, hi = args.get("start_line"), args.get("end_line")
        if lo or hi:
            lines.append(f"lines: {lo or 1}-{hi or 'end'}")
        if p is not None and p.is_file():
            try:
                size = p.stat().st_size
                n = sum(1 for _ in p.open("rb"))
                lines.append(f"({n:,} lines, {size / 1024:,.0f} KB)")
            except OSError:
                pass
        elif p is not None and not p.exists():
            lines.append("(does not exist)")

    return lines


def _tilde(p):
    try:
        return "~/" + str(p.relative_to(Path.home()))
    except ValueError:
        return str(p)
