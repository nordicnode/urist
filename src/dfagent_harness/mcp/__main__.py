"""Entry point: ``python -m dfagent_harness.mcp``.

Reads the daemon token, checks the daemon answers on /v1/health,
then serves MCP on stdin/stdout. Refuses to start (exit 2, clear
stderr message) when the token is missing or the daemon is down:
a hard error, never a silent stall.
"""

from __future__ import annotations

import sys
from typing import Optional

from .client import DaemonClient, DaemonError
from .protocol import run_stdio


def main(argv: Optional[list[str]] = None) -> int:
    try:
        client = DaemonClient()
    except DaemonError as exc:
        print(f"urist MCP server: cannot start: {exc.message}",
              file=sys.stderr)
        return 2
    try:
        client.health()
    except DaemonError as exc:
        print(f"urist MCP server: cannot start: {exc.message}",
              file=sys.stderr)
        return 2
    return run_stdio(client, sys.stdin, sys.stdout, sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
