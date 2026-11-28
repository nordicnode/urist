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

# Path-relative (2026-11-27, review step 10): the harness dir is
# derived from this script's own location, not hardcoded to
# ~/workspace/df-agent-harness — a fresh clone anywhere else must
# work, run from any cwd.
HARNESS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DF="$HARNESS/third_party/df_47_05"
mkdir -p "$HARNESS/logs"

# 1. System packages. Every one of these vanishes on VM replacement.
#    (xvfb is listed explicitly: SETUP.md's apt lines omitted it and it
#    only survived the last replacement because the base image had it.)
#    Non-fatal (2026-11-26): after a cell reboot apt is locked by the
#    system package replay for ~20 min; a locked apt must not abort
#    the recovery — the deblibs/tools fallbacks below cover the wait.
if ! sudo apt-get update -qq 2>/dev/null; then
  echo "apt update failed (locked by the system replay?) — continuing with cached libs"
fi
if ! sudo apt-get install -y xvfb x11-apps imagemagick xdotool \
  libsdl1.2debian libsdl-image1.2 libsdl-ttf2.0-0 libgtk2.0-0t64 \
  libglu1-mesa libgl1 2>/dev/null; then
  echo "apt install failed (locked?) — continuing with cached libs"
fi

# 1a. xdotool/scrot fallback (2026-11-26): if apt could not install
#     them, extract the already-cached .debs into scratch/tools.
#     Idempotent. Consumers (ui.py, shot.sh, dfh.py) resolve bare
#     `xdotool`/`scrot` via PATH, so source scratch/tools-env.sh (or
#     export its PATH/LD_LIBRARY_PATH) before driving the game.
if ! command -v xdotool >/dev/null 2>&1 \
    || ! command -v scrot >/dev/null 2>&1; then
  TOOLS="$HARNESS/scratch/tools"
  mkdir -p "$TOOLS"
  for spec in "xdotool_:xdotool" "scrot_:scrot" "libxdo3_:libxdo3" \
              "libxtst6_:libxtst6" "libimlib2t64_:libimlib2"; do
    deb="${spec%%:*}"; dir="${spec##*:}"
    f=$(ls /var/cache/apt/archives/${deb}*.deb 2>/dev/null | head -1 || true)
    # A missing cached deb must not abort the recovery (set -e
    # turns the failed ls into an exit 2): the extracted libs may
    # already exist from a previous run, and apt installs the
    # package system-wide later anyway. Observed 2026-11-27: the
    # libgl1 deb was absent from the cache and killed recover.sh
    # twice at the deblibs step, before DF ever launched.
    if [ -n "$f" ]; then
      dpkg-deb -x "$f" "$TOOLS/$dir" 2>/dev/null || true
    fi
  done
  cat > "$TOOLS-env.sh" <<EOF
# Sourced by callers that drive DF while apt packages are missing
# (post-reboot, before the system replay restores them).
export PATH="$TOOLS/xdotool/usr/bin:$TOOLS/scrot/usr/bin:\$PATH"
export LD_LIBRARY_PATH="$TOOLS/libxdo3/usr/lib/x86_64-linux-gnu:$TOOLS/libxtst6/usr/lib/x86_64-linux-gnu:$TOOLS/libimlib2/usr/lib/x86_64-linux-gnu\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}"
EOF
  echo "xdotool/scrot missing system-wide; extracted to $TOOLS (source $TOOLS-env.sh)"
fi

# 1b. Autosave (2026-11-26): a VM replacement wiped ~2 months of play
#     because the fort had never saved. The setting lives in d_init.txt
#     (NOT init.txt). Idempotent: only rewrites the two tokens.
DINIT="$DF/data/init/d_init.txt"
if [ -f "$DINIT" ]; then
  sed -i 's/\[AUTOSAVE:NONE\]/[AUTOSAVE:SEASONAL]/' "$DINIT"
  sed -i 's/\[AUTOBACKUP:NO\]/[AUTOBACKUP:YES]/' "$DINIT"
fi

# 2. Virtual display :99. Log goes to the workspace, not /tmp, so it
#    survives the next replacement.
if ! pgrep -x Xvfb >/dev/null; then
  Xvfb :99 -screen 0 1024x768x24 >"$HARNESS/logs/xvfb99.log" 2>&1 &
else
  echo "Xvfb already running, leaving it alone"
fi

# 3. DF + DFHack. Always launch with ./dfhack (loads DFHack), never ./df.
#    The world save (data/save/region1) lives in the workspace and survives.
#    Fallback (2026-11-26): after a VM replacement the apt step above can
#    sit queued behind the system package replay for ~20 min while the
#    SDL/GTK libs are still missing. If libSDL is not installed by then,
#    extract the already-cached .debs into scratch/deblibs and launch DF
#    with that LD_LIBRARY_PATH instead of waiting — DF only needs the
#    six libs, and the replay installs them system-wide later anyway.
#    The list MUST match _DEBLIB_PKGS in scripts/reload_fort.py (the
#    LD_LIBRARY_PATH below names all six dirs); keep them in sync.
if ! ldconfig -p 2>/dev/null | grep -q libSDL-1.2.so.0; then
  DEBLIBS="$HARNESS/scratch/deblibs"
  mkdir -p "$DEBLIBS"
  for deb in libsdl1.2debian libsdl-image1.2 libsdl-ttf2.0-0 \
             libgtk2.0-0t64 libglu1-mesa libgl1; do
    f=$(ls /var/cache/apt/archives/${deb}_*.deb 2>/dev/null | head -1 || true)
    # Same as step 1a above: a missing cached deb (libgl1,
    # 2026-11-27) must not abort the recovery under set -e.
    if [ -n "$f" ]; then
      dpkg-deb -x "$f" "$DEBLIBS/$deb" 2>/dev/null || true
    fi
  done
  export LD_LIBRARY_PATH="$DEBLIBS/libsdl1.2debian/usr/lib/x86_64-linux-gnu:$DEBLIBS/libsdl-image1.2/usr/lib/x86_64-linux-gnu:$DEBLIBS/libsdl-ttf2.0-0/usr/lib/x86_64-linux-gnu:$DEBLIBS/libgtk2.0-0t64/usr/lib/x86_64-linux-gnu:$DEBLIBS/libglu1-mesa/usr/lib/x86_64-linux-gnu:$DEBLIBS/libgl1/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
  echo "libsdl missing system-wide; using extracted libs from $DEBLIBS"
fi
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
"$HARNESS/.venv/bin/python" "$HARNESS/scripts/rpc_smoke.py" --port 5000
echo "RECOVER-OK: DF 0.47.05 + DFHack up, RPC on port 5000"

# 5. Boot supervisor (2026-11-27): install the systemd units so the
#    stack comes back on the next reboot without a human. Best effort
#    only — never fails the recovery. --install-only: the manual stack
#    above keeps running until the next boot, when the units take over
#    cleanly. After a VM replacement, re-run install-supervisor.sh
#    (without --install-only) to hand the stack to systemd.
if [[ -f "$HARNESS/scripts/install-supervisor.sh" ]]; then
  bash "$HARNESS/scripts/install-supervisor.sh" --install-only || true
fi
