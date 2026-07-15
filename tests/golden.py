#!/usr/bin/env python3
"""
golden.py — characterisation harness for the chat.py split.

Not a unit test suite. It pins down what the REPL *currently prints*, so a
refactor that is supposed to change nothing can be shown to change nothing.

    python3 tests/golden.py record    # capture current output as the baseline
    python3 tests/golden.py check     # re-run and diff against the baseline

Drives a real REPL over a fixture database with scripted stdin. Only exercises
commands that make no API call, so it costs nothing and can't flake on the
network — the chat path and :recall/:remember are covered by hand instead.

If `check` fails after a pure move, the move was not pure.
"""
import io, os, re, sys, sqlite3, difflib, contextlib, shutil
from pathlib import Path
from rich.console import Console

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

# Python validates a .pyc on (mtime, size). Two versions of a file that differ
# only in the case of a word are the same size, and an edit landing in the same
# second as the last compile keeps the mtime — so stale bytecode gets reused and
# this harness reports on code that is no longer on disk. That is a very
# convincing way to lie about whether a refactor was safe. Compile from source.
sys.dont_write_bytecode = True
for _cache in ROOT.glob("**/__pycache__"):
    if ".venv" not in _cache.parts:
        shutil.rmtree(_cache, ignore_errors=True)
BASELINE = HERE / "golden_baseline.txt"
FIXTURE = HERE / "_fixture.db"

# Commands to drive. No API calls: no chat turns, no :recall, no :remember.
SCRIPT = [
    ":list",
    ":config",
    ":tokens",
    ":title",
    ":title 2",
    ":tags",
    ":tags 2",
    ":taglist",
    ":tag wsl",
    ":tags",
    ":untag wsl",
    ":tag 2 python",
    ":taglist",
    ":model",
    ":models",
    ":prompts",
    ":prompt",
    ":prompt off",
    ":personas",
    ":persona",
    ":persona off",
    ":grep vector",
    ":grep zzz-no-such-word",
    ":grep",
    ":forget",
    ":title 1 Renamed By Golden",
    ":title",
    ":q",
]

def build_fixture(path):
    """A small deterministic database. Fixed timestamps: no clock in output."""
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY, title TEXT, model TEXT, provider TEXT,
            created_at TEXT, updated_at TEXT,
            system_prompt TEXT, system_prompt_name TEXT,
            persona TEXT, persona_name TEXT);
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY, session_id INTEGER, role TEXT,
            content TEXT, model TEXT, tokens_in INTEGER, tokens_out INTEGER,
            created_at TEXT);
        CREATE INDEX idx_messages_session ON messages(session_id);
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT UNIQUE);
        CREATE TABLE session_tags (
            session_id INTEGER, tag_id INTEGER,
            PRIMARY KEY (session_id, tag_id));
    """)
    T = "2026-01-01T09:00:00"
    conn.executemany(
        "INSERT INTO sessions (id,title,model,provider,created_at,updated_at) "
        "VALUES (?,?,?,?,?,?)",
        [(1, "Golden session one", "glm-5.2", "nano-gpt", T, T),
         (2, "Golden session two", "glm-5.2", "nano-gpt", T, T),
         (3, "(untitled)", "glm-5.2", "nano-gpt", T, T)])
    conn.executemany(
        "INSERT INTO messages "
        "(session_id,role,content,model,tokens_in,tokens_out,created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        [(1, "user", "what did we decide about the vector db?", "glm-5.2", 10, 0, T),
         (1, "assistant", "We chose sqlite-vec for the vector store.", "glm-5.2", 0, 20, T),
         (1, "user", "and the chunk size?", "glm-5.2", 5, 0, T),
         (1, "assistant", "500 tokens with 75 overlap.", "glm-5.2", 0, 8, T),
         (2, "user", "unrelated session content", "glm-5.2", 4, 0, T),
         (2, "assistant", "indeed unrelated", "glm-5.2", 0, 3, T)])
    conn.execute("INSERT INTO tags (id,name) VALUES (1,'memory')")
    conn.execute("INSERT INTO session_tags VALUES (1,1)")
    conn.commit()
    conn.close()

# Anything that legitimately varies run to run. If a refactor changes only
# these, that's not a regression.
SCRUB = [
    (re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?"), "<TS>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "<DATE>"),
    (re.compile(r"0x[0-9a-f]+"), "<ADDR>"),
    (re.compile(r"/tmp/[^\s'\"]+"), "<TMP>"),
    (re.compile(re.escape(str(ROOT))), "<ROOT>"),
    (re.compile(re.escape(str(Path.home()))), "<HOME>"),
]

def normalise(text):
    for pat, rep in SCRUB:
        text = pat.sub(rep, text)
    # trailing whitespace is invisible and rich pads lines
    return "\n".join(l.rstrip() for l in text.splitlines())

def capture():
    build_fixture(FIXTURE)
    # Rich reads width at construction, so pin it before importing anything
    # that builds a Console at import time.
    os.environ["COLUMNS"] = "100"
    os.environ["TERM"] = "dumb"

    import chat
    chat.DB_PATH = FIXTURE

    # Redirect the shared Console by mutating it, never by rebinding a module
    # attribute: once modules do `from ui import console`, setting chat.console
    # would leave every other module writing to the real stdout and this
    # harness would quietly grade the wrong output.
    consoles = []
    for mod in list(sys.modules.values()):
        c = getattr(mod, "console", None)
        if isinstance(c, Console) and c not in consoles:
            consoles.append(c)

    stdin = io.StringIO("\n".join(SCRIPT) + "\n")
    out = io.StringIO()
    real_stdin, saved = sys.stdin, [c.file for c in consoles]
    sys.stdin = stdin
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            for c in consoles:
                c.file = out
            chat.repl(session_id=1)
    finally:
        sys.stdin = real_stdin
        for c, f in zip(consoles, saved):
            c.file = f
        FIXTURE.unlink(missing_ok=True)
    return normalise(out.getvalue())

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    text = capture()
    if mode == "record":
        BASELINE.write_text(text)
        print(f"recorded {len(text.splitlines())} lines -> {BASELINE}")
        return 0
    if not BASELINE.exists():
        print("no baseline; run: python3 tests/golden.py record"); return 2
    want = BASELINE.read_text()
    if normalise(want) == text:
        print(f"golden: OK ({len(text.splitlines())} lines identical)")
        return 0
    diff = list(difflib.unified_diff(
        normalise(want).splitlines(), text.splitlines(),
        "baseline", "current", lineterm=""))
    print(f"golden: DIFF ({len(diff)} lines)")
    print("\n".join(diff[:80]))
    return 1

if __name__ == "__main__":
    sys.exit(main())
