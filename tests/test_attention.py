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

    def test_arrival_states_level_gap(self):
        # Fix 6 (2026-11-27): the model could not tell a threat
        # 174 levels down from one 3 levels down — the attention
        # said "deep underground, in the caverns" with no level
        # gap. A demon at z1 is 174 levels below the fort (z175).
        text = at.describe_arrival(
            _arrival(7002, "wildlife", "DEMON", (50, 50, 1),
                     dist=10)["data"], surface_z=175)
        self.assertIn("174 levels below the fort", text)
        # A troll at z123 is 52 levels below.
        text = at.describe_arrival(
            _arrival(5490, "visitor", "TROLL", (148, 65, 123),
                     dist=120)["data"], surface_z=175)
        self.assertIn("52 levels below the fort", text)

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


class TestDescribeUnit(unittest.TestCase):
    def test_citizen_idle_with_state(self):
        text = at.describe_unit({
            "id": 2, "name": "Udil Sodelkosh", "profession": "Miner",
            "pos": [97, 91, 175], "idle": True,
            "counters": {"hunger": 25000, "thirst": 12000,
                         "sleepiness": 10000},
            "stress": {"category": 4}, "wound_count": 0},
            surface_z=175)
        self.assertIn("Udil Sodelkosh, a citizen dwarf (miner)",
                      text)
        self.assertIn("on the surface, at (97, 91, z175)", text)
        self.assertIn("idle", text)
        self.assertIn("Getting hungry", text)
        self.assertIn("getting thirsty", text)

    def test_citizen_working_and_wounded(self):
        text = at.describe_unit({
            "id": 3, "name": "Mistem", "profession": "Woodcutter",
            "pos": [100, 93, 175], "idle": False,
            "job": {"type": "FellTree", "id": 10,
                    "pos": [100, 93, 175]},
            "counters": {"hunger": 5000, "thirst": 5000,
                         "sleepiness": 5000},
            "stress": {"category": 0}, "wound_count": 2},
            surface_z=175)
        self.assertIn("cutting down a tree", text)
        self.assertIn("Highly stressed", text)
        self.assertIn("wounded (2 wounds)", text)

    def test_citizen_very_thirsty(self):
        text = at.describe_unit({
            "id": 4, "name": "Aban", "profession": "Brewer",
            "pos": [97, 97, 175], "idle": True,
            "counters": {"hunger": 1000, "thirst": 21000,
                         "sleepiness": 1000},
            "stress": {"category": 5}, "wound_count": 0},
            surface_z=175)
        self.assertIn("Very thirsty", text)

    def test_wildlife_compact(self):
        text = at.describe_unit({
            "id": 7001, "race": "CRUNDLE", "pos": [38, 176, 124],
            "kind": "wildlife", "dist_nearest_citizen": 120},
            surface_z=175)
        self.assertIn("a crundle (wild animal)", text)
        self.assertIn("deep underground, in the caverns", text)
        self.assertIn("120 tiles from the nearest dwarf", text)

    def test_visitor_and_livestock(self):
        text = at.describe_unit({
            "id": 5490, "race": "TROLL", "pos": [148, 65, 123],
            "kind": "visitor", "role": "visitor"},
            surface_z=175)
        self.assertIn("a troll (visitor)", text)
        text = at.describe_unit({
            "id": 8001, "race": "CAT", "pos": [97, 97, 175],
            "kind": "livestock", "role": "pet"},
            surface_z=175)
        self.assertIn("a cat (pet)", text)

    def test_hostile(self):
        text = at.describe_unit({
            "id": 9001, "race": "GOBLIN", "pos": [100, 100, 175],
            "kind": "hostile"}, surface_z=175)
        self.assertIn("(HOSTILE)", text)


class TestBuildAttention(unittest.TestCase):
    def test_empty_when_nothing_to_say(self):
        items = at.build_attention(_state(), StubDetector([]))
        self.assertEqual(items, [])

    def test_low_drink_item_carries_briefing_with_wiki(self):
        # The low-drink item is the one the model faces every run —
        # it must carry the briefing (with wiki refs) so the
        # snapshot can teach the model how brewing works. Before
        # 2026-11-27 the low items had no briefing at all, and the
        # assembler dropped the field anyway.
        state = _state()
        state["stocks"] = {"drink_units": 9, "food_units": 30}
        items = at.build_attention(state, StubDetector([]))
        kinds = [it["kind"] for it in items]
        self.assertIn("low_drink", kinds)
        item = items[kinds.index("low_drink")]
        briefing = item.get("briefing")
        self.assertIsNotNone(briefing)
        self.assertIn("Still", briefing.get("what", ""))
        self.assertGreater(len(briefing.get("wiki") or []), 0)
        slugs = [w["slug"] for w in briefing["wiki"]]
        self.assertIn("still", slugs)

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

    def test_far_below_wildlife_demoted(self):
        # Fix 6 (2026-11-27): dist_nearest_citizen is a 2D
        # Chebyshev distance (+10 when z differs), so a demon at
        # z1 directly below a dwarf scores dist 10 and was flagged
        # P2 — the same priority as a real near-surface threat.
        # Far below the fort (> 40 levels) demotes a wildlife
        # arrival to P3. Visitors are never demoted.
        det = StubDetector([
            _arrival(7002, "wildlife", "DEMON", (50, 50, 1),
                     dist=10, tick=200000)])
        items = at.build_attention(_state(), det, surface_z=175)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["priority"], 3)
        self.assertIn("174 levels below the fort",
                      items[0]["text"])


if __name__ == "__main__":
    unittest.main()
