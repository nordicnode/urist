"""Tests for wiki lookup as a runtime tool (GOAL.md step 5,
guidance layer 6).

The agent asks the harness for DF knowledge; the harness answers
from the local DF wiki export (FTS + semantic indexes via dfq.py).
Hybrid is the best default for vague questions; plain FTS search
is the fast fallback.
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

from dfagent_harness import actions, wiki  # noqa: E402
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


class TestWikiOffline(unittest.TestCase):
    def test_search_returns_the_alcohol_page(self):
        # FTS search is fast and needs no model load.
        result = wiki.wiki_search("how to brew alcohol", mode="search",
                                  limit=3)
        self.assertIn("results", result)
        self.assertGreater(len(result["results"]), 0)
        self.assertEqual(result["results"][0]["slug"], "alcohol")
        self.assertIn("brewing", result["results"][0]["snippet"].lower())

    def test_unknown_mode_is_a_value_error(self):
        with self.assertRaises(ValueError):
            wiki.wiki_search("brewing", mode="bogus")

    def test_prefetch_maps_event_kinds(self):
        # A strange mood pre-fetches the strange-mood page.
        results = wiki.prefetch_for_event("strange_mood")
        self.assertGreater(len(results), 0)
        self.assertIn("strange", results[0]["title"].lower())
        # The kinds the attention system actually emits (2026-11-27):
        # low_drink / low_food are the fort's most common killers
        # and "hostile" is the briefing key for threat items — all
        # three returned [] before the mapping was added, so no wiki
        # context was ever pre-fetched for the events the model
        # faces every run.
        results = wiki.prefetch_for_event("low_drink")
        self.assertGreater(len(results), 0)
        self.assertIn("brew", " ".join(
            r.get("title", "") for r in results).lower())
        results = wiki.prefetch_for_event("low_food")
        self.assertGreater(len(results), 0)
        results = wiki.prefetch_for_event("hostile")
        self.assertGreater(len(results), 0)
        results = wiki.prefetch_for_event("threat")
        self.assertGreater(len(results), 0)
        # An unmapped kind returns nothing (no guess).
        self.assertEqual(wiki.prefetch_for_event("snapshot"), [])

    def test_page_dump(self):
        page = wiki.wiki_page("alcohol")
        self.assertEqual(page.get("slug"), "alcohol")
        self.assertGreater(len(page.get("text", "")), 1000)


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestWikiLive(unittest.TestCase):
    """The wiki route, served live (no game read — the wiki is
    local data, so this only needs the server up)."""

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
        cls.server.shutdown()
        cls.server.server_close()
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
        return resp.status, body

    def test_wiki_route_hybrid(self):
        status, body = self._get(
            "/v1/wiki?q=how%20to%20brew%20alcohol&limit=3")
        self.assertEqual(status, 200, body[:200])
        payload = json.loads(body)
        self.assertGreater(len(payload["results"]), 0)
        self.assertEqual(payload["results"][0]["slug"], "alcohol")

    def test_wiki_route_search_mode(self):
        status, body = self._get(
            "/v1/wiki?q=brewing&mode=search&limit=2")
        self.assertEqual(status, 200, body[:200])
        payload = json.loads(body)
        self.assertGreater(len(payload["results"]), 0)

    def test_wiki_route_missing_q_is_400(self):
        status, body = self._get("/v1/wiki")
        self.assertEqual(status, 400)

    def test_wiki_route_bad_mode_is_400(self):
        status, body = self._get("/v1/wiki?q=brewing&mode=bogus")
        self.assertEqual(status, 400)

    def test_wiki_page_route(self):
        status, body = self._get("/v1/wiki/alcohol")
        self.assertEqual(status, 200, body[:200])
        payload = json.loads(body)
        self.assertEqual(payload.get("slug"), "alcohol")


if __name__ == "__main__":
    unittest.main()
