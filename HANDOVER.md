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

## The other documents

| | |
|---|---|
| `README.md` | how a human uses it. Coupled to this file — rewrite one, rewrite the other |
| `CHANGELOG.md` | what shipped, with the reasoning. Newest first. Log every shipped change in the same commit |
| `BACKLOG.md` | deferred and still working. **Read it before touching the memory layer** |
| `BUGS.md` | broken and known |
| `legacy/` | the closed entries of both, frozen whole. **A closed entry moves here and leaves no stub** — see below |
| `ROADMAP.md` | Cas's. Propose, don't edit. `ROADMAP_PRIVATE.md` (gitignored) holds the forward plan |
| `CLAUDE.md` | who you're working with and the repo rules |

**The archive rule, changed 2026-07-27.** A closed `BUGS.md`/`BACKLOG.md` entry
used to leave a struck-through stub behind with its fix date. It doesn't any
more: it moves to `legacy/`, whole, and the live file holds open entries only.
The old rule is why those two files reached 283 and 897 lines with three and
five live entries between them, and an unreadable list is one nobody checks.

Two things hold it up and both are load-bearing. **`CHANGELOG.md` is the index**
— every shipped fix is logged there in the same commit, so nothing needs the
archive to answer "was this fixed, and why that way". And **the archive keeps
the original report**, which `CHANGELOG.md` never carried; the symptom as first
written is frequently the valuable half, and sometimes its *wrong* premise is
the finding (`MAX_DISTANCE`, below). That is what makes it an archive rather
than a delete, and it is the reason `legacy/` is tracked in git rather than
gitignored — a gitignored archive is invisible to clones, outside every backup,
and destroyed by a fresh checkout, which is the same argument that killed
`inbox/` at the repo root.

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
9. **Wiki recall keys off the frontmatter id, never the filename.** Renaming a
   page keeps its recall identity. Recall stays wiki-only; the chat log is indexed
   (`source='chat'`) but excluded until hybrid lands. Auto-embed is best-effort and
   must never break a turn.
10. **A private chat's isolation is the connection, not a flag.** It runs against
    `db(":memory:")`, so every `conn`-driven write — including the ones
    `agent_turn` makes on its own — is already a no-op against disk. `private=True`
    gates only the three paths that *escape* the connection: auto-embed (opens
    `DB_PATH` directly), auto-export (writes to the vault), and model file-writes
    (empty write roots). A new disk-writing path either goes through `conn` or
    silently defeats this, and owes `tests/test_private.py` a negative.
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
13. **The command surface is two lists that must agree**, and they are checked
    rather than maintained: `run_session` asserts its handler table equals
    `parse.VERBS`. An unrecognised verb falls through **to the model** — so a verb
    that is documented but missing from the table isn't an error message, it's an
    API call and a confused answer. **Retiring a word therefore means aliasing
    it, not deleting it.** `RETIRED` was a third list until v0.9; deleting it
    without moving its entries into `ALIASES` would have turned `/models` and
    `/prompts` back into prose, which is an API call each. An `ALIASES` value may
    be a *phrase* (`models` → `list models`) precisely so a retired word can map
    to a command that takes arguments. The one word with no alias is `detach`,
    whose replacement `/remove #<n>` changes the argument's shape — that is the
    bar for letting a word go.
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

## Two rules that generated most of the above

**Use a model for judgement under ambiguity; use code for anything with a right
answer.** The mover doesn't ask a model where a file goes. `/wiki` doesn't ask a
model to commit. The retrieval floor doesn't try to judge relevance — it hands
excerpts to a model that can say "these don't answer it."

**Separate states where they are separable, which is usually at the exception.**
An unreachable embedder and an empty result set are the same silence by the time
they reach a console, and one of them is a confident lie. They are cleanly
distinct exactly once — at the point where one is an exception and the other is
`[]` — so `embed.py` records which it saw *while catching it* and raises
`EmbedUnavailable` rather than a message. Re-deriving a state further up, from
wording or from a count, is the recurring hazard rebuilt: it works until someone
improves a sentence. If you find yourself inferring which failure happened,
you are at the wrong end of it.

**A format the provider needs and we don't goes at the wire boundary, not at the
call site.** `api.wire_messages` drops an empty `content` from a tool-call
message on the way out, while `history` keeps it for persistence and rendering.
It lives inside `call_api`/`stream_response` rather than in `agent_turn`,
because *both* paths replay history and the streaming one is the easy one to
miss — it has no tools, so it looks like it cannot carry a tool-call message,
and it can: a session that made tool calls and then switched to a non-tools
model replays exactly those. A transform each caller must remember is one a
caller will not.

**Prefer the failure that is visible.** Nearly every bug in the Scars section is
a silent false negative: nothing raised, something just quietly returned "there's
nothing here", which is indistinguishable from the truthful answer. When you add
a guard, work out which direction its failure points — `tools.reserved_write_reason`
fails open because failing to resolve a path can only narrow what is writable;
the journal's git guard fails closed because failing to check can only widen what
is destroyed.

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
- **~~Starting LM Studio from WSL~~ — not a rejected design, an open question.
  Moved to `BUGS.md`.** This entry claimed it was impossible on the strength of
  three failed attempts, and Cas then reported that the desktop shortcut used to
  do it. Three measurements failing is not proof of impossibility when the
  thing has been observed working; see `BUGS.md` for what was measured and the
  untested candidate. Recorded here because "we tried it and it can't be done"
  is exactly the kind of note that stops the next person trying, and it was
  written after one afternoon.
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
32 probes **on the wiki corpus** (write the corpus down — see below). The
answerable band (0.696–1.065) and the unanswerable band (0.995–1.194) *interleave*:
`"what was agentmail about"` needs 1.065 and `"how do I tune a guitar to drop D"`
scores 1.055. No threshold separates them, and a relative metric cancels ~70% of
phrasing noise and lands on the same error rate. So the floor is set
asymmetrically — **admit generously**, because a rejected good hit is a silent,
confident "memory has no answer", while an admitted bad one reaches `recall.py`'s
grounded synthesis, which is told to say when the excerpts don't cover the
question. One failure is invisible; the other self-corrects. 1.024 lost 4 of 20
good phrasings, which is what "recall returns nothing" actually was.

- Phrasing noise alone spans ~0.09. Any future floor needs more headroom than that.
- **Re-chunking or swapping the embedding model invalidates the floor** — it is
  geometry-specific and the corpus is half of what it measures. Re-measure, don't
  re-run the old number.
- `vec0` ranks by **L2**, not cosine. A cosine check is magnitude-blind and won't
  catch a normalisation change that moves every distance.
- **The provenance lesson itself:** the old 1.024 and its "total separation" were
  measured on the retired Anthropic export and recorded as wiki numbers. Nothing
  had ever regressed — the baseline was mislabelled, and it cost a full session to
  establish that. Record which corpus a tuned constant was measured on.

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

**`embed.py`'s two timeouts are not the same quantity either, and this pair is
the one that bit.** `httpx`'s single `timeout=` sets *connect*, *read*, *write*
and *pool* alike, so one number has to serve the slower quantity — and a
`timeout=60` meant every attempt against a dead embedding server waited out the
full read budget just to learn nothing was listening. Four attempts of that is
the ~240s `/recall` hang. Connect is 5s (the live endpoint answers in 0.18s);
read stays 60s, because a 100-chunk batch or a cold model load legitimately
needs it. **The retry budgets are split for the same reason the timeouts are:**
a 429 is a transient and waiting helps, a refused connection is a *state* and
asking four times gets one answer four times. `_DOWN_RETRIES = 2` rather than 1
only so a call can catch a restart. `tests/test_embed.py` pins the timeouts **as
a pair**, not as two numbers — retuning stays free, merging does not.

**`preflight.py` learned the same lesson one layer up, and the measurement is
what bought the traffic light.** `PROBE_CONNECT = 0.5` / `PROBE_READ = 8.0`
replaced a single `PROBE_TIMEOUT = 8.0` for exactly `embed.py`'s reason — one
number has to serve the slower quantity, so a *dead* port cost the full read
budget to learn nothing was listening. Measured 2026-07-27 on Cas's machine: a
live local embedder answers a real `/embeddings` POST in **0.157s**; `lms server
status` and `lms ps` are ~0.33s; `tasklist.exe` is ~0.15s; a dead local port on
WSL **hangs rather than refusing**, so it costs exactly the connect timeout.
Those numbers are the argument for the light having no cache at all — 0.16s
healthy and 0.5s broken is cheap enough to ask on every hub render, and an
answer you can always re-ask is one you never have to age. **Re-measure before
raising either**, and keep them a pair; `tests/test_connection.py` pins the
relationship, not the values.

**`PROBE_READ = 8.0` is not slack, and this is what it is for.** LM Studio
JIT-loads a model when a request names it, so the first probe after a restart
pays the load inside the read budget: 1.71s for bge-m3, measured with the model
explicitly unloaded. Cutting the read timeout to something that "looks like
plenty for a local call" would turn every cold start into a confident red light
over a working embedder. A larger model would need more, which is the number to
re-measure — not the healthy 0.157s, which is never the constraint.

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

**Add a sixth and add it to this table.**

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
so `[dim]recall cancelled.[/dim]` renders the brackets. One of them was the
embedder retry note **shipped in v0.8.2**, the release named for that note, and
it was visible on every slow embedder from the day it landed. It survived a
testing pass because a wrong-looking line still tells you the true thing. Styled
output is `style=`, never brackets; found by driving the feature, not by reading
it.

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

**All three raw sites were converted in v0.9**, and the shape of the fix is a
second helper rather than a call to the first: `format_ts` returns
`YYYY-MM-DD HH:MM`, so a site that only wants a date could not simply call it —
which is precisely why three `created_at[:10]` slices survived the v0.8.1 fix.
`ui.format_date` is that date half, beside it, at the bottom of the graph.

`[:10]` was never a cheap `format_date`. It reads the date off the **stored**
string, so a session created after 22:00 local was filed and labelled under
tomorrow. Confirmed live rather than reasoned about: session #24 on Cas's own
db stores `2026-07-19` and is locally `2026-07-20`. Cas's call (2026-07-27) was
to localise all three including `export.py`'s full timestamp — an export in the
vault in a different time base from the rest of the vault is itself the trap.

## The environment

- WSL2/Ubuntu on Windows. Vault on `/mnt/c`, reached Linux→Windows (fast); never
  `\\wsl.localhost` (slow, flakier).
- **`<vault>/00 inbox` is where Cas leaves briefs. `<vault>/99 outbox` is the only
  writable path in the system** — and one directory inside it, the routine log dir,
  is closed to `write_file` separately, because containment alone admits it and a
  model can decide to tidy its own audit trail without being asked.
- The vault is a git repo (`<vault>/.git` → `~/vaults/wiki.git` via a `gitdir:`
  pointer). It has **no remote**, and `wikigit.py` says so after every commit — a
  push that silently no-ops today is one that silently starts working the day a
  remote appears.
- Embeddings come from a **separate endpoint** to chat: self-hosted `bge-m3` on LM
  Studio. `networkingMode=mirrored` means localhost reaches the Windows host; the
  old NAT gateway IP no longer resolves at all, and don't put one back — a stale
  one now fails closed instead of drifting. "Serve on local network" must stay on,
  and the model id is `text-embedding-baai-bge-m3-568m`, not plain `bge-m3`.
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

Twenty-five unit suites beside it; none needs an API key. What they cover is
readable from the files. What they **don't**: the chat turn against a real API,
retrieval quality, `/export`'s output, the picker, `/routine`, and everything about
how the splash actually looks. Those are hand-verified.

Two habits worth keeping, both learned here: **verify a guard by disabling it** and
watching the assertions fail (seven of them for the journal's git guard), and
**patch the seam, not `config`** — `test_routines` patches `routines.routine_dir`
because patching config misses anything that read the value at import.

## Open threads

- **v0.8.2 has had one clean play-test** (Cas, 2026-07-27): every previously
  reported issue fixed, nothing new, and the model fallback behaved. What that
  pass does *not* cover is a broken id that is in `MODELS` — the auto-revert
  arms only for ids it doesn't recognise, so the case it was built for is the
  case it misses. See `BACKLOG.md`. Sustained use is still the open half of this
  thread.
- **The first *scheduled* routine run still hasn't happened** (v0.7's ST/MT jobs
  are waiting on a real tick). Read the first scheduled outputs rather than
  trusting the prompts.
- **`preflight.py`'s fix paths are no longer an open thread — all three states
  were driven on 2026-07-27.** Red **failed** and is now closed by measurement
  (see "Starting LM Studio from WSL" in Rejected designs): it is not fixable
  from WSL and the code says so instead of trying. Orange **worked** — `lms
  server start` fired for the first time and took it to green in 1.4s. And
  `lms load` turns out to be **near-unreachable**: LM Studio JIT-loads on
  demand, so an unloaded model does not fail the probe, it just makes it slow
  (1.71s vs 0.15s). The branch is kept because JIT is a setting rather than a
  guarantee. What replaces this thread is ordinary use: the light has never
  been watched over a working day.
- **A provider 400 on tool turns is open, and the list of things to try is now
  empty** — `BUGS.md`. Two candidate causes were fixed in v0.5, the surviving
  interrupt theory got its structural fix, and v0.9 spent the last suspect
  (`api.wire_messages`). None of that is confirmation: there is no reproduction,
  so there is no test that any of it *worked*. It closes on the next occurrence
  settling it, or on absence across the 0.9 → 1.0 window — a weaker claim than
  "fixed", and v1.0's note has to say which one happened rather than let an
  empty `BUGS.md` imply the stronger one.
- **Zero recall hits are now three distinguishable outcomes** (v0.9): the
  embedder never answered (`embed.EmbedUnavailable`), nothing is indexed
  (`search.why_empty` → `EMPTY_INDEX`), or the corpus was searched and missed.
  What is *not* built is the routine half, and the reason is worth recording:
  **no routine can reach recall.** The four tools are `list_dir`, `read_file`,
  `grep` and `write_file`, and `commands.py` is the only module that imports
  `search` or `recall` at all. The draft that scoped this assumed otherwise.
  So the distinction is made where it originates rather than at a call site
  that doesn't exist — when a recall tool lands, it inherits a typed exception
  instead of needing one retrofitted, and *that* is when a zero-hit routine
  policy becomes a real question.
- **The DB layer is anticipated to be reworked** — treat the chunk/vector schema as
  in flux. The intended shape is "SQLite stays the source of truth, sqlite-vec is an
  index over it".
