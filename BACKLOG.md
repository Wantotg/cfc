# Backlog

Things found in passing and deliberately not fixed, so they don't get lost.
Nothing here is urgent — this is a hobby project and it all still works.

Add to this rather than fixing on the spot when something turns up mid-task.
CLAUDE.md is for how the project works; this is for what's still owed.

---

## ~~`/routines` isn't an alias, so it reaches the model.~~ — FIXED (v0.8.2, 2026-07-26)

**Fixed:** one line in `parse.ALIASES`. The other verbs were checked for the
same trap while it was open — the remaining plurals a hand reaches for
(`prompts`, `models`, `tags`) are already caught by `RETIRED`, which is due for
deletion in v0.9. **Worth a thought when it goes:** those words stop being
commands and become prose again, so `/models` will start reaching the model
exactly the way `/routines` did. This entry is the argument for promoting a
couple of them to aliases rather than simply deleting the dict.

Also note `tests/test_parse.py` used `/routines` as its example of the prefix
trap (`":attached".startswith(":attach")`). The guard is kept; its example moved
to `/helper`, because a deliberate alias is the opposite of the accidental
prefix match it was guarding against.

Original report below.

**Found:** 2026-07-26, Cas's 0.8.1 testing pass.
Description: `parse.ALIASES` has three entries and `routines` is not one of
them, so `/routines` is an unrecognised verb — which by invariant 13 is not an
error message but a **fall-through to the model**. Typing the plural costs an
API call and returns a confused answer about routines rather than the list.
Working as designed and still the wrong outcome for an obvious plural.
Suggestion: one line in `ALIASES`. Worth a glance at the other verbs for plurals
a hand reaches for by reflex while it's open.

## ~~`/list routine` prints the vault's absolute path.~~ — FIXED (v0.8.2, 2026-07-26)

**Fixed, and it turned up something bigger than the display.** This entry said
to decide once whether cfc shows paths relative to `VAULT_PATH`. It can't:
**`VAULT_PATH` is the export destination, not the vault** — on Cas's machine
`/mnt/c/Users/disse/backup/cfc/cfc_chat_backup`, not under the vault at all —
and `/config` was labelling it "Vault path:". There was no vault-root setting
anywhere. `ROUTINE_DIR`, `WIKI_DIR`, `JOURNAL_DIR` and `MOVE_ROOTS` are each
configured independently, every one of them commented `<vault>/…`, describing a
root that existed in the documentation and nowhere in the code.

So: a new **`VAULT_ROOT`**, display-only, read with `getattr` so an older
`config.py` keeps working, empty meaning "print in full". `ui.vault_relative`
does the trimming — one implementation, as this entry asked, living next to
`format_ts` because `ui.py` is the bottom of the dependency graph and takes the
root as an argument rather than importing config. `/config` prints both lines
under their real names now.

**Still only used in one place**, deliberately. Every other path cfc prints was
left alone rather than swept: some of them are the answer to "where exactly is
this", where the full path is the point. The helper is there when a site wants
it.

Original report below.

**Found:** 2026-07-26, Cas's 0.8.1 testing pass.
Description: the header reads
`Routines (/mnt/c/Users/disse/cooking for cats/06 metadata/routines)` — the
whole WSL mount prefix for a path whose only informative part is the tail. Cas
asked for `(/cooking for cats/06 metadata/routines)`.
Suggestion: display vault-relative. Note this is display only and there is more
than one such header — decide once whether cfc shows paths relative to
`VAULT_PATH` generally, and if so put the shortener somewhere shared rather than
formatting at each site. A second copy of "trim the prefix" is how one gets fixed
and the other doesn't.

## Three timestamp sites still print UTC. v0.8.1, 26-07-2026
**Found:** 2026-07-26, fixing the hub's clock (`CHANGELOG.md`). `ui.format_ts`
now converts, and `hub.py` was its only caller — these three read the db
directly and were left alone rather than swept, because two of them are
arguably correct and the third is a one-day edge.
Description:
- **`export.py:186`** writes the message timestamp into the exported markdown as
  the raw stored ISO string, offset and all. Defensible: an export is a data
  file and an unambiguous absolute timestamp is the right thing in one. It is
  also the only place in the vault that isn't local time, which is the argument
  the other way.
- **`export.py:108`** takes `created_at[:10]` for the export filename's date
  part. A session created after 22:00 local gets tomorrow's date in its
  filename.
- **`commands.py:1022` and `recall.py:40`** take `(created_at or "")[:10]` for
  the date label on a recall excerpt. Same one-day edge, display only.
Not urgent, and the first one may be a decision rather than a fix. Deliberately
not swept: `format_ts` returns `YYYY-MM-DD HH:MM`, so none of the three can just
call it — the two `[:10]` sites want a date and `export.py` wants a full
timestamp, so this is three small decisions and not one substitution.
See `HANDOVER.md`, "Two time bases, and one conversion point".

## ~~":wiki commit <message>" commits all changes, even when inspecting a specific diff.~~ — FIXED (2026-07-24)

**Fixed:** `:wiki` grew a `<action> <scope> <granularity>` grammar. Granularity
`file` runs a numbered picker over the changed files in scope and diffs/commits
**only** the chosen one, via a `paths=[…]` pathspec — the same containment as the
scope pathspec, one level finer, pinned in `test_wikigit.py` (commit one wiki
file, assert the other stays uncommitted). And `:wiki commit vault` (formerly
`all`) now asks `[y/N]` at folder granularity — the whole-repo sweep that
committed 202 files at once. Both halves of this entry, in one change.

Note the framing shifted during the fix: the move/stamp step is `:file` (the
mover), not `:wiki commit` (git). "Timestamp and move the files" was never
`:wiki commit`'s job — it commits what's already in the corpus. Per-file *commit*
is the git half; per-file *filing* stays `:outbox`/`:file`, and the two are kept
separate so the `:updatedb` re-import still sits between them.

Original report below.

Description: The command :wiki diff "file" allows user to inspect the diff on file level vs wiki db level, but the commit is wiki db level, not file.
Problem: user is viewing a single view, a commit there implies a commit on for the diff that is being inspected, not the entire wiki db. Start with file #1 and commiting that, means that now rest of the diff is NOT inspected, and commited -> script timestamps and moves the files.
Suggestion: inspecting individual diff -> commit -> commits only that diff. Confirms the timestamp, and accapted changes.
Also: :wiki commit all should give a (y/n) warning 'are you sure'. (may be implemented, was no diff to test this yet.)

## ~~chat selection screen shows routines that failed at their task, but performed their routine:: "ok - timestamp."~~ — FIXED (2026-07-24)

**Fixed:** the realisation underneath it — one ok/failed bit can't carry two
facts (did the loop run + did the model actually do the task) — is now two
signals. `status` stays loop-health (ok/failed); a second, orthogonal `review`
flag rides alongside it in the run log (`ok (review)`), computed by
`runner.looks_unclear` from the model's final message (first-person / jail-block
phrases like "I cannot", "outside my allowed roots", biased to over-flag).
`last_run` returns `(status, ts, review)`; the hub panel and `:routine` show a
yellow **review** distinct from red **failed** and dim **ok**, and `do_routine`
says so live. Kept out of `status` on purpose: the run didn't fail, so
`on_failure` must not retry it. Heuristic and fail-safe — reword the refusals and
it degrades to a plain `ok`, never a false `failed`. Pinned in
`tests/test_routines.py`.

Original report below.

Transcript: **2026-07-24 12:20:36** — ok — I cannot perform this task. The `mt memory.md` and `lt memory.md` files live in `/mnt/c/Users/disse/cooking for cats/03 resources/tiered memory/`, which is outside my allowed readable roots (`99 outbo… (42s, session 87)
That is good and bad, report of the model came through, so that's ok. But the script needs to read the models message and flag certain keywords/phrases. Routine overview should show that the routine worked (the ok) but also flag the user that the log shows something irregular, to be inspected. "last routine performed at *timestamp*, result unclear?" 

## Model selection is too generous, accepts anything. ~~No routine model selection possible.~~

**Routine model selection — FIXED (2026-07-24).** Routines gained an optional
`model:` frontmatter field. `runner.effective_model` resolves routine pin ›
caller/session model › vetted default, everywhere (both the `do_routine` nudge
and `run_routine` use it). `:routine new` prompts for one, `:routine` shows a
model column, and it round-trips through the file (omitted when unset). Before,
every scheduled routine could only run on `ROUTINE_MODELS[0]`.

**The blind-error symptom — FIXED (2026-07-24) with auto-revert.** The real
damage wasn't that `:model shanhaig` set a bad id; it's that it *persisted* it, so
every turn 400ed and it survived reopening the session — you found out only via
`:models`. Switching to a model not in `known_models()` now arms a revert: the
first turn that errors on it backs out to the model you were on, with
`provider rejected 'X' — switched back to Y`. A working turn disarms it, so a
valid unlisted model is untouched. See `main.py:revert_bad_model` /
`tests/test_model_revert.py`.

**Should `:model` be stricter? — CALLED BY CAS, BUILT IN v0.8.2 (2026-07-26).**
Shipped as described below, with two notes worth keeping. The suggestion list
is a **separate function from `resolve_model`** and a looser one (0.6 against
0.7), because a suggestion is offered rather than acted on — and it needs two
strategies, since difflib alone scores `minimax3` below any usable cutoff
against `minimaxminimaxm3`. The `[esc]` half of the ask was **not** built: see
the note at the end of this entry.


Neither of the two options this entry offered. Rather than rejecting an
unrecognised id or silently setting it, **show the near misses and let the
unrecognised one through on a deliberate keypress**:

```
"minimax 3" is not a recognized model. Did you mean:
  [1] minimax-m3
  [2] minimax-m3:thinking
Press [enter] to use "minimax 3" anyway
```

That keeps the escape hatch a valid-but-unlisted model needs — which is why
strict rejection was never right — while making the typo case one keystroke
instead of a 400 and an auto-revert. The auto-revert stays as the backstop for
what gets through.

Two wording fixes ride with it, same testing pass:
- The existing confirm reads
  `did you mean deepseek/deepseek-v4-pro? [Enter] yes / [n] no:`. Drop the
  vendor prefix — nobody types it and it doubles the length of the line — and
  make the decline key `[esc]` rather than `[n]`, so the two prompts agree
  about how you back out.
- Lowercase `[enter]` consistently.

**`[esc]` is still open, and it is not a wording change.** The vendor prefix is
gone and `[enter]` is lowercased, but every prompt in cfc is built on plain
`input()`, which reads a *line* — it cannot see a bare Esc at all. Detecting one
needs a keypress reader, and Esc is the ambiguous key to pick for it: terminals
send it as the prefix of every arrow key, so a bare Esc is only distinguishable
by a timeout. So the decline key is still `[c]`/`[n]`.

Worth doing properly or not at all, because the value is **consistency across
every prompt**, not this one: the hub picker, `/file`, `/wiki`'s pickers and the
model prompts should all back out the same way. That makes it a v0.9-or-later
job with `read_input` in `ui.py`, and it has to respect the standing decision
that prompt_toolkit and rich never drive the terminal at once. Recorded here so
the ask isn't lost.

`'deepseek pro'` / `'shanhaig'` below are typos that also missed the fuzzy
cutoff; the numbered list is what they should have got.

Original report below.

**deepseek pro' isn't in your configured models — setting it anyway
Switched to model: deepseek pro
Current model: deepseek pro
 'shanhaig' isn't in your configured models — setting it anyway
Switched to model: shanhaig
Current model: shanhaig**

## Processed notes stay in "00 inbox/notes" forever. 0.8, 24-07-2026
**Found:** 2026-07-24, wiring the journal cadence. Cas had already hit it — it's
in `st memory.md` for the 22nd: "routine read a stale note from the 24th because
it was still in inbox/notes."
Description: nothing removes a note from `00 inbox/notes` after a routine has
processed it, so the folder grows without bound and every run re-reads material
it has already written up.
Mitigated, not fixed: the ST prompt now tells the model a note belongs to a date
by its own `created:` field and to ignore anything outside the dates it was
handed, so a stale note no longer produces a duplicate entry. That is a *prompt*
holding the line, which is the weaker half of every pair in this project — and
the cost is still real, since every run pays to read the whole folder.
Suggestion: a code-driven move, same shape as the mover. After a successful run,
notes whose `created:` date is covered by that run move to a processed folder.
Deliberately not the model's job (it has a right answer) and deliberately not
part of v0.7, which had enough moving parts.

**Cas's call (2026-07-26): manual trigger first, `/clear notes`.** Not the
automatic post-run move above, and the reason is the one thing that entry
missed — **`00 inbox/notes` is read by more than one routine**, so "covered by
that run" isn't ownership. The first routine to finish would move notes the
second one hasn't read yet, and the second would then be silently short of
input, which is exactly this project's worst failure shape. A human command
sidesteps the whole question: by the time you type it, the loop and the script
have already dealt with the outbox, so nothing is still owed the notes.
`notes` needs no qualifier — the inbox one is the only one that means anything.
Leaves open, and worth deciding when it's built: what `/clear` does with a note
no routine ever read, and whether "clear" moves or deletes (it should move —
`LOSER_DIR` set the precedent that a discarded thing keeps its body).

## Obsidian's template syntax and cfc's placeholders are both "{{ }}". 0.8-adjacent, 24-07-2026
**Found:** 2026-07-24, adding the cadence placeholders.
Description: `runner.PLACEHOLDERS` substitutes `{{date}}`, `{{dates}}`,
`{{week}}` in a routine prompt. Obsidian's own templates use the same braces —
this vault's `note template.md` has `{{date:YYYY-MM-DD}}` in it.
Not live: matching is exact, so `{{date:…}}` is untouched, and the prompts point
at the template by path rather than quoting it. But a bare `{{date}}` pasted
into a prompt from an Obsidian template *would* be substituted, and the model
would then write today's date into a new note where the placeholder belongs.
Suggestion: an escape (`\{{date}}`), or confine substitution to a marked region.
Don't build it on spec — the failure is visible the first time it happens and
the fix is one line. Recorded so it isn't a surprise.

**Cas's call (2026-07-26): change the vault, not the code.** The Obsidian
properties are there to be inspected, not templated, so converting them to plain
text is a small one-time edit of a handful of markdown files and it removes the
collision at the source. Cheaper than an escape syntax nobody would remember,
and it belongs to the vault repo rather than this one — `cfc ships the
mechanism, the vault ships the words`. **cfc's side of this is nothing**, which
is the point: leave `PLACEHOLDERS` exact-matching as it is. Keep the entry until
the vault edit has actually happened, because until then the trap is live.

## ":file" takes a number, not a title. 0.7 leftover, 24-07-2026
**Found:** Cas's 0.6.2 testing pass.
Description: `:outbox` now shows each proposal's frontmatter title beside its
filename, which fixes the "list of bare timestamps" half of the report. Typing
one is still `:file 3`.
Suggestion: accept `:file Aquarium Nitrogen Cycle` as well, matching the title
case-insensitively, refusing an ambiguous match rather than guessing. Pairs with
the `:move` entry below — both are "name the thing instead of counting rows" —
so decide the argument-parsing shape once, for both.

## The interactive tool path drops an empty-completion turn without offering a retry. 0.8-adjacent, 24-07-2026
**Found:** 2026-07-24, fixing the empty-completion 400 on the tool path.
Description: `agent_turn` now maps a thinking-model empty-completion 400 onto the
empty-completion path — it returns an empty message. Routines re-roll it
(`runner._turn_with_retry`); the **interactive** chat tool path (`main.py`, the
`use_tools` branch) just takes the empty return, prints the "provider hiccup"
note, renders an **empty answer panel**, and moves on.
Problem: the streaming path in the same situation *asks* `retry? (y/n)` (see the
empty-completion handler around `main.py:700`). The tool path offers no such
prompt and paints a blank panel. Not broken — a human can retype — but the two
paths handle the identical event differently, and the empty panel reads as a
render bug.
Suggestion: on an empty return from `agent_turn` in the interactive branch, skip
the empty panel and offer the same `retry? (y/n)` the stream path does (reuse the
handler, don't fork it). Low priority; symmetry, not a fault.

## ~~":diff decline <file>" — send a declined draft to a losers' folder.~~ — FIXED (v0.7, 2026-07-24)

**Fixed**, as `:file <n> decline [why]` rather than `:diff decline <title>`. The
verb changed on purpose: decline is an argument to the existing filing command,
so it inherits the numbering `:outbox` already put on screen and needs no new
command name — which matters because the v0.8 taxonomy has no slot for a
`/decline`, and the `:`→`/` flip has to stay a pure prefix change. Built once
and pointed at both corpora, as the entry asked: `LOSER_DIR/<corpus>`
(`wiki/`, `journal/`, `notes/`), split by corpus because the reason to keep a
declined draft is to debug the prompt that produced it, which is a per-routine
question.

Beyond the original ask: the **reason is recorded on the draft itself**
(`declined:` / `declined_reason:` in its frontmatter). A folder of near-identical
rejects with nothing saying what was wrong with each is close to useless a week
later — you end up re-deriving the fault instead of reading it. Frontmatter is
edited by hand rather than re-dumped through `yaml`, since a round trip
re-quotes unquoted digit ids and mangles wikilinks; the reason is quoted and
escaped, because free text with a colon would otherwise cost the file its whole
frontmatter block. Pinned in `test_mover.py`.

Also landed with it: `99 outbox/dropped/` retires (still the fallback when no
`LOSER_DIR` is configured), and the outbox's own readme became undroppable.

Original report below.

**Found:** in the note-reader workflow rewrite (00 inbox/400-error brief).
Description: the wiki-review loop lets you inspect a proposed page's diff, but
there's no way to *reject* one from there. A decline should move that draft to
`03 resources/loser corner` rather than leaving it in the proposal folder or
silently dropping it — declined ≠ deleted, and the losers' corner is managed
later in a chat session (model reads on approval, output to `99 outbox`).
Suggestion: `:diff decline <file title>` (the diff display should show the title
so there's something to type). Code-driven move, same shape as the mover — the
command names the target, code re-validates and carries it out. v0.7's tiered
memory wants the same behaviour for declined journal entries (see the v0.7
draft), so build the move once and point both at it.
Note: pairs with the top entry — per-file `:wiki commit` and per-file decline are
the two halves of "act on the draft you're looking at, not the whole set."

## ":move" — a file selector over the outbox. 0.8, 24-07-2026
**Found:** in the note-reader workflow brief.
Description: a command to move a file out of `99 outbox` (top level only, not the
subfolders) into the vault, driven like `:attach`: list filenames, arrow-select,
Enter to confirm, Esc to leave. The terminal states what will move and asks for a
destination (default `00 inbox`, arrow-select subfolders — today only
`00 inbox/notes` exists). A single Enter confirms — moving files, not replacing,
so no y/n. If a same-named file exists at the target, warn and offer: replace /
rename-the-new-one (timestamp appended?) / cancel; typing `replace` rather than
picking it is the protection against a careless clobber.
Where it fits: it's a filing command, closest to the existing `:outbox`/`:file`
pair rather than the taxonomy's attach/remove verbs — decide during v0.8 whether
it's a third filing command or an extension of that pair before naming it, so it
lands under the right prefix.

## Retire the ":"-command "startswith" chain for an exact-match table. 0.8-adjacent, 24-07-2026
**Found:** 2026-07-24, planning the v0.8 command flip.
Description: dispatch in `main.py` is a long `if user.startswith(":x")` chain, and
the branch order is load-bearing — `":attached".startswith(":attach")` is true,
which `main.py:368` carries a comment about. The v0.8 `:`→`/` flip is a *prefix
change* by decision, so it preserves the trap rather than fixing it.
Suggestion: after the flip settles, replace the chain with an exact-match command
table + argument split, which kills the ordering trap structurally. Deliberately
**not** bundled into the flip — that would break the "one re-baseline, pure
prefix change" property that makes the flip safe. Its own session. See the v0.8
build draft, block 5.


## ~~The run log sits inside the model's write scope~~ — FIXED (2026-07-23)

**Fixed:** `tools.reserved_write_reason()` refuses any write resolving inside
`ROUTINE_LOG_DIR`. Containment against the one directory, as this entry asked,
not a filename pattern. Enforced in `write_file` — **the boundary, because
`dispatch()` is reachable with no gate at all** — and mirrored in `precheck` so
the gate never prompts for a call that cannot succeed. Writes only; reading a
log is still allowed. Resolution happens before the check, so a symlink out of
the outbox into the log dir is judged as its target. Verified against the real
config (the live `heartbeat.md` is refused and unchanged), and the new
assertions were confirmed to fail with the guard disabled.

One thing this deliberately does *not* do: it makes no attempt to be a general
"reserved paths" mechanism. There is one such directory, so there is one check.
A second one is the point at which it should become a list.

Original report below.

**Found:** 2026-07-22, when a routine spent its last tool call reading its own
run log in order to update it.

`ROUTINE_LOG_DIR` is `<vault>/99 outbox/routine logs/`, and `WRITE_ROOTS` is
`<vault>/99 outbox`. Containment is checked, so the log directory is **inside
the writable universe** — verified, not assumed:

```
log dir   : …/99 outbox/routine logs
write root: …/99 outbox          -> log inside? True
```

So `write_file` will happily let a model overwrite the append-only log that
`runner.append_log` owns. That log is the audit trail *and* what the next run
reads via `last_run()` to honour `on_failure`, so a clobber destroys the record
of the failure it exists to preserve — and does it silently, since nothing
compares the file against what the runner wrote.

The trigger this time was a prompt asking the model to log its actions, which
is fixable by deleting the instruction (the runner logs every run
unconditionally, so the rule was redundant anyway). But the prompt is not the
boundary anywhere else in this system and shouldn't be here: a model can decide
to tidy its log without being asked.

Fix: refuse writes under `ROUTINE_LOG_DIR` in `tools.precheck`, the same shape
as `mover._reject_wiki` — which exists for the identical reason, a write whose
damage is silent and arrives later. Note the deny list is the *weaker* tool here
(name-based, open-ended) and this wants the containment form: a path check
against the one directory, not a filename pattern.

Related: **`mover.py` already special-cases this folder** — only top-level
`*.md` in the outbox count as proposals, so the logs are excluded from filing.
The precedent for "the log subfolder is not ordinary outbox content" exists;
the write path just never got it.

---

## ~~`append_log`'s `touched=()` is never passed~~ — FIXED (2026-07-23)

**Fixed:** the collector, as this entry preferred — `agent_turn` takes an
optional `touched` list and appends each successful write to it. A routine
passes one, chat passes nothing, and the signature stays honest about who
cares.

- **The collector is owned by `run_routine`, not by the turn.** Both of the
  turn's failure exits leave by raising (`CallLimitReached`, `EmptyCompletion`),
  so a value returned *from* the turn cannot carry the answer out of exactly
  the case the entry is about. The caller holds the list, so the `except`
  branch logs it. It also spans re-rolls: `history` is rebuilt per attempt,
  but files an earlier attempt wrote are on disk and stay there.
- **`tools.written_path()` reads `write_file`'s own result**, so the tool loop
  never has to understand tools and a *refused* write is never reported as one
  that happened. The producer and the parse live together, with the same hazard
  as `commands.py`'s markers and `db._MARKER_RE`: reword the success line and
  this returns None forever, which reads as "the run wrote nothing". Pinned by
  round-trip — a real write, parsed from its real result — so a reworded
  message fails a test instead of silently emptying a log field. Verified by
  rewording it: 4 assertions fail.
- **The rendering changed too, which the entry didn't foresee.** The first real
  line was unreadable: full paths repeat the 47-char write root per file, and
  the ` — ` field separator collides with the em-dashes *inside* this vault's
  filenames (`wiki draft — chunking.md`), so the list had no findable end. Now
  names rather than paths, and the list goes **last**, where everything after
  the colon is the list:

```
- **2026-07-23 07:09** — failed — TimeoutError: provider went away — wrote 2 files: wiki draft — sqlite-vec.md, wiki draft — chunking.md
- **2026-07-23 07:09** — ok — Nothing to do. (8s, session 392)
```

`last_run()` is unaffected — `_LOG_RE` is anchored at the head of the line.
A run that wrote nothing grows no `wrote` clause at all.

Original report below.

**Found:** 2026-07-22, reading the logging path after a routine hit the tool
ceiling mid-task.

`routines.append_log(routine_id, status, detail="", touched=())` renders the
fourth argument as `— wrote a.md, b.md` in the log line. **No caller passes
it.** All five `append_log` call sites in `runner.py` supply a status and a
detail and nothing else, so the slot is dead and every line reads as though the
run touched nothing.

It matters more than a cosmetic gap because of what the log is *for*. The two
consumers are a human asking "did the nightly thing work" and the next run
reading `last_run()`. When a run fails halfway — which is now a real, logged
outcome rather than a silent `ok` — the first question is **which files it got
to before it stopped**, and the log is the only place that could answer it
without reading the whole transcript back. Right now you diff the outbox by eye.

Fix: `agent_turn` already sees every dispatched call, so the write targets are
knowable at the point they succeed. Thread the successful `write_file` paths
back out of the tool loop and hand them to `append_log`. The seam is real but
not free — `agent_turn` currently returns just the final message, so it needs a
second return value or a small mutable collector passed in, and the chat path
must not start paying for something only the runner reads. Prefer the collector:
a routine passes one, chat passes nothing, and the signature stays honest about
who cares.

Not urgent. The transcript has the full truth today; this is about making the
one-line summary answer the question you actually ask it.

---

## ~~`golden.py check` writes a file into VAULT_PATH~~ — FIXED (2026-07-23)

**Fixed:** redirected, not disabled, as this entry asked — `VAULT_PATH` is now
patched on every cfc module that holds one (the same loop shape as `DB_PATH`,
and for the same reason: `export.py` and `commands.py` each hold a copy, so
patching one leaves the other pointing at the real folder). Exports land in
`tests/_fixture_vault` and are removed at the end of the run.

Three things came out of it that the entry didn't anticipate:

- **The baseline was pinning Cas's real vault path** on the `:config` line —
  the same class of bug as the API-key line that earned the `SCRUB` paragraph
  in `HANDOVER.md`. It now reads `<ROOT>/tests/_fixture_vault`, exactly like
  the `Prompts dir` line above it. That was the only line that changed;
  re-recorded.
- **`AUTO_EXPORT` is pinned on** rather than read from config. The script's
  `:q` only takes the export path when it's true, so leaving it to config
  meant the baseline covered a different amount of code on different machines.
- **The new guard caught the fix's own bug.** `assert_not_real_vault` first
  re-read `config.VAULT_PATH` at call time — after the loop had patched
  config's own copy — so it compared the fixture against itself. `REAL_VAULT`
  is now frozen at import, before anything is rewritten.

Verified: two consecutive `check` runs leave the real folder's mtimes
unchanged, and the guard was confirmed to fire when pointed at the real vault.
The harness also now asserts a document actually landed — the baseline pins
the `[auto-exported: …]` *message*, and `safe_export` swallows its own errors,
so those are not the same claim.

Left alone: the two stale `…_Renamed By Golden.md` files this bug already
wrote into the export folder. They are Cas's to delete.

Original report below.

**Found:** 2026-07-21, driving `:wiki` through the real dispatch for v0.3.

The harness ends its script with `:q`, and `:q` honours `AUTO_EXPORT` — so
every `golden.py check` exports the fixture session into the **real**
`VAULT_PATH`, leaving files like
`2026-01-01_Session-1_Renamed By Golden.md` in Cas's export folder. They
overwrite each other, so it's one or two files rather than a growing pile, and
nothing is corrupted: the fixture DB itself is correctly isolated.

But it is a test harness with a side effect outside its fixture, which is the
category invariant #1 exists for. The DB got the full assert-before-touch
treatment; the export path was never considered, because `:q` reads as a
navigation command rather than a write.

Fix: patch `AUTO_EXPORT` to False for the harness run, or redirect
`export.VAULT_PATH` to a temp dir the same way `DB_PATH` is redirected (the
loop that finds `DB_PATH` on every cfc module is the obvious place). Prefer
redirecting over disabling — the export path then stays exercised instead of
becoming untested.

Not urgent: it writes one predictable file to a backup folder. Noted because
"the tests don't touch anything real" is currently a slightly false claim, and
that claim is load-bearing for how freely the suite gets run.

---

## ~~A chunk with a dangling `session_id` — where does it come from?~~ — ROOT CAUSE FOUND, FIXED (2026-07-23)

**It was not `import_anthropic.py`, and it was not moot on the wiki db.** Both
guesses in the original report were wrong, and the second one is why this sat
here: the entry said the current corpus was unaffected, so nobody looked.

**Root cause: `db.delete_session` and `db.delete_message` never cascaded to
`chunks` or `vec_chunks`.** There are no foreign keys (`PRAGMA foreign_keys`
is 0 and the tables were never declared with any), so nothing enforced it.
Measured on the live db before the fix:

```
chunks 1011 · 152 whose message row is gone · 143 of those still had vectors
             ·  55 whose session_id disagrees with their message's
sessions 41 and 49 — deleted, their chunks still present
```

That is **three** bugs, and the reported one is the least of them:

1. **A deleted conversation stays in the retrieval index.** 143 vectors of
   deleted content were still searchable. A delete that leaves the text
   answering questions is not a delete. (Recall filters `provider='wiki'`, so
   they weren't reaching `:recall` today — but `search()` returns them, and
   the planned wiki+chat hybrid is precisely the thing that would surface
   them.)
2. **Orphaned rows** — the dangling `session_id` that was reported.
3. **Mis-attribution, the dangerous one.** SQLite reuses rowids at the top of
   a table, so a later message takes a deleted message's id and the stale
   chunk *joins cleanly* to it. Chunk 885's text is a routine log path; the
   message it now joins to reads `:wik commit all`. `search` reports such a
   chunk under that message's session, date and title — a citation pointing at
   a conversation the text never came from, silently.

**Fixed:** `delete_session`/`delete_message` now drop the index rows first,
while the messages that identify them still exist; `delete_session` also
sweeps chunks by `session_id` directly, for ones whose message was already
deleted separately. Vectors go before chunks and a failure there raises rather
than continuing — a chunk without its vector is stale, but a vector without
its chunk is text in the index that nothing can inspect or attribute.

**Repair for databases already damaged:** `db.find_stale_chunks()` /
`prune_stale_chunks()`, surfaced as `:updatedb prune`. Plain `:updatedb`
*reports* a stale count and removes nothing — this is the one maintenance path
that deletes, and a command run casually should not quietly drop rows. Both
detection rules are exact, not heuristic:

- the message row is gone; or
- `chunks.session_id != messages.session_id`, which **cannot happen in normal
  operation** — `chunk_new` copies the session id straight off the message row
  it is chunking, and `messages.session_id` is never reassigned anywhere in
  the codebase. A disagreement is proof of a reused rowid.

Verified on a **copy** of the live db: 207 stale chunks and 195 vectors
removed, idempotent on a second run, zero `source='wiki'` rows touched (every
stale row was `source='chat'`), messages and sessions untouched, no vector
left without a chunk. Six assertions confirmed to fail with the cascade
removed.

**Still open, deliberately:** real foreign keys with `ON DELETE CASCADE`.
SQLite cannot add one to an existing table without rebuilding it, and the
chunk/vector schema is already flagged as in flux — this belongs to the
DB-layer rework. The code cascade is the smaller, reversible half.

Also noted: `import_wiki.clear_chunks_for_message` does the same
vector-then-chunk dance for the same reason, and is still a second copy of it.
Left alone rather than merged mid-fix, but two implementations of a delete are
how one gets fixed and the other doesn't.

Original report below.

**Found:** 2026-07-15, while verifying the distance threshold.
**Retrieval side fixed:** 2026-07-17.

Chunks 4578, 4579 and 4580 have `session_id=364`, and no session 364 exists
(`sessions` holds 187 rows with ids 1–366, so there are gaps).

The retrieval-side symptom is fixed: `search.py` now `LEFT JOIN`s chunks to
sessions and surfaces an orphan with a `(missing session N)` placeholder title
and a null date, instead of the inner join silently dropping it (which is why a
`k=8` search sometimes returned 7 hits). Verified: 4579 and 4580 now come back
on a raw-KNN probe of their own content. They still fall outside
`MAX_DISTANCE = 0.93`, so a normal query won't reach them — but they're no
longer *invisible*, and a future import can't lose data this way unnoticed.

Still open, and the actual root cause: **why does a chunk point at a session
that was never written?** Suspect `import_anthropic.py` writes chunks with a
session id that isn't committed, or a session row was deleted without cascading.
Not investigated — belongs with the DB-layer rework.

---

## ~~`chunk.py` overlap cuts mid-word~~ — FIXED (v0.2, 2026-07-21)

**Fixed:** `slice_text` now seeks to a boundary at both edges — `_end_at`
(paragraph > line > sentence > space, never surrendering more than 40% of the
window) and `_open_at` (next whitespace only, so the overlap isn't eaten).
Measured against the old implementation on the same input: **22 of 26 chunks
opened on a fragment; now 0.** Corpus re-chunked and re-embedded (519 chunks,
512 vectors, 0 orphans), which is why `MAX_DISTANCE` was re-measured *after*
this landed rather than before. `tests/test_chunk.py` pins it.

Original report below.

**Found:** 2026-07-15, reading top-k output.

Chunk 1034 begins `'ne that decides when the AC stops being optional tonight.'`
— the 75-token overlap is slicing inside a word, so the chunk starts on a word
fragment. Presumably the overlap counts tokens/characters without seeking to a
boundary.

Cosmetic in most cases, but a chunk that opens on `'ne that...'` is
embedding a fragment, and it *did* score 1.034 on an unrelated query — right at
the top of a junk result set. Not proven to affect ranking; noted because it's
cheap to fix at the next chunker change.

Fixing means re-chunking and re-embedding the affected chunks (real money this
time, unlike the litter prune, which only deleted).

---

## `longcat-2.0` is in MODELS but can't chat — ~~CLOSED~~ re-opened

**Found:** 2026-07-15, while verifying which models do tool calling.
**Closed:** 2026-07-21, v0.4. Dropped from `MODELS`, `MODEL_LIMITS` and the
`TOOLS_MODELS` comment in both `config.py` and `config.example.py`. Cas's call:
the model isn't wanted, so there was nothing to fix — only a mention to remove.

The observation underneath it is still true and is *not* tracked as work:
**nothing validates that a model in `MODELS` can actually be chatted with.**
A wrong name fails at the first message with a provider 400, which is loud and
immediate, so it doesn't need a guard.

Edit by Cas: even with longcat gone, we still need to fix the underlying issue.

---

## ~~Local embedding endpoint IP is not stable across reboots~~ — FIXED

**Found:** 2026-07-19, wiring bge-m3 on LM Studio (Windows) for the wiki migration.
**Fixed:** 2026-07-20. `networkingMode=mirrored` in `.wslconfig` + `wsl --shutdown`.
`EMBED_BASE` is now `http://localhost:1233/v1`; the old gateway IP no longer
resolves at all, so a stale config fails closed rather than drifting. Verified
end-to-end (`embed_texts` returns 1024-d). LM Studio's "serve on local network"
toggle must still be ON, and the model id is still
`text-embedding-baai-bge-m3-568m`, not plain `bge-m3`. Kept for the record
below because the failure mode — embedding calls erroring like a dead server
when the address merely moved — is worth recognising if it ever recurs.

`embed.py` reaches LM Studio at `http://172.27.0.1:1233/v1` — the WSL2 NAT
gateway to the Windows host. That gateway IP is **not guaranteed stable**; it
can change on a WSL or Windows reboot, at which point embedding calls fail with
a connection error that looks like a dead server but is really a moved address.

Fix when it bites (or proactively): set `networkingMode=mirrored` in
`C:\Users\<user>\.wslconfig`, then `wsl --shutdown` once. After that
`localhost:1233` works from WSL and the IP stops mattering. The zero-setup
alternative is to re-run `ip route show default` and update the base URL when it
breaks. Also note LM Studio's "serve on local network" toggle must stay ON
(it's the 0.0.0.0 bind) and the model id is `text-embedding-baai-bge-m3-568m`,
not plain `bge-m3`.

---

## ~~Reasoning on the tool path is printed in full~~ — FIXED (v0.4, 2026-07-21)

**Found:** 2026-07-18, wiring reasoning into the tool path.

The streaming path tail-limits live reasoning to the last 12 lines
(`_REASONING_TAIL_LINES`) so the live region doesn't jump. The tool path
(`agent._render_reasoning`) prints each step's reasoning **in full**, because
it's a one-shot print into scrollback with no live region to keep still — and a
tool turn can print several such panels (one per loop iteration). On a verbose
thinking model that can bury the actual answer under walls of reasoning.

**Fixed:** middle-elided to `agent.REASONING_HEAD_LINES` + `REASONING_TAIL_LINES`
(6 + 10) with a "… N more lines …" marker. Head *and* tail rather than just the
tail: on this path the opening lines are usually "what am I about to do", which
is the part worth reading next to the tool call it explains. Larger than the
live panel's 12 because scrollback doesn't jump. Purely cosmetic either way —
reasoning is never persisted or replayed.


---

## ~~MAX_DISTANCE no longer separates~~ — RESOLVED (v0.2, 2026-07-21)

**The premise of this entry was wrong, and that turned out to be the finding.**

Nothing collapsed and nothing regressed. The old 1.024, and the "0.111-wide gap,
total separation" it was built on, were measured against the **Anthropic export**
and written into `HANDOVER.md` as if they were wiki numbers. Evidence:

- `"Who is Cas"` (capitalised, no question mark) measures **0.970 on the
  Anthropic corpus** — that is the recorded 0.969, to rounding.
- The same query has measured **1.036 on every wiki snapshot**, back to the first
  wiki-only db (`chat-20260719-151026.db`), with byte-identical chunk text
  throughout. The rolling backups made this checkable rather than arguable.
- So the wiki corpus never had a 0.111 gap to lose. Its gap has always been thin.

Ruled out first, each by measurement rather than reasoning: **the embedder**
(re-embedding a stored chunk reproduces its stored vector at L2 = 0.000000);
**the endpoint** (hosted vs self-hosted bge-m3 differ by 0.003 on the same query
— note that the "cosine ≥ 0.999 equivalence" in HANDOVER is a much weaker claim
than it sounds, since cosine is magnitude-blind and `vec0` ranks by **L2**);
**corpus drift** (none, per the snapshots).

**Lesson, and the reason this cost a session:** a tuned constant must record
*which corpus it was measured on*. Without that, a number outlives the thing it
described and the next person measures a "regression" that never happened.

**What replaced it:** the floor is no longer a relevance judge at all — the
answerable and unanswerable bands genuinely interleave (`"what was agentmail
about"` needs 1.065; `"How do I tune a guitar to drop D?"` scores 1.055), so no
threshold can separate them, and a relative metric doesn't either. It is now a
lint filter at **1.08**, set to admit generously because the two failures are
asymmetric: a rejected good hit is silent, an admitted bad one is caught by
recall's grounded synthesis. Full reasoning is in `search.py` and `HANDOVER.md`.
The old 1.024 was losing **4 of 20** real query phrasings.

Also fixed here: `search()`'s `k*4` over-fetch (noted at the foot of the original
report) now widens until it has k results, crosses the floor, or exhausts the
table — a low `k` with `provider='wiki'` could return zero rows purely because
the window filled with `source='chat'` chunks, and that got worse every day the
chat log grew.

Original report below, kept because the reasoning it prompted is worth the room.

---

**Found:** 2026-07-20, smoke-testing recall after the vault restructure.

`:recall` / `:remember` return nothing for some good queries. Re-measured over
30 probes on the unchanged wiki corpus (20 answerable, 10 unanswerable):

    answerable    0.734 – 1.036   (20/20 returned the CORRECT page at rank 1)
    unanswerable  1.061 – 1.203
    gap 0.025, vs the 0.111 recorded in HANDOVER

The floor (1.024) now sits *below* the top of the answerable band, so
`"who is Cas"` (1.036) is rejected outright while
`"orchestrator specialist architecture"` (1.023) passes by 0.001.

**Unresolved:** HANDOVER records `"who is Cas"` at **0.969**. It now measures
1.036 on the same query, same corpus, same embedder. Verified, not assumed:
re-embedding a stored chunk and comparing to its stored vector gives cosine
1.000000 (embedder identical); all 20 pages are byte-identical to their files
(corpus identical); the vectors are valid and ranking is correct. Distance is a
pure function of query vector and chunk vector, both verified unchanged — so the
number should reproduce and does not. No explanation fits the evidence yet.
Ruled out: the vault restructure, which touches none of this.

**Do not just nudge the floor.** ~1.048 would admit both borderline queries, but
a 0.025 gap is too thin to tune against with confidence, and the discrepancy
above suggests the recorded baseline itself may not be trustworthy. Resolve the
0.969-vs-1.036 question first — a floor built on a number that doesn't reproduce
is a floor that will fail again silently.

Note also: `search()` over-fetches `k*4` before applying the provider filter, so
a low `k` with `provider='wiki'` can return zero rows purely because the fetch
window filled with `source='chat'` chunks. Hit this at k=1 while probing. Not
the cause of the above, but a sharp edge worth widening the window for.

---

## ~~Routine runs clutter the session hub~~ — FIXED (v0.4, 2026-07-21)

**Found:** 2026-07-20, session 2 of the routines work.

Every routine run creates its own session, so the transcript is inspectable
afterwards like any other — that's deliberate and worth keeping. The side
effect is that `:list` and the hub picker fill up with
`routine: Heartbeat — 2026-07-20 19:18` rows, and a routine on a nightly
trigger will produce one per day forever.

Nothing is broken; it's noise. Options, roughly in order of appeal: filter the
hub to hide sessions whose title/provider marks them as routine runs (needs a
marker — probably a `provider='routine'` or a `kind` on the session, not a
title prefix, which is not data); or prune routine sessions older than N days
on startup like the backup rotation does; or give routines a single long-lived
session per routine rather than one per run — cheapest, but then a run's
transcript is buried in a growing log and the token cost of replay grows.

**Fixed:** the first option. Routine sessions carry `provider='routine'`
(`db.PROVIDER_ROUTINE`), set at insert by `runner.py`, with a one-shot migration
backfilling the runs that predate it — matched on the exact generated title
shape, so a chat called "routine: ideas" survives. The picker filters them out;
`:list` still shows them, so no transcript becomes unreachable. The hub grew a
routine panel of its own, one row per routine, with freshness from the run log.

Saying it on purpose, as this entry asked: `chunk.py`'s rule is `'wiki' if
provider == 'wiki' else 'chat'`, so **routine transcripts keep indexing as
`source='chat'`**, unchanged. `tests/test_schema.py` pins that coupling.

---

## ~~`write_file` refuses relative paths, and only the prompt prevents it~~ — CLOSED (2026-07-23)

**Closed the way this entry asked to close it: a better error, not a
reinterpretation.** The refusal is unchanged — resolving a relative path
against the write root would make the tool's behaviour depend on how many
roots are configured, and "the path you passed is not the path that was
written" remains the worst property the one mutating tool could have.

What changed is the explanation. The old message named a path the caller never
typed:

```
/home/disse/projects/cfc/heartbeat.md is outside the allowed roots (…/99 outbox)
```

which reads as the jail being misconfigured rather than the path being
relative. Now:

```
… is outside the allowed roots (…/99 outbox) — 'heartbeat.md' is a relative
path, resolved against the working directory /home/disse/projects/cfc. Pass an
absolute path.
```

**The note is added only when the input was relative**, so an absolute path
that misses the roots is not told it is relative. `runner.SYSTEM` keeps saying
"always pass absolute paths" — the prompt avoids the error, the message
recovers from it, and neither is the boundary.

**What a blanket refusal of relative paths would have broken, checked rather
than assumed:** the process cwd (`~/projects/cfc`) *is* inside a read root, so
relative **reads** currently resolve and succeed. Refusing them outright would
have removed working behaviour to fix a message. It is not inside a write root,
which is why every relative *write* fails and this only ever bit `write_file`.

Original report below.

**Found:** 2026-07-20, first end-to-end routine run.

A relative path handed to `write_file` is resolved against the **process
working directory**, which is not one of the roots and is not predictable on a
scheduled run. The model tried `heartbeat.md` on the first two runs, got
`outside the allowed roots`, and recovered — correctly, because the guard
returns the real reason rather than "denied". But it cost a full API round trip
each time.

Currently fixed at the **prompt** level: `runner.SYSTEM` names the roots and
says "always pass absolute paths". That worked (one-shot writes since), but a
prompt is a suggestion and this is the one tool where a near-miss writes a file
somewhere unintended — or rather, would, if containment weren't holding.

The alternative is resolving a relative path against the write root inside
`write_file` when there is exactly one. Not done, deliberately: it makes the
tool's behaviour depend on how many roots are configured, and "the path you
passed is not the path that was written" is a bad property for the one tool
that mutates the filesystem. Explicit refusal is defensible. Revisit only if a
model turns up that doesn't take the hint — and if so, prefer failing with a
better error over silently reinterpreting the path.
