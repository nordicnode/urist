"""Retry the diary write for a completed M1 run whose diary call
failed (e.g. Free Pi IncompleteRead). Reconstructs the
POST /v1/control/diary body from the run's jsonl and posts it. Usage:
  .venv/bin/python scripts/retry_diary.py logs/m1-....jsonl

The body is assembled by m1_driver.build_diary_body — the same
function the live driver uses — so the two paths cannot drift apart
again (they had: the live path gained the fresh-citizens fix and the
retry path did not, and the retry gained the text-first stocks
fallback and the live path did not). The retry's inputs are
reconstructed from the log, which has two limits the live path does
not: the decisions are rebuilt from logged actions (a queue_job
phrase comes from the logged phrase or the result reason, never
from bare params), and the citizens are snapshot-only — a fresh
collect at retry time would read the fort as it is now, not as it
was at run end, so a retried entry can still misattribute a dwarf
(the Olon/Mestthos class of bug). That is a data limit, not a code
one; the live path's fresh fetch has no retry equivalent.
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from m1_driver import (  # noqa: E402
    _snapshot_citizens, build_diary_body, decision_phrase_from_log,
    parse_fort_name, parse_snapshot_stocks_any)


def _token() -> str:
    # Read lazily (in main), not at import: importing this module
    # must not need the daemon token file to exist.
    return Path("~/.config/df-agent-harness/token").expanduser().read_text().strip()


def build_retry_body(recs: list[dict]) -> dict:
    """The diary body reconstructed from a run log's records.
    Raises ValueError when the log cannot supply a start tick
    (then the entry would land on the bogus date 0-01-01)."""
    snaps = [r for r in recs if r.get("kind") == "snapshot"]
    actions = [r for r in recs if r.get("kind") == "action"]
    run_start = next((r for r in recs if r.get("kind") == "run_start"), None)
    if not snaps or run_start is None:
        raise ValueError("no snapshots or run_start in log")
    snap0 = snaps[0]
    snap = snaps[-1]
    # The jsonl snapshot records carry tick: None — the tick lives
    # in the snapshot TEXT ("... (tick 106696) ..."). The driver's
    # own _write_diary uses self.start_tick (recorded live); a
    # retry must parse it out of the text, or day_start_tick
    # collapses to 0 and the entry lands on the bogus date 0-01-01.
    start_tick = None
    m = re.search(r"tick (\d+)", snap0.get("text", "") or "")
    if m:
        start_tick = int(m.group(1))
    if start_tick is None:
        start_tick = run_start.get("start_tick")
    if start_tick is None:
        raise ValueError("cannot determine start tick from log")
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
    return build_diary_body(
        start_tick=start_tick,
        year=year,
        fort_name=parse_fort_name(snap0),
        decisions=decisions,
        stocks_start=parse_snapshot_stocks_any(snap0),
        stocks_end=parse_snapshot_stocks_any(snap),
        citizens=_snapshot_citizens(snap),
        citizens_start=_snapshot_citizens(snap0),
    )


def main() -> int:
    log_path = Path(sys.argv[1])
    recs = [json.loads(line) for line in log_path.read_text().splitlines()
            if line.strip()]
    try:
        body = build_retry_body(recs)
    except ValueError as exc:
        print(exc)
        return 1
    print("day_start_tick:", body["day_start_tick"],
          "decisions:", len(body["decisions"]))
    req = urllib.request.Request(
        "http://127.0.0.1:8765/v1/control/diary",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {_token()}"},
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
