"""Attention section: what is wrong, what changed, what needs acting
on, in plain words (world-model design §6.1; milestone 5 assembler
seed).

The agent is TOLD, not left to query: this module builds the
attention list from the live state and the poll diff's arrival
record. The troll gap (2026-11-26) is the reason it exists — a troll
arrived in the caverns and fired no event anywhere, because the
watcher drops non-hostile UNIT_NEW_ACTIVE and the poll diff only
covered citizens and hostiles. Now a new non-citizen unit is a
first-class attention item the moment the diff sees it, with its
class, its name, and its position — and units already present when
monitoring starts are listed as already here, not silently
baselined away.

Milestone 5 grows this into the full assembler (stocks, distress,
diffing, the token accountant, the State Store). What is here now
is the arrivals + threats core, built so the fix is verifiable live
before the rest of the assembler lands.
"""

from __future__ import annotations

from typing import Any, Optional

__all__ = [
    "prettify_race", "describe_arrival", "build_attention",
    "ATTENTION_WINDOW_TICKS",
]

# An arrival stays in attention for one in-game day after its tick,
# then drops out (it remains in the journal/event stream for history).
ATTENTION_WINDOW_TICKS = 1200


def prettify_race(race: Optional[str]) -> str:
    """Turn a DF race id into plain words.

    "CRUNDLE" -> "crundle", "DEMON_14" -> "demon", "BIRD_TURKEY" ->
    "turkey", "WATER_BUFFALO" -> "water buffalo". The raw id is
    never shown to the agent without its plain form.
    """
    if not race:
        return "unknown creature"
    parts = race.lower().replace("_", " ").split()
    # Strip a trailing number (DEMON_14 is a demon) and a leading
    # "bird" (BIRD_TURKEY is a turkey).
    if parts and parts[-1].isdigit():
        parts = parts[:-1]
    if parts and parts[0] == "bird":
        parts = parts[1:]
    return " ".join(parts) or "unknown creature"


def _cheb3(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def _where(pos: tuple[int, int, int],
           surface_z: Optional[int]) -> str:
    """Plain-words location for a position: surface / underground /
    deep in the caverns. ``surface_z`` is the embark level (175 on
    Erushtathtat); without it the answer is just the coordinates.
    """
    if surface_z is None:
        return ""
    z = pos[2]
    if z >= surface_z - 8:
        return "on the surface"
    if z < surface_z - 40:
        return "deep underground, in the caverns"
    return "underground"


def describe_arrival(data: dict[str, Any],
                     surface_z: Optional[int] = None) -> str:
    """One plain-words sentence for a new-arrival event's data.

    Carries the class, the position, and (for wildlife) the distance
    to the nearest dwarf, so the agent can judge the risk without
    another query. Says whether the unit just arrived or was already
    here when monitoring started.
    """
    kind = data.get("kind") or "wildlife"
    role = data.get("role") or ""
    race = prettify_race(data.get("race"))
    if kind == "visitor":
        what = role if role and role != "visitor" else "visitor"
        noun = f"a {race} ({what})"
    elif kind == "livestock":
        noun = f"a {race} (pet)"
    else:
        noun = f"a {race} (wild animal)"
    pos = data.get("pos") or [None, None, None]
    where = _where((pos[0], pos[1], pos[2]), surface_z)
    at = f"at ({pos[0]}, {pos[1]}, z{pos[2]})"
    loc = f"{where}, {at}" if where else at
    dist = data.get("dist_nearest_citizen")
    dist_txt = ""
    if isinstance(dist, int):
        dist_txt = (f", {dist} tile{'s' if dist != 1 else ''} from "
                    f"the nearest dwarf")
    timing = ("It was already here when monitoring started."
              if data.get("at_baseline") else "It just arrived.")
    return f"{noun} is {loc}{dist_txt}. {timing}"


def build_attention(state: dict[str, Any],
                    detector: Any,
                    surface_z: Optional[int] = None,
                    window_ticks: int = ATTENTION_WINDOW_TICKS
                    ) -> list[dict[str, Any]]:
    """Build the attention list: threats first, then new arrivals.

    ``detector`` is the poll diff (its ``arrivals`` property is the
    record of what the agent has been told). An arrival stays in
    attention for ``window_ticks`` after its tick, then drops out —
    it is still in the journal. Returns items sorted P0-first:
    {"priority", "kind", "text", "unit_id", "pos", "at_baseline",
    "tick"} (arrivals carry their tick; threats carry none).
    """
    items: list[dict[str, Any]] = []
    status = state.get("status") or {}
    now_tick = status.get("year_tick")
    units = state.get("units") or {}
    citizens = [c.get("pos") for c in units.get("citizens") or []
                if isinstance(c, dict) and c.get("pos")]
    # Threats (priority 1): hostiles, nearest distance to a citizen.
    for h in units.get("hostiles") or []:
        if not isinstance(h, dict):
            continue
        pos = h.get("pos") or [None, None, None]
        dist = None
        if citizens and pos[0] is not None:
            dist = min(_cheb3((pos[0], pos[1], pos[2]),
                              (c[0], c[1], c[2])) for c in citizens)
        race = prettify_race(h.get("race"))
        where = _where((pos[0], pos[1], pos[2]), surface_z)
        loc = f"{where}, at ({pos[0]}, {pos[1]}, z{pos[2]})" \
            if where else f"at ({pos[0]}, {pos[1]}, z{pos[2]})"
        dist_txt = (f", {dist} tiles from the nearest dwarf"
                    if dist is not None else "")
        items.append({
            "priority": 1, "kind": "threat",
            "text": f"HOSTILE: a {race} is {loc}{dist_txt}. "
                    f"Keep dwarves away from it.",
            "unit_id": h.get("id"), "pos": pos,
            "at_baseline": False,
        })
    # New arrivals (priority 2 for visitors and near wildlife, 3 for
    # the rest): from the detector's record, inside the window.
    for rec in detector.arrivals:
        tick = rec.get("tick")
        if (isinstance(now_tick, int) and isinstance(tick, int)
                and now_tick - tick > window_ticks):
            continue
        data = rec.get("data") or {}
        severity = "warning" if data.get("kind") == "visitor" else \
            ("warning" if isinstance(
                data.get("dist_nearest_citizen"), int)
             and data["dist_nearest_citizen"] <= 15 else "info")
        priority = 2 if severity == "warning" else 3
        items.append({
            "priority": priority, "kind": "new_arrival",
            "text": describe_arrival(data, surface_z),
            "unit_id": data.get("unit_id"), "pos": data.get("pos"),
            "at_baseline": bool(rec.get("at_baseline")),
            "tick": tick,
        })
    # P0-first: priority ascending, most recent first within a
    # priority. (Python's sort is stable, so equal keys keep
    # insertion order: threats before arrivals, arrivals in
    # emission order.)
    items.sort(key=lambda it: (it["priority"],
                               -(it.get("tick") or 0)))
    return items
