"""Offline tests for the AI-written diary feed (GOAL.md step 4).

The diary entry is written by the model, not by code templates:
build_diary_feed curates the facts (the day's ledger + one
structured record per dwarf who changed, with their relations'
current state + recent entries + open threads), diary_prompt
renders those facts as plain text, and write_ai_entry calls the
model and validates the prose. A template list is never written
instead — on model failure the day is skipped.

These tests use a stub client (no network, no Free Pi) and fake
Store/Journal stand-ins. Live verification (a real day's entry,
read as a player) is separate and is what decides whether the
diary is done.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import diary  # noqa: E402
from dfagent_harness.dwarves import dwarf_record  # noqa: E402


class FakeStore:
    """Minimal Store stand-in: trends + deaths + unit history."""

    def __init__(self):
        self._trends = {}
        self._deaths = []
        self._units = {}

    def add_trend(self, metric, tick, value):
        self._trends.setdefault(metric, []).append((tick, value))

    def trend_samples(self, metric):
        return sorted(self._trends.get(metric, []))

    def add_death(self, tick, unit_id, cause, history_ref=""):
        self._deaths.append({"tick": tick, "unit_id": unit_id,
                             "cause": cause,
                             "history_ref": history_ref})

    def deaths(self):
        return list(self._deaths)

    def add_unit(self, uid, tick, **fields):
        sample = {"tick": tick, "unit_id": uid}
        sample.update(fields)
        self._units.setdefault(uid, []).append(sample)

    def unit_ids(self):
        return sorted(self._units)

    def unit_history(self, uid, limit=None):
        rows = sorted(self._units.get(uid, []),
                      key=lambda s: s["tick"])
        return list(rows[-limit:] if limit else rows)


class FakeJournal:
    """Minimal Journal stand-in: decisions + daemon events."""

    def __init__(self):
        self._decisions = []
        self._events = []

    def add_decision(self, tick, decision, reason="", action="",
                     domain="needs", ok=None, result=None):
        self._decisions.append({"tick": tick, "decision": decision,
                                "reason": reason, "action": action,
                                "domain": domain, "ok": ok,
                                "result": result})

    def add_event(self, tick, kind, detail=""):
        self._events.append({"tick": tick, "kind": kind,
                             "detail": detail})

    def recent_decisions(self, limit=100):
        return list(reversed(self._decisions[-limit:]))

    def recent_events(self, limit=100):
        return list(reversed(self._events[-limit:]))


class StubClient:
    """A model stand-in: returns canned prose, records the prompt."""

    def __init__(self, text):
        self.text = text
        self.messages = None

    def chat(self, messages):
        self.messages = messages
        return self.text


def _olons(day_start=100800):
    """Two samples for Olon (a brewer): calm in the morning,
    stressed and thirsty by the day's end."""
    store = FakeStore()
    store.add_unit(101, day_start, name="Olon Medtobalod",
                   profession="Brewer", mood=-1, mood_name="none",
                   stress_level=40000, stress_category=3,
                   needs=[], wounds=[], job="Brewer",
                   relations=[])
    store.add_unit(101, day_start + 1199, name="Olon Medtobalod",
                   profession="Brewer", mood=-1, mood_name="none",
                   stress_level=85000, stress_category=1,
                   needs=[{"need": "Drink", "focus": -30,
                           "level": 25}],
                   wounds=[], job="Brewer", relations=[])
    store.add_trend("drink", day_start, 38)
    store.add_trend("drink", day_start + 1199, 35)
    return store


def _seven(day_start=100800):
    """Seven citizens, six wounded (Ral clean), deity relations
    pre-existing, Lor gaining a friend today. Mirrors the
    125-04-01 run: the feed said six of seven wounded and the AI
    wrote "every dwarf ... carrying an injury". Olon is thirsty
    (a Drink need in both samples, so it is ongoing, not new)."""
    store = FakeStore()
    names = ["Lor", "Mestthos", "Olon", "Zulban",
             "Oslanlumash", "Rakust", "Ral"]
    for i, name in enumerate(names):
        uid = 100 + i
        wounds = [] if name == "Ral" else [{"id": i + 1}]
        job = "Fish" if name == "Ral" else (
            "Drink2" if name == "Lor" else "")
        rels_prev = [{"unit_id": 900 + i, "type": "deity",
                      "name": f"Deity {900 + i}", "in_fort": False,
                      "histfig_id": 900 + i}]
        rels_curr = list(rels_prev)
        if name == "Lor":
            rels_curr.append(
                {"unit_id": 101, "type": "friend",
                 "name": "Mestthos", "in_fort": True,
                 "histfig_id": 500})
        needs = ([{"need": "Drink", "focus": -30, "level": 25}]
                 if name == "Olon" else [])
        for tick, rels in ((day_start, rels_prev),
                           (day_start + 1199, rels_curr)):
            store.add_unit(uid, tick, name=name,
                           profession="Miner", mood=-1,
                           mood_name="none", stress_level=40000,
                           stress_category=3, needs=needs,
                           wounds=wounds, job=job,
                           relations=rels)
    store.add_trend("drink", day_start, 38)
    store.add_trend("drink", day_start + 1199, 38)
    return store


class TestFeed(unittest.TestCase):
    def test_stress_jump_is_featured(self):
        store = _olons()
        feed = diary.build_diary_feed(store, FakeJournal(), 100800,
                                      "Erushtathtat", 125)
        self.assertEqual(len(feed["dwarves"]), 1)
        rec = feed["dwarves"][0]
        self.assertTrue(rec["featured"])
        self.assertGreaterEqual(rec["significance"], 2)
        self.assertEqual(rec["name"], "Olon Medtobalod")
        self.assertTrue(any("stress" in c["text"].lower()
                            for c in rec["changes"]))

    def test_stable_dwarf_is_not_featured(self):
        store = FakeStore()
        store.add_unit(102, 100800, name="Zulban Rithgemesh",
                       profession="Miner", mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[], job="Miner",
                       relations=[])
        store.add_unit(102, 101999, name="Zulban Rithgemesh",
                       profession="Miner", mood=-1, mood_name="none",
                       stress_level=41000, stress_category=3,
                       needs=[], wounds=[], job="Miner",
                       relations=[])
        feed = diary.build_diary_feed(store, FakeJournal(), 100800,
                                      "Erushtathtat", 125)
        rec = feed["dwarves"][0]
        self.assertFalse(rec["featured"])
        self.assertEqual(rec["significance"], 0)

    def test_single_sample_still_carries_personal_life(self):
        # The first M1 day has only one sample per citizen (no
        # previous day to diff against). The feed must still carry
        # the dwarf's current mood, stress, needs, and relations —
        # the entry is about the dwarf as a person, not only about
        # what changed.
        store = FakeStore()
        store.add_unit(103, 100800, name="Rakust Cattenaval",
                       profession="Carpenter", mood=-1,
                       mood_name="none", stress_level=30000,
                       stress_category=4,
                       needs=[{"need": "Drink", "focus": -10,
                               "level": 15}],
                       wounds=[], job="Carpenter",
                       relations=[{"unit_id": 101, "type": "friend",
                                   "name": "Olon Medtobalod",
                                   "in_fort": True, "strength": 40}])
        feed = diary.build_diary_feed(store, FakeJournal(), 100800,
                                      "Erushtathtat", 125)
        rec = feed["dwarves"][0]
        self.assertEqual(rec["name"], "Rakust Cattenaval")
        self.assertEqual(rec["stress"]["words"], "relaxed")
        self.assertEqual(len(rec["needs"]), 1)
        self.assertEqual(len(rec["relations"]), 1)
        self.assertEqual(rec["relations"][0]["name"],
                         "Olon Medtobalod")

    def test_open_threads_from_current_state(self):
        store = _olons()
        threads = diary.open_threads(store, 100800, 125)
        kinds = {t["kind"] for t in threads}
        self.assertIn("stressed", kinds)
        self.assertIn("unmet_need", kinds)
        stressed = [t for t in threads
                    if t["kind"] == "stressed"][0]
        self.assertEqual(stressed["subject"], "Olon Medtobalod")

    def test_recent_entries_carried_for_continuity(self):
        # Day 125-04-02 (tick 102000): the 125-04-01 entry is
        # carried for continuity; the 125-04-02 entry is NOT — it
        # is from a different playthrough of today (run #17: the
        # entry invented a manager appointment and credited the
        # brewing to Olon by carrying forward an old entry's
        # claims for the same date).
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "diary.md").write_text(
                "# Diary of Erushtathtat\n\n"
                "## 125-04-01 — 1st of Hematite, 125\n\n"
                "Olon was thirsty all day.\n\n"
                "## 125-04-02 — 2nd of Hematite, 125\n\n"
                "Still no drink.\n")
            feed = diary.build_diary_feed(
                FakeStore(), FakeJournal(), 102000, "Erushtathtat",
                125, state_dir=state)
            self.assertEqual(len(feed["recent_entries"]), 1)
            self.assertIn("Olon was thirsty",
                          feed["recent_entries"][0]["body"])

    def test_recent_entries_exclude_future_dates(self):
        # An entry for a LATER date than today is also from
        # another playthrough (the fort was reloaded to an
        # earlier date) and must not be carried.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "diary.md").write_text(
                "# Diary of Erushtathtat\n\n"
                "## 125-04-01 — 1st of Hematite, 125\n\n"
                "Olon was thirsty all day.\n\n"
                "## 125-04-03 — 3rd of Hematite, 125\n\n"
                "The still is up.\n")
            feed = diary.build_diary_feed(
                FakeStore(), FakeJournal(), 102000, "Erushtathtat",
                125, state_dir=state)
            self.assertEqual(len(feed["recent_entries"]), 1)
            self.assertEqual(
                feed["recent_entries"][0]["date"], "125-04-01")


    def test_group_counts_name_the_wounded_and_the_one_not(self):
        # Run 060346: six of seven wounded (Ral clean) and the AI
        # wrote "every dwarf ... carrying an injury". The feed now
        # carries pre-computed counts — the number and the
        # complement — so the AI reads it instead of inferring it.
        feed = diary.build_diary_feed(_seven(), FakeJournal(),
                                      100800, "Erushtathtat", 125)
        counts = {g["key"]: g for g in feed["group_counts"]}
        wounded = counts["wounded"]
        self.assertEqual(wounded["count"], 6)
        self.assertEqual(wounded["total"], 7)
        self.assertEqual(wounded["not_names"], ["Ral"])
        self.assertNotIn("Ral", wounded["names"])
        self.assertEqual(counts["thirsty"]["count"], 1)
        self.assertEqual(counts["thirsty"]["names"], ["Olon"])
        self.assertEqual(counts["idle"]["count"], 5)
        self.assertEqual(sorted(counts["idle"]["not_names"]),
                         ["Lor", "Ral"])

    def test_relations_carry_new_today(self):
        # A deity link present in both samples is pre-existing
        # background; a friend gained today is new. The diary must
        # not present the god as "found today".
        feed = diary.build_diary_feed(_seven(), FakeJournal(),
                                      100800, "Erushtathtat", 125)
        lor = next(r for r in feed["dwarves"]
                   if r["name"] == "Lor")
        deity = next(r for r in lor["relations"]
                     if r["type"] == "deity")
        friend = next(r for r in lor["relations"]
                      if r["type"] == "friend")
        self.assertFalse(deity["new_today"])
        self.assertTrue(friend["new_today"])
        # A dwarf with no previous sample: every relation is
        # background (the dwarf is new to the record, the
        # relations are not new today).
        store = FakeStore()
        store.add_unit(103, 100800, name="Rakust Cattenaval",
                       profession="Carpenter", mood=-1,
                       mood_name="none", stress_level=30000,
                       stress_category=4, needs=[], wounds=[],
                       job="Carpenter",
                       relations=[{"unit_id": 101, "type": "friend",
                                   "name": "Olon Medtobalod",
                                   "in_fort": True, "strength": 40,
                                   "histfig_id": 501}])
        feed2 = diary.build_diary_feed(store, FakeJournal(),
                                       100800, "Erushtathtat", 125)
        rel = feed2["dwarves"][0]["relations"][0]
        self.assertFalse(rel["new_today"])


class TestFeedSamples(unittest.TestCase):
    def test_lite_prev_is_not_a_baseline(self):
        # Run 064517: the daemon's day-boundary lite sample at
        # tick 100800 (no name, no relations, no needs, wounds
        # empty) was the feed's prev, and diffing it against the
        # full run-end sample fabricated "gained a deity" for all
        # seven dwarves and "newly wounded" for five — the entry
        # then wrote "Every last one of them found a god today".
        # A lite sample is not a baseline: no new-today claims.
        store = FakeStore()
        store.add_unit(101, 100800, name="", profession="",
                       mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[], job="Drink2",
                       relations=[])
        store.add_unit(101, 101999, name="Lor Mebzuthkin",
                       profession="Miner", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3,
                       needs=[{"need": "Drink", "focus": -30,
                               "level": 25}],
                       wounds=[{"id": 4, "parts": 2}], job="",
                       relations=[{"unit_id": 900, "type": "deity",
                                   "name": "Katdir Rithuleser",
                                   "in_fort": False,
                                   "histfig_id": 900}])
        feed = diary.build_diary_feed(store, FakeJournal(),
                                      100800, "Erushtathtat", 125)
        lor = feed["dwarves"][0]
        kinds = [c["kind"] for c in lor["changes"]]
        self.assertNotIn("wound_new", kinds)
        self.assertNotIn("relation_new", kinds)
        deity = next(r for r in lor["relations"]
                     if r["type"] == "deity")
        self.assertFalse(deity["new_today"])

    def test_full_prev_full_curr_real_new_wound(self):
        # The true 101323 -> 101999 story: Lor was clean at run
        # start and wounded at run end, his deity pre-existing
        # both sides. The diff must report the wound and NOT the
        # god as new.
        store = FakeStore()
        deity = {"unit_id": 900, "type": "deity",
                 "name": "Katdir Rithuleser", "in_fort": False,
                 "histfig_id": 900}
        for tick, wounds in ((100800, []), (101999, [{"id": 4}])):
            store.add_unit(101, tick, name="Lor Mebzuthkin",
                           profession="Miner", mood=-1,
                           mood_name="none", stress_level=40000,
                           stress_category=3, needs=[],
                           wounds=wounds, job="",
                           relations=[deity])
        feed = diary.build_diary_feed(store, FakeJournal(),
                                      100800, "Erushtathtat", 125)
        lor = feed["dwarves"][0]
        kinds = [c["kind"] for c in lor["changes"]]
        self.assertIn("wound_new", kinds)
        self.assertNotIn("relation_new", kinds)
        deity_rec = next(r for r in lor["relations"]
                         if r["type"] == "deity")
        self.assertFalse(deity_rec["new_today"])

    def test_wound_worsened_same_id_more_parts(self):
        # The 04-01 äs case, verbatim: wound id 4, parts 0 -> 2.
        # The old diff compared ids only, so this produced NO
        # change and the entry never reported the wound getting
        # worse. A persisting id with more parts is a worsening.
        store = FakeStore()
        for tick, parts in ((100800, 0), (101999, 2)):
            store.add_unit(101, tick, name="Lor Mebzuthkin",
                           profession="Miner", mood=-1,
                           mood_name="none", stress_level=40000,
                           stress_category=3, needs=[],
                           wounds=[{"id": 4, "parts": parts}],
                           job="", relations=[])
        feed = diary.build_diary_feed(store, FakeJournal(),
                                      100800, "Erushtathtat", 125)
        lor = feed["dwarves"][0]
        kinds = [c["kind"] for c in lor["changes"]]
        self.assertIn("wound_worsened", kinds)
        self.assertNotIn("wound_new", kinds)
        self.assertNotIn("wound_healed", kinds)
        text = next(c["text"] for c in lor["changes"]
                    if c["kind"] == "wound_worsened")
        self.assertIn("worse", text)

    def test_wound_same_parts_is_not_worsened(self):
        # Same id, same parts: a stable wound is not a change.
        store = FakeStore()
        for tick in (100800, 101999):
            store.add_unit(101, tick, name="Lor Mebzuthkin",
                           profession="Miner", mood=-1,
                           mood_name="none", stress_level=40000,
                           stress_category=3, needs=[],
                           wounds=[{"id": 4, "parts": 2}],
                           job="", relations=[])
        feed = diary.build_diary_feed(store, FakeJournal(),
                                      100800, "Erushtathtat", 125)
        lor = feed["dwarves"][0]
        kinds = [c["kind"] for c in lor["changes"]]
        self.assertNotIn("wound_worsened", kinds)
        self.assertNotIn("wound_new", kinds)
        self.assertNotIn("wound_healed", kinds)

    def test_lite_curr_is_skipped(self):
        # A lite sample is the last one at or before the day end
        # (the daemon's poller keeps recording them). curr must
        # be the last FULL sample, not the lite one.
        store = FakeStore()
        for tick, name in ((100800, "Lor Mebzuthkin"),
                           (101500, "Lor Mebzuthkin")):
            store.add_unit(101, tick, name=name,
                           profession="Miner", mood=-1,
                           mood_name="none", stress_level=40000,
                           stress_category=3, needs=[],
                           wounds=[], job="", relations=[])
        store.add_unit(101, 101999, name="", profession="",
                       mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[], job="Drink2",
                       relations=[])
        prev, curr = diary._feed_samples(store, 101, 100800,
                                         101999)
        self.assertEqual(prev["tick"], 100800)
        self.assertEqual(curr["tick"], 101500)

    def test_no_full_prev_means_no_new_claims(self):
        # Only a lite sample before the day and one full sample
        # inside it: there is no baseline, so nothing is new.
        store = FakeStore()
        store.add_unit(101, 100000, name="", profession="",
                       mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[], job="Drink2",
                       relations=[])
        store.add_unit(101, 101999, name="Lor Mebzuthkin",
                       profession="Miner", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[],
                       wounds=[{"id": 4}], job="",
                       relations=[{"unit_id": 900, "type": "deity",
                                   "name": "Katdir Rithuleser",
                                   "in_fort": False,
                                   "histfig_id": 900}])
        prev, curr = diary._feed_samples(store, 101, 100800,
                                         101999)
        self.assertIsNone(prev)
        self.assertEqual(curr["tick"], 101999)
        feed = diary.build_diary_feed(store, FakeJournal(),
                                      100800, "Erushtathtat", 125)
        lor = feed["dwarves"][0]
        kinds = [c["kind"] for c in lor["changes"]]
        self.assertNotIn("wound_new", kinds)
        self.assertNotIn("relation_new", kinds)


class TestOpenThreadsSince(unittest.TestCase):
    """open_threads _since must not trust a flapping lite
    sample: a lite sample's empty wounds are "not recorded",
    not "clear". Re-check 2026-11-27: Lòr's wound first
    appears at tick 101999 = 125-04-01, but his 04-02 lite
    samples show no wound, so the old _since walk broke the
    run there and dated the wound 04-03 — contradicting the
    diary's own 04-01 entry (which carries a wound_new
    change for Lòr on 04-01)."""

    def _lor(self):
        store = FakeStore()
        # Full: unwounded 04-01 morning, wounded 04-01 end.
        store.add_unit(101, 100800, name="Lòr Mebzuthkin",
                       profession="Expedition Leader", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[],
                       wounds=[], job="ConstructBuilding",
                       relations=[])
        store.add_unit(101, 101999, name="Lòr Mebzuthkin",
                       profession="Expedition Leader", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[],
                       wounds=[{"id": 4, "parts": 2}], job="",
                       relations=[])
        # Lite 04-02: no name, no wound recorded (flapping).
        for tick in (102033, 102135):
            store.add_unit(101, tick, name="", profession="",
                           mood=-1, mood_name="none",
                           stress_level=40000, stress_category=3,
                           needs=[], wounds=[], job="Drink2",
                           relations=[])
        # Full 04-03: the same wound id reappears.
        store.add_unit(101, 103200, name="Lòr Mebzuthkin",
                       profession="Expedition Leader", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[],
                       wounds=[{"id": 4, "parts": 2}], job="",
                       relations=[])
        return store

    def test_lite_gap_does_not_break_wound_run(self):
        threads = diary.open_threads(self._lor(), 103200, 125)
        wounded = [t for t in threads if t["kind"] == "wounded"]
        self.assertEqual(len(wounded), 1)
        self.assertEqual(wounded[0]["since"], "125-04-01")

    def test_full_healed_sample_still_breaks_run(self):
        # A FULL sample with the wound clear is a real end:
        # the run dates from the later wounding, not the first.
        store = self._lor()
        store.add_unit(101, 104400, name="Lòr Mebzuthkin",
                       profession="Expedition Leader", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[], wounds=[],
                       job="", relations=[])
        store.add_unit(101, 105600, name="Lòr Mebzuthkin",
                       profession="Expedition Leader", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[],
                       wounds=[{"id": 9, "parts": 1}], job="",
                       relations=[])
        threads = diary.open_threads(store, 105600, 125)
        wounded = [t for t in threads if t["kind"] == "wounded"]
        self.assertEqual(len(wounded), 1)
        self.assertEqual(wounded[0]["since"], "125-04-05")

    def test_lite_only_wound_has_no_since(self):
        # The wound's only evidence is lite samples: the thread
        # exists (curr is wounded) but its start is unknown —
        # a lite gap earns no date rather than a wrong one.
        store = FakeStore()
        store.add_unit(101, 100800, name="", profession="",
                       mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[{"id": 4, "parts": 2}],
                       job="", relations=[])
        threads = diary.open_threads(store, 100800, 125)
        wounded = [t for t in threads if t["kind"] == "wounded"]
        self.assertEqual(len(wounded), 1)
        self.assertIsNone(wounded[0]["since"])

    def test_wound_present_at_first_sample_has_no_since(self):
        # Re-check 3 (2026-11-27): Rakust's wound is already
        # present in the lite sample at tick 100800, the first
        # tick of 04-01 — the store's first sample. Dating it
        # "since 125-04-01" made the diary claim it was taken
        # that day; it predates the record. A condition already
        # true at the earliest recorded moment earns no
        # since-date, not the first sample's date.
        store = FakeStore()
        store.add_unit(101, 100800, name="", profession="",
                       mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[{"id": 4, "parts": 0}],
                       job="", relations=[])
        store.add_unit(101, 101323, name="Rakust Cattenaval",
                       profession="Miner", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[],
                       wounds=[{"id": 4, "parts": 2}], job="",
                       relations=[])
        store.add_unit(101, 101999, name="Rakust Cattenaval",
                       profession="Miner", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[],
                       wounds=[{"id": 4, "parts": 2}], job="",
                       relations=[])
        threads = diary.open_threads(store, 100800, 125)
        wounded = [t for t in threads if t["kind"] == "wounded"]
        self.assertEqual(len(wounded), 1)
        self.assertIsNone(wounded[0]["since"])

    def test_wound_first_seen_at_first_full_sample_keeps_since(self):
        # The companion case (äs, Olon, Mestthos on 04-01): the
        # earliest lite sample shows NO wound, and the wound
        # first appears at the first full sample (101323). The
        # run reaches the store's start, but the condition was
        # not true at the earliest recorded moment, so the
        # first-full-sample date stands — five of the six 04-01
        # wounds were taken that day, and only Rakust's predates
        # the record.
        store = FakeStore()
        store.add_unit(101, 100800, name="", profession="",
                       mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[], job="", relations=[])
        store.add_unit(101, 101323, name="äs Oslanlumash",
                       profession="Woodcutter", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[],
                       wounds=[{"id": 4, "parts": 0}], job="",
                       relations=[])
        store.add_unit(101, 101999, name="äs Oslanlumash",
                       profession="Woodcutter", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[],
                       wounds=[{"id": 4, "parts": 2}], job="",
                       relations=[])
        threads = diary.open_threads(store, 100800, 125)
        wounded = [t for t in threads if t["kind"] == "wounded"]
        self.assertEqual(len(wounded), 1)
        self.assertEqual(wounded[0]["since"], "125-04-01")


class TestThreadNameResolution(unittest.TestCase):
    """A lite sample carries no name, so a thread (or lite-feed
    record) for that dwarf must resolve the name from the
    citizen's full samples at or before the day end — never from
    after it. Re-check 6, 06-02: the wound thread named only
    "dwarf 5407" for äs Oslanlumash, whose name the Store has at
    every full sample, and the model then wrote that there is no
    name for him. The companion rule: a name first recorded
    after the day (the migrants', 06-28) must not land on an
    earlier day's feed."""

    def _sample_kwargs(self, **over):
        kw = dict(profession="", mood=-1, mood_name="none",
                  stress_level=40000, stress_category=3, needs=[],
                  wounds=[], job="", relations=[])
        kw.update(over)
        return kw

    def test_lite_thread_resolves_name_from_earlier_full_sample(self):
        # äs, 06-02: full samples named at 101323 and 115166,
        # lite curr at 169650 wounded with no name.
        store = FakeStore()
        store.add_unit(5407, 101323, name="äs Oslanlumash",
                       **self._sample_kwargs(
                           profession="Woodcutter"))
        store.add_unit(5407, 115166, name="äs Oslanlumash",
                       **self._sample_kwargs(
                           profession="Woodcutter"))
        store.add_unit(5407, 169650, name="",
                       **self._sample_kwargs(
                           wounds=[{"id": 7, "parts": 1}]))
        threads = diary.open_threads(store, 169200, 125)
        wounded = [t for t in threads if t["kind"] == "wounded"]
        self.assertEqual(len(wounded), 1)
        self.assertEqual(wounded[0]["subject"], "äs Oslanlumash")

    def test_lite_thread_keeps_uid_when_no_full_sample_ever(self):
        # A migrant on 06-02: lite samples only, no full sample
        # ever — the thread keeps "dwarf {uid}", never a name
        # invented from nothing.
        store = FakeStore()
        store.add_unit(1700, 169650, name="",
                       **self._sample_kwargs(
                           wounds=[{"id": 7, "parts": 1}]))
        threads = diary.open_threads(store, 169200, 125)
        wounded = [t for t in threads if t["kind"] == "wounded"]
        self.assertEqual(len(wounded), 1)
        self.assertEqual(wounded[0]["subject"], "dwarf 1700")

    def test_lite_feed_resolves_name_from_earlier_full_sample(self):
        store = FakeStore()
        store.add_unit(5407, 115166, name="äs Oslanlumash",
                       **self._sample_kwargs(
                           profession="Woodcutter"))
        store.add_unit(5407, 169650, name="",
                       **self._sample_kwargs(
                           wounds=[{"id": 7, "parts": 1}]))
        lite = diary._lite_dwarf_feed(store, 169200, 10, 125)
        recs = [r for r in lite["records"]
                if r.get("unit_id") == 5407]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["name"], "äs Oslanlumash")

    def test_lite_feed_ignores_full_sample_after_day_end(self):
        # The migrant's name is first recorded at 201600
        # (06-28); a 06-02 lite feed must not use it — the
        # record keeps "an unnamed migrant".
        store = FakeStore()
        store.add_unit(1700, 169650, name="",
                       **self._sample_kwargs(
                           wounds=[{"id": 7, "parts": 1}]))
        store.add_unit(1700, 201600, name="Cog Letmossazir",
                       **self._sample_kwargs(
                           profession="Miner"))
        lite = diary._lite_dwarf_feed(store, 169200, 10, 125)
        recs = [r for r in lite["records"]
                if r.get("unit_id") == 1700]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["name"], "an unnamed migrant")


class TestGroupCountsAfterRename(unittest.TestCase):
    """The counts lines must name the dwarves the dwarf lines
    name. The counts are computed before the known-names rename,
    so without a recompute they still say "an unnamed migrant"
    for a dwarf the feed has since named (re-check 7: the 06-20
    counts said "an unnamed migrant" while the dwarf lines named
    Litast, Zasit, and Cog)."""

    def test_counts_use_the_renamed_name(self):
        # A lite-sampled migrant, wounded, named only by a
        # citizen_new event at the day start: the rename fires,
        # so the counts must carry the new name, not the old
        # "an unnamed migrant".
        store = FakeStore()
        store.add_unit(1700, 169650, name="",
                       profession="", mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[{"id": 7, "parts": 1}],
                       job="", relations=[])
        with tempfile.TemporaryDirectory() as tmp:
            events = Path(tmp) / "events.jsonl"
            events.write_text(
                json.dumps({"type": "citizen_new", "tick": 169200,
                            "year": 125, "at": 1795700000,
                            "source": "poll",
                            "data": {"unit_id": 1700,
                                     "name": "Cog Letmossazir",
                                     "profession": "Miner"}}) + "\n")
            feed = diary.build_diary_feed(
                store, FakeJournal(), 169200, "Erushtathtat", 125,
                state_dir=tmp, population=10)
        names = [r.get("name") for r in feed["dwarves"]]
        self.assertIn("Cog Letmossazir", names)
        for g in feed["group_counts"]:
            self.assertNotIn("an unnamed migrant", g["names"])
            self.assertNotIn("an unnamed migrant", g["not_names"])
        wounded = [g for g in feed["group_counts"]
                   if g["key"] == "wounded"][0]
        self.assertEqual(wounded["names"], ["Cog Letmossazir"])
        # The lite path's total is the ledger headcount, not
        # len(dwarves): the recompute must preserve it.
        self.assertEqual(wounded["total"], 10)


class TestFeedCoverage(unittest.TestCase):
    def test_coverage_counts_in_day_samples_and_latest(self):
        feed = diary.build_diary_feed(_olons(), FakeJournal(),
                                      100800, "Erushtathtat", 125)
        cov = feed["coverage"]
        self.assertEqual(cov["day_start_tick"], 100800)
        self.assertEqual(cov["samples"]["full_in_day"], 2)
        self.assertEqual(cov["samples"]["lite_in_day"], 0)
        self.assertEqual(cov["samples"]["latest_tick"], 101999)
        self.assertEqual(cov["samples"]["latest_date"], "125-04-01")
        # No state dir and no journal path: the bus file is absent.
        self.assertFalse(cov["bus"]["present"])
        self.assertIsNone(cov["bus"]["first_tick"])

    def test_coverage_lite_samples_in_day_are_counted(self):
        store = FakeStore()
        store.add_unit(101, 99500, name="Olon Medtobalod",
                       profession="Brewer", mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[], job="Brewer",
                       relations=[])
        # Lite: job only, no name, relations, or needs.
        store.add_unit(102, 100900, job="Drink2")
        store.add_trend("drink", 99500, 38)
        feed = diary.build_diary_feed(store, FakeJournal(),
                                      100800, "Erushtathtat", 125)
        cov = feed["coverage"]["samples"]
        self.assertEqual(cov["full_in_day"], 0)
        self.assertEqual(cov["lite_in_day"], 1)
        self.assertEqual(cov["latest_tick"], 100900)
        self.assertEqual(cov["latest_date"], "125-04-01")

    def test_coverage_latest_before_day_when_no_sample_in_day(self):
        store = FakeStore()
        store.add_unit(101, 99500, name="Olon Medtobalod",
                       profession="Brewer", mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[], job="Brewer",
                       relations=[])
        store.add_trend("drink", 99500, 38)
        feed = diary.build_diary_feed(store, FakeJournal(),
                                      100800, "Erushtathtat", 125)
        cov = feed["coverage"]["samples"]
        self.assertEqual(cov["full_in_day"], 0)
        self.assertEqual(cov["lite_in_day"], 0)
        self.assertEqual(cov["latest_tick"], 99500)
        self.assertEqual(cov["latest_date"], "125-03-27")


class TestPromptCoverage(unittest.TestCase):
    def _feed(self, coverage, has_events=False, day_start=181200):
        # A store sampled only before the day (06-03), so the
        # feed's own samples coverage is the stale shape; the
        # bus/watch coverage is set by the caller.
        store = FakeStore()
        store.add_unit(101, 171344, name="Olon Medtobalod",
                       profession="Brewer", mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[], job="Brewer",
                       relations=[])
        store.add_trend("drink", 171344, 6)
        feed = diary.build_diary_feed(store, FakeJournal(),
                                      day_start, "Erushtathtat", 125)
        feed["coverage"].update(coverage)
        feed["events"] = {"has_events": has_events}
        return feed

    def test_prompt_states_dead_sources_and_what_is_unknown(self):
        # 06-12: the bus runs to 07-08 and the watch log to 06-14,
        # so neither has a record in the day; the per-dwarf
        # samples end 06-03.
        feed = self._feed({
            "bus": {"present": True, "first_tick": 100800,
                    "last_tick": 210526, "in_day": 0},
            "watch": {"present": True, "first_tick": 100800,
                      "last_tick": 183723, "in_day": 0},
        })
        user = diary.diary_prompt(feed)[1]["content"]
        self.assertIn("Record for this day:", user)
        self.assertIn("No bus event log record exists for this "
                      "day.", user)
        self.assertIn("No watch log record exists for this day.",
                      user)
        self.assertIn("No per-dwarf sample falls in this day — the "
                      "last record is from 3rd of Galena, 125.", user)
        self.assertIn("Write two or three lines from the decisions "
                      "and the last dated record, and stop.", user)
        # The old branch that conflated dead sources with a quiet
        # day is gone when coverage is present.
        self.assertNotIn("No event record exists for this day", user)

    def test_prompt_source_ended_before_the_day_says_so(self):
        # 06-20: the watch log ended 06-14, before the day; the
        # bus runs past it with no record in the day.
        feed = self._feed({
            "bus": {"present": True, "first_tick": 100800,
                    "last_tick": 210526, "in_day": 0},
            "watch": {"present": True, "first_tick": 100800,
                      "last_tick": 183723, "in_day": 0},
        }, day_start=187200)
        user = diary.diary_prompt(feed)[1]["content"]
        self.assertIn("The watch log ends on 14th of Galena, 125",
                      user)
        self.assertIn("No bus event log record exists for this "
                      "day.", user)

    def test_prompt_names_the_litast_bad_example(self):
        # Re-check 7 P1: the old 06-12 entry named Litast eating
        # on the 12th, but his name was first recorded on the 1st
        # of Limestone. The rule names the case so a future
        # rewrite does not repeat it. The rule lives in the
        # system message, not the user facts.
        feed = self._feed({
            "bus": {"present": True, "first_tick": 100800,
                    "last_tick": 210526, "in_day": 0},
            "watch": {"present": True, "first_tick": 100800,
                      "last_tick": 183723, "in_day": 0},
        })
        system = diary.diary_prompt(feed)[0]["content"]
        self.assertIn("Litast Aknûnònul", system)
        self.assertIn("1st of Limestone", system)

    def test_prompt_live_but_quiet_day_says_so(self):
        # The per-dwarf record covers the day, but no event was
        # recorded for it. The old instruction ("The record is
        # live and nothing happened today") asserted something
        # false — the record is lossy, and a same-day first
        # sighting IS something happening (re-check 8).
        feed = self._feed({
            "bus": {"present": True, "first_tick": 100800,
                    "last_tick": 210526, "in_day": 0},
            "watch": {"present": True, "first_tick": 100800,
                      "last_tick": 210526, "in_day": 0},
            "samples": {"full_in_day": 1, "lite_in_day": 0,
                        "latest_tick": 181500,
                        "latest_date": "125-06-12"},
        })
        user = diary.diary_prompt(feed)[1]["content"]
        self.assertIn("The per-dwarf record covers this day. "
                      "Write two or three lines from the "
                      "per-dwarf record, and stop.", user)
        self.assertNotIn("nothing happened today", user)
        self.assertIn("Full per-dwarf samples exist for this day.",
                      user)
        self.assertNotIn("Write two or three lines from the "
                         "decisions", user)

    def test_prompt_coverage_present_with_events_has_no_instruction(self):
        feed = self._feed({
            "bus": {"present": True, "first_tick": 100800,
                    "last_tick": 210526, "in_day": 3},
            "watch": {"present": True, "first_tick": 100800,
                      "last_tick": 210526, "in_day": 3},
        }, has_events=True)
        user = diary.diary_prompt(feed)[1]["content"]
        self.assertIn("Record for this day:", user)
        self.assertNotIn("Write two or three lines", user)
        self.assertNotIn("nothing happened today", user)


class TestPrompt(unittest.TestCase):
    def test_prompt_names_the_featured_dwarf_and_forbids_lists(self):
        feed = diary.build_diary_feed(_olons(), FakeJournal(),
                                      100800, "Erushtathtat", 125)
        messages = diary.diary_prompt(feed)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Never a bullet list", messages[0]["content"])
        self.assertIn("Olon Medtobalod", messages[1]["content"])
        self.assertIn("FEATURED", messages[1]["content"])
        # No raw Store rows leak into the prompt.
        self.assertNotIn("unit_id", messages[1]["content"])
        self.assertNotIn("stress_category", messages[1]["content"])

    def test_prompt_forbids_carrying_old_claims_forward(self):
        # Run #17: the entry invented a manager appointment and
        # credited the brewing to Olon by carrying forward an old
        # entry's claims. The system prompt must forbid carrying
        # a claim from a recent entry unless today's facts
        # confirm it.
        feed = diary.build_diary_feed(_olons(), FakeJournal(),
                                      100800, "Erushtathtat", 125)
        messages = diary.diary_prompt(feed)
        system = messages[0]["content"]
        self.assertIn("recent entries are from EARLIER days",
                      system)
        self.assertIn("unless TODAY'S facts confirm it", system)
        self.assertIn("Name a dwarf as doing a job only if today's "
                      "facts name them doing it", system)

    def test_prompt_forbids_overgeneralising_counts(self):
        # Run 060346: the feed said six of seven dwarves were
        # wounded (Ral has no wound) and the AI wrote "every dwarf
        # ... carrying an injury ... One apiece." The system prompt
        # must make the AI count carefully.
        feed = diary.build_diary_feed(_olons(), FakeJournal(),
                                      100800, "Erushtathtat", 125)
        messages = diary.diary_prompt(feed)
        system = messages[0]["content"]
        self.assertIn("Count carefully", system)
        self.assertIn("Six wounded out of seven is six", system)
        self.assertIn("only if the facts say all of them", system)

    def test_prompt_carries_precomputed_counts(self):
        # The feed now carries the counts, so the AI reads the
        # number (and the complement) instead of inferring it.
        feed = diary.build_diary_feed(_seven(), FakeJournal(),
                                      100800, "Erushtathtat", 125)
        user = diary.diary_prompt(feed)[1]["content"]
        self.assertIn("Counts (read these", user)
        self.assertIn("Wounded: 6 of 7", user)
        self.assertIn("Not wounded: Ral", user)

    def test_prompt_groups_queued_jobs_by_workshop(self):
        # Run 060346: make_bed x1 + make_barrel x2 became "set one
        # job running". The feed now groups queued jobs by
        # workshop with counts per job type.
        journal = FakeJournal()
        journal.add_decision(
            100900,
            "queue make_bed x1 at the Carpenters workshop #7",
            action="queue_job", ok=True)
        journal.add_decision(
            100950,
            "queue make_barrel x2 at the Carpenters workshop #7",
            action="queue_job", ok=True)
        feed = diary.build_diary_feed(_seven(), journal,
                                      100800, "Erushtathtat", 125)
        user = diary.diary_prompt(feed)[1]["content"]
        self.assertIn(
            "Queued at the Carpenters workshop #7: make_bed x1, "
            "make_barrel x2 (3 jobs total; needs 3 wood)", user)

    def test_prompt_marks_preexisting_deity_not_new(self):
        # "Found a god today": the deity links are pre-existing
        # (embark), not found today. The feed marks them
        # long-standing; a bond gained today is marked new.
        feed = diary.build_diary_feed(_seven(), FakeJournal(),
                                      100800, "Erushtathtat", 125)
        user = diary.diary_prompt(feed)[1]["content"]
        self.assertIn("a long-standing devotion, not new today",
                      user)
        self.assertIn("close to friend Mestthos", user)
        self.assertIn("(new today)", user)

    def test_prompt_marks_preexisting_wound_since(self):
        # A wound present in both samples is background: the line
        # carries "(since before today)", not a "wounded today"
        # and not a since-date. Re-check 3 (2026-11-27): the
        # wound is already true at the store's first sample, so
        # dating it "since 125-04-01" made the diary claim it
        # was taken that day (Rakust, on the real 04-01). The
        # start predates the record, so the line says so.
        feed = diary.build_diary_feed(_seven(), FakeJournal(),
                                      100800, "Erushtathtat", 125)
        user = diary.diary_prompt(feed)[1]["content"]
        self.assertIn("1 wound (since before today)", user)
        self.assertNotIn("1 wound (since 125-04-01)", user)

    def test_prompt_marks_ongoing_need(self):
        # Olon's Drink need is in both samples (unchanged): it is
        # ongoing, not new today.
        feed = diary.build_diary_feed(_seven(), FakeJournal(),
                                      100800, "Erushtathtat", 125)
        user = diary.diary_prompt(feed)[1]["content"]
        self.assertIn("going without drink (ongoing, not new today)",
                      user)


class TestFinalizeDecisions(unittest.TestCase):
    def test_queue_same_job_twice_aggregates(self):
        # Two "queue make_bed x1" actions are two beds, not one
        # story beat.
        decs, _ = diary._finalize_decisions([
            {"decision": "queue make_bed x1 at building #7",
             "action": "queue_job", "ok": True},
            {"decision": "queue make_bed x1 at building #7",
             "action": "queue_job", "ok": True},
        ])
        self.assertEqual(len(decs), 1)
        self.assertEqual(decs[0]["decision"],
                         "queue make_bed x2 at building #7")

    def test_queue_different_jobs_stay_separate(self):
        decs, _ = diary._finalize_decisions([
            {"decision": "queue make_bed x1 at building #7",
             "action": "queue_job", "ok": True},
            {"decision": "queue make_barrel x2 at building #7",
             "action": "queue_job", "ok": True},
        ])
        self.assertEqual(len(decs), 2)
        self.assertEqual(decs[0]["decision"],
                         "queue make_bed x1 at building #7")
        self.assertEqual(decs[1]["decision"],
                         "queue make_barrel x2 at building #7")

    def test_queue_outcome_change_is_retry(self):
        decs, _ = diary._finalize_decisions([
            {"decision": "queue make_bed x1 at building #7",
             "action": "queue_job", "ok": False},
            {"decision": "queue make_bed x1 at building #7",
             "action": "queue_job", "ok": True},
        ])
        self.assertEqual(len(decs), 2)
        self.assertTrue(decs[1].get("retry"))

    def test_finalize_is_idempotent(self):
        decs, _ = diary._finalize_decisions([
            {"decision": "queue make_bed x1 at building #7",
             "action": "queue_job", "ok": True},
            {"decision": "queue make_bed x1 at building #7",
             "action": "queue_job", "ok": True},
        ])
        again, _ = diary._finalize_decisions(decs)
        self.assertEqual(len(again), 1)
        self.assertEqual(again[0]["decision"],
                         "queue make_bed x2 at building #7")


class TestValidateGroupClaims(unittest.TestCase):
    def _feed(self):
        return diary.build_diary_feed(_seven(), FakeJournal(),
                                      100800, "Erushtathtat", 125)

    def test_all_wounded_claim_rejected(self):
        # The run-060346 error, verbatim in shape: six of seven
        # wounded, the entry said every dwarf was.
        feed = self._feed()
        bad = ("Lor spent the day at the still while every dwarf "
               "in the fort is carrying an injury today, all seven "
               "of them hurting and none of them sound. I watched "
               "Lor from the doorway and said nothing at all.")
        with self.assertRaises(ValueError):
            diary._validate_ai_entry(bad, feed)

    def test_none_wounded_claim_rejected(self):
        feed = self._feed()
        bad = ("Lor spent the day at the still and none of the "
               "dwarves was wounded, not one of them hurt at all. "
               "I watched Lor from the doorway and said nothing.")
        with self.assertRaises(ValueError):
            diary._validate_ai_entry(bad, feed)

    def test_corrected_counts_entry_accepted(self):
        # The corrected 04-01 entry: six wounded, Ral unmarked.
        feed = self._feed()
        good = ("Lor spent the day at the still, six of the dwarves "
                "wounded and Ral the only one unmarked, and the "
                "fort held together through the evening. I watched "
                "Lor from the doorway and said nothing at all.")
        body = diary._validate_ai_entry(good, feed)
        self.assertIn("Ral", body)

    def test_compound_sentence_with_comma_not_rejected(self):
        # "All seven are here, and six are wounded" does not claim
        # all are wounded — the comma guard keeps the validator
        # from firing on a compound sentence.
        feed = self._feed()
        good = ("Lor spent the day at the still. All seven dwarves "
                "are here, and six are wounded, Ral the only one "
                "unmarked. I watched Lor from the doorway and said "
                "nothing at all.")
        body = diary._validate_ai_entry(good, feed)
        self.assertIn("Ral", body)

    def test_every_but_exception_not_rejected(self):
        # "Every dwarf but Ral is carrying an injury" is TRUE when
        # six of seven are wounded — it is the corrected 04-01
        # entry's own phrasing, and the validator must accept it.
        feed = self._feed()
        good = ("Lor spent the day at the still. Every dwarf but "
                "Ral is carrying an injury today, one apiece, and "
                "Ral is the only one unmarked. I watched Lor from "
                "the doorway and said nothing at all.")
        body = diary._validate_ai_entry(good, feed)
        self.assertIn("Ral", body)


# The exact 125-04-05 entry text, verbatim from diary.md (the
# retry-path entry that got nearly every number wrong). Shared
# with tests/test_server.py, which posts a retry-shaped body
# carrying this text to the route to prove the retry path runs
# the identical validation as the live path.
EXACT_0405_ENTRY = (
    "The 5th of Hematite, 125, Summer.\n\n"
    "Seven dwarves and seven wounds. I counted them twice "
    "because the first count seemed too tidy to be true, "
    "and it held: every soul in this fort is carrying "
    "exactly one mark of something, all of them stable, "
    "none of them slowing down. One of them is out at the "
    "water working the fish. The rest do whatever it is "
    "they do when I am not watching, which is most of it. "
    "Nobody has come to me about the wounds and I have "
    "decided that is a kind of answer.\n\n"
    "The brewing landed. Drink is back up to thirty-nine "
    "from thirty-three, which means Mestthos's hands have "
    "been busy at the still I put up, and the fort will "
    "drink tomorrow without me doing arithmetic at "
    "midnight. Food holds at thirty-two. Wood sits at a "
    "hundred and twenty-four, patient as ever. Stone "
    "remains a clean and honest nothing, and I have "
    "stopped taking it personally.\n\n"
    "I set one job going at one of the workshops today "
    "and it actually came back finished, which around here "
    "counts as an event worth writing down. Small "
    "mercies.\n\n"
    "So: a fort of the lightly damaged, all of them "
    "upright, all of them working, and a still that "
    "produces. I will take it.")


class TestValidateNumbers(unittest.TestCase):
    """_check_numbers: the 04-05 entry's numbers were wrong in
    every line (drink 39 from 33 vs 68, food 32 vs 25, wood 124 vs
    122, "seven wounds" vs 1, "one job" vs 9) and the old validator
    checked none of them — it only understood all/none phrasings.
    The numbers validator checks every stated number against the
    feed (the same facts the model was shown). A number the feed
    cannot verify is skipped, never guessed."""

    def _feed(self, drink=(68, 68), food=(25, 25),
              wood=(122, 121), stone=(0, 0), population=(7, 7),
              wounded=1, idle=0, arrivals=0, decisions=()):
        start = {}
        end = {}
        for metric, pair in (("drink", drink), ("food", food),
                             ("wood", wood), ("stone", stone)):
            if pair is not None:
                start[metric], end[metric] = pair
        start["population"], end["population"] = population
        return {
            "summary": {
                "stocks_start": start, "stocks_end": end,
                "arrivals": arrivals,
                "decisions": list(decisions),
            },
            "group_counts": [
                {"key": "wounded", "count": wounded, "total": 7,
                 "names": ["Lor"] if wounded else [],
                 "not_names": []},
                {"key": "idle", "count": idle, "total": 7,
                 "names": [], "not_names": []},
            ],
            "dwarves": [{"name": "Lor Medtobalod",
                         "featured": True}],
        }

    def _body(self, text):
        # Prose, long enough to pass the length check, naming the
        # featured dwarf.
        return (text + " Lor watched the fort from the doorway and "
                "said nothing at all through the long evening, "
                "while the dwarves went about their work in "
                "silence.")

    def _queue(self):
        # The 04-05 run's queue: 4 queue actions, 9 jobs.
        return [
            {"action": "queue_job",
             "decision": "queue make_barrel x2 at Carpenters "
                         "workshop #7"},
            {"action": "queue_job",
             "decision": "queue brew x2 at Still #8"},
            {"action": "queue_job",
             "decision": "queue make_bed x2 at Carpenters "
                         "workshop #7"},
            {"action": "queue_job",
             "decision": "queue make_bed x3 at Carpenters "
                         "workshop #7"},
        ]

    def test_0405_numbers_rejected(self):
        # The 04-05 entry's numbers, verbatim in shape: every one
        # is an old entry's number, not the run's.
        feed = self._feed()
        bad = self._body(
            "Drink is back up to thirty-nine from thirty-three. "
            "Food holds at thirty-two. Wood sits at a hundred and "
            "twenty-four.")
        with self.assertRaises(ValueError) as ctx:
            diary._validate_ai_entry(bad, feed)
        self.assertIn("drink", str(ctx.exception))

    def test_correct_numbers_accepted(self):
        feed = self._feed()
        good = self._body(
            "Drink holds at sixty-eight. Food holds at twenty-five. "
            "Wood sits at a hundred and twenty-one. Stone remains "
            "a clean and honest nothing.")
        body = diary._validate_ai_entry(good, feed)
        self.assertIn("sixty-eight", body)

    def test_from_to_end_off_by_one_rejected(self):
        # 04-01: the entry said drink ended at 33; the run-end
        # snapshot says 34. An off-by-one is still wrong.
        feed = self._feed(drink=(38, 34))
        bad = self._body(
            "The drink stores went from thirty-eight down to "
            "thirty-three.")
        with self.assertRaises(ValueError) as ctx:
            diary._validate_ai_entry(bad, feed)
        self.assertIn("33", str(ctx.exception))
        good = self._body(
            "The drink stores went from thirty-eight down to "
            "thirty-four.")
        diary._validate_ai_entry(good, feed)

    def test_digit_numbers_checked(self):
        feed = self._feed()
        bad = self._body("Drink holds at 39.")
        with self.assertRaises(ValueError):
            diary._validate_ai_entry(bad, feed)
        good = self._body("Drink holds at 68.")
        diary._validate_ai_entry(good, feed)

    def test_unverifiable_metric_skipped(self):
        # No food value in the feed: the validator does not guess,
        # so a food number it cannot check is accepted.
        feed = self._feed(food=None)
        body = self._body("Food holds at thirty-two.")
        diary._validate_ai_entry(body, feed)

    def test_bare_wound_count_rejected(self):
        # "Seven dwarves and seven wounds" vs 1 wounded in the
        # feed. The population claim (7) is right; the wound
        # count is not.
        feed = self._feed(wounded=1)
        bad = self._body(
            "Seven dwarves and seven wounds, every soul in this "
            "fort carrying exactly one mark of something.")
        with self.assertRaises(ValueError) as ctx:
            diary._validate_ai_entry(bad, feed)
        self.assertIn("wounded", str(ctx.exception))

    def test_correct_bare_wound_count_accepted(self):
        feed = self._feed(wounded=6)
        good = self._body(
            "Six of the dwarves wounded and Ral the only one "
            "unmarked, and six wounds between them.")
        diary._validate_ai_entry(good, feed)

    def test_mark_synonym_all_claim_rejected(self):
        # "mark" was not in the old wound keyword list, so the
        # 04-05 "exactly one mark" phrasing sailed through.
        feed = self._feed(wounded=1)
        bad = self._body(
            "Every soul in this fort is carrying exactly one mark "
            "of something, all of them stable.")
        with self.assertRaises(ValueError):
            diary._validate_ai_entry(bad, feed)

    def test_one_apiece_not_a_count_claim(self):
        # "one wound apiece" is per-dwarf, not a claim that one
        # dwarf is wounded — the guard must keep accepting it.
        feed = self._feed(wounded=6)
        good = self._body(
            "Every dwarf but Ral is carrying an injury today, one "
            "wound apiece, and Ral is the only one unmarked.")
        diary._validate_ai_entry(good, feed)

    def test_job_total_rejected(self):
        # 04-05: "one job ... came back finished" vs 9 queued.
        feed = self._feed(decisions=self._queue())
        bad = self._body(
            "I set one job going at one of the workshops today and "
            "it actually came back finished.")
        with self.assertRaises(ValueError) as ctx:
            diary._validate_ai_entry(bad, feed)
        self.assertIn("9", str(ctx.exception))

    def test_job_per_type_counts(self):
        feed = self._feed(decisions=self._queue())
        bad = self._body(
            "Two beds and two barrels in the queue at the "
            "carpenters, and the still waiting.")
        with self.assertRaises(ValueError):
            diary._validate_ai_entry(bad, feed)
        good = self._body(
            "Five beds and two barrels in the queue at the "
            "carpenters, and two brewings in the queue at the "
            "still.")
        diary._validate_ai_entry(good, feed)

    def test_no_drink_zero_claim(self):
        feed = self._feed(drink=(6, 0))
        good = self._body(
            "There is no drink left in the fort, and the barrels "
            "stand empty.")
        diary._validate_ai_entry(good, feed)
        feed = self._feed(drink=(68, 68))
        bad = self._body(
            "There is no drink left in the fort, and the barrels "
            "stand empty.")
        with self.assertRaises(ValueError):
            diary._validate_ai_entry(bad, feed)

    def test_population_checked(self):
        feed = self._feed(population=(7, 7))
        diary._validate_ai_entry(
            self._body("Seven dwarves held the fort together."),
            feed)
        with self.assertRaises(ValueError):
            diary._validate_ai_entry(
                self._body("Ten citizens held the fort together."),
                feed)

    def test_arrivals_checked(self):
        feed = self._feed(arrivals=3)
        diary._validate_ai_entry(
            self._body("Three new citizens arrived today, "
                       "strangers to us all."),
            feed)
        feed = self._feed(arrivals=0)
        with self.assertRaises(ValueError):
            diary._validate_ai_entry(
                self._body("Three new citizens arrived today, "
                           "strangers to us all."),
                feed)

    def test_exact_0405_entry_rejected(self):
        # THE bar for the validator (Mikey, 2026-11-27: "we really
        # need to nail the diary stuff"): the exact 125-04-05
        # entry text, verbatim from diary.md, against that day's
        # feed (run stocks: drink 68, food 25, wood 122->121,
        # 1 wounded of 7, 9 jobs queued). It must FAIL — drink
        # "39 from 33", food 32, wood 124, "seven wounds", "one
        # job" are all old entries' numbers, not the run's. If
        # this test ever passes, the validator is not good enough.
        feed = self._feed(decisions=self._queue())
        feed["dwarves"] = [{"name": "Mestthos", "featured": True}]
        with self.assertRaises(ValueError) as ctx:
            diary._validate_ai_entry(EXACT_0405_ENTRY, feed)
        self.assertIn("wounded", str(ctx.exception))

    def test_partitive_total_is_not_a_count(self):
        # The 04-01 probe false positive: "Six of the seven are
        # carrying wounds" — the SEVEN is the total, not the
        # count. The six is checked (6 == 6) and the seven is
        # skipped. Same for "Five of the seven sat idle".
        feed = self._feed(drink=(38, 37), wounded=6, idle=5)
        good = self._body(
            "Six of the seven are carrying wounds. Five of the "
            "seven sat idle.")
        diary._validate_ai_entry(good, feed)
        # But a wrong count in the same construction still fails.
        feed = self._feed(drink=(38, 37), wounded=5, idle=5)
        bad = self._body(
            "Six of the seven are carrying wounds. Five of the "
            "seven sat idle.")
        with self.assertRaises(ValueError):
            diary._validate_ai_entry(bad, feed)

    def test_carried_wounds_is_a_group_count(self):
        # "Six dwarves carried wounds" is a wound count, not a
        # population claim — the group check owns it, and the
        # population check must not fire on the same sentence.
        feed = self._feed(wounded=6)
        good = self._body("Six dwarves carried wounds through "
                          "the long day.")
        diary._validate_ai_entry(good, feed)
        feed = self._feed(wounded=1)
        with self.assertRaises(ValueError):
            diary._validate_ai_entry(good, feed)

    def test_bare_population_still_checked(self):
        # No condition word after the noun: "Six dwarves held
        # the fort" IS a population claim, and 6 != 7 fails.
        feed = self._feed(population=(7, 7))
        bad = self._body("Six dwarves held the fort together "
                         "through the day.")
        with self.assertRaises(ValueError):
            diary._validate_ai_entry(bad, feed)

    def test_number_scanner(self):
        self.assertEqual(
            [v for v, _, _ in diary._find_numbers("thirty-nine")],
            [39])
        self.assertEqual(
            [v for v, _, _ in
             diary._find_numbers("a hundred and twenty-four")],
            [124])
        self.assertEqual(
            [v for v, _, _ in diary._find_numbers("one and two")],
            [1, 2])
        self.assertEqual(
            [v for v, _, _ in diary._find_numbers("drink 68")],
            [68])
        self.assertEqual(diary._find_numbers("a dwarf"), [])
        self.assertEqual(diary._find_numbers("the first dwarf"), [])
        # Digit ordinals are dates, not quantities: "the 12th"
        # is no number at all, and a dated ledger interval keeps
        # only its stock numbers ("drink 6 on the 12th" is 6).
        self.assertEqual(diary._find_numbers("the 12th"), [])
        self.assertEqual(diary._find_numbers("the 20th"), [])
        self.assertEqual(diary._find_numbers("the 1st"), [])
        self.assertEqual(diary._find_numbers("the 2nd"), [])
        self.assertEqual(diary._find_numbers("the 3rd"), [])
        self.assertEqual(
            [v for v, _, _ in diary._find_numbers(
                "drink 6 on the 12th")],
            [6])

    def test_number_scanner_stops_at_sentence_boundary(self):
        # "thirty-three. Six of the seven" is 33 and 6, not 39:
        # the run must not swallow the next sentence's first
        # number word. The 04-02 entry failed validation on this
        # (the parser read its "thirty-three" as 39 and the
        # validator rejected a correct drink count).
        self.assertEqual(
            [v for v, _, _ in diary._find_numbers(
                "Drink came down two, from thirty-five to "
                "thirty-three. Six of the seven are carrying a "
                "wound.")],
            [2, 35, 33, 6, 7])
        self.assertEqual(
            [v for v, _, _ in diary._find_numbers(
                "thirty-three\nSix dwarves held the fort")],
            [33, 6])
        self.assertEqual(
            [v for v, _, _ in diary._find_numbers(
                "thirty-three! Six dwarves held the fort")],
            [33, 6])


class TestAIWriter(unittest.TestCase):
    GOOD = ("Olon Medtobalod spent the day at the still, his hands "
            "shaking a little more with each hour that passed "
            "without a drink. The barrels stood empty and his thirst "
            "gnawed at him, and by evening he was snapping at the "
            "others for no reason at all. I watched him from the "
            "doorway and said nothing. There is nothing to say when "
            "a dwarf is thirsty and the fort has nothing to give.")

    def test_good_entry_is_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            feed = diary.build_diary_feed(
                _olons(), FakeJournal(), 100800, "Erushtathtat",
                125, state_dir=state)
            client = StubClient(self.GOOD)
            path = diary.write_ai_entry(client, feed, state)
            text = path.read_text()
            self.assertIn("Olon Medtobalod", text)
            self.assertIn("shaking", text)
            self.assertIn("## 125-04-01", text)

    def test_ledger_line_appended_and_round_trips(self):
        # The stored AI entry carries the day's ledger line (the
        # same line the template renderer writes), so a later
        # rebuild recovers the numbers from the entry instead of
        # the Store's stale trend sample.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            feed = diary.build_diary_feed(
                _olons(), FakeJournal(), 100800, "Erushtathtat",
                125, state_dir=state)
            path = diary.write_ai_entry(StubClient(self.GOOD),
                                        feed, state)
            body = path.read_text()
            self.assertIn("Drink: 38 -> 35", body)
            start, end = diary.ledger_stocks(body)
            self.assertEqual(start["drink"], 38)
            self.assertEqual(end["drink"], 35)

    def test_no_ledger_line_without_stocks(self):
        # A feed with no stocks at all gets no ledger line (an
        # empty line would parse as nothing, and a made-up one
        # would be worse).
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            feed = diary.build_diary_feed(
                _olons(), FakeJournal(), 100800, "Erushtathtat",
                125, state_dir=state)
            feed["summary"]["stocks_start"] = {}
            feed["summary"]["stocks_end"] = {}
            path = diary.write_ai_entry(StubClient(self.GOOD),
                                        feed, state)
            self.assertNotIn("Drink:", path.read_text())

    def test_list_entry_is_rejected_not_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            feed = diary.build_diary_feed(
                _olons(), FakeJournal(), 100800, "Erushtathtat",
                125, state_dir=state)
            listed = ("- Olon was stressed.\n- Olon was thirsty.\n"
                      "- Drink fell to 35.\n- Nothing else happened.")
            with self.assertRaises(ValueError):
                diary.write_ai_entry(StubClient(listed), feed, state)
            self.assertFalse((state / "diary.md").exists())

    def test_entry_naming_no_featured_dwarf_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            feed = diary.build_diary_feed(
                _olons(), FakeJournal(), 100800, "Erushtathtat",
                125, state_dir=state)
            bland = ("It was a quiet day in the fort. The dwarves "
                     "went about their business and nothing much "
                     "happened. The stocks held steady and everyone "
                     "seemed content enough with how things were.")
            with self.assertRaises(ValueError):
                diary.write_ai_entry(StubClient(bland), feed, state)
            self.assertFalse((state / "diary.md").exists())

    def test_debris_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            feed = diary.build_diary_feed(
                _olons(), FakeJournal(), 100800, "Erushtathtat",
                125, state_dir=state)
            dirty = self.GOOD + " (see PLANNER.md for details.)"
            with self.assertRaises(ValueError):
                diary.write_ai_entry(StubClient(dirty), feed, state)
            self.assertFalse((state / "diary.md").exists())

    def test_model_failure_raises_and_writes_nothing(self):
        class FailingClient:
            def chat(self, messages):
                raise RuntimeError("model unavailable")

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            feed = diary.build_diary_feed(
                _olons(), FakeJournal(), 100800, "Erushtathtat",
                125, state_dir=state)
            with self.assertRaises(RuntimeError):
                diary.write_ai_entry(FailingClient(), feed, state)
            self.assertFalse((state / "diary.md").exists())

    def test_rejected_entry_is_retried_with_correction(self):
        # The 04-05 class: the model writes a wrong number, the
        # validator rejects it, the model is told exactly what
        # was wrong and rewrites it. The day is written, not
        # skipped.
        class SequencedClient:
            def __init__(self, texts):
                self.texts = list(texts)
                self.calls = []

            def chat(self, messages):
                self.calls.append(list(messages))
                return self.texts.pop(0)

        wrong = (self.GOOD + " Drink holds at ninety-nine.")
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            feed = diary.build_diary_feed(
                _olons(), FakeJournal(), 100800, "Erushtathtat",
                125, state_dir=state)
            client = SequencedClient([wrong, self.GOOD])
            path = diary.write_ai_entry(client, feed, state)
            self.assertIn("Olon Medtobalod", path.read_text())
            self.assertEqual(len(client.calls), 2)
            retry = client.calls[1]
            self.assertTrue(any(
                m.get("role") == "user"
                and "rejected" in m.get("content", "")
                for m in retry))

    def test_rejected_entry_gives_up_after_max_attempts(self):
        # A model that keeps writing wrong numbers does not loop
        # forever: three attempts, then the day is skipped.
        class SequencedClient:
            def __init__(self, texts):
                self.texts = list(texts)
                self.calls = []

            def chat(self, messages):
                self.calls.append(list(messages))
                return self.texts.pop(0)

        wrong = (self.GOOD + " Drink holds at ninety-nine.")
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            feed = diary.build_diary_feed(
                _olons(), FakeJournal(), 100800, "Erushtathtat",
                125, state_dir=state)
            client = SequencedClient([wrong, wrong, wrong, wrong])
            with self.assertRaises(ValueError):
                diary.write_ai_entry(client, feed, state)
            self.assertEqual(len(client.calls), 3)
            self.assertFalse((state / "diary.md").exists())


class TestDiaryPromptVoice(unittest.TestCase):
    """The prompt rewrite (2026-11-27, Mikey: "the writing is
    stilted and weird, it's a prompting issue"). "Boatmurdered-
    style" as a style instruction produced pastiche — a faux-
    archaic overseer ("the fort declined both, quietly") — and
    the honesty instruction was satisfied with the same
    disclaimer sentence every entry ("I won't dress it up as
    this morning's news"), while open threads were copied
    verbatim ("Somebody should find water... Saying it again
    fills nothing" six times). The rewrite describes the
    qualities instead of naming the style, and tells the model
    to vary, to write only what is new, and never to repeat a
    sentence from a previous entry. Grounding stays as strong:
    the validator still guards every fact."""

    def _system(self):
        feed = diary.build_diary_feed(
            _olons(), FakeJournal(), 100800, "Erushtathtat", 125)
        msgs = diary.diary_prompt(feed)
        self.assertEqual(msgs[0]["role"], "system")
        return msgs[0]["content"]

    def test_no_style_label(self):
        self.assertNotIn("Boatmurdered", self._system())

    def test_voice_described_in_qualities(self):
        system = self._system()
        for phrase in ("plain, concrete, dry",
                       "A detail beats a flourish",
                       "never reaching for effect"):
            self.assertIn(phrase, system)

    def test_variation_rules_present(self):
        system = self._system()
        for phrase in ("NEVER repeat a sentence, a joke, or a "
                       "refrain from a previous entry",
                       "two or three lines when it did not",
                       "Never open with the date",
                       # Re-check 2: the old "say so once, plainly,
                       # in your own words" staleness rule was
                       # satisfied with a disclaimer move every
                       # entry. Superseded by the age-inside-the-
                       # sentence rule (no opening disclaimer, no
                       # sentence about what can/can't be claimed).
                       "put its age inside the sentence about the "
                       "fact it qualifies",
                       "Advance open threads or drop them",
                       "Never copy a thread line verbatim",
                       "Write only what is new or changed today"):
            self.assertIn(phrase, system)

    def test_grounding_rules_kept(self):
        system = self._system()
        for phrase in ("Every claim must come from the facts",
                       "Count carefully",
                       "Six wounded out of seven is six",
                       "Time is in the facts",
                       "Do not compress distinct actions into one",
                       "The entry is ABOUT THE DWARVES"):
            self.assertIn(phrase, system)

    def test_season_calendar_present(self):
        # Re-check 2026-11-27: 06-02 and 06-12 called Hematite
        # wounds "spring"; Hematite is summer. The prompt now
        # carries the DF season calendar so the model stops
        # mapping Earth seasons onto DF months.
        system = self._system()
        for phrase in ("Hematite, Malachite and Galena are summer",
                       "Limestone, Sandstone and Timber are autumn",
                       "A wound from Hematite is a summer wound",
                       "never call it spring"):
            self.assertIn(phrase, system)

    def test_profession_is_not_the_job(self):
        # Re-check 2026-11-27: 07-04 put Olon "at his jeweler's
        # bench" / "grinds facets" when the 07-03 record says
        # job Drink. Profession is what a dwarf IS, not what
        # they are DOING today.
        system = self._system()
        for phrase in ("A dwarf's profession is what they ARE, "
                       "not what they are DOING today",
                       "do not put tools in their hands",
                       "A jeweler who spent the day drinking was "
                       "drinking, not grinding facets"):
            self.assertIn(phrase, system)

    def test_repetition_rule_names_the_mechanism(self):
        # Re-check 2026-11-27: the "never repeat" rule was in
        # the prompt and still violated 8 times ("I will not
        # dress it up" x3, "went onto the slate" x3, "did not
        # walk down" x3+1, "ten pairs of idle hands" x2). The
        # rule now tells the model to read the recent entries
        # first and name the used-up phrases.
        system = self._system()
        for phrase in ("read the recent entries and note the exact "
                       "phrases they use",
                       "Do NOT reuse any of them",
                       "those phrases are used up"):
            self.assertIn(phrase, system)

    def test_shape_rules_break_the_skeleton(self):
        # Re-check 2 (strict bar, 2026-11-27): 0/13 entries pass
        # voice — the same skeleton every day (staleness
        # disclaimer, stocks, roll-call, thirsty list, closer),
        # quiet days padded with boilerplate instead of short,
        # near-twin entries 06-25/06-27. The prompt must break
        # the skeleton, not just ask for variety.
        system = self._system()
        for phrase in ("the entry is at most three lines",
                       "the ledger line below your entry already "
                       "carries the numbers",
                       "Do not paste the whole roster",
                       "Start with what happened",
                       "Do not list every dwarf's need, wound, "
                       "or job"):
            self.assertIn(phrase, system)

    def test_disclaimer_moves_banned(self):
        # Re-check 2: the model reworded "I will not dress it
        # up" into "I record it as it stands" / "that is all I
        # have" / "That is the sum of what I have" / "The first
        # is certain" / "the one figure I am sure of" — the same
        # hedge, five ways. The ban is on the move, not the
        # phrases.
        system = self._system()
        for phrase in ("Do not announce your uncertainty",
                       "Do not certify one figure as the sure one",
                       "Do not close with a summary of how little "
                       "you know"):
            self.assertIn(phrase, system)

    def test_vow_and_aphorism_banned(self):
        # Re-check 2: closing vow x3 (06-20, 06-22, 07-02),
        # aphoristic closers ("three throats, no barrel",
        # "Water would answer most of what ails this place"),
        # asides about the writing.
        system = self._system()
        for phrase in ("Never end with a vow about tomorrow",
                       "Never close with an aphorism or tagline",
                       "End on a fact, not a line"):
            self.assertIn(phrase, system)

    def test_hands_and_personification_banned(self):
        # Re-check 2: the hands image three times in different
        # words ("four pairs of empty hands", "all ten had idle
        # hands", "nine idle pairs of hands"); the book/ledger/
        # column personified ("the book doesn't say", "the
        # column has stopped carrying his name", "the truest
        # line in the book"); self-flagellation and blame
        # ("parched for weeks by my own hand").
        system = self._system()
        for phrase in ("Do not use \"hands\" as a word for idle "
                       "dwarves",
                       "Do not personify the book, the ledger, or "
                       "the column",
                       "Do not apologize for the fort, the book, "
                       "or yourself"):
            self.assertIn(phrase, system)

    def test_no_guessing_why(self):
        # Re-check 2: 06-28 "Perhaps they drank early and made
        # it last" — a guess about unrecorded behaviour,
        # presented as a "perhaps" and then disclaimed. 04-01
        # drew a conclusion a one-drink drop cannot support.
        system = self._system()
        for phrase in ("Do not guess why",
                       "\"Perhaps\" is still a guess",
                       "Do not draw a conclusion the numbers "
                       "don't support"):
            self.assertIn(phrase, system)

    def test_record_date_frame_banned_as_construction(self):
        # Re-check 3 (strict bar, 2026-11-27): 2/13 pass voice.
        # The new template was one frame seven times — "The last
        # per-dwarf record is the 3rd's", "The latest page on
        # the dwarves is the 21st's", "The twenty-third is the
        # last roll with names on it" — four of them opening the
        # entry. The prompt banned opening with the record's age
        # and the model moved the frame to the second sentence.
        # The frame itself is banned now, in every position,
        # with the 06-20 "On the 13th, …" form as the only
        # permitted one.
        system = self._system()
        for phrase in ("the record-date frame",
                       "it is banned in every position, not just "
                       "as an opening",
                       "The ONLY permitted form is the one above",
                       "A quiet day's two or three lines must be "
                       "the new facts"):
            self.assertIn(phrase, system)

    def test_disclaimer_sentence_banned_as_move(self):
        # Re-check 3: the disclaimer survived as new sentences
        # — "the figures beside this entry are the old ones
        # carried over" (06-25), "I have the counts for the day
        # and nothing attached to them" (04-05), "the rest of
        # the store I have not measured again" (07-02). The ban
        # is on the sentence's job, not the phrase list.
        system = self._system()
        for phrase in ("The ban is on the move, not the phrase "
                       "list",
                       "ANY sentence whose job is to say the "
                       "figures are old, carried over, not fresh, "
                       "or unmeasured is out",
                       "The age belongs inside a fact sentence or "
                       "nowhere at all"):
            self.assertIn(phrase, system)

    def test_stock_recitation_checkable_rule(self):
        # Re-check 3: stock recitation in prose x4 (04-02,
        # 04-05, 06-28, 07-07 — the last two verbatim
        # identical), despite "do not recite the full stock
        # list". The rule now has a checkable form: a stock may
        # be named only in a sentence that dates the change —
        # a same-day change, or a ledger interval with both
        # endpoint dates (re-check 8: the old example, "Drink
        # fell from nine to six", was the 06-12 sentence in
        # substance, an undated ten-day interval).
        system = self._system()
        for phrase in ("only in a sentence that dates the "
                       "change",
                       "A sentence that only states current "
                       "levels",
                       "must carry both endpoint dates"):
            self.assertIn(phrase, system)

    def test_drink_zero_closer_and_well_joke_banned(self):
        # Re-check 3: "There is no drink in the fort" closes
        # 06-27 and 07-07 verbatim, and 06-28 closes on the
        # well joke ("so there is no well, and the woodpile
        # does not change that") — a punchline about something
        # the fort lacks, not a fact.
        system = self._system()
        for phrase in ("Never end an entry on the drink-zero "
                       "fact",
                       "A quiet day's last line is its one new "
                       "fact, not the standing zero",
                       "Do not close on a joke or a punchline "
                       "about something the fort lacks",
                       "no well jokes"):
            self.assertIn(phrase, system)

    def test_queue_inference_banned(self):
        # Re-check 3: 04-05 "none of it was begun" — invented
        # from the queue's existence, contradicted by the run
        # snapshots (queue 28 -> 24, drink 33 -> 68). A queued job
        # is finished only when the day's events say it finished.
        system = self._system()
        for phrase in ("Never infer whether queued jobs were "
                       "begun or finished",
                       "The feed says what was queued, and the "
                       "events say what finished",
                       "do not say it was begun, unbegun, or "
                       "finished"):
            self.assertIn(phrase, system)

    def test_thirst_ordering_banned(self):
        # Re-check 3: 07-02 "Olon's trouble with it goes back
        # further than anyone else's" — Ral's thirst is
        # documented from the 06-03 record, Olon's first from
        # 06-21, and the feed carries no since-dates for thirst.
        # Grounding was checked and is impossible: the raw
        # thirst counters show Ral and Olon BOTH first crossing
        # 20000 at tick 101323 on 04-01, and both dropping below
        # threshold repeatedly after — no ordering between them
        # is groundable. So the prompt forbids the claim.
        system = self._system()
        for phrase in ("Never say one dwarf has been thirsty "
                       "longer than another",
                       "The feed carries no since-dates for "
                       "thirst",
                       "never rank them by duration"):
            self.assertIn(phrase, system)

    def test_record_meta_comment_and_yesterday_banned(self):
        # Re-check 3: 07-07 "the one line on it that reads
        # differently from the pages before" — an aside about
        # the record; 06-02 "The stores are where yesterday
        # left them" — asserts a yesterday measurement the feed
        # never gave (06-01 is inside the gap).
        system = self._system()
        for phrase in ("Do not comment on the record, the "
                       "pages, or the entries themselves",
                       "Do not compare today's stocks to "
                       "yesterday's unless the feed lists "
                       "yesterday's numbers",
                       "asserts a yesterday measurement the feed "
                       "never gave"):
            self.assertIn(phrase, system)

    def test_since_before_today_is_not_new(self):
        # Re-check 3: Rakust's wound predates the record, so
        # the feed lists it "(since before today)". The prompt
        # must stop the model reading that as a wound taken
        # today — five taken today and one already there is
        # five, not all.
        system = self._system()
        for phrase in ("A wound the feed lists as \"(since before "
                       "today)\" was already there when the "
                       "record began",
                       "Five wounds taken today and one already "
                       "there is five, not all"):
            self.assertIn(phrase, system)


def _user(feed):
    msgs = diary.diary_prompt(feed)
    return [m["content"] for m in msgs if m["role"] == "user"][0]


class TestFeedStaleness(unittest.TestCase):
    """Audit R1: the live paths get the same staleness handling
    the rebuild had. The 04-05 entry copied 04-01's numbers
    because the live feed returned the last full sample however
    old, with no flag of any kind."""

    def test_0405_class_day_uses_dated_lite_record(self):
        # Full samples only on 04-01; the feed for 04-05 must
        # date its per-dwarf record and name the unknown days,
        # never present 04-01's dwarves as 04-05's.
        feed = diary.build_diary_feed(
            _seven(100800), FakeJournal(), 105600,
            "Erushtathtat", 125)
        self.assertFalse(feed["feed_fresh"])
        self.assertEqual(feed["lite_dwarf_record_date"], "125-04-01")
        self.assertEqual(feed["record_age_days"], 4)
        self.assertEqual(feed["unknown_dates"],
                         ["125-04-02", "125-04-03", "125-04-04",
                          "125-04-05"])
        self.assertEqual(len(feed["dwarves"]), 7)
        user = _user(feed)
        self.assertIn("The per-dwarf record below is from 125-04-01",
                      user)
        self.assertIn("The per-dwarf record is 4 days old.", user)
        self.assertIn(
            "No record exists for 125-04-02, 125-04-03, 125-04-04 "
            "or 125-04-05; say nothing about them", user)

    def test_no_samples_at_all_means_no_record(self):
        feed = diary.build_diary_feed(
            FakeStore(), FakeJournal(), 100800,
            "Erushtathtat", 125)
        self.assertFalse(feed["feed_fresh"])
        self.assertTrue(feed["no_per_dwarf_samples"])
        self.assertEqual(feed["dwarves"], [])
        self.assertEqual(feed["group_counts"], [])
        self.assertIn("No per-dwarf record exists for this day",
                      _user(feed))

    def test_0602_class_partial_poll_named(self):
        # 06-02: two citizens sampled today (one wounded), the
        # other eight last seen on 04-01. No single date owns the
        # record, so no count is attributable — the feed clears
        # the dwarves and names the partial poll instead.
        store = FakeStore()
        for i in range(8):
            store.add_unit(100 + i, 100800,
                           name=f"Dwarf {100 + i}",
                           profession="Miner", mood=-1,
                           mood_name="none", stress_level=40000,
                           stress_category=3, needs=[], wounds=[],
                           job="", relations=[])
        store.add_unit(200, 169200, job="",
                       wounds=[{"id": 3}], thirst=100)
        store.add_unit(201, 169800, job="", wounds=[], thirst=100)
        feed = diary.build_diary_feed(
            store, FakeJournal(), 169200, "Erushtathtat", 125,
            population=10)
        self.assertFalse(feed["feed_fresh"])
        self.assertEqual(feed["partial_dwarf_record"],
                         {"sampled": 2, "wounded": 1})
        self.assertEqual(feed["dwarves"], [])
        self.assertEqual(feed["group_counts"], [])
        self.assertIn(
            "Only 2 of the 10 citizens were recorded today "
            "(1 wounded, 1 unmarked)", _user(feed))

    def test_fresh_day_has_no_staleness_flags(self):
        feed = diary.build_diary_feed(
            _seven(), FakeJournal(), 100800, "Erushtathtat", 125)
        self.assertTrue(feed["feed_fresh"])
        for key in ("lite_dwarf_record_date", "unknown_dates",
                    "no_per_dwarf_samples", "partial_dwarf_record"):
            self.assertNotIn(key, feed)
        self.assertNotIn("days old", _user(feed))


class TestFeedWritable(unittest.TestCase):
    """Audit R2: skip-never-stale. A feed with no fresh anchor
    is refused before any model call; the retry route's old
    guard refused only an EMPTY feed, so the stale 04-05 feed
    passed it and the model wrote from 04-01's numbers."""

    def test_empty_feed_not_writable(self):
        feed = diary.build_diary_feed(
            FakeStore(), FakeJournal(), 100800,
            "Erushtathtat", 125)
        ok, why = diary.feed_is_writable(feed)
        self.assertFalse(ok)
        self.assertTrue(why.startswith("feed too thin"))

    def test_fresh_feed_writable(self):
        feed = diary.build_diary_feed(
            _seven(), FakeJournal(), 100800, "Erushtathtat", 125)
        self.assertEqual(diary.feed_is_writable(feed), (True, ""))

    def test_dated_lite_record_with_decision_writable(self):
        journal = FakeJournal()
        journal.add_decision(106000, "queue make_bed x1 at #7",
                             "Two dwarves are very tired.",
                             action="queue_job")
        feed = diary.build_diary_feed(
            _seven(100800), journal, 105600, "Erushtathtat", 125)
        self.assertEqual(diary.feed_is_writable(feed), (True, ""))

    def test_stale_live_0405_feed_is_refused(self):
        # The exact feed the live path built for 04-05: dated
        # lite record, no decisions, trend stocks only. The old
        # guard let it through; the new one refuses it.
        feed = diary.build_diary_feed(
            _seven(100800), FakeJournal(), 105600,
            "Erushtathtat", 125)
        ok, why = diary.feed_is_writable(feed)
        self.assertFalse(ok)
        self.assertTrue(why.startswith("feed too thin"))

    def test_no_record_with_snapshot_counts_and_run_stocks_writable(
            self):
        # The rebuild's case: no per-dwarf record, but the run
        # snapshots supply counts and the run supplies stocks.
        feed = diary.build_diary_feed(
            FakeStore(), FakeJournal(), 100800,
            "Erushtathtat", 125)
        changed = diary.apply_snapshot_counts(
            feed, {"wounded": 2, "idle": 5, "population": 7})
        self.assertTrue(changed)
        feed["summary"]["stocks_source"] = "run"
        self.assertEqual(diary.feed_is_writable(feed), (True, ""))


class TestPromptUnknownWindow(unittest.TestCase):
    """Audit R3: the age in days and the unknown window are
    stated in the prompt — the model must never subtract dates
    (06-20: the record was 06-13 and the model wrote "six days
    old" for seven) or assert anything about days with no
    record (07-07: "Nobody has moved since")."""

    def test_0620_class_prompt_states_seven_days(self):
        store = FakeStore()
        store.add_unit(101, 182982, name="Olon Medtobalod",
                       profession="Brewer", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[], wounds=[],
                       job="Brewer", relations=[])
        feed = diary.build_diary_feed(
            store, FakeJournal(), 190800, "Erushtathtat", 125)
        self.assertEqual(feed["lite_dwarf_record_date"], "125-06-13")
        self.assertEqual(feed["record_age_days"], 7)
        self.assertEqual(len(feed["unknown_dates"]), 7)
        user = _user(feed)
        self.assertIn("The per-dwarf record is 7 days old.", user)
        self.assertIn(
            "No record exists for the days from 125-06-14 to "
            "125-06-20 (7 days); say nothing about them", user)


class TestDistressAttached(unittest.TestCase):
    """Audit R4: distress is attached to the dwarf's record and
    survives as a thread. Olon's 06-28 distress row was in the
    rebuild feed as a buried one-liner and the model dropped it;
    the rebuild also cleared threads entirely, which dropped the
    thread the first review had flagged as dangling."""

    def _distress_journal(self):
        journal = FakeJournal()
        journal.add_decision(
            101500, "a dwarf is in distress",
            "1 citizen(s) past a distress line: Olon Medtobalod "
            "(thirsty) — check drink/food stocks first (the usual "
            "cause); no hospital zone exists yet",
            action="log")
        return journal

    def test_distress_attaches_to_the_dwarf_line(self):
        feed = diary.build_diary_feed(
            _olons(), self._distress_journal(), 100800,
            "Erushtathtat", 125)
        rec = feed["dwarves"][0]
        self.assertEqual(rec["distress"], "thirsty")
        user = _user(feed)
        self.assertIn("in distress, thirsty", user)
        self.assertIn(
            "Noted: Olon Medtobalod was in distress, thirsty.",
            user)

    def test_distress_thread_survives(self):
        feed = diary.build_diary_feed(
            _olons(), self._distress_journal(), 100800,
            "Erushtathtat", 125)
        self.assertTrue(any(
            t["kind"] == "distress"
            and t["subject"] == "Olon Medtobalod"
            for t in feed["threads"]))

    def test_threads_come_from_the_day_not_the_latest_sample(self):
        # Olon wounded on 04-01, healed by 04-05; Zulban wounded
        # only in July. A rebuild of April must not list July's
        # threads, and a July day must not list April's healed
        # wound — the old code read the store's latest sample
        # whatever the day.
        store = FakeStore()
        fields = dict(name="Olon Medtobalod", profession="Brewer",
                      mood=-1, mood_name="none", stress_level=40000,
                      stress_category=3, needs=[], job="Brewer",
                      relations=[])
        store.add_unit(101, 100800, wounds=[], **fields)
        store.add_unit(101, 101999, wounds=[{"id": 1}], **fields)
        store.add_unit(101, 105000, wounds=[], **fields)
        store.add_unit(102, 200000, name="Zulban Rithgemesh",
                       profession="Miner", mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[{"id": 2}], job="Miner",
                       relations=[])
        april = diary.open_threads(store, 100800, 125)
        self.assertTrue(any(
            t["kind"] == "wounded"
            and t["subject"] == "Olon Medtobalod" for t in april))
        self.assertEqual(
            [t for t in april
             if t["kind"] == "wounded"
             and t["subject"] == "Olon Medtobalod"][0]["since"],
            "125-04-01")
        self.assertFalse(any(
            t["subject"] == "Zulban Rithgemesh" for t in april))
        may = diary.open_threads(store, 105600, 125)
        self.assertFalse(any(
            t["kind"] == "wounded"
            and t["subject"] == "Olon Medtobalod" for t in may))
        july = diary.open_threads(store, 200400, 125)
        self.assertTrue(any(
            t["kind"] == "wounded"
            and t["subject"] == "Zulban Rithgemesh" for t in july))
        self.assertFalse(any(
            t["subject"] == "Olon Medtobalod" for t in july))


class TestPlainWordsJobs(unittest.TestCase):
    """Audit R5: the job in plain words, never the raw token.
    "Working as Fish" became "Ral cleans fish" in three entries;
    "Drink2" and "CustomReaction" are the same class of error."""

    def test_fish_and_drink_render_in_plain_words(self):
        user = _user(diary.build_diary_feed(
            _seven(), FakeJournal(), 100800, "Erushtathtat", 125))
        self.assertIn("fishing", user)
        self.assertNotIn("working as Fish", user)
        self.assertIn("drinking", user)
        self.assertNotIn("Drink2", user)

    def test_custom_reaction_renders_plain(self):
        store = FakeStore()
        store.add_unit(101, 100800, name="Olon Medtobalod",
                       profession="Brewer", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[], wounds=[],
                       job="CustomReaction", relations=[])
        store.add_unit(101, 101999, name="Olon Medtobalod",
                       profession="Brewer", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[], wounds=[],
                       job="CustomReaction", relations=[])
        user = _user(diary.build_diary_feed(
            store, FakeJournal(), 100800, "Erushtathtat", 125))
        self.assertIn("working a reaction", user)
        self.assertNotIn("CustomReaction", user)

    def test_job_words_table(self):
        # Malformed-input table: job_words never raises and never
        # returns the raw token.
        from dfagent_harness.dwarves import job_words
        cases = [(None, ""), (123, ""), ("", ""),
                 ("Fish", "fishing"), ("Drink2", "drinking"),
                 ("CustomReaction", "working a reaction"),
                 ("SomeNewJob", "some new job"),
                 ("Eat", "eating"), ("Sleep", "sleeping"),
                 ("ConstructBuilding", "constructing a building")]
        for token, expected in cases:
            with self.subTest(token=token):
                self.assertEqual(job_words(token), expected)


class TestNeedsDedup(unittest.TestCase):
    """Audit R6: needs listed once each, strongest first, with
    the focus carried. 04-01 carried ~11 need fragments per
    dwarf (up to 3 "going without" + ~8 "went without" change
    lines) and the model summarized them vaguely."""

    def test_need_listed_once_not_twice(self):
        # Olon gains a Drink need today: the "went without
        # drink" change duplicates the current "going without
        # drink" and must be skipped, not listed alongside it.
        user = _user(diary.build_diary_feed(
            _olons(), FakeJournal(), 100800, "Erushtathtat", 125))
        self.assertIn("going without drink", user)
        self.assertNotIn("went without drink", user)

    def test_strongest_need_marked_badly(self):
        store = FakeStore()
        store.add_unit(101, 100800, name="Olon Medtobalod",
                       profession="Brewer", mood=-1,
                       mood_name="none", stress_level=40000,
                       stress_category=3, needs=[], wounds=[],
                       job="Brewer", relations=[])
        store.add_unit(101, 101999, name="Olon Medtobalod",
                       profession="Brewer", mood=-1,
                       mood_name="none", stress_level=85000,
                       stress_category=1,
                       needs=[{"need": "Drink", "focus": -6000,
                               "level": 25}],
                       wounds=[], job="Brewer", relations=[])
        user = _user(diary.build_diary_feed(
            store, FakeJournal(), 100800, "Erushtathtat", 125))
        self.assertIn("going without drink badly", user)


class TestLivePathsCarryThreadsAndEntries(unittest.TestCase):
    """Audit R7 (feed half): the feed carries both the recent
    entries and the day's threads in one build — the route-level
    half (the retry route's feed reaching the model) is locked
    in tests/test_server.py."""

    def test_feed_carries_both(self):
        # The feed day is 04-02, so the 04-01 entry counts as a
        # recent entry (only dates strictly before today do).
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            (state / "diary.md").write_text(
                "## 125-04-01 — First day\n\nOlon was thirsty all "
                "day, and the still was silent.\n")
            feed = diary.build_diary_feed(
                _olons(), FakeJournal(), 102000, "Erushtathtat",
                125, state_dir=state)
            self.assertTrue(any(
                e["date"] == "125-04-01" for e in feed["recent_entries"]))
            # Olon is stressed in the day's samples: the thread
            # is there alongside the entries, not instead of them.
            self.assertTrue(any(
                t["kind"] == "stressed"
                and t["subject"] == "Olon Medtobalod"
                for t in feed["threads"]))


class TestOpenThreadsFirstSighting(unittest.TestCase):
    """Re-check 4 fix D: a condition's first sighting is not its
    start. A migrant's wound first appears at tick 182982 (the
    06-13 sample itself — the dwarf's record starts there, not the
    store's) so it renders "(first recorded 125-06-13)", never
    "(since 125-06-13)" and never "(since before today)". A wound
    already true at the store's first tick earns no date at all."""

    def _migrant(self):
        store = FakeStore()
        store.add_unit(101, 100800, name="Olon Medtobalod",
                       profession="Brewer", mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[], job="", relations=[])
        # The migrant's whole record: lite samples, wound present
        # from the first sighting (06-13).
        store.add_unit(1700, 182982, name="", profession="",
                       mood=-1, mood_name="none",
                       stress_level=40000, stress_category=-1,
                       needs=[], wounds=[{"id": 2, "parts": 2}],
                       job="", relations=[])
        store.add_unit(1700, 183500, name="", profession="",
                       mood=-1, mood_name="none",
                       stress_level=40000, stress_category=-1,
                       needs=[], wounds=[{"id": 2, "parts": 2}],
                       job="", relations=[])
        return store

    def test_migrant_wound_is_first_recorded_not_since(self):
        threads = diary.open_threads(self._migrant(), 182982, 125)
        wounded = [t for t in threads if t["kind"] == "wounded"]
        self.assertEqual(len(wounded), 1)
        self.assertEqual(wounded[0]["since"], "125-06-13")
        self.assertTrue(wounded[0]["first_sighting"])

    def test_pre_record_wound_still_has_no_since(self):
        store = FakeStore()
        store.add_unit(101, 100800, name="", profession="",
                       mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[{"id": 4, "parts": 2}],
                       job="", relations=[])
        store.add_unit(101, 101999, name="Rakust Cattenaval",
                       profession="Miner", mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[{"id": 4, "parts": 2}],
                       job="", relations=[])
        threads = diary.open_threads(store, 100800, 125)
        wounded = [t for t in threads if t["kind"] == "wounded"]
        self.assertEqual(len(wounded), 1)
        self.assertIsNone(wounded[0]["since"])
        self.assertFalse(wounded[0]["first_sighting"])

    def test_wound_id_change_dates_the_current_wound(self):
        # Re-check 5, 06-22: äs/Lòr/Zulban carry wound id 4 on
        # 04-01, [] on 04-12 (full sample — the April wounds
        # HEALED), id 7 on 06-02/06-03, [] on 06-13, id 8 on
        # 06-21. Tracking wound *presence* dated the id-8 wound
        # to the id-7 run's start (06-02), and the model then
        # invented 04-01 for it. The thread must date the wound
        # the dwarf carries NOW (id 8, first recorded 06-21),
        # never an earlier healed wound's run.
        store = FakeStore()
        for tick, wounds, name in (
                (101323, [{"id": 4, "parts": 2}],
                 "äs Oslanlumash"),
                (115166, [], "äs Oslanlumash"),
                (169650, [{"id": 7, "parts": 2}], ""),
                (192076, [{"id": 8, "parts": 2}], "")):
            store.add_unit(5407, tick, name=name, profession="",
                           mood=-1, mood_name="none",
                           stress_level=40000, stress_category=3,
                           needs=[], wounds=wounds, job="",
                           relations=[])
        threads = diary.open_threads(store, 193200, 125)
        wounded = [t for t in threads if t["kind"] == "wounded"]
        self.assertEqual(len(wounded), 1)
        self.assertEqual(wounded[0]["since"], "125-06-21")
        self.assertTrue(wounded[0]["first_sighting"])

    def test_broken_run_is_still_a_first_sighting(self):
        # Re-check 5 (2026-11-27) supersedes the re-check 4 fix D
        # distinction: a wound's since-date is ALWAYS a first
        # sighting, even when the walk breaks on a full clear
        # sample. A break only says the wound was absent at the
        # clear sample and present at the sighting — it does not
        # pin the taking date (the wound could have been taken
        # any day between them), and the model repeatedly wrote
        # "taken" claims from "(since DATE)" renderings. The
        # honest rendering is "(first recorded DATE)" in every
        # case; only a wound already true at the store's first
        # sample earns no date at all.
        store = FakeStore()
        store.add_unit(101, 100800, name="Olon Medtobalod",
                       profession="Brewer", mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[], job="", relations=[])
        store.add_unit(101, 101999, name="Olon Medtobalod",
                       profession="Brewer", mood=-1, mood_name="none",
                       stress_level=40000, stress_category=3,
                       needs=[], wounds=[{"id": 4, "parts": 2}],
                       job="", relations=[])
        threads = diary.open_threads(store, 100800, 125)
        wounded = [t for t in threads if t["kind"] == "wounded"]
        self.assertEqual(wounded[0]["since"], "125-04-01")
        self.assertTrue(wounded[0]["first_sighting"])


class TestDwarfRecordSocial(unittest.TestCase):
    """The 17:19 PT audit: the harness was blind to friendships,
    grudges, and meet counts (hf_visual). dwarf_record now carries
    social ties with wiki labels, salient traits, and recent
    emotions — and outside ties as a count only, so the feed can
    say a dwarf has people elsewhere without inventing who."""

    def _sample(self, **over):
        s = {"unit_id": 5407, "name": "äs Oslanlumash",
             "profession": "Miner", "mood_name": "none",
             "stress": 100, "stress_category": 3, "job": "",
             "needs": [], "relations": [],
             "social": [
                 {"histfig_id": 11, "unit_id": 5408,
                  "name": "Rakust Cattenaval", "in_fort": True,
                  "love": 80, "meet_count": 45},
                 {"histfig_id": 12, "unit_id": 5412,
                  "name": "Mestthos Zassezuk", "in_fort": True,
                  "love": -60, "meet_count": 12},
                 {"histfig_id": 99, "unit_id": None,
                  "name": "Someone Far Away", "in_fort": False,
                  "love": 55, "meet_count": 3},
             ],
             "traits": [
                 {"facet": "GREGARIOUSNESS", "value": 95},
                 {"facet": "LOVE_PROPENSITY", "value": 90},
                 {"facet": "STRAIGHTFORWARDNESS", "value": 51},
                 {"facet": "AMBITION", "value": 10},
             ],
             "emotions": [
                 {"type": "GRIEF", "strength": 60,
                  "thought": "SAW_DEAD_BODY", "severity": 2,
                  "year": 125, "year_tick": 101000},
                 {"type": "CONTENTMENT", "strength": 20,
                  "thought": "ATE_GOOD_MEAL", "severity": 0,
                  "year": 125, "year_tick": 100900},
             ]}
        s.update(over)
        return s

    def test_social_labels_from_love_and_meetings(self):
        from dfagent_harness.dwarves import social_ties
        ties, outside = social_ties(self._sample())
        self.assertEqual(
            [(t["name"], t["label"]) for t in ties],
            [("Rakust Cattenaval", "close friend"),
             ("Mestthos Zassezuk", "disliked")])
        self.assertEqual(outside, 1)

    def test_social_new_today_only_against_previous(self):
        from dfagent_harness.dwarves import dwarf_record
        prev = [{"histfig_id": 11}]
        rec = dwarf_record(self._sample(), prev_social=prev)
        by_name = {t["name"]: t for t in rec["social"]}
        self.assertFalse(by_name["Rakust Cattenaval"]["new_today"])
        self.assertTrue(by_name["Mestthos Zassezuk"]["new_today"])
        # First sighting: nothing is new today.
        rec2 = dwarf_record(self._sample(), prev_social=None)
        self.assertFalse(any(t["new_today"]
                             for t in rec2["social"]))

    def test_salient_traits_only_far_from_neutral(self):
        rec = dwarf_record(self._sample())
        self.assertEqual(
            [(t["facet"], t["words"]) for t in rec["traits"]],
            [("gregariousness", "very high"),
             ("love propensity", "very high"),
             ("ambition", "very low")])

    def test_recent_emotions_most_recent_first(self):
        rec = dwarf_record(self._sample())
        self.assertEqual(
            [(e["type"], e["thought"]) for e in rec["emotions"]],
            [("grief", "saw dead body"),
             ("contentment", "ate good meal")])

    def test_missing_social_fields_yield_empty(self):
        rec = dwarf_record({"unit_id": 1, "name": "X"})
        self.assertEqual(rec["social"], [])
        self.assertEqual(rec["social_outside"], 0)
        self.assertEqual(rec["traits"], [])
        self.assertEqual(rec["emotions"], [])


class TestDiaryPromptPass4(unittest.TestCase):
    """Prompt pass 4 (2026-11-27): dwarf-focus (17:19 PT) +
    event-not-stats (17:25 PT) + re-check 4 fixes 1-8."""

    def _system(self):
        feed = diary.build_diary_feed(
            _olons(), FakeJournal(), 100800, "Erushtathtat", 125)
        msgs = diary.diary_prompt(feed)
        return msgs[0]["content"]

    def test_recheck5_share_and_first_sighting_rules(self):
        system = self._system()
        for phrase in (
                "Never use a share word",
                "three of the six gatherings",
                "The date rides in EVERY sentence",
                "Write \"first recorded\", never \"taken\" or \"from "
                "before\"",
                "\"Taken today\" for a wound first seen today is "
                "wrong"):
            self.assertIn(phrase, system)

    def test_event_first_and_dwarf_focus_rules(self):
        system = self._system()
        for phrase in (
                "Write from WHAT HAPPENED TODAY, not from the "
                "ledger",
                "Lead with a dwarf doing something, or something "
                "happening to a dwarf",
                "The entry is ABOUT THE DWARVES",
                "A dwarf's friend in a bad mood matters more than "
                "the food count"):
            self.assertIn(phrase, system)

    def test_recheck4_causation_drink_materials_rules(self):
        system = self._system()
        for phrase in (
                "Never tie two same-day facts into one causal "
                "sentence unless the feed ties them",
                "Count drinkers from the completions, never from "
                "the needs",
                "Never state what a job or a building is made of "
                "unless the feed states it",
                "At most two dwarves' needs per entry",
                "Say each fact once",
                "Never close with a summary of the day",
                "A fact from a dated record carries its date in "
                "the same sentence"):
            self.assertIn(phrase, system)


class TestFeedEventsRendering(unittest.TestCase):
    """The event-first feed in the prompt: events lead, the ledger
    is background; thin days say so and stop; feed fixes D/E/F."""

    def _events_file(self, state, events):
        import json as _json
        (state / "events.jsonl").write_text(
            "".join(_json.dumps(e) + "\n" for e in events))

    def _user(self, feed):
        msgs = diary.diary_prompt(feed)
        return msgs[1]["content"]

    def test_events_lead_and_ledger_follows(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            self._events_file(state, [
                {"type": "report", "tick": 100900, "year": 125,
                 "at": 1795700000, "source": "poll",
                 "data": {"text": "A caravan from Umshadònul has"
                                   " arrived."}},
                {"type": "job_completed", "tick": 100901,
                 "year": 125, "at": 1795700000, "source": "eventful",
                 "data": {"job_type": "ConstructBuilding",
                          "worker_id": 5410, "pos": [92, 79, 42]}},
            ])
            feed = diary.build_diary_feed(
                _olons(), FakeJournal(), 100800, "Erushtathtat",
                125, state_dir=state)
            user = self._user(feed)
            self.assertIn("What happened today:", user)
            self.assertIn("A caravan from Umshadònul has arrived.",
                          user)
            self.assertLess(user.index("What happened today:"),
                            user.index("Ledger:"))

    def test_no_event_record_says_so_and_stops(self):
        # P0-2: the feed now carries source coverage, so the prompt
        # states which sources were live (here: none — the bus and
        # watch files are missing) and tells the writer to write
        # two or three lines and stop, instead of the old branch
        # that conflated dead sources with a quiet day.
        feed = diary.build_diary_feed(
            _olons(), FakeJournal(), 100800, "Erushtathtat", 125)
        user = self._user(feed)
        self.assertIn("Record for this day:", user)
        self.assertIn("The bus event log is missing", user)
        self.assertIn("Write two or three lines from the decisions "
                      "and the last dated record, and stop.", user)
        self.assertIn("Do not fill the entry with the ledger", user)
        self.assertNotIn("No event record exists for this day", user)

    def test_partial_poll_names_the_remainder(self):
        # Re-check 4 fix E: "the rest have no record" becomes a
        # number ("the other 8 have no record for today").
        feed = diary.build_diary_feed(
            _olons(), FakeJournal(), 100800, "Erushtathtat", 125)
        feed["partial_dwarf_record"] = {"sampled": 2, "wounded": 0}
        feed["population"] = 10
        user = self._user(feed)
        self.assertIn("the other 8 have no record for today", user)

    def test_unmet_need_threads_stay_out_of_the_prompt(self):
        # Re-check 4 fix F: unmet_need threads duplicate the dwarf
        # lines without focus values. Kept in the feed, never
        # rendered as a thread. (The phrase still appears in the
        # dwarf's own line — that is the feed's needs rendering,
        # not the thread.)
        feed = diary.build_diary_feed(
            _olons(), FakeJournal(), 100800, "Erushtathtat", 125)
        feed["threads"] = [{
            "kind": "unmet_need", "subject": "Olon Medtobalod",
            "detail": "going without drink", "since": None}]
        user = self._user(feed)
        threads_section = user[user.index("Open threads:"):]
        self.assertNotIn("going without drink", threads_section)
        self.assertNotIn("unmet_need", threads_section)
        self.assertEqual(
            [t for t in feed["threads"]
             if t["kind"] == "unmet_need"][0]["detail"],
            "going without drink")

    def test_first_sighting_renders_in_dwarf_line(self):
        # Re-check 4 fix D: a first sighting renders "(first
        # recorded DATE)", never "(since DATE)".
        feed = diary.build_diary_feed(
            _olons(), FakeJournal(), 100800, "Erushtathtat", 125)
        feed["threads"] = [{
            "kind": "wounded", "subject": "Olon Medtobalod",
            "detail": "1 wound", "since": "125-06-13",
            "first_sighting": True}]
        feed["dwarves"][0]["wounds"] = 1
        feed["dwarves"][0]["changes"] = []
        user = self._user(feed)
        self.assertIn("(first recorded 125-06-13)", user)
        self.assertNotIn("(since 125-06-13)", user)

    def test_unnamed_migrant_wound_resolves_by_unit_id(self):
        # Re-check 5, 06-20: three unnamed migrants share the
        # display name "an unnamed migrant" while their threads
        # name them "dwarf {uid}". Keying the wound since-date
        # lookup by name lost their dates and the line fell back
        # to "(since before today)" — the 06-20 root cause. The
        # lookup keys by unit_id, so the migrant's line carries
        # "(first recorded 125-06-13)".
        feed = diary.build_diary_feed(
            _olons(), FakeJournal(), 100800, "Erushtathtat", 125)
        feed["threads"] = [{
            "kind": "wounded", "subject": "dwarf 1700",
            "unit_id": 1700, "detail": "1 wound",
            "since": "125-06-13", "first_sighting": True}]
        feed["dwarves"][0]["name"] = "an unnamed migrant"
        feed["dwarves"][0]["unit_id"] = 1700
        feed["dwarves"][0]["wounds"] = 1
        feed["dwarves"][0]["changes"] = []
        user = self._user(feed)
        self.assertIn("(first recorded 125-06-13)", user)
        self.assertNotIn("(since before today)", user)

    def test_emotion_carries_its_own_date(self):
        # Re-check 5, 06-27: Zulban's uneasiness was felt on the
        # 8th of Hematite (year_tick 109200) and carried forward
        # undated into June, where the model reported it as the
        # 26th's. A feeling is a dated event, not a current
        # state: the date rides with the feeling, from its own
        # year_tick. An emotion with no recorded tick keeps no
        # date — undated is honest, a guessed date is not.
        feed = diary.build_diary_feed(
            _olons(), FakeJournal(), 100800, "Erushtathtat", 125)
        feed["dwarves"][0]["emotions"] = [{
            "type": "uneasiness", "thought": "Needs Unfulfilled",
            "year": 125, "year_tick": 109200}]
        user = self._user(feed)
        self.assertIn(
            "felt uneasiness — Needs Unfulfilled "
            "(8th of Hematite, 125)", user)

    def test_emotion_without_tick_has_no_date(self):
        feed = diary.build_diary_feed(
            _olons(), FakeJournal(), 100800, "Erushtathtat", 125)
        feed["dwarves"][0]["emotions"] = [{
            "type": "uneasiness", "thought": "Needs Unfulfilled",
            "year": 125, "year_tick": None}]
        user = self._user(feed)
        self.assertIn("felt uneasiness — Needs Unfulfilled.", user)
        self.assertNotIn("8th of Hematite", user)

    def test_no_record_note_names_event_workers(self):
        # Re-check 5, 04-02/04-05: the old note said "do not name
        # any dwarf" while the events section named the dwarves
        # who did the work — 04-02 obeyed the ban and hid its
        # gatherers and drinkers behind "one pair of hands"
        # while 04-05 named them correctly. The ban scopes to a
        # dwarf's individual state (wounds, needs, stress, mood);
        # the events' workers are named for what they did.
        feed = diary.build_diary_feed(
            _olons(), FakeJournal(), 100800, "Erushtathtat", 125)
        feed["no_per_dwarf_samples"] = True
        user = self._user(feed)
        self.assertNotIn("do not name any dwarf", user)
        self.assertIn(
            "do not describe any dwarf's individual state", user)
        self.assertIn(
            "The events section above names the dwarves who did "
            "things today, and you may name them for what they "
            "did", user)

    def test_migrant_names_resolve_from_the_event_log(self):
        # The migrants' names live in citizen_new events, not in
        # the Store's lite samples. The feed names them and stops
        # counting them unnamed — but only from the day the name
        # was first recorded: a name is a detection, not an
        # arrival. The citizen_new here is 07-01 (tick 201600),
        # so the 06-12 feed (day_start 181200) keeps the migrant
        # unnamed, and the 07-01 feed names them.
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            self._events_file(state, [
                {"type": "citizen_new", "tick": 201600,
                 "year": 125, "at": 1795730639, "source": "poll",
                 "data": {"unit_id": 1700, "name": "Litast Aknònul",
                          "profession": "Bowyer",
                          "pos": [20, 1, 181]}},
            ])
            store = FakeStore()
            store.add_unit(101, 100800, name="Olon Medtobalod",
                           profession="Brewer", mood=-1,
                           mood_name="none", stress_level=40000,
                           stress_category=3, needs=[], wounds=[],
                           job="", relations=[])
            store.add_unit(1700, 181500, name="", profession="",
                           mood=-1, mood_name="none",
                           stress_level=40000, stress_category=-1,
                           needs=[], wounds=[{"id": 2, "parts": 2}],
                           job="", relations=[])
            feed = diary.build_diary_feed(
                store, FakeJournal(), 181200, "Erushtathtat", 125,
                state_dir=state)
            self.assertEqual(feed.get("migrants_named") or [], [])
            self.assertEqual(feed.get("unnamed_citizens"), 1)
            feed = diary.build_diary_feed(
                store, FakeJournal(), 201600, "Erushtathtat", 125,
                state_dir=state)
            named = feed.get("migrants_named") or []
            self.assertEqual(
                [(m["name"], m["profession"],
                  m["first_recorded"]) for m in named],
                [("Litast Aknònul", "Bowyer", "125-06-12")])
            self.assertNotIn("unnamed_citizens", feed)


class TestCompletionPhrases(unittest.TestCase):
    def test_queue_job_phrase(self):
        self.assertEqual(diary._queue_job_phrase("brew"), "brewing")
        self.assertEqual(diary._queue_job_phrase("cook"), "cooking")
        self.assertEqual(
            diary._queue_job_phrase("make_bed"), "making a bed")
        self.assertEqual(
            diary._queue_job_phrase("make_barrel"),
            "making a barrel")

    def test_custom_reaction_at_still_one_kind_is_brewing(self):
        # The 04-01/04-05 still queue is brew only, so a
        # CustomReaction there is brewing — not "working a
        # reaction", and not a guess at beds vs barrels.
        ws = {(95, 108, 175): {"id": 8, "kind": "still"}}
        self.assertEqual(
            diary._completion_phrase(
                "CustomReaction", [95, 108, 175], ws, {8: {"brew"}}),
            "brewing")

    def test_custom_reaction_at_still_several_kinds_is_work(self):
        # The Carpenters queue is make_bed AND make_barrel, so a
        # CustomReaction there cannot name the kind — "work at
        # the still" is honest, a guessed kind is not.
        ws = {(95, 108, 175): {"id": 8, "kind": "still"}}
        self.assertEqual(
            diary._completion_phrase(
                "CustomReaction", [95, 108, 175], ws,
                {8: {"make_bed", "make_barrel"}}),
            "work at the still")

    def test_custom_reaction_unmapped_is_a_workshop_job(self):
        # The Carpenters is not in the run-log map (it was in the
        # clean base), so a CustomReaction there is vague but
        # true — never a guessed product.
        self.assertEqual(
            diary._completion_phrase(
                "CustomReaction", [93, 105, 175], {}, {}),
            "a workshop job")

    def test_construct_building_at_still_is_the_still(self):
        ws = {(95, 108, 175): {"id": 8, "kind": "still"}}
        self.assertEqual(
            diary._completion_phrase(
                "ConstructBuilding", [95, 108, 175], ws, {}),
            "the still")

    def test_construct_building_unmapped_stays_vague(self):
        self.assertEqual(
            diary._completion_phrase(
                "ConstructBuilding", [93, 105, 175], {}, {}),
            "constructing a building")

    def test_routine_jobs_unchanged(self):
        self.assertEqual(
            diary._completion_phrase(
                "Drink2", [97, 95, 175], {}, {}), "drinking")
        self.assertEqual(
            diary._completion_phrase(
                "GatherPlants", [107, 103, 175], {}, {}),
            "gathering plants")


class TestQueueMaterials(unittest.TestCase):
    def test_wood_jobs_aggregate_with_have(self):
        # 5 beds + 2 barrels = 7 wood; the have is the day-start
        # stock. This is the feed-side fix for the 04-02 "the
        # beds want stone" invention: a bed takes wood, and the
        # feed says so with the number.
        jobs = [("make_bed", 5, "worked"),
                ("make_barrel", 2, "worked")]
        self.assertEqual(
            diary._queue_materials_bit(jobs, {"wood": 117}),
            "; needs 7 wood (have 117)")

    def test_brew_needs_render_without_have(self):
        # Brewable plants and empty barrels have no summary stock
        # key, so the need renders with no have — never a guessed
        # count.
        jobs = [("brew", 2, "worked")]
        self.assertEqual(
            diary._queue_materials_bit(jobs, {"wood": 117}),
            "; needs 2 brewable plants + 2 empty barrels")

    def test_unknown_job_has_no_materials(self):
        self.assertEqual(
            diary._queue_materials_bit(
                [("unknown_job", 1, "worked")], {"wood": 117}), "")
        self.assertEqual(
            diary._queue_materials_bit([], {"wood": 117}), "")

    def test_prompt_carries_materials(self):
        journal = FakeJournal()
        journal.add_decision(
            100900, "queue make_bed x1 at the Carpenters workshop #7",
            action="queue_job", ok=True)
        journal.add_decision(
            100950,
            "queue make_barrel x2 at the Carpenters workshop #7",
            action="queue_job", ok=True)
        feed = diary.build_diary_feed(_seven(), journal,
                                      100800, "Erushtathtat", 125)
        user = diary.diary_prompt(feed)[1]["content"]
        # No wood stock in this fixture's summary, so the need
        # renders with no have — the point is the need is there
        # and it is wood, not stone.
        self.assertIn("needs 3 wood", user)


class TestLiteStressDelta(unittest.TestCase):
    def _lite_store(self, stresses):
        store = FakeStore()
        for tick, stress in stresses:
            store.add_unit(101, tick, name="", profession="",
                           mood=-1, mood_name="none", stress=stress,
                           stress_level=stress, stress_category=-1,
                           needs=[], wounds=[], job="", relations=[])
        return store

    def test_stress_jump_is_a_change(self):
        # Olon's 07-05 jump (38 to 716 in the live store) is the
        # kind of per-dwarf change the June/July days otherwise
        # lack: the lite feed carries no needs, relations, or
        # moods, so the stress delta is the signal.
        store = self._lite_store([(181200, 38), (182000, 716)])
        feed = diary.build_diary_feed(
            store, FakeJournal(), 181200, "Erushtathtat", 125)
        rec = feed["dwarves"][0]
        self.assertIn(
            {"kind": "stress_rose", "text": "stress rose sharply"},
            rec["changes"])

    def test_small_stress_move_is_not_a_change(self):
        # The routine band is roughly ±100; a +50 move is noise,
        # not a story.
        store = self._lite_store([(181200, 100), (182000, 150)])
        feed = diary.build_diary_feed(
            store, FakeJournal(), 181200, "Erushtathtat", 125)
        rec = feed["dwarves"][0]
        self.assertEqual(rec["changes"], [])

    def test_missing_stress_is_no_signal(self):
        store = FakeStore()
        store.add_unit(101, 181200, name="", profession="",
                       mood=-1, mood_name="none", stress=None,
                       stress_level=None, stress_category=-1,
                       needs=[], wounds=[], job="", relations=[])
        store.add_unit(101, 182000, name="", profession="",
                       mood=-1, mood_name="none", stress=716,
                       stress_level=716, stress_category=-1,
                       needs=[], wounds=[], job="", relations=[])
        feed = diary.build_diary_feed(
            store, FakeJournal(), 181200, "Erushtathtat", 125)
        rec = feed["dwarves"][0]
        self.assertEqual(rec["changes"], [])


class TestGoalSkillsRendering(unittest.TestCase):
    def test_goal_and_skills_reach_the_prompt(self):
        store = _seven()
        # Give Olon a goal and a skill in both samples.
        for uid in (102,):
            for s in store._units[uid]:
                s["goal"] = {"type": 4, "name": "Create Great Artwork"}
                s["skills"] = [{"skill": "MINING", "rating": "Adequate",
                                "rating_num": 2, "experience": 0}]
        feed = diary.build_diary_feed(store, FakeJournal(),
                                      100800, "Erushtathtat", 125)
        user = diary.diary_prompt(feed)[1]["content"]
        self.assertIn("wants to create great artwork", user)
        self.assertIn("skilled at mining (adequate)", user)


class TestEnumGuards(unittest.TestCase):
    def test_unresolved_facet_is_skipped(self):
        from dfagent_harness.dwarves import salient_traits
        sample = {"traits": [
            {"facet": "facet_41", "value": 90},
            {"facet": "LOVE_PROPENSITY", "value": 90}]}
        names = [t["facet"] for t in salient_traits(sample)]
        self.assertNotIn("facet_41", names)
        # Resolved facets pass through, lowercased with spaces.
        self.assertIn("love propensity", names)

    def test_unresolved_emotion_is_skipped(self):
        from dfagent_harness.dwarves import recent_emotions
        sample = {"emotions": [
            {"type": "14", "thought": "57", "strength": 1,
             "severity": 1, "tick": 100800},
            {"type": "ANNOYANCE", "thought": "Rain", "strength": 1,
             "severity": 1, "tick": 100800}]}
        types = [e["type"] for e in recent_emotions(sample)]
        self.assertNotIn("14", types)
        # Resolved names pass through, lowercased.
        self.assertIn("annoyance", types)


if __name__ == "__main__":
    unittest.main()
