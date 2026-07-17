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
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from config import API_BASE, API_KEY, MODEL

try:
    from config import STREAM_USAGE
except ImportError:
    STREAM_USAGE = True

from ui import console


def call_api(messages, model=None, tools=None):
    """Non-streaming API call. Used for title generation and the agent loop.

    Streaming is off whenever tools are in play: tool-call deltas arrive
    fragmented across chunks and the `arguments` string has to be reassembled
    by index. Not worth it — these responses are fast.
    """
    model = model or MODEL
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
    with httpx.Client(timeout=120) as client:
        r = client.post(
            f"{API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json=payload,
        )
        if r.is_error:
            raise httpx.HTTPError(_error_detail(r))
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


def _thinking_panel(reasoning):
    """The dim 'thinking' panel: last few lines of the reasoning stream."""
    lines = reasoning.splitlines() or [reasoning]
    tail = lines[-_REASONING_TAIL_LINES:]
    body = Text("\n".join(tail), style="dim italic")
    return Panel(
        body,
        title="thinking",
        title_align="left",
        border_style="dim",
    )


def stream_response(messages, model=None):
    """Stream API response, rendered live as Markdown.

    Returns (full_text, usage_dict, reasoning). usage may be None if the
    provider doesn't support include_usage. reasoning is the concatenated
    `delta.reasoning` stream (thinking models); "" when the provider sends
    none. It's returned, not just shown, so the caller can tell a genuinely
    empty completion from a reasoning-only one (see main.py's retry path)."""
    model = model or MODEL
    full_text = ""
    reasoning = ""
    usage = None

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if STREAM_USAGE:
        payload["stream_options"] = {"include_usage": True}

    with httpx.Client(timeout=300) as client:
        with Live(
            Spinner(
                "dots",
                text="Thinking...",
                style="cyan",
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
                    raise httpx.HTTPError(_error_detail(response))
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
                                if reasoning:
                                    panels.append(
                                        _thinking_panel(reasoning)
                                    )
                                if full_text:
                                    panels.append(Panel(
                                        Markdown(full_text),
                                        title="ai",
                                        title_align="left",
                                        border_style="cyan",
                                    ))
                                live.update(Group(*panels))
                    except json.JSONDecodeError:
                        continue

    return full_text, usage, reasoning


def generate_title(first_user_message):
    """Ask the AI for a short title based on the first message."""
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
        resp = call_api(title_request)
        title = resp["choices"][0]["message"]["content"].strip()
        title = title.strip("\"'").replace("\n", " ").strip()
        title = title.rstrip(".?!")
        if len(title) > 60:
            title = title[:57] + "..."
        return title if title else "(untitled)"
    except Exception:
        return "(untitled)"
