# HANDOVER.md

**Current authority from the 2.0 entry gate.** This file records the live
technical contract for the refactor. The completed 1.x system, its exact module
map, settled decisions, rejected designs, scars, and open threads are frozen in
[`archive/HANDOVER v1.9.1.md`](archive/HANDOVER%20v1.9.1.md). Read that
record for original rationale; do not treat its implementation details as the
2.0 architecture.

If this file and the code disagree, the code is right and this file is stale.
The Manager reconciles documents after a completed loop; the Reviewer audits
this file against the code and its real proof.

## What owns what

One maintained fact has one owner. This file carries compact technical
decisions, reasoning, recurring hazards, and development-loop context. It is
not a release history, issue tracker, or general index.

| Document | Owns |
|---|---|
| `README.md` | project introduction and short power-user route |
| `documents/` | public explanation written against the application that ships |
| `development/CHANGELOG.md` | what changed, when, and why it mattered |
| `ROADMAP.md` | Cas's shipped-version record |
| `development/BUGS.md` / `development/BACKLOG.md` | active broken behaviour / owed working behaviour |
| `workspace/TRACKER.md` | permanent ids and each open finding's destination |
| `archive/TRACKER_CLOSED.md` | closed tracker rows and their reasons |
| private roadmaps | active and later plans |
| `workspace/2.0 the refactor and beyond/` | settled 2.0 contracts and preparation |
| `archive/HANDOVER v1.9.1.md` | frozen 1.x technical record |

`agents/`, `scratchpad/`, `personal/`, and `workspace/` are private
working areas. `scratchpad/` handoffs are disposable. Removed tracked
material remains recoverable through Git history; `archive/` contains only
material deliberately retained there.

## The 2.0 boundary

Cooking for Cats 2.0 is a managed rewrite based on v1.9.1. It becomes a
user-controlled AI workspace: chat is the main interaction, durable knowledge
is human-readable, and tools and failures are inspectable.

The release proves three foundations:

1. a general tool boundary, first demonstrated by bounded DuckDuckGo
   `web_search`;
2. a Textual interface that owns input, rendering, focus, screens, modals,
   mouse events, and background-work presentation;
3. a data split: vault for human-readable knowledge, SQLite for application
   and operational records, and Qdrant for rebuildable retrieval
   representations.

2.0 restores ordinary chat, Main chat, private chat, the vault, and controlled
tools under these contracts. It replaces old recall with a smaller, honest
retrieval proof. Routines and scheduling are 2.1 operational-depth work. It
does not promise old module names, schemas,
commands, layouts, test files, database compatibility, browser control,
messaging, desktop action, automatic memory, or a finished TUI.

The settled 2.0 contracts in `workspace/2.0 the refactor and beyond/` own the
full product, data, tool, interaction, workflow, recovery, and environment
decisions. This file holds the rules that stay true while their build sequence
is planned.

## Live behavioural rules

1. **Validate the target before changing state.** A database write, migration,
   test, file operation, or other mutation establishes its intended target
   before it happens.
2. **Every accepted tool call ends once.** It has exactly one success, refusal,
   failure, or cancellation outcome in live and replayed history. Interrupted
   work cannot leave a provider-invalid conversation.
3. **Execution enforces authority.** Approval expresses user intent; the
   execution boundary decides whether an action is permitted. Earlier UI checks
   never replace the boundary.
4. **Containment precedes exceptions.** Capabilities begin with structural
   limits on what they can reach. Denial rules may narrow that authority; no
   caller, model, or interface request broadens it.
5. **Turn paths share an ending contract.** Streaming, tool-using, and later
   paths agree on completion, cancellation, stored history, usage evidence,
   and failure even when they render differently.
6. **Routines are reconstructable and validated twice when they return in
   2.1.** A durable definition contains the information needed to reconstruct
   and validate it. Creation gives early feedback; save and load remain
   authoritative.
7. **Private chat is locally ephemeral by structure.** cfc persists no private
   conversation, request, error, tool history, retrieval activity, or automatic
   export. SQLite and Qdrant are unavailable to it. A provider or explicitly
   enabled network tool may receive approved material, and the interface says
   so before it does.
8. **Identity survives a rename.** A filename is not durable knowledge
   identity. Retrieval and deletion follow a stable source identity.
9. **Each command surface has one definition.** Parsing, dispatch, help, and
   documentation derive from one owner or are checked against it. Unknown
   management input refuses visibly; model input is accepted only on a surface
   that clearly accepts it.
10. **Deletion reaches every derived representation.** A deleted canonical
    source cannot remain retrievable or join to a later object.
11. **Status renders canonical state.** Readiness, due state, outcome, and
    review-needed remain separate facts. A status surface reports the state the
    behaviour uses and names a recovery route where one exists.
12. **Destructive work has proportionate recovery.** Before changing unique
    durable material, cfc revalidates the target and provides a verified undo
    or recovery route. An irreversible outside-world action says that recovery
    is unavailable before approval.

## Data and retrieval

The vault owns human-readable material that a person meaningfully reads, edits,
exports, or approves. SQLite owns cfc-managed application and operational
records: chats, messages, tool outcomes, jobs, errors, timings, retrieval
runs, embedding work, and debugging evidence.

Qdrant holds derived chunks, summaries, embeddings, and metadata. No unique
fact exists only in Qdrant during 2.0. Its first collection is reproducible
from a named source snapshot and experiment manifest; it is not a live
synchronization claim and is read-only from the model's perspective.

The Stage 3 ordinary-chat kernel has one provider-wire history rule: completed
turns contribute both literal messages; failed, cancelled, and interrupted
turns retain their user message in SQLite but omit that orphan from the next
provider request and expose its turn identity and state in an omission
account; the one current active turn contributes its user message. The pure
converter refuses an incoherent snapshot before HTTP. This keeps stored
history provider-independent while making an unsuccessful turn's omission
visible rather than silently replaying it.

Stage 3 owns a database target through one non-blocking `flock` held on that
target's own file descriptor for the store's lifetime. Existing targets are
classified from the locked descriptor's header before SQLite opens them, and
the pathname is revalidated against that descriptor before proceeding. A
foreign, incompatible, corrupt, or empty target refuses without cfc creating
or deleting `.lock`, `-wal`, or `-shm` sidecars; the old sidecar protocol is
retired and is not a cross-version compatibility promise. A usable target must
also open read-write, so operating-system acquisition failures become the
store's bounded `TargetUnusable` refusal rather than escaping as raw errors.

At the provider boundary, exactly 200–299 is success and every other HTTP
status is typed evidence before the body is interpreted. A successful response
with an object-shaped top-level error has a fixed bounded malformed-response
reason, while provider text remains untrusted and unpersisted. Usage is
separate from absence: supported whole-number spellings are normalised,
explicit zero survives, and present invalid counts refuse the response rather
than being silently discarded.

SQLite and Qdrant formats are development interfaces until Cas deliberately
adopts a stable-data promise. An incompatible database refuses visibly and
explains deletion or rebuild; it is never silently reinterpreted, partially
migrated, or overwritten. Vault material, approved human-readable knowledge,
configuration, private planning, and repository history remain durable.

## Tool authority and interaction

An ordinary interactive tool asks for per-call approval. A configured agent or
routine may receive a narrow standing grant for declared inputs, tools, and
targets; it does not create authority to invent new tools or targets. Every
tool lifecycle leaves proportionate operational evidence while storing as
little sensitive content as practical. Private chat creates no local
operational record.

The first non-file proof is bounded DuckDuckGo `web_search`. It declares its
outgoing query and supplied context, uses the common authority and typed-outcome
path, and records success, refusal, failure, or cancellation. Browser control,
result-page fetching, messaging, email, vision, and desktop control remain
later work.

Textual alone owns live terminal input and rendering. The first interaction
slice opens on a Hub and provides ordinary and private chats plus a working Chat
screen. On a wide terminal, Chat retains a narrow stored-chat switcher; on a
narrow terminal, it collapses it. The composer stays available while the
conversation scrolls.

`Enter` sends, `Shift+Enter` creates a newline, and `Esc` first closes a
modal, then cancels an active prompt, then returns to the Hub. Quit is separate
from going back. A tool approval returns focus to its composer. Keyboard and
mouse invoke the same actions; literal user and model text remains selectable,
copyable, and uninterpreted as UI markup. Background work keeps progress,
cancellation, completion, and failure visible without corrupting typed text.

## Workflow and release rules

Every implementation loop has five numbered sessions:

1. Designer reads `Idea.md` and writes `Concept.md`.
2. Drafter reads `Concept.md` and `workspace/TRACKER.md`, then writes `Work Order.md`.
3. Coder reads `Work Order.md`, implements and proves the bounded claim, then writes `Update.md`.
4. Debugger reads `Update.md` and Cas's playtest, diagnoses every finding, then writes `Report.md`.
5. Manager reads a completed `Report.md` and reconciles durable records.

Designer and Drafter begin every new loop. A missing named input is a hard
stop; no specialist reconstructs it from source or an earlier loop. Debugger
routes blocking work before Manager closes the loop.

Brainstormer, Planner, Reviewer, and Overseer run outside the numbered loop.
Brainstormer maintains `workspace/CANDIDATES.md`; Planner maintains private
roadmaps; Reviewer audits this file against code and documents; Overseer
redesigns the repository and workflow. Cas writes `Idea.md` from the active
roadmap, tracker, and his direction.

Every completed playtest produces `Report.md`. A completed loop does not imply
a release. Cas decides when an accumulated version theme earns a tag and
supplies any version or reflection material for that tag. Every released
version, including a patch, receives a verified annotated tag.

For each loop: build, commit, and push; Cas playtests the pushed state;
findings are triaged; then the Manager reconciles records. Backup confirmation
and explicit authority remain required before private-record edits, a closeout
commit, push, tag, tag push, or handoff clearing. A Coder's completed build is
not held behind that later gate.

## Proof and recovery

The Drafter assigns proportionate proof before implementation. Automated proof
covers deterministic behaviour and safety boundaries. Cas's playtest judges
visual behaviour, usability, real-provider interaction, and retrieval quality
against real data. A baseline changes only after its difference is inspected
and tied to an intentional design or data change.

Recovery advice is behaviour, not commentary: proof must exercise the situation
in which the advice appears, including whether the target already exists and
could be lost. When one rule or message covers several failure cases, proof
must check each case where the consequence differs.

Before a loop overwrites, deletes, relocates, or reinterprets unique durable
material, its work order names the material at risk, recovery source,
verification before mutation, partial-failure state, and resumption route.
Development SQLite databases and Qdrant collections may be disposable; their
incompatibility still refuses visibly and supplies a rebuild route.

The refactor preserves these failure classes even when it replaces their old
tests or implementations:

- interruption cannot leave malformed tool or conversation history;
- deletion cannot leave stale retrievable knowledge;
- when 2.1 restores routines, one that did no useful work cannot report
  uncomplicated success;
- when 2.1 restores scheduling, execution chooses model and time inputs
  explicitly;
- tests do not touch personal configuration or live data;
- chunk boundaries preserve indexed text;
- generated names and identities advance under collisions;
- a replacement audits recovery paths its new invariant removes;
- persisted producer/parser formats round-trip through their real producer;
- numeric-looking fields and old routine files pass through their reader;
- promised interactions use the actual input stack; and
- user and model text remains literal UI content.

The v1.9.1 archive is the frozen provenance for these hazards. A retained
failure class gets a behavioural regression test, migration or compatibility
fixture, general engineering rule here, or a recorded retirement before its old
proof disappears.

## Environment

A fresh clone reaches ordinary chat with supported Python and dependencies, a
local configuration derived from the example, one usable chat provider, and a
new compatible SQLite database. Vault, embedding endpoint, Qdrant, tools, and
Git integration configure independently and disable their own surface with a
visible explanation when unavailable. Routines and scheduling are not 2.0
surfaces; their configuration begins with the 2.1 operational-depth work.

`config.py` remains private and ignored. `config.example.py` documents each
supported field and safe default without exposing paths or credentials. Git
protects source and history, and may protect the vault's human-readable wiki;
it does not version live SQLite or Qdrant data. Integrity-checked SQLite
snapshots protect compatible operational data. A local snapshot and an
off-machine copy are different protections.

## Entry-gate record

v1.9.1 is the retained 1.x endpoint. Every earlier tracker row has one recorded
outcome: finish before 2.0, rebuild as 2.0 work, defer beyond 2.0, or close
deliberately with a reason. `B-01`, the historical non-reproducing provider
400 on tool turns, closed as unresolved but no longer owed after it did not
recur through v1.9.1. A future recurrence is a new finding linked to that
record and uses current typed evidence.
