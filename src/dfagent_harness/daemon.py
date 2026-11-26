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
    fast_interval: float = 2.0
    paused_interval: float = 10.0
    slow_interval: float = 30.0
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
        self.server = None
        self._stop = threading.Event()
        self._planner_thread: Optional[threading.Thread] = None
        self._loop_paused = False  # autonomous loop paused (game runs)
        self.started_at = time.time()
        self._last_quicksave = 0.0
        self._recent_events: list[dict[str, Any]] = []
        self._goal_check_at = 0.0

    # -- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Connect, install the watcher, start poller + planner + HTTP.
        Blocks only for the HTTP server (call :meth:`serve_forever`)."""
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

    # -- event memory ----------------------------------------------------
    def _remember_event(self, event: dict[str, Any]) -> None:
        self._recent_events.append(event)
        if len(self._recent_events) > 200:
            self._recent_events = self._recent_events[-200:]

    # -- planner loop ----------------------------------------------------
    def _planner_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._planner_tick()
            except Exception as exc:  # noqa: BLE001 - loop must not die
                self.journal.log_event("daemon_error",
                                       f"planner tick failed: {exc}")
            self._stop.wait(self.config.planner_interval)

    def _planner_tick(self) -> None:
        if self._loop_paused or self.poller is None \
                or self.planner is None or self.client is None:
            return
        state = self.poller.last_state
        if state is None:
            with self.lock:
                state = observe.collect(self.client)
        if not state.get("status"):
            return
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
        # Otherwise the game should be running for the planner to
        # have anything to do.
        with self.lock:
            if get_paused(self.client):
                set_paused(self.client, False)
        manager = self._manager_present()
        self.planner.tick(state, list(self._recent_events),
                          manager=manager)
        self._check_goals(state)
        self._quicksave_if_due()

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
        with self.lock:
            state = observe.collect(self.client)
        if name == "gather":
            from .planner import GATHER_BOX
            result = act(self.client, "designate_gather",
                         box=tuple(GATHER_BOX))
            return {**result.to_dict(), "action": f"task:{name}"}
        need = spec["need"]
        subtype = {"still": "Still", "kitchen": "Kitchen",
                   "carpenter": "Carpenters"}[need]
        workshop = _find_workshop(state, subtype)
        if workshop is None:
            return {"ok": False, "action": f"task:{name}",
                    "detail": f"no {need} workshop exists",
                    "evidence": None,
                    "took_ms": round((time.monotonic() - started) * 1000)}
        job_name = spec["job"]
        result = act(self.client, "queue_job",
                     building_id=workshop["id"], job=job_name, count=count)
        if not result.ok:
            return {**result.to_dict(), "action": f"task:{name}"}
        job_ids = set(result.detail.get("job_ids") or [])
        deadline = time.monotonic() + wait
        done: Optional[dict[str, Any]] = None
        while time.monotonic() < deadline:
            time.sleep(5)
            with self.lock:
                cur = observe.collect(self.client, sections=("jobs",))
            live = {j.get("id") for j in
                    (cur.get("jobs") or {}).get("list") or []}
            if not (job_ids & live):
                done = {"completed": True}
                break
        took_ms = round((time.monotonic() - started) * 1000)
        if done is None:
            return {"ok": False, "action": f"task:{name}",
                    "detail": f"queued {job_name} x{count} on "
                              f"building #{workshop['id']} but the job "
                              f"did not finish within {wait}s",
                    "evidence": {"job_ids": sorted(job_ids)},
                    "took_ms": took_ms}
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
        self.journal.log_event(
            "daemon_loop_paused" if paused else "daemon_loop_resumed",
            f"loop_paused={paused}")
