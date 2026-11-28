"""Offline tests for the driver emission spec (EVALUATION.md).

The driver must emit, per run log: a ``model_call`` record per
model call attempt (tokens, latency, model, temperature); a
``run_start`` with the harness commit and protocol version; a
``--noop`` mode that never acts; and a ``--guidance-off`` flag
for the Phase 6 ablation (HARNESS_ROLE.md §8.1 groups A-D).
Tested by loading scripts/m1_driver.py directly, the same
pattern as test_m1_driver_helpers.py. No game, no network.
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

_SECTIONS = {
    "header": "HEADER", "attention": "ATTENTION",
    "suggestion": "SUGGESTION", "goals": "GOALS",
    "status": "STATUS", "stocks": "STOCKS",
    "placement": "PLACEMENT", "events": "EVENTS"}


def _snap():
    return {"text": "FULL TEXT", "tick": 100000,
            "sections": dict(_SECTIONS),
            "suggestion": "brew at the Still"}


class _FakeModel:
    """A model client returning canned chat_full results."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def chat_full(self, messages):
        self.calls += 1
        return self.replies.pop(0)


def _valid_reply():
    return {"content": json.dumps(
        {"reasoning": "brew", "actions": []}),
        "model": "deepseek-v4.1-flash-1017",
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        "temperature": 0.2}


class TestGuidanceGroups(unittest.TestCase):
    def test_strip_sets(self):
        self.assertEqual(
            m1_driver.guidance_stripped_sections("a"), {"suggestion"})
        self.assertEqual(
            m1_driver.guidance_stripped_sections("b"), frozenset())
        self.assertEqual(
            m1_driver.guidance_stripped_sections("c"), frozenset())
        self.assertEqual(
            m1_driver.guidance_stripped_sections("d"),
            {"suggestion", "attention", "goals", "placement"})
        self.assertEqual(
            m1_driver.guidance_stripped_sections(None), frozenset())
        self.assertEqual(
            m1_driver.guidance_stripped_sections("zzz"), frozenset())
        self.assertEqual(
            m1_driver.guidance_stripped_sections(123), frozenset())

    def test_system_prompt_variants(self):
        std = m1_driver.system_prompt_for(None)
        self.assertIn("know NOTHING", std)
        know = m1_driver.system_prompt_for("c")
        self.assertIn("may use your own knowledge", know)
        self.assertNotIn("know NOTHING", know)
        self.assertEqual(m1_driver.system_prompt_for("d"), know)
        self.assertEqual(m1_driver.system_prompt_for("a"), std)
        self.assertEqual(m1_driver.system_prompt_for("b"), std)
        # The knowledge variant is the standard prompt with only
        # the opening paragraph changed: the rest is identical.
        self.assertIn("HOW THIS WORKS", know)
        self.assertIn("PRIORITIES (in order)", know)

    def test_observation_text_strips(self):
        snap = _snap()
        a = m1_driver.observation_text(
            snap, m1_driver.guidance_stripped_sections("a"))
        self.assertNotIn("SUGGESTION", a)
        self.assertIn("ATTENTION", a)
        self.assertIn("GOALS", a)
        d = m1_driver.observation_text(
            snap, m1_driver.guidance_stripped_sections("d"))
        self.assertNotIn("SUGGESTION", d)
        self.assertNotIn("ATTENTION", d)
        self.assertNotIn("GOALS", d)
        self.assertNotIn("PLACEMENT", d)
        self.assertIn("STATUS", d)
        self.assertIn("EVENTS", d)

    def test_observation_text_fallback_and_malformed(self):
        self.assertEqual(
            m1_driver.observation_text({"text": "FULL"}), "FULL")
        self.assertEqual(m1_driver.observation_text(None), "")
        self.assertEqual(
            m1_driver.observation_text(
                {"sections": "not-a-dict", "text": "T"}), "T")
        self.assertEqual(
            m1_driver.observation_text({"sections": {}}), "")
        self.assertEqual(
            m1_driver.observation_text({"sections": {"x": ""}}), "")


def _driver(tmp, **over):
    args = SimpleNamespace(mock=True, model="x",
                           out=str(Path(tmp) / "m1.jsonl"),
                           days=1.0, window=150, max_ticks=0,
                           noop=False, guidance_off=None)
    args.__dict__.update(over)
    with mock.patch.object(m1_driver, "DaemonClient") as cls:
        daemon = mock.Mock()
        daemon.catalog.return_value = {"actions": []}
        cls.return_value = daemon
        driver = m1_driver.M1Driver(args)
    driver.daemon = daemon
    driver.catalog_text = '{"actions": []}'
    return driver


def _log_records(tmp):
    path = Path(tmp) / "m1.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()
            if line.strip()]


class TestPromptGuidanceOff(unittest.TestCase):
    def test_group_a_strips_suggestion_keeps_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = _driver(tmp, guidance_off="a")
            driver.tick_no = 1
            driver.regrounding_text = "REGROUND"
            user = driver._prompt(_snap())[1]["content"]
            self.assertNotIn("SUGGESTION", user)
            self.assertIn("ATTENTION", user)
            self.assertIn("REGROUND", user)
            self.assertIn("know NOTHING",
                          driver._prompt(_snap())[0]["content"])

    def test_group_d_strips_all_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = _driver(tmp, guidance_off="d")
            driver.tick_no = 1
            driver.regrounding_text = "REGROUND"
            driver.query_results = ["q -> r"]
            driver.last_action_results = ["brew -> OK"]
            driver.stall_ticks = 5
            prompt = driver._prompt(_snap())
            user = prompt[1]["content"]
            self.assertNotIn("SUGGESTION", user)
            self.assertNotIn("ATTENTION", user)
            self.assertNotIn("GOALS", user)
            self.assertNotIn("PLACEMENT", user)
            self.assertNotIn("REGROUND", user)
            self.assertNotIn("QUERY RESULTS", user)
            self.assertNotIn("LAST TURN'S ACTION OUTCOMES", user)
            self.assertNotIn("ESCALATION", user)
            self.assertIn("STATUS", user)
            self.assertIn("may use your own knowledge",
                          prompt[0]["content"])

    def test_group_c_only_changes_system_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = _driver(tmp, guidance_off="c")
            driver.tick_no = 1
            prompt = driver._prompt(_snap())
            user = prompt[1]["content"]
            self.assertIn("SUGGESTION", user)
            self.assertIn("ATTENTION", user)
            self.assertIn("may use your own knowledge",
                          prompt[0]["content"])

    def test_guidance_on_keeps_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = _driver(tmp)
            driver.tick_no = 1
            driver.regrounding_text = "REGROUND"
            driver.stall_ticks = 5
            prompt = driver._prompt(_snap())
            user = prompt[1]["content"]
            self.assertIn("SUGGESTION", user)
            self.assertIn("ATTENTION", user)
            self.assertIn("REGROUND", user)
            self.assertIn("ESCALATION", user)
            self.assertIn("know NOTHING", prompt[0]["content"])


class TestModelCallRecord(unittest.TestCase):
    def test_one_call_logs_tokens_latency_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = _driver(tmp)
            driver.args.mock = False
            driver.model = _FakeModel([_valid_reply()])
            driver.tick_no = 1
            reasoning, actions = driver._model_decide(_snap())
            self.assertEqual(reasoning, "brew")
            self.assertEqual(actions, [])
            recs = [r for r in _log_records(tmp)
                    if r.get("kind") == "model_call"]
            self.assertEqual(len(recs), 1)
            rec = recs[0]
            self.assertEqual(rec["prompt_tokens"], 100)
            self.assertEqual(rec["completion_tokens"], 20)
            self.assertEqual(rec["model"], "deepseek-v4.1-flash-1017")
            self.assertEqual(rec["temperature"], 0.2)
            self.assertIsInstance(rec["latency_s"], float)
            self.assertGreaterEqual(rec["latency_s"], 0.0)

    def test_parse_retry_logs_a_record_per_attempt(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = _driver(tmp)
            driver.args.mock = False
            bad = dict(_valid_reply())
            bad["content"] = "not json at all"
            driver.model = _FakeModel([bad, _valid_reply()])
            driver.tick_no = 1
            reasoning, actions = driver._model_decide(_snap())
            self.assertEqual(reasoning, "brew")
            recs = [r for r in _log_records(tmp)
                    if r.get("kind") == "model_call"]
            self.assertEqual(len(recs), 2)
            self.assertEqual(driver.model.calls, 2)

    def test_missing_usage_logs_none_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = _driver(tmp)
            driver.args.mock = False
            reply = dict(_valid_reply())
            reply["usage"] = None
            driver.model = _FakeModel([reply])
            driver.tick_no = 1
            driver._model_decide(_snap())
            recs = [r for r in _log_records(tmp)
                    if r.get("kind") == "model_call"]
            self.assertEqual(len(recs), 1)
            self.assertIsNone(recs[0]["prompt_tokens"])
            self.assertIsNone(recs[0]["completion_tokens"])

    def test_malformed_usage_logs_none_tokens(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = _driver(tmp)
            driver.args.mock = False
            reply = dict(_valid_reply())
            reply["usage"] = {"prompt_tokens": "not-an-int"}
            driver.model = _FakeModel([reply])
            driver.tick_no = 1
            driver._model_decide(_snap())
            recs = [r for r in _log_records(tmp)
                    if r.get("kind") == "model_call"]
            self.assertIsNone(recs[0]["prompt_tokens"])
            self.assertIsNone(recs[0]["completion_tokens"])

    def test_mock_guidance_off_has_nothing_to_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = _driver(tmp, guidance_off="a")
            driver.tick_no = 1
            reasoning, actions = driver._model_decide(_snap())
            self.assertEqual(actions, [])
            self.assertIn("guidance off", reasoning)


class TestRunStartAndNoop(unittest.TestCase):
    def _run_driver(self, tmp, **over):
        driver = _driver(tmp, **over)
        daemon = driver.daemon
        daemon.get.return_value = {"paused": True}
        daemon.stocks_fresh.return_value = {"drink_units": 50}
        daemon.units_citizens.return_value = [
            {"id": i, "name": f"Dwarf {i}"} for i in range(7)]
        daemon.daemon_control.return_value = {"loop_paused": True}
        daemon.wealth.return_value = {"fortress_value": 1000,
                                      "created_value": 100,
                                      "item_count": 10}
        daemon.post.return_value = {"advanced": 150,
                                    "tick_after": 100150,
                                    "unpaused_s": 1.0}
        return driver

    def _snapshots(self, ticks):
        return [{"text": "OBS", "tick": t, "date": "125-04-01",
                 "sections": {"status": "7 citizens",
                              "stocks": "drink 50"}}
                for t in ticks]

    def test_noop_run_logs_run_start_and_never_acts(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = self._run_driver(tmp, noop=True)
            driver.daemon.snapshot.side_effect = self._snapshots(
                [100000, 100150, 101200])
            with mock.patch(
                    "dfagent_harness.store.Store") as store_cls, \
                mock.patch(
                    "dfagent_harness.store.default_world_db_path",
                    return_value="/tmp/world.db"):
                store_cls.return_value.clear_snapshots.return_value = 0
                rc = driver.run()
            self.assertEqual(rc, 0)
            recs = _log_records(tmp)
            starts = [r for r in recs if r.get("kind") == "run_start"]
            self.assertEqual(len(starts), 1)
            start = starts[0]
            self.assertTrue(start["noop"])
            self.assertIsNone(start["guidance_off"])
            self.assertEqual(start["protocol_version"], 1)
            commit = start["harness_commit"]
            self.assertTrue(commit is None or (
                isinstance(commit, str) and len(commit) == 40
                and all(c in "0123456789abcdef" for c in commit)))
            # No model call, no action, no diary write; the run
            # did log noop ticks and ended day-complete.
            self.assertFalse(any(r.get("kind") == "model_call"
                                 for r in recs))
            self.assertFalse(any(r.get("kind") == "action"
                                 for r in recs))
            self.assertTrue(any(r.get("kind") == "noop_tick"
                                for r in recs))
            self.assertTrue(any(r.get("kind") == "run_end"
                                and r.get("reason") == "day complete"
                                for r in recs))
            diary = [r for r in recs if r.get("kind") == "diary"]
            self.assertTrue(any(r.get("skipped") == "noop run"
                                for r in diary))
            # The model was never consulted.
            self.assertEqual(driver.model, None)

    def test_mock_run_start_carries_commit_and_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            driver = self._run_driver(tmp)
            driver.daemon.snapshot.side_effect = self._snapshots(
                [100000, 101200])
            with mock.patch(
                    "dfagent_harness.store.Store") as store_cls, \
                mock.patch(
                    "dfagent_harness.store.default_world_db_path",
                    return_value="/tmp/world.db"):
                store_cls.return_value.clear_snapshots.return_value = 0
                rc = driver.run()
            self.assertEqual(rc, 0)
            recs = _log_records(tmp)
            starts = [r for r in recs if r.get("kind") == "run_start"]
            self.assertEqual(len(starts), 1)
            self.assertFalse(starts[0]["noop"])
            self.assertIsNone(starts[0]["guidance_off"])
            self.assertEqual(starts[0]["protocol_version"], 1)
            self.assertTrue(starts[0]["mock"])


if __name__ == "__main__":
    unittest.main()
