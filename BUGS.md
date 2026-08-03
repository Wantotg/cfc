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

---

## B-1.7-05 · An empty wiki id is filed twice and never indexed

**Symptom:** A wiki-bound draft whose frontmatter contains an empty `id:` is
filed successfully, but the resulting page has two `id` keys. The importer reads
the later empty value and skips the page as if it had no id, so the filed page
never reaches the wiki index.

**Where:** `mover._ensure_id()` treats an empty id as missing, prepends the new
id, then serializes the original empty key as well. `import_wiki._import_pages()`
skips a page when the parsed id is `None`. The direct path reproduces two id
lines and an imported id of `None`.

**Leading hypothesis:** Replace or remove an empty existing id before writing the
generated one. Add the regression at the filing/import boundary; the existing
test only covers a draft with no id key at all.

---

## B-1.7-01 · Whitespace-only reasoning draws an empty panel

**Symptom:** A thinking model that streams reasoning containing only whitespace
causes the live streaming path to draw an `AI · reasoning` panel with nothing
readable in it.

**Where:** `api.stream_response()` appends any truthy reasoning delta and sends
it to `_thinking_panel()`, which builds the panel without trimming it first. The
non-streaming tool path already guards its equivalent in
`agent._render_reasoning()` with `.strip()`, so this is a streaming-path gap.

**Leading hypothesis:** Apply the same readable-content check before updating the
live reasoning panel, while keeping the raw value available for the empty-
completion diagnosis.
