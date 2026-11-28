# Stoneworking

Design record for the stoneworking chain in the Urist harness. This is
the plan. Implementation follows it phase by phase, each phase verified
live against the real game before it counts as done. Anything not
verified against the 0.47.05 game, its raws, or the harness code is
marked UNVERIFIED.

Related docs: docs/STOCKPILES.md (stone stockpiles, wheelbarrows,
containers, links), docs/TRADING.md (stone trade goods and values),
docs/MILITARY.md (traps, levers, defense), docs/ADVANCED_MECHANICS.md
section 4 (trap construction route, lever linking), docs/FARMING.md
(querns and millstones for milling), docs/LABOR.md (labor plan).
This doc builds on them and does not duplicate them. It says WHAT the
stone chain is and HOW the harness runs it; STOCKPILES.md says how the
stone is stored, MILITARY.md says how the traps are used.

## A note on sources, read first

The local wiki export (`~/workspace/df-wiki-export/dfq.py`) holds the
CURRENT wiki, not the 0.47.05 wiki. Its pages say "stoneworker's
workshop" and "stonecutter", which are v50 names. In 0.47.05 the
workshop is the mason's workshop and the skill is Mason. The local
export was used only to find pages; nothing in this doc rests on a
v50 page alone.

Every game claim in this doc rests on one of these instead:

- The DF2014 namespace of the wiki (the 0.47.05 pages), read live
  2026-11-27: DF2014:Mason's workshop, DF2014:Mechanic's workshop,
  DF2014:Craftsdwarf's workshop, DF2014:Stone crafter,
  DF2014:Jeweler's workshop, DF2014:Stone industry, DF2014:Workshop.
- The 0.47.05 raws in the install itself
  (`third_party/df_47_05/raw/objects/inorganic_stone_*.txt`), read
  2026-11-27: flux stone values, obsidian value, magma-safe melting
  points.
- The harness code, read 2026-11-27 (section 4).

Where a claim comes from the v50 wiki only, or from memory, it is
marked UNVERIFIED and the phase that proves it is named.

## 1. Why stoneworking decides whether the fort works

Stone is the one material the fort cannot run out of and cannot avoid.
Every tile dug out of the mountain drops stone, and every building the
fort needs is made of it. The chain is short: dig, haul, make, place.
When any link in it breaks, the fort stops in a way that looks like a
different problem. No mason's workshop means no blocks, and no blocks
means slow construction, and slow construction means the still, the
kitchen, and the bedrooms all wait. No mechanisms means no traps and
no levers, and no traps means the military is the whole defense.
No stone crafts means the first caravan leaves with nothing to buy,
and the fort stays poor for another year.

The wiki puts it plainly: a considerable industry centered on the use
of stone is essential for any fortress, both as a source of revenue
through trade and as a source of material and items critical for
building and construction (DF2014:Stone industry).

Three failure modes dominate, and the system in this doc exists to
prevent all three:

1. **Stone everywhere, usable nowhere.** Digging produces boulders
   faster than any dwarf can haul them. Loose stone clutters the
   mines, blocks corridors, and sits a hundred tiles from the
   workshop that needs it. A boulder on the floor is not a boulder
   in stock.
2. **The wrong stone in the wrong job.** Flux stone burned on cheap
   blocks is steel that will never exist. Obsidian spent on a
   floodgate is trade value thrown away. A mechanism made of
   ordinary stone melts next to magma and takes the floodgate it
   was linked to with it.
3. **No hands for the work.** Masonry, mechanics, and stonecrafting
   are three different labors on three different dwarves. One dwarf
   cannot do all three, and a mason pulled onto a squad is a mason
   the fort no longer has.

The harness owns this system. The agent never reasons about tile
types, job type numbers, or stockpile links. It gets counts,
exceptions, and named options with a one-line why. See section 10.

## 2. How stone works in Dwarf Fortress 0.47.05

### 2.1 Where stone comes from

Stone comes from four places (DF2014:Stone industry):

1. **Mining.** Loose stone and boulders are a byproduct of mining.
   There is a 25% chance that a section of natural stone that is
   mined will produce a stone boulder. Normal rock and ore deposits
   drop an average of 1 boulder for every 4 squares mined. Ore gives
   a boulder of ore, which smelts; ordinary stone gives a boulder
   of that layer stone.
2. **Trade.** Stone can be bought at the trade depot from visiting
   caravans. Specific types can be requested from the liaison,
   provided the home civilization or the trading race has access
   to it.
3. **Embark.** Stone can be bought at embark. This matters on an
   aquifer embark, where stone may be hard to get at first.
4. **Creatures.** A defeated gabbro man leaves one unit of gabbro,
   a defeated magma man leaves one unit of obsidian. Rare enough
   to ignore in planning.

Mining is the source that matters. The fort digs, and stone arrives
whether anyone wants it or not. The chain is therefore a disposal
problem as much as a supply problem: the fort must turn boulders
into blocks, furniture, crafts, and mechanisms at least as fast as
the miners produce them, or the mines clog.

### 2.2 Stone types and value

Stone has three base value levels (DF2014:Stone industry, confirmed
against the 0.47.05 raws 2026-11-27):

- **Value 1, the vast majority.** Ordinary layer stone: granite,
  gabbro, sandstone, and the rest. The bulk of every dig.
- **Value 2, flux stone.** Limestone, dolomite, chalk, and marble.
  Confirmed in `inorganic_stone_layer.txt`: each carries
  `[MATERIAL_VALUE:2]`. Flux is also the steel ingredient, so it
  is the one value-2 stone the fort must NOT burn on cheap goods
  (TRADING.md: keep flux for steel).
- **Value 3, obsidian.** Confirmed in the raws:
  `[MATERIAL_VALUE:3]`. The highest-value stone in the game, magma
  safe, farmable with magma and water, and the only stone that
  makes rock short swords.

Value is a multiplier on everything made from the stone. A statue
with base value 25 is worth 25 in granite, 50 in marble, 75 in
obsidian. Quality multiplies again on top of that, so a skilled
stonecrafter working obsidian or flux produces goods worth several
times the same item in ordinary stone.

A typical fortress has 6 to 12 specific layer stones, out of 25
layer stone types in the game (DF2014:Stone industry). Each layer
stone brings 1 to 3 secondary stones with it: veins and clusters
of low-value stone that mostly add color. The fort does not choose
its stone; the embark does. The harness must work with what the
survey finds, not with a wishlist.

### 2.3 Magma-safe stone

Mechanisms and buildings next to magma must be magma safe, or they
are destroyed and the building they belong to deconstructs
(DF2014:Mechanism). In 0.47.05, magma safety is a melting point
above magma temperature (12000). The raws give the answer directly.
The seven magma-safe layer stones, verified from
`inorganic_stone_layer.txt` melting points 2026-11-27, are:

| Stone | Melting point | Value |
|---|---|---|
| Sandstone | 12070 | 1 |
| Gabbro | 12160 | 1 |
| Basalt | 12160 | 1 |
| Quartzite | 12970 | 1 |
| Chert | 13101 | 1 |
| Obsidian | 13600 | 3 |
| Dolomite | 16507 | 2 |

Dolomite is the only flux stone on the list, which makes it the
best magma-safe mechanism stone that is not obsidian. Granite,
the most common layer stone, is NOT magma safe. A fort that builds
its magma floodgates out of whatever stone is nearest will lose
them. The harness must know which of the fort's stones are magma
safe before it lets a mechanism job pick its own material.

### 2.4 Economic stone

Some stone has uses outside the stone industry and is excluded
from it by default: ore, flux, plaster stone, fuel stone, and
obsidian (DF2014:Stone industry). The game calls these economic
stones. A mason will not touch them unless the fort enables stone
industry use for that type in the Stone use tab. The harness must
respect this: a mason's workshop with 40 hematite boulders in stock
and economic use off has no usable stone, and the snapshot must say
so rather than reporting "40 stone" and leaving the agent to
wonder why nothing gets made. The exact list of which stones are
economic on a given embark, and whether the harness can read or
write the Stone use flags through DFHack on r8, is UNVERIFIED
(section 13).

### 2.5 What stone cannot do

Stone cannot make beds, bins, barrels, buckets, cages, or pipe
sections (DF2014:Stone industry). The mason cannot build them,
and the craftsdwarf cannot either. The substitute for barrels is
the large stone pot from the craftsdwarf's workshop, which holds
drink the same way a barrel does and frees wood for beds and bins.
Clay boulders cannot be used in place of stone at the mason's
workshop (DF2014:Mason's workshop). A fort on clay with no stone
layer has no mason's workshop at all until it digs to rock.

## 3. The workshops: the authoritative 0.47.05 list

0.47.05 has 31 workshops: 14 first tier, 11 second tier, 6 third
tier (DF2014:Workshop). The stone chain uses four of them, plus
the jeweler's workshop as a stone sink. All four are 3x3. All four
can be built from any building material that is not economic stone.

### 3.1 Mason's workshop

Job requirement: Masonry. Built with any non-economic building
material. The full job list, from DF2014:Mason's workshop, read
2026-11-27:

- Construct rock armor stand, blocks, throne, coffin, door,
  floodgate, hatch cover, grate, cabinet, coffer, statue, slab,
  table, weapon rack, quern, millstone.
- Make rock bookcase, pedestal, altar.

Notes that matter for the harness:

- **Querns, slabs, and millstones can only be made here.** No
  other workshop makes them. A fort without a mason has no mill
  and no memorial slabs.
- **Altars need stone crafting, not masonry.** The DF2014 page
  notes this explicitly. An altar job queued on a mason's workshop
  still needs a stonecrafter to do it, and the harness must not
  count it as mason work.
- **Blocks are the training job and the construction material.**
  One boulder makes 4 blocks. Blocks have no quality levels, haul
  much faster than boulders, and are stored in bins. A novice
  mason mass-producing blocks is how the skill is trained
  (DF2014:Stone industry).
- **Clay boulders cannot be used here.** See section 2.5.
- Masons also build stone constructions directly: trade depots,
  bridges, furnaces, and wells are built with the Masonry skill,
  and their quality and value follow the mason (DF2014:Mason).
  Walls, floors, stairs, and roads use the wall/floor construction
  labor instead, even when made of stone blocks, and have no skill.
  The harness must not credit a mason for a wall or expect a wall
  to train one.

### 3.2 Mechanic's workshop

Job requirement: Mechanics. Built with any non-economic building
material. The full job list, from DF2014:Mechanic's workshop
(v50 page text, same two jobs as the DF2014 revision history):

- Make rock mechanisms.
- Make traction bench.

A traction bench needs a rope (from a clothier's shop) or a chain
(from a metalsmith's forge), plus a table, plus a mechanism. It
equips a hospital zone. It is a three-industry job: clothier or
forge, carpenter or mason for the table, mechanic for the bench
itself. The harness must not queue a traction bench until all
three inputs exist, or the job sits unworked.

Metal mechanisms are made at a metalsmith's forge or magma forge
from one bar, under trap components, and only from weapons-grade
metals by that route (DF2014:Mechanism, v50 page). Stone
mechanisms are the general-purpose kind: one boulder, one
mechanism, base value 30.

### 3.3 Craftsdwarf's workshop

Job requirement: one of bone carving, stonecrafting, or
woodcrafting. The stone jobs, from DF2014:Stone crafter, read
2026-11-27:

- Make rock large pot, crafts, toys, instruments, mugs,
  short sword, nest box, jug, hive.

Notes that matter:

- **Skilled stonecrafters make up to 3 small objects from one
  stone.** Crafts, mugs, and toys multiply with skill. This is
  why a legendary stonecrafter is worth more than three dabbling
  ones for trade.
- **Rock short swords need obsidian and wood.** Only sharpenable
  hard rock works, which in practice means obsidian, and the
  handle needs a log. A fort with no obsidian has no rock short
  swords, and the harness must not offer them.
- **Large pots replace barrels.** A large stone pot holds drink
  like a barrel and costs stone instead of wood. On a wood-poor
  map this is the difference between brewing and not brewing.
- **Nest boxes and hives** are the poultry and beekeeping inputs
  (ANIMAL_HUSBANDRY.md, and the beekeeping industry doc when it
  lands). Stone nest boxes and hives are the cheap versions.
- The workshop also engraves memorial slabs, makes bone and shell
  armor, wood and bone bolts, and extracts adamantine strands.
  Those are not stone jobs and belong to their own docs.

### 3.4 Jeweler's workshop

Job requirement: gem cutting or gem setting. The stone job, from
DF2014:Jeweler's workshop, read 2026-11-27: cut gems. Ordinary
stone can be cut here too. A cut ordinary stone always comes out
as a cabochon, not a cut gem, and it can then be used to encrust
furniture and finished goods. Cutting any stone, including clay
and ice boulders, is possible, which makes the jeweler's workshop
a stone sink and a training ground: gem setters train on cheap
cut stone before touching real gems, and excess stone can be
disposed of by cutting it. Flux stone and obsidian cabochons are
2 to 3 times as valuable as ordinary ones. The harness treats
stone cutting as a late-phase sink, not a core job: it burns a
dwarf's time for small value, and only pays when stone is truly
in excess or a gem setter needs training.

### 3.5 Quern and millstone: the milling link

The quern and the millstone are the milling workshops. Both are
built by the mason (the millstone item comes from the mason's
workshop; the quern item too). The quern is hand-powered and works
anywhere. The millstone needs mechanical power: a water wheel or
a windmill, plus the millstone building placed on top of the power
train. Milling turns cave wheat into flour, sweet pods into sugar,
dimple cups into dye, and rock nuts into paste and oil. The full
milling chain belongs to FARMING.md; this doc owns only the mason
side: the fort cannot mill at all until a mason has made a quern,
and it cannot mill at scale until a mason has made a millstone and
the power exists to turn it. Power (water wheels, windmills, gear
assemblies, axles) is machinery, not stoneworking, and belongs to
its own doc when it lands. The millstone job itself is in phase 2
of this doc because a millstone with no power is a dead building
and the harness must say so.

## 4. What the harness has today

Verified against the repo 2026-11-27. Everything in this section
was read from the code, not assumed.

### 4.1 The mason exists; the mechanic and the craftsdwarf do not

`WORKSHOP_CATALOG` (actions.py) has exactly four workshops:
carpenter, mason, still, kitchen. The mason entry is correct: type
Workshop, subtype Masons, 3x3, material BOULDER, and it was
verified live 2026-11-26 (the still accepts wood; the mason
needs stone). The mechanic's workshop and the craftsdwarf's
workshop are NOT in the catalog. `build_workshop` cannot build
either one today. The jeweler's workshop is not in the catalog
either.

`placement.py` already anticipates them: the affinity table has
rows for `("workshop", "Mason")` and `("workshop", "Craftsdwarf")`,
each wanting a stone stockpile at affinity 25, and the Mason row
is the only workshop row that names stone. Placement is ready;
the build action is not.

### 4.2 No stone job can be queued today

`JOB_SPECS` (actions.py) has exactly these jobs: brew,
brew_fruit, cook, make_bed, make_table, make_chair, make_door,
make_barrel, make_bucket, make_bin, make_chest, make_cabinet.
Every one is a still, kitchen, or carpenter job. There is no
mason job, no mechanic job, and no craftsdwarf job in the list.

The gap is structural, not just a missing list. Workshop item
jobs in this harness are REACTIONS: `job_type` 211
(CustomReaction) with a `reaction_name` from the raws. Mason,
mechanic, and craftsdwarf stone jobs are NOT reactions. They are
hardcoded job types in the game (Construct rock blocks, Make rock
mechanism, Make rock mug, and so on). The `queue_workshop_job`
action can only express reaction jobs, so it cannot queue a single
stone job even if the building exists. The fix is a second job
shape in JOB_SPECS: a hardcoded `job_type` name with no reaction.
The exact `df.job_type` names for the stone jobs are UNVERIFIED
until probed live against the running game (section 13).

The one existing route that CAN express a stone job today is
`manager_order_create` (actions.py, `act_order.lua`). It takes a
`df.job_type` name directly and creates a manager order, which
the game dispatches to any workshop that can do it. It was
verified live for a generic order, but no stone job type has been
passed through it, and whether the manager validates and dispatches
a mason job without a manager noble appointed is UNVERIFIED
(section 13).

### 4.3 The harness can already see stone, and can already dig it

- `stocks.lua` counts `stone_units` (BOULDER items in play) and
  `stone_stacks`, plus a `by_material` list of per-material counts.
  The snapshot's Stocks line already prints the stone total, and
  the Store tracks its burn rate and days remaining
  (assembler.py `_stocks`). What it does NOT carry is a per-type
  breakdown the agent can act on: the top-8 `by_material` list
  may or may not include the flux and obsidian counts, and there
  is no line that says "flux 14, obsidian 9" on its own.
- `survey.py` counts stone tiles by z-level and names the richest
  z-levels, from the survey scan. Mineral veins are reported as
  unidentified: ore identity is not in the tile type, so a vein is
  "mineral vein (unidentified)" until its boulders are mined and
  read. The same limit applies to stone: the survey knows how much
  rock there is and where, not which layer stone a given block is.
- `designate_dig` (actions.py, `act_dig.lua`) is the dig route,
  verified live, with real designations. Digging is how stone
  arrives. The dig-now shortcut is never acceptable (AGENTS.md).
- `build_furniture` (actions.py, `act_furniture.lua`) places
  furniture from stock: bed, table, chair, door, coffin, chest,
  cabinet, armor stand, weapon rack, statue, floodgate, hatch,
  grate. It takes the item from stock and consumes it with a
  Construct job. It does NOT know whether the item is stone or
  wood, and it has no quern or millstone kind: those are buildings
  the mason makes, not furniture items in `FURNITURE_ITEMS`.
- `act_labor.lua` enables or disables any `df.unit_labor` by name
  on one citizen, verified by read-back. Masonry, Mechanics,
  Stonecrafting, Mining, and Engraving are all labor names the
  action can already set. The labor plan (LABOR.md) owns who gets
  them; this doc owns what they produce.

### 4.4 Traps and levers: sites exist, creation does not

ADVANCED_MECHANICS.md section 4 is the record, verified against
the code 2026-11-27:

- Placement already computes trap sites (1x1, weapon, cage,
  stonefall). No creation action exists.
- `act_build.lua` hardcodes its subtype lookup to
  `df.workshop_type[...]`, so a trap subtype would error as
  "unknown workshop subtype". It needs a type-aware lookup
  (`df.trap_type` for Trap). The `act_furniture.lua` pattern
  (non-workshop types, `subtype=-1`) is the model; traps use a
  real subtype instead.
- The DFHack `buildings.lua` trap_inputs table lists mechanism
  only for cage traps, while the wiki says a cage must be provided
  for a cage trap. Which one is right is UNVERIFIED until a live
  build settles it.
- Lever linking is unresolved: no DFHack "link lever" API was
  found. `advfort.lua` fake_linking and `lever.rb` are partial
  precedents. MILITARY.md says the drawbridge plan must include
  the lever-link investigation and must not promise a working
  drawbridge until the link is verified live.
- Trap state (loaded, unloaded, contents, jammed) is not read by
  the harness today: `building_trapst` fields are not collected.
  The harness cannot tell an armed stonefall trap from an empty
  one.

### 4.5 What the agent can see today

- The snapshot's Buildings line names each workshop by subtype
  and id (Masons #12, for example), and says "Still: none" when
  there is no still. It does NOT name a missing mason, mechanic,
  or craftsdwarf workshop. The agent cannot tell from the snapshot
  whether stoneworking is possible at all.
- The snapshot's Stocks line prints the stone total and its burn
  rate. It does not print flux, obsidian, blocks, or mechanisms.
- The snapshot's Materials section (materials.py) knows the
  mason's build material (1 stone boulder) and the still's and
  kitchen's. It knows nothing about mechanism jobs, craft jobs, or
  traction bench inputs, because no JOB_SPECS entry exists for
  them to hang requirements on.
- The diary feed groups queued jobs by workshop, so a mason job
  queued through a manager order would appear under its workshop
  once the workshop exists. No diary work is needed for
  stoneworking beyond that.

## 5. The chain, end to end

The chain has five steps, and the harness must be able to run all
five without the agent thinking about tiles.

1. **Dig.** `designate_dig` opens rock. One boulder per four
   squares on average, 25% per tile. The survey says where the
   rock is and how much of it there is; the dig action says what
   it opened.
2. **Haul.** Stone hauling moves boulders to the stone stockpile
   by the workshops. Wheelbarrows on, containers off, feeder
   stockpile close to the mason and the mechanic (STOCKPILES.md
   sections 2.5, 4.2, 10). A boulder is heavy; a dwarf carrying
   one by hand across the fort is a dwarf doing nothing else for
   a long time.
3. **Make.** The mason, mechanic, and craftsdwarf turn boulders
   into products. One boulder per job, except skilled crafters
   making up to 3 small objects per stone, and blocks at 4 per
   boulder.
4. **Store.** Blocks go to a bins-allowed bars/blocks stockpile.
   Furniture goes to a furniture stockpile. Crafts and mugs go to
   a finished-goods stockpile, bins on. Mechanisms go to a
   furniture stockpile (mechanisms count as furniture) or their
   own stockpile by the traps. Large pots go where the still needs
   them. See STOCKPILES.md section 10 for the settings table.
5. **Place or sell.** Furniture is placed with `build_furniture`
   from stock. Blocks are consumed by construction. Mechanisms
   are consumed by traps, levers, and machines. Crafts and mugs
   go to the trade stockpile and out with the caravan.

The bottleneck moves. Early on it is hauling: the miners outrun
the haulers and the mason waits. Later it is labor: one mason
cannot keep up with a fort that wants a hundred blocks and twenty
pieces of furniture. Later still it is material choice: the fort
has a thousand granite boulders and no obsidian, and the trade
goods are worth a third of what they could be. The snapshot must
show which bottleneck is binding right now, not just that stone
exists.

## 6. Blocks and construction

Blocks are the workhorse product and the first thing a mason
should make.

- One boulder makes 4 blocks. Blocks have no quality levels, so a
  dabbling mason makes blocks exactly as good as a legendary one.
  That makes blocks the training job: a novice mason mass-producing
  blocks trains masonry without wasting good stone on bad
  furniture.
- Blocks haul much faster than boulders and store in bins. The
  DF2014 stone industry page says 5 blocks per bin. STOCKPILES.md
  says bins hold 12 bars/blocks by the bin table and 10 by the
  Stockpile page, and plans on 10. Three pages, three numbers.
  The true number is UNVERIFIED until a live count settles it
  (section 13). The harness plans capacity on the smallest number
  until then.
- Blocks are the construction material for walls, floors, stairs,
  ramps, and fortifications built from stone. A wall built from
  blocks goes up faster than one built from boulders, and the
  mason's skill does not apply to it: walls use the wall/floor
  construction labor, not masonry. The harness must not queue
  block-making as mason training and then wonder why the mason
  is still dabbling.
- The block stockpile is a bars/blocks stockpile near the
  construction front, bins allowed. When it is empty and the fort
  is building, the mason is the bottleneck. When it is full and
  the mines are still producing boulders, the fort is digging
  faster than it builds, and the answer is more construction or
  more crafts, not more digging.

## 7. Furniture: what the fort lives in

Furniture is the mason's largest product list and the one the fort
feels most directly. A bedroom needs a bed (wood, not stone), a
cabinet or coffer, and a table and throne. A dining hall needs
tables and thrones. A tomb needs a coffin and a slab. A temple
needs an altar and statues. The mason makes all of the stone
versions: tables, thrones, coffers, cabinets, weapon racks, armor
stands, doors, floodgates, hatch covers, grates, statues, coffins,
slabs, querns, millstones, bookcases, pedestals, altars.

The rules that shape the furniture plan:

- **Stone furniture is heavy.** A granite statue weighs 156
  (STOCKPILES.md). Furniture stockpiles want wheelbarrows on for
  the heavy pieces, and the furniture must be made near where it
  will be placed, or the hauling cost eats the benefit.
- **Quality matters for furniture and not for blocks.** A
  masterwork statue in a dining hall gives happy thoughts; a
  masterwork door does not matter much, but a masterwork throne
  in a bedroom does. The harness gives the good stone (flux,
  obsidian) and the skilled mason to the furniture that lives
  where dwarves spend time, and the novice mason and the granite
  to the floodgates and grates nobody looks at.
- **Doors, floodgates, hatches, and grates are access control.**
  A stone door is the fort's front door. A floodgate is the
  water control. A grate keeps creatures out of a channel while
  letting water through. These are built by the mason and placed
  by `build_furniture` from stock, and the harness must have
  them in stock before the fort needs them, not after.
- **Coffins and slabs are the death system.** A dead dwarf needs
  a coffin in a tomb, or the fort gets ghosts. A slab engraved
  with the dwarf's name, placed as a memorial, also lays a ghost
  to rest. Slabs can only be made at the mason's workshop, and
  engraving a memorial slab is a craftsdwarf's workshop job.
  A fort with no mason cannot bury its dead properly. The
  snapshot must flag "no coffin in stock" as an attention item
  when a dwarf has died, not as a quiet zero.
- **Statues are the cheap happy thought.** A statue in a dining
  hall or a temple raises the room value and gives dwarves
  something to admire. Obsidian statues are the best value per
  job in the chain. Statues are also a trade good (base 25),
  behind mugs and crafts.
- **Querns and millstones are the milling link.** See section 3.5.
  A quern is placed as a workshop; a millstone is placed as a
  building on a power train. Neither is in `FURNITURE_ITEMS`
  today, so `build_furniture` cannot place either one. That is a
  phase 2 gap.

## 8. Crafts, pots, and trade value

Stone crafts are the fort's first export. Stone is free and
unlimited on most maps, so stone goods are sold freely, with flux
as the exception (TRADING.md: keep flux for steel). The trade
ranking from TRADING.md section 6.1, base values before material
and quality multipliers:

- **Mugs, best.** Base 30 for a stack of 3. One boulder, one job,
  up to 3 mugs from a skilled crafter.
- **Crafts, next.** About 20. Figurines, amulets, scepters,
  crowns, rings, earrings, bracelets, and large gems, 1 to 3 per
  job from one stone.
- **Statues, then.** Base 25. One boulder, one statue, heavier
  to haul to the depot than mugs.
- **Mechanisms, best per bar for metal, and good for stone too.**
  Base 30, one boulder, one mechanism. Heavy, which hurts with
  races that bring no wagons, notably the elves.

The trade plan for a young fort is stone mugs and crafts first:
no inputs but stone and a craftsdwarf, and the production pipeline
starts the season before the caravan it serves (TRADING.md).
Obsidian is the most valuable non-ore stone when the map has it,
and obsidian mugs and crafts are the first thing a skilled
stonecrafter should make when the caravan is coming.

Large pots are not trade goods. They are fort supply: barrel
replacements for the still. A fort that sells its large pots to
the caravan has sold its drink storage. The harness keeps pots
out of the trade stockpile. Jugs are the small equivalent: they
hold honey, oil, and other liquids, and they are also fort supply
first.

Nest boxes and hives are fort supply too, for poultry and
beekeeping. Stone is the cheap material for both, and the harness
makes them to the animal plan's numbers, not to the trade target.

## 9. Mechanisms, traps, levers, and machines

Mechanisms are the reason the mechanic's workshop exists, and the
most load-bearing single item in the chain. One mechanism is base
value 30, one boulder, one job. Everything that moves in the fort
runs on them.

### 9.1 What a mechanism is used for

From DF2014:Mechanism, read 2026-11-27 (v50 page text, mechanics
unchanged from DF2014):

- Building a trap, a lever, a pressure plate, or a gear assembly
  needs one mechanism.
- Linking an object to a lever or a pressure plate needs two
  mechanisms per linked item: one for the linked object, one for
  the trigger. The only way to recover either is to deconstruct
  the linked object.
- Minecart rollers need multiple mechanisms depending on length.
- Building a screw press workshop needs two mechanisms.
- Mechanisms for use next to or in magma MUST be magma safe, or
  they are destroyed and the linked object deconstructs.
- Mechanism quality sets the attack skill of weapon traps and
  stonefall traps. It does not change jam chance or refire speed.
  Artifact mechanisms count the same as masterworks.

Mechanisms count as furniture for stockpiling, which has a sharp
edge: the jeweler's "encrust furniture with gems" job can encrust
mechanisms with gems instead of more useful furniture. The
harness keeps mechanisms in their own stockpile when the fort has
a jeweler, or accepts the occasional gemmed mechanism as the cost
of a shared pile.

### 9.2 Traps

The trap types, from MILITARY.md section 9 and ADVANCED_MECHANICS.md
section 4, which cite the DF2014 Trap page:

- **Stonefall trap.** The easiest to build: 1 mechanism plus 1
  ordinary stone. No lever. Must be re-armed after every use, and
  a mechanic reloads it automatically with a new stone. Good in
  numbers around intersections and stairways, and a good way to
  train a mechanic. The stone's weight affects damage, and it
  respects economic stone restrictions: it cannot be loaded with
  clay.
- **Weapon trap.** The gold standard. 1 mechanism plus 1 to 10
  weapons. All weapons attack at once. Resets automatically, but
  a kill has a 50% chance to jam the trap, and a mechanic must
  clean it. Crossbows in weapon traps do not jam but need bolts.
  Hammers jam less than swords or axes; spears jam the most.
- **Cage trap.** Never fails. 1 mechanism plus 1 cage. Captures
  the victim unharmed and alerts the fort to ambushes when it
  triggers on hidden invaders. Must be re-armed with an empty
  cage. Creatures with the trapavoid tag escape unless knocked
  unconscious or webbed.
- **Upright spear/spike trap.** 1 to 10 spears or spikes, no
  mechanism unless linked. Does not self-trigger and does not
  discriminate friend from foe.

The trap plan is the military's plan (MILITARY.md): traps at the
choke points between the concentric circles of defense, deadliest
closest to the fort. The stoneworking side of it is supply: the
fort needs a standing stock of mechanisms and ordinary stone for
re-arming, and the harness must not let the mechanism stock hit
zero while traps are waiting to be built or re-armed. A trap with
no mechanism is a hole in the floor.

### 9.3 Levers and linking

A lever without a link is decoration. Linking is the unresolved
piece of the whole chain (ADVANCED_MECHANICS.md section 4,
MILITARY.md section 9): no DFHack "link lever" API was found on
r8, and `advfort.lua` fake_linking and `lever.rb` are partial
precedents only. The drawbridge over the entrance stairwell is
the cheapest real defense in the game, and it needs a linked
lever. Until the link is verified live, the harness must not
promise a working drawbridge, and the snapshot must say "lever
built, link unverified" rather than "defense ready". The lever
itself is a building that takes 1 mechanism (ADVANCED_MECHANICS.md:
`trap_inputs[Lever]` = 1 mechanism). Building the lever is phase 3
work; linking it is phase 4, and the phase 4 bar is a live pull
that moves the bridge.

### 9.4 Machines

Gear assemblies, axles, screw pumps, water wheels, and windmills
are the machine system. A gear assembly needs a mechanism. A
screw pump needs a mechanism. The power train that turns a
millstone runs on them. Machines belong to their own doc when it
lands; this doc owns only the mechanism supply for them. The
harness counts mechanisms reserved for machines separately from
mechanisms reserved for traps, so a millstone project never eats
the trap stock.

## 10. Stone stockpiles and hauling

The storage rules live in STOCKPILES.md and are not repeated here.
The stoneworking-specific rules are:

- **Feeder by the mason, bulk deeper in.** A small stone
  stockpile wraps the mason's workshop (and the mechanic's, and
  the craftsdwarf's), wheelbarrows on, no bins, no barrels. The
  bulk stone stockpile sits deeper, fed by link from the feeder.
  The mason takes a few steps for stone instead of crossing the
  fort.
- **Sort by value, not by type.** The DF2014 stone industry page
  recommends stockpiles by value tier: low value (1), medium
  (flux, 2), high (obsidian, 3), and magma safe. Four piles, not
  twenty-five. Sorting by each stone type is only worth it when
  the fort controls furniture by color, which it does not yet.
  The harness builds the four-tier piles and links the magma-safe
  pile to the mechanic's workshop and to any mason making blocks
  for magma-safe construction, and the medium and high piles to
  the craftsdwarf's workshop and the mason making furniture.
- **Wheelbarrows on for stone, always.** Boulders are so heavy a
  dwarf may spend weeks carrying one by hand (STOCKPILES.md).
  Wheelbarrows are only used to haul stone TO a stockpile, and
  they limit active hauling jobs to the number of wheelbarrows.
  The stone stockpile default is 1 wheelbarrow, and entering the
  custom settings with the count at 0 resets it to 1.
  UNVERIFIED: whether the harness's `create_stockpile` action can
  set the wheelbarrow count at all. STOCKPILES.md section 3.3
  says there is no settings write anywhere in the harness, so
  today the answer is no, and the count is whatever
  `constructBuilding` leaves behind.
- **Blocks in bins, boulders on the floor.** Blocks go to a
  bars/blocks stockpile, bins allowed. Boulders never go in bins.
  A stone stockpile that never drains means the fort digs faster
  than it builds, and the fix is more mason work, not a bigger
  pile.
- **Loose stone is the clutter signal.** Stone on the mine floor
  with no accepting stockpile is a missing stockpile, and the
  harness says so by name (STOCKPILES.md section 12). The
  snapshot's loose-stone count is the number that says whether
  hauling is keeping up with digging.
- **Economic stone stays out of the mason's reach.** Ore goes to
  the smelter feeder, flux to the smelter feeder, plaster stone
  to the kiln. The mason's feeder takes ordinary stone only, so a
  mason never burns the steel flux on a door. How the harness
  enforces this before stockpile settings writes exist is an open
  question (section 13): the only lever today is which stockpile
  the workshop is linked to, and links do not exist yet either.

## 11. Engraving and smoothing

Engraving and smoothing are part of the stone industry but not
part of this chain. An engraver smooths stone floors and walls,
then engraves them with images, which raises room value and gives
dwarves happy thoughts. The labor is Engraving, the skill is
Engraver, and it needs no workshop and no material: the dwarf
works on the stone where it stands. It is cheap value, it trains
a skill the fort otherwise never trains, and it is the only stone
work that happens after construction instead of before it. It is
out of scope for the phases in this doc, which cover making things
out of stone, not decorating stone that is already placed. The
harness already supports the labor through `act_labor.lua`, and
a later doc can pick engraving up without touching this one.

## 12. Model presentation

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
verifies them against the live assembler before commit, as the
amendment requires. The numbers are small because the section is
an index: it names counts and exceptions, and the detail lives
behind queries.

### 12.1 Snapshot: the Stoneworking section

The per-tick snapshot gains a short Stoneworking section, built
from the fresh collect, in plain words. Three lines, in this
shape:

```
Stoneworking: stone 142 boulders (granite 61, gabbro 22, obsidian 9, flux 14), blocks 38 in bins, mechanisms 6.
Mason #12: 3 jobs queued (blocks). Mechanic #14: idle. Craftsdwarf #15: 2 jobs queued (mugs).
Traps: 2 stonefall armed, 1 weapon trap jammed, 0 spare mechanisms.
```

What is in it, and what is not:

- **Line 1, counts.** Total boulders in stock, with the four
  numbers that decide material choice: the most common stone, the
  magma-safe count, the obsidian count, and the flux count. Then
  blocks in bins and mechanisms in stock. These are counts, not a
  list: the fort has 25 layer stones and the snapshot never names
  all of them.
- **Line 2, workshops.** One short clause per stoneworking
  workshop that exists, capped at 3 clauses, then "and N more
  stoneworking workshops" when there are more. Each clause names
  the workshop subtype and id (so the model can queue a job
  without a query turn), its state (idle, or jobs queued with the
  job kinds), and nothing else. When no stoneworking workshop
  exists, the line says so and names the fix: "No mason's
  workshop. Build one: 1 stone in stock." A missing workshop is
  an exception, not a silence.
- **Line 3, traps.** Armed stonefall traps, jammed weapon traps,
  empty cage traps, and spare mechanisms. A jammed trap and zero
  spare mechanisms are attention entries, ranked with the other
  problems, never buried in a list. When there are no traps at
  all, the line is one clause: "Traps: none built."
- **Diffs, not repeats.** When nothing in the section changed
  since the last tick, the assembler prints the short form
  ("stoneworking: unchanged"), the same way the Buildings section
  already does. The section costs its full price only on ticks
  when stone state actually moves.

**Token cost.** At 7 dwarves, the section as written above is 273
characters: about 91 tokens by the accountant's 3-chars-per-token
rate, 68 on the wire. At 50 dwarves, with more workshops and more
traps, it is 342 characters: about 114 tokens by the accountant,
86 on the wire. The cost grows by about 23 tokens from 7 dwarves
to 50, because the section is capped: 3 workshop clauses maximum,
4 stone-type counts maximum, trap counts only. It does not grow
with population, with the number of boulders, or with the number
of stone types on the map. If a future change makes it grow with
any of those, the change is refused until the section is capped
again.

### 12.2 Query route: GET /v1/stoneworking

GET /v1/stoneworking returns the full detail, read from the fresh
collect, not from a cache:

- Per stone type: boulders in stock, boulders loose on the ground,
  blocks made from it, and whether it is flux, obsidian, or magma
  safe. The full list, not the top 4.
- Per workshop: id, subtype, position, construction stage, queued
  jobs with their job types and counts, contained items (clutter),
  and the mason, mechanic, or stonecrafter assigned to it, with
  skill level.
- Mechanisms: in stock, in traps, in levers, reserved for
  machines, and the magma-safe count.
- Traps: each trap by id, type, position, armed or empty, jammed
  or clean, and what it is loaded with.
- Trade readiness: crafts, mugs, statues, and mechanisms in the
  trade stockpile with their computed values, and the caravan
  target from TRADING.md.

The snapshot carries the summary and the ids; the route carries
the detail. The agent asks the route when it needs to choose
which stone to use or which trap to fix, never as a matter of
routine. A second route, GET /v1/stoneworking/<workshop-id>,
returns one workshop in full: its queued jobs, its clutter, and
its worker. Both routes state their cost and staleness on every
response, the same as every other query route.

### 12.3 Briefing: what arrives just in time

Stoneworking has no standing briefing. Two events carry one,
both from the existing briefing system (briefings.py), each a few
hundred tokens at most, each fired once when the event starts:

- **Caravan arrives.** Trigger: the caravan event. Cost: about
  72 tokens by the accountant for the stoneworking paragraph
  (216 characters). It covers what stone goods are in the trade
  stockpile and their approximate value, whether obsidian goods
  exist, and what the fort could still make before the caravan
  leaves. It leaves the per-item values and the depot haggling to
  the query route and to TRADING.md.
- **First dwarf death.** Trigger: the death event. Cost: about
  50 tokens. It covers whether a coffin and a slab are in stock,
  and whether a mason's workshop exists to make them. It leaves
  the burial plan to MILITARY.md and the tomb layout to the site
  system. A fort with coffins in stock gets no briefing at all:
  the briefing fires only when the fort cannot bury its dead.

No other stoneworking event briefs the model. A mason finishing
a masterwork, a mechanism stock hitting zero, or a trap jamming
are attention entries and opportunities entries, not briefings.
A briefing is for something the model needs to understand right
now, not for something it can read in the snapshot.

### 12.4 Opportunities: at most 3, facts only

The opportunities section carries at most 3 stoneworking entries,
each one line: facts plus a query route, never a suggestion, never
a pause. Ignoring one costs nothing. Examples of what qualifies:

- "Stone: 142 boulders in stock, no mason's workshop.
  Query /v1/stoneworking for the breakdown."
- "Obsidian 9 boulders, no obsidian goods in the trade stockpile.
  Query /v1/stoneworking for the trade readiness."
- "Mechanisms 0 in stock, 2 stonefall traps waiting to be built.
  Query /v1/stoneworking for the trap list."

An opportunities entry fires only when the fact is actionable
and the snapshot alone does not already say it. A mason's workshop
with jobs queued is not an opportunity; it is the snapshot doing
its job. The entry never names the action to take and never
carries a cost estimate. The model decides.

### 12.5 What the system deliberately does NOT push, and why

- **The full stone list.** The fort has 25 layer stones plus
  veins and clusters. The snapshot names 4 counts; the full list
  is behind GET /v1/stoneworking. A list of 25 stone types every
  tick is a dump, and the model cannot act on the 21st stone type
  anyway.
- **Per-boulder positions.** Where each boulder sits is survey
  data, pulled by region when the model needs it. Pushing it
  would grow the snapshot with the map, which breaks the index.
- **Per-trap mechanism history.** Which mechanism went into which
  trap, and when, is journal data. The snapshot says how many
  traps are armed and how many are jammed. The history is there
  when the model asks why a trap is empty.
- **The whole job queue.** The snapshot says "3 jobs queued
  (blocks)". The full queue, with job ids and positions, is
  behind the workshop query route. A queue dump would grow with
  every job the fort queues.
- **Furniture placement suggestions.** The snapshot never says
  "put a statue here". Placement is the scored site system, and
  the model asks for a site when it decides to place something.
  The presentation gives the model what it needs to decide, not
  a script to follow (HARNESS_ROLE.md).
- **Trade values per item.** The snapshot says how many mugs are
  in the trade stockpile. The computed value of each item is
  behind the query route, because values change with quality and
  material and the snapshot cannot reprice the stock every tick.

## 13. Refusals

The harness refuses these, and says why in plain words when asked:

1. Never build a mason's workshop out of economic stone, and never
   let a mason job consume flux, ore, or plaster stone. Flux is
   steel. Ore is bars. The mason works ordinary stone unless the
   fort explicitly enables economic use for a type.
2. Never queue a traction bench until the rope or chain, the table,
   and the mechanism all exist. A job that cannot start is a job
   that blocks the queue.
3. Never offer rock short swords when the fort has no obsidian.
   Only obsidian makes them, and the harness must not offer a job
   whose material does not exist.
4. Never sell large pots, jugs, nest boxes, or hives as trade
   goods. They are fort supply. The trade stockpile holds mugs,
   crafts, statues, and mechanisms.
5. Never promise a working drawbridge, lever, or linked trap until
   the link is verified live. A lever with no link is decoration,
   and the snapshot must say so.
6. Never use a quantum stockpile for stone. It is a
   developer-tolerated exploit (STOCKPILES.md section 13). Stone
   is the heaviest thing in the fort, and the hauling system
   exists precisely so its cost is real.
7. Never claim a stone job works until a real item has been made
   and read back. A job type name from a wiki page is not proof
   the game accepts it, and a manager order that sits unvalidated
   is not proof the game dispatched it.
8. Never let the mechanism stock hit zero while traps are waiting.
   Mechanisms are the one item every defense and every machine
   needs, and an empty mechanism stock is a defense failure, not
   a quiet zero.
9. Never put the mason's feeder stockpile where its hauling route
   crosses the main corridor or the only path into the fort.
   Stone hauling is the slowest traffic in the fort and it must
   not block the entrance.
10. Never claim a magma-safe mechanism is magma safe because the
    stone's name sounds like it should be. Magma safety is a
    melting point in the raws, and the harness checks the number.

## 14. Implementation phases

Each phase ends with a live-verification bar. A phase that cannot
be verified live is logged as unverified and re-attempted, per the
standing rule. Nothing unverified gets pushed.

### Phase 1: Probe the stone job types and build the two missing workshops

- Add `mechanic` and `craftsdwarf` to `WORKSHOP_CATALOG`
  (3x3, material BOULDER), and `jeweler` for the stone sink.
  The build route is the existing `build_workshop`; only the
  catalog entries are new.
- Probe the exact `df.job_type` names for the stone jobs live
  against the running game: the mason's 16 Construct rock jobs
  plus Make rock bookcase, pedestal, and altar; the mechanic's
  Make rock mechanism and Make traction bench; the craftsdwarf's
  stone jobs (large pot, crafts, toys, instruments, mugs, short
  sword, nest box, jug, hive); the jeweler's Cut gems. Record
  the names in the code and in this doc. A name the game does not
  accept is a failed probe, not a job.
- Live bar: on the scratch fort, a mechanic's workshop and a
  craftsdwarf's workshop are built by `build_workshop` and read
  back in the buildings list with their subtypes and ids; the
  probed job type names are accepted by `df.job_type` without
  error.

### Phase 2: Queue stone jobs

- Add a hardcoded job shape to `JOB_SPECS`: a `job_type` name
  with no `reaction_name`, for the mason, mechanic, and
  craftsdwarf stone jobs. Wire the material fail-fast through
  `materials.py`: each job names what it needs (1 boulder; short
  sword needs obsidian plus 1 log; traction bench needs rope or
  chain plus table plus mechanism), and a job whose materials are
  short is never queued. The failure names the exact gathering
  fix, the same as brew and cook do today.
- Add quern and millstone placement: the mason makes the items,
  and the harness needs a route to place them. `build_furniture`
  cannot do it today (no Quern or Millstone kind). Either extend
  `FURNITURE_ITEMS` with a building placement route for them, or
  add a dedicated action. A millstone placed with no power is
  flagged in the result, not silently built.
- Live bar: on the scratch fort, a mason queues 4 blocks from 1
  boulder and the 4 blocks are read back in stock; a mechanic
  queues 1 mechanism and it is read back; a craftsdwarf queues
  mugs and the mugs are read back; a quern is made and placed and
  mills flour. A job queued with no stone in stock fails fast
  with the material named.

### Phase 3: Traps and the mechanism stock

- Generalize `act_build.lua` with a type-aware subtype lookup
  (`df.trap_type` for Trap), following the `act_furniture.lua`
  pattern. Build stonefall, weapon, and cage traps at the sites
  placement already computes. Resolve the cage discrepancy live:
  DFHack's trap_inputs lists mechanism only for cage traps, the
  wiki says a cage must be provided; record which one was right.
- Add trap state to the observation: `building_trapst` fields
  (loaded, contents, jammed) read back after each build, and a
  lever building action (1 mechanism) with its built state read
  back.
- Add the mechanism floor to the planner: the fort keeps a
  standing stock of mechanisms (starting floor: 3, tuned live),
  and the mechanic makes more when the stock falls below it.
  Traps waiting to be built and mechanisms in stock are both in
  the snapshot's Traps line.
- Live bar: on the scratch fort, one stonefall trap, one weapon
  trap, and one cage trap are built and read back armed; a
  stonefall trap is triggered, re-armed by a mechanic, and read
  back armed again; the mechanism stock never reads zero while
  traps are waiting.

### Phase 4: Lever linking

- Investigate the link route live: `advfort.lua` fake_linking
  and `lever.rb` as precedents, and a direct probe of what the
  game needs to link a lever to a floodgate or a bridge. If no
  programmatic route exists on r8, document the fallback (the
  lever is built and the link is left to a later investigation)
  and what it costs, and do not pretend otherwise.
- Live bar: on the scratch fort, a lever is linked to a
  floodgate, the lever is pulled, and the floodgate is read back
  open, then pulled again and read back closed. Until that bar
  passes, no doc or snapshot line claims a working drawbridge.

### Phase 5: The stone stockpile network

- Build the four-tier stone piles (low value, flux, obsidian,
  magma safe) by the network rules in section 10, with the mason
  feeder, the mechanic feeder, and the craftsdwarf feeder, and
  the links between them. This phase depends on the settings
  write and link actions from STOCKPILES.md phases 2 and 3; if
  those have not landed, this phase builds the piles
  category-flag-only and records what the missing links cost.
- Wire the economic-stone guard: the mason's feeder takes
  ordinary stone only, and the snapshot says when a mason is idle
  for lack of usable stone while economic stone sits in stock.
- Live bar: on the scratch fort, the four piles exist with the
  right stone in each; a mason draws from its feeder and the
  feeder is refilled from bulk; a flux boulder placed in the
  mason's feeder is not consumed by a block job.

### Phase 6: Trade production and the snapshot section

- Add the Stoneworking snapshot section (section 12.1) and the
  GET /v1/stoneworking route (section 12.2), with the per-type
  breakdown, the workshop records, the mechanism ledger, and the
  trade readiness. Add the caravan briefing paragraph and the
  first-death briefing paragraph (section 12.3), and the
  opportunities entries (section 12.4).
- Wire the trade production rule into the planner: the season
  before a caravan, the craftsdwarf makes mugs and crafts to the
  trade target from TRADING.md, obsidian first when the map has
  it, and the mason keeps blocks flowing for construction.
- Live bar: on the main fort, the snapshot's Stoneworking section
  prints true counts (stone by type, blocks, mechanisms) and the
  token cost is measured against the live assembler at 7 dwarves
  and at the largest population the fort reaches; GET
  /v1/stoneworking returns the full breakdown; a caravan-season
  run produces mugs that reach the trade stockpile and read back
  there.

### Phase 7: Jeweler's stone sink and engraving handoff

- Add the jeweler's workshop to the catalog and the Cut gems job
  to JOB_SPECS, as the stone sink: cut ordinary stone into
  cabochons when stone is in excess, and train gem setters on
  cheap stone before real gems. Add the encrust guard: mechanisms
  in their own stockpile when the fort has a jeweler, so the
  encrust job does not gem the trap stock.
- Hand engraving to its own doc: the labor route already exists
  (`act_labor.lua`), and the engraving plan is written there, not
  here.
- Live bar: on the scratch fort, a boulder is cut into a cabochon
  and read back; a gem setter's skill rises from cutting stone;
  no mechanism is encrusted while the separate mechanism
  stockpile exists.

## 15. Open questions

All marked UNVERIFIED until a live probe or a wiki page settles
them.

1. The exact `df.job_type` names for the stone jobs (phase 1).
   The DF2014 pages give the job names in words ("Construct rock
   blocks"); the enum names are a live probe.
2. Whether `queue_workshop_job` can express hardcoded jobs at all,
   or whether stone jobs go only through manager orders. The
   current action assumes `job_type` 211 (CustomReaction).
3. Whether a manager order for a mason job dispatches without a
   manager noble appointed, and how long validation takes.
4. Whether the Stone use (economic stone) flags are readable and
   writable through DFHack on r8, and by which field names.
5. Bin capacity for blocks: 5 (DF2014:Stone industry), 10
   (Stockpile page), or 12 (bin table). The doc plans on 5 until
   a live count settles it, and STOCKPILES.md plans on 10; the
   two docs disagree and the live count decides both.
6. Whether the harness's `create_stockpile` can set the
   wheelbarrow count, or whether the count is whatever
   `constructBuilding` leaves behind. STOCKPILES.md says there is
   no settings write anywhere in the harness.
7. The cage trap discrepancy: DFHack's trap_inputs lists mechanism
   only for cage traps, the wiki says a cage must be provided.
   Phase 3 settles it live.
8. Whether a lever link has any programmatic route on r8, or
   whether linking stays manual until a DFHack route is found.
   Phase 4 settles it.
9. Whether the snapshot's `by_material` top-8 list reliably
   carries the flux and obsidian counts, or whether the
   Stoneworking section needs its own per-type read.
10. Whether the game counts placed furniture in `stocks.lua` the
    way it counts placed beds (build_furniture comment, 2026-11-27):
    if so, the mechanism and furniture counts in the snapshot
    must use the accessible probe, not the stocks total.
11. Whether the altar job at the mason's workshop really needs
    the stone crafting labor on r8, as the DF2014 page says, or
    whether a mason does it.
12. Whether stone cut into cabochons at the jeweler's workshop
    counts against the trade target, or whether cabochons are
    fort supply only.

## 16. Sources

Wiki pages, all from the DF2014 namespace (the 0.47.05 pages),
read 2026-11-27:

- DF2014:Mason's workshop: the full job list (16 Construct rock
  jobs, Make rock bookcase, pedestal, altar), the altar labor
  note, the clay exclusion, querns/slabs/millstones only here.
- DF2014:Mechanic's workshop: Make rock mechanisms, Make traction
  bench, the traction bench inputs (rope or chain, table,
  mechanism).
- DF2014:Craftsdwarf's workshop: rock crafts, mugs, instruments,
  toys, jugs, large pots, hives, nest boxes, rock short swords,
  memorials, bolts, bone and shell armor.
- DF2014:Stone crafter: the stone job list, up to 3 small objects
  per stone, obsidian short swords need obsidian and wood, large
  pots replace barrels.
- DF2014:Jeweler's workshop: Cut gems, ordinary stone cuts to
  cabochons, any boulder can be cut, flux and obsidian cabochons
  are 2 to 3 times as valuable.
- DF2014:Stone industry: the four stone sources, the 25% boulder
  chance, the labor list, the three workshops, 4 blocks per
  boulder, 5 blocks per bin, value levels (1, flux 2, obsidian 3),
  the four-tier stockpile sort, economic stone, the 6 to 12 layer
  stones per fort.
- DF2014:Workshop: the authoritative 0.47.05 workshop list, 31
  workshops in three tiers, with the mason's, mechanic's,
  craftsdwarf's, and jeweler's entries.
- DF2014:Mechanism (v50 page text, mechanics unchanged): base
  value 30, one mechanism per trap/lever/pressure plate/gear
  assembly, two per link, magma-safe rule, quality sets trap
  attack skill, mechanisms count as furniture.
- DF2014:Mason: masons build trade depots, bridges, furnaces, and
  wells with the Masonry skill; walls and floors use wall/floor
  construction instead.

Local wiki export (`~/workspace/df-wiki-export/dfq.py`, hybrid
search), used only to find pages, never as authority, because it
holds the current v50 wiki: Stone industry (2,120 words), Mason
(655 words), Mechanic's workshop (394 words), Mechanism (1,382
words), Craftsdwarf's workshop (876 words), Stone crafter (822
words), Finished goods (1,623 words), Workshop (4,147 words),
Boulder (279 words).

0.47.05 raws, read from the install 2026-11-27
(`third_party/df_47_05/raw/objects/`):

- `inorganic_stone_layer.txt`: limestone, dolomite, chalk, marble
  carry `[MATERIAL_VALUE:2]`; obsidian carries
  `[MATERIAL_VALUE:3]`; melting points give the seven magma-safe
  layer stones (sandstone 12070, gabbro 12160, basalt 12160,
  quartzite 12970, chert 13101, obsidian 13600, dolomite 16507).

Harness state verified against the repo 2026-11-27: actions.py
`WORKSHOP_CATALOG` (mason only, no mechanic or craftsdwarf),
`JOB_SPECS` (no stone jobs), `manager_order_create` and
`act_order.lua` (takes a `df.job_type` name), `build_furniture`
and `FURNITURE_ITEMS` (no quern or millstone), `materials.py`
(mason build material only), `act_labor.lua` (any labor by name),
`stocks.lua` (`stone_units`, `stone_stacks`, `by_material`),
`survey.py` (stone by z-level, veins unidentified),
`placement.py` (affinity rows for Mason and Craftsdwarf),
`act_build.lua` (subtype lookup hardcoded to `df.workshop_type`),
`assembler.py` (`_buildings`, `_stocks`, `_materials`),
`briefings.py` (briefing system, caravan and strange mood kinds),
docs/TRADING.md (stone trade ranking, flux rule), docs/MILITARY.md
(trap types, lever linking unresolved), docs/ADVANCED_MECHANICS.md
section 4 (trap construction route, cage discrepancy),
docs/STOCKPILES.md (stone stockpiles, wheelbarrows, bins, links),
docs/KITCHEN.md section 13 (the presentation precedent),
GOAL.md and the coordinator log 2026-11-27 (the presentation
constraint and the breadth-doc amendment).
