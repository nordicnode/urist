# Advanced-mechanics library — design and build plan

The harness must provide a way for the model to do every advanced
DF mechanic, because the mechanics cannot be explained to the model
in the prompt. The harness holds the knowledge (a composed
task/recipe); the model names the goal, the harness walks it through
the steps with material checks at each one. Each mechanic is a
composed task with prerequisites, ordered steps, per-step
verification, failure diagnosis with cause + fix, and the same
have/need material checks as the general material-awareness work.
Steps come from the local DF wiki index, verified live against the
game, never guessed.

Synthesized 2026-11-27 from three file-only research passes (wiki
research, DFHack/code anchors, burrows/squads/floods). Every fact
below traces to one of those passes; "unknown" means the research
could not establish it from files and it needs a live probe.

## 0. The framework first (foundation for everything)

`Daemon.run_task` today is single-action only: one `queue_job` (or
one designation for `gather`) + wait-for-disappearance + a
cancellation check. There are no steps, no per-step prerequisites
beyond the single `need` workshop, and no step-by-step
verification. `TASK_DEFS` has only 5 tasks (brew, cook, make_bed,
make_barrel, gather) — basic production only. `wait_job` is recorded
but unused by verification. `_task_plan` fabricates its 4 steps from
the single spec.

Generalize before building any mechanic:
- A task is an ordered step list. Each step names a harness action
  (or a sub-task), its prerequisites (site, materials, labor), and
  its end-effect verification (a state re-read that proves the step
  happened, not just that the action returned ok).
- A step that fails stops the task and returns the diagnosis: what
  failed, why (the cause in game terms), and the exact fix (the
  corrective action + what it needs). Same rule as the action
  fail-fast work: every failure names the fix.
- Materials for each step go through the have/need machinery
  (exact counts, fail fast naming the gathering step).
- `TASK_DEFS` gains a `steps` form; the single-action form stays
  as a one-step task. `_task_plan` renders the real steps.
- Verify the framework live with the first mechanic (the well),
  not with a mock: a run where the model requests the well (or the
  harness suggests it) and the well gets built through the composed
  task, each step verified.

## 1. Wells (first mechanic — water access)

Materials (wiki *Well* infobox; DFHack `building_inputs[Well]`
confirms): **1 block + 1 bucket (lye/milk-free) + 1 chain + 1
mechanism**. The wiki says "1 chain **or** 1 rope" but DFHack's
filter table lists only CHAIN — verify live before promising rope
support. Labor depends on block material (stone: Masonry; wood:
Carpentry; metal: Blacksmithing/Weaponsmithing/Armoring/Metalcrafting).

Rules (wiki *Well*, *Well guide*):
- Built on an open-space or downward-slope tile (usually channeled),
  with adjacent floor tiles. No water needs to be underneath to
  build it — only for it to be active.
- Clear vertical pathway straight down to the water source is
  mandatory. Wells cannot function through a stairwell. Hatches,
  floor bars and floor grates block function if between well and
  water (they allow function again if opened with a lever).
- Water source: any water **≥3/7 deep**, at least 1 z-level
  somewhere directly below the opening; any distance below (deeper
  = slower bucket travel). If 7/7 water is somewhere directly
  below, the top tile's depth doesn't matter.
- Brooks: channel off the surface first. Aquifer: channel a 1×1
  square above it; "it will automatically fill and never flood."
- Using the well 10 times removes 1/7 water from the tile below.
  A well above-ground in a freezing biome loses its water tile to
  freezing and is dismantled — keep it ≥1 z-level above outdoor
  water or put the source underground.
- Well water is not cleaned or desalinated. Drinking stagnant water
  gives a bad thought and can infect wounds. Badly wounded dwarves
  drink only water while recuperating and won't go to the well
  themselves.
- A well is a hole in the floor: dwarves can fall through it;
  swimming enemies can path in (grates block swimmers but not
  building destroyers from below).

Construction route: `dfhack.buildings.constructBuilding` with
`type=df.building_type.Well`, `subtype=-1` (no well subtype enum;
the `act_furniture.lua` pattern). Named material args (`bucket`,
`chain`, `mechanism`) can pin specific items. No `build_well`
action exists; `PLACEMENT_KINDS` has no "well" entry yet.

Verification: working well reads "active"; obstructed or
insufficient water reads "dry". No well-specific state is read by
the harness today (`building_wellst` fields are not defined
anywhere in the repo — no df-structures XML). Verify "well works"
indirectly: check the tile(s) below for water (slice/column reads)
and/or observe dwarves drinking from it.

Ordered steps (from scratch): secure a water source ≥3/7 deep (or
dig a reservoir and fill it) → channel a 1×1 open-space tile
directly above it, keeping a clear vertical shaft → make/acquire 1
block, 1 bucket, 1 chain/rope, 1 mechanism → build (`b-m-L`) →
verify "active" (if "dry", check depth and obstructions).

## 2. Screw pumps (second — moves water up 1 z)

Materials: **1 block + 1 enormous corkscrew + 1 pipe section**.
Any material for water; each component must be magma-safe for
magma. Labor: carpentry, metalsmithing, or masonry depending on
block material. Job requirement: Pump operator (manual operation).

Rules (wiki *Screw pump*, *Power*, *Machine component*):
- Pump is 2 tiles × 1 tile but needs 4 tiles in a row: fluid
  source, 2 pump tiles, fluid output. The tile clicked becomes the
  output side; orientation is chosen at construction and cannot be
  changed afterwards (deconstruct and rebuild).
- Fluid is taken from one level below the tile next to the input
  side and moved to the tile next to the output side — it lifts
  fluid **up one z-level, to the pump's own level**. It never pushes
  fluid above its own level; higher lifts need a pump stack.
- Intake liquid must be **≥2/7 deep**. The space above the fluid
  source cannot be a floor, stairway or wall; pumps can pull through
  a grate, floor bars, or constructed fortification below. Stairs in
  the intake tile block it entirely.
- The input tile is where fluid enters and where the operator
  stands; it does not block flow or movement. The output tile is
  impassable to both fluid and movement.
- Pumping salt/stagnant water produces clean water.
- Needs **10 power**. Windmill (40/20/0 by wind level; 4 logs +
  Carpentry; center tile must be "outside") or water wheel (100,
  net +90; 3 logs + Carpentry; flowing water ≥4/7 deep under at
  least one of its 3 tiles). Gear assemblies cost 5 power each,
  axles 1 per tile. A pump accepts/transfers power through either
  tile; adjacent pumps transfer power automatically. Manually
  operated pumps do NOT generate power. Pumps keep running 49 ticks
  after losing power.
- Exact numeric flow rate: the wiki does not give one — do not
  assert a number.

## 3. Reservoirs

A cistern: a room mined out and sealed (wall, floodgate, or bridge),
with water routed into it. Most are made refillable via levers
attached to the floodgate linking source to container (pressure
plates can automate it).

Rules (wiki *Reservoir*, *Well guide*):
- Properly constructed, water in a reservoir never freezes or
  evaporates and always stays fresh. A secured 20×25×1 underground
  reservoir "can last for many years without needing to be
  refilled" — but a reservoir for a well should be deeper, to
  prevent hauled water being "laced with mud".
- Desalinated water touching salt water becomes salty; fresh water
  touching stagnant water becomes stagnant — then all water must be
  pumped out for an attached well to be useful again. Stagnant
  water must be cleaned and salt water desalinated, both by a screw
  pump.
- If there is a path from the reservoir into the fortress (e.g.
  through a channeled hole or a well), it should be sealable —
  amphibious foes can path through the cistern and up the well. A
  fortification + isolation works against building destroyers;
  fortifications let 7/7 water through but block all else.
- Uses: internal well supply (wounded dwarves need fresh water and
  will die of dehydration without it, often during sieges); drowning
  chambers; mist generators; storing magma from a pump stack.

Ordered steps: mine out a sealed room → connect it to a water
supply via a channel with a **floodgate** (lever-linked) in the
connection → seal all other openings → open the floodgate to flood
the room; close it when full → build the well above it (see §1),
with a sealable barrier against swimmers.

## 4. Traps (next after wells — sites already exist)

Placement already computes trap sites (1×1, weapon/cage/stonefall)
but no creation action exists. General rule (wiki *Trap*):
- Built on a vacant floor (natural or constructed), indoors or
  outdoors. All need **one mechanism + a dwarf with mechanic labor**
  (higher skill = faster build). Only mechanics reload/clean them.
- Mechanism quality determines attack skill for weapon and
  stone-fall traps (Basic = Dabbling 0 … Masterwork = Legendary 15);
  it has **no effect on cage traps**.
- Conscious dwarves, guests, allies, caravans and domestic animals
  do NOT set off self-triggered traps; any unconscious creature
  (including your own dwarves) will trigger them. Thieves, flying
  creatures and some invaders may avoid/recognize them. Traps block
  caravan wagons but not traders with pack animals.

Per type:
- Stone-fall (`b-t-t`): **1 mechanism + 1 ordinary stone**
  (respects economic stone restrictions; cannot be loaded with
  clay). Usually won't kill outright but can break a bone; stone
  weight affects damage. **Re-arming required after every use** — a
  mechanic automatically reloads with a new stone. Does not alert
  to ambushes; the reload job can send mechanics into danger.
- Weapon (`b-t-o`): **1 mechanism + 1–10 weapons** (any weapon,
  including training weapons and trap-only weapons — menacing spike,
  spiked ball, enormous corkscrew, large serrated disc, giant axe
  blade). All weapons attack at once. Ranged weapons: one bolt per
  crossbow per trigger; when bolts run out the trap signals reload
  and stops firing. **No reset needed — resets automatically after
  an unknown period of time** (the wiki's own words — do not assert
  a number). **50% chance a kill jams the trap** (victim stuck);
  a mechanic automatically tries to clean it. Only jams on a direct
  kill, not a bleed-out.
- Cage (`b-t-g`): **1 mechanism + 1 cage** (any material; glass
  terrarium is as strong as a steel cage). Victim is captured
  unharmed. **Alerts to ambushes** when triggered by hidden
  invaders. **Re-arming: yes** — reset by hauling an empty cage to
  it (automatic by a mechanic, only when the Trap Rearming standing
  order permits). Dwarves only load empty cages. Captured creatures
  survive indefinitely in a cage; if left alone ~a year or longer
  the prisoner escapes. Titans, forgotten beasts and certain
  creatures are immune to traps entirely — except a webbed cage trap.
- Upright spear/spike traps (`b-t-u`, 1–10 spears/spikes, no
  mechanism unless linked) are a fourth type: they do not
  self-trigger and do not discriminate friend/foe.

Construction route: `dfhack.buildings.constructBuilding` with
`type=df.building_type.Trap`, `subtype=<df.trap_type value>`
(`StoneFallTrap`, `WeaponTrap`, `CageTrap`, `Lever`,
`PressurePlate`, `TrackStop` — from DFHack's own
`buildings.lua:298-338` `trap_inputs` table). Filters default via
`buildings.getFiltersByType`, so passing only type+subtype suffices.
**Discrepancy to resolve live:** the DFHack table lists mechanism
only for cage traps (no cage in the filter list) while the wiki
says a cage must be provided — verify live before trusting either.
The harness's `act_build.lua` hardcodes the subtype lookup to
`df.workshop_type[...]` — a trap subtype would error as "unknown
workshop subtype". It needs a type-aware lookup (`df.trap_type` for
`Trap`). The `act_furniture.lua` pattern (non-workshop types,
`subtype=-1`) is the model; traps use a real subtype instead.
Trap state (loaded/unloaded, contents, jammed) is not read by the
harness today (`building_trapst` fields not collected) — add a
read-back or verify via the `t` query state.

## 5. Strange moods (fey moods), artifacts, engraving

### Detection (anchors already exist)
- Per citizen, the harness already collects `mood` (raw int) and
  `mood_name` (`units.lua:112-125`, `units_lite.lua`, `probe_unit.lua`).
  `docs/OBSERVE.md:118` documents them (`-1`/`"none"` when no mood).
- Current job is also collected (`u.job.current_job` → type/id/pos).
  Exact job types (fixture `runtime-enums-0.47.05-r8.json`):
  `SeekArtifact`, `StrangeMoodCrafter`, `StrangeMoodJeweller`,
  `StrangeMoodForge`, `StrangeMoodMagmaForge`, `StrangeMoodBrooding`,
  `StrangeMoodFell`, `StrangeMoodCarpenter`, `StrangeMoodMason`,
  `StrangeMoodBowyer`, `StrangeMoodTanner`, `StrangeMoodWeaver`,
  `StrangeMoodGlassmaker`, `StrangeMoodMechanics`.
- Consumers already exist: `events.py:295-300` (mood ≠ "none" →
  info-level distress note), `attention.py:178-180` ("in a <mood>
  mood" in the unit state line), `briefings.py:81-93`
  (`strange_mood` briefing). What is missing: detection of a mood
  STARTING (attention event), what the dwarf claimed, and the
  actions to satisfy it.

### Rules (wiki *Strange mood*, *Legendary artifact*)
- Requires **≥20 dwarves** in the fortress; at most one mood active
  at a time; artifact caps apply (max artifacts = lower of
  items-created ÷ 100, or revealed subterranean tiles ÷ 2304).
  **The fort has 7 citizens — live verification of a real mood
  needs a synthetic test (DFHack `strangemood` can force one:
  `-force -unit -type <type> -skill <skill>`) or a bigger fort.**
  Do not claim a live mood verification that did not happen.
- Frequency: internal counter starts at 1000, decremented every 100
  frames, reaching zero in ~3 months; then a 1-in-500 chance per
  check (~2.4%/day, ~52%/month, no guarantee).
- Eligibility: `[STRANGE_MOODS]` token (dwarves by default);
  permanent resident only; decided by actual profession. A dwarf who
  already made an artifact is never eligible again (at most one mood
  per dwarf per lifetime). On-duty military (other than Recruit)
  cannot enter moods; children can (babies cannot).
- Stages: announcement (does not pause the game) → claim a workshop
  matching their highest "moodable" skill (they kick out any dwarf
  using it; if no appropriate workshop exists/is accessible they
  don't claim one — **a moody dwarf cannot build a workshop
  themselves**; another dwarf must build it) → gather materials in
  order (you must provide the next one before they continue) →
  construction (the game pauses and centers; usually +20,000 XP in
  the skill → Legendary, except possessed).
- Demands: first demand is based on the mood skill (stoneworkers →
  boulders, woodworkers → logs, leatherworkers/tanners → leather,
  weavers/clothiers → cloth, metalworkers → metal bars, gem
  cutters/setters → rough gems, glassmakers → raw glass, bone
  carvers → bones). Then 1–3 base items + up to 7 decoration items
  (wood logs, metal bars, small gems, rock blocks, rough gems,
  boulders, bones, leather, cloth, raw glass). Fey states demands
  plainly; secretive sketches pictures (examine the claimed workshop
  while the dwarf waits inside); possessed mutters cryptically.
  Preferences matter (metalworkers demand adamantine/divine metals
  if available, else a preferred metal if ever smelted).
- Failure: if the dwarf cannot get the workshop/materials, they go
  insane after **exactly 50,000 ticks (~41.66 days)** of idling
  without the required workshop or item. The countdown resets after
  every item brought and doesn't run while fetching, working, or
  traveling. Insanity: stark raving mad, melancholy, catatonic
  (harmless) or berserk (attacks everybody). Any insane dwarf "will
  soon die, one way or another." Mood also fails immediately if the
  claimed magma forge loses power, the claimed workshop is
  deconstructed/destroyed/toppled, or a permanent building material
  of the claimed workshop is forbidden. Moody dwarves don't eat,
  drink, or sleep.
- Types: Fey (plain demands), Secretive (sketches), Possessed
  (cryptic, **no XP gain**), Fell (claims a butcher's/tanner's shop,
  murders the nearest dwarf, bone/leather object; only highly
  stressed dwarves), Macabre (like fell but no murder; needs bones,
  skulls, or vermin remains; only highly stressed dwarves).
- The artifact: unique, named, unsurpassable quality; each dwarf at
  most one in their life. Artifact weapons/armor get a **×3 quality
  bonus** to accuracy/deflection (vs ×2 masterwork); blades are not
  sharper and do no more damage; artifact weapons never dull.
  Artifact clothing is immune to wear. Artifact doors/hatches are
  **indestructible, instantly-lockable gates, immune to building
  destroyers**. Artifact furniture greatly raises room value.
  Creator gets a very strong happy thought plus partial immunity to
  insanity from prolonged stress.

### What is missing (build list)
- Claimed workshop / demanded materials: nothing in the repo reads
  them. `units.lua`/`probe_unit.lua` collect only job type/id/pos —
  no `job_items`, no worker link. The struct field exists in
  principle (`act_job.lua:60` proves `df.job` has `job_items`; each
  `df.job_item` carries `item_type`, `item_subtype`, `mat_type`,
  `mat_index`, `quantity`, `flags1/2/3`). A new probe must read the
  moody dwarf's current `StrangeMood*`/`SeekArtifact` job's
  `job_items` to get the demanded materials in order. The claimed
  workshop is findable by matching the mood job's `pos` to a
  building's centre, or via `buildings.lua` (`jobs` count per
  building — count only, not job ids).
- `showmood` is the DFHack-native answer but is **not Lua** (compiled
  plugin; "Shows all items needed for the active strange mood").
  Callable only via the guarded `/v1/actions/command` route, not a
  typed endpoint. Use it as a cross-check, not the route.
- Mood announcements reach the harness only by substring on report
  text ("taken by a fey mood") — `reports.lua` collects no
  announcement-type field.
- Not found anywhere: `df.mood_type` enum member names/values; any
  `unit.mood_skill` field; any `unit.flags1/flags2` mood bit.

### Engraving
- Only natural stone can be smoothed (soil cannot; constructions are
  already smooth for most purposes). Designate smooth with `v-m`,
  engrave with `v-g`. Requires Stonecutting labor to smooth, Engraver
  skill to engrave (Stone engraving labor). Natural stone must be
  smoothed first; constructions do not need smoothing first.
- Smoothing increases zone/room value (smooth cave floor 4×, smooth
  cave wall 5×; constructed floor 7×, constructed wall 9×).
  Engraving adds 10 × material value × quality modifier (quality
  levels — 1×, -Well-crafted- 2×, +Finely-crafted+ 3×, *Superior*
  4×, ≡Exceptional≡ 5×, ☼Masterful☼ 12×). Wall engravings are
  directional (only the room containing the floor tile the engraver
  stood on gets the value). A wall can only be engraved once.
- **Happiness: "It is unknown if dwarves currently look at
  engravings" (marked [Verify] on the wiki) — do not claim
  engravings make dwarves happy.** The verified effect is room and
  fortress value. Removing a masterwork engraving causes an unhappy
  thought in the artist. Engraving gives only 10 XP per job — the
  lowest of any skill.
- Job types exist: `DetailWall`, `DetailFloor`, `EngraveSlab`
  (fixture). Designation struct: `designations.lua` reads
  `blk.designation[x][y]` (`d.dig` decoded, `d.smooth` counted only)
  — the enum name/values for `designation.smooth` are **unknown
  from files** (not in any repo file, DFHack doc, or the fixture);
  needs df-structures or a live probe. No `designate_smooth` /
  `designate_engrave` action exists. A new engrave action follows
  the `act_dig.lua` pattern (new Lua file + `actions.py` wrapper +
  dispatch entry), writing `d.smooth` per tile **plus the block flag**
  (`b.flags.designated = true` — the digging gap proved the game's
  sweep only processes flagged blocks), then verifying via a
  re-read and/or waiting for `DetailWall`/`DetailFloor` jobs.
  `dfhack.job.checkDesignationsNow()` exists to force the check.
  No `dfhack.designations.*` Lua module exists.

## 6. Floods — detection and response (general hazard pattern)

Prevention exists; detection and response do not. `digging.py`
warns "aquifer rock at z{z} — digging here floods the fort" and
"water at z{z} — digging here floods the fort"; `column.py` warns
the same. Every "flood" hit in the code is flood-FILL (the region
algorithm), not a fort flooding. No flood event kind, no flood
attention item.

- Detection: the observation already reads water per tile
  (`flow_size > 0`). A flood is water in fort areas where it
  shouldn't be. Diff water tiles in fort areas between snapshots
  and fire a flood event when water appears where it wasn't, with
  the location, depth, and what is at risk (dwarves, workshops,
  stockpiles) in plain words. It must distinguish a flood from
  normal water (a well, a brook, a reservoir) — only water inside
  the fort's lived/worked areas counts.
- Reading (already exists): `TileDesignation.flow_size` bits 0–2
  (0–7 depth), `liquid_type` bit 21 (false = water, true = magma),
  via `dfhack.maps.getTileBlock`. `survey.lua:60–110` does a full-map
  scan per block (verified live 2026-11-26: pool at z=174, (162,122),
  flow 7; aquifer water shows no `flow_size` until exposed). Slow
  (~10–15 s), cached per kind, never per tick. `slice.lua:106–180`
  and `column.lua:54–55` read per tile/block. Nothing reads water
  in fort areas per tick, and there is no "water where it shouldn't
  be" detector.
- Response (composed flood-response task): identify the source, wall
  it off or close the floodgate, drain it, rescue drowning dwarves —
  with per-step verification and failure diagnosis, same pattern as
  §0.
- Drain route: `Channel` a floor-tile path from the flooded area
  toward a lower outlet / map edge / cistern (`act_dig.lua` modes;
  `dig_to_completion` wraps it). **Tension:** `digging.py:58`
  `HAZARD_CLASSES` refuses digs into/through water ("digging here
  floods the fort"). A deliberate drain channel toward water is
  exactly what the current check refuses, so a flood-drain action
  needs its own check (channel away from the fort, toward a safe
  outlet), not `check_dig_box` as-is.
- Flood control buildings: `Floodgate` (gate_flags: closed/closing/
  opening/collapsing/has_support; timer), `Hatch` (door_flags,
  close_timer), `GrateWall`/`GrateFloor`/`BarsVertical`/`BarsFloor`
  (same gate pattern). The harness already builds Floodgate, Hatch,
  Grate via `act_furniture.lua` (1×1, Construct job). No Trap/Lever
  in the furniture map.
- Lever linking: a lever is **not** a `building_type` — it is
  `building_trapst` with `trap_type == TrapType.Lever` (0);
  `BuildingTrapst` carries `linked_mechanisms` (vector of mechanism
  items). A link is a mechanism item in the lever's
  `contained_items` carrying general refs `BUILDING_TRIGGER`
  (lever) and `BUILDING_TRIGGERTARGET` (target). **No DFHack "link
  lever" API was found.** Precedents, both partial:
  `advfort.lua:1032–1044` `fake_linking` (self-described "fake",
  with a TODO for real linking) and `lever.rb` (legit pull: create
  a `PullLever` job on the lever; cheat pull: iterate
  `linked_mechanisms` and call `setTriggerState`). Lever
  construction has its material filter defined
  (`trap_inputs[Lever]` = 1 mechanism) but the harness has no
  Trap/Lever build action.
- General hazard pattern: floods are one case; the same detection +
  response shape covers other environmental hazards (magma,
  cave-ins, fire) as they are added — not a one-off flood hack.
  (Do NOT use `drain-aquifer.lua` — it strips aquifer flags
  map-wide, irreversible. `liquids.paint` is unprobed and its
  argument semantics are undocumented.)

## 7. Invasions and burrows

### Invasions — detection exists, response does not
- `events.py` has an INVASION handler (fires a critical event),
  `briefings.py` has an invasion briefing, the planner has threat
  tiers (near 15 tiles, critical 5 tiles; at critical it holds the
  game paused until the threat moves away). But the briefing tells
  the model to "muster the military" and there IS no military —
  `planner.py:337` says "no military exists; shelter by pausing
  only if it...". The only response is pause and wait.
- **Briefing drift (flagged by research):** `briefings.py`
  invasion/hostile/new_arrival options promise "muster the
  military", "seal the entrance (raise the drawbridge / lock the
  door)", "let the military intercept them away from civilians" —
  none of those actions exist. Fix the briefings when the military
  lands (or now, to stop promising what the harness cannot do).

### Military / squads — no creation API
- Two lists: `df.global.world.squads.all` (master) and
  `df.global.ui.squads.list` (UI). `df.squad` fields are known
  (id, name, alias, positions, orders, schedule, cur_alert_idx,
  rooms, rack_combat/rack_training, uniform_priority, activity,
  ammunition, train_weapon_free/inuse, ammo_items/units,
  carry_food/water, entity_id, leader_position/assignment).
  Unit side: `df.unit.military.squad_id`/`squad_position`.
- Grep of all DFHack scripts/lua/docs: **no `df.squad:new()`, no
  create-squad function, no squad tool, no `next_squad_id` counter**
  (only `next_uniform_id` exists, on the entity). No squads/military
  module in the Lua API at all. Orders exist as structs
  (`SquadOrderMovest`, `SquadOrderDefendBurrowsst`,
  `SquadOrderPatrolRoutest`, `SquadOrderTrainst`,
  `SquadOrderKillHfst`, `SquadOrderKillListst`, etc.) and can in
  principle be constructed — but **no precedent exists for inserting
  an order into `squad.orders` / `position.orders` and having the
  game execute it**. Member assignment would presumably be
  `df.squad_position:new()`, `occupant = unit.hist_figure_id`,
  insert into `squad.positions`, set
  `unit.military.squad_id`/`squad_position` — inferred, not found;
  no precedent. All unproven; needs live testing from scratch.
- Equipping/uniforms: `SquadPosition.uniform` (7 categories: Body,
  Head, Pants, Gloves, Shoes, Shield, Weapon), `SquadUniformSpec`
  (item, item_filter, color, assigned, indiv_choice),
  `SquadAmmoSpec`. No script writes a uniform spec or assigns an
  item to a squad member (only `clone-uniform.lua` clones
  entity-level uniform templates).
- Barracks: **there is no barracks zone type** (`CivzoneType` has no
  barracks). Barracks assignment is per-furniture, via the room
  system: beds, armor stands and weapon racks each have `squads`
  (vector of `BuildingSquadUse` {squad_id, mode}) +
  `specific_squad`/`specific_position` + `users`; the squad side
  mirrors it (`squad.rooms` = {building_id, mode}). `SquadUseFlags`
  bits: sleep 0, train 1, indiv_eq 2, squad_eq 3. No write precedent.

### Burrows — no DFHack create; direct struct construction is the route
- `df.burrow` (sizeof 128): id, name, tile (uint8 — semantics not
  documented anywhere; do not guess), fg_color, bg_color,
  block_x/block_y/block_z (parallel vectors of map-block coords),
  units (vector of unit ids), limit_workshops.
- Container: `df.global.ui.burrows` (`Ui_TBurrows`): list
  (vector of `Burrow*`), next_id, sel_index/sel_id, list_units,
  sel_units, unit_cursor_pos, rect_start, brush/symbol pickers.
- **Critical:** tile membership is NOT stored in `df.burrow`. It
  lives per map block: `MapBlock.block_burrows` is a linked list of
  `BlockBurrow` (id, tile_bitmask 16×16, link). The burrow's own
  block_x/y/z vectors list the blocks it touches. Any creation route
  must maintain both sides (or use `dfhack.burrows.setAssignedTile`,
  which does).
- What `dfhack.burrows` offers (blocker confirmed): `findByName`,
  `clearUnits`, `isAssignedUnit`, `setAssignedUnit`,
  `clearTiles`, `listBlocks`, `isAssignedTile`, `setAssignedTile`,
  `isAssignedBlockTile`, `setAssignedBlockTile`; plugin:
  `renameBurrow`, `copyUnits`, `copyTiles`, `setTilesByKeyword`
  (keywords: ABOVE_GROUND SUBTERRANEAN INSIDE OUTSIDE LIGHT DARK
  HIDDEN REVEALED). **No create command, no create function
  anywhere.** The blocker in `docs/PLANNER.md:117` is accurate.
- Direct-construction route (plausible, unproven — precedented for
  other compounds: `df.construction:new()` + `utils.insert_sorted`
  in `build-now.lua`; `df.manager_order:new()` + insert in
  `workorder.lua`; `clone-uniform.lua` is the closest template:
  `uniform:new()`, id from `entity.next_uniform_id`, insert):
  1. `local b = df.burrow:new()`
  2. `b.id = df.global.ui.burrows.next_id;` increment next_id
  3. `b.name = 'Shelter'`; fg_color / bg_color / limit_workshops —
     **values unknown from files**; copy them from a burrow created
     by hand in the UI first (do not guess defaults)
  4. `df.global.ui.burrows.list:insert('#', b)`
  5. Tiles: do NOT hand-build `BlockBurrow` entries first — test
     whether `dfhack.burrows.setAssignedTile(b, {x,y,z}, true)` per
     tile works on the hand-inserted burrow (it should maintain
     block_x/y/z + the block's tile_bitmask). If it errors or
     silently drops tiles, fall back to constructing
     `BlockBurrow` entries in each block's `block_burrows` list —
     that path has **no precedent** and is the riskiest step.
  6. Units: `dfhack.burrows.setAssignedUnit(b, unit, true)` per
     citizen (should populate `unit.burrows`).
  7. Verify live: burrow appears in the `w` burrow UI list, tiles
     highlight, `unit.burrows` is populated, civilians actually
     restrict to it under an alert, and it survives save/load. Read
     the `tile` uint8 field's meaning off a UI-created burrow during
     that test.
- Civilian alerts: `df.global.ui.alerts` (`Ui_TAlerts`): list of
  entries {id, name, burrows (vector of burrow ids)},
  next_id, `civ_alert_idx` (the active alert, -1 = none). Each squad
  also carries `cur_alert_idx`. **Missing:** no DFHack API creates
  an alert; no script creates one; the alert entry type is an
  anonymous compound (`Ui_TAlerts_TList`) with no discoverable Lua
  constructor name in the files. Live test must determine whether
  the entry can be `new()`'d, or whether the only viable path is
  cloning an existing entry / using whatever default alert entry the
  game creates. Also unknown: whether a fresh fort already has a
  default alert entry (live read needed).

## Build order

1. **Framework generalization (§0)** — the foundation. Verify with
   the well.
2. **Wells (§1)** — most needed (water access). Then screw pumps
   (§2) and reservoirs (§3).
3. **Traps (§4)** — sites already exist; the creation route is the
   missing piece. Generalize `act_build.lua`'s subtype lookup first.
4. **Floods (§6)** — detection (water diff in fort areas) +
   composed flood-response task + the general hazard pattern.
5. **Fey moods / engraving / artifacts (§5)** — mood detection +
   claimed-materials probe + smooth/engrave action. Live
   verification of a real mood needs ≥20 dwarves (synthetic force
   via `strangemood` or a bigger fort).
6. **Invasions / burrows / military (§7)** — the hardest (no creation
   APIs anywhere; direct struct construction, unproven). Squad
   creation, training, equipping, invasion-response task; burrow
   creation + civilian-alert assignment; fix the briefing drift.

## Standing rules for this library

- Every mechanic is verified live against the real game before it is
  committed and pushed — a mock or unit test alone is not
  verification. If a mechanic cannot be verified live (e.g. DF is
  down), log it as unverified and re-attempt. Nothing unverified
  gets pushed.
- Steps come from the local DF wiki index, verified live, never
  guessed. Where the wiki and DFHack's tables disagree (well rope,
  cage-trap cage), verify live and record which one was right.
- Where a value is unknown from files (burrow colors, `tile` field,
  `designation.smooth` enum, alert entry constructor), read it off
  a live game or a UI-created instance first — never guess a
  default into the code.
- If some screen/route genuinely has NO programmatic route after a
  real investigation, report that specific thing with the evidence —
  that is a finding, not a punt.
- The model triggers a mechanic by naming the goal ("I need a well")
  or by the harness suggesting it when the fort needs it; the
  harness does the rest. The model never guesses coordinates or
  steps — the placement system and the composed task supply them.

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

This doc is the advanced-mechanics library: wells, screw pumps,
reservoirs, traps, strange moods, artifacts, engraving, floods,
invasions, and burrows, each as a composed task or recipe the
model names and the harness walks through step by step, with
material checks at each step. The presentation of each mechanic
to the model lives in its own design doc where one exists
(MILITARY.md for invasions and burrows, MECHANISMS_AND_SIEGE.md
for traps, FARMING_PLAN.md for irrigation). This section states
the shared presentation rule for the library: mechanics reach
the model as tasks and recipes, never as doc text.

### Snapshot: the mechanic as a task, not a lecture

No mechanic from this library enters the snapshot as prose. A
mechanic reaches the model in two forms, both capped:

- **A task.** The model names the goal ("build a well"), and the
  harness walks it through the steps with material checks at
  each one (have/need from the fresh collect). The snapshot
  carries the task's current step and its material check, in one
  line, the same way every composed task is presented.
- **An attention entry.** A flood, an invasion, or a strange
  mood is an event first: it fires the event system, lands in
  attention, and may carry a briefing. The mechanic's detail is
  behind the query route, never in the snapshot.

**Token cost.** At 7 dwarves and at 50 dwarves alike, this
library costs 0 tokens in the snapshot on its own: its content
is carried by the task lines and attention entries of the
systems that use it, whose costs are stated in their own docs.
A task line is one line at any population. The library adds no
text of its own at any population.

### Query route: the task catalog and GET /v1/tasks (live)

The mechanics are reached through the task catalog: the model
names the goal, the harness runs the recipe. GET /v1/tasks
returns the composed tasks, live today. Each mechanic's detail
(well depth, pump chain, reservoir capacity, trap layout, mood
demands) is behind the mechanic's own route where one exists,
and behind the task result where it does not. The agent asks
when it needs to choose, never as a matter of routine.

### Briefing: per mechanic, fired by its event

The library has no standing briefing of its own. Each mechanic
briefs through its event: a strange mood starting, a flood
detected, an invasion arriving. The briefing states what changed,
what is urgent, and what can wait, in a few hundred tokens at
most, fired once when the event starts. The cost and trigger of
each are stated in the mechanic's own doc. A briefing never
carries the mechanic's full procedure: the procedure is the
task, and the task is walked step by step.

### Opportunities: at most 3, facts only, per system

The library carries no opportunities of its own. The systems
that use it name their entries (at most 3 per tick, facts plus a
query route, never a suggestion, never a pause). A mechanic is
an opportunity only when the fact is actionable and the snapshot
alone does not already say it: "Well: none, water 3 z below"
is an entry; "wells exist" is not.

### What the system deliberately does NOT push, and why

- **The library as text.** The doc is never pasted into the
  snapshot or the prompt. The model is not expected to know
  advanced DF mechanics; that is the library's whole point.
  The mechanic arrives as a task, not a lecture.
- **Unproven routes as available.** Every mechanic in this
  library carries its proof state (§Standing rules for this
  library). A route that is plausible and unproven (squad
  creation, burrow creation, order construction) is never
  presented as working. The task catalog lists only what the
  harness can actually do.
- **The whole procedure up front.** The harness walks the
  model through the steps with material checks at each one.
  Pushing the whole procedure at once would be a dump, and
  the model cannot act on step 5 before step 1 is verified.
- **Flood detection as a certainty.** Flood detection is spot
  water where it should not be, wall it off, drain it. The
  snapshot says water was spotted where it should not be. The
  response is a task. The presentation never claims a flood is
  contained before the wall is up.
