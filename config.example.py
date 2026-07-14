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
