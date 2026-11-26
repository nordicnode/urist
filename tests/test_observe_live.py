"""Live integration test for the observation layer.

Runs against a real Dwarf Fortress 0.47.05 game on 127.0.0.1:5000 and
skips itself (does not fail) when no game is reachable — the suite must
stay green on machines without DF running. Set DFH_TEST_LIVE=0 to force
the skip even when a game is up.

Run from the repo root:

    .venv/bin/python -m unittest discover -s tests -v
"""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness.observe import collect, render_text  # noqa: E402
from dfhack_rpc import DFHackClient, DFHackError  # noqa: E402

HOST = os.environ.get("DFH_TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("DFH_TEST_PORT", "5000"))
LIVE_DISABLED = os.environ.get("DFH_TEST_LIVE", "1") == "0"


def _game_is_up():
    if LIVE_DISABLED:
        return False
    try:
        with DFHackClient(HOST, PORT, timeout=3.0) as client:
            client.get_version()
    except DFHackError:
        return False
    return True


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestLiveObserve(unittest.TestCase):
    """Verified live against the Athelunol fort (region1)."""

    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=30.0)
        cls.client.connect()
        cls.state = collect(cls.client)

    @classmethod
    def tearDownClass(cls):
        cls.client.quit()

    def test_no_section_errors(self):
        self.assertEqual(self.state["errors"], [])

    def test_versions(self):
        ver = self.state["meta"]["version"]
        self.assertEqual(ver["dwarf_fortress_version"], "0.47.05")
        self.assertTrue(ver["dfhack_version"].startswith("0.47.05-r"))

    def test_fort_and_population(self):
        st = self.state["status"]
        self.assertEqual(st["fort_name"], "Athelunol")
        self.assertEqual(st["year"], 306)
        # 7 founders at embark; migrants arrive over time (15 by
        # 2026-11-26 after the phase-3 live runs), so only the floor
        # is pinned — the exact count is live state, not a constant.
        self.assertGreaterEqual(st["population"]["citizens"], 7)
        self.assertGreaterEqual(st["population"]["total_active_units"],
                                st["population"]["citizens"])

    def test_units_match_status(self):
        units = self.state["units"]
        self.assertEqual(
            units["citizen_count"],
            self.state["status"]["population"]["citizens"])
        for c in units["citizens"]:
            self.assertTrue(c["name"])
            self.assertEqual(len(c["pos"]), 3)

    def test_stocks_are_plausible(self):
        stocks = self.state["stocks"]
        # Drink may legitimately be 0 — the fort drank its last units
        # during the unpaused build windows, and that is exactly the
        # condition the phase-4 planner must fix. The observation
        # layer's job is to report the true number, not a healthy one.
        self.assertGreaterEqual(stocks["drink_units"], 0)
        self.assertGreater(stocks["food_units"], 0)
        self.assertGreater(stocks["barrels"], 0)
        self.assertGreaterEqual(stocks["wood_units"], 0)

    def test_text_rendering_covers_the_fort(self):
        text = render_text(self.state)
        self.assertIn("Athelunol", text)
        for c in self.state["units"]["citizens"]:
            self.assertIn(c["name"], text)

    def test_state_is_json_serializable(self):
        json.dumps(self.state)  # must not raise

    def test_designations_section(self):
        # Slow (~4 s full block scan); only run when requested.
        state = collect(self.client, sections=("designations",))
        self.assertEqual(state["errors"], [])
        des = state["designations"]
        self.assertIn("dig_total", des)
        self.assertIn("scan_seconds", des)


if __name__ == "__main__":
    unittest.main()
