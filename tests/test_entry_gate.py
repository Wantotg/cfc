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

import ast
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

import entry_gate_bootstrap

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

    The environment is inherited, deliberately: the repository-root
    `conftest.py` pins `COLUMNS`/`LINES` before pytest imports anything, and
    inheritance is what carries that pin into every child here. Without it,
    these suites render at the width of whichever terminal invoked
    `python -m pytest` and fail on wrapped output. See `conftest.py`.
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


# --- discovery: recognising the guard structurally, not textually ----------

# D-2.0-05: a line-anchored regex still matches guard-shaped text inside a
# triple-quoted string, since triple-quoted content still "starts a line" as
# far as a regex is concerned. `ast.parse` cannot produce an `ast.If` from
# string contents, a comment, or an assertion — only a real statement has
# this shape — so recognition here is structural: walk every `ast.If` in the
# module and check whether its test compares `__name__` to the literal
# `"__main__"`, either order. Deliberately narrow — this is not a parser for
# every syntactically valid entry point, only the one spelling the legacy
# suites use.
def has_main_guard(text: str) -> bool:
    """True only when `text` parses as Python and contains a real
    `if __name__ == "__main__":` statement — not a comment, docstring,
    assertion, string literal, or other prose mention of `__main__`, and not
    text that fails to parse at all.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    return any(
        _is_main_guard_test(node.test)
        for node in ast.walk(tree)
        if isinstance(node, ast.If)
    )


def _is_main_guard_test(test: ast.expr) -> bool:
    if not isinstance(test, ast.Compare):
        return False
    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False
    if len(test.comparators) != 1:
        return False
    left, right = test.left, test.comparators[0]
    return (
        (_is_dunder_name(left) and _is_main_string(right))
        or (_is_dunder_name(right) and _is_main_string(left))
    )


def _is_dunder_name(node: ast.expr) -> bool:
    return isinstance(node, ast.Name) and node.id == "__name__"


def _is_main_string(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value == "__main__"


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
        and has_main_guard(p.read_text(encoding="utf-8"))
    )
    assert discovered == LEGACY_SUITE_PATHS
    assert len(LEGACY_SUITE_PATHS) == 52


# --- provenance: the loaded config is the fixture, not Cas's root file -----
#
# D-2.0-04. `conftest.py` installs `entry_gate_bootstrap`'s synthetic
# `config` before any test module is collected, for the native process; the
# same module's `sitecustomize.py` half does it for every child. Neither
# reads, renames, writes, or shadows the root `config.py` — the mechanism
# plants an answer in `sys.modules` before anything goes looking, so what
# happens to sit at the repository root is irrelevant. These three tests
# prove that from three different angles rather than asserting it once.

def test_native_process_config_provenance_is_the_fixture():
    """The pytest process itself — the one collecting this very module —
    must resolve `import config` to the synthetic fixture.
    """
    import config
    resolved = Path(config.__file__).resolve()
    assert resolved == entry_gate_bootstrap.FIXTURE_PATH.resolve()
    assert resolved != (ROOT / "config.py").resolve()


def test_representative_child_process_config_provenance_is_the_fixture(tmp_path):
    """A representative child process — inserting the repository root onto
    `sys.path` and importing `config`, exactly as every legacy suite does —
    must resolve to the same fixture. The child reports what it actually
    imported rather than this test assuming the mechanism worked.
    """
    script = tmp_path / "report_config_provenance.py"
    script.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "import config\n"
        "print(config.__file__)\n",
        encoding="utf-8",
    )
    cmd = [sys.executable, str(script)]
    result = run_child(cmd, LEGACY_SUITE_TIMEOUT_SECONDS)
    reason = failure_reason(result)
    assert reason is None, reason
    reported = Path(result.stdout.strip()).resolve()
    assert reported == entry_gate_bootstrap.FIXTURE_PATH.resolve()
    assert reported != (ROOT / "config.py").resolve()


def test_child_process_config_resolves_without_repository_root_on_path(tmp_path):
    """D-2.0-04's actual failure mode without touching the real file: a
    child that never adds the repository root to `sys.path` at all, so
    Cas's `config.py` — present or absent — is unreachable by construction.
    `import config` must still succeed, because a missing personal
    `config.py` cannot be the reason the gate fails.
    """
    script = tmp_path / "report_config_without_root.py"
    script.write_text(
        "import config\n"
        "print(config.__file__)\n",
        encoding="utf-8",
    )
    cmd = [sys.executable, str(script)]
    result = run_child(cmd, LEGACY_SUITE_TIMEOUT_SECONDS)
    reason = failure_reason(result)
    assert reason is None, reason
    reported = Path(result.stdout.strip()).resolve()
    assert reported == entry_gate_bootstrap.FIXTURE_PATH.resolve()


# --- proof: prose mentioning __main__ is not a guard ------------------------

def test_discovery_seam_rejects_prose_only_dunder_main(tmp_path):
    """A temporary candidate whose only `__main__` text is prose — a
    docstring, a comment, an assertion — must not qualify as a legacy suite.
    """
    candidate = tmp_path / "test_prose_only.py"
    candidate.write_text(
        '"""This module talks about __main__ but never guards on it."""\n'
        "\n"
        "# if __name__ == '__main__' used to be here; removed intentionally\n"
        "\n"
        "def test_something():\n"
        "    assert '__main__' in repr(__name__) or True\n",
        encoding="utf-8",
    )
    assert has_main_guard(candidate.read_text(encoding="utf-8")) is False


def test_discovery_seam_accepts_conventional_guard(tmp_path):
    """A temporary candidate with a real conventional guard must qualify."""
    candidate = tmp_path / "test_real_guard.py"
    candidate.write_text(
        "def main():\n"
        "    pass\n"
        "\n"
        "\n"
        "if __name__ == '__main__':\n"
        "    main()\n",
        encoding="utf-8",
    )
    assert has_main_guard(candidate.read_text(encoding="utf-8")) is True


@pytest.mark.parametrize(
    "line",
    [
        'if __name__ == "__main__":',
        "if __name__ == '__main__':",
        "if __name__=='__main__':",
        "if __name__   ==   '__main__' :",
    ],
    ids=["double-quotes", "single-quotes", "no-spacing", "wide-spacing"],
)
def test_guard_formatting_boundary_is_accepted_at_top_level(line):
    """The accepted formatting boundary at module top level, unindented —
    the shape every retained legacy suite actually uses: spacing around `==`
    and either quote style still qualify as the conventional guard.
    """
    assert has_main_guard(f"{line}\n    pass\n") is True


@pytest.mark.parametrize("indent", ["    ", "\t"],
                          ids=["indented-spaces", "indented-tab"])
def test_guard_formatting_boundary_is_accepted_when_nested(indent):
    """The guard still qualifies nested inside a real block — the ast walk
    is not limited to the module's top level. Standalone indentation with no
    enclosing block is not valid Python at all (`ast.parse` would raise), so
    this nests the guard inside one rather than asserting on syntax that
    could never occur in a real file.
    """
    source = f"if True:\n{indent}if __name__ == '__main__':\n{indent}    pass\n"
    assert has_main_guard(source) is True


def test_discovery_seam_rejects_guard_shaped_triple_quoted_string():
    """D-2.0-05. The old line-anchored regex matched this: a guard-shaped
    line inside a triple-quoted string still "starts a line". `ast.parse`
    cannot produce an `ast.If` from string contents, so a candidate whose
    only guard-shaped text is fixture data inside a string literal must not
    qualify.
    """
    text = (
        'SRC = """\n'
        'if __name__ == "__main__":\n'
        '    main()\n'
        '"""\n'
    )
    assert has_main_guard(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "# if __name__ == '__main__':\n",
        "    # if __name__ == '__main__':\n",
        '"""if __name__ == "__main__":  is the usual guard spelling."""\n',
        "print('if __name__ == \"__main__\":')\n",
        "x = \"__main__\"\n",
        "if __name__ == '__main__'\n",  # missing the required colon
    ],
    ids=[
        "line-comment",
        "indented-comment",
        "docstring-mention",
        "string-literal-in-call",
        "bare-name-assignment",
        "missing-colon",
    ],
)
def test_prose_and_incomplete_mentions_are_rejected(text):
    """Neither a comment, a docstring, a string literal, a bare mention of
    the name, nor a guard missing its final colon counts as the real thing.
    """
    assert has_main_guard(text) is False


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
