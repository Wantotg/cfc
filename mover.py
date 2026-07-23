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

# A file dropped in this subfolder of the outbox is a *wiki* proposal: its
# destination is implicitly the wiki corpus, so the reader routine doesn't need
# to write a `destination:` at all — the folder is the signal. Everything else
# (notes/, routine logs/, tiered memory/, dropped/) stays out of the proposal
# list, same as the top-level "*.md only" rule.
WIKI_SUBFOLDER = "wiki"

# Wiki pages are keyed by a stable frontmatter id and named <id>.md on disk (see
# import_wiki.py and the wiki index's [[20260719160004|Title]] links). A page
# entering the wiki *must* carry one, or import_wiki silently skips it — the
# exact silent staleness the old outright refusal existed to prevent. Rather
# than refuse a draft that has no id (a dead end), filing STAMPS one: code
# assigns it at approval time, so it is never the model's job to invent a unique
# key. YYYYMMDDhhmmss is unique enough for one personal vault; the monotonic
# bump below guarantees a `:file all` batch filed in the same second can't
# collide (which would make import_wiki treat two pages as one).
_last_wiki_id = 0


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


def _wiki_proposal_dirs():
    """The `wiki/` subfolder of each outbox root, where it exists."""
    out = []
    for root in outbox_roots():
        wd = root / WIKI_SUBFOLDER
        if wd.is_dir():
            out.append(wd)
    return out


def _from_wiki_dir(source):
    """True if `source` sits directly in an outbox `wiki/` proposal folder."""
    try:
        parent = Path(source).resolve().parent
    except OSError:
        return False
    for wd in _wiki_proposal_dirs():
        try:
            if wd.resolve() == parent:
                return True
        except OSError:
            continue
    return False


def _gen_wiki_id():
    """A unique YYYYMMDDhhmmss id, monotonic so a same-second batch can't clash.

    On a collision the integer is bumped by one. That can read as a nonsense
    time (…6001), but the id is an opaque key everywhere it is used — the
    filename and import_wiki's lookup — never parsed as a date, so uniqueness is
    the only property that matters.
    """
    global _last_wiki_id
    now = int(datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
    if now <= _last_wiki_id:
        now = _last_wiki_id + 1
    _last_wiki_id = now
    return f"{now:014d}"


def _ensure_id(text, wid):
    """Return (text_with_id, id). If the frontmatter already names an id, keep
    it and ignore `wid`; otherwise stamp `wid` in as the first key."""
    fm, body, _ = split_frontmatter(text)
    existing = fm.get("id")
    if existing:
        return text, str(existing)
    # The id line is written by hand, not via yaml.safe_dump, which would quote
    # a pure-digit string (`id: '2026…'`). The vault's pages use it unquoted
    # (`id: 20260719160004`) and the wiki index links to it that way; keep the
    # convention. import_wiki str()s it either way, so this is cosmetic on the
    # read side but load-bearing for a consistent-looking corpus.
    rest = ""
    if fm:
        rest = yaml.safe_dump(fm, default_flow_style=False, allow_unicode=True,
                              sort_keys=False)
    return f"---\nid: {wid}\n{rest}---\n\n{body}", wid


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
                 reason="", into_wiki=False, wiki_id=None, needs_id=False):
        self.path = path
        self.destination = destination
        self.target = target
        self.ok = ok
        self.reason = reason
        # into_wiki: this lands in the wiki corpus, so filing it must also flag
        # the recall index stale (the caller does that; the mover only moves).
        # needs_id: no frontmatter id yet — one is stamped at commit time, so
        # `target` is not knowable until then and stays None here.
        self.into_wiki = into_wiki
        self.wiki_id = wiki_id
        self.needs_id = needs_id

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


def _into_wiki(target):
    """True if `target` resolves inside the wiki corpus."""
    wiki = wiki_dir()
    return bool(wiki and (target == wiki or wiki in target.parents))


def _plan_wiki(source, fm, raw):
    """Verdict for a page bound for the wiki corpus.

    The old code refused these outright, because a page landing in the corpus
    while the index is unaware makes recall answer from a stale copy with no
    signal — and that failure is silent and arrives weeks later. v0.6 resolves
    it rather than deleting the guard: the move is allowed, filing flags the
    index stale (loudly, one command to fix), and the id requirement that
    import_wiki has is met by *stamping* one at approval time instead of
    trusting the draft to carry it.
    """
    wiki = wiki_dir()
    if not wiki:
        return Proposal(source, reason="no WIKI_DIR configured — cannot file "
                        "into the wiki")
    dest = str(raw) if raw else "wiki db"
    wid = fm.get("id")
    wid = str(wid) if wid else None

    if wid:
        target = wiki / f"{wid}.md"
        why = denial_reason(target)
        if why:
            return Proposal(source, destination=dest, target=target,
                            into_wiki=True, wiki_id=wid, reason=why)
        # A page whose id already exists is an *edit* — that belongs in the
        # vault, then a re-import, not a second file the mover would clobber.
        if target.exists():
            return Proposal(source, destination=dest, target=target,
                            into_wiki=True, wiki_id=wid,
                            reason=f"a wiki page with id {wid} already exists "
                            "— edit it in the vault, don't re-file it")
        return Proposal(source, destination=dest, target=target, ok=True,
                        into_wiki=True, wiki_id=wid)

    # No id yet: one is stamped at commit time, so the final <id>.md name isn't
    # knowable now. That is a filable proposal, not a refusal.
    return Proposal(source, destination=dest, target=None, ok=True,
                    into_wiki=True, wiki_id=None, needs_id=True)


def plan(source):
    """Read one outbox file and decide what would happen. Never raises."""
    source = Path(source)
    try:
        text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return Proposal(source, reason=f"unreadable: {e}")

    fm, _, _ = split_frontmatter(text)
    raw = fm.get(DEST_KEY)

    # A file in the outbox `wiki/` subfolder is wiki-bound by location; it needs
    # no `destination:` key. A top-level file still declares its destination,
    # and that destination may now point into the wiki too.
    if _from_wiki_dir(source):
        return _plan_wiki(source, fm, raw)
    if not raw:
        return Proposal(source, reason="no destination")

    try:
        target = _resolve_destination(raw, source)
    except MoveError as e:
        return Proposal(source, destination=str(raw), reason=str(e))

    if _into_wiki(target):
        return _plan_wiki(source, fm, raw)

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
    # The wiki proposal subfolder is a second, explicit source — its pages are
    # what the reader routine drafts. Everything else under the outbox stays
    # out, same as the top-level rule.
    for wd in _wiki_proposal_dirs():
        for f in sorted(wd.glob("*.md")):
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

    if proposal.into_wiki:
        return _commit_wiki(proposal)

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


def _commit_wiki(proposal):
    """File a page into the wiki corpus, stamping an id if it has none.

    The id is assigned here, by code, at approval time — never by the model.
    Re-planning is still the guard: the source is re-read so an id added in the
    vault since listing is honoured, and a page whose id now exists is refused
    rather than clobbered. The <id>.md filename matches the vault's convention
    and is what the wiki index links to.
    """
    source = Path(proposal.path)
    fresh = plan(source)
    if not fresh.ok or not fresh.into_wiki:
        raise MoveError(fresh.reason or "the proposal changed since it was listed")

    wid = fresh.wiki_id or _gen_wiki_id()
    wiki = wiki_dir()
    if not wiki:
        raise MoveError("no WIKI_DIR configured")
    target = path_guard(wiki / f"{wid}.md", move_roots())
    if target.exists():
        raise MoveError(f"a wiki page with id {wid} already exists")

    text = strip_destination(source.read_text(encoding="utf-8"))
    text, wid = _ensure_id(text, wid)

    target.parent.mkdir(parents=True, exist_ok=True)
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
