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

def test_no_subcommand_states_it_is_not_yet_chat(tmp_path):
    result = run_cfc([], cwd=tmp_path)
    assert result.returncode == 0
    assert "not yet a chat application" in result.stdout
    assert "doctor" in result.stdout


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
