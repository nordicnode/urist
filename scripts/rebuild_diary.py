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

from dfagent_harness import diary  # noqa: E402
from dfagent_harness.planner import Journal  # noqa: E402
from dfagent_harness.store import Store  # noqa: E402

HEADING_RE = re.compile(r"^## (\d+)-(\d+)-(\d+)", re.M)
DECISION_RE = re.compile(r"^I decided to (.+?)(?:\. |$)")


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
    """{date: [decisions]} from non-mock M1 run jsonls. Mock runs
    are excluded — they are not real fort history. A run's
    decisions are the ones the Journal never saw (the daemon loop
    is paused during runs); the 04-01 entry predates the diary
    wiring, so without this the Still build would be lost."""
    import json

    by_date: dict[str, list[dict]] = {}
    for path in sorted(Path(log_dir).glob("m1-*.jsonl")):
        date = None
        mock = False
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
            elif r.get("kind") == "action" and not mock and date:
                phrase = _phrase_from_action_record(r)
                if phrase:
                    decisions.append({
                        "decision": phrase,
                        "reason": r.get("model_reason", ""),
                        "action": r.get("name", ""),
                        "ok": r.get("ok"), "result": None})
        if decisions and date:
            by_date.setdefault(date, []).extend(decisions)
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
        # Drop the " — 2nd of Galena, 125" heading suffix.
        body = re.sub(r"^ — [^\n]*\n", "", body, count=1)
        entries.append((date, body))
    return entries


def rebuild(state_dir: Path, log_dir: Path,
            dry_run: bool = False, ai: bool = False) -> None:
    state_dir = Path(state_dir).expanduser()
    diary_path = diary.diary_md_path(state_dir)
    text = diary_path.read_text()
    entries = _split_entries(text)
    runs = _run_decisions_by_date(Path(log_dir).expanduser())
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
        for date, body in sorted(entries):
            year, month, day = (int(v) for v in date.split("-"))
            day_start = _day_start(year, month, day)
            summary = diary.build_daily_summary(
                store, journal, day_start,
                "Erushtathtat", year)
            # The ledger is the record for that day's stocks — the
            # Store's samples for old days were cleared.
            start, end = diary.ledger_stocks(body)
            if start:
                summary["stocks_start"].update(start)
            if end:
                summary["stocks_end"].update(end)
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
                try:
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
    args = ap.parse_args()
    rebuild(Path(args.state_dir), Path(args.logs_dir),
            dry_run=args.dry_run, ai=args.ai)


if __name__ == "__main__":
    main()
