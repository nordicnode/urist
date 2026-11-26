"""Offline tests for the Context Assembler + token accountant
(design §6, §7). No game needed: the assembler works from a state
dict, a Store, and a detector stub.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import assembler  # noqa: E402
from dfagent_harness.assembler import (TokenAccountant, assemble,  # noqa: E402
                                       sample_daily, suggest)
from dfagent_harness.store import Store, TICKS_PER_DAY  # noqa: E402


def _citizen(i, **over):
    c = {"id": 100 + i, "name": f"Dwarf {i}",
         "profession": "Miner", "sex": "male", "age": 40,
         "pos": [97, 97, 175], "idle": False,
         # The live collect emits job as a dict {id, type, pos}
         # (or None when idle).
         "job": {"id": 140 + i, "type": "Mine",
                 "pos": [97, 97, 175]},
         "mood": None,
         "stress": {"level": 0, "category": 3},
         "counters": {"hunger": 1000, "thirst": 1000,
                      "sleepiness": 1000},
         "needs": [], "skills": [], "labors": [], "wounds": []}
    c.update(over)
    return c


def _state(n_citizens=10, **over):
    citizens = [_citizen(i) for i in range(n_citizens)]
    s = {
        "meta": {"schema_version": 1, "fps": 50.0},
        "errors": [],
        "status": {"date": "125-06-02", "year": 125,
                   "year_tick": 72000, "paused": True,
                   "focus": "dwarfmode/Default",
                   "population": {"citizens": n_citizens,
                                  "animals": 6},
                   "fort_name": "Erushtathtat"},
        "stocks": {"drink_units": 9, "food_units": 25,
                   "wood_units": 211, "stone_units": 500,
                   "seeds_units": 10, "barrels": 5,
                   "by_material": [
                       {"material": "wood", "units": 211},
                       {"material": "stone", "units": 500}]},
        "units": {"citizens": citizens, "hostiles": [],
                  "wildlife": [], "visitors": [], "livestock": [],
                  "total_active_units": n_citizens + 6,
                  # The live collect emits per-race counts as a list
                  # of {race, count} records, not a dict.
                  "wildlife_by_race": [{"race": "CRUNDLE", "count": 3}],
                  "livestock_by_race": [{"race": "CAT", "count": 2}],
                  "reconciled": True},
        "buildings": {"summary": [
            {"type": "Workshop", "count": 2},
            {"type": "Bed", "count": 10}],
            "list": [{"id": 1, "type": "Workshop"}]},
        "jobs": {"list": [
            {"type": "Mine", "id": 1},
            {"type": "FellTree", "id": 2}],
            "manager_orders": []},
        "reports": {"announcements": [
            "Udil has begun a mysterious construction!",
            "A migrant has arrived.",
            "It is now Summer."],
            "combat": []},
        "items": {"by_type": []},
    }
    s.update(over)
    return s


class _Detector:
    """Stub for the poll diff's arrival record."""

    def __init__(self, arrivals=None):
        self.arrivals = arrivals or []


class TestAssemble(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "world.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_snapshot_has_all_sections(self):
        snap = assemble(_state(), store=self.store,
                        detector=_Detector())
        for name in ("header", "attention", "goals", "status",
                     "stocks", "units", "entities", "buildings",
                     "jobs", "reports", "areas", "events",
                     "history"):
            self.assertIn(name, snap["sections"], name)
        self.assertEqual(snap["tick"], 72000)
        self.assertGreater(snap["tokens"], 0)
        self.assertIn("Erushtathtat", snap["text"])
        self.assertIn("125-06-02", snap["text"])

    def test_areas_cache_dict_accepted(self):
        # Regression (2026-11-26): the server's spatial cache holds
        # the full derivation dict (areas + graph + surface_blocks +
        # ...), and _snapshot passed that dict to assemble(), whose
        # _areas sliced it as a list — KeyError slice(None, 15,
        # None). The assembler now unwraps the dict, and the call
        # sites pass the list; either shape must work.
        area = {"id": "area_0001", "name": "Surface",
                "kind": "surface", "blocks": 586,
                "bbox": {"x0": 0, "y0": 0, "z0": 175,
                         "x1": 191, "y1": 191, "z1": 175}}
        cache_dict = {"areas": [area], "graph": {},
                      "surface_blocks": [1, 2],
                      "surface_z": 175, "summary": "49 areas"}
        # A fresh store per shape: the second assemble with the
        # same state would diff the areas section to "unchanged"
        # (identical text), hiding the area name.
        for areas_arg in ([area], cache_dict):
            tmp = tempfile.TemporaryDirectory()
            store = Store(Path(tmp.name) / "world.db")
            try:
                snap = assemble(_state(), store=store,
                                detector=_Detector(), areas=areas_arg)
                self.assertIn("Surface", snap["text"])
                self.assertIn("areas", snap["sections"])
            finally:
                store.close()
                tmp.cleanup()

    def test_snapshot_under_target(self):
        snap = assemble(_state(), store=self.store,
                        detector=_Detector())
        self.assertLessEqual(snap["tokens"],
                             assembler.TARGET_TOKENS)
        self.assertEqual(snap["cuts"], [])

    def test_scaling_100_citizens_still_under_target(self):
        # The scaling invariant: no section grows linearly with
        # population. 100 healthy citizens must still fit.
        snap = assemble(_state(n_citizens=100), store=self.store,
                        detector=_Detector())
        self.assertLessEqual(snap["tokens"],
                             assembler.TARGET_TOKENS)
        self.assertIn("100 citizens", snap["text"])

    def test_diffing_unchanged_sections(self):
        state = _state()
        first = assemble(state, store=self.store,
                         detector=_Detector())
        self.assertNotIn("unchanged", first["text"])
        second = assemble(state, store=self.store,
                          detector=_Detector())
        # Every section except attention renders as a one-liner.
        for name in ("header", "status", "stocks", "units",
                     "entities", "buildings", "jobs", "reports",
                     "areas", "events", "history", "goals"):
            self.assertIn(f"{name}: unchanged",
                          second["sections"].get(name, ""), name)
        # Attention is never diffed away.
        self.assertNotIn("unchanged",
                         second["sections"]["attention"])
        # The diffed snapshot is smaller (the one-liners cost
        # less than the full sections).
        self.assertLess(second["tokens"], first["tokens"])

    def test_diffing_changed_section_renders_in_full(self):
        state = _state()
        assemble(state, store=self.store, detector=_Detector())
        state2 = _state()
        state2["stocks"] = dict(state2["stocks"])
        state2["stocks"]["drink_units"] = 7
        second = assemble(state2, store=self.store,
                          detector=_Detector())
        # Stocks changed: rendered in full, not a one-liner.
        self.assertIn("drink 7", second["sections"]["stocks"])
        self.assertNotIn("unchanged",
                         second["sections"]["stocks"])
        # Everything else is unchanged.
        self.assertIn("unchanged",
                      second["sections"]["units"])

    def test_unavailable_section_is_marked_not_dropped(self):
        state = _state()
        del state["buildings"]
        snap = assemble(state, store=self.store,
                        detector=_Detector())
        self.assertIn("Buildings: unavailable",
                      snap["sections"]["buildings"])
        # A missing section is never read as zero.
        self.assertNotIn("0 buildings", snap["text"])

    def test_stocks_burn_rate_from_trends(self):
        # Drink falls 2/day for 7 days in the Store.
        for i, v in enumerate([23, 21, 19, 17, 15, 13, 11, 9]):
            self.store.sample_trend(i * TICKS_PER_DAY, "drink", v)
        state = _state()
        state["status"] = dict(state["status"])
        state["status"]["year_tick"] = 7 * TICKS_PER_DAY
        snap = assemble(state, store=self.store,
                        detector=_Detector())
        stocks = snap["sections"]["stocks"]
        self.assertIn("drink is falling 2.0/day", stocks)
        self.assertIn("4.5 days left", stocks)


class TestAccountant(unittest.TestCase):
    def test_count_is_conservative(self):
        # The accountant over-counts vs the 4-char wire estimate.
        text = "x" * 120
        self.assertGreater(TokenAccountant.count(text),
                           TokenAccountant.wire_count(text))

    def test_fit_applies_cut_order(self):
        acct = TokenAccountant(target=100)
        snap = assemble(_state(), store=None,
                        detector=_Detector(), accountant=acct)
        # Over the tiny budget: cuts were applied, and the
        # never-cut sections (attention, header, status) survive.
        self.assertTrue(snap["cuts"])
        self.assertIn("attention", snap["sections"])
        self.assertIn("header", snap["sections"])
        self.assertIn("status", snap["sections"])
        # History (lowest priority) is dropped first.
        self.assertNotIn("history", snap["sections"])
        # The cuts brought the total down (from 374 uncut), but
        # the never-cut floor (header + attention + status +
        # compacted sections + the suggestion, which names the
        # still build when no still exists) cannot go below ~264
        # for this state.
        self.assertLess(snap["tokens"], 374)

    def test_fit_no_cuts_under_target(self):
        acct = TokenAccountant()
        sections = [{"name": "header", "text": "hi",
                     "priority": 99, "cut": lambda: ""}]
        kept, cuts = acct.fit(sections)
        self.assertEqual(cuts, [])
        self.assertEqual(len(kept), 1)


class TestSuggest(unittest.TestCase):
    def test_threat_suggests_query(self):
        items = [{"priority": 1, "kind": "threat",
                  "text": "HOSTILE: a troll is at (38, 176, z124).",
                  "unit_id": 5490, "pos": [38, 176, 124],
                  "at_baseline": False}]
        out = suggest(_state(), items)
        self.assertIn("query unit 5490", out)

    def test_low_drink_suggests_brew(self):
        items = [{"priority": 2, "kind": "new_arrival",
                  "text": "Drink is low: 9 units left.",
                  "unit_id": None, "pos": None,
                  "at_baseline": False}]
        out = suggest(_state(), items)
        self.assertIn("brew", out)

    def test_low_drink_no_still_suggests_building_still(self):
        # M1 run #4: the model enabled brewers and gathered plants
        # but never built the still, because the suggestion only ever
        # said "run the brew task" — and the brew task fails without
        # a still. With no still in state, the suggestion must name
        # the still build first.
        items = [{"priority": 2, "kind": "needs",
                  "text": "Drink is low: 9 units left.",
                  "unit_id": None, "pos": None,
                  "at_baseline": False}]
        out = suggest(_state(), items)
        self.assertIn("NO STILL EXISTS", out)
        self.assertIn("build_workshop kind=still", out)

    def test_low_drink_with_still_suggests_brew_task(self):
        # With a still present, the brew task is the right call.
        items = [{"priority": 2, "kind": "needs",
                  "text": "Drink is low: 9 units left.",
                  "unit_id": None, "pos": None,
                  "at_baseline": False}]
        st = _state(buildings={
            "summary": [{"type": "Workshop", "count": 2}],
            "list": [{"id": 1, "type": "Workshop",
                      "subtype": "Still"}]})
        out = suggest(st, items)
        self.assertIn("run the brew task", out)
        self.assertNotIn("NO STILL EXISTS", out)

    def test_nothing_urgent_no_suggestion(self):
        self.assertIsNone(suggest(_state(), []))


class TestSampleDaily(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "world.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_samples_once_per_day(self):
        state = _state()
        self.assertTrue(sample_daily(state, self.store))
        # Same day again: no second sample.
        self.assertFalse(sample_daily(state, self.store))
        # Next day: samples again.
        state2 = _state()
        state2["status"] = dict(state2["status"])
        state2["status"]["year_tick"] = 72000 + TICKS_PER_DAY
        self.assertTrue(sample_daily(state2, self.store))
        pts = self.store.trend_samples("drink")
        self.assertEqual(len(pts), 2)
        # Unit history was recorded for each citizen each day.
        rows = self.store.unit_history(100)
        self.assertEqual(len(rows), 2)

    def test_sample_daily_needs_a_tick(self):
        state = _state()
        del state["status"]["year_tick"]
        self.assertFalse(sample_daily(state, self.store))


class TestBaselineWindow(unittest.TestCase):
    def test_baseline_arrival_survives_past_one_day(self):
        from dfagent_harness.attention import build_attention
        # A baseline arrival at tick 0: still in attention at
        # tick 5000 (past the 1,200-tick window) but gone by
        # tick 9000 (past the 8,400-tick baseline window).
        rec = {"tick": 0, "at_baseline": True,
               "data": {"kind": "visitor", "race": "DWARF",
                        "unit_id": 1, "pos": [90, 90, 175],
                        "dist_nearest_citizen": 5}}
        state = _state()
        state["status"] = dict(state["status"])
        state["status"]["year_tick"] = 5000
        items = build_attention(state, _Detector([rec]))
        arrivals = [it for it in items
                    if it["kind"] == "new_arrival"]
        self.assertEqual(len(arrivals), 1)
        state["status"]["year_tick"] = 9000
        items = build_attention(state, _Detector([rec]))
        arrivals = [it for it in items
                    if it["kind"] == "new_arrival"]
        self.assertEqual(len(arrivals), 0)

    def test_new_arrival_uses_the_short_window(self):
        from dfagent_harness.attention import build_attention
        rec = {"tick": 0, "at_baseline": False,
               "data": {"kind": "visitor", "race": "DWARF",
                        "unit_id": 1, "pos": [90, 90, 175],
                        "dist_nearest_citizen": 5}}
        state = _state()
        state["status"] = dict(state["status"])
        state["status"]["year_tick"] = 2000
        items = build_attention(state, _Detector([rec]))
        arrivals = [it for it in items
                    if it["kind"] == "new_arrival"]
        self.assertEqual(len(arrivals), 0)


class TestStocksAttention(unittest.TestCase):
    """Low drink/food are attention items (design §6.1: "what is
    wrong") and drive the suggestion — and they need no detector."""

    def test_low_drink_is_an_attention_item(self):
        from dfagent_harness.attention import build_attention
        # Drink 9 is below the warn threshold (20).
        items = build_attention(_state(), None)
        kinds = [it["kind"] for it in items]
        self.assertIn("low_drink", kinds)
        item = next(it for it in items if it["kind"] == "low_drink")
        self.assertEqual(item["priority"], 2)
        self.assertIn("9 units", item["text"])

    def test_critical_drink_is_priority_1(self):
        from dfagent_harness.attention import build_attention
        state = _state()
        state["stocks"] = dict(state["stocks"])
        state["stocks"]["drink_units"] = 5
        items = build_attention(state, None)
        item = next(it for it in items if it["kind"] == "low_drink")
        self.assertEqual(item["priority"], 1)
        self.assertIn("CRITICAL", item["text"])

    def test_no_detector_no_crash(self):
        from dfagent_harness.attention import build_attention
        # No detector: threats + stocks still reported, arrivals
        # skipped.
        items = build_attention(_state(), None)
        self.assertTrue(items)
        self.assertTrue(all(it["kind"] != "new_arrival"
                            for it in items))

    def test_assemble_suggests_brew_without_detector(self):
        tmp = tempfile.TemporaryDirectory()
        store = Store(Path(tmp.name) / "world.db")
        try:
            snap = assemble(_state(), store=store, detector=None)
            self.assertIsNotNone(snap["suggestion"])
            self.assertIn("brew", snap["suggestion"])
            self.assertIn("Drink is low",
                          snap["sections"]["attention"])
        finally:
            store.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
