# SYSTEM_INJECTIONS.md

Every place cfc puts words in front of the model that the model didn't say and
the user didn't type — the system-layer injection seams. Written up once,
here, because the alternative is re-deriving "what does the model actually
see" by reading five files under time pressure, which is exactly how a seam
goes stale without anyone noticing.

**This document is checked, not authoritative.** `tests/test_system_injections.py`
derives the same inventory mechanically from source — every function that
literally constructs a `{"role": ...}` message dict — and fails if the two
disagree in either direction: a producer that exists in source but not here,
or an anchor here that no longer resolves to anything. That is also why the
`Anchor` field is kept narrow: it names a source symbol and nothing else. No
product behaviour reads this file; only the test parses it, and only that one
field.

**Format.** Each entry below carries a stable `Anchor: `module.function`` line
— the derivation the test compares itself against — and four things prose
alone would drift on: where in the request the content lands, whether it is
durable (persisted, replayed on reopen) or request-only (built fresh, never
saved), who calls it, and what a caller sees when it fails.

## Exclusions

Three shapes construct a `{"role": ...}` dict without being a system-layer
injection, and the test's derivation excludes them structurally rather than
guessing from names:

- **Ordinary durable chat rows.** `main._run_turn` appends the user's own
  typed text and the model's own returned answer to `history`, unmodified —
  replaying what already happened, not manufacturing new content. (The test
  excludes this one function by name; everything else below is discovered,
  not listed by hand.)
- **Provider-produced assistant/tool-call rows.** The API's own reply gets
  wrapped into `history`'s shape (a missing `content` key normalised to `""`
  so replay doesn't choke on it) inside `agent.agent_turn` — see that entry
  below, which also carries a real injection and so cannot be excluded
  wholesale.
- **Tool results.** A literal `role: "tool"` is always a tool's own result —
  `agent._answer` is the one place that builds one, and the OpenAI-shaped API
  assigns that role to nothing else in this codebase. The test excludes any
  `role` literal equal to `"tool"` categorically, rather than naming
  `agent._answer` specifically.

Also structurally excluded, with no rule needed: `db.py`'s message row passes
`role` in as a **parameter**, not a literal — it is already whatever the
caller decided, not a place that invents one.

---

## 1. Assembled prompt, persona, and traits

Anchor: `assemble.assemble_system`

**Landing point:** request position 1 — persona, then system prompt, then
traits (attach order), one `system` message per non-empty layer.

**Durable or request-only:** request-only. The envelope itself is never
saved; the pool files it reads (persona/prompt/trait bodies) are the durable
objects, re-read live on every turn.

**Callers:** `main._run_turn`, once per turn, for both the streaming and the
tool path.

**Visible failure direction:** a blank pool file contributes nothing rather
than an empty `system` message — silent by design (assemble.py's own
docstring: "a blank prompt file is not a blank system message; it is an
absent one"). A pool item whose file has since been deleted is silently
skipped here too; that is reported once, in `/status`, not on every turn.

## 2. First Message and the governor's direction

Anchor: `governor.compile_messages`

**Landing point:** position 2 (the session's frozen First Message, as an
`assistant` turn) and position 4 (at most one compiled `[cfc direction]`, as
a `user` turn) of the request envelope.

**Durable or request-only:** First Message is durable — frozen once per
session (`db.get_first_message`), replayed identically on every turn and on
reopen. The direction is request-only: built fresh from `governor.wrap`,
never appended to `history`.

**Callers:** `agent.agent_turn` (once per tool-loop round trip, at a `split`
fixed at loop entry so the direction doesn't re-appear after every tool
result) and `main._run_turn`'s streaming path (once per turn).

**Visible failure direction:** no First Message → nothing inserted (most
sessions don't have one — silent and correct). No instruction → nothing
inserted. A trait named for the periodic reminder whose file has since gone
is reported as missing in the dim `cfc -> ...` line rather than silently
dropped (see `governor.ordinary_instruction`).

## 3. Tool guidance

Anchor: `agent.tools_guidance`

**Landing point:** appended to the prefix only on a turn that actually offers
tools (`use_tools` true) — a tools-off turn is byte-for-byte the request it
always was.

**Durable or request-only:** request-only, never persisted.

**Callers:** `main._run_turn`, tool path only.

**Visible failure direction:** none to speak of — a fixed template with the
call ceiling interpolated in; nothing about it depends on runtime state that
could go missing.

## 4. The tool turn's own advisory rider

Anchor: `agent.agent_turn`

**Landing point:** a `system` message appended to the request only once the
turn's output budget is running low (`agent._budget_note`), inside the tool
loop, after `governor.compile_messages` and before the call.

**Durable or request-only:** request-only — "never to `history`, so they are
not persisted, not exported and not replayed" (agent.py's own comment). This
same function also normalises the provider's own reply into `history`'s
shape a few lines later (the excluded "provider-produced" case above); that
half is response handling, not an injection, and is named here rather than
hidden only because both live in the one function the test discovers.

**Callers:** itself, from within the tool loop — reached from
`main._run_turn` (chat) and `runner.run_routine` (routines).

**Visible failure direction:** `_budget_note` returns `""` once nothing needs
saying, and a falsy note adds nothing — silent, and correct: most turns never
approach either budget.

## 5. The tool turn's synthetic stand-ins

Anchor: `agent._finish`

**Landing point:** ends a tool turn early with cfc's own text in place of a
real model answer — an oversize-request refusal, an empty-completion
stand-in (`""`), or `LIMIT_MESSAGE` when the call ceiling is spent.

**Durable or request-only:** durable. Persisted via `save_message` and
appended to `history`, so it replays in later turns exactly as a genuine
answer would — which is deliberate: `LIMIT_MESSAGE` is compared by identity
in `runner`, and the scar it exists to prevent is "a routine that did
nothing logged `ok`."

**Callers:** `agent.agent_turn`, all three early exits.

**Visible failure direction:** the stand-in text is explicit rather than
blank on purpose — an empty completion still needs to *say* it was empty, or
the run log reads as a clean success.

## 6. A routine's own opening turn

Anchor: `runner._turn_with_retry`

**Landing point:** the sole `user` message of a routine's own turn — the
routine's task text, rebuilt fresh on every retry attempt.

**Durable or request-only:** request-only per attempt. The task text itself
is saved once, before this runs, by `runner.run_routine`
(`save_message(..., "user", task, ...)`) — this function's own dict is a
disposable copy of it for one call.

**Callers:** `runner.run_routine`.

**Visible failure direction:** n/a — the task is always non-empty (a
routine's prompt file, already validated at save time).

## 7. A routine's assembled system context

Anchor: `runner.run_routine`

**Landing point:** request position 1 for a routine turn — the routine's own
prompt file content, after placeholder substitution
(`runner.fill_placeholders`, below).

**Durable or request-only:** request-only. Not itself saved; the routine's
prompt *file* is the durable object.

**Callers:** `main.py`'s `/routine` and the routines screen's `run`, and
`schedule.cli` for a scheduled tick — all through `runner.run_routine`.

**Visible failure direction:** an unrecognised `{{placeholder}}` is reported
as a warning `event()` line in the run log (naming the known set) rather than
silently reaching the model as literal `{{...}}` text — standing decision 12.

## 8. Recall's grounded synthesis

Anchor: `recall.recall`

**Landing point:** its own one-shot `system` + `user` pair, sent through
`call_api` entirely separately from the chat's own request — never merged
into the chat's prefix or `history`.

**Durable or request-only:** request-only and ephemeral. This exact pair is
never persisted; what *can* be persisted is the excerpt block a user chooses
to inject with `/remember` (a different anchor, below) — recall's synthesis
is a read, not a write.

**Callers:** `commands.do_recall`.

**Visible failure direction:** the three distinguishable zero-hit outcomes
named in `HANDOVER.md` — embedder unreachable, nothing indexed, or searched
and missed — never collapse to one silent "no answer."

## 9. Title generation

Anchor: `api.generate_title`

**Landing point:** its own one-shot `system` + `user` pair, structurally the
same shape as recall's synthesis call, for a session's title — never touches
the chat's own request.

**Durable or request-only:** request-only and ephemeral.

**Callers:** `main._finish_turn`, gated to the first successful ordinary
chat turn (`turn_count == 1`) — see `main.py`.

**Visible failure direction:** raises `api.TitleGenerationError` rather than
returning a `"(untitled)"` sentinel (v1.4.1, `D-13`). The caller decides what
to show (`main._finish_turn` prints one yellow line) and logs the failure
with `errorlog.log_error(..., where="title")`.

## 10. `/remember`'s excerpt block

Anchor: `commands.do_remember`

**Landing point:** a `user`-role message built from `build_envelope`,
appended straight into live `history` — so it rides every later request in
this session exactly like a typed message, until `/remove excerpts` peels it
back off.

**Durable or request-only:** durable in the live session (`history` and
`injected`), but only the `[:remember "..."]` marker line — not the excerpt
block itself — is what reaches the database; see the recurring-hazard table
in `HANDOVER.md` for that marker's own producer/parser pair.

**Callers:** `commands.do_recall`'s `/remember` verb path.

**Visible failure direction:** `search.why_empty` names why nothing came
back rather than injecting a silently empty block.

## 11. An attachment's envelope

Anchor: `commands.do_attach`

**Landing point:** a `user`-role message built from `attach_wrapper`,
appended to `history`.

**Durable or request-only:** durable — a real message row
(`save_message(..., kind="attachment")`), unlike a `/remember` injection,
because an attachment is what the conversation is *about* and should come
back on reopen.

**Callers:** `main.py`'s `/attach` handler.

**Visible failure direction:** a too-large attachment is refused, visibly,
before any message is built — never silently truncated.

---

## Indirect transforms (checked, not discovered)

These two do not construct a `{"role": ...}` dict themselves — one edits text,
the other edits an existing dict's keys — so the mechanical scan above cannot
find them. They are checked a different way: the test resolves each name
directly (import the module, confirm the attribute exists) rather than via
the AST derivation.

Anchor: `runner.fill_placeholders`

Text substitution on a routine's task before `runner.run_routine` assembles
it into a request — see family 7, above, for the request this feeds.

Anchor: `api.wire_messages`

The outbound shape transform at the wire boundary, applied by both
`api.call_api` and `api.stream_response`: drops an empty `content` key from
an assistant message that carries `tool_calls`, because some providers want
that key absent rather than `""`. Request-only, applied fresh on every call;
never mutates `history`. This is `BUGS.md`'s `B-01` surviving suspect — see
that entry for why it lives at the wire boundary rather than at either call
site.
