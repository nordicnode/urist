#!/usr/bin/env bash
# install-supervisor.sh — install the Urist systemd supervisor and
# hand the live stack over to it.
#
# The unit files live in the repo (systemd/) so they survive a VM
# replacement; this script copies them to /etc/systemd/system (which
# survives a reboot but NOT a replacement — re-run this script after
# recover.sh on a fresh VM), reloads systemd, and enables
# urist-stack.target so the stack comes up on boot.
#
# Default mode is a handover: it stops the manually started stack
# (daemon via dfh stop, DFs by PID+cwd, Xvfbs by display) and starts
# the target, so the stack ends up supervised with no duplicate
# processes. --install-only installs + enables without touching the
# running processes (used by recover.sh: the manual stack it just
# started keeps running until the next boot, when the units take
# over cleanly).
#
# Usage: bash scripts/install-supervisor.sh [--install-only]
# Must run as root (the runtime user; the whole manual stack runs
# as root too). Safe to re-run: install is idempotent, and if the
# units already own the processes the handover is a no-op.
set -euo pipefail

HARNESS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_ONLY=0
if [[ "${1:-}" == "--install-only" ]]; then
  INSTALL_ONLY=1
fi

if [[ "$(id -u)" != "0" ]]; then
  echo "install-supervisor: must run as root" >&2
  exit 2
fi
if [[ ! -d /run/systemd/system ]]; then
  echo "install-supervisor: systemd is not PID 1 here; cannot install" >&2
  exit 2
fi

# 1. Install the units.
for unit in urist-xvfb-main urist-xvfb-scratch urist-df-main \
            urist-df-scratch urist-daemon urist-stack; do
  cp "$HARNESS/systemd/$unit.service" /etc/systemd/system/ 2>/dev/null \
    || cp "$HARNESS/systemd/$unit.target" /etc/systemd/system/
done
systemctl daemon-reload
systemctl enable urist-stack.target >/dev/null
echo "install-supervisor: units installed, urist-stack.target enabled"

if [[ "$INSTALL_ONLY" == "1" ]]; then
  echo "install-supervisor: --install-only, leaving running processes alone"
  exit 0
fi

# 2. If the units already own the stack, there is nothing to hand over.
if systemctl is-active --quiet urist-stack.target; then
  echo "install-supervisor: stack already supervised; nothing to hand over"
  systemctl status urist-stack.target --no-pager | head -5
  exit 0
fi

# 3. Refuse the handover while a live run is in progress.
if pgrep -f "m1_driver.py" >/dev/null; then
  echo "install-supervisor: an M1 run is in progress; refusing handover" >&2
  exit 3
fi

# 4. Stop the manual stack: daemon first (clean stop quicksaves the
# main fort), then DFs by PID+cwd (never bare pkill), then Xvfbs.
echo "install-supervisor: stopping the manual stack ..."
"$HARNESS/.venv/bin/python" "$HARNESS/scripts/dfh.py" stop || true
"$HARNESS/.venv/bin/python" -c "
import sys
sys.path.insert(0, '$HARNESS/scripts')
import reload_fort as rf
from pathlib import Path
print('killed main DF:', rf.kill_df(Path('$HARNESS/third_party/df_47_05')))
print('killed scratch DF:', rf.kill_df(Path('$HARNESS/scratch/m2-embark/df')))
" || true
for disp in 99 98; do
  pkill -f "^Xvfb :$disp" 2>/dev/null || true
done
sleep 2
if pgrep -x Xvfb >/dev/null || pgrep -x Dwarf_Fortress >/dev/null; then
  echo "install-supervisor: WARNING — manual processes still alive:" >&2
  pgrep -a -x Xvfb >&2 || true
  pgrep -a -x Dwarf_Fortress >&2 || true
  echo "install-supervisor: not starting the target; clear them first" >&2
  exit 4
fi

# 5. Start the supervised stack and wait for the daemon to answer.
echo "install-supervisor: starting urist-stack.target ..."
systemctl start urist-stack.target
for i in $(seq 1 150); do
  if curl -sf --max-time 3 http://127.0.0.1:8765/v1/health >/dev/null 2>&1; then
    echo "install-supervisor: daemon healthy"
    break
  fi
  sleep 2
  if [[ "$i" == "150" ]]; then
    echo "install-supervisor: daemon did not become healthy in 5 min" >&2
    systemctl status urist-df-main.service urist-daemon.service \
      --no-pager >&2 | tail -30
    exit 5
  fi
done
systemctl is-active urist-xvfb-main.service urist-xvfb-scratch.service \
  urist-df-main.service urist-df-scratch.service urist-daemon.service
echo "install-supervisor: HANDOVER-OK — stack is supervised"
