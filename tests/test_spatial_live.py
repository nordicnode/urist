"""Live integration tests for the spatial model (design §3).

Runs against a real Dwarf Fortress 0.47.05 game on 127.0.0.1:5000 and
skips itself (does not fail) when no game is reachable. Set
DFH_TEST_LIVE=0 to force the skip even when a game is up.

Verifies, live on Erushtathtat (region2, Ilassil):
- A terrain slice returns real ground (grass, trees, shrubs, hidden
  rock) with a stated cost, and the water layer finds the pool below
  the surface (flow_size > 0, verified by probe).
- The full block scan + area derivation find the surface (holding the
  fort centre) and at least one large cavern, with a connectivity
  graph. The surface and the caverns are not connected (nothing has
  been dug), so /v1/path between them returns path=None with the
  honest note.
- The HTTP routes /v1/slice, /v1/areas, /v1/area/<id>, /v1/path
  answer with real data and stated costs, all through the read-safety
  gate (paused_read).

Room/stockpile/workshop labelling is verified offline
(tests/test_spatial.py) with realistic building records; the live
fort has no buildings yet, so those labels get their live exercise
when the fort has them (step 2 / the M1 live run).

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

from dfagent_harness import actions, spatial  # noqa: E402
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
class TestLiveSpatial(unittest.TestCase):
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
                                          timeout=180)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, json.loads(body)

    def test_slice_terrain_returns_real_ground(self):
        status, data = self._get(
            "/v1/slice?x0=77&y0=77&z=175&x1=116&y1=116&layer=terrain")
        self.assertEqual(status, 200, data)
        self.assertEqual(len(data["grid"]), 40)
        self.assertEqual(len(data["grid"][0]), 40)
        text = "\n".join(data["grid"])
        # Real ground: grass floor, trees, shrubs, hidden rock.
        self.assertIn(".", text)
        self.assertIn("T", text)
        self.assertIn("*", text)
        self.assertGreater(data["hidden"], 0)
        self.assertIn("cost", data)
        self.assertGreater(data["cost"]["tokens"], 0)
        self.assertIn("ms", data["cost"])
        self.assertIn("summary", data)
        self.assertIn("legend", data)

    def test_slice_water_layer_finds_the_pool(self):
        # The pool below the surface (z=174, around (162,122)) was
        # verified by probe: flow_size 7, liquid water. A water-layer
        # slice there must show '~'.
        status, data = self._get(
            "/v1/slice?x0=150&y0=110&z=174&x1=175&y1=135&layer=water")
        self.assertEqual(status, 200, data)
        text = "\n".join(data["grid"])
        self.assertIn("~", text, "water layer shows no water")
        self.assertNotIn("#", text,
                         "water layer must not show walls")

    def test_slice_rejects_an_oversize_rect(self):
        status, data = self._get(
            "/v1/slice?x0=0&y0=0&z=175&x1=100&y1=100&layer=terrain")
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["code"], "BAD_REQUEST")

    def test_areas_find_surface_and_caverns(self):
        status, data = self._get("/v1/areas")
        self.assertEqual(status, 200, data)
        areas = data["areas"]
        self.assertGreater(len(areas), 0)
        kinds = {a["kind"] for a in areas}
        self.assertIn("surface", kinds)
        self.assertIn("cavern", kinds)
        surface = [a for a in areas if a["kind"] == "surface"][0]
        # The surface holds the fort centre (a citizen stands in it).
        self.assertGreater(surface["blocks"], 100)
        caverns = [a for a in areas if a["kind"] == "cavern"]
        self.assertGreater(caverns[0]["blocks"], 100)
        # Every area states its cost and staleness.
        self.assertIn("cost", data)
        self.assertIn("stale", data)
        self.assertFalse(data["stale"])
        self.assertIn("graph", data)
        self.assertIn("derived_at_tick", data)
        # The per-tick snapshot's area list (max 15) is derivable.
        lines = spatial.area_summary(areas)
        self.assertLessEqual(len(lines), 15)
        self.assertTrue(any("Surface" in ln for ln in lines))

    def test_area_detail_returns_a_slice(self):
        _status, data = self._get("/v1/areas")
        surface = [a for a in data["areas"]
                   if a["kind"] == "surface"][0]
        status, detail = self._get(f"/v1/area/{surface['id']}")
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["area"]["id"], surface["id"])
        self.assertEqual(detail["area"]["kind"], "surface")
        self.assertIn("grid", detail["slice"])
        self.assertIn("cost", detail["slice"])

    def test_path_between_unconnected_areas_is_honest(self):
        _status, data = self._get("/v1/areas")
        surface = [a for a in data["areas"]
                   if a["kind"] == "surface"][0]
        cavern = [a for a in data["areas"]
                  if a["kind"] == "cavern"][0]
        status, path = self._get(
            f"/v1/path?a={surface['id']}&b={cavern['id']}")
        self.assertEqual(status, 200, path)
        # Nothing has been dug: the cavern is sealed off, so there is
        # no path — and the response says so instead of inventing one.
        self.assertIsNone(path["path"])
        self.assertIn("note", path)

    def test_slice_direct_call_is_read_safe(self):
        # The direct render_slice path also goes through paused_read:
        # from running, it pauses, reads, and restores running.
        try:
            actions.set_paused(self.client, False)
        except actions._Fail as exc:  # noqa: SLF001 - RFR flake
            self.skipTest(f"RFR unpause flake: {exc}")
        try:
            out = paused_read(
                self.client,
                lambda: spatial.render_slice(
                    self.client, 77, 77, 175, 116, 116))
            self.assertEqual(len(out["grid"]), 40)
            self.assertFalse(actions.get_paused(self.client),
                             "gate did not restore running")
        finally:
            actions.set_paused(self.client, True)

    def test_slice_has_rulers_landmarks_and_above_below(self):
        # Interpretability pass: coordinate rulers, the fort-centre
        # landmark, the areas in the rect, and what is directly
        # above and below the slice. The areas first, so the slice
        # can list the areas in its rect.
        self._get("/v1/areas")
        status, data = self._get(
            "/v1/slice?x0=77&y0=77&z=175&x1=116&y1=116&layer=terrain")
        self.assertEqual(status, 200, data)
        labeled = data["grid_labeled"]
        self.assertEqual(len(labeled), 42)  # 2 rulers + 40 rows
        self.assertTrue(labeled[0].startswith("    777"))
        self.assertTrue(labeled[2].startswith(" 77 "))
        # The fort centre (97, 97, z175) is in the rect.
        marks = [m for m in data["markers"] if m["char"] == "F"]
        self.assertEqual(len(marks), 1)
        self.assertEqual((marks[0]["x"], marks[0]["y"]), (97, 97))
        self.assertIn("fort centre", marks[0]["what"])
        self.assertIn("F", "\n".join(labeled))
        # Areas in the rect (from the cache — the areas test above
        # ran first and populated it).
        self.assertIn("areas_in_rect", data)
        self.assertTrue(any(a["kind"] == "surface"
                            for a in data["areas_in_rect"]))
        # Above and below are stated in plain words. The level
        # directly below the surface slice is all unrevealed rock
        # — the slice is honest about that and routes the agent to
        # the column probe for the geology (the column, not the
        # slice, answers what is actually down there).
        self.assertIn("Below (z174):", data["below_text"])
        self.assertIn("1600 hidden (unrevealed) tiles",
                      data["below_text"])
        self.assertIn("use /v1/column", data["below_text"])
        self.assertIn("Above (z176):", data["above_text"])
        self.assertIn("below", data["summary"].lower())
        self.assertIn("above", data["summary"].lower())

    def test_overview_shows_the_shape_of_the_world(self):
        status, data = self._get("/v1/overview")
        self.assertEqual(status, 200, data)
        # 13 block rows of z (197 levels / 16), top first.
        self.assertEqual(len(data["cross_section"]), 13)
        self.assertEqual(len(data["top_down"]), 12)
        # The fort's block, the magma sea at the bottom, and open
        # cavern bands deep down are all visible at a glance.
        flat = "\n".join(data["cross_section"])
        self.assertIn("F", flat)
        self.assertIn("!", data["cross_section"][-1])
        self.assertIn(".", flat)
        self.assertIn("summary", data)
        self.assertIn("cost", data)

    def test_areas_carry_plain_words_descriptions(self):
        # The survey first: area descriptions are enriched with
        # its vertical facts (magma, aquifer) only when it is
        # cached.
        self._get("/v1/survey")
        status, data = self._get("/v1/areas")
        self.assertEqual(status, 200, data)
        self.assertIn("summary", data)
        self.assertTrue(any("Surface" in ln for ln in data["summary"]))
        for a in data["areas"]:
            self.assertIn("description", a)
            self.assertIn(a["name"], a["description"])
            self.assertIn("spans x", a["description"])
        surface = [a for a in data["areas"]
                   if a["kind"] == "surface"][0]
        self.assertIn("Above it is open sky.", surface["description"])
        self.assertIn("magma sea", surface["description"])
        cavern = [a for a in data["areas"]
                  if a["kind"] == "cavern"][0]
        self.assertIn("From the Surface: no path",
                      cavern["description"])
        self.assertIn("magma sea", cavern["description"])
