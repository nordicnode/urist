"""Tests for the composed tasks' causal chains (GOAL.md step 5,
layer 2). A task encodes the causal chain for a goal: it checks its
prerequisites before queuing, and it reports a cancelled job as a
failure, not a success. A task that claims success when the job was
cancelled is worse than one that fails — it hides the problem.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness import actions, daemon as daemon_mod  # noqa: E402
from dfhack_rpc import DFHackClient, DFHackError  # noqa: E402

HOST = os.environ.get("DFH_TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("DFH_TEST_PORT", "5000"))
LIVE_DISABLED = os.environ.get("DFH_TEST_LIVE", "1") == "0"


def _game_is_up():
    if LIVE_DISABLED:
        return False
    try:
        with DFHackClient(HOST, PORT, timeout=3.0) as client:
            client.get_version()
    except DFHackError:
        return False
    return True


class TestTaskDefsOffline(unittest.TestCase):
    def test_every_task_names_its_need(self):
        # A task's 'need' is the workshop it cannot run without;
        # gather needs none (it designates plants in the open).
        for name, spec in daemon_mod.TASK_DEFS.items():
            self.assertIn("need", spec, name)
            self.assertIn("wait_job", spec, name)
            self.assertIn("action", spec, name)

    def test_brew_needs_a_still(self):
        self.assertEqual(daemon_mod.TASK_DEFS["brew"]["need"], "still")
        self.assertEqual(daemon_mod.TASK_DEFS["brew"]["wait_job"],
                         "CustomReaction")

    def test_cook_needs_a_kitchen(self):
        self.assertEqual(daemon_mod.TASK_DEFS["cook"]["need"], "kitchen")
        self.assertEqual(daemon_mod.TASK_DEFS["cook"]["wait_job"],
                         "PrepareMeal")

    def test_failed_task_names_its_reason(self):
        # The mock runs of 2026-11-27 drove task:brew three times
        # and the run log recorded reason "None": run_task's returns
        # carried "detail" but no "reason", and the driver reads
        # "reason". Every failure path must name its reason through
        # the standard field. The unknown-task path needs no game
        # (it returns before the client check).
        daemon = daemon_mod.Daemon()
        result = daemon.run_task("bogus_task")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "unknown task 'bogus_task'")
        self.assertEqual(result["detail"], result["reason"])

    def test_no_client_task_names_its_reason(self):
        daemon = daemon_mod.Daemon()
        result = daemon.run_task("brew")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "daemon has no DFHack client")


class TestFarmTaskOffline(unittest.TestCase):
    """The farm task's choice logic, offline (the action's own
    preconditions are tested in test_farming.py; the live path in
    test_farming_live.py). The helpers are stubbed with canned
    replies shaped like the live probes (verified 2026-11-27)."""

    def _daemon(self):
        daemon = daemon_mod.Daemon()
        daemon.client = mock.Mock()
        return daemon

    def _run(self, state, site=None, seeds=None, crops=None,
             jobs_present=True, jobs_sequence=None):
        """Run _run_farm_task with stubbed helpers. ``jobs_present``
        True: PlantSeeds jobs appear, then leave (the planting was
        worked). False: no job ever appears (the diagnosis path).
        ``jobs_sequence`` overrides: the per-collect job lists
        (appear wait reads [0], finish wait reads [1], clamped)."""
        site = site if site is not None else {
            "ok": True,
            "farm": {"soil_tiles": 9, "stone_tiles": 0,
                     "other_tiles": 0, "light_tiles": 0,
                     "total_tiles": 9, "light": "dark",
                     "biomes": ["MOUNTAIN"]}}
        seeds = seeds if seeds is not None else {
            "ok": True,
            "by_plant": {"MUSHROOM_HELMET_PLUMP": {
                "units": 5, "in_wagon_units": 5, "stacks": 1}},
            "total_stacks": 6}
        crops = crops if crops is not None else {}
        calls = {"act": []}
        def fake_run_helper(client, name, params, timeout=30.0):
            if name == "probe_site.lua":
                return site
            if name == "probe_seeds.lua":
                return seeds
            if name == "probe_crop.lua":
                return crops[params["crop"]]
            raise AssertionError(f"unexpected helper {name}")

        def fake_act(client, action_name, **kwargs):
            calls["act"].append((action_name, kwargs))
            return actions.ActionResult(
                ok=True, action=action_name, before={}, after={},
                reason="farm plot set",
                detail={"tiles_plantable": 5, "tiles": 9})

        jobs_calls = {"n": 0}

        def fake_collect(client, sections=None):
            jobs_calls["n"] += 1
            if jobs_sequence is not None:
                idx = min(jobs_calls["n"] - 1, len(jobs_sequence) - 1)
                return {"jobs": {"list": jobs_sequence[idx]}}
            if not jobs_present:
                return {"jobs": {"list": []}}
            # First read: the jobs are there; later reads: worked.
            if jobs_calls["n"] == 1:
                return {"jobs": {"list": [
                    {"id": 201, "type": "PlantSeeds"},
                    {"id": 202, "type": "PlantSeeds"}]}}
            return {"jobs": {"list": []}}

        def fake_wait(client, fn, timeout):
            return fn()

        daemon = self._daemon()
        with mock.patch.object(actions, "_run_helper",
                               side_effect=fake_run_helper), \
            mock.patch.object(daemon_mod, "act",
                              side_effect=fake_act), \
            mock.patch.object(daemon_mod.observe, "collect",
                              side_effect=fake_collect), \
            mock.patch.object(actions, "_wait_for_paused",
                              side_effect=fake_wait):
            return daemon._run_farm_task(state, 0.0, 120.0, {}), calls

    def _plot_state(self, stage=3):
        return {"buildings": {"list": [
            {"id": 1, "type": "FarmPlot", "x1": 82, "y1": 82,
             "x2": 84, "y2": 84, "z": 49,
             "construction_stage": stage}]}}

    def test_no_plot_fails_with_fix(self):
        res, _ = self._run({"buildings": {"list": []}})
        self.assertFalse(res["ok"])
        self.assertIn("no farm plot exists", res["reason"])
        self.assertIn("build_farm_plot", res["fix"])

    def test_plot_under_construction_fails(self):
        res, _ = self._run(self._plot_state(stage=2))
        self.assertFalse(res["ok"])
        self.assertIn("still under construction", res["reason"])

    def test_mixed_light_fails(self):
        site = {"ok": True, "farm": {
            "soil_tiles": 5, "stone_tiles": 4, "other_tiles": 0,
            "light_tiles": 5, "total_tiles": 9, "light": "mixed",
            "biomes": ["MOUNTAIN"]}}
        res, _ = self._run(self._plot_state(), site=site)
        self.assertFalse(res["ok"])
        self.assertIn("mixed", res["reason"])

    def test_dark_plot_plants_plump_helmets(self):
        res, calls = self._run(self._plot_state())
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["evidence"]["plant"],
                         "MUSHROOM_HELMET_PLUMP")
        self.assertEqual(calls["act"][0][0], "set_farm_crop")
        self.assertEqual(calls["act"][0][1]["building_id"], 1)
        self.assertEqual(calls["act"][0][1]["plant"],
                         "MUSHROOM_HELMET_PLUMP")
        self.assertIn("5 of 9 tiles", res["reason"])

    def test_other_plot_jobs_do_not_satisfy_appear(self):
        # Scoping (2026-11-27): a PlantSeeds job on another plot's
        # tiles must not satisfy this task's appear wait — live, jobs
        # already pending on plot #2 satisfied the appear wait before
        # plot #5 had any job at all. The plot here is (82-84, 82-84,
        # z49); the job is at (100, 100, 49).
        res, _ = self._run(
            self._plot_state(),
            jobs_sequence=[[{"id": 301, "type": "PlantSeeds",
                             "pos": [100, 100, 49]}]])
        self.assertFalse(res["ok"])
        self.assertIn("no PlantSeeds job appeared", res["reason"])

    def test_other_plot_jobs_do_not_block_finish(self):
        # Scoping (2026-11-27): a PlantSeeds job on another plot's
        # tiles must not block this task's finish wait — live, plot
        # #2's summer jobs kept the finish wait alive for 350+ s
        # after plot #5's own job had finished.
        res, _ = self._run(
            self._plot_state(),
            jobs_sequence=[
                [{"id": 302, "type": "PlantSeeds",
                  "pos": [83, 83, 49]}],
                [{"id": 303, "type": "PlantSeeds",
                  "pos": [100, 100, 49]}]])
        self.assertTrue(res["ok"], res)

    def test_job_without_pos_counts(self):
        # A job with no pos cannot be placed, so it counts — fail
        # toward waiting, never toward a false appear or finish.
        res, _ = self._run(
            self._plot_state(),
            jobs_sequence=[[{"id": 304, "type": "PlantSeeds"}], []])
        self.assertTrue(res["ok"], res)

    def test_malformed_pos_counts(self):
        # A job whose pos is not a numeric 3-list (dict, wrong
        # length, non-numeric) cannot be placed, so it counts — a
        # malformed entry must never fake an appear or a finish.
        res, _ = self._run(
            self._plot_state(),
            jobs_sequence=[
                [{"id": 305, "type": "PlantSeeds",
                  "pos": {"x": 100, "y": 100, "z": 49}},
                 {"id": 306, "type": "PlantSeeds",
                  "pos": [100, 100]},
                 {"id": 307, "type": "PlantSeeds",
                  "pos": ["a", "b", "c"]}],
                []])
        self.assertTrue(res["ok"], res)

    def test_light_plot_picks_most_seeds(self):
        site = {"ok": True, "farm": {
            "soil_tiles": 9, "stone_tiles": 0, "other_tiles": 0,
            "light_tiles": 9, "total_tiles": 9, "light": "all",
            "biomes": ["SWAMP_TEMPERATE_SALTWATER"]}}
        crops = {
            "REED_ROPE": {"ok": True, "crop": "REED_ROPE",
                          "index": 185, "depth_min": 0, "depth_max": 0,
                          "seasons": ["SPRING", "SUMMER", "AUTUMN",
                                      "WINTER"],
                          "biome_flags": ["BIOME_SWAMP_TEMPERATE_SALTWATER"],
                          "cur_season": 0},
            "GRASS_LONGLAND": {"ok": True, "crop": "GRASS_LONGLAND",
                               "index": 181, "depth_min": 0,
                               "depth_max": 0,
                               "seasons": ["SPRING", "SUMMER",
                                           "AUTUMN", "WINTER"],
                               "biome_flags": ["BIOME_SWAMP_TEMPERATE_SALTWATER"],
                               "cur_season": 0},
        }
        seeds = {"ok": True, "by_plant": {
            "REED_ROPE": {"units": 9, "in_wagon_units": 0, "stacks": 1},
            "GRASS_LONGLAND": {"units": 2, "in_wagon_units": 0,
                               "stacks": 1}},
            "total_stacks": 2}
        res, calls = self._run(self._plot_state(), site=site,
                               seeds=seeds, crops=crops)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["evidence"]["plant"], "REED_ROPE")
        self.assertEqual(calls["act"][0][1]["plant"], "REED_ROPE")

    def test_light_plot_no_plantable_crop_fails(self):
        site = {"ok": True, "farm": {
            "soil_tiles": 9, "stone_tiles": 0, "other_tiles": 0,
            "light_tiles": 9, "total_tiles": 9, "light": "all",
            "biomes": ["SWAMP_TEMPERATE_SALTWATER"]}}
        crops = {
            "REED_ROPE": {"ok": True, "crop": "REED_ROPE",
                          "index": 185, "depth_min": 0, "depth_max": 0,
                          "seasons": ["SPRING", "SUMMER", "AUTUMN",
                                      "WINTER"],
                          "biome_flags": ["BIOME_SWAMP_TEMPERATE_SALTWATER"],
                          "cur_season": 0},
            "GRASS_LONGLAND": {"ok": True, "crop": "GRASS_LONGLAND",
                               "index": 181, "depth_min": 0,
                               "depth_max": 0,
                               "seasons": ["SPRING", "SUMMER",
                                           "AUTUMN", "WINTER"],
                               "biome_flags": ["BIOME_SWAMP_TEMPERATE_SALTWATER"],
                               "cur_season": 0},
        }
        seeds = {"ok": True, "by_plant": {}, "total_stacks": 0}
        res, calls = self._run(self._plot_state(), site=site,
                               seeds=seeds, crops=crops)
        self.assertFalse(res["ok"])
        self.assertIn("no surface crop can be planted", res["reason"])
        self.assertEqual(calls["act"], [])

    def test_no_jobs_appearing_fails_with_diagnosis(self):
        res, _ = self._run(self._plot_state(), jobs_present=False)
        self.assertFalse(res["ok"])
        self.assertIn("no PlantSeeds job appeared", res["reason"])
        self.assertIn("wagon", res["fix"])


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestTasksLive(unittest.TestCase):
    """The causal chains, live (paused reads and writes only — no
    unpause, no game time advances, no drink consumed)."""

    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=180.0)
        cls.client.connect()
        cls.was_paused = actions.get_paused(cls.client)
        if not cls.was_paused:
            actions.set_paused(cls.client, True)
        cls.daemon = daemon_mod.Daemon()
        # The daemon normally connects its own client in start();
        # here the test supplies the shared one (the daemon is not
        # started — run_task only needs client + lock + state dir).
        cls.daemon.client = cls.client

    @classmethod
    def tearDownClass(cls):
        if not cls.was_paused:
            actions.set_paused(cls.client, False)
        cls.client.close()

    def test_brew_without_a_still_fails_fast(self):
        # The fort has no still (only a carpenter's workshop), so
        # the brew task must fail on the prerequisite (a still), not
        # queue a job that can never be worked.
        result = self.daemon.run_task("brew")
        self.assertFalse(result["ok"])
        self.assertIn("no still workshop exists", result["detail"])
        # The failure reason must be readable through the standard
        # "reason" field (the driver and the run log read it there).
        self.assertEqual(result["reason"], result["detail"])
        self.assertIn("no still workshop exists", result["reason"])

    def test_gather_uses_a_surface_box(self):
        # The gather box is derived from the live state (a probe for
        # shrubs on the surface), never the old hardcoded GATHER_BOX
        # (Athelunol z=42, solid rock here). Designating is a paused
        # write; the game stays paused, so no GatherPlants job
        # spawns and no drink is consumed. The designation is
        # cleared afterwards (mark=False) to leave no trace.
        from dfagent_harness import observe
        state = observe.collect(self.client)
        citizens = (state.get("units") or {}).get("citizens") or []
        self.assertGreater(len(citizens), 0)
        surface_z = min(c["pos"][2] for c in citizens if c.get("pos"))
        result = self.daemon.run_task("gather")
        self.assertTrue(result["ok"], result)
        # The box is on the surface (never z=42) and shrubs were
        # actually marked (the action's own before/after read-back).
        self.assertEqual(result["box"][2], surface_z)
        self.assertGreater(result["after"]["total"], 0)
        self.assertEqual(result["after"]["marked"],
                         result["after"]["total"])
        # Clean up: unmark the shrubs.
        actions.act(self.client, "designate_gather",
                    box=tuple(result["box"]), mark=False)

    def test_unknown_task_fails_cleanly(self):
        result = self.daemon.run_task("bogus_task")
        self.assertFalse(result["ok"])
        self.assertIn("unknown task", result["detail"])
        self.assertIn("unknown task", result["reason"])


if __name__ == "__main__":
    unittest.main()
