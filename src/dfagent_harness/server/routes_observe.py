from __future__ import annotations

import time
from http.server import BaseHTTPRequestHandler
from typing import Any, Optional

from .context import ServerContext
from .helpers import _cursor_array, _error, _json, _needs_still_site


def attention(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # The attention section (world-model design §6.1): what is
    # wrong, what changed, what needs acting on — built live
    # from the poller's detector (its arrival record) and last
    # state. Needs the daemon's poller; without it there is no
    # diff record to build from. The surface level comes from
    # the CACHED areas only (never triggers a scan).
    from .. import attention as attention_mod
    from ..spatial import estimate_tokens
    if ctx.poller is None:
        _error(handler, 503, "NO_POLLER",
               "attention needs the daemon's poller (its diff "
               "record); this server was started without one")
        return
    state = ctx.poller.last_state
    if state is None:
        _error(handler, 503, "NO_POLLER_STATE",
               "the poller has not collected a state yet")
        return
    t0 = time.monotonic()
    cached_areas = ctx.spatial_cache.get("areas")
    surface_z = (cached_areas or {}).get("surface_z")
    items = attention_mod.build_attention(
        state, ctx.poller.detector, surface_z=surface_z)
    text = "\n".join(it["text"] for it in items)
    _json(handler, 200, {
        "attention": items,
        "tick": (state.get("status") or {}).get("year_tick"),
        "source": "poller detector arrivals + last state",
        "cost": {"tokens": estimate_tokens(text),
                 "ms": int((time.monotonic() - t0) * 1000)}})

def snapshot(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    # The per-tick assembled snapshot (world-model design
    # §6): a FULL paused collect folded through the Context
    # Assembler with the Store (diffing + trends) and the
    # poller's detector (attention). Areas + survey come from
    # the CACHE — except the still-site derivation below,
    # which warms the areas on demand when the cache is cold
    # (one ~15 s scan per daemon restart, only when the model
    # actually needs a site; M1 run #11 tick 1 proved an
    # empty placement section costs an idle tick). Needs the
    # game client.
    from .. import assembler, observe
    from ..read_safety import ReadRefused, paused_read
    if ctx.client is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "no DFHack client")
        return
    t0 = time.monotonic()
    try:
        with ctx.rpc_lock:
            state = paused_read(
                ctx.client, lambda: observe.collect(ctx.client))
    except ReadRefused as exc:
        _error(handler, 503, "READ_REFUSED", str(exc),
               {"error": str(exc)})
        return
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "snapshot collect failed", {"error": str(exc)})
        return
    store = (ctx.daemon.store if ctx.daemon is not None
             and getattr(ctx.daemon, "store", None) is not None
             else ctx.default_store())
    detector = ctx.poller.detector if ctx.poller is not None else None
    # Free workshop sites for the suggestion: the model
    # stalls without a concrete build coordinate (M1 run
    # #6, "the observation gives no free ground
    # coordinates"). The snapshot derives sites when it
    # actually needs a still site and the cache is missing
    # or stale — a single derivation (~1 s: 2 slices + up
    # to 8 probes) is worth it, because without a site the
    # model cannot build the still at all. The build probe
    # re-verifies the site at build time, so a stale cached
    # site is handled by the fix hint, not a bad build.
    # (Both derivations warm the areas on demand when the
    # cache is cold after a daemon restart — M1 run #11
    # tick 1, where the placement section was empty and
    # the model burned an idle tick asking for
    # coordinates.)
    sites = None
    placement = None
    if ctx.daemon is not None:
        sites = getattr(ctx.daemon, "_sites_cache", None)
        placement = getattr(ctx.daemon, "_placement_cache", None)
        cache_at = getattr(ctx.daemon, "_sites_cache_at", 0) or 0
        if (sites is None
                or time.monotonic() - cache_at > 120):
            if _needs_still_site(state):
                try:
                    with ctx.rpc_lock:
                        sites = ctx.daemon._derive_sites(state)
                    ctx.daemon._sites_cache = sites
                    ctx.daemon._sites_cache_at = time.monotonic()
                    placement = getattr(
                        ctx.daemon, "_placement_cache", None)
                except Exception:  # noqa: BLE001 - no sites
                    sites = None  # is "no build", not fatal
        if placement is None:
            # General cold-cache warm: with a still already
            # built the still branch above does not run, so
            # after a restart the placement section would
            # still be empty and the model stalls asking
            # for bed/zone sites. get_placement warms the
            # areas on demand (once per restart) and
            # populates the placement cache; later ticks
            # read the cache, never re-derive.
            try:
                with ctx.rpc_lock:
                    ctx.daemon.get_placement("workshop", 3, 3)
                placement = getattr(
                    ctx.daemon, "_placement_cache", None)
            except Exception:  # noqa: BLE001 - no sites
                pass  # is "no build", not fatal
    try:
        # The areas cache holds the full derivation dict
        # (areas + graph + surface_blocks + ...); the
        # assembler takes the areas LIST. Passing the dict
        # made _areas slice a dict and fail with
        # KeyError slice(None, 15, None) (2026-11-26).
        snap = assembler.assemble(
            state, store=store, detector=detector,
            areas=(ctx.spatial_cache.get("areas") or {}).get("areas"),
            survey=ctx.spatial_cache.get("survey"),
            sites=sites, placement=placement,
            # The attention's vertical-distance text ("174
            # levels below the fort") needs the fort's
            # surface z — without it _where returns "" and
            # the fix-6 gap text never reaches the snapshot
            # (found live 2026-11-27: demons at z1 flagged
            # [P2] with no level gap stated).
            surface_z=(ctx.spatial_cache.get("areas") or {}).get(
                "surface_z"))
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "SNAPSHOT_FAILED",
               "assembler failed", {"error": str(exc)})
        return
    snap["cost"] = {"tokens": snap["tokens"],
                    "ms": int((time.monotonic() - t0) * 1000)}
    _json(handler, 200, snap)

def cursor(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    if ctx.client is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "no DFHack client")
        return
    try:
        from ..ui import get_cursor
        with ctx.rpc_lock:
            out = get_cursor(ctx.client)
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "GAME_NOT_RUNNING",
               "cursor read failed", {"error": str(exc)})
        return
    _json(handler, 200, {"cursor": _cursor_array(out.get("cursor"))})