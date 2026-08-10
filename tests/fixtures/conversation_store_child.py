"""conversation_store_child.py — a real separate process that opens the 2.0
conversation store, starts one active turn, and then holds the store
without ever finalising that turn, for
`tests/test_cfc_conversation_store.py`'s cross-process ownership proof.

Usage: `python conversation_store_child.py <db_path> <ready_path> <info_path>`.
Writes `chat_id\nturn_id\n` to `info_path`, then `ready_path`, once the
active turn is durably stored. The parent kills this process outright
(no graceful shutdown) so the ownership lock is released the way a real
crash releases it — by the kernel, when every file descriptor referencing
it closes — rather than by this script's own cleanup code running.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from cfc import conversation_store  # noqa: E402


def main() -> int:
    db_path = Path(sys.argv[1])
    ready_path = Path(sys.argv[2])
    info_path = Path(sys.argv[3])

    store = conversation_store.open_store(db_path)
    chat = store.create_chat("child-owned chat", "fixture-model")
    turn, _message = store.start_turn(chat.id, model="fixture-model",
                                       user_content="hi from the child process")
    info_path.write_text(f"{chat.id.value}\n{turn.id.value}\n", encoding="utf-8")
    ready_path.write_text("ready", encoding="utf-8")

    while True:
        time.sleep(0.05)


if __name__ == "__main__":
    sys.exit(main())
