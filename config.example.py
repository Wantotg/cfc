# config.py — copy this file to config.py and fill in your values.
#
# --- the 2.0 bootstrap, read this section first -----------------------------
#
# **Trusted-local-Python boundary.** config.py is not data cfc parses — it is
# a Python file cfc runs, the same way any `import config` always has.
# Anyone who can edit this file can run arbitrary code as you the moment
# anything imports it. That is not a cfc-specific risk to defend against here;
# it is the ordinary trust a local script always has, named explicitly so it
# is a choice rather than an assumption — only put values in this file you
# would be comfortable putting in any other script you run locally.
#
# **Required vs optional.** A fresh clone needs the four settings directly
# below (API_BASE, API_KEY, MODEL, and the 2.0 database target further down)
# to reach ordinary chat. Everything else — the vault, embeddings, file
# tools, routines — is optional: leave it unset and that surface reports
# itself unavailable rather than failing the whole app. Each optional
# section below says so again at the point it starts.
#
# **The copy-and-run route.** After filling in the required settings, run:
#
#     python -m cfc doctor
#
# It reads this file once, validates the settings above and the ones marked
# optional below, and reports each as ready, unavailable (optional and
# unset), error (set, but not usable as written), or not built (a 2.0
# surface that doesn't exist yet, regardless of configuration) — without
# opening a database, creating a directory, or contacting a provider. A
# clean report means the bootstrap is ready, not that a provider or embedder
# is actually reachable — doctor validates format locally, never live.
#
# The v1.9.1 flat application (`python main.py`, or `launch.sh`) reads this
# same file directly and remains the route that actually chats; `cfc doctor`
# is 2.0's parallel readiness check, not a replacement for it yet.
API_BASE = "https://api.nano-gpt.com/v1"   # check their docs for the exact URL
API_KEY  = ""   # paste your key here
MODEL    = "zai-org/glm-5.2:thinking"                    # pick a model your plan supports
RECALL_MODEL = "qwen3-30b-a3b-instruct-2507"             # model that answers /recall (grounded synthesis)

# The 2.0 database target — optional, a fresh install needs nothing here.
# Unset (the default) resolves to Path.home() / ".cfc" / "2.0" / "chat.db",
# a sibling of v1.9.1's own ~/.cfc/chat.db rather than a replacement for it,
# so both can exist on the same machine without either reading the other's
# schema. `cfc doctor` refuses a DB_PATH that resolves to the legacy
# database, this repository, or config.py itself — those are protected
# targets, not configuration choices.
# DB_PATH = ""   # e.g. "~/.cfc/2.0/chat.db" (the default, written out)

# Path to a folder inside your Obsidian vault where chats will be exported.
# The name says both what it holds and that it's a directory — see VAULT_ROOT
# below, which is the vault itself, for the thing this isn't.
#
# Renamed from VAULT_PATH in v1.3.1 (W-0.9.1-01): an existing config.py that
# still defines only VAULT_PATH keeps exporting untouched — export.py resolves
# CHAT_EXPORT_DIR first and falls back to the old name — but there is no
# reason to write a new config with the old one. One-line migration: rename
# your VAULT_PATH line to CHAT_EXPORT_DIR.
CHAT_EXPORT_DIR = "PLACEHOLDER"

# The vault's top folder. **Display only in v1.9.1** — the flat application
# never builds a path from this and no behaviour there depends on it. The 2.0
# bootstrap does read it: `python -m cfc doctor`'s vault row is this setting,
# so an unset VAULT_ROOT reports the vault unavailable however much else is
# configured. Every real v1.9.1 path is configured on its own line
# further down (ROUTINE_DIR, WIKI_DIR, JOURNAL_DIR, MOVE_ROOTS …); this exists
# so what gets *printed* can drop the machine-specific prefix. On WSL that
# prefix is most of the line and none of the information:
#
#   /mnt/c/Users/you/my vault/06 metadata/routines
#   →               /my vault/06 metadata/routines
#
# Leave it "" and paths print in full, which is also what happens to any path
# that resolves outside it — a directory configured somewhere unexpected should
# look different, not be trimmed until it looks local.
VAULT_ROOT = ""             # e.g. "/mnt/c/Users/you/my vault"

# Optional named partitions of the vault, deciding what a model-facing
# surface (chat/routine tools, /add, /recall, /remember, /update db) may
# reach. Each record: a unique `name`, a `path` relative to VAULT_ROOT, and
# `exposed` (True/False). Leave unset — the default — and the whole
# configured vault stays exposed exactly as before; this is an opt-in
# partition, not a demand to classify everything up front.
#
#   VAULT_SCOPES = (
#       dict(name="personal", path="01 personal", exposed=False),
#       dict(name="shared wiki", path="03 resources/wiki db", exposed=True),
#   )
#
# A scope path must resolve under VAULT_ROOT (no absolute path, no `..`, no
# symlink escape) and name a directory that exists. A hidden ancestor always
# wins over a nested exposed scope — privacy is monotonic, so declaration
# order never matters. `/config` then `scopes` shows the resolved state of
# every declared scope; an invalid declaration is reported there and fails
# CLOSED for model-facing vault access only — human screens (/wiki, /file,
# /move, notes) and chat without vault material keep working.
VAULT_SCOPES = ()

# Automatically export session to Obsidian when you leave it
AUTO_EXPORT = True

# Where the three pools of attachable text live: one folder each, one .md
# file per item, the filename is the name. Point them at your Obsidian vault so
# you can edit them there. A system prompt and a persona are singular (one at a
# time); traits are plural and stack, so keep them short and single-purpose.
PROMPTS_DIR = "PLACEHOLDER"
PERSONAS_DIR = "PLACEHOLDER"
TRAITS_DIR = "PLACEHOLDER"

# Optional opening lines for a persona, one .md file per persona filename —
# `muse.md` here is the First Message for the persona `muse.md`. Not a fourth
# pool: it isn't attachable and has no name of its own, only the persona's.
# When a persona with a matching file here first becomes active in a session
# with no chat turns yet, cfc snapshots that file's text onto the session as
# a frozen opening AI turn. Leave unset (or the file absent) and personas work
# exactly as before — a companion is optional per persona, not required.
FIRST_MESSAGES_DIR = "PLACEHOLDER"

# Main chat's one profile bundle: 'm' at the hub opens a single durable
# session whose system prompt and persona are read live from here, and whose
# opening line is frozen once, at creation, from this folder's first
# message.md. Unlike the pools above this is not a folder of many named
# files — it is one folder holding exactly three fixed names:
#
#   <MAIN_CHAT_DIR>/system prompt.md
#   <MAIN_CHAT_DIR>/persona.md
#   <MAIN_CHAT_DIR>/first message.md
#
# All three are required, UTF-8, and non-empty after whitespace is trimmed —
# 'm' refuses and says exactly which is wrong rather than opening an
# unconfigured chat that merely looks like Main. Leave unset and 'm' refuses
# every time, naming MAIN_CHAT_DIR itself as the problem.
MAIN_CHAT_DIR = "PLACEHOLDER"

# Two fixed names cfc will substitute into the shared, model-facing markdown
# it owns as a feature surface: pool bodies (system prompts/personas/traits),
# First Messages, Main's live system prompt/persona, and routine task
# prompts. `{{user}}` and `{{AI}}` are the only two tokens recognised — exact
# case, one literal substitution each, never a general template language.
# Leave unset for the effective defaults below. A value must be a single
# line, non-blank, and no longer than 40 characters; an invalid value is
# reported on /config and leaves the token literal rather than guessing.
# USER_DISPLAY_NAME = "You"           # default when unset
# AI_DISPLAY_NAME = "Cooking for Cats" # default when unset

# Models available on your plan, and everything cfc needs to know about each
# one — one place instead of four. Order is what /list models and /model <n>
# show; nothing here has to be exhaustive, an unlisted id can still be typed
# in full at /model, with a dim note that it isn't configured.
#
# Fields, all optional except id:
#   listed           shown in /list models and /model <n> (default True — set
#                     False for an id you want known but not on that list,
#                     e.g. a routine-only variant you never switch to by hand)
#   tools             emits OpenAI-style tool_calls — verify against your
#                     provider before setting this, don't assume it
#                     (default False)
#   routine           vetted for unattended runs (/routine, --run-due). The
#                     code does not guess this from "thinking" in the name —
#                     that judgement is yours: some thinking models run
#                     routines fine, others stall on empty completions
#                     (default False)
#   routine_default   the model a scheduled --run-due uses when a routine has
#                     no model of its own; at most one record may set this.
#                     Leave every record without it and routines fall back to
#                     MODEL above
#   limit             context window in tokens, for /status's usage bar
#                     (default None — unknown, /status shows a raw count)
#   preset_params     which sampling parameters this model accepts: a list of
#                     "temperature" and/or "top_p", and nothing else. Set it
#                     once you have checked they actually work on this id —
#                     like `tools`, a fact you verified, not a guess. Leave it
#                     unset and no preset can be used with this model
#                     (default: none declared)
#
#                     Parameter names, not preset names. A preset from
#                     PARAMETER_PRESETS below can be selected for this model
#                     when every parameter it sets is listed here.
#
# A config.py still using the pre-1.2.1 shape (MODELS as a bare list of
# strings, plus separate TOOLS_MODELS/ROUTINE_MODELS/MODEL_LIMITS) keeps
# working — it's translated automatically, with one warning at launch.
MODELS = [
    dict(id="zai-org/glm-5.2:thinking", tools=True, limit=1_000_000),
    dict(id="deepseek/deepseek-v4-pro:thinking", tools=True, limit=1_000_000),
    dict(id="deepseek/deepseek-v4-pro", routine=True, routine_default=True,
        limit=1_000_000),
    dict(id="moonshotai/kimi-k2.6:thinking", tools=True, limit=256_000),
]

# Named sampling profiles (v1.5). A name, mapped to temperature (0-2) and/or
# top_p (0-1) — the only two parameters cfc sends. In a chat, `/preset creative`
# selects one and `/preset default` clears it. 'default' is reserved for that,
# so you can't name a preset it.
#
# Turning one on takes both halves — the preset here, and the model above
# saying it accepts those parameters:
#
#   MODELS = [dict(id="some/model", preset_params=["temperature"])]
#   PARAMETER_PRESETS = {"precise": dict(temperature=0.2)}
#
# `precise` sets temperature, `some/model` accepts temperature, so `/preset
# precise` works there. Add top_p to the preset and it stops working until
# top_p is in preset_params too. Only declare a parameter you have actually
# seen the model take — cfc trusts you and sends what you configured.
#
# Leave this empty and nothing changes: presets are opt-in, and a preset with
# no model declaring its parameters is configured but never sent.
PARAMETER_PRESETS = {
    # "creative": dict(temperature=1.1, top_p=0.95),
    # "precise": dict(temperature=0.2),
}

# --- embeddings (RAG) ------------------------------------------------------
# Where the RAG layer gets its vectors. Defaults to nano-gpt's hosted bge-m3,
# using the same key/base as chat. To self-host instead (e.g. bge-m3 on
# LM Studio), point EMBED_BASE at that server's OpenAI-compatible /v1 and set
# EMBED_MODEL to its model id; EMBED_KEY can be any non-empty string if the
# local server ignores auth.
#
# From WSL to a Windows host: mirrored networking, so plain localhost reaches
# it. The NAT gateway IP (`ip route show default`) works only in NAT mode, and
# a gateway IP left here after a switch to mirrored does not resolve at all —
# it fails closed, with nothing on screen to say why. 127.0.0.1 is never right.
#
# EMBED_MODEL must be the server's *own* id for the model, which is not the
# name you searched for: LM Studio serves bge-m3 as
# "text-embedding-baai-bge-m3-568m". A wrong id here is a dead embedder.
EMBED_BASE  = API_BASE
EMBED_MODEL = "BAAI/bge-m3"
EMBED_KEY   = API_KEY

# Embed new chat messages into the memory index after each turn, so /recall can
# reach recent chats. Cheap on a local embedder; on a paid API you may prefer
# False and running /update db manually. A failed embed never breaks a chat turn.
AUTO_EMBED = True

# The default database state for a PRIVATE chat (started with 'p' at the hub).
# A private chat never writes anything down; this is the separate *read* axis —
# whether /recall and /remember may reach the wiki inside one. Default False
# keeps a private chat fully sealed (no memory in, nothing out); /database on
# turns it on for that session. A normal chat always starts with the database on.
DATABASE_ACTIVE = False

# Where the `lms` CLI lives, for launch.sh's preflight check (it starts the
# LM Studio server and loads EMBED_MODEL if they aren't already up). Leave
# unset and preflight.py finds it: `lms` on PATH for a native install, or
# /mnt/c/Users/*/.lmstudio/bin/lms.exe from WSL. Only set this if that fails.
# LMS_CLI = "/mnt/c/Users/you/.lmstudio/bin/lms.exe"

# --- attachments (/add) ----------------------------------------------------
# Files can only be attached from inside one of ATTACH_ROOTS. A path passes if
# it's inside any of them. Paths are resolved before the check, so ../ and
# symlinks can't escape. Some files are refused even inside a root regardless of
# this setting (config.py, .env, keys, .ssh/ ...) — see paths.py.
# ATTACH_DENY_EXTRA adds to that list; nothing removes from it.
from pathlib import Path

ATTACH_ROOTS = (
    Path("~/projects").expanduser(),
    # Add more as needed, e.g. a Windows-side notes folder under WSL:
    # Path("/mnt/c/Users/you/Notes"),
)
ATTACH_EXTENSIONS = {".md", ".txt", ".py", ".json", ".yaml", ".yml",
                     ".toml", ".csv", ".sql", ".sh"}
ATTACH_MAX_CHARS = 150_000
ATTACH_BUDGET_FRACTION = 0.4   # max share of the model's context one file may take
ATTACH_DENY_EXTRA = ()         # e.g. ("*.private.md", "notes-personal.txt")

# --- local file tools ------------------------------------------------------
# Tools the model can request: list_dir, read_file, grep (read) and write_file
# (write). Off by default — opt in per session with /tools on. Which models
# may use them is `tools=True` on that id's MODELS record above, not a
# setting here — GLM 5.2 and DeepSeek v4 Pro are the ones marked above,
# verified against the nano-gpt subscription rather than assumed.
TOOLS_ENABLED = False
TOOLS_ROOTS = ATTACH_ROOTS        # read scope: same jail, same deny list

# Write scope — where write_file may land a file. Deliberately NOT derived
# from ATTACH_ROOTS/TOOLS_ROOTS: an alias is how a read root becomes a write
# root by accident later. Keep it to one narrow folder (an "outbox"), and move
# files out of it by a separate, human-approved step.
#
# Leave it empty to keep the model read-only. context.py refuses any write
# root that overlaps the cfc source tree, so this cannot be widened into the
# code by editing this line.
WRITE_ROOTS = ()

# There is no TOOLS_AUTO_APPROVE. It was removed deliberately: it made
# "pre-clear these tools for everything, forever" a one-line config change.
# Interactive chat gates every call ('A' allows the rest of one turn only).
#
# A turn runs under TWO budgets and they do different jobs. The call count
# bounds round trips; the character count bounds how large the request grows,
# because every call re-sends the whole conversation with all its tool results
# in it. Raising the call ceiling alone makes that strictly worse.
TOOLS_MAX_CALLS_PER_TURN = 25         # tool calls, chat
TOOLS_MAX_RESULT_CHARS = 30_000       # truncate one tool result
TOOLS_MAX_TURN_RESULT_CHARS = 120_000  # all tool output in one turn (~30k tok)

# Routines get a bigger budget: in chat, hitting the ceiling is recoverable
# (the turn ends, you type "continue"), and unattended there is nobody to type
# it. Hitting this is a *failed* run, not a silently truncated ok one.
ROUTINE_MAX_CALLS_PER_TURN = 30

# How often the active conversation governor (governor.py) refreshes a trait
# into the model's attention, in durable user chat turns. Traits already reach
# the model on every request as a system message; this is a recency aid on top
# of that, not a second trait system. 6 is a starting policy, not a measured
# constant — playtest before trusting it. A positive integer sets the
# interval; 0 disables automatic refresh only (traits still ride every
# request as system messages either way).
GOVERNOR_TRAIT_INTERVAL = 6

# Whether the governor's automatic tone cue rides an ordinary chat turn
# (W-1.6.3-01b). This disables only that one cue — never traits, which still
# ride every request as system messages and still get their periodic
# reminder on GOVERNOR_TRAIT_INTERVAL's own cadence, and never an explicit
# OOC direction or /continue, both of which carry their own instruction
# regardless of this switch. True (the default, and what an existing
# config.py without this name keeps) matches today's behaviour.
GOVERNOR_TONE_CHECK = True

# --- routines --------------------------------------------------------------
# A routine is a task the model runs on demand (/routine <name>) or on a
# schedule. One markdown file per routine: frontmatter for the fields, a
# separate file for the task prompt.
#
# A routine must be fully reconstructable from its file — no hidden DB state.
# That is what makes "list" mean list the folder and "delete" mean remove a
# file. Keep these outside the repo (a vault folder is ideal): they are not
# code, so in the working tree they would have to be gitignored, which makes
# them invisible to clones and destroyed by a fresh checkout.
#
# ROUTINE_PROMPT_DIR is a sibling of, not the same as, PROMPTS_DIR — those are
# chat personas, these are tasks.
ROUTINE_DIR = ""            # e.g. "<vault>/06 metadata/routines"
ROUTINE_PROMPT_DIR = ""     # e.g. "<vault>/06 metadata/routine prompts"

# Append-only run log, one file per routine. Put it inside WRITE_ROOTS so the
# same jail covers it. The next run reads this to see whether the last one
# failed — which is why it is a log and not a print.
ROUTINE_LOG_DIR = ""        # e.g. "<vault>/99 outbox/routine logs"

# --- filing proposals out of the outbox ------------------------------------
# The model writes into the outbox with a suggested `destination:` in the
# file's frontmatter; /list outbox lists proposals and /file <n> carries one
# out. The mover re-validates that destination from scratch — the suggestion
# is data, never authority — and refuses anything outside these roots rather
# than guessing at what was meant.
#
# The mover may write outside WRITE_ROOTS **because it is not the model**.
# Keep this separate: widening WRITE_ROOTS to the whole vault would hand the
# model the same reach, which is what the outbox exists to prevent.
MOVE_ROOTS = ()             # e.g. (Path("<vault>"),)

# The wiki corpus: what recall reads, and the default scope of /wiki.
# Filing a page in here changes the corpus without the index knowing, so
# /file sets a reindex marker and says so, and /update db clears it. Leave
# empty if you have no wiki corpus.
WIKI_DIR = ""               # e.g. "<vault>/03 resources/wiki db"

# The journal corpus: the tiered memory files the memory routines rewrite.
# A /wiki … journal scope, and where journal drafts in '<outbox>/journal'
# are filed to. Filing here **replaces** a live file — that is what a rollover
# is — so the mover refuses the move unless this corpus is git-clean, leaving
# /wiki diff journal as the record of what changed. Leave empty if unused.
JOURNAL_DIR = ""            # e.g. "<vault>/03 resources/journal"

# Where a declined draft goes, split by corpus underneath (wiki/, journal/,
# notes/). Declined is not deleted — the draft that turns out to have been the
# good one has to be recoverable. Leave empty to drop into the outbox's own
# 'dropped/' folder instead.
LOSER_DIR = ""              # e.g. "<vault>/03 resources/loser corner"

# --- the notes inbox ---------------------------------------------------
# Raw material for the memory routines to read, and the human-declared batch
# clearing that empties it (/clear notes, D-02). Explicit deployment facts,
# not derived from VAULT_ROOT (display-only) or from each other — an older
# config.py without these two lines simply reports the feature unavailable
# rather than guessing at a path. Both are validated against MOVE_ROOTS, the
# same vault boundary the mover already enforces.
NOTES_DIR = ""              # e.g. "<vault>/00 inbox/notes"
NOTES_ARCHIVE_DIR = ""      # e.g. "<vault>/04 archive/cleared notes"

# --- terminal input --------------------------------------------------------
# Let the mouse position the cursor in the input line. Off by default, and the
# reason is a trade rather than caution: prompt_toolkit's mouse support puts
# the terminal into a reporting mode that captures clicks and drags for the
# whole window while the prompt is live, so click-to-position costs you
# ordinary click-drag selection of the conversation scrolled above it. Most
# terminals still select with Shift held down. Turn it on if you click into
# long multi-line prompts more often than you copy text out of the scrollback.
MOUSE_INPUT = False

# --- context usage colours ------------------------------------------------
# When the token bar turns orange and red, as a percentage of the model's
# claimed context limit. Far below the old 60/80 on purpose: a 1M-token window
# is a vendor claim, not a promise that the last 900k tokens get the same
# attention as the first. The percentages themselves stay honest — these change
# only the colour.
CONTEXT_GREEN_MAX = 15    # green below this
CONTEXT_ORANGE_MAX = 35   # orange up to this, red above

# --- splash ----------------------------------------------------------------
# Which pixel art the launch splash shows. The art itself lives in assets/ —
# it's the app's look, not a deployment knob; only the choice is a preference.
#
#   "balthazar"                one asset, every launch
#   ["balthazar", "mittens"]   one of these, picked at random per launch
#   "*"                        one of everything in assets/, at random
#
# Names map to assets/splash_<name>.raw. A missing or malformed asset skips the
# splash rather than raising — it's decoration, not a reason not to boot.
# dev/bake_splash.py turns an image into one of these.
SPLASH_ART = "*"
