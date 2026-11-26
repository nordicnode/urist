"""Tests for situation briefings (GOAL.md step 5, layer 5).

When an event fires, it carries a short briefing: what this is,
what usually matters, the options, and the cost of ignoring it.
The briefing text is static (curated from the DF wiki); the wiki
references are the top pages for the event kind, fetched once and
cached.
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

from dfagent_harness import actions, attention, briefings  # noqa: E402
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


class TestBriefingsOffline(unittest.TestCase):
    def setUp(self):
        briefings.clear_wiki_cache()

    def test_known_kind_has_all_four_fields(self):
        b = briefings.brief_for("new_arrival")
        self.assertIsNotNone(b)
        for field in ("what", "matters", "options", "cost"):
            self.assertIn(field, b)
            self.assertGreater(len(b[field]), 20)
        self.assertEqual(b["kind"], "new_arrival")

    def test_wiki_refs_are_real_pages(self):
        b = briefings.brief_for("strange_mood")
        self.assertIn("wiki", b)
        self.assertGreater(len(b["wiki"]), 0)
        slugs = [w["slug"] for w in b["wiki"]]
        self.assertIn("strange-mood", slugs)

    def test_unknown_kind_is_none(self):
        self.assertIsNone(briefings.brief_for("snapshot"))
        self.assertIsNone(briefings.brief_for("bogus_kind"))

    def test_every_briefing_kind_is_covered(self):
        # The kinds the harness can surface must all have a briefing.
        for kind in ("new_arrival", "citizen_new", "hostile",
                     "invasion", "strange_mood", "caravan",
                     "unit_death"):
            self.assertIsNotNone(briefings.brief_for(kind), kind)

    def test_attention_arrival_carries_briefing(self):
        # build_attention attaches the briefing to arrival items.
        class FakeDetector:
            arrivals = [{
                "tick": 169650, "at_baseline": True,
                "data": {"kind": "visitor", "unit_id": 5490,
                         "race": "TROLL", "pos": [38, 176, 124],
                         "dist_nearest_citizen": 40},
            }]

        state = {"status": {"year_tick": 169650},
                 "units": {"citizens": [], "hostiles": []},
                 "stocks": {}}
        items = attention.build_attention(state, FakeDetector())
        arrivals = [i for i in items if i["kind"] == "new_arrival"]
        self.assertEqual(len(arrivals), 1)
        b = arrivals[0].get("briefing")
        self.assertIsNotNone(b)
        self.assertIn("what", b)
        self.assertIn("cost", b)


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestBriefingsLive(unittest.TestCase):
    """The briefing on a real attention item, served live."""

    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=180.0)
        cls.client.connect()
        cls.was_paused = actions.get_paused(cls.client)
        if not cls.was_paused:
            actions.set_paused(cls.client, True)
        cls.bus = EventBus()
        from dfagent_harness import events as ev_mod
        cls.poller = ev_mod.EventPoller(cls.client, cls.bus,
                                        slow_interval=3600)
        cls.poller.poll_once()  # baseline: detector records arrivals
        cls.server = create_server(
            cls.bus, host="127.0.0.1", port=0, client=cls.client,
            poller=cls.poller)
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

    def test_attention_items_carry_briefings(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                         timeout=60)
        conn.request("GET", "/v1/attention")
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        conn.close()
        self.assertEqual(resp.status, 200)
        items = payload.get("items") or payload.get("attention") or []
        # The fort has baseline arrivals (wildlife/visitors), so
        # there should be arrival items, each with a briefing.
        arrivals = [i for i in items if i.get("kind") == "new_arrival"]
        self.assertGreater(len(arrivals), 0)
        for item in arrivals:
            b = item.get("briefing")
            self.assertIsNotNone(b, item)
            self.assertIn("what", b)
            self.assertIn("cost", b)


if __name__ == "__main__":
    unittest.main()
