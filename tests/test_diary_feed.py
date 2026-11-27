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


if __name__ == "__main__":
    unittest.main()
