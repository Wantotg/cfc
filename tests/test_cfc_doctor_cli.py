"""test_cfc_doctor_cli.py — `python -m cfc` and `python -m cfc doctor`
driven as real subprocesses, the interface a person actually runs.

Every test that needs an isolated configuration points the CLI at it with
`CFC_CONFIG_PATH` (`cfc.config_loader.CONFIG_PATH_ENV_VAR`) rather than
relying on cwd — cfc's discovery is root-relative by design (see
test_cfc_config_loader.py), so cwd alone cannot select a different config.
Root-relative discovery is proven separately below by running from two
different working directories against the *same* overridden configuration
and comparing states; "no flat runtime import" is proven by import tracing;
redaction and required-vs-optional exit behaviour are proven by inspecting
real stdout.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

sys.path.insert(0, str(ROOT))
from cfc import config_loader as _config_loader  # noqa: E402

VALID_BODY = (
    "API_BASE = 'https://provider.invalid/v1'\n"
    "API_KEY = 'fixture-key'\n"
    "MODEL = 'fixture-model'\n"
)


def config_env(path: Path | None) -> dict:
    """The environment that points the CLI at `path` via
    `CFC_CONFIG_PATH`, or at nothing (root-relative discovery, whatever is
    or is not really at the repository root) when `path` is None.
    """
    if path is None:
        return {}
    return {_config_loader.CONFIG_PATH_ENV_VAR: str(path)}


def run_cfc(args, cwd, extra_env=None, timeout=30):
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + existing if existing else "")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "cfc", *args],
        cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env,
    )


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.py"
    path.write_text(body, encoding="utf-8")
    return path


# --- no subcommand / unknown command -----------------------------------------

def test_no_subcommand_dispatches_to_the_tui_entry_point(monkeypatch):
    """Stage 4 loop 1 retires the old placeholder message: `python -m cfc`
    with no arguments now starts the real Textual client (`cfc.tui.run`).
    Driving that end to end needs a live terminal — a real subprocess with
    no tty attached blocks forever waiting on stdin rather than exiting, so
    this proves the dispatch wiring at the seam instead. `cfc.tui`'s own
    `build_app`/`CfcApp` behaviour, including every startup-refusal family,
    is proved directly and thoroughly in `tests/test_cfc_tui.py` through
    Textual's headless `Pilot`; real terminal feel is Cas's WSL/Windows
    Terminal playtest, not an automated proof this loop can give honestly.
    """
    from cfc import __main__ as cfc_main
    from cfc import tui

    calls = []
    monkeypatch.setattr(tui, "run", lambda: calls.append(1) or 7)

    code = cfc_main.main([])

    assert calls == [1]
    assert code == 7


def test_unknown_command_refuses_with_short_usage(tmp_path):
    result = run_cfc(["frobnicate"], cwd=tmp_path)
    assert result.returncode == 2
    assert "Unknown command" in result.stderr
    assert "doctor" in result.stderr


def test_doctor_rejects_extra_arguments(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    result = run_cfc(["doctor", "extra"], cwd=tmp_path, extra_env=config_env(path))
    assert result.returncode == 2
    assert "Usage" in result.stderr


# --- interpreter handling -----------------------------------------------------

def test_unsupported_interpreter_reports_before_any_other_output():
    """`entry.check_interpreter`'s own logic, driven the way the real
    version guard would be hit — construct the message directly rather
    than actually finding an unsupported interpreter to run this suite
    under, and confirm it names both the requirement and what is running.
    """
    from cfc import entry
    old = entry.MIN_PYTHON
    try:
        entry.MIN_PYTHON = (99, 0)
        message = entry.check_interpreter()
    finally:
        entry.MIN_PYTHON = old
    assert message is not None
    assert "99.0" in message
    assert "Python" in message


def test_unsupported_interpreter_exits_nonzero_via_main(monkeypatch):
    from cfc import __main__ as cfc_main
    from cfc import entry
    monkeypatch.setattr(entry, "MIN_PYTHON", (99, 0))
    code = cfc_main.main(["doctor"])
    assert code == 1


def test_unsupported_interpreter_message_reaches_real_stderr(tmp_path):
    """The same check, end to end through a real subprocess: patch
    `sys.version_info` from the outside by asking Python itself for an
    impossible requirement via a tiny wrapper script, so this proves the
    message actually reaches the process's stderr and exit code — not just
    the function in-process.
    """
    script = tmp_path / "run_with_bad_floor.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "from cfc import entry\n"
        "entry.MIN_PYTHON = (99, 0)\n"
        "from cfc.__main__ import main\n"
        "sys.exit(main(['doctor']))\n",
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, str(script)], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert "Python" in result.stderr
    assert "cfc doctor" not in result.stdout


def test_2_0_python_floor_is_3_14():
    """D-2.0-17's actual floor, named directly so a future accidental
    change to `MIN_PYTHON` fails here rather than only in a test that
    happens to construct a message around whatever the value currently is.
    """
    from cfc import entry
    assert entry.MIN_PYTHON == (3, 14)


def test_synthetic_python_3_13_is_refused_against_the_real_3_14_floor(tmp_path):
    """D-2.0-17, end to end: this project only ships 3.14, so there is no
    real 3.13 interpreter to run the suite under. Forcing the running
    interpreter to *report* 3.13, against the real, unpatched `MIN_PYTHON`,
    proves the same refusal path the entry gate exists for — both version
    numbers reach stderr, doctor's banner never prints, and nothing past
    entry.py (settings, diagnostics, doctor) gets imported.
    """
    script = tmp_path / "run_as_3_13.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "sys.version_info = (3, 13, 0, 'final', 0)\n"
        "from cfc.__main__ import main\n"
        "code = main(['doctor'])\n"
        "downstream = [n for n in ('cfc.doctor', 'cfc.settings', 'cfc.diagnostics')"
        " if n in sys.modules]\n"
        "print('DOWNSTREAM_IMPORTED:', downstream)\n"
        "sys.exit(code)\n",
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, str(script)], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    assert "3.14" in result.stderr
    assert "3.13" in result.stderr
    assert "cfc doctor" not in result.stdout
    assert "DOWNSTREAM_IMPORTED: []" in result.stdout


# --- documentation seams: example teaches 3.14, README still says 3.10 -----

def test_config_example_bootstrap_section_states_the_3_14_floor():
    text = (ROOT / "config.example.py").read_text(encoding="utf-8")
    bootstrap_section, _, _ = text.partition("CHAT_EXPORT_DIR")
    assert "3.14" in bootstrap_section


def test_readme_still_states_the_v1_9_1_3_10_floor():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Python 3.10" in text


# --- producer/parser: the real config.example.py through the real loader ----

def test_config_example_loads_through_the_real_loader_and_default_database_path(tmp_path):
    """The 2.0 database line in `config.example.py` is commented out, so
    this exercises `DATABASE_PATH` the way an unmodified copy actually
    would: configuration itself loads clean (no `ConfigLoadError`, no
    traceback), and the database row resolves to the ordinary 2.0 default —
    proof that renaming the field did not desync the shipped example from
    what `settings.py` reads.
    """
    example_path = ROOT / "config.example.py"
    result = run_cfc(["doctor"], cwd=tmp_path, extra_env=config_env(example_path))
    assert "Traceback" not in result.stdout + result.stderr
    assert "configuration" in result.stdout
    config_line = next(
        line for line in result.stdout.splitlines() if line.strip().startswith("configuration")
    )
    assert "ready" in config_line
    from cfc import settings as cfc_settings
    assert str(cfc_settings.DEFAULT_DATABASE_PATH.expanduser().resolve()) in result.stdout


# --- doctor: ordered output, redaction, required vs optional exit -----------

def test_doctor_ready_config_exits_zero_and_lists_ordered_rows(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    result = run_cfc(["doctor"], cwd=tmp_path, extra_env=config_env(path))
    assert result.returncode == 0
    names = ("runtime", "configuration", "chat provider",
              "2.0 database target", "vault", "embeddings", "file tools")
    for name in names:
        assert name in result.stdout, name
    order = [result.stdout.index(name) for name in names]
    assert order == sorted(order)


def test_doctor_required_error_exits_nonzero(tmp_path):
    path = write_config(tmp_path, "API_BASE = 'https://provider.invalid/v1'\nMODEL='m'\n")
    result = run_cfc(["doctor"], cwd=tmp_path, extra_env=config_env(path))
    assert result.returncode == 1
    assert "error" in result.stdout


def test_doctor_optional_absence_does_not_cause_nonzero_exit(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    result = run_cfc(["doctor"], cwd=tmp_path, extra_env=config_env(path))
    assert result.returncode == 0
    assert "unavailable" in result.stdout


def test_doctor_never_prints_the_api_key(tmp_path):
    marker = "SECRET-MARKER-DO-NOT-LEAK-cli-4b19"
    path = write_config(
        tmp_path,
        f"API_BASE = 'https://provider.invalid/v1'\nAPI_KEY = {marker!r}\nMODEL='m'\n",
    )
    result = run_cfc(["doctor"], cwd=tmp_path, extra_env=config_env(path))
    assert marker not in result.stdout
    assert marker not in result.stderr


def test_doctor_never_prints_a_traceback(tmp_path):
    path = write_config(tmp_path, "X = 1 / 0\n")
    result = run_cfc(["doctor"], cwd=tmp_path, extra_env=config_env(path))
    assert "Traceback" not in result.stdout
    assert "Traceback" not in result.stderr


# --- next_step / not-checked: no cure duplication, subordinate rendering ----

def test_doctor_no_config_shows_one_cure_and_five_not_checked_rows(tmp_path):
    """D-2.0-07 end to end: a missing config produces exactly one error
    (configuration) with the copy-and-fill next step, five `not checked`
    dependent rows with no next step of their own, and exit 1.
    """
    missing_path = tmp_path / "does_not_exist.py"
    result = run_cfc(["doctor"], cwd=tmp_path, extra_env=config_env(missing_path))
    assert result.returncode == 1
    assert result.stdout.count("error") == 1
    assert result.stdout.count("not checked") == 5
    assert result.stdout.count("config.example.py") == 1


def test_doctor_next_step_renders_directly_below_its_row(tmp_path):
    path = write_config(
        tmp_path, "API_BASE = 'https://provider.invalid/v1'\nMODEL = 'm'\n",
    )
    result = run_cfc(["doctor"], cwd=tmp_path, extra_env=config_env(path))
    lines = result.stdout.splitlines()
    row_index = next(i for i, line in enumerate(lines) if line.strip().startswith("chat provider"))
    assert "API_KEY" in lines[row_index + 1]
    assert lines[row_index + 1].startswith("      ")


def test_doctor_broken_existing_config_is_never_told_to_copy_the_example_over_it(tmp_path):
    """B-2.0-18 end to end: the file is present and unloadable, so the
    printed cure must not be the copy-and-fill one, and the file itself is
    still there, byte for byte, after the run.
    """
    body = "API_KEY = 'fixture-key'\nMODEL = (\n"
    path = write_config(tmp_path, body)
    result = run_cfc(["doctor"], cwd=tmp_path, extra_env=config_env(path))
    assert result.returncode == 1
    assert "Copy config.example.py to config.py" not in result.stdout
    assert "config.py" in result.stdout
    assert path.read_text(encoding="utf-8") == body


def test_doctor_optional_vault_error_is_visible_but_does_not_block_zero_exit(tmp_path):
    """B-2.0-11 plus D-2.0-07 together: a missing configured vault root is
    a real, visible error row with guidance, but it is optional — an
    otherwise-ready required bootstrap still exits 0.
    """
    missing_vault = tmp_path / "vault_never_created"
    path = write_config(tmp_path, VALID_BODY + f"VAULT_ROOT = {str(missing_vault)!r}\n")
    result = run_cfc(["doctor"], cwd=tmp_path, extra_env=config_env(path))
    assert result.returncode == 0
    assert str(missing_vault) in result.stdout
    assert "VAULT_ROOT" in result.stdout


# --- root-relative discovery: repository cwd vs elsewhere, same config ------

def test_doctor_matches_from_repository_root_and_elsewhere(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    env = config_env(path)
    from_root = run_cfc(["doctor"], cwd=ROOT, extra_env=env)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    from_elsewhere = run_cfc(["doctor"], cwd=elsewhere, extra_env=env)
    assert from_root.returncode == from_elsewhere.returncode
    assert from_root.stdout == from_elsewhere.stdout


# --- import tracing: no flat runtime module ----------------------------------

FLAT_MODULE_NAMES = (
    "agent", "api", "commands", "db", "main", "mainchat", "governor",
    "context", "models", "hub", "embed", "splash", "complete", "notes",
    "pools", "mover", "export", "preflight", "recall", "names", "ui",
    "vault", "runner", "routines", "screens", "tools", "wikigit", "parse",
    "chunk", "backup", "backfill", "search", "search_protocol",
    "search_worker",
)


def test_doctor_imports_no_flat_runtime_module(tmp_path):
    path = write_config(tmp_path, VALID_BODY)
    names = ",".join(repr(n) for n in FLAT_MODULE_NAMES)
    script = tmp_path / "trace_imports.py"
    script.write_text(
        "import sys, os\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        f"os.environ[{_config_loader.CONFIG_PATH_ENV_VAR!r}] = {str(path)!r}\n"
        "from cfc import doctor as _doctor\n"
        "_doctor.run([])\n"
        f"flat = [n for n in ({names},) if n in sys.modules]\n"
        "print('FLAT_IMPORTED:', flat)\n",
        encoding="utf-8",
    )
    result = subprocess.run([sys.executable, str(script)], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FLAT_IMPORTED: []" in result.stdout


# --- filesystem inventories: before/after, nothing protected changes --------

def test_doctor_run_leaves_the_repository_and_legacy_locations_untouched(tmp_path):
    path = write_config(tmp_path, VALID_BODY + "TOOLS_ENABLED = True\n")

    repo_config = ROOT / "config.py"
    repo_config_before = repo_config.read_bytes() if repo_config.exists() else None

    from cfc import settings as cfc_settings
    legacy_db = cfc_settings.LEGACY_DATABASE_PATH
    legacy_before = legacy_db.exists()

    result = run_cfc(["doctor"], cwd=tmp_path, extra_env=config_env(path))
    assert result.returncode in (0, 1)

    repo_config_after = repo_config.read_bytes() if repo_config.exists() else None
    assert repo_config_before == repo_config_after
    assert legacy_db.exists() == legacy_before


def test_doctor_run_repeated_creates_nothing_at_the_configured_targets(tmp_path):
    """Snapshots every location this loop's changes touch — the accepted
    nonexistent 2.0 database target, the accepted-and-now-error-reporting
    missing vault root, the legacy database, and the repository itself —
    before and after two real `doctor` runs. Every inventory must still
    match: `doctor` only ever validates, never creates, and running it
    twice is not different from running it once.
    """
    db_target = tmp_path / "database_not_yet_created" / "chat.db"
    vault_target = tmp_path / "vault_not_yet_created"
    path = write_config(
        tmp_path,
        VALID_BODY
        + f"DATABASE_PATH = {str(db_target)!r}\n"
        + f"VAULT_ROOT = {str(vault_target)!r}\n",
    )

    from cfc import settings as cfc_settings
    legacy_db = cfc_settings.LEGACY_DATABASE_PATH
    legacy_before = legacy_db.exists()
    repo_listing_before = sorted(
        p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
        if ".git" not in p.parts
    )

    env = config_env(path)
    first = run_cfc(["doctor"], cwd=tmp_path, extra_env=env)
    second = run_cfc(["doctor"], cwd=tmp_path, extra_env=env)

    assert first.returncode == second.returncode == 0
    assert first.stdout == second.stdout
    assert not db_target.exists()
    assert not db_target.parent.exists()
    assert not vault_target.exists()
    assert legacy_db.exists() == legacy_before
    repo_listing_after = sorted(
        p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*")
        if ".git" not in p.parts
    )
    assert repo_listing_before == repo_listing_after
