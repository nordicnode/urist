"""Unit tests for the phase-4 daemon (config, token, drain offset,
HTTP auth + endpoints). No live game needed; the HTTP server is
exercised in-process with a fake client where required.
"""

import json
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.daemon import (  # noqa: E402
    Daemon,
    DaemonConfig,
    load_config,
    load_or_create_token,
    save_config,
)
from dfagent_harness.events import EventBus, WatcherDrainer  # noqa: E402
from dfagent_harness.server import create_server  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_defaults_and_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            cfg = load_config(state_dir)
            self.assertEqual(cfg.http_port, 8765)
            self.assertEqual(cfg.df_port, 5000)
            cfg.http_port = 9999
            cfg.allow_raw_actions = True
            save_config(state_dir, cfg)
            reloaded = load_config(state_dir)
            self.assertEqual(reloaded.http_port, 9999)
            self.assertTrue(reloaded.allow_raw_actions)

    def test_malformed_config_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            (state_dir / "config.json").write_text("{not json")
            self.assertEqual(load_config(state_dir).http_port, 8765)

    def test_unknown_keys_ignored(self):
        cfg = DaemonConfig.from_dict({"http_port": 1234, "nope": 1})
        self.assertEqual(cfg.http_port, 1234)

    def test_loop_paused_round_trip(self):
        # The loop state must survive a config save/load cycle, so a
        # daemon restart starts with the same loop state it stopped
        # with (2026-11-27: the reset to "running" fired an
        # immediate planner tick that unpaused DF and killed it).
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            cfg = load_config(state_dir)
            self.assertFalse(cfg.loop_paused)
            cfg.loop_paused = True
            save_config(state_dir, cfg)
            self.assertTrue(load_config(state_dir).loop_paused)


class LoopPausedTests(unittest.TestCase):
    def _daemon(self, tmp, **cfg_kw):
        cfg = DaemonConfig(**cfg_kw)
        return Daemon(config=cfg, state_dir=Path(tmp))

    def test_daemon_init_reads_loop_paused_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(self._daemon(tmp)._loop_paused)
            self.assertTrue(
                self._daemon(tmp, loop_paused=True)._loop_paused)

    def test_set_loop_paused_persists_to_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            daemon = self._daemon(tmp)
            daemon.set_loop_paused(True)
            self.assertTrue(load_config(state_dir).loop_paused)
            daemon.set_loop_paused(False)
            self.assertFalse(load_config(state_dir).loop_paused)

    def test_first_planner_tick_waits_one_interval(self):
        # A fresh daemon must not fire a planner tick (which
        # unpauses the game) before a controller has had a chance
        # to pause the loop. With a 0.2 s interval, no tick may fire
        # in the first 0.05 s, and at least one must fire by 0.8 s.
        with tempfile.TemporaryDirectory() as tmp:
            daemon = self._daemon(tmp, planner_interval=0.2)
            calls = []
            daemon._pause_guard = lambda: None
            daemon._planner_tick = lambda: calls.append(1)
            thread = threading.Thread(target=daemon._planner_loop,
                                      daemon=True)
            thread.start()
            try:
                threading.Event().wait(0.05)
                self.assertEqual(calls, [])
                threading.Event().wait(0.75)
                self.assertGreaterEqual(len(calls), 1)
            finally:
                daemon._stop.set()
                thread.join(timeout=2.0)


class TokenTests(unittest.TestCase):
    def test_token_created_once_and_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            t1 = load_or_create_token(state_dir)
            t2 = load_or_create_token(state_dir)
            self.assertEqual(t1, t2)
            self.assertTrue(len(t1) >= 16)
            mode = (state_dir / "token").stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)

    def test_no_auth_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(
                load_or_create_token(Path(tmp), no_auth=True))

    def test_env_token_wins(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["DFH_AGENT_TOKEN"] = "env-token-123"
            try:
                self.assertEqual(
                    load_or_create_token(Path(tmp)), "env-token-123")
            finally:
                del os.environ["DFH_AGENT_TOKEN"]


class DrainOffsetTests(unittest.TestCase):
    def test_offset_persists_across_drainers(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "dfh-events.jsonl"
            log.write_text(
                '{"kind": "REPORT", "text": "a", "tick": 1, "year": 306}\n'
                '{"kind": "REPORT", "text": "b", "tick": 2, "year": 306}\n')
            offset_path = Path(tmp) / "drain-offset.json"
            d1 = WatcherDrainer(log, offset_path=offset_path)
            events = d1.drain()
            self.assertEqual(len(events), 2)
            self.assertGreater(d1.offset, 0)
            # A fresh drainer resumes instead of replaying.
            d2 = WatcherDrainer(log, offset_path=offset_path)
            self.assertEqual(d2.offset, d1.offset)
            self.assertEqual(d2.drain(), [])
            # New lines are picked up from the saved offset.
            with open(log, "a") as fh:
                fh.write('{"kind": "REPORT", "text": "c", "tick": 3, '
                         '"year": 306}\n')
            events2 = d2.drain()
            self.assertEqual(len(events2), 1)
            self.assertEqual(events2[0]["data"]["text"], "c")


class _FakeClient:
    def get_version(self):
        return {"dwarf_fortress_version": "0.47.05",
                "dfhack_version": "0.47.05-r8",
                "remote_fortress_reader_version": "0.21.0"}


def _serve(bus, **kw):
    server = create_server(bus, host="127.0.0.1", port=0, **kw)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def _get(port, path, token=None, headers=None):
    req_headers = dict(headers or {})
    if token:
        req_headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def _post(port, path, body, token=None):
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


class ServerAuthTests(unittest.TestCase):
    def test_health_needs_no_token(self):
        bus = EventBus()
        server, port = _serve(bus, client=_FakeClient(), token="secret")
        try:
            status, body = _get(port, "/v1/health")
            self.assertEqual(status, 200)
            self.assertTrue(body["df_reachable"])
        finally:
            server.shutdown()
            server.server_close()

    def test_state_requires_token_when_set(self):
        bus = EventBus()
        server, port = _serve(bus, client=_FakeClient(), token="secret")
        try:
            status, body = _get(port, "/v1/state")
            self.assertEqual(status, 401)
            self.assertEqual(body["error"]["code"], "UNAUTHORIZED")
            status, body = _get(port, "/v1/state", token="wrong")
            self.assertEqual(status, 401)
        finally:
            server.shutdown()
            server.server_close()

    def test_no_token_configured_means_no_auth(self):
        bus = EventBus()
        server, port = _serve(bus, client=_FakeClient(), token=None)
        try:
            status, body = _get(port, "/v1/health")
            self.assertEqual(status, 200)
        finally:
            server.shutdown()
            server.server_close()

    def test_raw_actions_disabled_by_default(self):
        bus = EventBus()
        server, port = _serve(bus, client=_FakeClient(), token=None,
                              allow_raw_actions=False)
        try:
            status, body = _post(port, "/v1/actions/lua",
                                 {"code": "print(1)"})
            self.assertEqual(status, 403)
            status, body = _post(port, "/v1/actions/command",
                                 {"command": "ls"})
            self.assertEqual(status, 403)
        finally:
            server.shutdown()
            server.server_close()

    def test_unknown_action_is_bad_request(self):
        bus = EventBus()
        server, port = _serve(bus, client=_FakeClient(), token=None)
        try:
            status, body = _post(port, "/v1/actions/nope", {})
            self.assertEqual(status, 400)
        finally:
            server.shutdown()
            server.server_close()

    def test_unknown_endpoint_is_404(self):
        bus = EventBus()
        server, port = _serve(bus, client=_FakeClient(), token=None)
        try:
            status, body = _get(port, "/v1/nope")
            self.assertEqual(status, 404)
            self.assertEqual(body["error"]["code"], "NOT_FOUND")
        finally:
            server.shutdown()
            server.server_close()

    def test_tasks_listed(self):
        bus = EventBus()
        server, port = _serve(bus, client=_FakeClient(), token=None)
        try:
            status, body = _get(port, "/v1/tasks")
            self.assertEqual(status, 200)
            self.assertIn("brew", body["tasks"])
            self.assertIn("cook", body["tasks"])
            status, body = _get(port, "/v1/tasks/brew/plan")
            self.assertEqual(status, 200)
            self.assertTrue(body["steps"])
            status, body = _get(port, "/v1/tasks/nope/plan")
            self.assertEqual(status, 404)
        finally:
            server.shutdown()
            server.server_close()


class _SaveClient(_FakeClient):
    """Fake DFHack client for quicksave tests: run_lua answers the
    save-dir probe; the game itself is never touched."""

    def run_lua(self, code, timeout=None):
        if "cur_savegame" in code:
            return "region2"
        return ""

    def close(self):
        pass


class TestQuicksaveLocks(unittest.TestCase):
    """H3/H4 (2026-11-27, external review): the quicksave
    unpause window must hold daemon.lock (== the server's
    rpc_lock), and a failed save must not abort shutdown."""

    def _daemon(self, tmp):
        df_dir = tmp / "df"
        (df_dir / "data" / "save" / "region2").mkdir(parents=True)
        (df_dir / "data" / "save" / "region2" / "world.sav") \
            .write_bytes(b"x")
        daemon = Daemon(config=DaemonConfig(df_dir=str(df_dir)),
                        state_dir=tmp / "state")
        daemon.client = _SaveClient()
        return daemon, df_dir

    def test_quicksave_holds_lock_across_unpause_window(self):
        import dfagent_harness.daemon as daemon_mod
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            daemon, df_dir = self._daemon(tmp)
            entered = threading.Event()
            release = threading.Event()
            calls = []

            def fake_set_paused(client, paused):
                calls.append(paused)
                if paused is False:
                    entered.set()
                    release.wait(timeout=10)

            with mock.patch.object(daemon_mod, "set_paused",
                                   fake_set_paused):
                t = threading.Thread(
                    target=lambda: daemon._quicksave_if_due(force=True),
                    daemon=True)
                t.start()
                try:
                    self.assertTrue(entered.wait(timeout=10),
                                    "unpause never started")
                    # The saving thread holds daemon.lock across the
                    # window: another thread cannot take it.
                    self.assertFalse(daemon.lock.acquire(timeout=0.5))
                    # Drop a new backup dir in while the game is
                    # "running" so the first poll sees the save.
                    (df_dir / "data" / "save"
                     / "region2-00125-04-13").mkdir()
                    release.set()
                    t.join(timeout=15)
                    self.assertFalse(t.is_alive())
                finally:
                    release.set()
            self.assertEqual(calls, [False, True])
            self.assertTrue(daemon.lock.acquire(timeout=0.5))
            daemon.lock.release()

    def test_stop_survives_failed_quicksave(self):
        import dfagent_harness.daemon as daemon_mod
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            daemon, _df_dir = self._daemon(tmp)
            daemon.planner = object()  # stop() saves only with one
            stopped = []

            class _FakePoller:
                def stop(self, timeout=None):
                    stopped.append("poller")

            class _FakeServer:
                def shutdown(self):
                    stopped.append("shutdown")

                def server_close(self):
                    stopped.append("close")

            daemon.poller = _FakePoller()
            daemon.server = _FakeServer()

            def boom(client, paused):
                if paused is False:
                    raise RuntimeError("RPC down")

            with mock.patch.object(daemon_mod, "set_paused", boom):
                daemon.stop()  # must not raise
            self.assertEqual(stopped, ["poller", "shutdown", "close"])

    def test_quicksave_endpoint_holds_rpc_lock(self):
        # Server half of H3: while a quicksave is in flight, a
        # concurrent GET /v1/health — which takes rpc_lock for its
        # version read — must wait. If _quicksave did not hold the
        # lock, health would answer while the game is running.
        entered = threading.Event()
        release = threading.Event()

        class _BlockingDaemon:
            def _quicksave_if_due(self, force=False):
                entered.set()
                release.wait(timeout=10)

        server, port = _serve(EventBus(), client=_FakeClient(),
                              daemon=_BlockingDaemon(), token="<redacted>")
        try:
            result = {}

            def post():
                result["post"] = _post(port, "/v1/control/quicksave",
                                      {}, token="<redacted>")

            t = threading.Thread(target=post, daemon=True)
            t.start()
            try:
                self.assertTrue(entered.wait(timeout=5),
                                "quicksave never started")
                with self.assertRaises(
                        (urllib.error.URLError, TimeoutError)):
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/v1/health", timeout=1)
            finally:
                release.set()
            t.join(timeout=5)
            self.assertFalse(t.is_alive())
            self.assertEqual(result["post"][0], 200)
            status, body = _get(port, "/v1/health", token="<redacted>")
            self.assertEqual(status, 200)
            self.assertTrue(body["df_reachable"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
