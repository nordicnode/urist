"""The dfh daemon (phase 4).

One process owns the single DFHack RPC connection and serves all
agents over HTTP (PROTOCOL.md §3): the phase-3 event server extended
with bearer-token auth, the typed action endpoints, the composed
task/goal endpoints, and the autonomous planner loop.

Layout (state dir, default ``~/.config/df-agent-harness``):

* ``config.json`` — ports, poll intervals, thresholds (all optional;
  defaults below).
* ``token`` — bearer token, mode 0600, generated on first start.
  ``DFH_AGENT_TOKEN`` overrides it; ``--no-auth`` disables auth
  (localhost-only still applies).
* ``journal.db`` — SQLite journal (planner decisions, daemon events,
  goals).
* ``events.jsonl`` — event bus journal (SSE replay survives restarts).
* ``drain-offset.json`` — watcher JSONL byte offset (phase-3
  limitation fixed: restarts resume, not replay).
* ``daemon.pid`` / ``daemon.port`` — lifecycle files for ``dfh``.

Lifecycle: ``dfh start`` (background, writes pid file),
``dfh stop`` (SIGTERM -> graceful shutdown: drain + flush journal),
``dfh status``, ``dfh daemon`` (foreground, for debugging).
"""

from __future__ import annotations

import faulthandler
import json
import os
import re
import secrets
import signal
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from dfhack_rpc import DFHackClient

from . import observe
from .actions import act, get_paused, set_paused
from .assembler import TICKS_PER_DAY
from .events import (
    DEFAULT_WATCH_LOG,
    EventBus,
    EventPoller,
    WatcherDrainer,
    install_watcher,
    make_event,
)
from .planner import Journal, Planner, state_summary
from .server import create_server
from .store import Store, diagnose_death
from .ui import appoint_noble as ui_appoint_noble
from .ui import create_stockpile as ui_create_stockpile

__all__ = [
    "Daemon",
    "DaemonConfig",
    "default_state_dir",
    "evaluate_goal",
    "load_config",
    "load_or_create_token",
]

DEFAULT_HTTP_PORT = 8765
DEFAULT_DF_PORT = 5000
DEFAULT_DF_HOST = "127.0.0.1"
DEFAULT_DISPLAY = ":99"


def default_state_dir() -> Path:
    """``~/.config/df-agent-harness`` (or ``$XDG_CONFIG_HOME/...``)."""
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "df-agent-harness"
    return Path.home() / ".config" / "df-agent-harness"


@dataclass
class DaemonConfig:
    """Daemon configuration (JSON file + CLI overrides)."""

    http_host: str = "127.0.0.1"
    http_port: int = DEFAULT_HTTP_PORT
    df_host: str = DEFAULT_DF_HOST
    df_port: int = DEFAULT_DF_PORT
    display: str = DEFAULT_DISPLAY
    df_dir: str = ""  # default: <repo>/third_party/df_47_05
    allow_raw_actions: bool = False
    no_auth: bool = False
    # Poll load measured 2026-11-26 (game paused): lite collect
    # ~1.6s every 2.0s + planner ~3s/30s + slow ~5s/30s = ~98% RPC
    # server saturation -> queueing -> 30s timeouts -> stale replies.
    # 6s/60s cuts that to ~40%: the poller is a watcher, not a
    # real-time feed (the planner does its own full collect).
    fast_interval: float = 6.0
    paused_interval: float = 10.0
    slow_interval: float = 60.0
    planner_interval: float = 30.0
    planner_max_actions: int = 2
    backoff_s: float = 180.0
    quicksave_interval: float = 3600.0
    drink_warn: int = 20
    drink_critical: int = 5
    food_warn: int = 15
    food_critical: int = 5

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DaemonConfig":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config(state_dir: Path) -> DaemonConfig:
    """Load ``config.json`` from the state dir (defaults when absent
    or malformed)."""
    path = state_dir / "config.json"
    try:
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            return DaemonConfig.from_dict(data)
    except (OSError, ValueError):
        pass
    return DaemonConfig()


def save_config(state_dir: Path, config: DaemonConfig) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "config.json").write_text(
        json.dumps(config.to_dict(), indent=2))


def load_or_create_token(state_dir: Path,
                         no_auth: bool = False) -> Optional[str]:
    """Return the bearer token, or None when auth is disabled.

    ``DFH_AGENT_TOKEN`` wins; else the token file (created on first
    run, mode 0600); ``no_auth`` disables auth entirely.
    """
    if no_auth:
        return None
    env = os.environ.get("DFH_AGENT_TOKEN")
    if env:
        return env
    path = state_dir / "token"
    try:
        token = path.read_text().strip()
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_hex(16)
    state_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(token + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


_GOAL_EXPR = re.compile(
    r"^\s*(drink|food|population|idlers|threats|wood|stone|barrels|seeds)"
    r"\s*(>=|<=|==|!=|>|<)\s*(\d+)\s*$")


def evaluate_goal(expression: str, state: dict[str, Any]) -> Optional[bool]:
    """Evaluate a goal expression (``drink >= 40``) over live state.

    Returns None for an unparseable expression. Only the listed
    variables and comparison operators are supported — no ``eval``.
    """
    m = _GOAL_EXPR.match(expression or "")
    if not m:
        return None
    name, op, raw = m.group(1), m.group(2), int(m.group(3))
    s = state_summary(state)
    value = {
        "drink": s["drink"], "food": s["food"],
        "population": s["citizens"], "threats": len(s["hostiles"]),
        "wood": s["wood"], "stone": s["stone"],
        "barrels": s["barrels"], "seeds": s["seeds"],
        "idlers": sum(1 for c in s["citizen_list"] if c.get("idle")),
    }[name]
    return {"==": value == raw, "!=": value != raw,
            ">": value > raw, "<": value < raw,
            ">=": value >= raw, "<=": value <= raw}[op]


# ----------------------------------------------------------------------
# Composed tasks (PROTOCOL.md §4.3): action + end-effect verification
# ----------------------------------------------------------------------

#: task name -> (act name, kwargs builder, end-effect check).
#: The end effect is verified by re-reading state after the job is
#: queued and (bounded) waiting for the queued job to leave the job
#: list — a job that disappears was worked (or cancelled; the
#: cancellation is detected via the newest report).
TASK_DEFS: dict[str, dict[str, Any]] = {
    "brew": {"action": "queue_job", "job": "brew",
             "need": "still", "wait_job": "CustomReaction"},
    "cook": {"action": "queue_job", "job": "cook",
             "need": "kitchen", "wait_job": "PrepareMeal"},
    "make_bed": {"action": "queue_job", "job": "make_bed",
                 "need": "carpenter", "wait_job": "CustomReaction"},
    "make_barrel": {"action": "queue_job", "job": "make_barrel",
                    "need": "carpenter", "wait_job": "CustomReaction"},
    "gather": {"action": "designate_gather",
               "need": None, "wait_job": "GatherPlants"},
}


def _find_workshop(state: dict[str, Any],
                   subtype: str) -> Optional[dict[str, Any]]:
    for b in (state.get("buildings") or {}).get("list") or []:
        if b.get("type") == "Workshop" and b.get("subtype") == subtype:
            return b
    return None


def _fort_centre(areas: dict[str, Any]) -> Optional[tuple[int, int]]:
    """The fort centre: the Surface area's bbox centre (the embark
    centre, where the wagon lands). NOT the median citizen position
    — the citizens scatter and the median drifts to the map edge
    (verified live: median (53, 9) while the fort is at (97, 97))."""
    for a in areas.get("areas") or []:
        if a.get("kind") == "surface":
            b = a.get("bbox") or {}
            if "x0" in b and "x1" in b and "y0" in b and "y1" in b:
                return ((b["x0"] + b["x1"]) // 2,
                        (b["y0"] + b["y1"]) // 2)
            return None
    return None


class Daemon:
    """Owns the RPC connection, the poller, the planner, the journal
    and the HTTP server. One instance per process."""

    def __init__(self, config: Optional[DaemonConfig] = None,
                 state_dir: Optional[Path] = None,
                 repo_dir: Optional[Path] = None) -> None:
        self.config = config or DaemonConfig()
        self.state_dir = Path(state_dir) if state_dir else default_state_dir()
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.repo_dir = (Path(repo_dir) if repo_dir else
                         Path(__file__).resolve().parent.parent.parent)
        df_dir = (Path(self.config.df_dir) if self.config.df_dir else
                  self.repo_dir / "third_party" / "df_47_05")
        self.df_dir = df_dir
        self.watch_log = df_dir / "dfh-events.jsonl"
        self.token = load_or_create_token(self.state_dir,
                                          self.config.no_auth)
        self.lock = threading.RLock()
        self.client: Optional[DFHackClient] = None
        self.bus: Optional[EventBus] = None
        self.poller: Optional[EventPoller] = None
        self.planner: Optional[Planner] = None
        self.journal = Journal(self.state_dir / "journal.db")
        # Milestone 5: the State Store (world.db) — the world
        # model's system of record, alongside journal.db. One
        # Store per daemon; the HTTP server reuses it (daemon.store).
        self.store = Store(self.state_dir / "world.db")
        self._deaths_recorded: set[int] = set()
        self.server = None
        self._stop = threading.Event()
        self._planner_thread: Optional[threading.Thread] = None
        self._loop_paused = False  # autonomous loop paused (game runs)
        self.started_at = time.time()
        self._last_quicksave = time.time()
        # NB: initialised to "now", not 0.0 — with 0.0 the first
        # planner tick thinks a quicksave is ~1.7e9 s overdue and
        # fires one immediately (observed live 2026-11-26: a save
        # landed ~30 s after daemon start, and the game died right
        # after it).
        self._recent_events: list[dict[str, Any]] = []
        self._goal_check_at = 0.0
        # Placement cache (kind -> [verified site, ...]): populated
        # by _derive_sites on each planner tick. A site is verified
        # free + reachable (canWalkBetween from the fort centre).
        # None until the first derivation; the snapshot and the
        # /v1/sites route derive on demand when it is missing.
        self._placement_cache: Optional[dict[str, Any]] = None
        self._placement_cache_at = 0.0

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Connect, install the watcher, start poller + planner + HTTP.
        Blocks only for the HTTP server (call :meth:`serve_forever`)."""
        # SIGUSR1 dumps every thread's stack to stderr (daemon.log)
        # without killing the daemon — the diagnostic for a wedged
        # planner/poller loop (a stall leaves no other trace).
        try:
            faulthandler.register(signal.SIGUSR1)
        except Exception:  # noqa: BLE001 - best-effort diagnostics
            pass
        self.client = DFHackClient(self.config.df_host,
                                   self.config.df_port, timeout=30.0)
        self.client.connect()
        try:
            install_watcher(self.client, self.watch_log)
        except Exception as exc:  # noqa: BLE001 - watcher is best-effort
            self.journal.log_event(
                "daemon_error", f"watcher install failed: {exc}")
        self.bus = EventBus(
            maxlen=1000,
            journal_path=self.state_dir / "events.jsonl")
        self.bus.subscribe(self._remember_event)
        drainer = WatcherDrainer(
            self.watch_log,
            offset_path=self.state_dir / "drain-offset.json")
        self.poller = EventPoller(
            self.client, self.bus, drainer=drainer,
            fast_interval=self.config.fast_interval,
            paused_interval=self.config.paused_interval,
            slow_interval=self.config.slow_interval,
            lock=self.lock)
        self.planner = Planner(
            self.client, self.journal,
            backoff_s=self.config.backoff_s,
            max_actions_per_tick=self.config.planner_max_actions,
            display=self.config.display,
            ui_appoint=ui_appoint_noble,
            ui_stockpile=ui_create_stockpile)
        self.poller.start()
        self.bus.publish(make_event(
            "daemon_started", "info",
            {"version": "phase4", "pid": os.getpid()},
            source="daemon"))
        self.journal.log_event("daemon_started",
                               f"pid {os.getpid()}")
        self.server = create_server(
            self.bus, host=self.config.http_host,
            port=self.config.http_port, client=self.client,
            poller=self.poller, started_at=self.started_at,
            token=self.token,
            allow_raw_actions=self.config.allow_raw_actions,
            lock=self.lock, daemon=self)
        self._planner_thread = threading.Thread(
            target=self._planner_loop, daemon=True,
            name="dfh-planner")
        self._planner_thread.start()

    def serve_forever(self) -> None:
        """Serve HTTP until SIGTERM/SIGINT (foreground mode)."""
        if self.server is None:
            raise RuntimeError("daemon not started")
        try:
            self.server.serve_forever()
        finally:
            self.stop()

    def stop(self) -> None:
        """Graceful shutdown: stop the planner + poller, drain once,
        flush the journal, close the server and the RPC connection."""
        if self._stop.is_set():
            return
        self._stop.set()
        if self.planner is not None:
            self._quicksave_if_due(force=True)
        if self.poller is not None:
            self.poller.stop(timeout=5.0)
        if self.bus is not None:
            self.bus.publish(make_event(
                "daemon_stopped", "info",
                {"version": "phase4", "pid": os.getpid()},
                source="daemon"))
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.client is not None:
            try:
                self.client.close()
            except Exception:  # noqa: BLE001 - shutdown is best-effort
                pass
        self.journal.log_event("daemon_stopped", "graceful")
        self.journal.close()
        self.store.close()

    # -- event memory ----------------------------------------------------
    def _remember_event(self, event: dict[str, Any]) -> None:
        self._recent_events.append(event)
        if len(self._recent_events) > 200:
            self._recent_events = self._recent_events[-200:]

    # -- planner loop ----------------------------------------------------
    def _pause_guard(self) -> None:
        """GUARD 4 — while the daemon loop is paused, the game must
        be paused. If the loop is paused but the game is running,
        re-pause it at once and log an anomaly. This closes the
        'game running free with no driver' hole (2026-11-26: a
        reload loaded the drink-0 backup and the game ran unpaused
        with no driver). A failed guard read must not kill the loop;
        the next iteration retries."""
        if not self._loop_paused or self.client is None:
            return
        try:
            if not get_paused(self.client):
                with self.lock:
                    set_paused(self.client, True)
                self.journal.log_event(
                    "pause_guard",
                    "loop paused but game was running; re-paused")
                print("dfh pause_guard: game was running while loop "
                      "paused; re-paused", flush=True)
        except Exception as exc:  # noqa: BLE001 - retry next tick
            print(f"dfh pause_guard: check failed: {exc}", flush=True)

    def _planner_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._pause_guard()
                self._planner_tick()
            except Exception as exc:  # noqa: BLE001 - loop must not die
                self.journal.log_event("daemon_error",
                                       f"planner tick failed: {exc}")
            self._stop.wait(self.config.planner_interval)

    def _planner_tick(self) -> None:
        if self._loop_paused or self.poller is None \
                or self.planner is None or self.client is None:
            print("dfh planner: tick skipped (loop paused or not "
                  "ready)", flush=True)
            return
        # Focus first, before any world-state read: a full collect
        # during map load crashed DF twice (2026-11-26, double-free
        # abort at "Resetting textures"). The probe reads GUI state
        # only; the collect below runs only once a fort is loaded.
        from .ui import fort_loaded, get_focus
        try:
            probe = get_focus(self.client, timeout=10.0)
            focus = probe.get("focus") if probe.get("ok") else None
        except Exception as exc:  # noqa: BLE001 - retry next tick
            print(f"dfh planner: focus probe failed: {exc}", flush=True)
            return
        if not fort_loaded(focus):
            print(f"dfh planner: tick skipped (no fort loaded; "
                  f"focus {focus!r})", flush=True)
            return
        # A modal dialog freezes the tick even when the pause flag is
        # clear (verified live: the outpost liaison meeting left the
        # fort at tick 225920 for 20+ minutes while the planner kept
        # ticking). Handle it PROGRAMMATICALLY (dialogs.advance):
        # dfhack.screen.dismiss marks the screen for removal, no
        # keystrokes. Mikey rejected the keystroke path (2026-11-26)
        # and flagging dialogs as a limitation — the programmatic
        # route is the only dismissal. A modal outside the allowlist
        # (game-committing or unknown) is named and logged as
        # dialog_blocked, never dismissed. Acting through a dialog
        # fails or, worse, drives the wrong menu, so the tick is
        # skipped either way.
        if focus != "dwarfmode/Default":
            from . import dialogs
            try:
                res = dialogs.advance(self.client, max_rounds=3,
                                      wait_s=2.0)
            except Exception as exc:  # noqa: BLE001 - retry next tick
                print(f"dfh planner: dialog advance failed: {exc}",
                      flush=True)
                return
            for audit in res.get("cleared") or []:
                self.journal.log_event(
                    "dialog_dismissed",
                    f"{audit.get('focus')} -> {audit.get('focus_after')} "
                    f"(dismissed={audit.get('dismissed')}, "
                    f"removed={audit.get('removed')})")
                print(f"dfh planner: dismissed {audit.get('focus')} "
                      f"dialog programmatically",
                      flush=True)
            if not res.get("ok"):
                blocked = res.get("blocked_by")
                if blocked != getattr(self, "_last_dialog_focus", None):
                    self._last_dialog_focus = blocked
                    self.journal.log_event(
                        "dialog_blocked",
                        f"game on blocking focus {blocked!r}; "
                        f"{res.get('reason')}; tick skipped")
                    print(f"dfh planner: blocking focus {blocked!r}; "
                          f"{res.get('reason')}", flush=True)
            return
        # The planner decides from a FULL state. The poller's
        # last_state is a lite snapshot (fast sections only: no
        # buildings, no stocks, no items most polls) — deciding from
        # it hallucinates drink 0 / no workshops and re-orders a
        # still on an occupied tile every tick. A full collect costs
        # ~3s per 30s tick; that is the correct price.
        # Read safety (world-model design §8): no world-state read
        # while the game is running. Pause (verified) BEFORE the full
        # collect and stay paused through the whole tick — decide and
        # act happen while paused (the actions re-pause after their
        # own bursts). The game is unpaused only at the end of the
        # tick, below. A refused read (pause unverifiable) skips the
        # tick; the outcome is unknown, never read while running.
        try:
            with self.lock:
                from .read_safety import ReadRefused, paused_read
                try:
                    state = paused_read(
                        self.client,
                        lambda: observe.collect(self.client),
                        restore=False)
                except ReadRefused as exc:
                    print(f"dfh planner: read refused: {exc}",
                          flush=True)
                    return
        except Exception as exc:  # noqa: BLE001 - poll again next tick
            print(f"dfh planner: full collect failed: {exc}",
                  flush=True)
            return
        if not state.get("status"):
            print(f"dfh planner: tick skipped (no status section); "
                  f"errors={state.get('errors')}",
                  flush=True)
            return
        # Milestone 5: the per-tick assembled snapshot (design §6)
        # — built from this tick's full paused collect, diffed
        # against the Store, trends + unit history sampled once per
        # in-game day, deaths recorded from UNIT_DEATH events. The
        # snapshot is the observation record the agent decides from;
        # its token count is logged so the budget is visible.
        self._record_snapshot(state)
        # Threat hold: a critical threat pauses the game and the
        # planner does nothing else until it moves away.
        summary = state_summary(state)
        hostiles = summary["hostiles"]
        if hostiles:
            from .planner import _nearest_hostile_distance
            dist = _nearest_hostile_distance(summary)
            if dist is not None and dist <= 5:
                with self.lock:
                    if not get_paused(self.client):
                        set_paused(self.client, True)
                self.journal.log_event(
                    "threat_hold",
                    f"hostile {dist} tiles from a citizen; game held "
                    f"paused", tick=summary["tick"])
                return
        # The tick stays paused through decide and act (read safety):
        # _manager_present reads noble assignments and planner.tick
        # runs verified actions, and both must see the game paused.
        # The old code unpaused here so the planner "had anything to
        # do", but the actions drive the clock themselves in bursts
        # (actions._wait_for_paused), and unpausing before the noble
        # probe read assignments while the game ticked. The game is
        # unpaused only at the end of the tick, below.
        manager = self._manager_present()
        sites = self._derive_sites(state)
        # Cache the derived sites for the snapshot route: the
        # snapshot (server._snapshot) cannot trigger a scan, but the
        # M1 model needs a concrete free site coordinate when the
        # suggestion tells it to build a still. The snapshot reads
        # this cache (freshness-checked there); the build probe
        # re-verifies the site at build time, so a stale entry is
        # handled by the fix hint, not a bad build.
        self._sites_cache = sites
        self._sites_cache_at = time.monotonic()
        _from = self._placement_cache.get("from") \
            if self._placement_cache else None
        records = self.planner.tick(
            state, list(self._recent_events),
            manager=manager, dig_site=self._derive_dig_site(state),
            sites=sites,
            gather_box=self._derive_gather_box(state),
            placement=self._placement_cache,
            from_pos=tuple(_from) if _from else None)
        print(f"dfh planner: tick {self.planner.ticks} done: "
              f"{len(records)} decision(s), "
              f"{sum(1 for r in records if r.get('ok'))} ok, "
              f"game tick {state_summary(state)['tick']}",
              flush=True)
        self._check_goals(state)
        self._quicksave_if_due()
        # Leave the game running between ticks. Actions re-pause the
        # game after their waits; without this the fort sits paused
        # for the whole planner interval (observed live: two ticks
        # 30s apart with zero ticks advanced). The threat hold above
        # already returned early for a critical threat, so reaching
        # here means it is safe to run.
        # BUT: re-check the loop-pause flag first. A tick that
        # started before the loop was paused must NOT unpause the
        # game at the end — the next tick is skipped while paused,
        # so nothing would re-pause it and the fort would run
        # unattended (observed 2026-11-26: 1530 ticks, drink 39
        # -> 35, during a mock run whose loop was paused).
        if self._loop_paused:
            return
        with self.lock:
            if get_paused(self.client):
                set_paused(self.client, False)

    def _record_snapshot(self, state: dict[str, Any]) -> None:
        """Build the per-tick assembled snapshot (milestone 5) and
        record it in the State Store: diff baselines, daily trend +
        unit-history samples, and deaths from the recent UNIT_DEATH
        events. Areas + survey come from the server's CACHE only —
        a tick never triggers a scan. Failures are logged, never
        fatal to the tick."""
        from .assembler import assemble, sample_daily
        areas = None
        survey_data = None
        cache = getattr(self.server, "spatial_cache", None) \
            if self.server is not None else None
        if cache:
            # The areas cache holds the full derivation dict; the
            # assembler takes the areas LIST (passing the dict made
            # _areas slice a dict: KeyError slice(None, 15, None)).
            areas = (cache.get("areas") or {}).get("areas")
            survey_data = cache.get("survey")
        detector = self.poller.detector if self.poller is not None \
            else None
        try:
            snap = assemble(state, store=self.store,
                            detector=detector, areas=areas,
                            survey=survey_data)
        except Exception as exc:  # noqa: BLE001 - never kill the tick
            self.journal.log_event("snapshot_error",
                                   f"assemble failed: {exc}")
            return
        sampled = sample_daily(state, self.store)
        tick = (state.get("status") or {}).get("year_tick")
        # Diary (GOAL.md step 4): when a new day is sampled, the day
        # that just ended gets its entry. The entry is built only
        # from the Store + Journal for that day's tick range, so
        # every claim traces to a recorded event, decision, or
        # observation. Failures are logged, never fatal to the tick.
        if sampled and isinstance(tick, int) and tick >= TICKS_PER_DAY:
            try:
                from .diary import (TICKS_PER_DAY as _TPD,
                                    build_daily_summary, write_entry)
                prev_start = (tick // _TPD - 1) * _TPD
                fort = (state.get("status") or {}).get("fort_name") or ""
                year = (state.get("status") or {}).get("year") or 0
                summary = build_daily_summary(
                    self.store, self.journal, prev_start, fort, year)
                write_entry(self.state_dir, summary)
            except Exception as exc:  # noqa: BLE001 - never kill tick
                self.journal.log_event(
                    "diary_error", f"diary write failed: {exc}")
        reports = (state.get("reports") or {}).get("announcements") \
            or []
        for ev in self._recent_events:
            if ev.get("kind") != "unit_death":
                continue
            uid = (ev.get("data") or {}).get("unit_id")
            if not isinstance(uid, int) \
                    or uid in self._deaths_recorded:
                continue
            self._deaths_recorded.add(uid)
            dtick = ev.get("tick") if isinstance(ev.get("tick"), int) \
                else (tick or 0)
            history = self.store.unit_history(uid)
            cause, ref = diagnose_death(uid, history, reports)
            self.store.record_death(dtick, uid, cause, ref)
        self.journal.log_event(
            "snapshot",
            f"tick {tick}: {snap['tokens']} tokens, "
            f"cuts={','.join(snap['cuts']) or 'none'}",
            tick=tick if isinstance(tick, int) else None)

    def _derive_dig_site(self, state: dict[str, Any]
                         ) -> Optional[dict[str, Any]]:
        """The planner's dig site, derived from the areas (never
        hardcoded): the Surface area + the fort centre (the median
        citizen position) + the surface z. Returns None when the
        areas are not cached yet — the planner then does not dig
        rather than digging blind. Failures are None, never fatal
        to the tick."""
        from . import digging
        cache = getattr(self.server, "spatial_cache", None) \
            if self.server is not None else None
        areas = cache.get("areas") if cache else None
        if not areas:
            return None
        surface_z = areas.get("surface_z")
        if not isinstance(surface_z, int):
            return None
        # The fort centre is the Surface area's bbox centre (the
        # embark centre, where the wagon lands) — NOT the median
        # citizen position. The citizens scatter (gathering, fishing)
        # and the median drifts to the map edge: verified live, the
        # median was (53, 9) while the fort is at (97, 97), and the
        # workshop sites derived from it landed on WALL tiles at
        # y=0. The bbox centre is stable and correct.
        centre = _fort_centre(areas)
        if centre is None:
            return None
        try:
            return digging.derive_dig_site(areas, centre, surface_z)
        except Exception:  # noqa: BLE001 - no site is "no dig"
            return None

    def _derive_sites(self, state: dict[str, Any]
                      ) -> Optional[dict[str, Any]]:
        """The planner's workshop/bed/farm/stockpile sites, derived
        from the areas (never hardcoded): the Surface area + the
        fort centre (the Surface bbox centre) + the surface z.
        Returns None when the areas are not cached yet — the planner
        then does not build rather than building blind (the stale
        Athelunol z=42 fallback is removed; see planner.py).
        Failures are None, never fatal to the tick.

        Placement system (2026-11-26): the workshop and stockpile
        sites come from placement.find_sites — verified free AND
        reachable (canWalkBetween from the fort centre) — not from
        fixed offsets. The verified sites are also stored on
        self._placement_cache (kind -> [site, ...]) for the snapshot
        (/v1/snapshot placement section), the /v1/sites query route,
        and the build actions' verified-alternative naming. The
        food_stockpile_box is the first verified 5x5 stockpile site
        (not the fixed offset derive_sites would otherwise use).
        """
        from . import placement as placement_mod
        from . import sites as sites_mod
        cache = getattr(self.server, "spatial_cache", None) \
            if self.server is not None else None
        areas = cache.get("areas") if cache else None
        if not areas:
            return None
        # The anchor: where the fort actually is (buildings first,
        # then citizens) — NOT the Surface bbox centre (the map
        # centre) or the lowest citizen z (the hills). The old
        # derivation gave (95,95,176) and 0 sites (2026-11-27).
        try:
            centre, surface_z, from_pos = \
                placement_mod.placement_anchor(state, areas)
        except ValueError:
            return None
        cx, cy = centre
        # Workshop sites (3x3) and stockpile sites (5x5), verified
        # free + reachable from the fort centre. A site with no path
        # is not a free site.
        try:
            ws = placement_mod.find_sites(
                self.client, "workshop", 3, 3, centre, surface_z,
                from_pos, limit=8)
        except Exception:  # noqa: BLE001 - no sites is "no build"
            ws = {"sites": []}
        try:
            sp = placement_mod.find_sites(
                self.client, "stockpile", 5, 5, centre, surface_z,
                from_pos, limit=3)
        except Exception:  # noqa: BLE001 - no sites is "no build"
            sp = {"sites": []}
        workshop_sites = [tuple(s["pos"]) for s in ws.get("sites") or []]
        stockpile_sites = [tuple(s["pos"]) for s in sp.get("sites") or []]
        self._placement_cache = {
            "workshop": ws.get("sites") or [],
            "stockpile": sp.get("sites") or [],
            "zone": sp.get("sites") or [],
            "centre": [cx, cy, surface_z],
            "from": list(from_pos),
        }
        self._placement_cache_at = time.monotonic()
        try:
            out = sites_mod.derive_sites(areas, centre, surface_z,
                                          floor_rects=workshop_sites)
        except Exception:  # noqa: BLE001 - no sites is "no build"
            return None
        # The food stockpile box is the first VERIFIED 5x5 stockpile
        # site, not derive_sites' fixed offset.
        if stockpile_sites:
            sx, sy, sz = stockpile_sites[0]
            out["food_stockpile_box"] = (sx, sy, sz, sx + 4, sy + 4, sz)
        return out

    def get_placement(self, kind: str, width: int, height: int,
                      limit: int = 5, max_age: float = 120.0
                      ) -> dict[str, Any]:
        """Verified sites for a kind + size, on demand.

        Returns the cached placement for the kind when it is fresh
        (derived within max_age seconds) and has sites of the right
        size; otherwise derives fresh via placement.find_sites (a
        paused read — no game time advances). The result is the
        placement.find_sites dict ({kind, width, height, sites,
        blocked, centre, from}). When the areas are not cached yet
        (no fort centre / surface z), returns {"sites": []} with a
        "reason" — never a guessed site, and the caller says so.
        """
        from . import placement as placement_mod
        cache = self._placement_cache
        if cache and (time.monotonic() - self._placement_cache_at
                      <= max_age):
            sites = [s for s in (cache.get(kind) or [])
                     if s.get("width") == width
                     and s.get("height") == height
                     and s.get("reachable") is True]
            if sites:
                return {"kind": kind, "width": width, "height": height,
                        "sites": sites[:limit], "blocked": [],
                        "centre": cache.get("centre"),
                        "from": cache.get("from"), "cached": True}
        # Derive fresh (needs the areas for the centre + surface z,
        # and a fresh state for the anchor — the buildings/citizens,
        # not the map centre).
        spatial = getattr(self.server, "spatial_cache", None) \
            if self.server is not None else None
        areas = spatial.get("areas") if spatial else None
        if not areas:
            return {"kind": kind, "width": width, "height": height,
                    "sites": [], "blocked": [],
                    "reason": "areas not cached yet — no fort centre"}
        # A fresh paused collect for the anchor (buildings +
        # citizens). The poller's last_state is lite (no buildings
        # most polls) and cannot anchor the search.
        try:
            from . import observe
            from .read_safety import paused_read
            state = paused_read(self.client,
                                lambda: observe.collect(self.client))
        except Exception as exc:  # noqa: BLE001 - no state, no sites
            return {"kind": kind, "width": width, "height": height,
                    "sites": [], "blocked": [],
                    "reason": f"state collect failed: {exc}"}
        try:
            centre, surface_z, from_pos = \
                placement_mod.placement_anchor(state, areas)
        except ValueError as exc:
            return {"kind": kind, "width": width, "height": height,
                    "sites": [], "blocked": [], "reason": str(exc)}
        try:
            found = placement_mod.find_sites(
                self.client, kind, width, height, centre, surface_z,
                from_pos, limit=limit)
        except Exception as exc:  # noqa: BLE001 - no sites is empty
            return {"kind": kind, "width": width, "height": height,
                    "sites": [], "blocked": [],
                    "reason": f"placement search failed: {exc}"}
        # Warm the placement cache with the fresh result, so the
        # snapshot's placement section and the build actions'
        # verified-alternative naming can use it without waiting
        # for a planner tick to derive sites.
        if self._placement_cache is None:
            self._placement_cache = {}
        self._placement_cache[kind] = found.get("sites") or []
        self._placement_cache["centre"] = found.get("centre")
        self._placement_cache["from"] = found.get("from")
        self._placement_cache_at = time.monotonic()
        return found

    def _derive_gather_box(self, state: dict[str, Any]
                           ) -> Optional[tuple[int, ...]]:
        """The planner's gather box, derived from a shrub probe on
        the surface (never the hardcoded GATHER_BOX). Returns None
        when there are no shrubs or the probe fails — the planner
        then falls back to GATHER_BOX. A paused read, no game time
        advances."""
        from .actions import _run_helper
        citizens = (state.get("units") or {}).get("citizens") or []
        if not citizens:
            return None
        surface_z = min(c["pos"][2] for c in citizens if c.get("pos"))
        try:
            probe = _run_helper(
                self.client, "probe_plants.lua",
                {"x0": 0, "y0": 0, "z0": surface_z,
                 "x1": 191, "y1": 191, "z1": surface_z,
                 "kind": "shrub"})
        except Exception:  # noqa: BLE001 - no box is "no gather"
            return None
        shrubs = probe.get("plants") or []
        if not shrubs:
            return None
        sx, sy = shrubs[0]["pos"][0], shrubs[0]["pos"][1]
        return (max(0, sx - 5), max(0, sy - 5), surface_z,
                min(191, sx + 5), min(191, sy + 5), surface_z)

    def _manager_present(self) -> Optional[bool]:
        """True when a manager is appointed, False when not, None
        when the probe failed (planner skips noble decisions)."""
        if self.client is None:
            return None
        try:
            from .actions import nobles as probe_nobles
            with self.lock:
                probe = probe_nobles(self.client)
            if not probe.get("ok", False):
                return None
            return bool((probe.get("nobles") or {})
                        .get("MANAGE_PRODUCTION"))
        except Exception:  # noqa: BLE001 - probe failure is "unknown"
            return None

    def _check_goals(self, state: dict[str, Any]) -> None:
        now = time.time()
        if now - self._goal_check_at < 60.0:
            return
        self._goal_check_at = now
        for goal in self.journal.list_goals():
            if goal["done"]:
                continue
            satisfied = evaluate_goal(goal["expression"], state)
            if satisfied:
                self.journal.mark_goal_done(goal["id"])
                if self.bus is not None:
                    self.bus.publish(make_event(
                        "goal_satisfied", "notice",
                        {"goal_id": goal["id"], "name": goal["name"]},
                        source="daemon"))

    def _quicksave_if_due(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_quicksave < \
                self.config.quicksave_interval:
            return
        if self.client is None:
            return
        self._last_quicksave = now
        save_path = (self.df_dir / "data" / "save" / "region1"
                     / "world.sav")
        before = save_path.stat().st_mtime if save_path.exists() else 0.0
        try:
            with self.lock:
                self.client.run_command("quicksave")
        except Exception as exc:  # noqa: BLE001 - save failure is logged
            self.journal.log_event(
                "daemon_error", f"quicksave failed: {exc}")
            return
        # Quicksave blocks RPC ~30-40s; wait for the save to land,
        # then verify the region save actually advanced (phase 4
        # found a quicksave that did not update region1/world.sav).
        time.sleep(45)
        after = save_path.stat().st_mtime if save_path.exists() else 0.0
        if self.bus is not None:
            self.bus.publish(make_event(
                "save", "info", {"region_mtime_advanced": after > before},
                source="daemon"))
        if after <= before:
            self.journal.log_event(
                "daemon_error",
                "quicksave finished but region1/world.sav mtime did "
                "not advance — the save may only exist in "
                "data/save/current/; use the in-game Save Game "
                "instead")

    # -- composed tasks --------------------------------------------------
    def run_task(self, name: str, wait: float = 120.0,
                 count: int = 1) -> dict[str, Any]:
        """Run a composed task (PROTOCOL.md §4.3): queue the work,
        then wait (bounded) for the queued job to leave the job list
        — disappearance means it was worked (or cancelled, which the
        newest report reveals). Returns an action envelope."""
        started = time.monotonic()
        spec = TASK_DEFS.get(name)
        if spec is None:
            return {"ok": False, "action": f"task:{name}",
                    "detail": f"unknown task {name!r}",
                    "evidence": None,
                    "took_ms": 0}
        if self.client is None:
            return {"ok": False, "action": f"task:{name}",
                    "detail": "daemon has no DFHack client",
                    "evidence": None,
                    "took_ms": 0}
        # Read safety (world-model design §8): pause (verified)
        # before the initial collect; a refused read fails the task
        # (outcome unknown), never reads while running.
        with self.lock:
            from .read_safety import ReadRefused, paused_read
            try:
                state = paused_read(
                    self.client,
                    lambda: observe.collect(self.client))
            except ReadRefused as exc:
                return {"ok": False, "action": f"task:{name}",
                        "detail": f"read refused: {exc}",
                        "evidence": None,
                        "took_ms": round((time.monotonic() - started)
                                         * 1000)}
        if name == "gather":
            # The gather box is derived from the live state, never
            # hardcoded: probe the surface for shrubs and build a
            # box around a cluster. The old GATHER_BOX was Athelunol
            # z=42 coordinates — on Erushtathtat (surface z=175)
            # it designated gathering in solid rock, with no
            # plants. The citizens' mean position is no good
            # either (verified live: no shrubs there) — the box
            # must be where the plants are.
            from .actions import _run_helper
            citizens = (state.get("units") or {}).get("citizens") or []
            if citizens:
                surface_z = min(c["pos"][2] for c in citizens
                                if c.get("pos"))
            else:
                surface_z = 175
            probe = _run_helper(
                self.client, "probe_plants.lua",
                {"x0": 0, "y0": 0, "z0": surface_z,
                 "x1": 191, "y1": 191, "z1": surface_z,
                 "kind": "shrub"})
            shrubs = probe.get("plants") or []
            if not shrubs:
                return {"ok": False, "action": f"task:{name}",
                        "detail": "no shrubs on the surface — "
                                  "nothing to gather",
                        "fix": "Fix: plant a farm plot (action "
                               "build_farm_plot) and grow plump "
                               "helmets instead of gathering.",
                        "evidence": None,
                        "took_ms": round((time.monotonic() - started)
                                         * 1000)}
            # A 10x10 box around the first shrub found (the probe
            # returns them in world order, so this is deterministic
            # for a given fort state).
            sx, sy = shrubs[0]["pos"][0], shrubs[0]["pos"][1]
            box = (max(0, sx - 5), max(0, sy - 5), surface_z,
                   min(191, sx + 5), min(191, sy + 5), surface_z)
            result = act(self.client, "designate_gather", box=box)
            # The box is returned so the caller can verify where the
            # gathering was designated (the surface z, never z=42).
            return {**result.to_dict(), "action": f"task:{name}",
                    "box": list(box)}
        need = spec["need"]
        subtype = {"still": "Still", "kitchen": "Kitchen",
                   "carpenter": "Carpenters"}[need]
        workshop = _find_workshop(state, subtype)
        if workshop is None:
            return {"ok": False, "action": f"task:{name}",
                    "detail": f"no {need} workshop exists",
                    "evidence": None,
                    "took_ms": round((time.monotonic() - started) * 1000)}
        # The causal chain, checked before queuing (layer 2): a brew
        # needs an empty barrel AND a brewable plant, not just a
        # still. Without them the job is queued and then cancelled,
        # and the task would have reported a false success. The
        # planner checks the same conditions before deciding to
        # brew; the task re-checks them so it is self-contained.
        if name == "brew":
            from .planner import _brewable_plants
            stocks = state.get("stocks") or {}
            barrels = stocks.get("barrels") or 0
            brewable = _brewable_plants(stocks)
            if barrels == 0:
                return {"ok": False, "action": f"task:{name}",
                        "detail": "no barrels in stock — cannot brew",
                        "fix": "Fix: queue make_barrel at the "
                               "carpenter (action queue_job, job "
                               "make_barrel). Needs 1 wood. "
                               f"Wood: {stocks.get('wood_units')}.",
                        "evidence": None,
                        "took_ms": round((time.monotonic() - started)
                                         * 1000)}
            if brewable == 0:
                return {"ok": False, "action": f"task:{name}",
                        "detail": "no brewable plants in stock — "
                                  "cannot brew",
                        "fix": "Fix: gather plants (action "
                               "designate_gather) or plant a farm "
                               "plot and grow plump helmets.",
                        "evidence": None,
                        "took_ms": round((time.monotonic() - started)
                                         * 1000)}
        job_name = spec["job"]
        result = act(self.client, "queue_job",
                     building_id=workshop["id"], job=job_name, count=count)
        if not result.ok:
            return {**result.to_dict(), "action": f"task:{name}"}
        job_ids = set(result.detail.get("job_ids") or [])
        # Read safety (world-model design §8): the job-completion
        # wait reads the jobs list, so it uses the burst pattern
        # (actions._wait_for_paused) — unpause briefly, pause
        # (verified), read while paused — never a 5s sleep + a read
        # while the game ticks.
        from .actions import _wait_for_paused

        def _jobs_done() -> bool:
            cur = observe.collect(self.client, sections=("jobs",))
            live = {j.get("id") for j in
                    (cur.get("jobs") or {}).get("list") or []}
            return not (job_ids & live)

        finished = _wait_for_paused(self.client, _jobs_done, wait)
        took_ms = round((time.monotonic() - started) * 1000)
        if not finished:
            return {"ok": False, "action": f"task:{name}",
                    "detail": f"queued {job_name} x{count} on "
                              f"building #{workshop['id']} but the job "
                              f"did not finish within {wait}s",
                    "evidence": {"job_ids": sorted(job_ids)},
                    "took_ms": took_ms}
        # The job left the list — but disappearance means it was
        # worked OR cancelled. A cancelled job is a FAILURE, not a
        # success (the old code reported ok=True for a cancelled
        # brew). Check the newest reports for a cancellation after
        # the task started; a cancellation's text names the cause
        # (e.g. "cancels Brew Drink: No empty barrel").
        try:
            cur = observe.collect(self.client, sections=("reports",))
            reports = (cur.get("reports") or {}).get("reports") or []
            start_tick = (state.get("status") or {}).get("year_tick")
            for rep in reports:
                text = str(rep.get("text") or "")
                if "cancel" not in text.lower():
                    continue
                if start_tick is not None and rep.get("time") is not None \
                        and rep["time"] < start_tick:
                    continue
                return {"ok": False, "action": f"task:{name}",
                        "detail": f"the {job_name} job was cancelled: "
                                  f"{text}",
                        "evidence": {"job_ids": sorted(job_ids)},
                        "took_ms": took_ms}
        except Exception:  # noqa: BLE001 - a failed report read must
            # not turn a completed job into a failure; the job did
            # leave the list, so report it as completed.
            pass
        return {"ok": True, "action": f"task:{name}",
                "detail": f"{job_name} x{count} completed on building "
                          f"#{workshop['id']}",
                "evidence": {"job_ids": sorted(job_ids)},
                "took_ms": took_ms}

    # -- status ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {
            "uptime_s": round(time.time() - self.started_at, 1),
            "df_reachable": self.client is not None,
            "loop_paused": self._loop_paused,
            "poll_count": self.poller.poll_count if self.poller else 0,
            "last_poll_ms": self.poller.last_poll_ms if self.poller else None,
            "event_seq": self.bus.latest_seq if self.bus else 0,
            "events_buffered": len(self.bus) if self.bus else 0,
            "planner": self.planner.status() if self.planner else None,
            "journal_decisions": self.journal.decision_counts(),
        }

    def set_loop_paused(self, paused: bool) -> None:
        self._loop_paused = paused
        # Pausing the loop also pauses the game at once: otherwise a
        # pause request leaves the fort running until the next tick
        # (which is skipped while paused, so nothing re-pauses it).
        if paused and self.client is not None:
            try:
                with self.lock:
                    if not get_paused(self.client):
                        set_paused(self.client, True)
            except Exception:
                pass
        self.journal.log_event(
            "daemon_loop_paused" if paused else "daemon_loop_resumed",
            f"loop_paused={paused}")
