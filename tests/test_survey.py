"""Offline tests for the resource survey (design §5).

Fabricated raw survey.lua output on a 2x2x4-block map (32x32x4
tiles), fort at (5, 25, 3). The water L-shape is the discriminating
case for block-level nearest: its bbox contains the fort, so a
bbox-clamped "nearest" would wrongly read 0 tiles away; the real
nearest water tile is 10 tiles away.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import survey  # noqa: E402

# Block idx = (bz*yb + by)*xb + bx, xb = yb = 2.
RAW = {
    "x_blocks": 2, "y_blocks": 2, "z_count": 4,
    "x_count": 32, "y_count": 32,
    # L-shaped water body: (0,0,3) + (1,0,3) + (1,1,3) = 35 tiles.
    "water_blocks": [
        {"idx": 12, "tiles": 10, "max_depth": 7, "z": 3},
        {"idx": 13, "tiles": 20, "max_depth": 5, "z": 3},
        {"idx": 15, "tiles": 5, "max_depth": 7, "z": 3},
        # Separate small pool at (0,1,2), 5 tiles.
        {"idx": 10, "tiles": 5, "max_depth": 7, "z": 2},
    ],
    "water_total": 40,
    # One magma pool at (0,0,0).
    "magma_blocks": [{"idx": 0, "tiles": 100, "max_depth": 7, "z": 0}],
    "magma_total": 100,
    # Widespread mineral at (0,0,1) + one small vein at (1,1,1).
    "mineral_blocks": [
        {"idx": 4, "tiles": 6000, "z": 1},
        {"idx": 7, "tiles": 10, "z": 1},
    ],
    "mineral_total": 6010,
    "aquifer_total": 5,
    "aquifer_by_z": [0, 0, 5, 0],
    "soil_by_z": [0, 10, 20, 30],
    "stone_by_z": [100, 200, 300, 400],
    "plants": [
        {"species": "PECAN", "name": "pecan tree", "is_shrub": False,
         "count": 10, "x0": 0, "y0": 0, "z0": 3, "x1": 31, "y1": 31,
         "z1": 3, "nearest_pos": [6, 26, 3], "nearest_dist": 1},
        {"species": "KANIWA", "name": "kaniwa", "is_shrub": True,
         "count": 5, "x0": 0, "y0": 0, "z0": 3, "x1": 31, "y1": 31,
         "z1": 3, "nearest_pos": [5, 25, 3], "nearest_dist": 0},
    ],
    "scan_seconds": 1.5,
}

FORT = (5, 25, 3)


class TestDirectionWords(unittest.TestCase):
    def test_right_here(self):
        self.assertEqual(survey.direction_words(FORT, FORT), "right here")

    def test_singular(self):
        self.assertEqual(survey.direction_words((5, 25, 3), (4, 25, 3)),
                         "1 tile west")
        self.assertEqual(survey.direction_words((5, 25, 3), (5, 25, 2)),
                         "1 level below")

    def test_compound(self):
        self.assertEqual(
            survey.direction_words((5, 25, 3), (10, 20, 5)),
            "5 tiles east, 5 tiles north and 2 levels above")

    def test_chebyshev3d(self):
        self.assertEqual(survey.chebyshev3d((0, 0, 0), (3, 4, 2)), 4)


class TestBuildSurvey(unittest.TestCase):
    def setUp(self):
        self.s = survey.build_survey(
            RAW, fort=FORT, surface_blocks={10}, cavern_top_z=1,
            tick=1000)

    def test_water_bodies_flood_filled(self):
        self.assertEqual(len(self.s["water_bodies"]), 2)
        big = max(self.s["water_bodies"], key=lambda b: b["tiles"])
        self.assertEqual(big["tiles"], 35)
        self.assertEqual(big["blocks"], 3)

    def test_nearest_is_block_level_not_bbox(self):
        # The L-body's bbox contains the fort; a bbox clamp would say
        # 0 tiles away. The real nearest water tile is (5, 15, 3),
        # 10 tiles north of the fort.
        big = max(self.s["water_bodies"], key=lambda b: b["tiles"])
        self.assertEqual(big["nearest"]["pos"], [5, 15, 3])
        self.assertEqual(big["nearest"]["distance_tiles"], 10)

    def test_nearest_water_is_the_small_pool(self):
        line = self.s["summary"][0]
        self.assertIn("Nearest water: pool of 5 water tiles", line)
        self.assertIn("(5, 25, z2)", line)
        self.assertIn("1 tile away", line)

    def test_reachability_from_surface_blocks(self):
        by_tiles = {b["tiles"]: b for b in self.s["water_bodies"]}
        # The small pool's block is in the surface region.
        self.assertIs(by_tiles[5]["reachable"], True)
        # The L-body's blocks are not.
        self.assertIs(by_tiles[35]["reachable"], False)

    def test_mineral_widespread_vs_vein(self):
        names = {v["name"] for v in self.s["mineral_veins"]}
        self.assertIn("mineral-bearing rock (widespread, ore "
                      "unidentified)", names)
        self.assertIn("mineral vein (unidentified)", names)
        line = [ln for ln in self.s["summary"]
                if ln.startswith("Mineral:")][0]
        self.assertIn("starts right under the fort", line)
        self.assertIn("z1..z1", line)
        self.assertIn("identify it by mining a boulder", line)

    def test_magma_and_vertical(self):
        self.assertEqual(len(self.s["magma_bodies"]), 1)
        self.assertEqual(self.s["magma_bodies"][0]["name"],
                         "magma pool")
        self.assertEqual(self.s["vertical"]["depth_to_magma_levels"], 3)
        self.assertEqual(
            self.s["vertical"]["depth_to_first_cavern_levels"], 2)
        line = [ln for ln in self.s["summary"]
                if ln.startswith("Magma:")][0]
        self.assertIn("3 levels below the fort", line)

    def test_aquifer_levels(self):
        aq = self.s["aquifer"]
        self.assertEqual(aq["levels"], [{"z": 2, "blocks_showing": 5}])
        self.assertIn("light (per the embark warning)", aq["kind"])
        line = [ln for ln in self.s["summary"]
                if ln.startswith("Aquifer:")][0]
        self.assertIn("at z2..z2", line)

    def test_hazards_name_the_risk(self):
        hazards = " ".join(self.s["hazards"])
        self.assertIn("Magma pool 3 levels below the fort", hazards)
        self.assertIn("will breach lava", hazards)
        self.assertIn("Light aquifer at z2..z2", hazards)
        self.assertIn("First cavern 2 levels below", hazards)

    def test_plants_nearest_is_real(self):
        pecan = [p for p in self.s["plants"]
                 if p["species"] == "PECAN"][0]
        self.assertEqual(pecan["nearest"]["pos"], [6, 26, 3])
        self.assertEqual(pecan["nearest"]["distance_tiles"], 1)
        kaniwa = [p for p in self.s["plants"]
                  if p["species"] == "KANIWA"][0]
        self.assertEqual(kaniwa["nearest"]["distance_tiles"], 0)
        line = [ln for ln in self.s["summary"]
                if "gatherable shrubs" in ln][0]
        self.assertIn("kaniwa", line)
        self.assertIn("right here", line)

    def test_summary_covers_every_kind(self):
        joined = "\n".join(self.s["summary"])
        for head in ("Nearest water:", "Mineral:", "Magma:",
                     "Aquifer:", "Nearest gatherable shrubs:",
                     "Nearest trees:", "First cavern:"):
            self.assertIn(head, joined)

    def test_descriptions_are_plain_words(self):
        big = max(self.s["water_bodies"], key=lambda b: b["tiles"])
        self.assertIn("nearest point at (5, 15, z3)", big["description"])
        self.assertIn("10 tiles away", big["description"])


if __name__ == "__main__":
    unittest.main()
