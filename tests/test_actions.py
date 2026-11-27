"""Unit tests for the verified action layer (phase 2).

The Python plumbing (pre/postcondition logic, failure paths, pause
restore, no-retry behaviour) is tested against a FakeClient that
simulates the game at the transport level: it parses the PARAMS block
out of the Lua the action layer generates and answers each helper the
way the real Lua helpers would, against a small in-memory fort. The Lua
helpers themselves are exercised by tests/test_actions_live.py against
the real game.
"""

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import actions  # noqa: E402
from dfhack_rpc import DFHackError, RemoteError, TransportError  # noqa: E402


# -- a tiny Lua-table parser for the PARAMS block --------------------------

def _parse_lua_table(text):
    """Parse the PARAMS literal the action layer generates."""
    pos = 0

    def skip_ws():
        nonlocal pos
        while pos < len(text) and text[pos] in " \t":
            pos += 1

    def parse_value():
        nonlocal pos
        skip_ws()
        ch = text[pos]
        if ch == "{":
            return parse_table()
        if ch == '"':
            return parse_string()
        m = re.compile(r"-?\d+").match(text, pos)
        if m:
            pos = m.end()
            return int(m.group(0))
        for word, val in (("true", True), ("false", False), ("nil", None)):
            if text.startswith(word, pos):
                pos += len(word)
                return val
        raise ValueError(f"cannot parse at {pos}: {text[pos:pos + 20]!r}")

    def parse_string():
        nonlocal pos
        assert text[pos] == '"'
        pos += 1
        out = bytearray()
        while text[pos] != '"':
            if text[pos] == "\\":
                m = re.compile(r"\\(\d+)").match(text, pos)
                if not m:
                    raise ValueError("bad escape in PARAMS string")
                out.append(int(m.group(1)))
                pos = m.end()
            else:
                out.extend(text[pos].encode("utf-8"))
                pos += 1
        pos += 1
        return bytes(out).decode("cp437")

    def parse_table():
        nonlocal pos
        assert text[pos] == "{"
        pos += 1
        arr, obj = [], {}
        while True:
            skip_ws()
            if text[pos] == "}":
                pos += 1
                return obj if obj else arr
            key = None
            m = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=").match(text, pos)
            if m:
                key = m.group(1)
                pos = m.end()
            val = parse_value()
            if key is None:
                arr.append(val)
            else:
                obj[key] = val
            skip_ws()
            if text[pos] == ",":
                pos += 1

    return parse_value()


class _SingleBool:
    def __init__(self, value):
        self.Value = value


class FakeGame:
    """Minimal simulated fort: z=41 is all wall, z=42 is all floor."""

    def __init__(self):
        self.paused = True
        self.dig = {}  # (x, y, z) -> mode name
        self.plants = [
            {"pos": [101, 103, 32], "kind": "tree",
             "des": [101, 103, 32], "marked": False},
            {"pos": [97, 98, 42], "kind": "shrub",
             "des": [97, 98, 42], "marked": False},
            {"pos": [99, 106, 42], "kind": "shrub",
             "des": [99, 106, 42], "marked": False},
            # A sapling: neither tree nor shrub — both actions ignore it.
            {"pos": [100, 100, 32], "kind": "sapling",
             "des": [100, 100, 32], "marked": False},
        ]
        self.jobs = []
        self.next_job_id = 1
        # Jobs whose removal was requested while paused: the real game
        # only drops them from world.jobs.list on a tick, so they stay
        # visible until the fake is unpaused (see FakeClient.call).
        self.pending_removal_ids = set()
        self.process_cancels = True  # False: cancellations never land
        self.orders = []
        self.next_order_id = 0
        self.buildings = [{"id": 0, "type": "Wagon", "type_id": 32,
                           "x1": 94, "y1": 94, "x2": 96, "y2": 96, "z": 42,
                           "center": [95, 95, 42], "construction_stage": 3,
                           "jobs": 0, "contained_items": 59}]
        self.next_building_id = 1
        self.citizens = [
            {"id": 1, "name": "Udil Testdwarf",
             "labors": ["MINE", "HAUL_STONE"]},
            {"id": 2, "name": "Deduk Stâkudunib",
             "labors": ["CARPENTER"]},
        ]
        self.material = {"WOOD": {"total": 3, "accessible": 3,
                                  # Stand-in wood material: the real
                                  # probe returns the first accessible
                                  # item's mat_type/mat_index, and the
                                  # action layer only needs a non-(-1)
                                  # value to pass an explicit filter.
                                  "mat_type": 0, "mat_index": 0}}
        # Stocks the queue_job material fail-fast reads (general
        # material awareness, 2026-11-27). Tests override per case.
        self.stocks = {"drink_units": 35, "food_units": 32,
                       "food_stacks": 12, "wood_units": 124,
                       "stone_units": 0, "seeds_units": 35,
                       "barrels": 15, "empty_barrels": 3,
                       "by_material": [
                           # Real plants (type PLANT, STRUCTURAL,
                           # flagged brewable by stocks.lua) — NOT
                           # the old DRINK-material entry, which
                           # counted brewed drink as plants
                           # (2026-11-27, external review C3).
                           {"type": "PLANT",
                            "material":
                            "PLANT:MUSHROOM_HELMET_PLUMP:STRUCTURAL",
                            "brewable": True, "units": 33}]}
        self.spawn_jobs = True       # tier-2: game spawns FellTree/etc.
        self.complete_builds = True  # buildings finish construction
        self.build_polls = 0
        self.process_dig_requested = False
        self.calls = []              # (helper, params) for call counting

    # -- shape of the observe sections the actions read --------------------
    def section(self, name):
        if name == "map":
            return {"size_tiles": [192, 192], "z_levels": 58}
        if name == "jobs":
            return {"list": list(self.jobs), "count": len(self.jobs),
                    "counts_by_type": [],
                    "manager_orders": [dict(o) for o in self.orders],
                    "manager_order_count": len(self.orders)}
        if name == "buildings":
            return {"list": [dict(b) for b in self.buildings],
                    "count": len(self.buildings), "summary": []}
        if name == "units":
            return {"citizens": [
                {"id": c["id"], "name": c["name"],
                 "labors": list(c["labors"])} for c in self.citizens],
                "citizen_count": len(self.citizens)}
        if name == "reports":
            return {"announcements": [], "announcement_count": 0,
                    "reports": [], "report_count": 0}
        if name == "stocks":
            return dict(self.stocks)
        raise AssertionError(f"unexpected section {name!r}")

    # -- helper simulation --------------------------------------------------
    def run_helper(self, name, params):
        self.calls.append((name, params))
        if name == "probe_dig.lua":
            total = sum(1 for (x, y, z) in self.dig
                        if params["x0"] <= x <= params["x1"]
                        and params["y0"] <= y <= params["y1"]
                        and z == params["z0"])
            return {"ok": True, "probe": "dig", "dig_total": total,
                    "dig_by_type": ([{"type": "Default", "count": total}]
                                    if total else [])}
        if name == "act_dig.lua":
            if params["mode"] != "clear":
                bad = [[x, y, "FLOOR"]
                       for x in range(params["x0"], params["x1"] + 1)
                       for y in range(params["y0"], params["y1"] + 1)
                       if params["z0"] == 42]
                if bad:
                    return {"ok": False, "action": "dig",
                            "kind": "precondition",
                            "error": "not all tiles are walls",
                            "bad_tiles": bad}
                for x in range(params["x0"], params["x1"] + 1):
                    for y in range(params["y0"], params["y1"] + 1):
                        self.dig[(x, y, params["z0"])] = params["mode"]
                return {"ok": True, "action": "dig",
                        "mode": params["mode"],
                        "set": (params["x1"] - params["x0"] + 1)
                        * (params["y1"] - params["y0"] + 1), "cleared": 0}
            cleared = sum(1 for (x, y, z) in list(self.dig)
                          if params["x0"] <= x <= params["x1"]
                          and params["y0"] <= y <= params["y1"]
                          and z == params["z0"])
            for k in list(self.dig):
                x, y, z = k
                if (params["x0"] <= x <= params["x1"]
                        and params["y0"] <= y <= params["y1"]
                        and z == params["z0"]):
                    del self.dig[k]
            return {"ok": True, "action": "dig", "mode": "clear",
                    "set": 0, "cleared": cleared}
        if name in ("probe_plants.lua", "act_plants.lua"):
            in_rect = [p for p in self.plants
                       if p["kind"] == params["kind"]
                       and p["pos"][2] == params["z0"]
                       and params["x0"] <= p["pos"][0] <= params["x1"]
                       and params["y0"] <= p["pos"][1] <= params["y1"]]
            if name == "probe_plants.lua":
                return {"ok": True, "probe": "plants",
                        "kind": params["kind"], "total": len(in_rect),
                        "marked": sum(1 for p in in_rect if p["marked"]),
                        "plants": [{"pos": p["pos"], "des": p["des"],
                                    "marked": p["marked"]}
                                   for p in in_rect]}
            if not in_rect:
                return {"ok": False, "action": "plants",
                        "kind": "precondition", "error": "no trees in area",
                        "found": 0}
            changed, already = [], []
            for p in in_rect:
                if params["mark"] and not p["marked"]:
                    p["marked"] = True
                    changed.append(p)
                    if self.spawn_jobs:
                        jtype = ("FellTree" if p["kind"] == "tree"
                                 else "GatherPlants")
                        self.jobs.append(
                            {"id": self.next_job_id, "type": jtype,
                             "pos": list(p["des"])})
                        self.next_job_id += 1
                elif not params["mark"] and p["marked"]:
                    p["marked"] = False
                    changed.append(p)
                    # Removal is deferred: the jobs stay listed until
                    # the game ticks (unpause), like the real game.
                    for j in self.jobs:
                        if j["pos"] == p["des"]:
                            self.pending_removal_ids.add(j["id"])
                else:
                    already.append(p)
            return {"ok": True, "action": "plants",
                    "kind": params["kind"], "mark": params["mark"],
                    "found": len(in_rect),
                    "changed": [{"pos": p["pos"]} for p in changed],
                    "already": [{"pos": p["pos"]} for p in already]}
        if name == "probe_jobs_at.lua":
            tiles = [tuple(t) for t in params["tiles"]]
            found = [j for j in self.jobs
                     if j["type"] in params["types"]
                     and tuple(j["pos"]) in tiles]
            return {"ok": True, "probe": "jobs_at", "jobs": found,
                    "count": len(found)}
        if name == "probe_material.lua":
            m = self.material.get(params["item_type"],
                                  {"total": 0, "accessible": 0})
            return {"ok": True, "probe": "material",
                    "item_type": params["item_type"], **m}
        if name == "probe_site.lua":
            return {"ok": True, "probe": "site", "free": True,
                    "problems": []}
        if name == "act_order.lua":
            if params["mode"] == "create":
                oid = self.next_order_id
                self.next_order_id += 1
                self.orders.append(
                    {"id": oid, "job_type": params["job_type"],
                     "job_type_name": params["job_type"],
                     "amount_left": params["amount"],
                     "amount_total": params["amount"]})
                return {"ok": True, "action": "order", "mode": "create",
                        "id": oid, "job_type": params["job_type"],
                        "amount_left": params["amount"],
                        "amount_total": params["amount"]}
            keep = [o for o in self.orders
                    if o["id"] != params["order_id"]]
            if len(keep) == len(self.orders):
                return {"ok": False, "action": "order",
                        "kind": "precondition",
                        "error": "no manager order with id "
                        f"{params['order_id']}"}
            gone = [o for o in self.orders
                    if o["id"] == params["order_id"]][0]
            self.orders = keep
            return {"ok": True, "action": "order", "mode": "remove",
                    "id": params["order_id"],
                    "job_type": gone["job_type"]}
        if name == "probe_bldg_mat.lua":
            target = next((b for b in self.buildings
                           if b["id"] == params["building_id"]), None)
            if target is None:
                return {"ok": False,
                        "error": "no building #"
                        f"{params['building_id']}"}
            return {"ok": True, "building_id": target["id"],
                    "mat_type": target.get("mat_type", -1),
                    "mat_index": target.get("mat_index", -1),
                    "mat_name": None,
                    "construction_stage":
                        target.get("construction_stage")}
        if name == "act_build.lua":
            bid = self.next_building_id
            self.next_building_id += 1
            self.buildings.append(
                {"id": bid, "type": "Workshop", "type_id": 13,
                 "x1": params["x"], "y1": params["y"],
                 "x2": params["x"] + params["width"] - 1,
                 "y2": params["y"] + params["height"] - 1,
                 "z": params["z"],
                 "center": [params["x"] + 1, params["y"] + 1, params["z"]],
                 "construction_stage": 0, "jobs": 1,
                 "contained_items": 0,
                 # No material filter in the params means the real
                 # game sometimes creates a mat-NONE building; the
                 # mock stores -1 so the fail-fast path is exercised.
                 "mat_type": params.get("mat_type")
                 if params.get("mat_type") is not None else -1,
                 "mat_index": params.get("mat_index")
                 if params.get("mat_index") is not None else -1})
            self.jobs.append({"id": self.next_job_id,
                              "type": "ConstructBuilding",
                              "pos": [params["x"] + 1, params["y"] + 1,
                                      params["z"]]})
            self.next_job_id += 1
            self.build_polls = 0
            return {"ok": True, "action": "build", "id": bid,
                    "center": [params["x"] + 1, params["y"] + 1,
                               params["z"]],
                    "construction_stage": 0}
        if name == "act_furniture.lua":
            bid = self.next_building_id
            self.next_building_id += 1
            self.buildings.append(
                {"id": bid, "type": params["kind"], "type_id": 0,
                 "x1": params["x"], "y1": params["y"],
                 "x2": params["x"], "y2": params["y"],
                 "z": params["z"],
                 "center": [params["x"], params["y"], params["z"]],
                 "construction_stage": 0, "jobs": 1,
                 "contained_items": 0})
            self.jobs.append({"id": self.next_job_id,
                              "type": "ConstructBuilding",
                              "pos": [params["x"], params["y"],
                                      params["z"]]})
            self.next_job_id += 1
            self.build_polls = 0
            return {"ok": True, "action": "build-furniture",
                    "kind": params["kind"], "id": bid,
                    "center": [params["x"], params["y"], params["z"]],
                    "x1": params["x"], "y1": params["y"],
                    "x2": params["x"], "y2": params["y"],
                    "z": params["z"], "construction_stage": 0}
        if name == "act_job.lua":
            # The real helper (fixed 2026-11-27) calls
            # linkIntoWorld(job, true), which assigns the next id
            # from the game's counter immediately — a fresh job
            # carries a real id, never -1. (-1 was the 1-arg
            # linkIntoWorld no-op; a -1 id is corrupt and the
            # action layer now rejects it.) It also attaches a
            # BUILDING_HOLDER general_ref to the workshop — without
            # it the game segfaults when a dwarf works the job
            # (run #12/#13/#14 deaths; 3/3 advances died without
            # the ref, 3/3 survived with it, and a bed job
            # completed). The mock records the holder the same way.
            count = params.get("count", 1)
            ids = []
            for _ in range(count):
                self.jobs.append({"id": self.next_job_id,
                                  "type": "CustomReaction",
                                  "holder_building_id":
                                      params["building_id"],
                                  "pos": [0, 0, 0]})
                ids.append(self.next_job_id)
                self.next_job_id += 1
            return {"ok": True, "action": "queue-job",
                    "job_ids": ids, "count": count}
        if name == "act_labor.lua":
            # Mirrors the real helper: -1 is the by-name sentinel
            # (2026-11-27, external review Table 5 row 4); unit id
            # 0 is a real id and must be targetable.
            target = None
            for c in self.citizens:
                if params["unit_id"] != -1 \
                        and c["id"] == params["unit_id"]:
                    target = c
                if params["unit_id"] == -1 \
                        and c["name"] == params["name"]:
                    target = c
            if target is None:
                return {"ok": False, "action": "labor",
                        "kind": "precondition", "error": "no such citizen"}
            before = params["labor"] in target["labors"]
            if params["on"]:
                if params["labor"] not in target["labors"]:
                    target["labors"].append(params["labor"])
            else:
                target["labors"] = [l for l in target["labors"]
                                    if l != params["labor"]]
            return {"ok": True, "action": "labor", "id": target["id"],
                    "name": target["name"], "labor": params["labor"],
                    "before": before, "after": params["on"]}
        raise AssertionError(f"unexpected helper {name!r}")


class FakeClient:
    """Pretends to be DFHackClient for the action layer."""

    def __init__(self, game):
        self.game = game
        self.raise_transport = False
        self.run_lua_calls = []  # raw Lua snippets (e.g. process_dig flag)

    def run_lua(self, code, timeout=None):
        self.run_lua_calls.append(code)
        if "checkDesignationsNow" in code:
            self.game.process_dig_requested = True
        return ""

    def run_lua_json(self, code, timeout=None):
        if self.raise_transport:
            raise DFHackError("simulated transport failure")
        m = re.search(r"^PARAMS = (.*)$", code, re.MULTILINE)
        params = _parse_lua_table(m.group(1)) if m else {}
        # Match on the helper's own header line ("-- <name> ..."); the
        # bodies mention each other (e.g. the shared des_tile note), so a
        # bare substring match would misroute act_plants <-> probe_plants.
        for name in ("probe_dig.lua", "act_dig.lua", "probe_plants.lua",
                     "act_plants.lua", "probe_jobs_at.lua",
                     "probe_material.lua", "probe_site.lua",
                     "probe_bldg_mat.lua",
                     "act_order.lua", "act_build.lua", "act_labor.lua",
                     "act_furniture.lua", "act_job.lua"):
            if f"-- {name}" in code:
                return self.game.run_helper(name, params)
        raise AssertionError("no helper marker found in Lua code")

    def call(self, method, msg, output_cls=None, **kwargs):
        if method == "GetPauseState":
            return _SingleBool(self.game.paused), ""
        if method == "SetPauseState":
            self.game.paused = bool(msg.Value)
            if not self.game.paused and self.game.process_cancels:
                # Ticks process pending cancellations: the jobs vanish.
                self.game.jobs = [
                    j for j in self.game.jobs
                    if j["id"] not in self.game.pending_removal_ids]
                self.game.pending_removal_ids.clear()
            return None, ""
        raise AssertionError(f"unexpected RPC {method!r}")


def _run_with_fake(testcase, game):
    """Patch actions._read_section to the fake; return the FakeClient."""
    client = FakeClient(game)
    patcher = mock.patch.object(
        actions, "_read_section",
        side_effect=lambda c, section, timeout=30.0: game.section(section))
    testcase.addCleanup(patcher.stop)
    patcher.start()
    # Buildings reads also drive build completion in the fake: after the
    # first post-placement poll, construction finishes (or never does).
    orig_section = game.section

    def section(name):
        if name == "buildings" and game.buildings:
            for b in game.buildings:
                # Any building with a pending construction job
                # (workshop or furniture) completes after the first
                # post-placement poll.
                if b.get("jobs") == 1:
                    game.build_polls += 1
                    if game.complete_builds and game.build_polls >= 2:
                        b["jobs"] = 0
                        b["construction_stage"] = 2
                        game.jobs = [j for j in game.jobs
                                     if j["type"] != "ConstructBuilding"]
        return orig_section(name)

    game.section = section
    return client


class TestDig(unittest.TestCase):
    def setUp(self):
        self.game = FakeGame()
        self.client = _run_with_fake(self, self.game)

    def test_dig_set_and_clear_roundtrip(self):
        box = (90, 90, 41, 92, 92, 41)
        r = actions.act(self.client, "designate_dig", box=box, mode="dig")
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.before, {"dig_total": 0})
        self.assertEqual(r.after["dig_total"], 9)
        r2 = actions.act(self.client, "designate_dig", box=box,
                         mode="clear")
        self.assertTrue(r2.ok, r2.reason)
        self.assertEqual(r2.after["dig_total"], 0)
        self.assertEqual(self.game.dig, {})

    def test_dig_to_completion_clear_is_precondition(self):
        # H7 (2026-11-27, external review): mode='clear' has no
        # job type, and the bare DIG_JOB_TYPES index raised
        # KeyError — which act() does not catch — killing the
        # caller instead of failing the action. Clearing is
        # designate_dig's job.
        r = actions.act(self.client, "dig_to_completion",
                        box=(90, 90, 41, 91, 91, 41), mode="clear")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")
        self.assertIn("clear", r.reason)

    def test_dig_multi_z_box_is_precondition(self):
        # H8 (2026-11-27, external review): the Lua helpers only
        # touch z0, so a multi-z box designated one layer while
        # the Python side verified the whole box. Boxes are one
        # layer; a multi-z box is refused before anything is
        # designated.
        r = actions.act(self.client, "designate_dig",
                        box=(90, 90, 41, 92, 92, 42), mode="dig")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")
        self.assertEqual(self.game.dig, {})

    def test_dig_refuses_floor_tiles_and_writes_nothing(self):
        box = (90, 90, 42, 91, 91, 42)  # z=42 is floor in the fake
        r = actions.act(self.client, "designate_dig", box=box, mode="dig")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")
        self.assertEqual(self.game.dig, {})

    def test_dig_bad_mode_is_precondition(self):
        r = actions.act(self.client, "designate_dig",
                        box=(90, 90, 41, 91, 91, 41), mode="explode")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")

    def test_dig_box_outside_map_is_precondition(self):
        r = actions.act(self.client, "designate_dig",
                        box=(190, 90, 41, 195, 92, 41), mode="dig")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")

    def test_verification_failure_runs_mutation_exactly_once(self):
        # Sabotage the read-back: after the mutation the probe lies and
        # reports 0 designated tiles. The action must fail verification
        # and must NOT retry the mutation.
        box = (90, 90, 41, 91, 91, 41)
        orig = self.game.run_helper

        def lying(name, params):
            out = orig(name, params)
            if name == "probe_dig.lua" and self.game.dig:
                return {"ok": True, "probe": "dig", "dig_total": 0,
                        "dig_by_type": []}
            return out

        self.game.run_helper = lying
        r = actions.act(self.client, "designate_dig", box=box, mode="dig")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "verification")
        mutates = [c for c in self.game.calls if c[0] == "act_dig.lua"]
        self.assertEqual(len(mutates), 1, "mutation must run exactly once")


class TestPlants(unittest.TestCase):
    def setUp(self):
        self.game = FakeGame()
        self.client = _run_with_fake(self, self.game)

    def test_chop_marks_and_unmarks(self):
        box = (98, 100, 32, 104, 106, 32)
        r = actions.act(self.client, "designate_chop", box=box,
                        job_timeout=5.0)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.after, {"total": 1, "marked": 1})
        self.assertTrue(any(j["type"] == "FellTree" for j in self.game.jobs))
        r2 = actions.act(self.client, "designate_chop", box=box, mark=False)
        self.assertTrue(r2.ok, r2.reason)
        self.assertEqual(r2.after, {"total": 1, "marked": 0})
        # FellTree jobs are reported, not waited on (the game never
        # removes them): the fake job stays listed.
        self.assertFalse(r2.detail["waited_for_job_removal"])
        self.assertEqual(len(r2.detail["remaining_jobs"]), 1)
        self.assertEqual(r2.detail["remaining_jobs"][0]["type"], "FellTree")

    def test_gather_marks_shrub(self):
        box = (95, 96, 42, 99, 100, 42)
        r = actions.act(self.client, "designate_gather", box=box,
                        job_timeout=5.0)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.after, {"total": 1, "marked": 1})

    def test_chop_no_trees_is_precondition(self):
        r = actions.act(self.client, "designate_chop",
                        box=(50, 50, 42, 55, 55, 42))
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")

    def test_chop_ignores_sapling(self):
        # The fake fort has a sapling at (100,100,32): it is neither a
        # tree nor a shrub, so chop and gather both refuse the box.
        box = (98, 98, 32, 102, 102, 32)
        r = actions.act(self.client, "designate_chop", box=box)
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")
        r2 = actions.act(self.client, "designate_gather", box=box)
        self.assertFalse(r2.ok)
        self.assertEqual(r2.error_kind, "precondition")

    def test_mark_requests_process_dig(self):
        # Marking must flag the designation for the game's processing,
        # or the game may never spawn the job (verified live).
        box = (98, 100, 32, 104, 106, 32)
        r = actions.act(self.client, "designate_chop", box=box,
                        job_timeout=5.0)
        self.assertTrue(r.ok, r.reason)
        self.assertTrue(self.game.process_dig_requested)

    def test_chop_job_timeout_restores_pause(self):
        self.game.spawn_jobs = False
        self.assertTrue(self.game.paused)
        r = actions.act(self.client, "designate_chop",
                        box=(98, 100, 32, 104, 106, 32), job_timeout=1.0)
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "timeout")
        self.assertTrue(self.game.paused, "game must be re-paused")

    def test_chop_unmark_reports_stale_job_without_waiting(self):
        # FellTree jobs are never removed by the game, so the unmark
        # does not burn the wait bound on them: it reports the stale
        # job immediately and never unpauses.
        box = (98, 100, 32, 104, 106, 32)
        r = actions.act(self.client, "designate_chop", box=box,
                        job_timeout=5.0)
        self.assertTrue(r.ok, r.reason)
        self.assertTrue(any(j["type"] == "FellTree" for j in self.game.jobs))
        r2 = actions.act(self.client, "designate_chop", box=box, mark=False,
                         job_timeout=5.0)
        self.assertTrue(r2.ok, r2.reason)
        self.assertFalse(r2.detail["waited_for_job_removal"],
                         "chop unmark must not wait on FellTree jobs")
        self.assertEqual(len(r2.detail["remaining_jobs"]), 1)
        self.assertEqual(r2.detail["remaining_jobs"][0]["type"], "FellTree")
        self.assertTrue(self.game.paused, "game must stay paused")

    def test_gather_unmark_waits_for_job_removal_on_ticks(self):
        # GatherPlants jobs do leave the list on ticks: the unmark
        # waits them out and re-pauses after.
        box = (95, 96, 42, 99, 100, 42)
        r = actions.act(self.client, "designate_gather", box=box,
                        job_timeout=5.0)
        self.assertTrue(r.ok, r.reason)
        self.assertTrue(any(j["type"] == "GatherPlants"
                            for j in self.game.jobs))
        r2 = actions.act(self.client, "designate_gather", box=box,
                         mark=False, job_timeout=5.0)
        self.assertTrue(r2.ok, r2.reason)
        self.assertTrue(r2.detail["waited_for_job_removal"],
                        "gather unmark should have waited for the job")
        self.assertEqual(r2.detail["remaining_jobs"], [])
        self.assertFalse(any(j["type"] == "GatherPlants"
                             for j in self.game.jobs))
        self.assertTrue(self.game.paused, "game must be re-paused")

    def test_gather_unmark_reports_unremoved_jobs_and_repauses(self):
        # The game never processes the cancellation: the unmark still
        # succeeds (the designation is verified clear) but reports the
        # remaining job in detail — and re-pauses.
        self.game.process_cancels = False
        box = (95, 96, 42, 99, 100, 42)
        r = actions.act(self.client, "designate_gather", box=box,
                        job_timeout=5.0)
        self.assertTrue(r.ok, r.reason)
        r2 = actions.act(self.client, "designate_gather", box=box,
                         mark=False, job_timeout=1.0)
        self.assertTrue(r2.ok, r2.reason)
        self.assertEqual(len(r2.detail["remaining_jobs"]), 1)
        self.assertEqual(r2.detail["remaining_jobs"][0]["type"],
                         "GatherPlants")
        self.assertTrue(self.game.paused, "game must be re-paused")


class TestOrders(unittest.TestCase):
    def setUp(self):
        self.game = FakeGame()
        self.client = _run_with_fake(self, self.game)

    def test_create_then_remove(self):
        r = actions.act(self.client, "manager_order_create",
                        job_type="MakeBarrel", amount=5)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.detail["order_id"], 0)
        self.assertEqual(r.after["manager_order_count"], 1)
        r2 = actions.act(self.client, "manager_order_remove", order_id=0)
        self.assertTrue(r2.ok, r2.reason)
        self.assertEqual(r2.after["manager_order_count"], 0)

    def test_remove_missing_is_precondition(self):
        r = actions.act(self.client, "manager_order_remove", order_id=99)
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")


class TestBuild(unittest.TestCase):
    def setUp(self):
        self.game = FakeGame()
        self.client = _run_with_fake(self, self.game)

    def test_build_completes(self):
        r = actions.act(self.client, "build_workshop", kind="carpenter",
                        pos=(85, 85, 42), build_timeout=30.0)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.after["building"]["construction_stage"], 2)
        self.assertTrue(self.game.paused)

    def test_build_no_accessible_material(self):
        self.game.material["WOOD"] = {"total": 3, "accessible": 0}
        r = actions.act(self.client, "build_workshop", kind="carpenter",
                        pos=(85, 85, 42))
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")
        # The error names the fix (chop trees), not a generic hint.
        self.assertIn("chop trees", r.reason)
        self.assertEqual(len(self.game.buildings), 1)  # nothing placed

    def test_build_no_material_still_names_both_alternatives(self):
        self.game.material["WOOD"] = {"total": 0, "accessible": 0}
        self.game.material["BOULDER"] = {"total": 0, "accessible": 0}
        r = actions.act(self.client, "build_workshop", kind="still",
                        pos=(85, 85, 42))
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")
        self.assertIn("1 stone (boulder)", r.reason)
        self.assertIn("1 wood (log)", r.reason)
        self.assertIn("dig stone", r.reason)
        self.assertIn("chop trees", r.reason)

    def test_build_unknown_kind(self):
        r = actions.act(self.client, "build_workshop", kind="sauna",
                        pos=(85, 85, 42))
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")

    def test_build_timeout_reports_and_repauses(self):
        self.game.complete_builds = False
        r = actions.act(self.client, "build_workshop", kind="carpenter",
                        pos=(85, 85, 42), build_timeout=2.0)
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "timeout")
        self.assertTrue(self.game.paused)

    def test_failed_material_probe_is_transport_not_mat_none(self):
        # Table 5 row 2: when the material read-back probe itself
        # fails, the read never happened — that is transport, not a
        # "placed with no material" verification failure. The old
        # code read mat_type off the failed probe, got -1, and
        # misclassified it.
        orig = actions._run_helper

        def _wrapped(client, name, params, timeout=30.0):
            if name == "probe_bldg_mat.lua":
                return {"ok": False, "error": "probe boom"}
            return orig(client, name, params, timeout=timeout)

        with mock.patch.object(actions, "_run_helper",
                               side_effect=_wrapped):
            r = actions.act(self.client, "build_workshop",
                            kind="carpenter", pos=(85, 85, 42))
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "transport")
        self.assertIn("read-back failed", r.reason)
        self.assertNotIn("mat NONE", r.reason)


class TestBuildFurniture(unittest.TestCase):
    def setUp(self):
        self.game = FakeGame()
        self.client = _run_with_fake(self, self.game)
        # The fort has a Carpenter's workshop (#7), like the live
        # fort — the refusal message names it.
        self.game.buildings += [
            {"id": 7, "type": "Workshop", "subtype": "Carpenters",
             "jobs": 0},
            {"id": 8, "type": "Workshop", "subtype": "Still",
             "jobs": 0}]

    def test_placed_bed_does_not_satisfy_availability(self):
        # Table 5 row 1: the items section's by_type counts placed
        # (in_building) furniture, so a placed bed used to satisfy
        # this check with zero loose items and the Construct job
        # suspended until the action burned its full timeout. The
        # check now uses the probe's accessible count: total 1,
        # accessible 0 (the one bed is placed) must refuse.
        self.game.material["BED"] = {"total": 1, "accessible": 0}
        r = actions.act(self.client, "build_furniture", kind="Bed",
                        pos=(90, 80, 42), build_timeout=30.0)
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")
        self.assertIn("make one first", r.reason)
        # The fix names the real Carpenter's workshop (#7 in the
        # fake): the lookup used to compare the subtype to
        # "Carpenter" while the game spells it "Carpenters", so it
        # always fell back to "build a Carpenter's workshop" even
        # when one already existed (caught live 2026-11-27).
        self.assertIn("building #7", r.reason)
        # Wagon + Carpenters + Still; nothing placed.
        self.assertEqual(len(self.game.buildings), 3)

    def test_accessible_bed_builds(self):
        self.game.material["BED"] = {"total": 1, "accessible": 1,
                                     "mat_type": 0, "mat_index": 0}
        r = actions.act(self.client, "build_furniture", kind="Bed",
                        pos=(90, 80, 42), build_timeout=30.0)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.after["building"]["type"], "Bed")

    def test_failed_material_probe_is_transport(self):
        orig = actions._run_helper

        def _wrapped(client, name, params, timeout=30.0):
            if name == "probe_material.lua":
                return {"ok": False, "error": "probe boom"}
            return orig(client, name, params, timeout=timeout)

        with mock.patch.object(actions, "_run_helper",
                               side_effect=_wrapped):
            r = actions.act(self.client, "build_furniture", kind="Bed",
                            pos=(90, 80, 42), build_timeout=30.0)
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "transport")


class TestQueueJobMaterials(unittest.TestCase):
    """queue_job fails fast on a material shortage (general material
    awareness, 2026-11-27): the job is never queued, nothing is
    written, and the error names the exact gathering fix."""

    def setUp(self):
        self.game = FakeGame()
        self.client = _run_with_fake(self, self.game)
        self.game.buildings += [
            {"id": 7, "type": "Workshop", "subtype": "Carpenters",
             "jobs": 0},
            {"id": 8, "type": "Workshop", "subtype": "Still",
             "jobs": 0}]

    def _queued(self, name):
        return [c for c in self.game.calls if c[0] == name]

    def test_brew_short_on_plants_fails_fast(self):
        self.game.stocks["by_material"] = []
        r = actions.act(self.client, "queue_job", building_id=8,
                        job="brew")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")
        self.assertIn("designate_gather", r.reason)
        self.assertEqual(self._queued("act_job.lua"), [])

    def test_brew_short_on_barrels_names_make_barrel(self):
        self.game.stocks["empty_barrels"] = 0
        r = actions.act(self.client, "queue_job", building_id=8,
                        job="brew")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")
        self.assertIn("make_barrel", r.reason)
        self.assertIn("#7", r.reason)
        self.assertEqual(self._queued("act_job.lua"), [])

    def test_brew_x5_with_3_empty_barrels_fails_fast(self):
        r = actions.act(self.client, "queue_job", building_id=8,
                        job="brew", count=5)
        self.assertFalse(r.ok)
        self.assertIn("need 5", r.reason)
        self.assertIn("have 3", r.reason)
        self.assertEqual(self._queued("act_job.lua"), [])

    def test_make_bed_short_on_wood_fails_fast(self):
        self.game.stocks["wood_units"] = 0
        r = actions.act(self.client, "queue_job", building_id=7,
                        job="make_bed")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")
        self.assertIn("designate_chop", r.reason)
        self.assertEqual(self._queued("act_job.lua"), [])

    def test_queue_succeeds_when_stocked(self):
        r = actions.act(self.client, "queue_job", building_id=8,
                        job="brew", count=3)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(len(self._queued("act_job.lua")), 1)
        self.assertTrue(any(j["type"] == "CustomReaction"
                            for j in self.game.jobs))

    def test_queue_success_carries_building_kind(self):
        # The diary feed groups queued jobs by workshop; the kind
        # (the buildings list subtype) rides in the result detail
        # where the driver can read it for the decision phrase.
        r = actions.act(self.client, "queue_job", building_id=8,
                        job="brew", count=3)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.detail.get("building_kind"), "Still")
        r = actions.act(self.client, "queue_job", building_id=7,
                        job="make_bed")
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.detail.get("building_kind"), "Carpenters")

    def test_job_count_is_jobs_not_buildings(self):
        # Table 5 row 3: the before/after job_count fields used to
        # read the buildings count for before and the jobs count
        # for after — comparing two different things under one
        # label. Both now come from the jobs section. The fake has
        # 3 buildings (Wagon + 2 workshops) and 0 jobs before the
        # queue, so the old code would have reported before=3.
        r = actions.act(self.client, "queue_job", building_id=8,
                        job="brew", count=3)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.before, {"job_count": 0})
        self.assertEqual(r.after, {"job_count": 3})

    def test_negative_job_id_is_rejected(self):
        # 2026-11-27: the pre-fix helper returned [-1] (linkIntoWorld
        # with one arg is a no-op, so no id was ever assigned) and
        # the action layer reported ok — the game then crashed a few
        # ticks later processing the corrupt job. A -1 id is now a
        # verification failure, never "ok".
        orig = self.game.next_job_id
        self.game.next_job_id = -1
        r = actions.act(self.client, "queue_job", building_id=8,
                        job="brew", count=1)
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "verification")
        self.assertIn("-1", r.reason)
        self.game.next_job_id = orig


class TestQueueJobHolderRef(unittest.TestCase):
    """Every workshop job carries a BUILDING_HOLDER general_ref to
    its workshop (2026-11-27): without it the game segfaults when a
    dwarf claims and works the job — the root cause of the run
    #12/#13/#14 deaths. 3/3 advances died with a correctly-built
    job lacking the ref; 3/3 survived with it, and a bed job
    completed and produced a bed."""

    def setUp(self):
        self.game = FakeGame()
        self.client = _run_with_fake(self, self.game)
        self.game.buildings += [
            {"id": 7, "type": "Workshop", "subtype": "Carpenters",
             "jobs": 0},
            {"id": 8, "type": "Workshop", "subtype": "Still",
             "jobs": 0}]

    def test_queued_jobs_carry_holder_building_id(self):
        r = actions.act(self.client, "queue_job", building_id=8,
                        job="brew", count=3)
        self.assertTrue(r.ok, r.reason)
        queued = [j for j in self.game.jobs
                  if j["type"] == "CustomReaction"]
        self.assertEqual(len(queued), 3)
        self.assertTrue(all(j.get("holder_building_id") == 8
                            for j in queued))

    def test_helper_creates_holder_ref_and_verifies_it(self):
        # Regression guard on the real Lua: the ref must be created
        # and the helper must fail fast if getHolder does not return
        # the workshop, or a future edit could silently reintroduce
        # the crash.
        src = (actions._LUA_DIR / "act_job.lua").read_text()
        self.assertIn("general_ref_building_holderst", src)
        self.assertIn("ref.building_id = b.id", src)
        self.assertIn("job.general_refs:insert('#', ref)", src)
        self.assertIn("dfhack.job.getHolder(job)", src)
        self.assertIn("has no BUILDING_HOLDER ref", src)


class TestLuaHelpersSyntax(unittest.TestCase):
    """No Lua helper may contain a line starting with '#'
    (2026-11-27): a '#' comment line slipped into jobs.lua in
    1c0fd07 ('# (run #12): ...'), which is a Lua syntax error
    ('#' is the length operator, not a comment) — every jobs
    section read then failed, which broke queue_job verification
    and the snapshot. There is no Lua parser in the offline env,
    so this scans for the mistake directly: no helper line may
    start with optional whitespace followed by '#'."""

    def test_no_hash_comment_lines(self):
        bad = []
        for path in sorted(actions._LUA_DIR.glob("*.lua")):
            for i, line in enumerate(
                    path.read_text().splitlines(), 1):
                if re.match(r"^\s*#", line):
                    bad.append(f"{path.name}:{i}: {line.strip()}")
        self.assertEqual(bad, [])


class TestSiteFixHint(unittest.TestCase):
    # M1 run #5: the model retried the same shrub-blocked still
    # site twice because the error named the blocker but not the
    # fix. The hint names the fix.
    def test_shrub_blocker_names_gather_fix(self):
        hint = actions._site_fix_hint(
            ["tile 96,95 is SHRUB; plant at 96,95"])
        self.assertIn("designate_gather", hint)
        self.assertIn("96,95", hint)
        # M1 run #7 tick 4 retried the build before the gather
        # finished: the hint must say to wait for it.
        self.assertIn("wait for the gather to finish", hint)

    def test_unit_blocker_names_wait_or_move(self):
        hint = actions._site_fix_hint(["tile 97,95 has a unit"])
        self.assertIn("wait", hint)

    def test_other_blocker_names_different_site(self):
        hint = actions._site_fix_hint(["tile is solid rock"])
        self.assertIn("different free 3x3 site", hint)



class TestLabor(unittest.TestCase):
    def setUp(self):
        self.game = FakeGame()
        self.client = _run_with_fake(self, self.game)

    def test_toggle_by_name_roundtrip(self):
        r = actions.act(self.client, "labor_toggle",
                        unit="Deduk Stâkudunib", labor="CARPENTER", on=False)
        self.assertTrue(r.ok, r.reason)
        self.assertNotIn("CARPENTER", r.after["labors"])
        r2 = actions.act(self.client, "labor_toggle",
                         unit="Deduk Stâkudunib", labor="CARPENTER", on=True)
        self.assertTrue(r2.ok, r2.reason)
        self.assertIn("CARPENTER", r2.after["labors"])

    def test_toggle_by_id(self):
        r = actions.act(self.client, "labor_toggle", unit=1,
                        labor="MINE", on=False)
        self.assertTrue(r.ok, r.reason)
        self.assertNotIn("MINE", r.after["labors"])

    def test_toggle_unit_id_zero(self):
        # Table 5 row 4: unit id 0 is a real id — the old 0
        # sentinel ("look up by name") meant it could never be
        # targeted by id. The sentinel is now -1.
        self.game.citizens.append(
            {"id": 0, "name": "Zeroth Testdwarf",
             "labors": ["MINE"]})
        r = actions.act(self.client, "labor_toggle", unit=0,
                        labor="MINE", on=False)
        self.assertTrue(r.ok, r.reason)
        self.assertNotIn("MINE", r.after["labors"])
        self.assertEqual(r.detail["unit_id"], 0)
        self.assertEqual(r.detail["name"], "Zeroth Testdwarf")

    def test_unknown_citizen_is_precondition(self):
        r = actions.act(self.client, "labor_toggle", unit="Nobody Here",
                        labor="MINE", on=True)
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "precondition")


class TestActEntryPoint(unittest.TestCase):
    def setUp(self):
        self.game = FakeGame()
        self.client = _run_with_fake(self, self.game)

    def test_unknown_action_raises(self):
        with self.assertRaises(ValueError):
            actions.act(self.client, "teleport")

    def test_transport_failure_is_reported_not_raised(self):
        self.client.raise_transport = True
        r = actions.act(self.client, "designate_dig",
                        box=(90, 90, 41, 91, 91, 41), mode="dig")
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "transport")

    def test_missing_helper_key_is_transport_not_raised(self):
        # Table 5 row 5: a helper that returns ok without an
        # expected key (here: act_build with no "id") raised
        # KeyError, which escaped act()'s never-raise contract and
        # killed the caller. It is a transport failure now.
        with mock.patch.object(
                actions, "_helper_or_fail",
                return_value={"ok": True}):
            r = actions.act(self.client, "build_workshop",
                            kind="carpenter", pos=(85, 85, 42))
        self.assertFalse(r.ok)
        self.assertEqual(r.error_kind, "transport")

    def test_result_is_json_serializable(self):
        import json
        r = actions.act(self.client, "designate_dig",
                        box=(90, 90, 41, 91, 91, 41), mode="dig")
        json.dumps(r.to_dict())


class TestWaitForPausedTransport(unittest.TestCase):
    # _wait_for_paused tolerates transient transport failures
    # (2026-11-27): a farm task's finish wait died on a single 5 s
    # handshake timeout after ~350 s of healthy bursts, while the
    # game + RPC answered fine immediately after. Up to 3 consecutive
    # TransportErrors are retried with a 1 s backoff; a 4th — or a
    # RemoteError, which is a real answer from the server, not a
    # hiccup — propagates.
    def _run(self, failures, predicate_values, error=None):
        client = mock.Mock()
        calls = {"set": 0}

        def fake_set(c, paused):
            calls["set"] += 1
            if calls["set"] <= failures:
                raise (error or TransportError("boom"))

        values = list(predicate_values)
        with mock.patch.object(actions, "get_paused",
                               return_value=True), \
            mock.patch.object(actions, "set_paused",
                              side_effect=fake_set):
            return actions._wait_for_paused(
                client, lambda: values.pop(0) if values else None,
                timeout=30.0, burst=0.01)

    def test_two_transport_failures_then_success(self):
        self.assertEqual(
            self._run(2, [None, None, "done"]), "done")

    def test_three_transport_failures_raise(self):
        with self.assertRaises(TransportError):
            self._run(3, [None, None, None, None])

    def test_remote_error_is_not_retried(self):
        with self.assertRaises(RemoteError):
            self._run(1, [None, "done"],
                      error=RemoteError(-1, "refused"))


if __name__ == "__main__":
    unittest.main()
