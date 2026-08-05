#!/usr/bin/env python3
"""test_wire.py — the shape sent to the provider, and the shape we keep.

`api.wire_messages` is the surviving suspect for the provider 400 on tool turns
(`development/BUGS.md`): `agent.py` normalises a missing `content` to `""` on the assistant
message carrying `tool_calls`, and some OpenAI-compatible providers want that
field absent and reject the replay on the next request.

Two things are pinned, and the second matters more than the first.

  1. The transform does what it says: `content` is dropped only from an
     assistant message that carries tool calls and has nothing to say.
  2. **It never touches the input.** `history` is what gets persisted and
     replayed, and standing decision 2 lives in it — every tool call keeping
     exactly one result. A wire-format fix that reached back into those dicts
     would edit the record of the conversation to satisfy a provider.

There is no test here that the fix *works*, because that cannot be written: the
bug has no reproduction. This pins the change, not the cure — see `development/BUGS.md`.

No network, no API key.
"""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api


def check(label, got, want):
    assert got == want, f"{label}: got {got!r}, want {want!r}"
    print(f"  ok  {label}")


CALLS = [{"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}]


def test_drops_only_the_right_key():
    print("content is dropped only where it is both empty and redundant")
    out = api.wire_messages([{"role": "assistant", "content": "",
                              "tool_calls": CALLS}])
    check("empty content beside tool_calls is dropped", "content" in out[0], False)
    check("...and the tool_calls survive", out[0]["tool_calls"], CALLS)
    check("...and the role survives", out[0]["role"], "assistant")

    # A tool-call message that also said something keeps it: the model
    # narrating what it is about to do is content the provider should see.
    out = api.wire_messages([{"role": "assistant", "content": "reading it now",
                              "tool_calls": CALLS}])
    check("real content beside tool_calls is kept",
          out[0]["content"], "reading it now")

    # An ordinary empty assistant message is NOT a tool-call message. Dropping
    # its content would change what an empty completion looks like on the wire,
    # which is a different bug in a feature that already exists (the re-roll).
    out = api.wire_messages([{"role": "assistant", "content": ""}])
    check("an empty message with no tool_calls is untouched",
          out[0], {"role": "assistant", "content": ""})

    # Whitespace-only is empty. A provider that rejects "" has no reason to
    # accept "\n".
    out = api.wire_messages([{"role": "assistant", "content": "  \n ",
                              "tool_calls": CALLS}])
    check("whitespace counts as empty", "content" in out[0], False)

    for role in ("user", "system", "tool"):
        msg = {"role": role, "content": ""}
        check(f"a {role} message is never rewritten",
              api.wire_messages([msg])[0], msg)


def test_does_not_mutate_history():
    print("history is left exactly as it was")
    history = [
        {"role": "user", "content": "read a file"},
        {"role": "assistant", "content": "", "tool_calls": CALLS},
        {"role": "tool", "tool_call_id": "c1", "content": "the file"},
    ]
    before = copy.deepcopy(history)
    out = api.wire_messages(history)
    check("the input list is unchanged", history, before)
    # ...including identity: a new dict, not the same one with a key removed.
    check("the rewritten message is a new object",
          out[1] is history[1], False)
    # The untouched ones may be shared — copying them would be waste, and
    # nothing here writes to them.
    check("the wire form is the same length", len(out), len(history))
    # Standing decision 2: the tool result must still be there to answer the
    # call. A transform that dropped or reordered messages would break replay.
    check("every tool call still has its result",
          [m.get("role") for m in out], ["user", "assistant", "tool"])
    check("the call id still matches its result",
          out[1]["tool_calls"][0]["id"], out[2]["tool_call_id"])


def test_both_paths_go_through_it():
    print("neither API path can forget the transform")
    # The streaming path is the easy one to forget: it does not use tools, so
    # it looks like it cannot carry a tool-call message. It can — a session
    # that made tool calls and then switched to a non-tools model replays
    # exactly those messages through it. Pinned by reading the source, because
    # the alternative is a live provider.
    src = Path(api.__file__).read_text()
    payloads = src.count('"messages": wire_messages(messages),')
    check("both payloads call it", payloads, 2)
    check("no payload passes messages raw",
          '"messages": messages,' in src, False)


if __name__ == "__main__":
    test_drops_only_the_right_key()
    test_does_not_mutate_history()
    test_both_paths_go_through_it()
    print("\nall wire-format tests passed")
