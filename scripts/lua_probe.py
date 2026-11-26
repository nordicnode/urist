#!/usr/bin/env python3
"""Dev helper: run a Lua file against the live game and print its output.

    python scripts/lua_probe.py scratch/probe1.lua [--port 5000]

Not part of the shipped CLI; used while developing Lua helpers.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfhack_rpc import DFHackClient, DFHackError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Lua file in DF.")
    parser.add_argument("lua_file")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args(argv)
    code = Path(args.lua_file).read_text()
    try:
        with DFHackClient(args.host, args.port,
                          timeout=args.timeout) as client:
            print(client.run_lua(code, timeout=args.timeout), end="")
    except DFHackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
