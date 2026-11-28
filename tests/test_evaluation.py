"""Offline tests for the evaluation framework (docs/EVALUATION.md).

The benchmark layer on top of scoring.py: run manifests, the failure
taxonomy, score v2, suite statistics, the scenario registry, the
eval_runs leaderboard table, and the suite runner. These tests use
synthetic run logs and a fake Store (no game, no daemon). Live
verification (scenario generation, a real multi-day suite, the
baselines) is separate and waits for a scheduled live turn.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                      / "scripts"))

from dfagent_harness import evaluation as ev  # noqa: E402
from dfagent_harness.evaluation import (  # noqa: E402
    WEIGHTS_V2, build_manifest,
    classify_action_failure, classify_model_failure,
    composite_v2, craft_share_cap, expansion_score,
    failure_taxonomy, load_scenarios, median,
    milestones_v2_from_log, ordering_verdict, quartiles,
    render_leaderboard_md, suite_stats, validity_verdict)
from dfagent_harness.scoring import Leaderboard  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _synthetic_log(tmp: Path, name: str = "m1-test.jsonl",
                   reason: str = "day complete",
                   model: str = "deepseek-v4.1-flash") -> Path:
    """A one-day run log: still built, brew queued, one failed brew
    (material shortage), one IncompleteRead, 0 idle ticks."""
    recs = [
        {"kind": "run_start", "days": 1.0, "window": 150,
         "model": model, "mock": False,
         "ts": "2026-11-27T07:10:26.000000+00:00"},
        {"kind": "diary_citizens", "when": "start", "count": 7},
        {"kind": "start_tick", "start_tick": 101323,
         "end_tick": 102523, "date": "125-04-01"},
        {"kind": "snapshot", "tick_no": 1,
         "text": "Stocks: drink 38, food 32, wood 124, stone 0. "
                 "Bed: need 1 BED item to place — have 0",
         "suggestion": "build a still"},
        {"kind": "action", "tick_no": 1, "name": "build_workshop",
         "ok": True, "params": {"kind": "Still", "pos": [94, 107, 175]},
         "phrase": "build a Still"},
        {"kind": "action", "tick_no": 1, "name": "queue_job",
         "ok": True, "params": {"building_id": 7, "job": "make_bed",
                                "count": 1},
         "phrase": "queue make_bed x1"},
        {"kind": "snapshot", "tick_no": 2,
         "text": "Stocks: drink 35, food 32, wood 124, stone 0. "
                 "Bed: need 1 BED item to place — have 1",
         "suggestion": "run the brew task"},
        {"kind": "action", "tick_no": 2, "name": "queue_job",
         "ok": True, "params": {"building_id": 8, "job": "brew",
                                "count": 2},
         "phrase": "queue brew x2"},
        {"kind": "action", "tick_no": 2, "name": "queue_job",
         "ok": True, "params": {"building_id": 7, "job": "make_barrel",
                                "count": 3},
         "phrase": "queue make_barrel x3"},
        {"kind": "action", "tick_no": 2, "name": "queue_job",
         "ok": False, "params": {"building_id": 8, "job": "brew",
                                 "count": 1},
         "phrase": "queue brew x1",
         "reason": "cannot queue brew x1 on building #8: material "
                   "shortage — need 3 in total (1 empty barrel "
                   "each), have 2 — queue make_barrel at the "
                   "carpenter #7"},
        {"kind": "model_failure", "tick_no": 3,
         "error": "IncompleteRead(0 bytes read)", "consecutive": 1},
        {"kind": "snapshot", "tick_no": 3,
         "text": "Stocks: drink 39, food 32, wood 124, stone 0. "
                 "Bed: need 1 BED item to place — have 1",
         "suggestion": "queue make_barrel"},
        {"kind": "diary_citizens", "when": "end", "count": 7},
        {"kind": "wealth", "when": "start", "fortress_value": 5418},
        {"kind": "wealth", "when": "end", "fortress_value": 5410},
        {"kind": "run_end", "reason": reason, "tick": 102523,
         "end_tick": 102523, "actions_taken": 5, "idle_ticks": 0,
         "ts": "2026-11-27T07:12:03.000000+00:00"},
    ]
    p = tmp / name
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return p


class TestFailureTaxonomy(unittest.TestCase):

    def test_model_failure_kinds(self):
        self.assertEqual(classify_model_failure(
            "IncompleteRead(0 bytes read)"), "transport")
        self.assertEqual(classify_model_failure(
            "Free Pi chat -> HTTP 429: concurrent"), "provider")
        self.assertEqual(classify_model_failure(
            "Free Pi chat -> HTTP 401: bad token"), "provider")
        self.assertEqual(classify_model_failure(
            "JSON parse failed: no choices"), "parse")
        self.assertEqual(classify_model_failure(
            "request timed out after 180s"), "timeout")
        self.assertEqual(classify_model_failure(
            "something entirely new"), "unclassified")

    def test_action_failure_kinds(self):
        self.assertEqual(classify_action_failure(
            "cannot queue brew x1: material shortage — need 3, "
            "have 2 — queue make_barrel at the carpenter #7"),
            "harness_refusal_named_fix")
        self.assertEqual(classify_action_failure(
            "unknown action: frobnicate"), "model_error")
        self.assertEqual(classify_action_failure(
            "no path to the site"), "game_constraint")
        self.assertEqual(classify_action_failure(
            "something entirely new"), "unclassified")

    def test_taxonomy_counts(self):
        from dfagent_harness.scoring import parse_run_log
        with tempfile.TemporaryDirectory() as d:
            log = _synthetic_log(Path(d))
            run = parse_run_log(log)
            tax = failure_taxonomy(run)
        self.assertEqual(tax["model_failures"], {"transport": 1})
        self.assertEqual(tax["action_failures"],
                         {"harness_refusal_named_fix": 1})
        self.assertEqual(tax["model_failures_unclassified"], [])
        self.assertEqual(tax["action_failures_unclassified"], [])


class TestValidity(unittest.TestCase):

    def _run(self, reason):
        from dfagent_harness.scoring import parse_run_log
        with tempfile.TemporaryDirectory() as d:
            log = _synthetic_log(Path(d), reason=reason)
            return parse_run_log(log)

    def test_day_complete_is_valid(self):
        verdict, _ = validity_verdict(self._run("day complete"))
        self.assertEqual(verdict, "valid")

    def test_fort_death_is_valid(self):
        verdict, _ = validity_verdict(
            self._run("fort died of thirst"))
        self.assertEqual(verdict, "valid")

    def test_infra_is_discarded(self):
        verdict, _ = validity_verdict(self._run("VM reboot"))
        self.assertEqual(verdict, "discarded")

    def test_unknown_reason_is_unclassified(self):
        verdict, _ = validity_verdict(self._run("hard error"))
        self.assertEqual(verdict, "unclassified")


class TestManifest(unittest.TestCase):

    def test_manifest_fields_and_gaps(self):
        with tempfile.TemporaryDirectory() as d:
            log = _synthetic_log(Path(d))
            m = build_manifest(log, scenario_id="S0", tier="day",
                               repeat=1)
        self.assertEqual(m["manifest_version"], 1)
        self.assertEqual(m["model"], "deepseek-v4.1-flash")
        self.assertEqual(m["model_resolved"],
                         "deepseek-v4.1-flash-1017")
        self.assertEqual(m["provider"], "free-pi")
        self.assertEqual(m["model_params"], {"temperature": 0.2})
        self.assertEqual(m["scenario_id"], "S0")
        self.assertEqual(m["validity"], "valid")
        # Nothing invented: no tokens, no harness commit, no
        # protocol version in a legacy log.
        self.assertIsNone(m["efficiency"]["tokens_in"])
        self.assertIsNone(m["efficiency"]["tokens_out"])
        self.assertIsNone(m["harness_commit"])
        self.assertIsNone(m["protocol_version"])
        self.assertIn("harness_commit (not recorded in the log",
                      " ".join(m["gaps"]))
        self.assertTrue(any(g.startswith("protocol_version")
                            for g in m["gaps"]))
        # Wall clock is derivable from the log timestamps: 97 s.
        self.assertAlmostEqual(m["efficiency"]["wall_clock_s"], 97.0)
        self.assertAlmostEqual(
            m["efficiency"]["wall_clock_s_per_day"], 97.0)
        self.assertEqual(m["efficiency"]["cost_usd"], 0.0)
        # The score is embedded so it can be recomputed.
        self.assertAlmostEqual(m["score_v1"]["composite"], 96.2,
                               places=1)

    def test_manifest_with_model_call_records(self):
        with tempfile.TemporaryDirectory() as d:
            log = _synthetic_log(Path(d))
            recs = [json.loads(line) for line in
                    log.read_text().splitlines()]
            recs.insert(2, {"kind": "model_call", "tick_no": 1,
                            "prompt_tokens": 12000,
                            "completion_tokens": 300,
                            "latency_s": 2.5})
            log.write_text("\n".join(json.dumps(r) for r in recs)
                           + "\n")
            m = build_manifest(log)
        self.assertEqual(m["efficiency"]["tokens_in"], 12000)
        self.assertEqual(m["efficiency"]["tokens_out"], 300)
        self.assertEqual(m["efficiency"]["tokens_per_day"], 12300)
        self.assertNotIn("tokens_in / tokens_out (no model_call "
                         "records; the Free Pi client discards the "
                         "usage field)", m["gaps"])

    def test_manifest_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            log = _synthetic_log(Path(d))
            out = ev.write_manifest(log, scenario_id="S0",
                                    tier="day", repeat=1)
            loaded = ev.load_manifest(out)
        self.assertEqual(loaded["scenario_id"], "S0")
        self.assertEqual(loaded["score_v1"]["composite"], 96.2)


class TestScoreV2(unittest.TestCase):

    def test_weights_sum_to_100(self):
        self.assertAlmostEqual(sum(WEIGHTS_V2.values()), 100.0)

    def test_expansion_counts_systems_once(self):
        actions = [
            {"name": "build_workshop", "ok": True,
             "params": {"kind": "Still"}},
            {"name": "queue_job", "ok": True,
             "params": {"job": "make_bed"}},
            {"name": "queue_job", "ok": True,
             "params": {"job": "make_barrel"}},
            {"name": "queue_job", "ok": True,
             "params": {"job": "brew"}},
            {"name": "build_farm_plot", "ok": True, "params": {}},
            {"name": "queue_job", "ok": False,
             "params": {"job": "engrave"}},
        ]
        score, used = expansion_score(actions)
        # Still (no system), make_bed + make_barrel (crafts once),
        # brew (no system), farm plot (farming). Failed engrave
        # does not count.
        self.assertEqual(used, {"crafts", "farming"})
        self.assertAlmostEqual(score, 100.0 * 2 / 8)

    def test_v2_partial_until_gated_dimensions_land(self):
        with tempfile.TemporaryDirectory() as d:
            log = _synthetic_log(Path(d))
            v2 = ev.compute_score_v2(log)
        self.assertIsNone(v2["composite_v2"])
        self.assertFalse(v2["v2_published"])
        self.assertEqual(v2["dimensions_v2"]["expansion"], 12.5)
        self.assertIsNone(v2["dimensions_v2"]["economy"])
        self.assertIsNone(v2["dimensions_v2"]["defense"])
        self.assertIsNone(v2["dimensions_v2"]["diplomacy"])
        self.assertEqual(v2["composite_v1"], 96.2)

    def test_composite_v2_full(self):
        dims = dict(WEIGHTS_V2)
        dims = {k: 100.0 for k in WEIGHTS_V2}
        self.assertEqual(composite_v2(dims, set()), 100.0)
        dims["survival"] = 50.0
        # 25 points of survival at 50 instead of 100: -12.5.
        self.assertAlmostEqual(composite_v2(dims, set()), 87.5)
        self.assertAlmostEqual(
            composite_v2(dims, {"first brew", "first bed"}), 91.5)
        partial = dict(dims)
        partial["economy"] = None
        self.assertIsNone(composite_v2(partial, set()))

    def test_milestones_v2(self):
        from dfagent_harness.scoring import parse_run_log
        with tempfile.TemporaryDirectory() as d:
            log = _synthetic_log(Path(d))
            run = parse_run_log(log)
            achieved, reasons = milestones_v2_from_log(run)
        # No siege, no trade, no artifact, no population rise.
        self.assertEqual(achieved, set())
        self.assertIn("not detectable", reasons["first caravan traded"])
        self.assertIn("not detectable", reasons["first artifact"])

    def test_milestone_siege_survived(self):
        from dfagent_harness.scoring import parse_run_log
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            log = _synthetic_log(tmp)
            events = tmp / "events.jsonl"
            events.write_text(json.dumps(
                {"tick": 101500, "type": "hostile_spawn",
                 "data": {"unit_id": 9999}}) + "\n")
            run = parse_run_log(log)
            achieved, _ = milestones_v2_from_log(run, events)
        self.assertIn("first siege survived", achieved)

    def test_milestone_migrant_wave_housed(self):
        from dfagent_harness.scoring import parse_run_log
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            recs = [json.loads(line) for line in
                    _synthetic_log(tmp).read_text().splitlines()]
            for r in recs:
                if r.get("kind") == "diary_citizens" \
                        and r.get("when") == "end":
                    r["count"] = 10
            log = tmp / "m1-migrants.jsonl"
            log.write_text("\n".join(json.dumps(r) for r in recs)
                           + "\n")
            run = parse_run_log(log)
            achieved, _ = milestones_v2_from_log(run)
        # Population 7 -> 10 and a bed item available (have 1).
        self.assertIn("first migrant wave housed", achieved)

    def test_craft_share_cap_is_proposed_not_adopted(self):
        # Cap binds at the built value: non-craft growth (10) plus
        # min(craft 90, built 40) = 50.
        self.assertEqual(craft_share_cap(100.0, 90.0, 40.0), 50.0)
        self.assertEqual(craft_share_cap(30.0, 10.0, 40.0), 30.0)
        self.assertEqual(craft_share_cap(0.0, 0.0, 0.0), 0.0)


class TestSuiteStats(unittest.TestCase):

    def test_median_and_quartiles(self):
        self.assertEqual(median([1, 2, 3]), 2.0)
        self.assertEqual(median([]), None)
        q1, med, q3 = quartiles([80, 85, 90, 95])
        self.assertEqual(med, 87.5)
        self.assertTrue(q1 < med < q3)

    def test_suite_stats(self):
        entries = [
            {"composite": 91.8, "survived": True, "scenario_id": "S0"},
            {"composite": 91.7, "survived": True, "scenario_id": "S0"},
            {"composite": 40.0, "survived": False, "scenario_id": "S1"},
        ]
        stats = suite_stats(entries)
        self.assertEqual(stats["n"], 3)
        self.assertEqual(stats["median"], 91.7)
        self.assertAlmostEqual(stats["survival_rate"], 2 / 3)
        self.assertEqual(stats["per_scenario"]["S0"]["n"], 2)
        self.assertEqual(stats["per_scenario"]["S1"]["n"], 1)

    def test_both_repeats_survived(self):
        entries = [
            {"composite": 90.0, "survived": True, "scenario_id": "S0"},
            {"composite": 91.0, "survived": True, "scenario_id": "S0"},
            {"composite": 50.0, "survived": True, "scenario_id": "S1"},
            {"composite": 20.0, "survived": False, "scenario_id": "S1"},
        ]
        stats = suite_stats(entries)
        self.assertAlmostEqual(stats["both_repeats_survived_rate"],
                               0.5)

    def test_ordering_verdict(self):
        a = {"q1": 80.0, "q3": 90.0, "median": 85.0}
        b = {"q1": 82.0, "q3": 92.0, "median": 87.0}
        self.assertIn("no ordering established",
                      ordering_verdict(a, b))
        c = {"q1": 91.0, "q3": 95.0, "median": 93.0}
        self.assertIn("ordering established",
                      ordering_verdict(a, c))
        self.assertIn("too few runs",
                      ordering_verdict({"q1": None, "q3": None,
                                        "median": None}, a))


class TestScenarioRegistry(unittest.TestCase):

    def test_loads_and_anchor_verified(self):
        registry = load_scenarios()
        self.assertEqual(len(registry["scenarios"]), 7)
        held_out = [s for s in registry["scenarios"]
                    if s.get("held_out")]
        self.assertEqual(len(held_out), 1)
        self.assertEqual(held_out[0]["id"], "S6")
        # The S0 anchor save lives in saves-clean/, which is
        # local-only (gitignored): on a fresh checkout it is
        # absent and the anchor cannot be verified, so skip that
        # assertion instead of failing (CI has no saves-clean).
        anchor = next((s for s in registry["scenarios"]
                       if s.get("id") == "S0"), None)
        save = anchor.get("save") if anchor else None
        if not save or not (REPO / "saves-clean" / save).is_dir():
            self.skipTest("S0 anchor save not present in saves-clean/")
        self.assertTrue(ev.anchor_verified(registry))
        unverified = [s["id"] for s in registry["scenarios"]
                      if not s.get("verified")]
        self.assertEqual(unverified, ["S1", "S2", "S3", "S4", "S5",
                                      "S6"])

    def test_duplicate_ids_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "scenarios.json"
            p.write_text(json.dumps({"scenarios": [
                {"id": "S0", "kind": "clean-base"},
                {"id": "S0", "kind": "clean-base"},
            ]}))
            with self.assertRaises(ValueError):
                load_scenarios(p)

    def test_missing_held_out_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "scenarios.json"
            p.write_text(json.dumps({"scenarios": [
                {"id": "S0", "kind": "clean-base"},
            ]}))
            with self.assertRaises(ValueError):
                load_scenarios(p)


class TestEvalLeaderboard(unittest.TestCase):

    def _manifest(self, tmp, composite=91.8, scenario="S0",
                  repeat=1, tier="day"):
        log = _synthetic_log(tmp, name=f"m1-{repeat}.jsonl")
        m = build_manifest(log, scenario_id=scenario, tier=tier,
                           repeat=repeat)
        m["manifest_path"] = str(log) + ".manifest.json"
        m["harness_version"] = "abc123"
        return m

    def test_record_and_list_eval(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "scores.db"
            lb = Leaderboard(db)
            lb.record_eval(self._manifest(Path(d)))
            lb.record_eval(self._manifest(Path(d), repeat=2))
            rows = lb.list_eval()
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["scenario_id"], "S0")
            self.assertEqual(rows[0]["validity"], "valid")
            self.assertEqual(rows[0]["harness_version"], "abc123")
            self.assertIsNone(rows[0]["composite_v2"])
            lb.close()

    def test_rerecord_replaces_row(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "scores.db"
            lb = Leaderboard(db)
            lb.record_eval(self._manifest(Path(d)))
            lb.record_eval(self._manifest(Path(d)))
            self.assertEqual(len(lb.list_eval()), 1)
            lb.close()

    def test_render_leaderboard_empty(self):
        md = render_leaderboard_md([], [
            {"model": "deepseek-v4.1-flash", "composite": 91.8,
             "date": "125-04-01",
             "run_log": "logs/m1-20261127-071025.jsonl"}])
        self.assertIn("No benchmark suite has completed yet", md)
        self.assertIn("smoke-tier", md)
        self.assertIn("91.8", md)


class TestEvalRunCLI(unittest.TestCase):

    def test_plan_day(self):
        import io
        from contextlib import redirect_stdout
        import eval_run
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = eval_run.main(["plan",
                                "--tier", "day"])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("runs: 10", out)
        self.assertIn("S0", out)
        self.assertIn("VERIFIED", out)

    def test_plan_two_year_estimate(self):
        import io
        from contextlib import redirect_stdout
        import eval_run
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = eval_run.main(["plan",
                                "--tier", "two-year"])
        self.assertEqual(rc, 0)
        # 12 runs x 672 days x 97 s/day = ~217 h.
        self.assertIn("217", buf.getvalue())

    def test_run_refuses_without_allow_live(self):
        import eval_run
        rc = eval_run.main(["run", "--tier", "day",
                            "--model", "deepseek-v4.1-flash"])
        self.assertEqual(rc, 2)

    def test_baselines_blocked(self):
        import eval_run
        rc = eval_run.main(["baselines",
                            "--kind", "noop"])
        self.assertEqual(rc, 2)

    def test_replay_two_logs(self):
        import io
        from contextlib import redirect_stdout
        import eval_run
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            log1 = _synthetic_log(tmp, name="m1-a.jsonl")
            log2 = _synthetic_log(tmp, name="m1-b.jsonl")
            db = tmp / "scores.db"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = eval_run.main([
                    "replay", "--tier", "day",
                    "--scenario", "S0", "--logs", str(log1),
                    str(log2), "--record", "--db", str(db)])
            self.assertEqual(rc, 0)
            out = buf.getvalue()
            self.assertIn("median composite: 96.2", out)
            self.assertIn("survival rate: 100%", out)
            lb = Leaderboard(db)
            self.assertEqual(len(lb.list_eval()), 2)
            lb.close()


if __name__ == "__main__":
    unittest.main()


class TestRunSummary(unittest.TestCase):

    def _events(self, tmp: Path) -> Path:
        """Daemon events journal rows inside the synthetic run's
        tick window (101323-102523)."""
        rows = [
            {"tick": 101500, "type": "job_completed",
             "data": {"job_id": 1, "job_type": "MakeBed",
                      "worker_id": 5407}},
            {"tick": 101600, "type": "job_completed",
             "data": {"job_id": 2, "job_type": "MakeBarrel",
                      "worker_id": 5407}},
            {"tick": 101700, "type": "job_completed",
             "data": {"job_id": 3, "job_type": "Eat",
                      "worker_id": 5409}},
            {"tick": 101800, "type": "citizen_new",
             "data": {"unit_id": 5700, "name": "New Migrant"}},
            {"tick": 101900, "type": "unit_death",
             "data": {"unit_id": 5565}},
            {"tick": 102000, "type": "job_cancelled",
             "data": {"job_id": 9, "job_type": "MakeBed"}},
            {"tick": 102100, "type": "dwarf_distress",
             "data": {"unit_id": 5411, "name": "Zulban",
                      "kind": "wounded"}},
            # Outside the window: must not count.
            {"tick": 99999, "type": "job_completed",
             "data": {"job_id": 4, "job_type": "Eat",
                      "worker_id": 5409}},
        ]
        p = tmp / "events.jsonl"
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        return p

    def test_summary_counts(self):
        from dfagent_harness.scoring import run_summary
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            log = _synthetic_log(tmp)
            events = self._events(tmp)
            s = run_summary(log, events_path=events)
        self.assertEqual(s["model"], "deepseek-v4.1-flash")
        self.assertEqual(s["score"]["composite"], 96.2)
        self.assertEqual(s["dwarves"]["start"], 7)
        self.assertEqual(s["dwarves"]["end"], 7)
        self.assertEqual(s["dwarves"]["arrived"], 1)
        self.assertEqual(s["dwarves"]["departed"], 0)
        self.assertEqual(s["buildings"]["workshops_by_kind"],
                         {"Still": 1})
        self.assertEqual(s["buildings"]["farm_plots"], 0)
        self.assertEqual(s["jobs"]["queued_by_job"],
                         {"brew": 2, "make_barrel": 3,
                          "make_bed": 1})
        self.assertEqual(s["jobs"]["queued_units_total"], 6)
        self.assertEqual(s["jobs"]["completed_by_type"],
                         {"Eat": 1, "MakeBarrel": 1, "MakeBed": 1})
        self.assertEqual(s["jobs"]["completed_total"], 3)
        self.assertEqual(s["jobs"]["cancelled_by_type"],
                         {"MakeBed": 1})
        self.assertEqual(s["jobs"]["failed_total"], 1)
        self.assertEqual(s["jobs"]["failed_by_job"], {"brew": 1})
        self.assertEqual(s["units_killed"]["total_unit_deaths"], 1)
        self.assertEqual(s["units_killed"]["citizen_deaths"], 0)
        self.assertEqual(s["units_killed"]["other_unit_deaths"], 1)
        self.assertEqual(s["wealth"]["start"], 5418)
        self.assertEqual(s["wealth"]["end"], 5410)
        self.assertEqual(s["wealth"]["change"], -8)
        self.assertEqual(s["decisions"]["decision_ticks"], 2)
        self.assertEqual(s["decisions"]["actions_taken"], 5)
        self.assertEqual(s["decisions"]["model_failures"], 1)
        self.assertEqual(
            s["decisions"]["failure_taxonomy"]["model_failures"],
            {"transport": 1})
        self.assertEqual(s["threats"]["faced"], 0)
        self.assertEqual(s["threats"]["dwarf_distress_by_kind"],
                         {"wounded": 1})
        # Moods, trades, hostile kills have no event yet: None
        # with a reason, never 0.
        self.assertIsNone(s["moods"])
        self.assertIsNone(s["trades"])
        self.assertIn("moods", s["not_recorded"])
        self.assertIn("trades", s["not_recorded"])
        self.assertIn("hostile_kills", s["not_recorded"])

    def test_summary_without_store_or_events(self):
        from dfagent_harness.scoring import run_summary
        with tempfile.TemporaryDirectory() as d:
            log = _synthetic_log(Path(d))
            s = run_summary(log)
        self.assertEqual(s["dwarves"]["arrived"], None)
        self.assertIsNone(s["units_killed"]["total_unit_deaths"])
        self.assertEqual(s["jobs"]["completed_total"], 0)
        self.assertIn("deaths", s["not_recorded"])
        self.assertIn("arrivals_departures", s["not_recorded"])

    def test_format_run_summary(self):
        from dfagent_harness.scoring import (
            format_run_summary, run_summary)
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            log = _synthetic_log(tmp)
            s = run_summary(log, events_path=self._events(tmp))
            text = format_run_summary(s)
        self.assertIn("Run summary — deepseek-v4.1-flash", text)
        self.assertIn("Score: 96.2/100", text)
        self.assertIn("Dwarves: 7 -> 7 (1 arrived, 0 died, 0 left)",
                      text)
        self.assertIn("Buildings created: Still x1", text)
        self.assertIn("Wealth: 5418 -> 5410 (-8, -0.1%)", text)
        self.assertIn("moods (no mood event exists", text)

    def test_manifest_includes_run_summary(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            log = _synthetic_log(tmp)
            m = build_manifest(log, events_path=self._events(tmp))
        self.assertIn("run_summary", m)
        self.assertEqual(m["run_summary"]["score"]["composite"], 96.2)
        self.assertEqual(
            m["run_summary"]["buildings"]["workshops_by_kind"],
            {"Still": 1})

    def test_score_run_summary_flag(self):
        import io
        import sys
        from contextlib import redirect_stdout
        from unittest import mock
        import score_run
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            log = _synthetic_log(tmp)
            events = self._events(tmp)
            argv = ["score_run.py", str(log), "--summary",
                    "--store", str(tmp / "no-such.db"),
                    "--events", str(events)]
            buf = io.StringIO()
            with mock.patch.object(sys, "argv", argv):
                with redirect_stdout(buf):
                    rc = score_run.main()
            self.assertEqual(rc, 0)
            out = buf.getvalue()
        self.assertIn("Run summary —", out)
        self.assertIn("Buildings created: Still x1", out)
        self.assertIn("Jobs: 6 queued", out)
