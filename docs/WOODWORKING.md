# Woodworking

Design record for the woodworking system in the Urist harness: woodcutting,
the carpenter's workshop, the wood furnace, beds and barrels, wood crafts,
wooden traps, and charcoal. This is the plan. Implementation follows it
phase by phase, each phase verified live against the real game before it
counts as done. Anything not verified against the wiki, the 0.47.05 raws,
the code, or the live game is marked UNVERIFIED.

Related docs: docs/STOCKPILES.md (wood stockpiles, containers, the barrel
ledger), docs/KITCHEN.md (brewing and the empty barrel bottleneck),
docs/FARMING_PLAN.md (the ash and potash chain, fertilizer), docs/TRADING.md
(wood crafts as trade goods, the elf refusal), docs/MILITARY.md (wooden
training weapons, shields, trap components in defense), docs/HUNTING.md
(animal traps), docs/LABOR.md (woodcutter and carpenter assignment).
This doc builds on them and does not duplicate them. Where this doc
changes a behavior another doc describes, it says so explicitly.

## 1. Purpose

Woodworking answers six questions every tick, from fresh collects, so
the agent never has to:

1. How much wood do we have, and how fast is it going?
2. How many beds and barrels do we still need, and what is stopping us
   making them?
3. Can we chop more wood right now (axes, trees, a woodcutter)?
4. Do we need charcoal, and can we afford to burn a log for it?
5. What wooden goods should we make for trade, and who will buy them?
6. What wooden trap parts, cages, crutches, and splints does the fort
   need?

The headline finding of the research behind this doc is that the fort
is not short of wood. The snapshot carries wood 117, and every carpenter
item costs exactly 1 log, so 117 logs is 117 beds, barrels, bins, or
buckets. The bottleneck the diary and the run logs keep tripping over
is throughput, not stock: the carpenter makes one item per job, the
barrel pipeline stalls brewing when empty barrels hit zero, and the
model has queued 20 barrel jobs at once while zero brews could run.
This doc designs the pipeline, not a bigger woodpile.

## 2. How woodworking works in DF 0.47.05

All of this section is from the wiki pages listed in Sources, checked
against the 0.47.05 raws shipped with the game where the wiki and the
version can disagree. The local wiki index is a current-wiki export:
some pages carry v50 markers (the Potash page shows a v50 preview
image), so a wiki claim is not a 0.47.05 claim until the raws or a live
probe agrees with it. Section 3 is the authoritative list for this
version. Where the wiki list and the raws disagree, the raws win and
the difference is named.

### 2.1 Trees and woodcutting

Most biomes with soil on the surface have trees. Surface trees spawn
randomly in surface soil. Underground trees (giant fungi) spawn in the
caverns once breached, in muddy soil. Saplings appear at random and
take about three and a half months to grow into a tree. Tree farming
is patience and luck more than skill: saplings spawn at random, and
the best the fort can do is isolate an area and keep dwarves and
critters from trampling the saplings (Tree farming).

To cut a tree, a dwarf with the wood cutting labor and a battle axe
goes to the tree and chops it. Designating any trunk tile marks the
tree. Each trunk tile yields exactly one log, while light branches,
twigs, and heavy branches give nothing (Tree). So a tree yields
roughly its height in logs, not a fixed number per tree, and a tall
old tree is worth several short young ones. A woodcutter who finishes
the first tile sees the tree convert instantly to free-floating logs
that fall away from the cutter. Cutting a tree from a trunk section
above ground level can drop the cutter to the ground (Tree).

Two hazards come with cutting. First, a trunk tile is an obstacle:
it blocks channeling, walls, and constructions on its tile, and a
forest can block the 3 tile wide path a caravan wagon needs to reach
the depot. Trees keep growing, so depot access must be rechecked and
impeding trees chopped (Tree). Second, digging the tile below a trunk
before cutting leaves a hole to the surface, which lets creatures
path into the fort. Never dig directly below a tree one z-level down
before clearing it, and check for open floor afterwards (Tree).

Woodcutting makes noise out to 8 tiles (placement.py, from the Noise
page). Bedrooms, jails, hospitals, and sleeping barracks belong at
least 8 levels below the cutting, or away from it, or dwarves lose
sleep to the sound (Noise).

### 2.2 What wood is

A log is a hard material found in nearly all biomes, base value 3,
size 50,000 cubic centimeters (Wood). For the most part all wood is
interchangeable: an oak log makes all the same things as an alder log.
Species differ in color and density, and those differences matter in
exactly three places:

* **Color.** Most logs are brown, so most wooden furniture is brown.
  Black-cap is black, feather tree is cream, blood thorn is crimson,
  nether-cap is indigo, fungiwood is lemon, glumprong is purple,
  goblin-cap is red, spore tree is teal, tunnel tube is violet,
  tower-cap is white (Wood industry). Color is aesthetic, except
  where a noble mandate or a room value calculation cares about it.
* **Weight.** Weight follows density. Average wood density is about
  0.575 grams per cubic centimeter. Feather tree wood is the lightest
  in the game at 0.1, which makes it ideal for items that move often:
  buckets, barrels, bins. Blood thorn at 1.25 and glumprong at 1.2
  are the densest, and suit ballista bolts and other weapons where
  weight drives damage (Wood industry). A log weighs about 30, which
  does not slow an average dwarf carrying it, so wood is a bad use
  for wheelbarrows (Stockpile design).
* **Fire and magma safety.** Wood catches fire and should not be used
  around magma or dragons. Nether-cap wood is the exception: its
  temperature is fixed just around freezing, so nether-cap items are
  both fire safe and magma safe. Nether-cap barrels, corkscrews, and
  pipe sections are magma safe (Wood industry). Fire can devastate
  a food stockpile full of wooden barrels, so metal or nether-cap
  barrels are worth considering if fire is a concern. Nether-cap
  grows only below the second cavern level, so the fort cannot trade
  for it and cannot cut it early (Wood industry).

Wood is weak compared to stone or metal, and usually flammable, but
it is lightweight and renewable, and sometimes the only option for an
item before the metal industry starts (Wood industry). Dwarves prefer
stone or metal when possible, for durability and variety.

### 2.3 The carpenter's workshop

A carpenter's workshop is a Tier 1 workshop. It makes most wooden
furniture, except statues, plus buckets, crutches, shields, and
training weapons. Beds can only be made at a carpenter's workshop
(Carpenter's workshop). It can be built from any building material
and must be built by a dwarf with the Carpentry labor enabled. It is
3 by 3 tiles. One log is consumed to make each item of wooden
furniture (Furniture industry).

The 0.47.05 reaction list for the workshop is 23 reactions, verified
against the shipped raws (reaction_adv_carpenter.txt, 22 reactions,
plus reaction_other.txt, 1 reaction). Every one takes 1 log unless
noted, and every one is a CustomReaction (job type 211) in the
harness's terms:

* Furniture and storage: MAKE WOODEN BED, MAKE WOODEN CHAIR, MAKE
  WOODEN TABLE, MAKE WOODEN CHEST, MAKE WOODEN CABINET, MAKE WOODEN
  DOOR, MAKE WOODEN BARREL, MAKE WOODEN BUCKET, MAKE WOODEN BIN,
  MAKE WOODEN CASKET (the coffin; the item type is COFFIN), MAKE
  WOODEN BOOKCASE, MAKE WOODEN PEDESTAL, MAKE WOODEN DISPLAY CASE,
  MAKE WOODEN STEPLADDER.
* Building parts: MAKE WOODEN HATCH COVER, MAKE WOODEN GRATE.
* Hospital: MAKE WOODEN SPLINT, MAKE WOODEN CRUTCH.
* Defense: MAKE WOODEN SHIELD, MAKE WOODEN BUCKLER, MAKE WOODEN
  TRAINING AXE, MAKE WOODEN TRAINING SHORT SWORD, MAKE WOODEN
  TRAINING SPEAR.
* Craftsdwarf input: CARVE_WOODEN_HELVE (a helve for a weapon, at
  the craftsdwarf's workshop, not the carpenter's).

The wiki's task list for the workshop is longer than the raw list.
The extra tasks (wooden animal trap, armor stand, blocks, enormous
corkscrew, floodgate, minecart, pipe section, menacing spike, spiked
ball, weapon rack, wheelbarrow, cage, altar) are not reactions in the
0.47.05 raws. Most are hardcoded job types in the live runtime enum:
MakeCage, MakeAnimalTrap, MakeTrapComponent, MakePipeSection,
ConstructArmorStand, ConstructWeaponRack, ConstructBlocks. They are
real jobs the workshop can do, through a different mechanism than the
reactions, and the harness route for each is UNVERIFIED until probed
(section 18, open question 1). Two wiki items are not in 0.47.05 at
all: the altar is a v50 temple item, and the minecart and wheelbarrow
routes need a live probe before the doc claims a workshop for them.

The carpenter's labor is Carpentry. The workshop also lists Trapping
as a job requirement on the wiki page, for the animal trap task.
Attributes the wiki names for a carpenter: strength, agility,
creativity, spatial sense (Carpenter).

### 2.4 The wood furnace: charcoal and ash

A wood furnace turns wood logs into ash or charcoal. It is a furnace,
not a workshop: it lives in the furnace list (WoodFurnace) beside the
smelter, glass furnace, and kiln. It is built from a fire-safe
building material, with stone (Masonry labor) or metal
(Blacksmithing, Weaponsmithing, Armoring, or Metalcrafting) as the
construction material (Wood furnace). The labor is Wood burning, and
the skill is Wood burner (strength, toughness, endurance,
kinesthetic sense).

* **Charcoal.** One log produces one bar of charcoal. Skill reduces
  the time, not the result (Fuel). Charcoal is fuel. Smelters,
  forges, glass furnaces, and kilns need fuel to operate. Coke from
  bituminous coal or lignite is the alternative, and neither is
  guaranteed on a map, so charcoal is typically the first reliable
  fuel for an early fortress (Wood).
* **Ash.** One log produces one bar of ash. Ash goes to the ashery
  for lye or potash (Wood industry).

In 0.47.05, making charcoal and making ash are hardcoded job types,
MakeCharcoal and MakeAsh, not reactions: neither appears in the
reaction raws, and both appear in the live runtime enum
(tests/fixtures/runtime-enums-0.47.05-r8.json). That matters for the
harness, because queue_job today only accepts JOB_SPECS names, and
JOB_SPECS holds reactions plus cook. The charcoal route needs a new
job spec entry, not a new reaction name (section 5).

### 2.5 The ashery chain: lye, potash, pearlash

Wood becomes farming and glass inputs through the ashery chain
(Wood industry):

* One bar of ash makes one bucket of lye at an ashery, with the wood
  burning labor, using an unused bucket.
* One bar of ash or one bucket of lye makes one bar of potash at an
  ashery, with the potash making labor. Potash fertilizes farm plots
  or becomes pearlash.
* One bar of potash makes one bar of pearlash at a kiln, with the
  furnace operator labor, consuming one bar of fuel as well (a magma
  kiln needs no fuel). Pearlash is used only in the glass industry,
  for higher-value glass.

The ashery itself needs a block, a barrel, and a bucket as
components (FARMING_PLAN.md, section 8). The barrel and the bucket
are carpenter products, so the ashery chain starts at the carpenter.
The fertilizer half of the chain belongs to the farming plan
(FARMING_PLAN.md, section 8, and its phase 3); this doc owns the
wood side, the ash supply, and the decision of when ash is worth a
log.

### 2.6 Crafts, bolts, and trade value

Wood feeds the craftsdwarf's workshop as well as the carpenter's.
A wood crafter makes wooden crafts, toys, instruments, cups, bolts,
nest boxes, jugs, and pots (Wood crafter). One log makes a stack of
25 wooden bolts, against 5 bolts from a single bone (Wood). Wooden
bolts are enough for training and hunting, and much less effective
against armored opponents than metal bolts.

Trade value, from the Maximizing value table: wooden crafts run
about 20 (1 to 3 crafts per job, variable), a minecart 50, a
wheelbarrow 50, a stepladder 50, a cup 30, a stack of 25 bolts 25,
a spiked ball 10, a menacing spike 10, an enormous corkscrew 10, a
training axe 10, a shield 10, a buckler 10, an armor stand 10, a
bed 10, a cabinet 10, a chair 10, a chest 10. A barrel is value 10
(Barrel). A log is value 3 (Wood). So a log becomes about 20 value
as crafts, 10 as a bed or barrel, 25 as a stack of bolts, 50 as a
minecart or wheelbarrow. The trading plan already draws the
conclusion: stone mugs and crafts are the default trade good because
stone is free and unlimited, and wood goods are a fallback, not a
staple (TRADING.md, section 5). Wood is also the elves' red line:
elves refuse wood and animal products entirely, including tower-cap
fungus wood, wood derivatives (ash, potash, pearlash, charcoal,
lye, tallow soap), clear and crystal glass, and obsidian short
swords with wooden handles (TRADING.md, section 4). Never offer a
wooden item to elves. A wooden cage holding an acceptable animal is
refused too, if the cage itself is wood.

### 2.7 Beds, bedrooms, and sleep

A bed is a piece of furniture made at a carpenter's workshop, base
value 10, size 30,000 cubic centimeters (Bed). Once built, a bed is
placed with the build menu, and a bedroom is an activity zone that
probably should contain a bed. Bedrooms are claimed automatically by
dwarves (or their spouses) or assigned by hand (Bedroom).

Sleep is a maintenance need alongside eating and drinking. Dwarves
awake a long time grow tired and desire sleep (Sleep). The fort's
choice is a dormitory or individual bedrooms:

* **Dormitory.** A zone with many beds, where every dwarf without a
  bedroom sleeps. Sleeping in a dormitory gives a negative thought
  (embarrassed after sleeping without privacy, per the Zone page).
  It is the cheap short-term answer: one zone, many beds, no rooms
  to dig.
* **Individual bedrooms.** Dwarves are happier with their own
  bedroom and furniture, and get good thoughts from admiring the
  furniture they own. Even a minimalist bedroom, a 1 by 1 grid
  containing only a bed, inside a communal space, gives the thought
  (Keeping your dwarves unstressed). A 3 by 3 engraved bedroom is
  the version the stress research praises most (Stress).

The planner already treats one bed per citizen as the floor
(planner.py). The design in this doc keeps that floor and adds the
dormitory-first rule: beds go in a dormitory zone until every dwarf
has a bed, and individual bedrooms come after, because a dwarf with
no bed sleeps on the floor, and that is worse than a dormitory
thought.

### 2.8 Wooden traps and components

Wood makes trap parts at the carpenter's workshop and the mechanic's
workshop between them. The trap component page names the menacing
spike, which mounts in weapon traps, stands upright at the bottom
of a pit, or goes into an automated upright spike trap (Trap
component). The trap design page adds the cage trap: a very powerful
trap, and even a wooden or glass cage can hold any creature
indefinitely, even trolls and megabeasts. A cage trap never fails,
except against creatures with the trapavoid tag, which must be
knocked unconscious or webbed first (Trap design). All traps other
than upright spears use mechanisms in their construction, and for
weapon traps and stone-fall traps the mechanism quality decides the
skill the weapon is used with (Trap).

The exact 0.47.05 routing is split and partly unverified. What the
live enum proves: MakeTrapComponent, MakeCage, MakeAnimalTrap, and
LoadCageTrap are real job types, and ConstructArmorStand,
ConstructWeaponRack, and ConstructBlocks are real job types. Which
workshop each wooden job runs at, and whether queue_job can drive
it through a JOB_SPECS entry, is UNVERIFIED (section 18, open
question 1). The military doc owns trap placement and defense; this
doc owns making the wooden parts.

### 2.9 What wood feeds

One material, five consumers, in the order the fort feels them:

1. **Beds.** One bed per dwarf, carpenter, 1 log each. No bed, no
   sleep, unhappy dwarves.
2. **Barrels.** One barrel per brew (5 drink) and one per food
   stockpile stack. No empty barrel, no brew, thirsty dwarves.
3. **Bins, buckets, chests.** Storage and hauling. Bins hold finished
   goods, cloth, leather, bars. Buckets carry water, lye, and milk.
4. **Charcoal and ash.** Fuel for every furnace that is not magma,
   and the ashery chain for fertilizer and glass.
5. **Construction and trade.** Logs as a building material, wooden
   furniture for rooms, crafts and bolts for trade.

The first two are survival. The last three are discretionary, and
they only spend wood above the bed and barrel floors (section 6).

## 3. The authoritative 0.47.05 workshop list for the chain

Workshops in this game are mostly hardcoded: the building type and
the jobs it runs are fixed by the version, not chosen by the player.
The list below is the chain as it stands in 0.47.05, verified against
the shipped raws and the live runtime enum
(tests/fixtures/runtime-enums-0.47.05-r8.json). Do not trust a v50
workshop list for this fort.

| Building | Type in the enum | What it does in the chain | Harness build kind today |
| --- | --- | --- | --- |
| Carpenter's workshop | Workshop, subtype Carpenters | All 23 reactions in section 2.3, plus the hardcoded jobs MakeCage, MakeAnimalTrap, MakeTrapComponent, MakePipeSection, ConstructArmorStand, ConstructWeaponRack, ConstructBlocks | carpenter, in WORKSHOP_CATALOG, verified live |
| Wood furnace | Furnace, subtype WoodFurnace | MakeCharcoal, MakeAsh, 1 log per bar | none, no furnace kind exists in WORKSHOP_CATALOG |
| Ashery | Workshop, subtype Ashery | MakeLye, MakePotashFromAsh, MakePotashFromLye | none |
| Kiln | Furnace, subtype Kiln | MakePearlash, 1 potash plus 1 fuel | none |
| Craftsdwarf's workshop | Workshop, subtype Craftsdwarfs | Wooden crafts, toys, instruments, cups, bolts, nest boxes, jugs, pots; CARVE_WOODEN_HELVE | none |
| Bowyer's workshop | Workshop, subtype Bowyers | Wooden crossbows | none |
| Siege workshop | Workshop, subtype Siege | Siege engine parts (wooden parts) | none |
| Mechanic's workshop | Workshop, subtype Mechanics | Mechanisms for traps; trap components in metal, and the trap loading jobs | none |

Notes on the list:

* The carpenter's workshop is the only building in the chain the
  harness can build today. Every other row is a gap, not a claim.
* The still accepts wood as a construction material (verified live
  2026-11-26: still #10 was built from a log with no stone in
  stock, actions.py). With stone at 0 in the snapshot, wood is the
  fort's only workshop building material right now.
* The furnace list in the enum is WoodFurnace, Smelter, GlassFurnace,
  Kiln, MagmaSmelter, MagmaGlassFurnace, MagmaKiln, Custom. A magma
  furnace needs magma, which the fort does not have, so the wood
  furnace is the only fuel source on the table.
* The workshop list in the enum is Carpenters, Farmers, Masons,
  Craftsdwarfs, Jewelers, MetalsmithsForge, MagmaForge, Bowyers,
  Mechanics, Siege, Butchers, Leatherworks, Tanners, Clothiers,
  Fishery, Still, Loom, Quern, Kennels, Kitchen, Ashery, Dyers,
  Millstone, Custom, Tool. That is the full set the harness can ever
  address by subtype; anything outside it does not exist in 0.47.05.

## 4. What the harness has today

Verified against the repo on 2026-11-27. Everything in this section
was read from the code, not remembered.

### 4.1 Woodcutting works

* **designate_chop** (actions.py) marks trees for chopping in a
  rectangle, one level, through act_plants.lua. It marks the SE-most
  trunk tile of each tree, which is the same tile for single-trunk
  trees and a valid trunk tile for multi-trunk trees. Unmarking is
  supported, with the known quirk that FellTree jobs never leave the
  job list: the game never removes them, so an unmark does not wait
  for the jobs to vanish (actions.py, _plants_action). The
  designation sweep is slow and variable: a FellTree job took about
  2 seconds once, about 6 seconds once, and over 30 seconds once, so
  the wait bound is generous at 60 seconds.
* **The catalog entry** (catalog.py) says chopping needs a dwarf
  with the Wood Cutting labor and an axe, and warns that the fort
  has 2 picks and axes are a separate item.
* **The map read** (lua/map.lua) counts trees and shrubs on the map,
  and observe.py logs them. The snapshot does not carry the count.
* **The gather box** in the planner is shrub-probed, for gathering,
  not for chopping. There is no chop box, no chop task, and no chop
  suggestion anywhere in the planner, daemon, or assembler (verified
  by grep: zero "chop" hits in planner.py, daemon.py, or
  assembler.py outside comments).

### 4.2 Carpenter jobs work, nine of them

* **JOB_SPECS** (actions.py) holds nine carpenter jobs, all
  CustomReaction 211, all 1 log each, all verified live in the same
  mechanism as brewing: make_bed (MAKE WOODEN BED, reaction index 2
  in the live probe), make_table, make_chair, make_door, make_barrel,
  make_bucket, make_bin, make_chest, make_cabinet.
* **queue_job** (actions.py) refuses a job whose materials are
  short, and counts already-queued copies first, so a second queue
  cannot pass on stock the first queue already claimed. Run #12
  proved why: 4 brews queued against 2 empty barrels, each queue
  passing because the check only ever saw fresh stock. The same
  guard covers carpenter jobs: a make_barrel x5 against 3 logs
  fails with the shortage named.
* **materials.py** carries the 1-log rule as _WOOD_1 for all nine
  jobs, and the barrel fix text ("queue make_barrel at the
  carpenter", 1 wood each) that the diagnosis system uses.
* **The build route** works: WORKSHOP_CATALOG has carpenter as a
  3 by 3 workshop built from WOOD, and build_workshop refuses unsafe
  sites after a probe.
* **The tasks** (daemon.py TASK_DEFS) have make_bed and make_barrel
  as composed tasks: queue the job at the carpenter and wait for the
  CustomReaction job to leave the job list. The planner queues
  make_bed x up to 3 when placed beds are fewer than citizens and no
  bed items are in stock, and make_barrel x3 when the still exists
  and empty barrels are 0 (planner.py). It also suggests building a
  carpenter when there is none and wood is at least 1, because the
  carpenter is needed for beds and barrels.

### 4.3 The stocks read already carries the bottleneck numbers

* **stocks.lua** counts wood_units and wood_stacks, barrels (total),
  empty_barrels (a BARREL item with no contained items), bins, and
  buckets. Trader-held goods are excluded, which matters: the
  comment records a fort that read drink 50, food 211, wood 15
  while the true stocks were drink 0, food 6, wood 3, all the rest
  in merchant-held barrels.
* **The empty barrel count is the brew check.** Total barrels is
  not: the fort had 15 barrels with only 3 empty on 2026-11-27, so
  a brew x5 against the total would queue 2 jobs that can never run.
  materials.py already fail-fasts on empty barrels.
* **The snapshot Stocks line** (assembler.py) renders "Stocks: drink
  97, food 23, wood 117, stone 0. brewable plants 1. empty barrels
  3. food stacks N." plus burn rates and days-remaining for drink,
  food, wood, and stone from the Store's trends. The agent never
  computes a burn rate from a single snapshot.
* **The Buildings line** (assembler.py) lists workshops by subtype
  with id and built state, so the model can tell a Carpenter's from
  a Still without a query turn, and names the Still explicitly when
  absent. Construction stage 2 or above is built; the live
  Carpenter's is stage 3.
* **The planner's bed check** reads placed beds from
  building_summary (Bed count) and bed items from items_by_type
  (BED count), and places beds in a grid from bed_origin when items
  exist (planner.py).
* **The diagnosis system** (diagnose.py) already fixes wood
  shortages in words: chop a tree for wood, make a bed at the
  carpenter, make a barrel at the carpenter, make a bucket at the
  carpenter, each with the wood count attached.
* **The diary feed** groups queued jobs by workshop and carries the
  materials bit per queue group ("make_bed x5, make_barrel x2, 7
  jobs total; needs 7 wood, have 117", diary.py). The feed never
  states what a job is made of unless the feed states it: a bed
  takes wood, not stone, and an earlier entry got that wrong.

### 4.4 Placement knows the carpenter wants wood nearby

* **placement.py** scores a wood stockpile near the carpenter
  (adjacency weight 25 for ("stockpile", "wood", 25) under the
  Carpenters key), and notes that the Still wants barrels nearby
  and the Carpenter wants wood. The wood stockpile default in the
  daemon's placement cache is a 5 by 5 box, and the stockpile doc
  puts small wood stockpiles near the felling areas feeding one
  large primary stockpile near the carpenter (STOCKPILES.md,
  section 4.2).

## 5. What is missing (verified gaps)

Every gap below was verified by reading the code, not by guessing
from the wiki.

* **No wood furnace.** WORKSHOP_CATALOG has exactly four kinds:
  carpenter, mason, still, kitchen. There is no furnace kind, so
  build_workshop cannot build a wood furnace, an ashery, a kiln, a
  craftsdwarf's workshop, a bowyer's, a siege workshop, or a
  mechanic's. The furnace list in the runtime enum proves the game
  has them; the harness cannot build any of them.
* **No charcoal or ash jobs.** JOB_SPECS has no make_charcoal and no
  make_ash. MakeCharcoal and MakeAsh are hardcoded job types in the
  enum, not reactions, so adding them needs a JOB_SPECS entry with
  reaction_name None and the job type name, plus the material rule
  (1 log each). Until then the fort has no fuel production at all,
  and no smelting, glass, or kiln work is possible except by magma,
  which the fort does not have.
* **Fourteen carpenter reactions have no job.** The raws verify 23
  reactions; JOB_SPECS covers 9. Missing: casket, hatch cover,
  grate, bookcase, pedestal, display case, stepladder, splint,
  crutch, shield, buckler, training axe, training short sword,
  training spear. Fourteen jobs, all the same mechanism as
  make_bed, all 1 log each. The hospital cannot get a wooden splint
  or crutch from the harness today, and the fort cannot bury its
  dead in a wooden casket.
* **No hardcoded carpenter jobs.** MakeCage, MakeAnimalTrap,
  MakeTrapComponent, MakePipeSection, ConstructArmorStand,
  ConstructWeaponRack, and ConstructBlocks are real job types in
  the enum, and queue_job only accepts JOB_SPECS names, so none of
  them can be queued. Whether act_job.lua can drive a hardcoded job
  type the same way it drives a reaction is UNVERIFIED.
* **No craftsdwarf wood jobs.** No wooden crafts, no wooden bolts,
  no wooden toys, cups, jugs, or pots. The trade fallback the
  trading plan names (wood goods when stone is short) cannot be
  produced by the harness.
* **No chop task, no chop suggestion, no wood floor.** TASK_DEFS has
  six tasks: brew, cook, make_bed, make_barrel, gather, farm. There
  is no chop task. The planner has no wood threshold: nothing fires
  when wood falls, nothing suggests chopping, nothing sizes a chop
  box by need. Wood is watched only as a number in the Stocks line.
* **No axe check.** The catalog warns that axes are a separate item
  from picks, but nothing counts axes in stock. A chop designation
  with no axe in the fort creates FellTree jobs no dwarf can work,
  and the harness would not know why. The stocks collect counts
  every item type in by_type, but the snapshot never renders axes.
* **No tree count in the snapshot.** map.lua counts trees, observe.py
  logs them, and the model never sees them. The agent cannot tell
  a forest from a cleared field without a query, and there is no
  query route that returns the count.
* **No wood by species.** stocks.lua carries by_material with a
  brewable flag on plants, but the snapshot's "By material" line
  shows only the top 8 entries by units, and nothing surfaces which
  wood species the fort holds. Feather tree logs for light bins and
  blood thorn for bolts are invisible to the model.
* **No charcoal, ash, or potash counts.** stocks.lua does not count
  charcoal, ash, or potash as headline numbers, and the snapshot
  never renders them. The fuel state of the fort is invisible until
  a furnace exists to need it, and then it is still invisible.
* **No bed assignment and no dormitory.** The planner places beds in
  a grid from bed_origin, but nothing creates a dormitory zone and
  nothing assigns a bedroom. ZONE_KINDS has garbage_dump, and the
  zone machinery in act_zone.lua exists, but no plan or task uses a
  bedroom zone. A placed bed with no zone is a bed no dwarf is
  assigned to sleep in.
* **No woodcutter assignment.** Nothing picks who cuts wood. The
  WOODCUTTER labor is toggled by hand, and the planner never checks
  whether a woodcutter exists, whether they have an axe, or whether
  they are alive. The same gap the kitchen doc names for the cook
  exists here for the woodcutter and the carpenter.
* **No burn-rate policy for wood.** The Store trends wood, and the
  snapshot prints its burn rate, but no floor and no decision reads
  it. Wood can fall for a season before anything notices.

## 6. The wood budget: the ledger

The budget is arithmetic from verified numbers, not a feeling. Every
carpenter item costs 1 log. Every charcoal bar costs 1 log. Every ash
bar costs 1 log. A brew costs 1 empty barrel, and a barrel costs 1 log.

### 6.1 The floors

The fort holds three floors, in priority order. A floor is a number
the harness defends: wood below a floor is never spent on anything
below that floor in priority.

1. **Bed floor.** One bed per citizen, placed or as a bed item in
   stock. 7 citizens need 7 beds. Each bed is 1 log, so the bed
   floor is citizens logs, plus the beds already placed. Migrants
   move the floor: a wave of 5 moves it by 5 logs and 5 beds.
2. **Barrel floor.** Enough barrels to hold the drink floor, plus
   empties to brew the next batch. The drink floor is population
   times 5 per season, plus one season of reserve (KITCHEN.md,
   section 3.3). Each brew makes 5 drink into 1 barrel, so the
   barrels in circulation at the floor are drink floor divided by
   5. For 7 dwarves: drink floor 70, barrels in circulation 14,
   plus 3 empty barrels to brew the next batch, so a barrel floor
   of 17. That arithmetic is for the 7 citizens of the clean base;
   the floor moves with migrants, 2 logs per extra dwarf. The fort
   has 15 total, 3 empty: it is 2 barrels short of its own floor,
   which is exactly why brews failed in M1 runs 17 and 17b. Each
   barrel is 1 log, so the barrel floor is 17 logs for 7 dwarves
   (one barrel per 5 drink of floor, roughly).
3. **Charcoal floor.** Zero until a furnace exists that burns fuel.
   Once the wood furnace and a smelter exist, the floor is the fuel
   the next season of smelting needs, and it is computed from the
   smelting plan, not guessed. Until then, charcoal is not a floor,
   it is a spend, and it never spends below floors 1 and 2.

The combined hard floor for 7 dwarves is 7 bed logs plus 17 barrel
logs, 24 logs, before a single log is spent on bins, buckets,
charcoal, furniture, or trade. Wood 117 covers that floor almost
five times over. The fort is not wood poor. It is barrel poor and
carpenter-time poor.

### 6.2 The burn rate and the days-remaining rule

The Store already trends wood and the snapshot prints "wood is
falling X/day, Y days left" when it falls. The budget adds the
interpretation, which the harness computes and the agent reads:

* **Carpenter burn.** Count carpenter jobs completed per day from
  the job events, times 1 log. A carpenter finishing 3 beds a day
  burns 3 logs a day.
* **Charcoal burn.** Count MakeCharcoal jobs per day, times 1 log,
  once the furnace exists.
* **Chop income.** Count logs hauled to the wood stockpile per day.
  Chop income minus carpenter burn minus charcoal burn is the net
  wood trend, and the days-remaining figure must use the net trend,
  not the gross burn. A fort chopping 5 logs a day and burning 3 is
  gaining wood while the snapshot says "falling" if it only counts
  the burn. UNVERIFIED: whether the Store's trend already nets
  chop income against burn. Phase 1 verifies it against the live
  game.
* **The chop trigger.** When days remaining at the net trend falls
  below 30 days, the harness suggests a chop sized to restore 60
  days of wood: trees to mark equal to 60 days of net burn divided
  by the measured logs per tree. When wood is above the hard floor
  and days remaining is above 60, no chop is suggested, however big
  the forest is. Chopping is driven by the budget, not by the sight
  of trees.

### 6.3 The barrel ledger

The barrel ledger is the part of the budget the fort keeps getting
wrong, so it is stated exactly. Barrels exist in three states, and
the snapshot must carry all three, not a total:

* Empty barrels: can take a brew. The brew check reads this number
  and nothing else.
* Barrels full of drink: drink in storage. Drink units divided by 5
  is approximately this number, since one barrel holds one stack.
* Barrels full of food: food in storage. Seeds in bags go in
  barrels too, and a barrel of seeds is not an empty barrel.

The fort's own history is the proof: 15 barrels, 3 empty, brew x5
requested, 2 jobs that could never run, then 20 MAKE WOODEN BARREL
jobs queued at once while no brew could run (coordinator log,
M1 run 17b). The ledger prevents the repeat: the planner queues
barrels only up to the barrel floor, and the queue size is the
shortfall, not a round number. Three missing barrels means queue 3,
not 20. A barrel job takes carpenter time that a bed job needs, and
20 barrel jobs is 20 logs and a season of carpenter time spent
solving a 3 barrel problem.

## 7. Woodcutting policy

* **Chop by the budget, not by the forest.** A chop is suggested
  only when section 6.2 says so, or when a building needs a cleared
  site. The chop box is sized to the need: trees to mark equal to
  the logs wanted divided by the measured logs per tree, and the box
  is drawn around the nearest standing trees to the entrance, not
  across the map.
* **Axe first.** Before any chop designation, the harness checks
  that an axe item exists in stock and that a dwarf has the Wood
  Cutting labor. A chop with no axe is refused with the reason
  named ("no axe in stock: trade for one or make one"). The axe
  count becomes a headline number in the woodworking observation
  (phase 1), because the catalog already warns about it and nothing
  counts it.
* **One woodcutter, one backup.** The woodcutter is the dwarf with
  the highest woodcutting skill, with a backup who keeps the labor
  warm. The woodcutter is not also the planter or the brewer; the
  assignment refuses a choice that would leave the farm or the
  still without a worker.
* **Never clear the entrance.** Trees near the entrance are shade,
  cover, and a windbreak for the depot path, and the wagon path
  needs 3 tiles clear, not a clear-cut. The chop box never covers
  the depot approach, and never covers the whole forest. Regrowth
  is random and slow (about three and a half months a sapling),
  so a clear-cut is a season of no wood, not a harvest.
* **Never chop below a dug tile.** Check the tile below each trunk
  before marking: if it is dug open, chopping leaves a hole to the
  surface. The harness refuses the box and names the hole.
* **Hauling follows the cut.** A felled tree is a log on the ground,
  not wood in stock, until a hauler carries it to the wood
  stockpile. The wood stockpile sits near the entrance and the
  carpenter, and the chop box sits near the stockpile, so the haul
  is short. Logs left on the ground are counted as unhauled in the
  observation, and a log unhauled for a season is a diagnosed
  failure with the cause named (no hauler, no stockpile space,
  no path).
* **Elves and the quota.** Elves detest tree cutting, and an elven
  liaison can set a tree-cutting limit the fort is expected to
  respect. Cutting past it angers the elves and can end trade.
  Whether the harness can read the quota from the game state is
  UNVERIFIED (section 18, open question 5). Until the probe
  answers it, the harness counts trees felled per year and the
  snapshot carries the count, so the agent can see the scale of
  the cutting before the elves arrive in spring.

## 8. Carpenter production priorities

The carpenter has one worker and one job at a time. The queue order
is the priority order, and the harness enforces it. The agent picks
the batch size; the harness picks the order.

1. **Beds, to the bed floor.** One bed per citizen, then stop.
   Beds are survival: a dwarf with no bed sleeps on the floor.
2. **Barrels, to the barrel floor.** Only up to the shortfall, never
   a round number. Three missing barrels means queue 3.
3. **Buckets, to 2 in stock.** Buckets carry water for the hospital
   and the well, lye for the ashery, and milk for the kitchen. Two
   is enough until a use needs more.
4. **Bins, to the bin need.** One bin per 12 bars, 303 cloth, 45
   leather, 305 small gems, or the finished goods stockpile's need
   (STOCKPILES.md, section 5.1). Bins are made when a stockpile
   reports it has no empty bin, not on a schedule.
5. **Caskets, crutches, splints.** One casket per unburied citizen
   corpse, one crutch and one splint per wounded dwarf who needs
   them. These are made on demand from the death and wound records,
   not stockpiled.
6. **Furniture for rooms.** Tables, chairs, doors, chests, cabinets,
   bookcases, pedestals, display cases, stepladders, hatch covers,
   grates. These are made when a room is being furnished, in the
   room's order, not before the room exists.
7. **Trap parts, cages, animal traps.** Made when the military or
   hunting plan asks for them, in the numbers it asks for.
8. **Training weapons, shields, bucklers.** Made when the military
   plan asks for them.
9. **Crafts and trade goods.** Last. Wood crafts are made only from
   wood above all the floors, and only in the season before the
   caravan they serve, because a craft made in spring for a caravan
   in autumn is a log that could have been a barrel in summer.

A batch is never larger than the wood above the floors. If the fort
holds 117 logs and the hard floor is 24, the carpenter can spend 93
logs on discretionary work, but only a batch at a time, because a
migrant wave can move the floors by 10 logs overnight and a 93 log
queue cannot be unmade.

## 9. Charcoal and fuel policy

* **Charcoal exists to feed furnaces, nothing else.** The wood
  furnace makes charcoal for the smelter, the forge, the glass
  furnace, and the kiln. Until one of those exists and has a job
  that needs fuel, charcoal is not made at all. Making charcoal
  early is burning beds and barrels for a pile of fuel with no
  furnace to burn it in.
* **Never burn below the floors.** A MakeCharcoal job is refused
  when wood is at or below the hard floor (bed floor plus barrel
  floor). The refusal names the floor: "cannot burn charcoal:
  wood 24 is the bed and barrel floor for 7 dwarves".
* **One log, one bar, no skill bonus.** Wood burner skill shortens
  the job, it does not change the yield. A dabbling wood burner
  makes the same charcoal as a legendary one, slower. So the
  charcoal worker is whoever is free with the labor, not a
  specialist to train, until the furnace is the bottleneck.
* **Ash is a separate decision from charcoal.** Ash and charcoal
  both cost 1 log, and they compete for the same logs. Ash is made
  when the ashery needs it for potash or lye, and only in the
  amount the ashery needs. The farming plan's fertilizer rule
  decides the potash amount; this doc decides the log spend, and
  it refuses ash above the potash need.
* **Coke replaces charcoal when it exists.** Bituminous coal or
  lignite make coke, and coke is not wood. If the fort finds coal,
  the fuel plan switches to coke and wood stops being burned for
  fuel entirely, because every log burned is a bed or a barrel the
  fort did not make. Whether the fort's stone layers hold coal is
  UNVERIFIED until the survey reads it (section 18, open
  question 6).
* **Magma replaces both, later.** A magma smelter, forge, glass
  furnace, and kiln need no fuel at all. If the fort reaches magma,
  the charcoal policy ends. The fort does not have magma today,
  and the wood furnace is the bridge, not the destination.

## 10. Beds and sleep policy

* **Dormitory first.** The first beds go in a dormitory zone, one
  zone holding every bed, until every citizen has a bed. A dwarf
  sleeping in a dormitory gets a negative thought, and a dwarf
  sleeping on the floor gets a worse one. The dormitory is the
  least bad option while beds are scarce, and it is the fastest:
  one zone, no rooms to dig.
* **Bedrooms second.** Once every citizen has a bed, new beds go in
  individual bedrooms, smallest first: a 1 by 1 bedroom with only
  a bed gives the good thought, and a 3 by 3 engraved bedroom gives
  the best one. Bedrooms are dug when the fort has hands to spare,
  not while beds are still missing.
* **One bed per citizen, always.** The floor is citizens, and it is
  recomputed when migrants arrive. A migrant wave that doubles the
  fort doubles the bed floor the same day, and the carpenter queue
  is re-prioritized the same tick: beds first, everything else
  waits.
* **Beds are placed, not stockpiled.** A bed item in stock is not a
  bed a dwarf sleeps in. The planner already places bed items in a
  grid from bed_origin; the design adds the dormitory zone around
  the grid, so a placed bed is a bed in a zone, and the snapshot
  carries placed beds, bed items in stock, and citizens, as three
  numbers, so the gap is visible.
* **Noise.** Bedrooms sit at least 8 levels below the woodcutting,
  or away from it. A bedroom above the chop box is a bedroom where
  nobody sleeps.

## 11. Crafts and trade policy

* **Stone first, wood second.** The trading plan already sets this:
  stone mugs and crafts are the default trade good, because stone
  is free and unlimited. Wood crafts are the fallback when stone
  is short or when the caravan wants variety. A log spent on a
  craft is a log not spent on a bed, so wood crafts are made only
  from wood above the floors, and only in the season before the
  caravan they serve.
* **Never trade wood to elves.** Elves refuse wood, wood
  derivatives, and anything with a wooden part, and one wrong item
  ends the session. The elf filter in the trading plan already
  refuses wooden goods for the spring caravan; this doc adds that
  the harness must never put a wooden item in the trade stockpile
  in spring, even by accident, because a wooden cage holding an
  acceptable animal is refused for the cage, not the animal.
* **Bolts are the best wood trade by value per log.** One log makes
  25 wooden bolts worth about 25, against about 20 for crafts and
  10 for a bed. Bolts are also the fort's own ammunition for
  training and hunting. The craftsdwarf's workshop makes them, so
  the bolt route waits on the craftsdwarf build (phase 7).
* **Value is quality, not volume.** A craft's value is its base
  times its material multiplier times its quality modifier, and a
  skilled wood crafter makes more valuable crafts from the same
  log. The harness prefers one skilled crafter making a few good
  crafts over many dwarves making poor ones, and it never queues
  crafts as a way to use up wood: surplus wood is a stockpile,
  not a production order.

## 12. Traps policy

* **Cage traps first.** A wooden cage in a cage trap can hold any
  creature indefinitely, even trolls and megabeasts, and never
  fails except against trapavoid creatures. Cages are the highest
  value wooden trap part in the game, and the carpenter makes them
  with the MakeCage job. The military doc owns where cage traps go;
  this doc owns making the cages, one per trap the military plan
  asks for.
* **Weapon traps need mechanisms.** Every trap except upright
  spears uses a mechanism, and the mechanism quality decides the
  skill the weapon is used with. A wooden menacing spike or spiked
  ball in a weapon trap is only as good as its mechanism. The
  harness never queues a wooden trap component without checking
  that a mechanism exists for it, or the component sits in stock
  with no trap to go in.
* **Animal traps are hunting gear.** A wooden animal trap catches
  live small animals for taming and hunting. The hunting doc owns
  the use; this doc owns the making, one per trapper who asks.
* **Wooden trap parts are a fallback, not a first choice.** Metal
  trap components hit harder and last longer. Wood is used when
  the fort has no metal, or when the part is a cage, where wood
  holds anything. The harness never spends wood above the floors
  on trap parts while the fort has no metal and no cages: cages
  first, spikes second.

## 13. Layout

Layout is scored placement (docs/SITE_SELECTION.md, queued work),
with woodworking factors on top of the shared threat, cover, and
traffic factors:

* **The triangle.** Carpenter's workshop, wood stockpile, and wood
  furnace belong together, within a few tiles of each other. The
  carpenter hauls logs from the stockpile, the furnace hauls logs
  from the same stockpile, and both workshops' outputs go to the
  furniture and bars stockpiles nearby. A carpenter far from its
  wood stockpile pays the hauling cost on every item.
* **The wood stockpile sits near the entrance and the carpenter.**
  Logs travel far and take long to haul, so the stockpile is close
  to where logs arrive (the entrance) and close to where they are
  used (the carpenter). Small wood stockpiles near the felling
  areas feed one large primary stockpile near the carpenter
  (STOCKPILES.md, section 4.2). Wood stockpiles take no bins or
  barrels and no wheelbarrows: logs weigh about 30 and do not slow
  an average dwarf, and wheelbarrows would cut the number of
  simultaneous log hauls.
* **The carpenter sits near the still and the kitchen.** Barrels
  made at the carpenter go to the still, and the still is beside
  the kitchen and the food stockpile. A barrel hauled across the
  fort is a brew delayed, and the barrel ledger in section 6.3 is
  the reason the distance matters.
* **The wood furnace sits near the wood stockpile and the smelter.**
  Charcoal goes to the smelter, ash goes to the ashery. The furnace
  is a fire risk: it sits away from the food stockpile full of
  wooden barrels, and away from the main corridor, because a fire
  in a wooden barrel stockpile is a fort-ending event.
* **The chop box sits near the entrance, not across the map.** The
  haulers carry logs from the chop box to the wood stockpile, and
  the shorter that haul, the faster wood reaches the carpenter.
  The chop box never covers the depot approach, and never covers
  ground the fort plans to build on.
* **Noise.** Woodcutting noise reaches 8 tiles. The carpenter's
  workshop is a workshop, not a bedroom, so it can sit near the
  cutting, but the dormitory and bedrooms sit at least 8 levels
  below it or away from it.

## 14. Failure modes

Every failure mode in this table has a diagnosis the harness must
produce, with the fix named. A silent zero is never acceptable.

| Failure | Cause | Diagnosis | Fix |
| --- | --- | --- | --- |
| No beds, dwarves sleep on the floor | Carpenter idle, no wood, no carpenter, or beds unplaced | "beds N placed, M citizens, K bed items in stock, wood W" | Make beds to the floor, place the items, or build the carpenter |
| Brew fails for no empty barrels | Barrels full of drink or food, carpenter not making barrels | "empty barrels 0, brewable plants N, barrels total M" | Queue barrels to the shortfall only, never 20 at once |
| Carpenter queue of 20 barrels, no brew | Planner queued a round number, not the shortfall | "barrel jobs queued 20, shortfall 3" | Queue the shortfall; refuse round-number batches |
| FellTree jobs never worked | No axe in stock, or no dwarf with Wood Cutting | "FellTree jobs N, axes 0" or "no woodcutter assigned" | Trade for or make an axe; assign a woodcutter |
| Logs rot on the ground | No hauler, no wood stockpile space, no path | "logs unhauled N, wood stockpile full" | Add haulers, expand the stockpile, check the path |
| Wood falls below the floors | Charcoal or crafts spent the reserve | "wood W, hard floor F, charcoal burned C" | Stop discretionary spends; chop to restore 60 days |
| Charcoal made with no furnace to burn it | Furnace built before the smelter, or charcoal queued early | "charcoal N, fuel consumers 0" | Do not make charcoal until a consumer exists |
| Depot path blocked by trees | Forest grew over the wagon path | "wagon path blocked at (x, y)" | Chop the impeding trees, recheck depot access |
| Hole to the surface under a cut tree | Dug tile below the trunk before cutting | "open floor at (x, y, z) under a felled tree" | Build a floor over the hole, or a wall below it |
| Wooden goods offered to elves | Trade stockpile held wood in spring | "wood items in trade stockpile, elves present" | Remove wood from the trade stockpile; refuse the offer |
| Casket missing for a dead dwarf | No casket job in JOB_SPECS, corpse unburied | "citizen dead, caskets 0, coffins placed 0" | Add make_casket (phase 2); place the casket |
| Splint or crutch missing for a wounded dwarf | No splint or crutch job in JOB_SPECS | "wounded dwarf N, splints 0, crutches 0" | Add make_splint and make_crutch (phase 2) |
| Carpenter starved by distance | Wood stockpile far from the carpenter | "carpenter idle, wood W, distance D tiles" | Move the wood stockpile next to the carpenter |
| Fire in the wooden barrel stockpile | Wood furnace or magma near wooden barrels | "fire at (x, y, z), barrels burning" | Separate the furnace from the food stockpile; use metal barrels if fire is a concern |

## 15. Model presentation

This section is required by Mikey's 2026-11-27 direction on
information presentation (coordinator log, 18:10 PT): the snapshot
stays an index, token budgets hold, and every system states how its
information reaches the model and what it costs. The numbers below
are computed from the proposed text with the accountant's own rule
(TokenAccountant.count: length divided by 3, conservative; wire
estimate about 4 characters per token). They are estimates, and the
coordinator verifies them against the live assembler before commit,
per the same direction. If the live numbers disagree, the live
numbers win and this section is corrected.

### 15.1 The snapshot: what reaches the model every tick

The snapshot gains a Woodworking section of 5 lines when quiet, 6
when an attention item fires. It is counts and exceptions, never a
dump. The Stocks line already carries wood and empty barrels today
(assembler.py, _stocks), so those two numbers cost 0 new tokens;
the Woodworking section adds the bed, barrel, charcoal, tree, and
workshop state that the Stocks line cannot carry.

Proposed quiet text. Only two numbers in it are live values: wood 117
and barrels 15 total with 3 empty, both read from the game on
2026-11-27. The rest are illustrative, showing the shape, and phase 1
replaces them with live values when the section is verified.

```
Woodworking: wood 117 (falling 2.1/day, 55 days left), 12 logs unhauled, 41 trees standing.
  Beds 5 placed for 7 citizens, 2 bed items in stock; carpenter #7 built, idle.
  Barrels 15 total, 3 empty; bins 4, buckets 2.
  Charcoal 0, ash 0, potash 0; wood furnace: none.
  Woodcutter: 1 dwarf; axes in stock: 1.
```

Proposed attention line, added as a sixth line only when it fires:

```
  Attention: brew blocked, 0 empty barrels with 1 brewable plant; make 2 barrels.
```

What each line is:

* Line 1 is a count plus a trend (wood, days left from the Store's
  trend, unhauled logs, standing trees). The days-remaining figure
  uses the net trend (chop income minus burn), per section 6.2.
* Line 2 is a count against a floor (placed beds vs citizens, bed
  items in stock) plus the carpenter's state and id, so the model
  can queue a job without a query turn. The carpenter id is already
  in the Buildings line; it is repeated here because the bed and
  barrel decisions need it in the same breath as the numbers.
* Line 3 is the barrel ledger (total, empty) plus bins and buckets.
  The empty count is repeated from the Stocks line deliberately:
  it is the brew bottleneck, and the KITCHEN.md precedent keeps a
  bottleneck number where the decision is made, not only where the
  stocks live.
* Line 4 is a count (charcoal, ash, potash) plus the wood furnace
  state. While there is no furnace it reads "wood furnace: none",
  so the model never has to guess whether charcoal can be made.
* Line 5 is a count (woodcutters, axes). The axe count is the
  precondition for every chop, and it is invisible today.
* Line 6 is an exception, present only when it fires: brew blocked,
  wood below the hard floor, or logs unhauled for a season. It is
  ranked with the other attention entries, never buried in a list.

Token cost, by the accountant's rule (length divided by 3):

* Quiet section: 311 characters, 103 tokens by the accountant,
  77 tokens on the wire. Counted from the proposed text above with
  the accountant's rule, not estimated.
* With the attention line: 393 characters, 131 tokens by the
  accountant, 98 tokens on the wire.
* At 7 dwarves and at 50 dwarves, the cost is the same within
  about 10 tokens. The section carries counts only, no per-dwarf
  lines, so it does not grow with population. The growth at 50
  dwarves lands in the Units section (exceptions capped at 8) and
  the profession counts (top 8), not here. A second carpenter or a
  second wood furnace adds one short clause to line 2 or line 4,
  about 15 tokens, and only while it exists.
* Against the budgets (target 30K, warning 60K, compaction 100K,
  never over 140K on a 200K window), the quiet section is about
  0.4 percent of the target, and the whole snapshot stays an index
  at about 4,700 tokens typical. The section is a budget decision
  reviewed against the accountant, not a default, and its cost is
  stated here so the review can check it.

What is not in the snapshot, and why:

* Not the tree list. Trees are positions on the map, and a list of
  them grows with the map. The count is in line 1; the positions
  live behind the query route.
* Not wood by species. Species matter for two decisions (feather
  tree for light bins, blood thorn for bolts), and both are rare
  enough to be a query, not a tick. The top-8 "By material" line in
  Stocks already surfaces a species when it is a large share.
* Not the full furniture inventory. Beds, barrels, bins, and
  buckets are the bottleneck goods; tables and chairs are not, and
  their counts live behind the query route.
* Not the carpenter reaction list. Twenty-three reactions live in
  the catalog, read on demand for the action the model needs, per
  the 6-tool surface rule. The snapshot never carries a menu.
* Not charcoal burn projections beyond the trend line. The trend
  line says falling or rising and days left; the projection is a
  query.

### 15.2 The query route

GET /v1/woodworking returns the full detail, read from the fresh
collect, not from a cache. The snapshot carries the summary; the
route carries the detail. The agent asks the route when it needs
to choose, never as a matter of routine.

Response shape:

* Wood: total units and stacks, units by species (when the collect
  supports it; UNVERIFIED today, section 18), unhauled logs with
  their positions, trees standing with a bounding box (not a list
  of every tree).
* Beds: placed count, bed items in stock, citizens, the shortfall,
  dormitory and bedroom zones if any.
* Barrels: the ledger (empty, full of drink, full of food), bins,
  buckets, and the barrel floor from section 6.1.
* Fuel: charcoal, ash, potash, lye, pearlash counts; the wood
  furnace and ashery and kiln, with ids and job counts, or "none".
* Workshops: the carpenter and wood furnace with ids,
  construction stage, current jobs, and queued jobs.
* Labor: woodcutters and carpenters by name and skill, axes in
  stock, and whether each assignment has a backup.
* Budget: the three floors, the net burn rate, days remaining at
  the net trend, and the chop size the budget recommends, if any.

The snapshot carries the pointer so the model knows the route
exists: the carpenter id in line 2 and the wood and empty barrel
counts in line 1 and line 3 are the pointer. The route is one
query; the existing /v1/stocks and /v1/buildings routes already
answer the wood total and the workshop list, and this route adds
the bed, barrel, fuel, and budget detail those routes do not
carry.

### 15.3 The briefing

No woodworking briefing exists today. The briefing kinds in
briefings.py are new_arrival, cavern_creature, citizen_new,
hostile, invasion, strange_mood, caravan, unit_death, low_drink,
and low_food. The woodworking system adds one kind, low_wood,
when phase 4 lands. It fires on exactly two triggers, and only
then:

* Wood falls below the hard floor (bed floor plus barrel floor)
  while a carpenter job is waiting on wood, or
* Empty barrels are 0 while brewable plants exist, so brewing is
  blocked for want of barrels.

The briefing follows the existing shape: what, matters, options,
cost, one or two sentences per field, and the whole briefing is a
few hundred tokens at most (briefings.py). Estimated cost: about
120 to 180 tokens by the accountant, about 90 to 135 on the wire,
for the four fields plus the numbers that name the shortage. The
estimate is computed from the existing low_drink briefing, which
is the same shape and length; the coordinator verifies it against
the live briefing text before commit.

What the briefing covers: the shortage (wood below the floor, or
zero empty barrels with plants to brew), what it blocks (beds,
barrels, or brews), and the fix (chop, make barrels, or both) with
the numbers attached. What it leaves to a query: the tree
positions, the species breakdown, and the full budget. The
briefing never fires for a discretionary shortage: charcoal at
zero with no furnace is not a briefing, and bins at zero is an
attention line, not a briefing.

### 15.4 Opportunities

The opportunities section does not exist in the code yet (gap
review 3, P2-3: the only "opportunit" hit in src/ is a briefing
string). Until that gap closes, the entries below have nowhere to
land, and this doc does not pretend otherwise. When the mechanism
lands, woodworking contributes at most 3 entries, each facts plus
a query route, never a suggestion, never a pause, and ignoring one
costs nothing:

* "Feather tree logs in stock (12). Light wood for bins and
  buckets. Query: GET /v1/woodworking."
* "Blood thorn logs in stock (8). Dense wood for bolts. Query:
  GET /v1/woodworking."
* "Standing trees 41 near the entrance. Chop would restore about
  60 days of wood. Query: GET /v1/woodworking."

An opportunity is not a suggestion: it carries no recommended
action and no priority, and the suggestion uptake metrics do not
count it. If the mechanism never lands, the snapshot and the
briefing still carry the system, and nothing is lost except the
low-pressure channel.

### 15.5 What the system deliberately does NOT push

* The full tree list, with coordinates. It grows with the map and
  the model does not decide from it. The count and the bounding
  box are the push; the list is a query.
* Wood by species per tick. Two decisions need species, both rare,
  both queries.
* The full furniture inventory. Only the bottleneck goods (beds,
  barrels, bins, buckets) are pushed. The rest is a query.
* The carpenter reaction list. Twenty-three reactions are a menu,
  and a menu in the snapshot is a script, not an index. The
  catalog carries them, read on demand.
* Charcoal and ash projections. The trend line is pushed; the
  projection is a query.
* Per-dwarf woodcutting or carpentry skill. The assignment (who,
  and whether a backup exists) is in the query route. The snapshot
  carries the count of woodcutters, not their skill table.
* The elf tree quota, even if the probe finds a read route. A quota
  is a number the agent needs before the spring caravan, not every
  tick. It arrives as a briefing when the elves are coming, and as
  a line in the query route the rest of the year.

The reason in every case is the same: the snapshot is an index, and
an index carries counts, exceptions, and diffs. Anything the model
needs once a season, or once per decision, lives behind the query
route. Pushing it every tick would grow the snapshot toward the
budgets for information the model reads once and forgets.

## 16. Implementation phases

Each phase ends with a concrete live-verification bar. Nothing counts
as done until it passes its bar against the real game. Every phase
carries offline tests (including malformed-input tests per the
standing rule) and goes through the pre-push self-review gate before
it is committed and pushed.

### Phase 1: Observation

* Extend the stocks collect so the snapshot can see what
  woodworking needs: charcoal, ash, potash, and lye counts as
  headline numbers; axes in stock; bed items vs placed beds; the
  barrel ledger split (empty, full of drink, full of food); unhauled
  logs; standing trees from the map read; wood by species where the
  collect supports it.
* Add the Woodworking section to the snapshot (section 15.1) and
  the GET /v1/woodworking route (section 15.2).
* Verify whether the Store's wood trend already nets chop income
  against burn (section 6.2). If it does not, fix the trend before
  the days-remaining figure is trusted.
* Live bar: a live collect on the main fort shows the true wood,
  barrel, bed, charcoal, and tree numbers, and each number matches
  a hand check against the game. The snapshot Woodworking section
  renders, and its token cost matches section 15.1 within 20 tokens
  by the accountant's count.

### Phase 2: Carpenter job coverage

* Add the fourteen missing reaction jobs to JOB_SPECS, materials.py,
  and the catalog, in the same shape as make_bed: casket, hatch
  cover, grate, bookcase, pedestal, display case, stepladder,
  splint, crutch, shield, buckler, training axe, training short
  sword, training spear. All are 1 log each, all are CustomReaction
  211, all use the existing queue_job mechanism.
* Probe the hardcoded jobs (MakeCage, MakeAnimalTrap,
  MakeTrapComponent, MakePipeSection, ConstructArmorStand,
  ConstructWeaponRack, ConstructBlocks) through act_job.lua with the
  job type name and no reaction, and record which ones the route
  can drive. Add the ones that work; document the ones that do not,
  with what blocked them, and do not pretend otherwise.
* Live bar: each new job queues live at the carpenter and produces
  the item, read back from the game. A casket, a splint, and a
  crutch are made and read back, because those three are the ones
  the fort cannot do without. A cage is made and read back, because
  the cage trap is the highest value wooden trap part.

### Phase 3: Wood furnace and fuel

* Add a furnace build kind to WORKSHOP_CATALOG (wood_furnace, built
  from fire-safe stone or metal) and the build route for furnaces,
  which are a different building family from workshops in the enum.
* Add make_charcoal and make_ash to JOB_SPECS as hardcoded job
  types with reaction_name None, 1 log each, with the material
  rule in materials.py.
* Add the fuel ledger to the observation: charcoal, ash, and the
  fuel consumers that exist (smelter, forge, glass furnace, kiln),
  or "none".
* Live bar: a wood furnace is built live on the scratch fort, 1 log
  becomes 1 charcoal read back, and 1 log becomes 1 ash read back.
  A MakeCharcoal job is refused live when wood is at or below the
  hard floor, with the floor named.

### Phase 4: Budget, floors, and planner decisions

* Implement the three floors (bed, barrel, charcoal) from section
  6.1, recomputed every tick from the live citizen count and the
  drink floor. Wire the barrel shortfall rule into the planner:
  queue the shortfall, never a round number.
* Replace the planner's barrel fallback (make_barrel x3 when empty
  barrels are 0) with the floor-based queue, and add the bed
  decision's missing half: queue beds when bed items are short, not
  only when placed beds are short.
* Add the low_wood briefing (section 15.3) on its two triggers.
* Add the chop suggestion: when days remaining at the net trend
  falls below 30, suggest a chop sized to restore 60 days, with the
  box drawn around the nearest standing trees to the entrance.
* Live bar: a live M1 day holds the bed and barrel floors without
  the model being asked, the barrel queue equals the shortfall
  (not 20), and a brew succeeds because an empty barrel existed
  when it was queued. The low_wood briefing fires live on a
  forced shortage and names the shortage.

### Phase 5: Chop discipline

* Add the chop task to TASK_DEFS (designate_chop plus a wait for
  FellTree jobs and a wait for the logs to reach the wood
  stockpile), with the axe check and the woodcutter check as
  preconditions.
* Add the chop box sizing from the budget, the dug-tile check below
  each trunk, and the depot approach exclusion.
* Add the tree-felled-per-year count to the observation, for the elf
  quota watch.
* Live bar: a chop is designated live, FellTree jobs appear, logs
  are hauled to the wood stockpile and read back, and the wood
  count rises by the measured logs per tree. A chop with no axe in
  stock is refused live with the reason named.

### Phase 6: Beds and sleep

* Add the dormitory zone action (bedroom zone kind in the zone
  machinery) and the planner decision that builds it around the
  placed beds.
* Add bedroom assignment once every citizen has a bed: smallest
  rooms first, 1 by 1, then 3 by 3 engraved when hands allow.
* Live bar: dwarves sleep in placed beds in the dormitory, and the
  snapshot shows placed beds equal to citizens with no floor
  sleepers in the exceptions. A migrant wave moves the bed floor
  and the carpenter queue re-prioritizes to beds first, verified
  live.

### Phase 7: Crafts, bolts, and traps

* Add the craftsdwarf's workshop build kind and the wood craft and
  wooden bolt jobs (1 log per stack of 25 bolts), plus the bowyer's
  workshop for wooden crossbows.
* Add the trap component jobs that phase 2 proved drivable, wired
  to the military plan's ask (cages first, spikes second).
* Wire the elf filter: no wooden item enters the trade stockpile
  in spring, enforced in code, not by the agent remembering.
* Live bar: a batch of wood crafts is made live and its value is
  read back; a stack of 25 wooden bolts is made from 1 log and read
  back; a cage trap is built with a wooden cage made by the
  harness. A wooden item is refused from the spring trade stockpile
  live, with the elf rule named.

### Phase 8: Ashery chain

* Add the ashery build kind (block, barrel, bucket components) and
  the lye and potash jobs, shared with FARMING_PLAN.md phase 3,
  which owns the fertilizer decision. This doc owns the wood side:
  the ash supply, the log spend, and the refusal when ash would
  spend below the floors.
* Add the kiln build kind and the pearlash job for the glass
  industry, when the kiln has fuel to burn.
* Live bar: ash becomes potash live, the potash stock is read back,
  and a fertilized plot uses it (the farming plan's bar). The ash
  spend is refused live when wood is at the hard floor.

## 17. Refusals

The woodworking system refuses, and says why, in plain words:

* Never burn wood for charcoal or ash at or below the hard floor
  (bed floor plus barrel floor). Fuel is discretionary; beds and
  barrels are survival.
* Never queue a round-number batch of barrels. The queue is the
  shortfall, and 20 barrel jobs for a 3 barrel problem is a refusal,
  not a strategy.
* Never chop without an axe in stock and a woodcutter assigned.
  A designation no dwarf can work is a lie in the job list.
* Never clear-cut the forest or the depot approach. Regrowth is
  random and slow, and the wagon path needs 3 tiles clear.
* Never chop above a dug tile. A hole to the surface is a door for
  whatever lives outside.
* Never trade wood or wooden goods to elves, in any season, and
  never put a wooden item in the spring trade stockpile.
* Never claim a furnace job the harness cannot queue. If
  MakeCharcoal has no JOB_SPECS entry, the harness says it cannot
  make charcoal, and does not queue a reaction by that name.
* Never use wood for construction when stone is available and wood
  is at the hard floor. Stone is free; wood is beds and barrels.
* Never claim a tree count, a species breakdown, or a charcoal
  stock the collect cannot read. An unread number is UNVERIFIED,
  not zero.
* Never put the wood furnace next to the food stockpile full of
  wooden barrels. Fire in that stockpile is a fort-ending event.

## 18. Open questions (UNVERIFIED)

1. **Hardcoded job route.** Can act_job.lua drive MakeCage,
   MakeAnimalTrap, MakeTrapComponent, MakePipeSection,
   ConstructArmorStand, ConstructWeaponRack, and ConstructBlocks
   through queue_job with a JOB_SPECS entry that has reaction_name
   None? The enum proves the job types exist; the route is
   unproven. Phase 2 probes it.
2. **Furnace build route.** Can build_workshop build a furnace
   (WoodFurnace) through the same constructBuilding call as a
   workshop, or does the furnace family need a different call?
   WORKSHOP_CATALOG has no furnace kind, so the route is unproven.
   Phase 3 probes it.
3. **Wood by species.** Does the stocks collect carry wood species
   in by_material in enough detail to tell feather tree from oak?
   The collect covers WOOD in by_material, but the snapshot's top-8
   line may hide it. Phase 1 verifies it against the live collect.
4. **Net wood trend.** Does the Store's wood burn rate already net
   chop income against carpenter and charcoal burn, or does it
   count the burn only? Phase 1 verifies it against the live game.
5. **Elf tree quota.** Can the harness read the tree-cutting limit
   an elven liaison sets, and does the fort have one? The mechanic
   is real in 0.47.05; the read route is unproven. Phase 5 probes
   it; until then the harness counts trees felled per year.
6. **Coal on the map.** Does the fort's stone hold bituminous coal
   or lignite for coke? The survey has not reported it. Answered
   by live observation, not by guessing.
7. **Wooden blocks per log.** How many blocks one log makes through
   ConstructBlocks is unproven. Phase 2 measures it live.
8. **Axe supply.** How many axes does the fort hold, and can the
   stocks collect count them as a headline number? The catalog
   warns about axes; nothing counts them. Phase 1 verifies it.
9. **Bed quality and sleep.** Does a higher quality bed give a
   better sleep thought, and by how much? The wiki says bedrooms
   matter and quality matters for rooms; the exact bed effect is
   unproven. Answered by live observation, not by guessing.
10. **Underground wood.** Do the caverns below the fort hold
    underground trees the fort can cut when the surface runs out?
    The caverns are unbreached, so the question is unanswered until
    the fort digs down.

## 19. Sources

Wiki pages read from the local index
(`~/workspace/df-wiki-export/dfq.py`, hybrid search, 2026-11-27).
The index is a current-wiki export (4,485 pages, built 2026-11-24),
so pages can carry v50 markers; every claim below that depends on
the version was checked against the 0.47.05 raws or the live
runtime enum, and the check is named where it matters.

* Carpenter's workshop: the task list, the 1 log per item rule,
  beds only at the carpenter's, the Trapping requirement.
* Wood industry: log production, woodcutting, trading for logs,
  color, temperature, weight, the workshop table, ash, lye,
  potash, pearlash, charcoal.
* Wood: log value 3, size 50,000, 25 bolts per log, fire and
  magma safety, nether-cap.
* Tree: 1 log per trunk tile, growth about three and a half
  months, saplings random, wagon path 3 tiles, digging below a
  trunk leaves a hole, elves detest cutting.
* Tree farming: patience and luck, isolate the area, keep
  saplings untrampled.
* Wood furnace: fire-safe construction material, Wood burning
  labor, ash and charcoal products.
* Fuel: 1 log makes 1 charcoal, skill changes time not yield,
  coke from coal, charcoal the first reliable fuel.
* Ash: 1 log makes 1 bar of ash, used for potash and lye.
* Potash: fertilizer and pearlash, material value 3. The page
  carries a v50 preview marker; the chain itself (ash to potash
  to pearlash) matches the 0.47.05 raws and the farming plan.
* Barrel: value 10, capacity 60,000, wooden or metal.
* Bed: value 10, size 30,000, carpenter's workshop only.
* Bedroom, Dormitory, Zone, Sleep: claiming, the dormitory
  negative thought, sleep as a maintenance need.
* Bedroom design, Keeping your dwarves unstressed, Stress: the
  1 by 1 bedroom, the 3 by 3 engraved bedroom.
* Furniture industry: 1 log per item of wooden furniture.
* Furniture: building a bed from scratch, the Carpentry labor.
* Storage: barrels, bins, bags, pots, what goes in each.
* Trap, Trap component, Trap design: mechanisms, menacing spike,
  cage traps holding anything indefinitely, trapavoid.
* Animal trap: wooden, carpenter's workshop, Trapping labor,
  value 10, capacity 30,000.
* Wood crafter: wooden crafts, toys, instruments, cups, bolts,
  nest boxes, jugs, pots.
* Bolt: wooden bolts, 25 per log, training and hunting use.
* Maximizing value: the wood value table (crafts about 20,
  minecart 50, wheelbarrow 50, stepladder 50, bolts 25, bed 10,
  barrel 10).
* Noise: woodcutting noise 8 tiles.
* Stockpile, Stockpile design: wood near the entrance and the
  carpenter, no wheelbarrows for wood, logs about 30 weight.

0.47.05 raws, read from the shipped game
(`third_party/df_47_05/raw/objects/`):

* reaction_adv_carpenter.txt: the 22 MAKE WOODEN reactions
  (bed, chair, table, chest, cabinet, door, barrel, bucket,
  casket, hatch cover, grate, bin, stepladder, bookcase, splint,
  crutch, shield, buckler, training axe, training short sword,
  training spear, pedestal).
* reaction_other.txt: MAKE WOODEN DISPLAY CASE and
  CARVE_WOODEN_HELVE; no MAKE_CHARCOAL or MAKE_ASH anywhere in
  the reaction raws, which proves those two are hardcoded jobs,
  not reactions. The altar, minecart, wheelbarrow, armor stand,
  weapon rack, floodgate, enormous corkscrew, pipe section,
  menacing spike, spiked ball, animal trap, cage, and blocks
  tasks from the wiki list appear in no reaction raw.
* The live runtime enum
  (tests/fixtures/runtime-enums-0.47.05-r8.json): MakeCharcoal,
  MakeAsh, MakeCage, MakeAnimalTrap, MakeTrapComponent,
  MakePipeSection, ConstructArmorStand, ConstructWeaponRack,
  ConstructBlocks as job types; WoodFurnace, Smelter,
  GlassFurnace, Kiln as furnace types; Carpenters, Craftsdwarfs,
  Bowyers, Mechanics, Siege, Ashery as workshop types.

Harness state verified against the repo on 2026-11-27:

* actions.py JOB_SPECS (9 carpenter jobs), WORKSHOP_CATALOG
  (carpenter, mason, still, kitchen), queue_job (material
  fail-fast, already-queued count, invalid job id rejection),
  designate_chop and _plants_action (FellTree jobs never leave
  the job list, 60 second bound), build_workshop.
* materials.py _WOOD_1 (1 log per carpenter item), the barrel fix
  text, the bed and barrel have/need checks.
* planner.py (bed floor at citizens, make_bed x up to 3,
  make_barrel x3 at 0 empty barrels, carpenter build suggestion,
  DRINK_WARN 20, FOOD_WARN 15).
* daemon.py TASK_DEFS (make_bed, make_barrel, brew, cook, gather,
  farm; no chop task).
* stocks.lua (wood_units, wood_stacks, barrels, empty_barrels,
  bins, buckets; trader-held goods excluded; 15 barrels with 3
  empty on 2026-11-27).
* assembler.py TokenAccountant (count at length divided by 3,
  TARGET 30000, WARNING 60000, COMPACTION 100000, NEVER 140000),
  _stocks (the Stocks line with wood and empty barrels), _buildings
  (workshops by subtype with id and stage), _units (exceptions
  capped at 8, professions top 8).
* catalog.py (designate_chop entry with the axe warning,
  make_bed and make_barrel entries).
* briefings.py (10 kinds, low_drink and low_food as the
  shape the low_wood briefing follows, "a few hundred tokens at
  most").
* diagnose.py (wood shortage fixes: chop, make_bed, make_barrel,
  make_bucket).
* placement.py (wood stockpile adjacency 25 to the carpenter,
  woodcutting noise 8 tiles).
* lua/map.lua and lua/act_plants.lua (tree counting, SE-most
  trunk tile marking).
* observe.py (trees and shrubs logged, not in the snapshot).
* docs/STOCKPILES.md sections 4.2, 5, 6, 10 (wood stockpile
  network, barrel and bin capacity, containers).
* docs/KITCHEN.md sections 3.3, 4, 13 (drink floor, empty barrel
  bottleneck, snapshot Kitchen section as the presentation
  precedent).
* docs/FARMING_PLAN.md section 8 (ashery chain, potash cost,
  fertilizer).
* docs/TRADING.md sections 4 and 5 (elf refusal of wood, stone
  first and wood as fallback).
* Coordinator log 2026-11-27, M1 runs 15 to 17b (model fixated on
  beds and barrels, brew failed 3 times for 0 empty barrels, 20
  MAKE WOODEN BARREL jobs queued at once, drink 38 to 33 with no
  brew) and the 18:10 PT presentation direction (snapshot stays
  an index at about 4,700 tokens typical, budgets hold, Model
  presentation required in every breadth doc, 6 MCP tools, the
  opportunities mechanism not implemented per gap review 3 P2-3).
