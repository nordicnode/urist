#!/usr/bin/env python3
"""Observe a live Dwarf Fortress game and dump its state.

    python scripts/dfh-observe.py [--format json|text] [--section all|...]
                                  [--fps] [--host 127.0.0.1] [--port 5000]

Connects to the running game over DFHack RPC, collects the requested
sections, prints the state document (JSON) or its compact text rendering,
and exits 0. Exits 1 with a JSON error on stderr when the game is not
reachable. Read-only: nothing here changes game state.

Sections: status, units, stocks, items, buildings, jobs, reports, map,
designations. Default is all fast sections (everything except
``designations``, whose full map-block scan takes ~4 s; request it
explicitly with ``--section designations`` or ``--section all,designations``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import SECTIONS, collect, render_text  # noqa: E402
from dfagent_harness.observe import measure_fps  # noqa: E402
from dfagent_harness.read_safety import ReadRefused, paused_read  # noqa: E402
from dfhack_rpc import DFHackClient, DFHackError  # noqa: E402


def _parse_sections(value: str) -> tuple[str, ...]:
    parts = tuple(p.strip() for p in value.split(",") if p.strip())
    if not parts:
        return ("all",)
    unknown = [p for p in parts if p != "all" and p not in SECTIONS]
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown section(s): {', '.join(unknown)} "
            f"(choose from {', '.join(SECTIONS)} or all)")
    return parts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Dump live Dwarf Fortress state (read-only).")
    parser.add_argument("--host", default="127.0.0.1",
                        help="DFHack RPC host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000,
                        help="DFHack RPC port (default 5000)")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="per-call timeout in seconds (default 30)")
    parser.add_argument("--format", choices=("json", "text"),
                        default="json", help="output format (default json)")
    parser.add_argument("--section", type=_parse_sections, default=("all",),
                        help="comma-separated sections, or 'all' "
                             "(default all fast sections; add "
                             "'designations' explicitly for the slow "
                             "map-block scan)")
    parser.add_argument("--fps", action="store_true",
                        help="measure FPS with a 1 s tick sample "
                             "(only when the game is unpaused)")
    parser.add_argument("--output", type=Path, default=None,
                        help="write output to this file instead of stdout")
    args = parser.parse_args(argv)

    try:
        with DFHackClient(args.host, args.port,
                          timeout=args.timeout) as client:
            # Read safety (world-model design §8): the section dump
            # runs only while the game is verified paused. --fps is
            # the exception: it measures the tick counter while the
            # game runs (single-value reads, explicitly opt-in), so
            # it is measured first, in the game's entry state, and
            # the gated collect runs with fps=False.
            fps_value = None
            if args.fps:
                fps_value = measure_fps(client)
            state = paused_read(
                client,
                lambda: collect(client, sections=args.section,
                                timeout=args.timeout, fps=False))
            if args.fps:
                state.setdefault("meta", {})["fps"] = (
                    round(fps_value, 1) if fps_value is not None else None)
                state["meta"]["fps_measured"] = fps_value is not None
    except ReadRefused as exc:
        print(json.dumps({"ok": False, "error": f"read refused: {exc}",
                          "host": args.host, "port": args.port},
                         indent=2), file=sys.stderr)
        return 1
    except DFHackError as exc:
        print(json.dumps({"ok": False, "error": str(exc),
                          "host": args.host, "port": args.port},
                         indent=2), file=sys.stderr)
        return 1

    if args.format == "json":
        out = json.dumps(state, indent=2)
    else:
        out = render_text(state)
    if args.output is not None:
        args.output.write_text(out)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
