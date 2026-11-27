"""Offline tests for the model benchmarking score (GOAL.md item 15).

The score is computed by the harness from live game state, the run
log, and the store — never self-reported by the model. These tests
use synthetic run logs and a fake Store (no game, no daemon). Live
verification (a real run's score, read against the real game) is
separate — tests/test_scoring_live.py — and is what decides whether
the score reads sensibly.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import scoring  # noqa: E402
from dfagent_harness.scoring import (  # noqa: E402
    Leaderboard, classify_death, competence_score, composite,
    growth_score, lives_score, milestone_bonus, milestones_from_log,
    needs_score, parse_run_log, repeated_failures, suggestion_job,
    suggestion_matches, survival_score, threats_score, wealth_score,
    action_job)


def _synthetic_log(tmp: Path) -> Path:
    """A one-day run log in the m1_driver format: 7 actions, 1 failed
    brew, 1 model failure, 0 idle ticks, suggestions followed 3/5."""
    recs = [
        {"kind": "run_start", "days": 1.0, "window": 150,
         "model": "deepseek-v4.1-flash", "mock": False},
        {"kind": "diary_citizens", "when": "start", "count": 7},
        {"kind": "start_tick", "start_tick": 101323,
         "end_tick": 102523, "date": "125-04-01"},
        {"kind": "snapshot", "tick_no": 1,
         "text": "Stocks: drink 38, food 32, wood 124, stone 0.",
         "suggestion": "Suggested action: build a still FIRST: "
                       "build_workshop kind=still at 94, 107, 175."},
        {"kind": "action", "tick_no": 1, "name": "build_workshop",
         "ok": True, "params": {"kind": "Still", "pos": [94, 107, 175]},
         "phrase": "build a Still at (94, 107, 175)"},
        {"kind": "action", "tick_no": 1, "name": "queue_job",
         "ok": True, "params": {"building_id": 7, "job": "make_bed",
                                "count": 1},
         "phrase": "queue make_bed x1 at the Carpenters workshop #7"},
        {"kind": "snapshot", "tick_no": 2,
         "text": "Stocks: drink 35, food 32, wood 124, stone 0.",
         "suggestion": "Suggested action: run the brew task "
                       "(POST /v1/tasks/brew)."},
        {"kind": "action", "tick_no": 2, "name": "queue_job",
         "ok": True, "params": {"building_id": 8, "job": "brew",
                                "count": 2},
         "phrase": "queue brew x2 at the Still workshop #8"},
        {"kind": "action", "tick_no": 2, "name": "queue_job",
         "ok": True, "params": {"building_id": 7, "job": "make_barrel",
                                "count": 3},
         "phrase": "queue make_barrel x3 at the Carpenters workshop #7"},
        {"kind": "snapshot", "tick_no": 3,
         "text": "Stocks: drink 35, food 32, wood 124, stone 0.",
         "suggestion": "Suggested action: queue make_barrel at the "
                       "carpenter #7 (queue_job job=make_barrel)."},
        {"kind": "action", "tick_no": 3, "name": "queue_job",
         "ok": True, "params": {"building_id": 7, "job": "make_bed",
                                "count": 2},
         "phrase": "queue make_bed x2 at the Carpenters workshop #7"},
        {"kind": "snapshot", "tick_no": 4,
         "text": "Stocks: drink 35, food 32, wood 124, stone 0.",
         "suggestion": "Suggested action: queue make_barrel at the "
                       "carpenter #7 (queue_job job=make_barrel)."},
        {"kind": "action", "tick_no": 4, "name": "queue_job",
         "ok": True, "params": {"building_id": 7, "job": "make_barrel",
                                "count": 1},
         "phrase": "queue make_barrel x1 at the Carpenters workshop #7"},
        {"kind": "action", "tick_no": 4, "name": "queue_job",
         "ok": False, "params": {"building_id": 8, "job": "brew",
                                 "count": 1},
         "phrase": "queue brew x1 at building #8",
         "reason": "material shortage"},
        {"kind": "model_failure", "tick_no": 5,
         "error": "IncompleteRead(0 bytes read)", "consecutive": 1},
        {"kind": "snapshot", "tick_no": 6,
         "text": "Stocks: drink 34, food 32, wood 124, stone 0.",
         "suggestion": "Suggested action: queue make_barrel at the "
                       "carpenter #7 (queue_job job=make_barrel)."},
        {"kind": "diary_citizens", "when": "end", "count": 7},
        {"kind": "wealth", "when": "start", "fortress_value": 5418,
         "created_value": 5, "item_count": 183},
        {"kind": "wealth", "when": "end", "fortress_value": 5410,
         "created_value": 5, "item_count": 183},
        {"kind": "run_end", "reason": "day complete", "tick": 102647,
         "end_tick": 102523, "actions_taken": 7, "idle_ticks": 0},
    ]
    p = tmp / "m1-test.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return p


class FakeStore:
    """Minimal Store stand-in: deaths + unit history."""

    def __init__(self, deaths=None, history=None):
        self._deaths = deaths or []
        self._history = history or {}

    def deaths(self):
        return list(self._deaths)

    def unit_ids(self):
        return list(self._history.keys())

    def unit_history(self, unit_id):
        return list(self._history.get(unit_id, []))


class TestDimensions(unittest.TestCase):
    def test_survival_full_day(self):
        self.assertEqual(survival_score(1.0, 1.0), 100.0)

    def test_survival_early_death(self):
        self.assertEqual(survival_score(0.5, 1.0), 50.0)

    def test_survival_zero_planned(self):
        self.assertEqual(survival_score(1.0, 0.0), 100.0)

    def test_lives_no_deaths(self):
        self.assertEqual(lives_score([]), 100.0)

    def test_lives_preventable_heaviest(self):
        deaths = [{"kind": "preventable"}, {"kind": "combat"},
                  {"kind": "mood"}, {"kind": "other"}]
        self.assertEqual(lives_score(deaths), 100 - 40 - 20 - 15 - 10)

    def test_lives_floors_at_zero(self):
        deaths = [{"kind": "preventable"}] * 3
        self.assertEqual(lives_score(deaths), 0.0)

    def test_classify_death(self):
        self.assertEqual(classify_death("died of thirst"), "preventable")
        self.assertEqual(classify_death("starved to death"),
                         "preventable")
        self.assertEqual(classify_death("slain by a goblin"), "combat")
        self.assertEqual(classify_death("died of its wounds"), "combat")
        self.assertEqual(classify_death("went insane"), "mood")
        self.assertEqual(classify_death("fell from a height"), "other")
        # Environmental deaths are not hostile kills.
        self.assertEqual(classify_death("drowned"), "other")
        self.assertEqual(classify_death("died in magma"), "other")

    def test_wealth_neutral_without_readings(self):
        self.assertEqual(wealth_score(None, 5410), 50.0)
        self.assertEqual(wealth_score(5418, None), 50.0)

    def test_wealth_no_change_is_fifty(self):
        self.assertEqual(wealth_score(5418, 5418), 50.0)

    def test_wealth_growth(self):
        self.assertEqual(wealth_score(5000, 7500), 100.0)
        self.assertAlmostEqual(wealth_score(5418, 5410), 49.85, places=1)

    def test_wealth_collapse_is_zero(self):
        self.assertEqual(wealth_score(5000, 1000), 0.0)

    def test_needs_clean(self):
        self.assertEqual(needs_score(False, 0.0), 100.0)

    def test_needs_zero_stock(self):
        self.assertEqual(needs_score(True, 0.0), 50.0)

    def test_needs_dangerous_time(self):
        self.assertEqual(needs_score(False, 0.5), 75.0)
        self.assertEqual(needs_score(True, 1.0), 0.0)

    def test_growth_base(self):
        self.assertEqual(growth_score(7, 7, 0, 0), 50.0)

    def test_growth_workshop_and_bed(self):
        self.assertEqual(growth_score(7, 7, 1, 0), 60.0)
        self.assertEqual(growth_score(7, 8, 1, 1), 70.0)

    def test_growth_caps(self):
        # 50 base + 20 workshops + 15 beds = 85 without a population
        # gain; a population gain of 3 or more takes it to 100.
        self.assertEqual(growth_score(7, 7, 10, 10), 85.0)
        self.assertEqual(growth_score(7, 10, 10, 10), 100.0)

    def test_competence_clean(self):
        self.assertEqual(
            competence_score(0, 0, 0, 0, 0, 0), 100.0)

    def test_competence_penalties(self):
        # 1 failed action, 1 model failure, 3/5 suggestions followed.
        self.assertEqual(
            competence_score(0, 1, 0, 1, 3, 5), 88.0)

    def test_competence_idle_and_repeats(self):
        self.assertEqual(
            competence_score(2, 0, 1, 0, 0, 0), 100 - 20 - 10)

    def test_competence_no_suggestions_no_penalty(self):
        self.assertEqual(
            competence_score(0, 0, 0, 0, 0, 0), 100.0)

    def test_threats(self):
        self.assertEqual(threats_score(0), 100.0)
        self.assertEqual(threats_score(2), 60.0)
        self.assertEqual(threats_score(10), 0.0)

    def test_milestone_bonus(self):
        self.assertEqual(milestone_bonus(set()), 0.0)
        self.assertEqual(milestone_bonus({"first brew"}), 2.0)
        self.assertEqual(
            milestone_bonus({"a", "b", "c", "d", "e", "f"}), 10.0)

    def test_composite_weights(self):
        dims = {"survival": 100.0, "lives": 100.0, "wealth": 50.0,
                "needs": 100.0, "growth": 60.0, "competence": 88.0,
                "threats": 100.0}
        self.assertAlmostEqual(composite(dims, set()), 91.8, places=1)
        self.assertAlmostEqual(
            composite(dims, {"first brew"}), 93.8, places=1)


class TestSuggestionMatching(unittest.TestCase):
    def test_suggestion_job(self):
        self.assertEqual(
            suggestion_job("Suggested action: build a still FIRST: "
                           "build_workshop kind=still at 94, 107."),
            "build_still")
        self.assertEqual(
            suggestion_job("Suggested action: run the brew task "
                           "(POST /v1/tasks/brew)."),
            "brew")
        self.assertEqual(
            suggestion_job("Suggested action: queue make_barrel at "
                           "the carpenter #7."),
            "make_barrel")
        self.assertIsNone(suggestion_job("Suggested action: watch it."))

    def test_action_job(self):
        self.assertEqual(
            action_job({"name": "build_workshop",
                        "params": {"kind": "Still"}}),
            "build_still")
        self.assertEqual(
            action_job({"name": "queue_job",
                        "params": {"job": "make_barrel"}}),
            "make_barrel")
        self.assertEqual(
            action_job({"name": "run_task",
                        "params": {"name": "brew"}}),
            "brew")
        self.assertIsNone(action_job({"name": "query", "params": {}}))

    def test_suggestion_matches(self):
        snaps = [
            {"tick_no": 1, "suggestion": "build a still FIRST: "
             "build_workshop kind=still"},
            {"tick_no": 2, "suggestion": "run the brew task"},
            {"tick_no": 3, "suggestion": "queue make_barrel"},
            {"tick_no": 4, "suggestion": "queue make_barrel"},
            {"tick_no": 5, "suggestion": "watch it"},
        ]
        actions = [
            {"tick_no": 1, "name": "build_workshop",
             "params": {"kind": "Still"}},
            {"tick_no": 2, "name": "queue_job",
             "params": {"job": "brew"}},
            {"tick_no": 3, "name": "queue_job",
             "params": {"job": "make_bed"}},
            {"tick_no": 4, "name": "queue_job",
             "params": {"job": "make_barrel"}},
        ]
        # Tick 5 has no extractable job: skipped, not penalised.
        self.assertEqual(suggestion_matches(snaps, actions), (3, 4))

    def test_suggestion_matches_excludes_final_snapshot(self):
        # The run's final snapshot (the driver ends the run on it
        # before calling the model) is never acted on, so it must
        # not count as an ignored suggestion.
        snaps = [
            {"tick_no": 1, "suggestion": "queue make_barrel"},
            {"tick_no": 2, "suggestion": "queue make_barrel"},
        ]
        actions = [{"tick_no": 1, "name": "queue_job",
                    "params": {"job": "make_barrel"}}]
        self.assertEqual(suggestion_matches(snaps, actions), (1, 2))
        self.assertEqual(
            suggestion_matches(snaps, actions, exclude_tick_no=2),
            (1, 1))


class TestRepeatedFailures(unittest.TestCase):
    def test_single_failure_not_repeated(self):
        actions = [{"name": "queue_job", "ok": False,
                    "params": {"job": "brew"}}]
        self.assertEqual(repeated_failures(actions), 0)

    def test_same_action_failing_twice(self):
        actions = [{"name": "queue_job", "ok": False,
                    "params": {"job": "brew"}},
                   {"name": "queue_job", "ok": False,
                    "params": {"job": "brew"}},
                   {"name": "queue_job", "ok": False,
                    "params": {"job": "make_bed"}}]
        self.assertEqual(repeated_failures(actions), 1)


class TestParseRunLog(unittest.TestCase):
    def test_parse_synthetic_log(self):
        with tempfile.TemporaryDirectory() as d:
            p = _synthetic_log(Path(d))
            run = parse_run_log(p)
            self.assertEqual(run["model"], "deepseek-v4.1-flash")
            self.assertEqual(run["days_planned"], 1.0)
            self.assertEqual(run["start_tick"], 101323)
            self.assertEqual(run["end_tick"], 102523)
            self.assertEqual(len(run["actions"]), 7)
            self.assertEqual(run["model_failures"], 1)
            self.assertEqual(run["idle_ticks"], 0)
            self.assertEqual(run["citizens_start"], 7)
            self.assertEqual(run["citizens_end"], 7)
            self.assertEqual(run["wealth_start"], 5418)
            self.assertEqual(run["wealth_end"], 5410)
            self.assertEqual(run["run_end"]["reason"], "day complete")

    def test_milestones_none_achieved(self):
        # Drink fell (38 -> 34), beds stayed at 0: no milestone.
        with tempfile.TemporaryDirectory() as d:
            run = parse_run_log(_synthetic_log(Path(d)))
            self.assertEqual(milestones_from_log(run), set())

    def test_milestones_brew_on_drink_rise(self):
        with tempfile.TemporaryDirectory() as d:
            p = _synthetic_log(Path(d))
            recs = [json.loads(x) for x in p.read_text().splitlines()]
            # Last snapshot: drink rose to 43 (a brew completed).
            for r in reversed(recs):
                if r.get("kind") == "snapshot":
                    r["text"] = ("Stocks: drink 43, food 32, wood 124, "
                                 "stone 0.")
                    break
            p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
            run = parse_run_log(p)
            self.assertEqual(milestones_from_log(run), {"first brew"})


class TestComputeScore(unittest.TestCase):
    def test_synthetic_run(self):
        with tempfile.TemporaryDirectory() as d:
            p = _synthetic_log(Path(d))
            store = FakeStore()
            score = scoring.compute_score(p, store=store)
            self.assertEqual(score.model, "deepseek-v4.1-flash")
            self.assertEqual(score.dimensions["survival"], 100.0)
            self.assertEqual(score.dimensions["lives"], 100.0)
            self.assertAlmostEqual(score.dimensions["wealth"], 49.85,
                                   places=1)
            self.assertEqual(score.dimensions["needs"], 100.0)
            self.assertEqual(score.dimensions["growth"], 60.0)
            # 1 failed action, 1 model failure, 3/4 suggestions
            # followed (the tick-6 snapshot is the run's final one:
            # the driver ends the run on it before the model acts,
            # so it is excluded from suggestion matching).
            self.assertEqual(score.dimensions["competence"], 88.75)
            self.assertEqual(score.dimensions["threats"], 100.0)
            self.assertEqual(score.milestones, set())
            self.assertAlmostEqual(score.composite, 91.86, places=2)
            self.assertEqual(score.evidence["wealth_start"], 5418)
            self.assertEqual(score.evidence["wealth_end"], 5410)
            self.assertEqual(score.evidence["drink_start"], 38)
            self.assertEqual(score.evidence["drink_end"], 34)
            self.assertEqual(score.evidence["suggestions_matched"], 3)
            self.assertEqual(score.evidence["suggestions_total"], 4)

    def test_score_with_death(self):
        with tempfile.TemporaryDirectory() as d:
            p = _synthetic_log(Path(d))
            store = FakeStore(deaths=[{
                "unit_id": 5407, "tick": 102000,
                "cause": "died of thirst", "history_ref": ""}])
            score = scoring.compute_score(p, store=store)
            self.assertEqual(score.dimensions["lives"], 60.0)
            self.assertEqual(score.dimensions["threats"], 100.0)
            self.assertEqual(score.evidence["deaths"][0]["kind"],
                             "preventable")

    def test_score_without_store(self):
        with tempfile.TemporaryDirectory() as d:
            p = _synthetic_log(Path(d))
            score = scoring.compute_score(p, store=None)
            self.assertEqual(score.dimensions["lives"], 100.0)
            self.assertEqual(score.dimensions["needs"], 100.0)


class TestLeaderboard(unittest.TestCase):
    def test_record_and_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = _synthetic_log(Path(d))
            db = Path(d) / "scores.db"
            lb = Leaderboard(db)
            score = scoring.compute_score(p, store=FakeStore())
            lb.record(score)
            rows = lb.list_scores()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["model"], "deepseek-v4.1-flash")
            self.assertAlmostEqual(rows[0]["composite"], 91.86,
                                   places=2)
            # Re-recording the same log replaces the row, not a dup.
            lb.record(score)
            self.assertEqual(len(lb.list_scores()), 1)
            lb.close()

    def test_list_by_model(self):
        with tempfile.TemporaryDirectory() as d:
            p = _synthetic_log(Path(d))
            db = Path(d) / "scores.db"
            lb = Leaderboard(db)
            score = scoring.compute_score(p, store=FakeStore())
            lb.record(score)
            self.assertEqual(len(lb.list_scores(model="other")), 0)
            self.assertEqual(
                len(lb.list_scores(model="deepseek-v4.1-flash")), 1)
            lb.close()


class TestWealthSectionRegistered(unittest.TestCase):
    def test_wealth_section(self):
        from dfagent_harness.observe import (
            FAST_SECTIONS, SECTIONS, _LUA_PROVIDES, _SECTION_LUA)
        self.assertIn("wealth", SECTIONS)
        self.assertEqual(_SECTION_LUA["wealth"], "wealth.lua")
        self.assertEqual(_LUA_PROVIDES["wealth.lua"], ("wealth",))
        # On-demand only: not in the per-tick fast sections.
        self.assertNotIn("wealth", FAST_SECTIONS)
        lua = (Path(__file__).resolve().parent.parent / "src"
               / "dfagent_harness" / "lua" / "wealth.lua")
        self.assertTrue(lua.exists())


if __name__ == "__main__":
    unittest.main()
