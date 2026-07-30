# notes.py — the notes inbox: one-level inventory and a human-declared batch
# clearing.
#
# `00 inbox/notes` is where Cas drops raw material for the memory routines to
# read. Nothing removes a note once a routine has processed it (`D-02`), so
# the folder grows without bound and every run re-reads material it has
# already written up. The fix Cas chose is a human command, `/clear notes`,
# not an automatic post-run move — more than one routine reads this folder,
# so "covered by that run" is not a claim any single run can make, and the
# first routine to finish would move notes the second hasn't read yet. By the
# time a human types the command, the loop and the script have already dealt
# with the outbox, so nothing is still owed the notes.
#
# This module owns the notes inbox and the cleared-notes archive the same way
# mover.py owns the outbox: validation, inventory, and the move — never the
# prompts or the rendering, which stay in commands.py.
import datetime
from pathlib import Path

from mover import move_roots
from paths import PathError, path_guard

# The backstage convention this module knows about: a template file dropped
# in the inbox as an example for a human to copy, never a note itself. Name-
# based, the same shape as mover.is_reserved and for the same reason: a
# malformed *note* must stay visible and countable, so this can't be "doesn't
# look like a note" — it has to name the one specific file that isn't one.
TEMPLATE_NAME = "note template.md"


class NotesError(Exception):
    """The notes inbox or archive cannot be reached. Carries the reason shown
    to the human."""


def _cfg(key, default=None):
    try:
        import config
        return getattr(config, key, default)
    except ImportError:
        return default


def notes_dir():
    """The guarded notes inbox, or None if it cannot be reached —
    unconfigured, missing, not a directory, outside the allowed vault roots
    (`MOVE_ROOTS`, shared with mover.py rather than redefined here), or
    reached through an escaping symlink."""
    raw = _cfg("NOTES_DIR", "")
    if not raw:
        return None
    try:
        d = path_guard(Path(raw).expanduser(), move_roots())
    except PathError:
        return None
    return d if d.is_dir() else None


def archive_dir():
    """The guarded cleared-notes archive root, or None. Existence is not
    required here — a batch folder is created under it on the first clear —
    only that it is configured and contained."""
    raw = _cfg("NOTES_ARCHIVE_DIR", "")
    if not raw:
        return None
    try:
        return path_guard(Path(raw).expanduser(), move_roots())
    except PathError:
        return None


def inventory():
    """(files, has_subfolder) — the regular files directly inside the notes
    inbox, template excluded, sorted by name.

    (None, False) means unavailable: unconfigured, missing, outside the
    allowed roots, or unreadable. Kept apart from an empty list on purpose —
    zero notes is a truthful state a bare inbox can be in; unavailable is a
    different one, and /status must not report one as the other.
    """
    d = notes_dir()
    if d is None:
        return None, False
    try:
        entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return None, False
    files, has_sub = [], False
    for e in entries:
        try:
            if e.is_dir():
                has_sub = True
                continue
            if not e.is_file():
                continue
        except OSError:
            continue
        if e.name == TEMPLATE_NAME:
            continue
        files.append(e)
    return files, has_sub


def _batch_dir(root, when):
    """A fresh, uniquely-named folder under `root` for one clearing. Bumped
    on collision so two clears in the same second can't land in one folder —
    the same idea as mover._gen_wiki_id, applied to a folder name."""
    stamp = when.strftime("%Y%m%d-%H%M%S")
    candidate = root / stamp
    n = 1
    while candidate.exists():
        n += 1
        candidate = root / f"{stamp}-{n}"
    return candidate


def clear_batch(files, when=None):
    """Move exactly `files` into one new batch folder under the archive.

    Re-validates the inbox and archive, and each file, at the moment of the
    move — the list handed in may be the preview the human read a moment ago,
    and only what is *displayed* ever moves: a note that appears after the
    preview stays in the inbox for the next batch, because this never re-reads
    the folder itself.

    Moves what it can and reports successes and failures separately rather
    than claiming the whole batch completed; a failure partway through never
    triggers a rollback, because a rollback can itself fail and turn one
    visible partial move into an uncertain one — the same reasoning `commit()`
    in mover.py follows for a single file, applied to a batch.

    Returns (moved_names, failed_names, batch_dir). Raises NotesError before
    anything moves if the inbox or archive cannot be reached at all.
    """
    when = when or datetime.datetime.now()
    d = notes_dir()
    if d is None:
        raise NotesError("the notes inbox is unavailable")
    archive = archive_dir()
    if archive is None:
        raise NotesError("the cleared-notes archive is unavailable")

    try:
        archive.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise NotesError(f"cannot create the archive root: {e}")
    batch = _batch_dir(archive, when)
    try:
        batch.mkdir(parents=True)
    except OSError as e:
        raise NotesError(f"cannot create the batch folder: {e}")

    moved, failed = [], []
    for f in files:
        name = f.name
        source = d / name
        try:
            still_there = source.is_file() and name != TEMPLATE_NAME
        except OSError:
            still_there = False
        if not still_there:
            failed.append(name)
            continue
        target = batch / name
        try:
            target = path_guard(target, (archive,))
        except PathError:
            failed.append(name)
            continue
        try:
            # A byte copy, not a text read/write — a note need not be
            # markdown or valid UTF-8 to be movable. Write-target-first,
            # source-remove-second: a crash in between leaves both copies,
            # recoverable, rather than neither.
            tmp = target.with_name(f".{target.name}.tmp")
            tmp.write_bytes(source.read_bytes())
            tmp.replace(target)
            source.unlink()
            moved.append(name)
        except OSError:
            failed.append(name)
    return moved, failed, batch
