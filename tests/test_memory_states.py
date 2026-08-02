#!/usr/bin/env python3
"""test_memory_states.py — the three kinds of nothing recall can return.

Before v0.9 these collapsed into one silence:

  1. the embedder never answered — the search did not happen;
  2. nothing is indexed — there was no corpus to search;
  3. the corpus was searched and nothing came close enough.

Only (3) is "memory has no answer". The other two are a broken lookup wearing
the costume of a truthful one, which is `HANDOVER.md`'s recurring silent false
negative in the module it does the most damage in.

**The load-bearing test here is `test_branches_on_type_not_text`.** The states
are cleanly separable exactly once, at the point where one of them is an
exception, so `embed.py` records which kind of failure it saw *while it is
catching it* and raises a type. Anything that re-derives the state later by
matching words is the recurring hazard rebuilt, and it fails the day someone
improves a sentence. That test is what stops it coming back.

No network, no API key, no LM Studio.
"""
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import embed
import search


def check(label, got, want):
    assert got == want, f"{label}: got {got!r}, want {want!r}"
    print(f"  ok  {label}")


def test_exception_types():
    print("embed raises a type, not a sentence")
    # Both are RuntimeError, which is what this module raised before the types
    # existed — every `except Exception` and `except RuntimeError` in the tree
    # keeps working. The type adds a distinction; it removes none.
    check("EmbedError is a RuntimeError",
          issubclass(embed.EmbedError, RuntimeError), True)
    check("EmbedUnavailable is an EmbedError",
          issubclass(embed.EmbedUnavailable, embed.EmbedError), True)
    # ...and the distinction is real, not cosmetic: a caller can catch the
    # unreachable case without catching a 500 from a server that answered.
    check("a 500 is not an unavailability",
          isinstance(embed.EmbedError("500"), embed.EmbedUnavailable), False)


def test_branches_on_type_not_text():
    print("the caller branches on class, never on wording")
    import commands
    # An unreachable embedder, with a message that says nothing recognisable.
    # If this fails, someone has started matching on the text.
    check("typed unavailability is reported however it is worded",
          commands.embedder_down_note(embed.EmbedUnavailable("")), True)
    # The mirror, and the one that actually catches a regression: an error
    # whose *message* looks exactly like the unreachable case, but whose type
    # says otherwise. Any string-matching implementation reports this as "the
    # embedder is down" and sends the reader to /connect embedding for a
    # server that is up and returning 500s.
    liar = embed.EmbedError(
        "no connection to http://localhost:1233 — is the embedding server running?")
    check("a lookalike message is not mistaken for one",
          commands.embedder_down_note(liar), False)
    check("an unrelated exception is not claimed either",
          commands.embedder_down_note(ValueError("nope")), False)


def _db_with(chunks):
    """A throwaway db holding `chunks` rows. Never touches the real one."""
    path = Path(tempfile.mkdtemp()) / "t.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY, provider TEXT)")
    db.execute("CREATE TABLE chunks (id INTEGER PRIMARY KEY, session_id INT)")
    for i, provider in enumerate(chunks, start=1):
        db.execute("INSERT INTO sessions (id, provider) VALUES (?,?)", (i, provider))
        db.execute("INSERT INTO chunks (id, session_id) VALUES (?,?)", (i, i))
    db.commit()
    db.close()
    return str(path)


def test_why_empty():
    print("an empty index is not a failed search")
    check("no chunks at all -> empty index",
          search.why_empty(_db_with([])), search.EMPTY_INDEX)
    check("chunks exist -> a real miss",
          search.why_empty(_db_with(["wiki"])), search.NO_MATCH)
    # The case that made this worth separating by provider rather than by a
    # bare count: a db full of chat chunks answers "yes, I have content" to a
    # wiki-scoped search that had nothing to look at.
    check("chat-only corpus, wiki-scoped search -> empty index",
          search.why_empty(_db_with(["chat", "chat"]), provider="wiki"),
          search.EMPTY_INDEX)
    check("...and the same corpus is a real miss unscoped",
          search.why_empty(_db_with(["chat", "chat"])), search.NO_MATCH)
    # A db that was never indexed has no tables at all. Failing open to
    # EMPTY_INDEX sends the reader to /update db, which is harmless if wrong;
    # NO_MATCH would assert that a search happened over content that is not
    # there. Guards should fail in the direction that cannot lie.
    bare = Path(tempfile.mkdtemp()) / "bare.db"
    sqlite3.connect(bare).close()
    check("a db with no tables -> empty index",
          search.why_empty(str(bare)), search.EMPTY_INDEX)


def test_recall_returns_none_not_a_sentence():
    print("recall signals zero hits by value, not by prose")
    import recall as recall_mod
    calls = {}

    def fake_search(db_path, question, **kw):
        calls["hit"] = True
        return []

    orig = recall_mod.search
    recall_mod.search = fake_search
    try:
        answer, hits = recall_mod.recall("ignored", "anything")
    finally:
        recall_mod.search = orig
    check("search was reached", calls.get("hit"), True)
    # It used to return the string "No relevant excerpts found in memory.",
    # which the caller rendered in the answer panel exactly as if a model had
    # written it — and any code wanting to react to zero hits had to match the
    # wording. None is checkable and cannot drift.
    check("no hits -> answer is None", answer, None)
    check("no hits -> no hits", hits, [])


def test_wiki_scope_gating():
    """v1.6: /recall, /remember and /update db must not reach a hidden
    WIKI_DIR. Reports the policy state rather than letting the corpus look
    merely empty — a fourth kind of nothing, alongside the three this file
    is named for, and the same discipline: branch on an explicit signal, not
    on a message a caller re-derives."""
    print("a hidden WIKI_DIR refuses /recall, /remember and /update db "
          "without reaching search")
    import commands
    import vault

    vroot = Path(tempfile.mkdtemp(prefix="vault-root-"))
    wiki_dir = vroot / "03 resources" / "wiki db"
    wiki_dir.mkdir(parents=True)

    # Sandboxed, same discipline as every other command test: do_updatedb
    # touches the memory index for real, and without this it would run
    # against the developer's own ~/.cfc/chat.db.
    import db as dbmod
    saved_db_path_mod, saved_db_path_cmd = dbmod.DB_PATH, commands.DB_PATH
    dbmod.DB_PATH = commands.DB_PATH = vroot / "chat.db"

    saved_wiki_dir = getattr(commands._config, "WIKI_DIR", "")
    saved_root, saved_scopes = vault.VAULT_ROOT, vault.VAULT_SCOPES
    commands._config.WIKI_DIR = str(wiki_dir)
    vault.VAULT_ROOT = str(vroot)
    vault.VAULT_SCOPES = (dict(name="wiki", path="03 resources/wiki db",
                               exposed=False),)
    try:
        check("hidden: _wiki_hidden_reason names the policy, not emptiness",
              commands._wiki_hidden_reason() is not None
              and "hidden" in commands._wiki_hidden_reason(), True)

        # do_recall/do_remember each do a LOCAL `from recall import recall` /
        # `from search import search` inside their own body — a call-time
        # import, re-read fresh every call — so patching the source
        # module's attribute here is what a broken gate would actually
        # reach, unlike patching a name some other module already bound at
        # its own import time.
        calls = {}
        import recall as recall_mod
        real_recall = recall_mod.recall
        recall_mod.recall = lambda *a, **k: calls.setdefault("recall", True)
        try:
            commands.do_recall("anything")
        finally:
            recall_mod.recall = real_recall
        check("do_recall never reaches recall() while the corpus is hidden",
              "recall" not in calls, True)

        import search as search_mod
        real_search = search_mod.search
        search_mod.search = lambda *a, **k: calls.setdefault("search", True)
        try:
            commands.do_remember(None, 1, [], [], "anything")
        finally:
            search_mod.search = real_search
        check("do_remember never reaches search() while the corpus is hidden",
              "search" not in calls, True)

        real_import = None
        try:
            import import_wiki
            real_import = import_wiki.run_import
            import_wiki.run_import = lambda *a, **k: calls.setdefault(
                "import", True)
        except ImportError:
            pass
        # backfill.update_index is the continuing chat-index half (D-1.6-03):
        # mocked only so this proves it ran, without touching a real index.
        import backfill
        real_update_index = backfill.update_index

        def fake_update_index(*a, **k):
            calls["index"] = True
            return (0, 0)

        backfill.update_index = fake_update_index
        import io
        buf = io.StringIO()
        commands.console.file = buf
        try:
            commands.do_updatedb()
        finally:
            commands.console.file = sys.stdout
            backfill.update_index = real_update_index
            if real_import is not None:
                import_wiki.run_import = real_import
        notice = buf.getvalue()
        check("do_updatedb skips the wiki re-import while it is hidden",
              "import" not in calls, True)
        check("...and still calls the continuing chat index",
              "index" in calls, True)
        check("the one pre-spinner notice names the wiki skip",
              "wiki re-import skipped" in notice, True)
        check("...and names the chat index continuing",
              "chat messages will still be indexed" in notice, True)

        vault.VAULT_SCOPES = (dict(name="wiki", path="03 resources/wiki db",
                                   exposed=True),)
        check("exposed: _wiki_hidden_reason clears",
              commands._wiki_hidden_reason() is None, True)
    finally:
        commands._config.WIKI_DIR = saved_wiki_dir
        vault.VAULT_ROOT, vault.VAULT_SCOPES = saved_root, saved_scopes
        dbmod.DB_PATH, commands.DB_PATH = saved_db_path_mod, saved_db_path_cmd


if __name__ == "__main__":
    test_exception_types()
    test_branches_on_type_not_text()
    test_why_empty()
    test_recall_returns_none_not_a_sentence()
    test_wiki_scope_gating()
    print("\nall memory-state tests passed")
