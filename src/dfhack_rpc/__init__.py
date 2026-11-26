"""DFHack RPC client for Dwarf Fortress 0.47.05 / DFHack 0.47.05-r5.

Public surface: :class:`DFHackClient`, the error types, and
:func:`decode_df_string`. Generated protobuf stubs live in
:mod:`dfhack_rpc.proto`.
"""

from .client import (
    DEFAULT_PORT,
    HANDSHAKE_REQUEST_MAGIC,
    HANDSHAKE_RESPONSE_MAGIC,
    MAX_MESSAGE_SIZE,
    PROTOCOL_VERSION,
    DFHackClient,
    decode_df_string,
)
from .errors import (
    COMMAND_RESULTS,
    DFHackError,
    HandshakeError,
    RemoteError,
    TransportError,
)

__all__ = [
    "DFHackClient",
    "decode_df_string",
    "DFHackError",
    "TransportError",
    "HandshakeError",
    "RemoteError",
    "COMMAND_RESULTS",
    "DEFAULT_PORT",
    "HANDSHAKE_REQUEST_MAGIC",
    "HANDSHAKE_RESPONSE_MAGIC",
    "MAX_MESSAGE_SIZE",
    "PROTOCOL_VERSION",
]
