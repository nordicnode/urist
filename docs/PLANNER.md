# DF Agent Harness — Planner

The planner is the brain: an observe → events → decide → verified
action → verify loop (`src/dfagent_harness/planner.py`). One tick
every 30 s, max 2 actions, every decision journalled with its reason
(SQLite `journal.db`, table `decisions`).

## Priority order

| Prio | Domain | What it covers |
|---|---|---|
| 1 | threat | hostile ≤5 tiles of a citizen: hold the fort paused, do not send anyone out |
| 1 | needs | drink/food critical; a dwarf in distress |
| 2 | threat | hostile 6–15 tiles: watch (log only) |
| 2 | nobles | appoint a manager (required — manager orders are never worked without one) |
| 3 | needs | drink/food low (warn level): brew / cook to top up |
| 4 | production | carpenter, kitchen, beds (make or place), barrels |
| 5 | expansion | dig down for stone, food stockpile, farm plot |

Within a tick, decisions are sorted by (priority, domain) and
deduplicated on identical (action, kwargs). A goal in backoff
(180 s after a verification/timeout/precondition failure) is dropped
from the tick, and suppression rules ignore blocked goals — so a
failed still build does not also block the carpenter and the dig
that could unblock it.

## Decision rules per domain

### Needs: drink
- Drink ≤5 (critical) with a still: brew (needs brewable plants +
  barrels + no CustomReaction already queued), else gather plants
  (no brewable plants), else make barrels (0 barrels + carpenter),
  else build a carpenter (0 barrels, no carpenter).
- Drink ≤5 with no still: build a still first.
- Drink ≤20 (warn, or 1× citizens if larger) with a still + brewable
  plants + barrels + no brew queued: brew 3.
- Brewable plants = `PLANT:…:DRINK` entries in stocks `by_material`
  (trader-held goods are filtered out of stocks — caravan merchants
  hold most of the fort's apparent drink/food; see OBSERVE.md).

### Needs: food
- Food ≤5 (critical) with a kitchen and no PrepareMeal queued: cook.
- Food ≤5 with no kitchen: gather plants.
- Food ≤15 (warn, or 1× citizens if larger) with a kitchen and no
  meal queued: cook 2.

### Needs: distress
- A citizen past a distress line (starving / dehydrated / exhausted /
  wounded / stressed) logs a priority-1 `needs:distress` decision
  naming the dwarf and the kinds. There is no hospital yet, so the
  decision is a log + a pointer to drink/food (the usual cause).

### Threats
- Hostile distance is Chebyshev distance from the nearest hostile to
  the nearest citizen. ≤5 tiles: priority 1, pause the game, hold.
  6–15 tiles: priority 2, log and watch. >15 tiles: no decision.
- Responses are shelter-only. There is no military (see below), so
  the planner never sends anyone at a threat, armed or not.

### Nobles
- Manager (position 10) is appointed first, via the `n` nobles
  screen with xdotool (`ui.appoint_noble`) — a Lua write into
  `assignments_by_type.MANAGE_PRODUCTION` does NOT work (screen stays
  VACANT). The expedition leader (first adult citizen) is appointed.
  Bookkeeper (13) and broker (12) are not yet appointed by the
  planner (see "does not do").

### Production
- **Carpenter** (WORKSHOP_SITES[1]) when none exists and wood ≥1.
  **Kitchen** (WORKSHOP_SITES[2]) when none exists and stone ≥1.
  **Still** is built by the drink rule (WORKSHOP_SITES[0]).
- **Beds:** when a carpenter exists and beds < citizens: place a bed
  item (grid from BED_ORIGIN) if one is in stock, else queue
  `make_bed` (max 3) if wood ≥1 and no CustomReaction is queued.
- **Barrels:** queued at the carpenter when drink is critical and
  barrels are 0 (see drink rule).

### Expansion
- **Dig:** stone 0 → designate a down-stair at DIG_STAIRS
  (100,100,42) so the fort can reach stone (kitchen / still-from-
  stone / mason all need it).
- **Stockpile:** no stockpile → create a food stockpile
  (`p` menu, category `f`) at FOOD_STOCKPILE_BOX (96,90–100,94,42).
  Cursor rule: open `p` FIRST, then set the cursor while the menu
  is open — a Lua cursor write before `p` is discarded.
- **Farm plot:** no farm plot + seeds ≥5 + a still exists → build a
  3×3 plot at FARM_SITE (80,80,42). Placement only (see below).

Fixed sites (all z=42 unless noted): still (88,85), carpenter
(92,86), kitchen (next WORKSHOP_SITE), farm (80,80), beds from
(93,93), food stockpile (96,90–100,94), dig stairs (100,100),
dig room (97,97,41–103,103,41), gather box (70,87–92,98).

## The missing-section rule (the duplicate-carpenter fix)

A failed observe section means "unknown", never "zero" or "none".
`_summary` records section presence (`has_buildings`,
`has_stocks`, `has_units`, `has_jobs`, `has_items`) and every rule
that needs a section skips when it is absent. Before this fix the
planner read a failed buildings section as "no carpenter" and built
one per bad tick — three carpenters (#15/#17/#21) on Athelunol,
2026-11-26. The daemon retries next tick; it never acts on a
partial state.

## What the planner does NOT do (and why)

| Missing | Why / status |
|---|---|
| Military squads, training, stationing | Not implemented. Threat response is shelter-only (pause + hold). Creating a squad needs the `m` military screen via keystrokes; weapons/armor assignment needs a working equipment stock — both unprobed. Never send unarmed civilians at a threat. |
| Hospital zone (beds, water, soap) | Not implemented. Hospital zones are UI-only (`i` menu); no verified path yet. Wounds heal on their own in the current fort (5 wounded → 0 over the window). |
| Tavern / meeting area / temple | Not implemented. Zones are UI-only; stress is logged (distress) but not treated. |
| Farm-plot crop configuration | Placement only. Configuring crops needs the `q` menu on the plot; unprobed. A plot with no crop configured grows nothing. |
| Fishing / hunting | Not implemented. Gathering covers the same need (raw plants) with a verified path. |
| Bookkeeper / broker appointment | Not implemented. Manager first (it gates all manager orders); the other two use the same `n`-screen path and are a small follow-up. |
| Manager orders | The planner never creates them (only `run_task`/TASK_DEFS does). Manager-order-worked verification is still open. |
| Clothing | Not implemented. No loom/clothier chain yet; no dwarf has died of exposure. |
| Burrows / civilian alerts | Not implemented. `df.global.ui.burrows` exists but `dfhack.burrows` has no create; v1 threat response is pause + tier by proximity. |

## Verified live on Athelunol (2026-11-25/26)

- Still #14 built (wood, stage 3), manager Udil Sodelkosh
  appointed (position 10, assignment 6).
- Gather designated on GATHER_BOX: 5–6 shrubs marked, GatherPlants
  jobs spawned (ids 262–266, later 407–411, 419+, 442+).
- Carpenters #15 + #17 built (stage 3); farm plot #18 built
  (stage 3); food stockpile #20 created (category `f`).
- `queue_job` make_bed ×3 on carpenter #15 (job_ids [-1,-1,-1] —
  queued, completion not yet verified); bed placement via
  `build_furniture` not yet verified (needs a bed item).
- Brew end-to-end NOT verified: no brewable plants were ever in
  stock (drink plants empty), so the still never brewed.
- Liaison meeting dismissed by the daemon (topicmeeting → `a` →
  takerequests → `Esc` → topicmeeting → `a` → requestagreement →
  `Esc` → textviewer → `Return`).

## Composed tasks and recipes

A composed task (`task:<name>`, daemon `TASK_DEFS`) is one action
name the model calls; the harness runs the whole chain and verifies
the end effect. Single-action tasks (brew, cook, make_bed,
make_barrel, gather, farm) queue one job and wait for it to leave
the job list; a cancelled job is a failure, not a success.

A recipe is a task whose spec carries `steps`: an ordered list run
in sequence, each step verified, a failed step stopping the recipe
with a diagnosis naming the step, why it failed, and the fix
(R3-P0-4, ADVANCED_MECHANICS §0). A step is one of:

- `{"task": "<name>"}` — a sub-task (single-action or another
  recipe, max 3 levels deep; a self-referential recipe fails
  naming the nesting, never recurses forever).
- `{"action": "<name>", "kwargs": {...}}` — one raw harness action,
  verified by its own read-back.
- `{"verify": "<predicate>", ...}` — a state check with no side
  effect: `workshop_exists` (subtype), `building_exists` (type,
  optional subtype), `stock_at_least` (kind drink/food/wood/stone,
  units). An unknown predicate fails, never passes.

Step kwargs support `$param` placeholders resolved from the recipe
call's kwargs (a missing parameter fails the step naming it).
`count` is ignored for recipes (a recipe runs once). The dry-run
plan (`GET /v1/tasks/{name}/plan`) renders a recipe's real steps;
legacy tasks render the same four lines as before.

First recipe: `stock_drink` (make a barrel, then brew) — the live
proof vehicle for the framework. The well recipe is NOT defined
yet: `build_furniture` has no `Well` kind and there is no Well
construction route (ADVANCED_MECHANICS §1), so a well recipe would
fail at its build step with a named reason until that route lands.
The well follows when its route exists; the framework is proven
with `stock_drink`.

## What went wrong live (the honest record)

- **5 citizens died of dehydration** (Kogan Mûthkatost tick 224421,
  Feb Rilbetfath tick 226373, Datan Erushninur tick 224971, Nil
  Idòeton tick ~230445; Deler Stûeegilstinthäd gone, cause
  unrecorded) while drink sat at 0–2u. The drink-critical rules
  existed, but the daemon was stalled (planner stall #1, liaison
  freeze) or crashing through the critical window, and the
  gather → haul → brew chain never produced drink in time. The
  planner's design would have gathered earlier if it had run
  continuously from the baseline — it did not.
- **Three carpenters** from deciding on partial states (fixed by
  the missing-section rule above).
- **Nine game crashes** in the 2026-11-26 window (double-free
  aborts, texture-reset aborts, load aborts), plus a cell reboot
  that wiped apt packages and all processes. The acceptance window
  was never completed crash-free. See ACCEPTANCE.md.

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

### Snapshot: the suggestion, once per tick

The planner's product in the snapshot is one suggested action
per tick, as a default, not an instruction, in this shape:

```
Suggestion: brew 2 at the still (drink 97, floor 70, 3 empty barrels).
```

The suggestion names the action, its parameters, and the
one-line why in game terms. The priority order (§Priority order)
and the decision rules per domain (§Decision rules per domain)
are harness policy; the snapshot carries the outcome, never the
rulebook. The model is told it may reject the suggestion. The
missing-section rule (the duplicate-carpenter fix) is a planner
rule: when a section the suggestion depends on is missing, the
planner says so instead of suggesting from stale state.

**Token cost.** At 7 dwarves, the suggestion as written above is
70 characters: about 23 tokens by the accountant's
3-chars-per-token rate, 17 on the wire. At 50 dwarves the
cost is about the same, about 200 characters: about 66 tokens
by the accountant, 50 on the wire. The suggestion is one action
with its parameters and one why, at any population; it does not
grow with the number of dwarves, the number of goals, or the
number of domains. If a future change makes it grow with any
of those, the change is refused until the suggestion is capped
again.

### Query route: the planner has no route; the catalog does

The planner is not queried. The model asks GET /v1/catalog for
what it can do, GET /v1/snapshot for the state, and the
per-system detail routes when it needs to choose. The planner's
priorities are not a route and are never dumped into the prompt.
When the model rejects the suggestion and acts otherwise, the
planner records the deviation and moves on; it does not argue.

### Briefing: none from this layer

The planner does not brief. Briefings come from briefings.py,
fired by events. The planner's stall handling sharpens the
prompt at 3 idle ticks and runs the snapshot's suggestion as a
fallback at 6 idle ticks; both are planner behavior, not
briefings. The model is never briefed about the planner's own
state.

### Opportunities: the planner feeds them, it is not them

The opportunities section carries at most 3 entries per tick,
each facts plus a query route, from the system docs. The
planner's per-goal backoff applies to build and production
goals, not to labor (§3.3 of LABOR.md), and the planner has no
labor domain. The planner decides which facts are opportunities
by the systems' rules; it never invents an opportunity entry of
its own.

### What the system deliberately does NOT push, and why

- **The priority order.** The priority order (§Priority order)
  is harness policy. The snapshot carries the suggestion it
  produces, never the ordering that produced it. The model
  decides from the fort's state, not from the planner's
  ranking.
- **The decision rules.** The rules per domain are harness
  policy, versioned in this doc. The snapshot carries the
  outcome. A rulebook dump would be a script, and the
  presentation gives the model what it needs to decide, not a
  script to follow (HARNESS_ROLE.md).
- **The goals list.** The planner's goals are not pushed. The
  snapshot carries goals only as the Goals section (assembler
  _goals), capped like every other section. The full goal
  hierarchy is harness state, not model input.
- **Stall handling as a threat.** The sharpened prompt at 3
  idle ticks and the fallback at 6 are behavior, not warnings.
  The snapshot never says "you are stalling". The model is
  told what the fort needs, not how it is performing as a
  planner.
