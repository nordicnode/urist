"""The day's events, read from the daemon's bus event log.

The diary audit of 2026-11-27 found the feed hands the model a
ledger because the feed has never seen the day's events: the
Journal's daemon_events table holds only daemon lifecycle kinds
(snapshot, daemon_started, pause_guard...), so build_daily_summary's
"events" list is empty for every diary date — while the real event
stream sits in the daemon state dir's events.jsonl (the EventBus
persistence), which the diary never read. The 04-01 caravan
("A caravan from Umshadònul has arrived... The merchants need a
trade depot") was in that file and in no diary entry.

This module is the one reader for that file. It takes a (year, day)
and returns the day's events in plain structured form, classified
and noise-filtered:

- reports: fort announcements (caravan, liaison, migrants, a dwarf
  becoming a Herbalist, a workshop the dwarves could not complete).
  Combat chatter between wildlife ("The stray dog misses the hoary
  marmot!") and uninterpretable fragments ("ashen item.") are
  dropped — only the count of dropped lines is kept, never the
  text. Weather ("It has started raining.") is kept apart, as
  weather, so a weather claim can be grounded or left out, never
  invented.
- completions: citizen job completions, grouped by (worker, job).
  Routine jobs (Drink2, Eat, Sleep) are counted with their distinct
  workers — "five of them drank" is groundable from completions,
  not from sampled need lines. Non-routine jobs name the dwarf
  where the record does. The bus log is NOT the whole story for
  completions: its job_completed rows include the poller's
  day-start baseline (every job in progress at the day's first
  tick, worker None — 18 of the 23 bus rows on 04-01 are those,
  not completions) and it misses the still's ConstructBuilding and
  every CustomReaction in year 125. The raw watch log
  (dfh-events.jsonl, passed as watch_log_path) is the fuller
  completion source: it carries job_id, worker, and position, and
  its records are window-deduped (the watcher re-reports the same
  completion ~15-25 times). The merge prefers the raw record
  (it has the position, which the phrase resolver needs) and
  drops bus rows that duplicate it by (job_id, job_type).
- cancellations: a named dwarf cancelling a named job. The reason
  is DROPPED: the report text is truncated ("Needs " cut off), so
  the feed states the cancellation and never the reason.
- arrivals: citizen_new events (dwarves joining, with name and
  profession — this is also where the migrants' names live: the
  Store's lite samples recorded them unnamed, the events name
  them). Wildlife arrivals are counted only.
- departures: citizen_gone events, with reload artifacts filtered
  (a "gone" whose unit has a later citizen_new is the poller
  re-baselining after a reload, not a departure).
- deaths: citizen deaths only (unit_death resolved through the
  name map); wildlife deaths counted only.
- distress: dwarf_distress events (named dwarf + kind).

A missing or unreadable file yields an empty result
(has_events False), never an error: the June/July diary dates have
no event record in either log (the watcher file stops ~06-14 in
game time and the poller recorded nothing on those days), and the
feed must say so rather than fail. Pure functions over the JSONL
files; no game reads, no model calls.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

# Jobs a dwarf does every day without it being news. Counted with
# their distinct workers; never narrated one by one.
ROUTINE_JOBS = frozenset({"Drink2", "Eat", "Sleep"})

# The watcher re-reports one completion many times, and — the
# defect the first dedup rule missed — one real completion can
# span MULTIPLE job ids. A Drink2 is cancelled and re-queued
# when the dwarf is interrupted, and the watcher logs a
# JOB_COMPLETED when a job disappears, whether it completed or
# was cancelled: Olon's 04-01 drink is jobs 85 AND 86 (first
# ticks 101599 and 101863), Lòr's 04-02 drink is jobs 87, 88,
# 89 AND 186. A dedup keyed on job_id counts those as separate
# drinks — the 250-tick rule gave 5 Drink2s on 04-01 and 10 on
# 04-02, while the run logs' drink stock fell by only 3-4 and
# 2-3 over those days. So the key is (worker, job, position)
# with NO job id, and the clustering is single-linkage (chain
# while consecutive ticks are within the window), not a fixed
# window from the first tick.
#
# Two windows, by job kind. Need-jobs (Drink2, Eat, Sleep — the
# ROUTINE_JOBS) get 5000 ticks: a dwarf's need-job records for
# one drink chain across 1322 ticks on 04-02 (Lòr, 102496 to
# 103818), with consecutive gaps up to 303 ticks inside that one
# chain (job 87 Drink2, 102560 to 102863 — the same drink, not
# two completions), and the stock says one dwarf drinks at most
# once a day in this data, so 5000 (about four days) does not
# merge two genuine drinks here — but it is a blunt rule, and it
# WILL undercount a dwarf who genuinely drinks twice in four days
# in some other fort. That is the known trade-off, chosen
# because the stock is the ground truth and it says the
# per-job-id count is wrong by 5x. Queued jobs (CustomReaction,
# ConstructBuilding, GatherPlants, and the rest) get 300 ticks:
# re-report gaps for one queued completion run to 231 ticks, so
# the window must exceed 231 to collapse them, while distinct
# queued completions sharing a key are as close as 670 ticks
# apart (job 90 CustomReaction, 105536 to 106206 — two different
# jobs reusing id 90), so the window must stay below 670 to keep
# them separate. 300 sits between the two. 300 keeps the 04-05
# CustomReaction count at 2 per dwarf (the correct count) and
# still collapses every observed re-report. Job ids are reused
# across types — job 85 is a Drink2, a GatherPlants, and a
# CarveDownwardStaircase on 04-01 — so the type and the position
# are part of the key, never the id alone; and across dwarves —
# Olon's Drink2 job 85 on 04-01 and Zulban's Drink2 job 85 on
# 04-02, both at the drink stockpile [97,95,175] — so the worker
# is part of the key too.
_NEED_JOB_WINDOW_TICKS = 5000
_QUEUED_JOB_WINDOW_TICKS = 300


def _completion_window(job: str) -> int:
    """The single-linkage window for one job type: need-jobs
    (Drink2, Eat, Sleep) chain across cancellations and
    re-queues, so they get the long window; queued jobs get the
    short one."""
    return (_NEED_JOB_WINDOW_TICKS if job in ROUTINE_JOBS
            else _QUEUED_JOB_WINDOW_TICKS)


def _bus_row_duplicates_raw(bus_row: dict[str, Any],
                            raw_clusters: list[dict[str, Any]]
                            ) -> bool:
    """True when a bus job_completed row is the same completion
    as a raw watch-log cluster: same worker, same job, and the
    bus tick inside the cluster's span plus a 300-tick poll lag
    on either side. The job id is never compared — one drink
    spans several job ids. A row with no worker cannot be
    deduped (False): without a worker there is no key to match
    on, and matching on job + tick alone would collapse a real
    completion by another dwarf. Verified safe on year-125 data:
    every None-worker bus row is a baseline-burst row (tick
    100800, dropped by that filter before this check runs), and
    no None-worker row outside the burst matches a raw cluster.
    The one apparent match (Drink2 job 105, bus tick 100800 vs
    Rakust's raw cluster 101020-101036) IS a burst row."""
    uid = bus_row.get("worker_id")
    if not isinstance(uid, int):
        return False
    job = bus_row.get("job") or ""
    tick = bus_row.get("tick")
    if not isinstance(tick, int):
        return False
    for rc in raw_clusters:
        if rc.get("worker_id") != uid or rc.get("job") != job:
            continue
        first = rc.get("tick")
        last = rc.get("last_tick", first)
        if (isinstance(first, int) and isinstance(last, int)
                and first - 300 <= tick <= last + 300):
            return True
    return False

# Report-text substrings that mark a fort announcement (matched
# case-insensitively). Built from the actual year-125 report texts
# in the daemon's events.jsonl (26 distinct texts, 2026-11-27):
# caravan/liaison/migrants, a dwarf becoming something, a build the
# dwarves could not complete, births, deaths, moods, sieges. A text
# matching none of these is dropped — combat chatter between
# wildlife and truncated fragments ("ashen item.") never reach the
# feed. Weather is kept apart under its own bucket.
_KEEP_SUBSTRINGS = (
    "caravan", "liaison", "merchant", "trader", "depot",
    "migrant", "has arrived", "have arrived",
    "has given birth", "has created", "has been struck down",
    "has died", "has gone missing", "has been found dead",
    "siege", "ambush", "strange mood", "has claimed", "artifact",
    "is on fire", "has drowned", "elected", "mandate", "demand",
    "were abducted", "has become a", "were unable to complete",
    "has been spotted", "thief", "has been wounded",
    "nothing to catch",
)
_WEATHER_SUBSTRINGS = (
    "has started raining", "weather has cleared", "has started snowing",
    "weather has turned",
)


def _is_report(text: str) -> bool:
    lowered = text.lower()
    return any(s in lowered for s in _KEEP_SUBSTRINGS)


def _is_weather(text: str) -> bool:
    lowered = text.lower()
    return any(s in lowered for s in _WEATHER_SUBSTRINGS)


def _tick_range(path: str | Path, year: int, day_start_tick: int
                ) -> tuple[int | None, int | None, int]:
    """(first, last, in-day) ticks of a JSONL log's records for
    ``year`` — the source-coverage facts (P0-2, gap review 3):
    which event sources were live for a day, and when each ended.
    A missing or unreadable file yields (None, None, 0), never an
    error. Malformed lines are skipped."""
    first_tick: int | None = None
    last_tick: int | None = None
    in_day = 0
    day_end = day_start_tick + 1200 - 1
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return None, None, 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(e, dict) or e.get("year") != year:
            continue
        tick = e.get("tick")
        if not isinstance(tick, int):
            continue
        if first_tick is None or tick < first_tick:
            first_tick = tick
        if last_tick is None or tick > last_tick:
            last_tick = tick
        if day_start_tick <= tick <= day_end:
            in_day += 1
    return first_tick, last_tick, in_day


def _read_watch_log(path: str | Path, year: int
                    ) -> tuple[list[dict[str, Any]],
                               list[dict[str, Any]]]:
    """The raw DFHack watch log (dfh-events.jsonl): its
    JOB_COMPLETED and REPORT records for ``year``.

    Returns (completions, reports). Completions are clustered by
    (worker, job_type, position) with single-linkage inside
    _completion_window(job) — 5000 ticks for need-jobs, 300 for
    queued jobs — keeping the earliest tick of each cluster, and
    carry job_id (of the cluster's first record, for display),
    job_type, worker_id, position, tick, and last_tick (the
    cluster's last tick, for the bus dedup). The job id is NOT
    part of the key: one drink spans several job ids. Reports are
    deduped by (index, text) keeping the earliest tick: the index
    recycles (index 5 is the caravan at 101250 and "nothing to
    catch" at 107158), so the text is part of the key, and the
    tick is an observation tick, so the earliest observation owns
    the day. A missing/unreadable file yields ([], []), never an
    error. Malformed lines are skipped."""
    completions: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return completions, reports
    # Collect first, then sort by tick: the file is append-ordered
    # by poll, not strictly tick-ordered, so a windowed dedup over
    # file order would drop a real completion that happens to be
    # written after a later-ticked re-report of the same job id
    # (job 85 Drink2 on 04-01 was lost exactly that way).
    raw_rows: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(e, dict) or e.get("year") != year:
            continue
        kind = e.get("kind") or ""
        tick = e.get("tick")
        if not isinstance(tick, int):
            continue
        if kind == "JOB_COMPLETED":
            job = e.get("job_type") or ""
            if not job:
                continue
            pos = e.get("pos")
            pos_t = tuple(pos) if isinstance(pos, list) else None
            uid = e.get("worker_id")
            raw_rows.append({
                "job_id": e.get("job_id"), "job": job,
                "worker_id": uid if isinstance(uid, int) else None,
                "pos": list(pos_t) if pos_t is not None else None,
                "tick": tick,
            })
        elif kind == "REPORT":
            text = (e.get("text") or "").strip()
            if not text:
                continue
            reports.append({"index": e.get("index"), "text": text,
                            "tick": tick})
    raw_rows.sort(key=lambda r: (r["tick"], str(r["job_id"]),
                                 r["job"]))
    # Cluster by (worker, job, position), single-linkage: sort
    # each group's ticks, chain while consecutive ticks are
    # within the window. The job id is not in the key — one drink
    # spans several job ids (Olon 85 + 86 on 04-01, Lòr 87 + 88
    # + 89 + 186 on 04-02), and a fixed window from the first
    # tick would split a long chain (Lòr's 04-02 drink spans
    # 1322 ticks). Each cluster is one completion, dated by its
    # first tick; last_tick is kept for the bus dedup.
    grouped: dict[tuple, list[dict[str, Any]]] = {}
    for r in raw_rows:
        key = (r["worker_id"], r["job"],
               tuple(r["pos"]) if r["pos"] is not None else None)
        grouped.setdefault(key, []).append(r)
    for (uid, job, pos_t), rows in grouped.items():
        rows.sort(key=lambda r: r["tick"])
        window = _completion_window(job)
        cluster: list[dict[str, Any]] = []
        for r in rows:
            if cluster and r["tick"] - cluster[-1]["tick"] > window:
                completions.append({
                    "job_id": cluster[0]["job_id"], "job": job,
                    "worker_id": uid,
                    "pos": (list(pos_t) if pos_t is not None
                            else None),
                    "tick": cluster[0]["tick"],
                    "last_tick": cluster[-1]["tick"],
                })
                cluster = []
            cluster.append(r)
        if cluster:
            completions.append({
                "job_id": cluster[0]["job_id"], "job": job,
                "worker_id": uid,
                "pos": (list(pos_t) if pos_t is not None else None),
                "tick": cluster[0]["tick"],
                "last_tick": cluster[-1]["tick"],
            })
    completions.sort(key=lambda c: (c["tick"], c["job"]))
    # Reports: keep only the earliest tick per (index, text).
    earliest: dict[tuple, dict[str, Any]] = {}
    for r in reports:
        key = (r["index"], r["text"])
        if key not in earliest or r["tick"] < earliest[key]["tick"]:
            earliest[key] = r
    return completions, list(earliest.values())


# A run-log build_workshop action's reason: "still workshop #8
# built at [95, 108, 175] (construction_stage 3)". The journal's
# decisions carry the same text, but the journal mixes forts (the
# 07-01 rows build a still #14 at z=42 — the scratch fort, same
# year, same ticks), and the main fort's 04-01 still build is not
# in the journal at all. The run logs are the source.
_BUILD_RE = re.compile(
    r"(\w+) workshop #(\d+) built at \[(\d+), (\d+), (\d+)\]")


def read_workshop_map(run_logs_dir):
    """pos -> {id, kind} for every workshop built in the run logs.

    The map is how a completion's position becomes a name: a
    CustomReaction at [95, 108, 175] is work at the still, not
    "working a reaction". A missing or unreadable dir is an
    empty map, never an error — the phrases fall back to the
    vague-but-true forms. Malformed lines are skipped."""
    out = {}
    if run_logs_dir is None:
        return out
    try:
        paths = sorted(Path(run_logs_dir).glob("m1-*.jsonl"))
    except (OSError, ValueError):
        return out
    for path in paths:
        try:
            lines = path.read_text(
                encoding="utf-8", errors="replace").splitlines()
        except (OSError, ValueError):
            continue
        for line in lines:
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(rec, dict):
                continue
            if rec.get("kind") != "action":
                continue
            act = rec.get("action")
            if not isinstance(act, dict):
                continue
            if act.get("name") != "build_workshop":
                continue
            if not act.get("ok"):
                continue
            reason = act.get("reason") or ""
            if not isinstance(reason, str):
                continue
            m = _BUILD_RE.search(reason)
            if not m:
                continue
            kind = m.group(1)
            pos = (int(m.group(3)), int(m.group(4)), int(m.group(5)))
            out[pos] = {"id": int(m.group(2)), "kind": kind}
    return out


def read_day_events(events_path: str | Path | None,
                    year: int, day_start_tick: int,
                    names: dict[int, str] | None = None,
                    watch_log_path: str | Path | None = None,
                    ) -> dict[str, Any]:
    """The day's events from the daemon's bus event log.

    ``events_path`` is the events.jsonl file (daemon state dir);
    None or a missing file means no event record. ``names`` maps
    unit ids to dwarf names (the caller's Store names, which win);
    the reader also builds a map from citizen_new events in the
    file itself, so dwarves the Store never named (the migrants)
    still resolve. ``watch_log_path`` is the raw DFHack watch log
    (dfh-events.jsonl): the fuller completion source (worker and
    position) and a second report source. When it is given,
    completions come from the raw log (clustered) plus bus
    completions that do not duplicate a raw cluster; without it
    the bus is the only source. Returns a dict with reports,
    weather, completions, cancellations, arrivals, departures,
    deaths, distress, wildlife counts, and has_events. Every list
    is chronological; every count is exact. A completion entry
    carries "pos" (the job's position, or None) and "job_id" so
    the feed can resolve which workshop a job happened at."""
    day_end = day_start_tick + 1200 - 1
    result: dict[str, Any] = {
        "reports": [], "weather": [], "completions": [],
        "cancellations": [], "arrivals": [], "departures": [],
        "deaths": [], "distress": [],
        "wildlife_arrivals": 0, "wildlife_deaths": 0,
        "dropped_reports": 0, "has_events": False,
        "known_names": {}, "stock_alerts": [], "threats": [],
        # Source coverage (P0-2): which event sources were live
        # for this day. The bus and the watch log end on different
        # days (the watch log ends 06-14, the bus runs to 07-08),
        # so each is measured, never assumed. "present" is False
        # when the file is missing or holds no record for the year.
        "coverage": {
            "bus": {"present": False, "first_tick": None,
                    "last_tick": None, "in_day": 0},
            "watch": {"present": False, "first_tick": None,
                      "last_tick": None, "in_day": 0},
        },
    }
    # The watch log's range is measured even when the bus file is
    # missing (the early returns below must not hide it): the
    # watch log is the primary completion source.
    if watch_log_path is not None:
        w_first, w_last, w_in_day = _tick_range(
            watch_log_path, year, day_start_tick)
        result["coverage"]["watch"] = {
            "present": w_first is not None,
            "first_tick": w_first, "last_tick": w_last,
            "in_day": w_in_day}
    if events_path is None:
        return result
    path = Path(events_path)
    if not path.exists():
        return result
    # Pass 1: unit id -> name from citizen_new events (whole file,
    # this year only — unit ids can collide across forts/worlds).
    # The caller's names win over these. The full info (name +
    # profession) is also returned as known_names, so the feed can
    # name dwarves the Store never named (the migrants).
    file_names: dict[int, str] = {}
    file_info: dict[int, dict[str, str]] = {}
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return result
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(e, dict) or e.get("year") != year:
            continue
        records.append(e)
        if e.get("type") == "citizen_new":
            data = e.get("data") or {}
            uid = data.get("unit_id")
            nm = data.get("name") or ""
            if isinstance(uid, int) and nm:
                file_names[uid] = nm
                # The first tick this name was recorded: the name
                # is a DETECTION, not an arrival. The migrants'
                # names were first recorded at tick 201600 (07-01)
                # though they arrived 06-02/06-03, so a feed for
                # an earlier day must not use them. The feed
                # gates on this tick.
                tick = e.get("tick")
                prev = file_info.get(uid) or {}
                first_tick = prev.get("first_seen_tick")
                if (not isinstance(first_tick, int)
                        and isinstance(tick, int)):
                    first_tick = tick
                file_info[uid] = {
                    "name": nm,
                    "profession": data.get("profession") or "",
                    "first_seen_tick": first_tick,
                }
    caller_names = names or {}
    names = {**file_names, **caller_names}
    result["known_names"] = file_info
    # Bus coverage, from the records already loaded: the file's
    # range for the year and how many of its rows fall in the day.
    bus_ticks = [e["tick"] for e in records
               if isinstance(e.get("tick"), int)]
    result["coverage"]["bus"] = {
        "present": bool(bus_ticks),
        "first_tick": min(bus_ticks) if bus_ticks else None,
        "last_tick": max(bus_ticks) if bus_ticks else None,
        "in_day": sum(1 for t in bus_ticks
                      if day_start_tick <= t <= day_end)}

    def resolve(uid: Any, tick: int | None = None) -> str:
        # A name is usable for an event only if the record had it
        # by then (P0-2, 06-12: the completion for uid 1700
        # resolved to "Litast Aknûnònul" although the name was
        # first recorded at tick 201600, sixteen days after the
        # meal — the entry then named a dwarf the 06-12 record
        # had only as an unnamed migrant). Caller (Store) names
        # pass through: the Store names founders from full samples
        # that predate the events, and it never names a migrant
        # (no full sample ever). File-derived names gate on
        # first_seen_tick; an event at its own first sighting
        # (a citizen_new) passes, since first_seen_tick is its
        # own tick.
        if not isinstance(uid, int):
            return ""
        if uid in caller_names:
            return caller_names[uid] or ""
        nm = file_names.get(uid) or ""
        if not nm or tick is None:
            return nm
        first_seen = (file_info.get(uid) or {}).get(
            "first_seen_tick")
        if isinstance(first_seen, int) and first_seen > tick:
            return ""
        return nm

    # Pass 2: the day's events, in file order (chronological).
    seen_reports: set[str] = set()
    # Bus completions are collected, not counted here: the
    # poller's day-start baseline (a burst of worker-None rows at
    # one tick) is not completions, and rows that duplicate a raw
    # watch-log record are dropped in the merge below.
    bus_completions: list[dict[str, Any]] = []
    gone: list[dict[str, Any]] = []
    # Every citizen_new sighting in the file (any tick): a "gone"
    # is a reload artifact when the unit is seen again later.
    new_sightings: list[tuple[int, int]] = []
    for e in records:
        tick = e.get("tick")
        if not isinstance(tick, int):
            continue
        if e.get("type") == "citizen_new":
            uid = (e.get("data") or {}).get("unit_id")
            if isinstance(uid, int):
                new_sightings.append((uid, tick))
        if tick > day_end:
            continue
        if tick < day_start_tick:
            continue
        etype = e.get("type") or ""
        data = e.get("data") or {}
        if etype == "report":
            text = (data.get("text") or "").strip()
            if not text:
                continue
            if _is_weather(text):
                if text not in result["weather"]:
                    result["weather"].append(text)
            elif _is_report(text):
                if text not in seen_reports:
                    seen_reports.add(text)
                    result["reports"].append(text)
            else:
                result["dropped_reports"] += 1
        elif etype == "job_completed":
            job = data.get("job_type") or ""
            if not job:
                continue
            uid = data.get("worker_id")
            bus_completions.append({
                "job_id": data.get("job_id"),
                "job": job,
                "worker_id": uid if isinstance(uid, int) else None,
                "tick": tick,
            })
        elif etype == "job_cancelled":
            text = (data.get("text") or "").strip()
            # "Lòr Mebzuthkin, expedition leader cancels Construct
            # Building: Needs " — name and job are in the text, the
            # reason is truncated, so only name + job are kept.
            name = ""
            job = ""
            if " cancels " in text:
                head, _, tail = text.partition(" cancels ")
                name = head.split(",")[0].strip()
                job = tail.split(":")[0].strip()
            if name and job:
                entry = {"name": name, "job": job}
                if entry not in result["cancellations"]:
                    result["cancellations"].append(entry)
        elif etype == "citizen_new":
            uid = data.get("unit_id")
            nm = data.get("name") or resolve(uid, tick)
            if nm:
                entry = {"name": nm,
                         "profession": data.get("profession") or ""}
                if entry not in result["arrivals"]:
                    result["arrivals"].append(entry)
        elif etype == "citizen_gone":
            uid = data.get("unit_id")
            nm = data.get("name") or resolve(uid, tick)
            if nm:
                gone.append({"name": nm, "unit_id": uid,
                             "tick": tick})
        elif etype == "unit_death":
            uid = data.get("unit_id")
            nm = resolve(uid, tick)
            if nm:
                result["deaths"].append({"name": nm})
            else:
                result["wildlife_deaths"] += 1
        elif etype == "new_arrival":
            # Wildlife/livestock arrivals: counted, never named.
            # Dwarf arrivals come through citizen_new instead.
            result["wildlife_arrivals"] += 1
        elif etype == "dwarf_distress":
            nm = data.get("name") or ""
            kind = data.get("kind") or ""
            if nm and kind:
                entry = {"name": nm, "kind": kind}
                if entry not in result["distress"]:
                    result["distress"].append(entry)
        elif etype == "stock_low":
            # The poller's dated stock crisis ("drink 9 left",
            # "drink 0"): the true date a stock ran low or out —
            # the 06-20 "ran out today" dispute is settled by the
            # stock_low event at tick 192076 (06-21), not by the
            # trend samples.
            kind = data.get("kind") or ""
            units = data.get("units")
            if kind and isinstance(units, int):
                entry = {"kind": kind, "units": units}
                if entry not in result["stock_alerts"]:
                    result["stock_alerts"].append(entry)
        elif etype in ("hostile_spawn", "threat"):
            nm = data.get("name") or ""
            race = data.get("race") or ""
            detail = data.get("detail") or data.get("text") or ""
            entry = {"name": nm, "race": race, "detail": detail}
            if entry not in result["threats"]:
                result["threats"].append(entry)
    # Reload artifacts: a "gone" whose unit is seen again later is
    # the poller re-baselining after a reload, not a departure
    # (04-01: the migrants "gone" at the day's first tick, then
    # citizen_new at 201600). A gone with no later sighting is a
    # real disappearance and is kept.
    for g in gone:
        uid = g.get("unit_id")
        gtick = g.get("tick")
        if (isinstance(uid, int) and isinstance(gtick, int)
                and any(u == uid and t > gtick
                        for u, t in new_sightings)):
            continue
        result["departures"].append({"name": g["name"]})
    # Completions: merge the bus rows with the raw watch log.
    # The bus rows carry the poller's day-start baseline: a burst
    # of worker-None rows at one tick (04-01: 18 rows at tick
    # 100800, every job in progress, not completions). A tick with
    # three or more worker-None completions is a baseline burst —
    # a real completion the poller could not attribute is a lone
    # row, never a burst — so those rows are dropped. The raw log
    # is then the authoritative completion source (it has the
    # worker and the position the bus lacks, and it carries the
    # still's ConstructBuilding and every CustomReaction, which
    # the bus misses entirely). A bus row that duplicates a raw
    # completion is dropped — the raw row wins, for its position.
    # The dedup is by (worker, job) and tick, NOT by job id: one
    # drink spans several job ids, so a job-id match would miss
    # the duplicate and double-count it. A bus row duplicates a
    # raw cluster when the same worker did the same job and the
    # bus tick falls inside the cluster's span plus a 300-tick
    # poll lag on either side. A bus row with no worker cannot be
    # deduped and is kept. The raw clusters are NOT filtered to
    # the day for this check — a cluster that started yesterday
    # and ended today still owns a bus row observed today.
    none_per_tick: Counter = Counter()
    for b in bus_completions:
        if b["worker_id"] is None:
            none_per_tick[b["tick"]] += 1
    baseline_ticks = {t for t, n in none_per_tick.items() if n >= 3}
    merged: list[dict[str, Any]] = []
    raw_clusters: list[dict[str, Any]] = []
    raw_reports: list[dict[str, Any]] = []
    if watch_log_path is not None:
        raw_completions, raw_reports = _read_watch_log(
            watch_log_path, year)
        raw_clusters = raw_completions
        for rc in raw_completions:
            if not (day_start_tick <= rc["tick"] <= day_end):
                continue
            merged.append(rc)
    for b in bus_completions:
        if b["worker_id"] is None and b["tick"] in baseline_ticks:
            continue
        if _bus_row_duplicates_raw(b, raw_clusters):
            continue
        merged.append({"job_id": b["job_id"], "job": b["job"],
                       "worker_id": b["worker_id"], "pos": None,
                       "tick": b["tick"]})
    # Raw reports: a report the bus already lists is not added
    # twice; a report the bus missed (the watcher saw it, the
    # drainer did not) is added, dated by its earliest
    # observation. Weather is kept apart, as with bus reports.
    for r in raw_reports:
        if not (day_start_tick <= r["tick"] <= day_end):
            continue
        text = r["text"]
        if _is_weather(text):
            if text not in result["weather"]:
                result["weather"].append(text)
        elif _is_report(text):
            if text not in seen_reports:
                seen_reports.add(text)
                result["reports"].append(text)
    # Group by (worker, job): the count is the number of
    # completions, the workers are the distinct dwarves, the
    # position is carried only when every completion in the group
    # happened at one place (a GatherPlants group spans the map;
    # a brew group sits at the still).
    grouped: dict[tuple, dict[str, Any]] = {}
    for m in merged:
        uid = m["worker_id"]
        name = resolve(uid, m["tick"])
        key = (name, m["job"])
        g = grouped.get(key)
        if g is None:
            g = {"name": name, "job": m["job"], "count": 0,
                 "routine": m["job"] in ROUTINE_JOBS,
                 "workers": [], "worker_id": uid,
                 "pos": m["pos"], "job_id": m["job_id"]}
            grouped[key] = g
        g["count"] += 1
        if name and name not in g["workers"]:
            g["workers"].append(name)
        if g["worker_id"] is None and isinstance(uid, int):
            g["worker_id"] = uid
        if g["pos"] is not None and m["pos"] != g["pos"]:
            g["pos"] = None
    for (name, job), g in sorted(grouped.items()):
        entry: dict[str, Any] = {
            "name": name, "job": job, "count": g["count"],
            "routine": g["routine"],
        }
        if name:
            entry["workers"] = g["workers"] or [name]
        if isinstance(g["worker_id"], int):
            entry["worker_id"] = g["worker_id"]
        if g["pos"] is not None:
            entry["pos"] = g["pos"]
        if g["job_id"] is not None:
            entry["job_id"] = g["job_id"]
        result["completions"].append(entry)
    result["has_events"] = bool(
        result["reports"] or result["weather"]
        or result["completions"] or result["cancellations"]
        or result["arrivals"] or result["departures"]
        or result["deaths"] or result["distress"]
        or result["stock_alerts"] or result["threats"])
    return result
