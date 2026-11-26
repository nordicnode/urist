"""Tests for dfhack_rpc against the mock DFHack server.

Run from the repo root:

    .venv/bin/python -m unittest discover -s tests -v

Everything here runs offline (mock server only); no DF install needed.
"""

import socket
import struct
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfhack_rpc import (  # noqa: E402
    DFHackClient,
    HandshakeError,
    RemoteError,
    TransportError,
    decode_df_string,
)
from dfhack_rpc.client import _HEADER, _HANDSHAKE  # noqa: E402
from dfhack_rpc.proto import CoreProtocol_pb2 as core  # noqa: E402
from mock_dfhack_server import MockDFHackServer  # noqa: E402


class TestFraming(unittest.TestCase):
    """PROTOCOL.md §8 Q1: header sizes, byte-exact per the r5 sources."""

    def test_message_header_is_8_bytes(self):
        # struct RPCMessageHeader { int16_t id; int32_t size; } pads to 8.
        self.assertEqual(_HEADER.size, 8)
        packed = _HEADER.pack(-1, 0, 42)
        self.assertEqual(packed, struct.pack("<hhi", -1, 0, 42))
        self.assertEqual(_HEADER.unpack(packed), (-1, 0, 42))

    def test_handshake_header_is_12_bytes(self):
        self.assertEqual(_HANDSHAKE.size, 12)
        packed = _HANDSHAKE.pack(b"DFHack?\n", 1)
        self.assertEqual(len(packed), 12)
        self.assertEqual(_HANDSHAKE.unpack(packed), (b"DFHack?\n", 1))

    def test_quit_header(self):
        self.assertEqual(_HEADER.pack(-4, 0, 0),
                         struct.pack("<hhi", -4, 0, 0))


class TestDecodeDFString(unittest.TestCase):
    def test_valid_utf8(self):
        self.assertEqual(decode_df_string("Urist McDwarf".encode()), "Urist McDwarf")

    def test_invalid_utf8_falls_back_to_cp437(self):
        # 0x81 is invalid UTF-8 alone; CP437 0x81 is 'ü'.
        self.assertEqual(decode_df_string(b"\x81"), "ü")
        self.assertEqual(decode_df_string(b"caf\x82"), "café")


class TestClientAgainstMock(unittest.TestCase):
    def setUp(self):
        self.server = MockDFHackServer(
            lua_responses={
                'print("dfh-smoke-ok")': "dfh-smoke-ok\n",
                'print("{\\"ok\\": true}")': '{"ok": true}',
            }
        ).start()
        self.addCleanup(self.server.stop)

    def _client(self, **kwargs):
        kwargs.setdefault("timeout", 5.0)
        return DFHackClient("127.0.0.1", self.server.port, **kwargs)

    def test_full_round_trip_version(self):
        with self._client() as client:
            version = client.get_version()
        self.assertEqual(version["dwarf_fortress_version"], "0.47.05")
        self.assertEqual(version["dfhack_version"], "0.47.05-r5")
        self.assertEqual(version["remote_fortress_reader_version"],
                         "0.47.05-r5-mock")
        # BindMethod was called with the right names/plugin.
        self.assertEqual(len(self.server.binds), 1)
        bind = self.server.binds[0]
        self.assertEqual(bind["method"], "GetVersionInfo")
        self.assertEqual(bind["plugin"], "RemoteFortressReader")
        self.assertEqual(bind["input_msg"], "dfproto.EmptyMessage")
        self.assertEqual(bind["output_msg"],
                         "RemoteFortressReader.VersionInfo")

    def test_bind_result_is_cached_per_connection(self):
        with self._client() as client:
            client.get_version()
            client.get_version()
        self.assertEqual(len(self.server.binds), 1)

    def test_run_lua_collects_text_fragments(self):
        with self._client() as client:
            text = client.run_lua('print("dfh-smoke-ok")')
        # Mock sends the text as two TEXT messages; client must join them.
        self.assertEqual(text, "dfh-smoke-ok\n")

    def test_run_lua_json(self):
        with self._client() as client:
            data = client.run_lua_json('print("{\\"ok\\": true}")')
        self.assertEqual(data, {"ok": True})

    def test_run_lua_json_rejects_non_json(self):
        with self._client() as client:
            with self.assertRaises(ValueError) as ctx:
                client.run_lua_json('print("dfh-smoke-ok")')
            self.assertIn("dfh-smoke-ok", str(ctx.exception))

    def test_run_lua_cp437_fragment_decoded(self):
        # Live find (phase 1): the real server sends CP437 bytes in TEXT
        # fragments (dwarf names); the protobuf runtime hands those back
        # as `bytes`, not `str`. The client must decode them (UTF-8 if
        # valid, else CP437) instead of crashing in "".join.
        server = MockDFHackServer(
            lua_response_bytes={
                'print("name")': b"Rimtar Stinth\x84dmebzuth\n",
            }).start()
        self.addCleanup(server.stop)
        with DFHackClient("127.0.0.1", server.port, timeout=5.0) as client:
            text = client.run_lua('print("name")')
        self.assertEqual(text, "Rimtar Stinthädmebzuth\n")

    def test_run_command_returns_text(self):
        with self._client() as client:
            text = client.run_command("help")
        self.assertEqual(text, "ran: help")

    def test_remote_fail_carries_code_and_text(self):
        server = MockDFHackServer(fail_commands={"failme"}).start()
        self.addCleanup(server.stop)
        with DFHackClient("127.0.0.1", server.port, timeout=5.0) as client:
            with self.assertRaises(RemoteError) as ctx:
                client.run_command("failme")
        self.assertEqual(ctx.exception.code, 1)  # CR_FAILURE
        self.assertIn("about to fail", ctx.exception.text)
        self.assertIn("CR_FAILURE", str(ctx.exception))

    def test_bind_unknown_method_fails(self):
        server = MockDFHackServer(
            fail_bind_methods={"NoSuchMethod"}).start()
        self.addCleanup(server.stop)
        with DFHackClient("127.0.0.1", server.port, timeout=5.0) as client:
            with self.assertRaises(RemoteError) as ctx:
                client.call("NoSuchMethod", core.EmptyMessage(),
                            core.EmptyMessage,
                            input_type="dfproto.EmptyMessage",
                            output_type="dfproto.EmptyMessage")
        self.assertEqual(ctx.exception.code, -1)  # CR_NOT_IMPLEMENTED

    def test_quit_sent_on_context_exit(self):
        with self._client():
            pass
        # The quit header is sent before the socket closes, but the
        # mock server reads it on its accept thread — wait briefly
        # for it to be processed instead of racing that thread.
        deadline = time.monotonic() + 2.0
        while not self.server.quit_received and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(self.server.quit_received)

    def test_connection_refused_is_transport_error(self):
        # Find a port nothing listens on: bind one, close it, reuse it.
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        with self.assertRaises(TransportError) as ctx:
            DFHackClient("127.0.0.1", port, timeout=2.0).connect()
        self.assertIn("could not connect", str(ctx.exception))

    def test_bad_handshake(self):
        server = MockDFHackServer(fail_handshake=True).start()
        self.addCleanup(server.stop)
        with self.assertRaises(HandshakeError):
            DFHackClient("127.0.0.1", server.port, timeout=5.0).connect()

    def test_malformed_reply(self):
        server = MockDFHackServer(bad_reply=True).start()
        self.addCleanup(server.stop)
        with DFHackClient("127.0.0.1", server.port, timeout=5.0) as client:
            with self.assertRaises(TransportError) as ctx:
                client.run_command("help")
            self.assertIn("unexpected reply id 42", str(ctx.exception))

    def test_silent_server_times_out(self):
        server = MockDFHackServer(silent=True).start()
        self.addCleanup(server.stop)
        with self.assertRaises(TransportError) as ctx:
            DFHackClient("127.0.0.1", server.port, timeout=0.5).connect()
        self.assertIn("timed out", str(ctx.exception))

    def test_call_without_connect(self):
        # Self-healing contract (2026-11-26): a call on a
        # never-connected client auto-connects instead of failing —
        # a dropped/poisoned connection must not wedge the daemon.
        client = DFHackClient("127.0.0.1", self.server.port)
        try:
            text = client.run_command("help")
        finally:
            client.quit()
        self.assertTrue(client.connected is False)  # quit closed it
        self.assertIsInstance(text, str)

    def test_call_unreachable_raises(self):
        # No server listening: the auto-connect itself fails.
        client = DFHackClient("127.0.0.1", 1, timeout=1.0)
        with self.assertRaises(TransportError):
            client.run_command("help")

    def test_invalid_json_resets_and_next_call_reconnects(self):
        # A helper always prints one JSON object, so unparsable
        # output means the stream went stale: run_lua_json raises,
        # the socket is dropped, and the NEXT call reconnects
        # transparently instead of reading the stale bytes again.
        server = MockDFHackServer(lua_responses={
            'print("not json")': "not json\n",
            'print("{\\"ok\\": true}")': '{"ok": true}',
        }).start()
        self.addCleanup(server.stop)
        client = DFHackClient("127.0.0.1", server.port, timeout=5.0)
        client.connect()
        with self.assertRaises(ValueError):
            client.run_lua_json('print("not json")')
        self.assertFalse(client.connected)
        out = client.run_lua_json('print("{\\"ok\\": true}")')
        self.assertEqual(out, {"ok": True})
        self.assertTrue(client.connected)
        client.quit()

    def test_double_connect_rejected(self):
        client = self._client()
        client.connect()
        try:
            with self.assertRaises(TransportError):
                client.connect()
        finally:
            client.quit()


if __name__ == "__main__":
    unittest.main()
