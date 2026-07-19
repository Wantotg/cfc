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
_TIMEOUT    = 60.0
_RETRIES    = 4

def _post(batch):
    import httpx  # lazy: only needed for the live call
    url = EMBED_BASE.rstrip("/") + "/embeddings"
    headers = {"Authorization": f"Bearer {EMBED_KEY}", "Content-Type": "application/json"}
    payload = {"model": EMBED_MODEL, "input": batch}
    last = None
    for attempt in range(_RETRIES):
        try:
            r = httpx.post(url, headers=headers, json=payload, timeout=_TIMEOUT)
            if r.status_code in (429, 500, 502, 503):
                last = f"{r.status_code}: {r.text[:200]}"
                time.sleep(2 ** attempt)   # exponential backoff
                continue
            r.raise_for_status()
            data = r.json()["data"]
            # preserve input order (API returns index field, but usually in-order)
            data = sorted(data, key=lambda d: d.get("index", 0))
            return [d["embedding"] for d in data]
        except httpx.HTTPError as e:
            last = str(e)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"embeddings request failed after {_RETRIES} tries: {last}")

def embed_texts(texts):
    """Embed a list of strings, batching under the hood. Returns list of vectors."""
    out = []
    for i in range(0, len(texts), _BATCH):
        out.extend(_post(texts[i:i+_BATCH]))
    return out

if __name__ == "__main__":
    # smoke test (needs live API + config): embed two tiny strings
    vecs = embed_texts(["hello world", "bonjour le monde"])
    print(f"got {len(vecs)} vectors, dim {len(vecs[0])}")
    assert len(vecs[0]) == EMBED_DIM, f"expected {EMBED_DIM}, got {len(vecs[0])}"
    print("dimension matches EMBED_DIM ✓")
