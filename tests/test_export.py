#!/usr/bin/env python3
"""
test_export.py — a real exported document, read back (1.3/1.3.1). No API calls.

    python3 tests/test_export.py

`/export`'s general behaviour used to be a known gap (HANDOVER's Testing
section) — covered now, not just the First Message regression this file
started as. Pinned here: the durable, human-facing contract — target
session, a title-safe filename that replaces on re-export, frontmatter
totals, transcript order, and compact attachment/tool records — plus the
export-destination resolution the 1.3.1 rename owes (`W-0.9.1-01`):
`CHAT_EXPORT_DIR` wins when set, and a config that still only defines the
legacy `VAULT_PATH` keeps exporting untouched.

The golden harness's own auto-export path (`:q` with AUTO_EXPORT on) is left
alone — this file drives `export_session`/`safe_export` directly rather than
building a second REPL driver to reach the same writer.
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import db as dbmod
import export as exportmod

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def main():
    tmp = Path(tempfile.mkdtemp())
    assert "tmp" in str(tmp), "refusing to touch a real db"
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()

    vault = Path(tempfile.mkdtemp())
    saved_chat_export_dir = exportmod.CHAT_EXPORT_DIR
    saved_vault_path = exportmod.VAULT_PATH
    exportmod.CHAT_EXPORT_DIR = str(vault)
    exportmod.VAULT_PATH = ""

    try:
        print("--- a session with no First Message exports as before ---")
        plain_sid = dbmod.new_session(conn, title="plain")
        dbmod.save_message(conn, plain_sid, "user", "hi", model="m")
        dbmod.save_message(conn, plain_sid, "assistant", "hello", model="m")
        exportmod.export_session(conn, plain_sid, quiet=True)
        plain_file = sorted(vault.glob(f"*Session-{plain_sid}_*.md"))[0]
        plain_text = plain_file.read_text(encoding="utf-8")
        ok("total_messages counts only the two real rows",
           "total_messages: 2" in plain_text, plain_text)

        print("\n--- a First Message is at the head, before the ordinary turns ---")
        fm_sid = dbmod.new_session(conn, title="with-opening")
        dbmod.set_first_message(conn, fm_sid, "muse.md", "Where should we begin?",
                                at="2026-07-31T09:00:00+00:00")
        dbmod.save_message(conn, fm_sid, "user", "let's start", model="m")
        dbmod.save_message(conn, fm_sid, "assistant", "sure thing", model="m")
        exportmod.export_session(conn, fm_sid, quiet=True)
        fm_file = sorted(vault.glob(f"*Session-{fm_sid}_*.md"))[0]
        fm_text = fm_file.read_text(encoding="utf-8")

        ok("the opening text is in the export",
           "Where should we begin?" in fm_text, fm_text)
        ok("total_messages counts it: 2 real rows + 1 opening = 3",
           "total_messages: 3" in fm_text, fm_text)
        ok("the opening comes before the first ordinary turn",
           fm_text.index("Where should we begin?")
           < fm_text.index("let's start"), fm_text)

        print("\n--- a representative document, read back ---")
        # System prompt, persona, tags, an attachment and a tool call/result
        # pair — the shapes commands.py and agent.py actually write, not a
        # simplified stand-in.
        rich_sid = dbmod.new_session(conn, title="rich session")
        dbmod.set_system_prompt(conn, rich_sid, "Be concise.", "terse.md")
        dbmod.set_persona(conn, rich_sid, "You are Muse.", "muse.md")
        dbmod.add_tag(conn, rich_sid, "memory")
        dbmod.save_message(conn, rich_sid, "user",
                           "what's in notes.txt?", model="m",
                           tok_in=5, tok_out=0)
        dbmod.save_message(
            conn, rich_sid, "user", "[attached: notes.txt]", model="m",
            kind="attachment",
            meta={"path": "/home/cas/notes.txt", "name": "notes.txt",
                  "sha256": "a1b2c3d4e5f6", "chars": 42, "est_tokens": 10})
        dbmod.save_message(
            conn, rich_sid, "assistant", "", model="m",
            tok_in=20, tok_out=8, kind="tool_call",
            meta={"tool_calls": [{
                "id": "call_1", "function": {
                    "name": "read_file",
                    "arguments": json.dumps({"path": "notes.txt"})}}]})
        dbmod.save_message(
            conn, rich_sid, "tool", "line one\nline two\nline three",
            model="m", kind="tool_result",
            meta={"tool": "read_file", "tool_call_id": "call_1"})
        dbmod.save_message(conn, rich_sid, "assistant",
                           "Three lines about the weekend trip.", model="m",
                           tok_in=0, tok_out=12)
        exportmod.export_session(conn, rich_sid, quiet=True)
        rich_file = sorted(vault.glob(f"*Session-{rich_sid}_*.md"))[0]
        rich_text = rich_file.read_text(encoding="utf-8")

        ok("names the target session in the frontmatter",
           f"session_id: {rich_sid}" in rich_text, rich_text)
        # 5 messages rows total: question, attachment, tool_call, tool_result,
        # answer — every kind counts, not just plain chat turns.
        ok("total_messages counts every row, tool/attachment kinds included",
           "total_messages: 5" in rich_text, rich_text)
        ok("token totals sum across all rows",
           "total_tokens_in: 25" in rich_text
           and "total_tokens_out: 20" in rich_text, rich_text)
        ok("the system prompt is named", '"terse.md"' in rich_text, rich_text)
        ok("the persona is named", '"muse.md"' in rich_text, rich_text)
        ok("the tag is listed", "- memory" in rich_text, rich_text)

        ok("the attachment renders as a compact reference, not the whole file",
           "**Attached:** `notes.txt`" in rich_text
           and "sha256:a1b2c3d" in rich_text, rich_text)
        ok("the tool call names the tool and its argument",
           "**Tool call:** `read_file` — `notes.txt`" in rich_text, rich_text)
        ok("the tool result is compact, not the raw 3-line file",
           "**Tool:** `read_file` — approved, 3 lines returned" in rich_text,
           rich_text)

        # Transcript order: DB insertion order (by id), not grouped by kind.
        order = [rich_text.index(s) for s in (
            "what's in notes.txt?", "**Attached:** `notes.txt`",
            "**Tool call:** `read_file`", "approved, 3 lines returned",
            "Three lines about the weekend trip.")]
        ok("the transcript preserves insertion order",
           order == sorted(order), order)

        print("\n--- a title-safe filename, replaced rather than duplicated "
              "on re-export ---")
        bad_sid = dbmod.new_session(
            conn, title='a/b:c*d?e"f<g>h|i')
        dbmod.save_message(conn, bad_sid, "user", "first turn", model="m")
        exportmod.export_session(conn, bad_sid, quiet=True)
        matches = sorted(vault.glob(f"*Session-{bad_sid}_*.md"))
        ok("exactly one file for a title full of filesystem-hostile characters",
           len(matches) == 1, matches)
        ok("none of the bad characters survive into the filename",
           not any(c in matches[0].name for c in '\\/:*?"<>|'), matches[0].name)

        dbmod.save_message(conn, bad_sid, "assistant", "second turn", model="m")
        exportmod.export_session(conn, bad_sid, quiet=True)
        matches2 = sorted(vault.glob(f"*Session-{bad_sid}_*.md"))
        ok("re-exporting the same session replaces the file, not duplicates it",
           len(matches2) == 1 and matches2[0].name == matches[0].name, matches2)
        ok("...and the replacement carries the new turn",
           "second turn" in matches2[0].read_text(encoding="utf-8"))

        print("\n--- an absent session exports nothing ---")
        before = set(vault.glob("*.md"))
        result = exportmod.export_session(conn, 999999, quiet=True)
        after = set(vault.glob("*.md"))
        ok("export_session reports failure for a session that doesn't exist",
           result is False, result)
        ok("...and creates no file at all", after == before,
           after - before)
    finally:
        exportmod.CHAT_EXPORT_DIR = saved_chat_export_dir
        exportmod.VAULT_PATH = saved_vault_path

    print("\n--- CHAT_EXPORT_DIR wins over the legacy VAULT_PATH ---")
    new_dir = Path(tempfile.mkdtemp())
    legacy_dir = Path(tempfile.mkdtemp())
    saved_chat_export_dir = exportmod.CHAT_EXPORT_DIR
    saved_vault_path = exportmod.VAULT_PATH
    exportmod.CHAT_EXPORT_DIR = str(new_dir)
    exportmod.VAULT_PATH = str(legacy_dir)
    try:
        both_sid = dbmod.new_session(conn, title="both keys set")
        dbmod.save_message(conn, both_sid, "user", "hi", model="m")
        exportmod.export_session(conn, both_sid, quiet=True)
        ok("the new key's directory receives the export",
           bool(list(new_dir.glob(f"*Session-{both_sid}_*.md"))))
        ok("...and the legacy directory does not",
           not list(legacy_dir.glob(f"*Session-{both_sid}_*.md")))
    finally:
        exportmod.CHAT_EXPORT_DIR = saved_chat_export_dir
        exportmod.VAULT_PATH = saved_vault_path

    print("\n--- a legacy-only config.py (VAULT_PATH, no CHAT_EXPORT_DIR) "
          "still writes to its configured directory ---")
    legacy_only_dir = Path(tempfile.mkdtemp())
    saved_chat_export_dir = exportmod.CHAT_EXPORT_DIR
    saved_vault_path = exportmod.VAULT_PATH
    exportmod.CHAT_EXPORT_DIR = ""
    exportmod.VAULT_PATH = str(legacy_only_dir)
    try:
        legacy_sid = dbmod.new_session(conn, title="legacy config only")
        dbmod.save_message(conn, legacy_sid, "user", "hi", model="m")
        exportmod.export_session(conn, legacy_sid, quiet=True)
        ok("a config.py with only VAULT_PATH still exports, unmodified",
           bool(list(legacy_only_dir.glob(f"*Session-{legacy_sid}_*.md"))))
    finally:
        exportmod.CHAT_EXPORT_DIR = saved_chat_export_dir
        exportmod.VAULT_PATH = saved_vault_path

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
