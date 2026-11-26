#!/usr/bin/env python3
"""Run one verified DF action from the command line and print its JSON result.

    python scripts/dfh-act.py dig --box 90,90,41,92,92,41
    python scripts/dfh-act.py dig --box 90,90,41,92,92,41 --mode clear
    python scripts/dfh-act.py chop --box 98,100,32,104,106,32
    python scripts/dfh-act.py gather --box 95,96,42,99,100,42
    python scripts/dfh-act.py order-create --job MakeBarrel --amount 5
    python scripts/dfh-act.py order-remove --id 3
    python scripts/dfh-act.py build --kind carpenter --pos 85,85,42
    python scripts/dfh-act.py labor --unit "Deduk Stâkudunib" --labor CARPENTER --off

Every action checks world state before and after (see
``src/dfagent_harness/actions.py``) and prints one JSON object with
``ok``, ``before``, ``after``, ``reason`` and ``error_kind``. Exit 0
when the action verified, 1 when it ran but failed (precondition,
verification, timeout or transport — see the JSON), 2 for bad arguments.
A failed action never retries; re-read state before running it again.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import actions  # noqa: E402
from dfhack_rpc import DFHackClient, DFHackError  # noqa: E402


def _box(value: str) -> tuple[int, ...]:
    parts = value.split(",")
    if len(parts) != 6:
        raise argparse.ArgumentTypeError(
            "box must be x0,y0,z0,x1,y1,z1 (6 ints)")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "box must be x0,y0,z0,x1,y1,z1 (6 ints)") from None


def _pos(value: str) -> tuple[int, int, int]:
    parts = value.split(",")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("pos must be x,y,z (3 ints)")
    try:
        return tuple(int(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        raise argparse.ArgumentTypeError("pos must be x,y,z (3 ints)") from None


def _unit(value: str) -> str | int:
    try:
        return int(value)
    except ValueError:
        return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one verified DF action (see docs/ACTIONS.md).")
    parser.add_argument("--host", default="127.0.0.1",
                        help="DFHack RPC host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000,
                        help="DFHack RPC port (default 5000)")
    parser.add_argument("--timeout", type=float, default=30.0,
                        help="per-call timeout in seconds (default 30)")
    sub = parser.add_subparsers(dest="action", required=True)

    p = sub.add_parser("dig", help="designate a rectangle for digging")
    p.add_argument("--box", type=_box, required=True)
    p.add_argument("--mode", choices=sorted(actions.DIG_MODES),
                   default="dig")

    p = sub.add_parser("chop", help="mark trees for chopping in an area")
    p.add_argument("--box", type=_box, required=True)
    p.add_argument("--unmark", action="store_true",
                   help="remove the chop marking instead of setting it")
    p.add_argument("--job-timeout", type=float,
                   default=actions.DEFAULT_JOB_TIMEOUT,
                   help="seconds to wait for a FellTree job to appear "
                        "(default 30)")

    p = sub.add_parser("gather", help="mark shrubs for gathering in an area")
    p.add_argument("--box", type=_box, required=True)
    p.add_argument("--unmark", action="store_true",
                   help="remove the gather marking instead of setting it")
    p.add_argument("--job-timeout", type=float,
                   default=actions.DEFAULT_JOB_TIMEOUT,
                   help="seconds to wait for a GatherPlants job to appear "
                        "(default 30)")

    p = sub.add_parser("order-create", help="create a manager order")
    p.add_argument("--job", required=True,
                   help="df.job_type name, e.g. MakeBarrel")
    p.add_argument("--amount", type=int, default=1)

    p = sub.add_parser("order-remove", help="remove a manager order by id")
    p.add_argument("--id", type=int, required=True)

    p = sub.add_parser("build", help="place a workshop and wait for it")
    p.add_argument("--kind", choices=sorted(actions.WORKSHOP_CATALOG),
                   required=True)
    p.add_argument("--pos", type=_pos, required=True,
                   help="corner tile x,y,z")
    p.add_argument("--build-timeout", type=float,
                   default=actions.DEFAULT_BUILD_TIMEOUT,
                   help="seconds to wait for construction (default 120)")

    p = sub.add_parser("labor", help="enable/disable a labor on a citizen")
    p.add_argument("--unit", type=_unit, required=True,
                   help="citizen name (exact) or unit id")
    p.add_argument("--labor", required=True,
                   help="df.unit_labor name, e.g. MINE")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--on", dest="on", action="store_true")
    group.add_argument("--off", dest="on", action="store_false")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    kwargs: dict = {}
    if args.action == "dig":
        kwargs = {"box": args.box, "mode": args.mode}
    elif args.action == "chop":
        kwargs = {"box": args.box, "mark": not args.unmark,
                  "job_timeout": args.job_timeout}
    elif args.action == "gather":
        kwargs = {"box": args.box, "mark": not args.unmark,
                  "job_timeout": args.job_timeout}
    elif args.action == "order-create":
        kwargs = {"job_type": args.job, "amount": args.amount}
    elif args.action == "order-remove":
        kwargs = {"order_id": args.id}
    elif args.action == "build":
        kwargs = {"kind": args.kind, "pos": args.pos,
                  "build_timeout": args.build_timeout}
    elif args.action == "labor":
        kwargs = {"unit": args.unit, "labor": args.labor, "on": args.on}
    try:
        with DFHackClient(args.host, args.port,
                          timeout=args.timeout) as client:
            result = actions.act(client, _CLI_ACTIONS[args.action],
                                 timeout=args.timeout, **kwargs)
    except DFHackError as exc:
        print(json.dumps({"ok": False, "action": args.action,
                          "error_kind": "transport",
                          "reason": f"could not reach the game: {exc}"},
                         indent=2))
        return 1
    print(json.dumps(result.to_dict(), indent=2))
    return 0 if result.ok else 1


#: CLI verb -> act() action name.
_CLI_ACTIONS = {
    "dig": "designate_dig",
    "chop": "designate_chop",
    "gather": "designate_gather",
    "order-create": "manager_order_create",
    "order-remove": "manager_order_remove",
    "build": "build_workshop",
    "labor": "labor_toggle",
}


if __name__ == "__main__":
    raise SystemExit(main())
