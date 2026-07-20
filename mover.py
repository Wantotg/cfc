# mover.py — filing a proposed file out of the outbox.
#
# The model writes into `99 outbox` and puts a suggested `destination:` in the
# frontmatter. This module reads that suggestion, re-validates it from scratch,
# and moves the file — or refuses.
#
# Three properties, and they are the entire point of the module:
#
#   1. **The suggested destination is data, not authority.** It arrives as text
#      written by a model and is re-validated here exactly as if a stranger had
#      typed it. Same shape as the read jail: never act on the model's say-so.
#
#   2. **The move is not an LLM task.** It has a correct answer, so it is code:
#      deterministic, auditable, free. Use a model for judgement under
#      ambiguity (what to write, roughly where it belongs); use code for
#      anything with a right answer.
#
#   3. **A destination outside the roots is refused, not guessed at.** No
#      "closest match", no falling back to a default folder. A silently-wrong
#      path is worse than an error, because nobody re-reads a file that was
#      filed successfully.
#
# Note the asymmetry that makes this safe: **the mover may write outside
# WRITE_ROOTS, because the mover is not the model.** It validates against its
# own `MOVE_ROOTS`. Do not widen `WRITE_ROOTS` to achieve the same thing — that
# would hand the model the reach that is deliberately reserved for this
# separate, human-triggered step.
import datetime
import os
import shutil
from pathlib import Path

import yaml

from paths import PathError, denial_reason, path_guard

DEST_KEY = "destination"


class MoveError(Exception):
    """A proposal cannot be filed. Carries the reason shown to the human."""


def _cfg(key, default=None):
    try:
        import config
        return getattr(config, key, default)
    except ImportError:
        return default


def move_roots():
    roots = _cfg("MOVE_ROOTS", ()) or ()
    return tuple(Path(r).expanduser().resolve() for r in roots)


def outbox_roots():
    """The outbox — where proposals come FROM. This is WRITE_ROOTS."""
    roots = _cfg("WRITE_ROOTS", ()) or ()
    return tuple(Path(r).expanduser().resolve() for r in roots)


def wiki_dir():
    d = _cfg("WIKI_DIR", "")
    return Path(d).expanduser().resolve() if d else None


def split_frontmatter(text):
    """(frontmatter_dict, body, raw_fm_text). ({}, text, '') if there is none."""
    if not text.startswith("---"):
        return {}, text, ""
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text, ""
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}, text, ""
    if not isinstance(fm, dict):
        return {}, text, ""
    return fm, parts[2].lstrip("\n"), parts[1]


def strip_destination(text):
    """The file's content with `destination:` removed from its frontmatter.

    The suggestion has been carried out, so leaving it behind would leave a
    stale instruction in a filed document — and one that a later sweep could
    act on a second time. Everything else in the frontmatter is preserved:
    this is the user's content, and the mover is not an editor.
    """
    fm, body, _ = split_frontmatter(text)
    if DEST_KEY not in fm:
        return text
    fm.pop(DEST_KEY)
    if not fm:
        return body
    dumped = yaml.safe_dump(fm, default_flow_style=False, allow_unicode=True,
                            sort_keys=False)
    return f"---\n{dumped}---\n\n{body}"


class Proposal:
    """One file sitting in the outbox, with its verdict already computed.

    `ok` is False for anything that cannot be filed — no destination, outside
    the roots, wiki, target exists. `reason` says which, in the words shown to
    the human. Computing the verdict at list time is deliberate: ':outbox'
    should show you what will happen *before* you type ':file 1'.
    """

    def __init__(self, path, destination=None, target=None, ok=False,
                 reason=""):
        self.path = path
        self.destination = destination
        self.target = target
        self.ok = ok
        self.reason = reason

    @property
    def name(self):
        return self.path.name

    def __repr__(self):
        return f"<Proposal {self.name} ok={self.ok} {self.reason}>"


def _resolve_destination(raw, source):
    """Turn a suggested destination into a target file path, or raise.

    Accepts an absolute path, or one relative to a move root (the natural way
    to write it: "02 areas/daily/"). A destination naming a directory keeps the
    source filename; one naming a file renames as it moves.
    """
    roots = move_roots()
    if not roots:
        raise MoveError("no MOVE_ROOTS configured — filing is disabled")

    candidate = Path(str(raw).strip()).expanduser()
    tries = [candidate] if candidate.is_absolute() else \
            [root / candidate for root in roots]

    # A relative destination is tried against each root; the first that lands
    # inside one wins. Ambiguity is not possible in practice (one root here),
    # and with several the first match is the documented rule rather than a
    # guess about intent.
    last = None
    for t in tries:
        try:
            resolved = path_guard(t, roots)
        except PathError as e:
            last = e
            continue

        if resolved.is_dir() or str(raw).endswith(("/", "\\")):
            resolved = resolved / source.name

        # Re-guard after appending the filename: the directory passing says
        # nothing about the final path, and the deny list has to see the name
        # that will actually exist on disk.
        try:
            return path_guard(resolved, roots)
        except PathError as e:
            raise MoveError(str(e))

    raise MoveError(str(last) if last else f"cannot resolve destination {raw!r}")


def _reject_wiki(target):
    """Refuse a destination inside the wiki corpus.

    Standing decision: writing a page there changes the corpus, but the index
    does not know until import_wiki.py runs — so recall keeps answering from a
    stale copy **with no signal that it is stale**. Enforced here rather than
    trusted to a habit, because the failure is silent and arrives weeks later.
    """
    wiki = wiki_dir()
    if wiki and (target == wiki or wiki in target.parents):
        raise MoveError(
            f"wiki destinations are refused ({wiki.name}/) — pages enter "
            "through import_wiki.py so the recall index cannot go stale"
        )


def plan(source):
    """Read one outbox file and decide what would happen. Never raises."""
    source = Path(source)
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return Proposal(source, reason=f"unreadable: {e}")

    fm, _, _ = split_frontmatter(text)
    raw = fm.get(DEST_KEY)
    if not raw:
        return Proposal(source, reason="no destination")

    try:
        target = _resolve_destination(raw, source)
        _reject_wiki(target)
    except MoveError as e:
        return Proposal(source, destination=str(raw), reason=str(e))

    why = denial_reason(target)
    if why:
        return Proposal(source, destination=str(raw), target=target,
                        reason=why)
    if target.exists():
        return Proposal(source, destination=str(raw), target=target,
                        reason=f"target exists: {target}")
    if target == source.resolve():
        return Proposal(source, destination=str(raw), target=target,
                        reason="destination is the file itself")

    return Proposal(source, destination=str(raw), target=target, ok=True,
                    reason="")


def list_proposals():
    """Every *.md in the outbox, with its verdict. Sorted by name.

    The run logs live in a subfolder and are not proposals — only top-level
    files are considered, the same shape as the wiki importer's "top-level
    *.md only" rule.
    """
    out = []
    for root in outbox_roots():
        if not root.is_dir():
            continue
        for f in sorted(root.glob("*.md")):
            out.append(plan(f))
    return out


def commit(proposal):
    """Carry out a planned move. Returns the target path.

    Order matters: the content is written to the target and only then is the
    source removed. A crash in between leaves **both** copies, which is
    recoverable by hand; the reverse order can lose the file outright. The
    write itself is a temp file + os.replace, like every other write here.
    """
    if not proposal.ok:
        raise MoveError(proposal.reason or "proposal is not filable")

    source, target = proposal.path, proposal.target

    # Re-validate at the moment of the move, not just at plan time. The plan
    # may be minutes old and the human has been looking at a list; nothing
    # guarantees the tree hasn't changed under it. This is the check that
    # actually guards the write.
    fresh = plan(source)
    if not fresh.ok or fresh.target != target:
        raise MoveError(fresh.reason or "the proposal changed since it was listed")

    target.parent.mkdir(parents=True, exist_ok=True)
    text = strip_destination(source.read_text(encoding="utf-8"))

    tmp = target.with_name(f".{target.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    source.unlink()
    return target


def drop(proposal, trash_dir=None):
    """Discard a proposal instead of filing it.

    Moved aside rather than deleted. 'Reject this draft' and 'destroy this
    draft' are different intentions, and only one of them is recoverable at
    3am when it turns out the draft was the good one.
    """
    source = Path(proposal.path)
    trash = Path(trash_dir) if trash_dir else source.parent / "dropped"
    trash.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = trash / f"{stamp}-{source.name}"
    shutil.move(str(source), str(target))
    return target
