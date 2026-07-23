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
FIELD_ORDER = ("id", "name", "prompt", "read_roots", "write_roots",
               "trigger", "on_failure", "enabled")

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_WIKILINK_RE = re.compile(r"^\[\[(.+)\]\]$")
_TRIGGER_RE = re.compile(r"^(command|\d{4})$")


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

    def __init__(self, id, name, prompt, read_roots=(), write_roots=(),
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
        if not _TRIGGER_RE.match(str(self.trigger)):
            problems.append(f"trigger {self.trigger!r} is not 'command' or HHMM")
        elif str(self.trigger) != "command":
            hh, mm = int(str(self.trigger)[:2]), int(str(self.trigger)[2:])
            if hh > 23 or mm > 59:
                problems.append(f"trigger {self.trigger!r} is not a valid time")
        if self.on_failure not in ("retry", "skip"):
            problems.append(f"on_failure {self.on_failure!r} is not retry|skip")

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
            "read_roots": list(self.read_roots),
            "write_roots": list(self.write_roots),
            "trigger": self.trigger,
            "on_failure": self.on_failure,
            "enabled": self.enabled,
        }
        ordered = "".join(
            yaml.safe_dump({k: fm[k]}, default_flow_style=False,
                           allow_unicode=True, sort_keys=False)
            for k in FIELD_ORDER
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
            read_roots=fm.get("read_roots") or (),
            write_roots=fm.get("write_roots") or (),
            trigger=str(fm.get("trigger", DEFAULTS["trigger"])),
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
                   ("id", "name", "prompt", "read_roots", "write_roots",
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

_LOG_RE = re.compile(r"^- \*\*(?P<ts>[^*]+)\*\* — (?P<status>\w+)")


def log_path(routine_id):
    return log_dir() / f"{routine_id}.md"


def append_log(routine_id, status, detail="", touched=()):
    """Record one run. `status` is 'ok' or 'failed'.

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
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"- **{ts}** — {status}"
    if detail:
        line += f" — {detail.strip()}"
    if touched:
        names = ", ".join(Path(t).name for t in touched)
        plural = "" if len(touched) == 1 else "s"
        line += f" — wrote {len(touched)} file{plural}: {names}"

    head = f"# Run log — {routine_id}\n\n" if not path.exists() else ""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(existing + head + line + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def last_run(routine_id):
    """(status, timestamp) of the most recent run, or (None, None).

    This is what on_failure is decided against, so it reads the file rather
    than any in-memory state — a scheduled run is a fresh process.
    """
    path = log_path(routine_id)
    if not path.exists():
        return None, None
    match = None
    for line in path.read_text(encoding="utf-8").splitlines():
        m = _LOG_RE.match(line.strip())
        if m:
            match = m
    if not match:
        return None, None
    return match.group("status"), match.group("ts")
