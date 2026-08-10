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

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
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


#: The four 2.0 vault category settings, in the order `build_vault_settings`
#: validates them — the vault-owned sources a `ContextPlan` can select from.
#: `VAULT_ROOT` itself is not in this tuple: it is the containment boundary
#: every one of these must resolve inside, not a category of its own.
VAULT_CATEGORY_FIELD_NAMES: tuple[str, ...] = (
    "USER_PREFERENCES_DIR", "PERSONAS_DIR", "TRAITS_DIR", "FIRST_MESSAGES_DIR",
)


@dataclass(frozen=True)
class VaultCategorySettings:
    """One configured vault category directory, or the reason it is not
    usable. `path` is set only when the category is genuinely usable:
    `VAULT_ROOT` and this field are both set, this field is a non-empty
    string, and it resolves inside `VAULT_ROOT`. Never raises — an unusable
    category leaves the optional selector visibly unavailable rather than
    blocking ordinary chat (Concept.md: "A missing vault leaves ordinary
    unpersonalised chat usable").

    This is shape validation only, same discipline as the rest of this
    module: it never checks whether `path` actually exists on disk. Whether
    a configured directory is real is `cfc.context`'s job, at the moment a
    selection is actually read.
    """
    path: Path | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class VaultSettings:
    root: Path | None
    user_preferences: VaultCategorySettings
    personas: VaultCategorySettings
    traits: VaultCategorySettings
    first_messages: VaultCategorySettings


def _vault_category(
    values, field_name: str, root: Path | None,
) -> VaultCategorySettings:
    raw = values.get(field_name)
    if raw is None or (isinstance(raw, str) and not raw.strip()) or raw == "PLACEHOLDER":
        return VaultCategorySettings(unavailable_reason=f"{field_name} is not set")
    if not isinstance(raw, str):
        return VaultCategorySettings(
            unavailable_reason=f"{field_name} must be a string, got {type(raw).__name__}"
        )
    if root is None:
        return VaultCategorySettings(
            unavailable_reason=f"VAULT_ROOT must be set for {field_name} to be usable"
        )
    resolved = Path(raw).expanduser().resolve()
    if resolved != root and root not in resolved.parents:
        return VaultCategorySettings(
            unavailable_reason=f"{field_name} ({resolved}) does not resolve inside VAULT_ROOT ({root})"
        )
    return VaultCategorySettings(path=resolved)


def build_vault_settings(snapshot) -> VaultSettings:
    """The optional 2.0 vault category settings: `VAULT_ROOT` plus
    `USER_PREFERENCES_DIR`/`PERSONAS_DIR`/`TRAITS_DIR`/`FIRST_MESSAGES_DIR`,
    each independently usable or not. Never raises. `snapshot` is a
    `config_loader.ConfigSnapshot`.

    `USER_PREFERENCES_DIR` is a 2.0-only setting — deliberately not v1.9.1's
    `PROMPTS_DIR` (Concept.md: cfc 2.0 calls this material User Preferences
    even where it points at the same directory v1.9.1 calls a prompt pool).
    `PERSONAS_DIR`, `TRAITS_DIR`, and `FIRST_MESSAGES_DIR` are the same
    field names v1.9.1 already reads; 2.0 imposes its own, stricter
    containment-inside-`VAULT_ROOT` rule on them rather than reusing
    v1.9.1's own validation.
    """
    values = snapshot.values
    raw_root = values.get("VAULT_ROOT")
    root: Path | None = None
    if isinstance(raw_root, str) and raw_root.strip() and raw_root != "PLACEHOLDER":
        root = Path(raw_root).expanduser().resolve()

    return VaultSettings(
        root=root,
        user_preferences=_vault_category(values, "USER_PREFERENCES_DIR", root),
        personas=_vault_category(values, "PERSONAS_DIR", root),
        traits=_vault_category(values, "TRAITS_DIR", root),
        first_messages=_vault_category(values, "FIRST_MESSAGES_DIR", root),
    )


@dataclass(frozen=True)
class ModelCatalogueEntry:
    """One `MODELS` record's fields the 2.0 picker consumes: an exact
    non-blank provider id, whether it is chat-selectable, and an optional
    positive context limit. Deliberately narrow — this loop does not read
    `tools`, `routine`, `routine_default`, or `preset_params`; those stay
    the flat `models.py` boundary's own concern.
    """
    id: str
    selectable: bool
    context_limit: int | None = None


@dataclass(frozen=True)
class ModelCatalogue:
    """The validated, ordered `MODELS` catalogue, or an empty one with a
    bounded `unavailable_reason` when `config.py`'s `MODELS` is malformed.
    `MODEL` (`ProviderSettings.model`) is never a member requirement of
    this: it remains usable even when absent here (Concept.md: "The
    required default is always a usable choice even when it is absent from
    the optional catalogue").
    """
    entries: tuple[ModelCatalogueEntry, ...] = field(default_factory=tuple)
    unavailable_reason: str | None = None

    def selectable_entries(self) -> tuple[ModelCatalogueEntry, ...]:
        return tuple(entry for entry in self.entries if entry.selectable)

    def entry_for(self, model_id: str) -> ModelCatalogueEntry | None:
        return next((entry for entry in self.entries if entry.id == model_id), None)


def _malformed_catalogue(detail: str) -> ModelCatalogue:
    return ModelCatalogue(unavailable_reason=(
        f"MODELS is configured but not usable as a 2.0 model catalogue: "
        f"{detail}; the picker is unavailable, but MODEL still works"
    ))


def build_model_catalogue(snapshot) -> ModelCatalogue:
    """The 2.0 model picker's validated view of `config.py`'s `MODELS` list
    — the same field the flat `models.py` boundary reads, not a second
    parallel setting, but read and validated independently here rather than
    through that module (`models.py` imports `ui.DISPLAY_NAME`, a flat
    runtime module this package never imports).

    A `MODELS` record's `listed` field (default `True`) is this catalogue's
    "chat-selectable" marker, and its `limit` field is the optional positive
    context limit — the same two fields the legacy picker already reads, so
    an existing `config.py` needs no new field to get a working 2.0
    catalogue. `id` is required and validated fresh regardless.

    Never raises: an unset or empty `MODELS` is an ordinary empty catalogue;
    any other malformed shape returns an empty catalogue carrying one
    bounded `unavailable_reason` instead of blocking ordinary chat.
    """
    raw = snapshot.values.get("MODELS")
    if not raw:
        return ModelCatalogue()
    if not isinstance(raw, tuple):
        return _malformed_catalogue(f"must be a list, got {type(raw).__name__}")

    entries: list[ModelCatalogueEntry] = []
    seen_ids: set[str] = set()
    for index, record in enumerate(raw):
        if not isinstance(record, Mapping):
            return _malformed_catalogue(f"MODELS[{index}] must be a dict, got {type(record).__name__}")
        model_id = record.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            return _malformed_catalogue(f"MODELS[{index}] has no usable 'id'")
        if model_id in seen_ids:
            return _malformed_catalogue(f"MODELS lists {model_id!r} twice")
        seen_ids.add(model_id)

        selectable = record.get("listed", True)
        if not isinstance(selectable, bool):
            return _malformed_catalogue(
                f"MODELS[{model_id!r}].listed must be True/False, got {selectable!r}"
            )

        limit = record.get("limit")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
            return _malformed_catalogue(
                f"MODELS[{model_id!r}].limit must be a positive int or None, got {limit!r}"
            )

        entries.append(ModelCatalogueEntry(id=model_id, selectable=selectable, context_limit=limit))

    return ModelCatalogue(entries=tuple(entries))


@dataclass(frozen=True)
class BootstrapSettings:
    provider: ProviderSettings
    database_path: Path
    theme: ThemeSettings
    vault: VaultSettings
    models: ModelCatalogue


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


class AppearanceSource(Enum):
    """Which precedence step produced an `EffectiveAppearance` — a saved
    cfc override, or the resolved `TUI_THEME` configured default (itself
    `DEFAULT_TUI_THEME` when `TUI_THEME` is unset or invalid; that distinction
    stays on `ThemeSettings.invalid_value_notice`, not duplicated here).
    """
    OVERRIDE = "override"
    CONFIGURED_DEFAULT = "configured_default"


@dataclass(frozen=True)
class EffectiveAppearance:
    """The one resolved `dark`/`light` value an app, doctor, or a palette
    label actually shows, plus which precedence step produced it —
    `resolve_effective_appearance`'s only return shape.
    """
    name: str
    source: AppearanceSource


def resolve_effective_appearance(
    theme: ThemeSettings, override: str | None,
) -> EffectiveAppearance:
    """The one precedence rule every appearance-consuming caller (doctor,
    `tui.build_app`, palette labels, reset notifications) shares rather than
    re-implementing: `override` wins when given; otherwise `theme.name` —
    `build_theme`'s own already-resolved bootstrap value — applies.

    `override` must already be validated to `ACCEPTED_TUI_THEMES` or `None`;
    this function does not re-validate it. `conversation_store`'s own
    stored-value check is where an impossible persisted value is caught, so
    it never reaches this function as anything but `None` or an accepted
    name.
    """
    if override is not None:
        return EffectiveAppearance(override, AppearanceSource.OVERRIDE)
    return EffectiveAppearance(theme.name, AppearanceSource.CONFIGURED_DEFAULT)


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
        vault=build_vault_settings(snapshot),
        models=build_model_catalogue(snapshot),
    )
