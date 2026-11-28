"""Tests for the day's-events reader (day_events.py).

The diary audit of 2026-11-27 found the feed had never seen the
day's events: the Journal holds only daemon lifecycle kinds, while
the real stream (job completions, reports, arrivals, cancellations)
sits in the daemon's bus event log. The reader classifies and
noise-filters that log. These tests run against synthetic JSONL so
they never touch the live game.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.day_events import read_day_events

DAY = 100800  # 125-04-01


def _event(etype, tick, year=125, **data):
    return {"type": etype, "tick": tick, "year": year,
            "at": 1795700000, "source": "poll", "data": data}


def _write(events):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl",
                                      delete=False)
    for e in events:
        tmp.write(json.dumps(e) + "\n")
    tmp.close()
    return Path(tmp.name)


class TestReadDayEvents(unittest.TestCase):
    def test_missing_file_is_empty_not_an_error(self):
        out = read_day_events(Path("/tmp/does-not-exist-urist.jsonl"),
                              125, DAY)
        self.assertFalse(out["has_events"])
        self.assertEqual(out["reports"], [])
        self.assertEqual(out["known_names"], {})

    def test_none_path_is_empty(self):
        out = read_day_events(None, 125, DAY)
        self.assertFalse(out["has_events"])

    def test_malformed_lines_are_skipped(self):
        path = Path(tempfile.mktemp(suffix=".jsonl"))
        path.write_text(
            "not json\n"
            "{\"type\": \"report\", \"tick\": 100900, \"year\": 125,"
            " \"data\": {\"text\": \"A caravan from Umshadònul has"
            " arrived.\"}}\n"
            "[1, 2, 3]\n"
            "{\"type\": \"report\", \"tick\": \"soon\", \"year\": 125,"
            " \"data\": {\"text\": \"x\"}}\n")
        out = read_day_events(path, 125, DAY)
        self.assertEqual(
            out["reports"],
            ["A caravan from Umshadònul has arrived."])

    def test_reports_keep_fort_news_drop_combat_and_fragments(self):
        path = _write([
            _event("report", 100900, text=(
                "A caravan from Umshadònul has arrived.")),
            _event("report", 100901, text=(
                "The merchants need a trade depot to unload their"
                " goods.")),
            _event("report", 100902, text=(
                "The outpost liaison Dîshmab Cattentad from"
                " Umshadònul has arrived.")),
            _event("report", 100903, text="Some migrants have"
                                          " arrived."),
            _event("report", 100904, text=(
                "Mestthos Zassezuk has become a Herbalist.")),
            _event("report", 100905, text=(
                "The dwarves were unable to complete the"
                " Carpenter's Workshop.")),
            _event("report", 100906, text=(
                "The stray dog misses the hoary marmot!")),
            _event("report", 100907, text=(
                "The hoary marmot scratches the stray dog in the"
                " throat, tearing the skin!")),
            _event("report", 100908, text="ashen item."),
            _event("report", 100909, text="It has started raining."),
            _event("report", 100910, text=(
                "A caravan from Umshadònul has arrived.")),
        ])
        out = read_day_events(path, 125, DAY)
        self.assertEqual(out["reports"], [
            "A caravan from Umshadònul has arrived.",
            "The merchants need a trade depot to unload their"
            " goods.",
            "The outpost liaison Dîshmab Cattentad from"
            " Umshadònul has arrived.",
            "Some migrants have arrived.",
            "Mestthos Zassezuk has become a Herbalist.",
            "The dwarves were unable to complete the"
            " Carpenter's Workshop.",
        ])
        self.assertEqual(out["weather"], ["It has started raining."])
        self.assertEqual(out["dropped_reports"], 3)
        self.assertTrue(out["has_events"])

    def test_year_filter_ignores_the_other_fort(self):
        path = _write([
            _event("report", 100900, year=306, text=(
                "A caravan from Umshadònul has arrived.")),
            _event("report", 100901, text=(
                "A caravan from Umshadònul has arrived.")),
        ])
        out = read_day_events(path, 125, DAY)
        self.assertEqual(len(out["reports"]), 1)

    def test_completions_group_by_worker_and_job(self):
        path = _write([
            _event("job_completed", 100900, job_type="Drink2",
                   worker_id=5409),
            _event("job_completed", 100901, job_type="Drink2",
                   worker_id=5409),
            _event("job_completed", 100902, job_type="Drink2",
                   worker_id=5410),
            _event("job_completed", 100903,
                   job_type="ConstructBuilding", worker_id=5410),
            _event("job_completed", 100904,
                   job_type="ConstructBuilding", worker_id=5410),
            _event("job_completed", 100905, job_type="GatherPlants",
                   worker_id=None),
            _event("job_completed", 100906, job_type="GatherPlants",
                   worker_id=None),
        ])
        names = {5409: "Olon Medtobalod", 5410: "Lòr Mebzuthkin"}
        out = read_day_events(path, 125, DAY, names)
        by_key = {(c["name"], c["job"]): c
                  for c in out["completions"]}
        self.assertEqual(by_key[("Olon Medtobalod", "Drink2")][
            "count"], 2)
        self.assertTrue(by_key[("Olon Medtobalod", "Drink2")][
            "routine"])
        self.assertEqual(by_key[("Lòr Mebzuthkin",
                                 "ConstructBuilding")]["count"], 2)
        self.assertFalse(by_key[("Lòr Mebzuthkin",
                                 "ConstructBuilding")]["routine"])
        self.assertEqual(by_key[("", "GatherPlants")]["count"], 2)
        self.assertEqual(by_key[("Olon Medtobalod", "Drink2")][
            "worker_id"], 5409)

    def test_cancellations_name_dwarf_and_job_but_not_reason(self):
        # The report text is truncated ("Needs " cut off) — the
        # feed states the cancellation and never the reason.
        path = _write([
            _event("job_cancelled", 100900, text=(
                "Lòr Mebzuthkin, expedition leader cancels"
                " Construct Building: Needs ")),
        ])
        out = read_day_events(path, 125, DAY)
        self.assertEqual(out["cancellations"], [
            {"name": "Lòr Mebzuthkin",
             "job": "Construct Building"}])

    def test_arrivals_name_migrants_and_fill_known_names(self):
        path = _write([
            _event("citizen_new", 201600, unit_id=1700,
                   name="Litast Aknònul", profession="Bowyer",
                   pos=[20, 1, 181]),
            _event("citizen_new", 201600, unit_id=1778,
                   name="Cog Letmossazir", profession="Stonecrafter",
                   pos=[33, 7, 180]),
        ])
        out = read_day_events(path, 125, 201600)
        self.assertEqual(out["arrivals"], [
            {"name": "Litast Aknònul", "profession": "Bowyer"},
            {"name": "Cog Letmossazir",
             "profession": "Stonecrafter"},
        ])
        self.assertEqual(out["known_names"][1700]["name"],
                         "Litast Aknònul")
        self.assertEqual(out["known_names"][1778]["profession"],
                         "Stonecrafter")

    def test_citizen_gone_reload_artifact_is_dropped(self):
        # 04-01: the migrants "gone" at the day's first tick, then
        # citizen_new at 201600 — the poller re-baselining after a
        # reload, not a departure.
        path = _write([
            _event("citizen_gone", 100800, unit_id=1778,
                   name="Cog Letmossazir", pos=[33, 7, 180]),
            _event("citizen_new", 201600, unit_id=1778,
                   name="Cog Letmossazir", profession="Stonecrafter",
                   pos=[33, 7, 180]),
            _event("citizen_gone", 100900, unit_id=9999,
                   name="Gone For Good", pos=[1, 1, 175]),
        ])
        out = read_day_events(path, 125, DAY)
        self.assertEqual(out["departures"],
                         [{"name": "Gone For Good"}])

    def test_deaths_name_citizens_and_count_wildlife(self):
        path = _write([
            _event("unit_death", 100900, unit_id=5409),
            _event("unit_death", 100901, unit_id=5555),
        ])
        out = read_day_events(path, 125, DAY,
                              {5409: "Olon Medtobalod"})
        self.assertEqual(out["deaths"],
                         [{"name": "Olon Medtobalod"}])
        self.assertEqual(out["wildlife_deaths"], 1)

    def test_stock_low_alerts_are_dated(self):
        # The 06-20 "ran out today" dispute: drink hit 0 at tick
        # 192076, which is 06-21's day, not 06-20's.
        path = _write([
            _event("stock_low", 171344, kind="drink", units=9,
                   threshold=20),
            _event("stock_low", 192076, kind="drink", units=0,
                   threshold=20),
        ])
        out = read_day_events(path, 125, 170400)
        self.assertEqual(out["stock_alerts"],
                         [{"kind": "drink", "units": 9}])
        out2 = read_day_events(path, 125, 192000)
        self.assertEqual(out2["stock_alerts"],
                         [{"kind": "drink", "units": 0}])

    def test_events_outside_the_day_are_excluded(self):
        path = _write([
            _event("report", 100799, text=(
                "A caravan from Umshadònul has arrived.")),
            _event("report", 102000, text=(
                "A caravan from Umshadònul has arrived.")),
        ])
        out = read_day_events(path, 125, DAY)
        self.assertEqual(out["reports"], [])
        self.assertFalse(out["has_events"])

    def test_distress_events_are_named(self):
        path = _write([
            _event("dwarf_distress", 100900, unit_id=5408,
                   name="Rakust Cattenaval", kind="wounded",
                   detail="1 wound(s)"),
        ])
        out = read_day_events(path, 125, DAY)
        self.assertEqual(out["distress"], [
            {"name": "Rakust Cattenaval", "kind": "wounded"}])


def _raw(kind, tick, year=125, **fields):
    row = {"kind": kind, "tick": tick, "year": year}
    row.update(fields)
    return row


def _write_raw(rows):
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl",
                                      delete=False)
    for r in rows:
        tmp.write(json.dumps(r) + "\n")
    tmp.close()
    return Path(tmp.name)


class TestReadDayEventsWatchLog(unittest.TestCase):
    def test_raw_custom_reaction_is_read_with_pos_and_worker(self):
        # The bus has no CustomReaction in year 125; the raw log
        # is the only source for workshop jobs.
        bus = _write([])
        raw = _write_raw([
            _raw("JOB_COMPLETED", 100900, job_id=95,
                 job_type="CustomReaction", worker_id=5412,
                 pos=[95, 108, 175]),
        ])
        out = read_day_events(bus, 125, DAY, names={5412: "Mestthos"},
                              watch_log_path=raw)
        self.assertEqual(out["completions"], [{
            "name": "Mestthos", "job": "CustomReaction", "count": 1,
            "routine": False, "workers": ["Mestthos"],
            "worker_id": 5412, "pos": [95, 108, 175],
            "job_id": 95}])

    def test_raw_re_reports_collapse_to_one(self):
        # One completion re-reported 15 times at nearby ticks is
        # one completion, not fifteen.
        bus = _write([])
        raw = _write_raw([
            _raw("JOB_COMPLETED", 100900 + i, job_id=78,
                 job_type="ConstructBuilding", worker_id=5410,
                 pos=[93, 105, 175])
            for i in range(15)
        ])
        out = read_day_events(bus, 125, DAY, names={5410: "Lòr"},
                              watch_log_path=raw)
        self.assertEqual(len(out["completions"]), 1)
        self.assertEqual(out["completions"][0]["count"], 1)

    def test_same_job_id_reused_670_ticks_apart_is_two(self):
        # Job ids are reused: the same (job_id, type, pos, worker)
        # 670 ticks apart is two different completions (the 300
        # queued window), not one re-report.
        bus = _write([])
        raw = _write_raw([
            _raw("JOB_COMPLETED", 100900, job_id=90,
                 job_type="CustomReaction", worker_id=5410,
                 pos=[93, 105, 175]),
            _raw("JOB_COMPLETED", 101570, job_id=90,
                 job_type="CustomReaction", worker_id=5410,
                 pos=[93, 105, 175]),
        ])
        out = read_day_events(bus, 125, DAY, names={5410: "Lòr"},
                              watch_log_path=raw)
        self.assertEqual(len(out["completions"]), 1)
        self.assertEqual(out["completions"][0]["count"], 2)

    def test_one_drink_spanning_two_job_ids_is_one(self):
        # The defect the first dedup rule missed: one drink spans
        # several job ids (a Drink2 cancelled and re-queued when
        # the dwarf is interrupted, the watcher logging a
        # completion when a job disappears). Olon's 04-01 drink
        # is jobs 85 (first 101599) and 86 (first 101863): two
        # job ids, one drink — the drink stock fell by one, not
        # two. The key is (worker, job, position), no job id.
        bus = _write([])
        raw = _write_raw([
            _raw("JOB_COMPLETED", 101599, job_id=85,
                 job_type="Drink2", worker_id=5409,
                 pos=[97, 95, 175]),
            _raw("JOB_COMPLETED", 101830, job_id=85,
                 job_type="Drink2", worker_id=5409,
                 pos=[97, 95, 175]),
            _raw("JOB_COMPLETED", 101863, job_id=86,
                 job_type="Drink2", worker_id=5409,
                 pos=[97, 95, 175]),
            _raw("JOB_COMPLETED", 101919, job_id=86,
                 job_type="Drink2", worker_id=5409,
                 pos=[97, 95, 175]),
        ])
        out = read_day_events(bus, 125, DAY, names={5409: "Olon"},
                              watch_log_path=raw)
        self.assertEqual(
            [(c["job"], c["count"]) for c in out["completions"]],
            [("Drink2", 1)])

    def test_two_need_job_drinks_far_apart_are_two(self):
        # The 5000-tick need-job window is long, not infinite:
        # two drinks more than 5000 ticks apart are two drinks.
        bus = _write([])
        raw = _write_raw([
            _raw("JOB_COMPLETED", 100900, job_id=85,
                 job_type="Drink2", worker_id=5409,
                 pos=[97, 95, 175]),
            _raw("JOB_COMPLETED", 106000, job_id=86,
                 job_type="Drink2", worker_id=5409,
                 pos=[97, 95, 175]),
        ])
        out = read_day_events(bus, 125, DAY, names={5409: "Olon"},
                              watch_log_path=raw)
        self.assertEqual(
            [(c["job"], c["count"]) for c in out["completions"]],
            [("Drink2", 1)])
        out2 = read_day_events(bus, 125, 105600,
                               names={5409: "Olon"},
                               watch_log_path=raw)
        self.assertEqual(
            [(c["job"], c["count"]) for c in out2["completions"]],
            [("Drink2", 1)])

    def test_bus_row_duplicating_raw_by_worker_and_tick_is_dropped(self):
        # The bus dedup is (worker, job, tick-window), not
        # (job_id, job): a bus row for the same drink under a
        # different job id is still the same drink.
        bus = _write([
            _event("job_completed", 100900, job_type="Drink2",
                   worker_id=5409, job_id=999),
        ])
        raw = _write_raw([
            _raw("JOB_COMPLETED", 100900, job_id=85,
                 job_type="Drink2", worker_id=5409,
                 pos=[97, 95, 175]),
        ])
        out = read_day_events(bus, 125, DAY, names={5409: "Olon"},
                              watch_log_path=raw)
        self.assertEqual(
            [(c["job"], c["count"]) for c in out["completions"]],
            [("Drink2", 1)])

    def test_bus_row_same_job_different_worker_is_kept(self):
        # Two dwarves drinking are two drinks, even at the same
        # tick and the same stockpile.
        bus = _write([
            _event("job_completed", 100900, job_type="Drink2",
                   worker_id=5411, job_id=86),
        ])
        raw = _write_raw([
            _raw("JOB_COMPLETED", 100900, job_id=85,
                 job_type="Drink2", worker_id=5409,
                 pos=[97, 95, 175]),
        ])
        out = read_day_events(
            bus, 125, DAY, names={5409: "Olon", 5411: "Zulban"},
            watch_log_path=raw)
        self.assertEqual(
            sorted((c["name"], c["count"])
                   for c in out["completions"]),
            [("Olon", 1), ("Zulban", 1)])

    def test_bus_row_same_job_far_outside_cluster_is_kept(self):
        # A bus row for the same worker and job, but thousands of
        # ticks after the raw cluster ended, is a second drink,
        # not a duplicate.
        bus = _write([
            _event("job_completed", 106500, job_type="Drink2",
                   worker_id=5409, job_id=86),
        ])
        raw = _write_raw([
            _raw("JOB_COMPLETED", 100900, job_id=85,
                 job_type="Drink2", worker_id=5409,
                 pos=[97, 95, 175]),
        ])
        out = read_day_events(bus, 125, 105600,
                              names={5409: "Olon"},
                              watch_log_path=raw)
        self.assertEqual(
            [(c["job"], c["count"]) for c in out["completions"]],
            [("Drink2", 1)])

    def test_bus_baseline_burst_is_dropped(self):
        # The poller's day-start baseline: every job in progress
        # at the day's first tick, worker None. Three or more
        # worker-None rows at one tick are a baseline, not
        # completions — the 04-01 bus file has 18 of them.
        bus = _write([
            _event("job_completed", 100800, job_type="GatherPlants",
                   worker_id=None, job_id=194),
            _event("job_completed", 100800, job_type="GatherPlants",
                   worker_id=None, job_id=195),
            _event("job_completed", 100800, job_type="Sleep",
                   worker_id=None, job_id=201),
            _event("job_completed", 100900, job_type="Drink2",
                   worker_id=5408, job_id=80),
        ])
        out = read_day_events(bus, 125, DAY,
                              names={5408: "Rakust"})
        self.assertEqual(
            [(c["job"], c["count"]) for c in out["completions"]],
            [("Drink2", 1)])

    def test_bus_row_duplicating_raw_is_dropped_raw_wins(self):
        # The same completion in both logs (same job_id + type)
        # is one completion; the raw row wins for its position.
        bus = _write([
            _event("job_completed", 100900, job_type="ConstructBuilding",
                   worker_id=5410, job_id=78),
        ])
        raw = _write_raw([
            _raw("JOB_COMPLETED", 100900, job_id=78,
                 job_type="ConstructBuilding", worker_id=5410,
                 pos=[93, 105, 175]),
        ])
        out = read_day_events(bus, 125, DAY, names={5410: "Lòr"},
                              watch_log_path=raw)
        self.assertEqual(len(out["completions"]), 1)
        self.assertEqual(out["completions"][0]["pos"], [93, 105, 175])

    def test_raw_report_missed_by_bus_is_added_once(self):
        # A report the watcher saw and the drainer did not (the
        # caravan re-observed at 104910, index 5) is dated by its
        # earliest observation (101250, 04-01), not the replay.
        bus = _write([])
        raw = _write_raw([
            _raw("REPORT", 101250, index=5,
                 text="A caravan from Umshadònul has arrived."),
            _raw("REPORT", 104910, index=5,
                 text="A caravan from Umshadònul has arrived."),
        ])
        out = read_day_events(bus, 125, DAY, watch_log_path=raw)
        self.assertEqual(
            out["reports"],
            ["A caravan from Umshadònul has arrived."])
        out2 = read_day_events(
            bus, 125, 104400, watch_log_path=raw)
        self.assertEqual(out2["reports"], [])

    def test_known_names_carry_first_seen_tick(self):
        bus = _write([
            _event("citizen_new", 201600, unit_id=1778,
                   name="Cog Letmossazir", profession="Stonecrafter"),
        ])
        out = read_day_events(bus, 125, 201600)
        self.assertEqual(out["known_names"][1778], {
            "name": "Cog Letmossazir", "profession": "Stonecrafter",
            "first_seen_tick": 201600})

    def test_missing_watch_log_is_bus_only_not_an_error(self):
        bus = _write([
            _event("job_completed", 100900, job_type="Drink2",
                   worker_id=5408, job_id=80),
        ])
        out = read_day_events(
            bus, 125, DAY, names={5408: "Rakust"},
            watch_log_path=Path("/tmp/does-not-exist-urist.jsonl"))
        self.assertEqual(
            [(c["job"], c["count"]) for c in out["completions"]],
            [("Drink2", 1)])


class TestCoverage(unittest.TestCase):
    def test_coverage_bus_live_and_watch_dead(self):
        # The bus runs past the day; the watch log ended before
        # it (the real 06-12 shape: bus to 07-08, watch to 06-14).
        # Each source is measured, never assumed.
        bus = _write([
            _event("report", 100900,
                   text="A caravan from Umshadònul has arrived."),
            _event("job_completed", 101000, job_type="Drink2",
                   worker_id=5408, job_id=80),
            _event("report", 100950, year=124,
                   text="Last year's news, not this year's."),
        ])
        watch = _write([
            {"kind": "JOB_COMPLETED", "job_type": "Eat",
             "worker_id": 5407, "pos": [97, 95, 175], "tick": 90000,
             "year": 125, "job_id": 155},
            {"kind": "JOB_COMPLETED", "job_type": "Eat",
             "worker_id": 5407, "pos": [97, 95, 175], "tick": 95000,
             "year": 125, "job_id": 156},
        ])
        out = read_day_events(bus, 125, DAY,
                              watch_log_path=watch)
        cov = out["coverage"]
        self.assertEqual(cov["bus"], {
            "present": True, "first_tick": 100900,
            "last_tick": 101000, "in_day": 2})
        self.assertEqual(cov["watch"], {
            "present": True, "first_tick": 90000,
            "last_tick": 95000, "in_day": 0})

    def test_coverage_missing_files_are_absent_not_an_error(self):
        out = read_day_events(
            Path("/tmp/does-not-exist-urist.jsonl"), 125, DAY,
            watch_log_path=Path("/tmp/does-not-exist-urist.jsonl"))
        cov = out["coverage"]
        self.assertEqual(cov["bus"], {
            "present": False, "first_tick": None,
            "last_tick": None, "in_day": 0})
        self.assertEqual(cov["watch"], {
            "present": False, "first_tick": None,
            "last_tick": None, "in_day": 0})

    def test_completion_name_gated_on_first_seen_tick(self):
        # The real 06-12 case: uid 1700 ate that day, but the name
        # "Litast Aknûnònul" was first recorded at tick 201600,
        # sixteen days later. The feed must not name the dwarf for
        # an event before the record knew the name.
        bus = _write([
            _event("citizen_new", 201600, unit_id=1700,
                   name="Litast Aknûnònul", profession="Bowyer"),
            _event("job_completed", 181929, job_type="Eat",
                   worker_id=1700, job_id=155),
            _event("job_completed", 201700, job_type="Eat",
                   worker_id=1700, job_id=156),
        ])
        early = read_day_events(bus, 125, 181200)
        self.assertEqual(
            [(c["name"], c.get("workers") or []) for c in
             early["completions"]],
            [("", [])])
        late = read_day_events(bus, 125, 201600)
        self.assertEqual(
            [(c["name"], c.get("workers") or []) for c in
             late["completions"]],
            [("Litast Aknûnònul", ["Litast Aknûnònul"])])

    def test_tick_range_malformed_lines_are_skipped(self):
        from dfagent_harness.day_events import _tick_range
        path = Path(tempfile.mktemp(suffix=".jsonl"))
        path.write_text(
            "not json\n"
            "{\"tick\": 100900, \"year\": 125}\n"
            "{\"tick\": \"soon\", \"year\": 125}\n"
            "{\"year\": 125}\n"
            "{\"tick\": 100950, \"year\": 124}\n"
            "[1, 2, 3]\n"
            "{\"tick\": 101000, \"year\": 125}\n")
        self.assertEqual(_tick_range(path, 125, DAY),
                         (100900, 101000, 2))
        self.assertEqual(
            _tick_range(Path("/tmp/does-not-exist-urist.jsonl"),
                        125, DAY),
            (None, None, 0))


class TestReadWorkshopMap(unittest.TestCase):
    def _logs_dir(self, lines_by_file):
        tmp = tempfile.mkdtemp()
        for name, lines in lines_by_file.items():
            Path(tmp, name).write_text("\n".join(
                json.dumps(l) for l in lines) + "\n")
        return Path(tmp)

    def test_build_workshop_reason_maps_pos_to_id_and_kind(self):
        logs = self._logs_dir({
            "m1-20261127-073557.jsonl": [
                {"kind": "action", "action": {
                    "name": "build_workshop", "ok": True,
                    "reason": "still workshop #8 built at "
                              "[95, 108, 175] (construction_stage 3)"}},
                {"kind": "action", "action": {
                    "name": "build_workshop", "ok": True,
                    "reason": "carpenter workshop #7 built at "
                              "[93, 105, 175] (construction_stage 3)"}},
            ],
        })
        from dfagent_harness.day_events import read_workshop_map
        out = read_workshop_map(logs)
        self.assertEqual(out, {
            (95, 108, 175): {"id": 8, "kind": "still"},
            (93, 105, 175): {"id": 7, "kind": "carpenter"},
        })

    def test_failed_builds_malformed_lines_and_other_files_ignored(self):
        logs = self._logs_dir({
            "m1-20261127-073557.jsonl": [
                {"kind": "action", "action": {
                    "name": "build_workshop", "ok": False,
                    "reason": "still workshop #8 built at "
                              "[95, 108, 175] (construction_stage 3)"}},
                {"kind": "action", "action": {
                    "name": "queue_job", "ok": True,
                    "reason": "queue make_bed x1 on building #7"}},
                "not json",
                [1, 2, 3],
                {"kind": "action", "action": {
                    "name": "build_workshop", "ok": True,
                    "reason": "no position here"}},
            ],
            "other.jsonl": [
                {"kind": "action", "action": {
                    "name": "build_workshop", "ok": True,
                    "reason": "still workshop #99 built at "
                              "[1, 2, 3] (construction_stage 3)"}},
            ],
        })
        from dfagent_harness.day_events import read_workshop_map
        self.assertEqual(read_workshop_map(logs), {})

    def test_missing_dir_is_empty_not_an_error(self):
        from dfagent_harness.day_events import read_workshop_map
        self.assertEqual(
            read_workshop_map(Path("/tmp/does-not-exist-urist")),
            {})
        self.assertEqual(read_workshop_map(None), {})


if __name__ == "__main__":
    unittest.main()
