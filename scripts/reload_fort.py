#!/usr/bin/env python3
"""Reload a fort save from disk (the drink-9 save is the clean state).

Kills DF (SIGTERM is ignored, so pkill -9), relaunches ./dfhack,
skips the intro movie, runs DFHack `load-save <region>` via RPC, and
verifies the fort loaded (dwarfmode/Default, paused, citizens, drink).

Load method (reliable, per the coordinator log): DFHack `load-save`
via RPC dismisses the gui/load-screen wrapper and selects by folder
name. The manual 3-step UI load is flaky (the wrapper has its own
selection, so setting sel_idx on the native loadgamest does not take
effect — it loaded region1/Athelunol twice).

Usage:
    .venv/bin/python scripts/reload_fort.py [region]
    .venv/bin/python scripts/reload_fort.py region2
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS / "src"))

from dfagent_harness.observe import collect  # noqa: E402
from dfagent_harness.read_safety import paused_read  # noqa: E402
from dfhack_rpc import DFHackClient  # noqa: E402
from dfhack_rpc.proto import RemoteFortressReader_pb2 as rfr  # noqa: E402
from dfhack_rpc.proto import CoreProtocol_pb2 as core  # noqa: E402

DF_DIR = HARNESS / "third_party" / "df_47_05"


def send_space(client: DFHackClient) -> None:
    for ev_type, state in ((2, 1), (3, 0)):
        client.call("PassKeyboardEvent",
                    rfr.KeyboardEvent(type=ev_type, sym=32, state=state,
                                      unicode=32, scancode=0, mod=0),
                    core.EmptyMessage)
        time.sleep(0.05)


def wait_rpc(timeout: int = 120) -> DFHackClient:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            c = DFHackClient("127.0.0.1", 5000, timeout=10.0)
            c.connect()
            return c
        except Exception:
            time.sleep(2)
    raise RuntimeError("RPC 5000 did not come up")


def wait_fort(client: DFHackClient, timeout: int = 300) -> dict:
    """Poll until the focus is dwarfmode/Default and a full collect
    works; returns the collected state."""
    from dfagent_harness.ui import get_focus
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            probe = get_focus(client, timeout=10.0)
            focus = probe.get("focus") if probe.get("ok") else None
            if focus == "dwarfmode/Default":
                return paused_read(client, lambda: collect(client))
        except Exception as exc:  # still loading
            last_err = exc
        time.sleep(10)
    raise RuntimeError(f"fort did not load in {timeout}s: {last_err}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("region", nargs="?", default="region2")
    args = ap.parse_args()

    print("killing DF ...", flush=True)
    # -x matches the exact process name; pkill's own name is "pkill",
    # so there is no self-match (the hazard from the log).
    subprocess.run(["pkill", "-9", "-x", "Dwarf_Fortress"],
                   capture_output=True)
    time.sleep(2)

    print("launching ./dfhack ...", flush=True)
    env = dict(os.environ)
    env["DISPLAY"] = ":99"
    env["TERM"] = "xterm"
    log = open(HARNESS / "logs" / "dfhack.log", "ab")
    # Detach fully: new session (setsid) + stdin from /dev/null +
    # SIGHUP ignored. Without this DF dies ~20 s after this script
    # exits (observed 2026-11-26 x3); a manual `setsid nohup`
    # launch survives. The Popen object is intentionally not kept.
    def _detach() -> None:
        import signal
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    subprocess.Popen(["./dfhack"], cwd=DF_DIR, env=env,
                     stdin=subprocess.DEVNULL,
                     stdout=log, stderr=subprocess.STDOUT,
                     start_new_session=True, preexec_fn=_detach)
    client = wait_rpc()
    print("RPC up; skipping intro ...", flush=True)
    time.sleep(5)
    send_space(client)
    time.sleep(2)
    print(f"loading save {args.region} ...", flush=True)
    client.run_command("load-save", args.region)
    state = wait_fort(client)
    st = state.get("status") or {}
    pop = st.get("population") or {}
    sk = state.get("stocks") or {}
    print(f"loaded: focus={st.get('focus')} date={st.get('date')} "
          f"paused={st.get('paused')} citizens={pop.get('citizens')} "
          f"drink={sk.get('drink_units')} food={sk.get('food_units')} "
          f"wood={sk.get('wood_units')}", flush=True)
    # The fort sometimes comes up UNPAUSED — re-pause by hand.
    if not st.get("paused"):
        from dfagent_harness.actions import set_paused
        set_paused(client, True)
        print("re-paused (came up unpaused)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
