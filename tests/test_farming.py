"""Offline tests for the farming action (set_farm_crop).

The action's job is to verify a planting BEFORE it writes anything:
the plot's light, the crop's depth/season/biome, and the seeds on
hand. Those checks are pure decision logic over the Lua helpers'
outputs, so they are tested here by stubbing _run_helper /
_read_section / _helper_or_fail with canned replies shaped like
the live probes (verified 2026-11-27 on the scratch fort). The Lua
helpers themselves are exercised by tests/test_farming_live.py.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import actions  # noqa: E402


def _plot(plot_id=1, x1=90, y1=90, x2=92, y2=92, z=50, stage=3,
          ptype="FarmPlot"):
    return {"id": plot_id, "type": ptype, "z": z, "x1": x1, "y1": y1,
            "x2": x2, "y2": y2, "center": [91, 91, z],
            "construction_stage": stage, "jobs": 0}


def _crop(name="MUSHROOM_HELMET_PLUMP", index=172, dmin=1, dmax=3,
          seasons=("SPRING", "SUMMER", "AUTUMN", "WINTER"),
          biomes=("BIOME_SUBTERRANEAN_WATER",), cur=0):
    return {"ok": True, "crop": name, "index": index,
            "depth_min": dmin, "depth_max": dmax, "growdur": 300,
            "seasons": list(seasons), "biome_flags": list(biomes),
            "cur_season": cur, "cur_season_name": "spring"}


def _site(light="dark", soil=9, stone=0, biomes=("MOUNTAIN",)):
    return {"ok": True, "probe": "site", "free": True, "reachable": True,
            "problems": [],
            "farm": {"soil_tiles": soil, "stone_tiles": stone,
                     "other_tiles": 0, "light_tiles": 0,
                     "total_tiles": 9, "light": light,
                     "biomes": list(biomes)}}


def _seeds(units=5, wagon=5):
    return {"ok": True,
            "by_plant": {"MUSHROOM_HELMET_PLUMP": {
                "units": units, "in_wagon_units": wagon, "stacks": 1}},
            "total_stacks": 6}


class TestSetFarmCrop(unittest.TestCase):
    def _run(self, plot=None, crop=None, site=None, seeds=None,
             plant="MUSHROOM_HELMET_PLUMP"):
        """Run set_farm_crop with stubbed helpers; returns the result
        or the _Fail raised."""
        plot = plot if plot is not None else _plot()
        crop = crop if crop is not None else _crop()
        site = site if site is not None else _site()
        seeds = seeds if seeds is not None else _seeds()
        calls = {}

        def fake_run_helper(client, name, params, timeout=30.0):
            calls[name] = params
            if name == "probe_crop.lua":
                return crop
            if name == "probe_site.lua":
                return site
            if name == "probe_seeds.lua":
                return seeds
            raise AssertionError(f"unexpected helper {name}")

        def fake_read_section(client, section, timeout=30.0):
            assert section == "buildings"
            return {"list": [plot]}

        def fake_helper_or_fail(client, name, params, timeout=30.0):
            calls["act"] = params
            assert name == "act_farm_crop.lua"
            return {"ok": True, "plant_id": [-1, 172, -1, -1]}

        with mock.patch.object(actions, "_run_helper",
                               side_effect=fake_run_helper), \
            mock.patch.object(actions, "_read_section",
                              side_effect=fake_read_section), \
            mock.patch.object(actions, "_helper_or_fail",
                              side_effect=fake_helper_or_fail):
            try:
                return actions.set_farm_crop(
                    mock.Mock(), 1, plant), calls
            except actions._Fail as exc:
                return exc, calls

    def test_happy_path_partial_seeds(self):
        res, calls = self._run()
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(res.detail["plant_index"], 172)
        self.assertEqual(res.detail["season"], 0)
        self.assertEqual(res.detail["tiles_plantable"], 5)
        self.assertIn("5 of 9 tiles", res.reason)
        self.assertIn("wagon", res.reason)
        self.assertEqual(calls["act"]["plant_index"], 172)
        self.assertEqual(calls["act"]["season"], 0)
        # The site probe carries the farm flag.
        self.assertTrue(calls["probe_site.lua"]["farm"])

    def test_full_seeds_plants_every_tile(self):
        res, _ = self._run(seeds=_seeds(units=9, wagon=0))
        self.assertTrue(res.ok, res.reason)
        self.assertEqual(res.detail["tiles_plantable"], 9)
        self.assertNotIn("stay empty", res.reason)

    def test_mixed_light_refused(self):
        exc, _ = self._run(site=_site(light="mixed"))
        self.assertIsInstance(exc, actions._Fail)
        self.assertEqual(exc.kind, "precondition")
        self.assertIn("mixed", exc.reason)

    def test_underground_crop_on_sunlit_plot_refused(self):
        exc, _ = self._run(site=_site(light="all"))
        self.assertIsInstance(exc, actions._Fail)
        self.assertIn("underground", exc.reason)
        self.assertIn("sunlit", exc.reason)

    def test_surface_crop_on_dark_plot_refused(self):
        exc, _ = self._run(
            crop=_crop(name="REED_ROPE", index=185, dmin=0, dmax=0,
                       biomes=("BIOME_SWAMP_TEMPERATE_SALTWATER",)),
            site=_site(light="dark"),
            plant="REED_ROPE")
        self.assertIsInstance(exc, actions._Fail)
        self.assertIn("above ground", exc.reason)

    def test_wrong_season_refused(self):
        exc, _ = self._run(
            crop=_crop(name="GRASS_WHEAT_CAVE", index=173,
                       seasons=("SUMMER", "AUTUMN")))
        self.assertIsInstance(exc, actions._Fail)
        self.assertIn("does not grow in spring", exc.reason)

    def test_biome_mismatch_refused(self):
        # Rope reed on a MOUNTAIN-biome plot: the crop's flags do
        # not include BIOME_MOUNTAIN.
        exc, _ = self._run(
            crop=_crop(name="REED_ROPE", index=185, dmin=0, dmax=0,
                       biomes=("BIOME_SWAMP_TEMPERATE_SALTWATER",)),
            site=_site(light="all", biomes=("MOUNTAIN",)),
            plant="REED_ROPE")
        self.assertIsInstance(exc, actions._Fail)
        self.assertIn("does not grow in this plot's biome",
                      exc.reason)

    def test_biome_match_accepted(self):
        res, _ = self._run(
            crop=_crop(name="REED_ROPE", index=185, dmin=0, dmax=0,
                       biomes=("BIOME_SWAMP_TEMPERATE_SALTWATER",)),
            site=_site(light="all", biomes=("SWAMP_TEMPERATE_SALTWATER",)),
            seeds={"ok": True,
                   "by_plant": {"REED_ROPE": {
                       "units": 9, "in_wagon_units": 0, "stacks": 1}},
                   "total_stacks": 1},
            plant="REED_ROPE")
        self.assertTrue(res.ok, res.reason)

    def test_no_seeds_refused(self):
        exc, _ = self._run(seeds={"ok": True, "by_plant": {},
                                  "total_stacks": 0})
        self.assertIsInstance(exc, actions._Fail)
        self.assertIn("no MUSHROOM_HELMET_PLUMP seeds", exc.reason)

    def test_unknown_crop_refused(self):
        exc, _ = self._run(crop={"ok": False, "crop": "NOPE",
                                 "error": "no plant raw NOPE"})
        self.assertIsInstance(exc, actions._Fail)
        self.assertIn("unknown crop", exc.reason)

    def test_plot_not_built_refused(self):
        exc, _ = self._run(plot=_plot(stage=2))
        self.assertIsInstance(exc, actions._Fail)
        self.assertIn("still under construction", exc.reason)

    def test_not_a_farm_plot_refused(self):
        exc, _ = self._run(plot=_plot(ptype="Workshop"))
        self.assertIsInstance(exc, actions._Fail)
        self.assertIn("not a farm plot", exc.reason)

    def test_explicit_season_used(self):
        res, calls = self._run()
        self.assertTrue(res.ok)
        # Default season is the current season (spring = 0).
        self.assertEqual(calls["act"]["season"], 0)

    def test_poor_soil_noted_not_refused(self):
        res, _ = self._run()
        self.assertTrue(res.ok, res.reason)
        self.assertTrue(res.detail["poor_soil"])
        self.assertIn("poor soil", res.reason)


class TestProbeCropIndex(unittest.TestCase):
    # Source-level regression guard for the probe_crop off-by-one
    # (2026-11-27): probe_crop.lua once computed `index = i - 1`
    # on the ipairs index, on the (wrong) assumption that ipairs
    # over a DFHack vector is 1-based. It is 0-based — verified
    # live: ipairs gives 172 for MUSHROOM_HELMET_PLUMP, the same
    # as raws[172]; raws[171] is WALNUT. The -1 wrote WALNUT (a
    # tree, never farm-plantable) into every plot set through
    # set_farm_crop, which is why autumn/winter produced 0
    # PlantSeeds jobs and summer fetched the wrong seeds. The Lua
    # helper itself is exercised by test_farming_live.py; this
    # pins the line so the mistake cannot silently return.
    def test_index_is_the_ipairs_index(self):
        src = (Path(__file__).resolve().parent.parent / "src"
               / "dfagent_harness" / "lua" / "probe_crop.lua").read_text()
        # Match the indented code line (the comment above it
        # mentions the old form in backticks, so a bare
        # substring match would trip on the comment itself).
        self.assertIn("\n      index = i\n", src)
        self.assertNotIn("\n      index = i - 1", src)


if __name__ == "__main__":
    unittest.main()
