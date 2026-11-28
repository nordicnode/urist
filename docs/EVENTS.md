# DF Agent Harness — Event System (Phase 3)

The harness watches the game and **pings the agent when things
happen** — push, not poll-only. Two sources feed one ordered stream
(PROTOCOL.md §5):

1. **In-game push (primary):** an eventful Lua watcher
   (`src/dfagent_harness/lua/watch.lua`) registers DFHack eventful
   handlers that append one JSON object per line to
   `dfh-events.jsonl` in the DF directory. The daemon drains it by
   byte offset.
2. **Poll-diff (fallback + coverage):** `DiffDetector` compares
   consecutive observation snapshots and emits events on changes.
   This covers everything eventful misses (dwarf distress from unit
   state, stock levels, season changes) and keeps working if the
   watcher fails to load.

Both feed `EventBus` (in-process pub/sub: ordering, dedup, replay),
served over SSE by the minimal HTTP server
(`src/dfagent_harness/server/` package, `routes_events.py`;
`GET /v1/events`).

## Status

- **Eventful works in 0.47.05-r8 fortress mode — verified live.**
  `JOB_COMPLETED` fired 14 times in ~18k ticks (Eat/Drink2
  completions), `UNIT_DEATH` 17 times (wildlife), `REPORT` and
  `UNIT_NEW_ACTIVE` fire on registration (backlog replay — see
  below) and on new activity. `INVASION` has no live trigger on this
  fort (no invasion yet) — implemented, fixture-tested, live-untested.
- Poll-diff verified live (pause toggle, manager-order
  disappearance, migrant `citizen_new` in recorded data) and by
  fixture for the rest.
- Full suite: `tests/test_events.py` (unit, fixtures),
  `tests/test_events_live.py` (live, skips without a game),
  `tests/test_server.py` (SSE endpoint in-process).

## Running it

```sh
# Install the watcher in the live game (idempotent; re-run after a
# world reload — see "Watcher install" below):
.venv/bin/python scripts/dfh-events.py --install-watcher
.venv/bin/python scripts/dfh-events.py --watcher-status

# Stream events to stdout (direct attach; game stays paused):
.venv/bin/python scripts/dfh-events.py --follow
.venv/bin/python scripts/dfh-events.py --once     # one poll cycle

# Minimal HTTP server (SSE + state + health on 127.0.0.1:8765):
.venv/bin/python scripts/dfh-events.py --serve [--http-port 8765]
curl -s http://127.0.0.1:8765/v1/events?limit=5
curl -N -H 'Accept: text/event-stream' http://127.0.0.1:8765/v1/events
curl -N -H 'Accept: text/event-stream' \
     -H 'Last-Event-ID: 42' http://127.0.0.1:8765/v1/events
```

## Event catalog

Envelope (PROTOCOL.md §5.3, plus `urgency`):

```json
{"seq": 1042, "id": "evt-1042", "type": "threat",
 "severity": "critical", "urgency": "immediate",
 "tick": 123456, "year": 306, "at": 1764020123,
 "source": "eventful", "dedup_key": "threat:88",
 "data": {"unit_id": 88, "name": "Goblin thief", "pos": [98, 102, 174]}}
```

`severity`: `info` | `notice` | `warning` | `critical`. `urgency`
derives from severity (`critical`→`immediate`, `warning`→`soon`,
`notice`→`routine`, `info`→`low`). `tick` is `cur_year_tick`
(tick within the year); `at` is wall-clock. `dedup_key` is the
bus-level dedup identity (absent when the event is inherently
unique). `seq`/`id` are assigned by the bus. Consumers must ignore
unknown future types.

| Type | Severity | Source | Data | Trigger / detection |
|---|---|---|---|---|
| `daemon_started` / `daemon_stopped` | info | daemon | `{version}` | Server/CLI lifecycle |
| `daemon_error` | critical | daemon | `{error, context}` | Poll RPC failure (rate-limited: 1/min) |
| `state` | info | poll | full compact status | Initial snapshot on (re)connect (server only) |
| `mode` | info | poll | `{viewscreen, game_mode}` | `focus` changed |
| `pause` | notice | poll | `{paused}` | Pause flag changed — **live-tested** (toggle) |
| `year` | info | poll | `{year}` | Year rolled over |
| `season_change` + | info | poll | `{season, season_index}` | Season index changed — observed live (Spring→Summer, tick 100800) |
| `citizen_new` | info | poll | `{unit_id, name, pos, profession}` | Citizen id appears — **live**: migrants Bim Kereshtân + ùshrir Tunvucar at tick 123590 (recorded states; detector verified on those snapshots) |
| `citizen_gone` | notice | poll | `{unit_id, name, pos}` | Citizen id vanishes (death, departure — check `unit_death`) |
| `new_arrival` + | warning / info | poll | `{unit_id, name, race, kind, role, pos, dist_nearest_citizen?, at_baseline}` | A non-citizen, non-hostile unit appears in `units.wildlife` / `visitors` / `livestock` — **live 2026-11-26** (see §new-arrival gap below). Visitor = warning; wildlife = warning within 15 tiles of a dwarf, else info; livestock (a birth) = info. `at_baseline` marks units already present when monitoring started — those are surfaced, not silenced. A unit that leaves and returns re-fires with a fresh dedup key. |
| `threat` | critical | poll | `{unit_id, name, race, pos}` | Hostile id appears in `units.hostiles` — fixture-only (no hostiles on this fort) |
| `invasion` | critical | eventful | `{args}` | Eventful INVASION — implemented, fixture-only (no live invasion) |
| `hostile_spawn` | critical | eventful | `{unit_id, name, race, pos}` | Eventful UNIT_NEW_ACTIVE with a hostile unit — fixture-only |
| `unit_death` | warning | eventful | `{unit_id, name, citizen, race, pos}` | Eventful UNIT_DEATH — **live**: 17 wildlife deaths in one run. Name resolved by the daemon against its last snapshot (the unit is already gone from the game) |
| `dwarf_distress` | warning / critical | poll | `{unit_id, name, kind, detail}` | See thresholds below — fixture-tested (no distress on this fort yet) |
| `report` | notice | eventful/poll | `{text, pos, announcement, report_index?}` | New announcement / combat report — **live**: weather + death reports flowed through the watcher; poll path verified on recorded states |
| `job_cancelled` | warning | poll | `{text, pos, announcement}` | A report containing "cancels" — fixture-only (no cancellation observed yet) |
| `job_completed` | info | eventful / poll | `{job_id, job_type, worker_id?, pos?}` / `{manager_order_id, job_type}` | Eventful JOB_COMPLETED — **live** (GatherPlants #31 + Eat/Drink2, see below). Poll: a job id disappearing from `world.jobs` — **live** for manager-order disappearance (removal and completion are indistinguishable by poll; see note) |
| `stock_low` + | warning / critical | poll | `{kind, units, threshold}` | Drink/food units below thresholds — fixture-only (drink 39 / food 38 at last check, above both lines) |
| `mandate` + | warning | poll | `{mandate_id, mandate}` | A mandate appears in `world.mandates` — implemented, live-untested (fort has no mandates; no nobles appointed) |
| `task_completed` / `task_failed` | notice / warning | daemon | `{task, detail, evidence}` | Phase 4 (composed tasks) — not emitted yet |
| `goal_satisfied` | notice | daemon | `{goal_id, name}` | Phase 4 (goals) — not emitted yet |
| `save` | info | daemon | `{}` | Phase 4 (quicksave) — not emitted yet |

Types marked `+` are phase-3 additions to the PROTOCOL.md §5.4
catalog (the protocol allows additions, never renames).

### Dwarf-distress thresholds — measured, not guessed

`counters2` hunger/thirst/sleepiness timers climb **1 tick per game
tick**. Measured live on Athelunol, 2026-11-26, two unpaused runs
(40 + 65 samples, ~5 s apart, 7 dwarves):

| Timer | Dwarf acts at | Measured window |
|---|---|---|
| hunger → Eat job | **40,000** | last no-job 39,630–40,464; first Eat 40,043–40,923; resets to 43–440 on eating |
| thirst → Drink2 job | **20,000** | last no-job 19,731–20,102; first Drink2 20,186–20,557; resets to 31–322 on drinking |
| sleepiness → sleep | **50,000** | maxima before reset 49,661–50,240; resets to ~300–4,700 |

Distress kinds (edge-triggered; a kind fires when it appears or its
severity rises, re-arms when it clears):

| Kind | Line | Meaning |
|---|---|---|
| `starving` | hunger ≥ 50,000 (warning); ≥ 70,000 (critical) | 10k ticks past the eat trigger without eating — food unreachable or absent. The critical line is **inferred, not observed**: no dwarf has starved on this fort, and the death timing is unmeasured |
| `thirsty` | thirst ≥ 30,000 (warning); ≥ 50,000 (critical) | Same shape, past the drink trigger. Critical line inferred |
| `exhausted` | sleepiness ≥ 60,000 (warning) | 10k past the sleep trigger without sleeping. Inferred |
| `unhappy` | stress category 1 (level ≥ 25,000) | Cutoffs from `getStressCategory`: 50000/25000/10000/-10000/-25000/-50000/-100000 (category 0 = most stressed). Baseline fort: all citizens category 3, levels -20..84 |
| `tantrum_risk` | stress category 0 (level ≥ 50,000) | Most-stressed category; urgency `immediate` |
| `wounded` | `wound_count` > 0 | Re-fires when the count changes |

### Stock thresholds

Adopted from dfkit's daemon policy (PROTOCOL.md §3.1: drink < 20 →
brew, food < 15 → cook), for a 7-dwarf fort — not measured against
starvation: drink ≤ 20 / food ≤ 15 → `stock_low` warning;
drink ≤ 5 / food ≤ 5 → critical. Last live reading: drink 39u,
food 38u (both above the lines).

### Poll vs eventful, and the known ambiguities

- **FellTree jobs never leave `world.jobs.list`** (ACTIONS.md), so
  poll-diff can never report a FellTree completion — only eventful
  can. **Live-untested on this fort**: every tree is a cavern tree
  (z=11–33, no surface trees at all) and none is reachable — the
  marked tree at (85,70,32) spawned FellTree job #2, which no dwarf
  took in 120 s unpaused; the designation was cleared afterwards and
  the stale job remains listed (inert, unreachable). A FellTree
  completion needs a dug route to a cavern first.
- **Manager orders are never worked without a manager noble.**
  Verified live: a MakeBarrel x1 order sat at `amount_left` 1/1
  through 90 s unpaused — no job spawned. So a manager-order
  *completion* cannot be triggered on this fort until a manager is
  appointed (UI-only, no API). The task's "complete a manager
  order" step is therefore satisfied by the GatherPlants completion
  below, not by an order.
- **Poll cannot distinguish a manager order completing from one
  being removed**: both look like the order vanishing. The detector
  reports the disappearance as `job_completed` either way; the
  daemon must not treat a poll `job_completed` for an order as proof
  it was worked. Eventful `JOB_COMPLETED` (with a job id) is the
  authoritative completion signal.
- **A job that vanishes in the same poll batch as a "cancels"
  report** is reported as `job_cancelled`, not `job_completed` —
  a deliberate heuristic (the report names the dwarf, not the job,
  so the link is by timing only).
- **Migrant arrival auto-pauses the game** (observed: tick froze at
  123590 on "Some migrants have arrived"). The poller must expect
  long frozen stretches and not mistake them for a dead game.

## SSE protocol + replay semantics

- `GET /v1/events` with `Accept: text/event-stream` opens a stream.
  Each event is one SSE message: `id: <seq>`, `data: <event json>`,
  blank line. A `:heartbeat` comment is sent every 30 s while idle.
- `?since=<seq>` or the `Last-Event-ID` header replays missed events
  from the bus ring, then continues live. Replay-then-subscribe is
  ordered so no event is delivered twice (see `server/routes_events.py`).
- Without the SSE Accept header, `GET /v1/events?limit=N`
  (`?since=` also works) returns a JSON array:
  `{"events": [...], "latest_seq": N}` (default limit 100, max 1000).
- The bus ring holds the last 1000 events in memory (configurable
  `maxlen`). With `--journal <path>`, the bus also appends every
  event to a JSONL file and restores the ring + sequence on restart —
  replay then survives a daemon restart (within the ring window).
  Without a journal, a restart resets the sequence at 1.
- Dedup: an event carrying a `dedup_key` already in the ring is
  dropped. Keys leave the seen set when their event leaves the ring,
  and detectors mint a fresh key per activation for re-firing
  conditions (distress, stock levels), so a genuine re-occurrence is
  never swallowed. Cross-source dedup works where it matters:
  eventful and poll `job_completed` share the key
  `job_completed:<job_id>`, so one completion emits once even when
  both sources see it.

## Poll intervals + costs

The poller (`EventPoller`) runs two cadences:

| Cadence | Sections | Default interval |
|---|---|---|
| Fast | `status`, `units_lite`, `jobs`, `reports` | 2 s running, 10 s paused |
| Slow | `stocks` (+ `mandates` probe) | 30 s |

Measured costs (Athelunol, 7 citizens at measurement time — the
fort has since grown to 15 via migrants; per-section means of
3 runs, 2026-11-26 after the VM-replacement reload):

| Section | Cost |
|---|---|
| `status` | ~50–110 ms (first call slowest) |
| `units` (full) | ~630–675 ms |
| `units_lite` | ~81 ms |
| `jobs` | ~5 ms |
| `reports` | ~5 ms |
| `stocks` | ~900–940 ms |
| `map` | ~10 ms |
| `buildings` | ~14 ms |
| fast set (full units) | ~670–745 ms |
| fast set (lite units) | ~121 ms |

Why `units_lite`: the full `units.lua` dumps needs, skills, labors
and goals for every citizen (~0.65 s, dominated by DFHack Lua's
~75 µs/function-call cost — see OBSERVE.md §10). The detector only
reads id/name/race/profession/pos/idle/job/mood/stress/counters/
wounds, so `units_lite.lua` returns exactly those in the same
`units` shape — 8x cheaper. The full dump stays available on demand
(`GET /v1/state`, `dfh-observe.py`) — the poller never needs it.

Tradeoff, stated plainly: at the 2 s fast interval with lite units,
the poller spends ~6% of wall time inside RPC calls while running
(~1% while paused at 10 s). With full units it would be ~35%.
Stocks (~0.9 s — the slowest section, it walks every in-play item)
runs only every 30 s. If the fort grows (more citizens, more
jobs/reports), the units/jobs sections grow with it and the interval
is the lever — raise `--interval` before touching the detectors.
The 10 s paused interval exists because nothing changes while
paused except watcher events (which are drained every tick
regardless) — pausing the game does not pause the push channel.

Quicksave blocks RPC for ~30–40 s (OBSERVE.md §9). A poll that hits
a save fails into `daemon_error` (rate-limited to one per minute)
and the next tick recovers; the poller never dies on a transport
error.

## The eventful watcher install

**Resolution of PROTOCOL.md §8 question 4** (how Lua helpers get
onto DFHack's script path on a clean install): they don't need to.
The watcher is installed by sending its source as a one-shot
`RunCommand("lua", code)` — the same transport phase 1 verified for
helpers. The handlers live in the `plugins.eventful` Lua module
state for the life of the DF process, so no copy/symlink/script-path
setup is needed. The canonical source is
`src/dfagent_harness/lua/watch.lua` (with the shared
`lua/json.lua` prelude prepended by the installer); it is also
written into the DF tree at `third_party/df_47_05/hack/scripts/
dfh_watch.lua` as a plain script so it can be re-run from the DFHack
console (`dfh-watch`) or `dfhack-run`.

Install / status / remove:

```sh
.venv/bin/python scripts/dfh-events.py --install-watcher
.venv/bin/python scripts/dfh-events.py --watcher-status
.venv/bin/python scripts/dfh-events.py --uninstall-watcher
```

What the watcher does (`watch.lua`):

- `require('plugins.eventful')`; `enableEvent(type, 1)` and a
  handler under the key `'dfh-watch'` for `JOB_COMPLETED`,
  `UNIT_DEATH`, `REPORT`, `INVASION`, `UNIT_NEW_ACTIVE`.
- Each handler appends one JSON object per line to
  `dfh-events.jsonl` in the DF directory (absolute path substituted
  by the installer), wrapped in `pcall` so a logging failure can
  never break a game tick.
- **Baseline suppression (measured behaviour):** enabling `REPORT` /
  `UNIT_NEW_ACTIVE` replays the backlog — every existing report
  index and every active unit fires once, spread over frames even
  while paused (observed: 168 REPORT + 21 UNIT_NEW_ACTIVE at
  registration). The watcher records the report count and active
  unit ids at install time and suppresses events at or below the
  baseline, so the daemon never sees the replay.
- **The new-arrival gap (found 2026-11-26, fixed):** a troll arrived
  in the caverns and produced NO event anywhere — zero
  `hostile_spawn` events, no `UNIT_NEW_ACTIVE` for the troll in the
  log. It was found only because a live test re-collected
  `/v1/units` and saw it in the visitor list: pull, not an alert.
  Cause, twofold: (1) the drainer deliberately drops non-hostile
  `UNIT_NEW_ACTIVE` (the watcher record cannot tell wildlife from
  visitor from livestock, so the classified poll diff is the right
  source); (2) the poll diff only covered citizens (`citizen_new`)
  and hostiles (`threat`) — wildlife/visitors/livestock were never
  diffed, and the first snapshot (baseline) emitted nothing at all.
  Fix: `DiffDetector` now emits `new_arrival` for wildlife /
  visitors / livestock, both on the baseline (units already present
  when monitoring starts, flagged `at_baseline`) and on later
  diffs, and the attention section (`src/dfagent_harness/attention.py`,
  `GET /v1/attention`) lists them as first-class items with class,
  name, and position. The drainer's drop of non-hostile
  `UNIT_NEW_ACTIVE` stays — the poll diff is now the source that
  actually fires, so the original claim in the code ("covered by
  poll-diff") is true instead of aspirational.
- **Handler argument shapes (measured, not the dfkit docs):**
  `JOB_COMPLETED` gets the job struct (read `.id` / `.job_type` /
  worker via `dfhack.job.getWorker`); `REPORT` gets a report index
  (number); `UNIT_NEW_ACTIVE` and `UNIT_DEATH` get the unit **id**
  (number, not the struct). A dead unit is already gone from
  `world.units.all`, so the watcher emits the id only and the daemon
  resolves the name against its last snapshot; a newly-active unit
  is in the active list at fire time, so hostility/name resolve in
  the watcher. `INVASION`'s signature is unsettled (no live
  invasion) — the handler records its raw args.
- **World reload:** eventful clears its C++ listeners on unload.
  The watcher hooks `dfhack.onStateChange.dfh_watch` to re-enable +
  re-baseline on `SC_WORLD_LOADED`. That path is designed, not
  live-tested (no world reload was performed in phase 3); the
  daemon also reinstalls the watcher on start, which is the tested
  route. Re-running `--install-watcher` after any reload is safe
  (idempotent, re-baselines).

The watcher log is append-only JSONL; the drainer tracks a byte
offset, holds a trailing partial line for the next drain, and skips
malformed lines. It is safe to delete the log while DF is paused
(the drainer re-reads from 0 when the file shrinks).

## What fired live vs fixture-only

| Event | Live evidence |
|---|---|
| `job_completed` (eventful) | GatherPlants job #31: spawned at (92,79,42), completed at tick 59590, watcher logged `{"kind":"JOB_COMPLETED","job_id":31,"job_type":"GatherPlants","worker_id":15201,...}`; drainer converted it to `job_completed`. Also 14 Eat/Drink2 completions in the pre-reload run-1 probe (14 in ~18k ticks) |
| `unit_death` (eventful) | 17 wildlife deaths in run 1 (ids in the watcher log) |
| `report` (eventful) | Weather + death reports flowed at registration (backlog) and live |
| `pause` (poll) | Toggle test, live |
| `citizen_new` (poll) | Migrants Bim + ùshrir at tick 123590 (pre-reload) — detector verified against the before/after snapshots; the migrants were lost in the VM-replacement reload (fort restored to the 01:01 save) |
| `season_change` (poll) | Spring→Summer observed at tick 100800 pre-reload (announcement + status) |
| `job_completed` (poll) | Manager-order disappearance, live |
| `threat`, `invasion`, `job_cancelled`, `stock_low`, `mandate`, `dwarf_distress`, `job_completed` for FellTree | Fixture-only — no invasion, cancellation, shortage, mandate, distressed dwarf, or reachable tree has occurred on this fort yet |
| `hostile_spawn` (eventful) | **Live, wildlife-grade**: two eagles flagged hostile (ticks 76630, 95530); one report reads "The eagle corpse attacks the woodcutter but She jumps away!" — real hostility, but a wild animal, not a siege. The watcher's hostility flag is best-effort (any non-tame wild unit); phase 4 should tier it by proximity/reports before treating it as a threat |

## What phase 4 will consume

- The bus is the daemon's event feed: `EventPoller` + `EventBus`
  are constructed once, and the phase-4 daemon loop subscribes to
  the bus (threat/invasion → pause the game first, then plan).
- `GET /v1/state` is the "one call to orient" endpoint; the poller's
  last snapshot is what it returns when one exists.
- `dwarf_distress` kinds are the planner's triggers for the needs
  loop (food/drink/sleep/stress/wounds); `stock_low` triggers
  brew/cook tasks; `job_completed` closes the wait primitive
  (phase 2's actions poll for completion — phase 4 can wait on the
  bus instead).
- Still missing for phase 4: bearer-token auth (PROTOCOL.md §3.3),
  the typed action endpoints, the SQLite journal (the JSONL journal
  is the interim), goal/task events, and the `save` event.
- Startup replay: the poller's `WatcherDrainer` starts at offset 0,
  so a fresh server re-emits the whole watcher log as events (232
  lines / 163 bus events on the 2026-11-26 smoke test, seq 1..163
  with fresh numbers). That is fine for a single long-lived daemon,
  but a restart replays history — phase 4 should persist the drain
  offset (or use the bus journal) so restarts resume, not replay.

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

### Snapshot: the Events section

The per-tick snapshot gains a short Events section, built from
the fresh event feed, in plain words. Two lines, in this shape:

```
Events: caravan arrived (Umshadònul). 2 new arrivals.
Attention: 1 hostile in range (15 tiles).
```

What is in it, and what is not:

- **Line 1, events.** The events that fired this tick, named by
  kind, capped at 3, each one clause. The event catalog (§Event
  catalog) is the full list; the snapshot names only what fired.
  Arrivals are listed in plain words, threats first, then new
  arrivals (attention.py), and an arrival stays in attention
  for one in-game day after its tick.
- **Line 2, attention.** The attention items the events raised,
  capped at 3, ranked with the other problems, never buried in
  a list. A quiet tick costs one line: "Events: none."
- **Diffs, not repeats.** When no event fired since the last
  tick, the assembler prints the short form ("events: none"),
  the same way the Buildings section already does. The section
  costs its full price only on ticks when an event fires.

**Token cost.** At 7 dwarves, the section as written above is
95 characters: about 31 tokens by the accountant's
3-chars-per-token rate, 23 on the wire. At 50 dwarves, with
more arrivals in a wave, it is about 300 characters: about 100
tokens by the accountant, 75 on the wire. The cost grows by
about 35 tokens from 7 dwarves to 50, because the section is
capped: 3 events maximum, 3 attention items maximum. It does
not grow with population, with the number of events in the log,
or with the size of a migration wave. If a future change makes
it grow with any of those, the change is refused until the
section is capped again.

### Query route: GET /v1/events (live) and SSE

GET /v1/events returns the event feed, with replay semantics
(§SSE protocol + replay semantics). The SSE push channel pings
the agent the moment something happens. The snapshot carries
what fired this tick; the route carries the history. The agent
asks the route when it needs to know what happened while it was
away, never as a matter of routine.

### Briefing: events drive briefings, they are not briefings

An event firing is what triggers a briefing (briefings.py), but
the event text is not the briefing text. The briefing states
what changed, what is urgent, and what can wait, in a few
hundred tokens at most, fired once when the event starts. The
cost of each briefing is stated in the system doc that owns the
event (TRADING.md for caravans, MILITARY.md for invasions,
MIGRANTS.md for waves). The event layer's job is to detect and
deliver; the briefing layer's job is to explain.

### Opportunities: none from this layer

Events do not suggest. An event raises an attention item, and
the attention item may become an opportunities entry when the
fact is actionable and the snapshot alone does not already say
it. The event layer reports what happened; the system docs
decide what is actionable. An event listed as an opportunity
would be the layer choosing for the model.

### What the system deliberately does NOT push, and why

- **The full event log.** The log is behind GET /v1/events with
  replay. The snapshot names what fired this tick. A log dump
  every tick would grow with the fort's history.
- **Raw event JSON.** The snapshot is plain words, never raw
  JSON. An event's kind, subject, and tick are rendered in
  words; the JSON is behind the route.
- **Fixture-only events.** Events that have only ever fired in
  fixtures, never live, are not presented as if they fired
  (§What fired live vs fixture-only). The snapshot names only
  what the live game produced.
- **Duplicate events.** The detectors are edge-triggered with a
  dedup key per unit id. The snapshot never names the same
  arrival twice.
