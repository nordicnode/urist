"""Material requirements for jobs and builds — one table, used by the
actions (fail fast), the snapshot (shortage flags) and the suggestion
(name the gathering fix instead of the blocked action).

Every quantity here is verified against the live game, never guessed:

* ``df.reaction.find`` (449 reactions, probed live 2026-11-27): every
  MAKE WOODEN * job (bed/table/chair/door/barrel/bucket/bin/chest/
  cabinet) takes exactly 1 WOOD (log). The reaction lists a second
  NONE "tool" reagent — it consumes no stock item (there is no item
  of type NONE), so the check is 1 log. BREW_DRINK_FROM_PLANT (index
  44): 1 PLANT with DRINK_MAT + 1 EMPTY barrel/pot -> 5 DRINK +
  1 SEEDS. BREW_DRINK_FROM_PLANT_GROWTH (45) is the same shape with
  PLANT_GROWTH. Cross-checked against the game raws
  (raw/objects/reaction_other.txt:265-294).
* Cook (PrepareMeal, job_type 115, no reaction): DF wiki (Cook page)
  — an easy meal needs 2 distinct food stacks, fine 3, lavish 4;
  the cook must have the proper number of distinct stacks when the
  job starts or it is cancelled. The fail-fast floor is 2 distinct
  food stacks per meal (``food_stacks`` in the stocks section).
* Workshops: WORKSHOP_CATALOG in actions.py (materials list) — a
  build needs 1 accessible unit of one of its materials (the build
  action already probes this live via probe_material.lua).
* Empty barrels: stocks.lua counts them (BARREL items with no
  contained items, trader-held excluded). Total barrels is NOT the
  check for brewing — the fort had 15 barrels with only 3 empty
  (2026-11-27), so a brew x5 against the total would queue 2 jobs
  that can never run.

Stock keys resolve against the stocks section dict. ``brewable_plants``
is computed from ``by_material`` by the same rule as the assembler's
and the planner's ``_brewable_plants`` (PLANT items whose material
has a DRINK product); the rule is duplicated here so this module
stays importable without the assembler.
"""

from __future__ import annotations

from typing import Any, Optional

# ----------------------------------------------------------------------
# Requirement table
# ----------------------------------------------------------------------
#
# One entry per JOB_SPECS job: the materials the game consumes per
# copy of the job. ``stock`` is a key of the stocks section (or the
# computed ``brewable_plants`` / ``empty_barrels`` keys). ``gather``
# is the exact fix when the fort is short — the action that gets the
# material, in the form the model can run. ``{carpenter}`` in a gather
# string is replaced with the carpenter's building id (``#7``) when
# the buildings list is available, else the words "the carpenter".

#: 1 wood (log) — every carpenter item job (verified live).
_WOOD_1 = {
    "stock": "wood_units",
    "per_job": 1,
    "label": "1 wood (log)",
    "gather": "chop trees first (designate_chop — needs a dwarf "
              "with the WOODCUTTER labor)",
}

#: 1 brewable plant — one brew job (verified live).
_PLANT_1 = {
    "stock": "brewable_plants",
    "per_job": 1,
    "label": "1 brewable plant",
    "gather": "gather plants first (designate_gather on a "
              "shrub-rich box — needs a dwarf with the HERBALIST "
              "labor)",
}

#: 1 empty barrel — one brew job (verified live). The fix names the
#: carpenter explicitly: a barrel is made there, 1 wood each.
_BARREL_1 = {
    "stock": "empty_barrels",
    "per_job": 1,
    "label": "1 empty barrel",
    "gather": "queue make_barrel at {carpenter} "
              "(queue_job job=make_barrel — 1 wood each)",
}

#: 2 distinct food stacks — one easy meal (DF wiki, Cook page).
_FOOD_STACKS_2 = {
    "stock": "food_stacks",
    "per_job": 2,
    "label": "2 distinct food stacks",
    "gather": "gather plants (designate_gather), fish, or hunt — "
              "a meal needs 2 distinct food stacks",
}

JOB_MATERIALS: dict[str, list[dict[str, Any]]] = {
    "brew": [_PLANT_1, _BARREL_1],
    # brew_fruit brews PLANT_GROWTH, whose drink stock is not split
    # out in the stocks section (by_material has no PLANT_GROWTH
    # entries) — the plant check below is the conservative proxy:
    # it uses the brewable-plant count, which never overstates the
    # fruit stock, so a pass here is honest and a fail names the
    # real fix (gather). The barrel check is exact.
    "brew_fruit": [_PLANT_1, _BARREL_1],
    "cook": [_FOOD_STACKS_2],
    "make_bed": [_WOOD_1],
    "make_table": [_WOOD_1],
    "make_chair": [_WOOD_1],
    "make_door": [_WOOD_1],
    "make_barrel": [_WOOD_1],
    "make_bucket": [_WOOD_1],
    "make_bin": [_WOOD_1],
    "make_chest": [_WOOD_1],
    "make_cabinet": [_WOOD_1],
}

#: Workshop build materials, by WORKSHOP_CATALOG kind. Each entry is
#: a list of ALTERNATIVES: the build needs 1 accessible unit of any
#: one of them (the build action probes them in order). The labels
#: are what the snapshot and the catalog print.
WORKSHOP_MATERIALS: dict[str, list[dict[str, Any]]] = {
    "carpenter": [_WOOD_1],
    "mason": [{
        "stock": "stone_units",
        "per_job": 1,
        "label": "1 stone (boulder)",
        "gather": "dig stone first (designate_dig — needs a dwarf "
                  "with the MINER labor and a pick)",
    }],
    "still": [
        {
            "stock": "stone_units",
            "per_job": 1,
            "label": "1 stone (boulder)",
            "gather": "dig stone first (designate_dig — needs a "
                      "dwarf with the MINER labor and a pick)",
        },
        _WOOD_1,
    ],
    "kitchen": [{
        "stock": "stone_units",
        "per_job": 1,
        "label": "1 stone (boulder)",
        "gather": "dig stone first (designate_dig — needs a dwarf "
                  "with the MINER labor and a pick)",
    }],
}


# ----------------------------------------------------------------------
# Stock counts
# ----------------------------------------------------------------------

def is_brewable_entry(entry: dict[str, Any]) -> bool:
    """True when one by_material entry counts as a brewable plant.

    stocks.lua marks PLANT entries with ``brewable`` (true iff the
    plant raw defines a DRINK material). Entries from an older
    collect carry no flag: fall back to the item type, counting
    PLANT items. The fallback overcounts non-brewable plants
    (dimple cup, quarry bush) — it is best-effort for old data
    only; the flag is the exact rule. Brewed drink is NEVER
    counted: a DRINK entry's material token ends :DRINK, which is
    what the old rule matched — it returned the fort's drink
    count, not its plants (2026-11-27, external review C3).
    """
    if not isinstance(entry, dict):
        return False
    flag = entry.get("brewable")
    if flag is not None:
        return flag is True
    return entry.get("type") == "PLANT"


def brewable_plants(stocks: dict[str, Any]) -> int:
    """Brewable plant units in stock: PLANT items whose plant has
    a DRINK product. The planner's and the assembler's
    ``_brewable_plants`` both delegate here, so the rule lives in
    exactly one place (the old rule was copied in three modules
    and all three were wrong together).
    """
    total = 0
    for e in stocks.get("by_material") or []:
        if is_brewable_entry(e):
            total += int(e.get("units") or 0)
    return total


def stock_count(stocks: dict[str, Any], key: str) -> Optional[int]:
    """Units on hand for a requirement's ``stock`` key, or None when
    the stocks section does not carry it (missing section means
    "unknown", never zero — a failed collect must not invent a
    shortage)."""
    if not isinstance(stocks, dict):
        return None
    if key == "brewable_plants":
        return brewable_plants(stocks)
    if key == "empty_barrels":
        # stocks.lua counts these since 2026-11-27; an older collect
        # has no key — fall back to total barrels so the check still
        # runs (a barrel count of 0 is exact either way).
        if "empty_barrels" in stocks:
            return stocks.get("empty_barrels")
        return stocks.get("barrels")
    val = stocks.get(key)
    return val if isinstance(val, int) else None


def item_count(items: dict[str, Any], item_type: str) -> Optional[int]:
    """Units of one item type from the items section's by_type table,
    or None when the section is missing."""
    if not isinstance(items, dict):
        return None
    for e in items.get("by_type") or []:
        if e.get("type") == item_type:
            return int(e.get("units") or 0)
    return 0


def workshop_id(buildings: dict[str, Any], subtype: str) -> Optional[int]:
    """Building id of a workshop subtype (e.g. "Carpenters"), or None
    when there is none / the section is missing."""
    if not isinstance(buildings, dict):
        return None
    for b in buildings.get("list") or []:
        if (b.get("type") == "Workshop"
                and b.get("subtype") == subtype):
            return b.get("id")
    return None


def _fill_carpenter(text: str, buildings: Optional[dict[str, Any]]
                    ) -> str:
    """Replace the ``{carpenter}`` placeholder with the carpenter's
    building id (``#7``) when known, else the words "the carpenter"."""
    cid = workshop_id(buildings or {}, "Carpenters")
    name = f"the carpenter #{cid}" if cid is not None else "the carpenter"
    return text.replace("{carpenter}", name)


# ----------------------------------------------------------------------
# Shortage checks
# ----------------------------------------------------------------------

def queued_count(jobs_section: Any, job_type: int,
                 reaction_name: Optional[str] = None) -> int:
    """Jobs of one kind already in the world job list (from the jobs
    section's list): same numeric job_type, and — for reaction jobs
    — the same reaction_name. A brew is CustomReaction (211) +
    BREW_DRINK_FROM_PLANT; the type name alone cannot tell it from
    a MAKE WOODEN BED. A missing/unreadable jobs section returns 0
    (the fail-fast then behaves as before — a missing section must
    not invent a shortage or block queueing); a present list that
    holds none also returns 0."""
    if not isinstance(jobs_section, dict):
        return 0
    n = 0
    for j in jobs_section.get("list") or []:
        if not isinstance(j, dict):
            continue
        if j.get("job_type") != job_type:
            continue
        if reaction_name is not None and \
                j.get("reaction") != reaction_name:
            continue
        n += 1
    return n


def check_requirements(
        stocks: dict[str, Any],
        requirements: list[dict[str, Any]],
        count: int = 1,
        buildings: Optional[dict[str, Any]] = None,
        already_queued: int = 0,
        ) -> list[dict[str, Any]]:
    """Shortages for one action: each requirement whose stock is
    short of ``per_job * count``. Returns a list of
    {need, have, label, fix}; empty when everything is covered or
    when the stocks section is missing a key (unknown, not short).
    ``count`` is how many copies of the job/build are wanted;
    ``already_queued`` is how many copies are already in the world
    job list — they hold the same stock (a brew already queued
    holds one empty barrel), so the need is per_job *
    (count + already_queued). Without it the model queued 4 brews
    against 2 empty barrels (run #12): each queue passed the
    check because it only ever saw the fresh stock."""
    shortages: list[dict[str, Any]] = []
    for req in requirements:
        have = stock_count(stocks, req["stock"])
        if have is None:
            continue
        need = int(req["per_job"]) * (max(1, count) + max(0, already_queued))
        if have < need:
            shortages.append({
                "need": need,
                "per_job": int(req["per_job"]),
                "have": have,
                "label": req["label"],
                "fix": _fill_carpenter(req["gather"], buildings),
            })
    return shortages


def check_job(job: str, stocks: dict[str, Any], count: int = 1,
              buildings: Optional[dict[str, Any]] = None,
              already_queued: int = 0,
              ) -> list[dict[str, Any]]:
    """Shortages for queueing ``count`` copies of a JOB_SPECS job.
    Unknown job -> [] (the caller validates the name itself).
    ``already_queued`` counts copies already in the world job list
    (see :func:`queued_count`) — they hold the same materials."""
    reqs = JOB_MATERIALS.get(job)
    if reqs is None:
        return []
    return check_requirements(stocks, reqs, count=count,
                              buildings=buildings,
                              already_queued=already_queued)


def check_workshop(kind: str, stocks: dict[str, Any],
                   buildings: Optional[dict[str, Any]] = None
                   ) -> list[dict[str, Any]]:
    """Shortages for building one workshop of ``kind``. The material
    is any-of: short only when EVERY alternative is short (a still
    builds from stone OR wood). Returns [] when any alternative is
    covered, or when the kind is unknown."""
    alternatives = WORKSHOP_MATERIALS.get(str(kind).strip().lower())
    if not alternatives:
        return []
    covered = False
    worst: list[dict[str, Any]] = []
    for req in alternatives:
        have = stock_count(stocks, req["stock"])
        if have is None:
            continue
        if have >= int(req["per_job"]):
            covered = True
            break
        worst.append({
            "need": int(req["per_job"]),
            "per_job": int(req["per_job"]),
            "have": have,
            "label": req["label"],
            "fix": _fill_carpenter(req["gather"], buildings),
        })
    if covered:
        return []
    return worst


def format_shortage(shortage: dict[str, Any]) -> str:
    """One shortage as the model sees it: need / have / exact fix.
    The label already carries its own count ("1 empty barrel"), so
    a single-copy shortage reads "need 1 empty barrel", not the
    doubled "need 1 1 empty barrel" the old text produced; a
    multi-copy shortage reads "need 5 in total (1 empty barrel
    each)".
    """
    need = shortage["need"]
    if need == shortage.get("per_job", need):
        need_txt = f"need {shortage['label']}"
    else:
        need_txt = (f"need {need} in total "
                    f"({shortage['label']} each)")
    return (f"{need_txt}, have {shortage['have']} — "
            f"{shortage['fix']}")


# ----------------------------------------------------------------------
# Snapshot requirements: exact have/need for the jobs the fort
# needs next (reinforced 2026-11-27 — the stock side is explicit)
# ----------------------------------------------------------------------

def _n(val: Optional[int]) -> str:
    """A stock count as the model sees it: the number, or "unknown"
    when the collect did not carry it — never a guessed zero."""
    return str(val) if isinstance(val, int) else "unknown"


def _item_make_line(need_txt: str, item_label: str, job: str,
                    stocks: dict[str, Any],
                    buildings: dict[str, Any]) -> str:
    """Have/need for an item the fort is out of (a BED item, an
    empty barrel): the item's own have/need AND the make job's
    have/need, so the model sees both numbers before it acts —
    e.g. "need 1 BED item to place — have 0; make one needs 1
    wood — have 124 (queue make_bed at the carpenter #7 ...)"."""
    wood = stock_count(stocks, "wood_units")
    cid = workshop_id(buildings, "Carpenters")
    if isinstance(wood, int) and wood >= 1:
        if cid is not None:
            fix = (f"queue {job} at the carpenter #{cid} "
                   f"(queue_job job={job} — 1 wood each)")
        else:
            fix = (f"no Carpenter's workshop — build one first "
                   f"(build_workshop kind=carpenter — 1 wood), then "
                   f"queue {job} there (queue_job job={job} — "
                   f"1 wood each)")
        return (f"{need_txt}; make one needs 1 wood — have {wood} "
                f"({fix})")
    if isinstance(wood, int):  # wood == 0
        return (f"{need_txt}; make one needs 1 wood — have 0 — "
                f"{_fill_carpenter(_WOOD_1['gather'], buildings)}")
    # Wood on hand unknown: the old form, without a wood number.
    return (f"no {item_label} in stock — "
            + _make_fix(job, buildings))


def requirements_for_state(state: dict[str, Any]) -> list[str]:
    """Have/need lines for the snapshot's Materials section — the
    jobs the fort is about to need, with EXACT counts on both
    sides, covered as well as short:

    * no Still yet: the still build itself (stone or wood);
    * Still exists: brew (plants, empty barrels, and how many
      brews the stock covers);
    * always: make_bed when no BED item is in stock, make_barrel
      when no empty barrel is in stock and there is no still (the
      brew line carries the barrel numbers once a still exists).

    A line is emitted for the action being considered whether the
    material is covered ("need X, have Y (enough)") or short
    ("need X, have Y — <fix>"), so the model sees the exact stock
    BEFORE it acts instead of learning it from a failure. The
    counts come from the same fresh collect the snapshot uses
    (``_snapshot`` does one paused full collect and passes that
    state here), never from the poller's cached state — a shortage
    built on stale zeros would be wrong. A missing
    stocks/buildings/items section means "unknown" — no line is
    emitted, never a false shortage. Empty list when there is no
    next job to consider or nothing is known.
    """
    stocks = state.get("stocks")
    if not isinstance(stocks, dict):
        return []
    buildings = state.get("buildings")
    if not isinstance(buildings, dict):
        buildings = {}
    items = state.get("items")
    lines: list[str] = []

    def _has_workshop(subtype: str) -> bool:
        return workshop_id(buildings, subtype) is not None

    has_still = _has_workshop("Still")
    if not has_still:
        stone = stock_count(stocks, "stone_units")
        wood = stock_count(stocks, "wood_units")
        still_short = check_workshop("still", stocks, buildings)
        if still_short:
            for s in still_short:
                lines.append(
                    "Still build: " + format_shortage(s))
        elif ((isinstance(stone, int) and stone >= 1) or
                (isinstance(wood, int) and wood >= 1)):
            lines.append(
                "Still build: need 1 stone or 1 wood — have stone "
                f"{_n(stone)}, wood {_n(wood)} (enough)")
        # else: both counts unknown — no honest line to emit.
    else:
        # Brews already queued hold the same stock (one empty
        # barrel + one plant each), so the "enough for N" number
        # and the fail-fast both subtract them — run #12 queued 4
        # brews against 2 empty barrels because the line still
        # said "enough for 2 brews" after 2 were already queued.
        queued_brews = (
            queued_count(state.get("jobs"), 211,
                         "BREW_DRINK_FROM_PLANT")
            + queued_count(state.get("jobs"), 211,
                           "BREW_DRINK_FROM_PLANT_GROWTH"))
        brew_short = check_job("brew", stocks, count=1,
                               buildings=buildings,
                               already_queued=queued_brews)
        if brew_short:
            for s in brew_short:
                lines.append("Brew: " + format_shortage(s))
        else:
            plants = stock_count(stocks, "brewable_plants")
            empty = stock_count(stocks, "empty_barrels")
            if isinstance(plants, int) and isinstance(empty, int):
                n = min(plants, empty) - queued_brews
                if n <= 0:
                    lines.append(
                        "Brew: need 1 brewable plant + 1 empty "
                        "barrel per drink — have "
                        f"{plants} plants, {empty} empty barrels "
                        f"({queued_brews} already committed to "
                        f"queued brews — enough for 0 more; make "
                        f"more barrels or wait for the queued "
                        f"brews to finish)")
                else:
                    queued_txt = (
                        f"; {queued_brews} already queued"
                        if queued_brews else "")
                    lines.append(
                        "Brew: need 1 brewable plant + 1 empty "
                        "barrel per drink — have "
                        f"{plants} plants, {empty} empty barrels "
                        f"(enough for {n} more brew"
                        f"{'s' if n != 1 else ''}{queued_txt})")
            # else: a count is unknown — no honest line to emit.
    beds = item_count(items, "BED") if isinstance(items, dict) else None
    if beds is not None and beds == 0:
        lines.append("Bed: " + _item_make_line(
            "need 1 BED item to place — have 0", "BED item",
            "make_bed", stocks, buildings))
    empty = stock_count(stocks, "empty_barrels")
    if empty is not None and empty == 0 and not has_still:
        lines.append("Barrel: " + _item_make_line(
            "need 1 empty barrel per brew — have 0", "empty barrel",
            "make_barrel", stocks, buildings))
    return lines


def _make_fix(job: str, buildings: dict[str, Any]) -> str:
    """The fix line for making one item when the item itself is out
    of stock but its material is on hand: queue it at the carpenter,
    or build a carpenter first when there is none."""
    cid = workshop_id(buildings, "Carpenters")
    if cid is not None:
        return (f"queue {job} at the carpenter #{cid} "
                f"(queue_job job={job} — 1 wood each)")
    return (f"no Carpenter's workshop — build one first "
            f"(build_workshop kind=carpenter — 1 wood), then queue "
            f"{job} there (queue_job job={job} — 1 wood each)")
