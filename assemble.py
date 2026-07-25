# assemble.py — the system layers of a request, built in one place.
#
# A turn's system prefix is composed from three pools: the system prompt, the
# persona, and any number of traits. This module owns the *order* they land in
# and nothing else. It takes bodies, not names — the caller has already loaded
# them from disk or from the session row — so it reaches for no config, no
# database and no filesystem, and can be tested by calling it.
#
# It exists because the composition was three `if` statements inline in the
# REPL's chat path, which is fine for two layers and stops being fine the
# moment a third is variable-length. Every layer that gets added later is added
# here, once, rather than in the chat path and the tool path and whatever comes
# after them.
#
# **Assembly order is not resolution order.** `/add relax` resolves a bare name
# across the pools by priority (System > Persona > Trait) to decide *which pool
# a name fills*; this decides *where each layer lands in the prompt*. They are
# the same sequence and two independent decisions — they only happen to agree.
# Changing one is not licence to change the other.


def assemble_system(system_prompt=None, persona=None, traits=()):
    """The `system`-role messages for a turn, in the order they are sent.

    persona → system prompt → traits, each as its own message.

    - **persona before system prompt** is what shipped before this function
      existed. It is preserved rather than chosen: moving it changes the bytes
      of every request for no reason anyone has argued for. If a reason turns
      up, this is the one line to change.
    - **traits last, in attach order, not sorted.** Attach order is the only
      order the user can see and control; sorting would silently reorder the
      prompt when a trait is renamed.
    - **one message per trait**, rather than one block with the traits joined.
      A separator would be a format written here and read by eye later, and
      removing a trait should remove exactly one thing.
    - **an empty layer contributes nothing.** A blank prompt file is not a
      blank system message; it is an absent one.
    """
    out = []
    for body in (persona, system_prompt, *(traits or ())):
        if body and body.strip():
            out.append({"role": "system", "content": body})
    return out
