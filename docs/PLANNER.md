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
