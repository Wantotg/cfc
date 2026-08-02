# routines.py — the routine object and its store.
#
# A routine is a task the model runs on demand now, and on a schedule later.
# It is one markdown file: YAML frontmatter for the machine-readable fields,
# the body reserved for notes. The task prompt is a separate file under
# ROUTINE_PROMPT_DIR.
#
# The load-bearing property is that **a routine is fully reconstructable from
# its file**. No hidden database state, no sidecar index. That is what makes
# "list" mean list the folder, "delete" mean remove a file, and "edit" mean
# edit it in Obsidian — and it is why management costs nothing to add later.
# Anything you are tempted to keep only in the DB either belongs in the
# frontmatter or belongs in the run log.
#
# Identity is the `id` field, not the filename. The wiki importer learned this
# the hard way (HANDOVER: "wiki identity survives edits"): key off a stable id
# and renaming a routine keeps its log history instead of orphaning it.
#
# Validation happens twice on purpose:
#
#   at type time      — paths.denial_reason() as each path is entered, so a
#                       typo is rejected while the human is still looking at it
#   at construction   — Routine.context() builds the real ToolContext, so a
#                       write root overlapping the source raises ScopeError and
#                       the routine cannot be saved, let alone run
#
# A routine that silently stores an out-of-bounds path is the failure you do
# not see until 03:00 six weeks later. Both checks are cheap; keep both.
import datetime
import os
import re
from pathlib import Path

import yaml

from context import ScopeError, ToolContext
from paths import denial_reason

DEFAULTS = {
    "trigger": "command",
    "on_failure": "retry",
    "enabled": True,
}

# Frontmatter keys written in this order — a stable field order keeps the diff
# of an edited routine readable in git/Obsidian.
FIELD_ORDER = ("id", "name", "prompt", "model", "read_roots", "write_roots",
               "trigger", "on_failure", "enabled")

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_WIKILINK_RE = re.compile(r"^\[\[(.+)\]\]$")
# 'command' | 'HHMM' (daily) | 'weekly HHMM'.
#
# `weekly` does NOT mean "on Mondays". It means "when a completed calendar week
# has gone unabsorbed" — see last_completed_week below. The distinction is the
# whole point: a Monday check is one the machine being off on Monday makes you
# miss entirely, and the missed week is then never processed by anything.
_TRIGGER_RE = re.compile(r"^(command|\d{4}|weekly\s+\d{4})$")


ON_FAILURE = ("retry", "skip")


# **The two field checks the creation flow needs *before* the last question,
# lifted out of `validate()` rather than copied beside it** (v1.0,
# `D-0.9.1-03`). `/routine new` used to take `trigger` and `on_failure` raw and
# find out they were wrong six answers later, at `save_routine`, discarding the
# name, the prompt, the roots and the model with them.
#
# Lifted, because the alternative is a second opinion about what a valid
# trigger is — and the two would disagree the first time `weekly` grew a
# variant. `validate()` still calls these and is still the thing that makes an
# invalid routine unsaveable (standing decision 8): the early check is a
# courtesy to the typist, the late one is the guarantee, and they cannot
# disagree because they are the same function.
def trigger_problem(value):
    """Why this trigger is unusable, or None. The single definition."""
    trig = str(value).strip()
    if not _TRIGGER_RE.match(trig):
        return (f"trigger {value!r} is not 'command', HHMM or 'weekly HHMM'")
    if trig != "command":
        hhmm = trig.split()[-1]
        hh, mm = int(hhmm[:2]), int(hhmm[2:])
        if hh > 23 or mm > 59:
            return f"trigger {value!r} is not a valid time"
    return None


def on_failure_problem(value):
    """Why this on_failure is unusable, or None. The single definition."""
    if value not in ON_FAILURE:
        return f"on_failure {value!r} is not retry|skip"
    return None


_RAW_TRIGGER_RE = re.compile(r"^trigger:\s*(?P<v>.+?)\s*$", re.MULTILINE)


def _raw_trigger(text, fm):
    """The `trigger:` value as it was actually typed.

    YAML 1.1 reads a leading-zero digit string as **octal**, so `trigger: 0300`
    — the obvious way to write 03:00, and the one every example uses — arrives
    from `yaml.safe_load` as the integer **192**. Nothing about that is
    visible: the file says 0300, the routine says 192, and validation rejects a
    trigger the author never wrote. It bites 0000–0777 (any leading zero with
    all digits ≤ 7) and leaves 1400 alone, so it fails on early-morning times
    specifically — exactly when these jobs run.

    So the field is re-read from the raw frontmatter whenever YAML hands back
    anything but a string. Narrow on purpose: YAML stays the parser for the
    whole file, and this intervenes only where its typing is known to lie
    about what the file says. Quoting on write (see to_markdown) fixes files
    cfc authors; this fixes the hand-written ones, which is most of them.
    """
    val = fm.get("trigger", DEFAULTS["trigger"])
    if isinstance(val, str):
        return val
    head = text.split("---", 2)[1] if text.startswith("---") else text
    m = _RAW_TRIGGER_RE.search(head)
    if m:
        return m.group("v").strip("'\"")
    return str(val)


def week_monday(d):
    """The Monday of the Mon–Sun week containing `d`."""
    return d - datetime.timedelta(days=d.weekday())


def last_completed_week(d):
    """(monday, sunday) of the most recent week that had fully ended by `d`.

    "Ended" is strict: on Sunday the 26th, the week 20–26 is still running, so
    the last completed one is 13–19. On Monday the 27th it is 20–26.

    This is the anchor for a weekly routine, and it is anchored to the calendar
    rather than to the last run on purpose. Anchoring to the run would let a
    late run shift every subsequent week — miss one Monday and the whole
    cadence walks forward a day and never walks back. Weeks are Mon–Sun
    permanently, however erratic the runs are.
    """
    monday = week_monday(d) - datetime.timedelta(days=7)
    return monday, monday + datetime.timedelta(days=6)


class RoutineError(Exception):
    """A routine file is malformed, missing, or names something that isn't there."""


def slugify(name):
    """A stable id from a display name. Lowercase, hyphen-separated."""
    return _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")


# --- naming the task prompt ------------------------------------------------
#
# These files are authored and linked in Obsidian, so `prompt:` arrives in
# whatever form Obsidian wrote: a wikilink `[[wiki draft writer prompt]]`, a
# link with an alias or a heading, a vault-relative path when "shortest path
# when possible" is off, or a plain filename typed by hand. All of them name
# the same file; only the last one used to work, and the failure was a
# `prompt file not found: …/[[wiki draft writer prompt]]` that reads like the
# file is missing when it is sitting right there.
#
# **The stored string is never rewritten.** `prompt_candidates` is a read-time
# interpretation, so `to_markdown()` still emits exactly what the file said and
# the round-trip stays byte-identical. Obsidian owns that field's syntax; if it
# is normalised on save, Obsidian's own link-update-on-rename stops finding it.
#
# Ambiguity is resolved by *existence*, not by guessing: every plausible form
# is tried in order and the first file that is actually there wins. A `.md` is
# appended only as a candidate, never assumed, so a prompt genuinely named
# `x.txt` still resolves.


def prompt_candidates(prompt):
    """Every filename `prompt:` might mean, best guess first.

    Pure and prompt_dir-free so it can be tested against a string.
    """
    text = (prompt or "").strip()
    m = _WIKILINK_RE.match(text)
    if m:
        text = m.group(1).strip()
        text = text.split("|", 1)[0].strip()       # [[note|alias]]
        text = text.split("#", 1)[0].strip()       # [[note#heading]]
        text = text.split("^", 1)[0].strip()       # [[note^block]]
    if not text:
        return []

    forms = [text] if text.lower().endswith(".md") else [text + ".md", text]
    # A vault-relative link ('06 metadata/routine prompts/x') names the same
    # file as its basename does, since ROUTINE_PROMPT_DIR is where prompts
    # live. Tried last: an actual subfolder under the prompt dir must win.
    forms += [Path(f).name for f in forms if "/" in f or "\\" in f]

    out = []
    for f in forms:
        if f and f not in out:
            out.append(f)
    return out


def _cfg(key, default=None):
    try:
        import config
        return getattr(config, key, default)
    except ImportError:
        return default


def routine_dir():
    return Path(_cfg("ROUTINE_DIR", "~/.cfc/routines")).expanduser()


def prompt_dir():
    return Path(_cfg("ROUTINE_PROMPT_DIR", "~/.cfc/routine prompts")).expanduser()


def log_dir():
    return Path(_cfg("ROUTINE_LOG_DIR", "~/.cfc/routine logs")).expanduser()


def split_frontmatter(text):
    """Return (frontmatter_dict, body). ({}, text) if there's no frontmatter.

    Same shape as import_wiki's — duplicated rather than shared because that
    one is about a corpus and this one is about config, and a change to either
    should not silently move the other.
    """
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as e:
        raise RoutineError(f"bad frontmatter: {e}")
    if not isinstance(fm, dict):
        raise RoutineError("frontmatter is not a mapping")
    return fm, parts[2].lstrip("\n")


class Routine:
    """One routine, as loaded from (or about to be written to) its file.

    `path` is where it was read from and is NOT part of the identity — it is
    None for a routine built in memory and never round-trips through the
    frontmatter.
    """

    def __init__(self, id, name, prompt, model="", read_roots=(), write_roots=(),
                 trigger="command", on_failure="retry", enabled=True,
                 body="", path=None):
        # The id is normalised to a slug here, at the one construction
        # chokepoint, rather than validated and rejected. These files are
        # hand-authored in Obsidian, where `id: note reader` is what you
        # naturally type, so a strict slug check turned every hand-made routine
        # into a validation failure. Normalising instead means the id is a clean
        # handle everywhere it's used — the log filename, the session lookup,
        # `:routine <id>` — while the *file* keeps whatever was written until
        # cfc itself next saves it (to_markdown emits the slug, load does not
        # rewrite disk). The name stays free text; only the id is coerced.
        self.id = slugify(id)
        self.name = name
        self.prompt = prompt
        # The model this routine runs on. Optional and kept as an opaque string
        # here on purpose: routines.py imports only context/paths/yaml, so it
        # does not know models.MODELS and must not start — vetting the model
        # against it is the runner's and the REPL's job, where that module
        # already lives. Empty means "use the caller's or the vetted
        # default" (see runner.effective_model). A routine's own pin is a
        # deliberate, persisted choice, so it wins over the ambient default.
        self.model = (model or "").strip()
        self.read_roots = tuple(str(r) for r in read_roots)
        self.write_roots = tuple(str(r) for r in write_roots)
        self.trigger = trigger
        self.on_failure = on_failure
        self.enabled = bool(enabled)
        # Normalised once, here, so the file's trailing newline can never be
        # part of the object's identity. to_markdown() strips on the way out
        # too; without this the round-trip differs by exactly "\n" and the
        # "reconstructable from its file" invariant fails on a technicality.
        self.body = (body or "").strip()
        self.path = path

    # --- validation --------------------------------------------------------

    def validate(self):
        """Every reason this routine is unusable, as a list of strings.

        Non-raising and exhaustive: the creation flow wants to show all the
        problems at once, and a caller that wants an exception can raise on a
        non-empty list. Path *containment* is not checked here — that is
        ToolContext's job, via context(), which this deliberately does not
        duplicate.
        """
        problems = []
        if not self.id:
            # Can only happen if the source id slugified to nothing (empty, or
            # all punctuation). The slug coercion in __init__ means a non-slug
            # id is normalised rather than reported — see there.
            problems.append("id is empty")
        if not self.name:
            problems.append("name is empty")
        if not self.prompt:
            problems.append("prompt is empty")
        elif self.prompt_path() is None:
            # Name the forms that were tried, not just the one that failed —
            # with wikilinks in play "not found" alone leaves you unsure
            # whether the file is missing or the link syntax went unread.
            tried = " | ".join(prompt_candidates(self.prompt)) or self.prompt
            problems.append(f"prompt file not found in {prompt_dir()}: {tried}")
        # The same two functions `/routine new` re-prompts against, so a field
        # accepted as you type it can never be rejected at save, and a field
        # edited into the file by hand is still caught here.
        for problem in (trigger_problem(self.trigger),
                        on_failure_problem(self.on_failure)):
            if problem:
                problems.append(problem)

        for label, roots in (("read", self.read_roots),
                             ("write", self.write_roots)):
            for r in roots:
                p = Path(r).expanduser()
                why = denial_reason(p)
                if why:
                    problems.append(f"{label} root {r}: {why}")
                elif not p.exists():
                    problems.append(f"{label} root does not exist: {r}")

        # Construction-time scope check. A write root overlapping the source
        # must make the routine unsaveable, not merely unrunnable.
        try:
            self.context()
        except ScopeError as e:
            problems.append(str(e))
        return problems

    def context(self, interactive=False):
        """The ToolContext this routine runs under. Ungated by construction."""
        return ToolContext.for_routine(
            self.id,
            read_roots=self.read_roots,
            write_roots=self.write_roots,
            interactive=interactive,
        )

    def prompt_path(self):
        """Where the task prompt actually is, or None if nothing matches.

        Resolution is by existence over `prompt_candidates`. Containment in
        ROUTINE_PROMPT_DIR is checked rather than assumed: `prompt:` is a
        string in a hand-edited file, so `[[../../.ssh/id_rsa]]` is a thing
        somebody can write, and this feeds a read. It is not the file jail —
        `paths.path_guard` is, for anything the model reaches — but a routine's
        own task prompt never comes from outside its folder, and a closed
        commitment beats a check somewhere else remembering to run.
        """
        base = prompt_dir()
        try:
            base_r = base.resolve()
        except OSError:
            return None
        for name in prompt_candidates(self.prompt):
            p = base / name
            try:
                if not p.is_file():
                    continue
                r = p.resolve()
            except OSError:
                continue
            if r == base_r or base_r in r.parents:
                return p
        return None

    def prompt_text(self):
        p = self.prompt_path()
        if p is None:
            raise RoutineError(f"cannot read prompt {self.prompt!r}: "
                               f"no such file under {prompt_dir()}")
        try:
            return p.read_text(encoding="utf-8")
        except OSError as e:
            raise RoutineError(f"cannot read prompt {p}: {e}")

    # --- serialisation -----------------------------------------------------

    def to_markdown(self):
        fm = {
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
            "model": self.model,
            "read_roots": list(self.read_roots),
            "write_roots": list(self.write_roots),
            "trigger": self.trigger,
            "on_failure": self.on_failure,
            "enabled": self.enabled,
        }
        # An unset model is omitted rather than written as `model: ''`, so a
        # hand-authored routine that never pins one stays minimal and the
        # round-trip is byte-stable (from_markdown reads a missing key as "").
        ordered = "".join(
            yaml.safe_dump({k: fm[k]}, default_flow_style=False,
                           allow_unicode=True, sort_keys=False)
            for k in FIELD_ORDER
            if not (k == "model" and not fm[k])
        )
        return f"---\n{ordered}---\n\n{self.body.strip()}\n"

    @classmethod
    def from_markdown(cls, text, path=None):
        fm, body = split_frontmatter(text)
        if not fm:
            raise RoutineError(f"{path or 'routine'} has no frontmatter")
        missing = [k for k in ("id", "name", "prompt") if not fm.get(k)]
        if missing:
            raise RoutineError(f"{path or 'routine'} is missing: "
                               f"{', '.join(missing)}")
        return cls(
            id=str(fm["id"]),
            name=str(fm["name"]),
            prompt=str(fm["prompt"]),
            model=fm.get("model") or "",
            read_roots=fm.get("read_roots") or (),
            write_roots=fm.get("write_roots") or (),
            trigger=_raw_trigger(text, fm),
            on_failure=str(fm.get("on_failure", DEFAULTS["on_failure"])),
            enabled=fm.get("enabled", DEFAULTS["enabled"]),
            body=body,
            path=path,
        )

    def __repr__(self):
        return (f"<Routine {self.id} trigger={self.trigger} "
                f"enabled={self.enabled}>")

    def __eq__(self, other):
        """Field equality, ignoring `path` — that's provenance, not identity.

        This is what the round-trip test asserts against: write a routine,
        read it back, get an equal object.
        """
        if not isinstance(other, Routine):
            return NotImplemented
        return all(getattr(self, f) == getattr(other, f) for f in
                   ("id", "name", "prompt", "model", "read_roots", "write_roots",
                    "trigger", "on_failure", "enabled", "body"))


# --- the store -------------------------------------------------------------


def list_routines():
    """Every routine file that parses, sorted by id. Malformed files are
    skipped rather than fatal — one bad file must not hide the rest."""
    out, bad = [], []
    d = routine_dir()
    if not d.is_dir():
        return out, bad
    for f in sorted(d.glob("*.md")):
        try:
            out.append(Routine.from_markdown(f.read_text(encoding="utf-8"), f))
        except (RoutineError, OSError) as e:
            bad.append((f.name, str(e)))
    return sorted(out, key=lambda r: r.id), bad


def load_routine(key):
    """By id, then display name, then the slug of what was typed.

    The third pass is what lets a display name be a sentence and an id be a
    handle without the two having to agree: 'Wiki Maintainer' finds
    `wiki-maintainer`. It runs last so an exact id or name always wins over a
    slugged guess. Raises RoutineError.
    """
    routines, _ = list_routines()
    for r in routines:
        if r.id == key:
            return r
    for r in routines:
        if r.name.lower() == (key or "").lower():
            return r
    slugged = slugify(key)
    for r in routines:
        if slugged and r.id == slugged:
            return r
    # The error names both, because the id is what a routine is looked up by
    # and the name is what it is called in Obsidian. Printing ids alone once
    # left a routine whose id was not a slug listed as available while being
    # unrunnable, which reads as the command being typed wrong.
    known = ", ".join(f"{r.id} ({r.name})" for r in routines) or "(none)"
    raise RoutineError(f"no routine {key!r} — known: {known}")


def save_routine(routine, overwrite=False):
    """Write the routine to ROUTINE_DIR/<id>.md, atomically.

    Refuses to save an invalid routine. That's the point of validating at
    construction: an unsaveable routine can never become a 03:00 surprise.
    """
    problems = routine.validate()
    if problems:
        raise RoutineError("; ".join(problems))
    d = routine_dir()
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{routine.id}.md"
    if dest.exists() and not overwrite:
        raise RoutineError(f"{dest.name} already exists")
    tmp = dest.with_name(f".{dest.name}.tmp")
    tmp.write_text(routine.to_markdown(), encoding="utf-8")
    os.replace(tmp, dest)
    routine.path = dest
    return dest


# --- the run log -----------------------------------------------------------
#
# One file per routine, append-only. Two consumers, and the second is why this
# is a log and not a print: a human asking "did the nightly thing work", and
# **the next run**, which has to see that the last one failed to honour
# on_failure.
#
# Appended through a temp file + os.replace like every other write here. A
# plain append that is interrupted mid-write leaves a torn final line; a log
# that can corrupt itself on the failure it exists to record is worse than no
# log.

_LOG_RE = re.compile(
    r"^- \*\*(?P<ts>[^*]+)\*\* — (?P<status>\w+)(?P<review> \(review\))?"
    r"(?: — run #(?P<run>\d+))?"
    r"(?: — (?P<rest>.*))?$")

# The touched-files clause, wherever it sits in `rest`. Two shapes because
# `rest` may or may not still carry the ` — ` that introduces it: `_LOG_RE`
# already consumed the *first* ` — ` in the line, so a line with no other
# clause has "wrote N files: …" sitting at the very start of `rest`, while a
# line that also has detail/session text keeps its own leading ` — ` intact
# inside `rest`. Matching both means "touched goes last" holds regardless of
# what precedes it.
_TOUCHED_RE = re.compile(r"(?:^| — )wrote \d+ files?: (?P<files>.*)$")

# The *current* writer's session marker: its own field, always the last thing
# before the touched clause (or end of line). Anchored at the end of whatever
# remains once touched is stripped, so it can never be confused with a
# filename that happens to contain the word "session".
_NEW_SESSION_RE = re.compile(r"\(session (?P<sid>\d+)\)$")

# Every session id ever spliced into `detail` by hand, before this field
# existed. `runner.py` wrote two shapes: a bare "{detail} (session N)", which
# is byte-identical to the current marker and so is caught (and stripped) by
# `_NEW_SESSION_RE` above without any special-casing; and, on the ok/failed
# paths, "{detail} (NNs, session N)" — a *different* shape, since the elapsed
# time breaks the "(" immediately before "session" that the strict pattern
# needs. This looser fallback recovers the id from that second shape only,
# and leaves `detail` exactly as it was rendered: rewriting old lines is not
# this parser's job, only reading them is.
_LEGACY_SESSION_RE = re.compile(r"\bsession (?P<sid>\d+)\)")

# `elapsed_seconds`'s own marker, anchored at the end of whatever remains
# once touched and session are stripped. Gated on the run-number marker's
# presence (see parse_log_line) rather than tried unconditionally: an old
# line's elapsed time is prose baked into `detail` itself — the same
# "(NNs, ...)" shape `_LEGACY_SESSION_RE` already has to work around — and
# reinterpreting that prose as structured data on read would rewrite what
# every pre-existing log line means without touching a single byte of it.
# This marker only ever appears on a line `append_log` itself wrote under
# the new shape, so the gate costs nothing on the lines it protects.
_ELAPSED_RE = re.compile(r"\((?P<secs>\d+)s\)$")


class RunRecord:
    """One parsed line from a routine's run log.

    `detail` is the free-text summary/reason, with a trailing session marker
    stripped out — it is structured metadata now, not prose, and a bare
    "(session N)" from before this field existed is indistinguishable from the
    current one, so it is stripped the same way. The one shape left untouched
    is the legacy "(NNs, session N)" combination, where the elapsed time makes
    it genuinely different text; rewriting old lines is not this parser's job.
    `touched` is the joined display string `append_log` already built, not a
    re-split list: a filename may itself contain ", ", so there is no lossless
    way back to individual names and nothing here needs one.

    `run_number` is `None` only transiently, between parsing and `read_log`'s
    post-pass — every record that reaches a caller has one, explicit (a line
    this module wrote under the new shape) or derived (an older line, given
    one deterministically, oldest first). `session_id` stays an internal
    field: it is what `db.routine_session` checks a transcript reference
    against, never what a routine surface names at a person — see
    `<routine-id>/<run-number>` on the routines screen.

    `elapsed_seconds` is `None` for a line that predates the field — the
    active-runtime clock `runner.py` measures with, not the wall-clock gap
    between this run's start and its log line, which a suspended machine can
    inflate to hours for a run that took seconds (`N-0.9.2-03`).
    """

    def __init__(self, timestamp, status, review, detail, touched, session_id,
                 run_number=None, elapsed_seconds=None):
        self.timestamp = timestamp
        self.status = status
        self.review = review
        self.detail = detail
        self.touched = touched
        self.session_id = session_id
        self.run_number = run_number
        self.elapsed_seconds = elapsed_seconds

    def __repr__(self):
        return (f"<RunRecord #{self.run_number} {self.timestamp} {self.status} "
                f"review={self.review} session={self.session_id} "
                f"elapsed={self.elapsed_seconds}>")


def parse_log_line(line):
    """A `RunRecord`, or None if this line isn't one.

    Reads both the current format and every line ever written under the old
    one — see the module comment above `_LEGACY_SESSION_RE`. `last_run()` and
    the routines screen's history both read the log through this one
    function, so there is exactly one place that understands a run-log line.

    `run_number` comes back `None` here for a line that never had the marker
    — `read_log`'s `_assign_run_numbers` pass is what gives it one. A single
    line is not enough context to derive it from: derivation is oldest-first
    across the *whole* log, so it belongs to the reader of the file, not the
    reader of one line.
    """
    m = _LOG_RE.match(line.strip())
    if not m:
        return None
    run_number = int(m.group("run")) if m.group("run") else None
    rest = m.group("rest") or ""

    touched = ""
    tm = _TOUCHED_RE.search(rest)
    if tm:
        touched = tm.group("files")
        rest = rest[:tm.start()]

    session_id = None
    sm = _NEW_SESSION_RE.search(rest.rstrip())
    if sm:
        session_id = int(sm.group("sid"))
        rest = rest[:sm.start()].rstrip()
    else:
        lm = _LEGACY_SESSION_RE.search(rest)
        if lm:
            session_id = int(lm.group("sid"))

    elapsed_seconds = None
    if run_number is not None:
        em = _ELAPSED_RE.search(rest.rstrip())
        if em:
            elapsed_seconds = float(em.group("secs"))
            rest = rest[:em.start()].rstrip()

    return RunRecord(
        timestamp=m.group("ts"),
        status=m.group("status"),
        review=bool(m.group("review")),
        detail=rest,
        touched=touched,
        session_id=session_id,
        run_number=run_number,
        elapsed_seconds=elapsed_seconds,
    )


def log_path(routine_id):
    return log_dir() / f"{routine_id}.md"


def _parse_lines(text):
    """Every parseable `RunRecord` in `text`, in file order. No I/O, no
    derivation — the shared core `read_log` and `_reserve_run_number` both
    build on, so the two can never read a line differently from one another."""
    out = []
    for line in text.splitlines():
        rec = parse_log_line(line)
        if rec is not None:
            out.append(rec)
    return out


def _assign_run_numbers(records):
    """Give every record missing a `run_number` one, oldest first — mutates
    and returns `records`.

    One counter, carried across the whole file: it only ever moves forward,
    to the explicit number on a record that has one or by one otherwise. In
    the log this design actually produces — a run of old, unnumbered lines
    followed by new, numbered ones, because numbering began at a point in
    time and nothing rewrites what came before it — that means the old lines
    number themselves 1, 2, 3… and the first numbered line continues from
    wherever they left off, with no gap and no collision.
    """
    counter = 0
    for rec in records:
        if rec.run_number is not None:
            counter = max(counter, rec.run_number)
        else:
            counter += 1
            rec.run_number = counter
    return records


def _reserve_run_number(existing_text):
    """The number the next `append_log` call should use, read fresh from the
    log's current text.

    Never from a caller's own read of history — a second read is a second
    chance for the two to disagree — and never defaulted on a read failure:
    `append_log` calls this against text it has already read, so a failure
    here is a failure to read the log, and letting that raise is what keeps
    a mis-reserved number from ever being silently reused. A duplicate run
    reference is a worse failure than a routine run that didn't get logged.
    """
    records = _assign_run_numbers(_parse_lines(existing_text))
    return max((r.run_number for r in records), default=0) + 1


def append_log(routine_id, status, detail="", touched=(), review=False,
               session_id=None, elapsed_seconds=None):
    """Record one run. `status` is 'ok', 'failed' or 'cancelled'.

    `review` is a **second, orthogonal signal**, and the reason it isn't folded
    into `status`: a run's loop can complete cleanly (`status='ok'`) while the
    model's own output reports it couldn't do the task ("I cannot …", "outside
    my allowed roots"). One ok/failed bit cannot say both "the loop worked" and
    "the result needs a human glance". It renders as ' (review)' right after the
    status — reading as `ok (review)` — so a person scanning the log sees it and
    `last_run` can parse it back, while `status` stays exactly 'ok' for the
    scheduler's on_failure logic, which must not retry a run that didn't fail.

    `run_number` is not a parameter — it is this function's own job to
    allocate one, from the same log text it is about to append to, so a
    caller can never hand it a number read at some earlier, now-stale moment.

    `elapsed_seconds` is data, not prose: `runner.py` used to format
    "({elapsed:.0f}s)" straight into `detail` in three different branches,
    which meant a reader recovering the number was reading the runner's
    wording rather than something the log structurally carries. One field,
    written once, here.

    `session_id` is the run's own session — also data, not prose, for the
    same reason. `parse_log_line` reads it back on either the current shape
    or any of the ones `runner.py` wrote before this field existed.

    `touched` is the files the run wrote — filled by the collector
    `runner.run_routine` hands to `agent_turn`. Two things about how it renders,
    both learned by looking at a real line:

    * **Names, not full paths.** Every write lands under the one write root, so
      full paths repeat 47 identical characters per file and bury the line in
      the prefix they share. The transcript holds the absolute truth; this
      field answers "which files", which a name answers.
    * **It goes last.** Fields here are separated by ` — `, and this vault's
      filenames contain that exact string (`wiki draft — chunking.md`), so a
      list in the middle of the line is a list you cannot find the end of.
      Last, everything after the colon is the list, to end of line.
    """
    d = log_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = log_path(routine_id)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    run_number = _reserve_run_number(existing)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"- **{ts}** — {status}"
    if review:
        line += " (review)"
    line += f" — run #{run_number}"
    notes = []
    if detail:
        notes.append(detail.strip())
    if elapsed_seconds is not None:
        notes.append(f"({elapsed_seconds:.0f}s)")
    if session_id is not None:
        notes.append(f"(session {session_id})")
    if notes:
        line += " — " + " ".join(notes)
    if touched:
        names = ", ".join(Path(t).name for t in touched)
        plural = "" if len(touched) == 1 else "s"
        line += f" — wrote {len(touched)} file{plural}: {names}"

    head = "" if path.exists() else f"# Run log — {routine_id}\n\n"
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(existing + head + line + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def read_log(routine_id):
    """Every parseable `RunRecord` for this routine, oldest first (file
    order), each carrying a `run_number` — explicit or derived. A line that
    doesn't parse is skipped rather than fatal — same policy `list_routines()`
    gives a malformed file: one bad line must not hide the rest of the
    history. Unlike `_reserve_run_number`, a read failure here returns []
    rather than raising: this is the lenient, consumer-facing reader, and a
    hidden history is a smaller failure than a broken hub or a broken screen."""
    path = log_path(routine_id)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return _assign_run_numbers(_parse_lines(text))


def last_run(routine_id):
    """(status, timestamp, review) of the most recent run, or (None, None, False).

    `status` is what on_failure is decided against, so it reads the file rather
    than any in-memory state — a scheduled run is a fresh process. `review` is
    the orthogonal 'loop ok but the output looks off' flag (see append_log); it
    is deliberately separate from `status` so a flagged run is not mistaken for
    a failed one.

    A consumer of `read_log`/`parse_log_line`, same as the routines screen's
    history — one parser, not a second regex that could drift from it.
    """
    records = read_log(routine_id)
    if not records:
        return None, None, False
    last = records[-1]
    return last.status, last.timestamp, last.review


def last_success(routine_id):
    """When this routine last completed a run that wasn't a failure, or None.

    Distinct from `last_run` because "when did this last *do* anything" and
    "what happened most recently" are different questions, and the cadence
    rules need the first. A weekly job's "have I absorbed that week yet" keyed
    off the latest run of any kind would treat a *failure* as having absorbed
    the week and skip it permanently — the week's material would then age out
    of short term with nothing having condensed it, silently.

    `ok (review)` counts as a success, deliberately: review means "the loop
    finished but the result wants a glance". The run happened and the file was
    written, so re-running it would process the same period twice. The two
    signals stay separate here for the same reason they do everywhere else.

    A `cancelled` run — Ctrl-C — is not a success either: nothing was
    absorbed, so it must not make a weekly job think its week is done. Only
    `status == "ok"` counts, which is also what keeps this correct should a
    fourth outcome ever join `ok`/`failed`/`cancelled` — a caller does not
    have to remember to add it here too.
    """
    for rec in reversed(read_log(routine_id)):
        if rec.status != "ok":
            continue
        try:
            return datetime.datetime.strptime(rec.timestamp,
                                              "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            # Same direction as the scheduler's unreadable-timestamp rule: a
            # line we cannot read is not evidence that anything succeeded.
            return None
    return None


def last_settled(routine_id):
    """(status, timestamp, review) of the most recent run that was `ok` or
    `failed` — skipping any `cancelled` runs — or (None, None, False).

    `last_run` answers "what happened most recently", and a cancelled run is
    real history that belongs there (Concept.md: it "remains the latest
    visible history row"). This answers a different question — "what does
    the schedule have to react to" — and a cancellation absorbed nothing, so
    it must not look like a completed run today: `schedule.why_not_due` calls
    this, not `last_run`, precisely so a manual Ctrl-C cannot make a due
    routine look done for the day, and so it cannot spend a retry slot a real
    failure would have.
    """
    for rec in reversed(read_log(routine_id)):
        if rec.status == "cancelled":
            continue
        return rec.status, rec.timestamp, rec.review
    return None, None, False
