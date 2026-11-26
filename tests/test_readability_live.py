"""Live readability check (standing directives 2026-11-26).

The world model is only as good as an AI can read it. This file
renders a slice, an area, an entity list, a column, and the survey
summary live on Erushtathtat and asserts that the seven questions
Mikey named are answerable from the output ALONE, without guessing
and without a second query:

- where is the nearest tree?
- what is in the cavern?
- how do I get from the surface to the cavern?
- what is directly below the fort?
- is there lava below us?
- is there an aquifer above us?
- if I dig down 5 levels from the fort centre, what do I hit?

"The data is present somewhere" is not "interpretable" — each
assertion checks that the answer is directly readable in the
rendered text. All reads are paused, so no game time advances and
no drink burns.

Runs against a real Dwarf Fortress 0.47.05 game on 127.0.0.1:5000
and skips itself (does not fail) when no game is reachable. Set
DFH_TEST_LIVE=0 to force the skip even when a game is up.
"""

import http.client
import json
import os
import re
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
class TestReadability(unittest.TestCase):
    """The seven questions, answered from the output alone."""

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
        # Render everything once, paused: the areas first (so the
        # slice can list the areas in its rect), then the slice,
        # the column, the survey summary, and the entity lists.
        cls.areas = cls._get("/v1/areas")[1]
        cls.slice = cls._get(
            "/v1/slice?x0=77&y0=77&z=175&x1=116&y1=116&layer=terrain")[1]
        cls.column = cls._get(
            "/v1/column?x=97&y=97&from_z=175&levels=5")[1]
        # The aquifer column (176, 160): the fort-centre column has
        # no aquifer or magma, so the hazard questions are answered
        # from this one (and the survey summary, which is map-wide).
        cls.aquifer_column = cls._get(
            "/v1/column?x=176&y=160&from_z=178&levels=14")[1]
        cls.survey = cls._get("/v1/survey")[1]
        cls.wildlife = cls._get("/v1/units?kind=wildlife")[1]

    @classmethod
    def _get(cls, path):
        conn = http.client.HTTPConnection("127.0.0.1", cls.port,
                                          timeout=180)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, json.loads(body)

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

    def test_nearest_tree_is_named_with_position(self):
        summary = "\n".join(self.survey["summary"])
        m = re.search(r"Nearest trees: (\w[\w ]+) \(\d+ on the map\) "
                      r"at \((\d+), (\d+), z(\d+)\), (\d+) tiles away",
                      summary)
        self.assertIsNotNone(m, "survey summary: " + summary)
        # And the slice shows the trees are really there.
        self.assertIn("trees", self.slice["summary"])

    def test_cavern_contents_are_stated(self):
        caverns = [a for a in self.areas["areas"]
                   if a["kind"] == "cavern"]
        self.assertTrue(caverns)
        desc = caverns[0]["description"]
        self.assertIn("Cavern", desc)
        self.assertIn("z19..z113", desc)
        self.assertIn("blocks", desc)
        self.assertIn("Nothing is built in it yet.", desc)

    def test_surface_to_cavern_path_is_honest(self):
        surface = [a for a in self.areas["areas"]
                   if a["kind"] == "surface"][0]
        cavern = [a for a in self.areas["areas"]
                  if a["kind"] == "cavern"][0]
        status, path = self._get(
            f"/v1/path?a={surface['id']}&b={cavern['id']}")
        self.assertEqual(status, 200)
        self.assertIsNone(path["path"])
        self.assertIn("dig a stairwell or tunnel", path["note"])
        self.assertIn("From the Surface: no path",
                      cavern["description"])

    def test_what_is_directly_below_the_fort(self):
        text = self.column["dig_down"]["text"]
        self.assertIn(
            "soil for 1 level (z174); solid rock for 4 levels "
            "(z173..z170)", text)
        self.assertIn("Below (z174):", self.slice["below_text"])
        # The level directly below the surface slice is the ground
        # layer: soil and solid rock, no water and no magma.
        self.assertEqual(self.slice["below"]["water"], 0)
        self.assertEqual(self.slice["below"]["magma"], 0)

    def test_lava_below_us_is_stated(self):
        summary = "\n".join(self.survey["summary"])
        self.assertIn("Magma:", summary)
        self.assertIn("161 levels below the fort", summary)
        # And the column at a spot that does have magma flags it.
        self.assertTrue(any("breach lava" in h
                            for h in self.aquifer_column["hazards"]))

    def test_aquifer_is_below_not_above(self):
        summary = "\n".join(self.survey["summary"])
        m = re.search(r"Aquifer: .*?, at z(\d+)", summary)
        self.assertIsNotNone(m, "survey summary: " + summary)
        # The aquifer (z164) is BELOW the fort (z175), not above it.
        self.assertLess(int(m.group(1)), 175)
        self.assertIn("light aquifer rock z164",
                      self.aquifer_column["profile"])
        self.assertTrue(any("leak water" in h
                            for h in self.aquifer_column["hazards"]))
        # Nothing above the fort is water: the slice's above level
        # has no water tiles.
        self.assertEqual(self.slice["above"]["water"], 0)

    def test_dig_down_five_from_the_fort_centre(self):
        text = self.column["dig_down"]["text"]
        self.assertIn(
            "If you dig down 5 levels from (97, 97, z175), you "
            "will hit soil for 1 level (z174); solid rock for 4 "
            "levels (z173..z170).", text)
        # No aquifer or magma at this spot — and the answer says
        # so by not naming either. The aquifer column, by contrast,
        # names the aquifer as the 14th tile dug.
        self.assertNotIn("aquifer", text)
        self.assertNotIn("magma", text)
        aq_text = self.aquifer_column["dig_down"]["text"]
        self.assertIn("aquifer rock for 1 level (z164)", aq_text)

    def test_slice_is_locatable_and_landmarked(self):
        labeled = self.slice["grid_labeled"]
        self.assertEqual(len(labeled), 42)  # 2 rulers + 40 rows
        self.assertTrue(labeled[2].startswith(" 77 "))
        # The fort centre is marked on the grid.
        self.assertIn("F", "\n".join(labeled))
        marks = [m for m in self.slice["markers"]
                 if m.get("char") == "F"]
        self.assertEqual(len(marks), 1)
        self.assertIn("fort centre", marks[0]["what"])
        self.assertIn("Surface", [a["name"] for a in
                                  self.slice["areas_in_rect"]])

    def test_entities_are_self_describing(self):
        units = self.wildlife["units"]
        self.assertTrue(units)
        for u in units[:5]:
            self.assertIn("description", u)
            self.assertIn("wild animal", u["description"])
            self.assertIn("at (", u["description"])
