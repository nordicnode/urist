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


def date_words(tick: int, year: int = 0) -> str:
    """'2nd of Galena, 125' for a year_tick + year."""
    y, m, d = date_of_tick(tick, year)
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(d, "th")
    return f"{d}{suffix} of {MONTHS[m - 1]}, {y}"


def season_of_tick(tick: int) -> str:
    return SEASONS[date_of_tick(tick)[1] - 1]


def day_range(day_start_tick: int) -> tuple[int, int]:
    """(first, last) year_tick of the day starting at day_start_tick
    (which must be a multiple of TICKS_PER_DAY)."""
    return day_start_tick, day_start_tick + TICKS_PER_DAY - 1


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


def render_entry(summary: dict[str, Any]) -> str:
    """Render the daily summary as a diary entry (markdown body, no
    heading — write_entry adds the heading). First-person overseer
    voice, Boatmurdered-style, but every sentence states a recorded
    fact from the summary. Nothing is invented: when there is nothing
    to say about a topic, it is not mentioned."""
    lines: list[str] = []
    date = summary["date_words"]
    season = summary["season"]
    lines.append(f"The {date}, {season}.")
    lines.append("")
    # Stocks.
    stock_bits = []
    for metric, label in (("drink", "Drink"), ("food", "Food"),
                          ("wood", "Wood"), ("stone", "Stone"),
                          ("population", "Souls")):
        line = _stock_line(summary["stocks_start"],
                           summary["stocks_end"], metric, label)
        if line:
            stock_bits.append(line)
    if stock_bits:
        lines.append(" ".join(stock_bits) + ".")
        lines.append("")
    # Deaths first — they are the day's weight.
    for death in summary["deaths"]:
        cause = death.get("cause") or "unknown cause"
        uid = death.get("unit_id")
        lines.append(f"A dwarf died today (id {uid}): {cause}.")
    if summary["deaths"]:
        lines.append("")
    # Arrivals and threats.
    if summary["arrivals"]:
        n = summary["arrivals"]
        lines.append(f"{n} new {'soul' if n == 1 else 'souls'} "
                     f"joined the fort today.")
    if summary["threats"]:
        lines.append("Something hostile came too close today; "
                     "the fort held its breath.")
    if summary["arrivals"] or summary["threats"]:
        lines.append("")
    # Decisions, in the order they were made, with their outcome.
    for dec in summary["decisions"]:
        what = dec.get("decision") or dec.get("action") or "a decision"
        why = dec.get("reason") or ""
        ok = dec.get("ok")
        outcome = ""
        if ok is True:
            outcome = " It worked."
        elif ok is False:
            outcome = " It did not work."
        result = dec.get("result") or ""
        if result:
            outcome += f" ({result})"
        sentence = f"I decided to {what}."
        if why:
            sentence += f" {why}"
        sentence += outcome
        lines.append(sentence)
    if summary["decisions"]:
        lines.append("")
    # Notable events (not arrivals/threats, which are above).
    skip = {"citizen_new", "new_arrival", "threat_hold",
            "hostile_spawn", "invasion", "snapshot"}
    for ev in summary["events"]:
        if ev.get("kind") in skip:
            continue
        detail = ev.get("detail") or ""
        kind = ev.get("kind") or "event"
        if detail:
            lines.append(f"{kind}: {detail}")
        else:
            lines.append(f"{kind}.")
    if any(ev.get("kind") not in skip
           for ev in summary["events"]):
        lines.append("")
    # A quiet day says so, plainly.
    if (not summary["deaths"] and not summary["decisions"]
            and not summary["events"]):
        lines.append("A quiet day. Nothing happened that the "
                     "fort felt the need to record.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ----------------------------------------------------------------------
# diary.md: the source of truth.
# ----------------------------------------------------------------------

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
    md_path = diary_md_path(state_dir)
    fort = summary.get("fort_name") or "the fort"
    heading = f"## {summary['date']} — {summary['date_words']}"
    body = render_entry(summary)
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
    entry = heading + "\n\n" + body
    if pattern.search(text):
        text = pattern.sub(entry.rstrip(), text)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += "\n" + entry
    md_path.write_text(text)
    render_html(md_path, diary_html_path(state_dir), fort)
    return md_path


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
