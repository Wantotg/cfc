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
import io, os, re, sys, sqlite3, difflib, contextlib, shutil, tempfile
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
from parse import PREFIX

BASELINE = HERE / "golden_baseline.txt"
FIXTURE = HERE / "_fixture.db"
# The chat screen lists the prompt and persona files that are *available*, so
# without this the baseline would depend on the contents of Cas's vault and
# break every time he adds one. Pinned to a fixture folder for the same reason
# the database is: a characterization harness must only change when the code
# changes.
FIXTURE_PROMPTS = HERE / "_fixture_prompts"
FIXTURE_PERSONAS = HERE / "_fixture_personas"
FIXTURE_TRAITS = HERE / "_fixture_traits"
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
FIXTURE_LOG = HERE / "_fixture_errors.log"

# **The outbox is environment too, and the baseline used to pin the live one**
# (`D-01`, fixed v1.0). Re-recording for an unrelated one-line change carried a
# second hunk: two journal proposals had been filed since the last `record`, so
# the baseline said `2 of 2 can be filed` and the run said `(nothing pending)`.
# Nothing about the code had changed.
#
# That is the `config.py` scar in a new place — *anything a baseline pins that
# lives in config rather than in source is this bug* — and it fails in the good
# direction, loudly, which is precisely what makes it dangerous: a `record`
# whose diff has a hunk you learn to skip is a `record` that will one day carry
# a real regression past you. It cost exactly that twice in one session, and
# both times the reasoning was "that one's not mine".
#
# **Redirected rather than dropped**, which was the decision between D-01's two
# written-up options (Cas, 2026-07-29). `/outbox` stays in `SCRIPT`, so a
# refactor that changes its rendering is still caught by the sweep — and the
# mechanism is the one `capture()` already uses for `DB_PATH`, `VAULT_PATH` and
# the model lists, rather than a second way of doing the same thing. The
# fixture carries one filable proposal and one refusal on purpose: both
# verdicts render, so what stays pinned is the part that is about the code.
FIXTURE_OUTBOX = HERE / "_fixture_outbox"
FIXTURE_FILED = HERE / "_fixture_filed"

# The notes inbox: /status's new row needs something to count, and driving
# it read-only ('/clear notes' then 'back') would otherwise be the only new
# screen this harness never renders. Nested under FIXTURE_FILED rather than
# given its own top-level fixture folder so it inherits that folder's
# MOVE_ROOTS patch below instead of needing a second one.
FIXTURE_NOTES = FIXTURE_FILED / "notes"
FIXTURE_NOTES_ARCHIVE = FIXTURE_FILED / "notes archive"

# The same rule the prompts fixture follows, applied to config.py's models:
# :config, :models and :tools print them verbatim, so editing your own MODELS
# failed `check` on lines that describe your config and not the code.
#
# Short ids on purpose — :models renders a rich table whose column width is
# the longest id, so a real provider id makes the *layout* config-derived too.
# 'glm-5.2' matches the fixture sessions' model, so it exercises the
# '<-- current' row; keeping it out of FIXTURE_TOOLS_MODELS is what keeps
# :tools' "doesn't support tools" branch covered. These three feed one
# `models.MODELS` record list built in capture() — see the comment there.
FIXTURE_MODEL = "glm-5.2"
FIXTURE_MODELS = ["glm-5.2", "fixture/tool-model"]
FIXTURE_TOOLS_MODELS = ["fixture/tool-model"]
FIXTURE_ROUTINE_MODELS = ["fixture/tool-model"]
FIXTURE_API_BASE = "https://api.example.invalid/v1"
# Truthy and fixed, never printed itself — the config screen renders only
# whether a key is set, so a real key and an unset one must not disagree
# about which line the baseline pins.
FIXTURE_API_KEY = "fixture-key-not-real"

# 1.2's command screens read the routine store and the wiki corpus live.
# Both fixtures are deliberately empty — a routine store and a wiki repo
# convincing enough to test the *rich* states (armed review, routines with
# problems, narrow rendering) belong to tests/test_screens.py, which builds
# them in a temp dir; this harness only needs the two screens' "nothing here
# yet" / "unavailable" states to stay pinned.
FIXTURE_ROUTINES = HERE / "_fixture_routines"
FIXTURE_ROUTINE_PROMPTS = HERE / "_fixture_routine_prompts"
FIXTURE_ROUTINE_LOGS = HERE / "_fixture_routine_logs"

# Commands to drive. No API calls: no chat turns, no :recall, no :remember.
SCRIPT = [
    f"{PREFIX}help",
    f"{PREFIX}list",
    f"{PREFIX}list sessions",
    f"{PREFIX}list chats",
    f"{PREFIX}list prompts",
    f"{PREFIX}list personas",
    f"{PREFIX}list traits",
    f"{PREFIX}list models",
    f"{PREFIX}list tags",
    f"{PREFIX}list nonsense",
    # Bare /config is driven at the very end of this script now — it enters
    # a command screen rather than printing once, so anything after it in
    # SCRIPT would be read as a screen command instead of a chat command.
    f"{PREFIX}status",
    f"{PREFIX}status prompt",
    # The absorbing verbs, then the ones that change something. Order matters:
    # /status is driven again after the attaches so the baseline holds both the
    # empty and the carrying screen.
    f"{PREFIX}add alpha",
    f"{PREFIX}add gamma",
    f"{PREFIX}add trait epsilon",
    f"{PREFIX}add trait zeta",
    f"{PREFIX}add tag wsl",
    f"{PREFIX}status",
    f"{PREFIX}status prompt",
    f"{PREFIX}status trait",
    f"{PREFIX}add epsilon",
    f"{PREFIX}remove epsilon",
    f"{PREFIX}remove trait",
    f"{PREFIX}remove persona",
    f"{PREFIX}remove tag wsl",
    f"{PREFIX}remove excerpts",
    f"{PREFIX}remove nosuchthing",
    f"{PREFIX}add nosuchthing",
    f"{PREFIX}add",
    f"{PREFIX}remove",
    f"{PREFIX}status",
    # Tags on another session, and the bare-integer rule.
    f"{PREFIX}add tag 2 python",
    f"{PREFIX}list tags",
    f"{PREFIX}model",
    f"{PREFIX}search vector",
    f"{PREFIX}search zzz-no-such-word",
    f"{PREFIX}search",
    # /tools echoes the read/write root split and the "no auto-approve exists"
    # line. Pinned here because that output is a statement about the permission
    # model, not just a status dump.
    f"{PREFIX}tools",
    f"{PREFIX}database",
    # Only the usage error is safe here: session 1 already has an assistant
    # turn from build_fixture(), so a bare /continue would make a real API
    # call — the refusal path (nothing to continue from) is covered instead
    # in tests/test_turn_paths.py, against a stubbed provider.
    f"{PREFIX}continue extra argument",
    # An unknown /connect target, and the accepted 'embed' alias — both are
    # local, no-API-call checks (`W-0.9.1-08`, `W-1.1.1-01`). Deterministic
    # here because `preflight.connection_state` is stubbed to "hosted" below,
    # which `preflight.ensure` returns early on, before any subprocess call.
    f"{PREFIX}connect nonsense",
    f"{PREFIX}connect embed",
    # Kinds are required where something is destroyed, and refused where the
    # kind is unknown. Both print and act on nothing, which is the point.
    f"{PREFIX}delete",
    f"{PREFIX}delete wombat",
    f"{PREFIX}update",
    f"{PREFIX}update wombat",
    f"{PREFIX}title 1 Renamed By Golden",
    f"{PREFIX}title abc",
    # The v0.8 taxonomy's old words are now real aliases, not corrections
    # (v0.9 deleted RETIRED). Every one of these would otherwise fall through
    # to the model, costing an API call and returning a confused answer — which
    # is exactly what `/routines` did until v0.8.2. `detach` is deliberately not
    # among them: its replacement takes `#<n>`, a different argument shape, so
    # no alias can carry it. See parse.ALIASES.
    f"{PREFIX}prompts",
    f"{PREFIX}models",
    f"{PREFIX}tags",
    f"{PREFIX}tokens",
    f"{PREFIX}attached",
    f"{PREFIX}outbox",
    f"{PREFIX}grep vector",
    f"{PREFIX}forget",
    # Both guided flows, driven read-only — 'back' cancels at the first
    # prompt, so neither actually touches the outbox or notes fixtures. What
    # this pins is the entry screen: the listing and the usage/refusal text.
    f"{PREFIX}move",
    "back",
    f"{PREFIX}clear notes",
    "back",
    f"{PREFIX}clear",
    # 1.2's command screens. Bare /config now ends the chat session (the
    # same cleanup /q does) and enters a screen — deliberately last in this
    # script, and its own 'q' is what ends the driven session; there is no
    # trailing /q after this block. The fixture has no routines and no wiki
    # corpus, so both screens exercise their deterministic 'nothing here yet'
    # / 'unavailable' states rather than a git repo or a routine store this
    # harness would have to fake convincingly. Richer states (armed review,
    # routines with problems, narrow rendering) are covered in
    # tests/test_screens.py instead.
    f"{PREFIX}config",
    "refresh",
    "help",
    "wiki",
    "status",
    "help",
    "routine",
    "help",
    "q",
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


def assert_not_repo_or_real_roots(path, what):
    """Refuse a `/tools` fixture root that is the cfc source tree, or one of
    Cas's own configured `TOOLS_ROOTS`/`WRITE_ROOTS` (`D-11`).

    `/tools` prints permission-model prose, not a status dump — read-roots-
    are-not-write-roots is the load-bearing half of it — so a fixture root
    that happens to coincide with the real thing would make the baseline a
    property of *this machine's config.py* again, exactly the `config.py.bak`
    class of bug this harness exists to keep out. Checked before the values
    are assigned, never after, same as every other guard here.
    """
    p = Path(path).expanduser().resolve()
    if p == ROOT or ROOT in p.parents:
        raise AssertionError(f"{what}: refuses a /tools fixture root under "
                             f"the cfc source tree ({ROOT})")
    try:
        from config import TOOLS_ROOTS as real_tools, WRITE_ROOTS as real_write
        real_roots = tuple(Path(r).expanduser().resolve()
                          for r in (tuple(real_tools) + tuple(real_write)))
    except Exception:
        real_roots = ()
    if p in real_roots:
        raise AssertionError(f"{what}: refuses Cas's own configured root {p}")


def build_prompt_fixtures():
    """Two files in each pool, with fixed names."""
    for d, names in ((FIXTURE_PROMPTS, ("alpha", "beta")),
                     (FIXTURE_PERSONAS, ("gamma", "delta")),
                     (FIXTURE_TRAITS, ("epsilon", "zeta"))):
        d.mkdir(exist_ok=True)
        for n in names:
            (d / f"{n}.md").write_text(f"# {n}\nfixture\n", encoding="utf-8")


def build_outbox_fixture():
    """Two proposals: one that can be filed, one that cannot.

    Both verdicts, because both have their own rendering and the refusal's is
    the one with a rule attached — `show_outbox` prints the destination that
    was *asked for* beside the reason, so the model's suggestion stays
    auditable rather than being replaced by the error. A fixture with only
    filable proposals would leave that untested and look complete.
    """
    for d in (FIXTURE_OUTBOX, FIXTURE_FILED):
        d.mkdir(exist_ok=True)
    (FIXTURE_OUTBOX / "filable-note.md").write_text(
        f"---\ndestination: {FIXTURE_FILED}\ntitle: A Filable Note\n---\n\n"
        "fixture\n", encoding="utf-8")
    (FIXTURE_OUTBOX / "no-destination.md").write_text(
        "---\ntitle: Missing Its Destination\n---\n\nfixture\n",
        encoding="utf-8")


def clean_outbox_fixture():
    """Path checked before the unlink, not after — invariant #1."""
    for d in (FIXTURE_OUTBOX, FIXTURE_FILED):
        assert_not_real_vault(d, "clean_outbox_fixture")
        if d.is_dir():
            for f in d.glob("*.md"):
                f.unlink()
            d.rmdir()


def build_notes_fixture():
    """Two notes and the backstage template, so /status's new row has
    something to count and the template's exclusion is exercised too. SCRIPT
    drives '/clear notes' read-only ('back' cancels), so this is never
    actually emptied — clean_notes_fixture() removes it regardless."""
    FIXTURE_NOTES.mkdir(parents=True, exist_ok=True)
    (FIXTURE_NOTES / "one.md").write_text("first\n", encoding="utf-8")
    (FIXTURE_NOTES / "two.md").write_text("second\n", encoding="utf-8")
    (FIXTURE_NOTES / "note template.md").write_text(
        "template\n", encoding="utf-8")


def clean_notes_fixture():
    """Must run before clean_outbox_fixture(): FIXTURE_NOTES sits inside
    FIXTURE_FILED, and that function's rmdir() would fail with it still
    there."""
    assert_not_real_vault(FIXTURE_NOTES, "clean_notes_fixture")
    if FIXTURE_NOTES.is_dir():
        for f in FIXTURE_NOTES.glob("*.md"):
            f.unlink()
        FIXTURE_NOTES.rmdir()
    assert_not_real_vault(FIXTURE_NOTES_ARCHIVE, "clean_notes_fixture")
    if FIXTURE_NOTES_ARCHIVE.is_dir():
        shutil.rmtree(FIXTURE_NOTES_ARCHIVE)


def clean_fixture_vault():
    """Remove the fixture export folder. Guarded like everything else that
    deletes here: the path is checked before the unlink, not after."""
    assert_not_real_vault(FIXTURE_VAULT, "clean_fixture_vault")
    if FIXTURE_VAULT.is_dir():
        for f in FIXTURE_VAULT.glob("*.md"):
            f.unlink()
        FIXTURE_VAULT.rmdir()


def clean_prompt_fixtures():
    for d in (FIXTURE_PROMPTS, FIXTURE_PERSONAS, FIXTURE_TRAITS):
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
    build_outbox_fixture()
    build_notes_fixture()
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

    # And the error log, which is the same class of live-data hazard as the two
    # around it: this script drives the real `run_session`, and `run_session`
    # owns an `errorlog.log_error` call site. Nothing in the baseline provokes a
    # provider error today, so nothing lands — but `~/.cfc/errors.log` is
    # `B-01`'s evidence file, one of whose closing routes is *absence across the
    # 0.9 → 1.0 window*, and this is the script most likely to grow a new
    # command test. One holder rather than a loop: `LOG_PATH` lives in
    # `errorlog.py` alone, which imports no cfc module and is never re-exported.
    # The assertion is against the path it *was*, read off the module rather
    # than written out here — `assert_not_real` is the wrong guard for this one
    # (it compares against the real *database*, so it would pass forever no
    # matter where the log pointed) and a literal `~/.cfc/errors.log` would be a
    # second copy of a constant that lives in `errorlog.py`.
    import errorlog
    real_log = Path(errorlog.LOG_PATH).expanduser().resolve()
    errorlog.LOG_PATH = FIXTURE_LOG
    if Path(errorlog.LOG_PATH).expanduser().resolve() == real_log:
        raise AssertionError(f"errorlog.LOG_PATH: refusing to write to the "
                             f"real error log at {real_log}")

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

    # Pin VAULT_ROOT for the same reason, and the reason is not hypothetical:
    # :config prints it, it is display-only, and it lands in config.py by hand.
    # Left unpinned, the baseline says `(not set)` today and fails the day Cas
    # fills his in — a `check` failure on a line that says nothing about the
    # source. Exactly the bug that earned the SCRUB paragraph in HANDOVER.md.
    # Pinned to the fixture vault's parent so the shortening is *exercised*
    # rather than skipped: an empty root returns paths untouched, which would
    # leave ui.vault_relative uncovered here.
    for mod in list(sys.modules.values()):
        if getattr(mod, "__file__", None) and str(ROOT) in str(mod.__file__):
            if hasattr(mod, "VAULT_ROOT"):
                setattr(mod, "VAULT_ROOT", str(FIXTURE_VAULT))

    # Pin AUTO_EXPORT on rather than reading it from config. The script's :q
    # takes the export path only when it's true, so leaving it to config would
    # mean the baseline covers a different amount of code on different
    # machines — and `Auto-export: on` is a line :config prints into it.
    for mod in list(sys.modules.values()):
        if getattr(mod, "__file__", None) and str(ROOT) in str(mod.__file__):
            if hasattr(mod, "AUTO_EXPORT"):
                setattr(mod, "AUTO_EXPORT", True)

    # `D-01`: point the outbox at the fixture. **Patched at the seam, not in
    # config** — `mover._cfg` re-reads config on every call, so setting
    # `config.WRITE_ROOTS` would work today and stop working the moment
    # anything caches it, which is the reason `test_routines` patches
    # `routines.routine_dir` rather than config. These four functions are the
    # whole surface `list_proposals` consults.
    #
    # `wiki_dir`/`journal_dir` are pinned to None deliberately: a corpus
    # subfolder pulls in `wikigit` and the vault's real git state, which is
    # environment of exactly the kind this is fixing.
    import mover
    mover.outbox_roots = lambda: (FIXTURE_OUTBOX,)
    mover.move_roots = lambda: (FIXTURE_FILED,)
    mover.wiki_dir = lambda: None
    mover.journal_dir = lambda: None
    for root in mover.outbox_roots():
        assert_not_real_vault(root, "mover.outbox_roots")

    # `/tools` prints `commands.TOOLS_ROOTS`/`commands.WRITE_ROOTS` — its own
    # bound copies, read from config at commands.py's import time, never
    # `context.chat_context()`'s live read of the real `config` module. So
    # this patches those two names directly, the same seam every other fixture
    # here uses, and does NOT touch `config.WRITE_ROOTS` or go anywhere near
    # `context.ScopeError` (`D-11`).
    #
    # **The earlier attempt was pointed at the wrong thing, not the wrong
    # idea.** Repointing the real `config.WRITE_ROOTS` at a path under
    # `tests/` raised `ScopeError` — standing decision 4 refuses a write root
    # overlapping the cfc source — because that path *is* inside the source
    # tree. A real temp directory, created here and torn down in the
    # `finally` below, is outside it by construction and needs no exception
    # to the guard. `SCRUB` already collapses `/tmp/...` to `<TMP>`, so the
    # baseline is deterministic for free once the directory exists.
    _tools_dir = Path(tempfile.mkdtemp(prefix="cfc-golden-tools-"))
    assert_not_repo_or_real_roots(_tools_dir, "capture (/tools fixture)")
    import commands as _commands
    _commands.TOOLS_ROOTS = (_tools_dir,)
    _commands.WRITE_ROOTS = (_tools_dir,)

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
    # tools-capable and one not, which is what `:tools`' "doesn't support
    # tools" branch needs to stay covered.
    for mod in list(sys.modules.values()):
        if getattr(mod, "__file__", None) and str(ROOT) in str(mod.__file__):
            for attr, val in (("MODEL", FIXTURE_MODEL),
                              ("API_BASE", FIXTURE_API_BASE),
                              ("API_KEY", FIXTURE_API_KEY),
                              ("NOTES_DIR", str(FIXTURE_NOTES)),
                              ("NOTES_ARCHIVE_DIR", str(FIXTURE_NOTES_ARCHIVE))):
                if hasattr(mod, attr):
                    setattr(mod, attr, val if isinstance(val, str)
                            else list(val))

    # 1.2.1: the four model collections (MODELS/TOOLS_MODELS/ROUTINE_MODELS/
    # MODEL_LIMITS) became one — `models.MODELS`, a list of records. Patched
    # directly at that one seam rather than through the generic attr loop
    # above: the loop sets a *name* on every module that has one, and nothing
    # downstream still has a bare `MODELS` list of strings to receive it.
    import models as _models
    _models.MODELS = [_models._spec(m, tools=(m in FIXTURE_TOOLS_MODELS),
                                    routine=(m in FIXTURE_ROUTINE_MODELS))
                      for m in FIXTURE_MODELS]

    # 1.2: the config screen prints whether a key is set (never the key
    # itself) and reads the routine store and wiki corpus live. Same rule as
    # everything above — pin the seam, not config.py, or a real key/vault
    # turns a baseline into a property of *this machine's* config again.
    import preflight
    import routines as _routines
    import wikigit as _wikigit
    _routines.routine_dir = lambda: FIXTURE_ROUTINES
    _routines.prompt_dir = lambda: FIXTURE_ROUTINE_PROMPTS
    _routines.log_dir = lambda: FIXTURE_ROUTINE_LOGS
    _wikigit.wiki_dir = lambda: None
    _wikigit.journal_dir = lambda: None
    # A fixed, network-free answer — golden drives no chat turns and no API
    # calls, and a live probe against FIXTURE_API_BASE would be both a
    # network dependency and a wait for a DNS failure on every run.
    preflight.connection_state = lambda: ("hosted", "golden harness stub")

    # Every path into a pool goes through Pool.dir(), which reads `configured`
    # at call time — so re-pointing the pool is enough and no call site needs to
    # know. Patching config instead would miss anything that read it at import.
    import pools as _pools
    _pools.POOLS["prompt"].configured = str(FIXTURE_PROMPTS)
    _pools.POOLS["persona"].configured = str(FIXTURE_PERSONAS)
    _pools.POOLS["trait"].configured = str(FIXTURE_TRAITS)

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
        FIXTURE_LOG.unlink(missing_ok=True)
        clean_prompt_fixtures()
        clean_notes_fixture()
        clean_outbox_fixture()
        shutil.rmtree(_tools_dir, ignore_errors=True)

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
