from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from typing import Any, Optional

from .context import ServerContext
from .helpers import _error, _json
from ..actions import get_paused
from ..planner import state_summary
from ..read_safety import ReadRefused


def health(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # Never block on rpc_lock (T3 row 6): a long RPC call
    # (or a slow client) used to stall /v1/health for
    # seconds. Try the lock; when it is held, fall back to
    # the poller's last state and say busy, so a caller can
    # tell "game up, just busy" from "game down".
    version: dict[str, Any] = {}
    reachable = False
    busy = False
    if ctx.client is not None:
        if ctx.rpc_lock.acquire(blocking=False):
            try:
                version = ctx.client.get_version()
                reachable = True
            except Exception:
                reachable = False
            finally:
                ctx.rpc_lock.release()
        elif ctx.poller is not None \
                and ctx.poller.last_state is not None:
            version = (ctx.poller.last_state.get("meta") or {}).get(
                "version") or {}
            reachable = True
            busy = True
        else:
            busy = True
    elif ctx.poller is not None and ctx.poller.last_state is not None:
        version = (ctx.poller.last_state.get("meta") or {}).get(
            "version") or {}
        reachable = True
    _json(handler, 200, {
        "ok": True,
        "daemon": "dfh/phase4",
        "df_reachable": reachable,
        "version": version,
        "busy": busy,
    })

def pause(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # Fresh RPC read of the pause flag (not the poller's
    # cached state, which only updates while paused).
    # Used by run-script pre-flight checks.
    if ctx.client is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "no DFHack client")
        return
    try:
        with ctx.rpc_lock:
            paused = get_paused(ctx.client)
        _json(handler, 200, {"paused": paused})
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "RPC_ERROR",
               f"pause read failed: {exc}")

def state(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    try:
        state = ctx.get_state()
    except ReadRefused as exc:
        # Read safety: pause could not be verified, so the
        # read was refused (outcome unknown). 503, retryable.
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001 - game down, etc.
        _error(handler, 503, "GAME_NOT_RUNNING",
               "DFHack RPC is not reachable or state is "
               "unavailable",
               {"error": str(exc)})
        return
    _json(handler, 200, state)

def status(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    try:
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
    s = state_summary(state)
    _json(handler, 200, {
        "paused": s["paused"], "year": s["year"],
        "tick": s["tick"], "population": s["citizens"],
        "animals": s["animals"],
        "threats": len(s["hostiles"]),
        "threat_list": s["hostiles"],
        "food": s["food"], "drink": s["drink"],
        "wood": s["wood"], "stone": s["stone"],
        "seeds": s["seeds"], "barrels": s["barrels"],
        "jobs": len(s["jobs"]),
        "wounded": sum(1 for c in s["citizen_list"]
                       if (c.get("wound_count") or 0) > 0),
        "buildings": s["building_summary"],
        "meta": {"tick": s["tick"]},
    })