# cfc — cooking for cats

A terminal AI chat client in Python. It talks to any OpenAI-compatible API (built
against [nano-gpt](https://nano-gpt.com)), keeps every conversation in a local
SQLite file, answers questions from a semantic index over an Obsidian wiki, and
runs unattended tasks against a narrow, declared slice of your filesystem.

This file is how you use cooking for cats. The rest of the shelf:
[`ROADMAP.md`](ROADMAP.md) is what each version added and what's next,
[`CHANGELOG.md`](CHANGELOG.md) is the current change history and links to its
frozen earlier entries, and
[`HANDOVER.md`](HANDOVER.md) is why the code is shaped the way it is —
invariants, rejected designs, and the non-obvious choices.
[`templates/`](templates/) is how cfc is actually built: six model sessions, one
per step of a loop, with the personal half taken out so you can copy them.


## What it does

- **Chat, with some upgrades to the terminal** — pixel-art splash, live Markdown,
  colour-coded speaker panels, a live view of thinking models' reasoning, and a
  context-usage bar that colours as the window fills
- **Everything local** — one SQLite file, fully queryable, rolling backups
- **Private chat** — `p` at the hub. Same client, in-memory, leaves nothing on
  disk: no transcript, no index, no title, invisible to the hub
- **Simple commands** — `/verb [kind] [target] [message]`, twenty-four verbs.
  `/add` attaches anything, `/remove` takes it off, `/status` says what's on,
  `/list` says what exists
- **System prompts, personas and traits** — Markdown files you edit in Obsidian.
  The first two are singular; traits stack, so a voice is composed of pieces
- **Semantic memory** — a distilled knowledge wiki, embedded locally. Ask it a
  question and get an answer cited by page, or pull raw excerpts into the live
  context. Chats are embedded as they happen too, into the same index — but
  recall reads the wiki only, until searching both lands
- **File tools behind a gate** — the model can request `list_dir` / `read_file` /
  `grep`, and can `write_file` into exactly one narrow root that cannot reach
  your code
- **Routines** — a task the model runs on command or on a schedule, against its
  own declared roots, with an append-only run log
- **Propose, review, approve** — everything the model writes lands in one outbox
  with a suggested destination. `/list outbox` shows what would happen to every
  Markdown filing proposal (top level, plus its `wiki/` and `journal/`
  subfolders), `/file` carries one out (by number or by its exact title),
  `/file <n> decline <why>` rejects it and records why. `/move` is the manual
  path: it guides *any* top-level outbox file — any type, with or without a
  suggested destination — to a place you pick by hand
- **A tiered journal the model maintains** — a diary in three tiers, each more
  compressed than the last, rolled over by routines and approved by you
- **Vault git from the REPL** — `/wiki diff`, `/wiki commit`, scoped to a corpus
  or a single file

## Requirements

- Python 3.10+
- `httpx`, `rich`, `prompt_toolkit`, [`sqlite-vec`](https://github.com/asg017/sqlite-vec),
  `PyYAML` — see `requirements.txt`
- An API key for an OpenAI-compatible chat provider
- An embedding endpoint for the memory layer — the provider's hosted `bge-m3`, or
  a self-hosted one (this setup runs it on LM Studio)

## Setup

```bash
git clone git@github.com:Wantotg/cfc.git
cd cfc
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.py config.py
```

Then edit `config.py`. The ones you must set:

| | |
|---|---|
| `API_KEY` / `API_BASE` | your provider |
| `MODELS` / `MODEL_LIMITS` | the models your plan supports, and their context sizes |
| `CHAT_EXPORT_DIR` | where exported chats are written — not the vault itself, see `VAULT_ROOT` below. Renamed from `VAULT_PATH` in v1.3.1; a config.py still using the old name keeps exporting untouched |
| `PROMPTS_DIR` / `PERSONAS_DIR` / `TRAITS_DIR` | your prompt, persona and trait folders |
| `EMBED_BASE` / `EMBED_MODEL` / `EMBED_KEY` | the embedding endpoint; falls back to the chat provider's hosted `bge-m3` |

Worth knowing about:

| | |
|---|---|
| `VAULT_ROOT` | your vault's top folder. Display only — cfc never builds a path from it, it just trims the machine's prefix off paths it prints. Leave empty for full paths |
| `FIRST_MESSAGES_DIR` | optional per-persona opening lines — see First Message, below |
| `GOVERNOR_TRAIT_INTERVAL` | how often (in your own chat turns) an active trait gets a recency reminder (default 6; `0` disables it) |
| `AUTO_EMBED` | index new chat messages after each turn (default on) |
| `SPLASH_ART` | a name from `assets/`, a list to pick from, or `"*"` for all (default `"*"`) |
| `CONTEXT_GREEN_MAX` / `CONTEXT_ORANGE_MAX` | when the context bar turns orange and red, as a percent of the model's claimed limit (default 15 / 35) |
| `MOUSE_INPUT` | click to position the cursor (default off — see Input, below) |
| `TOOLS_ENABLED` | tools are **off** by default. Read Security first |
| `LMS_CLI` | only if `launch.sh` can't find the LM Studio CLI itself |

`config.py` is gitignored and never committed. It is also on the deny list in
`paths.py`, so `/add` and the file tools refuse to read it even though it sits
inside the project.

## Running it

```bash
python main.py          # straight in
python main.py 5        # open session 5, skipping the hub
./launch.sh             # venv + an embedder check first
```

`python main.py` works and always will. `./launch.sh` is the same thing with a
**preflight check** in front: it confirms the embedder actually answers before
opening the app.

That check exists because of an asymmetry. Everything memory-shaped — `/recall`,
`/remember`, `/update db`, auto-embed — assumes LM Studio is up with bge-m3
loaded, and none of them say so when it isn't. Recall just returns nothing, which
looks exactly like "memory has nothing on that". The preflight turns a silent
degradation into one line at launch:

```
  embedder: http://localhost:1233/v1
  ✓ embedder ready — text-embedding-baai-bge-m3-568m (1024-d)
```

If the server is off it starts it; if the model isn't loaded it loads it; if it
can't fix things it says why and **starts cfc anyway**. Chat is fine without an
embedder.

It also checks whether your terminal can render the splash as it was drawn, and
says so when it can't:

```
  … this terminal is not truecolor — the splash will band
    COLORTERM=(unset) TERM=xterm-256color rich=256. Launch from Windows
    Terminal for the real thing; see README.
```

That is the whole of a real, previously silent problem: the splash background is
resampled in a way that looks right on truecolor and visibly bands at 256
colours, with no error anywhere. See [A Windows shortcut](#a-windows-shortcut).

### The connection, from inside the app

The hub shows a light for the same check, asked fresh every time you land there:

```
● embedder connected
● LM Studio is up, embedder is not — /connect embedding in a chat
● LM Studio is not running — start it, or /connect embedding in a chat
● embedder not answering — /connect embedding in a chat
● hosted embedder unreachable — not cfc's to start
```

`h` at the hub prints what can be typed there, the light's legend, and where the
in-chat commands live. It is generated from the same tables that dispatch the
keys and colour the light, so it cannot describe a hub cfc doesn't have.

**The colour says what cfc can do about it, not how bad it is.** Green is
working. Orange means `/connect embedding` will try. Red means it isn't cfc's to
fix — a hosted embedder is someone else's server. Severity would be the useless
axis here, because every light that isn't green means the same thing: memory is
off.

**The advice names where you can type it**, which is why the line says *in a
chat*. The light appears at the hub, and the hub takes a chat id and `n`/`p`/
`h`/`q` — commands live inside a conversation. So the light tells you the two
steps, rather than a command the screen you are looking at would refuse.

`/connect embedding` walks as much of the loop as it can from wherever it
starts: starts LM Studio if it has to, starts the server, loads the model,
verifies. If you started LM Studio by hand in the meantime it just lands on
green. Bare `/connect` reports without changing anything.

The light and the launch check are the **same function**, not two opinions about
the same thing. That matters more than it sounds: the failure worth designing
against is a green light over a dead server, because a green light is exactly
what stops you checking.

An alias, if you want one:

```bash
alias cfc='~/projects/cfc/launch.sh'
```

### A Windows shortcut

1. Right-click the desktop → **New → Shortcut**.
2. Paste this as the location, adjusting the distro name:

   ```
   wsl.exe -d Ubuntu --cd ~ -- bash -lc "~/projects/cfc/launch.sh"
   ```

3. Name it `cfc`. Optionally change its icon and pin it to the taskbar.

`bash -lc` gives a login shell, so your normal environment loads. `--cd ~` keeps
the working directory off `/mnt/c`, which is slow to stat from WSL; `launch.sh`
finds the repo from its own location, so the starting directory doesn't otherwise
matter.

For **Windows Terminal** instead of the plain console — better fonts, better
colours, box-drawing characters that render:

```
wt.exe -p "Command Prompt" -- C:\Windows\System32\wsl.exe -d Ubuntu --cd ~/projects/cfc -- ./launch.sh
```

Two things about this command that aren't obvious and will bite you if you
"simplify" them back to the intuitive version:

- **`-p "Command Prompt"`, not `-p Ubuntu`.** The `Ubuntu` profile is
  WSL-backed and does its own internal distro activation; pairing it with an
  explicit `wsl.exe -d Ubuntu` in the same commandline makes the two lookups
  collide and fail with `WSL_E_DISTRO_NOT_FOUND`. Any non-WSL profile works
  here — it only supplies terminal chrome, not what actually runs.
- **The `--` is load-bearing.** `wt.exe` parses its own arguments first and
  will strip quoting meant for the command after it if `--` isn't there to
  stop that parsing.

If a window closes instantly, that's the console exiting with the process —
`launch.sh` holds it open on a non-zero exit, so anything that vanishes silently
exited cleanly.

`launch.sh` sets `COLORTERM=truecolor` itself when `WT_SESSION` shows it's
really running under Windows Terminal — the shortcut execs the script
directly, so `.bashrc` never runs and would otherwise leave color detection
falling back to 256-colour, which bands the splash.

## The hub

Past the splash is the hub: your 10 most recent **chats** — id, latest message,
message count, context usage, title, prompt and persona — and below them your
routines, with a traffic light on whether each is **owed a run**: orange means
due and waiting for the next scheduled tick, green means nothing is owed, and
dim means it cannot be owed one — never run, disabled, or `trigger: command`,
which only runs when you type `/routine`. The colour is the scheduler's own
answer, so if the tick stops firing every scheduled routine goes orange and
stays there. Routine transcripts and wiki pages are
kept off this list; `/list sessions` inside a session shows every session there is.

| Key | Action |
|-----|--------|
| chat id | Open that chat — any ordinary chat id, whether or not it is printed |
| `n` | New session |
| `p` | New **private** chat |
| `r` | Rename an ordinary chat by id |
| `q` | Quit |

The number you type is the session id, the same one `/delete chat 7` and
`/export chat 7` take. There is no second numbering anywhere: an id that isn't
on the list can still open any session — a chat, a wiki page, or a routine
transcript. Opening a wiki page or a routine transcript prints a settled
notice: you're continuing a conversation grounded in that page or run, never
editing the vault or rerunning the routine. Typed replies persist like an
ordinary chat, but neither auto-titles, and `/swipe`/`/undo` refuse on both.

The hub is home base. `/q` inside a session comes back here rather than quitting,
so the program only exits from the hub. The splash does not reappear on the way
back — it's a launch screen, not a menu.

A **private chat** behaves like a normal one — same model, prompts, personas,
read tools — but nothing is written down. It runs against an in-memory database,
so closing it ends it for good: no transcript, no index, no auto-export, no
title, never in the hub, no restore. Two deliberate exceptions: the model's own
file-writes are blocked entirely, while an explicit `/export` *you* type is
honoured — the rule is that nothing reaches disk unless you ask for it by name.
The wiki database starts sealed (`/recall` and `/remember` disabled); `/database
on` opens it, or set `DATABASE_ACTIVE = True` to have it on by default.

## Commands

```
/verb [kind] [target] [message]
```

*kind* is which pool or corpus, optional wherever it can be worked out; *target*
is a name, a number or a path; *message* is free text, always last and always the
rest of the line. Two rules hold everywhere: **a bare integer is a chat id**
(`/delete chat 5`), and **`#n` is an attachment** (`/remove #1`).

Three commands answer the three questions you actually have:

| Command | Answers |
|---|---|
| `/help` | What can I type? |
| `/list <kind>` | What exists? |
| `/status` | What's active right now? |

Everything else changes something.

**ask**

| Command | Action |
|---------|--------|
| `/help` | Every command, grouped (aliases `/h`, `/?`) |
| `/list` | The kinds you can list |
| `/list <kind>` | `prompts` · `personas` · `traits` · `models` · `routines` · `tags` · `chats` · `sessions` · `outbox` |
| `/status` | Everything active here: prompt, persona, traits, attachments, tags, tools, database, context, calls sent |
| `/status <kind>` | Print the attached prompt's, persona's or traits' actual text |
| `/status request` | The literal payload cfc sent the provider on the last turn, call by call; empty if the turn was refused before any call |
| `/config` | Deployment settings (key masked) |
| `/search <word>` | Substring search across all messages |

`/list chats` is the picker's view — real conversations. `/list sessions` is
everything, routine runs and wiki pages included, each row's Kind noting
which — and any of them can be opened the same way as a chat. Two different
questions.

`/outbox` is a real alias for `/list outbox`, not just the noun the table
above uses — it's been resolved since v0.8.

**context — attach and detach**

| Command | Action |
|---------|--------|
| `/add <name>` | Attach a system prompt, persona or trait by name |
| `/add <kind> <name>` | Same, naming the pool: `/add trait relax` |
| `/add <path>` | Attach an external file (persistent, comes back on reopen) |
| `/add tag <name>` | Tag this session (`/add tag 3 python` tags session 3) |
| `/remove <name>` | Take off whichever layer carries that name |
| `/remove <kind>` | Take off whatever that pool is carrying: `/remove persona` |
| `/remove #<n>` | Detach attachment `n` |
| `/remove tag <name>` | Untag |
| `/remove excerpts` | Drop the most recently injected recall block |

Names are forgiving: case-insensitive, and a unique partial resolves — `/add
relax` finds `Relaxed`. If several things match you get a numbered pick; nothing
is guessed. The confirmation always reports what it chose (`added Relaxed —
Trait`), because on a partial match that report is how you learn what happened.

A bare name is looked for in the three pools in priority order — **system prompt,
then persona, then trait** — and fills the highest-priority one not already
carrying it. A path-shaped argument is an external file; the pools are searched
first, so a trait genuinely called `notes.md` still wins over a file.

**Traits** are one `.md` file each in `TRAITS_DIR`, exactly like prompts and
personas — the filename is the name, no id, no combined file. Unlike those two
they **stack**: prompts and personas are singular and get overwritten, traits
append in the order you attach them. The session stores the *names*, not the
text, so editing a trait file changes what every session carrying it sends, with
no re-attaching. An active trait also gets a **recency reminder** every few
turns (`GOVERNOR_TRAIT_INTERVAL`, default 6) — traits reach the model on every
request already, but a short description has to keep steering an entire, and
growing, conversation, so it's nudged back into attention periodically rather
than only said once at attach time.

**First Message.** Drop a `.md` file into `FIRST_MESSAGES_DIR` named after a
persona (`muse.md` for the persona `muse.md`) and that persona opens a brand
new, empty session with that text instead of a blank box — attaching the
persona is the only action, there's no separate command. The words are frozen
onto the session the moment it happens, so editing the file only ever changes
what a *future* new session opens with; a conversation that's already started
keeps what it actually said. Optional per persona — nothing breaks if the file
isn't there.

**`((double parentheses))`** on a line by themselves are a direction to cfc,
not a message — `((answer in one word))` gets that turn's answer shaped
without adding a bubble to the conversation. It has to be the *whole* line;
`((relax)) please` or a sentence that merely contains a `((...))` anywhere in
it is ordinary text. `/continue` (above) is the same mechanism, spent as its
own verb.

Whenever cfc adds one of these — an OOC direction, `/continue`, the tone
nudge every ordinary turn gets, or a trait's periodic reminder — it prints one
dim line right before the answer naming what it added, e.g.
`cfc -> tone check · trait: relax`. None of it is saved: not in this
session's history, not in an export, not in what gets indexed for `/recall`.

**destroy**

| Command | Action |
|---------|--------|
| `/delete chat` | Delete this conversation, after a confirmation |
| `/delete chat 5` | Delete conversation 5 |

`/delete` always needs a kind; bare `/delete` lists what is deletable and acts on
nothing. The line between it and `/remove` is **whether retyping the command gets
it back**. `/remove` never destroys anything.

**data · memory · session**

| Command | Action |
|---------|--------|
| `/export` | Export this session to Obsidian |
| `/export chat 5` | Export session 5 |
| `/recall <question>` | Ask the wiki; answer cited by page, no session effect |
| `/remember <query>` | Pull matching excerpts into the live context (ephemeral) |
| `/update db` | Re-import the wiki, then index anything not yet embedded |
| `/update db prune` | Also remove index rows left behind by an old delete |
| `/new` | Start a new session in place |
| `/new p` | Start a private chat from here |
| `/q` | Back to the hub (auto-exports if enabled) |
| `/title <n> <name>` | Rename session `n` |
| `/continue` | Ask the model to continue its last answer — no arguments, no new message of yours in the transcript |

**settings**

| Command | Action |
|---------|--------|
| `/model <name or number>` | Switch the session's model (loose names resolve; number is `/list models`'s row) |
| `/tools` | Whether tools are active, and which switch is blocking |
| `/tools on` / `/tools off` | Toggle tools for this session |
| `/database on` / `/database off` | Enable or disable `/recall` and `/remember` here (alias `/db`) |
| `/connect` | Where the embedder stands, and what can be connected |
| `/connect embedding` | Start LM Studio and its server if they aren't up, and verify (`embed`/`embedder`/`embeddings` all work too) |

**wiki, routines, filing**

| Command | Action |
|---------|--------|
| `/wiki` | Vault repo status — wiki changes listed, the rest counted |
| `/wiki diff [kind] [file]` | Show the diff. Kind: `wiki` (default), `journal`, `vault`. Add `file` to pick one |
| `/wiki commit [kind] [file] <msg>` | Stage and commit what's in scope; `vault` asks first |
| `/routine <name>` | Run a routine now |
| `/routine new` | Create a routine (name, prompt, roots, trigger) |
| `/file <n>` | File one proposal at its destination (`/list outbox` to review) |
| `/file <title>` | File the proposal with that exact title (case-insensitive, no quotes needed) |
| `/file all` | File every valid proposal |
| `/file <n> decline [why]` | Reject a proposal — moved aside with the reason recorded on it (`drop` is the terse form) |
| `/move` | Guide one top-level outbox file (any type) to a destination you pick |
| `/clear notes` | Archive everything in the notes inbox (`00 inbox/notes`) into a dated batch folder |

**Two deliberate exceptions to the grammar.** `/file 1 decline <why>` keeps
target-then-action so it inherits the numbering already on screen; and `/wiki`
carries an extra `folder|file` slot, being the one command whose object has a
sub-granularity. `/file` also takes a bare title instead of a number — the
whole remainder of the line, matched exactly after folding case — but never a
title *and* `decline`, since the reason is free text and would make it
ambiguous where the title ends.

**Coming from the `:` commands?** The old prefix is gone as of v0.9 — a `:` line
is ordinary text and goes to the model, as it did before v0.8. The old *words*
did not go with it: `/prompts`, `/models`, `/tags`, `/tokens`, `/attach`,
`/grep`, `/forget` and the rest are real aliases now rather than corrections, so
they run the command instead of telling you its new name. `/detach` is the one
exception, because its replacement `/remove #<n>` takes a different kind of
argument.

### Input

Type or paste. **Enter** sends, **Alt+Enter** inserts a newline. A pasted block
keeps its line breaks and doesn't submit early. **Ctrl+C** at the prompt clears
the current line (it does not leave the session — use `/q` or Ctrl-D); Ctrl+C
during streaming cancels the request.

**Tab completion** works on `/add`, `/remove`, `/routine` and `/list`. On `/add`
and `/remove` it offers pool names first, in the same priority order the command
resolves them, and switches to the filesystem the moment the fragment looks like
a path — a slash, a tilde, a dot. It's the same rule dispatch uses, so completion
and the command can't disagree about one line.

Path completion is scoped to `ATTACH_ROOTS` and needs three characters before it
offers anything, rather than dumping a directory. Pool and routine names have no
such floor — there are a handful of each, and listing them on a bare Tab is
exactly what you want when the thing you can't remember *is* the name. A fragment
**with a slash** navigates; a fragment **without one** searches by name across the
roots, breadth-first, vault before repo.

**`MOUSE_INPUT`** (default off) lets you click to position the cursor. The trade
is real: while the prompt is live it captures the mouse for the whole window, so
click-drag selection of the conversation above needs Shift held. Worth it if you
edit long multi-line prompts more than you copy text out of the scrollback.

## Memory

Recall runs over a **knowledge wiki** — Obsidian Markdown pages, each with a
stable id in its frontmatter — distilled from past work, not raw chat logs. Pages
are imported, chunked, embedded with `bge-m3` and stored in `sqlite-vec`.

```bash
python import_wiki.py <wiki_dir> ~/.cfc/chat.db   # idempotent by frontmatter id
python chunk.py ~/.cfc/chat.db
python backfill.py ~/.cfc/chat.db
```

In-app, `/update db` does all three. Editing a page and re-importing re-chunks and
re-embeds it under the same id, so a page's identity survives renames and
rewrites. New chats index automatically after each turn (`AUTO_EMBED`); they're
tagged `source='chat'` and accumulate for a future wiki+chat hybrid, while recall
stays wiki-only.

`/recall` synthesises an answer cited by page title and id and leaves the session
untouched. `/remember` injects the raw excerpts into the live context and is
ephemeral — only a marker row persists, so an export can still tell a grounded
claim from an invented one. `/remove excerpts` drops the last injection.

Retrieval has a floor (`MAX_DISTANCE`, currently `1.08`) below which memory says
it has no answer rather than returning eight mediocre excerpts. It is
deliberately **loose**: measured over 32 probes, the questions this wiki can
answer and the ones it can't overlap so thoroughly that no threshold separates
them — a question about guitar tuning scores better against the corpus than a
real question about its own contents. So the floor rejects obvious lint only, and
the model reading the excerpts decides whether they answer anything, which it is
told to say. Tightening it doesn't buy precision, it loses good questions
silently. The number is specific to `bge-m3`, this corpus, *and* how the corpus is
chunked — re-measure if any of the three change.

**When memory comes back empty, it says which kind of empty.** Three things used
to print the same line, and only one of them meant "your wiki doesn't cover
this":

```
[memory not searched] the embedder isn't answering, so nothing was looked up.
This is not 'nothing found' — the search never ran. Try /connect embedding.

[memory is empty] nothing is indexed to search.
Run /update db to import and index the wiki.

Nothing in memory comes close to 'the Treaty of Asuncion'.
The wiki is indexed and was searched — this is a real miss, not a broken lookup.
```

The distinction is made at the point the failure happens rather than guessed
afterwards from the wording, because a down embedder returning "nothing found"
is a confident answer to a question that was never asked — and you have no way
to tell it apart from the truth.

Deleting a session deletes what indexes it. `chunks` and `vec_chunks` are an
index over `messages` with no foreign key, so that cascade is code rather than a
database constraint — and until 2026-07-23 it wasn't there at all: a deleted
conversation stayed searchable, and because SQLite reuses row ids a stale chunk
could later attach itself to an unrelated message and be cited under it.
`/update db` reports any such rows left in an older database; `/update db prune`
removes them.

The embedder is self-hosted here (`bge-m3` on LM Studio) but any
OpenAI-compatible `/embeddings` endpoint works.

## Routines and the scheduler

A routine is a task the model runs against its own declared read and write roots,
either on command or on a schedule. `/routine new` creates one; the file lives in
the vault and is fully editable in Obsidian.

**Every answer is checked as you type it**, so a bad trigger or a name already
taken costs you that one line rather than the whole form. Ctrl-C at any prompt
abandons the routine — and says so, because the next line you type after that is
a chat message, not an answer.

**Ctrl-C also cancels a routine that's actually running** (`/routine <name>` or
`run <routine>` from the routines screen say so as they start). It's logged
`cancelled` rather than `failed` — whatever the transcript and any files it had
written by that point are kept, but the run doesn't count against a scheduled
routine's cadence and doesn't trigger `on_failure`, so a manual cancel today
doesn't make tomorrow's tick think today's job already happened.

A routine's `trigger:` is one of three things:

| `trigger:` | When it runs |
|---|---|
| `command` | Only when you type `/routine <name>`. The default |
| `0300` | Daily, on the first tick at or after 03:00. A missed day is not replayed the next day |
| `weekly 0330` | When a Monday–Sunday week has *finished* and this routine hasn't processed it yet — **not** "on Mondays". Miss Monday and it runs Tuesday, on the same week |

**Quote a hand-written time with a leading zero:** `trigger: "0300"`. Unquoted,
YAML reads it as octal and `0300` becomes `192`. cfc re-reads the raw field to
undo this and validation catches the rest, but the quotes make it a non-question.

Something on the OS side has to call cfc on a tick; cfc works out the rest:

```bash
python main.py --due                  # what's due right now, run nothing
python main.py --run-due              # run everything that's due
python main.py --run-routine <name>   # run one now, due or not
```

**One scheduler entry covers every routine, forever.** `--run-due` reads each
routine's own `trigger:` and its run log, so adding a routine never means
touching the OS scheduler.

On Windows use **Task Scheduler**, not cron inside WSL — Windows shuts idle WSL
instances down and cron dies with them, so a 03:00 job would only run if you
happened to leave a terminal open. In an **admin** PowerShell:

```powershell
schtasks /Create /TN "cfc routines" /SC MINUTE /MO 15 /RU $env:USERNAME /RP * `
  /TR "wsl.exe -d Ubuntu -- /home/<you>/projects/cfc/run-due.sh"
```

The **`/RP *`** is the part that matters: it makes the task run whether or not
you're logged on, which prompts once for your Windows password and, crucially,
runs it in the background **with no console window**. (Same as the *"Run whether
user is logged on or not"* radio button on the General tab, if you prefer the
GUI.) This is the recommended default:

- **A window popping up every 15 minutes is intolerable, and people fix it the
  wrong way** — by disabling the task, or stretching the interval to hours, which
  defeats the design: every routine due since the last tick then fires at once, in
  a batch, instead of each near its own trigger time.
- **Hidden is not blind.** Every run, every failure, and failures *before* cfc
  even starts — a bad path, a missing venv — are appended to
  **`~/.cfc/schedule.log`**, rotated by size. That log is the window you gave up.

Then set a routine's `trigger:` to a time and check it's seen with
`python main.py --due`. Behaviour worth knowing before you rely on it:

- **A job runs once a day, not once a tick.** Whether it already ran is read from
  its run log — there is no separate state file to get out of step.
- **Catch-up is same-day only.** Machine off at 03:00, back at 10:00: it runs,
  late, once. Off three days: once, not three times.
- **`on_failure: retry`** tries again next tick; **`skip`** waits for tomorrow. A
  retry gives up after 3 failures in a day, so a routine failing for a permanent
  reason can't run every 15 minutes until midnight at full API cost.
- **A brief provider hiccup is re-rolled in place and doesn't spend that budget.**
  An HTTP 429, 502 or 503 — and an empty completion — get the same turn retried
  immediately, up to twice. Only the status code decides this, never the error
  text, so a 400 is still a failure however temporary it sounds.
- **An idle tick is silent and exits 0.** It runs ~90 times a day, and a log full
  of "nothing due" is a log nobody reads. The wrapper still writes a dated
  heartbeat per tick, so "did it fire at all?" has an answer.
- Two ticks can't overlap, and a run that gets killed leaves no stale lock behind.
- **A run has two outcomes, not one.** `ok`/`failed` is whether the run mechanically
  completed; a separate `review` flag is raised when the model's own answer says it
  couldn't do the task. A clean loop reporting "those files are outside my allowed
  roots" is a real thing that happens, and it isn't a failure — but it isn't a
  success either.

## The journal

Separate from recall, and don't confuse the two: memory is a *search index* over
a wiki you wrote; the journal is a **diary the model keeps**, in three files that
get shorter as they get older.

```
03 resources/journal/st memory.md    days, as they happen
                     mt memory.md    one block per finished week
                     lt memory.md    single lines, the things that lasted
```

Three routines maintain them and none writes to those files. Each drafts a whole
replacement into `99 outbox/journal/`, and `/list outbox` shows it as a proposal
you can read before anything happens:

```
  1. st memory.md  —  Short term memory   [journal]
     REPLACES /…/03 resources/journal/st memory.md
```

`REPLACES` rather than `→` because filing a journal draft overwrites the live
file — which is what a rollover *is*. That's the one place the outbox's "a target
that already exists is a refusal" rule doesn't hold, so something else has to make
it safe, and that something is git: the journal lives in the vault repo, so **cfc
refuses the move unless the journal is committed.** Then `/wiki diff journal`
shows exactly what the rollover did and `git checkout` undoes it. If git can't be
consulted at all the move is refused rather than done — you can't offer an undo
you haven't checked exists.

**Nothing infers a date.** Each routine is handed the dates it owes, computed by
cfc from the clock and the run log, because a model has no clock and a scheduled
run is a fresh process. Prompts use `{{dates}}` (the days a daily routine owes,
including catch-up after a gap) and `{{week}}` (the Monday–Sunday span a weekly
one should condense, always one that has ended). An unrecognised `{{…}}` is
reported at the start of the run rather than reaching the model as literal text.

Missing days is fine and expected. A day nobody captured anything for gets no
entry; a week with three days in it condenses to three days' worth. The journal
holding less is the correct outcome, not a gap to paper over.

## The notes inbox

`00 inbox/notes` is where raw material goes for the memory routines to read —
nothing there is written by cfc, and nothing removes a note once a routine has
read it. That's deliberate: more than one routine reads the folder, so no
single run can claim it covered everything, and an automatic post-run move
would risk emptying it out from under a routine that hasn't looked yet.

`/clear notes` is the human alternative: it shows every note that will move,
you confirm once, and they're archived together into one dated folder under
`04 archive/cleared notes` — an undo, not a deletion. A backstage `note
template.md` in the inbox is never counted or offered; `/status` shows the
same count `/clear notes` would clear, from the same inventory, so the two can
never disagree. Set `NOTES_DIR` and `NOTES_ARCHIVE_DIR` in `config.py` to turn
it on — both are optional and unset by default, and neither is derived from
`VAULT_ROOT`, which stays display-only.

## Security

Read this before turning tools on.

- **Reads and writes have separate scopes.** `ATTACH_ROOTS`/`TOOLS_ROOTS` bound
  what can be read; `WRITE_ROOTS` — a standalone setting, never derived from the
  read roots — bounds what can be written, and is one folder. Being able to read a
  file says nothing about being able to write next to it. `WRITE_ROOTS = ()` keeps
  the model read-only.
- **The code is structurally unwritable.** A write root overlapping the cfc source
  tree is refused when the context is built. The scripts aren't protected by a
  deny-list entry — they aren't in the writable universe at all.
- **Everything is jailed, and paths are resolved before they're checked**, which
  is what defeats `../` traversal and symlink escape: a symlink named `notes.md`
  pointing at `~/.ssh/id_rsa` is judged as what it resolves to.
- **Some files are refused inside the jail.** A root like `~/projects` contains
  cfc, which contains `config.py`, which holds your API key — and `.py` is
  attachable, so containment alone isn't enough. The deny list runs on the resolved
  path regardless of which root allowed it, covering `config.py` and its backup
  shapes, `.env*`, `*.pem`, `*.key`, `id_rsa`, `.ssh/`, compiled bytecode. You may
  **add** to it via `ATTACH_DENY_EXTRA`; nothing removes.
- **Writes are atomic and don't clobber.** `write_file` writes to a temp file and
  moves it into place. Replacing an existing file needs an explicit `overwrite`,
  and the approval panel says so in red before you agree.
- **The approval gate cannot be switched off.** Every tool call is shown —
  resolved path, real file size — and confirmed before dispatch. There is no
  auto-approve setting; it was removed deliberately. `A` allows the rest of one
  turn, dies with it, and never covers writes.
- **Approval does not bypass validation.** The guard runs inside the dispatcher
  regardless of what was approved. You can approve a call that then fails it;
  that's correct. The gate is where *you* decide, the guard is what holds when
  you've stopped reading the gate carefully.
- **`TOOLS_ENABLED = False` by default.** Opt-in.
- **A small surface** — `list_dir`, `read_file`, `grep`, `write_file`. No shell,
  no delete, no move.
- **Denial is data.** A refused call returns `{"error": …}` as the tool result;
  the model reads it and adapts rather than crashing the turn. Asked to fetch
  `API_KEY`, it gets "config.py is on the deny list" and moves on. **You see
  something different from what the model sees**, and only here: when the
  refusal was yours, the line reads `← read_file denied at the prompt` rather
  than an error, because it isn't one. A refusal cfc made for you — a deny-list
  hit, a path outside the roots — still reads as an error, in red, since that
  is what it is.
- **The model proposes where a file goes; it doesn't put it there.** The suggested
  `destination:` is re-validated from scratch against the mover's own `MOVE_ROOTS`
  — **data, not authority** — and anything outside them is refused rather than
  guessed at. The mover may write outside `WRITE_ROOTS` precisely *because it is
  not the model*, which is why it stays a separate step instead of widening what
  the model can reach.
- **Filing into the wiki is allowed but flagged.** A page filed there leaves the
  recall index stale until it's re-imported, so cfc sets a marker, says so on
  `/file`, keeps saying so on `/list outbox` and `/wiki`, and clears it when
  `/update db` re-imports. The id is stamped by code at approval, never by the
  model, and a page whose id already exists is refused rather than clobbered.
- **`/move` is a human picking a destination, never the model.** It has no
  title argument and no tool schema; the destination is typed at a prompt,
  validated against `MOVE_ROOTS` the same way a suggested `destination:` is.
  Overwriting an existing file needs the word `replace`, typed in full, and
  even then only when git proves the target is tracked and unmodified —
  typing the word is intent, the git check is recoverability, and neither
  substitutes for the other. `rename` (a suggested, non-colliding name) is
  always available instead.
- **Routines are the one ungated path, and that is why they declare their own
  roots.** A chat has two guardrails: the roots, and you at the gate. A routine
  running at 03:00 has no human, so the gate can't function and the roots are all
  that's left. That's why a routine names its roots in its own file, why they're
  validated when it's created rather than when it runs, and why a routine whose
  write root overlaps the source **cannot be saved at all**. The safety is the
  narrow root, never a pre-cleared tool.
- **The run log is closed to the model.** It sits inside the writable outbox, so
  containment alone would admit it — it's refused separately, because it is both
  the audit trail and what the next run reads to honour `on_failure`.

`tests/test_paths.py` and `tests/test_gate.py` are the ones that back this up.
Keep them green.

## The skeleton — two machines, four places

cfc is one program, but the system it sits in is spread across two filesystems
that fail independently, and nothing in the source says so. This section is the
map. It matters most on the day you rebuild something.

**Two machines, in the sense that counts.** cfc runs in WSL2 (Ubuntu) on a
Windows host. That is one physical computer and two storage worlds: Linux's
ext4, which a `wsl --unregister` erases completely, and Windows' NTFS reached
through `/mnt/c`, which survives it. Which side a file lands on decides what
kills it.

| what | where | side | survives a WSL reset |
|---|---|---|---|
| the code | `~/projects/cfc` | ext4 | **no** — but it is on GitHub |
| the state: `chat.db`, snapshots, logs | `~/.cfc/` | ext4 | **no**, and see below |
| the vault's *history* (`.git`) | `~/vaults/wiki.git` | ext4 | **no** — but it has a remote |
| the vault's *files* | `/mnt/c/…/<vault>` | NTFS | yes |
| exported chat transcripts | `/mnt/c/…` (`CHAT_EXPORT_DIR`) | NTFS | yes |

**The vault is split across both sides on purpose**, and it is the one piece of
this that looks like a mistake and isn't. The notes live on the Windows side so
Obsidian and Windows' own backup can see them; the `.git` directory was moved to
ext4 and replaced with a `gitdir:` pointer, because git on a 9p mount is slow
and occasionally strange. The consequence is worth holding in your head: **losing
Windows loses the files but not the history; losing WSL loses the history but not
the files.** Neither failure alone is fatal, which is the accidental virtue of
the arrangement — but only if you know it, which is what this paragraph is for.

**Where the embedder lives, and why it is a separate endpoint.** Chat goes to a
hosted provider over the internet. Embeddings go to LM Studio running as a
**Windows** application, reached from WSL at `localhost:1233` — which only works
because WSL2's `networkingMode=mirrored` makes localhost mean the same thing on
both sides. They are separate because they are different jobs: the corpus is
personal, embedding it is cheap and constant, and sending every note you write to
a third party to get a vector back is a trade with nothing on the other side of
it. It also means memory keeps working when the internet doesn't, and that the
chat provider can be swapped without re-indexing anything. The cost is a second
thing that has to be running — which is the entire reason the connection light
exists.

### What backs up what, and the one gap

| | backed up by | to |
|---|---|---|
| the code | git | GitHub (public) |
| the vault | git, **pushed by hand** | a private GitHub repo |
| chat transcripts | cfc's auto-export, per session | `CHAT_EXPORT_DIR` on the Windows side |
| `chat.db` | `backup.py`, 10 rolling snapshots | `~/.cfc/backups/` — **the same disk** |

**The database has no off-machine copy, and the exports are not one.** On this
machine that is 28 MB of database against 1.5 MB of exported Markdown. The
difference is not compression: the exports are the chat *text*. The retrieval
index, the vectors, the routine transcripts, the token accounting and the tool
metadata exist in one file, on one filesystem, with ten snapshots beside it on
the same disk.

That is not a bug in `backup.py`. Rolling snapshots protect against a corrupted
write, a bad migration and a mistake — which they have, more than once — and
those are the failures that actually happen. They do not protect against losing
the disk, and they were never meant to. **It is written down here so that it is a
decision rather than a discovery.**

**Settled for v1.1: cfc stays local-only.** It keeps verified snapshots; it
does not make an off-machine copy of them, and it does not push anything —
`wikigit.py` issues no `push` for the same reason. That is not the last word on
durability, only this version's: off-machine backup is left to you, as an
explicit step outside cfc rather than a feature inside it, and the database
layer this all sits on is expected to be reworked later regardless.

**cfc never pushes** — not the code, not the vault. `wikigit.py` issues no `push`
and no `remote`, and there is a test that fails if either appears. So "the vault
is backed up" is true exactly as often as you run `git push` in it.

## Backups

cfc snapshots the database to `~/.cfc/backups/` on startup — at most once every 6
hours, skipped when nothing has changed, keeping the newest 10.

```bash
python backup.py                  # snapshot now (skips if unchanged)
python backup.py --force
python backup.py --list
python backup.py --restore latest
```

Snapshots use SQLite's online backup API rather than a file copy, so they're safe
to take while the database is in use, and each is integrity-checked before it's
kept. A restore backs up the current database first.

They've earned their keep beyond disaster recovery: v0.2 resolved a retrieval
mystery by measuring the same query against five months of daily snapshots and
proving the corpus had never changed. A rolling backup is also a record of what
used to be true.

### An off-machine copy, if you want one

cfc doesn't make one — see *the one gap*, above. If losing this machine
entirely is a risk worth covering, the pattern is manual and outside cfc:

```bash
python backup.py --force          # a fresh, integrity-checked snapshot
# then copy that snapshot file yourself, to wherever you trust:
# a private cloud drive, another machine, an external disk.
```

**Never copy the live `~/.cfc/chat.db` itself** — copying mid-write is exactly
what the online backup API in `backup.py --force` exists to avoid, so always
copy the snapshot it produces, not the database. This is deliberately a
pattern for *you* to run, not a feature: cfc has no GitHub credentials, makes
no git commits or pushes of its own, and defines no second backup format to
maintain alongside SQLite's.

## The vault, and why it's a git repo

cfc's memory is not stored in cfc. The corpus is an Obsidian vault on the Windows
side (`/mnt/c/…` from WSL), and the app reads it, indexes it, and writes into one
folder of it. That split explains most of the path handling in `config.py`.

```
<vault>/03 resources/wiki db   the distilled pages recall answers from
<vault>/00 inbox               you write, the model reads
<vault>/99 outbox              the model writes, you read  (the only writable path)
```

The vault is a git repo. Obsidian has no real diff or rollback of its own, and a
daily file backup answers "what does this note say now" but never "what did it
say last week, and what changed it". More to the point it's the plumbing the
automation needs: before a model is allowed to propose edits to the corpus, there
has to be a way to see exactly what it changed and refuse it.

Two setup decisions, both easy to get wrong and neither obvious:

**`.git` does not live in the vault.** It was moved to native Linux storage and
replaced with a one-line pointer:

```bash
git init                                  # inside the vault
mv .git ~/vaults/wiki.git
echo "gitdir: /home/<user>/vaults/wiki.git" > .git
```

`gitdir:` is a standard git redirect — the same mechanism worktrees use — so
every git command run from inside the vault works unchanged. It keeps git's
internals off the slow `/mnt/c` bridge, and makes `.git` a 36-byte file rather
than a folder full of objects, which keeps Obsidian's explorer, search and graph
clear of it. The tradeoff, stated plainly: the history lives outside the Windows
backup that covers the notes themselves, so a WSL reinstall would keep every note
and lose every commit. **Closed on 2026-07-27 by giving the vault repo a remote**
— a private GitHub repo, pushed to by hand.

By hand is the point: cfc commits and never pushes. `/wiki commit` says
`committed locally — cfc does not push` every time, because "committed" reads as
"safe" to anyone who has ever used git with a remote. A push is a network call
against someone else's server with failure modes cfc has no way to explain
(auth, connectivity, a rejected non-fast-forward), run from a REPL that would
block for the duration. `git push` from a terminal is one word and reports its
own errors properly.

**Binaries are not tracked.** `.gitignore` excludes PDFs and images, dropping the
repo from 131 MB to about 7 — static reference material that never gets edited,
already backed up, and a committed blob is in the history permanently. The
extracted Markdown of those PDFs *is* tracked, so the content is versioned even
where the source isn't. Also ignored: `.obsidian/workspace.json` and
`.claude/settings.local.json` (per-device state that rewrites itself every
session — a repo that's always dirty is one whose `git status` you stop reading),
and everything in `99 outbox` except its readme.

**One git config that matters.** `core.autocrlf` is pinned to `false` and
`.gitattributes` sets `* text=auto eol=lf`. Windows git and WSL git normalize line
endings differently, and a file written under one then diffed under the other
shows as *entirely rewritten* with no visible change.

## Known limitations

- **The scheduler needs one entry on the OS side, and it's yours to create.** cfc
  decides *what* is due; something has to call it on a tick.
- **The journal is not in recall** — it's a diary the model writes, not a corpus
  you can question. Reading it back into a conversation is a later idea.
- **Filing a journal draft needs a committed journal.** That's the price of being
  allowed to overwrite a live file at all. If `/list outbox` refuses one,
  `/wiki commit journal` — or a `git checkout` to throw away the hand-edit — is the
  fix.
- **Recall is wiki-only.** Raw chat logs are indexed but not yet folded in. This
  sidesteps the "resolution staleness" problem, where searching transcripts
  surfaces the messages where a decision was *argued* over the one where it was
  settled.
- **Streaming is off when tools are active** — tool-call deltas arrive fragmented
  and have to be reassembled across chunks by index. Not worth it; these responses
  are fast. Reasoning still shows, per step rather than streaming.
- **Tool calling needs a model in `TOOLS_MODELS`**, and unattended runs want one in
  `ROUTINE_MODELS` — not every model handles either well, and one that returns
  empty completions every time will fail a routine loudly rather than quietly
  retrying forever. Both lists were verified against nano-gpt, not assumed.
- Streaming token counts need the provider to support
  `stream_options: {"include_usage": true}`. Without it the post-response bar is
  skipped; `/status` still works from stored data.
- Search is substring (`LIKE`), not full-text. Fine at this scale; FTS5 is a
  possible upgrade.
- **Traits are per-session and don't follow you**, the same way prompts and
  personas already don't. There is no global "always on" trait; if that turns out
  to be the daily move it earns a setting later.
- **`/swap` doesn't exist.** `/add` overwrites the singular layers and appends to
  traits; `/remove` peels. Swap is redundant where it's unambiguous and ambiguous
  where it isn't (*which* trait?), so it's held rather than spent.
- Sessions are linear — no branching. Single user, local machine.

Known rough edges are in `BACKLOG.md`; things that are outright broken are in
`BUGS.md`. Both hold **open entries only** — once something is fixed, its entry
moves to `legacy/` whole, with the original report intact, and `CHANGELOG.md`
records what shipped.

## Tests

```bash
python tests/golden.py check     # the REPL's exact output for every no-API command
python tests/test_paths.py       # and the other 29 suites in tests/
```

`golden.py` is a characterization harness: it pins stdout so a refactor meant to
change nothing is proven to. `record` re-baselines once a change to it is
intended — check the diff first, it exists to catch the changes you *didn't*
intend. None of the suites need an API key.

What they don't cover, and is verified by hand: the chat turn against a real API,
retrieval quality, and how the splash actually looks. `HANDOVER.md` has the full
list with the reason each one is hand-verified — some of them cannot be
automated, and saying which is which is the point.

## Where things are

`HANDOVER.md` has the module map and the reasoning. In short: `main.py` is the
REPL, `parse.py` the grammar, `commands.py` what each verb does, `agent.py` the
tool-calling turn, `paths.py` the jail, `db.py` everything SQLite, `runner.py` and
`schedule.py` the unattended path, `mover.py` the filing step, and the memory
layer is `import_wiki` → `chunk` → `backfill` → `search` → `recall`.

Public template versions of the specialist files that run this repo's
development loop live in `templates/README.md`. The wider set — templates for
starting a project like this one from scratch — is in its own repo,
[Template Vault](https://github.com/Wantotg/Template-Vault-cooking-for-cats).

## License

AGPL-3.0 licensed. See LICENSE.md
