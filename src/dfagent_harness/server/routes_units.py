from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import Any, Optional

from .context import ServerContext
from .helpers import _error, _json
from ..read_safety import ReadRefused


def units(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # fresh=1 forces a fresh FULL units collect (units.lua)
    # instead of the poller's lite cache. The poller's units
    # are the cheap lite records (no needs, wounds list,
    # relations, labors, skills, sex, age, goals) — not
    # enough for a per-dwarf sample. The diary's run-start/
    # run-end samples come from here (the M1 driver fetches
    # ?kind=citizens&fresh=1). A fresh collect is a paused
    # read, so it is safe while the game is paused.
    fresh = ((query.get("fresh") or [""])[0].lower()
             in ("1", "true"))
    try:
        if fresh and ctx.collect_section is not None:
            state = ctx.collect_section("units")
        else:
            state = ctx.get_state()
    except ReadRefused as exc:
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "DFHack RPC is not reachable",
               {"error": str(exc)})
        return
    units = state.get("units") or {}
    citizens = units.get("citizens") or []
    # kind filter (design §4.2): citizens | hostiles |
    # wildlife | visitors | livestock. Default: citizens +
    # hostiles (the old behaviour).
    kind = (query.get("kind") or [""])[0].lower()
    by_kind = {
        "citizens": citizens,
        "hostiles": units.get("hostiles") or [],
        "wildlife": units.get("wildlife") or [],
        "visitors": units.get("visitors") or [],
        "livestock": units.get("livestock") or [],
    }
    if kind:
        if kind not in by_kind:
            _error(handler, 400, "BAD_REQUEST",
                   "kind must be citizens, hostiles, wildlife, "
                   "visitors, or livestock")
            return
        out = list(by_kind[kind])
    elif query.get("citizens_only", [""])[0].lower() in (
            "1", "true"):
        out = citizens
    else:
        out = citizens + (units.get("hostiles") or [])
    # region filter: region=x0,y0,z0,x1,y1,z1 (inclusive box).
    region = (query.get("region") or [""])[0]
    if region:
        try:
            rx0, ry0, rz0, rx1, ry1, rz1 = (
                int(v) for v in region.split(","))
        except ValueError:
            _error(handler, 400, "BAD_REQUEST",
                   "region must be x0,y0,z0,x1,y1,z1 integers")
            return
        out = [rec for rec in out
               if len(rec.get("pos") or []) == 3
               and rx0 <= rec["pos"][0] <= rx1
               and ry0 <= rec["pos"][1] <= ry1
               and rz0 <= rec["pos"][2] <= rz1]
    try:
        limit = int(query.get("limit", ["100"])[0])
    except ValueError:
        limit = 100
    limit = max(1, min(limit, 1000))
    # Plain-words description per unit (standing directive):
    # the record stays compact, the description says what
    # the unit is, where it is, and what it is doing.
    from .. import attention as attention_mod
    cached_areas = ctx.spatial_cache.get("areas")
    surface_z = (cached_areas or {}).get("surface_z")
    described = [
        dict(rec, description=attention_mod.describe_unit(
            rec, surface_z=surface_z))
        for rec in out[:limit]]
    _json(handler, 200, {
        "units": described,
        "count": len(out),
        "citizen_count": len(citizens),
        "total_active_units": units.get("total_active_units"),
        "reconciled": units.get("reconciled"),
    })

def unit(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    try:
        unit_id = int(path[len("/v1/unit/"):])
    except ValueError:
        _error(handler, 400, "BAD_REQUEST",
               f"bad unit id: {path!r}")
        return
    # The full record for one unit of any class (design §4.2):
    # a single-unit probe, cheap, through the read-safety
    # gate. Citizens get the full record (profession, needs,
    # skills); other classes get the compact record plus
    # wounds, job and owner where applicable.
    if ctx.client is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "no DFHack client")
        return
    try:
        from ..actions import _run_helper
        from ..read_safety import paused_read
        with ctx.rpc_lock:
            out = paused_read(
                ctx.client,
                lambda: _run_helper(
                    ctx.client, "probe_unit.lua",
                    {"id": unit_id}, timeout=30.0))
    except ReadRefused as exc:
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "DFHack RPC is not reachable",
               {"error": str(exc)})
        return
    if not out.get("ok", False):
        if out.get("kind") == "not_found":
            _error(handler, 404, "NOT_FOUND",
                   f"no unit with id {unit_id}")
            return
        _error(handler, 503, "GAME_NOT_RUNNING",
               f"unit probe failed: {out.get('error')}")
        return
    from .. import attention as attention_mod
    cached_areas = ctx.spatial_cache.get("areas")
    surface_z = (cached_areas or {}).get("surface_z")
    unit = dict(out["unit"])
    unit["description"] = attention_mod.describe_unit(
        unit, surface_z=surface_z)
    _json(handler, 200, unit)

def section(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    section = path.rsplit("/", 1)[-1]
    try:
        state = ctx.collect_section(section)
    except ReadRefused as exc:
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               f"section {section!r} unavailable",
               {"error": str(exc)})
        return
    _json(handler, 200, state.get(section, state))