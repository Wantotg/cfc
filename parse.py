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

# v0.8 flips this to "/". It is one constant on purpose: the flip is a change
# to the grammar, not thirty-five edits to the handlers.
PREFIX = ":"

# Typed verb → canonical verb. Kept here rather than in the dispatch table so
# completion and dispatch agree on the whole surface by construction; two lists
# of aliases is how one of them goes stale.
ALIASES = {
    "h": "help",
    "?": "help",
    "db": "database",
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
    bare prefix with nothing after it is also None: `:` on its own is a typo,
    and treating it as a verb named "" would need a special case in the table.
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
    return Cmd(
        verb=ALIASES.get(verb, verb),
        raw=raw,
        args=tuple(raw.split()),
    )
