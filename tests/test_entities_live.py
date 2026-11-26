"""Live integration tests for the entity model (design §4).

Runs against a real Dwarf Fortress 0.47.05 game on 127.0.0.1:5000 and
skips itself (does not fail) when no game is reachable. Set
DFH_TEST_LIVE=0 to force the skip even when a game is up.

Verifies, live on Erushtathtat (region2, Ilassil):
- The units section classifies every active unit and reconciles:
  citizens + hostiles + wildlife + visitors + livestock equals
  total_active_units (no unit dropped silently).
- The compact records carry kind/role/pos, and wildlife carries the
  distance to the nearest citizen.
- /v1/units?kind=<...> filters by class, ?region= filters by box,
  and /v1/unit/<id> returns the full record for a unit of any class
  (citizen, wildlife, livestock) and 404 for an unknown id.

There are no traders or diplomats on the fort yet (fresh embark),
so the visitor role mapping is exercised by the generic fallback: a
troll arrived in the caverns on 2026-11-26 and is classified as a
visitor with role "visitor" (the remaining-humanoid cascade). The
merchant/diplomat/performer/scholar roles get their live exercise
when such a visitor arrives.
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
from dfagent_harness.observe import collect  # noqa: E402
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
class TestLiveEntities(unittest.TestCase):
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
                                          timeout=60)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, json.loads(body)

    def _fresh_units(self):
        """Re-collect the units section now (the game runs between
        tests, so a setUpClass snapshot goes stale: wildlife wanders
        in and out, and a visitor can arrive mid-suite — as one did
        on 2026-11-26, a troll in the caverns)."""
        return paused_read(
            self.client,
            lambda: collect(self.client, sections=("units",)))["units"]

    def test_reconciliation_holds(self):
        u = self._fresh_units()
        total = (u["citizen_count"] + u["hostile_count"]
                 + u["wildlife_count"] + u["visitor_count"]
                 + u["livestock_count"])
        self.assertEqual(total, u["total_active_units"],
                         "class counts do not sum to total_active_units")
        self.assertTrue(u["reconciled"])
        self.assertGreater(u["total_active_units"], 0)

    def test_citizens_and_livestock_present(self):
        u = self._fresh_units()
        self.assertEqual(u["citizen_count"], 7)
        self.assertGreater(u["livestock_count"], 0)
        self.assertEqual(u["hostile_count"], 0)
        # Visitors may arrive mid-suite (a troll did on 2026-11-26);
        # when one is present it must carry kind + role.
        for v in u["visitors"]:
            self.assertEqual(v["kind"], "visitor")
            self.assertIn("role", v)
            self.assertIn("purpose", v)

    def test_wildlife_has_distance_to_citizens(self):
        u = self._fresh_units()
        self.assertGreater(u["wildlife_count"], 0)
        for w in u["wildlife"]:
            self.assertEqual(w["kind"], "wildlife")
            self.assertIn("dist_nearest_citizen", w)
            self.assertIsInstance(w["dist_nearest_citizen"], int)
            self.assertGreaterEqual(w["dist_nearest_citizen"], 0)
        # The cavern wildlife is far from the surface citizens.
        self.assertTrue(all(
            w["dist_nearest_citizen"] >= 10 for w in u["wildlife"]))

    def test_counts_by_race(self):
        u = self._fresh_units()
        by_race = {r["race"]: r["count"]
                   for r in u["wildlife_by_race"]}
        self.assertEqual(sum(by_race.values()), u["wildlife_count"])
        self.assertIn("CRUNDLE", by_race)
        by_race = {r["race"]: r["count"]
                   for r in u["livestock_by_race"]}
        self.assertEqual(sum(by_race.values()), u["livestock_count"])
        self.assertIn("DOG", by_race)

    def test_units_kind_filter_live(self):
        u = self._fresh_units()
        status, data = self._get("/v1/units?kind=wildlife")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["count"], u["wildlife_count"])
        self.assertTrue(all(x["kind"] == "wildlife"
                            for x in data["units"]))
        status, data = self._get("/v1/units?kind=livestock")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["count"], u["livestock_count"])
        status, data = self._get("/v1/units?kind=visitors")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["count"], u["visitor_count"])
        self.assertTrue(all(x["kind"] == "visitor"
                            for x in data["units"]))

    def test_units_region_filter_live(self):
        # Surface wildlife only (z 170-181): the birds, not the
        # cavern creatures.
        u = self._fresh_units()
        status, data = self._get(
            "/v1/units?kind=wildlife&region=0,0,170,192,192,181")
        self.assertEqual(status, 200, data)
        self.assertGreater(data["count"], 0)
        self.assertLess(data["count"], u["wildlife_count"])
        self.assertTrue(all(170 <= x["pos"][2] <= 181
                            for x in data["units"]))

    def test_unit_full_record_by_class(self):
        u = self._fresh_units()
        # A livestock animal: full record, kind livestock, no owner
        # (a stray fort animal, not a personal pet).
        dog = u["livestock"][0]
        status, data = self._get(f"/v1/unit/{dog['id']}")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["kind"], "livestock")
        self.assertEqual(data["race"], dog["race"])
        self.assertIn("wound_count", data)
        # A wildlife unit: full record, kind wildlife.
        wild = u["wildlife"][0]
        status, data = self._get(f"/v1/unit/{wild['id']}")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["kind"], "wildlife")
        # A citizen: full record with profession and counters.
        citizen = u["citizens"][0]
        status, data = self._get(f"/v1/unit/{citizen['id']}")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["kind"], "citizen")
        self.assertIn("profession", data)
        self.assertIn("counters", data)

    def test_unit_unknown_is_404(self):
        status, data = self._get("/v1/unit/999999")
        self.assertEqual(status, 404)
        self.assertEqual(data["error"]["code"], "NOT_FOUND")
