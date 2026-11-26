"""Resource survey: bodies, veins, nearest, vertical (design §5).

Builds on ``lua/survey.lua`` (one full block scan, ~13 s Lua, cached,
never per tick). The Lua side emits sparse per-block aggregates; this
module flood-fills them into bodies/veins, measures the nearest of
each kind from the fort centre in 3D, and states everything in plain
words — "nearest X at (coords), distance N, quantity M" — so an agent
can answer "where is the nearest water / iron ore?" directly from the
response, without geometry.

Vertical awareness (standing directive 2026-11-26): the survey also
reports depth to magma, depth to the first cavern, aquifer layers
(which z-levels, light/heavy per the embark warning — never inferred
from tile data), and nearest water/lava by 3D distance, not just
horizontal distance.

Read safety (design §8): ``run_survey`` is only ever called inside a
``paused_read`` window, by the HTTP route.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Optional

from dfhack_rpc import DFHackClient

from .actions import _helper_or_fail

__all__ = [
    "FORT_CENTRE", "SEASON_TICKS", "run_survey", "build_survey",
    "survey_summary", "describe_body", "direction_words",
    "chebyshev3d",
]

# The embark point, recorded at the Erushtathtat embark (phase 4
# fixtures: fort centre ~(97,97,175), dig box (95,95,174)-(96,96,174),
# build site (102,92)). The wagon stands here; the citizens have
# since wandered across the surface for woodcutting, so no live
# citizen position is a stable anchor. The wagon itself is not in
# ``world.buildings.all`` (verified live 2026-11-26: zero buildings),
# so the recorded embark point is the anchor, not a live lookup.
FORT_CENTRE: tuple[int, int, int] = (97, 97, 175)

# One in-game season in ticks (design §7: a survey older than one
# season is stale).
SEASON_TICKS = 33600

# The site's aquifer is "light" per the embark warning (accepted at
# the Erushtathtat embark and at the Dakasdoma embark before it).
# Light vs heavy is NOT measurable from tile data; the label is
# reported with the measured z-levels, never inferred.
AQUIFER_KIND = "light (per the embark warning)"


def run_survey(client: DFHackClient,
               fort: tuple[int, int, int] = FORT_CENTRE) -> dict[str, Any]:
    """Run the full survey scan (survey.lua). SLOW (~25 s wall).

    Call only inside ``paused_read``. Returns the raw Lua dict.
    The fort centre is passed so per-species nearest plants are
    computed against the real fort, not a bbox.
    """
    out = _helper_or_fail(client, "survey.lua", {
        "fx": fort[0], "fy": fort[1], "fz": fort[2]}, timeout=180.0)
    return out["survey"]


def chebyshev3d(a: tuple[int, int, int],
                b: tuple[int, int, int]) -> int:
    """3D Chebyshev distance in tiles (diagonals cost 1)."""
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def direction_words(frm: tuple[int, int, int],
                    to: tuple[int, int, int]) -> str:
    """Plain-words direction from ``frm`` to ``to``.

    DF axes: x+ is east, y+ is south (y grows downward on the map),
    z+ is up. Returns e.g. "65 tiles east and 25 tiles south,
    1 level below" or "directly below, 62 levels down".
    """
    dx, dy, dz = to[0] - frm[0], to[1] - frm[1], to[2] - frm[2]
    def _tiles(n: int, word: str) -> str:
        return f"{n} tile {word}" if n == 1 else f"{n} tiles {word}"
    def _levels(n: int, word: str) -> str:
        return f"{n} level {word}" if n == 1 else f"{n} levels {word}"
    parts: list[str] = []
    if dx > 0:
        parts.append(_tiles(dx, "east"))
    elif dx < 0:
        parts.append(_tiles(-dx, "west"))
    if dy > 0:
        parts.append(_tiles(dy, "south"))
    elif dy < 0:
        parts.append(_tiles(-dy, "north"))
    if dz > 0:
        parts.append(_levels(dz, "above"))
    elif dz < 0:
        parts.append(_levels(-dz, "below"))
    if not parts:
        return "right here"
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _block_xyz(idx: int, xb: int, yb: int) -> tuple[int, int, int]:
    bz, rem = divmod(idx, xb * yb)
    by, bx = divmod(rem, xb)
    return bx, by, bz


def _block_index(bx: int, by: int, bz: int, xb: int, yb: int) -> int:
    return (bz * yb + by) * xb + bx


def _flood_bodies(entries: list[dict[str, Any]], xb: int,
                  yb: int, zc: int) -> list[dict[str, Any]]:
    """Flood-fill block entries (6-connectivity) into bodies.

    Each entry is {idx, tiles, ...}. Returns bodies with block sets,
    tile totals, max depth, and a tile-coordinate bbox.
    """
    by_idx = {e["idx"]: e for e in entries}
    seen: set[int] = set()
    bodies: list[dict[str, Any]] = []
    for start in sorted(by_idx):
        if start in seen:
            continue
        blocks: set[int] = set()
        queue: deque[int] = deque([start])
        seen.add(start)
        while queue:
            idx = queue.popleft()
            blocks.add(idx)
            bx, by, bz = _block_xyz(idx, xb, yb)
            for nbx, nby, nbz in (
                    (bx - 1, by, bz), (bx + 1, by, bz),
                    (bx, by - 1, bz), (bx, by + 1, bz),
                    (bx, by, bz - 1), (bx, by, bz + 1)):
                if 0 <= nbx < xb and 0 <= nby < yb and 0 <= nbz < zc:
                    n = _block_index(nbx, nby, nbz, xb, yb)
                    if n in by_idx and n not in seen:
                        seen.add(n)
                        queue.append(n)
        tiles = sum(by_idx[i]["tiles"] for i in blocks)
        max_depth = max((by_idx[i].get("max_depth", 0) for i in blocks),
                        default=0)
        xs, ys, zs = [], [], []
        for i in blocks:
            bx, by, bz = _block_xyz(i, xb, yb)
            xs.append(bx)
            ys.append(by)
            zs.append(bz)
        bodies.append({
            "blocks": blocks, "tiles": tiles, "max_depth": max_depth,
            "bbox": {"x0": min(xs) * 16, "y0": min(ys) * 16,
                     "z0": min(zs), "x1": max(xs) * 16 + 15,
                     "y1": max(ys) * 16 + 15, "z1": max(zs)},
        })
    bodies.sort(key=lambda b: b["tiles"], reverse=True)
    return bodies


def _nearest_point(fort: tuple[int, int, int],
                   bbox: dict[str, int]) -> tuple[int, int, int]:
    """The point in the bbox closest to the fort (clamped).

    Only an approximation when the body does not fill its bbox — use
    :func:`_nearest_block_point` for bodies, where the block set is
    known.
    """
    return (
        max(bbox["x0"], min(fort[0], bbox["x1"])),
        max(bbox["y0"], min(fort[1], bbox["y1"])),
        max(bbox["z0"], min(fort[2], bbox["z1"])),
    )


def _nearest_block_point(fort: tuple[int, int, int],
                         blocks: set[int], xb: int,
                         yb: int) -> tuple[int, int, int]:
    """The closest tile of any block in ``blocks`` to the fort.

    The point is clamped inside the nearest block's 16x16x1 tile
    box, so it is always a tile of the body itself — never a dry
    tile inside the body's bounding box.
    """
    best: Optional[tuple[int, int, int]] = None
    best_d: Optional[int] = None
    for idx in blocks:
        bx, by, bz = _block_xyz(idx, xb, yb)
        box = {"x0": bx * 16, "y0": by * 16, "z0": bz,
               "x1": bx * 16 + 15, "y1": by * 16 + 15, "z1": bz}
        p = _nearest_point(fort, box)
        d = chebyshev3d(fort, p)
        if best_d is None or d < best_d:
            best, best_d = p, d
    assert best is not None
    return best


def _finish_body(body: dict[str, Any], kind: str,
                 fort: tuple[int, int, int],
                 surface_blocks: Optional[set[int]],
                 name: str, xb: int, yb: int, zc: int) -> dict[str, Any]:
    """Add nearest/reachable/description to a flood-filled body."""
    bbox = body["bbox"]
    near = _nearest_block_point(fort, body["blocks"], xb, yb)
    dist = chebyshev3d(fort, near)
    # Reachable: a water/magma body is reachable on foot when one of
    # its blocks is open surface ground itself, or face-adjacent to
    # open surface ground (a dwarf standing next to the water can
    # drink from it — the water block itself need not be "open" in
    # the scan's sense, and a pond block usually is not: it holds
    # water over a brook bed, not a floor tile).
    reachable: Optional[bool] = None
    reach_note = "reachability unknown — no area data yet"
    if surface_blocks is not None:
        if kind in ("water", "magma"):
            reach = bool(body["blocks"] & surface_blocks)
            if not reach:
                for idx in body["blocks"]:
                    bx, by, bz = _block_xyz(idx, xb, yb)
                    for nbx, nby, nbz in (
                            (bx - 1, by, bz), (bx + 1, by, bz),
                            (bx, by - 1, bz), (bx, by + 1, bz),
                            (bx, by, bz - 1), (bx, by, bz + 1)):
                        if 0 <= nbx < xb and 0 <= nby < yb \
                                and 0 <= nbz < zc:
                            if _block_index(nbx, nby, nbz, xb, yb) \
                                    in surface_blocks:
                                reach = True
                                break
                    if reach:
                        break
            reachable = reach
            reach_note = (
                "reachable on foot — open water on the surface"
                if reachable else
                "not reachable on foot — no open water on the surface")
        else:
            # Mineral reachability is adjacency (a vein block
            # face-adjacent to open surface ground), computed by
            # build_survey with the real block grid — never claimed
            # here.
            reachable = None
            reach_note = ("reachability not yet computed — "
                          "needs the area data")
    rec = {
        "kind": kind, "name": name, "tiles": body["tiles"],
        "blocks": len(body["blocks"]),
        "max_depth": body["max_depth"],
        "bbox": bbox,
        "nearest": {"pos": list(near), "distance_tiles": dist,
                    "direction": direction_words(fort, near)},
        "reachable": reachable, "reachable_note": reach_note,
    }
    rec["description"] = describe_body(rec, fort)
    return rec


def describe_body(body: dict[str, Any],
                  fort: tuple[int, int, int]) -> str:
    """One plain-words sentence (plus a hazard clause) for a body."""
    b = body["bbox"]
    near = body["nearest"]
    where = (f"at ({near['pos'][0]}, {near['pos'][1]}, "
             f"z{near['pos'][2]})")
    span = ""
    if b["x1"] - b["x0"] > 15 or b["y1"] - b["y0"] > 15 \
            or b["z1"] != b["z0"]:
        span = (f", spanning x{b['x0']}..{b['x1']}, "
                f"y{b['y0']}..{b['y1']}, z{b['z0']}..{b['z1']}")
    depth = ""
    if body.get("max_depth"):
        depth = f", up to {body['max_depth']} deep (7 is full)"
    return (
        f"{body['name']}: {body['tiles']} tiles in "
        f"{body['blocks']} blocks{depth}, nearest point {where}, "
        f"{_away(near['distance_tiles'])}: "
        f"{near['direction']}{span}. "
        f"{body.get('reachable_note', '')}.")


def build_survey(raw: dict[str, Any],
                 fort: tuple[int, int, int] = FORT_CENTRE,
                 surface_blocks: Optional[set[int]] = None,
                 cavern_top_z: Optional[int] = None,
                 tick: Optional[int] = None) -> dict[str, Any]:
    """Build the interpretable survey from raw survey.lua output.

    ``surface_blocks`` is the set of block indices in the surface
    region (from the area derivation); it drives the reachability
    proxy. ``cavern_top_z`` is the highest z of the big cavern (from
    the areas); it gives the depth to the first cavern.
    """
    t0 = time.monotonic()
    xb, yb, zc = raw["x_blocks"], raw["y_blocks"], raw["z_count"]
    fort_z = fort[2]

    # Water bodies (pool = small, lake = large; surface vs underground
    # by whether the top is near the fort's level).
    waters = _flood_bodies(raw["water_blocks"], xb, yb, zc)
    water_bodies = []
    for w in waters:
        underground = w["bbox"]["z1"] < fort_z - 10
        name = ("underground lake" if underground else "pool")
        if w["tiles"] >= 1000:
            name = ("underground lake" if underground
                    else "lake")
        water_bodies.append(_finish_body(
            w, "water", fort, surface_blocks, name, xb, yb, zc))
    # Magma: the sea is the big one; anything else is a pipe/pool.
    magmas = _flood_bodies(raw["magma_blocks"], xb, yb, zc)
    magma_bodies = []
    for m in magmas:
        name = "magma sea" if m["tiles"] >= 10000 else "magma pool"
        magma_bodies.append(_finish_body(
            m, "magma", fort, surface_blocks, name, xb, yb, zc))
    # Mineral veins (ore identity is NOT in the tiletype).
    veins_raw = _flood_bodies(raw["mineral_blocks"], xb, yb, zc)
    veins = []
    for v in veins_raw:
        # A body holding most of the map's mineral is not a vein —
        # it is widespread mineral-bearing rock. Only small isolated
        # bodies are veins.
        name = ("mineral-bearing rock (widespread, ore "
                "unidentified)" if v["tiles"] >= 5000 else
                "mineral vein (unidentified)")
        rec = _finish_body(v, "mineral", fort, surface_blocks,
                           name, xb, yb, zc)
        # Mineral reachability is adjacency, not membership: a vein
        # block face-adjacent to an open surface block can be mined
        # from the surface. (The membership check in _finish_body
        # always says False for mineral; replace it here.)
        if surface_blocks is not None:
            adj = False
            for idx in v["blocks"]:
                bx, by, bz = _block_xyz(idx, xb, yb)
                for nbx, nby, nbz in (
                        (bx - 1, by, bz), (bx + 1, by, bz),
                        (bx, by - 1, bz), (bx, by + 1, bz),
                        (bx, by, bz - 1), (bx, by, bz + 1)):
                    if 0 <= nbx < xb and 0 <= nby < yb \
                            and 0 <= nbz < zc:
                        if _block_index(nbx, nby, nbz, xb, yb) \
                                in surface_blocks:
                            adj = True
                            break
                if adj:
                    break
            rec["reachable"] = adj
            rec["reachable_note"] = (
                "reachable — a vein block touches open ground, "
                "it can be mined from the surface"
                if adj else
                "not reachable from the surface yet — the vein "
                "is buried; dig down to it")
            rec["description"] = describe_body(rec, fort)
        veins.append(rec)

    # Aquifer: per-z sampled block counts (survey.lua §aquifer).
    aq_levels = [(i, v) for i, v in enumerate(raw["aquifer_by_z"])
                 if v > 0]
    aquifer = {
        "kind": AQUIFER_KIND,
        "levels": [{"z": z, "blocks_showing": n}
                   for z, n in aq_levels],
        "total_blocks": raw["aquifer_total"],
        "note": (
            "Light aquifer (per the embark warning). The z-levels "
            "above are where sampled rock shows aquifer tiles; "
            "digging into them will leak water into the fort."
            if aq_levels else
            "Light aquifer reported at embark, but no aquifer "
            "tiles showed in the sampled scan — treat soil and "
            "stone layers below the surface as suspect until rock "
            "is exposed."),
    }
    # Soil / stone: totals + the richest z-levels.
    def _top(by_z: list[int], n: int = 3) -> list[dict[str, int]]:
        order = sorted(range(len(by_z)), key=lambda z: -by_z[z])
        return [{"z": z, "tiles": by_z[z]} for z in order[:n]
                if by_z[z] > 0]
    soil = {"total_tiles": sum(raw["soil_by_z"]),
            "richest_levels": _top(raw["soil_by_z"])}
    stone = {"total_tiles": sum(raw["stone_by_z"]),
             "richest_levels": _top(raw["stone_by_z"])}
    # Plants: per species, nearest to the fort by bbox.
    plants = []
    for p in raw["plants"]:
        bbox = {"x0": p["x0"], "y0": p["y0"], "z0": p["z0"],
                "x1": p["x1"], "y1": p["y1"], "z1": p["z1"]}
        # The Lua side records the nearest real plant per species
        # (against the fort centre passed in PARAMS). A bbox clamp
        # would read 0 whenever the fort sits inside the species'
        # range, even when no plant of that species is nearby — so
        # the Lua nearest is authoritative when present.
        npos = p.get("nearest_pos")
        if npos is not None:
            near = (npos[0], npos[1], npos[2])
        else:
            near = _nearest_point(fort, bbox)
        plants.append({
            "species": p["species"], "name": p["name"],
            "is_shrub": p["is_shrub"], "count": p["count"],
            "bbox": bbox,
            "nearest": {"pos": list(near),
                        "distance_tiles": chebyshev3d(fort, near),
                        "direction": direction_words(fort, near)},
        })
    plants.sort(key=lambda p: p["count"], reverse=True)

    # Vertical: depth to magma, depth to the first cavern.
    magma_top = (min((m["bbox"]["z1"] for m in magma_bodies),
                     default=None))
    vertical = {
        "fort_z": fort_z,
        "depth_to_magma_levels": (
            fort_z - magma_top if magma_top is not None else None),
        "magma_top_z": magma_top,
        "depth_to_first_cavern_levels": (
            fort_z - cavern_top_z
            if cavern_top_z is not None else None),
        "first_cavern_top_z": cavern_top_z,
    }
    # Hazards, in plain words, wherever they are relevant.
    hazards: list[str] = []
    if vertical["depth_to_magma_levels"] is not None and magma_bodies:
        d = vertical["depth_to_magma_levels"]
        hazards.append(
            f"{magma_bodies[0]['name'].capitalize()} {d} levels below "
            f"the fort (top at z{magma_top}). If you dig straight "
            f"down {d} levels from the fort centre you will breach "
            f"lava.")
    if aq_levels:
        lo = min(z for z, _ in aq_levels)
        hi = max(z for z, _ in aq_levels)
        hazards.append(
            f"Light aquifer at z{lo}..z{hi} "
            f"({raw['aquifer_total']} sampled blocks show aquifer "
            f"rock). Digging into those levels will leak water "
            f"into the fort — dig through them fast and seal "
            f"behind you.")
    if cavern_top_z is not None:
        hazards.append(
            f"First cavern {vertical['depth_to_first_cavern_levels']} "
            f"levels below the fort (top at z{cavern_top_z}). "
            f"Digging down will eventually break into open "
            f"cavern space.")
    survey = {
        "water_bodies": water_bodies,
        "magma_bodies": magma_bodies,
        "mineral_veins": veins,
        "aquifer": aquifer,
        "soil": soil, "stone": stone, "plants": plants,
        "vertical": vertical, "hazards": hazards,
        "fort_centre": list(fort),
        # Block index sets for the coarse overview (spatial.py):
        # one char per block needs to know which blocks hold water
        # or magma. Small (a few hundred ints), kept alongside the
        # bodies they came from.
        "water_block_indices": sorted(
            {i for w in waters for i in w["blocks"]}),
        "magma_block_indices": sorted(
            {i for m in magmas for i in m["blocks"]}),
        "derived_at_tick": tick,
        "scan_seconds": raw.get("scan_seconds"),
        "build_ms": int((time.monotonic() - t0) * 1000),
    }
    survey["summary"] = survey_summary(survey)
    return survey


def _away(n: int) -> str:
    """'1 tile away' / 'N tiles away'."""
    return f"{n} tile away" if n == 1 else f"{n} tiles away"


def survey_summary(s: dict[str, Any]) -> list[str]:
    """The ~150-token survey summary (design §5.2): nearest of each
    kind, in plain words, with distance and quantity."""
    lines: list[str] = []
    fort = tuple(s["fort_centre"])
    if s["water_bodies"]:
        w = min(s["water_bodies"],
                key=lambda b: b["nearest"]["distance_tiles"])
        n = w["nearest"]
        lines.append(
            f"Nearest water: {w['name']} of {w['tiles']} water tiles "
            f"at ({n['pos'][0]}, {n['pos'][1]}, z{n['pos'][2]}), "
            f"{_away(n['distance_tiles'])} — {n['direction']} — "
            f"up to {w['max_depth']} deep. "
            f"{w['reachable_note']}.")
    else:
        lines.append("Nearest water: none found on the map.")
    if s["mineral_veins"]:
        v = min(s["mineral_veins"],
                key=lambda b: b["nearest"]["distance_tiles"])
        n = v["nearest"]
        if "widespread" in v["name"]:
            b = v["bbox"]
            lines.append(
                f"Mineral: mineral-bearing rock starts right under "
                f"the fort — nearest mineral tile at "
                f"({n['pos'][0]}, {n['pos'][1]}, z{n['pos'][2]}), "
                f"{_away(n['distance_tiles'])} — and spans "
                f"z{b['z0']}..z{b['z1']} across the whole map "
                f"({v['tiles']} tiles). Ore identity is not "
                f"visible in the rock; identify it by mining a "
                f"boulder. {v['reachable_note']}.")
        else:
            lines.append(
                f"Nearest mineral vein (ore unidentified): "
                f"{v['tiles']} mineral tiles "
                f"at ({n['pos'][0]}, {n['pos'][1]}, z{n['pos'][2]}), "
                f"{_away(n['distance_tiles'])} — {n['direction']}. "
                f"{v['reachable_note']}.")
    else:
        lines.append("Nearest mineral vein: none found.")
    if s["magma_bodies"]:
        m = s["magma_bodies"][0]
        n = m["nearest"]
        lines.append(
            f"Magma: {m['name']} of {m['tiles']} tiles, top at "
            f"z{m['bbox']['z1']}, "
            f"{s['vertical']['depth_to_magma_levels']} levels below "
            f"the fort. {m['reachable_note']}.")
    else:
        lines.append("Magma: none found.")
    aq = s["aquifer"]
    if aq["levels"]:
        lo = min(l["z"] for l in aq["levels"])
        hi = max(l["z"] for l in aq["levels"])
        lines.append(
            f"Aquifer: {aq['kind']}, at z{lo}..z{hi}. "
            f"Digging into those levels leaks water.")
    else:
        lines.append(f"Aquifer: {aq['kind']}, no layers located "
                     f"by the sampled scan.")
    shrubs = [p for p in s["plants"] if p["is_shrub"]]
    if shrubs:
        near = min(shrubs,
                   key=lambda p: p["nearest"]["distance_tiles"])
        n = near["nearest"]
        lines.append(
            f"Nearest gatherable shrubs: {near['name']} "
            f"({near['count']} on the map) at "
            f"({n['pos'][0]}, {n['pos'][1]}, z{n['pos'][2]}), "
            f"{_away(n['distance_tiles'])} — {n['direction']}.")
    trees = [p for p in s["plants"] if not p["is_shrub"]]
    if trees:
        near = min(trees,
                   key=lambda p: p["nearest"]["distance_tiles"])
        n = near["nearest"]
        lines.append(
            f"Nearest trees: {near['name']} "
            f"({near['count']} on the map) at "
            f"({n['pos'][0]}, {n['pos'][1]}, z{n['pos'][2]}), "
            f"{_away(n['distance_tiles'])} — {n['direction']}.")
    if s["vertical"]["depth_to_first_cavern_levels"] is not None:
        lines.append(
            f"First cavern: "
            f"{s['vertical']['depth_to_first_cavern_levels']} levels "
            f"below the fort (top at "
            f"z{s['vertical']['first_cavern_top_z']}).")
    return lines
