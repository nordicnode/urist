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

from .dwarves import FEATURE_THRESHOLD, diff_unit_samples, dwarf_record

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


def parse_distress(reason: Any) -> str | None:
    """A planner distress diagnostic as an overseer's observation.
    "15 citizen(s) past a distress line: Udil (thirsty), ... —
    <advice>; <note>" -> "15 dwarves were in distress, all thirsty."
    The advice and the internal note after the dash are planner
    guidance, not story, and are dropped. Returns None when the
    reason is not a distress diagnostic."""
    if not isinstance(reason, str):
        return None
    m = _DISTRESS_RE.search(reason)
    if not m:
        return None
    pairs = []
    for part in m.group(2).split(", "):
        nm = _NEED_RE.match(part.strip())
        if nm:
            pairs.append((nm.group(1), nm.group(2)))
    if not pairs:
        return None
    needs = sorted({need for _, need in pairs})
    if len(pairs) == 1:
        return f"{pairs[0][0]} was in distress, {needs[0]}."
    if len(needs) == 1:
        return f"{len(pairs)} dwarves were in distress, all {needs[0]}."
    return (f"{len(pairs)} dwarves were in distress "
            f"({', '.join(needs)}).")


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

    Idempotent: re-finalizing an already-finalized list changes
    nothing (the log records are already gone, the dedup is
    stable)."""
    kept: list[dict[str, Any]] = []
    kept_ok: dict[str, set] = {}
    observations: list[str] = []
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
    # identical decisions collapse to one story beat.
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
    quiet. Returns the sentences, [] when the stocks are fine."""
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
            lines.append(f"The last of the {label} ran out today.")
        elif isinstance(e, (int, float)) and e == 0:
            lines.append(f"There is no {label} left in the fort.")
    return lines


def render_entry(summary: dict[str, Any]) -> str:
    """Render the daily summary as a diary entry (markdown body, no
    heading — write_entry adds the heading). Narrative prose in the
    overseer's voice, Boatmurdered-style: the day's story — what
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
    stock_bits = []
    for metric, label in (("drink", "Drink"), ("food", "Food"),
                          ("wood", "Wood"), ("stone", "Stone"),
                          ("population", "Citizens")):
        line = _stock_line(summary["stocks_start"],
                           summary["stocks_end"], metric, label)
        if line:
            stock_bits.append(line)
    if stock_bits:
        lines.append(" ".join(stock_bits) + ".")
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
        text = pattern.sub(entry.rstrip(), text)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + entry
    md_path.write_text(text)
    render_html(md_path, diary_html_path(state_dir), fort)
    return md_path


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


def _feed_samples(store: Any, uid: int, first: int, last: int
                  ) -> tuple[dict[str, Any] | None,
                             dict[str, Any] | None]:
    """(prev, curr) samples for one dwarf around a day. curr is the
    last sample at or before the day end; prev is the last sample
    before the day start, falling back to the earliest sample inside
    the day (so the first sampled day still diffs against the
    morning's state). (None, None) when the dwarf was never
    sampled."""
    samples = store.unit_history(uid)
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
    """The fort's open threads, derived from the current samples:
    a wounded dwarf, a stressed dwarf, a dwarf in a strange mood,
    a dwarf with an unmet need, a survival stock at zero. Each
    thread carries how long it has been true (walked back through
    the samples), so the diary can arc a story across days — a
    wound on its third day reads differently from a fresh one. A
    thread closes when its condition clears; nothing is stored, so
    a closed thread simply stops appearing."""
    first, last = day_range(day_start_tick)
    threads: list[dict[str, Any]] = []
    for uid in store.unit_ids():
        samples = store.unit_history(uid)
        if not samples:
            continue
        curr = samples[-1]
        name = curr.get("name") or f"dwarf {uid}"
        # A condition's start: the earliest sample in the current
        # unbroken run of samples where the condition holds.
        def _since(pred: Any) -> int | None:
            since = None
            for s in reversed(samples):
                if pred(s):
                    since = s.get("tick")
                else:
                    break
            return since if isinstance(since, int) else None

        wounds = curr.get("wounds") or []
        if wounds:
            since = _since(lambda s: bool(s.get("wounds")))
            threads.append({
                "kind": "wounded", "subject": name,
                "unit_id": uid,
                "detail": f"{len(wounds)} wound"
                          f"{'s' if len(wounds) > 1 else ''}",
                "since": date_str(since, year) if since else None})
        cat = curr.get("stress_category")
        if isinstance(cat, int) and cat != -1 and cat <= 1:
            since = _since(lambda s: isinstance(
                s.get("stress_category"), int)
                and s.get("stress_category") != -1
                and s.get("stress_category") <= 1)
            threads.append({
                "kind": "stressed", "subject": name,
                "unit_id": uid,
                "detail": ("at breaking point" if cat == 0
                           else "highly stressed"),
                "since": date_str(since, year) if since else None})
        mood = curr.get("mood")
        if isinstance(mood, int) and mood != -1:
            since = _since(lambda s: isinstance(s.get("mood"), int)
                           and s.get("mood") != -1)
            threads.append({
                "kind": "strange_mood", "subject": name,
                "unit_id": uid,
                "detail": curr.get("mood_name") or "a strange mood",
                "since": date_str(since, year) if since else None})
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


def build_diary_feed(store: Any, journal: Any,
                     day_start_tick: int,
                     fort_name: str = "",
                     year: int = 0,
                     state_dir: str | Path | None = None
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
                rsamples = store.unit_history(ruid)
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
        rec = dwarf_record(curr, changes, related)
        rec["featured"] = (
            rec["significance"] >= FEATURE_THRESHOLD
            or uid in featured_ids)
        dwarves.append(rec)
    dwarves.sort(key=lambda r: (not r["featured"],
                                -r["significance"],
                                r["name"]))
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
    return {"summary": summary, "dwarves": dwarves,
            "recent_entries": recent, "threads": threads}


_DIARY_SYSTEM = """You are the overseer of the Dwarf Fortress fort {fort}. You write one diary entry per in-game day, in the voice of a tired, dry-witted overseer chronicling their dwarves — Boatmurdered-style: a story about the dwarves as people, not a ledger and not a list.

RULES — break none of them:
- Write narrative prose in the first person ("I"), 150-300 words, a few paragraphs. Never a bullet list, never a table, never "I decided to ... It worked."
- Every claim must come from the facts supplied below. Never invent an event, a name, a number, or a death that is not in the facts. If the facts do not say what happened to a dwarf, do not guess — leave them out or say their fate is unclear.
- The recent entries are from EARLIER days and may describe a different telling of this fort's story. Never carry a claim forward from a recent entry unless TODAY'S facts confirm it. If a past entry says an attempt failed, it stays failed unless today's facts say it succeeded. Name a dwarf as doing a job only if today's facts name them doing it — never because an old entry named them.
- The entry is ABOUT THE DWARVES: their moods, stress, wounds, needs, relationships, and what happened to them today. The stocks are a ledger line at most — one short sentence, never the story.
- Continue any open thread that is still true (a wound, a stressed dwarf, a strange mood) and note when one closes. Refer back to the recent entries when a story arcs across days.
- Name the dwarves by name. Use each dwarf's full name the first time you mention them, and their first name after that. When you write about a dwarf, use their personal life from the facts: who they are close to, how that person is doing, what they need.
- Plain words, no game jargon, no internal terms (no "unit_id", no "tick", no "job_type", no "stress_category"). A stranger reading this should follow it as a story.
- If nothing happened today and no dwarf changed, say so in one or two sentences — a quiet day, plainly. Do not pad a quiet day into a saga."""


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
    for crisis in _stock_crisis_lines(summary):
        parts.append("CRISIS: " + crisis)
    for death in summary["deaths"]:
        parts.append(
            f"A dwarf died today: {death.get('cause') or 'an unknown cause'}.")
    if summary["arrivals"]:
        n = summary["arrivals"]
        parts.append(
            f"{n} new {'dwarf' if n == 1 else 'dwarves'} joined the fort today.")
    if summary["threats"]:
        parts.append("Something hostile came too close today.")
    for obs in summary.get("observations") or []:
        parts.append("Noted: " + obs)
    dec_phrases = []
    for dec in summary["decisions"]:
        phrase = clean_diary_text(
            dec.get("decision") or dec.get("action") or "")
        if not phrase:
            continue
        outcome = ("worked" if dec.get("ok") is True
                   else "did not work" if dec.get("ok") is False
                   else "outcome unknown")
        dec_phrases.append(f"{phrase} ({outcome})")
    if dec_phrases:
        parts.append("What I did today: " + "; ".join(dec_phrases) + ".")
    # The dwarves: featured first, each with their changes and
    # their personal life. A stable dwarf gets one line.
    dwarf_lines = []
    for rec in feed["dwarves"]:
        bits = [f"{rec['name']} ({rec['profession'] or 'dwarf'})"]
        if rec["mood"] != "none":
            bits.append(f"in a {rec['mood']} mood")
        stress_w = (rec["stress"] or {}).get("words") or ""
        if stress_w and stress_w not in ("content",):
            bits.append(f"{stress_w}")
        if rec["wounds"]:
            bits.append(
                f"{rec['wounds']} wound{'s' if rec['wounds'] > 1 else ''}")
        for n in rec["needs"]:
            bits.append(f"going without {n['need']}")
        if rec["job"]:
            bits.append(f"working as {rec['job']}")
        for ch in rec["changes"]:
            bits.append(ch["text"])
        for rel in rec["relations"]:
            rbits = f"{rel['type']} {rel['name']}"
            if rel.get("in_fort"):
                if rel.get("mood") and rel["mood"] != "none":
                    rbits += f" (in a {rel['mood']} mood)"
                if rel.get("stress"):
                    rbits += f" ({rel['stress']})"
                if rel.get("changed"):
                    rbits += " — changed today"
            else:
                rbits += " (not in the fort)"
            bits.append("close to " + rbits)
        marker = "FEATURED" if rec.get("featured") else "stable"
        dwarf_lines.append(f"[{marker}] " + "; ".join(bits) + ".")
    if dwarf_lines:
        parts.append("The dwarves:\n" + "\n".join(dwarf_lines))
    if feed["threads"]:
        tlines = []
        for t in feed["threads"]:
            since = f" since {t['since']}" if t.get("since") else ""
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
    return body


def write_ai_entry(client: Any, feed: dict[str, Any],
                   state_dir: str | Path) -> Path:
    """Write today's diary entry with the model. Builds the prompt
    from the feed, calls the model, validates the prose, stores it.
    Raises on model failure or bad output — the caller logs and
    skips the day; a template list is never written instead."""
    messages = diary_prompt(feed)
    text = client.chat(messages)
    body = _validate_ai_entry(text, feed)
    return write_ai_body(state_dir, feed["summary"], body)


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
    fort = fort_name or "the fort"
    data = json.dumps(entries)
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
