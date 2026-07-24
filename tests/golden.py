#!/usr/bin/env python3
"""
golden.py — characterisation harness for the REPL.

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
# The chat screen lists the prompt and persona files that are *available*, so
# without this the baseline would depend on the contents of Cas's vault and
# break every time he adds one. Pinned to a fixture folder for the same reason
# the database is: a characterization harness must only change when the code
# changes.
FIXTURE_PROMPTS = HERE / "_fixture_prompts"
FIXTURE_PERSONAS = HERE / "_fixture_personas"
# The script ends with :q, and :q honours AUTO_EXPORT — so every `check` used
# to write the fixture session into Cas's real VAULT_PATH. Nothing was
# corrupted (the files overwrite each other) but "the tests don't touch
# anything real" is a load-bearing claim about how freely this suite gets run,
# and it was false.
#
# Redirected rather than disabled: switching AUTO_EXPORT off would fix the
# side effect by making the export path untested, and this harness's whole job
# is to notice when output changes. Now it runs for real, into here.
FIXTURE_VAULT = HERE / "_fixture_vault"

# The same rule the prompts fixture follows, applied to config.py's model
# lists: :config, :models and :tools print them verbatim, so editing your own
# MODELS failed `check` on lines that describe your config and not the code.
#
# Short ids on purpose — :models renders a rich table whose column width is
# the longest id, so a real provider id makes the *layout* config-derived too.
# 'glm-5.2' matches the fixture sessions' model, so it exercises the
# '<-- current' row; keeping it out of TOOLS_MODELS is what keeps the :tools
# "NOT in TOOLS_MODELS" branch covered.
FIXTURE_MODEL = "glm-5.2"
FIXTURE_MODELS = ["glm-5.2", "fixture/tool-model"]
FIXTURE_TOOLS_MODELS = ["fixture/tool-model"]
FIXTURE_ROUTINE_MODELS = ["fixture/tool-model"]
FIXTURE_API_BASE = "https://api.example.invalid/v1"

# Commands to drive. No API calls: no chat turns, no :recall, no :remember.
SCRIPT = [
    ":help",
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
    # :tools echoes the read/write root split and the "no auto-approve exists"
    # line. Pinned here because that output is now a statement about the
    # permission model, not just a status dump.
    ":tools",
    ":forget",
    ":title 1 Renamed By Golden",
    ":title",
    ":q",
]

REAL_DB = Path.home() / ".cfc" / "chat.db"


def _real_vault():
    """The configured export folder, or None if there is no readable config.

    Read **once**, at import, into REAL_VAULT — before capture() rewrites
    VAULT_PATH on every module that holds one, including config's own. Asking
    config for the real path *after* that would compare the fixture against
    itself and pass whatever it was handed, which is precisely the guard being
    unable to fail. (Written the other way first; the guard caught it.)

    None on a checkout with no config.py: this file must still run there.
    """
    try:
        from config import VAULT_PATH
        return Path(VAULT_PATH).expanduser().resolve()
    except Exception:
        return None


REAL_VAULT = _real_vault()


def assert_not_real_vault(path, what):
    """Refuse to let the harness export into the user's real vault.

    Same discipline as assert_not_real, and called for the same reason: before
    the write, never after. A redirect that silently didn't take is the exact
    failure this guard exists to catch, and it is invisible in the output —
    the export announces the filename, not the folder.
    """
    real = REAL_VAULT
    if real is not None and Path(path).expanduser().resolve() == real:
        raise AssertionError(f"{what}: refusing to export into the real "
                             f"vault at {real}")


def assert_not_real(path, what):
    """Refuse to touch the user's actual database. Called before anything
    destructive, never after.

    This exists because the original guard ran *after* build_fixture(), which
    opens with unlink(). Pointing FIXTURE at the real path to prove the guard
    worked deleted the real database and then correctly reported that it was
    protecting it. An assertion downstream of the damage is decoration.
    """
    p = Path(path).expanduser().resolve()
    if p == REAL_DB.expanduser().resolve():
        raise AssertionError(f"{what}: refusing to touch the real database "
                             f"at {p}")


def build_prompt_fixtures():
    """Two prompt files and two personas, with fixed names."""
    for d, names in ((FIXTURE_PROMPTS, ("alpha", "beta")),
                     (FIXTURE_PERSONAS, ("gamma", "delta"))):
        d.mkdir(exist_ok=True)
        for n in names:
            (d / f"{n}.md").write_text(f"# {n}\nfixture\n", encoding="utf-8")


def clean_fixture_vault():
    """Remove the fixture export folder. Guarded like everything else that
    deletes here: the path is checked before the unlink, not after."""
    assert_not_real_vault(FIXTURE_VAULT, "clean_fixture_vault")
    if FIXTURE_VAULT.is_dir():
        for f in FIXTURE_VAULT.glob("*.md"):
            f.unlink()
        FIXTURE_VAULT.rmdir()


def clean_prompt_fixtures():
    for d in (FIXTURE_PROMPTS, FIXTURE_PERSONAS):
        if d.is_dir():
            for f in d.glob("*.md"):
                f.unlink()
            d.rmdir()


def build_fixture(path):
    """A small deterministic database. Fixed timestamps: no clock in output."""
    assert_not_real(path, "build_fixture")
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
    # `:config` prints the last 4 of the API key. Not a secret — it is exactly
    # what a provider dashboard shows — but it made the baseline a property of
    # *this machine's config.py*, so rotating the key failed `check` on a line
    # that says nothing about the code. A tripwire that fires on something the
    # code can't cause is a tripwire that gets ignored, and this harness is the
    # one that has to be trusted after a refactor.
    #
    # Scrubs only the `...abcd` form on purpose: with no key set the line reads
    # `not set`, which will still diff against <KEY>. A config that lost its key
    # is a real finding and must stay visible.
    (re.compile(r"(API key:\s+)\.\.\.\S+"), r"\1<KEY>"),
]

def normalise(text):
    for pat, rep in SCRUB:
        text = pat.sub(rep, text)
    # trailing whitespace is invisible and rich pads lines
    return "\n".join(l.rstrip() for l in text.splitlines())

def capture():
    assert_not_real(FIXTURE, "capture")
    build_fixture(FIXTURE)
    build_prompt_fixtures()
    # Rich reads width at construction, so pin it before importing anything
    # that builds a Console at import time.
    os.environ["COLUMNS"] = "100"
    os.environ["TERM"] = "dumb"

    import main as chat

    # Point every module that holds a DB_PATH at the fixture. During the split
    # DB_PATH lives in db.py, and patching only main.DB_PATH would
    # leave the connection opening the real ~/.cfc/chat.db — this script runs
    # :title, :tag and :untag, so that is a live-data hazard, not a test bug.
    patched = []
    for name, mod in list(sys.modules.items()):
        if getattr(mod, "__file__", None) and str(ROOT) in str(mod.__file__):
            if hasattr(mod, "DB_PATH"):
                setattr(mod, "DB_PATH", FIXTURE)
                patched.append(name)
    if not patched:
        raise SystemExit("refusing to run: found no DB_PATH to redirect")

    for name in patched:
        assert_not_real(getattr(sys.modules[name], "DB_PATH"), f"{name}.DB_PATH")

    # Same treatment for VAULT_PATH, and for the same reason: export.py reads
    # its module global at call time, and commands.py holds a second copy that
    # :config prints. Patching one would leave the other pointing at the real
    # folder — either a live write or a baseline line that depends on Cas's
    # config.py rather than on the code. Both are the bug this loop exists for.
    assert_not_real_vault(FIXTURE_VAULT, "capture")
    FIXTURE_VAULT.mkdir(exist_ok=True)
    vaulted = []
    for name, mod in list(sys.modules.items()):
        if getattr(mod, "__file__", None) and str(ROOT) in str(mod.__file__):
            if hasattr(mod, "VAULT_PATH"):
                setattr(mod, "VAULT_PATH", str(FIXTURE_VAULT))
                vaulted.append(name)
    if not vaulted:
        raise SystemExit("refusing to run: found no VAULT_PATH to redirect")
    for name in vaulted:
        assert_not_real_vault(getattr(sys.modules[name], "VAULT_PATH"),
                              f"{name}.VAULT_PATH")

    # Pin AUTO_EXPORT on rather than reading it from config. The script's :q
    # takes the export path only when it's true, so leaving it to config would
    # mean the baseline covers a different amount of code on different
    # machines — and `Auto-export: on` is a line :config prints into it.
    for mod in list(sys.modules.values()):
        if getattr(mod, "__file__", None) and str(ROOT) in str(mod.__file__):
            if hasattr(mod, "AUTO_EXPORT"):
                setattr(mod, "AUTO_EXPORT", True)

    # Same class of bug as the API key, one layer up: :config, :models and
    # :tools all print config.py's model lists straight into the baseline, so
    # adding a model to your own config failed `check` on lines that say
    # nothing whatever about the code. Scrubbing them is the wrong tool — they
    # render inside a rich table whose column widths move with the longest id,
    # so the *layout* is config-derived too. Pin the lists instead, exactly as
    # DB_PATH and VAULT_PATH are pinned, and the baseline goes back to being a
    # property of the source.
    #
    # FIXTURE_MODELS is deliberately unlike a real config: two short ids, one
    # tools-capable and one not, which is what the `:tools` "NOT in
    # TOOLS_MODELS" branch needs to stay covered.
    for mod in list(sys.modules.values()):
        if getattr(mod, "__file__", None) and str(ROOT) in str(mod.__file__):
            for attr, val in (("MODEL", FIXTURE_MODEL),
                              ("MODELS", FIXTURE_MODELS),
                              ("TOOLS_MODELS", FIXTURE_TOOLS_MODELS),
                              ("ROUTINE_MODELS", FIXTURE_ROUTINE_MODELS),
                              ("API_BASE", FIXTURE_API_BASE)):
                if hasattr(mod, attr):
                    setattr(mod, attr, val if isinstance(val, str)
                            else list(val))

    # get_prompts_dir()/get_personas_dir() read these at call time, so patching
    # the module attribute is enough and no call site needs to know.
    import commands as _cmds
    _cmds.PROMPTS_DIR = str(FIXTURE_PROMPTS)
    _cmds.PERSONAS_DIR = str(FIXTURE_PERSONAS)

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
            # run_session, not repl: repl() is now the outer hub loop, and a
            # :q returns to the hub rather than ending. This harness drives one
            # session's command output, which is exactly run_session.
            conn = chat.db()
            chat.run_session(conn, session_id=1)
            conn.close()
    finally:
        sys.stdin = real_stdin
        for c, f in zip(consoles, saved):
            c.file = f
        FIXTURE.unlink(missing_ok=True)
        clean_prompt_fixtures()

    # The baseline pins the `[auto-exported: …]` line, which proves the message
    # printed. This proves a document landed: safe_export swallows its own
    # errors, so the two are not the same claim.
    exported = sorted(FIXTURE_VAULT.glob("*.md"))
    if not exported:
        raise AssertionError("auto-export wrote nothing into the fixture vault")
    if "session_id: 1" not in exported[0].read_text(encoding="utf-8"):
        raise AssertionError(f"exported {exported[0].name} is not the fixture "
                             f"session")
    clean_fixture_vault()
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
