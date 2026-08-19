"""diagnostics.py — the fourteen-row inventory `cfc doctor` renders: runtime,
configuration, chat provider, 2.0 database target, vault, embeddings, file
tools, the four Stage 5 vault categories (User Preferences, Personas,
Traits, First Messages), the model catalogue, display names, and appearance.
The first four are required — `required_rows_ok` is an exact allow-list, so
`doctor` exits non-zero unless every one of them is `READY`, not merely
absent of `ERROR`. Every other row is optional: absence is `UNAVAILABLE`,
and neither that nor `NOT_CHECKED` blocks the exit code.

Every check here is local and structural, same as `settings.py`, which this
module calls for most rows, and `cfc.context`, which the four vault-category
rows call for the exact same directory/selectable-file rules the Context
picker uses — so a category doctor calls "ready, empty" and one Context
would show empty are provably the same fact, not two opinions. The
appearance row is the one row that opens anything: a narrow, read-only,
non-blocking peek at the configured 2.0 database target
(`conversation_store.inspect_appearance_override`) to report a saved
palette override when one can be safely read — it never creates a target,
mutates one, or leaves a sidecar.

`Row.detail` is diagnostic evidence — what was checked and what it found.
`Row.next_step`, stored separately, is recovery guidance — what to do about
it — and is only ever set on a row this module actually diagnosed. A `NOT
CHECKED` row (one that depends on an earlier row that failed) carries a
local explanation in `detail` but no `next_step`: the cure lives once, on
the row that owns it, not copied onto everything downstream.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

from cfc import config_loader, conversation_store, entry, settings
from cfc import context as context_mod

REQUIRED_ROW_NAMES = ("runtime", "configuration", "chat provider", "2.0 database target")
OPTIONAL_ROW_NAMES = (
    "vault", "embeddings", "file tools",
    "user preferences", "personas", "traits", "first messages",
    "model catalogue", "display names", "appearance",
)
ROW_ORDER = REQUIRED_ROW_NAMES + OPTIONAL_ROW_NAMES

#: `ContextReadinessState`/`Row.name` pairing for the four Stage 5 vault
#: categories, in `Concept.md`'s own listed order — named once here so
#: `_vault_category_rows` and any test walking "every category" share one
#: source of the row name, the `VaultSettings` attribute to read, and the
#: exact `config.py` field to name in an `ERROR` row's `next_step`.
_VAULT_CATEGORY_ROWS = (
    ("user preferences", "user_preferences", "USER_PREFERENCES_DIR"),
    ("personas", "personas", "PERSONAS_DIR"),
    ("traits", "traits", "TRAITS_DIR"),
    ("first messages", "first_messages", "FIRST_MESSAGES_DIR"),
)

#: `configuration`'s own next step is the one true cure for every row a
#: failed config load leaves NOT_CHECKED — named once here so the cascade
#: below and any test asserting "no duplicate cure" refer to the same text.
#: Only offered when no file is there to lose (see `_config_load_next_step`).
_CONFIG_MISSING_NEXT_STEP = ("Copy config.example.py to config.py, then fill in "
                              "the required settings.")


class State(Enum):
    READY = "ready"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    NOT_CHECKED = "not checked"


@dataclass(frozen=True)
class Row:
    name: str
    state: State
    detail: str = ""
    next_step: str | None = None


def _config_load_next_step(exc: config_loader.ConfigLoadError) -> str:
    """Recovery guidance for a configuration that would not load, chosen by
    whether a file is already sitting at that path (B-2.0-18).

    Copy-and-fill is the cure for exactly one case: nothing is there. A
    `config.py` that exists and failed — a syntax error, a failed import,
    an exception in its own top-level code, an unreadable file — is a file
    holding an API key and every path this machine is configured with, and
    it is gitignored, so replacing it with the example loses material
    nothing can restore. That case gets told to correct the file, and told
    plainly that copying over it is not the route.
    """
    if not exc.path.exists():
        return _CONFIG_MISSING_NEXT_STEP
    return (f"Correct {exc.path.name} — the detail above names the error. "
            f"Do not copy config.example.py over it; that would replace the "
            f"settings already in it.")


def diagnose(config_path: Path | None = None) -> tuple[Row, ...]:
    """The full ordered inventory, `ROW_ORDER`. Never raises: every failure
    this can hit — a bad interpreter, a missing config, an invalid required
    or optional field — becomes a `Row` instead, so a caller renders once
    and reports the exit code from the rows themselves
    (`required_rows_ok`), not from a `try`/`except` around this call.
    """
    rows = [_runtime_row()]

    try:
        snapshot = config_loader.load_snapshot(config_path)
    except config_loader.ConfigLoadError as exc:
        rows.append(Row("configuration", State.ERROR, str(exc),
                         next_step=_config_load_next_step(exc)))
        prerequisite = "configuration did not load; see the configuration row"
        for name in REQUIRED_ROW_NAMES[2:] + OPTIONAL_ROW_NAMES:
            rows.append(Row(name, State.NOT_CHECKED, prerequisite))
        return tuple(rows)

    rows.append(Row("configuration", State.READY,
                     f"loaded from {snapshot.path}"))
    rows.append(_provider_row(snapshot))
    rows.append(_database_row(snapshot))
    rows.append(_vault_row(snapshot))
    rows.append(_embeddings_row(snapshot))
    rows.append(_file_tools_row(snapshot))
    vault_settings = settings.build_vault_settings(snapshot)
    rows.extend(_vault_category_rows(vault_settings))
    rows.append(_model_catalogue_row(snapshot))
    rows.append(_display_names_row(snapshot))
    rows.append(_appearance_row(snapshot))
    return tuple(rows)


def required_rows_ok(rows: tuple[Row, ...]) -> bool:
    """An exact allow-list, not merely "no `ERROR`": every required row
    must be `READY` — what `doctor` bases its exit code on. A required row
    left `NOT_CHECKED` (its prerequisite failed, so it was never actually
    diagnosed) is not readiness either, and must not produce exit zero.
    Optional rows never affect this.
    """
    return all(
        row.state == State.READY
        for row in rows
        if row.name in REQUIRED_ROW_NAMES
    )


def _runtime_row() -> Row:
    problem = entry.check_interpreter()
    if problem is None:
        version = ".".join(str(part) for part in sys.version_info[:3])
        floor = ".".join(str(part) for part in entry.MIN_PYTHON)
        return Row("runtime", State.READY, f"{version} (floor {floor})")
    return Row("runtime", State.ERROR, problem)


def _settings_error_next_step(exc: settings.SettingsError) -> str:
    """Recovery guidance for a `settings.SettingsError`, kept generic and
    redacted on purpose: it names the field to fix, never the value that
    was rejected (`Row.detail`, printed right above, already carries that
    evidence for a value that was safe to show in the first place).
    """
    if exc.kind == "missing":
        return f"Set {exc.field_name} in config.py."
    if exc.kind == "type":
        return f"Set {exc.field_name} to the expected type in config.py."
    return f"Fix {exc.field_name} in config.py — see the detail above."


def _provider_row(snapshot) -> Row:
    """A fresh clone's real surface for learning what to fill in: unlike
    `build_provider`'s own deliberate fail-fast raise on the first missing
    field, this collects every required field absent from the snapshot and
    names them together (D-2.0-19). Once all required names exist, this
    falls through to `build_provider` unchanged, so its ordinary type,
    empty-value, and URL validation still fails one actionable field at a
    time — only the "nothing was even set" case is aggregated.
    """
    values = snapshot.values
    missing = [name for name in settings.REQUIRED_PROVIDER_FIELD_NAMES if name not in values]
    if missing:
        names = ", ".join(missing)
        return Row("chat provider", State.ERROR,
                    f"missing required setting(s): {names}",
                    next_step=f"Set {names} in config.py.")

    try:
        provider = settings.build_provider(snapshot)
    except settings.SettingsError as exc:
        return Row("chat provider", State.ERROR, str(exc),
                    next_step=_settings_error_next_step(exc))
    return Row("chat provider", State.READY,
               f"{provider.model} via {provider.api_base}")


def _database_row(snapshot) -> Row:
    try:
        db_path = settings.build_database_path(snapshot)
    except settings.SettingsError as exc:
        return Row("2.0 database target", State.ERROR, str(exc),
                    next_step=_settings_error_next_step(exc))
    return Row("2.0 database target", State.READY, str(db_path))


def _vault_row(snapshot) -> Row:
    """The vault is `VAULT_ROOT` — the folder of human-readable material
    cfc reads, and the one this row is named after. Deliberately not
    `CHAT_EXPORT_DIR` (nor `VAULT_PATH`, its pre-1.3.1 name): that is where
    v1.9.1 *writes* exported chats, usually a folder inside the vault, and
    reporting it here answered a different question than the row asked.

    Unlike the 2.0 database target, cfc never creates the vault root
    (B-2.0-11): a configured root is `READY` only if it already exists and
    is a directory. A missing directory or a configured file is a visible,
    non-blocking `ERROR` — optional rows are never allowed to block the
    exit code — with guidance that Cas creates or corrects it himself;
    doctor never offers to make it.
    """
    values = snapshot.values
    raw = values.get("VAULT_ROOT")
    if not raw or raw == "PLACEHOLDER":
        return Row("vault", State.UNAVAILABLE, "VAULT_ROOT is not set")

    resolved = Path(raw).expanduser().resolve()
    if resolved.is_dir():
        return Row("vault", State.READY, str(resolved))
    if resolved.exists():
        detail = f"{resolved} exists but is not a directory"
    else:
        detail = f"{resolved} does not exist"
    next_step = (f"Create the directory at {resolved}, or correct "
                 f"VAULT_ROOT in config.py — cfc does not create it.")
    return Row("vault", State.ERROR, detail, next_step=next_step)


def _embeddings_row(snapshot) -> Row:
    values = snapshot.values
    base = values.get("EMBED_BASE") or ""
    model = values.get("EMBED_MODEL") or ""
    key = values.get("EMBED_KEY") or ""

    if not base and not model and not key:
        return Row("embeddings", State.UNAVAILABLE,
                    "EMBED_BASE/EMBED_MODEL/EMBED_KEY are not set")

    if not base:
        return Row("embeddings", State.ERROR, "EMBED_BASE is empty")
    parsed = urlparse(base)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return Row("embeddings", State.ERROR, f"EMBED_BASE {base!r} is not an http(s) URL")
    if not model:
        return Row("embeddings", State.ERROR, "EMBED_MODEL is empty")
    if not key:
        return Row("embeddings", State.ERROR, "EMBED_KEY is empty")

    return Row("embeddings", State.READY, f"{model} via {base}")


def _file_tools_row(snapshot) -> Row:
    """Reports exactly the same truth `cfc.settings.build_file_tool_settings`
    already computed — no second validator. A malformed `TOOLS_*` field is
    `ERROR`; a well-formed but disabled or root-less configuration is
    `UNAVAILABLE`; a usable capability is `READY` naming its root count.
    """
    file_tools = settings.build_file_tool_settings(snapshot)
    if file_tools.usable:
        count = len(file_tools.roots)
        plural = "" if count == 1 else "s"
        return Row("file tools", State.READY, f"{count} configured root{plural}")
    if file_tools.problem is settings.FileToolProblem.MALFORMED:
        return Row("file tools", State.ERROR, file_tools.unavailable_reason,
                    next_step="Correct the TOOLS_* fields in config.py — see the detail above.")
    return Row("file tools", State.UNAVAILABLE, file_tools.unavailable_reason)


# --- Stage 5 vault categories: shared readiness rules with Context --------

def _vault_category_rows(vault: settings.VaultSettings) -> tuple[Row, ...]:
    return tuple(
        _vault_category_row(row_name, field_name, getattr(vault, attr))
        for row_name, attr, field_name in _VAULT_CATEGORY_ROWS
    )


def _vault_category_row(row_name: str, field_name: str, category_settings) -> Row:
    readiness = context_mod.category_readiness(category_settings)
    if readiness.state is context_mod.CategoryReadinessState.UNAVAILABLE:
        return Row(row_name, State.UNAVAILABLE, readiness.reason)
    if readiness.state is context_mod.CategoryReadinessState.ERROR:
        next_step = (f"Create the directory, or correct {field_name} in "
                     f"config.py — cfc does not create it.")
        return Row(row_name, State.ERROR, readiness.reason, next_step=next_step)
    if readiness.count == 0:
        return Row(row_name, State.READY, "ready, empty (0 selectable .md files)")
    plural = "" if readiness.count == 1 else "s"
    return Row(row_name, State.READY, f"ready ({readiness.count} selectable .md file{plural})")


# --- model catalogue: absent/empty is unavailable, malformed is an error --

def _model_catalogue_row(snapshot) -> Row:
    catalogue = settings.build_model_catalogue(snapshot)
    if catalogue.unavailable_reason is not None:
        return Row("model catalogue", State.ERROR, catalogue.unavailable_reason,
                    next_step="Correct MODELS in config.py — see the detail above.")
    selectable = catalogue.selectable_entries()
    if not selectable:
        if not catalogue.entries:
            return Row("model catalogue", State.UNAVAILABLE, "MODELS is not set")
        return Row("model catalogue", State.UNAVAILABLE,
                    f"MODELS lists {len(catalogue.entries)} model(s), none chat-selectable")
    return Row("model catalogue", State.READY, f"{len(selectable)} selectable model(s)")


# --- display names: {{user}}/{{AI}} substitution, always resolvable -------

def _display_names_row(snapshot) -> Row:
    """Always resolvable, never `UNAVAILABLE`: `USER_DISPLAY_NAME` and
    `AI_DISPLAY_NAME` each have a documented default, so there is always an
    effective value to report — `ERROR` names exactly which setting is
    invalid without blocking the other or ordinary chat (B-2.0-71's own
    "an invalid value leaves the token literal", not a reason to refuse).
    """
    resolved = settings.build_display_name_settings(snapshot)
    notices = [n for n in (resolved.user_invalid_notice, resolved.ai_invalid_notice) if n]
    if notices:
        return Row("display names", State.ERROR, "; ".join(notices),
                    next_step="Correct USER_DISPLAY_NAME/AI_DISPLAY_NAME in config.py, "
                              "or remove the invalid one to use its default.")
    return Row("display names", State.READY,
                f"{{{{user}}}} -> {resolved.user_name!r}, {{{{AI}}}} -> {resolved.ai_name!r}")


# --- appearance: the effective dark/light value and its source ------------

def _appearance_row(snapshot) -> Row:
    """Always `READY`: an effective `dark`/`light` value is resolvable
    regardless of whether a saved override can currently be inspected — the
    bootstrap `TUI_THEME` (or its own built-in `dark` fallback) is always
    available (Concept.md's "appearance row always names the effective
    value and its source").

    A `TUI_THEME` cfc does not recognise is that third source, and it is
    the one this row must not quietly flatten into the second (B-2.0-64):
    `build_theme` falls back to `DEFAULT_TUI_THEME` for an unset setting
    and a wrong one alike, so reporting both as "configured default" told
    Cas his rejected value had been honoured. That state is named, and it
    is the only one here carrying a `next_step`.
    """
    theme = settings.build_theme(snapshot)
    next_step = _tui_theme_next_step(theme)
    try:
        db_path = settings.build_database_path(snapshot)
    except settings.SettingsError:
        return Row("appearance", State.READY,
                    f"{theme.name} ({_bootstrap_source(theme)}; see the 2.0 database "
                    f"target row — the database could not be resolved)",
                    next_step=next_step)

    inspection = conversation_store.inspect_appearance_override(db_path)
    if inspection.state is conversation_store.AppearanceInspectionState.READY:
        effective = settings.resolve_effective_appearance(theme, inspection.override)
        source = ("saved override" if effective.source is settings.AppearanceSource.OVERRIDE
                  else _bootstrap_source(theme))
        return Row("appearance", State.READY, f"{effective.name} ({source})",
                    next_step=next_step)

    return Row("appearance", State.READY,
                f"{theme.name} ({_bootstrap_source(theme)}; database not inspected: "
                f"{_appearance_inspection_reason(inspection)})",
                next_step=next_step)


def _bootstrap_source(theme: settings.ThemeSettings) -> str:
    """What produced `theme.name`: `config.py`'s own accepted `TUI_THEME`
    (or its absence, which is the documented default), or cfc's built-in
    fallback after that setting was rejected.
    """
    if theme.invalid_value_notice is None:
        return "configured default"
    return "built-in default; TUI_THEME is not one cfc recognises"


def _tui_theme_next_step(theme: settings.ThemeSettings) -> str | None:
    """The correction route for a rejected `TUI_THEME`, and nothing else —
    it names the field and its two accepted values, never the rejected
    value, matching `_settings_error_next_step`'s own redaction.
    """
    if theme.invalid_value_notice is None:
        return None
    accepted = " or ".join(settings.ACCEPTED_TUI_THEMES)
    return (f"Set TUI_THEME to {accepted} in config.py, or remove it to use "
            f"{settings.DEFAULT_TUI_THEME}.")


def _appearance_inspection_reason(inspection) -> str:
    if inspection.state is conversation_store.AppearanceInspectionState.ABSENT:
        return "no database exists there yet"
    if inspection.state is conversation_store.AppearanceInspectionState.LOCKED:
        return "another cfc process currently owns it"
    return inspection.detail or "it could not be safely recognised as a compatible cfc database"
