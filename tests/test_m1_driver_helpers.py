"""Offline tests for the M1 driver's diary helpers (scripts/).

The diary entry for an M1 day is built from the run's own record:
the model's decisions (as plain phrases), the start/end stocks
parsed from the run's snapshots, and the fort name from the
snapshot header. These helpers are pure functions on the driver's
own data — no game, no daemon — so they are tested here by loading
scripts/m1_driver.py directly.
"""

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "m1_driver",
    Path(__file__).resolve().parent.parent / "scripts" / "m1_driver.py")
m1_driver = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(m1_driver)


class TestDiaryDecisionText(unittest.TestCase):
    def test_build_workshop(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "build_workshop",
                {"kind": "still", "pos": [95, 108, 175]}),
            "build a still at (95, 108, 175)")

    def test_queue_job(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "queue_job",
                {"job": "brew", "count": 5, "building_id": 8}),
            "queue brew x5 at building #8")

    def test_labor_toggle(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "labor_toggle",
                {"labor": "BREWER", "unit_name": "Olon",
                 "on": True}),
            "enable BREWER labor on Olon")

    def test_unmapped_action_falls_back_to_name_and_kwargs(self):
        text = m1_driver.diary_decision_text(
            "appoint_noble", {"noble": "manager"})
        self.assertIn("appoint_noble", text)
        self.assertIn("manager", text)


class TestParseSnapshotStocks(unittest.TestCase):
    def test_full_section(self):
        sections = {
            "stocks": ("Stocks: drink 39, food 32, wood 124, stone 0, "
                       "brewable plants 33."),
            "status": ("Population: 7 citizens (0 idle, 0 wounded), "
                       "25 animals, 0 hostiles, 37 active units "
                       "(reconciled)."),
        }
        self.assertEqual(m1_driver.parse_snapshot_stocks(sections),
                         {"drink": 39, "food": 32, "wood": 124,
                          "stone": 0, "population": 7})

    def test_diffed_one_liner(self):
        # The snapshot diffs unchanged sections to one-liners, but
        # the parenthetical still carries the numbers.
        sections = {
            "stocks": ("stocks: unchanged (drink 35, food 32, "
                       "wood 124, stone 0, brewable plants 35)."),
            "status": "status: unchanged (7 citizens, 0 hostiles).",
        }
        self.assertEqual(m1_driver.parse_snapshot_stocks(sections),
                         {"drink": 35, "food": 32, "wood": 124,
                          "stone": 0, "population": 7})

    def test_empty_sections(self):
        self.assertEqual(m1_driver.parse_snapshot_stocks({}), {})
        self.assertEqual(m1_driver.parse_snapshot_stocks(None), {})


class TestParseFortName(unittest.TestCase):
    def test_full_header(self):
        snap = {"text": "Erushtathtat, 125-04-02 (tick 102033) "
                        "paused: True focus: dwarfmode/Default."}
        self.assertEqual(m1_driver.parse_fort_name(snap),
                         "Erushtathtat")

    def test_diffed_header(self):
        snap = {"text": "header: unchanged (Erushtathtat, 125-04-02)."}
        self.assertEqual(m1_driver.parse_fort_name(snap),
                         "Erushtathtat")

    def test_missing(self):
        self.assertEqual(m1_driver.parse_fort_name({}), "")
        self.assertEqual(m1_driver.parse_fort_name(None), "")


if __name__ == "__main__":
    unittest.main()
