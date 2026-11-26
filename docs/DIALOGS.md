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
| `topicmeeting` | yes | Liaison meeting; closing ends the meeting with no agreement — the same as leaving. |
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

## The meeting screen (status 2026-11-26)

The meeting screen (`viewscreen_topicmeetingst`) is the proven
blocking case: DeepSeek's dfkit showed the live meeting screen
ignored LEAVESCREEN and only closed with its menu key, and the
outpost liaison meeting left a fort at tick 225920 for 20+ minutes.
It is in the allowlist (dismiss = end the meeting with no
agreement), and the dismiss mechanism is proven on native
viewscreens, so the same `dfhack.screen.dismiss` call applies.

Live verification on a REAL meeting screen is still pending, because
no liaison could be produced: the fort has no trade depot, and a
forced Diplomat event (inserted directly into `timed_events` — the
`force` command via RPC silently failed to insert it) fired but no
diplomat appeared on the map and no meeting screen ever showed
(~43,000 ticks watched). The liaison needs a trade depot to meet
at; the harness has no depot-build action yet (that is a separate
gap, not a dialog gap). Once a depot exists, force a Diplomat, watch
for the `topicmeeting` focus, and run `advance` — the mechanism is
already in place.

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
