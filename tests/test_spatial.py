"""Offline tests for the spatial model (world-model design §3).

The flood-fill, connectivity graph, labelling and path finding are
pure Python over a block scan, so they are tested here with synthetic
scans — no game required. Live behaviour (real slice rendering, the
real scan, area derivation on Erushtathtat) is covered by
tests/test_spatial_live.py.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import spatial  # noqa: E402


def _scan(xb, yb, zc, open_blocks, up_blocks=(), down_blocks=()):
    """Build a synthetic scan dict from block (bx, by, bz) tuples."""
    def idx(bx, by, bz):
        return (bz * yb + by) * xb + bx
    return {
        "x_blocks": xb, "y_blocks": yb, "z_count": zc,
        "x_count": xb * 16, "y_count": yb * 16,
        "total_blocks": xb * yb * zc,
        "open_blocks": len(open_blocks),
        "open": {idx(*b) for b in open_blocks},
        "up": {idx(*b) for b in up_blocks},
        "down": {idx(*b) for b in down_blocks},
        "scan_seconds": 0.0,
    }


def _state(buildings=(), citizens=(), tick=1000):
    return {
        "status": {"year_tick": tick},
        "buildings": {"list": list(buildings)},
        "units": {"citizens": list(citizens)},
        "map": {"size_tiles": [48, 48], "z_levels": 3},
    }


class TestFloodRegions(unittest.TestCase):
    def test_horizontal_neighbours_merge(self):
        scan = _scan(3, 3, 1, [(0, 0, 0), (1, 0, 0), (0, 1, 0)])
        regions = spatial._flood_regions(scan)
        self.assertEqual(len(regions), 1)
        self.assertEqual(len(regions[0]), 3)

    def test_separate_blocks_stay_separate(self):
        scan = _scan(3, 3, 1, [(0, 0, 0), (2, 2, 0)])
        regions = spatial._flood_regions(scan)
        self.assertEqual(len(regions), 2)

    def test_vertical_step_needs_a_stair(self):
        # Two open blocks stacked, no stair: NOT connected (a floor
        # above a floor is a ceiling, not a passage).
        scan = _scan(3, 3, 2, [(1, 1, 0), (1, 1, 1)])
        regions = spatial._flood_regions(scan)
        self.assertEqual(len(regions), 2)

    def test_vertical_step_with_up_stair_connects(self):
        scan = _scan(3, 3, 2, [(1, 1, 0), (1, 1, 1)],
                     up_blocks=[(1, 1, 0)])
        regions = spatial._flood_regions(scan)
        self.assertEqual(len(regions), 1)

    def test_vertical_step_with_down_stair_connects(self):
        scan = _scan(3, 3, 2, [(1, 1, 0), (1, 1, 1)],
                     down_blocks=[(1, 1, 1)])
        regions = spatial._flood_regions(scan)
        self.assertEqual(len(regions), 1)


class TestDeriveAreas(unittest.TestCase):
    def test_stockpile_is_authoritative(self):
        # A stockpile building in an open region labels it stockpile.
        scan = _scan(3, 3, 1, [(0, 0, 0), (1, 0, 0)])
        buildings = [{"id": 1, "type": "Stockpile", "type_id": 0,
                      "x1": 0, "y1": 0, "x2": 5, "y2": 5, "z": 0,
                      "center": [2, 2, 0]}]
        out = spatial.derive_areas(_state(buildings), scan)
        self.assertEqual(len(out["areas"]), 1)
        a = out["areas"][0]
        self.assertEqual(a["kind"], "stockpile")
        self.assertEqual(a["confidence"], 1.0)
        self.assertIn("stockpile x1", a["contents"]["buildings"])

    def test_bed_and_door_is_a_bedroom(self):
        scan = _scan(3, 3, 1, [(0, 0, 0), (1, 0, 0)])
        buildings = [
            {"id": 1, "type": "Bed", "type_id": 0,
             "x1": 0, "y1": 0, "x2": 0, "y2": 0, "z": 0,
             "center": [0, 0, 0]},
            {"id": 2, "type": "Door", "type_id": 0,
             "x1": 1, "y1": 0, "x2": 1, "y2": 0, "z": 0,
             "center": [1, 0, 0]},
        ]
        out = spatial.derive_areas(_state(buildings), scan)
        a = out["areas"][0]
        self.assertEqual(a["kind"], "room")
        self.assertEqual(a["name"], "Bedroom")

    def test_tables_and_chairs_is_a_dining_hall(self):
        scan = _scan(3, 3, 1, [(0, 0, 0)])
        buildings = [
            {"id": 1, "type": "Table", "type_id": 0,
             "x1": 0, "y1": 0, "x2": 0, "y2": 0, "z": 0,
             "center": [0, 0, 0]},
            {"id": 2, "type": "Chair", "type_id": 0,
             "x1": 1, "y1": 0, "x2": 1, "y2": 0, "z": 0,
             "center": [1, 0, 0]},
        ]
        out = spatial.derive_areas(_state(buildings), scan)
        self.assertEqual(out["areas"][0]["name"], "Dining Hall")

    def test_large_underground_region_is_a_cavern(self):
        # 10 open blocks below the surface, no buildings: cavern.
        blocks = [(x, y, 0) for x in range(5) for y in range(2)]
        scan = _scan(5, 5, 3, blocks)
        citizens = [{"pos": [40, 40, 2]}]
        out = spatial.derive_areas(_state(citizens=citizens), scan)
        kinds = {a["kind"] for a in out["areas"]}
        self.assertIn("cavern", kinds)
        cavern = [a for a in out["areas"]
                  if a["kind"] == "cavern"][0]
        self.assertEqual(cavern["blocks"], 10)

    def test_surface_region_holds_the_fort_centre(self):
        # The region holding a citizen is the surface, even when its
        # z-range dips below the citizens' lowest z (hills).
        scan = _scan(3, 3, 3, [(0, 0, 1), (1, 0, 1), (1, 0, 2)])
        citizens = [{"pos": [5, 5, 1]}]
        out = spatial.derive_areas(_state(citizens=citizens), scan)
        self.assertEqual(len(out["areas"]), 1)
        self.assertEqual(out["areas"][0]["kind"], "surface")

    def test_graph_links_adjacent_regions(self):
        # Two regions side by side, connected by a shared edge, but
        # separated into two regions by a closed block between them
        # that is open on one z only — instead, build two regions
        # that touch diagonally (no edge) vs side by side (edge).
        # Side by side regions ARE one region when both open, so the
        # graph edge arises between regions on different z-levels
        # linked by a stair: region A (z=0) and region B (z=1) touch
        # through the stair block.
        scan = _scan(3, 3, 2,
                     [(0, 0, 0), (1, 0, 0), (1, 0, 1), (2, 0, 1)],
                     up_blocks=[(1, 0, 0)])
        out = spatial.derive_areas(_state(), scan)
        # (1,0,0) has the up-stair, so all four blocks are ONE region.
        self.assertEqual(len(out["areas"]), 1)
        # Now without the stair the two z-levels are separate regions
        # with no edge between them (no passage).
        scan2 = _scan(3, 3, 2,
                      [(0, 0, 0), (1, 0, 0), (1, 0, 1), (2, 0, 1)])
        out2 = spatial.derive_areas(_state(), scan2)
        self.assertEqual(len(out2["areas"]), 2)
        graph = out2["graph"]
        self.assertEqual(graph[out2["areas"][0]["id"]], [])
        self.assertEqual(graph[out2["areas"][1]["id"]], [])

    def test_single_block_pockets_are_dropped(self):
        scan = _scan(4, 4, 1, [(0, 0, 0), (3, 3, 0)])
        out = spatial.derive_areas(_state(), scan)
        self.assertEqual(out["areas"], [])


class TestFindPath(unittest.TestCase):
    def test_path_through_the_graph(self):
        graph = {"a": ["b"], "b": ["a", "c"], "c": ["b"]}
        self.assertEqual(spatial.find_path(graph, "a", "c"),
                         ["a", "b", "c"])

    def test_no_path_returns_none(self):
        graph = {"a": [], "b": []}
        self.assertIsNone(spatial.find_path(graph, "a", "b"))

    def test_same_area(self):
        graph = {"a": ["b"]}
        self.assertEqual(spatial.find_path(graph, "a", "a"), ["a"])

    def test_unknown_area(self):
        graph = {"a": ["b"]}
        self.assertIsNone(spatial.find_path(graph, "a", "zzz"))


class TestLabeledGrid(unittest.TestCase):
    def test_rulers_label_every_column_and_row(self):
        labeled = spatial._labeled_grid([".#T", "..*", "T.."], 77, 175)
        # Two header lines (tens, then ones of x) + one row per y.
        self.assertEqual(len(labeled), 5)
        self.assertEqual(labeled[0], "    777")
        self.assertEqual(labeled[1], "    789")
        self.assertEqual(labeled[2], "175 .#T")
        self.assertEqual(labeled[4], "177 T..")

    def test_rulers_cross_a_hundred(self):
        labeled = spatial._labeled_grid([".."], 99, 175)
        self.assertEqual(labeled[0], "    90")
        self.assertEqual(labeled[1], "    90")


class TestAdjacentText(unittest.TestCase):
    def test_below_with_water_warns(self):
        text = spatial._adjacent_text(
            "Below", {"z": 174, "open": 60, "solid": 1520,
                      "water": 42, "magma": 0, "hidden": 18})
        self.assertIn("Below (z174):", text)
        self.assertIn("1520 solid rock", text)
        self.assertIn("42 water tiles", text)
        self.assertIn("Water sits directly below", text)
        self.assertIn("will let water in", text)

    def test_below_with_magma_warns(self):
        text = spatial._adjacent_text(
            "Below", {"z": 13, "open": 0, "solid": 0,
                      "water": 0, "magma": 400, "hidden": 0})
        self.assertIn("Magma sits directly below", text)
        self.assertIn("will breach lava", text)

    def test_open_below_notes_the_drop(self):
        text = spatial._adjacent_text(
            "Below", {"z": 100, "open": 500, "solid": 0,
                      "water": 0, "magma": 0, "hidden": 0})
        self.assertIn("Open space directly below", text)

    def test_out_of_range_is_honest(self):
        self.assertIn("the map ends here",
                      spatial._adjacent_text("Above", None))


def _area(aid="area_0001", name="Surface", kind="surface",
          bbox=None, purpose="the embark surface, open ground",
          contents=None, connections=(), blocks=586, conf=0.9):
    return {
        "id": aid, "name": name, "kind": kind,
        "bbox": bbox or {"x0": 80, "y0": 80, "z0": 175,
                         "x1": 111, "y1": 111, "z1": 181},
        "purpose": purpose, "contents": contents or {},
        "connections": list(connections), "blocks": blocks,
        "confidence": conf, "derived_at_tick": 1000, "stale": False,
    }


def _survey():
    return {
        "vertical": {"fort_z": 175,
                     "depth_to_magma_levels": 161,
                     "magma_top_z": 14,
                     "depth_to_first_cavern_levels": 62,
                     "first_cavern_top_z": 113},
        "aquifer": {"levels": [{"z": 164, "blocks_showing": 7}],
                    "total_blocks": 7},
    }


class TestDescribeArea(unittest.TestCase):
    def test_surface_description(self):
        areas = [_area()]
        text = spatial.describe_area(
            areas[0], areas, {"area_0001": []},
            survey=_survey(), fort_centre=(97, 97, 175))
        self.assertIn("The Surface (surface):", text)
        self.assertIn("x80..x111, y80..y111, z175..z181", text)
        self.assertIn("586 blocks", text)
        self.assertIn("It holds the fort centre.", text)
        self.assertIn("This is where the fort starts.", text)
        self.assertIn("Above it is open sky.", text)
        self.assertIn("first cavern starts 62 levels below", text)
        self.assertIn("aquifer layer sits at z164, 11 levels below",
                      text)
        self.assertIn("magma sea (top at z14)", text)

    def test_cavern_description_with_no_path(self):
        surface = _area()
        cavern = _area("area_0002", "Cavern", "cavern",
                       {"x0": 0, "y0": 0, "z0": 19,
                        "x1": 191, "y1": 191, "z1": 113},
                       "open underground space, unclaimed",
                       blocks=1972, conf=0.6)
        areas = [surface, cavern]
        text = spatial.describe_area(
            cavern, areas, {"area_0001": [], "area_0002": []},
            survey=_survey(), fort_centre=(97, 97, 175))
        self.assertIn("The Cavern (cavern):", text)
        self.assertIn("From the Surface: no path", text)
        self.assertIn("sealed off by solid rock", text)
        self.assertIn("Below it is solid rock for 5 levels, then "
                      "the magma sea", text)
        self.assertIn("derived from the buildings and shape "
                      "(confidence 0.6)", text)

    def test_path_from_surface_is_named(self):
        surface = _area()
        stair = _area("area_0002", "Stairwell", "stairwell",
                      {"x0": 96, "y0": 96, "z0": 170,
                       "x1": 97, "y1": 97, "z1": 175},
                      "vertical passage between levels",
                      blocks=4, conf=0.6)
        cavern = _area("area_0003", "Cavern", "cavern",
                       {"x0": 0, "y0": 0, "z0": 19,
                        "x1": 191, "y1": 191, "z1": 113},
                       "open underground space, unclaimed",
                       blocks=1972, conf=0.6)
        areas = [surface, stair, cavern]
        graph = {"area_0001": ["area_0002"],
                 "area_0002": ["area_0001", "area_0003"],
                 "area_0003": ["area_0002"]}
        text = spatial.describe_area(cavern, areas, graph)
        self.assertIn("From the Surface: Surface → Stairwell → "
                      "Cavern.", text)

    def test_area_with_buildings_and_units(self):
        hall = _area("area_0002", "Dining Hall", "room",
                     {"x0": 96, "y0": 90, "z0": 174,
                      "x1": 100, "y1": 94, "z1": 174},
                     "eating and socialising; tables and chairs",
                     {"buildings": ["table x4", "chair x4"],
                      "units_present": 3},
                     connections=["area_0001"], blocks=2, conf=0.7)
        text = spatial.describe_area(hall, [_area(), hall],
                                     {"area_0001": ["area_0002"],
                                      "area_0002": ["area_0001"]},
                                     fort_centre=(97, 97, 175))
        self.assertIn("buildings: table x4, chair x4", text)
        self.assertIn("3 dwarfs inside", text)


class TestRenderOverview(unittest.TestCase):
    def _scan(self):
        # 2x2 blocks, 48 z-levels: open at (0,0,32) and (1,0,32)
        # (the surface, tile z 32) and open at (0,0,0) (a cavern
        # block, tile z 0), the rest solid. A DF map block is
        # 16x16x1, so bz here is a TILE z, not a 16-level band:
        # z_count 48 -> 3 band rows (z32..z47, z16..z31, z0..z15).
        def idx(bx, by, bz):
            return (bz * 2 + by) * 2 + bx
        return {
            "x_blocks": 2, "y_blocks": 2, "z_count": 48,
            "x_count": 32, "y_count": 32, "total_blocks": 192,
            "open_blocks": 3,
            "open": {idx(0, 0, 32), idx(1, 0, 32), idx(0, 0, 0)},
            "up": set(), "down": set(), "scan_seconds": 0.0,
        }

    def test_cross_section_and_top_down(self):
        out = spatial.render_overview(self._scan(), survey=None,
                                      fort=(8, 8, 32))
        # Cross-section: 3 band rows (z32..z47, z16..z31, z0..z15),
        # top first. The fort is at (8, 8, 32): band 2, x-block 0.
        # Band 2 is the surface (open at both x-blocks) -> 'F.';
        # band 0 is the cavern (open at x-block 0 only) -> '.#'.
        self.assertEqual(len(out["cross_section"]), 3)
        self.assertTrue(out["cross_section"][0].startswith("z32..z47"))
        self.assertTrue(out["cross_section"][0].endswith("F."))
        self.assertTrue(out["cross_section"][2].startswith("z0..z15"))
        self.assertTrue(out["cross_section"][2].endswith(".#"))
        self.assertEqual(len(out["top_down"]), 2)
        self.assertIn("F", out["top_down"][0])
        self.assertIn("fort's level (z32)", out["summary"])
        self.assertGreater(out["cost"]["tokens"], 0)

    def test_water_and_magma_blocks_marked(self):
        scan = self._scan()
        survey = {"water_block_indices": [0],  # (0,0,0)
                  "magma_block_indices": [1]}  # (1,0,0)
        out = spatial.render_overview(scan, survey=survey,
                                      fort=(8, 8, 32))
        # Bottom cross-section row (z0..z15): water at (0,0,0),
        # magma at (1,0,0).
        self.assertIn("~!", out["cross_section"][2])


class TestRleDecode(unittest.TestCase):
    def test_round_trip(self):
        # bits: 0,0,1,1,1,0,1 (runs: 2 zeros, 3 ones, 1 zero, 1 one)
        runs = [2, 3, 1, 1]
        self.assertEqual(spatial._rle_decode(runs, 7), {2, 3, 4, 6})

    def test_leading_ones(self):
        # bits start with 1: the first run (zeros) is 0.
        runs = [0, 2, 1]
        self.assertEqual(spatial._rle_decode(runs, 3), {0, 1})

    def test_bad_length_raises(self):
        with self.assertRaises(ValueError):
            spatial._rle_decode([2, 2], 7)


if __name__ == "__main__":
    unittest.main()
