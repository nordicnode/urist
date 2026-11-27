"""Digging: reachability + hazard checks, completion verification,
and area-derived dig sites (the digging gap).

The gap (Mikey's question 2026-11-26): dig was designation-only
verified — no proof a Dig job spawns, a dwarf digs it, and the
terrain changes; no reachability check; no hazard check; no
completion tracking; the planner designated one hardcoded down-stair
(at Athelunol coordinates, z=42 — the wrong fort and the wrong
level).

Geometry (verified live 2026-11-26 on Erushtathtat): a dwarf stands
on the FLOOR at the surface (z175 at the fort centre); the solid
earth below is soil (z174) then stone. A down-stair / channel is
designated on the FLOOR tile (the surface a dwarf stands on); a
regular dig / up-stair is designated on a WALL tile. Designating a
down-stair on buried soil (z174) sets the bits but the game never
turns it into a Dig job — no dwarf can reach a buried tile — and
``act_dig.lua`` used to reject the correct floor location (it
required WALL for every mode). Both are fixed: the shape check is
per-mode now, and this module refuses unreachable / hazardous sites
before anything is designated.

Checks (all paused reads — no game time, no drink):
- ``check_dig_site``: for one tile + mode, reads the column and
  (when given) the areas. Hazard: what is below (down-stair /
  channel), above (up-stair), or in the tile itself (dig) — magma,
  aquifer, water. Reachability: a dwarf must be able to stand
  where the digging happens — on the surface (open sky above) or
  in an area connected to the Surface. Returns a verdict, never a
  bare boolean: the reason names the hazard / the missing access.
- ``verify_dig``: after the dig, the designation must be gone and
  every tile must read the mode's expected post-dig class (dig to
  floor, stairs/ramp to passage, channel to air — see
  EXPECTED_DIG_CLASS). A designation that is still set, or a tile
  reading anything else, is not complete.
- ``derive_dig_site``: the planner's dig site, derived from the
  areas (the Surface area + the fort centre) instead of hardcoded
  coordinates. Returns a down-stair site on the surface and a room
  box one z-level below it.
- ``dig_to_completion`` (in actions.py): the end-to-end loop —
  designate (after the checks) -> wait for a Dig job to spawn ->
  wait for completion. Verified live when drink allows; see
  tests/test_digging_live.py.
"""

from __future__ import annotations

from typing import Any, Optional

from dfhack_rpc import DFHackClient

from . import column as column_mod
from .actions import _run_helper

#: How far below a down-stair / channel to look for hazards (levels).
HAZARD_LOOKAHEAD = 3

#: CLI dig mode -> the column class a tile must read AFTER the dig
#: completes (column.lua's classifier: FLOOR shape -> 'floor',
#: RAMP / STAIR_* shapes -> 'passage', open space -> 'air'). The
#: expected post-dig class is mode-dependent (external review C4,
#: 2026-11-27): a plain dig mines a wall out and leaves a FLOOR
#: tile, a stair carves a passage, a channel opens the tile to
#: air, a ramp carves a passage. The old code checked the negative
#: (tile not in a bad set), which accepted anything else — water,
#: magma, and the never-matching display label
#: 'hidden (unrevealed)' (column.lua emits the raw class 'hidden'
#: when the tile block is nil; the merged name only exists in
#: column.py _merge_strata, which verify_dig never calls).
EXPECTED_DIG_CLASS: dict[str, frozenset[str]] = {
    "dig": frozenset({"floor"}),
    "down-stair": frozenset({"passage"}),
    "up-stair": frozenset({"passage"}),
    "up-down-stair": frozenset({"passage"}),
    "channel": frozenset({"air"}),
    "ramp": frozenset({"passage"}),
}

#: Strata classes that are a hazard to dig into / under.
HAZARD_CLASSES = ("magma", "aquifer", "water")


def _stratum_at(col: dict[str, Any], z: int) -> Optional[dict[str, Any]]:
    """The raw stratum covering z (or None when the column has a gap
    there — the column is empty above the map top)."""
    for s in col.get("strata") or []:
        if s.get("z0", 0) <= z <= s.get("z1", 0):
            return s
    return None


def _class_at(col: dict[str, Any], z: int) -> Optional[str]:
    s = _stratum_at(col, z)
    return s.get("class") if s else None


def _hazard_at(col: dict[str, Any], z: int) -> Optional[str]:
    """The hazard at one level, in plain words, or None."""
    cls = _class_at(col, z)
    if cls in ("magma",):
        return f"magma at z{z} — digging here hits lava"
    if cls in ("aquifer",):
        return f"aquifer rock at z{z} — digging here floods the fort"
    if cls in ("water",):
        return f"water at z{z} — digging here floods the fort"
    return None


def _open_above(col: dict[str, Any], z: int) -> bool:
    """True when the level above z is open space — air, passage,
    open space, cavern space, or open sky. A FLOOR above is NOT
    open: it is a slab (a second story, or the surface floor over
    a dug room), so the tile below is not on the surface and its
    reachability must be proven by the areas check instead. The
    old code counted 'floor' as open, so every buried floor under
    another floor was declared 'surface / reachable' with no
    verification at all (found live 2026-11-27 on the scratch
    fort's farm-room floor at (82,82,49))."""
    cls = _class_at(col, z + 1)
    return cls in ("air", "passage", "open space",
                   "cavern space", "open sky")


def check_dig_site(client: DFHackClient, x: int, y: int, z: int,
                   mode: str,
                   areas: Optional[dict[str, Any]] = None,
                   surface_z: Optional[int] = None) -> dict[str, Any]:
    """Check one dig site before anything is designated.

    ``mode`` is a DIG_MODES key ('dig', 'channel', 'ramp',
    'up-stair', 'down-stair', 'up-down-stair'). Reads the column at
    (x, y) (paused read). Returns {"ok", "reachable", "hazards",
    "reason", "detail"} where "ok" is True only when the site is
    reachable AND has no hazard in the dig path. "reachable" is
    None when it cannot be determined (no areas and not on the
    surface) — the caller decides whether to proceed.
    """
    try:
        col = column_mod.read_column(client, x, y)
    except Exception as exc:  # noqa: BLE001 - column failure is "unknown"
        return {"ok": False, "reachable": None, "hazards": [],
                "reason": f"column read failed: {exc}", "detail": {}}
    hazards: list[str] = []
    detail: dict[str, Any] = {"tile_class": _class_at(col, z)}
    # -- hazards: what the dig hits ----------------------------------
    if mode in ("down-stair", "channel", "up-down-stair"):
        # Digging down: the levels below the tile. A channel removes
        # the floor AND the tile below; a down-stair opens the tile
        # below. Look HAZARD_LOOKAHEAD levels down.
        depth = 2 if mode == "channel" else HAZARD_LOOKAHEAD
        for dz in range(1, depth + 1):
            h = _hazard_at(col, z - dz)
            if h:
                hazards.append(
                    f"digging down from (x{x}, y{y}, z{z}): {h}")
    elif mode == "up-stair":
        # Digging up: the level above.
        h = _hazard_at(col, z + 1)
        if h:
            hazards.append(f"digging up from (x{x}, y{y}, z{z}): {h}")
    else:  # dig / ramp: the tile itself
        h = _hazard_at(col, z)
        if h:
            hazards.append(f"digging (x{x}, y{y}, z{z}): {h}")
    # -- reachability: can a dwarf stand where the digging happens --
    reachable: Optional[bool] = None
    if mode in ("down-stair", "channel", "up-down-stair"):
        # The dwarf stands ON the tile at z (it must be a FLOOR, a
        # surface a dwarf can stand on) and digs down. A buried
        # WALL (soil/stone with no floor) has no dwarf able to dig
        # it — that is the designation that never spawns a job.
        # Once on a floor, the floor must be on the surface (open
        # sky above) or inside a reachable area (a dug room).
        if _class_at(col, z) == "floor":
            # Open sky above means the tile is on the surface — but
            # only at or above the embark level (2026-11-27,
            # external review Table 5 row 6: the surface_z
            # parameter was never used at all). Below surface_z, an
            # open space above is a dug room or a cavern, and the
            # tile's reachability must be proven by the areas check
            # instead — the old code called every such tile
            # "surface / reachable" with no verification. Hills
            # rise above the embark level, so the test is z >=
            # surface_z, not z == surface_z; a valley floor below
            # it falls through to the areas check (conservative when
            # areas are unknown, correct when they are known).
            # With no surface_z given, the old heuristic stands.
            if _open_above(col, z) and (surface_z is None
                                        or z >= surface_z):
                reachable = True
                detail["access"] = "surface (open sky above)"
            elif areas is not None:
                reachable = _in_reachable_area(areas, x, y, z)
                detail["access"] = ("in a reachable area" if reachable
                                    else "not in a reachable area")
        else:
            reachable = False
            detail["access"] = (f"tile at z{z} is "
                                f"{_class_at(col, z)}, not a floor — "
                                f"no dwarf can stand on it to dig down")
    elif mode == "up-stair":
        # The dwarf stands below (z-1, open) and digs up.
        cls_below = _class_at(col, z - 1)
        if cls_below in ("air", "floor", "passage", "open space",
                         "cavern space", "open sky"):
            reachable = True
            detail["access"] = "open space below"
        elif areas is not None:
            reachable = _in_reachable_area(areas, x, y, z - 1)
            detail["access"] = ("open space below, in a reachable "
                                "area" if reachable else
                                "no open space below")
    else:  # dig / ramp: the dwarf stands beside the wall, same z.
        reachable = None  # needs the neighbours; see check_dig_box
        detail["access"] = "needs a neighbouring open tile (see box)"
    ok = not hazards and reachable is not False
    if hazards:
        reason = "; ".join(hazards)
    elif reachable is False:
        reason = (f"no dwarf can reach (x{x}, y{y}, z{z}) to dig a "
                  f"{mode} — {detail.get('access', 'no access')}")
    elif reachable is None:
        reason = (f"reachability unknown for (x{x}, y{y}, z{z}) "
                  f"({mode}) — no areas data and not on the surface")
    else:
        reason = (f"(x{x}, y{y}, z{z}) {mode}: reachable, no hazard "
                  f"({detail.get('access')})")
    return {"ok": ok, "reachable": reachable, "hazards": hazards,
            "reason": reason, "detail": detail}


def _in_reachable_area(areas: dict[str, Any], x: int, y: int,
                       z: int) -> bool:
    """True when (x, y, z) is inside the Surface area's bbox, or
    inside an area connected to it through the graph. The areas are
    bbox-granularity (the flood-fill region is not stored per-block),
    so this is an approximation — the Dig job wait is the proof that
    a dwarf can actually get there."""
    area_list = areas.get("areas") or []
    surface = None
    target = None
    for a in area_list:
        b = a.get("bbox") or {}
        inside = (b.get("x0", 0) <= x <= b.get("x1", -1)
                  and b.get("y0", 0) <= y <= b.get("y1", -1)
                  and b.get("z0", 0) <= z <= b.get("z1", -1))
        if inside:
            if a.get("kind") == "surface":
                return True
            target = a
        if a.get("kind") == "surface":
            surface = a
    if target is None or surface is None:
        return False
    # Connected to the Surface through the graph?
    graph = areas.get("graph") or {}
    seen = {target.get("id")}
    frontier = [target.get("id")]
    while frontier:
        cur = frontier.pop()
        if cur == surface.get("id"):
            return True
        for nxt in graph.get(cur) or []:
            if nxt not in seen:
                seen.add(nxt)
                frontier.append(nxt)
    return False


def check_dig_box(client: DFHackClient,
                  box: tuple[int, ...], mode: str,
                  areas: Optional[dict[str, Any]] = None,
                  surface_z: Optional[int] = None
                  ) -> dict[str, Any]:
    """Check every tile in a dig box (for the horizontal modes the
    reachability needs a neighbouring open tile at the same z, so
    the box check reads the neighbours too). Returns the same shape
    as check_dig_site, with the first failing tile named."""
    x0, y0, z0, x1, y1, z1 = box
    if z0 != z1:
        # A dig box is one layer (H8, 2026-11-27): the Lua helpers
        # only touch z0, so a multi-z box would check every layer
        # here and designate only one. Refuse at the boundary.
        return {"ok": False, "reachable": None, "hazards": [],
                "reason": (f"box {list(box)} spans z{z0}..z{z1}: dig "
                           "boxes are one layer (z0 must equal z1)"),
                "detail": {}}
    all_hazards: list[str] = []
    seen_unknown = False
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            for z in range(z0, z1 + 1):
                one = check_dig_site(client, x, y, z, mode,
                                     areas=areas, surface_z=surface_z)
                all_hazards.extend(one["hazards"])
                if one["reachable"] is None:
                    seen_unknown = True
                if not one["ok"]:
                    return {"ok": False,
                            "reachable": one["reachable"],
                            "hazards": all_hazards,
                            "reason": one["reason"],
                            "detail": {"tile": [x, y, z],
                                       **one["detail"]}}
    # Horizontal modes: at least one tile in the box must have an
    # open neighbour at the same z (a dwarf stands beside the wall).
    if mode in ("dig", "ramp"):
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                for z in range(z0, z1 + 1):
                    if _has_open_neighbour(client, x, y, z):
                        return {"ok": True, "reachable": True,
                                "hazards": all_hazards,
                                "reason": (f"box {list(box)} {mode}: "
                                           "reachable, no hazard"),
                                "detail": {}}
        return {"ok": False, "reachable": False,
                "hazards": all_hazards,
                "reason": (f"no dwarf can reach box {list(box)} to "
                           f"dig {mode} — no open tile beside it at "
                           f"the same level"),
                "detail": {}}
    if seen_unknown:
        # A tile whose reachability could not be determined (no
        # areas, not on the surface) must not be reported as
        # verified-reachable — the old code returned a literal
        # True here (2026-11-27, external review H5). The dig
        # still proceeds (ok=True): the job wait is the proof.
        return {"ok": True, "reachable": None, "hazards": all_hazards,
                "reason": (f"box {list(box)} {mode}: reachability "
                           "unknown — no areas data and not on the "
                           "surface"),
                "detail": {}}
    return {"ok": True, "reachable": True, "hazards": all_hazards,
            "reason": f"box {list(box)} {mode}: reachable, no hazard",
            "detail": {}}


def _has_open_neighbour(client: DFHackClient, x: int, y: int,
                        z: int) -> bool:
    """True when a neighbouring tile at the same z is open space a
    dwarf can stand in (for horizontal digs)."""
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        try:
            col = column_mod.read_column(client, x + dx, y + dy)
        except Exception:  # noqa: BLE001 - a failed column is "no"
            continue
        if _class_at(col, z) in ("air", "floor", "passage",
                                 "open space", "cavern space",
                                 "open sky"):
            return True
    return False


def verify_dig(client: DFHackClient, box: tuple[int, ...],
               mode: str) -> dict[str, Any]:
    """Verify a dig completed: the designation must be gone AND
    every tile in the box must read the mode's expected post-dig
    class (see EXPECTED_DIG_CLASS). A designation still set, or a
    tile still solid — or reading anything other than the expected
    class (water, magma, hidden, a floor where a stair should be)
    — is not complete. Returns {"complete", "designations_left",
    "terrain_ok", "reason"}. Raises ValueError on an unknown mode:
    a mode with no expected class must fail loudly, never silently
    pass (mode 'clear' never reaches here — it has no job type and
    dig_to_completion rejects it first)."""
    x0, y0, z0, x1, y1, z1 = box
    expected = EXPECTED_DIG_CLASS.get(mode)
    if expected is None:
        raise ValueError(
            f"verify_dig: unknown dig mode {mode!r} "
            f"(want one of {sorted(EXPECTED_DIG_CLASS)})")
    if z0 != z1:
        # A dig box is one layer (H8, 2026-11-27): the probe only
        # reads z0, so a multi-z box could never verify honestly.
        raise ValueError(
            f"verify_dig: box {list(box)} spans z{z0}..z{z1} — dig "
            f"boxes are one layer (z0 must equal z1)")
    probe = _run_helper(
        client, "probe_dig.lua",
        {"x0": x0, "y0": y0, "z0": z0, "x1": x1, "y1": y1, "z1": z1})
    left = probe.get("dig_total", -1) if probe.get("ok") else -1
    # Terrain: every tile in the box must read the mode's expected
    # post-dig class. A dug wall BECOMES a floor tile (mode dig),
    # a carved stair reads 'passage', a channelled tile reads
    # 'air' — the old negative check ("not in a bad set") accepted
    # water, magma and the never-matching 'hidden (unrevealed)'
    # label, and listed 'floor' as undug for every mode, so a
    # horizontal dig could never verify (the room dig on the
    # region5 fort, 2026-11-27, "failed" after 600 s with its
    # designations gone and its tiles reading 'floor').
    want = " or ".join(sorted(expected))
    terrain_ok = True
    bad: list[str] = []
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            for z in range(z0, z1 + 1):
                try:
                    col = column_mod.read_column(client, x, y)
                except Exception:  # noqa: BLE001
                    terrain_ok = False
                    bad.append(f"({x}, {y}, {z}): column failed")
                    continue
                cls = _class_at(col, z)
                if cls not in expected:
                    terrain_ok = False
                    bad.append(f"(x{x}, y{y}, z{z}) still "
                               f"{cls or 'no column'}, want {want}")
    complete = (left == 0 and terrain_ok)
    if complete:
        reason = f"box {list(box)} {mode}: dug (designation gone, " \
                 f"terrain changed)"
    elif left != 0:
        reason = (f"box {list(box)} {mode}: not complete — "
                  f"{left} designation(s) still set")
    else:
        reason = (f"box {list(box)} {mode}: designation gone but "
                  f"terrain unchanged — {'; '.join(bad[:3])}")
    return {"complete": complete, "designations_left": left,
            "terrain_ok": terrain_ok, "reason": reason}


def derive_dig_site(areas: dict[str, Any],
                    fort_centre: tuple[int, int],
                    surface_z: int) -> dict[str, Any]:
    """Derive the planner's dig site from the areas (never hardcoded
    coordinates): a down-stair on the Surface inside / nearest the
    fort centre, and a room box one z-level below it. Returns
    {"stairs": (x, y, z), "room": (x0, y0, z0, x1, y1, z1),
    "surface_z": <the embark level, so the dig action's site check
    can tell surface from cavern/dug space>, "reason"}. The room is
    7x7 around the stairs. Raises ValueError when there is no
    Surface area to derive from."""
    area_list = areas.get("areas") or []
    surface = None
    for a in area_list:
        if a.get("kind") == "surface":
            surface = a
            break
    if surface is None:
        raise ValueError("no Surface area — cannot derive a dig site")
    # The Surface's bbox is its extent; pick the tile in it nearest
    # the fort centre (clamped into the bbox), at the surface z.
    b = surface.get("bbox") or {}
    tx = min(max(fort_centre[0], b.get("x0", 0)), b.get("x1", 191))
    ty = min(max(fort_centre[1], b.get("y0", 0)), b.get("y1", 191))
    stairs = (tx, ty, surface_z)
    room = (tx - 3, ty - 3, surface_z - 1,
            tx + 3, ty + 3, surface_z - 1)
    return {"stairs": stairs, "room": room, "surface_z": surface_z,
            "reason": (f"down-stair at (x{tx}, y{ty}, z{surface_z}) "
                       f"on the Surface near the fort centre "
                       f"(x{fort_centre[0]}, y{fort_centre[1]}), "
                       f"room 7x7 one level below")}
