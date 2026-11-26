"""Live integration tests for the Context Assembler + /v1/snapshot.

Runs against a real Dwarf Fortress 0.47.05 game on 127.0.0.1:5000 and
skips itself (does not fail) when no game is reachable. Set
DFH_TEST_LIVE=0 to force the skip even when a game is up.

Verifies, live on Erushtathtat (region2, Ilassil):
- GET /v1/snapshot answers with the assembled per-tick snapshot:
  all sections, a token count within the 30K target, the fort name
  and date in the text, and the tick matching the game.
- A second call diffs against the Store: unchanged sections render
  as one-liners and the token count drops.
- The snapshot is recorded in the Store (snapshots table).
- With drink at 9 (below the warn threshold) the suggestion names
  the brew task.

All reads are paused — no game time advances, no drink burns.

Run from the repo root:

    .venv/bin/python -m unittest discover -s tests -v
"""

import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness import actions  # noqa: E402
from dfagent_harness.assembler import TARGET_TOKENS  # noqa: E402
from dfagent_harness.events import EventBus  # noqa: E402
from dfagent_harness.server import create_server  # noqa: E402
from dfagent_harness.store import Store  # noqa: E402
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


class _FakeDaemon:
    """A daemon stub carrying only the Store the snapshot route
    needs (so the test uses a temp world.db, not the real one)."""

    def __init__(self, store):
        self.store = store


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestLiveSnapshot(unittest.TestCase):
    """Verified live against the Erushtathtat fort (region2, Ilassil)."""

    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=180.0)
        cls.client.connect()
        cls.was_paused = actions.get_paused(cls.client)
        if not cls.was_paused:
            actions.set_paused(cls.client, True)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.store = Store(Path(cls.tmp.name) / "world.db")
        cls.bus = EventBus()
        cls.server = create_server(
            cls.bus, host="127.0.0.1", port=0, client=cls.client,
            daemon=_FakeDaemon(cls.store))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.store.close()
        cls.tmp.cleanup()
        if not cls.was_paused:
            actions.set_paused(cls.client, False)
        cls.client.close()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                         timeout=120)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, json.loads(body)

    def test_snapshot_route(self):
        status, snap = self._get("/v1/snapshot")
        self.assertEqual(status, 200, snap)
        self.assertIn("tick", snap)
        self.assertIn("tokens", snap)
        self.assertIn("sections", snap)
        self.assertIn("text", snap)
        self.assertGreater(snap["tokens"], 0)
        self.assertLessEqual(snap["tokens"], TARGET_TOKENS)
        for name in ("header", "attention", "goals", "status",
                     "stocks", "units", "entities", "buildings",
                     "jobs", "reports", "areas", "events",
                     "history"):
            self.assertIn(name, snap["sections"], name)
        self.assertIn("Erushtathtat", snap["text"])
        self.assertIn("125-06-02", snap["text"])
        # The tick matches the game (/v1/status carries it at the
        # top level).
        status2, state = self._get("/v1/status")
        self.assertEqual(status2, 200)
        self.assertEqual(snap["tick"], state["tick"])

    def test_snapshot_diffs_second_call(self):
        _, first = self._get("/v1/snapshot")
        _, second = self._get("/v1/snapshot")
        self.assertEqual(first["tick"], second["tick"])
        # Unchanged sections render as one-liners.
        for name in ("header", "status", "stocks", "units",
                     "entities", "buildings", "jobs", "reports"):
            self.assertIn("unchanged",
                          second["sections"].get(name, ""), name)
        # The diffed snapshot costs fewer tokens.
        self.assertLess(second["tokens"], first["tokens"])

    def test_snapshot_recorded_in_store(self):
        self._get("/v1/snapshot")
        prev = self.store.get_snapshot("stocks")
        self.assertIsNotNone(prev)
        self.assertIn("drink", prev["text"])

    def test_snapshot_suggests_brew_when_drink_low(self):
        _, snap = self._get("/v1/snapshot")
        # Drink is 9 (below the warn threshold of 20): the one
        # suggested action is the brew task.
        self.assertIsNotNone(snap.get("suggestion"))
        self.assertIn("brew", snap["suggestion"])


if __name__ == "__main__":
    unittest.main()
