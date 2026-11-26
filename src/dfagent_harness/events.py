"""Event system for the DF Agent Harness (phase 3).

The harness watches the game and PINGS the agent when things happen —
push, not poll-only. Two sources feed one ordered stream (PROTOCOL.md
§5):

1. **In-game push (primary):** the eventful watcher
   (``lua/watch.lua``) registers DFHack eventful handlers that append
   one JSON object per line to ``dfh-events.jsonl`` in the DF directory.
   :class:`WatcherDrainer` reads that file by byte offset and converts
   raw watcher records into catalog events.
2. **Poll-diff (fallback + coverage):** :class:`DiffDetector` compares
   consecutive :mod:`dfagent_harness.observe` snapshots and emits
   events on changes. This covers everything eventful misses (dwarf
   distress derived from unit state, stock levels, season changes) and
   keeps working if the watcher fails to load.

Both paths feed :class:`EventBus`, an in-process pub/sub with
deduplication (same underlying change emits once, even if both sources
see it) and replay (a reconnecting SSE client gets events since its
``Last-Event-ID``).

Event envelope (PROTOCOL.md §5.3, plus ``urgency``):

    {"seq": 1042, "id": "evt-1042", "type": "threat",
     "severity": "critical", "urgency": "immediate",
     "tick": 123456, "year": 306, "at": 1764020123,
     "source": "eventful", "dedup_key": "threat:88",
     "data": {"unit_id": 88, "name": "Goblin thief", "pos": [98, 102, 174]}}

``severity`` is ``info`` | ``notice`` | ``warning`` | ``critical``.
``urgency`` is derived from severity (``critical`` → ``immediate``,
``warning`` → ``soon``, ``notice`` → ``routine``, ``info`` → ``low``)
unless a detector overrides it. ``dedup_key`` is the bus-level dedup
identity; it is omitted (``None``) for events that are inherently
unique. ``seq``/``id`` are assigned by the bus, not by producers.

Thresholds — measured live on Athelunol 2026-11-26, not guessed
(see docs/EVENTS.md for the full measurement log):

* ``counters2`` hunger/thirst/sleepiness timers climb 1 tick per game
  tick. Dwarves start an ``Eat`` job when hunger crosses ~40,000
  (observed trigger window 39,630–40,043 across 7 dwarves) and a
  ``Drink2`` job when thirst crosses ~20,000 (window 19,731–20,186);
  the timer resets to ~0–450 on eating/drinking.
* Sleepiness never reset below ~49,700 in run 1; run 2 pinned the
  trigger at ~50,000 (maxima before reset 49,661–50,240 across 7
  dwarves; resets land at ~300–4,700).
* Stress categories come from ``dfhack.units.getStressCategory`` with
  cutoffs 50000/25000/10000/-10000/-25000/-50000/-100000 (category 0 =
  most stressed). Baseline fort: all citizens category 3, levels
  -20..83.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Optional

from dfhack_rpc import DFHackClient

__all__ = [
    # Thresholds (measured — see module docstring / docs/EVENTS.md).
    "HUNGER_EAT_TRIGGER",
    "THIRST_DRINK_TRIGGER",
    "SLEEP_TRIGGER",
    "STARVING_WARN",
    "STARVING_CRITICAL",
    "THIRSTY_WARN",
    "THIRSTY_CRITICAL",
    "EXHAUSTED_WARN",
    "DRINK_LOW_WARN",
    "DRINK_LOW_CRITICAL",
    "FOOD_LOW_WARN",
    "FOOD_LOW_CRITICAL",
    "SEVERITY_URGENCY",
    "EVENT_TYPES",
    "make_event",
    "DiffDetector",
    "EventBus",
    "WatcherDrainer",
    "drain_watch_log",
    "watcher_record_to_event",
    "install_watcher",
    "uninstall_watcher",
    "watcher_status",
    "collect_mandates",
    "EventPoller",
]

#: Hunger timer value at which a dwarf starts an Eat job (measured).
HUNGER_EAT_TRIGGER = 40_000
#: Thirst timer value at which a dwarf starts a Drink2 job (measured).
THIRST_DRINK_TRIGGER = 20_000
#: Sleepiness timer value at which a dwarf goes to sleep (measured:
#: maxima before reset 49,661–50,240 across 7 dwarves).
SLEEP_TRIGGER = 50_000

#: Dwarf-distress thresholds. A dwarf that has not eaten 10k ticks past
#: the eat trigger is in trouble (food unreachable/absent); the critical
#: line is inferred, not observed — no dwarf has starved on this fort.
STARVING_WARN = HUNGER_EAT_TRIGGER + 10_000       # 50,000
STARVING_CRITICAL = HUNGER_EAT_TRIGGER + 30_000   # 70,000
THIRSTY_WARN = THIRST_DRINK_TRIGGER + 10_000      # 30,000
THIRSTY_CRITICAL = THIRST_DRINK_TRIGGER + 30_000  # 50,000
EXHAUSTED_WARN = SLEEP_TRIGGER + 10_000           # 60,000 (provisional)

#: Stock thresholds (units). Adopted from dfkit's daemon policy
#: (PROTOCOL.md §3.1: drink < 20 → brew, food < 15 → cook), for a
#: 7-dwarf fort; not measured against starvation.
DRINK_LOW_WARN = 20
DRINK_LOW_CRITICAL = 5
FOOD_LOW_WARN = 15
FOOD_LOW_CRITICAL = 5

#: Severity -> default urgency.
SEVERITY_URGENCY = {
    "critical": "immediate",
    "warning": "soon",
    "notice": "routine",
    "info": "low",
}

#: Event types this module can emit (PROTOCOL.md §5.4 catalog plus
#: phase-3 additions marked with a ``+`` in docs/EVENTS.md).
EVENT_TYPES = (
    "daemon_started", "daemon_stopped", "daemon_error",
    "state", "mode", "pause", "year", "season_change",
    "citizen_new", "citizen_gone",
    "threat", "invasion", "hostile_spawn",
    "unit_death", "dwarf_distress", "report", "job_cancelled",
    "job_completed", "stock_low", "mandate",
    "task_completed", "task_failed", "goal_satisfied", "save",
)

_LUA_DIR = Path(__file__).resolve().parent / "lua"
_DEFAULT_DF_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "third_party" / "df_47_05"
)
DEFAULT_WATCH_LOG = _DEFAULT_DF_DIR / "dfh-events.jsonl"


def make_event(
    type: str,
    severity: str,
    data: Optional[dict[str, Any]] = None,
    source: str = "poll",
    tick: Optional[int] = None,
    year: Optional[int] = None,
    urgency: Optional[str] = None,
    dedup_key: Optional[str] = None,
    at: Optional[float] = None,
) -> dict[str, Any]:
    """Build one catalog event (without ``seq``/``id`` — the bus adds
    those). ``urgency`` defaults from severity; ``at`` defaults to now.
    """
    if severity not in SEVERITY_URGENCY:
        raise ValueError(f"unknown severity: {severity!r}")
    event: dict[str, Any] = {
        "seq": None,
        "id": None,
        "type": type,
        "severity": severity,
        "urgency": urgency or SEVERITY_URGENCY[severity],
        "tick": tick,
        "year": year,
        "at": int(at if at is not None else time.time()),
        "source": source,
        "data": data or {},
    }
    if dedup_key is not None:
        event["dedup_key"] = dedup_key
    return event


# ----------------------------------------------------------------------
# Poll-diff detector
# ----------------------------------------------------------------------

def _citizens(state: dict[str, Any]) -> dict[int, dict[str, Any]]:
    units = state.get("units") or {}
    out: dict[int, dict[str, Any]] = {}
    for c in units.get("citizens") or []:
        if isinstance(c, dict) and c.get("id") is not None:
            out[c["id"]] = c
    return out


def _hostiles(state: dict[str, Any]) -> dict[int, dict[str, Any]]:
    units = state.get("units") or {}
    out: dict[int, dict[str, Any]] = {}
    for h in units.get("hostiles") or []:
        if isinstance(h, dict) and h.get("id") is not None:
            out[h["id"]] = h
    return out


def _jobs(state: dict[str, Any]) -> dict[int, dict[str, Any]]:
    jobs = state.get("jobs") or {}
    out: dict[int, dict[str, Any]] = {}
    for j in jobs.get("list") or []:
        if isinstance(j, dict) and j.get("id") is not None:
            out[j["id"]] = j
    return out


def _orders(state: dict[str, Any]) -> dict[int, dict[str, Any]]:
    jobs = state.get("jobs") or {}
    out: dict[int, dict[str, Any]] = {}
    for o in jobs.get("manager_orders") or []:
        if isinstance(o, dict) and o.get("id") is not None:
            out[o["id"]] = o
    return out


def _report_key(entry: dict[str, Any]) -> str:
    return "%s|%s|%s" % (entry.get("year"), entry.get("time"),
                         entry.get("text"))


def _distress_for(citizen: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Active distress kinds for one citizen.

    Returns ``{kind: {"severity": ..., "detail": ...}}``. Edge-triggered
    by the detector: a kind fires when it appears or its severity
    rises, and re-arms when it clears.
    """
    out: dict[str, dict[str, Any]] = {}
    counters = citizen.get("counters") or {}
    hunger = counters.get("hunger") or 0
    thirst = counters.get("thirst") or 0
    sleepiness = counters.get("sleepiness") or 0
    if hunger >= STARVING_CRITICAL:
        out["starving"] = {"severity": "critical",
                           "detail": f"hunger timer {hunger} "
                           f"(eat trigger {HUNGER_EAT_TRIGGER})"}
    elif hunger >= STARVING_WARN:
        out["starving"] = {"severity": "warning",
                           "detail": f"hunger timer {hunger} "
                           f"(eat trigger {HUNGER_EAT_TRIGGER})"}
    if thirst >= THIRSTY_CRITICAL:
        out["thirsty"] = {"severity": "critical",
                          "detail": f"thirst timer {thirst} "
                          f"(drink trigger {THIRST_DRINK_TRIGGER})"}
    elif thirst >= THIRSTY_WARN:
        out["thirsty"] = {"severity": "warning",
                          "detail": f"thirst timer {thirst} "
                          f"(drink trigger {THIRST_DRINK_TRIGGER})"}
    if sleepiness >= EXHAUSTED_WARN:
        out["exhausted"] = {"severity": "warning",
                            "detail": f"sleepiness timer {sleepiness} "
                            f"(sleep trigger ~{SLEEP_TRIGGER})"}
    stress = citizen.get("stress") or {}
    category = stress.get("category")
    if category == 0:
        out["tantrum_risk"] = {
            "severity": "warning",
            "detail": f"stress level {stress.get('level')} "
            "(category 0, most stressed)"}
    elif category == 1:
        out["unhappy"] = {
            "severity": "warning",
            "detail": f"stress level {stress.get('level')} "
            "(category 1)"}
    wounds = citizen.get("wound_count") or 0
    if wounds > 0:
        out["wounded"] = {"severity": "warning",
                          "detail": f"{wounds} wound(s)"}
    mood = citizen.get("mood_name")
    if mood not in (None, "none"):
        # A strange mood is not distress by itself, but the daemon
        # wants to know: a mood dwarf without a workshop goes insane.
        # Reported as info-level distress kind "mood" — hmm, keep the
        # catalog kinds only; moods surface via the units snapshot.
        pass
    return out


class DiffDetector:
    """Compares consecutive observe snapshots and emits catalog events.

    Stateful: the first snapshot passed to :meth:`detect` is the
    baseline and emits nothing. Later calls emit one event per change
    (edge-triggered — a persisting condition does not re-fire unless
    its severity rises). All state is per-instance; create a fresh
    detector per fort run.
    """

    def __init__(self) -> None:
        self._prev: Optional[dict[str, Any]] = None
        # unit_id -> {kind: severity} currently active
        self._distress: dict[int, dict[str, str]] = {}
        # (unit_id, kind) -> activation counter, so a re-armed distress
        # gets a fresh dedup key (the bus drops keys it has seen).
        self._distress_activations: dict[tuple[int, str], int] = {}
        # (kind,) -> activation counter for stock_low, same reason.
        self._stock_activations: dict[str, int] = {}
        # unit_id -> wound_count last seen (for wounded re-fire on change)
        self._wounds: dict[int, int] = {}
        # Report keys already emitted (announcements + combat reports).
        self._seen_reports: set[str] = set()
        # Stock level state: "ok" | "warning" | "critical" per kind.
        self._stock_state: dict[str, str] = {"drink": "ok", "food": "ok"}
        # Mandate keys already emitted.
        self._seen_mandates: set[str] = set()

    def _tick_year(self, state: dict[str, Any]) -> tuple[Optional[int],
                                                         Optional[int]]:
        status = state.get("status") or {}
        return status.get("year_tick"), status.get("year")

    def detect(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        """Diff ``state`` against the previous snapshot; return new
        events (without ``seq`` — the bus assigns it)."""
        tick, year = self._tick_year(state)
        if self._prev is None:
            self._prev = state
            self._baseline_reports(state)
            self._baseline_distress(state)
            self._baseline_stocks(state)
            self._baseline_mandates(state)
            return []
        prev = self._prev
        self._prev = state
        events: list[dict[str, Any]] = []
        events.extend(self._diff_status(prev, state, tick, year))
        events.extend(self._diff_citizens(prev, state, tick, year))
        events.extend(self._diff_hostiles(prev, state, tick, year))
        events.extend(self._diff_jobs(prev, state, tick, year))
        events.extend(self._diff_reports(prev, state, tick, year))
        events.extend(self._diff_stocks(state, tick, year))
        events.extend(self._diff_mandates(state, tick, year))
        return events

    # -- baselines ------------------------------------------------------
    def _baseline_reports(self, state: dict[str, Any]) -> None:
        reports = state.get("reports") or {}
        for key in ("announcements", "reports"):
            for e in reports.get(key) or []:
                if isinstance(e, dict):
                    self._seen_reports.add(_report_key(e))

    def _baseline_distress(self, state: dict[str, Any]) -> None:
        for uid, c in _citizens(state).items():
            kinds = _distress_for(c)
            if kinds:
                self._distress[uid] = {k: v["severity"]
                                       for k, v in kinds.items()}
            self._wounds[uid] = c.get("wound_count") or 0

    def _baseline_stocks(self, state: dict[str, Any]) -> None:
        stocks = state.get("stocks")
        if stocks is not None:
            self._stock_state = self._stock_levels(stocks)

    def _baseline_mandates(self, state: dict[str, Any]) -> None:
        for m in state.get("mandates") or []:
            if isinstance(m, dict):
                self._seen_mandates.add(self._mandate_key(m))

    # -- status ---------------------------------------------------------
    def _diff_status(self, prev, state, tick, year):
        events: list[dict[str, Any]] = []
        ps, cs = prev.get("status") or {}, state.get("status") or {}
        if not cs:
            return events
        if ps.get("paused") != cs.get("paused") and ps:
            events.append(make_event(
                "pause", "notice", {"paused": cs.get("paused")},
                tick=tick, year=year))
        if ps.get("focus") != cs.get("focus") and ps:
            events.append(make_event(
                "mode", "info",
                {"viewscreen": cs.get("focus"),
                 "game_mode": cs.get("gametype")},
                tick=tick, year=year))
        if ps and ps.get("year") != cs.get("year"):
            events.append(make_event(
                "year", "info", {"year": cs.get("year")},
                tick=tick, year=year,
                dedup_key=f"year:{cs.get('year')}"))
        if ps and ps.get("season_index") != cs.get("season_index"):
            events.append(make_event(
                "season_change", "info",
                {"season": cs.get("season"),
                 "season_index": cs.get("season_index")},
                tick=tick, year=year,
                dedup_key=f"season:{cs.get('year')}:{cs.get('season_index')}"))
        return events

    # -- citizens / distress --------------------------------------------
    def _diff_citizens(self, prev, state, tick, year):
        events: list[dict[str, Any]] = []
        pc, cc = _citizens(prev), _citizens(state)
        if not cc and not pc:
            return events
        for uid, c in cc.items():
            if uid not in pc:
                events.append(make_event(
                    "citizen_new", "info",
                    {"unit_id": uid, "name": c.get("name"),
                     "pos": c.get("pos"),
                     "profession": c.get("profession")},
                    tick=tick, year=year,
                    dedup_key=f"citizen_new:{uid}"))
        for uid, c in pc.items():
            if uid not in cc:
                events.append(make_event(
                    "citizen_gone", "notice",
                    {"unit_id": uid, "name": c.get("name"),
                     "pos": c.get("pos")},
                    tick=tick, year=year,
                    dedup_key=f"citizen_gone:{uid}"))
        # Distress: edge-triggered per kind, re-fire on severity rise
        # or wound-count change.
        for uid, c in cc.items():
            kinds = _distress_for(c)
            active = self._distress.setdefault(uid, {})
            for kind, info in kinds.items():
                prev_sev = active.get(kind)
                wounds_now = c.get("wound_count") or 0
                wounds_changed = (
                    kind == "wounded"
                    and self._wounds.get(uid) != wounds_now)
                if prev_sev is None or prev_sev != info["severity"] \
                        or wounds_changed:
                    act_n = self._distress_activations.get((uid, kind), 0)
                    if prev_sev is None or wounds_changed:
                        act_n += 1
                        self._distress_activations[(uid, kind)] = act_n
                    events.append(make_event(
                        "dwarf_distress", info["severity"],
                        {"unit_id": uid, "name": c.get("name"),
                         "kind": kind, "detail": info["detail"]},
                        tick=tick, year=year,
                        dedup_key=f"distress:{uid}:{kind}:"
                        f"{info['severity']}:{act_n}"))
                active[kind] = info["severity"]
            for kind in [k for k in active if k not in kinds]:
                del active[kind]
            self._wounds[uid] = c.get("wound_count") or 0
        for uid in [u for u in self._distress if u not in cc]:
            del self._distress[uid]
        return events

    # -- hostiles ---------------------------------------------------------
    def _diff_hostiles(self, prev, state, tick, year):
        events: list[dict[str, Any]] = []
        ph, ch = _hostiles(prev), _hostiles(state)
        for uid, h in ch.items():
            if uid not in ph:
                events.append(make_event(
                    "threat", "critical",
                    {"unit_id": uid, "name": h.get("name"),
                     "race": h.get("race"), "pos": h.get("pos")},
                    tick=tick, year=year,
                    dedup_key=f"threat:{uid}"))
        return events

    # -- jobs / orders ----------------------------------------------------
    def _diff_jobs(self, prev, state, tick, year):
        events: list[dict[str, Any]] = []
        pj, cj = _jobs(prev), _jobs(state)
        cancels = self._cancels_in(state)
        gone = [j for uid, j in pj.items() if uid not in cj]
        for j in gone:
            # A job that vanished in the same batch as a "cancels"
            # report was probably cancelled, not completed — the
            # cancellation event (from reports) is the signal; do not
            # also claim a completion.
            if cancels:
                continue
            events.append(make_event(
                "job_completed", "info",
                {"job_id": j.get("id"), "job_type": j.get("type"),
                 "pos": j.get("pos")},
                tick=tick, year=year,
                dedup_key=f"job_completed:{j.get('id')}"))
        po, co = _orders(prev), _orders(state)
        for oid, o in po.items():
            if oid not in co:
                events.append(make_event(
                    "job_completed", "info",
                    {"manager_order_id": oid,
                     "job_type": o.get("job_type_name") or o.get("job_type"),
                     "amount_total": o.get("amount_total")},
                    tick=tick, year=year,
                    dedup_key=f"job_completed:order:{oid}"))
        return events

    def _cancels_in(self, state: dict[str, Any]) -> bool:
        reports = state.get("reports") or {}
        for key in ("announcements", "reports"):
            for e in reports.get(key) or []:
                if isinstance(e, dict) and "cancels" in \
                        str(e.get("text") or "").lower():
                    return True
        return False

    # -- reports ----------------------------------------------------------
    def _diff_reports(self, prev, state, tick, year):
        events: list[dict[str, Any]] = []
        reports = state.get("reports") or {}
        for key in ("announcements", "reports"):
            for e in reports.get(key) or []:
                if not isinstance(e, dict):
                    continue
                rk = _report_key(e)
                if rk in self._seen_reports:
                    continue
                self._seen_reports.add(rk)
                text = str(e.get("text") or "")
                if "cancels" in text.lower():
                    events.append(make_event(
                        "job_cancelled", "warning",
                        {"text": text, "pos": e.get("pos"),
                         "announcement": key == "announcements"},
                        tick=tick, year=year,
                        dedup_key=f"report:{rk}"))
                else:
                    events.append(make_event(
                        "report", "notice",
                        {"text": text, "pos": e.get("pos"),
                         "announcement": key == "announcements"},
                        tick=tick, year=year,
                        dedup_key=f"report:{rk}"))
        return events

    # -- stocks -----------------------------------------------------------
    @staticmethod
    def _stock_levels(stocks: dict[str, Any]) -> dict[str, str]:
        drink = stocks.get("drink_units") or 0
        food = stocks.get("food_units") or 0
        return {
            "drink": ("critical" if drink <= DRINK_LOW_CRITICAL
                      else "warning" if drink <= DRINK_LOW_WARN else "ok"),
            "food": ("critical" if food <= FOOD_LOW_CRITICAL
                     else "warning" if food <= FOOD_LOW_WARN else "ok"),
        }

    def _diff_stocks(self, state, tick, year):
        events: list[dict[str, Any]] = []
        stocks = state.get("stocks")
        if stocks is None:
            return events
        levels = self._stock_levels(stocks)
        for kind, level in levels.items():
            prev_level = self._stock_state.get(kind, "ok")
            if level != "ok" and level != prev_level:
                units = stocks.get("drink_units" if kind == "drink"
                                   else "food_units")
                act_n = self._stock_activations.get(kind, 0) + 1
                self._stock_activations[kind] = act_n
                events.append(make_event(
                    "stock_low",
                    "critical" if level == "critical" else "warning",
                    {"kind": kind, "units": units,
                     "threshold": (DRINK_LOW_WARN if kind == "drink"
                                   else FOOD_LOW_WARN)},
                    tick=tick, year=year,
                    dedup_key=f"stock_low:{kind}:{level}:{act_n}"))
            self._stock_state[kind] = level
        return events

    # -- mandates ---------------------------------------------------------
    @staticmethod
    def _mandate_key(mandate: dict[str, Any]) -> str:
        mid = mandate.get("id")
        if mid is not None:
            return f"mandate:{mid}"
        return "mandate:%s" % json.dumps(mandate, sort_keys=True,
                                         default=str)

    def _diff_mandates(self, state, tick, year):
        events: list[dict[str, Any]] = []
        for m in state.get("mandates") or []:
            if not isinstance(m, dict):
                continue
            key = self._mandate_key(m)
            if key in self._seen_mandates:
                continue
            self._seen_mandates.add(key)
            events.append(make_event(
                "mandate", "warning",
                {"mandate": {k: v for k, v in m.items()
                             if k != "id"},
                 "mandate_id": m.get("id")},
                tick=tick, year=year,
                dedup_key=key))
        return events


# ----------------------------------------------------------------------
# Event bus
# ----------------------------------------------------------------------

class EventBus:
    """In-process pub/sub with ordering, dedup, replay, and an
    optional JSONL journal (one event per line) so replay survives a
    daemon restart.

    Subscribers receive events in ``seq`` order. :meth:`publish`
    assigns the monotonic ``seq``/``id``. Events carrying a
    ``dedup_key`` already seen among the events still in the ring are
    dropped (the safety net for the same underlying change arriving
    from both eventful and poll-diff); keys leave the seen set when
    their event leaves the ring, so a genuinely new occurrence with
    the same key can fire again after the ring turns over. Detectors
    that re-fire a condition (distress, stock levels) also mint a
    fresh key per activation, so they are never blocked by an earlier
    firing still in the ring.
    """

    def __init__(self, maxlen: int = 1000,
                 journal_path: Optional[Path | str] = None) -> None:
        self.maxlen = maxlen
        self.journal_path = Path(journal_path) if journal_path else None
        self._lock = threading.Lock()
        self._ring: deque[dict[str, Any]] = deque()
        self._key_counts: dict[str, int] = {}
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        self._seq = 0
        if self.journal_path is not None:
            self._load_journal()

    def _load_journal(self) -> None:
        assert self.journal_path is not None
        if not self.journal_path.exists():
            return
        try:
            lines = self.journal_path.read_text().splitlines()
        except OSError:
            return
        for line in lines[-self.maxlen:]:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or "seq" not in event:
                continue
            self._ring.append(event)
            self._seq = max(self._seq, int(event["seq"]))
            if event.get("dedup_key"):
                key = event["dedup_key"]
                self._key_counts[key] = self._key_counts.get(key, 0) + 1

    def publish(self, event: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Assign ``seq``/``id`` and deliver. Returns the stamped event,
        or ``None`` when it was a duplicate (``dedup_key`` already
        seen). Never raises for a subscriber failure."""
        key = event.get("dedup_key")
        with self._lock:
            if key is not None and key in self._key_counts:
                return None
            self._seq += 1
            stamped = dict(event)
            stamped["seq"] = self._seq
            stamped["id"] = f"evt-{self._seq}"
            if key is not None:
                self._key_counts[key] = self._key_counts.get(key, 0) + 1
            self._ring.append(stamped)
            while len(self._ring) > self.maxlen:
                evicted = self._ring.popleft()
                ekey = evicted.get("dedup_key")
                if ekey is not None:
                    remaining = self._key_counts.get(ekey, 1) - 1
                    if remaining <= 0:
                        self._key_counts.pop(ekey, None)
                    else:
                        self._key_counts[ekey] = remaining
            subscribers = list(self._subscribers)
        if self.journal_path is not None:
            try:
                with open(self.journal_path, "a") as fh:
                    fh.write(json.dumps(stamped) + "\n")
            except OSError:
                pass
        for fn in subscribers:
            try:
                fn(stamped)
            except Exception:  # noqa: BLE001 - one bad subscriber
                # must not break delivery to the rest.
                import traceback
                traceback.print_exc()
        return stamped

    def subscribe(self, fn: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            if fn not in self._subscribers:
                self._subscribers.append(fn)

    def unsubscribe(self, fn: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            if fn in self._subscribers:
                self._subscribers.remove(fn)

    def replay(self, since_seq: Optional[int] = None,
               limit: Optional[int] = None) -> list[dict[str, Any]]:
        """Events with ``seq`` greater than ``since_seq`` (all of them
        when ``since_seq`` is ``None``), oldest first. ``limit`` caps
        the count (most recent ``limit`` when ``since_seq`` is None,
        first ``limit`` after ``since_seq`` otherwise)."""
        with self._lock:
            events = list(self._ring)
        if since_seq is not None:
            events = [e for e in events if e["seq"] > since_seq]
        elif limit is not None:
            events = events[-limit:]
        if limit is not None and since_seq is not None:
            events = events[:limit]
        return events

    @property
    def latest_seq(self) -> int:
        with self._lock:
            return self._seq

    def __len__(self) -> int:
        with self._lock:
            return len(self._ring)


# ----------------------------------------------------------------------
# Eventful watcher: drain + install
# ----------------------------------------------------------------------

def watcher_record_to_event(
        record: dict[str, Any],
        resolve_unit: Optional[Callable[[int], Optional[dict[str, Any]]]]
        = None) -> Optional[dict[str, Any]]:
    """Convert one raw watcher JSONL record into a catalog event (no
    ``seq``), or ``None`` when the record is not an event the daemon
    surfaces (non-hostile UNIT_NEW_ACTIVE is covered by poll-diff's
    ``citizen_new``).

    ``resolve_unit`` maps a unit id to ``{name, citizen, race, pos}``
    from the daemon's last snapshot — used for UNIT_DEATH, whose unit
    is already gone from the game. Without it, deaths carry the id
    only.
    """
    kind = record.get("kind")
    tick = record.get("tick")
    year = record.get("year")
    if kind == "JOB_COMPLETED":
        job_id = record.get("job_id")
        return make_event(
            "job_completed", "info",
            {"job_id": job_id, "job_type": record.get("job_type"),
             "worker_id": record.get("worker_id"),
             "pos": record.get("pos")},
            source="eventful", tick=tick, year=year,
            dedup_key=(f"job_completed:{job_id}"
                       if job_id is not None else None))
    if kind == "UNIT_DEATH":
        uid = record.get("unit_id")
        data: dict[str, Any] = {"unit_id": uid}
        if resolve_unit is not None and isinstance(uid, int):
            resolved = resolve_unit(uid)
            if resolved:
                data.update({"name": resolved.get("name"),
                             "citizen": resolved.get("citizen", True),
                             "race": resolved.get("race"),
                             "pos": resolved.get("pos")})
        return make_event(
            "unit_death", "warning", data,
            source="eventful", tick=tick, year=year,
            dedup_key=(f"unit_death:{uid}" if uid is not None else None))
    if kind == "REPORT":
        text = record.get("text")
        return make_event(
            "report", "notice",
            {"text": text, "year": record.get("year"),
             "time": record.get("time"),
             "announcement": record.get("announcement"),
             "report_index": record.get("index")},
            source="eventful", tick=tick, year=year,
            dedup_key=(f"report:{record.get('year')}|"
                       f"{record.get('time')}|{text}"
                       if text else f"report-idx:{record.get('index')}"))
    if kind == "INVASION":
        return make_event(
            "invasion", "critical",
            {"args": record.get("args") or []},
            source="eventful", tick=tick, year=year)
    if kind == "UNIT_NEW_ACTIVE":
        if not record.get("hostile"):
            return None
        uid = record.get("unit_id")
        return make_event(
            "hostile_spawn", "critical",
            {"unit_id": uid, "name": record.get("name"),
             "race": record.get("race"), "pos": record.get("pos")},
            source="eventful", tick=tick, year=year,
            dedup_key=(f"hostile_spawn:{uid}"
                       if uid is not None else None))
    return None


def drain_watch_log(path: Path | str,
                    offset: int = 0,
                    resolve_unit: Optional[
                        Callable[[int], Optional[dict[str, Any]]]]
                    = None) -> tuple[list[dict[str, Any]], int]:
    """Read watcher JSONL records from ``offset``; return ``(events,
    new_offset)``. A trailing partial line (watcher mid-write) is left
    for the next drain — ``new_offset`` stops before it. Malformed
    lines are skipped, never fatal."""
    path = Path(path)
    if not path.exists():
        return [], offset
    data = path.read_bytes()
    if len(data) < offset:
        offset = 0  # log rotated/truncated; re-read from the start
    chunk = data[offset:]
    if not chunk:
        return [], offset
    events: list[dict[str, Any]] = []
    new_offset = offset
    # The last element is partial unless the chunk ends with a newline;
    # parts[:-1] are the complete lines in both cases.
    parts = chunk.split(b"\n")
    consumed = 0
    for raw in parts[:-1]:
        consumed += len(raw) + 1
        if not raw.strip():
            continue
        try:
            record = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(record, dict):
            continue
        event = watcher_record_to_event(record, resolve_unit)
        if event is not None:
            events.append(event)
    new_offset = offset + consumed
    return events, new_offset


class WatcherDrainer:
    """Stateful drainer over the watcher JSONL file: remembers the byte
    offset so no record is delivered twice.

    With ``offset_path`` given, the offset is persisted to that file
    after every drain and restored on construction — a daemon restart
    resumes where it left off instead of replaying the whole log
    (phase-3 known limitation, fixed in phase 4). The file holds one
    JSON object: ``{"offset": <int>}``. A missing/corrupt file starts
    at 0.
    """

    def __init__(self, path: Path | str = DEFAULT_WATCH_LOG,
                 offset_path: Optional[Path | str] = None) -> None:
        self.path = Path(path)
        self.offset_path = (Path(offset_path) if offset_path else None)
        self.offset = 0
        if self.offset_path is not None:
            try:
                saved = json.loads(self.offset_path.read_text())
                self.offset = int(saved.get("offset", 0))
            except (OSError, ValueError, TypeError):
                self.offset = 0

    def _save_offset(self) -> None:
        if self.offset_path is None:
            return
        try:
            self.offset_path.parent.mkdir(parents=True, exist_ok=True)
            self.offset_path.write_text(
                json.dumps({"offset": self.offset}))
        except OSError:
            pass

    def drain(self, resolve_unit: Optional[
            Callable[[int], Optional[dict[str, Any]]]] = None
            ) -> list[dict[str, Any]]:
        events, self.offset = drain_watch_log(
            self.path, self.offset, resolve_unit)
        self._save_offset()
        return events


def _load_watch_lua(log_path: Path) -> str:
    prelude = (_LUA_DIR / "json.lua").read_text()
    watcher = (_LUA_DIR / "watch.lua").read_text()
    # The path goes into a Lua double-quoted literal; JSON escaping is
    # valid Lua escaping for the characters that can appear in a path
    # (ASCII printable, no control characters).
    path_str = str(log_path)
    assert all(32 <= ord(c) < 127 for c in path_str), \
        "watch log path must be printable ASCII"
    lua_path = json.dumps(path_str)
    watcher = watcher.replace("'__DFH_EVENT_LOG__'", lua_path)
    return prelude + "\n" + watcher


def install_watcher(client: DFHackClient,
                    log_path: Path | str = DEFAULT_WATCH_LOG) -> str:
    """Install (or re-install) the eventful watcher in the live game.
    Idempotent. Returns the watcher's ``DFH-WATCH-OK ...`` line."""
    code = _load_watch_lua(Path(log_path))
    out = client.run_lua(code)
    for line in out.splitlines():
        if "DFH-WATCH-OK" in line:
            return line.strip()
    raise RuntimeError(f"watcher install did not confirm: {out!r:.300}")


def uninstall_watcher(client: DFHackClient) -> str:
    """Remove the watcher's eventful handlers (stops the JSONL flow).
    The daemon's drain offset is unaffected."""
    code = (
        "local ev = require('plugins.eventful')\n"
        "for _, t in ipairs({'onJobCompleted','onUnitDeath','onReport',"
        "'onInvasion','onUnitNewActive'}) do\n"
        "  if ev[t] then ev[t]['dfh-watch'] = nil end\n"
        "end\n"
        "dfhack.onStateChange.dfh_watch = nil\n"
        "print('DFH-WATCH-REMOVED')\n"
    )
    out = client.run_lua(code)
    for line in out.splitlines():
        if "DFH-WATCH-REMOVED" in line:
            return line.strip()
    raise RuntimeError(f"watcher removal did not confirm: {out!r:.300}")


def watcher_status(client: DFHackClient) -> dict[str, Any]:
    """Report whether the watcher handlers are currently registered."""
    prelude = (_LUA_DIR / "json.lua").read_text()
    code = prelude + "\n" + (
        "local ev = require('plugins.eventful')\n"
        "local function has(t) "
        "return ev[t] ~= nil and ev[t]['dfh-watch'] ~= nil end\n"
        "result = {ok = true, installed = has('onJobCompleted') "
        "and has('onUnitDeath') and has('onReport') "
        "and has('onInvasion') and has('onUnitNewActive'), "
        "on_state_change = dfhack.onStateChange.dfh_watch ~= nil}\n"
        "dfh_print(result)\n"
    )
    return client.run_lua_json(code)


def collect_mandates(client: DFHackClient) -> list[dict[str, Any]]:
    """Read the fort's mandates (``df.global.world.mandates``) via a
    small Lua probe. Returns a list of generic scalar dumps (the struct
    has no live instance to probe field names against — the fort has
    no mandates yet). Used by the poller to feed ``state['mandates']``
    to the detector."""
    prelude = (_LUA_DIR / "json.lua").read_text()
    helper = (_LUA_DIR / "mandates.lua").read_text()
    out = client.run_lua_json(prelude + "\n" + helper)
    if not isinstance(out, dict) or not out.get("ok", False):
        raise RuntimeError(
            f"mandates probe failed: {out.get('error', out)!r:.200}")
    return out.get("mandates", [])


# ----------------------------------------------------------------------
# Poller: owns the RPC client, feeds the bus
# ----------------------------------------------------------------------

class EventPoller:
    """Background poll loop: cheap sections every fast tick, slow
    sections (stocks, mandates) on a longer cadence, watcher drain
    every tick. All events go to the bus.

    Cost (measured live, Athelunol, 7 citizens, paused — see
    docs/EVENTS.md): the fast set with lite units costs ~0.12 s
    (status ~0.05 s, units_lite ~0.08 s, jobs/reports ~0.01 s each);
    with full units it would be ~0.7 s (full units alone ~0.65 s).
    Stocks costs ~0.9 s, hence the slow cadence. Defaults (6 s fast
    while running, 10 s while paused, 60 s slow) — raised from
    2 s / 30 s on 2026-11-26 after measuring ~98% RPC server
    saturation at the old rates (lite ~1.6 s every 2 s + planner
    ~3 s/30 s + slow ~5 s/30 s -> queueing -> 30 s timeouts).
    """

    FAST_SECTIONS = ("status", "units", "jobs", "reports")
    SLOW_EVERY = 15  # fast ticks between slow collections

    def __init__(self, client: DFHackClient, bus: EventBus,
                 drainer: Optional[WatcherDrainer] = None,
                 fast_interval: float = 6.0,
                 paused_interval: float = 10.0,
                 slow_interval: float = 60.0,
                 lock: Optional[threading.RLock] = None) -> None:
        self.client = client
        self.bus = bus
        self.drainer = drainer
        self.fast_interval = fast_interval
        self.paused_interval = paused_interval
        self.slow_interval = slow_interval
        self.lock = lock or threading.RLock()
        self.detector = DiffDetector()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_state: Optional[dict[str, Any]] = None
        self._last_state_lock = threading.Lock()
        self._fast_ticks = 0
        self._last_slow_at = 0.0
        self._last_error_at = 0.0
        self.poll_count = 0
        self.last_poll_ms: Optional[float] = None

    @property
    def last_state(self) -> Optional[dict[str, Any]]:
        with self._last_state_lock:
            return self._last_state

    def poll_once(self) -> list[dict[str, Any]]:
        """One poll cycle: drain the watcher log, collect the fast
        sections (plus slow ones when due), diff, publish. Returns the
        events published this cycle. Raises nothing — an RPC failure
        emits ``daemon_error`` (rate-limited to one per minute) and
        returns whatever the watcher drain produced. The whole cycle
        holds the poller's lock, so the daemon's single RPC connection
        is never shared with a concurrent HTTP handler call.
        """
        from . import observe  # deferred: avoid a cycle at import time

        with self.lock:
            return self._poll_once_locked(observe)

    def _poll_once_locked(self, observe) -> list[dict[str, Any]]:
        published: list[dict[str, Any]] = []
        # Deaths resolve against the PREVIOUS snapshot (the unit was
        # alive then; it is gone from the game now).
        prev_state = self.last_state
        resolver = None
        if prev_state is not None:
            lookup: dict[int, dict[str, Any]] = {}
            for uid, c in _citizens(prev_state).items():
                lookup[uid] = {"name": c.get("name"), "citizen": True,
                               "race": c.get("race"), "pos": c.get("pos")}
            for uid, h in _hostiles(prev_state).items():
                lookup.setdefault(uid, {"name": h.get("name"),
                                        "citizen": False,
                                        "race": h.get("race"),
                                        "pos": h.get("pos")})

            def resolver(uid: int) -> Optional[dict[str, Any]]:
                return lookup.get(uid)

        if self.drainer is not None:
            try:
                for event in self.drainer.drain(resolve_unit=resolver):
                    stamped = self.bus.publish(event)
                    if stamped is not None:
                        published.append(stamped)
            except OSError:
                pass
        started = time.time()
        try:
            # Focus first: while the game is loading (title / load /
            # movie) the world is absent or mid-rebuild and a full
            # Lua collect can crash it (double-free abort, 2026-11-26
            # x2). getCurFocus reads GUI state only, so the probe is
            # the one call that is safe to make here. The watcher
            # drain above is file-only and already ran.
            from .ui import fort_loaded, get_focus
            try:
                probe = get_focus(self.client, timeout=10.0)
                focus = probe.get("focus") if probe.get("ok") else None
            except Exception:  # noqa: BLE001 - probe failure skips
                focus = None
            if not fort_loaded(focus):
                return published
            sections = list(self.FAST_SECTIONS)
            now = time.time()
            slow_due = (now - self._last_slow_at) >= self.slow_interval
            if slow_due:
                sections.append("stocks")
            state = observe.collect(self.client, sections=tuple(sections),
                                    lite_units=True)
            if slow_due:
                self._last_slow_at = now
                try:
                    state["mandates"] = collect_mandates(self.client)
                except Exception:
                    pass
            self.last_poll_ms = round((time.time() - started) * 1000)
            self.poll_count += 1
            with self._last_state_lock:
                self._last_state = state
            for event in self.detector.detect(state):
                stamped = self.bus.publish(event)
                if stamped is not None:
                    published.append(stamped)
        except Exception as exc:  # noqa: BLE001 - poll must not die
            now = time.time()
            if now - self._last_error_at >= 60.0:
                self._last_error_at = now
                stamped = self.bus.publish(make_event(
                    "daemon_error", "critical",
                    {"error": str(exc), "context": "poll_once"},
                    source="daemon"))
                if stamped is not None:
                    published.append(stamped)
        return published

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="dfh-event-poller")
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            paused = True
            state = self.last_state
            if state is not None:
                paused = bool((state.get("status") or {}).get("paused"))
            self.poll_once()
            interval = (self.paused_interval if paused
                        else self.fast_interval)
            self._stop.wait(interval)
