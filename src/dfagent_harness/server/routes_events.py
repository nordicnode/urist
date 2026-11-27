from __future__ import annotations

import queue
import time
from http.server import BaseHTTPRequestHandler
from typing import Any, Optional

from .context import ServerContext
from .helpers import _HEARTBEAT_SECONDS, _error, _json, _sse_event
from ..actions import set_paused


def daemon_control(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    payload = {
        "poll_count": ctx.poller.poll_count if ctx.poller else 0,
        "last_poll_ms": ctx.poller.last_poll_ms if ctx.poller else None,
        "event_seq": ctx.bus.latest_seq,
        "events_buffered": len(ctx.bus),
        "uptime_s": round(time.time() - ctx.started, 1),
    }
    if ctx.daemon is not None:
        payload.update(ctx.daemon.status())
    _json(handler, 200, payload)

def events(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    accept = handler.headers.get("Accept", "")
    wants_sse = "text/event-stream" in accept
    since_raw = (query.get("since", [None])[0]
                 or handler.headers.get("Last-Event-ID"))
    since: Optional[int] = None
    if since_raw is not None:
        try:
            since = int(since_raw)
        except ValueError:
            _error(handler, 400, "BAD_REQUEST",
                   f"bad since/Last-Event-ID: {since_raw!r}")
            return
    if not wants_sse:
        try:
            limit = int(query.get("limit", ["100"])[0])
        except ValueError:
            _error(handler, 400, "BAD_REQUEST",
                   "bad limit: must be an integer")
            return
        limit = max(1, min(limit, 1000))
        events = ctx.bus.replay(since_seq=since, limit=limit)
        _json(handler, 200, {"events": events,
                          "latest_seq": ctx.bus.latest_seq})
        return
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()
    # Subscribe BEFORE replaying (T3 row 4): an event
    # published between the replay and the subscribe was
    # lost. The live loop dedups by seq, so events that
    # arrive in both the replay and the queue are written
    # once.
    pending: queue.Queue[dict[str, Any]] = queue.Queue()
    ctx.bus.subscribe(pending.put)
    replayed = ctx.bus.replay(since_seq=since)
    max_seen = max([e["seq"] for e in replayed],
                   default=since if since is not None else 0)
    try:
        for event in replayed:
            handler.wfile.write(_sse_event(event["seq"], event))
        handler.wfile.flush()
        while True:
            try:
                event = pending.get(timeout=_HEARTBEAT_SECONDS)
            except queue.Empty:
                handler.wfile.write(b":heartbeat\n\n")
                handler.wfile.flush()
                continue
            if event["seq"] <= max_seen:
                continue
            max_seen = event["seq"]
            handler.wfile.write(_sse_event(event["seq"], event))
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass  # client went away; normal for SSE
    finally:
        ctx.bus.unsubscribe(pending.put)

def advance(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    """POST /v1/control/advance — the harness advance check.

    While time is not moving, check the current viewscreen; if
    a blocking screen is present, dismiss it programmatically
    (dialogs.advance, per the allowlist) and re-check. Names
    the last blocking screen in a zero-tick failure instead of
    timing out quietly. The M1 driver calls this when the clock
    does not advance during a window, so a modal can never
    stall a run silently. Returns the advance result dict.
    """
    if ctx.client is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "no DFHack client")
        return
    from .. import dialogs
    try:
        with ctx.rpc_lock:
            res = dialogs.advance(ctx.client, max_rounds=3,
                                 wait_s=2.0)
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "RPC_ERROR",
               f"advance failed: {exc}")
        return
    if ctx.daemon is not None:
        for audit in res.get("cleared") or []:
            ctx.daemon.journal.log_event(
                "dialog_dismissed",
                f"{audit.get('focus')} -> "
                f"{audit.get('focus_after')} "
                f"(dismissed={audit.get('dismissed')}, "
                f"removed={audit.get('removed')})")
        if not res.get("ok") and res.get("blocked_by"):
            ctx.daemon.journal.log_event(
                "dialog_blocked",
                f"advance refused {res.get('blocked_by')!r}: "
                f"{res.get('reason')}")
    _json(handler, 200, res)

def advance_clock(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    """POST /v1/control/advance-clock — advance the game clock
    by running unpaused for ``sleep_s`` wall seconds, as ONE
    atomic operation under rpc_lock.

    Root cause (2026-11-27, runs #12/#13): the M1 driver
    advanced the clock with three separate HTTP calls
    (unpause, sleep client-side, re-pause), leaving the
    unpause window unprotected. During that window the
    poller's focus probe + pause-flag read and the pause
    guard's pause-flag read (RFR calls, made on their own
    threads) could land while the game was ticking — and
    RPC reads while the game ticks can crash DF (double-free
    abort in the DFHack RPC server; the 2026-11-25 chop-test
    evidence in read_safety.py, and the identical
    "I/O error in receive header" + "free(): double free
    detected in tcache 2" signature that killed runs #12
    and #13 at tick 4 and tick 3). The daemon lock serializes
    calls but does NOT stop a call from running while the
    game ticks — only holding the lock across the whole
    unpause does that. This endpoint holds rpc_lock from the
    unpause through the re-pause, so no other thread can
    make any RPC call while the game is running.

    Body: {"sleep_s": float} (clamped to [0.25, 30.0], the
    driver's window clamp). Returns {"ok", "tick_before",
    "tick_after", "advanced", "sleep_s"}. On any failure
    the handler re-pauses the game (best effort) before
    returning the error, so a failed advance never leaves
    the game running.
    """
    if ctx.client is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "no DFHack client")
        return
    try:
        sleep_s = float(body.get("sleep_s") or 0.0)
    except (TypeError, ValueError):
        _error(handler, 400, "BAD_REQUEST",
               "sleep_s (number) is required")
        return
    sleep_s = max(0.25, min(sleep_s, 30.0))
    from .. import observe
    from ..read_safety import paused_read

    def _tick() -> int | None:
        st = paused_read(
            ctx.client,
            lambda: observe.collect(
                ctx.client, sections=("status",)))
        return (st.get("status") or {}).get("year_tick")

    try:
        with ctx.rpc_lock:
            tick_before = _tick()
            # The game is RUNNING from the moment the pause
            # flag clears until the re-pause verifies — the
            # set_paused round trips are inside that span,
            # not outside it. Time the whole span: the
            # driver calibrates its tick rate on it, and
            # run #12's first window overshot 803 ticks for
            # a 150 target because the rate was calibrated
            # on sleep_s alone (the verification overhead
            # ran uncounted while the game ticked).
            unpaused_start = time.monotonic()
            set_paused(ctx.client, False)
            try:
                time.sleep(sleep_s)
            finally:
                # Re-pause even if the sleep was interrupted;
                # a failed advance must never leave the game
                # running.
                set_paused(ctx.client, True)
            unpaused_s = time.monotonic() - unpaused_start
            tick_after = _tick()
    except Exception as exc:  # noqa: BLE001
        _error(handler, 503, "RPC_ERROR",
               f"advance-clock failed: {exc}")
        return
    if not isinstance(tick_before, int) \
            or not isinstance(tick_after, int):
        _error(handler, 503, "RPC_ERROR",
               "advance-clock could not read the tick")
        return
    _json(handler, 200, {
        "ok": True, "tick_before": tick_before,
        "tick_after": tick_after,
        "advanced": tick_after - tick_before,
        "sleep_s": sleep_s,
        "unpaused_s": round(unpaused_s, 3)})

def quicksave(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    if ctx.daemon is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "quicksave needs the daemon")
        return
    # H3 (2026-11-27): the only RPC-touching handler that
    # did not hold rpc_lock. A quicksave unpauses the game
    # for up to 90 s; holding the lock for the call keeps
    # every other handler from reading while it runs.
    with ctx.rpc_lock:
        ctx.daemon._quicksave_if_due(force=True)
    _json(handler, 200, {"ok": True, "action": "quicksave",
                      "detail": "quicksave requested; see the "
                                "event log for the save event",
                      "evidence": None, "took_ms": 0})

def _daemon_pause(ctx: ServerContext, handler: BaseHTTPRequestHandler, paused: bool) -> None:
    if ctx.daemon is None:
        _error(handler, 503, "GAME_NOT_RUNNING",
               "daemon control needs the daemon")
        return
    ctx.daemon.set_loop_paused(paused)
    _json(handler, 200, {"ok": True, "loop_paused": paused})

def daemon_pause(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    _daemon_pause(ctx, handler, True)


def daemon_resume(ctx: ServerContext, handler: BaseHTTPRequestHandler, query: dict[str, list[str]], path: str, body: Optional[dict[str, Any]]) -> None:
    _daemon_pause(ctx, handler, False)
