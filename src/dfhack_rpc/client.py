"""Minimal DFHack RPC client (DFHack 0.47.05-r5 wire protocol).

Written from scratch against the protocol spec in ``docs/PROTOCOL.md``
and the 0.47.05-r5 server sources (``library/RemoteServer.cpp``,
``library/RemoteClient.cpp``, ``library/include/RemoteClient.h``).
Stdlib + ``protobuf`` runtime only.

Wire summary (all integers little-endian; see PROTOCOL.md §2.3):

* Handshake (12 bytes): client sends ``b"DFHack?\\n"`` + int32 1; server
  replies ``b"DFHack!\\n"`` + int32 1. Anything else aborts.
* Request header (8 bytes): ``struct.pack("<hhi", method_id, 0, size)``.
  The 8 bytes are *not* a mistake: the C struct is
  ``struct RPCMessageHeader { int16_t id; int32_t size; };`` and C++
  alignment pads it to 8 bytes. Both the server and the reference client
  read/write ``sizeof(header)`` == 8. This resolves PROTOCOL.md §8
  open question #1 — verified against the 0.47.05-r5 sources (the server
  reads ``sizeof(RPCMessageHeader)`` and the reference client sends the
  same); still to be confirmed against the live game in phase 1.
* Reply: zero or more TEXT messages (id -3, body ``CoreTextNotification``),
  then exactly one terminal message — RESULT (id -1, body is the method's
  output protobuf) or FAIL (id -2, the *size field itself* holds the
  DFHack ``command_result`` code; no body).
* Quit: header (id -4, size 0), then close immediately.

Usage::

    from dfhack_rpc import DFHackClient

    with DFHackClient("127.0.0.1", 5000) as client:
        print(client.get_version())
        print(client.run_lua('print("hello")'))

Rules: one connection, calls serialized (a lock guards concurrent
callers); every socket operation has a timeout; no retries — callers
decide what a failure means.
"""

from __future__ import annotations

import json
import socket
import struct
import threading
from types import TracebackType
from typing import Optional, Type, TypeVar

from google.protobuf.message import Message

from . import methods as _methods
from .errors import HandshakeError, RemoteError, TransportError
from .proto import CoreProtocol_pb2 as core

__all__ = [
    "DFHackClient",
    "decode_df_string",
    "HANDSHAKE_REQUEST_MAGIC",
    "HANDSHAKE_RESPONSE_MAGIC",
    "PROTOCOL_VERSION",
    "MAX_MESSAGE_SIZE",
    "DEFAULT_PORT",
]

#: Default DFHack RPC port (RemoteClient.h: DEFAULT_PORT = 5000).
DEFAULT_PORT = 5000

HANDSHAKE_REQUEST_MAGIC = b"DFHack?\n"
HANDSHAKE_RESPONSE_MAGIC = b"DFHack!\n"
PROTOCOL_VERSION = 1

#: ``struct RPCMessageHeader { int16_t id; int32_t size; }`` — 8 bytes on
#: the wire because of C++ alignment padding (see module docstring).
_HEADER = struct.Struct("<hhi")
#: ``struct RPCHandshakeHeader { char magic[8]; int version; }`` — 12 bytes.
_HANDSHAKE = struct.Struct("<8si")

#: Reply / request codes (RemoteClient.h: DFHackReplyCode).
RPC_REPLY_RESULT = -1
RPC_REPLY_FAIL = -2
RPC_REPLY_TEXT = -3
RPC_REQUEST_QUIT = -4

#: Hardcoded method ids: 0 = BindMethod, 1 = RunCommand.
BIND_METHOD_ID = 0
RUN_COMMAND_ID = 1

#: Max protobuf payload (RemoteClient.h: MAX_MESSAGE_SIZE = 64 MiB).
MAX_MESSAGE_SIZE = 64 * 1024 * 1024

M = TypeVar("M", bound=Message)


def decode_df_string(data: bytes) -> str:
    """Decode a DF string: UTF-8 if valid, else CP437 (PROTOCOL.md §1.2)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp437")


class DFHackClient:
    """One TCP connection to a DFHack RPC server.

    Args:
        host: server host (DFHack binds 127.0.0.1 by default).
        port: server port (5000 default; DFHACK_PORT / dfkit use 5001).
        timeout: default timeout in seconds for every socket operation,
            including the initial connect.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT,
                 timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._bind_cache: dict[tuple[str, str], int] = {}
        # Calls are serialized: the server handles one request at a time
        # per connection and replies interleave TEXT + RESULT/FAIL.
        self._lock = threading.Lock()

    # -- lifecycle ------------------------------------------------------

    def connect(self) -> "DFHackClient":
        """Open the TCP connection and complete the handshake."""
        if self._sock is not None:
            raise TransportError("already connected; close() first")
        try:
            sock = socket.create_connection(
                (self.host, self.port), timeout=self.timeout)
        except (OSError, socket.timeout) as exc:
            raise TransportError(
                f"could not connect to DFHack RPC at "
                f"{self.host}:{self.port}: {exc}") from exc
        self._sock = sock
        try:
            sock.settimeout(self.timeout)
            self._handshake()
        except BaseException:
            self._close_socket()
            raise
        return self

    def close(self) -> None:
        """Close the socket without sending the quit header."""
        self._close_socket()

    def quit(self) -> None:
        """Send the RPC_REQUEST_QUIT header, then close immediately.

        Best effort: errors while quitting are ignored — the socket is
        being torn down either way.
        """
        if self._sock is not None:
            try:
                self._send_all(_HEADER.pack(RPC_REQUEST_QUIT, 0, 0))
            except OSError:
                pass
        self._close_socket()

    def _close_socket(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._bind_cache.clear()

    def reset(self) -> None:
        """Drop the connection, discarding any buffered bytes.

        Call this when a reply looks stale or unparsable: after a
        timeout mid-reply the socket can hold a partial reply, and
        the next call would read those bytes as its own reply
        (observed live 2026-11-26: empty TEXT, wrong-section JSON).
        The next call reconnects transparently (see :meth:`call_raw`).
        Idempotent.
        """
        self._close_socket()

    def __enter__(self) -> "DFHackClient":
        return self.connect()

    def __exit__(self, exc_type: Optional[type[BaseException]],
                 exc: Optional[BaseException],
                 tb: Optional[TracebackType]) -> None:
        self.quit()

    @property
    def connected(self) -> bool:
        return self._sock is not None

    # -- low-level framing ----------------------------------------------

    def _handshake(self) -> None:
        assert self._sock is not None
        self._send_all(_HANDSHAKE.pack(HANDSHAKE_REQUEST_MAGIC,
                                       PROTOCOL_VERSION))
        reply = self._recv_exact(_HANDSHAKE.size)
        magic, version = _HANDSHAKE.unpack(reply)
        if magic != HANDSHAKE_RESPONSE_MAGIC or version != PROTOCOL_VERSION:
            raise HandshakeError(
                f"bad handshake reply from {self.host}:{self.port}: "
                f"magic={magic!r} version={version} "
                f"(expected {HANDSHAKE_RESPONSE_MAGIC!r} + {PROTOCOL_VERSION})")

    def _send_all(self, data: bytes) -> None:
        assert self._sock is not None
        try:
            self._sock.sendall(data)
        except (OSError, socket.timeout) as exc:
            raise TransportError(f"send failed: {exc}") from exc

    def _recv_exact(self, n: int) -> bytes:
        """Read exactly n bytes or raise TransportError (EOF/timeout)."""
        assert self._sock is not None
        chunks: list[bytes] = []
        remaining = n
        try:
            while remaining:
                chunk = self._sock.recv(remaining)
                if not chunk:
                    raise TransportError(
                        f"connection closed by server while reading "
                        f"{n} bytes ({n - remaining} received)")
                chunks.append(chunk)
                remaining -= len(chunk)
        except socket.timeout as exc:
            raise TransportError(
                f"timed out after {self.timeout}s reading {n} bytes") from exc
        except OSError as exc:
            raise TransportError(f"recv failed: {exc}") from exc
        return b"".join(chunks)

    def _read_header(self) -> tuple[int, int]:
        raw = self._recv_exact(_HEADER.size)
        method_id, _pad, size = _HEADER.unpack(raw)
        return method_id, size

    # -- core call path ---------------------------------------------------

    def call_raw(self, method_id: int, payload: bytes,
                 timeout: Optional[float] = None,
                 method: str = "") -> tuple[bytes, str]:
        """Send one request, collect TEXT, return (result_payload, text).

        Self-healing: if a call fails after its request was sent
        (timeout, I/O error, malformed reply), the socket may hold a
        partial reply — the next call would read those stale bytes as
        its own reply (observed live 2026-11-26: a 30s timeout
        reading a reply header, after which every call returned
        empty TEXT in ~300ms). The connection is therefore dropped
        on any such failure and the next call reconnects
        transparently. The failed call is NOT retried: its Lua may
        already have run server-side.

        Raises:
            TransportError: send/recv failure, timeout, malformed reply.
            RemoteError: server answered RPC_REPLY_FAIL (code carried).
        """
        if len(payload) > MAX_MESSAGE_SIZE:
            raise TransportError(
                f"request payload {len(payload)} bytes exceeds "
                f"max {MAX_MESSAGE_SIZE}")
        with self._lock:
            if self._sock is None:
                self.connect()
            if timeout is not None:
                self._sock.settimeout(timeout)
            try:
                self._send_all(_HEADER.pack(method_id, 0, len(payload)) + payload)
                return self._collect_reply(method=method)
            except BaseException:
                self._close_socket()
                raise
            finally:
                if timeout is not None and self._sock is not None:
                    try:
                        self._sock.settimeout(self.timeout)
                    except OSError:
                        pass

    def _collect_reply(self, method: str = "") -> tuple[bytes, str]:
        """Read TEXT messages until the terminal RESULT/FAIL.

        For FAIL the header's size field *is* the DFHack ``command_result``
        code (no body follows); it is raised as RemoteError with the
        console text collected so far attached.
        """
        texts: list[str] = []
        while True:
            method_id, size = self._read_header()
            if method_id == RPC_REPLY_FAIL:
                raise RemoteError(code=size, text="".join(texts),
                                  method=method)
            if size < 0 or size > MAX_MESSAGE_SIZE:
                raise TransportError(
                    f"malformed reply: id={method_id} size={size} "
                    f"(max {MAX_MESSAGE_SIZE})")
            payload = self._recv_exact(size)
            if method_id == RPC_REPLY_RESULT:
                return payload, "".join(texts)
            if method_id == RPC_REPLY_TEXT:
                note = core.CoreTextNotification()
                try:
                    note.ParseFromString(payload)
                except Exception as exc:
                    raise TransportError(
                        f"malformed CoreTextNotification: {exc}") from exc
                # Fragment text is declared `string` in the proto, but the
                # protobuf runtime hands back `bytes` when the server sent
                # bytes that are not valid UTF-8 — which is exactly what
                # happens with CP437 dwarf names (e.g. 0x84 = 'ä').
                # Found live in phase 1: decode each fragment the DF way
                # (UTF-8 if valid, else CP437) instead of assuming str.
                texts.append("".join(
                    f.text if isinstance(f.text, str)
                    else decode_df_string(f.text)
                    for f in note.fragments))
                continue
            raise TransportError(
                f"malformed reply: unexpected reply id {method_id}")

    # -- binding ----------------------------------------------------------

    def bind(self, method: str, input_msg: str, output_msg: str,
             plugin: str = "") -> int:
        """Resolve a method name to a numeric id (cached per connection).

        ``plugin`` empty means the core service (RemoteServer.cpp:
        findFunction uses core_service when the plugin string is empty).
        """
        key = (plugin, method)
        cached = self._bind_cache.get(key)
        if cached is not None:
            return cached
        req = core.CoreBindRequest(method=method, input_msg=input_msg,
                                   output_msg=output_msg, plugin=plugin)
        payload, _text = self.call_raw(BIND_METHOD_ID,
                                       req.SerializeToString(),
                                       method="BindMethod")
        reply = core.CoreBindReply()
        try:
            reply.ParseFromString(payload)
        except Exception as exc:
            raise TransportError(
                f"malformed CoreBindReply for {method}: {exc}") from exc
        self._bind_cache[key] = reply.assigned_id
        return reply.assigned_id

    def call(self, method: str, input_msg: Message,
             output_cls: Optional[Type[M]] = None,
             plugin: str = _methods.PLUGIN,
             input_type: str = "", output_type: str = "",
             timeout: Optional[float] = None) -> tuple[M, str]:
        """Call a bound method by name; return (parsed output, text).

        For methods in the :mod:`dfhack_rpc.methods` table the protobuf
        type names and output class are filled in automatically; otherwise
        pass ``input_type``/``output_type`` explicitly (fully-qualified,
        e.g. ``"dfproto.EmptyMessage"``) and ``output_cls``.
        """
        spec = _methods.METHODS.get(method) if plugin == _methods.PLUGIN else None
        if spec is not None:
            input_type = input_type or spec.input_msg
            output_type = output_type or spec.output_msg
            output_cls = output_cls or spec.output_cls
        if not input_type or not output_type or output_cls is None:
            raise ValueError(
                f"unknown method {plugin}::{method}: pass input_type, "
                f"output_type and output_cls explicitly "
                f"(not in the method table)")
        method_id = self.bind(method, input_type, output_type, plugin)
        payload, text = self.call_raw(
            method_id, input_msg.SerializeToString(), timeout=timeout,
            method=f"{plugin}::{method}")
        out = output_cls()
        try:
            out.ParseFromString(payload)
        except Exception as exc:
            raise TransportError(
                f"malformed {output_type} reply for {method}: {exc}") from exc
        return out, text

    # -- convenience ------------------------------------------------------

    def run_command(self, command: str, *args: str,
                    timeout: Optional[float] = None) -> str:
        """Run a DFHack console command; return its console text.

        Output is whatever the command prints, delivered as TEXT
        notifications before the RESULT (which is EmptyMessage).
        """
        req = core.CoreRunCommandRequest(command=command, arguments=list(args))
        _payload, text = self.call_raw(RUN_COMMAND_ID,
                                       req.SerializeToString(),
                                       timeout=timeout,
                                       method=f"RunCommand({command})")
        return text

    def run_lua(self, code: str,
                timeout: Optional[float] = None) -> str:
        """Evaluate arbitrary Lua via ``RunCommand("lua", code)``.

        Returns the text the snippet printed. Convention (PROTOCOL.md
        §2.6): helper snippets print exactly one JSON object; use
        :meth:`run_lua_json` to parse it.
        """
        return self.run_command("lua", code, timeout=timeout)

    def run_lua_json(self, code: str,
                     timeout: Optional[float] = None) -> object:
        """Like :meth:`run_lua`, but parse the printed text as JSON.

        Raises ValueError if the output is not valid JSON (the raw text
        is attached to the exception for debugging).
        """
        text = self.run_lua(code, timeout=timeout)
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError as exc:
            # A helper always prints exactly one JSON object, so
            # unparsable output means the stream is stale/misaligned
            # (a previous call's leftover reply) — drop the
            # connection so the next call starts clean.
            self.reset()
            raise ValueError(
                f"Lua output was not valid JSON: {exc}; raw text: {text!r}"
            ) from exc

    def get_version(self) -> dict[str, str]:
        """Version probe via RFR ``GetVersionInfo``.

        There is no core ``GetVersion`` RPC at 0.47.05-r5 (PROTOCOL.md
        §2.5); RFR's GetVersionInfo is the equivalent probe. Returns e.g.
        ``{"dwarf_fortress_version": "0.47.05",
        "dfhack_version": "0.47.05-r5",
        "remote_fortress_reader_version": "..."}``.
        """
        from .proto import RemoteFortressReader_pb2 as rfr

        info, _text = self.call("GetVersionInfo", core.EmptyMessage(),
                                rfr.VersionInfo)
        return {
            "dwarf_fortress_version": info.dwarf_fortress_version,
            "dfhack_version": info.dfhack_version,
            "remote_fortress_reader_version": info.remote_fortress_reader_version,
        }
