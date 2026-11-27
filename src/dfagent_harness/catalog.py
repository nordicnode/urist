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

__all__ = ["catalog", "describe", "NOTES", "QUERY_ROUTES"]

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
            "Checks the site first (reachability + hazard: magma, "
            "aquifer, water above/below) and refuses unsafe sites.",
            "Digging works (verified live 2026-11-26, f0e8617): "
            "the designation sets the map-block flag and the wait "
            "covers the job type the mode creates.",
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
            "Gathering needs a dwarf with the HERBALIST labor. "
            "Gathered plants are the brewable stock.",
        ],
        "example": {"box": [70, 70, 175, 125, 125, 175]},
    },
    "manager_order_create": {
        "params": {
            "job_type": "A df.job_type name, e.g. MakeBarrel, "
                        "MakeBucket, PrepareMeal. NOT a JOB_SPECS "
                        "key — brew, make_bed, cook are queue_job "
                        "names, not manager-order job types.",
        },
        "constraints": [
            "Manager orders NEVER work without a manager noble "
            "appointed (position id 10).",
            "There is no BrewDrink / MakeBed / CookMeal job_type: "
            "brewing is CustomReaction 211 "
            "(BREW_DRINK_FROM_PLANT), cooking is PrepareMeal 115, "
            "bed-making is CustomReaction 211 (MAKE WOODEN BED). "
            "Order those through queue_job with the JOB_SPECS key "
            "(brew, cook, make_bed), not through a manager order.",
            "An order consumes the same materials as the queue_job "
            "of the same job (1 wood per carpenter item; 1 brewable "
            "plant + 1 empty barrel per brew; 2 distinct food "
            "stacks per meal) — order only what the fort has, or "
            "the job is queued and then cancelled.",
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
            "pos": "A 3-element (x, y, z) position on the ground — "
                   "use a VERIFIED site from the snapshot's placement "
                   "section or GET /v1/sites?kind=workshop; never "
                   "guess coordinates.",
        },
        "constraints": [
            "The workshop needs its material — 1 unit of one of "
            "its materials (Carpenter: 1 wood; Mason: 1 stone; "
            "Still: 1 stone or 1 wood; Kitchen: 1 stone) — and a "
            "dwarf with the matching labor. The build fails fast "
            "on a missing material rather than queuing a job that "
            "can never be worked, and the error names what to "
            "gather (chop trees for wood, dig stone for stone).",
            "On a site-not-free failure the error names a verified "
            "alternative site — use it, do not retry the blocked "
            "one, and do not gather the blocker and retry the same "
            "site.",
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
        "example": {"unit": 1, "labor": "BREWER", "on": True},
    },
    "queue_job": {
        "params": {
            "building_id": "The workshop's building id.",
            "job": f"One of: {', '.join(sorted(JOB_SPECS))}.",
        },
        "example": {"building_id": 12, "job": "make_barrel"},
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
        "example": {"x": 90, "y": 90, "z": 175, "width": 3,
                    "height": 3},
    },
    "build_furniture": {
        "params": {
            "kind": "The furniture type, e.g. Bed, Table, Chair, "
                    "Door, Cabinet, Chest.",
        },
        "constraints": [
            "Placing a bed needs a bed ITEM in stock — wood alone "
            "does not place one. Make one first with queue_job "
            "job=make_bed at the carpenter (1 wood each), then "
            "place it. The place failure names that exact call. "
            "Dwarves sleep on the floor without one.",
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
    "create_stockpile": {
        "params": {
            "category": "The stockpile category: food, wood, stone, "
                        "refuse, furniture, animals, armor, "
                        "bars_blocks, cloth, coins, finished_goods, "
                        "gems, leather, ore, sheet, weapons, ammo, "
                        "corpses.",
            "pos": "A 3-element (x, y, z) position — the stockpile's "
                   "top-left corner. Use a VERIFIED site from the "
                   "snapshot's placement section or GET /v1/sites; "
                   "never guess coordinates.",
            "width": "The stockpile's width in tiles (1..31).",
            "height": "The stockpile's height in tiles (1..31).",
        },
        "constraints": [
            "A stockpile is abstract — it exists at once, no "
            "construction job. The site must be open floor, "
            "reachable, and not overlap another stockpile or zone. "
            "On a site-not-free failure the error names a verified "
            "alternative site — use it, do not retry the blocked "
            "one.",
        ],
        "example": {"category": "food", "pos": [93, 87, 176],
                    "width": 5, "height": 5},
    },
    "create_zone": {
        "params": {
            "zone_type": "The zone kind: meeting_area, pen_pasture, "
                         "pit_pond, hospital, animal_training, "
                         "fishing, garbage_dump, gather, clay, sand, "
                         "water_source.",
            "pos": "A 3-element (x, y, z) position — the zone's "
                   "top-left corner. Use a VERIFIED site from the "
                   "snapshot's placement section or GET /v1/sites; "
                   "never guess coordinates.",
            "width": "The zone's width in tiles (1..31).",
            "height": "The zone's height in tiles (1..31).",
        },
        "constraints": [
            "A zone (civzone) is abstract — it exists at once, no "
            "construction job. The site must be open floor, "
            "reachable, and not overlap another zone or stockpile. "
            "On a site-not-free failure the error names a verified "
            "alternative site — use it, do not retry the blocked "
            "one.",
        ],
        "example": {"zone_type": "meeting_area",
                    "pos": [112, 101, 175], "width": 5, "height": 5},
    },
}


def _type_name(annotation: Any) -> str:
    """A readable name for a parameter annotation."""
    if annotation is inspect.Parameter.empty:
        return "any"
    # tuple[int, ...] -> "tuple[int, ...]"; str | int -> "str | int".
    return str(annotation).replace("typing.", "")


def _job_materials_line() -> str:
    """The queue_job materials constraint, built from the same
    JOB_MATERIALS table the fail-fast check reads — so the catalog
    can never disagree with the implementation about what a job
    needs (general material awareness, 2026-11-27)."""
    from . import materials as _materials_mod
    parts = []
    for job in sorted(_materials_mod.JOB_MATERIALS):
        labels = " + ".join(
            r["label"] for r in _materials_mod.JOB_MATERIALS[job])
        parts.append(f"{job}: {labels}")
    return ("Materials per copy — the job fails fast when short, "
            "naming the gathering fix: " + "; ".join(parts) + ".")


# Query routes: read-only detail the snapshot only indexes (the
# model asks for them with the "query" pseudo-action, not POST
# /v1/actions). The wiki is the one the model needs most — it is
# how a model that knows nothing about DF learns how something
# works — and it was missing from the catalog entirely (2026-11-27:
# zero wiki uses in any M1 run), so the model never knew it was
# there. A query route is a GET with a query string, not an action
# call: {"action": "query", "kwargs": {"route": "/v1/wiki?q=..."}}.
QUERY_ROUTES: dict[str, dict[str, Any]] = {
    "wiki": {
        "route": "/v1/wiki?q=<question>",
        "about": ("Look up how Dwarf Fortress works in the local "
                  "wiki export (4,485 pages). Use it when you do "
                  "not know how something works or what to do "
                  "about an event — the briefing in the observation "
                  "already names the wiki pages for the event you "
                  "are facing."),
        "params": {
            "q": "The question, in plain words, e.g. "
                 "'how does brewing work'.",
            "mode": "search (fast keyword, default for a named "
                    "thing) or hybrid (best for vague questions).",
            "limit": "Max results (default 5).",
        },
        "constraints": [
            "A query does not count toward the 2-action limit, "
            "but do not query when the observation already "
            "answers the question.",
            "The search returns slugs + snippets; read the full "
            "page with GET /v1/wiki/<slug> when the snippet is "
            "not enough.",
        ],
        "example": {"route": "/v1/wiki?q=how does brewing work"},
    },
}


def describe(name: str) -> dict[str, Any] | None:
    """One action's description (None when the name is unknown).
    A 'task:<name>' name describes the composed task."""
    if name.startswith("task:"):
        return describe_task(name[len("task:"):])
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
    constraints = list(notes.get("constraints", []))
    if name == "queue_job":
        constraints.append(_job_materials_line())
    return {
        "name": name,
        "about": first_line,
        "detail": doc,
        "params": params,
        "constraints": constraints,
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
        "tasks": describe_tasks(),
        "query_routes": [QUERY_ROUTES[name]
                         for name in sorted(QUERY_ROUTES)],
        "how_to_call": (
            "POST /v1/actions/<name> with a JSON body of the "
            "parameters (the 'client' parameter is not yours — "
            "the harness supplies it). Every action returns "
            "{ok, reason, error_kind, fix, before, after, "
            "took_ms}. A failed action carries 'fix': the "
            "corrective action + what it needs. A composed task "
            "is called the same way, with the action name "
            "'task:<name>' and no parameters: the harness runs "
            "the whole chain (find the workshop, queue the job, "
            "wait for it) and reports the outcome."),
        "note": (
            "This catalog is built from the harness code itself "
            "(parameter names, types and defaults are the real "
            "ones). If a parameter's legal values are listed in "
            "'constraints', use exactly those. Prefer a composed "
            "task over the raw action when one exists for the "
            "goal: 'task:brew' does the whole brew (find the "
            "still, queue the job, wait) where 'queue_job brew' "
            "only queues it."),
    }


# The composed tasks (daemon.TASK_DEFS), as the model sees them.
# A task is one action name, 'task:<name>', with no parameters:
# the harness picks the workshop or plot and runs the whole chain.
# The 'about' line and the precondition come from the task's own
# implementation (daemon.run_task), not from the game's wiki — a
# task whose precondition is unmet fails fast and names it.
# The import is lazy (as in server.py): daemon.py is heavy and
# imports server.py at module level.
_TASK_NOTES: dict[str, dict[str, str]] = {
    "brew": {
        "about": ("Brew drink at a Still: find the still, queue "
                  "the brew job, wait for it to finish."),
        "needs": ("a Still workshop; 1 brewable plant + 1 empty "
                  "barrel or pot per brew (5 drink + 1 seed back)"),
    },
    "cook": {
        "about": ("Cook a meal at a Kitchen: find the kitchen, "
                  "queue the cooking job, wait for it to finish."),
        "needs": ("a Kitchen workshop; 2 distinct food stacks "
                  "for an easy meal (3 fine, 4 lavish)"),
    },
    "make_bed": {
        "about": ("Make a bed at a Carpenter's workshop: find "
                  "the workshop, queue the job, wait for it."),
        "needs": ("a Carpenter's workshop; 1 wood"),
    },
    "make_barrel": {
        "about": ("Make a barrel at a Carpenter's workshop: "
                  "find the workshop, queue the job, wait."),
        "needs": ("a Carpenter's workshop; 1 wood"),
    },
    "gather": {
        "about": ("Gather plants on the surface: find shrubs, "
                  "designate the gathering box, wait for the "
                  "gathering jobs to finish."),
        "needs": "shrubs on the surface (the harness finds them)",
    },
    "farm": {
        "about": ("Plant a farm plot: pick a crop for the plot's "
                  "light, biome and season, set it, wait for "
                  "PlantSeeds jobs to appear and finish."),
        "needs": ("a built farm plot; seeds on hand for a crop "
                  "that grows there"),
    },
}


def describe_task(name: str) -> dict[str, Any] | None:
    """One composed task's description (None when unknown). The
    name is the task name WITHOUT the 'task:' prefix."""
    from .daemon import TASK_DEFS

    if name not in TASK_DEFS:
        return None
    notes = _TASK_NOTES.get(name, {})
    return {
        "name": f"task:{name}",
        "about": notes.get("about", f"Run the {name} task."),
        "params": {},
        "constraints": ([f"needs {notes['needs']}"]
                        if "needs" in notes else []),
    }


def describe_tasks() -> list[dict[str, Any]]:
    """Every composed task, in name order. Built from TASK_DEFS
    so the catalog cannot list a task the daemon cannot run."""
    from .daemon import TASK_DEFS

    return [d for d in (describe_task(n) for n in sorted(TASK_DEFS))
            if d is not None]
