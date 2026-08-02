# names.py — {{user}} and {{AI}} personalisation for cfc-owned shared markdown.
#
# One pure substitution helper, called only from the loaders that already own
# a shared, model-facing instruction file: pools.load (system prompts,
# personas, traits) and pools.load_first_message, mainchat._read (Main's
# system prompt, persona and creation First Message), and runner.py's routine
# task prompt. Nothing else calls this — attachments, recall excerpts, vault
# pages, user/model messages and tool traffic are content, not a template
# cfc owns, and stay untouched.
#
# Two exact, case-sensitive tokens, one literal `.replace` pass each. No
# regex, no `.format`, no recursive pass — a configured name's own braces are
# inserted as-is and never rescanned as a second placeholder.
try:
    from config import USER_DISPLAY_NAME
except ImportError:
    USER_DISPLAY_NAME = None
try:
    from config import AI_DISPLAY_NAME
except ImportError:
    AI_DISPLAY_NAME = None

DEFAULT_USER = "You"
DEFAULT_AI = "Cooking for Cats"

# Not measured, chosen: long enough for a real name or short title, short
# enough that a pasted paragraph is obviously not one and reads as the
# config error it is rather than being sent to a model as someone's name.
MAX_LEN = 40

USER_TOKEN = "{{user}}"
AI_TOKEN = "{{AI}}"
TOKENS = (USER_TOKEN, AI_TOKEN)


def problem(value, label):
    """Why a configured display name is invalid, or None. `value=None` (the
    setting is absent) is never a problem — only a value that was SET wrong
    is reported; an absent one uses the default silently."""
    if value is None:
        return None
    if not isinstance(value, str):
        return f"{label} must be a string"
    if "\n" in value or "\r" in value:
        return f"{label} must be a single line"
    if not value.strip():
        return f"{label} must not be blank"
    if len(value) > MAX_LEN:
        return f"{label} is {len(value)} characters, over the {MAX_LEN} limit"
    return None


def effective_names():
    """(user_name, ai_name, problems).

    Each name is the configured value when it's valid, the effective default
    when the setting is absent, or None when it's set but invalid — `apply`
    reads None as "leave the token literal", which is the visible-error
    behaviour Concept.md asks for rather than a silent fallback to the
    default. `problems` lists what's wrong, for /config to show.
    """
    problems = []

    p = problem(USER_DISPLAY_NAME, "USER_DISPLAY_NAME")
    if p:
        problems.append(p)
        user = None
    else:
        user = USER_DISPLAY_NAME if USER_DISPLAY_NAME is not None else DEFAULT_USER

    p = problem(AI_DISPLAY_NAME, "AI_DISPLAY_NAME")
    if p:
        problems.append(p)
        ai = None
    else:
        ai = AI_DISPLAY_NAME if AI_DISPLAY_NAME is not None else DEFAULT_AI

    return user, ai, problems


def apply(text):
    """Substitute `{{user}}` and `{{AI}}` in `text` with the effective
    configured names. Exact, case-sensitive, a single pass over the
    ORIGINAL text — an invalid configured value leaves its token untouched
    rather than guessing.

    Deliberately not two sequential `str.replace` calls: replacing
    `{{user}}` first and then scanning for `{{AI}}` would also match an
    `{{AI}}` that `{{user}}`'s own *replacement* just inserted — a
    configured `USER_DISPLAY_NAME` containing that literal text would come
    out substituted a second time, which is exactly the "braces inside a
    configured name are never scanned as a second placeholder pass" rule.
    Walking the source text once and copying straight to the output means a
    replacement value is never itself re-examined.
    """
    if not text:
        return text
    user, ai, _ = effective_names()
    replacements = {}
    if user is not None:
        replacements[USER_TOKEN] = user
    if ai is not None:
        replacements[AI_TOKEN] = ai
    if not replacements:
        return text

    out = []
    i, n = 0, len(text)
    while i < n:
        for token, value in replacements.items():
            if text.startswith(token, i):
                out.append(value)
                i += len(token)
                break
        else:
            out.append(text[i])
            i += 1
    return "".join(out)
