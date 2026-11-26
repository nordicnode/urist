"""Minimal agent-facing HTTP server for the DF Agent Harness (phase 3).

Stdlib only (``http.server``), same shape as the daemon PROTOCOL.md
§3–§4 plans for phase 4 — phase 4 extends this module with auth,
the action endpoints and the planner; it does not replace it.

Routes (all ``127.0.0.1`` only, no auth in this phase — see the note
in :func:`create_server`):

* ``GET /v1/health`` — ``{"ok", "daemon", "df_reachable", "version"}``.
* ``GET /v1/state`` — latest snapshot passthrough: the poller's most
  recent state when one is available, else a fresh
  :func:`dfagent_harness.observe.collect`. (A fresh collect costs
  ~1.6 s; the poller snapshot is free.)
* ``GET /v1/events`` — Server-Sent Events when the client asks for
  ``text/event-stream``, else a JSON array of recent events.
  ``?since=<seq>`` (or the ``Last-Event-ID`` header) replays missed
  events from the bus ring, then continues live. ``?limit=N`` caps
  the JSON-array form (default 100). Each SSE message is
  ``id: <seq>`` + ``data: <event json>`` + blank line; a
  ``:heartbeat`` comment goes out every 30 s while idle.
* ``GET /v1/control/daemon`` — daemon state: tick count (polls),
  last poll duration, journal size, event seq, uptime.

Errors follow PROTOCOL.md §6: HTTP status + ``{"error": {"code",
"message", "detail": ...}, "request_id": ...}``. ``503
GAME_NOT_RUNNING`` when the game is unreachable for ``/v1/state``.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from dfhack_rpc import DFHackClient

from .events import EventBus, EventPoller

__all__ = ["create_server", "run_server", "HEALTH_PATH"]

HEALTH_PATH = "/v1/health"
_HEARTBEAT_SECONDS = 30.0


def _request_id() -> str:
    return uuid.uuid4().hex[:12]


def _error(handler: BaseHTTPRequestHandler, status: int, code: str,
           message: str, detail: Optional[dict[str, Any]] = None) -> None:
    body = json.dumps({
        "error": {"code": code, "message": message,
                  "detail": detail or {}},
        "request_id": _request_id(),
    }).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _json(handler: BaseHTTPRequestHandler, status: int,
          payload: Any) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _sse_event(seq: int, payload: dict[str, Any]) -> bytes:
    return (f"id: {seq}\n"
            f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
            ).encode()


def create_server(
        bus: EventBus,
        host: str = "127.0.0.1",
        port: int = 8765,
        client: Optional[DFHackClient] = None,
        poller: Optional[EventPoller] = None,
        started_at: Optional[float] = None) -> ThreadingHTTPServer:
    """Build (but do not start) the HTTP server.

    ``client`` is used for liveness/version on ``/v1/health`` and for
    a fresh ``/v1/state`` collect when no poller snapshot exists.
    ``poller`` (when given) supplies the snapshot and daemon stats.
    No authentication in this phase: the server binds localhost only,
    and PROTOCOL.md §3.3's bearer token is a phase-4 daemon item.
    """
    started = started_at if started_at is not None else time.time()

    def get_state() -> dict[str, Any]:
        if poller is not None:
            state = poller.last_state
            if state is not None:
                return state
        if client is None:
            raise ConnectionError("no DFHack client and no poller state")
        from . import observe
        return observe.collect(client)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # keep stdout clean
            pass

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            path = parsed.path.rstrip("/") or "/"
            if path == HEALTH_PATH:
                self._health()
            elif path == "/v1/state":
                self._state(get_state)
            elif path == "/v1/events":
                self._events(query)
            elif path == "/v1/control/daemon":
                self._daemon_control()
            else:
                _error(self, 404, "NOT_FOUND",
                       f"unknown endpoint: {path}")

        # -- endpoints ------------------------------------------------
        def _health(self) -> None:
            version: dict[str, Any] = {}
            reachable = False
            if client is not None:
                try:
                    version = client.get_version()
                    reachable = True
                except Exception:
                    reachable = False
            elif poller is not None and poller.last_state is not None:
                version = (poller.last_state.get("meta") or {}).get(
                    "version") or {}
                reachable = True
            _json(self, 200, {
                "ok": True,
                "daemon": "dfh-events/phase3",
                "df_reachable": reachable,
                "version": version,
            })

        def _state(self, get_state_fn: Callable[[], dict[str, Any]]
                   ) -> None:
            try:
                state = get_state_fn()
            except Exception as exc:  # noqa: BLE001 - game down, etc.
                _error(self, 503, "GAME_NOT_RUNNING",
                       "DFHack RPC is not reachable or state is "
                       "unavailable",
                       {"error": str(exc)})
                return
            _json(self, 200, state)

        def _daemon_control(self) -> None:
            _json(self, 200, {
                "poll_count": poller.poll_count if poller else 0,
                "last_poll_ms": poller.last_poll_ms if poller else None,
                "event_seq": bus.latest_seq,
                "events_buffered": len(bus),
                "uptime_s": round(time.time() - started, 1),
            })

        def _events(self, query: dict[str, list[str]]) -> None:
            accept = self.headers.get("Accept", "")
            wants_sse = "text/event-stream" in accept
            since_raw = (query.get("since", [None])[0]
                         or self.headers.get("Last-Event-ID"))
            since: Optional[int] = None
            if since_raw is not None:
                try:
                    since = int(since_raw)
                except ValueError:
                    _error(self, 400, "BAD_REQUEST",
                           f"bad since/Last-Event-ID: {since_raw!r}")
                    return
            if not wants_sse:
                try:
                    limit = int(query.get("limit", ["100"])[0])
                except ValueError:
                    _error(self, 400, "BAD_REQUEST",
                           "bad limit: must be an integer")
                    return
                limit = max(1, min(limit, 1000))
                events = bus.replay(since_seq=since, limit=limit)
                _json(self, 200, {"events": events,
                                  "latest_seq": bus.latest_seq})
                return
            # SSE stream: replay missed, then live. Replay first,
            # then subscribe, and skip anything the queue duplicates
            # (an event published between replay and subscribe would
            # otherwise be delivered twice).
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            replayed = bus.replay(since_seq=since)
            max_seen = max([e["seq"] for e in replayed],
                           default=since if since is not None else 0)
            pending: queue.Queue[dict[str, Any]] = queue.Queue()
            bus.subscribe(pending.put)
            try:
                for event in replayed:
                    self.wfile.write(_sse_event(event["seq"], event))
                self.wfile.flush()
                while True:
                    try:
                        event = pending.get(timeout=_HEARTBEAT_SECONDS)
                    except queue.Empty:
                        self.wfile.write(b":heartbeat\n\n")
                        self.wfile.flush()
                        continue
                    if event["seq"] <= max_seen:
                        continue
                    max_seen = event["seq"]
                    self.wfile.write(_sse_event(event["seq"], event))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass  # client went away; normal for SSE
            finally:
                bus.unsubscribe(pending.put)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def run_server(bus: EventBus, client: Optional[DFHackClient] = None,
               host: str = "127.0.0.1", port: int = 8765,
               poller: Optional[EventPoller] = None) -> None:
    """Build the server and serve forever (blocking). Starts the
    poller first when one is given. Intended for the CLI's ``--serve``
    mode and for phase 4's daemon; Ctrl-C stops it."""
    if poller is not None:
        poller.start()
    server = create_server(bus, host=host, port=port, client=client,
                           poller=poller)
    print(f"dfh-events serving on http://{host}:{port} "
          f"(health /v1/health, state /v1/state, events /v1/events)",
          flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if poller is not None:
            poller.stop()
        server.server_close()
