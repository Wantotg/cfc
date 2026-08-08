"""
test_entry_gate.py — the honest v1.9.1 preservation gate.

`python -m pytest` is meant to be the one complete check: the native pytest
collection plus every retained legacy direct-script suite plus the golden
characterisation check. This module is what makes the legacy scripts and
`tests/golden.py` collect and run as part of that one command, each in its
own child process — the same interface a developer would use running the
script by hand (`python3 tests/test_foo.py`), not a reimplementation of what
it checks.

It owns one frozen list of every legacy path (`LEGACY_SUITE_PATHS`) so that
adding, removing, renaming, or de-guarding a suite is a visible failure here
rather than a silent change to what the gate actually covers.

This module has no `__main__` guard on purpose: it is not itself one of the
legacy scripts it inventories, and the inventory test below would otherwise
have to carve out its own name.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# Frozen, sorted, relative to the repository root. This is the preserved
# v1.9.1 interface: one process per script, run as a developer would run it.
# A script leaving this list, a new one arriving, or one losing its
# `__main__` guard is a change to the entry gate's coverage and must be seen,
# not absorbed — see test_frozen_list_matches_discovered_legacy_scripts.
LEGACY_SUITE_PATHS = [
    "tests/test_agent.py",
    "tests/test_api_stream.py",
    "tests/test_assemble.py",
    "tests/test_attach.py",
    "tests/test_chunk.py",
    "tests/test_complete.py",
    "tests/test_connection.py",
    "tests/test_embed.py",
    "tests/test_empty.py",
    "tests/test_empty_retry.py",
    "tests/test_export.py",
    "tests/test_first_message.py",
    "tests/test_gate.py",
    "tests/test_golden_fixture.py",
    "tests/test_governor.py",
    "tests/test_hub.py",
    "tests/test_litter.py",
    "tests/test_main_identity.py",
    "tests/test_mainchat.py",
    "tests/test_mainchat_turns.py",
    "tests/test_memory_states.py",
    "tests/test_model.py",
    "tests/test_model_revert.py",
    "tests/test_model_tools_notice.py",
    "tests/test_models.py",
    "tests/test_mover.py",
    "tests/test_notes.py",
    "tests/test_parse.py",
    "tests/test_paths.py",
    "tests/test_pools.py",
    "tests/test_preflight.py",
    "tests/test_private.py",
    "tests/test_process_model.py",
    "tests/test_recall.py",
    "tests/test_resolve.py",
    "tests/test_routines.py",
    "tests/test_schedule.py",
    "tests/test_schema.py",
    "tests/test_screens.py",
    "tests/test_search_protocol.py",
    "tests/test_search_worker.py",
    "tests/test_splash.py",
    "tests/test_system_injections.py",
    "tests/test_titles.py",
    "tests/test_tools.py",
    "tests/test_turn_paths.py",
    "tests/test_turn_repair.py",
    "tests/test_ui.py",
    "tests/test_vault.py",
    "tests/test_websearch.py",
    "tests/test_wikigit.py",
    "tests/test_wire.py",
]

assert LEGACY_SUITE_PATHS == sorted(LEGACY_SUITE_PATHS)

# Generous on purpose: this bounds a hang, not a slow-but-honest suite. Every
# legacy suite runs in well under a second standalone as of this loop.
LEGACY_SUITE_TIMEOUT_SECONDS = 120
GOLDEN_TIMEOUT_SECONDS = 60


@dataclass
class ChildResult:
    path: str
    cmd: list[str]
    timeout: float
    returncode: int | None
    timed_out: bool
    stdout: str
    stderr: str


def run_child(cmd: list[str], timeout: float, path: str | None = None) -> ChildResult:
    """Run `cmd` as its own process from the repository root, the way a
    developer would run a legacy script by hand. No shell, no guessed
    entry-point callable: the executable script is the preserved interface.
    """
    display_path = path if path is not None else cmd[-1]
    try:
        proc = subprocess.run(
            cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout,
        )
        return ChildResult(
            path=display_path, cmd=cmd, timeout=timeout,
            returncode=proc.returncode, timed_out=False,
            stdout=proc.stdout, stderr=proc.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return ChildResult(
            path=display_path, cmd=cmd, timeout=timeout,
            returncode=None, timed_out=True,
            stdout=exc.stdout or "", stderr=exc.stderr or "",
        )


def failure_reason(result: ChildResult) -> str | None:
    """None if the child succeeded. Otherwise a diagnostic naming the path,
    the command, the exit state, and the captured output — the detail
    pytest's own failure needs, since the child's own stdout/stderr is
    otherwise thrown away with the process.
    """
    if result.timed_out:
        state = f"timed out after {result.timeout}s"
    elif result.returncode != 0:
        state = f"exit {result.returncode}"
    else:
        return None
    return (
        f"{state}: {result.path}\n"
        f"command: {' '.join(result.cmd)}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )


# --- inventory: the frozen list is the actual list -------------------------

def test_frozen_list_matches_discovered_legacy_scripts():
    """A legacy suite is any tests/test_*.py with a __main__ guard, other
    than this module. An addition, removal, rename, or a script losing its
    guard must fail here rather than silently shrink or grow what
    `python -m pytest` actually preserves.
    """
    discovered = sorted(
        p.relative_to(ROOT).as_posix()
        for p in HERE.glob("test_*.py")
        if p.name != Path(__file__).name
        and "__main__" in p.read_text(encoding="utf-8")
    )
    assert discovered == LEGACY_SUITE_PATHS
    assert len(LEGACY_SUITE_PATHS) == 52


# --- one case per legacy suite ----------------------------------------------

@pytest.mark.parametrize(
    "rel_path", LEGACY_SUITE_PATHS,
    ids=[p.removeprefix("tests/") for p in LEGACY_SUITE_PATHS],
)
def test_legacy_suite(rel_path):
    cmd = [sys.executable, str(ROOT / rel_path)]
    result = run_child(cmd, LEGACY_SUITE_TIMEOUT_SECONDS, path=rel_path)
    reason = failure_reason(result)
    if reason is not None:
        pytest.fail(reason)


# --- the golden characterisation check --------------------------------------

def test_golden_check():
    """Explicitly `check`, never the bare-argv default — the default gate
    must never invoke `record`, which overwrites the baseline instead of
    comparing against it.
    """
    golden_path = "tests/golden.py"
    cmd = [sys.executable, str(ROOT / golden_path), "check"]
    result = run_child(cmd, GOLDEN_TIMEOUT_SECONDS, path=golden_path)
    reason = failure_reason(result)
    if reason is not None:
        pytest.fail(reason)


# --- the gate's own diagnostics, proven without touching a legacy suite ----

def test_diagnostics_name_a_failing_exit(tmp_path):
    script = tmp_path / "child_fails.py"
    script.write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
    cmd = [sys.executable, str(script)]

    result = run_child(cmd, LEGACY_SUITE_TIMEOUT_SECONDS)
    assert result.timed_out is False
    assert result.returncode == 7

    reason = failure_reason(result)
    assert reason is not None
    assert str(script) in reason
    assert " ".join(cmd) in reason
    assert "exit 7" in reason


def test_diagnostics_name_a_timeout(tmp_path):
    script = tmp_path / "child_hangs.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    cmd = [sys.executable, str(script)]
    short_timeout = 0.2

    result = run_child(cmd, short_timeout)
    assert result.timed_out is True
    assert result.returncode is None

    reason = failure_reason(result)
    assert reason is not None
    assert str(script) in reason
    assert " ".join(cmd) in reason
    assert "timed out" in reason
    assert str(short_timeout) in reason
