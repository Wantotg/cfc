# HANDOVER.md

You have the repo. Read it. This file is only for what reading it won't tell
you: which decisions are settled, which good-looking ideas were tried and
rejected, where the constants came from, and which bugs were quiet enough that
nothing failed while they were live.

**If this file and the code disagree, the code is right and this file is stale.**
Say so rather than working around it.

Its predecessor, `legacy/HANDOVER.md`, is frozen at v0.8 and no longer updated.
It was written for a model working *without* the source, so it re-describes
things you can just go and look at — but it holds the long-form reasoning behind
most of what is summarised here. Go there when a one-liner below isn't enough.

## Which file owns what

**Every fact has one home; everywhere else names its `TRACKER.md` id and stops.**
A finding written up in `BUGS.md`, again in a roadmap version and again in a
session brief has to be *maintained* in three places — one change costs three
edits and the three drift, which is this project's own recurring hazard rebuilt
in prose.

| | owns | must not carry |
|---|---|---|
| `README.md` | how a human uses it. Coupled to this file — rewrite one, rewrite the other | internal reasoning |
| `CHANGELOG.md` | what changed, when, and why it mattered. Newest first, logged in the same commit | reasoning that outlives the change |
| this file | why the code is shaped as it is: decisions, rejected designs, provenance, scars | history |
| `BACKLOG.md` | what's owed and still working. **Read it before touching the memory layer** | anything closed |
| `BUGS.md` | what's broken and known | anything closed |
| `legacy/` | closed entries of both, frozen whole with the original report; the pre-1.0 changelog | stubs |
| `ROADMAP.md` | what each version added, in Cas's words. His file — propose, don't edit | bugs, backlog, design detail |
| `ROADMAP_PRIVATE.md` · `ROADMAP_BEYOND.md` | gitignored. The forward plan, below and above 2.0 | |
| `TRACKER.md` | gitignored. One line per open issue and the version it's assigned to | any explanation at all |

**The test between here and `CHANGELOG.md`: will it still be true in three
versions?** If yes it belongs here. If it is about one change it belongs there —
a changelog entry may state a decision and its reason in a sentence, but it does
not argue it.

### Three rules for writing any of them

**Say it once, then stop.** A paragraph that would not change what a reader does
is deleted. *"Wrote the decision down so it is visible"* is eight words; the same
point ran to fifty-six in a v1.0 changelog entry, and the surviving eight
belonged in this file anyway.

**Name the failure, not the person.** These files record decisions, false
assumptions and what they cost — that is why they are worth reading. They are
not a narrative about how the mistakes came to be made. Retelling one past the
point it teaches something spends tokens, distracts the reader and the model,
and buries the finding it is wrapped around.

**Records are frozen; rules are maintained.** A version note, a changelog entry,
a `legacy/` file and a scar below record what was true when they were written,
and restyling them to a convention invented afterwards destroys the one property
they have. That covers the reasoning, not just the prose: *"we used to do it the
other way, and here is what it cost"* is the half most projects delete and the
half worth keeping. A **rule** is a live instruction with no such claim — edit it
freely, and this section was rewritten under exactly that licence
(2026-07-29). Correcting something factually wrong is allowed in either; say
which one you are doing.

### Two files with a rule of their own

**`TRACKER.md`'s ids are permanent and its closed rows stay.** An id comes from
the playtest report and is never reallocated — `B-0.9.1-01` is finding 01 of the
v0.9.1 pass, forever, so the report, the tracker row, the `BUGS.md` entry and the
changelog line name the same thing with nothing to reconcile. Closed rows keep
their reason and stay, *nothing owed* included: without that, the same note comes
back next playtest looking new. A session transcript is not a record. The reports
it consumes are in `<vault>/00 inbox`, one file per playtest.

**`legacy/` takes a closed entry whole and leaves no stub.** Struck-through stubs
are why `BUGS.md` and `BACKLOG.md` once reached 283 and 897 lines with eight live
entries between them. Two things make the deletion safe: `CHANGELOG.md` is the
index, so *was this fixed, and why that way* never needs the archive; and the
archive keeps the **original report**, which the changelog never carried and
whose wrong premise is sometimes the finding (`MAX_DISTANCE`, below). It is
tracked in git rather than gitignored — a gitignored archive is invisible to
clones, outside every backup, and destroyed by a fresh checkout, which is the
same argument that killed `inbox/` at the repo root.

## Shape

```
main.py __main__ → safe_backup → splash → repl()
repl()           → hub loop: pick_session ⇄ run_session; owns the connection
run_session()    → one session's REPL; returns to the hub, never exits
main.py --run-due / --run-routine → schedule.cli → runner.run_routine   (headless, no REPL)
```

A chat turn takes one of two paths, chosen per turn by
`TOOLS_ENABLED and tools_on and model in TOOLS_MODELS`: `api.stream_response`
(streaming, no tools) or `agent.agent_turn` (non-streaming tool loop). **They
must end a turn identically** — see invariant 6.

| Module | Holds |
|---|---|
| `main.py` | hub loop, session loop, verb→handler table, live session state |
| `parse.py` | the grammar: `parse(line) → Cmd`, `VERBS`/`ALIASES`/`RESERVED` |
| `commands.py` | what each verb does, the approval gate, the resolver's I/O shell |
| `pools.py` / `assemble.py` | the three pools (prompt/persona/trait) / how they become system messages |
| `agent.py` | the tool-calling turn |
| `tools.py` | the four tools + dispatcher |
| `paths.py` | the jail: `path_guard`, containment + deny list |
| `api.py` | streaming and non-streaming calls, per-phase timeouts, provider error extraction |
| `db.py` | connection, schema/migrations, every query, replay + orphan drop |
| `hub.py` | session browser, picker, `HUB_KEYS` + the help it generates, routine freshness |
| `context.py` | `ToolContext` — read roots, write roots, gated/interactive |
| `routines.py` / `runner.py` | the routine object + its file store and run log / executing one |
| `schedule.py` | what is due, the tick lock, the `--run-due` entry point |
| `mover.py` | filing a proposal out of the outbox; destination re-validation; the journal's git guard |
| `wikigit.py` | the vault repo: status/diff/commit, scoped to a corpus. Owns no console |
| `errorlog.py` | `~/.cfc/errors.log`: provider errors + a line per launch. **Imports no cfc module, never raises, nothing private** |
| `ui.py` | shared Console, palette, panels, `read_input`. **Imports no other cfc module** |
| memory | `import_wiki` → `chunk` → `embed`/`backfill` → `search` → `recall` |
| `config.py` | every deployment knob. **Gitignored** — `config.example.py` is the tracked copy |

---

## Standing decisions

Settled. Argue with them only with a reason, and say that you are.

1. **Any DB write checks its path before the write, not after.** A test guard
   that asserted after a destructive `unlink()` once deleted the real database.
2. **Every tool call gets exactly one result** — in live history and on replay.
   An unanswered call makes the whole conversation 400 forever. Both halves are
   needed: `agent_turn` answers every call on every exit including exceptions,
   and `db._drop_orphan_tool_calls` repairs one on replay. Repair-on-read did
   nothing for the live `history` the REPL keeps replaying from, which is how one
   Ctrl-C used to brick a session in place while looking like a provider fault.
3. **`path_guard` resolves before checking, and the deny list is add-only.**
   Resolving first is what defeats `../` and symlinks. `config.py` may add to the
   list; nothing removes.
4. **Write safety is containment first, deny list second.** A deny list is an
   open-ended commitment — every `config.py.bak` shape escaped it once. `WRITE_ROOTS`
   is the vault outbox and nothing else, is never derived from `TOOLS_ROOTS`, and
   `context.py` refuses a write root overlapping the source. The repo is readable
   and structurally unwritable.
5. **The guard lives in the dispatcher, never at the gate.** Approval decides
   whether a call runs; the guard decides whether it may. `dispatch` is reachable
   with no gate at all, so a check that lives only in `precheck` is advice.
   Approving a call that then fails the guard is correct behaviour.
6. **prompt_toolkit and rich must never drive the terminal at once.** One shared
   `rich.Console` in `ui.py`, which sits at the bottom of the dependency graph.
   This is why there is no in-process timer thread and no full-screen dialog
   anywhere — numbered `input()` pickers are the house idiom.
7. **The two turn paths end identically** (`commands.print_context_bar`). They
   drifted once: when tools became the default, the spinner and token bar
   silently vanished and usage was discarded, blanking `/status`. New per-turn UI
   goes in a shared helper, not one branch.
8. **A routine is reconstructable from its file alone**, keyed by `id`, and an
   invalid one cannot be *saved*. `ToolContext.for_routine()` is the only ungated
   context and forces a declared write scope in the same call. There is no config
   flag that pre-clears a tool; don't rebuild one.

   **The creation flow checks early *as well*, never instead** (v1.0,
   `D-0.9.1-03`). `/routine new` re-prompts per field, but `Routine.validate()`
   and `save_routine`'s refusal are untouched — a hand-edited file never passes
   through the flow at all. What keeps the two honest is that they are the *same
   function*: `routines.trigger_problem` and `on_failure_problem` are called by
   the prompt and by `validate()`, so a field accepted as you type it cannot be
   rejected at save. Two checks written separately would have disagreed the
   first time `weekly` grew a variant.

   The finding underneath was the *exit*, not the validation: the flow returned
   to the REPL silently, so the next line typed became a chat message —
   decision 13's failure shape reached through an abandoned prompt instead of a
   missing verb. Every way out of `create_routine` now says it is one. Worth
   checking for in any prompt flow added later; nothing enforces it but
   `_routine_abandoned`.
9. **Wiki recall keys off the frontmatter id, never the filename.** Renaming a
   page keeps its recall identity. Recall stays wiki-only; the chat log is indexed
   (`source='chat'`) but excluded until hybrid lands. Auto-embed is best-effort and
   must never break a turn.
10. **A private chat's isolation is the connection, not a flag.** It runs against
    `db(":memory:")`, so every `conn`-driven write — including the ones
    `agent_turn` makes on its own — is already a no-op against disk.
    `private=True` gates only the four paths that *escape* the connection:
    auto-embed (opens `DB_PATH` directly), auto-export (writes to the vault),
    model file-writes (empty write roots), and the provider error log (opens
    `~/.cfc/errors.log` by path). A new disk-writing path either goes through
    `conn` or silently defeats this, and owes `tests/test_private.py` a negative.

    **Learn the shape from the fourth.** Its gate is inside `errorlog.log_error`,
    at the write rather than at either call site, because a caller that forgets
    is the failure being prevented. And its negative is *two* assertions — no
    line written, **and** a marker planted in the error text absent from the file
    — because the payload is up to 800 characters of the provider's own body and
    providers echo request fragments back inside a 400. A test that only counts
    lines passes while leaking.
11. **A move that overwrites a live file requires a verified undo.** Journal
    filing is the only such path; it is allowed only against a git-clean corpus,
    checked at plan time *and* inside `commit`, and **fails closed** when git
    can't be consulted. Everywhere else, a target that exists is still a refusal.
12. **Nothing in a routine infers the date or the period it works on.** Both are
    computed and injected (`runner.placeholder_values`). A model has no clock and
    a scheduled run is a fresh process. Inferring from the document — "the last
    entry is Thursday, so write Friday" — is self-consistent and therefore
    silently wrong forever after one missed run.
13b. **The hub's keys are one table too.** `hub.HUB_KEYS` is the dispatch *and*
    the source of the `h` help screen, and the light's legend is generated from
    `ui.CONNECTION_STYLE` — the same mapping the light renders. A help screen is
    the artefact nobody re-reads, so the only safe kind is one that cannot be
    wrong; `tests/test_hub.py` fails if a key is dispatched that the help does
    not describe. The single hand-written line points at `/help`, which is a
    fact about where the commands are documented rather than a copy of them.
13. **The command surface is two lists that must agree**, checked rather than
    maintained: `run_session` asserts its handler table equals `parse.VERBS`. An
    unrecognised verb falls through **to the model**, so a verb that is
    documented but missing from the table isn't an error message — it's an API
    call and a confused answer. **Retiring a word therefore means aliasing it,
    not deleting it.** An `ALIASES` value may be a *phrase* (`models` → `list
    models`) precisely so a retired word can map to a command that takes
    arguments. The only word ever let go is `detach`, whose replacement
    `/remove #<n>` changes the argument's *shape* — that is the bar.

    **Retiring a verb also means grepping `config.example.py`** (`B-0.9.1-02`).
    It is the only shipped file that *instructs a human*, it is not code, and
    nothing checks it — it carried twelve retired `:` commands across three
    releases. The failure is this decision's own: the reader types what their
    config file told them, and an unrecognised verb is an API call rather than
    an error. Write the **canonical** verb, never the alias — `/list models`,
    not `/models`, or the retired word is re-taught one generation later.
14. **A delete reaches the index that points at what was deleted.**
    `chunks`/`vec_chunks` have no foreign keys, so the cascade is in code: index
    rows first, vectors before chunks, a vector-delete failure raising rather than
    half-completing.
15. **"Chat" means both chats.** Every feature is specified for private chat too.
    The one exception is privacy itself, and there you refuse and leave the private
    half unbuilt rather than ship a half-private one. See `CLAUDE.md`.
16. **The connection light renders `preflight.connection_state()` and never
    forms an opinion.** The hub's light, `/connect embedding` and the launch
    report are three renderings of one function. A light that decides for itself
    can disagree with the thing it describes, and the failure is **green over a
    dead server** — the one output nobody double-checks, because it is precisely
    the reassurance that stops you checking. This is affordable rather than
    aspirational: a real embedding call is 0.16s, so the light asks live on every
    hub render and there is no cache anywhere, hence no staleness to reason
    about. It also reports the *process* state only where it measured one —
    `DOWN` exists so "LM Studio is running, its server isn't" is never a guess.

    **The dot carries recoverability, not severity** (v1.0, `D-0.9.1-01`,
    `B-0.9.1-03`). Orange where `/connect embedding` will try, red where it is
    not cfc's to fix — the split `preflight.ensure` already makes, since
    `hosted` returns early and the other three fall through to the fixer.
    Severity cannot discriminate: every non-green state means memory is off,
    equally, so a light sorted by severity is sorted by nothing. Three states
    share orange, and that is a class rather than a collision. **A colour per
    state is still the wrong answer** — `ui.py` imports no cfc module, so this
    is a producer/parser pair across a boundary that cannot close; adding a
    colour widens it.

    **The advice says where it can be typed** (*"in a chat"*), because two of
    its three renderings are at the hub and the hub takes only `n`/`p`/`h`/`q`
    and a chat id. `commands.connect_status` kept a second copy of that advice
    and it had already gone wrong; the copy was deleted rather than corrected.
    `tests/test_connection.py` pins both properties against the mapping, not
    against colour names or an exact phrase, so re-wording stays free.

    **The routine column is the second light** (v0.9.2, `B-0.9.1-04`).
    `hub._freshness` renders `schedule.why_not_due()` and decides nothing.
    It used to be hours-since-last-run against v0.4's 24/48h thresholds — an
    independent opinion about the question the scheduler already answers, and
    therefore free to disagree with it. Five of six live rows were untrue when
    it was fixed: `weekly` postdated the thresholds, and `command` routines aged
    into red despite never being able to be owed a run.

    Two properties fall out, and the second is the argument. **If the OS tick
    stops firing, every scheduled routine goes orange and stays orange** — no
    threshold over a timestamp can say that. And the failure inverts: the
    function deciding the colour *is* the function deciding whether the run
    happens, so a wrong green is a routine that genuinely isn't running. The
    light and the behaviour fail together and cannot disagree.

    **The reason string stays unparsed** — `why_not_due` returns prose, the hub
    uses only `is None`, and `trigger: command` is detected with `parse_trigger`.
    Matching the wording would have added a seventh row to the producer/parser
    table, inside the commit fixing a bug caused by a signal forming its own
    opinion.

    Red left this column deliberately: *how badly overdue* is not a fact
    `why_not_due` knows, and reconstructing it means reinventing the threshold
    just removed. So dim means *cannot be owed a run*, which puts `command` and
    a malformed trigger in one cell — `D-10`, not something this colour can fix.

    **`D-10` is three tiers and the dim conflation is the least of them**
    (body in `BACKLOG.md`, written v1.0 from driving the panel). A file that
    will not parse is dropped entirely — `_routine_rows` discards
    `list_routines()`'s `bad`. And **a routine that parses but fails
    `validate()` renders green**, because nothing in `_freshness` consults
    `validate()`. The colour is not lying about what it measures — *is a run
    owed* — and that is the trap: the panel is read as *is this still working*,
    and the two questions agree on every routine except a broken one.

## Four rules that generated most of the above

**Use a model for judgement under ambiguity; use code for anything with a right
answer.** The mover doesn't ask a model where a file goes. `/wiki` doesn't ask a
model to commit. The retrieval floor doesn't judge relevance — it hands excerpts
to a model that can say "these don't answer it."

**Separate states where they are separable, which is usually at the exception.**
An unreachable embedder and an empty result set are the same silence by the time
they reach a console, and one of them is a confident lie. They are cleanly
distinct exactly once — where one is an exception and the other is `[]` — so
`embed.py` records which it saw *while catching it* and raises `EmbedUnavailable`
rather than a message. Re-deriving a state further up, from wording or from a
count, works until someone improves a sentence. If you are inferring which
failure happened, you are at the wrong end of it.

**A format the provider needs and we don't goes at the wire boundary, not at the
call site.** `api.wire_messages` drops an empty `content` from a tool-call
message on the way out; `history` keeps it for persistence and rendering. It
lives in `call_api`/`stream_response` rather than `agent_turn` because *both*
paths replay history, and the streaming one is the easy one to miss: it has no
tools, so it looks like it cannot carry a tool-call message — and it can, when a
session that made tool calls switches to a non-tools model. A transform each
caller must remember is one a caller will not.

**Prefer the failure that is visible.** Nearly every bug in Scars is a silent
false negative: nothing raised, something quietly returned "there's nothing
here", indistinguishable from the truthful answer. When you add a guard, work
out which way its failure points — `tools.reserved_write_reason` fails open
because failing to resolve a path can only narrow what is writable; the
journal's git guard fails closed because failing to check can only widen what is
destroyed.

---

## Rejected designs

These look like the obvious next move. They were tried or thought through, and
they lose. Reopening one needs a new argument, not a fresh eye.

- **An in-process timer thread for routines.** Breaks decision 6, and a heartbeat
  has to fire when the REPL is closed. The OS scheduler calls the entry point.
- **One OS scheduler entry per routine.** Simpler, and it makes `trigger:` in the
  routine file decorative while the real schedule lives outside the vault in a
  second place, free to drift. Under the tick design a new routine needs no
  change to the OS scheduler at all.
- **cron in WSL.** Windows shuts idle WSL instances down and cron dies with them,
  so a 03:00 job runs only if a terminal happens to be open. `run-due.sh` still
  works under cron on native Linux; the supported path is Task Scheduler.
- **`inbox/` and `outbox/` at the repo root.** Existed briefly. It isn't code, so
  it'd have to be gitignored — and a gitignored folder in the repo is invisible to
  clones, outside the vault's backup, and destroyed by a fresh checkout. The vault
  pair is backed up and editable from Obsidian.
- **Widening `WRITE_ROOTS` so the mover can reach the vault.** The mover validates
  against its own `MOVE_ROOTS` precisely because it is not the model. The
  separation is the design; the two tuples are independent.
- **~~Starting LM Studio from WSL~~ — not a rejected design; it works.** Written
  up as impossible on three failures in one afternoon, then done first time from
  a cold machine (`legacy/BUGS.md`). Kept here as the standing caution: **this
  section stops people trying things, so an entry needs to have earned that.**
  Three failures are not proof of impossibility about something observed working.
- **Tightening the retrieval floor.** See the constants below. The signal isn't there.
- **A tighter model-is-thinking check than list membership.** The only available
  signal is the `:thinking` id suffix, and it miscalibrates —
  `deepseek-v4-pro:thinking` runs routines fine while `glm-5.2:thinking` empties
  every time. `ROUTINE_MODELS` is the judgement; the code guesses nothing.
- **Real `ON DELETE CASCADE`.** The right answer, and parked: SQLite can't add one
  without rebuilding the table, and the schema is already in flux. Belongs to the
  DB-layer rework, along with the duplicated vector-delete in
  `import_wiki.clear_chunks_for_message`.
- **Persisting reasoning.** Presentation-only on both paths. It isn't a valid
  input field, it would bloat context, and the DB holds messages, not scratch
  thinking. Same discipline for the budget notes spliced into `messages` — they
  ride on the request only, never on `history`.

---

## Constants with provenance

Numbers you can read off `config.py` and `search.py`. What you can't read off
them is what they were measured against, which is what makes them re-derivable.

**`MAX_DISTANCE = 1.08` is a lint filter, not a relevance judge.** Measured over
32 probes **on the wiki corpus**. The answerable band (0.696–1.065) and the
unanswerable band (0.995–1.194) *interleave* — `"what was agentmail about"` needs
1.065 while `"how do I tune a guitar to drop D"` scores 1.055 — so no threshold
separates them, and a relative metric lands on the same error rate. The floor is
therefore asymmetric: **admit generously**, because a rejected good hit is a
silent, confident "memory has no answer" while an admitted bad one reaches
`recall.py`'s grounded synthesis, which is told to say when the excerpts don't
cover the question. One failure is invisible, the other self-corrects. The old
1.024 lost 4 of 20 good phrasings, which is what "recall returns nothing" was.

- Phrasing noise alone spans ~0.09. Any future floor needs more headroom.
- **Re-chunking or swapping the embedding model invalidates the floor** — it is
  geometry-specific and the corpus is half of what it measures. Re-measure.
- `vec0` ranks by **L2**, not cosine. A cosine check is magnitude-blind and won't
  catch a normalisation change that moves every distance.
- **Record which corpus a constant was measured on.** The old 1.024 and its
  "total separation" were measured on the retired Anthropic export and filed as
  wiki numbers. Nothing had ever regressed; the baseline was mislabelled, and it
  cost a session to establish that.

**The tool turn's two budgets** (`TOOLS_MAX_CALLS_PER_TURN`,
`TOOLS_MAX_TURN_RESULT_CHARS`) had to land together. The call ceiling is generous
*because* the output ceiling makes generosity affordable: roam widely, read
narrowly. Raising the ceiling alone — which is what the symptom asks for — makes
the context problem strictly worse. They **exit differently, and that asymmetry is
load-bearing**: calls exhausted inserts `agent.LIMIT_MESSAGE` (a stub *we* wrote,
compared by identity in `runner`, so it must interpolate nothing) and fails a
routine; output exhausted takes the tools off the request for one more call so the
model answers in prose about a real partial job, and does not fail the run.

**A routine's ceiling is its own** (`ROUTINE_MAX_CALLS_PER_TURN` > the chat one).
The number was never about cost — it bounds how long a runaway loop runs before a
human interrupts it, and a routine has no human. `max_calls` is a parameter and
deliberately not on `ToolContext`: that object is the permission boundary, and a
call count is capacity, not permission.

**Connect and read are never one number, and this is the pair that bit.**
`httpx`'s single `timeout=` sets *connect*, *read*, *write* and *pool* alike, so
one value has to serve the slower quantity — and a dead port then costs the full
*read* budget to learn nothing was listening. Both layers split it:

| | connect | read | why read is that high |
|---|---|---|---|
| `embed.py` | 5s | 60s | a 100-chunk batch or a cold model load |
| `preflight.py` | 0.5s | 8.0s | LM Studio **JIT-loads** on demand: 1.71s for bge-m3 from unloaded |

`embed.py`'s old flat `timeout=60` × four attempts is the ~240s `/recall` hang.
`preflight.py`'s old flat `PROBE_TIMEOUT = 8.0` is the same bug one layer up.
**`PROBE_READ` is not slack** — cutting it to something that "looks like plenty
for a local call" turns every cold start into a confident red light over a
working embedder. A larger embedding model is the reason to re-measure it; the
healthy 0.157s never is.

Measured 2026-07-27 on Cas's machine: a live local embedder answers a real
`/embeddings` POST in **0.157s**, `lms server status` and `lms ps` ~0.33s,
`tasklist.exe` ~0.15s, and a dead local port on WSL **hangs rather than
refusing**, so it costs exactly the connect timeout. That is what buys the
traffic light its lack of a cache: 0.16s healthy and 0.5s broken is cheap enough
to ask on every hub render, and an answer you can always re-ask never has to be
aged.

**The retry budgets split for the same reason.** A 429 is a transient and
waiting helps; a refused connection is a *state*, and asking four times gets one
answer four times. `_DOWN_RETRIES = 2` rather than 1 only so a call can catch a
restart. `tests/test_embed.py` and `tests/test_connection.py` pin these **as
pairs**, not as values — retuning stays free, merging does not.

**The two read timeouts are not the same quantity, so don't unify them.**
`call_api` reads for 600s because non-streaming means no bytes arrive until the
whole completion is done — a thinking model inside a tool loop is legitimately
silent for minutes. `stream_response` reads for 300s, but httpx resets that clock
per chunk, so it bounds the *gap between deltas*. Title generation gets 60s
because it swallows every exception, and a hung title on the long timeout would be
ten minutes of silence followed by `(untitled)`.

**`_SUGGEST_CUTOFF = 0.6` was measured on a MODELS list, and that is half of
what it measures.** The model near-miss picker's difflib cutoff, looser than
`resolve_model`'s 0.7 because a suggestion is only offered, never acted on.
Over the eight ids in Cas's `MODELS` (2026-07-26): real near-misses land at 0.67
(`minimax 3`) and 0.69 (`deepseek pro`), pure noise (`zzzznothing`) reaches 0.47
against `glm-5.2:thinking`. 0.6 sits in that gap with room on both sides rather
than shaving one edge — difflib finds *something* for almost any input, which is
why the floor can't be 0. **Re-measure against a different MODELS list before
trusting it**, exactly as `MAX_DISTANCE` must be re-measured against a different
corpus. Note also that difflib is the *second* strategy: a word-substring pass
runs first, because a short query against a long id scores below any usable
cutoff (`minimax3` vs `minimaxminimaxm3`) while the word `minimax` is a plain
substring of every minimax id.

**Context colours are opinionated; the percentages aren't.** `ui.context_style` is
the single mapping read by the bar, the hub column and the post-turn nudge — they
were three literals away from disagreeing. 15/35 rather than 60/80, because a 1M
window is a vendor claim, not a promise that the last 900k tokens get the same
attention as the first.

**Splash resampling is box-average, not nearest, and that is specific to this
art** — a one-pixel rim light on black, which nearest-neighbour halving breaks
into dashes. Don't "fix" the bake resolution to match a terminal; the asset is a
source of truth that gets resampled.

---

## The recurring hazard: written in one place, parsed in another

Not one bug — a shape this codebase keeps producing. Every instance fails the same
way: a regex quietly stops matching, nothing raises, and the feature returns
"there is nothing here."

| written by | parsed by | what breaks on drift |
|---|---|---|
| `commands.py`'s `/remember` marker | `db._MARKER_RE` | recall markers stop parsing |
| `commands.py` / `import_anthropic.py` markers | `backfill.is_litter` | markers get embedded as content |
| `routines.append_log`'s line | `routines.last_run` | `on_failure` reads the wrong status |
| `routines.append_log`'s status word | `routines.last_success` | a weekly routine's week is marked absorbed, or never is |
| `tools.write_file`'s success line | `tools.written_path` | the run log says the run wrote nothing |
| `preflight.STATES` | `ui.CONNECTION_STYLE` | a connection state with no colour renders as a blank light |

The sixth row is a producer/parser pair **across a module boundary that cannot
be closed**: `ui.py` imports no cfc module by decision 6, so it cannot import
the state constants it maps. It is pinned by round-trip in
`tests/test_connection.py` — every state must have a rendering and every
rendering a state — and an unmapped state degrades to a dim `?` rather than
raising, because taking the hub down over a decorative light is the worse
failure of the two.

Same class, provider-side: `agent._is_empty_completion_400` and
`runner.looks_unclear()` match on wording nobody controls. Both are deliberately
**fail-safe in direction** — a reword degrades to the older, louder failure, never
to a new silent pass.

Two rules: **keep producer and parser in the same module** where the dependency
graph allows, and **pin them by round-trip, never against a literal.** A test
asserting `written_path("wrote /x (1 chars)")` passes forever while the real pair
drifts apart; `tests/test_tools.py` runs a real write and parses its real result.

**Add a seventh and add it to this table — unless the first rule can close it
instead.** That is what happened to the one that would have been the seventh:
`B-0.9.1-01` needed `agent._render_result` to recognise the gate's two human
verdicts, which the obvious way is a literal at each end. But `agent.py` already
imports from `commands.py` and nothing imports back, so the strings became
`commands.DENIED` / `SKIPPED` and the pair closed. **Check the graph before
adding a row** — a pair that *can* be closed and is merely pinned will drift
eventually, and this table is for the ones that genuinely can't be.
`tests/test_agent.py` still round-trips it, because an import is only a
guarantee while it is the thing being used.

---

## Scars

Bugs that were live and quiet. Each one is a class, not an incident.

**A deleted conversation stayed in the retrieval index.** Three bugs in one:
still-searchable content, orphaned rows, and — because SQLite reuses rowids — a
stale chunk *joining cleanly* to an unrelated live message, so `search` cited it
under a conversation the text never came from. 207 stale chunks and 195 vectors on
the live db. The repair rule is exact rather than heuristic, which is what made it
safe to run: a chunk is stale if its message is gone *or* if
`chunks.session_id != messages.session_id`, and the second cannot arise in normal
operation.

**One Ctrl-C bricked a session in place.** The orphaned-tool-call fix existed at
replay time only, so reopening the session repaired it — which is exactly what made
the failure look intermittent and provider-shaped rather than local and
deterministic.

**A routine that did nothing logged `ok`.** Three separate doors into the same
failure: an empty completion summarised to `""`; `LIMIT_MESSAGE` was *non-empty*,
so a halfway-stopped run rendered a respectable log line; and a model can finish a
clean loop while its own answer says it couldn't do the task ("those files are
outside my allowed roots"). That last one had a nightly job doing nothing for weeks.
Hence `review` as a **second, orthogonal flag** — kept out of `status` so
`on_failure` doesn't retry a working routine at full API cost.

**A scheduled run inherited the interactive chat default model** — which was the
one model that empties 3/3 re-rolls. `--run-due` passes `model=None`, so before
`ROUTINE_MODELS` existed the unattended path silently ran on whatever chat was
using.

**`trigger: 0300` was read as 192.** YAML 1.1 types a leading-zero digit string as
octal, so the obvious way to write 03:00 arrived as an integer and validation
rejected a trigger nobody wrote. Bites `0000`–`0777` only — i.e. exactly the hours
these jobs run. **Any other digit-string field is exposed to the same trap.**

**Tab completion had silently stopped existing.** `complete.py` wired into
readline; input moved to prompt_toolkit, which never consults it. Nothing raised,
`install()` kept returning True, no test covered it. It didn't break — it stopped
happening.

**The golden baseline was pinning `config.py`.** Adding a model to your own config
failed `check` on lines that say nothing about the code; so did rotating the API
key. Anything a baseline pins that lives in config rather than in source is this
bug. They're forced to fixture values in `capture()` now.

**The chunker sliced mid-word at both edges** — 22 of 26 chunks opened on a
fragment, embedding leading garbage as content. It sat in `BACKLOG.md` for six days
precisely because nothing failed; a bad slice is embedded, stored, and thereafter
visible only as slightly worse ranking.

**The collision walk compared a stored filename against a resolved stem**, so it
silently never advanced and `/add relax` filled the system prompt forever. Found by
driving it, not by reading it.

**`is_litter` matched one marker against a whole concatenated string** instead of
per line, so concatenated markers got embedded as content. Shipped that way once.

**Four `console.print` calls printed their own markup tags.** `ui.console` is
`Console(markup=False)` — chat content must never be reinterpreted as markup —
so `[dim]recall cancelled.[/dim]` renders the brackets. One shipped in v0.8.2,
the release named for that very note, visible on every slow embedder from the
day it landed: it survived a testing pass because **a wrong-looking line still
tells you the true thing.** Styled output is `style=`, never brackets.

**A prose sweep nearly renamed the persisted `[:remember …]` marker** during the
`:`→`/` flip, which would have stopped every existing marker row from parsing. When
you sweep for a prefix, storage formats are not prose.

---

## Two time bases, and one conversion point

**`db.py` is the only module that stores UTC.** `new_session` and `save_message`
write `datetime.now(timezone.utc).isoformat()`. Everything else — `routines`,
`schedule`, `runner`, `mover`, `backup`, `hub._freshness` — writes and compares
**local naive** time. That split is not going away casually; the db's offsets are
the correct thing to store and the rest is correct for what it does.

So **`ui.format_ts` is the conversion point**, and it converts only when the
value carries an offset. A naive timestamp is left alone deliberately: assuming
UTC would move the one set of times that was already right. Anything new that
prints a db timestamp goes through `format_ts`; anything new that *stores* one
should store an offset.

This was live and quiet until v0.8.1 — the hub stacks Recent chats (db, UTC)
directly above Routines (run log, local), so the two panels ran two hours apart
on the same screen and neither looked wrong on its own. **The golden harness
cannot catch this class**: `SCRUB` normalises timestamps on both sides, so a
timezone bug is invisible there by construction. It is pinned in
`tests/test_hub.py` against an offset computed five hours from the host's, since
a test written against a literal `+00:00` passes without the conversion on a
UTC machine.

**`ui.format_date` is the date half, and it exists because `format_ts` returns
`YYYY-MM-DD HH:MM`** — a site wanting only a date could not call it, which is
why three `created_at[:10]` slices survived the v0.8.1 fix. `[:10]` reads the
date off the **stored** string, so a session created after 22:00 local was filed
under tomorrow: session #24 stores `2026-07-19` and is locally `2026-07-20`. All
three sites converted in v0.9, `export.py`'s full timestamp included — an export
in the vault in a different time base from the rest of the vault is itself the
trap.

## The environment

**The skeleton, written down v1.0 (`W-03`).** cfc is understandable from its own
source; the system around it was not written anywhere, and the failure mode of
that is a rebuild discovering something lived in exactly one place. `README.md`
carries the layout; this is the failure modes.

**One computer, two filesystems that fail independently.** ext4 (`~`) is erased
by `wsl --unregister`; NTFS (`/mnt/c`) is not. Every durability question here
reduces to which side a file is on.

| | side | what erases it |
|---|---|---|
| `~/projects/cfc` — the code | ext4 | a WSL reset. Recoverable: GitHub |
| `~/.cfc/` — `chat.db`, `backups/`, `errors.log`, `schedule.log` | ext4 | a WSL reset. **Not recoverable** |
| `~/vaults/wiki.git` — the vault's history | ext4 | a WSL reset. Recoverable only as far as the last manual push |
| `<vault>` — the notes | NTFS | a Windows loss |
| `VAULT_PATH` — exported transcripts | NTFS | a Windows loss |

**The vault straddling both sides is deliberate and the split is load-bearing.**
Files on NTFS so Obsidian and Windows' backup reach them; `.git` on ext4 via a
`gitdir:` pointer because git over 9p is slow. So **losing Windows loses the
files but not the history, and losing WSL loses the history but not the files** —
two independent failures, neither individually fatal. That property is worth not
breaking by "tidying" the `.git` back into the vault.

**`VAULT_PATH` is not the vault** and this is the one naming trap in the layout
(`W-0.9.1-01`, still open). It is the chat *export* destination — a different
folder on the Windows side. `VAULT_ROOT`, three lines below it in `config.py`, is
the actual vault. Nothing enforces the distinction and both are strings.

**The database is the single point of failure, stated so it is a decision**
(`Q-01`). `backup.py` keeps ten rolling snapshots **on the same disk as the
original** — right for what it defends against (a torn write, a bad migration, a
mistake, all of which have happened) and never meant to be an off-machine copy.
The auto-exports are not one either: 28 MB of database against 1.5 MB of
exported Markdown (2026-07-29), and the difference is not compression — the
exports carry the chat text, while the retrieval index, the vectors, the routine
transcripts, the token accounting and the tool metadata exist only in that one
file. Anyone making this durable should note the chunk/vector schema is in flux
(`W-07`, 2.0): a scheme that copies the file survives the rework, one that
exports the schema does not.

- WSL2/Ubuntu on Windows. Vault on `/mnt/c`, reached Linux→Windows (fast); never
  `\\wsl.localhost` (slow, flakier).
- **`<vault>/00 inbox` is where Cas leaves briefs. `<vault>/99 outbox` is the only
  writable path in the system** — and one directory inside it, the routine log dir,
  is closed to `write_file` separately, because containment alone admits it and a
  model can decide to tidy its own audit trail without being asked.
- The vault is a git repo (`<vault>/.git` → `~/vaults/wiki.git` via a `gitdir:`
  pointer). **It has a remote as of 2026-07-27** — `origin` is a *private*
  GitHub repo (`cfc-vault-cas`), `main` tracks `origin/main`, and the ext4-only
  history that v1.0 called out as the most urgent chore in the project is no
  longer the exposure it was.
- **cfc never pushes, and since the remote arrived that is a choice rather than
  a description.** `wikigit.py` issues no `push` and no `remote`;
  `tests/test_wikigit.py` pins both absent. The reasoning is in `wikigit.py`'s
  header: a push is a network call with other people's failure modes (auth,
  connectivity, a rejected non-fast-forward), from a REPL that would block for
  the duration, and it owes an answer to *what does a failed push do to a commit
  that already succeeded*. Teaching it to push is a design decision.
- **`/wiki commit` says what cfc did, not what the repo has** (`_LOCAL_ONLY`,
  one constant across both commit paths). It used to print `local only — this
  repo has no remote`, true when written. Worth keeping because it runs opposite
  to this project's usual hazard: the conclusion stayed true while its *reason*
  went false — and the false reason was the half saying nothing could be done,
  at the moment something could. A warning that talks you out of the fix is
  worse than no warning.
- Embeddings come from a **separate endpoint** to chat: self-hosted `bge-m3` on LM
  Studio. `networkingMode=mirrored` means localhost reaches the Windows host; the
  old NAT gateway IP no longer resolves at all, and don't put one back — a stale
  one now fails closed instead of drifting. "Serve on local network" must stay on,
  and the model id is `text-embedding-baai-bge-m3-568m`, not plain `bge-m3`.

  **Why separate, since the code only shows that it is:** the corpus is
  personal, embedding it is cheap and constant, and posting every note you write
  to a third party to get a vector back buys nothing. Two properties fall out —
  **memory keeps working when the internet doesn't**, and **the chat provider
  can be swapped without re-indexing.** The cost is a second process that has to
  be running, which is why `preflight.py` and the connection light exist. The
  coupling runs one way only: swapping the *embedding* model invalidates
  `MAX_DISTANCE` and the whole index; swapping the chat model costs nothing.
- **LM Studio running is not the same as its server running.** The tray app can sit
  there for weeks with the server off; that's the state `preflight.py` exists for.
- Windows Task Scheduler fires `run-due.sh` on a fixed tick. The wrapper redirects
  its own stdout to `~/.cfc/schedule.log` before anything that can fail, because the
  recommended hidden task discards stdout — hiding the window is only safe because
  the output went somewhere.

## Testing

`tests/golden.py` is a **characterization harness**, not unit tests: it pins the
REPL's exact stdout for every no-API command, so a refactor meant to change nothing
is proven to. `record` re-baselines — inspect the diff first, it exists to catch
the changes you *didn't* intend. `SCRUB` normalises timestamps, paths and the key
digest on both sides at compare time, so adding a rule fixes a baseline without
re-recording.

Twenty-five unit suites beside it; none needs an API key. **What is
hand-verified, stated rather than implied** (`W-02`) — a version claiming things
are verified by something that doesn't get tired owes the reader the other half
of the sentence:

| | |
|---|---|
| the chat turn against a **real** API | **not automatable, and not a gap.** Against a stub it is covered — `tests/test_turn_paths.py`, `test_agent.py`, `test_empty.py`. What a real provider adds is its own behaviour, which is what `BUGS.md`'s `B-01` is about and what no test can assert |
| retrieval quality | **not automatable.** A judgement, not an assertion. The *states* around it are pinned (`test_memory_states.py`); whether the right chunk came back is what `MAX_DISTANCE`'s 32 probes measured by hand, and re-measuring is the only honest method |
| the two answer **panels** | **not comparable, and the reason is structural.** The tool path renders through `agent.render_answer`; the streaming path renders inside `api.stream_response`, delta by delta, because it paints as it arrives. Stubbing the provider — the right place — takes the streaming render with it |
| how the splash **looks** | **not automatable.** The compositor and the import graph are pinned (`test_splash.py`); a one-pixel rim light on black is not |
| `/export`'s output | **a real gap, and honestly automatable.** Owed, not impossible — write to a temp dir and read it back. Left out of v1.0 by scope, not by argument |
| `/routine`'s listing and run commands | **a partial gap.** Creation is covered as of v1.0 (`test_routines.py`), `run_routine` since v0.5; `show_routines` and `do_routine` are not |

**A list of what isn't tested goes stale in the safe-looking direction.** The
picker sat on that table as hand-verified for two releases after `test_hub.py`
already drove it — adding a test is the moment nobody thinks to edit the docs,
and the result is a version planning work that is already done.

Three habits worth keeping, all learned here: **verify a guard by disabling it**
and watching the assertions fail (seven of them for the journal's git guard);
**patch the seam, not `config`** — `test_routines` patches
`routines.routine_dir` because patching config misses anything that read the
value at import; and **compare two implementations to each other rather than
to a literal** where there are two — `test_turn_paths.py` asserts the tool path
ends exactly as the streaming path does, which cannot pass while they disagree
and needs no edit when they agree differently.

## Open threads

Only what is genuinely unsettled. A thread that closed is a `TRACKER.md` row and
a changelog entry, not a paragraph here.

- **A provider 400 on tool turns, and the list of things to try is empty**
  (`B-01`, `BUGS.md`). Two candidate causes fixed in v0.5, the interrupt theory
  given its structural fix, the last suspect (`api.wire_messages`) spent in
  v0.9. None of that is confirmation — there is no reproduction, so there is no
  test that any of it *worked*. It closes by recurring and being explained, or
  by absence across a window whose length was never stated (`Q-0.9.2-01`), which
  is the weaker claim and has to be named as such. `errorlog.py` makes the watch
  real: the error line is captured when it fires, so neither route depends on a
  human reading scrollback in time. Blind spots (private chats, non-`httpx`
  exceptions) are with the entry.
- **Scheduled runs fire; their outputs are still trusted rather than read.** The
  tick is driven and settled (`Q-0.9.1-04`). *Did the routine do the right
  thing* is a second claim and nobody has checked it.
- **The connection light has not been watched over a working day.** All three
  fix paths were driven on 2026-07-27; ordinary use is what is left.
- **v0.8.2's model fallback misses the case it was built for** — auto-revert
  arms only for ids it doesn't recognise, so a *broken id that is in* `MODELS`
  goes unhandled. `BACKLOG.md`.
- **The DB layer is anticipated to be reworked** (`W-07`) — treat the
  chunk/vector schema as in flux. Intended shape: SQLite stays the source of
  truth, sqlite-vec is an index over it.

**One closed thread is kept, because what closed it is reusable.** Zero recall
hits are three distinguishable outcomes (`W-01`, v1.0) — embedder never answered
(`embed.EmbedUnavailable`), nothing indexed (`search.why_empty`), or searched and
missed. The routine half was never built and never can be as things stand: **no
routine can reach recall.** The four tools are `list_dir`, `read_file`, `grep`
and `write_file`, and `commands.py` is the only module importing `search` or
`recall`, so there is no call site a routine's zero-hit policy could live at. The
transferable half is that the draft scoping it assumed otherwise: **a policy for
a caller that doesn't exist is a spec nobody can execute**, and it reads exactly
like ordinary owed work until someone greps for the import. Successor in
`ROADMAP_BEYOND.md`, number unclaimed.
