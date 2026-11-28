#!/usr/bin/env python3
"""run_df.py — systemd wrapper that keeps one DF instance in its fort.

systemd cannot supervise DF directly: DF must be (re)launched, then a
save loaded through DFHack RPC, then the pause verified (GUARD 1) —
and a bare DF process at the title screen is not a recovered fort.
This wrapper owns the whole sequence:

  1. Kill any stale DF in the target dir (PID + cwd, never bare pkill).
  2. Run the reload command (reload_fort.py --exact for main,
     reload_scratch.py for scratch), which launches ./dfhack, loads
     the save, and verifies the pause. A nonzero reload exits this
     wrapper nonzero, so systemd restarts it (Restart=on-failure).
  3. Find the DF pid by scanning /proc for a Dwarf_Fortress process
     whose cwd is the target dir, then notify systemd ready
     (Type=notify: units ordered After= this one only start once the
     fort is loaded and paused).
  4. Watch the pid. If DF dies, exit nonzero -> systemd relaunches
     and reloads the fort from the last save. On SIGTERM/SIGINT
     (systemctl stop), SIGKILL the DF pid (DF ignores SIGTERM) and
     exit 0 — a clean stop, not a crash.

Requested reloads (eval suite): the suite runner may ask this
wrapper to load a different save for ONE restart (e.g. the S0
anchor for a benchmark tier) instead of the pinned save. The
request is one line in ~/.config/df-agent-harness/reload-request
holding the full reload command (argv, no shell). It is consumed
once (deleted on read) and ignored when stale (>30 min), so a
later crash recovery always falls back to the pinned save. The
requester writes it atomically (temp file + rename). Never kill
DF behind this wrapper to load another save: the wrapper
relaunches the pinned save and the daemon stops while it does
(observed 2026-11-28: both eval baselines failed that way).

The wrapper never guesses a pid: the DF it watches is identified by
(process name, cwd), the same identification kill_df uses.
"""

import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path


# Requested reloads (see the module docstring). One line holding
# the full reload command (argv, no shell). Consumed once, ignored
# when stale, so crash recovery always falls back to the pinned save.
DEFAULT_REQUEST_FILE = (
    Path.home() / ".config" / "df-agent-harness" / "reload-request")
REQUEST_MAX_AGE_SECONDS = 1800
_REQUEST_FORBIDDEN = set(";&|$`><\n\r")


def read_reload_request(path: Path | str,
                        max_age_seconds: int = REQUEST_MAX_AGE_SECONDS
                        ) -> str | None:
    """Consume a pending requested-reload command, or None.

    One-shot: the file is deleted on read (valid or not), so a
    request can only ever fire once. Stale (> max_age) and
    malformed requests are dropped with a warning, never executed.
    A request is well-formed when it is one line, splits into at
    least two argv tokens starting with a python binary, and
    contains no shell metacharacters (it is run as an argv list,
    never through a shell).
    """
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except FileNotFoundError:
        return None
    except OSError as exc:
        print(f"run_df: cannot stat request file {p}: {exc}",
              flush=True)
        return None
    if time.time() - mtime > max_age_seconds:
        print(f"run_df: ignoring stale reload request {p} "
              f"(older than {max_age_seconds}s)", flush=True)
        try:
            p.unlink()
        except OSError:
            pass
        return None
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"run_df: cannot read request file {p}: {exc}",
              flush=True)
        return None
    cmd = raw.strip()
    ok = bool(cmd) and "\n" not in cmd
    argv: list[str] = []
    if ok:
        try:
            argv = shlex.split(cmd)
        except ValueError:
            argv = []
        ok = (len(argv) >= 2
              and Path(argv[0]).name in ("python", "python3")
              and not any(c in cmd for c in _REQUEST_FORBIDDEN))
    try:
        p.unlink()
    except OSError as exc:
        print(f"run_df: cannot consume request file {p}: {exc}; "
              "ignoring the request", flush=True)
        return None
    if not ok:
        print(f"run_df: ignoring malformed reload request: {cmd!r}",
              flush=True)
        return None
    return cmd


def find_df_pid(df_dir: Path, proc_root: str = "/proc") -> int | None:
    """PID of the Dwarf_Fortress process whose cwd is df_dir.

    Scans proc_root for numeric dirs, matching /proc/<pid>/comm ==
    "Dwarf_Fortress" and readlink(/proc/<pid>/cwd) == df_dir. A pid
    whose cwd cannot be read is skipped, never assumed. Returns None
    when no such process exists.
    """
    target = df_dir.resolve()
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return None
    for name in entries:
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            comm = Path(proc_root, name, "comm").read_text(
                encoding="utf-8").strip()
            if comm != "Dwarf_Fortress":
                continue
            cwd = Path(os.readlink(Path(proc_root, name, "cwd"))).resolve()
        except (OSError, ValueError):
            continue
        if cwd == target:
            return pid
    return None


def _pid_dead(pid: int) -> bool:
    """True when the pid is gone, or a zombie (dead, awaiting reap)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            if fh.read().rsplit(b")", 1)[-1].split()[0] == b"Z":
                return True
    except OSError:
        return True
    return False


def _notify_ready() -> None:
    if "NOTIFY_SOCKET" not in os.environ:
        return
    try:
        subprocess.run(["systemd-notify", "--ready"], check=False,
                       timeout=10)
    except OSError as exc:
        print(f"run_df: systemd-notify failed: {exc}", flush=True)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--df-dir", required=True,
                    help="DF install dir (DF cwd), absolute")
    ap.add_argument("--display", required=True,
                    help="X display, e.g. :99")
    ap.add_argument("--reload-cmd", required=True,
                    help="reload command, e.g. '.venv/bin/python "
                         "scripts/reload_fort.py region2-00125-04-12 "
                         "--exact'")
    ap.add_argument("--name", required=True,
                    help="instance name for logs, e.g. main")
    ap.add_argument("--request-file", default=None,
                    help="requested-reload file (default: "
                         "~/.config/df-agent-harness/reload-request)")
    args = ap.parse_args(argv)
    df_dir = Path(args.df_dir)
    os.environ["DISPLAY"] = args.display
    print(f"run_df[{args.name}]: df_dir={df_dir} display={args.display}",
          flush=True)

    # Import here: reload_fort pulls in the harness package, which the
    # offline pid-discovery test must not need.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import reload_fort as rf

    # 1. Stale DF in this dir only (PID + cwd; other instances left
    # alone). reload_fort does this too, but the scratch reload does
    # not — do it here so both paths are safe.
    killed = rf.kill_df(df_dir)
    if killed:
        print(f"run_df[{args.name}]: killed stale DF pids {killed}",
              flush=True)

    # 2. Reload: launch ./dfhack, load the save, verify the pause.
    # A requested reload (eval suite) overrides the pinned command
    # for this restart only; anything else uses --reload-cmd.
    request_file = (Path(args.request_file) if args.request_file
                    else DEFAULT_REQUEST_FILE)
    requested = read_reload_request(request_file)
    if requested is not None:
        print(f"run_df[{args.name}]: using requested reload: "
              f"{requested}", flush=True)
        reload_cmd = requested
    else:
        reload_cmd = args.reload_cmd
    cmd = shlex.split(reload_cmd)
    print(f"run_df[{args.name}]: running: {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd)
    if proc.returncode != 0:
        print(f"run_df[{args.name}]: reload failed "
              f"(exit {proc.returncode}); exiting for restart",
              flush=True)
        return 1

    # 3. Find the DF this reload launched, then report ready.
    pid = None
    deadline = time.time() + 30
    while time.time() < deadline:
        pid = find_df_pid(df_dir)
        if pid is not None:
            break
        time.sleep(1)
    if pid is None:
        print(f"run_df[{args.name}]: reload ok but no DF found in "
              f"{df_dir}; exiting for restart", flush=True)
        return 1
    print(f"run_df[{args.name}]: DF pid {pid} up; fort loaded",
          flush=True)
    _notify_ready()

    # 4. Watch the pid. SIGTERM/SIGINT means stop: kill DF (it
    # ignores SIGTERM) and exit 0. DF dying on its own means crash:
    # exit 1 so systemd restarts the whole reload sequence.
    stop = {"flag": False}

    def _handle(signum, frame):
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    while True:
        if stop["flag"]:
            # Re-verify the pid is still the DF in this dir before
            # killing: between polls the pid could have been
            # recycled after a DF death.
            if find_df_pid(df_dir) == pid:
                print(f"run_df[{args.name}]: stopping; killing DF "
                      f"{pid}", flush=True)
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                print(f"run_df[{args.name}]: stopping; DF {pid} "
                      f"already gone", flush=True)
            return 0
        if _pid_dead(pid):
            print(f"run_df[{args.name}]: DF pid {pid} died; exiting "
                  f"for restart", flush=True)
            return 1
        if find_df_pid(df_dir) != pid:
            # The pid was recycled, or another DF took over the dir.
            print(f"run_df[{args.name}]: DF pid {pid} no longer the "
                  f"DF in {df_dir}; exiting for restart", flush=True)
            return 1
        time.sleep(2)


if __name__ == "__main__":
    raise SystemExit(main())
