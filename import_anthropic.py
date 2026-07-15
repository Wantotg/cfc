#!/usr/bin/env python3
"""
import_anthropic.py — importer for an Anthropic data export into cfc's SQLite db.

Usage:
    python3 import_anthropic.py conversations.json ~/.cfc/chat.db [--wipe]

--wipe : delete existing provider='anthropic' rows first (clean re-import).
         Leaves other providers (GLM etc.) untouched.

Idempotent by Anthropic UUID. Thinking blocks are preserved and marked so a
later chunker can separate them (kind='thinking').
"""
import json, sqlite3, sys, os
from collections import Counter

PROVIDER = "anthropic"

# Sentinel markers so the chunker can split a message body back into kinds.
THINK_OPEN, THINK_CLOSE = "\u2402THINK\u2402", "\u2402/THINK\u2402"  # unlikely to occur naturally

def migrate(db):
    cols_s = {r[1] for r in db.execute("PRAGMA table_info(sessions)")}
    cols_m = {r[1] for r in db.execute("PRAGMA table_info(messages)")}
    if "source_uuid" not in cols_s:
        db.execute("ALTER TABLE sessions ADD COLUMN source_uuid TEXT")
    if "source_uuid" not in cols_m:
        db.execute("ALTER TABLE messages ADD COLUMN source_uuid TEXT")
    db.commit()

def extract_text(content, text_fallback, stats):
    """Join content[] blocks. Thinking wrapped in sentinels; tools marked."""
    if not content:
        return text_fallback.strip()
    parts = []
    for block in content:
        btype = block.get("type")
        if btype == "text":
            parts.append(block.get("text", ""))
        elif btype == "thinking":
            t = block.get("thinking") or block.get("text") or ""
            if t.strip():
                parts.append(f"{THINK_OPEN}{t}{THINK_CLOSE}")
                stats["thinking_blocks_kept"] += 1
        elif btype == "tool_use":
            parts.append(f"\n[tool_use: {block.get('name','?')}]\n")
            stats["tool_use_marked"] += 1
        elif btype == "tool_result":
            stats["tool_result_skipped"] += 1
        else:
            stats[f"other_block_{btype}"] += 1
    return "".join(parts).strip()

def title_for(conv):
    name = (conv.get("name") or "").strip()
    return name if name else f"(untitled) {conv.get('created_at','')[:10]}"

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    wipe = "--wipe" in sys.argv
    if len(args) != 2:
        print("usage: python3 import_anthropic.py conversations.json /path/to/chat.db [--wipe]")
        sys.exit(1)
    export_path, db_path = args[0], os.path.expanduser(args[1])
    data = json.load(open(export_path))
    db = sqlite3.connect(db_path)
    migrate(db)

    if wipe:
        sids = [r[0] for r in db.execute("SELECT id FROM sessions WHERE provider=?", (PROVIDER,))]
        if sids:
            db.executemany("DELETE FROM messages WHERE session_id=?", [(s,) for s in sids])
            db.execute("DELETE FROM sessions WHERE provider=?", (PROVIDER,))
            db.commit()
            print(f"wiped {len(sids)} existing anthropic sessions")

    existing_convs = {r[0] for r in db.execute(
        "SELECT source_uuid FROM sessions WHERE source_uuid IS NOT NULL")}
    existing_msgs = {r[0] for r in db.execute(
        "SELECT source_uuid FROM messages WHERE source_uuid IS NOT NULL")}

    stats = Counter()
    for conv in data:
        cuuid = conv["uuid"]
        msgs = sorted(conv.get("chat_messages", []), key=lambda m: m.get("created_at",""))
        prepared = []
        for m in msgs:
            body = extract_text(m.get("content", []), m.get("text",""), stats)
            if not body:
                stats["empty_messages_skipped"] += 1
                continue
            prepared.append((m, body))
        if not prepared:
            stats["empty_conversations_skipped"] += 1
            continue
        if cuuid in existing_convs:
            sid = db.execute("SELECT id FROM sessions WHERE source_uuid=?", (cuuid,)).fetchone()[0]
            stats["conversations_already_present"] += 1
        else:
            cur = db.execute(
                "INSERT INTO sessions (title, provider, created_at, updated_at, source_uuid) VALUES (?,?,?,?,?)",
                (title_for(conv), PROVIDER, conv.get("created_at"), conv.get("updated_at"), cuuid))
            sid = cur.lastrowid
            stats["conversations_imported"] += 1
        for m, body in prepared:
            muuid = m["uuid"]
            if muuid in existing_msgs:
                continue
            role = "user" if m.get("sender")=="human" else "assistant"
            db.execute(
                "INSERT INTO messages (session_id, role, content, created_at, source_uuid) VALUES (?,?,?,?,?)",
                (sid, role, body, m.get("created_at"), muuid))
            existing_msgs.add(muuid)
            stats["messages_imported"] += 1
    db.commit()

    print("\n=== import summary ===")
    for k,v in sorted(stats.items()):
        print(f"  {k}: {v}")
    print(f"\n  db totals: {db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]} sessions, "
          f"{db.execute('SELECT COUNT(*) FROM messages').fetchone()[0]} messages")
    db.close()

if __name__ == "__main__":
    main()
