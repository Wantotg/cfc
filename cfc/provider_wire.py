"""provider_wire.py — the pure conversion from cfc's stored conversation
records to one OpenAI-compatible request plan (Q-2.0-29).

The stored ledger and the provider request answer different questions:
SQLite records what happened in cfc, the wire request contains only a
conversation shape a provider can continue safely. This module is that
seam, and nothing else. It never opens a socket, never touches SQLite, and
never mutates the `ConversationSnapshot` it is given — it only reads it and
builds fresh, immutable request-plan values.

The rule this module applies:

- both literal messages from every completed turn go on the wire;
- the user-only message of every failed, cancelled, or interrupted turn is
  omitted (interrupted turns are `FailedOutcome` underneath — the store
  never gives them a second shape) and named in the returned omission
  account instead;
- the user message of the one current active turn (the turn with no
  outcome yet) goes on the wire.

An omitted message is never deleted, rewritten, merged into a later prompt,
or replaced with an invented assistant reply — it stays exactly as stored,
simply absent from this one request. The omission account is not sent to
the provider; it exists so a caller (today, `scratchpad/stage3_harness.py`;
later, an interface) can say plainly what was left out and why.

A snapshot whose turns and messages do not form one of the shapes above —
an orphaned message, a turn with the wrong message count for its outcome,
two active turns, messages out of canonical order — refuses with
`MalformedSnapshot` before any HTTP work is attempted. This module does not
sort a bad snapshot into plausibility or discard an unexplained row.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from cfc.conversation_types import (
    CompletedOutcome,
    ConversationSnapshot,
    Message,
    Role,
    Turn,
    TurnId,
    TurnState,
)


class MalformedSnapshot(ValueError):
    """The snapshot's turns and messages do not form a coherent history.
    Raised before any request plan is built and before any HTTP work.
    """


@dataclass(frozen=True)
class WireMessage:
    """One literal message as it goes on the wire. `role` is the provider's
    own spelling (`"user"` / `"assistant"`), not cfc's `Role` enum — this is
    the boundary where cfc's vocabulary becomes the provider's.
    """
    role: str
    content: str


@dataclass(frozen=True)
class OmittedTurn:
    """One turn left off the wire: its identity and the terminal state that
    excluded it (`TurnState.FAILED` or `TurnState.CANCELLED` — an active or
    completed turn is never omitted).
    """
    turn_id: TurnId
    state: TurnState


@dataclass(frozen=True)
class RequestPlan:
    """An immutable, OpenAI-compatible request plan. Nothing here is a raw
    provider dictionary — the adapter (`cfc.provider_adapter`) is the only
    code that turns this into JSON and sends it. Deliberately narrow: no
    system/named context, tools, reasoning fields, sampling controls, or
    stored provider JSON is expressible here.
    """
    model: str
    messages: tuple[WireMessage, ...] = field(default_factory=tuple)
    stream: bool = False
    omitted: tuple[OmittedTurn, ...] = field(default_factory=tuple)


_WIRE_ROLE = {Role.USER: "user", Role.ASSISTANT: "assistant"}

#: Turn outcome types whose messages are omitted rather than sent — anything
#: that is not `None` (active) and not `CompletedOutcome`.
_OMITTED_OUTCOME_STATE = {
    "FailedOutcome": TurnState.FAILED,
    "CancelledOutcome": TurnState.CANCELLED,
}


def _group_messages_by_turn(
    chat_id, turns: tuple[Turn, ...], messages: tuple[Message, ...],
) -> dict[TurnId, list[Message]]:
    grouped: dict[TurnId, list[Message]] = {turn.id: [] for turn in turns}
    for message in messages:
        if message.chat_id != chat_id:
            raise MalformedSnapshot(
                f"message {message.id} belongs to chat {message.chat_id}, "
                f"not snapshot chat {chat_id}"
            )
        if message.turn_id not in grouped:
            raise MalformedSnapshot(
                f"message {message.id} references unknown turn {message.turn_id}"
            )
        grouped[message.turn_id].append(message)
    return grouped


def _require_canonical_order(
    turns: tuple[Turn, ...], messages: tuple[Message, ...],
) -> None:
    position_by_turn = {turn.id: turn.position for turn in turns}
    sort_key = lambda m: (position_by_turn[m.turn_id], m.turn_position)
    if list(messages) != sorted(messages, key=sort_key):
        raise MalformedSnapshot("messages are not in canonical (turn, position) order")


def _require_well_formed_turns(turns: tuple[Turn, ...]) -> None:
    seen_ids: set[TurnId] = set()
    previous_position: int | None = None
    active_count = 0
    for turn in turns:
        if turn.id in seen_ids:
            raise MalformedSnapshot(f"turn {turn.id} appears more than once")
        seen_ids.add(turn.id)
        if previous_position is not None and turn.position <= previous_position:
            raise MalformedSnapshot("turns are not strictly ordered by position")
        previous_position = turn.position
        if turn.outcome is None:
            active_count += 1
    if active_count > 1:
        raise MalformedSnapshot(f"{active_count} turns are active; at most one is coherent")
    if active_count == 1 and turns[-1].outcome is not None:
        raise MalformedSnapshot("the active turn is not the most recently positioned turn")


def _require_turn_message_shape(turn: Turn, msgs: list[Message]) -> None:
    outcome_name = type(turn.outcome).__name__ if turn.outcome is not None else "active"

    if turn.outcome is None or outcome_name in _OMITTED_OUTCOME_STATE:
        if len(msgs) != 1:
            raise MalformedSnapshot(
                f"turn {turn.id} ({outcome_name}) must carry exactly one message, "
                f"has {len(msgs)}"
            )
        if msgs[0].turn_position != 0 or msgs[0].role is not Role.USER:
            raise MalformedSnapshot(
                f"turn {turn.id} ({outcome_name})'s one message must be its opening "
                f"user message"
            )
    elif isinstance(turn.outcome, CompletedOutcome):
        if len(msgs) != 2:
            raise MalformedSnapshot(
                f"turn {turn.id} (completed) must carry exactly two messages, "
                f"has {len(msgs)}"
            )
        if msgs[0].turn_position != 0 or msgs[0].role is not Role.USER:
            raise MalformedSnapshot(f"turn {turn.id}'s first message must be the user message")
        if msgs[1].turn_position != 1 or msgs[1].role is not Role.ASSISTANT:
            raise MalformedSnapshot(
                f"turn {turn.id}'s second message must be the assistant message"
            )
    else:
        raise MalformedSnapshot(f"turn {turn.id} has an unrecognised outcome type: {outcome_name}")


def build_request_plan(snapshot: ConversationSnapshot, model: str) -> RequestPlan:
    """The pure conversion this module exists for. Refuses with
    `MalformedSnapshot` rather than guessing when `snapshot` is incoherent.
    Never mutates `snapshot`.
    """
    turns = snapshot.turns
    messages = snapshot.messages

    _require_well_formed_turns(turns)
    grouped = _group_messages_by_turn(snapshot.chat_id, turns, messages)
    _require_canonical_order(turns, messages)
    for turn in turns:
        _require_turn_message_shape(turn, grouped[turn.id])

    wire_messages: list[WireMessage] = []
    omitted: list[OmittedTurn] = []
    for turn in turns:
        outcome_name = type(turn.outcome).__name__ if turn.outcome is not None else "active"
        if turn.outcome is None or isinstance(turn.outcome, CompletedOutcome):
            for message in grouped[turn.id]:
                wire_messages.append(
                    WireMessage(role=_WIRE_ROLE[message.role], content=message.content)
                )
        else:
            omitted.append(OmittedTurn(turn_id=turn.id, state=_OMITTED_OUTCOME_STATE[outcome_name]))

    return RequestPlan(
        model=model, messages=tuple(wire_messages), stream=False, omitted=tuple(omitted),
    )
