"""Tests for failure diagnosis (GOAL.md step 5, layer 4).

Every failed action carries its cause AND the fix — the corrective
catalog action, what it needs, and the current stock of what it
needs — so the agent never repeats a failed action with the same
approach.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness import actions, diagnose  # noqa: E402
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


STATE = {"stocks": {"drink_units": 9, "food_units": 25,
                    "wood_units": 211, "stone_units": 0}}


class TestDiagnoseOffline(unittest.TestCase):
    def test_brew_no_barrels_names_the_fix(self):
        fix = diagnose.diagnose_failure(
            "brew", "no empty barrels", "precondition", STATE)
        self.assertIsNotNone(fix)
        self.assertIn("MakeBarrel", fix)
        self.assertIn("1 wood", fix)
        self.assertIn("Wood: 211", fix)

    def test_brew_no_plants_names_gather(self):
        fix = diagnose.diagnose_failure(
            "brew", "no brewable plants", "precondition", STATE)
        self.assertIsNotNone(fix)
        self.assertIn("designate_gather", fix)

    def test_brew_no_still_names_build(self):
        fix = diagnose.diagnose_failure(
            "brew", "no still", "precondition", STATE)
        self.assertIsNotNone(fix)
        self.assertIn("Still", fix)
        self.assertIn("Wood: 211", fix)

    def test_dig_unreachable_names_a_new_site(self):
        fix = diagnose.diagnose_failure(
            "dig_to_completion",
            "no dwarf can reach (97, 97, z174) to dig a down-stair",
            "precondition", STATE)
        self.assertIsNotNone(fix)
        self.assertIn("different site", fix)
        self.assertIn("derive_dig_site", fix)

    def test_dig_job_never_spawns_says_do_not_retry(self):
        fix = diagnose.diagnose_failure(
            "dig_to_completion",
            "no Dig job spawned within 60.0s",
            "timeout", STATE)
        self.assertIsNotNone(fix)
        self.assertIn("do NOT retry", fix)
        self.assertIn("known blocker", fix)

    def test_dig_wrong_shape_names_the_shape(self):
        fix = diagnose.diagnose_failure(
            "dig", "not all tiles are a valid shape for DownStair",
            "precondition", STATE)
        self.assertIsNotNone(fix)
        self.assertIn("FLOOR", fix)
        self.assertIn("WALL", fix)

    def test_dig_hazard_names_a_new_site(self):
        fix = diagnose.diagnose_failure(
            "dig_to_completion",
            "digging down here would hit magma",
            "precondition", STATE)
        self.assertIsNotNone(fix)
        self.assertIn("different site", fix)

    def test_unknown_cause_is_none(self):
        self.assertIsNone(diagnose.diagnose_failure(
            "brew", "something completely unexpected happened",
            "precondition", STATE))

    def test_timeout_without_a_cause_says_reread(self):
        fix = diagnose.diagnose_failure(
            "chop", "job did not appear", "timeout", STATE)
        self.assertIsNotNone(fix)
        self.assertIn("re-read", fix)


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestDiagnoseLive(unittest.TestCase):
    """A real failed action carries its fix, live (paused reads
    only — the site check refuses before designating, so nothing
    is written to the game and no game time advances)."""

    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=180.0)
        cls.client.connect()
        cls.was_paused = actions.get_paused(cls.client)
        if not cls.was_paused:
            actions.set_paused(cls.client, True)

    @classmethod
    def tearDownClass(cls):
        if not cls.was_paused:
            actions.set_paused(cls.client, False)
        cls.client.close()

    def test_unreachable_dig_carries_its_fix(self):
        # A down-stair on buried soil (97, 97, z174) — the site
        # check refuses it before any designation is set.
        result = actions.act(
            self.client, "dig_to_completion",
            box=(97, 97, 174, 97, 97, 174), mode="down-stair",
            state={"stocks": {"drink_units": 9, "food_units": 25,
                              "wood_units": 211, "stone_units": 0}})
        self.assertFalse(result.ok)
        self.assertEqual(result.error_kind, "precondition")
        self.assertIsNotNone(result.fix)
        self.assertIn("different site", result.fix)
        # And the result serialises with the fix (the agent reads
        # the JSON, not the Python object).
        self.assertIn("different site", result.to_dict()["fix"])


if __name__ == "__main__":
    unittest.main()
