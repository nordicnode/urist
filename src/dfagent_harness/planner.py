"""Autonomous planner for the DF Agent Harness (phase 4).

The planner is a rule engine, not a model: given one observation
snapshot (plus recent events), it produces a short ordered list of
decisions, each naming one verified action from
:mod:`dfagent_harness.actions` (or a UI-keystroke action from
:mod:`dfagent_harness.ui`). The daemon executes them in order, at
most ``max_actions_per_tick`` per tick, and journals every decision
with its reason and its verified outcome.

Priority order (docs/PLANNER.md): survival needs > safety >
production > expansion. Within a tick the planner takes the FIRST
applicable decision per domain, highest priority first — one
corrective action per domain per tick, so a single bad read cannot
fire off a cascade.

Rules are pure functions of the snapshot (see :func:`decide`) so
they are unit-testable against fixture states; :class:`Planner`
adds the stateful parts (backoff after failures, cooldowns,
already-tried tracking) and executes through ``act()``.

What the planner does NOT do (documented in docs/PLANNER.md):
military squads (UI-only, unimplemented), burrow-based shelter
(no working creation API), hospital/temple/tavern zones (UI-only,
deferred), trade (no caravan on this fort yet), metal industry
(no ore/forge inputs on this fort yet).
"""

from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from dfhack_rpc import DFHackClient

from . import observe
from .actions import act, nobles as probe_nobles

__all__ = [
    "Decision",
    "Planner",
    "Journal",
    "decide",
    "state_summary",
    # Thresholds (measured or adopted — see docs/PLANNER.md).
    "DRINK_WARN",
    "DRINK_CRITICAL",
    "FOOD_WARN",
    "FOOD_CRITICAL",
    "THREAT_NEAR_TILES",
    "THREAT_CRITICAL_TILES",
]

#: Stock thresholds (units). Adopted from dfkit's daemon policy via
#: docs/EVENTS.md (drink < 20 brew, food < 15 cook), for a 15-dwarf
#: fort — the fort has outgrown the 7-dwarf numbers they were tuned
#: for, so the planner scales the warn line with population (see
#: :func:`state_summary`): warn = max(base, citizens).
DRINK_WARN = 20
DRINK_CRITICAL = 5
FOOD_WARN = 15
FOOD_CRITICAL = 5

#: Threat tiers (tiles, Chebyshev distance hostile -> nearest citizen).
#: <= critical: hold the game paused until the threat moves away.
#: <= near: watch — log, and never send work designations near it.
THREAT_NEAR_TILES = 15
THREAT_CRITICAL_TILES = 5

#: How long a failed goal waits before the planner retries it (s).
DEFAULT_BACKOFF_S = 180.0

#: Candidate workshop sites near the wagon/fort centre (95,95,42),
#: tried in order; probe_site verifies each before use.
WORKSHOP_SITES: list[tuple[int, int, int]] = [
    (88, 85, 42), (91, 85, 42), (85, 88, 42), (100, 85, 42),
    (85, 100, 42), (102, 92, 42), (105, 90, 42), (88, 100, 42),
]

#: Dormitory bed grid origin (surface, near the wagon site).
BED_ORIGIN: tuple[int, int, int] = (93, 93, 42)
#: Farm plot site (surface, for surface crops until underground
#: digging opens soil below).
FARM_SITE: tuple[int, int, int] = (80, 80, 42)
#: Food stockpile site (surface, near the wagon site).
FOOD_STOCKPILE_BOX: tuple[int, ...] = (96, 90, 42, 100, 94, 42)
#: Dig plan (retired 2026-11-26): the down-stair + room were hardcoded
#: Athelunol coordinates (100, 100, 42) — the wrong fort and the wrong
#: level (Erushtathtat's surface is z175). The dig site is now
#: derived from the areas by digging.derive_dig_site (the Surface
#: area + the fort centre) and passed in as ``dig_site``; when none
#: is available the planner does not dig rather than digging blind.
#: Gather area (surface shrubs — phase-2 verified tiles).
GATHER_BOX: tuple[int, ...] = (70, 87, 42, 92, 98, 42)


@dataclass
class Decision:
    """One planner decision: what to do, why, and how urgent."""

    priority: int  # lower runs first (1 = act now)
    domain: str    # threat | needs | nobles | production | expansion
    decision: str  # short imperative, e.g. "build a still"
    reason: str    # the state that triggered it, with numbers
    action: str    # act() name or "ui:<fn>"
    kwargs: dict[str, Any] = field(default_factory=dict)
    goal_key: str = ""  # backoff identity, e.g. "drink:brew"

    def to_dict(self) -> dict[str, Any]:
        return {"priority": self.priority, "domain": self.domain,
                "decision": self.decision, "reason": self.reason,
                "action": self.action, "kwargs": self.kwargs,
                "goal_key": self.goal_key}


# ----------------------------------------------------------------------
# Snapshot interpretation (pure functions over an observe state)
# ----------------------------------------------------------------------

def _summary(state: dict[str, Any]) -> dict[str, Any]:
    """Headline numbers the rules read (all from the snapshot)."""
    status = state.get("status") or {}
    stocks = state.get("stocks") or {}
    units = state.get("units") or {}
    buildings = state.get("buildings") or {}
    jobs = state.get("jobs") or {}
    items = state.get("items") or {}
    citizens = units.get("citizens") or []
    summary = {
        # Section presence: a missing section means "unknown", never
        # "zero/absent". A failed collect must not make the planner
        # build a second carpenter or queue a duplicate brew — the
        # rules below skip when the section they need is absent
        # (verified live 2026-11-26: three carpenters #15/#17/#21,
        # one per tick whose buildings section failed).
        "has_buildings": "buildings" in state,
        "has_stocks": "stocks" in state,
        "has_units": "units" in state,
        "has_jobs": "jobs" in state,
        "has_items": "items" in state,
        "tick": status.get("year_tick"),
        "year": status.get("year"),
        "paused": status.get("paused"),
        "citizens": len(citizens),
        "animals": (status.get("population") or {}).get("animals", 0),
        "hostiles": units.get("hostiles") or [],
        "drink": stocks.get("drink_units") or 0,
        "food": stocks.get("food_units") or 0,
        "wood": stocks.get("wood_units") or 0,
        "stone": stocks.get("stone_units") or 0,
        "seeds": stocks.get("seeds_units") or 0,
        "barrels": stocks.get("barrels") or 0,
        "buildings": buildings.get("list") or [],
        "building_summary": {e.get("type"): e.get("count")
                             for e in buildings.get("summary") or []},
        "jobs": jobs.get("list") or [],
        "manager_orders": jobs.get("manager_orders") or [],
        "items_by_type": {e.get("type"): e.get("units", 0)
                          for e in items.get("by_type") or []},
        "by_material": stocks.get("by_material") or [],
        "citizen_list": citizens,
    }
    return summary


def state_summary(state: dict[str, Any]) -> dict[str, Any]:
    """Public wrapper for :func:`_summary` (tests + daemon)."""
    return _summary(state)


def _workshop(summary: dict[str, Any], subtype: str) -> Optional[dict]:
    for b in summary["buildings"]:
        if b.get("type") == "Workshop" and b.get("subtype") == subtype:
            return b
    return None


def _count_jobs(summary: dict[str, Any], job_type: str) -> int:
    return sum(1 for j in summary["jobs"] if j.get("type") == job_type)


def _brewable_plants(summary: dict[str, Any]) -> int:
    """Brewable plant units in stock: PLANT items whose material has
    a DRINK product (by_material entries like
    PLANT:MUSHROOM_HELMET_PLUMP:DRINK)."""
    total = 0
    for e in summary["by_material"]:
        mat = str(e.get("material") or "")
        if mat.startswith("PLANT:") and mat.endswith(":DRINK"):
            total += int(e.get("units") or 0)
    return total


def _nearest_hostile_distance(summary: dict[str, Any]) -> Optional[int]:
    """Chebyshev distance from the nearest hostile to the nearest
    citizen, or None when there are no hostiles/citizens."""
    hostiles = summary["hostiles"]
    citizens = summary["citizen_list"]
    if not hostiles or not citizens:
        return None
    best: Optional[int] = None
    for h in hostiles:
        hp = h.get("pos") or []
        if len(hp) != 3:
            continue
        for c in citizens:
            cp = c.get("pos") or []
            if len(cp) != 3:
                continue
            d = max(abs(hp[0] - cp[0]), abs(hp[1] - cp[1]))
            if hp[2] != cp[2]:
                d += 10  # different z-level: not an immediate threat
            if best is None or d < best:
                best = d
    return best


def _wounded(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in summary["citizen_list"]
            if (c.get("wound_count") or 0) > 0]


def _distressed(summary: dict[str, Any]) -> list[dict[str, Any]]:
    """Citizens past a measured distress line (EVENTS.md)."""
    out = []
    for c in summary["citizen_list"]:
        counters = c.get("counters") or {}
        stress = c.get("stress") or {}
        kinds = []
        if (counters.get("hunger") or 0) >= 50_000:
            kinds.append("starving")
        if (counters.get("thirst") or 0) >= 30_000:
            kinds.append("thirsty")
        if (counters.get("sleepiness") or 0) >= 60_000:
            kinds.append("exhausted")
        if (stress.get("category") in (0, 1)):
            kinds.append("stressed")
        if kinds:
            out.append({"id": c.get("id"), "name": c.get("name"),
                        "kinds": kinds})
    return out


# ----------------------------------------------------------------------
# Rules: decide(state, events) -> ordered decisions (pure)
# ----------------------------------------------------------------------

def decide(state: dict[str, Any],
           events: Optional[list[dict[str, Any]]] = None,
           manager: Optional[bool] = None,
           blocked: Optional[frozenset] = None,
           dig_site: Optional[dict[str, Any]] = None) -> list[Decision]:
    """Decide what to do next from one snapshot (+ recent events).

    ``manager`` overrides the noble read (the daemon passes the
    probe_nobles result; None means "unknown — do not decide on
    nobles this tick"). ``blocked`` is the set of goal keys in
    backoff (the planner passes its failed goals): blocked decisions
    are dropped, and suppression rules ignore blocked goals — so a
    failed still build does not also block the carpenter and the dig
    that could unblock it. ``dig_site`` is the area-derived dig site
    (digging.derive_dig_site: {"stairs", "room"}); when None the
    planner does not dig — the hardcoded coordinates are gone, and
    digging blind is worse than not digging. Returns decisions
    sorted by priority.
    """
    s = _summary(state)
    decisions: list[Decision] = []
    events = events or []
    blocked = blocked or frozenset()

    def _blocked(key: str) -> bool:
        return key in blocked

    # Section gates (see _summary): a rule that needs a section
    # skips when that section is absent. "Unknown" is never read as
    # "zero" or "none" — that is how the fort ended up with three
    # carpenters.
    has_b = s["has_buildings"]
    has_s = s["has_stocks"]
    has_u = s["has_units"]
    has_j = s["has_jobs"]
    has_i = s["has_items"]

    # -- 1. Threats (safety) -------------------------------------------
    dist = _nearest_hostile_distance(s)
    hostile_names = [h.get("race") or h.get("name") or "?"
                     for h in s["hostiles"]]
    if has_u and s["hostiles"] and dist is not None:
        if dist <= THREAT_CRITICAL_TILES:
            decisions.append(Decision(
                1, "threat",
                "hold the fort: hostile within 5 tiles of a citizen",
                f"{len(s['hostiles'])} hostile(s) ({', '.join(hostile_names)}) "
                f"nearest {dist} tiles from a citizen — keep the game "
                f"paused, do not send anyone out",
                "pause", {"paused": True},
                goal_key="threat:hold"))
        elif dist <= THREAT_NEAR_TILES:
            decisions.append(Decision(
                2, "threat",
                "watch hostile, keep work away from it",
                f"{len(s['hostiles'])} hostile(s) ({', '.join(hostile_names)}) "
                f"nearest {dist} tiles from a citizen — wildlife-grade, "
                f"no military exists; shelter by pausing only if it "
                f"closes in",
                "log", {"message": "hostile near, watching"},
                goal_key="threat:watch"))

    # -- 2. Survival: drink --------------------------------------------
    citizens = max(s["citizens"], 1)
    drink_warn = max(DRINK_WARN, citizens)
    drink = s["drink"]
    still = _workshop(s, "Still")
    if has_s and has_b and drink <= DRINK_CRITICAL:
        if still is not None:
            brewable = _brewable_plants(s)
            queued = _count_jobs(s, "CustomReaction")
            if has_j and brewable > 0 and s["barrels"] > 0 \
                    and queued == 0:
                decisions.append(Decision(
                    1, "needs", "brew drink now",
                    f"drink {drink}u (critical <= {DRINK_CRITICAL}) with "
                    f"{brewable} brewable plant units and "
                    f"{s['barrels']} barrels; still #{still['id']} idle",
                    "queue_job",
                    {"building_id": still["id"], "job": "brew",
                     "count": min(5, brewable)},
                    goal_key="drink:brew"))
            elif brewable == 0:
                decisions.append(Decision(
                    1, "needs", "gather plants for brewing",
                    f"drink {drink}u (critical) and no brewable plants "
                    f"in stock — gather surface shrubs",
                    "designate_gather", {"box": list(GATHER_BOX)},
                    goal_key="drink:gather"))
            elif s["barrels"] == 0:
                carpenter0 = _workshop(s, "Carpenters")
                if carpenter0 is not None:
                    decisions.append(Decision(
                        1, "needs", "make barrels for brewing",
                        f"drink {drink}u (critical), brewable plants "
                        f"available, but 0 barrels",
                        "queue_job",
                        {"building_id": carpenter0["id"],
                         "job": "make_barrel", "count": 3},
                        goal_key="drink:barrels"))
                else:
                    decisions.append(Decision(
                        1, "needs", "build a carpenter (no barrels)",
                        f"drink {drink}u (critical), brewable plants "
                        f"available, but 0 barrels and no carpenter "
                        f"to make them",
                        "build_workshop",
                        {"kind": "carpenter",
                         "pos": list(WORKSHOP_SITES[1])},
                        goal_key="drink:barrels"))
        else:
            decisions.append(Decision(
                1, "needs", "build a still (drink critical)",
                f"drink {drink}u (critical <= {DRINK_CRITICAL}) and no "
                f"still exists — wood {s['wood']}u, stone {s['stone']}u",
                "build_workshop",
                {"kind": "still", "pos": list(WORKSHOP_SITES[0])},
                goal_key="drink:still"))
    elif has_s and has_b and drink <= drink_warn:
        if has_j and still is not None and _brewable_plants(s) > 0 \
                and s["barrels"] > 0 \
                and _count_jobs(s, "CustomReaction") == 0:
            decisions.append(Decision(
                3, "needs", "brew drink (stock low)",
                f"drink {drink}u (warn <= {drink_warn}) — top up",
                "queue_job",
                {"building_id": still["id"], "job": "brew", "count": 3},
                goal_key="drink:brew"))

    # -- 2b. Survival: food --------------------------------------------
    food_warn = max(FOOD_WARN, citizens)
    food = s["food"]
    kitchen = _workshop(s, "Kitchen")
    if has_s and has_b and food <= FOOD_CRITICAL:
        if has_j and kitchen is not None \
                and _count_jobs(s, "PrepareMeal") == 0:
            decisions.append(Decision(
                1, "needs", "cook a meal (food critical)",
                f"food {food}u (critical <= {FOOD_CRITICAL}); kitchen "
                f"#{kitchen['id']} idle",
                "queue_job",
                {"building_id": kitchen["id"], "job": "cook",
                 "count": 2},
                goal_key="food:cook"))
        elif kitchen is None:
            decisions.append(Decision(
                2, "needs", "gather plants for food",
                f"food {food}u (critical) and no kitchen — gather "
                f"surface shrubs for raw food now",
                "designate_gather", {"box": list(GATHER_BOX)},
                goal_key="food:gather"))
    elif has_s and has_b and food <= food_warn:
        if has_j and kitchen is not None \
                and _count_jobs(s, "PrepareMeal") == 0:
            decisions.append(Decision(
                3, "needs", "cook a meal (food low)",
                f"food {food}u (warn <= {food_warn}) — top up",
                "queue_job",
                {"building_id": kitchen["id"], "job": "cook",
                 "count": 2},
                goal_key="food:cook"))

    # -- 2c. Distress (starving/thirsty/wounded) ------------------------
    distressed = _distressed(s)
    if distressed:
        names = ", ".join(
            f"{d['name']} ({'/'.join(d['kinds'])})" for d in distressed)
        decisions.append(Decision(
            1, "needs", "a dwarf is in distress",
            f"{len(distressed)} citizen(s) past a distress line: "
            f"{names} — check drink/food stocks first (the usual "
            f"cause); no hospital zone exists yet (see PLANNER.md)",
            "log", {"message": f"distress: {names}"},
            goal_key="needs:distress"))

    # -- 3. Nobles (manager gates all manager orders) -------------------
    if manager is False:
        # Appoint the expedition leader (first adult citizen) — the
        # daemon resolves the unit id; the decision names the rule.
        leader = next((c for c in s["citizen_list"]
                       if c.get("profession") != "Dwarven Child"), None)
        if leader is not None:
            decisions.append(Decision(
                2, "nobles", "appoint a manager",
                "no manager appointed — manager orders are never "
                "worked without one (verified live)",
                "ui:appoint_noble",
                {"position": "manager", "unit_id": leader["id"]},
                goal_key="nobles:manager"))

    # -- 4. Production: workshops ---------------------------------------
    carpenter = _workshop(s, "Carpenters")
    if has_b and has_s and carpenter is None and s["wood"] >= 1 \
            and not any(
            d.goal_key == "drink:still" and not _blocked(d.goal_key)
            for d in decisions):
        decisions.append(Decision(
            4, "production", "build a carpenter's workshop",
            f"no carpenter's workshop; wood {s['wood']}u — needed "
            f"for beds and barrels",
            "build_workshop",
            {"kind": "carpenter", "pos": list(WORKSHOP_SITES[1])},
            goal_key="production:carpenter"))
    if has_b and has_s and kitchen is None and s["stone"] >= 1:
        decisions.append(Decision(
            4, "production", "build a kitchen",
            f"no kitchen; stone {s['stone']}u — needed to cook meals",
            "build_workshop",
            {"kind": "kitchen", "pos": list(WORKSHOP_SITES[2])},
            goal_key="production:kitchen"))

    # -- 4b. Beds --------------------------------------------------------
    beds = s["building_summary"].get("Bed", 0)
    bed_items = s["items_by_type"].get("BED", 0)
    if has_b and has_i and carpenter is not None \
            and beds < s["citizens"]:
        if bed_items > 0:
            # Place beds in a grid from BED_ORIGIN; find the first
            # free 1x1 the daemon will verify (site check happens in
            # the action). Queue one placement per tick.
            idx = beds
            pos = [BED_ORIGIN[0] + (idx % 5),
                   BED_ORIGIN[1] + (idx // 5),
                   BED_ORIGIN[2]]
            decisions.append(Decision(
                4, "production", "place a bed",
                f"{beds} beds for {s['citizens']} citizens; "
                f"{bed_items} bed item(s) in stock",
                "build_furniture",
                {"kind": "Bed", "pos": pos},
                goal_key="production:bed"))
        elif has_s and has_j and s["wood"] >= 1 \
                and _count_jobs(s, "CustomReaction") == 0:
            decisions.append(Decision(
                4, "production", "make beds at the carpenter",
                f"{beds} beds for {s['citizens']} citizens and no bed "
                f"items in stock; wood {s['wood']}u",
                "queue_job",
                {"building_id": carpenter["id"], "job": "make_bed",
                 "count": min(3, s["wood"])},
                goal_key="production:make_bed"))

    # -- 5. Expansion: digging for stone + farm space -------------------
    # The dig site is area-derived (digging.derive_dig_site), never
    # hardcoded: a down-stair on the Surface near the fort centre,
    # then a room one z-level below. The action is dig_to_completion
    # (check -> designate -> job -> terrain change), not a bare
    # designation. No site, no dig.
    if has_s and s["stone"] == 0 and dig_site is not None and not any(
            d.goal_key.startswith("drink:") and not _blocked(d.goal_key)
            for d in decisions):
        stairs = dig_site["stairs"]
        decisions.append(Decision(
            5, "expansion", "dig down for stone",
            "stone 0u — no mason/kitchen/still-from-stone until the "
            "fort digs below the surface",
            "dig_to_completion",
            {"box": [stairs[0], stairs[1], stairs[2],
                     stairs[0], stairs[1], stairs[2]],
             "mode": "down-stair"},
            goal_key="expansion:dig"))
    if has_b and s["building_summary"].get("Stockpile", 0) == 0:
        decisions.append(Decision(
            5, "expansion", "create a food stockpile",
            "no stockpile yet — food sits where it falls and rots; "
            "a food stockpile near the fort keeps it hauled in",
            "ui:create_stockpile",
            {"box": list(FOOD_STOCKPILE_BOX), "category": "f"},
            goal_key="expansion:food-stockpile"))
    # Farm plot once a still exists and seeds are on hand (surface
    # plot first; underground when the dug room exists).
    farm_plots = s["building_summary"].get("FarmPlot", 0)
    if has_b and has_s and farm_plots == 0 and s["seeds"] >= 5 \
            and still is not None:
        decisions.append(Decision(
            5, "expansion", "build a farm plot",
            f"{s['seeds']} seeds in stock and no farm plot — surface "
            f"plot first (underground when dug)",
            "build_farm_plot",
            {"x": FARM_SITE[0], "y": FARM_SITE[1], "z": FARM_SITE[2],
             "width": 3, "height": 3},
            goal_key="expansion:farm"))

    decisions.sort(key=lambda d: (d.priority, d.domain))
    # Dedup identical actions (same act + kwargs): the drink-gather
    # and food-gather rules can both fire on the same box in one
    # tick — running designate_gather twice is a no-op re-mark, so
    # keep only the first (highest-priority) copy.
    seen: set[tuple[str, str]] = set()
    deduped: list[Decision] = []
    for d in decisions:
        key = (d.action, json.dumps(d.kwargs, sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(d)
    return [d for d in deduped if d.goal_key not in blocked]


# ----------------------------------------------------------------------
# Journal (SQLite): every decision + outcome, queryable by the daemon
# ----------------------------------------------------------------------

class Journal:
    """Append-only SQLite journal for planner decisions and daemon
    events. One file in the daemon state dir (``journal.db``)."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at REAL NOT NULL,
        tick INTEGER,
        year INTEGER,
        priority INTEGER NOT NULL,
        domain TEXT NOT NULL,
        decision TEXT NOT NULL,
        reason TEXT NOT NULL,
        action TEXT NOT NULL,
        goal_key TEXT NOT NULL,
        ok INTEGER,
        result TEXT,
        took_ms INTEGER
    );
    CREATE TABLE IF NOT EXISTS daemon_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        at REAL NOT NULL,
        tick INTEGER,
        kind TEXT NOT NULL,
        detail TEXT
    );
    CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        expression TEXT NOT NULL,
        task TEXT NOT NULL,
        priority INTEGER NOT NULL DEFAULT 5,
        created_at REAL NOT NULL,
        done INTEGER NOT NULL DEFAULT 0
    );
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.executescript(self.SCHEMA)
        self._db.commit()

    def log_decision(self, decision: Decision, tick: Optional[int],
                     year: Optional[int], ok: Optional[bool] = None,
                     result: Optional[str] = None,
                     took_ms: Optional[int] = None) -> int:
        cur = self._db.execute(
            "INSERT INTO decisions (at, tick, year, priority, domain, "
            "decision, reason, action, goal_key, ok, result, took_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), tick, year, decision.priority, decision.domain,
             decision.decision, decision.reason, decision.action,
             decision.goal_key,
             None if ok is None else (1 if ok else 0),
             result, took_ms))
        self._db.commit()
        return cur.lastrowid

    def log_event(self, kind: str, detail: str = "",
                  tick: Optional[int] = None) -> int:
        cur = self._db.execute(
            "INSERT INTO daemon_events (at, tick, kind, detail) "
            "VALUES (?, ?, ?, ?)",
            (time.time(), tick, kind, detail))
        self._db.commit()
        return cur.lastrowid

    def recent_decisions(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT at, tick, year, priority, domain, decision, reason, "
            "action, goal_key, ok, result, took_ms FROM decisions "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        keys = ("at", "tick", "year", "priority", "domain", "decision",
                "reason", "action", "goal_key", "ok", "result", "took_ms")
        return [dict(zip(keys, r)) for r in rows]

    def recent_events(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT at, tick, kind, detail FROM daemon_events "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        keys = ("at", "tick", "kind", "detail")
        return [dict(zip(keys, r)) for r in rows]

    def decision_counts(self) -> dict[str, int]:
        rows = self._db.execute(
            "SELECT domain, COUNT(*) FROM decisions GROUP BY domain"
            ).fetchall()
        return {d: n for d, n in rows}

    # -- goals -----------------------------------------------------------
    def create_goal(self, name: str, expression: str, task: str,
                    priority: int = 5) -> int:
        cur = self._db.execute(
            "INSERT INTO goals (name, expression, task, priority, "
            "created_at) VALUES (?, ?, ?, ?, ?)",
            (name, expression, task, priority, time.time()))
        self._db.commit()
        return cur.lastrowid

    def list_goals(self) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT id, name, expression, task, priority, created_at, "
            "done FROM goals ORDER BY priority, id").fetchall()
        keys = ("id", "name", "expression", "task", "priority",
                "created_at", "done")
        return [dict(zip(keys, r)) for r in rows]

    def get_goal(self, goal_id: int) -> Optional[dict[str, Any]]:
        row = self._db.execute(
            "SELECT id, name, expression, task, priority, created_at, "
            "done FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if row is None:
            return None
        keys = ("id", "name", "expression", "task", "priority",
                "created_at", "done")
        return dict(zip(keys, row))

    def mark_goal_done(self, goal_id: int) -> bool:
        cur = self._db.execute(
            "UPDATE goals SET done = 1 WHERE id = ?", (goal_id,))
        self._db.commit()
        return cur.rowcount > 0

    def delete_goal(self, goal_id: int) -> bool:
        cur = self._db.execute(
            "DELETE FROM goals WHERE id = ?", (goal_id,))
        self._db.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._db.close()


# ----------------------------------------------------------------------
# Planner: decide + execute (stateful: backoff, cooldowns)
# ----------------------------------------------------------------------

class Planner:
    """Runs :func:`decide` against live state and executes the top
    decisions through the verified action layer.

    ``execute`` takes at most ``max_actions_per_tick`` decisions per
    tick (default 2), skipping goals in backoff (a failure waits
    ``backoff_s`` before retry) and decisions whose action is "log"
    (recorded, not executed). The game is left paused by the action
    layer after every action; the daemon owns unpausing.
    """

    def __init__(self, client: DFHackClient, journal: Journal,
                 backoff_s: float = DEFAULT_BACKOFF_S,
                 max_actions_per_tick: int = 2,
                 display: str = ":99",
                 ui_appoint: Optional[Callable[..., dict]] = None,
                 ui_stockpile: Optional[Callable[..., dict]] = None,
                 ) -> None:
        self.client = client
        self.journal = journal
        self.backoff_s = backoff_s
        self.max_actions_per_tick = max_actions_per_tick
        self.display = display
        self._ui_appoint = ui_appoint
        self._ui_stockpile = ui_stockpile
        self._last_attempt: dict[str, float] = {}
        self._last_failure: dict[str, float] = {}
        self.ticks = 0
        self.decisions_made = 0
        self.actions_ok = 0
        self.actions_failed = 0

    # -- one tick --------------------------------------------------------
    def tick(self, state: dict[str, Any],
             events: Optional[list[dict[str, Any]]] = None,
             manager: Optional[bool] = None,
             dig_site: Optional[dict[str, Any]] = None
             ) -> list[dict[str, Any]]:
        """Decide + execute. Returns one journal-ready record per
        decision considered (executed, logged, or skipped).
        ``dig_site`` is the area-derived dig site (see decide)."""
        self.ticks += 1
        s = _summary(state)
        tick = s["tick"]
        year = s["year"]
        records: list[dict[str, Any]] = []
        now = time.time()
        blocked = frozenset(
            k for k, t in self._last_failure.items()
            if now - t < self.backoff_s)
        try:
            decisions = decide(state, events, manager=manager,
                               blocked=blocked, dig_site=dig_site)
        except Exception as exc:  # noqa: BLE001 - planner must not die
            self.journal.log_event(
                "planner_error", f"decide() failed: {exc}", tick=tick)
            return records
        executed = 0
        for d in decisions:
            if executed >= self.max_actions_per_tick:
                records.append({**d.to_dict(), "status": "deferred",
                                "ok": None})
                continue
            now = time.time()
            last_fail = self._last_failure.get(d.goal_key, 0.0)
            if now - last_fail < self.backoff_s:
                records.append({**d.to_dict(), "status": "backoff",
                                "ok": None})
                continue
            self.decisions_made += 1
            if d.action == "log":
                self.journal.log_decision(d, tick, year, ok=True,
                                          result="logged")
                records.append({**d.to_dict(), "status": "logged",
                                "ok": True})
                continue
            if d.action == "pause":
                try:
                    from .actions import set_paused
                    set_paused(self.client, bool(d.kwargs.get("paused")))
                    self.journal.log_decision(d, tick, year, ok=True,
                                              result="paused")
                    records.append({**d.to_dict(), "status": "executed",
                                    "ok": True})
                    executed += 1
                except Exception as exc:  # noqa: BLE001
                    self._last_failure[d.goal_key] = now
                    self.journal.log_decision(d, tick, year, ok=False,
                                              result=str(exc))
                    records.append({**d.to_dict(), "status": "failed",
                                    "ok": False})
                continue
            if d.action.startswith("ui:"):
                ok, result = self._run_ui(d)
                self._record(d, tick, year, ok, result, now, records)
                if ok:
                    executed += 1
                continue
            started = time.monotonic()
            result = act(self.client, d.action, state=state, **d.kwargs)
            took_ms = round((time.monotonic() - started) * 1000)
            # The recorded result carries the fix (layer 4) so the
            # journal shows cause AND fix, and the loop detector can
            # see whether the next attempt changed approach.
            recorded = result.reason
            if result.fix:
                recorded = f"{result.reason} {result.fix}"
            self._record(d, tick, year, result.ok, recorded, now,
                         records, took_ms=took_ms)
            self._last_attempt[d.goal_key] = now
            if result.ok:
                self.actions_ok += 1
                executed += 1
            else:
                self.actions_failed += 1
                if result.error_kind in ("verification", "timeout",
                                         "precondition"):
                    # A failed attempt waits out the backoff; a
                    # transport failure (unknown outcome) does not
                    # count as a goal failure — the next tick re-reads.
                    if result.error_kind != "transport":
                        self._last_failure[d.goal_key] = now
        return records

    def _record(self, d: Decision, tick: Optional[int],
                year: Optional[int], ok: bool, result: str, now: float,
                records: list[dict[str, Any]],
                took_ms: Optional[int] = None) -> None:
        self.journal.log_decision(d, tick, year, ok=ok, result=result,
                                  took_ms=took_ms)
        records.append({**d.to_dict(),
                        "status": "executed" if ok else "failed",
                        "ok": ok, "result": result})

    def _run_ui(self, d: Decision) -> tuple[bool, str]:
        """Run a ui: action (keystroke menu). Returns (ok, reason)."""
        name = d.action[3:]
        try:
            if name == "appoint_noble" and self._ui_appoint is not None:
                out = self._ui_appoint(
                    self.client, d.kwargs["position"],
                    d.kwargs["unit_id"], display=self.display)
                return bool(out.get("ok")), str(out.get("reason"))
            if name == "create_stockpile" and self._ui_stockpile is not None:
                out = self._ui_stockpile(
                    self.client, tuple(d.kwargs["box"]),
                    d.kwargs.get("category", "f"),
                    display=self.display)
                return bool(out.get("ok")), str(out.get("reason"))
        except Exception as exc:  # noqa: BLE001 - UI failure is a result
            return False, f"ui action {name} failed: {exc}"
        return False, f"no UI handler for {name}"

    # -- status ----------------------------------------------------------
    def status(self) -> dict[str, Any]:
        return {"ticks": self.ticks,
                "decisions_made": self.decisions_made,
                "actions_ok": self.actions_ok,
                "actions_failed": self.actions_failed,
                "goals_in_backoff": len(self._last_failure)}
