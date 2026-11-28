# Metalworking

A plan for giving Urist a metal industry: ore survey and mining,
smelting, fuel, forging, metals by tier, bars, weapons, armor, tools,
alloys, fuel economy, and how metalworking feeds the military and the
trap systems. Everything here is researched from the local DF wiki
index, from the 0.47.05 raw files shipped with the game, and from the
harness code. Nothing is guessed. Anything not verified against the
wiki, the raws, or the live game is marked UNVERIFIED.

Status: design only. No metalworking code exists yet. The coordinator
owns implementation; this doc is the record it builds from.

Related docs: docs/MILITARY.md (what the metal is for: uniforms,
weapons, armor, ammunition), docs/STOCKPILES.md (ore, fuel, and bar
stockpiles, the melt-smelter rule, the never-sell list),
docs/TRADING.md (buying iron, steel, flux, and an anvil; selling metal
crafts), docs/SITE_SELECTION.md (scored placement for the smelter and
forge), docs/FARMING_PLAN.md (wood supply, which is also the charcoal
supply). This doc builds on them and does not duplicate them.

## 1. What metalworking is in DF 0.47.05

Metalworking is the chain that turns rock into weapons. It has four
links, and every link has to work before the next one can start:

1. **Ore.** Mined from veins and clusters underground, then hauled to
   the smelter. No ore, no metal, whatever else the fort has built.
2. **Fuel.** Charcoal from wood, coke from coal, or magma heat. Every
   smelt and every forge job at a conventional furnace burns one unit
   of fuel, plus extra fuel where the reaction itself uses coal as an
   ingredient (steel).
3. **Smelting.** Ore plus fuel at a smelter becomes bars. Alloys are
   made here too, from ores or from bars.
4. **Forging.** Bars plus fuel at a metalsmith's forge become weapons,
   armor, tools, trap components, mechanisms, furniture, and crafts.
   The forge needs an anvil, and the first anvil cannot be made in
   the fort: it has to come from embark or trade.

Without a metal industry the military fights with traps, traded
weapons, and leather armor (Metal industry). That is the fort's
position today, and the plan respects it: the first metalworking work
is finding out what ore and fuel the map holds, not building a forge.

### 1.1 The 0.47.05 buildings in the chain, verified

The authoritative list is the live runtime enum fixture the harness
already probes against the game,
`tests/fixtures/runtime-enums-0.47.05-r8.json`. Do not trust v50
workshop lists: the v50 wiki pages in the local index describe the
mouse-driven v50 interface and v50 building behavior, and several
details differ (section 12). The 0.47.05 list:

| Building | Enum | Kind | Needs to build | Needs to run |
| --- | --- | --- | --- | --- |
| Wood furnace | `WoodFurnace` | Furnace | Fire-safe material | 1 log per job, wood burner labor. No fuel. |
| Smelter | `Smelter` | Furnace | Fire-safe material | 1 fuel per job, furnace operator labor |
| Kiln | `Kiln` | Furnace | Fire-safe material | 1 fuel per job. NOT part of the metal chain (section 1.2). |
| Glass furnace | `GlassFurnace` | Furnace | Fire-safe material | Not part of the metal chain. |
| Metalsmith's forge | `MetalsmithsForge` | Workshop | Fire-safe material plus a fire-safe anvil | 1 fuel per job (except studding), 1 bar per item (section 6) |
| Magma smelter | `MagmaSmelter` | Furnace | Magma-safe material, 4/7 magma under an edge tile | No fuel for heat. Steel and pig iron still need fuel as a reaction ingredient. |
| Magma forge | `MagmaForge` | Workshop | Magma-safe material plus a magma-safe anvil, 4/7 magma under an edge tile | No fuel for heat. |
| Magma kiln | `MagmaKiln` | Furnace | Magma-safe material, magma | Not part of the metal chain. |
| Magma glass furnace | `MagmaGlassFurnace` | Furnace | Magma-safe material, magma | Not part of the metal chain. |

Two traps in that table, both verified against the enum fixture:

- A magma forge is a **workshop** (`workshop_types`), not a furnace.
  A magma smelter is a **furnace** (`furnace_types`). Code that looks
  one of them up in the wrong enum will fail, and the harness's build
  action today only knows the workshop enum at all (section 9).
- There is no plain `Forge` furnace and no `MagmaForge` furnace. The
  forge lives in the workshop enum; the smelter lives in the furnace
  enum. The build action has to learn both lookups.

Sizes: the smelter and the forge are both 3x3 in the game. UNVERIFIED
against the live game on r8: the harness has never built either, so
the footprint is a wiki claim the phase 1 build must confirm by
read-back, like every other build.

### 1.2 The kiln is not in this chain

The kiln burns fuel and uses the furnace operator labor, which is why
it looks like part of metalworking. It is not. The kiln makes
ceramics, pearlash, plaster powder, and quicklime (Kiln page), and
nothing it makes is a metal bar, a weapon, or a piece of armor. The
0.47.05 raws confirm it: every kiln reaction in
`reaction_other.txt` is pottery, plaster, pearlash, or quicklime; no
kiln reaction touches metal. The kiln matters to this doc in exactly
two ways: it competes for the same fuel the smelter and forge burn,
and its plaster powder is a hospital input, so the hospital plan
(section 10 of the breadth order) may want one. The metalworking
phases do not build a kiln, and a kiln must never be counted as metal
industry progress.

### 1.3 The chain, end to end, in one example

One hematite boulder, mined, becomes 4 iron bars at a smelter for 1
fuel. Two of those bars, plus 2 flux stone and 4 fuel across the two
steel steps, become 2 steel bars. One of those bars, plus 1 fuel at
the forge, becomes a steel war hammer. Total from ore to weapon: 1
ore, 2 flux, 6 fuel, one smelter, one forge, one anvil, and three
labors (miner, furnace operator, weaponsmith). Every number in that
sentence is verified below. The harness's job is to keep that whole
chain visible as have/need counts, so the agent never queues a forge
job the fort cannot feed.

## 2. The fort today

Verified against the world store (`~/.config/df-agent-harness/world.db`,
snapshot tick 115166, 2026-11-27) and the harness code. The fort has
no metal industry at all:

- 7 citizens. Buildings: Carpenters #7 and Still #8 only. No smelter,
  no forge, no wood furnace, no kiln, no magma anything.
- Stocks at tick 115166: drink 97, food 23, wood 117, stone 0. The
  rendered stocks carry no metal bars and no ore, and the
  `by_material` list shows no BAR entries at all. The full
  `by_material` list is truncated in the stored render, so the
  precise bar count (zero or a few) is re-verified from a fresh
  collect in phase 1; what is certain is that no bar stock exists in
  any quantity the snapshot shows.
- No survey is stored in world.db. The ore state of the map is
  completely unknown: no vein has been found, and no vein has been
  looked for. The embark record lists a bow and a war hammer as the
  fort's weapons, not picks, and the anvil is not in any record the
  harness can read. Whether the fort owns an anvil, and how many
  picks it owns, is UNVERIFIED until phase 1 reads the live stocks.
- Wood is the one input the fort already has: 117 wood is enough to
  bootstrap charcoal (section 4), and the carpenter exists to make
  barrels and bins for the bar stockpile.
- The planner already knows metalworking is deferred: `planner.py`
  names "metal industry (no ore/forge inputs on this fort yet)" as a
  deferred system. This doc is the plan that un-defers it, in order.

The consequence is blunt: the first metalworking milestone is not a
weapon. It is a survey that says what ore the map holds, and a fuel
stock that says the fort can smelt it. A forge built before those two
answers exist is a 3x3 room with an anvil in it and nothing to do.

## 3. Ore: survey and mining

### 3.1 What ore is, and where it lives

Ores are stones that leave metal behind when mined. Each ore boulder
smelts to 4 bars of its metal, and an ore with two metals listed gives
4 bars of the first plus 0 to 4 bars of the second (Ore page). Ores
occur in veins (long, single z-level, weaving through a stone layer)
or in clusters (small, round, usually rare ores). When a new ore is
struck on a z-level the game announces it, and where there is one ore
there is a whole vein or cluster to mine out (Metal industry).

The ore table, from the Ore wiki page cross-checked against the
0.47.05 raws (`inorganic_stone_mineral.txt`, `METAL_ORE` tokens):

| Ore | Metal | Found in |
| --- | --- | --- |
| Native copper, malachite | Copper | Igneous extrusive, sandstone, limestone, marble, all stone (tetrahedrite: copper plus 20% silver) |
| Cassiterite | Tin | Alluvial, granite |
| Hematite, limonite, magnetite | Iron | Sedimentary (all three); hematite also igneous extrusive; magnetite also metamorphic and igneous |
| Galena | Lead, 50% silver | Igneous extrusive, metamorphic, granite, limestone |
| Sphalerite | Zinc | Metamorphic |
| Garnierite | Nickel | Gabbro |
| Native silver, horn silver | Silver | Granite, gneiss, native silver clusters |
| Native gold | Gold | Igneous, alluvial |
| Bismuthinite | Bismuth | Granite |
| Native aluminum | Aluminum | Igneous extrusive |
| Native platinum | Platinum | Alluvial, olivine, magnetite, chromite |
| Raw adamantine | Adamantine | The depths (special rules, section 7.4) |

Two facts in that table decide the fort's whole metal future. First,
iron ores and flux stone and both coal ores all live in sedimentary
layers (Steel page), so a fort with no sedimentary layer has no
iron, no flux, and no coal of its own, and must trade for all three.
Second, hematite is the exception: it also occurs in igneous
extrusive layers, so a fort with no sedimentary layer can still have
iron if it has igneous extrusive rock. The survey has to report the
layer types, not just the veins, or the agent cannot reason about
this.

### 3.2 What the survey can and cannot tell the agent

The harness already has a survey (`survey.py`, `lua/survey.lua`):
one full block scan, about 25 seconds wall time, cached, with veins
flood-filled into bodies and the nearest of each kind measured. But
it has a hard limit the doc must not hide: **the specific ore is NOT
in the tiletype**. A vein reports as "mineral vein (unidentified)"
(survey.py:323, survey.lua header), and only small isolated bodies
count as veins at all; a body holding most of the map's mineral
reports as widespread mineral-bearing rock. The world-model design
already records the fallback: veins are identified by the boulders
mined out of them.

That shapes the whole ore workflow:

1. Run the survey. It says where mineral bodies are, how big they
   are, and how far they are from the fort, but not what metal they
   hold.
2. Dig an exploratory shaft to the nearest mineral body (digging.py
   already does verified digging with real designations; dig-now is
   never acceptable).
3. Mine the vein. The mined boulders are the identification: the
   stocks collect must report boulder materials, which it does not
   do today (section 9.3), so the identification step needs a
   collect extension before it can work.
4. Once the boulders name the ore, the survey body gets its identity
   in the store, and the have/need counts for that metal become real.

Exploratory mining is normal DF play, not a harness invention: the
wiki's advice is to dig up a z-level to discover what it holds
(Metal industry). The harness must do it the same way, with the dig
action and verification, and it must say which vein it is exploring
and what it expects to find there, so a dry hole is a finding ("that
body is not iron") and not a silent failure.

### 3.3 Ore handling rules

- Ores are economic stone. By default they are reserved for smelting
  and unavailable to masons and stone crafters (Metal industry). The
  harness must not enable ore for masonry to save a walk: the fuel
  saved by skipping the smelt is paid for in lost bars, and furniture
  made from ore cannot be recycled and is worth about 25% less than
  the refined metal. The only exception is a deliberate, named
  decision to use a surplus ore as stone, and it is the agent's call,
  not the harness's default.
- Ore goes to an ore stockpile by the smelter, with wheelbarrows on
  (Stockpiles section 4.2: stone feeder by the mason and smelter).
  The smelter's furnace operator must not walk across the fort for
  every boulder.
- A vein is mined out, not nibbled. The game announces the strike;
  the harness records the vein as found, mines it, and counts the
  boulders. A half-mined vein with no count is how a fort thinks it
  has iron and does not.

## 4. Fuel: charcoal, coke, and magma

Fuel is the binding constraint on the whole industry, more than ore.
Every smelt and every forge job at a conventional furnace burns one
unit of fuel for heat, and steel also burns fuel as a reaction
ingredient (section 5.3). A fort that runs out of fuel mid-chain has
bars it cannot forge and ore it cannot smelt, and the fix is measured
in trees, not in dwarves.

### 4.1 The three fuels

**Charcoal.** Made at a wood furnace from 1 log by a dwarf with the
wood burning labor. One log gives one bar of charcoal, and the wood
furnace needs no fuel to run (Fuel page, Wood furnace page). This is
the bootstrap fuel: the fort has 117 wood, so it can make 117
charcoal before it needs anything else. The cost is trees and burner
time. A heavily forested embark can run on charcoal alone, but it
takes many trees and potentially multiple burners on repeat to keep
the metalworkers supplied (Metal industry).

**Coke.** Made at a smelter from bituminous coal or lignite by a
furnace operator. One bituminous coal boulder gives 9 coke, one
lignite boulder gives 5 coke (verified in the 0.47.05 raws,
`reaction_smelter.txt`: BITUMINOUS_COAL_TO_COKE gives 9 bars,
LIGNITE_TO_COKE gives 5). At a conventional smelter each of those
reactions also burns 1 fuel for heat, so the net gain is 8 from
bituminous coal and 4 from lignite. At a magma smelter there is no
heat cost, so the net is the full 9 or 5. Coke and charcoal are
interchangeable as fuel for every workshop purpose (Fuel page). The
only in-game difference is that elven traders are offended by
charcoal and not by coke.

**Magma.** Once magma is found, magma smelters and forges use its
heat and burn no fuel for heat at all. Steel and pig iron still need
fuel as a reaction ingredient (the carbon), so magma does not end the
fuel economy, it halves it for steel and ends it for everything else.
Getting to magma means going down through the caverns, which is a
mature-fort undertaking, not a first-year one (Metal industry). The
magma work is phase 7, and nothing in the early phases depends on it.

### 4.2 The bootstrap problem

Coke needs fuel to make, charcoal needs only wood, and the fort
starts with wood. So the bootstrap order is fixed: wood furnace
first, charcoal second, coke third (if the map has coal), magma last.
A fort with no trees and no coal has no bootstrap at all and must buy
fuel, logs, or coal from a caravan, or go straight to magma. The
harness must check this before it promises any smelting: the smelt
decision names the fuel on hand and the fuel the job will burn, and
refuses when the fuel is not there.

### 4.3 Fuel economy, in numbers

All numbers verified against the Fuel and Smelting wiki pages and the
0.47.05 raws:

| Step | Cost | Yield |
| --- | --- | --- |
| 1 log at wood furnace | 0 fuel | 1 charcoal |
| 1 bituminous coal at smelter | 1 fuel | 9 coke (net +8) |
| 1 lignite at smelter | 1 fuel | 5 coke (net +4) |
| 1 ore at smelter | 1 fuel (0 at magma) | 4 bars |
| 1 forge job (weapon, armor, tool, craft) | 1 fuel (0 at magma), 1 bar | 1 item (goblets and flasks 3, coins 500) |
| Studding at forge | 0 fuel | 1 studded item |
| 2 steel bars, from iron bars | 4 fuel (2 at magma) | 2 steel bars |
| 2 steel bars, from iron ore | 5 fuel (2 at magma) | 2 steel bars |

The steel-from-ore row is the one the harness must get right: 1 ore
smelts to 4 iron for 1 fuel, then pig iron costs 2 fuel and steel
costs 2 fuel (Steel page recipe, verified against
`reaction_smelter.txt` PIG_IRON_MAKING and STEEL_MAKING, each with a
`[FUEL]` heat tag plus a 150-unit coal bar as a reagent). A fort that
budgets 4 fuel for 2 steel and forgets the ore smelt runs short by
exactly one fuel, every time.

Fuel rules the harness enforces:

- Never burn the last fuel without a way to make more. The Steel
  page says it plainly, and the harness must treat fuel 0 with no
  wood, no coal, and no magma as a dead industry, not a slow one.
- Keep a fuel floor, like the drink floor: enough fuel on hand to
  smelt the ore already mined and forge the bars already smelted.
  The exact floor is a phase 3 decision; the rule is that the floor
  exists and the snapshot shows fuel against it.
- Charcoal competes with beds, barrels, bins, and construction for
  the same wood. The fuel plan is a wood plan: the harness must say
  how many logs the charcoal burn will take and what else those logs
  were for. A fort that burns its bed wood into charcoal sleeps on
  the floor.
- Fuel is stored in a bars/blocks stockpile (charcoal and coke are
  bars), near the smelter and forge, with bins allowed. There is no
  way to stockpile charcoal separately from coke (Fuel page), so the
  harness tracks them as one fuel number with the split behind the
  query route.

## 5. Smelting

### 5.1 The smelter

The smelter turns ore into bars, coal into coke, and metal items back
into fractional bars (melting, section 5.4). It is built from
fire-safe material, it needs a dwarf with the furnace operator labor,
and every job at a conventional smelter burns one unit of fuel for
heat (Smelter page). It is a 3x3 furnace. It clutters easily: the
wiki warns that smelters are very prone to cluttering, so the bar
stockpile must not fill and must have bins (Metal industry). The
layout rule follows from that: ore stockpile on one side, fuel
stockpile on the other, bar stockpile with bins a few tiles away, all
inside, all reachable without crossing the main corridor.

### 5.2 Smelting ore

One ore boulder plus one fuel gives 4 bars of the ore's metal
(Smelting page, Ore page). For a two-metal ore the second metal adds
0 to 4 bars. Bars have no quality, so furnace operator skill only
changes how fast the job runs, not what it produces (Smelting page).
That has a planning consequence: the smelter needs a dedicated
operator for throughput, but a dabbling operator produces exactly the
same bars as a legendary one, so the harness never blocks smelting on
skill.

The smelt jobs the harness must be able to queue, with their 0.47.05
job types from the live runtime enum fixture
(`tests/fixtures/runtime-enums-0.47.05-r8.json`, `job_types`):

- `SmeltOre`: one ore boulder plus one fuel, 4 bars out.
- `MeltMetalObject`: one metal item plus one fuel, fractional bars
  back (section 5.4).
- `ExtractMetalStrands`: adamantine thread to wafers (section 7.4).
- `MakeCharcoal`: one log, no fuel, at the wood furnace (same enum
  list; the job type exists even though the job runs at a different
  furnace).

The alloy reactions are CustomReaction jobs (job type 211) with the
reaction codes from `reaction_smelter.txt` (section 5.3), which is
the same mechanism the brew and carpenter jobs already use
(actions.py JOB_SPECS). The ore smelt itself is NOT a reaction in
the raws: no SMELT_ORE reaction exists in `reaction_smelter.txt`,
and no MAKE_CHARCOAL reaction exists in any reaction raw. Both are
hardcoded game jobs, which is why they appear as plain job types in
the enum and not as reactions. The harness must queue them as plain
jobs, not as CustomReaction jobs with a reaction name. How the ore
and fuel items attach to a plain job at queue time is UNVERIFIED:
act_job.lua builds job items from reaction reagents, and a plain job
has no reagents, so the probe in phase 2 must show whether the game
fills the items when the dwarf takes the job (as it does for a cook
job) or whether the harness must attach them. Until that probe runs,
no smelt job is promised.

### 5.3 Alloys, verified against the 0.47.05 raws

Every alloy reaction below is copied from
`third_party/df_47_05/raw/objects/reaction_smelter.txt`, the game
files themselves, not the wiki. The wiki agrees with all of them
(Bronze page recipe, Steel page recipe), but the raws are the
authority. Each reaction burns 1 fuel for heat at a conventional
smelter, on top of the ingredients listed. Amounts are in boulders
for ore, bars for metal, and 150 units for a bar reagent (one bar).

| Alloy | From ore (per job) | From bars (per job) | Bars out |
| --- | --- | --- | --- |
| Bronze | 1 cassiterite + 1 copper ore | 1 tin bar + 1 copper bar | 8 (ore) / 2 (bars) |
| Brass | 1 sphalerite + 1 copper ore | 1 zinc bar + 1 copper bar | 8 (ore) / 2 (bars) |
| Billon | 1 silver ore + 1 copper ore | 1 silver bar + 1 copper bar | 8 (ore) / 2 (bars) |
| Electrum | 1 silver ore + 1 gold ore | 1 silver bar + 1 gold bar | 8 (ore) / 2 (bars) |
| Fine pewter | 3 tin ore + 1 copper ore | 3 tin bars + 1 copper bar | 16 (ore) / 4 (bars) |
| Trifle pewter | 2 tin ore + 1 copper ore | 2 tin bars + 1 copper bar | 12 (ore) / 3 (bars) |
| Lay pewter | No ore recipe | 2 tin bars + 1 copper bar + 1 lead bar | 4 |
| Bismuth bronze | No ore recipe | 1 tin bar + 2 copper bars + 1 bismuth bar | 4 |
| Nickel silver | No ore recipe | 2 nickel bars + 1 copper bar + 1 zinc bar | 4 |
| Black bronze | No ore recipe | 2 copper bars + 1 silver bar + 1 gold bar | 4 |
| Sterling silver | No ore recipe | 3 silver bars + 1 copper bar | 4 |
| Rose gold | No ore recipe | 3 gold bars + 1 copper bar | 4 |
| Pig iron | No ore recipe | 1 iron bar + 1 flux stone + 1 coal bar | 1 |
| Steel | No ore recipe | 1 iron bar + 1 pig iron bar + 1 flux stone + 1 coal bar | 2 |
| Adamantine wafers | No ore recipe | 15000 adamantine thread | 1 |

The ore route is four times as efficient as the bars route for the
alloys that have one (8 bars from 2 ores against 2 bars from 2 bars),
because smelting ore multiplies by four and alloying bars does not.
The harness must always prefer the ore route when both ores are on
hand, and say so when it cannot ("no cassiterite on hand, alloying
from bars at quarter yield"). The bars-only alloys (lay pewter,
bismuth bronze, nickel silver, black bronze, sterling silver, rose
gold) exist for value and color, not for military use, and the
harness must not burn silver and gold on them while the military
waits for steel.

**Steel, in full.** Steelmaking from iron bars has two steps, and
both steps need coal as part of the reaction, in addition to the heat
fuel at a conventional smelter (Steel page). Step 1, pig iron: 1 iron
bar + 1 flux stone + 1 coal bar, plus 1 fuel for heat, gives 1 pig
iron bar. Step 2, steel: 1 iron bar + 1 pig iron bar + 1 flux stone +
1 coal bar, plus 1 fuel for heat, gives 2 steel bars. Steel cannot be
made directly from ore: the ore must first become iron bars
(`reaction_smelter.txt` has no ore-to-steel reaction, and the Steel
page says so). Flux stones are calcite, chalk, dolomite, limestone,
and marble, verified in the 0.47.05 raws: limestone, dolomite, chalk,
and marble carry `[REACTION_CLASS:FLUX]` in
`inorganic_stone_layer.txt`, calcite in
`inorganic_stone_mineral.txt`. Flux is also the trade fallback: if
the map has no flux, the caravan is the only source, and the trading
plan already lists flux as a buy-list item (TRADING.md).

### 5.4 Melting: goblinite and the melt smelter

Metal items melt at a smelter with the furnace operator labor,
recovering a fixed fraction of the metal per item type, from 10% to
150% or more (Melt item page, Stockpiles section 9.2). Recovery is
counted in tenths of a bar, per smelter, per metal, and fractions are
not shared between smelters: ten tenths make a bar, and if the
smelter is torn down the fractions are lost. So the fort designates
one smelter as the melting smelter, so fractions add up. The melt
decision and the smelt decision must never share a smelter without
the harness saying so, or the fractions split and nothing ever
completes.

What melting is for: goblinite. The arms and armor of killed
invaders are the early fort's main metal supply (Metal industry,
Military section 10): a dead goblin's iron axe is worth more than
the iron the fort cannot yet smelt. The melt pipeline is: collect
the loot, mark the worn, damaged, and surplus pieces for melting,
queue MeltMetalObject jobs at the designated melting smelter, and
count the fractions per metal until whole bars appear. The yield
table (Melt item page) is the planning basis: leggings return 1.5
bars for 1 bar to make (150%), gauntlets 0.6 for half a bar (120%),
shields 1.2 for 1 (120%), helms 0.6 for 1 (60%), mail shirts 1.8
for 2 (90%). Some items return more metal than they cost, which is
why melting loot is profitable and why the harness must never melt a
piece the military still needs.

Melt rules, carried over from Stockpiles section 9.2 and enforced
here:

- An item marked for melting AND forbidden is NOT melted. The
  harness must never forbid a melt candidate.
- Melting a container does not melt its contents; they are left in
  the smelter.
- Never melt artifacts, never melt the last tool of a kind, never
  melt mandated items, never melt a piece the uniform still needs.
- The melt designation itself has no harness route today (section
  9.3). Whether the melt flag is writable from Lua is a phase 5
  probe, and until it runs, melting is a named gap, not a capability.

## 6. Forging

### 6.1 The forge and the anvil

The metalsmith's forge turns bars into finished metal goods. It is
built from fire-safe material plus a fire-safe anvil, and every use
except studding consumes one unit of fuel (Metalsmith's forge page).
The anvil is the gate: anvils need 3 metal bars to smith at a forge
(Anvil page), and the only way to make an anvil is with a forge, so
the fort's first anvil must come from outside, at embark or from a
caravan. If the civilization has iron ore, a standard iron anvil is
in the starting equipment for 100 embark points; if not, a steel
anvil for 300 (Anvil page). A fort that embarks without an anvil must
trade for one, and the dwarven liaison can be asked to guarantee one
on the next caravan at an increased price. The harness must treat
"no anvil" as a hard blocker with a named fix (buy one, request one),
never as a missing build material to gather. Tearing a forge down
returns its anvil, so the anvil is never lost by rebuilding, only by
trading it away or melting it, both of which the never-sell list
forbids (TRADING.md: the last anvil is never sold).

Anvil material does not affect forge performance: only the smith's
skill does (Anvil page). A mood anvil of a strange metal can be
unusable, tin for any forge and any non-magma-safe metal for a magma
forge, so a mood anvil is checked before it is trusted, not assumed
good.

### 6.2 Who works the forge

Four of the five metalsmithing skills work at the forge (the fifth,
smelting, works at the smelter). Verified against the forge wiki
pages and the live runtime enum fixture, which lists the labors
`FORGE_WEAPON`, `FORGE_ARMOR`, `FORGE_FURNITURE`, `METAL_CRAFT`,
`BURN_WOOD`, `SMELT`, plus `MECHANIC` and `TRAPPER`:

| Labor (0.47.05 enum) | Skill | Makes |
| --- | --- | --- |
| FORGE_WEAPON | Weaponsmithing | Weapons, trap components, bolts, ballista arrowheads |
| FORGE_ARMOR | Armoring | Armor |
| FORGE_FURNITURE | Blacksmithing | Anvils, blocks, all furniture except chains |
| METAL_CRAFT | Metalcrafting | Chains, crafts, coins, goblets, flasks, toys, instruments, studding |
| TRAPPER | Trapping | Animal traps |
| MECHANIC | Mechanics | Mechanisms |
| BURN_WOOD | Wood burning | Charcoal and ash, at the wood furnace, not the forge |
| SMELT | Furnace operating | Everything at the smelter, not the forge |

Note the 0.47.05 detail the v50 pages blur: there is no separate
Blacksmith labor in the enum. Anvils, blocks, and furniture are the
FORGE_FURNITURE labor (the blacksmithing skill). The harness assigns
labors by these enum names through the existing `labor_toggle`
action (act_labor.lua takes a `df.unit_labor` name and writes it
with read-back), which is verified working for other labors. Which
dwarf gets which forge labor is a skill read: the harness reads
skills from the units collect and picks the best smith per labor,
with a backup who keeps the skill warm, the same way the kitchen
plan picks its cook. A forge with no smith of the right labor is a
forge that never runs, and the snapshot must say which labor is
missing, not just that the forge is idle.

### 6.3 What a bar buys

The cost of a weapon or armor piece in bars is its material size
divided by 3, rounded down, with no item costing less than one bar
(Metalsmith's forge page, Armor page). Finished goods differ:
goblets and flasks always produce 3 from one bar, coins produce a
stack of 500 from one bar, crafts produce 1 to 3, and minecarts and
wheelbarrows cost 2 bars (Metal crafter page). Verified per-piece
costs from the Melt item yield table, which lists bars to make:

| Item | Bars to make |
| --- | --- |
| Weapon (axe, sword, hammer, spear, mace) | 1 |
| Helm, cap | 1 |
| Mail shirt | 2 |
| Greaves | 2 |
| Gauntlets (pair) | 1 |
| High boots (pair) | 1 |
| Shield, buckler | 1 |
| Crossbow | 1 |
| Bolts | 1 bar per 25 bolts |
| Anvil | 3 |
| Breastplate | 2 by the size/3 rule. UNVERIFIED against the melt table: the table excerpt the index returned ends at the mail shirt, so the breastplate figure is computed, not quoted, and phase 2 verifies it live. |

A full kit per dwarf on the Military basic uniform (helm, mail
shirt, breastplate, greaves, gauntlets, boots, shield, weapon) is 10
bars if the breastplate figure holds, 8 without it. A 5-dwarf squad
is 50 bars of iron or steel, plus bolts. That number is why the
military plan sizes squads from stocks and not from a fixed number,
and why the forge queue is a have/need computation, never a wish
list. One bar of metal is also one pick, one axe, one mechanism, or
one trap component, and the harness must rank those against each
other when bars are short: picks first (no picks, no mining, no
more ore), then the squad's weapons, then armor, then traps, then
crafts. The exact ranking is a planner decision; the rule is that
the ranking exists and the agent sees it.

### 6.4 What the forge makes, beyond weapons

The forge is also the fort's tool and furniture shop, and the plan
must not let the military eat all of it:

- **Tools:** picks, axes, and other tools. Picks are the most
  valuable item in the early fort: without them there is no mining
  and no more ore. The harness never lets the pick count hit zero
  without an attention entry.
- **Trap components:** weaponsmiths forge the metal parts for weapon
  traps, and mechanics forge metal mechanisms. A weapon trap without
  metal components is a stonefall trap, and the trap plan
  (Military section 9, breadth step 10) depends on these parts
  existing. Crossbows in weapon traps do not jam, and they need
  bolts, so the trap loadout is part of the forge queue.
- **Mechanisms:** metal mechanisms for levers, bridges, and traps.
  A drawbridge without a linked mechanism is a wall the fort cannot
  open, and lever linking is itself unresolved work (Military
  section 9).
- **Blocks and furniture:** metal blocks for construction, anvils,
  chains, grates, and metal furniture. Metal furniture is high-value
  trade stock and noble-room stock, not a first-year need.
- **Crafts, goblets, flasks, coins:** the trade goods. One bar
  becomes 3 goblets or 500 coins, which is why metalcrafting is a
  good way to make high-value trade goods quickly when the fort has
  surplus metal (Metal crafter page). Crafts are never forged from
  a metal the military still needs.
- **Armor stands and weapon racks:** built at the forge or the
  carpenter, and the barracks needs them (Military section 4.2).

## 7. Metals by tier

The tiers are the military's tiers (Military section 5.2), restated
here with the production cost attached, because the tier decision is
a production decision: the fort fields the best metal it can make in
quantity, not the best metal it has heard of.

### 7.1 Copper

The starter metal. Native copper, malachite, and tetrahedrite smelt
to copper, value 2. Copper weapons and armor are quickly outclassed
against almost anything except silver weapons and animal attacks
(Armor page), but copper is what a fort with no tin and no iron
fields, and it is infinitely better than wood and leather. Copper
picks and axes are the first forge products: they keep the mine
running. Copper is also the base of every early alloy: bronze,
brass, billon, and bismuth bronze all need copper.

### 7.2 Bronze

One tin ore plus one copper ore, or one tin bar plus one copper bar,
plus fuel, gives 8 bars from ore or 2 from bars (section 5.3).
Bronze value 5, and it can be used for every metallic item in the
game (Bronze page). Bronze and iron are the minimum the wiki
recommends for real fighting (Armor page). A fort with cassiterite
and copper but no iron fields bronze, and fields it proudly: a
bronze squad beats a copper squad and beats an unarmored goblin
squad. Bronze is the tier the fort aims for when iron is absent,
and the trade plan should not buy iron at bronze prices when the map
already gives bronze.

### 7.3 Iron

Hematite, limonite, and magnetite smelt to iron, value 10. One ore
gives 4 bars for 1 fuel. Iron is the workhorse: weapons, armor,
picks, anvils, mechanisms, trap components. An iron squad is a real
squad. Iron is also the input to steel, so the fort never treats
iron as finished stock while steel is the goal: every iron bar is
either a weapon today or a steel bar tomorrow, and the harness shows
both numbers.

### 7.4 Steel

The standard for a serious military (Armor page). Value 30, tied
with gold for the fourth highest metal value (Steel page). Two steel
bars cost 2 iron bars, 2 flux, and 4 fuel at a conventional smelter
(2 fuel at magma), from ore 5 fuel total (section 4.3). Only dwarven
civilizations regularly make steel; humans and goblins make do with
lesser metals (Steel page). A full set of exceptional steel can
absorb most of a goblin squad's ammunition (Armor page). Steel is
the end of the tier ladder for this fort, and the plan says so: there
is no tier above steel that the fort can produce.

What is above steel and out of scope: **adamantine**. Raw adamantine
is mined in the depths, processed at a craftsdwarf's workshop into
thread, and smelted to wafers at a ratio of 15000 thread per wafer
(`reaction_smelter.txt` ADAMANTINE_WAFERS). It is the best metal in
the game and it lives past the caverns, past the magma sea, in the
most dangerous rock in the game. This doc records that it exists and
does not plan for it. A fort that reaches adamantine has outgrown
this doc.

### 7.5 The other metals

Not every metal is a weapon metal. The harness must know which is
which, or it will forge a silver war hammer and wonder why the squad
loses:

- **Silver** (value 10): too soft for weapons and armor, but the
  best metal against undead and werecreatures in the game's damage
  model, and a trade metal. Silver war hammers are a known
  anti-undead choice, not a general one. UNVERIFIED against the live
  game on r8: the damage-model claim is wiki text, and the harness
  has never fought an undead with a silver hammer.
- **Gold** (value 30), **platinum** (40), **aluminum** (40): trade
  and craft metals, never armor. Their value is the point: a gold
  goblet is trade stock, not kit.
- **Lead** (2), **zinc** (2), **nickel** (2), **bismuth** (2), **tin**
  (2): alloy inputs and craft metals. Tin's military value is
  entirely as bronze. Lead's is as lay pewter and billon.
- **Metal value and mood value:** metal bars are trade goods in
  their own right, and a bar stockpile is also a wealth stockpile.
  The wealth read (`lua/wealth.lua`) already exists; the metal plan
  does not duplicate it.

## 8. The layout: where the industry lives

Layout is scored placement (docs/SITE_SELECTION.md), with
metalworking-specific factors on top of the shared threat, cover,
and traffic factors:

- **The triangle.** Smelter, forge, and wood furnace belong together,
  within a few tiles of each other, inside, near the mine entrance.
  The furnace operator and the smith both haul ore, fuel, and bars,
  and every tile of distance is paid on every job.
- **Feeder stockpiles.** An ore stockpile by the smelter, a fuel
  stockpile (bars/blocks, bins allowed) by the smelter and forge, a
  bar stockpile with bins by the forge. Feeders take from anywhere;
  bulk stores take from links only (Stockpiles section 4). The bar
  stockpile must never fill: a full bar stockpile clutters the
  smelter and the forge, and clutter slows both.
- **The melt smelter sits apart.** One smelter is the melting
  smelter, so melt fractions accumulate (section 5.4). It is marked
  as such in the store, and the smelt queue never sends ore there
  without the harness saying so.
- **Fire safety.** Smelters, forges, wood furnaces, and kilns are
  built from fire-safe material, and the build action must enforce
  it: a wooden smelter is not a smelter, it is a fire. The build
  action today takes whatever material the probe finds first
  (actions.py `build_workshop` takes the first accessible material
  in the spec list), with no fire-safe check anywhere. That is a gap
  the metalworking build work closes, not a detail to leave to the
  model. UNVERIFIED: whether the game refuses a non-fire-safe
  material at placement time or lets the building stand and burn.
  The phase 1 build must probe it and record the answer.
- **Magma safety.** Magma buildings need magma-safe material, and
  the open tile over magma is a creature entry point: the v50 wiki
  text says the impassable tile was removed in v50, which means in
  0.47.05 the smelter and forge still have an impassable tile.
  UNVERIFIED on r8: the wiki says it was removed "as of v50", which
  implies it exists in 0.47.05, but the harness has never built a
  magma building to confirm it. Phase 7 verifies it live before any
  magma building is trusted as sealed.
- **Smoke and traffic.** The industry lives downwind of the dining
  hall and off the main corridor, like every workshop, and its
  hauling route must not cross the only path into the fort. A siege
  must never find the fort's fuel haul crossing its kill zone.

## 9. What the harness has today

Verified against the repo 2026-11-27. Everything in this section was
read from the code, not assumed.

### 9.1 What exists and can be reused

- **Digging works.** `digging.py` (check_dig_site, check_dig_box,
  verify_dig, derive_dig_site) does verified digging with real
  designations, and the dig action is the exploratory-mining route.
  The survey (`survey.py`, `lua/survey.lua`) finds mineral bodies
  and measures the nearest of each kind, in about 25 seconds wall
  time, cached per kind and re-surveyed on demand, after a dig in
  that region, or once per season.
- **Job queueing works for reactions.** `queue_job` (actions.py
  JOB_SPECS, act_job.lua) queues CustomReaction jobs (job type 211)
  by reaction code, which is exactly how the alloy reactions run.
  The brew and carpenter jobs prove the mechanism. The alloy
  reactions only need JOB_SPECS entries naming their codes.
- **Labor toggle works.** `labor_toggle` (act_labor.lua) takes a
  `df.unit_labor` name, validates it against the live enum, writes
  it, and reads it back. The metal labors (SMELT, FORGE_WEAPON,
  FORGE_ARMOR, FORGE_FURNITURE, METAL_CRAFT, BURN_WOOD, MECHANIC,
  TRAPPER) are all in the live enum fixture, so assignment is a
  solved problem, not a research problem.
- **Stocks count bars.** `stocks.lua` counts `metal_bar_units` and
  `metal_bar_stacks`, and one snapshot path renders the total
  (observe.py:304, "metal bars N"). The count exists; the breakdown
  does not.
- **The planner knows metalworking is missing.** `planner.py` names
  the metal industry as deferred for lack of ore and forge inputs.
  The deferral is honest and stays until the inputs exist.
- **The trade plan already carries the buy list.** TRADING.md lists
  steel, flux, and an anvil as things the fort cannot make yet and
  should buy, and ranks steel first by how much it unblocks. The
  metalworking plan feeds that list with live numbers (how much iron
  the map has, how much flux, whether an anvil is owned) instead of
  leaving it as a static list.

### 9.2 What is missing (verified gaps)

- **No furnace build.** WORKSHOP_CATALOG (actions.py:133) has four
  kinds: carpenter, mason, still, kitchen. No smelter, no forge, no
  wood furnace, no kiln. `act_build.lua` hardcodes its subtype
  lookup to `df.workshop_type`, so a furnace subtype would error as
  "unknown workshop subtype" (ADVANCED_MECHANICS.md section 4).
  Furnaces need a `df.furnace_type` lookup and a `type` of Furnace,
  and the forge needs the workshop lookup with a different width,
  height, and material rule. This is the first build gap, and the
  trap work already queued the same generalization.
- **No two-material build.** `build_workshop` takes a single
  material (one mat_type and mat_index) and `act_build.lua` passes
  exactly one material to `constructBuilding`. A forge needs two:
  a fire-safe building material and an anvil. There is no code path
  that supplies the second one. Until the build action learns a
  second material, no forge can be built by the harness at all.
- **No fire-safe check.** Nothing in the build path checks that the
  chosen material is fire-safe. The first accessible stone is
  whatever the probe finds, and the fort's stone today is 0, so the
  first smelter build would fail on material anyway. The check has
  to land with the build work, not after a wooden smelter burns.
- **No smelt or forge jobs in JOB_SPECS.** JOB_SPECS (actions.py)
  has brew, brew_fruit, cook, and nine carpenter jobs. No SmeltOre,
  no MeltMetalObject, no MakeCharcoal, no alloy reaction, no
  MakeWeapon, no MakeArmor, no ForgeAnvil. The job types exist in
  the live enum fixture (`SmeltOre`, `MeltMetalObject`,
  `ExtractMetalStrands`, `MakeWeapon`, `ForgeAnvil`, `MakeArmor`,
  `MakeCharcoal`), but no harness action names them.
- **No plain-job item attachment, verified.** act_job.lua builds job
  items from reaction reagents. A plain job (SmeltOre, MakeWeapon)
  has no reagents, and whether the game fills its items when the
  dwarf takes the job is UNVERIFIED (section 5.2). The cook job
  (PrepareMeal, job type 115, no reaction) proves plain jobs queue;
  it does not prove a plain job with material inputs attaches them.
- **No ore observation.** The survey reports unidentified mineral
  veins, and `by_material` in the stocks collect covers only DRINK,
  FOOD, MEAT, FISH, PLANT, SEEDS, BAR, WOOD, CLOTH, THREAD
  (KITCHEN.md section 4.1). Mined ore boulders (BOULDER items with
  an ore material) are invisible to the snapshot. The fort can mine
  hematite and the model will never know.
- **No fuel observation.** Charcoal and coke are BAR items, counted
  only inside the undifferentiated `metal_bar_units` total. The
  snapshot cannot say "6 fuel" today, and the planner cannot refuse
  a smelt for lack of fuel, because it cannot see fuel.
- **No anvil tracking.** Nothing counts anvils, nothing says whether
  the fort owns one, and the never-sell list (TRADING.md) names "the
  last anvil" as protected without any read to back it. Phase 1
  adds the read before any build is promised.
- **No melt designation.** No action marks an item for melting, and
  no read reports melt fractions per smelter (Stockpiles section
  3.3). Goblinite melting is a named gap until phase 5 probes it.
- **No metalworking section in the snapshot.** The model sees a
  total bar count on one snapshot path and nothing else: no ore, no
  fuel, no furnace state, no smith assignment, no have/need for the
  next weapon. Section 13 closes that.

### 9.3 Cross-references already settled

- MILITARY.md section 5: the uniform tiers, the weapon damage
  types, the ammunition pipeline, and the sizing rule (squads sized
  from stocks, never from a fixed number). The forge queue serves
  those numbers; it does not re-decide them.
- MILITARY.md section 9: trap creation and the weapon-trap loadout
  (hammers jam less than swords or axes, spears jam most, crossbows
  in weapon traps do not jam but must stay loaded). The forge makes
  the trap components; the trap plan decides where they go.
- STOCKPILES.md sections 4.2, 9.2, and 10: the ore, fuel, and bar
  stockpiles, the melt-smelter rule, the melt fractions, and the
  bars/blocks stockpile settings (bins hold 12 bars by the bin table
  and 10 by the Stockpile page; plan on 10).
- TRADING.md sections on the buy list (steel, flux, an anvil) and the
  never-sell list (the last anvil, the last pick, mandated items).
  The metalworking plan turns those from static lists into live
  have/need counts.

## 10. How metalworking feeds the military and the traps

Metalworking is not an end in itself. It exists to arm the fort, and
every bar is spent against a named need from the military plan or
the trap plan. The harness tracks the flow as one ledger:

1. **Picks first.** A pick is a weapon (MakeWeapon) and a mining
   tool. No picks means no mining, no more ore, and no more metal.
   The pick count is a standing attention item, and the forge queue
   never lets it reach zero while bars exist.
2. **Squad weapons.** One bar per weapon, forged from the best metal
   the fort can make in quantity. Against unarmored enemies, axes
   and swords; against armored goblins and trolls, war hammers and
   maces; piercing (spears, picks) against armor and organs
   (Military section 5.3). The harness names the weapon, the metal,
   and the have/need count, and the agent picks the mix.
3. **Armor.** Helm, mail shirt, greaves, gauntlets, boots, shield,
   and breastplate, in the tier the fort can afford (section 6.3).
   Armor user skill matters as much as the armor, so the training
   plan and the forge queue advance together: armor forged for a
   squad that never trains is weight, not protection.
4. **Bolts.** 25 bolts per bar, and a marksdwarf needs 100 to 200
   assigned (Military section 5.4). The bolt queue is part of the
   forge queue, and training bolts (wood and bone) stay in a
   separate stockpile from war bolts (metal).
5. **Trap components and mechanisms.** Weapon traps take forged
   metal components; mechanisms take a mechanic at the forge. The
   choke-point trap plan cannot run without them, and the forge
   queue carries them as named items with counts, not as an
   afterthought.
6. **Goblinite back in.** Looted weapons and armor come back to the
   smelter as melt stock (section 5.4). The loop is the early fort's
   metal economy: kill goblins with bronze, melt their iron, forge
   steel. The harness counts the loop (bars in from melt, bars out
   to the forge) so the agent can see whether the fort is gaining
   metal or burning it.

What the harness refuses, in this flow: never forge a craft from a
metal the squad still needs; never forge armor for a squad that does
not exist; never melt a piece the uniform still needs; never queue a
forge job without the fuel on hand; never claim a squad is equipped
without a live read-back of what its members actually carry.

## 11. Labor and assignment

Metalworking needs five labors across four dwarves at minimum, and
the fort has 7 citizens, of whom the miner, the brewer, the
carpenter, and the planter are already spoken for. The assignment
rules:

- **Miner:** already exists. The miner is never drafted into the
  military while the fort still needs ore (Military section 3.2:
  never draft the only dwarf with a critical skill). The miner is
  the industry's first link.
- **Wood burner:** one dwarf, part time at first. Charcoal is batch
  work: burn a stack of logs when fuel runs low, then go back to
  other work. The burner needs the BURN_WOOD labor and nothing else.
- **Furnace operator:** one dwarf, the smelter's dwarf. Smelting is
  the throughput bottleneck once ore flows, so the operator becomes
  full time as soon as the fort has a vein in production. Skill
  changes speed only, so any dwarf can start; the best operator is
  the one with nothing else critical to do.
- **Weaponsmith, armorsmith, metalcrafter, blacksmith:** one dwarf
  per labor at most, and one dwarf can hold several forge labors
  while the fort is small. The harness picks by skill from the units
  collect, and it must say which forge labor has no dwarf at all,
  because a forge job of that kind simply never runs.
- **Mechanic:** the mechanism maker. Shared with the trap plan; the
  mechanic is not a metalworker by trade, but metal mechanisms come
  from the forge, so the mechanic needs forge access too.

The labor plan (docs/LABOR.md) owns who holds which labor; this doc
owns which labors the industry needs and what happens when one is
missing. A missing labor is a named blocker ("no furnace operator:
smelter idle"), never a silent idle workshop.

## 12. Open questions (UNVERIFIED)

- **Plain-job item attachment.** Whether SmeltOre, MakeWeapon, and
  MakeArmor jobs queued by act_job.lua get their ore, fuel, and bar
  items attached by the game when the dwarf takes the job, or
  whether the harness must attach them. Phase 2 probes it live.
- **The anvil.** Whether the fort owns an anvil at all, and how many
  picks it owns. No record the harness can read today says so.
  Phase 1 reads it from a fresh collect.
- **Fire-safe refusal.** Whether the game refuses a non-fire-safe
  material for a smelter or forge at placement time, or lets the
  building stand. Phase 1 probes it.
- **Magma impassable tile.** Whether the 0.47.05 magma smelter and
  magma forge still have the impassable tile the v50 wiki says was
  removed in v50. Phase 7 verifies it live before any magma
  building is trusted as sealed.
- **Melt flag write.** Whether an item can be marked for melting
  from Lua, and where the melt fractions per smelter live for
  read-back. Phase 5 probes it.
- **Breastplate bars.** The melt-table figure of 2 bars by the
  size/3 rule is computed, not quoted: the table excerpt the index
  returned ends at the mail shirt. Phase 2 verifies it live.
- **Silver against undead.** The wiki's damage-model claim that
  silver is the best metal against undead and werecreatures is
  untested on this fort and this version. It is a planning note,
  not a forge order, until a live fight proves it.
- **Ore identification read.** Whether the stocks collect can report
  boulder materials (ore identity) per item, or whether a new Lua
  read is needed. Phase 1 probes it.
- **Kiln shortcuts and the v50 UI.** The shortcut keys and the
  click paths on the wiki pages are v50. The harness never uses
  keystrokes for game actions, so this only matters for human
  verification steps, and any shortcut in a verification step must
  be confirmed against 0.47.05 first.
- **The survey's ore answer.** Whether a mined boulder's material
  is enough to identify a whole vein, or whether a vein can hold
  mixed ores. The working assumption is one vein, one ore, and the
  first mined vein proves or breaks it.
- **Adamantine.** Everything about it is out of scope for this doc
  (section 7.4). If the fort ever reaches it, it gets its own plan.

## 13. Model presentation

This section is required by the standing presentation constraint
(GOAL.md, 2026-11-27): the snapshot stays an index, budgets hold,
and every new system states how its information reaches the model,
what it costs, and what it deliberately does not push.

### 13.1 The snapshot section

The per-tick snapshot gains a short Metalworking section, built from
the fresh collect, in plain words. Counts and exceptions only, never
a dump. Two states, because the fort lives in the first one today:

No metal industry yet (the fort today):

```
Metal: no smelter, no forge, no wood furnace, no anvil on record.
Ore: none surveyed (0 mineral veins found). Fuel: 0 charcoal, 0 coke.
Bars: 0. Next step: survey for ore (no survey on record).
```

Working industry (what the section looks like once the chain runs):

```
Metal: smelter #12, forge #14 (iron anvil). Fuel: 6 charcoal, 0 coke (about 6 smelts).
Bars: copper 8, bronze 0, iron 12, steel 0. Ore on hand: hematite 3, cassiterite 0.
Next: smelt 3 hematite (have 3 ore, 6 fuel, need 3 fuel) or forge 2 iron axes (have 12 bars, need 2).
```

What is in it, and what is not:

- **In it:** furnace state (which furnaces and forges exist, by
  building id, and whether each has its anvil and its labor), fuel
  against the fuel floor, bars by metal, ore on hand by kind,
  the next smelt or forge step as a have/need pair, and the blocker
  when a step cannot run ("no anvil: buy one" beats "forge idle").
- **Not in it:** the full alloy table, the per-item melt fractions,
  the full ore table, the survey bitmask, the per-dwarf smith
  skills, or the melt yield table. Those live behind the query
  route (section 13.2).
- **Never in it:** a list of every bar, a list of every ore boulder,
  or a number without its floor or its need. A bar count without the
  forge queue it serves is a number the agent cannot act on.

### 13.2 Token cost: measured from the section as written

Costs use the assembler's own accountant (assembler.py): the
conservative count is about 3 characters per token, the wire
estimate about 4 characters per token, and the accountant enforces
the budget at the conservative count, so the numbers below are the
accountant numbers first. The two example blocks in section 13.1
were measured character by character from the text as written.

- **No-industry state:** 193 characters, about 65 tokens
  accountant, about 49 tokens wire.
- **Working-industry state:** 272 characters, about 91 tokens
  accountant, about 68 tokens wire.
- **At 7 dwarves:** the section costs 65 tokens in the fort's
  current state (no industry), 91 tokens once the chain runs.
- **At 50 dwarves:** the same, 65 tokens with no industry and 91
  tokens with a working industry. The section reports counts per
  metal, per furnace, and per ore kind, so its size does not grow
  with population. The per-dwarf growth lives in the units section,
  not here. The only way this section grows is by the fort holding
  more kinds of metal at once, one short entry per kind, and a fort
  that holds ten metals at once is a fort with a different problem.
- **Against the budget:** the snapshot is about 4,700 tokens typical
  (world-model design section 6), with a 30K target, 60K warning,
  100K compaction, and a 140K hard cap on a 200K window, enforced by
  the token accountant with its cut order. This section is about 1 to
  2% of a typical snapshot. It never threatens the budget, and it is
  cut by the same cut order as everything else if the snapshot ever
  runs long: the section is not in NEVER_CUT, and the suggestion
  carries the urgent part if the section itself is cut.

### 13.3 The query route

GET /v1/metalworking returns the full detail, read from the fresh
collect, not from a cache: furnaces and forges with ids, materials,
and labor assignments; bars by metal with units and stacks; ore on
hand by kind with boulder counts; fuel split (charcoal against coke)
with the fuel floor; the alloy table with which recipes are
available from current stocks and which are blocked and why; melt
fractions per smelter per metal; the forge queue with have/need per
item; and the smith assignments with skills. It reuses the existing
read paths where they exist (GET /v1/stockpiles for the ore, fuel,
and bar stockpiles; GET /v1/sites for furnace and forge sites; the
survey record for veins). The snapshot carries the summary; the route
carries the detail. The agent asks the route when it needs to choose
a recipe or a forge order, never as a matter of routine.

### 13.4 Briefing trigger and cost

Metalworking briefings fire on events, not on ticks. The triggers,
all named from the existing event vocabulary (events.py, briefings.py):

- **Ore struck.** The game announces a new ore on a z-level. The
  briefing names the ore (once identified from mined boulders), the
  vein, and the next step: mine it out and smelt a test bar.
- **First bar smelted.** The chain works end to end for the first
  time. The briefing names the metal, the bars on hand, and what
  the forge can make from them now.
- **Anvil acquired.** The blocker clears. The briefing names the
  anvil's metal and the forge build it unblocks.
- **Fuel out.** Fuel hits zero with ore on hand and no wood, no
  coal, and no magma to make more. The briefing names the dead
  industry and the fix (trade for fuel, logs, or coal).
- **First steel.** The two-step steel reaction completes. The
  briefing names the steel on hand and the squad it arms.

Cost: a briefing is a short text plus its options, about 150 to 250
tokens accountant each, and it is delivered once per trigger, not
every tick. A fort that strikes ore once a season pays that cost once
a season. The briefing never repeats the snapshot section; it names
the event and the choice, and points at the query route for the
numbers. The existing briefing drift rule applies here too
(Military phase 1): a briefing option must name an action the
harness can actually do, or say the action does not exist yet and
what to do instead. A "forge steel axes" option on a fort with no
forge is a bug, not a briefing.

### 13.5 Opportunities entries

There is no separate opportunities list in the code today (verified
by grep: no `opportunit` symbol exists in `src/dfagent_harness/`).
So metalworking opportunities are expressed through the two
mechanisms that already exist, and this doc does not invent a third:

- **The snapshot suggestion.** The assembler already carries one
  suggestion per tick (NEVER_CUT, assembler.py:71), and the planner
  already writes material-blocker and build suggestions through it.
  The metalworking suggestion is one line with a one-line why, in
  the existing shape: "Build a wood furnace (117 wood, 0 fuel, the
  smelter cannot run without charcoal)" or "Smelt 3 hematite (have
  3 ore, 6 fuel, need 3 fuel)" or "Forge 2 iron axes (have 12 bars,
  need 2; the squad has 3 axes for 5 dwarves)". One suggestion per
  tick, the most urgent metalworking step, and only when a step is
  actually runnable. A suggestion never points at a job the fort
  cannot run.
- **Attention entries.** The conditions that outrank a quiet
  suggestion become attention entries, ranked with the other
  problems: fuel at zero with ore on hand, picks at zero with bars
  on hand, the last anvil traded or melted, a full bar stockpile
  cluttering the smelter, a vein mined out with its ore uncounted.
  Attention is for the things that stop the industry, not for the
  things that would be nice.

No other opportunities mechanism is defined here. If a dedicated
opportunities list is built later, it takes these entries over
unchanged; nothing in this doc depends on it existing.

### 13.6 What this doc deliberately does NOT push to the model

- The full alloy table (section 5.3). The model needs to know which
  alloy it can make from current stocks, not all fourteen recipes.
  The query route answers that; the snapshot carries only the next
  step.
- The full ore table (section 3.1). Twelve ores and their layers
  are reference material for the survey and the trade plan, not a
  per-tick fact. The snapshot carries only the ores the fort holds
  and the veins it has found.
- The melt yield table. Fractions per smelter per metal live behind
  the query route. The snapshot carries only "melt smelter #12
  holds 0.8 iron" when a bar is close, and nothing when it is not.
- The survey bitmask and the vein geometry. The survey is an area
  (world-model design section 5); the snapshot carries the nearest
  vein and its distance, and the slice and query routes carry the
  map.
- Per-dwarf smith skills. The snapshot names the missing labor
  ("no armorsmith"), not every smith's skill line. Skills live in
  the units section and the query route.
- The fuel arithmetic. The snapshot carries fuel against its floor;
  the per-recipe fuel math stays in this doc and in the have/need
  check that refuses a job the fort cannot feed.
- The kiln. It is not metalworking (section 1.2), and it is not in
  the metalworking snapshot section. A kiln that burns the fuel
  floor shows up as a fuel exception, not as metal industry.

The rule, restated from the constraint: the snapshot is an index
into the full state, not a replacement for it. The model pulls the
detail when it needs to decide, and the harness never pushes a dump
to save it the asking.

## 14. Refusals

The harness refuses these, and says why in plain words when asked:

1. Never build a forge without an anvil on hand. The anvil is the
   gate, and the fix is to buy one or request one, not to gather.
2. Never build a smelter or forge from a material that is not
   fire-safe, and never build a magma building from a material that
   is not magma-safe. The build fails fast naming the material.
3. Never queue a smelt or forge job without the fuel on hand. The
   fail-fast names the fuel shortfall, not a generic error.
4. Never burn the last fuel without a way to make more. Fuel zero
   with no wood, no coal, and no magma is a dead industry, and the
   harness says so instead of queueing jobs that can never run.
5. Never enable ore for masonry by default. Ore is for smelting,
   and any exception is the agent's named decision.
6. Never forge a craft, a goblet, or a coin from a metal the squad
   still needs. Trade goods come from surplus, never from kit.
7. Never melt artifacts, the last tool of a kind, mandated items,
   or a piece the uniform still needs. Never melt a forbidden item.
   A forbidden melt candidate is not melted, so the harness must
   never forbid one.
8. Never split melt fractions across smelters without saying so.
   One smelter is the melting smelter, per metal where it matters.
9. Never claim a bar, a weapon, or a squad is ready without a live
   read-back: the bars exist in stocks, the item exists in the
   forge's output, the dwarf carries the uniform.
10. Never let the pick count hit zero while bars exist. Picks are
    the industry's first link, and losing them loses the mine.
11. Never use the kiln as metal industry progress. It burns fuel and
    makes no metal.
12. Never send the model a dump. Section 13.6 is the list, and the
    snapshot stays an index.

## 15. Implementation phases, in order

Each phase lands only when its verification bar is met live. A mock
or a unit test alone is not verification.

1. **Metal observation.** Read-only probes: anvils in play (count
   and metal), picks in play, ore boulders by material (extend the
   stocks collect to report BOULDER materials), charcoal and coke
   split out of the bar total, furnaces and forges from the
   buildings read with their materials, and smith labors per dwarf.
   Add the Metalworking section to the snapshot and the
   GET /v1/metalworking route. Verification: a live collect on the
   main fort reports the true anvil count (zero or one, named),
   the true pick count, and fuel split as zero and zero, and the
   snapshot section matches a hand check of the stocks.
2. **Smelt and forge job probes.** Queue SmeltOre, MakeCharcoal,
   MakeWeapon, and MakeArmor jobs on the scratch fort and read the
   job structs back: how do the ore, fuel, and bar items attach to
   a plain job, and can the harness queue one without them? Queue
   one alloy CustomReaction (BRONZE_MAKING) the same way. Record
   the breastplate bar cost from the live job. Verification: each
   probe names the field or the absence of one with a live job id,
   and this doc records the answers. If plain jobs cannot take
   items at queue time, the plan adapts and never claims otherwise.
3. **Fuel first: wood furnace and charcoal.** Build the wood furnace
   (fire-safe material, verified live), assign the wood burner
   labor, queue MakeCharcoal jobs, and establish the fuel floor.
   Verification: live charcoal bars appear in stocks, the fuel
   split reads them back, and a smelt decision refuses with the
   fuel shortfall named when fuel is spent down to zero.
4. **Furnace builds.** Generalize `act_build.lua` to a type-aware
   subtype lookup (`df.furnace_type` for furnaces,
   `df.workshop_type` for workshops), add smelter, wood furnace,
   and kiln to the build path with their fire-safe material rule,
   and add the smelter and forge to WORKSHOP_CATALOG and to
   materials.WORKSHOP_MATERIALS with their have/need text.
   Verification: a smelter and a wood furnace build live on the
   scratch fort from fire-safe stone, read back with their
   materials, and a non-fire-safe material is refused with the
   reason named.
5. **The forge and the anvil.** Add the two-material build path
   (building material plus anvil) to `build_workshop` and
   `act_build.lua`, verify the fort owns an anvil or acquire one
   through trade first, then build the forge. Verification: the
   forge builds live, its anvil reads back by material, and a
   forge build with no anvil fails fast naming the anvil and the
   fix (buy one, request one from the liaison).
6. **Smelting pipeline.** JOB_SPECS entries for SmeltOre and the
   alloy reactions, the smelt have/need check (ore, fuel, operator),
   and the smelt decision in the planner: smelt the nearest
   identified ore to its bar floor. Verification: a live smelt of
   a named ore on the scratch fort produces 4 bars per boulder,
   read back in stocks, and the snapshot names the bars by metal.
7. **Forge pipeline.** JOB_SPECS entries for MakeWeapon, MakeArmor,
   ForgeAnvil, and the metalcrafter jobs, the forge have/need check
   (bars, fuel, smith labor), and the forge queue in the planner,
   ranked picks first, then squad weapons, then armor, then trap
   components, then crafts. Verification: a live forge job produces
   the named item from the named bars, read back in stocks, and the
   uniform have/need counts in the military plan move.
8. **Alloys and steel.** The full alloy JOB_SPECS set from section
   5.3, the ore-route preference (ore over bars, with the yield
   named when bars are the only route), flux tracking (flux stone
   on hand by kind), and the two-step steel chain with its fuel
   accounting. Verification: a live bronze smelt from ore yields 8
   bars, a live steel run from iron bars yields 2 steel for 4 fuel
   at a conventional smelter, and the snapshot shows the flux
   count against the steel plan.
9. **Melt pipeline.** The melt designation probe (write route and
   fraction read-back per smelter per metal), the designated
   melting smelter, and the goblinite flow from the military loot
   count into melt jobs. Verification: a live melt of a named loot
   item adds its fraction to the melting smelter's record, and ten
   tenths produce a whole bar read back in stocks.
10. **Magma.** The magma survey (find the magma sea), magma-safe
    material checks, and magma smelter and forge builds with the
    4/7 depth rule and the impassable-tile check from section 12.
    Verification: a magma smelter smelts ore with zero heat fuel,
    a magma forge forges with zero heat fuel, and a steel run at
    magma costs exactly 2 fuel (the reaction ingredient only).
11. **Fuel economy and the floor.** The fuel floor wired into the
    planner and the snapshot (fuel on hand against fuel needed for
    the ore mined and the bars smelted), the charcoal burn schedule
    against wood stocks, and the coke switch when coal is found.
    Verification: a live season runs with the fuel floor never
    breached, and a fuel-out state produces the section 13.4
    briefing with the fix named.
12. **Military and trap integration.** The forge queue driven by the
    military uniform have/need counts and the trap component list,
    the bolt pipeline (25 per bar, metal war bolts separated from
    wood and bone training bolts), and the goblinite loop counted
    end to end. Verification: a live squad is equipped from forge
    output on the scratch fort, its uniform reads back complete,
    and a weapon trap is loaded with forged components.

## 16. Sources

Wiki pages read from the local index
(`~/workspace/df-wiki-export/dfq.py`, hybrid search default):

- Smelter, Magma smelter, Metalsmith's forge, Magma forge, Wood
  furnace, Kiln, Smelting, Fuel, Metal industry, Ore, Metal, Anvil,
  Bronze, Steel, Melt item, Metal crafter, Armor, Weapon.
- The local index tracks current DF (v50 and later). Every UI-level
  claim from it (shortcuts, click paths, the magma impassable tile)
  is treated as v50 text until verified live against 0.47.05, and
  section 12 lists the ones that matter.

0.47.05 raws, read from the game files in the repo
(`third_party/df_47_05/raw/objects/`):

- `reaction_smelter.txt`: all alloy, coke, pig iron, steel, and
  adamantine reactions in section 5.3, with exact yields.
- `inorganic_stone_mineral.txt` and `inorganic_stone_layer.txt`:
  the ore table in section 3.1 (`METAL_ORE` tokens) and the flux
  stones in section 5.3 (`REACTION_CLASS:FLUX`).
- Ore smelting and charcoal making appear in NO reaction raw: both
  are hardcoded game jobs, which is why they are plain job types in
  the enum fixture and not CustomReaction jobs.

Harness state verified against the repo:

- `tests/fixtures/runtime-enums-0.47.05-r8.json`: `workshop_types`
  (MetalsmithsForge, MagmaForge), `furnace_types` (WoodFurnace,
  Smelter, GlassFurnace, Kiln, MagmaSmelter, MagmaGlassFurnace,
  MagmaKiln), `job_types` (SmeltOre, MeltMetalObject,
  ExtractMetalStrands, MakeWeapon, ForgeAnvil, MakeArmor,
  MakeCharcoal), `unit_labors` (SMELT, FORGE_WEAPON, FORGE_ARMOR,
  FORGE_FURNITURE, METAL_CRAFT, BURN_WOOD, MECHANIC, TRAPPER).
- `src/dfagent_harness/actions.py`: WORKSHOP_CATALOG (carpenter,
  mason, still, kitchen only), JOB_SPECS (brew, cook, carpenter
  jobs only), `build_workshop` (single material, workshop subtype
  only).
- `src/dfagent_harness/lua/act_build.lua`: workshop-only subtype
  lookup, single material.
- `src/dfagent_harness/lua/act_job.lua`: job items from reaction
  reagents; plain-job attachment unverified.
- `src/dfagent_harness/lua/act_labor.lua`: labor toggle with
  read-back by `df.unit_labor` name.
- `src/dfagent_harness/lua/stocks.lua`: `metal_bar_units` counted,
  `by_material` covers DRINK, FOOD, MEAT, FISH, PLANT, SEEDS, BAR,
  WOOD, CLOTH, THREAD only.
- `src/dfagent_harness/survey.py` and `lua/survey.lua`: mineral
  veins unidentified, identified by mined boulders.
- `src/dfagent_harness/observe.py:304`: one snapshot path renders
  the total bar count.
- `src/dfagent_harness/assembler.py`: token accountant (3
  chars/token conservative, 4 chars/token wire), NEVER_CUT
  (attention, header, status, suggestion), budgets 30K/60K/100K/140K.
- `src/dfagent_harness/planner.py`: metal industry deferred for
  lack of ore and forge inputs.
- `src/dfagent_harness/digging.py`: verified digging, the
  exploratory-mining route.
- `docs/ADVANCED_MECHANICS.md` section 4: the `act_build.lua`
  subtype generalization, already queued by the trap work.
- `docs/MILITARY.md` sections 5, 9, 10: tiers, weapons, armor,
  ammunition, traps, goblinite.
- `docs/STOCKPILES.md` sections 4.2, 9.2, 10: ore, fuel, and bar
  stockpiles, melt fractions, bins.
- `docs/TRADING.md`: buy list (steel, flux, an anvil), never-sell
  list (the last anvil, the last pick).
- `docs/KITCHEN.md` section 4.1: the `by_material` coverage limit.
- `~/workspace/goals/dwarf-fortress-0-47-05-autonomous-play-harness/GOAL.md`:
  the presentation constraint (2026-11-27) and the breadth order.

Fort state: `~/.config/df-agent-harness/world.db`, snapshot tick
115166, 2026-11-27 (7 citizens, Carpenters #7 and Still #8 only,
drink 97, food 23, wood 117, stone 0, no metal bars or ore in the
rendered stocks, no survey stored).
