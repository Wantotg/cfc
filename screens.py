# screens.py — the command-screen controller: config, wiki, routines.
#
# A screen is a small REPL of its own, entered from a chat (bare /config,
# /wiki, /routine) or from another screen (typing config/wiki/routine). The
# boundary the whole feature exists for:
#
#   Ordinary text becomes a model message only at a chat prompt. On a command
#   screen, every submitted line is either a recognised action or a visible
#   refusal.
#
# So `_classify()` below has exactly three outcomes — blank, recognised,
# invalid — and the invalid branch never touches history, never calls an API.
# `enter()` is the only thing that owns a terminal loop; every screen action
# below it is a handler called from that one loop, the same pure-core/shell
# split `resolve_model`/`select_model` and `gate`/`gate_and_dispatch` already
# use elsewhere in this codebase.
#
# The three screens share one navigation vocabulary (help, q/quit/back,
# config, wiki, routine) and one rule: **the command table is the only source
# for both dispatch and generated help.** A table is rebuilt fresh every time
# a screen is (re-)entered, which is what makes per-visit state (the wiki
# review, below) reset on every visit without anyone having to remember to
# clear it.
#
# Nothing here reimplements what commands.py, wikigit.py, routines.py or
# preflight.py already do — a screen calls those and renders the result.
import datetime

from rich.table import Table as RichTable
from rich.text import Text

from ui import console, read_input

TO_HUB = object()


def _switch(name):
    return ("switch", name)


class ScreenTable:
    """One screen's command table. `entries` is
    [(name, aliases, help_text, handler)], in the order help prints them.
    `handler(rest, conn, table)` returns:

        None                  stay, no redraw (the command already printed)
        TO_HUB                leave to the session picker
        ("switch", mode)      leave to another screen
        ("transcript", sid)   leave, opening a persisted routine session

    `phrase_aliases` maps a lowercase two-word phrase to a canonical verb —
    the wiki screen's `show diff` / `inspect diff` / `review diff`, which
    can't be expressed as a single-token alias. `state` is a scratch dict a
    screen's own handlers use for anything that must live only for this
    visit (the wiki screen's transient review, below).
    """

    def __init__(self, mode, entries, phrase_aliases=None, chat_model=None):
        self.mode = mode
        self.entries = entries
        self.phrase_aliases = phrase_aliases or {}
        self.dispatch = {}
        for name, aliases, _help, handler in entries:
            self.dispatch[name] = handler
            for a in aliases:
                self.dispatch[a] = handler
        self.state = {}
        # The model of the chat this screen was entered from — `None` when
        # entered straight from the hub, where there is no chat model to
        # carry (`B-05`). Kept on the table itself, not in `state`, because
        # it must survive a screen switch, which rebuilds `state` fresh but
        # is handed this same value again — see `enter()`.
        self.chat_model = chat_model


def classify(table, line):
    """('blank', None) | ('ok', (handler, rest)) | ('bad', stripped_line).

    Exactly the three outcomes the design requires. A leading '/' is
    stripped (one, not repeatedly — chat muscle memory is harmless, and '//x'
    is still not a command). Verb words are matched case-insensitively;
    `rest` is handed back exactly as typed, so a routine name, a path or a
    commit message keeps its case and its spacing. A multi-line paste is one
    `line` here regardless of how it reached this function, so it is
    classified once, as a whole — never split into several commands.
    """
    stripped = (line or "").strip()
    if stripped.startswith("/"):
        stripped = stripped[1:].strip()
    if not stripped:
        return "blank", None
    low = stripped.lower()
    for phrase, canon in table.phrase_aliases.items():
        if low == phrase or low.startswith(phrase + " "):
            rest = stripped[len(phrase):].strip()
            return "ok", (table.dispatch[canon], rest)
    verb, _, rest = stripped.partition(" ")
    handler = table.dispatch.get(verb.lower())
    if handler is None:
        return "bad", stripped
    return "ok", (handler, rest.strip())


def _print_help(table):
    console.print()
    console.print(f"{table.mode} commands", style="bold")
    width = max(len(name) for name, *_ in table.entries) + 2
    for name, _aliases, help_text, _handler in table.entries:
        line = Text(f"  {name:<{width}}", style="cyan")
        line.append(help_text, style="dim")
        console.print(line)
    console.print()


def _h_help(rest, conn, table):
    _print_help(table)


def _h_leave(rest, conn, table):
    return TO_HUB


def _nav_entries(mode):
    """help / q / config / wiki / routine — every table gets these, minus
    the switch-to-self entry (there's no reason to switch to where you are)."""
    entries = [
        ("help", (), "this screen's commands", _h_help),
        ("q", ("quit", "back"), "back to the session picker", _h_leave),
    ]
    for target in ("config", "wiki", "routine"):
        if target != mode:
            entries.append((
                target, (), f"switch to the {target} screen",
                (lambda t: (lambda rest, conn, table: _switch(t)))(target)))
    return entries


def _title(mode):
    return {"config": "cooking for cats: config",
            "wiki": "cooking for cats: wiki",
            "routine": "cooking for cats: routines"}[mode]


def _print_title(mode):
    console.print()
    console.print(Text(_title(mode), justify="center", style="bold"))
    console.print()


# --- config screen -----------------------------------------------------


def _config_row(label, value):
    line = Text(f"{label:<18}", style="bold")
    if isinstance(value, Text):
        line.append(value)
    else:
        line.append(str(value))
    console.print(line)


def _wiki_attention():
    """(count, error) — total changed paths across the vault, or (None,
    reason) if the corpus can't be read. Never raises: a broken WIKI_DIR
    must not blank the rest of the config screen."""
    import wikigit
    try:
        wiki, other = wikigit.summary()
    except wikigit.GitError as e:
        return None, str(e)
    return len(wiki) + len(other), None


def _routine_attention():
    """(count, breakdown) — distinct routines needing attention, and the
    reasons why, or (None, reason) if the store can't be read.

    Count is of *routines*, not of reasons: one routine flagged for two
    reasons is one routine, not two alarming arithmetic events. The
    breakdown may still sum past the count for exactly that reason.
    """
    from routines import list_routines, last_run
    try:
        good, bad = list_routines()
    except Exception as e:                       # noqa: BLE001
        return None, str(e)

    reasons = {"invalid": 0, "failed": 0, "flagged": 0, "due": 0}
    attended = len(bad)
    reasons["invalid"] += len(bad)

    now = datetime.datetime.now()
    for r in good:
        hit = False
        if r.validate():
            reasons["invalid"] += 1
            hit = True
        status, _ts, review = last_run(r.id)
        if status == "failed":
            reasons["failed"] += 1
            hit = True
        if review:
            reasons["flagged"] += 1
            hit = True
        try:
            from schedule import why_not_due
            if why_not_due(r, now) is None:
                reasons["due"] += 1
                hit = True
        except Exception:                        # noqa: BLE001
            pass
        if hit:
            attended += 1

    parts = [f"{n} {label}" for label, n in
             (("invalid", reasons["invalid"]), ("failed", reasons["failed"]),
              ("flagged", reasons["flagged"]), ("due", reasons["due"])) if n]
    return attended, ", ".join(parts)


def _render_config():
    import config as _config
    import preflight
    from backfill import wiki_stale
    from db import DB_PATH
    from export import chat_export_dir
    from ui import connection_light

    model = getattr(_config, "MODEL", "") or "(not set)"
    api_base = getattr(_config, "API_BASE", "")
    api_key = getattr(_config, "API_KEY", "")
    vault_root = (getattr(_config, "VAULT_ROOT", "") or "").strip()
    vault_path = chat_export_dir().strip()
    embed_model = getattr(_config, "EMBED_MODEL", "")

    _config_row("Chat default", model)
    _config_row("Chat API", f"{api_base} · "
                f"{'key set' if api_key else 'key not set'}")

    # Evaluated live, every time — decision 16: this row renders
    # preflight.connection_state() and forms no opinion of its own.
    state, _detail = preflight.connection_state()
    mark, style, text = connection_light(state)
    embed_line = Text()
    embed_line.append(mark, style=style)
    embed_line.append(f" {text} · {embed_model}" if state == "connected"
                      else f" {text}")
    _config_row("Embedding", embed_line)

    # A false marker is 'no update flagged', never 'current' — absence of the
    # flag is not proof the filesystem, imported messages, chunks and vectors
    # agree; edits made outside cfc never set it.
    _config_row("Wiki import",
                "update required" if wiki_stale() else "no update flagged")
    _config_row("Database", str(DB_PATH))
    _config_row("Vault", vault_root or "not configured")
    _config_row("Export", vault_path or "not configured")

    console.print()
    n, detail = _wiki_attention()
    if n is None:
        _config_row("Wiki", f"unavailable — {detail}")
    elif n == 0:
        _config_row("Wiki", "clean · open with: wiki")
    else:
        _config_row("Wiki", f"{n} uncommitted change{'' if n == 1 else 's'} "
                    "· open with: wiki")

    n, detail = _routine_attention()
    if n is None:
        _config_row("Routines", f"unavailable — {detail}")
    elif n == 0:
        _config_row("Routines", "nothing needs attention · open with: routine")
    else:
        verb = "needs" if n == 1 else "need"
        _config_row("Routines", f"{n} {verb} attention: {detail} · "
                    "open with: routine")


def _path_line(label, value):
    line = Text(f"  {label:<22}", style="cyan")
    line.append(str(value) if value else "not configured", style="dim")
    console.print(line)


def _render_config_paths():
    import commands as _commands
    import config as _config
    from db import DB_PATH
    from export import chat_export_dir
    from mover import loser_dir, move_roots
    from notes import archive_dir, notes_dir
    from pools import pool_dir
    from routines import log_dir, prompt_dir, routine_dir
    from wikigit import journal_dir, wiki_dir

    def raw(key):
        return (getattr(_config, key, "") or "").strip()

    console.print("Paths", style="bold")
    _path_line("Database", DB_PATH)
    _path_line("Vault root", raw("VAULT_ROOT"))
    _path_line("Chat export", chat_export_dir())
    _path_line("Prompts", pool_dir("prompt"))
    _path_line("Personas", pool_dir("persona"))
    _path_line("Traits", pool_dir("trait"))
    _path_line("Wiki", wiki_dir() if raw("WIKI_DIR") else "")
    _path_line("Journal", journal_dir() if raw("JOURNAL_DIR") else "")
    _path_line("Routine definitions",
              routine_dir() if raw("ROUTINE_DIR") else "")
    _path_line("Routine prompts",
              prompt_dir() if raw("ROUTINE_PROMPT_DIR") else "")
    _path_line("Routine logs", log_dir() if raw("ROUTINE_LOG_DIR") else "")
    _path_line("Notes inbox", notes_dir() or "")
    _path_line("Notes archive", archive_dir() or "")
    _path_line("Attach/read roots",
              ", ".join(str(r) for r in _commands.ATTACH_ROOTS))
    _path_line("Write root",
              ", ".join(str(r) for r in _commands.WRITE_ROOTS))
    _path_line("Move roots", ", ".join(str(r) for r in move_roots()))
    _path_line("Loser directory", loser_dir() or "")
    console.print()


def _config_refresh(rest, conn, table):
    _print_title("config")
    _render_config()


def _config_connect(rest, conn, table):
    if rest.strip().lower() != "embedding":
        console.print("Usage: connect embedding", style="dim")
        return
    import commands as _commands
    console.print()
    _commands.connect_embedding()
    console.print()
    _render_config()


def _config_paths(rest, conn, table):
    console.print()
    _render_config_paths()


def _config_entries():
    return [
        ("refresh", (), "re-evaluate this screen", _config_refresh),
        ("connect", (), "connect embedding — run the connection flow, "
         "then redraw", _config_connect),
        ("paths", (), "the complete effective path inventory", _config_paths),
    ]


# --- wiki screen ---------------------------------------------------------
#
# The wiki screen does not invent a queue or an approval database — git's
# current changes are the work, so every command here calls straight into
# wikigit.py / commands.py's existing wiki functions. The only thing new is
# the transient per-visit review, armed by a successful diff and re-checked
# on the way out (`_leave_ok` in enter(), below).

PHRASE_ALIASES = {
    "show diff": "diff", "inspect diff": "diff", "review diff": "diff",
}


# `lead=""` on every call into commands.py: those functions print suggested
# command lines, and here the command is `diff`, not `/wiki diff`. See the note
# above `commands.show_wiki_status`.
def _wiki_status(rest, conn, table):
    import commands as _commands
    _commands.show_wiki_status(lead="")


def _wiki_diff(rest, conn, table):
    import commands as _commands
    import wikigit
    scope, _gran, _msg = _commands._parse_wiki_args(rest)
    _commands.show_wiki_diff(rest, lead="")
    # A successful diff arms the review for this scope; a failed one (a
    # GitError, already reported by show_wiki_diff) must not.
    try:
        changes = wikigit.status(scope)
        table.state["wiki_review"] = {"scope": scope,
                                      "paths": {c.path for c in changes}}
    except wikigit.GitError:
        table.state.pop("wiki_review", None)


def _wiki_commit(rest, conn, table):
    import commands as _commands
    import wikigit
    scope, _gran, _msg = _commands._parse_wiki_args(rest)
    _commands.do_wiki_commit(rest, lead="")
    # The review is resolved only if THIS scope now has no changes — a
    # partial or differently-scoped commit leaves it armed, to be re-checked
    # as "changed since the diff" on the way out.
    review = table.state.get("wiki_review")
    if review and review["scope"] == scope:
        try:
            if not wikigit.status(scope):
                table.state.pop("wiki_review", None)
        except wikigit.GitError:
            pass


def _wiki_entries():
    return [
        ("status", (), "the vault repo summary", _wiki_status),
        ("diff", (), "diff [wiki|journal|vault] [file] — the diff for a "
         "scope", _wiki_diff),
        ("commit", (), "commit [wiki|journal|vault] [file] <message>",
         _wiki_commit),
    ]


# --- routines screen -------------------------------------------------------

_ROUTINES_WIDE_MIN = 110    # below this: labelled blocks, not a table


def _routines_narrow():
    return console.size.width < _ROUTINES_WIDE_MIN


def _routine_row(r, problems, status, ts, review):
    return {
        "name": f"! {r.name}" if problems else r.name,
        "model": r.model or "(default)",
        "trigger": str(r.trigger),
        "write": "yes" if r.write_roots else "no",
        "loop": status or "never",
        "flag": "yes" if review else "no",
        # Seconds are dropped here (kept in show/history) and the year
        # always stays, so a run near a year boundary can't read as six
        # days old.
        "last": ts[:16] if ts else "never",
    }


def _render_routines_wide(rows):
    t = RichTable(show_header=True, header_style="bold", box=None,
                 padding=(0, 2, 0, 0))
    for col in ("Routine", "Model", "Trigger", "Write", "Loop", "Flag",
                "Last run"):
        t.add_column(col, overflow="fold")
    for row in rows:
        t.add_row(row["name"], row["model"], row["trigger"], row["write"],
                  row["loop"], row["flag"], row["last"])
    console.print(t)


def _render_routines_narrow(rows):
    for row in rows:
        console.print(row["name"])
        console.print(f"  model    {row['model']}")
        console.print(f"  trigger  {row['trigger']}")
        console.print(f"  write    {row['write']}")
        console.print(f"  loop     {row['loop']}")
        console.print(f"  flag     {row['flag']}")
        console.print(f"  last     {row['last']}")
        console.print()


def _render_routines(conn):
    from routines import list_routines, last_run

    try:
        good, bad = list_routines()
    except Exception as e:                        # noqa: BLE001
        console.print(f"Cannot read routines: {e}", style="red")
        return

    if not good and not bad:
        console.print("(none yet — 'new' to make one)", style="dim")
        return

    rows, problems_by_id = [], {}
    for r in good:
        problems = r.validate()
        problems_by_id[r.id] = problems
        status, ts, review = last_run(r.id)
        rows.append(_routine_row(r, problems, status, ts, review))

    if rows:
        (_render_routines_narrow if _routines_narrow()
         else _render_routines_wide)(rows)

    for r in good:
        for why in problems_by_id[r.id]:
            console.print(f"  ! {r.name}: {why}", style="red")
    # Malformed files are listed, not swallowed — the file most likely to be
    # the one you came here about.
    for name, why in bad:
        console.print(f"  ! {name}: {why}", style="red")


def _routine_show(rest, conn, table):
    from routines import RoutineError, last_run, load_routine
    name = rest.strip()
    if not name:
        console.print("Usage: show <routine>", style="dim")
        return
    try:
        r = load_routine(name)
    except RoutineError as e:
        console.print(f"  {e}", style="red")
        return
    console.print()
    console.print(r.name, style="bold")
    console.print(f"  id            {r.id}")
    console.print(f"  enabled       {'yes' if r.enabled else 'no'}")
    console.print(f"  model         {r.model or '(default)'}")
    console.print(f"  prompt        {r.prompt}")
    console.print(f"  trigger       {r.trigger}")
    console.print(f"  on_failure    {r.on_failure}")
    console.print(f"  read roots    {', '.join(r.read_roots) or '(none)'}")
    console.print(f"  write roots   {', '.join(r.write_roots) or '(none)'}")
    problems = r.validate()
    if problems:
        for why in problems:
            console.print(f"  ! {why}", style="red")
    else:
        console.print("  valid", style="green")
    status, ts, review = last_run(r.id)
    if status:
        console.print(f"  last run      {status}{' (review)' if review else ''}"
                      f" {ts}")
    else:
        console.print("  last run      never")
    console.print()


def _routine_history(rest, conn, table):
    from routines import RoutineError, load_routine, read_log
    name = rest.strip()
    if not name:
        console.print("Usage: history <routine>", style="dim")
        return
    try:
        r = load_routine(name)
    except RoutineError as e:
        console.print(f"  {e}", style="red")
        return
    records = list(reversed(read_log(r.id)))
    console.print()
    if not records:
        console.print(f"  no runs recorded for {r.id}", style="dim")
        console.print()
        return
    console.print(f"{r.name} — run history, newest first", style="bold")
    for rec in records:
        flag = " (review)" if rec.review else ""
        sid = f"session #{rec.session_id}" if rec.session_id is not None else "—"
        console.print(f"  {rec.timestamp}  {rec.status}{flag}  {sid}")
        if rec.detail:
            console.print(f"    {rec.detail}")
        if rec.touched:
            console.print(f"    wrote: {rec.touched}")
    console.print()


def _routine_open(rest, conn, table):
    from db import routine_session
    token = rest.strip()
    if not token.lstrip("-").isdigit():
        console.print("Usage: open <session id>", style="dim")
        return
    sid = int(token)
    if routine_session(conn, sid) is None:
        console.print(f"  no routine transcript at session #{sid} — "
                      f"see 'history <routine>' for valid ids", style="red")
        return
    return ("transcript", sid)


def _routine_run(rest, conn, table):
    import commands as _commands
    name = rest.strip()
    if not name:
        console.print("Usage: run <routine>", style="dim")
        return
    # `B-05`: an unpinned routine run from here used to fall through to
    # `runner.default_routine_model()` because nothing passed a model at
    # all, silently running on a different model than `/routine <name>`
    # from the chat that opened this screen would have used. `table.chat_model`
    # is that chat's model (None if this screen was opened straight from the
    # hub); a routine's own `model:` pin still wins inside `do_routine`.
    _commands.do_routine(conn, name, model=table.chat_model)


def _routine_new(rest, conn, table):
    import commands as _commands
    _commands.create_routine(return_to="routines")


def _routine_refresh(rest, conn, table):
    _print_title("routine")
    _render_routines(conn)


def _routine_entries():
    return [
        ("show", (), "show <routine> — the complete routine", _routine_show),
        ("history", (), "history <routine> — recent runs", _routine_history),
        ("open", (), "open <session id> — a run's transcript", _routine_open),
        ("run", (), "run <routine> — run it now", _routine_run),
        ("new", (), "create a routine", _routine_new),
        ("refresh", (), "re-evaluate this screen", _routine_refresh),
    ]


# --- the shared loop --------------------------------------------------------


def _leave_ok(table, destination):
    """True if it is safe to leave `table`'s screen right now.

    Only the wiki screen ever populates `table.state["wiki_review"]`; every
    other table's check is a no-op, so this can be called unconditionally on
    every exit route — q/quit/back, EOF, a screen switch, or opening a
    transcript — without a special case per route.
    """
    review = table.state.get("wiki_review")
    if not review:
        return True
    import wikigit
    try:
        current = {c.path for c in wikigit.status(review["scope"])}
    except wikigit.GitError:
        return True   # can't check — a transient git failure must not trap you
    if not current:
        table.state.pop("wiki_review", None)
        return True
    if current != review["paths"]:
        lead = "Reviewed wiki changes have changed since the diff."
    else:
        n = len(current)
        lead = (f"{n} reviewed wiki change{'' if n == 1 else 's'} are "
                f"still uncommitted.")
    try:
        ans = input(f"{lead} Leave them for later and return to "
                    f"{destination}? (y/n) ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return False
    return ans in ("y", "yes")


def build_table(mode, chat_model=None):
    if mode == "config":
        return ScreenTable("config", _config_entries() + _nav_entries("config"),
                           chat_model=chat_model)
    if mode == "wiki":
        return ScreenTable("wiki", _wiki_entries() + _nav_entries("wiki"),
                           phrase_aliases=PHRASE_ALIASES, chat_model=chat_model)
    if mode == "routine":
        return ScreenTable("routine",
                           _routine_entries() + _nav_entries("routine"),
                           chat_model=chat_model)
    raise ValueError(f"unknown screen: {mode!r}")


def render(table, conn):
    _print_title(table.mode)
    if table.mode == "config":
        _render_config()
    elif table.mode == "wiki":
        import commands as _commands
        _commands.show_wiki_status(lead="")
    elif table.mode == "routine":
        _render_routines(conn)
    # Said once, on the way in — the same pointer the "not a command" refusal
    # already gives, so entering clean and mistyping the first line no longer
    # teach two different things (`W-1.2.1-02`).
    console.print()
    console.print("Type help to see what works here.", style="dim")


def enter(conn, mode="config", chat_model=None):
    """Run the screen controller. Returns None (leave to the session picker)
    or a session id (open that persisted routine transcript as an ordinary
    chat).

    One loop, one current screen — switching replaces `table` rather than
    calling `enter()` again, which is what keeps "config -> wiki -> routine
    -> q" from either recursing or reopening the chat that launched it.

    `chat_model` is the model of the chat this screen was entered from (or
    `None` from the hub); it rides on every `table` a switch builds so the
    routines screen's `run <routine>` resolves like `/routine <name>` would
    have, and survives navigating between screens (`B-05`).
    """
    table = build_table(mode, chat_model=chat_model)
    render(table, conn)
    while True:
        try:
            line = read_input(f"{table.mode}> ")
        except EOFError:
            console.print()
            if _leave_ok(table, "the session picker"):
                return None
            continue

        outcome, payload = classify(table, line)
        if outcome == "blank":
            continue
        if outcome == "bad":
            console.print(f"Not a {table.mode} command: {payload}")
            console.print("Type help to see what works here.", style="dim")
            continue

        handler, rest = payload
        result = handler(rest, conn, table)

        if result is None:
            continue
        if result is TO_HUB:
            if _leave_ok(table, "the session picker"):
                return None
            continue
        kind, value = result
        if kind == "switch":
            if _leave_ok(table, f"the {value} screen"):
                table = build_table(value, chat_model=chat_model)
                render(table, conn)
            continue
        if kind == "transcript":
            if _leave_ok(table, "the routine transcript"):
                return value
            continue
