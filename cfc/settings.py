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
    #: Main's one fixed profile directory — not a member of
    #: `VAULT_CATEGORY_FIELD_NAMES`: that tuple is the vault-owned sources a
    #: `ContextSelection` can *pick from*, and Main's profile is never picked
    #: from — it names one fixed directory with a fixed file list.
    main_chat: VaultCategorySettings = field(default_factory=VaultCategorySettings)


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
    `USER_PREFERENCES_DIR`/`PERSONAS_DIR`/`TRAITS_DIR`/`FIRST_MESSAGES_DIR`/
    `MAIN_CHAT_DIR`, each independently usable or not. Never raises.
    `snapshot` is a `config_loader.ConfigSnapshot`.

    `USER_PREFERENCES_DIR` is a 2.0-only setting — deliberately not v1.9.1's
    `PROMPTS_DIR` (Concept.md: cfc 2.0 calls this material User Preferences
    even where it points at the same directory v1.9.1 calls a prompt pool).
    `PERSONAS_DIR`, `TRAITS_DIR`, and `FIRST_MESSAGES_DIR` are the same
    field names v1.9.1 already reads; 2.0 imposes its own, stricter
    containment-inside-`VAULT_ROOT` rule on them rather than reusing
    v1.9.1's own validation.

    `MAIN_CHAT_DIR` is a 2.0-only setting: it names Main's one fixed
    profile directory (`system prompt.md`, `persona.md`, `first message.md`
    inside it — `cfc.context`'s job to read, never this module's). It reuses
    `_vault_category`'s shape/containment rule rather than a bespoke one:
    Main's profile is exactly as much "a vault category directory" as the
    other four, just with a fixed, non-selectable file list.
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
        main_chat=_vault_category(values, "MAIN_CHAT_DIR", root),
    )


#: `USER_DISPLAY_NAME`/`AI_DISPLAY_NAME`'s effective defaults when
#: `config.py` sets neither — the same values the flat `names.py` module
#: already ships (`DEFAULT_USER`/`DEFAULT_AI`), named again here rather than
#: imported, since this module never imports the flat runtime.
DEFAULT_USER_DISPLAY_NAME = "You"
DEFAULT_AI_DISPLAY_NAME = "Cooking for Cats"

#: Not measured, chosen: long enough for a real name or short title, short
#: enough that a pasted paragraph is obviously not one and reads as the
#: config error it is rather than being sent to a model as someone's name.
#: Mirrors `names.MAX_LEN`.
DISPLAY_NAME_MAX_LEN = 40

#: The two exact, case-sensitive tokens `cfc.context` substitutes in a
#: template source's decoded body — named once here so `diagnostics.py` and
#: any caller reporting on this setting quote the same literal spelling
#: `cfc.context.apply_display_names` actually matches.
USER_DISPLAY_TOKEN = "{{user}}"
AI_DISPLAY_TOKEN = "{{AI}}"


@dataclass(frozen=True)
class DisplayNameSettings:
    """The resolved `USER_DISPLAY_NAME`/`AI_DISPLAY_NAME` settings —
    `cfc.context`'s one input for substituting `{{user}}`/`{{AI}}` in a
    template source's decoded body.

    `user_name`/`ai_name` are the effective default when the setting is
    unset, the configured value when it validates, or `None` when it is set
    but invalid — `None` means `cfc.context.apply_display_names` leaves that
    token literal rather than guessing, matching the flat `names.py`
    module's own "an invalid value leaves the token untouched" rule.
    `user_invalid_notice`/`ai_invalid_notice` are set only in that last
    case, bounded and safe to show directly (never the rejected value's
    content beyond the length `problem` already reports).
    """
    user_name: str | None
    ai_name: str | None
    user_invalid_notice: str | None = None
    ai_invalid_notice: str | None = None


def _display_name_problem(value, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return f"{field_name} must be a string, got {type(value).__name__}"
    if "\n" in value or "\r" in value:
        return f"{field_name} must be a single line"
    if not value.strip():
        return f"{field_name} must not be blank"
    if len(value) > DISPLAY_NAME_MAX_LEN:
        return f"{field_name} is {len(value)} characters, over the {DISPLAY_NAME_MAX_LEN} limit"
    return None


def _resolve_one_display_name(raw, field_name: str, token: str, default: str):
    problem = _display_name_problem(raw, field_name)
    if problem is not None:
        notice = f"{problem}; {token} is left literal until config.py is corrected."
        return None, notice
    return (raw if raw is not None else default), None


def build_display_name_settings(snapshot) -> DisplayNameSettings:
    """The optional `USER_DISPLAY_NAME`/`AI_DISPLAY_NAME` settings, each
    resolved independently — never raises: an invalid one leaves its own
    token literal without blocking the other name or ordinary chat, the
    same discipline every other optional builder in this module follows.
    """
    values = snapshot.values
    user_name, user_notice = _resolve_one_display_name(
        values.get("USER_DISPLAY_NAME"), "USER_DISPLAY_NAME",
        USER_DISPLAY_TOKEN, DEFAULT_USER_DISPLAY_NAME,
    )
    ai_name, ai_notice = _resolve_one_display_name(
        values.get("AI_DISPLAY_NAME"), "AI_DISPLAY_NAME",
        AI_DISPLAY_TOKEN, DEFAULT_AI_DISPLAY_NAME,
    )
    return DisplayNameSettings(user_name, ai_name, user_notice, ai_notice)


@dataclass(frozen=True)
class ExportSettings:
    """`CHAT_EXPORT_DIR`'s validated shape: a resolved `Path` when it is
    configured as a non-empty string, or an `unavailable_reason` when it is
    not. Deliberately independent of `VaultSettings` and `VAULT_ROOT`
    (Concept.md: "It is independent of `VAULT_ROOT`: an export is a
    user-requested readable copy, not authority to edit a context source") —
    this field is never checked for containment inside the vault, and never
    falls back to `VAULT_ROOT` when unset.

    Same shape-only discipline as `VaultCategorySettings`: this never checks
    whether the directory actually exists, is writable, or is even a
    directory at all. `cfc.chat_export.validate_destination` is where an
    export actually confirms the target is usable, at the moment export is
    requested — a directory created after startup, or removed since, must
    still be judged by its state right now, not a startup snapshot.
    """
    path: Path | None = None
    unavailable_reason: str | None = None


def build_export_settings(snapshot) -> ExportSettings:
    """The optional `CHAT_EXPORT_DIR` setting. Never raises: an unset,
    blank, placeholder, or wrong-typed value leaves export unavailable
    without blocking ordinary chat, the same discipline `_vault_category`
    already applies to the vault categories.
    """
    raw = snapshot.values.get("CHAT_EXPORT_DIR")
    if raw is None or (isinstance(raw, str) and not raw.strip()) or raw == "PLACEHOLDER":
        return ExportSettings(unavailable_reason="CHAT_EXPORT_DIR is not set")
    if not isinstance(raw, str):
        return ExportSettings(
            unavailable_reason=f"CHAT_EXPORT_DIR must be a string, got {type(raw).__name__}"
        )
    return ExportSettings(path=Path(raw).expanduser().resolve())


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
    chat_export: ExportSettings
    display_names: DisplayNameSettings


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
        chat_export=build_export_settings(snapshot),
        display_names=build_display_name_settings(snapshot),
    )
