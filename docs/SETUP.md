# DF Agent Harness — Environment Setup (DF 0.47.05 + DFHack)

Verified end-to-end on this VM 2026-11-25. DF 0.47.05 is pinned — never
upgrade to 50.x for this project.

## Versions

| Component | Version | Notes |
|---|---|---|
| Dwarf Fortress | **0.47.05** (Linux, 64-bit) | Bay 12 download below |
| DFHack | **0.47.05-r8** (release, 2022-12-02) | Newest stable built for 0.47.05; r9 does not exist. r5/r6/r7 also exist but are older. |
| Xvfb display | `:99`, 1024x768x24 | `/usr/bin/Xvfb` |

## Downloads (exact URLs + checksums)

| File | URL | Size | SHA-256 |
|---|---|---|---|
| `df_47_05_linux.tar.bz2` | https://www.bay12games.com/dwarves/df_47_05_linux.tar.bz2 | 12,725,420 | `ac74a6dbb7d7d9621f430405080322ab50c35f6632352ff2ea923f6dc5affca3` |
| `dfhack-0.47.05-r8-Linux-64bit-gcc-7.tar.bz2` | GitHub release `DFHack/dfhack`, tag `0.47.05-r8` (asset `...-Linux-64bit-gcc-7.tar.bz2`) | 18,139,358 | `2eab7ca38a25eb15e6b2f1005a44968d58fae53f618ea9e4a31e1cd74d31926f` |

Downloaded copies are kept in `third_party/downloads/` (not gitignored —
keep them so a rebuild never re-downloads).

Why the gcc-7 64-bit build: the DF Linux binary (`libs/Dwarf_Fortress`) is a
64-bit ELF, so the 64-bit DFHack build is the match; gcc-7 is the build for
modern distros (gcc-4.8 is the legacy alternative in the same release).

## System packages (apt)

```sh
sudo apt-get install -y libsdl1.2debian libsdl-image1.2 libsdl-ttf2.0-0 libgtk2.0-0t64
# plus two more that DF actually needs at launch:
sudo apt-get install -y libglu1-mesa libgl1          # libGLU.so.1 missing without this
# screenshot / input tools used for verification (optional for later phases):
sudo apt-get install -y x11-apps imagemagick xdotool
```

Installed versions observed: libsdl1.2debian 1.2.68-2, libsdl-image1.2
1.2.12-13build4, libsdl-ttf2.0-0 2.0.11-6, libgtk2.0-0t64 2.24.33-4ubuntu1.1,
libglu1-mesa 9.0.2-1.1build1.

## Install from scratch

```sh
DF=~/workspace/df-agent-harness/third_party/df_47_05
DL=~/workspace/df-agent-harness/third_party/downloads
mkdir -p "$DL"
cd "$DL"
curl -fL -o df_47_05_linux.tar.bz2 https://www.bay12games.com/dwarves/df_47_05_linux.tar.bz2
gh release download 0.47.05-r8 --repo DFHack/dfhack \
  --pattern 'dfhack-0.47.05-r8-Linux-64bit-gcc-7.tar.bz2'

cd ~/workspace/df-agent-harness/third_party
# NOTE: use --no-same-owner — the tarball stores uid/gid 1000 and plain tar
# fails with "Cannot change ownership" errors otherwise (files still extract).
tar --no-same-owner -xjf "$DL/df_47_05_linux.tar.bz2"
mv df_linux df_47_05
tar --no-same-owner -xjf "$DL/dfhack-0.47.05-r8-Linux-64bit-gcc-7.tar.bz2" -C df_47_05

# Known fix (also done automatically by the ./dfhack launcher, which renames
# the file to libstdc++.so.6.backup — deleting outright is equivalent here):
rm df_47_05/libs/libstdc++.so.6 df_47_05/libs/libgcc_s.so.1

# Silence sound for headless runs (avoids audio-device errors):
sed -i 's/^\[SOUND:YES\]/[SOUND:NO]/' df_47_05/data/init/init.txt
```

`third_party/df_47_05/` is gitignored (see `.gitignore`).

## Launching headless (Xvfb)

```sh
# Start the virtual display once (left running on :99 after setup):
Xvfb :99 -screen 0 1024x768x24 >/tmp/xvfb99.log 2>&1 &

# IMPORTANT: launch with ./dfhack, NOT ./df.
# ./df runs vanilla DF; ./dfhack sets LD_PRELOAD=./hack/libdfhack.so,
# which is what loads DFHack. (First attempt with ./df ran fine but
# dfhack-run could not connect — no DFHack loaded.)
cd ~/workspace/df-agent-harness/third_party/df_47_05
DISPLAY=:99 ./dfhack
```

DF plays an intro movie (~30 s) before the main menu. `stderr.log` in the
DF dir shows `DFHack is ready. Have a nice day!` and
`DFHack version 0.47.05-r8 (release) on x86_64`.

Stopping: DF ignores SIGTERM — `pkill -x Dwarf_Fortress` does not kill it.
Use `pkill -9 -x Dwarf_Fortress` (safe at the main menu; nothing unsaved).
`export TERM=xterm` before launching avoids a harmless `tput: No value for
$TERM` warning from the launcher script.

## DFHack remote access

No config change is needed. The remote server is built into DFHack core and
auto-starts on **TCP 5000** (localhost only by default; see
`dfhack-config/remote-server.json` — `allow_remote` defaults to `false`,
`port` to `5000`, overridable with the `DFHACK_PORT` env var).
Docs: `hack/docs/docs/dev/Remote.txt`.

Verify while the game is running (at the main menu is fine):

```sh
cd ~/workspace/df-agent-harness/third_party/df_47_05
./dfhack-run ls                       # lists all DFHack commands
./dfhack-run lua 'print("PROBE-OK df="..dfhack.getDFVersion().." dfhack="..dfhack.getDFHackVersion())'
# => PROBE-OK df=v0.47.05 linux64 dfhack=0.47.05-r8
```

Quoting gotcha: `dfhack-run` takes the command as argv[1] and the rest as
separate args, and DFHack's `lua` command treats its argument as raw Lua
code. So pass the Lua snippet as a **separate quoted argument**
(`dfhack-run lua 'print(...)')`. Passing one combined string
(`dfhack-run 'lua print(...)'`) fails with "not a recognized command", and
`lua -e '...'` / `lua /path/script.lua` fail with Lua syntax errors
(`-e` and `/` are not valid Lua).

Port check observed: TCP port 5000 in state `0A` (LISTEN) while DF runs.

## World generation (small world)

The stock `SMALL REGION` preset (`data/init/world_gen.txt`, 65x65) has
`END_YEAR:1050` — on this VM (~1.5 CPU share) history advances at roughly
8 years/minute, so a full run would take ~2 hours. Instead, generate with
`-gen` and finish the history early:

```sh
cd ~/workspace/df-agent-harness/third_party/df_47_05
DISPLAY=:99 ./dfhack -gen 1 20261125 "SMALL REGION"
# While history is running the screen says "Enter or ESC to pause/finish".
# There is no window manager under Xvfb, so xdotool windowactivate fails;
# send keys directly to the DF window:
WID=$(DISPLAY=:99 xdotool search --name "Dwarf Fortress" | head -1)
DISPLAY=:99 xdotool key --window "$WID" Return   # pauses; prompt appears:
#   u: Use the world as it currently exists / c: Continue / a: Abort
DISPLAY=:99 xdotool key --window "$WID" u        # finalize + save + quit
```

Observed run: paused at **Year 306** (38,725 historical figures, 400,017
events), then "Save World / Offloading units..." and the process exited
cleanly. Total wall time ~15 minutes (mostly history sim).

### Generated world (saved, ready for later phases)

- Save dir: `third_party/df_47_05/data/save/region1/` (42 MB;
  `world.dat` 27 MB, sha256 prefix `3f366a1f6b37b79f`)
- World shown in-game as **"Mitom Kodor, Folder: region1"** (gen screen
  called the planet "The Planets of Dawning"; a dwarven site in it is
  "Asteshzin, The Ivory Mountain")
- Seed: `20261125`, preset `SMALL REGION`, history stopped at year 306
- `-gen` exports in the DF dir root:
  `region1-00306-01-01-world_map.bmp`,
  `region1-00306-01-01-detailed.bmp`,
  `region1-00306-01-01-world_history.txt`,
  `region1-00306-01-01-world_sites_and_pops.txt`,
  `region1-world_gen_param.txt`
- Reproducing it exactly: delete `data/save/region1` and re-run the `-gen`
  command above with the same seed; the early-finish year will differ
  (depends on when you press Return), which is fine — any year ≥ ~100 is
  plenty of history for harness work.

**Not yet done:** no embark has been made in this world. Picking a starter
embark site is phase-1 work (interactive site selection or DFHack
embark-assistant); the world is ready for it.

## What was verified (2026-11-25, observed output)

1. DF 0.47.05 launches under Xvfb and reaches the main menu — screenshot
   `docs/main-menu.png` shows "DFHack 0.47.05-r8", "Slaves to Armok: God of
   Blood / Chapter II: Dwarf Fortress", v0.47.05.
2. DFHack loads: `stderr.log` contains `DFHack version 0.47.05-r8 (release)
   on x86_64`.
3. DFHack remote works at the main menu: TCP 5000 LISTEN, `dfhack-run ls`
   returns the command list, `dfhack-run lua 'print(...)'` returns
   `PROBE-OK df=v0.47.05 linux64 dfhack=0.47.05-r8`.
4. Small world generated and saved as `region1` (42 MB); re-launched DF,
   Start Playing lists "Mitom Kodor, Folder: region1" — screenshot
   `docs/world-select.png`.
5. Screenshot method for later phases: `DISPLAY=:99 xwd -root -silent
   -out /tmp/x.xwd && convert /tmp/x.xwd out.png`; keystrokes via
   `xdotool key --window <wid> <key>` (no WM, so `windowactivate` fails).

## Layout

```
third_party/
  downloads/            # original tarballs (kept, re-download not needed)
  df_47_05/             # DF + DFHack install (gitignored)
    df / dfhack         # launchers — ALWAYS use ./dfhack
    dfhack-run          # remote CLI client
    data/save/region1/  # generated small world
    region1-00306-*     # -gen exports (map, history, sites)
docs/
  SETUP.md              # this file
  main-menu.png         # main-menu screenshot (verification evidence)
  world-select.png      # generated world listed in Start Playing
```
