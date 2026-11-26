"""Tests for the area-derived planner sites (sites.py).

The planner's workshop, bed, farm and stockpile sites were hardcoded
Athelunol coordinates at z=42 — the wrong fort and the wrong level
(Erushtathtat's surface is z175). A workshop site at z=42 on
Erushtathtat is deep underground stone, so probe_site rejects it and
the planner never builds anything. The sites are now derived from
the areas (the Surface area + the fort centre + the surface z).
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness import actions, observe, sites  # noqa: E402
from dfagent_harness import spatial as spatial_mod  # noqa: E402
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


FAKE_AREAS = {
    "areas": [
        {"id": "area_0001", "kind": "surface", "name": "Surface",
         "bbox": {"x0": 0, "y0": 0, "z0": 167, "x1": 191, "y1": 191,
                  "z1": 181}},
    ],
    "surface_z": 175,
}


class TestSitesOffline(unittest.TestCase):
    def test_sites_are_at_the_surface_z(self):
        s = sites.derive_sites(FAKE_AREAS, (97, 97), 175)
        self.assertEqual(len(s["workshop_sites"]), 8)
        for pos in s["workshop_sites"]:
            self.assertEqual(pos[2], 175)
        self.assertEqual(s["bed_origin"][2], 175)
        self.assertEqual(s["farm_site"][2], 175)
        self.assertEqual(s["food_stockpile_box"][2], 175)
        self.assertEqual(s["food_stockpile_box"][5], 175)

    def test_sites_are_near_the_fort_centre(self):
        s = sites.derive_sites(FAKE_AREAS, (97, 97), 175)
        # The workshop candidates are within ~12 tiles of the centre.
        for pos in s["workshop_sites"]:
            self.assertLessEqual(abs(pos[0] - 97), 12)
            self.assertLessEqual(abs(pos[1] - 97), 12)
        # The farm is further out than the beds.
        self.assertGreater(abs(s["farm_site"][0] - 97),
                           abs(s["bed_origin"][0] - 97))

    def test_sites_are_clamped_into_the_surface_bbox(self):
        # A fort centre near the map edge: the offsets must not push
        # a site outside the Surface bbox.
        small = {"areas": [
            {"id": "area_0001", "kind": "surface", "name": "Surface",
             "bbox": {"x0": 90, "y0": 90, "z0": 167,
                      "x1": 110, "y1": 110, "z1": 181}}],
                 "surface_z": 175}
        s = sites.derive_sites(small, (100, 100), 175)
        for pos in s["workshop_sites"]:
            self.assertGreaterEqual(pos[0], 90)
            self.assertLessEqual(pos[0], 110)
            self.assertGreaterEqual(pos[1], 90)
            self.assertLessEqual(pos[1], 110)

    def test_find_free_rects_finds_floor(self):
        # A grid with a 3x3 floor block (and a 2x3 block that is too
        # small), nearest the centre first.
        grid = [
            "##########",
            "#...######",
            "#...######",
            "#...######",
            "##########",
            "#####..###",
            "#####..###",
            "##########",
        ]
        rects = sites.find_free_rects(grid, 90, 90, 175,
                                      centre=(95, 95))
        self.assertEqual(rects, [(91, 91, 175)])

    def test_find_free_rects_ignores_walls_and_ramps(self):
        grid = [
            "###",
            "#.#",
            "###",
        ]
        self.assertEqual(sites.find_free_rects(grid, 0, 0, 175), [])
        grid = [
            "___",
            "___",
            "___",
        ]
        self.assertEqual(sites.find_free_rects(grid, 0, 0, 175), [])

    def test_no_surface_area_raises(self):
        with self.assertRaises(ValueError):
            sites.derive_sites({"areas": []}, (97, 97), 175)

    def test_planner_uses_derived_sites(self):
        # decide() with a sites dict uses those sites (not the
        # Athelunol z=42 constants) for its build decisions.
        from dfagent_harness import planner as planner_mod
        derived = sites.derive_sites(FAKE_AREAS, (97, 97), 175)
        state = {
            "status": {"year_tick": 169650, "paused": True},
            "units": {"citizens": [
                {"id": 1, "pos": [97, 97, 175], "job": None,
                 "profession": "Miner"}],
                      "hostiles": []},
            "stocks": {"drink_units": 25, "food_units": 25,
                       "wood_units": 211, "stone_units": 0,
                       "barrels": 15, "seeds_units": 51,
                       "by_material": []},
            "buildings": {"list": []},
            "jobs": {"list": []},
            "items": {"list": []},
        }
        decisions = planner_mod.decide(state, sites=derived)
        builds = [d for d in decisions
                  if d.action == "build_workshop"]
        self.assertGreater(len(builds), 0)
        for d in builds:
            self.assertEqual(d.kwargs["pos"][2], 175, d)


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestSitesLive(unittest.TestCase):
    """The derived sites on the real fort (paused reads only)."""

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

    def test_derived_sites_are_on_the_real_surface(self):
        state = observe.collect(self.client)
        scan = spatial_mod.scan_blocks(self.client)
        areas = spatial_mod.derive_areas(state, scan)
        surface_z = areas["surface_z"]
        # The fort centre is the Surface bbox centre (the embark
        # centre), not the median citizen position — the citizens
        # scatter and the median drifts to the map edge.
        from dfagent_harness.daemon import _fort_centre
        centre = _fort_centre(areas)
        self.assertIsNotNone(centre)
        # The workshop sites must be searched for, not assumed: the
        # surface is hilly, so fixed offsets land on WALL/RAMP/
        # BOULDER (verified live: all 8 fixed candidates around
        # (95, 95) were unbuildable). Render a slice at the surface
        # z, find the 3x3 floor rects nearest the centre, and verify
        # the first with probe_site (the daemon's _derive_sites does
        # exactly this, plus the z+1 level when the surface has none).
        from dfagent_harness.actions import _run_helper
        cx, cy = centre
        sl = spatial_mod.render_slice(
            self.client, max(0, cx - 20), max(0, cy - 20), surface_z,
            min(191, cx + 20), min(191, cy + 20))
        grid = sl.get("grid") or []
        self.assertGreater(len(grid), 0)
        rects = sites.find_free_rects(
            grid, max(0, cx - 20), max(0, cy - 20), surface_z,
            centre=centre)
        self.assertGreater(len(rects), 0)
        s = sites.derive_sites(areas, centre, surface_z,
                               floor_rects=rects)
        # Every site is at the real surface z (175), never z=42.
        for pos in s["workshop_sites"]:
            self.assertEqual(pos[2], surface_z)
        self.assertEqual(s["bed_origin"][2], surface_z)
        self.assertEqual(s["farm_site"][2], surface_z)
        self.assertEqual(s["food_stockpile_box"][2], surface_z)
        # And the first workshop candidate is a free floor (the
        # probe_site check the planner runs before building — a
        # 3x3 rect at the candidate, the size of a workshop).
        x, y, z = s["workshop_sites"][0]
        probe = _run_helper(
            self.client, "probe_site.lua",
            {"x": x, "y": y, "z": z, "width": 3, "height": 3})
        self.assertTrue(probe.get("ok", False), probe)
        self.assertTrue(probe.get("free", False), probe)


if __name__ == "__main__":
    unittest.main()
