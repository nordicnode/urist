"""Unit tests for the attention section (offline, fabricated state).

The attention section is the "agent is told" surface: threats first,
then new arrivals, in plain words with class and position. These
tests use a stub detector (an object with an ``arrivals`` list) so
they never touch the game.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import attention as at  # noqa: E402


class StubDetector:
    def __init__(self, arrivals):
        self._arrivals = arrivals

    @property
    def arrivals(self):
        return list(self._arrivals)


def _state(tick=200000, citizens=((97, 97, 175),), hostiles=()):
    return {
        "status": {"year_tick": tick, "year": 125},
        "units": {
            "citizens": [{"id": i + 1, "pos": list(p)}
                         for i, p in enumerate(citizens)],
            "hostiles": [{"id": i + 9000, "race": race,
                          "pos": list(pos)}
                         for i, (race, pos) in enumerate(hostiles)],
        },
    }


def _arrival(uid, kind, race, pos, tick=200000, at_baseline=False,
             dist=None):
    data = {"unit_id": uid, "name": race.title(), "race": race,
            "kind": kind, "role": "visitor" if kind == "visitor"
            else ("pet" if kind == "livestock" else "wild"),
            "pos": list(pos), "at_baseline": at_baseline}
    if dist is not None:
        data["dist_nearest_citizen"] = dist
    return {"tick": tick, "year": 125, "data": data,
            "at_baseline": at_baseline}


class TestPrettifyRace(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(at.prettify_race("CRUNDLE"), "crundle")
        self.assertEqual(at.prettify_race("DEMON_14"), "demon")
        self.assertEqual(at.prettify_race("BIRD_TURKEY"), "turkey")
        self.assertEqual(at.prettify_race("WATER_BUFFALO"),
                         "water buffalo")
        self.assertEqual(at.prettify_race(None), "unknown creature")


class TestDescribeArrival(unittest.TestCase):
    def test_troll_in_caverns(self):
        text = at.describe_arrival(
            _arrival(5490, "visitor", "TROLL", (148, 65, 123),
                     dist=120)["data"], surface_z=175)
        self.assertIn("troll (visitor)", text)
        self.assertIn("deep underground, in the caverns", text)
        self.assertIn("(148, 65, z123)", text)
        self.assertIn("120 tiles from the nearest dwarf", text)
        self.assertIn("It just arrived.", text)

    def test_baseline_timing(self):
        text = at.describe_arrival(
            _arrival(5490, "visitor", "TROLL", (148, 65, 123),
                     at_baseline=True)["data"], surface_z=175)
        self.assertIn("It was already here when monitoring started.",
                      text)

    def test_surface_wildlife(self):
        text = at.describe_arrival(
            _arrival(7001, "wildlife", "CRUNDLE", (120, 88, 174),
                     dist=50)["data"], surface_z=175)
        self.assertIn("crundle (wild animal)", text)
        self.assertIn("on the surface", text)

    def test_no_surface_z_no_where_clause(self):
        text = at.describe_arrival(
            _arrival(7001, "wildlife", "CRUNDLE", (120, 88, 174),
                     dist=50)["data"])
        self.assertIn("(120, 88, z174)", text)
        self.assertNotIn("surface", text)


class TestBuildAttention(unittest.TestCase):
    def test_empty_when_nothing_to_say(self):
        items = at.build_attention(_state(), StubDetector([]))
        self.assertEqual(items, [])

    def test_threat_before_arrival(self):
        det = StubDetector([
            _arrival(5490, "visitor", "TROLL", (148, 65, 123),
                     dist=120)])
        state = _state(hostiles=(("GOBLIN", (100, 100, 175)),))
        items = at.build_attention(state, det, surface_z=175)
        self.assertEqual([it["kind"] for it in items],
                         ["threat", "new_arrival"])
        self.assertEqual(items[0]["priority"], 1)
        self.assertIn("HOSTILE", items[0]["text"])
        self.assertIn("(100, 100, z175)", items[0]["text"])
        self.assertIn("3 tiles from the nearest dwarf",
                      items[0]["text"])

    def test_visitor_outranks_far_wildlife(self):
        det = StubDetector([
            _arrival(7001, "wildlife", "ELK_BIRD", (150, 150, 178),
                     dist=80, tick=199000),
            _arrival(5490, "visitor", "TROLL", (148, 65, 123),
                     dist=120, tick=200000),
        ])
        items = at.build_attention(_state(), det, surface_z=175)
        self.assertEqual([it["priority"] for it in items], [2, 3])
        self.assertEqual(items[0]["unit_id"], 5490)

    def test_arrival_drops_out_after_window(self):
        det = StubDetector([
            _arrival(5490, "visitor", "TROLL", (148, 65, 123),
                     tick=198000)])
        # 200000 - 198000 = 2000 ticks > the 1200-tick window.
        items = at.build_attention(_state(tick=200000), det,
                                   surface_z=175)
        self.assertEqual(items, [])
        # Inside the window it is still there.
        det = StubDetector([
            _arrival(5490, "visitor", "TROLL", (148, 65, 123),
                     tick=199000)])
        items = at.build_attention(_state(tick=200000), det,
                                   surface_z=175)
        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
