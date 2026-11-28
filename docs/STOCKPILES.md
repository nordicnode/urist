# Stockpiles and Item Management

Design record for the stockpile and item management system in the Urist
harness. This is the plan. Implementation follows it phase by phase, each
phase verified live against the real game before it counts as done. Anything
not verified against the wiki or the live game is marked UNVERIFIED.

Related docs: docs/TRADING.md (trade stockpile near the depot),
docs/FARMING_PLAN.md (seed stockpile rules, Bug 9004), docs/MILITARY.md
(armor and ammo stockpiles), docs/ANIMAL_HUSBANDRY.md (refuse from
butchering), docs/FISHING.md (fish cleaning and shells). This doc builds on
them and does not duplicate them. The scored placement of stockpiles is in
docs/SITE_SELECTION.md (queued work at the time of writing, not existing
work); this doc says WHAT the network looks like, that doc says WHERE each
piece goes.

## 1. Why stockpiles decide whether the fort works

A stockpile is where an item waits between being produced and being used.
That wait is the whole economy of the fort. Every workshop input, every
meal, every bolt, every seed passes through a stockpile, and every one of
those trips is a hauling job done by a dwarf who could be doing something
else.

The wiki puts it bluntly: efficient stockpile design is one of the most
critical aspects of overall fortress efficiency, third only to keeping
dwarves fed and protected, and a fortress with poor stockpile layouts will
grind to an FPS death faster than one designed well (Stockpile design).

Three failure modes dominate, and the system in this doc exists to prevent
all three:

1. **Distance.** An item hauled across the fort is an item nobody can use
   while it travels. A barrel of seeds dragged from the dining room to the
   farm is every seed in the fort, unavailable for planting, for the whole
   trip. Hauling distance is the efficiency killer (Stockpile design).
2. **Containers in transit.** While an item is being hauled, or is inside a
   container tasked for hauling, it cannot be used. If the hauling job takes
   a month, every item in that container is unavailable for a month. The
   classic case is seeds in a barrel (Stockpile design; Bug 9004).
3. **No room.** A full stockpile means items pile up where they were made.
   Workshops clutter and slow down. Food rots on the floor. Seeds never get
   stored and never get planted.

The harness owns this system. The agent never reasons about tiles,
containers, or link graphs. It gets counts, exceptions, and named options
with a one-line why. See section 12.

## 2. How stockpiles work in Dwarf Fortress 0.47.05

### 2.1 Creating one

A stockpile is a painted rectangle, 1 to 31 tiles on a side in the harness
action. Tiles that cannot hold a stockpile (wall, workshop, an existing
stockpile) are simply not part of it. Any movable item already sitting on
the painted tiles is automatically considered part of the stockpile, even
if the settings disallow that item, and it marks its tile full until it is
moved (Stockpile).

### 2.2 Categories

The game has 18 stockpile categories, each with its own settings subtree
(Stockpile). The harness action accepts exactly these names (verified live
on a fresh stockpile 2026-11-26):

food, wood, stone, refuse, furniture, animals, armor, bars_blocks, cloth,
coins, finished_goods, gems, leather, ore, sheet, weapons, ammo, corpses.

What each holds, in brief (Stockpile):

- **Food**: food of all kinds, plus seeds, lye, dye bags, venom, and other
  inedible plant and animal products. Drinks always in barrels or pots.
  Seeds in bags, which may go in barrels. Food never spoils while in a
  stockpile, though vermin may eat it.
- **Wood**: chopped logs. No bins or barrels. Goes near the fortress
  entrance and the carpenter, since logs travel far and take long to haul.
- **Stone**: rough stone and ore. No bins or barrels. Wheelbarrows strongly
  advised. Stones are extremely heavy; minimize hand-carried distance.
- **Refuse**: anything that can rot or is garbage. See section 8.
- **Corpses**: dead sapient beings and pets with no burial place. A morgue.
  Indoors, decaying bodies generate miasma.
- **Furniture**: finished furniture from carpenter, mason, mechanic, and
  other shops. No barrels or bins. Anvils, millstones, and querns count as
  furniture. Sand bags appear in furniture stockpiles unless forbidden.
- **Bars/Blocks**: smelted bars, cut blocks, plus ashes, potash, soap,
  charcoal, and coke. Bins hold up to 10 bars/blocks (the wiki's bin table
  says 12; the two numbers disagree, see section 15).
- **Finished goods**: craftsdwarf, clothier, and leather works products
  with armor level 0. Bins consolidate them. Keep splints, crutches,
  ropes, and waterskins in a separate stockpile or they will be sold by
  accident.
- **Armor**: armor level above 0, including shields. No filter for wear
  level. Bins hold them.
- **Weapons**: weapons of all types, including picks and trap components.
  Bins hold them.
- **Ammo**: ammunition for all ranged weapons except siege engines. Bins
  hold them.
- **Cloth**: woven cloth and thread. Bins hold them.
- **Leather**: tanned leather. Bins hold it.
- **Gems**: cut and uncut gems, raw glass, gizzard stones. Bins hold them.
- **Coins**: minted coins, thousands per bin.
- **Sheets**: paper and parchment. Bins hold them.
- **Animals**: caged animals not fixed to a location, plus empty cages and
  animal traps. No bins or barrels.
- **None**: accepts nothing. Useful as a staging trick: paint a (none)
  stockpile around a workshop, set it to give to the workshop, and the
  workshop processes the loose stone sitting there (Stockpile).

Settings have three columns: major category, subcategory, individual
item. The "all" and "none" buttons only affect entries currently listed,
not entries that belong to the same subcategory but are never displayed
(Stockpile). A stockpile set to a category first, then customized, keeps
non-listed types selected. The correct way to narrow a stockpile is to
forbid types first, then re-enable the wanted ones, and to check material
and quality columns too: selecting "beds" under Type alone does not make
a beds-only stockpile, because quality columns still register as
forbidden (Stockpile).

Two quality filters exist: **core quality** (the craftsdwarfship of the
item itself) and **total quality** (the best of the item, its components,
or its decorations). A finely-crafted dress from exceptional cloth is
fine core, exceptional total (Stockpile).

### 2.3 Containers

Each item or stack normally takes one stockpile tile. Containers
consolidate (Using bins and barrels):

- **Barrels and pots** hold food and drink. One barrel or pot holds up to
  60 total units of food, counting every unit in a stack. Foods never mix
  categories in one barrel: plants and meat never share. A barrel holds a
  single stack of alcohol. Seeds need bags first; the bags then go in the
  barrel. Without bags, one seed takes one tile.
- **Bins** hold most non-food items. Bin capacity by good: bars/blocks 12
  (the Stockpile page says 10, see section 15), bolts 400, coins 193
  stacks of 500, cloth 303, leather 45, small gems 305, thread 205.
- Empty bins live in a Furniture/Bins stockpile; empty barrels in a
  Furniture/Barrels stockpile. Every barrel- or bin-using stockpile tries
  to keep one empty container on hand for future use.
- The max bin, max barrel, and max wheelbarrow settings control how many
  containers a stockpile may use. The default is the number of tiles in
  the stockpile. Setting a limit to 0 disallows that container. Changing
  a stockpile's size or contents can reset these numbers (Stockpile).
- Heavy barrels and bins slow hauling. Make containers from light wood
  when possible; feather tree wood is the lightest. Metal barrels resist
  vermin, but there is no way to make dwarves prefer them for food.
  Container material also decides fire and magma safety (Using bins and
  barrels).

### 2.4 Give and take links

A stockpile takes from anywhere by default. Turn that off and it only
gives and takes from specified workshops and stockpiles (Stockpile).

- A stockpile can take from any number of other stockpiles. Two stockpiles
  cannot feed into each other, but larger loops are allowed. A loop of
  stockpiles giving to each other (A to B to C to A) makes dwarves haul
  forever (Hauling). The harness must refuse loops.
- Giving to a stockpile creates the equal and opposite take-from link in
  the other direction. Deleting one deletes both.
- When a stockpile takes from a workshop, items produced in that workshop
  become eligible to move. Items the stockpile does not accept sit in the
  workshop forever.
- A workshop set to take only from linked stockpiles takes ONLY from
  those. This is powerful and dangerous: link an ore stockpile to a
  smelter without also linking fuel and the smelter cannot smelt; link a
  plant stockpile to a still without also linking a furniture stockpile
  and the still has no barrels. Every input a workshop needs must have a
  linked source (Stockpile).

### 2.5 Wheelbarrows

Wheelbarrows let a dwarf move one item at full walking speed regardless
of weight, but the dwarf must walk to the stockpile to fetch the
wheelbarrow first, then to the item, then back. For light items that
extra walk costs more than it saves (Stockpile design).

- Stone stockpiles use wheelbarrows by default, for good reason. Boulders
  are so heavy a dwarf may spend weeks carrying one cinnabar boulder by
  hand (Hauling).
- Furniture is another good use: a granite statue weighs 156, a gold
  statue 1159.
- Wood is a bad use. Most logs weigh about 30, which does not slow an
  average dwarf. Forcing wheelbarrows increases time per log and reduces
  simultaneous log hauling jobs. Weak dwarves are slowed by logs; bar
  them from wood hauling instead (Stockpile design).
- Wheelbarrows are only used to haul stone TO a stockpile, and they limit
  the number of active hauling jobs to the number of available
  wheelbarrows (Hauling).
- The stone stockpile default is 1 wheelbarrow. Entering the custom
  settings with the count at 0 resets it to 1, even with no changes made
  (Stockpile).

### 2.6 What the game does on its own

- Dwarves place an item in the nearest empty spot in the stockpile, not
  counting obstructions, and stockpile the newest item first, which may
  not be the nearest (Stockpile).
- Tiles holding only forbidden items count as available space (Stockpile).
- A workshop's own worker gathers its raw materials; produced goods need
  a hauler with the right labor to leave the workshop, or the workshop
  clutters and slows down. Workers do not reliably clear their own
  workshops (Hauling).
- No stockpile for a type is sometimes better than a bad one: with no gem
  stockpile, the jeweler fetches fresh gems directly instead of waiting
  for them to be hauled. With enough haulers, stockpiles are generally
  better (Stockpile).

## 3. What the harness has today

Verified against the repo 2026-11-27. Everything in this section was read
from the code, not assumed.

### 3.1 Creation works

- `create_stockpile` (actions.py) is programmatic and verified live
  2026-11-26 (building #8): `dfhack.buildings.constructBuilding` with
  type Stockpile and abstract=true, then the category flag set on the
  stockpile's settings, then `dfhack.job.checkBuildingsNow()`. The site is
  verified first (probe_site.lua) and a site-not-free failure names a
  verified alternative. Size 1 to 31 per side. The 18 categories above are
  the accepted values.
- `constructAbstract` on a hand-built building CRASHED the game live
  2026-11-26 (probe31, DF-down incident). The rule stands: never call
  `constructAbstract` directly; always go through `constructBuilding`.
  The r8 `plugins.stockpiles.import/export_settings` are nil, so there is
  no settings-library route (GOAL.md step 2 remainder).
- Placement has five verification layers (terrain, occupancy, clear,
  overlap, reachability) and ranks by distance from the fort centre only.
  Scored placement (threat, cover, adjacency, traffic) is queued work
  under docs/SITE_SELECTION.md, which does not exist yet.
- The daemon keeps a placement cache with a food stockpile box: the first
  verified 5x5 stockpile site (daemon.py). The planner's only stockpile
  decision today is "create a food stockpile" when the fort has no
  stockpile at all and the verified box exists (planner.py).
- `ui.py` still has a keystroke `create_stockpile`, wired into the
  Planner as `_ui_stockpile`. No current decision uses it (the planner's
  food-stockpile decision uses the programmatic action, and `server/routes_actions.py`
  routes `create_stockpile` through the programmatic action). The ui path
  is dead weight that contradicts the no-keystrokes rule and must be
  confirmed unused and removed in phase 1.

### 3.2 The open sub-vector question

The category flag is what the action sets. The category's sub-vectors
(food.plants, food.meat, and so on) are left exactly as
`constructBuilding` leaves them (empty). Whether an empty sub-vector
blocks hauling is OPEN since 2026-11-26 (act_stockpile.lua): a plump
helmet spawned on the ground was not hauled to stockpile #8 in 25
seconds and no StoreItemInStockpile job was created, but the spawned item
may not have been registered by the game's hauling scan. The definitive
test is a NATURALLY occurring loose food item, a gathered plant, watched
to see whether it is hauled to the stockpile. It has not been run. The
r8 stockpiles plugin has no import_settings or library files, so the
sub-vectors cannot be populated from a preset. Phase 1 closes this: it
decides whether the harness needs a settings-write action at all.

### 3.3 What does not exist yet

- No settings write: no action sets sub-vectors, barrel/bin/wheelbarrow
  limits, or quality filters on an existing stockpile.
- No link actions: no take-from or give-to link can be created, read, or
  deleted through the harness.
- No forbid, dump, or melt action anywhere in the harness (verified by
  grep). The Stocks window discipline in section 9 has no harness route
  at all today.
- No garbage dump zone creation through the harness (garbage_dump is a
  zone kind in ZONE_KINDS, but no plan or task uses it).
- No stockpile audit: nothing checks for full, empty, orphaned, or
  mislinked stockpiles.
- No sizing policy: the only size ever created is 5x5, from the daemon's
  placement cache. Nothing expands a stockpile.

### 3.4 What the AI can see today

- `buildings.lua` lists every building with id, type, bounding box,
  centre, job count, and contained_items count. For stockpiles it carries
  NO category, NO fill fraction, NO links, and NO settings. One stockpile
  once broke the whole buildings section because stockpiles have no
  construction_stage field; the read is now best-effort.
- `stocks.lua` gives per-material counts of IN_PLAY items with trader-held
  goods excluded, empty barrel counts, and brewable flags. It says what
  the fort HAS, not where it sits or whether it is hauled in.
- The snapshot has no stockpile section. The agent cannot tell a full
  stockpile from an empty one, a fed workshop from a starved one, or a
  rotting backlog from a clean fort. That is the gap section 12 closes.

### 3.5 Cross-references already settled

- TRADING.md: finished goods go to a trade stockpile near the depot,
  placed by the scored site system, not blocking the main corridor; meals
  rot outside a food stockpile, so they are cooked close to the caravan
  season; the target value of goods in the trade stockpile is verified by
  stockpile counts.
- FARMING_PLAN.md: the seed stockpile sits in a ring of plots, barrels
  set to 0, one seed bag per tile; barrels on a seed stockpile cause
  cancellations and stalls planting (Bug 9004); the seed reserve rule
  (plot tiles plus 5 bank seeds) is never cooked or traded.
- Coordinator log 2026-11-27: stockpile #4 was rebuilt at (90,90)-(94,94)
  with food plus all 224 seed bits set during the farm investigation, and
  the re-test proved the stockpile was NOT the fix for 0 PlantSeeds jobs.
  A stockpile built after an autosave exists only in memory; a restart
  loses it. Stockpiles are part of the save, not of the harness.

## 4. The system design: the stockpile network

One stockpile is a box. The system is a network with a direction of flow.
Every item moves: production, intake, bulk storage, use. The harness
builds and maintains that network, and the agent only ever sees its
health.

### 4.1 Roles

Every stockpile in the fort has exactly one role. A stockpile with two
roles fills with the wrong things and serves neither.

- **Intake / feeder.** Small, no containers, takes from anywhere. Its job
  is to receive items the moment they exist, a few tiles from where they
  are produced, so the producer is never blocked and the hauling job is
  short. The classic cases are the seed stockpile by the farms and the
  armor feeder by the forges (Stockpile design).
- **Bulk storage.** Large, containers allowed, takes from links only, and
  linked to take from the feeder next to it. Its job is capacity. Bins
  and barrels live here, and only here, because a container in transit
  here costs little: the trip is a few tiles to the feeder.
- **Workshop feeder.** A small stockpile wrapped around a workshop, or on
  the z-level above or below it, holding exactly that workshop's inputs.
  The mason's stone, the still's brewable plants, the kitchen's food.
  The crafter takes a few steps instead of crossing the fort (Stockpile).
  A workshop with several inputs gets a feeder per input group, or one
  feeder whose settings cover exactly the input set.
- **Trade stockpile.** Finished goods and saleable surplus, near the
  depot, sized to the target trade value (TRADING.md). Nothing the fort
  still needs goes here: splints, crutches, ropes, and waterskins stay in
  their own stockpile.
- **Seed stockpile.** Feeder role, seeds only, barrels 0, one bag per
  tile, in the middle of a ring of plots (FARMING_PLAN.md). Never
  containers, never anything else.
- **Refuse and corpse.** See section 8. Outside the fort or behind an
  airlock, never in the traffic flow.
- **Specialized.** Ammo near the barracks, bars near the forge, cloth near
  the loom and clothier, gems near the jeweler. Each is a workshop feeder
  with a narrow settings subset.

### 4.2 The standard network, per industry

The wiki's production flowchart is the map (Stockpile design). The
network follows the flow of goods, not the shape of the fort.

- **Farm-centric.** Farms feed the kitchen, still, mill, and farmer's
  workshop; the mill and farmer's workshop feed the loom and dyer, which
  feed the clothier; seeds flow back from the still, mill, farmer's
  workshop, and dining rooms. Put these workshops and their stockpiles
  around each other. One source plant stockpile by the farms, no barrels,
  takes from anywhere. One plant stockpile by each consuming workshop,
  takes from links only, each holding only the subset that workshop uses:
  the still takes only brewable plants, the farmer's workshop only plants
  that process into thread (Stockpile design).
- **Wood.** Small wood stockpiles near the tree-felling areas feed one
  large primary stockpile near the carpenter, which feeds a small
  stockpile near the wood furnace (Stockpile). Wood stockpiles sit close
  to the fortress entrance and the carpenter (Stockpile).
- **Stone and metal.** Stone feeder by the mason and smelter, wheelbarrows
  on, bulk stone deeper in. Ore stockpile linked to the smelter AND a
  fuel stockpile linked to the same smelter, or nothing smelts. Bars go
  to a bins-allowed bar stockpile near the forge. One smelter is the
  melting smelter, so melt fractions accumulate (Melt item).
- **Butcher and tanning.** The tanner sits next to the butcher and takes
  hides directly from the shop, no hauling. A refuse stockpile taking
  corpses feeds the butcher. Useless by-products go to a refuse stockpile
  behind an airlock (Stockpile design).
- **Kitchen.** A food stockpile accepting meat, fish, raw edible plants,
  cheese, leaves, milled plants except dyes, fat, and cookable extracts;
  barrels at maximum; prepared food OFF unless the stockpile is the
  prepared-food store (Stockpile design). A separate barrel stockpile near
  the still keeps empty barrels coming.
- **Finished goods and trade.** Finished goods stockpile near the
  craftsdwarf workshop, bins on; a trade stockpile near the depot takes
  from it by link (TRADING.md).

### 4.3 Link rules

Links are the wiring. Wrong wiring starves a workshop or hauls the fort
in circles. The harness enforces these rules when it creates or changes
a link; the agent never edits links directly.

1. Flow goes one way: production to intake to bulk to use. A stockpile
   never takes from a stockpile it gives to.
2. No loops. A to B to C to A makes dwarves haul forever (Hauling). Any
   link that closes a loop is refused, with the loop named.
3. A workshop linked to take only from stockpiles must have EVERY input
   linked. Ore without fuel, plants without barrels, are the classic
   failures (Stockpile). The harness checks the input set before the link
   is made and refuses an incomplete set.
4. A feeder takes from anywhere; a bulk store takes from links only. If
   a bulk store takes from anywhere, haulers drag bins across the fort
   and the feeder is pointless.
5. A stockpile taking from a workshop only receives what its settings
   accept. Everything else sits in the workshop. The harness checks the
   workshop's outputs against the stockpile's settings before linking.
6. Links are never created to a full stockpile, and never from a
   stockpile that is itself fed by the target. The harness reads fill
   before linking.

### 4.4 Placement

Placement is the scored site system (docs/SITE_SELECTION.md, queued):
inside, near the consumer, not on the main corridor, covered when the
kind needs cover. The stockpile-specific rules, from the wiki:

- Feeders wrap the workshop or sit directly above or below it.
- Wood near the entrance and the carpenter. Stone near the mason and
  smelter. Food near the kitchen, still, and dining hall.
- Refuse outside or airlocked, never in traffic (section 8).
- Trade stockpile near the depot, not blocking the main corridor.
- Corridors carrying stockpile traffic are at least 2 tiles wide, 3
  better. A squeezed corridor costs pathfinding time on every trip
  (Stockpile design).
- No stockpile sits where its hauling route crosses the only path into
  the fort. A siege must never find the fort's food haul crossing its
  kill zone.

## 5. Sizing

A stockpile is sized from what it must hold, not from a fixed number.
The arithmetic is the design; the numbers come from the live fort.

### 5.1 Capacity arithmetic

- One tile holds one item or stack without a container.
- One barrel or pot holds up to 60 units of food. One bin holds 12
  bars/blocks, 400 bolts, 303 cloth, 45 leather, 205 thread, 305 small
  gems (Using bins and barrels). The Stockpile page says 10 bars/blocks
  per bin; the two pages disagree (section 15). The harness uses the
  smaller number when planning capacity and verifies live.
- A 5x5 stockpile is 25 tiles. With barrels, a 5x5 food stockpile holds
  up to 25 barrels, which is 1,500 food units in theory; in practice the
  fort's food flow, not the ceiling, decides the size.

### 5.2 Sizing rules per category

- **Food.** Population times per-dwarf consumption per season, plus one
  season of reserve, plus the drink floor (population times 5 per
  season, TRADING.md). A fort of 7 dwarves eating about 2 meals a season
  each needs about 14 meals a season (FISHING.md); the food stockpile
  must hold the raw inputs for that plus the reserve, and the barrels to
  hold them. When the stockpile is full and food is still on the floor,
  expand the stockpile or add a second one; never let food sit.
- **Wood.** Burn rate of the carpenter plus the wood furnace plus
  construction. Wood is bulky and containerless, so it is the category
  that most often needs floor space. Expand outward near the entrance
  rather than deeper in.
- **Stone.** Stone is the space hog: no containers, one boulder per tile,
  and digging produces it constantly. Size by dig rate, not by demand,
  and clear it by use (mason, mechanisms, crafts) or by dumping the
  excess. A stone stockpile that never drains is a sign the fort digs
  faster than it builds.
- **Refuse.** Grows with fort size and battle frequency. Small for a
  quiet fort; it must never be allowed to fill, because a full refuse
  pile means trash in the hallways and miasma in the air (Garbage
  disposal).
- **Seed.** Plot tiles of that crop plus 5 bank seeds (FARMING_PLAN.md).
  One bag per tile, no barrels, so the seed stockpile is exactly as many
  tiles as the reserve needs.
- **Finished goods and trade.** Sized to the target trade value for the
  next caravan (TRADING.md), not to production. Overproduction past the
  trade target is wasted hauling.
- **Bars, cloth, leather, gems.** Sized by the workshop that consumes
  them, in bins: one bin holds 12 bars, so a forge burning 2 bars a day
  needs a bin a week, not a room.

### 5.3 When to expand

The harness watches fill fraction per stockpile (section 12) and acts on
thresholds, not on a fixed schedule:

- **Above 80% full** with items still arriving: expand the stockpile or
  build a second one of the same role nearby. The agent gets a named
  option with the reason.
- **100% full** with items on the floor: an attention entry, not a quiet
  number. Food on the floor rots; seeds on the floor never get planted.
- **Below 20% full** for a season with no arrivals: the stockpile is
  oversized or its source is dead. The harness says which, and whether
  to shrink it, move it, or fix the source.
- The Quickstart guide's rule of thumb, stockpile rooms about 11x11, is
  UNVERIFIED against this fort and this version. The harness sizes by
  the arithmetic above and verifies live; the rule of thumb is a sanity
  check, not a target.

## 6. Containers

Containers are capacity, and capacity in transit is unavailability. The
rules are per role, not per fort.

- **Feeder stockpiles: containers 0.** A feeder exists to receive and
  hand on quickly. A barrel in a feeder is a barrel that leaves with all
  its contents the moment a new item arrives (Bug 9004). The seed
  stockpile is the strictest case: barrels 0, always (FARMING_PLAN.md).
- **Bulk stockpiles: containers at maximum.** Bins for bars, bolts,
  cloth, leather, gems, finished goods, ammo. Barrels for food. The bulk
  store is where containers pay, because the trip to the feeder is a few
  tiles.
- **One empty container kept.** Every container-using stockpile tries to
  keep one empty barrel or bin for future use (Stockpile design). The
  harness counts empties and flags a stockpile with zero empties as
  unable to receive.
- **Bin reassignment is automatic and ignores settings.** A non-empty bin
  is always assigned to a stockpile that allows it, even if that
  stockpile takes from links only, and even if the bin came from
  somewhere else (Using bins and barrels). Deleting a stockpile
  reassigns its bins immediately. The harness must expect bins to move
  and must never assume a bin stays where it was put. When two linked
  stockpiles share items, bins move up to the number of empty tiles in
  the target, which is how temporary linking cuts hauling (Using bins
  and barrels).
- **Barrel reassignment.** When barrels are short, the wiki's trick is to
  drop a stockpile's barrel limit, dump the contents of its barrels to a
  garbage zone, and let the empty barrels move to a furniture stockpile
  for reuse (Using bins and barrels). The harness must be able to do
  this deliberately, and must never do it to a seed stockpile.
- **Material.** Light wood for containers; feather tree wood is the
  lightest. Metal barrels resist vermin but cannot be targeted. Container
  material decides fire and magma safety (Using bins and barrels).
- **Wheelbarrows.** Stone and furniture: on, with a count the harness
  sets from the stockpile's traffic. Wood: off. Food: off. Remember the
  stone default of 1 and the reset-to-1 quirk when custom settings are
  entered (Stockpile).

## 7. Item flow and hauling

### 7.1 The flow

Production, intake, bulk, use. A workshop's outputs go to its feeder or
bulk store; its inputs come from its feeder; the feeder is refilled from
bulk or from the source stockpile. The agent sees the flow as health:
which feeder is empty, which bulk store is full, which workshop is
waiting on an input.

### 7.2 The in-transit rule

While an item is being hauled, or is inside a container tasked for
hauling, it cannot be used (Stockpile design; Bug 9004). The harness
treats in-transit items as unavailable in every have/need check. That is
why feeders have no containers and why bulk stores sit next to their
feeders: the unavailable window is a few tiles, not a season.

### 7.3 Hauling labor

Hauling is split by labor: stone, wood, item, food, refuse, burial,
furniture, animal, trade good, water (Hauling). The labor plan
(docs/LABOR.md, queued work) owns who hauls what; this doc owns what
they haul to and from.

- Dedicated haulers let specialists stay in their workshops. A dwarf
  hauling stone across the fort is a dwarf not making anything.
- Specialize by area where possible: food haulers around the kitchen and
  farms, stone haulers around the mines and furnaces, wood haulers around
  the carpenter. A hauler crossing the whole fort for one load is the
  failure mode (Hauling).
- Specialize by attribute: agility for wood haulers who walk far,
  strength for stone haulers who carry heavy boulders (Hauling).
- Trade good hauling has the highest priority of all hauling and can
  delay workshop jobs: a dwarf hauling an item to a workshop may take a
  trade-good job before resuming the workshop job (Hauling). The harness
  schedules trade hauling around production, never through it.
- Refuse and burial hauling expose dwarves to bodies, trauma, and the
  outside. Bar important or depression-prone dwarves from it (Hauling).
  Standing orders can forbid all the dead's bodies on death so haulers
  do not run into a fight; reclaim them later (Hauling).
- Food hauling priority: storing food in a stockpile outranks moving
  food already in a stockpile into a barrel (Hauling). The harness never
  re-barrels food while loose food waits.

### 7.4 Backlogs and clutter

- A backlog is a queue the fort cannot clear. The worst is food: prepared
  meals rot in the kitchen while haulers carry single seeds (Hauling).
  The harness reports backlog by category and the agent gets the fix:
  more haulers on that labor, a closer stockpile, or a paused source.
- Workshop clutter slows production. Outputs must leave the workshop.
  If a workshop's output stockpile is full or missing, the items sit
  there and the workshop slows (Stockpile). The harness flags a workshop
  with more than a few finished items still inside it.

## 8. Refuse, corpses, rot, and miasma

### 8.1 What goes where

- **Refuse stockpile**: corpses and body parts of non-sapient creatures,
  butchery and fishing by-products (bones, raw hides, shells), rotten
  things, withered plants, damaged furniture, tattered clothes, vermin
  remains (Refuse). Bones, hides, wool, hair, teeth, horn, shells, and
  skulls are resources, not trash: bone bolts and crafts, leather, yarn,
  shell armor and decorations, skull totems (Refuse). Sort usable refuse
  from rotting refuse with separate stockpiles, or the bone carver's
  material rots with the garbage.
- **Corpse stockpile**: dead sapient beings and pets with no burial place.
  A morgue. Undead former sapients count as non-sapient and go to refuse,
  not here (Refuse).
- **Garbage dump**: an activity zone, not a stockpile. Dwarves throw
  anything marked for dumping there, including valuables (Garbage dump).
  Use it for deliberate disposal, never as a refuse stockpile.

### 8.2 Miasma

Rotting items produce miasma, and only on subterranean tiles. Miasma
makes dwarves unhappy and spreads north, south, east, west, up, and
down, never diagonally, through grates and open doors, but not through
closed doors (Miasma).

- Food rots unless it is in a stockpile, a trade depot, the embark
  wagon, a minecart, being carried, or used as a reaction component.
  A barrel of meat left in a corridor rots. Milk, fat, tallow, flour,
  drinks, seeds, and rock nut paste do not rot. Raw fish rots no matter
  where it is stored: clean it fast (Miasma).
- Plants wither instead of rotting and produce no miasma.
- A refuse pile on the surface works: rotting items on Light Above
  Ground tiles do not generate miasma. A subterranean pile needs either
  a room with several doors as an airlock, a diagonal-only entrance,
  a channel to the sky (the tiles stay Light Above Ground even after a
  floor is built over them), a garbage chute long enough that miasma
  cannot climb it, or magma 3 z-levels below the dump point (Miasma;
  Garbage disposal).
- Refuse items lying outside the fortress are ignored by default. The
  standing orders toggle controls outside refuse collection, and it also
  controls dumped items outside (Refuse).
- On an evil biome, refuse can reanimate. Put the refuse pile on the
  part of the map that is not evil, and dispose of corpses promptly,
  preferably in magma (Stockpile; Refuse).
- Sapient corpses in view horrify dwarves and can make merchants drop
  their goods and flee (Bug 7185, Refuse). Keep the corpse stockpile
  out of sight of the trade depot and the main corridor.

### 8.3 Disposal ladder

When the refuse pile fills, the harness escalates in this order, and the
agent approves the step:

1. Sort it: usable refuse to its own stockpiles, rotting refuse to the
   pile, nothing else.
2. Destroy it before it rots: butcher, tan, carve, and cook the usable
   parts promptly.
3. Dump it: garbage dump zone plus a chute, or an atom smasher (a
   drawbridge that pulverizes; keep the chute 2 or more z-levels deep,
   because it can toss trash back up, Garbage disposal).
4. Burn it: a magma pool at least 3 z-levels below the dump point, so
   there is no deadly magma mist (Garbage disposal).
5. A full refuse pile is an attention entry, not a number. Trash in the
   hallways means the pile failed.

## 9. Worn, damaged, and unwanted items

### 9.1 Wear

Wear is degradation over time, marked x, X, XX. One level of wear costs
806400 wear points. Value falls 100%, 75%, 50%, 25% across the levels,
then the item is destroyed (Wear).

- Clothing worn by a dwarf wears from normal use, regardless of
  material. Armor and weapons wear from combat, by material properties.
- Armor does not wear over time, UNLESS it is put in a refuse stockpile.
  Never store armor in refuse (Wear).
- Items of creature or plant material wear one level per 100 years even
  sitting in a stockpile. Artifacts never wear: their wear level is
  locked at zero, though they can still melt or boil (Wear).
- Worn clothing still sells. Sell it to caravans early, while it is
  still worth good money (Wear). A worn-clothing stockpile near the
  trade depot exists for exactly this, and it is kept separate from new
  clothing: there is no setting that stockpiles only new clothing, so
  new clothing is taken from the clothier's shop by a link-only
  stockpile, and worn clothing goes to a take-from-anywhere stockpile
  (Stockpile).
- Worn clothing issued as a military uniform is NOT replaced (Bug 6039).
  The harness must watch uniform wear and reissue, not assume the game
  does it (Wear; MILITARY.md).

### 9.2 Melt

Metal items melt at a smelter with the furnace operator labor, recovering
a fixed percentage of the metal per item type, from 10% to 150% or more
(Melt item).

- Recovery is counted in tenths of a bar, per smelter, per metal, and
  fractions are not shared between smelters. Ten tenths make a bar. If
  the smelter is torn down, the fractions are lost. Designate one smelter
  as the melting smelter, per metal where it matters, so fractions add
  up (Melt item).
- An item marked for melting AND forbidden is NOT melted. Melting a
  container does not melt its contents; they are left in the smelter
  (Melt item).
- Melt the worn, the damaged, and the surplus metal the fort cannot use.
  Never melt artifacts, never melt the last tool of a kind, never melt
  mandated items.

### 9.3 Dump and forbid

- **Dump** marks an item to be carried to a garbage dump zone. Bulk
  dumping marks everything on the tiles, including built furniture and
  building components, which take effect on deconstruction (Garbage
  dump). Dumping is deliberate and named: the harness dumps a named
  list, never a rectangle of whatever happens to be there.
- **Forbid** makes an item invisible to workshops and haulers. Forbidden
  items are ignored for tasks, which is why a workshop can report
  "needs unrotten item" while rotten ones sit nearby (Miasma). Forbid
  is also the fix for a cancellation loop: if a dwarf hauls an item
  whose destination became unreachable, the dwarf spams cancellations
  until the item is forbidden (Bug 597, Hauling).
- Standing orders can forbid all the dead's bodies and items on death,
  so haulers do not run into a fight. They must be reclaimed later or
  the bodies rot (Hauling).
- **Never fake a shortage by forbidding stocks.** Forbidden items do not
  count for have/need checks, so forbidding a stock makes the fort look
  poorer than it is and the harness will buy or make what it already
  has. This is a refusal (section 13), carried over from TRADING.md.

### 9.4 Masterworks and artifacts

- Disposing of a masterwork causes an unhappy thought in its creator.
  Trade masterworks to a caravan instead of destroying them (Garbage
  disposal).
- Artifacts cannot be dumped. The way to remove an artifact from a bin
  is to display it on a pedestal (Using bins and barrels). Artifacts
  never wear, never rot, and must never be sold, melted, or forbidden
  away. The harness keeps an artifact list and refuses any action that
  touches one.

## 10. Stockpile settings per category

The default settings for each stockpile the harness builds. A setting
not listed here is the game's default for that category. Where the wiki
is silent, the entry says so and the phase that proves it is named.

| Stockpile | Containers | Wheelbarrows | Key settings | Notes |
|---|---|---|---|---|
| Food, general | Barrels max | Off | Subsets per use, prepared food off except the prepared store | Vermin eat food in stockpiles; metal barrels resist vermin but cannot be targeted |
| Food, seeds | Barrels 0, bins 0 | Off | Seeds only, one bag per tile | Ring of plots around it (FARMING_PLAN.md); Bug 9004 |
| Food, brew plants | Barrels max | Off | Brewable plants only | Near the still; pig tail excluded if the cloth industry needs it |
| Food, kitchen | Barrels max | Off | Meat, fish, edible plants, cheese, leaves, milled plants except dyes, fat, cookable extracts; prepared food off | Near the kitchen (Stockpile design) |
| Wood | None | Off | Logs only | Near entrance and carpenter; logs travel far |
| Stone | None | On, count by traffic | Rough stone and ore | No bins or barrels; default 1, reset-to-1 quirk |
| Refuse, rotting | None | Off | Rotting refuse only | Outside, Light Above Ground, or airlocked |
| Refuse, usable | None | Off | Bones, hides, shells, skulls, teeth, horn | Near butcher and bone carver, not in traffic |
| Corpses | None | Off | Sapient corpses and pets | Morgue, out of sight of depot and corridor |
| Furniture | None | On for heavy pieces | Subset by type AND quality | Selecting a type alone is not enough (Stockpile) |
| Furniture, empty containers | None | Off | Empty bins and barrels only | So empties are findable when a stockpile needs one |
| Bars/Blocks | Bins max | Off | Bars, blocks, ash, potash, soap, charcoal, coke | Bins hold 12 by the bin table, 10 by the Stockpile page; plan on 10 |
| Finished goods | Bins max | Off | Crafts and goods, quality filter | Splints, crutches, ropes, waterskins in their own stockpile |
| Trade goods | Bins max | Off | Saleable surplus only | Near the depot (TRADING.md) |
| Armor | Bins max | Off | Armor level above 0 | No wear filter; new vs worn separated by workshop link only |
| Weapons | Bins max | Off | All weapons | Picks and trap components included |
| Ammo | Bins max | Off | Ammunition | 400 bolts per bin; near the barracks |
| Cloth | Bins 0 | Off | Cloth and thread | Near loom and clothier. Bins 0: the clothier ignores cloth in bins, so the feed stockpile must hold cloth loose (CLOTHING.md cross-doc correction) |
| Leather | Bins max | Off | Tanned leather | Near tanner and leather works |
| Gems | Bins max | Off | Cut and uncut gems, raw glass | Near jeweler |
| Animals | None | Off | Caged animals, empty cages and traps | No bins or barrels |
| Coins | Bins max | Off | Minted coins | Thousands per bin |
| Sheets | Bins max | Off | Paper and parchment | Near the library when it exists |

## 11. Special cases

- **Seeds.** The reserve rule, barrels 0, the ring layout, and the Bug
  9004 watch are in FARMING_PLAN.md. The stockpile system enforces
  them; it does not re-decide them.
- **Drinks.** Barrels hold one stack each. The brew check is EMPTY
  barrels, not total barrels: the fort once had 15 barrels with only 3
  empty (stocks.lua). A barrel stockpile near the still keeps empties
  coming.
- **Empty containers.** Empty bins and barrels live in a furniture
  stockpile so they can be found. A stockpile that needs a container and
  finds none is a blocked stockpile, and the harness says so.
- **Sand bags.** Bags filled with sand appear in any furniture stockpile
  unless expressly forbidden (Stockpile). The harness forbids them from
  the general furniture stockpile or they crowd out furniture.
- **Artifacts and mandated items.** Kept on a list the harness refuses to
  touch: never sold, melted, dumped, or forbidden. Mandated items are
  never traded away even when the trade stockpile is full.
- **Clothing.** New clothing and worn clothing are different stockpiles
  by construction (section 9.1). Worn clothing is a trade good; new
  clothing is fort supply.
- **Vermin.** Food in stockpiles attracts vermin. Cats help. Metal
  barrels resist vermin but cannot be targeted (Using bins and barrels).
  The harness reports vermin-eaten food as a loss, not as a mystery.

## 12. What the AI sees, and how

The agent never sees a stockpile's raw settings struct, a tile list, or
a link graph. It sees health, and it asks for detail. This is the same
discipline as the snapshot (assembler.py): counts and exceptions, full
detail behind a query, never a dump.

### 12.1 Observation to build

A new observation section, `stockpiles`, built from a Lua read of
`df.global.world.buildings.all` plus the stocks counts:

- Per stockpile: id, category, position, size in tiles, fill fraction
  (contained items and tiles used, computed from the building record),
  container counts (barrels, bins, wheelbarrows assigned), empties,
  link list (takes-from and gives-to, by stockpile id and workshop id),
  and a one-line settings summary (category plus any narrowed subset).
- Per category: total tiles, total items, fill fraction, and the count of
  items of that category sitting loose on the ground (unhauled).
- Exceptions: stockpiles at 100% with items waiting, stockpiles below
  20% with no arrivals for a season, workshops whose output stockpile
  is missing or full, feeders with zero empties, refuse piles with
  rotting items and no miasma-safe placement, worn clothing above the
  trade threshold, meltable metal above the smelter's fraction need.
- Loose items: counts by category of items on the ground with no
  accepting stockpile. A loose item with nowhere to go is a missing
  stockpile, and the harness says so by name.

### 12.2 The snapshot section

A compact Stockpiles block in the per-tick snapshot, in the same style
as the existing sections:

- One line per role that needs attention: "Food stockpile 87% full,
  12 meals unhauled" or "Stone stockpile full, 40 boulders on the
  floor". Quiet stockpiles are one line of counts.
- Full stockpiles, empty critical stockpiles (seed, food, drink
  barrels), and rotting backlogs are attention entries, ranked with the
  other problems, never buried in a list.
- The top stockpile need per tick is a named option with a one-line why:
  "Expand the food stockpile: 87% full and harvest is coming in" or
  "Build a stone feeder by the mason: the mason walks 60 tiles per
  stone". The agent picks; the harness has already done the arithmetic.

### 12.3 Query routes

- `GET /v1/stockpiles`: the full list, per-stockpile records as in 12.1,
  plus per-category rollups. Filterable by category and by role.
- `GET /v1/stockpile/<id>`: one stockpile in full: settings, links,
  contents summary by item type, fill history.
- `GET /v1/items?state=worn|forbidden|dumped|loose|unhauled`: the
  item-management view. Worn clothing by wear level, forbidden items by
  reason, loose items by category.
- The diary and history systems (docs/HISTORY.md, queued work) record
  stockpile events the same way they record everything else: expansions,
  new stockpiles, full stockpiles, and miasma incidents are dated events
  with causes, not silent numbers.

### 12.4 What the harness decides, what the agent decides

The harness decides: which stockpiles exist and their roles, their
settings, their links, their container counts, when to expand, and when
a pile is full. The agent decides: whether to build the named stockpile
now or later, which of two named sites to use, and whether to approve a
disposal step (dump, melt, atom smasher) that destroys value. The agent
never picks a tile, never writes a setting, and never edits a link.

## 13. Refusals

The harness refuses these, and says why in plain words when asked:

1. Never forbid stocks to fake a shortage. Forbidden items do not count
   for have/need checks, so the fort looks poorer than it is.
2. Never use a quantum stockpile. It is a developer-tolerated exploit
   (Quantum stockpile). The system works with real capacity, and the
   sizing rules in section 5 exist precisely so capacity is planned.
   A dump-zone quantum pile is not a stockpile design, it is a refusal
   to design one.
3. Never create a link loop. A to B to C to A hauls forever.
4. Never link a workshop to take only from stockpiles without every
   input linked. A starved workshop is worse than a slow one.
5. Never put containers on a feeder or seed stockpile. Bug 9004.
6. Never store armor in a refuse stockpile. Armor wears there and
   nowhere else over time.
7. Never sell, melt, dump, or forbid an artifact or a mandated item.
8. Never bulk-dump a rectangle of tiles. Dumping names the items.
9. Never put the refuse or corpse pile where its hauling route crosses
   the main corridor or the trade depot's sight line.
10. Never claim a stockpile works until a real item has been hauled into
    it and read back. A stockpile with an empty sub-vector may accept
    nothing, and the harness must prove otherwise (section 3.2).

## 14. Implementation phases

Each phase ends with a live-verification bar. A phase that cannot be
verified live is logged as unverified and re-attempted, per the standing
rule. Nothing unverified gets pushed.

### Phase 1: Close the sub-vector question and observe stockpiles

- Run the definitive test: a naturally occurring loose food item (a
  gathered plant) watched to see whether it is hauled to a
  category-flag-only stockpile. Record the answer in act_stockpile.lua
  and in this doc.
- Read stockpile settings, links, and fill from the live game (new Lua
  helper): category flag, sub-vector contents, barrel/bin/wheelbarrow
  counts, takes-from and gives-to lists, contained items vs tiles.
  Add the `stockpiles` observation section and the `GET /v1/stockpiles`
  route.
- Confirm the ui:create_stockpile path is unused and remove it, with
  the removal verified by grep and by the offline suite.
- Live bar: on the main fort, a gathered plant is hauled into the food
  stockpile and read back; /v1/stockpiles lists every stockpile with a
  true category and a true fill fraction.

### Phase 2: Settings write

- Build the settings-write action: set sub-vectors, barrel/bin/
  wheelbarrow limits, and quality filters on an existing stockpile,
  from the r8 settings struct as probed live. If a sub-vector cannot be
  written on r8, document the fallback (category-flag-only stockpiles
  plus per-workshop link discipline) and what it costs, and do not
  pretend otherwise.
- Live bar: a food stockpile narrowed to seeds-only by settings write
  accepts seeds and refuses plants, verified by a live haul.

### Phase 3: Link actions

- Build take-from and give-to link actions, with the phase-3 validation
  in section 4.3 enforced in code: no two-way feeds, no loops, complete
  input sets for workshops, no links to a full stockpile.
- Live bar: a feeder and a bulk store linked live, items move from the
  feeder to the bulk store, and a loop link is refused with the loop
  named.

### Phase 4: The network builder

- A composed task that builds a whole industry network at once: feeder,
  bulk store, links, and the workshop feeders, from the per-industry
  layouts in section 4.2. Planner integration: stockpile decisions
  beyond the first food pile, driven by fill fraction and by workshop
  input distance.
- Live bar: on the scratch fort, the farm-centric network is built by
  one task call; plants land in the source stockpile and the still's
  feeder, and the still brews from its feeder.

### Phase 5: Refuse, corpses, and disposal

- Refuse and corpse stockpile placement by the scored site system,
  airlock or outside placement, usable-refuse sorting, garbage dump zone
  action, and the disposal ladder in section 8.3.
- Live bar: a rotting corpse goes to the outside refuse pile, no miasma
  reaches the fort, and a miasma incident is reported as an attention
  entry with its cause.

### Phase 6: Worn and damaged discipline

- Wear observation (wear level per item, from the stocks read), melt
  designation and the melt-smelter rule, dump designation by named list,
  forbid and reclaim actions, and the worn-clothing trade rule.
- Live bar: a worn metal item is melted at the designated smelter and
  the fraction is read back; a worn clothing item is sold at the next
  caravan from the trade stockpile.

### Phase 7: Sizing and expansion policy

- Fill-fraction thresholds from section 5.3 wired into the planner and
  the snapshot, plus seasonal forecasting (harvest coming, caravan
  coming, migrants coming) so expansion happens before the pile fills.
- Live bar: a food stockpile crossing 80% during a harvest triggers the
  expansion option, and the expanded stockpile reads back with the new
  size.

### Phase 8: Audit

- A stockpile audit task: orphaned stockpiles (no role, no links, no
  arrivals), dead links (target deleted or full), misplaced stockpiles
  (refuse in traffic, wood far from the carpenter), and settings drift
  (a stockpile whose settings no longer match its role). The audit runs
  on demand and at season boundaries, and its findings are journal
  events.
- Live bar: the audit on the main fort finds at least one real issue
  and names it, or reports clean with the checks listed.

## 15. Open questions

All marked UNVERIFIED until a live probe or a wiki page settles them.

1. Whether an empty category sub-vector blocks hauling (section 3.2).
   The definitive natural-item test has not been run.
2. Whether sub-vectors, links, and container limits can be written
   through the r8 settings struct, and by which field names. The r8
   stockpiles plugin has no import_settings, so the write route must be
   probed directly.
3. Whether bin auto-reassignment on r8 ignores links and settings the
   way the v50 wiki describes. The v50 pages are the source; r8 may
   differ.
4. Bin capacity for bars/blocks: 12 (Using bins and barrels) or 10
   (Stockpile). The doc plans on 10 until a live count settles it.
5. Whether the game exposes per-stockpile fill directly or it must be
   computed from contained items against tiles.
6. Whether wear level is readable per item through DFHack on r8, and
   whether melt, dump, and forbid designations have a writable route
   (item flags) or need a different mechanism.
7. Whether a stockpile's settings survive a save and reload unchanged,
   and whether a deleted stockpile's bins reassign as the wiki says.
8. The Quickstart guide's 11x11 stockpile room rule of thumb: cited in
   the site-selection research, not re-verified against the wiki export
   or the live game.
9. Whether the fort's stone flow (dig rate vs mason consumption) makes
   the stone stockpile the binding constraint on digging, and at what
   population the stone pile needs a second room.

## 16. Sources

Wiki pages read from the local export
(`~/workspace/df-wiki-export/dfq.py`, hybrid search), in order of use:

- Stockpile (5,981 words): categories, settings, containers, links,
  custom stockpiles.
- Stockpile design (2,486 words): cancellation spam, double stockpile,
  single-source distribution, workshop layout, farm-centric and kitchen
  designs, wheelbarrows.
- Using bins and barrels (1,933 words): bin and barrel capacities,
  assignment behavior, reassignment tricks, container material.
- Hauling (2,327 words): hauling labors, specialization, backlogs,
  wheelbarrow limits, Bug 597, Bug 9004.
- Refuse (822 words): what refuse is, usable refuse, miasma avoidance,
  outside collection.
- Miasma (895 words): rot rules, spread rules, avoidance designs.
- Garbage disposal (478 words): refuse pile, landfill, atom smasher,
  incinerator, masterwork disposal.
- Garbage dump: dump zones vs refuse stockpiles, bulk dump rules.
- Wear: wear levels and values, what wears and what does not, Bug 6039.
- Melt item: smelter melting, fractional bars, designation rules.
- Stocks: the stocks window, bookkeeper record-keeping.
- Quantum stockpile (2,277 words): the exploit, documented here only
  to refuse it.

Harness state verified against the repo 2026-11-27: actions.py
`create_stockpile` and `STOCKPILE_CATEGORIES`, lua/act_stockpile.lua
(the open sub-vector question and the constructAbstract crash rule),
lua/buildings.lua (no category, fill, or links on stockpile records),
lua/stocks.lua (per-material counts, empty barrels, trader-held
exclusion), planner.py (the single food-stockpile decision), daemon.py
(placement cache, food stockpile box), ui.py (the unused keystroke
stockpile path), docs/TRADING.md, docs/FARMING_PLAN.md, docs/MILITARY.md,
and the coordinator log (stockpile #4 rebuild, farm re-test result).

## 17. Model presentation

This section is required by the 2026-11-27 presentation constraint
(GOAL.md, coordinator log 2026-11-27 ~17:47 PT): every new system
must state how its information reaches the model, what it costs,
and what it deliberately does not push. The snapshot stays an
index: counts, exceptions, and diffs only, about 4,700 tokens
typical, never a replacement for full state. Budgets hold (target
30K, warning 60K, compaction 100K, hard cap 140K on a 200K
window), enforced by the assembler's token accountant with its
cut order. No system bolts its own dump onto the snapshot.

Token costs below are computed from the exact section text with
the accountant's own rates (3 chars per token for the cap, 4 chars
per token on the wire). They are estimates until the coordinator
verifies them against the live assembler before commit. The
numbers are small because the section is an index: it names counts
and exceptions, and the detail lives behind queries.

### 17.1 Snapshot: the Stockpiles section

The snapshot section is specified in full in §12.2; this
subsection states its shape and cost, and does not repeat it.
The per-tick snapshot gains a compact Stockpiles block, built
from the fresh collect, in plain words. Two lines, in this
shape:

```
Stockpiles: food 87% full (12 meals unhauled), stone full (40 boulders on the floor).
Seeds 64%, drink barrels 3 empty, refuse: 2 rotting.
```

What is in it, and what is not:

- **Line 1, attention.** One line per role that needs attention,
  capped at 3 roles: full stockpiles, empty critical stockpiles
  (seed, food, drink barrels), and rotting backlogs. Quiet
  stockpiles are one line of counts. Full stockpiles, empty
  critical stockpiles, and rotting backlogs are attention entries,
  ranked with the other problems, never buried in a list (§12.2).
- **Line 2, counts.** Per-category fill fractions for the
  categories that matter this tick, capped at 4 categories, plus
  the loose-items count by category. A loose item with nowhere
  to go is a missing stockpile, and the harness says so by name
  (§12.1). The top stockpile need per tick is a named option
  with a one-line why (§12.2).
- **Diffs, not repeats.** When nothing in the section changed
  since the last tick, the assembler prints the short form
  ("stockpiles: unchanged"), the same way the Buildings section
  already does. The section costs its full price only on ticks
  when stockpile state actually moves.

**Token cost.** At 7 dwarves, the section as written above is
138 characters: about 46 tokens by the accountant's
3-chars-per-token rate, 34 on the wire. At 50 dwarves, with
more stockpiles and more categories, it is about 340
characters: about 113 tokens by the accountant, 85 on the wire.
The cost grows by about 40 tokens from 7 dwarves to 50, because
the section is capped: 3 attention roles maximum, 4 category
counts maximum. It does not grow with population, with the
number of stockpiles, or with the number of items in them. If a
future change makes it grow with any of those, the change is
refused until the section is capped again.

### 17.2 Query route: GET /v1/stockpiles (UNVERIFIED)

The routes are specified in §12.3; this subsection states the
presentation rule for them. GET /v1/stockpiles returns the full
list (per-stockpile records as in §12.1, plus per-category
rollups), filterable by category and by role.
GET /v1/stockpile/<id> returns one stockpile in full: settings,
links, contents summary by item type, fill history.
GET /v1/items?state=worn|forbidden|dumped|loose|unhauled returns
the item-management view. None of these routes exists yet; they
are part of the implementation phases in §14, and the snapshot
section above is written against them as design targets, not
against live routes.

The snapshot carries the summary and the ids; the routes carry
the detail. The agent asks a route when it needs to choose a
stockpile to expand, a link to fix, or an item to dispose of,
never as a matter of routine. Until the routes exist, the same
detail is behind GET /v1/stocks and GET /v1/buildings, which do
exist today.

### 17.3 Briefing: what arrives just in time

Stockpiles have no standing briefing. Two events carry one, both
from the existing briefing system (briefings.py), each a few
hundred tokens at most, each fired once when the event starts:

- **Critical stockpile empty.** Trigger: the seed, food, or
  drink-barrel stockpile hits zero. Cost: about 60 tokens by
  the accountant (UNVERIFIED: the briefing text has not been
  measured against the live briefing system). It covers which
  stockpile is empty and what the fort loses without it. It
  leaves the fix to §4 and §5.
- **Miasma from rot.** Trigger: rotting items in a refuse pile
  with no miasma-safe placement. Cost: about 55 tokens. It
  covers what is rotting and where. It leaves the disposal to
  §8.

No other stockpile event briefs the model. A stockpile filling
up, a new stockpile being built, or a link being set are
attention entries and opportunities entries, not briefings. A
briefing is for something the model needs to understand right
now, not for something it can read in the snapshot.

### 17.4 Opportunities: at most 3, facts only

The opportunities section carries at most 3 stockpile entries,
each one line: facts plus a query route, never a suggestion, never
a pause. Ignoring one costs nothing. Examples of what qualifies:

- "Stockpiles: food 87% full, harvest coming in. Query
  /v1/stockpiles for the fill."
- "Stone full, 40 boulders on the floor. Query /v1/stockpiles
  for the loose items."
- "Seed stockpile empty. Query /v1/stockpiles for the
  categories."

An opportunities entry fires only when the fact is actionable
and the snapshot alone does not already say it. A stockpile at
a healthy fill is not an opportunity; it is the snapshot doing
its job. The entry never names the action to take and never
carries a cost estimate. The model decides.

### 17.5 What the system deliberately does NOT push, and why

- **A stockpile's raw settings struct.** The agent never sees
  it (§12). It sees health, and it asks for detail. The
  settings summary is one line per stockpile behind the route.
- **Tile lists and link graphs.** No tile list, no link graph,
  ever (§12). The snapshot names the stockpile and its fill;
  the links are behind GET /v1/stockpile/<id>.
- **Per-item contents.** Which item sits where is behind the
  route, summarized by item type. The snapshot says how full a
  pile is and how many items are unhauled. A contents dump
  would grow with every item the fort owns.
- **Fill history.** The fill history of a stockpile is behind
  GET /v1/stockpile/<id>. The snapshot says the fill now. The
  history is there when the model asks why a pile filled.
- **Disposal as a suggestion.** The snapshot never says "dump
  this" or "melt that". Disposal destroys value, and §12.4
  reserves it to the agent's approval. The presentation gives
  the model what it needs to decide, not a script to follow
  (HARNESS_ROLE.md).
