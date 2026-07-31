# Known bugs

Things that **don't work as intended** and haven't been fixed yet. Not debt, not
a design choice — a defect, flagged on purpose so it's fixed deliberately rather
than rediscovered.

The line between this and the neighbours:

- **BUGS.md** (this file) — it's *broken*. The behaviour is wrong, or a feature
  doesn't do what it says. Fix is owed; the entry records the symptom, where to
  look, and any leading hypothesis.
- **BACKLOG.md** — found in passing, deliberately deferred, and *still works*.
  Debt with reasoning, not a defect.
- **CHANGELOG.md** — what already shipped.

Each entry carries its **tracker id** in the heading — the id the playtest
report gave it, unchanged thereafter, so this file, the report and
`CHANGELOG.md` name one finding without three descriptions of it.

## When an entry closes

**It moves to [`legacy/BUGS.md`](legacy/BUGS.md), whole, and leaves nothing
behind here.** This file holds open entries only. Why the archive is safe rather
than lossy, and why it is tracked in git: `HANDOVER.md`, *Which file owns what*.

---

## B-01 · A provider 400 on tool turns, cause not yet established

**Found:** 2026-07-23, reported by Cas. Two candidate causes were fixed in v0.5
(see `CHANGELOG.md`). Whether either was *the* one is unproven, and this entry
exists so the next occurrence settles it instead of restarting the argument.

**Symptom:** while letting the model roam a tree of files, a turn comes back as
an HTTP 400. Reported variously as complaining about `max_tokens`, as a
tool-handling error, and as something that read like a content filter — while
the model was doing nothing more exotic than reading README files.

**Two theories are already weak, and one of them was mine:**

- **Context overflow is unlikely.** Cas's files were small. The turn's total
  tool output is bounded now regardless, which is worth having on its own
  merits, but it probably was not the cause.
- **A content filter is unlikely.** Ordinary README files, repeatedly.

**The theory that survived has since had its structural fix, and is spent.**
The trigger Cas reports — *only* when the model opens several files in one
turn — is literally the multi-tool-call batch, and the orphaned-call bug fixed
in v0.5 is a batch-only phenomenon. The thing that exits mid-batch is Ctrl-C at
the approval prompt, precisely what a human does when the model starts opening
files they did not ask for. **But `agent.py` now wraps the batch in a
`try/finally` that answers every call on every exit, interrupt included.** So
the interrupt path can no longer poison a session, and there is nothing left of
this theory to build. If it recurs on a turn where nothing was cancelled, that
falsifies it outright and is a genuinely new finding.

**The last suspect was addressed in v0.9, and nothing was confirmed by it.**
`agent.py` normalises a missing `content` to `""` on the assistant message
carrying `tool_calls`; some OpenAI-compatible providers want that field absent
and reject the replay on the next call. Size-independent, tool-turns-only, and
it fits the symptom — every *subsequent* message failing rather than the one.

The fix is `api.wire_messages`, and where it lives is the whole of it. The
normalised value is read three lines later by `save_message` and again at the
render, so it has to stay in `history` — which means `history` and the request
are no longer the same object on this path. The transform therefore sits at the
**wire boundary inside `api.py`**, applied by `call_api` and `stream_response`
alike, rather than at either call site. Both paths replay history, and the
streaming one is the easy one to forget precisely because it has no tools: a
session that made tool calls and then switched to a non-tools model replays
those same messages through it. It never mutates its input, because standing
decision 2 lives in `history`. Pinned in `tests/test_wire.py`.

**This changes nothing about the entry's status.** There is no reproduction, so
there is no test that the fix *works* — only that the change is what it claims.
The suspect is now spent, which means the list of things left to try is empty.

**Two of the provider's own three candidate causes are structurally impossible
here** (2026-07-28, from Cas reading nano-gpt's error-handling docs). Those docs
list stop sequences, a very low `max_tokens`, and filtering as the common causes
of the `empty_response` 400. **cfc sends neither `stop` nor `max_tokens`** — the
entire request is built in `api.py`'s two payload literals and is `model`,
`messages`, `stream`, plus `tools` and `stream_options` where they apply. So the
provider's guidance narrows to filtering on its own terms, which this entry
already rates unlikely on the evidence (ordinary README files, repeatedly).

Same reading rules out **inline moderation**: it is an opt-in that has to be
requested, there is no field for it in either payload, and therefore the
"moderation preflight is still charged" clause cannot apply to us either.

This is not a cause and it is not progress toward one. What it is worth is the
next time the error line quotes that same sentence back — *common causes: stop
sequences, very low max_tokens, or filtering* — and someone starts checking two
things cfc cannot do. **A provider's generic advice is not evidence about this
client**, and the twelve lines that establish which of it applies are cheaper to
read once than to re-derive under pressure.

**What to capture when it next fires.** The whole error line — the provider's
message is verbatim in it, and cfc's own request shape is appended:

```
[error] HTTP 400 from …: <provider's message> [cfc: call 3/25, 14 messages,
        ~9,100 tokens, 41,200 chars of tool output this turn, model …]
```

plus **whether anything was interrupted in that session**, and which model. A
low call number with a small token estimate means the conversation's *shape* is
being rejected, which after v0.5 would be a real finding rather than the known
bug. Note `api._error_detail` truncates the body at 800 characters; a message
cut off mid-sentence is that, not the provider being terse.

**All three were driven on 2026-07-27 and they fire.** `_request_shape` renders
the rider; `_error_detail` truncates at 800 as described; and
`_is_empty_completion_400` still recognises the empty-response 400 while letting
a context-overflow 400 through to the raise path — the fail-safe direction that
makes matching on a provider's wording tolerable. Confirmed rather than rebuilt,
as this entry asked.

**The absence-watch has started.** Cas play-tested v0.8.2 on 2026-07-27: every
previously reported issue fixed, nothing new, and no 400. That is one clean
pass, not a window — but it is the first datapoint, and it means the count
starts here rather than at the 0.9 tag.

**The evidence no longer depends on anyone noticing (v0.9.1).** Everything the
paragraph above asks for is now appended to `~/.cfc/errors.log` when it happens:
the whole error line with `_request_shape`'s rider, the model, the session, and
how many turns were cancelled in that session — the last of which nothing
tracked before, and which is the field that tests the surviving interrupt
theory. Before this, the only copy was the scrollback of a tool turn, so one
long turn later the evidence was gone. It also survives a model switch, which it
previously did not: `revert_bad_model()` printed its own line *instead of* the
provider's, so the one case where a 400 is most likely was the one case with
nothing kept.

**Two blind spots, stated rather than discovered at the gate.** A **private
chat** logs nothing, deliberately — the payload includes up to 800 characters of
provider body and that is the one thing a private chat promises never reaches
disk (invariant 10). And errors.log is narrowed to `httpx.HTTPError`, so a 400
arriving as some other exception type would miss it. Routines *are* covered,
which matters here because this is a tool-turn bug and routines are the heaviest
tool users.

**Reading it: a launch writes a line too.** So an empty file means cfc has never
written to it, which is a different fact from "no errors" — that distinction is
the whole basis of closing this entry on absence, and without it the two are the
same artefact.

**How this entry is allowed to close, decided 2026-07-27 rather than at the
gate.** Nothing identified remains to fix, so it cannot be closed by fixing it.
It closes one of three ways: the next occurrence's error line settles it; it
recurs on an uninterrupted turn and becomes a new finding; or it **is not
observed across the whole 0.9 → 1.0 window and closes on absence**. The third is
accepted. It is a weaker claim than "fixed", and v1.0's note has to say which
one happened rather than let an empty `BUGS.md` imply the stronger one.



## B-1.2-04 · A model revert lands on a model the provider already rejected

**Found:** 2026-07-31, v1.2 playtest, reported by Cas.

**Symptom:** two lines from one session, in this order —

```
[error] HTTP 400 from https://api.nano-gpt.com/v1/chat/completions:
        Model moonseek is not supported on /v1/chat/completions.
LATER
[error] provider rejected 'deepkseek' — switched back to moonseek
```

So the session was on `moonseek`, which the provider had already refused;
`/model deepkseek` was also refused; and `revert_bad_model()` put the session
back on `moonseek` and reported it as a recovery.

**Where to look:** `main.py`'s `revert_bad_model()` and the `revert_model`
local it reads. Arming happens at every model switch and holds exactly one id —
the previous session model — with no record of whether that id has already
failed. Nothing there is wrong on its own terms: it backs out the switch you
just made, which is what it says it does.

**What is wrong is the sentence over the outcome.** `switched back to moonseek`
reads as *fixed*, and cfc knows enough to know it isn't: the 400 naming
`moonseek` went through `handle_turn_error` in the same session and was written
to `errors.log`. This is the shape `HANDOVER.md` calls green over a dead
server — the reassurance that stops you checking.

**Leading hypothesis, and it is small:** the session already collects what it
needs; it just doesn't keep it. A set of ids the provider rejected during this
session, consulted before reverting onto one, is enough — either decline the
revert and say the previous model was refused too, or revert and say so. Which
of those it should be is a wording question, not a structural one.
`tests/test_model_revert.py` is where it would be pinned.

**Not in scope here:** *"fall back to a model in `config.py`"*, which is what
the report asked for. `MODELS` is a list of ids config asserts, not a list of
ids known to work — `moonseek` was in it. A fallback needs a source of truth
about which models the provider actually serves, and cfc has none. That is
`W-08` and `Q-1.1-12`, and building a fallback before either is answered would
pick the next unverified id instead of this one.

## B-04 · The connection advice tells you to go to a chat, from a screen that can do it

**Found:** 2026-07-31, by reading during the v1.2 triage, not by use. Never
observed live: it needs a non-green embedder while the config screen is open,
and both the coder and the playtest had a healthy one.

**Symptom:** the v1.2 config screen renders `preflight.connection_state()`
through `ui.connection_light()`, so its Embedding row prints, verbatim:

```
Embedding    ● LM Studio is not running — start it, or /connect embedding
             in a chat
```

The config screen's own command for this is `connect embedding`, listed on its
help screen and three lines below the row saying to go elsewhere. Typing
`/connect embedding` there works exactly as typed — `classify` strips one
leading slash, and `_config_connect` requires the `embedding` argument — so
every word of the advice is right except the two that send you away.

**Same class as `B-1.2-01`, and that is the reason to record it rather than
patch it:** a string written for one reader, given a second reader by v1.2.
`B-1.2-01` closed because the producer and the new reader were both in cfc's
own modules and a parameter could reach across. This one cannot take that fix.

**Why it is a designer's question.** Standing decision 16 puts the advice in
`ui.CONNECTION_STYLE` precisely so there is one copy — the last time a second
copy existed (`commands.connect_status`) it had already gone wrong, and it was
deleted rather than corrected. But `ui.py` imports no cfc module, so the advice
cannot know where it is being rendered, and the two obvious repairs both cost
something a standing decision protects:

- **a `where=` parameter on `connection_light()`** — one copy still, but every
  caller now asserts its own context, and a caller that forgets gets the
  current bug back silently.
- **the screen rewriting the string** — a producer/parser pair on prose, which
  is the shape `HANDOVER.md`'s recurring-hazard table exists to stop.

A third option is that the advice simply stops naming a place (*"start it, or
run connect embedding"*), which is true at all four renderings and costs the
one thing `B-0.9.1-03` added it for. That is a judgement about which reader
matters more, and it belongs to whoever owns decision 16, not to a triage pass.

## B-05 · `run` from the routines screen uses a different model than `/routine`, silently

**Found:** 2026-07-31, in the v1.2.1 triage, by reading — the report
(`N-1.2.1-01`) saw the symptom and read it as a lost warning. Found by
diagnosing that, so a plain-sequence id.

**Symptom:** the same routine, run two ways, runs on two different models and
nothing says so.

- `/routine note writer` from a chat → `main.py:944` passes
  `model=current_model`, so it runs on **the session's model**.
- `run note writer` from the routines screen → `screens.py:576` calls
  `_commands.do_routine(conn, name)` with no `model=`, so `model` is `None`,
  `runner.effective_model` falls through to `default_routine_model()`, and it
  runs on **`routine_default`**.

Confirmed against the database rather than inferred: session 170, the
playtest's own 13:34 run of `note writer` from the screen, is stored with
`model = deepseek/deepseek-v4-pro-cheaper` while the session model was not
that. The routine carries no `model:` pin, so `effective_model` had nothing
else to resolve.

**Why it is quiet.** `do_routine`'s warning fires on
`not models.is_routine_vetted(eff)`, and `routine_default` is vetted by
definition — so the screen path is *structurally incapable* of warning. The
one signal that would tell you the model changed is suppressed by the same
change that caused it.

**Where to look:** `screens.py`'s `_routine_run`, and `enter(conn, mode)` above
it. The session model cannot currently reach the handler: `enter` is called as
`screens.enter(app_conn, mode=target)` (`main.py:501`) and never receives it,
and every screen handler shares one signature, `handler(rest, conn, table)`.
So this is not a forgotten argument — there is no slot to put it in. The fix is
either a field on `table` or a parameter on `enter`, and that is a small design
call rather than a patch.

**Third instance of one shape, which is the reason to record it rather than
fix it in passing.** `B-1.2-01` (the wiki screen printing a chat command),
`B-04` (the connection advice naming a chat from a screen that can do it) and
this are all v1.2 giving an existing function a second reader and the function
behaving as though it still has one. The first two are about *wording*; this
one changes **which model runs**, so it is the first of the three where the
second reader gets different behaviour rather than a confusing sentence.

**Not obviously wrong, which is the other reason it needs a call.** Running a
routine on the vetted default is arguably the *better* default for a screen —
it is the unattended-shaped path, and the screen has no chat to salvage. If
that is the intent it should be said out loud: the screen's own
`show <routine>` prints `model (default)`, which is true from the screen and
false from a chat. What cannot stand is the two paths disagreeing with nothing
naming the difference.
