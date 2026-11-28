"""Evaluation framework (docs/EVALUATION.md): benchmark manifests, score
v2, suite statistics, scenario registry, leaderboard publication.

Score v1 lives in scoring.py and is unchanged. This module is the
benchmark layer on top of it: it records WHAT a run was (manifest),
scores it under the expanded v2 weights, aggregates repeated runs
into suite statistics, and publishes the leaderboard.

Honesty rules, enforced here, not just documented:
- A dimension with no evidence reports None ("not measured"), never 0.
- A v2 composite is published only when every v2 dimension is
  measured; until then v1 remains the headline.
- A manifest field the log does not record is None, listed in
  ``gaps`` — never inferred from the current repo state (the current
  git commit is NOT the run's commit).
- The two verified 1-day runs (91.8 / 91.7) are smoke-tier, never
  benchmark results.
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from dfagent_harness.scoring import (
    classify_action_failure, classify_model_failure,
    compute_score, failure_taxonomy, milestone_bonus,
    model_calls_attempted, run_summary)

# -- protocol version -----------------------------------------------------
# The agent protocol version: the model prompt plus the snapshot
# schema. Bump it whenever either changes; the leaderboard keys on
# it so a cross-version comparison cannot happen silently. The
# snapshot schema itself is SCHEMA_VERSION in observe.py (currently
# 1); the protocol version covers the whole model-facing contract.
PROTOCOL_VERSION = 1

MANIFEST_VERSION = 1

# -- failure taxonomy -----------------------------------------------------
# Classifiers live in scoring.py (run_summary uses them too);
# re-exported here so existing imports keep working.
__all__ = ["classify_model_failure", "classify_action_failure",
           "failure_taxonomy"]


# -- run validity ---------------------------------------------------------
# A run is valid if it reached its planned duration or the fort died
# by game causes. A fort death is a result, not a discard. A run is
# DISCARDED only for infrastructure (VM reboot, daemon crash, DF
# crash not caused by game events, harness bug, provider outage
# that aborts the run). The log alone cannot always tell infra from
# game: those runs are "unclassified" and flagged for human review,
# never silently counted or silently discarded.

def validity_verdict(run: dict[str, Any]) -> tuple[str, str]:
    """(verdict, reason) for one parsed run log. Verdicts: valid |
    discarded | unclassified."""
    run_end = run.get("run_end") or {}
    reason = str(run_end.get("reason", "") or "")
    if not reason:
        return ("unclassified",
                "no run_end record: the run aborted without a verdict")
    low = reason.lower()
    if low in ("day complete", "season complete", "year complete",
               "run complete"):
        return ("valid", "reached planned duration")
    if any(k in low for k in ("fort died", "fort lost", "all dwarves",
                              "died of thirst", "tantrum spiral",
                              "overrun", "destroyed")):
        return ("valid", "fort died by game causes: " + reason)
    if any(k in low for k in ("vm reboot", "daemon crash", "df crash",
                              "harness bug", "provider outage",
                              "infrastructure")):
        return ("discarded", "infrastructure failure: " + reason)
    return ("unclassified",
            "run_end reason does not settle valid vs discarded: "
            + reason)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _wall_clock_s(records: list[dict[str, Any]]) -> Optional[float]:
    """Wall-clock seconds from the first to the last log timestamp.
    None when the log carries no usable timestamps."""
    stamps = [_parse_ts(r.get("ts")) for r in records]
    stamps = [s for s in stamps if s is not None]
    if len(stamps) < 2:
        return None
    return (stamps[-1] - stamps[0]).total_seconds()


# -- manifest -------------------------------------------------------------

# Model call parameters verified from the Free Pi client source
# (freepi.py, read 2026-11-27): body is {"model", "messages",
# "temperature": 0.2}. No max_tokens, no other parameters.
FREEPI_MODEL_PARAMS = {"temperature": 0.2}
FREEPI_MODEL_IDS = ("deepseek-v4.1-flash", "deepseek-v4-flash",
                    "particle")
# Resolved model ids, verified live via chat completions 2026-11-26
# (the response 'model' field is authoritative).
FREEPI_RESOLVED_IDS = {
    "deepseek-v4.1-flash": "deepseek-v4.1-flash-1017",
    "deepseek-v4-flash": "deepseek-v4-flash-0731",
}


def build_manifest(run_log: str | Path,
                   store: Any = None,
                   events_path: str | Path | None = None,
                   wealth_start: Optional[float] = None,
                   wealth_end: Optional[float] = None,
                   model: Optional[str] = None,
                   start_save: str = "region2-00125-04-01-clean",
                   scenario_id: Optional[str] = None,
                   tier: Optional[str] = None,
                   repeat: Optional[int] = None,
                   harness_commit: Optional[str] = None,
                   cost_usd: Optional[float] = None,
                   ) -> dict[str, Any]:
    """Build the run manifest for one run log (EVALUATION.md Phase 1).

    The manifest is the reproducibility record: given the log and the
    manifest, anyone can recompute the score and see exactly what
    the model was given. Fields the log does not record are None,
    listed in ``gaps`` — never invented. The current git commit is
    NOT the run's commit: ``harness_commit`` stays None unless the
    caller passes it with evidence (e.g. the driver logged it).
    """
    from dfagent_harness.scoring import parse_run_log
    run = parse_run_log(run_log)
    records = run.get("records") or []
    gaps: list[str] = []

    run_start = next((r for r in records if r.get("kind") == "run_start"),
                     {})
    model_id = model or run.get("model") or "unknown"
    provider = ("free-pi" if model_id in FREEPI_MODEL_IDS
                else "unknown")
    if provider == "unknown":
        gaps.append("provider (model id not a known Free Pi id)")

    # Token counts: only from explicit model_call records (the
    # format the driver will emit once Phase 1 lands in it). The
    # Free Pi client discards the response usage field today, and
    # the log records no prompt text, so legacy logs have no token
    # data at all — None, not an estimate.
    tokens_in = tokens_out = None
    latency_s = None
    call_records = [r for r in records if r.get("kind") == "model_call"]
    if call_records:
        tokens_in = sum(int(r.get("prompt_tokens", 0) or 0)
                        for r in call_records)
        tokens_out = sum(int(r.get("completion_tokens", 0) or 0)
                         for r in call_records)
        latency_s = sum(float(r.get("latency_s", 0) or 0)
                        for r in call_records)
    else:
        gaps.append("tokens_in / tokens_out (no model_call records; "
                    "the Free Pi client discards the usage field)")

    protocol_version = run_start.get("protocol_version")
    if protocol_version is None:
        gaps.append("protocol_version (not recorded in the log)")
    run_harness_commit = (harness_commit
                          or run_start.get("harness_commit"))
    if run_harness_commit is None:
        gaps.append("harness_commit (not recorded in the log; the "
                    "current git commit is not the run's commit)")

    # Model call attempts: one per decision tick (one snapshot per
    # tick, except the final snapshot the run ends on before calling
    # the model) plus in-tick retries (scoring.model_calls_attempted).
    attempts = model_calls_attempted(run)

    wall_s = _wall_clock_s(records)
    if wall_s is None:
        gaps.append("wall_clock_s (no usable log timestamps)")

    days_planned = float(run.get("days_planned") or 1.0)
    # The run-end summary (scoring.run_summary) computes the v1
    # score from the same inputs and carries it in summary["score"],
    # so the score is computed once here, not twice.
    summary = run_summary(run_log, store=store,
                          events_path=events_path,
                          wealth_start=wealth_start,
                          wealth_end=wealth_end, model=model,
                          start_save=start_save)
    score_v1 = summary["score"]
    score_v2 = compute_score_v2(run_log, store=store,
                                events_path=events_path,
                                wealth_start=wealth_start,
                                wealth_end=wealth_end, model=model,
                                start_save=start_save)

    verdict, verdict_reason = validity_verdict(run)
    taxonomy = failure_taxonomy(run)

    if cost_usd is None:
        cost_usd = 0.0 if provider == "free-pi" else None
        if cost_usd is None:
            gaps.append("cost_usd (provider unknown)")

    model_params = (dict(FREEPI_MODEL_PARAMS)
                    if provider == "free-pi" else None)
    if model_params is None:
        gaps.append("model_params (provider unknown)")

    efficiency: dict[str, Any] = {
        "model_calls_attempted": attempts,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "model_latency_s_total": latency_s,
        "wall_clock_s": wall_s,
        "wall_clock_s_per_day": (wall_s / days_planned
                                 if wall_s is not None else None),
        "tokens_per_day": (
            (tokens_in + tokens_out) / days_planned
            if tokens_in is not None and tokens_out is not None
            else None),
        "calls_per_day": attempts / days_planned if attempts else None,
        "cost_usd": cost_usd,
        "cost_usd_per_day": (cost_usd / days_planned
                             if cost_usd is not None else None),
        "score_per_token": (
            score_v1["composite"] / (tokens_in + tokens_out)
            if tokens_in is not None and tokens_out is not None
            and (tokens_in + tokens_out) > 0 else None),
        "score_per_dollar": (
            score_v1["composite"] / cost_usd
            if cost_usd not in (None, 0) else None),
    }

    return {
        "manifest_version": MANIFEST_VERSION,
        "run_log": str(run_log),
        "model": model_id,
        "model_resolved": FREEPI_RESOLVED_IDS.get(model_id),
        "provider": provider,
        "endpoint_route": ("free-pi /v1/chat/completions"
                           if provider == "free-pi" else None),
        "harness_commit": run_harness_commit,
        "protocol_version": protocol_version,
        "snapshot_schema_version": 1,
        "scenario_id": scenario_id,
        "tier": tier,
        "repeat": repeat,
        "start_save": start_save,
        "days_planned": days_planned,
        "window": run.get("window"),
        "tick_budget": score_v1["tick_budget"],
        "start_tick": run.get("start_tick"),
        "end_tick": run.get("end_tick"),
        "date": score_v1["date"],
        "model_params": model_params,
        "validity": verdict,
        "validity_reason": verdict_reason,
        "failure_taxonomy": taxonomy,
        "efficiency": efficiency,
        "score_v1": score_v1,
        "score_v2": score_v2,
        "run_summary": summary,
        "gaps": gaps,
    }


def write_manifest(run_log: str | Path,
                   path: str | Path | None = None,
                   **kwargs: Any) -> Path:
    """Build a manifest for ``run_log`` and write it as JSON next to
    the log (``<log>.manifest.json`` by default). Returns the path."""
    manifest = build_manifest(run_log, **kwargs)
    out = (Path(path) if path is not None
           else Path(str(run_log) + ".manifest.json"))
    out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out


def load_manifest(path: str | Path) -> dict[str, Any]:
    """Load a manifest written by write_manifest."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


# -- score v2 ---------------------------------------------------------------
# The expanded composite (EVALUATION.md). The v1 dimensions and
# definitions do not change. v2 adds economy, defense, diplomacy,
# and expansion, and re-weights explicitly. Both composites are
# reported side by side during the transition; the leaderboard
# carries both until v2 has a full suite of its own.

WEIGHTS_V2: dict[str, float] = {
    "survival": 25.0,
    "lives": 25.0,
    "wealth": 8.0,
    "needs": 8.0,
    "growth": 5.0,
    "competence": 8.0,
    "threats": 5.0,
    "economy": 5.0,
    "defense": 5.0,
    "diplomacy": 3.0,
    "expansion": 3.0,
}
# Weights sum to 100 before the milestone bonus (checked in tests).

# The eight systems the expansion dimension counts (EVALUATION.md):
# farming, cooking, crafts, metalworking, rooms, zones, animals,
# engraving. Each counts once, on first verified use (an ok action).
_EXPANSION_SYSTEMS = ("farming", "cooking", "crafts", "metalworking",
                      "rooms", "zones", "animals", "engraving")
_EXPANSION_TOTAL = len(_EXPANSION_SYSTEMS)


def _expansion_systems_used(actions: list[dict[str, Any]]) -> set[str]:
    """Which of the eight expansion systems the run actually used,
    from ok actions in the log. Conservative: only actions the
    harness executed (ok=true) count; a queued job that never ran
    does not."""
    from dfagent_harness.scoring import action_job
    used: set[str] = set()
    for a in actions:
        if not a.get("ok", True):
            continue
        name = (a.get("name") or "").lower()
        params = a.get("params") or {}
        job = action_job(a) or ""
        task = str(params.get("name", "") or params.get("task", "")
                   ).lower()
        if (name == "build_farm_plot" or job in ("plant", "harvest",
            "plant_seeds", "sow") or "farm" in task):
            used.add("farming")
        if job in ("cook", "prepare_meal", "preparemeal") \
                or "cook" in task:
            used.add("cooking")
        if job.startswith("make_"):
            used.add("crafts")
        kind = str(params.get("kind", "")).lower()
        if kind in ("forge", "smelter", "metalsmiths_forge",
                    "magma_forge", "magma_smelter", "kiln") \
                or job in ("smelt", "forge", "make_weapon",
                           "make_armor"):
            used.add("metalworking")
        if name == "build_furniture":
            used.add("rooms")
        if name == "create_zone":
            used.add("zones")
            zone = str(params.get("zone", "") or "").lower()
            if zone in ("pasture", "pen"):
                used.add("animals")
        if job in ("tame", "pasture", "pen") \
                or "animal" in task or "pasture" in task:
            used.add("animals")
        if job in ("engrave", "smooth", "carve"):
            used.add("engraving")
    return used


def expansion_score(actions: list[dict[str, Any]]
                    ) -> tuple[float, set[str]]:
    """Expansion dimension (0-100): 100 * systems used / 8. Returns
    (score, systems used)."""
    used = _expansion_systems_used(actions)
    return 100.0 * len(used) / _EXPANSION_TOTAL, used


# Economy, defense, and diplomacy are gated on systems that do not
# exist yet in the harness (trade, military, liaison meetings). Each
# returns None ("not measured") with its reason — never 0. Until
# all four new dimensions land, v2 is not published and v1 remains
# the headline.
_V2_GATED_REASONS = {
    "economy": ("gated on the trade system and on job-completion "
                "value tracking (produced-goods value, trade "
                "profit, self-sufficiency)"),
    "defense": ("gated on the military system (invasion/siege "
                "response, fortifications, squads)"),
    "diplomacy": ("gated on the trade system and on liaison-meeting "
                  "handling (meetings held, agreements secured)"),
}


def economy_score() -> tuple[None, str]:
    """Not measured yet; see _V2_GATED_REASONS."""
    return None, _V2_GATED_REASONS["economy"]


def defense_score() -> tuple[None, str]:
    """Not measured yet; see _V2_GATED_REASONS."""
    return None, _V2_GATED_REASONS["defense"]


def diplomacy_score() -> tuple[None, str]:
    """Not measured yet; see _V2_GATED_REASONS."""
    return None, _V2_GATED_REASONS["diplomacy"]


def composite_v2(dimensions: dict[str, Optional[float]],
                 milestones: set[str]) -> Optional[float]:
    """Expanded composite. Returns None when any v2 dimension is
    not measured — a partial v2 is not a score, and v1 stays the
    headline until every dimension lands."""
    if any(dimensions.get(k) is None for k in WEIGHTS_V2):
        return None
    total = sum(WEIGHTS_V2[k] * dimensions[k]
                for k in WEIGHTS_V2) / 100.0
    return max(0.0, min(100.0, total + milestone_bonus(milestones)))


# v2 milestone detectors. The four new milestones are defined the
# same conservative way as the v1 ones: positive evidence only,
# never a queue, never a claim before the system exists.
V2_MILESTONES_EXTRA = ("first siege survived", "first caravan traded",
                       "first migrant wave housed", "first artifact")


def milestones_v2_from_log(run: dict[str, Any],
                           events_path: str | Path | None = None
                           ) -> tuple[set[str], dict[str, str]]:
    """Detect the four new v2 milestones from the run log (plus the
    daemon events journal where a detector needs it). Returns
    (achieved, reasons) where reasons records, for every new
    milestone, why it did or did not count — so a False is
    auditable, not silent."""
    from dfagent_harness.scoring import parse_bed_have
    achieved: set[str] = set()
    reasons: dict[str, str] = {}
    snapshots = run.get("snapshots") or []
    days_planned = float(run.get("days_planned") or 1.0)
    start_tick = run.get("start_tick") or 0
    run_end = run.get("run_end") or {}
    last_tick = run_end.get("tick") or run.get("end_tick") or start_tick
    days_lasted = max(0.0, (last_tick - start_tick) / 1200)

    # First siege survived: a hostile_spawn / siege / invasion event
    # in the run window, the fort lasted its planned duration, and
    # no dwarf died in combat. A 'threat' poll-diff alone does not
    # count — it can be a cavern demon 175 levels down.
    siege_seen = False
    if events_path is not None:
        try:
            with open(events_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(ev, dict):
                        continue
                    t = ev.get("tick")
                    if (t is not None and start_tick <= t <= last_tick
                            and ev.get("type") in ("hostile_spawn",
                                                   "siege",
                                                   "invasion")):
                        siege_seen = True
                        break
        except OSError:
            siege_seen = False
    if siege_seen and days_lasted >= days_planned:
        achieved.add("first siege survived")
        reasons["first siege survived"] = (
            "hostile_spawn/siege event in window, fort lasted its "
            "planned duration")
    elif siege_seen:
        reasons["first siege survived"] = (
            "hostile seen but the fort did not last its planned "
            "duration")
    else:
        reasons["first siege survived"] = (
            "no hostile_spawn/siege/invasion event in the run "
            "window (or no events journal supplied)")

    # First caravan traded / first artifact: no trade or artifact
    # event exists in the harness yet — always False, documented.
    reasons["first caravan traded"] = (
        "not detectable: no trade event exists in the harness yet")
    reasons["first artifact"] = (
        "not detectable: no artifact event exists in the harness "
        "yet")

    # First migrant wave housed: population rose across the run AND
    # a bed item was available to place (the wave has somewhere to
    # sleep). Conservative: a rise with no bed is arrival, not
    # housing.
    pop_start = run.get("citizens_start")
    pop_end = run.get("citizens_end")
    bed_have = [parse_bed_have(s.get("text", "")) for s in snapshots]
    bed_have = [b for b in bed_have if b is not None]
    if (pop_start is not None and pop_end is not None
            and pop_end > pop_start and bed_have
            and max(bed_have) >= 1):
        achieved.add("first migrant wave housed")
        reasons["first migrant wave housed"] = (
            f"population {pop_start} -> {pop_end} with a bed item "
            "available")
    else:
        reasons["first migrant wave housed"] = (
            "no population rise with a bed item available")

    return achieved, reasons


def compute_score_v2(run_log: str | Path,
                     store: Any = None,
                     events_path: str | Path | None = None,
                     wealth_start: Optional[float] = None,
                     wealth_end: Optional[float] = None,
                     model: Optional[str] = None,
                     start_save: str = "region2-00125-04-01-clean",
                     ) -> dict[str, Any]:
    """Score one run under v2 (EVALUATION.md Phase 4).

    Returns a dict with the v1 composite alongside, the v2
    dimensions (None where not measured), the v2 composite (None
    until every v2 dimension is measured), the v2 milestones, and
    the evidence. The v1 score is computed by scoring.compute_score
    and is not recomputed here."""
    from dfagent_harness.scoring import (
        milestones_from_log, parse_run_log)
    v1 = compute_score(run_log, store=store,
                       events_path=events_path,
                       wealth_start=wealth_start,
                       wealth_end=wealth_end, model=model,
                       start_save=start_save)
    run = parse_run_log(run_log)
    actions = run.get("actions") or []
    exp_value, exp_used = expansion_score(actions)
    econ_value, econ_reason = economy_score()
    def_value, def_reason = defense_score()
    dip_value, dip_reason = diplomacy_score()
    new_milestones, milestone_reasons = milestones_v2_from_log(
        run, events_path=events_path)
    v1_milestones = milestones_from_log(run)
    all_milestones = set(v1_milestones) | new_milestones
    dimensions_v2: dict[str, Optional[float]] = dict(v1.dimensions)
    dimensions_v2.update({
        "economy": econ_value,
        "defense": def_value,
        "diplomacy": dip_value,
        "expansion": exp_value,
    })
    v2 = composite_v2(dimensions_v2, all_milestones)
    return {
        "composite_v1": round(v1.composite, 1),
        "composite_v2": (round(v2, 1) if v2 is not None else None),
        "v2_published": v2 is not None,
        "v2_status": ("complete" if v2 is not None
                      else "partial: economy, defense, diplomacy "
                      "not measured — v1 remains the headline"),
        "dimensions_v2": {
            k: (round(v, 1) if v is not None else None)
            for k, v in dimensions_v2.items()},
        "dimensions_v1": {k: round(v, 1)
                          for k, v in v1.dimensions.items()},
        "milestones_v1": sorted(v1_milestones),
        "milestones_v2_extra": sorted(new_milestones),
        "milestones_all": sorted(all_milestones),
        "milestone_bonus_v2": round(milestone_bonus(all_milestones),
                                    1),
        "milestone_reasons": milestone_reasons,
        "expansion_systems_used": sorted(exp_used),
        "expansion_systems_missing": sorted(
            set(_EXPANSION_SYSTEMS) - exp_used),
        "gated_reasons": {
            "economy": econ_reason,
            "defense": def_reason,
            "diplomacy": dip_reason,
        },
        # Craft share of wealth growth (anti-gaming evidence). The
        # current log carries no item-level value tracking, so this
        # is None — not measurable — and the dkta-style cap below is
        # PROPOSED, not adopted: it is not used by any composite.
        "craft_share_of_wealth_growth": None,
        "craft_share_note": (
            "not measurable from the current run log (no "
            "item-level value tracking); cap is proposed, not "
            "adopted"),
    }


def craft_share_cap(wealth_growth: float, craft_value: float,
                    built_value: float) -> float:
    """PROPOSED anti-gaming cap (dkta-style, EVALUATION.md): the
    craft contribution to wealth growth is capped at the value of
    what the fort actually built. Capped growth = non-craft growth
    + min(craft value, built value). Not adopted — validate the cap
    against live data before it is used by any score. Pure function
    so the cap itself is testable on synthetic numbers."""
    if wealth_growth <= 0 or built_value <= 0:
        return wealth_growth
    return (wealth_growth - craft_value) + min(craft_value,
                                               built_value)


# -- suite statistics -------------------------------------------------------
# The headline number is the MEDIAN composite across the suite, with
# the interquartile range, min/max, and survival rate (EVALUATION.md:
# dkta ran 12 and still refused to rank, because pairs split 3-3 or
# 4-2). When the IQRs of two models overlap, no ordering is
# established — the leaderboard says so, it does not rank on noise.

def median(xs: list[float]) -> Optional[float]:
    """Median, or None for an empty list."""
    if not xs:
        return None
    return float(statistics.median(xs))


def quartiles(xs: list[float]) -> tuple[Optional[float],
                                        Optional[float],
                                        Optional[float]]:
    """(Q1, median, Q3) via statistics.quantiles (exclusive method).
    All None for an empty list."""
    if not xs:
        return None, None, None
    if len(xs) == 1:
        return xs[0], xs[0], xs[0]
    qs = statistics.quantiles(xs, n=4, method="exclusive")
    return float(qs[0]), float(statistics.median(xs)), float(qs[2])


def suite_stats(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate suite statistics for a list of run entries, each
    with at least ``composite`` (float) and ``survived`` (bool), and
    optionally ``scenario_id``. Returns median, IQR, min/max,
    survival rate, per-scenario medians, and the reliability
    numbers (tau-bench spirit: survival of ALL repeats per
    scenario)."""
    composites = [float(e["composite"]) for e in entries
                  if e.get("composite") is not None]
    n = len(composites)
    q1, med, q3 = quartiles(composites)
    survived = sum(1 for e in entries if e.get("survived"))
    total = len(entries)
    per_scenario: dict[str, dict[str, Any]] = {}
    for e in entries:
        sid = str(e.get("scenario_id", "unknown"))
        per_scenario.setdefault(sid, []).append(e)
    per_scenario_stats = {}
    for sid, group in sorted(per_scenario.items()):
        vals = [float(e["composite"]) for e in group
                if e.get("composite") is not None]
        gq1, gmed, gq3 = quartiles(vals)
        per_scenario_stats[sid] = {
            "n": len(group),
            "median": gmed,
            "q1": gq1,
            "q3": gq3,
            "survival_rate": (sum(1 for e in group if e.get("survived"))
                              / len(group) if group else None),
        }
    # Reliability: fraction of scenario groups (with >= 2 repeats)
    # in which EVERY repeat survived.
    multi = [g for g in per_scenario.values() if len(g) >= 2]
    both_survived = (sum(1 for g in multi
                         if all(e.get("survived") for e in g))
                     / len(multi)) if multi else None
    return {
        "n": n,
        "median": med,
        "q1": q1,
        "q3": q3,
        "iqr": (q3 - q1) if (q1 is not None and q3 is not None)
        else None,
        "min": min(composites) if composites else None,
        "max": max(composites) if composites else None,
        "survival_rate": (survived / total) if total else None,
        "both_repeats_survived_rate": both_survived,
        "per_scenario": per_scenario_stats,
    }


def ordering_verdict(stats_a: dict[str, Any],
                     stats_b: dict[str, Any]) -> str:
    """Whether two models' suite stats establish an ordering. When
    the interquartile ranges overlap, no ordering is established —
    the leaderboard says so instead of ranking on noise."""
    a_q1, a_q3 = stats_a.get("q1"), stats_a.get("q3")
    b_q1, b_q3 = stats_b.get("q1"), stats_b.get("q3")
    if None in (a_q1, a_q3, b_q1, b_q3):
        return "no ordering established (too few runs to compute IQRs)"
    overlap = not (a_q3 < b_q1 or b_q3 < a_q1)
    if overlap:
        return "no ordering established (interquartile ranges overlap)"
    if stats_a["median"] is not None and stats_b["median"] is not None:
        higher = "A" if stats_a["median"] > stats_b["median"] else "B"
        return (f"ordering established: {higher} higher "
                "(IQRs do not overlap)")
    return "no ordering established"


# -- scenario registry ------------------------------------------------------

def default_scenarios_path() -> Path:
    """``<repo>/scenarios/scenarios.json``."""
    return (Path(__file__).resolve().parent.parent.parent
            / "scenarios" / "scenarios.json")


def load_scenarios(path: str | Path | None = None) -> dict[str, Any]:
    """Load and validate the scenario registry. Raises ValueError on
    a malformed registry (duplicate ids, missing anchor, no held-out
    scenario, non-integer seeds)."""
    p = Path(path) if path is not None else default_scenarios_path()
    registry = json.loads(p.read_text(encoding="utf-8"))
    scenarios = registry.get("scenarios", [])
    if not scenarios:
        raise ValueError("scenario registry has no scenarios")
    ids = [s.get("id") for s in scenarios]
    if len(ids) != len(set(ids)):
        raise ValueError("scenario registry has duplicate ids")
    if "S0" not in ids:
        raise ValueError("scenario registry has no S0 anchor")
    held_out = [s for s in scenarios if s.get("held_out")]
    if len(held_out) != 1:
        raise ValueError("scenario registry must hold out exactly one "
                         "scenario (found %d)" % len(held_out))
    for s in scenarios:
        seed = s.get("world_seed")
        if s.get("kind") == "seeded-embark" and not isinstance(seed,
                                                               int):
            raise ValueError(
                f"scenario {s.get('id')}: seeded embark needs an "
                "integer world_seed")
    return registry


def current_harness_commit() -> Optional[str]:
    """The git commit of the repo right now (the harness that is
    scoring, not necessarily the harness that ran). Used for the
    eval row's harness_version; the run's own commit comes only
    from the log's run_start record and is never inferred from
    this."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "-C",
             str(Path(__file__).resolve().parent.parent.parent),
             "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or None
    except (subprocess.SubprocessError, OSError):
        return None


def anchor_verified(registry: dict[str, Any]) -> bool:
    """True when the S0 anchor save exists in saves-clean/."""
    anchor = next((s for s in registry.get("scenarios", [])
                   if s.get("id") == "S0"), None)
    if anchor is None:
        return False
    save = anchor.get("save")
    if not save:
        return False
    return (Path(__file__).resolve().parent.parent.parent
            / "saves-clean" / save).is_dir()


# -- leaderboard publication ------------------------------------------------

def render_leaderboard_md(eval_rows: list[dict[str, Any]],
                          v1_rows: list[dict[str, Any]] | None = None
                          ) -> str:
    """Render docs/LEADERBOARD.md from eval_runs rows (and, when
    given, the v1 scores table). Generated, never hand-edited: the
    table reproduces from scores.db. A run without a manifest is
    not a benchmark result and is not listed as one."""
    lines = ["# Leaderboard",
             "",
             "Generated from scores.db (`eval_runs`). No hand editing: "
             "regenerate with `scripts/eval_run.py leaderboard`.",
             "",
             "## Benchmark headline (two-year suite, median v2)",
             "",
             "The headline is the median v2 composite across the full "
             "two-year suite (6 scenarios x 2 repeats = 12 runs), "
             "with the interquartile range and the survival rate next "
             "to it. When the interquartile ranges of two models "
             "overlap, no ordering is established.",
             ""]
    if not eval_rows:
        lines += [
            "No benchmark suite has completed yet. The two verified "
            "1-day runs (DeepSeek V4.1 Flash, 91.8 and 91.7) are "
            "smoke-tier, not benchmark results, and are listed "
            "below under v1 smoke runs — not as a headline.",
            ""]
    else:
        by_model: dict[str, list[dict[str, Any]]] = {}
        for r in eval_rows:
            by_model.setdefault(r["model"], []).append(r)
        lines += ["| model | median v2 | IQR | survival | "
                  "score/token | score/$ | harness | protocol |",
                  "|---|---|---|---|---|---|---|---|",
                  ]
        for model, rows in sorted(by_model.items()):
            vals = [r["composite_v2"] for r in rows
                    if r.get("composite_v2") is not None]
            q1, med, q3 = quartiles(vals) if vals else (None, None,
                                                        None)
            surv = (sum(1 for r in rows if r.get("survival"))
                    / len(rows)) if rows else None
            toks = sum((r.get("tokens_in") or 0)
                       + (r.get("tokens_out") or 0) for r in rows)
            cost = sum(r.get("cost_usd") or 0 for r in rows)
            med_s = f"{med:.1f}" if med is not None else "n/a"
            iqr_s = (f"{q1:.1f}-{q3:.1f}"
                     if q1 is not None and q3 is not None else "n/a")
            surv_s = f"{surv:.0%}" if surv is not None else "n/a"
            spt = (f"{sum(vals) / toks:.4f}" if toks and vals
                   else "n/a")
            spd = (f"{sum(vals) / cost:.1f}" if cost and vals
                   else "n/a")
            harness = rows[0].get("harness_version") or "n/a"
            proto = rows[0].get("protocol_version")
            proto_s = str(proto) if proto is not None else "n/a"
            lines.append(
                f"| {model} | {med_s} | {iqr_s} | {surv_s} | {spt} | "
                f"{spd} | {harness} | {proto_s} |")
        lines += ["",
                  "Every row links to a run manifest. No run is "
                  "listed without its manifest.",
                  ""]
        for r in eval_rows:
            manifest = r.get("manifest_path") or "(no manifest)"
            lines.append(
                f"- {r['model']} / {r.get('scenario_id')} / repeat "
                f"{r.get('repeat')} / {r.get('tier')}: v1 "
                f"{r.get('composite_v1')}, v2 "
                f"{r.get('composite_v2')}, manifest: {manifest}")
        lines.append("")
    if v1_rows:
        lines += ["## v1 smoke runs (not benchmark results)",
                  "",
                  "| model | composite | date | run |",
                  "|---|---|---|---|"]
        for r in v1_rows:
            lines.append(
                f"| {r['model']} | {r['composite']:.1f} | "
                f"{r['date']} | {Path(r['run_log']).name} |")
        lines.append("")
    return "\n".join(lines)
