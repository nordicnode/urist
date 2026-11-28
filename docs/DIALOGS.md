# DF Agent Harness — Dialog handling

Mikey's directive (2026-11-26): "There MUST be a way to properly
handle dialogs. This is a roadblock, not a hard blocker. Figure it
out." He rejected both the keystroke exception and flagging dialogs
as a limitation. So there are no keystrokes for game actions and no
punting: a modal is handled programmatically or it is named as a
failure.

## The programmatic route (proven live 2026-11-26)

DFHack's Lua API (0.47.05-r6 docs):

- `dfhack.screen.dismiss(screen[,to_first])` — "Marks the screen to
  be removed when the game enters its event loop. If `to_first` is
  true, all screens up to the first one will be deleted."
- `dfhack.screen.isDismissed(screen)` — "Checks if the screen is
  already marked for removal."
- `dfhack.gui.getCurViewscreen([skip_dismissed])` — topmost
  viewscreen. `dfhack.gui.getCurFocus([skip_dismissed])` — its focus
  string. `dfhack.gui.getViewscreenByType(type[, depth])` and
  `dfhack.gui.getDFViewscreen(...)` — find a screen by type / the
  topmost non-DFHack screen.

Proven live on a native `viewscreen_textviewerst`:

1. Created and showed it (`dfhack.screen.show` returned true); focus
   changed to `textviewer`.
2. `dfhack.screen.dismiss(vs)`; `isDismissed` returned true.
3. After the game entered its event loop (a short unpause-and-
   repause), the stack came back clean: topmost screen
   `viewscreen_dwarfmodest`, focus `dwarfmode/Default`, no
   textviewer in the parent chain.

The removal happens when the game enters its event loop, so a
dismiss is always followed by a short unpause-and-repause to let it
take effect, then the focus is re-read to verify the screen is gone.

## Detection

`dialogs.is_blocking(client)`: reads the focus string and the game
tick, waits ~2 s with the game unpaused, reads the tick again. A
modal is blocking when the focus is not a playable screen AND the
tick did not advance. The game is left in the pause state it was
found in. The focus probe reads GUI state only (safe while running);
the tick reads are paused collects (read safety).

## The advance check

`dialogs.advance(client, max_rounds=5, wait_s=2.0)` — the harness
equivalent of dfkit's `advance`. While time is not moving, check the
current viewscreen; if a blocking screen is present, dismiss it
programmatically (per the allowlist) and re-check. Returns a dict:
`ok`, `cleared` (one audit dict per screen dismissed, with
focus_before / focus_after / dismissed / removed), `blocked_by`
(the focus string that could not be cleared, or None), `reason`.
A blocking screen that cannot be cleared is NAMED in a zero-tick
failure instead of timing out quietly.

Wired in:

- **Daemon** (`daemon.py`, `_planner_tick`): when the focus is not
  `dwarfmode/Default`, the tick runs `dialogs.advance` instead of
  the old keystroke `dismiss_dialog`. Cleared screens are journalled
  as `dialog_dismissed` (with the audit); a refused screen is
  journalled as `dialog_blocked` and the tick is skipped. This
  replaces the `DIALOG_KEYS` keystroke path entirely.
- **HTTP** (`POST /v1/control/advance`): runs the advance check on
  the daemon's client and returns the result dict; cleared/refused
  screens are journalled the same way.
- **M1 driver** (`scripts/m1_driver.py`, `_advance_clock`): when the
  clock does not move during a window, the driver calls
  `POST /v1/control/advance` and logs the result, so a modal can
  never stall a run silently.

## Safety rules / allowlist

Not every modal may be dismissed. A modal whose only option is
game-committing must be NAMED and returned as a failure, never
chosen for the player. The allowlist (`dialogs.ALLOWLIST`) is built
from live evidence; anything outside it is REFUSED by default — an
unknown modal is never dismissed.

| Focus (prefix) | Dismissable | Reason |
|---|---|---|
| `textviewer` | yes | Announcement/help text; closing it commits nothing. Proven live. |
| `topicmeeting` | **no** (plain dismiss) — resolvable via `resolve_topicmeeting()` | Liaison meeting; plain `screen.dismiss` re-creates it every tick. Resolved programmatically by jumping the dipscript to its farewell step (see below). Proven live 2026-11-27; no keypress used. |
| `announcelist` | yes | Announcements list; closing it commits nothing. |
| anything else | **no** | Unknown or game-committing; named and returned as a failure. |

Verified live 2026-11-26:

- **Dismiss:** a native textviewer was shown, `advance` detected
  it as blocking, dismissed it programmatically, and the focus
  returned to `dwarfmode/Default` with the clock advancing.
  Audit: `focus_before=textviewer, focus_after=dwarfmode/Default,
  dismissed=true, removed=true`.
- **Refusal:** a trade screen (`tradegoods/NoTraders`, not in the
  allowlist) was shown; `advance` returned `ok=false`,
  `blocked_by="tradegoods/NoTraders"`, with the reason naming the
  screen and the allowlist. The screen was NOT dismissed (focus
  stayed on it until the test cleaned it up by hand).

## The meeting screen (verified live 2026-11-27)

The meeting screen is the proven blocking case: DeepSeek's dfkit
showed the live meeting screen ignored LEAVESCREEN and only closed
with its menu key, and the outpost liaison meeting left a fort at
tick 225920 for 20+ minutes. It was first written into the allowlist
as dismissable (dismiss = end the meeting with no agreement) on
the assumption that the dismiss mechanism proven on native
viewscreens would apply — the live case below proves it does NOT,
and gives the resolution that does apply instead.

**Live verification on a REAL meeting screen: DONE 2026-11-27 — and it
CORRECTS the allowlist.** The scratch fort (region5, 238-07-18) was
found frozen at tick 222278 with the outpost liaison meeting open —
screenshot showed "The Fisherdwarf Urvad Takûsthututh meets with the
outpost liaison Reg Mng..." / "Reg Mengokol: I am your liaison from
the Mountainhomes. Let's discuss your situation." The FIRST screen
was a `viewscreen_textviewerst` (focus `textviewer`); `advance`
dismissed it in one round (focus `textviewer` ->
`dwarfmode/Default`, clock advancing 222278 -> 222287). But the
meeting then re-presented as a genuine `viewscreen_topicmeetingst`
(focus `topicmeeting`) — the peek view: "There is much to share...
<Information added to Civilizations/World Info>" with the single
option "a - Finish peeking in on conversation." **That screen does
NOT dismiss.** Five live experiments, all on the same meeting:
(1) dismiss the topicmeeting child — marked dismissed, but a NEW
topicmeeting appeared (different address; the parent re-creates the
child); (2) dismiss the parent meetingst — marked dismissed, child
stayed, tick frozen; (3) dismiss child + parent together — both
marked, game ticked exactly +1, then the screen re-appeared;
(4) write `option_key_pressed = 97` ('a') on the topicmeeting —
field set (read-back 97), screen ignored it (the field is only read
inside feed(), which runs on input events, not ticks);
(5) write `popup.flags.close_screen = true` — ignored. Also
established: `feed()` cannot express the letter 'a' —
`df.interface_key` (1615 entries, enumerated numerically) has no
single-letter key (SELECT=1, LEAVESCREEN=6); letter-key menu options
are raw SDL keysyms, not interface keys. Structure found live:
stack dwarfmodest -> meetingst (parent) -> topicmeetingst (child);
`meeting_diplomat_info` (civ 68, diplomat 4275, cur_step 3, topics
[8,6,5], no agreement yet); no flaggable "peek" state in the
meeting/popup flags. **So `topicmeeting` is UNDISMISSABLE by plain
`screen.dismiss` in `dialogs.ALLOWLIST` (not dismissable as
previously written): the meeting is a scripted conversation
(dipscript) that only ends when the player makes the menu choice,
and no dismiss route can make it.**

**RESOLVED programmatically 2026-11-27 — no keypress was ever
needed.** Mikey's decision (same day): programmatic routes first,
thoroughly; the 'a' keypress only as an absolute last resort. The
route found: the dipscript itself is the state machine, and its
state is writable from Lua. The meeting's `dipscript_info` (code
`DWARF_LIAISON`, script file `data/dipscript/dwarf_liaison`) holds
5 steps: 0 textviewer (`dwarf_liaison1`, next 1), 1 topic
discussion (next 2), 2 diphistory `SHORT` (next 3), 3 topic
discussion (next 4), 4 textviewer (`dwarf_liaison_bye`,
next -1 = script end). The live meeting was at `cur_step` 3.
Writing `meeting.cur_step = 4` (the farewell step) and dismissing
the topicmeeting child + parent meetingst in one Lua call made the
next tick present the bye textviewer; `advance` dismissed it by
the proven textviewer route; the game set `cur_step` to -1 (its
own done marker), the liaison left the map, the popup vector
emptied, and the clock ran 6000+ ticks over 60 s with focus
`dwarfmode/Default` and no re-presentation. Citizens stayed 11.
The jump skips only the remaining discussion DISPLAY: by the time
the peek view is showing, the discussion steps' state effects
(topic list built, history recorded) have already happened; the
farewell text is still shown. No agreement is made (there is none
in this script) and the liaison returns next year. This is
implemented as `dialogs.resolve_topicmeeting()` (`lua/
resolve_meeting.lua`, which refuses unless the last step is a
farewell textviewer with `next_step_idx == -1`) and `advance()`
routes a blocking topicmeeting to it. The 'a' keypress Mikey
allowed as a last resort was never used — the route is fully
programmatic. Ending the peek commits NOTHING (no agreement, no
trade; the NPCs keep talking off-screen and the meeting concludes
on its own). The scratch fort, frozen at tick 222291 before the
resolution, is unblocked (tick 228925 after verification, paused).
The 07-18 backup preserves the pre-resolution state.

Two corrections to the earlier (2026-11-26) reasoning, both from
this live case:
- The liaison does NOT need a trade depot to meet: this fort has no
  depot and the liaison still arrived in autumn and opened the
  meeting. A depot is needed for TRADE, not for the meeting itself.
- A frozen clock with 0 jobs over a long watch is the signature of
  a blocking modal, not a job-creation failure: the autumn farm
  watches that showed "0 PlantSeeds jobs in 600 s" ran against this
  frozen clock. **Every watch must verify the tick advances; a
  0-job reading with a frozen tick proves nothing.** See
  docs/FARMING.md and the coordinator log (2026-11-27).

## What did NOT work (recorded so it is not retried)

- **Keystrokes** (`xdotool`, `gui.simulateInput`, RFR
  `PassKeyboardEvent`) for game actions: rejected by Mikey. The
  pause-state Space fallback is the only keypress precedent and it
  is for pause state only.
- **`force` via RPC `run_command`**: `force Diplomat` / `force
  Caravan` returned empty (no error) but inserted no timed event.
  Inserting the event directly in Lua
  (`df.timed_event:new()`, set type/season/season_ticks/entity,
  `df.global.timed_events:insert`) works and the event fires.
- **Creating a meeting viewscreen directly**: `df.meeting` is not
  exposed in the Lua API, so a meeting object cannot be constructed
  from scratch; a real meeting needs a real liaison.
- **Two RPC clients**: the daemon owns the one RPC connection. A
  second direct `DFHackClient` alongside the running daemon made DF
  crash within ~10 s of unpaused running (three "Resetting textures
  / Aborted" deaths). With the daemon stopped and a single client,
  DF ran stably for 150+ windows. Live dialog work uses one client
  at a time.

## Model presentation

This section is required by the 2026-11-27 presentation constraint
(GOAL.md, coordinator log 2026-11-27 ~17:47 PT): every new system
must state how its information reaches the model, what it costs,
and what it deliberately does not push. The snapshot stays an
index: counts, exceptions, and diffs only, about 4,700 tokens
typical, never a replacement for full state. Budgets hold (target
30K, warning 60K, compaction 100K, hard cap 140K on a 200K
window), enforced by the assembler's token accountant with its
cut order. No system bolts its own dump onto the snapshot.

### Snapshot: a blocking dialog is a failure, not a section

Dialogs reach the model as failure feedback, never as a snapshot
section. When a dialog blocks the game, the harness names the
modal and returns it as a failure (the advance check, §The
advance check): the model is told what is blocking, in plain
words, and the run does not proceed past it. When a dialog is
dismissed programmatically (the proven route, §The programmatic
route), the model is told nothing: the dismissal is harness
machinery, not game state. The meeting screen is the exception
with a rule of its own: once trade exists, a liaison meeting is
surfaced to the agent instead of auto-ended (§The meeting
screen), because a fort with a depot can use the trade
agreement. Until trade exists, the meeting is ended by the
dipscript jump, because it freezes the clock and there is
nothing to gain from it.

**Token cost.** At 7 dwarves and at 50 dwarves alike, the dialog
layer costs 0 tokens in the snapshot: there is no dialog section
to render. A blocking dialog costs one failure-feedback line
when it happens, and nothing when it does not. The cost does not
grow with population, because dialogs do not multiply with
dwarves.

### Query route: POST /v1/control/advance (live)

POST /v1/control/advance dismisses a dismissable screen through
`dfhack.screen.dismiss`, wired into the daemon and the M1 driver
clock-advance. The route returns whether the advance worked and,
when it did not, what blocks it (`blocked_by`). The model never
calls this route directly: the daemon owns the advance check.
The route exists for the driver and the operator, not for the
playing model.

### Briefing: none from this layer

Dialogs do not brief. A game-committing modal (the trade screen
is the proven case) is named and returned as a failure, never
chosen for the player. A briefing is for something the model
needs to understand right now; a modal is something the model
must not decide, and the harness says so in one line.

### Opportunities: none from this layer

Dialogs are not opportunities. A dismissable screen is
machinery; a blocking screen is a failure. Neither is a fact
about the fort the model can act on.

### What the system deliberately does NOT push, and why

- **The dialog contents.** The model never sees a dialog's
  text, options, or buttons. It sees the failure line naming
  what blocks. Showing the options would invite the model to
  choose on a screen the harness refuses to choose on.
- **Keystrokes.** The harness never pushes a keystroke to the
  model, and the model never sends one. The programmatic route
  (DFHack Lua screen dismissal) is the only dismissal. Key
  press is the absolute last resort, only after all
  programmatic routes genuinely fail, and it is never
  presented as a normal option.
- **The allowlist.** The safety rules and allowlist (§Safety
  rules / allowlist) are harness policy. The model sees the
  outcome (dismissed, or blocked with a reason), never the
  list.
