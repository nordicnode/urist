"""Live integration tests for the phase-3 event system.

Runs against a real Dwarf Fortress 0.47.05 game on 127.0.0.1:5000 and
skips itself (does not fail) when no game is reachable — the suite
must stay green on machines without DF running. Set DFH_TEST_LIVE=0
to force the skip even when a game is up.

Verified live against the Athelunol fort (region1). The game is left
paused by every test (pause state is restored even on failure), and
the eventful watcher is uninstalled afterwards.
"""

import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness import collect, events as ev  # noqa: E402
from dfagent_harness import actions  # noqa: E402
from dfhack_rpc import DFHackClient, DFHackError  # noqa: E402

HOST = os.environ.get("DFH_TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("DFH_TEST_PORT", "5000"))
LIVE_DISABLED = os.environ.get("DFH_TEST_LIVE", "1") == "0"
DF_DIR = Path(__file__).resolve().parent.parent / "third_party" / "df_47_05"
WATCH_LOG = DF_DIR / "dfh-events.jsonl"


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
class TestLiveEvents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=30.0)
        cls.client.connect()
        cls.was_paused = actions.get_paused(cls.client)
        if not cls.was_paused:
            actions.set_paused(cls.client, True)
        cls.install_line = ev.install_watcher(cls.client, WATCH_LOG)
        cls.drainer = ev.WatcherDrainer(WATCH_LOG)
        # Drain the install-time baseline (nothing should be pending:
        # the watcher suppresses the replay, but be safe).
        cls.drainer.drain()

    @classmethod
    def tearDownClass(cls):
        try:
            ev.uninstall_watcher(cls.client)
        finally:
            try:
                actions.set_paused(cls.client, cls.was_paused)
            finally:
                cls.client.quit()

    def test_watcher_install_reports(self):
        self.assertIn("DFH-WATCH-OK", self.install_line)
        status = ev.watcher_status(self.client)
        self.assertTrue(status["installed"])
        self.assertTrue(status["on_state_change"])

    def test_mandates_probe_runs(self):
        mandates = ev.collect_mandates(self.client)
        self.assertIsInstance(mandates, list)
        # No nobles appointed yet: no mandates on this fort.
        self.assertEqual(mandates, [])

    def test_units_lite_matches_full(self):
        full = collect(self.client, sections=("units",))
        lite = collect(self.client, sections=("units",), lite_units=True)
        full_ids = sorted(c["id"] for c in full["units"]["citizens"])
        lite_ids = sorted(c["id"] for c in lite["units"]["citizens"])
        self.assertEqual(full_ids, lite_ids)
        self.assertEqual(full["units"]["citizen_count"],
                         lite["units"]["citizen_count"])
        # Lite keeps every field the detector reads. (job is absent —
        # not null — when idle: the Lua encoder omits nil keys. The
        # detector reads it with .get(), and the full section behaves
        # the same way.)
        for c in lite["units"]["citizens"]:
            for key in ("counters", "stress", "wound_count", "idle"):
                self.assertIn(key, c)
            self.assertEqual(c.get("job"), None if c["idle"] else
                             c.get("job"))

    def test_poller_sees_pause_toggle(self):
        bus = ev.EventBus()
        poller = ev.EventPoller(
            self.client, bus, drainer=self.drainer,
            fast_interval=0.1, paused_interval=0.1, slow_interval=3600)
        poller.poll_once()  # baseline
        try:
            actions.set_paused(self.client, False)
        except actions._Fail as exc:  # noqa: SLF001 - known RFR flake
            self.skipTest(f"RFR unpause flake, cannot toggle: {exc}")
        try:
            found = poller.poll_once()
            pauses = [e for e in found if e["type"] == "pause"]
            self.assertEqual(len(pauses), 1)
            self.assertEqual(pauses[0]["data"], {"paused": False})
        finally:
            actions.set_paused(self.client, True)
        found = poller.poll_once()
        pauses = [e for e in found if e["type"] == "pause"]
        self.assertEqual(len(pauses), 1)
        self.assertEqual(pauses[0]["data"], {"paused": True})

    def test_job_completion_via_eventful(self):
        """A JOB_COMPLETED record must reach the watcher log within a
        bounded unpause, and the drainer must turn it into a
        job_completed event with a job id. This is the live proof
        that eventful works in 0.47.05-r8 fortress mode. Ambient
        completions are bursty (dwarves eat/drink on ~40k-tick
        timers), so a quiet window SKIPS rather than fails — the
        deterministic proof is test_work_completion_via_eventful,
        which triggers a gather completion on demand."""
        try:
            actions.set_paused(self.client, False)
        except actions._Fail as exc:  # noqa: SLF001 - known RFR flake
            self.skipTest(f"RFR unpause flake, cannot toggle: {exc}")
        deadline = time.time() + 120
        found = []
        try:
            while time.time() < deadline:
                found = [e for e in self.drainer.drain()
                         if e["type"] == "job_completed"
                         and e["data"].get("job_id") is not None]
                if found:
                    break
                time.sleep(5)
        finally:
            actions.set_paused(self.client, True)
        if not found:
            self.skipTest("no JOB_COMPLETED in 120 s unpaused — the "
                          "fort was quiet (timers freshly reset); "
                          "see test_work_completion_via_eventful")
        self.assertTrue(found[0]["data"]["job_type"],
                        "job completion without a job type")

    def test_manager_order_seen_by_detector(self):
        """A manager order appearing then disappearing is visible to
        the poll-diff detector (which reports the disappearance as a
        job completion — poll cannot distinguish completion from
        removal; see docs/EVENTS.md)."""
        result = actions.manager_order_create(self.client, "MakeBarrel",
                                              amount=1)
        self.assertTrue(result.ok, result.reason)
        order_id = result.detail["order_id"]
        try:
            det = ev.DiffDetector()
            before = collect(self.client, sections=("jobs",))
            det.detect(before)
            result = actions.manager_order_remove(self.client, order_id)
            self.assertTrue(result.ok, result.reason)
            after = collect(self.client, sections=("jobs",))
            found = det.detect(after)
            completed = [e for e in found if e["type"] == "job_completed"]
            self.assertEqual(len(completed), 1)
            self.assertEqual(completed[0]["data"]["manager_order_id"],
                             order_id)
        finally:
            # Cleanup if the test failed mid-way.
            state = collect(self.client, sections=("jobs",))
            ids = [o["id"] for o in
                   state["jobs"]["manager_orders"]]
            if order_id in ids:
                actions.manager_order_remove(self.client, order_id)

    def test_work_completion_via_eventful(self):
        """Gather a surface shrub; the GatherPlants job must complete
        and the watcher must report it with the job's id. This is the
        eventful-or-nothing case on this fort: a FellTree completion
        cannot be tested live here (every tree is a cavern tree and
        none is reachable — the one at (85,70,32) spawned a job no
        dwarf took in 120 s), and a manager order is never worked
        without a manager noble. Poll-diff alone can see a
        GatherPlants completion too (the job leaves world.jobs.list),
        but only eventful carries the job id + worker."""
        # One known-good surface shrub tile, probed live. Shrubs
        # regrow after being gathered, but a tile may be empty when
        # the suite runs, so try the candidates in order.
        candidates = [(92, 79, 42), (70, 87, 42), (85, 44, 42),
                      (51, 90, 42), (73, 95, 42), (59, 100, 42)]
        marked = None
        box = None
        for x, y, z in candidates:
            b = (x, y, z, x, y, z)
            try:
                m = actions.designate_gather(self.client, box=b)
            except Exception:
                continue
            if m.ok:
                marked, box = m, b
                break
        if marked is None:
            self.skipTest("no candidate shrub tile had a shrub "
                          "(they regrow; try again later)")
        evidence = marked.detail.get("job_evidence") or {}
        job_ids = [j["id"] for j in evidence.get("jobs", [])]
        if not job_ids:
            self.skipTest("shrub gathered before the spawn poll saw "
                          "the job (harvested during marking)")
        target = job_ids[0]
        try:
            actions.set_paused(self.client, False)
        except actions._Fail as exc:  # noqa: SLF001 - known RFR flake
            self.skipTest(f"RFR unpause flake, cannot toggle: {exc}")
        deadline = time.time() + 300
        found = []
        try:
            while time.time() < deadline:
                found = [e for e in self.drainer.drain()
                         if e["type"] == "job_completed"
                         and e["data"].get("job_id") == target]
                if found:
                    break
                time.sleep(5)
        finally:
            actions.set_paused(self.client, True)
            actions.designate_gather(self.client, box=box, mark=False)
        self.assertTrue(found, f"GatherPlants job {target} did not "
                               "complete within 300 s unpaused")
        self.assertEqual(found[0]["data"]["job_type"], "GatherPlants")
        self.assertIsNotNone(found[0]["data"]["worker_id"])


if __name__ == "__main__":
    unittest.main()
