"""config_loader.py — executes the trusted repository-root `config.py`
exactly once per command invocation and hands back a raw, immutable
snapshot of its top-level names.

**Trusted-local-Python boundary.** `config.py` is a plain Python file this
loader `exec`s, the same way the v1.9.1 launcher already does via
`import config`. Anyone who can edit that file can run arbitrary code as
this user — this loader does not add or remove that trust, it only stops
the file from being re-run a second time downstream: everything after this
module receives the snapshot this produced, never imports `config` again.

This module never imports a flat v1.9.1 runtime module, opens a database,
creates a directory, or touches a configured path — it reads one file and
returns what it found.
"""
from __future__ import annotations

import os
import types
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_FILENAME = "config.py"

#: Overrides root-relative discovery when set — the one escape hatch from
#: "always the repository root", used to point a command or a test at a
#: different trusted file without touching the real one. Unset in ordinary
#: use; `resolve_config_path` is where this is read.
CONFIG_PATH_ENV_VAR = "CFC_CONFIG_PATH"


@dataclass(frozen=True)
class ConfigSnapshot:
    """The result of one `load_snapshot` call: `values`, the config file's
    immutable top-level names, and `path`, the file that produced them.
    Carrying `path` alongside `values` is what lets `settings.py` refuse a
    database target that resolves back to this exact file without either
    module re-deriving or re-reading it.
    """

    values: types.MappingProxyType
    path: Path


class ConfigLoadError(Exception):
    """Raised for a missing file, an unreadable one, a syntax error, an
    import that failed inside it, or any other error the file's own
    top-level code raised while running.

    `kind` distinguishes those cases for a caller that wants to react
    differently (`"missing"`, `"unreadable"`, `"syntax"`, `"import"`,
    `"exec"`). `str(exc)` names the path and the underlying error's own
    message — never the file's contents, so it stays safe to print even
    when the file holds a credential.
    """

    def __init__(self, kind: str, path: Path, detail: str):
        self.kind = kind
        self.path = path
        self.detail = detail
        super().__init__(f"{path}: {detail}")


def default_config_path() -> Path:
    """The repository-root `config.py`, found relative to this package's
    own location rather than the working directory — `cfc/config_loader.py`
    sits directly under the repository root, so its own parent is that root
    regardless of where the command was actually run from.
    """
    return Path(__file__).resolve().parent.parent / DEFAULT_CONFIG_FILENAME


def resolve_config_path() -> Path:
    """`CONFIG_PATH_ENV_VAR` if set, else `default_config_path()`. The
    single seam every caller that does not pass an explicit path goes
    through — `load_snapshot(None)` calls this, so it is also what
    `python -m cfc doctor` resolves without any command-line flag of its
    own.
    """
    override = os.environ.get(CONFIG_PATH_ENV_VAR)
    if override:
        return Path(override)
    return default_config_path()


def load_snapshot(path: Path | None = None) -> ConfigSnapshot:
    """Execute the trusted config file once and return its top-level public
    names as an immutable mapping — something a reader can index, not a
    module a second `import config` could return a different copy of.
    Nested lists/dicts/sets are normalised to immutable equivalents (see
    `_freeze`) so nothing downstream can mutate a shared structure.

    Raises `ConfigLoadError` for a missing file, an unreadable one, a
    syntax error, a failed import inside it, or any other exception its
    own top-level code raised.
    """
    config_path = path if path is not None else resolve_config_path()

    if not config_path.exists():
        raise ConfigLoadError("missing", config_path,
                               "no configuration file at this path")
    if not config_path.is_file():
        raise ConfigLoadError("missing", config_path,
                               "exists but is not a file")

    try:
        source = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigLoadError("unreadable", config_path, str(exc)) from exc

    try:
        code = compile(source, str(config_path), "exec")
    except SyntaxError as exc:
        raise ConfigLoadError("syntax", config_path, str(exc)) from exc

    namespace: dict = {"__file__": str(config_path), "__name__": "config"}
    try:
        exec(code, namespace)  # noqa: S102 — the trusted-config boundary itself
    except ImportError as exc:
        raise ConfigLoadError("import", config_path, str(exc)) from exc
    except Exception as exc:
        raise ConfigLoadError(
            "exec", config_path,
            f"raised {type(exc).__name__} while loading: {exc}",
        ) from exc

    public = {k: v for k, v in namespace.items() if not k.startswith("__")}
    return ConfigSnapshot(values=_freeze(public), path=config_path)


def _freeze(value):
    """Recursively replace a mutable collection with an immutable
    equivalent: dict -> MappingProxyType, list/set/frozenset -> tuple.
    Anything else (str, int, bool, Path, None, a dataclass instance
    `config.py` built itself, ...) is returned as-is — freezing stops at
    the collections this loader itself introduces structure for.
    """
    if isinstance(value, dict):
        return types.MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, (list, tuple, set, frozenset)):
        return tuple(_freeze(v) for v in value)
    return value
