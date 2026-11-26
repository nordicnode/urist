"""Area-derived planner sites (the digging gap's lesson, applied to
the rest of the planner).

The planner's workshop, bed, farm and stockpile sites were hardcoded
Athelunol coordinates at z=42 — the wrong fort and the wrong level
(Erushtathtat's surface is z175). A workshop site at z=42 on
Erushtathtat is deep underground stone, so probe_site rejects it
and the planner never builds anything. The gather box had the same
bug (fixed in run_task by probing for shrubs); these sites are fixed
the same way: derived from the live state (the Surface area + the
fort centre + the surface z), never hardcoded.

``derive_sites`` returns a dict with workshop_sites (a list of
candidates, tried in order, probe_site verifies each), bed_origin,
farm_site and food_stockpile_box. The offsets mirror the old
Athelunol layout relative to the wagon at (95, 95, 42) — workshops
around the centre, beds just off it, the farm further out, the food
stockpile beside the centre — so the layout is the same shape, just
on the right fort at the right level.

The gather box is NOT here: it needs a shrub probe (a client call),
so the daemon derives it separately and passes it in with the sites.
"""

from __future__ import annotations

from typing import Any

__all__ = ["derive_sites", "find_free_rects"]

# Offsets from the fort centre, mirroring the old Athelunol layout
# relative to the wagon at (95, 95, 42).
_WORKSHOP_OFFSETS = [(-9, -10), (-6, -10), (-12, -7), (3, -10),
                     (-12, 3), (5, -5), (8, -7), (-9, 3)]
_BED_OFFSET = (-2, -2)
_FARM_OFFSET = (-15, -15)
_FOOD_BOX_OFFSETS = ((1, -5), (5, -1))

# Slice grid characters that are buildable floor (slice.lua's legend).
_FLOOR_CHARS = frozenset({".", ","})


def find_free_rects(grid: list[str], x0: int, y0: int, z: int,
                    size: int = 3, limit: int = 8,
                    centre: tuple[int, int] | None = None
                    ) -> list[tuple[int, int, int]]:
    """Find size x size blocks of floor in a slice grid (the terrain
    layer: '.' is FLOOR, ',' is PEBBLES). Returns the top-left
    corners as (x, y, z), nearest the centre first (the fort centre
    when given, else the grid centre). This is the terrain check
    only — a candidate still needs probe_site (plants, units, stale
    occupancy) before building. The surface is hilly, so fixed
    offsets land on WALL/RAMP/BOULDER (verified live: all 8 fixed
    candidates around (95, 95) were unbuildable); the rects must be
    searched for, not assumed."""
    h = len(grid)
    w = len(grid[0]) if h else 0
    if w == 0 or h < size:
        return []
    cx, cy = centre or (x0 + w // 2, y0 + h // 2)
    found = []
    for y in range(0, h - size + 1):
        for x in range(0, w - size + 1):
            ok = True
            for dy in range(size):
                row = grid[y + dy]
                for dx in range(size):
                    if row[x + dx] not in _FLOOR_CHARS:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                found.append((x0 + x, y0 + y, z))
    found.sort(key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
    return found[:limit]


def derive_sites(areas: dict[str, Any],
                 fort_centre: tuple[int, int],
                 surface_z: int,
                 floor_rects: list[tuple[int, int, int]] | None = None
                 ) -> dict[str, Any]:
    """Derive the planner's sites from the areas (never hardcoded
    coordinates). Returns {"workshop_sites": [...], "bed_origin":
    (x, y, z), "farm_site": (x, y, z), "food_stockpile_box":
    (x0, y0, z, x1, y1, z)}. The Surface area must exist (raises
    ValueError when it does not — the planner then does not build
    rather than building blind). ``floor_rects`` is the searched
    free floor (find_free_rects + probe_site); when given, the
    workshop sites are those rects. When None, the workshop sites
    are fixed offsets from the fort centre (the offline-test
    fallback — the surface is hilly, so live the daemon always
    passes the searched rects)."""
    area_list = areas.get("areas") or []
    surface = next((a for a in area_list if a.get("kind") == "surface"),
                   None)
    if surface is None:
        raise ValueError("no Surface area — cannot derive sites")
    # Clamp into the Surface bbox so a site never lands outside the
    # area (the fort centre is inside it by construction, but the
    # offsets can push a site out on a small embark).
    b = surface.get("bbox") or {}
    x0, y0 = b.get("x0", 0), b.get("y0", 0)
    x1, y1 = b.get("x1", 191), b.get("y1", 191)
    cx, cy = fort_centre

    def _clamp(x: int, y: int) -> tuple[int, int]:
        return (min(max(x, x0), x1), min(max(y, y0), y1))

    workshop_sites = list(floor_rects) if floor_rects is not None \
        else []
    if floor_rects is None:
        for dx, dy in _WORKSHOP_OFFSETS:
            x, y = _clamp(cx + dx, cy + dy)
            workshop_sites.append((x, y, surface_z))
    bx, by = _clamp(cx + _BED_OFFSET[0], cy + _BED_OFFSET[1])
    fx, fy = _clamp(cx + _FARM_OFFSET[0], cy + _FARM_OFFSET[1])
    f0 = _clamp(cx + _FOOD_BOX_OFFSETS[0][0],
                cy + _FOOD_BOX_OFFSETS[0][1])
    f1 = _clamp(cx + _FOOD_BOX_OFFSETS[1][0],
                cy + _FOOD_BOX_OFFSETS[1][1])
    return {
        "workshop_sites": workshop_sites,
        "bed_origin": (bx, by, surface_z),
        "farm_site": (fx, fy, surface_z),
        "food_stockpile_box": (f0[0], f0[1], surface_z,
                               f1[0], f1[1], surface_z),
    }
