"""Build the agent-facing HTTP server (factory).

``create_server`` assembles the ServerContext and the Handler;
``run_server`` is the blocking CLI entry point. The daemon-visible
attributes (``server.spatial_cache``, ``server.get_areas``) are set
here exactly as before, so the daemon keeps working unchanged.
"""
from __future__ import annotations

import threading
import time
from http.server import ThreadingHTTPServer
from typing import Any, Optional

from dfhack_rpc import DFHackClient

from .context import ServerContext
from ..events import EventBus, EventPoller
from .handler import Handler


def create_server(
        bus: EventBus,
        host: str = "127.0.0.1",
        port: int = 8765,
        client: Optional[DFHackClient] = None,
        poller: Optional[EventPoller] = None,
        started_at: Optional[float] = None,
        token: Optional[str] = None,
        allow_raw_actions: bool = False,
        lock: Optional[threading.RLock] = None,
        daemon: Optional[Any] = None) -> ThreadingHTTPServer:
    """Build (but do not start) the HTTP server.

    ``daemon`` (when given) supplies the journal, goals, tasks and
    planner control; without it the read/action endpoints still work
    but journal/goals/tasks return 503. ``token`` enables bearer
    authentication on every route except ``/v1/health``. ``lock``
    serialises RPC use with the poller (the daemon's single
    connection).
    """
    started = started_at if started_at is not None else time.time()
    rpc_lock = lock or threading.RLock()
    ctx = ServerContext(
        bus=bus, client=client, poller=poller, daemon=daemon,
        token=token, rpc_lock=rpc_lock, started=started,
        allow_raw_actions=allow_raw_actions)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    server.ctx = ctx
    # The spatial cache (areas + survey) is exposed on the server so
    # the daemon can fold the cached areas/survey into its per-tick
    # snapshot without triggering a scan.
    server.spatial_cache = ctx.spatial_cache
    # get_areas is exposed too, so the daemon can warm the areas on
    # demand when the cache is cold (2026-11-27, M1 run #11 tick 1:
    # after a daemon restart nothing had hit /v1/areas yet, so the
    # placement system returned "areas not cached", the still
    # suggestion named no site, and the model burned an idle tick).
    # The scan costs ~10-15 s and runs once per restart, only when
    # a site is actually needed — far cheaper than the idle tick.
    server.get_areas = ctx.get_areas
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
