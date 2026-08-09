"""conversation_types.py — the provider-independent vocabulary for the 2.0
conversation ledger: opaque chat/turn/message identities, literal content,
explicit ordering, terminal outcomes, and the injected responder boundary.

These are cfc's own records, not OpenAI message dictionaries and not SQLite
rows. `conversation_store.py` translates rows to these types only at its own
boundary; nothing here imports `sqlite3`, `config`, or a flat v1.9.1 runtime
module, and nothing here can express a private durable chat — `ChatKind` has
exactly one member because this loop closes over ordinary chat only.

Every dataclass is `frozen=True`: once built, a record cannot be mutated in
place, only replaced. A `Turn` carries at most one `outcome`, so "two
terminal outcomes on one turn" is not a shape these types can hold — it is a
repository/service behaviour proved elsewhere (`conversation_store.py`).
"""
from __future__ import annotations

import datetime
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, Union


def utc_now() -> datetime.datetime:
    """The one clock every record in this module is built against — always
    timezone-aware, so a stored timestamp always carries its UTC offset
    rather than becoming a naive value some caller has to guess about.
    """
    return datetime.datetime.now(datetime.timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex


def _require_aware(name: str, value: datetime.datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware datetime, got a naive one")


# --- opaque identities --------------------------------------------------

@dataclass(frozen=True)
class ChatId:
    """An opaque, stable chat identity. Never generated from a title, a
    timestamp, or a row id that could be reused — `new()` is the only
    constructor ordinary callers use.
    """
    value: str

    @staticmethod
    def new() -> "ChatId":
        return ChatId(_new_id())

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TurnId:
    value: str

    @staticmethod
    def new() -> "TurnId":
        return TurnId(_new_id())

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class MessageId:
    value: str

    @staticmethod
    def new() -> "MessageId":
        return MessageId(_new_id())

    def __str__(self) -> str:
        return self.value


# --- chat metadata --------------------------------------------------------

class ChatKind(Enum):
    """The durable chat kinds these types can express. Deliberately one
    member: private chat is locally ephemeral by structure (`HANDOVER.md`
    rule 7), so there is no `PRIVATE` value here for a caller to reach for.
    A later loop that gives Main its own durable path adds a member here;
    it does not repurpose this one.
    """
    ORDINARY = "ordinary"


@dataclass(frozen=True)
class Chat:
    id: ChatId
    kind: ChatKind
    title: str
    created_at: datetime.datetime
    updated_at: datetime.datetime

    def __post_init__(self) -> None:
        _require_aware("created_at", self.created_at)
        _require_aware("updated_at", self.updated_at)


# --- messages ---------------------------------------------------------------

class Role(Enum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class Message:
    """One literal message. `turn_position` is the explicit within-turn
    order (0 for the user message that opened the turn, 1 for the assistant
    message that closed it) — never inferred from `created_at` or `id`.
    """
    id: MessageId
    chat_id: ChatId
    turn_id: TurnId
    turn_position: int
    role: Role
    content: str
    created_at: datetime.datetime

    def __post_init__(self) -> None:
        _require_aware("created_at", self.created_at)
        if self.turn_position < 0:
            raise ValueError("turn_position must not be negative")


# --- usage ------------------------------------------------------------------

@dataclass(frozen=True)
class Usage:
    """Token counts a provider reported. Each field is independently
    optional: a provider that reports input and output but not total must
    stay distinguishable from one that reports zero — an absent count is
    never coerced to `0`.

    All three counts absent is not constructible (B-2.0-26): that spelling
    is indistinguishable from `usage=None` once stored as three `NULL`
    columns, so a caller with no counts at all uses `usage=None` rather than
    building an empty `Usage`.
    """
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.input_tokens is None and self.output_tokens is None \
                and self.total_tokens is None:
            raise ValueError(
                "Usage with all three counts absent is not constructible; "
                "use usage=None to represent no reported usage"
            )


# --- failure evidence ---------------------------------------------------

class FailureKind(Enum):
    """Which boundary produced a failed turn — kept distinct so a provider-
    independent refusal, an unexpected internal exception, and a recovered
    process-death interruption never collapse into the same silence.
    """
    RESPONDER = "responder"        #: the responder itself returned Failure
    INTERNAL = "internal"          #: an unexpected responder exception, converted
    INTERRUPTED = "interrupted"    #: ended by something outside the responder —
                                   #: Ctrl-C or a cancelled task during a live
                                   #: turn, or reopen recovery after process death


class ProviderProblem(Enum):
    """The provider-wire taxonomy a `RESPONDER` failure's evidence may
    narrow to. `None` on `FailureEvidence.problem` means the failure is not
    a provider-wire failure (an internal or interrupted failure, or a
    responder failure that predates this taxonomy).
    """
    CONNECTION = "connection"                  #: could not reach the endpoint
    TIMEOUT = "timeout"                        #: see FailureEvidence.timeout_phase
    HTTP_STATUS = "http_status"                #: see FailureEvidence.status_code
    MALFORMED_RESPONSE = "malformed_response"  #: no usable assistant content


class TimeoutPhase(Enum):
    """Which `httpx` timeout budget expired. Read has its own, longer
    budget than the others: a model may legitimately take longer to answer
    than a dead endpoint needs to prove it is unreachable.
    """
    CONNECT = "connect"
    WRITE = "write"
    POOL = "pool"
    READ = "read"


@dataclass(frozen=True)
class FailureEvidence:
    """Typed, redacted failure detail. `reason` is a short description for
    a human or a later retry decision — never a credential, an API key, or
    an entire provider response body.

    `problem`, `timeout_phase`, and `status_code` narrow a provider-wire
    `RESPONDER` failure without smuggling in anything unsafe: `timeout_phase`
    is set exactly when `problem` is `TIMEOUT`, and `status_code` exactly
    when `problem` is `HTTP_STATUS`. An `INTERNAL` or `INTERRUPTED` failure,
    or a `RESPONDER` failure with no provider-wire detail, leaves all three
    `None`.
    """
    kind: FailureKind
    reason: str
    problem: ProviderProblem | None = None
    timeout_phase: TimeoutPhase | None = None
    status_code: int | None = None

    def __post_init__(self) -> None:
        has_phase = self.timeout_phase is not None
        wants_phase = self.problem is ProviderProblem.TIMEOUT
        if has_phase != wants_phase:
            raise ValueError(
                "timeout_phase must be set exactly when problem is TIMEOUT"
            )
        has_status = self.status_code is not None
        wants_status = self.problem is ProviderProblem.HTTP_STATUS
        if has_status != wants_status:
            raise ValueError(
                "status_code must be set exactly when problem is HTTP_STATUS"
            )


# --- terminal turn outcomes (as persisted / read back) -----------------

@dataclass(frozen=True)
class CompletedOutcome:
    usage: Usage | None = None


@dataclass(frozen=True)
class FailedOutcome:
    evidence: FailureEvidence


@dataclass(frozen=True)
class CancelledOutcome:
    pass


#: The stored terminal outcome of a turn. A `Turn.outcome` field holds at
#: most one of these — the type itself has no shape that could carry two.
TurnOutcome = Union[CompletedOutcome, FailedOutcome, CancelledOutcome]


class TurnState(Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


_OUTCOME_STATE = {
    CompletedOutcome: TurnState.COMPLETED,
    FailedOutcome: TurnState.FAILED,
    CancelledOutcome: TurnState.CANCELLED,
}


@dataclass(frozen=True)
class Turn:
    """A turn's identity, position, model, timing, and current terminal
    state. `outcome` is `None` while the turn is active — there is no
    separate boolean to drift out of step with it.
    """
    id: TurnId
    chat_id: ChatId
    position: int
    model: str
    started_at: datetime.datetime
    finished_at: datetime.datetime | None = None
    outcome: TurnOutcome | None = None

    def __post_init__(self) -> None:
        _require_aware("started_at", self.started_at)
        if self.finished_at is not None:
            _require_aware("finished_at", self.finished_at)
        if self.position < 0:
            raise ValueError("position must not be negative")
        if (self.outcome is None) != (self.finished_at is None):
            raise ValueError(
                "a turn has a finished_at exactly when it has an outcome, and "
                "neither otherwise"
            )

    @property
    def state(self) -> TurnState:
        if self.outcome is None:
            return TurnState.ACTIVE
        return _OUTCOME_STATE[type(self.outcome)]


# --- the responder boundary --------------------------------------------

@dataclass(frozen=True)
class ConversationSnapshot:
    """The immutable stored history a responder is allowed to see: this
    chat's turns and messages in canonical order, including the user
    message that opened the active (still-outcome-less) turn. No SQLite
    connection, no authority object, and no provider-shaped dictionary — the
    provider-wire converter reads this, not raw rows.

    `turns` carries each turn's identity, position, and terminal state (or
    none, for the one active turn) so a converter can decide which stored
    messages belong on the wire without re-querying SQLite.
    """
    chat_id: ChatId
    turns: tuple[Turn, ...] = field(default_factory=tuple)
    messages: tuple[Message, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Completion:
    """A responder's typed success: the literal assistant text and whatever
    usage the provider reported.
    """
    content: str
    usage: Usage | None = None


@dataclass(frozen=True)
class Failure:
    """A responder's typed, provider-independent failure."""
    evidence: FailureEvidence


@dataclass(frozen=True)
class Cancellation:
    """A responder's typed cancellation — the turn was withdrawn or
    superseded rather than answered or refused.
    """
    pass


#: What an injected responder returns: exactly one of a completion, a
#: failure, or a cancellation.
ResponderResult = Union[Completion, Failure, Cancellation]


class Responder(Protocol):
    """The injected boundary the conversation service awaits to produce a
    turn's answer. Receives only an immutable stored-conversation snapshot
    and the selected model — never a SQLite connection, never a general
    authority object — so it cannot read or write anything this loop does
    not explicitly hand it.

    `respond` is a coroutine so the service can await real network I/O
    (`cfc.provider_adapter`) without blocking; a deterministic test
    responder is still an ordinary `async def`.
    """

    async def respond(self, snapshot: ConversationSnapshot, model: str) -> ResponderResult:
        ...
