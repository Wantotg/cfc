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

from rich.markdown import Markdown
from rich.text import Text

from api import call_api
from commands import TurnApproval, gate_and_dispatch
from db import save_message
from tools import TOOL_SCHEMAS
from ui import SPINNER_COLOR, ai_answer_panel, ai_reasoning_panel, console

try:
    from config import TOOLS_MAX_CALLS_PER_TURN
except ImportError:
    TOOLS_MAX_CALLS_PER_TURN = 8
from context import chat_context

LIMIT_MESSAGE = "[tool call limit reached — TOOLS_MAX_CALLS_PER_TURN]"


def _render_call(call):
    fn = call.get("function", {})
    args = fn.get("arguments", "")
    try:
        pretty = ", ".join(f"{k}={v!r}"
                           for k, v in json.loads(args or "{}").items())
    except json.JSONDecodeError:
        pretty = args
    console.print(f"  → {fn.get('name')}({pretty})", style="dim")


def _render_reasoning(reasoning):
    """The model's thinking for this step, in the same dim panel the streaming
    path uses. Shown full, not tail-limited: unlike the live panel there's no
    region to keep from jumping — this prints once, complete, into scrollback,
    like the tool call/result lines below it."""
    if not (reasoning or "").strip():
        return
    console.print()
    console.print(ai_reasoning_panel(Text(reasoning, style="dim italic")))


def _render_result(result):
    """Show what came back, briefly. The chain has to be legible — that's what
    makes the feature trustworthy — but a 30k-char file would bury it."""
    try:
        d = json.loads(result)
        if isinstance(d, dict) and "error" in d:
            console.print(f"  ← error: {d['error']}", style="dim red")
            return
    except (json.JSONDecodeError, TypeError):
        pass
    lines = (result or "").splitlines()
    head = lines[0][:76] if lines else "(empty)"
    console.print(f"  ← {head}", style="dim")
    if len(lines) > 1:
        console.print(f"    ({len(lines):,} lines)", style="dim")


def agent_turn(prefix, history, model, conn, session_id):
    """Run a turn that may use tools. Returns the final assistant message.

    Takes the system `prefix` and `history` separately, and appends every
    message it produces to `history` — which is the list the REPL replays from
    on the next turn.

    The handoff's signature was agent_turn(messages, ...), mutating one
    combined list. That list is rebuilt each turn from history + system
    prompts, so the calls and results would be saved to the database and then
    vanish from live context until the session was reopened: the model would
    forget it had just read a file.
    """
    # An interactive chat turn: gated, always. ToolContext.for_chat cannot
    # produce an ungated context, so there is no config or argument that turns
    # the gate off from here.
    ctx = chat_context()
    approval = TurnApproval()

    for _ in range(TOOLS_MAX_CALLS_PER_TURN):
        messages = list(prefix) + history
        # call_api blocks with nothing on screen — the streaming path shows a
        # spinner here, so the tool path does too. Not streaming: the spinner
        # is the whole feedback, from request to response.
        with console.status("Thinking...", spinner="dots",
                            spinner_style=SPINNER_COLOR):
            resp = call_api(messages, model=model, tools=TOOL_SCHEMAS)
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
        # Persist this call's usage so the post-turn bar and :tokens work on the
        # tool path — the whole reason both went blank when tools took over.
        save_message(conn, session_id, "assistant", msg["content"],
                     model=model,
                     tok_in=usage.get("prompt_tokens") or None,
                     tok_out=usage.get("completion_tokens") or None,
                     kind="tool_call" if calls else "chat",
                     meta={"tool_calls": calls} if calls else None)

        if not calls:
            return msg

        if msg["content"].strip():
            console.print()
            console.print(msg["content"], style="dim")

        for call in calls:
            _render_call(call)
            result = gate_and_dispatch(call, approval, ctx)
            _render_result(result)

            fn = call.get("function", {})
            tool_msg = {"role": "tool",
                        "tool_call_id": call.get("id"),
                        "content": result}
            history.append(tool_msg)
            save_message(conn, session_id, "tool", result, model=model,
                         kind="tool_result",
                         meta={"tool": fn.get("name"),
                               "tool_call_id": call.get("id")})

    # A real assistant message, shown to the user, not a silent truncation.
    final = {"role": "assistant", "content": LIMIT_MESSAGE}
    history.append(final)
    save_message(conn, session_id, "assistant", LIMIT_MESSAGE, model=model)
    return final


def render_answer(text):
    console.print()
    console.print(ai_answer_panel(Markdown(text or "")))
