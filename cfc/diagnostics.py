"""diagnostics.py — the seven-row inventory `cfc doctor` renders: runtime,
configuration, chat provider, 2.0 database target, vault, embeddings, and
file tools. The first four are required — a `Row.state` of `ERROR` on any
of them is what makes `doctor` exit non-zero. The last three are optional:
absence is `UNAVAILABLE`, never `ERROR`, and never blocks the exit code.

Every check here is local and structural, same as `settings.py`, which this
module calls for the two rows that share its rules. Nothing here opens a
socket, a database, or creates a directory.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

from cfc import config_loader, entry, paths, settings

REQUIRED_ROW_NAMES = ("runtime", "configuration", "chat provider", "2.0 database target")
OPTIONAL_ROW_NAMES = ("vault", "embeddings", "file tools")
ROW_ORDER = REQUIRED_ROW_NAMES + OPTIONAL_ROW_NAMES


class State(Enum):
    READY = "ready"
    UNAVAILABLE = "unavailable"
    ERROR = "error"
    NOT_BUILT = "not built"


@dataclass(frozen=True)
class Row:
    name: str
    state: State
    detail: str = ""


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
        rows.append(Row("configuration", State.ERROR, str(exc)))
        cascaded = "configuration failed to load; see the configuration row"
        for name in REQUIRED_ROW_NAMES[2:]:
            rows.append(Row(name, State.ERROR, cascaded))
        for name in OPTIONAL_ROW_NAMES:
            rows.append(Row(name, State.ERROR, cascaded))
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
    """False if any required row is `ERROR` — what `doctor` bases its exit
    code on. Optional rows never affect this.
    """
    return all(
        row.state != State.ERROR
        for row in rows
        if row.name in REQUIRED_ROW_NAMES
    )


def _runtime_row() -> Row:
    problem = entry.check_interpreter()
    if problem is None:
        return Row("runtime", State.READY, "")
    return Row("runtime", State.ERROR, problem)


def _provider_row(snapshot) -> Row:
    try:
        provider = settings.build_provider(snapshot)
    except settings.SettingsError as exc:
        return Row("chat provider", State.ERROR, str(exc))
    return Row("chat provider", State.READY,
               f"{provider.model} via {provider.api_base}")


def _database_row(snapshot) -> Row:
    try:
        db_path = settings.build_database_path(snapshot)
    except settings.SettingsError as exc:
        return Row("2.0 database target", State.ERROR, str(exc))
    return Row("2.0 database target", State.READY, str(db_path))


def _vault_row(snapshot) -> Row:
    values = snapshot.values
    raw = values.get("CHAT_EXPORT_DIR") or values.get("VAULT_PATH")
    if not raw or raw == "PLACEHOLDER":
        return Row("vault", State.UNAVAILABLE,
                    "CHAT_EXPORT_DIR (or legacy VAULT_PATH) is not set")

    resolved = Path(raw).expanduser().resolve()
    reason = paths.usable_directory_reason(resolved)
    if reason is not None:
        return Row("vault", State.ERROR, reason)
    return Row("vault", State.READY, str(resolved))


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
