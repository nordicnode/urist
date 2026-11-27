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

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import diary  # noqa: E402


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
            "make_barrel x2 (3 jobs total)", user)

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
        # carries its since-date, not a "wounded today".
        feed = diary.build_diary_feed(_seven(), FakeJournal(),
                                      100800, "Erushtathtat", 125)
        user = diary.diary_prompt(feed)[1]["content"]
        self.assertIn("1 wound (since 125-04-01)", user)

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


if __name__ == "__main__":
    unittest.main()
