"""Offline tests for the vertical column profile (column.py).

Pure Python over fabricated Lua strata — no game required. Live
behaviour (the real column at the fort centre, the /v1/column
route) is covered by tests/test_column_live.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import column as col  # noqa: E402


def _strata():
    # A synthetic column exercising every class: sky, soil, rock,
    # aquifer, rock, cavern, magma. (Not the live fort-centre
    # column — that one has soil at z174 and no aquifer or magma;
    # see test_column_live.py for the live truth.)
    return [
        {"class": "air", "z1": 196, "z0": 182, "max_depth": 0},
        {"class": "soil", "z1": 181, "z0": 176, "max_depth": 0},
        {"class": "stone", "z1": 175, "z0": 165, "max_depth": 0},
        {"class": "aquifer", "z1": 164, "z0": 164, "max_depth": 0},
        {"class": "stone", "z1": 163, "z0": 115, "max_depth": 0},
        {"class": "air", "z1": 114, "z0": 19, "max_depth": 0},
        {"class": "magma", "z1": 14, "z0": 0, "max_depth": 7},
    ]


def _col():
    return {"x": 97, "y": 97, "z_count": 197, "strata": _strata(),
            "cost_ms": 50}


class TestMergeStrata(unittest.TestCase):
    def test_open_runs_merge_and_rename(self):
        runs = col._merge_strata(_strata(), surface_z=175)
        classes = [r["class"] for r in runs]
        self.assertEqual(classes, [
            "open sky", "soil", "stone", "aquifer", "stone",
            "cavern space", "magma"])
        cavern = runs[5]
        self.assertEqual((cavern["z1"], cavern["z0"]), (114, 19))

    def test_short_open_run_below_surface_is_open_space(self):
        strata = [
            {"class": "air", "z1": 10, "z0": 9, "max_depth": 0},
            {"class": "air", "z1": 8, "z0": 7, "max_depth": 0},
            {"class": "stone", "z1": 6, "z0": 0, "max_depth": 0},
        ]
        runs = col._merge_strata(strata, surface_z=10)
        # Two adjacent air runs merge into one open-space run of
        # 4 levels — too short to be cavern space.
        self.assertEqual(runs[0]["class"], "open space")
        self.assertEqual((runs[0]["z1"], runs[0]["z0"]), (10, 7))

    def test_floor_passage_air_merge(self):
        strata = [
            {"class": "floor", "z1": 5, "z0": 5, "max_depth": 0},
            {"class": "passage", "z1": 4, "z0": 4, "max_depth": 0},
            {"class": "air", "z1": 3, "z0": 3, "max_depth": 0},
            {"class": "stone", "z1": 2, "z0": 0, "max_depth": 0},
        ]
        runs = col._merge_strata(strata, surface_z=10)
        self.assertEqual(runs[0]["class"], "open space")
        self.assertEqual((runs[0]["z1"], runs[0]["z0"]), (5, 3))


class TestDescribeColumn(unittest.TestCase):
    def test_profile_names_every_run(self):
        d = col.describe_column(_col(), surface_z=175)
        self.assertIn("At (97, 97), from the top down:", d["profile"])
        self.assertIn("open sky z196..z182", d["profile"])
        self.assertIn("soil z181..z176", d["profile"])
        self.assertIn("solid rock z175..z165", d["profile"])
        self.assertIn("light aquifer rock z164", d["profile"])
        self.assertIn("cavern space z114..z19", d["profile"])
        self.assertIn("magma z14..z0", d["profile"])

    def test_hazards_name_aquifer_and_magma(self):
        d = col.describe_column(_col(), surface_z=175)
        self.assertEqual(len(d["hazards"]), 2)
        self.assertIn("aquifer", d["hazards"][0])
        self.assertIn("leak water", d["hazards"][0])
        self.assertIn("Magma", d["hazards"][1])
        self.assertIn("breach lava", d["hazards"][1])

    def test_no_hazards_without_aquifer_or_magma(self):
        c = {"x": 0, "y": 0, "z_count": 10, "strata": [
            {"class": "air", "z1": 9, "z0": 8, "max_depth": 0},
            {"class": "soil", "z1": 7, "z0": 6, "max_depth": 0},
            {"class": "stone", "z1": 5, "z0": 0, "max_depth": 0}]}
        d = col.describe_column(c, surface_z=7)
        self.assertEqual(d["hazards"], [])


class TestDigDown(unittest.TestCase):
    def test_five_levels_from_the_fort_centre(self):
        # Digging down 5 from z175 digs z174..z170: solid rock.
        text = col.dig_down(_col(), 5, 175, 175)
        self.assertIn("solid rock for 5 levels (z174..z170)", text)
        self.assertIn("the aquifer is 6 levels further down (z164)",
                      text)
        self.assertIn("open cavern space starts 56 levels further "
                      "down (z114)", text)
        self.assertIn("magma starts 156 levels further down (z14)",
                      text)

    def test_one_level(self):
        text = col.dig_down(_col(), 1, 175, 175)
        self.assertIn("dig down 1 level", text)
        self.assertIn("solid rock for 1 level (z174)", text)

    def test_dig_into_the_aquifer(self):
        # Digging down 12 from z175 reaches z163: rock, then the
        # aquifer at z164 is inside the dug range.
        text = col.dig_down(_col(), 12, 175, 175)
        self.assertIn("aquifer rock for 1 level (z164)", text)


class TestGroundLevel(unittest.TestCase):
    def test_ground_is_one_above_the_top_solid(self):
        # A dwarf stands on the floor above the top solid tile,
        # not inside the solid ground itself: soil tops at z181,
        # so the ground (where a dwarf stands) is z182.
        self.assertEqual(col.ground_level(_strata(), 175), 182)

    def test_no_ground_without_solid(self):
        strata = [{"class": "air", "z1": 9, "z0": 0, "max_depth": 0}]
        self.assertIsNone(col.ground_level(strata, 10))


class TestColumnResponse(unittest.TestCase):
    def test_response_shape(self):
        out = col.column_response(_col(), 5, 175, surface_z=175,
                                  ms=12, lua_ms=50)
        self.assertIn("profile", out)
        self.assertIn("hazards", out)
        self.assertIn("dig_down", out)
        self.assertEqual(out["dig_down"]["levels"], 5)
        self.assertEqual(out["dig_down"]["from_z"], 175)
        self.assertIn("solid rock for 5 levels",
                      out["dig_down"]["text"])
        self.assertEqual(out["cost"]["ms"], 12)
        self.assertEqual(out["cost"]["lua_ms"], 50)
        self.assertGreater(out["cost"]["tokens"], 0)


if __name__ == "__main__":
    unittest.main()
