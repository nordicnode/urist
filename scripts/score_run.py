"""Score one M1 run and (optionally) record it in the leaderboard.

The score is computed by the harness from the run log, the store, and
the daemon's events journal — never from what the model claimed.
Wealth comes from the run log's `wealth` records (the driver logs
fortress value at run start and run end via GET /v1/wealth); for an
older log without them, pass --wealth-start / --wealth-end explicitly
(measured live with GET /v1/wealth at the run's start and end states).
Without both readings the wealth dimension is neutral 50 and the
breakdown says so — the score never invents a wealth number, and it
never probes the live game on its own (the game may have moved on
from the run's end state).

Usage:
  .venv/bin/python scripts/score_run.py logs/m1-20261127-071025.jsonl
  .venv/bin/python scripts/score_run.py logs/m1-....jsonl --record
  .venv/bin/python scripts/score_run.py logs/m1-....jsonl \\
      --wealth-start 5418 --wealth-end 5410 --record
  .venv/bin/python scripts/score_run.py --leaderboard
  .venv/bin/python scripts/score_run.py --leaderboard --model deepseek-v4.1-flash
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.scoring import (  # noqa: E402
    Leaderboard, WEIGHTS, compute_score, default_scores_db_path)
from dfagent_harness.store import Store, default_world_db_path  # noqa: E402


def _print_score(score) -> None:
    print(f"model:        {score.model}")
    print(f"run:          {score.run_log}")
    print(f"start save:   {score.start_save}")
    print(f"tick budget:  {score.tick_budget} "
          f"({score.days_planned} day(s))")
    print(f"date:         {score.date}")
    print(f"composite:    {score.composite:.1f} / 100")
    print("dimensions:")
    for name in WEIGHTS:
        print(f"  {name:<11} {score.dimensions[name]:>5.1f} "
              f"(weight {WEIGHTS[name]:.0f})")
    print(f"milestones:   {', '.join(sorted(score.milestones)) or 'none'}"
          f" (+{score.to_dict()['milestone_bonus']:.0f})")
    print("evidence:")
    for k, v in score.evidence.items():
        print(f"  {k}: {json.dumps(v)}")


def _print_leaderboard(rows: list[dict]) -> None:
    if not rows:
        print("leaderboard is empty")
        return
    print(f"{'model':<24} {'composite':>9}  {'date':<12}  run")
    for r in rows:
        print(f"{r['model']:<24} {r['composite']:>9.1f}  "
              f"{r['date']:<12}  {Path(r['run_log']).name}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_log", nargs="?",
                    help="m1 run log (JSONL) to score")
    ap.add_argument("--store", default=None,
                    help="world.db path (default: daemon state dir)")
    ap.add_argument("--events", default=None,
                    help="events.jsonl path (default: daemon state dir)")
    ap.add_argument("--wealth-start", type=float, default=None,
                    help="fortress value at run start (GET /v1/wealth)")
    ap.add_argument("--wealth-end", type=float, default=None,
                    help="fortress value at run end (GET /v1/wealth)")
    ap.add_argument("--model", default=None,
                    help="model name (default: from the run log)")
    ap.add_argument("--start-save",
                    default="region2-00125-04-01-clean",
                    help="start save the run used")
    ap.add_argument("--record", action="store_true",
                    help="record the score in the leaderboard")
    ap.add_argument("--db", default=None,
                    help="scores.db path (default: daemon state dir)")
    ap.add_argument("--leaderboard", action="store_true",
                    help="list the leaderboard instead of scoring")
    args = ap.parse_args()

    if args.leaderboard:
        lb = Leaderboard(args.db)
        _print_leaderboard(lb.list_scores(model=args.model))
        lb.close()
        return 0
    if not args.run_log:
        ap.error("run_log is required unless --leaderboard is given")

    store = None
    store_path = Path(args.store) if args.store else default_world_db_path()
    if store_path.exists():
        store = Store(store_path)
    else:
        print(f"warning: store not found at {store_path}; deaths and "
              "needs come from the run log alone", file=sys.stderr)

    from pathlib import Path as _P
    state_dir = _P.home() / ".config" / "df-agent-harness"
    events_path = args.events or str(state_dir / "events.jsonl")

    score = compute_score(
        args.run_log, store=store, events_path=events_path,
        wealth_start=args.wealth_start, wealth_end=args.wealth_end,
        model=args.model, start_save=args.start_save)
    _print_score(score)
    if store is not None:
        store.close()
    if args.record:
        lb = Leaderboard(args.db or default_scores_db_path())
        lb.record(score)
        lb.close()
        print(f"recorded in {args.db or default_scores_db_path()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
