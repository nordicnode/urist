#!/usr/bin/env python3
"""Smoke-test the DFHack RPC client against a (real or mock) server.

    python scripts/rpc_smoke.py --host 127.0.0.1 --port 5000

Connects, prints the DFHack version (RFR GetVersionInfo), runs one
trivial Lua snippet, and prints the results as JSON on stdout.
Exits 0 on success.

When nothing is listening it fails cleanly: a JSON error on stderr and
a non-zero exit, within the connect timeout (default 5 s) — it never
hangs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfhack_rpc import DFHackClient, DFHackError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Smoke-test the DFHack RPC client.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="DFHack RPC host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000,
                        help="DFHack RPC port (default 5000)")
    parser.add_argument("--timeout", type=float, default=5.0,
                        help="connect/call timeout in seconds (default 5)")
    args = parser.parse_args(argv)

    try:
        with DFHackClient(args.host, args.port,
                          timeout=args.timeout) as client:
            version = client.get_version()
            lua_text = client.run_lua('print("dfh-smoke-ok")')
    except DFHackError as exc:
        print(json.dumps({"ok": False, "error": str(exc),
                          "host": args.host, "port": args.port},
                         indent=2), file=sys.stderr)
        return 1

    print(json.dumps({"ok": True, "host": args.host, "port": args.port,
                      "version": version, "lua_text": lua_text}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
