"""Offline tests for the diary (GOAL.md step 4).

The diary is the narrative rendering of the daily rolling summary:
one entry per in-game day, built ONLY from the State Store + the
planner Journal for that day's tick range, so every claim traces to
a recorded event, decision, or observation. diary.md is the source
of truth; diary.html is the generated DF-themed view.
"""

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import diary  # noqa: E402


class FakeStore:
    """Minimal Store stand-in: trend samples + deaths."""

    def __init__(self):
        self._trends = {}
        self._deaths = []

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


def _day_summary(store=None, journal=None, day_start=169200):
    """Day starting at tick 169200 (125-06-02, Galena 2)."""
    store = store or FakeStore()
    journal = journal or FakeJournal()
    return diary.build_daily_summary(store, journal, day_start,
                                     "Erushtathtat", 125)


class TestDFCalendar(unittest.TestCase):
    def test_date_of_tick(self):
        # Tick 0 is Granite 1 (the first day of the year).
        self.assertEqual(diary.date_of_tick(0, 125), (125, 1, 1))
        # 1,200 ticks = 1 day.
        self.assertEqual(diary.date_of_tick(1200, 125), (125, 1, 2))
        # 33,600 ticks = 1 month (Slate 1).
        self.assertEqual(diary.date_of_tick(33600, 125), (125, 2, 1))
        # The last day of the year: tick 403199 is Obsidian 28.
        self.assertEqual(diary.date_of_tick(403199, 125), (125, 12, 28))

    def test_date_str_and_words(self):
        # 125-06-02 is year_tick 169200 (month 6 starts at 168000).
        tick = 5 * 33600 + 1 * 1200
        self.assertEqual(diary.date_str(tick, 125), "125-06-02")
        self.assertEqual(diary.date_words(tick, 125),
                         "2nd of Galena, 125")
        self.assertEqual(diary.season_of_tick(tick), "Summer")

    def test_day_range(self):
        self.assertEqual(diary.day_range(169200),
                         (169200, 170399))


class TestBuildDailySummary(unittest.TestCase):
    def test_stocks_from_trend_samples(self):
        store = FakeStore()
        store.add_trend("drink", 169200, 9.0)
        store.add_trend("drink", 170400, 8.0)
        store.add_trend("food", 169200, 25.0)
        s = _day_summary(store=store)
        self.assertEqual(s["stocks_start"]["drink"], 9.0)
        self.assertEqual(s["stocks_end"]["drink"], 8.0)
        self.assertEqual(s["stocks_start"]["food"], 25.0)

    def test_deaths_in_range_only(self):
        store = FakeStore()
        store.add_death(169500, 42, "died of thirst")
        store.add_death(171000, 43, "died of hunger")  # next day
        s = _day_summary(store=store)
        self.assertEqual(len(s["deaths"]), 1)
        self.assertEqual(s["deaths"][0]["unit_id"], 42)
        self.assertEqual(s["deaths"][0]["cause"], "died of thirst")

    def test_decisions_and_events_in_range_only(self):
        journal = FakeJournal()
        journal.add_decision(169300, "brew drink",
                             reason="Drink is low: 9 units left",
                             action="brew", ok=True)
        journal.add_decision(171100, "brew drink")  # next day
        journal.add_event(169400, "citizen_new", "migrant arrived")
        journal.add_event(169500, "snapshot", "tick 169500")
        s = _day_summary(journal=journal)
        self.assertEqual(len(s["decisions"]), 1)
        self.assertEqual(s["decisions"][0]["decision"], "brew drink")
        self.assertTrue(s["decisions"][0]["ok"])
        self.assertEqual(s["arrivals"], 1)
        self.assertEqual(len(s["events"]), 2)

    def test_decisions_filtered_by_year(self):
        # The Journal is shared across forts: a year-306 decision
        # in the same tick range must not leak into a year-125 day.
        journal = FakeJournal()
        journal.add_decision(169300, "brew drink", ok=True)
        # FakeJournal.add_decision does not set a year; simulate a
        # year-306 row by patching it in directly.
        journal._decisions[0]["year"] = 306
        s = _day_summary(journal=journal)
        self.assertEqual(len(s["decisions"]), 0)


class TestRenderEntry(unittest.TestCase):
    def test_merge_driver_record(self):
        # The daemon's planner loop is paused during M1 runs, so the
        # run's decisions are not in the Journal and no trend samples
        # are taken for the run's day. The driver's own record (its
        # decisions + start/end stocks from its snapshots) merges
        # into the summary — without it the entry would say 'a quiet
        # day' for a day the model acted on.
        summary = _day_summary()
        diary.merge_driver_record(
            summary,
            decisions=[{
                "decision": "build a Still at (95, 108, 175)",
                "reason": "No still exists, so brewing is impossible.",
                "action": "build_workshop", "ok": True,
                "result": "still workshop #8 built"}],
            stocks_start={"drink": 39, "food": 32, "wood": 124,
                          "stone": 0, "population": 7},
            stocks_end={"drink": 34, "food": 35, "wood": 124,
                        "stone": 0, "population": 7})
        self.assertEqual(len(summary["decisions"]), 1)
        self.assertEqual(summary["stocks_start"]["drink"], 39)
        self.assertEqual(summary["stocks_end"]["drink"], 34)
        entry = diary.render_entry(summary)
        self.assertIn("build a Still at (95, 108, 175)", entry)
        self.assertIn("Drink: 39 -> 34", entry)
        self.assertNotIn("A quiet day", entry)

    def test_merge_driver_record_replaces_journal_decisions(self):
        # Run #17: the entry invented a manager appointment and
        # credited the brewing to Olon because the Journal still
        # carried earlier reloads' decisions for the same in-game
        # ticks. The Journal is cumulative across playthroughs, so
        # its decisions for the day are from previous playthroughs
        # of the same date — the daemon loop was paused for this
        # run, so the Journal holds nothing from it. The driver's
        # decisions REPLACE the Journal's for the day; they do not
        # append to them.
        journal = FakeJournal()
        journal.add_decision(169300, "appoint a manager",
                             reason="Need a manager noble",
                             action="appoint_manager", ok=False)
        journal.add_decision(169400,
                             "enable BREWER labor on Olon Medtobalod",
                             reason="Need a brewer",
                             action="labor_toggle", ok=True)
        summary = _day_summary(journal=journal)
        self.assertEqual(len(summary["decisions"]), 2)
        diary.merge_driver_record(
            summary,
            decisions=[{
                "decision": "build a Still at (95, 108, 175)",
                "reason": "No still exists, so brewing is impossible.",
                "action": "build_workshop", "ok": True,
                "result": "still workshop #8 built"}])
        self.assertEqual(len(summary["decisions"]), 1)
        self.assertEqual(
            summary["decisions"][0]["decision"],
            "build a Still at (95, 108, 175)")
        entry = diary.render_entry(summary)
        self.assertNotIn("appoint a manager", entry)
        self.assertNotIn("Olon Medtobalod", entry)

    def test_merge_driver_record_empty_changes_nothing(self):
        summary = _day_summary()
        before = dict(summary)
        diary.merge_driver_record(summary)
        self.assertEqual(summary["decisions"], before["decisions"])
        self.assertEqual(summary["stocks_start"],
                         before["stocks_start"])

    def test_entry_states_recorded_facts_only(self):
        store = FakeStore()
        store.add_trend("drink", 169200, 9.0)
        store.add_trend("drink", 170400, 8.0)
        store.add_trend("food", 169200, 25.0)
        journal = FakeJournal()
        journal.add_decision(169300, "brew drink",
                             reason="Drink is low: 9 units left",
                             action="brew", ok=True)
        s = _day_summary(store=store, journal=journal)
        entry = diary.render_entry(s)
        self.assertIn("2nd of Galena, 125", entry)
        self.assertIn("Drink: 9 -> 8", entry)
        self.assertIn("Food: 25", entry)
        self.assertIn("brew drink", entry)
        self.assertIn("It worked.", entry)
        # No invented events: no death, no arrival, no threat.
        self.assertNotIn("died", entry)
        self.assertNotIn("joined", entry)
        self.assertNotIn("hostile", entry)

    def test_death_entry_names_cause(self):
        store = FakeStore()
        store.add_death(169500, 42, "died of thirst")
        s = _day_summary(store=store)
        entry = diary.render_entry(s)
        self.assertIn("died of thirst", entry)
        # The unit id is harness-internal; the overseer names the
        # death, not the id.
        self.assertNotIn("id 42", entry)

    def test_quiet_day_says_so(self):
        s = _day_summary()
        entry = diary.render_entry(s)
        self.assertIn("quiet day", entry.lower())


class TestDiaryQuality(unittest.TestCase):
    """The 2026-11-27 quality pass: root-cause fixes, not patches.

    Each test pins one of the defects found in the live diary.md:
    a stock hitting zero called "quiet", a distress diagnostic
    rendered as a decision, internal debris in the text, the
    "22th" ordinal, "Souls" for population, and one decision
    repeated 93 times.
    """

    def test_ordinal_22nd(self):
        self.assertEqual(diary.date_words(5 * 33600 + 21 * 1200, 125),
                         "22nd of Galena, 125")
        self.assertEqual(diary.date_words(5 * 33600 + 10 * 1200, 125),
                         "11th of Galena, 125")
        self.assertEqual(diary.date_words(5 * 33600 + 22 * 1200, 125),
                         "23rd of Galena, 125")

    def test_stock_zero_is_not_quiet(self):
        # The 125-06-20 defect: drink 6 -> 0, no events, and the
        # entry called it a quiet day. A stock hitting zero is
        # significant even when no event record fired.
        store = FakeStore()
        store.add_trend("drink", 169200, 6.0)
        store.add_trend("drink", 170400, 0.0)
        s = _day_summary(store=store)
        entry = diary.render_entry(s)
        self.assertNotIn("quiet day", entry.lower())
        self.assertIn("The last of the drink ran out today.", entry)

    def test_stock_at_zero_stays_significant(self):
        store = FakeStore()
        store.add_trend("drink", 169200, 0.0)
        store.add_trend("drink", 170400, 0.0)
        s = _day_summary(store=store)
        entry = diary.render_entry(s)
        self.assertNotIn("quiet day", entry.lower())
        self.assertIn("There is no drink left in the fort.", entry)

    def test_log_decision_becomes_observation_not_decision(self):
        # The 125-06-28 defect: a distress diagnostic rendered as
        # "I decided to a dwarf is in distress. 1 citizen(s) past
        # a distress line: ... (see PLANNER.md) (logged)".
        journal = FakeJournal()
        journal.add_decision(
            169300, "a dwarf is in distress",
            reason="1 citizen(s) past a distress line: "
                   "Olon Medtobalod (thirsty) — check drink/food "
                   "stocks first (the usual cause); no hospital "
                   "zone exists yet (see PLANNER.md)",
            action="log", ok=True, result="logged")
        s = _day_summary(journal=journal)
        self.assertEqual(len(s["decisions"]), 0)
        entry = diary.render_entry(s)
        self.assertNotIn("I decided to a dwarf", entry)
        self.assertNotIn("PLANNER.md", entry)
        self.assertNotIn("(logged)", entry)
        self.assertNotIn("check drink/food", entry)
        self.assertIn("Olon Medtobalod was in distress, thirsty.",
                      entry)

    def test_distress_plural(self):
        self.assertEqual(
            diary.parse_distress(
                "15 citizen(s) past a distress line: Udil (thirsty), "
                "Zefon (thirsty) — check stocks"),
            "2 dwarves were in distress, all thirsty.")
        self.assertIsNone(diary.parse_distress("brew drink"))

    def test_repeated_decision_collapses_to_one(self):
        # The 125-04-01 defect: one decision repeated 93 times.
        journal = FakeJournal()
        for _ in range(30):
            journal.add_decision(169300, "appoint a manager",
                                 action="ui:appoint_noble", ok=False)
        s = _day_summary(journal=journal)
        self.assertEqual(len(s["decisions"]), 1)
        entry = diary.render_entry(s)
        self.assertEqual(entry.count("appoint a manager"), 1)
        self.assertIn("It did not work.", entry)

    def test_changed_outcome_kept_as_retry(self):
        journal = FakeJournal()
        journal.add_decision(169300, "appoint a manager",
                             action="ui:appoint_noble", ok=False)
        journal.add_decision(169400, "appoint a manager",
                             action="ui:appoint_noble", ok=True)
        s = _day_summary(journal=journal)
        self.assertEqual(len(s["decisions"]), 2)
        entry = diary.render_entry(s)
        self.assertIn("I tried again to appoint a manager.", entry)

    def test_int_ok_normalized_and_unknown_ok_no_retry(self):
        # The Journal stores ok as SQLite ints (0/1); the renderer
        # must see them as outcomes, and an outcome-less repeat
        # must not add a story beat.
        journal = FakeJournal()
        journal.add_decision(169300, "appoint a manager",
                             action="ui:appoint_noble", ok=0)
        journal.add_decision(169400, "appoint a manager",
                             action="ui:appoint_noble", ok=1)
        journal.add_decision(169500, "appoint a manager",
                             action="ui:appoint_noble", ok=None)
        s = _day_summary(journal=journal)
        self.assertEqual(len(s["decisions"]), 2)
        entry = diary.render_entry(s)
        self.assertIn("I decided to appoint a manager. "
                      "It did not work.", entry)
        self.assertIn("I tried again to appoint a manager. "
                      "It worked.", entry)

    def test_oscillating_outcome_told_once_per_outcome(self):
        # The planner re-decides every tick, so one decision's
        # outcome can flip (failed, worked, failed, worked) across
        # the day. The diary tells it once per outcome, not once
        # per flip — the 125-04-01 entry rendered "appoint a
        # manager" five times before this cap.
        journal = FakeJournal()
        for i, ok in enumerate([False, True, False, True, False]):
            journal.add_decision(169300 + i * 100, "appoint a manager",
                                 action="ui:appoint_noble", ok=ok)
        s = _day_summary(journal=journal)
        self.assertEqual(len(s["decisions"]), 2)
        entry = diary.render_entry(s)
        self.assertEqual(entry.count("appoint a manager"), 2)

    def test_population_uses_citizens(self):
        store = FakeStore()
        store.add_trend("population", 169200, 10.0)
        s = _day_summary(store=store)
        entry = diary.render_entry(s)
        self.assertIn("Citizens: 10", entry)
        self.assertNotIn("Souls", entry)

    def test_ledger_stocks_round_trips(self):
        start, end = diary.ledger_stocks(
            "Drink: 39 -> 33 Food: 32 Wood: 124 Stone: 0 Citizens: 7.")
        self.assertEqual(start["drink"], 39)
        self.assertEqual(end["drink"], 33)
        self.assertEqual(end["population"], 7)
        # The old "Souls" label parses too.
        start, end = diary.ledger_stocks("Souls: 10.")
        self.assertEqual(start["population"], 10)
        self.assertEqual(diary.ledger_stocks("A quiet day."), ({}, {}))


class TestWriteEntry(unittest.TestCase):
    def test_append_and_regenerate_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = _day_summary()
            md_path = diary.write_entry(tmp, s)
            self.assertTrue(md_path.exists())
            text = md_path.read_text()
            self.assertIn("## 125-06-02", text)
            self.assertIn("Erushtathtat", text)
            html_path = diary.diary_html_path(tmp)
            self.assertTrue(html_path.exists())
            html_doc = html_path.read_text()
            self.assertIn("125-06-02", html_doc)
            self.assertIn("Diary of Erushtathtat", html_doc)

    def test_rewrite_same_date_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = _day_summary()
            diary.write_entry(tmp, s)
            diary.write_entry(tmp, s)
            text = diary.diary_md_path(tmp).read_text()
            self.assertEqual(text.count("## 125-06-02"), 1)

    def test_two_days_both_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            diary.write_entry(tmp, _day_summary(day_start=169200))
            diary.write_entry(tmp, _day_summary(day_start=170400))
            entries = diary.parse_entries(
                diary.diary_md_path(tmp).read_text())
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0]["date"], "125-06-02")
            self.assertEqual(entries[1]["date"], "125-06-03")


class TestRenderHtml(unittest.TestCase):
    def test_html_is_self_contained_and_navigable(self):
        with tempfile.TemporaryDirectory() as tmp:
            diary.write_entry(tmp, _day_summary(day_start=169200))
            diary.write_entry(tmp, _day_summary(day_start=170400))
            html_doc = diary.diary_html_path(tmp).read_text()
            # One file: entries embedded as JSON, no external assets.
            self.assertNotIn("http://", html_doc)
            self.assertNotIn("https://", html_doc)
            self.assertIn("ENTRIES =", html_doc)
            # DF palette + layout markers.
            self.assertIn("#FFFF55", html_doc)  # yellow accent
            self.assertIn("prev day", html_doc)
            self.assertIn("jump to latest", html_doc)
            # Both entries are in the embedded data.
            data = json.loads(re.search(
                r"var ENTRIES = (\[.*?\]);", html_doc,
                re.DOTALL).group(1))
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]["date"], "125-06-02")


if __name__ == "__main__":
    unittest.main()
