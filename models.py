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
import math
from collections import namedtuple

# listed          shown in `/list models`, indexable by `/model <n>`
# tools           emits OpenAI-style tool_calls — verified per id, never guessed
# routine         vetted for unattended routine runs
# routine_default the one record `default_routine_model()` returns when a
#                 routine has no model of its own; at most one may be True
# limit           context window in tokens, or None if unknown
# preset_params   the PARAMETER_PRESETS keys verified for this id — never
#                 guessed, same discipline as `tools` (default: none declared)
ModelSpec = namedtuple("ModelSpec",
                       "id listed tools routine routine_default limit "
                       "preset_params")

# The v1.5 sampling-parameter vocabulary. Bounded on purpose — Concept.md's
# "Named Parameter presets" is named profiles from a small checked set, not an
# unvalidated API console. (lo, hi) is the documented range for the current
# NanoGPT Chat Completions contract; both bounds are inclusive.
PRESET_PARAM_RANGES = {"temperature": (0, 2), "top_p": (0, 1)}


class ModelConfigError(Exception):
    """A MODELS record in config.py is missing a required field, or a field
    is the wrong shape. Raised at import time — a bad record must be loud,
    never silently read as unsupported or without a limit."""


def _validate_preset_params(id, keys):
    """A MODELS record's declared preset support: a list/tuple of names from
    PRESET_PARAM_RANGES, each at most once. `None` (the field's absence) is
    "declares nothing" — the legacy-translation default, so old config keeps
    loading with presets simply unavailable rather than guessed at."""
    if keys is None:
        return ()
    if not isinstance(keys, (list, tuple)):
        raise ModelConfigError(
            f"MODELS[{id!r}].preset_params must be a list/tuple of names, "
            f"got {keys!r}")
    seen = []
    for k in keys:
        if k not in PRESET_PARAM_RANGES:
            raise ModelConfigError(
                f"MODELS[{id!r}].preset_params names {k!r} — only "
                f"{tuple(PRESET_PARAM_RANGES)} exist in v1.5")
        if k in seen:
            raise ModelConfigError(
                f"MODELS[{id!r}].preset_params lists {k!r} twice")
        seen.append(k)
    return tuple(seen)


def _spec(id, listed=True, tools=False, routine=False, routine_default=False,
          limit=None, preset_params=None):
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
    preset_params = _validate_preset_params(id, preset_params)
    return ModelSpec(id, listed, tools, routine, routine_default, limit,
                     preset_params)


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


def _validate_presets(cfg):
    """`config.PARAMETER_PRESETS`, validated: name -> {temperature, top_p}.

    Every failure here is loud at import time, same discipline as `_spec` —
    a malformed preset must never quietly become "unsupported" or, worse,
    reach a provider request. Booleans are rejected before the general
    numeric check because `isinstance(True, int)` is true in Python and
    would otherwise pass a stray `top_p=True` as 1.0.
    """
    raw = getattr(cfg, "PARAMETER_PRESETS", None) or {}
    if not isinstance(raw, dict):
        raise ModelConfigError(
            f"PARAMETER_PRESETS must be a dict, got {raw!r}")
    out = {}
    for name, params in raw.items():
        if not isinstance(name, str) or not name.strip():
            raise ModelConfigError(
                f"PARAMETER_PRESETS has an unusable name: {name!r}")
        name = name.strip()
        if name.lower() == "default":
            raise ModelConfigError(
                "PARAMETER_PRESETS can't define a preset named 'default' "
                "— that word means 'clear the preset' at /preset default")
        if not isinstance(params, dict) or not params:
            raise ModelConfigError(
                f"PARAMETER_PRESETS[{name!r}] must be a non-empty dict, "
                f"got {params!r}")
        clean = {}
        for k, v in params.items():
            if k not in PRESET_PARAM_RANGES:
                raise ModelConfigError(
                    f"PARAMETER_PRESETS[{name!r}] names {k!r} — only "
                    f"{tuple(PRESET_PARAM_RANGES)} exist in v1.5")
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ModelConfigError(
                    f"PARAMETER_PRESETS[{name!r}][{k!r}] must be a number, "
                    f"got {v!r}")
            if not math.isfinite(v):
                raise ModelConfigError(
                    f"PARAMETER_PRESETS[{name!r}][{k!r}] must be finite, "
                    f"got {v!r}")
            lo, hi = PRESET_PARAM_RANGES[k]
            if not (lo <= v <= hi):
                raise ModelConfigError(
                    f"PARAMETER_PRESETS[{name!r}][{k!r}]={v!r} is outside "
                    f"{k}'s documented range {lo}-{hi}")
            clean[k] = float(v)
        if name in out:
            raise ModelConfigError(f"PARAMETER_PRESETS lists {name!r} twice")
        out[name] = clean
    return out


def load_presets(cfg=None):
    """Pure-ish entry point for `PARAMETER_PRESETS`, mirroring `load()` above
    so a test can compare fixtures through the exact function the module
    uses at import."""
    if cfg is None:
        import config as cfg
    return _validate_presets(cfg)


_startup_warnings = []
MODELS = load(warn=_startup_warnings.append)
PARAMETER_PRESETS = load_presets()


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


def preset_names():
    """Every configured preset name, in `config.PARAMETER_PRESETS`'s order —
    what `/preset` lists and what completion offers."""
    return list(PARAMETER_PRESETS)


def preset_params(name):
    """The validated {temperature, top_p, ...} dict for this preset name, or
    None. Callers must not read `PARAMETER_PRESETS` or a `ModelSpec`'s
    `preset_params` field directly — this and `compatible_presets` are the
    one boundary (Concept.md: "callers must not inspect record fields or
    configuration directly")."""
    return PARAMETER_PRESETS.get(name)


def compatible_presets(model_id):
    """Configured preset names whose keys are all declared by this model —
    an unknown/unconfigured model declares nothing, so nothing is
    compatible with it."""
    spec = by_id(model_id)
    declared = set(spec.preset_params) if spec else set()
    return [name for name, params in PARAMETER_PRESETS.items()
            if set(params) <= declared]


def preset_compatible(model_id, name):
    return name in compatible_presets(model_id)


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
