#!/usr/bin/env python3
"""
test_golden_fixture.py — the /tools fixture guard (D-11).

    python3 tests/test_golden_fixture.py

`golden.py` used to pin `/tools`' read/write roots to Cas's own configured
values, which made the baseline a property of *his* config.py rather than of
the code — the same class of bug the `config.py.bak` scar names. The fix
points the fixture at a real temp directory outside the checkout; this test
verifies the guard that keeps it there by disabling it, the same habit this
codebase asks of every guard (CODER.md).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

sys.path.insert(0, str(HERE))
import golden

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")
    if not cond and detail:
        print(f"       {str(detail)[:200]}")


def main():
    print("--- the guard refuses the source tree ---")
    try:
        golden.assert_not_repo_or_real_roots(golden.ROOT, "test")
        ok("the repo root itself is refused", False, "did not raise")
    except AssertionError as e:
        ok("the repo root itself is refused", "source tree" in str(e), e)

    try:
        golden.assert_not_repo_or_real_roots(golden.ROOT / "tests", "test")
        ok("a path under the repo is refused", False, "did not raise")
    except AssertionError as e:
        ok("a path under the repo is refused", "source tree" in str(e), e)

    print("\n--- the guard refuses Cas's own configured roots ---")
    import config
    saved_tools = getattr(config, "TOOLS_ROOTS", ())
    saved_write = getattr(config, "WRITE_ROOTS", ())
    real_root = Path("/tmp/not-a-real-config-root-for-this-test")
    config.TOOLS_ROOTS = (real_root,)
    config.WRITE_ROOTS = ()
    try:
        golden.assert_not_repo_or_real_roots(real_root, "test")
        ok("a real configured root is refused", False, "did not raise")
    except AssertionError as e:
        ok("a real configured root is refused", "configured root" in str(e), e)
    finally:
        config.TOOLS_ROOTS, config.WRITE_ROOTS = saved_tools, saved_write

    print("\n--- disabled: a real temp directory outside the repo passes ---")
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="cfc-golden-fixture-test-"))
    try:
        golden.assert_not_repo_or_real_roots(tmp, "test")
        ok("a genuine external temp dir is accepted", True)
    except AssertionError as e:
        ok("a genuine external temp dir is accepted", False, e)
    finally:
        tmp.rmdir()

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED: " + ", ".join(FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
