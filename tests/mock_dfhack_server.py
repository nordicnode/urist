"""A fake DFHack RPC server for offline tests.

Speaks the wire protocol exactly as the real 0.47.05-r5 server does
(12-byte handshake, 8-byte message headers, TEXT then RESULT/FAIL),
but with scripted replies. Used by tests/test_client.py and
tests/test_smoke.py — no DF install needed.

Behaviour (configurable per instance):

* ``lua_responses``: dict mapping exact Lua code -> text the server
  "prints" (sent as two TEXT messages to exercise the client's
  collection loop). Unknown code gets ``lua-ok: <code>``.
* ``lua_response_bytes``: dict mapping exact Lua code -> raw bytes the
  server "prints" as one TEXT fragment. Used to reproduce the real
  server sending CP437 bytes (invalid UTF-8) in a fragment, which the
  protobuf runtime hands back as ``bytes`` rather than ``str``.
* ``fail_bind_methods``: method names for which BindMethod answers FAIL
  with CR_NOT_IMPLEMENTED.
* ``fail_commands``: console commands answered FAIL with CR_FAILURE
  (after one TEXT line ``"about to fail"``).
* ``fail_handshake``: reply with a wrong magic/version instead of
  ``DFHack!\\n`` + 1.
* ``bad_reply``: after the next request, send a header with an unknown
  reply id (42) and close — exercises the client's malformed-reply path.
* ``silent``: accept the connection and then never speak (client must
  time out, not hang).
"""

from __future__ import annotations

import socket
import struct
import threading
import time

from dfhack_rpc.proto import CoreProtocol_pb2 as core
from dfhack_rpc.proto import RemoteFortressReader_pb2 as rfr

_HEADER = struct.Struct("<hhi")
_HANDSHAKE = struct.Struct("<8si")

RPC_REPLY_RESULT = -1
RPC_REPLY_FAIL = -2
RPC_REPLY_TEXT = -3
RPC_REQUEST_QUIT = -4
BIND_METHOD_ID = 0
RUN_COMMAND_ID = 1

CR_NOT_IMPLEMENTED = -1
CR_FAILURE = 1
CR_NOT_FOUND = 3


class MockDFHackServer:
    """A scripted DFHack server on an ephemeral localhost port."""

    def __init__(self, *, lua_responses=None, lua_response_bytes=None,
                 fail_bind_methods=(), fail_commands=(), fail_handshake=False,
                 bad_reply=False, silent=False):
        self.lua_responses = dict(lua_responses or {})
        self.lua_response_bytes = dict(lua_response_bytes or {})
        self.fail_bind_methods = set(fail_bind_methods)
        self.fail_commands = set(fail_commands)
        self.fail_handshake = fail_handshake
        self.bad_reply = bad_reply
        self.silent = silent

        self.binds: list[dict] = []      # every BindMethod request seen
        self.quit_received = False
        self.connections = 0
        self.version = {
            "dwarf_fortress_version": "0.47.05",
            "dfhack_version": "0.47.05-r5",
            "remote_fortress_reader_version": "0.47.05-r5-mock",
        }

        self._listener: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._next_id = 100
        self._assigned: dict[int, str] = {}  # method id -> method name

    # -- lifecycle ------------------------------------------------------

    @property
    def port(self) -> int:
        assert self._listener is not None
        return self._listener.getsockname()[1]

    def start(self) -> "MockDFHackServer":
        self._listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._listener.bind(("127.0.0.1", 0))
        self._listener.listen(8)
        self._listener.settimeout(0.2)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._listener is not None:
            self._listener.close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def __enter__(self) -> "MockDFHackServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    # -- serving --------------------------------------------------------

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._stop.is_set():
            try:
                conn, _addr = self._listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.connections += 1
            try:
                self._handle(conn)
            except OSError:
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def _recv_exact(self, conn: socket.socket, n: int) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("client closed connection")
            buf += chunk
        return bytes(buf)

    def _send_header(self, conn: socket.socket, msg_id: int, size: int) -> None:
        conn.sendall(_HEADER.pack(msg_id, 0, size))

    def _send_message(self, conn: socket.socket, msg_id: int, payload: bytes) -> None:
        self._send_header(conn, msg_id, len(payload))
        conn.sendall(payload)

    def _send_text(self, conn: socket.socket, text: str) -> None:
        note = core.CoreTextNotification()
        frag = note.fragments.add()
        frag.text = text
        self._send_message(conn, RPC_REPLY_TEXT, note.SerializeToString())

    @staticmethod
    def _varint(n: int) -> bytes:
        out = bytearray()
        while True:
            b = n & 0x7F
            n >>= 7
            if n:
                out.append(b | 0x80)
            else:
                out.append(b)
                return bytes(out)

    def _send_raw_text(self, conn: socket.socket, raw: bytes) -> None:
        """Send one TEXT fragment with raw bytes, hand-encoded.

        A CoreTextFragment is field 1 (string) of CoreTextNotification;
        assigning raw non-UTF-8 bytes via the protobuf API is not
        possible, so the wire bytes are built directly. This is what
        the real server sends for CP437 text.
        """
        frag = b"\x0a" + self._varint(len(raw)) + raw
        note = b"\x0a" + self._varint(len(frag)) + frag
        self._send_message(conn, RPC_REPLY_TEXT, note)

    def _send_fail(self, conn: socket.socket, code: int) -> None:
        # FAIL carries the CR_* code in the size field; no body.
        self._send_header(conn, RPC_REPLY_FAIL, code)

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(5.0)
        if self.silent:
            time.sleep(2.0)
            return
        raw = self._recv_exact(conn, _HANDSHAKE.size)
        magic, version = _HANDSHAKE.unpack(raw)
        if self.fail_handshake:
            conn.sendall(_HANDSHAKE.pack(b"DFHack?\n", 99))
            return
        if magic != b"DFHack?\n" or version != 1:
            return  # real server just drops the connection
        conn.sendall(_HANDSHAKE.pack(b"DFHack!\n", 1))

        while True:
            raw = self._recv_exact(conn, _HEADER.size)
            method_id, _pad, size = _HEADER.unpack(raw)
            if method_id == RPC_REQUEST_QUIT:
                self.quit_received = True
                return
            if size < 0 or size > 64 * 1024 * 1024:
                return
            payload = self._recv_exact(conn, size) if size else b""
            if self.bad_reply:
                self._send_header(conn, 42, 0)
                return
            self._dispatch(conn, method_id, payload)

    def _dispatch(self, conn: socket.socket, method_id: int, payload: bytes) -> None:
        if method_id == BIND_METHOD_ID:
            req = core.CoreBindRequest()
            req.ParseFromString(payload)
            self.binds.append({
                "method": req.method, "plugin": req.plugin,
                "input_msg": req.input_msg, "output_msg": req.output_msg,
            })
            if req.method in self.fail_bind_methods:
                self._send_fail(conn, CR_NOT_IMPLEMENTED)
                return
            assigned = self._next_id
            self._next_id += 1
            self._assigned[assigned] = req.method
            reply = core.CoreBindReply(assigned_id=assigned)
            self._send_message(conn, RPC_REPLY_RESULT, reply.SerializeToString())
            return

        if method_id == RUN_COMMAND_ID:
            req = core.CoreRunCommandRequest()
            req.ParseFromString(payload)
            if req.command in self.fail_commands:
                self._send_text(conn, "about to fail")
                self._send_fail(conn, CR_FAILURE)
                return
            if req.command == "lua" and req.arguments:
                code = req.arguments[0]
                if code in self.lua_response_bytes:
                    self._send_raw_text(conn, self.lua_response_bytes[code])
                    self._send_message(conn, RPC_REPLY_RESULT,
                                       core.EmptyMessage().SerializeToString())
                    return
                text = self.lua_responses.get(code, f"lua-ok: {code}")
                # Two TEXT messages: exercises the client's collect loop.
                half = len(text) // 2
                self._send_text(conn, text[:half])
                self._send_text(conn, text[half:])
                self._send_message(conn, RPC_REPLY_RESULT,
                                   core.EmptyMessage().SerializeToString())
                return
            self._send_text(conn, f"ran: {req.command}")
            self._send_message(conn, RPC_REPLY_RESULT,
                               core.EmptyMessage().SerializeToString())
            return

        name = self._assigned.get(method_id)
        if name == "GetVersionInfo":
            info = rfr.VersionInfo(**self.version)
            self._send_message(conn, RPC_REPLY_RESULT, info.SerializeToString())
            return
        self._send_fail(conn, CR_NOT_FOUND)
