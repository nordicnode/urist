# DF Agent Harness — Daemon (`dfh`)

The daemon is the long-running process that plays the fort: it owns the
one DFHack RPC connection, polls the game, runs the planner every 30 s,
and serves the REST API + SSE event stream. DF 0.47.05 pinned, never
50.x.

## Lifecycle

```sh
cd ~/workspace/df-agent-harness
.venv/bin/python scripts/dfh.py start    # daemon + HTTP on 127.0.0.1:8765
.venv/bin/python scripts/dfh.py stop     # graceful stop (forced quicksave; ~45 s)
.venv/bin/python scripts/dfh.py status   # health + poller/planner counters
```

- `dfh start` refuses to start a second daemon (pid file). The daemon
  does NOT launch DF itself — launch DF first (`bash scripts/recover.sh`
  after a VM reboot, or `DISPLAY=:99 ./dfhack` from
  `third_party/df_47_05/`).
- `dfh stop` is graceful: it quicksaves, stops the poller, publishes
  `daemon_stopped`, and shuts down the HTTP server. (A SIGTERM handler
  that called `stop()` synchronously deadlocked against
  `serve_forever()` on the same thread — fixed 2026-11-26: the handler
  only sets a flag and kicks shutdown from a helper thread.)
- DF ignores SIGTERM: stop the game with `pkill -9 -x Dwarf_Fortress`.
  The daemon survives a dead game (planner ticks fail on the focus
  probe, poller skips) and resumes when DF is back on the map — but it
  does NOT reinstall the watcher into a relaunched DF on its own;
  restart the daemon after a reload.
- After a VM/cell reboot, apt packages (xdotool, scrot, SDL/GL libs)
  are gone until the system package replay restores them.
  `scripts/recover.sh` handles it: the apt step is non-fatal, and
  xdotool/scrot are extracted from cached .debs into
  `scratch/tools/` (source `scratch/tools-env.sh` for PATH/LD_LIBRARY_PATH)
  and the SDL/GL libs into `scratch/deblibs/` (LD_LIBRARY_PATH).
  The daemon resolves bare `xdotool` via PATH, so start it with that
  environment when the system packages are missing.

## State dir

`~/.config/df-agent-harness/`:

| File | Contents |
|---|---|
| `config.json` | ports, intervals, thresholds (see below) |
| `token` (0600) | bearer token for the HTTP API |
| `journal.db` | planner decisions + daemon events (SQLite) |
| `events.jsonl` | watcher event log (append-only, drained with a persistent offset) |
| `drain-offset.json` | watcher drain offset (no full-log replay on restart) |
| `daemon.pid`, `daemon.log` | pid file, stdout log |

## Config (`config.json`)

| Key | Default | Notes |
|---|---|---|
| `http_host` / `http_port` | 127.0.0.1 / 8765 | localhost-only |
| `df_host` / `df_port` | 127.0.0.1 / 5000 | DFHack RPC |
| `display` | `:99` | Xvfb display for xdotool |
| `allow_raw_actions` | false | `lua`/`command` endpoints return 403 unless true |
| `no_auth` | false | bearer token required unless true |
| `fast_interval` | 6.0 s | poller lite collect while running |
| `paused_interval` | 10.0 s | poller lite collect while paused |
| `slow_interval` | 60.0 s | stocks + mandates cadence |
| `planner_interval` | 30.0 s | planner tick cadence |
| `planner_max_actions` | 2 | actions executed per tick |
| `backoff_s` | 180.0 s | per-goal backoff after a failed action |
| `quicksave_interval` | 3600.0 s | first quicksave 1 h after daemon start (not on tick 1) |
| `drink_warn` / `drink_critical` | 20 / 5 | drink units |
| `food_warn` / `food_critical` | 15 / 5 | food units |

Poll intervals were raised 2026-11-26 (fast 2.0→6.0, slow 30→60)
after measuring ~98% RPC-server saturation at the old rates (lite
collect ~1.6 s every 2 s + planner ~3 s/30 s + slow ~5 s/30 s →
queueing → 30 s timeouts → stale replies).

## Endpoints (all `127.0.0.1:8765`, bearer token except `/v1/health`)

| Route | Method | Notes |
|---|---|---|
| `/v1/health` | GET | no auth; daemon + DF reachability |
| `/v1/state` | GET | poller's **lite** last_state (fast sections only), not a full collect |
| `/v1/status`, `/v1/units`, `/v1/unit/{id}` | GET | live reads |
| `/v1/buildings`, `/v1/jobs`, `/v1/items`, `/v1/reports`, `/v1/map`, `/v1/cursor` | GET | live reads |
| `/v1/events` | GET | SSE stream + JSON |
| `/v1/journal`, `/v1/goals`, `/v1/tasks` | GET | journal, goals, tasks (+create/get/done/delete) |
| `/v1/control/daemon` | GET | daemon state |
| `/v1/actions/{pause,dig,undesignate,chop,gather,build,deconstruct,stockpile,order,order-remove,queue-job,labor,key,cursor,lua,command}` | POST | verified actions; `lua`/`command` need `allow_raw_actions` |
| `/v1/tasks/{name}` | POST | run a composed task |
| `/v1/control/quicksave`, `/v1/control/daemon/pause`, `/v1/control/daemon/resume` | POST | control |

## How the daemon ticks

1. **Focus probe first.** Every planner tick and every poller cycle
   probes the GUI focus (`dfhack.gui.getCurFocus`, GUI state only)
   before any world-state read. While the game is on a no-fort focus
   (`movieplayer`, `title`, `loadgame`, `dfhack/lua`, `dfhack/lua/*`)
   the cycle is skipped — a full Lua collect during map load crashed
   DF twice live (2026-11-26, double-free abort at "Resetting
   textures"). The watcher drain is file-only and still runs.
2. **Dialogs.** A known modal dialog (`topicmeeting`, `textviewer`,
   `topicmeeting_takerequests`, `requestagreement`) is dismissed with
   its verified key and the tick is skipped. An unknown focus is
   logged once as `dialog_blocked` and the tick is skipped — never
   blind-keyed.
3. **Full collect + decide.** The planner decides from a full
   `observe.collect` (~3 s), never from the poller's lite snapshot
   (deciding from lite state hallucinates drink 0 / no workshops).
4. **Act (max 2 actions/tick)** through the verified `act()` path;
   failures back off that goal for 180 s (no blind retries) and are
   journalled with the reason.
5. **Unpause at end of tick.** Actions re-pause the game after their
   waits; without this the fort sits paused for the whole interval.
   A critical threat (hostile ≤5 tiles) returns early and holds the
   game paused instead.

## RPC robustness (learned live 2026-11-26)

- **Stream poisoning:** a call that times out mid-reply leaves a
  partial reply in the socket; every later call then reads the stale
  leftover and returns empty text in ~300 ms. Fix: `call_raw` drops
  the socket on ANY exception after the request is sent; the next
  call auto-reconnects (the failed call is NOT retried — its Lua may
  already have run). `run_lua_json` resets on invalid JSON;
  `run_section` verifies the reply's `"section"` tag and resets +
  returns ok False ("stale reply") on mismatch.
- **Quicksave:** `dfhack-run quicksave` writes only to
  `data/save/current/`, NOT to `region1/world.sav` — the daemon
  verifies the region save's mtime advanced and logs a
  `daemon_error` when it did not. Quicksave blocks RPC ~30–40 s.
- **First-tick quicksave bug:** `_last_quicksave` was initialised to
  0.0, so the first planner tick fired a quicksave immediately
  (a save landed ~30 s after daemon start, and the game died right
  after it). Fixed: initialise to `time.time()`.

## Known limits

- The daemon does not survive a cell reboot (nothing does); restart
  it after `recover.sh`.
- The `daemon_stopped` journal row is sometimes missing after a
  clean stop (log_event can fail silently, e.g. DB lock) —
  observability only.
- `/v1/screen` is not implemented (ASCII profile not active).
