#!/usr/bin/env bash
# recover.sh — rebuild the DF harness environment after a VM replacement.
#
# What survives a VM replacement: the home dir (~), so all code, docs,
# world saves and fixtures in ~/workspace/df-agent-harness survive.
# What does NOT survive: apt-installed packages, /tmp, and running
# processes (Xvfb, DF). This script restores all three and verifies the
# result. Safe to re-run: installs are idempotent and Xvfb/DF are only
# started when not already running.
#
# Usage: bash scripts/recover.sh   (run from anywhere; it cds as needed)
# Do NOT run while a live DF session holds unsaved progress you care
# about — this script never kills DF, but if DF is already running it
# leaves it alone entirely.
set -euo pipefail

HARNESS=~/workspace/df-agent-harness
DF="$HARNESS/third_party/df_47_05"
mkdir -p "$HARNESS/logs"

# 1. System packages. Every one of these vanishes on VM replacement.
#    (xvfb is listed explicitly: SETUP.md's apt lines omitted it and it
#    only survived the last replacement because the base image had it.)
sudo apt-get update -qq
sudo apt-get install -y xvfb x11-apps imagemagick xdotool \
  libsdl1.2debian libsdl-image1.2 libsdl-ttf2.0-0 libgtk2.0-0t64 \
  libglu1-mesa libgl1

# 2. Virtual display :99. Log goes to the workspace, not /tmp, so it
#    survives the next replacement.
if ! pgrep -x Xvfb >/dev/null; then
  Xvfb :99 -screen 0 1024x768x24 >"$HARNESS/logs/xvfb99.log" 2>&1 &
else
  echo "Xvfb already running, leaving it alone"
fi

# 3. DF + DFHack. Always launch with ./dfhack (loads DFHack), never ./df.
#    The world save (data/save/region1) lives in the workspace and survives.
if ! pgrep -x Dwarf_Fortress >/dev/null; then
  cd "$DF"
  export TERM=xterm
  DISPLAY=:99 ./dfhack >"$HARNESS/logs/dfhack.log" 2>&1 &
  cd "$HARNESS"
else
  echo "Dwarf_Fortress already running, leaving it alone"
fi

# 4. Verify: wait for the DFHack remote server (TCP 5000), then run the
#    RPC smoke test against the live game.
for i in $(seq 1 30); do
  if (exec 3<>/dev/tcp/127.0.0.1/5000) 2>/dev/null; then
    break
  fi
  sleep 2
done
.venv/bin/python scripts/rpc_smoke.py --port 5000
echo "RECOVER-OK: DF 0.47.05 + DFHack up, RPC on port 5000"
