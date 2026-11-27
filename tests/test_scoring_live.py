"""Live integration tests for the scoring system's wealth probe
(GOAL.md item 15).

Runs against a real Dwarf Fortress 0.47.05 game on 127.0.0.1:5000 and
skips itself (does not fail) when no game is reachable. Set
DFH_TEST_LIVE=0 to force the skip even when a game is up.

Verifies, live on Erushtathtat (region2, Ilassil):
- GET /v1/wealth returns the fortress value computed by lua/wealth.lua
  (IN_PLAY items, trader-held goods / ground items / abstract world
  artifacts excluded), with created_value, item_count, and the
  exclusion counts.
- The value is sane (a small embark fort: a few thousand ☼, not
  zero and not the wild-item total world.items.all would give).

The exact number is state-dependent (brews complete, items move), so
the test asserts shape and a sane range, not a fixed value. The
fixed-value verification (5410 ☼, created 5, 183 items on 125-04-02)
was done by hand against the live game and is recorded in
docs/SCORING.md.
"""
import http.client
import json
import os
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

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
class TestLiveWealth(unittest.TestCase):
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

    def test_wealth_route(self):
        status, body = self._get("/v1/wealth")
        self.assertEqual(status, 200, body)
        for key in ("fortress_value", "created_value", "item_count",
                    "excluded_ground", "excluded_trader"):
            self.assertIn(key, body, body)
        self.assertIsInstance(body["fortress_value"], int)
        self.assertIsInstance(body["created_value"], int)
        self.assertIsInstance(body["item_count"], int)
        # A small embark fort: a few thousand ☼ of value, not zero
        # (which would mean the probe read nothing) and not the
        # wild-item total (which would mean the exclusions failed).
        self.assertGreater(body["fortress_value"], 1000)
        self.assertLess(body["fortress_value"], 100000)
        self.assertGreater(body["item_count"], 0)
        self.assertGreaterEqual(body["created_value"], 0)
        self.assertLessEqual(body["created_value"],
                             body["fortress_value"])
        # Ground items are excluded (wild items lie on the ground);
        # trader-held goods are excluded (none on this fort yet).
        self.assertGreaterEqual(body["excluded_ground"], 0)
        self.assertGreaterEqual(body["excluded_trader"], 0)


if __name__ == "__main__":
    unittest.main()
