# search_worker.py — the v1.7 offline search worker.
#
# Runs *inside* the Bubblewrap sandbox websearch.py builds: no network, no
# filesystem beyond its own read-only mount, a cleared environment. Depends
# on nothing but the stdlib and search_protocol.py, mounted beside it at the
# same sandboxed path — no other cfc import exists to reach for, since
# nothing else is mounted.
#
# One behaviour, always: read the request, answer `unavailable` /
# `not_available_yet`, exit. There is no search provider in v1.7 — see
# HANDOVER.md and Concept.md for why that is the whole point of this
# version. A later version that adds one replaces this file's body; the
# request/response shape and the sandbox around it do not need to change.
import sys

import search_protocol as proto


def main():
    raw = sys.stdin.read()
    query, err = proto.parse_request(raw)
    if err is not None:
        # The host never sends a malformed request — this exists so the
        # worker's own boundary can be driven directly (Work Order step 2's
        # plain-subprocess proof), without needing the sandbox to exercise
        # it. Same failure vocabulary the host uses for a malformed
        # *response*, so both directions speak one protocol.
        print(proto.dumps_response(
            "failed",
            failures=[{"stage": "search", "code": "protocol_error",
                      "retryable": False}]))
        return 0

    print(proto.dumps_response(
        "unavailable",
        failures=[{"stage": "search", "code": "not_available_yet",
                  "retryable": False}]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
