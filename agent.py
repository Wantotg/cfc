# agent.py — one chat turn, with tools.
#
# The normal turn (main.py) streams a single response. This one loops: ask,
# maybe get tool calls back, run them, feed the results in, ask again, until
# the model answers with prose or the loop breaker fires.
#
# Not in the handoff's module list. It could live in commands.py next to the
# gate, but it isn't a ':' command — it's the alternative shape of a chat turn.
# main.py chooses between this and stream_response().
#
# Two things are deliberate and easy to get wrong later:
#
#   Non-streaming. Tool-call deltas arrive fragmented and the arguments string
#   has to be reassembled across chunks by index. Streaming stays on the normal
#   path, where it's worth it.
#
#   Every message is persisted, including calls and results. Skipping them
#   would leave a session that replays into an API error, because an assistant
#   message with tool_calls must be followed by its results.
import json

import httpx
from rich.markdown import Markdown
from rich.text import Text

from api import call_api
from commands import DENIED, SKIPPED, TurnApproval, gate_and_dispatch
from db import save_message
import governor
from tools import TOOL_SCHEMAS, written_path
from ui import SPINNER_COLOR, ai_answer_panel, ai_reasoning_panel, console

try:
    from config import TOOLS_MAX_CALLS_PER_TURN
except ImportError:
    TOOLS_MAX_CALLS_PER_TURN = 25
try:
    from config import TOOLS_MAX_TURN_RESULT_CHARS
except ImportError:
    TOOLS_MAX_TURN_RESULT_CHARS = 120_000
import models
from context import chat_context

# The exact string a turn ends with when it runs out of calls. It is a
# **constant, compared by identity** — `runner._turn_with_retry` tests for it to
# turn a truncated routine into a logged failure, and an f-string carrying the
# call count would break that check the moment the two paths used different
# ceilings (which they now do). Don't interpolate anything into it.
LIMIT_MESSAGE = "[tool call limit reached]"

# The turn's total tool output, in characters, and the second of the two budgets
# a turn runs under. It exists because the call ceiling alone does not bound
# what a turn *sends*.
#
# Each loop iteration re-sends the whole conversation, tool results included, so
# the request grows with everything read so far. `TOOLS_MAX_RESULT_CHARS`
# (30,000) bounds one result; nothing bounded their sum. A model let loose on a
# tree could ask for four reads in one message, and the ceiling — which counted
# *iterations*, not calls — happily allowed thirty of them: ~900,000 characters,
# roughly 225k tokens, re-sent on every subsequent call. That is where the
# "your max_tokens is too low" 400s were coming from; the provider computes the
# completion budget as (context - prompt) and reports a negative one in the
# vocabulary of max_tokens, which reads like a setting we don't even send.
#
# Raising the call ceiling makes that *worse*, not better, which is why the two
# changes had to land together: the ceiling is now generous and this is what
# keeps the generosity affordable. Roam widely, read narrowly.
#
# Spending it does not truncate the turn — see _budget_note. Tools are simply
# withdrawn for one final call and the model answers from what it has.
TURN_RESULT_CHARS = TOOLS_MAX_TURN_RESULT_CHARS

# When to start telling the model to wrap up, as a fraction of the call budget.
# Purely advisory and never persisted: it rides on the request for one call.
_NUDGE_AT = 0.75


def _err_result(msg):
    """A tool result carrying a refusal. Same shape tools.py returns, because
    the model must not have to tell our refusals from the jail's."""
    return json.dumps({"error": msg})


def est_tokens(messages):
    """Rough token count for a request. chars/4, the same naive estimate
    chunk.py uses — good enough to answer 'is this obviously too big'."""
    total = 0
    for m in messages:
        total += len(m.get("content") or "")
        for c in (m.get("tool_calls") or []):
            total += len(json.dumps(c))
    return total // 4


def _oversize_reason(messages, model):
    """Why this request is too big to send, or None.

    A backstop, and an honest one: a MODELS record's `limit` holds a **vendor
    claim** (several say 1,000,000), so on the models used here this will
    rarely fire before the provider's real limit does. It costs nothing, and
    when it does fire it turns an opaque provider 400 into a sentence naming
    the number. The load-bearing bound is TURN_RESULT_CHARS above, which does
    not depend on trusting a published context window.
    """
    limit = models.context_limit(model)
    if not limit:
        return None
    est = est_tokens(messages)
    if est <= limit:
        return None
    return (f"[this turn's context is about {est:,} tokens, over {model}'s "
            f"{limit:,} — stopping here rather than sending a request the "
            f"provider will refuse. Start a new session, or read less per turn.]")


def _request_shape(messages, model, calls_used, max_calls, result_chars):
    """What was in flight when a request failed.

    Every provider 400 arrived looking identical — one `[error] HTTP 400` with
    the provider's own words and nothing about *our* side of it. These three
    numbers are what separate the three causes that were wearing that one
    symptom: a context overflow (large est, many results), a malformed
    conversation (small est, early call), and a content filter (neither).
    """
    return (f"[cfc: call {calls_used}/{max_calls}, {len(messages)} messages, "
            f"~{est_tokens(messages):,} tokens, {result_chars:,} chars of tool "
            f"output this turn, model {model}]")


def _render_call(call):
    fn = call.get("function", {})
    args = fn.get("arguments", "")
    try:
        pretty = ", ".join(f"{k}={v!r}"
                           for k, v in json.loads(args or "{}").items())
    except json.JSONDecodeError:
        pretty = args
    console.print(f"  → {fn.get('name')}({pretty})", style="dim")


# How much of a step's reasoning to show on the tool path. This was full text
# and it buried the answer: a tool turn prints one of these *per loop
# iteration*, so a verbose thinking model could push its own conclusion off the
# top of the scrollback. The streaming path tail-limits for a different reason
# (keeping a live region still); here it is purely about not drowning the thing
# you asked for.
#
# Larger than the live panel's 12 because this is scrollback, not a jumping
# region — you can read it. The head *and* tail are kept rather than just the
# tail: on the tool path the opening lines are usually "what am I about to do",
# which is the part worth seeing next to the tool call it explains.
REASONING_HEAD_LINES = 6
REASONING_TAIL_LINES = 10


def _elide(reasoning):
    """Middle-elide to head + tail lines, or return it unchanged if short."""
    lines = reasoning.splitlines()
    keep = REASONING_HEAD_LINES + REASONING_TAIL_LINES
    if len(lines) <= keep + 1:   # +1: eliding one line saves nothing
        return reasoning
    hidden = len(lines) - keep
    return "\n".join(
        lines[:REASONING_HEAD_LINES]
        + [f"    … {hidden} more lines of reasoning …"]
        + lines[-REASONING_TAIL_LINES:]
    )


def _render_reasoning(reasoning):
    """The model's thinking for this step, in the same dim panel the streaming
    path uses, middle-elided so several steps' worth can't bury the answer.

    Nothing is lost that was ever kept: reasoning is presentation-only on both
    paths — never persisted, never replayed to the API. This changes what is
    shown, not what exists."""
    if not (reasoning or "").strip():
        return
    console.print()
    console.print(ai_reasoning_panel(Text(_elide(reasoning), style="dim italic")))


# Your own verdicts, rendered as what they are. **This is a rendering table and
# nothing else** — the payload keeps saying `{"error": "user denied"}`, because
# that is what makes a refusal something the model can adapt to rather than a
# system fault it should apologise for. Keyed off `commands`' own constants, so
# the two ends cannot drift; a literal here would have been the drift.
#
# The wording distinguishes these from `gate_and_dispatch`'s `auto-denied
# <tool>: <why>`, which is the machine refusing and stays an error, styled red.
# "at the prompt" is the half that says which of the two happened.
_HUMAN_VERDICTS = {DENIED: "denied at the prompt",
                   SKIPPED: "skipped at the prompt"}


def _render_result(result, name=None):
    """Show what came back, briefly. The chain has to be legible — that's what
    makes the feature trustworthy — but a 30k-char file would bury it.

    `name` is the tool's, passed in rather than parsed back out of anything: a
    batch renders several of these in a row, and a bare "denied" under the
    third panel is a line you have to count backwards to read.
    """
    try:
        d = json.loads(result)
        if isinstance(d, dict) and "error" in d:
            # **Dim, not dim red, and only for these two exact strings.** The
            # failure to design against is the inverse of the reported one: a
            # real tool error styled as a polite human decline reads as
            # something you chose, so a run that should have stopped keeps
            # going and looks fine doing it. Matching the constants and nothing
            # else is what bounds that — no prefix test, no "looks like a
            # verdict" heuristic.
            verdict = _HUMAN_VERDICTS.get(d["error"])
            if verdict:
                console.print(f"  ← {name + ' ' if name else ''}{verdict}",
                              style="dim")
                return
            console.print(f"  ← error: {d['error']}", style="dim red")
            return
    except (json.JSONDecodeError, TypeError):
        pass
    lines = (result or "").splitlines()
    head = lines[0][:76] if lines else "(empty)"
    console.print(f"  ← {head}", style="dim")
    # Lines *below* the head, not lines in the result. The head has just been
    # printed, so counting it again was an off-by-one against the only number
    # the reader can check — and against `read_file`'s own header, which says
    # `<path> (115 lines)` and then got a `(116 lines)` stacked under it. Two
    # counters counting two different things, one line apart.
    #
    # Counting the remainder makes them agree without either module knowing
    # about the other, which is the point: the alternative — the renderer
    # noticing that the head line already carries a count — would be a producer
    # here and a parser there, the shape `HANDOVER.md` keeps a table of. It also
    # stays honest when `_truncate` has cut the body, where the two numbers
    # *should* differ and now say so.
    if len(lines) > 1:
        console.print(f"    ({len(lines) - 1:,} more lines)", style="dim")


def tools_guidance(max_calls=None):
    """The system message a tools-on chat turn carries, as a one-item list.

    States the two budgets up front rather than only warning when one is nearly
    gone. A model that learns the budget exists by hitting it has already spent
    it on whichever files it happened to open first — and the failure this
    prevents is not a refused call but a turn that browses until the request is
    too large to send.

    A list so a caller can splice it into `prefix` without a conditional, and
    part of the *prefix* rather than of `history`: it is re-sent with every
    call in the turn and persisted with none of them.
    """
    if max_calls is None:
        max_calls = TOOLS_MAX_CALLS_PER_TURN
    return [{"role": "system", "content": (
        f"You can read files with list_dir, read_file and grep, and every call "
        f"is shown to the user for approval. One turn is bounded by "
        f"{max_calls} tool calls and {TURN_RESULT_CHARS:,} characters of total "
        f"tool output; both are shared across everything you open. Reading a "
        f"whole file where a grep or a line range would answer the question is "
        f"what spends them. Work in small steps, and end the turn with an "
        f"answer rather than another read — if the job needs more, say what "
        f"you would do next and stop."
    )}]


def _budget_note(calls_used, max_calls, result_chars):
    """What to tell the model about what it has left, or None.

    This is the "slow down and finish your turn" channel, and it is a rider on
    one request rather than a line in the conversation: the model needs to know
    the budget exists at the moment it is deciding whether to open another
    file, and nothing about that belongs in the transcript afterwards.

    Silent until three quarters of the calls are gone, so an ordinary two-call
    turn never sees it.
    """
    spent = result_chars >= TURN_RESULT_CHARS
    if spent:
        return ("[cfc] You have read this turn's full output budget "
                f"({result_chars:,} characters). Your tools are withdrawn for "
                "this reply. Answer now from what you have read, and say "
                "plainly what you did not get to.")
    if calls_used >= int(max_calls * _NUDGE_AT):
        return (f"[cfc] You have used {calls_used} of {max_calls} tool calls "
                f"for this turn. Stop opening files, finish the work you can, "
                f"and answer. Prefer grep or a line range over reading a whole "
                f"file.")
    return None


def _answer(call, result, history, conn, session_id, model):
    """Record one tool result: into live history and into the DB, together.

    Every dispatched call goes through here, and so does every call that was
    *not* dispatched, because the API's requirement is one result per requested
    call regardless of whether anything ran.
    """
    history.append({"role": "tool",
                    "tool_call_id": call.get("id"),
                    "content": result})
    save_message(conn, session_id, "tool", result, model=model,
                 kind="tool_result",
                 meta={"tool": call.get("function", {}).get("name"),
                       "tool_call_id": call.get("id")})


def _finish(text, history, conn, session_id, model):
    """End the turn with an assistant message of our own making."""
    final = {"role": "assistant", "content": text}
    history.append(final)
    save_message(conn, session_id, "assistant", text, model=model)
    return final


# A thinking model returns the occasional empty completion — a provider hiccup,
# not a size limit; the same context usually answers on a re-roll. On the
# streaming path that arrives as a 200 with empty content, and main.py re-rolls
# it. On the **non-streaming** path the tool loop takes, nano-gpt surfaces the
# same thing as an HTTP 400 whose body reads "The model returned an empty
# response" — so it comes through the exception door and neither main.py's stream
# re-roll nor runner._turn_with_retry (which both key off an *empty return*) ever
# saw it. A routine died on a transient the retry machinery was built to absorb.
#
# The match is on the provider's wording, and that coupling is deliberately
# fail-safe: it recognises ONLY the empty-response 400 and nothing else. An
# oversize 400 — or any other — must keep raising, because re-rolling it re-sends
# an identical doomed request and spends the whole budget on it. If nano-gpt ever
# rewords this, we stop recognising it and fall straight back to the hard-fail
# path below, which is the current behaviour — never a new silent pass. Same
# provider-wording hazard the codebase flags for LIMIT_MESSAGE and the litter
# markers; the fail direction is what makes it safe.
_EMPTY_COMPLETION_MARK = "empty response"


def _is_empty_completion_400(err):
    return _EMPTY_COMPLETION_MARK in str(err).lower()


def _say_empty():
    """Announce an empty turn. Used by **both** ways this loop can produce one.

    The tool path has two: a 200 whose content is empty, and the provider's 400
    that means the same thing. They used to announce differently — the 400 said
    "provider hiccup", the 200 said nothing at all and left `main.py` painting a
    blank answer panel — so the same event looked like two different bugs
    depending on which door it came through.

    It lives here rather than in the caller because *which* kind of empty this
    was is knowledge this module has and its callers don't. What the caller
    owns is the decision to re-roll, and that is shared with the streaming path
    (`commands.empty_completion_decision`) precisely so the two cannot drift.
    """
    console.print("\n[the model returned no answer — provider hiccup, "
                  "common on thinking models]")


def agent_turn(prefix, history, model, conn, session_id, ctx=None,
               max_calls=None, touched=None, first_message=None,
               instruction=None, params=None):
    """Run a turn that may use tools. Returns the final assistant message.

    `params` is the optional validated preset dictionary (v1.5,
    `models.preset_params`), passed through unchanged to every `call_api`
    call inside the loop below — so a multi-step tool turn samples under the
    same preset on every round trip, not just the first. `None` (the
    default) is what every caller except the interactive ordinary turn
    passes — routines, and any future internal use, are unaffected.

    Takes the system `prefix` and `history` separately, and appends every
    message it produces to `history` — which is the list the REPL replays from
    on the next turn.

    `first_message` and `instruction` are the governor's envelope pieces (see
    `governor.compile_messages`): the session's frozen opening and at most one
    compiled cfc direction. `split` is captured once, here, at `len(history)`
    before the loop appends anything — which is what keeps the direction
    pinned at its original position across every call in the loop instead of
    being re-appended after each tool result. Neither is ever written into
    `history`, so neither is persisted or replayed.

    The handoff's signature was agent_turn(messages, ...), mutating one
    combined list. That list is rebuilt each turn from history + system
    prompts, so the calls and results would be saved to the database and then
    vanish from live context until the session was reopened: the model would
    forget it had just read a file.

    `touched`, if given, is a list this appends every successfully written file
    to. **A collector rather than a second return value**, because only the
    runner reads it: a routine passes one, chat passes nothing, and the
    signature stays honest about who cares. It also survives the paths where
    there is no useful return value to carry it — the call-ceiling exit, and a
    caller that re-rolls and throws its history away — which is exactly when
    "what did it manage to write" is worth asking.
    """
    # An interactive chat turn: gated, always. ToolContext.for_chat cannot
    # produce an ungated context, so there is no config or argument that turns
    # the gate off from here.
    #
    # `ctx` is the routine runner's injection point, and it is a parameter
    # rather than a global on purpose: a global would make "which scope is this
    # turn under" depend on execution order, which is exactly the property you
    # cannot audit. Passing None still means chat, so every existing caller —
    # and every test that patches chat_context — is unchanged.
    ctx = ctx or chat_context()
    approval = TurnApproval()

    # A parameter, for the same reason `ctx` is one: the budget belongs to the
    # caller, not to whoever imported the module last. It is deliberately NOT on
    # ToolContext — that object is the permission boundary ("who is asking and
    # what may they touch"), and a call count is capacity, not permission.
    # Reading the module global at call time (not as a default argument) is what
    # keeps `test_agent`'s monkeypatch of TOOLS_MAX_CALLS_PER_TURN working.
    if max_calls is None:
        max_calls = TOOLS_MAX_CALLS_PER_TURN

    # Two budgets, counted here rather than by the loop's shape.
    #
    # `calls_used` counts **tool calls, not iterations**, which is what the
    # parameter has always claimed to count and never did: `for _ in
    # range(max_calls)` bounded trips round the loop, and a model that asks for
    # four reads in one assistant message spends one trip. Eight iterations
    # could be thirty-odd calls, so the one number a user could see and tune
    # bounded neither the work nor the context. A call that is refused for
    # budget still counts — it cost a round trip, and counting it is also what
    # guarantees the loop terminates.
    calls_used = 0
    result_chars = 0
    # Captured before the loop appends anything of its own — see the
    # docstring's note on `split`.
    split = len(history)

    while calls_used < max_calls:
        messages = governor.compile_messages(
            prefix, first_message, history, instruction, split=split)

        too_big = _oversize_reason(messages, model)
        if too_big:
            return _finish(too_big, history, conn, session_id, model)

        # Advisory riders, added to *this request only* — never to `history`,
        # so they are not persisted, not exported and not replayed. Same
        # discipline as reasoning: the DB holds the conversation, not our
        # asides to the model.
        note = _budget_note(calls_used, max_calls, result_chars)
        if note:
            messages = messages + [{"role": "system", "content": note}]

        # Once the turn's output budget is spent the tools come off the
        # request. The model then has to answer in prose, which ends the loop
        # in one more round trip with a real answer instead of a stub. This is
        # deliberately NOT how the call ceiling exits — see LIMIT_MESSAGE.
        offer = None if result_chars >= TURN_RESULT_CHARS else TOOL_SCHEMAS

        # call_api blocks with nothing on screen — the streaming path shows a
        # spinner here, so the tool path does too. Not streaming: the spinner
        # is the whole feedback, from request to response.
        with console.status("Thinking...", spinner="dots",
                            spinner_style=SPINNER_COLOR):
            try:
                # Passed only when set: a stub or a caller with the pre-1.5
                # `call_api(messages, model=, tools=)` shape keeps working
                # unchanged when no preset is active, which is every call
                # except the interactive ordinary turn's.
                call_kwargs = {"params": params} if params else {}
                resp = call_api(messages, model=model, tools=offer,
                                **call_kwargs)
            except httpx.HTTPError as e:
                # An empty-completion 400 is the benign thinking-model hiccup,
                # not a real failure — map it back onto the empty-completion path
                # the callers already own by returning an empty message. runner's
                # _turn_with_retry then re-rolls it (bounded, and fails the run
                # loudly if it persists); the interactive tool path drops the
                # turn, same as it does a 200-empty. Persisted like any empty
                # completion the loop produces, so the routine's audit transcript
                # shows the hiccup. Every OTHER 400 keeps the raise path below.
                if _is_empty_completion_400(e):
                    _say_empty()
                    return _finish("", history, conn, session_id, model)
                # Re-raised as the same class, so every existing `except
                # httpx.HTTPError` still matches, with our side of the request
                # appended to the provider's words. main.py prints it and
                # runner.py logs it; both were showing a bare status code.
                enriched = httpx.HTTPError(
                    f"{e} {_request_shape(messages, model, calls_used, max_calls, result_chars)}"
                )
                # api.py owns the status code.  Keep it as structured data
                # while adding this loop's useful request context, so the
                # routine runner can make its retry decision without parsing
                # either our wording or the provider's.
                if hasattr(e, "status_code"):
                    enriched.status_code = e.status_code
                raise enriched from e
        usage = resp.get("usage") or {}
        msg = resp["choices"][0]["message"]
        calls = msg.get("tool_calls")

        # Thinking models return their reasoning here too (non-streaming), where
        # it was previously discarded. Render it before this step's tool calls or
        # final answer, so the tool path shows reasoning like the stream path.
        # It's presentation only — never persisted or replayed into the API.
        _render_reasoning(msg.get("reasoning"))

        # Normalise: the API may omit content entirely on a tool call, but our
        # own history and renderers expect the key to exist.
        msg = {"role": "assistant", "content": msg.get("content") or "",
               **({"tool_calls": calls} if calls else {})}
        history.append(msg)
        # Persist this call's usage so the post-turn bar and /status work on the
        # tool path — the whole reason both went blank when tools took over.
        save_message(conn, session_id, "assistant", msg["content"],
                     model=model,
                     tok_in=usage.get("prompt_tokens") or None,
                     tok_out=usage.get("completion_tokens") or None,
                     kind="tool_call" if calls else "chat",
                     meta={"tool_calls": calls} if calls else None)

        if not calls:
            # Both empty exits announce, so the caller's retry decision never
            # has to work out which door this came through — and a 200 with
            # empty content stops being the silent one of the pair. See
            # `_say_empty`.
            if not msg["content"].strip():
                _say_empty()
            return msg

        if msg["content"].strip():
            console.print()
            console.print(msg["content"], style="dim")

        # **Every call in this message gets exactly one result, on every path
        # out of here — including an exception.** An unanswered call rejects
        # the conversation forever after. See HANDOVER.md standing decision 2.
        answered = set()
        try:
            for call in calls:
                _render_call(call)
                calls_used += 1
                if calls_used > max_calls:
                    result = _err_result(
                        f"not run: this turn's budget of {max_calls} tool "
                        f"calls is spent. Answer with what you have.")
                elif result_chars >= TURN_RESULT_CHARS:
                    result = _err_result(
                        f"not run: this turn has already read "
                        f"{result_chars:,} characters, its whole output "
                        f"budget. Answer with what you have.")
                else:
                    result = gate_and_dispatch(call, approval, ctx)
                    result_chars += len(result or "")
                _render_result(result, call.get("function", {}).get("name"))

                fn = call.get("function", {})
                # Recorded at the point it succeeded, from the result rather
                # than from the arguments: the model's requested path is what
                # it asked for, and this wants what actually landed.
                if touched is not None:
                    wrote = written_path(fn.get("name"), result)
                    if wrote is not None and wrote not in touched:
                        touched.append(wrote)

                _answer(call, result, history, conn, session_id, model)
                answered.add(call.get("id"))
        finally:
            for call in calls:
                if call.get("id") in answered:
                    continue
                _answer(call, _err_result(
                    "not run: the turn was interrupted before this call."),
                    history, conn, session_id, model)

    # A real assistant message, shown to the user, not a silent truncation.
    #
    # The call ceiling exits here and the *output* budget deliberately does
    # not. The difference is who wrote the last message: LIMIT_MESSAGE is a
    # stub we insert because the model produced nothing, and runner.py reads it
    # (by identity) to log a truncated run as failed. A turn that spends its
    # output budget instead loses its tools for one more call and answers in
    # its own words, having been told why — that is a real answer about a real
    # partial job, not silence dressed up as one.
    return _finish(LIMIT_MESSAGE, history, conn, session_id, model)


def render_answer(text):
    console.print()
    console.print(ai_answer_panel(Markdown(text or "")))
