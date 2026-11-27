"""Retry the diary write for a completed M1 run whose diary call
failed (e.g. Free Pi IncompleteRead). Reconstructs the
POST /v1/control/diary body from the run's jsonl the same way
m1_driver._write_diary does, then posts it. Usage:
  .venv/bin/python scripts/retry_diary.py logs/m1-....jsonl
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from m1_driver import (  # noqa: E402
    TICKS_PER_DAY, _snapshot_citizens, diary_decision_text,
    decision_phrase_from_log, parse_fort_name,
    parse_snapshot_stocks, parse_snapshot_stocks_text)

TOKEN = Path("~/.config/df-agent-harness/token").expanduser().read_text().strip()


def main() -> int:
    log_path = Path(sys.argv[1])
    recs = [json.loads(line) for line in log_path.read_text().splitlines()
            if line.strip()]
    snaps = [r for r in recs if r.get("kind") == "snapshot"]
    actions = [r for r in recs if r.get("kind") == "action"]
    run_start = next((r for r in recs if r.get("kind") == "run_start"), None)
    if not snaps or run_start is None:
        print("no snapshots or run_start in log")
        return 1
    snap0 = snaps[0]
    snap = snaps[-1]
    # The jsonl snapshot records carry tick: None — the tick lives
    # in the snapshot TEXT ("... (tick 106696) ..."). The driver's
    # own _write_diary uses self.start_tick (recorded live); a
    # retry must parse it out of the text, or day_start_tick
    # collapses to 0 and the entry lands on the bogus date 0-01-01.
    import re as _re
    start_tick = None
    m = _re.search(r"tick (\d+)", snap0.get("text", "") or "")
    if m:
        start_tick = int(m.group(1))
    if start_tick is None:
        start_tick = run_start.get("start_tick")
    if start_tick is None:
        print("cannot determine start tick from log")
        return 1
    date = snap0.get("date") or ""
    try:
        year = int(str(date).split("-")[0])
    except (ValueError, IndexError):
        # The jsonl snapshots carry no date either; derive the year
        # from the tick (tick 0 is year 125 Granite 1 in this fort).
        year = 125
    decisions = []
    for a in actions:
        # The run log's action records carry name/ok/reason; the
        # phrase comes from the logged phrase when the driver
        # wrote one, else from the reason (queue_job) or params.
        # diary_decision_text alone cannot rebuild a queue_job
        # phrase from an empty params dict (see
        # decision_phrase_from_log).
        phrase = decision_phrase_from_log(a)
        if phrase is None:
            continue
        decisions.append({
            "decision": phrase,
            "reason": a.get("model_reason", ""),
            "action": a.get("name", ""),
            "ok": bool(a.get("ok")),
            "result": str(a.get("reason") or "")[:300],
        })
    body = {
        "day_start_tick": (start_tick // TICKS_PER_DAY * TICKS_PER_DAY),
        "year": year,
        "fort_name": parse_fort_name(snap0),
        "decisions": decisions,
        # The log's snapshots carry no sections — the numbers
        # live in the snapshot text. Parse the text first; the
        # sections parse is the fallback for a log that has them.
        "stocks_start": (
            parse_snapshot_stocks_text(snap0.get("text") or "")
            or parse_snapshot_stocks(
                (snap0 or {}).get("sections"))),
        "stocks_end": (
            parse_snapshot_stocks_text(snap.get("text") or "")
            or parse_snapshot_stocks(snap.get("sections"))),
        "citizens": _snapshot_citizens(snap),
        "citizens_start": _snapshot_citizens(snap0),
        "tick_start": start_tick,
    }
    print("day_start_tick:", body["day_start_tick"],
          "decisions:", len(decisions))
    req = urllib.request.Request(
        "http://127.0.0.1:8765/v1/control/diary",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {TOKEN}"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            print("HTTP", resp.status, resp.read().decode()[:300])
    except Exception as exc:  # noqa: BLE001 - report and exit nonzero
        print("diary retry failed:", exc)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
