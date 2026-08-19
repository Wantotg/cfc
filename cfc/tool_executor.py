"""tool_executor.py — the three bounded read-only file tools (Stage 6 loop
1): `list_dir`, `read_file`, and literal `grep`. Every one goes through
`cfc.tool_authority.open_contained` for its target (and, for `grep` on a
directory, every descendant it descends into) — no path here is ever
resolved and reopened by name a second time.

Presentation-free: nothing here formats for a terminal, asks for approval,
or knows about a provider. Each function returns one `ExecutionOutcome` —
a typed kind, a bounded cfc-authored reason, the exact bounded text a
caller may replay to a provider, counts, a truncation flag, and (when
applicable) the canonical target and configured root a caller wants for
operational evidence. `cfc.tool_registry` is this module's one caller.

Work bounds are enforced *while* work is performed, not by slicing a
finished string: a scan stops at its own entry/file/byte limit before
`os.scandir`/`os.read` produce more than that limit's worth of data, and
every bounded loop checks `is_cancelled()` between units of work.
"""
from __future__ import annotations

import errno
import os
import stat
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from cfc.conversation_types import ToolOutcomeKind
from cfc.settings import REPOSITORY_ROOT, FileToolSettings
from cfc.tool_authority import (
    AuthorityOutcome,
    FileAuthority,
    OpenTarget,
    Refused,
    is_denied_name,
    open_contained,
    require_absolute,
)

IsCancelled = Callable[[], bool]


def _never_cancelled() -> bool:
    return False


@dataclass(frozen=True)
class ExecutionOutcome:
    """One tool call's execution result — the shape `cfc.tool_registry`
    turns into both a `conversation_types.ToolResult` (kind, reason,
    content, truncated) and a `conversation_types.ToolCallEvidence` (kind,
    reason, root, canonical_target, counts, truncated) without asking this
    module twice.
    """
    kind: ToolOutcomeKind
    reason: str
    content: str
    truncated: bool = False
    canonical_target: str | None = None
    root: str | None = None
    counts: dict[str, int] = field(default_factory=dict)


_AUTHORITY_TO_TOOL_OUTCOME = {
    AuthorityOutcome.UNAVAILABLE: ToolOutcomeKind.UNAVAILABLE,
    AuthorityOutcome.REFUSAL: ToolOutcomeKind.REFUSAL,
    AuthorityOutcome.FAILURE: ToolOutcomeKind.FAILURE,
}


def _from_refused(refused: Refused) -> ExecutionOutcome:
    return ExecutionOutcome(
        kind=_AUTHORITY_TO_TOOL_OUTCOME[refused.outcome], reason=refused.reason, content="",
    )


def is_hidden_name(name: str) -> bool:
    """A dotfile/dotdirectory — omitted from a listing or a recursive
    search the same way a denied name is (Concept.md: "Denied,
    source-tree, and hidden entries are omitted"), distinct from the
    built-in secret deny list: broader, and never refuses a *direct*
    request for a hidden path the way a denied name does — only pruned
    from enumeration.
    """
    return name.startswith(".")


def _is_repository_path(candidate: Path) -> bool:
    return candidate == REPOSITORY_ROOT or REPOSITORY_ROOT in candidate.parents


def _child_absolute(target: OpenTarget, name: str) -> Path:
    if target.relative == ".":
        return target.root / name
    return target.root / target.relative / name


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    omitted = len(text) - max_chars
    return text[:max_chars] + f"\n\n[truncated, {omitted:,} chars omitted]", True


# --- list_dir ---------------------------------------------------------------

_LIST_DIR_MAX_RAW_ENTRIES = 10_000
_LIST_DIR_MAX_VISIBLE_ENTRIES = 1_000


def list_dir(
    path_str: object, authority: FileAuthority, settings: FileToolSettings,
    is_cancelled: IsCancelled = _never_cancelled,
) -> ExecutionOutcome:
    """Lists one directory without recursion. Sorted by name; a regular
    file may carry its byte size; a symlink or directory never does (its
    kind alone is reported, never followed to discover a size). Denied,
    hidden, and cfc-source-tree entries are omitted, with an exclusion
    count so an omission is never mistaken for a truly empty directory.
    """
    located = require_absolute(path_str)
    if isinstance(located, Refused):
        return _from_refused(located)
    opened = open_contained(located, authority)
    if isinstance(opened, Refused):
        return _from_refused(opened)

    with opened as target:
        try:
            mode = os.fstat(target.fd).st_mode
        except OSError as exc:
            return ExecutionOutcome(
                kind=ToolOutcomeKind.FAILURE, reason=f"could not inspect target ({exc.strerror})",
                content="", canonical_target=target.relative, root=str(target.root),
            )
        if not stat.S_ISDIR(mode):
            return ExecutionOutcome(
                kind=ToolOutcomeKind.FAILURE, reason=f"{target.relative} is not a directory",
                content="", canonical_target=target.relative, root=str(target.root),
            )

        rows: list[tuple[str, str, int | None]] = []
        raw_examined = 0
        excluded = 0
        raw_bound_hit = False
        visible_bound_hit = False
        cancelled = False

        try:
            with os.scandir(target.fd) as it:
                for entry in it:
                    if is_cancelled():
                        cancelled = True
                        break
                    if raw_examined >= _LIST_DIR_MAX_RAW_ENTRIES:
                        raw_bound_hit = True
                        break
                    raw_examined += 1
                    name = entry.name
                    if is_hidden_name(name) or is_denied_name(name):
                        excluded += 1
                        continue
                    if _is_repository_path(_child_absolute(target, name)):
                        excluded += 1
                        continue
                    if len(rows) >= _LIST_DIR_MAX_VISIBLE_ENTRIES:
                        visible_bound_hit = True
                        break
                    try:
                        if entry.is_symlink():
                            rows.append(("symlink", name, None))
                        elif entry.is_dir(follow_symlinks=False):
                            rows.append(("dir", name, None))
                        elif entry.is_file(follow_symlinks=False):
                            try:
                                size = entry.stat(follow_symlinks=False).st_size
                            except OSError:
                                size = None
                            rows.append(("file", name, size))
                        else:
                            rows.append(("other", name, None))
                    except OSError:
                        rows.append(("other", name, None))
        except OSError as exc:
            return ExecutionOutcome(
                kind=ToolOutcomeKind.FAILURE, reason=f"could not list directory ({exc.strerror})",
                content="", canonical_target=target.relative, root=str(target.root),
            )

        if cancelled:
            return ExecutionOutcome(
                kind=ToolOutcomeKind.CANCELLATION, reason="cancelled while listing the directory",
                content="", canonical_target=target.relative, root=str(target.root),
            )

        rows.sort(key=lambda row: row[1])
        if rows:
            width = max(len(str(size)) for _, _, size in rows if size is not None) if any(
                size is not None for _, _, size in rows
            ) else 0
            lines = []
            for kind, name, size in rows:
                size_field = "" if size is None else f"{size:>{width},}"
                lines.append(f"{kind:<7} {size_field:>{width}}  {name}")
            body = f"{target.relative} ({len(rows)} entr{'y' if len(rows) == 1 else 'ies'} shown)\n" \
                   + "\n".join(lines)
        else:
            body = f"{target.relative} (0 entries shown)"

        notes = []
        if raw_bound_hit:
            notes.append(f"stopped after examining {_LIST_DIR_MAX_RAW_ENTRIES:,} raw entries")
        if visible_bound_hit:
            notes.append(f"stopped after {_LIST_DIR_MAX_VISIBLE_ENTRIES:,} visible entries")
        if excluded:
            plural = "y" if excluded == 1 else "ies"
            notes.append(f"{excluded:,} entr{plural} excluded (denied, hidden, or source tree)")
        if notes:
            body += "\n\n[" + "; ".join(notes) + "]"

        content, truncated = _truncate(body, settings.max_result_chars)
        return ExecutionOutcome(
            kind=ToolOutcomeKind.SUCCESS, reason="listed directory", content=content,
            truncated=truncated, canonical_target=target.relative, root=str(target.root),
            counts={"entries_examined": raw_examined, "entries_returned": len(rows),
                    "entries_excluded": excluded},
        )


# --- read_file ----------------------------------------------------------

_READ_CHUNK_SIZE = 65536
_READ_FAR_RANGE_SCAN_CAP = 8 * 1024 * 1024


def _validate_line_range(start_line: object, end_line: object) -> tuple[int, int | None] | str:
    if start_line is None:
        lo = 1
    elif isinstance(start_line, bool) or not isinstance(start_line, int):
        return "start_line must be an integer"
    elif start_line < 1:
        return f"start_line must be 1 or greater, got {start_line}"
    else:
        lo = start_line

    if end_line is None:
        hi = None
    elif isinstance(end_line, bool) or not isinstance(end_line, int):
        return "end_line must be an integer"
    elif end_line < lo:
        return f"end_line {end_line} is before start_line {lo}"
    else:
        hi = end_line
    return lo, hi


def read_file(
    path_str: object, authority: FileAuthority, settings: FileToolSettings,
    start_line: object = None, end_line: object = None,
    is_cancelled: IsCancelled = _never_cancelled,
) -> ExecutionOutcome:
    """Reads strict UTF-8 from the opened file descriptor, optionally
    bounded to `[start_line, end_line]` (1-based, inclusive). Output stops
    at `settings.max_result_chars` and says the last included line and
    that more text exists; it never calls a truncated whole file complete.
    A far-away requested range scans at most 8 MiB before returning an
    explicit incomplete result rather than walking an arbitrary file to
    find one line.
    """
    located = require_absolute(path_str)
    if isinstance(located, Refused):
        return _from_refused(located)

    range_result = _validate_line_range(start_line, end_line)
    if isinstance(range_result, str):
        return ExecutionOutcome(kind=ToolOutcomeKind.FAILURE, reason=range_result, content="")
    lo, hi = range_result

    opened = open_contained(located, authority)
    if isinstance(opened, Refused):
        return _from_refused(opened)

    with opened as target:
        try:
            mode = os.fstat(target.fd).st_mode
        except OSError as exc:
            return ExecutionOutcome(
                kind=ToolOutcomeKind.FAILURE, reason=f"could not inspect target ({exc.strerror})",
                content="", canonical_target=target.relative, root=str(target.root),
            )
        if not stat.S_ISREG(mode):
            return ExecutionOutcome(
                kind=ToolOutcomeKind.FAILURE, reason=f"{target.relative} is not a regular file",
                content="", canonical_target=target.relative, root=str(target.root),
            )

        bytes_read = 0
        buffer = bytearray()
        line_no = 1
        collected: list[bytes] = []
        collected_chars = 0
        hit_char_cap = False
        hit_scan_cap = False
        reached_hi = False
        eof = False

        while True:
            if is_cancelled():
                return ExecutionOutcome(
                    kind=ToolOutcomeKind.CANCELLATION, reason="cancelled while reading the file",
                    content="", canonical_target=target.relative, root=str(target.root),
                )
            try:
                chunk = os.read(target.fd, _READ_CHUNK_SIZE)
            except OSError as exc:
                return ExecutionOutcome(
                    kind=ToolOutcomeKind.FAILURE, reason=f"could not read file ({exc.strerror})",
                    content="", canonical_target=target.relative, root=str(target.root),
                )
            if not chunk:
                eof = True
                break
            bytes_read += len(chunk)
            buffer += chunk
            while True:
                newline = buffer.find(b"\n")
                if newline == -1:
                    break
                raw = bytes(buffer[:newline])
                del buffer[:newline + 1]
                if line_no >= lo:
                    collected.append(raw)
                    collected_chars += len(raw) + 1
                line_no += 1
                if hi is not None and line_no > hi:
                    reached_hi = True
                    break
                if collected_chars > settings.max_result_chars:
                    hit_char_cap = True
                    break
            if reached_hi or hit_char_cap:
                break
            if line_no <= lo and bytes_read >= _READ_FAR_RANGE_SCAN_CAP:
                hit_scan_cap = True
                break

        if hit_scan_cap:
            return ExecutionOutcome(
                kind=ToolOutcomeKind.FAILURE,
                reason=f"scanned {_READ_FAR_RANGE_SCAN_CAP:,} bytes without reaching line "
                       f"{lo}; the file may be too large for this range",
                content="", canonical_target=target.relative, root=str(target.root),
                counts={"bytes_scanned": bytes_read},
            )

        total_lines: int | None = None
        if eof:
            if buffer:
                raw = bytes(buffer)
                if not (reached_hi or hit_char_cap):
                    if line_no >= lo and (hi is None or line_no <= hi):
                        collected.append(raw)
                        collected_chars += len(raw)
                    total_lines = line_no
                else:
                    total_lines = None
            else:
                total_lines = line_no - 1

        if total_lines is not None and lo > total_lines and total_lines > 0:
            return ExecutionOutcome(
                kind=ToolOutcomeKind.FAILURE,
                reason=f"start_line {lo} is past the end of the file ({total_lines} lines)",
                content="", canonical_target=target.relative, root=str(target.root),
            )

        try:
            decoded = [line.decode("utf-8") for line in collected]
        except UnicodeDecodeError:
            return ExecutionOutcome(
                kind=ToolOutcomeKind.FAILURE, reason=f"{target.relative} is not valid UTF-8",
                content="", canonical_target=target.relative, root=str(target.root),
            )

        if decoded:
            first_line = lo
            last_line = lo + len(decoded) - 1
            width = len(str(last_line))
            body_lines = "\n".join(
                f"{n:>{width}}| {text}" for n, text in zip(range(first_line, last_line + 1), decoded)
            )
            if total_lines is not None:
                header = f"{target.relative} ({total_lines} lines"
                header += ")" if (first_line, last_line) == (1, total_lines) \
                    else f", showing {first_line}-{last_line})"
            else:
                header = f"{target.relative} (showing {first_line}-{last_line}, more text exists)"
            body = f"{header}\n{body_lines}"
        else:
            body = f"{target.relative} (0 lines in the requested range)"

        content, char_truncated = _truncate(body, settings.max_result_chars)
        truncated = char_truncated or hit_char_cap
        if hit_char_cap and not char_truncated:
            content += "\n\n[truncated: more text exists beyond this line range]"

        return ExecutionOutcome(
            kind=ToolOutcomeKind.SUCCESS, reason="read file", content=content,
            truncated=truncated, canonical_target=target.relative, root=str(target.root),
            counts={"bytes_scanned": bytes_read, "lines_returned": len(decoded)},
        )


# --- literal grep ---------------------------------------------------------

_GREP_MAX_PATTERN_CHARS = 1_000
_GREP_MAX_MATCHES = 100
_GREP_MAX_FILES_EXAMINED = 10_000
_GREP_MAX_BYTES_EXAMINED = 64 * 1024 * 1024

_TEXT_SUFFIXES = {
    ".txt", ".md", ".markdown", ".py", ".json", ".yaml", ".yml", ".toml",
    ".csv", ".sql", ".sh", ".cfg", ".ini", ".js", ".ts", ".html", ".css",
    ".rst", ".log",
}


@dataclass
class _GrepState:
    matches: list[tuple[str, int, str]] = field(default_factory=list)
    files_examined: int = 0
    bytes_examined: int = 0
    files_skipped: int = 0
    files_excluded: int = 0
    match_bound_hit: bool = False
    file_bound_hit: bool = False
    byte_bound_hit: bool = False
    cancelled: bool = False
    complete: bool = True

    def bounded(self) -> bool:
        return (len(self.matches) >= _GREP_MAX_MATCHES
                or self.files_examined >= _GREP_MAX_FILES_EXAMINED
                or self.bytes_examined >= _GREP_MAX_BYTES_EXAMINED
                or self.cancelled)


def _grep_one_file(
    pattern: str, target: OpenTarget, state: _GrepState, is_cancelled: IsCancelled,
) -> None:
    try:
        data = b""
        while True:
            chunk = os.read(target.fd, _READ_CHUNK_SIZE)
            if not chunk:
                break
            data += chunk
            if len(data) > _GREP_MAX_BYTES_EXAMINED:
                break
    except OSError:
        state.files_skipped += 1
        state.complete = False
        return
    state.bytes_examined += len(data)
    state.files_examined += 1
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        state.files_skipped += 1
        state.complete = False
        return
    for line_no, line in enumerate(text.split("\n"), start=1):
        if pattern in line:
            state.matches.append((target.relative, line_no, line))
            if len(state.matches) >= _GREP_MAX_MATCHES:
                state.match_bound_hit = True
                state.complete = False
                return


def _iter_tree(
    dir_fd: int, dir_relative: str, root: Path, is_cancelled: IsCancelled, state: _GrepState,
) -> Iterator[tuple[str, int]]:
    """Yields `(relative_path, opened_fd)` for every eligible regular file
    under `dir_fd`, recursing without following symlinks. The cfc source
    tree, built-in/hidden/denied names, and non-text suffixes are pruned
    before descent or open — never opened at all, so an excluded subtree
    costs nothing beyond a name comparison. Caller closes each yielded fd.
    """
    try:
        with os.scandir(dir_fd) as it:
            children = sorted(it, key=lambda e: e.name)
    except OSError:
        state.complete = False
        return

    for entry in children:
        if is_cancelled():
            state.cancelled = True
            return
        if state.bounded():
            return
        name = entry.name
        if is_hidden_name(name) or is_denied_name(name):
            state.files_excluded += 1
            continue
        child_relative = name if dir_relative == "." else f"{dir_relative}/{name}"
        child_absolute = root / child_relative
        if child_absolute == REPOSITORY_ROOT or REPOSITORY_ROOT in child_absolute.parents:
            state.files_excluded += 1
            continue
        try:
            child_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                state.files_excluded += 1  # a symlink, silently pruned
            else:
                state.files_skipped += 1
                state.complete = False
            continue
        try:
            mode = os.fstat(child_fd).st_mode
        except OSError:
            os.close(child_fd)
            state.files_skipped += 1
            state.complete = False
            continue
        if stat.S_ISDIR(mode):
            yield from _iter_tree(child_fd, child_relative, root, is_cancelled, state)
            os.close(child_fd)
        elif stat.S_ISREG(mode):
            if os.path.splitext(name)[1].lower() not in _TEXT_SUFFIXES:
                os.close(child_fd)
                state.files_excluded += 1
                continue
            yield (child_relative, child_fd)
        else:
            os.close(child_fd)


def grep(
    pattern: object, path_str: object, authority: FileAuthority, settings: FileToolSettings,
    is_cancelled: IsCancelled = _never_cancelled,
) -> ExecutionOutcome:
    """Literal-only search: no regex, case-folding, glob, or shell, and no
    implicit "search every root" mode — `path` is always required. A
    directory target recurses without following symlinks, pruning the cfc
    source tree, hidden/denied paths, and non-text suffixes before
    descent. Stops at 100 matches, 10,000 examined files, or 64 MiB of
    examined data, and records which limit won; files skipped because they
    were denied, not valid UTF-8, or could not be read are counted
    separately from files that simply had no match.
    """
    if not isinstance(pattern, str) or not pattern:
        return ExecutionOutcome(kind=ToolOutcomeKind.FAILURE, reason="pattern is required", content="")
    if len(pattern) > _GREP_MAX_PATTERN_CHARS:
        return ExecutionOutcome(
            kind=ToolOutcomeKind.FAILURE,
            reason=f"pattern is over the {_GREP_MAX_PATTERN_CHARS:,}-character limit", content="",
        )

    located = require_absolute(path_str)
    if isinstance(located, Refused):
        return _from_refused(located)
    opened = open_contained(located, authority)
    if isinstance(opened, Refused):
        return _from_refused(opened)

    with opened as target:
        try:
            mode = os.fstat(target.fd).st_mode
        except OSError as exc:
            return ExecutionOutcome(
                kind=ToolOutcomeKind.FAILURE, reason=f"could not inspect target ({exc.strerror})",
                content="", canonical_target=target.relative, root=str(target.root),
            )

        state = _GrepState()
        if stat.S_ISREG(mode):
            _grep_one_file(pattern, target, state, is_cancelled)
        elif stat.S_ISDIR(mode):
            for relative, fd in _iter_tree(target.fd, target.relative, target.root,
                                            is_cancelled, state):
                file_target = OpenTarget(fd=fd, relative=relative, root=target.root)
                try:
                    if state.bounded():
                        file_target.close()
                        break
                    _grep_one_file(pattern, file_target, state, is_cancelled)
                finally:
                    file_target.close()
                if state.bounded():
                    break
        else:
            return ExecutionOutcome(
                kind=ToolOutcomeKind.FAILURE,
                reason=f"{target.relative} is neither a regular file nor a directory",
                content="", canonical_target=target.relative, root=str(target.root),
            )

        if state.cancelled:
            return ExecutionOutcome(
                kind=ToolOutcomeKind.CANCELLATION, reason="cancelled while searching",
                content="", canonical_target=target.relative, root=str(target.root),
            )

        width = max((len(str(n)) for _, n, _ in state.matches), default=1)
        lines = [f"{path}:{n:>{width}}: {text}" for path, n, text in state.matches]
        if lines:
            body = f"{len(state.matches)} match(es) for {pattern!r} under {target.relative}\n" \
                   + "\n".join(lines)
        else:
            body = f"no matches for {pattern!r} under {target.relative}"

        limit_notes = []
        if state.match_bound_hit:
            limit_notes.append(f"stopped at {_GREP_MAX_MATCHES} matches")
        if state.files_examined >= _GREP_MAX_FILES_EXAMINED:
            state.file_bound_hit = True
            limit_notes.append(f"stopped after examining {_GREP_MAX_FILES_EXAMINED:,} files")
        if state.bytes_examined >= _GREP_MAX_BYTES_EXAMINED:
            state.byte_bound_hit = True
            limit_notes.append(f"stopped after examining {_GREP_MAX_BYTES_EXAMINED:,} bytes")
        if state.files_skipped:
            limit_notes.append(f"{state.files_skipped:,} file(s) skipped (unreadable or not UTF-8)")
        if state.files_excluded:
            limit_notes.append(f"{state.files_excluded:,} file(s) excluded (denied, hidden, "
                                f"source tree, or non-text)")
        incomplete = bool(limit_notes) and not state.complete or state.match_bound_hit \
            or state.file_bound_hit or state.byte_bound_hit
        if incomplete:
            limit_notes.append("search incomplete: more matches may exist")
        if limit_notes:
            body += "\n\n[" + "; ".join(limit_notes) + "]"

        content, char_truncated = _truncate(body, settings.max_result_chars)
        return ExecutionOutcome(
            kind=ToolOutcomeKind.SUCCESS, reason="search complete" if not incomplete
            else "search incomplete: a limit was reached", content=content,
            truncated=char_truncated, canonical_target=target.relative, root=str(target.root),
            counts={"matches": len(state.matches), "files_examined": state.files_examined,
                    "files_skipped": state.files_skipped, "files_excluded": state.files_excluded,
                    "bytes_examined": state.bytes_examined},
        )
