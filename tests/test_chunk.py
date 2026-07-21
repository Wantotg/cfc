#!/usr/bin/env python3
"""
test_chunk.py — chunk.py's slicing rules.

    python3 tests/test_chunk.py

The chunker had no suite, and its window is the one piece of the memory layer
whose output silently becomes permanent: a bad slice is embedded, stored, and
then only visible as a slightly worse ranking months later. BACKLOG carried
"overlap cuts mid-word" for six days precisely because nothing failed.

Pins three things:
  - the sizing contract (short stays whole, long is sliced, nothing exceeds the
    hard cap, overlap actually overlaps),
  - boundary seeking at BOTH edges — a chunk must not open or close mid-word,
    which is the bug this suite was written for,
  - the message-boundary invariant, via split_kinds: thinking and message
    segments never merge into one chunk.

No API key, no db, no network.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

from chunk import (slice_text, split_kinds, est_tokens, _end_at, _open_at,
                   TARGET_TOKENS, OVERLAP_TOKENS, CHARS_PER_TOK, _MIN_FILL,
                   THINK_OPEN, THINK_CLOSE)

PASS, FAIL = [], []
TARGET_CHARS = TARGET_TOKENS * CHARS_PER_TOK


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {detail}")


def prose(nwords, word="alpha"):
    """Plain prose with sentence and paragraph structure, long enough to slice."""
    sentences = []
    for i in range(nwords // 10):
        sentences.append(" ".join(f"{word}{i}_{j}" for j in range(10)) + ".")
    out = []
    for i in range(0, len(sentences), 4):
        out.append(" ".join(sentences[i:i + 4]))
    return "\n\n".join(out)


def main():
    print("chunk.py — sizing")
    short = "a short page about the cat."
    ok("short text is returned whole, unsliced",
       slice_text(short) == [short])

    long = prose(4000)
    pieces = slice_text(long)
    ok("long text is sliced into several chunks", len(pieces) > 3,
       f"got {len(pieces)}")
    ok("no chunk exceeds the hard character cap",
       all(len(p) <= TARGET_CHARS for p in pieces),
       f"longest {max(len(p) for p in pieces)} > {TARGET_CHARS}")
    ok("no chunk is empty or whitespace-only",
       all(p.strip() for p in pieces))
    ok("seeking never starves a chunk below the fill floor",
       all(len(p) >= TARGET_CHARS * _MIN_FILL for p in pieces[:-1]),
       f"shortest non-final {min((len(p) for p in pieces[:-1]), default=0)}")

    print("\nchunk.py — the mid-word bug (BACKLOG: chunk 1034)")
    # The reported symptom: a chunk beginning 'ne that decides when...'. Every
    # chunk must open and close on a whole word.
    starts_clean = [p for p in pieces if p and not p[0].isspace()]
    ok("every chunk opens on a word character",
       all(p[0].isalnum() or p[0] in "#>-*[(\"'" for p in pieces),
       f"bad openers: {[p[:14] for p in pieces if not (p[0].isalnum() or p[0] in '#>-*[(\"' + chr(39))][:3]}")

    words = set(long.split())
    def first_word(p): return p.split()[0].rstrip(".,;")
    def last_word(p):  return p.split()[-1].rstrip(".,;")
    bad_open = [p[:20] for p in pieces if first_word(p) not in words
                and first_word(p) + "." not in words]
    bad_close = [p[-20:] for p in pieces if last_word(p) not in words
                 and last_word(p) + "." not in words]
    ok("no chunk STARTS on a word fragment", not bad_open, f"{bad_open[:3]}")
    ok("no chunk ENDS on a word fragment", not bad_close, f"{bad_close[:3]}")

    print("\nchunk.py — overlap")
    ok("consecutive chunks overlap (context is not lost at the seam)",
       any(pieces[0].split()[-1] in pieces[1] for _ in [0]) or
       len(set(pieces[0].split()) & set(pieces[1].split())) > 0,
       "no shared words between chunk 0 and 1")
    joined = " ".join(pieces)
    sample = [w for w in long.split() if w][::37]
    missing = [w for w in sample if w.rstrip(".") not in joined]
    ok("slicing loses no content", not missing, f"missing {missing[:3]}")

    print("\nchunk.py — pathological input (must not hang or crash)")
    solid = "x" * (TARGET_CHARS * 3)          # no boundary anywhere
    sp = slice_text(solid)
    ok("an unbroken blob still terminates and is capped",
       len(sp) >= 3 and all(len(p) <= TARGET_CHARS for p in sp))
    ok("a blob with one space near the end terminates",
       len(slice_text("y" * (TARGET_CHARS * 2) + " tail")) >= 2)
    nl = slice_text(("word " * 50 + "\n") * 60)
    ok("newline-dense text slices without empty chunks",
       all(p.strip() for p in nl) and len(nl) > 1)

    print("\nchunk.py — boundary helpers")
    t = "alpha beta gamma. delta epsilon\n\nzeta eta theta"
    ok("_end_at prefers a paragraph break when one is in range",
       _end_at(t, 0, len(t) - 5) == t.index("\n\n") + 2,
       f"got {_end_at(t, 0, len(t) - 5)}")
    ok("_end_at hard-cuts when the span has no boundary",
       _end_at("z" * 100, 0, 50) == 50)
    ok("_end_at returns the end of text when the window covers it",
       _end_at(t, 0, len(t) + 99) == len(t))
    ok("_open_at moves off the middle of a word",
       t[_open_at(t, 2):].startswith("beta"),
       f"got {t[_open_at(t, 2):][:12]!r}")
    ok("_open_at is a no-op with no whitespace within the window",
       _open_at("q" * 500, 3) == 3)

    print("\nchunk.py — message boundary invariant")
    content = f"before text{THINK_OPEN}secret reasoning{THINK_CLOSE}after text"
    segs = split_kinds(content)
    ok("thinking is separated from message",
       [k for k, _ in segs] == ["message", "thinking", "message"],
       f"got {[k for k, _ in segs]}")
    ok("thinking text never leaks into a message segment",
       all("secret reasoning" not in txt for k, txt in segs if k == "message"))
    ok("sentinels are stripped from segment text",
       all(THINK_OPEN not in txt and THINK_CLOSE not in txt for _, txt in segs))
    ok("plain content yields a single message segment",
       split_kinds("just a normal page") == [("message", "just a normal page")])

    print("\nchunk.py — token estimate")
    ok("est_tokens never returns 0 for non-empty text", est_tokens("a") >= 1)
    ok("est_tokens scales with length",
       est_tokens("x" * 4000) > est_tokens("x" * 400))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
