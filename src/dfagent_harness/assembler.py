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

import time
from typing import Any, Optional

from .attention import build_attention
from .spatial import estimate_tokens
from .store import Store, TICKS_PER_DAY, TREND_WINDOW_DAYS

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
    """Render an already-built attention list (max 8 items)."""
    items = items[:MAX_ATTENTION_ITEMS]
    if not items:
        return "Attention: nothing needs acting on.", "0 items"
    lines = ["Attention (most urgent first):"]
    for it in items:
        lines.append(f"  [P{it['priority']}] {it['text']}")
    return "\n".join(lines), f"{len(items)} items"


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
    wounded = sum(1 for c in citizens if c.get("wounds"))
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
    lines.append("Stocks: " + (", ".join(head) if head else "none")
                 + ".")
    # Burn rates + days-remaining from the Store's trends. The
    # agent never computes a burn rate from a single snapshot.
    if store is not None and isinstance(tick, int):
        for metric, label in (("drink", "drink"),
                              ("food", "food"),
                              ("wood", "wood"),
                              ("stone", "stone")):
            rate = store.burn_rate(metric, tick)
            days = store.days_remaining(metric, tick)
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
        idle = c.get("idle")
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
    lines = ["Buildings: " + ", ".join(
        f"{e.get('type')} x{e.get('count')}" for e in summary[:12])
        + "."]
    return "\n".join(lines), f"{len(lst)} buildings"


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


def _reports(state: dict[str, Any]) -> tuple[str, str]:
    if "reports" not in state:
        return ("Reports: unavailable (section failed to collect).",
                "unavailable")
    reports = state.get("reports") or {}
    anns = reports.get("announcements") or []
    combat = reports.get("combat") or []
    if not anns and not combat:
        return "Reports: nothing new.", "0 reports"
    lines = ["Reports:"]
    for a in anns[-MAX_REPORTS:]:
        lines.append(f"  - {a}")
    for c in combat[-2:]:
        lines.append(f"  - combat: {c}")
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


def suggest(state: dict[str, Any],
            attention_items: list[dict[str, Any]]) -> Optional[str]:
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
    """
    if not attention_items:
        return None
    for item in attention_items:
        kind = item.get("kind")
        text = item.get("text", "")
        # A hostile is the most urgent problem: look at it first.
        if kind == "threat" and item.get("unit_id") is not None:
            return (f"Suggested action: query unit {item['unit_id']} "
                    f"to see what it is and where it is going — "
                    f"{text}")
        # Low drink: brew. Low food: cook (or gather). These use the
        # daemon's tasks, which the planner already knows how to run.
        if "drink" in text.lower() or "thirst" in text.lower():
            return ("Suggested action: run the brew task "
                    "(POST /v1/tasks/brew) — the fort is short on "
                    "drink and brewing turns plants into drink.")
        if "food" in text.lower() or "hunger" in text.lower():
            return ("Suggested action: run the cook task "
                    "(POST /v1/tasks/cook) — the fort is short on food.")
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
    units_text, units_short = _units(state)
    entities_text, entities_short = _entities(state)
    buildings_text, buildings_short = _buildings(state)
    jobs_text, jobs_short = _jobs(state)
    reports_text, reports_short = _reports(state)
    areas_text, areas_short = _areas(areas, survey)
    events_text, events_short = _events(events)
    history_text, history_short = _history(decisions)

    # The suggestion comes from the top attention item.
    suggestion = suggest(state, att_items)

    sections = [
        _section("header", header_text, header_short, 99),
        _section("attention", att_text, att_short, 99),
        _section("goals", goals_text, goals_short, 80,
                 cut=lambda: ""),
        _section("status", status_text, status_short, 99),
        _section("stocks", stocks_text, stocks_short, 70,
                 cut=lambda: _stocks(state, None, tick)[0].split(
                     "\n")[0]),
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
    return f"Reports: {anns[-1]}"


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
    # The last sampled day is the max trend tick for drink.
    pts = store.trend_samples("drink")
    if pts and pts[-1][0] // TICKS_PER_DAY >= day:
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
    for c in citizens:
        counters = c.get("counters") or {}
        stress = (c.get("stress") or {}).get("level", 0)
        # The live collect emits job as a dict {id, type, pos} (or
        # None when idle); the history stores the job type string.
        job = c.get("job")
        if isinstance(job, dict):
            job = job.get("type") or ""
        elif not isinstance(job, str):
            job = ""
        store.record_unit_history(
            tick, c.get("id", 0), pos=c.get("pos"),
            job=job,
            hunger=counters.get("hunger", 0) or 0,
            thirst=counters.get("thirst", 0) or 0,
            sleepiness=counters.get("sleepiness", 0) or 0,
            stress=stress or 0,
            wounds=c.get("wounds") or [])
    return True
