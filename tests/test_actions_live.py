"""Live integration tests for the verified action layer (phase 2).

Runs against a real Dwarf Fortress 0.47.05 game on 127.0.0.1:5000 and
skips itself (does not fail) when no game is reachable — the suite must
stay green on machines without DF running. Set DFH_TEST_LIVE=0 to force
the skip even when a game is up.

Every test cleans up after itself: designations are undone, orders
removed, labors restored, and the workshop built by the build test is
deconstructed again. The game is left paused. One deliberate exception:
the build test deconstructs the embark wagon first (test setup, not a
phase-2 action) — all embark wood is trapped inside the wagon, so no
workshop can be built until it is gone; see docs/ACTIONS.md.

Run from the repo root:

    .venv/bin/python -m unittest discover -s tests -v
"""

import json
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness import actions  # noqa: E402
from dfagent_harness.observe import collect  # noqa: E402
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


def _wait_for(fn, timeout, interval=0.5):
    deadline = time.monotonic() + timeout
    while True:
        value = fn()
        if value:
            return value
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestLiveActions(unittest.TestCase):
    """Verified live against the Athelunol fort (region1)."""

    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=30.0)
        cls.client.connect()
        # The suite runs paused; any test that unpauses restores it.
        actions.set_paused(cls.client, True)

    @classmethod
    def tearDownClass(cls):
        try:
            actions.set_paused(cls.client, True)
        finally:
            cls.client.quit()

    def setUp(self):
        # A previous test must never leave the game running.
        self.assertTrue(actions.get_paused(self.client),
                        "game left unpaused by a previous test")

    # -- helpers ----------------------------------------------------------

    def _buildings(self):
        return collect(self.client, sections=("buildings",))["buildings"]

    def _jobs(self):
        return collect(self.client, sections=("jobs",))["jobs"]

    def _deconstruct_building(self, building_id, timeout=30.0):
        """Mark a building for deconstruction and wait until it is gone.

        Uses dfhack.buildings.deconstruct + almost_deleted (the wagon
        vanishes a tick later, per deep-embark.lua); the game is unpaused
        for the wait and re-paused after. Afterwards the building's
        footprint tiles get their stale "building" occupancy cleared:
        deconstruction does not clear it (verified live 2026-11-26 —
        a deconstructed workshop's tiles keep occupancy.building=2 and
        constructBuilding refuses them until the flag is cleared), so
        without this every test run would burn one workshop site.
        """
        target = next((b for b in self._buildings()["list"]
                       if b["id"] == building_id), None)
        self.assertIsNotNone(target, f"no building #{building_id}")
        code = (
            "local b = df.building.find(%d)\n"
            "if b == nil then print('NO_BUILDING') else\n"
            "  dfhack.buildings.deconstruct(b)\n"
            "  b.flags.almost_deleted = true\n"
            "  print('DECONSTRUCT_MARKED')\n"
            "end\n" % building_id)
        out = self.client.run_lua(code).strip()
        self.assertEqual(out, "DECONSTRUCT_MARKED",
                         f"deconstruct failed for #{building_id}: {out!r}")
        actions.set_paused(self.client, False)
        try:
            gone = _wait_for(
                lambda: not any(b["id"] == building_id
                                for b in self._buildings()["list"]),
                timeout)
        finally:
            actions.set_paused(self.client, True)
        self.assertTrue(gone, f"building #{building_id} did not vanish")
        # Clear the stale building occupancy on the footprint so the
        # site is buildable again (see probe_site.lua).
        x1, y1, z = target["x1"], target["y1"], target["z"]
        x2, y2 = target["x2"], target["y2"]
        clear = (
            "for x = %d, %d do for y = %d, %d do\n"
            "  local b = dfhack.maps.getTileBlock(x, y, %d)\n"
            "  b.occupancy[x %% 16][y %% 16].building = 0\n"
            "end end\n" % (x1, x2, y1, y2, z))
        self.client.run_lua(clear)

    def _ensure_accessible_wood(self):
        """Deconstruct the embark wagon if the wood is still inside it.

        One-time fort setup for the build test: all 3 embark logs sit in
        the wagon (in_building), and jobs cannot use them. Returns True
        when at least one accessible log exists afterwards.
        """
        mat = actions._run_helper(self.client, "probe_material.lua",
                                  {"item_type": "WOOD"})
        if mat.get("accessible", 0) >= 1:
            return True
        wagon = next((b for b in self._buildings()["list"]
                      if b["type"] == "Wagon"), None)
        self.assertIsNotNone(wagon, "no accessible wood and no wagon?")
        self._deconstruct_building(wagon["id"])
        mat = actions._run_helper(self.client, "probe_material.lua",
                                  {"item_type": "WOOD"})
        return mat.get("accessible", 0) >= 1

    def _first_free_workshop_site(self):
        """First free 3x3 site from a candidate list near the wagon."""
        for x, y in ((85, 85), (88, 85), (85, 88), (100, 85),
                     (85, 100), (105, 90), (102, 92)):
            site = actions._run_helper(
                self.client, "probe_site.lua",
                {"x": x, "y": y, "z": 42, "width": 3, "height": 3})
            if site.get("free"):
                return (x, y, 42)
        self.fail("no free 3x3 workshop site found near the wagon")

    # -- tests -------------------------------------------------------------

    def test_build_carpenter_workshop(self):
        self.assertTrue(self._ensure_accessible_wood(),
                        "still no accessible wood after wagon teardown")
        site = self._first_free_workshop_site()
        before_count = self._buildings()["count"]
        r = actions.act(self.client, "build_workshop", kind="carpenter",
                        pos=site, build_timeout=120.0)
        self.assertTrue(r.ok, r.reason)
        bid = r.detail["building_id"]
        self.assertEqual(r.after["building_count"], before_count + 1)
        self.assertEqual(r.after["building"]["id"], bid)
        # Construction really finished: no ConstructBuilding job remains.
        self.assertFalse(
            [j for j in self._jobs()["list"]
             if j["type"] == "ConstructBuilding"],
            "a ConstructBuilding job is still queued after completion")
        # Cleanup: deconstruct the workshop again, verify it is gone.
        self._deconstruct_building(bid)
        self.assertEqual(self._buildings()["count"], before_count)

    def test_chop_marks_tree_spawns_job_and_unmarks(self):
        # Tree at 110,98,32 (des tile the same). The unmark succeeds on
        # the verified designation, but the FellTree job is NOT removed
        # by the game — verified live 2026-11-25/26: removeJob, the
        # game's own designation processing, and ticks all leave it, and
        # manual deletion crashed the game once, so it is reported in
        # detail["remaining_jobs"] rather than failed on. See
        # docs/ACTIONS.md. The tree itself must still stand, and the
        # test tolerates a stale FellTree job left by an earlier run.
        box = (108, 96, 32, 112, 100, 32)  # just the tree at 110,98,32
        # The game's designation sweep is slow and variable (a FellTree
        # job took >30s to appear once), so the spawn wait is generous.
        r = actions.act(self.client, "designate_chop", box=box,
                        job_timeout=90.0)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.before, {"total": 1, "marked": 0})
        self.assertEqual(r.after, {"total": 1, "marked": 1})
        self.assertIn("FellTree", json.dumps(r.detail.get("job_evidence")),
                      "no FellTree job evidence")
        # The tree itself must still stand: it is in an unreachable
        # cavern pocket, so no dwarf ever takes the stale FellTree job.
        r2 = actions.act(self.client, "designate_chop", box=box, mark=False)
        self.assertTrue(r2.ok, r2.reason)
        self.assertEqual(r2.after, {"total": 1, "marked": 0})
        remaining = r2.detail.get("remaining_jobs") or []
        self.assertGreaterEqual(
            len(remaining), 1,
            "expected the known stale FellTree job(s) to be reported")
        self.assertTrue(
            all(j["type"] == "FellTree" and j["pos"] == [110, 98, 32]
                for j in remaining),
            f"unexpected remaining jobs: {remaining!r}")

    def test_dig_designate_and_clear(self):
        box = (90, 90, 41, 91, 91, 41)  # 4 soil-wall tiles under the fort
        r = actions.act(self.client, "designate_dig", box=box, mode="dig")
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.before, {"dig_total": 0})
        self.assertEqual(r.after["dig_total"], 4)
        # Still paused: no Dig job may have spawned, no terrain changed.
        # (Scoped to Dig jobs: the zombie FellTree #3 is always listed.)
        self.assertFalse([j for j in self._jobs()["list"]
                          if j["type"] == "Dig"],
                         "a Dig job spawned while paused")
        r2 = actions.act(self.client, "designate_dig", box=box, mode="clear")
        self.assertTrue(r2.ok, r2.reason)
        self.assertEqual(r2.after["dig_total"], 0)

    def test_gather_marks_shrub_spawns_job_and_unmarks(self):
        box = (95, 96, 42, 99, 100, 42)  # around the shrub at 97,98,42
        r = actions.act(self.client, "designate_gather", box=box,
                        job_timeout=90.0)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.before, {"total": 1, "marked": 0})
        self.assertEqual(r.after, {"total": 1, "marked": 1})
        self.assertIn("GatherPlants",
                      json.dumps(r.detail.get("job_evidence")),
                      "no GatherPlants job evidence")
        r2 = actions.act(self.client, "designate_gather", box=box,
                         mark=False)
        self.assertTrue(r2.ok, r2.reason)
        self.assertEqual(r2.after, {"total": 1, "marked": 0})
        # GatherPlants jobs really do leave the list (unlike FellTree):
        # the unmark must report none remaining.
        self.assertEqual(r2.detail.get("remaining_jobs"), [])

    def test_labor_toggle_roundtrip(self):
        units = collect(self.client, sections=("units",))["units"]
        citizen = units["citizens"][0]
        labor = next(iter(citizen["labors"]), None)
        self.assertIsNotNone(labor, "first citizen has no labors on")
        r = actions.act(self.client, "labor_toggle", unit=citizen["id"],
                        labor=labor, on=False)
        self.assertTrue(r.ok, r.reason)
        self.assertNotIn(labor, r.after["labors"])
        r2 = actions.act(self.client, "labor_toggle", unit=citizen["id"],
                         labor=labor, on=True)
        self.assertTrue(r2.ok, r2.reason)
        self.assertIn(labor, r2.after["labors"])

    def test_manager_order_create_and_remove(self):
        before = self._jobs()["manager_order_count"]
        self.assertEqual(before, 0)
        r = actions.act(self.client, "manager_order_create",
                        job_type="MakeBarrel", amount=5)
        self.assertTrue(r.ok, r.reason)
        oid = r.detail["order_id"]
        after = self._jobs()
        self.assertEqual(after["manager_order_count"], 1)
        order = after["manager_orders"][0]
        self.assertEqual(order["id"], oid)
        self.assertEqual(order["job_type_name"], "MakeBarrel")
        self.assertEqual(order["amount_left"], 5)
        self.assertEqual(order["amount_total"], 5)
        r2 = actions.act(self.client, "manager_order_remove", order_id=oid)
        self.assertTrue(r2.ok, r2.reason)
        self.assertEqual(self._jobs()["manager_order_count"], 0)

    def test_observe_sections_healthy(self):
        # Regression guard for the reports.lua 0-based indexing fix: the
        # fort now has announcements, so a broken take_tail fails here.
        state = collect(self.client)
        self.assertEqual(state["errors"], [])
        self.assertGreaterEqual(
            state["reports"]["announcement_count"], 1)

    def test_pause_restored(self):
        self.assertTrue(actions.get_paused(self.client))


if __name__ == "__main__":
    unittest.main()
