"""sitecustomize.py — the entry gate's child-process half of
`entry_gate_bootstrap.install`.

Python's `site` module imports a module named `sitecustomize` automatically
at interpreter start, if one is importable, before running the target
script. This directory only lands on a child's `PYTHONPATH` when
`entry_gate_bootstrap.child_env` built that child's environment, so an
ordinary `python3 tests/test_foo.py` run outside the gate never imports
this file and never touches `config` resolution.

Guarded on the fixture env var rather than assuming presence, so a stray
`PYTHONPATH` entry pointing here without the rest of the gate's environment
does nothing rather than fail.
"""
import os

_fixture = os.environ.get("CFC_ENTRY_GATE_CONFIG_FIXTURE")
if _fixture:
    import entry_gate_bootstrap
    from pathlib import Path

    entry_gate_bootstrap.install(Path(_fixture))
