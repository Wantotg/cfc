#!/usr/bin/env python3
"""test_mainchat.py — the Main chat profile bundle loader. No network, no
database.

    python3 tests/test_mainchat.py

One folder, three fixed filenames, two access modes. What's worth pinning:

* every way a bundle file can be unusable — unconfigured, missing, not a
  file, unreadable, empty — is named precisely, and the loader never returns
  a partial bundle (creation) or a partial live profile (reopen/turn use);
* the live-profile mode never reads `first message.md`, which is what keeps
  a stale or deleted source file from touching an existing session's frozen
  opening;
* `bundle_states()` never raises, for callers (the header, `/status`) that
  must render a broken bundle rather than crash on one.
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import mainchat

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:300]}")


def write_bundle(d, system_prompt="You are Main.", persona="A steady voice.",
                 first_message="Hello — where should we start?"):
    if system_prompt is not None:
        (d / mainchat.SYSTEM_PROMPT_FILE).write_text(system_prompt,
                                                      encoding="utf-8")
    if persona is not None:
        (d / mainchat.PERSONA_FILE).write_text(persona, encoding="utf-8")
    if first_message is not None:
        (d / mainchat.FIRST_MESSAGE_FILE).write_text(first_message,
                                                      encoding="utf-8")


def main_():
    saved = mainchat.MAIN_CHAT_DIR

    try:
        print("--- unconfigured ---")
        mainchat.MAIN_CHAT_DIR = ""
        try:
            mainchat.load_creation_bundle()
            ok("unconfigured raises for creation", False)
        except mainchat.MainChatProblem as e:
            ok("unconfigured names MAIN_CHAT_DIR, not a file",
               e.reason == mainchat.UNCONFIGURED, e.reason)
        try:
            mainchat.load_live_profile()
            ok("unconfigured raises for the live profile too", False)
        except mainchat.MainChatProblem as e:
            ok("...same reason", e.reason == mainchat.UNCONFIGURED, e.reason)

        print("\n--- directory missing entirely ---")
        tmp = Path(tempfile.mkdtemp())
        mainchat.MAIN_CHAT_DIR = str(tmp / "does-not-exist")
        try:
            mainchat.load_creation_bundle()
            ok("a missing directory raises", False)
        except mainchat.MainChatProblem as e:
            ok("...as MISSING, naming the system prompt path",
               e.reason == mainchat.MISSING
               and "system prompt.md" in e.path, (e.reason, e.path))

        print("\n--- one file missing ---")
        d = Path(tempfile.mkdtemp())
        write_bundle(d, first_message=None)
        mainchat.MAIN_CHAT_DIR = str(d)
        try:
            mainchat.load_creation_bundle()
            ok("a missing first message.md raises for creation", False)
        except mainchat.MainChatProblem as e:
            ok("...as MISSING, naming first message.md",
               e.reason == mainchat.MISSING and "first message.md" in e.path,
               (e.reason, e.path))
        sp, pe = mainchat.load_live_profile()
        ok("the live profile doesn't care — it never reads first message.md",
           sp.strip() == "You are Main." and pe.strip() == "A steady voice.",
           (sp, pe))

        print("\n--- not a file (a directory sitting where one belongs) ---")
        d2 = Path(tempfile.mkdtemp())
        write_bundle(d2)
        (d2 / mainchat.PERSONA_FILE).unlink()
        (d2 / mainchat.PERSONA_FILE).mkdir()
        mainchat.MAIN_CHAT_DIR = str(d2)
        try:
            mainchat.load_live_profile()
            ok("a directory where persona.md belongs raises", False)
        except mainchat.MainChatProblem as e:
            ok("...as NOT_FILE", e.reason == mainchat.NOT_FILE, e.reason)

        print("\n--- empty / whitespace-only ---")
        d3 = Path(tempfile.mkdtemp())
        write_bundle(d3, persona="   \n\t  \n")
        mainchat.MAIN_CHAT_DIR = str(d3)
        try:
            mainchat.load_live_profile()
            ok("a whitespace-only persona.md raises", False)
        except mainchat.MainChatProblem as e:
            ok("...as EMPTY, naming persona.md",
               e.reason == mainchat.EMPTY and "persona.md" in e.path,
               (e.reason, e.path))

        print("\n--- unreadable (bad encoding) ---")
        d4 = Path(tempfile.mkdtemp())
        write_bundle(d4)
        (d4 / mainchat.SYSTEM_PROMPT_FILE).write_bytes(b"\xff\xfe\x00\xff")
        mainchat.MAIN_CHAT_DIR = str(d4)
        try:
            mainchat.load_live_profile()
            ok("bytes that aren't valid UTF-8 raise", False)
        except mainchat.MainChatProblem as e:
            ok("...as UNREADABLE, carrying a detail",
               e.reason == mainchat.UNREADABLE and bool(e.detail),
               (e.reason, e.detail))

        print("\n--- a complete bundle ---")
        d5 = Path(tempfile.mkdtemp())
        write_bundle(d5, system_prompt="  You are Main.  \n",
                    persona="  A steady voice.  \n",
                    first_message="  Hello — where should we start?  \n")
        mainchat.MAIN_CHAT_DIR = str(d5)
        sp, pe, fm = mainchat.load_creation_bundle()
        ok("creation returns all three bodies, stripped",
           (sp, pe, fm) == ("You are Main.", "A steady voice.",
                            "Hello — where should we start?"),
           (sp, pe, fm))
        sp2, pe2 = mainchat.load_live_profile()
        ok("the live profile matches the same two bodies",
           (sp2, pe2) == (sp, pe), (sp2, pe2))

        print("\n--- bundle_states() never raises ---")
        mainchat.MAIN_CHAT_DIR = ""
        states = mainchat.bundle_states()
        ok("all three keys present even when unconfigured",
           set(states) == {"system_prompt", "persona", "first_message"},
           states)
        ok("every entry is (False, a MainChatProblem) when unconfigured",
           all(ok_ is False and isinstance(prob, mainchat.MainChatProblem)
              for ok_, prob in states.values()), states)

        mainchat.MAIN_CHAT_DIR = str(d5)
        states = mainchat.bundle_states()
        ok("a complete bundle reports all three ok",
           all(ok_ for ok_, _ in states.values()), states)

        d6 = Path(tempfile.mkdtemp())
        write_bundle(d6, first_message=None)
        mainchat.MAIN_CHAT_DIR = str(d6)
        states = mainchat.bundle_states()
        ok("a partial bundle reports only the missing one as broken",
           states["system_prompt"][0] and states["persona"][0]
           and not states["first_message"][0], states)
    finally:
        mainchat.MAIN_CHAT_DIR = saved

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
