# config.py — fill in your values from the nano-gpt dashboard
API_BASE = "https://api.nano-gpt.com/v1"   # check their docs for the exact URL
API_KEY  = ""   # paste your key here
MODEL    = "zai-org/glm-5.2:thinking"                    # pick a model your plan supports
RECALL_MODEL = "qwen3-30b-a3b-instruct-2507"             # model that answers :recall (grounded synthesis)

# Path to a folder inside your Obsidian vault where chats will be exported
VAULT_PATH = "PLACEHOLDER"

# Automatically export session to Obsidian when you leave it
AUTO_EXPORT = True

# Where system prompt markdown files are stored
# Point to a folder in your Obsidian vault so you can edit prompts there
PROMPTS_DIR = "PLACEHOLDER"
PERSONAS_DIR = "PLACEHOLDER"

# Models available on your plan (for the :models command)
# Replace these with the actual model names from your nano-gpt dashboard
MODELS = [
    "zai-org/glm-5.2:thinking",
    "deepseek/deepseek-v4-pro:thinking",
    "moonshotai/kimi-k2.6:thinking",
]

# Models vetted for routines (unattended runs). The FIRST entry is the default
# a scheduled --run-due uses when no model is passed; an on-command :routine on
# a model that isn't in this list nudges (y/n) before running. The code trusts
# the list — it does NOT detect "thinking" models, because that judgement is
# yours: some thinking models run routines fine, others stall on empty
# completions. Leave unset/empty to fall back to MODEL and skip the nudge.
ROUTINE_MODELS = [
    "deepseek/deepseek-v4-pro",
    "minimax/minimax-m3",
]

# Context window size in tokens for each model
# Used by :tokens to show how full the context is
MODEL_LIMITS = {
    "zai-org/glm-5.2:thinking": 1000000,
    "deepseek/deepseek-v4-pro:thinking": 1000000,
    "moonshotai/kimi-k2.6:thinking": 256000,
}

# --- embeddings (RAG) ------------------------------------------------------
# Where the RAG layer gets its vectors. Defaults to nano-gpt's hosted bge-m3,
# using the same key/base as chat. To self-host instead (e.g. bge-m3 on
# LM Studio), point EMBED_BASE at that server's OpenAI-compatible /v1 and set
# EMBED_MODEL to its model id; EMBED_KEY can be any non-empty string if the
# local server ignores auth. From WSL to a Windows host, use the NAT gateway
# IP (see `ip route show default`) or mirrored networking, not 127.0.0.1.
EMBED_BASE  = API_BASE
EMBED_MODEL = "BAAI/bge-m3"
EMBED_KEY   = API_KEY

# Embed new chat messages into the memory index after each turn, so :recall can
# reach recent chats. Cheap on a local embedder; on a paid API you may prefer
# False and running :updatedb manually. A failed embed never breaks a chat turn.
AUTO_EMBED = True

# The default database state for a PRIVATE chat (started with 'p' at the hub).
# A private chat never writes anything down; this is the separate *read* axis —
# whether :recall/:remember may reach the wiki inside one. Default False keeps a
# private chat fully sealed (no memory in, nothing out); :database on turns it
# on for that session. A normal chat always starts with the database on.
DATABASE_ACTIVE = False

# Where the `lms` CLI lives, for launch.sh's preflight check (it starts the
# LM Studio server and loads EMBED_MODEL if they aren't already up). Leave
# unset and preflight.py finds it: `lms` on PATH for a native install, or
# /mnt/c/Users/*/.lmstudio/bin/lms.exe from WSL. Only set this if that fails.
# LMS_CLI = "/mnt/c/Users/you/.lmstudio/bin/lms.exe"

# --- :attach ---------------------------------------------------------------
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
# (write). Off by default — opt in per session with ":tools on".
#
# TOOLS_MODELS was verified against the nano-gpt subscription, not assumed:
# these three emit OpenAI-style tool_calls. GLM 5.2 is the intended primary
# driver.
TOOLS_ENABLED = False
TOOLS_MODELS = [
    "zai-org/glm-5.2:thinking",
    "deepseek/deepseek-v4-pro:thinking",
    "moonshotai/kimi-k2.6:thinking",
]
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
# in it. Until v0.5 only the first existed, and it counted loop iterations
# rather than calls — so a model asking for four reads per message spent one
# of its eight, and a browsing turn could quietly build a 200k-token request
# that the provider rejected with a 400 about max_tokens.
TOOLS_MAX_CALLS_PER_TURN = 25         # tool calls, chat
TOOLS_MAX_RESULT_CHARS = 30_000       # truncate one tool result
TOOLS_MAX_TURN_RESULT_CHARS = 120_000  # all tool output in one turn (~30k tok)

# Routines get a bigger budget: in chat, hitting the ceiling is recoverable
# (the turn ends, you type "continue"), and unattended there is nobody to type
# it. Hitting this is a *failed* run, not a silently truncated ok one.
ROUTINE_MAX_CALLS_PER_TURN = 30

# --- routines --------------------------------------------------------------
# A routine is a task the model runs on demand (":routine <name>") and, later,
# on a schedule. One markdown file per routine: frontmatter for the fields,
# a separate file for the task prompt.
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
# file's frontmatter; ":outbox" lists proposals and ":file <n>" carries one
# out. The mover re-validates that destination from scratch — the suggestion
# is data, never authority — and refuses anything outside these roots rather
# than guessing at what was meant.
#
# The mover may write outside WRITE_ROOTS **because it is not the model**.
# Keep this separate: widening WRITE_ROOTS to the whole vault would hand the
# model the same reach, which is what the outbox exists to prevent.
MOVE_ROOTS = ()             # e.g. (Path("<vault>"),)

# Destinations under here are refused outright. Writing a page into the wiki
# changes the corpus, but the index doesn't know until import_wiki.py runs, so
# recall would answer from a stale copy with no signal that it's stale. Leave
# empty if you have no wiki corpus.
WIKI_DIR = ""               # e.g. "<vault>/03 resources/wiki db"

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
