"""Offline tests for general material awareness (2026-11-27).

No game needed: the requirements table, the shortage checks, the
snapshot Materials section and the suggestion substitution all work
from state dicts. The quantities in the table are verified live
against the game's own reaction table (df.reaction.find, 449
reactions): every MAKE WOODEN * job takes 1 log; brew takes 1
brewable plant + 1 empty barrel and yields 5 drink + 1 seed; an
easy meal needs 2 distinct food stacks (DF wiki, Cook page).
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import catalog, materials  # noqa: E402
from dfagent_harness.actions import JOB_SPECS  # noqa: E402
from dfagent_harness.assembler import (  # noqa: E402
    _materials, assemble, suggest)
from dfagent_harness.store import Store  # noqa: E402


def _stocks(**over):
    s = {"drink_units": 35, "food_units": 32, "food_stacks": 12,
         "wood_units": 124, "stone_units": 0, "seeds_units": 35,
         "barrels": 15, "empty_barrels": 3,
         "by_material": [
             # Real plants (type PLANT, STRUCTURAL material, flagged
             # brewable by stocks.lua) — these are the 48 brewable
             # plants. The DRINK entry below is brewed drink (20u):
             # it must NOT count (the old rule matched its :DRINK
             # material and returned the fort's drink count instead
             # of its plants — 2026-11-27, external review C3).
             {"type": "PLANT",
              "material": "PLANT:MUSHROOM_HELMET_PLUMP:STRUCTURAL",
              "brewable": True, "units": 33},
             {"type": "PLANT",
              "material": "PLANT:POD_SWEET:STRUCTURAL",
              "brewable": True, "units": 15},
             {"type": "DRINK",
              "material": "PLANT:MUSHROOM_HELMET_PLUMP:DRINK",
              "units": 20}]}
    s.update(over)
    return s


def _buildings(**over):
    b = {"list": [
        {"id": 7, "type": "Workshop", "subtype": "Carpenters"},
        {"id": 8, "type": "Workshop", "subtype": "Still"}]}
    b.update(over)
    return b


def _state(**over):
    s = {"status": {"date": "125-04-02", "year": 125,
                    "year_tick": 102635, "paused": True,
                    "focus": "dwarfmode/Default",
                    "population": {"citizens": 7, "animals": 25},
                    "fort_name": "Erushtathtat"},
         "stocks": _stocks(),
         "buildings": _buildings(),
         "items": {"by_type": [{"type": "BED", "units": 0},
                               {"type": "BARREL", "units": 15}]},
         "units": {"citizens": [], "hostiles": [], "wildlife": [],
                   "visitors": [], "livestock": []},
         "jobs": {"list": []},
         "reports": {"announcements": [], "combat": []}}
    s.update(over)
    return s


class TestRequirementsTable(unittest.TestCase):
    def test_every_job_spec_has_materials(self):
        for job in JOB_SPECS:
            self.assertIn(job, materials.JOB_MATERIALS,
                          f"{job} has no materials entry")

    def test_carpenter_jobs_need_one_log(self):
        for job in ("make_bed", "make_table", "make_chair",
                    "make_door", "make_barrel", "make_bucket",
                    "make_bin", "make_chest", "make_cabinet"):
            reqs = materials.JOB_MATERIALS[job]
            self.assertEqual(len(reqs), 1)
            self.assertEqual(reqs[0]["stock"], "wood_units")
            self.assertEqual(reqs[0]["per_job"], 1)

    def test_brew_needs_plant_and_empty_barrel(self):
        reqs = materials.JOB_MATERIALS["brew"]
        self.assertEqual({r["stock"] for r in reqs},
                         {"brewable_plants", "empty_barrels"})
        for r in reqs:
            self.assertEqual(r["per_job"], 1)

    def test_cook_needs_two_food_stacks(self):
        reqs = materials.JOB_MATERIALS["cook"]
        self.assertEqual(len(reqs), 1)
        self.assertEqual(reqs[0]["stock"], "food_stacks")
        self.assertEqual(reqs[0]["per_job"], 2)


class TestStockCounts(unittest.TestCase):
    def test_brewable_plants_from_by_material(self):
        self.assertEqual(materials.brewable_plants(_stocks()), 48)

    def test_brewable_plants_counts_plants_not_drink(self):
        # C3 (2026-11-27): the old rule (material starts PLANT:
        # and ends :DRINK) matched ONLY brewed drink — it returned
        # the fort's drink count. Plants carry STRUCTURAL; drinks
        # carry DRINK. A DRINK entry must not count, a non-brewable
        # PLANT (dimple cup, brewable False) must not count, and
        # an entry without the flag falls back to its type.
        stocks = {"by_material": [
            {"type": "PLANT",
             "material": "PLANT:MUSHROOM_HELMET_PLUMP:STRUCTURAL",
             "brewable": True, "units": 10},
            {"type": "DRINK",
             "material": "PLANT:MUSHROOM_HELMET_PLUMP:DRINK",
             "units": 99},
            {"type": "PLANT",
             "material": "PLANT:MUSHROOM_CUP_DIMPLE:STRUCTURAL",
             "brewable": False, "units": 7},
            {"type": "PLANT",
             "material": "PLANT:GRASS_TAIL_PIG:STRUCTURAL",
             "units": 3}]}
        self.assertEqual(materials.brewable_plants(stocks), 13)

    def test_empty_barrels_falls_back_to_total(self):
        old = _stocks()
        del old["empty_barrels"]
        self.assertEqual(materials.stock_count(old, "empty_barrels"), 15)

    def test_missing_key_is_unknown_not_zero(self):
        self.assertIsNone(materials.stock_count({}, "wood_units"))


class TestCheckJob(unittest.TestCase):
    def test_brew_short_on_plants_names_gather(self):
        short = materials.check_job(
            "brew", _stocks(by_material=[]), count=1,
            buildings=_buildings())
        self.assertEqual(len(short), 1)
        self.assertIn("designate_gather", short[0]["fix"])
        self.assertEqual(short[0]["have"], 0)

    def test_brew_short_on_barrels_names_make_barrel_with_id(self):
        short = materials.check_job(
            "brew", _stocks(empty_barrels=0), count=1,
            buildings=_buildings())
        self.assertEqual(len(short), 1)
        self.assertIn("make_barrel", short[0]["fix"])
        self.assertIn("#7", short[0]["fix"])

    def test_brew_x5_with_3_empty_barrels_is_short(self):
        short = materials.check_job(
            "brew", _stocks(), count=5, buildings=_buildings())
        self.assertEqual(len(short), 1)
        self.assertEqual(short[0]["need"], 5)
        self.assertEqual(short[0]["have"], 3)

    def test_brew_covered_when_stocked(self):
        self.assertEqual(
            materials.check_job("brew", _stocks(), count=3,
                                buildings=_buildings()), [])

    def test_make_bed_short_on_wood_names_chop(self):
        short = materials.check_job(
            "make_bed", _stocks(wood_units=0), count=1)
        self.assertEqual(len(short), 1)
        self.assertIn("designate_chop", short[0]["fix"])

    def test_cook_short_on_stacks(self):
        short = materials.check_job(
            "cook", _stocks(food_stacks=1), count=1)
        self.assertEqual(len(short), 1)
        self.assertEqual(short[0]["need"], 2)
        short3 = materials.check_job(
            "cook", _stocks(food_stacks=4), count=3)
        self.assertEqual(len(short3), 1)
        self.assertEqual(short3[0]["need"], 6)


class TestCheckWorkshop(unittest.TestCase):
    def test_still_needs_stone_or_wood(self):
        # Both short: both alternatives reported.
        short = materials.check_workshop(
            "still", _stocks(wood_units=0, stone_units=0))
        self.assertEqual(len(short), 2)
        # Either one covered: no shortage.
        self.assertEqual(
            materials.check_workshop(
                "still", _stocks(wood_units=0, stone_units=5)), [])
        self.assertEqual(
            materials.check_workshop(
                "still", _stocks(wood_units=5, stone_units=0)), [])

    def test_carpenter_needs_wood_only(self):
        short = materials.check_workshop(
            "carpenter", _stocks(wood_units=0))
        self.assertEqual(len(short), 1)
        self.assertIn("chop", short[0]["fix"])


class TestRequirementsForState(unittest.TestCase):
    def test_no_still_and_no_material_names_still_build(self):
        state = _state(
            stocks=_stocks(wood_units=0, stone_units=0),
            buildings=_buildings(list=[
                {"id": 7, "type": "Workshop",
                 "subtype": "Carpenters"}]))
        lines = materials.requirements_for_state(state)
        self.assertTrue(any(l.startswith("Still build:") for l in lines))

    def test_no_still_and_wood_on_hand_states_have_need(self):
        # Reinforced 2026-11-27: the line is emitted for the action
        # being considered even when the material is COVERED, with
        # exact have/need numbers — not only when short.
        state = _state(
            buildings=_buildings(list=[
                {"id": 7, "type": "Workshop",
                 "subtype": "Carpenters"}]))
        lines = materials.requirements_for_state(state)
        still = [l for l in lines if l.startswith("Still build:")]
        self.assertEqual(len(still), 1)
        self.assertIn("need 1 stone or 1 wood", still[0])
        self.assertIn("have stone 0, wood 124", still[0])
        self.assertIn("(enough)", still[0])

    def test_still_and_no_plants_names_brew_gather(self):
        state = _state(stocks=_stocks(by_material=[]))
        lines = materials.requirements_for_state(state)
        self.assertTrue(any(l.startswith("Brew:") and
                            "designate_gather" in l for l in lines))

    def test_brew_covered_states_plants_barrels_and_brew_count(self):
        # Default state: still exists, 48 brewable plants, 3 empty
        # barrels — the line states the per-drink need, the exact
        # stock, and how many brews it covers.
        lines = materials.requirements_for_state(_state())
        brew = [l for l in lines if l.startswith("Brew:")]
        self.assertEqual(len(brew), 1)
        self.assertIn("need 1 brewable plant + 1 empty barrel",
                      brew[0])
        self.assertIn("have 48 plants, 3 empty barrels", brew[0])
        self.assertIn("enough for 3 more brews", brew[0])

    def test_still_and_no_empty_barrels_brew_line_names_make_barrel(
            self):
        # With a still the brew line carries the barrel numbers, so
        # there is no separate Barrel line — the brew line names
        # the make_barrel fix.
        state = _state(stocks=_stocks(empty_barrels=0))
        lines = materials.requirements_for_state(state)
        self.assertTrue(any(l.startswith("Brew:") and
                            "make_barrel" in l and "#7" in l
                            for l in lines))
        self.assertFalse(any(l.startswith("Barrel:") for l in lines))

    def test_no_still_and_no_empty_barrels_names_barrel_line(self):
        state = _state(
            stocks=_stocks(empty_barrels=0),
            buildings=_buildings(list=[
                {"id": 7, "type": "Workshop",
                 "subtype": "Carpenters"}]))
        lines = materials.requirements_for_state(state)
        self.assertTrue(any(l.startswith("Barrel:") and
                            "make_barrel" in l and "#7" in l
                            for l in lines))

    def test_no_bed_item_names_make_bed_with_id(self):
        lines = materials.requirements_for_state(_state())
        self.assertTrue(any(l.startswith("Bed:") and
                            "make_bed" in l and "#7" in l
                            for l in lines))

    def test_bed_line_states_bed_and_wood_numbers(self):
        lines = materials.requirements_for_state(_state())
        bed = [l for l in lines if l.startswith("Bed:")]
        self.assertEqual(len(bed), 1)
        self.assertIn("need 1 BED item to place — have 0", bed[0])
        self.assertIn("make one needs 1 wood — have 124", bed[0])

    def test_bed_line_with_no_wood_names_chop(self):
        state = _state(stocks=_stocks(wood_units=0))
        lines = materials.requirements_for_state(state)
        bed = [l for l in lines if l.startswith("Bed:")]
        self.assertEqual(len(bed), 1)
        self.assertIn("have 0 — chop trees first", bed[0])

    def test_no_bed_and_no_carpenter_says_build_one_first(self):
        state = _state(buildings=_buildings(list=[
            {"id": 8, "type": "Workshop", "subtype": "Still"}]))
        lines = materials.requirements_for_state(state)
        self.assertTrue(any("build one first" in l and
                            "kind=carpenter" in l for l in lines))

    def test_covered_actions_still_state_have_need(self):
        # The old "nothing short is empty" is gone by design
        # (reinforced 2026-11-27): covered actions state their
        # have/need. BED 7 means no bed line; the brew line is
        # present with exact numbers.
        state = _state(
            stocks=_stocks(by_material=[
                {"type": "PLANT",
                 "material": "PLANT:MUSHROOM_HELMET_PLUMP:STRUCTURAL",
                 "brewable": True, "units": 33}]),
            items={"by_type": [{"type": "BED", "units": 7},
                               {"type": "BARREL", "units": 15}]})
        lines = materials.requirements_for_state(state)
        self.assertTrue(any(
            l.startswith("Brew:") and
            "have 33 plants, 3 empty barrels" in l for l in lines))
        self.assertFalse(any(l.startswith("Bed:") for l in lines))

    def test_unknown_stock_emits_no_lines(self):
        # No still, no wood/stone/barrel keys, BED on hand: nothing
        # is known, so nothing is claimed — never a guessed
        # shortage, and no covered line either.
        state = _state(
            stocks={"drink_units": 35, "food_units": 32},
            buildings={"list": []},
            items={"by_type": [{"type": "BED", "units": 7}]})
        self.assertEqual(materials.requirements_for_state(state), [])

    def test_missing_stocks_is_unknown_not_short(self):
        self.assertEqual(materials.requirements_for_state({}), [])


class TestFormatShortage(unittest.TestCase):
    def test_single_copy_uses_label_count_once(self):
        # The label already carries its count ("1 brewable plant"):
        # the old text doubled it ("need 1 1 brewable plant",
        # observed live in P0-1 run 3's fail-fast message).
        out = materials.format_shortage({
            "need": 1, "per_job": 1, "have": 0,
            "label": "1 brewable plant",
            "fix": "gather plants first"})
        self.assertEqual(
            out, "need 1 brewable plant, have 0 — "
                 "gather plants first")

    def test_multi_copy_names_total_and_each(self):
        out = materials.format_shortage({
            "need": 3, "per_job": 1, "have": 2,
            "label": "1 empty barrel",
            "fix": "queue make_barrel at the carpenter #7"})
        self.assertEqual(
            out, "need 3 in total (1 empty barrel each), have 2 — "
                 "queue make_barrel at the carpenter #7")

    def test_multi_copy_per_job_two(self):
        out = materials.format_shortage({
            "need": 4, "per_job": 2, "have": 0,
            "label": "2 distinct food stacks",
            "fix": "gather plants first"})
        self.assertEqual(
            out, "need 4 in total (2 distinct food stacks each), "
                 "have 0 — gather plants first")


class TestAssemblerMaterials(unittest.TestCase):
    def test_materials_section_lists_have_need(self):
        text, short = _materials(_state())
        self.assertIn("Materials (have / need", text)
        self.assertIn("Bed:", text)
        self.assertIn("make_bed", text)
        self.assertIn("Brew:", text)
        self.assertIn("2 requirement(s)", short)

    def test_materials_section_empty_when_nothing_known(self):
        # No still, no stock keys, BED on hand: nothing can be
        # stated honestly, so the section costs no tokens.
        state = _state(
            stocks={"drink_units": 35, "food_units": 32},
            buildings={"list": []},
            items={"by_type": [{"type": "BED", "units": 7}]})
        self.assertEqual(_materials(state), ("", ""))

    def test_assemble_carries_materials_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "world.db")
            try:
                snap = assemble(_state(), store=store)
                self.assertIn("materials", snap["sections"])
                self.assertIn("Bed:", snap["sections"]["materials"])
            finally:
                store.close()

    def test_suggest_substitutes_gather_when_brew_short_on_plants(self):
        state = _state(stocks=_stocks(by_material=[]))
        items = [{"kind": "needs", "priority": 1,
                  "text": "drink 8 — brew more drink"}]
        out = suggest(state, items)
        self.assertIsNotNone(out)
        self.assertIn("gather", out)
        self.assertNotIn("Suggested action: run the brew task", out)

    def test_suggest_substitutes_gather_when_brew_short_on_barrels(self):
        state = _state(stocks=_stocks(empty_barrels=0))
        items = [{"kind": "needs", "priority": 1,
                  "text": "drink 8 — brew more drink"}]
        out = suggest(state, items)
        self.assertIsNotNone(out)
        self.assertIn("make_barrel", out)
        self.assertNotIn("Suggested action: run the brew task", out)

    def test_suggest_brew_task_when_stocked(self):
        items = [{"kind": "needs", "priority": 1,
                  "text": "drink 8 — brew more drink"}]
        out = suggest(_state(), items)
        self.assertIn("run the brew task", out)

    def test_suggest_substitutes_material_when_no_still_and_no_wood(
            self):
        state = _state(
            stocks=_stocks(drink_units=30, wood_units=0,
                           stone_units=0),
            buildings=_buildings(list=[
                {"id": 7, "type": "Workshop",
                 "subtype": "Carpenters"}]))
        out = suggest(state, [])
        self.assertIsNotNone(out)
        self.assertIn("gather building material", out)
        self.assertNotIn("build_workshop kind=still", out)


class TestCatalogMaterials(unittest.TestCase):
    def test_queue_job_names_materials_per_job(self):
        desc = catalog.describe("queue_job")
        constraints = " ".join(desc["constraints"])
        self.assertIn("Materials per copy", constraints)
        self.assertIn("brew: 1 brewable plant + 1 empty barrel",
                      constraints)
        self.assertIn("cook: 2 distinct food stacks", constraints)
        self.assertIn("make_bed: 1 wood (log)", constraints)

    def test_build_workshop_names_per_kind_material(self):
        desc = catalog.describe("build_workshop")
        constraints = " ".join(desc["constraints"])
        self.assertIn("Still: 1 stone or 1 wood", constraints)
        self.assertNotIn("usually 1 wood", constraints)

    def test_build_furniture_bed_needs_item_not_wood(self):
        desc = catalog.describe("build_furniture")
        constraints = " ".join(desc["constraints"])
        self.assertIn("needs a bed ITEM in stock", constraints)


if __name__ == "__main__":
    unittest.main()
