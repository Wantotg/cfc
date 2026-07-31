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

## v1.1 - Name it, don't count it **completed, 30/07**
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
## v1.1.1 - A hiccup is not a rejection **completed, 30/07**
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
## v1.2 - Screens that aren't chat **completed, 31/07**
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
## v1.2.1 - 1.2 bug patch **completed, 31/07**
Three small fixes
- a revert no longer lands on a rejected model
- improved /model <n> 
- clarified user messages

> *Note: added even more room for mistakes!*
```
₍^. .^₎⟆ 'more mistakes!'
```

## v1.3 - The hidden turn **completed, 31/07**

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


## v1.3.1 — First Message visibility — **completed, 31/07**

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
