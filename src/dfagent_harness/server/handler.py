from __future__ import annotations

import hmac
import json
import traceback
from http.server import BaseHTTPRequestHandler
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, unquote, urlparse

from .helpers import _error, _exact, _prefix, _prefix_suffix, HEALTH_PATH
from .routes_actions import action
from .routes_catalog import catalog, catalog_one
from .routes_events import advance, advance_clock, daemon_control, daemon_pause, daemon_resume, events, quicksave
from .routes_goals import goal_create, goal_delete, goal_done, goal_get, goals_list
from .routes_health import health, pause, state, status
from .routes_journal import diary_html, diary_read, diary_write, journal, memory_summary, memory_why
from .routes_observe import attention, cursor, snapshot
from .routes_spatial import area, areas, column, overview, path, sites, slice_, survey
from .routes_tasks import task_plan, task_run, tasks_list
from .routes_units import section, unit, units
from .routes_wiki import wiki, wiki_page


ROUTES: list[tuple[str, Callable[[str], bool],
                   Callable[..., None]]] = [
    ("GET", _exact("/v1/health"), health),
    ("GET", _exact("/v1/state"), state),
    ("GET", _exact("/v1/status"), status),
    ("GET", _exact("/v1/units"), units),
    ("GET", _prefix("/v1/unit/"), unit),
    ("GET", _exact("/v1/buildings"), section),
    ("GET", _exact("/v1/stocks"), section),
    ("GET", _exact("/v1/jobs"), section),
    ("GET", _exact("/v1/items"), section),
    ("GET", _exact("/v1/reports"), section),
    ("GET", _exact("/v1/map"), section),
    ("GET", _exact("/v1/wealth"), section),
    ("GET", _exact("/v1/slice"), slice_),
    ("GET", _exact("/v1/column"), column),
    ("GET", _exact("/v1/overview"), overview),
    ("GET", _exact("/v1/areas"), areas),
    ("GET", _prefix("/v1/area/"), area),
    ("GET", _exact("/v1/path"), path),
    ("GET", _exact("/v1/survey"), survey),
    ("GET", _exact("/v1/sites"), sites),
    ("GET", _exact("/v1/attention"), attention),
    ("GET", _exact("/v1/snapshot"), snapshot),
    ("GET", _exact("/v1/pause"), pause),
    ("GET", _exact("/v1/cursor"), cursor),
    ("GET", _exact("/v1/events"), events),
    ("GET", _exact("/v1/control/daemon"), daemon_control),
    ("GET", _exact("/v1/journal"), journal),
    ("GET", _exact("/v1/diary"), diary_read),
    ("GET", _exact("/v1/diary.html"), diary_html),
    ("GET", _prefix("/v1/memory/why/"), memory_why),
    ("GET", _exact("/v1/memory/summary"), memory_summary),
    ("GET", _exact("/v1/wiki"), wiki),
    ("GET", _prefix("/v1/wiki/"), wiki_page),
    ("GET", _exact("/v1/catalog"), catalog),
    ("GET", _prefix("/v1/catalog/"), catalog_one),
    ("GET", _exact("/v1/goals"), goals_list),
    ("GET", _prefix("/v1/goals/"), goal_get),
    ("GET", _exact("/v1/tasks"), tasks_list),
    ("GET", _prefix_suffix("/v1/tasks/", "/plan"), task_plan),
    ("POST", _prefix("/v1/actions/"), action),
    ("POST", _prefix("/v1/tasks/"), task_run),
    ("POST", _exact("/v1/goals"), goal_create),
    ("POST", _prefix_suffix("/v1/goals/", "/done"), goal_done),
    ("POST", _exact("/v1/control/quicksave"), quicksave),
    ("POST", _exact("/v1/control/advance"), advance),
    ("POST", _exact("/v1/control/advance-clock"), advance_clock),
    ("POST", _exact("/v1/control/diary"), diary_write),
    ("POST", _exact("/v1/control/daemon/pause"), daemon_pause),
    ("POST", _exact("/v1/control/daemon/resume"), daemon_resume),
    ("DELETE", _prefix("/v1/goals/"), goal_delete),
]


class Handler(BaseHTTPRequestHandler):
    """Thin HTTP plumbing: auth, JSON reading, dispatch.

    Every route is a plain function in a routes_* module taking
    (ctx, handler, query, path, body); this class only parses,
    authenticates, and dispatches through ROUTES. The context lives
    on the server instance (``server.ctx``), set by create_server.
    """

    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # keep stdout clean
                pass
    def _auth_ok(self, path: str) -> bool:
                if self.server.ctx.token is None or path == HEALTH_PATH:
                    return True
                auth = self.headers.get("Authorization", "")
                return hmac.compare_digest(auth, f"Bearer {self.server.ctx.token}")
    def _read_json(self) -> tuple[Optional[dict[str, Any]], bool]:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0:
                    return {}, True
                try:
                    raw = self.rfile.read(length)
                    body = json.loads(raw.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    _error(self, 400, "BAD_REQUEST",
                           "request body is not valid JSON")
                    return None, False
                if not isinstance(body, dict):
                    _error(self, 400, "BAD_REQUEST",
                           "request body must be a JSON object")
                    return None, False
                return body, True
    def _dispatch(self, method: str, path: str,
                          query: dict[str, list[str]],
                          body: Optional[dict[str, Any]]) -> bool:
                """Route (method, path) through the route table. The
                first matching route's handler writes the response.
                Returns True when a route matched, False when no route
                matched (the caller answers 404)."""
                for route_method, match, fn in ROUTES:
                    if route_method == method and match(path):
                        fn(self.server.ctx, self, query, path, body)
                        return True
                return False
    def _dispatch_safe(self, method: str, path: str,
                               query: dict[str, list[str]],
                               body: Optional[dict[str, Any]]
                               ) -> Optional[bool]:
                """Dispatch with the last-resort net (T3 row 2): a
                handler must never drop the connection. ValueError
                (bad client input) is 400; anything else is 502 with
                a traceback in the daemon log. Returns None when the
                net answered, so the caller must not answer again."""
                try:
                    return self._dispatch(method, path, query, body)
                except ValueError as exc:
                    try:
                        _error(self, 400, "BAD_REQUEST", str(exc))
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
                    try:
                        _error(self, 502, "RPC_ERROR",
                               "handler failed at the transport")
                    except (BrokenPipeError, ConnectionResetError):
                        pass
                return None
    def do_GET(self) -> None:  # noqa: N802 - http.server naming
                parsed = urlparse(self.path)
                query = parse_qs(parsed.query)
                path = unquote(parsed.path).rstrip("/") or "/"
                if not self._auth_ok(path):
                    _error(self, 401, "UNAUTHORIZED",
                           "missing or wrong bearer token")
                    return
                matched = self._dispatch_safe("GET", path, query, None)
                if matched is False:
                    _error(self, 404, "NOT_FOUND",
                           f"unknown endpoint: {path}")
    def do_POST(self) -> None:  # noqa: N802 - http.server naming
                parsed = urlparse(self.path)
                path = unquote(parsed.path).rstrip("/") or "/"
                if not self._auth_ok(path):
                    _error(self, 401, "UNAUTHORIZED",
                           "missing or wrong bearer token")
                    return
                body, ok = self._read_json()
                if not ok:
                    return
                assert body is not None
                matched = self._dispatch_safe("POST", path, {}, body)
                if matched is False:
                    _error(self, 404, "NOT_FOUND",
                           f"unknown endpoint: {path}")
    def do_DELETE(self) -> None:  # noqa: N802 - http.server naming
                parsed = urlparse(self.path)
                path = unquote(parsed.path).rstrip("/") or "/"
                if not self._auth_ok(path):
                    _error(self, 401, "UNAUTHORIZED",
                           "missing or wrong bearer token")
                    return
                matched = self._dispatch_safe("DELETE", path, {}, None)
                if matched is False:
                    _error(self, 404, "NOT_FOUND",
                           f"unknown endpoint: {path}")
