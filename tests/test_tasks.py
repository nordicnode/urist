"""Tests for the composed tasks' causal chains (GOAL.md step 5,
layer 2). A task encodes the causal chain for a goal: it checks its
prerequisites before queuing, and it reports a cancelled job as a
failure, not a success. A task that claims success when the job was
cancelled is worse than one that fails — it hides the problem.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness import actions, daemon as daemon_mod  # noqa: E402
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


class TestTaskDefsOffline(unittest.TestCase):
    def test_every_task_names_its_need(self):
        # A task's 'need' is the workshop it cannot run without;
        # gather needs none (it designates plants in the open).
        for name, spec in daemon_mod.TASK_DEFS.items():
            self.assertIn("need", spec, name)
            self.assertIn("wait_job", spec, name)
            self.assertIn("action", spec, name)

    def test_brew_needs_a_still(self):
        self.assertEqual(daemon_mod.TASK_DEFS["brew"]["need"], "still")
        self.assertEqual(daemon_mod.TASK_DEFS["brew"]["wait_job"],
                         "CustomReaction")

    def test_cook_needs_a_kitchen(self):
        self.assertEqual(daemon_mod.TASK_DEFS["cook"]["need"], "kitchen")
        self.assertEqual(daemon_mod.TASK_DEFS["cook"]["wait_job"],
                         "PrepareMeal")


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestTasksLive(unittest.TestCase):
    """The causal chains, live (paused reads and writes only — no
    unpause, no game time advances, no drink consumed)."""

    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=180.0)
        cls.client.connect()
        cls.was_paused = actions.get_paused(cls.client)
        if not cls.was_paused:
            actions.set_paused(cls.client, True)
        cls.daemon = daemon_mod.Daemon()
        # The daemon normally connects its own client in start();
        # here the test supplies the shared one (the daemon is not
        # started — run_task only needs client + lock + state dir).
        cls.daemon.client = cls.client

    @classmethod
    def tearDownClass(cls):
        if not cls.was_paused:
            actions.set_paused(cls.client, False)
        cls.client.close()

    def test_brew_without_a_still_fails_fast(self):
        # The fort has no workshops at all, so the brew task must
        # fail on the prerequisite (a still), not queue a job that
        # can never be worked.
        result = self.daemon.run_task("brew")
        self.assertFalse(result["ok"])
        self.assertIn("no still workshop exists", result["detail"])

    def test_gather_uses_a_surface_box(self):
        # The gather box is derived from the live state (a probe for
        # shrubs on the surface), never the old hardcoded GATHER_BOX
        # (Athelunol z=42, solid rock here). Designating is a paused
        # write; the game stays paused, so no GatherPlants job
        # spawns and no drink is consumed. The designation is
        # cleared afterwards (mark=False) to leave no trace.
        from dfagent_harness import observe
        state = observe.collect(self.client)
        citizens = (state.get("units") or {}).get("citizens") or []
        self.assertGreater(len(citizens), 0)
        surface_z = min(c["pos"][2] for c in citizens if c.get("pos"))
        result = self.daemon.run_task("gather")
        self.assertTrue(result["ok"], result)
        # The box is on the surface (never z=42) and shrubs were
        # actually marked (the action's own before/after read-back).
        self.assertEqual(result["box"][2], surface_z)
        self.assertGreater(result["after"]["total"], 0)
        self.assertEqual(result["after"]["marked"],
                         result["after"]["total"])
        # Clean up: unmark the shrubs.
        actions.act(self.client, "designate_gather",
                    box=tuple(result["box"]), mark=False)

    def test_unknown_task_fails_cleanly(self):
        result = self.daemon.run_task("bogus_task")
        self.assertFalse(result["ok"])
        self.assertIn("unknown task", result["detail"])


if __name__ == "__main__":
    unittest.main()
