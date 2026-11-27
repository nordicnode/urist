# AGENTS.md — operating instructions for an AI working on this repo

This file is for an AI agent working ON Urist, not for a user running it.
(For the user-facing guide, read README.md. For the full setup, read
docs/SETUP.md. For the copy-paste setup prompt, see the README's
"Set it up with your AI" section.)

## What this is

Urist is a harness that lets any AI play Dwarf Fortress fortress mode
autonomously. It sits between the game and the AI: it reads the full state
of the fort, turns it into a form an AI can understand, lets the AI act
through a clean API, and pings the AI the moment something happens.

It is pinned to **Dwarf Fortress 0.47.05** with **DFHack 0.47.05-r8**. That
version is a deliberate choice, not a limitation. **Never propose or start
a 50.x port.**

## Project layout

```
src/dfagent_harness/   the harness: observe, actions, events, planner,
                       daemon, server, assembler, store, diary, dwarves,
                       dialogs, materials, placement, sites, wiki
src/dfhack_rpc/        minimal DFHack RPC client (stdlib + protobuf)
src/dfagent_harness/lua/  Lua helpers run inside the game via DFHack
scripts/               CLIs: dfh (daemon), dfh-observe, dfh-act,
                       dfh-events, m1_driver, reload_fort, recover.sh,
                       rebuild_diary, retry_diary, rpc_smoke,
                       freepi_token_poll
docs/                  OBSERVE.md, ACTIONS.md, EVENTS.md, DAEMON.md,
                       PLANNER.md, PROTOCOL.md, ACCEPTANCE.md,
                       DIALOGS.md, ADVANCED_MECHANICS.md, SETUP.md
tests/                 unit tests plus live tests against a running fort
third_party/df_47_05/  DF + DFHack install (gitignored)
third_party/downloads/ original tarballs (kept, never re-download)
saves-clean/           pristine clean-base save (gitignored, local only)
logs/                  M1 run logs (m1-*.jsonl)
```

The coordinator log (what was done, when, and why) lives outside the repo:
`~/workspace/goals/dwarf-fortress-0-47-05-autonomous-play-harness/hidden_files/coordinator-log.md`.
Log everything there. GOAL.md in the same goal dir is the design record.

## How to run things

- **Python:** always `.venv/bin/python`. Never the system python3 — it has
  no pytest and no protobuf.
- **Tests:** `.venv/bin/python -m pytest tests/ -q`. The offline tests pass
  without a game. The live tests need the game and the daemon running,
  and fail without them — that is expected, not a regression. The full
  suite takes ~6 minutes. **Offline invocation (do not improvise it):**
  ignore every `*_live.py` file AND deselect the six live classes that
  live in non-live files, by exact class name:
  `.venv/bin/python -m pytest tests/ -q --ignore-glob='tests/*_live.py' -k "not TestBriefingsLive and not TestCatalogLive and not TestDiagnoseLive and not TestSitesLive and not TestTasksLive and not TestWikiLive"`.
  Do NOT use `-k "not live"` or `-k "not Live"`: `-k` matching is
  case-insensitive, so "live" also deselects the scoring tests whose
  names contain "lives" (silently dropping 3 tests). A partial ignore
  once ran live tests against the game and advanced it to tick 135706.
- **The game:** launch with `./dfhack`, NEVER `./df` (`./df` runs vanilla
  DF with no DFHack loaded). It runs under Xvfb on display `:99`
  (`Xvfb :99 -screen 0 1024x768x24`). DFHack RPC listens on **TCP 5000**.
  Verify with `./dfhack-run lua 'print("PROBE-OK df="..dfhack.getDFVersion().." dfhack="..dfhack.getDFHackVersion())'`
  — it must print `PROBE-OK df=v0.47.05 linux64 dfhack=0.47.05-r8`.
  **DF ignores SIGTERM.** Stop it by PID after confirming its cwd
  via `/proc/<pid>/cwd` (main = `third_party/df_47_05`, scratch =
  `scratch/m2-embark/df`). **Never use bare `pkill -9 -x
  Dwarf_Fortress`** — it matches by process name and kills every DF
  at once (it killed the main fort while targeting the scratch DF on
  2026-11-27). `reload_fort.py` has the same flaw (line 229) and is
  owed a PID-based fix.
- **The daemon:** `.venv/bin/python scripts/dfh.py start|stop|status`.
  HTTP API on `127.0.0.1:8765`, bearer token in
  `~/.config/df-agent-harness/token` (0600). `/v1/health` needs no auth.
  The daemon keeps dying when the exec service restarts; restart it with
  `dfh.py start`. After a restart the `/v1/status` cache is stale —
  trust the live snapshot (`GET /v1/snapshot`), not `/v1/status`.
  `dfh.py stop` can claim "no daemon running" when the pid file is stale;
  SIGTERM the pid directly.
- **The M1 model:** DeepSeek V4.1 Flash via Free Pi, model id
  `deepseek-v4.1-flash-1017`, JWT at `~/.free-pi/agent/jwt.txt` (0600).
  Free Pi is the weak link (IncompleteRead, HTTP 429 "concurrent" when
  two drivers collide). Not a harness bug. If a model call fails with
  401, surface it as a hard error, never stall silently.
- **Git identity is not global.** Commit with
  `-c user.name=nordicnode -c user.email=nordicnode@users.noreply.github.com`.

## Live-verification discipline (non-negotiable)

- **No shortcuts.** A thing is either working, verified live against the
  real game with the real game mechanics, or it is not done. A mock or a
  unit test alone is not verification. Nothing unverified gets pushed.
- **Fix the root cause, not the symptom.** The proper fix, not a bandage.
  If the proper fix is bigger than the quick one, do the proper fix.
- **Address the issue, do NOT sidestep it.** Do NOT route around
  `queue_job`, do NOT avoid workshop jobs, do NOT make the model stop
  queueing jobs. Auto-recovery is a safety net, not the fix.
- **dig-now is NEVER an acceptable dig mechanism.** Digging goes through
  the harness's dig action with real designations, verified live.
- **Everything through the harness API.** No UI keystrokes or screenshots
  for game actions. Embark and save-load keystrokes are pre-game setup,
  quarantined — they are the only exception.
- **Do NOT modify dfkit.** It is a read-only reference at most.

## The M1 workflow

M1 is done (a full in-game day with a brew that completed and raised
drink), but it is still the workflow for every live run.

1. **Clean base.** The pristine base is
   `saves-clean/region2-00125-04-01-clean/`. Restore it by copying it
   into the save dir first — **never let the game play the backup dir
   directly** (its autosaves would overwrite the only clean copy):
   `rm -rf third_party/df_47_05/data/save/region2-00125-04-01 && cp -r saves-clean/region2-00125-04-01-clean third_party/df_47_05/data/save/region2-00125-04-01`
   (Remove the destination first — a bare `cp -r` into an existing save
   folder nests the copy inside it instead of replacing it.)
2. **Reload explicitly:**
   `.venv/bin/python scripts/reload_fort.py region2-00125-04-01 --exact`
   Verify the game loaded paused, on the clean base's date (125-04-01),
   with drink >= 10. GUARD 2 refuses a save with drink < 10 unless
   `--force` is passed. Re-verify the pause stuck shortly after load.
3. **Run:** `.venv/bin/python scripts/m1_driver.py` (default: 1 day =
   1200 ticks, 8 decision ticks, max 2 actions per tick). A failed model
   call or action ends the TICK, never the run. Stall handling: sharper
   prompt at 3 idle ticks, run the snapshot's suggestion as fallback at 6.
4. **Pre-flight guards** (in the driver, do not weaken them): game paused,
   drink >= 10, citizens > 0, daemon loop paused; refuse with exit 2.
   Verify paused on exit.
5. **Run-log review after every M1 run.** Read `logs/m1-*.jsonl` for idle
   ticks and why, repeated failed actions, log field errors, guidance
   gaps. Log "no new issues" when there are none. The game runs at ~7 FPS
   on this VM — a brew takes ~2600 game ticks of wall-clock waiting, so a
   job still queued after a few hundred ticks is not a stall.

## Push rules

- Only committed, verified work. Fetch first. **Never force-push.**
  Never discard commits. Commit with tests.
- The daemon owns the clock; the agent owns decisions. Agent tools never
  include pause/unpause.
- The no-stop mandate: do not stop at a milestone, commit, or handoff.
  Work stops only when a fort plays itself end to end with no
  intervention, or when Mikey says stop. When your run ends, your
  successor starts immediately — leave the state (game, daemon, log)
  clean and written up.

## Coordination

Another agent (the voice-call delegate) sometimes works the same live
game in parallel. Before any live work, verify the quiet window: no
pytest, no second daemon, no other M1 driver running. If the other actor
appears, stop, log exactly what it did, and flag it to the parent — do
not fight it. The parent serializes by killing its pytests.
