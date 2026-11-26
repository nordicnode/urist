"""Live integration tests for read safety (world-model design §8).

Runs against a real Dwarf Fortress 0.47.05 game on 127.0.0.1:5000 and
skips itself (does not fail) when no game is reachable — the suite must
stay green on machines without DF running. Set DFH_TEST_LIVE=0 to force
the skip even when a game is up.

Verifies, live:
- ``paused_read`` pauses before reading and restores the entry pause
  state afterwards (both from running and from paused).
- The poller does NOT collect while the game is running (poll_count
  does not advance) but still reports the pause toggle (via the
  pause-flag read + DiffDetector.note_pause), and DOES collect while
  paused (poll_count advances).
- A direct ``observe.collect`` is never the path these gates take;
  the tests exercise the gates, not a raw read while running.

Run from the repo root:

    .venv/bin/python -m unittest discover -s tests -v
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness import actions, events as ev  # noqa: E402
from dfagent_harness.observe import collect  # noqa: E402
from dfagent_harness.read_safety import paused_read  # noqa: E402
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
class TestLiveReadSafety(unittest.TestCase):
    """Verified live against the Erushtathtat fort (region2, Ilassil)."""

    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=30.0)
        cls.client.connect()
        cls.was_paused = actions.get_paused(cls.client)
        if not cls.was_paused:
            actions.set_paused(cls.client, True)

    @classmethod
    def tearDownClass(cls):
        try:
            actions.set_paused(cls.client, cls.was_paused)
        finally:
            cls.client.quit()

    def setUp(self):
        # Every test starts paused; tests that unpause restore it.
        if not actions.get_paused(self.client):
            actions.set_paused(self.client, True)

    def tearDown(self):
        if not actions.get_paused(self.client):
            actions.set_paused(self.client, True)

    def test_paused_read_pauses_before_reading(self):
        # From running: the gate pauses first, reads while paused,
        # and restores running afterwards.
        try:
            actions.set_paused(self.client, False)
        except actions._Fail as exc:  # noqa: SLF001 - known RFR flake
            self.skipTest(f"RFR unpause flake, cannot toggle: {exc}")
        seen = {}

        def _read():
            seen["paused_during_read"] = actions.get_paused(self.client)
            return collect(self.client, sections=("status",))

        state = paused_read(self.client, _read)
        self.assertTrue(seen.get("paused_during_read"),
                        "read_fn ran while the game was running")
        self.assertIn("status", state)
        self.assertFalse(actions.get_paused(self.client),
                         "gate did not restore the running entry state")

    def test_paused_read_from_paused_stays_paused(self):
        self.assertTrue(actions.get_paused(self.client))
        seen = {}

        def _read():
            seen["paused_during_read"] = actions.get_paused(self.client)
            return collect(self.client, sections=("status",))

        state = paused_read(self.client, _read)
        self.assertTrue(seen.get("paused_during_read"))
        self.assertIn("status", state)
        self.assertTrue(actions.get_paused(self.client),
                        "gate unpaused a game that was paused on entry")

    def test_poller_skips_collect_while_running(self):
        bus = ev.EventBus()
        # No drainer: the pause events under test come from the
        # detector (flag read + note_pause), not the watcher file.
        poller = ev.EventPoller(
            self.client, bus, drainer=None,
            fast_interval=0.1, paused_interval=0.1, slow_interval=3600)
        poller.poll_once()  # baseline (paused): establishes last_state
        baseline_count = poller.poll_count
        self.assertGreater(baseline_count, 0,
                           "baseline poll did not collect while paused")
        try:
            actions.set_paused(self.client, False)
        except actions._Fail as exc:  # noqa: SLF001 - known RFR flake
            self.skipTest(f"RFR unpause flake, cannot toggle: {exc}")
        # While running: the poller must NOT collect (poll_count
        # frozen), but it must still report the pause toggle.
        found = poller.poll_once()
        self.assertEqual(poller.poll_count, baseline_count,
                         "poller collected while the game was running")
        pauses = [e for e in found if e["type"] == "pause"]
        self.assertEqual(len(pauses), 1,
                         "pause toggle not reported while running")
        self.assertEqual(pauses[0]["data"], {"paused": False})
        # Back to paused: the poller collects again, and the return
        # transition is reported (the baseline was kept true by
        # note_pause, so the detector sees False -> True).
        actions.set_paused(self.client, True)
        found = poller.poll_once()
        self.assertGreater(poller.poll_count, baseline_count,
                           "poller did not collect once paused again")
        pauses = [e for e in found if e["type"] == "pause"]
        self.assertEqual(len(pauses), 1,
                         "return-to-paused toggle not reported")
        self.assertEqual(pauses[0]["data"], {"paused": True})
