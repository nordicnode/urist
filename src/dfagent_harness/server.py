"""Agent-facing HTTP server for the DF Agent Harness (phase 4).

Stdlib only (``http.server``). The daemon (``daemon.py``) owns the
one DFHack RPC connection; this module serves it over HTTP/JSON on
``127.0.0.1`` only, with optional bearer-token auth (PROTOCOL.md
§3.3) and the typed action endpoints (PROTOCOL.md §4).

Routes:

* ``GET /v1/health`` — liveness, no auth required.
* ``GET /v1/state`` — full snapshot (poller snapshot when fresh,
  else a fresh collect).
* ``GET /v1/status`` — compact status (population, stocks, threats).
* ``GET /v1/units``, ``/v1/unit/{id}``, ``/v1/buildings``,
  ``/v1/jobs``, ``/v1/items``, ``/v1/reports``, ``/v1/map``,
  ``/v1/cursor`` — read-only state queries.
* ``GET /v1/journal`` — daemon journal (decisions + events).
* ``GET /v1/goals``, ``POST /v1/goals``, ``GET /v1/goals/{id}``,
  ``POST /v1/goals/{id}/done``, ``DELETE /v1/goals/{id}``.
* ``GET /v1/tasks``, ``GET /v1/tasks/{name}/plan``,
  ``POST /v1/tasks/{name}`` — composed tasks.
* ``GET /v1/events`` — SSE stream (``Accept: text/event-stream``)
  or JSON array (``?limit=N`` / ``?since=N``).
* ``POST /v1/actions/{pause,dig,undesignate,chop,gather,build,
  deconstruct,stockpile,order,order-remove,queue-job,labor,key,
  cursor,lua,command}`` — verified actions (action envelope).
  ``lua``/``command`` are guarded: disabled unless the daemon was
  started with ``allow_raw_actions``.
* ``POST /v1/control/quicksave``,
  ``GET /v1/control/daemon``,
  ``POST /v1/control/daemon/pause|resume`` — daemon control.

Errors follow PROTOCOL.md §6: HTTP status + ``{"error": {"code",
"message", "detail": ...}, "request_id": ...}``. ``503
GAME_NOT_RUNNING`` when the game is unreachable.
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
from dfhack_rpc.proto import CoreProtocol_pb2 as core
from dfhack_rpc.proto import RemoteFortressReader_pb2 as rfr

from .actions import JOB_SPECS, act, get_paused, set_paused
from .events import EventBus, EventPoller
from .planner import state_summary

__all__ = ["create_server", "run_server", "HEALTH_PATH", "KEYSYMS"]

HEALTH_PATH = "/v1/health"
_HEARTBEAT_SECONDS = 30.0

#: SDL 1.2 keysyms for PassKeyboardEvent (PROTOCOL.md §2.6).
KEYSYMS: dict[str, int] = {
    "down": 274, "up": 273, "left": 276, "right": 275,
    "enter": 13, "return": 13, "escape": 27, "esc": 27,
    "space": 32, "tab": 9, "backspace": 8,
    "pageup": 280, "pagedown": 281, "home": 278, "end": 279,
    "delete": 127, "insert": 277,
    "f1": 282, "f2": 283, "f3": 284, "f4": 285, "f5": 286,
    "f6": 287, "f7": 288, "f8": 289, "f9": 290, "f10": 291,
    "f11": 292, "f12": 293,
}
for _c in "abcdefghijklmnopqrstuvwxyz0123456789":
    KEYSYMS.setdefault(_c, ord(_c))
for _c in ",./;'[]\\-=":
    KEYSYMS.setdefault(_c, ord(_c))


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
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        pass


def _json(handler: BaseHTTPRequestHandler, status: int,
          payload: Any) -> None:
    body = json.dumps(payload).encode()
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    try:
        handler.wfile.write(body)
    except (BrokenPipeError, ConnectionResetError):
        # Client went away mid-response (e.g. dfh status timing
        # out); not an error worth a traceback in the daemon log.
        pass


def _sse_event(seq: int, payload: dict[str, Any]) -> bytes:
    return (f"id: {seq}\n"
            f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
            ).encode()


def _action_envelope(result: Any) -> dict[str, Any]:
    """Normalise an ActionResult (or dict) to the §4.1 envelope."""
    if isinstance(result, dict):
        return result
    return result.to_dict()


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
    but journal/goals/tasks return 503. ``token`` enables bearer auth
    on every route except ``/v1/health``. ``lock`` serialises RPC
    use with the poller (the daemon's single connection).
    """
    started = started_at if started_at is not None else time.time()
    rpc_lock = lock or threading.RLock()

    def get_state() -> dict[str, Any]:
        if poller is not None:
            state = poller.last_state
            if state is not None:
                return state
        if client is None:
            raise ConnectionError("no DFHack client and no poller state")
        from . import observe
        with rpc_lock:
            return observe.collect(client)

    def collect_section(section: str) -> dict[str, Any]:
        from . import observe
        if client is None:
            raise ConnectionError("no DFHack client")
        with rpc_lock:
            return observe.collect(client, sections=(section,))

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # keep stdout clean
            pass

        # -- plumbing ------------------------------------------------
        def _auth_ok(self, path: str) -> bool:
            if token is None or path == HEALTH_PATH:
                return True
            auth = self.headers.get("Authorization", "")
            return auth == f"Bearer {token}"

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

        def do_GET(self) -> None:  # noqa: N802 - http.server naming
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            path = parsed.path.rstrip("/") or "/"
            if not self._auth_ok(path):
                _error(self, 401, "UNAUTHORIZED",
                       "missing or wrong bearer token")
                return
            if path == HEALTH_PATH:
                self._health()
            elif path == "/v1/state":
                self._state(get_state)
            elif path == "/v1/status":
                self._status(get_state)
            elif path == "/v1/units":
                self._units(query, get_state)
            elif path.startswith("/v1/unit/"):
                self._unit(path, get_state)
            elif path == "/v1/buildings":
                self._section("buildings", collect_section)
            elif path == "/v1/jobs":
                self._section("jobs", collect_section)
            elif path == "/v1/items":
                self._section("items", collect_section)
            elif path == "/v1/reports":
                self._section("reports", collect_section)
            elif path == "/v1/map":
                self._section("map", collect_section)
            elif path == "/v1/cursor":
                self._cursor()
            elif path == "/v1/events":
                self._events(query)
            elif path == "/v1/control/daemon":
                self._daemon_control()
            elif path == "/v1/journal":
                self._journal(query)
            elif path == "/v1/goals":
                self._goals_list()
            elif path.startswith("/v1/goals/"):
                self._goal_get(path)
            elif path == "/v1/tasks":
                self._tasks_list()
            elif path.startswith("/v1/tasks/") and path.endswith("/plan"):
                self._task_plan(path)
            else:
                _error(self, 404, "NOT_FOUND",
                       f"unknown endpoint: {path}")

        def do_POST(self) -> None:  # noqa: N802 - http.server naming
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if not self._auth_ok(path):
                _error(self, 401, "UNAUTHORIZED",
                       "missing or wrong bearer token")
                return
            body, ok = self._read_json()
            if not ok:
                return
            assert body is not None
            if path.startswith("/v1/actions/"):
                self._action(path[len("/v1/actions/"):], body)
            elif path.startswith("/v1/tasks/"):
                self._task_run(path, body)
            elif path == "/v1/goals":
                self._goal_create(body)
            elif path.startswith("/v1/goals/") and path.endswith("/done"):
                self._goal_done(path)
            elif path == "/v1/control/quicksave":
                self._quicksave()
            elif path == "/v1/control/daemon/pause":
                self._daemon_pause(True)
            elif path == "/v1/control/daemon/resume":
                self._daemon_pause(False)
            else:
                _error(self, 404, "NOT_FOUND",
                       f"unknown endpoint: {path}")

        def do_DELETE(self) -> None:  # noqa: N802 - http.server naming
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            if not self._auth_ok(path):
                _error(self, 401, "UNAUTHORIZED",
                       "missing or wrong bearer token")
                return
            if path.startswith("/v1/goals/"):
                self._goal_delete(path)
            else:
                _error(self, 404, "NOT_FOUND",
                       f"unknown endpoint: {path}")

        # -- read endpoints ------------------------------------------
        def _health(self) -> None:
            version: dict[str, Any] = {}
            reachable = False
            if client is not None:
                try:
                    with rpc_lock:
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
                "daemon": "dfh/phase4",
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

        def _status(self, get_state_fn: Callable[[], dict[str, Any]]
                    ) -> None:
            try:
                state = get_state_fn()
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "DFHack RPC is not reachable",
                       {"error": str(exc)})
                return
            s = state_summary(state)
            _json(self, 200, {
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

        def _units(self, query: dict[str, list[str]],
                   get_state_fn: Callable[[], dict[str, Any]]) -> None:
            try:
                state = get_state_fn()
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "DFHack RPC is not reachable",
                       {"error": str(exc)})
                return
            units = state.get("units") or {}
            citizens = units.get("citizens") or []
            if query.get("citizens_only", [""])[0].lower() in ("1", "true"):
                out = citizens
            else:
                out = citizens + (units.get("hostiles") or [])
            try:
                limit = int(query.get("limit", ["100"])[0])
            except ValueError:
                limit = 100
            _json(self, 200, {"units": out[:max(1, min(limit, 1000))],
                              "citizen_count": len(citizens)})

        def _unit(self, path: str,
                  get_state_fn: Callable[[], dict[str, Any]]) -> None:
            try:
                unit_id = int(path[len("/v1/unit/"):])
            except ValueError:
                _error(self, 400, "BAD_REQUEST",
                       f"bad unit id: {path!r}")
                return
            try:
                state = get_state_fn()
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "DFHack RPC is not reachable",
                       {"error": str(exc)})
                return
            units = state.get("units") or {}
            found = next((c for c in (units.get("citizens") or [])
                          if c.get("id") == unit_id), None)
            if found is None:
                found = next((h for h in (units.get("hostiles") or [])
                              if h.get("id") == unit_id), None)
            if found is None:
                _error(self, 404, "NOT_FOUND",
                       f"no unit with id {unit_id}")
                return
            _json(self, 200, found)

        def _section(self, section: str,
                     collect_fn: Callable[[str], dict[str, Any]]) -> None:
            try:
                state = collect_fn(section)
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       f"section {section!r} unavailable",
                       {"error": str(exc)})
                return
            _json(self, 200, state.get(section, state))

        def _cursor(self) -> None:
            if client is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "no DFHack client")
                return
            try:
                from .ui import get_cursor
                with rpc_lock:
                    out = get_cursor(client)
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "cursor read failed", {"error": str(exc)})
                return
            _json(self, 200, {"cursor": (out.get("cursor") or [None] * 3)})

        def _daemon_control(self) -> None:
            payload = {
                "poll_count": poller.poll_count if poller else 0,
                "last_poll_ms": poller.last_poll_ms if poller else None,
                "event_seq": bus.latest_seq,
                "events_buffered": len(bus),
                "uptime_s": round(time.time() - started, 1),
            }
            if daemon is not None:
                payload.update(daemon.status())
            _json(self, 200, payload)

        def _journal(self, query: dict[str, list[str]]) -> None:
            if daemon is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "daemon journal is not available in this mode")
                return
            try:
                limit = int(query.get("limit", ["100"])[0])
            except ValueError:
                limit = 100
            kind = query.get("kind", [None])[0]
            decisions = daemon.journal.recent_decisions(
                limit=max(1, min(limit, 1000)))
            if kind:
                decisions = [d for d in decisions
                             if d.get("domain") == kind]
            _json(self, 200, {"decisions": decisions,
                              "counts": daemon.journal.decision_counts()})

        # -- goals ------------------------------------------------------
        def _goals_list(self) -> None:
            if daemon is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "goals need the daemon")
                return
            _json(self, 200, {"goals": daemon.journal.list_goals()})

        def _goal_get(self, path: str) -> None:
            if daemon is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "goals need the daemon")
                return
            try:
                gid = int(path[len("/v1/goals/"):])
            except ValueError:
                _error(self, 400, "BAD_REQUEST", "bad goal id")
                return
            goal = daemon.journal.get_goal(gid)
            if goal is None:
                _error(self, 404, "NOT_FOUND", f"no goal {gid}")
                return
            _json(self, 200, goal)

        def _goal_create(self, body: dict[str, Any]) -> None:
            if daemon is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "goals need the daemon")
                return
            name = body.get("name")
            expression = body.get("expression")
            task = body.get("task")
            if not name or not expression or not task:
                _error(self, 400, "BAD_REQUEST",
                       "goal needs name, expression and task")
                return
            gid = daemon.journal.create_goal(
                str(name), str(expression), str(task),
                int(body.get("priority", 5)))
            _json(self, 200, daemon.journal.get_goal(gid))

        def _goal_done(self, path: str) -> None:
            if daemon is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "goals need the daemon")
                return
            try:
                gid = int(path[len("/v1/goals/"):-len("/done")])
            except ValueError:
                _error(self, 400, "BAD_REQUEST", "bad goal id")
                return
            if not daemon.journal.mark_goal_done(gid):
                _error(self, 404, "NOT_FOUND", f"no goal {gid}")
                return
            _json(self, 200, daemon.journal.get_goal(gid))

        def _goal_delete(self, path: str) -> None:
            if daemon is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "goals need the daemon")
                return
            try:
                gid = int(path[len("/v1/goals/"):])
            except ValueError:
                _error(self, 400, "BAD_REQUEST", "bad goal id")
                return
            if not daemon.journal.delete_goal(gid):
                _error(self, 404, "NOT_FOUND", f"no goal {gid}")
                return
            _json(self, 200, {"ok": True, "deleted": gid})

        # -- tasks ------------------------------------------------------
        def _tasks_list(self) -> None:
            from .daemon import TASK_DEFS
            _json(self, 200, {"tasks": sorted(TASK_DEFS)})

        def _task_plan(self, path: str) -> None:
            from .daemon import TASK_DEFS
            name = path[len("/v1/tasks/"):-len("/plan")]
            spec = TASK_DEFS.get(name)
            if spec is None:
                _error(self, 404, "NOT_FOUND", f"unknown task {name!r}")
                return
            _json(self, 200, {
                "task": name,
                "steps": [
                    f"find the {spec['need']} workshop" if spec["need"]
                    else "find shrubs to gather",
                    f"queue {spec['job']}",
                    "wait (bounded) for the job to leave the job list",
                    "report completion or cancellation",
                ],
                "preconditions": [
                    f"a {spec['need']} workshop exists" if spec["need"]
                    else "shrubs exist on the surface",
                ],
            })

        def _task_run(self, path: str, body: dict[str, Any]) -> None:
            if daemon is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "tasks need the daemon")
                return
            name = path[len("/v1/tasks/"):]
            if name.endswith("/cancel"):
                _json(self, 200, {"ok": False,
                                  "detail": "no asynchronous task is "
                                            "running (tasks run "
                                            "synchronously)"})
                return
            wait = float(body.get("wait", 120))
            count = int(body.get("count", 1))
            out = daemon.run_task(name, wait=wait, count=count)
            _json(self, 200, out)

        # -- actions ----------------------------------------------------
        def _action(self, name: str, body: dict[str, Any]) -> None:
            if client is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "no DFHack client")
                return
            if name in ("lua", "command") and not allow_raw_actions:
                _error(self, 403, "BAD_REQUEST",
                       f"raw action {name!r} is disabled (start the "
                       f"daemon with allow_raw_actions to enable it)")
                return
            try:
                with rpc_lock:
                    result = self._dispatch_action(name, body)
            except ValueError as exc:
                _error(self, 400, "BAD_REQUEST", str(exc))
                return
            except Exception as exc:  # noqa: BLE001 - transport etc.
                _error(self, 502, "RPC_ERROR",
                       f"action {name!r} failed at the transport",
                       {"error": str(exc)})
                return
            _json(self, 200, result)

        def _dispatch_action(self, name: str,
                             body: dict[str, Any]) -> dict[str, Any]:
            if name == "pause":
                paused = bool(body.get("paused"))
                if set_paused(client, paused) != paused:
                    raise RuntimeError("pause flag did not stick")
                return {"ok": True, "action": "pause",
                        "detail": f"game {'paused' if paused else 'running'}",
                        "evidence": {"paused": paused}, "took_ms": 0}
            if name == "dig":
                box = body.get("box")
                mode = body.get("mode", "dig")
                return _action_envelope(act(
                    client, "designate_dig",
                    box=tuple(box), mode=mode))
            if name == "undesignate":
                return _action_envelope(act(
                    client, "designate_dig",
                    box=tuple(body.get("box")), mode="clear"))
            if name in ("chop", "gather"):
                return _action_envelope(act(
                    client, f"designate_{name}",
                    box=tuple(body.get("box")),
                    mark=bool(body.get("mark", True))))
            if name == "build":
                return _action_envelope(act(
                    client, "build_workshop", kind=body.get("kind"),
                    pos=tuple(body.get("pos"))))
            if name == "deconstruct":
                return _action_envelope(act(
                    client, "deconstruct_building",
                    building_id=int(body.get("building_id"))))
            if name == "stockpile":
                from .ui import create_stockpile
                display = (daemon.config.display if daemon is not None
                           else ":99")
                out = create_stockpile(
                    client, tuple(body.get("box")),
                    body.get("category", "f"), display=display)
                return {"ok": bool(out.get("ok")), "action": "stockpile",
                        "detail": str(out.get("reason")),
                        "evidence": {"building_id": out.get("building_id")},
                        "took_ms": 0}
            if name == "order":
                return _action_envelope(act(
                    client, "manager_order_create",
                    job_type=body.get("job_type"),
                    amount=int(body.get("amount", 1))))
            if name == "order-remove":
                return _action_envelope(act(
                    client, "manager_order_remove",
                    order_id=int(body.get("order_id"))))
            if name == "queue-job":
                return _action_envelope(act(
                    client, "queue_job",
                    building_id=int(body.get("building_id")),
                    job=body.get("job"),
                    count=int(body.get("count", 1))))
            if name == "labor":
                unit = body.get("unit_id", body.get("unit"))
                if isinstance(unit, str) and unit.isdigit():
                    unit = int(unit)
                return _action_envelope(act(
                    client, "labor_toggle", unit=unit,
                    labor=body.get("labor"),
                    on=bool(body.get("on", True))))
            if name == "key":
                return self._send_keys(body.get("keys") or [])
            if name == "cursor":
                from .ui import set_cursor
                out = set_cursor(client, *tuple(body.get("pos")))
                return {"ok": bool(out.get("ok")), "action": "cursor",
                        "detail": "cursor moved",
                        "evidence": {"cursor": out.get("cursor")},
                        "took_ms": 0}
            if name == "lua":
                text = client.run_lua(body.get("code", ""))
                return {"ok": True, "action": "lua",
                        "detail": "lua executed (raw, guarded)",
                        "evidence": {"text": text}, "took_ms": 0}
            if name == "command":
                cmd = body.get("command", "")
                args = body.get("args") or []
                text = client.run_command(cmd, *args)
                return {"ok": True, "action": "command",
                        "detail": f"ran DFHack command {cmd!r}",
                        "evidence": {"text": text}, "took_ms": 0}
            raise ValueError(f"unknown action {name!r}")

        def _send_keys(self, keys: list[str]) -> dict[str, Any]:
            unknown = [k for k in keys
                       if str(k).lower() not in KEYSYMS]
            if unknown:
                raise ValueError(f"unknown key(s): {unknown}")
            for key in keys:
                sym = KEYSYMS[str(key).lower()]
                for ev_type, state in ((2, 1), (3, 0)):
                    client.call(
                        "PassKeyboardEvent",
                        rfr.KeyboardEvent(type=ev_type, sym=sym,
                                          state=state,
                                          unicode=sym if 32 <= sym < 127
                                          else 0,
                                          scancode=0, mod=0),
                        core.EmptyMessage)
                    time.sleep(0.05)
            try:
                focus = client.run_lua(
                    "print(dfhack.gui.getCurFocus())")
            except Exception:  # noqa: BLE001 - viewscreen is best-effort
                focus = ""
            return {"ok": True, "action": "key",
                    "detail": f"sent keys {keys}; viewscreen now "
                              f"{focus.strip()!r}",
                    "evidence": {"viewscreen": focus.strip()},
                    "took_ms": 0}

        # -- events (SSE + JSON) ----------------------------------------
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

        # -- control ----------------------------------------------------
        def _quicksave(self) -> None:
            if daemon is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "quicksave needs the daemon")
                return
            daemon._quicksave_if_due(force=True)
            _json(self, 200, {"ok": True, "action": "quicksave",
                              "detail": "quicksave requested; see the "
                                        "event log for the save event",
                              "evidence": None, "took_ms": 0})

        def _daemon_pause(self, paused: bool) -> None:
            if daemon is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "daemon control needs the daemon")
                return
            daemon.set_loop_paused(paused)
            _json(self, 200, {"ok": True, "loop_paused": paused})

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
