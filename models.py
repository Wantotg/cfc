# models.py — one validated boundary over config.py's model list.
#
# Before 1.2.1 a model's properties were spread across four separate
# collections: MODELS (the chat list), TOOLS_MODELS, ROUTINE_MODELS and
# MODEL_LIMITS. Every caller that wanted to know "does this id take tools" or
# "what's its context window" read one of the three side collections and hoped
# it agreed with MODELS — and when it didn't, the failure was silent
# (commands.unknown_model_ids() existed only to catch that class of typo).
#
# This module replaces all four with one ordered list of records, MODELS,
# each a complete description of one model id. There is nothing left to cross
# check: a record either has the field or it doesn't, and a malformed one
# raises at import time instead of quietly reading as "unsupported".
#
# A config.py written before 1.2.1 still works. _from_legacy() below detects
# the old shape — MODELS as a bare list of id strings — and translates it,
# printing one warning that points at config.example.py. After translation,
# nothing downstream reads config.MODELS, config.TOOLS_MODELS,
# config.ROUTINE_MODELS or config.MODEL_LIMITS directly; every caller
# (commands.py, main.py, agent.py, hub.py, runner.py) reads this module.
from collections import namedtuple

# listed          shown in `/list models`, indexable by `/model <n>`
# tools           emits OpenAI-style tool_calls — verified per id, never guessed
# routine         vetted for unattended routine runs
# routine_default the one record `default_routine_model()` returns when a
#                 routine has no model of its own; at most one may be True
# limit           context window in tokens, or None if unknown
ModelSpec = namedtuple("ModelSpec",
                       "id listed tools routine routine_default limit")


class ModelConfigError(Exception):
    """A MODELS record in config.py is missing a required field, or a field
    is the wrong shape. Raised at import time — a bad record must be loud,
    never silently read as unsupported or without a limit."""


def _spec(id, listed=True, tools=False, routine=False, routine_default=False,
          limit=None):
    if not isinstance(id, str) or not id.strip():
        raise ModelConfigError(f"a MODELS record has no usable 'id': {id!r}")
    for field, val in (("listed", listed), ("tools", tools),
                       ("routine", routine),
                       ("routine_default", routine_default)):
        if not isinstance(val, bool):
            raise ModelConfigError(
                f"MODELS[{id!r}].{field} must be True/False, got {val!r}")
    if routine_default and not routine:
        raise ModelConfigError(
            f"MODELS[{id!r}] sets routine_default without routine")
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)
                              or limit <= 0):
        raise ModelConfigError(
            f"MODELS[{id!r}].limit must be a positive int or None, "
            f"got {limit!r}")
    return ModelSpec(id, listed, tools, routine, routine_default, limit)


def _from_records(raw):
    """The 1.2.1 shape: MODELS is already a list of per-model dicts."""
    specs = []
    seen = set()
    for i, rec in enumerate(raw):
        if not isinstance(rec, dict) or "id" not in rec:
            raise ModelConfigError(
                f"MODELS[{i}] must be a dict with an 'id' field, got {rec!r}")
        spec = _spec(**rec)
        if spec.id in seen:
            raise ModelConfigError(f"MODELS lists {spec.id!r} twice")
        seen.add(spec.id)
        specs.append(spec)
    defaults = [s.id for s in specs if s.routine_default]
    if len(defaults) > 1:
        raise ModelConfigError(
            "more than one MODELS record sets routine_default: "
            + ", ".join(defaults))
    return specs


def _from_legacy(cfg, warn):
    """The pre-1.2.1 shape: MODELS a bare list of ids, plus three separate
    collections. Translated once, faithfully.

    This is what `commands.known_models()` used to compute by hand: MODELS in
    order, then any ROUTINE_MODELS id not already there, in ROUTINE_MODELS'
    own order — a routine-only id (Cas's config pins the *non-thinking*
    variant for routines while chat uses the *thinking* one) is a different
    string and gets its own record.

    The default is `ROUTINE_MODELS[0]` verbatim, not "whichever routine model
    sorts first in the combined order" — those disagree the moment a routine
    variant isn't also a chat one, which is exactly that config.
    """
    warn("config.py's MODELS is still a plain list of ids — cfc now reads "
        "one 'MODELS = [...]' list of per-model records in place of MODELS "
        "+ TOOLS_MODELS + ROUTINE_MODELS + MODEL_LIMITS. See the new shape "
        "in config.example.py; this config.py still works, translated.")
    listed = list(getattr(cfg, "MODELS", []) or [])
    routine = list(getattr(cfg, "ROUTINE_MODELS", []) or [])
    tools = set(getattr(cfg, "TOOLS_MODELS", []) or [])
    limits = dict(getattr(cfg, "MODEL_LIMITS", {}) or {})
    default_id = routine[0] if routine else None
    routine_set = set(routine)

    order = list(listed)
    for m in routine:
        if m not in order:
            order.append(m)

    return [_spec(m, listed=m in listed, tools=m in tools,
                 routine=m in routine_set, routine_default=(m == default_id),
                 limit=limits.get(m))
           for m in order]


def _default_warn(msg):
    from ui import console
    console.print(f"[config] {msg}", style="yellow")


def load(cfg=None, warn=None):
    """Pure-ish entry point: build the record list from a config module (or
    config-shaped namespace). `cfg`/`warn` are injectable so tests can compare
    a legacy fixture and a new-shape fixture through this exact function."""
    if cfg is None:
        import config as cfg
    warn = warn or _default_warn
    raw = getattr(cfg, "MODELS", None) or []
    if not raw:
        return []
    if isinstance(raw[0], dict):
        return _from_records(raw)
    return _from_legacy(cfg, warn)


_startup_warnings = []
MODELS = load(warn=_startup_warnings.append)


def startup_warnings():
    """Anything noticed while loading `MODELS` — currently only the
    legacy-shape notice. Collected rather than printed at import time so a
    caller can show it at the right moment (main.py prints these after the
    splash, same timing the old per-collection typo warning used), and so
    importing this module has no console side effect for anything that
    imports it early, like the golden harness."""
    return list(_startup_warnings)


def by_id(model_id):
    return next((m for m in MODELS if m.id == model_id), None)


def listed_ids():
    """Ids in `/list models`' displayed order — `/model <n>` indexes into
    this, 1-based."""
    return [m.id for m in MODELS if m.listed]


def known_ids():
    """Every id this config knows, in the order `resolve_model` matches
    against: listed first, then anything known but not listed."""
    return [m.id for m in MODELS]


def supports_tools(model_id):
    spec = by_id(model_id)
    return bool(spec and spec.tools)


def tool_capable_ids():
    return [m.id for m in MODELS if m.tools]


def is_routine_vetted(model_id):
    spec = by_id(model_id)
    return bool(spec and spec.routine)


def routine_ids():
    return [m.id for m in MODELS if m.routine]


def routine_default_id():
    """The id `runner.default_routine_model()` falls back to when a routine
    has no model of its own. None if nothing is marked — the caller's own
    fallback (config.MODEL) applies then, same as an empty ROUTINE_MODELS
    used to."""
    return next((m.id for m in MODELS if m.routine_default), None)


def context_limit(model_id):
    spec = by_id(model_id)
    return spec.limit if spec else None
