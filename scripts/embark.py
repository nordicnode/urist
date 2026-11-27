#!/usr/bin/env python3
"""Embark driver: run the embark module end to end from the CLI.

This is the pre-game setup driver (the sanctioned UI-keystroke path —
see src/dfagent_harness/embark.py). It drives one DF instance on one
Xvfb display and one RPC port; it never touches the main fort's DF
(unless you point it at it — do not).

Modes (run one per invocation; --full chains them):
  --gen            generate the world (DF must NOT be running on this
                   dir; ./dfhack -gen runs and exits).
  --to-screen      navigate Title -> Start Playing -> Dwarf Fortress
                   -> the embark screen (DF must be running, on the
                   title screen).
  --screen-only    write the profile and run fileresult; print the
                   match count (DF must be on the embark screen).
  --full           gen + launch DF + navigate + embark end to end
                   (launches ./dfhack on the display, waits for RPC,
                   then navigates and embarks). The fort is left
                   paused in fortress mode and quicksaved.

Usage:
  .venv/bin/python scripts/embark.py --df-dir scratch/m2-embark/df \\
      --display :98 --port 5001 --region 3 --seed 20261128 --full
  .venv/bin/python scripts/embark.py --df-dir scratch/m2-embark/df \\
      --display :98 --port 5001 --screen-only
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS / "src"))

from dfagent_harness import embark, ui  # noqa: E402
from dfhack_rpc import DFHackClient  # noqa: E402


def _wait_rpc(host: str, port: int, timeout: float = 120.0) -> None:
    """Wait until the DFHack RPC port accepts a TCP connection."""
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return
        except OSError:
            time.sleep(2.0)
    raise SystemExit(f"embark: RPC port {port} never came up")


def _launch_df(df_dir: Path, display: str) -> subprocess.Popen:
    """Launch ./dfhack on the display (deblibs LD_LIBRARY_PATH)."""
    env = dict(os.environ)
    env["DISPLAY"] = display
    ldpath = HARNESS / "scratch" / "deblibs-ldpath.txt"
    if ldpath.is_file():
        env["LD_LIBRARY_PATH"] = ldpath.read_text().strip()
    proc = subprocess.Popen(["./dfhack"], cwd=df_dir, env=env,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    return proc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--df-dir", required=True,
                        help="DF install dir (e.g. scratch/m2-embark/df)")
    parser.add_argument("--display", default=":98")
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--region", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20261128)
    parser.add_argument("--preset", default="SMALL REGION")
    parser.add_argument("--gen", action="store_true",
                        help="generate the world and exit")
    parser.add_argument("--to-screen", action="store_true",
                        help="navigate to the embark screen and exit")
    parser.add_argument("--screen-only", action="store_true",
                        help="profile + fileresult only, print the count")
    parser.add_argument("--full", action="store_true",
                        help="gen + launch + navigate + embark")
    parser.add_argument("--profile", default="m2",
                        choices=["m2"],
                        help="finder profile to use (m2 only for now)")
    args = parser.parse_args(argv)

    df_dir = Path(args.df_dir)
    if not df_dir.is_dir():
        print(f"embark: no such DF dir: {df_dir}", file=sys.stderr)
        return 2
    profile = dict(embark.M2_PROFILE)

    if args.gen or args.full:
        print(f"embark: generating world region{args.region} "
              f"seed={args.seed} preset={args.preset!r} ...",
              flush=True)
        res = embark.generate_world(df_dir, args.region, args.seed,
                                    args.preset)
        print(f"embark: world generated: {res}", flush=True)
        if args.gen and not args.full:
            return 0

    proc = None
    if args.full:
        print(f"embark: launching ./dfhack on {args.display} ...",
              flush=True)
        proc = _launch_df(df_dir, args.display)
        _wait_rpc(args.host, args.port, timeout=180.0)
        print("embark: RPC up, waiting for the title screen ...",
              flush=True)
        time.sleep(5.0)

    wid = ui.df_window_id(args.display)
    if wid is None:
        print(f"embark: no Dwarf Fortress window on {args.display}",
              file=sys.stderr)
        if proc is not None:
            proc.kill()
        return 2
    print(f"embark: DF window {wid} on {args.display}", flush=True)

    try:
        with DFHackClient(args.host, args.port, timeout=30.0) as client:
            if args.full or args.to_screen:
                print("embark: navigating to the embark screen ...",
                      flush=True)
                res = embark.navigate_to_embark_screen(
                    client, wid, args.display)
                print(f"embark: {res}", flush=True)
                if args.to_screen and not args.full:
                    return 0
            if args.screen_only:
                embark.write_profile(df_dir, profile)
                count = embark.run_fileresult(client, df_dir, wid=wid,
                                              display=args.display)
                print(f"embark: fileresult matches = {count}", flush=True)
                return 0
            # Default / --full: end-to-end embark.
            print("embark: running embark_site ...", flush=True)
            fort = embark.embark_site(client, df_dir, wid, args.display,
                                      profile=profile)
            print(f"embark: FORT LOADED: {fort}", flush=True)
            # Quicksave the clean embark so it is the M2 base.
            try:
                client.run_command("quicksave", timeout=120.0)
                print("embark: quicksaved", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"embark: quicksave failed (non-fatal): {exc}",
                      flush=True)
    except embark.EmbarkError as exc:
        print(f"embark: FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
