"""Offline tests for the digging gap (digging.py): the hazard +
reachability checks, completion verification, and area-derived dig
sites. No game needed: the column reads are stubbed.

The live shape (verified 2026-11-26 on Erushtathtat): a dwarf
stands on the FLOOR at the surface (z175 at the fort centre); the
solid earth below is soil (z174) then stone. A down-stair / channel
is designated on the FLOOR; a regular dig / up-stair on a WALL.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import digging  # noqa: E402


def _col(x, y, strata):
    """A fake column.read_column return: {x, y, strata} where each
    stratum is {z0, z1, class}."""
    return {"x": x, "y": y, "strata": strata, "z_count": 197}


def _surface_col(x=97, y=97, below="soil"):
    """The fort-centre column: open sky above z175, floor at z175,
    soil at z174, stone below (or the given class at z174)."""
    return _col(x, y, [
        {"z0": 176, "z1": 196, "class": "air"},
        {"z0": 175, "z1": 175, "class": "floor"},
        {"z0": 174, "z1": 174, "class": below},
        {"z0": 0, "z1": 173, "class": "stone"},
    ])


def _areas():
    """Synthetic areas: a Surface of 2 blocks near the fort centre."""
    return {
        "areas": [
            {"id": "area_0001", "name": "Surface", "kind": "surface",
             "bbox": {"x0": 80, "y0": 80, "z0": 167,
                      "x1": 111, "y1": 111, "z1": 181},
             "blocks": 585},
            {"id": "area_0002", "name": "Cavern", "kind": "cavern",
             "bbox": {"x0": 0, "y0": 0, "z0": 19,
                      "x1": 31, "y1": 31, "z1": 113},
             "blocks": 1972},
        ],
        "surface_z": 175,
        "graph": {"area_0001": ["area_0002"],
                  "area_0002": ["area_0001"]},
    }


class TestCheckDigSite(unittest.TestCase):
    def setUp(self):
        self.client = mock.Mock()

    def _check(self, col, x=97, y=97, z=175, mode="down-stair",
               areas=None, surface_z=None):
        with mock.patch.object(digging.column_mod, "read_column",
                               return_value=col):
            return digging.check_dig_site(self.client, x, y, z, mode,
                                          areas=areas,
                                          surface_z=surface_z)

    def test_down_stair_on_surface_is_ok(self):
        out = self._check(_surface_col())
        self.assertTrue(out["ok"], out["reason"])
        self.assertTrue(out["reachable"])
        self.assertEqual(out["hazards"], [])

    def test_down_stair_over_magma_is_refused(self):
        col = _surface_col(below="soil")
        # Magma 2 levels below the floor (z173).
        col["strata"] = [
            {"z0": 176, "z1": 196, "class": "air"},
            {"z0": 175, "z1": 175, "class": "floor"},
            {"z0": 174, "z1": 174, "class": "soil"},
            {"z0": 173, "z1": 173, "class": "magma"},
            {"z0": 0, "z1": 172, "class": "stone"},
        ]
        out = self._check(col)
        self.assertFalse(out["ok"])
        self.assertIn("magma", out["reason"])
        self.assertTrue(any("magma" in h for h in out["hazards"]))

    def test_down_stair_over_aquifer_is_refused(self):
        col = _surface_col(below="aquifer")
        out = self._check(col)
        self.assertFalse(out["ok"])
        self.assertIn("aquifer", out["reason"])

    def test_down_stair_on_buried_soil_is_unreachable(self):
        # No open sky above: the floor is underground (a dug room
        # with no areas data to prove it is reachable).
        col = _col(97, 97, [
            {"z0": 175, "z1": 175, "class": "floor"},
            {"z0": 174, "z1": 174, "class": "soil"},
            {"z0": 0, "z1": 173, "class": "stone"},
        ])
        out = self._check(col)
        self.assertIsNone(out["reachable"])
        self.assertIn("unknown", out["reason"])

    def test_down_stair_buried_floor_under_floor_is_unknown(self):
        # A floor with another floor above it (a dug room under
        # the surface floor, a second story) is NOT on the surface:
        # the old _open_above counted 'floor' as open, so the tile
        # was declared reachable with no verification (found live
        # 2026-11-27 on the scratch fort's farm-room floor at
        # (82,82,49)). Without areas it is unknown, not reachable.
        col = _col(97, 97, [
            {"z0": 176, "z1": 176, "class": "floor"},
            {"z0": 175, "z1": 175, "class": "floor"},
            {"z0": 174, "z1": 174, "class": "soil"},
            {"z0": 0, "z1": 173, "class": "stone"},
        ])
        out = self._check(col)
        self.assertIsNone(out["reachable"])
        self.assertIn("unknown", out["reason"])

    def test_down_stair_in_reachable_area_is_ok(self):
        # Underground floor, but the block is in the Surface area
        # (a dug room connected to the fort).
        col = _col(97, 97, [
            {"z0": 175, "z1": 175, "class": "floor"},
            {"z0": 174, "z1": 174, "class": "soil"},
            {"z0": 0, "z1": 173, "class": "stone"},
        ])
        # Block (6, 6) is in the Surface area; (97, 97) is in it.
        out = self._check(col, areas=_areas())
        self.assertTrue(out["ok"], out["reason"])
        self.assertTrue(out["reachable"])

    def test_up_stair_under_water_is_refused(self):
        col = _col(97, 97, [
            {"z0": 176, "z1": 176, "class": "water"},
            {"z0": 175, "z1": 175, "class": "stone"},
            {"z0": 0, "z1": 174, "class": "stone"},
        ])
        out = self._check(col, z=175, mode="up-stair")
        self.assertFalse(out["ok"])
        self.assertIn("water", out["reason"])

    def test_column_failure_is_not_ok(self):
        with mock.patch.object(digging.column_mod, "read_column",
                               side_effect=ValueError("boom")):
            out = digging.check_dig_site(self.client, 97, 97, 175,
                                         "down-stair")
        self.assertFalse(out["ok"])
        self.assertIn("column read failed", out["reason"])

    def test_open_above_below_surface_z_is_not_surface(self):
        # Table 5 row 6: the surface_z parameter was never used —
        # open space above a tile far below the embark level (a
        # cavern floor, a dug room) was called "surface /
        # reachable" with no verification. With surface_z given,
        # such a tile falls through to the areas check; with no
        # areas it is unknown, not reachable.
        col = _col(97, 97, [
            {"z0": 151, "z1": 196, "class": "cavern space"},
            {"z0": 150, "z1": 150, "class": "floor"},
            {"z0": 149, "z1": 149, "class": "soil"},
            {"z0": 0, "z1": 148, "class": "stone"},
        ])
        out = self._check(col, z=150, surface_z=175)
        self.assertIsNone(out["reachable"])
        self.assertIn("unknown", out["reason"])
        # Without surface_z the old heuristic stands (open above
        # counts as surface) — backward compatible for callers
        # that cannot supply it.
        out = self._check(col, z=150)
        self.assertTrue(out["reachable"])

    def test_open_above_at_or_above_surface_z_is_surface(self):
        # A hilltop tile above the embark level is genuinely on
        # the surface, and so is the embark-level floor itself.
        col = _col(97, 97, [
            {"z0": 181, "z1": 196, "class": "air"},
            {"z0": 180, "z1": 180, "class": "floor"},
            {"z0": 179, "z1": 179, "class": "soil"},
            {"z0": 0, "z1": 178, "class": "stone"},
        ])
        out = self._check(col, z=180, surface_z=175)
        self.assertTrue(out["ok"], out["reason"])
        self.assertTrue(out["reachable"])
        out = self._check(_surface_col(), z=175, surface_z=175)
        self.assertTrue(out["reachable"])


class TestCheckDigBox(unittest.TestCase):
    def setUp(self):
        self.client = mock.Mock()

    def test_dig_box_needs_an_open_neighbour(self):
        # A wall tile with open space beside it at the same z.
        wall = _col(97, 97, [
            {"z0": 174, "z1": 174, "class": "stone"},
            {"z0": 0, "z1": 173, "class": "stone"},
        ])
        open_col = _col(98, 97, [
            {"z0": 174, "z1": 174, "class": "open space"},
            {"z0": 0, "z1": 173, "class": "stone"},
        ])

        def _read(client, x, y):
            return open_col if (x, y) == (98, 97) else wall

        with mock.patch.object(digging.column_mod, "read_column",
                               side_effect=_read):
            out = digging.check_dig_box(
                self.client, (97, 97, 174, 97, 97, 174), "dig")
        self.assertTrue(out["ok"], out["reason"])

    def test_dig_box_buried_wall_is_refused(self):
        # A wall tile with solid rock on all four sides: no dwarf
        # can stand beside it to dig it.
        wall = _col(97, 97, [
            {"z0": 174, "z1": 174, "class": "stone"},
            {"z0": 0, "z1": 173, "class": "stone"},
        ])
        with mock.patch.object(digging.column_mod, "read_column",
                               return_value=wall):
            out = digging.check_dig_box(
                self.client, (97, 97, 174, 97, 97, 174), "dig")
        self.assertFalse(out["ok"])
        self.assertFalse(out["reachable"])


class TestVerifyDig(unittest.TestCase):
    def setUp(self):
        self.client = mock.Mock()

    def _verify(self, dig_total, col, mode="down-stair"):
        def _helper(client, name, params, timeout=30.0):
            if name == "probe_dig.lua":
                return {"ok": True, "dig_total": dig_total}
            raise AssertionError(name)

        with mock.patch.object(digging, "_run_helper",
                               side_effect=_helper), \
                mock.patch.object(digging.column_mod, "read_column",
                                  return_value=col):
            return digging.verify_dig(
                self.client, (97, 97, 175, 97, 97, 175), mode)

    def test_complete_when_designation_gone_and_terrain_changed(self):
        # The floor at z175 is now a stair (not a solid floor).
        # NOTE: the class is 'passage', not 'stair' — column.lua
        # classifies every STAIR_* / RAMP shape as 'passage', and
        # 'stair' is a class the game never emits; the old fixture
        # passed only because the negative check accepted anything
        # not in the bad set (2026-11-27, C4).
        col = _col(97, 97, [
            {"z0": 175, "z1": 175, "class": "passage"},
            {"z0": 174, "z1": 174, "class": "soil"},
            {"z0": 0, "z1": 173, "class": "stone"},
        ])
        out = self._verify(0, col)
        self.assertTrue(out["complete"], out["reason"])

    def test_incomplete_when_designation_remains(self):
        col = _col(97, 97, [
            {"z0": 175, "z1": 175, "class": "passage"},
            {"z0": 174, "z1": 174, "class": "soil"},
            {"z0": 0, "z1": 173, "class": "stone"},
        ])
        out = self._verify(1, col)
        self.assertFalse(out["complete"])
        self.assertEqual(out["designations_left"], 1)

    def test_channel_air_is_dug_and_floor_is_not(self):
        # A channelled tile reads 'air'; a tile still reading
        # 'floor' is unchanged for channel mode.
        col = _col(97, 97, [
            {"z0": 175, "z1": 175, "class": "air"},
            {"z0": 0, "z1": 174, "class": "stone"},
        ])
        out = self._verify(0, col, mode="channel")
        self.assertTrue(out["complete"], out["reason"])
        col = _surface_col()
        out = self._verify(0, col, mode="channel")
        self.assertFalse(out["complete"])
        self.assertIn("still floor", out["reason"])
        self.assertIn("want air", out["reason"])

    def test_ramp_passage_is_dug(self):
        col = _col(97, 97, [
            {"z0": 175, "z1": 175, "class": "passage"},
            {"z0": 0, "z1": 174, "class": "stone"},
        ])
        out = self._verify(0, col, mode="ramp")
        self.assertTrue(out["complete"], out["reason"])

    def test_hidden_tile_is_not_dug(self):
        # C4: the old bad set listed the display label
        # 'hidden (unrevealed)', which column.lua never emits —
        # the raw class is 'hidden' (tile block nil) — so an
        # unrevealed tile passed as dug. It must fail in every
        # mode, as must a column with no stratum at z (None).
        col = _col(97, 97, [
            {"z0": 175, "z1": 175, "class": "hidden"},
            {"z0": 0, "z1": 174, "class": "stone"},
        ])
        for mode in ("dig", "down-stair", "channel", "ramp"):
            out = self._verify(0, col, mode=mode)
            self.assertFalse(out["complete"], mode)
            self.assertIn("still hidden", out["reason"], mode)
        col = _col(97, 97, [
            {"z0": 0, "z1": 174, "class": "stone"},
        ])
        out = self._verify(0, col, mode="dig")
        self.assertFalse(out["complete"])
        self.assertIn("no column", out["reason"])

    def test_water_is_not_dug(self):
        # The old negative check accepted water and magma as dug
        # (neither was in the bad set) — a dug tile that hit water
        # is a flood, not a completed dig.
        col = _col(97, 97, [
            {"z0": 175, "z1": 175, "class": "water"},
            {"z0": 0, "z1": 174, "class": "stone"},
        ])
        out = self._verify(0, col, mode="dig")
        self.assertFalse(out["complete"])
        self.assertIn("still water", out["reason"])

    def test_unknown_mode_raises(self):
        # A mode with no expected class must fail loudly, never
        # silently pass. ('clear' has no job type and is rejected
        # by dig_to_completion before verify_dig is reached.)
        with self.assertRaises(ValueError):
            self._verify(0, _surface_col(), mode="clear")

    def test_incomplete_when_terrain_unchanged(self):
        col = _surface_col()
        out = self._verify(0, col)
        self.assertFalse(out["complete"])
        self.assertIn("still floor", out["reason"])

    def test_dig_mode_floor_is_dug(self):
        # A plain dig mines a wall out and leaves a FLOOR tile — the
        # room dig on the region5 fort (2026-11-27) "failed" for
        # 600 s with its designations gone and its tiles reading
        # 'floor', because the old code listed 'floor' as undug for
        # every mode. For mode "dig", floor IS the dug state.
        col = _surface_col()
        out = self._verify(0, col, mode="dig")
        self.assertTrue(out["complete"], out["reason"])

    def test_dig_mode_soil_is_not_dug(self):
        col = _col(97, 97, [
            {"z0": 175, "z1": 175, "class": "soil"},
            {"z0": 0, "z1": 174, "class": "stone"},
        ])
        out = self._verify(0, col, mode="dig")
        self.assertFalse(out["complete"])
        self.assertIn("still soil", out["reason"])


class TestDeriveDigSite(unittest.TestCase):
    def test_derives_stairs_near_fort_centre(self):
        out = digging.derive_dig_site(_areas(), (97, 97), 175)
        x, y, z = out["stairs"]
        self.assertEqual(z, 175)
        # Inside the Surface bbox (x80..111, y80..111), at the fort
        # centre (it is already inside the bbox).
        self.assertEqual((x, y), (97, 97))
        x0, y0, z0, x1, y1, z1 = out["room"]
        self.assertEqual((z0, z1), (174, 174))
        self.assertEqual((x1 - x0, y1 - y0), (6, 6))
        # Table 5 row 6: the embark level rides with the site so
        # the dig action's site check can use it.
        self.assertEqual(out["surface_z"], 175)

    def test_no_surface_raises(self):
        with self.assertRaises(ValueError):
            digging.derive_dig_site({"areas": []}, (97, 97), 175)


class TestPlannerUsesDerivedSite(unittest.TestCase):
    def test_no_site_no_dig(self):
        from dfagent_harness.planner import decide
        state = {
            "status": {"date": "125-06-02", "year_tick": 169650,
                       "paused": True, "population": {"citizens": 10}},
            "stocks": {"drink_units": 9, "food_units": 25,
                       "wood_units": 211, "stone_units": 0},
            "units": {"citizens": [], "hostiles": []},
            "buildings": {"summary": [], "list": []},
            "jobs": {"list": []},
            "reports": {"announcements": []},
        }
        decisions = decide(state, dig_site=None)
        self.assertFalse(any(d.goal_key == "expansion:dig"
                             for d in decisions))

    def test_derived_site_digs_with_dig_to_completion(self):
        from dfagent_harness.planner import decide
        state = {
            "status": {"date": "125-06-02", "year_tick": 169650,
                       "paused": True, "population": {"citizens": 10}},
            "stocks": {"drink_units": 9, "food_units": 25,
                       "wood_units": 211, "stone_units": 0},
            "units": {"citizens": [], "hostiles": []},
            "buildings": {"summary": [], "list": []},
            "jobs": {"list": []},
            "reports": {"announcements": []},
        }
        site = {"stairs": (97, 97, 175),
                "room": (94, 94, 174, 100, 100, 174)}
        decisions = decide(state, dig_site=site)
        digs = [d for d in decisions
                if d.goal_key == "expansion:dig"]
        self.assertEqual(len(digs), 1)
        self.assertEqual(digs[0].action, "dig_to_completion")
        self.assertEqual(digs[0].kwargs["box"],
                         [97, 97, 175, 97, 97, 175])
        self.assertEqual(digs[0].kwargs["mode"], "down-stair")


class TestProbeDigStateJobWalk(unittest.TestCase):
    # Source-level regression guard for the probe_dig_state job
    # count (2026-11-27): probe_dig_state.lua once read the jobs
    # with `ipairs(df.global.world.jobs.list)`. world.jobs.list is
    # a LINKED list, not a vector — ipairs over it yields nothing,
    # so n_jobs was always 0 and dig_jobs always empty, and
    # verify_dig's job read was blind. The same ipairs pattern in
    # the scratch farm watch scripts read 0 PlantSeeds jobs that
    # were in fact present, which briefly misled the farm-mystery
    # investigation into a "building-jobs-list" theory that was
    # wrong (jobs.lua's while-walk sees them). The helper itself
    # is exercised by test_digging_live.py; this pins the walk so
    # the mistake cannot silently return.
    def test_jobs_are_walked_as_a_linked_list(self):
        src = (Path(__file__).resolve().parent.parent / "src"
               / "dfagent_harness" / "lua"
               / "probe_dig_state.lua").read_text()
        self.assertIn("local node = df.global.world.jobs.list", src)
        self.assertIn("while node ~= nil", src)
        self.assertIn("node = node.next", src)
        self.assertNotIn("ipairs(df.global.world.jobs.list)", src)
        # The worker comes from dfhack.job.getWorker (the pattern
        # probe_postings.lua / watch.lua use): the job struct has no
        # usable .worker field, so `j.worker` always read nil.
        self.assertIn("dfhack.job.getWorker", src)
        self.assertNotIn("j.worker", src)


class TestCheckDigBoxReachableUnknown(unittest.TestCase):
    """H5 (2026-11-27, external review): a box whose tiles only
    said 'unknown' (reachable None) was reported reachable True.
    The per-tile verdict must propagate."""

    def setUp(self):
        self.client = mock.Mock()

    def _box(self, col, box=(97, 97, 175, 97, 97, 175),
             mode="down-stair"):
        with mock.patch.object(digging.column_mod, "read_column",
                               return_value=col):
            return digging.check_dig_box(self.client, box, mode)

    def test_unknown_stays_unknown(self):
        # Buried floor, no open sky, no areas: the per-tile check
        # says reachable None (see
        # test_down_stair_on_buried_soil_is_unreachable).
        col = _col(97, 97, [
            {"z0": 175, "z1": 175, "class": "floor"},
            {"z0": 174, "z1": 174, "class": "soil"},
            {"z0": 0, "z1": 173, "class": "stone"},
        ])
        out = self._box(col)
        self.assertTrue(out["ok"], out["reason"])
        self.assertIsNone(out["reachable"])
        self.assertIn("unknown", out["reason"])

    def test_verified_stays_verified(self):
        out = self._box(_surface_col())
        self.assertTrue(out["ok"], out["reason"])
        self.assertTrue(out["reachable"])


class TestMultiZBoxes(unittest.TestCase):
    """H8 (2026-11-27, external review): the Lua helpers only
    touch z0, so a multi-z box designated one layer while the
    Python side verified and reported the whole box. Boxes are
    one layer; a multi-z box is refused at the boundary."""

    def test_check_dig_box_refuses_multi_z(self):
        out = digging.check_dig_box(
            mock.Mock(), (97, 97, 175, 98, 98, 176), "dig")
        self.assertFalse(out["ok"])
        self.assertIn("one layer", out["reason"])

    def test_verify_dig_refuses_multi_z(self):
        with self.assertRaises(ValueError):
            digging.verify_dig(
                mock.Mock(), (97, 97, 175, 98, 98, 176), "dig")


if __name__ == "__main__":
    unittest.main()
