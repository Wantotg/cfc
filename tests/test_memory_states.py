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
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import embed
import import_wiki
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


def test_missing_id_wiki_warning_names_files():
    """B-1.6.2-01a: a missing-id skip is diagnostic, not just a count.

    Two top-level pages with no frontmatter `id` sit beside one eligible page
    in a real temp wiki directory. Driven through the real `import_wiki` and
    `commands.do_updatedb`, not a stub, so the producer (`_import_pages`) and
    the parser (`do_updatedb`'s renderer) are proven against each other: one
    yellow warning names both filenames, the eligible page still imports, and
    the continuing chat-index pass still runs — a missing id is evidence, not
    a partial-import failure.
    """
    print("a missing-id skip names every skipped file in one warning")
    import commands
    import db as dbmod
    import vault

    vroot = Path(tempfile.mkdtemp(prefix="vault-root-"))
    wiki_dir = vroot / "wiki db"
    wiki_dir.mkdir(parents=True)

    (wiki_dir / "no-id-b.md").write_text(
        "---\ntitle: No Id B\n---\nSome body text.\n", encoding="utf-8")
    (wiki_dir / "no-id-a.md").write_text(
        "---\ntitle: No Id A\n---\nSome other body text.\n", encoding="utf-8")
    (wiki_dir / "eligible.md").write_text(
        "---\nid: 20260101000000\ntitle: Eligible Page\n---\n"
        "This page has an id and real content.\n", encoding="utf-8")

    db_path = vroot / "chat.db"
    saved_db_path_mod, saved_db_path_cmd = dbmod.DB_PATH, commands.DB_PATH
    dbmod.DB_PATH = commands.DB_PATH = db_path

    saved_wiki_dir = getattr(commands._config, "WIKI_DIR", "")
    saved_root, saved_scopes = vault.VAULT_ROOT, vault.VAULT_SCOPES
    commands._config.WIKI_DIR = str(wiki_dir)
    vault.VAULT_ROOT = str(vroot)
    vault.VAULT_SCOPES = ()   # exposed: nothing declared hides it

    import backfill
    real_update_index = backfill.update_index
    calls = {}

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
        commands._config.WIKI_DIR = saved_wiki_dir
        vault.VAULT_ROOT, vault.VAULT_SCOPES = saved_root, saved_scopes
        dbmod.DB_PATH, commands.DB_PATH = saved_db_path_mod, saved_db_path_cmd

    notice = buf.getvalue()
    check("the warning names the count", "2 wiki file(s) had no id" in notice, True)
    check("...and both deterministic filenames, in one warning",
          "no-id-a.md" in notice and "no-id-b.md" in notice
          and notice.count("had no id") == 1, True)
    check("the eligible page still imports",
          "+1 new page(s)" in notice, True)
    check("...and the continuing chat-index pass still runs",
          "index" in calls, True)

    db = sqlite3.connect(db_path)
    row = db.execute(
        "SELECT title FROM sessions WHERE provider='wiki' AND source_uuid=?",
        ("20260101000000",)).fetchone()
    db.close()
    check("the eligible page's row is really there, not just counted",
          row is not None and row[0] == "Eligible Page", True)


def test_resolve_wiki_source():
    """W-1.9-01c: `import_wiki.resolve_wiki_source` — where a wiki session's
    frontmatter id currently lives, at the same top-level `*.md` boundary
    `_import_pages` reads. Direct coverage of the resolver itself; the wiring
    that threads its result through a real session's opening notice and
    bare `/status` is `test_turn_paths.py`'s job, driven end to end.

    A fifth kind of nothing, alongside the three this file is named for:
    'no page has this id any more' and 'the directory can't be read' must
    stay distinguishable, for the same reason `why_empty` splits an empty
    index from a real miss — a resolver that quietly reports the wrong one
    of the two turns an unreadable WIKI_DIR into a confident 'page deleted'.
    """
    print("resolve_wiki_source: found, missing, duplicate, unavailable, "
          "top-level-only")

    def page(path, wid, title="T"):
        path.write_text(f"---\nid: {wid}\ntitle: {title}\n---\nbody\n",
                        encoding="utf-8")

    vroot = Path(tempfile.mkdtemp(prefix="wiki-source-"))
    page(vroot / "renamed-now.md", "111")
    page(vroot / "other.md", "222")
    dup_a, dup_b = vroot / "dup-a.md", vroot / "dup-b.md"
    page(dup_a, "333")
    page(dup_b, "333")
    # A page one level down shares an id with nothing at the top level — the
    # importer never reads it either (only *.md directly under wiki_dir).
    sub = vroot / "sources"
    sub.mkdir()
    page(sub / "buried.md", "444")

    check("a page found under a different name than it was imported under "
          "still resolves — identity survives a rename",
          import_wiki.resolve_wiki_source("111", str(vroot)),
          import_wiki.WikiSource(import_wiki.WS_FOUND, "renamed-now.md",
                                 None, None))
    check("an id with no page anywhere reports missing",
          import_wiki.resolve_wiki_source("999", str(vroot)).status,
          import_wiki.WS_MISSING)

    dup = import_wiki.resolve_wiki_source("333", str(vroot))
    check("two pages sharing an id report duplicate", dup.status,
          import_wiki.WS_DUPLICATE)
    check("...naming both, sorted, never picking one",
          dup.filenames, ["dup-a.md", "dup-b.md"])

    check("a page that only exists one level down (sources/) is out of "
          "scope, same as import — reports missing, not found",
          import_wiki.resolve_wiki_source("444", str(vroot)).status,
          import_wiki.WS_MISSING)

    check("an unconfigured directory (falsy) is unavailable, not missing",
          import_wiki.resolve_wiki_source("111", "").status,
          import_wiki.WS_UNAVAILABLE)
    check("a directory that doesn't exist is unavailable",
          import_wiki.resolve_wiki_source(
              "111", str(vroot / "nowhere")).status,
          import_wiki.WS_UNAVAILABLE)

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("  skip  unreadable-directory case (running as root)")
    else:
        unreadable = Path(tempfile.mkdtemp(prefix="wiki-unreadable-"))
        page(unreadable / "a.md", "111")
        os.chmod(unreadable, 0o000)
        try:
            # glob.glob degrades a permission error to an empty result
            # rather than raising it — indistinguishable from "nothing has
            # this id" unless checked for, which is exactly the false
            # WS_MISSING this guards against.
            check("an unreadable directory is unavailable, not a false "
                  "missing",
                  import_wiki.resolve_wiki_source(
                      "111", str(unreadable)).status,
                  import_wiki.WS_UNAVAILABLE)
        finally:
            os.chmod(unreadable, 0o755)


if __name__ == "__main__":
    test_exception_types()
    test_branches_on_type_not_text()
    test_why_empty()
    test_recall_returns_none_not_a_sentence()
    test_wiki_scope_gating()
    test_missing_id_wiki_warning_names_files()
    test_resolve_wiki_source()
    print("\nall memory-state tests passed")
