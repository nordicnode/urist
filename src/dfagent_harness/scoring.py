"""Model benchmarking score (GOAL.md item 15).

A smart, sophisticated scoring system so different AI models can be
benchmarked against each other on the same fort. Computed by the
HARNESS from live game state, the run log, and the store — never
self-reported by the model. Same start conditions for every run
(clean 04-01 base, fixed tick budget), so scores are comparable.

Dimensions (each 0-100) and weights — survival and lives dominate,
wealth is low, milestones are a bonus, so building cheap junk to
inflate value cannot win:

    survival   30  in-game days lasted vs the run's planned duration
    lives      30  citizen deaths; preventable (thirst/starvation)
                    penalised heaviest, then combat, then mood/other
    wealth     10  fortress-value growth (end - start) / start
    needs      10  drink/food never hitting zero; no dwarf left
                    dangerously hungry/thirsty
    growth      5  population change, workshops built, beds/rooms
    competence 10  idle ticks, failed actions, repeated failures,
                    model reliability, suggestion handling
    threats     5  dwarves lost to hostiles
    milestones  +2 each (cap +10): first brew, first bed, first farm,
                    first trade, first mood resolved

The composite is the weighted sum (0-100) plus the milestone bonus,
capped at 100. The per-dimension breakdown is always reported
alongside the composite, so a score never hides a tradeoff.

Wealth (see docs/SCORING.md for the full definition): there is NO
direct wealth read in DFHack 0.47.05-r8 (df.global.ui has no `wealth`
field, dfhack.economy is nil — verified live 2026-11-27). Fortress
value is the sum of dfhack.items.getValue over the fort's own items
(IN_PLAY, excluding trader-held goods, items lying on the ground, and
abstract world artifacts; lua/wealth.lua, GET /v1/wealth). It is the
fort's total item value (imports + created), NOT the z-screen created
wealth — the module never claims otherwise.

Scores are stored in a leaderboard (scores.db in the daemon state
dir) with model, start save, tick budget, and date, so runs
accumulate into a real comparison. DF's own RNG means exact
reproducibility may not hold — the leaderboard records the date and
the run log, and repeat runs should be averaged where it matters.

Distinct from the dfkit See/Target/Act/Verify scorecard (GOAL.md
step 11), which scores the HARNESS, not the model.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# -- weights ------------------------------------------------------------
# Survival and lives dominate; wealth is low; milestones are a bonus.
WEIGHTS: dict[str, float] = {
    "survival": 30.0,
    "lives": 30.0,
    "wealth": 10.0,
    "needs": 10.0,
    "growth": 5.0,
    "competence": 10.0,
    "threats": 5.0,
}
MILESTONE_BONUS_EACH = 2.0
MILESTONE_BONUS_CAP = 10.0

# -- thresholds (live-verified, phase 1) ---------------------------------
# Hunger climbs 1/tick; a dwarf eats at ~40,000. Thirst climbs 1/tick;
# a dwarf drinks at ~20,000. "Dangerously" above the trigger means the
# dwarf could not eat/drink when it needed to (no food/drink available).
HUNGER_TRIGGER = 40_000
THIRST_TRIGGER = 20_000
HUNGER_DANGEROUS = 50_000
THIRST_DANGEROUS = 30_000
TICKS_PER_DAY = 1200

# Death-cause classification (from the store's diagnose_death cause).
_PREVENTABLE = ("thirst", "starv", "hunger", "dehydrat")
_COMBAT = ("combat", "killed", "slain", "wound", "attack", "maul")
_MOOD = ("mood", "insane", "melancholy", "tantrum", "berserk",
         "stark raving")


def classify_death(cause: str) -> str:
    """Classify a death cause: preventable | combat | mood | other.

    Preventable means the fort failed the dwarf (thirst/starvation) —
    penalised heaviest. Combat is a hostile kill. Mood is a strange
    mood / insanity death. Anything else is 'other'.
    """
    c = (cause or "").lower()
    if any(k in c for k in _PREVENTABLE):
        return "preventable"
    if any(k in c for k in _COMBAT):
        return "combat"
    if any(k in c for k in _MOOD):
        return "mood"
    return "other"


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# -- dimensions (pure functions; each unit-testable) ---------------------

def survival_score(days_lasted: float, days_planned: float) -> float:
    """Days lasted vs planned. A run that lasts its full planned
    duration scores 100; a fort that dies early scores in proportion
    to how far it got."""
    if days_planned <= 0:
        return 100.0 if days_lasted > 0 else 0.0
    return _clamp(100.0 * days_lasted / days_planned)


def lives_score(deaths: list[dict[str, Any]]) -> float:
    """Start at 100; each citizen death penalised by kind. A death
    the fort could have prevented (thirst/starvation) costs 40 — a
    fort that lets a dwarf die of thirst has failed at the one thing
    M1 exists to prove. Combat costs 20, mood 15, other 10."""
    penalty = {"preventable": 40.0, "combat": 20.0, "mood": 15.0,
               "other": 10.0}
    score = 100.0
    for d in deaths:
        kind = d.get("kind") or classify_death(d.get("cause", ""))
        score -= penalty.get(kind, 10.0)
    return _clamp(score)


def wealth_score(start_value: Optional[float],
                 end_value: Optional[float]) -> float:
    """Fortress-value growth, centred on 50 (no change scores 50, not
    0 — a fort that held its value did not fail). +1 point per
    percentage point of growth, clamped 0-100. Without both readings
    the dimension is neutral 50 and the breakdown says so."""
    if start_value is None or end_value is None:
        return 50.0
    if start_value <= 0:
        return 100.0 if end_value > 0 else 50.0
    growth_pct = (end_value - start_value) / start_value * 100.0
    return _clamp(50.0 + growth_pct)


def needs_score(zero_stock: bool, dangerous_fraction: float) -> float:
    """100 minus 50 if drink or food hit zero at any sampled tick,
    minus up to 50 for the fraction of citizen-time spent dangerously
    hungry/thirsty (counters far above the eat/drink trigger, meaning
    the dwarf could not eat/drink when it needed to)."""
    score = 100.0
    if zero_stock:
        score -= 50.0
    score -= 50.0 * _clamp(dangerous_fraction, 0.0, 1.0)
    return _clamp(score)


def growth_score(pop_start: int, pop_end: int, workshops_built: int,
                 beds_built: int) -> float:
    """50 base + 10 per workshop built (cap +20) + 5 per bed/room
    completed (cap +15) + 5 per net population gained (cap +15).
    Population loss does not penalise here — deaths are already
    counted in lives; growth measures what the fort built."""
    score = 50.0
    score += min(20.0, 10.0 * max(0, workshops_built))
    score += min(15.0, 5.0 * max(0, beds_built))
    score += min(15.0, 5.0 * max(0, pop_end - pop_start))
    return _clamp(score)


def competence_score(idle_ticks: int, failed_actions: int,
                     repeated_failures: int, model_failures: int,
                     suggestions_matched: int,
                     suggestions_total: int) -> float:
    """100 minus 10 per idle tick, 5 per failed action, 10 per
    repeated failure (the same action failing twice or more — the
    failure memory the design demands), 5 per model failure (a Free
    Pi IncompleteRead counts here: model reliability is part of
    competence), and up to 5 for ignoring the snapshot's suggestions
    (proportional to the fraction ignored; no suggestions means no
    penalty). A correct fail-fast that names the fix is still a
    failed action — the model asked for something it could not do —
    but it is only 5 points, and the suggestion penalty is where
    ignoring the named fix shows up."""
    score = 100.0
    score -= 10.0 * max(0, idle_ticks)
    score -= 5.0 * max(0, failed_actions)
    score -= 10.0 * max(0, repeated_failures)
    score -= 5.0 * max(0, model_failures)
    if suggestions_total > 0:
        ignored = 1.0 - suggestions_matched / suggestions_total
        score -= 5.0 * _clamp(ignored, 0.0, 1.0)
    return _clamp(score)


def threats_score(hostile_deaths: int) -> float:
    """100 minus 20 per dwarf lost to hostiles. Facing a threat and
    surviving it with no losses scores 100 — the dimension measures
    what threats cost, not whether any appeared."""
    return _clamp(100.0 - 20.0 * max(0, hostile_deaths))


def milestone_bonus(achieved: set[str]) -> float:
    """+2 per achieved milestone (first brew, first bed, first farm,
    first trade, first mood resolved), capped at +10."""
    return min(MILESTONE_BONUS_CAP, MILESTONE_BONUS_EACH * len(achieved))


def composite(dimensions: dict[str, float],
              milestones: set[str]) -> float:
    """Weighted sum of the seven dimensions plus the milestone bonus,
    capped at 100."""
    total = sum(WEIGHTS[k] * dimensions.get(k, 0.0)
                for k in WEIGHTS) / 100.0
    return _clamp(total + milestone_bonus(milestones))


# -- run-log parsing ------------------------------------------------------

_STOCKS_RE = re.compile(r"drink\s+(\d+),\s*food\s+(\d+)")
_BED_HAVE_RE = re.compile(r"Bed:.*?have\s+(\d+)", re.IGNORECASE)


def parse_snapshot_stocks(text: str) -> Optional[dict[str, int]]:
    """Parse the `Stocks: drink N, food M, ...` line from a snapshot's
    text (the same line m1_driver.parse_snapshot_stocks_text reads).
    Returns None when the line is absent (a diffed snapshot)."""
    m = _STOCKS_RE.search(text or "")
    if not m:
        return None
    return {"drink": int(m.group(1)), "food": int(m.group(2))}


def parse_bed_have(text: str) -> Optional[int]:
    """Parse the `Bed: need 1 BED item to place — have N` line from a
    snapshot's text (the material-awareness line). None when absent."""
    m = _BED_HAVE_RE.search(text or "")
    if not m:
        return None
    return int(m.group(1))


# Suggestion -> job matching. The snapshot's suggestion is free-form
# prose ("Suggested action: ... build_workshop kind=still ...", "run
# the brew task (POST /v1/tasks/brew)", "queue make_barrel at the
# carpenter #7"). Both sides are normalised to a job string; a tick
# matches when any action that tick has the same job. Matching on the
# job (not the verb) is deliberate: the tick-2 suggestion says "run
# the brew task" and the model queued brew via queue_job — same intent,
# different verb — and that counts as followed. A tick whose
# suggestion has no extractable job is skipped, not penalised.
_SUGGESTION_PATTERNS: list[tuple[str, str]] = [
    (r"build[ _]workshop[^a-z]*kind\s*=\s*still|build a still",
     "build_still"),
    (r"make_barrel", "make_barrel"),
    (r"make_bed", "make_bed"),
    (r"brew", "brew"),
    (r"gather", "gather"),
    (r"cook|prepare\s+meal|preparemeal", "cook"),
    (r"chop", "chop"),
    (r"\bdig\b", "dig"),
]


def suggestion_job(text: str) -> Optional[str]:
    """Normalise a suggestion's prose to a job string, or None when
    no known job is named."""
    low = (text or "").lower()
    for pattern, job in _SUGGESTION_PATTERNS:
        if re.search(pattern, low):
            return job
    return None


def action_job(action: dict[str, Any]) -> Optional[str]:
    """Normalise a logged action to a job string, or None when the
    action has no job (e.g. a query)."""
    name = (action.get("name") or "").lower()
    params = action.get("params") or {}
    if name == "build_workshop":
        kind = str(params.get("kind", "")).lower()
        return f"build_{kind}" if kind else None
    if name == "queue_job":
        job = str(params.get("job", "")).lower()
        return job or None
    if name == "run_task":
        task = str(params.get("name", "") or params.get("task", "")
                   ).lower()
        return task or None
    if name in ("gather", "chop", "dig"):
        return name
    return None


def suggestion_matches(snapshots: list[dict[str, Any]],
                       actions: list[dict[str, Any]],
                       exclude_tick_no: Optional[int] = None
                       ) -> tuple[int, int]:
    """Count (matched, total) suggestion ticks. Each snapshot carrying
    a suggestion with an extractable job is one tick; it matches when
    any action logged in the same tick_no has the same job.
    ``exclude_tick_no`` skips one tick — the run's final snapshot:
    the driver ends the run on that snapshot (day complete / fort
    dead / hard error) BEFORE calling the model, so the model never
    acts on its suggestion, and counting it as ignored would be a
    systematic one-tick penalty on every run."""
    by_tick: dict[int, list[dict[str, Any]]] = {}
    for a in actions:
        by_tick.setdefault(a.get("tick_no", -1), []).append(a)
    matched = total = 0
    for snap in snapshots:
        if (exclude_tick_no is not None
                and snap.get("tick_no") == exclude_tick_no):
            continue
        job = suggestion_job(snap.get("suggestion") or "")
        if job is None:
            continue
        total += 1
        tick_actions = by_tick.get(snap.get("tick_no", -1), [])
        if any(action_job(a) == job for a in tick_actions):
            matched += 1
    return matched, total


def parse_run_log(path: str | Path) -> dict[str, Any]:
    """Parse an m1 run log (JSONL) into the structured inputs the
    score needs. Unknown record kinds are ignored."""
    records: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    run: dict[str, Any] = {
        "model": None, "days_planned": None, "window": None,
        "start_tick": None, "end_tick": None, "date": None,
        "actions": [], "snapshots": [], "model_failures": 0,
        "idle_ticks": 0, "run_end": None, "citizens_start": None,
        "citizens_end": None, "wealth_start": None,
        "wealth_end": None, "final_snapshot_tick_no": None,
        "records": records,
    }
    last_snapshot_tick_no: Optional[int] = None
    for r in records:
        kind = r.get("kind")
        if kind == "run_start":
            run["model"] = r.get("model")
            run["days_planned"] = r.get("days")
            run["window"] = r.get("window")
        elif kind == "start_tick":
            run["start_tick"] = r.get("start_tick")
            run["end_tick"] = r.get("end_tick")
            run["date"] = r.get("date")
        elif kind == "snapshot":
            run["snapshots"].append(r)
            last_snapshot_tick_no = r.get("tick_no")
        elif kind == "action":
            run["actions"].append(r)
        elif kind == "model_failure":
            run["model_failures"] += 1
        elif kind == "run_end":
            run["run_end"] = r
            run["idle_ticks"] = r.get("idle_ticks", 0) or 0
            # The snapshot immediately before run_end is the run's
            # final snapshot: the driver ends the run on it before
            # calling the model, so its suggestion was never acted
            # on (see suggestion_matches).
            run["final_snapshot_tick_no"] = last_snapshot_tick_no
        elif kind == "diary_citizens":
            if r.get("when") == "start":
                run["citizens_start"] = r.get("count")
            elif r.get("when") == "end":
                run["citizens_end"] = r.get("count")
        elif kind == "wealth":
            val = r.get("fortress_value")
            if r.get("when") == "start":
                run["wealth_start"] = val
            elif r.get("when") == "end":
                run["wealth_end"] = val
    return run


def repeated_failures(actions: list[dict[str, Any]]) -> int:
    """Number of repeat failures: for each (action, job) group that
    failed twice or more, count the failures beyond the first. A
    single failure is a mistake; repeating it is the loop the design
    demands the agent break out of."""
    from collections import Counter
    counts: Counter[tuple[str, Optional[str]]] = Counter()
    for a in actions:
        if not a.get("ok", True):
            counts[(a.get("name"), action_job(a))] += 1
    return sum(c - 1 for c in counts.values() if c >= 2)


def milestones_from_log(run: dict[str, Any]) -> set[str]:
    """Milestones achievable from the run log alone. Conservative:
    a milestone counts only on positive evidence, never on a queue.
    - first brew: a brew was queued AND drink rose across the run's
      snapshots (brewing adds 5 drink per brew; dwarves drinking
      pulls it down, so a net rise means brewing outpaced drinking).
    - first bed: a make_bed was queued AND a later snapshot shows a
      BED item available to place (have >= 1).
    - first farm / first trade / first mood resolved: not yet
      detectable from the log (no plant action, no trade event, no
      mood event in the harness) — always False, documented in
      docs/SCORING.md. They become detectable when those systems
      land; the code must not claim them before then."""
    achieved: set[str] = set()
    actions = run.get("actions") or []
    snapshots = run.get("snapshots") or []
    stocks = [parse_snapshot_stocks(s.get("text", ""))
              for s in snapshots]
    stocks = [s for s in stocks if s is not None]
    if any(action_job(a) == "brew" and a.get("ok")
           for a in actions) and len(stocks) >= 2:
        if stocks[-1]["drink"] > stocks[0]["drink"]:
            achieved.add("first brew")
    bed_queued_tick = None
    for a in actions:
        if action_job(a) == "make_bed" and a.get("ok"):
            bed_queued_tick = a.get("tick_no", -1)
            break
    if bed_queued_tick is not None:
        for s in snapshots:
            if s.get("tick_no", -1) < bed_queued_tick:
                continue
            have = parse_bed_have(s.get("text", ""))
            if have is not None and have >= 1:
                achieved.add("first bed")
                break
    return achieved


# -- score computation ----------------------------------------------------

@dataclass
class Score:
    """A computed score: the composite, the per-dimension breakdown,
    the milestones, and the evidence each dimension was computed
    from (so a score can be audited, never just asserted)."""
    model: str
    run_log: str
    start_save: str
    tick_budget: int
    days_planned: float
    date: str
    composite: float
    dimensions: dict[str, float]
    milestones: set[str] = field(default_factory=set)
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "run_log": self.run_log,
            "start_save": self.start_save,
            "tick_budget": self.tick_budget,
            "days_planned": self.days_planned,
            "date": self.date,
            "composite": round(self.composite, 1),
            "dimensions": {k: round(v, 1)
                           for k, v in self.dimensions.items()},
            "milestones": sorted(self.milestones),
            "milestone_bonus": round(
                milestone_bonus(self.milestones), 1),
            "evidence": self.evidence,
        }


def compute_score(run_log: str | Path,
                  store: Any = None,
                  events_path: str | Path | None = None,
                  wealth_start: Optional[float] = None,
                  wealth_end: Optional[float] = None,
                  model: Optional[str] = None,
                  start_save: str = "region2-00125-04-01-clean",
                  ) -> Score:
    """Compute a score for one run.

    ``run_log`` is the m1-*.jsonl log. ``store`` is a Store (world.db)
    or None (deaths and needs then come from the log alone, and the
    evidence says so). ``events_path`` is the daemon's events.jsonl
    or None (threats then come from the log's snapshots only).
    ``wealth_start`` / ``wealth_end`` override the log's wealth
    records (the log's `wealth` records win when the arguments are
    None). Everything is computed from the harness's own records —
    never from what the model claimed.
    """
    run = parse_run_log(run_log)
    start_tick = run.get("start_tick") or 0
    end_tick = run.get("end_tick") or start_tick
    run_end = run.get("run_end") or {}
    end_reason = run_end.get("reason", "unknown")
    last_tick = run_end.get("tick") or end_tick
    days_planned = float(run.get("days_planned") or 1.0)
    days_lasted = max(0.0, (last_tick - start_tick) / TICKS_PER_DAY)
    model_name = model or run.get("model") or "unknown"
    tick_budget = int(days_planned * TICKS_PER_DAY)

    actions = run.get("actions") or []
    failed = [a for a in actions if not a.get("ok", True)]
    matched, total_sugg = suggestion_matches(
        run.get("snapshots") or [], actions,
        exclude_tick_no=run.get("final_snapshot_tick_no"))

    # -- deaths: the store's deaths table is the authority (citizen
    # deaths with a diagnosed cause). Events are a cross-check only
    # when the store has no death for a citizen that died.
    deaths: list[dict[str, Any]] = []
    if store is not None:
        for d in store.deaths():
            if start_tick <= d.get("tick", 0) <= max(last_tick, end_tick):
                kind = classify_death(d.get("cause", ""))
                deaths.append({"unit_id": d.get("unit_id"),
                               "tick": d.get("tick"),
                               "cause": d.get("cause", ""),
                               "kind": kind})
    hostile_deaths = sum(1 for d in deaths if d["kind"] == "combat")

    # -- needs: zero-stock ticks from the log's snapshot stocks lines;
    # dangerous counters from unit_history in the run's tick range.
    stocks = [parse_snapshot_stocks(s.get("text", ""))
              for s in (run.get("snapshots") or [])]
    stocks = [s for s in stocks if s is not None]
    zero_stock = any(s["drink"] <= 0 or s["food"] <= 0 for s in stocks)
    dangerous_fraction = 0.0
    dangerous_samples = total_samples = 0
    if store is not None:
        for uid in store.unit_ids():
            for h in store.unit_history(uid):
                t = h.get("tick", 0)
                if not (start_tick <= t <= max(last_tick, end_tick)):
                    continue
                total_samples += 1
                if (h.get("hunger", 0) >= HUNGER_DANGEROUS
                        or h.get("thirst", 0) >= THIRST_DANGEROUS):
                    dangerous_samples += 1
        if total_samples:
            dangerous_fraction = dangerous_samples / total_samples

    # -- growth: population from the diary citizen counts. When a
    # count is absent the change is 0 (unknown, not growth) — a
    # missing count must never read as a population gain.
    pop_start = run.get("citizens_start")
    pop_end = run.get("citizens_end")
    if pop_start is None and pop_end is None:
        pop_start = pop_end = 0
    elif pop_start is None:
        pop_start = pop_end
    elif pop_end is None:
        pop_end = pop_start
    workshops_built = sum(
        1 for a in actions
        if a.get("name") == "build_workshop" and a.get("ok"))
    beds_built = 0
    bed_have = [parse_bed_have(s.get("text", ""))
                for s in (run.get("snapshots") or [])]
    bed_have = [b for b in bed_have if b is not None]
    if bed_have and max(bed_have) >= 1:
        beds_built = 1

    # -- threats: 'threat' / 'hostile_spawn' events in the run window.
    # Counted per distinct creature (unit_id), not per event: the
    # same hostile used to emit both a 'threat' (poll diff) and a
    # 'hostile_spawn' (eventful) event, double-counting one creature
    # (2026-11-27, external review Table 6 row 1). Events without a
    # unit_id cannot be deduped and count individually.
    threats_faced = 0
    if events_path is not None:
        try:
            seen_units: set[Any] = set()
            with open(events_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # A line that parses as valid JSON but is not an
                    # object (e.g. [1, 2]) has no .get — guard it
                    # (2026-11-27, self-review finding): the journal
                    # is harness-written so this is latent, but an
                    # AttributeError here used to kill the whole
                    # scoring run.
                    if not isinstance(ev, dict):
                        continue
                    t = ev.get("tick")
                    if (t is not None and start_tick <= t <= last_tick
                            and ev.get("type") in ("threat",
                                                   "hostile_spawn")):
                        data = ev.get("data")
                        uid = (data.get("unit_id")
                               if isinstance(data, dict) else None)
                        if uid is not None:
                            seen_units.add(uid)
                        else:
                            threats_faced += 1
            threats_faced += len(seen_units)
        except OSError:
            threats_faced = 0

    # -- wealth: the log's wealth records win; the arguments override.
    w_start = wealth_start if wealth_start is not None \
        else run.get("wealth_start")
    w_end = wealth_end if wealth_end is not None else run.get("wealth_end")
    wealth_known = w_start is not None and w_end is not None

    milestones = milestones_from_log(run)
    dimensions = {
        "survival": survival_score(days_lasted, days_planned),
        "lives": lives_score(deaths),
        "wealth": wealth_score(w_start, w_end),
        "needs": needs_score(zero_stock, dangerous_fraction),
        "growth": growth_score(pop_start or 0, pop_end or 0,
                               workshops_built, beds_built),
        "competence": competence_score(
            run.get("idle_ticks", 0) or 0, len(failed),
            repeated_failures(actions),
            run.get("model_failures", 0) or 0, matched, total_sugg),
        "threats": threats_score(hostile_deaths),
    }
    evidence = {
        "days_lasted": round(days_lasted, 2),
        "end_reason": end_reason,
        "deaths": deaths,
        "hostile_deaths": hostile_deaths,
        "threats_faced": threats_faced,
        "wealth_start": w_start,
        "wealth_end": w_end,
        "wealth_known": wealth_known,
        "wealth_growth_pct": (
            round((w_end - w_start) / w_start * 100, 2)
            if wealth_known and w_start else None),
        "zero_stock": zero_stock,
        "dangerous_samples": dangerous_samples,
        "total_samples": total_samples,
        "dangerous_fraction": round(dangerous_fraction, 3),
        "pop_start": pop_start, "pop_end": pop_end,
        "workshops_built": workshops_built,
        "beds_built": beds_built,
        "actions_taken": len(actions),
        "failed_actions": len(failed),
        "repeated_failures": repeated_failures(actions),
        "model_failures": run.get("model_failures", 0) or 0,
        "idle_ticks": run.get("idle_ticks", 0) or 0,
        "suggestions_matched": matched,
        "suggestions_total": total_sugg,
        "drink_start": stocks[0]["drink"] if stocks else None,
        "drink_end": stocks[-1]["drink"] if stocks else None,
        "food_start": stocks[0]["food"] if stocks else None,
        "food_end": stocks[-1]["food"] if stocks else None,
    }
    return Score(
        model=model_name,
        run_log=str(run_log),
        start_save=start_save,
        tick_budget=tick_budget,
        days_planned=days_planned,
        date=run.get("date") or "",
        composite=composite(dimensions, milestones),
        dimensions=dimensions,
        milestones=milestones,
        evidence=evidence,
    )


# -- leaderboard ----------------------------------------------------------

def default_scores_db_path() -> Path:
    """``~/.config/df-agent-harness/scores.db`` (or
    ``$XDG_CONFIG_HOME/df-agent-harness/scores.db``) — the same
    directory the daemon uses as its state dir."""
    import os
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "df-agent-harness" / "scores.db"
    return Path.home() / ".config" / "df-agent-harness" / "scores.db"


class Leaderboard:
    """The scores DB. One row per scored run: model, start save, tick
    budget, date, composite, dimensions, milestones, evidence. A run
    log is scored at most once per model — re-scoring the same log
    replaces its row (the score is a function of the log, not of when
    it was computed)."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path is not None \
            else default_scores_db_path()
        self.conn = sqlite3.connect(str(self.path))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS scores ("
            " model TEXT NOT NULL,"
            " run_log TEXT NOT NULL,"
            " start_save TEXT NOT NULL,"
            " tick_budget INTEGER NOT NULL,"
            " days_planned REAL NOT NULL,"
            " date TEXT NOT NULL,"
            " composite REAL NOT NULL,"
            " dimensions_json TEXT NOT NULL,"
            " milestones_json TEXT NOT NULL,"
            " evidence_json TEXT NOT NULL,"
            " scored_at TEXT NOT NULL,"
            " PRIMARY KEY (model, run_log))")
        self.conn.commit()

    def record(self, score: Score) -> None:
        from datetime import datetime, timezone
        self.conn.execute(
            "INSERT INTO scores (model, run_log, start_save,"
            " tick_budget, days_planned, date, composite,"
            " dimensions_json, milestones_json, evidence_json,"
            " scored_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(model, run_log) DO UPDATE SET"
            " start_save=excluded.start_save,"
            " tick_budget=excluded.tick_budget,"
            " days_planned=excluded.days_planned,"
            " date=excluded.date, composite=excluded.composite,"
            " dimensions_json=excluded.dimensions_json,"
            " milestones_json=excluded.milestones_json,"
            " evidence_json=excluded.evidence_json,"
            " scored_at=excluded.scored_at",
            (score.model, score.run_log, score.start_save,
             score.tick_budget, score.days_planned, score.date,
             score.composite, json.dumps(score.dimensions),
             json.dumps(sorted(score.milestones)),
             json.dumps(score.evidence),
             datetime.now(timezone.utc).isoformat()))
        self.conn.commit()

    def list_scores(self, model: Optional[str] = None
                    ) -> list[dict[str, Any]]:
        q = ("SELECT model, run_log, start_save, tick_budget,"
             " days_planned, date, composite, dimensions_json,"
             " milestones_json, scored_at FROM scores")
        args: tuple = ()
        if model is not None:
            q += " WHERE model=?"
            args = (model,)
        q += " ORDER BY composite DESC, scored_at DESC"
        rows = self.conn.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = dict(zip(
                ("model", "run_log", "start_save", "tick_budget",
                 "days_planned", "date", "composite", "dimensions",
                 "milestones", "scored_at"), r))
            d["dimensions"] = json.loads(d["dimensions"])
            d["milestones"] = json.loads(d["milestones"])
            out.append(d)
        return out

    def close(self) -> None:
        self.conn.close()
