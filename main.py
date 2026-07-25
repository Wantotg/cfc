# main.py — the REPL: dispatch and the session state the commands act on.
#
# This file owns the loop and the eight pieces of live state a session has
# (history, injected excerpts, title, model, system prompt, persona). The ':'
# commands live in commands.py; everything here is deciding which one to call
# and what to do with the result.
#
#     python3 main.py [session_id]
import sys

import httpx

try:
    import readline  # noqa: F401 — activates line editing for input()
except ImportError:
    pass

from config import MODEL, AUTO_EXPORT

try:
    from config import TOOLS_ENABLED
except ImportError:
    TOOLS_ENABLED = False
try:
    from config import TOOLS_MODELS
except ImportError:
    TOOLS_MODELS = []
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

from parse import parse
from assemble import assemble_system
from pools import bodies as pool_bodies

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
from api import stream_response, generate_title, EMPTY_COMPLETION_RETRIES
from backup import safe_backup
from complete import install as install_completion, make_completer
from export import export_session, safe_export
from hub import list_sessions, pick_session
from commands import (
    show_tags, list_all_tags,
    list_prompts, load_prompt_file, list_personas, load_persona_file,
    list_models, select_model, known_models, show_config, show_token_stats,
    context_bar, print_context_bar,
    search_messages,
    do_recall, do_remember, do_forget,
    do_updatedb, auto_embed,
    do_attach, show_attachments, do_detach,
    show_tools_state,
    show_routines, create_routine, do_routine,
    show_outbox, do_file,
    show_wiki_status, show_wiki_diff, do_wiki_commit,
    print_session_header, print_core_commands, print_help,
)

# --- Main REPL ---


def _one_line(text, width=60):
    """Squash a tool result to a single short line for the replay."""
    flat = " ".join((text or "").split())
    return flat[:width] + ("..." if len(flat) > width else "")


_DB_OFF = ("Database is off for this chat — :database on to enable "
           ":recall and :remember.")

# What a command handler returns to leave the session. A nested handler can't
# `break` the loop it lives in; a sentinel makes the exit visible at the call
# site instead of hiding it behind a mutable flag nobody remembers to reset.
_LEAVE = object()


def repl(session_id=None):
    """Outer driver: the hub, and the session you return to it from.

    A session never exits the program. `:q` (and EOF / Ctrl-C) drop back to the
    hub — the exact screen you started on. The program quits only from the hub,
    with `q`. A `session_id` from `main.py 5` still returns to the hub on `:q`,
    so the hub is the one way out.
    """
    conn = db()
    # Two completion front ends for two readers: prompt_toolkit on a real
    # terminal, readline behind the input() fallback. See complete.py — the
    # readline one silently stopped running when the editor landed.
    install_completion()
    set_completer(make_completer())

    while True:
        if session_id is None:
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
                priv = db(":memory:")
                try:
                    run_session(priv, new_session(priv), private=True)
                finally:
                    priv.close()
                continue        # session_id is still None → back to the hub
            session_id = result if result is not None \
                else new_session(conn)
        run_session(conn, session_id)
        session_id = None   # back to the hub for the next round

    conn.close()


def run_session(conn, session_id, private=False):
    """One session's REPL loop. Returns when the user leaves the session
    (`:q`, EOF, Ctrl-C); repl() reads that as 'back to the hub'.

    `private` is not a per-call-site switch — the isolation is structural, in
    the in-memory `conn` repl() hands us, so every DB write is already a no-op
    against disk. It gates only the two paths that *escape* the connection:
    auto-embed (reads the real db by hardcoded path) and auto-export (writes a
    file). Automatic persistence is off; an explicit `:export` is still honoured
    — the contract is 'nothing is written down unless you ask for it by name'.
    """
    history = load_history(conn, session_id)
    # Built once per session: `interactive` reports whether stdin is a
    # terminal, which is what the empty-completion handler consults before it
    # asks anyone anything.
    chat_ctx = chat_context(private=private)
    injected = []          # blocks added by :remember, newest last
    tools_on = True        # session toggle; the master switch still gates it
    # Whether :recall/:remember/:updatedb may reach the wiki this session. A
    # normal chat: on. A private chat: DATABASE_ACTIVE (default off), so memory
    # is sealed unless you type :database on. This is the *read* axis and is
    # separate from privacy, which is about the write paths — a private chat
    # never persists regardless of this flag.
    db_on = True if not private else DATABASE_ACTIVE
    current_title = get_session_title(conn, session_id)
    current_model = get_session_model(conn, session_id)
    # Auto-revert arming. Non-None ⇒ the current model was set via the
    # "not in your configured models" path and has not yet completed a turn, so
    # the first turn that errors on it is almost certainly "no such model": we
    # back out to this remembered model rather than stranding the session on a
    # dead id. A turn that returns without an HTTP error disarms it (the model
    # is real). Known models are never armed. This holds for both chats — it's
    # the same dispatch, and a private chat's throwaway db takes the revert the
    # same way, persisting nothing real either way.
    revert_model = None
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
                         system_prompt_name, persona_name, private=private)
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
            "appear in the hub. Closing it\n(:q, Ctrl-D, or quitting) ends "
            "it for good; there is no restore. Model file\nwrites are "
            "blocked; an explicit [bold]:export[/] is the one thing that "
            "reaches disk,\nand only because you asked for it by name.",
            style="cyan",
        ))
        if db_on:
            console.print(
                "The wiki database is on: :recall and :remember work here. "
                ":database off to seal it.", style="cyan")
        else:
            console.print(
                "The wiki database is off: :recall and :remember are "
                "disabled. :database on to\nenable them (change the default "
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
        """If an unverified model's first turn just failed, back out to the
        model we were on and say so, instead of printing the raw provider error
        and leaving the session stranded on a dead id. Returns True if it acted.
        Idempotent: disarms itself, so a later transient error prints normally."""
        nonlocal current_model, revert_model
        if not revert_model:
            return False
        bad, current_model, revert_model = current_model, revert_model, None
        set_session_model(conn, session_id, current_model)
        console.print(f"\n[error] provider rejected '{bad}' — switched back to "
                      f"{current_model}\n")
        return True

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
        number. `:title abc` used to reach a bare `int()` and take the whole
        REPL down; a typo should cost a line of output, not the app.
        """
        if not cmd.arg(i):
            return session_id
        target = cmd.int_arg(i)
        if target is None:
            console.print(usage or f":{cmd.verb} <session id>")
        return target

    def h_quit(cmd):
        if AUTO_EXPORT and history and not private:
            safe_export(conn, session_id)
        return _LEAVE

    def h_help(cmd):
        print_help()

    def h_list(cmd):
        list_sessions(conn)

    def h_new(cmd):
        nonlocal session_id, history, injected, current_title, current_model
        nonlocal system_prompt, system_prompt_name, persona, persona_name
        nonlocal trait_names
        if AUTO_EXPORT and history and not private:
            safe_export(conn, session_id)
        session_id = new_session(conn)
        history = []
        injected = []
        current_title = "(untitled)"
        current_model = MODEL
        system_prompt = None
        system_prompt_name = None
        persona = None
        persona_name = None
        trait_names = []
        console.print(f"\nStarted session "
                      f"#{session_id}\n")

    def h_config(cmd):
        show_config(current_model)

    def h_tokens(cmd):
        show_token_stats(conn, session_id,
                         current_model, current_title)

    def h_export(cmd):
        target = _session_arg(cmd)
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
            console.print(":title | :title <session id> | "
                          ":title <session id> <new title>")
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
        target = _session_arg(cmd)
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

    def h_grep(cmd):
        if not cmd.raw:
            console.print("Usage: :grep <keyword>")
            console.print("Example: :grep indexing")
            return
        search_messages(conn, cmd.raw)

    # --- Memory ---

    def h_recall(cmd):
        if not db_on:
            console.print(_DB_OFF)
            return
        if not cmd.raw:
            console.print("Usage: :recall <question>")
            console.print("Example: :recall what did we "
                          "decide about the vector db?")
            return
        do_recall(cmd.raw)

    def h_remember(cmd):
        if not db_on:
            console.print(_DB_OFF)
            return
        if not cmd.raw:
            console.print("Usage: :remember <query>")
            console.print("Example: :remember what we "
                          "decided about chunking")
            return
        do_remember(conn, session_id, history, injected,
                    cmd.raw, model=current_model)

    def h_forget(cmd):
        do_forget(history, injected)

    def h_updatedb(cmd):
        if not db_on:
            console.print(_DB_OFF)
            return
        do_updatedb(cmd.raw)

    # --- Attachments ---

    def h_attached(cmd):
        show_attachments(conn, session_id)

    def h_detach(cmd):
        do_detach(conn, session_id, history, cmd.raw)

    def h_attach(cmd):
        do_attach(conn, session_id, history, cmd.raw,
                  model=current_model)

    # --- Models ---

    def h_models(cmd):
        list_models(current_model)

    def h_model(cmd):
        nonlocal current_model, revert_model
        if not cmd.raw:
            console.print(f"Current model: "
                          f"{current_model}")
            return
        new_model = select_model(cmd.raw)
        if not new_model:
            console.print("model unchanged", style="dim")
            return
        prev_model = current_model
        set_session_model(conn, session_id, new_model)
        current_model = new_model
        console.print(f"Switched to model: "
                      f"{new_model}")
        # Arm auto-revert if we can't vouch for this model: the first turn
        # that errors on it backs out to prev_model. A known model, or
        # re-selecting the same one, disarms.
        revert_model = (prev_model
                        if new_model not in known_models()
                        and new_model != prev_model else None)

    # --- Tags ---

    def h_taglist(cmd):
        list_all_tags(conn)

    def h_tags(cmd):
        if not cmd.args:
            show_tags(conn, session_id)
            return
        target = cmd.int_arg(0)
        if target is None:
            console.print("Usage: :tags | :tags <session_id>")
            return
        show_tags(conn, target)

    def h_tag(cmd):
        if not cmd.args:
            console.print("Usage: :tag <name> or "
                          ":tag <session_id> <name>")
        elif len(cmd.args) == 1:
            if cmd.args[0].isdigit():
                show_tags(conn, int(cmd.args[0]))
            else:
                add_tag(conn, session_id, cmd.args[0])
        elif cmd.args[0].isdigit():
            add_tag(conn, int(cmd.args[0]), cmd.tail(1))
        else:
            console.print("Usage: :tag <session_id> "
                          "<name>")

    def h_untag(cmd):
        if not cmd.args:
            console.print("Usage: :untag <name> or "
                          ":untag <session_id> <name>")
        elif len(cmd.args) == 1:
            if cmd.args[0].isdigit():
                console.print("Usage: :untag "
                              "<session_id> <name>")
            else:
                remove_tag(conn, session_id, cmd.args[0])
        elif cmd.args[0].isdigit():
            remove_tag(conn, int(cmd.args[0]), cmd.tail(1))
        else:
            console.print("Usage: :untag "
                          "<session_id> <name>")

    # --- System prompt and persona ---

    def h_prompts(cmd):
        list_prompts()

    def h_prompt(cmd):
        nonlocal system_prompt, system_prompt_name
        arg = cmd.raw
        if not arg:
            if system_prompt:
                console.print(f"\nSystem prompt: "
                              f"{system_prompt_name}\n")
                console.print("---")
                console.print(system_prompt)
                console.print("---\n")
            else:
                console.print("No system prompt set. Use "
                              "':prompts' to see "
                              "available prompt files.")
        elif arg == "off":
            clear_system_prompt(conn, session_id)
            system_prompt = None
            system_prompt_name = None
            console.print("System prompt removed.")
        else:
            content, name = load_prompt_file(arg)
            if content is not None:
                set_system_prompt(conn, session_id,
                                  content, name)
                system_prompt = content
                system_prompt_name = name
                console.print(f"System prompt set: {name}")
                console.print(f"({len(content)} "
                              f"characters)")
            else:
                console.print(f"Prompt file '{arg}' not "
                              "found. Use ':prompts' to "
                              "list available files.")

    def h_personas(cmd):
        list_personas()

    def h_persona(cmd):
        nonlocal persona, persona_name
        arg = cmd.raw
        if not arg:
            if persona:
                console.print(f"\nPersona: "
                              f"{persona_name}\n")
                console.print("---")
                console.print(persona)
                console.print("---\n")
            else:
                console.print("No persona set. Use "
                              "':personas' to see "
                              "available persona "
                              "files.")
        elif arg == "off":
            clear_persona(conn, session_id)
            persona = None
            persona_name = None
            console.print("Persona removed.")
        else:
            content, name = load_persona_file(arg)
            if content is not None:
                set_persona(conn, session_id,
                            content, name)
                persona = content
                persona_name = name
                console.print(f"Persona set: {name}")
                console.print(f"({len(content)} "
                              f"characters)")
            else:
                console.print(f"Persona file '{arg}' "
                              "not found. Use "
                              "':personas' to list "
                              "available files.")

    # --- Settings ---

    def h_database(cmd):
        nonlocal db_on
        arg = cmd.raw.lower()
        if arg == "on":
            db_on = True
            console.print("Database on: :recall and :remember can reach "
                          "the wiki this session.")
        elif arg == "off":
            db_on = False
            console.print("Database off: :recall and :remember are "
                          "disabled this session.")
        elif not arg:
            state = "on" if db_on else "off"
            console.print(f"Database is {state} for this session.")
            if private and not db_on:
                console.print("This is a private chat; it stays sealed "
                              "unless you turn the database on.")
        else:
            console.print("Usage: :database | :database on | :database off")

    def h_tools(cmd):
        nonlocal tools_on
        arg = cmd.raw
        if arg == "on":
            tools_on = True
            console.print("Tools on for this session.")
            if current_model not in TOOLS_MODELS:
                console.print(f"Note: {current_model} is not in "
                              f"TOOLS_MODELS, so tools stay inactive.")
            elif not TOOLS_ENABLED:
                console.print("Note: TOOLS_ENABLED is False in "
                              "config.py, so tools stay inactive.")
        elif arg == "off":
            tools_on = False
            console.print("Tools off for this session.")
        elif not arg:
            show_tools_state(current_model, tools_on)
        else:
            console.print("Usage: :tools | :tools on | :tools off")

    # --- Feature areas ---

    def h_routine(cmd):
        # 'new' is tested before the run form, or a routine would have to be
        # called something other than "new" for either to work.
        if not cmd.raw:
            show_routines()
        elif cmd.raw == "new":
            create_routine()
        else:
            do_routine(conn, cmd.raw, model=current_model)

    def h_outbox(cmd):
        show_outbox()

    def h_file(cmd):
        do_file(cmd.raw)

    def h_wiki(cmd):
        if not cmd.args:
            show_wiki_status()
            return
        action = cmd.arg(0)
        rest = cmd.tail(1)
        if action == "diff":
            show_wiki_diff(rest)
        elif action == "commit":
            do_wiki_commit(rest)
        else:
            console.print(
                "Usage: :wiki | :wiki <diff|commit> [scope] [file] "
                "[<message>]", style="red")
            console.print(
                "  scope: wiki (default) | journal | vault    "
                "granularity: folder (default) | file", style="dim")

    # The whole command surface, in one place. A verb that isn't here is not a
    # command: it falls through to the model, exactly as an unmatched
    # `startswith` did. Aliases (`h`, `?`, `db`) are resolved by the parser, so
    # this table holds canonical verbs only.
    HANDLERS = {
        "q": h_quit,
        "help": h_help,
        "list": h_list,
        "new": h_new,
        "config": h_config,
        "tokens": h_tokens,
        "export": h_export,
        "title": h_title,
        "delete": h_delete,
        "grep": h_grep,
        "recall": h_recall,
        "remember": h_remember,
        "forget": h_forget,
        "updatedb": h_updatedb,
        "attached": h_attached,
        "detach": h_detach,
        "attach": h_attach,
        "models": h_models,
        "model": h_model,
        "taglist": h_taglist,
        "tags": h_tags,
        "tag": h_tag,
        "untag": h_untag,
        "prompts": h_prompts,
        "prompt": h_prompt,
        "personas": h_personas,
        "persona": h_persona,
        "database": h_database,
        "tools": h_tools,
        "routine": h_routine,
        "outbox": h_outbox,
        "file": h_file,
        "wiki": h_wiki,
    }


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
                     and current_model in TOOLS_MODELS)

        if use_tools:
            # Only on the turn that actually offers tools, and only in the
            # prefix — so a tools-off turn is byte-for-byte the request it
            # always was, and nothing about our budgets reaches the transcript.
            prefix = prefix + tools_guidance()
            try:
                final = agent_turn(prefix, history, current_model,
                                   conn, session_id, ctx=chat_ctx)
            except KeyboardInterrupt:
                console.print("\n[tool turn cancelled]\n")
                continue
            except httpx.HTTPError as e:
                if not revert_bad_model():
                    console.print(f"\n[error] {e}\n")
                continue
            revert_model = None   # the model answered — it's real; disarm
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
                assistant = ""
                break
            except httpx.HTTPError as e:
                if not revert_bad_model():
                    console.print(f"\n[error] {e}\n")
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

            # Who decides whether to re-roll depends on whether anyone is
            # there. With a human at a terminal, ask — it's their tokens and
            # they can see what happened. Driven from a pipe (or, later, a
            # headless run), asking means blocking on a keypress that never
            # comes, so retry a bounded number of times and then give up
            # loudly. The old code asked unconditionally and read the EOFError
            # as "no", which turned every piped hiccup into a lost turn.
            if not chat_ctx.interactive:
                empty_attempts += 1
                if empty_attempts <= EMPTY_COMPLETION_RETRIES:
                    console.print(f"[no human to ask — retrying "
                                  f"{empty_attempts}/{EMPTY_COMPLETION_RETRIES}]")
                    continue
                console.print(f"[gave up after {EMPTY_COMPLETION_RETRIES} "
                              f"retries]")
                break

            try:
                again = input("retry? (y/n) ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                console.print()
                again = "n"
            if again == "y":
                console.print()
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
    # Once per launch, deliberately not inside repl(): returning from a session
    # to the hub must not re-show it. It also has to finish before repl() reads
    # any input — the splash is safe under invariant #4 only because nothing is
    # driving the terminal yet.
    if splash() == "quit":
        sys.exit(0)
    sid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    repl(sid)