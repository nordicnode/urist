"""The self-describing action catalog (GOAL.md step 5, layer 1).

A fresh model with no DF knowledge, given only the harness protocol,
must be able to discover what it can do — the catalog is the map.
It is built by introspection from the real action functions
(``actions.ACTIONS``), so it cannot drift from the implementation:
parameter names, types, defaults and the docstring's first line come
from the code itself. A small hand-written NOTES table adds the
constraints that are not in the signature (legal values for an enum
parameter, a known blocker, an example call).

``catalog()`` returns the whole catalog (for GET /v1/catalog);
``describe(name)`` returns one action (for GET /v1/catalog/<name>).
Unknown names return None (the route answers 404 with the legal
names, so a typo is a recoverable error, not a dead end).
"""

from __future__ import annotations

import inspect
from typing import Any

from .actions import ACTIONS, JOB_SPECS

__all__ = ["catalog", "describe", "NOTES"]

# Constraints and examples that are not in the function signature.
# Legal values are the real ones (from the runtime enums / JOB_SPECS),
# not guesses — a wrong value is a precondition failure, so the catalog
# must name the right ones.
NOTES: dict[str, dict[str, Any]] = {
    "designate_dig": {
        "params": {
            "box": "A rectangle (x1, y1, z1, x2, y2, z2). The z is a "
                   "single level; use one level per call.",
            "mode": "dig (into a wall), down-stair (through a floor), "
                    "up-stair (into a ceiling), channel (through a "
                    "floor, open above), up-down-stair, ramp, or "
                    "clear (remove designations).",
        },
        "constraints": [
            "A down-stair or channel is dug through a FLOOR (the "
            "ground surface) — a dwarf stands on it. A regular dig "
            "or up-stair goes into a WALL.",
            "A buried-soil down-stair is unreachable: no dwarf can "
            "stand on it, so the game never turns it into a job. "
            "Use dig_to_completion (it checks) or "
            "digging.derive_dig_site for a valid site.",
        ],
        "example": {"box": [97, 97, 175, 97, 97, 175],
                    "mode": "down-stair"},
    },
    "dig_to_completion": {
        "params": {
            "box": "A rectangle (x1, y1, z1, x2, y2, z2), one level.",
            "mode": "dig, down-stair, up-stair, channel, "
                    "up-down-stair, or ramp.",
        },
        "constraints": [
            "KNOWN BLOCKER (verified live 2026-11-26): the game "
            "will not create Dig jobs from designations in this "
            "fort, so this action times out waiting for a job. Do "
            "not retry it with the same site — escalate instead.",
            "Checks the site first (reachability + hazard: magma, "
            "aquifer, water above/below) and refuses unsafe sites.",
        ],
        "example": {"box": [97, 97, 175, 97, 97, 175],
                    "mode": "down-stair"},
    },
    "designate_chop": {
        "params": {
            "box": "A rectangle (x1, y1, z1, x2, y2, z2) containing "
                   "trees, one level.",
        },
        "constraints": [
            "Chopping needs a dwarf with the Wood Cutting labor "
            "and an axe. The fort has 2 picks; axes are a separate "
            "item.",
        ],
        "example": {"box": [70, 70, 175, 125, 125, 175]},
    },
    "designate_gather": {
        "params": {
            "box": "A rectangle (x1, y1, z1, x2, y2, z2) containing "
                   "gatherable plants, one level.",
        },
        "constraints": [
            "Gathering needs a dwarf with the Plant Gathering "
            "labor. Gathered plants are the brewable stock.",
        ],
        "example": {"box": [70, 70, 175, 125, 125, 175]},
    },
    "manager_order_create": {
        "params": {
            "job_type": f"One of: {', '.join(sorted(JOB_SPECS))}.",
        },
        "constraints": [
            "Manager orders NEVER work without a manager noble "
            "appointed (position id 10).",
            "There is NO BrewDrink / MakeBed / CookMeal job type — "
            "brewing is a CustomReaction (BREW_DRINK_FROM_PLANT), "
            "cooking is PrepareMeal, bed-making is MakeBed.",
        ],
        "example": {"job_type": "MakeBarrel", "amount": 1},
    },
    "manager_order_remove": {
        "params": {
            "order_id": "The manager order's id (from the jobs list).",
        },
        "example": {"order_id": 3},
    },
    "build_workshop": {
        "params": {
            "kind": "The workshop type, e.g. Still, Carpenter, "
                    "Mason, Kitchen, FarmPlot (use build_farm_plot "
                    "for farm plots).",
            "pos": "A 3-element (x, y, z) position on the ground.",
        },
        "constraints": [
            "The workshop needs its material (usually 1 wood) and "
            "a dwarf with the matching labor. The build fails fast "
            "on a missing material rather than queuing a job that "
            "can never be worked.",
        ],
        "example": {"kind": "Still", "pos": [95, 95, 175]},
    },
    "labor_toggle": {
        "params": {
            "unit": "A dwarf's id (or name).",
            "labor": "A labor name, e.g. MINER, CARPENTER, MASON, "
                     "BREWER, WOODCUTTER, HERBALIST. (The plant-"
                     "gathering labor is HERBALIST, not "
                     "PLANT_GATHERER — the catalog wrongly listed "
                     "PLANT_GATHERER until 2026-11-26, and the "
                     "model's attempt failed with 'unknown labor'.)",
        },
        "example": {"unit": 1, "labor": "BREWER", "enable": True},
    },
    "queue_job": {
        "params": {
            "building_id": "The workshop's building id.",
            "job": f"One of: {', '.join(sorted(JOB_SPECS))}.",
        },
        "example": {"building_id": 12, "job": "MakeBarrel"},
    },
    "build_farm_plot": {
        "params": {
            "x": "The plot's left edge.",
            "y": "The plot's top edge.",
            "z": "The z-level (the ground).",
        },
        "constraints": [
            "A farm plot needs soil (or mud) and a dwarf with the "
            "Farming labor. Plant plump helmets for brewing.",
        ],
        "example": {"x": 90, "y": 90, "z": 175, "w": 3, "h": 3},
    },
    "build_furniture": {
        "params": {
            "kind": "The furniture type, e.g. Bed, Table, Chair, "
                    "Door, Cabinet, Chest.",
        },
        "constraints": [
            "A bed needs a bed item (made at the carpenter) or "
            "wood. Dwarves sleep on the floor without one.",
        ],
        "example": {"kind": "Bed", "pos": [95, 95, 175]},
    },
    "deconstruct_building": {
        "params": {
            "building_id": "The building's id.",
        },
        "constraints": [
            "Deconstructing leaves a stale occupancy record; the "
            "site is blocked until the game clears it.",
        ],
        "example": {"building_id": 12},
    },
}


def _type_name(annotation: Any) -> str:
    """A readable name for a parameter annotation."""
    if annotation is inspect.Parameter.empty:
        return "any"
    # tuple[int, ...] -> "tuple[int, ...]"; str | int -> "str | int".
    return str(annotation).replace("typing.", "")


def describe(name: str) -> dict[str, Any] | None:
    """One action's description (None when the name is unknown)."""
    fn = ACTIONS.get(name)
    if fn is None:
        return None
    sig = inspect.signature(fn)
    params: dict[str, Any] = {}
    for pname, param in sig.parameters.items():
        if pname == "client":
            continue
        notes = NOTES.get(name, {}).get("params", {})
        params[pname] = {
            "type": _type_name(param.annotation),
            "required": param.default is inspect.Parameter.empty,
            **({"default": param.default}
               if param.default is not inspect.Parameter.empty else {}),
            **({"about": notes[pname]} if pname in notes else {}),
        }
    doc = inspect.getdoc(fn) or ""
    first_line = doc.splitlines()[0] if doc else ""
    notes = NOTES.get(name, {})
    return {
        "name": name,
        "about": first_line,
        "detail": doc,
        "params": params,
        "constraints": notes.get("constraints", []),
        **({"example": notes["example"]} if "example" in notes else {}),
    }


def catalog() -> dict[str, Any]:
    """The whole catalog: every action, its parameters, its
    constraints, and an example call. Built from the code, so it
    cannot drift from what the harness actually does."""
    actions = [describe(name) for name in sorted(ACTIONS)]
    return {
        "actions": [a for a in actions if a is not None],
        "count": len(actions),
        "how_to_call": (
            "POST /v1/actions/<name> with a JSON body of the "
            "parameters (the 'client' parameter is not yours — "
            "the harness supplies it). Every action returns "
            "{ok, reason, error_kind, fix, before, after, "
            "took_ms}. A failed action carries 'fix': the "
            "corrective action + what it needs."),
        "note": (
            "This catalog is built from the harness code itself "
            "(parameter names, types and defaults are the real "
            "ones). If a parameter's legal values are listed in "
            "'constraints', use exactly those."),
    }
