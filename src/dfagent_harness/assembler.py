"""Context Assembler + token accountant (world-model design §6, §7).

The per-tick snapshot is TEXT FIRST (the measured text snapshot is
8x smaller than JSON) and a DIFF + INDEX, not a re-dump. It is the
``observe`` tool's return and the daemon's tick input.

Budget (research doc §6, design §6.1): target <=30K tokens,
warning 60K, compaction 100K, never >140K on a 200K window. The
typical snapshot is ~5K, leaving ~25K of headroom for on-demand
pulls inside the same decision (retrieval cap 4K).

Token counting: the accountant is CONSERVATIVE — it over-counts,
never under-counts (design §12 open item 8). The wire cost uses
the measured ~4 chars/token (``spatial.estimate_tokens``); the
accountant enforces the cap at ~3 chars/token, a 33% margin, so a
snapshot the accountant calls 30K is really ~22K.

Scaling invariant (design §6.1): NO section of the per-tick
snapshot may grow linearly with population, items, or map size.
Counts, exceptions, and diffs only. A section that grows linearly
is a bug in the assembler, not a property of the fort.

Cut order (research doc §6), applied when over budget: drop
recent history -> drop old reports -> compact units to counts ->
drop secondary sections. THREATS, ATTENTION, and FAILURE FEEDBACK
are NEVER dropped.

Diffing (design §7): each section is hashed and compared with the
Store's last snapshot for that section. An unchanged section
renders as a one-liner ("units: unchanged (10 citizens)"). Stable
lists (labors, skills) are sent once and then as diffs only. The
diff is computed from the Store, not by re-reading the game.

Trends (design §7): the Store keeps a daily time series of
headline numbers. Burn rate = slope over the last 7 in-game days;
days-remaining = stock / burn rate. Both are computed by the
harness and pushed in the stocks section. The agent never computes
a burn rate from a single snapshot.
"""

from __future__ import annotations

from typing import Any, Optional

from .attention import build_attention
from .spatial import estimate_tokens
from .store import Store, TICKS_PER_DAY

__all__ = [
    "TokenAccountant", "assemble", "suggest", "sample_daily",
    "TARGET_TOKENS", "WARNING_TOKENS", "COMPACTION_TOKENS",
    "NEVER_TOKENS", "MAX_ATTENTION_ITEMS", "MAX_EXCEPTION_ITEMS",
    "MAX_REPORTS", "MAX_EVENTS", "MAX_AREAS", "MAX_HISTORY",
]

# Token budgets (research doc §6).
TARGET_TOKENS = 30000
WARNING_TOKENS = 60000
COMPACTION_TOKENS = 100000
NEVER_TOKENS = 140000

# Section bounds (design §6.1).
MAX_ATTENTION_ITEMS = 8
MAX_EXCEPTION_ITEMS = 8
MAX_REPORTS = 3
MAX_EVENTS = 5
MAX_AREAS = 15
MAX_HISTORY = 2

# Sections that are never cut, in any order.
NEVER_CUT = ("attention", "header", "status", "suggestion")


class TokenAccountant:
    """Conservative token counting + cap enforcement.

    ``count`` over-counts (3 chars/token) so a snapshot the
    accountant calls 30K is really ~22K. ``fit`` applies the cut
    order and returns the sections that survive, in order, plus
    the list of cuts applied.
    """

    def __init__(self, target: int = TARGET_TOKENS):
        self.target = target

    @staticmethod
    def count(text: str) -> int:
        """Conservative token estimate: ~3 chars per token."""
        return max(1, len(text) // 3)

    @staticmethod
    def wire_count(text: str) -> int:
        """The measured wire estimate (~4 chars/token)."""
        return estimate_tokens(text)

    def fit(self, sections: list[dict[str, Any]]
            ) -> tuple[list[dict[str, Any]], list[str]]:
        """Apply the cut order until the total is under target.

        ``sections`` is a list of {"name", "text", "priority",
        "cut"} where ``cut`` is a callable returning the compacted
        text (or "" to drop the section) and priority is the cut
        order (lower = cut first). Returns (surviving, cuts).
        Never-cut sections are never passed a cut.
        """
        total = sum(self.count(s["text"]) for s in sections)
        cuts: list[str] = []
        if total <= self.target:
            return sections, cuts
        # Cut in priority order (lowest priority first).
        ordered = sorted(
            (s for s in sections if s["name"] not in NEVER_CUT),
            key=lambda s: s["priority"])
        for s in ordered:
            if total <= self.target:
                break
            old = self.count(s["text"])
            new_text = s["cut"]()
            if not new_text:
                cuts.append(f"dropped {s['name']} "
                            f"({old} tokens)")
                s["text"] = ""
                s["dropped"] = True
                total -= old
            else:
                new = self.count(new_text)
                if new < old:
                    cuts.append(f"compacted {s['name']} "
                                f"({old} -> {new} tokens)")
                    s["text"] = new_text
                    total -= (old - new)
        return [s for s in sections if s.get("text")], cuts


def _section(name: str, text: str, short: str,
             priority: int, cut=None) -> dict[str, Any]:
    return {"name": name, "text": text, "short": short,
            "priority": priority, "cut": cut}


def _header(state: dict[str, Any]) -> tuple[str, str]:
    status = state.get("status") or {}
    fort = (status.get("fort_name") or status.get("save_dir")
            or "Fort")
    date = status.get("date") or "unknown date"
    tick = status.get("year_tick")
    paused = status.get("paused")
    focus = status.get("focus")
    fps = (state.get("meta") or {}).get("fps")
    tick_txt = f"tick {tick}" if isinstance(tick, int) else "tick ?"
    parts = [f"{fort}, {date} ({tick_txt})",
             f"paused: {paused}" if paused is not None else None,
             f"focus: {focus}" if focus else None,
             f"FPS: {fps}" if fps is not None else None]
    text = " ".join(p for p in parts if p) + "."
    return text, f"{fort}, {date}"


def _attention_items(items: list[dict[str, Any]]
                     ) -> tuple[str, str]:
    """Render an already-built attention list (max 8 items).

    An item with a ``briefing`` carries it inline (the situation
    briefing + its wiki references) — before this the briefing
    field was built by attention.build_attention and then dropped
    here, so the model never saw the wiki slugs for the event it
    was facing (2026-11-27: zero wiki uses in any M1 run). The
    briefing is a few lines under its item, never a separate
    section, so a tick with no briefed items costs nothing.
    """
    items = items[:MAX_ATTENTION_ITEMS]
    if not items:
        return "Attention: nothing needs acting on.", "0 items"
    lines = ["Attention (most urgent first):"]
    for it in items:
        lines.append(f"  [P{it['priority']}] {it['text']}")
        lines.extend(_briefing_lines(it.get("briefing")))
    return "\n".join(lines), f"{len(items)} items"


def _briefing_lines(briefing: Any) -> list[str]:
    """One briefed item's briefing as indented lines: what it is,
    why it matters, the options, the cost of ignoring it, and the
    wiki pages for it (slugs + the route to the full page). Empty
    when the item has no briefing."""
    if not isinstance(briefing, dict):
        return []
    out = []
    for label, key in (("Briefing", "what"),
                       ("Why it matters", "matters"),
                       ("Options", "options"),
                       ("Cost of ignoring", "cost")):
        text = briefing.get(key)
        if text:
            out.append(f"    {label}: {text}")
    refs = briefing.get("wiki") or []
    slugs = [r.get("slug") for r in refs if r.get("slug")]
    if slugs:
        first = slugs[0]
        listed = ", ".join(slugs)
        out.append(
            f"    Wiki: {listed} — full page: /v1/wiki/{first} "
            f"(or search: /v1/wiki?q=<question>)")
    return out


def _attention(state: dict[str, Any], detector: Any,
               surface_z: Optional[int]) -> tuple[str, str]:
    items = build_attention(state, detector, surface_z=surface_z)
    return _attention_items(items)


def _goals(goals: Optional[list[dict[str, Any]]]) -> tuple[str, str]:
    if not goals:
        return ("Goals: none recorded yet.",
                "0 goals")
    lines = ["Goals:"]
    for g in goals:
        name = g.get("name", "?")
        done = "done" if g.get("done") else "open"
        lines.append(f"  - {name} ({done}, priority "
                     f"{g.get('priority', '?')})")
    return "\n".join(lines), f"{len(goals)} goals"


def _status(state: dict[str, Any]) -> tuple[str, str]:
    status = state.get("status") or {}
    units = state.get("units") or {}
    citizens = units.get("citizens") or []
    hostiles = units.get("hostiles") or []
    pop = status.get("population") or {}
    idle = sum(1 for c in citizens if c.get("idle"))
    # The count uses wound_count — the same field describe_unit
    # renders ("wounded (N wound(s))") — so the Population count and
    # the Units exception list can never disagree even if a record
    # carries a stale wounds list. (Run #12's review flagged a
    # count/list mismatch; the jsonl snapshots agree everywhere, so
    # the hardening is the fix: one predicate, one field.)
    wounded = sum(
        1 for c in citizens
        if (c.get("wound_count") if isinstance(c.get("wound_count"), int)
            else len(c.get("wounds") or [])) > 0)
    total = (units.get("total_active_units")
             or len(citizens) + len(hostiles)
             + len(units.get("wildlife") or [])
             + len(units.get("visitors") or [])
             + len(units.get("livestock") or []))
    text = (f"Population: {len(citizens)} citizens "
            f"({idle} idle, {wounded} wounded), "
            f"{pop.get('animals', 0)} animals, "
            f"{len(hostiles)} hostiles, {total} active units "
            f"(reconciled).")
    return text, (f"{len(citizens)} citizens, {len(hostiles)} "
                  f"hostiles")


def _materials(state: dict[str, Any]) -> tuple[str, str]:
    """Exact have/need for the jobs the fort needs next (general
    material awareness, 2026-11-27; reinforced the same day): what
    each considered job/build needs, how much is on hand, and the
    exact gathering fix when short — so the model sees the numbers
    BEFORE it acts, instead of learning them from a failure. A
    line is emitted for the action being considered whether the
    material is covered or short; empty only when there is no
    next job to consider or nothing is known (the section then
    costs no tokens at all). The counts come from the same fresh
    collect as the rest of the snapshot. The table lives in
    materials.py; this only renders it."""
    from . import materials as _materials_mod
    lines = _materials_mod.requirements_for_state(state)
    if not lines:
        return "", ""
    text = "Materials (have / need for the next jobs):\n" + \
        "\n".join(f"  - {line}" for line in lines)
    return text, f"{len(lines)} requirement(s)"


def _stocks(state: dict[str, Any], store: Optional[Store],
            tick: Optional[int]) -> tuple[str, str]:
    stocks = state.get("stocks") or {}
    if "stocks" not in state:
        return ("Stocks: unavailable (section failed to collect).",
                "unavailable")
    drink = stocks.get("drink_units")
    food = stocks.get("food_units")
    wood = stocks.get("wood_units")
    stone = stocks.get("stone_units")
    lines = []
    head = []
    for label, val in (("drink", drink), ("food", food),
                       ("wood", wood), ("stone", stone)):
        if val is not None:
            head.append(f"{label} {val}")
    # Brewable plants, in the head line so it survives compaction:
    # the model needs the count to decide about brewing without a
    # query turn (M1 tick 6: three brewers enabled, no brew queued,
    # no check of whether plants existed to brew).
    head.append(f"brewable plants {_brewable_plants(stocks)}")
    # Empty barrels and food stacks, same reason (reinforced
    # 2026-11-27): the barrel count is the brew bottleneck and the
    # stack count is what cooking needs (2 per easy meal) — both
    # are exact stock the model needs before it acts, not a
    # shortage flag. stocks.lua counts both since 2026-11-27.
    empty_barrels = stocks.get("empty_barrels")
    if isinstance(empty_barrels, int):
        head.append(f"empty barrels {empty_barrels}")
    food_stacks = stocks.get("food_stacks")
    if isinstance(food_stacks, int):
        head.append(f"food stacks {food_stacks}")
    lines.append("Stocks: " + (", ".join(head) if head else "none")
                 + ".")
    # Burn rates + days-remaining from the Store's trends. The
    # agent never computes a burn rate from a single snapshot. The
    # days-remaining uses the CURRENT snapshot's stock value, not
    # the last trend sample (a stale zero sample used to print
    # "0.0 days left" while the real stock was 39).
    if store is not None and isinstance(tick, int):
        stock_keys = {"drink": "drink_units", "food": "food_units",
                      "wood": "wood_units", "stone": "stone_units"}
        for metric, label in (("drink", "drink"),
                              ("food", "food"),
                              ("wood", "wood"),
                              ("stone", "stone")):
            rate = store.burn_rate(metric, tick)
            current = stocks.get(stock_keys[metric])
            current = (float(current)
                       if isinstance(current, (int, float)) else None)
            days = store.days_remaining(metric, tick, current=current)
            if rate is None:
                continue
            if rate > 0:
                days_txt = (f", {days:.1f} days left"
                            if days is not None else
                            ", days left unknown")
                lines.append(f"  {label} is falling "
                             f"{rate:.1f}/day{days_txt}.")
            else:
                lines.append(f"  {label} is rising "
                             f"{-rate:.1f}/day.")
    by_mat = stocks.get("by_material") or []
    if by_mat:
        top = sorted(by_mat, key=lambda e: e.get("units", 0),
                     reverse=True)[:8]
        lines.append("  By material: " + ", ".join(
            f"{e.get('material')} {e.get('units')}" for e in top)
        + ".")
    short = ", ".join(head) if head else "no stocks"
    return "\n".join(lines), short


def _units(state: dict[str, Any]) -> tuple[str, str]:
    from .attention import describe_unit
    if "units" not in state:
        return ("Units: unavailable (section failed to collect).",
                "unavailable")
    units = state.get("units") or {}
    citizens = units.get("citizens") or []
    if not citizens:
        return "Units: no citizens.", "0 citizens"
    # Exception list only: distressed, wounded, or idle with a
    # problem — max 8, compact. The full citizen list is NEVER
    # pushed (it grows linearly with population).
    exceptions = []
    for c in citizens:
        counters = c.get("counters") or {}
        stress = (c.get("stress") or {}).get("level", 0)
        wounds = c.get("wounds") or []
        if (stress >= 10000 or wounds
                or (counters.get("thirst", 0) or 0) >= 15000
                or (counters.get("hunger", 0) or 0) >= 30000
                or (counters.get("sleepiness", 0) or 0) >= 40000):
            exceptions.append(c)
    lines = [f"Units: {len(citizens)} citizens."]
    if exceptions:
        lines.append("  Exceptions (distressed / wounded / needy):")
        for c in exceptions[:MAX_EXCEPTION_ITEMS]:
            lines.append("  - " + describe_unit(c))
        if len(exceptions) > MAX_EXCEPTION_ITEMS:
            lines.append(f"  ... and {len(exceptions) - MAX_EXCEPTION_ITEMS} more.")
    else:
        lines.append("  No citizen is distressed, wounded, or "
                     "dangerously needy.")
    # Counts by profession (bounded: top 8 professions).
    prof: dict[str, int] = {}
    for c in citizens:
        prof[c.get("profession") or "?"] = \
            prof.get(c.get("profession") or "?", 0) + 1
    top = sorted(prof.items(), key=lambda kv: -kv[1])[:8]
    lines.append("  By profession: " + ", ".join(
        f"{k} {v}" for k, v in top) + ".")
    return "\n".join(lines), (f"{len(citizens)} citizens, "
                              f"{len(exceptions)} exceptions")


def _entities(state: dict[str, Any]) -> tuple[str, str]:
    if "units" not in state:
        return ("Entities: unavailable (section failed to collect).",
                "unavailable")
    units = state.get("units") or {}
    lines = []
    # Per-race counts come per class (wildlife_by_race,
    # livestock_by_race); combine them for the summary. The live
    # collect emits them as a list of {race, count} records (sorted
    # by count); accept a dict too, for offline fixtures.
    counts: dict[str, int] = {}
    for key in ("wildlife_by_race", "livestock_by_race"):
        raw = units.get(key) or []
        pairs = ([(r.get("race"), r.get("count", 0)) for r in raw]
                 if isinstance(raw, list)
                 else raw.items())
        for race, n in pairs:
            if race:
                counts[race] = counts.get(race, 0) + (n or 0)
    total = units.get("total_active_units")
    if counts:
        lines.append("Entities by race: " + ", ".join(
            f"{k} {v}" for k, v in
            sorted(counts.items(), key=lambda kv: -kv[1])[:12])
            + ".")
    if total is not None:
        lines.append(f"  Total active units: {total} (reconciled).")
    hostiles = units.get("hostiles") or []
    if hostiles:
        lines.append("  Hostiles (in full):")
        for h in hostiles:
            pos = h.get("pos") or []
            lines.append(f"    - {h.get('race')} at "
                         f"({pos[0] if len(pos) > 0 else '?'}, "
                         f"{pos[1] if len(pos) > 1 else '?'}, "
                         f"z{pos[2] if len(pos) > 2 else '?'})")
    else:
        lines.append("  No hostiles.")
    return "\n".join(lines), (f"{total} active units, "
                              f"{len(hostiles)} hostiles")


def _buildings(state: dict[str, Any]) -> tuple[str, str]:
    if "buildings" not in state:
        return ("Buildings: unavailable (section failed to collect).",
                "unavailable")
    buildings = state.get("buildings") or {}
    summary = buildings.get("summary") or []
    lst = buildings.get("list") or []
    if not summary and not lst:
        return "Buildings: none.", "0 buildings"
    # Workshops by subtype with state AND id. The model must be
    # able to tell a Carpenter's from a Still without spending a
    # query turn: M1 ticks 1 and 4 burned idle ticks asking what
    # the single existing building is, and by tick 6 three brewers
    # were enabled without ever checking whether a Still existed.
    # construction_stage >= 2 is built (the live Carpenter's is 3;
    # the fake's completed build is 2); 0/1 is under construction.
    # The Still is named explicitly when absent, so the model never
    # has to guess whether brewing is possible. The id is carried
    # because queue_job needs a building_id — M1 run #10 stalled
    # for three idle ticks ("I need the building ids for the
    # carpenter and still before I can queue bed-making or
    # brewing") because the list named the workshops but not
    # their ids.
    workshops = [b for b in lst if b.get("type") == "Workshop"]
    parts: list[str] = []
    for b in workshops:
        sub = b.get("subtype") or "?"
        stage = b.get("construction_stage")
        state_txt = ("under construction"
                     if isinstance(stage, int) and stage < 2
                     else "built")
        bid = b.get("id")
        parts.append(f"{sub} #{bid} ({state_txt})"
                     if isinstance(bid, int)
                     else f"{sub} ({state_txt})")
    if not any(b.get("subtype") == "Still" for b in workshops):
        parts.append("Still: none")
    # Other building types as counts (workshops are listed above,
    # so the Workshop summary count is not repeated).
    for e in [e for e in summary if e.get("type") != "Workshop"][:12]:
        parts.append(f"{e.get('type')} x{e.get('count')}")
    lines = ["Buildings: " + ", ".join(parts) + "."]
    # The short form is what the diffed one-liner shows when the
    # section is unchanged ("buildings: unchanged (SHORT)"). It
    # must carry the workshop subtypes, not just a count: M1 run
    # #7 tick 6 regressed to asking "what the one existing building
    # is" because the one-liner said only "1 buildings" and the
    # model had lost the subtype.
    return "\\n".join(lines), ", ".join(parts)


def _brewable_plants(stocks: dict[str, Any]) -> int:
    """Brewable plant units in stock — see materials.brewable_plants.
    The rule lives there so it cannot drift across the three copies
    again (2026-11-27, external review C3); surfaced in the snapshot
    so the model can decide about brewing without a query turn."""
    from . import materials as _materials
    return _materials.brewable_plants(stocks)


def _jobs(state: dict[str, Any]) -> tuple[str, str]:
    if "jobs" not in state:
        return ("Jobs: unavailable (section failed to collect).",
                "unavailable")
    jobs = state.get("jobs") or {}
    lst = jobs.get("list") or []
    by_type: dict[str, int] = {}
    for j in lst:
        by_type[j.get("type") or "?"] = \
            by_type.get(j.get("type") or "?", 0) + 1
    lines = [f"Jobs: {len(lst)} active."]
    if by_type:
        lines.append("  By type: " + ", ".join(
            f"{k} {v}" for k, v in
            sorted(by_type.items(), key=lambda kv: -kv[1])[:8])
            + ".")
    # Failure feedback (never dropped): blocked/cancelled jobs
    # with their reason. The planner's decide() surfaces these;
    # the snapshot carries the count + the first few.
    blocked = [j for j in lst
               if (j.get("suspended") or j.get("cancelled")
                   or j.get("blocked"))]
    if blocked:
        lines.append(f"  Blocked/cancelled: {len(blocked)}.")
        for j in blocked[:MAX_EXCEPTION_ITEMS]:
            reason = (j.get("reason") or j.get("cancel_reason")
                      or "no reason given")
            lines.append(f"    - {j.get('type')} ({reason})")
    return "\n".join(lines), f"{len(lst)} jobs"


def _placement(placement: Optional[dict[str, Any]]
               ) -> tuple[str, str]:
    """Compact placement section: verified free + reachable sites.

    The placement cache is {kind: [site, ...]} where a site is
    {pos, kind, width, height, reachable, why}. Renders a few named
    options per kind with what makes each one good (format_compact),
    token-light — the full detail (checks, blocked reasons) lives
    behind GET /v1/sites. Returns ("", short) when there are no
    verified sites, so the section is omitted, not rendered empty.
    When the cache is missing, the section says the placement is
    unavailable rather than implying no site exists.
    """
    if placement is None:
        return ("Placement: unavailable (no placement cache yet).",
                "unavailable")
    from .placement import PLACEMENT_KINDS, format_compact
    # Only real placement kinds — the cache also carries "centre"
    # and "from" (lists of ints), which are not site lists; passing
    # them to format_compact breaks it ('int' has no .get).
    by_kind = {k: v for k, v in placement.items()
               if k in PLACEMENT_KINDS
               and isinstance(v, list) and v}
    text = format_compact(by_kind)
    if not text:
        return ("Placement: no verified sites on hand — query "
                "/v1/sites?kind=<kind> to search.",
                "no verified sites")
    # The short form is what the diffed one-liner shows when the
    # section is unchanged ("placement: unchanged (SHORT)"). A
    # bare count ("16 verified sites") loses the coordinates, and
    # M1 run #10 ticks 3 and 6 stalled asking for verified free
    # sites the model had already been given on tick 1. Carry the
    # first site per kind, compactly — the full list is in the
    # section text on a changed tick and behind /v1/sites.
    short_parts = []
    for kind in PLACEMENT_KINDS:
        sites = by_kind.get(kind) or []
        if not sites:
            continue
        p = (sites[0].get("pos") or [])
        if len(p) == 3:
            short_parts.append(f"{kind} ({p[0]},{p[1]},{p[2]})")
    short = "; ".join(short_parts) if short_parts else \
        f"{sum(len(v) for v in by_kind.values())} verified sites"
    return text, short


def _report_line(entry: Any) -> str:
    """One announcement/combat report as one line of text.

    The collect dumps the raw DFHack struct (unk_v40_1, zoom_type,
    pos, ...) alongside the named fields — printing the dict
    wastes tokens and noise. Format: [y125 t100800] It is now
    summer. A plain string is returned as-is.
    """
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, dict):
        return str(entry)
    text = entry.get("text") or ""
    year = entry.get("year")
    time = entry.get("time")
    if year is not None and time is not None:
        return f"[y{year} t{time}] {text}"
    if time is not None:
        return f"[t{time}] {text}"
    return str(text)


def _report_key(entry: Any) -> tuple:
    """Identity of one report entry for dedupe: (year, time, text).
    A plain string keys on its text alone."""
    if isinstance(entry, str):
        return (None, None, entry)
    if isinstance(entry, dict):
        return (entry.get("year"), entry.get("time"),
                entry.get("text") or "")
    return (None, None, str(entry))


# Weather / season announcements are not combat. They already print
# as plain announcement lines; world.status.reports carries them too,
# so without this filter the same rain prints twice — once plain,
# once as "combat:" (run #12: "combat: [y125 t68350] It has started
# raining."). Matched on the announcement's opening words.
_WEATHER_PREFIXES = (
    "It has started raining", "It has stopped raining",
    "The weather has cleared",
    "It is now spring", "It is now summer",
    "It is now autumn", "It is now winter",
    "It has started snowing", "It has stopped snowing",
)


def _is_weather(text: str) -> bool:
    return any(text.startswith(p) for p in _WEATHER_PREFIXES)


def _reports(state: dict[str, Any]) -> tuple[str, str]:
    if "reports" not in state:
        return ("Reports: unavailable (section failed to collect).",
                "unavailable")
    reports = state.get("reports") or {}
    anns = reports.get("announcements") or []
    # The Lua helper names the combat reports "reports", not
    # "combat" — read the real field (the old key never fired).
    combat = reports.get("reports") or reports.get("combat") or []
    if not anns and not combat:
        return "Reports: nothing new.", "0 reports"
    lines = ["Reports:"]
    shown = {_report_key(a) for a in anns[-MAX_REPORTS:]}
    for a in anns[-MAX_REPORTS:]:
        lines.append(f"  - {_report_line(a)}")
    for c in combat[-2:]:
        # A combat line that duplicates an announcement line, or
        # that IS a weather/season announcement, is not combat —
        # skip it instead of printing the rain twice.
        if _report_key(c) in shown:
            continue
        if _is_weather((c.get("text") or "")
                        if isinstance(c, dict) else str(c)):
            continue
        lines.append(f"  - combat: {_report_line(c)}")
    return "\n".join(lines), f"{len(anns)} announcements"


def _areas_list(areas: Any) -> Optional[list[dict[str, Any]]]:
    """Normalise the areas argument to a list (or None).

    Callers pass the areas list, but the spatial cache holds the
    full derivation dict (areas + graph + surface_blocks + ...);
    accepting the dict here too means a caller that passes the
    cache dict cannot break the snapshot with a KeyError from
    slicing a dict (2026-11-26).
    """
    if areas is None:
        return None
    if isinstance(areas, dict):
        return areas.get("areas")
    return areas


def _areas(areas: Optional[list[dict[str, Any]]],
           survey: Optional[dict[str, Any]]) -> tuple[str, str]:
    areas = _areas_list(areas)
    if areas is None:
        return ("Areas: unavailable (not derived yet).",
                "unavailable")
    lines = [f"Areas ({len(areas)}):"]
    for a in areas[:MAX_AREAS]:
        b = a["bbox"]
        lines.append(f"  - {a['name']} ({a['kind']}): "
                     f"x{b['x0']}..x{b['x1']}, y{b['y0']}..y{b['y1']}, "
                     f"z{b['z0']}..z{b['z1']}.")
    if len(areas) > MAX_AREAS:
        lines.append(f"  ... and {len(areas) - MAX_AREAS} more.")
    if survey is not None:
        summary = survey.get("summary") or []
        if summary:
            lines.append("  Survey: " + " ".join(summary[:3]))
    return "\n".join(lines), f"{len(areas)} areas"


def _events(events: Optional[list[dict[str, Any]]]
            ) -> tuple[str, str]:
    if not events:
        return "Events: nothing new.", "0 events"
    # P0 first (priority ascending), most recent first.
    ordered = sorted(
        events, key=lambda e: (e.get("priority", 99),
                               -(e.get("tick") or 0)))[:MAX_EVENTS]
    lines = ["Events (most urgent first):"]
    for e in ordered:
        lines.append(f"  [P{e.get('priority', '?')}] "
                     f"{e.get('type')}: {e.get('text', '')}")
    return "\n".join(lines), f"{len(events)} events"


def _history(decisions: Optional[list[dict[str, Any]]]
             ) -> tuple[str, str]:
    if not decisions:
        return "Recent history: no decisions recorded yet.", "0"
    lines = ["Recent decisions (did they work?):"]
    for d in decisions[-MAX_HISTORY:]:
        outcome = d.get("outcome") or d.get("result") or "unknown"
        lines.append(f"  - {d.get('summary') or d.get('name')}: "
                     f"{outcome}")
    return "\n".join(lines), f"{len(decisions)} decisions"


def _has_workshop(state: dict[str, Any], subtype: str) -> bool:
    """True if a workshop of the given subtype exists in state.

    Buildings in the snapshot state are type=="Workshop" with a
    subtype (e.g. "Still", "Carpenters"). Used by suggest() so the
    low-drink suggestion can name the still build when no still
    exists, instead of pointing at the brew task (which fails
    without one).
    """
    buildings = state.get("buildings") or {}
    lst = buildings.get("list") or []
    return any(
        b.get("type") == "Workshop" and b.get("subtype") == subtype
        for b in lst)


def _free_workshop_site(
        sites: Optional[dict[str, Any]]) -> Optional[tuple[int, int, int]]:
    """First probe-verified free workshop site, or None.

    The daemon's derived sites dict has "workshop_sites": a list
    of (x, y, z) 3x3 origins. The suggestion names the first one
    so the model has a concrete build coordinate.
    """
    if not sites:
        return None
    for pos in sites.get("workshop_sites") or []:
        if isinstance(pos, (list, tuple)) and len(pos) == 3:
            return (int(pos[0]), int(pos[1]), int(pos[2]))
    return None


def _material_blocker_suggestion(
        state: dict[str, Any], what: str) -> Optional[str]:
    """The gathering fix as a suggestion, when the action ``what``
    ("brew" or "still") is blocked by a material shortage — so the
    suggestion never points at a job the fort cannot run. Returns
    None when the materials are covered (or unknown).
    General material awareness (2026-11-27): the model must know it
    needs more materials BEFORE it acts, not after a failure."""
    from . import materials as _materials_mod
    stocks = state.get("stocks")
    buildings = state.get("buildings")
    if not isinstance(stocks, dict):
        return None
    if not isinstance(buildings, dict):
        buildings = {}
    if what == "brew":
        # Brews already queued hold a barrel + plant each (run #12:
        # 4 brews against 2 empty barrels) — the suggestion must
        # not point at a brew the fort cannot run.
        already_queued = (
            _materials_mod.queued_count(
                state.get("jobs"), 211, "BREW_DRINK_FROM_PLANT")
            + _materials_mod.queued_count(
                state.get("jobs"), 211, "BREW_DRINK_FROM_PLANT_GROWTH"))
        shortages = _materials_mod.check_job(
            "brew", stocks, count=1, buildings=buildings,
            already_queued=already_queued)
        if not shortages:
            return None
        fixes = "; ".join(_materials_mod.format_shortage(s)
                          for s in shortages)
        return (f"Suggested action: gather the brewing materials "
                f"first — {fixes}. Only then run the brew task "
                f"(POST /v1/tasks/brew).")
    if what == "still":
        shortages = _materials_mod.check_workshop(
            "still", stocks, buildings)
        if not shortages:
            return None
        fixes = "; ".join(_materials_mod.format_shortage(s)
                          for s in shortages)
        return (f"Suggested action: gather building material first "
                f"— {fixes}. Only then build the still.")
    return None


def _has_farm_plot(state: dict[str, Any]) -> bool:
    """True when a FarmPlot building exists (built or building)."""
    for b in (state.get("buildings") or {}).get("list") or []:
        if b.get("type") == "FarmPlot":
            return True
    return False


def _still_build_suggestion(
        sites: Optional[dict[str, Any]]) -> str:
    """The still-build suggestion text (shared by the low-drink
    branch and the proactive fallback). Names a concrete free site
    when one is known."""
    site = _free_workshop_site(sites)
    at = (f" at {site[0]}, {site[1]}, {site[2]}"
          if site else "")
    return ("Suggested action: NO STILL EXISTS, so "
            "brewing is impossible until you build one. "
            "Build a still FIRST: build_workshop "
            f"kind=still{at} (a probe-verified free 3x3 "
            "site). If the build reports 'site not free', "
            "gather the blocking plant or use the next "
            "free site. Only then run the brew task.")


def suggest(state: dict[str, Any],
            attention_items: list[dict[str, Any]],
            sites: Optional[dict[str, Any]] = None) -> Optional[str]:
    """The ONE suggested action for the single most urgent problem.

    Names the exact tool + parameters + the reason in game terms.
    A default, not an instruction: the agent may accept, modify,
    or reject it. No suggestion when nothing is urgent. The mapping
    is explicit and small — it only suggests actions the harness
    can actually do (the daemon's tasks + the query tools).

    Scans the attention list in priority order and returns the
    first actionable item: the top item alone is not enough, since
    a non-actionable item (e.g. a new arrival) can sit above a
    critical one (e.g. low drink) and mask it.

    ``sites`` (the daemon's derived sites, probe-verified free
    workshop sites) supplies a concrete build coordinate when the
    suggestion is to build a still. Without one the model stalls:
    M1 run #6, "the observation gives no free ground
    coordinates".
    """
    for item in attention_items or []:
        kind = item.get("kind")
        text = item.get("text", "")
        # A hostile is the most urgent problem: look at it first.
        if kind == "threat" and item.get("unit_id") is not None:
            return (f"Suggested action: query unit {item['unit_id']} "
                    f"to see what it is and where it is going — "
                    f"{text}")
        # Low drink: brew — BUT the brew task needs a still to
        # already exist (it fails "no still workshop exists" without
        # one). M1 run #4 proved the gap: the model enabled brewers
        # and gathered plants but never built the still, because the
        # suggestion only ever said "run the brew task". So when no
        # still exists, the suggestion must name the still build
        # itself, first, and only then the brew task.
        if "drink" in text.lower() or "thirst" in text.lower():
            if not _has_workshop(state, "Still"):
                blocked = _material_blocker_suggestion(state, "still")
                if blocked is not None:
                    return blocked
                return _still_build_suggestion(sites)
            blocked = _material_blocker_suggestion(state, "brew")
            if blocked is not None:
                return blocked
            return ("Suggested action: run the brew task "
                    "(POST /v1/tasks/brew) — the fort is short on "
                    "drink and brewing turns plants into drink.")
        if "food" in text.lower() or "hunger" in text.lower():
            return ("Suggested action: run the cook task "
                    "(POST /v1/tasks/cook) — the fort is short on food.")
    # Proactive fallback: no attention item fired, but there is no
    # still and drink is finite. A fort with no still can never
    # make more drink, so building one is the top priority well
    # before drink hits the attention warn threshold (20): M1 run
    # #7 tick 1 stalled at drink 32 with no suggestion and no site
    # coordinate. The 50 bound is ~10 days at the measured ~5/day
    # burn — enough lead time to build + gather + brew before
    # drink runs out. Threats and low-drink/food items above take
    # precedence; this only fires when nothing else did.
    if not _has_workshop(state, "Still"):
        drink = (state.get("stocks") or {}).get("drink_units")
        if isinstance(drink, int) and drink < 50:
            blocked = _material_blocker_suggestion(state, "still")
            if blocked is not None:
                return blocked
            return _still_build_suggestion(sites)
    # Proactive brew: a still exists, but drink is finite and
    # falling, and no low-drink attention item fired (drink is
    # above the attention warn threshold of 20). Without this the
    # model builds the still and then drifts — M1 runs #15 and
    # #16b both built the still, queued barrels and beds, and
    # never brewed, while drink fell 38 -> 34. The same 50 bound
    # as the still fallback: ~10 days at ~5/day burn. Only fires
    # when another brew is actually possible (the blocker check
    # accounts for brews already queued, so it never points at a
    # brew the fort cannot run). Once drink is >= 50 the
    # suggestion stops and the model is free for other work.
    if _has_workshop(state, "Still"):
        drink = (state.get("stocks") or {}).get("drink_units")
        if isinstance(drink, int) and drink < 50:
            blocked = _material_blocker_suggestion(state, "brew")
            if blocked is not None:
                return blocked
            return ("Suggested action: run the brew task "
                    "(POST /v1/tasks/brew) — the still is built "
                    "and drink is finite; brewing turns plants "
                    "into drink before the stock runs out.")
    # Proactive farm: no farm plot exists, but the fort holds seeds.
    # category_stacks.SEEDS is the raw game-category count — it
    # includes seeds still in the wagon, unlike seeds_stacks, so
    # this fires on a fresh fort too. A fort that only gathers will
    # run out of plants; a farm grows plump helmets underground and
    # surface crops in the sun. Fires only when nothing more urgent
    # did — farming is growth, not survival. The farm_site
    # coordinate is area-derived, not probe-verified; the build
    # action re-verifies the site and names a verified alternative
    # when it is not free.
    if not _has_farm_plot(state):
        seeds = ((state.get("stocks") or {}).get("category_stacks")
                 or {}).get("SEEDS")
        if isinstance(seeds, int) and seeds > 0:
            farm_site = None
            if sites:
                fs = sites.get("farm_site")
                if isinstance(fs, (list, tuple)) and len(fs) == 3:
                    farm_site = (int(fs[0]), int(fs[1]), int(fs[2]))
            at = (f" at {farm_site[0]}, {farm_site[1]}, {farm_site[2]}"
                  if farm_site else "")
            return ("Suggested action: NO FARM PLOT EXISTS, so the "
                    "fort cannot grow its own food. Build a farm "
                    "plot FIRST: build_farm_plot"
                    f"{at} (3x3; the build verifies the site and "
                    "names a verified alternative when it is not "
                    "free). Then run the farm task "
                    "(POST /v1/tasks/farm) — it picks a crop for the "
                    "plot's light and biome and plants it.")
    return None


def assemble(state: dict[str, Any],
             store: Optional[Store] = None,
             detector: Any = None,
             goals: Optional[list[dict[str, Any]]] = None,
             decisions: Optional[list[dict[str, Any]]] = None,
             events: Optional[list[dict[str, Any]]] = None,
             surface_z: Optional[int] = None,
             areas: Optional[list[dict[str, Any]]] = None,
             survey: Optional[dict[str, Any]] = None,
             sites: Optional[dict[str, Any]] = None,
             placement: Optional[dict[str, Any]] = None,
             accountant: Optional[TokenAccountant] = None
             ) -> dict[str, Any]:
    """Build the per-tick snapshot (text first, diff + index).

    Renders each section, diffs it against the Store's last
    snapshot for that section (an unchanged section renders as a
    one-liner), enforces the token cap with the cut order, and
    stores each section's full text as the next baseline. Returns
    {"text", "sections", "tokens", "wire_tokens", "tick", "cuts",
    "suggestion", "cost"}.
    """
    acct = accountant or TokenAccountant()
    status = state.get("status") or {}
    tick = status.get("year_tick")
    tick = tick if isinstance(tick, int) else 0

    # The attention items are computed once and shared by the
    # attention section and the suggestion. Always built — the
    # threats + stocks checks need no detector; only the arrivals
    # need one (and are skipped without it).
    att_items = build_attention(state, detector,
                                surface_z=surface_z)
    att_text, att_short = _attention_items(att_items)
    header_text, header_short = _header(state)
    goals_text, goals_short = _goals(goals)
    status_text, status_short = _status(state)
    stocks_text, stocks_short = _stocks(state, store, tick)
    materials_text, materials_short = _materials(state)
    units_text, units_short = _units(state)
    entities_text, entities_short = _entities(state)
    buildings_text, buildings_short = _buildings(state)
    jobs_text, jobs_short = _jobs(state)
    reports_text, reports_short = _reports(state)
    areas_text, areas_short = _areas(areas, survey)
    events_text, events_short = _events(events)
    history_text, history_short = _history(decisions)
    # Placement (verified free + reachable sites, compact): a few
    # named options per kind with what makes each one good — not a
    # dump of every free tile. The full detail lives behind
    # GET /v1/sites. The section is diffed like the others, so an
    # unchanged placement renders as a one-liner.
    placement_text, placement_short = _placement(placement)

    # The suggestion comes from the top attention item. The sites
    # (probe-verified free workshop sites, derived by the daemon)
    # give it a concrete build coordinate when it recommends a
    # still — without one the model stalls ("the observation gives
    # no free ground coordinates", M1 run #6).
    suggestion = suggest(state, att_items, sites=sites)

    sections = [
        _section("header", header_text, header_short, 99),
        _section("attention", att_text, att_short, 99),
        _section("goals", goals_text, goals_short, 80,
                 cut=lambda: ""),
        _section("status", status_text, status_short, 99),
        _section("stocks", stocks_text, stocks_short, 70,
                 cut=lambda: _stocks(state, None, tick)[0].split(
                     "\n")[0]),
        _section("materials", materials_text, materials_short, 65,
                 cut=lambda: ""),
        _section("units", units_text, units_short, 60,
                 cut=lambda: _units_compact(state)),
        _section("entities", entities_text, entities_short, 65,
                 cut=lambda: _entities_compact(state)),
        _section("buildings", buildings_text, buildings_short, 50,
                 cut=lambda: _buildings(state)[0].split("\n")[0]),
        _section("jobs", jobs_text, jobs_short, 55,
                 cut=lambda: _jobs(state)[0].split("\n")[0]),
        _section("reports", reports_text, reports_short, 40,
                 cut=lambda: _reports_trimmed(state)),
        _section("areas", areas_text, areas_short, 45,
                 cut=lambda: _areas_compact(areas, survey)),
        _section("placement", placement_text, placement_short, 55,
                 cut=lambda: ""),
        _section("events", events_text, events_short, 75,
                 cut=lambda: ""),
        _section("history", history_text, history_short, 30,
                 cut=lambda: ""),
    ]

    # Diffing: an unchanged section renders as a one-liner. The
    # full text is still stored as the next baseline. Threats,
    # attention, and failure feedback are never diffed away — the
    # attention section is always rendered in full.
    rendered: list[dict[str, Any]] = []
    for s in sections:
        full = s["text"]
        if store is not None and s["name"] not in ("attention",):
            prev = store.get_snapshot(s["name"])
            if prev is not None and prev["text"] == full:
                s["text"] = (f"{s['name']}: unchanged "
                             f"({s['short']}).")
                s["diffed"] = True
            else:
                s["diffed"] = False
            store.record_snapshot(tick, s["name"], full)
        else:
            s["diffed"] = False
        rendered.append(s)

    # Suggestion goes after attention, before the rest.
    if suggestion:
        rendered.insert(2, _section("suggestion", suggestion,
                                    "1 suggestion", 99))

    kept, cuts = acct.fit(rendered)
    text = "\n\n".join(s["text"] for s in kept if s.get("text"))
    tokens = acct.count(text)
    return {
        "text": text,
        "sections": {s["name"]: s["text"] for s in kept
                     if s.get("text")},
        "tokens": tokens,
        "wire_tokens": acct.wire_count(text),
        "tick": tick,
        # The in-game calendar date (e.g. "125-04-01"), as a field:
        # the M1 driver used to take it from the status section
        # text, which starts with "Population: ..." — the wrong
        # line (2026-11-26). A section's text is never a date.
        "date": (status.get("date") or "unknown date"),
        "cuts": cuts,
        "suggestion": suggestion,
        "cost": {"tokens": tokens,
                 "wire_tokens": acct.wire_count(text),
                 "ms": 0},
    }


def _units_compact(state: dict[str, Any]) -> str:
    """Units reduced to counts only (the cut-order compaction)."""
    units = state.get("units") or {}
    citizens = units.get("citizens") or []
    return f"Units: {len(citizens)} citizens (compacted to counts)."


def _entities_compact(state: dict[str, Any]) -> str:
    """Entities reduced to counts only."""
    units = state.get("units") or {}
    total = units.get("total_active_units")
    hostiles = units.get("hostiles") or []
    return (f"Entities: {total} active units, "
            f"{len(hostiles)} hostiles (compacted to counts).")


def _reports_trimmed(state: dict[str, Any]) -> str:
    """Reports reduced to the single newest announcement."""
    reports = state.get("reports") or {}
    anns = reports.get("announcements") or []
    if not anns:
        return "Reports: nothing new."
    return f"Reports: {_report_line(anns[-1])}"


def _areas_compact(areas: Optional[list[dict[str, Any]]],
                   survey: Optional[dict[str, Any]]) -> str:
    """Areas reduced to the count + the survey summary line."""
    areas = _areas_list(areas)
    if areas is None:
        return "Areas: unavailable (not derived yet)."
    out = f"Areas: {len(areas)} areas (compacted to the count)."
    if survey is not None:
        summary = survey.get("summary") or []
        if summary:
            out += " Survey: " + " ".join(summary[:2])
    return out


def sample_daily(state: dict[str, Any], store: Store) -> bool:
    """Sample trends + unit history once per in-game day.

    Called every tick; samples only when the day number
    (year_tick // 1200) has advanced past the last sampled day.
    Returns True when a sample was taken. Metrics: drink, food,
    wood, stone, population. Unit history: one row per citizen.
    """
    status = state.get("status") or {}
    tick = status.get("year_tick")
    if not isinstance(tick, int):
        return False
    day = tick // TICKS_PER_DAY
    # Reload check: if the current tick is BEHIND the last sampled
    # tick, the game was reloaded to an earlier save and the old
    # timeline is dead. Its samples would corrupt every burn rate
    # (the least-squares slope mixes two timelines — verified live
    # 2026-11-27: drink samples from the drink-0 timeline gave a
    # 0.3/day rate and "0.0 days left" while the real stock was 39)
    # and freeze sampling entirely (the day number went backwards,
    # so the day-advance check below never fires). Drop the whole
    # timeline — trends, unit history and deaths — and start fresh
    # (2026-11-27, external review Table 4 row 8: clearing only
    # the trends left the dead timeline's unit history and deaths
    # behind, so post-reload death diagnosis read future samples
    # from a timeline the fort no longer has).
    last = store.latest_sample_tick()
    if last is not None and tick < last:
        store.clear_timeline()
        last = None
    # The last sampled day is the max trend tick across ALL
    # metrics, not drink alone (2026-11-27, external review Table
    # 4 row 1): if the stocks section fails, no drink sample
    # lands and a drink-only gate never blocks — unit history
    # rewrites every tick, trends grow unbounded, and the per-day
    # diary write fires every tick. Any metric landing proves a
    # sample was taken that day.
    if last is not None and last // TICKS_PER_DAY >= day:
        return False
    stocks = state.get("stocks") or {}
    units = state.get("units") or {}
    citizens = units.get("citizens") or []
    pop = status.get("population") or {}
    metrics = {
        "drink": stocks.get("drink_units"),
        "food": stocks.get("food_units"),
        "wood": stocks.get("wood_units"),
        "stone": stocks.get("stone_units"),
        "population": len(citizens) or pop.get("citizens"),
    }
    for metric, val in metrics.items():
        if isinstance(val, (int, float)):
            store.sample_trend(tick, metric, float(val))
    # One sample per citizen (dwarves.record_citizens is the single
    # mapping from a live citizen record to a Store sample — the
    # diary write uses the same function to capture the run-end
    # state, since no samples are taken while the loop is paused).
    from .dwarves import record_citizens
    record_citizens(store, tick, citizens)
    return True
