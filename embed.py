#!/usr/bin/env python3
"""
embed.py — embedding layer for cfc's RAG. Talks to nano-gpt's OpenAI-compatible
/embeddings endpoint using the SAME api key/base as chat (from config.py).

Exposes:
    embed_texts(texts: list[str]) -> list[list[float]]   # batch embed
    EMBED_MODEL, EMBED_DIM

Standalone so it slots into the future api.py cleanly.
"""
import time

# Pulled from config.py. The embedding endpoint is independent of chat
# (EMBED_BASE/EMBED_MODEL/EMBED_KEY); if those aren't set it falls back to the
# chat key/base and hosted bge-m3, so an older config keeps working.
try:
    import config
    API_KEY  = getattr(config, "API_KEY", None)
    API_BASE = getattr(config, "API_BASE", "https://api.nano-gpt.com/v1")
    EMBED_BASE  = getattr(config, "EMBED_BASE", API_BASE)
    EMBED_MODEL = getattr(config, "EMBED_MODEL", "BAAI/bge-m3")
    EMBED_KEY   = getattr(config, "EMBED_KEY", API_KEY)
except Exception:
    API_KEY, API_BASE = None, "https://api.nano-gpt.com/v1"
    EMBED_BASE, EMBED_MODEL, EMBED_KEY = API_BASE, "BAAI/bge-m3", None

EMBED_DIM   = 1024
_BATCH      = 100          # well under the 2048 cap; keeps requests small

# Two timeouts, not one. httpx's single `timeout=` sets connect, read, write and
# pool to the same value, and those measure different things: "is anything
# there" against "is it finished yet". One number has to serve the slower of the
# two, which is why a dead server used to cost four minutes — every attempt sat
# out the full 60s read budget just to discover nothing was listening.
_CONNECT_TIMEOUT = 5.0     # a server on localhost answers in milliseconds
_READ_TIMEOUT    = 60.0    # a 100-chunk batch, or a cold model load, legitimately takes this

# Two retry budgets, for the same reason. A 429 or a 503 is a transient and
# waiting is the correct response to it. A refused connection is a *state*:
# asking again gets the same answer, so ask twice (in case of a restart mid-call)
# and then stop rather than four times.
_RETRIES      = 4
_DOWN_RETRIES = 2


class EmbedError(RuntimeError):
    """An embeddings request failed after its retries.

    Subclasses `RuntimeError` because that is what this module raised before
    the type existed, and every caller's `except Exception` keeps working
    unchanged — the type adds a distinction, it doesn't take one away.
    """


class EmbedUnavailable(EmbedError):
    """Nothing was listening. A *state*, not a transient.

    This is the whole reason the type exists. "The embedder is down" and
    "memory has nothing on that" produce the identical silence at the top of
    the stack, and the second is a confident, wrong, unfalsifiable answer.
    They are only cleanly separable **here**, at the point where one of them
    is an exception and the other is an empty list — so the separation is made
    here and carried up as a type.

    Callers must branch on this class, never on the message text. The wording
    is for humans; matching on it would be the recurring hazard `HANDOVER.md`
    tabulates, and it would fail the day someone improves a sentence.
    """


def _post(batch, on_retry=None):
    """One embeddings request, with retries.

    `on_retry(attempt, attempts, detail)` is called after a failed attempt when
    another is coming — the callback exists because embed.py has no console and
    must not grow one: routines and imports run headless, so who says something
    about a slow embedder is the caller's business, not this module's.
    """
    import httpx  # lazy: only needed for the live call
    url = EMBED_BASE.rstrip("/") + "/embeddings"
    headers = {"Authorization": f"Bearer {EMBED_KEY}", "Content-Type": "application/json"}
    payload = {"model": EMBED_MODEL, "input": batch}
    timeout = httpx.Timeout(_READ_TIMEOUT, connect=_CONNECT_TIMEOUT)
    last, attempt, attempts = None, 0, _RETRIES
    # Which *kind* of failure the last attempt was. Recorded as a flag at the
    # point the exception is caught, rather than reconstructed afterwards from
    # the message, because the message is prose and prose drifts.
    unreachable = False
    while attempt < attempts:
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            if r.status_code in (429, 500, 502, 503):
                last, unreachable = f"{r.status_code}: {r.text[:200]}", False
            else:
                r.raise_for_status()
                data = r.json()["data"]
                # preserve input order (API returns index field, but usually in-order)
                data = sorted(data, key=lambda d: d.get("index", 0))
                return [d["embedding"] for d in data]
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            last = (f"no connection to {EMBED_BASE} ({type(e).__name__}) "
                    f"— is the embedding server running?")
            unreachable = True
            attempts = min(attempts, _DOWN_RETRIES)
        except httpx.HTTPError as e:
            last, unreachable = str(e), False
        attempt += 1
        if attempt >= attempts:
            break                          # don't sleep on the way out
        if on_retry:
            on_retry(attempt, attempts, last)
        time.sleep(2 ** (attempt - 1))     # exponential backoff
    cls = EmbedUnavailable if unreachable else EmbedError
    raise cls(
        f"embeddings request failed after {attempt} "
        f"{'try' if attempt == 1 else 'tries'}: {last}")

def embed_texts(texts, on_retry=None):
    """Embed a list of strings, batching under the hood. Returns list of vectors."""
    out = []
    for i in range(0, len(texts), _BATCH):
        out.extend(_post(texts[i:i+_BATCH], on_retry=on_retry))
    return out

if __name__ == "__main__":
    # smoke test (needs live API + config): embed two tiny strings
    vecs = embed_texts(["hello world", "bonjour le monde"])
    print(f"got {len(vecs)} vectors, dim {len(vecs[0])}")
    assert len(vecs[0]) == EMBED_DIM, f"expected {EMBED_DIM}, got {len(vecs[0])}"
    print("dimension matches EMBED_DIM ✓")
