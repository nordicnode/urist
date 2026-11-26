"""Offline tests for the entity model (world-model design §4).

The Lua classification (isCitizen / isAnimal / isTame / hostile) is
verified live (tests/test_entities_live.py); these tests cover the
Python side — the /v1/units kind + region filters and the
reconciliation fields — with a stub poller state, no game required.
"""

import http.client
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.events import EventBus  # noqa: E402
from dfagent_harness.server import create_server  # noqa: E402


def _unit(uid, race, pos, kind="wildlife"):
    return {"id": uid, "name": "", "race": race, "pos": pos,
            "kind": kind, "role": "wild"}


class _StubPoller:
    def __init__(self, state):
        self.last_state = state


class TestUnitsFilters(unittest.TestCase):
    def setUp(self):
        self.state = {
            "units": {
                "citizens": [
                    {"id": 1, "name": "A", "race": "DWARF",
                     "pos": [10, 10, 175], "profession": "Miner"},
                    {"id": 2, "name": "B", "race": "DWARF",
                     "pos": [20, 20, 175], "profession": "Mason"},
                ],
                "hostiles": [
                    {"id": 3, "name": "", "race": "GOBLIN",
                     "pos": [15, 15, 175]},
                ],
                "wildlife": [
                    _unit(4, "CRUNDLE", [12, 12, 175]),
                    _unit(5, "DRALTHA", [50, 50, 120]),
                    _unit(6, "BIRD_TURKEY", [11, 11, 175]),
                ],
                "visitors": [
                    {"id": 7, "name": "C", "race": "HUMAN",
                     "pos": [10, 10, 175], "kind": "visitor",
                     "role": "merchant", "purpose": "trading"},
                ],
                "livestock": [
                    _unit(8, "DOG", [10, 10, 175], kind="livestock"),
                    _unit(9, "CAT", [30, 30, 175], kind="livestock"),
                ],
                "total_active_units": 9,
                "reconciled": True,
            }
        }
        self.server = create_server(
            EventBus(), host="127.0.0.1", port=0,
            poller=_StubPoller(self.state))
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                          timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, json.loads(body)

    def test_kind_wildlife(self):
        status, data = self._get("/v1/units?kind=wildlife")
        self.assertEqual(status, 200)
        self.assertEqual(data["count"], 3)
        self.assertEqual({u["race"] for u in data["units"]},
                         {"CRUNDLE", "DRALTHA", "BIRD_TURKEY"})

    def test_kind_livestock_and_visitors(self):
        _, data = self._get("/v1/units?kind=livestock")
        self.assertEqual(data["count"], 2)
        _, data = self._get("/v1/units?kind=visitors")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["units"][0]["role"], "merchant")

    def test_kind_bad_is_400(self):
        status, data = self._get("/v1/units?kind=bogus")
        self.assertEqual(status, 400)
        self.assertEqual(data["error"]["code"], "BAD_REQUEST")

    def test_region_filter(self):
        # Only the surface wildlife (z=175, near the fort) match.
        _, data = self._get(
            "/v1/units?kind=wildlife&region=0,0,170,192,192,181")
        self.assertEqual(data["count"], 2)
        self.assertEqual({u["race"] for u in data["units"]},
                         {"CRUNDLE", "BIRD_TURKEY"})
        # The deep cavern wildlife is outside the region.
        _, data = self._get(
            "/v1/units?kind=wildlife&region=0,0,100,192,192,130")
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["units"][0]["race"], "DRALTHA")

    def test_region_bad_is_400(self):
        status, _ = self._get("/v1/units?kind=wildlife&region=1,2,3")
        self.assertEqual(status, 400)

    def test_limit(self):
        _, data = self._get("/v1/units?kind=wildlife&limit=1")
        self.assertEqual(len(data["units"]), 1)
        self.assertEqual(data["count"], 3)

    def test_default_is_citizens_plus_hostiles(self):
        _, data = self._get("/v1/units")
        self.assertEqual(data["count"], 3)
        self.assertEqual({u["id"] for u in data["units"]}, {1, 2, 3})

    def test_reconciliation_fields(self):
        _, data = self._get("/v1/units?kind=wildlife")
        self.assertEqual(data["total_active_units"], 9)
        self.assertTrue(data["reconciled"])


if __name__ == "__main__":
    unittest.main()
