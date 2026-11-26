#!/usr/bin/env python3
"""Reload a fort save from disk.

Kills DF (SIGTERM is ignored, so pkill -9), relaunches ./dfhack,
skips the intro movie, runs DFHack `load-save <region>` via RPC, and
verifies the fort loaded (dwarfmode/Default, paused, citizens, drink).

Load method (reliable, per the coordinator log): DFHack `load-save`
via RPC dismisses the gui/load-screen wrapper and selects by folder
name. The manual 3-step UI load is flaky (the wrapper has its own
selection, so setting sel_idx on the native loadgamest does not take
effect — it loaded region1/Athelunol twice).

Save resolution (2026-11-26 fix): a bare region name (e.g. region2)
resolves to the NEWEST dated backup (region2-00125-07-01 beats
region2-00125-04-01) by the in-game date in the folder suffix, NOT
by filesystem mtime — mtime is unreliable after a copy (copying an
old backup into the base folder makes the base folder's world.sav
mtime newest while its content is the older state; that is how the
fort silently landed on 125-04-01 / 7 citizens instead of 125-07-01
/ 10 citizens on 2026-11-26). Use --exact to load the named folder
as-is (e.g. deliberately loading an older backup for drink headroom).
Use --list to see all candidates before choosing.

Usage:
    .venv/bin/python scripts/reload_fort.py [region] [--exact] [--list]
    .venv/bin/python scripts/reload_fort.py region2
    .venv/bin/python scripts/reload_fort.py region2-00125-04-01 --exact
"""
import argparse
import os
import re
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
SAVE_DIR = DF_DIR / "data" / "save"

# Dated AUTOBACKUP folders: <base>-YYYYY-MM-DD, e.g.
# region2-00125-07-01 (in-game year 125, month 07, day 01).
_DATE_RE = re.compile(r"^(.+)-(\d{5})-(\d{2})-(\d{2})$")


def list_saves() -> list[dict]:
    """All save folders with their in-game date (from the suffix, if
    any) and world.sav mtime/size. Sorted newest-first by in-game
    date, then mtime."""
    out = []
    if not SAVE_DIR.is_dir():
        return out
    for d in sorted(SAVE_DIR.iterdir()):
        if not d.is_dir():
            continue
        ws = d / "world.sav"
        if not ws.is_file():
            continue
        m = _DATE_RE.match(d.name)
        date = None
        base = d.name
        if m:
            base = m.group(1)
            date = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
        st = ws.stat()
        out.append({"folder": d.name, "base": base, "date": date,
                    "mtime": st.st_mtime, "size": st.st_size})
    # Dated backups sort by in-game date; the undated base folder
    # sorts by mtime only (its content date is unknown without
    # reading the save).
    out.sort(key=lambda r: (r["date"] or (0, 0, 0), r["mtime"]),
             reverse=True)
    return out


def resolve_save(region: str, exact: bool = False) -> str:
    """Resolve a region argument to the save folder to load.

    Exact mode (--exact) or an exact dated folder name: use it as-is.
    Otherwise, if dated backups exist for the base, return the newest
    by in-game date suffix. If none exist, return the base folder.
    Prints the resolution so the operator always sees what loaded.
    """
    saves = list_saves()
    if exact:
        print(f"reload: --exact, loading {region} as given", flush=True)
        return region
    m = _DATE_RE.match(region)
    if m:
        # An exact dated folder was named; use it as-is.
        print(f"reload: loading dated backup {region} as given",
              flush=True)
        return region
    dated = [s for s in saves if s["base"] == region and s["date"]]
    if dated:
        newest = dated[0]
        base_row = next((s for s in saves if s["folder"] == region),
                        None)
        print(f"reload: {region} resolves to newest backup "
              f"{newest['folder']} (in-game "
              f"{newest['date'][0]:05d}-{newest['date'][1]:02d}-"
              f"{newest['date'][2]:02d})", flush=True)
        if base_row is not None:
            print(f"reload: note: base folder {region}/world.sav "
                  f"mtime is {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(base_row['mtime']))} "
                  f"— mtime is NOT used (unreliable after a copy); "
                  f"the dated backup is the newest game state",
                  flush=True)
        return newest["folder"]
    print(f"reload: no dated backups for {region}; loading base folder",
          flush=True)
    return region


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
    ap.add_argument("--exact", action="store_true",
                    help="load the named folder as-is, no newest-"
                         "backup resolution")
    ap.add_argument("--list", action="store_true",
                    help="list save folders (in-game date, world.sav "
                         "mtime/size) and exit")
    ap.add_argument("--force", action="store_true",
                    help="load even if the save is below the drink "
                         "floor (drink < 10); otherwise a low-drink "
                         "save is refused")
    args = ap.parse_args()

    if args.list:
        for s in list_saves():
            date = (f"{s['date'][0]:05d}-{s['date'][1]:02d}-"
                    f"{s['date'][2]:02d}" if s["date"] else "  (base)")
            print(f"{s['folder']:28s} {date}  "
                  f"mtime {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s['mtime']))}  "
                  f"{s['size']:,} bytes")
        return 0

    region = resolve_save(args.region, exact=args.exact)

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
    print(f"loading save {region} ...", flush=True)
    client.run_command("load-save", region)
    state = wait_fort(client)
    st = state.get("status") or {}
    pop = st.get("population") or {}
    sk = state.get("stocks") or {}
    # GUARD 1 — pause verification after every load. A reload must
    # never leave the game running, even for a moment (2026-11-26:
    # a reload left the game unpaused and it ran free on drink 0).
    # set_paused verifies by re-reading and falls back to a Space
    # keypress if the flag does not stick; re-verify here and fail
    # loudly if it still does not stick.
    from dfagent_harness.actions import set_paused
    paused = st.get("paused")
    if not paused:
        print("reload: GUARD 1 — game came up UNPAUSED; pausing at "
              "once", flush=True)
        try:
            paused = set_paused(client, True)
        except Exception as exc:
            print(f"reload: GUARD 1 FAILED — could not pause: {exc}",
                  flush=True)
            return 4
    # Re-read the flag to verify the pause stuck (set_paused already
    # verifies, but the flag is re-checked here as the load's final
    # word, independent of the setter's return).
    from dfagent_harness.actions import get_paused
    try:
        paused_now = get_paused(client)
    except Exception as exc:
        print(f"reload: GUARD 1 FAILED — could not read pause flag: "
              f"{exc}", flush=True)
        return 4
    if not paused_now:
        print("reload: GUARD 1 FAILED — pause flag did not stick "
              "after load; leaving DF paused is not verified",
              flush=True)
        return 4
    print(f"loaded: focus={st.get('focus')} date={st.get('date')} "
          f"paused={paused_now} citizens={pop.get('citizens')} "
          f"drink={sk.get('drink_units')} food={sk.get('food_units')} "
          f"wood={sk.get('wood_units')}", flush=True)
    print(f"reload: GUARD 1 OK — post-load pause state verified: "
          f"paused={paused_now}", flush=True)
    # GUARD 2 — refuse bad saves. A save below the drink floor must
    # never be silently landed on (2026-11-26: the newest backup was
    # a drink-0 state and a bare-region reload landed the fort on it).
    # Floor is drink < 10 (~2 days at the measured M1 burn of
    # ~5/day). Refusal exits non-zero with the game left PAUSED
    # (safe); --force overrides for a deliberate low-drink load.
    drink = sk.get("drink_units")
    citizens = pop.get("citizens")
    if drink is not None and drink < 10 and not args.force:
        print(f"reload: GUARD 2 REFUSAL — {region} has drink "
              f"{drink} (< 10 floor), date {st.get('date')}, "
              f"{citizens} citizens. Refusing to hand this save to "
              f"a run; re-run with --force to override. Game left "
              f"PAUSED.", flush=True)
        return 3
    print(f"reload: GUARD 2 OK — drink {drink} >= 10 floor "
          f"(date {st.get('date')}, {citizens} citizens)",
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
