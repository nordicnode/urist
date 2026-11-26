"""Unit tests for the acceptance criteria (docs/ACCEPTANCE.md).

The criteria are pure functions over plain data (see
``dfagent_harness.acceptance``); these tests pin their behaviour
against the real Athelunol numbers from the 2026-11-26 shakedown
window, so a future change to a threshold or a rule shows up here
first.
"""

import sys
import unittest
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

# The 5 Athelunol deaths, as recorded in events.jsonl (2026-11-26).
ATHELUNOL_DEATHS = [
    {"citizen": True, "name": "Kogan Mûthkatost",
     "cause": "dehydrated", "tick": 224421},
    {"citizen": True, "name": "Feb Rilbetfath",
     "cause": "dehydrated", "tick": 226373},
    {"citizen": True, "name": "Datan Erushninur",
     "cause": "dehydrated", "tick": 224971},
    {"citizen": True, "name": "Nil Idòeton",
     "cause": "dehydrated", "tick": 230445},
    {"citizen": True, "name": "Deler Stûeegilstinthäd",
     "cause": None, "tick": None},
]


class SurvivalTests(unittest.TestCase):
    def test_athelunol_window_fails_on_deaths_and_duration(self):
        r = check_survival(168875, 231622, ATHELUNOL_DEATHS)
        self.assertEqual(r["result"], "fail")
        self.assertIn("0.16 game-years", r["evidence"])
        self.assertIn("4 thirst/starvation", r["evidence"])
        self.assertIn("Deler", r["evidence"])  # unrecorded cause is named

    def test_two_clean_years_pass(self):
        r = check_survival(0, 806_400, [])
        self.assertEqual(r["result"], "pass")

    def test_clean_short_run_fails_on_duration(self):
        r = check_survival(0, 403_200, [])
        self.assertEqual(r["result"], "fail")
        self.assertIn("1.00 game-years", r["evidence"])

    def test_unknown_cause_alone_does_not_fail(self):
        r = check_survival(0, 806_400,
                           [{"citizen": True, "name": "X",
                             "cause": None, "tick": 100}])
        self.assertEqual(r["result"], "pass")
        self.assertIn("unrecorded cause", r["evidence"])

    def test_non_citizen_deaths_do_not_count(self):
        r = check_survival(0, 806_400,
                           [{"citizen": False, "name": "eagle",
                             "cause": "dehydrated", "tick": 100}])
        self.assertEqual(r["result"], "pass")


class StocksTests(unittest.TestCase):
    def test_athelunol_window_fails(self):
        snaps = [{"tick": 168875, "drink": 2, "food": 23},
                 {"tick": 229208, "drink": 0, "food": 0}]
        r = check_stocks(snaps)
        self.assertEqual(r["result"], "fail")
        self.assertIn("first breach", r["evidence"])

    def test_healthy_stocks_pass(self):
        snaps = [{"tick": 1, "drink": 60, "food": 45},
                 {"tick": 2, "drink": 55, "food": 40}]
        self.assertEqual(check_stocks(snaps)["result"], "pass")

    def test_no_snapshots_is_untested(self):
        self.assertEqual(check_stocks([])["result"], "untested")


class ThreatTests(unittest.TestCase):
    def test_no_spawn_is_untested(self):
        r = check_threat_response(None, None)
        self.assertEqual(r["result"], "untested")

    def test_response_within_limit_passes(self):
        r = check_threat_response(1000, 1500, max_ticks=1100)
        self.assertEqual(r["result"], "pass")

    def test_late_response_fails(self):
        r = check_threat_response(1000, 3000, max_ticks=1100)
        self.assertEqual(r["result"], "fail")

    def test_spawn_with_no_decision_fails(self):
        r = check_threat_response(1000, None)
        self.assertEqual(r["result"], "fail")


class ExpansionTests(unittest.TestCase):
    def test_athelunol_window_fails(self):
        # Buildings grew 0 -> 6, but citizens fell 15 -> 10 and
        # nothing was produced.
        r = check_expansion({"buildings": 0, "citizens": 15,
                             "produced": 0},
                            {"buildings": 6, "citizens": 10,
                             "produced": 0})
        self.assertEqual(r["result"], "fail")

    def test_growth_passes(self):
        r = check_expansion({"buildings": 6, "citizens": 10,
                             "produced": 0},
                            {"buildings": 8, "citizens": 12,
                             "produced": 20})
        self.assertEqual(r["result"], "pass")


class NeglectTests(unittest.TestCase):
    def test_athelunol_deaths_fail_when_daemon_continuous(self):
        r = check_no_neglect_deaths(ATHELUNOL_DEATHS, True)
        self.assertEqual(r["result"], "fail")
        self.assertIn("4 preventable", r["evidence"])

    def test_no_continuous_daemon_is_inconclusive(self):
        # The shakedown reality: the daemon was stalled/crashing, so
        # the deaths cannot be attributed to the planner either way.
        r = check_no_neglect_deaths(ATHELUNOL_DEATHS, False)
        self.assertEqual(r["result"], "inconclusive")

    def test_no_deaths_pass(self):
        r = check_no_neglect_deaths([], True)
        self.assertEqual(r["result"], "pass")


class EvaluateAllTests(unittest.TestCase):
    def test_orders_a_to_e(self):
        results = {
            "e": {"criterion": "e", "result": "pass", "evidence": ""},
            "a": {"criterion": "a", "result": "fail", "evidence": ""},
            "c": {"criterion": "c", "result": "untested", "evidence": ""},
        }
        ordered = evaluate_all(results)
        self.assertEqual([r["criterion"] for r in ordered],
                         ["a", "c", "e"])


if __name__ == "__main__":
    unittest.main()
