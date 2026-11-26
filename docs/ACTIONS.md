# DF Agent Harness — Verified Action Layer (Phase 2)

Every action follows one contract: read the world state **before**,
execute the mutation, then read the world state **after** through the
observation layer (`docs/OBSERVE.md`) and check the postcondition. A
success means "verified in the game", never "command sent". On any
failure the action stops at the first failure with an honest blocking
reason. There are no retries anywhere — a caller that wants to retry
must re-read state first and call `act()` again with fresh eyes.

Verified live on the Athelunol fort (region1, Mitom Kodor), DF 0.47.05
+ DFHack 0.47.05-r8, 2026-11-25/26. The full suite
(`.venv/bin/python -m unittest discover -s tests -v`) passes: 82 tests
(26 unit with a mocked transport, 8 live action tests, the rest phase-1
observation/RPC tests).

## Entry point

```python
from dfagent_harness import act
result = act(client, "designate_chop", box=(108, 96, 32, 112, 100, 32))
result.to_dict()
# {"ok": true, "action": "designate_chop",
#  "before": {"total": 1, "marked": 0},
#  "after": {"total": 1, "marked": 1},
#  "reason": "marked 1 tree(s) in [108, 96, 32, 112, 100, 32]; ...",
#  "error_kind": null, "detail": {...}, "took_ms": 1234,
#  "mechanism": "lua"}
```

`act(client, name, **kwargs)` returns an `ActionResult` and never
raises for a failed action. An unknown action name raises `ValueError`
(a caller bug, not game state). All actions are also importable
directly (`designate_dig`, `designate_chop`, `designate_gather`,
`manager_order_create`, `manager_order_remove`, `build_workshop`,
`labor_toggle`). The CLI `scripts/dfh-act.py` runs one action and
prints the JSON result (exit 0 ok / 1 action failed / 2 bad args).

## Mechanism: Lua, except pause

Mutations and targeted read-backs run as Lua helpers
(`src/dfagent_harness/lua/act_*.lua`, `probe_*.lua`) over the
`dfhack_rpc` transport via `RunCommand("lua", ...)` — the proven path
from phase 1. The one exception is pause/unpause, which uses RFR
`GetPauseState`/`SetPauseState` (verified to stick, phase 1). No other
RFR method offered a better call: RFR has no designation, order, labor
or building API, and its `SendDigCommand` only covers the dig modes the
Lua path already handles with a precise read-back.

| Action | Mechanism |
|---|---|
| `designate_dig` | Lua (designation bits + probe) |
| `designate_chop`, `designate_gather` | Lua (designation bits + probes) + RFR pause for the job-spawn/removal waits |
| `manager_order_create`, `manager_order_remove` | Lua (`act_order.lua`) + observe `jobs` section |
| `build_workshop` | Lua (`act_build.lua`, `probe_site.lua`, `probe_material.lua`) + observe `buildings`/`jobs` sections + RFR pause for the construction wait |
| `labor_toggle` | Lua (`act_labor.lua`) + observe `units` section |

## Error model

`ActionResult.error_kind` is one of:

* `null` — the action succeeded and its effect was observed.
* `"precondition"` — refused before writing anything (no trees in the
  area, no accessible material, site occupied, unknown name/kind).
  Nothing was written.
* `"transport"` — the RPC call failed or the read-back was unavailable,
  so the outcome is *unknown*. The caller must re-read state before
  deciding anything; it must never assume the mutation did or did not
  happen.
* `"verification"` — the mutation ran but the effect was not observed
  on re-read (or the game rejected it, e.g. a construction cancelled).
* `"timeout"` — an async effect (job spawn, workshop construction) did
  not appear within its bounded wait. The mutation itself may have
  taken effect; the caller must re-read state.

## Action catalog

### `designate_dig(box, mode="dig")`

Designate a rectangle for digging, or clear it (`mode="clear"`).
Modes: `dig`, `channel`, `ramp`, `up-stair`, `down-stair`,
`up-down-stair`, `clear`.

* **Preconditions:** the box is 6 ints in order and inside the map;
  every tile in the rect is a wall (checked by `act_dig.lua`, which
  refuses floor tiles before writing anything).
* **Postcondition:** a targeted probe counts dig designations in the
  rect before and after. A set requires every tile designated in the
  requested mode; a clear requires none remaining.
* **Verification:** designation-level only, while paused. No Dig job
  spawns and no terrain changes while paused — the job-spawn proof
  lives on chop/gather instead (see below).
* **Also:** after a successful set, the action flags the game's
  `process_dig` (see "The process_dig flag" below) so the game will
  act on the designation on later ticks. The game stays paused, so no
  Dig job spawns during the action.
* **Live evidence:** rect (90,90,41)–(91,91,41) went 0→4 designated
  tiles, then 4→0 on clear; no Dig job spawned while paused.

### `designate_chop(box, mark=True)` / `designate_gather(box, mark=True)`

Mark trees for chopping / shrubs for gathering in a rect
(`mark=False` undoes it).

* **Preconditions:** the box is valid; at least one tree (chop) or
  shrub (gather) is in the rect. Classification is by structure: a
  tree has `tree_info` set, a shrub has `is_shrub` set. A *sapling*
  has neither and is excluded from both (see "Saplings" below).
* **Postcondition (mark):** two tiers. (1) The designation bits read
  back marked while paused. (2) Only when something was newly marked:
  the game is unpaused (bounded, default 60 s, 0.25 s poll) and the
  action waits for a FellTree/GatherPlants job **with a new id** at one
  of the designation tiles — or for a marked plant to disappear
  (harvested faster than the poll). Either proves the game saw the
  designation. A job already at the tile before marking does not count
  as evidence (the game does not duplicate a job for a re-marked tree
  promptly — see "Sweep latency").
* **Postcondition (unmark):** the designation bits read back cleared.
  Jobs remaining at the tiles are then handled per type (see "Job
  removal" below) and reported in `detail["remaining_jobs"]`.
* **Live evidence:** chop on the tree at (110,98,32): 0→1 marked, a
  FellTree job spawned at the tile. Gather on the shrub at (97,98,42):
  0→1 marked, a GatherPlants job spawned at the tile. Both unmark to
  0 marked.

### `manager_order_create(job_type, amount=1)`

Create a manager order (e.g. `MakeBarrel` x5). Follows DFHack's own
`workorder.lua` pattern: id from `world.manager_order_next_id`,
`df.manager_order:new()`, `job_type`/`amount_left`/`amount_total`/
`frequency` set, inserted into `world.manager_orders`.

* **Preconditions:** `amount >= 1`.
* **Postcondition:** the order appears in the observe `jobs` section
  with the returned id, job type and amounts.
* **Known limit:** the order is verified to *exist*, not to be
  *validated* by the game. The game validates orders on ticks and
  this fort has no appointed manager noble, so the order's
  `status.validated`/`status.active` flags are left unset (as
  `workorder.lua` leaves them) and may stay unvalidated. The daemon
  must not assume a created order will be worked.
* **Live evidence:** MakeBarrel x5 created as order #1,
  `manager_order_count` 0→1, `amount_left`/`amount_total` 5/5.

### `manager_order_remove(order_id)`

Remove a manager order by id (erase from `world.manager_orders` +
`o:delete()`).

* **Preconditions:** an order with that id exists.
* **Postcondition:** it is gone on re-read.
* **Live evidence:** order #1 removed, `manager_order_count` 1→0.

### `build_workshop(kind, pos, build_timeout=120.0)`

Place a workshop (`carpenter`, `mason`, `still`, `kitchen` — all 3×3)
at a corner position and wait for construction to complete.

* **Preconditions:** the kind is known; the site is free (see
  "Stale building occupancy" — the probe now checks the occupancy
  flag, which `constructBuilding` itself checks); at least one
  **accessible** unit of the required material exists. Material inside
  a building does not count: all 3 embark logs sit inside the wagon
  (`flags.in_building=true`), and jobs cannot use them — the live test
  deconstructs the wagon first as setup when no accessible wood
  exists.
* **Postcondition:** the building appears in the `buildings` list
  immediately with a ConstructBuilding job; the game is then unpaused
  (if it was paused) and the action waits, bounded, for that job to
  finish. Completion is judged by the job disappearing while the
  building remains — `construction_stage` is recorded as evidence, not
  assumed. If the building vanishes instead, the game cancelled the
  job; the reason is taken from the newest matching announcement
  ("cancels" / "unable to complete").
* **Live evidence:** carpenter's workshop built at (100,85)–(102,87,42)
  (building #2, `construction_stage` 3), then deconstructed by the
  test. An earlier attempt at (85,85) was cancelled by the game with
  "Needs building material non-economic item" because the wood was
  still in the wagon — that failure is what the material precondition
  now guards against.

### `labor_toggle(unit, labor, on)`

Enable/disable a labor on one citizen, by exact name (CP437-encoded)
or unit id. Labors are indexed by enum name (`u.status.labors.MINE`,
`CUTWOOD`, `CARPENTER`, `HERBALIST`, …).

* **Preconditions:** the citizen exists; the labor name is a valid
  `df.unit_labor` enum name (an unknown name is a precondition
  failure from the helper).
* **Postcondition:** the citizen's labor list in the observe `units`
  section contains (or lacks) the labor.
* **Live evidence:** toggling CARPENTER on Deduk Stâkudunib off and
  back on; toggling MINE on a citizen by id.

## Findings that shaped this layer

### The `process_dig` flag

Setting dig bits directly in Lua does **not** set the game's
`process_dig` flag — only the UI does that — so the game may not scan
a new designation for a long time. Verified live: a marked tree
spawned no FellTree job in 65 s of ticks; after
`dfhack.job.checkDesignationsNow()` (which just sets that flag) the
job appeared within 2 s. The mark path (and dig-set) therefore calls
`checkDesignationsNow()` after writing the bits and before the
unpaused wait. It is only a hint and is safe to set while paused.

### Sweep latency

Even with the flag set, the game's designation sweep is slow and
variable: a FellTree job took ~2 s once, ~6 s once, and >30 s once.
The job-spawn bound (`DEFAULT_JOB_TIMEOUT`, 60 s) is generous for
this reason; the wait ends as soon as the job appears. Do not lower
it without re-measuring.

### Job removal: GatherPlants clears, FellTree never does

Unmarking clears the designation (verified), but what happens to the
job differs by type — verified repeatedly, 2026-11-25/26:

* **GatherPlants** jobs leave `world.jobs.list` within seconds of
  ticks after the designation is cleared (whether by
  `dfhack.job.removeJob` or by the game itself). The unmark path
  therefore waits (bounded by `job_timeout`) for them to vanish and
  reports any that remain.
* **FellTree** jobs (and Dig jobs) **never** leave the list: not via
  `dfhack.job.removeJob` (returns `true`, job stays listed through
  thousands of ticks), not via the game's own designation processing
  (`process_dig` set + ticks with the designation cleared), and not
  via the game's cleanup on its own. The designation being cleared
  means the game will not create a *new* job, but the stale job stays
  listed — and a dwarf can still take it if the tree is reachable.
  The unmark therefore succeeds on the verified designation and
  reports remaining FellTree jobs in `detail["remaining_jobs"]`
  instead of failing on them: failing would make chop-unmark
  unusable while hiding nothing. The live chop test asserts exactly
  this (designation cleared + stale job reported). Five stale FellTree
  jobs now sit at the test tree (110,98,32) — one per chop mark
  across the test runs. The tree is in an unreachable cavern pocket,
  so no dwarf ever takes them; they are inert fort state.
* **Do not manually delete a job struct.** `dfhack.job.removeJob`
  (the sanctioned path, mirroring DFHack's own `unmarkPlant`) is all
  this layer uses. Manually unlinking the list node and deleting the
  job struct removed one Dig job cleanly, then **crashed the game**
  when applied to three FellTree jobs (probable double-free of a
  struct `removeJob` had already deleted). The game was recovered
  from its 01:01 save; nothing else was lost. Manual job deletion is
  not used anywhere in this layer.

### Saplings are neither trees nor shrubs

A sapling has `is_shrub=false` but `tree_info=nil`. The first
version of the plant helpers classified by `is_shrub` alone, so a
sapling counted as a "tree": marking it set a dig designation on a
floor tile, which the game read as a **Dig** job. Classification is
now by structure (tree ⇔ `tree_info` set; shrub ⇔ `is_shrub` set)
in both `act_plants.lua` and `probe_plants.lua`, and saplings are
excluded from both actions (unit-tested with a fake sapling).

### Stale building occupancy

Deconstructing a building does not clear its tiles' `occupancy`
"building" flag (it reads `2` where free tiles read `0`), and
`dfhack.buildings.constructBuilding` (via
`Buildings::checkFreeTiles`) refuses such tiles. The first
`probe_site.lua` did not check occupancy, so it reported a
deconstructed workshop's site (85,85) as free while placement failed
with "cannot place at this position". The probe now reports
`occupancy.building != 0` as a problem (the field is numeric, not
boolean — test `~= 0`, not `== true`). The live test's deconstruction
helper clears the flag on the footprint after the building vanishes,
so sites stay reusable. The wagon's old site (95,95) had the same
stale flag and was cleared the same way.

### RFR unpause flake

`SetPauseState(False)` failed to stick twice in a row after a reload
(raising a verification failure), then worked again after a Space
keypress and has worked since (3/3 retries). Cause unknown, possibly
a transient post-load state. The action layer already handles it
honestly: `set_paused` raises a verification failure and the action
reports it rather than hanging. Do not add retries around it.

## How the daemon will call `act()` (phase 4)

* Call `act(client, name, **kwargs)` once per decision; read
  `ok`/`before`/`after`/`reason`/`detail` from the returned dict.
* On `error_kind == "transport"`, re-read state with `observe.collect`
  before deciding anything — the outcome is unknown.
* On `error_kind == "timeout"`, the mutation may have taken effect;
  re-read state (e.g. check whether the job/building appeared) before
  retrying.
* `detail["remaining_jobs"]` on a chop/gather unmark lists jobs the
  game left behind; the daemon must treat a stale FellTree job as
  permanent (see above) and must not re-mark a tree whose stale job
  would be taken by a dwarf if the tree is reachable.
* `detail["job_evidence"]` on a mark carries the job(s) the game
  spawned (fresh ids only — a pre-existing job at the tile does not
  count).
* The game is left paused by every action that unpauses (construction,
  job spawn/removal waits) — the pause state is restored even on
  failure. The daemon must not assume the game is running after an
  action.

## Files

* `src/dfagent_harness/actions.py` — `ActionResult`, `act()`, the
  seven actions, pause helpers, Lua plumbing.
* `src/dfagent_harness/lua/act_*.lua`, `probe_*.lua` — the helpers.
  `des_tile()` is duplicated in `act_plants.lua`/`probe_plants.lua`
  (keep in sync).
* `scripts/dfh-act.py` — CLI (`dig`, `chop`, `gather`,
  `order-create`, `order-remove`, `build`, `labor`).
* `tests/test_actions.py` — 26 unit tests (FakeClient/FakeGame
  simulating the game at the transport level, including deferred job
  removal on ticks and the sapling exclusion).
* `tests/test_actions_live.py` — 8 live tests on Athelunol, all
  cleaning up after themselves (the build test deconstructs the wagon
  first as one-time setup — all embark wood is trapped inside it —
  and deconstructs the workshop afterwards).
