# api.py — every outbound call to the OpenAI-compatible endpoint.
#
# Two paths deliberately:
#   stream_response() for the chat turn, so text appears as it arrives
#   call_api()        non-streaming, for title generation
#
# STREAM_USAGE exists because token counts only come back if the provider
# supports stream_options.include_usage. Providers that don't will either
# ignore it or reject the request, hence the config switch.
import json

import httpx
from rich.console import Group
from rich.live import Live
from rich.markdown import Markdown
from rich.spinner import Spinner
from rich.text import Text

from config import API_BASE, API_KEY, MODEL

try:
    from config import STREAM_USAGE
except ImportError:
    STREAM_USAGE = True

from ui import SPINNER_COLOR, ai_answer_panel, ai_reasoning_panel, console

# --- request capture (W-1.6.4-04) -------------------------------------------
#
# The interactive turn's own record of what cfc actually sent, for `/status
# request`. Set only for the span of one turn's call(s) via `capture_requests`
# below — never a parameter threaded through `call_api`/`stream_response`
# themselves, which is what keeps every existing caller and every existing
# test stub of either function unchanged: title generation, /recall and
# routine execution all go through `call_api` too, from outside any
# `capture_requests` block, so they never touch this and never need to say so.
#
# A plain module global, not a `contextvars.ContextVar`: cfc is single-
# threaded and synchronous end to end — one turn, one blocking call, no
# asyncio and no worker thread — so there is no concurrent call this could
# leak across. `main.py`'s process-wide `_process_model` is the same shape
# for the same reason.
_capture_sink = None


class capture_requests:
    """Context manager: append every payload `call_api`/`stream_response`
    send to `sink` for calls made inside the block.

    Restores whatever sink was active before (usually `None`) rather than
    assuming that, so this can never silently drop an outer capture if
    something one day nests it. `sink` itself is the caller's — `run_session`
    holds it, resets it to a fresh list at the start of each attempted turn,
    and reads it back for `/status request`; this context manager only says
    *when* it is live, never what it holds or how long it persists.
    """

    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        global _capture_sink
        self._prev = _capture_sink
        _capture_sink = self.sink
        return self

    def __exit__(self, *exc):
        global _capture_sink
        _capture_sink = self._prev
        return False


# Read timeout for the non-streaming path, in seconds.
#
# This is the one number that has to be generous, and a bare `timeout=N` is the
# wrong shape for it: httpx applies a scalar to connect, read, write AND pool
# alike, so tuning for a slow *model* also means waiting that long for a dead
# *socket*. They are opposite requirements — a connect that hasn't landed in ten
# seconds never will, while a read is legitimately silent for as long as the
# model thinks.
#
# The non-streaming path is where that bites. `stream_response` sees a chunk
# every few hundred ms and resets its read clock on each one; `call_api` sees
# nothing at all until the model has finished reasoning and emitted the whole
# completion. A thinking model working through several wiki pages inside the
# agent loop is silent for minutes, and the old flat 120 killed the request
# mid-thought — surfacing as a bare `[error] The read operation timed out`,
# which reads like a provider fault and isn't one.
#
# 600 is "long enough that tripping it means something is actually wrong",
# not an estimate of how long a turn takes.
try:
    from config import API_READ_TIMEOUT
except ImportError:
    API_READ_TIMEOUT = 600.0

# Title generation runs on the same function but is a throwaway 3-5 word call
# on a fast model. It must not inherit the agent path's patience: a hung title
# request would block the REPL for ten minutes with nothing on screen, and
# generate_title swallows the exception anyway, so the failure would be a long
# silence followed by "(untitled)".
_TITLE_READ_TIMEOUT = 60.0

_CONNECT_TIMEOUT = 10.0
_WRITE_TIMEOUT = 60.0


def _timeout(read):
    """Per-phase timeouts: short on connect/pool, long on read."""
    return httpx.Timeout(
        connect=_CONNECT_TIMEOUT,
        read=read,
        write=_WRITE_TIMEOUT,
        pool=_CONNECT_TIMEOUT,
    )


def wire_messages(messages):
    """The conversation in the shape the provider is sent, not the shape we keep.

    **One transform today**, and it is the surviving suspect for the provider
    400 on tool turns (`development/BUGS.md`). `agent.py` normalises a missing `content` to
    `""` on the assistant message that carries `tool_calls`, because our own
    `history`, `save_message` and the renderer all expect the key to exist.
    Some OpenAI-compatible providers want that field **absent** on a tool-call
    message and reject the replay on the next request — which fits the reported
    symptom exactly: tool turns only, size-independent, and every subsequent
    message in the session failing rather than just the one.

    **It lives here rather than at the call sites, and that is the design.**
    Two paths replay history to a provider — `agent_turn`'s loop and the
    streaming path — and the streaming one is easy to forget precisely because
    it does not use tools: a session that made tool calls and then switched to
    a non-tools model replays those same messages through `stream_response`.
    A transform each caller has to remember is one a caller will not. At the
    wire boundary there is nothing to remember.

    **It never mutates the input.** `history` is what gets persisted and
    replayed, and standing decision 2 lives in it — every tool call keeping
    exactly one result. Editing those dicts in place to fix a wire format would
    reach back into the record of the conversation. New dicts, always.

    Note this drops the key rather than sending `null`. Absent is what the
    OpenAI schema means by "no content"; `None` is a third state that some
    providers accept and others reject, and there is no reason to pick the
    riskier of two spellings of the same thing.
    """
    out = []
    for m in messages:
        if (m.get("role") == "assistant"
                and m.get("tool_calls")
                and not (m.get("content") or "").strip()):
            m = {k: v for k, v in m.items() if k != "content"}
        out.append(m)
    return out


def call_api(messages, model=None, tools=None, read_timeout=None, params=None):
    """Non-streaming API call. Used for title generation and the agent loop.

    Streaming is off whenever tools are in play: tool-call deltas arrive
    fragmented across chunks and the `arguments` string has to be reassembled
    by index. Not worth it — these responses are fast.

    `params` is the validated preset dictionary (v1.5, `models.preset_params`)
    — at most `{"temperature": ..., "top_p": ...}` — merged into the payload
    only when given. Every existing caller (title generation, recall,
    routines) omits it, so their payload is unchanged; only `agent_turn`'s
    interactive tool loop passes one through, and only when a preset is
    active.
    """
    model = model or MODEL
    payload = {
        "model": model,
        "messages": wire_messages(messages),
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    if params:
        payload.update(params)
    if read_timeout is None:
        read_timeout = API_READ_TIMEOUT
    if _capture_sink is not None:
        _capture_sink.append(dict(payload))
    with httpx.Client(timeout=_timeout(read_timeout)) as client:
        r = client.post(
            f"{API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json=payload,
        )
        if r.is_error:
            raise _provider_error(r)
        return r.json()


def _error_detail(r):
    """The provider's own words, not httpx's.

    raise_for_status() reports the status code and links MDN — it discards the
    response body, which is the only part that says *why*. A 400 on a tool call
    is unreadable without it.
    """
    body = (r.text or "").strip()
    try:
        d = r.json()
        if isinstance(d, dict):
            err = d.get("error", d)
            if isinstance(err, dict):
                body = err.get("message") or json.dumps(err)
            elif isinstance(err, str):
                body = err
    except (json.JSONDecodeError, ValueError):
        pass
    return f"HTTP {r.status_code} from {r.request.url}: {body[:800] or '(empty body)'}"


# How much of the reasoning stream to keep on screen. Thinking models emit
# thousands of reasoning tokens; rendering all of it live would blow past the
# terminal height and make Rich crop unpredictably. We show the tail so the
# panel stays put and you can still see it's alive and what it's chewing on.
_REASONING_TAIL_LINES = 12

# How many times to silently re-send after an empty completion when there is no
# human to ask. Thinking models return these now and then and the same context
# usually answers on a re-roll, so one hiccup shouldn't cost an unattended run.
# Bounded because the failure mode of "retry until it works" against a sick
# provider is a very large bill, discovered late.
EMPTY_COMPLETION_RETRIES = 2

# A status code is a provider contract; an error message is not.  Keep this
# deliberately small: 400 and 401 describe a request/auth problem that another
# identical call cannot repair, while these four are the temporary admission
# and availability failures an unattended routine can reasonably outwait. 408
# is deliberately not here: it's the *client* giving up on a slow request, and
# resending an identical one that was already too slow buys nothing.
TRANSIENT_STATUS_CODES = frozenset((429, 502, 503, 504))


def is_transient_status(error):
    """Whether a provider response explicitly says this error is transient.

    Transport failures do not carry a response status and are intentionally not
    guessed at here.  The status is attached at the HTTP boundary below and
    carried through agent.py; matching rendered text would make a provider
    rewording silently change retry policy.
    """
    return getattr(error, "status_code", None) in TRANSIENT_STATUS_CODES


def _provider_error(response):
    """An HTTPError that keeps the provider status as data, not prose."""
    error = httpx.HTTPError(_error_detail(response))
    error.status_code = response.status_code
    return error


def _thinking_panel(reasoning):
    """The dim 'thinking' panel: last few lines of the reasoning stream."""
    lines = reasoning.splitlines() or [reasoning]
    tail = lines[-_REASONING_TAIL_LINES:]
    body = Text("\n".join(tail), style="dim italic")
    return ai_reasoning_panel(body)


def stream_response(messages, model=None, params=None):
    """Stream API response, rendered live as Markdown.

    Returns (full_text, usage_dict, reasoning). usage may be None if the
    provider doesn't support include_usage. reasoning is the concatenated
    `delta.reasoning` stream (thinking models); "" when the provider sends
    none. It's returned, not just shown, so the caller can tell a genuinely
    empty completion from a reasoning-only one (see main.py's retry path).

    `params` is the same optional preset dictionary `call_api` takes — see
    its docstring. Merged into the payload only when given, so a turn with no
    active preset sends exactly the request it always has.
    """
    model = model or MODEL
    full_text = ""
    reasoning = ""
    usage = None

    payload = {
        "model": model,
        "messages": wire_messages(messages),
        "stream": True,
    }
    if STREAM_USAGE:
        payload["stream_options"] = {"include_usage": True}
    if params:
        payload.update(params)

    if _capture_sink is not None:
        _capture_sink.append(dict(payload))

    # Read stays at 300 here and is a different quantity from the one above:
    # httpx resets the read clock on every chunk, so this is the gap *between*
    # deltas, not the length of the turn. 300s of dead air on an open stream is
    # a hung connection, not a slow model. Connect/write get the same short
    # bounds as everywhere else.
    with httpx.Client(timeout=_timeout(300.0)) as client:
        with Live(
            Spinner(
                "dots",
                text="Thinking...",
                style=SPINNER_COLOR,
            ),
            console=console,
            refresh_per_second=8,
        ) as live:
            with client.stream(
                "POST",
                f"{API_BASE}/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}"
                },
                json=payload,
            ) as response:
                if response.is_error:
                    response.read()
                    raise _provider_error(response)
                for line in response.iter_lines():
                    if not line or not line.startswith(
                        "data: "
                    ):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        if "error" in chunk:
                            msg = chunk["error"].get(
                                "message",
                                "Unknown error",
                            )
                            raise httpx.HTTPError(
                                f"API error: {msg}"
                            )
                        if "usage" in chunk and \
                                chunk["usage"]:
                            usage = chunk["usage"]
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get(
                                "delta", {}
                            )
                            # Thinking models stream reasoning separately, and
                            # ahead of any answer. Render it dimmed so a long
                            # silent think looks alive instead of hung — and so
                            # a reasoning-only turn (provider hiccup) is visibly
                            # distinct from a truly empty one.
                            think = delta.get("reasoning")
                            content = delta.get("content")
                            if think:
                                reasoning += think
                            if content:
                                full_text += content
                            if think or content:
                                panels = []
                                # Whitespace-only reasoning is unreadable, but
                                # the raw `reasoning` returned below is left
                                # alone — it's still the diagnostic that tells
                                # a reasoning-only completion apart from a
                                # truly empty one.
                                if reasoning.strip():
                                    panels.append(
                                        _thinking_panel(reasoning)
                                    )
                                if full_text:
                                    panels.append(
                                        ai_answer_panel(Markdown(full_text))
                                    )
                                live.update(Group(*panels))
                    except json.JSONDecodeError:
                        continue

    return full_text, usage, reasoning


class TitleGenerationError(Exception):
    """`generate_title` couldn't produce a usable title.

    Replaces the old `"(untitled)"` sentinel return, which made a real
    failure indistinguishable from the display text a caller chooses to show
    for one (`D-13`). The message preserves whatever detail is available: the
    transport/provider error verbatim on a failed call, or a description of
    the response shape on a blank or malformed one — the two failure classes
    the caller's proof (`tests/test_titles.py`) drives separately.
    """


def generate_title(first_user_message):
    """Ask the AI for a short title based on the first message.

    Raises `TitleGenerationError` on any failure — transport, empty, or a
    response that normalises to nothing usable — rather than returning a
    sentinel string. There is no retry and no fallback title here; a caller
    that wants `(untitled)` as display text supplies it itself.
    """
    title_request = [
        {
            "role": "system",
            "content": (
                "Generate a concise title of 3-5 words for a "
                "conversation that starts with the following "
                "message. Return ONLY the title text. No quotes, "
                "no punctuation at the end, no explanation."
            ),
        },
        {"role": "user", "content": first_user_message},
    ]
    try:
        resp = call_api(title_request, read_timeout=_TITLE_READ_TIMEOUT)
    except Exception as e:
        raise TitleGenerationError(str(e)) from e
    try:
        title = resp["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as e:
        raise TitleGenerationError(
            f"malformed title response: {e}: {resp!r}"[:800]) from e
    title = title.strip("\"'").replace("\n", " ").strip()
    title = title.rstrip(".?!")
    if not title:
        raise TitleGenerationError(
            f"empty title after normalising response: {resp!r}"[:800])
    if len(title) > 60:
        title = title[:57] + "..."
    return title
