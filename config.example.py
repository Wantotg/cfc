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
# Files can only be attached from inside ATTACH_ROOT. Paths are resolved before
# the check, so ../ and symlinks can't escape it. Some files are refused even
# inside the root regardless of this setting (config.py, .env, keys, .ssh/ ...)
# — see paths.py. ATTACH_DENY_EXTRA adds to that list; nothing removes from it.
from pathlib import Path

ATTACH_ROOT = Path("~/projects").expanduser()
ATTACH_EXTENSIONS = {".md", ".txt", ".py", ".json", ".yaml", ".yml",
                     ".toml", ".csv", ".sql", ".sh"}
ATTACH_MAX_CHARS = 100_000
ATTACH_BUDGET_FRACTION = 0.4   # max share of the model's context one file may take
ATTACH_DENY_EXTRA = ()         # e.g. ("*.private.md", "notes-personal.txt")
