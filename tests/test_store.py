"""Offline tests for the State Store (world.db, design §9).

No game needed: the Store is plain SQLite. Tests cover the
snapshot baseline, areas/survey versioning, the 7-day trend slope
+ days-remaining, unit history, and the death diagnosis.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.store import (Store, diagnose_death,  # noqa: E402
                                   TICKS_PER_DAY)


class TestStoreSnapshots(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "world.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_snapshot_round_trip_and_hash(self):
        h = self.store.record_snapshot(1200, "units",
                                       "Units: 10 citizens.")
        got = self.store.get_snapshot("units")
        self.assertEqual(got["tick"], 1200)
        self.assertEqual(got["hash"], h)
        self.assertEqual(got["text"], "Units: 10 citizens.")
        # Overwrite: the new text wins.
        self.store.record_snapshot(2400, "units",
                                   "Units: 11 citizens.")
        got = self.store.get_snapshot("units")
        self.assertEqual(got["tick"], 2400)
        self.assertNotEqual(got["hash"], h)

    def test_missing_snapshot_is_none(self):
        self.assertIsNone(self.store.get_snapshot("nope"))


class TestStoreAreasSurvey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "world.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_areas_replace(self):
        areas = [{"id": "area_0001", "name": "Surface",
                  "kind": "surface",
                  "bbox": {"x0": 0, "y0": 0, "z0": 167,
                           "x1": 191, "y1": 191, "z1": 181},
                  "purpose": "the embark surface",
                  "blocks": 585, "description": "The Surface."}]
        self.store.record_areas(1200, areas,
                                {"area_0001": ["area_0002"]})
        got = self.store.get_areas()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["name"], "Surface")
        self.assertEqual(got[0]["connections"], ["area_0002"])
        self.assertEqual(got[0]["summary"]["blocks"], 585)
        # A second derivation replaces the set.
        self.store.record_areas(2400, [], {})
        self.assertEqual(self.store.get_areas(), [])

    def test_survey_versioned_by_kind(self):
        h = self.store.record_survey(1200, "water",
                                     {"total": 6602})
        got = self.store.get_survey("water")
        self.assertEqual(got["tick"], 1200)
        self.assertEqual(got["data"], {"total": 6602})
        self.assertEqual(got["hash"], h)
        self.assertFalse(got["stale"])
        self.assertIsNone(self.store.get_survey("magma"))


class TestStoreTrends(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "world.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def _sample_drink(self, values, start_tick=0):
        # One sample per in-game day, falling steadily.
        for i, v in enumerate(values):
            self.store.sample_trend(start_tick + i * TICKS_PER_DAY,
                                    "drink", v)

    def test_burn_rate_linear_fall(self):
        # Drink falls 2/day for 7 days: 20, 18, ..., 8.
        self._sample_drink([20, 18, 16, 14, 12, 10, 8])
        tick = 6 * TICKS_PER_DAY
        rate = self.store.burn_rate("drink", tick)
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(rate, 2.0, places=2)
        # 8 units left at 2/day = 4 days remaining.
        days = self.store.days_remaining("drink", tick)
        self.assertAlmostEqual(days, 4.0, places=2)

    def test_burn_rate_rising_is_negative(self):
        self._sample_drink([8, 10, 12, 14, 16, 18, 20])
        tick = 6 * TICKS_PER_DAY
        rate = self.store.burn_rate("drink", tick)
        self.assertAlmostEqual(rate, -2.0, places=2)
        # Rising stock: no days-remaining (it is not running out).
        self.assertIsNone(self.store.days_remaining("drink", tick))

    def test_burn_rate_needs_two_samples(self):
        self.store.sample_trend(0, "drink", 20)
        self.assertIsNone(self.store.burn_rate("drink", 0))
        self.assertIsNone(self.store.days_remaining("drink", 0))

    def test_burn_rate_uses_last_seven_days(self):
        # Falls 2/day for 3 days, then flat for 7 days: the 7-day
        # window (days 3..9) is entirely flat, so the rate is ~0
        # even though the stock fell earlier.
        values = [20, 18, 16, 16, 16, 16, 16, 16, 16, 16]
        self._sample_drink(values)
        tick = 9 * TICKS_PER_DAY
        rate = self.store.burn_rate("drink", tick)
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(rate, 0.0, places=1)

    def test_days_remaining_uses_current_value(self):
        # The last trend sample is stale by definition (a previous
        # day). After a reload it can be a zero from a dead timeline
        # while the real stock is positive — days_remaining must
        # use the CURRENT snapshot value, never the stale sample.
        # Verified live 2026-11-27: the last sample was 0.0 (the
        # drink-0 timeline) while the real stock was 39, and the
        # model was told "0.0 days left".
        # Drink falls 2/day for 7 days and ends at 0.
        self._sample_drink([12, 10, 8, 6, 4, 2, 0])
        tick = 6 * TICKS_PER_DAY
        # Without a current value the stale zero gives 0.0 (the
        # old behaviour, kept for callers with no snapshot).
        self.assertEqual(self.store.days_remaining("drink", tick),
                         0.0)
        # With the current snapshot value (39) the answer is
        # positive, never 0.0.
        days = self.store.days_remaining("drink", tick, current=39.0)
        self.assertGreater(days, 0)
        self.assertAlmostEqual(days, 39.0 / 2.0, places=1)

    def test_burn_rate_ignores_future_samples(self):
        # Samples from a LATER tick belong to a dead timeline (a
        # reload moved the clock backwards). They must not pollute
        # the rate at the current tick.
        self._sample_drink([20, 18, 16, 14, 12, 10, 8])
        # A dead-timeline sample far in the future (drink 0).
        self.store.sample_trend(100 * TICKS_PER_DAY, "drink", 0)
        tick = 6 * TICKS_PER_DAY
        rate = self.store.burn_rate("drink", tick)
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(rate, 2.0, places=2)

    def test_clear_trends(self):
        self._sample_drink([20, 18, 16])
        self.assertEqual(len(self.store.trend_samples("drink")), 3)
        self.store.clear_trends()
        self.assertEqual(self.store.trend_samples("drink"), [])

    def test_latest_sample_tick_max_across_metrics(self):
        # Table 4 row 1: the gate must see ANY metric's sample,
        # not drink's alone.
        self.assertIsNone(self.store.latest_sample_tick())
        self.store.sample_trend(1200, "food", 25)
        self.assertEqual(self.store.latest_sample_tick(), 1200)
        self.store.sample_trend(2400, "drink", 20)
        self.assertEqual(self.store.latest_sample_tick(), 2400)
        self.store.sample_trend(3600, "wood", 100)
        self.assertEqual(self.store.latest_sample_tick(), 3600)

    def test_clear_timeline_drops_history_and_deaths(self):
        # Table 4 row 8: a reload kills the whole timeline.
        self._sample_drink([20, 18])
        self.store.record_unit_history(
            1200, 42, pos=[97, 97, 175], job="Mine")
        self.store.record_death(1200, 43, "died of thirst")
        self.store.clear_timeline()
        self.assertEqual(self.store.trend_samples("drink"), [])
        self.assertEqual(self.store.unit_history(42), [])
        self.assertEqual(self.store.deaths(), [])

    def test_earliest_unit_z(self):
        # Table 5 row 8: the embark level is the lowest citizen z
        # at the earliest sampled tick.
        self.assertIsNone(self.store.earliest_unit_z())
        self.store.record_unit_history(
            1200, 42, pos=[97, 97, 178], job="Mine")
        self.store.record_unit_history(
            1200, 43, pos=[51, 33, 175], job="Mine")
        self.store.record_unit_history(
            2400, 42, pos=[97, 97, 160], job="Mine")
        # A miner dug down by the second day — the earliest tick
        # still pins the embark level, not the mine.
        self.assertEqual(self.store.earliest_unit_z(), 175)


class TestStoreUnitHistoryDeaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "world.db")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_unit_history_round_trip(self):
        self.store.record_unit_history(
            1200, 42, pos=[97, 97, 175], job="Drink",
            hunger=1000, thirst=5000, sleepiness=2000,
            stress=0, wounds=[])
        self.store.record_unit_history(
            2400, 42, pos=[97, 97, 175], job="Eat",
            hunger=500, thirst=1000, sleepiness=3000,
            stress=0, wounds=[])
        rows = self.store.unit_history(42)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["job"], "Drink")
        self.assertEqual(rows[1]["thirst"], 1000)
        self.assertEqual(rows[0]["pos"], [97, 97, 175])

    def test_unit_history_limit_returns_most_recent(self):
        # Table 4 row 7: a limit means the MOST RECENT N samples,
        # still oldest-first — not the earliest N.
        for i in range(5):
            self.store.record_unit_history(
                (i + 1) * 1200, 42, pos=[97, 97, 175],
                job=f"Day{i + 1}")
        rows = self.store.unit_history(42, limit=2)
        self.assertEqual([r["job"] for r in rows], ["Day4", "Day5"])
        # No limit: all five, oldest first.
        rows = self.store.unit_history(42)
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["job"], "Day1")

    def test_deaths_round_trip(self):
        self.store.record_death(2400, 42, "died of thirst",
                                history_ref="1200")
        got = self.store.deaths()
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["cause"], "died of thirst")
        self.assertEqual(got[0]["history_ref"], "1200")


class TestDiagnoseDeath(unittest.TestCase):
    def test_thirst(self):
        cause, ref = diagnose_death(
            42, [{"tick": 1200, "thirst": 25000, "hunger": 1000,
                  "sleepiness": 1000, "wounds": []}])
        self.assertIn("died of thirst", cause)
        self.assertIn("25000", cause)
        self.assertEqual(ref, "1200")

    def test_hunger(self):
        cause, _ = diagnose_death(
            42, [{"tick": 1200, "thirst": 1000, "hunger": 45000,
                  "sleepiness": 1000, "wounds": []}])
        self.assertIn("died of hunger", cause)

    def test_wounds(self):
        cause, _ = diagnose_death(
            42, [{"tick": 1200, "thirst": 1000, "hunger": 1000,
                  "sleepiness": 1000,
                  "wounds": [{"type": "cut"}, {"type": "bruise"}]}])
        self.assertIn("died of wounds", cause)
        self.assertIn("2 wounds", cause)

    def test_no_history(self):
        cause, ref = diagnose_death(42, [])
        self.assertIn("unknown", cause)
        self.assertEqual(ref, "")

    def test_nothing_at_threshold(self):
        cause, _ = diagnose_death(
            42, [{"tick": 1200, "thirst": 1000, "hunger": 1000,
                  "sleepiness": 1000, "wounds": []}])
        self.assertIn("unknown cause", cause)


if __name__ == "__main__":
    unittest.main()
