"""Rebuild diary.md from the recorded history with the current renderer.

One-off migration for the 2026-11-27 diary quality pass: the existing
entries were rendered by the old renderer (dry stock reports, broken
decision grammar, internal debris, "22th", "Souls", one decision
repeated 93 times). This rebuilds each entry from the best available
recorded facts:

* the Journal + Store for that day (planner decisions, daemon
  events, trend samples) — via diary.build_daily_summary;
* the entry's own ledger line (diary.ledger_stocks) — the stocks
  the old renderer recorded from live samples, which the Store no
  longer has (old samples were cleared);
* the entry's own "I decided to ..." sentences — the M1 run's
  decisions, which the Journal never saw (the daemon loop is paused
  during runs) and which the run jsonl does not carry with kwargs.
  Only the phrase (up to the first ". ") and the recorded outcome
  ("It worked." / "It did not work.") are recovered; the reason and
  the raw result are dropped by the new renderer, as they should be.
  A distress diagnostic line is recovered as a log record, so it
  renders as an observation, not a decision.

Nothing is invented: a day with no recorded facts re-renders as a
quiet day. The file is written in chronological order; a backup
(diary.md.bak) is kept next to it. --dry-run prints what would be
written without touching the file.

Caveat (honest, not hidden): an in-game day replayed across reloads
composites several playthroughs into one entry — 125-04-01 was
played by several runs (00:55 queued brew at a Still that a later
reload removed, 01:17 built the Still again), so its entry merges
decisions from more than one timeline. The rebuild records what was
recorded; it cannot untangle the timelines, and it does not drop a
real recorded decision to pretend a clean order exists.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness import diary  # noqa: E402
from dfagent_harness.planner import Journal  # noqa: E402
from dfagent_harness.store import Store  # noqa: E402
from m1_driver import parse_snapshot_stocks_any  # noqa: E402

HEADING_RE = re.compile(r"^## (\d+)-(\d+)-(\d+)", re.M)
DECISION_RE = re.compile(r"^I decided to (.+?)(?:\. |$)")
# The game's date in a snapshot's header ("Erushtathtat,
# 125-04-02 ...", or "header: unchanged (Erushtathtat,
# 125-04-02)." when diffed) — the same pattern parse_fort_name
# uses, so the rebuild and the retry read the date the same way.
_SNAPSHOT_DATE_RE = re.compile(r"[A-Z][\w ]*?,\s*(\d+-\d+-\d+)")


def _day_start(year: int, month: int, day: int) -> int:
    """year_tick of the first tick of (year, month, day)."""
    return (month - 1) * diary.TICKS_PER_MONTH + (day - 1) * diary.TICKS_PER_DAY


def _parse_entry_phrases(body: str) -> list[dict]:
    """The run's decision phrases from an old entry's text. Each
    "I decided to <phrase>. <reason> (<result>)" line yields one
    decision: the phrase, the recorded outcome, and action="log"
    for a distress diagnostic (so it renders as an observation).
    The reason and the raw result are not recovered — the new
    renderer drops them by design."""
    decisions = []
    for line in body.splitlines():
        if not line.startswith("I decided to "):
            continue
        m = DECISION_RE.match(line)
        if not m:
            continue
        phrase = m.group(1).strip()
        rest = line[m.end():].strip()
        if " It did not work." in line:
            ok = False
        elif " It worked." in line:
            ok = True
        else:
            ok = None
        action = "log" if "past a distress line" in line else ""
        decisions.append({"decision": phrase, "reason": rest,
                          "action": action, "ok": ok, "result": None})
    return decisions


_ACTION_REASON_RE = {
    "labor_toggle": re.compile(
        r"labor (\w+) (enabled|disabled) on (.+)"),
    "build_workshop": re.compile(
        r"(\w+) workshop #\d+ built at \[(\d+), (\d+), (\d+)\]"),
    "queue_job": re.compile(
        r"queued (\w+) x(\d+) on building #(\d+)"),
}


def _phrase_from_action_record(record: dict) -> str | None:
    """A run jsonl action record as a diary decision phrase. The
    record carries no kwargs, so the phrase is parsed from the
    harness's own reason string (a recorded fact). Returns None
    when the reason does not match a known shape — nothing is
    invented."""
    name = record.get("name") or ""
    reason = str(record.get("reason") or "")
    if name == "labor_toggle":
        m = _ACTION_REASON_RE["labor_toggle"].match(reason)
        if m:
            verb = "enable" if m.group(2) == "enabled" else "disable"
            return f"{verb} {m.group(1)} labor on {m.group(3)}"
    elif name == "build_workshop":
        m = _ACTION_REASON_RE["build_workshop"].match(reason)
        if m:
            return (f"build a {m.group(1)} at "
                    f"({m.group(2)}, {m.group(3)}, {m.group(4)})")
    elif name == "queue_job":
        m = _ACTION_REASON_RE["queue_job"].match(reason)
        if m:
            return (f"queue {m.group(1)} x{m.group(2)} "
                    f"at building #{m.group(3)}")
    elif name.startswith("task:"):
        return f"run the {name[len('task:'):]} task"
    return None


def _run_decisions_by_date(log_dir: Path) -> dict[str, list[dict]]:
    """{date: [decisions]} from non-mock M1 run jsonls — ONE RUN
    PER DATE, not the sum of all runs. The old code aggregated
    every run file for a date, so 04-01's feed claimed 28 beds
    and 35 barrels: sixteen replays of the same day, each
    queueing a few beds, summed into a number no single
    playthrough ever had. The model faithfully repeated it
    ("sixteen beds and nineteen barrels, thirty-five jobs in
    all") and the validator blessed it, because the feed said so.
    The run for a date is the LATEST run that attempted a diary
    write for it (kind == "diary" record, ok or failed — it is
    the run that was live at the day's end); if no run attempted
    a write for the date, the latest run for the date. Mock runs
    are excluded. A run's decisions are the ones the Journal
    never saw (the daemon loop is paused during runs); the 04-01
    entry predates the diary wiring, so without this the Still
    build would be lost."""
    import json

    files: list[tuple[str, str, bool, list[dict]]] = []
    for path in sorted(Path(log_dir).glob("m1-*.jsonl")):
        date = None
        mock = False
        attempted = False
        decisions: list[dict] = []
        for line in path.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") == "run_start":
                mock = bool(r.get("mock"))
            elif r.get("kind") == "start_tick":
                date = r.get("date")
            elif r.get("kind") == "diary":
                attempted = True
            elif r.get("kind") == "action" and not mock and date:
                phrase = _phrase_from_action_record(r)
                if phrase:
                    decisions.append({
                        "decision": phrase,
                        "reason": r.get("model_reason", ""),
                        "action": r.get("name", ""),
                        "ok": r.get("ok"), "result": None})
        if date and not mock:
            # A start_tick record's date is trusted only when it
            # looks like a date. Some run files carry a garbage
            # "date" (a "Population: ..." string in the start_tick
            # record) — those runs cannot be attributed to a day,
            # so their decisions are dropped, not filed under a
            # junk key that would never match a diary date.
            if re.fullmatch(r"\d+-\d+-\d+", date):
                files.append((date, str(path), attempted, decisions))
    by_date: dict[str, list[dict]] = {}
    for date in sorted({d for d, _, _, _ in files}):
        dated = [f for f in files if f[0] == date]
        attempted = [f for f in dated if f[2]]
        # Latest file wins (filenames sort in time order); a
        # diary-attempting run beats one that never tried.
        pick = (attempted or dated)[-1]
        if pick[3]:
            by_date[date] = pick[3]
    return by_date


_POPULATION_RE = re.compile(
    r"Population: (\d+) citizens \((\d+) idle, (\d+) wounded\)")


def _snapshot_group_counts(
        log_dir: Path) -> dict[str, dict[str, dict]]:
    """{date: {"start": {"wounded", "idle", "population"},
    "end": {...}}} from the Population lines in non-mock run
    snapshots ("7 citizens (5 idle, 2 wounded)"). Same date
    grouping as _run_stocks_by_date (the date in the snapshot
    text, not the run file's date). First snapshot of the day
    carrying a line is the start, last is the end. This is the
    day's own per-dwarf count when the Store has no full samples
    for the day (04-05: the feed's curr is a stale 04-01 sample
    saying 6 wounded; the day's snapshots say 2 at start, 2 at
    end — the run's end, 1 wounded, is dated 04-06)."""
    import json

    by_date: dict[str, dict[str, dict]] = {}
    for path in sorted(Path(log_dir).glob("m1-*.jsonl")):
        mock = False
        for line in path.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") == "run_start":
                mock = bool(r.get("mock"))
            if mock or r.get("kind") != "snapshot":
                continue
            text = str(r.get("text") or "")
            if not text:
                sections = (r.get("sections") or {})
                text = str(sections.get("header") or "")
            dm = _SNAPSHOT_DATE_RE.search(text)
            if not dm:
                continue
            pm = _POPULATION_RE.search(text)
            if not pm:
                continue
            counts = {"population": int(pm.group(1)),
                      "idle": int(pm.group(2)),
                      "wounded": int(pm.group(3))}
            slot = by_date.setdefault(dm.group(1), {})
            if "start" not in slot:
                slot["start"] = counts
            slot["end"] = counts
    return by_date


def _day_has_full_samples(store, day_start: int) -> bool:
    """True when any citizen has a full per-dwarf sample inside
    the day starting at day_start. The feed's curr is the last
    full sample at or before the day end; when no full sample
    falls inside the day, curr is an older day's sample and the
    feed's per-dwarf record is stale for this day (04-05: the
    last full samples are 101999, from 04-01; the June/July days:
    the last full is 101999 for the originals, and the migrants
    never had one)."""
    day_end = day_start + diary.TICKS_PER_DAY - 1
    for uid in store.unit_ids():
        for s in store.unit_history(uid):
            tick = s.get("tick")
            if (isinstance(tick, int)
                    and day_start <= tick <= day_end
                    and diary._is_full_sample(s)):
                return True
    return False


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
_LITE_STALE_TICKS = 10 * diary.TICKS_PER_DAY


def _lite_dwarf_feed(store, day_start: int, population: int,
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
    end."""
    from dfagent_harness.dwarves import dwarf_record

    day_end = day_start + diary.TICKS_PER_DAY - 1
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
        for s in samples:
            tick = s.get("tick")
            if isinstance(tick, int) and tick <= day_end:
                if latest is None or tick > latest["tick"]:
                    latest = s
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
        full = [s for s in samples if diary._is_full_sample(s)]
        name = full[-1].get("name") if full else ""
        if not name:
            unnamed += 1
        rec = dwarf_record(latest, changes=[], related_states={},
                           prev_relations=None)
        rec["name"] = name or "an unnamed migrant"
        rec["profession"] = (full[-1].get("profession") or ""
                             if full else "")
        rec["needs"] = []
        thirst = latest.get("thirst")
        if isinstance(thirst, int) and thirst > _THIRST_THRESHOLD:
            # Derived, not game-reported: the lite sample carries
            # the counter but not the need. Marked by the comment
            # and by the rebuild's log line, not hidden.
            rec["needs"] = [{"need": "drink", "focus": -1,
                             "level": 1}]
        rec["featured"] = False
        rec["significance"] = 0
        records.append(rec)
        if isinstance(tick, int) and (record_tick is None
                                      or tick > record_tick):
            record_tick = tick
    if not records and unnamed == 0:
        return None
    counts = diary._group_counts(records)
    for g in counts:
        g["total"] = population
    span = (max(latest_ticks) - min(latest_ticks)
            if latest_ticks else 0)
    return {"records": records, "counts": counts,
            "record_tick": record_tick, "unnamed": unnamed,
            "sampled": sampled, "span_ticks": span,
            "in_day_sampled": in_day_sampled,
            "in_day_wounded": in_day_wounded}


def _run_stocks_by_date(log_dir: Path) -> dict[str, dict[str, dict]]:
    """{date: {"start": stocks, "end": stocks}} from non-mock M1
    run jsonls. A run's snapshots are grouped by the DATE IN THE
    SNAPSHOT TEXT (the game's date at that tick), not by the run
    file's date — a 1-day run starting mid-day crosses midnight,
    so its later snapshots belong to the next day (run 071025
    started 04-01 but its last snapshot, drink 34, is dated
    04-02; grouping by file date would credit 34 to 04-01).
    First snapshot of the day across all runs is the start, last
    is the end. Mock runs are excluded. A snapshot with no
    parseable stocks is skipped, never guessed. Verified
    2026-11-27: 04-01 38->37, 04-02 35->33, 04-05 68->68 (wood
    122->122; the run's last snapshot, wood 121, is dated 04-06)."""
    import json

    by_date: dict[str, dict[str, dict]] = {}
    for path in sorted(Path(log_dir).glob("m1-*.jsonl")):
        mock = False
        for line in path.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") == "run_start":
                mock = bool(r.get("mock"))
            if mock or r.get("kind") != "snapshot":
                continue
            text = str(r.get("text") or "")
            if not text:
                sections = (r.get("sections") or {})
                text = str(sections.get("header") or "")
            m = _SNAPSHOT_DATE_RE.search(text)
            if not m:
                continue
            stocks = parse_snapshot_stocks_any(r)
            if not stocks:
                continue
            date = m.group(1)
            slot = by_date.setdefault(date, {})
            if "start" not in slot:
                slot["start"] = stocks
            slot["end"] = stocks
    return by_date


def _split_entries(text: str) -> list[tuple[str, str]]:
    """(heading date, body) per entry in file order."""
    entries = []
    parts = re.split(r"(?m)^## ", text)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(\d+)-(\d+)-(\d+)", part)
        if not m:
            continue
        date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        body = part[len(m.group(0)):].strip()
        # Drop the " — 2nd of Galena, 125" heading suffix. The
        # strip above already removed the leading space, so the
        # suffix starts with the dash itself — the old pattern
        # "^ — " never matched and the suffix stayed in the body
        # (harmless for phrase/ledger parsing, but a body test
        # like the gap-marker check needs the real first line).
        body = re.sub(r"^— [^\n]*\n", "", body, count=1).strip()
        entries.append((date, body))
    return entries


# The gap with no entries at all: 125-04-06 to 125-06-01. A
# marker, not a story — it states what is known and what is not,
# and it says so. Drink stood at 68 on 04-05 (the run's
# snapshots) and the 06-02 entry records it at 9; three new
# citizens arrived in the gap and their names were never recorded
# (their samples are lite-only). No day count is stated: the
# review's "28 days" does not survive a recount (the DF calendar
# and the real calendar disagree on the span), so the marker
# gives the date range and leaves the count out. There is a
# second, smaller hole just before it — 125-04-03 to 125-04-04
# have no entries either. What little is known of those two days:
# a run played 04-03 and its snapshots read drink 33, food 32,
# wood 124; 04-04 has nothing recorded at all.
GAP_DATE = "125-04-06"
GAP_BODY = (
    "GAP — no entries exist for 125-04-06 to 125-06-01. Nothing "
    "was recorded for these days, so this is not a story about "
    "them; it is a marker for what is known and what is not. "
    "What is known: drink stood at sixty-eight on 125-04-05, "
    "from the run's snapshots, and the 125-06-02 entry records "
    "it at nine; three new citizens arrived in the gap, and "
    "their names were never recorded. What is not known: what "
    "happened to the drink, when the migrants arrived, or what "
    "the fort did in the meantime. Two days just before the gap "
    "are missing too — no entries exist for 125-04-03 to "
    "125-04-04. A run played 125-04-03 and its snapshots read "
    "drink thirty-three, food thirty-two, wood a hundred and "
    "twenty-four; 125-04-04 has nothing recorded at all. The "
    "entries resume on 125-06-02.")


def rebuild(state_dir: Path, log_dir: Path,
            dry_run: bool = False, ai: bool = False,
            drop_dates: list[str] | None = None,
            dates: list[str] | None = None,
            ledger_source: Path | None = None) -> None:
    state_dir = Path(state_dir).expanduser()
    diary_path = diary.diary_md_path(state_dir)
    text = diary_path.read_text()
    entries = _split_entries(text)
    # Ledgers from the pre-rewrite diary (the safety copy taken
    # before the first AI rewrite). The first run's AI entries
    # dropped their ledger lines, so a second run over them has
    # no ledger to read — and the Store's only trend sample is
    # 04-01's (drink 39), which would poison a June day's feed
    # (06-22 would read drink 39, food 32, pop 7). The
    # pre-rewrite template entries still carry the June ledgers
    # (drink 0, food 23, wood 211, pop 10). Only used when the
    # current entry has no ledger line and no run stocks.
    source_ledgers: dict[str, tuple[dict, dict]] = {}
    if ledger_source is not None:
        ledger_path = Path(ledger_source).expanduser()
        if ledger_path.exists():
            source_text = ledger_path.read_text()
            for d, b in _split_entries(source_text):
                source_ledgers[d] = diary.ledger_stocks(b)
    runs = _run_decisions_by_date(Path(log_dir).expanduser())
    run_stocks = _run_stocks_by_date(Path(log_dir).expanduser())
    snap_counts = _snapshot_group_counts(Path(log_dir).expanduser())
    store = Store(state_dir / "world.db")
    journal = Journal(state_dir / "journal.db")
    client = None
    if ai:
        # One shared model client for the whole rebuild (a fresh
        # FreePiClient per entry would re-read the JWT each time).
        from dfagent_harness.freepi import FreePiClient
        client = FreePiClient()
    try:
        if not dry_run:
            shutil.copy2(diary_path, diary_path.with_suffix(".md.bak"))
        # Drop ungrounded entries first (125-03-28 predates the
        # fort's recorded existence — no run log, no journal row,
        # no trend sample, no event for that day). A dropped date
        # is deleted from the file, not rewritten: skipping it in
        # the loop below would leave the old entry in place.
        for date in drop_dates or []:
            if dry_run:
                print(f"{date}: would drop (ungrounded entry)")
                continue
            if diary.remove_entry(state_dir, date):
                print(f"{date}: dropped (ungrounded entry)")
                entries = [(d, b) for d, b in entries if d != date]
            else:
                print(f"{date}: drop requested, no entry found")
        for date, body in sorted(entries):
            if dates and date not in dates:
                continue
            # The gap marker is not an entry to rewrite: it is a
            # dated note written after the loop, and rewriting it
            # with the AI would destroy it (a second run over a
            # diary that already has the marker would otherwise
            # feed it to the model as a story to retell).
            if body.strip().startswith("GAP —"):
                print(f"{date}: gap marker, skipped")
                continue
            year, month, day = (int(v) for v in date.split("-"))
            day_start = _day_start(year, month, day)
            summary = diary.build_daily_summary(
                store, journal, day_start,
                "Erushtathtat", year)
            # Stocks, in priority order: run snapshots first, the
            # old entry's ledger second, the Store's trend samples
            # last. WITHOUT the run override the feed is wrong:
            # build_daily_summary uses the trend samples, and the
            # only one is tick 100800 (drink 39) — so the 04-05
            # feed would say drink 39 and the validator would
            # REJECT a correct "68" and ACCEPT a wrong "39".
            # The run snapshots are the freshest record (the
            # game's own numbers at that tick). Which source won
            # is logged per date, with the discrepancy when the
            # ledger and the run disagree.
            start, end = diary.ledger_stocks(body)
            source = "store"
            if start or end:
                source = "ledger"
                if start:
                    summary["stocks_start"].update(start)
                if end:
                    summary["stocks_end"].update(end)
            rs = run_stocks.get(date)
            if rs:
                for which in ("start", "end"):
                    if rs.get(which):
                        if source == "ledger":
                            for metric, val in rs[which].items():
                                old = (summary["stocks_start"]
                                       if which == "start"
                                       else summary["stocks_end"]
                                       ).get(metric)
                                if old is not None and old != val:
                                    print(f"{date}: ledger {which} "
                                          f"{metric} {old}, run "
                                          f"snapshot {which} "
                                          f"{val} — using run "
                                          f"snapshot")
                        (summary["stocks_start"] if which == "start"
                         else summary["stocks_end"]).update(rs[which])
                source = "run"
            if source == "store":
                # No ledger in this entry and no run stocks: fall
                # back to the pre-rewrite diary's ledger for the
                # date (see the --ledger-source note above). The
                # Store's trend sample is 04-01's and would lie
                # about a June day.
                src = source_ledgers.get(date)
                if src:
                    s_start, s_end = src
                    if s_start:
                        summary["stocks_start"].update(s_start)
                    if s_end:
                        summary["stocks_end"].update(s_end)
                    if s_start or s_end:
                        source = "ledger"
            summary["stocks_source"] = source
            print(f"{date}: stocks from {source}")
            # Arrivals from the population change, not from the
            # Journal's daemon events: the Journal mixes two
            # forts by tick, and the 06/07 tick-range events are
            # year 306 Athelunol (the events table has no year
            # column), so event-counted arrivals would be
            # Athelunol's. The population change is the fort's
            # own record: 06-02 pop 7 -> 10 is 3 arrivals, which
            # matches the three new citizens' first samples.
            pop_start = summary["stocks_start"].get("population")
            pop_end = summary["stocks_end"].get("population")
            if isinstance(pop_start, int) and isinstance(pop_end,
                                                        int):
                summary["arrivals"] = max(0, pop_end - pop_start)
            # The run's decisions: the entry's own phrases (the
            # journal's decisions re-rendered, outcome-less) plus
            # the run jsonl's action records (the M1 decisions the
            # Journal never saw). The dedup collapses the overlap.
            phrases = _parse_entry_phrases(body)
            run_decs = runs.get(date, [])
            if phrases or run_decs:
                diary.merge_driver_record(
                    summary, decisions=phrases + run_decs)
            if ai:
                # AI rewrite: the feed is built from the same
                # summary + the Store's per-dwarf samples (the feed
                # builder re-derives the ledger from the summary, so
                # the merged decisions/stocks above carry over), and
                # the model writes the entry. A failed write leaves
                # the old entry in place (logged, never fatal to the
                # rebuild); the template render is never written
                # instead.
                feed = diary.build_diary_feed(
                    store, journal, day_start, "Erushtathtat", year,
                    state_dir=state_dir)
                feed["summary"] = summary
                # Open threads are the STORE's latest state, not
                # the day's: open_threads takes the last sample
                # per dwarf whatever the day, so for a rebuild of
                # an old day it would list July's threads (nobody
                # wounded, everybody thirsty) on an April day.
                # A rebuild cannot reconstruct the day's threads,
                # so it claims none — the dwarf changes and the
                # recent entries carry the continuity instead.
                feed["threads"] = []
                # Stale per-dwarf record. When no full sample
                # falls inside the day, the feed's dwarves and
                # group counts are an older day's (04-05: six
                # wounded from 04-01; the June/July days: the
                # same six, plus 04-01's needs). The day's own
                # numbers come from the run snapshots first
                # (Population lines — the day's own data), else
                # from the lite samples. A snapshot override that
                # changes the counts also clears the named dwarves
                # (their states are not the day's) and drops the
                # other groups (stressed/mood/needs from the stale
                # day have no record here); the lite override
                # keeps its groups, all lite-derived.
                stale = not _day_has_full_samples(store, day_start)
                snap = snap_counts.get(date) if stale else None
                if snap:
                    end = snap.get("end") or {}
                    changed = False
                    new_counts = []
                    for g in feed.get("group_counts") or []:
                        if g["key"] in ("wounded", "idle") \
                                and g["key"] in end:
                            if (g["count"] != end[g["key"]]
                                    or g["total"]
                                    != end["population"]):
                                changed = True
                            new_counts.append({
                                "key": g["key"],
                                "label": g["label"],
                                "complement": g["complement"],
                                "count": end[g["key"]],
                                "total": end["population"],
                                "names": [], "not_names": []})
                    if changed:
                        feed["group_counts"] = new_counts
                        feed["dwarves"] = []
                        feed["no_per_dwarf_samples"] = True
                        print(f"{date}: per-dwarf record stale — "
                              f"group counts from run snapshots "
                              f"(wounded {end.get('wounded')}, "
                              f"idle {end.get('idle')}), dwarves "
                              f"cleared")
                    else:
                        print(f"{date}: per-dwarf record stale, "
                              f"snapshot counts agree "
                              f"(wounded {end.get('wounded')}, "
                              f"idle {end.get('idle')}) — dwarves "
                              f"kept")
                elif stale:
                    pop_end = summary["stocks_end"].get("population")
                    pop = pop_end if isinstance(pop_end, int) else 7
                    lite = _lite_dwarf_feed(store, day_start, pop,
                                            year)
                    if lite is None:
                        feed["dwarves"] = []
                        feed["group_counts"] = []
                        feed["no_per_dwarf_samples"] = True
                        print(f"{date}: no per-dwarf record at "
                              f"all — dwarves and counts cleared")
                    else:
                        day_end = (day_start
                                   + diary.TICKS_PER_DAY - 1)
                        rec_tick = lite["record_tick"]
                        rec_date = diary.date_str(rec_tick, year)
                        # Citizens with no sample at all (the
                        # migrants on 06-02: first sampled 06-03)
                        # are unnamed too, on top of the ones in
                        # the records as "an unnamed migrant".
                        no_record = pop - lite["sampled"]
                        unnamed = lite["unnamed"] + max(0, no_record)
                        if lite["span_ticks"] > _LITE_STALE_TICKS:
                            # Partial record: the per-citizen
                            # latest samples span weeks (06-02:
                            # two dwarves sampled today, the rest
                            # from 04-03). No single date owns the
                            # record, so no count is attributable
                            # to the day — clear it, and name the
                            # partial poll instead of hiding it.
                            feed["dwarves"] = []
                            feed["group_counts"] = []
                            feed["no_per_dwarf_samples"] = True
                            feed["last_dwarf_record_date"] = (
                                diary.date_str(
                                    rec_tick - lite["span_ticks"],
                                    year))
                            feed["partial_dwarf_record"] = {
                                "sampled": lite["in_day_sampled"],
                                "wounded": lite["in_day_wounded"]}
                            if unnamed:
                                feed["unnamed_citizens"] = unnamed
                            print(f"{date}: lite record spans "
                                  f"{lite['span_ticks']} ticks "
                                  f"(partial poll: "
                                  f"{lite['in_day_sampled']} sampled "
                                  f"today, "
                                  f"{lite['in_day_wounded']} wounded) "
                                  f"— dwarves and counts cleared")
                        elif day_end - rec_tick > _LITE_STALE_TICKS:
                            feed["dwarves"] = []
                            feed["group_counts"] = []
                            feed["no_per_dwarf_samples"] = True
                            feed["last_dwarf_record_date"] = rec_date
                            if unnamed:
                                feed["unnamed_citizens"] = unnamed
                            print(f"{date}: lite record from "
                                  f"{rec_date} is too old "
                                  f"({day_end - rec_tick} ticks) — "
                                  f"dwarves and counts cleared")
                        else:
                            feed["dwarves"] = lite["records"]
                            feed["group_counts"] = lite["counts"]
                            if unnamed:
                                feed["unnamed_citizens"] = unnamed
                            if rec_date != date:
                                feed["lite_dwarf_record_date"] = (
                                    rec_date)
                            w = next((g["count"]
                                      for g in lite["counts"]
                                      if g["key"] == "wounded"),
                                     "?")
                            print(f"{date}: per-dwarf record from "
                                  f"lite samples dated {rec_date} "
                                  f"(wounded {w} of {pop}, "
                                  f"{unnamed} unnamed)")
                try:
                    if dry_run:
                        # Preview the feed the model would get
                        # (stocks source, decisions, group counts,
                        # dwarves, notes) without calling the model
                        # or touching the file. The ai branch used
                        # to ignore --dry-run and write anyway.
                        print(f"{date}: AI feed preview — "
                              f"stocks from "
                              f"{summary.get('stocks_source')}, "
                              f"{len(summary['decisions'])} "
                              f"decisions, "
                              f"{len(feed['dwarves'])} dwarves, "
                              f"counts="
                              f"{[(g['key'], g['count'], g['total']) for g in feed.get('group_counts') or []]}, "
                              f"no_per_dwarf="
                              f"{bool(feed.get('no_per_dwarf_samples'))}, "
                              f"lite_record="
                              f"{feed.get('lite_dwarf_record_date')}, "
                              f"unnamed="
                              f"{feed.get('unnamed_citizens')}")
                        print("---")
                    else:
                        diary.write_ai_entry(client, feed, state_dir)
                        print(f"{date}: AI entry written")
                except Exception as exc:  # noqa: BLE001 - keep going
                    print(f"{date}: AI write failed, kept old entry: "
                          f"{exc}")
                continue
            rendered = diary.render_entry(summary)
            n_dec = len(summary["decisions"])
            n_obs = len(summary.get("observations") or [])
            crisis = bool(diary._stock_crisis_lines(summary))
            quiet = not rendered or "quiet day" in rendered.lower()
            print(f"{date}: {n_dec} decisions, {n_obs} observations, "
                  f"crisis={crisis}, quiet={quiet}")
            if dry_run:
                print(rendered)
                print("---")
            else:
                diary.write_entry(state_dir, summary)
        # The gap marker: a dated entry at the start of the hole,
        # written after the entry loop so the store's sort places
        # it chronologically. It is not AI-written (there are no
        # facts to write from) and it is not a template render —
        # the body is the marker text, stored as-is.
        gap_year, gap_month, gap_day = (
            int(v) for v in GAP_DATE.split("-"))
        gap_summary = diary.build_daily_summary(
            store, journal, _day_start(gap_year, gap_month, gap_day),
            "Erushtathtat", gap_year)
        if dry_run:
            print(f"{GAP_DATE}: gap marker (dry run, not written)")
            print(GAP_BODY)
            print("---")
        else:
            diary.write_ai_body(state_dir, gap_summary, GAP_BODY)
            print(f"{GAP_DATE}: gap marker written")
    finally:
        store.close()
        journal.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state-dir", default="~/.config/df-agent-harness")
    ap.add_argument("--logs-dir",
                    default=str(Path(__file__).resolve().parent.parent
                                / "logs"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ai", action="store_true",
                    help="rewrite each entry with the AI writer "
                         "(per-dwarf feed + model prose) instead of "
                         "the template renderer")
    ap.add_argument("--drop-dates", default="",
                    help="comma-separated dates whose entries are "
                         "deleted, not rewritten (ungrounded "
                         "entries, e.g. 125-03-28)")
    ap.add_argument("--dates", default="",
                    help="comma-separated dates to rebuild; when "
                         "given, all other entries are skipped "
                         "(the gap marker is still written)")
    ap.add_argument("--ledger-source", default="",
                    help="diary.md file to recover ledger lines "
                         "from when an entry has none and no run "
                         "stocks exist (the pre-rewrite diary: the "
                         "first run's AI entries dropped their "
                         "ledger lines, and the Store's only trend "
                         "sample is 04-01's)")
    args = ap.parse_args()
    rebuild(Path(args.state_dir), Path(args.logs_dir),
            dry_run=args.dry_run, ai=args.ai,
            drop_dates=[d.strip() for d in args.drop_dates.split(",")
                        if d.strip()] or None,
            dates=[d.strip() for d in args.dates.split(",")
                   if d.strip()] or None,
            ledger_source=(Path(args.ledger_source)
                           if args.ledger_source else None))


if __name__ == "__main__":
    main()
