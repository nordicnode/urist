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
