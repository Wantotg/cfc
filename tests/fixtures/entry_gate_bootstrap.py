"""entry_gate_bootstrap.py — one seam that makes `import config` resolve to
the tracked synthetic fixture, for both halves of the entry gate.

The gate runs in two shapes: natively, inside the `pytest` process that
collects and imports every `tests/test_*.py` module; and as 52 independent
child processes, one per legacy suite (`tests/test_entry_gate.py`). Both
shapes must see the same fixture, and neither may read, rename, write, or
shadow Cas's root `config.py` to get it.

`install()` is the one real mechanism: it loads
`entry_gate_synthetic_config.py` under the module name `config` and plants it
directly in `sys.modules`, so any later `import config` anywhere in the
process — native or child — finds it already cached and never touches
`sys.path` or the filesystem at all. `conftest.py` calls this directly for
the native half. `sitecustomize.py`, in this same directory, calls it for a
child: Python's `site` module imports `sitecustomize` automatically at
interpreter start, before the legacy script itself runs, so this plants
`config` before that script's own `sys.path.insert(0, ROOT)` and `import
config` even execute — those still run, they just find the name already
resolved.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

FIXTURE_PATH = (Path(__file__).resolve().parent
                 / "entry_gate_synthetic_config.py")

# Read by sitecustomize.py in a child process, and set (alongside PYTHONPATH)
# by conftest.py for every subprocess the gate spawns.
ENV_VAR = "CFC_ENTRY_GATE_CONFIG_FIXTURE"


def install(fixture_path: Path = FIXTURE_PATH) -> object:
    """Load `fixture_path` under the module name `config` and cache it in
    `sys.modules`, returning the module. Idempotent: a second call in the
    same process is a no-op that returns the already-installed module,
    since the whole point is that later `import config` calls stop here.
    """
    cached = sys.modules.get("config")
    if cached is not None and getattr(cached, "__file__", None) == str(fixture_path):
        return cached

    spec = importlib.util.spec_from_file_location("config", fixture_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["config"] = module
    spec.loader.exec_module(module)
    return module


def child_env(base_env: dict[str, str] | None = None,
              fixture_path: Path = FIXTURE_PATH) -> dict[str, str]:
    """The environment a child process needs to install the same fixture
    through `sitecustomize.py`: the fixture path, and this directory on
    `PYTHONPATH` so `site` finds `sitecustomize` at interpreter start.
    """
    env = dict(base_env if base_env is not None else os.environ)
    env[ENV_VAR] = str(fixture_path)
    fixtures_dir = str(Path(__file__).resolve().parent)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        fixtures_dir if not existing else f"{fixtures_dir}{os.pathsep}{existing}"
    )
    return env
