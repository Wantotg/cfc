# tools.py — the tools a model may ask for, and the dispatcher.
#
# list_dir, read_file, grep (read) and write_file (write). No shell, no delete,
# no move. The approval gate (commands.py) decides *whether* a call runs; this
# module decides what it does and, crucially, whether it is allowed to at all.
#
# Three rules hold this together:
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
#
#   3. Reads and writes are guarded against DIFFERENT root sets, chosen by tool
#      name in _roots_for(). The write set is narrow (the vault outbox) and
#      cannot overlap the source tree — see context.py. A read root never
#      grants write access: a call arriving with only bare read roots gets an
#      empty write set, so write_file fails closed.
import json
import os
import re
from pathlib import Path

from context import ToolContext, as_context
from paths import path_guard, PathError, denial_reason, _as_roots

try:
    from config import TOOLS_ROOTS
except ImportError:
    try:
        from config import ATTACH_ROOTS as TOOLS_ROOTS
    except ImportError:
        TOOLS_ROOTS = (Path("~/projects").expanduser(),)
try:
    from config import TOOLS_MAX_RESULT_CHARS
except ImportError:
    TOOLS_MAX_RESULT_CHARS = 30_000

GREP_MAX_MATCHES = 100

# Tools that mutate the filesystem. Guarded against the write roots, never
# auto-approved, and the only members of this set are ones that create files.
WRITE_TOOLS = {"write_file"}


def is_mutating(name):
    """Whether this tool name mutates the filesystem — the one classification
    the codebase owns for it. /swipe and /undo's turn repair (main.py) ask
    this rather than keeping a second, command-local name list, so a future
    mutating tool joins the same refusal by joining WRITE_TOOLS alone."""
    return name in WRITE_TOOLS

# A runaway model writing a 50MB file into the vault is not a security problem
# but it is a mess to clean up. Content over this is refused, not truncated —
# a silently half-written note is worse than a failed call.
WRITE_MAX_CHARS = 200_000


def reserved_write_reason(p):
    """Why this resolved path is off-limits to a write tool, or None.

    ROUTINE_LOG_DIR lives *inside* WRITE_ROOTS (`<vault>/99 outbox/routine
    logs/` under `<vault>/99 outbox`), so containment alone lets a model
    overwrite the append-only run log that runner.append_log owns. That log is
    the audit trail AND what the next run reads via last_run() to honour
    on_failure, so a clobber destroys the record of the failure it exists to
    preserve — silently, since nothing compares the file against what the
    runner wrote. A model does not have to be asked to tidy its own log.

    Containment, not a name pattern. The deny list is the weaker tool here:
    it matches filenames, so it is an open-ended commitment (every config.py.bak
    shape escaped it once), while "this one directory" is a closed one. Same
    shape and same reason as mover._reject_wiki — a write whose damage is
    silent and arrives later.

    Writes only. Reading a run log is legitimate and stays allowed.
    """
    log_dir = _log_dir()
    if log_dir is None:
        return None
    if p == log_dir or log_dir in p.parents:
        return (f"{log_dir.name}/ is the routines' run log and is not "
                f"writable — runner.py appends to it, and a write here would "
                f"destroy the record of a run")
    return None


def _log_dir():
    """The resolved ROUTINE_LOG_DIR, or None if there isn't one.

    Imported lazily so the jail carries no import-time dependency on a feature
    module, and so patching routines.log_dir in a test is seen here. None on
    failure restricts nothing extra — the write roots still bound every write,
    so this can only ever narrow that scope, never widen it.
    """
    try:
        import routines
        return routines.log_dir().expanduser().resolve()
    except Exception:
        return None

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
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write a text file. Can only write inside the configured "
                "write scope (the outbox), which is separate from and much "
                "narrower than the readable scope — you cannot write next to "
                "a file just because you can read it. Refuses to replace an "
                "existing file unless overwrite is true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File to write, inside the write scope.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full text to write. Not appended — "
                                       "this is the whole file.",
                    },
                    "overwrite": {
                        "type": "boolean",
                        "description": "Replace the file if it already "
                                       "exists. Defaults to false.",
                    },
                },
                "required": ["path", "content"],
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


def _guard(path, roots):
    """path_guard, but returning the error string instead of raising."""
    try:
        return path_guard(path, roots), None
    except PathError as e:
        return None, _err(str(e))


def list_dir(path, roots):
    p, err = _guard(path, roots)
    if err:
        return err
    if not p.exists():
        return _err(f"no such directory: {p}")
    if not p.is_dir():
        return _err(f"not a directory: {p}")

    rows = []
    for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name)):
        # Denied entries are omitted entirely — not listed-and-refused. A
        # listing that shows config.py invites a read that path_guard will
        # refuse, which costs the user a prompt to decline a call that was
        # never going to succeed. Hiding is ergonomics, not security: the
        # deny list still refuses the path if the model simply guesses the
        # name, so nothing here is load-bearing for safety.
        if denial_reason(child):
            continue
        try:
            size = child.stat().st_size if child.is_file() else 0
        except OSError:
            size = 0
        kind = "dir" if child.is_dir() else "file"
        rows.append(f"{kind:<4} {size:>10,}  {child.name}")
    if not rows:
        return f"{p} is empty"
    return _truncate(f"{p}\n" + "\n".join(rows))


def read_file(path, roots, start_line=None, end_line=None):
    p, err = _guard(path, roots)
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


def _searchable(p, roots):
    if p.suffix.lower() not in _TEXT_SUFFIXES:
        return False
    try:
        path_guard(p, roots)
    except PathError:
        return False       # denied files are not grep-able either
    return True


def grep(pattern, roots, path=None):
    if not pattern:
        return _err("pattern is required")

    # No path means "search everything": walk every root. A given path is
    # guarded against the roots as usual.
    if path:
        target, err = _guard(path, roots)
        if err:
            return err
        if not target.exists():
            return _err(f"no such path: {target}")
        targets = [target]
    else:
        targets = _as_roots(roots)

    files = []
    for target in targets:
        if target.is_file():
            files.append(target)
            continue
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fn in sorted(filenames):
                files.append(Path(dirpath) / fn)

    out, hit_cap = [], False
    for f in files:
        # grep reads whole files looking for matches, so the deny list has to
        # apply per file, not just to the directory it was pointed at.
        # Otherwise grep("API_KEY", "~/projects") prints config.py's key.
        if not _searchable(f, roots):
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
        where = str(targets[0]) if len(targets) == 1 else \
            f"{len(targets)} roots"
        return f"no matches for {pattern!r} in {where}"
    body = "\n".join(out)
    if hit_cap:
        body += f"\n\n[stopped at {GREP_MAX_MATCHES} matches]"
    return _truncate(body)


def write_file(path, content, roots, overwrite=False):
    """Create or replace one text file inside the write roots.

    Two properties worth stating, because they're the point:

    * **Guarded before anything is touched.** Honours the standing invariant
      that a write checks its path *before* the write, never after — a test
      guard that asserted after its destructive step once deleted the real
      database.
    * **Atomic.** Content goes to a temp file in the same directory and is
      moved into place with os.replace(), which is atomic on the same
      filesystem. A crash or a full disk mid-write leaves the original intact
      rather than a half-written file that looks complete.
    """
    if not roots:
        return _err("writing is not enabled: no write roots are configured")

    p, err = _guard(path, roots)
    if err:
        return err

    # The boundary for the reserved directories, not the pre-filter in
    # precheck(). dispatch() is reachable without a gate at all, so a check
    # that only ran there would be advice.
    why = reserved_write_reason(p)
    if why:
        return _err(why)

    if content is None:
        return _err("write_file requires 'content'")
    if not isinstance(content, str):
        content = str(content)
    if len(content) > WRITE_MAX_CHARS:
        return _err(f"content is {len(content):,} chars, over the "
                    f"{WRITE_MAX_CHARS:,} limit")
    if p.is_dir():
        return _err(f"{p} is a directory, not a file")

    # Overwrite is an explicit capability, not a silent default. Clobbering is
    # the one thing writes do that reads never could, so it takes its own flag
    # and shows up as its own line at the approval gate.
    existed = p.exists()
    if existed and not overwrite:
        return _err(f"{p.name} already exists — pass overwrite=true to "
                    f"replace it")

    # Parents of a guarded path are inside the root by construction, so this
    # cannot create a directory outside the write scope.
    tmp = p.with_name(f".{p.name}.tmp-{os.getpid()}")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, p)
    except OSError as e:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return _err(f"could not write {p.name}: {e}")

    verb = "replaced" if existed else "wrote"
    lines = content.count("\n") + (1 if content and not
                                   content.endswith("\n") else 0)
    return f"{verb} {p} ({len(content):,} chars, {lines:,} lines)"


# The shape write_file's success line takes, and the only place that knows it.
# Anchored at both ends because every path in the vault contains spaces, so
# "the path" is everything between the verb and the trailing size clause — a
# split on whitespace would truncate `99 outbox/note.md` to `99`.
_WROTE_RE = re.compile(r"^(?:wrote|replaced) (?P<path>.+) "
                       r"\([\d,]+ chars, [\d,]+ lines\)$")


def written_path(name, result):
    """The file a successful write_file call landed on, or None.

    Lets a caller learn what a turn wrote without the tool loop having to
    understand tools. The run log is the consumer: when a routine fails
    halfway, "which files did it get to" is the first question, and the
    transcript is the only thing that could answer it today.

    **The producer and the parse live together on purpose.** This is the same
    coupling as commands.py's markers and db._MARKER_RE, and it carries the
    same hazard: reword write_file's success line and this silently returns
    None forever, which reads as "the run wrote nothing" — the exact false
    negative the log exists to avoid. tests/test_tools.py pins it by
    round-trip, running a real write and parsing its real result, so a reworded
    message fails a test instead of emptying a log field.

    An error result is a dict-shaped JSON string and cannot match the anchor,
    so a refused write is never counted as one that happened.
    """
    if name not in WRITE_TOOLS or not isinstance(result, str):
        return None
    m = _WROTE_RE.match(result.strip())
    return Path(m.group("path")) if m else None


def _roots_for(name, ctx):
    """The root set this tool is guarded against: write tools get the write
    set, everything else the read set. This is the split — a tool cannot pick
    its own scope, and there is no path by which a read root reaches a write.
    """
    return ctx.write_roots if name in WRITE_TOOLS else ctx.read_roots


def dispatch(name, arguments, ctx=None):
    """(tool name, arguments) -> result string. Never raises.

    `arguments` is whatever the model sent: a JSON string in practice, a dict
    if a caller already parsed it.

    `ctx` is a ToolContext. A bare roots value is still accepted and read as
    read-only scope (see context.as_context) — passing read roots must never
    imply write access.
    """
    ctx = as_context(ctx if ctx is not None else TOOLS_ROOTS)
    roots = _roots_for(name, ctx)

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
            return list_dir(args["path"], roots)
        if name == "read_file":
            if "path" not in args:
                return _err("read_file requires 'path'")
            return read_file(args["path"], roots,
                             args.get("start_line"), args.get("end_line"))
        if name == "grep":
            if "pattern" not in args:
                return _err("grep requires 'pattern'")
            return grep(args["pattern"], roots, args.get("path"))
        if name == "write_file":
            if "path" not in args:
                return _err("write_file requires 'path'")
            if "content" not in args:
                return _err("write_file requires 'content'")
            return write_file(args["path"], args["content"], roots,
                              bool(args.get("overwrite")))
        return _err(f"unknown tool: {name}")
    except Exception as e:
        # A tool bug must not take the agent loop down with it.
        return _err(f"{name} failed: {type(e).__name__}: {e}")


def precheck(name, arguments, ctx=None):
    """The jail error this call would fail with, or None. Never raises.

    Lets the approval gate refuse a doomed call without asking, so the user is
    never prompted to decline something path_guard was going to reject anyway.
    A gate that fires on calls that cannot succeed is a gate that gets
    rubber-stamped.

    This is a pre-filter, NOT the boundary. path_guard still runs inside
    dispatch() for every call regardless of what the gate decided — dispatch is
    reachable without a gate at all, so the guard cannot live here. Only
    containment/deny failures are pre-checked; a missing file or a bad argument
    stays a normal tool error the model sees and adapts to.
    """
    ctx = as_context(ctx if ctx is not None else TOOLS_ROOTS)
    roots = _roots_for(name, ctx)
    if isinstance(arguments, str):
        try:
            args = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            return None          # unparseable: let dispatch report it
    else:
        args = arguments or {}
    if not isinstance(args, dict):
        return None

    # A write with no write scope configured can never succeed, so refuse it
    # here rather than prompting for something that will fail anyway.
    if name in WRITE_TOOLS and not roots:
        return _err("writing is not enabled: no write roots are configured")

    # grep's path is optional (no path = walk the roots, which is fine).
    path = args.get("path")
    if not path or name not in ("list_dir", "read_file", "grep", "write_file"):
        return None
    try:
        p = path_guard(path, roots)
    except PathError as e:
        return _err(str(e))

    # Mirrors the refusal write_file makes, for the same reason precheck
    # mirrors path_guard: prompting for a call that cannot succeed teaches
    # the habit of rubber-stamping the gate.
    if name in WRITE_TOOLS:
        why = reserved_write_reason(p)
        if why:
            return _err(why)
    return None


def describe(name, arguments, ctx=None):
    """A human-readable summary of a call, for the approval gate.

    Shows the resolved path and, for read_file, the real size — so the cost of
    approving is visible before the decision, not after. Deliberately does not
    validate: this is what the model *asked for*, and a call that will be
    refused should still be shown honestly rather than pre-filtered.
    """
    ctx = as_context(ctx if ctx is not None else TOOLS_ROOTS)
    roots = _roots_for(name, ctx)
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
            roots = _as_roots(roots)
            where = _tilde(roots[0]) if len(roots) == 1 else \
                f"{len(roots)} roots"
            lines.append(f"path: {where} (whole tree)")

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

    if name == "write_file":
        # The one call that changes something on disk, so the panel has to say
        # plainly what it will do. "replaces an existing file" is the line that
        # should make a human stop and read.
        body = args.get("content")
        body = body if isinstance(body, str) else str(body or "")
        lines.insert(0, "WRITE")
        lines.append(f"{len(body):,} chars, "
                     f"{body.count(chr(10)) + 1:,} lines")
        if p is not None and p.exists():
            if args.get("overwrite"):
                lines.append("REPLACES an existing file")
            else:
                lines.append("(file exists — will be refused "
                             "without overwrite)")
        else:
            lines.append("(new file)")

    return lines


def _tilde(p):
    try:
        return "~/" + str(p.relative_to(Path.home()))
    except ValueError:
        return str(p)
