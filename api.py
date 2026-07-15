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
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.spinner import Spinner

from config import API_BASE, API_KEY, MODEL

try:
    from config import STREAM_USAGE
except ImportError:
    STREAM_USAGE = True

from ui import console


def call_api(messages, model=None):
    """Non-streaming API call. Used for title generation."""
    model = model or MODEL
    with httpx.Client(timeout=120) as client:
        r = client.post(
            f"{API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "model": model,
                "messages": messages,
                "stream": False,
            },
        )
        r.raise_for_status()
        return r.json()


def stream_response(messages, model=None):
    """Stream API response, rendered live as Markdown.
    Returns (full_text, usage_dict). usage may be None
    if the provider doesn't support include_usage."""
    model = model or MODEL
    full_text = ""
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
                response.raise_for_status()
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
                            content = delta.get("content")
                            if content:
                                full_text += content
                                live.update(
                                    Panel(
                                        Markdown(full_text),
                                        title="ai",
                                        title_align="left",
                                        border_style="cyan",
                                    )
                                )
                    except json.JSONDecodeError:
                        continue

    return full_text, usage


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
