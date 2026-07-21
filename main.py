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

from splash import splash
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
    delete_session,
)
from agent import agent_turn, render_answer
from context import chat_context
from api import stream_response, generate_title, EMPTY_COMPLETION_RETRIES
from backup import safe_backup
from complete import install as install_completion, make_completer
from export import export_session, safe_export
from hub import list_sessions, pick_session
from commands import (
    show_tags, list_all_tags,
    list_prompts, load_prompt_file, list_personas, load_persona_file,
    list_models, show_config, show_token_stats, context_bar,
    print_context_bar,
    search_messages,
    do_recall, do_remember, do_forget,
    do_updatedb, auto_embed,
    do_attach, show_attachments, do_detach,
    show_tools_state,
    show_routines, create_routine, do_routine,
    show_outbox, do_file,
    show_wiki_status, show_wiki_diff, do_wiki_commit,
)

# --- Main REPL ---


def _one_line(text, width=60):
    """Squash a tool result to a single short line for the replay."""
    flat = " ".join((text or "").split())
    return flat[:width] + ("..." if len(flat) > width else "")


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
            session_id = result if result is not None \
                else new_session(conn)
        run_session(conn, session_id)
        session_id = None   # back to the hub for the next round

    conn.close()


def run_session(conn, session_id):
    """One session's REPL loop. Returns when the user leaves the session
    (`:q`, EOF, Ctrl-C); repl() reads that as 'back to the hub'."""
    history = load_history(conn, session_id)
    # Built once per session: `interactive` reports whether stdin is a
    # terminal, which is what the empty-completion handler consults before it
    # asks anyone anything.
    chat_ctx = chat_context()
    injected = []          # blocks added by :remember, newest last
    tools_on = True        # session toggle; the master switch still gates it
    current_title = get_session_title(conn, session_id)
    current_model = get_session_model(conn, session_id)
    system_prompt = get_system_prompt(conn, session_id)
    system_prompt_name = get_system_prompt_name(
        conn, session_id
    )
    persona = get_persona(conn, session_id)
    persona_name = get_persona_name(conn, session_id)

    console.print(f"\nSession #{session_id} | "
                  f"model={current_model} | "
                  f"{current_title}")
    if system_prompt_name:
        console.print(f"System prompt: {system_prompt_name}")
    if persona_name:
        console.print(f"Persona: {persona_name}")

    ctx_str = context_bar(conn, session_id, current_model)
    if ctx_str:
        console.print(f"Context: {ctx_str}")

    # Once, here — not on every turn. The handoff is explicit about that, and
    # a warning printed each turn is a warning nobody reads.
    if TOOLS_ENABLED and current_model not in TOOLS_MODELS:
        console.print(f"Tools are enabled but {current_model} is not in "
                      f"TOOLS_MODELS — proceeding without tools.")

    console.print("Commands:")
    console.print("  :q            back to the session list")
    console.print("  :list         show all sessions")
    console.print("  :new          start a new session")
    console.print("  :export       export this session to "
                  "Obsidian")
    console.print("  :export 5     export session #5 to "
                  "Obsidian")
    console.print("  :tokens       show token usage for this "
                  "session")
    console.print("  :title        show this session's title")
    console.print("  :title 5 Name rename session #5 to "
                  "'Name'")
    console.print("  :delete       delete this session "
                  "(with confirm)")
    console.print("  :delete 5     delete session #5 "
                  "(with confirm)")
    console.print("  :grep word    search all messages for "
                  "'word'")
    console.print("  :recall q     ask your history a "
                  "question (cited answer)")
    console.print("  :remember q   pull matching excerpts "
                  "into this conversation")
    console.print("  :forget       drop the last injected "
                  "excerpts")
    console.print("  :attach path  attach a local text file "
                  "(persistent)")
    console.print("  :attached     list attachments in this "
                  "session")
    console.print("  :detach 1     remove attachment #1")
    console.print("  :tag python   add tag 'python' to this "
                  "session")
    console.print("  :tag 3 python add tag to session #3")
    console.print("  :tags         show tags on this session")
    console.print("  :tags 3       show tags on session #3")
    console.print("  :untag python remove tag from this "
                  "session")
    console.print("  :taglist      show all tags with "
                  "session counts")
    console.print("  :prompts      list available system "
                  "prompt files")
    console.print("  :prompt       show current system "
                  "prompt")
    console.print("  :prompt name  set system prompt from "
                  "'name.md'")
    console.print("  :prompt off   remove system prompt")
    console.print("  :personas     list available persona "
                  "files")
    console.print("  :persona      show current persona")
    console.print("  :persona name set persona from "
                  "'name.md'")
    console.print("  :persona off  remove persona")    
    console.print("  :model        show current model")
    console.print("  :model name   switch to model 'name'")
    console.print("  :models       list configured models")
    console.print("  :tools        show tool state for this "
                  "session")
    console.print("  :tools on     enable tools this session")
    console.print("  :config       show all settings")
    console.print("  Alt+Enter     insert a newline "
                  "(Enter sends)")
    console.print()

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

    while True:
        try:
            user = read_input("you> ").strip()
        except EOFError:
            # Ctrl-D on an empty line leaves the session. Ctrl-C is handled
            # inside read_input (cancel line, stay) and never reaches here.
            console.print()
            if AUTO_EXPORT and history:
                safe_export(conn, session_id)
            break
        if not user:
            continue

        if user == ":q":
            if AUTO_EXPORT and history:
                safe_export(conn, session_id)
            break

        if user == ":list":
            list_sessions(conn)
            continue

        if user == ":new":
            if AUTO_EXPORT and history:
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
            console.print(f"\nStarted session "
                          f"#{session_id}\n")
            continue

        if user == ":config":
            show_config(current_model)
            continue

        if user == ":tokens":
            show_token_stats(conn, session_id,
                             current_model, current_title)
            continue

        if user.startswith(":export"):
            parts = user.split()
            target = int(parts[1]) if len(parts) > 1 \
                else session_id
            export_session(conn, target, quiet=False)
            continue

        if user.startswith(":title"):
            parts = user.split(maxsplit=2)
            if len(parts) == 1:
                console.print(f"Current title: "
                              f"{current_title}")
            elif len(parts) == 2:
                target = int(parts[1])
                console.print(f"Title: {get_session_title(conn, target)}")
            elif len(parts) == 3:
                target = int(parts[1])
                new_title = parts[2]
                set_session_title(conn, target, new_title)
                if target == session_id:
                    current_title = new_title
                console.print(f"Session #{target} titled: "
                              f"{new_title}")
            continue

        if user.startswith(":delete"):
            parts = user.split()
            target = int(parts[1]) if len(parts) > 1 \
                else session_id
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
                    break
            else:
                console.print("Cancelled.")
            continue

        if user.startswith(":grep"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2:
                console.print("Usage: :grep <keyword>")
                console.print("Example: :grep indexing")
                continue
            search_messages(conn, parts[1])
            continue

        # --- Memory commands ---

        if user.startswith(":recall"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                console.print("Usage: :recall <question>")
                console.print("Example: :recall what did we "
                              "decide about the vector db?")
                continue
            do_recall(parts[1].strip())
            continue

        if user.startswith(":remember"):
            parts = user.split(maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                console.print("Usage: :remember <query>")
                console.print("Example: :remember what we "
                              "decided about chunking")
                continue
            do_remember(conn, session_id, history, injected,
                        parts[1].strip(), model=current_model)
            continue

        if user == ":forget":
            do_forget(history, injected)
            continue

        if user == ":updatedb":
            do_updatedb()
            continue

        # --- Attachments ---
        #
        # :attached and :detach are matched before :attach, because
        # ":attached".startswith(":attach") is true and would otherwise be
        # read as an attach of a file called "ed".

        if user == ":attached":
            show_attachments(conn, session_id)
            continue

        if user.startswith(":detach"):
            parts = user.split(maxsplit=1)
            do_detach(conn, session_id, history,
                      parts[1] if len(parts) > 1 else "")
            continue

        if user.startswith(":attach"):
            parts = user.split(maxsplit=1)
            do_attach(conn, session_id, history,
                      parts[1].strip() if len(parts) > 1 else "",
                      model=current_model)
            continue

        # --- Model commands ---

        if user == ":models":
            list_models(current_model)
            continue

        if user.startswith(":model"):
            if user == ":model":
                console.print(f"Current model: "
                              f"{current_model}")
            else:
                parts = user.split(maxsplit=1)
                new_model = parts[1].strip()
                set_session_model(conn, session_id,
                                  new_model)
                current_model = new_model
                console.print(f"Switched to model: "
                              f"{new_model}")
            continue

        # --- Tag commands ---

        if user == ":taglist":
            list_all_tags(conn)
            continue

        if user.startswith(":tags"):
            parts = user.split()
            if len(parts) == 1:
                show_tags(conn, session_id)
            elif len(parts) == 2:
                show_tags(conn, int(parts[1]))
            continue

        if user.startswith(":tag"):
            parts = user.split(maxsplit=2)
            if len(parts) == 1:
                console.print("Usage: :tag <name> or "
                              ":tag <session_id> <name>")
            elif len(parts) == 2:
                if parts[1].isdigit():
                    show_tags(conn, int(parts[1]))
                else:
                    add_tag(conn, session_id, parts[1])
            elif len(parts) == 3:
                if parts[1].isdigit():
                    add_tag(conn, int(parts[1]), parts[2])
                else:
                    console.print("Usage: :tag <session_id> "
                                  "<name>")
            continue

        if user.startswith(":untag"):
            parts = user.split(maxsplit=2)
            if len(parts) == 1:
                console.print("Usage: :untag <name> or "
                              ":untag <session_id> <name>")
            elif len(parts) == 2:
                if parts[1].isdigit():
                    console.print("Usage: :untag "
                                  "<session_id> <name>")
                else:
                    remove_tag(conn, session_id, parts[1])
            elif len(parts) == 3:
                if parts[1].isdigit():
                    remove_tag(conn, int(parts[1]),
                               parts[2])
                else:
                    console.print("Usage: :untag "
                                  "<session_id> <name>")
            continue

        # --- System prompt commands ---

        if user == ":prompts":
            list_prompts()
            continue

        if user.startswith(":prompt"):
            arg = user.split(maxsplit=1)
            arg = arg[1].strip() if len(arg) > 1 else ""

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
            continue
        if user == ":personas":
            list_personas()
            continue

        if user.startswith(":persona"):
            arg = user.split(maxsplit=1)
            arg = arg[1].strip() if len(arg) > 1 else ""

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
            continue

        # --- Tools ---

        if user.startswith(":tools"):
            arg = user.split(maxsplit=1)
            arg = arg[1].strip() if len(arg) > 1 else ""
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
            continue

        # --- Routines ---
        #
        # ':routine new' is matched before the run form, or a routine would
        # have to be called something other than "new" for either to work.

        if user == ":routine":
            show_routines()
            continue

        if user.startswith(":routine"):
            arg = user.split(maxsplit=1)[1].strip()
            if arg == "new":
                create_routine()
            else:
                do_routine(conn, arg, model=current_model)
            continue

        # --- Outbox ---

        if user == ":outbox":
            show_outbox()
            continue

        if user.startswith(":file"):
            do_file(user.split(maxsplit=1)[1].strip()
                    if len(user.split(maxsplit=1)) > 1 else "")
            continue

        # --- The vault repo ---
        #
        # Matched before the bare ':wiki' so ':wiki diff' can't be read as an
        # unknown argument to the status screen. Same shape as ':routine'.

        if user == ":wiki":
            show_wiki_status()
            continue

        if user.startswith(":wiki "):
            rest = user.split(maxsplit=1)[1].strip()
            verb, _, rest_arg = rest.partition(" ")
            if verb == "diff":
                show_wiki_diff(rest_arg.strip())
            elif verb == "commit":
                do_wiki_commit(rest_arg.strip())
            else:
                console.print(
                    "Usage: :wiki | :wiki diff [all] | "
                    ":wiki commit [all] <message>", style="red")
            continue

        # --- Chat ---

        # Frame what was just sent, so the human turn reads as a peer to the AI
        # panels below it rather than a bare `you>` line.
        console.print(human_panel(user))

        save_message(conn, session_id, "user", user,
                     model=current_model)
        history.append({"role": "user", "content": user})

        prefix = []
        if persona:
            prefix.append({
                "role": "system",
                "content": persona,
            })
        if system_prompt:
            prefix.append({
                "role": "system",
                "content": system_prompt,
            })

        # Tools need all three switches on. Otherwise the original single
        # streamed call, unchanged.
        use_tools = (TOOLS_ENABLED and tools_on
                     and current_model in TOOLS_MODELS)

        if use_tools:
            try:
                final = agent_turn(prefix, history, current_model,
                                   conn, session_id)
            except KeyboardInterrupt:
                console.print("\n[tool turn cancelled]\n")
                continue
            except httpx.HTTPError as e:
                console.print(f"\n[error] {e}\n")
                continue
            render_answer(final.get("content"))
            # Same context bar as the streaming path — agent_turn persisted the
            # final turn's usage, so read it back from the row it just wrote.
            t_in, t_out, _ = get_context_info(
                conn, session_id, current_model)
            print_context_bar(current_model, t_in, t_out)
            console.print()
            if current_title == "(untitled)":
                new_title = generate_title(user)
                if new_title != "(untitled)":
                    set_session_title(conn, session_id, new_title)
                    current_title = new_title
                    console.print(f"[title: {new_title}]\n")
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
                console.print(f"\n[error] {e}\n")
                assistant = ""
                break

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

        if current_title == "(untitled)":
            new_title = generate_title(user)
            if new_title != "(untitled)":
                set_session_title(conn, session_id,
                                  new_title)
                current_title = new_title
                console.print(f"[title: {new_title}]\n")

        auto_embed()   # index this turn's messages (best-effort)

if __name__ == "__main__":
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