"""Live integration tests for the diary + memory retrieval
(GOAL.md step 4).

Runs against the real State Store (world.db) and planner Journal
(journal.db) in the daemon state dir, and a real Dwarf Fortress
game on 127.0.0.1:5000 for the HTTP routes. Skips itself when no
game is reachable. Set DFH_TEST_LIVE=0 to force the skip.

Verifies, live on Erushtathtat:
- A daily summary built from the real Store + Journal for a real
  day (125-06-02, the day of the milestone-5 snapshot) carries
  real data (the drink trend sample, the journal's decisions).
- The entry renders grounded (only recorded facts) and diary.md +
  diary.html are generated in a temp dir.
- GET /v1/memory/summary returns the real trends (drink, food)
  from the Store, and GET /v1/diary returns the entries.

All reads are from the on-disk Store/Journal (no game reads for
the summary itself); the HTTP routes are paused reads at most.
No game time advances, no drink burns.

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

from dfagent_harness import actions, diary  # noqa: E402
from dfagent_harness.daemon import default_state_dir  # noqa: E402
from dfagent_harness.events import EventBus  # noqa: E402
from dfagent_harness.planner import Journal  # noqa: E402
from dfagent_harness.server import create_server  # noqa: E402
from dfagent_harness.store import Store, default_world_db_path  # noqa: E402
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
class TestLiveDiary(unittest.TestCase):
    """Verified live against the Erushtathtat fort's real Store +
    Journal."""

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
        cls.store = Store(default_world_db_path())
        cls.journal = Journal(default_state_dir() / "journal.db")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.store.close()
        if not cls.was_paused:
            actions.set_paused(cls.client, False)
        cls.client.close()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                         timeout=60)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_daily_summary_from_real_store(self):
        # The day of the milestone-5 snapshot: 125-06-02, ticks
        # 169200..170399. The Store has a drink trend sample at
        # tick 169650 (drink 9).
        s = diary.build_daily_summary(self.store, self.journal,
                                      169200, "Erushtathtat", 125)
        self.assertEqual(s["date"], "125-06-02")
        self.assertEqual(s["date_words"], "2nd of Galena, 125")
        self.assertEqual(s["season"], "Summer")
        self.assertIn("drink", s["stocks_start"])
        self.assertEqual(s["stocks_start"]["drink"], 9.0)

    def test_entry_renders_and_html_generated(self):
        s = diary.build_daily_summary(self.store, self.journal,
                                      169200, "Erushtathtat", 125)
        entry = diary.render_entry(s)
        self.assertIn("2nd of Galena, 125", entry)
        self.assertIn("Drink: 9", entry)
        with tempfile.TemporaryDirectory() as tmp:
            md_path = diary.write_entry(tmp, s)
            self.assertTrue(md_path.exists())
            html_path = diary.diary_html_path(tmp)
            self.assertTrue(html_path.exists())
            html_doc = html_path.read_text()
            self.assertIn("125-06-02", html_doc)
            self.assertIn("Diary of Erushtathtat", html_doc)
            self.assertIn("prev day", html_doc)

    def test_memory_summary_route(self):
        status, body = self._get("/v1/memory/summary")
        self.assertEqual(status, 200, body[:200])
        payload = json.loads(body)
        self.assertIn("trends", payload)
        self.assertIn("drink", payload["trends"])
        self.assertEqual(payload["trends"]["drink"]["latest"], 9.0)

    def test_diary_route(self):
        status, body = self._get("/v1/diary")
        self.assertEqual(status, 200, body[:200])
        payload = json.loads(body)
        self.assertIn("entries", payload)
        self.assertIn("count", payload)


if __name__ == "__main__":
    unittest.main()
