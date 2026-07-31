# governor.py — the one request compiler for every model-facing chat turn.
#
# 1.3's job: let cfc add direction to a request — "answer this more gently",
# "continue where you left off", a periodic trait reminder — without that
# direction ever becoming a line in the conversation. Five triggers (First
# Message, /continue, OOC, periodic trait refresh, the tone cue) are not five
# prompt formats; they are five ways of arriving at one wrapped `user`-role
# message this module builds, and one place deciding where it sits in the
# request.
#
# This module is pure: it takes bodies and counts already read by its caller
# (main.py) and returns message lists. No config read that isn't the one
# documented seam below, no filesystem, no database, no console — the same
# discipline assemble.py holds, and for the same reason: two turn paths
# (streaming, tools) must build byte-identical envelopes, and a function that
# reaches for its own state is a function two callers can make disagree.
#
# The wrapper has no cfc-side parser. It is a model-facing format with one
# producer (`compile_messages`, below) and nothing downstream ever reads it
# back out of a request — so it is deliberately not a row in HANDOVER's
# producer/parser table.
DIRECTION_OPEN = "[cfc direction]"
DIRECTION_CLOSE = "[/cfc direction]"


def wrap(text):
    """The one cfc-direction wrapper. Nothing else in this codebase produces
    this shape, and nothing parses it back out — see the module docstring."""
    return f"{DIRECTION_OPEN}\n{text}\n{DIRECTION_CLOSE}"


try:
    from config import GOVERNOR_TRAIT_INTERVAL
except ImportError:
    GOVERNOR_TRAIT_INTERVAL = 6


# Bounded on purpose — see Concept.md's "Tone becomes diagnosis" failure mode.
# It tells the model to use its own judgement under ambiguity rather than
# asking it to name a feeling, which is exactly the "use a model for
# judgement, use code for anything with a right answer" rule this codebase
# already follows everywhere else (HANDOVER's four generating rules).
TONE_INSTRUCTION = (
    "tone check — if the immediately preceding user message carries a "
    "strong, unambiguous emotional cue in its own wording, let that shape "
    "this answer's tone. Otherwise make no adjustment. Never state or "
    "diagnose an emotion as fact, never change what is factually true, "
    "never lower a safety position, and never override the explicit task."
)

CONTINUE_INSTRUCTION = (
    "continue directly from your last substantive answer in this "
    "conversation. Do not repeat it and do not summarise it — extend it."
)


def compile_messages(prefix, first_message, history, instruction=None,
                      split=None):
    """The request envelope, positions 1 through 4:

        1. `prefix`         persona/system prompt/traits/tool guidance
        2. `first_message`  the session's frozen opening, as an assistant turn
        3. `history`        durable conversation, through the current turn
        4. `instruction`    at most one compiled cfc direction (not durable)

    Position 5 (assistant/tool messages this turn produces) is the caller's:
    it is appended live to `history` as the turn proceeds and is not this
    function's concern.

    `split` is where in `history` the direction belongs, and exists for the
    tool loop: `agent_turn` calls this once per round trip with a growing
    `history` (its own calls and results are appended between calls) but a
    fixed `split` taken at the loop's entry, which is what keeps the
    direction pinned at its original position instead of being re-appended
    after every tool result. Default is `len(history)` — the end of durable
    history — which is exactly right for a one-shot streaming request and for
    the tool loop's first call.

    `instruction` is raw, unwrapped text; wrapping happens here, once, so
    there is exactly one producer of the format.
    """
    if split is None:
        split = len(history)
    out = list(prefix)
    if first_message:
        out.append({"role": "assistant", "content": first_message["text"]})
    out.extend(history[:split])
    if instruction:
        out.append({"role": "user", "content": wrap(instruction)})
    out.extend(history[split:])
    return out


def trait_refresh(trait_names, turn_count, interval=None):
    """The trait name to refresh into the direction on this turn, or None.

    Purely a function of `turn_count` (durable user chat turns so far,
    this one included — see `db.count_chat_user_turns`) and `interval`: no
    state is kept between calls, and none needs to be. Refresh number N
    (1st, 2nd, …) rotates through `trait_names` in attach order, one at a
    time — `(N-1) % len(trait_names)` — so reopening a session recomputes
    the same answer from the same durable count instead of drifting from
    whatever was in memory when it last ran.

    `interval <= 0` disables automatic refresh; traits still ride every
    request as system messages regardless (assemble.py) — this only turns
    off the *reminder*.
    """
    interval = GOVERNOR_TRAIT_INTERVAL if interval is None else interval
    if not interval or interval <= 0 or not trait_names:
        return None
    if turn_count <= 0 or turn_count % interval != 0:
        return None
    refresh_no = turn_count // interval
    return trait_names[(refresh_no - 1) % len(trait_names)]


def ordinary_instruction(trait_names, turn_count, trait_bodies=None,
                          interval=None):
    """The automatic direction for an ordinary chat turn.

    Tone applies to every ordinary turn, unconditionally. A trait reminder
    joins it on a cadence turn — never a second direction message, one
    combined instruction, per Concept.md's "the governor piles on" failure
    mode. `trait_bodies` maps name -> body-or-None; a name whose body is None
    (its file has gone since it was attached) is named as missing in the
    returned labels and contributes no text — a missing trait must not be
    replaced by an empty instruction.

    Returns `(instruction, labels)`. `labels` is what main.py prints as the
    dim `cfc -> ...` line; always at least `["tone check"]`.
    """
    parts = [TONE_INSTRUCTION]
    labels = ["tone check"]
    name = trait_refresh(trait_names, turn_count, interval)
    if name is not None:
        body = (trait_bodies or {}).get(name)
        if body:
            parts.append(f"trait reminder — stay in character for the "
                         f"trait '{name}':\n\n{body}")
            labels.append(f"trait: {name}")
        else:
            labels.append(f"trait: {name} (missing)")
    return "\n\n".join(parts), labels


def continue_instruction():
    """`/continue`'s direction. No tone, no trait — an explicit trigger
    suppresses the automatic ones (Concept.md, "OOC" section; the same rule
    applies to /continue, which is equally explicit)."""
    return CONTINUE_INSTRUCTION, ["continue"]


def ooc_instruction(text):
    """An OOC turn's direction: the typed text, verbatim, as the whole
    instruction — no tone, no trait. `text` must already be non-empty; an
    empty `(( ))` is main.py's refusal to make, not this module's."""
    return text, ["ooc"]
