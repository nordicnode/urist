from __future__ import annotations

import time
from http.server import BaseHTTPRequestHandler
from typing import Any, Optional

from .context import ServerContext
from .helpers import KEYSYMS, _action_envelope, _error, _json, _req_int, _req_seq
from ..actions import act
from ..actions import set_paused
from dfhack_rpc.proto import CoreProtocol_pb2 as core
from dfhack_rpc.proto import RemoteFortressReader_pb2 as rfr


def action(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    name = path[len("/v1/actions/"):]
    if ctx.client is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "no DFHack client")
        return
    if name in ("lua", "command") and not ctx.allow_raw_actions:
        _error(handler, 403, "BAD_REQUEST",
               f"raw action {name!r} is disabled (start the "
               f"ctx.daemon with ctx.allow_raw_actions to enable it)")
        return
    try:
        with ctx.rpc_lock:
            result = _dispatch_action(ctx, handler, name, body)
    except ValueError as exc:
        _error(handler, 400, "BAD_REQUEST", str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - transport etc.
        _error(handler, 502, "RPC_ERROR",
               f"action {name!r} failed at the transport",
               {"error": str(exc)})
        return
    _json(handler, 200, result)

def _placement_cache(ctx: ServerContext, handler: BaseHTTPRequestHandler) -> Optional[dict[str, Any]]:
    # The daemon's verified-site cache (kind -> [site, ...]),
    # for the placement-aware build actions' verified-
    # alternative naming. None when the daemon has not
    # derived sites yet — the action then searches fresh.
    if ctx.daemon is None:
        return None
    return getattr(ctx.daemon, "_placement_cache", None)

def _placement_from(ctx: ServerContext, handler: BaseHTTPRequestHandler) -> Optional[tuple[int, int, int]]:
    # The walkable origin (the fort centre) the placement
    # cache's reachability was verified from. None when the
    # cache is missing — the action then cannot verify
    # reachability and says so instead of naming an
    # unverified site.
    cache = _placement_cache(ctx, handler)
    if not cache:
        return None
    frm = cache.get("from")
    return tuple(frm) if frm else None

def _dispatch_action(ctx: ServerContext, handler: BaseHTTPRequestHandler, name: str, body: dict[str, Any]) -> None:
    if name == "pause":
        paused = bool(body.get("paused"))
        if set_paused(ctx.client, paused) != paused:
            raise RuntimeError("pause flag did not stick")
        return {"ok": True, "action": "pause",
                "detail": f"game {'paused' if paused else 'running'}",
                "evidence": {"paused": paused}, "took_ms": 0}
    if name == "dig":
        mode = body.get("mode", "dig")
        return _action_envelope(act(
            ctx.client, "designate_dig",
            box=_req_seq(body.get("box"), "box", 6), mode=mode))
    if name == "undesignate":
        return _action_envelope(act(
            ctx.client, "designate_dig",
            box=_req_seq(body.get("box"), "box", 6), mode="clear"))
    if name in ("chop", "gather"):
        return _action_envelope(act(
            ctx.client, f"designate_{name}",
            box=_req_seq(body.get("box"), "box", 6),
            mark=bool(body.get("mark", True))))
    if name == "build":
        return _action_envelope(act(
            ctx.client, "build_workshop", kind=body.get("kind"),
            pos=_req_seq(body.get("pos"), "pos", 3),
            placement=_placement_cache(ctx, handler),
            from_pos=_placement_from(ctx, handler)))
    if name == "deconstruct":
        return _action_envelope(act(
            ctx.client, "deconstruct_building",
            building_id=_req_int(body.get("building_id"),
                                 "building_id")))
    if name == "stockpile":
        # Programmatic stockpile (constructBuilding
        # abstract=true) — the ui.create_stockpile keystroke
        # route is forbidden for game actions. The body
        # takes pos + width/height + category (the old box
        # + single-letter category form is still accepted).
        box = body.get("box")
        if box is not None:
            box = _req_seq(box, "box", 6)
            pos = (box[0], box[1], box[2])
            width = box[3] - box[0] + 1
            height = box[4] - box[1] + 1
        else:
            pos = _req_seq(body.get("pos"), "pos", 3)
            width = _req_int(body.get("width", 5), "width")
            height = _req_int(body.get("height", 5), "height")
        category = body.get("category", "food")
        if len(str(category)) == 1:
            # Old single-letter form (f = food, w = wood,
            # s = stone, r = refuse) from the ui route.
            category = {"f": "food", "w": "wood",
                        "s": "stone", "r": "refuse"}.get(
                str(category).lower(), str(category))
        return _action_envelope(act(
            ctx.client, "create_stockpile", category=category,
            pos=pos, width=width, height=height,
            placement=_placement_cache(ctx, handler),
            from_pos=_placement_from(ctx, handler)))
    if name == "zone":
        return _action_envelope(act(
            ctx.client, "create_zone",
            zone_type=body.get("zone_type", "meeting_area"),
            pos=_req_seq(body.get("pos"), "pos", 3),
            width=_req_int(body.get("width", 5), "width"),
            height=_req_int(body.get("height", 5), "height"),
            placement=_placement_cache(ctx, handler),
            from_pos=_placement_from(ctx, handler)))
    if name == "farm":
        return _action_envelope(act(
            ctx.client, "build_farm_plot",
            x=_req_int(body.get("x"), "x"),
            y=_req_int(body.get("y"), "y"),
            z=_req_int(body.get("z"), "z"),
            width=_req_int(body.get("width", 3), "width"),
            height=_req_int(body.get("height", 3), "height"),
            placement=_placement_cache(ctx, handler),
            from_pos=_placement_from(ctx, handler)))
    if name == "furniture":
        return _action_envelope(act(
            ctx.client, "build_furniture", kind=body.get("kind"),
            pos=_req_seq(body.get("pos"), "pos", 3),
            placement=_placement_cache(ctx, handler),
            from_pos=_placement_from(ctx, handler)))
    if name == "order":
        return _action_envelope(act(
            ctx.client, "manager_order_create",
            job_type=body.get("job_type"),
            amount=_req_int(body.get("amount", 1), "amount")))
    if name == "order-remove":
        return _action_envelope(act(
            ctx.client, "manager_order_remove",
            order_id=_req_int(body.get("order_id"), "order_id")))
    if name == "queue-job":
        return _action_envelope(act(
            ctx.client, "queue_job",
            building_id=_req_int(body.get("building_id"),
                                 "building_id"),
            job=body.get("job"),
            count=_req_int(body.get("count", 1), "count")))
    if name == "labor":
        unit = body.get("unit_id", body.get("unit"))
        if isinstance(unit, str) and unit.isdigit():
            unit = int(unit)
        return _action_envelope(act(
            ctx.client, "labor_toggle", unit=unit,
            labor=body.get("labor"),
            on=bool(body.get("on", True))))
    if name == "key":
        return _send_keys(ctx, handler, body.get("keys") or [])
    if name == "cursor":
        from ..ui import set_cursor
        out = set_cursor(
            ctx.client, *_req_seq(body.get("pos"), "pos", 3))
        return {"ok": bool(out.get("ok")), "action": "cursor",
                "detail": "cursor moved",
                "evidence": {"cursor": out.get("cursor")},
                "took_ms": 0}
    if name == "lua":
        text = ctx.client.run_lua(body.get("code", ""))
        return {"ok": True, "action": "lua",
                "detail": "lua executed (raw, guarded)",
                "evidence": {"text": text}, "took_ms": 0}
    if name == "command":
        cmd = body.get("command", "")
        args = body.get("args") or []
        text = ctx.client.run_command(cmd, *args)
        return {"ok": True, "action": "command",
                "detail": f"ran DFHack command {cmd!r}",
                "evidence": {"text": text}, "took_ms": 0}
    # Registry names: the catalog (GET /v1/catalog) lists the
    # ACTIONS registry names (designate_gather, labor_toggle,
    # build_farm_plot, ...), so accept them here too, not just
    # the short aliases above. The model follows the catalog
    # and was getting "unknown action" for every catalog name
    # (M1, 2026-11-26). Coerce coordinate params from JSON
    # lists to tuples, as the alias branches do.
    from ..actions import ACTIONS
    if name in ACTIONS:
        kwargs = dict(body)
        for key in ("box", "pos"):
            if isinstance(kwargs.get(key), list):
                kwargs[key] = tuple(kwargs[key])
        # Placement-aware actions need the daemon's verified-
        # site cache + the walkable from-point, or a failed
        # build cannot name a verified alternative (the
        # registry-name route is the one the model actually
        # uses — the catalog lists registry names). act()
        # forwards placement/from_pos only to functions that
        # accept them, so passing them here is safe for every
        # action.
        kwargs.setdefault("placement",
                          _placement_cache(ctx, handler))
        kwargs.setdefault("from_pos", _placement_from(ctx, handler))
        return _action_envelope(act(ctx.client, name, **kwargs))
    raise ValueError(f"unknown action {name!r}")

def _send_keys(ctx: ServerContext, handler: BaseHTTPRequestHandler, keys: list[str]) -> dict[str, Any]:
    unknown = [k for k in keys
               if str(k).lower() not in KEYSYMS]
    if unknown:
        raise ValueError(f"unknown key(s): {unknown}")
    for key in keys:
        sym = KEYSYMS[str(key).lower()]
        for ev_type, state in ((2, 1), (3, 0)):
            ctx.client.call(
                "PassKeyboardEvent",
                rfr.KeyboardEvent(type=ev_type, sym=sym,
                                  state=state,
                                  unicode=sym if 32 <= sym < 127
                                  else 0,
                                  scancode=0, mod=0),
                core.EmptyMessage)
            time.sleep(0.05)
    try:
        focus = ctx.client.run_lua(
            "print(dfhack.gui.getCurFocus())")
    except Exception:  # noqa: BLE001 - viewscreen is best-effort
        focus = ""
    return {"ok": True, "action": "key",
            "detail": f"sent keys {keys}; viewscreen now "
                      f"{focus.strip()!r}",
            "evidence": {"viewscreen": focus.strip()},
            "took_ms": 0}