#!/usr/bin/env python3
"""
recall.py — memory that talks. Retrieves relevant chunks (via search.py) and
feeds them to a chat model that answers ONLY from those excerpts, with citations.

    python3 recall.py /path/to/chat.db "what did we decide about the vector db?"

Grounding discipline: the model is instructed to answer only from retrieved
excerpts and to say plainly when they don't cover the question — no invention.
"""
import re
import sys, os, json
from search import search
# `ui` is imported for `format_date` alone and imports no cfc module itself, so
# this stays at the bottom of the dependency graph. The date label was reading
# `created_at[:10]` off a UTC string, which puts an evening session on the wrong
# day — see ui.format_date.
from ui import DISPLAY_NAME, format_date

try:
    import config
    API_KEY  = getattr(config, "API_KEY", None)
    API_BASE = getattr(config, "API_BASE", "https://nano-gpt.com/api/v1")
    # optional dedicated recall model; fall back to the main chat model
    RECALL_MODEL = getattr(config, "RECALL_MODEL", getattr(config, "MODEL", None))
except Exception:
    API_KEY, API_BASE, RECALL_MODEL = None, "https://nano-gpt.com/api/v1", None

SYSTEM = (
    "You answer questions from the user's own knowledge wiki, using ONLY the "
    "excerpts provided. Each excerpt is labelled with its source page title and "
    "stable id. Rules:\n"
    "- Answer only from the excerpts. Do not use outside knowledge.\n"
    "- Cite the source of each point by its page title and id (the 'From:' line "
    "above each excerpt). Never cite by number or position.\n"
    "- If the excerpts do not contain the answer, say so plainly. Do not guess "
    "or fill gaps with plausible invention.\n"
    "- Distinguish decisions the user made from ideas that were only discussed.\n"
    "- Be concise."
)

# --- excerpt spacing, for the synthesis request only -----------------------
#
# Excess blank lines between paragraphs cost tokens and carry nothing. This is
# the one input class eligible for that: the request built here is a
# dedicated, tool-free model call whose text is never parsed back, stored, or
# quoted (Concept.md's inventory). It never touches `hits` themselves — only
# the local string this module builds for the provider — and it is
# deliberately fail-open: anything that makes "is this blank line just
# spacing" uncertain leaves the whole excerpt exact rather than guess.

_FENCE_RE = re.compile(r'^\s{0,3}(`{3,}|~{3,})')
_HEADING_RE = re.compile(r'^#{1,6}(\s|$)')
_BLOCKQUOTE_RE = re.compile(r'^\s{0,3}>')
_LIST_RE = re.compile(r'^\s*([-*+]\s+|\d+\.\s+)')
_TABLE_RE = re.compile(r'^\s*\|')


def _is_plain_prose(text):
    """False if any line looks like fenced/indented code or Markdown block
    structure. A fence disqualifies the excerpt whether or not it is closed —
    pairing fences correctly is exactly the kind of classification this stays
    conservative about, so any fence marker is enough to leave it alone."""
    for line in text.split("\n"):
        if (_FENCE_RE.match(line) or line.startswith("    ")
                or line.startswith("\t") or _HEADING_RE.match(line)
                or _BLOCKQUOTE_RE.match(line) or _LIST_RE.match(line)
                or _TABLE_RE.match(line)):
            return False
    return True


def _compact_spacing(text):
    """Collapse a run of more than one blank line to exactly one. Non-empty
    lines, their order and their characters are untouched; only excess blank
    lines are dropped. Returns `text` unchanged when `_is_plain_prose` says
    no — this never runs on code-shaped or structured input."""
    if not _is_plain_prose(text):
        return text
    out = []
    blank_run = 0
    for line in text.split("\n"):
        if line == "":
            blank_run += 1
            if blank_run > 1:
                continue
        else:
            blank_run = 0
        out.append(line)
    return "\n".join(out)


def build_context(hits):
    blocks = []
    for h in hits:
        tag = " [reasoning]" if h["kind"] == "thinking" else ""
        date = format_date(h["created_at"])
        wid = h.get("source_uuid") or "?"
        datepart = f", {date}" if date else ""
        text = _compact_spacing(h["text"])
        blocks.append(
            f"From: {h['session_title']} (id {wid}{datepart}){tag}\n"
            f"{text}"
        )
    return "\n\n---\n\n".join(blocks)

def recall(db_path, question, k=8, kind=None, provider="wiki", on_retry=None):
    """(answer, hits). **`answer` is None when nothing was retrieved.**

    It used to be the sentence "No relevant excerpts found in memory.", which
    made a retrieval outcome indistinguishable from a synthesised one at the
    call site — the caller rendered it in the answer panel exactly as if a
    model had written it, and any code wanting to react to zero hits had to
    match on the wording. `None` is checkable and cannot drift.

    Saying *which* kind of nothing it was is the caller's job, via
    `search.why_empty`: this module has no console and the answer depends on
    which corpus the caller asked for. An unreachable embedder never reaches
    this branch at all — it raises `embed.EmbedUnavailable` out of `search`.
    """
    # provider='wiki' keeps recall grounded in the wiki even once the chat log
    # accumulates its own (source='chat') chunks. Pass provider=None for all.
    import httpx
    hits = search(db_path, question, k=k, kind=kind, provider=provider,
                  on_retry=on_retry)
    if not hits:
        return None, []
    context = build_context(hits)
    user_msg = (
        f"Question: {question}\n\n"
        f"Here are the most relevant excerpts from past conversations:\n\n{context}"
    )
    url = API_BASE.rstrip("/") + "/chat/completions"
    r = httpx.post(url,
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json={"model": RECALL_MODEL, "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_msg},
        ]}, timeout=120)
    r.raise_for_status()
    answer = r.json()["choices"][0]["message"]["content"]
    return answer, hits

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print('usage: python3 recall.py /path/to/chat.db "your question" [k]'); sys.exit(1)
    db_path, question = sys.argv[1], sys.argv[2]
    k = int(sys.argv[3]) if len(sys.argv) > 3 else 8
    answer, hits = recall(db_path, question, k=k)
    if answer is None:
        from search import why_empty, EMPTY_INDEX
        why = why_empty(db_path, provider="wiki")
        print(f"nothing indexed to search — run /update db in {DISPLAY_NAME}"
              if why == EMPTY_INDEX else
              "the wiki is indexed, but nothing came close enough to that "
              "question")
        sys.exit(0)
    print("\n" + "="*60)
    print(answer)
    print("="*60)
    print(f"\n(drew on {len(hits)} excerpts from "
          f"{len(set(h['session_id'] for h in hits))} wiki pages)")
