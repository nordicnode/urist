"""Dialog handling: detect a blocking modal, dismiss it programmatically.

Mikey's directive (2026-11-26): "There MUST be a way to properly
handle dialogs. This is a roadblock, not a hard blocker. Figure it
out." He rejected both the keystroke exception and flagging dialogs
as a limitation. So: no keystrokes (xdotool, gui.simulateInput, RFR
PassKeyboardEvent) for game actions — the pause-state Space fallback
is the only keypress precedent and it is for pause state only — and
no punting.

The programmatic route (proven live 2026-11-26):
``dfhack.screen.dismiss(screen)`` marks a viewscreen to be removed
when the game enters its event loop (DFHack Lua API, 0.47.05-r6),
and ``dfhack.screen.isDismissed(screen)`` verifies the mark.
Proven on a native ``viewscreen_textviewerst``: shown, focus changed
to ``textviewer``, dismissed (``isDismissed`` true), and the stack
came back clean (``viewscreen_dwarfmodest`` on top, focus
``dwarfmode/Default``) after the game ticked. The removal happens
when the game enters its event loop, so a dismiss is followed by a
short unpause-and-repause to let it take effect.

Detection: ``dfhack.gui.getCurFocus()`` gives the current focus
string; a modal is blocking when the focus is not the dwarfmode
screen AND the game clock (``year_tick``) is not advancing while the
game is unpaused. The daemon's focus probe already reads GUI state
only (safe while running); the clock check needs two tick reads
around a short wait.

Safety: not every modal may be dismissed. A modal whose only option
is game-committing must be NAMED and returned as a failure, never
chosen for the player. The allowlist below is built from live
evidence; anything outside it is refused.
"""

from __future__ import annotations

import time
from typing import Any

from dfhack_rpc import DFHackClient

# -- allowlist -----------------------------------------------------------
# Focus string (prefix match) -> (dismissable, reason). A focus is
# matched by prefix so sub-screens (e.g. topicmeeting_takerequests)
# inherit the parent's classification.
#
# Dismissable = ending the screen without choosing anything is safe:
# it declines to engage, it does not commit the game to anything.
#   textviewer: an announcement / help text. Dismissing closes it.
#     Proven live 2026-11-26 (dfhack.screen.dismiss).
#   topicmeeting: the outpost liaison meeting. Dismissing ends the
#     meeting without an agreement — the same as leaving. The live
#     meeting screen ignored LEAVESCREEN and only closed with its
#     menu key (DeepSeek's dfkit, 2026-11-25), which is why the
#     programmatic route matters. Dismiss on a real meeting screen
#     is verified separately (see DIALOGS.md).
#   announcelist: the announcements list. Dismissing closes it.
# Game-committing = refusing to dismiss; the caller names the screen
# and returns it as a failure. These are screens where closing
# without choosing would either commit the game or lose state.
#   (Populated as screens are encountered live; anything not in this
#   table is REFUSED by default — an unknown modal is never dismissed.)
ALLOWLIST: dict[str, tuple[bool, str]] = {
    "textviewer": (True, "announcement/help text; closing it commits nothing"),
    "topicmeeting": (True, "liaison meeting; closing ends the meeting with no agreement"),
    "announcelist": (True, "announcements list; closing it commits nothing"),
}

# Focus strings that are NOT modals at all (the game is playable).
NON_MODAL_PREFIXES = (
    "dwarfmode/",
    "title",
    "loadgame",
    "movieplayer",
)


def classify_focus(focus: str | None) -> tuple[str, bool, str]:
    """Classify a focus string.

    Returns (kind, dismissable, reason) where kind is one of
    "non_modal", "dismissable", "committing", "unknown".
    """
    if not focus:
        return ("unknown", False, "no focus string")
    for prefix in NON_MODAL_PREFIXES:
        if focus.startswith(prefix):
            return ("non_modal", False, "playable screen")
    for prefix, (ok, reason) in ALLOWLIST.items():
        if focus.startswith(prefix):
            return ("dismissable" if ok else "committing", ok, reason)
    return ("unknown", False, f"focus {focus!r} is not in the dialog allowlist")


def current_focus(client: DFHackClient) -> str | None:
    """Read the current focus string (GUI state only, safe while running)."""
    from .ui import get_focus

    probe = get_focus(client, timeout=10.0)
    return probe.get("focus") if probe.get("ok") else None


def is_blocking(client: DFHackClient, *, wait_s: float = 2.0) -> dict[str, Any]:
    """Is a modal blocking the clock?

    Reads the focus and the game tick, waits ``wait_s`` seconds with
    the game unpaused, and reads the tick again. A modal is blocking
    when the focus is not a playable screen AND the tick did not
    advance. Returns a dict with focus, classification, tick_before,
    tick_after, and blocked (bool). The game is left in the pause
    state it was found in.
    """
    from .actions import get_paused, set_paused
    from .observe import collect
    from .read_safety import paused_read

    focus = current_focus(client)
    kind, dismissable, reason = classify_focus(focus)
    if kind == "non_modal":
        return {"focus": focus, "kind": kind, "dismissable": False,
                "reason": reason, "blocked": False}
    was_paused = get_paused(client)
    # Tick before: a paused collect is the ground truth.
    before = paused_read(client, lambda: collect(client, sections=("status",)))
    tick_before = ((before.get("status") or {}).get("year_tick"))
    if was_paused:
        set_paused(client, False)
    time.sleep(wait_s)
    # Tick after: pause again first (a read while running is unsafe),
    # then collect. The pause also restores the entry state.
    set_paused(client, True)
    after = paused_read(client, lambda: collect(client, sections=("status",)))
    tick_after = ((after.get("status") or {}).get("year_tick"))
    if not was_paused:
        set_paused(client, False)
    blocked = (tick_before is not None and tick_after is not None
               and tick_after <= tick_before)
    return {"focus": focus, "kind": kind, "dismissable": dismissable,
            "reason": reason, "tick_before": tick_before,
            "tick_after": tick_after, "blocked": blocked}


def dismiss_current(client: DFHackClient) -> dict[str, Any]:
    """Dismiss the current viewscreen programmatically.

    Uses ``dfhack.screen.dismiss`` on the topmost viewscreen, verifies
    with ``isDismissed``, then lets the game enter its event loop
    (a short unpause-and-repause) so the removal takes effect, and
    re-reads the focus. Returns an audit dict: focus_before,
    focus_after, dismissed (bool), and the screen that was cleared.
    Raises on a transport failure; returns dismissed False (not an
    exception) when the screen refuses the dismiss mark.
    """
    from pathlib import Path

    from .actions import get_paused, set_paused

    focus_before = current_focus(client)
    lua_dir = Path(__file__).resolve().parent / "lua"
    prelude = (lua_dir / "json.lua").read_text()
    code = prelude + """
local vs = dfhack.gui.getCurViewscreen()
local out = {}
out.vs = vs and tostring(vs) or "nil"
if vs then
  dfhack.screen.dismiss(vs)
  out.is_dismissed = dfhack.screen.isDismissed(vs)
else
  out.is_dismissed = false
end
dfh_print(out)
"""
    result = client.run_lua_json(code, timeout=15.0)
    dismissed = bool(result.get("is_dismissed"))
    # The removal happens when the game enters its event loop.
    was_paused = get_paused(client)
    if was_paused:
        set_paused(client, False)
        time.sleep(1.0)
        set_paused(client, True)
    time.sleep(0.5)
    focus_after = current_focus(client)
    return {"focus_before": focus_before, "focus_after": focus_after,
            "dismissed": dismissed, "screen": result.get("vs"),
            "removed": focus_after != focus_before}


def advance(client: DFHackClient, *, max_rounds: int = 5,
            wait_s: float = 2.0) -> dict[str, Any]:
    """The harness ``advance`` check (dfkit's ``advance`` equivalent).

    While time is not moving, check the current viewscreen; if a
    blocking screen is present, dismiss it programmatically (per the
    allowlist) and re-check. Names the last blocking screen in a
    zero-tick failure instead of timing out quietly.

    Returns a dict: ok (bool), cleared (list of audit dicts, one per
    screen dismissed), blocked_by (the focus string that could not be
    cleared, or None), reason. ``ok`` is False when a blocking screen
    is game-committing or unknown (refused) or when a dismiss did not
    remove the screen within ``max_rounds`` rounds.
    """
    cleared: list[dict[str, Any]] = []
    for _ in range(max_rounds):
        check = is_blocking(client, wait_s=wait_s)
        if not check.get("blocked"):
            return {"ok": True, "cleared": cleared, "blocked_by": None,
                    "reason": "clock advancing; no blocking modal"}
        focus = check.get("focus")
        kind = check.get("kind")
        if kind != "dismissable":
            return {"ok": False, "cleared": cleared, "blocked_by": focus,
                    "reason": (f"blocking modal {focus!r} is {kind} "
                               f"({check.get('reason')}); refusing to "
                               f"dismiss — returning as a failure")}
        audit = dismiss_current(client)
        audit["focus"] = focus
        cleared.append(audit)
        if not audit.get("dismissed") or not audit.get("removed"):
            return {"ok": False, "cleared": cleared, "blocked_by": focus,
                    "reason": (f"dismiss of {focus!r} did not remove "
                               f"the screen (dismissed="
                               f"{audit.get('dismissed')}, removed="
                               f"{audit.get('removed')})")}
    check = is_blocking(client, wait_s=wait_s)
    return {"ok": not check.get("blocked"), "cleared": cleared,
            "blocked_by": check.get("focus") if check.get("blocked") else None,
            "reason": ("clock still blocked after "
                       f"{max_rounds} dismiss rounds" if check.get("blocked")
                       else "clock advancing after dismiss rounds")}
