"""Unit tests for the phase-4 planner (decide rules, journal, goals).

Decisions are tested against fixture states built from the real
phase-1 observe dump (tests/fixtures/observe-athelunol.json) with
targeted mutations — no game needed.
"""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.planner import (  # noqa: E402
    Decision,
    Journal,
    Planner,
    decide,
    state_summary,
)
from dfagent_harness.daemon import evaluate_goal  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "observe-athelunol.json"


def load_state() -> dict:
    return json.loads(FIXTURE.read_text())


def _set_stock(state: dict, **kw: int) -> None:
    for key, value in kw.items():
        state["stocks"][key] = value


def _add_building(state: dict, type_: str, subtype=None, bid=99):
    entry = {"id": bid, "type": type_, "type_id": 0,
             "x1": 88, "y1": 85, "x2": 90, "y2": 87, "z": 42,
             "center": [89, 86, 42], "construction_stage": 3,
             "jobs": 0, "contained_items": 0}
    if subtype is not None:
        entry["subtype"] = subtype
    state["buildings"]["list"].append(entry)
    summary = state["buildings"]["summary"]
    for e in summary:
        if e["type"] == type_:
            e["count"] += 1
            break
    else:
        summary.append({"type": type_, "count": 1})
    state["buildings"]["count"] = len(state["buildings"]["list"])


def _add_hostile(state: dict, pos, race="BIRD_EAGLE", uid=9001):
    state["units"]["hostiles"] = [
        {"id": uid, "name": "eagle", "race": race, "pos": list(pos)}]
    state["units"]["hostile_count"] = 1


class DecideDrinkTests(unittest.TestCase):
    def test_drink_critical_no_still_builds_still_first(self):
        state = load_state()
        _set_stock(state, drink_units=2)
        decisions = decide(state)
        self.assertTrue(decisions)
        first = decisions[0]
        self.assertEqual(first.domain, "needs")
        self.assertEqual(first.action, "build_workshop")
        self.assertEqual(first.kwargs["kind"], "still")

    def test_drink_critical_still_and_brewable_brews(self):
        state = load_state()
        _set_stock(state, drink_units=2)
        _add_building(state, "Workshop", "Still", bid=10)
        # Fixture by_material already has PLANT:GRASS_WHEAT_CAVE:DRINK.
        decisions = decide(state)
        brews = [d for d in decisions if d.goal_key == "drink:brew"]
        self.assertEqual(len(brews), 1)
        self.assertEqual(brews[0].action, "queue_job")
        self.assertEqual(brews[0].kwargs["job"], "brew")
        self.assertEqual(brews[0].kwargs["building_id"], 10)

    def test_drink_critical_no_brewable_gathers(self):
        state = load_state()
        _set_stock(state, drink_units=0)
        _add_building(state, "Workshop", "Still", bid=10)
        state["stocks"]["by_material"] = [
            e for e in state["stocks"]["by_material"]
            if not (str(e.get("material") or "").startswith("PLANT:")
                    and str(e.get("material") or "").endswith(":DRINK"))]
        decisions = decide(state)
        gathers = [d for d in decisions if d.goal_key == "drink:gather"]
        self.assertEqual(len(gathers), 1)
        self.assertEqual(gathers[0].action, "designate_gather")

    def test_drink_healthy_no_drink_decision(self):
        state = load_state()  # drink 60, 7 citizens
        decisions = decide(state)
        self.assertFalse([d for d in decisions
                          if d.domain == "needs"
                          and "drink" in d.decision.lower()])


class DecideFoodTests(unittest.TestCase):
    def test_food_critical_kitchen_cooks(self):
        state = load_state()
        _set_stock(state, food_units=3)
        _add_building(state, "Workshop", "Kitchen", bid=11)
        decisions = decide(state)
        cooks = [d for d in decisions if d.goal_key == "food:cook"]
        self.assertEqual(len(cooks), 1)
        self.assertEqual(cooks[0].kwargs["job"], "cook")

    def test_food_critical_no_kitchen_gathers(self):
        state = load_state()
        _set_stock(state, food_units=3)
        decisions = decide(state)
        gathers = [d for d in decisions if d.goal_key == "food:gather"]
        self.assertEqual(len(gathers), 1)


class DecideThreatTests(unittest.TestCase):
    def test_hostile_adjacent_holds_paused(self):
        state = load_state()
        citizen = state["units"]["citizens"][0]
        pos = list(citizen["pos"])
        _add_hostile(state, [pos[0] + 2, pos[1], pos[2]])
        decisions = decide(state)
        holds = [d for d in decisions if d.goal_key == "threat:hold"]
        self.assertEqual(len(holds), 1)
        self.assertEqual(holds[0].priority, 1)
        self.assertEqual(holds[0].action, "pause")
        self.assertTrue(holds[0].kwargs["paused"])

    def test_hostile_near_watches(self):
        state = load_state()
        citizen = state["units"]["citizens"][0]
        pos = list(citizen["pos"])
        _add_hostile(state, [pos[0] + 12, pos[1], pos[2]])
        decisions = decide(state)
        self.assertTrue([d for d in decisions
                         if d.goal_key == "threat:watch"])
        self.assertFalse([d for d in decisions
                          if d.goal_key == "threat:hold"])

    def test_hostile_far_no_threat_decision(self):
        state = load_state()
        citizen = state["units"]["citizens"][0]
        pos = list(citizen["pos"])
        _add_hostile(state, [pos[0] + 40, pos[1], pos[2]])
        decisions = decide(state)
        self.assertFalse([d for d in decisions if d.domain == "threat"])


class DecideNoblesTests(unittest.TestCase):
    def test_no_manager_appoints_leader(self):
        state = load_state()
        decisions = decide(state, manager=False)
        appts = [d for d in decisions if d.goal_key == "nobles:manager"]
        self.assertEqual(len(appts), 1)
        self.assertEqual(appts[0].action, "ui:appoint_noble")
        self.assertEqual(appts[0].kwargs["position"], "manager")
        self.assertEqual(appts[0].kwargs["unit_id"],
                         state["units"]["citizens"][0]["id"])

    def test_manager_unknown_no_noble_decision(self):
        state = load_state()
        decisions = decide(state, manager=None)
        self.assertFalse([d for d in decisions if d.domain == "nobles"])

    def test_manager_present_no_noble_decision(self):
        state = load_state()
        decisions = decide(state, manager=True)
        self.assertFalse([d for d in decisions if d.domain == "nobles"])


class DecideProductionTests(unittest.TestCase):
    def test_no_carpenter_builds_one_when_wood(self):
        state = load_state()
        decisions = decide(state)
        builds = [d for d in decisions
                  if d.goal_key == "production:carpenter"]
        self.assertEqual(len(builds), 1)
        self.assertEqual(builds[0].kwargs["kind"], "carpenter")

    def test_beds_made_when_carpenter_and_wood(self):
        state = load_state()
        _add_building(state, "Workshop", "Carpenters", bid=12)
        decisions = decide(state)
        makes = [d for d in decisions
                 if d.goal_key == "production:make_bed"]
        self.assertEqual(len(makes), 1)
        self.assertEqual(makes[0].kwargs["job"], "make_bed")

    def test_bed_placed_when_bed_item_in_stock(self):
        state = load_state()
        _add_building(state, "Workshop", "Carpenters", bid=12)
        state["items"]["by_type"].append(
            {"type": "BED", "units": 2, "stacks": 2})
        decisions = decide(state)
        places = [d for d in decisions if d.goal_key == "production:bed"]
        self.assertEqual(len(places), 1)
        self.assertEqual(places[0].action, "build_furniture")

    def test_stone_zero_digs_down(self):
        state = load_state()  # stone 0 in the fixture
        decisions = decide(state)
        digs = [d for d in decisions if d.goal_key == "expansion:dig"]
        self.assertEqual(len(digs), 1)
        self.assertEqual(digs[0].kwargs["mode"], "down-stair")

    def test_priority_order_survival_first(self):
        state = load_state()
        _set_stock(state, drink_units=1, food_units=2)
        decisions = decide(state)
        self.assertLess(decisions[0].priority, 4)
        self.assertIn(decisions[0].domain, ("needs", "threat"))


class StateSummaryTests(unittest.TestCase):
    def test_summary_counts(self):
        s = state_summary(load_state())
        self.assertEqual(s["citizens"], 7)
        self.assertEqual(s["drink"], 60)
        self.assertEqual(s["food"], 45)
        self.assertEqual(s["wood"], 3)
        self.assertEqual(s["stone"], 0)


class JournalTests(unittest.TestCase):
    def test_log_and_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(Path(tmp) / "j.db")
            d = Decision(1, "needs", "brew drink now", "drink 2u",
                         "queue_job", {"building_id": 10}, "drink:brew")
            journal.log_decision(d, tick=100, year=306, ok=True,
                                 result="queued", took_ms=5)
            rows = journal.recent_decisions()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["decision"], "brew drink now")
            self.assertEqual(rows[0]["ok"], 1)
            self.assertEqual(journal.decision_counts(), {"needs": 1})
            journal.close()

    def test_goals_crud(self):
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(Path(tmp) / "j.db")
            gid = journal.create_goal("drink", "drink >= 40", "brew", 6)
            self.assertEqual(len(journal.list_goals()), 1)
            self.assertTrue(journal.mark_goal_done(gid))
            self.assertEqual(journal.get_goal(gid)["done"], 1)
            self.assertTrue(journal.delete_goal(gid))
            self.assertEqual(journal.list_goals(), [])
            journal.close()


class EvaluateGoalTests(unittest.TestCase):
    def test_comparisons(self):
        state = load_state()
        self.assertTrue(evaluate_goal("drink >= 40", state))
        self.assertFalse(evaluate_goal("drink >= 100", state))
        self.assertTrue(evaluate_goal("food < 50", state))
        self.assertTrue(evaluate_goal("population == 7", state))
        self.assertFalse(evaluate_goal("threats > 0", state))
        self.assertIsNone(evaluate_goal("drink ~= 40", state))
        self.assertIsNone(evaluate_goal("DROP TABLE goals", state))


class PlannerTickTests(unittest.TestCase):
    def test_tick_executes_top_decisions_and_backs_off(self):
        state = load_state()
        _set_stock(state, drink_units=2)
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(Path(tmp) / "j.db")
            planner = Planner(client=object(), journal=journal,
                              backoff_s=60.0, max_actions_per_tick=1)
            ok_result = mock.Mock()
            ok_result.ok = True
            ok_result.reason = "built"
            ok_result.error_kind = None
            fail_result = mock.Mock()
            fail_result.ok = False
            fail_result.reason = "no accessible material"
            fail_result.error_kind = "precondition"
            with mock.patch(
                    "dfagent_harness.planner.act",
                    side_effect=[fail_result, ok_result]) as mock_act:
                records = planner.tick(state, manager=True)
                self.assertTrue(records)
                self.assertEqual(records[0]["status"], "failed")
                # Second tick: the failed goal is filtered out of the
                # decisions entirely (blocked), and the suppression it
                # caused lifts — the carpenter runs instead.
                records2 = planner.tick(state, manager=True)
                self.assertFalse(any(
                    r["goal_key"] == "drink:still" for r in records2))
                self.assertEqual(mock_act.call_count, 2)
                self.assertEqual(
                    mock_act.call_args[0][1], "build_workshop")
            journal.close()

    def test_tick_logs_log_actions_without_calling_act(self):
        state = load_state()
        citizen = state["units"]["citizens"][0]
        pos = list(citizen["pos"])
        _add_hostile(state, [pos[0] + 12, pos[1], pos[2]])
        with tempfile.TemporaryDirectory() as tmp:
            journal = Journal(Path(tmp) / "j.db")
            planner = Planner(client=object(), journal=journal,
                              max_actions_per_tick=1)
            with mock.patch(
                    "dfagent_harness.planner.act") as mock_act:
                mock_act.return_value.ok = True
                mock_act.return_value.reason = "built"
                mock_act.return_value.error_kind = None
                records = planner.tick(state, manager=True)
                watch = [r for r in records
                         if r["goal_key"] == "threat:watch"]
                self.assertEqual(len(watch), 1)
                self.assertEqual(watch[0]["status"], "logged")
                # The one executed action is the carpenter build, not
                # the watch — log actions never reach act().
                self.assertEqual(mock_act.call_count, 1)
                self.assertEqual(
                    mock_act.call_args[0][1], "build_workshop")
            journal.close()


if __name__ == "__main__":
    unittest.main()
