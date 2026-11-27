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
  the terrain must have changed (the tile is a stair / open space,
  read from the column). A designation that is still set, or a tile
  that is still solid, is not complete.
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
from .actions import _Fail, _run_helper

#: How far below a down-stair / channel to look for hazards (levels).
HAZARD_LOOKAHEAD = 3

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
    """True when the level above z is open (air / open sky / floor
    the dwarf stands on is not open — the level above must be open
    space for the dwarf to be there)."""
    cls = _class_at(col, z + 1)
    return cls in ("air", "floor", "passage", "open space",
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
            if _open_above(col, z):
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
    all_hazards: list[str] = []
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            for z in range(z0, z1 + 1):
                one = check_dig_site(client, x, y, z, mode,
                                     areas=areas, surface_z=surface_z)
                all_hazards.extend(one["hazards"])
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
    """Verify a dig completed: the designation must be gone AND the
    terrain must have changed (the tile is a stair / open space,
    read from the column). A designation still set, or a tile still
    solid, is not complete. Returns {"complete", "designations_left",
    "terrain_ok", "reason"}."""
    x0, y0, z0, x1, y1, z1 = box
    probe = _run_helper(
        client, "probe_dig.lua",
        {"x0": x0, "y0": y0, "z0": z0, "x1": x1, "y1": y1, "z1": z1})
    left = probe.get("dig_total", -1) if probe.get("ok") else -1
    # Terrain: every tile in the box must no longer be solid.
    # A dug tile is a stair, a ramp, or open space — or, for a
    # plain dig, a FLOOR: mining a wall out leaves a FLOOR tile
    # (column.lua classifies FLOOR shape as 'floor'). The old code
    # listed 'floor' as undug for every mode, so a horizontal dig
    # could never verify — the room dig on the region5 fort
    # (2026-11-27) had its designations gone and its tiles reading
    # 'floor' and still "failed" after 600 s. For stair/channel
    # modes a tile still reading 'floor' IS unchanged (a down-stair
    # must become a stair), so 'floor' stays bad there.
    bad_classes = {"stone", "soil", "mineral", "aquifer",
                   "hidden (unrevealed)"}
    if mode != "dig":
        bad_classes = bad_classes | {"floor"}
    terrain_ok = True
    bad: list[str] = []
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            for z in range(z0, z1 + 1):
                try:
                    col = column_mod.read_column(client, x, y)
                except Exception as exc:  # noqa: BLE001
                    terrain_ok = False
                    bad.append(f"(x{x}, y{y}, z{z}): column failed")
                    continue
                cls = _class_at(col, z)
                if cls in bad_classes:
                    terrain_ok = False
                    bad.append(f"(x{x}, y{y}, z{z}) still {cls}")
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
    "reason"}. The room is 7x7 around the stairs. Raises ValueError
    when there is no Surface area to derive from."""
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
    return {"stairs": stairs, "room": room,
            "reason": (f"down-stair at (x{tx}, y{ty}, z{surface_z}) "
                       f"on the Surface near the fort centre "
                       f"(x{fort_centre[0]}, y{fort_centre[1]}), "
                       f"room 7x7 one level below")}
