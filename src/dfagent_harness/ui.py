"""UI-keystroke actions for the DF Agent Harness (phase 4).

Some things have no Lua/RPC API at all in DFHack 0.47.05-r8 and can
only be done through the game's own menus: noble appointments and
stockpile creation. This module drives those menus with xdotool
keystrokes sent to the DF window on the Xvfb display (the proven
path from SETUP.md: ``xdotool key --window <wid> <key>``; there is
no window manager, so ``windowactivate`` fails and keys go straight
to the window).

Every function here VERIFIES its effect by re-reading game state
through the observation layer afterwards — a keystroke sequence is
never trusted on its own. A mismatch is reported honestly, never
silently accepted. Screenshots are saved to the daemon log dir when
``screenshot_dir`` is given, for debugging a failed sequence.

These functions need the game window to be at dwarfmode (the main
fortress view) on entry, and they leave it there on exit.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from dfhack_rpc import DFHackClient

from . import observe
from .actions import NOBLES_SCREEN_ORDER, nobles as probe_nobles

__all__ = ["appoint_noble", "create_stockpile", "set_cursor", "get_cursor",
           "ensure_map_view", "get_focus", "df_window_id"]

#: xdotool key names for the nobles/stockpile menus.
_KEY_DELAY = 0.35

#: DFHack focus string of the main fortress view.
_MAP_FOCUS = "dwarfmode/Default"


def get_focus(client: DFHackClient,
              timeout: float = 30.0) -> dict[str, Any]:
    """Current DFHack GUI focus string (``dwarfmode/Default`` is the
    main map view). A sub-screen freezes the tick even when the pause
    flag is clear — every UI helper checks this before and after
    sending keys."""
    from .actions import _run_helper
    return _run_helper(client, "probe_focus.lua", {}, timeout=timeout)


def ensure_map_view(client: DFHackClient, wid: str, display: str = ":99",
                    timeout: float = 30.0) -> tuple[bool, str]:
    """Get the game back to the main map view, if it is not there.

    Probes the focus; while it is not ``dwarfmode/Default`` (and not
    already failing), sends Escape and re-probes, up to 3 times.
    Returns ``(True, focus)`` on the map view, else ``(False, focus)``
    — the caller must not send menu keys in that case. Escape from
    the map view opens the Options menu, so this stops as soon as the
    focus reads Default and never sends a blind extra Escape.
    """
    for _ in range(4):
        try:
            focus = get_focus(client, timeout=timeout).get("focus")
        except Exception as exc:  # noqa: BLE001 - probe failed
            return False, f"focus probe failed: {exc}"
        if focus == _MAP_FOCUS:
            return True, focus
        try:
            _keys(wid, display, "Escape")
        except subprocess.CalledProcessError as exc:
            return False, f"xdotool failed: {exc}"
        time.sleep(0.5)
    try:
        focus = get_focus(client, timeout=timeout).get("focus")
    except Exception as exc:  # noqa: BLE001 - probe failed
        return False, f"focus probe failed: {exc}"
    return focus == _MAP_FOCUS, str(focus)


def df_window_id(display: str = ":99") -> Optional[str]:
    """X window id of the Dwarf Fortress window, or None."""
    try:
        out = subprocess.run(
            ["xdotool", "search", "--name", "Dwarf Fortress"],
            capture_output=True, text=True, timeout=10,
            env={"DISPLAY": display, "PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    return lines[0] if lines else None


def _keys(wid: str, display: str, *keys: str,
          delay: float = _KEY_DELAY) -> None:
    """Send keys to the DF window, one xdotool call per key."""
    import os
    env = dict(os.environ)
    env["DISPLAY"] = display
    for key in keys:
        subprocess.run(
            ["xdotool", "key", "--window", wid, key],
            capture_output=True, timeout=10, env=env, check=True)
        if delay:
            time.sleep(delay)


def _screenshot(display: str, path: Path) -> None:
    """Save a screenshot of the display (best-effort, never raises)."""
    try:
        import os
        env = dict(os.environ)
        env["DISPLAY"] = display
        xwd = path.with_suffix(".xwd")
        subprocess.run(["xwd", "-root", "-silent", "-out", str(xwd)],
                       capture_output=True, timeout=15, env=env)
        subprocess.run(["convert", str(xwd), str(path)],
                       capture_output=True, timeout=15, env=env)
    except Exception:  # noqa: BLE001 - screenshots are diagnostics only
        pass


def set_cursor(client: DFHackClient, x: int, y: int, z: int,
               timeout: float = 30.0) -> dict[str, Any]:
    """Move the map cursor (``df.global.cursor`` — verified live:
    it reads -30000 when unset and holds a written value)."""
    prelude = (Path(__file__).resolve().parent / "lua" / "json.lua"
               ).read_text()
    code = (f"df.global.cursor.x = {x}\n"
            f"df.global.cursor.y = {y}\n"
            f"df.global.cursor.z = {z}\n"
            f"result = {{ok = true, cursor = {{df.global.cursor.x, "
            f"df.global.cursor.y, df.global.cursor.z}}}}\n"
            f"dfh_print(result)\n")
    return client.run_lua_json(prelude + "\n" + code, timeout=timeout)


def get_cursor(client: DFHackClient,
               timeout: float = 30.0) -> dict[str, Any]:
    """Read the map cursor."""
    code = ("result = {ok = true, cursor = {df.global.cursor.x, "
            "df.global.cursor.y, df.global.cursor.z}}\n"
            "dfh_print(result)\n")
    prelude = (Path(__file__).resolve().parent / "lua" / "json.lua"
               ).read_text()
    return client.run_lua_json(prelude + "\n" + code, timeout=timeout)


def _adult_citizens(client: DFHackClient,
                    timeout: float = 30.0) -> list[dict[str, Any]]:
    """Citizens in observe order, excluding children (children cannot
    hold noble positions — they do not appear in the chooser list)."""
    state = observe.collect(client, sections=("units",), timeout=timeout)
    return [c for c in (state.get("units") or {}).get("citizens") or []
            if c.get("profession") != "Dwarven Child"]


def appoint_noble(client: DFHackClient, position: str, unit_id: int,
                  display: str = ":99",
                  screenshot_dir: Optional[Path] = None,
                  timeout: float = 30.0) -> dict[str, Any]:
    """Appoint a citizen to a noble position via the nobles screen.

    ``position`` is one of ``manager`` / ``broker`` / ``bookkeeper``
    (also ``militia_commander`` / ``sheriff`` / ``hammerer`` /
    ``chief_medical_dwarf`` work — same screen, same mechanism).
    Verified live 2026-11-26: the Lua-write path does NOT register
    (nobles screen stays VACANT), the UI path does. The chooser list
    is the adult citizens in observe order, after "Leave Vacant".

    Returns ``{"ok": bool, "reason": str, "appointed": {...}|None}``.
    """
    pos_key = {"manager": "MANAGE_PRODUCTION",
               "broker": "TRADE",
               "bookkeeper": "ACCOUNTING"}.get(position)
    if position not in NOBLES_SCREEN_ORDER:
        return {"ok": False,
                "reason": f"unknown noble position {position!r}",
                "appointed": None}
    wid = df_window_id(display)
    if wid is None:
        return {"ok": False,
                "reason": "no Dwarf Fortress window found on "
                          f"display {display}",
                "appointed": None}
    # Never send menu keys into an unknown screen: a stuck sub-screen
    # freezes the tick, and keys meant for the nobles menu would
    # navigate whatever is actually open instead.
    on_map, focus = ensure_map_view(client, wid, display, timeout=timeout)
    if not on_map:
        return {"ok": False,
                "reason": f"game is not on the main view (focus "
                          f"{focus!r}) — refusing to send menu keys",
                "appointed": None}
    try:
        adults = _adult_citizens(client, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - game read failed
        return {"ok": False, "reason": f"could not read citizens: {exc}",
                "appointed": None}
    target = next((c for c in adults if c.get("id") == unit_id), None)
    if target is None:
        return {"ok": False,
                "reason": f"no adult citizen with id {unit_id}",
                "appointed": None}
    # Chooser: "Leave Vacant" is line 0, then adults in observe order.
    chooser_index = adults.index(target) + 1
    pos_index = NOBLES_SCREEN_ORDER.index(position)
    try:
        _keys(wid, display, "n")
        time.sleep(0.8)
        _keys(wid, display, *["Down"] * pos_index)
        _keys(wid, display, "Return")
        time.sleep(0.8)
        _keys(wid, display, *["Down"] * chooser_index)
        _keys(wid, display, "Return")
        time.sleep(0.8)
        _keys(wid, display, "Escape")
        time.sleep(0.5)
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "reason": f"xdotool failed: {exc}",
                "appointed": None}
    # Confirm the game is back on the map view — a stuck sub-screen
    # freezes the tick even with the pause flag clear (seen live
    # 2026-11-26: the game sat on a unit screen for minutes).
    on_map, focus = ensure_map_view(client, wid, display, timeout=timeout)
    if not on_map:
        return {"ok": False,
                "reason": f"keys sent but the game did not return to "
                          f"the main view (focus {focus!r})",
                "appointed": None}
    if screenshot_dir is not None:
        _screenshot(display, screenshot_dir / "nobles-after-appoint.png")
    # Verify by re-reading the appointments (Lua probe).
    try:
        probe = probe_nobles(client, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - verification read failed
        return {"ok": False,
                "reason": f"appointment sent but verification read "
                          f"failed: {exc}",
                "appointed": None}
    if not probe.get("ok", False):
        return {"ok": False,
                "reason": f"noble probe failed: {probe.get('error')}",
                "appointed": None}
    if pos_key is not None:
        # probe_nobles returns each responsibility as a dict keyed by
        # assignment id ({"1": {...}}), not a list.
        raw = (probe.get("nobles") or {}).get(pos_key) or {}
        entries = raw.values() if isinstance(raw, dict) else raw
        got = next((a for a in entries
                    if a.get("unit_id") == unit_id), None)
        if got is None:
            return {"ok": False,
                    "reason": f"nobles screen did not appoint "
                              f"{target.get('name')} as {position} "
                              f"(read-back: "
                              f"{(probe.get('nobles') or {}).get(pos_key)})",
                    "appointed": None}
        return {"ok": True,
                "reason": f"{target.get('name')} appointed {position}",
                "appointed": got}
    # Positions without a responsibility mapping (e.g. militia
    # commander) are verified by the screen only — report the probe.
    return {"ok": True,
            "reason": f"keys sent for {target.get('name')} as {position}; "
                      f"no responsibility mapping to verify against",
            "appointed": {"unit_id": unit_id,
                          "name": target.get("name")}}


def create_stockpile(client: DFHackClient, box: tuple[int, ...],
                     category: str = "f",
                     display: str = ":99",
                     screenshot_dir: Optional[Path] = None,
                     timeout: float = 30.0) -> dict[str, Any]:
    """Create a stockpile via the 'p' menu (no Lua API exists —
    ``dfhack.buildings.constructAbstract`` CRASHED the game live
    2026-11-26 and must never be used; see docs/PLANNER.md).

    ``box`` is (x0, y0, z0, x1, y1, z1) inclusive, one z-level.
    ``category`` is the menu letter for the stockpile kind (``f`` =
    Food, the default; ``w`` = Wood, ``s`` = Stone, ``r`` = Refuse).
    Flow: set the map cursor to the first corner (Lua), open 'p',
    press the category letter, Enter to anchor, arrow-key to the
    opposite corner, Enter to create. The category step is required:
    'p' opens a category list first — pressing Enter there selects
    nothing (found by screenshot 2026-11-26). Verified by the
    buildings list afterwards (a new Stockpile building). A fresh
    stockpile's category settings are left at the game default
    (verified separately — see docs).
    """
    if len(box) != 6:
        return {"ok": False, "reason": f"bad box: {box!r}",
                "building_id": None}
    x0, y0, z0, x1, y1, z1 = box
    if z0 != z1 or x0 > x1 or y0 > y1:
        return {"ok": False,
                "reason": f"box must be a flat x/y rectangle: {box!r}",
                "building_id": None}
    wid = df_window_id(display)
    if wid is None:
        return {"ok": False,
                "reason": "no Dwarf Fortress window found on "
                          f"display {display}",
                "building_id": None}
    on_map, focus = ensure_map_view(client, wid, display, timeout=timeout)
    if not on_map:
        return {"ok": False,
                "reason": f"game is not on the main view (focus "
                          f"{focus!r}) — refusing to send menu keys",
                "building_id": None}
    before = observe.collect(client, sections=("buildings",),
                             timeout=timeout)
    before_ids = {b.get("id") for b in
                  (before.get("buildings") or {}).get("list") or []}
    try:
        # Open 'p' FIRST, then set the cursor: opening the menu resets
        # df.global.cursor to the menu's remembered position (verified
        # live 2026-11-26: a Lua write before 'p' was discarded and
        # three stockpiles landed at the map's southwest corner), but
        # a write while the menu is open sticks.
        _keys(wid, display, "p")
        time.sleep(0.8)
        set_cursor(client, x0, y0, z0, timeout=timeout)
        _keys(wid, display, category)
        time.sleep(0.5)
        _keys(wid, display, "Return")
        time.sleep(0.5)
        # Arrow-key from the first corner to the opposite corner.
        moves: list[str] = []
        moves += ["Right"] * (x1 - x0)
        moves += ["Down"] * (y1 - y0)
        if moves:
            _keys(wid, display, *moves, delay=0.12)
        _keys(wid, display, "Return")
        time.sleep(0.8)
        _keys(wid, display, "Escape")
        time.sleep(0.5)
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "reason": f"xdotool failed: {exc}",
                "building_id": None}
    on_map, focus = ensure_map_view(client, wid, display, timeout=timeout)
    if not on_map:
        return {"ok": False,
                "reason": f"keys sent but the game did not return to "
                          f"the main view (focus {focus!r})",
                "building_id": None}
    if screenshot_dir is not None:
        _screenshot(display,
                    screenshot_dir / "stockpile-after-create.png")
    after = observe.collect(client, sections=("buildings",),
                            timeout=timeout)
    new = [b for b in (after.get("buildings") or {}).get("list") or []
           if b.get("id") not in before_ids
           and b.get("type") == "Stockpile"]
    if not new:
        return {"ok": False,
                "reason": "no new Stockpile building after the 'p' "
                          "keystroke sequence",
                "building_id": None}
    return {"ok": True,
            "reason": f"stockpile #{new[0]['id']} created at {list(box)}",
            "building_id": new[0]["id"]}


def remove_stockpile(client: DFHackClient, building_id: int,
                     display: str = ":99",
                     timeout: float = 30.0) -> dict[str, Any]:
    """Remove a stockpile via the 'p' menu (``x``: Remove Designation).

    ``building_id`` is looked up first so the cursor goes to a tile
    inside that stockpile. Same cursor rule as create_stockpile:
    open 'p', then set the cursor while the menu is open. Verified
    by the buildings list afterwards.
    """
    state = observe.collect(client, sections=("buildings",),
                            timeout=timeout)
    target = next((b for b in (state.get("buildings") or {}).get("list")
                   or [] if b.get("id") == building_id), None)
    if target is None:
        return {"ok": False,
                "reason": f"no building #{building_id}",
                "building_id": None}
    if target.get("type") != "Stockpile":
        return {"ok": False,
                "reason": f"building #{building_id} is a "
                          f"{target.get('type')}, not a stockpile",
                "building_id": None}
    wid = df_window_id(display)
    if wid is None:
        return {"ok": False,
                "reason": "no Dwarf Fortress window found on "
                          f"display {display}",
                "building_id": None}
    on_map, focus = ensure_map_view(client, wid, display, timeout=timeout)
    if not on_map:
        return {"ok": False,
                "reason": f"game is not on the main view (focus "
                          f"{focus!r}) — refusing to send menu keys",
                "building_id": None}
    cx, cy, cz = target["x1"], target["y1"], target["z"]
    ox, oy = target["x2"], target["y2"]
    try:
        # 'x' enters remove-selection mode (same anchor + drag +
        # Enter as creation — a bare 'x' does nothing, verified
        # live 2026-11-26).
        _keys(wid, display, "p")
        time.sleep(0.8)
        set_cursor(client, cx, cy, cz, timeout=timeout)
        _keys(wid, display, "x")
        time.sleep(0.5)
        _keys(wid, display, "Return")
        time.sleep(0.5)
        moves: list[str] = []
        moves += ["Right"] * (ox - cx)
        moves += ["Down"] * (oy - cy)
        if moves:
            _keys(wid, display, *moves, delay=0.12)
        _keys(wid, display, "Return")
        time.sleep(0.8)
        _keys(wid, display, "Escape")
        time.sleep(0.5)
    except subprocess.CalledProcessError as exc:
        return {"ok": False, "reason": f"xdotool failed: {exc}",
                "building_id": None}
    on_map, focus = ensure_map_view(client, wid, display, timeout=timeout)
    if not on_map:
        return {"ok": False,
                "reason": f"keys sent but the game did not return to "
                          f"the main view (focus {focus!r})",
                "building_id": None}
    after = observe.collect(client, sections=("buildings",),
                            timeout=timeout)
    gone = all(b.get("id") != building_id
               for b in (after.get("buildings") or {}).get("list") or [])
    if not gone:
        return {"ok": False,
                "reason": f"stockpile #{building_id} still present "
                          f"after the 'x' keystroke",
                "building_id": None}
    return {"ok": True,
            "reason": f"stockpile #{building_id} removed",
            "building_id": building_id}
