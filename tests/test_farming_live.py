"""Live tests for farming (GOAL.md item 16, M2).

Runs against the scratch DF on 127.0.0.1:5001 (the region5 fort),
where the farm plots live — surface plot #1 at (90,90,50) and the
underground plot at (82,82,49) built by scratch/farm_live.py — and
skips itself (does not fail) when no game is reachable or no farm
plot exists. Set DFH_TEST_LIVE=0 to force the skip.

Paused reads and writes only: the refusals and the crop write +
read-back are verified here. The PlantSeeds-jobs watch (the proof
the crop is actually being planted) needs the game to run, so it
lives in scratch/farm_live.py, not here.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import actions  # noqa: E402
from dfhack_rpc import DFHackClient, DFHackError  # noqa: E402

HOST = os.environ.get("DFH_TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("DFH_TEST_PORT", "5001"))
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


def _plots(client):
    buildings = actions._read_section(client, "buildings")
    return [b for b in buildings.get("list") or []
            if b.get("type") == "FarmPlot"]


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestFarmingLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=60.0)
        cls.client.connect()
        cls.was_paused = actions.get_paused(cls.client)
        if not cls.was_paused:
            actions.set_paused(cls.client, True)
        plots = _plots(cls.client)
        if not plots:
            raise unittest.SkipTest("no farm plot on this fort")
        # Split the plots by light, from a fresh farm probe each.
        cls.sunlit = None
        cls.dark = None
        for p in plots:
            site = actions._run_helper(
                cls.client, "probe_site.lua",
                {"x": p["x1"], "y": p["y1"], "z": p["z"],
                 "width": p["x2"] - p["x1"] + 1,
                 "height": p["y2"] - p["y1"] + 1, "farm": True})
            light = (site.get("farm") or {}).get("light")
            if light == "all" and cls.sunlit is None:
                cls.sunlit = p
            elif light == "dark" and cls.dark is None:
                cls.dark = p

    @classmethod
    def tearDownClass(cls):
        if not cls.was_paused:
            actions.set_paused(cls.client, False)
        cls.client.close()

    def test_surface_plot_refuses_underground_crop(self):
        if self.sunlit is None:
            self.skipTest("no sunlit plot on this fort")
        with self.assertRaises(actions._Fail) as ctx:
            actions.set_farm_crop(self.client, self.sunlit["id"],
                                  "MUSHROOM_HELMET_PLUMP")
        self.assertIn("sunlit", str(ctx.exception))

    def test_surface_plot_refuses_wrong_season(self):
        if self.sunlit is None:
            self.skipTest("no sunlit plot on this fort")
        # Pick a season cave wheat does NOT grow in, from its own
        # raw — season-proof, whatever the fort's current season.
        crop = actions._run_helper(self.client, "probe_crop.lua",
                                   {"crop": "GRASS_WHEAT_CAVE"})
        self.assertTrue(crop.get("ok"), crop)
        seasons = {str(s) for s in crop.get("seasons") or []}
        names = ("SPRING", "SUMMER", "AUTUMN", "WINTER")
        bad = next(i for i, n in enumerate(names) if n not in seasons)
        with self.assertRaises(actions._Fail) as ctx:
            actions.set_farm_crop(self.client, self.sunlit["id"],
                                  "GRASS_WHEAT_CAVE", season=bad)
        self.assertIn(f"does not grow in {names[bad].lower()}",
                      str(ctx.exception))

    def test_surface_plot_refuses_without_seeds(self):
        if self.sunlit is None:
            self.skipTest("no sunlit plot on this fort")
        seeds = actions._run_helper(self.client, "probe_seeds.lua", {})
        have = int(((seeds.get("by_plant") or {}).get("REED_ROPE")
                    or {}).get("units") or 0)
        if have > 0:
            self.skipTest("rope reed seeds now on hand — the "
                          "refusal cannot be tested on this fort")
        with self.assertRaises(actions._Fail) as ctx:
            actions.set_farm_crop(self.client, self.sunlit["id"],
                                  "REED_ROPE")
        self.assertIn("no REED_ROPE seeds", str(ctx.exception))

    def test_underground_plot_takes_plump_helmets(self):
        if self.dark is None:
            self.skipTest("no underground plot on this fort")
        res = actions.set_farm_crop(self.client, self.dark["id"],
                                    "MUSHROOM_HELMET_PLUMP")
        self.assertTrue(res.ok, res.reason)
        # 172 is the live raw index for MUSHROOM_HELMET_PLUMP
        # (raws[171] is WALNUT). probe_crop.lua once returned
        # `ipairs` index - 1, writing WALNUT into the plot — a
        # tree that can never be farm-planted, which is why
        # autumn/winter produced 0 PlantSeeds jobs (2026-11-27).
        self.assertEqual(res.detail["plant_index"], 172)
        # The write stuck: plant_id[season] read back is the crop.
        self.assertEqual(res.after["plant_id"][res.detail["season"]],
                         172)
        self.assertGreater(res.detail["tiles_plantable"], 0)


if __name__ == "__main__":
    unittest.main()
