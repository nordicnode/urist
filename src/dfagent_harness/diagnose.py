"""Failure diagnosis (GOAL.md step 5, guidance layer 4).

Every cancelled or failed job comes with its cause AND the fix,
not just the game's raw message. The agent never has to guess what
to do next, and it never repeats a failed action with the same
approach — the fix names a different action.

``diagnose_failure`` matches the failure's action + reason against
known causes and returns a fix in plain words: the corrective
catalog action (by name, with parameters), what it needs, and the
current stock of what it needs (from the state the caller already
has). When the cause is unknown, it returns None — no invented
fix, and the caller records the failure as-is so the loop detector
can still see it.

The digging blocker is a first-class diagnosis: the game will not
create Dig jobs from designations in this fort (verified live
2026-11-26), so the fix for a Dig job that never spawns is to NOT
retry the same designation — it will not work.
"""

from __future__ import annotations

from typing import Any, Optional


def _stocks(state: dict[str, Any]) -> dict[str, Any]:
    return state.get("stocks") or {}


def _n(state: dict[str, Any], key: str) -> Optional[int]:
    val = _stocks(state).get(key)
    return val if isinstance(val, int) else None


def diagnose_failure(action: str, reason: str,
                     error_kind: Optional[str],
                     state: dict[str, Any]) -> Optional[str]:
    """The fix for a failed action, in plain words, or None when
    the cause is not recognised. ``state`` is the observe state the
    caller already has (stocks for the numbers)."""
    reason_l = (reason or "").lower()
    action_l = (action or "").lower()
    wood = _n(state, "wood_units")
    wood_txt = f"Wood: {wood}." if wood is not None else ""
    drink = _n(state, "drink_units")
    food = _n(state, "food_units")

    # Brewing (the fort's most common failure: the drink chain).
    if "brew" in action_l:
        if "barrel" in reason_l:
            return ("Fix: queue make_barrel at the carpenter "
                    "(action queue_job, job make_barrel). "
                    f"Needs 1 wood. {wood_txt}")
        if "plant" in reason_l or "brewable" in reason_l:
            return ("Fix: gather plants (action designate_gather) "
                    "or plant a farm plot and grow plump helmets. "
                    "Brewing needs 1 brewable plant per batch.")
        if "still" in reason_l:
            return ("Fix: build a still (action build, workshop "
                    f"Still). Needs 1 wood. {wood_txt}")
        if "no drink" in reason_l or "drink" in reason_l:
            return ("Fix: brew drink (action brew) — but first "
                    "check the chain: a still, an empty barrel, "
                    "and a brewable plant. "
                    f"Drink: {drink}. {wood_txt}")
    # Digging.
    if "dig" in action_l:
        if "reach" in reason_l or "unreachable" in reason_l:
            return ("Fix: pick a different site — this one has no "
                    "dwarf able to dig it (no floor to stand on, or "
                    "no reachable area). Use digging.derive_dig_site "
                    "for a site on the Surface near the fort centre.")
        if "job" in reason_l and ("spawn" in reason_l
                                  or "did not" in reason_l
                                  or "timeout" in reason_l):
            # Digging works since f0e8617 (the designation sets the
            # map-block flag and the wait covers the job type the
            # mode creates). A job that never spawns now means the
            # site or the miner is wrong, not a game blocker.
            return ("Fix: the designation did not become a job. "
                    "Check the site (a down-stair needs a FLOOR a "
                    "dwarf can stand on; the tile must be reachable) "
                    "and that a dwarf has the MINER labor and a pick, "
                    "then retry with a verified site from "
                    "digging.derive_dig_site.")
        if "shape" in reason_l or "valid shape" in reason_l:
            return ("Fix: a down-stair/channel is dug through a "
                    "FLOOR (the ground surface), a regular dig or "
                    "up-stair into a WALL. Pick a tile of the right "
                    "shape for the mode.")
        if "hazard" in reason_l or "magma" in reason_l \
                or "aquifer" in reason_l or "water" in reason_l:
            return ("Fix: pick a different site — this one would "
                    "hit magma, an aquifer, or water. Check the "
                    "column (/v1/column) before designating.")
    # Building / furniture.
    if "build" in action_l or "make" in action_l or "queue" in action_l:
        if "wood" in reason_l or "material" in reason_l:
            return ("Fix: chop a tree (action chop) for wood, or "
                    f"dig for stone. {wood_txt}")
        if "bed" in reason_l:
            return ("Fix: make a bed at the carpenter (action "
                    f"queue_job, job make_bed). {wood_txt}")
        if "barrel" in reason_l:
            return ("Fix: queue make_barrel at the carpenter "
                    f"(action queue_job, job make_barrel). "
                    f"Needs 1 wood. {wood_txt}")
        if "bucket" in reason_l:
            return ("Fix: queue make_bucket at the carpenter "
                    f"(action queue_job, job make_bucket). "
                    f"Needs 1 wood. {wood_txt}")
    # Gathering / farming.
    if "gather" in action_l or "farm" in action_l:
        if "plant" in reason_l or "no " in reason_l:
            return ("Fix: gather in a different area (the plants "
                    "here are picked out), or plant a farm plot "
                    "(action build, workshop FarmPlot) and grow "
                    "your own.")
    # Cooking.
    if "cook" in action_l:
        if "food" in reason_l or "ingredient" in reason_l:
            return ("Fix: gather plants or butcher an animal for "
                    f"ingredients. Food: {food}.")
    # Chopping.
    if "chop" in action_l:
        if "tree" in reason_l or "no " in reason_l:
            return ("Fix: pick a different area — there is no tree "
                    "here. Use the slice (/v1/slice) to find one.")
    # A timeout / verification failure with no recognised cause:
    # say what to do (re-read state, do not blindly retry).
    if error_kind in ("timeout", "verification"):
        return ("Fix: re-read the state before retrying — the "
                "outcome is unknown, and blindly repeating the "
                "same action can repeat the same failure.")
    return None
