"""chat_export.py — a presentation-free, standalone Markdown exporter for
one supplied chat snapshot (Stage 5 loop 3).

Pure rendering plus safe, atomic publication to a configured destination
directory. This module never touches SQLite, the vault, the provider,
embeddings, or Qdrant, and it never triggers itself — every export is one
explicit caller-invoked action (`ConversationService.export_chat`). It reads
exactly the canonical `Chat`, `OpeningMessage | None`, and
`ConversationSnapshot` a caller hands it; it never reaches back into the
store, a filesystem path outside the one destination it is given, or a
source/attachment body.

The rendered Markdown is a write-only human artifact (Concept.md: "cfc does
not parse or import it, so this design does not open a maintained
producer/parser pair") — there is deliberately no reader half to keep in
sync with this one.
"""
from __future__ import annotations

import datetime
import os
import re

from cfc.conversation_types import (
    CancelledOutcome,
    Chat,
    CompletedOutcome,
    ContextManifestEntry,
    ConversationSnapshot,
    FailedOutcome,
    FailureKind,
    Message,
    OpeningMessage,
    Role,
    Turn,
    Usage,
)

#: Bumped only when the rendered shape itself changes — recorded inside
#: every export so a much later human reader can tell which shape they are
#: looking at, the same discipline `context.SYSTEM_INSTRUCTIONS_VERSION`
#: already applies to a different fixed text.
#:
#: v2 (Stage 5 loop 4): the filename uses local wall-clock time instead of
#: UTC (B-2.0-74) — the document metadata's `export time` remains the same
#: instant, now with its local offset rather than always `+00:00`; the
#: context-provenance block is one valid nested Markdown list rather than a
#: bare line that broke it in two (D-2.0-75); an interrupted turn's status
#: is named `interrupted`, not folded into `failed` (B-2.0-79).
EXPORT_FORMAT_VERSION = "v2"


def _local_now() -> datetime.datetime:
    """One timezone-aware local instant — `datetime.now()`'s naive local
    wall-clock reading, with `.astimezone()` (no argument) attaching this
    machine's real local UTC offset to it in the same call. `export_chat`
    reads this once and feeds the same instant to both the filename (its
    local wall-clock form) and the document metadata (that instant, with
    its offset) — one clock read, never two independently timed calls that
    could straddle a second boundary and disagree (B-2.0-74).
    """
    return datetime.datetime.now().astimezone()


class ExportError(Exception):
    """Base for every typed export refusal this module raises. `str(exc)`
    is always bounded and safe to show directly — never a raw `OSError`
    string or a source/attachment body.
    """


class DestinationUnusable(ExportError):
    """`CHAT_EXPORT_DIR` is unset, or does not currently resolve to an
    existing, writable directory. Raised before anything is rendered or
    written.
    """


class CollisionExhausted(ExportError):
    """Every numbered suffix this module is willing to try is already
    taken. Vanishingly unlikely (`_reserve_destination`'s own upper bound),
    named as its own type rather than folded into a generic I/O failure so
    a caller can tell "the destination is full of exports" apart from "the
    disk refused a write."
    """


class ExportWriteFailed(ExportError):
    """A read, render, temporary-write, flush, or publish step failed.
    Never leaves a temporary file presented as a finished export — the
    caller sees this exception, or a `Path` that genuinely exists with
    complete content, never something in between.
    """


def _safe_title(title: str) -> str:
    """A filesystem-safe fragment derived from a chat title: ASCII
    letters/digits kept, every run of anything else collapsed to one `-`,
    lowercased, and trimmed of leading/trailing `-`. An all-punctuation (or
    empty) title still yields a usable, non-empty fragment rather than a
    filename that starts or ends with a bare separator.
    """
    fragment = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()
    return fragment or "chat"


def _export_filename(kind_value: str, title: str, chat_id_value: str, now) -> str:
    timestamp = now.strftime("%Y%m%dT%H%M%S")
    return f"{timestamp}-{kind_value}-{_safe_title(title)}-{chat_id_value}.md"


#: The highest numbered suffix `_reserve_destination` will try before
#: refusing — generous enough that reaching it means something is actually
#: wrong (a destination shared with another writer producing the exact same
#: name every second), not ordinary use.
_MAX_COLLISION_SUFFIX = 9999


def _claim_destination(candidate):
    """Attempts to exclusively create `candidate` as an empty placeholder
    (`os.O_CREAT | os.O_EXCL`). Returns the **open file descriptor** for
    that placeholder once this invocation genuinely owns it, or `None` if
    the name was already taken — an existing export, or a racing writer that
    claimed it first (`FileExistsError`). Any other `OSError` propagates to
    the caller.

    The descriptor is deliberately kept open rather than closed here
    (B-2.0-78): a pathname is not an ownership token. Holding the descriptor
    is what lets `_still_owns_claim` ask, at the publication boundary, whether
    the file *now* at that pathname is still the same object this invocation
    created — the one question `os.replace` on a bare pathname cannot ask.
    The caller owns closing it.
    """
    try:
        return os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return None


def _still_owns_claim(claim_fd: int, path) -> bool:
    """`True` only while `path` still names the exact filesystem object
    `claim_fd` refers to, compared by device and inode.

    `False` means another writer replaced (or removed) this invocation's
    claim after it was made — publishing onto that pathname would destroy
    their file, and cleaning it up would delete it. Both are refused instead
    (Concept.md: "A complete temporary export may replace only the final-name
    claim created for this invocation. The implementation must verify that
    ownership at the publication boundary").

    This narrows the window rather than closing it: POSIX has no portable
    "rename onto exactly this inode", so a competitor arriving between this
    check and the `os.replace` a few instructions later is still possible.
    That residual window is microseconds of a single syscall pair instead of
    the whole render-and-write span, and it is the strongest guarantee this
    module can make without a Linux-only `renameat2` dependency.
    """
    try:
        on_disk = os.stat(path)
    except OSError:
        return False
    claimed = os.fstat(claim_fd)
    return (on_disk.st_dev, on_disk.st_ino) == (claimed.st_dev, claimed.st_ino)


def _reserve_destination(directory, filename: str):
    """The final path this export will publish to plus the **open descriptor
    proving this invocation owns it** — `filename` itself if unclaimed, else
    the same stem with an advancing numeric suffix (B-2.0-78). The caller
    closes that descriptor.

    Choosing and claiming are the same atomic step — by the time this
    returns, the path already exists on disk as this invocation's own empty
    placeholder, never merely a name this invocation *intends* to use. A
    concurrent writer racing for the exact same name loses that race
    cleanly (its own `_claim_destination` call fails and it advances to its
    own next suffix) rather than either invocation's later `os.replace`
    silently overwriting the other's finished export — the gap between
    "decided" and "own it" that made the old exists()-then-write shape a
    race no longer exists. Never overwrites an existing file: a name is
    only ever claimed via `O_EXCL`, which refuses if anything is already
    there, published export or otherwise.
    """
    candidate = directory / filename
    try:
        claim_fd = _claim_destination(candidate)
        if claim_fd is not None:
            return candidate, claim_fd
        stem, suffix = candidate.stem, candidate.suffix
        for n in range(2, _MAX_COLLISION_SUFFIX + 1):
            numbered = directory / f"{stem}-{n}{suffix}"
            claim_fd = _claim_destination(numbered)
            if claim_fd is not None:
                return numbered, claim_fd
    except OSError as exc:
        raise ExportWriteFailed(
            f"cfc could not claim an export filename in {directory} ({exc.strerror})"
        ) from exc
    raise CollisionExhausted(f"could not find a free export filename in {directory}")


def validate_destination(directory):
    """`directory` (a `Path | None`, straight from `cfc.settings.
    ExportSettings.path`) if it currently resolves to an existing writable
    directory. Raises `DestinationUnusable` naming exactly why otherwise:
    unset, missing, or not a directory. Never creates it — export is never
    a reason to invent a folder cfc was not told exists.
    """
    if directory is None:
        raise DestinationUnusable("CHAT_EXPORT_DIR is not configured")
    if not directory.exists():
        raise DestinationUnusable(f"{directory} does not exist")
    if not directory.is_dir():
        raise DestinationUnusable(f"{directory} is not a directory")
    if not os.access(directory, os.W_OK):
        raise DestinationUnusable(f"{directory} is not writable")
    return directory


def _turn_status_line(turn: Turn) -> str:
    """B-2.0-79: `FailureKind.INTERRUPTED` (cfc restarted while the turn was
    active, or a live interruption ended it) gets its own `interrupted`
    status rather than being flattened into `failed` — the export contract
    distinguishes failed, cancelled, and interrupted turns, and the reason
    text already said so even while the status line did not.
    """
    if turn.outcome is None:
        return "status: active (no reply — turn was still in progress when exported)"
    if isinstance(turn.outcome, CompletedOutcome):
        return "status: completed"
    if isinstance(turn.outcome, FailedOutcome):
        if turn.outcome.evidence.kind is FailureKind.INTERRUPTED:
            return f"status: interrupted ({turn.outcome.evidence.reason})"
        return f"status: failed ({turn.outcome.evidence.reason})"
    if isinstance(turn.outcome, CancelledOutcome):
        return "status: cancelled"
    raise TypeError(f"turn {turn.id} has an unrecognised outcome type: {turn.outcome!r}")


def _usage_line(usage: Usage | None) -> str:
    if usage is None:
        return "usage: not reported"

    def one(value: int | None) -> str:
        return "not reported" if value is None else str(value)

    return (f"usage: input {one(usage.input_tokens)}, output {one(usage.output_tokens)}, "
            f"total {one(usage.total_tokens)}")


def _provenance_lines(manifest: tuple[ContextManifestEntry, ...]) -> list[str]:
    """D-2.0-75: every line here carries the same `-` marker the
    surrounding per-turn metadata (`model`, `status`, `usage`) already
    uses, and a non-empty manifest's own entries are indented two spaces
    under their own `- context:` line — one valid nested Markdown list, not
    a bare `context:` line that ended the enclosing list and started a new,
    wrongly-flat one.
    """
    if not manifest:
        return ["- context: none"]
    lines = ["- context:"]
    for entry in manifest:
        lines.append(
            f"  - {entry.category.value}: {entry.name} "
            f"({entry.character_count} chars, fingerprint {entry.fingerprint})"
        )
    return lines


def render_markdown(
    chat: Chat, opening: OpeningMessage | None, snapshot: ConversationSnapshot, *,
    exported_at=None,
) -> str:
    """The complete, literal Markdown document for one chat — exact
    metadata, the frozen opening (when present), then every stored turn in
    canonical order with its literal user/assistant content, terminal
    status, model, usage, and ordered context/attachment provenance
    (identity, size, fingerprint — never a source or attachment body).
    Deterministic given its inputs, except for `exported_at` (this module's
    own `_local_now()` when not supplied by a caller — tests pass a fixed
    value; `export_chat` always supplies one explicitly, the same instant
    its filename was built from).
    """
    exported_at = exported_at if exported_at is not None else _local_now()
    by_turn: dict[str, list[Message]] = {turn.id.value: [] for turn in snapshot.turns}
    for message in snapshot.messages:
        by_turn[message.turn_id.value].append(message)

    lines = [
        f"# cfc chat export ({EXPORT_FORMAT_VERSION})",
        "",
        f"- export time: {exported_at.isoformat()}",
        f"- chat id: {chat.id.value}",
        f"- chat kind: {chat.kind.value}",
        f"- title: {chat.title}",
        f"- created at: {chat.created_at.isoformat()}",
        f"- opening: {opening.source_name if opening is not None else 'none'}",
        "",
    ]

    if opening is not None:
        lines.append(f"## Opening ({opening.source_name})")
        lines.append("")
        lines.append(opening.content)
        lines.append("")

    for turn in snapshot.turns:
        lines.append(f"## Turn {turn.position}")
        lines.append("")
        lines.append(f"- model: {turn.model}")
        lines.append(f"- {_turn_status_line(turn)}")
        usage = turn.outcome.usage if isinstance(turn.outcome, CompletedOutcome) else None
        lines.append(f"- {_usage_line(usage)}")
        lines.extend(_provenance_lines(turn.context_manifest))
        lines.append("")
        for message in by_turn[turn.id.value]:
            speaker = "User" if message.role is Role.USER else "Assistant"
            lines.append(f"**{speaker}:**")
            lines.append("")
            lines.append(message.content)
            lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def _quietly_unlink(path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:  # noqa: BLE001 — best-effort cleanup after an already-reported failure
        pass


def export_chat(
    directory, chat: Chat, opening: OpeningMessage | None, snapshot: ConversationSnapshot, *,
    now=None,
):
    """Render `chat`'s snapshot and publish it as one new Markdown file
    under `directory`. Raises `DestinationUnusable`, `CollisionExhausted`,
    or `ExportWriteFailed`; returns the final published `Path` only once a
    complete file exists there. `now`, a timezone-aware `datetime`, is
    `_local_now()` when not supplied by a caller — tests pass a fixed value
    to prove the filename and the document metadata agree on the exact same
    instant.

    Atomic within `directory`: `_reserve_destination` exclusively claims the
    final pathname before anything is rendered and keeps the descriptor for
    that claim open (B-2.0-78), the render is written to a hidden temporary
    file, flushed and `fsync`ed, and only then — after `_still_owns_claim`
    confirms the pathname still names this invocation's own claim — published
    with one `os.replace`. A reader never observes a partial file under the
    final name; another writer who replaced the claim in the meantime gets a
    typed refusal instead of having their file overwritten, and is left
    equally untouched by failure cleanup, which removes the temporary file
    unconditionally but the final name only while it is still this
    invocation's claim. Never touches SQLite, a vault source, or an earlier
    export.
    """
    resolved_dir = validate_destination(directory)
    instant = now if now is not None else _local_now()
    filename = _export_filename(chat.kind.value, chat.title, chat.id.value, instant)
    final_path, claim_fd = _reserve_destination(resolved_dir, filename)
    temp_path = resolved_dir / f".{final_path.name}.tmp"

    try:
        try:
            body = render_markdown(chat, opening, snapshot, exported_at=instant)

            try:
                with open(temp_path, "w", encoding="utf-8") as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
            except OSError as exc:
                raise ExportWriteFailed(
                    f"cfc could not write the export into {resolved_dir} ({exc.strerror})"
                ) from exc

            if not _still_owns_claim(claim_fd, final_path):
                raise ExportWriteFailed(
                    f"another writer replaced cfc's reserved export name {final_path} "
                    f"before this export could be published; their file was left "
                    f"untouched and nothing was exported"
                )

            try:
                os.replace(temp_path, final_path)
            except OSError as exc:
                raise ExportWriteFailed(
                    f"cfc could not finish publishing the export to {final_path} "
                    f"({exc.strerror})"
                ) from exc
        except BaseException:
            _quietly_unlink(temp_path)
            #: Only ever removes this invocation's *own* claim. After a
            #: successful `os.replace` the claim inode is gone, so this is
            #: also what stops a late failure from deleting a published
            #: export — and after a competitor replaced the claim, what stops
            #: cleanup from deleting their file (B-2.0-78).
            if _still_owns_claim(claim_fd, final_path):
                _quietly_unlink(final_path)
            raise
    finally:
        os.close(claim_fd)

    return final_path
