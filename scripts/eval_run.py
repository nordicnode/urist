"""Benchmark suite runner (docs/EVALUATION.md Phase 3).

Runs a tier of the evaluation suite: a fixed scenario set, fixed
run lengths, fixed budgets, one model at a time. Records validity,
reruns infrastructure failures without counting them, and computes
the median, interquartile range, survival rate, and efficiency
numbers.

Usage:
  .venv/bin/python scripts/eval_run.py plan --tier day
  .venv/bin/python scripts/eval_run.py replay --tier day --model deepseek-v4.1-flash --logs logs/m1-....jsonl logs/m1-....jsonl [--record] [--db PATH]
  .venv/bin/python scripts/eval_run.py run --tier day --model deepseek-v4.1-flash --allow-live
  .venv/bin/python scripts/eval_run.py leaderboard [--db PATH] [--out docs/LEADERBOARD.md]
  .venv/bin/python scripts/eval_run.py baselines --kind noop

Live runs are scheduled by the main chat: the live fort is
serialized and only one track drives it at a time, only after the
diary commit lands. `run` refuses without --allow-live.

Tiers (EVALUATION.md): day = 1 in-game day, 10 repeats on the
anchor; season = 84 days, 6 scenarios x 1; year = 336 days,
6 x 1; two-year = 672 days, 6 x 2 = 12 runs (the headline).
Wall-clock estimate: 97 s per in-game day, measured on the
verified 1-day run (log m1-20261127-071025.jsonl, 07:10:26 to
07:12:03). It will get worse as forts grow; the runner measures
and reports actual wall time per run.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import evaluation as ev  # noqa: E402
from dfagent_harness.scoring import (  # noqa: E402
    Leaderboard, default_scores_db_path)

HARNESS = Path(__file__).resolve().parent.parent
VENV_PYTHON = HARNESS / ".venv" / "bin" / "python"

# The supervisor owns the main DF: the runner never kills DF
# behind its back (observed 2026-11-28: a direct reload_fort.py
# kill made run_df relaunch the pinned save while the daemon was
# down, and both baselines failed). The anchor reload is a
# request the supervisor consumes once (see run_df.py).
REQUEST_FILE = (Path.home() / ".config" / "df-agent-harness"
                / "reload-request")
TOKEN_FILE = Path.home() / ".config" / "df-agent-harness" / "token"
DAEMON_URL = "http://127.0.0.1:8765"
ANCHOR_SAVE = "region2-00125-04-01"
CLEAN_BASE = HARNESS / "saves-clean" / "region2-00125-04-01-clean"
ANCHOR_DIR = (HARNESS / "third_party" / "df_47_05" / "data"
              / "save" / ANCHOR_SAVE)

# Measured wall clock: 97 s per in-game day on the verified 1-day
# run. Estimates only; the runner reports actuals per run.
SECONDS_PER_DAY = 97.0

TIERS: dict[str, dict[str, object]] = {
    "day": {"days": 1, "scenarios": ["S0"], "repeats": 10,
            "purpose": "smoke and regression; tight confidence"},
    "season": {"days": 84, "scenarios": ["S0", "S1", "S2", "S3",
                                         "S4", "S5"], "repeats": 1,
               "purpose": "brewing, farming, first caravan cycle"},
    "year": {"days": 336, "scenarios": ["S0", "S1", "S2", "S3",
                                        "S4", "S5"], "repeats": 1,
             "purpose": "migrants, first siege season, winter"},
    "two-year": {"days": 672, "scenarios": ["S0", "S1", "S2", "S3",
                                            "S4", "S5"], "repeats": 2,
                 "purpose": "the benchmark headline; dkta parity"},
}


def _harness_commit() -> str | None:
    return ev.current_harness_commit()


def _matrix(tier: str) -> list[tuple[str, int]]:
    spec = TIERS[tier]
    return [(s, r) for s in spec["scenarios"]
            for r in range(1, spec["repeats"] + 1)]


def _estimate_hours(tier: str) -> float:
    spec = TIERS[tier]
    runs = len(spec["scenarios"]) * spec["repeats"]
    return runs * spec["days"] * SECONDS_PER_DAY / 3600.0


def cmd_plan(args) -> int:
    registry = ev.load_scenarios()
    by_id = {s["id"]: s for s in registry["scenarios"]}
    print(f"tier: {args.tier} — {TIERS[args.tier]['purpose']}")
    print(f"days per run: {TIERS[args.tier]['days']}")
    print(f"runs: {len(_matrix(args.tier))} "
          f"({len(TIERS[args.tier]['scenarios'])} scenarios x "
          f"{TIERS[args.tier]['repeats']} repeat(s))")
    print(f"estimated wall clock: {_estimate_hours(args.tier):.1f} h "
          f"serial (at {SECONDS_PER_DAY:.0f} s/day, measured; grows "
          "as forts grow)")
    print("scenarios:")
    for sid in TIERS[args.tier]["scenarios"]:
        s = by_id[sid]
        status = ("VERIFIED" if s.get("verified")
                  else "UNVERIFIED — generate live twice first")
        print(f"  {sid} {s['name']}: {status}")
    print("fixed: tick budget 150 ticks/decision tick, 8 decision "
          "ticks/day, max 2 actions/tick, protocol version "
          f"{ev.PROTOCOL_VERSION}")
    return 0


def _print_suite_stats(entries: list[dict]) -> None:
    stats = ev.suite_stats(entries)
    print(f"runs: {stats['n']}")
    if stats["median"] is not None:
        print(f"median composite: {stats['median']:.1f}")
        print(f"IQR: {stats['q1']:.1f}-{stats['q3']:.1f}")
        print(f"min/max: {stats['min']:.1f} / {stats['max']:.1f}")
    if stats["survival_rate"] is not None:
        print(f"survival rate: {stats['survival_rate']:.0%}")
    if stats["both_repeats_survived_rate"] is not None:
        print("both repeats survived: "
              f"{stats['both_repeats_survived_rate']:.0%}")
    for sid, s in stats["per_scenario"].items():
        med = (f"{s['median']:.1f}" if s["median"] is not None
               else "n/a")
        print(f"  {sid}: n={s['n']} median={med} "
              f"survival={s['survival_rate']:.0%}")


def cmd_replay(args) -> int:
    """Score recorded logs and compute suite stats (offline).
    Verifies the stats + leaderboard path without the live game.
    Logs are assigned scenario/repeat in the order given."""
    if not args.logs:
        print("replay needs --logs (recorded run logs)", file=sys.stderr)
        return 2
    entries = []
    manifests = []
    for i, log in enumerate(args.logs):
        repeat = i + 1
        manifest = ev.build_manifest(
            log, scenario_id=args.scenario, tier=args.tier,
            repeat=repeat, harness_commit=_harness_commit())
        manifest["manifest_path"] = str(
            Path(str(log) + ".manifest.json"))
        manifest["harness_version"] = _harness_commit()
        manifests.append(manifest)
        v2 = manifest["score_v2"]
        entries.append({
            "composite": v2["composite_v1"],
            "survived": manifest["validity"] == "valid",
            "scenario_id": args.scenario,
            "run_log": log,
        })
        print(f"{log}: v1 {v2['composite_v1']:.1f} "
              f"v2 {v2['composite_v2']} "
              f"({v2['v2_status']}) validity={manifest['validity']}")
        if args.write_manifests:
            ev.write_manifest(log, **{
                "scenario_id": args.scenario, "tier": args.tier,
                "repeat": repeat,
                "harness_commit": _harness_commit()})
    _print_suite_stats(entries)
    if args.record:
        lb = Leaderboard(args.db or default_scores_db_path())
        for m in manifests:
            lb.record_eval(m)
        lb.close()
        print(f"recorded {len(manifests)} eval row(s)")
    return 0


def _restore_anchor() -> bool:
    """Restore the S0 clean base into the working save dir.

    reload_fort.py loads the named folder as-is; it never restores
    the pristine base, so without this step repeats would start
    from wherever the previous repeat left the save instead of
    from identical conditions. The running game plays the pinned
    04-12 save, never this dir, so the copy is safe mid-run; and
    between repeats the game is paused (the driver leaves it so),
    so nothing writes to this dir during the copy.
    """
    try:
        if ANCHOR_DIR.exists():
            shutil.rmtree(ANCHOR_DIR)
        shutil.copytree(CLEAN_BASE, ANCHOR_DIR)
    except OSError as exc:
        print(f"reload: cannot restore the clean base: {exc}",
              file=sys.stderr)
        return False
    print("reload: S0 clean base restored from saves-clean",
          flush=True)
    return True


def _write_reload_request() -> bool:
    """Atomically write the supervisor reload request (temp + rename)."""
    cmd = (f"{VENV_PYTHON} {HARNESS / 'scripts' / 'reload_fort.py'} "
           f"{ANCHOR_SAVE} --exact")
    try:
        REQUEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = REQUEST_FILE.with_name(REQUEST_FILE.name + ".tmp")
        tmp.write_text(cmd + "\n", encoding="utf-8")
        os.replace(tmp, REQUEST_FILE)
    except OSError as exc:
        print(f"reload: cannot write request file: {exc}",
              file=sys.stderr)
        return False
    return True


def _wait_daemon_healthy(timeout: float = 600.0) -> bool:
    """Poll /v1/health until the fresh daemon answers (no auth)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    DAEMON_URL + "/v1/health", timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok") and data.get("df_reachable"):
                return True
        except Exception:  # noqa: BLE001 - daemon still down
            pass
        time.sleep(5.0)
    return False


def _anchor_loaded() -> bool:
    """Verify the reloaded fort IS the S0 anchor: paused, 7
    citizens, in-game April year 125. The live fort has 9 citizens
    at 125-07-10, so this distinguishes the two. Uses the live
    snapshot, not /v1/status (stale after a restart). One retry:
    the first snapshot after a daemon restart was observed empty.
    """
    for attempt in (1, 2):
        try:
            token = TOKEN_FILE.read_text(encoding="utf-8").strip()
            req = urllib.request.Request(
                DAEMON_URL + "/v1/snapshot",
                headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            text = data.get("text", "")
        except Exception as exc:  # noqa: BLE001
            print(f"reload: snapshot check failed: {exc}",
                  file=sys.stderr)
            return False
        if not text:
            if attempt == 1:
                time.sleep(30.0)
                continue
            print("reload: snapshot came back empty", file=sys.stderr)
            return False
        break
    header = text[:400]
    if "paused: True" not in header:
        print(f"reload: anchor not paused: {header[:200]!r}",
              file=sys.stderr)
        return False
    if "125-04-01" not in header:
        print(f"reload: anchor date wrong: {header[:200]!r}",
              file=sys.stderr)
        return False
    m = (re.search(r"Population: (\d+) citizens", text)
         or re.search(r"status: .*?\((\d+) citizens", text))
    if m is None or int(m.group(1)) != 7:
        print(f"reload: anchor citizens wrong: {header[:200]!r}",
              file=sys.stderr)
        return False
    print("reload: anchor verified live (125-04, 7 citizens, "
          "paused)", flush=True)
    return True


def _reload_anchor() -> bool:
    """Reload the S0 clean base via the supervisor.

    The supervisor owns the main DF, so the anchor reload is a
    request, not a kill: restore the clean base, write the reload
    request, restart the DF unit, and wait for the fresh daemon
    to report the anchor loaded and paused. Returns False when
    any step fails; the caller aborts the suite (a run on the
    wrong fort would poison the benchmark).
    """
    if not _restore_anchor():
        return False
    if not _write_reload_request():
        return False
    print("reload: requested S0 anchor via supervisor; restarting "
          "urist-df-main.service ...", flush=True)
    proc = subprocess.run(
        ["systemctl", "restart", "urist-df-main.service"],
        capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        print(f"reload: systemctl restart failed: "
              f"{proc.stderr[-1000:]}", file=sys.stderr)
        return False
    if not _wait_daemon_healthy():
        print("reload: daemon did not come back healthy after "
              "the supervisor reload", file=sys.stderr)
        return False
    if not _anchor_loaded():
        print("reload: anchor check FAILED — the reloaded fort "
              "is not the S0 anchor", file=sys.stderr)
        return False
    print("reload: GUARD 1 OK — S0 anchor loaded via supervisor, "
          "game paused, daemon healthy", flush=True)
    return True


def cmd_run(args) -> int:
    """Execute a tier live. Gated: refuses without --allow-live
    (live runs are scheduled by the main chat)."""
    if not args.allow_live:
        print("live runs are scheduled by the main chat: the live "
              "fort is serialized and only one track drives it at a "
              "time, only after the diary commit lands. Re-run with "
              "--allow-live once your turn is scheduled.",
              file=sys.stderr)
        return 2
    registry = ev.load_scenarios()
    by_id = {s["id"]: s for s in registry["scenarios"]}
    days = TIERS[args.tier]["days"]
    commit = _harness_commit()
    suite_ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suite_log: dict[str, object] = {
        "tier": args.tier, "model": args.model,
        "harness_commit": commit, "runs": [],
        "discarded_reruns": [],
    }
    lb = Leaderboard(args.db or default_scores_db_path())
    try:
        for scenario_id, repeat in _matrix(args.tier):
            scenario = by_id[scenario_id]
            if not scenario.get("verified"):
                print(f"{scenario_id}: UNVERIFIED scenario — "
                      "generate it live twice from its registry "
                      "entry first; skipping", file=sys.stderr)
                suite_log["runs"].append({
                    "scenario": scenario_id, "repeat": repeat,
                    "status": "skipped-unverified-scenario"})
                continue
            if scenario_id != "S0":
                print(f"{scenario_id}: live generation not wired "
                      "into the runner yet; skipping", file=sys.stderr)
                suite_log["runs"].append({
                    "scenario": scenario_id, "repeat": repeat,
                    "status": "skipped-generation-not-wired"})
                continue
            attempt = 0
            while attempt < 3:
                attempt += 1
                if not _reload_anchor():
                    print("reload failed; aborting suite",
                          file=sys.stderr)
                    return 1
                log_path = (HARNESS / "logs" /
                            f"eval-{args.tier}-{scenario_id}-"
                            f"r{repeat}-{suite_ts}.jsonl")
                rc = subprocess.run(
                    [str(VENV_PYTHON),
                     str(HARNESS / "scripts" / "m1_driver.py"),
                     "--days", str(days), "--model", args.model,
                     "--out", str(log_path)]).returncode
                if rc != 0:
                    print(f"driver exited {rc}; treating as "
                          "infrastructure failure", file=sys.stderr)
                    suite_log["discarded_reruns"].append({
                        "scenario": scenario_id, "repeat": repeat,
                        "attempt": attempt, "reason": "driver exit "
                        f"{rc}"})
                    continue
                manifest = ev.build_manifest(
                    log_path, scenario_id=scenario_id, tier=args.tier,
                    repeat=repeat, harness_commit=commit)
                manifest_path = ev.write_manifest(
                    log_path, scenario_id=scenario_id, tier=args.tier,
                    repeat=repeat, harness_commit=commit)
                manifest["manifest_path"] = str(manifest_path)
                if manifest["validity"] == "discarded":
                    print(f"{scenario_id} r{repeat}: discarded "
                          f"({manifest['validity_reason']}); "
                          "rerunning", file=sys.stderr)
                    suite_log["discarded_reruns"].append({
                        "scenario": scenario_id, "repeat": repeat,
                        "attempt": attempt,
                        "reason": manifest["validity_reason"]})
                    continue
                lb.record_eval(manifest)
                suite_log["runs"].append({
                    "scenario": scenario_id, "repeat": repeat,
                    "attempt": attempt, "run_log": str(log_path),
                    "manifest": str(manifest_path),
                    "validity": manifest["validity"],
                    "composite_v1": manifest["score_v1"]["composite"],
                    "composite_v2": manifest["score_v2"]
                    ["composite_v2"]})
                print(f"{scenario_id} r{repeat}: v1 "
                      f"{manifest['score_v1']['composite']:.1f} "
                      f"validity={manifest['validity']}")
                break
            else:
                print(f"{scenario_id} r{repeat}: discarded 3 times; "
                      "giving up on this run", file=sys.stderr)
                suite_log["runs"].append({
                    "scenario": scenario_id, "repeat": repeat,
                    "status": "abandoned-after-3-discards"})
    finally:
        lb.close()
        suite_path = (HARNESS / "logs" /
                      f"eval-suite-{suite_ts}.json")
        suite_path.write_text(json.dumps(suite_log, indent=2),
                              encoding="utf-8")
        print(f"suite manifest: {suite_path}")
    return 0


def cmd_leaderboard(args) -> int:
    lb = Leaderboard(args.db or default_scores_db_path())
    eval_rows = lb.list_eval()
    v1_rows = lb.list_scores()
    lb.close()
    out = Path(args.out) if args.out else HARNESS / "docs" / "LEADERBOARD.md"
    out.write_text(ev.render_leaderboard_md(eval_rows, v1_rows),
                   encoding="utf-8")
    print(f"wrote {out} ({len(eval_rows)} eval row(s), "
          f"{len(v1_rows)} v1 row(s))")
    return 0


def cmd_baselines(args) -> int:
    """Run one baseline live (S0 anchor, day tier, 1 repeat).
    Gated: refuses without --allow-live (live runs are scheduled
    by the main chat; the live fort is serialized). The no-op
    baseline uses the driver's --noop (never acts); the scripted
    baseline uses --scripted (the harness's checklist applied in
    order, no model). Both driver routes exist (track 4); the
    full multi-repeat, multi-scenario baseline suite is R2-6
    work, not this command."""
    if not args.allow_live:
        print("live runs are scheduled by the main chat: the live "
              "fort is serialized and only one track drives it at a "
              "time. Re-run with --allow-live once your turn is "
              "scheduled.", file=sys.stderr)
        return 2
    model = "noop" if args.kind == "noop" else "scripted"
    flag = "--noop" if args.kind == "noop" else "--scripted"
    if not _reload_anchor():
        print("reload failed; aborting baseline", file=sys.stderr)
        return 1
    suite_ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log_path = (HARNESS / "logs" /
                f"eval-baseline-{args.kind}-S0-{suite_ts}.jsonl")
    rc = subprocess.run(
        [str(VENV_PYTHON),
         str(HARNESS / "scripts" / "m1_driver.py"),
         "--days", "1", flag, "--out", str(log_path)]).returncode
    if rc != 0:
        print(f"driver exited {rc}; baseline failed",
              file=sys.stderr)
        return 1
    commit = _harness_commit()
    manifest = ev.build_manifest(
        log_path, model=model, scenario_id="S0", tier="day",
        repeat=1, harness_commit=commit)
    manifest_path = ev.write_manifest(
        log_path, model=model, scenario_id="S0", tier="day",
        repeat=1, harness_commit=commit)
    manifest["manifest_path"] = str(manifest_path)
    if manifest["validity"] == "discarded":
        print(f"baseline discarded ({manifest['validity_reason']})",
              file=sys.stderr)
        return 1
    lb = Leaderboard(args.db or default_scores_db_path())
    try:
        lb.record_eval(manifest)
    finally:
        lb.close()
    print(f"{args.kind} baseline: v1 "
          f"{manifest['score_v1']['composite']:.1f} "
          f"validity={manifest['validity']} "
          f"manifest={manifest_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    p_plan = sub.add_parser("plan", help="print a tier's run matrix")
    p_plan.add_argument("--tier", required=True, choices=TIERS)
    p_plan.set_defaults(fn=cmd_plan)
    p_replay = sub.add_parser("replay",
                              help="score recorded logs offline")
    p_replay.add_argument("--tier", required=True, choices=TIERS)
    p_replay.add_argument("--model", default=None)
    p_replay.add_argument("--scenario", default="S0")
    p_replay.add_argument("--logs", nargs="+", default=[])
    p_replay.add_argument("--record", action="store_true")
    p_replay.add_argument("--write-manifests", action="store_true")
    p_replay.add_argument("--db", default=None)
    p_replay.set_defaults(fn=cmd_replay)
    p_run = sub.add_parser("run", help="execute a tier live")
    p_run.add_argument("--tier", required=True, choices=TIERS)
    p_run.add_argument("--model", required=True)
    p_run.add_argument("--allow-live", action="store_true")
    p_run.add_argument("--db", default=None)
    p_run.set_defaults(fn=cmd_run)
    p_lb = sub.add_parser("leaderboard",
                          help="regenerate docs/LEADERBOARD.md")
    p_lb.add_argument("--db", default=None)
    p_lb.add_argument("--out", default=None)
    p_lb.set_defaults(fn=cmd_leaderboard)
    p_base = sub.add_parser("baselines", help="run one baseline live")
    p_base.add_argument("--kind", required=True,
                        choices=["noop", "scripted"])
    p_base.add_argument("--allow-live", action="store_true")
    p_base.add_argument("--db", default=None)
    p_base.set_defaults(fn=cmd_baselines)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
