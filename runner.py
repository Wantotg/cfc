# runner.py — executing a routine.
#
# Separated from routines.py (which is the object and its store, and stays
# light) because this is the half that reaches for the API, the database and
# the tool loop.
#
# **This is the headless entry point in everything but name.** `:routine <name>`
# and a future `--run-routine <name>` both call run_routine() with nothing
# between them and it, which is the whole reason the scheduler was deferred
# rather than designed around: when the OS scheduler arrives it calls this
# function and nothing here changes. Do not put REPL state, prompting, or
# terminal assumptions in this module — the on-command path has a human, the
# scheduled path does not, and they must not diverge.
#
# The run is a normal tool-calling turn with three differences:
#
#   1. Its ToolContext is ungated (ToolContext.for_routine), so the routine's
#      declared roots are the only guardrail. That is the deal from
#      HANDOVER: narrow roots, never pre-cleared tools.
#   2. It runs in its own session, so the transcript is inspectable afterwards
#      like any other — a routine that did something surprising can be read.
#   3. Its outcome lands in the run log whatever happens, including on an
#      exception. A failed run that leaves no trace is the failure mode the
#      log exists to prevent.
import datetime
import traceback

from agent import agent_turn
from api import EMPTY_COMPLETION_RETRIES
from db import PROVIDER_ROUTINE, new_session, save_message
from routines import RoutineError, append_log, last_run, load_routine

try:
    from config import MODEL
except ImportError:
    MODEL = None

# The routine's own prompt is the task. This says who is asking and what is
# absent — a model that assumes a human is watching will end a turn with a
# question, which at 03:00 is the same as doing nothing.
SYSTEM = """You are running as an unattended cfc routine: {name} (id: {id}).

The current date and time is {now}. Use it. You have no clock of your own and
your sense of the date is whatever your training left you with — the first
heartbeat run confidently stamped a file 2025-07-10 on 2026-07-20. A routine
that runs on a schedule is precisely the thing that must not guess at the date.

There is no human present to answer questions or approve anything. Do not ask
for confirmation and do not end your turn with a question — decide, act, and
report what you did.

Your file access is limited to the roots declared by this routine:

  readable: {read_roots}
  writable: {write_roots}

**Always pass absolute paths.** A relative path is resolved against this
process's working directory, which is not one of your roots and is not
something you can predict on a scheduled run — it will simply be refused.

A tool that returns an error is telling you a real boundary — adapt, don't
retry the same call.

When the task is done, reply with a short plain-text summary of what you did.
That summary is what gets recorded in the run log."""


def _summarise(text, limit=200):
    """One line for the log. The transcript keeps the full version."""
    flat = " ".join((text or "").split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


class EmptyCompletion(Exception):
    """The model returned nothing, repeatedly. Treated as a failed run."""


def _turn_with_retry(prefix, task, model, conn, session_id, ctx, event):
    """Run the turn, re-rolling an empty completion rather than accepting it.

    Thinking models return the occasional empty completion — a provider
    hiccup, not a size limit, and the same context usually answers on a
    re-roll.

    **The retry here is unconditional, and deliberately does NOT consult
    `ctx.interactive`.** A routine is a batch job whether or not somebody
    happens to be watching it run, so the policy is the same either way;
    gating it on `interactive` would have made an on-command run give up on
    the first hiccup while an unattended one re-rolled twice, which is exactly
    backwards. `interactive` earns its keep in `main.py`, where it decides
    whether there is a human to *ask* — a question that has no meaning here,
    because this module owns no console and asks nobody anything.

    **The bug this fixes was not a missing prompt.** `agent_turn` returns the
    empty message, `_summarise("")` yields "", and the run was logged as `ok`
    with a blank summary — a routine that did nothing looked exactly like a
    routine that had nothing to do. Same failure mode standing decision #4
    flags for zero-hit recall, arriving through a different door. That is why
    this raises rather than returning something falsy for the caller to notice.

    `history` is rebuilt per attempt so a re-roll re-sends the identical
    request rather than one polluted by the previous empty answer. The empty
    assistant rows `agent_turn` persists are left in the transcript on purpose:
    the routine's session is the audit trail, and "it returned nothing twice"
    is exactly what you want to see there.
    """
    attempts = EMPTY_COMPLETION_RETRIES + 1
    for attempt in range(1, attempts + 1):
        history = [{"role": "user", "content": task}]
        final = agent_turn(prefix, history, model, conn, session_id, ctx=ctx)
        if (final.get("content") or "").strip():
            return final
        if attempt < attempts:
            event(f"empty completion — re-rolling {attempt}/{attempts - 1}")

    raise EmptyCompletion(
        f"model returned an empty completion {attempts} time(s)"
    )


def run_routine(key, conn, model=None, interactive=False, on_event=None):
    """Run one routine. Returns (ok, summary, session_id).

    Never raises for an expected failure — a routine that dies must still get
    a log line, so failures come back as `(False, reason, session_id)` and the
    log is written on every path out of here. `on_event(str)` is optional
    progress reporting, so the REPL can narrate without this module owning a
    console.
    """
    def event(msg):
        if on_event:
            on_event(msg)

    try:
        routine = key if hasattr(key, "id") else load_routine(key)
    except RoutineError as e:
        return False, str(e), None

    if not routine.enabled:
        append_log(routine.id, "skipped", "routine is disabled")
        return False, f"{routine.id} is disabled", None

    problems = routine.validate()
    if problems:
        detail = "; ".join(problems)
        append_log(routine.id, "failed", f"invalid: {detail}")
        return False, f"{routine.id} is invalid: {detail}", None

    # The previous outcome is read from the log, not from memory — a scheduled
    # run is a fresh process and has no memory to read. on_failure is stored
    # and surfaced now; the scheduler is what will act on it.
    prev_status, prev_ts = last_run(routine.id)
    if prev_status == "failed":
        event(f"last run failed at {prev_ts} (on_failure: {routine.on_failure})")

    ctx = routine.context(interactive=interactive)
    model = model or MODEL
    started = datetime.datetime.now()

    # provider marks this as a routine run so the hub can filter it out
    # without parsing the title. The title prefix stays because it is what a
    # human reads in the transcript; it is no longer what the code keys off.
    title = f"routine: {routine.name} — {started.strftime('%Y-%m-%d %H:%M')}"
    session_id = new_session(conn, title=title, model=model,
                             provider=PROVIDER_ROUTINE)
    event(f"session {session_id} — {ctx}")

    # The roots go into the prompt because the model otherwise learns them only
    # by hitting the wall: every run burned a round trip on a relative path
    # that resolved against the process cwd, recovered only because the guard
    # returns the real reason. Telling it up front is not a weakening of the
    # boundary — dispatch still enforces it — it just stops paying for the
    # lesson once per run.
    system = SYSTEM.format(
        name=routine.name, id=routine.id,
        now=started.strftime("%Y-%m-%d %H:%M (%A)"),
        read_roots=", ".join(str(r) for r in ctx.read_roots) or "(none)",
        write_roots=", ".join(str(r) for r in ctx.write_roots)
                    or "(none — you cannot write)",
    )
    try:
        task = routine.prompt_text()
    except RoutineError as e:
        append_log(routine.id, "failed", str(e))
        return False, str(e), session_id

    prefix = [{"role": "system", "content": system}]
    save_message(conn, session_id, "user", task, model=model)

    try:
        final = _turn_with_retry(prefix, task, model, conn, session_id, ctx,
                                 event)
    except Exception as e:                      # noqa: BLE001 — see below
        # Deliberately broad. Anything from an HTTP timeout to a provider
        # returning a shape we don't expect has to reach the log, because an
        # unattended run that dies silently looks identical to one that had
        # nothing to do. The traceback goes to the transcript; the log gets
        # the one-line reason.
        save_message(conn, session_id, "assistant",
                     f"[routine failed]\n\n{traceback.format_exc()}",
                     model=model)
        conn.commit()
        detail = f"{type(e).__name__}: {e}"
        append_log(routine.id, "failed", detail)
        return False, detail, session_id

    conn.commit()
    summary = _summarise(final.get("content", ""))
    elapsed = (datetime.datetime.now() - started).total_seconds()
    append_log(routine.id, "ok", f"{summary} ({elapsed:.0f}s, session {session_id})")
    return True, summary, session_id
