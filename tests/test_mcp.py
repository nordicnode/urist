"""Offline tests for the MCP server (Track 2, R2-7).

Everything runs against a fake in-process daemon (stdlib
http.server on an ephemeral port), so no game is needed. The
subprocess smoke test drives the real scripts/dfh-mcp entry
point over stdio against the same fake.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from dfagent_harness.mcp import TOOL_NAMES
from dfagent_harness.mcp.client import DaemonClient, DaemonError
from dfagent_harness.mcp.protocol import handle_line, handle_message
from dfagent_harness.mcp.tools import TOOLS, ToolArgumentError, dispatch

REPO = Path(__file__).resolve().parent.parent


# --- Fake daemon ------------------------------------------------

class _FakeDaemonHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # noqa: D102 - keep test output clean
        pass

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        self._send(status, {"error": {"code": code, "message": message,
                                      "detail": {}}, "request_id": "t1"})

    def do_GET(self):  # noqa: N802 - http.server naming
        self.server.hits.append(("GET", self.path, self.headers.get(
            "authorization")))
        parsed = urllib.parse.urlsplit(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)
        if path == "/v1/health":
            self._send(200, {"ok": True, "daemon": "up"})
        elif path == "/v1/snapshot":
            self._send(200, {"tick": 116750, "sections": {"stocks": {}}})
        elif path == "/v1/catalog":
            self._send(200, {
                "actions": [
                    {"name": "queue_job", "about": "Queue a job"},
                    {"name": "build_workshop",
                     "about": "Build a workshop"}],
                "count": 2,
                "tasks": [{"name": "brew", "about": "Brew a batch"}],
                "query_routes": []})
        elif path == "/v1/catalog/queue_job":
            self._send(200, {"name": "queue_job", "about": "Queue a job",
                             "params": {"job": {"type": "str",
                                                "required": True}}})
        elif path == "/v1/catalog/task:brew":
            self._send(200, {"name": "task:brew",
                             "about": "Brew a batch",
                             "params": {}})
        elif path == "/v1/catalog/nope":
            self._error(404, "UNKNOWN_ACTION",
                        "no action named 'nope' - choose from: "
                        "build_workshop, queue_job or a task: brew")
        elif path == "/v1/wiki":
            self._send(200, {"query": query.get("q", [""])[0],
                             "mode": query.get("mode", ["hybrid"])[0],
                             "results": [{"slug": "brewing",
                                          "title": "Brewing",
                                          "snippet": "Booze."}]})
        elif path == "/v1/wiki/brewing":
            self._send(200, {"slug": "brewing", "title": "Brewing",
                             "text": "Full brewing page."})
        elif path == "/v1/journal":
            self._send(200, {
                "decisions": [{"domain": "needs", "decision": "brew",
                               "ok": 1, "result": "ok"}],
                "counts": {"needs": 1}})
        elif path == "/v1/diary":
            self._send(200, {"entries": [], "count": 0})
        elif path == "/v1/units":
            self._send(200, {"units": []})
        elif path == "/v1/stocks":
            self._send(200, {"drink": 97})
        elif path == "/v1/plain-error":
            # A non-JSON error body: the client must not crash.
            body = b"not json at all"
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._error(404, "NOT_FOUND", f"no route {path}")

    def do_POST(self):  # noqa: N802 - http.server naming
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode())
        except ValueError:
            body = {}
        self.server.hits.append(("POST", self.path, body))
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/v1/actions/queue_job":
            self._send(200, {"ok": True, "action": "queue_job",
                             "detail": "queued", "evidence": {},
                             "took_ms": 1})
        elif parsed.path == "/v1/actions/pause":
            self._send(200, {"ok": True, "action": "pause"})
        elif parsed.path == "/v1/tasks/brew":
            self._send(200, {"ok": True, "action": "task:brew",
                             "detail": "brewed", "evidence": {},
                             "took_ms": 1})
        else:
            self._error(404, "NOT_FOUND",
                        f"no route {parsed.path}")


@pytest.fixture(scope="module")
def fake_daemon():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeDaemonHandler)
    server.hits = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def client(fake_daemon):
    base = f"http://127.0.0.1:{fake_daemon.server_port}"
    return DaemonClient(base=base, token="test-token")


def _text(result: dict) -> str:
    assert result["content"][0]["type"] == "text"
    return result["content"][0]["text"]


# --- Client -----------------------------------------------------

class TestDaemonClient:
    def test_health_and_auth_header(self, client, fake_daemon):
        assert client.health() == {"ok": True, "daemon": "up"}
        # Health needs no auth; an authed call carries the token.
        client.get("/v1/snapshot")
        _, _, auth = fake_daemon.hits[-1]
        assert auth == "Bearer test-token"

    def test_daemon_404_carries_code_and_message(self, client):
        with pytest.raises(DaemonError) as exc:
            client.get("/v1/catalog/nope")
        assert exc.value.status == 404
        assert exc.value.code == "UNKNOWN_ACTION"
        assert "nope" in exc.value.message

    def test_non_json_error_body_does_not_crash(self, client):
        with pytest.raises(DaemonError) as exc:
            client.get("/v1/plain-error")
        assert exc.value.status == 500
        assert exc.value.code == "HTTP_ERROR"

    def test_unreachable_daemon_is_transport_error(self):
        dead = DaemonClient(base="http://127.0.0.1:1", token="x")
        with pytest.raises(DaemonError) as exc:
            dead.health()
        assert exc.value.status == 0
        assert exc.value.code == "TRANSPORT"

    def test_missing_token_file_is_a_clear_error(self, tmp_path):
        with pytest.raises(DaemonError) as exc:
            DaemonClient(base="http://127.0.0.1:8765",
                         token_path=str(tmp_path / "nope"))
        assert exc.value.code == "NO_TOKEN"

    def test_env_token_wins_over_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DFH_AGENT_TOKEN", "env-token")
        made = DaemonClient(base="http://127.0.0.1:8765",
                            token_path=str(tmp_path / "nope"))
        assert made.token == "env-token"


# --- Tool list --------------------------------------------------

class TestToolList:
    def test_exactly_six_tools(self):
        assert [t["name"] for t in TOOLS] == list(TOOL_NAMES)
        assert len(TOOLS) == 6

    def test_no_enums_in_any_schema(self):
        def walk(obj):
            if isinstance(obj, dict):
                assert "enum" not in obj, f"enum found in {obj}"
                for value in obj.values():
                    walk(value)
            elif isinstance(obj, list):
                for value in obj:
                    walk(value)
        for tool in TOOLS:
            walk(tool["inputSchema"])

    def test_every_tool_has_description_and_schema(self):
        for tool in TOOLS:
            assert tool["description"].strip()
            assert tool["inputSchema"]["type"] == "object"


# --- Dispatch: observe / act ------------------------------------

class TestObserveAndAct:
    def test_observe_returns_snapshot(self, client):
        result = dispatch(client, "observe", {})
        assert result["isError"] is False
        assert json.loads(_text(result))["tick"] == 116750

    def test_observe_rejects_arguments(self, client):
        with pytest.raises(ToolArgumentError):
            dispatch(client, "observe", {"tick": 1})

    def test_act_validates_then_posts(self, client, fake_daemon):
        result = dispatch(client, "act", {
            "action": "queue_job",
            "parameters": {"job": "MakeBed", "building_id": 7}})
        assert result["isError"] is False
        assert json.loads(_text(result))["ok"] is True
        assert ("POST", "/v1/actions/queue_job",
                {"job": "MakeBed", "building_id": 7}) in fake_daemon.hits

    def test_act_task_goes_to_tasks_route(self, client, fake_daemon):
        result = dispatch(client, "act", {"action": "task:brew"})
        assert result["isError"] is False
        assert json.loads(_text(result))["action"] == "task:brew"
        assert any(m == "POST" and p == "/v1/tasks/brew"
                   for m, p, _ in fake_daemon.hits)

    def test_act_unknown_name_names_legal_values(self, client):
        result = dispatch(client, "act", {"action": "nope"})
        assert result["isError"] is True
        assert "UNKNOWN_ACTION" in _text(result)
        assert "queue_job" in _text(result)

    def test_act_refuses_pause_without_touching_daemon(
            self, client, fake_daemon):
        before = len(fake_daemon.hits)
        result = dispatch(client, "act", {
            "action": "pause", "parameters": {"paused": True}})
        assert result["isError"] is True
        assert "daemon owns the clock" in _text(result)
        assert len(fake_daemon.hits) == before

    def test_act_refuses_key(self, client):
        result = dispatch(client, "act", {
            "action": "key", "parameters": {"keys": ["enter"]}})
        assert result["isError"] is True
        assert "keystrokes" in _text(result)

    def test_act_rejects_bad_arguments(self, client):
        with pytest.raises(ToolArgumentError):
            dispatch(client, "act", {})
        with pytest.raises(ToolArgumentError):
            dispatch(client, "act", {"action": "queue_job",
                                     "parameters": "not-a-dict"})
        with pytest.raises(ToolArgumentError):
            dispatch(client, "act", {"action": "a/b"})
        with pytest.raises(ToolArgumentError):
            dispatch(client, "act", {"action": "queue_job",
                                     "surprise": 1})

    def test_unknown_tool_is_an_argument_error(self, client):
        with pytest.raises(ToolArgumentError):
            dispatch(client, "teleport", {})


# --- Dispatch: query / catalog / wiki / journal -----------------

class TestQueryCatalogWikiJournal:
    def test_query_read_route(self, client):
        result = dispatch(client, "query",
                          {"route": "/v1/units?kind=citizens"})
        assert result["isError"] is False
        assert json.loads(_text(result)) == {"units": []}

    def test_query_refuses_other_tools_routes(self, client):
        for route, tool in [
                ("/v1/snapshot", "observe"),
                ("/v1/catalog", "catalog"),
                ("/v1/catalog/queue_job", "catalog"),
                ("/v1/journal", "journal"),
                ("/v1/diary", "journal"),
                ("/v1/wiki?q=brew", "wiki_search"),
                ("/v1/wiki/brewing", "wiki_search")]:
            result = dispatch(client, "query", {"route": route})
            assert result["isError"] is True, route
            assert tool in _text(result), route

    def test_query_refuses_writes_and_unknown_routes(self, client):
        for route in ["/v1/actions/queue_job", "/v1/tasks/brew",
                      "/v1/control/daemon", "/v1/bogus",
                      "http://example.com/v1/units", "/v2/units"]:
            result = dispatch(client, "query", {"route": route})
            assert result["isError"] is True, route

    def test_catalog_lists_all(self, client):
        result = dispatch(client, "catalog", {})
        assert result["isError"] is False
        body = json.loads(_text(result))
        assert body["count"] == 2

    def test_catalog_one_action(self, client):
        result = dispatch(client, "catalog", {"action": "queue_job"})
        assert json.loads(_text(result))["name"] == "queue_job"

    def test_catalog_unknown_action_is_error(self, client):
        result = dispatch(client, "catalog", {"action": "nope"})
        assert result["isError"] is True
        assert "UNKNOWN_ACTION" in _text(result)

    def test_catalog_search_filters(self, client):
        result = dispatch(client, "catalog", {"search": "brew"})
        body = json.loads(_text(result))
        assert body["count"] == 1
        assert body["tasks"][0]["name"] == "brew"

    def test_wiki_search_defaults(self, client):
        result = dispatch(client, "wiki_search",
                          {"query": "how does brewing work"})
        assert result["isError"] is False
        body = json.loads(_text(result))
        assert body["results"][0]["slug"] == "brewing"

    def test_wiki_search_bad_mode(self, client):
        with pytest.raises(ToolArgumentError):
            dispatch(client, "wiki_search",
                     {"query": "x", "mode": "fuzzy"})

    def test_wiki_search_page(self, client):
        result = dispatch(client, "wiki_search",
                          {"query": "ignored", "page": "brewing"})
        assert json.loads(_text(result))["slug"] == "brewing"

    def test_wiki_search_requires_query(self, client):
        with pytest.raises(ToolArgumentError):
            dispatch(client, "wiki_search", {})

    def test_journal_decisions(self, client):
        result = dispatch(client, "journal", {})
        body = json.loads(_text(result))
        assert body["counts"] == {"needs": 1}

    def test_journal_diary_source(self, client):
        result = dispatch(client, "journal", {"source": "diary"})
        assert json.loads(_text(result))["count"] == 0

    def test_journal_bad_kind_and_source(self, client):
        with pytest.raises(ToolArgumentError):
            dispatch(client, "journal", {"kind": "feelings"})
        with pytest.raises(ToolArgumentError):
            dispatch(client, "journal", {"source": "ledger"})
        with pytest.raises(ToolArgumentError):
            dispatch(client, "journal",
                     {"source": "diary", "kind": "needs"})

    def test_journal_limit_clamps(self, client, fake_daemon):
        dispatch(client, "journal", {"limit": 5000})
        assert any(p.startswith("/v1/journal?limit=1000")
                   for _, p, *_ in fake_daemon.hits)


# --- Protocol ---------------------------------------------------

class TestProtocol:
    def test_initialize_echoes_supported_version(self, client):
        resp = handle_message(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18",
                       "capabilities": {},
                       "clientInfo": {"name": "t", "version": "1"}}})
        assert resp["result"]["protocolVersion"] == "2025-06-18"
        assert resp["result"]["serverInfo"]["name"] == "urist"

    def test_initialize_unknown_version_gets_latest(self, client):
        resp = handle_message(client, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "1999-01-01"}})
        assert resp["result"]["protocolVersion"] == "2025-06-18"

    def test_ping_and_tools_list(self, client):
        assert handle_message(client, {"jsonrpc": "2.0", "id": 2,
                                       "method": "ping"})["result"] == {}
        resp = handle_message(client, {"jsonrpc": "2.0", "id": 3,
                                       "method": "tools/list"})
        assert [t["name"] for t in resp["result"]["tools"]] == \
            list(TOOL_NAMES)

    def test_tools_call_roundtrip(self, client):
        resp = handle_message(client, {
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "observe", "arguments": {}}})
        assert resp["result"]["isError"] is False

    def test_tools_call_unknown_tool_is_32602(self, client):
        resp = handle_message(client, {
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {"name": "teleport", "arguments": {}}})
        assert resp["error"]["code"] == -32602

    def test_tools_call_bad_arguments_is_32602(self, client):
        resp = handle_message(client, {
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {"name": "act", "arguments": {}}})
        assert resp["error"]["code"] == -32602

    def test_unknown_method_is_32601(self, client):
        resp = handle_message(client, {"jsonrpc": "2.0", "id": 7,
                                       "method": "resources/list"})
        assert resp["error"]["code"] == -32601

    def test_non_object_is_32600(self, client):
        resp = handle_message(client, ["not", "a", "request"])
        assert resp["error"]["code"] == -32600

    def test_malformed_json_is_32700(self, client):
        line = handle_line(client, "{not json")
        assert json.loads(line)["error"]["code"] == -32700

    def test_notifications_get_no_response(self, client):
        assert handle_message(client, {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"}) is None
        assert handle_line(client, "") is None


# --- Subprocess smoke: the real entry point over stdio -----------

class TestSubprocessSmoke:
    def test_stdio_server_end_to_end(self, fake_daemon, tmp_path):
        token_file = tmp_path / "token"
        token_file.write_text("test-token\n")
        env = dict(os.environ,
                   DFH_DAEMON_URL=(
                       f"http://127.0.0.1:{fake_daemon.server_port}"),
                   DFH_TOKEN_FILE=str(token_file))
        proc = subprocess.Popen(
            [sys.executable, str(REPO / "scripts" / "dfh-mcp")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, env=env)
        try:
            def send(obj):
                proc.stdin.write(json.dumps(obj) + "\n")
                proc.stdin.flush()
                return json.loads(proc.stdout.readline())

            init = send({"jsonrpc": "2.0", "id": 1,
                         "method": "initialize",
                         "params": {"protocolVersion": "2025-06-18",
                                    "capabilities": {},
                                    "clientInfo": {"name": "smoke",
                                                   "version": "1"}}})
            assert init["result"]["serverInfo"]["name"] == "urist"
            listed = send({"jsonrpc": "2.0", "id": 2,
                           "method": "tools/list"})
            assert len(listed["result"]["tools"]) == 6
            called = send({"jsonrpc": "2.0", "id": 3,
                           "method": "tools/call",
                           "params": {"name": "observe",
                                      "arguments": {}}})
            assert called["result"]["isError"] is False
            assert json.loads(
                called["result"]["content"][0]["text"])["tick"] == 116750
        finally:
            proc.stdin.close()
            assert proc.wait(timeout=30) == 0

    def test_server_refuses_to_start_without_daemon(self, tmp_path):
        token_file = tmp_path / "token"
        token_file.write_text("test-token\n")
        env = dict(os.environ,
                   DFH_DAEMON_URL="http://127.0.0.1:1",
                   DFH_TOKEN_FILE=str(token_file))
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "dfh-mcp")],
            capture_output=True, text=True, env=env, timeout=30)
        assert proc.returncode == 2
        assert "did not answer" in proc.stderr
