#!/usr/bin/env python3
"""test_mainchat_turns.py — Main chat wired into the hub and the turn
pipeline (1.4 steps 4-5). No network.

    python3 tests/test_mainchat_turns.py

What's worth pinning beyond the loader (tests/test_mainchat.py) and the
database identity (tests/test_main_identity.py):

* `m` creates on first use and reopens after, validating the creation
  bundle before ever touching the database, and a bundle problem leaves the
  hub exactly where it was — no blank row, no fallback to an ordinary chat;
* numeric resume of Main's id enters the identical fixed-profile path — the
  provider kind selects the behaviour, never the entry key;
* the hub renders Main's row distinctly, by identity, not by title text;
* `/add`, `/remove` and `/title` refuse to touch Main's identity, while
  ordinary facilities (tags, attachments, export, `/model`) stay available;
* a broken live system prompt/persona refuses the turn before the user's
  line is persisted, and a fixed edit is picked up on the very next turn;
* the frozen First Message survives edits and removal of the source file,
  and delete-then-recreate gets a genuinely new one;
* no private-chat path can ever create an on-disk Main row.
"""
import contextlib
import io
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import commands
import db as dbmod
import hub
import mainchat
import main
import models

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:400]}")


def flat(text):
    """Collapse whitespace, since rich wraps long lines to the console width
    and a substring check must not depend on exactly where that lands."""
    return " ".join((text or "").split())


def drive(conn, sid, keys, private=False, app_conn=None):
    out = io.StringIO()
    real_stdin = sys.stdin
    sys.stdin = io.StringIO(keys)
    try:
        with contextlib.redirect_stdout(out):
            main.console.file = out
            outcome = main.run_session(conn, sid, auto_export=False,
                                       private=private, app_conn=app_conn)
    finally:
        sys.stdin = real_stdin
        main.console.file = sys.stdout
    return out.getvalue(), outcome


def write_bundle(d, system_prompt="You are Main.", persona="A steady voice.",
                 first_message="Hello — where should we start?"):
    (d / mainchat.SYSTEM_PROMPT_FILE).write_text(system_prompt, encoding="utf-8")
    (d / mainchat.PERSONA_FILE).write_text(persona, encoding="utf-8")
    (d / mainchat.FIRST_MESSAGE_FILE).write_text(first_message, encoding="utf-8")


def main_():
    tmp = Path(tempfile.mkdtemp())
    assert "tmp" in str(tmp), "refusing to touch a real db"
    dbmod.DB_PATH = tmp / "chat.db"
    conn = dbmod.db()

    main.stream_response = lambda messages, model=None: (
        "an answer", {"prompt_tokens": 3, "completion_tokens": 2}, "")
    main.generate_title = lambda *a, **k: "(untitled)"
    main.auto_embed = lambda: None
    main.safe_export = lambda *a, **k: None
    main.set_process_model("stub-model")
    models.MODELS = [models._spec("stub-model", tools=True, limit=100_000)]
    # Off by default so every ordinary drive() below takes the streaming
    # path deterministically; only the turn-path parity section flips it.
    main.TOOLS_ENABLED = False

    saved_dir = mainchat.MAIN_CHAT_DIR

    try:
        print("--- 'm' refuses when the bundle is unconfigured ---")
        mainchat.MAIN_CHAT_DIR = ""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main.console.file = out
            result = main._open_main(conn)
        main.console.file = sys.stdout
        ok("no session id is returned", result is None)
        ok("no Main row was created", dbmod.main_session_id(conn) is None)
        ok("the problem names MAIN_CHAT_DIR",
           "MAIN_CHAT_DIR" in out.getvalue(), out.getvalue())

        print("\n--- 'm' refuses when one bundle file is missing ---")
        bdir = Path(tempfile.mkdtemp())
        write_bundle(bdir)
        (bdir / mainchat.FIRST_MESSAGE_FILE).unlink()
        mainchat.MAIN_CHAT_DIR = str(bdir)
        out2 = io.StringIO()
        with contextlib.redirect_stdout(out2):
            main.console.file = out2
            result2 = main._open_main(conn)
        main.console.file = sys.stdout
        ok("still no session id", result2 is None)
        ok("still no Main row", dbmod.main_session_id(conn) is None)
        ok("names first message.md",
           "first message.md" in out2.getvalue(), out2.getvalue())

        print("\n--- 'm' creates on first use ---")
        bundle_dir = Path(tempfile.mkdtemp())
        write_bundle(bundle_dir)
        mainchat.MAIN_CHAT_DIR = str(bundle_dir)
        sid = main._open_main(conn)
        ok("a session id came back", sid is not None, sid)
        ok("provider is main",
           dbmod.get_session_provider(conn, sid) == dbmod.PROVIDER_MAIN)
        ok("title is fixed", dbmod.get_session_title(conn, sid) == "Main")
        fm = dbmod.get_first_message(conn, sid)
        ok("the First Message froze from the source file",
           fm and fm["text"] == "Hello — where should we start?", fm)

        print("\n--- 'm' reopens after, never a second row ---")
        sid_again = main._open_main(conn)
        ok("the same id comes back", sid_again == sid, (sid_again, sid))
        ok("still exactly one Main row",
           dbmod.main_session_id(conn) == sid)

        print("\n--- numeric resume enters the identical fixed path ---")
        out3, _ = drive(conn, sid, "\n/status\n/q\n")
        ok("the header says Main chat", "Main chat" in out3, out3[:300])
        ok("system prompt/persona report live, not pool names",
           "System prompt" in out3 and "not set" not in out3.split(
               "Main chat")[1][:400], out3[:600])

        print("\n--- the hub renders Main's row distinctly, by identity ---")
        rows = hub.recent_chats(conn)
        ok("Main is in the picker's rows (chat-shaped)",
           any(r[0] == sid for r in rows), rows)
        table = hub._session_table("test")
        hub._add_rows(table, rows)
        title_col = table.columns[4]._cells
        main_idx = [i for i, r in enumerate(rows) if r[0] == sid][0]
        cell = title_col[main_idx]
        ok("Main's title cell is styled distinctly",
           getattr(cell, "style", None) == "bold cyan", cell)
        other_cells = [c for i, c in enumerate(title_col) if i != main_idx]
        ok("...and nothing else on screen is styled the same way",
           all(getattr(c, "style", None) != "bold cyan"
              for c in other_cells if not isinstance(c, str)), other_cells)

        print("\n--- /add, /remove and /title refuse Main's identity ---")
        out4, _ = drive(conn, sid, "\n/add trait anything\n/q\n")
        ok("/add refuses", "can't be changed with /add" in flat(out4), out4)
        out5, _ = drive(conn, sid, "\n/remove persona\n/q\n")
        ok("/remove refuses", "can't be changed with /remove" in flat(out5), out5)
        out6, _ = drive(conn, sid, f"\n/title {sid} Renamed\n/q\n")
        ok("/title refuses", "can't be renamed" in out6, out6)
        ok("...and the title really didn't change",
           dbmod.get_session_title(conn, sid) == "Main")

        print("\n--- ordinary facilities stay available on Main ---")
        out7, _ = drive(conn, sid, "\n/add tag important\n/status\n/q\n")
        ok("tagging still works", "Tagged session" in out7, out7)
        ok("...and shows in /status", "important" in out7, out7)

        # `/add <path>` is an ordinary facility, not a profile layer, and the
        # fixed-profile refusal used to sit above the path branch and swallow
        # it (1.4-01). Driven end to end — attach, then detach by #n — because
        # the bug was reachable only by typing a real path at a real Main.
        jail = Path(tempfile.mkdtemp())
        (jail / "note.md").write_text("attachable body", encoding="utf-8")
        saved_roots = commands.ATTACH_ROOTS
        commands.ATTACH_ROOTS = (jail,)
        try:
            out7b, _ = drive(conn, sid,
                             f"\n/add {jail / 'note.md'}\n/status\n/q\n")
        finally:
            commands.ATTACH_ROOTS = saved_roots
        ok("/add <path> attaches on Main", "Attached note.md" in flat(out7b),
           out7b)
        ok("...and is not refused as a profile change",
           "can't be changed with /add" not in flat(out7b), out7b)
        ok("...and shows in /status", "note.md" in flat(out7b), out7b)
        out7c, _ = drive(conn, sid, "\n/remove #1\ny\n/status\n/q\n")
        ok("/remove #n detaches it again",
           "note.md" not in flat(out7c).split("Attached")[-1][:80], out7c)

        # A pool name still refuses, path-shaped or not: the refusal moved to
        # the layer, it did not go away.
        out7d, _ = drive(conn, sid, "\n/add nosuchlayer\n/q\n")
        ok("a bare name still refuses",
           "can't be changed with /add" in flat(out7d), out7d)

        print("\n--- a broken live persona refuses the turn before "
              "persistence ---")
        before_msgs = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=?",
            (sid,)).fetchone()[0]
        (bundle_dir / mainchat.PERSONA_FILE).write_text("   ", encoding="utf-8")
        out8, _ = drive(conn, sid, "\nthis should not be sent\n/q\n")
        ok("the turn is refused, not silently answered",
           "Main chat unavailable" in out8, out8)
        after_msgs = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=?",
            (sid,)).fetchone()[0]
        ok("nothing new was persisted", after_msgs == before_msgs,
           (before_msgs, after_msgs))
        ok("the marker text never reached the db",
           conn.execute(
               "SELECT COUNT(*) FROM messages WHERE session_id=? AND "
               "content LIKE '%should not be sent%'",
               (sid,)).fetchone()[0] == 0)

        print("\n--- a live edit is picked up on the very next turn ---")
        (bundle_dir / mainchat.PERSONA_FILE).write_text(
            "A restored voice.", encoding="utf-8")
        captured = []
        main.stream_response = lambda messages, model=None: (
            captured.append(list(messages)) or
            ("an answer", {"prompt_tokens": 1, "completion_tokens": 1}, ""))
        out9, _ = drive(conn, sid, "\nhello again\n/q\n")
        ok("the turn actually reached the provider stub", bool(captured),
           out9[-200:])
        ok("the restored persona text rode the request",
           any("A restored voice." in (m.get("content") or "")
              for m in captured[-1]), captured[-1] if captured else None)

        print("\n--- the frozen First Message survives source edits and "
              "removal ---")
        original_fm = dbmod.get_first_message(conn, sid)["text"]
        (bundle_dir / mainchat.FIRST_MESSAGE_FILE).write_text(
            "A completely different opening.", encoding="utf-8")
        out10, _ = drive(conn, sid, "\n/q\n")
        ok("the session still opens with the original snapshot",
           original_fm in out10 and "completely different" not in out10,
           out10[:400])
        (bundle_dir / mainchat.FIRST_MESSAGE_FILE).unlink()
        out11, _ = drive(conn, sid, "\n/q\n")
        ok("...even after the source file is gone entirely",
           original_fm in out11, out11[:400])

        print("\n--- delete then recreate gets a genuinely new First "
              "Message ---")
        (bundle_dir / mainchat.FIRST_MESSAGE_FILE).write_text(
            "A brand new opening.", encoding="utf-8")
        (bundle_dir / mainchat.PERSONA_FILE).write_text(
            "A restored voice.", encoding="utf-8")
        # Confirmation is keyed to the target's *identity* (is_main), not how
        # it was looked up — deleting Main by its raw numeric id still asks
        # for 'main' back, the same as `/delete chat main` would.
        out12, _ = drive(conn, sid, f"\n/delete chat {sid}\nmain\n")
        ok("delete succeeds through the ordinary chat path",
           "deleted" in out12, out12)
        ok("Main is gone", dbmod.main_session_id(conn) is None)
        new_sid = main._open_main(conn)
        ok("recreation succeeds", new_sid is not None)
        new_fm = dbmod.get_first_message(conn, new_sid)
        ok("...with the current source text, not the old snapshot",
           new_fm and new_fm["text"] == "A brand new opening.", new_fm)

        print("\n--- a Main row missing its frozen First Message refuses "
              "to open, as corruption ---")
        conn.execute(
            "UPDATE sessions SET first_message_text=NULL WHERE id=?",
            (new_sid,))
        conn.commit()
        out13, outcome13 = drive(conn, new_sid, "\n/q\n")
        ok("run_session refuses and returns to the hub",
           outcome13 is None and "corrupt" in out13, out13)
        # Clean up the deliberately-corrupted row so later scenarios get a
        # genuine, valid Main again rather than reopening this one.
        dbmod.delete_session(conn, new_sid)

        print("\n--- turn-path parity: streaming and tools send the same "
              "Main prefix ---")
        (bundle_dir / mainchat.SYSTEM_PROMPT_FILE).write_text(
            "You are Main, parity edition.", encoding="utf-8")
        (bundle_dir / mainchat.PERSONA_FILE).write_text(
            "A parity voice.", encoding="utf-8")
        (bundle_dir / mainchat.FIRST_MESSAGE_FILE).write_text(
            "Parity opening.", encoding="utf-8")
        sid_p = main._open_main(conn)

        stream_seen = []
        main.stream_response = lambda messages, model=None: (
            stream_seen.append(list(messages)) or
            ("stream answer", {"prompt_tokens": 1, "completion_tokens": 1}, ""))
        drive(conn, sid_p, "\n/tools off\nhello streaming\n/q\n")

        import agent as agentmod
        tool_seen = []
        agentmod.call_api = lambda messages, model=None, tools=None: (
            tool_seen.append(list(messages)) or
            {"choices": [{"message": {"role": "assistant",
                                      "content": "tool answer"}}],
             "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
        main.TOOLS_ENABLED = True
        drive(conn, sid_p, "\nhello tools\n/q\n")
        main.TOOLS_ENABLED = False

        def system_layers(msgs):
            return [m for m in msgs if m.get("role") == "system"]

        ok("both paths actually ran", bool(stream_seen) and bool(tool_seen),
           (len(stream_seen), len(tool_seen)))
        ok("the streaming request carries the live Main persona/prompt",
           any("A parity voice." in (m.get("content") or "")
              for m in system_layers(stream_seen[-1]))
           and any("parity edition" in (m.get("content") or "")
                  for m in system_layers(stream_seen[-1])), stream_seen[-1])
        ok("the tool request carries the identical system layers",
           system_layers(stream_seen[-1]) == system_layers(tool_seen[-1])[
               :len(system_layers(stream_seen[-1]))],
           (system_layers(stream_seen[-1]), system_layers(tool_seen[-1])))
        ok("both opened with the same frozen First Message",
           any(m.get("content") == "Parity opening."
              for m in stream_seen[-1])
           and any(m.get("content") == "Parity opening."
                  for m in tool_seen[-1]))

        print("\n--- private negative: no Main request can create an "
              "on-disk Main row ---")
        dbmod.delete_session(conn, sid_p)
        assert dbmod.main_session_id(conn) is None
        priv = dbmod.db(":memory:")
        psid = dbmod.new_session(priv, title="(untitled)")
        drive(priv, psid,
             "\n/add trait anything\n/status\n/tools off\nhello\n/q\n",
             private=True, app_conn=conn)
        priv.close()
        ok("the durable db still has no Main row",
           dbmod.main_session_id(conn) is None)
    finally:
        mainchat.MAIN_CHAT_DIR = saved_dir
        main.TOOLS_ENABLED = False

    conn.close()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
