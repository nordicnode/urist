"""Unit tests for the phase-3 minimal HTTP/SSE server (offline).

The server is exercised in-process on an ephemeral port with a
preloaded bus and no DFHack client (so /v1/state answers 503, which
is the honest answer with no game). No live game is needed.
"""

import http.client
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.events import EventBus, make_event  # noqa: E402
from dfagent_harness.server import (  # noqa: E402
    _cursor_array, _req_float, _req_int, _req_seq, create_server)


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

    def test_diary_route_returns_entries(self):
        # GET /v1/diary reads diary.md from the state dir — no
        # game read. This caught a real bug: the POST _diary(body)
        # shadowed the GET _diary() in the same class, so GET
        # /v1/diary raised TypeError and dropped the connection
        # (the live test_diary_route failed the same way). The
        # two are now _diary_read / _diary_write.
        status, _headers, body = self._get("/v1/diary")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertIn("entries", data)
        self.assertIn("count", data)
        self.assertEqual(data["count"], len(data["entries"]))

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


# -- Table 11 step 9 (H10 + T3): input validation, cursor shape,
# percent-decoding, auth, health, SSE, cache stampede -------------


class TestCursorArray(unittest.TestCase):
    def test_object_shape_normalizes(self):
        self.assertEqual(_cursor_array({"1": 10, "2": 20, "3": 30}),
                         [10, 20, 30])

    def test_list_passes_through(self):
        self.assertEqual(_cursor_array([1, 2, 3]), [1, 2, 3])

    def test_short_list_pads(self):
        self.assertEqual(_cursor_array([1, 2]), [1, 2, None])

    def test_junk_is_nulls(self):
        self.assertEqual(_cursor_array(None), [None, None, None])
        self.assertEqual(_cursor_array({"x": 1}), [None, None, None])
        self.assertEqual(_cursor_array("abc"), [None, None, None])


class TestReqCoercions(unittest.TestCase):
    """Malformed-input table (malformed-input test rule): every
    bad shape the HTTP body coercions must reject with ValueError
    — never a TypeError escaping to 502 or a dropped connection."""

    def test_req_int(self):
        self.assertEqual(_req_int(5, "x"), 5)
        self.assertEqual(_req_int("42", "x"), 42)
        self.assertEqual(_req_int(5.0, "x"), 5)
        self.assertEqual(_req_int(None, "x", 7), 7)
        for bad in (None, True, "abc", 5.5, [1], {"a": 1}, ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _req_int(bad, "x")

    def test_req_float(self):
        self.assertEqual(_req_float("1.5", "x"), 1.5)
        self.assertEqual(_req_float(2, "x"), 2.0)
        self.assertEqual(_req_float(None, "x", 3.0), 3.0)
        for bad in (None, True, "abc", [1], ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _req_float(bad, "x")

    def test_req_seq(self):
        self.assertEqual(_req_seq([1, 2, 3], "pos", 3), (1, 2, 3))
        self.assertEqual(_req_seq(["4", "5", "6"], "pos", 3),
                         (4, 5, 6))
        for bad in (None, "abc", [1, 2], [1, 2, 3, 4], 5,
                    [1, "x", 3], (1, 2, None)):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _req_seq(bad, "pos", 3)


class _HttpCase(unittest.TestCase):
    """A live in-process server on an ephemeral port."""

    def _start(self, **kwargs):
        self.bus = EventBus()
        self.server = create_server(self.bus, host="127.0.0.1", port=0,
                                    **kwargs)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def _req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                          timeout=5)
        payload = json.dumps(body) if body is not None else None
        hdrs = dict(headers or {})
        if payload is not None:
            hdrs["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, data


class _FakeCursorClient:
    """Serves a canned cursor payload; records the Lua it is asked
    to run, so the test can pin the dfh_arr() producer fix (H10)."""

    def __init__(self, cursor):
        self.cursor = cursor
        self.lua_calls: list[str] = []

    def run_lua_json(self, code, timeout=None):
        self.lua_calls.append(code)
        return {"ok": True, "cursor": self.cursor}

    def get_version(self):
        return {"df": "v0.47.05"}


class TestCursorEndpoint(_HttpCase):
    def test_old_object_shape_normalizes_to_array(self):
        # The live bug: GET /v1/cursor returned
        # {"cursor": {"1": -30000, "2": -30000, "3": -30000}}.
        self._start(client=_FakeCursorClient(
            {"1": -30000, "2": -30000, "3": -30000}))
        status, raw = self._req("GET", "/v1/cursor")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["cursor"],
                         [-30000, -30000, -30000])

    def test_array_shape_passes_through(self):
        self._start(client=_FakeCursorClient([1, 2, 3]))
        status, raw = self._req("GET", "/v1/cursor")
        self.assertEqual(json.loads(raw)["cursor"], [1, 2, 3])

    def test_lua_wraps_cursor_in_dfh_arr(self):
        client = _FakeCursorClient([1, 2, 3])
        self._start(client=client)
        self._req("GET", "/v1/cursor")
        self.assertTrue(client.lua_calls)
        self.assertIn("dfh_arr", client.lua_calls[0])

    def test_cursor_action_returns_array_evidence(self):
        client = _FakeCursorClient([4, 5, 6])
        self._start(client=client)
        status, raw = self._req("POST", "/v1/actions/cursor",
                                {"pos": [4, 5, 6]})
        self.assertEqual(status, 200, raw)
        data = json.loads(raw)
        self.assertEqual(data["evidence"]["cursor"], [4, 5, 6])
        self.assertTrue(any("dfh_arr" in c for c in client.lua_calls))


class _ExplodingClient:
    """Any RPC call is a test failure: validation must reject the
    request before act() ever touches the client."""

    def __getattr__(self, name):
        raise AssertionError(f"client.{name} must not be called")


class TestActionValidation(_HttpCase):
    # Every coercion site in _dispatch_action, with a body that
    # must be 400 BAD_REQUEST. Live, POST /v1/actions/dig with
    # {"box": null} was a 502 RPC_ERROR; now it is a 400.
    BAD_CASES = [
        ("dig", {"box": None}),
        ("dig", {"box": [1, 2, 3, 4, 5]}),
        ("dig", {"box": [1, "x", 3, 4, 5, 6]}),
        ("dig", {"box": "abc"}),
        ("undesignate", {"box": None}),
        ("chop", {"box": None}),
        ("gather", {"box": [1, 2]}),
        ("build", {"kind": "Still", "pos": None}),
        ("build", {"kind": "Still", "pos": [1, 2]}),
        ("deconstruct", {"building_id": "x"}),
        ("deconstruct", {"building_id": None}),
        ("stockpile", {"box": [1, 2, 3]}),
        ("stockpile", {"pos": None}),
        ("stockpile", {"pos": [1, 2, 3], "width": "wide"}),
        ("zone", {"pos": None}),
        ("farm", {"x": "abc", "y": 1, "z": 1}),
        ("furniture", {"kind": "Bed", "pos": None}),
        ("order", {"job_type": "BrewDrink", "amount": "lots"}),
        ("order-remove", {"order_id": None}),
        ("queue-job", {"building_id": "x", "job": "BrewDrink"}),
        ("queue-job", {"building_id": 1, "job": "BrewDrink",
                       "count": "many"}),
        ("cursor", {"pos": None}),
        ("cursor", {"pos": [1, 2]}),
    ]

    def setUp(self):
        self._start(client=_ExplodingClient())

    def test_bad_bodies_are_400(self):
        for name, body in self.BAD_CASES:
            with self.subTest(action=name, body=body):
                status, raw = self._req(
                    "POST", f"/v1/actions/{name}", body)
                self.assertEqual(status, 400, raw)
                self.assertEqual(json.loads(raw)["error"]["code"],
                                 "BAD_REQUEST")


class _FakeJournal:
    def create_goal(self, name, expression, task, priority):
        return 7

    def get_goal(self, gid):
        return {"id": gid, "name": "x"}


class _FakeDaemon:
    def __init__(self, run_task=None):
        self.journal = _FakeJournal()
        self._run_task = run_task or (lambda name, **kw: {"ok": True})

    def run_task(self, name, wait=120, count=1, **kwargs):
        return self._run_task(name, wait=wait, count=count, **kwargs)

    def get_placement(self, kind, width, height):
        return {"kind": kind, "width": width, "height": height,
                "sites": [{"x": 1, "y": 2, "z": 3, "score": 9}]}


class TestTaskGoalValidation(_HttpCase):
    def setUp(self):
        self.daemon = _FakeDaemon()
        self._start(daemon=self.daemon)

    def test_brew_bad_wait_is_400(self):
        # Live, this dropped the connection (curl 52) before the fix.
        status, raw = self._req("POST", "/v1/tasks/brew",
                                {"wait": "abc"})
        self.assertEqual(status, 400, raw)
        self.assertEqual(json.loads(raw)["error"]["code"],
                         "BAD_REQUEST")

    def test_brew_bad_count_season_building_are_400(self):
        for body in ({"count": "x"}, {"season": "autumn"},
                     {"building_id": "x"}):
            with self.subTest(body=body):
                status, raw = self._req("POST", "/v1/tasks/brew", body)
                self.assertEqual(status, 400, raw)

    def test_brew_ok_still_works(self):
        status, raw = self._req("POST", "/v1/tasks/brew", {"wait": 5})
        self.assertEqual(status, 200, raw)

    def test_goal_bad_priority_is_400(self):
        status, raw = self._req("POST", "/v1/goals", {
            "name": "x", "expression": "y", "task": "brew",
            "priority": "abc"})
        self.assertEqual(status, 400, raw)
        self.assertEqual(json.loads(raw)["error"]["code"],
                         "BAD_REQUEST")

    def test_handler_exception_is_502_not_dropped(self):
        # The last-resort net (T3 row 2): a handler bug must be a
        # JSON 502, never an empty reply.
        def _boom(name, **kwargs):
            raise RuntimeError("boom")

        self.daemon._run_task = _boom
        status, raw = self._req("POST", "/v1/tasks/brew", {"wait": 5})
        self.assertEqual(status, 502, raw)
        self.assertEqual(json.loads(raw)["error"]["code"], "RPC_ERROR")


class TestSitesRoute(_HttpCase):
    def setUp(self):
        self.daemon = _FakeDaemon()
        self._start(daemon=self.daemon)

    def test_sites_ok_returns_placement(self):
        # Regression: the split renamed the handler param to `h`,
        # which the height local then shadowed — the final _json
        # crashed and the route 502'd on every successful search.
        status, raw = self._req(
            "GET", "/v1/sites?kind=workshop&w=3&h=3")
        self.assertEqual(status, 200, raw)
        body = json.loads(raw)
        self.assertEqual(body["kind"], "workshop")
        self.assertEqual(body["width"], 3)
        self.assertEqual(body["height"], 3)
        self.assertIn("cost", body)
        self.assertIsInstance(body["cost"]["ms"], int)

    def test_sites_defaults_to_workshop(self):
        status, raw = self._req("GET", "/v1/sites")
        self.assertEqual(status, 200, raw)
        self.assertEqual(json.loads(raw)["kind"], "workshop")

    def test_sites_bad_kind_is_400(self):
        status, raw = self._req("GET", "/v1/sites?kind=nope")
        self.assertEqual(status, 400, raw)
        self.assertEqual(json.loads(raw)["error"]["code"],
                         "BAD_REQUEST")

    def test_sites_bad_size_is_400(self):
        for qs in ("w=0&h=3", "w=3&h=abc", "w=99&h=3", "w=3&h=0"):
            with self.subTest(qs=qs):
                status, raw = self._req(
                    "GET", f"/v1/sites?kind=workshop&{qs}")
                self.assertEqual(status, 400, raw)
                self.assertEqual(json.loads(raw)["error"]["code"],
                                 "BAD_REQUEST")


class TestSitesNoDaemon(_HttpCase):
    def setUp(self):
        self._start()

    def test_sites_no_daemon_is_503(self):
        status, raw = self._req("GET", "/v1/sites?kind=workshop")
        self.assertEqual(status, 503, raw)
        self.assertEqual(json.loads(raw)["error"]["code"],
                         "NO_DAEMON")


class TestPercentDecoding(_HttpCase):
    def setUp(self):
        self._start()

    def test_unknown_endpoint_shows_decoded_path(self):
        # Live, GET /v1/area/Dug%20Space 404'd with
        # "no area 'Dug%20Space'" — the %20 was never decoded.
        status, raw = self._req("GET", "/v1/nope%20x")
        self.assertEqual(status, 404)
        self.assertIn("/v1/nope x",
                      json.loads(raw)["error"]["message"])


class TestAuth(_HttpCase):
    def setUp(self):
        self._start(token="s3cret")

    def test_health_needs_no_auth(self):
        status, _raw = self._req("GET", "/v1/health")
        self.assertEqual(status, 200)

    def test_missing_token_is_401(self):
        status, _raw = self._req("GET", "/v1/state")
        self.assertEqual(status, 401)

    def test_wrong_token_is_401(self):
        status, _raw = self._req(
            "GET", "/v1/state",
            headers={"Authorization": "Bearer nope"})
        self.assertEqual(status, 401)

    def test_right_token_passes_auth(self):
        status, _raw = self._req(
            "GET", "/v1/state",
            headers={"Authorization": "Bearer s3cret"})
        self.assertEqual(status, 503)  # no game, but auth passed


class _HealthClient:
    def __init__(self):
        self.version_calls = 0

    def get_version(self):
        self.version_calls += 1
        return {"df": "v0.47.05"}


class _StubPoller:
    def __init__(self):
        self.last_state = {"meta": {"version": {"df": "v0.47.05"}}}


class TestHealthBusy(_HttpCase):
    def setUp(self):
        self.client = _HealthClient()
        self.lock = threading.RLock()
        self._start(client=self.client, lock=self.lock,
                    poller=_StubPoller())

    def test_busy_lock_returns_200_with_busy_flag(self):
        self.lock.acquire()
        try:
            status, raw = self._req("GET", "/v1/health")
        finally:
            self.lock.release()
        self.assertEqual(status, 200, raw)
        data = json.loads(raw)
        self.assertTrue(data["busy"])
        self.assertTrue(data["df_reachable"])
        self.assertEqual(self.client.version_calls, 0)

    def test_free_lock_reads_version(self):
        status, raw = self._req("GET", "/v1/health")
        data = json.loads(raw)
        self.assertFalse(data["busy"])
        self.assertTrue(data["df_reachable"])
        self.assertEqual(self.client.version_calls, 1)


class TestSseNoLoss(_HttpCase):
    def setUp(self):
        self._start()

    def test_events_published_after_connect_are_not_lost(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                          timeout=5)
        conn.request("GET", "/v1/events?since=0",
                     headers={"Accept": "text/event-stream"})
        resp = conn.getresponse()
        self.assertEqual(resp.status, 200)

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

        # Publish after connecting: with subscribe-before-replay
        # every event lands in the replay or the live queue, never
        # in the gap between them — so all ten arrive exactly once.
        for i in range(10):
            self.bus.publish(make_event("report", "notice", {"n": i}))
        seen = []
        for _ in range(10):
            event_id, _data = read_event()
            seen.append(event_id)
        conn.close()
        self.assertEqual(seen, list(range(1, 11)))


def _canned_state():
    return {
        "status": {"year_tick": 1000},
        "buildings": {"list": []},
        "units": {"citizens": []},
        "map": {"size_tiles": [48, 48], "z_levels": 3},
    }


def _synthetic_scan():
    # 3x3x1, two open blocks — enough for derive_areas to run.
    def idx(bx, by, bz):
        return (bz * 3 + by) * 3 + bx
    return {
        "x_blocks": 3, "y_blocks": 3, "z_count": 1,
        "x_count": 48, "y_count": 48,
        "total_blocks": 9, "open_blocks": 2,
        "open": {idx(0, 0, 0), idx(1, 0, 0)},
        "up": set(), "down": set(),
        "scan_seconds": 0.0,
    }


class _StampedeClient:
    def call(self, method, req, resp_type):
        class _State:
            Value = True
        return _State(), ""

    def run_lua_json(self, code, timeout=None):
        raise AssertionError("run_lua_json must not be called")

    def get_version(self):
        return {"df": "v0.47.05"}


def _minimal_raw():
    return {
        "x_blocks": 3, "y_blocks": 3, "z_count": 1,
        "water_blocks": [], "magma_blocks": [], "mineral_blocks": [],
        "aquifer_by_z": [0], "aquifer_total": 0,
        "soil_by_z": [0], "stone_by_z": [0], "plants": [],
    }


class TestSpatialStampede(_HttpCase):
    def setUp(self):
        self._start(client=_StampedeClient())

    def test_concurrent_cold_areas_derive_once(self):
        scans = {"n": 0}

        def slow_scan(client):
            scans["n"] += 1
            time.sleep(0.3)
            return _synthetic_scan()

        results = []

        def hit():
            results.append(self._req("GET", "/v1/areas"))

        with mock.patch("dfagent_harness.observe.collect",
                        side_effect=lambda *a, **k: _canned_state()), \
             mock.patch("dfagent_harness.spatial.scan_blocks",
                        side_effect=slow_scan):
            t1 = threading.Thread(target=hit)
            t2 = threading.Thread(target=hit)
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)
        self.assertEqual([s for s, _ in results], [200, 200])
        self.assertEqual(scans["n"], 1)

    def test_concurrent_cold_survey_runs_once(self):
        surveys = {"n": 0}

        def slow_survey(client, fort=(0, 0, 0)):
            surveys["n"] += 1
            time.sleep(0.3)
            return _minimal_raw()

        results = []

        def hit():
            results.append(self._req("GET", "/v1/survey"))

        with mock.patch("dfagent_harness.observe.collect",
                        side_effect=lambda *a, **k: _canned_state()), \
             mock.patch("dfagent_harness.spatial.scan_blocks",
                        return_value=_synthetic_scan()), \
             mock.patch("dfagent_harness.survey.run_survey",
                        side_effect=slow_survey):
            t1 = threading.Thread(target=hit)
            t2 = threading.Thread(target=hit)
            t1.start()
            t2.start()
            t1.join(timeout=10)
            t2.join(timeout=10)
        self.assertEqual([s for s, _ in results], [200, 200])
        self.assertEqual(surveys["n"], 1)
