"""Cold-cache placement derivation tests (offline, fake client).

M1 run #11 tick 1 (2026-11-27): the daemon had restarted minutes
before the run, the areas cache was empty, and get_placement /
_derive_sites returned empty instead of warming the areas — the
snapshot's placement section was empty and the model burned an idle
tick asking for coordinates. Both methods must now warm the areas on
demand (via server.get_areas) when the cache is cold, instead of
returning empty. These tests pin that behaviour with a fake server
whose spatial cache starts cold.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_placement import _FakeClient  # noqa: E402

from dfagent_harness.daemon import Daemon  # noqa: E402


class _PausedStub:
    """RFR SingleBool stand-in: the fake game is always paused."""
    Value = True


class _FakeClientPausable(_FakeClient):
    """_FakeClient plus the RFR ``call`` path (GetPauseState) that
    paused_read needs before any collect."""

    def call(self, name, msg, response_type=None):
        return _PausedStub(), ""


def _areas_dict():
    return {
        "areas": [{
            "id": "area_0001", "name": "Surface", "kind": "surface",
            "blocks": 586,
            "bbox": {"x0": 0, "y0": 0, "z0": 175,
                     "x1": 191, "y1": 191, "z1": 175},
        }],
        "surface_z": 175,
        "graph": {},
    }


def _state():
    return {
        "buildings": {"list": [
            {"id": 7, "type": "Workshop", "subtype": "Carpenters",
             "pos": [93, 105, 175]}]},
        "units": {"citizens": [
            {"id": 1, "pos": [94, 106, 175]},
            {"id": 2, "pos": [95, 107, 175]}]},
    }


class _FakeServer:
    """server.get_areas warms the spatial cache on first call."""

    def __init__(self, areas):
        self.spatial_cache = {"areas": None}
        self._areas = areas
        self.warm_calls = 0

    def get_areas(self, refresh=False):
        self.warm_calls += 1
        self.spatial_cache["areas"] = self._areas
        return self._areas


def _daemon(server, client):
    d = Daemon.__new__(Daemon)
    d.server = server
    d.client = client
    d._placement_cache = None
    d._placement_cache_at = 0.0
    return d


class TestDeriveSitesColdCache(unittest.TestCase):
    def test_derive_sites_warms_areas_on_demand(self):
        server = _FakeServer(_areas_dict())
        d = _daemon(server, _FakeClientPausable())
        out = d._derive_sites(_state())
        self.assertEqual(server.warm_calls, 1,
                         "cold cache must trigger one areas warm")
        self.assertIsNotNone(out, "warmed derivation must return sites")
        self.assertTrue(out["workshop_sites"],
                        "workshop sites must be derived, not empty")
        self.assertIsNotNone(d._placement_cache)
        self.assertTrue(d._placement_cache["workshop"],
                        "placement cache must be warmed too")

    def test_derive_sites_no_server_returns_none_not_a_guess(self):
        d = _daemon(None, _FakeClientPausable())
        self.assertIsNone(d._derive_sites(_state()))


class TestGetPlacementColdCache(unittest.TestCase):
    def test_get_placement_warms_areas_on_demand(self):
        server = _FakeServer(_areas_dict())
        d = _daemon(server, _FakeClientPausable())
        out = d.get_placement("workshop", 3, 3)
        self.assertEqual(server.warm_calls, 1,
                         "cold cache must trigger one areas warm")
        self.assertTrue(out["sites"], "warmed search must find sites")
        self.assertNotEqual(out.get("cached"), True,
                            "a warmed result is fresh, not cached")
        for site in out["sites"]:
            self.assertTrue(site["reachable"])

    def test_get_placement_no_server_returns_empty_with_reason(self):
        d = _daemon(None, _FakeClientPausable())
        out = d.get_placement("workshop", 3, 3)
        self.assertEqual(out["sites"], [])
        self.assertIn("reason", out)


if __name__ == "__main__":
    unittest.main()
