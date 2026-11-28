# Mechanisms and siege

Design record for mechanisms, levers, floodgates, bridges, hatches,
traps, machine components, and siege engines in the Urist harness.
This is the plan. Implementation follows it phase by phase, each
phase verified live against the real game before it counts as done.
Anything not verified against the 0.47.05 game, its raws, or the
harness code is marked UNVERIFIED.

Related docs: docs/ADVANCED_MECHANICS.md (wells, screw pumps,
reservoirs, traps section 4, lever linking section 6, military
section 7; this doc owns the mechanisms and siege-engine side and
does not duplicate those sections), docs/STONEWORKING.md (mechanism
production from the stone side, mechanism stock rules, trap supply),
docs/METALWORKING.md (metal mechanisms, trap components, ballista
arrowheads), docs/WOODWORKING.md (siege engine parts are wood),
docs/MILITARY.md (how traps, bridges, and siege engines are used in
defense), docs/LABOR.md (who gets the mechanic and siege labors),
docs/PLANNER.md (placement scoring for trap sites).
This doc says WHAT the mechanism and siege systems are and HOW the
harness runs them; MILITARY.md says how they are used in a fight.

## A note on sources, read first

The local wiki export (`~/workspace/df-wiki-export/dfq.py`) holds
the CURRENT wiki, not the 0.47.05 wiki. Its pages describe v50
mechanics unless they say otherwise. The v50 pages were used only
to find pages and to read rules that did not change between
versions. Nothing in this doc rests on a v50 page alone where a
0.47.05 source exists.

Every game claim in this doc rests on one of these instead:

- The 0.47.05 raws in the install itself
  (`third_party/df_47_05/raw/objects/item_siegeammo.txt`,
  `item_trapcomp.txt`), read 2026-11-27.
- The live runtime-enum fixture
  (`tests/fixtures/runtime-enums-0.47.05-r8.json`), read
  2026-11-27: job types, building types, item types, labors,
  skills, professions.
- The DFHack 0.47.05-r8 Lua in the install
  (`third_party/df_47_05/hack/lua/dfhack/buildings.lua`,
  `third_party/df_47_05/hack/scripts/gui/advfort.lua`,
  `third_party/df_47_05/hack/scripts/internal/quickfort/build.lua`),
  read 2026-11-27.
- The harness code, read 2026-11-27 (section 13).
- The wiki pages Mechanism, Lever, Lever operation, Floodgate,
  Bridge, Trap, Hatch cover, Pressure plate, Gear assembly,
  Siege engine, Siege workshop, Ballista arrow, Mechanic's
  workshop, read 2026-11-27 from the local export. Where a page
  describes a v50-only feature, this doc says so and does not
  carry it into 0.47.05.

Where a claim comes from the v50 wiki only, or from memory, it is
marked UNVERIFIED and the phase that proves it is named.

## 1. Why mechanisms decide whether the fort survives

A mechanism is the one item every defense and every machine needs.
One mechanism is a trap, a lever, a gear assembly, or a link. Two
mechanisms are a link between a lever and the thing it controls.
Without mechanisms there are no traps, no drawbridge, no floodgate
control, no power train, and no siege engines. The fort can have a
hundred dwarves and a full stockpile of stone and still be
defenseless, because a mechanism is not stone. It is stone plus a
mechanic plus a mechanic's workshop, and none of those three exists
in the harness today.

Three failure modes dominate, and the system in this doc exists to
prevent all three:

1. **No mechanisms at all.** The mechanic's workshop is not in
   `WORKSHOP_CATALOG`, no mechanism job can be queued, and the
   snapshot never prints a mechanism count. The fort can dig for a
   year and never make one. The first siege arrives and the
   entrance is an open corridor.
2. **Mechanisms spent in the wrong place.** A link costs two
   mechanisms, a gear costs one, a trap costs one. A fort that
   links every floodgate and builds gears freely will have no
   mechanisms left when the trap line needs building. Mechanism
   stock is a budget, and the harness must show the balance, not
   just the total.
3. **A lever with no link.** Building the lever is the easy half.
   Linking it is the unresolved half (section 6.4). A lever that
   is not linked is decoration, and a drawbridge that is not
   linked is a floor. The harness must never report a defense as
   ready when only the unlinked half exists.

The harness owns this system. The agent never reasons about
`df.trap_type` values, link job roles, or bridge direction flags.
It gets counts, exceptions, and named options with a one-line why.
See section 15.

## 2. The mechanic labor and the mechanic's workshop

### 2.1 The labor

Mechanics is one labor (`MECHANIC` in the fixture `unit_labors`,
skill `MECHANICS`, profession `MECHANIC`). A dwarf with the
mechanic labor enabled does all of the following: makes stone
mechanisms at the mechanic's workshop, makes metal mechanisms at
a forge, builds traps, builds levers and pressure plates, builds
gear assemblies, links triggers to devices, loads and cleans
traps, and builds screw press workshops. Higher skill means faster
builds. For weapon traps and stone-fall traps, the quality of the
mechanism the mechanic installs sets the attack skill (section
10.1); the mechanic's own skill does not.

The harness can already set the labor: `act_labor.lua` enables or
disables any `df.unit_labor` by name on one citizen, verified by
read-back (STONEWORKING.md section 4.3). LABOR.md owns who gets
the labor; this doc owns what the labor produces. The mechanic
labor is the one labor the fort cannot do without once it has
walls, and it is also the labor that sends dwarves into danger:
mechanics reload and clean traps automatically, including during a
siege, and the only controls on that are forbidding the trap or
burrowing the mechanic away (Trap page). The harness must be able
to say "do not send the mechanic out there" and mean it.

### 2.2 The workshop

The mechanic's workshop is 3x3, built from any non-economic
building material, labor Mechanics (Mechanic's workshop page).
Its job list is two jobs long:

- Make rock mechanisms (`ConstructMechanisms` in the fixture
  `job_types`).
- Make traction bench (`ConstructTractionBench` in the fixture).

A traction bench needs a rope (from a clothier's shop) or a chain
(from a metalsmith's forge), plus a table, plus a mechanism. It
equips a hospital zone. It is a three-industry job: clothier or
forge, carpenter or mason for the table, mechanic for the bench
itself. The harness must not queue a traction bench until all
three inputs exist, or the job sits unworked (STONEWORKING.md
section 3.2 says the same; the rule is repeated here because the
bench is this workshop's job, not the mason's).

Stone mechanisms are the general-purpose kind: one boulder, one
mechanism, base value 30. The workshop is NOT in
`WORKSHOP_CATALOG` today (section 13.1), so `build_workshop`
cannot build it. Placement already anticipates it only by
omission: there is no mechanic affinity row in `placement.py`,
unlike the Mason and Craftsdwarf rows. The workshop wants a stone
stockpile at its side, the same as the mason's, and the affinity
row is part of phase 1.

### 2.3 The siege labors

Siege work is two more labors, both in the fixture: `SIEGECRAFT`
(skill `SIEGECRAFT`, profession `SIEGE_ENGINEER`) and
`SIEGEOPERATE` (skill `SIEGEOPERATE`, profession
`SIEGE_OPERATOR`), plus `PULL_LEVER` for lever pulling (Lever
operation page: the labor is on by default, and limiting it to
dwarves near the lever matters in a crisis, because a pull job
can be assigned to a dwarf hundreds of tiles away). All three are
settable today through `act_labor.lua` by name. Siege engineers
make parts and ammunition at the siege workshop and assemble
engines; siege operators load and fire them. Operators are
civilians: they run in fear if enemy units attack them (Siege
engine page). The harness must not treat an operator as a soldier.

## 3. Metal mechanisms

Metal mechanisms are identical in function to stone mechanisms
(Mechanism page). They are made at a metalsmith's forge or magma
forge from 1 bar of metal, under trap components, and only from
weapons-grade metals by that route. Using the work order menu to
make metal mechanisms (from the manager screen or from a mechanic
workshop's profile) uses a mechanic's workshop instead, always
requires fuel, and allows any metal. The wiki notes it is
generally far more cost effective to smelt a valuable ore into 4
bars and make a metal mechanism from one bar than to make a stone
mechanism from the raw ore.

Two things in that paragraph are UNVERIFIED for 0.47.05. First,
the forge-route restriction to weapons-grade metals comes from
the v50 Mechanism page; the 0.47.05 behavior needs a live probe
(section 19). Second, whether the manager-order route to a
mechanic's workshop works at all in 0.47.05, and whether it
requires a manager noble appointed, is the same open question
STONEWORKING.md section 4.2 raises for stone jobs. The metal
mechanism route belongs to METALWORKING.md for the forge side;
this doc owns only the accounting: a metal mechanism costs 1 bar,
a stone mechanism costs 1 boulder, and the fort needs a standing
reason to choose one over the other (magma safety, section 5, is
usually the reason).

## 4. Mechanism accounting: what each thing costs

Every mechanism in the fort is spent in one of these places. The
harness counts them separately, because a mechanism in a gear is
not a mechanism in a trap, and the fort runs out of one before it
runs out of the other.

| Use | Mechanisms | Source |
|---|---|---|
| Build a trap (stone-fall, weapon, cage) | 1 | Trap page; `trap_inputs` |
| Build a lever | 1 | Lever page; `trap_inputs[Lever]` |
| Build a pressure plate | 1 to 4, by trigger-type count | Pressure plate page |
| Build a gear assembly | 1 | Gear assembly page |
| Link one object to one trigger | 2 (one at each end) | Mechanism page; Lever page |
| Minecart roller | multiple, by length | Mechanism page |
| Build a screw press workshop | 2 | Mechanism page |
| Build a well | 1 | ADVANCED_MECHANICS.md section 1 |
| Build a millstone building | 1 | `workshop_inputs[Millstone]` |
| Make a traction bench | 1 (plus table plus rope or chain) | Mechanic's workshop page |

Notes on the table:

- **The link cost is the one that surprises.** Two mechanisms per
  linked item, one for the linked object and one for the trigger.
  The only way to recover either is to deconstruct the linked
  object. A single lever can be linked to any number of objects,
  and each object can have any number of levers, but every link
  costs two more mechanisms. Deconstructing the lever frees all
  of its mechanisms for reuse, so permanent and one-time linkages
  belong on separate levers (Lever page).
- **Which mechanism goes where matters for magma.** When linking,
  the first mechanism chosen goes to the device end and the second
  to the trigger end. A magma-safe mechanism belongs at the hot
  end; the trigger end can be ordinary (Mechanism page, Lever
  page). The harness must choose the placement, not the agent,
  and must say which end got the magma-safe one.
- **The screw pump takes no mechanism.** A screw pump needs 1
  block, 1 enormous corkscrew, and 1 pipe section
  (ADVANCED_MECHANICS.md section 2). This corrects
  STONEWORKING.md section 9.4, which says a screw pump needs a
  mechanism. See section 18, conflict 1.
- **Bridges take no mechanism to build.** A bridge costs stone,
  logs, or blocks (section 9). The mechanism cost of a bridge is
  the link cost, if it is linked at all.
- **Mechanisms count as furniture for stockpiling.** They go in a
  furniture stockpile, and the jeweler's "encrust furniture with
  gems" job can encrust mechanisms instead of more useful
  furniture (Mechanism page). The harness keeps mechanisms in
  their own stockpile when the fort has a jeweler, or accepts the
  occasional gemmed mechanism (STONEWORKING.md section 9.1).

The mechanism floor (STONEWORKING.md section 14, phase 3) is the
planner rule that follows from this table: the fort keeps a
standing stock of mechanisms, starting floor 3, tuned live, and
does not spend below the floor on gears or links while traps are
waiting to be built or re-armed.

## 5. Magma safety

Mechanisms for use next to or in magma must be magma safe, or
they are destroyed and the object they belong to deconstructs
(Mechanism page). In 0.47.05, magma safety is a melting point
above magma temperature (12000). STONEWORKING.md section 2.3
verified the seven magma-safe layer stones from the raws:
sandstone, gabbro, basalt, quartzite, chert, obsidian, dolomite.
Dolomite is the only flux stone on the list. Granite, the most
common layer stone, is NOT magma safe.

The rule reaches further than mechanisms. A floodgate opened in
magma is destroyed if it is not magma safe, and its mechanisms
must be magma safe too (Floodgate page). A bridge built with any
non-magma-safe material melts if its center tile is covered in
magma or exposed to fire, whether raised, lowered, or retracted,
and the whole bridge deconstructs: the ability of a bridge to
withstand heat is limited by the least fire-resistant item in it
(Bridge page). A single non-magma-safe block or mechanism in a
magma bridge destroys the bridge.

The harness must know which of the fort's stones are magma safe
before it lets a mechanism job pick its own material, and it must
never claim a mechanism is magma safe because the stone's name
sounds like it should be. Magma safety is a melting point in the
raws, and the harness checks the number (STONEWORKING.md
section 13, refusal 10). Whether a metal mechanism is magma safe
depends on the metal, and belongs to METALWORKING.md.

## 6. Levers

### 6.1 Building a lever

A lever is a building constructed from one mechanism on an empty
tile (Lever page, `b-m-l`). It is not a `building_type` of its
own: it is `building_trapst` with `trap_type == TrapType.Lever`
(ADVANCED_MECHANICS.md section 6). The construction filter is
`trap_inputs[Lever]`, one mechanism, and the construction job is
a mechanic's job. The harness has no lever build action today
(section 13.3). The build route is the same `constructBuilding`
call as traps (section 10.3), with `type=Trap` and
`subtype=df.trap_type.Lever`.

Levers make good room decorations when built with high-quality
mechanisms: they have a greater base value than statues
(Mechanism page). That is a use, not a reason to build one: a
lever built for decoration still costs a mechanism and still
needs a mechanic.

### 6.2 Linking a lever to a device

Linking needs two more mechanisms and a dwarf with the Mechanic
labor. The link is made by selecting the lever, choosing Link
lever, and selecting the target object. The linkage interface
warns "Cannot link to" if the object is already linked, or tasked
to be linked, to that lever, or if the building is forbidden. A
lever cannot be linked to a locked door: the dwarves must stand
on the door to complete the link, and the task suspends with a
message that they cannot find a path (Lever page).

What can be linked: doors, hatches, floodgates, grates, bridges,
supports, gear assemblies, restraints, cages, upright
spears/spikes, bars, and track stops (Lever page, Pressure plate
page). What happens on activation depends on the device
(section 6.3). There is no way to de-link an object without
disassembling either the object or the lever. When a linked
single-use object (a cage, a support) is used up, the mechanism
in the lever stays in the lever while the object and its mechanism
deconstruct, so a single lever can accumulate many mechanisms
(Lever page).

Build order does not affect lever timing: in any given tick, levers
send their signals before any furniture receives them, so levers
behave as if they were built after the furniture they link to
(Lever page).

### 6.3 Pulling a lever, and what happens

A dwarf with the lever operation labor pulls the lever
(`PullLever` in the fixture `job_types`). The pull is a
high-priority job, and the dwarf ends up near the lever, usually
on top of it. Levers can be assigned to a specific dwarf, which
prevents other dwarves from pulling them (Lever page). A lever
not linked to anything can still be pulled, which is a way to move
a dwarf to a place (the "Urist's lever" trick). The harness does
not use that trick: moving dwarves by pulling unlinked levers is
a micromanagement hack, not a system.

Levers have an on state and an off state, and pulling one sets
every linked device to the corresponding state. It does not
toggle. Two levers on one bridge can therefore disagree, and the
bridge follows the last state change, not the last pull (Lever
page). Gear assemblies are the sole exception: they toggle
between engaged and disengaged (Lever page, Gear assembly page).

Response delays: doors and hatches activate instantly. Bridges
and floodgates respond 100 steps after the trigger. Several
devices will not respond to a second signal until the first has
taken effect: pulling a lever on then off in rapid succession
moves a floodgate only on the first signal (Lever page).

Per device, on activation:

- Doors, hatches, floodgates, grates: open and close. A linked
  door or hatch is either completely open or sealed shut; there
  is no "closed but openable by a dwarf" state any more.
- Supports: collapse, possibly causing a cave-in. Pulling the
  lever again does not re-assemble the support.
- Bridges: raise and lower, or retract and extend, by bridge type
  (section 9).
- Gear assemblies: toggle engaged and disengaged.
- Restraints: release the creature assigned to them.
- Cages: deconstruct, releasing their occupants. Irreversible.
- Upright spears/spikes: raise and lower.
- Bars: retract and extend.
- Track stops: deactivate and reactivate.

### 6.4 The linking route: what exists and what does not

ADVANCED_MECHANICS.md section 6 records that no DFHack "link
lever" API was found, with two partial precedents:
`advfort.lua` `fake_linking` and `lever.rb`. This doc's research
found a third lead the earlier pass missed, and it changes the
phase 4 plan.

**The lead: the link is a real game job.** The fixture
`job_types` contains `LinkBuildingToTrigger`. The game itself
creates that job when a player links a lever in the UI. And
`advfort.lua` lines 1073 to 1074 contain commented-out code that
would create exactly that job:

```
-- args.job_type=df.job_type.LinkBuildingToTrigger
-- args.building=lever_bld
-- args.triggertarget=bld
```

with a commented-out `assign_link_roles` above it (lines 1020
to 1027) that sets the two job items' roles to
`LinkToTarget` and `LinkToTrigger`. The advfort author got as far
as naming the job and its roles, then fell back to `fake_linking`
instead. The harness's phase 4 tries the real job first: create a
`LinkBuildingToTrigger` job on the lever, with the target
building as `triggertarget` and two mechanism items as job items
with roles `LinkToTarget` (device end) and `LinkToTrigger`
(trigger end), and let a mechanic work it. Whether the game
accepts a directly created link job, validates it, and dispatches
a mechanic to it is UNVERIFIED. It is the first thing phase 4
probes, because a working link job is a typed, verifiable route
and fake linking is not.

**The fallback: `fake_linking`, understood, not trusted.**
`advfort.lua` lines 1028 to 1044 show the end state a real link
produces, and that is the specification for verifying any link,
however it was made:

1. Move one mechanism item into the lever building and one into
   the target building (`dfhack.items.moveToBuilding`, mode 2).
2. Give the trigger-end mechanism a general ref
   `BUILDING_TRIGGER` pointing at the lever, and the device-end
   mechanism a general ref `BUILDING_TRIGGERTARGET` pointing at
   the target.
3. Insert the trigger-end mechanism into the lever's
   `linked_mechanisms` vector.
4. For doors and hatches, set
   `building.door_flags.operated_by_mechanisms` to true.

`fake_linking` does all four directly, with no job and no dwarf,
which is why it is self-described "fake". It is a valid read-back
specification and a last-resort construction route, not the route
of first choice: a link made without a job has no mechanic, no
travel time, and no failure mode the game understands, and the
harness must prove live that a fake-linked device actually
responds to a pull before it relies on one. The proving bar is a
live pull that moves the device (phase 4).

**What a link is, in the observation.** A linked lever carries
`linked_mechanisms` (a vector of mechanism items). A linked
device carries a mechanism item in its contained items with a
`BUILDING_TRIGGERTARGET` general ref. Neither is read by the
harness today (section 13.4). Phase 3 adds the read; phase 4
adds the write.

## 7. Pressure plates

A pressure plate is a lever that is triggered by creatures or
fluids directly rather than by giving an order to a dwarf (Lever
page). It is `building_trapst` with `trap_type ==
TrapType.PressurePlate`, built with `b-t-p` on any floor. The
mechanism cost depends on how many trigger types it watches: one
mechanism per trigger type, so 1 to 4 mechanisms for water,
magma, minecart weight, and creature weight (Pressure plate
page). The creature setting has a toggle for citizens: plates
that can be triggered by citizens are triggerable by
non-citizens as well, and there is no way to make a plate
triggerable by civilians only. Creatures with the `trapavoid`
token do not trigger pressure plates regardless of weight, and
vermin do not trigger traps at all (Pressure plate page).
Pressure plates are not targeted by building destroyers.

A plate sends an open signal the instant its trigger conditions
are met, and resets with a close signal after its conditions have
not been met for 99 consecutive ticks (Pressure plate page). That
99-tick close delay is the plate's sharp edge: closing a hatch or
door 100 ticks later can be too late, and the workaround is a
repeater cycle of several plates. Linked items keep their normal
reaction delay on top of the plate's signal.

Linking a plate costs two mechanisms per target, the same as a
lever, and is done the same way (section 6.4). The plate's own
build route is the same `constructBuilding` call as a lever, with
`subtype=df.trap_type.PressurePlate` and the mechanism count set
by the trigger types chosen at build time. How the harness
chooses trigger types and weight ranges through
`constructBuilding` filters is UNVERIFIED: the DFHack
`trap_inputs[PressurePlate]` entry is a single mechanism filter
with no trigger configuration, and the UI configures triggers at
build time. Phase 3 must determine whether a plate built through
`constructBuilding` gets a default trigger configuration, and
what it is, before the harness offers plates at all.

Pressure plates are the automation half of this doc. A plate on
a lower level, linked to a floodgate between the water supply and
the fort, acts as an automated safety valve (Floodgate page).
That design belongs to the reservoir work in
ADVANCED_MECHANICS.md section 3; this doc owns the plate itself.

## 8. Floodgates, hatches, grates, bars, doors

These are the linkable access-control buildings. They are built
from items, not from raw materials at the build site, and the
harness already places three of them.

### 8.1 Floodgates

A floodgate is a gate that controls the flow of liquids (Floodgate
page). It is made from stone at a mason's workshop, wood at a
carpenter's workshop, metal at a metalsmith's forge (3 bars), or
glass at a glass furnace, then placed with `b-m-f` in the closed
position on a solid, completely flat, unflooded floor. The
construction job is `ConstructFloodgate` (fixture). The harness
places floodgates today: `Floodgate` is in `FURNITURE_ITEMS` and
`act_furniture.lua` places it from stock with a Construct job
(section 13.3). What the harness does not do is link one: a
floodgate with no link is a wall that can only be opened by
deconstruction.

Rules that shape the floodgate plan:

- When closed, a floodgate behaves like a wall. When open, it
  lets liquids, objects, and creatures pass over it.
- Once the lever is pulled, the floodgate opens after a delay
  (100 steps, section 6.3). Pulling again closes it after the
  same delay.
- Closing destroys any liquid occupying the floodgate's tile, but
  objects on the tile cannot be destroyed that way: any object,
  from a sword to a sock to a stone, jams the floodgate open
  until it is removed, and then the gate grinds shut by itself.
  Liquid flow moves objects downstream and can jam a gate the
  fort thought was clear (Floodgate page).
- A floodgate resists magma when closed, like a constructed wall,
  but when opened it is destroyed if it is not made from
  magma-safe materials, and its mechanisms must be magma safe
  too (Floodgate page, section 5).
- A floodgate can be built over empty space by building a floor,
  marking it for removal, and designating the floodgate at once,
  but a floodgate built that way may disappear entirely when the
  lever is pulled in current versions (Floodgate page). The
  harness does not use that trick: a floodgate that vanishes on
  first use is not a floodgate.

### 8.2 Hatches

A hatch cover is a door between z-levels (Hatch cover page). It
is made from stone, metal, wood, or glass at the matching
workshop (`ConstructHatchCover` in the fixture; metal costs 3
bars, returns 1 bar when melted), then placed with `b-p-h` over
stairs, ramps, or open space, as long as it is supported by an
adjacent floor tile. The harness places hatches today:
`Hatch` is in `FURNITURE_ITEMS` (section 13.3).

Rules that shape the hatch plan:

- Like a door, a hatch can be linked with mechanisms or locked.
  A linked hatch is either completely open or sealed shut.
- A dwarf falling down stairs is stopped by a closed floor
  hatch. A dwarf standing on a hatch over stairs does not start
  falling if the hatch is opened. A dwarf standing on a hatch
  above a ramp or open space starts falling if the hatch is
  opened, and drops anything it was hauling.
- Building destroyers can only destroy buildings on other
  z-levels under certain conditions, so hatch covers are
  effective at keeping out enemies when used properly (Hatch
  cover page). ADVANCED_MECHANICS.md section 6 notes the same
  for the flood response: a hatch is a sealable barrier.
- A hatch over a hole with a garbage dump designated on it drops
  dumped items into the hole when opened, which is a use, not a
  hazard the harness plans around.

### 8.3 Grates, bars, doors

- **Grates** (`GrateWall`, `GrateFloor` in the fixture
  `building_types`) let liquid through and block creatures. The
  harness places grates today: `Grate` is in `FURNITURE_ITEMS`.
  A grate is a linkable device: a lever or plate opens and closes
  it like a floodgate. ADVANCED_MECHANICS.md section 1 notes
  that floor grates between a well and its water block the well
  unless opened with a lever.
- **Bars** (`BarsVertical`, `BarsFloor`) retract and extend on a
  signal. No harness build action exists for bars today; the
  build route is `constructBuilding` with the matching type, and
  the material filter for bars is UNVERIFIED (section 19).
- **Doors** are placed today (`Door` in `FURNITURE_ITEMS`,
  `ConstructDoor` in the fixture). A linked door is either
  completely open or sealed shut, and a lever cannot be linked to
  a locked door (section 6.2). A door is the cheapest linkable
  seal in the fort, and the one the harness links first when it
  needs to prove linking works, because a door's state is
  instantly visible.

## 9. Bridges

A bridge is a building that provides a temporarily walkable floor
that can either be removed (a retracting bridge) or turned into a
wall (a raising bridge, a drawbridge) via linked mechanisms
(Bridge page). It is the cheapest real defense in the game: a
drawbridge over the entrance stairwell isolates the surface at
the pull of a lever (MILITARY.md section 9). It is also the
largest single building in this doc, and the one with the most
ways to go wrong.

### 9.1 Building a bridge

Bridges are built with `b-n-b`, of metal, stone, or wood, up to
31 squares in each direction, placed side by side for wider
spans. The material formula is: number of tiles divided by four,
rounded down, plus one. A 3-tile bridge takes 1 material, a
4-tile bridge takes 2, a 7-tile bridge takes 2, a 2x5 bridge
takes 3, a 5x10 bridge takes 13 (Bridge page). Materials can be
mixed: stone, logs, and blocks, with blocks placed significantly
faster during construction, and construction three times faster
for blocks. The "core" material is the single oldest individual
building material used: it determines the color, style,
description, value, and the labor required for construction.

Placement requirements: only one accessible adjacent tile is
required, despite the "Needs walkable perimeter" message. All
tiles the bridge occupies must have no more than 1/7 water at
construction time. Bridges can be placed on floors built
beforehand, but floors cannot be built where the bridge would
lower. Raising bridges must be anchored to a solid surface on the
raising edge, and the raising direction is chosen at placement
and cannot be changed later without deconstructing and
rebuilding. A bridge can span 20 tiles across open space; longer
spans need columns or another anchor (Bridge page).

The harness has no bridge build action today (section 13.3).
The build route is `constructBuilding` with `type=Bridge`,
width, height, and `direction`, which DFHack's `constructBuilding`
passes through `setSize` (buildings.lua lines 496 to 500). Whether
the direction value the harness passes is the raising direction,
the firing direction, or something else, and which enum it comes
from, is UNVERIFIED (section 19). Bridges are also the one
building in this doc whose placement is a site-design problem,
not a 1x1 or 3x3 site: the bridge must span a gap, a channel, or
an entrance, and placement has no bridge site kind today
(section 13.5).

### 9.2 Raising and retracting

A retracting bridge disappears when it is up. A raising bridge
becomes a wall when it is up. The wall is always 1 z-level high
and 1 tile thick, however long the drawbridge is when down, and
it is watertight and invulnerable to building destroyers (Bridge
page). Both kinds respond to a trigger signal 100 ticks after the
signal is sent, and several bridges on one trigger respond
simultaneously.

The two kinds behave oppositely on the same signal, and the
harness must not confuse them: on an open signal, both disappear
from view, but the retracting bridge disappears completely while
the raising bridge becomes a wall that closes the passage on the
same level. The same lever can therefore open one passage and
close another, by design or by mistake (Bridge page).

What a bridge does to what is on it:

- A retracting bridge tosses anything on it (friend, foe, or
  object) onto whatever is underneath, with a semi-random initial
  velocity. That is a pit-trap mechanism, and also a reason to
  never retract a bridge with dwarves on it.
- A raising bridge flings anything on it into the air when it
  raises. When lowered, a bridge destroys most anything on the
  underlying tiles: dwarves, foes, and items entirely disappear.
  That is the dwarven atom smasher, and it is the reason a
  drawbridge is never lowered blind.
- A bridge does not operate if any one creature of size 1,200,000
  or larger is on it. The limit is not cumulative: a hundred
  goblins do not block it, but one rutherer does. Attempting to
  lower a drawbridge onto such a creature deconstructs the
  bridge. Attempting to unretract a bridge while such a creature
  is on any of its tiles deconstructs it too (Bridge page).
- A raised bridge cannot be linked to a lever from the inside:
  the mechanic must be able to access the center tile of the
  bridge when lowered (Bridge page).

### 9.3 Bridges and heat, water, and support

- **Heat:** any non-magma-safe material in the bridge melts it
  when the center tile is covered in magma or exposed to fire,
  whether raised, lowered, or retracted. Dragonfire melts nearly
  all bridges (Bridge page, section 5).
- **Water:** water displaced by a raising bridge is destroyed
  regardless of open space on either side or above. Water resting
  on a retracting bridge falls straight down after it retracts.
  A bridge is therefore a fluid-control device as well as a
  floor, and a single large bridge can replace many floodgates
  when the fluid needs a wide opening (Bridge page).
- **Support:** bridges do not provide structural support. A
  construction completed when attached only to a bridge causes
  an immediate cave-in. The harness must never place a
  construction adjacent to a bridge unless it is also adjacent
  to a completed construction (Bridge page).
- **Digging:** stone directly under a bridge cannot be channeled
  out, raised or not, and a ramp cannot be dug under a bridge.
  The bridge must be deconstructed first (Bridge page).

## 10. Traps

This section owns the trap creation route, the loading jobs, the
mechanism supply, and the observation. The per-type behavior
rules live in ADVANCED_MECHANICS.md section 4 and MILITARY.md
section 9; they are summarized here only where the creation or
observation work depends on them, not repeated in full.

### 10.1 The four types

- **Stone-fall trap** (`b-t-t`): 1 mechanism plus 1 ordinary
  stone. Usually will not kill outright but can break a bone;
  stone weight affects damage. Re-arming is required after every
  use: a mechanic automatically reloads with a new stone. Does
  not alert to ambushes. Respects economic stone restrictions
  and cannot be loaded with clay.
- **Weapon trap** (`b-t-o`): 1 mechanism plus 1 to 10 weapons.
  All weapons attack at once. Resets automatically after an
  unknown period; the wiki's own words, do not assert a number.
  A kill has a 50 percent chance to jam the trap, and a mechanic
  automatically tries to clean it. Only jams on a direct kill,
  not a bleed-out. Crossbows fire one bolt per trigger and stop
  firing when bolts run out, signalling reload. Hammers jam less
  than swords or axes; spears jam the most.
- **Cage trap** (`b-t-g`): 1 mechanism plus 1 cage. Captures the
  victim unharmed. Alerts to ambushes when triggered by hidden
  invaders. Re-arming: reset by hauling an empty cage to it,
  automatic by a mechanic, only when the Trap Rearming standing
  order permits. Dwarves only load empty cages. Captured
  creatures survive indefinitely in a cage; if left alone about
  a year or longer the prisoner escapes. Titans, forgotten beasts,
  and certain creatures are immune to traps entirely, except a
  webbed cage trap.
- **Upright spear/spike trap** (`b-t-u`): 1 to 10 spears or
  spikes, no mechanism unless linked. Does not self-trigger and
  does not discriminate friend from foe. Does not jam. Damage
  happens only at the moment the spikes spring up, or to a
  creature that falls onto deployed spikes from above, and the
  pit must be more than 1 z-level deep for falling damage.

Mechanism quality sets the attack skill for weapon and stone-fall
traps: Basic is Dabbling 0, Well-crafted is Competent 3, Fine is
Talented 6, Superior is Professional 9, Exceptional is Master 12,
Masterwork (including artifact) is Legendary 15. It has no effect
on cage traps, and no effect on upright spikes (Trap page).

Conscious dwarves, guests, allies, caravans, and domestic animals
do NOT set off self-triggered traps. Any unconscious creature,
including your own dwarves, will trigger them. Thieves, flying
creatures, and some invaders may avoid or recognize them. Traps
block caravan wagons but not traders with pack animals (Trap
page).

### 10.2 The creation route (the known missing piece)

Placement already computes trap sites: 1x1, weapon, cage, and
stonefall kinds, scored at entrance choke points, with cage traps
doubled as ambush alarms (placement.py lines 104 to 106, 152,
841 to 849). No creation action exists. The route is
`dfhack.buildings.constructBuilding` with `type=df.building_type.Trap`
and `subtype=<df.trap_type value>`, with filters defaulting from
DFHack's `trap_inputs` table (buildings.lua lines 298 to 338).
Quickfort uses exactly this call for all four trap kinds
(build.lua lines 718 to 732), which is the in-tree precedent.

The filter table settles the construction inputs:

- StoneFallTrap: 1 mechanism. The stone is NOT a construction
  input. It is loaded after construction by the `LoadStoneTrap`
  job (fixture `job_types`).
- WeaponTrap: 1 mechanism plus 1 weapon (`ANY_WEAPON` vector).
  Further weapons, up to 10, are added after construction; how
  the game adds weapons 2 to 10 to a built weapon trap through
  DFHack, and whether `LoadWeaponTrap` covers it, is UNVERIFIED.
- Lever: 1 mechanism.
- PressurePlate: 1 mechanism (see section 7 for the trigger
  configuration gap).
- CageTrap: 1 mechanism. The cage is NOT a construction input.
  It is loaded after construction by the `LoadCageTrap` job
  (fixture `job_types`).

**The cage discrepancy, resolved on paper.** ADVANCED_MECHANICS.md
section 4 records a discrepancy: DFHack's table lists mechanism
only for cage traps, while the wiki says a cage must be provided.
Both are right at different levels. The wiki's "Components used:
mechanism and a cage" describes the finished trap. The DFHack
table describes the construction job, which takes only the
mechanism. The cage arrives afterwards, through the
`LoadCageTrap` job, which the fixture confirms exists. Quickfort's
cage trap entry carries `additional_orders={'wooden cage'}`,
which is a production order for the cage item, not a build input:
the cage must exist in stock before the load job can run. The
resolution still needs a live build to confirm (phase 2), but
there is no longer a contradiction to choose between. See
section 18, conflict 3.

**The subtype lookup blocker.** `act_build.lua` hardcodes its
subtype lookup to `df.workshop_type[...]`, so a trap subtype
would error as "unknown workshop subtype". It needs a type-aware
lookup: `df.trap_type` for `Trap`, `df.siegeengine_type` for
`SiegeEngine`, and no subtype (or a bridge direction) for
`Bridge`. The `act_furniture.lua` pattern (non-workshop types,
`subtype=-1`) is the model; traps use a real subtype instead
(ADVANCED_MECHANICS.md section 4).

**Upright spears are not traps in the code.** Quickfort builds
an upright spear/spike trap as `type=df.building_type.Weapon`
(build.lua line 735), not `Trap`. ADVANCED_MECHANICS.md section
4 lists it under the trap types without noting the different
building type. The harness needs a separate build route for it,
and its observation is a `Weapon` building, not a `Trap`
building. See section 18, conflict 4.

### 10.3 Loading, cleaning, and re-arming

The fixture `job_types` has the whole maintenance set:
`LoadCageTrap`, `LoadStoneTrap`, `LoadWeaponTrap`, `CleanTrap`,
plus `BaitTrap` and `MakeAnimalTrap` for animal traps, which are
a different system (vermin catching, not defense). The game
creates load and clean jobs automatically when a trap needs them,
and a mechanic with the labor enabled takes them. That automatic
behavior is the hazard as well as the convenience: a triggered
stone-fall trap issues a reload job at once, and a mechanic will
walk out to reload it in the middle of a siege unless the trap is
forbidden or the mechanic is burrowed away (Trap page). The
harness's maintenance loop must therefore do three things the
game does not do on its own: forbid traps during a siege, unforbid
them when it is safe, and say which traps are waiting for service
(section 15).

Trap components for weapon traps are made with `MakeTrapComponent`
(fixture `job_types`): menacing spike, spiked ball, enormous
corkscrew, large serrated disc, giant axe blade. The raws
(`item_trapcomp.txt`) confirm all five: giant axe blade and large
serrated disc are metal only; enormous corkscrew, spiked ball, and
menacing spike are wood or metal. The forge, carpenter, and glass
furnace routes belong to METALWORKING.md, WOODWORKING.md, and the
glass work; this doc owns only the fact that a weapon trap needs
its weapons to exist before it can be loaded, and that trap-only
weapons are larger than dwarf weapons and massively less durable
(Trap page).

### 10.4 Trap state: what the harness cannot see

Trap state (loaded or unloaded, contents, jammed) is not read by
the harness today. `buildings.lua` lists every building with its
type, position, job count, and contained-item count, but it reads
a subtype only for workshops, so a Trap building appears with no
kind, and a SiegeEngine building appears with no kind or
direction. The `building_trapst` fields (loaded, contents,
jammed, linked mechanisms) are not collected anywhere in the
repo. The harness cannot tell an armed stone-fall trap from an
empty one, or a jammed weapon trap from a clean one. Phase 2 adds
a trap-state probe; until then, every trap claim in the snapshot
is a count of buildings, not a state (section 13.4).

## 11. Siege engines

### 11.1 The siege workshop

The siege workshop (`b-o-g`) makes ballista and catapult parts
and assembles siege ammunition (Siege workshop page). It is built
from 3 building materials (non-economic), labor Siege engineer.
Its size is UNVERIFIED: the workshop diagram suggests 3x3, but
no 0.47.05 source in this research confirms the footprint, and
the harness must read it off a live build before placing one
(section 19). The workshop is NOT in `WORKSHOP_CATALOG` today
(section 13.1).

Its jobs, from the fixture `job_types`:

- `ConstructCatapultParts`: 3 parts per engine, each part made
  from wood at the siege workshop (Siege engine page). The exact
  log input per part is UNVERIFIED (section 19).
- `ConstructBallistaParts`: same, 3 parts per engine.
- `AssembleSiegeAmmo`: assembles ballista arrows at the siege
  workshop.
- `MakeBallistaArrowHead`: at a metalsmith's forge, from 3 metal
  bars, by a weaponsmith (Ballista arrow page). The forge side
  belongs to METALWORKING.md.

Part quality has no effect on engine operation, so there is no
reason to produce high-quality parts except to raise fortress
architecture value (Siege engine page).

### 11.2 The engines

0.47.05 has two siege engines. The third engine on the v50 wiki
page, the bolt thrower, does NOT exist in 0.47.05: there is no
bolt thrower in the raws, no bolt thrower job type in the
fixture, and no bolt thrower part item. The harness must never
offer it, and any v50 text about it is ignored for this version.

- **Catapult** (`b-y-p`): 3x3, built from 3 catapult parts,
  crewed by a siege operator, labor Siege operating to fire.
  Ammunition is ordinary stone. Catapults respect economic stone
  restrictions and cannot fire clay. Range is more than a
  screen-width, around 80 to 100 tiles (Siege engine page). A
  catapult has a minimum range of at least 30 tiles, and fires
  over creatures between it and its target (Siege engine page,
  flagged "[is this true?]" on the page itself; treat the minimum
  range as UNVERIFIED).
- **Ballista** (`b-y-b`): 3x3, built from 3 ballista parts.
  Ammunition is ballista arrows, wood or metal. Range is between
  130 and 200 tiles (Siege engine page). A ballista arrow kills
  or injures each creature in its path, friend or foe, and the
  arrow loses range per creature hit based on its weight: arrows
  of 50 or less subtract 50 tiles per hit, arrows of 150 or more
  subtract 5 tiles per hit (Ballista arrow page). The exact
  0.47.05 ranges are UNVERIFIED: the page numbers are v50 text
  and the 0.47.05 numbers need a live firing test (section 19).

Both engines are built like any other building, selecting the
parts, and cannot be moved except by taking them down and
re-assembling them. They do not impede movement, so they can be
built in a corridor. Orientation is chosen at placement: in
0.47.05 the engines fire in the cardinal directions only, per the
v50 page's note that earlier versions could only fire directly in
the cardinal directions and versions 53.01 and later can target
anything in their firing arc. Whether 0.47.05 orientation is
four-way or eight-way at build time, and how `constructBuilding`
sets it, is UNVERIFIED (section 19). DFHack's `constructBuilding`
does accept a `direction` argument through `setSize`
(buildings.lua lines 496 to 500), so the call has somewhere to
put a direction; the value it takes for a siege engine is the
open question.

### 11.3 Ammunition

- **Catapult stones:** ordinary stone, any boulder the fort can
  spare. Stone is effectively free, which is why the catapult is
  the training platform: catapults and ballistae train the siege
  operator skill at the same rate, and catapult stone costs
  nothing (Ballista arrow page). Ammo is destroyed on landing,
  unless it falls a z-level, in which case it falls harmlessly
  and can be recovered: a channel at the end of a firing range
  preserves the stone (Siege engine page).
- **Ballista arrows:** two kinds. A simple wooden arrow is
  assembled from one unit of wood at the siege workshop by a
  siege engineer. A metal arrow needs an arrowhead first (3 bars
  at the forge by a weaponsmith), then final assembly with wood
  at the siege workshop (Ballista arrow page). Wooden arrows are
  surprisingly ineffective, dealing only minor blunt damage.
  Metal arrows are extremely lethal: one can kill two
  fully-grown elephants standing in a line if it hits squarely
  (Ballista arrow page). Wood type matters for wooden arrows
  (heavier wood is better); for metal arrows the shaft wood is
  irrelevant because the game treats the whole arrow as metal.
  Both arrowheads and completed arrows are stored in the Siege
  ammo section of Furniture/Siege Ammo stockpiles. The wiki's
  advice is blunt: there is never much reason to produce wooden
  ballista arrows. The harness follows it: wooden arrows are a
  training consumable at most, never the defense plan.

### 11.4 Operating an engine

When an engine is placed, its mode is set in its menu: not in
use, loaded, prepare to fire, training, or fire at enemies
(Siege engine page). The exact 0.47.05 mode names and their
behavior are UNVERIFIED: the page describes the v50 menu, and the
0.47.05 menu needs a live read (section 19). The shape is the
same in both versions: an operator loads the engine, and in
firing modes the engine shoots at enemies or at an archery target
for training. Operators load any engine that is not loaded, and
there is no way to stop them short of disabling the labor on all
dwarves or forbidding every piece of ammunition (Siege engine
page). Practice fire wastes ammunition; fire-at-enemies stops
when no targets are left.

The fixture `job_types` has the operating jobs: `LoadCatapult`,
`LoadBallista`, `FireCatapult`, `FireBallista`. How the harness
sets an engine's mode through DFHack, and whether mode is a
building field the harness can write or a job it must create, is
UNVERIFIED. That is the phase 6 probe: without a mode write, the
harness can build an engine and load it, but cannot order it to
fire.

### 11.5 Safety

Ballistae kill anything in their path, friend or foe, including
in the space the loaded arrowhead occupies. The firing arc must
be a restricted traffic area, walled off with fortifications, or
both, and dwarves must be kept out of it (Siege engine page).
Catapult stones can hit and injure dwarves in their path, and the
shrapnel they create on impact can inflict damage as well. Both
engines have a narrow field of fire, roughly 19 degrees across,
and aim at a location exactly 60 tiles away with up to 10 tiles
of sideways drift for an unskilled operator; skill reduces the
drift, and a Legendary operator eliminates it (Siege engine page).
The firing arc numbers are v50 text; the 0.47.05 numbers are
UNVERIFIED, but the safety rule is not version dependent: the
harness never places an engine whose firing arc crosses a
corridor dwarves use, and never fires one while a dwarf is
downrange. Siege operators are civilians and flee; an engine
whose operator flees is an unmanned engine, and the harness says
so rather than reporting it as firing.

## 12. Machine components

Machines are the power system, and mechanisms are its currency.
The power rules (windmill 40/20/0 by wind level, water wheel 100
net plus 90, gear 5 power, axle 1 per tile, pump 10 power, pumps
run 49 ticks after losing power) live in ADVANCED_MECHANICS.md
section 2 and are not repeated here. This section owns only the
components and their mechanism costs.

- **Gear assembly** (`b-m-g`): 1 mechanism, needs 5 power.
  Transmits power from one adjacent machine component to another,
  and is required to change the direction of power flow, whether
  a horizontal x/y change on the same z-level or a change between
  vertical and horizontal (Gear assembly page). Gears transfer
  power only orthogonally, never diagonally. To transfer power
  between z-levels, dig a channel, place the gear over the
  opening, and place another gear, a vertical axle, or a machine
  on the z-level below in the same square. Gears do not block unit
  movement. A gear can be disconnected by linking it to a lever:
  pulling the lever toggles it between engaged and disengaged,
  and a device supported entirely by that gear may collapse when
  it is disconnected (Gear assembly page). The harness has no gear
  build action today (section 13.3); the route is
  `constructBuilding` with `type=GearAssembly` and a mechanism
  filter.
- **Axle**: 1 power per tile. Horizontal and vertical axles
  (`AxleHorizontal`, `AxleVertical` in the fixture
  `building_types`). No mechanism cost. The harness has no axle
  build action today.
- **Roller** (`Rollers` in the fixture `building_types`):
  minecart rollers need multiple mechanisms depending on length
  (Mechanism page). The exact count by length is UNVERIFIED
  (section 19). Rollers belong to the minecart work, not to this
  doc's phases; the mechanism cost is recorded here so the
  minecart plan does not spend the trap stock blind.
- **Screw press workshop**: needs 2 mechanisms, built by any
  dwarf with the mechanics labor (Mechanism page). The press
  itself belongs to the kitchen/oil work; the mechanism cost is
  recorded here.
- **Screw pump**: no mechanism (section 4). Its components are a
  block, an enormous corkscrew, and a pipe section, and its power
  and placement rules are in ADVANCED_MECHANICS.md section 2.
- **Millstone building**: 1 mechanism plus the millstone item
  (`workshop_inputs[Millstone]` in buildings.lua). The millstone
  job itself is in STONEWORKING.md phase 2; the mechanism cost is
  recorded here.

## 13. What the harness has today

Verified against the repo 2026-11-27. Everything in this section
was read from the code, not assumed. The game and the daemon were
down during this research (VM replacement about 19:37 PT,
recovery running separately), so no live read was possible; every
live value is flagged UNVERIFIED in section 19 rather than
invented.

### 13.1 The mechanic and siege workshops do not exist

`WORKSHOP_CATALOG` (actions.py lines 133 to 148) has exactly four
workshops: carpenter, mason, still, kitchen. The mechanic's
workshop and the siege workshop are NOT in the catalog.
`build_workshop` cannot build either one today. The jeweler's
workshop and the craftsdwarf's workshop are also missing
(STONEWORKING.md section 4.1). The siege workshop needs a
catalog entry with its own material shape: 3 building materials,
not the single `material` the catalog's four entries carry, so
the entry is not a copy of the mason's.

`placement.py` already anticipates the mason and the craftsdwarf
with stone-stockpile affinity rows. There is no mechanic row and
no siege row. The mechanic's workshop wants a stone stockpile at
affinity 25, the same as the mason's. The siege workshop wants a
wood stockpile at its side, and its affinity row is new work.

### 13.2 No mechanism, trap-component, or siege job can be queued today

`JOB_SPECS` (actions.py lines 155 to 188) has exactly twelve
jobs: brew, brew_fruit, cook, make_bed, make_table, make_chair,
make_door, make_barrel, make_bucket, make_bin, make_chest,
make_cabinet. Every one is a still, kitchen, or carpenter job.
There is no mechanic job, no siege job, and no trap-component job
in the list.

The gap is structural, not just a missing list, and it is the
same gap STONEWORKING.md section 4.2 names: workshop item jobs
in this harness are REACTIONS (`job_type` 211, CustomReaction,
with a `reaction_name` from the raws). Mechanic, siege, and trap
jobs are NOT reactions. They are hardcoded job types in the game,
and the fixture confirms every one of them exists in 0.47.05:
`ConstructMechanisms`, `ConstructTractionBench`,
`MakeTrapComponent`, `ConstructCatapultParts`,
`ConstructBallistaParts`, `MakeBallistaArrowHead`,
`AssembleSiegeAmmo`, `LoadCatapult`, `LoadBallista`,
`FireCatapult`, `FireBallista`, `LoadCageTrap`, `LoadStoneTrap`,
`LoadWeaponTrap`, `CleanTrap`, `PullLever`,
`LinkBuildingToTrigger`, `ConstructFloodgate`,
`ConstructHatchCover`, `ConstructGrate`. The `queue_workshop_job`
action can only express reaction jobs, so it cannot queue a
single mechanism or siege job even if the building exists. The
fix is the same second job shape STONEWORKING.md phase 2
specifies: a hardcoded `job_type` name with no reaction. That one
fix unblocks the mechanic, the siege workshop, and the trap
components together, because all three are hardcoded job types.

The one existing route that CAN express a mechanism or siege job
today is `manager_order_create` (actions.py, `act_order.lua`). It
takes a `df.job_type` name directly and creates a manager order,
which the game dispatches to any workshop that can do it. It was
verified live for a generic order, but no mechanism or siege job
type has been passed through it, and whether the manager validates
and dispatches a mechanic job without a manager noble appointed
is UNVERIFIED (section 19).

### 13.3 Building: furniture works, traps, levers, bridges, gears, and engines do not

- `act_build.lua` places workshops via
  `dfhack.buildings.constructBuilding`. It hardcodes its subtype
  lookup to `df.workshop_type[...]`. A trap subtype would error
  as "unknown workshop subtype". A siege-engine subtype would
  error the same way. A bridge has no workshop subtype at all.
  The lookup must become type-aware before any building in this
  doc can be placed through it (section 10.2).
- `act_furniture.lua` places 1x1 furniture from stock:
  Bed, Table, Chair, Door, Coffin, Chest, Cabinet, ArmorStand,
  WeaponRack, Statue, Floodgate, Hatch, Grate. Floodgate, Hatch,
  and Grate already work from stock, verified live for Bed
  2026-11-26. It does NOT know Trap, Lever, PressurePlate,
  GearAssembly, Bridge, or SiegeEngine, and it does NOT know
  Bars. A bridge is not 1x1 and is not placed from a stock item,
  so it needs the `act_build.lua` route, not the furniture route.
- `constructBuilding` itself is ready. DFHack's
  `getFiltersByType` covers Trap (all six subtypes), SiegeEngine
  (Catapult and Ballista, 3 parts each), and the building-input
  tables cover Floodgate, Hatch, and Grate. The DFHack side has
  no gap; the harness side has all of it.
- No pull-lever action exists. No link action exists. No
  trap-load or trap-clean action exists (the game creates those
  jobs automatically; the harness needs only to observe them and
  to forbid or unforbid the trap, which is a separate action that
  also does not exist). No siege-mode action exists. No bridge
  direction is passed anywhere.

### 13.4 Observation: buildings are listed, their state is not

`buildings.lua` lists every building with its type name, type id,
position, job count, contained-item count, and construction stage,
plus a subtype read that runs only for workshops. A Trap building
appears with no kind. A SiegeEngine building appears with no kind
and no direction. A Bridge building appears with no direction and
no raised or lowered state. A Lever building appears with no link
state. The `building_trapst` fields (loaded, contents, jammed,
`linked_mechanisms`) are not collected anywhere in the repo, and
neither are the `building_siegeenginest` fields, the
`building_bridgest` fields (direction, raised state), or the
`building_gearst` fields. The harness can count how many Trap
buildings exist. It cannot say whether any of them is armed.

`stocks.lua` does carry the raw material for mechanism counts:
its `items.by_type` array lists every item type in play with
stacks and units, keyed by type name, so `TRAPPARTS`,
`CATAPULTPARTS`, `BALLISTAPARTS`, `SIEGEAMMO`, `TRAPCOMP`, and
`CAGE` counts are collectable today. The assembler never surfaces
them: `_stocks` in assembler.py prints drink, food, wood, stone,
brewable plants, empty barrels, and food stacks, and nothing
else. A mechanism count of zero is invisible to the model until
section 15 lands.

### 13.5 Placement: trap sites exist, nothing else in this doc does

`placement.py` computes trap sites (1x1, weapon, cage, stonefall)
at entrance choke points, scored for path position, door and
stair adjacency, and service distance, with cage traps doubled as
ambush alarms (lines 104 to 106, 152, 280, 841 to 849). Traps are
exempt from the threat hold that blocks other placements during an
attack (line 586): they are unmanned and built ahead of an
attack. That is the whole placement surface for this doc. There
is no lever site kind, no pressure-plate site kind, no bridge
site kind, no gear site kind, and no siege-engine site kind. A
siege engine needs a firing lane, not a room: its site is a
position plus a direction plus a clear arc, and the site system
has no arc concept today. A bridge needs a gap to span, and the
site system has no gap concept today. Both are phase 5 and phase
6 design work, not a one-line site kind.

### 13.6 Tasks: the composed-task framework does not exist yet

`TASK_DEFS` (daemon.py lines 214 to 226) has six tasks: brew,
cook, make_bed, make_barrel, gather, farm. `Daemon.run_task` is
single-action only: one `queue_job` plus wait-for-disappearance
plus a cancellation check. There are no steps, no per-step
prerequisites beyond the single `need` workshop, and no
step-by-step verification. ADVANCED_MECHANICS.md section 0
specifies the generalization (an ordered step list, per-step
verification, failure diagnosis with cause and fix) and orders it
before any mechanic is built. This doc does not re-specify it:
every composed task in section 14 depends on that framework
landing first, and the first mechanism task (make a mechanism,
build a trap) is the second verification of the framework after
the well.

## 14. The chains, end to end

### 14.1 The mechanism supply chain

Dig stone, haul boulders to the stone stockpile by the mechanic's
workshop, make mechanisms, store them in their own furniture
stockpile by the traps and the levers. One boulder per mechanism,
one mechanic per workshop, one labor the fort must staff before
it has walls worth defending. The bottleneck moves: early on it
is the workshop (it does not exist); then it is the mechanic
(one dwarf, every trap and link competing for one pair of hands);
then it is the magma-safe stock (the fort has a hundred granite
mechanisms and none that can go near magma). The snapshot must
show which bottleneck is binding right now (section 15).

### 14.2 The defense chain

Make mechanisms, build traps at the sites placement already
computes, build a lever, link the lever to the drawbridge and the
floodgates, pull the lever when the siege arrives. The chain has
one step the harness cannot do yet (linking, section 6.4) and one
step it cannot see yet (trap state, section 10.4). Until both
land, the defense chain is a list of buildings, not a defense.
The military plan (MILITARY.md) depends on traps existing, so
trap creation lands before or alongside the military, not after
it. Invaders learn trap locations: after a siege, traps are torn
down and rebuilt elsewhere, and the harness must track which
traps have been observed sprung (MILITARY.md section 9).

### 14.3 The siege-engine chain

Build a siege workshop, make 3 parts per engine, build the
engine on a firing lane, make ammunition, set the engine to fire
at enemies, keep the firing arc clear of dwarves. The chain is
long and the fort needs it late: a catapult is a training
platform before it is a weapon, and a ballista is a weapon only
when it has metal arrows. The harness must not build an engine
before it has the parts, must not set it to fire before it has
ammunition, and must not fire it while a dwarf is downrange. The
firing lane is the site-design problem in section 13.5, and it is
the reason siege engines are phase 6, not phase 2.

### 14.4 The machine chain

Make mechanisms, build gear assemblies and axles, connect a power
source (windmill or water wheel) to a consumer (screw pump,
millstone). The power rules are ADVANCED_MECHANICS.md section 2.
The mechanism cost is section 4. The chain is phase 7, after the
defense chain, because a millstone project must never eat the
trap stock: the harness counts mechanisms reserved for machines
separately from mechanisms reserved for traps.

## 15. Model presentation

This section is required by the 2026-11-27 presentation
constraint (GOAL.md, coordinator log 2026-11-27 about 17:47 PT):
every new system must state how its information reaches the
model, what it costs, and what it deliberately does not push. The
snapshot stays an index: counts, exceptions, and diffs only,
about 4,700 tokens typical, never a replacement for full state.
Budgets hold (target 30K, warning 60K, compaction 100K, hard cap
140K on a 200K window), enforced by the assembler's token
accountant with its cut order. No system bolts its own dump onto
the snapshot.

Token costs below are computed from the exact section text with
the accountant's own rates (3 chars per token for the cap, 4 chars
per token on the wire). They are estimates until the coordinator
verifies them against the live assembler before commit, as the
amendment requires. The numbers are small because the section is
an index: it names counts and exceptions, and the detail lives
behind queries.

### 15.1 Snapshot: the Mechanisms section

The per-tick snapshot gains a short Mechanisms section, built
from the fresh collect, in plain words. Three lines, in this
shape:

```
Mechanisms: 6 in stock (4 stone, 2 iron), 3 in traps, 2 in levers, 0 spare for machines.
Mechanic #14: idle. Siege #16: idle, 0 catapult parts, 0 ballista parts, 0 ballista arrows.
Traps: 2 stonefall armed, 1 weapon trap jammed, 1 cage trap empty. Bridge: raised, lever linked.
```

What is in it, and what is not:

- **Line 1, counts.** Mechanisms in stock, split stone and metal,
  then mechanisms committed to traps, to levers, and the spare
  count for machines. These are counts, not a list: the fort has
  many mechanisms and the snapshot never names each one. When the
  stock is zero and traps are waiting, the line says so and names
  the fix: "Mechanisms: 0 in stock, 2 stonefall traps waiting to
  be built. Make mechanisms: 1 boulder each." A zero stock is an
  exception, not a silence.
- **Line 2, workshops.** One short clause per mechanism or siege
  workshop that exists, capped at 2 clauses, then "and N more"
  when there are more. Each clause names the workshop subtype and
  id (so the model can queue a job without a query turn), its
  state (idle, or jobs queued with the job kinds), and the parts
  and ammunition counts for the siege workshop. When no
  mechanic's workshop exists, the line says so and names the fix:
  "No mechanic's workshop. Build one: 1 stone in stock." A
  missing workshop is an exception, not a silence.
- **Line 3, traps and bridge.** Armed stone-fall traps, jammed
  weapon traps, empty cage traps, and the bridge state with its
  link state. A jammed trap and zero spare mechanisms are
  attention entries, ranked with the other problems, never buried
  in a list. When there are no traps at all, the line is one
  clause: "Traps: none built." When there is a bridge with no
  link, the line says "Bridge: built, lever not linked" rather
  than "defense ready".
- **Diffs, not repeats.** When nothing in the section changed
  since the last tick, the assembler prints the short form
  ("mechanisms: unchanged"), the same way the Buildings section
  already does. The section costs its full price only on ticks
  when mechanism state actually moves.

**Token cost.** At 7 dwarves, the section as written above is 277
characters: about 92 tokens by the accountant's 3-chars-per-token
rate, 69 on the wire. At 50 dwarves, with more workshops and more
traps, it reads:

```
Mechanisms: 14 in stock (9 stone, 5 iron), 8 in traps, 4 in levers, 2 spare for machines.
Mechanic #14: 2 jobs queued (mechanisms). Siege #16: 1 job queued (catapult parts), 6 catapult parts, 4 ballista parts, 12 ballista arrows. And 1 more.
Traps: 5 stonefall armed, 2 weapon traps jammed, 1 cage trap empty, 1 upright spike. Bridge: raised, lever linked.
```

That is 356 characters: about 119 tokens by the accountant,
89 on the wire. The cost grows by about 27 tokens from 7 dwarves
to 50, because the section is capped: 2 workshop clauses maximum,
trap counts only, bridge state in one clause. It does not grow
with population, with the number of mechanisms, or with the number
of traps on the map. If a future change makes it grow with any of
those, the change is refused until the section is capped again.

### 15.2 Query route: GET /v1/mechanisms

GET /v1/mechanisms returns the full detail, read from the fresh
collect, not from a cache:

- Mechanisms: in stock by material and quality, in traps, in
  levers, in gears, reserved for machines, and the magma-safe
  count.
- Per workshop: id, subtype, position, construction stage, queued
  jobs with their job types and counts, contained items (clutter),
  and the mechanic or siege engineer assigned to it, with skill
  level.
- Traps: each trap by id, type, position, armed or empty, jammed
  or clean, what it is loaded with, and whether it has been
  observed sprung.
- Levers and plates: each trigger by id, position, on or off
  state, what it is linked to, and whether the link is verified
  by a live pull.
- Bridges: each bridge by id, position, size, direction, raised
  or lowered, retracted or extended, linked or unlinked.
- Siege engines: each engine by id, type, position, direction,
  mode, loaded or unloaded, and ammunition in stock by kind.
- Trade readiness: mechanisms in the trade stockpile with their
  computed values (base 30, quality and material multipliers).

The snapshot carries the summary and the ids; the route carries
the detail. The agent asks the route when it needs to choose which
mechanism to use, which trap to fix, or which lever to pull, never
as a matter of routine. Both routes state their cost and staleness
on every response, the same as every other query route.

### 15.3 Briefing: what arrives just in time

Mechanisms have no standing briefing. Three events carry one,
all from the existing briefing system (briefings.py), each a few
hundred tokens at most, each fired once when the event starts:

- **Invasion announced.** Trigger: the invasion event. Cost:
  about 58 tokens by the accountant for the mechanisms paragraph
  (174 characters). It covers how many traps are armed, whether
  the drawbridge is linked and which state it is in, and whether
  any weapon trap is jammed. It leaves the trap list and the
  lever pull to the query route and to MILITARY.md. A fort with
  no traps and no bridge gets no paragraph at all: the briefing
  does not promise a defense the fort does not have.
- **First siege engine built.** Trigger: the first SiegeEngine
  building appears in the collect. Cost: about 48 tokens. It
  covers the engine type, its direction, its mode, and whether
  ammunition exists for it. It leaves the firing-lane safety
  check to the query route.
- **Mechanism stock hits zero while traps wait.** Trigger: the
  stock hits zero with trap sites unbuilt or traps unloaded.
  Cost: about 44 tokens. It covers how many mechanisms the
  waiting work needs and what one mechanism costs. It fires once
  per stock-out, not once per tick.

No other mechanisms event briefs the model. A mechanic finishing
a masterwork mechanism, a trap springing, or a gear being built
are attention entries and opportunities entries, not briefings.
A briefing is for something the model needs to understand right
now, not for something it can read in the snapshot.

### 15.4 Opportunities: at most 3, facts only

The opportunities section carries at most 3 mechanisms entries,
each one line: facts plus a query route, never a suggestion, never
a pause. Ignoring one costs nothing. Examples of what qualifies:

- "Mechanisms: 0 in stock, 2 stonefall traps waiting to be built.
  Query /v1/mechanisms for the trap list."
- "Bridge built, lever not linked. Query /v1/mechanisms for the
  link state."
- "Ballista built, 0 ballista arrows in stock. Query
  /v1/mechanisms for ammunition."

An opportunities entry fires only when the fact is actionable
and the snapshot alone does not already say it. A mechanic's
workshop with jobs queued is not an opportunity; it is the
snapshot doing its job. The entry never names the action to take
and never carries a cost estimate. The model decides.

### 15.5 What the system deliberately does NOT push, and why

- **The full mechanism list.** The snapshot names counts by
  material and by commitment. Where each mechanism sits is
  journal data, pulled by query when the model needs it. A list
  of every mechanism every tick is a dump.
- **Per-trap mechanism history.** Which mechanism went into which
  trap, and when, is journal data. The snapshot says how many
  traps are armed and how many are jammed. The history is there
  when the model asks why a trap is empty.
- **The whole job queue.** The snapshot says "2 jobs queued
  (mechanisms)". The full queue, with job ids and positions, is
  behind the workshop query route. A queue dump would grow with
  every job the fort queues.
- **Linkage diagrams.** The snapshot says "Bridge: raised, lever
  linked". The full linkage graph (which lever links to which
  devices, which mechanism sits at which end) is behind GET
  /v1/mechanisms. A graph dump would grow with every link.
- **Firing-lane geometry.** The snapshot never draws the firing
  arc. The arc is site data, checked when the engine is placed
  and when it is ordered to fire. Pushing it every tick would
  grow the snapshot with the map, which breaks the index.
- **Placement suggestions.** The snapshot never says "put a trap
  here" or "build the bridge there". Placement is the scored site
  system, and the model asks for a site when it decides to place
  something. The presentation gives the model what it needs to
  decide, not a script to follow (HARNESS_ROLE.md).

## 16. Refusals

The harness refuses these, and says why in plain words when asked:

1. Never build a mechanic's workshop or a siege workshop out of
   economic stone. The workshops take non-economic building
   material, and the harness checks before it builds.
2. Never queue a traction bench until the rope or chain, the table,
   and the mechanism all exist. A job that cannot start is a job
   that blocks the queue.
3. Never offer the bolt thrower. It does not exist in 0.47.05.
   Any v50 text about it is ignored.
4. Never promise a working drawbridge, lever, or linked trap
   until the link is verified live by a pull that moves the
   device. A lever with no link is decoration, and the snapshot
   must say so.
5. Never let the mechanism stock hit zero while traps are waiting.
   Mechanisms are the one item every defense and every machine
   needs, and an empty mechanism stock is a defense failure, not
   a quiet zero.
6. Never spend the trap mechanism stock on gears or links while
   traps are waiting to be built or re-armed. The mechanism floor
   is a budget, and the budget is enforced.
7. Never claim a stone job, a mechanism job, or a siege job works
   until a real item has been made and read back. A job type name
   from the fixture is not proof the game accepts it, and a
   manager order that sits unvalidated is not proof the game
   dispatched it.
8. Never claim a mechanism, floodgate, or bridge is magma safe
   because the stone's name sounds like it should be. Magma
   safety is a melting point in the raws, and the harness checks
   the number.
9. Never lower a drawbridge blind, and never retract a bridge
   with dwarves on it. A lowering bridge destroys what is under
   it, and a retracting bridge tosses what is on it.
10. Never fire a siege engine while a dwarf is downrange, and
    never place an engine whose firing arc crosses a corridor
    dwarves use. A ballista kills friend and foe alike.
11. Never use a fake link as if it were a real one until a live
    pull has moved the device. A link made without a job has no
    failure mode the game understands, and the harness proves it
    works before it relies on it.
12. Never offer wooden ballista arrows as the defense plan. They
    are a training consumable at most. A ballista is a weapon
    only when it has metal arrows.
13. Never queue a siege engine build before the 3 parts exist,
    and never set an engine to fire before ammunition exists for
    it. An engine with no parts is a hole in the floor, and an
    engine with no ammunition is a statue.

## 17. Implementation phases

Each phase ends with a live-verification bar. A phase that cannot
be verified live is logged as unverified and re-attempted, per the
standing rule. Nothing unverified gets pushed. Phases run in
order, and no phase starts before the composed-task framework in
ADVANCED_MECHANICS.md section 0 lands, because the mechanism
tasks are composed tasks.

### Phase 1: Mechanic workshop, mechanism jobs, mechanism counts

- Add `mechanic` to `WORKSHOP_CATALOG` (3x3, material BOULDER),
  with a placement affinity row for a stone stockpile at 25, the
  same as the mason's.
- Add the hardcoded job shape to `JOB_SPECS` (shared with
  STONEWORKING.md phase 2): a `job_type` name with no
  `reaction_name`. Add `make_mechanism` (`ConstructMechanisms`,
  1 boulder) and `make_traction_bench` (`ConstructTractionBench`,
  1 mechanism plus table plus rope or chain), with the material
  fail-fast through `materials.py`.
- Surface mechanism counts in the assembler: `TRAPPARTS` units
  from `items.by_type` into the Stocks line or the new Mechanisms
  section (section 15.1), with the stone and metal split from
  the material breakdown.
- Live bar: on the scratch fort, a mechanic's workshop is built
  by `build_workshop` and read back in the buildings list with
  subtype Mechanics and its id; a mechanic queues 1 mechanism
  from 1 boulder and the mechanism is read back in stock by type
  and material; the snapshot prints the mechanism count. A job
  queued with no stone in stock fails fast with the material
  named.

### Phase 2: Trap creation and trap state

- Generalize `act_build.lua` with a type-aware subtype lookup:
  `df.workshop_type` for Workshop, `df.trap_type` for Trap,
  `df.siegeengine_type` for SiegeEngine, no subtype for Bridge
  (direction instead). Add a `build_trap` action (kind stonefall,
  weapon, cage; site from placement) and a `build_lever` action
  (1 mechanism) on the same route.
- Resolve the cage discrepancy live: build a cage trap, confirm
  the construction job takes only the mechanism, confirm the
  `LoadCageTrap` job then loads a cage from stock, and record
  which side was right.
- Add a trap-state probe: a Lua read of `building_trapst` fields
  (loaded, contents, jammed, linked mechanisms) for each Trap
  building, plus the Trap subtype, surfaced in the buildings
  section or a new trap section.
- Live bar: on the scratch fort, a stone-fall trap is built at a
  placement site and its loaded stone is read back; a weapon
  trap is built with 1 weapon and read back; a cage trap is built
  and its loaded cage is read back; the trap-state probe reports
  armed, empty, and jammed correctly against hand-checked traps.
  A trap built with no mechanism in stock fails fast with the
  material named.

### Phase 3: Levers, pressure plates, pull, and link observation

- Add a `pull_lever` action: create a `PullLever` job on a lever
  building, verify the lever state flips, and read back the
  linked device state where the device reports one.
- Add a `build_pressure_plate` action on the trap route, and
  determine live what trigger configuration a plate built
  through `constructBuilding` gets by default (section 7).
  If the default is wrong or unset, the phase reports that and
  does not offer plates until a configuration route exists.
- Add link observation: read `linked_mechanisms` on levers and
  plates, and the `BUILDING_TRIGGERTARGET` general refs on
  linked devices, into the mechanisms query route.
- Add the mechanism floor to the planner (starting floor 3, tuned
  live): the fort does not spend below the floor on gears or
  links while traps wait.
- Live bar: on the scratch fort, a lever is built and read back;
  a `PullLever` job completes and the lever state flips; the link
  observation reads an empty `linked_mechanisms` vector on the
  unlinked lever; a pressure plate is built and its default
  trigger configuration is read back and recorded.

### Phase 4: Linking (the hard phase)

- Probe the `LinkBuildingToTrigger` job first: create the job on
  a lever with the target building as `triggertarget` and two
  mechanism items as job items with roles `LinkToTarget` (device
  end) and `LinkToTrigger` (trigger end), and let a mechanic work
  it. Read back the link with the phase 3 observation. If the
  game accepts, validates, and dispatches the job, that is the
  route.
- If the job route fails, fall back to the `fake_linking` end
  state (section 6.4): move the mechanisms into the buildings,
  insert the general refs, insert into `linked_mechanisms`, set
  `door_flags.operated_by_mechanisms` for doors and hatches. Then
  prove live that a fake-linked device responds to a pull.
  If neither route produces a device that moves on a pull, the
  phase reports that specific failure with the evidence, and no
  drawbridge is promised.
- Add a `link_lever` action on whichever route works, with the
  magma-safe mechanism placed at the device end when the device
  is hot, and the choice recorded.
- Live bar: on the scratch fort, a lever is linked to a door; a
  pull opens the door and a second pull closes it; the link is
  read back in the observation (`linked_mechanisms` populated,
  target ref present); the mechanism counts drop by 2 and the
  stock accounting matches. Then the same bar for a floodgate
  and for a bridge (phase 5).

### Phase 5: Bridges, floodgates, hatches, grates under link control

- Add a `build_bridge` action on the `act_build.lua` route with
  width, height, and direction, and determine live what the
  direction value means for a bridge (raising direction) and
  which enum it comes from (section 19).
- Add a bridge site kind to placement: a gap or entrance to span,
  with the raising direction chosen by the site, not by the
  model. The site names the span, the anchor edge, and the
  material count from the tiles-over-four formula.
- Wire the composed defense task: build the drawbridge, build the
  lever, link them, verify by a pull that raises the bridge, and
  report the bridge state and link state in the snapshot
  (section 15.1, line 3).
- Floodgate, hatch, and grate placement already work from stock
  (section 13.3). This phase adds only their linking, through
  the phase 4 route, and the jam rule: a floodgate that refuses
  to close reports the obstruction, not a silent failure.
- Live bar: on the scratch fort, a raising bridge is built over
  a channel, linked to a lever, and a pull raises it into a wall
  and a second pull lowers it, each state read back; a floodgate
  is linked and a pull opens and closes it; a hatch is linked
  and a pull opens and closes it. A bridge built with the wrong
  direction is caught by the read-back, not by the model.

### Phase 6: Siege engines

- Add `siege` to `WORKSHOP_CATALOG` (3 building materials,
  footprint read off the live build), with a placement affinity
  row for a wood stockpile.
- Add the siege jobs to `JOB_SPECS` on the hardcoded shape:
  `make_catapult_parts` (`ConstructCatapultParts`),
  `make_ballista_parts` (`ConstructBallistaParts`),
  `assemble_ballista_arrow` (`AssembleSiegeAmmo`), with the
  material fail-fast (wood per part, wood per arrow, arrowhead
  plus wood for a metal arrow).
- Add a `build_siege_engine` action (type SiegeEngine, subtype
  Catapult or Ballista, 3 parts, direction), a siege-engine site
  kind (position plus direction plus a clear firing arc, with the
  arc checked against dwarf traffic), and a mode action once the
  phase 6 probe determines how mode is written.
- Live bar: on the scratch fort, a siege workshop is built and
  read back; 3 catapult parts are made and read back; a catapult
  is built on a firing lane and read back with its direction; it
  is loaded with stone (`LoadCatapult`) and fired
  (`FireCatapult`) at a target, and the stone is consumed; a
  ballista arrow is assembled and read back; a ballista is built,
  loaded, and fired. The firing arc is verified clear of dwarves
  before each shot. The 0.47.05 ranges and the firing-arc width
  are measured and recorded.

### Phase 7: Machine components and the mechanism budget

- Add a `build_gear` action (type GearAssembly, 1 mechanism) and
  an axle build action on the `act_build.lua` route.
- Add power-train observation: which gears, axles, and machines
  are connected and powered, read from the machine fields, so
  the snapshot can say whether a millstone or pump has power
  rather than merely existing. The exact machine fields are
  UNVERIFIED (section 19).
- Enforce the mechanism budget in the planner: mechanisms
  reserved for machines are counted separately from mechanisms
  reserved for traps, and the floor from phase 3 is enforced.
- Live bar: on the scratch fort, a gear assembly is built and
  read back; a windmill or water wheel powers a machine through
  it and the machine operates (a pump moves water or a millstone
  mills); the mechanism accounting shows the gear's mechanism
  separately from the trap stock.

### Phase 8: Upright spears, trap maintenance, and the composed defense task

- Add an upright spear/spike build action on the
  `building_type.Weapon` route (section 10.2), with 1 to 10
  spears or spikes from stock, and link it through the phase 4
  route when it is automated.
- Add the trap maintenance loop: forbid traps during a siege,
  unforbid them when it is safe, report jammed weapon traps and
  empty cage and stone-fall traps as attention entries, and track
  which traps have been observed sprung so the harness can tear
  them down and rebuild them elsewhere after a siege
  (MILITARY.md section 9).
- Add the composed defense task: build the trap line at the
  placement sites, build and link the drawbridge, verify by pull,
  and report the whole defense state in the snapshot.
- Live bar: on the scratch fort, an upright spike trap is built
  and read back as a Weapon building; a weapon trap is jammed by
  a kill and the harness reports it jammed, then a mechanic
  cleans it (`CleanTrap`) and the harness reports it clean; a
  stone-fall trap fires and is re-armed (`LoadStoneTrap`) and the
  harness reports it armed again; the composed defense task runs
  end to end on a scratch fort and the snapshot reports the
  defense as ready only after the link pull has moved the bridge.

## 18. Cross-doc conflicts flagged

1. **Screw pump mechanism cost: STONEWORKING.md is wrong.**
   STONEWORKING.md section 9.4 says "A screw pump needs a
   mechanism." ADVANCED_MECHANICS.md section 2 says a screw pump
   needs 1 block, 1 enormous corkscrew, and 1 pipe section, and
   the wiki Screw pump page agrees. No mechanism. This doc
   follows ADVANCED_MECHANICS.md section 2. STONEWORKING.md
   section 9.4 should be corrected to remove the mechanism from
   the screw pump line.
2. **Cage traps and megabeasts: MILITARY.md overstates.**
   MILITARY.md section 9 says a cage trap "holds any creature
   indefinitely, including trolls and megabeasts." The Trap page
   says titans and forgotten beasts are immune to traps entirely,
   except a webbed cage trap. MILITARY.md should be narrowed: a
   cage trap holds any creature that is not trap-immune, and
   titans and forgotten beasts need a webbed cage or another
   answer.
3. **Cage-trap construction inputs: resolved, pending live.**
   ADVANCED_MECHANICS.md section 4 leaves open whether a cage
   trap build needs a cage, because DFHack's table lists mechanism
   only while the wiki says a cage must be provided. This doc
   resolves it on paper (section 10.2): construction takes only
   the mechanism, and the cage is loaded afterwards by the
   `LoadCageTrap` job. The resolution needs the phase 2 live
   build before it is treated as proven.
4. **Upright spear building type: ADVANCED_MECHANICS.md does not
   note it.** ADVANCED_MECHANICS.md section 4 lists upright
   spear/spike traps under the trap types with the `b-t-u`
   shortcut. Quickfort builds them as
   `type=df.building_type.Weapon`, not `Trap` (build.lua line
   735). The build route and the observation differ from the other
   three trap types, and ADVANCED_MECHANICS.md section 4 should
   gain a line saying so.
5. **Linking precedents: ADVANCED_MECHANICS.md missed a lead.**
   ADVANCED_MECHANICS.md section 6 says no DFHack link-lever API
   was found and lists `fake_linking` and `lever.rb` as the only
   precedents. This doc found a third: the `LinkBuildingToTrigger`
   job type exists in the fixture, and advfort.lua has
   commented-out code to create it (section 6.4). ADVANCED_MECHANICS.md
   section 6 should gain the lead, and phase 4 of this doc probes
   it first.
6. **TASK_DEFS count drift: ADVANCED_MECHANICS.md is stale.**
   ADVANCED_MECHANICS.md section 0 says `TASK_DEFS` has only 5
   tasks. The code now has 6 (brew, cook, make_bed, make_barrel,
   gather, farm). Minor, but the count should be updated where it
   is stated.

## 19. Open questions

UNVERIFIED items, each with its live-verification bar. Nothing
here is asserted as fact; each is a question the phases answer.

1. **Forge-route metal mechanisms and weapons-grade metals.**
   Does the 0.47.05 forge route restrict metal mechanisms to
   weapons-grade metals, and does the manager-order route to a
   mechanic's workshop allow any metal? Bar: on the scratch fort,
   order a metal mechanism at a forge from a non-weapons-grade
   metal and from a weapons-grade metal, and order one through a
   manager order, and record which are accepted and which are
   dispatched.
2. **Manager-order dispatch without a manager.** Does the game
   validate and dispatch a `ConstructMechanisms` or
   `ConstructCatapultParts` manager order when no manager noble
   is appointed? Bar: create the order on the scratch fort with
   no manager appointed and watch for the job to appear and be
   worked.
3. **Pressure-plate default triggers.** What trigger
   configuration does a plate built through `constructBuilding`
   get, and can the harness choose trigger types and weight ranges
   through filters? Bar: build a plate through the route on the
   scratch fort, read back its trigger fields, and try to set a
   creature-weight trigger.
4. **Weapon-trap loading past the first weapon.** How are weapons
   2 to 10 added to a built weapon trap, and does
   `LoadWeaponTrap` cover it? Bar: build a weapon trap with 1
   weapon, then add 3 more through the candidate route and read
   back the trap contents.
5. **Link job acceptance.** Does the game accept a directly
   created `LinkBuildingToTrigger` job with roles `LinkToTarget`
   and `LinkToTrigger`, validate it, and dispatch a mechanic?
   Bar: phase 4 probe on the scratch fort, with the link read
   back and a pull moving the device.
6. **Fake-link validity.** If the job route fails, does a
   fake-linked device respond to a pull, and does the link survive
   save and load? Bar: fake-link a lever to a door on the scratch
   fort, pull it, save, reload, pull it again.
7. **Bridge direction.** What does the `direction` argument to
   `constructBuilding` mean for a bridge, and which enum supplies
   it? Bar: build bridges with each candidate direction on the
   scratch fort and read back the raising edge.
8. **Siege-engine direction and firing.** Is 0.47.05 orientation
   four-way or eight-way at build time, what does the `direction`
   argument take for a siege engine, and what are the true
   catapult and ballista ranges and firing-arc widths? Bar: phase
   6 live firing test with measured ranges and observed arcs.
9. **Siege-engine modes.** What are the exact 0.47.05 engine
   modes, and how is mode written through DFHack: a building
   field, or a job? Bar: build an engine on the scratch fort,
   read back its mode fields, set each mode, and observe the
   operator behavior.
10. **Siege workshop footprint.** Is the siege workshop 3x3?
    Bar: build one on the scratch fort and read back its width
    and height.
11. **Siege part inputs.** How many logs does one catapult part
    or ballista part take, and does `AssembleSiegeAmmo` take 1
    log per wooden arrow? Bar: queue each job with a counted
    stock and read back the consumption.
12. **Catapult minimum range.** Is there a 30-tile minimum range
    in 0.47.05? Bar: fire a catapult at a target closer than 30
    tiles on the scratch fort and observe whether it fires over
    it or refuses.
13. **Roller mechanism count.** How many mechanisms does a
    minecart roller need by length? Bar: build rollers of several
    lengths on the scratch fort and read back the mechanism cost.
    Deferred to the minecart work; recorded here only so the
    budget is not spent blind.
14. **Machine power observation.** Which fields report whether a
    gear, axle, pump, or millstone is powered, and can the harness
    read the power train? Bar: build a powered machine on the
    scratch fort and read back the candidate fields before and
    after power is connected.
15. **Bars build route.** What is the material filter for
    `BarsVertical` and `BarsFloor` through `constructBuilding`?
    Bar: build a set of bars on the scratch fort and read back
    the construction job and its inputs.
16. **Trap-state field names.** What are the exact
    `building_trapst` field names for loaded, contents, and jammed
    in the r8 df-structures, and are they readable from Lua? Bar:
    phase 2 probe against a hand-built trap with known state.
17. **Trap re-arming standing order.** Can the harness read or
    write the Trap Rearming standing order that gates cage-trap
    re-arming? Bar: find the order in the game state on the
    scratch fort and read it back.
18. **Lever state read-back.** Is the lever on/off state readable
    from `building_trapst`, and does it flip on a `PullLever`
    job? Bar: phase 3 probe on a built lever.
19. **Siege-engine building fields.** What are the
    `building_siegeenginest` field names for mode, direction, and
    loaded state in r8? Bar: phase 6 probe against a built engine.
20. **Bridge building fields.** What are the
    `building_bridgest` field names for direction and raised
    state in r8? Bar: phase 5 probe against a built bridge.

## 20. Failure modes

What goes wrong with these systems, and what the harness does
about each one. Each mode names the detection and the response;
a mode with no detection is a mode the harness has not built yet.

1. **Mechanism stock hits zero.** Detection: the snapshot line
   prints 0 and the stock-out briefing fires (section 15.3).
   Response: queue mechanism jobs before any other mechanic work,
   and hold gear and link spending at the floor (phase 3).
2. **A trap is built but never loaded.** Detection: the trap-state
   probe reports it empty (phase 2). Response: the maintenance
   loop reports it as an attention entry with the missing load
   named (stone, cage, or weapon).
3. **A weapon trap jams.** Detection: the trap-state probe
   reports it jammed (phase 2). Response: a mechanic cleans it
   (`CleanTrap`) once the area is safe; during a siege the trap
   is forbidden and the mechanic is not sent.
4. **A mechanic walks into a siege to reload a trap.**
   Detection: a load or clean job exists while a threat is near
   the trap. Response: forbid the trap, or burrow the mechanic
   away, until the threat clears (Trap page; phase 8).
5. **A lever is built but never linked.** Detection: the link
   observation reads an empty `linked_mechanisms` vector
   (phase 3). Response: the snapshot says "lever built, link
   unverified", never "defense ready", and the link is queued
   through phase 4.
6. **A link is made but the device does not move.** Detection:
   the pull verification reads the device state unchanged after
   a pull (phase 4). Response: the link is reported failed with
   the device and the lever named, and the harness retries the
   other route (job, then fake) rather than reporting success.
7. **A floodgate jams open on an object.** Detection: the gate
   refuses to close after a pull and the obstruction is read
   back (phase 5). Response: the harness names the object and
   orders it removed before the next pull.
8. **A drawbridge is lowered onto a dwarf or a large creature.**
   Detection: none, until it happens. Prevention: the harness
   never lowers a bridge without checking the tiles under it, and
   never lowers one while a creature of size 1,200,000 or larger
   is on it, because the bridge deconstructs (section 9.2).
9. **A siege engine fires downrange at a dwarf.** Detection:
   none, until it happens. Prevention: the firing arc is checked
   against dwarf traffic at placement and before every shot, and
   the arc is a restricted area (section 11.5).
10. **A magma floodgate or bridge melts.** Detection: the building
    disappears and its linked device deconstructs. Prevention:
    the harness checks melting points in the raws before it lets
    a magma-adjacent mechanism, floodgate, or bridge pick its own
    material (section 5).
11. **A siege engine is built with no ammunition.** Detection:
    the snapshot prints 0 arrows or 0 stone for the engine
    (section 15.1). Response: the engine is not set to fire, and
    the ammunition job is queued first.
12. **An operator flees and the engine stands unmanned.**
    Detection: the engine mode is firing but no operator job
    exists and no operator is at the engine. Response: the
    snapshot reports the engine unmanned rather than firing, and
    the harness does not count it as defense.
13. **A cage-trap prisoner escapes.** Detection: the "Something
    has emptied a cage!" announcement, read from reports, about a
    year after capture. Prevention: captured creatures are moved
    to the animal stockpile or dealt with long before a year
    passes; the harness does not leave a sprung cage trap
    unvisited.
14. **A gear is disconnected and the machine above it collapses.**
    Detection: the machine disappears after a lever pull.
    Prevention: a second, unconnected gear supports a machine
    that rests entirely on a linked gear (Gear assembly page).
    The harness never links the only supporting gear of a machine
    without that second gear in place.
15. **The link job is created but never worked.** Detection: the
    `LinkBuildingToTrigger` job sits unworked while a mechanic
    is idle. Response: the harness diagnoses it the same way as
    any unworked job (materials, path, labor) and does not report
    the link as done until the read-back confirms it.
