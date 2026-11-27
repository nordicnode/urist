"""Agent-facing HTTP server for the DF Agent Harness (phase 4).

Stdlib only (``http.server``). The daemon (``daemon.py``) owns the
one DFHack RPC connection; this module serves it over HTTP/JSON on
``127.0.0.1`` only, with optional bearer-token auth (PROTOCOL.md
§3.3) and the typed action endpoints (PROTOCOL.md §4).

Routes:

* ``GET /v1/health`` — liveness, no auth required.
* ``GET /v1/state`` — full snapshot (poller snapshot when fresh,
  else a fresh collect).
* ``GET /v1/snapshot`` — the per-tick assembled snapshot
  (world-model design §6): full paused collect folded through the
  Context Assembler with the Store (diffing + trends) and the
  poller's detector (attention). Areas + survey from cache only.
* ``GET /v1/status`` — compact status (population, stocks, threats).
* ``GET /v1/units``, ``/v1/unit/{id}``, ``/v1/buildings``,
  ``/v1/jobs``, ``/v1/items``, ``/v1/reports``, ``/v1/map``,
  ``/v1/cursor`` — read-only state queries.
* ``GET /v1/slice?x0&y0&z&x1&y1&layer`` — one ASCII slice
  (world-model design §3.4; max 64x64, ``&full=1`` for a full
  z-level, flagged expensive). Coordinate rulers, the fort-centre
  landmark, the areas overlapping the rect, and what is directly
  above and below the slice, in plain words.
* ``GET /v1/column?x&y[&from_z=N][&levels=N]`` — vertical profile
  of one map column (standing directive 2026-11-26): strata from
  the top down in plain words, hazards (aquifer/magma/water), and
  the answer to "if I dig down N levels from here, what do I hit?"
* ``GET /v1/overview`` — coarse block-level overview of the whole
  map (a side cross-section through the fort + a top-down view of
  the fort's level), built from the cached scan + survey, no game
  read.
* ``GET /v1/areas``, ``/v1/area/{id|name}``, ``/v1/path?a&b`` —
  named areas + the connectivity graph (design §3; derived once
  from a full block scan, cached, ``?refresh=1`` re-derives).
  Every area carries a plain-words ``description`` (what it is,
  where, how big, what is in it, how to get there, what is above
  and below it).
* ``GET /v1/survey[?kind=water|magma|mineral|aquifer|plants|soil]``
  — resource survey (design §5; one ~25 s scan, cached, stale
  after one season; ``?refresh=1`` re-scans). Plain-words summary,
  nearest of each kind, vertical facts, hazards, cost.
* ``GET /v1/sites?kind=workshop|stockpile|zone|farm_plot|furniture|
  trap|room[&w=N][&h=N]`` — verified-free placement sites for a
  kind + size (the full detail behind the snapshot's compact
  placement section): each site verified free (terrain, occupancy,
  plants, units, overlap) AND reachable by a dwarf from the fort
  centre, with why each is good, plus the top blocked candidates
  with their reasons. Never guess coordinates — use these.
* ``GET /v1/attention`` — the attention section (design §6.1):
  threats first, then new arrivals, in plain words with position
  and class. Needs the daemon's poller (its diff record).
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
* ``POST /v1/control/diary`` — write the diary entry for a
  completed M1 day (the driver calls it at day-complete run end;
  the daemon's own day-boundary trigger cannot fire while its loop
  is paused for an M1 run).

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
from .read_safety import ReadRefused

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


def _needs_still_site(state: dict) -> bool:
    """True when the snapshot's suggestion would be a still build:
    drink is low and no Still exists. Used by _snapshot to decide
    whether deriving free workshop sites is worth the ~1 s cost —
    the snapshot never triggers a scan otherwise. The threshold is
    drink < 50, matching the proactive still suggestion in
    assembler.suggest (a still takes days to build + brew, so the
    model needs the site well before drink is critical)."""
    stocks = state.get("stocks") or {}
    drink = stocks.get("drink_units")
    if not isinstance(drink, int) or drink >= 50:
        return False
    buildings = state.get("buildings") or {}
    for b in buildings.get("list") or []:
        if b.get("type") == "Workshop" and b.get("subtype") == "Still":
            return False
    return True


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
        from .read_safety import paused_read
        with rpc_lock:
            # Read safety (world-model design §8): pause (verified),
            # read, restore the prior pause state. A refused read
            # surfaces as a 503 (outcome unknown), never a read
            # while running.
            return paused_read(client, lambda: observe.collect(client))

    def collect_section(section: str) -> dict[str, Any]:
        from . import observe
        from .read_safety import paused_read
        if client is None:
            raise ConnectionError("no DFHack client")
        with rpc_lock:
            return paused_read(
                client,
                lambda: observe.collect(client, sections=(section,)))

    # The State Store (world-model design §5). The daemon owns one
    # (daemon.store); a standalone server (no daemon) gets its own
    # lazily, so the snapshot route works without the daemon.
    _store_holder: dict[str, Any] = {"store": None}

    def _default_store() -> Any:
        if _store_holder["store"] is None:
            from .store import Store, default_world_db_path
            _store_holder["store"] = Store(default_world_db_path())
        return _store_holder["store"]

    # -- spatial model (world-model design §3) -------------------------
    # Areas + the connectivity graph are derived once from a full
    # block scan and cached in memory; re-derived on demand
    # (?refresh=1) or after a dig/build action. Never per tick.
    # The scan is slow (~10 s), so the derivation is one paused_read
    # holding a single pause for the collect + the scan.
    spatial_cache: dict[str, Any] = {"areas": None}

    def get_areas(refresh: bool = False) -> dict[str, Any]:
        from . import observe, spatial
        from .read_safety import paused_read
        if client is None:
            raise ConnectionError("no DFHack client")
        if spatial_cache["areas"] is not None and not refresh:
            return spatial_cache["areas"]
        t0 = time.monotonic()
        holder: dict[str, Any] = {}

        def _derive() -> dict[str, Any]:
            state = observe.collect(
                client, sections=("buildings", "units", "map",
                                  "status"))
            scan = spatial.scan_blocks(client)
            holder["scan"] = scan
            return spatial.derive_areas(state, scan)

        with rpc_lock:
            areas = paused_read(client, _derive)
        areas["cost"] = {
            "tokens": spatial.estimate_tokens(
                str(areas.get("areas", []))),
            "ms": int((time.monotonic() - t0) * 1000),
            "cached": False,
        }
        areas["stale"] = False
        spatial_cache["areas"] = areas
        # The scan is cached for the overview route (no second scan).
        if holder.get("scan") is not None:
            spatial_cache["scan"] = holder["scan"]
        return areas

    def _enrich_area_descriptions(areas: dict[str, Any]) -> None:
        """Re-describe areas with the cached survey's vertical facts
        (magma, aquifer, first cavern) when a survey is cached.
        In place, idempotent — the derivation-time descriptions are
        graph-only, so this upgrades them whenever the survey exists.
        """
        from . import spatial
        from .survey import FORT_CENTRE
        cached_survey = spatial_cache.get("survey")
        if cached_survey is None:
            return
        descs = spatial.area_descriptions(
            areas["areas"], areas["graph"], cached_survey, FORT_CENTRE)
        for a in areas["areas"]:
            a["description"] = descs[a["id"]]

    def get_slice(x0: int, y0: int, z: int, x1: int, y1: int,
                  layer: str, allow_full: bool) -> dict[str, Any]:
        from . import spatial
        from .read_safety import paused_read
        from .survey import FORT_CENTRE
        if client is None:
            raise ConnectionError("no DFHack client")
        landmarks = [{"x": FORT_CENTRE[0], "y": FORT_CENTRE[1],
                      "z": FORT_CENTRE[2], "char": "F",
                      "what": "fort centre (the embark point, "
                              "where the wagon stands)"}]
        with rpc_lock:
            out = paused_read(
                client,
                lambda: spatial.render_slice(
                    client, x0, y0, z, x1, y1, layer=layer,
                    allow_full=allow_full, landmarks=landmarks))
        # Areas overlapping this rect, from the cache only (never
        # triggers a scan). The key is always present — empty when
        # the areas have not been derived yet — so a client can
        # rely on it.
        cached = spatial_cache.get("areas")
        if cached is not None:
            out["areas_in_rect"] = [
                {"id": a["id"], "name": a["name"], "kind": a["kind"]}
                for a in cached["areas"]
                if a["bbox"]["x0"] <= x1 and a["bbox"]["x1"] >= x0
                and a["bbox"]["y0"] <= y1 and a["bbox"]["y1"] >= y0
                and a["bbox"]["z0"] <= z <= a["bbox"]["z1"]]
        else:
            out["areas_in_rect"] = []
        return out

    def get_column(x: int, y: int, levels: int,
                   from_z: Optional[int]) -> dict[str, Any]:
        from . import column as column_mod
        from .read_safety import paused_read
        if client is None:
            raise ConnectionError("no DFHack client")
        t0 = time.monotonic()
        cached = spatial_cache.get("areas")
        surface_z = (cached or {}).get("surface_z")
        with rpc_lock:
            col = paused_read(
                client,
                lambda: column_mod.read_column(client, x, y))
        if from_z is None:
            from_z = column_mod.ground_level(
                col.get("strata") or [], surface_z)
            if from_z is None:
                from_z = (surface_z if surface_z is not None
                          else col["z_count"] - 1)
        return column_mod.column_response(
            col, levels, from_z, surface_z=surface_z,
            ms=int((time.monotonic() - t0) * 1000),
            lua_ms=col.get("cost_ms", 0))

    def get_overview() -> dict[str, Any]:
        """Coarse overview from the cached scan + survey (no game
        read). Triggers the area derivation (which runs the scan)
        and the survey (which runs the scan) only if uncached."""
        from . import spatial
        areas = get_areas()
        survey_out = get_survey()
        scan = spatial_cache.get("scan")
        if scan is None:
            # The scan was derived before the cache was added (or
            # the areas came from an older cache): re-derive once.
            areas = get_areas(refresh=True)
            scan = spatial_cache.get("scan")
        from .survey import FORT_CENTRE
        out = spatial.render_overview(scan, survey_out, FORT_CENTRE)
        out["stale"] = bool(survey_out.get("stale"))
        return out

    # -- resource survey (world-model design §5) -----------------------
    # One full scan (~25 s wall, ~16 s Lua), cached in memory; the
    # scan is one pass for all kinds, so ?kind= only filters what is
    # returned. Re-surveyed on demand (?refresh=1) or once a season
    # (stale after 33,600 ticks). Never per tick. The reachability
    # proxy needs the surface region (from get_areas) and the depth
    # to the first cavern (the biggest cavern's top z).
    spatial_cache["survey"] = None

    def get_survey(refresh: bool = False) -> dict[str, Any]:
        from . import observe, spatial, survey
        from .read_safety import paused_read
        if client is None:
            raise ConnectionError("no DFHack client")
        cached = spatial_cache.get("survey")
        # Current tick (light status read) for the staleness check.
        with rpc_lock:
            now_tick = paused_read(
                client,
                lambda: (observe.collect(
                    client, sections=("status",)).get("status") or {}
                ).get("year_tick"))
        if cached is not None and not refresh:
            derived = cached.get("derived_at_tick")
            stale = (isinstance(now_tick, int)
                     and isinstance(derived, int)
                     and now_tick - derived > survey.SEASON_TICKS)
            out = dict(cached)
            out["stale"] = stale
            out["cost"] = {"tokens": spatial.estimate_tokens(
                str(cached.get("summary", []))),
                "ms": 0, "scan_seconds": cached.get("scan_seconds"),
                "cached": True}
            return out
        t0 = time.monotonic()

        def _run() -> dict[str, Any]:
            areas = get_areas()
            surface_blocks = set(areas.get("surface_blocks") or [])
            caverns = [a for a in areas.get("areas", [])
                       if a["kind"] == "cavern"]
            cavern_top = None
            if caverns:
                biggest = max(caverns, key=lambda a: a["blocks"])
                cavern_top = biggest["bbox"]["z1"]
            raw = survey.run_survey(client)
            return survey.build_survey(
                raw, surface_blocks=surface_blocks,
                cavern_top_z=cavern_top,
                tick=areas.get("derived_at_tick"))

        with rpc_lock:
            built = paused_read(client, _run)
        built["stale"] = False
        built["cost"] = {
            "tokens": spatial.estimate_tokens(str(built.get("summary",
                                                           []))),
            "ms": int((time.monotonic() - t0) * 1000),
            "scan_seconds": built.get("scan_seconds"),
            "cached": False,
        }
        spatial_cache["survey"] = built
        return built

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
                self._units(query, get_state, collect_section)
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
            elif path == "/v1/slice":
                self._slice(query, get_slice)
            elif path == "/v1/column":
                self._column(query, get_column)
            elif path == "/v1/overview":
                self._overview(get_overview)
            elif path == "/v1/areas":
                self._areas(query, get_areas)
            elif path.startswith("/v1/area/"):
                self._area(path, query, get_areas, get_slice)
            elif path == "/v1/path":
                self._path(query, get_areas)
            elif path == "/v1/survey":
                self._survey(query, get_survey)
            elif path == "/v1/sites":
                self._sites(query)
            elif path == "/v1/attention":
                self._attention()
            elif path == "/v1/snapshot":
                self._snapshot()
            elif path == "/v1/pause":
                # Fresh RPC read of the pause flag (not the poller's
                # cached state, which only updates while paused).
                # Used by run-script pre-flight checks.
                if client is None:
                    _error(self, 503, "GAME_NOT_RUNNING",
                           "no DFHack client")
                else:
                    try:
                        with rpc_lock:
                            paused = get_paused(client)
                        _json(self, 200, {"paused": paused})
                    except Exception as exc:  # noqa: BLE001
                        _error(self, 503, "RPC_ERROR",
                               f"pause read failed: {exc}")
            elif path == "/v1/cursor":
                self._cursor()
            elif path == "/v1/events":
                self._events(query)
            elif path == "/v1/control/daemon":
                self._daemon_control()
            elif path == "/v1/journal":
                self._journal(query)
            elif path == "/v1/diary":
                self._diary()
            elif path == "/v1/diary.html":
                self._diary_html()
            elif path.startswith("/v1/memory/why/"):
                self._memory_why(path)
            elif path == "/v1/memory/summary":
                self._memory_summary()
            elif path == "/v1/wiki":
                self._wiki(query)
            elif path.startswith("/v1/wiki/"):
                self._wiki_page(path)
            elif path == "/v1/catalog":
                self._catalog()
            elif path.startswith("/v1/catalog/"):
                self._catalog_one(path)
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
            elif path == "/v1/control/advance":
                self._advance()
            elif path == "/v1/control/advance-clock":
                self._advance_clock(body)
            elif path == "/v1/control/diary":
                self._diary(body)
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
            except ReadRefused as exc:
                # Read safety: pause could not be verified, so the
                # read was refused (outcome unknown). 503, retryable.
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
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
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
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
                   get_state_fn: Callable[[], dict[str, Any]],
                   collect_fn: Callable[[str], dict[str, Any]] | None
                   = None) -> None:
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
                if fresh and collect_fn is not None:
                    state = collect_fn("units")
                else:
                    state = get_state_fn()
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
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
                    _error(self, 400, "BAD_REQUEST",
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
                    _error(self, 400, "BAD_REQUEST",
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
            from . import attention as attention_mod
            cached_areas = spatial_cache.get("areas")
            surface_z = (cached_areas or {}).get("surface_z")
            described = [
                dict(rec, description=attention_mod.describe_unit(
                    rec, surface_z=surface_z))
                for rec in out[:limit]]
            _json(self, 200, {
                "units": described,
                "count": len(out),
                "citizen_count": len(citizens),
                "total_active_units": units.get("total_active_units"),
                "reconciled": units.get("reconciled"),
            })

        def _unit(self, path: str,
                  get_state_fn: Callable[[], dict[str, Any]]) -> None:
            try:
                unit_id = int(path[len("/v1/unit/"):])
            except ValueError:
                _error(self, 400, "BAD_REQUEST",
                       f"bad unit id: {path!r}")
                return
            # The full record for one unit of any class (design §4.2):
            # a single-unit probe, cheap, through the read-safety
            # gate. Citizens get the full record (profession, needs,
            # skills); other classes get the compact record plus
            # wounds, job and owner where applicable.
            if client is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "no DFHack client")
                return
            try:
                from .actions import _run_helper
                from .read_safety import paused_read
                with rpc_lock:
                    out = paused_read(
                        client,
                        lambda: _run_helper(
                            client, "probe_unit.lua",
                            {"id": unit_id}, timeout=30.0))
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "DFHack RPC is not reachable",
                       {"error": str(exc)})
                return
            if not out.get("ok", False):
                if out.get("kind") == "not_found":
                    _error(self, 404, "NOT_FOUND",
                           f"no unit with id {unit_id}")
                    return
                _error(self, 503, "GAME_NOT_RUNNING",
                       f"unit probe failed: {out.get('error')}")
                return
            from . import attention as attention_mod
            cached_areas = spatial_cache.get("areas")
            surface_z = (cached_areas or {}).get("surface_z")
            unit = dict(out["unit"])
            unit["description"] = attention_mod.describe_unit(
                unit, surface_z=surface_z)
            _json(self, 200, unit)

        def _section(self, section: str,
                     collect_fn: Callable[[str], dict[str, Any]]) -> None:
            try:
                state = collect_fn(section)
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       f"section {section!r} unavailable",
                       {"error": str(exc)})
                return
            _json(self, 200, state.get(section, state))

        # -- spatial model (world-model design §3) --------------------
        def _slice(self, query: dict[str, list[str]],
                   slice_fn: Callable[..., dict[str, Any]]) -> None:
            try:
                x0 = int(query["x0"][0])
                y0 = int(query["y0"][0])
                z = int(query["z"][0])
                x1 = int(query["x1"][0])
                y1 = int(query["y1"][0])
            except (KeyError, IndexError, ValueError):
                _error(self, 400, "BAD_REQUEST",
                       "slice needs integer x0,y0,z,x1,y1 params")
                return
            layer = query.get("layer", ["terrain"])[0]
            allow_full = query.get("full", [""])[0].lower() in (
                "1", "true")
            try:
                out = slice_fn(x0, y0, z, x1, y1, layer, allow_full)
            except ValueError as exc:
                _error(self, 400, "BAD_REQUEST", str(exc))
                return
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "slice unavailable", {"error": str(exc)})
                return
            _json(self, 200, out)

        def _column(self, query: dict[str, list[str]],
                    column_fn: Callable[..., dict[str, Any]]) -> None:
            try:
                x = int(query["x"][0])
                y = int(query["y"][0])
            except (KeyError, IndexError, ValueError):
                _error(self, 400, "BAD_REQUEST",
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
                    _error(self, 400, "BAD_REQUEST",
                           "from_z must be an integer")
                    return
            try:
                out = column_fn(x, y, levels, from_z)
            except ValueError as exc:
                _error(self, 400, "BAD_REQUEST", str(exc))
                return
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "column unavailable", {"error": str(exc)})
                return
            _json(self, 200, out)

        def _overview(self,
                      overview_fn: Callable[[], dict[str, Any]]
                      ) -> None:
            try:
                out = overview_fn()
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "overview unavailable", {"error": str(exc)})
                return
            _json(self, 200, out)

        def _areas(self, query: dict[str, list[str]],
                   areas_fn: Callable[[bool], dict[str, Any]]) -> None:
            refresh = query.get("refresh", [""])[0].lower() in (
                "1", "true")
            try:
                areas = areas_fn(refresh)
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "areas unavailable", {"error": str(exc)})
                return
            _enrich_area_descriptions(areas)
            from . import spatial
            areas["summary"] = spatial.area_summary(areas["areas"])
            _json(self, 200, areas)

        def _area(self, path: str, query: dict[str, list[str]],
                  areas_fn: Callable[[bool], dict[str, Any]],
                  slice_fn: Callable[..., dict[str, Any]]) -> None:
            from . import spatial
            ref = path[len("/v1/area/"):]
            if not ref:
                _error(self, 400, "BAD_REQUEST",
                       "area id or name required")
                return
            refresh = query.get("refresh", [""])[0].lower() in (
                "1", "true")
            try:
                areas = areas_fn(refresh)
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "areas unavailable", {"error": str(exc)})
                return
            _enrich_area_descriptions(areas)
            area = spatial.resolve_area(areas["areas"], ref)
            if area is None:
                _error(self, 404, "NOT_FOUND",
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
                sl = slice_fn(x0, y0, z, x1, y1, "terrain", False)
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "area slice unavailable", {"error": str(exc)})
                return
            _json(self, 200, {"area": area, "slice": sl})

        def _path(self, query: dict[str, list[str]],
                  areas_fn: Callable[[bool], dict[str, Any]]) -> None:
            from . import spatial
            a = (query.get("a") or [""])[0]
            b = (query.get("b") or [""])[0]
            if not a or not b:
                _error(self, 400, "BAD_REQUEST",
                       "path needs ?a=<area>&b=<area>")
                return
            try:
                areas = areas_fn(False)
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
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
                _error(self, 404, "NOT_FOUND",
                       f"unknown area: {a!r} or {b!r}")
                return
            ids = spatial.find_path(graph, a_id, b_id)
            if ids is None:
                _json(self, 200, {
                    "from": a_id, "to": b_id, "path": None,
                    "note": "no connection between these areas "
                            "(they are separated by solid rock; dig "
                            "a stairwell or tunnel to link them)"})
                return
            _json(self, 200, {
                "from": a_id, "to": b_id,
                "path": [{"id": i, "name": by_id[i]["name"],
                          "kind": by_id[i]["kind"],
                          "bbox": by_id[i]["bbox"]} for i in ids]})

        def _survey(self, query: dict[str, list[str]],
                    survey_fn: Callable[[bool], dict[str, Any]]) -> None:
            # ?kind= filters what is returned (the scan itself is one
            # pass for all kinds); ?refresh=1 forces a fresh scan
            # (~25 s). The response always carries the plain-words
            # summary, the vertical facts, the hazards, the cost, and
            # the staleness flag.
            kind = (query.get("kind") or ["all"])[0].lower()
            if kind not in ("all", "water", "magma", "mineral",
                            "aquifer", "plants", "soil"):
                _error(self, 400, "BAD_REQUEST",
                       "kind must be all|water|magma|mineral|"
                       "aquifer|plants|soil")
                return
            refresh = query.get("refresh", [""])[0].lower() in (
                "1", "true")
            try:
                out = survey_fn(refresh)
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "survey unavailable", {"error": str(exc)})
                return
            if kind == "all":
                _json(self, 200, out)
                return
            key = {"water": "water_bodies", "magma": "magma_bodies",
                   "mineral": "mineral_veins", "aquifer": "aquifer",
                   "plants": "plants",
                   "soil": "soil"}[kind]
            _json(self, 200, {
                "kind": kind, key: out.get(key),
                "summary": out.get("summary"),
                "hazards": out.get("hazards"),
                "vertical": out.get("vertical"),
                "stale": out.get("stale"),
                "derived_at_tick": out.get("derived_at_tick"),
                "cost": out.get("cost")})

        def _sites(self, query: dict[str, list[str]]) -> None:
            # GET /v1/sites?kind=workshop&w=3&h=3 — verified-free
            # sites for a placement kind + size (the full detail
            # behind the snapshot's compact placement section).
            # Each site is verified free (terrain, occupancy,
            # plants, units, overlap) AND reachable (canWalkBetween
            # from the fort centre). Blocked candidates carry their
            # reasons. A site is never returned as verified when its
            # reachability could not be checked.
            from .placement import PLACEMENT_KINDS
            kind = (query.get("kind") or ["workshop"])[0].lower()
            if kind not in PLACEMENT_KINDS:
                _error(self, 400, "BAD_REQUEST",
                       f"kind must be one of "
                       f"{', '.join(sorted(PLACEMENT_KINDS))}")
                return
            try:
                w = int((query.get("w") or [""])[0] or
                        PLACEMENT_KINDS[kind]["default_size"][0])
                h = int((query.get("h") or [""])[0] or
                        PLACEMENT_KINDS[kind]["default_size"][1])
            except ValueError:
                _error(self, 400, "BAD_REQUEST",
                       "w and h must be integers")
                return
            if w < 1 or h < 1 or w > 31 or h > 31:
                _error(self, 400, "BAD_REQUEST",
                       "w and h must be 1..31")
                return
            if daemon is None or getattr(daemon, "get_placement",
                                         None) is None:
                _error(self, 503, "NO_DAEMON",
                       "sites need the daemon's placement service")
                return
            t0 = time.monotonic()
            try:
                with rpc_lock:
                    out = daemon.get_placement(kind, w, h)
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "placement search failed", {"error": str(exc)})
                return
            out["cost"] = {"ms": int((time.monotonic() - t0) * 1000)}
            _json(self, 200, out)

        def _attention(self) -> None:
            # The attention section (world-model design §6.1): what is
            # wrong, what changed, what needs acting on — built live
            # from the poller's detector (its arrival record) and last
            # state. Needs the daemon's poller; without it there is no
            # diff record to build from. The surface level comes from
            # the CACHED areas only (never triggers a scan).
            from . import attention as attention_mod
            from .spatial import estimate_tokens
            if poller is None:
                _error(self, 503, "NO_POLLER",
                       "attention needs the daemon's poller (its diff "
                       "record); this server was started without one")
                return
            state = poller.last_state
            if state is None:
                _error(self, 503, "NO_POLLER_STATE",
                       "the poller has not collected a state yet")
                return
            t0 = time.monotonic()
            cached_areas = spatial_cache.get("areas")
            surface_z = (cached_areas or {}).get("surface_z")
            items = attention_mod.build_attention(
                state, poller.detector, surface_z=surface_z)
            text = "\n".join(it["text"] for it in items)
            _json(self, 200, {
                "attention": items,
                "tick": (state.get("status") or {}).get("year_tick"),
                "source": "poller detector arrivals + last state",
                "cost": {"tokens": estimate_tokens(text),
                         "ms": int((time.monotonic() - t0) * 1000)}})

        def _snapshot(self) -> None:
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
            from . import assembler, observe
            from .read_safety import ReadRefused, paused_read
            if client is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "no DFHack client")
                return
            t0 = time.monotonic()
            try:
                with rpc_lock:
                    state = paused_read(
                        client, lambda: observe.collect(client))
            except ReadRefused as exc:
                _error(self, 503, "READ_REFUSED", str(exc),
                       {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "GAME_NOT_RUNNING",
                       "snapshot collect failed", {"error": str(exc)})
                return
            store = (daemon.store if daemon is not None
                     and getattr(daemon, "store", None) is not None
                     else _default_store())
            detector = poller.detector if poller is not None else None
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
            if daemon is not None:
                sites = getattr(daemon, "_sites_cache", None)
                placement = getattr(daemon, "_placement_cache", None)
                cache_at = getattr(daemon, "_sites_cache_at", 0) or 0
                if (sites is None
                        or time.monotonic() - cache_at > 120):
                    if _needs_still_site(state):
                        try:
                            with rpc_lock:
                                sites = daemon._derive_sites(state)
                            daemon._sites_cache = sites
                            daemon._sites_cache_at = time.monotonic()
                            placement = getattr(
                                daemon, "_placement_cache", None)
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
                        with rpc_lock:
                            daemon.get_placement("workshop", 3, 3)
                        placement = getattr(
                            daemon, "_placement_cache", None)
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
                    areas=(spatial_cache.get("areas") or {}).get("areas"),
                    survey=spatial_cache.get("survey"),
                    sites=sites, placement=placement,
                    # The attention's vertical-distance text ("174
                    # levels below the fort") needs the fort's
                    # surface z — without it _where returns "" and
                    # the fix-6 gap text never reaches the snapshot
                    # (found live 2026-11-27: demons at z1 flagged
                    # [P2] with no level gap stated).
                    surface_z=(spatial_cache.get("areas") or {}).get(
                        "surface_z"))
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "SNAPSHOT_FAILED",
                       "assembler failed", {"error": str(exc)})
                return
            snap["cost"] = {"tokens": snap["tokens"],
                            "ms": int((time.monotonic() - t0) * 1000)}
            _json(self, 200, snap)

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

        # -- diary + memory (GOAL.md step 4) --------------------------
        def _diary(self) -> None:
            # The diary: entries parsed from diary.md in the daemon
            # state dir. No game read.
            from .daemon import default_state_dir
            from .diary import diary_md_path, parse_entries
            state_dir = daemon.state_dir if daemon is not None \
                else default_state_dir()
            md_path = diary_md_path(state_dir)
            entries = parse_entries(md_path.read_text()) \
                if md_path.exists() else []
            _json(self, 200, {"entries": entries,
                              "count": len(entries)})

        def _diary_html(self) -> None:
            # Serve the generated diary.html as a page.
            from .daemon import default_state_dir
            from .diary import diary_html_path
            state_dir = daemon.state_dir if daemon is not None \
                else default_state_dir()
            html_path = diary_html_path(state_dir)
            if not html_path.exists():
                _error(self, 404, "NOT_FOUND",
                       "no diary yet — the fort has not lived a day")
                return
            body = html_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _memory_why(self, path: str) -> None:
            # Death investigation: why did this dwarf die? The
            # Store's death record + diagnosis + the unit's history,
            # in plain words. No game read.
            try:
                unit_id = int(path[len("/v1/memory/why/"):])
            except ValueError:
                _error(self, 400, "BAD_REQUEST",
                       "unit id must be an integer")
                return
            store = daemon.store if daemon is not None \
                else _default_store()
            deaths = [d for d in store.deaths()
                      if d.get("unit_id") == unit_id]
            if not deaths:
                _error(self, 404, "NOT_FOUND",
                       f"no death recorded for unit {unit_id}")
                return
            death = deaths[-1]
            history = store.unit_history(unit_id)
            _json(self, 200, {
                "unit_id": unit_id,
                "death": death,
                "history": history,
                "answer": (
                    f"Unit {unit_id} died at tick "
                    f"{death.get('tick')} ({death.get('cause')}). "
                    f"History: {len(history)} daily samples; "
                    f"last sample {history[-1] if history else None}."),
            })

        def _memory_summary(self) -> None:
            # Re-grounding: the current situation + open problems +
            # recent failures, for a new session or a compacted
            # context. No game read — Store + Journal.
            store = daemon.store if daemon is not None \
                else _default_store()
            journal = daemon.journal if daemon is not None else None
            summary: dict[str, Any] = {
                "deaths": store.deaths()[-5:],
                "trends": {},
            }
            for metric in ("drink", "food", "wood", "population"):
                pts = store.trend_samples(metric)
                if pts:
                    summary["trends"][metric] = {
                        "latest": pts[-1][1],
                        "days_remaining": store.days_remaining(
                            metric, pts[-1][0]),
                    }
            if journal is not None:
                summary["recent_decisions"] = \
                    journal.recent_decisions(limit=10)
                summary["recent_events"] = journal.recent_events(
                    limit=10)
                # Failures: decisions that did not work, most recent.
                summary["failures"] = [
                    d for d in journal.recent_decisions(limit=100)
                    if d.get("ok") is False][:5]
            _json(self, 200, summary)

        def _wiki(self, query: dict[str, list[str]]) -> None:
            # Wiki lookup (GOAL.md step 5, layer 6): the agent asks
            # the harness for DF knowledge; the harness answers from
            # the local wiki export. No game read. mode=search is
            # the fast keyword fallback; hybrid (the default) fuses
            # FTS + semantic and is best for vague questions.
            q = query.get("q", [""])[0].strip()
            if not q:
                _error(self, 400, "BAD_REQUEST",
                       "missing ?q= (the question to look up)")
                return
            mode = query.get("mode", ["hybrid"])[0]
            try:
                limit = int(query.get("limit", ["5"])[0])
            except ValueError:
                limit = 5
            from . import wiki as wiki_mod
            try:
                result = wiki_mod.wiki_search(
                    q, mode=mode, limit=max(1, min(limit, 10)))
            except ValueError as exc:
                _error(self, 400, "BAD_REQUEST", str(exc))
                return
            except RuntimeError as exc:
                _error(self, 503, "WIKI_UNAVAILABLE", str(exc))
                return
            _json(self, 200, result)

        def _wiki_page(self, path: str) -> None:
            # Dump a whole wiki page by slug.
            slug = path[len("/v1/wiki/"):]
            if not slug or "/" in slug:
                _error(self, 400, "BAD_REQUEST",
                       "a wiki page slug has no '/' in it")
                return
            from . import wiki as wiki_mod
            try:
                result = wiki_mod.wiki_page(slug)
            except RuntimeError as exc:
                _error(self, 503, "WIKI_UNAVAILABLE", str(exc))
                return
            _json(self, 200, result)

        # -- action catalog (GOAL.md step 5, layer 1) ------------------
        def _catalog(self) -> None:
            # The self-describing catalog: every action, its
            # parameters, its constraints, an example call. Built
            # from the code, so it cannot drift from what the
            # harness actually does. No game read — it works even
            # with the game down.
            from . import catalog as catalog_mod
            _json(self, 200, catalog_mod.catalog())

        def _catalog_one(self, path: str) -> None:
            # One action's description, by name.
            name = path[len("/v1/catalog/"):]
            if not name or "/" in name:
                _error(self, 400, "BAD_REQUEST",
                       "an action name has no '/' in it")
                return
            from . import catalog as catalog_mod
            desc = catalog_mod.describe(name)
            if desc is None:
                from .actions import ACTIONS
                _error(self, 404, "UNKNOWN_ACTION",
                       f"no action named {name!r} — choose from: "
                       f"{', '.join(sorted(ACTIONS))}")
                return
            _json(self, 200, desc)

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

        def _placement_cache(self) -> Optional[dict[str, Any]]:
            # The daemon's verified-site cache (kind -> [site, ...]),
            # for the placement-aware build actions' verified-
            # alternative naming. None when the daemon has not
            # derived sites yet — the action then searches fresh.
            if daemon is None:
                return None
            return getattr(daemon, "_placement_cache", None)

        def _placement_from(self) -> Optional[tuple[int, int, int]]:
            # The walkable origin (the fort centre) the placement
            # cache's reachability was verified from. None when the
            # cache is missing — the action then cannot verify
            # reachability and says so instead of naming an
            # unverified site.
            cache = self._placement_cache()
            if not cache:
                return None
            frm = cache.get("from")
            return tuple(frm) if frm else None

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
                    pos=tuple(body.get("pos")),
                    placement=self._placement_cache(),
                    from_pos=self._placement_from()))
            if name == "deconstruct":
                return _action_envelope(act(
                    client, "deconstruct_building",
                    building_id=int(body.get("building_id"))))
            if name == "stockpile":
                # Programmatic stockpile (constructBuilding
                # abstract=true) — the ui.create_stockpile keystroke
                # route is forbidden for game actions. The body
                # takes pos + width/height + category (the old box
                # + single-letter category form is still accepted).
                box = body.get("box")
                if box is not None:
                    pos = (box[0], box[1], box[2])
                    width = box[3] - box[0] + 1
                    height = box[4] - box[1] + 1
                else:
                    pos = tuple(body.get("pos"))
                    width = int(body.get("width", 5))
                    height = int(body.get("height", 5))
                category = body.get("category", "food")
                if len(str(category)) == 1:
                    # Old single-letter form (f = food, w = wood,
                    # s = stone, r = refuse) from the ui route.
                    category = {"f": "food", "w": "wood",
                                "s": "stone", "r": "refuse"}.get(
                        str(category).lower(), str(category))
                return _action_envelope(act(
                    client, "create_stockpile", category=category,
                    pos=pos, width=width, height=height,
                    placement=self._placement_cache(),
                    from_pos=self._placement_from()))
            if name == "zone":
                return _action_envelope(act(
                    client, "create_zone",
                    zone_type=body.get("zone_type", "meeting_area"),
                    pos=tuple(body.get("pos")),
                    width=int(body.get("width", 5)),
                    height=int(body.get("height", 5)),
                    placement=self._placement_cache(),
                    from_pos=self._placement_from()))
            if name == "farm":
                return _action_envelope(act(
                    client, "build_farm_plot",
                    x=int(body.get("x")), y=int(body.get("y")),
                    z=int(body.get("z")),
                    width=int(body.get("width", 3)),
                    height=int(body.get("height", 3)),
                    placement=self._placement_cache(),
                    from_pos=self._placement_from()))
            if name == "furniture":
                return _action_envelope(act(
                    client, "build_furniture", kind=body.get("kind"),
                    pos=tuple(body.get("pos")),
                    placement=self._placement_cache(),
                    from_pos=self._placement_from()))
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
            # Registry names: the catalog (GET /v1/catalog) lists the
            # ACTIONS registry names (designate_gather, labor_toggle,
            # build_farm_plot, ...), so accept them here too, not just
            # the short aliases above. The model follows the catalog
            # and was getting "unknown action" for every catalog name
            # (M1, 2026-11-26). Coerce coordinate params from JSON
            # lists to tuples, as the alias branches do.
            from .actions import ACTIONS
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
                                  self._placement_cache())
                kwargs.setdefault("from_pos", self._placement_from())
                return _action_envelope(act(client, name, **kwargs))
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
        def _advance(self) -> None:
            """POST /v1/control/advance — the harness advance check.

            While time is not moving, check the current viewscreen; if
            a blocking screen is present, dismiss it programmatically
            (dialogs.advance, per the allowlist) and re-check. Names
            the last blocking screen in a zero-tick failure instead of
            timing out quietly. The M1 driver calls this when the clock
            does not advance during a window, so a modal can never
            stall a run silently. Returns the advance result dict.
            """
            if client is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "no DFHack client")
                return
            from . import dialogs
            try:
                with rpc_lock:
                    res = dialogs.advance(client, max_rounds=3,
                                         wait_s=2.0)
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "RPC_ERROR",
                       f"advance failed: {exc}")
                return
            if daemon is not None:
                for audit in res.get("cleared") or []:
                    daemon.journal.log_event(
                        "dialog_dismissed",
                        f"{audit.get('focus')} -> "
                        f"{audit.get('focus_after')} "
                        f"(dismissed={audit.get('dismissed')}, "
                        f"removed={audit.get('removed')})")
                if not res.get("ok") and res.get("blocked_by"):
                    daemon.journal.log_event(
                        "dialog_blocked",
                        f"advance refused {res.get('blocked_by')!r}: "
                        f"{res.get('reason')}")
            _json(self, 200, res)

        def _advance_clock(self, body: dict[str, Any]) -> None:
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
            if client is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "no DFHack client")
                return
            try:
                sleep_s = float(body.get("sleep_s") or 0.0)
            except (TypeError, ValueError):
                _error(self, 400, "BAD_REQUEST",
                       "sleep_s (number) is required")
                return
            sleep_s = max(0.25, min(sleep_s, 30.0))
            from . import observe
            from .read_safety import paused_read

            def _tick() -> int | None:
                st = paused_read(
                    client,
                    lambda: observe.collect(
                        client, sections=("status",)))
                return (st.get("status") or {}).get("year_tick")

            try:
                with rpc_lock:
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
                    set_paused(client, False)
                    try:
                        time.sleep(sleep_s)
                    finally:
                        # Re-pause even if the sleep was interrupted;
                        # a failed advance must never leave the game
                        # running.
                        set_paused(client, True)
                    unpaused_s = time.monotonic() - unpaused_start
                    tick_after = _tick()
            except Exception as exc:  # noqa: BLE001
                _error(self, 503, "RPC_ERROR",
                       f"advance-clock failed: {exc}")
                return
            if not isinstance(tick_before, int) \
                    or not isinstance(tick_after, int):
                _error(self, 503, "RPC_ERROR",
                       "advance-clock could not read the tick")
                return
            _json(self, 200, {
                "ok": True, "tick_before": tick_before,
                "tick_after": tick_after,
                "advanced": tick_after - tick_before,
                "sleep_s": sleep_s,
                "unpaused_s": round(unpaused_s, 3)})

        def _diary(self, body: dict[str, Any]) -> None:
            # POST /v1/control/diary — write the diary entry for a
            # completed M1 day. The daemon's planner loop is paused
            # during M1 runs, so its day-boundary trigger never
            # fires there; the driver calls this at day-complete run
            # end instead. The summary is built from the Store +
            # Journal exactly like the daemon trigger; the driver's
            # own record (its decisions + the run's start/end stocks,
            # parsed from its snapshots) is merged in via
            # diary.merge_driver_record — the run's decisions are not
            # in the Journal and no trend samples are taken while
            # the loop is paused. The entry itself is AI-written
            # (diary.write_ai_entry) from the per-dwarf feed — the
            # template renderer is retired from the write path
            # (Mikey: it reads as a list, not a diary entry). The
            # driver's run-end citizens are recorded first, so the
            # feed has today's per-dwarf samples. write_ai_body is
            # idempotent per date, so a later daemon-trigger write
            # for the same day replaces rather than duplicates. On
            # model failure the day is skipped (503 DIARY_FAILED);
            # a template list is never written instead.
            if daemon is None:
                _error(self, 503, "GAME_NOT_RUNNING",
                       "diary needs the daemon")
                return
            day_start = body.get("day_start_tick")
            if not isinstance(day_start, int):
                _error(self, 400, "BAD_REQUEST",
                       "day_start_tick (int) is required")
                return
            year = body.get("year") or 0
            fort = body.get("fort_name") or ""
            from .diary import (build_diary_feed,
                                merge_driver_record, write_ai_entry)
            from .dwarves import record_citizens
            from .freepi import FreePiClient
            try:
                citizens = body.get("citizens") or []
                if citizens:
                    # The run-end citizens are the dwarves' state at
                    # the end of the entry's day; clamp the stamp to
                    # the day's last tick so the feed sees them as
                    # the day's current sample (the run itself ends
                    # part-way into the next day).
                    tick_end = day_start + 1200 - 1
                    record_citizens(daemon.store, tick_end,
                                    citizens)
                citizens_start = body.get("citizens_start") or []
                tick_start = body.get("tick_start")
                if citizens_start and isinstance(tick_start, int):
                    record_citizens(daemon.store, tick_start,
                                    citizens_start)
                # Fresh stocks at the same moment as the run-end
                # citizens: the entry's closing numbers must come
                # from the same fresh run-end collect as the
                # per-dwarf samples, not a stale trend sample (run
                # 060346: the trend sample said drink 39, the live
                # game said 38 — two moments, two numbers). The
                # game is paused at run end, so this collect and
                # the citizens' values describe the same moment.
                # Best-effort: a failed collect falls back to the
                # driver's posted stocks, never fails the write.
                stocks_end = body.get("stocks_end") or {}
                try:
                    fresh = collect_section("stocks")
                    stocks = (fresh or {}).get("stocks") or {}
                    fresh_end: dict[str, Any] = {}
                    for key, field in (
                            ("drink", "drink_units"),
                            ("food", "food_units"),
                            ("wood", "wood_units"),
                            ("stone", "stone_units")):
                        val = stocks.get(field)
                        if isinstance(val, int):
                            fresh_end[key] = val
                    if citizens:
                        fresh_end["population"] = len(citizens)
                    if fresh_end:
                        stocks_end = fresh_end
                except Exception:  # noqa: BLE001 - best-effort
                    pass
                feed = build_diary_feed(
                    daemon.store, daemon.journal, day_start, fort,
                    year, state_dir=daemon.state_dir)
                merge_driver_record(
                    feed["summary"],
                    decisions=body.get("decisions") or [],
                    stocks_start=body.get("stocks_start") or {},
                    stocks_end=stocks_end)
                path = write_ai_entry(FreePiClient(),
                                      feed, daemon.state_dir)
            except Exception as exc:  # noqa: BLE001 - best-effort
                _error(self, 503, "DIARY_FAILED",
                       f"diary write failed: {exc}")
                return
            _json(self, 200, {"ok": True,
                              "date": feed["summary"]["date"],
                              "path": str(path)})

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
    # The spatial cache (areas + survey) is exposed on the server so
    # the daemon can fold the cached areas/survey into its per-tick
    # snapshot without triggering a scan.
    server.spatial_cache = spatial_cache
    # get_areas is exposed too, so the daemon can warm the areas on
    # demand when the cache is cold (2026-11-27, M1 run #11 tick 1:
    # after a daemon restart nothing had hit /v1/areas yet, so the
    # placement system returned "areas not cached", the still
    # suggestion named no site, and the model burned an idle tick).
    # The scan costs ~10-15 s and runs once per restart, only when
    # a site is actually needed — far cheaper than the idle tick.
    server.get_areas = get_areas
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
