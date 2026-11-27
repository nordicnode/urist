"""Placement: verified-free sites for anything that needs placing.

Mikey's directive (2026-11-26): the model must know exactly where
it can and cannot place things, because that only gets more important
as the fort grows. The harness computes verified-free sites and the
model never guesses coordinates. A build failure names a verified
alternative site — never just "gather the blocker or move", but
WHERE to move.

Design principle (Mikey, voice call): ROBUSTNESS AND INFORMATION
DENSITY — as much information as possible without overloading. The
snapshot carries verified sites compactly (a few named options per
kind, with what makes each one good), not a dump of every free tile;
the full detail lives behind the query route (/v1/sites). Every
placement answer carries what the model needs to decide — the
verified sites, why each is good, what is blocked and why, and the
named alternative on a failure — and nothing it does not need. The
snapshot is an index, detail on demand, token budgets enforced
(30K target, 140K hard cap). If a check cannot be verified, say so
explicitly and fall back to the next-best check — never silently
drop it and never silently hand the model an unverified site.

One system for every kind (workshops, stockpiles, zones, training
grounds, traps, fortifications, rooms): a placement request names
the kind and size, the harness returns verified sites. The
verification adapts to the kind only in size and terrain; the
mechanism is the same five layers, all in probe_site.lua:

  1. Terrain: every tile FLOOR or PEBBLES (buildable).
  2. Occupancy: no stale building-occupancy flag (a deconstructed
     building's tiles stay unbuildable until cleared).
  3. Clear: no plants/shrubs, no units standing there.
  4. Overlap: no overlapping building. Stockpiles and zones ARE
     buildings (Stockpile / Civzone types), so this covers the
     stockpile/zone no-conflicting-overlap rule too.
  5. Reachability: dfhack.maps.canWalkBetween from the fort centre
     (the game's own pathfinder, verified live 2026-11-26) to the
     site centre. A site with no path is NOT a free site — the
     "Could not find path" construction suspension is the failure
     mode this closes. When no from-point is given, reachable is
     None (unchecked) and the site is NOT presented as verified.

Kinds covered by the finder (the size is the only per-kind input;
the creation route differs per kind and is documented in
PLACEMENT.md): workshop, stockpile, zone, farm_plot, furniture,
trap, room. Creation routes built so far: workshop (build_workshop),
stockpile (create_stockpile, constructBuilding abstract=true),
zone/civzone (create_zone, constructBuilding abstract=true).
Trap/room creation routes are still to come — their sites are
verified by this module, but no creation action exists yet.
"""

from __future__ import annotations

from typing import Any, Optional

from dfhack_rpc import DFHackClient

from .actions import _run_helper
from .sites import find_free_rects
from .spatial import render_slice

__all__ = [
    "PLACEMENT_KINDS",
    "find_sites",
    "verify_site",
    "format_compact",
    "site_why",
]

#: kind -> {default size (w, h), notes}. The size is the only
#: per-kind input to the finder; the verification layers are the
#: same for every kind (see the module docstring). Creation routes
#: live elsewhere (actions.py / act_stockpile.lua / act_zone.lua).
PLACEMENT_KINDS: dict[str, dict[str, Any]] = {
    "workshop": {
        "default_size": (3, 3),
        "notes": "3x3 workshop (Still, Carpenter's, Mason, Kitchen).",
    },
    "stockpile": {
        "default_size": (5, 5),
        "notes": "5x5 stockpile (food, wood, stone, refuse).",
    },
    "zone": {
        "default_size": (5, 5),
        "notes": "5x5 activity zone (meeting, pasture, bedroom, "
                 "dining, temple, barracks, archery).",
    },
    "farm_plot": {
        "default_size": (3, 3),
        "notes": "Farm plot (soil floor; size varies).",
    },
    "furniture": {
        "default_size": (1, 1),
        "notes": "1x1 furniture (bed, table, chair, door).",
    },
    "trap": {
        "default_size": (1, 1),
        "notes": "1x1 trap (weapon, cage, stonefall).",
    },
    "room": {
        "default_size": (3, 3),
        "notes": "Room floor area (bedroom, dining, office).",
    },
}


def _dist(a: tuple[int, int], b: tuple[int, int]) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def site_why(site: dict[str, Any],
             centre: tuple[int, int]) -> str:
    """One-line 'why this site is good' for a verified site.

    Distance-based, so it stays true without extra queries: the
    nearest site is 'nearest the fort', the rest get their
    compass direction + distance from the fort centre.
    """
    pos = site["pos"]
    d = _dist((pos[0], pos[1]), centre)
    if d < 3:
        return "nearest the fort"
    dx, dy = pos[0] - centre[0], pos[1] - centre[1]
    ew = "east" if dx > 0 else "west" if dx < 0 else ""
    ns = "south" if dy > 0 else "north" if dy < 0 else ""
    direction = " ".join(p for p in (ns, ew) if p) or "at"
    return f"{int(round(d))} tiles {direction} of the fort"


def find_sites(client: DFHackClient,
               kind: str,
               width: int,
               height: int,
               centre: tuple[int, int],
               surface_z: int,
               from_pos: tuple[int, int, int],
               limit: int = 5,
               search_radius: int = 20,
               probe_budget: int = 12,
               timeout: float = 30.0
               ) -> dict[str, Any]:
    """Find verified-free sites for a kind + size.

    Renders slices around the centre at surface_z (and one level
    up), finds free rects of the requested size, and verifies each
    with probe_site (terrain, occupancy, plants, units, overlap)
    PLUS reachability from from_pos (the fort centre, where
    dwarves stand). Returns {"sites": [verified...], "blocked":
    [top blocked candidates with reasons], "kind": kind, ...}.

    A site is verified only when probe_site says free AND
    reachable is True. A site whose reachability could not be
    checked (reachable None) is never returned as verified — it
    is reported in "blocked" with the reason "reachability
    unchecked". The caller must say so explicitly, never silently
    hand the model an unverified site.
    """
    if kind not in PLACEMENT_KINDS:
        raise ValueError(f"unknown placement kind {kind!r} "
                         f"(choose from {sorted(PLACEMENT_KINDS)})")
    if width < 1 or height < 1:
        raise ValueError(f"bad size {width}x{height}")
    # centre is a 2-tuple (x, y); a 3-tuple (x, y, z) is accepted
    # and normalised (callers sometimes pass the fort centre with
    # its z). The slice search and the rect finder use x/y only.
    cx, cy = centre[0], centre[1]
    centre2 = (cx, cy)
    if from_pos is None:
        # Reachability cannot be checked without a walkable
        # origin — and a site whose reachability is unchecked is
        # never verified. Say so explicitly rather than returning
        # an empty list the caller might read as "no free ground".
        return {"kind": kind, "width": width, "height": height,
                "sites": [], "blocked": [],
                "centre": [cx, cy, surface_z], "from": None,
                "reason": "reachability_unchecked"}
    verified: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    probed = 0
    for z in (surface_z, surface_z + 1):
        if len(verified) >= limit:
            break
        try:
            sl = render_slice(client,
                              max(0, cx - search_radius),
                              max(0, cy - search_radius), z,
                              min(191, cx + search_radius),
                              min(191, cy + search_radius))
        except Exception:  # noqa: BLE001 - no slice is no sites
            continue
        grid = sl.get("grid") or []
        if not grid:
            continue
        size = max(width, height)
        for pos in find_free_rects(
                grid, max(0, cx - search_radius),
                max(0, cy - search_radius), z,
                size=size, limit=probe_budget, centre=centre2):
            if len(verified) >= limit or probed >= probe_budget:
                break
            # find_free_rects returns size x size squares; a
            # non-square request (e.g. 5x3) needs the exact rect,
            # so re-check the requested footprint here.
            if size != width or size != height:
                # Only square rects are returned by the finder;
                # a non-square request is verified by probing the
                # exact footprint (the terrain layer already
                # confirmed the square, so this is a re-check).
                pass
            probed += 1
            try:
                probe = _run_helper(
                    client, "probe_site.lua",
                    {"x": pos[0], "y": pos[1], "z": pos[2],
                     "width": width, "height": height,
                     "from_x": from_pos[0], "from_y": from_pos[1],
                     "from_z": from_pos[2]},
                    timeout=timeout)
            except Exception:  # noqa: BLE001 - a failed probe
                continue  # is not a free site
            if not probe.get("ok", False):
                continue
            reachable = probe.get("reachable")
            if probe.get("free") and reachable is True:
                site = {"pos": [pos[0], pos[1], pos[2]],
                        "kind": kind, "width": width,
                        "height": height, "reachable": True,
                        "why": site_why(
                            {"pos": [pos[0], pos[1], pos[2]]}, centre)}
                verified.append(site)
            else:
                problems = probe.get("problems") or []
                reason = "; ".join(problems[:2])
                if reachable is None:
                    reason = (reason + "; reachability unchecked"
                              if reason else "reachability unchecked")
                blocked.append({"pos": [pos[0], pos[1], pos[2]],
                                "reason": reason})
    verified.sort(key=lambda s: _dist((s["pos"][0], s["pos"][1]),
                                      centre))
    return {"kind": kind, "width": width, "height": height,
            "sites": verified[:limit],
            "blocked": blocked[:3],
            "centre": [cx, cy, surface_z],
            "from": list(from_pos)}


def verify_site(client: DFHackClient,
                kind: str,
                pos: tuple[int, int, int],
                width: int,
                height: int,
                from_pos: tuple[int, int, int],
                timeout: float = 30.0) -> dict[str, Any]:
    """Verify one site (the same five layers as find_sites).

    Returns {"free": bool, "reachable": bool|None,
    "problems": [...]}. Used by the build actions to check a
    specific site, and by the query route for a single-site check.
    """
    if kind not in PLACEMENT_KINDS:
        raise ValueError(f"unknown placement kind {kind!r}")
    probe = _run_helper(
        client, "probe_site.lua",
        {"x": pos[0], "y": pos[1], "z": pos[2],
         "width": width, "height": height,
         "from_x": from_pos[0], "from_y": from_pos[1],
         "from_z": from_pos[2]},
        timeout=timeout)
    if not probe.get("ok", False):
        return {"free": False, "reachable": None,
                "problems": [f"probe failed: {probe.get('error')}"]}
    return {"free": bool(probe.get("free")),
            "reachable": probe.get("reachable"),
            "problems": list(probe.get("problems") or [])}


def placement_anchor(state: dict[str, Any],
                     areas: Optional[dict[str, Any]] = None
                     ) -> tuple[tuple[int, int], int,
                                tuple[int, int, int]]:
    """A robust anchor for the placement search: (centre, surface_z,
    from_pos).

    The anchor must be where the fort actually is, not where the
    map is. The old derivation (Surface area bbox centre + lowest
    citizen z) is fragile on a hilly map: the Surface area spans
    the whole map, so its centre is the map centre (95,95), not the
    fort (97,97); and the lowest citizen z varies with where the
    dwarves happen to wander (175 one scan, 176 the next, up to
    179 on the hills). With that anchor the search found 0 sites —
    canWalkBetween from the map centre at z=176 reaches nothing
    (2026-11-27, live).

    Priority:
    1. Buildings: the centroid of the existing building centres is
       the search centre, the most common building z is the ground
       level (buildings sit on the ground), and the first citizen's
       position is the from-point (a dwarf stands on walkable
       ground by definition — a building centre is occupied, not
       walkable, so it must never be the from-point).
    2. Citizens: the first citizen's position (walkable ground)
       as both the search centre and the from-point, its z as the
       ground level.
    3. Areas fallback: the Surface bbox centre + the areas'
       surface_z (the old behaviour, for a fort with no buildings
       and no citizens in the state).
    """
    buildings = ((state.get("buildings") or {}).get("list")) or []
    citizens = ((state.get("units") or {}).get("citizens")) or []
    # Citizen positions (walkable ground by definition). The
    # from-point is the citizen NEAREST the building centroid — a
    # distant wanderer (or one stuck in a disconnected area) would
    # make the reachability check fail spuriously.
    citizen_pos: list[tuple[int, int, int]] = []
    for c in citizens:
        pos = c.get("pos") or []
        if len(pos) == 3 and all(isinstance(v, int) for v in pos):
            citizen_pos.append((pos[0], pos[1], pos[2]))
    centres: list[tuple[int, int, int]] = []
    for b in buildings:
        c = b.get("center") or []
        if len(c) == 3 and all(isinstance(v, int) for v in c):
            centres.append((c[0], c[1], c[2]))
    if centres:
        cx = sum(c[0] for c in centres) // len(centres)
        cy = sum(c[1] for c in centres) // len(centres)
        # The ground level is the most common building z.
        zs: dict[int, int] = {}
        for c in centres:
            zs[c[2]] = zs.get(c[2], 0) + 1
        surface_z = max(zs.items(), key=lambda kv: kv[1])[0]
        if citizen_pos:
            from_pos = min(
                citizen_pos,
                key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
        else:
            from_pos = centres[0]
        return (cx, cy), surface_z, from_pos
    if citizen_pos:
        from_pos = citizen_pos[0]
        return (from_pos[0], from_pos[1]), from_pos[2], from_pos
    # Areas fallback (no buildings, no citizens in the state).
    if areas:
        surface_z = areas.get("surface_z")
        for a in areas.get("areas") or []:
            if a.get("kind") == "surface":
                b = a.get("bbox") or {}
                if all(k in b for k in ("x0", "x1", "y0", "y1")):
                    cx = (b["x0"] + b["x1"]) // 2
                    cy = (b["y0"] + b["y1"]) // 2
                    if isinstance(surface_z, int):
                        return (cx, cy), surface_z, (cx, cy, surface_z)
        if isinstance(surface_z, int):
            return (95, 95), surface_z, (95, 95, surface_z)
    raise ValueError("no placement anchor: no buildings, citizens, "
                     "or areas")


def format_compact(sites_by_kind: dict[str, list[dict[str, Any]]],
                   limit_per_kind: int = 3) -> str:
    """Compact snapshot text for verified sites, token-light.

    A few named options per kind, with what makes each one good —
    not a dump of every free tile. The full detail (checks, blocked
    reasons) lives behind GET /v1/sites. Returns "" when there are
    no sites (the section is omitted, not rendered empty).
    """
    lines: list[str] = []
    for kind in sorted(sites_by_kind):
        sites = [s for s in (sites_by_kind[kind] or [])
                 if isinstance(s, dict) and isinstance(
                     s.get("pos"), (list, tuple))]
        sites = sites[:limit_per_kind]
        if not sites:
            continue
        w = sites[0].get("width")
        h = sites[0].get("height")
        size = f" {w}x{h}" if w and h else ""
        opts = "; ".join(
            f"({s['pos'][0]},{s['pos'][1]},{s['pos'][2]}) "
            f"{s.get('why') or ''}".rstrip()
            for s in sites)
        lines.append(f"  {kind}{size}: {opts}.")
    if not lines:
        return ""
    return "Placement (verified free + reachable):\n" + "\n".join(lines)
