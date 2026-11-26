"""Live integration tests for the digging gap (digging.py).

Runs against a real Dwarf Fortress 0.47.05 game on 127.0.0.1:5000 and
skips itself (does not fail) when no game is reachable. Set
DFH_TEST_LIVE=0 to force the skip even when a game is up.

Verifies, live on Erushtathtat (region2, Ilassil), all with paused
reads (no game time advances, no drink burns):
- The down-stair site at the fort centre (97, 97, z175, the floor)
  is reachable with no hazard.
- A down-stair on buried soil (97, 97, z174) is refused as
  unreachable — this is the exact designation that set the bits but
  never spawned a Dig job (verified live 2026-11-26).
- A down-stair over the aquifer column (176, 160) does not hit the
  aquifer in one level (it is 14 levels down), so it is not a hazard
  for a single down-stair.
- derive_dig_site from the real areas puts the stairs on the Surface
  near the fort centre.
- verify_dig on an undug site reports not complete (the terrain is
  still solid), so a false "complete" is impossible.

The end-to-end loop (dig_to_completion: job spawns + terrain
changes) IS run here, in TestLiveDigToCompletion — it needs unpaused
game time, and drink is at the watch threshold. It finds a fresh
FLOOR site at runtime (the fort-centre stair is already dug in the
save) and sets up a pick for the miner if he holds none (the fort
ships no pick). Root cause of the digging gap, fixed 2026-11-26:
act_dig did not set the map-block flags.designated bit, so the
game's sweep skipped the block and no Dig job was ever created; and
dig_to_completion waited only for Dig/DigChannel, but a down-stair
creates a CarveDownwardStaircase job.

Run from the repo root:

    .venv/bin/python -m unittest discover -s tests -v
"""

import http.client
import json
import os
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness import actions, digging  # noqa: E402
from dfagent_harness.events import EventBus  # noqa: E402
from dfagent_harness.server import create_server  # noqa: E402
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


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestLiveDigging(unittest.TestCase):
    """Verified live against the Erushtathtat fort (region2, Ilassil)."""

    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=180.0)
        cls.client.connect()
        cls.was_paused = actions.get_paused(cls.client)
        if not cls.was_paused:
            actions.set_paused(cls.client, True)
        cls.bus = EventBus()
        cls.server = create_server(
            cls.bus, host="127.0.0.1", port=0, client=cls.client)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        # Derive the areas once (a paused block scan, ~10 s) so the
        # area-derived site can be tested.
        conn = http.client.HTTPConnection("127.0.0.1", cls.port,
                                         timeout=180)
        conn.request("GET", "/v1/areas?refresh=1")
        resp = conn.getresponse()
        cls.areas = json.loads(resp.read())
        conn.close()
        assert resp.status == 200, cls.areas

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        if not cls.was_paused:
            actions.set_paused(cls.client, False)
        cls.client.close()

    def test_fort_centre_down_stair_is_ok(self):
        out = digging.check_dig_site(
            self.client, 97, 97, 175, "down-stair")
        self.assertTrue(out["ok"], out["reason"])
        self.assertTrue(out["reachable"])
        self.assertEqual(out["hazards"], [])

    def test_buried_soil_down_stair_is_refused(self):
        # The exact designation that never spawned a Dig job: a
        # down-stair on buried soil (z174) has no dwarf able to dig
        # it (no open sky above, no areas proving access).
        out = digging.check_dig_site(
            self.client, 97, 97, 174, "down-stair")
        self.assertFalse(out["ok"])
        self.assertIn("reach", out["reason"])

    def test_aquifer_column_single_stair_is_not_a_hazard(self):
        # The aquifer at (176, 160) is at z164, 14 levels below the
        # surface (z178) — a single down-stair does not reach it.
        out = digging.check_dig_site(
            self.client, 176, 160, 178, "down-stair")
        self.assertTrue(out["ok"], out["reason"])
        self.assertEqual(out["hazards"], [])

    def test_derive_dig_site_live(self):
        out = digging.derive_dig_site(self.areas, (97, 97), 175)
        x, y, z = out["stairs"]
        self.assertEqual(z, 175)
        # On the Surface near the fort centre.
        self.assertTrue(80 <= x <= 111 and 80 <= y <= 111)
        self.assertEqual(out["room"][2], 174)

    def test_verify_dig_undug_site_is_not_complete(self):
        out = digging.verify_dig(
            self.client, (97, 97, 175, 97, 97, 175), "down-stair")
        self.assertFalse(out["complete"])
        self.assertEqual(out["designations_left"], 0)
        self.assertFalse(out["terrain_ok"])

    def test_act_dig_shape_check_live(self):
        # A down-stair on the floor works; on buried soil it is
        # refused by the per-mode shape check (not a crash).
        r = actions.designate_dig(
            self.client, box=(97, 97, 175, 97, 97, 175),
            mode="down-stair")
        self.assertTrue(r.ok, r.reason)
        r2 = actions.designate_dig(
            self.client, box=(97, 97, 175, 97, 97, 175), mode="clear")
        self.assertTrue(r2.ok, r2.reason)
        with self.assertRaises(actions._Fail):
            actions.designate_dig(
                self.client, box=(97, 97, 174, 97, 97, 174),
                mode="down-stair")


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestLiveDigToCompletion(unittest.TestCase):
    """The end-to-end dig loop: designate a down-stair at a fresh
    floor site, wait for the Dig job to spawn, wait for the terrain
    to change, verify the stair. Needs unpaused game time, so it
    skips itself when drink is at the watch threshold (<= 8).

    Root cause of the digging gap, fixed live 2026-11-26: (1) act_dig
    did not set the map-block flags.designated bit, so the game's
    designation sweep skipped the block and no Dig job was ever
    created (verified: designation bit stuck at 5, zero jobs, zero
    postings over ~6,000 ticks); (2) dig_to_completion waited only
    for job types Dig/DigChannel, but a down-stair creates a
    CarveDownwardStaircase job, so it timed out even when the dwarf
    dug the tile. Both fixed; this test proves the loop end to end.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=180.0)
        cls.client.connect()
        cls.was_paused = actions.get_paused(cls.client)
        if not cls.was_paused:
            actions.set_paused(cls.client, True)

    @classmethod
    def tearDownClass(cls):
        if not cls.was_paused:
            actions.set_paused(cls.client, False)
        cls.client.close()

    def _find_floor_site(self, cx=97, cy=97, z=175, radius=10):
        """A FLOOR tile near the fort centre that is not yet dug."""
        from dfagent_harness.actions import _run_helper
        cands = []
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                cands.append((abs(dx) + abs(dy), cx + dx, cy + dy))
        cands.sort()
        for _, x, y in cands:
            out = _run_helper(self.client, "probe_block_flags.lua",
                              {"x": x, "y": y, "z": z})
            if (out.get("shape") == "FLOOR"
                    and (out.get("designation") or {}).get("dig") == 0):
                return (x, y, z)
        return None

    def _miner_has_pick(self):
        """True when the miner (id 5407) holds a pick.

        A pick is a WEAPON (df.item_type.WEAPON == 25, runtime enums)
        with subtype 6 (the weapon raws: subtype 6 = PICK).
        """
        from dfagent_harness.actions import _run_helper
        out = _run_helper(self.client, "probe_picks.lua", {})
        miner = out.get("miner") or {}
        # The Lua JSON encoder returns arrays as string-keyed dicts.
        invs = (list(miner.values()) if isinstance(miner, dict)
                else list(miner))
        for inv in invs:
            if inv.get("type") == 25 and inv.get("subtype") == 6:
                return True
        return False

    def test_dig_to_completion(self):
        # Drink gate: the loop unpauses the game in 1 s bursts.
        from dfagent_harness import observe
        from dfagent_harness.read_safety import paused_read
        s = paused_read(self.client, lambda: observe.collect(
            self.client, sections=("stocks",)))
        drink = (s.get("stocks") or {}).get("drink_units")
        if drink is None or drink <= 8:
            self.skipTest("drink %s at/below the watch threshold "
                          "(8) — not spending unpaused game time"
                          % drink)
        # The fort ships no pick (verified live: the embark brought
        # none, and the miner held a halberd and a spear). A Dig job
        # needs a pick, so spawn one and equip the miner if he has
        # none — the test sets up its own precondition.
        from dfagent_harness.actions import _run_helper
        if not self._miner_has_pick():
            spawned = _run_helper(self.client, "spawn_pick.lua",
                                  {"x": 97, "y": 95, "z": 175,
                                   "unit_id": 5407})
            self.assertTrue(spawned.get("ok"), str(spawned))
            equipped = _run_helper(self.client, "equip_pick.lua",
                                   {"unit_id": 5407})
            self.assertTrue(equipped.get("ok"), str(equipped))
            self.assertTrue(equipped.get("in_inventory"), str(equipped))
        site = self._find_floor_site()
        self.assertIsNotNone(site, "no undug FLOOR tile near the fort")
        box = (site[0], site[1], site[2], site[0], site[1], site[2])
        r = actions.dig_to_completion(
            self.client, box=box, mode="down-stair")
        self.assertTrue(r.ok, r.reason)
        # The terrain really changed: the floor is now a stair.
        v = digging.verify_dig(self.client, box, "down-stair")
        self.assertTrue(v["complete"], str(v))
        # The job that did it was a CarveDownwardStaircase (not Dig).
        self.assertEqual(
            (r.detail.get("job") or {}).get("type"),
            "CarveDownwardStaircase", str(r.detail))
        # The dug stair is left in place — it is the first step of
        # the real expansion dig, and the planner will use it.


if __name__ == "__main__":
    unittest.main()
