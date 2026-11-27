#!/usr/bin/env python3
"""dfh — the DF Agent Harness daemon CLI (phase 4).

    dfh start [--port N] [--df-port N] [--no-auth] [--allow-raw]
    dfh stop
    dfh status
    dfh daemon [--port N] [--df-port N] [--no-auth] [--allow-raw]
        (foreground; for debugging, tmux, or systemd --user)

``dfh start`` launches the daemon in the background (logs to
``~/.config/df-agent-harness/daemon.log``), writes a PID file, and
waits for ``/v1/health`` to answer. ``dfh stop`` sends SIGTERM; the
daemon shuts down gracefully (drain + flush journal first). The
daemon binds 127.0.0.1 only and requires the bearer token from
``~/.config/df-agent-harness/token`` (or ``DFH_AGENT_TOKEN``) unless
``--no-auth`` was given at start.

Exit 0 on success, 1 on failure (daemon not running, port in use,
health check timeout), 2 for bad flags.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.daemon import (  # noqa: E402
    Daemon,
    DaemonConfig,
    default_state_dir,
    load_config,
    load_or_create_token,
    save_config,
)

DEFAULT_DF_DIR = Path(__file__).resolve().parent.parent / "third_party" / "df_47_05"


def _state_dir() -> Path:
    return default_state_dir()


def _pid_file(state_dir: Path) -> Path:
    return state_dir / "daemon.pid"


def _read_pid(state_dir: Path) -> int | None:
    try:
        pid = int(_pid_file(state_dir).read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return pid
    return pid


def _health_url(config: DaemonConfig) -> str:
    return f"http://{config.http_host}:{config.http_port}/v1/health"


def _http_get(url: str, token: str | None,
              timeout: float = 5.0) -> dict | None:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError):
        return None


def _wait_healthy(config: DaemonConfig, token: str | None,
                  timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _http_get(_health_url(config), token) is not None:
            return True
        time.sleep(2)
    return False


def _apply_persisted_flags(args: argparse.Namespace,
                           config: DaemonConfig) -> DaemonConfig:
    """Apply the CLI flags that ARE persisted to config.json:
    the ports. Called before save_config."""
    if args.port is not None:
        config.http_port = args.port
    if args.df_port is not None:
        config.df_port = args.df_port
    return config


def _apply_runtime_flags(args: argparse.Namespace,
                         config: DaemonConfig) -> DaemonConfig:
    """Apply the CLI flags that are runtime-only and must NEVER be
    persisted (H11): --no-auth and --allow-raw weaken the daemon's
    security, and saving them turned one debug start into a
    permanently unauthenticated daemon. Called AFTER save_config,
    so a debug flag can never leak into config.json. Prints a loud
    warning when either is used."""
    if args.no_auth:
        config.no_auth = True
        print("WARNING: dfh started with --no-auth: the HTTP API "
              "accepts unauthenticated requests for this run only "
              "(not saved to config.json)", file=sys.stderr)
    if args.allow_raw:
        config.allow_raw_actions = True
        print("WARNING: dfh started with --allow-raw: the raw "
              "Lua/DFHack command actions are enabled for this run "
              "only (not saved to config.json)", file=sys.stderr)
    return config


def _cmd_start(args: argparse.Namespace) -> int:
    state_dir = _state_dir()
    config = _apply_persisted_flags(args, load_config(state_dir))
    pid = _read_pid(state_dir)
    if pid is not None:
        print(f"dfh: daemon already running (pid {pid})")
        return 1
    save_config(state_dir, config)
    config = _apply_runtime_flags(args, config)
    token = load_or_create_token(state_dir, config.no_auth)
    log_path = state_dir / "daemon.log"
    log_fh = open(log_path, "ab")
    cmd = [sys.executable, str(Path(__file__).resolve()), "daemon",
           "--port", str(config.http_port),
           "--df-port", str(config.df_port)]
    if config.no_auth:
        cmd.append("--no-auth")
    if config.allow_raw_actions:
        cmd.append("--allow-raw")
    proc = subprocess.Popen(
        cmd, stdout=log_fh, stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True,
        cwd=str(Path(__file__).resolve().parent.parent))
    _pid_file(state_dir).write_text(str(proc.pid))
    print(f"dfh: daemon starting (pid {proc.pid}, "
          f"http://{config.http_host}:{config.http_port}, "
          f"auth={'off' if token is None else 'token'}, "
          f"log {log_path})")
    if _wait_healthy(config, token):
        print("dfh: healthy")
        return 0
    print("dfh: daemon did not become healthy in 60s — see "
          f"{log_path}", file=sys.stderr)
    return 1


def _cmd_stop(args: argparse.Namespace) -> int:
    state_dir = _state_dir()
    pid = _read_pid(state_dir)
    if pid is None:
        print("dfh: no daemon running")
        return 1
    os.kill(pid, signal.SIGTERM)
    # Graceful stop runs a forced quicksave first (up to ~45s for
    # the region1 mtime check), so 20s was too short to ever succeed.
    deadline = time.time() + 75
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            print(f"dfh: daemon (pid {pid}) stopped")
            _pid_file(state_dir).unlink(missing_ok=True)
            return 0
        time.sleep(1)
    print(f"dfh: daemon (pid {pid}) did not stop in 75s",
          file=sys.stderr)
    return 1


def _cmd_status(args: argparse.Namespace) -> int:
    state_dir = _state_dir()
    config = load_config(state_dir)
    pid = _read_pid(state_dir)
    token = None
    if not config.no_auth:
        token_path = state_dir / "token"
        try:
            token = token_path.read_text().strip() or None
        except OSError:
            token = os.environ.get("DFH_AGENT_TOKEN")
    health = _http_get(_health_url(config), token)
    control = _http_get(
        f"http://{config.http_host}:{config.http_port}/v1/control/daemon",
        token)
    print(json.dumps({
        "daemon_pid": pid,
        "running": pid is not None,
        "health": health,
        "control": control,
        "auth": "off" if config.no_auth else "token",
        "token_file": str(state_dir / "token"),
    }, indent=2))
    return 0 if pid is not None and health is not None else 1


class _TimestampedWriter:
    """Wrap a text stream so every line gets a UTC timestamp prefix.

    The daemon log had no timestamps (plain print), so a DF death
    could never be correlated with the daemon's last RPC call
    (run #12: the daemon log showed pause-guard failures with no
    time attached). Line-buffered: a partial line is held until
    its newline arrives. Installed at daemon startup, before any
    print below.
    """

    def __init__(self, wrapped):
        self._wrapped = wrapped
        self._buf = ""

    def write(self, s):
        if not isinstance(s, str):
            s = str(s)
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            ts = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S")
            self._wrapped.write(f"{ts} {line}\n")
        return len(s)

    def flush(self):
        if self._buf:
            ts = datetime.now(timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S")
            self._wrapped.write(f"{ts} {self._buf}")
            self._buf = ""
        self._wrapped.flush()

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


def _cmd_daemon(args: argparse.Namespace) -> int:
    state_dir = _state_dir()
    config = _apply_persisted_flags(args, load_config(state_dir))
    save_config(state_dir, config)
    config = _apply_runtime_flags(args, config)
    sys.stdout = _TimestampedWriter(sys.stdout)
    sys.stderr = _TimestampedWriter(sys.stderr)
    daemon = Daemon(config=config, state_dir=state_dir)

    def _handle(signum, frame):
        # Do NOT call daemon.stop() here: stop() calls
        # server.shutdown(), which blocks until serve_forever()
        # returns — but serve_forever() runs on this very thread
        # (suspended inside this handler), so that deadlocks and
        # the daemon never exits on SIGTERM. Instead just flag the
        # stop and kick serve_forever from a helper thread; the
        # graceful stop() runs after serve_forever() returns below.
        daemon._stop.set()
        if daemon.server is not None:
            threading.Thread(target=daemon.server.shutdown,
                             daemon=True).start()

    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    print(f"dfh daemon: starting on "
          f"http://{config.http_host}:{config.http_port} "
          f"(DFHack {config.df_host}:{config.df_port}, "
          f"auth={'off' if daemon.token is None else 'token'})",
          flush=True)
    try:
        daemon.start()
    except Exception as exc:  # noqa: BLE001 - startup failure
        print(f"dfh daemon: failed to start: {exc}", file=sys.stderr)
        return 1
    print("dfh daemon: running (Ctrl-C / SIGTERM to stop)", flush=True)
    daemon.serve_forever()
    daemon.stop()
    print("dfh daemon: stopped", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DF Agent Harness daemon (dfh).")
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--port", type=int, default=None,
                       help="agent HTTP port (default 8765)")
        p.add_argument("--df-port", type=int, default=None,
                       help="DFHack RPC port (default 5000)")
        p.add_argument("--no-auth", action="store_true",
                       help="disable the bearer token (localhost "
                            "only; this run only, never saved)")
        p.add_argument("--allow-raw", action="store_true",
                       help="enable the guarded /lua and /command "
                            "endpoints (this run only, never saved)")

    p_start = sub.add_parser("start", help="start the daemon")
    _add_common(p_start)
    p_start.set_defaults(fn=_cmd_start)

    p_stop = sub.add_parser("stop", help="stop the daemon")
    p_stop.set_defaults(fn=_cmd_stop)

    p_status = sub.add_parser("status", help="daemon status as JSON")
    p_status.set_defaults(fn=_cmd_status)

    p_daemon = sub.add_parser("daemon", help="run in the foreground")
    _add_common(p_daemon)
    p_daemon.set_defaults(fn=_cmd_daemon)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
