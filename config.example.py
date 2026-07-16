# config.py — fill in your values from the nano-gpt dashboard
API_BASE = "https://api.nano-gpt.com/v1"   # check their docs for the exact URL
API_KEY  = "PLACEHOLDER"   # paste your key here
MODEL    = "zai-org/glm-5.2:thinking"                    # pick a model your plan supports

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
# Read-only tools the model can request: list_dir, read_file, grep. Off by
# default — opt in per session with ":tools on".
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
TOOLS_ROOTS = ATTACH_ROOTS        # same jail, same deny list
TOOLS_AUTO_APPROVE = set()        # e.g. {"list_dir"} once trusted; empty gates everything
TOOLS_MAX_CALLS_PER_TURN = 8      # loop breaker
TOOLS_MAX_RESULT_CHARS = 30_000   # truncate tool output
