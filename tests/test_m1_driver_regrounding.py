"""Offline tests for run-start re-grounding (R3-P0-3).

The driver pulls the previous run's open problems and recent
failures from the journal/store at run start and puts them in the
tick-1 prompt, so a run does not start amnesiac. The renderer is a
pure function on server/store data (untrusted shapes — every input
is validated defensively), and the fetch is best-effort. Tested here
by loading scripts/m1_driver.py directly, the same pattern as
test_m1_driver_helpers.py.
"""

import importlib.util
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


def _summary(**over):
    base = {
        "deaths": [],
        "trends": {},
        "recent_decisions": [],
        "recent_events": [],
        "failures": [],
    }
    base.update(over)
    return base


class TestRenderRegrounding(unittest.TestCase):
    def test_full_input_names_everything(self):
        text = m1_driver.render_regrounding(
            _summary(
                failures=[{"decision": "brew at the Still",
                           "action": "task:brew",
                           "result": "no still workshop exists"}],
                deaths=[{"name": "Olon Medtobalod",
                         "cause": "died of thirst"}],
                trends={"drink": {"latest": 9, "days_remaining": 1}}),
            [{"name": "Keep drink above 40",
              "expression": "drink >= 40", "task": "brew",
              "done": 0}],
            [{"kind": "wounded", "subject": "Lòr Mebzuthkin",
              "detail": "2 wounds", "since": "125-06-02",
              "first_sighting": True}])
        self.assertIn("Keep drink above 40", text)
        self.assertIn("brew at the Still", text)
        self.assertIn("no still workshop exists", text)
        self.assertIn("Olon Medtobalod", text)
        self.assertIn("died of thirst", text)
        self.assertIn("drink", text)
        self.assertIn("Lòr Mebzuthkin", text)
        self.assertIn("2 wounds", text)
        self.assertIn("125-06-02", text)
        self.assertIn("WHERE THE LAST RUN LEFT OFF", text)

    def test_done_goals_are_not_open_problems(self):
        text = m1_driver.render_regrounding(
            _summary(), [{"name": "Finished goal", "done": 1}], [])
        self.assertNotIn("Finished goal", text)
        self.assertIn("Nothing open", text)

    def test_empty_input_renders_the_clean_line(self):
        text = m1_driver.render_regrounding(_summary(), [], [])
        self.assertIn("Nothing open", text)
        self.assertIn("no unfinished goals", text)

    def test_malformed_inputs_never_raise(self):
        # Server/store data is untrusted shape: wrong types render
        # as "nothing there", never raise. The malformed-input rule
        # applies to every function parsing outside input.
        cases = [
            (None, None, None),
            ("junk", "junk", "junk"),
            (_summary(failures="not a list",
                      deaths=[None, "junk", {"name": 5}],
                      trends={"drink": "not a dict"}),
             [{"name": 7, "done": "maybe"}],
             [{"kind": 5}, "junk", None,
              {"subject": ["not", "a", "string"]}]),
            (_summary(failures=[{"decision": ["a", "list"]}]),
             [], []),
        ]
        for summary, goals, threads in cases:
            with self.subTest(summary=summary):
                text = m1_driver.render_regrounding(
                    summary, goals, threads)
                self.assertIsInstance(text, str)
                self.assertIn("WHERE THE LAST RUN LEFT OFF", text)

    def test_groups_are_capped_at_five(self):
        failures = [{"decision": f"failure {i}", "result": "x"}
                    for i in range(7)]
        text = m1_driver.render_regrounding(
            _summary(failures=failures), [], [])
        self.assertIn("failure 4", text)
        self.assertNotIn("failure 5", text)
        self.assertIn("and 2 more", text)

    def test_only_urgent_trends_are_listed(self):
        text = m1_driver.render_regrounding(
            _summary(trends={
                "drink": {"latest": 9, "days_remaining": 1},
                "food": {"latest": 50, "days_remaining": 9},
                "wood": {"latest": 117, "days_remaining": None}}),
            [], [])
        self.assertIn("drink", text)
        self.assertNotIn("food", text)
        self.assertNotIn("wood", text)

    def test_thread_without_since_renders_without_a_date(self):
        text = m1_driver.render_regrounding(
            _summary(), [],
            [{"kind": "unmet_need", "subject": "Ral Dalzatolin",
              "detail": "going without drink", "since": None}])
        self.assertIn("Ral Dalzatolin", text)
        self.assertIn("going without drink", text)
        self.assertNotIn("since", text.lower().replace(
            "re-grounding", ""))


class TestPromptRegrounding(unittest.TestCase):
    def _driver(self, tmp):
        args = SimpleNamespace(mock=True, model="x",
                               out=str(Path(tmp) / "m1.jsonl"))
        with mock.patch.object(m1_driver, "DaemonClient") as cls:
            daemon = mock.Mock()
            daemon.catalog.return_value = {"actions": []}
            cls.return_value = daemon
            driver = m1_driver.M1Driver(args)
        driver.daemon = daemon
        return driver

    def test_section_only_on_tick_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = self._driver(tmp)
            driver.regrounding_text = ("--- WHERE THE LAST RUN "
                                       "LEFT OFF (re-grounding) ---"
                                       "\n- brew failed")
            snap = {"text": "OBS", "tick": 1}
            driver.tick_no = 1
            prompt = driver._prompt(snap)
            user = prompt[1]["content"]
            self.assertIn("WHERE THE LAST RUN LEFT OFF", user)
            driver.tick_no = 2
            prompt = driver._prompt(snap)
            self.assertNotIn("WHERE THE LAST RUN LEFT OFF",
                             prompt[1]["content"])

    def test_no_section_when_no_regrounding(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = self._driver(tmp)
            driver.tick_no = 1
            prompt = driver._prompt({"text": "OBS", "tick": 1})
            self.assertNotIn("WHERE THE LAST RUN LEFT OFF",
                             prompt[1]["content"])


class TestRegroundFetch(unittest.TestCase):
    def _driver(self, tmp):
        args = SimpleNamespace(mock=True, model="x",
                               out=str(Path(tmp) / "m1.jsonl"))
        with mock.patch.object(m1_driver, "DaemonClient") as cls:
            daemon = mock.Mock()
            cls.return_value = daemon
            driver = m1_driver.M1Driver(args)
        driver.daemon = daemon
        driver.snap0 = {"date": "125-04-12"}
        driver.start_tick = 120000
        return driver

    def test_reground_pulls_all_three_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = self._driver(tmp)
            driver.daemon.memory_summary.return_value = _summary(
                failures=[{"decision": "brew failed",
                           "result": "no still"}])
            driver.daemon.goals_list.return_value = {"goals": [
                {"name": "Keep drink up", "expression": "drink>=40",
                 "task": "brew", "done": 0}]}
            fake_threads = [{"kind": "wounded",
                             "subject": "Lòr Mebzuthkin",
                             "detail": "1 wound",
                             "since": "125-06-02",
                             "first_sighting": True}]
            with mock.patch(
                    "dfagent_harness.diary.open_threads",
                    return_value=fake_threads), \
                mock.patch(
                    "dfagent_harness.store.Store"), \
                mock.patch(
                    "dfagent_harness.store.default_world_db_path",
                    return_value=Path(tmp) / "world.db"):
                driver._reground()
            text = driver.regrounding_text or ""
            self.assertIn("brew failed", text)
            self.assertIn("Keep drink up", text)
            self.assertIn("Lòr Mebzuthkin", text)
            # The rendered text is logged whole (the auditable
            # proof the first tick named the open problems).
            log = (Path(tmp) / "m1.jsonl").read_text()
            self.assertIn('"kind": "regrounding"', log)
            self.assertIn("brew failed", log)

    def test_failed_fetches_leave_a_clean_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = self._driver(tmp)
            driver.daemon.memory_summary.side_effect = RuntimeError(
                "daemon down")
            driver.daemon.goals_list.side_effect = RuntimeError(
                "daemon down")
            with mock.patch(
                    "dfagent_harness.diary.open_threads",
                    side_effect=RuntimeError("no store")), \
                mock.patch(
                    "dfagent_harness.store.Store"), \
                mock.patch(
                    "dfagent_harness.store.default_world_db_path",
                    return_value=Path(tmp) / "world.db"):
                driver._reground()
            self.assertIn("Nothing open",
                          driver.regrounding_text or "")


if __name__ == "__main__":
    unittest.main()
