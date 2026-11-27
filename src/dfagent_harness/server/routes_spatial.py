from __future__ import annotations

import time
from http.server import BaseHTTPRequestHandler
from typing import Any, Optional

from .context import ServerContext
from .helpers import _error, _json
from ..read_safety import ReadRefused


def slice_(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    try:
        x0 = int(query["x0"][0])
        y0 = int(query["y0"][0])
        z = int(query["z"][0])
        x1 = int(query["x1"][0])
        y1 = int(query["y1"][0])
    except (KeyError, IndexError, ValueError):
        _error(handler, 400, "BAD_REQUEST",
               "slice needs integer x0,y0,z,x1,y1 params")
        return
    layer = query.get("layer", ["terrain"])[0]
    allow_full = query.get("full", [""])[0].lower() in (
        "1", "true")
    try:
        out = ctx.get_slice(x0, y0, z, x1, y1, layer, allow_full)
    except ValueError as exc:
        _error(handler, 400, "BAD_REQUEST", str(exc))
        return
    except ReadRefused as exc:
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "slice unavailable", {"error": str(exc)})
        return
    _json(handler, 200, out)

def column(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    try:
        x = int(query["x"][0])
        y = int(query["y"][0])
    except (KeyError, IndexError, ValueError):
        _error(handler, 400, "BAD_REQUEST",
               "column needs integer x&y params")
        return
    try:
        levels = int(query.get("levels", ["5"])[0])
    except ValueError:
        levels = 5
    levels = max(1, min(levels, 197))
    from_z = None
    if query.get("from_z"):
        try:
            from_z = int(query["from_z"][0])
        except ValueError:
            _error(handler, 400, "BAD_REQUEST",
                   "from_z must be an integer")
            return
    try:
        out = ctx.get_column(x, y, levels, from_z)
    except ValueError as exc:
        _error(handler, 400, "BAD_REQUEST", str(exc))
        return
    except ReadRefused as exc:
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "column unavailable", {"error": str(exc)})
        return
    _json(handler, 200, out)

def overview(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    try:
        out = ctx.get_overview()
    except ReadRefused as exc:
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "overview unavailable", {"error": str(exc)})
        return
    _json(handler, 200, out)

def areas(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    refresh = query.get("refresh", [""])[0].lower() in (
        "1", "true")
    try:
        areas = ctx.get_areas(refresh)
    except ReadRefused as exc:
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "areas unavailable", {"error": str(exc)})
        return
    ctx.enrich_area_descriptions(areas)
    from .. import spatial
    areas["summary"] = spatial.area_summary(areas["areas"])
    _json(handler, 200, areas)

def area(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    from .. import spatial
    ref = path[len("/v1/area/"):]
    if not ref:
        _error(handler, 400, "BAD_REQUEST",
               "area id or name required")
        return
    refresh = query.get("refresh", [""])[0].lower() in (
        "1", "true")
    try:
        areas = ctx.get_areas(refresh)
    except ReadRefused as exc:
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "areas unavailable", {"error": str(exc)})
        return
    ctx.enrich_area_descriptions(areas)
    area = spatial.resolve_area(areas["areas"], ref)
    if area is None:
        _error(handler, 404, "NOT_FOUND",
               f"no area {ref!r}")
        return
    # A slice of the area: its centre, clamped to 40x40, at
    # the top z for the surface (the ground) and the bottom z
    # otherwise (the floor). The area may be larger than the
    # slice cap; the response says so.
    b = area["bbox"]
    cx = (b["x0"] + b["x1"]) // 2
    cy = (b["y0"] + b["y1"]) // 2
    z = b["z1"] if area["kind"] == "surface" else b["z0"]
    x0 = max(b["x0"], cx - 20)
    x1 = min(b["x1"], cx + 19)
    y0 = max(b["y0"], cy - 20)
    y1 = min(b["y1"], cy + 19)
    try:
        sl = ctx.get_slice(x0, y0, z, x1, y1, "terrain", False)
    except ReadRefused as exc:
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "area slice unavailable", {"error": str(exc)})
        return
    _json(handler, 200, {"area": area, "slice": sl})

def path(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    from .. import spatial
    a = (query.get("a") or [""])[0]
    b = (query.get("b") or [""])[0]
    if not a or not b:
        _error(handler, 400, "BAD_REQUEST",
               "path needs ?a=<area>&b=<area>")
        return
    try:
        areas = ctx.get_areas(False)
    except ReadRefused as exc:
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "areas unavailable", {"error": str(exc)})
        return
    graph = areas["graph"]
    # Resolve names to ids first.
    by_id = {x["id"]: x for x in areas["areas"]}
    a_id = a if a in by_id else (
        spatial.resolve_area(areas["areas"], a) or {}).get("id")
    b_id = b if b in by_id else (
        spatial.resolve_area(areas["areas"], b) or {}).get("id")
    if a_id is None or b_id is None:
        _error(handler, 404, "NOT_FOUND",
               f"unknown area: {a!r} or {b!r}")
        return
    ids = spatial.find_path(graph, a_id, b_id)
    if ids is None:
        _json(handler, 200, {
            "from": a_id, "to": b_id, "path": None,
            "note": "no connection between these areas "
                    "(they are separated by solid rock; dig "
                    "a stairwell or tunnel to link them)"})
        return
    _json(handler, 200, {
        "from": a_id, "to": b_id,
        "path": [{"id": i, "name": by_id[i]["name"],
                  "kind": by_id[i]["kind"],
                  "bbox": by_id[i]["bbox"]} for i in ids]})

def survey(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # ?kind= filters what is returned (the scan itself is one
    # pass for all kinds); ?refresh=1 forces a fresh scan
    # (~25 s). The response always carries the plain-words
    # summary, the vertical facts, the hazards, the cost, and
    # the staleness flag.
    kind = (query.get("kind") or ["all"])[0].lower()
    if kind not in ("all", "water", "magma", "mineral",
                    "aquifer", "plants", "soil"):
        _error(handler, 400, "BAD_REQUEST",
               "kind must be all|water|magma|mineral|"
               "aquifer|plants|soil")
        return
    refresh = query.get("refresh", [""])[0].lower() in (
        "1", "true")
    try:
        out = ctx.get_survey(refresh)
    except ReadRefused as exc:
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "survey unavailable", {"error": str(exc)})
        return
    if kind == "all":
        _json(handler, 200, out)
        return
    key = {"water": "water_bodies", "magma": "magma_bodies",
           "mineral": "mineral_veins", "aquifer": "aquifer",
           "plants": "plants",
           "soil": "soil"}[kind]
    _json(handler, 200, {
        "kind": kind, key: out.get(key),
        "summary": out.get("summary"),
        "hazards": out.get("hazards"),
        "vertical": out.get("vertical"),
        "stale": out.get("stale"),
        "derived_at_tick": out.get("derived_at_tick"),
        "cost": out.get("cost")})

def sites(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # GET /v1/sites?kind=workshop&w=3&h=3 — verified-free
    # sites for a placement kind + size (the full detail
    # behind the snapshot's compact placement section).
    # Each site is verified free (terrain, occupancy,
    # plants, units, overlap) AND reachable (canWalkBetween
    # from the fort centre). Blocked candidates carry their
    # reasons. A site is never returned as verified when its
    # reachability could not be checked.
    from ..placement import PLACEMENT_KINDS
    kind = (query.get("kind") or ["workshop"])[0].lower()
    if kind not in PLACEMENT_KINDS:
        _error(handler, 400, "BAD_REQUEST",
               f"kind must be one of "
               f"{', '.join(sorted(PLACEMENT_KINDS))}")
        return
    try:
        w = int((query.get("w") or [""])[0] or
                PLACEMENT_KINDS[kind]["default_size"][0])
        h = int((query.get("h") or [""])[0] or
                PLACEMENT_KINDS[kind]["default_size"][1])
    except ValueError:
        _error(handler, 400, "BAD_REQUEST",
               "w and h must be integers")
        return
    if w < 1 or h < 1 or w > 31 or h > 31:
        _error(handler, 400, "BAD_REQUEST",
               "w and h must be 1..31")
        return
    if ctx.daemon is None or getattr(ctx.daemon, "get_placement",
                                 None) is None:
        _error(handler, 503, "NO_DAEMON",
               "sites need the daemon's placement service")
        return
    t0 = time.monotonic()
    try:
        with ctx.rpc_lock:
            out = ctx.daemon.get_placement(kind, w, h)
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "placement search failed", {"error": str(exc)})
        return
    out["cost"] = {"ms": int((time.monotonic() - t0) * 1000)}
    _json(handler, 200, out)