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

# Aliased: this module already defines a function called `names()` (below),
# which would otherwise rebind this import the moment that def executes —
# a plain `import names` would silently stop being the module by the time
# `load()` runs.
import names as _names

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
try:
    from config import FIRST_MESSAGES_DIR
except ImportError:
    FIRST_MESSAGES_DIR = ""


class Pool:
    """One pool's identity: where it lives and what to call it on screen.

    `plural`/`singular`/`usage` are three fields rather than one because the
    existing `:prompts` output says "prompts", "prompt files" and "system
    prompts" in three different sentences, and this module's job was to unify
    the code without changing a character of what it prints.
    """

    def __init__(self, kind, configured, default, plural, singular, usage,
                 label):
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
        # What an attach or detach calls this pool back to the user: "added
        # Relaxed — Trait". On a partial or a case-fold the report *is* how you
        # learn what happened, so it names the pool as well as the item.
        self.label = label

    def dir(self):
        # Read through the attribute rather than captured at import, so a test
        # (or a future reconfiguration) can point a pool somewhere else without
        # the value having been frozen by whoever imported first.
        return (Path(self.configured).expanduser() if self.configured
                else self._default())


POOLS = {
    "prompt": Pool(
        "prompt", PROMPTS_DIR, lambda: Path.home() / ".cfc" / "prompts",
        "prompts", "prompt", "system prompts", "System prompt"),
    "persona": Pool(
        "persona", PERSONAS_DIR, lambda: Path.home() / ".cfc" / "personas",
        "personas", "persona", "personas", "Persona"),
    "trait": Pool(
        "trait", TRAITS_DIR, lambda: Path.home() / ".cfc" / "traits",
        "traits", "trait", "traits", "Trait"),
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


# --- Resolving a name ---
#
# One resolver, shared by `/add` and `/remove`. The routine loader is the
# precedent (id → display name → slug, first hit wins) and it works, so this
# extends the idea rather than inventing a second dialect: try the strongest
# form first, and only widen when it finds nothing.
#
# The rule that keeps it honest is that **it never judges under ambiguity**. If
# two things match equally well the caller is handed both and asks; a resolver
# that picked one would be making a guess the user cannot see, which is the same
# failure the retrieval floor is set to avoid.

TIERS = ("exact", "prefix", "substring")

# `#n` is how an attachment is referred to everywhere in the surface
# (`/remove #1`), so a pool item whose name contains `#` would be typeable only
# by accident. It is refused rather than escaped: the namespace is worth more
# than the one file that wanted the character.
BAD_NAME_CHARS = "#"


def bad_name_reason(name):
    """Why this item can't be attached by name, or None.

    Reported where the pool is *listed*, not swallowed — a file sitting in the
    folder and never resolving, with nothing said, is the silent-failure shape
    this codebase keeps flagging.
    """
    bad = [c for c in BAD_NAME_CHARS if c in (name or "")]
    if bad:
        return (f"'{bad[0]}' is reserved — it is the attachment namespace "
                f"(#1, #2). Rename the file.")
    return None


def _tier(query, name):
    """How well `name` matches `query`, or None. Case-insensitive, always —
    these are filenames in an Obsidian vault, where capitalisation is a
    display choice nobody should have to reproduce at a prompt."""
    q, n = query.strip().lower(), name.lower()
    if not q:
        return None
    if q == n:
        return "exact"
    if n.startswith(q):
        return "prefix"
    if q in n:
        return "substring"
    return None


def _best(query, pairs):
    """The `(kind, name)` pairs matching `query` at the strongest tier that
    found anything.

    Tiers don't mix: an exact hit means near-misses are not offered, so typing
    a name in full always does what it says even when it is a prefix of three
    other names. Order is preserved from `pairs` — pool priority, then
    alphabetical — which is the order they are numbered in if the caller asks.
    """
    hits = {t: [] for t in TIERS}
    for kind, name in pairs:
        t = _tier(query, name)
        if t and not bad_name_reason(name):
            hits[t].append((kind, name))
    for t in TIERS:
        if hits[t]:
            return hits[t]
    return []


def match(query, kinds=None):
    """Matches among everything the pools *hold*. What `/add` searches."""
    kinds = tuple(kinds) if kinds else PRIORITY
    return _best(query, [(k, n) for k in kinds for n in names(k)])


def stem(name):
    """A pool item's name, however it was stored.

    `sessions.system_prompt_name` holds the **filename** (`relax.md`) because
    that is what it has always held and the hub's columns render it; a pool
    resolves by **stem** (`relax`). Those two are compared constantly — the
    collision walk is exactly "is this pool already carrying that name" — so
    they are normalised in one place rather than at each comparison. Doing it
    per call site is how the walk silently stops advancing, which it did.
    """
    n = (name or "").strip()
    return n[:-3] if n.lower().endswith(".md") else n


def active_layers(active, kinds=None):
    """`(kind, name)` for everything currently attached, in priority order.

    `active` maps kind → a name (the singular pools) or a list of names
    (traits). Flattening it here means `/remove`, `/status` and the resolver
    all read the session's layers through one shape instead of each knowing
    which pools are singular. Names come back as stems — see `stem`.
    """
    kinds = tuple(kinds) if kinds else PRIORITY
    out = []
    for kind in kinds:
        carried = (active or {}).get(kind)
        if not carried:
            continue
        for name in ([carried] if isinstance(carried, str) else carried):
            out.append((kind, stem(name)))
    return out


def match_active(query, active, kinds=None):
    """Matches among what the session is *carrying*. What `/remove` searches.

    Deliberately not the same set as `match`: removing is about detaching
    something that is on, so a query that names a real prompt you never
    attached must fail rather than silently doing nothing. Same tier rules, so
    a partial peels a layer exactly as a partial attached it.
    """
    return _best(query, active_layers(active, kinds))


def fill(matches, active):
    """Which pool a resolved name should fill, given what is already attached.

    `active` maps kind → the name(s) that pool currently carries. When a name
    exists in more than one pool, the highest-priority pool that isn't already
    carrying it wins — so repeating `/add relax` walks down the pools instead
    of doing nothing twice. That walk is emergent rather than designed: it is
    allowed to work, and it is not advertised.

    Returns `(kind, name)`, or None if `matches` is empty. Callers pass
    matches that already share one name; several *names* is ambiguity, which
    is the caller's to ask about, not this function's to resolve.
    """
    if not matches:
        return None
    carried = dict()
    for kind, name in active_layers(active):
        carried.setdefault(kind, []).append(name)
    for kind, name in matches:
        if stem(name) not in carried.get(kind, []):
            return kind, name
    return matches[0]


def tried(query):
    """What a failed lookup looked for, for the message that says so.

    A failure has to distinguish "you typed it wrong" from "the thing is
    broken", which means naming the forms and the pools searched — the same
    reason `Routine.validate()` lists every candidate it tried.
    """
    counts = ", ".join(
        f"{len(names(k))} {POOLS[k].plural if len(names(k)) != 1 else POOLS[k].singular}"
        for k in PRIORITY)
    return (f"no exact, prefix or substring match for '{query.strip()}' "
            f"in {counts}")


def bodies(kind, wanted):
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
    for n in wanted or []:
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
            body = path.read_text(encoding="utf-8").strip()
            return _names.apply(body), path.name
    return None, None


# --- First Message: a persona's optional frozen opening -------------------
#
# Not a fourth pool. It isn't attachable, has no listing of its own and no
# separate name to keep in step — a persona's own filename is its whole
# identity here too. Kept in this module anyway because it is the same shape
# as the three pools above (a folder of .md files, filename is the key) and
# because `stem()` is what both need to compare a stored `persona_name`
# ("muse.md") against a bare query.


def first_messages_dir():
    """Where a persona's frozen opening lives, one .md per persona filename."""
    return (Path(FIRST_MESSAGES_DIR).expanduser() if FIRST_MESSAGES_DIR
            else Path.home() / ".cfc" / "first_messages")


class FirstMessageError(Exception):
    """The folder or the matching file exists but couldn't be read.

    Kept distinct from "no companion for this persona" (a plain `None`
    return) on purpose — Concept.md names this failure mode directly:
    optional and broken must never look identical.
    """


# The four states a persona's companion can be in. Named rather than left as
# bare strings so `/status` (commands.py) and this module agree on the same
# four words instead of each spelling them out.
FM_NO_DIR = "no_dir"     # the First Message directory itself doesn't exist
FM_NONE = "none"         # the directory exists; this persona has no companion
FM_OK = "ok"             # a readable companion file
FM_BROKEN = "broken"     # something is there and reading it failed


def _first_message_lookup(persona_name):
    """Where a persona's companion file would be, and what state it's in.

    The one seam behind both `load_first_message` (session-open behaviour)
    and `first_message_status` (`/status`) — one filename-matching
    implementation rather than two that can drift apart, and the reason
    `/status` doesn't reimplement this lookup itself.

    Returns `(state, path_or_None, detail_or_None)`. `detail` is only set
    for `FM_BROKEN`, and is the same message `load_first_message` used to
    raise verbatim.
    """
    name = stem(persona_name or "")
    if not name:
        return FM_NONE, None, None
    d = first_messages_dir()
    try:
        is_dir = d.is_dir()
    except OSError as e:
        return FM_BROKEN, None, f"can't read {d}: {e}"
    if not is_dir:
        return FM_NO_DIR, None, None
    path = d / f"{name}.md"
    if not path.exists():
        return FM_NONE, None, None
    if not path.is_file():
        # Something is there and it isn't a file — a directory sitting where
        # the companion should be, say. Absent and broken must not read the
        # same: a missing companion is silent, this is not.
        return FM_BROKEN, path, f"{path} is not a file"
    return FM_OK, path, None


def load_first_message(persona_name):
    """The opening text for a persona's filename, or None if it has no
    companion. Raises FirstMessageError for anything that reads as broken —
    an unreadable directory or an unreadable file — rather than returning
    the same None a missing companion does.
    """
    state, path, detail = _first_message_lookup(persona_name)
    if state == FM_BROKEN:
        raise FirstMessageError(detail)
    if state != FM_OK:
        return None
    try:
        return _names.apply(path.read_text(encoding="utf-8").strip())
    except OSError as e:
        raise FirstMessageError(f"can't read {path}: {e}") from e


def first_message_status(persona_name):
    """`(state, detail)` for `/status`: one of `FM_NO_DIR`/`FM_NONE`/`FM_OK`/
    `FM_BROKEN`, `detail` set only for `FM_BROKEN`. Doesn't read the
    companion's contents — naming the state is all `/status` needs;
    `load_first_message` is what actually loads it.
    """
    state, _path, detail = _first_message_lookup(persona_name)
    return state, detail
