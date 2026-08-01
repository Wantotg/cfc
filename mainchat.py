# mainchat.py — the one loader for Main chat's vault-configured profile
# bundle: system prompt, persona, First Message, one fixed filename each.
#
# This is the single owner of the bundle's shape (MAIN_CHAT_DIR, the three
# fixed names, path resolution, UTF-8 reads and validation) so the hub,
# session and `/status` cannot each grow a separate definition of "ready" —
# the same job pools.py does for the three attachable pools, on a folder with
# exactly three files and no listing of its own.
#
# Two access modes, not one, because creating a Main session and turning one
# it already has are different questions: creation needs all three bodies or
# none; reopening/a turn needs only the two *live* files (system prompt,
# persona) readable right now. The source First Message is never read again
# after creation — an existing session speaks for its own opening through the
# frozen snapshot db.py already stores, not through this module.
from pathlib import Path

try:
    from config import MAIN_CHAT_DIR
except ImportError:
    MAIN_CHAT_DIR = ""

SYSTEM_PROMPT_FILE = "system prompt.md"
PERSONA_FILE = "persona.md"
FIRST_MESSAGE_FILE = "first message.md"

# What can be wrong with one bundle file. Named states rather than a string a
# caller would have to parse — the recurring hazard HANDOVER.md tabulates —
# and precise about *which* of the five is true, since "Main chat
# unavailable" tells nobody whether to edit config.py or a file inside it.
UNCONFIGURED = "unconfigured"   # MAIN_CHAT_DIR itself is unset
MISSING = "missing"             # the directory or file doesn't exist
NOT_FILE = "not_file"           # something is there and isn't a file
UNREADABLE = "unreadable"       # exists, is a file, couldn't be read
EMPTY = "empty"                 # readable, but blank or whitespace-only


class MainChatProblem(Exception):
    """One bundle file could not be used. `.reason` is one of the module
    constants above, `.path` the exact offending path — a plain string,
    since UNCONFIGURED has no Path to point at — and `.detail` an
    underlying error's message where there is one."""

    def __init__(self, reason, path, detail=None):
        self.reason = reason
        self.path = path
        self.detail = detail
        messages = {
            UNCONFIGURED: "MAIN_CHAT_DIR is not configured",
            MISSING: f"{path} does not exist",
            NOT_FILE: f"{path} is not a file",
            UNREADABLE: f"{path} could not be read"
                        + (f" — {detail}" if detail else ""),
            EMPTY: f"{path} is empty (or whitespace only)",
        }
        super().__init__(messages.get(reason, f"{path}: {reason}"))


def main_chat_dir():
    """The configured bundle directory, or None if MAIN_CHAT_DIR is unset.
    Read through the attribute at call time, not captured at import, so a
    test can repoint it the way tests/golden.py repoints pools.py's dirs."""
    return Path(MAIN_CHAT_DIR).expanduser() if MAIN_CHAT_DIR else None


def _read(filename):
    """The stripped body of one bundle file. Raises MainChatProblem naming
    exactly what's wrong; never returns a partial or guessed result."""
    d = main_chat_dir()
    if d is None:
        raise MainChatProblem(UNCONFIGURED, filename)
    path = d / filename
    if not path.exists():
        raise MainChatProblem(MISSING, str(path))
    if not path.is_file():
        raise MainChatProblem(NOT_FILE, str(path))
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise MainChatProblem(UNREADABLE, str(path), str(e)) from e
    body = text.strip()
    if not body:
        raise MainChatProblem(EMPTY, str(path))
    return body


def load_creation_bundle():
    """(system_prompt, persona, first_message) — all three, or raises
    MainChatProblem naming the first one that fails. A session either gets
    all three bodies or none of them; this is the only function that reads
    `first message.md`, and it is called exactly once per Main session, at
    creation."""
    system_prompt = _read(SYSTEM_PROMPT_FILE)
    persona = _read(PERSONA_FILE)
    first_message = _read(FIRST_MESSAGE_FILE)
    return system_prompt, persona, first_message


def load_live_profile():
    """(system_prompt, persona) — what a reopened session or an in-progress
    turn needs. Raises MainChatProblem exactly as creation does. Deliberately
    never touches `first message.md`: the source First Message is not
    consulted again after a session owns its frozen snapshot."""
    system_prompt = _read(SYSTEM_PROMPT_FILE)
    persona = _read(PERSONA_FILE)
    return system_prompt, persona


# name -> filename, for callers that want every bundle file's state at once
# (the hub/`/status` reporting the "three bundle states" Concept.md asks
# for) without caring which function above would have needed it.
_BUNDLE_FILES = (
    ("system_prompt", SYSTEM_PROMPT_FILE),
    ("persona", PERSONA_FILE),
    ("first_message", FIRST_MESSAGE_FILE),
)


def bundle_states():
    """{"system_prompt": (ok, problem_or_None), "persona": (...),
    "first_message": (...)} for every bundle file. Never raises — this is a
    display seam (the header, `/status`), and a broken bundle must be
    showable rather than something that stops a screen rendering."""
    out = {}
    for key, filename in _BUNDLE_FILES:
        try:
            _read(filename)
            out[key] = (True, None)
        except MainChatProblem as e:
            out[key] = (False, e)
    return out
