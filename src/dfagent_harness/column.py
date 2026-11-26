"""Vertical column profile: what is above and below a spot.

Standing directive 2026-11-26 (vertical awareness): the agent must
be able to ask "what is underneath this spot before I dig there?"
and get a plain-words answer. Wraps ``lua/column.lua`` (one
getTileBlock per z-level, ~50 ms) and merges its strata into
readable runs: floor/passage/air become "open space", a tall open
run below the surface becomes "cavern space", the topmost open run
is "open sky".

Read safety (design §8): ``read_column`` is only ever called inside
a ``paused_read`` window, by the HTTP route.
"""

from __future__ import annotations

from typing import Any, Optional

from dfhack_rpc import DFHackClient

from .actions import _helper_or_fail
from .spatial import estimate_tokens

__all__ = [
    "read_column", "describe_column", "dig_down", "ground_level",
]

# An open-space run this tall, below the surface, is cavern space
# rather than a dug room or passage (a room is a few levels).
CAVERN_SPAN_LEVELS = 10


def read_column(client: DFHackClient, x: int, y: int) -> dict[str, Any]:
    """Read the full column at (x, y) (column.lua). Cheap (~50 ms).

    Call only inside ``paused_read``. Returns the raw Lua dict.
    Raises _Fail on a helper failure, ValueError on bad coords.
    """
    out = _helper_or_fail(client, "column.lua", {"x": x, "y": y},
                          timeout=60.0)
    if not out["column"].get("ok", True):
        raise ValueError(out["column"].get("error") or "column failed")
    return out["column"]


def _merge_strata(strata: list[dict[str, Any]],
                  surface_z: Optional[int]) -> list[dict[str, Any]]:
    """Merge raw Lua strata into readable runs.

    floor/passage/air -> "open space" (or "open sky" above the
    surface, "cavern space" for a tall open run below it). The rest
    keep their class. Consecutive runs of the same merged class
    join. Each run: {class, z1, z0, levels, max_depth}.
    """
    def _class(s: dict[str, Any]) -> str:
        c = s["class"]
        if c in ("floor", "passage", "air"):
            if surface_z is not None and s["z0"] >= surface_z:
                return "open sky"
            if (surface_z is not None and s["z1"] - s["z0"] + 1
                    >= CAVERN_SPAN_LEVELS and s["z1"] < surface_z):
                return "cavern space"
            return "open space"
        if c == "hidden":
            return "hidden (unrevealed)"
        return c

    merged: list[dict[str, Any]] = []
    for s in strata:
        cls = _class(s)
        # Never merge across the revealed / unrevealed boundary: a
        # revealed run and an unrevealed run of the same class are
        # different knowledge.
        unrev = bool(s.get("unrevealed", False))
        if (merged and merged[-1]["class"] == cls
                and merged[-1].get("unrevealed", False) == unrev):
            merged[-1]["z0"] = s["z0"]
            merged[-1]["levels"] = (
                merged[-1]["z1"] - merged[-1]["z0"] + 1)
            merged[-1]["max_depth"] = max(
                merged[-1]["max_depth"], s.get("max_depth", 0))
        else:
            merged.append({
                "class": cls, "z1": s["z1"], "z0": s["z0"],
                "levels": s["z1"] - s["z0"] + 1,
                "max_depth": s.get("max_depth", 0),
                "unrevealed": unrev,
            })
    return merged


def ground_level(strata: list[dict[str, Any]],
                   surface_z: Optional[int] = None) -> Optional[int]:
    """The ground surface at this column: the level a dwarf stands
    on. That is one above the top solid run (soil, stone, mineral,
    aquifer) — the floor a dwarf stands on sits on top of the solid
    ground below it. (At the fort centre the top solid is soil
    z174, so the ground is z175, where the dwarves stand.)"""
    merged = _merge_strata(strata, surface_z)
    for run in merged:
        if run["class"] in ("soil", "stone", "mineral", "aquifer"):
            return run["z1"] + 1
    return None


def describe_column(col: dict[str, Any],
                    surface_z: Optional[int] = None,
                    fort_z: Optional[int] = None) -> dict[str, Any]:
    """Plain-words profile of a column + its hazards.

    Returns {"profile", "runs", "hazards"} where ``runs`` is the
    merged strata list and ``profile`` is one readable sentence per
    run, top to bottom. ``surface_z`` is the embark level (175 on
    Erushtathtat); without it, open runs above the ground are
    called "open space" instead of "open sky".
    """
    x, y = col["x"], col["y"]
    strata = col.get("strata") or []
    runs = _merge_strata(strata, surface_z)
    if not runs:
        return {"profile": f"At ({x}, {y}): nothing read.",
                "runs": [], "hazards": []}
    parts = []
    for run in runs:
        cls = run["class"]
        span = (f"z{run['z1']}..z{run['z0']}" if run["z1"] != run["z0"]
                else f"z{run['z1']}")
        if cls == "soil":
            parts.append(f"soil {span}")
        elif cls == "stone":
            parts.append(f"solid rock {span}")
        elif cls == "mineral":
            parts.append(
                f"mineral-bearing rock {span} "
                f"(ore unidentified)")
        elif cls == "aquifer":
            parts.append(
                f"light aquifer rock {span} "
                f"(digging here leaks water)")
        elif cls == "water":
            depth = run["max_depth"]
            parts.append(
                f"water {span}"
                + (f", up to {depth} deep (7 is full)"
                   if depth else ""))
        elif cls == "magma":
            parts.append(f"magma {span}")
        elif cls == "plant":
            parts.append(f"plants {span}")
        elif cls == "hidden (unrevealed)":
            parts.append(
                f"hidden (unrevealed) rock {span} — could be "
                f"solid or open, the game has not shown it yet")
        else:
            parts.append(f"{cls} {span}")
        # Unrevealed runs are map data (designation + tiletype),
        # not ground a dwarf has seen — say so on each one.
        if run.get("unrevealed"):
            parts[-1] += " (unrevealed)"
    profile = (f"At ({x}, {y}), from the top down: "
               + "; ".join(parts) + ".")
    if any(r.get("unrevealed") for r in runs):
        profile += (" Runs marked (unrevealed) are map data — no "
                    "dwarf has seen them yet, but they are what "
                    "digging will find.")
    hazards: list[str] = []
    for run in runs:
        if run["class"] == "aquifer":
            hazards.append(
                f"Light aquifer rock at z{run['z1']}..z{run['z0']} — "
                f"digging into it will leak water into the fort.")
        elif run["class"] == "magma":
            hazards.append(
                f"Magma at z{run['z1']}..z{run['z0']} — digging "
                f"into it will breach lava.")
        elif run["class"] == "water":
            hazards.append(
                f"Water at z{run['z1']}..z{run['z0']} — digging "
                f"into it will flood the fort.")
    return {"profile": profile, "runs": runs, "hazards": hazards}


def dig_down(col: dict[str, Any], levels: int, from_z: int,
             surface_z: Optional[int] = None) -> str:
    """Plain words for "if I dig down N levels from (x, y, z), what
    do I hit?" — the strata crossed, then the next hazards below
    (aquifer, cavern, magma) with their distances.

    Digging down N levels from z means digging the N tiles below
    it (z-1 .. z-N); the tile at z itself is where the dwarf
    stands, not a tile to dig.
    """
    _WORDS = {"stone": "solid rock",
              "mineral": "mineral-bearing rock",
              "aquifer": "aquifer rock", "soil": "soil",
              "water": "water", "magma": "magma",
              "open space": "open space",
              "cavern space": "open cavern space",
              "hidden (unrevealed)": "hidden (unrevealed) rock",
              "plant": "plants", "open sky": "open sky"}
    x, y = col["x"], col["y"]
    runs = _merge_strata(col.get("strata") or [], surface_z)
    target = from_z - levels
    top = from_z - 1
    crossed = [r for r in runs if r["z1"] >= target
               and r["z0"] <= top]
    if not crossed:
        hit = "nothing — the column is empty there"
    else:
        parts = []
        for r in crossed:
            hi = min(r["z1"], top)
            lo = max(r["z0"], target)
            n = hi - lo + 1
            span = (f"z{hi}..z{lo}" if hi != lo else f"z{hi}")
            parts.append(
                f"{_WORDS.get(r['class'], r['class'])} for {n} "
                f"level{'s' if n != 1 else ''} ({span})")
        hit = "; ".join(parts)
    out = (f"If you dig down {levels} level"
           f"{'s' if levels != 1 else ''} from ({x}, {y}, z{from_z}), "
           f"you will hit {hit}.")
    below = []
    for r in runs:
        if r["z1"] >= target:
            continue
        if r["class"] == "aquifer":
            below.append(
                f"the aquifer is {target - r['z1']} levels further "
                f"down (z{r['z1']})")
        elif r["class"] == "cavern space":
            below.append(
                f"open cavern space starts {target - r['z1']} "
                f"levels further down (z{r['z1']})")
        elif r["class"] == "magma":
            below.append(
                f"magma starts {target - r['z1']} levels further "
                f"down (z{r['z1']})")
    if below:
        out += " Below that: " + "; ".join(below) + "."
    return out


def column_response(col: dict[str, Any], levels: int, from_z: int,
                    surface_z: Optional[int] = None,
                    ms: int = 0, lua_ms: int = 0) -> dict[str, Any]:
    """The /v1/column response: raw strata + plain-words profile,
    hazards, the dig-down answer, and the cost."""
    described = describe_column(col, surface_z=surface_z)
    text = (described["profile"] + " "
            + dig_down(col, levels, from_z, surface_z))
    return {
        "column": col,
        "runs": described["runs"],
        "profile": described["profile"],
        "hazards": described["hazards"],
        "dig_down": {"levels": levels, "from_z": from_z,
                     "text": dig_down(col, levels, from_z,
                                      surface_z)},
        "cost": {"tokens": estimate_tokens(text), "ms": ms,
                 "lua_ms": lua_ms},
    }
