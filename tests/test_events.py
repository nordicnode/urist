"""Unit tests for the phase-3 event system (offline, fixture-based).

Fixtures: ``tests/fixtures/events-base.json`` is a real Athelunol
snapshot (tick 93135, 7 citizens, drink 39 / food 38, 168 combat
reports) trimmed to the sections the detector reads; variants are
built by mutating deep copies in the tests. ``watch-log.jsonl`` holds
sample raw watcher records, including a duplicate and a malformed
line.
"""

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import events as ev  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_base() -> dict:
    return json.loads((FIXTURES / "events-base.json").read_text())


def types(found):
    return [e["type"] for e in found]


def by_type(found, type_):
    return [e for e in found if e["type"] == type_]


class TestMakeEvent(unittest.TestCase):
    def test_envelope_and_urgency(self):
        event = ev.make_event("threat", "critical",
                              {"unit_id": 88}, tick=100, year=306)
        self.assertEqual(event["urgency"], "immediate")
        self.assertEqual(event["severity"], "critical")
        self.assertEqual(event["source"], "poll")
        self.assertIsNone(event["seq"])
        self.assertNotIn("dedup_key", event)

    def test_urgency_mapping(self):
        self.assertEqual(ev.make_event("x", "warning")["urgency"], "soon")
        self.assertEqual(ev.make_event("x", "notice")["urgency"], "routine")
        self.assertEqual(ev.make_event("x", "info")["urgency"], "low")

    def test_bad_severity(self):
        with self.assertRaises(ValueError):
            ev.make_event("x", "dire")


class TestDiffDetectorStatus(unittest.TestCase):
    def setUp(self):
        self.det = ev.DiffDetector()
        self.base = load_base()

    def test_first_snapshot_is_baseline(self):
        self.assertEqual(self.det.detect(self.base), [])

    def test_pause_toggle_fires_twice(self):
        # Regression: the bus used to swallow the second toggle because
        # the dedup key was the same; the detector must not key pause
        # events at all (it is edge-triggered, single source).
        self.det.detect(self.base)
        s2 = copy.deepcopy(self.base)
        s2["status"]["paused"] = False
        found = self.det.detect(s2)
        self.assertEqual(types(found), ["pause"])
        self.assertEqual(found[0]["data"], {"paused": False})
        s3 = copy.deepcopy(s2)
        s3["status"]["paused"] = True
        found = self.det.detect(s3)
        self.assertEqual(types(found), ["pause"])
        self.assertEqual(found[0]["data"], {"paused": True})

    def test_no_event_without_change(self):
        self.det.detect(self.base)
        self.assertEqual(self.det.detect(copy.deepcopy(self.base)), [])

    def test_season_and_year(self):
        self.det.detect(self.base)
        s2 = copy.deepcopy(self.base)
        s2["status"]["season_index"] = 1
        s2["status"]["season"] = "Summer"
        s2["status"]["year_tick"] = 100800
        found = self.det.detect(s2)
        self.assertEqual(types(found), ["season_change"])
        self.assertEqual(found[0]["data"]["season"], "Summer")
        s3 = copy.deepcopy(s2)
        s3["status"]["year"] = 307
        found = self.det.detect(s3)
        self.assertEqual(types(found), ["year"])

    def test_mode_change(self):
        self.det.detect(self.base)
        s2 = copy.deepcopy(self.base)
        s2["status"]["focus"] = "dwarfmode/ViewUnits"
        found = self.det.detect(s2)
        self.assertEqual(types(found), ["mode"])


class TestDiffDetectorCitizens(unittest.TestCase):
    def setUp(self):
        self.det = ev.DiffDetector()
        self.base = load_base()

    def test_citizen_new_and_gone(self):
        self.det.detect(self.base)
        s2 = copy.deepcopy(self.base)
        new_citizen = copy.deepcopy(s2["units"]["citizens"][0])
        new_citizen["id"] = 9999
        new_citizen["name"] = "Bim Kereshtân"
        s2["units"]["citizens"].append(new_citizen)
        s2["units"]["citizen_count"] = 8
        found = self.det.detect(s2)
        self.assertEqual(types(found), ["citizen_new"])
        self.assertEqual(found[0]["data"]["unit_id"], 9999)
        s3 = copy.deepcopy(s2)
        s3["units"]["citizens"] = [
            c for c in s3["units"]["citizens"] if c["id"] != 9999]
        found = self.det.detect(s3)
        self.assertEqual(types(found), ["citizen_gone"])
        self.assertEqual(found[0]["data"]["unit_id"], 9999)

    def test_threat(self):
        self.det.detect(self.base)
        s2 = copy.deepcopy(self.base)
        s2["units"]["hostiles"].append(
            {"id": 88, "name": "Goblin thief", "race": "Goblin",
             "pos": [98, 102, 42]})
        s2["units"]["hostile_count"] = 1
        found = self.det.detect(s2)
        self.assertEqual(types(found), ["threat"])
        self.assertEqual(found[0]["severity"], "critical")
        self.assertEqual(found[0]["data"]["unit_id"], 88)
        # Persists: no re-fire.
        self.assertEqual(self.det.detect(copy.deepcopy(s2)), [])


class TestDiffDetectorDistress(unittest.TestCase):
    def setUp(self):
        self.det = ev.DiffDetector()
        self.base = load_base()

    def _with_citizen(self, **overrides):
        s2 = copy.deepcopy(self.base)
        c = s2["units"]["citizens"][0]
        for key, value in overrides.items():
            if key in ("hunger", "thirst", "sleepiness"):
                c["counters"][key] = value
            elif key == "stress_category":
                c["stress"]["category"] = value
            elif key == "stress_level":
                c["stress"]["level"] = value
            elif key == "wound_count":
                c["wound_count"] = value
                c["wounds"] = [{"id": i, "parts": 1}
                               for i in range(value)]
            else:
                c[key] = value
        return s2

    def test_below_thresholds_no_event(self):
        # Fixture hunger is 34,651-35,670: below the 50,000 starving
        # line, so the baseline emits nothing.
        self.det.detect(self.base)
        s2 = self._with_citizen(hunger=49_999, thirst=29_999,
                                sleepiness=59_999)
        self.assertEqual(self.det.detect(s2), [])

    def test_starving_warning_then_critical_then_rearm(self):
        self.det.detect(self.base)
        found = self.det.detect(self._with_citizen(hunger=51_000))
        distress = by_type(found, "dwarf_distress")
        self.assertEqual(len(distress), 1)
        self.assertEqual(distress[0]["data"]["kind"], "starving")
        self.assertEqual(distress[0]["severity"], "warning")
        # Severity rise re-fires.
        found = self.det.detect(self._with_citizen(hunger=71_000))
        distress = by_type(found, "dwarf_distress")
        self.assertEqual(len(distress), 1)
        self.assertEqual(distress[0]["severity"], "critical")
        # Clears below the line, then re-arms and fires again: the
        # bus must not swallow the second firing (activation counter).
        self.assertEqual(
            self.det.detect(self._with_citizen(hunger=40_000)), [])
        found = self.det.detect(self._with_citizen(hunger=51_000))
        distress = by_type(found, "dwarf_distress")
        self.assertEqual(len(distress), 1)
        self.assertEqual(distress[0]["severity"], "warning")

    def test_thirsty_and_exhausted(self):
        self.det.detect(self.base)
        found = self.det.detect(self._with_citizen(
            thirst=31_000, sleepiness=61_000))
        kinds = sorted(e["data"]["kind"] for e in
                       by_type(found, "dwarf_distress"))
        self.assertEqual(kinds, ["exhausted", "thirsty"])

    def test_stress_kinds(self):
        self.det.detect(self.base)
        found = self.det.detect(self._with_citizen(
            stress_category=1, stress_level=30_000))
        distress = by_type(found, "dwarf_distress")
        self.assertEqual([e["data"]["kind"] for e in distress],
                         ["unhappy"])
        found = self.det.detect(self._with_citizen(
            stress_category=0, stress_level=60_000))
        distress = by_type(found, "dwarf_distress")
        self.assertEqual([e["data"]["kind"] for e in distress],
                         ["tantrum_risk"])

    def test_wounded_and_count_change(self):
        self.det.detect(self.base)
        found = self.det.detect(self._with_citizen(wound_count=2))
        distress = by_type(found, "dwarf_distress")
        self.assertEqual(len(distress), 1)
        self.assertEqual(distress[0]["data"]["kind"], "wounded")
        # More wounds re-fire (same kind, new count).
        found = self.det.detect(self._with_citizen(wound_count=3))
        distress = by_type(found, "dwarf_distress")
        self.assertEqual(len(distress), 1)
        # Healed: clears, no event.
        self.assertEqual(
            self.det.detect(self._with_citizen(wound_count=0)), [])


class TestDiffDetectorJobsReportsStocks(unittest.TestCase):
    def setUp(self):
        self.det = ev.DiffDetector()
        self.base = load_base()

    def test_job_disappearance_is_completion(self):
        s1 = copy.deepcopy(self.base)
        s1["jobs"]["list"] = [{"id": 7, "type": "FellTree",
                               "pos": [110, 98, 32]}]
        s1["jobs"]["count"] = 1
        s1["jobs"]["counts_by_type"] = [{"type": "FellTree", "count": 1}]
        self.det.detect(s1)
        found = self.det.detect(copy.deepcopy(self.base))
        completed = by_type(found, "job_completed")
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["data"]["job_id"], 7)
        self.assertEqual(completed[0]["data"]["job_type"], "FellTree")

    def test_job_disappearance_with_cancels_is_not_completion(self):
        s1 = copy.deepcopy(self.base)
        s1["jobs"]["list"] = [{"id": 7, "type": "ConstructBuilding",
                               "pos": [100, 85, 42]}]
        s1["jobs"]["count"] = 1
        self.det.detect(s1)
        s2 = copy.deepcopy(self.base)
        s2["reports"]["announcements"] = list(
            self.base["reports"]["announcements"]) + [{
                "text": "Udil cancels Construct Building: "
                        "Needs building material",
                "year": 306, "time": 94000, "pos": [100, 85, 42]}]
        found = self.det.detect(s2)
        self.assertEqual(types(found), ["job_cancelled"])
        self.assertEqual(found[0]["severity"], "warning")

    def test_manager_order_disappearance(self):
        s1 = copy.deepcopy(self.base)
        s1["jobs"]["manager_orders"] = [{
            "id": 1, "job_type": 123, "job_type_name": "MakeBarrel",
            "amount_left": 5, "amount_total": 5}]
        s1["jobs"]["manager_order_count"] = 1
        self.det.detect(s1)
        found = self.det.detect(copy.deepcopy(self.base))
        completed = by_type(found, "job_completed")
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]["data"]["manager_order_id"], 1)
        self.assertEqual(completed[0]["data"]["job_type"], "MakeBarrel")

    def test_new_report_and_no_refire(self):
        self.det.detect(self.base)
        s2 = copy.deepcopy(self.base)
        s2["reports"]["announcements"] = list(
            self.base["reports"]["announcements"]) + [{
                "text": "Some migrants have arrived.",
                "year": 306, "time": 123590, "pos": None}]
        s2["reports"]["announcement_count"] = 7
        found = self.det.detect(s2)
        self.assertEqual(types(found), ["report"])
        self.assertIn("migrants", found[0]["data"]["text"])
        # Same snapshot again: no re-fire.
        self.assertEqual(self.det.detect(copy.deepcopy(s2)), [])

    def test_stock_low_warning_critical_rearm(self):
        self.det.detect(self.base)  # drink 39 / food 38: ok
        s2 = copy.deepcopy(self.base)
        s2["stocks"]["drink_units"] = 19
        found = self.det.detect(s2)
        low = by_type(found, "stock_low")
        self.assertEqual(len(low), 1)
        self.assertEqual(low[0]["data"], {
            "kind": "drink", "units": 19, "threshold": 20})
        self.assertEqual(low[0]["severity"], "warning")
        s3 = copy.deepcopy(s2)
        s3["stocks"]["drink_units"] = 4
        found = self.det.detect(s3)
        low = by_type(found, "stock_low")
        self.assertEqual(len(low), 1)
        self.assertEqual(low[0]["severity"], "critical")
        # Recovered, then low again: fires again.
        s4 = copy.deepcopy(s3)
        s4["stocks"]["drink_units"] = 30
        self.assertEqual(self.det.detect(s4), [])
        s5 = copy.deepcopy(s4)
        s5["stocks"]["drink_units"] = 12
        s5["stocks"]["food_units"] = 10
        found = self.det.detect(s5)
        low = by_type(found, "stock_low")
        self.assertEqual(sorted(e["data"]["kind"] for e in low),
                         ["drink", "food"])

    def test_mandate(self):
        self.det.detect(self.base)
        s2 = copy.deepcopy(self.base)
        s2["mandates"] = [{"id": 3, "type": "MakeItem",
                           "amount": 2}]
        found = self.det.detect(s2)
        self.assertEqual(types(found), ["mandate"])
        self.assertEqual(found[0]["severity"], "warning")
        self.assertEqual(self.det.detect(copy.deepcopy(s2)), [])


class TestEventBus(unittest.TestCase):
    def test_order_seq_and_subscribers(self):
        bus = ev.EventBus()
        seen = []
        bus.subscribe(seen.append)
        for i in range(3):
            stamped = bus.publish(ev.make_event("report", "notice",
                                                {"n": i}))
            self.assertEqual(stamped["seq"], i + 1)
            self.assertEqual(stamped["id"], f"evt-{i + 1}")
        self.assertEqual([e["seq"] for e in seen], [1, 2, 3])

    def test_dedup_and_ring_eviction(self):
        bus = ev.EventBus(maxlen=3)
        e1 = bus.publish(ev.make_event("job_completed", "info",
                                       {"job_id": 7},
                                       dedup_key="job_completed:7"))
        self.assertIsNotNone(e1)
        self.assertIsNone(bus.publish(ev.make_event(
            "job_completed", "info", {"job_id": 7},
            dedup_key="job_completed:7")))
        # Fill the ring past the first event; its key leaves the seen
        # set, so the same underlying change may fire again.
        for i in range(3):
            bus.publish(ev.make_event("report", "notice", {"n": i}))
        self.assertIsNotNone(bus.publish(ev.make_event(
            "job_completed", "info", {"job_id": 7},
            dedup_key="job_completed:7")))

    def test_replay(self):
        bus = ev.EventBus()
        for i in range(5):
            bus.publish(ev.make_event("report", "notice", {"n": i}))
        self.assertEqual([e["seq"] for e in bus.replay(since_seq=3)],
                         [4, 5])
        self.assertEqual([e["seq"] for e in bus.replay(limit=2)],
                         [4, 5])
        self.assertEqual([e["seq"] for e in
                          bus.replay(since_seq=2, limit=2)], [3, 4])
        self.assertEqual(bus.latest_seq, 5)

    def test_subscriber_failure_isolated(self):
        bus = ev.EventBus()
        good = []
        bus.subscribe(lambda e: 1 / 0)  # noqa: B018 - deliberate
        bus.subscribe(good.append)
        stamped = bus.publish(ev.make_event("report", "notice"))
        self.assertEqual(good, [stamped])

    def test_journal_survives_restart(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "events.jsonl"
            bus = ev.EventBus(journal_path=journal)
            bus.publish(ev.make_event("report", "notice", {"n": 1}))
            bus.publish(ev.make_event("report", "notice", {"n": 2}))
            bus2 = ev.EventBus(journal_path=journal)
            self.assertEqual(bus2.latest_seq, 2)
            self.assertEqual([e["seq"] for e in bus2.replay()], [1, 2])
            stamped = bus2.publish(ev.make_event("report", "notice",
                                                 {"n": 3}))
            self.assertEqual(stamped["seq"], 3)


class TestWatcherDrain(unittest.TestCase):
    def test_record_conversion(self):
        death = ev.watcher_record_to_event(
            {"kind": "UNIT_DEATH", "tick": 101290, "year": 306,
             "unit_id": 15284},
            resolve_unit=lambda uid: {"name": "Stray Dog",
                                      "citizen": False,
                                      "race": "Dog",
                                      "pos": [90, 90, 42]})
        self.assertEqual(death["type"], "unit_death")
        self.assertEqual(death["data"]["name"], "Stray Dog")
        self.assertFalse(death["data"]["citizen"])
        hostile = ev.watcher_record_to_event(
            {"kind": "UNIT_NEW_ACTIVE", "tick": 1, "year": 306,
             "unit_id": 15321, "hostile": True, "name": "Goblin thief",
             "race": "Goblin", "pos": [98, 102, 42]})
        self.assertEqual(hostile["type"], "hostile_spawn")
        self.assertEqual(hostile["severity"], "critical")
        self.assertIsNone(ev.watcher_record_to_event(
            {"kind": "UNIT_NEW_ACTIVE", "tick": 1, "year": 306,
             "unit_id": 15320, "hostile": False}))
        self.assertIsNone(ev.watcher_record_to_event(
            {"kind": "TICK", "tick": 1, "year": 306}))
        invasion = ev.watcher_record_to_event(
            {"kind": "INVASION", "tick": 1, "year": 306,
             "args": ["GOBLIN"]})
        self.assertEqual(invasion["type"], "invasion")
        report = ev.watcher_record_to_event(
            {"kind": "REPORT", "tick": 1, "year": 306, "index": 170,
             "time": 101350})
        self.assertEqual(report["type"], "report")
        self.assertEqual(report["data"]["report_index"], 170)

    def test_drain_fixture(self):
        drainer = ev.WatcherDrainer(FIXTURES / "watch-log.jsonl")
        found = drainer.drain()
        # 11 lines: 2 job completions + 1 duplicate completion line
        # (the drainer does not dedup — the bus does), 1 death,
        # 1 report, 1 non-hostile new-active (dropped), 1 hostile
        # spawn, 1 invasion, 1 TICK (dropped), 1 malformed (skipped),
        # 1 report without text.
        self.assertEqual(types(found), [
            "job_completed", "job_completed", "unit_death", "report",
            "hostile_spawn", "invasion", "job_completed", "report"])
        # Second drain: nothing new.
        self.assertEqual(drainer.drain(), [])

    def test_partial_line_held(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "w.jsonl"
            path.write_text(
                '{"kind": "REPORT", "tick": 1, "year": 306, '
                '"index": 1, "text": "x", "time": 1}\n'
                '{"kind": "REPORT", "tick": 2, "year": 306, "index": 2, '
                '"text": "y", "time": 2')  # no closing brace, no newline
            events, offset = ev.drain_watch_log(path, 0)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["data"]["report_index"], 1)
            # Complete the partial line; the next drain picks it up.
            with open(path, "a") as fh:
                fh.write("}\n")
            events, _ = ev.drain_watch_log(path, offset)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["data"]["report_index"], 2)

    def test_missing_file_is_empty(self):
        events, offset = ev.drain_watch_log("/nonexistent/x.jsonl", 0)
        self.assertEqual((events, offset), ([], 0))


if __name__ == "__main__":
    unittest.main()
