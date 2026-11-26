"""Offline tests for read safety (world-model design §8).

The live behaviour (pause before read, poller skip while running) is
covered by tests/test_read_safety_live.py against a real game. These
tests cover the refusal path and the detector's pause baseline with
fakes, no game required.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import events as ev  # noqa: E402
from dfagent_harness.actions import _Fail  # noqa: E402
from dfagent_harness.read_safety import (  # noqa: E402
    ReadRefused, paused_read)


class TestPausedReadRefusal(unittest.TestCase):
    def test_refuses_when_pause_cannot_be_verified(self):
        # Game running, set_paused raises (flag will not stick):
        # the read is refused and the read function never runs.
        calls = []

        def _read():
            calls.append(True)
            return {"ok": True}

        with mock.patch(
                "dfagent_harness.read_safety.get_paused",
                return_value=False), mock.patch(
                "dfagent_harness.read_safety.set_paused",
                side_effect=_Fail("verification", "flag did not stick")):
            with self.assertRaises(ReadRefused):
                paused_read(object(), _read)
        self.assertEqual(calls, [], "read_fn ran despite refusal")

    def test_pauses_before_read_and_restores(self):
        # Game running on entry: the gate pauses, reads while paused,
        # and restores running afterwards.
        state = {"paused": False}
        seen = {}

        def _get_paused(client):
            return state["paused"]

        def _set_paused(client, paused):
            state["paused"] = paused
            return paused

        def _read():
            seen["paused_during_read"] = state["paused"]
            return {"status": {"paused": True}}

        with mock.patch(
                "dfagent_harness.read_safety.get_paused",
                side_effect=_get_paused), mock.patch(
                "dfagent_harness.read_safety.set_paused",
                side_effect=_set_paused):
            out = paused_read(object(), _read)
        self.assertEqual(out, {"status": {"paused": True}})
        self.assertTrue(seen["paused_during_read"],
                        "read_fn ran while the game was running")
        self.assertFalse(state["paused"],
                         "entry pause state (running) was not restored")

    def test_from_paused_stays_paused(self):
        state = {"paused": True}
        seen = {}

        def _get_paused(client):
            return state["paused"]

        def _set_paused(client, paused):
            state["paused"] = paused
            return paused

        def _read():
            seen["paused_during_read"] = state["paused"]
            return {"status": {"paused": True}}

        with mock.patch(
                "dfagent_harness.read_safety.get_paused",
                side_effect=_get_paused), mock.patch(
                "dfagent_harness.read_safety.set_paused",
                side_effect=_set_paused):
            paused_read(object(), _read)
        self.assertTrue(seen["paused_during_read"])
        self.assertTrue(state["paused"],
                        "gate unpaused a game that was paused on entry")


class TestNotePause(unittest.TestCase):
    def _detector_with_baseline(self, paused=True):
        d = ev.DiffDetector()
        baseline = {"status": {"paused": paused, "year_tick": 100,
                               "year": 125},
                    "units": {"citizens": []}, "jobs": {"list": []},
                    "reports": {"announcements": [], "reports": []},
                    "stocks": None, "mandates": []}
        self.assertEqual(d.detect(baseline), [])
        return d

    def test_toggle_reports_event_and_keeps_baseline_true(self):
        d = self._detector_with_baseline(paused=True)
        event = d.note_pause(False)
        self.assertIsNotNone(event, "pause toggle not reported")
        self.assertEqual(event["type"], "pause")
        self.assertEqual(event["data"], {"paused": False})
        # No change on a repeat: no duplicate event.
        self.assertIsNone(d.note_pause(False))
        # The return transition is visible to the next full diff
        # (the baseline was kept true), not swallowed.
        event = d.note_pause(True)
        self.assertIsNotNone(event)
        self.assertEqual(event["data"], {"paused": True})
        # And a full detect() after the toggle does not re-fire it:
        # the baseline now says paused=True, matching the new state.
        state = {"status": {"paused": True, "year_tick": 200,
                            "year": 125},
                 "units": {"citizens": []}, "jobs": {"list": []},
                 "reports": {"announcements": [], "reports": []},
                 "stocks": None, "mandates": []}
        events = d.detect(state)
        self.assertEqual([e for e in events if e["type"] == "pause"], [])

    def test_no_baseline_reports_nothing(self):
        d = ev.DiffDetector()
        self.assertIsNone(d.note_pause(False))


if __name__ == "__main__":
    unittest.main()
