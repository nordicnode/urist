"""MCP over stdio: newline-delimited JSON-RPC 2.0.

One message per line on stdin, one response per line on stdout
(or nothing, for notifications). Nothing but protocol messages
goes to stdout; diagnostics go to stderr.

Handled methods: ``initialize``, ``ping``, ``tools/list``,
``tools/call``. Anything else with an id gets JSON-RPC
``-32601`` (method not found); a line that is not JSON gets
``-32700``; a JSON value that is not a request object gets
``-32600``; bad tool arguments get ``-32602``. The server never
crashes on a bad message.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from . import __version__
from .client import DaemonClient
from .tools import TOOLS, ToolArgumentError, dispatch

LATEST_VERSION = "2025-06-18"
SUPPORTED_VERSIONS = (LATEST_VERSION, "2024-11-05")
SERVER_NAME = "urist"

_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602


def _error_response(code: int, message: str,
                    req_id: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0",
            "error": {"code": code, "message": message},
            "id": req_id}


def _result_response(result: Any, req_id: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "result": result, "id": req_id}


def handle_line(client: DaemonClient, line: str) -> Optional[str]:
    """Handle one input line. Returns the response line (without
    a trailing newline), or None when no response is owed
    (notification, or a blank line)."""
    if not line.strip():
        return None
    try:
        message = json.loads(line)
    except ValueError:
        return json.dumps(_error_response(
            _PARSE_ERROR, "not valid JSON", None))
    response = handle_message(client, message)
    if response is None:
        return None
    return json.dumps(response)


def handle_message(client: DaemonClient,
                   message: Any) -> Optional[dict[str, Any]]:
    """Handle one decoded message. Returns the response object,
    or None when no response is owed (a notification)."""
    if not isinstance(message, dict):
        return _error_response(
            _INVALID_REQUEST, "a request must be a JSON object", None)
    method = message.get("method")
    if not isinstance(method, str) or not method:
        return _error_response(
            _INVALID_REQUEST, "a request needs a method string",
            message.get("id"))
    req_id = message.get("id")
    is_notification = "id" not in message
    if method.startswith("notifications/"):
        # Notifications get no response, known or not.
        return None
    if is_notification:
        # A method call without an id is a notification; the
        # methods below all need an id to answer, so there is
        # nothing to send back.
        return None
    if method == "initialize":
        return _result_response(_initialize(message.get("params")),
                                req_id)
    if method == "ping":
        return _result_response({}, req_id)
    if method == "tools/list":
        return _result_response({"tools": TOOLS}, req_id)
    if method == "tools/call":
        try:
            return _result_response(_call(client, message.get("params")),
                                    req_id)
        except _CallParamsError as exc:
            return _error_response(_INVALID_PARAMS, str(exc), req_id)
    return _error_response(
        _METHOD_NOT_FOUND, f"no such method: {method}", req_id)


def _initialize(params: Any) -> dict[str, Any]:
    requested = None
    if isinstance(params, dict):
        requested = params.get("protocolVersion")
    version = (requested if requested in SUPPORTED_VERSIONS
               else LATEST_VERSION)
    return {
        "protocolVersion": version,
        "capabilities": {"tools": {}},
        "serverInfo": {"name": SERVER_NAME, "version": __version__},
    }


def _call(client: DaemonClient, params: Any) -> dict[str, Any]:
    if not isinstance(params, dict):
        raise _CallParamsError(
            "tools/call params must be an object")
    name = params.get("name")
    if not isinstance(name, str) or not name:
        raise _CallParamsError(
            "tools/call needs a tool name string")
    arguments = params.get("arguments", {})
    try:
        return dispatch(client, name, arguments)
    except ToolArgumentError as exc:
        raise _CallParamsError(str(exc)) from exc


class _CallParamsError(Exception):
    """A tools/call request itself is malformed (not a tool
    failure: those come back as isError results). The protocol
    layer converts this to -32602."""


def run_stdio(client: DaemonClient, stdin: Any, stdout: Any,
              stderr: Any) -> int:
    """Serve MCP on the given streams until EOF. Returns 0.
    A _CallParamsError from tools/call is answered -32602;
    anything else unexpected is answered -32603 instead of
    killing the server."""
    print(f"urist MCP server {__version__} "
          f"(daemon {client.base})", file=stderr, flush=True)
    for line in stdin:
        try:
            response = handle_line(client, line)
        except _CallParamsError as exc:
            req_id = _request_id_of(line)
            response = json.dumps(_error_response(
                _INVALID_PARAMS, str(exc), req_id))
        except Exception as exc:  # noqa: BLE001 - never die on input
            req_id = _request_id_of(line)
            response = json.dumps(_error_response(
                -32603, f"internal error: {exc}", req_id))
        if response is not None:
            stdout.write(response + "\n")
            stdout.flush()
    return 0


def _request_id_of(line: str) -> Any:
    """Best-effort id recovery for an error response when the
    normal handler died; None when the line carries no id."""
    try:
        message = json.loads(line)
    except ValueError:
        return None
    if isinstance(message, dict):
        return message.get("id")
    return None
