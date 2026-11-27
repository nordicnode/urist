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
from dfagent_harness.assembler import (TokenAccountant, _buildings,  # noqa: E402
                                       _stocks, assemble,
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

    def test_low_drink_no_still_names_free_site(self):
        # M1 run #6: the model stalled because the observation
        # gave it no free ground coordinates. When the daemon's
        # derived sites are passed in, the still-build suggestion
        # names the concrete coordinate.
        items = [{"priority": 2, "kind": "needs",
                  "text": "Drink is low: 9 units left.",
                  "unit_id": None, "pos": None,
                  "at_baseline": False}]
        sites = {"workshop_sites": [(96, 105, 175), (89, 105, 175)]}
        out = suggest(_state(), items, sites=sites)
        self.assertIn("build_workshop kind=still at 96, 105, 175", out)

    def test_nothing_urgent_no_suggestion(self):
        # No attention items, a still present, drink plentiful:
        # nothing urgent, so no suggestion. (A no-still state
        # with finite drink DOES get the proactive still-build
        # suggestion even with no attention items.)
        st = _state(buildings={
            "summary": [{"type": "Workshop", "count": 1}],
            "list": [{"id": 1, "type": "Workshop",
                      "subtype": "Still"}]})
        st["stocks"] = dict(st["stocks"])
        st["stocks"]["drink_units"] = 120
        self.assertIsNone(suggest(st, []))

    def test_proactive_still_suggestion_without_drink_item(self):
        # M1 run #7 tick 1: drink 32 is above the attention warn
        # threshold (20), so no drink item fired and the model got
        # no suggestion and no site coordinate. The fallback fires
        # the still build proactively when there is no still and
        # drink is finite (< 50).
        st = _state()
        st["stocks"] = dict(st["stocks"])
        st["stocks"]["drink_units"] = 32
        out = suggest(st, [])
        self.assertIn("NO STILL EXISTS", out)
        self.assertIn("build_workshop kind=still", out)


class TestBuildingsAndStocksVisibility(unittest.TestCase):
    # Mikey, 2026-11-26: M1 ticks 1 and 4 burned idle ticks asking
    # what the single existing building is, and by tick 6 three
    # brewers were enabled without ever checking whether a Still
    # existed. The snapshot must surface the workshops (subtype +
    # state) and the brewable plant count directly.
    def test_buildings_names_workshop_subtype_and_still_none(self):
        st = _state(buildings={
            "summary": [{"type": "Workshop", "count": 1},
                        {"type": "Bed", "count": 10}],
            "list": [{"id": 7, "type": "Workshop",
                      "subtype": "Carpenters",
                      "construction_stage": 3}]})
        text, short = _buildings(st)
        self.assertIn("Carpenters #7 (built)", text)
        self.assertIn("Still: none", text)
        self.assertIn("Bed x10", text)
        self.assertNotIn("Workshop x", text)
        # The short form is the diffed one-liner ("buildings:
        # unchanged (SHORT)"). It must carry the subtypes too:
        # M1 run #7 tick 6 re-asked what the building was because
        # the one-liner said only "1 buildings".
        self.assertIn("Carpenters #7 (built)", short)
        self.assertIn("Still: none", short)

    def test_buildings_names_still_when_present(self):
        st = _state(buildings={
            "summary": [{"type": "Workshop", "count": 2}],
            "list": [{"id": 7, "type": "Workshop",
                      "subtype": "Carpenters",
                      "construction_stage": 3},
                     {"id": 8, "type": "Workshop",
                      "subtype": "Still",
                      "construction_stage": 1}]})
        text, _short = _buildings(st)
        self.assertIn("Carpenters #7 (built)", text)
        self.assertIn("Still #8 (under construction)", text)
        self.assertNotIn("Still: none", text)

    def test_stocks_head_line_has_brewable_plants(self):
        st = _state()
        st["stocks"] = dict(st["stocks"])
        st["stocks"]["by_material"] = [
            {"material": "PLANT:MUSHROOM_HELMET_PLUMP:DRINK",
             "units": 12},
            {"material": "PLANT:MUSHROOM_HELMET_PLUMP:STRUCTURAL",
             "units": 5},
            {"material": "wood", "units": 211}]
        text, _short = _stocks(st, None, 0)
        # Only the DRINK material counts; STRUCTURAL does not.
        self.assertIn("brewable plants 12", text.split("\n")[0])

    def test_assemble_carries_calendar_date(self):
        # The M1 driver's start_tick log took "date" from the
        # status section text ("Population: ...") — the wrong line.
        # The snapshot carries the calendar date as a field.
        snap = assemble(_state(), store=None, detector=_Detector())
        self.assertEqual(snap["date"], "125-06-02")
        self.assertNotIn("Population", snap["date"])


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

    def test_sample_daily_invalidates_trends_on_reload(self):
        # A reload moves the clock backwards (the fort was restored
        # from an older save). The old timeline's samples must be
        # dropped, or they corrupt every burn rate and freeze
        # sampling (the day number went backwards). Verified live
        # 2026-11-27: drink samples from the drink-0 timeline gave
        # a 0.3/day rate and "0.0 days left" while the real stock
        # was 39, and no new sample was ever taken.
        state = _state()
        state["status"] = dict(state["status"])
        state["status"]["year_tick"] = 200 * TICKS_PER_DAY
        self.assertTrue(sample_daily(state, self.store))
        self.assertEqual(len(self.store.trend_samples("drink")), 1)
        # Reload to an earlier tick: the old sample is dropped and
        # the new timeline starts fresh.
        state2 = _state()
        state2["status"] = dict(state2["status"])
        state2["status"]["year_tick"] = 85 * TICKS_PER_DAY
        self.assertTrue(sample_daily(state2, self.store))
        pts = self.store.trend_samples("drink")
        self.assertEqual(len(pts), 1)
        self.assertEqual(pts[0][0], 85 * TICKS_PER_DAY)


class TestReportsOneLine(unittest.TestCase):
    """Fix 5 (2026-11-27): reports are one line of text, never a
    raw DFHack dict. The prompt used to print the whole struct
    (unk_v40_1, zoom_type, pos, ...) — token waste and noise."""

    def test_announcement_is_one_line(self):
        state = _state()
        state["reports"] = {
            "announcements": [{
                "unk_v40_1": -1, "zoom_type": 0, "time": 100800,
                "year": 125, "text": "It is now summer.",
                "pos": [-30000, -30000, -30000],
            }],
            "reports": [],
        }
        snap = assemble(state, detector=_Detector())
        reports = snap["sections"]["reports"]
        self.assertIn("[y125 t100800] It is now summer.", reports)
        self.assertNotIn("unk_v40_1", reports)
        self.assertNotIn("zoom_type", reports)
        self.assertNotIn("-30000", reports)

    def test_combat_reports_use_the_reports_field(self):
        # The Lua helper names combat reports "reports", not
        # "combat" — the old key never fired, so combat was
        # silently dropped from the snapshot.
        state = _state()
        state["reports"] = {
            "announcements": [],
            "reports": [{"year": 125, "time": 100900,
                         "text": "The crundle bites the dwarf."}],
        }
        snap = assemble(state, detector=_Detector())
        self.assertIn("combat: [y125 t100900] The crundle bites",
                      snap["sections"]["reports"])



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
