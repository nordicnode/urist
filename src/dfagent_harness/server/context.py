"""Server context: everything the route handlers close over.

The old ``server.py`` defined the HTTP handler class nested inside
``create_server()`` so every handler closed over a dozen variables
(client, daemon, rpc_lock, the get_state/get_areas closures, ...).
That nesting is what made the file un-splittable. The context is
that closure, made explicit: one dataclass built by ``create_server``
and passed to every route function. The spatial getters
(get_state, get_areas, get_survey, ...) are methods here, moved
verbatim from the old closures.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from dfhack_rpc import DFHackClient

from ..events import EventBus, EventPoller


@dataclass
class ServerContext:
    """Everything a route handler needs. Built once by create_server."""

    bus: EventBus
    client: Optional[DFHackClient]
    poller: Optional[EventPoller]
    daemon: Optional[Any]
    token: Optional[str]
    rpc_lock: threading.RLock
    started: float
    allow_raw_actions: bool
    spatial_cache: dict[str, Any] = field(
        default_factory=lambda: {"areas": None, "survey": None})
    store_holder: dict[str, Any] = field(
        default_factory=lambda: {"store": None})

    def get_state(self) -> dict[str, Any]:
        if self.poller is not None:
            state = self.poller.last_state
            if state is not None:
                return state
        if self.client is None:
            raise ConnectionError("no DFHack client and no poller state")
        from .. import observe
        from ..read_safety import paused_read
        with self.rpc_lock:
            # Read safety (world-model design §8): pause (verified),
            # read, restore the prior pause state. A refused read
            # surfaces as a 503 (outcome unknown), never a read
            # while running.
            return paused_read(self.client, lambda: observe.collect(self.client))
    def collect_section(self, section: str) -> dict[str, Any]:
        from .. import observe
        from ..read_safety import paused_read
        if self.client is None:
            raise ConnectionError("no DFHack client")
        with self.rpc_lock:
            return paused_read(
                self.client,
                lambda: observe.collect(self.client, sections=(section,)))
    def default_store(self) -> Any:
        if self.store_holder["store"] is None:
            from ..store import Store, default_world_db_path
            self.store_holder["store"] = Store(default_world_db_path())
        return self.store_holder["store"]
    def get_areas(self, refresh: bool = False) -> dict[str, Any]:
        from .. import observe, spatial
        from ..read_safety import paused_read
        if self.client is None:
            raise ConnectionError("no DFHack client")
        if self.spatial_cache["areas"] is not None and not refresh:
            return self.spatial_cache["areas"]
        t0 = time.monotonic()
        holder: dict[str, Any] = {}

        def _derive() -> dict[str, Any]:
            state = observe.collect(
                self.client, sections=("buildings", "units", "map",
                                  "status"))
            scan = spatial.scan_blocks(self.client)
            holder["scan"] = scan
            # Pin the surface level at the embark level from the
            # store (2026-11-27, external review Table 5 row 8):
            # the citizen-minimum heuristic drifts down as miners
            # dig, but the embark level never moves. A store read
            # failure here must not fail the derivation — fall back
            # to the heuristic.
            try:
                store = (self.daemon.store if self.daemon is not None
                         and getattr(self.daemon, "store", None) is not None
                         else self.default_store())
                embark_z = store.earliest_unit_z()
            except Exception:  # noqa: BLE001 - heuristic fallback
                embark_z = None
            return spatial.derive_areas(state, scan, embark_z=embark_z)

        with self.rpc_lock:
            # Re-check inside the lock (T3 row 7): two cold
            # requests used to both run the ~10 s derivation.
            # The cache is stored before the lock releases, so a
            # second caller waiting here always finds it warm.
            if self.spatial_cache["areas"] is not None and not refresh:
                return self.spatial_cache["areas"]
            areas = paused_read(self.client, _derive)
            areas["cost"] = {
                "tokens": spatial.estimate_tokens(
                    str(areas.get("areas", []))),
                "ms": int((time.monotonic() - t0) * 1000),
                "cached": False,
            }
            areas["stale"] = False
            self.spatial_cache["areas"] = areas
            # The scan is cached for the overview route (no second scan).
            if holder.get("scan") is not None:
                self.spatial_cache["scan"] = holder["scan"]
        return areas
    def enrich_area_descriptions(self, areas: dict[str, Any]) -> None:
        """Re-describe areas with the cached survey's vertical facts
        (magma, aquifer, first cavern) when a survey is cached.
        In place, idempotent — the derivation-time descriptions are
        graph-only, so this upgrades them whenever the survey exists.
        """
        from .. import spatial
        from ..survey import FORT_CENTRE
        cached_survey = self.spatial_cache.get("survey")
        if cached_survey is None:
            return
        descs = spatial.area_descriptions(
            areas["areas"], areas["graph"], cached_survey, FORT_CENTRE)
        for a in areas["areas"]:
            a["description"] = descs[a["id"]]
    def get_slice(self, x0: int, y0: int, z: int, x1: int, y1: int,
                      layer: str, allow_full: bool) -> dict[str, Any]:
        from .. import spatial
        from ..read_safety import paused_read
        from ..survey import FORT_CENTRE
        if self.client is None:
            raise ConnectionError("no DFHack client")
        landmarks = [{"x": FORT_CENTRE[0], "y": FORT_CENTRE[1],
                      "z": FORT_CENTRE[2], "char": "F",
                      "what": "fort centre (the embark point, "
                              "where the wagon stands)"}]
        with self.rpc_lock:
            out = paused_read(
                self.client,
                lambda: spatial.render_slice(
                    self.client, x0, y0, z, x1, y1, layer=layer,
                    allow_full=allow_full, landmarks=landmarks))
        # Areas overlapping this rect, from the cache only (never
        # triggers a scan). The key is always present — empty when
        # the areas have not been derived yet — so a client can
        # rely on it.
        cached = self.spatial_cache.get("areas")
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
    def get_column(self, x: int, y: int, levels: int,
                       from_z: Optional[int]) -> dict[str, Any]:
        from .. import column as column_mod
        from ..read_safety import paused_read
        if self.client is None:
            raise ConnectionError("no DFHack client")
        t0 = time.monotonic()
        cached = self.spatial_cache.get("areas")
        surface_z = (cached or {}).get("surface_z")
        with self.rpc_lock:
            col = paused_read(
                self.client,
                lambda: column_mod.read_column(self.client, x, y))
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
    def get_overview(self) -> dict[str, Any]:
        """Coarse overview from the cached scan + survey (no game
        read). Triggers the area derivation (which runs the scan)
        and the survey (which runs the scan) only if uncached."""
        from .. import spatial
        self.get_areas()
        survey_out = self.get_survey()
        scan = self.spatial_cache.get("scan")
        if scan is None:
            # The scan was derived before the cache was added (or
            # the areas came from an older cache): re-derive once.
            self.get_areas(refresh=True)
            scan = self.spatial_cache.get("scan")
        from ..survey import FORT_CENTRE
        out = spatial.render_overview(scan, survey_out, FORT_CENTRE)
        out["stale"] = bool(survey_out.get("stale"))
        return out
    def get_survey(self, refresh: bool = False) -> dict[str, Any]:
        from .. import observe, spatial, survey
        from ..read_safety import paused_read
        if self.client is None:
            raise ConnectionError("no DFHack client")
        cached = self.spatial_cache.get("survey")
        # Current tick (light status read) for the staleness check.
        with self.rpc_lock:
            now_tick = paused_read(
                self.client,
                lambda: (observe.collect(
                    self.client, sections=("status",)).get("status") or {}
                ).get("year_tick"))

        def _cached_copy(cached: dict[str, Any]) -> dict[str, Any]:
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

        if cached is not None and not refresh:
            return _cached_copy(cached)
        t0 = time.monotonic()

        def _run() -> dict[str, Any]:
            areas = self.get_areas()
            surface_blocks = set(areas.get("surface_blocks") or [])
            caverns = [a for a in areas.get("areas", [])
                       if a["kind"] == "cavern"]
            cavern_top = None
            if caverns:
                biggest = max(caverns, key=lambda a: a["blocks"])
                cavern_top = biggest["bbox"]["z1"]
            raw = survey.run_survey(self.client)
            return survey.build_survey(
                raw, surface_blocks=surface_blocks,
                cavern_top_z=cavern_top,
                tick=areas.get("derived_at_tick"))

        with self.rpc_lock:
            # Re-check inside the lock (T3 row 7): a second cold
            # request waits here while the first runs the ~25 s
            # survey, then finds the cache warm instead of
            # re-running it. The cache is stored before the lock
            # releases.
            cached = self.spatial_cache.get("survey")
            if cached is not None and not refresh:
                return _cached_copy(cached)
            built = paused_read(self.client, _run)
            built["stale"] = False
            built["cost"] = {
                "tokens": spatial.estimate_tokens(str(built.get(
                    "summary", []))),
                "ms": int((time.monotonic() - t0) * 1000),
                "scan_seconds": built.get("scan_seconds"),
                "cached": False,
            }
            self.spatial_cache["survey"] = built
        return built