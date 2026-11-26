"""Acceptance criteria evaluation (docs/ACCEPTANCE.md).

Pure functions over plain data — no game, no daemon, no I/O — so
the criteria can be unit-tested against fixture numbers and the
live runner (`scripts/acceptance_run.py`) can reuse them verbatim.

Each check returns ``{"criterion", "result", "evidence"}`` where
``result`` is ``"pass"``, ``"fail"``, ``"inconclusive"`` or
``"untested"``. A death whose cause is unrecorded is never counted
as a thirst/starvation death, but it is always named in the
evidence — an unknown cause is a gap in the record, not a pass.
"""

from __future__ import annotations

from typing import Any, Optional

TICKS_PER_YEAR = 403_200

# Causes that count as "starvation/thirst" for criterion (a).
THIRST_CAUSES = frozenset({"dehydrated", "starved", "thirst", "hunger"})
# Causes the planner could have prevented for criterion (e).
PREVENTABLE_CAUSES = THIRST_CAUSES | frozenset(
    {"wounds", "untreated", "stress"})


def check_survival(tick_start: int, tick_end: int,
                    deaths: list[dict[str, Any]],
                    years_required: float = 2.0) -> dict[str, Any]:
    """(a) Fort survives N game years with zero starvation/thirst deaths."""
    span_years = (tick_end - tick_start) / TICKS_PER_YEAR
    thirst = [d for d in deaths
              if d.get("citizen") and d.get("cause") in THIRST_CAUSES]
    unknown = [d for d in deaths
               if d.get("citizen") and d.get("cause") is None]
    ok = span_years >= years_required and not thirst
    evidence = (f"{span_years:.2f} game-years "
                f"(need {years_required}); {len(thirst)} thirst/starvation "
                f"death(s): "
                + (", ".join(d.get("name", "?") for d in thirst) or "none")
                + (f"; {len(unknown)} citizen death(s) of unrecorded cause: "
                   + ", ".join(d.get("name", "?") for d in unknown)
                   if unknown else ""))
    return {"criterion": "a", "result": "pass" if ok else "fail",
            "evidence": evidence}


def check_stocks(snapshots: list[dict[str, Any]],
                 drink_critical: int = 5,
                 food_critical: int = 5) -> dict[str, Any]:
    """(b) Drink/food stay above the survival thresholds at every snapshot."""
    below = [s for s in snapshots
             if s.get("drink", 0) <= drink_critical
             or s.get("food", 0) <= food_critical]
    ok = bool(snapshots) and not below
    result = "pass" if ok else ("untested" if not snapshots else "fail")
    evidence = (f"{len(snapshots)} snapshot(s); "
                f"{len(below)} below threshold "
                f"(drink<={drink_critical} or food<={food_critical})")
    if below:
        first = below[0]
        evidence += (f"; first breach at tick {first.get('tick')}: "
                     f"drink {first.get('drink')}u, "
                     f"food {first.get('food')}u")
    return {"criterion": "b", "result": result, "evidence": evidence}


def check_threat_response(spawn_tick: Optional[int],
                          decision_tick: Optional[int],
                          max_ticks: int = 1100) -> dict[str, Any]:
    """(c) Planner responds to a hostile spawn within ``max_ticks``.

    ``max_ticks`` defaults to ~1 planner tick (30 s wall × ~37 t/s).
    Either tick None means no spawn was observed in the window.
    """
    if spawn_tick is None:
        return {"criterion": "c", "result": "untested",
                "evidence": "no new hostile spawn observed in the window"}
    if decision_tick is None:
        return {"criterion": "c", "result": "fail",
                "evidence": f"hostile spawned at tick {spawn_tick}; "
                            "no threat decision followed"}
    delta = decision_tick - spawn_tick
    ok = 0 <= delta <= max_ticks
    return {"criterion": "c", "result": "pass" if ok else "fail",
            "evidence": f"hostile at tick {spawn_tick}; threat decision "
                        f"at tick {decision_tick} ({delta} ticks later; "
                        f"limit {max_ticks})"}


def check_expansion(before: dict[str, Any],
                    after: dict[str, Any]) -> dict[str, Any]:
    """(d) Buildings grow, population does not shrink, production > 0."""
    b_grew = after.get("buildings", 0) > before.get("buildings", 0)
    c_shrank = after.get("citizens", 0) < before.get("citizens", 0)
    produced = after.get("produced", 0)
    ok = b_grew and not c_shrank and produced > 0
    evidence = (f"buildings {before.get('buildings')} -> "
                f"{after.get('buildings')}; citizens "
                f"{before.get('citizens')} -> {after.get('citizens')}; "
                f"drink/food produced {produced}u")
    return {"criterion": "d", "result": "pass" if ok else "fail",
            "evidence": evidence}


def check_no_neglect_deaths(deaths: list[dict[str, Any]],
                            daemon_continuous: bool) -> dict[str, Any]:
    """(e) No dwarf dies of neglect the planner could have prevented."""
    if not daemon_continuous:
        return {"criterion": "e", "result": "inconclusive",
                "evidence": "daemon did not run continuously through "
                            "the window — deaths cannot be attributed "
                            "to the planner either way"}
    neglect = [d for d in deaths
               if d.get("citizen") and d.get("cause") in PREVENTABLE_CAUSES]
    ok = not neglect
    evidence = (f"{len(neglect)} preventable death(s): "
                + (", ".join(f"{d.get('name', '?')} "
                             f"({d.get('cause')})" for d in neglect)
                   or "none"))
    return {"criterion": "e", "result": "pass" if ok else "fail",
            "evidence": evidence}


def evaluate_all(results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Order the per-criterion results (a)–(e) for the report table."""
    return [results[k] for k in ("a", "b", "c", "d", "e") if k in results]
