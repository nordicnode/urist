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

from .actions import _helper_or_fail

__all__ = [
    "LEGEND", "SLICE_LAYERS", "MAX_SLICE", "FULL_SLICE",
    "estimate_tokens", "render_slice", "scan_blocks",
    "derive_areas", "find_path", "resolve_area", "area_summary",
    "describe_area", "area_descriptions", "render_overview",
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
    "F": "fort centre (the embark point, where the wagon stands)",
    " ": "open air, void, or hidden tile (blank)",
}

SLICE_LAYERS = ("terrain", "water", "designations", "buildings", "units")
MAX_SLICE = 64          # max 64x64 tiles per call (design §3.4)
FULL_SLICE = 192        # a full z-level, explicit on-demand only


def estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token (design §1e anchor)."""
    return max(1, len(text) // 4)


def _labeled_grid(grid: list[str], x0: int, y0: int) -> list[str]:
    """The grid with coordinate rulers (standing directive 2026-11-26).

    Two header lines label every column (tens, then ones of the x
    coordinate) and every row is prefixed with its y coordinate, so
    a tile can be located by reading the grid instead of counting
    characters. The raw ``grid`` is kept alongside for parsers.
    """
    w = len(grid[0]) if grid else 0
    tens = "".join(str((x0 + i) // 10 % 10) for i in range(w))
    ones = "".join(str((x0 + i) % 10) for i in range(w))
    out = ["    " + tens, "    " + ones]
    for j, row in enumerate(grid):
        out.append(f"{y0 + j:3d} {row}")
    return out


def _adjacent_text(which: str, c: Optional[dict[str, Any]]) -> str:
    """Plain words for the level directly above/below a slice.

    ``c`` is the Lua adjacent-level count ({z, open, solid, water,
    magma, hidden}) or None when out of range. Ends with a hazard
    clause when water or magma sits in the adjacent level, so the
    agent is told before it digs.
    """
    if c is None:
        return f"{which}: nothing — the map ends here."
    parts = []
    if c["solid"]:
        parts.append(f"{c['solid']} solid rock")
    if c["open"]:
        parts.append(f"{c['open']} open tiles")
    if c["water"]:
        parts.append(f"{c['water']} water tiles")
    if c["magma"]:
        parts.append(f"{c['magma']} magma tiles")
    if c["hidden"]:
        parts.append(f"{c['hidden']} hidden (unrevealed) tiles")
    base = (f"{which} (z{c['z']}): "
            + (", ".join(parts) if parts else "empty"))
    hazards = []
    if c["water"]:
        hazards.append(
            "Water sits directly " + which.lower()
            + " — digging through the floor here will let water in.")
    if c["magma"]:
        hazards.append(
            "Magma sits directly " + which.lower()
            + " — digging through the floor here will breach lava.")
    if c["open"] and not c["solid"] and not c["water"] \
            and not c["magma"]:
        hazards.append(
            "Open space directly " + which.lower()
            + " — digging down here drops into open space.")
    total = (c["solid"] + c["open"] + c["water"] + c["magma"]
             + c["hidden"])
    if c["hidden"] and c["hidden"] * 2 >= total:
        # The level is mostly unrevealed rock: the slice cannot
        # say what is in it. Route the agent to the column probe,
        # which reads the geology even on unrevealed tiles.
        hazards.append(
            "This level is mostly unrevealed — use /v1/column at "
            "a spot to see what is in it before digging.")
    return base + (". " + " ".join(hazards) if hazards else ".")


def render_slice(client: DFHackClient, x0: int, y0: int, z: int,
                 x1: int, y1: int, layer: str = "terrain",
                 allow_full: bool = False,
                 landmarks: Optional[list[dict[str, Any]]] = None
                 ) -> dict[str, Any]:
    """Render one slice (design §3.4). Returns the slice + its cost.

    Bounds: at most 64x64 tiles unless ``allow_full`` (then at most
    192x192, a full z-level, flagged expensive in the response).
    ``landmarks`` is a list of {x, y, char, what} (e.g. the fort
    centre) drawn onto the grid and listed in ``markers``.
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
    grid = list(out["slice"]["grid"])
    markers = list(out["slice"]["markers"])
    # Landmarks overlay onto the grid (and the labeled grid below).
    for lm in landmarks or []:
        lx, ly = lm.get("x"), lm.get("y")
        lz = lm.get("z")
        if (isinstance(lx, int) and isinstance(ly, int)
                and x0 <= lx <= x1 and y0 <= ly <= y1
                and (lz is None or lz == z)):
            row = list(grid[ly - y0])
            row[lx - x0] = lm.get("char", "F")
            grid[ly - y0] = "".join(row)
            markers.append({"char": lm.get("char", "F"), "x": lx,
                            "y": ly, "what": lm.get("what", "landmark")})
    text = "\n".join(grid)
    ms = int((time.monotonic() - t0) * 1000)
    above_text = _adjacent_text("Above", out["slice"].get("above"))
    below_text = _adjacent_text("Below", out["slice"].get("below"))
    return {
        "bbox": out["slice"]["bbox"], "layer": layer,
        "grid": grid, "grid_labeled": _labeled_grid(grid, x0, y0),
        "legend": LEGEND,
        "markers": markers,
        "counts": out["slice"]["counts"],
        "hidden": out["slice"]["hidden"],
        "above": out["slice"].get("above"),
        "below": out["slice"].get("below"),
        "above_text": above_text, "below_text": below_text,
        "cost": {
            "tokens": estimate_tokens(text),
            "ms": ms, "lua_ms": out["slice"]["cost_ms"],
            "expensive": allow_full,
        },
        "summary": _slice_summary(out["slice"], layer)
        + f" {below_text} {above_text}",
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
                 scan: dict[str, Any],
                 embark_z: Optional[int] = None) -> dict[str, Any]:
    """Derive areas + the connectivity graph (design §3.5).

    ``state`` is an observe snapshot (needs the buildings, units and
    map sections; status for the tick). ``scan`` is scan_blocks().
    ``embark_z`` pins the surface level (see _surface_z); without
    it the citizen-minimum heuristic is used. Returns {"areas":
    [...], "graph": {...}, "derived_at_tick", ...}. Areas are
    sorted by relevance (has buildings, then size) so the per-tick
    snapshot can take the first 15.
    """
    xb, yb = scan["x_blocks"], scan["y_blocks"]
    buildings = ((state.get("buildings") or {}).get("list")) or []
    units = ((state.get("units") or {}).get("citizens")) or []
    surface_z = _surface_z(state, scan, embark_z=embark_z)
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
            # (~600 ints) to ship in the response. UNION, not
            # overwrite (2026-11-27, external review Table 5 row 7):
            # with several surface regions (hilltop plus
            # fort-centre) the old assignment let whichever was
            # processed last win, and the survey ran its proxy
            # against the wrong blocks.
            surface_blocks = sorted(set(surface_blocks) | set(region))
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
    # Plain-words descriptions (standing directive 2026-11-26):
    # what it is, where, how big, what is in it, how to get there,
    # what is above and below it. The survey is not available here,
    # so the vertical facts are graph-based; the server re-describes
    # with the cached survey when one exists.
    for area in areas:
        area["description"] = describe_area(
            area, areas, graph, survey=None, fort_centre=centre)
    return {
        "areas": areas,
        "graph": {k: sorted(v) for k, v in graph.items()},
        "surface_blocks": surface_blocks,
        "derived_at_tick": _tick(state),
        "surface_z": surface_z,
        "region_count": len(areas),
        "scan_seconds": scan.get("scan_seconds"),
    }


def describe_area(area: dict[str, Any],
                  areas: list[dict[str, Any]],
                  graph: Optional[dict[str, list[str]]] = None,
                  survey: Optional[dict[str, Any]] = None,
                  fort_centre: Optional[tuple[int, int, int]] = None
                  ) -> str:
    """Plain-words description of one area (standing directive).

    What it is, where it is, how big, what is in it, how to get
    there from the Surface, and what is above and below it. The
    above/below comes from neighbouring areas in the graph when one
    sits directly above or below, and from the survey's vertical
    facts (magma, aquifer, first cavern) otherwise. Nothing is
    claimed that the scan and the survey do not support.
    """
    from .survey import direction_words

    b = area["bbox"]
    name, kind = area["name"], area["kind"]
    by_id = {a["id"]: a for a in areas}
    sentences = [f"The {name} ({kind}): {area['purpose']}."]
    # Where + how big.
    centre = ((b["x0"] + b["x1"]) // 2, (b["y0"] + b["y1"]) // 2,
              (b["z0"] + b["z1"]) // 2)
    where = (f"It spans x{b['x0']}..x{b['x1']}, "
             f"y{b['y0']}..y{b['y1']}, z{b['z0']}..z{b['z1']} — "
             f"{area['blocks']} blocks "
             f"(about {area['blocks'] * 256} tiles) of open space.")
    if fort_centre is not None:
        if (b["x0"] <= fort_centre[0] <= b["x1"]
                and b["y0"] <= fort_centre[1] <= b["y1"]
                and b["z0"] <= fort_centre[2] <= b["z1"]):
            where += " It holds the fort centre."
        else:
            where += (" It is "
                      + direction_words(fort_centre, centre)
                      + " of the fort centre.")
    sentences.append(where)
    # What is in it.
    contents = area.get("contents") or {}
    held = []
    if contents.get("buildings"):
        held.append("buildings: "
                    + ", ".join(contents["buildings"]))
    if contents.get("units_present"):
        n = contents["units_present"]
        held.append(f"{n} dwarf{'s' if n != 1 else ''} inside")
    if held:
        sentences.append("It holds " + "; ".join(held) + ".")
    else:
        sentences.append("Nothing is built in it yet.")
    # How to get there from the Surface.
    if kind == "surface":
        sentences.append("This is where the fort starts.")
    elif graph is not None:
        surface = next((a for a in areas if a["kind"] == "surface"),
                       None)
        path = None
        if surface is not None:
            path = find_path(graph, surface["id"], area["id"])
        if path:
            names = [by_id[i]["name"] for i in path]
            sentences.append("From the Surface: "
                             + " → ".join(names) + ".")
        else:
            sentences.append(
                "From the Surface: no path — it is sealed off by "
                "solid rock; dig a stairwell or tunnel to link them.")
    # Above.
    def _overlaps(a: dict[str, int], c: dict[str, int]) -> bool:
        return (a["x0"] <= c["x1"] and c["x0"] <= a["x1"]
                and a["y0"] <= c["y1"] and c["y0"] <= a["y1"])
    above_area = None
    below_area = None
    for other in areas:
        if other["id"] == area["id"]:
            continue
        ob = other["bbox"]
        if not _overlaps(b, ob):
            continue
        if ob["z0"] > b["z1"] and (
                above_area is None
                or ob["z0"] < above_area["bbox"]["z0"]):
            above_area = other
        if ob["z1"] < b["z0"] and (
                below_area is None
                or ob["z1"] > below_area["bbox"]["z1"]):
            below_area = other
    if kind == "surface":
        sentences.append("Above it is open sky.")
    elif above_area is not None:
        ab = above_area["bbox"]
        sentences.append(
            f"Above it is the {above_area['name']} "
            f"(z{ab['z0']}..z{ab['z1']}).")
    else:
        sentences.append(
            "Above it is solid rock (unrevealed ground between "
            "here and the surface).")
    # Below: a neighbouring area first, then the survey's vertical
    # facts (first cavern, aquifer, magma). These are not mutually
    # exclusive: the surface can sit above a cavern AND above the
    # magma sea, and the agent needs both facts — so the survey
    # sentences are added even when a neighbouring area is named.
    said_below = False
    if below_area is not None:
        bb = below_area["bbox"]
        sentences.append(
            f"Below it is the {below_area['name']} "
            f"(z{bb['z0']}..z{bb['z1']}).")
        said_below = True
    if survey is not None:
        vert = survey.get("vertical") or {}
        z0 = b["z0"]
        cavern_top = vert.get("first_cavern_top_z")
        if (cavern_top is not None and z0 > cavern_top
                and kind != "cavern"
                and (below_area is None
                     or below_area["kind"] != "cavern")):
            sentences.append(
                f"The first cavern starts {z0 - cavern_top} levels "
                f"below (top at z{cavern_top}).")
            said_below = True
        aq = survey.get("aquifer") or {}
        levels = aq.get("levels") or []
        if levels:
            lo = min(l["z"] for l in levels)
            hi = max(l["z"] for l in levels)
            zrange = f"z{lo}" if lo == hi else f"z{lo}..z{hi}"
            if hi < z0:
                sentences.append(
                    f"An aquifer layer sits at {zrange}, "
                    f"{z0 - hi} levels below — digging into it "
                    f"will leak water.")
                said_below = True
            elif lo <= z0 <= hi:
                sentences.append(
                    f"This area sits inside the aquifer layer "
                    f"({zrange}) — digging here will leak water.")
                said_below = True
        magma_top = vert.get("magma_top_z")
        if magma_top is not None and z0 > magma_top:
            if below_area is None:
                sentences.append(
                    f"Below it is solid rock for "
                    f"{z0 - magma_top} levels, then the magma sea "
                    f"(top at z{magma_top}).")
            else:
                # An area sits between this one and the magma, so
                # do not claim solid rock all the way down.
                sentences.append(
                    f"The magma sea sits {z0 - magma_top} levels "
                    f"below this area (top at z{magma_top}).")
            said_below = True
    if not said_below:
        sentences.append(
            "Below it is solid rock as far as the scan shows.")
    if area.get("confidence", 1.0) < 1.0:
        sentences.append(
            f"This label is derived from the buildings and shape "
            f"(confidence {area['confidence']}), not a name the "
            f"game gives it.")
    return " ".join(sentences)


def area_descriptions(areas: list[dict[str, Any]],
                      graph: Optional[dict[str, list[str]]] = None,
                      survey: Optional[dict[str, Any]] = None,
                      fort_centre: Optional[tuple[int, int, int]] = None
                      ) -> dict[str, str]:
    """{area_id: plain-words description} for a whole area list."""
    return {a["id"]: describe_area(a, areas, graph, survey,
                                   fort_centre) for a in areas}


def render_overview(scan: dict[str, Any],
                    survey: Optional[dict[str, Any]] = None,
                    fort: Optional[tuple[int, int, int]] = None
                    ) -> dict[str, Any]:
    """Coarse block-level overview (standing directive 2026-11-26).

    Shape-at-a-glance: a side cross-section through the fort (the
    x-z plane at the fort's y) and a top-down view of the fort's
    level. One char per 16x16 column, over a 16-level band for the
    cross-section. A DF map block is 16x16 tiles and ONE z-level
    thick, so the scan is indexed by tile z (0..z_count-1) — the
    cross-section aggregates 16 consecutive tile-z levels into one
    band row, and the top-down is the fort's own tile z (not a
    16-level block). A band char means that class is present
    somewhere in the band: '!' magma, '~' water, '.' open, '#'
    solid rock, 'F' the fort's column. Built from the cached block
    scan + the survey's water/magma block sets — no game read, so
    it costs nothing live.
    """
    xb, yb, zc = (scan["x_blocks"], scan["y_blocks"],
                  scan["z_count"])
    open_set = scan["open"]
    water_idx = set((survey or {}).get("water_block_indices") or [])
    magma_idx = set((survey or {}).get("magma_block_indices") or [])
    fort = fort or (97, 97, 175)
    fbx, fby = fort[0] // 16, fort[1] // 16
    # fort[2] is a TILE z; the band holding it is fort[2] // 16.
    fort_z = fort[2]
    fort_band = fort_z // 16
    z_bands = (zc + 15) // 16

    def _band_char(bx: int, band: int) -> str:
        # The char for one (x-block, band) column at the fort's
        # y-block. Magma beats water beats open beats solid, over
        # the 16 tile-z levels in the band — a hazard anywhere in
        # the band must show.
        z0 = band * 16
        z1 = min(z0 + 15, zc - 1)
        has_open = has_water = has_magma = False
        for z in range(z0, z1 + 1):
            idx = _block_index(bx, fby, z, xb, yb)
            if idx in magma_idx:
                has_magma = True
            elif idx in water_idx:
                has_water = True
            elif idx in open_set:
                has_open = True
        if has_magma:
            return "!"
        if has_water:
            return "~"
        if has_open:
            return "."
        return "#"

    def _top_char(bx: int, by: int) -> str:
        # One tile-z level: the fort's own level.
        idx = _block_index(bx, by, fort_z, xb, yb)
        if bx == fbx and by == fby:
            return "F"
        if idx in water_idx:
            return "~"
        if idx in magma_idx:
            return "!"
        if idx in open_set:
            return "."
        return "#"

    # Cross-section: x across, z down (top of the map first).
    cross: list[str] = []
    for band in range(z_bands - 1, -1, -1):
        row = "".join(
            "F" if (band == fort_band and bx == fbx)
            else _band_char(bx, band)
            for bx in range(xb))
        z_hi = min(band * 16 + 15, zc - 1)
        label = f"z{band * 16}..z{z_hi}".ljust(10)
        cross.append(f"{label} {row}")
    # Top-down at the fort's level: y down, x across.
    top: list[str] = []
    for by in range(yb):
        row = "".join(
            _top_char(bx, by)
            for bx in range(xb))
        label = f"y{by * 16}..y{by * 16 + 15}".ljust(10)
        top.append(f"{label} {row}")
    text = "\n".join(cross + [""] + top)
    return {
        "cross_section": cross,
        "top_down": top,
        "fort": list(fort),
        "legend": {".": "open block", "#": "solid rock block",
                   "~": "water block", "!": "magma block",
                   "F": "the fort's block"},
        "summary": (
            f"Cross-section through the fort at y={fort[1]} "
            f"(x across, z down, one char per 16x16 column over "
            f"a 16-level band) and a top-down view of the fort's "
            f"level (z{fort[2]}). '.' open, '#' solid rock, '~' "
            f"water, '!' magma, 'F' the fort. A band char means "
            f"that class is present somewhere in the band. The "
            f"cross-section shows the shape of the world: the "
            f"surface band at the top, solid rock in the middle, "
            f"open cavern bands deep down, and magma at the "
            f"bottom."),
        "cost": {"tokens": estimate_tokens(text), "ms": 0},
    }


def _surface_z(state: dict[str, Any],
               scan: dict[str, Any],
               embark_z: Optional[int] = None) -> int:
    """The embark ground level.

    When ``embark_z`` is given (the lowest citizen z at the fort's
    earliest sampled tick, from the store — see
    ``Store.earliest_unit_z``), it IS the answer: the embark level
    is a fixed property of the world, and the citizens' minimum z
    drifts down as soon as any miner works below the surface (the
    old code returned that minimum, so the fort's own phase-1 plan
    digging down degraded region labeling and the 'on the surface'
    attention test over time; 2026-11-27, external review Table 5
    row 8). The modal citizen z is no substitute — verified live on
    Erushtathtat, the modal z is 180 (the hilltop three citizens
    stand on) while the embark level is 175.

    Without it, fall back to the old heuristic: the lowest z any
    citizen stands on (citizens stand on the ground; the lowest one
    is at the embark level, the wagon's z). The hills rise above
    it, so the highest open z is the hilltop, not the surface —
    the old heuristic (highest z with >25% open) returned the
    hilltop and mislabelled the hills as underground. Falls back
    to that heuristic when there are no citizen positions.
    """
    if isinstance(embark_z, int):
        return embark_z
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
