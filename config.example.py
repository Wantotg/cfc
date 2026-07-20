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
    "longcat-2.0",
]

# Context window size in tokens for each model
# Used by :tokens to show how full the context is
MODEL_LIMITS = {
    "zai-org/glm-5.2:thinking": 1000000,
    "deepseek/deepseek-v4-pro:thinking": 1000000,
    "moonshotai/kimi-k2.6:thinking": 256000,
    "longcat-2.0": 1000000,
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
ATTACH_MAX_CHARS = 100_000
ATTACH_BUDGET_FRACTION = 0.4   # max share of the model's context one file may take
ATTACH_DENY_EXTRA = ()         # e.g. ("*.private.md", "notes-personal.txt")

# --- local file tools ------------------------------------------------------
# Tools the model can request: list_dir, read_file, grep (read) and write_file
# (write). Off by default — opt in per session with ":tools on".
#
# TOOLS_MODELS was verified against the nano-gpt subscription, not assumed:
# these three emit OpenAI-style tool_calls; longcat-2.0 rejects
# /v1/chat/completions outright. GLM 5.2 is the intended primary driver.
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
TOOLS_MAX_CALLS_PER_TURN = 8      # loop breaker
TOOLS_MAX_RESULT_CHARS = 30_000   # truncate tool output
