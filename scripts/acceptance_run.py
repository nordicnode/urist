#!/usr/bin/env python3
"""Live acceptance run (docs/ACCEPTANCE.md).

Runs the daemon against the loaded fort for a bounded window and
measures the acceptance criteria from before/after snapshots.

Usage (game loaded on the map, daemon running):
    .venv/bin/python scripts/acceptance_run.py [--minutes 10]
        [--out logs/acceptance-<ts>.json]

The runner does NOT start/stop the daemon or the game — the
operator does that. It exits non-zero when the game is down, the
fort is not loaded, or the run is interrupted by a crash, and
still writes the partial report. "produced" is a lower bound:
max(0, (drink+food) delta over the window) — consumption during
the window is not observable from stocks alone.
"""

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.acceptance import (  # noqa: E402
    check_expansion,
    check_no_neglect_deaths,
    check_stocks,
    check_survival,
    check_threat_response,
    evaluate_all,
)
from dfagent_harness.observe import collect  # noqa: E402
from dfhack_rpc import DFHackClient  # noqa: E402

HARNESS = Path(__file__).resolve().parent.parent
STATE_DIR = Path.home() / ".config" / "df-agent-harness"
DAEMON_URL = "http://127.0.0.1:8765"


def snapshot(client) -> dict:
    s = collect(client)
    st = s["status"]
    units = s["units"]
    citizens = {c["id"]: c for c in units.get("citizens", [])}
    return {
        "tick": st["year_tick"],
        "date": st.get("date"),
        "paused": st.get("paused"),
        "focus": st.get("focus"),
        "citizens": len(citizens),
        "citizen_ids": sorted(citizens),
        "citizen_names": {i: c.get("name") for i, c in citizens.items()},
        "hostile_ids": sorted(h["id"] for h in units.get("hostiles", [])),
        "buildings": len(s["buildings"].get("list", [])),
        "drink": s["stocks"].get("drink_units") or 0,
        "food": s["stocks"].get("food_units") or 0,
        "errors": s.get("errors") or [],
    }


def daemon_healthy() -> bool:
    try:
        with urllib.request.urlopen(DAEMON_URL + "/v1/health",
                                    timeout=10) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception:
        return False


def window_events(tick_start: int, tick_end: int) -> list[dict]:
    """Deaths + dehydration reports in the tick window, from events.jsonl."""
    path = STATE_DIR / "events.jsonl"
    out = []
    if not path.exists():
        return out
    for line in path.read_text(errors="replace").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        tick = e.get("tick")
        if tick is None or not (tick_start <= tick <= tick_end):
            continue
        if e.get("type") in ("unit_death", "report"):
            out.append(e)
    return out


def parse_deaths(before: dict, after: dict,
                 events: list[dict]) -> list[dict]:
    """Citizen deaths in the window: missing ids + event evidence."""
    deaths = []
    names = before["citizen_names"]
    for uid in before["citizen_ids"]:
        if uid in after["citizen_ids"]:
            continue
        cause = None
        name = names.get(uid, f"unit {uid}")
        for e in events:
            data = e.get("data") or {}
            if e.get("type") == "report":
                text = data.get("text", "")
                if name.split()[0] in text and "dehydrated" in text:
                    cause = "dehydrated"
                elif name.split()[0] in text and "starved" in text:
                    cause = "starved"
            elif e.get("type") == "unit_death" \
                    and data.get("unit_id") == uid:
                # A unit_death with no matching report: cause unknown
                # (the report may have scrolled off or the watcher
                # missed it); do not guess.
                pass
        deaths.append({"citizen": True, "name": name, "cause": cause,
                       "tick": None})
    return deaths


def threat_decision_tick(tick_start: int, tick_end: int) -> int | None:
    """First threat decision tick in the window, from the journal."""
    db = STATE_DIR / "journal.db"
    if not db.exists():
        return None
    con = sqlite3.connect(str(db))
    try:
        row = con.execute(
            "SELECT MIN(tick) FROM decisions "
            "WHERE goal_key LIKE 'threat:%' AND tick >= ? AND tick <= ?",
            (tick_start, tick_end)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--out", type=str, default="")
    args = ap.parse_args()

    if not daemon_healthy():
        print("acceptance: daemon not healthy on " + DAEMON_URL
              + " — start it first (dfh.py start)", file=sys.stderr)
        return 2
    client = DFHackClient("127.0.0.1", 5000, timeout=60.0)
    try:
        client.connect()
    except Exception as exc:  # noqa: BLE001 - report, don't traceback
        print(f"acceptance: cannot reach DFHack RPC: {exc}",
              file=sys.stderr)
        return 2

    try:
        before = snapshot(client)
    except Exception as exc:  # noqa: BLE001
        print(f"acceptance: before-snapshot failed: {exc}",
              file=sys.stderr)
        return 2
    if before["focus"] != "dwarfmode/Default":
        print(f"acceptance: fort not loaded (focus {before['focus']!r})",
              file=sys.stderr)
        return 2
    print(f"acceptance: start tick {before['tick']} "
          f"({before['date']}), {before['citizens']} citizens, "
          f"drink {before['drink']}u food {before['food']}u, "
          f"{before['buildings']} buildings; window {args.minutes} min")

    snapshots = [{"tick": before["tick"], "drink": before["drink"],
                  "food": before["food"]}]
    spawn_tick = None
    seen_hostiles = set(before["hostile_ids"])
    crashed = False
    deadline = time.time() + args.minutes * 60
    while time.time() < deadline:
        time.sleep(30)
        try:
            s = snapshot(client)
        except Exception as exc:  # noqa: BLE001 - crash interrupts
            print(f"acceptance: run interrupted — game unreachable: {exc}",
                  file=sys.stderr)
            crashed = True
            break
        snapshots.append({"tick": s["tick"], "drink": s["drink"],
                          "food": s["food"]})
        for hid in s["hostile_ids"]:
            if hid not in seen_hostiles:
                seen_hostiles.add(hid)
                if spawn_tick is None:
                    spawn_tick = s["tick"]
                    print(f"acceptance: new hostile {hid} at tick "
                          f"{spawn_tick}")
        print(f"acceptance: tick {s['tick']} drink {s['drink']}u "
              f"food {s['food']}u citizens {s['citizens']}")
    if crashed:
        after = None
    else:
        try:
            after = snapshot(client)
        except Exception as exc:  # noqa: BLE001
            print(f"acceptance: after-snapshot failed: {exc}",
                  file=sys.stderr)
            crashed = True
            after = None

    tick_end = after["tick"] if after else snapshots[-1]["tick"]
    events = window_events(before["tick"], tick_end)
    deaths = parse_deaths(before, after, events) if after else []
    produced = 0
    if after:
        produced = max(0, (after["drink"] + after["food"])
                       - (before["drink"] + before["food"]))
    results = {
        "a": check_survival(before["tick"], tick_end, deaths),
        "b": check_stocks(snapshots),
        "c": check_threat_response(
            spawn_tick,
            threat_decision_tick(before["tick"], tick_end)
            if spawn_tick is not None else None),
        "d": check_expansion(
            {"buildings": before["buildings"],
             "citizens": before["citizens"], "produced": 0},
            {"buildings": after["buildings"] if after else before["buildings"],
             "citizens": after["citizens"] if after else before["citizens"],
             "produced": produced}) if after else
        {"criterion": "d", "result": "untested",
         "evidence": "run interrupted before the after-snapshot"},
        "e": check_no_neglect_deaths(deaths, daemon_continuous=not crashed),
    }
    table = evaluate_all(results)
    print("\nacceptance results:")
    for r in table:
        print(f"  ({r['criterion']}) {r['result'].upper():12} {r['evidence']}")
    if crashed:
        print("acceptance: RUN INTERRUPTED BY CRASH — "
              "results are partial, not a pass")

    out_path = args.out or str(
        HARNESS / "logs" /
        f"acceptance-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json")
    report = {"started_utc": datetime.now(timezone.utc).isoformat(),
              "minutes": args.minutes, "crashed": crashed,
              "before": before, "after": after,
              "snapshots": snapshots, "deaths": deaths,
              "spawn_tick": spawn_tick, "results": table}
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(report, indent=2))
    print(f"acceptance: report written to {out_path}")
    return 1 if crashed or any(
        r["result"] == "fail" for r in table) else 0


if __name__ == "__main__":
    raise SystemExit(main())
