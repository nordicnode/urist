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

    def test_unmapped_action_returns_none(self):
        # A diary phrase must be a clean action phrase — the old
        # "name k=v" fallback leaked raw kwargs into the diary.
        # An unmapped action returns None and the caller skips it.
        self.assertIsNone(m1_driver.diary_decision_text(
            "appoint_noble", {"noble": "manager"}))

    def test_dig_to_completion_uses_start_coordinate(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "dig_to_completion",
                {"box": [95, 95, 175, 95, 95, 175],
                 "mode": "down-stair"}),
            "dig a down-stair at (95, 95, 175)")

    def test_manager_order_create(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "manager_order_create",
                {"job_type": "MakeBarrel", "amount": 5}),
            "order MakeBarrel x5 from the manager")

    def test_manager_order_remove(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "manager_order_remove", {"order_id": 3}),
            "remove manager order #3")

    def test_deconstruct_building(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "deconstruct_building", {"building_id": 8}),
            "deconstruct building #8")

    def test_designate_dig(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "designate_dig",
                {"box": [90, 100, 175, 94, 104, 175], "mode": "dig"}),
            "dig at (90, 100, 175)")

    def test_build_farm_plot_uses_xyz(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "build_farm_plot",
                {"x": 95, "y": 108, "z": 175, "width": 3, "height": 3}),
            "build a farm plot at (95, 108, 175)")


class TestParseSuggestion(unittest.TestCase):
    """The mock runs the snapshot's suggestion verbatim, so the
    parser must read the suggestion's PRIMARY action — the one the
    leading "Suggested action:" clause names first. The mock runs
    of 2026-11-27 drove task:brew three times on a fort with no
    still because the old unanchored regex matched the trailing
    brew-task clause of the still-build suggestion."""

    STILL = ("Suggested action: NO STILL EXISTS, so brewing is "
             "impossible until you build one. Build a still FIRST: "
             "build_workshop kind=still at 94, 107, 175 (a "
             "probe-verified free 3x3 site). If the build reports "
             "'site not free', gather the blocking plant or use the "
             "next free site. Only then run the brew task.")
    BREW = ("Suggested action: run the brew task "
            "(POST /v1/tasks/brew) — the fort is short on drink and "
            "brewing turns plants into drink.")
    BLOCKER = ("Suggested action: gather the brewing materials "
               "first — need 1 empty barrel for brew, have 0. Only "
               "then run the brew task (POST /v1/tasks/brew).")
    THREAT = ("Suggested action: query unit 123 to see what it is "
              "and where it is going — a demon is near the fort.")

    def test_still_build_suggestion_names_no_task(self):
        # The trailing "Only then run the brew task" is a
        # subordinate mention, not the action to run.
        self.assertIsNone(m1_driver.parse_suggestion(self.STILL))

    def test_brew_suggestion_runs_brew(self):
        self.assertEqual(m1_driver.parse_suggestion(self.BREW),
                         ("task", "brew"))

    def test_blocker_suggestion_names_no_task(self):
        self.assertIsNone(m1_driver.parse_suggestion(self.BLOCKER))

    def test_threat_suggestion_queries_the_unit(self):
        self.assertEqual(m1_driver.parse_suggestion(self.THREAT),
                         ("query", "/v1/unit/123"))

    def test_empty_suggestion_is_none(self):
        self.assertIsNone(m1_driver.parse_suggestion(None))
        self.assertIsNone(m1_driver.parse_suggestion(""))


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


class TestSnapshotCitizens(unittest.TestCase):
    def test_full_units_section(self):
        snap = {"sections": {"units": {"citizens": [
            {"id": 1, "name": "Udil Testdwarf"},
            {"id": 2, "name": "Deduk Stakudunib"}]}}}
        self.assertEqual(
            [c["id"] for c in m1_driver._snapshot_citizens(snap)],
            [1, 2])

    def test_diffed_units_section_is_string(self):
        # 2026-11-27 (run #15): the final snapshot diffs the units
        # section to a one-liner STRING, and _snapshot_citizens
        # called .get on it — AttributeError killed the diary
        # write after the run had completed the day. A non-dict
        # units section carries no citizens.
        snap = {"sections": {"units": "units: unchanged (7 citizens)."}}
        self.assertEqual(m1_driver._snapshot_citizens(snap), [])

    def test_missing(self):
        self.assertEqual(m1_driver._snapshot_citizens({}), [])
        self.assertEqual(m1_driver._snapshot_citizens(None), [])
        self.assertEqual(
            m1_driver._snapshot_citizens({"sections": {}}), [])


if __name__ == "__main__":
    unittest.main()
