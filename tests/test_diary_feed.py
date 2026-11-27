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
