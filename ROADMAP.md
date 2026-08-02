# Roadmap

What each version of cfc added, and what's coming. **This is the front office**:
what a release does, in general terms. *Why* it was built that way is in
`CHANGELOG.md` and `HANDOVER.md`; what's still owed is in `BACKLOG.md` and
`BUGS.md`. Nothing is described twice — a fix gets one line here and its id.

Cas's document. A session may *propose* changes, it doesn't make them. Every
version ends with his note, written from use rather than from the plan, and that
note is the point of numbering this at all.

A shipped version gets its full entry. A version still ahead gets only its
number and title; the planning behind it lives in `ROADMAP_PRIVATE.md`,
gitignored, and moves over here the day it ships.

## The shape of an entry, from v1.1

**Everything up to and including v1.0 is in an older, longer shape and stays
that way** — those entries record what was true when they were written, and
restyling them would destroy the one property they have. From v1.1:

```markdown
## vX.Y — Title — YYYY-MM-DD

Two or three sentences: what this version added, and what you can do now that
you couldn't before.

**Added**
- one line per feature

**Fixed**
- one line per fix, patch-note style, carrying its tracker id (D-10)

> *Note: Cas's, from use.*
```

A fix is **one line**. It is already described in `legacy/BUGS.md`, closed in
`CHANGELOG.md` with its reasoning, and indexed in `TRACKER.md`; the id is how a
reader reaches all three. The note stays at the bottom, where it reads as the
signature on a release rather than a preamble to one.

## What "feature complete" means here

**`BUGS.md` is empty.** Every claim made up to and including that version does
what it says. `BACKLOG.md` does *not* have to be empty — that file is, by its
own definition, things that still work and are merely owed.

It's a line in the sand rather than a promise to stop adding features. cfc has
shipped features that weren't fully functional as intended; a feature-complete
version is where that stops being true. Two are planned: **v1.0**, minimal cfc,
and **v1.9**, cfc as wanted. **v2.0** rebuilds on what the first two taught.

Past v1.0 the arc is planned but not committed to numbers, so it isn't stubbed
here yet.

## The vault is a separate project

The Obsidian vault cfc reads and writes has its own repo and its own roadmap.
The seam: **cfc ships the mechanism, the vault ships the words** — safe code
defaults, gate text and chat mechanics here; templates, structure and
walkthrough material there. The two are not worked on equally. When a version
lines up with something on the vault side, its note says so.

---

**Everything through v1.0 is archived in [`legacy/ROADMAP.md`](legacy/ROADMAP.md)**
— frozen at the tag, in the older per-version shape those entries were written
in. From here down is the shape described above.

---

## v1.1 - Name it, don't count it *completed, 30/07*
Three commands close three pieces of workflow that were number-only or manual.
You can file a proposal by typing its title instead of counting rows, walk one
loose outbox file to a folder you pick, and archive the notes inbox in one
confirmed batch instead of deleting notes by hand.

**Added**
- `/file <title>` — file a proposal by its exact frontmatter title, no quotes
  needed (W-05)
- `/move` — guide one loose top-level outbox file to a destination you choose,
  with a verified-replace guard on collisions (W-05)
- `/clear notes` — archive the notes inbox into a dated batch folder (D-02)
- a Notes inbox row on `/status`, from the same inventory `/clear notes` uses

**Fixed**
- `/status`'s "Last turn" no longer renders in the same grey as an inactive
  setting (W-0.9.1-09)
- `/list outbox` puts the corpus tag first, so a proposal's title is the last
  thing on its line and can be pasted straight into `/file` (W-1.1-07)

**Settled**
- cfc stays local-only. Off-machine backup is optional and yours to run:
  `backup.py --force`, then copy the snapshot by hand (Q-01)

> *Note: users should be able to choose how to interact with the vault, added options to make it easier from cfc*
```
      'welcome to'    <(✦) 'your tag was late'
˶^•ﻌ•^˵ the team!      (\ \_
                       \\//
                     --" "---
```
## v1.1.1 - A hiccup is not a rejection *completed, 30/07*
The v1.1 playtest patch. A model you just switched to now survives a provider
hiccup on its first turn instead of being switched back out from under you, and
you can pick a model by the number the list already prints.

**Added**
- `/model <n>` — switch by the number `/list models` shows, no picker
  (W-1.1-10)

**Fixed**
- a transient provider error on the first turn after `/model` no longer reverts
  the switch; only a real rejection does. 504 joins the retryable statuses
  (W-1.1-03, D-1.1-05)
- the hub's Routines panel lists seven, so a routine no longer falls off it
  unseen (W-1.1-04)
- `/clear notes` names the inbox and archive it moves between, and its
  confirmation no longer reads as one more filename (D-1.1-08)
- retired `:` command spellings gone from source comments, and from the two
  lines that printed them at you (D-1.1-09, B-03)
- three files describing the pre-v1.0 auto-revert scope corrected (D-12)

> *Note: small update: a few fixes and a easier time switching models.*
```
 /\_/\ 'so, that was NOT a rejection?'
( 0_o )
==_~_==
 /___\
```
## v1.2 - Screens that aren't chat *completed, 31/07*
The wiki and routines each get a command centre instead of a chat window doing
double duty. `/wiki` reviews and acts on vault diffs, `/routine` manages
routines with their run history, and `/config` gathers connection, model and
path settings in one place — none of them ever hand a stray line to a model.

**Added**
- `/wiki` — a wiki management screen: inspect, review and act on diffs, generous
  about phrasing so a typo doesn't read as a broken feature
- `/routine` — a routine screen with an overview and run history; opening a run
  as a chat picks up the conversation where it stopped
- the routine view redesigned: `routine`/`model`/`trigger`/`write`/`loop`/`flag`/
  `last run`, ordered so the `flag` column alone tells you whether to read
  further
- `/config` — connection, model picker and paths gathered on one screen

**Fixed**
- the wiki screen no longer prints a chat command it then refuses to run
  (B-1.2-01)

> *Note: New screens! Where you can make mistakes that don't mess up your chat!*
```
 \    /\ 'show me the screens!'
  )  ( ')
 (  /  )
  \(__)| 
```
## v1.2.1 - 1.2 bug patch *completed, 31/07*
Three small fixes
- a revert no longer lands on a rejected model
- improved /model <n> 
- clarified user messages

> *Note: added even more room for mistakes!*
```
₍^. .^₎⟆ 'more mistakes!'
```

## v1.3 - The hidden turn *completed, 31/07*

cfc can now put something in front of the model that you didn't type and that
never becomes a line in the conversation. A chat can open with the model
already speaking, you can ask it to keep going, you can direct it mid-scene
without breaking the scene, and an active trait stops fading out of a long
history. All five are one mechanism wearing five triggers, and a dim
`cfc -> …` line says which one fired.

**Added**
- **First Message** — a persona can carry a prewritten opening, one `.md` per
  persona, frozen onto the session the first time it opens
- **`/continue`** — ask the model to keep going from its own last answer, with
  no user turn of your own
- **`((OOC))`** — a whole line in double parentheses is a direction, not
  dialogue
- **Trait refresh** — an active trait is re-stated to the model every few turns
  instead of being left to fade
- **A tone cue on every ordinary turn** — the model is told how your message
  reads before it answers

**Fixed**
- `run` from the routines screen uses the chat's model, like `/routine` does (B-05)
- a routine says when it starts, and that Ctrl-C cancels it; a cancelled run is
  no longer logged as a failure or counted against a weekly slot (W-0.9.1-06)
- the picker's `Msgs` column is `Messages`, and counts a First Message (W-0.9.1-02)
- `/connect embed` is accepted alongside `embedder` and `embeddings` (W-0.9.1-08)
- an unknown `/connect` target says "connection", not "connect target" (W-1.1.1-01)
- every command screen says `help` exists on the way in (W-1.2.1-02)
- the `/tools` golden fixture no longer bakes real tool roots into the baseline (D-11)

> *Note: the turn that is so hidden, that this update announces a working feature that can't be found*
```
 __
( o> 'the cat is preparing v1.3.1'
///\
\V_/_
```


## v1.3.1 — First Message visibility — *completed, 31/07*

A light patch. A First Message now has somewhere to be seen, the export
destination has a name that says what it is rather than one that looks like the
vault, and two commands that were called hand-verified stopped being.

**Added**
- **`/status` names the First Message state** — ready, none for this persona,
  not configured, or unavailable with the reason, and only when a persona is
  attached (W-09)

**Fixed**
- `CHAT_EXPORT_DIR` replaces `VAULT_PATH` as the export-destination key; an
  existing config keeps working unchanged (W-0.9.1-01)
- `/export` and `/routine`'s listing are covered by tests rather than by hand,
  and the docs that said otherwise are corrected (W-02)

> *Note: the hidden is unhidden!*
```
𐔌˙. 'visible.'
```

## v1.4 — The third chat *completed, 01/08*

cfc now has a durable Main chat for the vault: one fixed profile, one frozen
opening, and live persona and system-prompt files read again on each turn. The
selected model is process-wide, so changing chats no longer changes what
"selected" means.

**Added**
- **`m` — Main chat**, one durable vault-manager session with ordinary chat
  history and the existing chat commands around it
- a process-wide model selection carried through chats, private sessions and
  command screens (W-1.3.1-03)

**Fixed**
- `/model` immediately explains when the new model cannot use tools
  (W-1.3.1-01)
- unreachable hosted embedders now give actionable connection advice
  (W-0.9.1-05)
- `/add <path>` attaches files in Main chat instead of applying Main's fixed
  profile refusal (B-1.4-01)

> *Note: a third way to chat with your AI, it writes to your chat db (not private) and is more rigid than regular chat. A work in progress.*
```
    /\_/\     'a turd chat?'
 _\/ o o \/_______
  /\__^__/\     _ \
      \ _/ ___ (  \ \
       (__/  (__ /  \|
```

## v1.4.1 — Main chat follow-through *completed, 01/08*

A turn now ends honestly: cfc says it is still working instead of looking
ready, and everything it does after an answer happens before it offers you
the next line. A failed title is a real failure with a place to read about
it, terminal text is finally literal, and there is one checked document
saying every way cfc puts words in front of the model.

**Added**
- `SYSTEM_INJECTIONS.md` — every system-layer injection seam, checked against
  the source by a test rather than maintained by hand (W-1.4-05)
- `finishing turn` — a visible busy state covering titling and indexing

**Fixed**
- typing during the silent post-turn window no longer sends a line you never
  wrote (B-1.3.1-02)
- a failed title call is visible, logged, and never handed to a later turn
  (D-13)
- a chat whose first turn hit a provider error can still be titled (B-07)
- `:key:`-shaped text in a chat is no longer rewritten as an emoji (B-06)
- the routines screen names a routine, not its slug id (D-1.4-02)
- the test suite no longer writes fabricated errors into `errors.log` (B-08)

> *Note: mainly chatting, and hunting for silent failures and invisible errors *
```
=^._.^= ∫ 'make them visible, make them scream!'
```

## v1.5.1 — Say the true thing *completed, 02/08*

A patch about honesty rather than features. The hub stops answering a question
you didn't ask with a colour, a routine run stops borrowing a chat's identity,
a run's elapsed time stops counting the hours your machine was asleep, and the
two words that overclaimed — the product's name and "private" — now say what
they mean.

**Fixed**
- the hub's Routines panel splits into `Last run`, `Result` and `Schedule`, so a
  routine that spent its retry budget on failures can no longer read green in
  the column you check first (W-0.9.2-02)
- a run's logged elapsed time measures the time it was actually running, so a
  machine suspend no longer turns a three-second call into 10,148 seconds
  (W-0.9.2-01)
- a routine run has its own reference, `<routine>/<run number>` — `history`, a
  finished `/routine`, the routines screen's help and `open` all use it, and no
  routine surface calls a transcript a chat session (W-0.9.1-07)
- the application calls itself Cooking for Cats where it speaks to you, and
  `cfc` only where it's an identifier — a test derives the list and fails on a
  new one (W-0.9.1-03)
- a private chat's own notice says what "private" covers and what it doesn't:
  nothing written locally, and your messages still reach the chat provider
  (W-0.9.1-04)

> *Note: some fixes and changes to make things easier to understand*
```
 /\___/\
꒰ ˶• ༝ - ˶꒱ 'MOAR FIXES!'
./づᡕᠵ᠊ᡃ࡚ࠢ࠘ ⸝່ࠡࠣ᠊߯᠆ࠣ࠘ᡁࠣ࠘᠊᠊°.~♡︎
```

> *Note: the most useful new features so far: turn the tide against the 503's*
```
(ง •̀_•́)ง 'take that!'
```
## v1.5 — Conversation control *completed, 01/08*

An answer you didn't like is no longer something you have to live with. You can
ask for a different one, take your own message back and try a different turn,
or change how adventurous the model is before you do either. Chats also stop
choosing their own numbers: you pick the id, and you can delete one from the
hub instead of from inside it.

**Added**
- `/swipe` — a different answer to the message you already sent, same
  everything else
- `/undo` — take back your last message and the answer it caused
- `/preset <name>` — named sampling profiles (temperature, top_p), configured
  per model and only ever sent to one that accepts them
- `c` at the hub and `/new <id>` — create a chat at an id you choose; a taken
  id refuses and never replaces (W-1.3-03)
- `d` at the hub and `/delete chat [<id>|main]` — delete a chat from either
  side, on one confirmation and one index-clean deletion (W-1.3-02, W-1.4-03)
- the chat-start tips rewritten around the commands that now exist
  (W-1.3.1-05)

**Fixed**
- `config.example.py` said `preset_params` takes preset names; it takes
  parameter names, and following it stopped cfc launching (B-1.5-02)

## v1.5.2 — Fail out loud — 2026-08-02
Adding more information only helps if it agrees on what is true, and if it points out where something might me wrong.

**Added**
- The routines screen shows each routine's scheduler state in a `Schedule`
  column, so `/config` saying something is due now leads somewhere
  (`D-1.5.1-01c`)

**Fixed**
- A scheduled tick no longer dies with `database is locked` while a chat is
  open — an ordinary database open takes no write lock at all (`B-1.5.1-01a`)
- A routine that did its work always leaves a run-log line, even when saving
  its transcript fails, and one routine's failure no longer ends the tick for
  the rest (`B-1.5.1-01b`)
- The NULL-kind migration commits the write it makes, instead of handing back
  a connection holding an open transaction forever (`B-09`)

> *Note: trying to keep the issue-tracker emptry; we add, we take away*
```
        /\_/\  'failing loudly, silently: is this a text based app or what?'
   ____/ o o \
 /~____  =ø= /
(______)__m_m)
```

## v1.6 — What the model sees — 2026-08-02

The vault can be partitioned into named scopes, and a hidden one is hidden the
same way everywhere a model could reach it — file tools, recall, and the
commands that read the wiki corpus. Files with a frontmatter title now show
that title next to the filename in every picker cfc owns, and `{{user}}` /
`{{AI}}` in cfc's own shared markdown are replaced with names you configure.

**Added**
- Named vault scopes: `VAULT_SCOPES` in `config.py` marks vault folders exposed
  or hidden. No setting keeps today's fully-open behaviour.
- A hidden folder is refused to file tools, omitted from listings and tree
  grep, refused to `/add`, never offered by tab completion, and refused to
  `/recall`, `/remember`, and the wiki re-import half of `/update db`.
- `/config` counts declared scopes; its `scopes` action shows each name, state,
  and resolved path, including valid scopes when the declaration has a problem.
- Frontmatter titles appear beside filenames in cfc's attach, status, outbox,
  filing, move, and wiki changed-file pickers. The path remains what is typed,
  inserted, and stored.
- `USER_DISPLAY_NAME` and `AI_DISPLAY_NAME` fill `{{user}}` and `{{AI}}` in
  prompts, personas, traits, First Messages, and routine task prompts.

**Fixed**
- A routine's failed transcript marker no longer leaves a stale transaction
  for the next save to commit (`D-16`).

> *Note: more freedom and more restriction and all still contained to the vault, for now*
```
≽ ^⎚ ˕ ⎚^ ≼ 'All in all, it's just another brick in the wall'
```
