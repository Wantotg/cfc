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
# The `:` prefix was accepted for one version (v0.8) with a once-per-session
# nudge, and removed in v0.9 as designed. It was self-removing on purpose:
# deleting the constant is all it took, and `:add` is ordinary prose again.
PREFIX = "/"

# Typed verb → canonical verb. Kept here rather than in the dispatch table so
# completion and dispatch agree on the whole surface by construction; two lists
# of aliases is how one of them goes stale.
# **A value may be a phrase, not just a verb.** `models` has to become `list
# models`, and without that an alias can only rename a verb — which is why the
# plurals lived in `RETIRED` instead, borrowing a deprecation table to do a
# synonym's job. When `RETIRED` was deleted they would have become prose again
# and fallen through *to the model*, costing an API call and a confused answer:
# exactly what `/routines` did until v0.8.2. So the deletion and this promotion
# are one change, not two.
#
# Expansion happens once, in `parse`, and the user's own arguments are appended
# after it — so `/grep foo` is `/search foo` and nothing has to know that `grep`
# was ever a word.
ALIASES = {
    "h": "help",
    "?": "help",
    "db": "database",
    # Plurals the hand types by reflex, because the command lists several of
    # them. An unrecognised verb is not an error — it falls through to the
    # model (see run_session) — so a missing line here is an API call, not a
    # "no such command".
    "routines": "routine",
    "models": "list models",
    "prompts": "list prompts",
    "personas": "list personas",
    "traits": "list traits",
    "tags": "list tags",
    "sessions": "list sessions",
    "chats": "list chats",
    "outbox": "list outbox",
    # Singulars that read as questions about the current session. These were in
    # `RETIRED` pointing at `/status`, and they are worth keeping as real
    # synonyms rather than corrections: "what prompt am I on" is a thing to ask,
    # not a mistake to be told off for.
    "prompt": "status",
    "persona": "status",
    "attached": "status",
    "tokens": "status",
    # Verb renames where the argument carries over untouched.
    "grep": "search",
    "updatedb": "update db",
    "taglist": "list tags",
    "attach": "add",
    "tag": "add tag",
    "untag": "remove tag",
    "forget": "remove excerpts",
    # **`detach` is deliberately absent, and it is the only one.** Its
    # replacement is `/remove #<n>` — the `#` is the attachment namespace, so
    # the argument changes shape and no verb-level alias can carry `1` across
    # to `#1`. `/remove 1` would look for a *pool item named "1"*. The choices
    # were to widen `/remove` to accept a bare number (changing a deliberate
    # namespace to rescue a retired word) or to let this one go. It goes: it
    # had its version of correction, and it is the only member of the retired
    # set whose replacement is not the same command under a different name.
}


# The whole surface, in the order `/help` groups them. This is the canonical
# list: `main.py` asserts its handler table matches, so a verb added to one and
# not the other fails at import rather than at the moment someone types it.
# Two lists that have to agree (the table and this) is exactly the drift
# `HANDOVER.md` names as a recurring hazard — so they are checked, not
# maintained by hand. `RETIRED` was the third until v0.9; its live entries
# moved into `ALIASES` above rather than simply going away, because a deleted
# correction is a word that falls through to the model.
VERBS = (
    "help", "list", "status", "config", "search",     # ask
    "add", "remove",                                  # context
    "delete",                                         # destroy
    "export",                                         # data
    "recall", "remember", "update",                   # memory
    "new", "q", "title",                              # session
    "model", "tools", "database", "connect",          # settings
    "wiki", "routine", "file",                        # feature areas
)

# Verbs held but deliberately unspent. Reserving costs nothing; spending one
# does, which is why `:routine name` stayed `/routine name` rather than becoming
# `/start name`. `connect` was spent in v0.9 — it had been held since v0.8
# precisely for this, which is the reservation working as intended.
RESERVED = ("start", "launch", "swap", "continue", "refresh", "import")


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


def parse(line, prefix=PREFIX):
    """A `Cmd`, or None if this line isn't a command.

    None means "not addressed to us" — the caller sends it to the model. A
    bare prefix with nothing after it is also None: `/` on its own is a typo,
    and treating it as a verb named "" would need a special case in the table.

    The `:` prefix is gone as of v0.9 — a `:` line is prose and goes to the
    model, which is what it was before v0.8 and what the migration promised.
    """
    line = (line or "").strip()
    if not line.startswith(prefix):
        return None
    body = line[len(prefix):].strip()
    if not body:
        return None
    verb, _, raw = body.partition(" ")
    verb = verb.lower()
    raw = raw.strip()
    # An alias may expand to a phrase (`models` → `list models`), in which case
    # the extra words become the leading arguments and anything the user typed
    # follows them. Done here rather than in the dispatch table so completion
    # and dispatch see one surface: two places that expand aliases is how they
    # come to disagree about a single line.
    expansion = ALIASES.get(verb, verb)
    if " " in expansion:
        verb, _, extra = expansion.partition(" ")
        raw = f"{extra.strip()} {raw}".strip()
    else:
        verb = expansion
    return Cmd(
        verb=verb,
        raw=raw,
        args=tuple(raw.split()),
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
