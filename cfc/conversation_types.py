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
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Union


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


# --- context: named selection, resolved sources, and a turn's frozen
# --- opening (Stage 5 loop 1) ------------------------------------------

class ContextCategory(Enum):
    """The source kinds a `ContextPlan` can carry. `SYSTEM_INSTRUCTIONS` is
    cfc-owned and always resolvable; `USER_PREFERENCES`/`PERSONA`/`TRAIT` are
    vault-owned Markdown a chat selects, each independently optional.
    `FIRST_MESSAGE` never appears in a `ContextPlan` (the frozen opening is
    conversation content, not provenance — see `OpeningMessage`) but is one
    of the rows the Context modal lists, so it stays in this vocabulary
    rather than a parallel one `tui.py` would have to keep in sync by hand.

    `MAIN_SYSTEM_PROMPT` and `MAIN_PERSONA` (Stage 5 loop 3) are Main's own
    fixed profile files (`system prompt.md`, `persona.md` in `MAIN_CHAT_DIR`)
    — never selected, always resolved fresh for a Main chat, and distinct
    from `PERSONA`: a Main chat's `ContextSelection.persona` stays unused,
    since Main's persona is this fixed file, not a vault pick.

    `ATTACHMENT` (Stage 5 loop 3) is one selected vault-relative Markdown
    file, for both ordinary and Main chats — reference material, not a
    system-owned or Main-owned source (see `ContextPlan.ordered_sources`'s
    own docstring for why it is never grouped with the others).
    """
    SYSTEM_INSTRUCTIONS = "system_instructions"
    USER_PREFERENCES = "user_preferences"
    PERSONA = "persona"
    TRAIT = "trait"
    FIRST_MESSAGE = "first_message"
    MAIN_SYSTEM_PROMPT = "main_system_prompt"
    MAIN_PERSONA = "main_persona"
    ATTACHMENT = "attachment"


@dataclass(frozen=True)
class SourceRecord:
    """One context source, read once and never re-read for the plan that
    carries it: cfc's own System Instructions, or one vault-owned Markdown
    file. `name` is the exact stored identity (a fixed name for System
    Instructions, the exact filename for a vault source); `display_name` is
    what a person sees (the filename's stem for a vault source). `body` is
    the literal text this source resolved to at the moment it was read —
    never truncated, reformatted, or re-fetched later by anything holding
    this record.
    """
    category: ContextCategory
    name: str
    display_name: str
    body: str
    character_count: int
    fingerprint: str

    def __post_init__(self) -> None:
        if self.character_count != len(self.body):
            raise ValueError("character_count must equal len(body)")


@dataclass(frozen=True)
class ContextSelection:
    """A chat's durable context choices: exact vault filenames, never
    bodies. `user_preferences` and `persona` are each at most one filename;
    `traits` preserves the order they were selected in. `model` is the
    chat's current default model id for a future turn — a turn always
    stores the model it actually used on its own `Turn.model`, so this
    field never rewrites a past turn's evidence.

    `attachments` (Stage 5 loop 3) is the ordered, duplicate-free set of
    exact vault-relative Markdown paths selected as reference material —
    shared by ordinary and Main chats alike. `persona` stays unused for a
    Main chat: Main's persona is its own fixed profile file, not a
    selection this field expresses (`ContextCategory`'s own docstring).
    """
    user_preferences: str | None = None
    persona: str | None = None
    traits: tuple[str, ...] = field(default_factory=tuple)
    model: str | None = None
    attachments: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OpeningMessage:
    """A chat's frozen First Message: a Persona's same-filename companion,
    snapshotted once as the chat's opening assistant message. Conversation
    content, not context provenance (Concept.md's "First Message is an
    opening, not a synthetic turn") — it is never rebuilt from a later
    vault edit, deletion, or Persona change.
    """
    source_name: str
    content: str
    created_at: datetime.datetime
    fingerprint: str

    def __post_init__(self) -> None:
        _require_aware("created_at", self.created_at)


@dataclass(frozen=True)
class ContextManifestEntry:
    """One recorded row of a turn's context provenance: which source, in
    what order, how large, and its fingerprint at the moment that turn
    started — never the body itself. If a source later changes, comparing
    a fresh read's fingerprint against this one is how inspection notices
    (Concept.md's "If a source later changes...").
    """
    category: ContextCategory
    name: str
    order: int
    character_count: int
    fingerprint: str


@dataclass(frozen=True)
class ContextPlan:
    """One immutable, freshly resolved context plan: cfc's own System
    Instructions plus whatever a chat's current selection resolved to, at
    the moment this plan was built. Never mutated and never partially
    rebuilt — a caller that wants a plan reflecting a later edit builds a
    fresh one.

    `main_system_prompt`/`main_persona` (Stage 5 loop 3) are set only for a
    Main chat's plan — Main's own fixed profile files, freshly resolved
    every time, never a vault selection. `attachments` is set for either
    chat kind: the chat's currently selected reference material, resolved
    and frozen for this one plan.
    """
    system_instructions: SourceRecord
    main_system_prompt: SourceRecord | None = None
    main_persona: SourceRecord | None = None
    user_preferences: SourceRecord | None = None
    persona: SourceRecord | None = None
    traits: tuple[SourceRecord, ...] = field(default_factory=tuple)
    attachments: tuple[SourceRecord, ...] = field(default_factory=tuple)

    def ordered_sources(self) -> tuple[SourceRecord, ...]:
        """Every resolved *system-role* source in exact provider request
        order: System Instructions, Main's System Prompt and Persona (when
        this is a Main plan), User Preferences, Persona, then Traits in
        selection order. The one ordering `provider_wire` and the Context
        modal's preview both read, so they cannot independently drift apart.

        Deliberately excludes `attachments`: those are sent as labelled
        `user` reference messages, not `system` messages, and are placed
        after the chat's frozen opening rather than among these sources
        (Concept.md's "exact wire order" — see `provider_wire.build_request_
        plan`). A caller that wants every provenance-bearing source
        together, in the plan's one true order, uses `all_sources` instead.
        """
        sources = [self.system_instructions]
        if self.main_system_prompt is not None:
            sources.append(self.main_system_prompt)
        if self.main_persona is not None:
            sources.append(self.main_persona)
        if self.user_preferences is not None:
            sources.append(self.user_preferences)
        if self.persona is not None:
            sources.append(self.persona)
        sources.extend(self.traits)
        return tuple(sources)

    def all_sources(self) -> tuple[SourceRecord, ...]:
        """`ordered_sources()` followed by `attachments` — every source this
        plan resolved, in the one order `to_manifest` records. Not wire
        order (attachments interleave after the opening on the wire; see
        `ordered_sources`'s own docstring) — this is provenance order.
        """
        return self.ordered_sources() + self.attachments

    def to_manifest(self) -> tuple[ContextManifestEntry, ...]:
        """This plan's sources, minus their bodies — the shape
        `ConversationStore.start_turn` persists as one turn's provenance
        (never a vault body; Concept.md's "It deliberately does not copy
        all source bodies into SQLite").
        """
        return tuple(
            ContextManifestEntry(
                category=source.category, name=source.name, order=index,
                character_count=source.character_count, fingerprint=source.fingerprint,
            )
            for index, source in enumerate(self.all_sources())
        )


# --- chat metadata --------------------------------------------------------

class ChatKind(Enum):
    """The durable chat kinds these types can express. Private chat is
    locally ephemeral by structure (`HANDOVER.md` rule 7), so there is no
    `PRIVATE` value here for a caller to reach for.

    `MAIN` (Stage 5 loop 3) is one distinguished row in the same ledger as
    `ORDINARY` chats — the same `Chat`/`Turn`/`Message` shapes, the same
    store, service, and provider path. Exactly one `MAIN` row can exist
    (`conversation_store`'s own singleton invariant); nothing in this module
    enforces that itself, since this module expresses shapes, not repository
    invariants.
    """
    ORDINARY = "ordinary"
    MAIN = "main"


@dataclass(frozen=True)
class Chat:
    id: ChatId
    kind: ChatKind
    title: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    context_selection: ContextSelection = field(default_factory=lambda: ContextSelection())
    opening: OpeningMessage | None = None

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


# --- tool calls: the durable ledger between a turn's two messages ---------
# (Stage 6 loop 1)
#
# A turn's `cfc_messages` shape — the opening user message, and, once the
# turn completes, one closing assistant message — is unchanged by tool use.
# Everything a tool-using turn does *between* those two messages, each
# provider round trip and its calls' results, is new, separate ledger
# material a `ConversationSnapshot` carries alongside `messages`, and
# `provider_wire` interleaves back onto the wire in provider-exchange order
# (Concept.md: "rather than forcing tool protocol into the current
# two-message turn_position shape"). This keeps every existing turn/message
# invariant untouched: an active turn's `cfc_messages` shape stays exactly
# the opening user message, no matter how many tool round trips it is
# mid-way through.

class ExchangeEnding(Enum):
    """What one provider round trip within a turn produced. Mirrors
    `ResponderResult`'s shape at exchange granularity rather than turn
    granularity: a `FAILURE`/`CANCELLED` exchange still leaves its own
    evidence (model, usage) even though the *turn* fails or cancels because
    of it (Concept.md: "Earlier exchange usage remains evidence even when a
    later provider request fails or the turn is cancelled").
    """
    COMPLETION = "completion"
    TOOL_CALL_BATCH = "tool_call_batch"
    FAILURE = "failure"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ProviderExchange:
    """One request/response round trip in a turn's continuation loop,
    ordered by `sequence` (0-based, strictly increasing per turn — the order
    `provider_wire` replays and budgets are spent in). `assistant_content` is
    the literal text the provider returned alongside this ending, when it
    returned any: always present for `COMPLETION`, optionally present for
    `TOOL_CALL_BATCH`, absent for `FAILURE`/`CANCELLED`. `usage` is this
    exchange's own independently optional reported counts — never coerced to
    zero, never summed here (the turn-level sum is a service behaviour, not
    a ledger shape).
    """
    turn_id: TurnId
    sequence: int
    model: str
    ending: ExchangeEnding
    assistant_content: str | None = None
    usage: Usage | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0:
            raise ValueError("sequence must not be negative")


@dataclass(frozen=True)
class ToolCallId:
    """An opaque, stable tool-call ledger identity — cfc's own, distinct
    from `ToolCall.provider_call_id`, which is the provider's exact spelling
    and is never generated.
    """
    value: str

    @staticmethod
    def new() -> "ToolCallId":
        return ToolCallId(_new_id())

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class ToolCall:
    """One accepted call's durable ledger row: cfc's own `id`, which
    exchange and position within its batch it belongs to, and the provider's
    exact spelling (`provider_call_id`, `name`, `arguments`) preserved
    verbatim for replay. `position` is the 0-based order within its batch —
    the order approval, execution, and budgets process calls in.
    """
    id: ToolCallId
    turn_id: TurnId
    exchange_sequence: int
    position: int
    provider_call_id: str
    name: str
    arguments: str

    def __post_init__(self) -> None:
        if self.exchange_sequence < 0:
            raise ValueError("exchange_sequence must not be negative")
        if self.position < 0:
            raise ValueError("position must not be negative")
        if not self.provider_call_id:
            raise ValueError("provider_call_id must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")


class ApprovalDecision(Enum):
    APPROVE = "approve"
    REFUSE = "refuse"


class ToolOutcomeKind(Enum):
    """Every accepted call's exactly-one typed outcome (Concept.md's "Typed
    call outcomes"). Deliberately distinct: a `REFUSAL` (declined, or
    authority denied the concrete target, or a turn budget refused
    execution), an `UNAVAILABLE` capability or root (including an unknown
    tool name), a `CANCELLATION` that arrived before this call's outcome
    won, and a `FAILURE` that is neither of those — never collapsed to a
    single success/failure boolean.
    """
    SUCCESS = "success"
    REFUSAL = "refusal"
    UNAVAILABLE = "unavailable"
    CANCELLATION = "cancellation"
    FAILURE = "failure"


@dataclass(frozen=True)
class ToolResult:
    """One tool call's exactly-one committed outcome: the typed `kind`, a
    bounded cfc-authored `reason`, and `content` — the exact bounded text
    sent back to the provider as this call's `tool` message, stored once as
    canonical replay material (never re-parsed as a provider response, never
    duplicated into operational evidence). `decision`/`decided_at` record
    the approval boundary's own decision when this call reached one; both
    stay `None` for a call that never reached approval (an unknown or
    unavailable tool, or one cut off once a turn budget was already spent).
    """
    tool_call_id: ToolCallId
    kind: ToolOutcomeKind
    reason: str
    content: str
    decision: ApprovalDecision | None = None
    decided_at: datetime.datetime | None = None
    truncated: bool = False

    def __post_init__(self) -> None:
        if self.decided_at is not None:
            _require_aware("decided_at", self.decided_at)


@dataclass(frozen=True)
class ToolCallEvidence:
    """Operational evidence for one accepted call, deliberately body-free:
    identity, authority/root and canonical target, timestamps, the same
    typed outcome and a bounded reason, counts, truncation, a result hash,
    and a character count. Never the tool's raw file text or provider
    response body — that lives once, in `ToolResult.content`, and is never
    duplicated here (Concept.md: "Diagnostic duplication becomes a second
    leak"). `counts` is a small named-integer map (e.g. entries examined,
    matches found) whose exact keys are each tool definition's own concern,
    not this module's.
    """
    tool_call_id: ToolCallId
    definition_name: str
    started_at: datetime.datetime
    finished_at: datetime.datetime
    outcome_kind: ToolOutcomeKind
    reason: str
    character_count: int
    root: str | None = None
    canonical_target: str | None = None
    counts: Mapping[str, int] = field(default_factory=dict)
    truncated: bool = False
    result_hash: str | None = None

    def __post_init__(self) -> None:
        _require_aware("started_at", self.started_at)
        _require_aware("finished_at", self.finished_at)
        if not self.definition_name:
            raise ValueError("definition_name must not be empty")


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
    context_manifest: tuple[ContextManifestEntry, ...] = field(default_factory=tuple)

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
    messages belong on the wire without re-querying SQLite. `exchanges`,
    `tool_calls`, and `tool_results` (Stage 6 loop 1) are the ledger material
    between a tool-using turn's two `messages` rows — flat and grouped by
    `turn_id`/`exchange_sequence` on read, the same convention `messages`
    already uses (see this module's own "durable ledger between a turn's two
    messages" section).
    """
    chat_id: ChatId
    turns: tuple[Turn, ...] = field(default_factory=tuple)
    messages: tuple[Message, ...] = field(default_factory=tuple)
    exchanges: tuple[ProviderExchange, ...] = field(default_factory=tuple)
    tool_calls: tuple[ToolCall, ...] = field(default_factory=tuple)
    tool_results: tuple[ToolResult, ...] = field(default_factory=tuple)


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


@dataclass(frozen=True)
class ProposedToolCall:
    """One call exactly as a provider proposed it, before persistence
    assigns cfc's own `ToolCallId` — the responder boundary's own output
    shape, not yet a ledger row. `arguments` is the raw, unparsed argument
    string; parsing and validating it against a registry definition happens
    at the execution boundary, never here or in `provider_adapter`.
    """
    provider_call_id: str
    name: str
    arguments: str

    def __post_init__(self) -> None:
        if not self.provider_call_id:
            raise ValueError("provider_call_id must not be empty")
        if not self.name:
            raise ValueError("name must not be empty")


@dataclass(frozen=True)
class ToolCallBatch:
    """A responder's typed reply when the provider proposed one or more
    tool calls instead of (or alongside) finishing: the ordered proposals in
    provider order, optional literal assistant content alongside them, and
    optional usage. Provider call ids must be unique within the batch — the
    complete-batch validation the Work Order requires, enforced here so a
    malformed batch cannot be constructed at all, the same discipline
    `FailureEvidence`'s cross-field `__post_init__` already applies.
    """
    calls: tuple[ProposedToolCall, ...]
    assistant_content: str | None = None
    usage: Usage | None = None

    def __post_init__(self) -> None:
        if not self.calls:
            raise ValueError("a tool-call batch must contain at least one call")
        ids = [call.provider_call_id for call in self.calls]
        if len(ids) != len(set(ids)):
            raise ValueError("a tool-call batch's provider call ids must be unique")


#: What an injected responder returns: exactly one of a completion, a
#: failure, a cancellation, or (Stage 6 loop 1) a proposed tool-call batch.
#: The `Responder` protocol itself now lives in `cfc.provider_wire` (Stage 5
#: loop 1): it types on `RequestPlan`, which this module deliberately does
#: not know about (see this module's own docstring: "not OpenAI message
#: dictionaries").
ResponderResult = Union[Completion, Failure, Cancellation, ToolCallBatch]
