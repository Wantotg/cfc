# pools.py — the three pools of attachable text cfc owns.
#
#     prompt   the system prompt   PROMPTS_DIR
#     persona  the persona         PERSONAS_DIR
#     trait    a trait             TRAITS_DIR
#
# All three are the same thing on disk: a folder of `.md` files, one per item,
# where **the filename is the identity**. They differ only in which directory
# they live in, how many of them a session may carry, and where they land in
# the assembled prompt — none of which is a reason for three copies of the same
# twenty lines.
#
# That duplication is what this module removes, and removing it is the reason
# `assemble.py` was extracted first: traits mirror prompts and personas
# *exactly*, so a different storage shape for traits would have reintroduced
# the duplication at the moment it was being paid off. A combined traits file
# would also need a parser, and "a format written in one place and parsed in
# another" is a named recurring hazard here with a five-row table in
# `HANDOVER.md`. One file per trait needs no parser and no id: the file is the
# id.
#
# Owns no console. Listing is rendering and lives in `commands.py`, the same
# split `wikigit.py` and `runner.py` keep.
from pathlib import Path

try:
    from config import PROMPTS_DIR
except ImportError:
    PROMPTS_DIR = ""
try:
    from config import PERSONAS_DIR
except ImportError:
    PERSONAS_DIR = ""
try:
    # Absent from an older config: traits then live under ~/.cfc/traits like
    # the other two pools do, so cfc runs and the feature is reachable without
    # editing config first.
    from config import TRAITS_DIR
except ImportError:
    TRAITS_DIR = ""


class Pool:
    """One pool's identity: where it lives and what to call it on screen.

    `plural`/`singular`/`usage` are three fields rather than one because the
    existing `:prompts` output says "prompts", "prompt files" and "system
    prompts" in three different sentences, and this module's job was to unify
    the code without changing a character of what it prints.
    """

    def __init__(self, kind, configured, default, plural, singular, usage):
        self.kind = kind
        # The single seam. Every path into this pool goes through `dir()`, so
        # pointing `configured` somewhere else re-points the whole pool — which
        # is what `tests/golden.py` does to keep its baseline off Cas's vault.
        # Patching `config` instead would miss anyone who read it at import.
        self.configured = configured
        self._default = default
        self.plural = plural
        self.singular = singular
        self.usage = usage

    def dir(self):
        # Read through the attribute rather than captured at import, so a test
        # (or a future reconfiguration) can point a pool somewhere else without
        # the value having been frozen by whoever imported first.
        return (Path(self.configured).expanduser() if self.configured
                else self._default())


POOLS = {
    "prompt": Pool(
        "prompt", PROMPTS_DIR, lambda: Path.home() / ".cfc" / "prompts",
        "prompts", "prompt", "system prompts"),
    "persona": Pool(
        "persona", PERSONAS_DIR, lambda: Path.home() / ".cfc" / "personas",
        "personas", "persona", "personas"),
    "trait": Pool(
        "trait", TRAITS_DIR, lambda: Path.home() / ".cfc" / "traits",
        "traits", "trait", "traits"),
}

# Bare-name resolution order for `/add` and `/remove`: a name that exists in
# more than one pool fills the highest-priority one that isn't already carrying
# it. **This is not the assembly order** — `assemble.py` owns that. The two
# sequences agree today and are still two decisions; see the note there.
PRIORITY = ("prompt", "persona", "trait")


def pool(kind):
    """The Pool for a kind, or None. Accepts the plural too, since `/list
    traits` and `/add trait x` are the same word to everyone but the code."""
    kind = (kind or "").strip().lower()
    if kind in POOLS:
        return POOLS[kind]
    for p in POOLS.values():
        if kind == p.plural:
            return p
    return None


def pool_dir(kind):
    p = pool(kind)
    return p.dir() if p else None


def names(kind):
    """Every item in a pool, by filename stem, sorted. `[]` if the folder
    isn't there — an unconfigured pool is empty, not an error."""
    d = pool_dir(kind)
    if not d or not d.is_dir():
        return []
    return sorted(f.stem for f in d.glob("*.md"))


def bodies(kind, names):
    """The bodies for a list of names, in the order given.

    A name whose file has gone is **skipped, not reported here.** The session
    stores names and re-reads bodies every turn precisely so a file can be
    edited underneath it; the cost is that a rename or delete leaves a session
    carrying a name with nothing behind it. That is a fact about the session,
    so it is `/status`'s job to show it — printing a warning on every turn
    would put the same line in front of every message for as long as the name
    stays attached, which is how a real signal gets trained out.
    """
    out = []
    for n in names or []:
        body, _ = load(kind, n)
        if body:
            out.append(body)
    return out


def load(kind, name):
    """`(body, filename)` for one item, or `(None, None)`.

    `.md` is tried first but never assumed — the same rule
    `routines.prompt_candidates` follows, and for the same reason: these files
    are authored in Obsidian, where a name arrives without its extension, but
    a file genuinely named something else must still load.
    """
    d = pool_dir(kind)
    if not d:
        return None, None
    d.mkdir(parents=True, exist_ok=True)
    name = (name or "").strip()
    if not name:
        return None, None
    candidates = ([d / name] if name.endswith(".md")
                  else [d / f"{name}.md", d / name])
    for path in candidates:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip(), path.name
    return None, None
