# main.py — the REPL: dispatch and the session state the commands act on.
#
# This file owns the loop and the eight pieces of live state a session has
# (history, injected excerpts, title, model, system prompt, persona). The ':'
# commands live in commands.py; everything here is deciding which one to call
# and what to do with the result.
#
#     python3 main.py [session_id]
import sys
from itertools import takewhile

import httpx

try:
    import readline  # noqa: F401 — activates line editing for input()
except ImportError:
    pass

from config import MODEL, AUTO_EXPORT
import models

try:
    from config import TOOLS_ENABLED
except ImportError:
    TOOLS_ENABLED = False
try:
    # The default database state for a *private* chat. A normal chat always
    # starts with the db on (recall is a core feature); a private chat starts
    # from this, defaulting off so memory is sealed unless asked for. Absent
    # from config → off, so an old config keeps a private chat maximally sealed.
    from config import DATABASE_ACTIVE
except ImportError:
    DATABASE_ACTIVE = False

from splash import splash
from rich.text import Text

from parse import parse, looks_like_path, VERBS, PREFIX
from assemble import assemble_system
from pools import bodies as pool_bodies, pool as pool_of, stem

from ui import console, human_panel, read_input, set_completer
# `db` is both the module and its connect function; main.py wants the
# function, so import the names directly rather than the module.
from db import (
    db, new_session, save_message, load_history,
    get_context_info,
    get_session_title, set_session_title,
    get_session_model, set_session_model,
    add_tag, remove_tag,
    get_system_prompt, get_system_prompt_name,
    set_system_prompt, clear_system_prompt,
    get_persona, get_persona_name, set_persona, clear_persona,
    get_traits, set_traits,
    delete_session,
)
from agent import agent_turn, render_answer, tools_guidance
from context import chat_context
from api import (stream_response, generate_title, is_transient_status,
                 EMPTY_COMPLETION_RETRIES)
from backup import safe_backup
import errorlog
import screens
from complete import install as install_completion, make_completer
from export import export_session, safe_export
from hub import list_sessions, pick_session
from commands import (
    show_tags, list_all_tags,
    list_prompts, load_prompt_file, list_personas, load_persona_file,
    list_models, select_model, known_models, model_by_number,
    show_token_stats,
    context_bar, print_context_bar,
    search_messages,
    do_recall, do_remember, do_forget,
    do_updatedb, auto_embed,
    do_attach, show_attachments, do_detach,
    show_tools_state, show_status, show_list, tools_unsupported_reason,
    resolve_layer, resolve_attached, load_pool_file,
    create_routine, do_routine,
    show_outbox, do_file, do_move, do_clear,
    show_wiki_diff, do_wiki_commit,
    connect_embedding, connect_status, empty_completion_decision,
    print_session_header, print_core_commands, print_help,
)

# --- Main REPL ---


def _one_line(text, width=60):
    """Squash a tool result to a single short line for the replay."""
    flat = " ".join((text or "").split())
    return flat[:width] + ("..." if len(flat) > width else "")


_DB_OFF = ("Database is off for this chat — /database on to enable "
           "/recall and /remember.")

# What a command handler returns to leave the session. A nested handler can't
# `break` the loop it lives in; a sentinel makes the exit visible at the call
# site instead of hiding it behind a mutable flag nobody remembers to reset.
_LEAVE = object()


# What run_session() hands back to repl(): either None (the plain "back to
# the hub" it always meant) or an _Open naming a session to open next without
# going through the picker — a routine transcript a screen requested. One
# shape rather than a bare int, because the *next* run_session() call needs
# to know whether to label that session as a routine transcript, and that
# fact has to survive the hop between two separate calls, not just one.
class _Open:
    __slots__ = ("session_id", "routine_transcript")

    def __init__(self, session_id, routine_transcript=False):
        self.session_id = session_id
        self.routine_transcript = routine_transcript


def repl(session_id=None):
    """Outer driver: the hub, and the session you return to it from.

    A session never exits the program. `/q` (and EOF / Ctrl-C) drop back to the
    hub — the exact screen you started on. The program quits only from the hub,
    with `q`. A `session_id` from `main.py 5` still returns to the hub on `/q`,
    so the hub is the one way out.

    A screen (config/wiki/routines, see screens.py) is entered from inside a
    session and, like a session, has exactly one way out: back to the hub, or
    — for the routines screen's `open <id>` — a persisted routine transcript.
    `run_session()`'s return value carries that; this loop is what turns an
    `_Open` into the next `run_session()` call, so a screen never has to call
    `run_session()` itself.
    """
    conn = db()
    # Two completion front ends for two readers: prompt_toolkit on a real
    # terminal, readline behind the input() fallback. See complete.py — the
    # readline one silently stopped running when the editor landed.
    install_completion()
    set_completer(make_completer())

    transcript = False
    while True:
        if session_id is None:
            transcript = False
            try:
                result = pick_session(conn)
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            if result == "quit":
                break
            if result == "private":
                # A private chat runs against an isolated in-memory database:
                # every conn-driven write (messages, titles, agent_turn's own
                # saves) lands there and is gone the moment we close it. Nothing
                # touches ~/.cfc/chat.db. See run_session(private=True) for the
                # two paths that escape the connection (auto-embed, auto-export).
                #
                # `app_conn=conn` is what lets a screen opened *from* this
                # private chat reach durable, global state — the screen
                # controller never sees the private connection at all.
                priv = db(":memory:")
                try:
                    outcome = run_session(priv, new_session(priv),
                                          private=True, app_conn=conn)
                finally:
                    priv.close()
                if outcome is None:
                    continue    # session_id is still None → back to the hub
                session_id = outcome.session_id
                transcript = outcome.routine_transcript
                # Falls through to the ordinary run_session() call below,
                # opening what the private chat's screen asked for.
            else:
                session_id = result if result is not None \
                    else new_session(conn)

        outcome = run_session(conn, session_id, routine_transcript=transcript)
        if outcome is None:
            session_id = None
        else:
            session_id, transcript = outcome.session_id, outcome.routine_transcript

    conn.close()


def run_session(conn, session_id, private=False, app_conn=None,
                routine_transcript=False):
    """One session's REPL loop. Returns None (repl() reads that as 'back to
    the hub') or an `_Open` naming the session to open next.

    `private` is not a per-call-site switch — the isolation is structural, in
    the in-memory `conn` repl() hands us, so every DB write is already a no-op
    against disk. It gates only the two paths that *escape* the connection:
    auto-embed (reads the real db by hardcoded path) and auto-export (writes a
    file). Automatic persistence is off; an explicit `/export` is still honoured
    — the contract is 'nothing is written down unless you ask for it by name'.

    `app_conn` is the durable, on-disk connection — always `conn` itself for
    an ordinary session, but explicitly the real database when this call
    *is* a private chat's throwaway `conn`. A command screen entered from a
    private chat (bare `/config`, `/wiki`, `/routine`) is handed `app_conn`,
    never `conn`, so it reads and writes global state and never the private
    connection or its history.

    `routine_transcript` labels this session, in its header only, as a run a
    routine already made — the routines screen's `open <id>` opens one of
    these as an ordinary chat, and the label is what stops the first line
    typed there reading as an unrelated new conversation.
    """
    app_conn = conn if app_conn is None else app_conn
    outcome = None
    history = load_history(conn, session_id)
    # Built once per session: `interactive` reports whether stdin is a
    # terminal, which is what the empty-completion handler consults before it
    # asks anyone anything.
    chat_ctx = chat_context(private=private)
    injected = []          # blocks added by /remember, newest last
    # Turns cancelled in this session. `BUGS.md` asks whether anything was
    # interrupted when a provider 400 fires — the surviving theory for that bug
    # is an interrupt mid-batch — and nothing tracked it before. Counted rather
    # than flagged: same cost, and "three" and "one" are not the same finding.
    # Only *turn* interrupts count; a cancelled memory search never reached the
    # provider, so including it would dilute the one signal this exists for.
    turns_interrupted = 0
    tools_on = True        # session toggle; the master switch still gates it
    # Whether /recall, /remember or /updatedb may reach the wiki this session. A
    # normal chat: on. A private chat: DATABASE_ACTIVE (default off), so memory
    # is sealed unless you type /database on. This is the *read* axis and is
    # separate from privacy, which is about the write paths — a private chat
    # never persists regardless of this flag.
    db_on = True if not private else DATABASE_ACTIVE
    current_title = get_session_title(conn, session_id)
    current_model = get_session_model(conn, session_id)
    # Auto-revert arming. Non-None ⇒ the current model was set by a switch and
    # has not yet completed a turn, so a turn that errors on it needs a
    # decision: a status-coded transient (429/502/503/504) says the provider
    # was temporarily unavailable, not that the selected id is dead, so it
    # leaves this armed and prints the ordinary error; anything else — a
    # rejection, or an error with no transient status — is almost certainly
    # "no such model", and backs out to this remembered model rather than
    # stranding the session on a dead id. A turn that returns without an HTTP
    # error disarms it (the model is real). This holds for both chats — it's
    # the same dispatch, and a private chat's throwaway db takes the revert the
    # same way, persisting nothing real either way.
    revert_model = None
    # Every model id the provider has refused with a 400 in this chat
    # (`B-1.2-04`). `revert_bad_model()` reads it before backing out to
    # `revert_model` — the fallback earning its own place in this set is
    # exactly what "switched back to X" used to claim as a recovery while
    # the *previous* turn's error log said X had already been refused. A
    # plain `set()`, never persisted: it lives exactly as long as
    # `revert_model` does, for the same reason — this chat only, and a
    # private chat's throwaway connection carries it the same way everything
    # else in-memory here is carried.
    rejected_models = set()
    system_prompt = get_system_prompt(conn, session_id)
    system_prompt_name = get_system_prompt_name(
        conn, session_id
    )
    persona = get_persona(conn, session_id)
    persona_name = get_persona_name(conn, session_id)
    # Names, not bodies: the bodies are re-read from the pool on every turn, so
    # editing a trait file updates every session carrying its name. See
    # db.get_traits.
    trait_names = get_traits(conn, session_id)

    print_session_header(conn, session_id, current_model, current_title,
                         system_prompt_name, persona_name, private=private,
                         trait_names=trait_names)
    if routine_transcript:
        # State it, don't warn it — same voice as the private-chat notice
        # below, and for the same reason: the label is the only thing that
        # stops a free-text message here reading as an ordinary new chat.
        console.print(Text.from_markup(
            "[bold]Routine transcript[/] — this is the session a routine "
            "run wrote. Typing here sends an ordinary chat message; it "
            "does not run the routine again.",
            style="cyan"))
    if private:
        # State it, don't warn it — this is a fact about the session, in the
        # same voice as the header. It is the user's only signal that the usual
        # persistence is off, so it says exactly what is and isn't kept.
        # The shared console is markup=False (invariant #4), so a "[bold]…[/]"
        # string prints literally. Build a styled Text via from_markup instead —
        # the same discipline the panel helpers use.
        console.print(Text.from_markup(
            "[bold]Private chat[/] — nothing here is written down. No "
            "transcript, no\nmemory index, no auto-export, and it won't "
            "appear in the hub. Closing it\n(/q, Ctrl-D, or quitting) ends "
            "it for good; there is no restore. Model file\nwrites are "
            "blocked; an explicit [bold]/export[/] is the one thing that "
            "reaches disk,\nand only because you asked for it by name.",
            style="cyan",
        ))
        if db_on:
            console.print(
                "The wiki database is on: /recall and /remember work here. "
                "/database off to seal it.", style="cyan")
        else:
            console.print(
                "The wiki database is off: /recall and /remember are "
                "disabled. /database on to\nenable them (change the default "
                "with DATABASE_ACTIVE in config).", style="cyan")
        console.print()
    print_core_commands()

    if history:
        console.print("--- Previous messages in this session "
                      "---")
        for m in history:
            # Tool rows replay too, but raw: a tool result is a JSON blob and
            # a tool call has empty content, so printing them as "ai> ..."
            # dumps machine chatter at someone catching up on a conversation.
            if m.get("role") == "tool":
                console.print(f"     [tool result: "
                              f"{_one_line(m.get('content'))}]\n")
                continue
            if m.get("tool_calls"):
                for c in m["tool_calls"]:
                    console.print(f"     [called "
                                  f"{c.get('function', {}).get('name')}]")
                if not (m.get("content") or "").strip():
                    continue
            label = "you" if m["role"] == "user" else "ai"
            console.print(f"{label}> {m['content']}\n")
        console.print("--- End of history ---\n")

    def revert_bad_model():
        """Back out to the model we were on before the just-armed switch, and
        say so, instead of leaving the session stranded on a dead id. Returns
        True if it acted — including the refusal below, which counts as
        "acted" for the caller's purposes (it must not also print the raw
        provider error). Idempotent: disarms itself either way, so a later
        transient error prints normally — the arming a caller must check
        first, since a transient right after a switch is handled by
        `handle_turn_error` without ever reaching here.

        `B-1.2-04`: if the fallback itself is in `rejected_models` — this
        chat already had it 400 the provider — reverting to it would trade
        one dead id for another already proven dead, and say so as a
        recovery. Disarm instead, leave `current_model` selected (it is
        itself the id that was just rejected, by the caller's own 400), and
        say plainly that neither is known-good. `/model` is the only way
        out cfc can offer; it does not guess a third id.
        """
        nonlocal current_model, revert_model
        if not revert_model:
            return False
        if revert_model in rejected_models:
            bad_prev, revert_model = revert_model, None
            console.print(f"\n[error] {current_model} was rejected too — "
                          f"both it and {bad_prev} have already been refused "
                          f"by the provider this session. Neither is "
                          f"known-good; pick a different model with "
                          f"{PREFIX}model.\n")
            return True
        bad, current_model, revert_model = current_model, revert_model, None
        set_session_model(conn, session_id, current_model)
        console.print(f"\n[error] provider rejected '{bad}' — switched back to "
                      f"{current_model}\n")
        return True

    def handle_turn_error(e):
        """What both turn paths do with an HTTP error: record it, then decide
        how to render it. In that order, and the order is the fix.

        `revert_bad_model()` prints `provider rejected 'X' — switched back to Y`
        **instead of** the provider's words, so before this existed the one
        error line `BUGS.md` asks to be captured was discarded exactly when a
        model switch preceded it — and "I switched model and the next turn
        400ed" is an ordinary session, not an exotic one. Two things that are
        each correct alone; the log records what happened and the console
        decides what to show, and neither reads the other.

        One function called from both `except httpx.HTTPError` sites rather
        than two `log_error(e)` calls: standing decision 7 exists because these
        two paths drifted once already, and a hand-placed pair is that drift
        pre-made.

        A status-coded transient (`api.is_transient_status`) on an armed
        switch's first turn is deliberately not a revert: 429/502/503/504 say
        the provider was briefly unavailable, not that the id itself is bad, so
        `revert_model` stays armed for a later, non-transient failure and this
        prints the ordinary provider error instead of the switched-back-to-Y
        line. Anything else — a rejection, or an error with no transient status
        — still reverts as before.

        **`rejected_models` is recorded here, before any of that** (`B-1.2-04`):
        exactly HTTP 400, never a transient or a transport failure with no
        status at all — a 400 is the provider naming this id unsupported, and
        anything else is not evidence the id itself is bad. Recording happens
        whether or not a revert is armed, so the *first* turn on a model that
        400s already poisons that id against ever being reverted onto later.
        """
        errorlog.log_error(e, session_id=session_id, model=current_model,
                           interrupted=turns_interrupted, private=private)
        if getattr(e, "status_code", None) == 400:
            rejected_models.add(current_model)
        if revert_model and is_transient_status(e):
            console.print(f"\n[error] {e}\n")
            return
        if not revert_bad_model():
            console.print(f"\n[error] {e}\n")

    # --- Command handlers ---
    #
    # One nested function per verb, reached through HANDLERS below. Each takes
    # the parsed Cmd and returns None to stay in the session, or _LEAVE to
    # leave it — a nested function cannot `break` the loop it lives in, and a
    # sentinel says so at the call site instead of hiding it in a flag.
    #
    # They are nested because a session's state *is* these locals, which is
    # what `nonlocal` is for. Lifting them out means a state object, and that
    # is a separate fork (see HANDOVER on unifying the three session fields);
    # doing it here would move the chat path too, and the point of this step is
    # that the chat path does not move.

    def _session_arg(cmd, i=0, usage=None):
        """The session id at token `i`, defaulting to this session.

        Returns None — having said why — when a token is present but isn't a
        number. `/title abc` used to reach a bare `int()` and take the whole
        REPL down; a typo should cost a line of output, not the app.
        """
        if not cmd.arg(i):
            return session_id
        target = cmd.int_arg(i)
        if target is None:
            console.print(usage or f"/{cmd.verb} <session id>")
        return target

    def h_quit(cmd):
        if AUTO_EXPORT and history and not private:
            safe_export(conn, session_id)
        return _LEAVE

    def h_help(cmd):
        print_help()

    def h_new(cmd):
        nonlocal session_id, history, injected, current_title, current_model
        nonlocal system_prompt, system_prompt_name, persona, persona_name
        nonlocal trait_names, turns_interrupted, outcome
        # `/new p` — a private chat from inside a session, joining `p` at the
        # hub. It **nests** rather than replacing this session: a private chat
        # is a side trip, and coming back to what you were doing is the point.
        # The isolation is the same one the hub's `p` gets, for the same reason
        # — a separate in-memory connection, closed on the way out. No
        # `if private` branch is involved, which is the test that the design
        # holds (invariant #10).
        if cmd.arg(0).lower() in ("p", "private"):
            priv = db(":memory:")
            try:
                # app_conn, not conn: a screen entered from *this* nested
                # private chat must reach the same durable connection this
                # session would hand it, never the private one.
                result = run_session(priv, new_session(priv), private=True,
                                     app_conn=app_conn)
            finally:
                priv.close()
            if result is not None:
                # The nested private chat's screen asked to open a session —
                # bubble that up as this session's own exit rather than
                # silently discarding it and reprinting our own header.
                outcome = result
                return _LEAVE
            # Say where you have landed. Returning from a private chat into an
            # ordinary one with no marker is how a message ends up in the
            # wrong place.
            print_session_header(conn, session_id, current_model,
                                 current_title, system_prompt_name,
                                 persona_name, private=private,
                                 trait_names=trait_names)
            return
        if AUTO_EXPORT and history and not private:
            safe_export(conn, session_id)
        session_id = new_session(conn)
        history = []
        injected = []
        turns_interrupted = 0
        current_title = "(untitled)"
        current_model = MODEL
        system_prompt = None
        system_prompt_name = None
        persona = None
        persona_name = None
        trait_names = []
        console.print(f"\nStarted session "
                      f"#{session_id}\n")

    def _enter_screens(target):
        """Leave the chat loop for the shared screen controller — the same
        cleanup `/q` does, then one call to `screens.enter()`, never a
        recursive `run_session()`. Its return becomes this session's own
        exit: None means the hub, a session id means a routine transcript
        the routines screen opened.
        """
        nonlocal outcome
        if AUTO_EXPORT and history and not private:
            safe_export(conn, session_id)
        result = screens.enter(app_conn, mode=target)
        if result is not None:
            outcome = _Open(result, routine_transcript=True)
        return _LEAVE

    def h_config(cmd):
        return _enter_screens("config")

    def h_export(cmd):
        # `/export`, `/export chat 5`, and `/export 5` — a bare integer is a
        # chat id everywhere in the surface, so the kind is optional here even
        # though `/delete` requires it. The asymmetry is deliberate and is
        # about consequence, not consistency: an export you didn't mean costs
        # a file, a delete you didn't mean costs the conversation.
        i = 1 if cmd.arg(0).lower() in ("chat", "chats", "session") else 0
        target = _session_arg(cmd, i)
        if target is None:
            return
        export_session(conn, target, quiet=False)

    def h_title(cmd):
        nonlocal current_title
        if not cmd.args:
            console.print(f"Current title: "
                          f"{current_title}")
            return
        target = cmd.int_arg(0)
        if target is None:
            console.print("/title | /title <session id> | "
                          "/title <session id> <new title>")
            return
        new_title = cmd.tail(1)
        if not new_title:
            console.print(f"Title: {get_session_title(conn, target)}")
            return
        set_session_title(conn, target, new_title)
        if target == session_id:
            current_title = new_title
        console.print(f"Session #{target} titled: "
                      f"{new_title}")

    def h_delete(cmd):
        """`/delete` destroys durable data, so it **always** needs a kind.

        Bare `/delete` lists what is deletable and acts on nothing. That is
        not politeness: the drafts had bare `/delete` meaning both "delete
        this conversation" and "drop the injected excerpts", and a confirm
        prompt is the worst possible place to discover which one you typed.
        Detaching lives under `/remove`, where nothing is destroyed.
        """
        if not cmd.args:
            console.print("Usage: /delete chat [<id>]   "
                          "(deletes this conversation and its messages)")
            console.print("  /remove is the reversible one — prompts, "
                          "personas, traits, attachments, excerpts.",
                          style="dim")
            return
        if cmd.arg(0).lower() not in ("chat", "chats", "session"):
            console.print(f"Don't know how to delete '{cmd.arg(0)}'. "
                          f"Deletable: chat.")
            return
        target = _session_arg(cmd, 1)
        if target is None:
            return
        title = get_session_title(conn, target)
        msg_count = conn.execute(
            "SELECT COUNT(*) FROM messages "
            "WHERE session_id=?", (target,)
        ).fetchone()[0]
        confirm = input(
            f"Delete session #{target} '{title}' "
            f"with {msg_count} messages? (y/n) "
        ).strip().lower()
        if confirm == "y":
            delete_session(conn, target)
            console.print(f"Session #{target} deleted.")
            if target == session_id:
                return _LEAVE
        else:
            console.print("Cancelled.")

    def h_search(cmd):
        if not cmd.raw:
            console.print("Usage: /search <keyword>")
            console.print("Example: /search indexing")
            return
        search_messages(conn, cmd.raw)

    def h_update(cmd):
        """`/update db` — re-import the wiki, then index anything new.

        Bare `/update` says what is updatable rather than guessing, the same
        rule `/delete` follows: a command that reaches the vault and the
        embedder should be typed on purpose. `database` is accepted for `db`,
        matching the plural forgiveness `/list` has.
        """
        what = cmd.arg(0).lower()
        if not what:
            console.print(f"\n{PREFIX}update <kind> — one of:")
            console.print("  db     re-import the wiki and embed anything "
                          "not yet indexed\n")
            return
        if what not in ("db", "database"):
            console.print(f"Don't know how to update '{cmd.arg(0)}'. "
                          f"Updatable: db.")
            return
        if not db_on:
            console.print(_DB_OFF)
            return
        do_updatedb(cmd.tail(1))

    def h_recall(cmd):
        if not db_on:
            console.print(_DB_OFF)
            return
        if not cmd.raw:
            console.print("Usage: /recall <question>")
            console.print("Example: /recall what did we "
                          "decide about the vector db?")
            return
        do_recall(cmd.raw)

    def h_remember(cmd):
        if not db_on:
            console.print(_DB_OFF)
            return
        if not cmd.raw:
            console.print("Usage: /remember <query>")
            console.print("Example: /remember what we "
                          "decided about chunking")
            return
        do_remember(conn, session_id, history, injected,
                    cmd.raw, model=current_model)

    def h_model(cmd):
        nonlocal current_model, revert_model
        if not cmd.raw:
            console.print(f"Current model: "
                          f"{current_model}")
            return
        raw = cmd.raw.strip()
        # A plain integer picks straight off /list models' displayed order,
        # ahead of loose-name resolution and with no second picker. Checked
        # here rather than inside `select_model`, which the routine-creation
        # model prompt also calls — that flow reads a `None` return as
        # "cancelled", and a mistyped number there must not silently abandon
        # the routine being built.
        if raw.isdigit():
            new_model = model_by_number(int(raw))
            if new_model is None:
                console.print(f"  {raw} doesn't pick a row — digits select "
                              f"off {PREFIX}list models' displayed order, "
                              f"they're never a raw id. Run "
                              f"{PREFIX}list models to see what's there.",
                              style="dim")
                return
        else:
            new_model = select_model(cmd.raw)
        if not new_model:
            console.print("model unchanged", style="dim")
            return
        prev_model = current_model
        set_session_model(conn, session_id, new_model)
        current_model = new_model
        console.print(f"Switched to model: "
                      f"{new_model}")
        # Arm auto-revert on **every** switch: the first turn that errors on
        # the new model backs out to prev_model, and a turn that works disarms.
        #
        # It used to arm only for models *not* in `known_models()`, which meant
        # the safety net skipped the exact case it was built for. A broken id
        # that is in your `MODELS` — the longcat case — switched cleanly, armed
        # nothing, and 400ed every turn with a raw provider error that never
        # names the model, until you worked it out and switched back by hand.
        # Dropping longcat from the config deleted the instance and left the
        # class.
        #
        # A status-coded transient (429/502/503/504) on this first turn no
        # longer spends the revert (`W-1.1-03`, 2026-07-30): `handle_turn_error`
        # checks `api.is_transient_status` before reverting, so a hiccup right
        # after a switch leaves the new model selected and armed, and only a
        # rejection or an untyped error still backs out to prev_model.
        revert_model = prev_model if new_model != prev_model else None

    # --- Tags ---

    def _active():
        """What the session is carrying, in the shape the resolver reads."""
        return {"prompt": system_prompt_name,
                "persona": persona_name,
                "trait": list(trait_names)}

    def _attach_layer(kind, name):
        """Put one resolved pool item on the session and say what happened."""
        nonlocal system_prompt, system_prompt_name, persona, persona_name
        nonlocal trait_names
        body, filename = load_pool_file(kind, name)
        if body is None:
            # Resolution said it was there, so this is a file that moved or
            # became unreadable between the two — worth naming as such.
            console.print(f"'{name}' resolved but could not be read from "
                          f"{pool_of(kind).plural}.")
            return
        label = pool_of(kind).label
        if kind == "prompt":
            set_system_prompt(conn, session_id, body, filename)
            system_prompt, system_prompt_name = body, filename
        elif kind == "persona":
            set_persona(conn, session_id, body, filename)
            persona, persona_name = body, filename
        else:
            # Traits stack. Re-adding an active one is a clear no-op rather
            # than a duplicate: two copies of a trait in the prompt is not
            # twice the instruction, it is a bug that reads as emphasis.
            if name in trait_names:
                console.print(f"{name} — {label} is already on.")
                return
            trait_names = trait_names + [name]
            set_traits(conn, session_id, trait_names)
        console.print(f"added {name} — {label} ({len(body)} characters)")

    def h_add(cmd):
        if not cmd.args:
            console.print("Usage: /add <name> | /add <prompt|persona|trait> "
                          "<name> | /add <path> | /add tag [session] <name>")
            return
        head = cmd.arg(0).lower()

        # Tags never resolve bare — '/add python' must not guess a tag — so
        # the kind is required and is checked before anything else.
        if head in ("tag", "tags"):
            rest = cmd.args[1:]
            if not rest:
                console.print("Usage: /add tag <name> or "
                              "/add tag <session_id> <name>")
            elif len(rest) == 1:
                add_tag(conn, session_id, rest[0])
            elif rest[0].isdigit():
                add_tag(conn, int(rest[0]), cmd.tail(2))
            else:
                console.print("Usage: /add tag <session_id> <name>")
            return

        # Explicit kind: '/add trait relax' searches that pool only.
        p = pool_of(head)
        if p and len(cmd.args) > 1:
            found = resolve_layer(cmd.tail(1), _active(), kinds=[p.kind])
            if found:
                _attach_layer(*found)
            return
        if p:
            console.print(f"Usage: /add {p.singular} <name>   "
                          f"(/list {p.plural} to see them)")
            return

        # Bare: search the three pools by priority. A path is only considered
        # once that has found nothing, so a pool item named like a file still
        # wins — see parse.looks_like_path. **The ordering is the deliberate
        # part and does not change.** What changes is that the pool search
        # keeps its miss to itself when the thing is a path: it used to print
        # `no exact, prefix or substring match for './notes.md' in 5 prompts, 3
        # personas, 4 traits` and then attach the file on the very next line,
        # which is the app contradicting itself inside two lines of output.
        #
        # Suppressed whenever it looks like a path, not only when the attach
        # then works, because `do_attach` reports its own refusals and every one
        # of them is more specific than the pool miss — outside the jail, no
        # such file, a directory, wrong extension, not UTF-8, too big. There is
        # no silent branch for the miss message to be covering.
        maybe_path = looks_like_path(cmd.raw)
        found = resolve_layer(cmd.raw, _active(), quiet=maybe_path)
        if found:
            _attach_layer(*found)
        elif maybe_path:
            do_attach(conn, session_id, history, cmd.raw,
                      model=current_model)

    def _detach_layer(kind, name):
        nonlocal system_prompt, system_prompt_name, persona, persona_name
        nonlocal trait_names
        # The singular pools store a filename and the resolver works in stems;
        # report the stem either way, so what you are told you removed is what
        # you typed. See pools.stem.
        label, name = pool_of(kind).label, stem(name)
        if kind == "prompt":
            clear_system_prompt(conn, session_id)
            system_prompt = system_prompt_name = None
        elif kind == "persona":
            clear_persona(conn, session_id)
            persona = persona_name = None
        else:
            trait_names = [t for t in trait_names if t != name]
            set_traits(conn, session_id, trait_names)
        console.print(f"removed {name} — {label}")

    def h_remove(cmd):
        if not cmd.args:
            console.print("Usage: /remove <name> | /remove "
                          "<prompt|persona|trait> [name] | /remove #<n> | "
                          "/remove tag <name> | /remove excerpts")
            return
        head = cmd.arg(0).lower()

        # `#n` is the attachment namespace. Any trailing text is ignored, so
        # pasting a line straight out of the attachment list works.
        if head.startswith("#"):
            digits = "".join(takewhile(str.isdigit, head[1:]))
            if digits:
                do_detach(conn, session_id, history, digits)
            else:
                console.print("Usage: /remove #<n>   (/status lists them)")
            return

        if head in ("tag", "tags"):
            rest = cmd.args[1:]
            if not rest:
                console.print("Usage: /remove tag <name> or "
                              "/remove tag <session_id> <name>")
            elif len(rest) == 1:
                remove_tag(conn, session_id, rest[0])
            elif rest[0].isdigit():
                remove_tag(conn, int(rest[0]), cmd.tail(2))
            else:
                console.print("Usage: /remove tag <session_id> <name>")
            return

        # Injected recall excerpts. This is a *detach*, not a delete: /remember
        # attached them and nothing durable is destroyed by dropping them,
        # which is exactly the line between /remove and /delete.
        if head in ("excerpts", "excerpt"):
            do_forget(history, injected)
            return

        # A bare kind peels whatever that pool is carrying: '/remove persona'.
        p = pool_of(head)
        if p and len(cmd.args) == 1:
            carried = _active().get(p.kind)
            if not carried:
                console.print(f"No {p.singular} attached.")
            elif isinstance(carried, str):
                _detach_layer(p.kind, carried)
            elif len(carried) == 1:
                _detach_layer(p.kind, carried[0])
            else:
                # Several traits and no name: ambiguity is listed, never
                # guessed. "Which one" is a question only the user can answer.
                console.print(f"  {len(carried)} {p.plural} attached: "
                              f"{', '.join(carried)}")
                console.print(f"  /remove {p.singular} <name>", style="dim")
            return

        query = cmd.tail(1) if p else cmd.raw
        found = resolve_attached(query, _active(),
                                 kinds=[p.kind] if p else None)
        if found:
            _detach_layer(*found)

    # --- Settings ---

    def h_database(cmd):
        nonlocal db_on
        arg = cmd.raw.lower()
        if arg == "on":
            db_on = True
            console.print("Database on: /recall and /remember can reach "
                          "the wiki this session.")
        elif arg == "off":
            db_on = False
            console.print("Database off: /recall and /remember are "
                          "disabled this session.")
        elif not arg:
            state = "on" if db_on else "off"
            console.print(f"Database is {state} for this session.")
            if private and not db_on:
                console.print("This is a private chat; it stays sealed "
                              "unless you turn the database on.")
        else:
            console.print("Usage: /database | /database on | /database off")

    def h_tools(cmd):
        nonlocal tools_on
        arg = cmd.raw
        if arg == "on":
            tools_on = True
            console.print("Tools on for this session.")
            if not models.supports_tools(current_model):
                console.print(f"Note: {tools_unsupported_reason(current_model)}, "
                              f"so tools stay inactive.")
            elif not TOOLS_ENABLED:
                console.print("Note: TOOLS_ENABLED is False in "
                              "config.py, so tools stay inactive.")
        elif arg == "off":
            tools_on = False
            console.print("Tools off for this session.")
        elif not arg:
            show_tools_state(current_model, tools_on)
        else:
            console.print("Usage: /tools | /tools on | /tools off")

    def h_connect(cmd):
        """`/connect [embedding]` — the connection, from wherever it starts.

        Works identically in a private chat, and that is not an accident worth
        skipping over: the connection is a property of the machine, not of the
        session, and every path here either reads local process state or talks
        to the embedding endpoint cfc already uses. Nothing is written down and
        nothing new is phoned home, so the private half needs no special case —
        which is what "chat means both chats" looks like when it comes free.
        """
        target = cmd.arg(0).lower()
        if not target:
            connect_status()
        elif target in ("embedding", "embedder", "embeddings"):
            connect_embedding()
        else:
            console.print(f"Unknown connect target '{target}'. "
                          "Targets: embedding")

    # --- The two absorbing verbs ---

    def h_status(cmd):
        show_status(conn, session_id, current_model, current_title,
                    private=private,
                    system_prompt_name=system_prompt_name,
                    persona_name=persona_name, trait_names=trait_names,
                    tools_on=tools_on, db_on=db_on, injected=injected,
                    kind=cmd.arg(0) or None)

    def h_list(cmd):
        show_list(conn, cmd.raw, current_model)

    # --- Feature areas ---

    def h_routine(cmd):
        # 'new' is tested before the run form, or a routine would have to be
        # called something other than "new" for either to work. Bare
        # `/routine` now opens the routines screen; the direct quick forms
        # (`/routine <name>`, `/routine new`) are unchanged.
        if not cmd.raw:
            return _enter_screens("routine")
        elif cmd.raw == "new":
            create_routine()
        else:
            do_routine(conn, cmd.raw, model=current_model)

    def h_file(cmd):
        do_file(cmd.raw)

    def h_move(cmd):
        do_move()

    def h_clear(cmd):
        do_clear(cmd.raw)

    def h_wiki(cmd):
        # Bare `/wiki` now opens the wiki screen; `/wiki diff ...` and
        # `/wiki commit ...` remain direct quick forms from the chat.
        if not cmd.args:
            return _enter_screens("wiki")
        action = cmd.arg(0)
        rest = cmd.tail(1)
        if action == "diff":
            show_wiki_diff(rest)
        elif action == "commit":
            do_wiki_commit(rest)
        else:
            console.print(
                "Usage: /wiki | /wiki <diff|commit> [scope] [file] "
                "[<message>]", style="red")
            console.print(
                "  scope: wiki (default) | journal | vault    "
                "granularity: folder (default) | file", style="dim")

    # The command surface: twenty-four verbs, in one place. A verb that isn't
    # here is not a command — it falls through to the model, exactly as an
    # unmatched `startswith` did. Aliases (`h`, `?`, `db`) and retired verbs
    # are the parser's business, so this table holds live, canonical verbs only.
    HANDLERS = {
        # ask
        "help": h_help,
        "list": h_list,
        "status": h_status,
        "config": h_config,
        "search": h_search,
        # context
        "add": h_add,
        "remove": h_remove,
        # destroy
        "delete": h_delete,
        # data
        "export": h_export,
        # memory
        "recall": h_recall,
        "remember": h_remember,
        "update": h_update,
        # session
        "new": h_new,
        "q": h_quit,
        "title": h_title,
        # settings
        "model": h_model,
        "tools": h_tools,
        "database": h_database,
        "connect": h_connect,
        # feature areas
        "wiki": h_wiki,
        "routine": h_routine,
        "file": h_file,
        "move": h_move,
        "clear": h_clear,
    }
    # The table and the canonical list must agree. Checked rather than
    # remembered: a verb in one and not the other is a command that is
    # documented and does nothing, or does something and is undocumented.
    assert set(HANDLERS) == set(VERBS), set(HANDLERS) ^ set(VERBS)


    while True:
        try:
            user = read_input("you> ").strip()
        except EOFError:
            # Ctrl-D on an empty line leaves the session. Ctrl-C is handled
            # inside read_input (cancel line, stay) and never reaches here.
            console.print()
            if AUTO_EXPORT and history and not private:
                safe_export(conn, session_id)
            break
        if not user:
            continue

        cmd = parse(user)
        if cmd is not None:
            handler = HANDLERS.get(cmd.verb)
            if handler is not None:
                if handler(cmd) is _LEAVE:
                    # `outcome` may already carry an `_Open` — set by
                    # `_enter_screens` or by `/new p` bubbling one up from a
                    # nested private chat — or stay None, the plain "hub".
                    break
                continue
            # An unrecognised verb is not a command; it goes to the model,
            # exactly as an unmatched startswith did. cfc does not claim the
            # whole prefix namespace.

        # --- Chat ---

        # Frame what was just sent, so the human turn reads as a peer to the AI
        # panels below it rather than a bare `you>` line.
        console.print(human_panel(user))

        save_message(conn, session_id, "user", user,
                     model=current_model)
        history.append({"role": "user", "content": user})

        # One place builds the system layers, so a new one is added there and
        # not in each turn path. Same order as before it was a function.
        prefix = assemble_system(system_prompt, persona,
                                 pool_bodies("trait", trait_names))

        # Tools need all three switches on. Otherwise the original single
        # streamed call, unchanged.
        use_tools = (TOOLS_ENABLED and tools_on
                     and models.supports_tools(current_model))

        if use_tools:
            # Only on the turn that actually offers tools, and only in the
            # prefix — so a tools-off turn is byte-for-byte the request it
            # always was, and nothing about our budgets reaches the transcript.
            prefix = prefix + tools_guidance()
            # Re-roll an empty tool turn instead of painting a blank panel.
            # The decision is `commands.empty_completion_decision`, the same
            # one the streaming path below uses — standing decision 7 exists
            # because these two drifted once, and the tool path silently not
            # offering this retry was that drift. `agent_turn` has already said
            # *what* happened by the time we get here (see `agent._say_empty`).
            empty_attempts = 0
            final = None
            while True:
                try:
                    final = agent_turn(prefix, history, current_model,
                                       conn, session_id, ctx=chat_ctx)
                except KeyboardInterrupt:
                    console.print("\n[tool turn cancelled]\n")
                    turns_interrupted += 1
                    final = None
                    break
                except httpx.HTTPError as e:
                    handle_turn_error(e)
                    final = None
                    break
                revert_model = None   # the model answered — it's real; disarm
                if (final.get("content") or "").strip():
                    break
                retry, empty_attempts = empty_completion_decision(
                    chat_ctx.interactive, empty_attempts,
                    EMPTY_COMPLETION_RETRIES)
                if not retry:
                    final = None
                    break
            if final is None:
                console.print()
                continue
            render_answer(final.get("content"))
            # Same context bar as the streaming path — agent_turn persisted the
            # final turn's usage, so read it back from the row it just wrote.
            t_in, t_out, _ = get_context_info(
                conn, session_id, current_model)
            print_context_bar(current_model, t_in, t_out)
            console.print()
            if current_title == "(untitled)" and not private:
                new_title = generate_title(user)
                if new_title != "(untitled)":
                    set_session_title(conn, session_id, new_title)
                    current_title = new_title
                    console.print(f"[title: {new_title}]\n")
            if not private:
                auto_embed()   # index this turn's messages (best-effort)
            continue

        api_messages = list(prefix)
        api_messages.extend(history)

        console.print()  # blank line before AI panel

        assistant = ""
        usage = None
        empty_attempts = 0
        while True:
            try:
                assistant, usage, reasoning = stream_response(
                    api_messages, model=current_model
                )
            except KeyboardInterrupt:
                console.print("\n[streaming cancelled]\n")
                turns_interrupted += 1
                assistant = ""
                break
            except httpx.HTTPError as e:
                handle_turn_error(e)
                assistant = ""
                break
            revert_model = None   # a response came back — the model is real

            if assistant.strip():
                break

            # Empty completion. Thinking models (e.g. GLM-5.2:thinking) do this
            # now and then — a provider-side hiccup, not a size limit. Say which
            # kind it was; the same context usually answers on a re-roll.
            if reasoning.strip():
                console.print(
                    "\n[the model thought but returned no answer — "
                    "provider hiccup, common on thinking models]")
            else:
                console.print("\n[empty response]")

            # The re-roll policy now lives in one place, shared with the tool
            # path above. What stays here is the diagnosis: this path can see
            # whether the model thought before returning nothing, which the
            # tool path's provider hides behind a 400.
            retry, empty_attempts = empty_completion_decision(
                chat_ctx.interactive, empty_attempts, EMPTY_COMPLETION_RETRIES)
            if retry:
                continue
            break

        if not assistant.strip():
            console.print()
            continue

        tok_in = (usage or {}).get("prompt_tokens") or 0
        tok_out = (usage or {}).get("completion_tokens") or 0

        save_message(
            conn, session_id, "assistant", assistant,
            tok_in=tok_in or None,
            tok_out=tok_out or None,
            model=current_model,
        )

        # Show context usage after response
        print_context_bar(current_model, tok_in, tok_out)
        console.print()  # Blank line before next prompt

        history.append(
            {"role": "assistant", "content": assistant}
        )

        if current_title == "(untitled)" and not private:
            new_title = generate_title(user)
            if new_title != "(untitled)":
                set_session_title(conn, session_id,
                                  new_title)
                current_title = new_title
                console.print(f"[title: {new_title}]\n")

        if not private:
            auto_embed()   # index this turn's messages (best-effort)

    return outcome

if __name__ == "__main__":
    # The headless flags branch before anything that assumes a terminal — no
    # backup on an idle tick, no splash, no REPL. `schedule.cli` returns an
    # exit code because the OS scheduler reads one; the interactive path below
    # is unchanged and `python main.py 5` still means session 5.
    if len(sys.argv) > 1 and sys.argv[1].startswith("-"):
        import schedule
        sys.exit(schedule.cli(sys.argv[1:]))

    # Snapshot before the session touches anything. Deliberately here and not
    # in repl(): repl() is called directly by tests/golden.py, which must not
    # write snapshots of its fixture into the real backup directory.
    safe_backup()
    # One line per launch, for the same reason and in the same place. This is
    # what makes an *empty* errors.log mean "never written" rather than "no
    # errors" — the two are otherwise the same artefact, and the second is the
    # claim the whole log exists to be able to make. See errorlog.py.
    errorlog.log_launch()
    # Once per launch, deliberately not inside repl(): returning from a session
    # to the hub must not re-show it. It also has to finish before repl() reads
    # any input — the splash is safe under invariant #4 only because nothing is
    # driving the terminal yet.
    if splash() == "quit":
        sys.exit(0)
    # After the splash and before the hub, so it is read rather than scrolled
    # past. Silent unless something is actually wrong. Here rather than in
    # repl() for the same reason as safe_backup: tests/golden.py drives repl()
    # directly and must not have config warnings appear in its baseline.
    for _msg in models.startup_warnings():
        console.print(f"[config] {_msg}", style="yellow")
    sid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    repl(sid)