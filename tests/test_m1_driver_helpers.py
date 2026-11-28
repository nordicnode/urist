"""Offline tests for the M1 driver's diary helpers (scripts/).

The diary entry for an M1 day is built from the run's own record:
the model's decisions (as plain phrases), the start/end stocks
parsed from the run's snapshots, and the fort name from the
snapshot header. These helpers are pure functions on the driver's
own data — no game, no daemon — so they are tested here by loading
scripts/m1_driver.py directly.
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "m1_driver",
    Path(__file__).resolve().parent.parent / "scripts" / "m1_driver.py")
m1_driver = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(m1_driver)


class TestDiaryDecisionText(unittest.TestCase):
    def test_build_workshop(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "build_workshop",
                {"kind": "still", "pos": [95, 108, 175]}),
            "build a still at (95, 108, 175)")

    def test_queue_job(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "queue_job",
                {"job": "brew", "count": 5, "building_id": 8}),
            "queue brew x5 at building #8")

    def test_queue_job_names_workshop_when_kind_known(self):
        # The queue_job result detail carries the workshop kind
        # (actions.py); the phrase names it so the feed can group
        # queued jobs by workshop instead of a bare building #.
        self.assertEqual(
            m1_driver.diary_decision_text(
                "queue_job",
                {"job": "make_bed", "count": 1, "building_id": 7},
                workshop_kind="Carpenters"),
            "queue make_bed x1 at the Carpenters workshop #7")

    def test_labor_toggle(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "labor_toggle",
                {"labor": "BREWER", "unit_name": "Olon",
                 "on": True}),
            "enable BREWER labor on Olon")

    def test_unmapped_action_returns_none(self):
        # A diary phrase must be a clean action phrase — the old
        # "name k=v" fallback leaked raw kwargs into the diary.
        # An unmapped action returns None and the caller skips it.
        self.assertIsNone(m1_driver.diary_decision_text(
            "appoint_noble", {"noble": "manager"}))

    def test_dig_to_completion_uses_start_coordinate(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "dig_to_completion",
                {"box": [95, 95, 175, 95, 95, 175],
                 "mode": "down-stair"}),
            "dig a down-stair at (95, 95, 175)")

    def test_manager_order_create(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "manager_order_create",
                {"job_type": "MakeBarrel", "amount": 5}),
            "order MakeBarrel x5 from the manager")

    def test_manager_order_remove(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "manager_order_remove", {"order_id": 3}),
            "remove manager order #3")

    def test_deconstruct_building(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "deconstruct_building", {"building_id": 8}),
            "deconstruct building #8")

    def test_designate_dig(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "designate_dig",
                {"box": [90, 100, 175, 94, 104, 175], "mode": "dig"}),
            "dig at (90, 100, 175)")

    def test_build_farm_plot_uses_xyz(self):
        self.assertEqual(
            m1_driver.diary_decision_text(
                "build_farm_plot",
                {"x": 95, "y": 108, "z": 175, "width": 3, "height": 3}),
            "build a farm plot at (95, 108, 175)")


class TestParseSuggestion(unittest.TestCase):
    """The mock runs the snapshot's suggestion verbatim, so the
    parser must read the suggestion's PRIMARY action — the one the
    leading "Suggested action:" clause names first. The mock runs
    of 2026-11-27 drove task:brew three times on a fort with no
    still because the old unanchored regex matched the trailing
    brew-task clause of the still-build suggestion."""

    STILL = ("Suggested action: NO STILL EXISTS, so brewing is "
             "impossible until you build one. Build a still FIRST: "
             "build_workshop kind=still at 94, 107, 175 (a "
             "probe-verified free 3x3 site). If the build reports "
             "'site not free', gather the blocking plant or use the "
             "next free site. Only then run the brew task.")
    BREW = ("Suggested action: run the brew task "
            "(POST /v1/tasks/brew) — the fort is short on drink and "
            "brewing turns plants into drink.")
    BLOCKER = ("Suggested action: gather the brewing materials "
               "first — need 1 empty barrel for brew, have 0. Only "
               "then run the brew task (POST /v1/tasks/brew).")
    THREAT = ("Suggested action: query unit 123 to see what it is "
              "and where it is going — a demon is near the fort.")

    def test_still_build_suggestion_names_no_task(self):
        # The trailing "Only then run the brew task" is a
        # subordinate mention, not the action to run.
        self.assertIsNone(m1_driver.parse_suggestion(self.STILL))

    def test_brew_suggestion_runs_brew(self):
        self.assertEqual(m1_driver.parse_suggestion(self.BREW),
                         ("task", "brew"))

    def test_blocker_suggestion_names_no_task(self):
        self.assertIsNone(m1_driver.parse_suggestion(self.BLOCKER))

    def test_threat_suggestion_queries_the_unit(self):
        self.assertEqual(m1_driver.parse_suggestion(self.THREAT),
                         ("query", "/v1/unit/123"))

    def test_empty_suggestion_is_none(self):
        self.assertIsNone(m1_driver.parse_suggestion(None))
        self.assertIsNone(m1_driver.parse_suggestion(""))


class TestParseSnapshotStocks(unittest.TestCase):
    def test_full_section(self):
        sections = {
            "stocks": ("Stocks: drink 39, food 32, wood 124, stone 0, "
                       "brewable plants 33."),
            "status": ("Population: 7 citizens (0 idle, 0 wounded), "
                       "25 animals, 0 hostiles, 37 active units "
                       "(reconciled)."),
        }
        self.assertEqual(m1_driver.parse_snapshot_stocks(sections),
                         {"drink": 39, "food": 32, "wood": 124,
                          "stone": 0, "population": 7})

    def test_diffed_one_liner(self):
        # The snapshot diffs unchanged sections to one-liners, but
        # the parenthetical still carries the numbers.
        sections = {
            "stocks": ("stocks: unchanged (drink 35, food 32, "
                       "wood 124, stone 0, brewable plants 35)."),
            "status": "status: unchanged (7 citizens, 0 hostiles).",
        }
        self.assertEqual(m1_driver.parse_snapshot_stocks(sections),
                         {"drink": 35, "food": 32, "wood": 124,
                          "stone": 0, "population": 7})

    def test_empty_sections(self):
        self.assertEqual(m1_driver.parse_snapshot_stocks({}), {})
        self.assertEqual(m1_driver.parse_snapshot_stocks(None), {})


class TestParseSnapshotStocksText(unittest.TestCase):
    def test_full_stocks_line(self):
        # Run 064517 snap0: the log's snapshot records carry no
        # sections, so the retry must read the numbers out of the
        # rendered text.
        text = ("Erushtathtat, 125-04-01 (tick 101323) paused: True "
                "focus: dwarfmode/Default.\n\n"
                "Stocks: drink 38, food 32, wood 124, stone 0, "
                "brewable plants 38, empty barrels 2, food stacks 7.\n"
                "Population: 7 citizens (25 animals).")
        self.assertEqual(m1_driver.parse_snapshot_stocks_text(text),
                         {"drink": 38, "food": 32, "wood": 124,
                          "stone": 0, "population": 7})

    def test_empty_text(self):
        self.assertEqual(m1_driver.parse_snapshot_stocks_text(""), {})
        self.assertEqual(m1_driver.parse_snapshot_stocks_text(None),
                         {})


class TestDecisionPhraseFromLog(unittest.TestCase):
    def test_logged_phrase_preferred(self):
        rec = {"name": "queue_job",
               "params": {"job": "make_bed", "count": 1,
                          "building_id": 7},
               "phrase": ("queue make_bed x1 at the Carpenters "
                          "workshop #7"),
               "reason": "queued make_bed x1 on building #7"}
        self.assertEqual(
            m1_driver.decision_phrase_from_log(rec),
            "queue make_bed x1 at the Carpenters workshop #7")

    def test_queue_job_recovered_from_reason(self):
        # Run 064517's log has no params and no phrase — the
        # reason is the only record of the job, the count, and
        # the building. Without it every queue_job rendered as
        # "queue a job x1 at building #?" and deduped to one.
        rec = {"name": "queue_job", "params": None,
               "reason": ("queued make_barrel x4 on building #7 "
                          "(jobs [89, 90, 91, 92])")}
        self.assertEqual(
            m1_driver.decision_phrase_from_log(rec),
            "queue make_barrel x4 at building #7")

    def test_queue_job_from_params(self):
        rec = {"name": "queue_job",
               "params": {"job": "brew", "count": 2,
                          "building_id": 8},
               "reason": "queued brew x2 on building #8"}
        self.assertEqual(
            m1_driver.decision_phrase_from_log(rec),
            "queue brew x2 at building #8")

    def test_unmapped_action_returns_none(self):
        rec = {"name": "unknown_action", "params": {},
               "reason": "did something"}
        self.assertIsNone(m1_driver.decision_phrase_from_log(rec))


class TestParseFortName(unittest.TestCase):
    def test_full_header(self):
        snap = {"text": "Erushtathtat, 125-04-02 (tick 102033) "
                        "paused: True focus: dwarfmode/Default."}
        self.assertEqual(m1_driver.parse_fort_name(snap),
                         "Erushtathtat")

    def test_diffed_header(self):
        snap = {"text": "header: unchanged (Erushtathtat, 125-04-02)."}
        self.assertEqual(m1_driver.parse_fort_name(snap),
                         "Erushtathtat")

    def test_missing(self):
        self.assertEqual(m1_driver.parse_fort_name({}), "")
        self.assertEqual(m1_driver.parse_fort_name(None), "")


class TestSnapshotCitizens(unittest.TestCase):
    def test_full_units_section(self):
        snap = {"sections": {"units": {"citizens": [
            {"id": 1, "name": "Udil Testdwarf"},
            {"id": 2, "name": "Deduk Stakudunib"}]}}}
        self.assertEqual(
            [c["id"] for c in m1_driver._snapshot_citizens(snap)],
            [1, 2])

    def test_diffed_units_section_is_string(self):
        # 2026-11-27 (run #15): the final snapshot diffs the units
        # section to a one-liner STRING, and _snapshot_citizens
        # called .get on it — AttributeError killed the diary
        # write after the run had completed the day. A non-dict
        # units section carries no citizens.
        snap = {"sections": {"units": "units: unchanged (7 citizens)."}}
        self.assertEqual(m1_driver._snapshot_citizens(snap), [])

    def test_missing(self):
        self.assertEqual(m1_driver._snapshot_citizens({}), [])
        self.assertEqual(m1_driver._snapshot_citizens(None), [])
        self.assertEqual(
            m1_driver._snapshot_citizens({"sections": {}}), [])


class _StubDaemon:
    """Stands in for DaemonClient: post() captures the diary body,
    units_citizens() returns canned fresh records (or raises, to
    exercise the fallback). get() answers the pause read;
    stocks_fresh() returns canned fresh stocks (or raises);
    daemon_control() answers the loop state. status() raises: the
    pre-flight must never read the /v1/status lite cache (stale
    after a daemon restart — the run #17 false refusal)."""

    def __init__(self, fresh=None, fail_fresh=False, *, paused=True,
                 drink=38, loop_paused=True, fail_stocks=False):
        self.fresh = fresh or []
        self.fail_fresh = fail_fresh
        self.posted = []
        self.paused = paused
        self.drink = drink
        self.loop_paused = loop_paused
        self.fail_stocks = fail_stocks

    def get(self, path, timeout=120):
        if path == "/v1/pause":
            return {"paused": self.paused}
        raise AssertionError(f"unexpected GET {path}")

    def stocks_fresh(self):
        if self.fail_stocks:
            raise RuntimeError("fresh stocks collect failed")
        return {"drink_units": self.drink}

    def daemon_control(self):
        return {"loop_paused": self.loop_paused}

    def status(self):
        raise AssertionError(
            "/v1/status must not be called by pre-flight (stale cache)")

    def units_citizens(self):
        if self.fail_fresh:
            raise RuntimeError("fresh collect failed")
        return self.fresh

    def post(self, path, body):
        self.posted.append((path, body))
        return {"ok": True, "date": "125-04-06", "path": "diary.md"}


def _fresh_citizen(uid, name):
    return {"id": uid, "name": name, "profession": "Brewer",
            "job": {"type": "CustomReaction"},
            "counters": {"hunger": 100, "thirst": 50,
                         "sleepiness": 0},
            "stress": {"level": 0, "category": 6},
            "wound_count": 0, "wounds": [],
            "needs": [{"name": "Drink", "strength": 10}],
            "relations": [{"type": "deity", "name": "Rakas"}],
            "mood": -1, "mood_name": "none"}


def _snap(units, date="125-04-06", tick=108000):
    return {"tick": tick, "date": date,
            "text": f"Erushtathtat, {date} ...",
            "sections": {
                "stocks": "Stocks: drink 68, food 25, wood 121, stone 0",
                "status": "7 citizens",
                "units": units,
            }}


class TestWriteDiaryFreshCitizens(unittest.TestCase):
    """_write_diary prefers fresh full citizen records for the
    diary feed's per-dwarf samples and falls back to the
    snapshot's citizens when the fresh fetch fails."""

    def _driver(self, daemon, snap0, citizens_start_fresh):
        drv = m1_driver.M1Driver.__new__(m1_driver.M1Driver)
        drv.args = SimpleNamespace(mock=False)
        drv.daemon = daemon
        drv.start_tick = 107000
        drv.snap0 = snap0
        drv.diary_decisions = []
        drv.citizens_start_fresh = citizens_start_fresh
        drv.tick_no = 9
        self._tmp = tempfile.TemporaryDirectory()
        drv.out = Path(self._tmp.name) / "log.jsonl"
        return drv

    def tearDown(self):
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()

    def test_fresh_citizens_preferred(self):
        # The final snapshot's units section is diffed to a string
        # (the usual case) — it carries no citizens. The fresh
        # fetch is the only source of per-dwarf samples.
        fresh_end = [_fresh_citizen(5412, "Mestthos"),
                     _fresh_citizen(5410, "Olon")]
        fresh_start = [_fresh_citizen(5412, "Mestthos")]
        daemon = _StubDaemon(fresh=fresh_end)
        drv = self._driver(daemon, _snap("units: unchanged (7 "
                                         "citizens)."),
                           fresh_start)
        drv._write_diary(_snap("units: unchanged (7 citizens)."))
        self.assertEqual(len(daemon.posted), 1)
        path, body = daemon.posted[0]
        self.assertEqual(path, "/v1/control/diary")
        self.assertEqual([c["id"] for c in body["citizens"]],
                         [5412, 5410])
        self.assertEqual([c["id"] for c in body["citizens_start"]],
                         [5412])
        # The fresh records carry the fields the feed needs.
        self.assertEqual(body["citizens"][0]["mood"], -1)
        self.assertEqual(body["citizens"][0]["needs"][0]["name"],
                         "Drink")

    def test_fresh_fetch_failure_falls_back_to_snapshot(self):
        # When the fresh fetch fails, the snapshot's citizens are
        # the fallback (a full units section, as on the first tick).
        snap_units = {"citizens": [
            {"id": 1, "name": "Udil Testdwarf"},
            {"id": 2, "name": "Deduk Stakudunib"}]}
        snap0_units = {"citizens": [
            {"id": 1, "name": "Udil Testdwarf"}]}
        daemon = _StubDaemon(fail_fresh=True)
        drv = self._driver(daemon, _snap(snap0_units), None)
        drv._write_diary(_snap(snap_units))
        self.assertEqual(len(daemon.posted), 1)
        _, body = daemon.posted[0]
        self.assertEqual([c["id"] for c in body["citizens"]], [1, 2])
        self.assertEqual([c["id"] for c in body["citizens_start"]],
                         [1])


class TestPreflight(unittest.TestCase):
    """GUARD 3 decides on FRESH collects, never the snapshot text
    or the /v1/status lite cache. Run #17 (2026-11-27) was refused
    on a healthy fort ("drink 0 < 10 floor" + "citizens 0")
    because snap0 was assembled against stale store baselines from
    the previous daemon instance and the fallback to /v1/status
    returned the poller's lite zeros — the fort was actually drink
    38, 7 citizens, paused."""

    def _driver(self, daemon):
        drv = m1_driver.M1Driver.__new__(m1_driver.M1Driver)
        drv.args = SimpleNamespace(mock=True)
        drv.daemon = daemon
        drv.tick_no = 0
        drv.citizens_start_fresh = None
        self._tmp = tempfile.TemporaryDirectory()
        drv.out = Path(self._tmp.name) / "log.jsonl"
        return drv

    def tearDown(self):
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()

    def _healthy(self, **kw):
        kw.setdefault("fresh", [_fresh_citizen(i, f"D{i}")
                                for i in range(7)])
        return _StubDaemon(**kw)

    def test_healthy_fort_passes_with_empty_snapshot(self):
        # The snapshot text is not consulted at all: an empty snap
        # passes on the fresh reads alone, and the fresh citizen
        # list is stashed for the diary's run-start sample.
        drv = self._driver(self._healthy())
        self.assertEqual(drv._preflight({}), [])
        self.assertEqual(len(drv.citizens_start_fresh), 7)

    def test_stale_zero_snapshot_passes_when_fresh_is_healthy(self):
        # The run #17 case: snap0's stale baselines say drink 0
        # and 0 citizens; the fresh collects say 38 and 7. Pass.
        snap = {"sections": {
            "stocks": "Stocks: drink 0, food 25, wood 121, stone 0",
            "status": "Population: 0 citizens (0 idle, 0 wounded), "
                      "0 animals, 0 hostiles",
        }}
        drv = self._driver(self._healthy())
        self.assertEqual(drv._preflight(snap), [])

    def test_genuinely_low_drink_refused_on_fresh_value(self):
        drv = self._driver(self._healthy(drink=5))
        failures = drv._preflight({})
        self.assertEqual(len(failures), 1)
        self.assertIn("drink 5 < 10", failures[0])
        self.assertIn("fresh collect", failures[0])

    def test_zero_citizens_refused_on_fresh_value(self):
        drv = self._driver(self._healthy(fresh=[]))
        failures = drv._preflight({})
        self.assertTrue(any("citizens 0" in f for f in failures))

    def test_fresh_collect_failure_is_unreadable_not_floor(self):
        # A failed fresh collect is reported as unreadable — never
        # as a floor failure on stale data.
        drv = self._driver(self._healthy(fail_stocks=True))
        failures = drv._preflight({})
        self.assertTrue(any("unreadable" in f for f in failures))
        self.assertFalse(any("floor" in f for f in failures))

    def test_unpaused_game_refused(self):
        drv = self._driver(self._healthy(paused=False))
        failures = drv._preflight({})
        self.assertTrue(any("not paused" in f for f in failures))

    def test_loop_running_refused(self):
        drv = self._driver(self._healthy(loop_paused=False))
        failures = drv._preflight({})
        self.assertTrue(any("loop not paused" in f for f in failures))


class TestParseSnapshotStocksAny(unittest.TestCase):
    """parse_snapshot_stocks_any: the text first, the sections as
    fallback — the one stocks reader both diary paths use."""

    _TEXT = ("Erushtathtat, 125-04-01 (tick 101323) paused: True.\n\n"
             "Stocks: drink 38, food 32, wood 124, stone 0.\n"
             "Population: 7 citizens (25 animals).")
    _SECTIONS = {
        "stocks": "Stocks: drink 39, food 32, wood 124, stone 0",
        "status": "7 citizens",
    }

    def test_text_first_when_present(self):
        snap = {"text": self._TEXT, "sections": self._SECTIONS}
        self.assertEqual(m1_driver.parse_snapshot_stocks_any(snap),
                         {"drink": 38, "food": 32, "wood": 124,
                          "stone": 0, "population": 7})

    def test_sections_fallback_when_text_has_no_stocks(self):
        snap = {"text": "Erushtathtat, 125-04-01 (tick 101323).",
                "sections": self._SECTIONS}
        self.assertEqual(m1_driver.parse_snapshot_stocks_any(snap),
                         {"drink": 39, "food": 32, "wood": 124,
                          "stone": 0, "population": 7})

    def test_empty_when_neither(self):
        self.assertEqual(m1_driver.parse_snapshot_stocks_any({}), {})
        self.assertEqual(m1_driver.parse_snapshot_stocks_any(None), {})

    def test_agrees_with_sections_parse(self):
        # The live path switched to this helper: on a snapshot
        # carrying both, it must read the same numbers as the old
        # sections-only parse (the text is rendered from the same
        # collect).
        snap = {"text": self._TEXT, "sections": {
            "stocks": "Stocks: drink 38, food 32, wood 124, stone 0",
            "status": "7 citizens",
        }}
        self.assertEqual(
            m1_driver.parse_snapshot_stocks_any(snap),
            m1_driver.parse_snapshot_stocks(snap["sections"]))


class TestBuildDiaryBody(unittest.TestCase):
    """build_diary_body: the single source of truth for the diary
    POST body, used by the live driver and the retry script."""

    def test_assembles_all_nine_fields(self):
        body = m1_driver.build_diary_body(
            start_tick=107000, year=125, fort_name="Erushtathtat",
            decisions=[{"decision": "build a Still"}],
            stocks_start={"drink": 38}, stocks_end={"drink": 68},
            citizens=[{"id": 1}], citizens_start=[{"id": 1}])
        self.assertEqual(body["day_start_tick"], 106800)
        self.assertEqual(body["tick_start"], 107000)
        self.assertEqual(body["year"], 125)
        self.assertEqual(body["fort_name"], "Erushtathtat")
        self.assertEqual(body["decisions"],
                         [{"decision": "build a Still"}])
        self.assertEqual(body["stocks_start"], {"drink": 38})
        self.assertEqual(body["stocks_end"], {"drink": 68})
        self.assertEqual(body["citizens"], [{"id": 1}])
        self.assertEqual(body["citizens_start"], [{"id": 1}])

    def test_day_start_tick_floors_to_the_day(self):
        # start_tick 101323 is mid-day 125-04-01 (day = 1200 ticks,
        # day 84 starts at 100800).
        body = m1_driver.build_diary_body(
            start_tick=101323, year=125, fort_name="",
            decisions=[], stocks_start={}, stocks_end={},
            citizens=[], citizens_start=[])
        self.assertEqual(body["day_start_tick"], 100800)


_RETRY_SPEC = importlib.util.spec_from_file_location(
    "retry_diary",
    Path(__file__).resolve().parent.parent / "scripts" / "retry_diary.py")
retry_diary = importlib.util.module_from_spec(_RETRY_SPEC)
_RETRY_SPEC.loader.exec_module(retry_diary)


class TestBuildRetryBody(unittest.TestCase):
    """retry_diary.build_retry_body reconstructs the same body the
    live driver would have posted, from a run log."""

    def _recs(self):
        return [
            {"kind": "run_start", "start_tick": 101323},
            {"kind": "snapshot", "tick": None, "date": "",
             "text": ("Erushtathtat, 125-04-01 (tick 101323) paused: "
                      "True focus: dwarfmode/Default.\n\n"
                      "Stocks: drink 38, food 32, wood 124, stone 0, "
                      "brewable plants 38.\n"
                      "Population: 7 citizens (25 animals)."),
             "sections": None},
            {"kind": "action", "name": "build_workshop",
             "params": {"kind": "Still", "pos": [95, 108, 175]},
             "phrase": "build a Still at (95, 108, 175)",
             "model_reason": "need drink", "ok": True,
             "reason": "built workshop #8"},
            {"kind": "action", "name": "queue_job", "params": {},
             "model_reason": "", "ok": True,
             "reason": ("queued make_barrel x4 on building #7 "
                        "(jobs [89, 90, 91, 92])")},
            {"kind": "snapshot", "tick": None, "date": "",
             "text": ("Erushtathtat, 125-04-06 (tick 108000) paused: "
                      "True focus: dwarfmode/Default.\n\n"
                      "Stocks: drink 68, food 25, wood 121, stone 0.\n"
                      "Population: 7 citizens (25 animals)."),
             "sections": None},
        ]

    def test_rebuilds_the_live_body(self):
        body = retry_diary.build_retry_body(self._recs())
        self.assertEqual(body["day_start_tick"], 100800)
        self.assertEqual(body["tick_start"], 101323)
        self.assertEqual(body["year"], 125)
        self.assertEqual(body["fort_name"], "Erushtathtat")
        self.assertEqual(
            [d["decision"] for d in body["decisions"]],
            ["build a Still at (95, 108, 175)",
             "queue make_barrel x4 at building #7"])
        self.assertEqual(body["stocks_start"],
                         {"drink": 38, "food": 32, "wood": 124,
                          "stone": 0, "population": 7})
        self.assertEqual(body["stocks_end"],
                         {"drink": 68, "food": 25, "wood": 121,
                          "stone": 0, "population": 7})
        # The log's snapshots carry no units sections, so the
        # retry's citizens are snapshot-only (empty here) — the
        # known limit, documented in retry_diary.py.
        self.assertEqual(body["citizens"], [])
        self.assertEqual(body["citizens_start"], [])

    def test_no_start_tick_raises(self):
        recs = self._recs()
        recs[1]["text"] = "Erushtathtat, 125-04-01 paused: True."
        recs[0] = {"kind": "run_start"}
        with self.assertRaises(ValueError):
            retry_diary.build_retry_body(recs)

    def test_no_snapshots_raises(self):
        with self.assertRaises(ValueError):
            retry_diary.build_retry_body(
                [{"kind": "run_start", "start_tick": 1}])


class TestParseModelReply(unittest.TestCase):
    """parse_model_reply is the single riskiest pure function in the
    repo (external review section 8, 2026-11-27): it had zero tests,
    and the C5 bug — a list kwargs reaching the query route
    extraction outside its try and killing the run — lived exactly
    in the data it fails to validate. Malformed-input table."""

    def test_valid_reply(self):
        reasoning, actions = m1_driver.parse_model_reply(
            '{"reasoning": "brew", "actions": [{"action": "query", '
            '"kwargs": {"route": "/v1/stocks"}, "reason": "check"}]}')
        self.assertEqual(reasoning, "brew")
        self.assertEqual(actions, [{"action": "query",
                                    "kwargs": {"route": "/v1/stocks"},
                                    "reason": "check"}])

    def test_fenced_block(self):
        text = ("```json\n{\"reasoning\": \"\", "
                "\"actions\": []}\n```")
        reasoning, actions = m1_driver.parse_model_reply(text)
        self.assertEqual((reasoning, actions), ("", []))

    def test_prose_wrapped_json(self):
        text = ('Here is my plan: {"reasoning": "dig", "actions": '
                '[{"action": "dig_to_completion", "kwargs": {}}]} '
                'Hope that helps.')
        reasoning, actions = m1_driver.parse_model_reply(text)
        self.assertEqual(reasoning, "dig")
        self.assertEqual(len(actions), 1)

    def test_non_dict_kwargs_raises(self):
        # C5: a list kwargs once sailed through to the query route
        # extraction and killed the run with AttributeError.
        text = '{"actions": [{"action": "query", '
        '"kwargs": ["/v1/stocks"]}]}'
        with self.assertRaises(ValueError):
            m1_driver.parse_model_reply(text)

    def test_non_string_action_raises(self):
        text = '{"actions": [{"action": ["query"], "kwargs": {}}]}'
        with self.assertRaises(ValueError):
            m1_driver.parse_model_reply(text)

    def test_non_list_actions_raises(self):
        with self.assertRaises(ValueError):
            m1_driver.parse_model_reply(
                '{"actions": {"action": "query"}}')

    def test_non_object_reply_raises(self):
        with self.assertRaises(ValueError):
            m1_driver.parse_model_reply('[{"action": "query"}]')

    def test_reply_not_json_raises(self):
        with self.assertRaises(ValueError):
            m1_driver.parse_model_reply("no json here at all")

    def test_malformed_action_skipped(self):
        # A non-dict action, or one without an "action" key, is
        # skipped — only a well-formed action with a bad TYPE
        # raises (a confused model is visible; a junk entry is not).
        text = ('{"actions": [42, {"nope": true}, '
                '{"action": "query", "kwargs": {}}]}')
        _reasoning, actions = m1_driver.parse_model_reply(text)
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["action"], "query")

    def test_missing_kwargs_defaults_to_empty_dict(self):
        _reasoning, actions = m1_driver.parse_model_reply(
            '{"actions": [{"action": "query"}]}')
        self.assertEqual(actions[0]["kwargs"], {})


class _ScriptDaemon(_StubDaemon):
    """_StubDaemon plus a scripted snapshot() sequence: each entry
    is a dict to return or an Exception to raise (the last entry
    repeats). pause_daemon_loop and run_task are stubbed."""

    def __init__(self, script, **kw):
        super().__init__(**kw)
        self._script = list(script)
        self._calls = 0
        self.tasks_run = []

    def snapshot(self):
        entry = self._script[min(self._calls, len(self._script) - 1)]
        self._calls += 1
        if isinstance(entry, Exception):
            raise entry
        return entry

    def pause_daemon_loop(self):
        return {"ok": True}

    def run_task(self, name):
        self.tasks_run.append(name)
        return {"ok": True, "reason": f"task {name} ok"}


def _good_snap(tick=100000, suggestion=None):
    """A snapshot the tick loop accepts: tick below end_tick, 7
    citizens alive, optional suggestion text."""
    snap = {"tick": tick, "date": "125-04-01", "text": "",
            "sections": {
                "status": "Population: 7 citizens (0 idle, "
                          "0 wounded), 25 animals, 0 hostiles",
                "stocks": "Stocks: drink 38, food 32, wood 124, "
                          "stone 0, brewable plants 1, empty "
                          "barrels 7, food stacks 7."}}
    if suggestion is not None:
        snap["suggestion"] = suggestion
    return snap


class _ScriptedModel:
    """A fake model: chat_full() returns the scripted replies in
    order, then repeats the last one. Records every messages list
    it was called with. Replies are plain text; chat_full wraps
    them in the response dict the driver logs (no usage, so the
    model_call records carry None tokens)."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat_full(self, messages):
        self.calls.append(messages)
        idx = min(len(self.calls) - 1, len(self.replies) - 1)
        return {"content": self.replies[idx], "model": "x",
                "usage": None, "temperature": 0.2}

    def chat(self, messages):
        return self.chat_full(messages)["content"]


class TestModelDecideRetry(unittest.TestCase):
    """In-tick retry of a malformed model reply (Mikey, 2026-11-27):
    a parse failure re-prompts the model in the SAME tick with the
    specific error instead of burning the turn. Bounded at
    MODEL_PARSE_RETRIES; only then does the tick end idle through
    the model-failure path. A parse that fails and then recovers
    still counts as a model failure for scoring, but not toward
    the consecutive-failure cap."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _driver(self, replies, daemon=None, max_ticks=2):
        drv = m1_driver.M1Driver.__new__(m1_driver.M1Driver)
        drv.args = SimpleNamespace(mock=False, days=1, window=150,
                                   max_ticks=max_ticks, model="x",
                                   out=str(Path(self._tmp.name)
                                           / "log.jsonl"))
        drv.out = Path(drv.args.out)
        drv.daemon = daemon if daemon is not None else _StubDaemon()
        drv.model = _ScriptedModel(replies)
        drv._catalog = lambda: "{}"
        drv.tick_no = 0
        drv.stall_ticks = 0
        drv.consecutive_model_failures = 0
        drv.consecutive_snapshot_failures = 0
        drv.query_results = []
        drv.last_action_results = []
        drv.actions_taken = 0
        drv.idle_ticks = 0
        drv.diary_decisions = []
        drv.snap0 = None
        drv.citizens_start_fresh = None
        return drv

    def _run(self, drv):
        # run() clears snapshot baselines via the real Store and
        # sleeps 5 s per snapshot failure — both stubbed out.
        store = mock.Mock()
        store.return_value.clear_snapshots.return_value = 0
        with mock.patch("dfagent_harness.store.Store", store), \
                mock.patch("dfagent_harness.store."
                           "default_world_db_path",
                           return_value="/tmp/nope.db"), \
                mock.patch.object(m1_driver.time, "sleep"):
            return drv.run()

    def _log_records(self, drv):
        out = Path(drv.args.out)
        if not out.exists():
            return []
        return [json.loads(line)
                for line in out.read_text().splitlines() if line]

    def test_retry_recovers_and_counts_as_model_failure(self):
        # Malformed first reply, valid second: the decision comes
        # back, the re-prompt carries the parse error and the bad
        # reply, and the recovery is logged as a model failure
        # (recovered=True) for scoring.
        drv = self._driver([
            "not json at all",
            '{"reasoning": "ok", "actions": '
            '[{"action": "task:brew", "kwargs": {}}]}'])
        reasoning, actions = drv._model_decide(_good_snap())
        self.assertEqual(reasoning, "ok")
        self.assertEqual(actions, [{"action": "task:brew",
                                    "kwargs": {}, "reason": ""}])
        self.assertEqual(len(drv.model.calls), 2)
        retry = drv.model.calls[1]
        self.assertEqual(retry[-2]["role"], "assistant")
        self.assertEqual(retry[-2]["content"], "not json at all")
        self.assertIn("could not be parsed", retry[-1]["content"])
        self.assertIn("JSON object", retry[-1]["content"])
        recs = self._log_records(drv)
        self.assertEqual(
            [r for r in recs if r["kind"] == "model_retry"][0]
            ["attempt"], 1)
        recovered = [r for r in recs
                     if r["kind"] == "model_failure"
                     and r.get("recovered") is True]
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["attempts"], 1)

    def test_retry_exhausts_after_two_reprompts(self):
        # Three bad replies in a row: 1 + MODEL_PARSE_RETRIES
        # model calls, one model_retry per attempt, then the
        # ValueError escapes — run() ends the tick through the
        # model-failure path, which logs the failure itself.
        drv = self._driver(["garbage"] * 3)
        with self.assertRaises(ValueError):
            drv._model_decide(_good_snap())
        self.assertEqual(len(drv.model.calls), 3)
        recs = self._log_records(drv)
        self.assertEqual(
            len([r for r in recs if r["kind"] == "model_retry"]), 3)
        self.assertEqual(
            [r["attempt"] for r in recs
             if r["kind"] == "model_retry"], [1, 2, 3])
        self.assertFalse([r for r in recs
                          if r["kind"] == "model_failure"])

    def test_recovered_parse_does_not_burn_the_turn(self):
        # Run-loop level: a tick whose first reply is malformed
        # still runs the task (the turn is not burned), and the
        # consecutive-failure counter stays at zero.
        daemon = _ScriptDaemon(
            [_good_snap()],
            fresh=[_fresh_citizen(i, f"D{i}") for i in range(7)])
        drv = self._driver([
            "not json at all",
            '{"reasoning": "ok", "actions": '
            '[{"action": "task:brew", "kwargs": {}}]}'],
            daemon=daemon, max_ticks=2)
        drv._advance_clock = lambda target, current: target
        self.assertEqual(self._run(drv), 0)
        self.assertEqual(daemon.tasks_run, ["brew", "brew"])
        self.assertEqual(drv.consecutive_model_failures, 0)
        recs = self._log_records(drv)
        self.assertIn("model_retry", [r["kind"] for r in recs])
        # The recovered failure is logged by _model_decide itself,
        # marked recovered — and the tick loop logged no failure of
        # its own, because the tick succeeded.
        recovered = [r for r in recs
                     if r["kind"] == "model_failure"
                     and r.get("recovered") is True]
        self.assertEqual(len(recovered), 1)
        self.assertFalse([r for r in recs
                          if r["kind"] == "model_failure"
                          and not r.get("recovered")])


class TestTickLoopFailureAccounting(unittest.TestCase):
    """The M1 tick loop's failure accounting (external review
    section 8, 2026-11-27): the snapshot-retry cap (H1), the
    five-failure model cap, and the stall fallback. These were
    validated only by live runs; the loop is driven here with a
    scripted daemon. The Store clear inside run() is stubbed so
    the test never touches the real world.db."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _driver(self, daemon, max_ticks=100):
        drv = m1_driver.M1Driver.__new__(m1_driver.M1Driver)
        drv.args = SimpleNamespace(mock=True, days=1, window=150,
                                   max_ticks=max_ticks, model="x",
                                   out=str(Path(self._tmp.name)
                                           / "log.jsonl"))
        drv.out = Path(drv.args.out)
        drv.daemon = daemon
        drv.tick_no = 0
        drv.stall_ticks = 0
        drv.consecutive_model_failures = 0
        drv.consecutive_snapshot_failures = 0
        drv.query_results = []
        drv.last_action_results = []
        drv.actions_taken = 0
        drv.idle_ticks = 0
        drv.diary_decisions = []
        drv.snap0 = None
        drv.citizens_start_fresh = None
        return drv

    def _run(self, drv):
        # run() clears snapshot baselines via the real Store and
        # sleeps 5 s per snapshot failure — both stubbed out.
        store = mock.Mock()
        store.return_value.clear_snapshots.return_value = 0
        with mock.patch("dfagent_harness.store.Store", store), \
                mock.patch("dfagent_harness.store."
                           "default_world_db_path",
                           return_value="/tmp/nope.db"), \
                mock.patch.object(m1_driver.time, "sleep"):
            return drv.run()

    def _log_kinds(self, drv):
        out = Path(drv.args.out)
        if not out.exists():
            return []
        return [json.loads(line)["kind"]
                for line in out.read_text().splitlines() if line]

    def test_snapshot_cap_ends_run_after_five(self):
        # H1: DF dead + daemon up = every snapshot fails. The old
        # code retried forever; five consecutive failures end the
        # run non-zero, mirroring the model-failure rule.
        daemon = _ScriptDaemon(
            [_good_snap()] + [RuntimeError("daemon down")] * 10,
            fresh=[_fresh_citizen(i, f"D{i}") for i in range(7)])
        drv = self._driver(daemon)
        self.assertEqual(self._run(drv), 2)
        kinds = self._log_kinds(drv)
        self.assertIn("run_end", kinds)
        out = Path(drv.args.out).read_text()
        self.assertIn("snapshot failed 5 ticks in a row", out)

    def test_snapshot_failures_reset_on_success(self):
        # Four failures, one good tick, four more failures: the
        # counter resets on success, so the run does NOT end — it
        # runs to max_ticks instead.
        daemon = _ScriptDaemon(
            [_good_snap(),
             RuntimeError("down"), RuntimeError("down"),
             RuntimeError("down"), RuntimeError("down"),
             _good_snap(),
             RuntimeError("down"), RuntimeError("down"),
             RuntimeError("down"), RuntimeError("down"),
             _good_snap()],
            fresh=[_fresh_citizen(i, f"D{i}") for i in range(7)])
        drv = self._driver(daemon, max_ticks=10)
        drv._model_decide = lambda snap: ("mock", [])
        drv._advance_clock = lambda target, current: target
        self.assertEqual(self._run(drv), 0)

    def test_model_failure_cap_ends_run_after_five(self):
        # Five consecutive model failures end the run (exit 2),
        # mirroring the snapshot cap.
        daemon = _ScriptDaemon(
            [_good_snap()],
            fresh=[_fresh_citizen(i, f"D{i}") for i in range(7)])
        drv = self._driver(daemon, max_ticks=100)
        drv._model_decide = mock.Mock(
            side_effect=RuntimeError("model down"))
        drv._advance_clock = lambda target, current: target
        self.assertEqual(self._run(drv), 2)
        out = Path(drv.args.out).read_text()
        self.assertIn("model failed 5 ticks in a row", out)

    def test_stall_fallback_runs_suggestion(self):
        # Six idle ticks with no model actions: the fallback runs
        # the snapshot's suggestion (task:brew) via the daemon.
        daemon = _ScriptDaemon(
            [_good_snap(
                suggestion="Suggested action: run the brew task")],
            fresh=[_fresh_citizen(i, f"D{i}") for i in range(7)])
        drv = self._driver(daemon, max_ticks=7)
        drv._model_decide = lambda snap: ("mock", [])
        drv._advance_clock = lambda target, current: target
        self.assertEqual(self._run(drv), 0)
        self.assertEqual(daemon.tasks_run, ["brew"])


if __name__ == "__main__":
    unittest.main()
