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

## Pause guard (added 2026-11-26, after the drink-0 incident)

While the daemon loop is paused, the game must be paused. The
planner loop runs `_pause_guard()` every iteration (every
`planner_interval`, 30 s): if the loop is paused but the game is
running, it re-pauses the game at once and logs a `pause_guard`
anomaly in the journal (`daemon_events`). This closes the "game
running free with no driver" hole: on 2026-11-26 a reload loaded
the drink-0 backup and the game came up unpaused, and ran free
with drink 0 and no driver until the parent paused it by hand.
A failed guard read never kills the loop; the next iteration
retries. Verified live 2026-11-26: a manually unpaused game was
re-paused by the guard within one interval, twice (the daemon-start
race and the manual unpause), with 2 `pause_guard` rows logged.

## Reload and run guards (added 2026-11-26, same incident)

- **reload_fort.py, GUARD 1 — pause verification after every load.**
  After any load, the pause flag is re-read; if the game came up
  unpaused, `set_paused(True)` pauses it at once (Space-key
  fallback, verified by re-reading) and the pause is re-verified.
  A reload must never leave the game running, even for a moment.
  The post-load pause state is logged every time.
- **reload_fort.py, GUARD 2 — refuse bad saves.** After loading,
  drink/citizens/date are read and reported. A save with drink < 10
  (~2 days at the measured M1 burn of ~5/day) is refused — exit 3,
  game left PAUSED — unless `--force` is passed. A bare region name
  must never silently land the fort on a drink-0 state again.
- **m1_driver.py, GUARD 3 — pre-flight check.** Before a run starts
  the driver verifies: game paused (fresh RPC read via
  `GET /v1/pause`, not the poller's cached state), drink >= 10,
  citizens > 0, daemon loop paused. Any failure refuses the run
  (exit 2) and says which check failed. On exit — normal, error, or
  crash — the driver re-pauses the game and verifies the pause stuck
  via `GET /v1/pause`, retrying once. The driver never exits with
  the game running.
- **M1 start procedure.** Always name the save explicitly with
  `--exact` (e.g. `scripts/reload_fort.py region2-00125-04-01
  --exact`). Never use a bare region name for an M1 start while the
  newest backup is a bad state. The driver runs its pre-flight
  against that save before the model is consulted.
- **`GET /v1/pause`** returns the fresh RPC pause flag
  (`{"paused": bool}`), for run-script pre-flight checks. The
  snapshot cannot answer this (`paused_read` restores the entry
  pause state after the collect) and `/v1/status` is the poller's
  cached state, which only updates while paused — both would lie
  about a running game.

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

## Model presentation

This section is required by the 2026-11-27 presentation constraint
(GOAL.md, coordinator log 2026-11-27 ~17:47 PT): every new system
must state how its information reaches the model, what it costs,
and what it deliberately does not push. The snapshot stays an
index: counts, exceptions, and diffs only, about 4,700 tokens
typical, never a replacement for full state. Budgets hold (target
30K, warning 60K, compaction 100K, hard cap 140K on a 200K
window), enforced by the assembler's token accountant with its
cut order. No system bolts its own dump onto the snapshot.

### Snapshot: the daemon owns the clock, not the text

The daemon does not write snapshot text. It owns the loop and
the clock (§How the daemon ticks) and assembles the snapshot
from the fresh collect through the assembler. What reaches the
model from the daemon is the snapshot itself, the suggestion,
and the failure feedback when a tick or an action fails. The
daemon's own state (poll intervals, RPC health, pause guard
state, reload guards) never enters the snapshot. The model sees
the fort, not the machinery.

**Token cost.** At 7 dwarves and at 50 dwarves alike, the daemon
layer costs 0 tokens in the snapshot: it writes no section. Its
cost is the snapshot it assembles, stated in OBSERVE.md. It does
not grow with population, because the daemon adds no text of
its own at any population.

### Query route: GET /v1/status and GET /v1/health (live)

GET /v1/health needs no auth and says whether the daemon is up.
GET /v1/status returns the daemon's state, but after a restart
its cache is stale: the live snapshot (GET /v1/snapshot) is the
truth, not /v1/status. The agent asks the health route when it
needs to know the daemon is alive; it never asks for the
daemon's internals. The control routes (POST /v1/control/*) are
for the operator and the driver, not for the playing model:
agent tools never include pause/unpause.

### Briefing: none from this layer

The daemon does not brief. It delivers the briefings that
briefings.py fires, on the events the event system raises. A
daemon restart, a poller hiccup, or an RPC retry is logged, not
briefed. The model is never told about machinery unless the
machinery has failed and the run cannot continue, in which case
the run ends with a hard error, not a briefing.

### Opportunities: none from this layer

The daemon does not suggest. It runs the snapshot's suggestion
as a fallback at 6 idle ticks (the stall handling), and it
sharpens the prompt at 3 idle ticks. Both are daemon behavior,
not opportunities. The opportunities section carries facts
about the fort, never facts about the daemon.

### What the system deliberately does NOT push, and why

- **Daemon internals.** Poll intervals, RPC retries, pause
  guard state, and reload guards are operator concerns. The
  model sees the fort. Pushing internals would be noise the
  model cannot act on.
- **Stale status.** After a restart, /v1/status is stale. The
  presentation never presents a stale number as fresh. The
  live snapshot is the truth.
- **The clock as a number.** The daemon owns the clock; the
  agent owns decisions. The snapshot carries the date and the
  tick. The daemon never tells the model how many ticks it has
  left to decide.
