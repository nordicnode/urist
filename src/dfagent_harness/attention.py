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
    "prettify_race", "describe_arrival", "describe_unit",
    "build_attention", "ATTENTION_WINDOW_TICKS",
]

# An arrival stays in attention for one in-game day after its tick,
# then drops out (it remains in the journal/event stream for history).
ATTENTION_WINDOW_TICKS = 1200
# A baseline arrival (already present when the first snapshot was
# taken) can age out of the 1,200-tick window before the agent's
# first planner tick ever sees it. Baseline arrivals stay for 7
# in-game days (7 x 1,200 ticks) instead — long enough for the
# planner to notice them, short enough that they still drop out of
# attention once the fort has settled.
BASELINE_WINDOW_TICKS = 8400


def _briefing_for(kind: str) -> dict[str, Any] | None:
    """The situation briefing for an attention kind (GOAL.md step 5,
    layer 5). A wiki failure never breaks attention — the briefing
    is None and the item stands on its own text."""
    try:
        from .briefings import brief_for
        return brief_for(kind)
    except Exception:  # noqa: BLE001 - briefing is best-effort
        return None


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


# Job-type verbs for the citizen description. Only the common ones
# are mapped; anything else falls back to the raw type name, never
# an invented verb.
_JOB_VERBS = {
    "Dig": "digging", "FellTree": "cutting down a tree",
    "Eat": "eating", "Drink": "drinking", "Drink2": "drinking",
    "Sleep": "sleeping", "HaulStone": "hauling stone",
    "HaulWood": "hauling wood", "HaulItem": "hauling an item",
    "HaulBody": "hauling a body", "HaulFood": "hauling food",
    "HaulFurniture": "hauling furniture",
    "ConstructBuilding": "constructing a building",
    "CustomReaction": "working a reaction",
    "PrepareMeal": "cooking a meal", "MakeBarrel": "making a barrel",
    "MakeBucket": "making a bucket", "PlantSeeds": "planting seeds",
    "HarvestPlants": "harvesting plants",
    "GatherPlants": "gathering plants", "Fish": "fishing",
    "Hunt": "hunting", "TrainAnimal": "training an animal",
    "ButcherAnimal": "butchering an animal", "MilkCreature": "milking",
    "ShearCreature": "shearing", "Clean": "cleaning",
    "Rest": "resting", "SeekArtifact": "seeking an artifact",
    "StoreItemInStockpile": "storing an item",
    "RemoveConstruction": "removing a construction",
    "DestroyBuilding": "destroying a building",
}


def _counter_words(counters: dict[str, Any]) -> list[str]:
    """Plain words for hunger/thirst/sleepiness, from the measured
    live thresholds (hunger eats at ~40,000, thirst drinks at
    ~20,000, sleepiness sleeps at ~50,000)."""
    out = []
    hunger = counters.get("hunger")
    if isinstance(hunger, int):
        if hunger >= 40000:
            out.append("very hungry")
        elif hunger >= 30000:
            out.append("hungry")
        elif hunger >= 20000:
            out.append("getting hungry")
    thirst = counters.get("thirst")
    if isinstance(thirst, int):
        if thirst >= 20000:
            out.append("very thirsty")
        elif thirst >= 15000:
            out.append("thirsty")
        elif thirst >= 10000:
            out.append("getting thirsty")
    sleepiness = counters.get("sleepiness")
    if isinstance(sleepiness, int):
        if sleepiness >= 50000:
            out.append("exhausted, needs sleep")
        elif sleepiness >= 40000:
            out.append("very tired")
        elif sleepiness >= 30000:
            out.append("getting tired")
    return out


def describe_unit(rec: dict[str, Any],
                  surface_z: Optional[int] = None,
                  fort_centre: Optional[tuple[int, int, int]] = None
                  ) -> str:
    """One plain-words sentence (or two) for any unit record.

    Citizens get name, profession, what they are doing, where they
    are, and their state (hunger/thirst/sleepiness/stress/wounds)
    in words, not raw numbers. Compact records (wildlife, visitors,
    livestock, hostiles) get class, race in plain words, position,
    and distance to the nearest dwarf where known. The raw record
    stays alongside; this is the readable form.
    """
    pos = rec.get("pos") or [None, None, None]
    where = _where((pos[0], pos[1], pos[2]), surface_z)
    at = f"at ({pos[0]}, {pos[1]}, z{pos[2]})"
    loc = f"{where}, {at}" if where else at
    kind = rec.get("kind")
    name = rec.get("name") or ""
    # Citizens: the full record (profession, job, counters, stress).
    if kind is None and rec.get("profession"):
        prof = rec["profession"]
        who = f"{name}, a citizen dwarf ({prof.lower()})" \
            if name else f"A citizen dwarf ({prof.lower()})"
        doing = ""
        job = rec.get("job") or {}
        if rec.get("idle"):
            doing = "idle"
        elif job.get("type"):
            doing = _JOB_VERBS.get(job["type"],
                                   f"doing {job['type']}")
        state = _counter_words(rec.get("counters") or {})
        stress = rec.get("stress") or {}
        cat = stress.get("category")
        if isinstance(cat, int):
            if cat <= 1:
                state.append("highly stressed")
            elif cat == 2:
                state.append("stressed")
        wounds = rec.get("wound_count")
        if isinstance(wounds, int) and wounds > 0:
            state.append(f"wounded ({wounds} wound"
                         f"{'s' if wounds != 1 else ''})")
        mood_name = rec.get("mood_name")
        if mood_name and mood_name != "none":
            state.append(f"in a {mood_name.lower()} mood")
        text = f"{who} is {loc}"
        if doing:
            text += f", {doing}"
        if state:
            joined = "; ".join(state)
            text += ". " + joined[0].upper() + joined[1:]
        return text + "."
    # Compact records and hostiles.
    race = prettify_race(rec.get("race"))
    if kind == "visitor":
        role = rec.get("role") or ""
        what = role if role and role != "visitor" else "visitor"
        noun = f"a {race} ({what})"
    elif kind == "livestock":
        noun = f"a {race} (pet)"
    elif kind == "wildlife":
        noun = f"a {race} (wild animal)"
    elif kind == "hostile":
        noun = f"a {race} (HOSTILE)"
    else:
        noun = f"a {race}"
    if name and name.lower() not in (race, "unit"):
        noun = f"{name}, {noun}"
    text = f"{noun} is {loc}"
    dist = rec.get("dist_nearest_citizen")
    if isinstance(dist, int):
        text += (f", {dist} tile{'s' if dist != 1 else ''} from "
                 f"the nearest dwarf")
    return text + "."


def _level_gap(pos: tuple[int, int, int],
                 surface_z: Optional[int]) -> str:
    """Plain-words vertical distance from the fort: "174 levels
    below the fort", "3 levels below the fort", "on the fort's
    level", "2 levels above the fort". The model cannot tell a
    threat 174 levels down from one 3 levels down from the
    coordinates alone — the gap has to be stated.
    """
    if surface_z is None or pos[2] is None:
        return ""
    gap = surface_z - pos[2]
    if gap == 0:
        # On the fort's level is the default — saying so adds
        # nothing.
        return ""
    if gap > 0:
        return (f"{gap} level{'s' if gap != 1 else ''} "
                f"below the fort")
    gap = -gap
    return f"{gap} level{'s' if gap != 1 else ''} above the fort"


def _where(pos: tuple[int, int, int],
           surface_z: Optional[int]) -> str:
    """Plain-words location for a position: surface / underground /
    deep in the caverns, plus the vertical distance from the fort.
    ``surface_z`` is the embark level (175 on Erushtathtat);
    without it the answer is just the coordinates.
    """
    if surface_z is None:
        return ""
    z = pos[2]
    if z >= surface_z - 8:
        base = "on the surface"
    elif z < surface_z - 40:
        base = "deep underground, in the caverns"
    else:
        base = "underground"
    gap = _level_gap(pos, surface_z)
    return f"{base}, {gap}" if gap else base


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
    """Build the attention list: threats first, then low stocks,
    then new arrivals.

    ``detector`` is the poll diff (its ``arrivals`` property is the
    record of what the agent has been told); it may be None, in
    which case the arrivals are skipped and only the threats +
    stocks are reported. An arrival stays in attention for
    ``window_ticks`` after its tick, then drops out — it is still
    in the journal. Returns items sorted P0-first: {"priority",
    "kind", "text", "unit_id", "pos", "at_baseline", "tick"}
    (arrivals carry their tick; threats and stocks carry none).
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
            "briefing": _briefing_for("hostile"),
        })
    # Low stocks (design §6.1: "what is wrong"): low drink/food
    # are the fort's most common killers, and the suggestion maps
    # them to the brew/cook tasks. The thresholds match the
    # planner's (DRINK_WARN 20 / CRITICAL 5, FOOD_WARN 15 /
    # CRITICAL 5). These need no detector — they come straight
    # from the state.
    stocks = state.get("stocks") or {}
    for key, label, warn, crit in (
            ("drink_units", "Drink", 20, 5),
            ("food_units", "Food", 15, 5)):
        n = stocks.get(key)
        if not isinstance(n, int):
            continue
        if n <= crit:
            items.append({
                "priority": 1, "kind": f"low_{label.lower()}",
                "text": f"{label} is CRITICAL: {n} units left. "
                        f"The fort will run out in days.",
                "unit_id": None, "pos": None,
                "at_baseline": False,
            })
        elif n <= warn:
            items.append({
                "priority": 2, "kind": f"low_{label.lower()}",
                "text": f"{label} is low: {n} units left.",
                "unit_id": None, "pos": None,
                "at_baseline": False,
            })
    # New arrivals (priority 2 for visitors and near wildlife, 3 for
    # the rest): from the detector's record, inside the window.
    # Baseline arrivals get the long window (7 in-game days): they
    # were already present at the first snapshot, and the agent's
    # first planner tick may come much later than the 1,200-tick
    # (one-day) window.
    for rec in (detector.arrivals if detector is not None else []):
        tick = rec.get("tick")
        window = (BASELINE_WINDOW_TICKS if rec.get("at_baseline")
                  else window_ticks)
        if (isinstance(now_tick, int) and isinstance(tick, int)
                and now_tick - tick > window):
            continue
        data = rec.get("data") or {}
        severity = "warning" if data.get("kind") == "visitor" else \
            ("warning" if isinstance(
                data.get("dist_nearest_citizen"), int)
             and data["dist_nearest_citizen"] <= 15 else "info")
        priority = 2 if severity == "warning" else 3
        # Far below the fort: a wild animal 174 levels down in the
        # caverns is not an urgent arrival, however close it looks
        # in the horizontal plane. Demote it to info (P3) — the
        # level gap is now in its text, so the model can still see
        # it. Visitors are never demoted: they come to the fort.
        pos = data.get("pos") or [None, None, None]
        if (data.get("kind") != "visitor"
                and surface_z is not None
                and isinstance(pos[2], int)
                and surface_z - pos[2] > 40):
            priority = 3
        items.append({
            "priority": priority, "kind": "new_arrival",
            "text": describe_arrival(data, surface_z),
            "unit_id": data.get("unit_id"), "pos": data.get("pos"),
            "at_baseline": bool(rec.get("at_baseline")),
            "tick": tick,
            "briefing": _briefing_for("new_arrival"),
        })
    # P0-first: priority ascending, most recent first within a
    # priority. (Python's sort is stable, so equal keys keep
    # insertion order: threats before arrivals, arrivals in
    # emission order.)
    items.sort(key=lambda it: (it["priority"],
                               -(it.get("tick") or 0)))
    return items
