"""settings.py — turns a raw config snapshot into the immutable bootstrap
settings 2.0 actually needs: the provider cfc will talk to, and the 2.0
database target.

Everything here is local, structural validation — URL shape, non-empty
strings, path shape, the protected-target refusal below. Nothing here opens
a socket, opens a database, or creates a directory; "valid" means "usable if
cfc tried", not "reachable right now". Optional settings (vault, embeddings,
file tools) are `diagnostics.py`'s job, not this module's — this module only
raises on the settings 2.0 cannot run without.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from cfc import paths

#: v1.9.1's hardcoded database path (`db.py`'s own `DB_PATH`), named again
#: here rather than imported — importing `db.py` would pull in a flat
#: runtime module, which this package never does. A 2.0 database target
#: resolving to this exact path is refused: the two schemas are not
#: compatible, and 2.0 must never open v1.9.1's database.
LEGACY_DATABASE_PATH = Path.home() / ".cfc" / "chat.db"

#: The 2.0 default, used when `config.py` sets no `DATABASE_PATH` — a
#: sibling of the legacy path, not a replacement for it, so both can exist
#: at once.
DEFAULT_DATABASE_PATH = Path.home() / ".cfc" / "2.0" / "chat.db"

#: The repository root, computed the same way `config_loader.default_config_path`
#: does — this package's own grandparent directory.
REPOSITORY_ROOT = Path(__file__).resolve().parent.parent


class SettingsError(Exception):
    """A required bootstrap setting is missing, the wrong type, or an
    invalid value. `field_name` names which one; `kind` is `"missing"`,
    `"type"`, or `"value"`. `str(exc)` never includes a credential's value.
    """

    def __init__(self, field_name: str, kind: str, detail: str):
        self.field_name = field_name
        self.kind = kind
        self.detail = detail
        super().__init__(f"{field_name}: {detail}")


@dataclass(frozen=True)
class ProviderSettings:
    api_base: str
    api_key: str = field(repr=False)
    model: str


#: The provider fields `build_provider` cannot run without, in the order it
#: validates them — named once here so `diagnostics._provider_row` can name
#: every one absent from a snapshot together, rather than only the first one
#: `build_provider`'s own fail-fast raise would reach (D-2.0-19).
REQUIRED_PROVIDER_FIELD_NAMES: tuple[str, ...] = ("API_BASE", "API_KEY", "MODEL")

#: `TUI_THEME`'s only two accepted values — a startup preference, not an
#: in-memory palette experiment (Concept.md, "cfc owns Ctrl+P").
ACCEPTED_TUI_THEMES: tuple[str, ...] = ("dark", "light")

#: `TUI_THEME`'s value when `config.py` sets none, and the value an invalid
#: setting falls back to rather than blocking ordinary chat.
DEFAULT_TUI_THEME = "dark"


@dataclass(frozen=True)
class ThemeSettings:
    """The resolved `TUI_THEME` value plus, when `config.py` set an
    unrecognised one, the bounded notice `tui.py` shows once at startup
    instead of silently discarding the reader's mistake. `name` is always
    one of `ACCEPTED_TUI_THEMES` — an invalid value never reaches the rest
    of the app as anything but `DEFAULT_TUI_THEME`.
    """
    name: str
    invalid_value_notice: str | None = None


@dataclass(frozen=True)
class BootstrapSettings:
    provider: ProviderSettings
    database_path: Path
    theme: ThemeSettings


def _require_nonempty_str(values, name: str) -> str:
    if name not in values:
        raise SettingsError(name, "missing", "not set in config.py")
    value = values[name]
    if not isinstance(value, str):
        raise SettingsError(name, "type",
                             f"must be a string, got {type(value).__name__}")
    if not value.strip():
        raise SettingsError(name, "value", "is empty")
    return value


def _require_url(values, name: str) -> str:
    value = _require_nonempty_str(values, name)
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise SettingsError(
            name, "value",
            f"{value!r} is not an http(s) URL",
        )
    return value


def build_provider(snapshot) -> ProviderSettings:
    """The required chat provider settings: `API_BASE`, `API_KEY`, `MODEL`.
    `snapshot` is a `config_loader.ConfigSnapshot`. Raises `SettingsError`
    naming the first field that fails.
    """
    base_name, key_name, model_name = REQUIRED_PROVIDER_FIELD_NAMES
    values = snapshot.values
    api_base = _require_url(values, base_name)
    api_key = _require_nonempty_str(values, key_name)
    model = _require_nonempty_str(values, model_name)
    return ProviderSettings(api_base=api_base, api_key=api_key, model=model)


def build_database_path(snapshot) -> Path:
    """The 2.0 database target: `config.py`'s `DATABASE_PATH` if it set one
    and it is a non-empty string, else `DEFAULT_DATABASE_PATH`. Expanded and
    resolved before the protected-target check, so `~` and `..` cannot be
    used to aim at a protected path while looking like something else.
    `snapshot` is a `config_loader.ConfigSnapshot`.

    `DB_PATH` is never read here: that spelling is the legacy flat runtime's
    own field, and this module does not treat it as an alias for
    `DATABASE_PATH` — an unset `DATABASE_PATH` falls back to the 2.0
    default even when `DB_PATH` is set.

    Refused if it resolves to the legacy v1.9.1 database, `config.py`
    itself, or anywhere inside the repository — all three are `"value"`
    errors on the field name `"DATABASE_PATH"`, since a default that fails
    this check would be a bug in cfc, not something the reader configured.
    """
    raw = snapshot.values.get("DATABASE_PATH")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        candidate = DEFAULT_DATABASE_PATH
    elif isinstance(raw, (str, Path)):
        candidate = Path(raw)
    else:
        raise SettingsError("DATABASE_PATH", "type",
                             f"must be a string or path, got {type(raw).__name__}")

    resolved = candidate.expanduser().resolve()

    protected = {
        LEGACY_DATABASE_PATH.expanduser().resolve(): "the legacy v1.9.1 database",
        Path(snapshot.path).expanduser().resolve(): "config.py itself",
    }

    if resolved in protected:
        raise SettingsError("DATABASE_PATH", "value",
                             f"{resolved} is protected: {protected[resolved]}")
    if resolved == REPOSITORY_ROOT or REPOSITORY_ROOT in resolved.parents:
        raise SettingsError("DATABASE_PATH", "value",
                             f"{resolved} is inside the repository, which git tracks "
                             f"and a live database must not live in")

    reason = paths.usable_target_reason(resolved)
    if reason is not None:
        raise SettingsError("DATABASE_PATH", "value", reason)

    return resolved


def build_theme(snapshot) -> ThemeSettings:
    """The optional `TUI_THEME` setting: `config.py`'s value when it is one
    of `ACCEPTED_TUI_THEMES`, else `DEFAULT_TUI_THEME` — absent or invalid
    alike. Never raises: an invalid value is bootstrap-shaped recovery
    guidance, not a reason to refuse ordinary chat (Concept.md's "Ephemeral
    preference" section still requires the value come only from this
    setting, but a wrong one must not block startup the way a missing
    provider field does).
    """
    raw = snapshot.values.get("TUI_THEME")
    if raw is None:
        return ThemeSettings(DEFAULT_TUI_THEME)
    if isinstance(raw, str) and raw in ACCEPTED_TUI_THEMES:
        return ThemeSettings(raw)
    notice = (
        f"TUI_THEME is set to {raw!r}, which cfc does not recognise. "
        f"Accepted values are {' and '.join(ACCEPTED_TUI_THEMES)}. "
        f"Using {DEFAULT_TUI_THEME} until config.py is corrected."
    )
    return ThemeSettings(DEFAULT_TUI_THEME, invalid_value_notice=notice)


def build_settings(snapshot) -> BootstrapSettings:
    """Everything 2.0 cannot boot without, plus the optional `TUI_THEME`
    preference. `snapshot` is a `config_loader.ConfigSnapshot`. Raises
    `SettingsError` naming the first required field that fails; a caller
    that wants every failure at once should call
    `build_provider`/`build_database_path` directly.
    """
    return BootstrapSettings(
        provider=build_provider(snapshot),
        database_path=build_database_path(snapshot),
        theme=build_theme(snapshot),
    )
