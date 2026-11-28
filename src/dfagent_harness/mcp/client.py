"""HTTP client for the harness daemon (bearer token auth).

Same shape as the M1 driver's client (``scripts/m1_driver.py``):
stdlib ``urllib`` only, bearer token from
``~/.config/df-agent-harness/token`` (or ``DFH_AGENT_TOKEN`` when
set, or the file named by ``DFH_TOKEN_FILE``), daemon URL from
``DFH_DAEMON_URL`` (default ``http://127.0.0.1:8765``).

A daemon HTTP error becomes a :class:`DaemonError` carrying the
status, the daemon's error code, and its message, so the tools
can quote the daemon instead of inventing their own wording. A
transport failure (connection refused, timeout) becomes a
:class:`DaemonError` with status 0 and a message naming the URL.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

DEFAULT_BASE = "http://127.0.0.1:8765"
DEFAULT_TOKEN_PATH = Path.home() / ".config" / "df-agent-harness" / "token"


class DaemonError(Exception):
    """A daemon call failed. ``status`` is the HTTP status (0 when
    the daemon was never reached); ``code`` is the daemon's error
    code (``TRANSPORT`` when the daemon was never reached)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _read_token(token: Optional[str], token_path: Optional[str]) -> str:
    if token is not None:
        return token.strip()
    env_token = os.environ.get("DFH_AGENT_TOKEN")
    if env_token:
        return env_token.strip()
    path = Path(token_path) if token_path is not None else Path(
        os.environ.get("DFH_TOKEN_FILE", str(DEFAULT_TOKEN_PATH)))
    try:
        return path.read_text().strip()
    except OSError as exc:
        raise DaemonError(
            0, "NO_TOKEN",
            f"no daemon token: {path} is not readable ({exc}); "
            "start the daemon with dfh start so it writes one, "
            "or set DFH_AGENT_TOKEN") from exc


class DaemonClient:
    """Minimal daemon HTTP client. One method per verb; the tools
    decide the paths and the timeouts."""

    def __init__(self, base: Optional[str] = None,
                 token: Optional[str] = None,
                 token_path: Optional[str] = None,
                 timeout: int = 120) -> None:
        self.base = (base or os.environ.get(
            "DFH_DAEMON_URL", DEFAULT_BASE)).rstrip("/")
        self.token = _read_token(token, token_path)
        if not self.token:
            raise DaemonError(
                0, "NO_TOKEN",
                "daemon token is empty; start the daemon with "
                "dfh start so it writes one, or set DFH_AGENT_TOKEN")
        self.timeout = timeout

    def health(self) -> dict[str, Any]:
        """Liveness check; needs no auth. Raises DaemonError when
        the daemon does not answer."""
        return self._req("GET", "/v1/health", auth=False, timeout=15)

    def get(self, path: str, timeout: Optional[int] = None) -> dict[str, Any]:
        return self._req("GET", path, timeout=timeout)

    def post(self, path: str, body: Optional[dict[str, Any]] = None,
             timeout: Optional[int] = None) -> dict[str, Any]:
        return self._req("POST", path, body=body or {}, timeout=timeout)

    def _req(self, method: str, path: str,
             body: Optional[dict[str, Any]] = None,
             auth: bool = True,
             timeout: Optional[int] = None) -> dict[str, Any]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"content-type": "application/json"}
        if auth:
            headers["authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(
            self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(
                    req, timeout=self.timeout if timeout is None
                    else timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:500]
            code, message = _daemon_error(detail, exc.code)
            raise DaemonError(exc.code, code, message) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DaemonError(
                0, "TRANSPORT",
                f"daemon at {self.base} did not answer "
                f"({method} {path}: {exc}); is the daemon running? "
                "start it with dfh start") from exc


def _daemon_error(detail: str, status: int) -> tuple[str, str]:
    """Pull the daemon's own code/message out of an error body
    (``{"error": {"code", "message", "detail"}}``); fall back to
    the raw body when it is not that shape."""
    try:
        parsed = json.loads(detail)
    except ValueError:
        return "HTTP_ERROR", detail or f"HTTP {status}"
    err = parsed.get("error") if isinstance(parsed, dict) else None
    if not isinstance(err, dict):
        return "HTTP_ERROR", detail or f"HTTP {status}"
    code = err.get("code") or "HTTP_ERROR"
    message = err.get("message") or detail or f"HTTP {status}"
    return str(code), str(message)
