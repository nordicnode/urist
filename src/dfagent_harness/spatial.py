"""Spatial model: slices, block scan, area derivation, connectivity.

World-model design §3. The agent never sees the whole map; it sees
named areas (the spatial atom), ASCII slices of one place at a time,
and a block-granularity connectivity graph between areas.

Read safety (design §8): every function here that touches the game
takes a client and reads only while the game is verified paused —
callers must wrap these in ``paused_read`` (the HTTP routes do).
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Optional

from dfhack_rpc import DFHackClient

from .actions import _helper_or_fail, _run_helper

__all__ = [
    "LEGEND", "SLICE_LAYERS", "MAX_SLICE", "FULL_SLICE",
    "estimate_tokens", "render_slice", "scan_blocks",
    "derive_areas", "find_path", "resolve_area", "area_summary",
]

# -- slice ---------------------------------------------------------------

LEGEND = {
    "#": "wall (any solid — stone, soil, mineral)",
    ".": "floor", ",": "floor with pebbles", "_": "ramp",
    "<": "up-stair", ">": "down-stair", "X": "up/down stair",
    "+": "closed door", "=": "bridge", '"': "grate", "^": "trap",
    "~": "water", "!": "magma", "T": "tree", "*": "shrub/plant",
    "o": "boulder/loose stone", "B": "building",
    "D": "designated for digging", "S": "smoothed/engraved",
    "d": "citizen dwarf", "u": "other unit",
    " ": "open air, void, or hidden tile (blank)",
}

SLICE_LAYERS = ("terrain", "water", "designations", "buildings", "units")
MAX_SLICE = 64          # max 64x64 tiles per call (design §3.4)
FULL_SLICE = 192        # a full z-level, explicit on-demand only


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token (design §1e anchor)."""
    return max(1, len(text) // 4)


def render_slice(client: DFHackClient, x0: int, y0: int, z: int,
                 x1: int, y1: int, layer: str = "terrain",
                 allow_full: bool = False) -> dict[str, Any]:
    """Render one slice (design §3.4). Returns the slice + its cost.

    Bounds: at most 64x64 tiles unless ``allow_full`` (then at most
    192x192, a full z-level, flagged expensive in the response).
    Raises ValueError on a bad rect/layer, _Fail on a helper failure.
    """
    if layer not in SLICE_LAYERS:
        raise ValueError(f"unknown layer: {layer!r}")
    if x1 < x0 or y1 < y0:
        raise ValueError("empty rect: x1 < x0 or y1 < y0")
    w, h = x1 - x0 + 1, y1 - y0 + 1
    limit = FULL_SLICE if allow_full else MAX_SLICE
    if w > limit or h > limit:
        raise ValueError(
            f"slice {w}x{h} exceeds the {limit}x{limit} cap"
            + ("" if allow_full else " (pass allow_full for a full z-level)"))
    t0 = time.monotonic()
    out = _helper_or_fail(client, "slice.lua", {
        "x0": x0, "y0": y0, "z": z, "x1": x1, "y1": y1,
        "layer": layer}, timeout=60.0)
    grid = out["slice"]["grid"]
    text = "\n".join(grid)
    ms = int((time.monotonic() - t0) * 1000)
    return {
        "bbox": out["slice"]["bbox"], "layer": layer,
        "grid": grid, "legend": LEGEND,
        "markers": out["slice"]["markers"],
        "counts": out["slice"]["counts"],
        "hidden": out["slice"]["hidden"],
        "cost": {
            "tokens": estimate_tokens(text),
            "ms": ms, "lua_ms": out["slice"]["cost_ms"],
            "expensive": allow_full,
        },
        "summary": _slice_summary(out["slice"], layer),
    }


def _slice_summary(s: dict[str, Any], layer: str) -> str:
    parts = []
    counts = {c["glyph"]: c["count"] for c in s["counts"]}
    water = counts.get("~", 0)
    magma = counts.get("!", 0)
    if water:
        parts.append(f"{water} water tiles")
    if magma:
        parts.append(f"{magma} magma tiles")
    trees = counts.get("T", 0)
    shrubs = counts.get("*", 0)
    if trees:
        parts.append(f"{trees} trees")
    if shrubs:
        parts.append(f"{shrubs} shrubs/plants")
    doors = counts.get("+", 0)
    if doors:
        parts.append(f"{doors} doors")
    if s["hidden"]:
        parts.append(f"{s['hidden']} hidden tiles")
    b = s["bbox"]
    where = (f"z={b['z']} x={b['x0']}..{b['x1']} "
             f"y={b['y0']}..{b['y1']} ({layer})")
    return (", ".join(parts) or "open ground") + " — " + where


# -- block scan ----------------------------------------------------------

def _rle_decode(runs: list[int], total: int) -> set[int]:
    """Decode a run-length bitmask (runs alternate 0/1, starting 0).

    Returns the set of indices whose bit is 1.
    """
    out: set[int] = set()
    idx = 0
    value = 0
    for run in runs:
        if value == 1:
            out.update(range(idx, idx + run))
        idx += run
        value = 1 - value
    if idx != total:
        raise ValueError(
            f"RLE length {idx} != total blocks {total}")
    return out


def scan_blocks(client: DFHackClient) -> dict[str, Any]:
    """Run the full block scan (scan.lua). Returns the decoded masks.

    The scan is SLOW (~10-15 s on a 192x192x197 map) and is cached
    by the caller (the HTTP layer); it is never run per tick.
    """
    out = _helper_or_fail(client, "scan.lua", {}, timeout=120.0)
    s = out["scan"]
    total = s["total_blocks"]
    return {
        "x_blocks": s["x_blocks"], "y_blocks": s["y_blocks"],
        "z_count": s["z_count"],
        "x_count": s["x_count"], "y_count": s["y_count"],
        "total_blocks": total, "open_blocks": s["open_blocks"],
        "open": _rle_decode(s["open_rle"], total),
        "up": _rle_decode(s["up_rle"], total),
        "down": _rle_decode(s["down_rle"], total),
        "scan_seconds": s["scan_seconds"],
    }


# -- area derivation -----------------------------------------------------

def _block_index(bx: int, by: int, bz: int, xb: int, yb: int) -> int:
    return (bz * yb + by) * xb + bx


def _block_xyz(idx: int, xb: int, yb: int) -> tuple[int, int, int]:
    bz, rem = divmod(idx, xb * yb)
    by, bx = divmod(rem, xb)
    return bx, by, bz


def _flood_regions(scan: dict[str, Any]) -> list[set[int]]:
    """Flood-fill open blocks into connected regions (design §3.3).

    Horizontal neighbours (same z) connect when both are open.
    A vertical step connects only when the lower block has an
    up-stair/ramp or the upper block has a down-stair/ramp — a floor
    above a floor is a ceiling, not a passage.
    """
    open_set = scan["open"]
    up, down = scan["up"], scan["down"]
    xb, yb, zc = scan["x_blocks"], scan["y_blocks"], scan["z_count"]
    seen: set[int] = set()
    regions: list[set[int]] = []
    for start in sorted(open_set):
        if start in seen:
            continue
        region: set[int] = set()
        queue: deque[int] = deque([start])
        seen.add(start)
        while queue:
            idx = queue.popleft()
            region.add(idx)
            bx, by, bz = _block_xyz(idx, xb, yb)
            # Horizontal neighbours.
            for nbx, nby, nbz in (
                    (bx - 1, by, bz), (bx + 1, by, bz),
                    (bx, by - 1, bz), (bx, by + 1, bz)):
                if 0 <= nbx < xb and 0 <= nby < yb:
                    n = _block_index(nbx, nby, nbz, xb, yb)
                    if n in open_set and n not in seen:
                        seen.add(n)
                        queue.append(n)
            # Vertical neighbours (stair rule).
            if bz + 1 < zc:
                n = _block_index(bx, by, bz + 1, xb, yb)
                if (n in open_set and n not in seen
                        and (idx in up or n in down)):
                    seen.add(n)
                    queue.append(n)
            if bz - 1 >= 0:
                n = _block_index(bx, by, bz - 1, xb, yb)
                if (n in open_set and n not in seen
                        and (n in up or idx in down)):
                    seen.add(n)
                    queue.append(n)
        regions.append(region)
    return regions


def _region_bbox(region: set[int], xb: int, yb: int) -> dict[str, int]:
    xs, ys, zs = [], [], []
    for idx in region:
        bx, by, bz = _block_xyz(idx, xb, yb)
        xs.append(bx)
        ys.append(by)
        zs.append(bz)
    return {"x0": min(xs) * 16, "y0": min(ys) * 16, "z0": min(zs),
            "x1": max(xs) * 16 + 15, "y1": max(ys) * 16 + 15,
            "z1": max(zs)}


def _buildings_in(region: set[int], buildings: list[dict[str, Any]],
                  xb: int, yb: int) -> list[dict[str, Any]]:
    """Buildings whose centre block is in the region."""
    out = []
    for b in buildings:
        cx, cy, cz = b["center"]
        bx, by = cx // 16, cy // 16
        if _block_index(bx, by, cz, xb, yb) in region:
            out.append(b)
    return out


def _label_region(region: set[int], bbox: dict[str, int],
                  buildings: list[dict[str, Any]],
                  surface_z: int) -> tuple[str, str, str, float]:
    """Label one region: (kind, name, purpose, confidence).

    Stockpiles and farms are authoritative (from the building list);
    rooms are heuristic (bed + door = bedroom, tables + chairs =
    dining hall, same-type workshops = workshop area) and carry a
    confidence below 1. Caverns are a size + depth heuristic.
    """
    types = [b["type"] for b in buildings]
    subtypes = [b.get("subtype") for b in buildings
                if b.get("subtype")]
    blocks = len(region)
    below = bbox["z1"] < surface_z
    # Stockpile (authoritative).
    if "Stockpile" in types:
        return ("stockpile", "Stockpile", "storage", 1.0)
    # Farm (authoritative).
    if "FarmPlot" in types:
        return ("farm", "Farm", "growing crops", 1.0)
    if buildings:
        has_bed = "Bed" in types
        has_door = "Door" in types
        has_table = "Table" in types
        has_chair = "Chair" in types
        workshops = [s for s in subtypes if s]
        if has_bed and has_door:
            return ("room", "Bedroom",
                    "sleeping quarters; bed and door", 0.7)
        if has_table and has_chair:
            return ("room", "Dining Hall",
                    "eating and socialising; tables and chairs", 0.7)
        if workshops:
            from collections import Counter
            common, n = Counter(workshops).most_common(1)[0]
            name = (f"{common} Workshop" if n == 1
                    else f"{common} Workshops")
            return ("room", name,
                    f"workshops ({', '.join(sorted(set(workshops)))})",
                    0.7)
        if has_bed:
            return ("room", "Bedroom",
                    "sleeping quarters; bed, no door yet", 0.6)
        return ("room", "Room",
                "furnished space (" + ", ".join(sorted(set(types)))
                + ")", 0.6)
    # No buildings: cavern, surface, stairwell, or plain dug space.
    if below and blocks > 8:
        return ("cavern", "Cavern",
                "open underground space, unclaimed", 0.6)
    if not below:
        return ("surface", "Surface",
                "the embark surface, open ground", 0.9)
    z_span = bbox["z1"] - bbox["z0"]
    if z_span >= 2 and blocks <= 2 * (z_span + 1):
        return ("stairwell", "Stairwell",
                "vertical passage between levels", 0.6)
    return ("dug", "Dug Space",
            "dug-out space, no purpose yet", 0.6)


def derive_areas(state: dict[str, Any],
                 scan: dict[str, Any]) -> dict[str, Any]:
    """Derive areas + the connectivity graph (design §3.5).

    ``state`` is an observe snapshot (needs the buildings, units and
    map sections; status for the tick). ``scan`` is scan_blocks().
    Returns {"areas": [...], "graph": {...}, "derived_at_tick", ...}.
    Areas are sorted by relevance (has buildings, then size) so the
    per-tick snapshot can take the first 15.
    """
    xb, yb = scan["x_blocks"], scan["y_blocks"]
    buildings = ((state.get("buildings") or {}).get("list")) or []
    units = ((state.get("units") or {}).get("citizens")) or []
    surface_z = _surface_z(state, scan)
    centre = _fort_centre(state)
    centre_block = None
    if centre is not None:
        centre_block = _block_index(centre[0] // 16, centre[1] // 16,
                                    centre[2], xb, yb)
    regions = _flood_regions(scan)
    # Drop isolated single-block pockets with no buildings: a lone
    # open block inside solid rock is a natural pocket, not an area
    # the agent can use (and the design's cavern threshold is >500
    # open tiles — one block holds at most 256). A dug room is never
    # an isolated single block: if it is connected to the fort it is
    # part of a larger region, and if it holds a building it is kept.
    regions = [r for r in regions
               if len(r) >= 2 or centre_block in r
               or _buildings_in(r, buildings, xb, yb)]
    # Label every region, then order by relevance for stable ids.
    labelled = []
    for region in regions:
        bbox = _region_bbox(region, xb, yb)
        in_region = _buildings_in(region, buildings, xb, yb)
        if centre_block is not None and centre_block in region:
            # The region holding the fort centre IS the surface,
            # whatever its z-range (the hills rise above the embark
            # level; a z heuristic alone would mislabel them).
            kind, name, purpose, conf = (
                "surface", "Surface",
                "the embark surface, open ground", 0.9)
        else:
            kind, name, purpose, conf = _label_region(
                region, bbox, in_region, surface_z)
        labelled.append((region, bbox, in_region, kind, name,
                         purpose, conf))
    # Relevance: regions with buildings first, then by size.
    labelled.sort(key=lambda t: (len(t[2]) > 0, len(t[0])),
                  reverse=True)
    areas: list[dict[str, Any]] = []
    region_of_block: dict[int, str] = {}
    surface_blocks: list[int] = []
    for i, (region, bbox, in_region, kind, name, purpose,
            conf) in enumerate(labelled):
        area_id = f"area_{i + 1:04d}"
        for idx in region:
            region_of_block[idx] = area_id
        if kind == "surface":
            # The surface region's block set drives the survey's
            # reachability proxy (water/magma on open surface ground,
            # mineral veins touching it). Sorted list: small enough
            # (~600 ints) to ship in the response.
            surface_blocks = sorted(region)
        from collections import Counter
        contents: dict[str, Any] = {}
        if in_region:
            by_type: Counter[str] = Counter()
            for b in in_region:
                label = b.get("subtype") or b["type"]
                by_type[label] += 1
            contents["buildings"] = [
                f"{t.lower()} x{n}" for t, n in
                sorted(by_type.items())]
        units_present = 0
        for u in units:
            pos = u.get("pos") or []
            if (len(pos) == 3 and bbox["x0"] <= pos[0] <= bbox["x1"]
                    and bbox["y0"] <= pos[1] <= bbox["y1"]
                    and bbox["z0"] <= pos[2] <= bbox["z1"]):
                units_present += 1
        if units_present:
            contents["units_present"] = units_present
        areas.append({
            "id": area_id, "name": name, "kind": kind,
            "bbox": bbox, "purpose": purpose,
            "contents": contents, "connections": [],
            "blocks": len(region),
            "confidence": conf,
            "derived_at_tick": _tick(state),
            "stale": False,
        })
    # Graph: adjacent regions (an open block next to an open block in
    # another region, under the same stair rule as the flood-fill).
    graph: dict[str, set[str]] = {a["id"]: set() for a in areas}
    open_set, up, down = scan["open"], scan["up"], scan["down"]
    zc = scan["z_count"]
    for idx in sorted(open_set):
        a = region_of_block.get(idx)
        if a is None:
            continue
        bx, by, bz = _block_xyz(idx, xb, yb)
        neighbours = []
        for nbx, nby, nbz in (
                (bx - 1, by, bz), (bx + 1, by, bz),
                (bx, by - 1, bz), (bx, by + 1, bz)):
            if 0 <= nbx < xb and 0 <= nby < yb:
                neighbours.append(
                    _block_index(nbx, nby, nbz, xb, yb))
        if bz + 1 < zc and (idx in up
                            or _block_index(bx, by, bz + 1, xb, yb)
                            in down):
            neighbours.append(_block_index(bx, by, bz + 1, xb, yb))
        if bz - 1 >= 0 and (idx in down
                            or _block_index(bx, by, bz - 1, xb, yb)
                            in up):
            neighbours.append(_block_index(bx, by, bz - 1, xb, yb))
        for n in neighbours:
            if n in open_set:
                b = region_of_block.get(n)
                if b is not None and b != a:
                    graph[a].add(b)
                    graph[b].add(a)
    for area in areas:
        area["connections"] = sorted(graph[area["id"]])
    return {
        "areas": areas,
        "graph": {k: sorted(v) for k, v in graph.items()},
        "surface_blocks": surface_blocks,
        "derived_at_tick": _tick(state),
        "surface_z": surface_z,
        "region_count": len(areas),
        "scan_seconds": scan.get("scan_seconds"),
    }


def _surface_z(state: dict[str, Any],
               scan: dict[str, Any]) -> int:
    """The embark ground level: the lowest z any citizen stands on.

    Citizens stand on the ground; the lowest one is at the embark
    level (the wagon's z). The hills rise above it, so the highest
    open z is the hilltop, not the surface — the old heuristic
    (highest z with >25% open) returned the hilltop and mislabelled
    the hills as underground. Falls back to that heuristic when
    there are no citizen positions.
    """
    units = ((state.get("units") or {}).get("citizens")) or []
    zs = [u["pos"][2] for u in units
          if len(u.get("pos") or []) == 3]
    if zs:
        return min(zs)
    xb, yb, zc = scan["x_blocks"], scan["y_blocks"], scan["z_count"]
    open_set = scan["open"]
    per_z = [0] * zc
    for idx in open_set:
        per_z[_block_xyz(idx, xb, yb)[2]] += 1
    threshold = (xb * yb) // 4
    for z in range(zc - 1, -1, -1):
        if per_z[z] >= threshold:
            return z
    return zc - 1


def _fort_centre(state: dict[str, Any]) -> Optional[tuple[int, int, int]]:
    """The fort centre: the first citizen's position, if known."""
    units = ((state.get("units") or {}).get("citizens")) or []
    for u in units:
        pos = u.get("pos") or []
        if len(pos) == 3:
            return (pos[0], pos[1], pos[2])
    return None


def _tick(state: dict[str, Any]) -> Optional[int]:
    status = state.get("status") or {}
    tick = status.get("year_tick")
    return tick if isinstance(tick, int) else None


# -- queries -------------------------------------------------------------

def resolve_area(areas: list[dict[str, Any]],
                 ref: str) -> Optional[dict[str, Any]]:
    """Find an area by id (area_0007) or by name (case-insensitive)."""
    ref = ref.strip()
    for a in areas:
        if a["id"] == ref:
            return a
    lowered = ref.lower()
    for a in areas:
        if a["name"].lower() == lowered:
            return a
    return None


def find_path(graph: dict[str, list[str]], a: str,
              b: str) -> Optional[list[str]]:
    """BFS over the area graph: a list of area ids from a to b."""
    if a == b:
        return [a]
    if a not in graph or b not in graph:
        return None
    prev: dict[str, Optional[str]] = {a: None}
    queue: deque[str] = deque([a])
    while queue:
        cur = queue.popleft()
        for nxt in graph.get(cur, []):
            if nxt not in prev:
                prev[nxt] = cur
                if nxt == b:
                    path = [b]
                    while prev[path[-1]] is not None:
                        path.append(prev[path[-1]])  # type: ignore[arg-type]
                    return list(reversed(path))
                queue.append(nxt)
    return None


def area_summary(areas: list[dict[str, Any]],
                 max_areas: int = 15) -> list[str]:
    """One line per area (the per-tick snapshot's area list)."""
    lines = []
    for a in areas[:max_areas]:
        b = a["bbox"]
        lines.append(
            f"{a['id']} {a['name']} ({a['kind']}) "
            f"[{b['x0']},{b['y0']},z{b['z0']}..{b['z1']}] "
            f"{a['purpose']}")
    return lines
