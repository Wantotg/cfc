#!/usr/bin/env python3
"""
recall.py — memory that talks. Retrieves relevant chunks (via search.py) and
feeds them to a chat model that answers ONLY from those excerpts, with citations.

    python3 recall.py /path/to/chat.db "what did we decide about the vector db?"

Grounding discipline: the model is instructed to answer only from retrieved
excerpts and to say plainly when they don't cover the question — no invention.
"""
import sys, os, json
from search import search

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

def build_context(hits):
    blocks = []
    for h in hits:
        tag = " [reasoning]" if h["kind"] == "thinking" else ""
        date = (h["created_at"] or "")[:10]
        wid = h.get("source_uuid") or "?"
        datepart = f", {date}" if date else ""
        blocks.append(
            f"From: {h['session_title']} (id {wid}{datepart}){tag}\n"
            f"{h['text']}"
        )
    return "\n\n---\n\n".join(blocks)

def recall(db_path, question, k=8, kind=None, provider="wiki"):
    # provider='wiki' keeps recall grounded in the wiki even once the chat log
    # accumulates its own (source='chat') chunks. Pass provider=None for all.
    import httpx
    hits = search(db_path, question, k=k, kind=kind, provider=provider)
    if not hits:
        return "No relevant excerpts found in memory.", []
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
    print("\n" + "="*60)
    print(answer)
    print("="*60)
    print(f"\n(drew on {len(hits)} excerpts from "
          f"{len(set(h['session_id'] for h in hits))} wiki pages)")
