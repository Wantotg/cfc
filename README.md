# cfc — Cooking for Cats

A terminal-based AI chat client written in Python. It connects to any OpenAI-compatible API (built against [nano-gpt](https://nano-gpt.com)), stores every conversation in a local SQLite database, and exports sessions to an Obsidian vault as Markdown.

The name comes from a book cover. It means nothing, intentionally.

For the internals — architecture, data model, invariants, and the reasoning behind the non-obvious choices — see [`HANDOVER.md`](HANDOVER.md).

## Features

- **Rich terminal UI** — a pixel-art splash at launch, live Markdown rendering, colour-coded speaker panels (you, AI reasoning, AI answer), spinners, styled tables, progress bars
- **Streaming responses** rendered as Markdown in real time — with a live view of thinking models' reasoning, and a re-roll when a model returns an empty completion — it asks you if you're there, and retries on its own if you're not. Reasoning shows on the tool path too (rendered per step, not streamed)
- **Local SQLite storage** — every session and message, fully queryable, single portable file
- **Private chat** — start one with `p` at the hub: same client, but it runs in-memory and leaves nothing on disk — no transcript, no memory index, no title, invisible to the hub. Model file-writes are blocked; only an `/export` you type yourself reaches disk
- **Obsidian export** — auto-exports sessions to Markdown with YAML frontmatter
- **Per-session models** — switch models mid-project; each message records what generated it
- **One command grammar** — `/verb [kind] [target] [message]`, twenty-one verbs. `/add` attaches anything (a prompt, a persona, a trait, a file, a tag), `/remove` takes any of it off again, `/status` says what's on, `/list` says what exists. Names are forgiving — a unique partial resolves, ambiguity is a numbered pick, never a guess
- **System prompts, personas & traits** — Markdown files injected as system messages, editable in Obsidian. Prompts and personas are singular; traits stack, so you can compose a voice out of small pieces
- **Tagging** — many-to-many tags, exported to Obsidian frontmatter
- **Search** — case-insensitive substring search across all messages
- **Semantic memory** — a knowledge wiki (Obsidian Markdown) embedded locally; ask it a question and get an answer cited by page, or pull the raw excerpts into the live context. New chats are indexed as they happen
- **File attachments** — inject a local text file into a session; it persists and comes back on reopen
- **Local file tools** — let the model request `list_dir` / `read_file` / `grep` itself, behind an approval gate. It can also `write_file`, but only into one narrow write root that cannot reach your code
- **Token tracking** — live context-usage bar with warnings as the window fills
- **Routines, on command or on a schedule** — a task the model runs against its own declared roots, `/routine <name>` now, at a trigger time, or once a calendar week has finished. One OS scheduler entry covers every routine; cfc decides what's due from each routine's own file and its run log
- **A tiered journal the model maintains** — a rolling diary in three tiers (short, medium, long term), each more compressed than the last. Routines draft the rollovers, you review them with `/list outbox`, and `/file` carries one out. Nothing reaches the live files without you approving it, and the undo is git
- **Propose, review, approve** — everything the model writes lands in one outbox with its destination already worked out, and a human decides. `/file <n>` files it, `/file <n> decline <why>` rejects it and records the reason on the draft for later prompt debugging
- **Vault git from the REPL** — review and commit hand-edited pages with `/wiki diff` / `/wiki commit`, scoped to the wiki corpus by default, the journal or the whole vault on request, per folder or per file
- **Rolling backups** — the database is snapshotted on startup, automatically
- **A launcher that checks its dependencies** — `launch.sh` confirms the embedder is up (starting LM Studio and loading the model if not) before opening the app, so memory failing silently stops being a thing

## Requirements

- Python 3.10+
- `httpx`, `rich`, `prompt_toolkit`, [`sqlite-vec`](https://github.com/asg017/sqlite-vec), and `PyYAML` — see `requirements.txt`
- An API key for an OpenAI-compatible chat provider
- An embedding endpoint for the memory layer — either the provider's hosted `bge-m3`, or a self-hosted one (this setup runs it locally on LM Studio)

## Setup

**1. Clone and enter the project**

```bash
git clone git@github.com:Wantotg/cfc.git
cd cfc
```

**2. Create a virtual environment and install dependencies**

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**3. Create your config**

The repo ships a `config.example.py` with placeholder values. Copy it to `config.py` and fill in your real settings:

```bash
cp config.example.py config.py
```

Then edit `config.py` and set:

- `API_KEY` — your provider's API key
- `API_BASE` — the provider's base URL
- `VAULT_PATH` — folder where exported chats are written; anywhere you like, in your Obsidian vault or outside it
- `PROMPTS_DIR` / `PERSONAS_DIR` — folders for your system-prompt and persona Markdown files
- `MODELS` / `MODEL_LIMITS` — the models your plan supports and their context sizes
- `EMBED_BASE` / `EMBED_MODEL` / `EMBED_KEY` — the embedding endpoint; defaults to the hosted `bge-m3`, or point it at a local server to self-host
- `AUTO_EMBED` — index new chat messages into memory after each turn (default on)
- `SPLASH_ART` — which pixel art the launch splash shows: a name from `assets/`, a list to pick from at random, or `"*"` for all of them (default `"*"`)
- `CONTEXT_GREEN_MAX` / `CONTEXT_ORANGE_MAX` — when the context bar turns orange and red, as a percent of the model's claimed limit (default 15 / 35)
- `MOUSE_INPUT` — click to position the cursor in the input line (default off; see Usage for the trade-off)
- `LMS_CLI` — only if `launch.sh` can't find the LM Studio CLI on its own

`config.py` is gitignored and will never be committed — it holds your key and stays local. It's also on the deny list in `paths.py`, so `/add` and the file tools refuse to read it even though it sits inside the project.

**4. Run**

```bash
python main.py          # straight in
./launch.sh             # venv + an embedder check first (see Usage)
```

Optional shell alias for convenience:

```bash
alias cfc='~/projects/cfc/launch.sh'
```

## Usage

`python main.py` works and always will. `./launch.sh` is the same thing with a
**preflight check** in front of it: it activates the venv, then confirms the
embedder actually answers before opening the app.

That check exists because of an asymmetry. Everything memory-shaped — `/recall`,
`/remember`, `/update db`, the per-turn auto-embed — assumes LM Studio is running
with bge-m3 loaded, and when it isn't, none of them say so. Auto-embed warns
quietly by design; recall just returns nothing, which looks exactly like "memory
has nothing on that". The preflight turns a silent degradation into one line at
launch:

```
  embedder: http://localhost:1233/v1
  ✓ embedder ready — text-embedding-baai-bge-m3-568m (1024-d)
```

If the LM Studio server is off it starts it; if the server is up but the model
isn't loaded it loads it; if it can't fix things it says why and **starts cfc
anyway**. Chat works fine without an embedder, and a launcher that refuses to
open the app because a subsystem is down is worse than the problem it's
guarding. It also checks the vector width against `vec_chunks`'s `float[1024]` —
a wrong-sized embedder doesn't error, it inserts, and you'd find out weeks later
as slightly worse ranking.

### A Windows shortcut

To open cfc from the taskbar or desktop:

1. Right-click the desktop → **New → Shortcut**.
2. For the location, paste this — one line, adjusting the distro name if yours
   isn't `Ubuntu`:

   ```
   wsl.exe -d Ubuntu --cd ~ -- bash -lc "~/projects/cfc/launch.sh"
   ```

3. Name it `cfc`. Finish.
4. Optional, and worth it: right-click the shortcut → **Properties** → **Change
   Icon**, and pick something. Then right-click → **Pin to taskbar**.

`bash -lc` gives you a login shell, so your normal environment is loaded.
`--cd ~` keeps the working directory off `/mnt/c`, which matters because
Windows-side paths are slow to stat from WSL — `launch.sh` finds the repo from
its own location, so the starting directory doesn't otherwise matter.

To get **Windows Terminal** instead of the plain console window (better fonts,
better colours, and the box-drawing characters render properly):

```
wt.exe -p Ubuntu wsl.exe -d Ubuntu --cd ~ -- bash -lc "~/projects/cfc/launch.sh"
```

If the window closes instantly on a crash, that's the console exiting with the
process — `launch.sh` already holds it open on a non-zero exit, so anything that
vanishes silently exited cleanly.

### Running routines on a schedule

A routine's `trigger:` field is one of three things:

| `trigger:` | When it runs |
|---|---|
| `command` | Only when you type `/routine <name>`. The default |
| `0300` | Daily, on the first tick at or after 03:00. A day missed is not replayed the next day |
| `weekly 0330` | When a Monday–Sunday week has *finished* and this routine hasn't processed it yet — **not** "on Mondays". Miss Monday and it runs Tuesday, on the same week |

**Quote a time with a leading zero if you write it by hand:** `trigger: "0300"`.
Unquoted, YAML reads a leading-zero digit string as octal and `0300` becomes
`192`. cfc re-reads the field from the raw file to undo this, and validation
catches what's left, but the quotes make it a non-question. It only affects
`0000`–`0777`, which is to say early-morning times.

Something on the OS side has to call cfc on a tick; cfc works out the rest:

```bash
python main.py --due                  # what's due right now, run nothing
python main.py --run-due              # run everything that's due
python main.py --run-routine <name>   # run one now, due or not
```

**One scheduler entry covers every routine, forever.** `--run-due` reads each
routine's own `trigger:` and its run log and decides what to run, so adding a
routine never means touching the OS scheduler. The alternative — one entry per
routine — makes `trigger:` decorative and puts the real schedule somewhere
other than the file that claims to hold it.

On Windows, use **Task Scheduler**, not cron inside WSL. Windows shuts idle WSL
instances down and cron dies with them, so a 03:00 job would only run if you
happened to leave a terminal open — silently. In an **admin** PowerShell:

```powershell
schtasks /Create /TN "cfc routines" /SC MINUTE /MO 15 /RU $env:USERNAME /RP * `
  /TR "wsl.exe -d Ubuntu -- /home/<you>/projects/cfc/run-due.sh"
```

The **`/RP *`** is the part that matters: it makes the task **run whether or not
you're logged on**, which prompts once for your Windows account password and,
crucially, runs it **in the background with no console window**. (The same
setting is the *"Run whether user is logged on or not"* radio button on the
task's **General** tab if you'd rather use the GUI.) This is the recommended
default, on purpose:

- **A window popping up every 15 minutes is intolerable, and people fix it the
  wrong way.** Left visible, you'll either disable the task outright or stretch
  the interval to hours — and a long interval defeats the whole design: every
  routine due since the last tick then fires *at once*, in a batch, instead of
  each near its own `trigger:` time. A short, invisible tick is what lets
  per-routine trigger times mean anything.
- **Hidden is not blind.** Everything the tick does — every run, every failure,
  and failures *before* cfc even starts (a bad path, a missing venv) — is
  appended to **`~/.cfc/schedule.log`** (rotated by size). That log is the
  window you gave up; check it there instead of watching a console.

Adjust the path and the distro name. Then set a routine's `trigger:` to a time
in its file, and check it's seen:

```bash
python main.py --due
```

Behaviour worth knowing before you rely on it:

- **A job runs once a day, not once a tick.** Whether it already ran is read
  from its run log — there's no separate state file to get out of step.
- **Catch-up is same-day only.** Machine off at 03:00 and back at 10:00: it
  runs, late, once. Off for three days: it runs once, not three times.
- **`on_failure: retry`** tries again on the next tick; **`skip`** waits for
  tomorrow. A retry gives up after 3 failures in a day — otherwise a routine
  failing for a permanent reason would run every 15 minutes until midnight, at
  full API cost, with nobody watching.
- **An idle tick is silent and exits 0.** It runs ~90 times a day; cfc's own
  stdout stays quiet because a log full of "nothing due" is a log nobody reads.
  Failures exit 1. The scheduler wrapper still writes a dated heartbeat line per
  tick to `~/.cfc/schedule.log`, so "did it fire at all?" has an answer even
  when nothing was due.
- Two ticks can't overlap — a lock in `~/.cfc/` sees to that, and a run that is
  killed doesn't leave a stale one behind.

---

Launch shows the **splash** — pixel art, once per run. **Enter** continues,
**Esc** quits. Resize the window while it's up and it redraws. It's skipped
entirely when input isn't a terminal, so piping into cfc behaves exactly as it
did before it existed.

The art is drawn with Unicode half-blocks in truecolor, from a baked asset in
`assets/` — no image library at runtime. Drop another one in and it joins the
rotation. To make one from your own image:

```bash
pip install -r requirements-dev.txt          # Pillow, dev-time only
python dev/bake_splash.py cat.png mittens    # → assets/splash_mittens.raw
```

Past it is the **hub**, listing your 10 most recent **chats** — id, last
update, message count, how full the context is, title, system prompt and
persona — and, below that, your routines with a traffic light on when each last
ran (green under a day, orange under two, red beyond). Routine transcripts and
wiki pages are kept off this list; `/list sessions` inside a session still shows every
session there is. From there:

| Key | Action |
|-----|--------|
| number | Open that session |
| `n` | New session |
| `p` | New **private** chat (nothing saved) |
| `q` | Quit |

The hub is home base: `/q` inside a session brings you back here rather than
quitting, so the program only exits from the hub (`q`, or Ctrl-D/Ctrl-C). The
splash does **not** reappear on the way back — it's a launch screen, not a menu.

A **private chat** (`p`) behaves like a normal one — same model, prompts,
personas, and read tools — but **nothing is written down**. It runs against an
in-memory database, so closing it (`/q`, Ctrl-D, or quitting the app) ends it
for good: no transcript, no memory index, no auto-export, no title, and it never
appears in the hub. There is no restore. Two deliberate exceptions: the model's
own file-writes are blocked (a private chat leaves zero disk artifacts), while
an explicit `/export` *you* type is honoured — the rule is that nothing reaches
disk unless you ask for it by name. The wiki database starts sealed in a private
chat (`/recall`/`/remember` disabled); `/database on` opens it, or set
`DATABASE_ACTIVE = True` in config to have it on by default.

`python main.py 5` opens session 5 directly, skipping the hub — but its `/q`
still returns to the hub.

### In-session commands

Commands start with `/` and follow one grammar:

```
/verb [kind] [target] [message]
```

*kind* is which pool or corpus (optional wherever it can be worked out),
*target* is the thing — a name, a number, a path — and *message* is free text,
always last and always the rest of the line. Two rules hold everywhere: **a bare
integer is a chat id** (`/delete chat 5`, `/title 5 Name`), and **`#n` is an
attachment** (`/remove #1`).

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
| `/help` | Every command, grouped (aliases: `/h`, `/?`) |
| `/list` | The kinds you can list |
| `/list <kind>` | `prompts` · `personas` · `traits` · `models` · `routines` · `tags` · `chats` · `sessions` · `outbox` |
| `/status` | Everything active in this session: prompt, persona, traits, attachments, tags, tools, database, context |
| `/status <kind>` | Print the attached prompt's, persona's or traits' actual text |
| `/config` | Deployment settings (key masked) |
| `/search <word>` | Substring search across all messages |

`/list chats` is the picker's view — real conversations. `/list sessions` is
everything, routine runs and wiki pages included. Two different questions.

**context — attach and detach**

| Command | Action |
|---------|--------|
| `/add <name>` | Attach a system prompt, persona or trait by name |
| `/add <kind> <name>` | Same, naming the pool: `/add trait relax` |
| `/add <path>` | Attach an external file (persistent, comes back on reopen) |
| `/add tag <name>` | Tag this session (`/add tag 3 python` tags session 3) |
| `/remove <name>` | Take off whichever layer is carrying that name |
| `/remove <kind>` | Take off whatever that pool is carrying: `/remove persona` |
| `/remove #<n>` | Detach attachment `n` |
| `/remove tag <name>` | Untag |
| `/remove excerpts` | Drop the most recently injected recall block |

Names are forgiving: case-insensitive, and a unique partial resolves — `/add
relax` finds `Relaxed`. If several things match, you get a numbered list and
pick; nothing is guessed. The confirmation always reports what it picked
(`added Relaxed — Trait`), because on a partial that report *is* how you learn
what happened.

A bare name is looked for in the three pools in priority order — **system prompt,
then persona, then trait** — and fills the highest-priority one not already
carrying it. A path-shaped argument is an external file. The pools are searched
first, so a trait genuinely called `notes.md` still wins over a file.

**Traits are the new pool.** One `.md` file each in `TRAITS_DIR`, exactly like
prompts and personas — the filename is the name, no id, no combined file. Unlike
those two they **stack**: a system prompt and a persona are singular and get
overwritten, traits append in the order you attach them. They belong to the
session, and the *names* are stored, not the text — so editing a trait file
changes what every session carrying it sends, with no re-attaching.

**destroy**

| Command | Action |
|---------|--------|
| `/delete chat` | Delete this conversation, after a confirmation |
| `/delete chat 5` | Delete conversation 5 |

`/delete` always needs a kind, and bare `/delete` lists what is deletable and
acts on nothing. The line between it and `/remove` is not memory-versus-the-rest
— it is **whether retyping the command gets it back.** `/remove` never destroys
anything.

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
| `/new p` | Start a private chat from here (joins `p` at the hub) |
| `/q` | Back to the hub (auto-exports if enabled) |
| `/title <n> <name>` | Rename session `n` |

**settings**

| Command | Action |
|---------|--------|
| `/model <name>` | Switch the session's model (loose names resolve) |
| `/tools` | Whether tools are active, and which switch is blocking |
| `/tools on` / `/tools off` | Toggle tools for this session |
| `/database on` / `/database off` | Enable/disable `/recall` & `/remember` this session (alias `/db`) |

**wiki, routines, filing**

| Command | Action |
|---------|--------|
| `/wiki` | Vault repo status — wiki changes listed, the rest counted |
| `/wiki diff [kind] [file]` | Show the diff. Kind: `wiki` (default), `journal`, `vault`. Add `file` to pick one |
| `/wiki commit [kind] [file] <msg>` | Stage and commit what's in scope; `vault` asks first |
| `/routine <name>` | Run a routine now |
| `/routine new` | Create a routine (name, prompt, roots, trigger) |
| `/file <n>` | File one proposal at its destination (`/list outbox` to review) |
| `/file all` | File every valid proposal |
| `/file <n> decline [why]` | Reject a proposal — moved to the losers' corner with the reason recorded on it (`drop` is the terse form) |

**Two deliberate exceptions to the grammar.** `/file 1 decline <why>` keeps
target-then-action, so it inherits the numbering already on screen; and `/wiki`
carries an extra `folder|file` slot, because it is the one command whose object
has a sub-granularity.

**Coming from the `:` commands?** They still work for this version, with a
one-line note the first time you use one in a session. Verbs that were retired
rather than renamed tell you what replaced them — `/list prompts` says `/list
prompts` — instead of being sent to the model as a message. Both go away in the
next minor version.

**Multi-line input:** just type or paste. Enter sends; **Alt+Enter** inserts a
newline. A pasted block keeps its line breaks and doesn't submit early. Ctrl+C
at the prompt clears the current line (it no longer leaves the session — use
`/q` or Ctrl-D for that); Ctrl+C during streaming cancels the request.

**Tab completion** on `/add`, `/remove`, `/routine` and `/list`.

On `/add` and `/remove` it offers pool names first — every prompt, persona and
trait, in the same priority order the command itself resolves them — and
switches to the filesystem the moment the fragment looks like a path (a slash, a
tilde, a dot). It is the same rule the command uses to decide what you typed, so
completion and dispatch cannot disagree about one line.

Path completion is scoped to `ATTACH_ROOTS`. Type three or more characters of a
name and press Tab; it stays quiet before that rather than dumping a directory.
Pool names and routine names have no such floor — there are a handful of each and
listing them all on a bare Tab is exactly what you want when the thing you can't
remember is the name.

A fragment **with a slash** navigates — `~/projects/cfc/READ` lists that folder.
A fragment **without one** searches by name across the roots, breadth-first, so
a note two folders deep in the vault is found by typing its name. Vault matches
come before repo matches, because the first candidate is the one Tab takes
without a second keystroke. Matching is case-insensitive and never offers a path
`/add` would then refuse.

**`MOUSE_INPUT`** (in `config.py`, default off) lets you click to position the
cursor in the input line. The trade is real: while the prompt is live it
captures the mouse for the whole window, so click-drag selection of the
conversation above needs Shift held down. Worth it if you edit long multi-line
prompts more than you copy text out of the scrollback.

## How it works

The flow:

```
main.py → splash() → repl() ┬→ pick_session() → run_session() ─┐
          Esc → exit         └───────────← /q ←─────────────────┘
                              q at the hub → quit
```

The splash sits outside `repl()` deliberately, which is why it shows once per
launch rather than every time you return to the hub.

- **SQLite** (`~/.cfc/chat.db`) holds sessions, messages, tags, and a session↔tag junction table. Schema and migrations run automatically on start — safe to re-run on an existing database.
- **API layer** streams from an OpenAI-compatible `/chat/completions` endpoint, prepending persona and system prompt as system messages.
- **Rich** drives the terminal UI with `markup=False` (so `[...]` in strings isn't treated as formatting).
- **Export** writes one Markdown file per session, overwriting on re-export — version history lives in the database, not in duplicate files.
- **Message kinds** — every row is tagged `chat`, `attachment`, `recall_marker`, `tool_call` or `tool_result`, with a JSON `meta` blob whose shape follows the kind. That's what lets an attachment export as a one-line reference instead of dumping the whole file, and lets a tool exchange replay in the right order.

## Memory

Recall runs over a **knowledge wiki** — Obsidian Markdown pages, each with a stable id in YAML frontmatter — distilled from past work. Pages are imported, chunked (500 tokens, 75 overlap, never crossing a message boundary), embedded with `bge-m3`, and stored in `sqlite-vec`.

```
python import_wiki.py <wiki_dir> ~/.cfc/chat.db   # import wiki pages (idempotent by id)
python chunk.py ~/.cfc/chat.db                     # chunk
python backfill.py ~/.cfc/chat.db                  # embed
```

Editing a page and re-importing re-chunks and re-embeds it under the same id, so a page's identity survives edits. New in-app chats are indexed automatically after each turn (`AUTO_EMBED`), or on demand with `/update db`; they're tagged `source='chat'` and accumulate for a future wiki+chat hybrid, while recall stays wiki-only for now.

Deleting a session deletes what indexes it. `chunks` and `vec_chunks` are an index over `messages` with no foreign key enforcing the link, so this is code rather than a database constraint — and until 2026-07-23 it wasn't there at all: a deleted conversation stayed searchable, and, because SQLite reuses row ids, a stale chunk could later attach itself to an unrelated message and be cited under it. `/update db` reports any such rows left in an older database and `/update db prune` removes them.

`/recall` synthesises an answer cited by page title and id, and leaves the session untouched. `/remember` injects the raw excerpts into the live context and is ephemeral — only a marker row persists, so an export can still tell a grounded claim from an invented one. `/remove excerpts` drops the last injection.

The embedder is self-hosted here (`bge-m3` on LM Studio) but any OpenAI-compatible `/embeddings` endpoint works — set `EMBED_BASE` / `EMBED_MODEL` / `EMBED_KEY`, or leave them to fall back to the chat provider's hosted copy.

Retrieval has a floor (`MAX_DISTANCE`, currently `1.08`): if nothing is within it, memory says it has no answer rather than returning eight mediocre excerpts. It is deliberately **loose**. Measured over 32 probes, the questions this wiki can answer and the questions it can't overlap so thoroughly that no threshold tells them apart — a question about guitar tuning scores better against the corpus than a real question about its own contents. So the floor only rejects obvious lint, and the model reading the excerpts decides whether they actually answer anything, which it is told to say. Setting it tighter doesn't buy precision, it just loses good questions silently.

The number is specific to `bge-m3` **and** this corpus, including how the corpus is chunked — re-measure if any of those change.

## The journal

Separate from recall, and don't confuse the two: memory is a *search index* over
a wiki you wrote. The journal is a **diary the model keeps**, in three files that
get shorter as they get older.

```
03 resources/journal/st memory.md    days, as they happen
                     mt memory.md    one block per finished week
                     lt memory.md    single lines, the things that lasted
```

Three routines maintain them, and none of them writes to those files. Each
drafts a whole replacement into `99 outbox/journal/`, and `/list outbox` shows it as
a proposal you can read before anything happens:

```
  1. st memory.md  —  Short term memory   [journal]
     REPLACES /…/03 resources/journal/st memory.md
```

`REPLACES` rather than `→` because it is a replacement — filing a journal draft
overwrites the live file, which is what a rollover *is*. That's the one place
the outbox's "a target that already exists is a refusal" rule doesn't hold, so
something else has to make it safe, and that something is git: the journal lives
in the vault repo, so **cfc refuses the move unless the journal is committed.**
Then `/wiki diff journal` shows exactly what the rollover did and
`git checkout` undoes it. If git can't be consulted at all, the move is refused
rather than done — you can't offer an undo you haven't checked exists.

**Nothing infers a date.** Each routine is handed the dates it owes, computed by
cfc from the clock and the run log, because a model has no clock and a scheduled
run is a fresh process with no memory of the last one. Prompts use `{{dates}}`
(the days a daily routine owes, including catch-up after a gap) and `{{week}}`
(the Monday–Sunday span a weekly one should condense — always one that has
ended). An unrecognised `{{…}}` is reported at the start of the run rather than
reaching the model as literal text.

**A weekly routine is due when a finished week hasn't been absorbed yet** —
`trigger: weekly 0330` does *not* mean "Mondays at 03:30". Miss Monday and it
runs on Tuesday, taking the same week. A day-of-week check would simply skip it,
and that week would then age out of short term with nothing having condensed it
— the quiet kind of failure, where the file just holds less and nothing says so.

Missing days is fine and expected. A day nobody captured anything for gets no
entry, a week with three days in it condenses to three days' worth. The journal
holding less is the correct outcome, not a gap to paper over.

## Security

Read this before turning tools on.

- **Reads and writes have separate scopes.** `ATTACH_ROOTS`/`TOOLS_ROOTS` bound what can be read; `WRITE_ROOTS` — a standalone setting, never derived from the read roots — bounds what can be written, and is one folder (an outbox). Being able to read a file says nothing about being able to write next to it. `WRITE_ROOTS = ()` keeps the model read-only.
- **The code is structurally unwritable.** A write root that overlaps the cfc source tree is refused when the context is built, checked in both directions. The model isn't stopped from editing the scripts by a deny-list entry — the scripts aren't in the writable universe at all.
- **Writes are atomic and don't clobber.** `write_file` writes to a temp file and moves it into place, so an interrupted write leaves the original intact. Replacing an existing file needs an explicit `overwrite`, and the approval panel says so in red before you agree.
- **Everything is jailed.** Every file operation resolves inside *any* configured root for its direction — a path passes if it resolves inside *any* configured root. Paths are **resolved before** they're checked, which is what defeats `../` traversal and symlink escape — a symlink named `notes.md` pointing at `~/.ssh/id_rsa` is judged as what it resolves to, not what it's called.
- **Some files are refused inside the jail.** A root like `~/projects` contains cfc, which contains `config.py`, which holds your API key — and `.py` is an attachable type. Containment alone is not enough. The deny list is root-agnostic: it runs on the resolved path no matter which root allowed it, so adding a root never un-denies anything. `paths.py` refuses `config.py`, `.env*`, `*.pem`, `*.key`, `id_rsa`, `.ssh/`, and friends. `config.py` may **add** to that list via `ATTACH_DENY_EXTRA`; nothing removes from it.
- **The approval gate, with no way to switch it off.** Every tool call is shown — resolved path, real file size — and confirmed before dispatch. There is no auto-approve setting: it was removed deliberately, because "pre-clear these tools permanently" is one config line away from becoming "everything runs unattended and unwatched". `A` allows the rest of one turn and dies with it, and it never covers writes — those are asked one at a time.
- **Approval does not bypass validation.** `path_guard` runs inside the dispatcher regardless of what was approved. You can approve a call that then fails the guard; that's correct. The gate is where *you* decide. The guard is what holds when you've stopped reading the gate carefully — which is what a gate that fires on every call eventually becomes.
- **`TOOLS_ENABLED = False` by default.** Opt-in, not opt-out.
- **A small surface.** `list_dir`, `read_file`, `grep`, `write_file`, and nothing else. No shell, no delete, no move.
- **Denial is data.** A denied, skipped or refused call returns `{"error": ...}` to the model as a tool result. It reads it and adapts; it doesn't crash the turn. Asked to fetch `API_KEY`, the model gets `config.py is on the deny list` and moves on — the key never reaches it.
- **The model proposes where a file should go; it doesn't put it there.** A routine writes into the outbox with a suggested `destination:` in the frontmatter. `/list outbox` shows you each suggestion and what would happen; `/file <n>` carries it out. The mover re-validates the destination from scratch against its own `MOVE_ROOTS` — the suggestion is **data, not authority** — and refuses anything outside them rather than guessing at a near-miss. It may write outside `WRITE_ROOTS` precisely *because it is not the model*, which is why it stays a separate step instead of widening what the model can reach. Wiki destinations are refused outright: a page written there would leave the recall index stale with no signal that it's stale.
- **Routines are the one ungated path, and that is the whole reason they declare their own roots.** A chat has two guardrails: the roots, and you at the gate. A routine that runs at 03:00 has no human, so the gate cannot function and its roots are the only thing left. That is why a routine names its own read and write roots in its file, why those are validated when it is created rather than when it runs, and why a routine whose write root overlaps the source **cannot be saved at all**. The safety is the narrow root — never a pre-cleared tool. Every run appends to a log, so an unattended run that failed can't look like one that had nothing to do.

The tests that back this up are worth keeping green: `tests/test_paths.py` covers traversal, symlink escape, the deny list, and the write jail; `tests/test_gate.py` asserts that approving a call still doesn't bypass the guard, that writes are never auto-approved, and that a readable path is not a writable one.

## Known limitations

- **The scheduler needs one entry on the OS side, and it's yours to create** — cfc decides *what* is due, but something has to call it on a tick. See “Running routines on a schedule”. Nothing is scheduled until you set a routine's `trigger:` to a time and add that entry.
- **The journal is not in recall** — it is a diary the model writes, not a corpus you can ask questions of. Reading it back into a conversation is a later idea, not a thing that works today.
- **Filing a journal draft needs a committed journal.** That's the price of being allowed to overwrite a live file at all — see “The journal”. If `/list outbox` refuses one, `/wiki commit journal` (or a `git checkout` to throw away the hand-edit) is the fix.
- **Recall is wiki-only** — the semantic index answers from the distilled wiki, which states each decision once. Raw chat logs are indexed (`source='chat'`) but not yet folded into recall; that hybrid is a future additive step. This sidesteps the old "resolution staleness" problem, where searching raw transcripts surfaced the messages where a decision was being *argued* over the one where it was settled.
- **Streaming is off when tools are active** — tool-call deltas arrive fragmented and the `arguments` string has to be reassembled across chunks by index. Not worth it; these responses are fast. The normal chat path still streams. (Reasoning still shows on the tool path — it just arrives all at once per step rather than streaming in.)
- **Tool calling needs a model in `TOOLS_MODELS`** — not every provider's models handle it. The list was verified against nano-gpt rather than assumed; `/tools` tells you whether the active model qualifies.
- Streaming token counts depend on the provider supporting `stream_options: {"include_usage": true}`. Without it, the post-response bar is skipped, but `/status` still works from stored data.
- Search is substring (`LIKE`), not full-text. Fine at current scale; FTS5 is a possible upgrade.
- **Traits are per-session and don't follow you** — they belong to the chat they were attached to, the same way a system prompt and a persona already do. There is no global "always on" trait; if that turns out to be the daily move, it earns a setting later rather than a third scope invented on spec.
- **`/swap` doesn't exist.** `/add` overwrites the singular layers and appends to traits; `/remove` peels. Swap is redundant where it's unambiguous and ambiguous where it isn't (*which* trait?), so it is held rather than spent.
- Sessions are linear — no branching.
- Single user, local machine.

Known rough edges live in `BACKLOG.md`.

## Project structure

| File | Holds |
|---|---|
| `main.py` | the REPL: dispatch, and the live session state |
| `parse.py` | the command grammar: one line in, a verb and its arguments out |
| `commands.py` | what each command does, and the approval gate |
| `pools.py` | the three pools — prompts, personas, traits — and the name resolver |
| `assemble.py` | the system layers of a request, in order |
| `agent.py` | the tool-calling turn |
| `tools.py` | the tools and the dispatcher |
| `context.py` | what a given run may read, write, and whether it's gated |
| `paths.py` | the jail: containment and the deny list |
| `routines.py` | the routine object, its file store, and the run log |
| `runner.py` | running one routine — the headless entry point in all but name |
| `schedule.py` | which routines are due, and the `--run-due` entry point |
| `mover.py` | filing a proposal out of the outbox: re-validates the destination, or refuses |
| `wikigit.py` | the vault repo: status, diff and commit, scoped to a corpus by default |
| `preflight.py` | the launcher's embedder check — is LM Studio up with bge-m3 loaded? |
| `complete.py` | Tab completion for `/add`, `/remove`, `/routine`, `/list` |
| `hub.py` | the session browser and picker |
| `db.py` | connection, schema, every query |
| `api.py` | streaming and non-streaming calls to the endpoint |
| `export.py` | writing a session out to the vault |
| `backup.py` | rolling snapshots of the database |
| `ui.py` | the shared console, presentation helpers, and the line editor |
| `splash.py` | the launch screen — pixel art, composited with the title |
| `config.py` | settings — gitignored |
| `launch.sh` | preflight, then cfc — what the desktop shortcut runs |
| `run-due.sh` | preflight, then `--run-due` — what the OS scheduler runs |

The memory layer is separate: `import_wiki.py` (and `import_anthropic.py`), `chunk.py`, `embed.py`, `backfill.py`, `search.py`, `recall.py`.

## Tests

```bash
python tests/golden.py check     # the REPL's exact output, for every no-API command
python tests/test_paths.py       # the jail
python tests/test_tools.py       # tools and dispatcher
python tests/test_gate.py        # the approval gate
python tests/test_agent.py       # the agent loop and tool replay
python tests/test_attach.py      # /add / /status / /remove
python tests/test_schema.py      # the kind/meta migration, and the delete cascade
python tests/test_litter.py      # the litter filter's marker coupling
python tests/test_routines.py    # the routine file round-trip, scope refusal, run log
python tests/test_mover.py       # filing: destination re-validation, refusals, atomicity
python tests/test_empty.py       # empty completions: ask a human, or re-roll and give up
python tests/test_chunk.py       # chunk sizing and boundary seeking at both edges
python tests/test_wikigit.py     # vault git: scope containment, the -z parse, no push
python tests/test_preflight.py   # the embedder check: dimension guard, never hangs
python tests/test_complete.py    # /add completion: vault first, and the jail holds
python tests/test_splash.py      # the splash compositor: aspect, resampling, the key read
python tests/test_hub.py         # the screens: chat filter, colours, routine freshness
python tests/test_private.py     # private chat: real db untouched, writes blocked, db toggle
python tests/test_schedule.py    # what's due and what isn't: catch-up, on_failure, the lock
python tests/test_parse.py       # the grammar, and that the verb lists agree
python tests/test_pools.py       # the three pools, and a session's trait list
python tests/test_resolve.py     # the resolver: tiers, the collision walk, never guessing
python tests/test_assemble.py    # the system layers: order, and that empty means absent
```

None of them need an API key. `golden.py record` re-baselines the output once a change to it is intended — check the diff first; it's there to catch the changes you *didn't* intend.

## Backups

cfc snapshots the database to `~/.cfc/backups/` on startup — at most once every 6 hours, skipped entirely when nothing has changed, keeping the newest 10.

```
python backup.py                  # snapshot now (skips if unchanged)
python backup.py --force          # snapshot regardless
python backup.py --list           # show what's kept
python backup.py --restore latest # roll back to the newest snapshot
```

Snapshots use SQLite's online backup API rather than a file copy, so they're safe to take while the database is in use, and each is integrity-checked before it's kept. A restore backs up the current database first — restoring the wrong one is recoverable.

Those snapshots have already earned their keep beyond disaster recovery: v0.2 resolved a retrieval mystery by measuring the same query against five months of daily snapshots and proving the corpus had never changed. A rolling backup is also a record of what used to be true.

## The vault, and why it's a git repo

cfc's memory is not stored in cfc. The corpus is an Obsidian vault on the Windows side (`/mnt/c/...` from WSL), and the app reads it, indexes it, and writes into one folder of it. Understanding that split explains most of the path handling in `config.py`.

```
<vault>/03 resources/wiki db   the distilled pages that recall answers from
<vault>/00 inbox               Cas writes, the model reads
<vault>/99 outbox              the model writes, Cas reads  (the only writable path)
```

As of 2026-07-21 the vault is a git repo. Obsidian has no real diff or rollback of its own, and the daily file backup answers "what does this note say now" but never "what did it say last week, and what changed it." More to the point, it's the plumbing the wiki automation needs: before a model is allowed to propose edits to the corpus, there has to be a way to see exactly what it changed and refuse it.

Two setup decisions are worth recording, because both are easy to get wrong and neither is obvious.

**`.git` does not live in the vault.** It was moved to native Linux storage and replaced with a one-line pointer:

```bash
git init                                  # inside the vault
mv .git ~/vaults/wiki.git
echo "gitdir: /home/<user>/vaults/wiki.git" > .git
```

`gitdir:` is a standard git redirect — the same mechanism worktrees and submodules use — so every `git` command run from inside the vault works unchanged. It buys two things. Git's internals stop being read and written across the `/mnt/c` bridge, which is markedly slower than ext4; and `.git` becomes a 36-byte file rather than a folder full of objects, which keeps Obsidian's file explorer, search and graph clear of it. (Obsidian hides dotfiles anyway — this was confirmed by looking, not assumed.)

The tradeoff, stated plainly: the history now lives outside the Windows daily backup that covers the notes themselves. A WSL reinstall would keep every note and lose every commit. A remote would close that, and is parked at v1.0 alongside the question of whether the vault's medical reference material belongs on someone else's server.

**Binaries are not tracked.** `.gitignore` excludes PDFs and images, which drops the repo from 131 MB to about 7. They're static reference material that never gets edited, they're already backed up, and a committed blob is in the history permanently. The extracted Markdown of those PDFs *is* tracked, so the content is versioned even where the source file isn't. Also ignored: `.obsidian/workspace.json` and `.claude/settings.local.json` (per-device state that rewrites itself every session — a repo that's always dirty is a repo whose `git status` you stop reading), and everything in `99 outbox` except its readme, since a scratch folder has no meaningful clean state.

**One git config that matters.** `core.autocrlf` is pinned to `false` and `.gitattributes` sets `* text=auto eol=lf`. Windows git and WSL git normalize line endings differently, and a file written under one then diffed under the other shows as *entirely rewritten* with no visible change. The vault is worked on from Ubuntu only; the `.gitattributes` is belt-and-braces in case that ever slips.

## License

Personal project. No license specified.
