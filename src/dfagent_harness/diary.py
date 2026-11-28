"""The diary (GOAL.md step 4): one entry per in-game day, written
from the fort overseer's perspective, stored as markdown in the
daemon state dir, and rendered as a single self-contained DF-themed
HTML file (diary.html).

The diary is the narrative rendering of the daily rolling summary
that the memory system already plans — not a new system, the same
synthesis in story form. The hard rule is grounding: every claim in
an entry must trace to a recorded event, decision, or observation.
The entry is built ONLY from the State Store (trends, unit history,
deaths) and the planner Journal (decisions, daemon events) for that
day's tick range, so it cannot invent events that did not happen.
The daemon triggers it at the day boundary (year_tick rollover) as
part of the tick, outside the decision loop, so it never slows play.

diary.md is the source of truth; diary.html is the generated view,
re-generated after each new entry and on demand. The HTML is one
file, no server: CP437 pixel font, the 16-colour DF palette, ASCII
box-drawing borders, and the classic DF screen layout (header bar
with fort name and date, an index pane of entries by in-game date,
a main reading pane). It indexes all entries with click-to-read,
prev/next day, and jump-to-latest.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from .day_events import read_day_events, read_workshop_map
from .dwarves import (FEATURE_THRESHOLD, JOB_VERBS,
                      diff_unit_samples, dwarf_record, job_words,
                      recent_emotions, salient_traits, social_ties)
from .materials import JOB_MATERIALS

# DF calendar: 12 months of 28 days, 1,200 ticks/day, 33,600
# ticks/month, 403,200 ticks/year. Year 1 starts at tick 0.
TICKS_PER_DAY = 1200
TICKS_PER_MONTH = 33600
TICKS_PER_YEAR = 403200

MONTHS = ("Granite", "Slate", "Felsite", "Hematite", "Malachite",
          "Galena", "Limestone", "Sandstone", "Timber", "Moonstone",
          "Opal", "Obsidian")

SEASONS = ("Spring", "Spring", "Spring", "Summer", "Summer", "Summer",
           "Autumn", "Autumn", "Autumn", "Winter", "Winter", "Winter")

# The 16-colour DF palette (vga text colours), as used by the game.
DF_PALETTE = {
    "black": "#000000", "blue": "#0000AA", "green": "#00AA00",
    "cyan": "#00AAAA", "red": "#AA0000", "magenta": "#AA00AA",
    "brown": "#AA5500", "lightgray": "#AAAAAA",
    "darkgray": "#555555", "lightblue": "#5555FF",
    "lightgreen": "#55FF55", "lightcyan": "#55FFFF",
    "lightred": "#FF5555", "lightmagenta": "#FF55FF",
    "yellow": "#FFFF55", "white": "#FFFFFF",
}


def date_of_tick(tick: int, year: int = 0) -> tuple[int, int, int]:
    """(year, month, day) for a year_tick. ``tick`` is the tick
    within the current year (0..403199); ``year`` is the calendar
    year from the status (cur_year), since year_tick alone does not
    carry it."""
    month = tick // TICKS_PER_MONTH + 1
    day = (tick % TICKS_PER_MONTH) // TICKS_PER_DAY + 1
    return year, month, day


def date_str(tick: int, year: int = 0) -> str:
    """'125-06-02' for a year_tick + year (the observe status
    format)."""
    y, m, d = date_of_tick(tick, year)
    return f"{y}-{m:02d}-{d:02d}"


def _ordinal(n: int) -> str:
    """English ordinal suffix: 1st, 2nd, 3rd, 4th, 11th, 12th, 13th,
    21st, 22nd, 23rd. The old table ({1: "st", 2: "nd", 3: "rd"})
    gave "22th" — 21/22/23 need the same suffixes as 1/2/3, and
    11/12/13 are always "th"."""
    if 11 <= n % 100 <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def date_words(tick: int, year: int = 0) -> str:
    """'2nd of Galena, 125' for a year_tick + year."""
    y, m, d = date_of_tick(tick, year)
    return f"{d}{_ordinal(d)} of {MONTHS[m - 1]}, {y}"


def season_of_tick(tick: int) -> str:
    return SEASONS[date_of_tick(tick)[1] - 1]


def day_range(day_start_tick: int) -> tuple[int, int]:
    """(first, last) year_tick of the day starting at day_start_tick
    (which must be a multiple of TICKS_PER_DAY)."""
    return day_start_tick, day_start_tick + TICKS_PER_DAY - 1


# ----------------------------------------------------------------------
# The diary text boundary (quality pass, 2026-11-27).
#
# The diary only ever receives cleaned, overseer-facing text. Raw
# tool output, internal references and diagnostic prose are stopped
# HERE, at the data boundary — never rendered and never patched over
# afterwards. Three typed inputs, three renderers; nothing is
# concatenated blindly into "I decided to ...".
# ----------------------------------------------------------------------

#: Journal decision actions that are diagnostics, not decisions.
#: A "log" decision is the planner noting something (a dwarf in
#: distress, a threat) — it is routed to the observation renderer,
#: never rendered as "I decided to ...".
LOG_ACTIONS = frozenset({"log"})

#: Daemon event kinds the diary renders as lines. Everything else
#: is a harness operation (pause_guard, dialog_dismissed, snapshot,
#: daemon_loop_paused, ...) and never reaches the diary — the diary
#: is the fort's story, not the harness's log. Arrivals and threats
#: are counted above, not rendered here. Fort-event kinds added by
#: later systems (mood, flood) go in this set when they land.
RENDERABLE_EVENT_KINDS = frozenset()

#: Markers of harness-internal text. A parenthetical carrying one
#: is stripped; a bare one outside a parenthetical drops the whole
#: piece (better to lose a sentence than print harness internals
#: in the overseer's diary).
_PAREN_MARKERS = ("see ", "logged", "verified live", ".md",
                  "display :", "keystroke", "Traceback", "read-back",
                  "no Dwarf Fortress window", "jobs [-1")
_BARE_MARKERS = (".md", "display :", "keystroke", "Traceback",
                 "read-back", "no Dwarf Fortress window", "jobs [-1",
                 "Error:", "verified live")


def clean_diary_text(text: Any) -> str:
    """Strip internal debris from a piece of diary text. Returns ""
    when the piece is dropped entirely."""
    if not isinstance(text, str):
        return ""
    # Drop parentheticals that carry an internal marker.
    def _drop_group(m: Any) -> str:
        inner = m.group(0)
        if any(marker.lower() in inner.lower()
               for marker in _PAREN_MARKERS):
            return ""
        return inner
    text = re.sub(r"\([^()]*\)", _drop_group, text)
    # A bare marker outside a parenthetical drops the whole piece.
    low = text.lower()
    if any(marker.lower() in low for marker in _BARE_MARKERS):
        return ""
    # Tidy up: collapse spaces, drop a dangling dash or comma.
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+—\s*$", "", text).strip()
    text = re.sub(r"\s*,\s*$", "", text).strip()
    return text


_DISTRESS_RE = re.compile(
    r"(\d+) citizen\(s\) past a distress line: (.+?)(?: — |$)")
_NEED_RE = re.compile(r"^(.+?) \(([^)]+)\)$")


def parse_distress_pairs(reason: Any) -> list[tuple[str, str]]:
    """A planner distress diagnostic as (dwarf name, need) pairs.
    "1 citizen(s) past a distress line: Olon Medtobalod (thirsty),
    ... — <advice>; <note>" -> [("Olon Medtobalod", "thirsty")].
    The advice and the internal note after the dash are planner
    guidance, not story, and are dropped. [] when the reason is
    not a distress diagnostic."""
    if not isinstance(reason, str):
        return []
    m = _DISTRESS_RE.search(reason)
    if not m:
        return []
    pairs = []
    for part in m.group(2).split(", "):
        nm = _NEED_RE.match(part.strip())
        if nm:
            pairs.append((nm.group(1), nm.group(2)))
    return pairs


def parse_distress(reason: Any) -> str | None:
    """A planner distress diagnostic as an overseer's observation.
    "15 citizen(s) past a distress line: Udil (thirsty), ... —
    <advice>; <note>" -> "15 dwarves were in distress, all thirsty."
    The advice and the internal note after the dash are planner
    guidance, not story, and are dropped. Returns None when the
    reason is not a distress diagnostic."""
    pairs = parse_distress_pairs(reason)
    if not pairs:
        return None
    needs = sorted({need for _, need in pairs})
    if len(pairs) == 1:
        return f"{pairs[0][0]} was in distress, {needs[0]}."
    if len(needs) == 1:
        return f"{len(pairs)} dwarves were in distress, all {needs[0]}."
    return (f"{len(pairs)} dwarves were in distress "
            f"({', '.join(needs)}).")


# A queue_job decision phrase, as diary_decision_text builds it:
# "queue make_bed x1 at building #7" or "queue make_bed x1 at
# the Carpenters workshop #7". The feed aggregates queued jobs by
# (workshop, job) instead of deduping them, so two x1 queues are
# two jobs, not one story beat.
_QUEUE_PHRASE = re.compile(r"^queue (\S+) x(\d+) at (.+)$")

# A queue-job token as a gerund, for what a completion at a
# workshop reads as: "brew" -> "brewing", "make_bed" -> "making
# a bed". The queue tokens are snake_case reaction/job names;
# the gerund is what the model needs — job_words alone says
# "working a reaction" for a CustomReaction, which is how the
# 04-02 entry ended up claiming "the beds want stone".
_QUEUE_GERUND = {
    "brew": "brewing",
    "cook": "cooking",
}


def _queue_job_phrase(job: str) -> str:
    """A queue-job token as a gerund phrase ("brewing",
    "making a bed"). Unknown tokens fall back to job_words."""
    if job in _QUEUE_GERUND:
        return _QUEUE_GERUND[job]
    if job.startswith("make_"):
        return "making a " + job[5:].replace("_", " ")
    return job_words(job) or job


def _workshop_display(kind: str) -> str:
    """A workshop kind as the prompt names it ("the still",
    "the carpenter's workshop")."""
    if kind == "still":
        return "the still"
    if kind == "carpenter":
        return "the carpenter's workshop"
    return f"the {kind} workshop"


def _completion_phrase(job: str, pos, workshop_map,
                       queue_kinds) -> str:
    """What a completion reads as in the prompt.

    job_words alone says "finished working a reaction" for a
    CustomReaction and "finished constructing a building" for a
    ConstructBuilding — true, but the model cannot tell brewing
    from bed-making. The position joins the workshop map
    (run-log build actions) and the day's queue:
      CustomReaction at a mapped workshop, one queued kind
        -> the gerund ("brewing", "making a bed")
      CustomReaction at a mapped workshop, several queued kinds
        -> "work at the {workshop}" (the kind is not knowable)
      CustomReaction at an unmapped position
        -> "a workshop job" (vague, true)
      ConstructBuilding at a mapped workshop
        -> "the still" (the workshop that was built)
      anything else -> job_words, as before.
    workshop_map is {pos tuple: {id, kind}}; queue_kinds is
    {building id: set of queue-job tokens}. A completion's pos is
    a list (or None); a job id is never used here — ids are
    reused across types and days, so they cannot name a job."""
    ws = None
    if pos is not None:
        ws = workshop_map.get(tuple(pos))
    if job == "CustomReaction" and ws is not None:
        kinds = queue_kinds.get(ws["id"]) or set()
        if len(kinds) == 1:
            return _queue_job_phrase(next(iter(kinds)))
        if len(kinds) > 1:
            return "work at " + _workshop_display(ws["kind"])
        return "a workshop job"
    if job == "CustomReaction":
        return "a workshop job"
    if job == "ConstructBuilding" and ws is not None:
        return _workshop_display(ws["kind"])
    return job_words(job) or job


def _queue_groups_and_phrases(summary: dict[str, Any]
                              ) -> tuple[list[str],
                                         dict[str, list[tuple[str, int, str]]],
                                         list[str]]:
    """The day's decisions as prompt phrases, with queue_job
    decisions grouped by workshop instead of listed one by one.
    Returns (dec_phrases, queue_groups, queue_order): the groups
    are {loc: [(job token, count, outcome)]} in first-seen order.
    A job that did not work keeps its outcome on its own item.
    This is the one place the queue phrases are parsed — the
    events section reads the groups (for the completion-phrase
    resolver) and the "What I did today" section renders them,
    so both agree on what was queued where.
    Each group also carries its materials, from JOB_MATERIALS
    with the day-start stocks as the have: "Queued at the
    Carpenters workshop #7: make_bed x5, make_barrel x2 (7 jobs
    total; needs 7 wood, have 117)". The have is the day-start
    stock (what the fort had when the queue was made), falling
    back to the day-end stock. A material the feed has no count
    for (brewable plants, empty barrels, food stacks — the
    summary stocks carry only drink/food/wood/stone/population)
    renders its need with no have, never a guessed number.
    That is the real fix for the 04-02 "the beds want stone"
    invention: the model reads the need from the feed instead of
    guessing it, and a bed needs wood, not stone."""
    dec_phrases: list[str] = []
    queue_groups: dict[str, list[tuple[str, int, str]]] = {}
    queue_order: list[str] = []
    for dec in summary.get("decisions") or []:
        phrase = clean_diary_text(
            dec.get("decision") or dec.get("action") or "")
        if not phrase:
            continue
        outcome = ("worked" if dec.get("ok") is True
                   else "did not work" if dec.get("ok") is False
                   else "outcome unknown")
        if dec.get("action") == "queue_job":
            m = _QUEUE_PHRASE.match(phrase)
            if m:
                loc = m.group(3)
                if loc not in queue_groups:
                    queue_groups[loc] = []
                    queue_order.append(loc)
                queue_groups[loc].append(
                    (m.group(1), int(m.group(2)), outcome))
                continue
        dec_phrases.append(f"{phrase} ({outcome})")
    for loc in queue_order:
        jobs = queue_groups[loc]
        total = sum(n for _, n, _ in jobs)
        job_bits = ", ".join(
            f"{j} x{n}" if o == "worked" else f"{j} x{n} ({o})"
            for j, n, o in jobs)
        mat_bit = _queue_materials_bit(
            jobs, summary.get("stocks_start")
            or summary.get("stocks_end") or {})
        dec_phrases.append(
            f"Queued at {loc}: {job_bits} ({total} job"
            f"{'s' if total > 1 else ''} total{mat_bit})")
    return dec_phrases, queue_groups, queue_order


# JOB_MATERIALS stock keys to the summary stocks' keys, and the
# singular/plural the prompt uses. The summary stocks carry only
# drink/food/wood/stone/population, so brewable plants, empty
# barrels, and food stacks have no have-number — their need
# renders alone, never with a guessed count.
_MATERIAL_STOCK_KEY = {
    "wood_units": "wood",
    "stone_units": "stone",
}
_MATERIAL_NAMES = {
    "wood_units": ("wood", "wood"),
    "stone_units": ("stone", "stone"),
    "brewable_plants": ("brewable plant", "brewable plants"),
    "empty_barrels": ("empty barrel", "empty barrels"),
    "food_stacks": ("food stack", "food stacks"),
}


def _queue_materials_bit(jobs: list[tuple[str, int, str]],
                         stocks: dict[str, Any]) -> str:
    """The materials bit for one queue group: "; needs 7 wood
    (have 117)" or "; needs 2 brewable plants + 2 empty barrels"
    or "" when no queued job has a materials row. The need is the
    per-job requirement times the count, summed across the
    group's jobs (5 beds + 2 barrels = 7 wood). The have is the
    day-start stock when the summary carries it; a material with
    no summary count renders its need with no have."""
    needs: dict[str, int] = {}
    for job, count, _outcome in jobs:
        for req in JOB_MATERIALS.get(job) or []:
            stock = req.get("stock") or ""
            if stock not in _MATERIAL_NAMES:
                continue
            per = req.get("per_job") or 0
            if not isinstance(per, int) or per <= 0:
                continue
            needs[stock] = needs.get(stock, 0) + count * per
    if not needs:
        return ""
    bits = []
    for stock, need in needs.items():
        singular, plural = _MATERIAL_NAMES[stock]
        name = singular if need == 1 else plural
        summary_key = _MATERIAL_STOCK_KEY.get(stock)
        have = stocks.get(summary_key) if summary_key else None
        if isinstance(have, int):
            bits.append(f"{need} {name} (have {have})")
        else:
            bits.append(f"{need} {name}")
    return "; needs " + " + ".join(bits)


def _finalize_decisions(decisions: list[dict[str, Any]]
                        ) -> tuple[list[dict[str, Any]],
                                   list[str]]:
    """Split a day's decision records into (decisions, observations)
    and deduplicate the decisions.

    * Log/diagnostic records are not decisions: a distress
      diagnostic becomes an observation sentence, anything else
      diagnostic is dropped.
    * A decision phrase that does not survive cleaning is dropped.
    * The planner re-decides the same thing every tick at a frozen
      game tick, so the same phrase repeated 30 times is ONE story
      beat, not 30. A repeated decision whose outcome CHANGED
      (failed, then worked) is kept a second time, flagged as a
      retry — the outcome changing is a story beat. At most one
      keep per (phrase, outcome): an outcome that oscillates
      (failed, worked, failed, worked) is told once per outcome,
      not once per flip — the diary is a story, not a tick log.
    * ok is normalized here (the Journal stores it as a SQLite
      int 0/1, the driver passes a bool): after this, ok is
      True/False/None, so the renderer sees the outcomes. An
      outcome-less repeat never creates a beat — it adds nothing
      to a decision already told.
    * queue_job decisions AGGREGATE instead of deduping: two
      "queue make_bed x1 at building #7" actions are two beds
      queued, not one. They group by (workshop, job, outcome),
      summing the counts, so the feed can say "make_bed x2" and
      the diary cannot compress two different jobs into "set one
      job running". A group whose outcome changed is kept a
      second time, flagged as a retry, like any other decision.

    Idempotent: re-finalizing an already-finalized list changes
    nothing (the log records are already gone, the dedup is
    stable, and an aggregated phrase re-parses to the same
    group)."""
    kept: list[dict[str, Any]] = []
    kept_ok: dict[str, set] = {}
    observations: list[str] = []
    queue_groups: dict[tuple, dict[str, Any]] = {}
    queue_counts: dict[tuple, int] = {}
    for dec in decisions or []:
        action = dec.get("action") or ""
        if action in LOG_ACTIONS:
            obs = parse_distress(dec.get("reason") or "")
            if obs and obs not in observations:
                observations.append(obs)
            continue
        phrase = clean_diary_text(
            dec.get("decision") or action or "")
        if not phrase:
            continue
        ok = dec.get("ok")
        ok = None if ok is None else bool(ok)
        if action == "queue_job":
            m = _QUEUE_PHRASE.match(phrase)
            if m:
                job, count, loc = (m.group(1), int(m.group(2)),
                                   m.group(3))
                key = (loc, job, ok)
                if key in queue_groups:
                    queue_counts[key] += count
                    queue_groups[key]["decision"] = (
                        f"queue {job} x{queue_counts[key]} "
                        f"at {loc}")
                    continue
                entry = dict(dec)
                entry["decision"] = phrase
                entry["ok"] = ok
                if any(k[0] == loc and k[1] == job
                       for k in queue_groups):
                    entry["retry"] = True
                queue_groups[key] = entry
                queue_counts[key] = count
                kept.append(entry)
                continue
        oks = kept_ok.setdefault(phrase, set())
        if ok in oks:
            continue  # same decision, same outcome — already told
        if ok is None and oks:
            continue  # unknown outcome on a decision already told
        oks.add(ok)
        entry = dict(dec)
        entry["decision"] = phrase
        entry["ok"] = ok
        if len(oks) > 1:
            entry["retry"] = True
        kept.append(entry)
    return kept, observations


def ledger_stocks(body: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """Parse the ledger line of an existing diary entry body back
    into (stocks_start, stocks_end). The ledger is a recorded fact
    — it was rendered from live samples — so a rebuild recovers the
    numbers from it when the Store no longer has samples for that
    day (old samples were cleared). Accepts the old "Souls" label
    as well as "Citizens". Returns ({}, {}) when there is no ledger
    line."""
    labels = {"Drink": "drink", "Food": "food", "Wood": "wood",
              "Stone": "stone", "Citizens": "population",
              "Souls": "population"}
    start: dict[str, Any] = {}
    end: dict[str, Any] = {}
    for label, metric in labels.items():
        m = re.search(rf"{label}: (\d+)(?: -> (\d+))?", body or "")
        if not m:
            continue
        start[metric] = int(m.group(1))
        end[metric] = int(m.group(2)) if m.group(2) else int(m.group(1))
    return start, end


# ----------------------------------------------------------------------
# Daily summary: the recorded facts for one in-game day.
# ----------------------------------------------------------------------

def build_daily_summary(store: Any, journal: Any,
                        day_start_tick: int,
                        fort_name: str = "",
                        year: int = 0) -> dict[str, Any]:
    """Build the structured summary for the day starting at
    day_start_tick, from the State Store + the planner Journal only.
    ``day_start_tick`` is a year_tick; ``year`` is the calendar year
    from the status. Every field traces to a recorded row; nothing
    is inferred beyond the Store's own trend/death diagnosis.
    Returns a dict the diary renderer turns into an entry."""
    first, last = day_range(day_start_tick)
    summary: dict[str, Any] = {
        "tick_start": first, "tick_end": last,
        "date": date_str(first, year),
        "date_words": date_words(first, year),
        "season": season_of_tick(first), "fort_name": fort_name,
        "stocks_start": {}, "stocks_end": {},
        "deaths": [], "decisions": [], "events": [],
        "observations": [],
        # Distress as structured pairs, not only as an observation
        # sentence: the feed attaches each pair to the named
        # dwarf's record (audit R4 — a "Noted:" line alone was
        # dropped by the model on 06-28, while the manager and
        # stockpile attempts beside it were kept).
        "distress": [],
        "arrivals": 0, "threats": 0,
    }
    # Stocks at the day boundaries, from the trend samples (one per
    # day, taken when the daemon's tick first runs that day — so the
    # sample's tick is inside the day, not at its start). Start =
    # the last sample at or before the day start, else the first
    # sample inside the day. End = the last sample at or before the
    # next day's start (the next day's sample when the fort has run
    # another day), else the last sample inside the day.
    for metric in ("drink", "food", "wood", "stone", "population"):
        pts = store.trend_samples(metric)
        start = None
        end = None
        for tick, val in pts:
            if tick <= first and (start is None or tick > start[0]):
                start = (tick, val)
            if tick <= last + TICKS_PER_DAY and (
                    end is None or tick > end[0]):
                end = (tick, val)
        if start is None:
            for tick, val in pts:
                if first <= tick <= last:
                    start = (tick, val)
                    break
        if start is not None:
            summary["stocks_start"][metric] = start[1]
        if end is not None:
            summary["stocks_end"][metric] = end[1]
    # Deaths in the day, with the Store's diagnosis attached.
    for death in store.deaths():
        tick = death.get("tick")
        if isinstance(tick, int) and first <= tick <= last:
            summary["deaths"].append({
                "tick": tick, "unit_id": death.get("unit_id"),
                "cause": death.get("cause"),
                "history_ref": death.get("history_ref"),
            })
    # Decisions + daemon events in the day, from the Journal.
    # Decisions carry a year (the Journal is shared across forts,
    # so a tick range alone would mix Athelunol's year-306 decisions
    # into Erushtathtat's year-125 diary). Daemon events have no
    # year column, so they filter by tick range only.
    for dec in journal.recent_decisions(limit=10000):
        tick = dec.get("tick")
        if not isinstance(tick, int) or not (first <= tick <= last):
            continue
        if dec.get("year") is not None and dec.get("year") != year:
            continue
        summary["decisions"].append({
            "decision": dec.get("decision"),
            "reason": dec.get("reason"),
            "action": dec.get("action"),
            "domain": dec.get("domain"),
            "ok": dec.get("ok"),
            "result": dec.get("result"),
        })
    for ev in journal.recent_events(limit=10000):
        tick = ev.get("tick")
        if not isinstance(tick, int) or not (first <= tick <= last):
            continue
        summary["events"].append({
            "kind": ev.get("kind"), "detail": ev.get("detail")})
        if ev.get("kind") in ("citizen_new", "new_arrival"):
            summary["arrivals"] += 1
        if ev.get("kind") in ("threat_hold", "hostile_spawn",
                              "invasion"):
            summary["threats"] += 1
    # Chronological order (the Journal returns newest-first).
    summary["decisions"].reverse()
    summary["events"].reverse()
    # Diary boundary: diagnostics become observations, repeated
    # identical decisions collapse to one story beat. The distress
    # pairs are kept structured alongside the observation sentence
    # (see the "distress" field above): _finalize_decisions turns
    # the diagnostic into prose and drops the reason, which is the
    # only place the dwarf's name lives.
    for dec in summary["decisions"]:
        if (dec.get("action") or "") in LOG_ACTIONS:
            for name, need in parse_distress_pairs(
                    dec.get("reason") or ""):
                pair = {"name": name, "need": need}
                if pair not in summary["distress"]:
                    summary["distress"].append(pair)
    decisions, observations = _finalize_decisions(
        summary["decisions"])
    summary["decisions"] = decisions
    summary["observations"] = observations
    return summary


def _stock_line(start: dict[str, Any], end: dict[str, Any],
                metric: str, label: str) -> str:
    """'Drink: 9 -> 8' (or 'Drink: 9' when only one sample)."""
    s = start.get(metric)
    e = end.get(metric)
    if s is None and e is None:
        return ""
    if s is not None and e is not None and s != e:
        return f"{label}: {int(s)} -> {int(e)}"
    val = e if e is not None else s
    return f"{label}: {int(val)}"


def _stock_crisis_lines(summary: dict[str, Any]) -> list[str]:
    """Stock-crisis sentences (significance, 2026-11-27): a survival
    stock hitting zero, or sitting at zero, is significant even when
    no event record fired — a day like that can never be called
    quiet. Returns the sentences, [] when the stocks are fine.
    The crossing is stated as an interval of the record, never as
    a same-day event: the ledger endpoints (06-20: drink 6 -> 0)
    do not date the crossing — the stock_low event dates the zero
    to 06-21 (tick 192076), and only two drinks are recorded
    06-13 to 06-20. "Ran out today" for a ledger interval is
    wrong; the event-dated form lives in the prompt's event list,
    where the stock_low event itself carries the date."""
    lines = []
    start = summary.get("stocks_start") or {}
    end = summary.get("stocks_end") or {}
    for metric, label in (("drink", "drink"), ("food", "food")):
        s = start.get(metric)
        e = end.get(metric)
        # Stocks are numbers (ints or floats — the Store returns
        # floats); a zero value of either type is a zero stock.
        if isinstance(e, (int, float)) and e == 0 \
                and isinstance(s, (int, float)) and s > 0:
            lines.append(f"The last of the {label} ran out during "
                         f"this record ({int(s)} at the start, "
                         "none at the end).")
        elif isinstance(e, (int, float)) and e == 0:
            lines.append(f"There is no {label} left in the fort.")
    return lines


def _ledger_line(summary: dict[str, Any]) -> str:
    """The machine-readable stock record for a day, in the format
    ledger_stocks parses back: 'Drink: 38 -> 37 Food: 32 Wood:
    124 Stone: 0 Citizens: 7.' One builder for the template
    renderer and the AI writer — the two used to disagree (the
    template entries carried the line, the AI entries did not),
    so a rebuild over AI entries had no ledger to read and fell
    back to the Store's single trend sample (04-01's drink 39),
    which lies about a June day. Empty when the summary carries
    no stocks at all."""
    stock_bits = []
    for metric, label in (("drink", "Drink"), ("food", "Food"),
                          ("wood", "Wood"), ("stone", "Stone"),
                          ("population", "Citizens")):
        line = _stock_line(summary.get("stocks_start") or {},
                           summary.get("stocks_end") or {},
                           metric, label)
        if line:
            stock_bits.append(line)
    return " ".join(stock_bits) + "." if stock_bits else ""


def render_entry(summary: dict[str, Any]) -> str:
    """Render the daily summary as a diary entry (markdown body, no
    heading — write_entry adds the heading). Narrative prose in the
    overseer's voice — plain, concrete, dry: the day's story — what
    happened, what was decided, what went wrong, what the dwarves
    did — with the stock numbers kept as a ledger line, not the
    story itself. Every sentence states a recorded fact from the
    summary; nothing is invented. When there is nothing to say
    about a topic, it is not mentioned.

    The decisions are one flowing paragraph, not a list: the
    planner re-decides the same thing every tick, so the summary
    already collapsed repeats to one story beat (a changed outcome
    reads as "I tried again to ..."). A decision's reason and raw
    result never render — the reason is planner rationale, the
    result is tool output; the outcome is only "It worked." /
    "It did not work.", from the recorded ok flag."""
    lines: list[str] = []
    date = summary["date_words"]
    season = summary["season"]
    lines.append(f"The {date}, {season}.")
    lines.append("")
    # The ledger: the numbers stay, as a ledger line.
    ledger = _ledger_line(summary)
    if ledger:
        lines.append(ledger)
        lines.append("")
    # The story: what happened, in the order it matters.
    story: list[str] = []
    # Stock crises first — they are the day's weight when they happen.
    story.extend(_stock_crisis_lines(summary))
    # Deaths.
    for death in summary["deaths"]:
        cause = death.get("cause") or "an unknown cause"
        story.append(f"A dwarf died today: {cause}.")
    # Arrivals and threats.
    if summary["arrivals"]:
        n = summary["arrivals"]
        story.append(f"{n} new {'dwarf' if n == 1 else 'dwarves'} "
                     f"joined the fort today.")
    if summary["threats"]:
        story.append("Something hostile came too close today; "
                     "the fort held its breath.")
    # Distress observations (parsed from the planner's diagnostics).
    for obs in summary.get("observations") or []:
        story.append(obs)
    # Decisions, as one flowing paragraph.
    dec_sentences = []
    for dec in summary["decisions"]:
        phrase = clean_diary_text(
            dec.get("decision") or dec.get("action") or "")
        if not phrase:
            continue
        verb = ("I tried again to" if dec.get("retry")
                else "I decided to")
        sentence = f"{verb} {phrase}."
        if dec.get("ok") is True:
            sentence += " It worked."
        elif dec.get("ok") is False:
            sentence += " It did not work."
        dec_sentences.append(sentence)
    if dec_sentences:
        story.append(" ".join(dec_sentences))
    # Notable fort events only (the allowlist in
    # RENDERABLE_EVENT_KINDS) — daemon operations never render.
    event_lines = []
    for ev in summary["events"]:
        if ev.get("kind") not in RENDERABLE_EVENT_KINDS:
            continue
        detail = clean_diary_text(ev.get("detail") or "")
        kind = ev.get("kind") or "event"
        if detail:
            event_lines.append(f"{kind}: {detail}")
        else:
            event_lines.append(f"{kind}.")
    story.extend(event_lines)
    # A quiet day says so, plainly — but only when NOTHING
    # significant happened: no deaths, decisions, fort events,
    # arrivals, threats, distress, and no survival stock at zero.
    if story:
        for s in story:
            lines.append(s)
            lines.append("")
    else:
        lines.append("A quiet day. Nothing happened that the "
                     "fort felt the need to record.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ----------------------------------------------------------------------
# diary.md: the source of truth.
# ----------------------------------------------------------------------

def merge_driver_record(summary: dict[str, Any],
                        decisions: list[dict[str, Any]] | None = None,
                        stocks_start: dict[str, Any] | None = None,
                        stocks_end: dict[str, Any] | None = None
                        ) -> dict[str, Any]:
    """Fold an M1 run's own record into a daily summary built from
    the Store + Journal (in place, returned for convenience).

    The daemon's planner loop is paused during M1 runs, so the
    run's decisions are not in the Journal and no trend samples are
    taken for the run's day — without this the entry would say 'a
    quiet day' for a day the model acted on, and show no stocks.
    Driver decisions REPLACE the Journal's for the day (they are
    the authoritative record for this run): the Journal is
    cumulative across playthroughs, so its decisions for the same
    in-game ticks are from earlier reloads of the same date — run
    #17's entry invented a manager appointment and credited the
    brewing to Olon because the Journal still carried run #10's
    decisions. Appending mixed playthroughs; replacing scopes the
    feed to the current run. Driver stocks (parsed from the run's
    start/end snapshots) override the Store samples when given.
    Everything merged is still a recorded fact — the run's log and
    its snapshots — nothing is invented.
    """
    if decisions:
        # Replace, not append: the Journal's decisions for this
        # tick range are from previous playthroughs of the same
        # date (the daemon loop was paused for this run, so the
        # Journal holds nothing from it).
        combined = list(decisions)
        # The driver's decisions are raw action records: run them
        # through the same boundary as the Journal's (dedup repeats,
        # split diagnostics) so the entry does not repeat a decision
        # once per tick.
        final, new_obs = _finalize_decisions(combined)
        summary["decisions"] = final
        existing_obs = summary.get("observations") or []
        summary["observations"] = existing_obs + [
            o for o in new_obs if o not in existing_obs]
    for key, val in (("stocks_start", stocks_start),
                     ("stocks_end", stocks_end)):
        if val:
            merged = dict(summary.get(key) or {})
            for metric, v in val.items():
                if v is not None:
                    merged[metric] = v
            summary[key] = merged
    return summary


def diary_md_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / "diary.md"


def diary_html_path(state_dir: str | Path) -> Path:
    return Path(state_dir) / "diary.html"


def write_entry(state_dir: str | Path,
                summary: dict[str, Any]) -> Path:
    """Append the entry for summary['date'] to diary.md (creating it
    with a header when missing) and regenerate diary.html. Returns
    the diary.md path. An entry for a date already present is
    replaced, not duplicated (re-running a day is idempotent)."""
    return _store_entry(state_dir, summary, render_entry(summary))


def write_ai_body(state_dir: str | Path, summary: dict[str, Any],
                  body: str) -> Path:
    """Append an AI-written entry body for summary['date'] to
    diary.md (same idempotence and HTML regeneration as
    write_entry). The body is the model's prose, already validated
    by write_ai_entry — this stores it, nothing more."""
    return _store_entry(state_dir, summary, body)


def _store_entry(state_dir: str | Path, summary: dict[str, Any],
                 body: str) -> Path:
    """Store one entry body for summary['date'] in diary.md and
    regenerate diary.html. An entry for a date already present is
    replaced, not duplicated."""
    md_path = diary_md_path(state_dir)
    fort = summary.get("fort_name") or "the fort"
    heading = f"## {summary['date']} — {summary['date_words']}"
    if md_path.exists():
        text = md_path.read_text()
    else:
        text = (f"# Diary of {fort}\n\n"
                f"One entry per in-game day, written by the fort's "
                f"overseer. Every claim traces to a recorded event, "
                f"decision, or observation in the harness journal "
                f"and state store.\n\n")
    # Replace an existing entry for this date, else append.
    pattern = re.compile(
        r"^## " + re.escape(summary["date"]) + r" — .*$"
        r"(?:\n(?!## ).*)*", re.MULTILINE)
    entry = heading + "\n\n" + body.rstrip() + "\n"
    if pattern.search(text):
        # A lambda replacement (2026-11-27, external review Table 6
        # row 4): the entry body is the replacement string, and a
        # backslash in it made re.sub treat it as a bad escape and
        # raise re.error, losing the day's entry. A callable
        # replacement is used verbatim.
        text = pattern.sub(lambda _: entry.rstrip(), text)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + entry
    text = _sort_entries_chronologically(text)
    md_path.write_text(text)
    render_html(md_path, diary_html_path(state_dir), fort)
    return md_path


def _date_key(date: str) -> tuple[int, int, int]:
    """(year, month, day) ints for a YYYY-MM-DD date string. Dates
    are zero-padded, so a string sort would agree — but parse
    defensively, so a hand-written or gap-marker date that drops
    a zero still sorts by the calendar, not the alphabet."""
    parts = date.split("-")
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return (0, 0, 0)


def _sort_entries_chronologically(md_text: str) -> str:
    """Re-emit diary.md with the entries in date order, keeping
    the preamble verbatim. The file was append-ordered, so a
    backfilled or retried entry (a later day written before an
    earlier one) landed out of order — and the HTML reader's
    "latest" is the last entry in the file, so it showed 04-05
    when the latest date was 07-07. Sorting on every store keeps
    the file chronological whatever order entries arrive in."""
    idx = md_text.find("## ")
    if idx == -1:
        return md_text
    preamble, rest = md_text[:idx], md_text[idx:]
    entries = parse_entries(rest)
    if len(entries) < 2:
        return md_text
    entries.sort(key=lambda e: _date_key(e["date"]))
    return _emit_entries(preamble, entries)


def _emit_entries(preamble: str,
                  entries: list[dict[str, str]]) -> str:
    """diary.md text from a preamble + parsed entries (in the
    order given — callers sort first). One blank line between
    entries, one trailing newline."""
    out = preamble.rstrip("\n") + "\n\n"
    for e in entries:
        out += (f"## {e['date']} — {e['date_words']}\n\n"
                + e["body"].rstrip("\n") + "\n\n")
    return out.rstrip("\n") + "\n"


def remove_entry(state_dir: str | Path, date: str) -> bool:
    """Delete the entry for `date` from diary.md (and regenerate
    diary.html). Returns True when an entry was removed. Used by
    the rebuild's --drop-dates for entries with no grounding —
    125-03-28 predates the fort's recorded existence, so its
    entry is deleted, not rewritten."""
    md_path = diary_md_path(state_dir)
    if not md_path.exists():
        return False
    text = md_path.read_text()
    idx = text.find("## ")
    if idx == -1:
        return False
    preamble, rest = text[:idx], text[idx:]
    entries = parse_entries(rest)
    kept = [e for e in entries if e["date"] != date]
    if len(kept) == len(entries):
        return False
    kept.sort(key=lambda e: _date_key(e["date"]))
    md_path.write_text(_emit_entries(preamble, kept))
    fort = ""
    m = re.search(r"^# Diary of (.+)$", preamble, re.MULTILINE)
    if m:
        fort = m.group(1).strip()
    render_html(md_path, diary_html_path(state_dir), fort)
    return True


# ----------------------------------------------------------------------
# The AI-written diary: per-dwarf feed + prompt + writer.
#
# The template renderer (render_entry) writes a ledger with short
# sentences — it reads as a list, not a diary entry (Mikey,
# 2026-11-26). The diary must be narrative prose ABOUT THE
# DWARVES. So the entry is written by the model, not by code
# templates: the harness supplies the facts (the feed below) and
# the model writes the story. The feed is curated, not dumped —
# only dwarves with real changes, plus their personal lives — and
# every fact in it traces to a recorded Store/Journal row.
# On model failure the caller logs and skips the day; a template
# list is never silently written instead.
# ----------------------------------------------------------------------


def _is_full_sample(sample: dict[str, Any] | None) -> bool:
    """A sample recorded the per-dwarf detail the feed diffs on
    (name, relations, needs). The daemon's poller records lite
    samples — no name, no relations, no needs, wounds mostly
    empty — for cheap frequent polling; those are valid for
    position/job/hunger/thirst, but an empty field in a lite
    sample is "not recorded", not "nothing there". Diffing one
    against a full sample fabricates new-today wounds, deities,
    and needs for every dwarf (observed 2026-11-27: the daemon's
    day-boundary lite sample at tick 100800 made the feed claim
    all seven dwarves gained a god and five were newly wounded,
    when the full run-start sample at 101323 shows the deities
    were pre-existing and only two wounds were new). A dwarf
    with genuinely no relations or needs still has a name, so
    the name is the primary marker; relations/needs are
    belt-and-braces for a record that somehow lost its name."""
    if not sample:
        return False
    return bool(sample.get("name")
                or sample.get("relations")
                or sample.get("needs"))


def _feed_samples(store: Any, uid: int, first: int, last: int
                  ) -> tuple[dict[str, Any] | None,
                             dict[str, Any] | None]:
    """(prev, curr) samples for one dwarf around a day. curr is
    the last FULL sample at or before the day end; prev is the
    last FULL sample before the day start, falling back to the
    earliest FULL sample inside the day (so the first sampled day
    still diffs against the morning's state). Only full samples
    are used: a lite sample (see _is_full_sample) is not a
    baseline — its empty wounds/relations/needs would read as
    "nothing was there" and fabricate new-today changes. When
    no full prev exists, prev is None and the diff yields no
    changes (the dwarf's relations are background, not new).
    (None, None) when the dwarf was never sampled."""
    samples = [s for s in store.unit_history(uid)
               if _is_full_sample(s)]
    curr = None
    prev = None
    for s in samples:
        t = s.get("tick")
        if not isinstance(t, int):
            continue
        if t <= last and (curr is None or t > curr["tick"]):
            curr = s
        if t < first and (prev is None or t > prev["tick"]):
            prev = s
    if curr is None:
        return None, None
    if prev is None:
        for s in samples:
            t = s.get("tick")
            if isinstance(t, int) and first <= t <= last \
                    and s is not curr:
                if prev is None or t < prev["tick"]:
                    prev = s
    return prev, curr


def open_threads(store: Any, day_start_tick: int,
                 year: int = 0) -> list[dict[str, Any]]:
    """The fort's open threads, derived from the day's samples:
    a wounded dwarf, a stressed dwarf, a dwarf in a strange mood,
    a dwarf with an unmet need, a survival stock at zero. Each
    thread carries how long it has been true (walked back through
    the samples), so the diary can arc a story across days — a
    wound on its third day reads differently from a fresh one. A
    thread closes when its condition clears; nothing is stored, so
    a closed thread simply stops appearing. The current sample is
    the latest at or before the DAY END, not the store's latest
    overall: a rebuild of an old day used to list July's threads
    on an April day (the rebuild cleared threads entirely to dodge
    it — that dropped real threads like Olon's 06-28 distress
    from the feed, audit R4)."""
    first, last = day_range(day_start_tick)
    # The store's earliest sample tick, once: _since needs it for
    # the pre-record boundary (a run reaching the first recorded
    # moment with the condition already true predates the record).
    # The method exists on the real Store; the fallback scans the
    # samples (test fakes) and gives the same number.
    earliest_tick: int | None = None
    getter = getattr(store, "earliest_unit_tick", None)
    if callable(getter):
        earliest_tick = getter()
    if earliest_tick is None:
        for _uid in store.unit_ids():
            for _s in store.unit_history(_uid):
                _t = _s.get("tick")
                if isinstance(_t, int) and (
                        earliest_tick is None or _t < earliest_tick):
                    earliest_tick = _t
    threads: list[dict[str, Any]] = []
    for uid in store.unit_ids():
        samples = [s for s in store.unit_history(uid)
                   if isinstance(s.get("tick"), int)
                   and s["tick"] <= last]
        if not samples:
            continue
        curr = samples[-1]
        name = curr.get("name")
        if not name:
            # A lite sample carries no name: resolve it from the
            # citizen's latest full sample at or before the day
            # end (re-check 6, 06-02: the wound thread named only
            # "dwarf 5407" for äs Oslanlumash, whose name the
            # Store has at every full sample — the model then
            # wrote that there is no name for him). Samples are
            # already filtered to tick <= day end, so a name
            # first recorded after the day is never used; a
            # citizen with no full sample ever keeps
            # "dwarf {uid}".
            full_names = [s.get("name") for s in samples
                          if _is_full_sample(s) and s.get("name")]
            name = full_names[-1] if full_names else f"dwarf {uid}"
        # A condition's start: the earliest sample in the current
        # unbroken run of samples where the condition holds.
        # Returns (tick_or_None, first_sighting): the tick is a
        # true run start when the walk broke on a full sample with
        # the condition clear; a first sighting when the walk ran
        # out of samples without breaking (the condition may have
        # started earlier — rendered "(first recorded DATE)", never
        # "(since DATE)"). None when the run reaches the store's
        # first sample with the condition already true there: the
        # start predates the record and no date is honest.
        def _since(pred: Any) -> tuple[int | None, bool]:
            since = None
            broke = False
            for s in reversed(samples):
                if not _is_full_sample(s):
                    # A lite sample records no wounds, needs, or
                    # relations: its empty fields are "not
                    # recorded", not "clear". Skipping it keeps the
                    # run unbroken across the gap — Lòr's 04-02
                    # lite samples (no wound recorded) broke his
                    # wound run and dated it 04-03 instead of
                    # 04-01, contradicting the diary's own 04-01
                    # entry (re-check 2026-11-27). But a lite
                    # sample that SHOWS the condition is positive
                    # evidence it held at that tick: record it as
                    # a sighting and keep walking — an earlier
                    # full sample may push the run further back,
                    # and a full clear sample below it still
                    # breaks the run.
                    if isinstance(s.get("tick"), int) and pred(s):
                        since = s.get("tick")
                    continue
                if pred(s):
                    since = s.get("tick")
                else:
                    broke = True
                    break
            if broke:
                return (since if isinstance(since, int) else None,
                        False)
            # The walk ran out of samples. The start predates the
            # record only when the dwarf's earliest sample IS the
            # store's earliest tick AND shows the condition there
            # (Rakust's wound is already present in the lite
            # sample at tick 100800, the first tick of 04-01 —
            # re-check 3, 2026-11-27). An empty earliest lite
            # sample proves nothing ("not recorded"), and a dwarf
            # whose record starts later (a migrant, first seen
            # 06-13) has a first sighting, not a pre-record start.
            if (earliest_tick is not None and samples
                    and samples[0].get("tick") == earliest_tick
                    and pred(samples[0])):
                return (None, False)
            return (since if isinstance(since, int) else None, True)

        wounds = curr.get("wounds") or []
        if wounds:
            # Wound dates are first sightings of THIS wound id,
            # never taking-dates and never the start of an earlier
            # healed wound. A wound record's id is stable per wound
            # (dwarves._wound_ids): a new id is a new wound, a
            # missing id is a healed one. The April wounds (id 4)
            # healed by 04-12; the June wounds are id 7, then id
            # 8 — tracking wound *presence* dated the id-8 wound
            # to the id-7 run's start (06-02), and the model then
            # invented 04-01 for it (re-check 5, 06-22). Walk back
            # per id. The date is always a first sighting
            # ("(first recorded DATE)"), never "(since DATE)": a
            # first sighting is not a taking-date — the wound could
            # have been taken any day between the last clear sample
            # and the sighting. A wound present in the store's
            # earliest sample predates the record: no date, and the
            # dwarf line renders "(since before today)".
            since_ticks: list[int] = []
            pre_record = False
            for w in wounds:
                wid = w.get("id") if isinstance(w, dict) else None
                if wid is None:
                    continue
                t, _first = _since(
                    lambda s, wid=wid: any(
                        isinstance(x, dict) and x.get("id") == wid
                        for x in s.get("wounds") or []))
                if t is None:
                    pre_record = True
                else:
                    since_ticks.append(t)
            if pre_record:
                since = None
                first_sighting = False
            elif since_ticks:
                since = min(since_ticks)
                first_sighting = True
            else:
                since = None
                first_sighting = False
            threads.append({
                "kind": "wounded", "subject": name,
                "unit_id": uid,
                "detail": f"{len(wounds)} wound"
                          f"{'s' if len(wounds) > 1 else ''}",
                "since": date_str(since, year) if since else None,
                "first_sighting": first_sighting})
        cat = curr.get("stress_category")
        if isinstance(cat, int) and cat != -1 and cat <= 1:
            since, first_sighting = _since(lambda s: isinstance(
                s.get("stress_category"), int)
                and s.get("stress_category") != -1
                and s.get("stress_category") <= 1)
            threads.append({
                "kind": "stressed", "subject": name,
                "unit_id": uid,
                "detail": ("at breaking point" if cat == 0
                           else "highly stressed"),
                "since": date_str(since, year) if since else None,
                "first_sighting": first_sighting})
        mood = curr.get("mood")
        if isinstance(mood, int) and mood != -1:
            since, first_sighting = _since(
                lambda s: isinstance(s.get("mood"), int)
                and s.get("mood") != -1)
            threads.append({
                "kind": "strange_mood", "subject": name,
                "unit_id": uid,
                "detail": curr.get("mood_name") or "a strange mood",
                "since": date_str(since, year) if since else None,
                "first_sighting": first_sighting})
        for n in curr.get("needs") or []:
            if not isinstance(n, dict):
                continue
            focus = n.get("focus")
            level = n.get("level")
            if not isinstance(focus, int) or focus >= 0:
                continue
            if isinstance(level, int) and level <= 0:
                continue
            threads.append({
                "kind": "unmet_need", "subject": name,
                "unit_id": uid,
                "detail": f"going without {n.get('need')}",
                "since": None})
            break
    return threads


def _group_counts(dwarves: list[dict[str, Any]]
                  ) -> list[dict[str, Any]]:
    """Pre-computed counts for every condition the feed lists, so
    the diary AI reads the number instead of inferring it from a
    list of names (run 060346: the feed listed six wounded dwarves
    and the AI wrote "every dwarf ... carrying an injury" — six of
    seven is six, not all). Each group carries the count, the
    total, the names in the group, and the names NOT in it — the
    complement is what stops the overgeneralization (Ral is the
    one dwarf not wounded). Groups with count 0 are still listed
    (the validator needs them: "none wounded" is true only when
    the count really is 0); the prompt renders only count > 0."""
    total = len(dwarves)

    def _stressed(rec: dict[str, Any]) -> bool:
        cat = (rec.get("stress") or {}).get("category")
        return (isinstance(cat, int) and cat != -1 and cat <= 1)

    def _thirsty(rec: dict[str, Any]) -> bool:
        return any("drink" in (n.get("need") or "")
                   for n in rec["needs"])

    def _hungry(rec: dict[str, Any]) -> bool:
        return any(any(w in (n.get("need") or "")
                       for w in ("eat", "food", "meal"))
                   for n in rec["needs"])

    groups = [
        ("wounded", "Wounded", "Not wounded",
         lambda r: r["wounds"] > 0),
        ("idle", "Idle", "Working",
         lambda r: not r["job"]),
        ("stressed", "Stressed", "Not stressed", _stressed),
        ("mood", "In a mood", "Not in a mood",
         lambda r: r["mood"] != "none"),
        ("unmet_needs", "Going without something", "Needs met",
         lambda r: bool(r["needs"])),
        ("thirsty", "Thirsty", "Not thirsty", _thirsty),
        ("hungry", "Hungry", "Not hungry", _hungry),
    ]
    out = []
    for key, label, complement, pred in groups:
        names = [r["name"] for r in dwarves if pred(r)]
        out.append({
            "key": key, "label": label, "complement": complement,
            "count": len(names), "total": total,
            "names": names,
            "not_names": [r["name"] for r in dwarves
                          if not pred(r)],
        })
    return out


# The drink threshold the review itself used for Olon's distress
# (thirst counter past ~20000). The lite feed below derives a
# drink need from it — the game's need report is not in lite
# samples, so the counter is the signal.
_THIRST_THRESHOLD = 20000
# A lite record older than this before the day end is not the
# day's record at all (06-02's last sample is 04-02's, 54 days
# back) — the day gets no per-dwarf record. Up to this old, the
# record is used with its date attached, so the model attributes
# it instead of presenting it as today's. The line is a judgment
# call, flagged for the re-review.
_LITE_STALE_TICKS = 10 * TICKS_PER_DAY
# A lite-to-lite stress jump big enough to be a change, not
# noise. The full-sample diff uses a 10,000 threshold for a
# stress-category change; lite samples are the raw counter, and
# their deltas run in the tens/hundreds. Calibrated from the
# year-125 lite data: the routine band is roughly ±100 (Litast
# -30, -30, -6, +10; Cog -30, -30, -55, -10, -4, -42; Zulban
# -90, -45), while real jumps start at +131 (Zulban, 06-12) and
# run to +1034 (Litast, 06-12) and +678 (Olon, 07-05). 150 sits
# between the noise band and the signal: it catches Litast's
# +183/+212/+1034, Cog's +354, Olon's +678, Ral's +194, and
# misses Zulban's borderline +131. A judgment call, like the
# staleness line above — the re-review can move it.
_LITE_STRESS_DELTA = 150


def _day_has_full_samples(store: Any, day_start: int) -> bool:
    """True when any citizen has a full per-dwarf sample inside
    the day starting at day_start. The feed's curr is the last
    full sample at or before the day end; when no full sample
    falls inside the day, curr is an older day's sample and the
    feed's per-dwarf record is stale for this day (04-05: the
    last full samples are 101999, from 04-01; the June/July days:
    the last full is 101999 for the originals, and the migrants
    never had one)."""
    day_end = day_start + TICKS_PER_DAY - 1
    for uid in store.unit_ids():
        for s in store.unit_history(uid):
            tick = s.get("tick")
            if (isinstance(tick, int)
                    and day_start <= tick <= day_end
                    and _is_full_sample(s)):
                return True
    return False


def _lite_dwarf_feed(store: Any, day_start: int, population: int,
                     year: int):
    """The day's per-dwarf record from LITE samples — the only
    per-dwarf data the June/July days have. For each citizen, the
    latest sample (full or lite) at or before the day end: wounds
    from its wounds list (presence only — the lite sampler's wound
    ids are suspect: at tick 103996 all six wounded dwarves carry
    the identical wound id 4, parts 2, so only the count is used,
    never the id), job from its job column, and a drink need
    derived from its thirst counter (past _THIRST_THRESHOLD).
    Names come from the citizen's last FULL sample; a citizen with
    no full sample ever (the three migrants) has no name and
    appears as "an unnamed migrant" — the prompt names the gap
    instead of inventing one. Returns a dict — records,
    group_counts, record_tick (the latest sample tick used),
    unnamed (citizens in the records with no recorded name),
    sampled (citizens with any sample at or before the day end),
    span_ticks (the spread of the per-citizen latest-sample ticks
    — 0 when every record is from one sample round),
    in_day_sampled / in_day_wounded (citizens whose latest sample
    falls inside the day, and how many of them are wounded) — or
    None when no citizen has any sample at or before the day
    end. Moved here from scripts/rebuild_diary.py (2026-11-27,
    audit R1) so the live paths use the same fallback the rebuild
    does, instead of presenting an older day's full samples as
    today's."""
    day_end = day_start + TICKS_PER_DAY - 1
    records: list[dict] = []
    record_tick = None
    unnamed = 0
    sampled = 0
    in_day_sampled = 0
    in_day_wounded = 0
    latest_ticks: list[int] = []
    for uid in store.unit_ids():
        samples = store.unit_history(uid)
        latest = None
        prev = None
        for s in samples:
            tick = s.get("tick")
            if not isinstance(tick, int) or tick > day_end:
                continue
            if latest is None or tick > latest["tick"]:
                prev = latest
                latest = s
            elif prev is None or tick > prev["tick"]:
                prev = s
        if latest is None:
            continue
        sampled += 1
        tick = latest.get("tick")
        if isinstance(tick, int):
            latest_ticks.append(tick)
            if day_start <= tick <= day_end:
                in_day_sampled += 1
                if latest.get("wounds"):
                    in_day_wounded += 1
        # Names (and the social/traits/emotions taken from the
        # same sample, below) come only from full samples at or
        # before the day end. The unfiltered version took the
        # citizen's last full sample overall — a name first
        # recorded after the day (the migrants', 06-28) would
        # land on an earlier day's feed (same root cause as
        # re-check 6's 06-02 thread: a lite record with no name
        # of its own must resolve against what the record had
        # by then, never against the future).
        full = [s for s in samples
                if _is_full_sample(s)
                and isinstance(s.get("tick"), int)
                and s["tick"] <= day_end]
        name = full[-1].get("name") if full else ""
        if not name:
            unnamed += 1
        rec = dwarf_record(latest, changes=[], related_states={},
                           prev_relations=None)
        rec["name"] = name or "an unnamed migrant"
        rec["profession"] = (full[-1].get("profession") or ""
                             if full else "")
        if full:
            # A lite sample carries no social/traits/emotions, so
            # the record takes them from the latest full sample —
            # the same override as name/profession above. Without
            # this the June/July feeds would show every dwarf as
            # friendless and characterless by construction.
            ties, outside = social_ties(full[-1], None, {})
            rec["social"] = ties
            rec["social_outside"] = outside
            rec["traits"] = salient_traits(full[-1])
            rec["emotions"] = recent_emotions(full[-1])
        rec["needs"] = []
        thirst = latest.get("thirst")
        if isinstance(thirst, int) and thirst > _THIRST_THRESHOLD:
            # Derived, not game-reported: the lite sample carries
            # the counter but not the need. Marked by the comment
            # and by the rebuild's log line, not hidden.
            rec["needs"] = [{"need": "drink", "focus": -1,
                             "level": 1}]
        # A stress jump between lite samples is the only per-dwarf
        # change signal the June/July days have (the lite feed
        # carries no needs, relations, or moods, and the wounds
        # flap). The raw counter, rendered qualitatively — never
        # the number, which the model would narrate as a stat.
        # prev is the sample before latest in tick order (None on
        # a first sighting); a missing stress on either side is
        # no signal, not a zero.
        cur_stress = latest.get("stress")
        prev_stress = prev.get("stress") if prev is not None else None
        if isinstance(cur_stress, int) and isinstance(prev_stress, int):
            delta = cur_stress - prev_stress
            if delta >= _LITE_STRESS_DELTA:
                rec["changes"].append({
                    "kind": "stress_rose",
                    "text": "stress rose sharply"})
            elif delta <= -_LITE_STRESS_DELTA:
                rec["changes"].append({
                    "kind": "stress_eased",
                    "text": "stress eased sharply"})
        rec["featured"] = False
        rec["significance"] = 0
        records.append(rec)
        if isinstance(tick, int) and (record_tick is None
                                      or tick > record_tick):
            record_tick = tick
    if not records and unnamed == 0:
        return None
    counts = _group_counts(records)
    for g in counts:
        g["total"] = population
    span = (max(latest_ticks) - min(latest_ticks)
            if latest_ticks else 0)
    return {"records": records, "counts": counts,
            "record_tick": record_tick, "unnamed": unnamed,
            "sampled": sampled, "span_ticks": span,
            "in_day_sampled": in_day_sampled,
            "in_day_wounded": in_day_wounded}


def feed_is_writable(feed: dict[str, Any]) -> tuple[bool, str]:
    """Whether a diary feed is worth writing from (audit R2:
    skip, never write from stale). A feed is writable when it
    carries a fresh per-dwarf record, or a dated lite/partial
    record plus an anchor (decisions, or stocks from a run, a
    fresh collect, or a ledger — never the Store's trend sample,
    which is a single 04-01 sample for every later day), or
    snapshot counts plus an anchor (the rebuild's 04-05 class),
    or decisions/observations plus fresh stocks. A feed with no
    fresh dwarves, no usable lite record, no decisions and only
    trend stocks is refused — the model would invent the day
    from the recent entries. Returns (True, "") or
    (False, reason); the reason always starts "feed too thin"
    so the route's existing contract holds."""
    summary = feed.get("summary") or {}
    stocks_ok = summary.get("stocks_source") in (
        "run", "fresh", "ledger")
    has_fresh_dwarves = bool(feed.get("feed_fresh")
                             and feed.get("dwarves"))
    has_dated_record = bool(
        feed.get("lite_dwarf_record_date")
        or feed.get("partial_dwarf_record"))
    has_counts = bool(feed.get("group_counts"))
    has_decisions = bool(summary.get("decisions"))
    has_observations = bool(summary.get("observations"))
    if has_fresh_dwarves:
        return True, ""
    if has_dated_record and (has_decisions or stocks_ok):
        return True, ""
    if (feed.get("no_per_dwarf_samples") and has_counts
            and (has_decisions or stocks_ok)):
        return True, ""
    if (has_decisions or has_observations) and stocks_ok:
        return True, ""
    return False, ("feed too thin or stale: no fresh per-dwarf "
                   "record, no usable lite record, no decisions, "
                   "and no fresh stocks")


def apply_snapshot_counts(feed: dict[str, Any],
                          end: dict[str, Any]) -> bool:
    """Override a stale feed's wounded/idle counts with the run
    snapshots' own counts (rebuild-only: the live paths have no
    run logs to read them from). The snapshots are the day's own
    data — the Population lines the run recorded — so they win
    over lite counts and over a feed whose counts were already
    cleared. Only wounded/idle are overridden, with names
    cleared (their states are not the day's); the other groups
    (stressed/mood/needs from the stale day) are dropped, they
    have no record here. Returns True when the counts changed.
    A from-scratch group (feed counts already cleared) gets its
    label/complement from _group_counts' table."""
    labels = {"wounded": ("Wounded", "Not wounded"),
              "idle": ("Idle", "Working")}
    existing = {g["key"]: g for g in feed.get("group_counts") or []}
    new_counts = []
    changed = False
    for key in ("wounded", "idle"):
        if key not in end:
            continue
        old = existing.get(key)
        label, complement = labels[key]
        if old is None:
            changed = True
        else:
            label, complement = old["label"], old["complement"]
            if (old["count"] != end[key]
                    or old["total"] != end["population"]):
                changed = True
        new_counts.append({
            "key": key, "label": label, "complement": complement,
            "count": end[key], "total": end["population"],
            "names": [], "not_names": []})
    if changed:
        feed["group_counts"] = new_counts
        feed["dwarves"] = []
        feed["no_per_dwarf_samples"] = True
    return changed


def build_diary_feed(store: Any, journal: Any,
                     day_start_tick: int,
                     fort_name: str = "",
                     year: int = 0,
                     state_dir: str | Path | None = None,
                     population: int | None = None,
                     watch_log_path: str | Path | None = None,
                     run_logs_dir: str | Path | None = None,
                     ) -> dict[str, Any]:
    """The feed for the AI diary writer: the day's ledger
    (build_daily_summary) + one structured record per dwarf who
    changed (diffed against their previous sample, with their
    relations' current state) + the last few entries for
    continuity + the open threads. Curated, not dumped: stable
    dwarves get a line or nothing; the featured dwarves (a real
    change, or named in a death) lead."""
    summary = build_daily_summary(store, journal, day_start_tick,
                                  fort_name, year)
    first, last = day_range(day_start_tick)
    # The day's events, from the daemon's bus event log
    # (day_events) plus the raw DFHack watch log, which is the
    # fuller completion source (the bus misses CustomReaction and
    # the still's ConstructBuilding, and its day-start baseline
    # rows are not completions). The watch log lives in the repo
    # (third_party/df_47_05/dfh-events.jsonl); the caller passes
    # it. None means bus-only (the offline tests, which must not
    # read a live game file) — never auto-resolved here, so a
    # test feed stays hermetic.
    events_path = None
    if state_dir is not None:
        events_path = Path(state_dir) / "events.jsonl"
    else:
        jpath = getattr(journal, "path", None)
        if jpath:
            events_path = Path(jpath).parent / "events.jsonl"
    resolved_watch: Path | None = None
    if watch_log_path is not None:
        resolved_watch = Path(watch_log_path)
    store_names: dict[int, str] = {}
    for _uid in store.unit_ids():
        _full = [s for s in store.unit_history(_uid)
                 if _is_full_sample(s)]
        if _full and _full[-1].get("name"):
            store_names[_uid] = _full[-1]["name"]
    events = read_day_events(events_path, year, first, store_names,
                             watch_log_path=resolved_watch)
    # The workshop map (run logs, not the journal — the journal
    # mixes forts and lacks the main fort's 04-01 still build):
    # pos -> {id, kind}, so a completion's position becomes a
    # name in the prompt. A missing dir is an empty map; the
    # phrases fall back to the vague-but-true forms.
    workshops = read_workshop_map(run_logs_dir)
    feed_workshops = [
        {"pos": list(pos), "id": w["id"], "kind": w["kind"]}
        for pos, w in sorted(workshops.items())]
    # Deaths, named: the Store's death diagnosis carries the cause
    # but no name; the event log carries the name but no cause.
    # Join them here (the harness joins, never the model), so the
    # prompt renders one death line with both — and the events
    # section can skip deaths the summary already names.
    for d in summary.get("deaths") or []:
        uid = d.get("unit_id")
        if isinstance(uid, int) and uid in store_names:
            d["name"] = store_names[uid]
    featured_ids: set[int] = set()
    for d in summary["deaths"]:
        if isinstance(d.get("unit_id"), int):
            featured_ids.add(d["unit_id"])
    dwarves: list[dict[str, Any]] = []
    for uid in store.unit_ids():
        prev, curr = _feed_samples(store, uid, first, last)
        if curr is None:
            continue
        changes = diff_unit_samples(prev, curr)
        related: dict[int, dict[str, Any]] = {}
        for r in curr.get("relations") or []:
            ruid = r.get("unit_id")
            if isinstance(ruid, int) and r.get("in_fort"):
                # Only full samples: a lite latest would make the
                # diff report every deity as "lost" and mark the
                # dwarf changed when they did not (same bug as
                # _feed_samples — a lite sample is not a baseline).
                rsamples = [s for s in store.unit_history(ruid)
                            if _is_full_sample(s)]
                if rsamples:
                    latest = rsamples[-1]
                    prev_r = rsamples[-2] \
                        if len(rsamples) > 1 else None
                    related[ruid] = {
                        "mood_name": latest.get("mood_name"),
                        "stress_category":
                            latest.get("stress_category"),
                        "changed": bool(diff_unit_samples(
                            prev_r, latest)),
                    }
        rec = dwarf_record(curr, changes, related,
                           prev_relations=(
                               prev.get("relations")
                               if prev else None),
                           prev_social=(
                               prev.get("social")
                               if prev else None))
        rec["featured"] = (
            rec["significance"] >= FEATURE_THRESHOLD
            or uid in featured_ids)
        dwarves.append(rec)
    dwarves.sort(key=lambda r: (not r["featured"],
                                -r["significance"],
                                r["name"]))
    counts = _group_counts(dwarves)
    # Stocks provenance: build_daily_summary reads the Store's
    # trend samples — a single 04-01 sample for every later day —
    # so unless a caller merged fresher stocks in (the retry
    # route's driver stocks, the rebuild's run/ledger stocks),
    # these are the trend's, not today's. feed_is_writable uses
    # this to refuse a feed whose only anchor is a stale trend.
    summary.setdefault("stocks_source", "trend")
    # Staleness (audit R1): the per-dwarf record above is the last
    # FULL sample at or before the day end, however old. When no
    # full sample falls inside the day, that record is an older
    # day's — presenting it as today's wrote 04-01's numbers into
    # the 04-05 entry. Fall back to the lite record (dated) or to
    # no per-dwarf record at all, exactly as the rebuild used to
    # do on its own; the live paths now get the same treatment.
    # feed_fresh is False whenever the day has no full samples,
    # even when a lite record covers it — the prompt dates the
    # record either way.
    feed: dict[str, Any] = {"summary": summary, "dwarves": dwarves,
                            "group_counts": counts,
                            "feed_fresh": True,
                            "workshops": feed_workshops}
    pop_end = (summary.get("stocks_end") or {}).get("population")
    if isinstance(population, int):
        # The rebuild passes the merged summary's population: the
        # ledger/run stocks know the true headcount (10 on 06-02),
        # while the trend sample says 7 for a June day.
        pop = population
    else:
        pop = pop_end if isinstance(pop_end, int) else 0
    sampled_uids = 0
    for uid in store.unit_ids():
        if any(isinstance(s.get("tick"), int)
               and s["tick"] <= last
               for s in store.unit_history(uid)):
            sampled_uids += 1
    pop = max(pop, sampled_uids)
    feed["population"] = pop
    record_tick: int | None = None
    if _day_has_full_samples(store, first):
        # Citizens with no full sample ever (the migrants) are
        # missing from the dwarves list: name the gap instead of
        # letting the counts pretend the fort is smaller.
        missing = max(0, pop - len(dwarves))
        if missing:
            feed["unnamed_citizens"] = missing
            for g in counts:
                g["total"] = pop
    else:
        feed["feed_fresh"] = False
        lite = _lite_dwarf_feed(store, first, pop, year)
        if lite is None:
            feed["dwarves"] = []
            feed["group_counts"] = []
            feed["no_per_dwarf_samples"] = True
        else:
            record_tick = lite["record_tick"]
            rec_date = (date_str(record_tick, year)
                        if isinstance(record_tick, int) else None)
            no_record = pop - lite["sampled"]
            unnamed = lite["unnamed"] + max(0, no_record)
            if lite["span_ticks"] > _LITE_STALE_TICKS:
                # Partial record: the per-citizen latest samples
                # span weeks (06-02: two dwarves sampled today,
                # the rest from 04-03). No single date owns the
                # record, so no count is attributable to the day
                # — clear it, and name the partial poll instead
                # of hiding it.
                feed["dwarves"] = []
                feed["group_counts"] = []
                feed["no_per_dwarf_samples"] = True
                feed["last_dwarf_record_date"] = date_str(
                    record_tick - lite["span_ticks"], year)
                feed["partial_dwarf_record"] = {
                    "sampled": lite["in_day_sampled"],
                    "wounded": lite["in_day_wounded"]}
                if unnamed:
                    feed["unnamed_citizens"] = unnamed
            elif isinstance(record_tick, int) \
                    and last - record_tick > _LITE_STALE_TICKS:
                feed["dwarves"] = []
                feed["group_counts"] = []
                feed["no_per_dwarf_samples"] = True
                feed["last_dwarf_record_date"] = rec_date
                if unnamed:
                    feed["unnamed_citizens"] = unnamed
            else:
                feed["dwarves"] = lite["records"]
                feed["group_counts"] = lite["counts"]
                if unnamed:
                    feed["unnamed_citizens"] = unnamed
                if rec_date != summary.get("date"):
                    feed["lite_dwarf_record_date"] = rec_date
    feed["events"] = events
    # Source coverage (P0-2): the feed states which sources were
    # live for the day. The events part (bus + watch log) comes
    # from read_day_events; the samples part is measured here from
    # the Store: how many full/lite samples fall in the day, and
    # the latest sample at or before the day end. Six of the seven
    # bar-failing days have no sample in the day at all, so the
    # "latest" fact is what the prompt can honestly draw on.
    full_in_day = lite_in_day = 0
    latest_tick: int | None = None
    for _uid in store.unit_ids():
        for s in store.unit_history(_uid):
            t = s.get("tick")
            if not isinstance(t, int):
                continue
            if first <= t <= last:
                if _is_full_sample(s):
                    full_in_day += 1
                else:
                    lite_in_day += 1
            if t <= last and (latest_tick is None or t > latest_tick):
                latest_tick = t
    feed["coverage"] = {
        **(events.get("coverage") or {}),
        "day_start_tick": first,
        "samples": {
            "full_in_day": full_in_day,
            "lite_in_day": lite_in_day,
            "latest_tick": latest_tick,
            "latest_date": (date_str(latest_tick, year)
                            if isinstance(latest_tick, int) else None),
        },
    }
    # Per-dwarf "did": what each dwarf actually did today, from
    # the day's job completions — the per-dwarf section is what a
    # dwarf DID and what happened TO them, not their stat line.
    # Routine jobs (drink/eat/sleep) ride as counts; non-routine
    # jobs name the work. A dwarf with no completions gets none.
    for rec in feed["dwarves"]:
        uid = rec.get("unit_id")
        did = [{"job": c["job"], "count": c["count"],
                "routine": c["routine"], "pos": c.get("pos")}
               for c in events.get("completions") or []
               if c.get("worker_id") == uid]
        if did:
            rec["did"] = did
    # Migrant names (audit 2026-11-27): the Store's lite samples
    # never recorded the migrants' names, but the event log's
    # citizen_new events do (Cog Letmossazir, Litast Aknònul,
    # Zasit Bistöklòr). Resolve them here so no entry calls them
    # unnamed: records named "an unnamed migrant" take the name,
    # and citizens missing from the dwarves list entirely (no full
    # sample ever) are named with their first-recorded date.
    known = events.get("known_names") or {}
    if known:
        for rec in feed["dwarves"]:
            uid = rec.get("unit_id")
            if (rec.get("name") == "an unnamed migrant"
                    and isinstance(uid, int) and uid in known):
                # The name is a detection, not an arrival: the
                # migrants' names were first recorded at tick
                # 201600 (07-01) though they arrived 06-02/06-03.
                # A feed for an earlier day must not use a name
                # the record did not have yet — the day's feed
                # keeps them unnamed, as the record had them.
                first_seen = known[uid].get("first_seen_tick")
                if (not isinstance(first_seen, int)
                        or first_seen > day_start_tick):
                    continue
                rec["name"] = known[uid]["name"]
                if known[uid].get("profession"):
                    rec["profession"] = known[uid]["profession"]
                if feed.get("unnamed_citizens"):
                    feed["unnamed_citizens"] -= 1
        present = {r.get("unit_id") for r in feed["dwarves"]}
        named_missing = []
        for uid in store.unit_ids():
            if uid in present or uid not in known:
                continue
            samples = store.unit_history(uid)
            if any(_is_full_sample(s) for s in samples):
                continue
            first_tick = samples[0].get("tick") if samples else None
            # Not yet arrived: a migrant whose first sample is
            # after this day's end was not in the fort on this
            # day, so the feed does not list them (04-01 listed
            # all three with a future first-recorded date).
            if (not isinstance(first_tick, int)
                    or first_tick > last):
                continue
            # Not yet named: the name is a detection, not an
            # arrival — a migrant whose name was first recorded
            # after this day's end (the three migrants' names at
            # 201600/07-01, though they arrived 06-02/06-03) is
            # not named on this day, even though they were in the
            # fort. The same gate as the rename above, against
            # the day end instead of the day start (this list
            # names citizens missing from the dwarves list, so
            # the day end is the right bound).
            first_seen = known[uid].get("first_seen_tick")
            if (not isinstance(first_seen, int)
                    or first_seen > last):
                continue
            named_missing.append({
                "name": known[uid]["name"],
                "profession": known[uid].get("profession") or "",
                "first_recorded": (
                    date_str(first_tick, year)
                    if isinstance(first_tick, int) else "")})
        if named_missing:
            feed["migrants_named"] = named_missing
            if feed.get("unnamed_citizens"):
                feed["unnamed_citizens"] = max(
                    0, feed["unnamed_citizens"] - len(named_missing))
        if not feed.get("unnamed_citizens"):
            feed.pop("unnamed_citizens", None)
    # The counts were computed before the rename above, so their
    # names still say "an unnamed migrant" for dwarves the dwarf
    # lines now name (re-check 7: Litast/Zasit/Cog named in the
    # dwarf lines, "an unnamed migrant" in the counts). Recompute
    # them from the renamed records so the two agree; the rename
    # touches only name/profession, so the counts themselves do
    # not change. Totals are preserved: the lite path's total is
    # the ledger headcount (population), not len(dwarves).
    if feed.get("group_counts"):
        old_totals = {g["key"]: g.get("total")
                      for g in feed["group_counts"]}
        feed["group_counts"] = _group_counts(feed["dwarves"])
        for g in feed["group_counts"]:
            if g["key"] in old_totals:
                g["total"] = old_totals[g["key"]]
    # Record age + unknown window (audit R3): the model must never
    # subtract dates or assert anything about days with no record.
    # Age is the date difference (day indices), not tick elapsed:
    # 06-20 minus 06-13 is 7 days even though the record tick sits
    # part-way through 06-13.
    if isinstance(record_tick, int):
        rec_day = record_tick // TICKS_PER_DAY
        first_day = first // TICKS_PER_DAY
        age = first_day - rec_day
        if age > 0:
            feed["record_age_days"] = age
        unknown = [date_str(d * TICKS_PER_DAY, year)
                   for d in range(rec_day + 1, first_day + 1)]
        if unknown:
            feed["unknown_dates"] = unknown
    # Distress attached to the dwarf (audit R4): a distress
    # observation is a fact about a named dwarf, not a footnote.
    # The dwarf's own line carries it, and it also becomes an open
    # thread (merged with open_threads below), so it survives even
    # when the model skims the notes.
    distress_threads: list[dict[str, Any]] = []
    for pair in summary.get("distress") or []:
        name = pair.get("name") or ""
        need = pair.get("need") or ""
        if not name:
            continue
        for rec in feed["dwarves"]:
            if rec.get("name") == name:
                rec["distress"] = need
        distress_threads.append({
            "kind": "distress", "subject": name,
            "detail": f"in distress, {need}",
            "since": summary.get("date")})
    recent: list[dict[str, str]] = []
    if state_dir is not None:
        md = diary_md_path(state_dir)
        if md.exists():
            # Only entries for dates strictly BEFORE today. The
            # diary is cumulative across reloads of the same fort,
            # so an entry for TODAY (or a later date) is from a
            # different playthrough of the same day — run #17's
            # entry invented a manager appointment and credited
            # the brewing to Olon because it carried forward an
            # old entry's claims. Earlier dates are the fort's
            # real history; today's story comes from today's facts.
            today = summary.get("date") or ""
            for e in parse_entries(md.read_text()):
                if today and e["date"] >= today:
                    continue
                recent.append({"date": e["date"],
                               "body": e["body"][:1500]})
            recent = recent[-3:]
    threads = open_threads(store, day_start_tick, year)
    for t in distress_threads:
        if not any(x.get("kind") == "distress"
                   and x.get("subject") == t["subject"]
                   for x in threads):
            threads.append(t)
    feed["recent_entries"] = recent
    feed["threads"] = threads
    return feed


_DIARY_SYSTEM = """You are the overseer of the Dwarf Fortress fort {fort}. You write one diary entry per in-game day, in the first person, as a person keeping a log — not as a storyteller performing one.

VOICE — plain, concrete, dry. Short sentences and long ones mixed. A detail beats a flourish: "the brewer has been thirsty for a week" is a good line; "thirst has become the fort's long shadow" is not — it says nothing a ledger could not. Dry humour is welcome when the facts earn it; archaic phrasing, elegy, and purple prose are not. Write the way a tired overseer would write at the end of the day: direct, specific, a little weary, never reaching for effect.

RULES — break none of them:
- Write from WHAT HAPPENED TODAY, not from the ledger. The feed opens with the day's events (announcements, arrivals, failures, what each dwarf finished) and what you decided ("What I did today"). Those are the entry. The ledger and the counts are background: they are there so you can check a number, not so you can narrate them. A count without a name and a deed behind it is not a sentence — "seven of the ten had no work" is a spreadsheet, not a day. Lead with a dwarf doing something, or something happening to a dwarf, or a decision you made and what came of it. Never lead with a stock, a count, or the ledger. Numbers appear only as the trace of an event: "Lòr finished the carpenter's workshop" is an event; "wood two hundred eleven" is not. If the feed says no event record exists for the day, the entry is two or three lines from the decisions and the per-dwarf record, and then it stops.
- The entry is ABOUT THE DWARVES: what they did today, what happened to them, how they relate, who they are close to, how that person is doing, their moods, stress, wounds, needs. The feed gives each dwarf their friends and grudges, their character, what they felt — use them. A dwarf's friend in a bad mood matters more than the food count. The stocks are a ledger line at most — one short sentence, never the story, never the opening, never the close.
- Write narrative prose in the first person ("I"), a few paragraphs when the day had something in it (150-300 words), two or three lines when it did not — and then stop. Never a bullet list, never a table. Write only what is new or changed today. If the feed lists no new event, no new decision, and no change since yesterday, the entry is at most three lines. No exceptions, and never fill the page with the roll-call and the stocks to reach a length: the ledger line below your entry already carries the numbers. A quiet day is two or three lines, then stop.
- Vary the shape of the entry. No two entries should read as if they were written from the same template. Never open with the date (the heading already carries it), with the age of the record, or with a disclaimer about what you do or don't know. Start with what happened. Never write a sentence whose job is to say which record is the latest: "The last per-dwarf record is the 3rd's", "The latest page on the dwarves is the 21st's", "The twenty-third is the last roll with names on it", "The third is the most recent page with names on it" are all the same construction — the record-date frame — and it is banned in every position, not just as an opening: moving it to the second sentence or the second paragraph is still the frame. The ONLY permitted form is the one above: the date inside the sentence about the fact it qualifies ("On the 13th, two migrants were carrying wounds"). A quiet day's two or three lines must be the new facts — the one thing that changed, or the one dwarf the day turned on. Never spend a line restating the record's date, the roll-call, or the stocks. Do not recite the full stock list in the prose — the ledger line below your entry carries the numbers; mention a stock only when it changed, and only in a sentence that dates the change: a same-day change ("Drink fell from thirty-five to thirty-three", two drinks recorded that day — the entry's day is its date), or a ledger interval with both endpoint dates ("Drink went from six at the end of the 12th to none by the 20th"). A stock change the day's events cannot account for must carry both endpoint dates. A sentence that only states current levels ("Food twenty-three, wood two hundred eleven") is out, even once. A sentence that only says a stock did not change ("food sits at thirty-two where it was") is the same move and is out too — an unchanged stock is not news. Do not paste the whole roster: name a dwarf when they did something, changed, or are the one the day turned on. The feed lists everyone for reference; the entry is not the list. Do not list every dwarf's need, wound, or job — pick the one or two that matter today; the rest is in the feed, not the entry. Do not put the ledger in the same place every day, and do not close with the same refrain.
- NEVER repeat a sentence, a joke, or a refrain from a previous entry. The recent entries are there so you know what has already been said — not so you can say it again. Before you write, read the recent entries and note the exact phrases they use for staleness, for the ledger, for idle hands, for thirst, for the workshops. Do NOT reuse any of them — not the words, not the construction. That includes the constructions a recent entry uses: a sentence that says which record is latest, a sentence that announces what you do not know, a sentence that restates the stocks. If a recent entry opens with a record-date sentence, do not open yours with one, and do not move it to the second sentence either. If a recent entry says "I will not dress it up", "I would swear to", "did not walk down", "went onto the slate", "ten pairs of idle hands", or "wood does not hold water", those phrases are used up: find different words, or leave the point unmade. If you said it yesterday, find a new way to say it or do not say it at all.
- When the record is old, put its age inside the sentence about the fact it qualifies ("On the 13th, two migrants were carrying wounds"), never as an opening disclaimer and never as a sentence about what you can or can't claim. One mention is enough; the reader knows.
- Do not announce your uncertainty. Never write a sentence whose job is to say what you will or won't claim, what you can or can't swear to, what you do or don't know, or how little you have. "I cannot tell you", "so I will not", "I won't claim", "I record it as it stands", "that is all I have", "That is the sum of what I have", "The first is certain", "the one figure I am sure of" are all the same move in different words — do not write any of them. The ban is on the move, not the phrase list: ANY sentence whose job is to say the figures are old, carried over, not fresh, or unmeasured is out — "the figures beside this entry are the old ones carried over", "I have the counts for the day and nothing attached to them", "the rest of the store I have not measured again" are the same move in new words. The age belongs inside a fact sentence or nowhere at all. State the facts and stop. Do not certify one figure as the sure one. Do not close with a summary of how little you know.
- Never end with a vow about tomorrow ("Tomorrow I will…", "I mean to find…", "I will find out…"). A bare prediction about what will happen ("they will not wait long") is the same move without the vow's wording — do not write it. Never close with an aphorism or tagline ("three throats, no barrel", "Water would answer most of what ails this place", "dry barrels or no"). Never write an aside about the writing ("That is the whole difficulty in two lines", "I know what the barrels would tell me"). End on a fact, not a line.
- Never end an entry on the drink-zero fact — "There is no drink in the fort" or any restatement of it. The ledger line already says it. A quiet day's last line is its one new fact, not the standing zero. Do not close on a joke or a punchline about something the fort lacks: no well jokes — the fort has no well in the facts, and "so there is no well" is a line, not a fact.
- Never infer whether queued jobs were begun or finished. The feed says what was queued, and the events say what finished ("Finished: ..."). A queued job is finished only when the events say it finished — never because it was queued, and never because a building stands. If the events do not say a job finished, do not say it was begun, unbegun, or finished.
- Never tie two same-day facts into one causal sentence unless the feed ties them. Wounds and a finished building on the same day are two facts, not one story — "five of them took wounds putting it there" is invention unless the feed says the wounds came from that job (same job, same report, same event). A coincidence of dates is not a cause.
- Count drinkers from the completions, never from the needs. One unit of drink is one drink. The events list who drank ("Routine: drinking — Olon, Ral"); the needs lines say who still goes without. Five "finally got drink" need lines are not five drinkers, and a stock drop of one is one drink, not five.
- Never state what a job or a building is made of unless the feed states it. "The beds want stone" is wrong (a bed takes wood) and the feed never said stone — materials come from the feed or not at all.
- At most two dwarves' needs per entry, and only the strongest one each. The feed lists every dwarf's needs for reference; the entry is not the list. "Badly" comes from the feed's rendering only (the feed marks a need "badly" when it gnaws hard) — never add it yourself, and never present a dwarf's weakest need as their defining want. A need the feed marks ongoing is background, not today's news.
- Say each fact once. Restating the same fact in new words is still restating it: a wound count, a thirsty list, a stock level, or a decision gets one sentence, not three. If you have said it, move on.
- Never close with a summary of the day. "That is the whole of the day:", "That is the day:" and any sentence that sums the entry up are out. End on a fact, not a line.
- A fact from a dated record carries its date in the same sentence. A wound first recorded on the 13th, a friendship from before the record, a stock from the previous entry's ledger — the date rides with the fact, never in a separate sentence about the record. The date rides in EVERY sentence that reports a fact from a dated record, not just the first: 06-27's second sentence ("Olon's close friend Rakust was idle alongside him") reported 06-26 facts with no date and was wrong.
- A wound first recorded on a date was not necessarily taken that day, and a wound first recorded on the 13th was not necessarily from before the 13th. First sighting is not the date of injury: the wound could have been taken any day between the last clear record and the sighting. Write "first recorded", never "taken" or "from before", for a wound's first sighting. "Taken today" for a wound first seen today is wrong; "from before the 13th" for a wound first seen on the 13th is wrong.
- A change is first recorded on the record's date, and may have happened any day since the last record: a stress rise first seen on the 21st may have happened any day since the last record. Date the change to the record date, and never claim a day inside the gap for it.
- Never say one dwarf has been thirsty longer than another. The feed carries no since-dates for thirst, and the thirst counters cannot order two dwarves — both Ral and Olon first crossed the line on the same day. "Goes back further than anyone else's", "longest", "the one going without longest" are all out. Say who is thirsty today; never rank them by duration.
- Do not comment on the record, the pages, or the entries themselves. "The one line on it that reads differently from the pages before" is an aside about the record, not a fact about the fort. Do not compare today's stocks to yesterday's unless the feed lists yesterday's numbers: "The stores are where yesterday left them" asserts a yesterday measurement the feed never gave.
- Do not use "hands" as a word for idle dwarves. Say "idle" or "with no work" plainly. No "pairs of hands", no "idle hands", no "empty hands".
- Do not personify the book, the ledger, or the column. The book is paper; it does not speak, keep secrets, carry names, or have a truest line. Do not write "the book doesn't say", "the column has stopped carrying his name", "the truest line in the book". Do not set the scene ("The ledger sits open on the desk"). Do not apologize for the fort, the book, or yourself, and do not assign blame the facts don't support ("parched for weeks by my own hand"). The thirst is a fact; whose fault it is is not in the facts.
- Do not guess why. "Perhaps" is still a guess. If the facts don't say why something happened, say nothing about why. Do not draw a conclusion the numbers don't support: a one-drink drop tells you nothing about how much the fort had.
- Advance open threads or drop them. A thread that has not changed in days is not news: mention it only if today changed it, and note when one closes. Never copy a thread line verbatim. Refer back to the recent entries when a story arcs across days.
- Every claim must come from the facts supplied below. Never invent an event, a name, a number, or a death that is not in the facts. If the facts do not say what happened to a dwarf, do not guess — leave them out or say their fate is unclear.
- Count carefully. When you say how many dwarves share a condition — wounded, stressed, thirsty, in a mood — name exactly which ones, and claim ALL of them only if the facts say all of them. Six wounded out of seven is six, not every dwarf. A dwarf the facts do not list as wounded is not wounded.
- Never use a share word ("most", "bulk", "mainly", "the bulk of", "the lion's share") unless the feed states the total — and then put the total in the sentence. "Most of what the fort got out of the daylight" for three gatherings out of six is wrong; "three of the six gatherings" is right. Say the numbers, not the share.
- Time is in the facts. A fact the feed marks pre-existing, long-standing, ongoing, or "since" a date did NOT happen today — never write that it happened today, was found today, or is new. Only a fact the feed marks "new today", or a change the feed lists for today, happened today. A dwarf's god, a long-standing bond, and a wound from an earlier day are background, not today's events. A wound the feed lists as "(since before today)" was already there when the record began — do not say it was taken today, found today, or is new. Five wounds taken today and one already there is five, not all. The seasons follow the Dwarf Fortress calendar, not Earth's: Granite, Slate and Felsite are spring; Hematite, Malachite and Galena are summer; Limestone, Sandstone and Timber are autumn; Moonstone, Opal and Obsidian are winter. A wound from Hematite is a summer wound — never call it spring. A count from Limestone is autumn, not summer.
- Do not compress distinct actions into one. If the feed lists two different actions — two job types, two workshops, a build and a queue — name both, with their counts. "Set one job running" for two queued jobs is wrong; say which jobs, how many of each, and at which workshop.
- The recent entries are from EARLIER days and may describe a different telling of this fort's story. Never carry a claim forward from a recent entry unless TODAY'S facts confirm it. If a past entry says an attempt failed, it stays failed unless today's facts say it succeeded. Name a dwarf as doing a job only if today's facts name them doing it — never because an old entry named them.
- A dwarf's profession is what they ARE, not what they are DOING today. Never write a dwarf working at their profession's bench, tool, or trade unless the facts say their job today is that work. If the facts say a dwarf is drinking, eating, or idle, say that — do not put tools in their hands. A jeweler who spent the day drinking was drinking, not grinding facets.
- When you write about a dwarf, use their personal life from the facts: who they are close to, how that person is doing, what they need, what they did today, what they felt. A new friendship is news; a long-standing bond is background — the feed marks which is which, and only the new one is today's story. A dwarf's character (their traits) and what they felt (their emotions) are in the feed when the game recorded them; use them when they bear on the day, and never invent a feeling the feed does not carry. People outside the fort are a count only — the feed says how many, never who they are, and you must not give them names or stories.
- Name the dwarves by name. Use each dwarf's full name the first time you mention them, and their first name after that. When you write about a dwarf, use their personal life from the facts: who they are close to, how that person is doing, what they need.
- A name first recorded after the event must not name the event. A completion names its worker by id, not by name: the old 06-12 entry named Litast Aknûnònul eating on the 12th, but his name was first recorded on the 1st of Limestone — on the 12th the record had him only as an unnamed migrant. Name a dwarf in an event only when the feed names them for that event.
- Plain words, no game jargon, no internal terms (no "unit_id", no "tick", no "job_type", no "stress_category"). A stranger reading this should follow it as a story."""


def _coverage_lines(feed: dict[str, Any],
                    has_events: bool) -> list[str]:
    """Plain-words source coverage for the day (P0-2): which event
    sources were live for the day, and what is unknown. The bus and
    the watch log end on different days, and the per-dwarf samples
    often end days before the day itself — the feed states each,
    so "sources dead, unknown" is never conflated with "sources
    live, nothing happened". Returns [] when the feed carries no
    coverage (old hand-built feeds keep the old text)."""
    cov = feed.get("coverage") or {}
    if not cov:
        return []
    year = 0
    date = (feed.get("summary") or {}).get("date") or ""
    try:
        year = int(str(date).split("-")[0])
    except ValueError:
        year = 0
    day_start = cov.get("day_start_tick")
    if not isinstance(day_start, int):
        day_start = 0
    lines: list[str] = []
    dead = False
    for key, label, unknown in (
            ("bus", "bus event log",
             "announcements, arrivals, and completions"),
            ("watch", "watch log", "job completions")):
        src = cov.get(key) or {}
        if not src.get("present"):
            dead = True
            lines.append(f"The {label} is missing — no {unknown} "
                         "from it.")
            continue
        last_tick = src.get("last_tick")
        in_day = src.get("in_day") or 0
        if isinstance(last_tick, int) and last_tick < day_start:
            dead = True
            lines.append(f"The {label} ends on "
                         f"{date_words(last_tick, year)} — no "
                         f"{unknown} from it after that day.")
        elif in_day:
            lines.append(f"The {label} covers this day "
                         f"({in_day} record"
                         f"{'s' if in_day != 1 else ''}).")
        else:
            # No rows in the day is not "live and recorded
            # nothing": the bus is lossy (06-12 captured 1 of 2
            # Eat completions) and a gap of days with zero rows
            # says nothing about what happened. The honest
            # wording is that no record exists for the day.
            lines.append(f"No {label} record exists for this day.")
    samples = cov.get("samples") or {}
    if samples.get("full_in_day"):
        lines.append("Full per-dwarf samples exist for this day.")
    elif samples.get("lite_in_day"):
        lines.append("Lite per-dwarf samples exist for this day.")
    else:
        latest_tick = samples.get("latest_tick")
        if isinstance(latest_tick, int):
            lines.append("No per-dwarf sample falls in this day — "
                         "the last record is from "
                         f"{date_words(latest_tick, year)}.")
        else:
            lines.append("No per-dwarf sample exists at or before "
                         "this day.")
        dead = True
    if not has_events:
        if dead:
            lines.append("Write two or three lines from the "
                         "decisions and the last dated record, and "
                         "stop. Do not fill the entry with the "
                         "ledger or the roll-call.")
        else:
            # The per-dwarf record covers this day, and no event
            # was recorded for it — but "nothing happened today"
            # is not the claim: the record is lossy, and a
            # same-day first sighting (06-02: äs's wound) IS
            # something happening. Say what the writer may draw
            # on, never that nothing happened (re-check 8).
            lines.append("The per-dwarf record covers this day. "
                         "Write two or three lines from the "
                         "per-dwarf record, and stop.")
    return lines


def diary_prompt(feed: dict[str, Any]) -> list[dict[str, str]]:
    """(system, user) messages for the AI diary writer, from the
    feed. The user message renders the day's facts as plain text —
    ledger, featured dwarves with their changes and personal lives,
    open threads, recent entries — and nothing else. The model gets
    facts, never raw Store rows."""
    summary = feed["summary"]
    fort = summary.get("fort_name") or "the fort"
    system = _DIARY_SYSTEM.format(fort=fort)
    parts: list[str] = []
    parts.append(
        f"Day: {summary['date_words']} ({summary['date']}), "
        f"{summary['season']}.")
    # What happened today — the day's events, first, before the
    # ledger. The feed used to hand the model stocks and state
    # diffs, so it narrated a spreadsheet; the events are the day.
    # A day with no event record says so and stops padding.
    # The queue groups are parsed once here (the one place the
    # queue phrases are parsed) so the completion phrases below
    # can resolve a workshop job to its gerund, and the "What I
    # did today" section later renders the same groups.
    dec_phrases, queue_groups, queue_order = (
        _queue_groups_and_phrases(summary))
    workshop_map = {
        tuple(w["pos"]): w for w in feed.get("workshops") or []
        if isinstance(w.get("pos"), list)}
    queue_kinds: dict[int, set] = {}
    for _loc in queue_order:
        _m = re.search(r"#(\d+)", _loc)
        if _m:
            queue_kinds[int(_m.group(1))] = {
                j for j, _, _ in queue_groups[_loc]}
    ev = feed.get("events") or {}
    cov_lines = _coverage_lines(feed, bool(ev.get("has_events")))
    if cov_lines:
        # Record for this day, right after the Day line and before
        # the events: which sources were live, and what is unknown.
        # The no-event branch below stays silent when this block
        # exists — it already says what the entry may draw on.
        parts.append("Record for this day:\n" + "\n".join(cov_lines))
    if ev.get("has_events"):
        elines = []
        for text in ev.get("reports") or []:
            elines.append(f"Announced: {text}")
        for text in ev.get("weather") or []:
            elines.append(f"Weather: {text}")
        for a in ev.get("arrivals") or []:
            prof = (f" ({a['profession']})"
                    if a.get("profession") else "")
            elines.append(
                f"Arrived: {a['name']}{prof} joined the fort.")
        for d in ev.get("departures") or []:
            elines.append(
                f"Left: {d['name']} is no longer in the fort "
                "(not recorded as a death).")
        for c in ev.get("cancellations") or []:
            job = job_words(c["job"]) or c["job"]
            elines.append(
                f"Failed: {c['name']} cancelled {job}. The record "
                "does not say why — do not guess.")
        routine_by_job: dict[str, list[str]] = {}
        for c in ev.get("completions") or []:
            job = _completion_phrase(c["job"], c.get("pos"),
                                     workshop_map, queue_kinds)
            if c.get("routine"):
                workers = c.get("workers") or []
                who = ", ".join(workers) if workers else "someone"
                n = c["count"]
                routine_by_job.setdefault(job, []).append(
                    f"{who} ({n})" if n > 1 else who)
            elif c.get("name"):
                n = c["count"]
                elines.append(
                    f"Finished: {c['name']} finished {job}"
                    + (f" ({n} times)" if n > 1 else "") + ".")
            else:
                n = c["count"]
                elines.append(
                    f"Finished: {job} was completed {n} "
                    f"time{'s' if n > 1 else ''} (the record does "
                    "not say by whom).")
        for job, whos in routine_by_job.items():
            elines.append(f"Routine: {job} — {', '.join(whos)}.")
        summary_death_names = {
            d.get("name") for d in summary.get("deaths") or []
            if d.get("name")}
        for d in ev.get("deaths") or []:
            if d.get("name") not in summary_death_names:
                elines.append(
                    f"Died: {d['name']} died today (the record "
                    "does not give the cause).")
        for d in ev.get("distress") or []:
            elines.append(f"In distress: {d['name']} — {d['kind']}.")
        for s in ev.get("stock_alerts") or []:
            if s["units"] == 0:
                elines.append(f"Ran out: the last of the "
                              f"{s['kind']} ran out today.")
            else:
                elines.append(f"Running low: {s['kind']} down to "
                              f"{s['units']}.")
        for t in ev.get("threats") or []:
            what = t.get("name") or t.get("race") or t.get("detail") \
                or "something hostile"
            elines.append(f"Threat: {what} came too close today.")
        noise = []
        if ev.get("wildlife_arrivals"):
            noise.append(f"{ev['wildlife_arrivals']} wild creatures "
                         "appeared")
        if ev.get("wildlife_deaths"):
            noise.append(f"{ev['wildlife_deaths']} wild creatures "
                         "died")
        if ev.get("dropped_reports"):
            noise.append(f"{ev['dropped_reports']} combat reports")
        if noise:
            elines.append("Also recorded, not the fort's story: "
                          + ", ".join(noise) + ".")
        parts.append("What happened today:\n" + "\n".join(elines))
    elif not cov_lines:
        parts.append(
            "No event record exists for this day: the watcher and "
            "the poller recorded nothing — write only from the "
            "decisions, the per-dwarf record, and the counts "
            "below, briefly, and stop. Do not pad the entry with "
            "the stocks or the roll-call to reach a length.")
    stock_bits = []
    for metric, label in (("drink", "drink"), ("food", "food"),
                          ("wood", "wood"), ("stone", "stone"),
                          ("population", "citizens")):
        line = _stock_line(summary["stocks_start"],
                           summary["stocks_end"], metric, label)
        if line:
            stock_bits.append(line)
    if stock_bits:
        parts.append("Ledger: " + "; ".join(stock_bits) + ".")
    if summary.get("stocks_source") == "ledger":
        # The rebuild's ledger-carried days (the 06/07 entries):
        # the numbers come from the previous entry's ledger, not
        # from a fresh measurement — the model must not present
        # them as if the store had samples for the day. The
        # validator still checks the entry against them.
        parts.append(
            "Stocks are carried from the previous entry's ledger; "
            "the store has no samples for this day — do not "
            "present them as fresh measurements.")
    if feed.get("no_per_dwarf_samples"):
        # The rebuild sets this when the Store has no full
        # per-dwarf samples for the day (04-05): the counts above
        # are the day's own, from the run snapshots, but no
        # individual dwarf's state was recorded. Do not describe
        # a dwarf's individual state (wounds, needs, stress,
        # mood) from the record — there is none. But the events
        # section above DOES name the dwarves who did things
        # (finished a building, gathered plants, drank), and the
        # entry must name them for what they did: the old wording
        # ("do not name any dwarf") contradicted the events and
        # made 04-02 hide its gatherers and drinkers behind "one
        # pair of hands" while 04-05 named them correctly
        # (re-check 5). When the last record is known (a lite
        # sample from an earlier day, e.g. 06-02's is 04-02's),
        # say so — the gap itself is a fact.
        part = feed.get("partial_dwarf_record")
        if part:
            # 06-02: lite samples exist today for a few citizens,
            # but the curated record was cleared (the samples span
            # too far to attribute to this day). "No record" would
            # contradict the coverage block, which says lite
            # samples exist for this day — say the partial truth
            # instead (re-check 8): samples exist today, only a
            # few citizens are covered, the rest have no record.
            pop = feed.get("population") or (
                feed["summary"].get("stocks_end") or {}).get(
                    "population")
            note = (f"The per-dwarf record for this day is "
                    f"partial: only {part['sampled']} of the {pop} "
                    f"citizens were recorded today. Do not "
                    f"describe any dwarf's individual state "
                    f"(wounds, needs, stress, mood) from the "
                    f"record beyond what the open threads carry. "
                    f"The events section above names the dwarves "
                    f"who did things today, and you may name them "
                    f"for what they did.")
        else:
            note = ("No per-dwarf record exists for this day: do "
                    "not describe any dwarf's individual state "
                    "(wounds, needs, stress, mood) from the "
                    "record — there is none. The events section "
                    "above names the dwarves who did things "
                    "today, and you may name them for what they "
                    "did. Write only about the day's events, "
                    "decisions, and counts.")
        last = feed.get("last_dwarf_record_date")
        if last:
            if part:
                # The date is the span's start, not the last
                # record: the partial samples run from it to
                # today, and no single date owns the record.
                note += (f" The samples behind it run from {last} "
                         f"to today; no single date owns the "
                         f"record — do not present its states as "
                         f"today's.")
            else:
                note += (f" The last per-dwarf record is from "
                         f"{last}; do not present its states as "
                         f"today's.")
        parts.append(note)
    if feed.get("partial_dwarf_record"):
        # The rebuild's partial-poll days (06-02): the day's own
        # samples cover only a few citizens. The numbers are the
        # poll's, not the fort's — say so, and claim nothing
        # about the unrecorded dwarves.
        part = feed["partial_dwarf_record"]
        # The population is the feed's own (computed in
        # build_diary_feed); the summary's stocks_end has no
        # population when the store has no trend samples, and
        # rendering "None citizens" would be worse than the gap.
        pop = feed.get("population") or (
            feed["summary"].get("stocks_end") or {}).get(
                "population")
        parts.append(
            f"Only {part['sampled']} of the {pop} citizens were "
            f"recorded today ({part['wounded']} wounded, "
            f"{part['sampled'] - part['wounded']} unmarked); the "
            f"other {pop - part['sampled']} have no record for "
            f"today. Do not claim anything about the unrecorded "
            f"dwarves.")
    if feed.get("lite_dwarf_record_date"):
        # The rebuild's lite-sample days (June/July): the
        # per-dwarf record below is the most recent one, from an
        # earlier day — the counts are that day's, not today's.
        # The model must attribute them to their date, not
        # present them as a fresh measurement.
        parts.append(
            f"The per-dwarf record below is from "
            f"{feed['lite_dwarf_record_date']}, the last day with "
            f"a per-dwarf sample — it is the most recent record, "
            f"not today's measurement. Attribute its facts to "
            f"that day; do not present them as today's.")
    if feed.get("record_age_days"):
        # Audit R3: the age in days, stated — never make the
        # model subtract dates (06-20: the record was 06-13 and
        # the model wrote "six days old" for seven).
        n = feed["record_age_days"]
        parts.append(
            f"The per-dwarf record is {n} "
            f"{'day' if n == 1 else 'days'} old.")
    if feed.get("unknown_dates"):
        # Audit R3: the days with no record at all, named — the
        # model must say nothing about them (07-07: the record
        # was 07-05 and the model still asserted "Nobody has
        # moved since" about 07-06/07-07). A long gap names its
        # ends, not every day in it.
        dates = feed["unknown_dates"]
        if len(dates) > 5:
            span = (f"the days from {dates[0]} to {dates[-1]} "
                    f"({len(dates)} days)")
        elif len(dates) == 1:
            span = dates[0]
        else:
            span = ", ".join(dates[:-1]) + f" or {dates[-1]}"
        parts.append(
            f"No record exists for {span}; say nothing about "
            f"them — do not claim any dwarf changed, stayed the "
            f"same, or did anything on those days.")
    if feed.get("unnamed_citizens"):
        # The rebuild's June/July days: migrants whose names were
        # never recorded. They are in the counts (the total is
        # the population) and appear in the lists below as "an
        # unnamed migrant" — the model must not give them names.
        n = feed["unnamed_citizens"]
        parts.append(
            f"{n} of the citizens {'is' if n == 1 else 'are'} "
            f"migrants whose names were never recorded; "
            f"{'it appears' if n == 1 else 'they appear'} in the "
            f"lists below as 'an unnamed migrant'. Do not invent "
            f"names for {'it' if n == 1 else 'them'}.")
    if feed.get("migrants_named"):
        # Citizens missing from the dwarves list whose names the
        # event log recovered: named here with their first-recorded
        # date, so the entry can write about them without inventing
        # an arrival date.
        mn = []
        for m in feed["migrants_named"]:
            prof = (f", {m['profession']}" if m.get("profession")
                    else "")
            when = (f" (first recorded {m['first_recorded']})"
                    if m.get("first_recorded") else "")
            mn.append(f"{m['name']}{prof}{when}")
        parts.append(
            "Migrants in the fort whose names the record "
            "recovered: " + "; ".join(mn) + ".")
    for crisis in _stock_crisis_lines(summary):
        parts.append("CRISIS: " + crisis)
    for death in summary["deaths"]:
        name = death.get("name")
        who = f"{name} died today" if name else "A dwarf died today"
        parts.append(
            f"{who}: {death.get('cause') or 'an unknown cause'}.")
    for obs in summary.get("observations") or []:
        parts.append("Noted: " + obs)
    # Queued jobs group by workshop, with counts per job type:
    # "Queued at the Carpenters workshop #7: make_bed x1,
    # make_barrel x2 (3 jobs total)". Two different jobs are two
    # facts, never compressed into "set one job running". A job
    # that did not work keeps its outcome on its own item.
    # (dec_phrases, queue_groups, queue_order were parsed once
    # above, before the events section, so the completion phrases
    # could resolve workshop jobs; they are rendered here.)
    if dec_phrases:
        parts.append("What I did today: " + "; ".join(dec_phrases) + ".")
    # Pre-computed counts: the AI reads the number instead of
    # inferring it from a list of names. The complement (who is
    # NOT in the group) is the point — it is what stops "every
    # dwarf is wounded" when six of seven are.
    count_lines = []
    for g in feed.get("group_counts") or []:
        if not g["count"]:
            continue
        line = (f"{g['label']}: {g['count']} of {g['total']} — "
                f"{', '.join(g['names'])}")
        if g["count"] < g["total"]:
            line += f". {g['complement']}: {', '.join(g['not_names'])}"
        count_lines.append(line)
    if count_lines:
        parts.append(
            "Counts (read these — do not recount from the lists "
            "below):\n" + "\n".join(count_lines))
    # The dwarves: featured first, each with their changes and
    # their personal life. A stable dwarf gets one line.
    # Wound threads carry "since" (first recorded date of the
    # wound the dwarf carries now) — a pre-existing wound is
    # background, not today's event. A wound that appeared today
    # is already named by the change text ("was wounded"), so the
    # line only needs the since-date for the pre-existing case.
    # Keyed by unit_id, not by name: three unnamed migrants share
    # the display name "an unnamed migrant" while the threads
    # name them "dwarf {uid}" — keying by name lost their
    # since-dates and the line fell back to "(since before today)"
    # (re-check 5, 06-20). The name key is kept only as a
    # fallback for threads/records without a unit id.
    wound_since = {}
    wound_since_by_name = {}
    for t in feed["threads"]:
        if t["kind"] != "wounded" or not t.get("since"):
            continue
        entry = (t["since"], t.get("first_sighting"))
        if isinstance(t.get("unit_id"), int):
            wound_since[t["unit_id"]] = entry
        wound_since_by_name[t["subject"]] = entry
    dwarf_lines = []
    for rec in feed["dwarves"]:
        bits = [f"{rec['name']} ({rec['profession'] or 'dwarf'})"]
        if rec["mood"] != "none":
            bits.append(f"in a {rec['mood']} mood")
        stress_w = (rec["stress"] or {}).get("words") or ""
        if stress_w and stress_w not in ("content",):
            bits.append(f"{stress_w}")
        if rec.get("distress"):
            # Audit R4: distress is a fact about this dwarf, on
            # their own line — not only a "Noted:" line elsewhere
            # (06-28: the model dropped the note and kept the
            # manager/stockpile attempts beside it).
            bits.append(f"in distress, {rec['distress']}")
        if rec["wounds"]:
            w = (f"{rec['wounds']} wound"
                 f"{'s' if rec['wounds'] > 1 else ''}")
            wound_new = any(c["kind"] == "wound_new"
                            for c in rec["changes"])
            if not wound_new:
                since = None
                if isinstance(rec.get("unit_id"), int):
                    since = wound_since.get(rec["unit_id"])
                if since is None:
                    since = wound_since_by_name.get(rec["name"])
                if since:
                    date, first = since
                    w += (f" (first recorded {date})" if first
                          else f" (since {date})")
                else:
                    w += " (since before today)"
            bits.append(w)
        # Needs, once each, strongest first (most_unmet_needs
        # already sorts by focus, lowest first): a need that is
        # both current and newly unmet is listed once here, and
        # its "went without" change below is skipped (audit R6 —
        # 04-01 carried ~11 need fragments per dwarf and the
        # model summarized them vaguely). A need gnawing hard
        # (focus at or below -5000; 22 of 254 unmet needs in the
        # store sit there, the rest mostly -1000..-5000) says so.
        current_needs = {n["need"] for n in rec["needs"]}
        for n in rec["needs"]:
            need_new = any(
                c["kind"] == "need_unmet"
                and n["need"] in c["text"]
                for c in rec["changes"])
            focus = n.get("focus")
            strength = (" badly" if isinstance(focus, int)
                        and focus <= -5000 else "")
            bits.append(f"going without {n['need']}{strength}"
                        + ("" if need_new
                           else " (ongoing, not new today)"))
        if rec["job"]:
            # Audit R5: the job in plain words, never the raw
            # token — "working as Fish" became "Ral cleans fish"
            # in three entries. Mapped tokens render bare
            # ("fishing"); unmapped ones render as
            # "working as <words>".
            words = job_words(rec["job"])
            if rec["job"] in JOB_VERBS:
                bits.append(words)
            elif words:
                bits.append(f"working as {words}")
        for ch in rec["changes"]:
            if ch["kind"] == "need_unmet" \
                    and ch["text"].startswith("went without "):
                if ch["text"][len("went without "):] \
                        in current_needs:
                    continue
            bits.append(ch["text"])
        # What the dwarf DID today (from the day's job completions)
        # comes before the state: the per-dwarf section is what
        # happened to them, not their stat line.
        for did in rec.get("did") or []:
            job = _completion_phrase(did["job"], did.get("pos"),
                                     workshop_map, queue_kinds)
            n = did["count"]
            if did.get("routine"):
                bits.append(f"{job} {n} "
                            f"time{'s' if n > 1 else ''} today")
            else:
                bits.append(f"finished {job}"
                            + (f" {n} times" if n > 1 else ""))
        # Social ties (friendships, grudges — hf_visual), with the
        # other dwarf's state, so the entry can write the human
        # consequence. People outside the fort are a count only:
        # their names and stories are not in the record, and the
        # model must not invent them.
        for tie in rec.get("social") or []:
            tbits = f"{tie['label']} of {tie['name']}"
            if tie.get("mood") and tie["mood"] != "none":
                tbits += f" (in a {tie['mood']} mood)"
            if tie.get("stress"):
                tbits += f" ({tie['stress']})"
            if tie.get("changed"):
                tbits += " — changed today"
            tbits += (" (new today)" if tie.get("new_today")
                      else " (long-standing, not new today)")
            bits.append(tbits)
        if rec.get("social_outside"):
            n = rec["social_outside"]
            bits.append(
                f"has {n} {'person' if n == 1 else 'people'} "
                "elsewhere, outside the fort (a count only — "
                "their names and stories are not in the record)")
        for t in rec.get("traits") or []:
            bits.append(f"{t['facet']} {t['words']} ({t['value']})")
        for e in rec.get("emotions") or []:
            thought = (f" — {e['thought']}" if e.get("thought")
                       else "")
            # A feeling is a dated event, not a current state:
            # Zulban's uneasiness was felt on the 8th of Hematite
            # and carried forward undated into June, where the
            # model reported it as the 26th's (re-check 5). The
            # date rides with the feeling, from its own year_tick.
            # An emotion with no recorded tick keeps no date —
            # undated is honest, a guessed date is not.
            when = ""
            yt = e.get("year_tick")
            ey = e.get("year")
            if isinstance(yt, int):
                if not isinstance(ey, int):
                    ey = int((summary.get("date") or "125").split(
                        "-")[0])
                when = f" ({date_words(yt, ey)})"
            bits.append(f"felt {e['type']}{thought}{when}")
        # Personal goals and notable skills: the dwarf's own
        # ambitions, not a stat. The goal names are verb phrases
        # ("Create Great Artwork", "Be a Father"), so they render
        # lowercased after "wants to". Skills render with their
        # game rating word ("adequate"), best first.
        if rec.get("goal"):
            bits.append(f"wants to {str(rec['goal']).lower()}")
        if rec.get("skills"):
            sk = ", ".join(
                f"{str(s.get('skill') or '').lower().replace('_', ' ')}"
                f" ({str(s.get('rating') or '').lower()})"
                for s in rec["skills"] if s.get("skill"))
            if sk:
                bits.append(f"skilled at {sk}")
        for rel in rec["relations"]:
            rbits = f"{rel['type']} {rel['name']}"
            word = ("devotion" if rel["type"] == "deity"
                    else "bond")
            if rel.get("in_fort"):
                if rel.get("mood") and rel["mood"] != "none":
                    rbits += f" (in a {rel['mood']} mood)"
                if rel.get("stress"):
                    rbits += f" ({rel['stress']})"
                if rel.get("changed"):
                    rbits += " — changed today"
                rbits += (" (new today)" if rel.get("new_today")
                          else f" (a long-standing {word}, "
                          "not new today)")
            else:
                rbits += (" (not in the fort; new today)"
                          if rel.get("new_today")
                          else " (not in the fort; a long-standing "
                          f"{word}, not new today)")
            bits.append("close to " + rbits)
        marker = "FEATURED" if rec.get("featured") else "stable"
        dwarf_lines.append(f"[{marker}] " + "; ".join(bits) + ".")
    if dwarf_lines:
        parts.append("The dwarves:\n" + "\n".join(dwarf_lines))
    if feed["threads"]:
        tlines = []
        for t in feed["threads"]:
            if t.get("kind") == "unmet_need":
                # Re-check 4 fix F: unmet_need threads duplicate
                # the dwarf lines without focus values — the exact
                # lines the model misread on 04-01. Kept in the
                # feed dict, never rendered into the prompt.
                continue
            if t.get("since"):
                since = (f" (first recorded {t['since']})"
                         if t.get("first_sighting")
                         else f" since {t['since']}")
            else:
                since = ""
            tlines.append(
                f"{t['subject']}: {t['kind']} — {t['detail']}{since}")
        parts.append("Open threads:\n" + "\n".join(tlines))
    if feed["recent_entries"]:
        rlines = []
        for e in feed["recent_entries"]:
            rlines.append(f"--- {e['date']} ---\n{e['body']}")
        parts.append("Recent entries (for continuity):\n"
                     + "\n".join(rlines))
    parts.append(
        "Write today's diary entry now. Prose, not a list.")
    return [{"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(parts)}]


# Debris the AI must never emit (the same boundary as
# clean_diary_text): internal references, log noise, raw game
# internals. An entry containing any of these is rejected, not
# cleaned — the model misbehaving is a signal, not a typo.
_AI_DEBRIS = ("PLANNER.md", "(logged)", "window error",
              "keystroke", "unit_id", "job_type",
              "stress_category", "tick", "dfhack")


def _name_tokens(name: str) -> list[str]:
    """The whitespace tokens of a dwarf's name that are long enough
    to identify them (length >= 3 — the two-letter prefixes some
    names carry, e.g. \"äs\" in \"äs Oslanlumash\", are not names the
    AI would write)."""
    return [t for t in (name or "").split() if len(t) >= 3]


def _dwarf_named(body: str, name: str,
                 token_counts: dict[str, int]) -> bool:
    """Is this dwarf named in the entry? The full name counts, and
    so does any single token of their name that no other dwarf in
    the feed shares — the AI writes \"Mestthos\" as readily as
    \"Mestthos Zassezuk\", and the validator's job is to confirm the
    AI actually wrote about the dwarf, not to enforce a naming
    convention the prompt never required. A shared token does not
    count (it names no one in particular). Matches are whole-word,
    so \"Olon\" does not match \"Olon\" inside another word."""
    if not name:
        return False
    if name in body:
        return True
    for tok in _name_tokens(name):
        if token_counts.get(tok, 0) != 1:
            continue
        if re.search(rf"\b{re.escape(tok)}\b", body):
            return True
    return False


# The feed's pre-computed group counts, with the words an entry
# would use to claim the condition. The validator checks "all /
# every / none" claims against these counts — the backstop for the
# run-060346 overgeneralization (six of seven wounded, entry said
# "every dwarf ... carrying an injury"). The patterns are narrow
# on purpose: the quantifier and the condition must be in the same
# short clause (no comma, no sentence break between them) and the
# condition must follow a linking verb ("are wounded", "was
# stressed", "is carrying an injury") — so "all seven dwarves
# gathered around the wounded one" (no linking verb) and "all
# seven are here, and six are wounded" (comma) do not fire. An
# exception in the gap ("every dwarf but Ral is wounded") is a
# TRUE claim when six of seven are wounded, so the gap refuses
# to cross but/except/save. A fired check rejects the entry,
# like every other validator rule.
_GROUP_KEYWORDS = {
    # "mark" is a wound word too (the 04-05 entry said "seven
    # dwarves and seven wounds" and "every soul ... carrying
    # exactly one mark" — the old list missed "mark" entirely, so
    # neither the all-check nor the bare-count check fired). "hurt"
    # / "cut" / "bruise" are the same class: a dwarf the entry
    # describes as hurt, cut, or bruised is a wounded dwarf. The
    # patterns that use these keywords always require a linking
    # verb or a number next to them, so "cut wood" or "mark the
    # day" never fire.
    "wounded": (r"(?:wound(?:s|ed|ing)?|injur(?:y|ies|ed|ing)?|"
                r"marks?|hurt(?:s|ing)?|cut(?:s|ting)?|"
                r"bruis(?:e|es|ed|ing)?)"),
    "idle": r"idle",
    "stressed": r"stress(?:ed|ful)?",
    "mood": r"mood",
    "thirsty": r"thirst(?:y|ier)?",
    "hungry": r"hungr(?:y|ier)?",
}


# Number words the diary AI writes ("seven", "thirty-nine", "a
# hundred and twenty-four") — the validator must read numbers as
# words, not just digits, because the 04-05 entry wrote every
# number as words and the old validator only understood digits
# (it understood no numbers at all — bare counts were never
# checked). _find_numbers returns [(value, start, end)] over the
# body text, where start/end are character offsets into the body
# (lowered first by the caller when needed — the values are the
# same either way).
_NUMBER_ONES = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_NUMBER_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_NUMBER_WORD_RE = (
    r"(?:\d+|zero|one|two|three|four|five|six|seven|eight|nine|"
    r"ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|"
    r"sixty|seventy|eighty|ninety|hundred|thousand|and|a|an)"
)


def _parse_number_run(tokens: list[str]) -> int | None:
    """English number words to an int (0..9999). "a"/"an" count as
    1 only before hundred/thousand ("a hundred" is 100; a lone
    "a" is not a number and never reaches this function). "and"
    is skipped. Returns None when the tokens are not a number
    (e.g. a bare "and")."""
    total = 0
    current = 0
    seen = False
    for tok in tokens:
        if tok in ("and",):
            continue
        if tok in ("a", "an"):
            # "a hundred": 1 * 100. A lone "a" never starts a run
            # (the scanner requires hundred/thousand after it).
            current += 1
            seen = True
        elif tok in _NUMBER_ONES:
            current += _NUMBER_ONES[tok]
            seen = True
        elif tok in _NUMBER_TENS:
            current += _NUMBER_TENS[tok]
            seen = True
        elif tok == "hundred":
            current = (current or 1) * 100
            seen = True
        elif tok == "thousand":
            total += (current or 1) * 1000
            current = 0
            seen = True
        else:
            return None
    if not seen:
        return None
    return total + current


def _find_numbers(body: str) -> list[tuple[int, int, int]]:
    """[(value, start, end)] for every number in the body: digit
    runs, and runs of number words ("thirty-nine" tokenises to
    thirty + nine; "a hundred and twenty-four" is one run).
    A run starts on a digit or a number word; "a"/"an" start a run
    only when the next token is hundred/thousand. Runs are maximal
    — "thirty-nine from thirty-three" is two numbers, not one.
    Digit ordinals ("the 12th", "the 20th") are dates, not
    numbers, and are skipped: the tokenizer splits "12th" into
    "12" + "th", and without the skip the stock check reads the
    date as a level — which makes bar (2), the date riding with
    the fact in the same sentence, unimplementable. Word ordinals
    ("first") already return no number."""
    lowered = body.lower()
    tokens = [(m.group(0), m.start(), m.end())
              for m in re.finditer(r"[a-z]+|\d+", lowered)]
    out: list[tuple[int, int, int]] = []
    i = 0
    while i < len(tokens):
        tok, start, _ = tokens[i]
        if tok.isdigit():
            # Ordinal date, not a quantity: "12th" is the day, and
            # the two characters right after the digits are the
            # suffix. A space or punctuation intervenes in every
            # legitimate quantity use ("drink 12", "12 dwarves"),
            # so the adjacency is the test.
            if lowered[tokens[i][2]:tokens[i][2] + 2] in (
                    "th", "st", "nd", "rd"):
                i += 1
                continue
            out.append((int(tok), start, tokens[i][2]))
            i += 1
            continue
        if tok not in _NUMBER_ONES and tok not in _NUMBER_TENS \
                and tok not in ("hundred", "thousand", "a", "an"):
            i += 1
            continue
        if tok in ("a", "an"):
            # Only a number when hundred/thousand follows.
            if i + 1 >= len(tokens) \
                    or tokens[i + 1][0] not in ("hundred",
                                                "thousand"):
                i += 1
                continue
        # Consume the maximal run of number words. "and" joins a
        # run only after hundred/thousand ("a hundred and
        # twenty-four" is one number); "one and two" is two numbers,
        # not three — the "and" there ends the run. A sentence
        # boundary also ends a run: "thirty-three. Six of the
        # seven" is 33 and 6, not 39 — the tokenizer drops the
        # punctuation, so the gap between tokens is checked for
        # ".", "!", "?", or a newline.
        run = [tok]
        end = tokens[i][2]
        j = i + 1
        while j < len(tokens):
            gap = lowered[tokens[j - 1][2]:tokens[j][1]]
            if any(c in gap for c in ".!?\n"):
                break
            t2 = tokens[j][0]
            if t2 in _NUMBER_ONES or t2 in _NUMBER_TENS \
                    or t2 in ("hundred", "thousand"):
                run.append(t2)
                end = tokens[j][2]
                j += 1
            elif t2 == "and" and run and run[-1] in (
                    "hundred", "thousand"):
                run.append(t2)
                end = tokens[j][2]
                j += 1
            else:
                break
        value = _parse_number_run(run)
        if value is not None:
            out.append((value, start, end))
        i = j
    return out


# Verbs that link a count to a condition ("six are wounded",
# "six carried wounds", "five sat idle"). The list covers the
# linking verbs and the past-tense/stance verbs the model uses
# for the same claim — "Six dwarves carried wounds" is a wound
# count, not a population count, and the 04-01 probe entry's
# "Five of the seven sat idle" is an idle count. One constant
# for the all-pattern and the bare-count pattern, so they cannot
# drift apart again.
_GROUP_VERBS = (r"(?:are|were|is|was|carrying|have|has|had|"
                r"carried|bore|nursed|showed|suffered|sat|stood|"
                r"lay)")


def _check_group_claims(body: str, feed: dict[str, Any]) -> None:
    """Raise ValueError when the entry claims all (or none) of the
    dwarves share a condition the feed's counts contradict."""
    counts = {g["key"]: g for g in feed.get("group_counts") or []}
    if not counts:
        return
    lowered = body.lower()
    # The gap between the quantifier and the verb must not contain
    # an exception ("but Ral", "except Ral", "all but one") —
    # "every dwarf but Ral is wounded" is TRUE when six of seven
    # are wounded, and the corrected 04-01 entry says exactly
    # that. The tempered token refuses to cross but/except/save.
    gap = r"(?:(?!\b(?:but|except|save)\b)[^.!?,\n]){0,45}"
    for key, keyword in _GROUP_KEYWORDS.items():
        g = counts.get(key)
        if g is None:
            continue
        verb = (rf"(?:{_GROUP_VERBS})\s+"
                r"(?:all\s+)?(?:carrying\s+|an?\s+)?"
                # "exactly one mark", "just one cut": an adverb
                # and a number between the verb and the condition
                # is still the same claim.
                r"(?:exactly\s+|just\s+|only\s+|really\s+)?"
                rf"(?:(?:{_NUMBER_WORD_RE})\s+)?")
        if g["count"] < g["total"]:
            pat = (rf"\b(all|every)\b{gap}\b{verb}"
                   rf"(?:{keyword})\b")
            if re.search(pat, lowered):
                raise ValueError(
                    f"diary AI entry claims all dwarves are "
                    f"{key} but only {g['count']} of {g['total']} "
                    f"are")
        if g["count"] > 0:
            pat = (r"\b(none|no dwarf|not a single dwarf|"
                   rf"not one dwarf)\b{gap}\b(?:{keyword})\b")
            if re.search(pat, lowered):
                raise ValueError(
                    f"diary AI entry claims no dwarf is {key} "
                    f"but {g['count']} of {g['total']} are")
    # Bare counts (the 04-05 gap): "seven wounds", "six wounded",
    # "six of the dwarves wounded", "six of my seven dwarves are
    # carrying wounds" — a number next to the condition, with no
    # all/every/none quantifier. The number must equal the feed's
    # count for that condition. The number comes from the scanner
    # (_find_numbers), not a regex, because the entry writes
    # numbers as words ("seven", "thirty-nine"). Guards: the
    # number and the keyword must be in the same short clause (no
    # sentence break, comma, semicolon, or "and" between them —
    # "six dwarves ate, and one was wounded" is not a claim that
    # six are wounded); a number followed by "apiece"/"each" is a
    # per-dwarf distribution ("one wound apiece" means each dwarf
    # has one, not that one dwarf is wounded) and is skipped.
    for value, start, end in _find_numbers(body):
        # Partitive guard (the 04-01 probe): in "Six of the seven
        # are carrying wounds", the SEVEN is the total, not the
        # count — the six before "of the" is the count, and it
        # gets its own check. A number preceded by "<number> of
        # the/my" is the total of a partitive, never a claim.
        before = lowered[max(0, start - 16):start]
        if re.search(rf"(?:{_NUMBER_WORD_RE})\s+of\s+"
                     r"(?:the|my)\s+$", before):
            continue
        after = lowered[end:end + 60]
        # The clause after the number, cut at the first sentence
        # break, comma, semicolon, or "and".
        cut = re.split(r"[.!?,\n;]|\band\b", after, maxsplit=1)[0]
        for key, keyword in _GROUP_KEYWORDS.items():
            g = counts.get(key)
            if g is None:
                continue
            m = re.match(
                rf"\s*(?:of\s+(?:the|my)\s+)?"
                # The inner total ("six of the SEVEN are ...") —
                # a bare number with no noun after it. It must be
                # consumable on its own: the old form required a
                # citizen noun after the inner number, so "seven
                # are carrying" matched nothing and a wrong "six"
                # in "Six of the seven are carrying wounds"
                # sailed through unchecked.
                rf"(?:(?:{_NUMBER_WORD_RE})\s+)?"
                rf"(?:(?:dwarves?|souls?|citizens?)\s+)?"
                rf"(?:(?:{_GROUP_VERBS})\s+"
                rf"(?:all\s+)?(?:carrying\s+|an?\s+)?)?"
                rf"(?:{keyword})\b", cut)
            if not m:
                continue
            # "one wound apiece" / "two cuts each" is per-dwarf.
            tail = cut[m.end():m.end() + 12]
            if re.match(r"\s*(?:apiece|each)\b", tail):
                continue
            if value != g["count"]:
                raise ValueError(
                    f"diary AI entry claims {value} {key} but "
                    f"the feed says {g['count']} of {g['total']} "
                    f"are")
    # Bare zero: "no wounds", "not a single wound".
    for key, keyword in _GROUP_KEYWORDS.items():
        g = counts.get(key)
        if g is None or g["count"] == 0:
            continue
        if re.search(rf"\b(?:no|not a single)\s+(?:{keyword})\b",
                     lowered):
            raise ValueError(
                f"diary AI entry claims no dwarf is {key} but "
                f"{g['count']} of {g['total']} are")


def _queued_job_totals(decisions: list[dict[str, Any]]
                       ) -> tuple[dict[str, int], dict[str, int],
                                  int]:
    """Queued jobs from the feed's decisions: ({job: count},
    {location: count}, grand total). Same source as the prompt's
    "Queued at ..." rendering (same _QUEUE_PHRASE), so the
    validator and the model agree on the numbers. A decision
    whose phrase does not parse is not a queue_job the prompt
    showed — it is skipped, never guessed."""
    per_job: dict[str, int] = {}
    per_loc: dict[str, int] = {}
    total = 0
    for dec in decisions or []:
        if dec.get("action") != "queue_job":
            continue
        phrase = clean_diary_text(
            dec.get("decision") or dec.get("action") or "")
        m = _QUEUE_PHRASE.match(phrase)
        if not m:
            continue
        job, n, loc = m.group(1), int(m.group(2)), m.group(3)
        per_job[job] = per_job.get(job, 0) + n
        per_loc[loc] = per_loc.get(loc, 0) + n
        total += n
    return per_job, per_loc, total


# Job nouns the entry uses, mapped to the queue_job names the
# feed carries. Only these three are checked: they are the ones
# the 04-01 and 04-05 entries got wrong (beds, barrels, brews).
# Any other job the entry names is not checked — the validator
# does not guess a mapping it was not given.
_JOB_NOUNS = {
    "bed": "make_bed", "beds": "make_bed",
    "barrel": "make_barrel", "barrels": "make_barrel",
    "brew": "brew", "brews": "brew",
    "brewing": "brew", "brewings": "brew",
}

_STOCK_WORDS = ("drink", "food", "wood", "stone")
_CITIZEN_WORDS = ("dwarf", "dwarves", "citizen", "citizens",
                  "soul", "souls")


def _sentence_end(text: str, pos: int) -> int:
    """Index just past the next sentence break at or after pos
    (or pos + 120 when the sentence runs long — the job-context
    check needs the whole sentence, and the number's own clause
    can sit well before the word "queue")."""
    ends = [i for i in (text.find(".", pos), text.find("!", pos),
                        text.find("?", pos), text.find("\n", pos))
            if i != -1]
    end = min(ends) + 1 if ends else len(text)
    return min(end, pos + 120)


def _check_numbers(body: str, feed: dict[str, Any]) -> None:
    """Raise ValueError when the entry states a number the feed
    contradicts. The feed is the ground truth (the same facts the
    model was shown): the ledger's start/end stocks, the group
    counts (already covered by _check_group_claims — this function
    does stocks, population, arrivals, and queued jobs), the
    summary's arrivals, and the queued-job totals. A number the
    feed cannot verify (no ledger value for that metric, no
    queue_job decisions at all) is skipped, never guessed — the
    validator checks stated numbers against given facts, and
    silence where there are no facts. Numbers are read as words
    as well as digits: the 04-05 entry wrote "thirty-nine",
    "thirty-two", "a hundred and twenty-four", and every one of
    them was an old entry's number, not the run's."""
    summary = feed.get("summary") or {}
    start = summary.get("stocks_start") or {}
    end = summary.get("stocks_end") or {}
    lowered = body.lower()

    def _num(v: Any) -> int | None:
        return v if isinstance(v, int) else None

    # -- stocks: a number after a stock word in the same sentence.
    # The marker between the stock word and the number says which
    # end it is: "from" is the day's start, "to"/"at"/"up to" and
    # the rest are the day's end, and a number hard against the
    # stock word ("drink 68") is the end. A number with no marker
    # in the gap is skipped — it may be a mid-day value the feed
    # does not carry, and the validator does not guess.
    for value, num_start, num_end in _find_numbers(body):
        window = lowered[max(0, num_start - 160):num_start]
        # The stock word must be in the same sentence as the
        # number: a sentence break between them means the number
        # belongs to another sentence's claim.
        sent = max(window.rfind("."), window.rfind("!"),
                   window.rfind("?"), window.rfind("\n"))
        window = window[sent + 1:]
        metric = None
        metric_at = -1
        for word in _STOCK_WORDS:
            at = window.rfind(word)
            if at > metric_at:
                metric_at, metric = at, word
        if metric is None:
            continue
        gap = window[metric_at + len(metric):]
        # Last marker in the gap wins ("went from thirty-eight
        # down to thirty-three": the 38 is "from", the 33 is "to").
        markers = [(m.start(), m.group(0)) for m in re.finditer(
            r"\b(from|to|at|holds?|sits?|stands?|remains?|now|"
            r"left|around|about)\b", gap)]
        if not markers:
            if gap.strip(" :") == "":
                # "drink 68": hard against the stock word.
                which = "end"
            else:
                continue
        else:
            which = ("start" if markers[-1][1] == "from"
                     else "end")
        actual = _num((start if which == "start" else end)
                      .get(metric))
        if actual is None:
            continue
        if value != actual:
            raise ValueError(
                f"diary AI entry says {metric} {value} ({which}) "
                f"but the feed says {metric} {actual}")
    # -- stocks: zero claims ("no drink left", "drink ran out").
    for m in re.finditer(
            r"\bno\s+(drink|food|wood|stone)\b(?:\s+left)?"
            r"|\b(drink|food|wood|stone)\s+ran out\b"
            r"|\bran out of\s+(drink|food|wood|stone)\b"
            r"|\bnot a drop of\s+(drink|food|wood|stone)\b",
            lowered):
        metric = next(g for g in m.groups() if g)
        actual = _num(end.get(metric))
        if actual is None:
            continue
        if actual != 0:
            raise ValueError(
                f"diary AI entry says no {metric} left but the "
                f"feed says {metric} {actual}")
    # -- population: a number hard against a citizen noun.
    # Guard (the 04-01 probe): "Six dwarves carried wounds" is
    # a wound count, not a population count — when a group
    # condition word follows the noun in the same clause, the
    # number belongs to the group check, not this one. Without
    # the guard the population check fires first on a sentence
    # the group check already accepts.
    pop = _num(end.get("population"))
    if pop is None:
        pop = _num(start.get("population"))
    if pop is not None:
        for value, num_start, num_end in _find_numbers(body):
            after = lowered[num_end:num_end + 14]
            m = re.match(r"\s*(dwarf|dwarves|citizen|citizens|"
                         r"soul|souls)\b", after)
            if not m:
                continue
            rest = lowered[num_end + m.end():
                           num_end + m.end() + 40]
            clause = re.split(r"[.!?,\n;]|\band\b", rest,
                              maxsplit=1)[0]
            if any(re.search(rf"\b(?:{kw})\b", clause)
                   for kw in _GROUP_KEYWORDS.values()):
                continue
            if value != pop:
                raise ValueError(
                    f"diary AI entry says {value} "
                    f"{m.group(1)} but the feed says {pop} "
                    f"citizens")
    # -- arrivals: "three new citizens", "three migrants arrived".
    arrivals = summary.get("arrivals")
    if isinstance(arrivals, int):
        for value, num_start, num_end in _find_numbers(body):
            after = lowered[num_end:num_end + 30]
            m = re.match(
                r"\s*new\s+(?:dwarf|dwarves|citizen|citizens|"
                r"soul|souls|migrant|migrants|newcomer|newcomers)\b"
                r"|\s*(?:dwarf|dwarves|citizen|citizens|soul|souls|"
                r"migrant|migrants|newcomer|newcomers)\s+"
                r"(?:arrived|joined|came)\b", after)
            if m and value != arrivals:
                raise ValueError(
                    f"diary AI entry says {value} new arrivals "
                    f"but the feed says {arrivals}")
    # -- queued jobs: "one job" in a queue context, and per-type
    # counts ("two beds ... in the queue"). The totals are the
    # feed's queue_job decisions (same source as the prompt's
    # "Queued at ..." lines). No queue_job decisions in the feed
    # means no ground truth — skip, do not guess.
    per_job, per_loc, total = _queued_job_totals(
        summary.get("decisions") or [])
    if total:
        for value, num_start, num_end in _find_numbers(body):
            after = lowered[num_end:num_end + 16]
            if not re.match(r"\s*jobs?\b", after):
                continue
            sent_start = max(lowered.rfind(".", 0, num_start),
                             lowered.rfind("!", 0, num_start),
                             lowered.rfind("?", 0, num_start),
                             lowered.rfind("\n", 0, num_start))
            sentence = lowered[sent_start + 1:
                               _sentence_end(lowered, num_end)]
            if not re.search(
                    r"\b(set|put|queued?|started|going)\b",
                    sentence):
                continue
            # A named workshop scopes the claim to that
            # location's total; a generic "one of the workshops"
            # is the grand total.
            expect = total
            for loc, n in per_loc.items():
                if loc.lower() in sentence:
                    expect = n
                    break
            if value != expect:
                raise ValueError(
                    f"diary AI entry says {value} "
                    f"{'job' if value == 1 else 'jobs'} queued "
                    f"but the feed says {expect}")
        for value, num_start, num_end in _find_numbers(body):
            after = lowered[num_end:num_end + 16]
            m = re.match(r"\s*(bed|beds|barrel|barrels|brew|brews|"
                         r"brewing|brewings)\b", after)
            if not m:
                continue
            sent_start = max(lowered.rfind(".", 0, num_start),
                             lowered.rfind("!", 0, num_start),
                             lowered.rfind("?", 0, num_start),
                             lowered.rfind("\n", 0, num_start))
            sentence = lowered[sent_start + 1:
                               _sentence_end(lowered, num_end)]
            if not re.search(r"\bqueue", sentence):
                continue
            job = _JOB_NOUNS[m.group(1)]
            expect = per_job.get(job, 0)
            if value != expect:
                raise ValueError(
                    f"diary AI entry says {value} {m.group(1)} "
                    f"queued but the feed says {job} x{expect}")


def _validate_ai_entry(text: str, feed: dict[str, Any]) -> str:
    """Validate the model's diary prose. Returns the cleaned body.
    Raises ValueError when the output is unusable — the caller logs
    and skips the day rather than writing a bad entry."""
    body = (text or "").strip()
    if len(body) < 120:
        raise ValueError(
            f"diary AI entry too short ({len(body)} chars)")
    if len(body) > 4000:
        raise ValueError(
            f"diary AI entry too long ({len(body)} chars)")
    lowered = body.lower()
    for pat in _AI_DEBRIS:
        if pat.lower() in lowered:
            raise ValueError(
                f"diary AI entry contains debris: {pat!r}")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    list_lines = sum(
        1 for ln in lines
        if ln.lstrip().startswith(("- ", "* ", "• "))
        or re.match(r"^\d+[.)] ", ln.lstrip()))
    if lines and list_lines / len(lines) > 0.5:
        raise ValueError("diary AI entry reads as a list, not prose")
    featured = [r for r in feed["dwarves"] if r.get("featured")]
    if featured:
        # A token counts only when it belongs to one dwarf in the
        # feed (a shared first name names no one in particular).
        token_counts: dict[str, int] = {}
        for r in feed["dwarves"]:
            for tok in _name_tokens(r.get("name") or ""):
                token_counts[tok] = token_counts.get(tok, 0) + 1
        named = [r for r in featured
                 if r["name"] and _dwarf_named(body, r["name"],
                                               token_counts)]
        if not named:
            raise ValueError(
                "diary AI entry names none of the featured dwarves")
    _check_group_claims(body, feed)
    _check_numbers(body, feed)
    return body


def write_ai_entry(client: Any, feed: dict[str, Any],
                   state_dir: str | Path,
                   max_attempts: int = 3) -> Path:
    """Write today's diary entry with the model. Builds the prompt
    from the feed, calls the model, validates the prose, stores it.
    Raises on model failure or bad output — the caller logs and
    skips the day; a template list is never written instead.

    A rejected entry is retried with a correction, not silently
    dropped: the model is told exactly which number it got wrong
    and is asked to rewrite it from the facts (the 04-05 entry's
    numbers were wrong in every line, and a single attempt would
    have left the day unwritten). At most max_attempts calls; after
    the last rejection the day is skipped, as before.

    The stored body carries the day's ledger line (the same line
    the template renderer writes, from the same summary the
    validator checked) — the machine-readable record, so a later
    rebuild recovers the day's numbers from the entry instead of
    the Store's stale trend sample. The gap marker goes through
    write_ai_body directly and gets no ledger line: its summary's
    stocks are not the day's.
    """
    messages = diary_prompt(feed)
    last_exc: Exception | None = None
    for _attempt in range(max_attempts):
        text = client.chat(messages)
        try:
            body = _validate_ai_entry(text, feed)
        except ValueError as exc:
            last_exc = exc
            messages = messages + [
                {"role": "assistant", "content": text},
                {"role": "user",
                 "content": (
                     "Your entry was rejected: "
                     f"{exc}. Rewrite it, keeping every number "
                     "exactly as given in the facts above — do not "
                     "copy numbers from the recent entries.")}]
            continue
        ledger = _ledger_line(feed["summary"])
        if ledger:
            body = body.rstrip() + "\n\n" + ledger
        return write_ai_body(state_dir, feed["summary"], body)
    raise last_exc  # type: ignore[misc]


def parse_entries(md_text: str) -> list[dict[str, str]]:
    """Parse diary.md into [{date, date_words, body}]."""
    entries: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in md_text.splitlines():
        m = re.match(r"^## (\d+-\d+-\d+) — (.*)$", line)
        if m:
            if current is not None:
                entries.append(current)
            current = {"date": m.group(1),
                       "date_words": m.group(2), "body": ""}
            continue
        if current is not None:
            current["body"] += line + "\n"
    if current is not None:
        entries.append(current)
    for e in entries:
        e["body"] = e["body"].strip() + "\n"
    return entries


# ----------------------------------------------------------------------
# diary.html: one self-contained file, DF-themed.
# ----------------------------------------------------------------------

def render_html(md_path: str | Path, html_path: str | Path,
                fort_name: str = "") -> Path:
    """Generate diary.html from diary.md. One file, no server, no
    external assets: the entries are embedded as JSON, the styling
    is inline, and the reading pane is driven by a small script
    (index click-to-read, prev/next day, jump-to-latest)."""
    md_path = Path(md_path)
    html_path = Path(html_path)
    entries = parse_entries(md_path.read_text()) if md_path.exists() \
        else []
    # Defensive: the file should already be chronological (the
    # store sorts on every write), but a hand-edited file may not
    # be — and the reader's "latest" is the last entry in the
    # list, so sort here too rather than trusting file order.
    entries.sort(key=lambda e: _date_key(e["date"]))
    fort = fort_name or "the fort"
    # Escape "</" after json.dumps (2026-11-27, external review
    # Table 6 row 5): the entries are embedded raw inside a script
    # block, so an entry containing "</script>" broke out of it.
    # "<\/" is the same string in a JS string literal but does not
    # close the script element in HTML parsing.
    data = json.dumps(entries).replace("</", "<\\/")
    p = DF_PALETTE
    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Diary of {html.escape(fort)}</title>
<style>
  :root {{
    --bg: {p['black']}; --panel: #111111; --ink: {p['lightgray']};
    --dim: {p['darkgray']}; --accent: {p['yellow']};
    --border: {p['brown']}; --header: {p['lightgreen']};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: "Courier New", ui-monospace, monospace;
    font-size: 15px; line-height: 1.45;
  }}
  .screen {{ max-width: 1100px; margin: 0 auto; padding: 12px; }}
  .bar {{
    border: 2px solid var(--border); padding: 6px 12px;
    display: flex; justify-content: space-between; gap: 12px;
    color: var(--header); background: var(--panel);
  }}
  .bar b {{ color: var(--accent); }}
  .cols {{ display: flex; gap: 12px; margin-top: 12px; }}
  .index {{
    flex: 0 0 220px; border: 2px solid var(--border);
    background: var(--panel); padding: 8px; max-height: 70vh;
    overflow-y: auto;
  }}
  .index h2 {{ margin: 0 0 8px; font-size: 15px; color: var(--accent); }}
  .index a {{
    display: block; color: var(--ink); text-decoration: none;
    padding: 2px 4px; white-space: nowrap;
  }}
  .index a:hover, .index a.active {{
    background: {p['blue']}; color: {p['white']};
  }}
  .reader {{
    flex: 1; border: 2px solid var(--border);
    background: var(--panel); padding: 12px 16px; min-height: 70vh;
  }}
  .reader h2 {{ margin: 0 0 4px; color: var(--header); font-size: 17px; }}
  .reader .meta {{ color: var(--dim); margin-bottom: 12px; }}
  .reader p {{ margin: 0 0 10px; white-space: pre-wrap; }}
  .nav {{ margin-top: 16px; color: var(--dim); }}
  .nav a {{ color: var(--accent); text-decoration: none; margin-right: 16px; }}
  .nav a:hover {{ text-decoration: underline; }}
  .empty {{ color: var(--dim); }}
</style>
</head>
<body>
<div class="screen">
  <div class="bar">
    <span>Diary of <b>{html.escape(fort)}</b></span>
    <span id="bar-date"></span>
    <span><a href="#" id="jump-latest" style="color: var(--accent)">latest</a></span>
  </div>
  <div class="cols">
    <div class="index"><h2>Entries</h2><div id="index"></div></div>
    <div class="reader">
      <h2 id="entry-title"></h2>
      <div class="meta" id="entry-meta"></div>
      <div id="entry-body"></div>
      <div class="nav">
        <a href="#" id="prev">&lt; prev day</a>
        <a href="#" id="next">next day &gt;</a>
        <a href="#" id="latest">jump to latest</a>
      </div>
    </div>
  </div>
</div>
<script>
var ENTRIES = {data};
var cur = ENTRIES.length - 1;
function esc(s) {{
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
          .replace(/>/g, '&gt;');
}}
function show(i) {{
  if (!ENTRIES.length) {{
    document.getElementById('entry-title').textContent = 'No entries yet';
    document.getElementById('entry-body').innerHTML =
      '<p class="empty">The fort has not lived a full day yet.</p>';
    document.getElementById('bar-date').textContent = '';
    return;
  }}
  if (i < 0) i = 0;
  if (i >= ENTRIES.length) i = ENTRIES.length - 1;
  cur = i;
  var e = ENTRIES[i];
  document.getElementById('entry-title').textContent =
    e.date + ' \\u2014 ' + e.date_words;
  document.getElementById('entry-meta').textContent =
    'Entry ' + (i + 1) + ' of ' + ENTRIES.length;
  document.getElementById('bar-date').textContent = e.date;
  var paras = e.body.split(/\\n\\n+/).filter(function (p) {{
    return p.trim().length > 0;
  }});
  document.getElementById('entry-body').innerHTML = paras.map(function (p) {{
    return '<p>' + esc(p.trim()) + '</p>';
  }}).join('');
  var links = document.querySelectorAll('#index a');
  links.forEach(function (a, j) {{
    a.classList.toggle('active', j === i);
  }});
}}
function buildIndex() {{
  var box = document.getElementById('index');
  box.innerHTML = '';
  ENTRIES.forEach(function (e, i) {{
    var a = document.createElement('a');
    a.href = '#';
    a.textContent = e.date;
    a.onclick = function (ev) {{ ev.preventDefault(); show(i); }};
    box.appendChild(a);
  }});
}}
document.getElementById('prev').onclick = function (ev) {{
  ev.preventDefault(); show(cur - 1);
}};
document.getElementById('next').onclick = function (ev) {{
  ev.preventDefault(); show(cur + 1);
}};
document.getElementById('latest').onclick = function (ev) {{
  ev.preventDefault(); show(ENTRIES.length - 1);
}};
document.getElementById('jump-latest').onclick = function (ev) {{
  ev.preventDefault(); show(ENTRIES.length - 1);
}};
buildIndex();
show(ENTRIES.length - 1);
</script>
</body>
</html>
"""
    html_path.write_text(html_doc)
    return html_path
