#!/usr/bin/env python3
"""Stream DF Agent Harness events to stdout (phase 3).

    python scripts/dfh-events.py [--follow] [--once]
    python scripts/dfh-events.py --serve [--http-port 8765]
    python scripts/dfh-events.py --url http://127.0.0.1:8765/v1/events [--since N]
    python scripts/dfh-events.py --install-watcher | --watcher-status | --uninstall-watcher

Default mode attaches directly to the game over DFHack RPC: it drains
the eventful watcher log (``dfh-events.jsonl`` in the DF directory)
and runs the poll-diff detector, printing one JSON event per line.
``--once`` runs a single poll cycle and exits; ``--follow`` keeps
polling until Ctrl-C (the game is never unpaused by this tool).

``--serve`` runs the minimal HTTP server instead (``GET /v1/events``
SSE, ``GET /v1/state``, ``GET /v1/health``) with the poller feeding
it; see docs/EVENTS.md. ``--url`` streams SSE from such a server.

Exit 0 on a clean run, 1 when the game is not reachable (or the
server URL fails), 2 for bad flags.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

# Allow running from the repo root without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.events import (  # noqa: E402
    DEFAULT_WATCH_LOG,
    EventBus,
    EventPoller,
    WatcherDrainer,
    install_watcher,
    make_event,
    uninstall_watcher,
    watcher_status,
)
from dfagent_harness.server import run_server  # noqa: E402
from dfhack_rpc import DFHackClient, DFHackError  # noqa: E402

DEFAULT_DF_DIR = Path(__file__).resolve().parent.parent / "third_party" / "df_47_05"


def _watch_log(df_dir: Path) -> Path:
    return df_dir / "dfh-events.jsonl"


def _stream_sse(url: str, since: int | None) -> int:
    """Stream SSE from a server URL, printing each event's data line."""
    if since is not None:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}since={since}"
    req = urllib.request.Request(
        url, headers={"Accept": "text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("data:"):
                    print(line[5:].strip(), flush=True)
    except Exception as exc:  # noqa: BLE001 - report and exit 1
        print(f"dfh-events: SSE stream failed: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Stream DF Agent Harness events (JSON lines).")
    parser.add_argument("--host", default="127.0.0.1",
                        help="DFHack RPC host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000,
                        help="DFHack RPC port (default 5000)")
    parser.add_argument("--df-dir", type=Path, default=DEFAULT_DF_DIR,
                        help="DF install dir holding dfh-events.jsonl")
    parser.add_argument("--journal", type=Path, default=None,
                        help="event journal JSONL (bus replay survives "
                             "restarts when set)")
    parser.add_argument("--once", action="store_true",
                        help="one poll cycle, print its events, exit")
    parser.add_argument("--follow", action="store_true",
                        help="keep polling until Ctrl-C (default when "
                             "neither --once nor --serve is given)")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="fast poll interval in seconds (default 2)")
    parser.add_argument("--paused-interval", type=float, default=10.0,
                        help="poll interval while paused (default 10)")
    parser.add_argument("--slow-interval", type=float, default=30.0,
                        help="stocks/mandates poll interval (default 30)")
    parser.add_argument("--serve", action="store_true",
                        help="run the minimal HTTP/SSE server instead")
    parser.add_argument("--http-host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8765)
    parser.add_argument("--url", default=None,
                        help="stream SSE from a running server instead "
                             "of attaching to the game directly")
    parser.add_argument("--since", type=int, default=None,
                        help="with --url: replay events after this seq")
    parser.add_argument("--install-watcher", action="store_true",
                        help="install the eventful watcher and exit")
    parser.add_argument("--uninstall-watcher", action="store_true",
                        help="remove the eventful watcher and exit")
    parser.add_argument("--watcher-status", action="store_true",
                        help="report watcher install state and exit")
    args = parser.parse_args(argv)

    if args.url is not None:
        return _stream_sse(args.url, args.since)

    log_path = _watch_log(args.df_dir)
    try:
        client = DFHackClient(args.host, args.port, timeout=30.0)
        client.connect()
    except DFHackError as exc:
        print(f"dfh-events: game not reachable: {exc}", file=sys.stderr)
        return 1

    try:
        if args.install_watcher:
            print(install_watcher(client, log_path))
            return 0
        if args.uninstall_watcher:
            print(uninstall_watcher(client))
            return 0
        if args.watcher_status:
            print(json.dumps(watcher_status(client)))
            return 0

        bus = EventBus(journal_path=args.journal)
        drainer = WatcherDrainer(log_path)
        poller = EventPoller(
            client, bus, drainer=drainer,
            fast_interval=args.interval,
            paused_interval=args.paused_interval,
            slow_interval=args.slow_interval)
        if args.serve:
            bus.publish(make_event(
                "daemon_started", "info", {"version": "phase3"},
                source="daemon"))
            run_server(bus, client=client, host=args.http_host,
                       port=args.http_port, poller=poller)
            return 0

        def _emit(event: dict[str, Any]) -> None:
            print(json.dumps(event), flush=True)

        bus.subscribe(_emit)
        if args.once:
            poller.poll_once()
            return 0
        # Default: follow.
        poller.start()
        print("dfh-events: streaming (Ctrl-C to stop)",
              file=sys.stderr, flush=True)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
        finally:
            poller.stop()
        return 0
    finally:
        client.quit()


if __name__ == "__main__":
    raise SystemExit(main())
