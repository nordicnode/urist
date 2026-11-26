"""Unit tests for the phase-3 minimal HTTP/SSE server (offline).

The server is exercised in-process on an ephemeral port with a
preloaded bus and no DFHack client (so /v1/state answers 503, which
is the honest answer with no game). No live game is needed.
"""

import http.client
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.events import EventBus, make_event  # noqa: E402
from dfagent_harness.server import create_server  # noqa: E402


class TestServer(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        for i in range(3):
            self.bus.publish(make_event("report", "notice", {"n": i}))
        self.server = create_server(self.bus, host="127.0.0.1", port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _get(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                          timeout=5)
        conn.request("GET", path, headers=headers or {})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, dict(resp.getheaders()), body

    def test_health_without_game(self):
        status, _headers, body = self._get("/v1/health")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertFalse(data["df_reachable"])

    def test_state_without_game_is_503(self):
        status, _headers, body = self._get("/v1/state")
        self.assertEqual(status, 503)
        data = json.loads(body)
        self.assertEqual(data["error"]["code"], "GAME_NOT_RUNNING")
        self.assertIn("request_id", data)

    def test_unknown_endpoint_is_404(self):
        status, _headers, body = self._get("/v1/nope")
        self.assertEqual(status, 404)
        self.assertEqual(json.loads(body)["error"]["code"], "NOT_FOUND")

    def test_events_json_array(self):
        status, _headers, body = self._get("/v1/events?limit=2")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual([e["seq"] for e in data["events"]], [2, 3])
        self.assertEqual(data["latest_seq"], 3)

    def test_events_json_since(self):
        status, _headers, body = self._get("/v1/events?since=2")
        data = json.loads(body)
        self.assertEqual([e["seq"] for e in data["events"]], [3])

    def test_events_bad_since(self):
        status, _headers, body = self._get("/v1/events?since=banana")
        self.assertEqual(status, 400)
        self.assertEqual(json.loads(body)["error"]["code"], "BAD_REQUEST")

    def test_daemon_control(self):
        status, _headers, body = self._get("/v1/control/daemon")
        data = json.loads(body)
        self.assertEqual(data["event_seq"], 3)
        self.assertEqual(data["events_buffered"], 3)

    def test_sse_replay_then_live(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                          timeout=5)
        conn.request("GET", "/v1/events?since=2",
                     headers={"Accept": "text/event-stream"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)
        self.assertIn("text/event-stream",
                      resp.getheader("Content-Type"))

        def read_event():
            event_id, data = None, None
            while True:
                line = resp.readline().decode().strip()
                if line == "":
                    return event_id, data
                if line.startswith("id:"):
                    event_id = int(line[3:].strip())
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip())

        # Replay: only seq 3 (since=2).
        event_id, data = read_event()
        self.assertEqual(event_id, 3)
        self.assertEqual(data["data"], {"n": 2})
        # Live: publish after connecting; it must arrive with its seq.
        self.bus.publish(make_event("report", "notice", {"n": 3}))
        event_id, data = read_event()
        self.assertEqual(event_id, 4)
        self.assertEqual(data["data"], {"n": 3})
        conn.close()


if __name__ == "__main__":
    unittest.main()
