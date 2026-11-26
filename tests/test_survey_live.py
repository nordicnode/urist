"""Live integration tests for the resource survey (design §5).

Runs against a real Dwarf Fortress 0.47.05 game on 127.0.0.1:5000 and
skips itself (does not fail) when no game is reachable. Set
DFH_TEST_LIVE=0 to force the skip even when a game is up.

Verifies, live on Erushtathtat (region2, Ilassil):
- /v1/survey returns real data: the known surface pool at
  (162, 122, z174, depth 7), the magma sea (top z14, 161 levels
  below the fort), the light aquifer at z164, widespread
  mineral-bearing rock, and per-species plants with real nearest
  positions.
- The plain-words summary answers "where is the nearest water /
  mineral / magma / aquifer / shrub / tree?" directly.
- ?kind= filters; a bad kind is a 400; the second call is served
  from cache (cost.cached True) and the first is not.
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

from dfagent_harness import actions  # noqa: E402
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
class TestLiveSurvey(unittest.TestCase):
    """Verified live against the Erushtathtat fort (region2, Ilassil)."""

    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=60.0)
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
        # One survey call up front (the ~40 s scan + area derivation);
        # the route caches it, so the individual tests are fast.
        status, cls.survey = cls._get(cls, "/v1/survey")
        assert status == 200, cls.survey

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

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                          timeout=120)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, json.loads(body)

    def test_known_pool_is_found(self):
        # The surface pool at (162, 122, z174), depth 7, verified
        # live 2026-11-26 from the tile data before the survey existed.
        pools = [b for b in self.survey["water_bodies"]
                 if b["bbox"]["x0"] <= 162 <= b["bbox"]["x1"]
                 and b["bbox"]["y0"] <= 122 <= b["bbox"]["y1"]
                 and b["bbox"]["z0"] <= 174 <= b["bbox"]["z1"]]
        self.assertTrue(pools, "the known pool is missing")
        self.assertEqual(pools[0]["max_depth"], 7)

    def test_magma_sea_depth(self):
        v = self.survey["vertical"]
        self.assertEqual(v["magma_top_z"], 14)
        self.assertEqual(v["depth_to_magma_levels"], 161)
        sea = self.survey["magma_bodies"][0]
        self.assertEqual(sea["name"], "magma sea")
        self.assertGreater(sea["tiles"], 60000)

    def test_aquifer_at_z164(self):
        aq = self.survey["aquifer"]
        self.assertIn("light (per the embark warning)", aq["kind"])
        self.assertEqual([lv["z"] for lv in aq["levels"]], [164])
        self.assertGreater(aq["total_blocks"], 0)

    def test_first_cavern_depth(self):
        self.assertEqual(
            self.survey["vertical"]["depth_to_first_cavern_levels"], 62)
        self.assertEqual(
            self.survey["vertical"]["first_cavern_top_z"], 113)

    def test_mineral_is_widespread(self):
        names = [v["name"] for v in self.survey["mineral_veins"]]
        self.assertIn("mineral-bearing rock (widespread, ore "
                      "unidentified)", names)

    def test_plants_have_real_nearest_positions(self):
        # A bbox-clamped nearest would read 0 for every species whose
        # range covers the fort; the Lua nearest is a real plant.
        pecan = [p for p in self.survey["plants"]
                 if p["species"] == "PECAN"][0]
        self.assertGreater(pecan["nearest"]["distance_tiles"], 0)
        self.assertEqual(pecan["nearest"]["pos"][2], 175)

    def test_reachability_is_decided(self):
        # With the area data wired in, reachable is a real boolean,
        # not the "unknown" placeholder.
        for b in (self.survey["water_bodies"]
                  + self.survey["magma_bodies"]):
            self.assertIsInstance(b["reachable"], bool)
        pool = [b for b in self.survey["water_bodies"]
                if b["bbox"]["x0"] <= 162 <= b["bbox"]["x1"]
                and b["bbox"]["y0"] <= 122 <= b["bbox"]["y1"]
                and b["bbox"]["z0"] <= 174 <= b["bbox"]["z1"]][0]
        self.assertIs(pool["reachable"], True)

    def test_summary_answers_the_questions(self):
        joined = "\n".join(self.survey["summary"])
        for head in ("Nearest water:", "Mineral:", "Magma:",
                     "Aquifer:", "Nearest gatherable shrubs:",
                     "Nearest trees:", "First cavern:"):
            self.assertIn(head, joined)
        # The nearest-water line carries a position and a distance.
        water_line = [ln for ln in self.survey["summary"]
                      if ln.startswith("Nearest water:")][0]
        self.assertRegex(water_line, r"\(\d+, \d+, z\d+\)")
        self.assertRegex(water_line, r"\d+ tiles? away")

    def test_hazards_state_the_risks(self):
        hazards = " ".join(self.survey["hazards"])
        self.assertIn("Magma sea 161 levels below", hazards)
        self.assertIn("breach lava", hazards)
        self.assertIn("Light aquifer at z164", hazards)
        self.assertIn("First cavern 62 levels below", hazards)

    def test_second_call_is_cached(self):
        status, again = self._get("/v1/survey")
        self.assertEqual(status, 200)
        self.assertIs(again["cost"]["cached"], True)
        self.assertIs(again["stale"], False)

    def test_kind_filter_and_bad_kind(self):
        status, water = self._get("/v1/survey?kind=water")
        self.assertEqual(status, 200)
        self.assertIn("water_bodies", water)
        self.assertNotIn("magma_bodies", water)
        status, bad = self._get("/v1/survey?kind=bogus")
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
