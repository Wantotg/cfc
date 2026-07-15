#!/usr/bin/env python3
"""
backup.py — timestamped snapshots of the chat database.

    python3 backup.py                 # snapshot now (skips if nothing changed)
    python3 backup.py --force         # snapshot even if unchanged
    python3 backup.py --list          # show what's kept
    python3 backup.py --restore latest        # restore newest
    python3 backup.py --restore chat-2026...  # restore a specific one

main.py calls backup_db() on startup, throttled to once every INTERVAL_HOURS,
so ordinary use keeps a rolling history without thinking about it.

Uses SQLite's online backup API rather than copying the file. A cp of a live
database can catch a torn write mid-transaction and produce a snapshot that
looks fine and won't open; backup() takes a read lock and copies page by page.

Restores are themselves backed up first, so restoring the wrong snapshot is
recoverable rather than a second loss.
"""
import hashlib
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path.home() / ".cfc" / "chat.db"
BACKUP_DIR = Path.home() / ".cfc" / "backups"
KEEP = 10               # rolling snapshots to retain
INTERVAL_HOURS = 6      # startup backup skipped if one is newer than this
PREFIX = "chat-"
SUFFIX = ".db"


def _snapshots():
    """Newest first."""
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob(f"{PREFIX}*{SUFFIX}"),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _copy(src, dest):
    """Online backup + integrity check. Never leaves a half-written file at
    dest: writes to a temp name and renames only once verified."""
    tmp = dest.with_suffix(".partial")
    tmp.unlink(missing_ok=True)
    source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(tmp)
        try:
            source.backup(target)
            ok = target.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                raise RuntimeError(f"integrity_check said {ok!r}")
        finally:
            target.close()
    finally:
        source.close()
    tmp.replace(dest)
    return dest


def _unique(prefix):
    """A snapshot name that isn't taken. Timestamps are second-resolution, so
    two snapshots in the same second would otherwise silently overwrite one
    another — which is a backup tool quietly discarding a backup."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_DIR / f"{prefix}{stamp}{SUFFIX}"
    n = 1
    while dest.exists():
        dest = BACKUP_DIR / f"{prefix}{stamp}-{n}{SUFFIX}"
        n += 1
    return dest


def _prune():
    for old in _snapshots()[KEEP:]:
        old.unlink(missing_ok=True)


def backup_db(force=False, quiet=False):
    """Snapshot the database. Returns the path written, or None if skipped.

    Skips when the newest snapshot is both recent and identical, so starting
    cfc ten times in an afternoon doesn't cost ten copies of the same bytes.
    """
    if not DB_PATH.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    existing = _snapshots()
    if not force and existing:
        newest = existing[0]
        age = datetime.now() - datetime.fromtimestamp(newest.stat().st_mtime)
        if age < timedelta(hours=INTERVAL_HOURS):
            return None
        # Time to make one, but don't bother if nothing has changed since.
        if _digest(newest) == _digest(DB_PATH):
            os.utime(newest, None)   # reset the clock; content is current
            return None

    dest = _unique(PREFIX)
    _copy(DB_PATH, dest)
    _prune()
    if not quiet:
        mb = dest.stat().st_size / 1e6
        print(f"[backup: {dest.name} — {mb:.1f} MB]")
    return dest


def safe_backup():
    """Startup path: a failed backup must never stop cfc from opening."""
    try:
        return backup_db(quiet=True)
    except Exception as e:
        print(f"[backup failed: {e}]")
        return None


def restore(which):
    snaps = _snapshots()
    if not snaps:
        print("No snapshots to restore from."); return False
    if which == "latest":
        src = snaps[0]
    else:
        matches = [s for s in snaps if s.name == which or s.stem == which]
        if not matches:
            print(f"No snapshot named {which!r}. Try --list."); return False
        src = matches[0]

    # The current database may be the only copy of something. Keep it.
    if DB_PATH.exists():
        rescue = _unique("pre-restore-")
        _copy(DB_PATH, rescue)
        print(f"Current database saved to: {rescue.name}")

    _copy(src, DB_PATH)
    print(f"Restored {src.name} -> {DB_PATH}")
    return True


def _show(paths):
    for s in paths:
        ts = datetime.fromtimestamp(s.stat().st_mtime)
        mb = s.stat().st_size / 1e6
        print(f"  {s.name:<32} {ts:%Y-%m-%d %H:%M}  {mb:>6.1f} MB")


def _list():
    snaps = _snapshots()
    if not snaps:
        print(f"No snapshots in {BACKUP_DIR}"); return
    print(f"\n{len(snaps)} snapshot(s) in {BACKUP_DIR} "
          f"(rolling, newest {KEEP} kept):\n")
    _show(snaps)

    # Rescue copies taken before a restore. Never auto-pruned — a restore is
    # exactly when the database you overwrote might have been the only copy —
    # so they must at least be visible, and are yours to delete.
    rescues = sorted(BACKUP_DIR.glob("pre-restore-*.db"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    if rescues:
        print(f"\n{len(rescues)} pre-restore rescue copy(ies), kept "
              f"indefinitely:\n")
        _show(rescues)
    print()


def main():
    argv = sys.argv[1:]
    if "--list" in argv:
        _list(); return 0
    if "--restore" in argv:
        i = argv.index("--restore")
        if i + 1 >= len(argv):
            print("usage: backup.py --restore <latest|name>"); return 1
        return 0 if restore(argv[i + 1]) else 1
    path = backup_db(force="--force" in argv)
    if path is None:
        print("Nothing to do — newest snapshot is recent and identical.")
        print("Use --force to snapshot anyway.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
