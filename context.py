# context.py — who is asking, and what they may touch.
#
# Permission scope is per-context, not global. Interactive chat has two
# guardrails, the roots *and* the human at the gate. An unattended routine has
# no human, so the gate cannot function, which means its roots are the only
# guardrail left. That asymmetry is the whole reason this object exists: it
# makes the scope a required, declared field rather than an afterthought, and
# it makes "who may skip the gate" a property of the caller instead of a
# setting in a config file.
#
# Two things here are structural, not documentation:
#
#   1. There is no config knob that pre-clears a tool. TOOLS_AUTO_APPROVE used
#      to exist and was one line away from turning "no human present" into
#      "everything pre-approved". It is gone. A chat context is gated, and
#      `gated` has no setter, so it cannot be turned off by assignment either.
#      Only for_routine() produces an ungated context.
#
#   2. A write root may not overlap the cfc source tree. Enforced at
#      construction against this file's own directory, so it needs no config
#      and cannot drift out of date. The model is not prevented from editing
#      the source by a deny-list entry — the source is simply not in the
#      writable universe.
#
# Read scope and write scope are separate sets and the write set is never
# derived from the read set by assignment. Both are passed in; nothing here
# reaches for a default that would widen either.
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parent


class ScopeError(Exception):
    """Raised when a context is constructed with an unsafe scope."""


def _norm(roots):
    """Normalise a single root or an iterable of them to a tuple of Paths."""
    if roots is None:
        return ()
    if isinstance(roots, (str, Path)):
        roots = [roots]
    return tuple(Path(r).expanduser().resolve() for r in roots)


def _reject_code_roots(write_roots):
    """A write root may not contain, or live inside, the cfc source tree.

    Checked both directions: `~/projects` would *contain* the source, and
    `~/projects/cfc/notes` would live *inside* it. Either one puts the .py
    files this program is running from into reach of a write tool.
    """
    for r in write_roots:
        if r == CODE_ROOT or CODE_ROOT in r.parents or r in CODE_ROOT.parents:
            raise ScopeError(
                f"{r} overlaps the cfc source tree ({CODE_ROOT}) — "
                "write roots must not reach the code"
            )


class ToolContext:
    """The scope one run of the tool loop operates under.

    Build these with the classmethods, not the constructor: for_chat() and
    for_routine() are what encode the gated/ungated asymmetry.
    """

    def __init__(self, read_roots=(), write_roots=(), gated=True,
                 interactive=True, label="chat"):
        self.read_roots = _norm(read_roots)
        self.write_roots = _norm(write_roots)
        _reject_code_roots(self.write_roots)
        self._gated = bool(gated)
        self.interactive = bool(interactive)
        self.label = label

    # Read-only on purpose. `ctx.gated = False` raises AttributeError rather
    # than quietly disarming the gate — the only way to an ungated context is
    # for_routine(), which forces you to declare a write scope while you're
    # there.
    @property
    def gated(self):
        return self._gated

    @property
    def can_write(self):
        return bool(self.write_roots)

    @classmethod
    def for_chat(cls, read_roots, write_roots=(), interactive=None):
        """Interactive chat: always gated, whatever else is configured.

        `interactive` answers one question — **is there a human who can answer
        a prompt right now?** It defaults to whether stdin is a terminal, which
        is the only honest source for that. Hard-coding it True was a lie the
        moment input was piped: the empty-completion handler would ask
        `retry? (y/n)`, take the EOFError, and give up on a hiccup that a
        re-roll would have fixed.

        Note this is a separate question from `gated`. A chat is always gated —
        tool calls are never auto-approved — but a chat driven from a pipe has
        nobody to ask about a re-roll. Don't collapse the two.
        """
        if interactive is None:
            try:
                interactive = sys.stdin.isatty()
            except (AttributeError, ValueError):
                # A closed or replaced stdin (tests capture it) is not a human.
                interactive = False
        return cls(read_roots=read_roots, write_roots=write_roots,
                   gated=True, interactive=interactive, label="chat")

    @classmethod
    def for_routine(cls, name, read_roots, write_roots=(), interactive=False):
        """An unattended routine: ungated, so its roots are the only guardrail.

        Safety here comes from write_roots being narrow — never from
        pre-clearing tools, which is the failure this whole object exists to
        make unavailable.
        """
        return cls(read_roots=read_roots, write_roots=write_roots,
                   gated=False, interactive=interactive,
                   label=f"routine:{name}")

    def __repr__(self):
        return (f"<ToolContext {self.label} "
                f"read={len(self.read_roots)} write={len(self.write_roots)} "
                f"gated={self.gated}>")


def _config_roots():
    """(read, write) from config, with the write set standing alone.

    TOOLS_ROOTS used to be `ATTACH_ROOTS` by assignment. WRITE_ROOTS is
    deliberately not derived from either: an alias is how a read root becomes a
    write root by accident six months later.
    """
    try:
        from config import TOOLS_ROOTS as read
    except ImportError:
        try:
            from config import ATTACH_ROOTS as read
        except ImportError:
            read = (Path("~/projects").expanduser(),)
    try:
        from config import WRITE_ROOTS as write
    except ImportError:
        write = ()
    return read, write


def chat_context():
    """The default context for an interactive session."""
    read, write = _config_roots()
    return ToolContext.for_chat(read, write)


def as_context(obj, write_roots=()):
    """Accept a ToolContext or a bare roots value; always return a context.

    The bare-roots form is the old `roots=` argument, kept working for callers
    and tests that only ever meant read scope. It yields **no write scope** —
    passing a read root must never hand out write access by implication.
    """
    if isinstance(obj, ToolContext):
        return obj
    return ToolContext(read_roots=obj, write_roots=write_roots,
                       gated=True, interactive=True, label="ad-hoc")
