# parse.py — the command line grammar.
#
# One place decides what a typed line means. Everything downstream reads a
# `Cmd`; nothing else in the codebase looks at the prefix character or splits a
# command line for itself.
#
#     <prefix>verb [kind] [target] [message]
#
# `kind` and `target` are ordinary positional tokens — the parser does not know
# which commands take which, because that is the handler's business. What the
# parser owns is the *shape*: which verb, what the tokens are, and where the
# greedy free-text tail starts. `message` is always last and always the rest of
# the line, so `tail()` is the only thing that needs the raw string.
#
# Why this exists at all: dispatch used to be a chain of
# `user.startswith(":foo")` tests, which is order-dependent in a way nothing
# declares. `":attached".startswith(":attach")` is true, so `:attached` had to
# be tested *before* `:attach` or it read as attaching a file called "ed" —
# a trap fixed by a comment rather than structurally, and one that comes back
# every time a command is added whose name prefixes another. Exact verb
# matching cannot have that bug.
from dataclasses import dataclass

# The command prefix. It is one constant on purpose: flipping it in v0.8 was a
# change to the grammar and not to a single handler.
#
# `LEGACY_PREFIX` is accepted for one version and then removed. A `:` command
# still runs, and `Cmd.legacy` tells the REPL to say so — once per session, not
# once per command, because a correction repeated forty times is one that stops
# being read. Self-removing rather than an undocumented dialect kept alive
# forever: delete the constant and `:add` becomes ordinary prose again.
PREFIX = "/"
LEGACY_PREFIX = ":"

# Typed verb → canonical verb. Kept here rather than in the dispatch table so
# completion and dispatch agree on the whole surface by construction; two lists
# of aliases is how one of them goes stale.
ALIASES = {
    "h": "help",
    "?": "help",
    "db": "database",
    # A plural the hand types by reflex, because the command lists several of
    # them. Worth a line here rather than nothing: an unrecognised verb is not
    # an error, it falls through to the model (see run_session), so `/routines`
    # cost an API call and a confused answer about routines. The other verbs
    # were checked for the same trap — the rest of the plurals people reach for
    # (`prompts`, `models`, `tags`) are already caught by RETIRED.
    "routines": "routine",
}


# The whole surface, in the order `/help` groups them. This is the canonical
# list: `main.py` asserts its handler table matches, so a verb added to one and
# not the other fails at import rather than at the moment someone types it.
# Three lists that have to agree (the table, this, and `RETIRED`) is exactly the
# drift `HANDOVER.md` names as a recurring hazard — so they are checked, not
# maintained by hand.
VERBS = (
    "help", "list", "status", "config", "search",     # ask
    "add", "remove",                                  # context
    "delete",                                         # destroy
    "export",                                         # data
    "recall", "remember", "update",                   # memory
    "new", "q", "title",                              # session
    "model", "tools", "database",                     # settings
    "wiki", "routine", "file",                        # feature areas
)

# Verbs held but deliberately unspent. Reserving costs nothing; spending one
# does, which is why `:routine name` stayed `/routine name` rather than becoming
# `/start name`.
RESERVED = ("connect", "start", "launch", "swap", "continue", "refresh",
            "import")

# Verbs the taxonomy retired, and what replaced them. Kept for one minor
# version so muscle memory costs a line of help rather than an API call — an
# unrecognised verb falls through to the model, so without this `:prompts`
# would be *sent to it* as a chat message. Self-removing, like the old-prefix
# nudge: delete the map and the words become ordinary prose again.
RETIRED = {
    "prompts": "list prompts",
    "prompt": "status  (or add <name> to attach one)",
    "personas": "list personas",
    "persona": "status  (or add <name> to attach one)",
    "attach": "add <path>",
    "attached": "status",
    "detach": "remove #<n>",
    "forget": "remove excerpts",
    "tag": "add tag <name>",
    "untag": "remove tag <name>",
    "tags": "status",
    "taglist": "list tags",
    "grep": "search <word>",
    "updatedb": "update db",
    "tokens": "status",
    "models": "list models",
    "outbox": "list outbox",
}


@dataclass(frozen=True)
class Cmd:
    """A parsed command line.

    `verb` is canonical (aliases resolved, lowercased). `args` is the token
    list after the verb. `raw` is that same remainder unsplit, which is what
    lets `tail()` hand back free text with its own spacing intact.
    """

    verb: str
    raw: str
    args: tuple
    legacy: bool = False

    def arg(self, i, default=""):
        """Token `i` after the verb, or `default` if the line stopped short."""
        return self.args[i] if i < len(self.args) else default

    def tail(self, i=0):
        """Everything from token `i` onward, as typed.

        Splitting and rejoining would collapse runs of spaces inside a commit
        message or a title, so this re-splits the raw remainder with a maxsplit
        and takes what's left.
        """
        if i >= len(self.args):
            return ""
        return self.raw.split(maxsplit=i)[i] if i else self.raw

    def int_arg(self, i, default=None):
        """Token `i` as an int, or `default` when it is absent or not a number.

        Deliberately forgiving: `:title abc` used to reach a bare `int()` and
        take the whole REPL down on a typo. A command that can't read its
        argument should say so, not raise.
        """
        try:
            return int(self.args[i])
        except (IndexError, ValueError):
            return default


def parse(line, prefix=PREFIX, legacy=LEGACY_PREFIX):
    """A `Cmd`, or None if this line isn't a command.

    None means "not addressed to us" — the caller sends it to the model. A
    bare prefix with nothing after it is also None: `/` on its own is a typo,
    and treating it as a verb named "" would need a special case in the table.

    `legacy` is the retired prefix. It parses identically and sets
    `Cmd.legacy`, so the REPL can nudge without the command failing — a
    migration that breaks the thing it is migrating teaches only that the
    upgrade was a mistake.
    """
    line = (line or "").strip()
    was_legacy = False
    if line.startswith(prefix):
        body = line[len(prefix):].strip()
    elif legacy and line.startswith(legacy):
        body, was_legacy = line[len(legacy):].strip(), True
    else:
        return None
    if not body:
        return None
    verb, _, raw = body.partition(" ")
    verb = verb.lower()
    raw = raw.strip()
    return Cmd(
        verb=ALIASES.get(verb, verb),
        raw=raw,
        args=tuple(raw.split()),
        legacy=was_legacy,
    )


def looks_like_path(fragment):
    """Is this argument a filesystem path rather than a name?

    `/add` takes both — a bare name is one of cfc's own pools, a path is an
    external file — so something has to tell them apart. The rule is the
    fragment's *shape*, and it is deliberately loose, because it is only ever
    consulted **after** the pools have been searched and found nothing: a real
    pool item called `relax.md` resolves as a name and never reaches here.

    Lives in the parser because `complete.py` asks the same question to decide
    whether to offer pool names or filesystem paths, and two copies of this
    rule is how completion and dispatch come to disagree about one line.
    """
    f = (fragment or "").strip()
    return bool(f) and any(c in f for c in "/\\~.")
