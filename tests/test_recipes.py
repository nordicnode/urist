"""Offline tests for the multi-step recipe framework (R3-P0-4).

A task whose TASK_DEFS spec carries "steps" runs them in order —
each step a sub-task, a raw action, or a state check — each step
verified, and a failed step stops the recipe with a diagnosis
naming the step. The legacy single-action form is unchanged. No
game: the daemon runs against a mock client with the same stubbing
pattern as test_tasks.py (patched paused_read / observe.collect /
act / _wait_for_paused), and the fake game answers reads from
scripted sequences.
"""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness import actions, daemon as daemon_mod  # noqa: E402


def _state(workshops=("Carpenters", "Still"), drink_plants=5,
           empty_barrels=3):
    buildings = [{"id": 7 + i, "type": "Workshop", "subtype": w}
                 for i, w in enumerate(workshops)]
    return {
        "status": {"year_tick": 100000, "population": 7},
        "buildings": {"list": buildings},
        "stocks": {
            "by_material": [{"type": "PLANT", "brewable": True,
                             "units": drink_plants}],
            "empty_barrels": empty_barrels, "barrels": 5,
            "drink_units": 97, "food_units": 23, "wood_units": 117,
            "stone_units": 0},
        "jobs": {"list": []},
        "units": {"citizens": [{"id": 5409, "pos": [97, 97, 175]}]},
    }


class _FakeGame:
    """Scripted reads for one run_task call. ``jobs_seq`` is the
    per-read job list for sections=("jobs",) (the job-completion
    wait); ``reports_seq`` the per-read report list for
    sections=("reports",) (the cancellation check). Anything else
    returns the full state."""

    def __init__(self, state, jobs_seq=None, reports_seq=None):
        self.state = state
        self.jobs_seq = list(jobs_seq) if jobs_seq is not None \
            else [[]]
        self.reports_seq = list(reports_seq) \
            if reports_seq is not None else [[]]
        self.jobs_reads = 0
        self.reports_reads = 0

    def collect(self, client, sections=None):
        if sections == ("jobs",):
            idx = min(self.jobs_reads, len(self.jobs_seq) - 1)
            self.jobs_reads += 1
            return {"jobs": {"list": self.jobs_seq[idx]}}
        if sections == ("reports",):
            idx = min(self.reports_reads, len(self.reports_seq) - 1)
            self.reports_reads += 1
            return {"reports": {"reports": self.reports_seq[idx]}}
        return self.state


class _RecipeCase(unittest.TestCase):
    def _daemon(self, tmp):
        daemon = daemon_mod.Daemon(state_dir=Path(tmp))
        daemon.client = mock.Mock()
        return daemon

    def _run(self, daemon, game, name, **kwargs):
        """Run run_task with the game stubbed. Returns (result,
        act_calls). act() answers queue_job with incrementing job
        ids and every other action ok."""
        calls = {"act": [], "job_id": [100]}

        def fake_act(client, action_name, **kw):
            # Mirror the real act(): an unknown action name raises
            # ValueError (a caller bug), so the framework's handling
            # of it is exercised, not bypassed by the stub.
            if action_name not in actions.ACTIONS:
                raise ValueError(
                    f"unknown action {action_name!r}")
            calls["act"].append((action_name, kw))
            calls["job_id"][0] += 1
            return actions.ActionResult(
                ok=True, action=action_name, before={}, after={},
                reason=f"{action_name} done",
                detail={"job_ids": [calls["job_id"][0]]})

        def fake_paused_read(client, fn):
            return fn()

        def fake_wait(client, fn, timeout):
            return fn()

        with mock.patch.object(daemon_mod.observe, "collect",
                               side_effect=game.collect), \
            mock.patch.object(daemon_mod, "act",
                              side_effect=fake_act), \
            mock.patch("dfagent_harness.read_safety.paused_read",
                       side_effect=fake_paused_read), \
            mock.patch.object(actions, "_wait_for_paused",
                              side_effect=fake_wait):
            return daemon.run_task(name, **kwargs), calls


class TestRecipeDefs(_RecipeCase):
    def test_every_task_still_names_its_keys(self):
        for name, spec in daemon_mod.TASK_DEFS.items():
            self.assertIn("need", spec, name)
            self.assertIn("wait_job", spec, name)
            self.assertIn("action", spec, name)

    def test_stock_drink_is_a_two_step_recipe(self):
        spec = daemon_mod.TASK_DEFS["stock_drink"]
        self.assertEqual(spec["action"], "recipe")
        self.assertEqual(spec["steps"], [{"task": "make_barrel"},
                                         {"task": "brew"}])

    def test_every_step_names_exactly_one_kind(self):
        known_tasks = set(daemon_mod.TASK_DEFS)
        known_predicates = {"workshop_exists", "building_exists",
                            "stock_at_least"}
        for name, spec in daemon_mod.TASK_DEFS.items():
            steps = spec.get("steps")
            if not steps:
                continue
            for step in steps:
                kinds = [k for k in ("task", "action", "verify")
                         if step.get(k) is not None]
                self.assertEqual(len(kinds), 1, (name, step))
                if "task" in step:
                    self.assertIn(step["task"], known_tasks,
                                  (name, step))
                if "verify" in step:
                    self.assertIn(step["verify"], known_predicates,
                                  (name, step))


class TestStockDrinkOffline(_RecipeCase):
    def test_recipe_runs_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            daemon = self._daemon(tmp)
            game = _FakeGame(_state())
            res, calls = self._run(daemon, game, "stock_drink")
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["action"], "task:stock_drink")
            steps = res["evidence"]["steps"]
            self.assertEqual(len(steps), 2)
            self.assertTrue(all(s["ok"] for s in steps), steps)
            self.assertEqual([s["label"] for s in steps],
                             ["task:make_barrel", "task:brew"])
            self.assertEqual(
                [c[0] for c in calls["act"]],
                ["queue_job", "queue_job"])
            self.assertEqual(
                [c[1]["job"] for c in calls["act"]],
                ["make_barrel", "brew"])

    def test_failed_first_step_stops_the_recipe(self):
        # No carpenter: make_barrel fails on its prerequisite, and
        # the brew step never runs — no queue_job for it at all.
        with tempfile.TemporaryDirectory() as tmp:
            daemon = self._daemon(tmp)
            game = _FakeGame(_state(workshops=("Still",)))
            res, calls = self._run(daemon, game, "stock_drink")
            self.assertFalse(res["ok"], res)
            self.assertIn("step 1/2", res["reason"])
            self.assertIn("task:make_barrel", res["reason"])
            self.assertIn("no carpenter workshop exists",
                          res["reason"])
            self.assertEqual(res["evidence"]["failed_step"], 1)
            self.assertEqual(calls["act"], [])

    def test_cancelled_second_step_fails_naming_it(self):
        # The barrel is made, but the brew job is cancelled: the
        # recipe fails at step 2, not as a success.
        with tempfile.TemporaryDirectory() as tmp:
            daemon = self._daemon(tmp)
            game = _FakeGame(
                _state(),
                reports_seq=[
                    [],
                    [{"text": "Olon cancels Brew Drink: "
                              "No empty barrel",
                      "time": 100001}]])
            res, calls = self._run(daemon, game, "stock_drink")
            self.assertFalse(res["ok"], res)
            self.assertIn("step 2/2", res["reason"])
            self.assertIn("task:brew", res["reason"])
            self.assertIn("cancelled", res["reason"])
            self.assertEqual(res["evidence"]["failed_step"], 2)

    def test_job_that_never_finishes_fails_the_step(self):
        # The barrel job stays in the list: the wait times out and
        # step 1 fails naming the wait, step 2 never runs.
        with tempfile.TemporaryDirectory() as tmp:
            daemon = self._daemon(tmp)
            game = _FakeGame(
                _state(),
                jobs_seq=[[{"id": 101, "type": "CustomReaction"}]])
            res, calls = self._run(daemon, game, "stock_drink")
            self.assertFalse(res["ok"], res)
            self.assertIn("step 1/2", res["reason"])
            self.assertIn("did not finish", res["reason"])
            self.assertEqual(len(calls["act"]), 1)


class TestStepFailures(_RecipeCase):
    def _temp_recipe(self, steps):
        daemon_mod.TASK_DEFS["__test_recipe__"] = {
            "action": "recipe", "need": None, "wait_job": None,
            "steps": steps}
        self.addCleanup(
            lambda: daemon_mod.TASK_DEFS.pop("__test_recipe__", None))

    def test_unknown_task_step_fails_naming_it(self):
        self._temp_recipe([{"task": "bogus_task"}])
        with tempfile.TemporaryDirectory() as tmp:
            daemon = self._daemon(tmp)
            game = _FakeGame(_state())
            res, _ = self._run(daemon, game, "__test_recipe__")
            self.assertFalse(res["ok"], res)
            self.assertIn("step 1/1", res["reason"])
            self.assertIn("unknown task 'bogus_task'", res["reason"])

    def test_unknown_predicate_fails_never_passes(self):
        self._temp_recipe([{"verify": "bogus_check"}])
        with tempfile.TemporaryDirectory() as tmp:
            daemon = self._daemon(tmp)
            game = _FakeGame(_state())
            res, _ = self._run(daemon, game, "__test_recipe__")
            self.assertFalse(res["ok"], res)
            self.assertIn("unknown verify predicate", res["reason"])

    def test_malformed_steps_fail_never_raise(self):
        # Every malformed shape fails with a named reason; none
        # raises, none runs. The malformed-input rule applies to
        # recipe data exactly as to model replies.
        bad_steps = [
            [None],
            ["brew"],
            [{}],
            [{"task": "brew", "action": "queue_job"}],
            [{"task": 5}],
            [{"action": ""}],
            [{"verify": 7}],
            [{"kwargs": {"a": 1}}],
        ]
        for steps in bad_steps:
            with self.subTest(steps=steps):
                self._temp_recipe(steps)
                with tempfile.TemporaryDirectory() as tmp:
                    daemon = self._daemon(tmp)
                    game = _FakeGame(_state())
                    res, calls = self._run(daemon, game,
                                           "__test_recipe__")
                    self.assertFalse(res["ok"], res)
                    self.assertIn("step 1/1", res["reason"])
                    self.assertEqual(calls["act"], [])
                daemon_mod.TASK_DEFS.pop("__test_recipe__", None)

    def test_unknown_action_step_fails_naming_it(self):
        self._temp_recipe([{"action": "bogus_action"}])
        with tempfile.TemporaryDirectory() as tmp:
            daemon = self._daemon(tmp)
            game = _FakeGame(_state())
            res, _ = self._run(daemon, game, "__test_recipe__")
            self.assertFalse(res["ok"], res)
            self.assertIn("unknown action 'bogus_action'",
                          res["reason"])

    def test_param_substitution(self):
        # "$pos" resolves from the recipe call's kwargs; a missing
        # parameter fails the step naming it, before any action.
        self._temp_recipe([{"action": "build_furniture",
                            "kwargs": {"kind": "Bed",
                                       "pos": "$pos"}}])
        with tempfile.TemporaryDirectory() as tmp:
            daemon = self._daemon(tmp)
            game = _FakeGame(_state())
            res, calls = self._run(daemon, game, "__test_recipe__",
                                   pos=[95, 108, 175])
            self.assertTrue(res["ok"], res)
            self.assertEqual(calls["act"][0][1]["pos"], [95, 108, 175])
        with tempfile.TemporaryDirectory() as tmp:
            daemon = self._daemon(tmp)
            game = _FakeGame(_state())
            res, calls = self._run(daemon, game, "__test_recipe__")
            self.assertFalse(res["ok"], res)
            self.assertIn("$pos", res["reason"])
            self.assertEqual(calls["act"], [])

    def test_self_referential_recipe_fails_on_depth(self):
        self._temp_recipe([{"task": "__test_recipe__"}])
        with tempfile.TemporaryDirectory() as tmp:
            daemon = self._daemon(tmp)
            game = _FakeGame(_state())
            res, _ = self._run(daemon, game, "__test_recipe__")
            self.assertFalse(res["ok"], res)
            self.assertIn("nests deeper", res["reason"])


class TestVerifyPredicates(unittest.TestCase):
    def test_workshop_exists(self):
        ok, reason, fix = daemon_mod._verify_predicate(
            "workshop_exists", {"subtype": "Still"}, _state())
        self.assertTrue(ok)
        self.assertIn("Still", reason)
        self.assertIsNone(fix)
        ok, reason, fix = daemon_mod._verify_predicate(
            "workshop_exists", {"subtype": "Kitchen"}, _state())
        self.assertFalse(ok)
        self.assertIn("no Kitchen workshop exists", reason)
        self.assertIn("build a Kitchen", fix)

    def test_stock_at_least(self):
        ok, _, _ = daemon_mod._verify_predicate(
            "stock_at_least", {"kind": "drink", "units": 10},
            _state())
        self.assertTrue(ok)
        ok, reason, fix = daemon_mod._verify_predicate(
            "stock_at_least", {"kind": "drink", "units": 200},
            _state())
        self.assertFalse(ok)
        self.assertIn("97 < 200", reason)
        self.assertIn("103 more drink", fix)

    def test_stock_unreadable_fails(self):
        ok, reason, _ = daemon_mod._verify_predicate(
            "stock_at_least", {"kind": "drink", "units": 1}, {})
        self.assertFalse(ok)
        self.assertIn("unreadable", reason)

    def test_building_exists(self):
        state = {"buildings": {"list": [
            {"id": 9, "type": "FarmPlot"}]}}
        ok, _, _ = daemon_mod._verify_predicate(
            "building_exists", {"type": "FarmPlot"}, state)
        self.assertTrue(ok)
        ok, reason, _ = daemon_mod._verify_predicate(
            "building_exists", {"type": "Well"}, state)
        self.assertFalse(ok)
        self.assertIn("no Well building exists", reason)

    def test_unknown_predicate_and_bad_params_fail(self):
        for name, step in [
                ("bogus", {}),
                ("workshop_exists", {}),
                ("workshop_exists", {"subtype": 5}),
                ("stock_at_least", {"kind": "gold", "units": 1}),
                ("stock_at_least", {"kind": "drink",
                                    "units": "many"})]:
            ok, reason, _ = daemon_mod._verify_predicate(
                name, step, _state())
            self.assertFalse(ok, (name, step))


class TestTaskPlan(unittest.TestCase):
    def test_legacy_task_renders_the_old_four_lines(self):
        plan = daemon_mod.task_plan("brew")
        self.assertEqual(plan["task"], "brew")
        self.assertEqual(len(plan["steps"]), 4)
        self.assertIn("still", plan["preconditions"][0])

    def test_farm_plan_is_unchanged(self):
        plan = daemon_mod.task_plan("farm")
        self.assertEqual(len(plan["steps"]), 5)
        self.assertIn("farm plot", plan["preconditions"][0])

    def test_recipe_renders_its_real_steps(self):
        plan = daemon_mod.task_plan("stock_drink")
        self.assertEqual(len(plan["steps"]), 2)
        self.assertIn("make_barrel", plan["steps"][0])
        self.assertIn("brew", plan["steps"][1])
        self.assertEqual(len(plan["preconditions"]), 2)

    def test_unknown_task_returns_none(self):
        self.assertIsNone(daemon_mod.task_plan("bogus_task"))


class TestResolveKwargs(unittest.TestCase):
    def test_substitution_and_passthrough(self):
        resolved, missing = daemon_mod._resolve_kwargs(
            {"pos": "$pos", "kind": "Bed", "count": 2},
            {"pos": [1, 2, 3]})
        self.assertIsNone(missing)
        self.assertEqual(resolved,
                         {"pos": [1, 2, 3], "kind": "Bed",
                          "count": 2})

    def test_missing_parameter_named(self):
        _, missing = daemon_mod._resolve_kwargs(
            {"pos": "$pos"}, {})
        self.assertEqual(missing, "pos")

    def test_non_dict_kwargs_named(self):
        _, missing = daemon_mod._resolve_kwargs("nope", {})
        self.assertEqual(missing, "kwargs")


class _FakeHandler:
    """Minimal BaseHTTPRequestHandler stand-in: the route helpers
    only need send_response / send_header / end_headers / wfile."""

    def __init__(self):
        self.status = None
        self.headers: dict[str, str] = {}
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass

    @property
    def payload(self):
        return json.loads(self.wfile.getvalue().decode())


class TestTaskPlanRoute(unittest.TestCase):
    """The GET /v1/tasks/{name}/plan route, hit offline: the
    route used to fabricate the four legacy lines for every task,
    which lied about recipes. It now delegates to
    daemon.task_plan. The route takes no daemon (ctx unused), so
    None stands in for the context."""

    def _call(self, name):
        from dfagent_harness.server.routes_tasks import task_plan

        handler = _FakeHandler()
        task_plan(None, handler, {}, f"/v1/tasks/{name}/plan",
                  None)
        return handler

    def test_recipe_route_renders_real_steps(self):
        handler = self._call("stock_drink")
        self.assertEqual(handler.status, 200)
        steps = handler.payload["steps"]
        self.assertTrue(any("make_barrel" in s for s in steps))
        self.assertTrue(any("brew" in s for s in steps))

    def test_legacy_route_renders_old_four_lines(self):
        handler = self._call("brew")
        self.assertEqual(handler.status, 200)
        self.assertEqual(len(handler.payload["steps"]), 4)

    def test_unknown_task_route_is_404(self):
        handler = self._call("bogus_task")
        self.assertEqual(handler.status, 404)
        self.assertEqual(handler.payload["error"]["code"],
                         "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
