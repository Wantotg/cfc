"""entry_gate_synthetic_config.py — the entry gate's tracked stand-in for
`config.py`.

This is not `config.py` and is never imported under that filename. The gate
loads it under the module name `config` (see `entry_gate_bootstrap.install`)
so every retained flat module's `import config` resolves here instead of to
Cas's ignored root file — whether or not that file exists on this machine.

Every value here is a safe fixture: no real credential, no path that has to
exist, nothing read from disk at import time. A legacy suite that needs a
real directory already builds its own `tmp_path` and monkeypatches the
relevant name — see `tests/test_memory_states.py` and
`tests/test_golden_fixture.py` for the pattern. This file only has to
satisfy `import`, not behaviour.

Field set mirrors `config.example.py` — the same names, in the same shape,
so a field this gate cannot resolve should read as a real gap in the example
route, not a fixture that quietly diverged from it.
"""
from pathlib import Path

API_BASE = "https://entry-gate.invalid/v1"
API_KEY = "entry-gate-fixture-key"
MODEL = "entry-gate/fixture-model"
RECALL_MODEL = "entry-gate/fixture-recall-model"

CHAT_EXPORT_DIR = "entry-gate-fixture/chat-export"
VAULT_ROOT = ""
VAULT_SCOPES = ()

AUTO_EXPORT = True

PROMPTS_DIR = "entry-gate-fixture/prompts"
PERSONAS_DIR = "entry-gate-fixture/personas"
TRAITS_DIR = "entry-gate-fixture/traits"
FIRST_MESSAGES_DIR = "entry-gate-fixture/first-messages"
MAIN_CHAT_DIR = "entry-gate-fixture/main-chat"

MODELS = [
    dict(id="entry-gate/fixture-model", tools=True, routine=True,
         routine_default=True, limit=32_000, preset_params=["temperature", "top_p"]),
]

PARAMETER_PRESETS = {
    "precise": dict(temperature=0.2),
}

EMBED_BASE = API_BASE
EMBED_MODEL = "entry-gate/fixture-embed-model"
EMBED_KEY = "entry-gate-fixture-embed-key"

AUTO_EMBED = True
DATABASE_ACTIVE = True

ATTACH_ROOTS = (
    Path("entry-gate-fixture/attach-root"),
)
ATTACH_EXTENSIONS = {".md", ".txt", ".py", ".json", ".yaml", ".yml",
                      ".toml", ".csv", ".sql", ".sh"}
ATTACH_MAX_CHARS = 150_000
ATTACH_BUDGET_FRACTION = 0.4
ATTACH_DENY_EXTRA = ()

TOOLS_ENABLED = False
TOOLS_ROOTS = ATTACH_ROOTS
WRITE_ROOTS = ()
MOVE_ROOTS = ()

WIKI_DIR = ""
JOURNAL_DIR = ""
LOSER_DIR = ""
NOTES_DIR = ""
NOTES_ARCHIVE_DIR = ""

TOOLS_MAX_CALLS_PER_TURN = 25
TOOLS_MAX_RESULT_CHARS = 30_000
TOOLS_MAX_TURN_RESULT_CHARS = 120_000
ROUTINE_MAX_CALLS_PER_TURN = 30

GOVERNOR_TRAIT_INTERVAL = 6
GOVERNOR_TONE_CHECK = True

ROUTINE_DIR = ""
ROUTINE_PROMPT_DIR = ""
ROUTINE_LOG_DIR = ""

MOUSE_INPUT = False

CONTEXT_GREEN_MAX = 15
CONTEXT_ORANGE_MAX = 35

SPLASH_ART = "balthazar"
