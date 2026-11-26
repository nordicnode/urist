"""Error types for the DFHack RPC client.

Two families, kept apart on purpose (see PROTOCOL.md §6: transport failure
is not action failure):

* :class:`TransportError` — the bytes never made it: connection refused,
  timeout, EOF, malformed reply. The caller does not know what the game did.
* :class:`RemoteError` — the server answered with RPC_REPLY_FAIL. DFHack
  refused the call; ``code`` carries the DFHack ``command_result`` (CR_*)
  value and ``text`` holds any console text produced before the failure.
"""

from __future__ import annotations


class DFHackError(Exception):
    """Base class for all client errors."""


class TransportError(DFHackError):
    """Local/transport failure: connect, timeout, EOF, malformed reply."""


class HandshakeError(TransportError):
    """The server did not answer the handshake with ``DFHack!\\n`` + 1."""


class RemoteError(DFHackError):
    """DFHack answered RPC_REPLY_FAIL for a call.

    Attributes:
        code: the DFHack ``command_result`` value carried in the reply
            header's size field (see :data:`COMMAND_RESULTS`).
        text: console text the server emitted before failing (may be empty).
        method: the method name that was being called, if known.
    """

    def __init__(self, code: int, text: str = "", method: str = "") -> None:
        self.code = code
        self.text = text
        self.method = method
        name = COMMAND_RESULTS.get(code, f"CR_UNKNOWN({code})")
        where = f" calling {method}" if method else ""
        super().__init__(f"DFHack failed{where}: {name} (code {code}){': ' + text if text else ''}")


#: DFHack ``command_result`` values (RemoteClient.h / CoreProtocol.proto).
COMMAND_RESULTS = {
    -3: "CR_LINK_FAILURE",
    -2: "CR_WOULD_BREAK",
    -1: "CR_NOT_IMPLEMENTED",
    0: "CR_OK",
    1: "CR_FAILURE",
    2: "CR_WRONG_USAGE",
    3: "CR_NOT_FOUND",
}
