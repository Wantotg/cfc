"""diagnostics.py — the seven-row inventory `cfc doctor` renders: runtime,
configuration, chat provider, 2.0 database target, vault, embeddings, and
file tools. The first four are required — `required_rows_ok` is an exact
allow-list, so `doctor` exits non-zero unless every one of them is `READY`,
not merely absent of `ERROR`. The last three are optional: absence is
`UNAVAILABLE`, and neither that nor `NOT_CHECKED` blocks the exit code.

Every check here is local and structural, same as `settings.py`, which this
module calls for the two rows that share its rules. Nothing here opens a
socket, a database, or creates a directory.

`Row.detail` is diagnostic evidence — what was checked and what it found.
`Row.next_step`, stored separately, is recovery guidance — what to do about
it — and is only ever set on a row this module actually diagnosed. A `NOT
CHECKED` row (one that depends on an earlier row that failed) carries a
local explanation in `detail` but no `next_step`: the cure lives once, on
the row that owns it, not copied onto everything downstream.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

from cfc import config_loader, entry, settings

REQUIRED_ROW_NAMES = ("runtime", "configuration", "chat provider", "2.0 database target")
OPTIONAL_ROW_NAMES = ("vault", "embeddings", "file tools")
ROW_ORDER = REQUIRED_ROW_NAMES + OPTIONAL_ROW_NAMES

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
    NOT_BUILT = "not built"
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
        return Row("runtime", State.READY, "")
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
    enabled = bool(snapshot.values.get("TOOLS_ENABLED", False))
    if not enabled:
        return Row("file tools", State.UNAVAILABLE, "TOOLS_ENABLED is off")
    return Row("file tools", State.NOT_BUILT,
               "TOOLS_ENABLED is on, but file tools are not implemented in "
               "the 2.0 boundary yet")
