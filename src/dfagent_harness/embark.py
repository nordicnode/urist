"""Embark module: seeded world gen -> site screening -> embark -> verify.

This is the pre-game setup path, quarantined from the harness API by
design: there is no non-UI way to embark in DFHack 0.47.05-r8, so the
embark screen is driven with xdotool keystrokes sent to the DF window,
exactly like the UI-driven noble/stockpile paths in ui.py. Every step
VERIFIES its effect by re-reading game state through the RPC Lua
helpers afterwards — a keystroke sequence is never trusted on its own.

Proven path (verified live 2026-11-27, region3 and region4, scratch DF):
  generate world (seeded ``-gen``) -> Title -> "Start Playing" (Down
  once from Continue Playing) -> the world loads
  (viewscreen_adopt_regionst, a pure loading screen) ->
  ``viewscreen_choose_start_sitest`` directly (no mode selection,
  no extra Return — an extra Return once selected Adventurer) ->
  write the finder profile -> ``embark-assistant fileresult`` (quit
  the overlay first; trust the FILE, not the overlay display) ->
  open the overlay (a), full finder (f), Load (l), Find (f) -> read
  the match grid via ``dfhack.screen.readTile`` -> move the region
  cursor by arrow keys to a match -> position the embark rectangle
  by keys (u/m/h/k) -> ``e`` -> "Play Now!" -> arrival text ->
  fortress mode, verify the fort loaded (dwarves, wagon, stocks).
  "Start Playing" appears on the title screen only when a world
  without a fort exists; generate one first if it is absent.

Hard-won facts (do not re-litigate; all verified live):
  * The embark rectangle and the region cursor are independent; the
    rect does NOT follow the cursor. The rect is what ``e`` embarks.
  * Local-area keys are ``u`` (up), ``m`` (down), ``h`` (left),
    ``k`` (right) — the bottom bar reads "umhk", NOT "u/h/k/l".
    ``l`` does nothing. Each key moves the rect exactly 1 tile.
  * Key registration is flaky at this VM's ~7 FPS (~30-50% of
    presses register). Send in small batches and re-read the rect
    after each batch; never trust a blind count.
  * NEVER write ``region_pos`` (the cursor) via Lua — it crashed the
    game. Move the cursor by arrow keys only (single-step arrows are
    exact; Shift+arrows move an unreliable distance).
  * Writing the rect (``embark_pos_min/max``) via Lua does NOT crash,
    but ``e`` is then silently rejected: the Lua write sets the
    display coords but not the game's internal validation state.
    After a Lua rect set, move the rect one step by keys (``u`` then
    ``m`` back) to re-sync, then ``e`` works. Prefer keys end to end.
  * ``embark-assistant fileresult`` ACTIVATES the overlay (every
    invocation creates the plugin state). A second call fails with
    "already active" until the overlay is quit (``q``). The overlay's
    "Matching World Tiles" count can disagree with the fileresult
    FILE — trust the FILE.
  * The full Site Finder does NOT load the profile on open (it starts
    all N/A). Press ``l`` (Load) in the finder, then ``f`` (Find).
  * Find does NOT move the region cursor to a match. It builds a
    match grid (green X = match, yellow X = preliminary); the driver
    must move the cursor to a green X.
  * ``region_map`` is a ``region_map_entry**`` and does NOT support
    2D indexing from Lua; do not flat-index it and do not dump an
    entry obtained by a suspect access (both crashed the game).
    Read the match grid off the screen with ``readTile`` instead.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dfhack_rpc import DFHackClient, DFHackError

from . import ui
from .actions import _run_helper

__all__ = [
    "M2_PROFILE", "PROFILE_FIELDS", "EmbarkError", "EmbarkResult",
    "write_profile", "read_profile_civs", "read_profile",
    "run_fileresult", "read_fileresult_file", "probe_embark",
    "read_match_grid", "move_cursor_to", "move_rect_to", "set_rect",
    "embark", "verify_fort_loaded", "generate_world",
    "navigate_to_embark_screen", "scan_matches", "embark_site",
    "DEFAULT_CIVS", "viewport_for_cursor", "screen_to_world",
    "sweep_centres",
]

#: Default civilizations for a fresh world (region3's set). The driver
#: reuses the civ lines already in the profile file when one exists.
DEFAULT_CIVS = ["ELF", "HUMAN", "GOBLIN", "SKULKING"]

#: The finder profile fields, in the enum order load_profile expects.
#: Each entry is (field name, default value). The value is the display
#: text exactly as the finder shows it (see finder_ui.cpp ui_setup).
PROFILE_FIELDS: list[tuple[str, str]] = [
    ("X Dimension", "4"),
    ("Y Dimension", "4"),
    ("Low Savagery", "N/A"),
    ("Medium Savagery", "N/A"),
    ("High Savagery", "Absent"),
    ("Good", "N/A"),
    ("Neutral", "N/A"),
    ("Evil", "Absent"),
    ("Aquifer", "None"),
    ("Min River", "Brook"),
    ("Max River", "N/A"),
    ("Min Waterfall Drop", "N/A"),
    ("Flat", "N/A"),
    ("Clay", "N/A"),
    ("Sand", "N/A"),
    ("Flux", "Present"),
    ("Coal", "N/A"),
    ("Min Soil", "Shallow"),
    ("Min Soil Everywhere", "All"),
    ("Max Soil", "N/A"),
    ("Freezing", "Never Frozen"),
    ("Blood Rain", "No"),
    ("Syndrome Rain", "No Syndrome"),
    ("Reanimation", "None"),
    ("Min Adamantine", "N/A"),
    ("Max Adamantine", "N/A"),
    ("Min Magma", "N/A"),
    ("Max Magma", "N/A"),
    ("Min Biome Count", "N/A"),
    ("Max Biome Count", "N/A"),
    ("Region Type 1", "N/A"),
    ("Region Type 2", "N/A"),
    ("Region Type 3", "N/A"),
    ("Biome 1", "N/A"),
    ("Biome 2", "N/A"),
    ("Biome 3", "N/A"),
    ("Min Trees", "Woodland"),
    ("Max Trees", "N/A"),
    ("Metal 1", "ZINC"),
    ("Metal 2", "N/A"),
    ("Metal 3", "N/A"),
    ("Economic 1", "N/A"),
    ("Economic 2", "N/A"),
    ("Economic 3", "N/A"),
    ("Mineral 1", "N/A"),
    ("Mineral 2", "N/A"),
    ("Mineral 3", "N/A"),
    ("Min Necro Tower", "N/A"),
    ("Max Necro Tower", "N/A"),
    ("Min Near Civs", "N/A"),
    ("Max Near Civs", "N/A"),
]

#: The M2 site criteria (verified live 2026-11-27: 42 matches on
#: region3). Must-haves: water (Min River Brook), trees (Woodland),
#: soil (Shallow, everywhere), non-evil, temperate (Never Frozen),
#: no aquifer, no savagery, no evil weather, flux present, and a
#: metal the finder can guarantee. IRON gives 0 matches on region3
#: (iron lives in mountains, which lack soil/trees); ZINC gives 42.
M2_PROFILE: dict[str, str] = dict(PROFILE_FIELDS)

#: Name of the profile file DFHack reads (relative to the DF dir).
PROFILE_NAME = "data/init/embark_assistant_profile.txt"
#: Name of the fileresult output file. It is written under
#: ``data/init/`` (verified live 2026-11-27: the file appears at
#: ``data/init/embark_assistant_fileresult.txt``, NOT at the DF root).
FILERESULT_NAME = "embark_assistant_fileresult.txt"


def fileresult_path(df_dir: Path) -> Path:
    """Absolute path of the fileresult output file for a DF dir."""
    return Path(df_dir) / "data" / "init" / FILERESULT_NAME

#: How long fileresult takes to survey a 65x65 world (~20s observed).
FILERESULT_TIMEOUT = 120.0
#: How long to wait for the fileresult file to appear/change.
FILERESULT_POLL = 60.0

#: Viewscreen names used along the embark path.
SCREEN_EMBARK = "viewscreen_choose_start_sitest"
SCREEN_SETUP = "viewscreen_setupdwarfgamest"
SCREEN_ARRIVAL = "viewscreen_textviewerst"
SCREEN_FORT = "viewscreen_dwarfmodest"
SCREEN_TITLE = "viewscreen_titlest"

#: xdotool delay (seconds) between keys in a fast batch. The cursor
#: arrows are exact at 0.08; the rect keys need re-reads regardless.
KEY_DELAY = 0.08
#: Max keys per rect-move batch (registration is flaky; re-read after
#: each batch and send only the remaining delta).
RECT_BATCH = 5


class EmbarkError(Exception):
    """A step of the embark failed (message names the step and why)."""


@dataclass
class EmbarkResult:
    """Outcome of one embark step or the whole run."""
    ok: bool
    step: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)


def viewport_for_cursor(cx: int, cy: int, width: int, height: int,
                        dim_x: int, dim_y: int) -> dict[str, int]:
    """Overlay region-view viewport for a cursor position.

    The overlay's own math (plugins/embark-assistant/overlay.cpp,
    render): the region view is drawn at screen (i - left_x + 18,
    k - top_y + 2). span_x = width/2 - 7 - 18, span_y = height - 8
    - 2. All divisions are integer (floor — all values here are
    non-negative, so floor == C++ truncation). Kept as a pure
    function so the sweep and the tests share it with the Lua
    helper (read_match_grid.lua implements the same math).
    """
    span_x = width // 2 - 7 - 18
    span_y = height - 8 - 2
    left_x = cx - (width // 2 - 7 - 18 + 1) // 2
    top_y = cy - (height - 8 - 2 + 1) // 2
    if left_x < 0:
        left_x = 0
    if top_y < 0:
        top_y = 0
    right_x = left_x + span_x
    bottom_y = top_y + span_y
    if right_x >= dim_x:
        right_x = dim_x - 1
        left_x = right_x - span_x
    if bottom_y >= dim_y:
        bottom_y = dim_y - 1
        top_y = bottom_y - span_y
    if left_x < 0:
        left_x = 0
    if top_y < 0:
        top_y = 0
    return {"left_x": left_x, "top_y": top_y,
            "right_x": right_x, "bottom_y": bottom_y,
            "span_x": span_x, "span_y": span_y}


def screen_to_world(sx: int, sy: int,
                    viewport: dict[str, int]) -> tuple[int, int]:
    """World tile for a region-view screen cell (the inverse draw)."""
    return (sx - 18 + viewport["left_x"],
            sy - 2 + viewport["top_y"])


def sweep_centres(dim: int, span: int) -> list[int]:
    """Cursor positions whose viewports tile one axis of the world.

    Centres are span//2, span//2 + span, ... with the last world
    tile appended when the tiling does not land on it. For a 65-wide
    world with span 16: [8, 24, 40, 56, 64].
    """
    centres = list(range(span // 2, dim, span))
    if not centres or centres[-1] != dim - 1:
        centres.append(dim - 1)
    return centres


def _screen_name(client: DFHackClient,
                 timeout: float = 30.0) -> str:
    """Current top viewscreen, as a short name (no pointer suffix)."""
    code = ("local vs = dfhack.gui.getCurViewscreen()\n"
            "print(tostring(vs))\n")
    out = client.run_lua(code, timeout=timeout)
    # tostring is "viewscreen_foo: 0x..." — take the part before ':'.
    name = out.strip().split(":")[0].strip()
    # Strip a leading "<viewscreen: ...>" wrapper if present.
    name = name.strip("<>").split(":")[0].strip()
    return name


def _wait_screen(client: DFHackClient, want: str,
                 timeout: float = 30.0, poll: float = 1.0) -> str:
    """Poll until the top viewscreen contains ``want``; return its name.

    Raises EmbarkError on timeout. ``want`` is a substring so the
    pointer suffix in tostring() does not matter.
    """
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            last = _screen_name(client, timeout=10.0)
        except Exception as exc:  # noqa: BLE001 - probe failed, retry
            last = f"probe failed: {exc}"
        if want in last:
            return last
        time.sleep(poll)
    raise EmbarkError(
        f"timed out waiting for screen {want!r} (last: {last!r})")


def _wait_either_screen(client: DFHackClient, wants: tuple[str, ...],
                        timeout: float = 30.0, poll: float = 1.0) -> str:
    """Poll until the top viewscreen contains any of ``wants``.

    Returns the screen name. Raises EmbarkError on timeout. Used
    where a screen is transient (the adopt loading screen may
    already have given way to the embark screen by the time we
    look).
    """
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            last = _screen_name(client, timeout=10.0)
        except Exception as exc:  # noqa: BLE001 - probe failed, retry
            last = f"probe failed: {exc}"
        for want in wants:
            if want in last:
                return last
        time.sleep(poll)
    raise EmbarkError(
        f"timed out waiting for one of {wants!r} (last: {last!r})")


def _keys_fast(wid: str, display: str, *keys: str,
               delay: float = KEY_DELAY) -> None:
    """Send several keys in ONE xdotool call (fast, for cursor moves).

    The cursor arrows are exact at delay 0.08 (verified live); the
    rect keys are flaky at any delay, so rect moves always re-read
    and send only the remaining delta (see move_rect_to).
    """
    if not keys:
        return
    env = dict(os.environ)
    env["DISPLAY"] = display
    cmd = ["xdotool", "key", "--delay", str(int(delay * 1000)),
           "--window", wid, *keys]
    subprocess.run(cmd, capture_output=True, timeout=60, env=env,
                   check=True)


def _keys_one(wid: str, display: str, key: str,
              delay: float = 0.35) -> None:
    """Send a single key via ui._keys (one xdotool call, slow delay)."""
    ui._keys(wid, display, key, delay=delay)


# ----------------------------------------------------------------------
# Finder profile
# ----------------------------------------------------------------------

def write_profile(df_dir: Path, profile: dict[str, str],
                  civs: Optional[list[str]] = None) -> Path:
    """Write ``embark_assistant_profile.txt`` in the learned format.

    One ``[Field:Value]`` line per field in PROFILE_FIELDS order,
    then one ``[<CIV>:N/A]`` line per civilization. ``load_profile``
    validates strictly, so field names and value texts must be exact.
    ``civs`` defaults to the civ lines already in the file (if any),
    else DEFAULT_CIVS.
    """
    df_dir = Path(df_dir)
    if civs is None:
        civs = read_profile_civs(df_dir) or list(DEFAULT_CIVS)
    lines: list[str] = []
    for fname, _default in PROFILE_FIELDS:
        value = profile.get(fname, "N/A")
        lines.append(f"[{fname}:{value}]")
    for civ in civs:
        lines.append(f"[{civ}:N/A]")
    path = df_dir / PROFILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return path


def read_profile_civs(df_dir: Path) -> list[str]:
    """Civilization lines already in the profile file (or [] if none).

    The civ set depends on the world; reusing the lines the finder
    itself saved keeps load_profile happy on a fresh world.
    """
    path = Path(df_dir) / PROFILE_NAME
    if not path.is_file():
        return []
    civs: list[str] = []
    for line in path.read_text().splitlines():
        m = re.match(r"\[([A-Z_]+):N/A\]$", line.strip())
        if m and m.group(1) not in dict(PROFILE_FIELDS):
            civs.append(m.group(1))
    return civs


def read_profile(df_dir: Path) -> dict[str, str]:
    """Parse the profile file back into a field dict (for tests)."""
    path = Path(df_dir) / PROFILE_NAME
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        m = re.match(r"\[([^:\]]+):([^\]]*)\]$", line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


# ----------------------------------------------------------------------
# fileresult screening
# ----------------------------------------------------------------------

def read_fileresult_file(df_dir: Path) -> Optional[int]:
    """Match count from ``embark_assistant_fileresult.txt`` (or None)."""
    path = fileresult_path(df_dir)
    if not path.is_file():
        return None
    text = path.read_text().strip()
    m = re.search(r"(\d+)", text)
    return int(m.group(1)) if m else None


def run_fileresult(client: DFHackClient, df_dir: Path,
                   wid: Optional[str] = None, display: str = ":98",
                   timeout: float = FILERESULT_TIMEOUT) -> int:
    """Screen the world with ``embark-assistant fileresult``.

    Returns the match count from the fileresult FILE (never the
    overlay display — the two can disagree; the file is the truth).
    Every fileresult call ACTIVATES the overlay, so a second call
    fails with "already active" until the overlay is quit (``q``);
    this retries once after quitting it. The caller must be on the
    embark screen. The fileresult file takes ~20s to appear for a
    65x65 world; this polls for it.
    """
    df_dir = Path(df_dir)
    fpath = fileresult_path(df_dir)
    before = fpath.stat().st_mtime if fpath.is_file() else 0.0

    def _run_once() -> str:
        # Use the Lua route, not client.run_command("embark-assistant",
        # "fileresult"): the direct RPC RunCommand does not deliver
        # the "fileresult" argument to this plugin command (it comes
        # back CR_WRONG_USAGE / the help text), while the in-game Lua
        # dfhack.run_command parses it correctly (verified live
        # 2026-11-27: Lua route writes the file, RPC route does not).
        try:
            out = client.run_lua(
                'dfhack.run_command("embark-assistant", "fileresult")',
                timeout=timeout)
        except DFHackError as exc:
            return str(exc)
        return str(out or "")

    out = _run_once()
    if "already active" in out:
        # The overlay is up from a previous fileresult; quit it (q)
        # and retry once. The overlay is not a viewscreen, so the
        # error text is the only detector.
        if wid is None:
            raise EmbarkError(
                "fileresult: overlay already active and no window id "
                "given to quit it (pass wid/display)")
        _keys_one(wid, display, "q", delay=0.5)
        time.sleep(2.0)
        out = _run_once()
        if "already active" in out:
            raise EmbarkError(
                "fileresult: overlay still active after quitting it "
                f"(output: {out!r:.200})")
    # Poll for the file to be (re)written.
    deadline = time.time() + FILERESULT_POLL
    while time.time() < deadline:
        if fpath.is_file() and fpath.stat().st_mtime > before:
            count = read_fileresult_file(df_dir)
            if count is not None:
                return count
        time.sleep(2.0)
    # Fall back to whatever the file holds now (it may predate us).
    count = read_fileresult_file(df_dir)
    if count is None:
        raise EmbarkError(
            "fileresult: no count file after "
            f"{FILERESULT_POLL:.0f}s (output: {out!r:.200})")
    return count


# ----------------------------------------------------------------------
# Embark screen state (Lua helpers)
# ----------------------------------------------------------------------

def probe_embark(client: DFHackClient,
                 timeout: float = 30.0) -> dict[str, Any]:
    """Current embark-screen state (cursor, rect, biome index)."""
    return _run_helper(client, "probe_embark.lua", {}, timeout=timeout)


def read_match_grid(client: DFHackClient,
                    timeout: float = 30.0) -> dict[str, Any]:
    """Matching world tiles visible in the overlay's region view.

    Returns the helper dict: ok, matches [{x, y}], count, cursor,
    viewport, grid. The overlay must be open and Find run; a count
    of 0 means no green X is visible in the current viewport (the
    caller distinguishes overlay-off / Find-not-run / no match here
    by its own state). Yellow X (preliminary) is never returned.
    The Lua JSON encoder returns a Lua array as an object with
    string numeric keys ({"1": {...}, "2": {...}}) rather than a
    JSON array, so the matches are normalised to a list here.
    """
    res = _run_helper(client, "read_match_grid.lua", {},
                      timeout=timeout)
    m = res.get("matches")
    if isinstance(m, dict):
        res["matches"] = [m[k] for k in sorted(m, key=lambda k: int(k))]
    return res


# ----------------------------------------------------------------------
# Cursor and rect movement (keys only — the game-native path)
# ----------------------------------------------------------------------

def move_cursor_to(client: DFHackClient, wid: str, display: str,
                   tx: int, ty: int,
                   timeout: float = 30.0) -> dict[str, Any]:
    """Move the region cursor to (tx, ty) by single-step arrow keys.

    Single-step arrows are exact (verified live); Shift+arrows move
    an unreliable distance and are never used. Verifies via
    probe_embark after the move and retries the remaining delta
    (up to 3 rounds). NEVER writes region_pos via Lua (it crashed
    the game).
    """
    for attempt in range(3):
        state = probe_embark(client, timeout=timeout)
        if not state.get("ok"):
            raise EmbarkError(
                f"move_cursor_to: {state.get('error', state)}")
        cur = state["cursor"]
        dx = tx - int(cur["x"])
        dy = ty - int(cur["y"])
        if dx == 0 and dy == 0:
            return {"ok": True, "cursor": {"x": tx, "y": ty},
                    "attempts": attempt + 1}
        keys: list[str] = []
        keys += ["Right"] * dx if dx > 0 else ["Left"] * (-dx)
        keys += ["Down"] * dy if dy > 0 else ["Up"] * (-dy)
        _keys_fast(wid, display, *keys)
        time.sleep(0.5)
    state = probe_embark(client, timeout=timeout)
    cur = state.get("cursor", {})
    raise EmbarkError(
        f"move_cursor_to: cursor at ({cur.get('x')},{cur.get('y')}) "
        f"after 3 attempts, wanted ({tx},{ty})")


def move_rect_to(client: DFHackClient, wid: str, display: str,
                 tx: int, ty: int,
                 timeout: float = 30.0) -> dict[str, Any]:
    """Move the embark rectangle's top-left to (tx, ty) by keys.

    Uses u (up), m (down), h (left), k (right) — one tile per key.
    Registration is flaky (~30-50% at 7 FPS), so this sends at most
    RECT_BATCH keys, re-reads the rect, and sends only the remaining
    delta, until the rect is at the target (max 40 rounds). Raises
    EmbarkError if it does not converge. The rect size is unchanged
    (X/Y Dimension from the profile, normally 4x4).
    """
    for _round in range(40):
        state = probe_embark(client, timeout=timeout)
        if not state.get("ok"):
            raise EmbarkError(
                f"move_rect_to: {state.get('error', state)}")
        mn = state["rect_min"]
        dx = tx - int(mn["x"])
        dy = ty - int(mn["y"])
        if dx == 0 and dy == 0:
            return {"ok": True,
                    "rect_min": {"x": tx, "y": ty},
                    "rect_max": state["rect_max"]}
        keys: list[str] = []
        keys += ["k"] * dx if dx > 0 else ["h"] * (-dx)
        keys += ["m"] * dy if dy > 0 else ["u"] * (-dy)
        _keys_fast(wid, display, *keys[:RECT_BATCH])
        time.sleep(0.5)
    state = probe_embark(client, timeout=timeout)
    mn = state.get("rect_min", {})
    raise EmbarkError(
        f"move_rect_to: rect at ({mn.get('x')},{mn.get('y')}) after "
        f"40 rounds, wanted ({tx},{ty})")


def set_rect(client: DFHackClient, wid: str, display: str,
             x: int, y: int, w: int = 4, h: int = 4,
             timeout: float = 30.0) -> dict[str, Any]:
    """Set the embark rectangle via Lua, then re-sync by keys.

    The Lua write alone does NOT crash, and on region4 ``e`` worked
    immediately after a Lua-only write (verified live 2026-11-27) —
    the u/m round-trip that region3 seemed to need is NOT reliably
    required. The rect keys (u/m/h/k) do NOT move the rect at all
    after a Lua write in region4 (verified: 8 keypresses, no movement
    in any direction), so the round-trip is best-effort only: try it,
    but never fail on it — the ``e`` press in embark() is the real
    test of whether the rect is accepted. Prefer this over
    move_rect_to (keys end to end) for any long move; the keys-only
    path stalls part-way (rect stuck at y=12 after 40 rounds).
    """
    code = (
        f"local vs = dfhack.gui.getCurViewscreen()\n"
        f"local loc = vs.location\n"
        f"loc.embark_pos_min.x = {x}\n"
        f"loc.embark_pos_min.y = {y}\n"
        f"loc.embark_pos_max.x = {x + w - 1}\n"
        f"loc.embark_pos_max.y = {y + h - 1}\n"
        f"print('RECT-SET')\n")
    client.run_lua(code, timeout=timeout)
    state = probe_embark(client, timeout=timeout)
    if not state.get("ok"):
        raise EmbarkError(f"set_rect: {state.get('error', state)}")
    mn = state["rect_min"]
    if (int(mn["x"]), int(mn["y"])) != (x, y):
        raise EmbarkError(
            f"set_rect: Lua write did not take (rect at "
            f"({mn['x']},{mn['y']}), wanted ({x},{y}))")
    # Best-effort re-sync: one key step up, then back. Each step is
    # verified; a dropped key is retried a few times, then we proceed
    # anyway — ``e`` is the real acceptance test, and on region4 it
    # passed with no round-trip at all.
    synced = False
    for _ in range(3):
        _keys_fast(wid, display, "u")
        time.sleep(0.5)
        s = probe_embark(client, timeout=timeout)
        if int(s["rect_min"]["y"]) == y - 1:
            synced = True
            break
    if synced:
        for _ in range(3):
            _keys_fast(wid, display, "m")
            time.sleep(0.5)
            s = probe_embark(client, timeout=timeout)
            if (int(s["rect_min"]["x"]), int(s["rect_min"]["y"])) == (x, y):
                break
    return {"ok": True, "rect_min": {"x": x, "y": y},
            "rect_max": {"x": x + w - 1, "y": y + h - 1},
            "resynced": synced}


# ----------------------------------------------------------------------
# The embark itself
# ----------------------------------------------------------------------

def embark(client: DFHackClient, wid: str, display: str,
           timeout: float = 30.0) -> dict[str, Any]:
    """Press ``e`` and walk through to fortress mode.

    e -> viewscreen_setupdwarfgamest ("Prepare for the Journey") ->
    Return on "Play Now!" -> viewscreen_textviewerst (arrival text) ->
    Return -> viewscreen_dwarfmodest (fortress mode). Each screen is
    verified before the next key. Returns the fort verification dict.
    """
    _wait_screen(client, SCREEN_EMBARK, timeout=timeout)
    for _ in range(3):
        _keys_one(wid, display, "e", delay=0.5)
        try:
            _wait_screen(client, SCREEN_SETUP, timeout=10.0)
            break
        except EmbarkError:
            continue
    else:
        raise EmbarkError(
            "embark: 'e' did not reach the setup screen after 3 tries "
            "(if the rect was set by Lua, re-sync it by keys first)")
    # "Play Now!" is the default selection: Return embarks with the
    # default dwarves and supplies (no prepare-carefully customising).
    _keys_one(wid, display, "Return", delay=0.5)
    _wait_screen(client, SCREEN_ARRIVAL, timeout=60.0)
    _keys_one(wid, display, "Return", delay=0.5)
    _wait_screen(client, SCREEN_FORT, timeout=60.0)
    time.sleep(2.0)
    return verify_fort_loaded(client, timeout=timeout)


def verify_fort_loaded(client: DFHackClient,
                       timeout: float = 30.0) -> dict[str, Any]:
    """Verify the fort loaded: citizens, wagon, drink, date, paused."""
    return _run_helper(client, "probe_fort_loaded.lua", {},
                       timeout=timeout)


# ----------------------------------------------------------------------
# World generation
# ----------------------------------------------------------------------

def generate_world(df_dir: Path, region_num: int, seed: int,
                   preset: str = "SMALL REGION",
                   timeout: float = 1800.0) -> dict[str, Any]:
    """Generate a world with ``./dfhack -gen <n> <seed> "<preset>"``.

    A partial ``data/save/region<N>`` left by an aborted -gen makes
    later -gen runs abort, so a stale partial dir is deleted first.
    -gen generates the world and exits; it does NOT land on the
    embark screen. World gen takes ~15 min for SMALL REGION with
    history; this blocks until the process exits (or times out).
    """
    df_dir = Path(df_dir)
    partial = df_dir / "data" / "save" / f"region{region_num}"
    if partial.is_dir():
        # A partial region dir aborts -gen; remove it first.
        import shutil
        shutil.rmtree(partial)
    env = dict(os.environ)
    env["DISPLAY"] = env.get("DISPLAY", ":99")
    # libSDL lives in the extracted deblibs (see scratch/deblibs-ldpath.txt).
    ldpath = Path(__file__).resolve().parent.parent / "scratch" / "deblibs-ldpath.txt"
    if ldpath.is_file():
        env["LD_LIBRARY_PATH"] = ldpath.read_text().strip()
    cmd = ["./dfhack", "-gen", str(region_num), str(seed), preset]
    proc = subprocess.run(cmd, cwd=df_dir, capture_output=True,
                          text=True, timeout=timeout, env=env)
    world_dat = df_dir / "data" / "save" / f"region{region_num}" / "world.dat"
    if proc.returncode != 0 or not world_dat.is_file():
        raise EmbarkError(
            f"generate_world: -gen failed (rc={proc.returncode}, "
            f"world.dat present={world_dat.is_file()}). "
            f"stdout tail: {proc.stdout[-500:]!r} "
            f"stderr tail: {proc.stderr[-500:]!r}")
    return {"ok": True, "region": region_num, "seed": seed,
            "preset": preset, "world_dat": str(world_dat)}


# ----------------------------------------------------------------------
# Navigation: title -> embark screen
# ----------------------------------------------------------------------

def navigate_to_embark_screen(client: DFHackClient, wid: str,
                              display: str,
                              timeout: float = 60.0) -> dict[str, Any]:
    """Title -> Start Playing -> Dwarf Fortress -> embark screen.

    From the title screen "Continue Playing" is selected; Down once
    selects "Start Playing", Return opens the world/mode selection,
    Return on "Dwarf Fortress" loads the world (viewscreen_adopt_
    regionst) and lands on viewscreen_choose_start_sitest. Keys
    sometimes do not register on first press (and the first keypress
    after a relaunch can hit a black/loading screen and be lost), so
    every step is verified by the screen name before the next key,
    with retries. "Continue Playing" only loads saved forts; it is
    never the embark path.

    "Start Playing" appears on the title screen only when a world
    without a fort exists (verified live 2026-11-27: it was absent
    while region1/region3 both had forts, and appeared once region4
    was generated). If no such world exists, generate one first
    (generate_world) — do not press Down expecting Start Playing.
    """
    _wait_screen(client, SCREEN_TITLE, timeout=timeout)
    time.sleep(2.0)  # let the title screen finish rendering
    # The adopt screen is transient — the world may already be on
    # the embark screen, or on the intermediate update_regionst, by
    # the time we look — so accept any of them here.
    _ADOPT_OR_EMBARK = ("viewscreen_adopt_regionst",
                        "viewscreen_update_regionst", SCREEN_EMBARK)
    for _ in range(3):
        _keys_one(wid, display, "Down", delay=0.5)
        time.sleep(1.0)
        # Down from Continue Playing selects Start Playing; Return
        # loads the world.
        _keys_one(wid, display, "Return", delay=0.5)
        try:
            _wait_either_screen(
                client, _ADOPT_OR_EMBARK, timeout=30.0)
            break
        except EmbarkError:
            # Still on the title (Down or Return did not register) —
            # or we landed on the load screen (Continue Playing was
            # still selected). Escape back to the title and VERIFY
            # we are there before retrying: a single Escape from the
            # load-screen wrapper lands on Options, not the title,
            # and pressing Down+Return on Options desyncs the whole
            # navigation (it once landed on the Adventurer setup).
            for _esc in range(3):
                try:
                    cur = _screen_name(client, timeout=10.0)
                except Exception:  # noqa: BLE001
                    cur = "?"
                if SCREEN_TITLE in cur:
                    break
                _keys_one(wid, display, "Escape", delay=0.5)
                time.sleep(1.0)
            continue
    else:
        raise EmbarkError(
            "navigate_to_embark_screen: could not leave the title "
            "screen via Start Playing after 3 tries")
    # World/mode selection: "Start Playing" loads the (only) world
    # without a fort. The adopt screen (viewscreen_adopt_regionst)
    # is purely a world-LOADING screen (cur_step/progress, no mode
    # fields) — it transitions via viewscreen_update_regionst to the
    # embark screen on its own once loading finishes. Do NOT press
    # Return after adopt: an extra Return once selected Adventurer
    # (viewscreen_setupadventurest) instead. So: wait for the embark
    # screen directly, with a long timeout for the world load.
    _wait_screen(client, SCREEN_EMBARK, timeout=180.0)
    return {"ok": True, "screen": SCREEN_EMBARK}


# ----------------------------------------------------------------------
# Match scanning
# ----------------------------------------------------------------------

def scan_matches(client: DFHackClient, wid: str, display: str,
                 timeout: float = 30.0) -> list[dict[str, int]]:
    """All matching world tiles, by sweeping the cursor over the world.

    The overlay's region view is 16 wide (x) by 41 tall (y) around
    the cursor, so the cursor is stepped through viewport centres
    (x in 8,24,40,56,64; y in 20,61 for a 65x65 world) and the
    region view is read at each stop. Matches are deduplicated.
    The overlay must be open and Find already run.
    """
    state = probe_embark(client, timeout=timeout)
    if not state.get("ok"):
        raise EmbarkError(f"scan_matches: {state.get('error', state)}")
    # World dimensions from the first grid read.
    first = read_match_grid(client, timeout=timeout)
    if not first.get("ok"):
        raise EmbarkError(f"scan_matches: {first.get('error', first)}")
    grid = first["grid"]
    dim_x, dim_y = int(grid["dim_x"]), int(grid["dim_y"])
    # Viewport span for this grid size (80x50 -> 16 wide, 41 tall).
    vp = viewport_for_cursor(0, 0, int(grid["w"]), int(grid["h"]),
                             dim_x, dim_y)
    xs = sweep_centres(dim_x, vp["span_x"])
    ys = sweep_centres(dim_y, vp["span_y"])
    found: dict[tuple[int, int], dict[str, int]] = {}
    for cy in ys:
        for cx in xs:
            move_cursor_to(client, wid, display, cx, cy,
                           timeout=timeout)
            time.sleep(0.5)
            res = read_match_grid(client, timeout=timeout)
            if not res.get("ok"):
                continue
            for m in res.get("matches", []):
                found[(int(m["x"]), int(m["y"]))] = {
                    "x": int(m["x"]), "y": int(m["y"])}
    return sorted(found.values(), key=lambda m: (m["y"], m["x"]))


# ----------------------------------------------------------------------
# End-to-end driver
# ----------------------------------------------------------------------

def embark_site(client: DFHackClient, df_dir: Path, wid: str,
                display: str, profile: Optional[dict[str, str]] = None,
                civs: Optional[list[str]] = None,
                timeout: float = 30.0) -> dict[str, Any]:
    """Full embark: profile -> fileresult -> pick a match -> embark.

    Assumes the game is already on the embark screen
    (viewscreen_choose_start_sitest) for the target world. Returns
    the fort verification dict. Steps:
      1. Write the finder profile.
      2. fileresult screen (quit the overlay first if active);
         require a nonzero count.
      3. The overlay is already active (fileresult activated it);
         open the full finder (f), Load (l), Find (f) — the finder
         dismisses and the overlay shows the match grid.
      4. Scan for matches; pick the first (topmost, then leftmost).
      5. Move the cursor to it, move the rect to it (keys).
      6. Embark (e -> Play Now! -> arrival -> fort) and verify.
    """
    df_dir = Path(df_dir)
    profile = dict(profile) if profile is not None else dict(M2_PROFILE)
    write_profile(df_dir, profile, civs=civs)
    count = run_fileresult(client, df_dir, wid=wid, display=display)
    if count <= 0:
        raise EmbarkError(
            "embark_site: fileresult found 0 matches for the profile "
            "(loosen a criterion and retry)")
    # The overlay is already active: run_fileresult activates it (every
    # embark-assistant invocation does), so do NOT press "a" here — it
    # would toggle the overlay off. Go straight to the full finder.
    _keys_one(wid, display, "f", delay=0.5)  # overlay f -> full finder
    time.sleep(1.0)
    _keys_one(wid, display, "l", delay=0.5)  # finder l -> Load profile
    time.sleep(1.0)
    _keys_one(wid, display, "f", delay=0.5)  # finder f -> Find
    time.sleep(2.0)
    matches = scan_matches(client, wid, display, timeout=timeout)
    if not matches:
        raise EmbarkError(
            "embark_site: fileresult said "
            f"{count} matches but the match grid showed none "
            "(overlay/Find state — retry after re-opening the finder)")
    # Quit the overlay before moving the rect: with the overlay open
    # the u/m/h/k rect keys are intercepted (the rect stalls part-way
    # — verified live 2026-11-27: rect stuck at (12,12) after 40
    # rounds with the overlay up). Arrow keys still move the cursor
    # with the overlay open, but the rect keys do not.
    _keys_one(wid, display, "q", delay=0.5)
    time.sleep(1.0)
    target = matches[0]
    move_cursor_to(client, wid, display, target["x"], target["y"],
                   timeout=timeout)
    # Position the rect by Lua (set_rect): the keys-only move_rect_to
    # stalls on long moves (the rect keys do not move the rect after
    # a Lua write / over distance — verified live 2026-11-27). The
    # Lua write is verified by probe, and ``e`` in embark() is the
    # real acceptance test.
    set_rect(client, wid, display, target["x"], target["y"],
             timeout=timeout)
    fort = embark(client, wid, display, timeout=timeout)
    fort["matches"] = count
    fort["target"] = target
    fort["scanned"] = len(matches)
    return fort
