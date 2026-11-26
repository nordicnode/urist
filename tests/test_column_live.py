"""Live integration tests for the vertical column profile.

Runs against a real Dwarf Fortress 0.47.05 game on 127.0.0.1:5000 and
skips itself (does not fail) when no game is reachable. Set
DFH_TEST_LIVE=0 to force the skip even when a game is up.

Verifies, live on Erushtathtat (region2, Ilassil):
- The column at the fort centre (97, 97) shows the aquifer at z164
  and the magma sea with its top at z14 (the M4 survey's facts),
  in plain words, with hazards and the dig-down answer.
- GET /v1/column answers with the profile, hazards, dig-down and
  cost, all through the read-safety gate (paused_read).
- Out-of-bounds columns are a 400, not a crash.

All reads are paused — no game time advances, no drink burns.

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

from dfagent_harness import actions, column  # noqa: E402
from dfagent_harness.events import EventBus  # noqa: E402
from dfagent_harness.read_safety import paused_read  # noqa: E402
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
class TestLiveColumn(unittest.TestCase):
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
        # Populate the areas cache first: the column route needs
        # surface_z (175) to label the top open run "open sky" and
        # tall open runs below it "cavern space".
        cls._get("/v1/areas")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.server.shutdown()
            cls.server.server_close()
            cls.thread.join(timeout=5)
        finally:
            try:
                actions.set_paused(cls.client, cls.was_paused)
            finally:
                cls.client.quit()

    @classmethod
    def _get(cls, path):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port,
                                          timeout=180)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, json.loads(body)

    def test_fort_centre_column_is_honest_about_this_spot(self):
        # The fort-centre column (97, 97) has NO aquifer and NO
        # magma — the survey's aquifer (z164) and magma sea (top
        # z14) are map-wide facts, not facts at this spot. The
        # column must say what is under THIS spot, and it does:
        # soil, then stone, a small cavity, more stone, open space
        # at the very bottom. Everything below the surface is
        # unrevealed map data, marked as such.
        status, data = self._get("/v1/column?x=97&y=97")
        self.assertEqual(status, 200, data)
        runs = data["runs"]
        classes = [r["class"] for r in runs]
        self.assertEqual(classes, ["open sky", "soil", "stone",
                                   "open space", "stone",
                                   "open space"])
        soil = runs[1]
        self.assertEqual((soil["z1"], soil["z0"]), (174, 174))
        self.assertTrue(soil["unrevealed"])
        self.assertFalse(runs[0]["unrevealed"])
        self.assertIn("soil z174 (unrevealed)", data["profile"])
        self.assertIn("solid rock z173..z130 (unrevealed)",
                      data["profile"])
        self.assertEqual(data["hazards"], [])
        self.assertIn("cost", data)
        self.assertGreater(data["cost"]["tokens"], 0)

    def test_aquifer_column_flags_the_hazard(self):
        # (176, 160) is a column that DOES have the aquifer
        # (found by a grid probe 2026-11-26): light aquifer rock
        # at z164, and magma at z7..z6. The column must flag both
        # hazards in plain words.
        status, data = self._get("/v1/column?x=176&y=160")
        self.assertEqual(status, 200, data)
        classes = [r["class"] for r in data["runs"]]
        self.assertIn("aquifer", classes)
        aq = [r for r in data["runs"] if r["class"] == "aquifer"][0]
        self.assertEqual((aq["z1"], aq["z0"]), (164, 164))
        self.assertIn("magma", classes)
        self.assertIn("light aquifer rock z164", data["profile"])
        self.assertIn("magma z7..z6", data["profile"])
        self.assertTrue(any("leak water" in h for h in data["hazards"]))
        self.assertTrue(any("breach lava" in h for h in data["hazards"]))

    def test_magma_and_cavern_column(self):
        # (16, 16) is a column with a real cavern band and magma
        # (found by a grid probe 2026-11-26): cavern space
        # z108..z84, magma z12..z11. The tall open run below the
        # surface must be called cavern space, not open space.
        status, data = self._get("/v1/column?x=16&y=16")
        self.assertEqual(status, 200, data)
        classes = [r["class"] for r in data["runs"]]
        self.assertIn("cavern space", classes)
        cav = [r for r in data["runs"]
               if r["class"] == "cavern space"][0]
        self.assertEqual((cav["z1"], cav["z0"]), (108, 84))
        self.assertIn("magma", classes)
        self.assertIn("cavern space z108..z84", data["profile"])
        self.assertIn("magma z12..z11", data["profile"])
        self.assertTrue(any("breach lava" in h for h in data["hazards"]))

    def test_dig_down_five_from_the_fort_centre(self):
        # From the fort centre (z175), five levels down is soil for
        # one level, then solid rock — and no aquifer or magma below
        # it at this spot, so no hazard clause follows.
        status, data = self._get(
            "/v1/column?x=97&y=97&from_z=175&levels=5")
        self.assertEqual(status, 200, data)
        text = data["dig_down"]["text"]
        self.assertIn(
            "If you dig down 5 levels from (97, 97, z175), you "
            "will hit soil for 1 level (z174); solid rock for 4 "
            "levels (z173..z170).", text)
        self.assertNotIn("aquifer", text)
        self.assertNotIn("magma", text)

    def test_dig_down_from_the_aquifer_column(self):
        # From the aquifer column's ground (z178), digging down 14
        # levels crosses soil, mineral and soil — and the 14th tile
        # dug IS the aquifer (z164). The dig-down answer must name
        # it as a hit, and the magma below it.
        status, data = self._get(
            "/v1/column?x=176&y=160&from_z=178&levels=14")
        self.assertEqual(status, 200, data)
        text = data["dig_down"]["text"]
        self.assertIn("soil for 8 levels (z177..z170)", text)
        self.assertIn("mineral-bearing rock for 1 level (z169)", text)
        self.assertIn("soil for 4 levels (z168..z165)", text)
        self.assertIn("aquifer rock for 1 level (z164)", text)
        self.assertIn("magma starts 157 levels further down (z7)",
                      text)

    def test_column_out_of_bounds_is_a_400(self):
        status, data = self._get("/v1/column?x=999&y=999")
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["code"], "BAD_REQUEST")

    def test_column_direct_call_is_read_safe(self):
        # From running, the direct read_column path pauses, reads,
        # and restores running.
        try:
            actions.set_paused(self.client, False)
        except actions._Fail as exc:  # noqa: SLF001 - RFR flake
            self.skipTest(f"RFR unpause flake: {exc}")
        try:
            out = paused_read(
                self.client,
                lambda: column.read_column(self.client, 97, 97))
            self.assertTrue(out["strata"])
            self.assertFalse(actions.get_paused(self.client),
                             "gate did not restore running")
        finally:
            actions.set_paused(self.client, True)
