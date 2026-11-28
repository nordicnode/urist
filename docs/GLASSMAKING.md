# Glassmaking

Design record for the glassmaking industry in the Urist harness. This
is the plan. Implementation follows it phase by phase, each phase
verified live against the real game before it counts as done. Anything
not verified against the 0.47.05 game, its raws, or the harness code is
marked UNVERIFIED.

Related docs: docs/STONEWORKING.md (the industry glass most closely
replaces, and the furnace-build blocker both docs share),
docs/METALWORKING.md (furnaces, fuel, the shared build generalization),
docs/TRADING.md (glass trade goods and the elf rules),
docs/STOCKPILES.md (sand bags, raw glass, glass blocks),
docs/FARMING.md (extracts, which need glass vials), docs/MILITARY.md
(glass trap components), docs/ADVANCED_MECHANICS.md (strange moods
that demand raw glass), docs/LABOR.md (the glassmaking labor),
docs/CLOTHING.md (bags, which sand collection consumes).
The kiln side of this industry does not live here: pearlash, potash,
quicklime, and pottery belong to CERAMICS, not to this doc. This doc
consumes pearlash and never makes it. Section 6 draws that line.

## A note on sources, read first

The local wiki export (`~/workspace/df-wiki-export/dfq.py`) holds the
CURRENT wiki, not the 0.47.05 wiki. Its pages use v50 names in places
("Stoneworker" for the mason's workshop, "Furnace operator" wording
that matches 0.47.05 in some places and not others). The local export
was used to find pages and to take the shape of the industry; nothing
in this doc rests on a v50 page alone where the 0.47.05 raws or the
live runtime enum can settle it.

Every game claim in this doc rests on one of these instead:

- The 0.47.05 raws in the install itself
  (`third_party/df_47_05/raw/objects/`), read 2026-11-27: the five
  true sands and the soils that are not sand
  (`inorganic_stone_soil.txt`), rock crystal and its
  `[CRYSTAL_GLASSABLE]` token (`inorganic_stone_gem.txt`), the
  pearlash reaction (`reaction_other.txt`), the glassmaker job
  permission (`entity_default.txt`), and the absence of any glass
  reaction file (there is no `reaction_glassmaking.txt`; glass jobs
  are hardcoded job types, not reactions).
- The live runtime-enum fixture
  (`tests/fixtures/runtime-enums-0.47.05-r8.json`), read 2026-11-27:
  241 job types including `CollectSand`, `MakeRawGlass`, `CutGlass`,
  `EncrustWithGlass`, `MakeWindow`, `MakeTrapComponent`,
  `StrangeMoodGlassmaker`; 7 furnace types including `GlassFurnace`
  and `MagmaGlassFurnace`, which live in `furnace_types`, not in
  `workshop_types`; the `GLASSMAKER` labor.
- The harness code, read 2026-11-27 (section 11).

Where a claim comes from the v50 wiki only, or from memory, it is
marked UNVERIFIED and the phase that proves it is named. The DF2014
namespace pages for glass (DF2014:Glass industry, DF2014:Glass
furnace, DF2014:Sand) were NOT read for this doc: no live browser
was available when it was written, and the v50 export was the only
wiki source on hand. Any claim below that cites a wiki page by name
is therefore v50-sourced until a DF2014 read confirms it, and the
open questions in section 18 name the ones where the version gap
could actually bite.

## 1. Why glassmaking decides whether the fort is rich or poor

Glass is the only industry in the game whose raw material is
infinite, free, and on the surface. One sand tile holds an endless
supply. A magma glass furnace turns that sand into goods worth twice
what stone goods are worth, burning no fuel and consuming nothing
but dwarven labor. No other industry offers that: metal runs out of
ore, wood runs out of trees, stone runs out of nothing but is worth
half as much. A fort with sand and magma has a money printer that
never jams. A fort with sand and no magma has a good trade industry
that eats fuel. A fort with no sand has no glass industry at all,
and must buy its sand bag by bag from caravans.

The wiki puts the shape of it plainly: glass is a versatile and,
under the right circumstances, sustainable source of items, and a
glassmaker can produce nearly everything a fortress needs (Glass
industry, Glassmaker). The industry is a cross between stoneworking
and metalworking: it uses a furnace and fuel like metalworking, and
its product list looks like stoneworking, with a few items only
glass can make.

Three failure modes dominate, and the system in this doc exists to
prevent all three:

1. **Sand nowhere, furnace nowhere.** The fort builds a glass
   furnace before it knows whether the map has sand, or builds it
   far from the sand zone, and the glassmaker waits while the sand
   sits three z-levels away. Sand collection needs a zone, a bag,
   and a hauler; miss any one and nothing happens, silently.
2. **The wrong glass in the wrong job.** Pearlash burned on a
   window is clear glass the fort did not need. Rock crystal spent
   on a goblet is crystal glass that could have been ten goblets.
   Fuel burned on green glass at a standard furnace when a magma
   furnace sits idle one level down is charcoal thrown away.
3. **Bags gone, chain stuck.** Every sand collection needs an
   empty bag, and every glass job returns the bag empty, but bags
   are also what the miller, the dyer, and the seed stockpile want.
   A fort with no bags has no sand, no dye, and no seeds, and the
   snapshot must say "no bags" rather than "no sand".

The harness owns this system. The agent never reasons about sand
tile types, furnace subtypes, or job type numbers. It gets counts,
exceptions, and named options with a one-line why. See section 15.

## 2. How glass works in Dwarf Fortress 0.47.05

### 2.1 Sand: the only input that matters

Sand is a soil, not a stone. There are five true sands, confirmed
in `inorganic_stone_soil.txt` by their `[SOIL_SAND]` token, read
2026-11-27:

| Sand | Raw token | Color |
|---|---|---|
| Sand (tan) | SAND_TAN | tan |
| Yellow sand | SAND_YELLOW | yellow |
| White sand | SAND_WHITE | white |
| Black sand | SAND_BLACK | black |
| Red sand | SAND_RED | red |

The color makes no difference to glassmaking. Any of the five works
for any glass job. The soils that look like sand and are NOT sand,
confirmed in the same file, are sandy clay, sandy clay loam, sandy
loam, and loamy sand. None of them carries `[SOIL_SAND]`, and none
of them can be collected for glass. A fort that zones a sandy loam
flat for collection gets nothing, and the harness must say the zone
is on the wrong soil rather than reporting "sand zone placed".

Sand is found in deserts, on ocean beaches, and sometimes in other
biomes. The embark screen shows "Sand" when the embark has any. A
single sand tile holds an infinite amount of sand: collecting from
it never depletes it. Caverns can also hold small amounts of sand.
Not every map has sand. When the map has none, the only sand comes
from embark points (1 point per bag, bag included) or from caravans,
which bring a few bags each year, more if the liaison is asked for
it (Sand page). Whether the current fort's embark has sand is
UNVERIFIED (section 18): the survey counts soil tiles by z-level
but does not identify sand, and the daemon and game were down when
this doc was written, so no live read exists.

### 2.2 The three glasses

Glass comes in three grades. The values are hardcoded in the game,
not in the raws: the wiki reconstructs them from disassembly as
material values 2, 5, and 10, all with melting point 13600, which
is above magma temperature (12000), so all three are magma safe
(Glass page). The raws cannot confirm these numbers because glass
materials do not exist in the raws at all; that is why this
paragraph is wiki-sourced and the live bar in phase 2 reads the
values back from made items instead of trusting the page.

- **Green glass, value 2.** One bag of sand. Worth twice most
  stone goods, about the same as cheap metals like copper and
  zinc. The workhorse grade. With a magma furnace it costs nothing
  but labor and sand.
- **Clear glass, value 5.** One bag of sand plus one bar of
  pearlash. Worth five times most stone goods, about the same as
  bronze. Pearlash comes from the kiln (CERAMICS), so clear glass
  is a two-industry product and the kiln is its bottleneck.
- **Crystal glass, value 10.** No sand. One rough rock crystal
  plus one bar of pearlash. Worth ten times most stone goods,
  about the same as silver. Rock crystal is not on every map, and
  where it exists it is limited, so crystal glass is rare by
  geology, not by choice. Cut rock crystals bought from traders
  do NOT work for crystal glass (Gem page); only rough rock
  crystal does. The raw confirms the input exists:
  `inorganic_stone_gem.txt` line 439 gives rock crystal
  `[CRYSTAL_GLASSABLE]` and `[MATERIAL_VALUE:2]`.

The grade is chosen per job, not per furnace. A furnace makes any
grade its inputs allow. What the harness must record, per job, is
which grade the job makes and what it costs. How a queued job
specifies its grade is UNVERIFIED (section 18, open question 1):
the enum has one `MakeRawGlass` job type and one set of
`Construct*` job types, so the grade must ride on the job's
material or detail fields, and no harness code has probed those
fields yet.

### 2.3 Raw glass is not glass goods

Raw glass is the gem form: a rough glass "gem" made at the furnace
from sand (green), sand plus pearlash (clear), or rock crystal plus
pearlash (crystal). It can be cut at a jeweler's workshop by a gem
cutter (`CutGlass` in the enum), and the cut glass decorates items
(`EncrustWithGlass`). Raw glass bought from caravans can also be
cut. What raw glass can NOT do is become a glass item: the Glass
page says raw glass cannot be made into glass items, strange moods
excepted. Only sand-bearing bags make glass goods. A fort that
makes raw glass expecting goblets has made gems, not goblets, and
the harness must never count raw glass toward the goods target.
Raw glass is also the strange-mood input: a glassmaker in a fey
mood demands raw glass (ADVANCED_MECHANICS.md section on moods),
and a fort with no raw glass in stock cannot satisfy that mood.

### 2.4 Glass is magma safe, always

All three glasses melt at 13600, above magma temperature. Built
glass furniture survives indefinitely under magma. That makes glass
the magma-safe building material that needs no magma-safe stone
hunt: a fort that has not found dolomite or obsidian can still build
magma-safe floodgates, trap components, tubes, and blocks out of
green glass. One edge, wiki-sourced and UNVERIFIED live: unbuilt
glass items submerged in magma tend to disappear (Bug 10314, Glass
page). The harness never stores loose glass goods where magma can
reach them, and never counts a glass item that fell in magma as
still in stock.

### 2.5 What glass cannot do

Glass cannot make beds, querns, millstones, or slabs (Glass furnace
page). Those stay with the carpenter and the mason. Glass cannot
make generic "crafts" the way a stonecrafter does: the Glassmaker
page says generic crafts are made by a gem cutter, not a
glassmaker, which is a split the harness must respect when it
queues trade goods. Glass cannot make obsidian short swords, which
need obsidian and wood at a craftsdwarf's workshop. Glass cannot
make armor or weapons beyond trap components. Everything else a
mason makes, glass can make, and at twice the value or better.

## 3. The furnaces: the authoritative 0.47.05 list

Glass uses two furnaces. Both are FURNACES, not workshops. That
distinction is load-bearing for the harness: the live enum puts
them in `furnace_types` (`GlassFurnace`, `MagmaGlassFurnace`),
while `workshop_types` has no furnace in it at all (fixture read
2026-11-27). Any code that looks a furnace subtype up in
`df.workshop_type` fails. METALWORKING.md section 9.2 already
records this for the smelter; the glass furnace is the same gap.

Both furnaces are 3x3 in the game layout shown on their wiki
pages. That size is wiki-sourced and UNVERIFIED against the live
build until phase 1 places one and reads back its footprint.

### 3.1 Glass furnace

Shortcut: b-o-u-g. Job requirement: Glassmaking. Built from any
fire-safe building material that is not economic stone, by a dwarf
with Masonry (stone), Blacksmithing, Weaponsmithing, Armoring, or
Metalcrafting (metal). Every job at a standard glass furnace burns
one unit of fuel (coke or charcoal). It also issues the Collect
Sand order.

Fire safety is a real rule with a real failure: a furnace built
from a non-fire-safe material burns. The harness has no fire-safe
check anywhere in its build path today (METALWORKING.md section
9.2). The check has to land with the furnace build work, not after
a wooden glass furnace catches fire. Which materials count as
fire-safe in 0.47.05, and whether the harness can read that from
the raws or must carry a list, is UNVERIFIED (section 18).

### 3.2 Magma glass furnace

Shortcut: b-o-u-G. Job requirement: Glassmaking. Built from any
MAGMA-SAFE building material that is not economic stone, by the
same labors. It burns no fuel at all. It needs magma: it only
becomes available for construction after the fort discovers a
source of magma, and it only functions when one of its eight edge
tiles sits above a channel filled with at least 4/7 magma. If the
magma supply goes away, the furnace stops working at once, even
for Collect Sand, which needs no heat. The magma itself is not
consumed: one tile of magma lasts forever.

The magma furnace is the reason glass is worth building an
industry around. Green glass from a magma furnace costs nothing
but labor and sand, and it is worth twice stone. The cost is
distance: magma is deep, sand is on the surface, and every sand
bag has to travel between them unless the fort hauls magma up or
builds the furnace on a magma pipe near the surface. The layout
section (section 12) deals with that distance; this section only
records that it exists.

### 3.3 Furnace build order

A fort that wants glass builds in this order, and the harness
enforces it:

1. Sand confirmed on the map, or sand bought, before any furnace
   is built. A furnace with no sand is a building with no work.
2. A standard glass furnace first, near the sand zone. It is the
   one that collects sand, and it works before magma is found.
3. A magma glass furnace second, once magma is discovered and a
   magma-safe material is in stock. It takes over production; the
   standard furnace stays as the sand collector.
4. A second standard furnace as a dedicated sand collector, once
   production starts, so Collect Sand never blocks a glassmaker
   mid-job (Sand page recommendation).

## 4. Sand collection

Sand collection is a four-part mechanism, and every part must be
in place before the first bag fills.

### 4.1 The zone

A sand collection zone is an activity zone placed over or next to
sand tiles. Sand can be collected from adjacent sand walls, even
diagonally, so the zone does not need to cover every sand tile.
The harness already has this action: `create_zone` in actions.py
takes `zone_type="sand"`, and `ZONE_KINDS` includes "sand". The
zone action was verified live on civzone #9 on 2026-11-26
(actions.py comment). What is NOT verified is whether a sand zone
placed by the harness actually yields sand when a Collect Sand job
runs against it (section 18, open question 2). Placement must put
the zone on true sand, not on sandy loam: the survey has to tell
the two apart, and today it cannot (section 11.4).

Grass is the quiet failure of sand zones. Grass growing on sand
makes the sand unavailable for collection, and a Collect Sand job
cancels with "Sand vanished" or "Need valid, active sand collection
zone" (Sand page). A paved road over the grass removes it and does
not block collection; a floor grate over a sand floor stops
regrowth and does not block collection, once the grass is removed
first. The harness must watch for cancelled Collect Sand jobs and
name grass as the suspect, not just requeue the job. Whether the
harness can build a paved road or a floor grate over a sand tile
today is UNVERIFIED (section 18).

### 4.2 The job

Collect Sand is job type `CollectSand` in the live enum. It takes
an empty bag, it takes a dwarf with the Item Hauling labor, NOT
the glassmaking labor, and it occupies the furnace until the sand
is collected, so no glassmaker can work that furnace meanwhile.
Only one dwarf collects sand per furnace, which is why the plan
builds several furnaces for collection. The filled bags are left
in the sand collection zone, not carried to the furnace: they wait
there until hauled or picked up by a glass job. A bag of sand is
therefore two hauling jobs (zone to stockpile, stockpile to
furnace) plus the collection itself, and the hauling labor is the
bottleneck long before the glassmaker is.

Collect Sand is a hardcoded job type, not a reaction. There is no
reaction file for it, and `JOB_SPECS` has no entry for it today.
It goes in through the same hardcoded-job shape STONEWORKING.md
needs for mason jobs, and the two docs share that fix.

### 4.3 The bag

Every Collect Sand needs one empty bag. Bags come from three
places: a leather bag made at a leather works, a cloth bag made at
a clothier's shop, or a caravan. Bags are also the container for
milled dye, plaster powder, quicklime, and seeds, so sand
collection bids against the dyer, the kiln, and the farm for the
same small stock. The harness keeps a bag floor: enough empty bags
on hand to keep sand collection running, and it never lets a
single job type eat the last bag. How many bags that floor is, and
whether the harness can count empty bags today (bags are BOX items
in the stocks `by_type` table, but nothing renders them), is
UNVERIFIED (section 18). The bag supply chain itself belongs to
CLOTHING.md (cloth bags) and ANIMAL_HUSBANDRY.md (leather bags);
this doc only records what glass needs from it: at least one empty
bag per furnace collecting sand, plus one per glass job waiting.

Filled sand bags are furniture items. They are stored in furniture
stockpiles with "sand bags" enabled, under type, with all core and
total quality levels allowed (Sand page). A furniture stockpile
that forbids sand bags leaves filled bags sitting in the zone.
STOCKPILES.md already notes that sand bags appear in furniture
stockpiles unless forbidden; the glass stockpile plan (section 13)
builds on that.

### 4.4 Sand without a sand tile

When the map has no sand, glass does not stop entirely. Bags of
sand can be bought at embark and from caravans, and raw glass gems
can be bought and cut. But bought sand is a trickle: a few bags a
year, never enough for an industry. The harness treats bought sand
as a mood reserve, not a production input: keep several bags on
hand for strange moods that demand glass, and never burn the last
bought bag on a goblet. The trade plan (TRADING.md) already says
sand unblocks glass and belongs on the buy list when the map has
none; this doc adds the reserve rule on top of it.

## 5. What glassmakers make

The glassmaker's job list, from the Glassmaker page, read
2026-11-27 (v50 export; the 0.47.05 names are the enum probe in
phase 2):

- Make raw glass (`MakeRawGlass` in the enum).
- Construct glass furniture: the same furniture list the mason
  makes, minus beds, querns, millstones, and slabs. A glass door
  is called a portal, a glass chest a box, a glass pipe section a
  tube, a glass cage a terrarium or aquarium, a glass flask a vial.
  The renamed items are the same items for placement and use; only
  the name changes.
- Make glass goblet (`MakeGoblet`), glass toy (`MakeToy`), glass
  instrument, glass vial (flask, `MakeFlask`), glass window
  (`MakeWindow`), glass trap component (`MakeTrapComponent`).
- Make glass blocks (`ConstructBlocks`), glass pipe sections
  (`MakePipeSection`).
- Glass instruments and instrument pieces, and (v0.42.01 and
  later, so present in 0.47.05) bookcases, book bindings, and
  scroll rollers, where the world's instrument and book types
  allow them.

The furniture jobs are the generic `Construct*` job types
(`ConstructDoor`, `ConstructTable`, and so on), shared with wood
and stone. The goblet, toy, window, flask, trap component, and raw
glass jobs have their own enum entries. The instrument and book
jobs have no confirmed enum entries yet: whether a glass instrument
is a `MakeToy`, a `MakeInstrument` that does not exist in the
fixture, or a job type the fixture does not list is UNVERIFIED
(section 18). Phase 2 enumerates the furnace menu live and
records the real list.

### 5.1 Raw glass and the jeweler

Raw glass is the gem form and the jeweler's training material. A
gem cutter cuts raw glass at a jeweler's workshop (`CutGlass`),
and a gem setter encrusts finished goods with it
(`EncrustWithGlass`). Raw green glass is the cheapest practice
material a jeweler can get: sand plus labor, cut again and again.
The value loop is the point: green glass goods, decorated with
cut green glass, are worth far more than the sum of their parts,
and both the glassmaker and the jeweler train on the same
essentially free input. The jeweler's workshop and the cut-glass
jobs belong to the gem doc when it lands; this doc owns only the
raw glass supply for them. The split matters for the planner: raw
glass made for cutting is jeweler supply, and the glassmaker must
not starve the goods line to feed it, or the other way round.

### 5.2 Vials: the extract link

Vials are the one glass item another industry cannot live without.
A glass vial is a flask, and flasks hold extracts at a farmer's
workshop: golden salve, gnomeblight, venom, and the rest. Without
vials, the fort cannot make extracts at all. Vials can also stand
in for flasks and waterskins for dwarves. The vial floor is small
and absolute: the fort keeps vials in stock before it makes a
single trade goblet, because an extract job that cannot start for
want of a vial is a job the harness must never queue blind. How
many vials the extract chain needs, and whether the farmer's
workshop reads glass vials the same way it reads flasks, is
UNVERIFIED (section 18). FARMING.md owns the extract chain; this
doc owns the vial supply for it.

### 5.3 Windows and display cases

Windows are glass-only items that work like gem windows, and they
are the input for display cases. A display case shows an artifact
or a valued item, and it needs a window to build. A fort with no
glass has no windows and no display cases, whatever else it has.
Windows are also the one glass item whose value is mostly
decorative: a window in a dining hall is a happy thought, not a
trade good. The harness makes windows to the display-case plan,
not to the trade target. Whether display cases in 0.47.05 take a
glass window the way the v50 page says is UNVERIFIED (section 18).

### 5.4 Furniture, blocks, and trap components

Glass furniture is the mason's furniture list at twice the value
or better, and it is magma safe. The fort's dining hall tables,
thrones, coffers, cabinets, doors, floodgates, and statues can all
be glass, and glass floodgates next to magma are the safe choice
when the fort has no magma-safe stone. Glass blocks go to the same
bars/blocks stockpile as stone blocks and build the same
constructions; a glass block wall is magma safe and, in the
graphical versions, transparent, though the game itself never sees
through it. Glass trap components arm weapon traps: a glass trap
component is a valid trap weapon, and the trap plan (MILITARY.md)
takes them the same way it takes metal ones. Whether a glass trap
component is as effective as a metal one, and which trap component
shapes glass can make, is UNVERIFIED (section 18).

### 5.5 Goblets, toys, and trade goods

Goblets are the glass trade good. TRADING.md section 6.1 ranks
them at base 30, the same as mugs and mechanisms, and says green
glass goblets scale well because green glass is nearly free with
sand and a magma furnace. Toys and instruments are the secondary
trade goods, and raw glass cut as gems is the third. The trade
rule for glass is the same as for stone: make in the season before
the caravan, to the value target, obsidian first for stone,
crystal first for glass when the map has rock crystal, and never
from the last bag of sand. The elf rule is the sharp edge: elves
accept green glass, but refuse clear and crystal glass, because
both need pearlash, and pearlash is a wood derivative (TRADING.md
section 2.5). A clear glass goblet offered to an elf ends the
trading session. The harness filters the elf offer through that
list before the agent ever sees it, and the glass section of the
snapshot says which grade each good is, so the agent never has to
remember the rule.

## 6. The pearlash boundary: CERAMICS owns the kiln

Clear and crystal glass need pearlash, and pearlash needs a kiln.
The kiln is not in this doc. The boundary is:

- **CERAMICS owns:** the kiln and magma kiln builds, potash from
  ash and lye at the ashery, pearlash from potash at the kiln
  (reaction `MAKE_PEARLASH` in `reaction_other.txt`: 1 potash bar
  in, 1 pearlash bar out, furnace operator labor, 1 fuel per job
  at a standard kiln), quicklime, plaster powder, and all pottery.
  The reaction was read in the raws 2026-11-27, lines 59 to 63.
- **This doc owns:** counting pearlash bars in stock, refusing a
  clear or crystal job when pearlash is short and naming the kiln
  as the fix, and never queueing a kiln job itself.
- **Shared and contested:** fuel. The kiln burns one fuel per
  pearlash bar, the glass furnace burns one fuel per glass job,
  and the smelter burns one fuel per smelt. Three industries, one
  fuel pile. METALWORKING.md owns the fuel floor; this doc reads
  it and never plans clear glass the fuel cannot cover.

The practical consequence is a dependency order: a fort that wants
clear glass must first have a kiln, an ashery, ash, and fuel. The
glass phases in section 17 assume the kiln exists when they reach
clear glass, and they stop at green glass if it does not. The
planner never queues clear glass on a fort with no kiln, and the
snapshot says "clear glass blocked: no kiln" rather than "no
pearlash", because the kiln is the missing step, not the bar.

## 7. Fuel

Every job at a standard glass furnace burns one unit of fuel:
coke or charcoal. The magma furnace burns none. Fuel comes from
METALWORKING.md section 4: charcoal from 1 log at a wood furnace
(`MakeCharcoal`, wood burner labor, no fuel to run), coke from
bituminous coal (9 per boulder) or lignite (5 per boulder) at a
smelter, confirmed in `reaction_smelter.txt`. The glass fuel math
is simple and the harness does it before every queue: jobs queued
times 1 fuel, against fuel on hand minus the fuel floor. A green
glass job queued with no fuel fails fast and names fuel, not sand.
A magma furnace never checks fuel at all.

The fuel floor is the shared rule: the fort keeps enough fuel for
the smelter, the kiln, and the glass furnace together, and glass
never eats the last fuel the smelter needs for steel. The exact
floor number belongs to METALWORKING.md; this doc reads it and
applies it. What the harness cannot do today is count fuel at all:
`stocks.lua` counts `metal_bar_units` (all BAR items, which
includes charcoal, coke, pearlash, and potash bars together) but
nothing splits fuel bars from pearlash bars, and the assembler
never renders a fuel number. That is a phase 1 gap, shared with
metalworking.

## 8. Bags: the shared input

Bags are the one input every glass job touches and no glass job
makes. The chain is: cloth or leather in, bag out (clothier's shop
or leather works), bag to the sand zone, sand in the bag, bag to
the furnace, glass out, empty bag back. The bag is never consumed
by glassmaking: every job returns it empty. That makes bags a
stock, not a flow, and the fort needs only as many bags as its
furnaces can use at once, plus a spare for each job waiting. The
harness counts empty bags, sand bags, and bags in use separately,
and the snapshot names the smallest of the three numbers, because
that is the binding one.

The bag floor competes with the seed floor, the dye floor, and the
plaster floor, all of which also need bags. The rule is the same
as the fuel rule: glass never takes the last bag the farm needs
for seeds. The bag-making jobs themselves belong to CLOTHING.md
and ANIMAL_HUSBANDRY.md; this doc only names the number it needs.
Whether a cloth bag and a leather bag are interchangeable for sand
collection, and whether the harness can tell an empty bag from a
bag of sand in stocks today, is UNVERIFIED (section 18).

## 9. When glass is worth it, and when it is not

Glass is worth building when the map has sand. It is worth
building early when the map has sand and the fort has found magma
or has fuel to spare. It is worth building late, as a trade
industry only, when the map has sand but fuel is tight and magma
is far. It is not worth building when the map has no sand and no
caravan sand: the furnace would sit idle, and the labor would be
better spent on stone. The harness decides this from the survey,
not from the agent's guess: sand present plus fuel or magma
present means build; sand absent means do not build, and the
snapshot says "no sand on map" once, then stops repeating it.

The value ladder, for the planner's trade ranking (TRADING.md
section 6.1, base values before material and quality
multipliers): glass goblets base 30, the same as stone mugs and
metal mechanisms. Green glass goblets are nearly free with sand
and a magma furnace, so they scale: the fort can make as many as
it has glassmakers, and the only limit is hauling. Clear glass
goblets are worth more per item (material value 5 against green
glass 2) but cost pearlash and fuel, so they are made only when
the kiln is running and fuel is above the floor. Crystal glass
goods are the best value per job in the whole trade list (material
value 10), but rock crystal is limited by geology, so they are
made only while rough rock crystal lasts, and never from cut
crystal.

## 10. Glass in the other systems

Glass touches four systems outside its own chain, and each one
has a claim on it that the planner must respect.

- **Magma projects.** Glass is the magma-safe material that needs
  no stone hunt. Screw pump components (tubes, blocks) and
  floodgates for magma can be glass. The pump plan belongs to the
  machinery doc when it lands; this doc supplies magma-safe tubes
  and blocks to it, and counts them separately from trade goods.
  Which screw pump parts glass can make, and whether a glass screw
  exists, is UNVERIFIED (section 18).
- **Strange moods.** A glassmaker in a strange mood demands raw
  glass (ADVANCED_MECHANICS.md). A fort with sand and a furnace
  but no raw glass in stock fails that mood. The harness keeps a
  small raw glass reserve (starting rule: 3 raw green glass) once
  the furnace exists, and the snapshot flags it when the reserve
  is empty. The reserve size is a starting value, tuned live.
- **Display cases and libraries.** Windows are the display-case
  input, and bookcases, book bindings, and scroll rollers can be
  glass where the world allows. The library plan owns the demand;
  this doc owns the supply.
- **Extracts and healthcare.** Vials are the extract input
  (section 5.2). The extract chain owns the demand; this doc owns
  the vial floor.

## 11. What the harness has today

Verified against the repo 2026-11-27. Everything in this section
was read from the code, not assumed. The daemon and the game were
down when this doc was written (VM replacement about 19:37 PT,
recovery running separately), so no live snapshot was read and
every live value below is flagged UNVERIFIED where it depends on
the running game.

### 11.1 The sand zone exists; the furnace does not

`create_zone` (actions.py) already supports `zone_type="sand"`,
and `ZONE_KINDS` includes "sand". The zone action was verified
live on civzone #9 on 2026-11-26, and `placement.py` lists "sand"
among the zone kinds it scores. That is the one glass input the
harness can already place.

`WORKSHOP_CATALOG` (actions.py) has exactly four workshops:
carpenter, mason, still, kitchen. There is no glass furnace, no
magma glass furnace, no smelter, no kiln, and no wood furnace.
`build_workshop` cannot build any furnace today. `act_build.lua`
hardcodes its subtype lookup to `df.workshop_type`, so a furnace
subtype would error as "unknown workshop subtype". The fix is the
type-aware lookup METALWORKING.md section 9.2 already queued:
`df.furnace_type` for furnaces, `df.workshop_type` for workshops.
Glass needs that fix exactly as metalworking does, and the two
docs share it: whichever lands first, the other uses it. No
furnace build in this doc is a separate implementation; it is the
same generalization, used twice.

### 11.2 No glass job can be queued today

`JOB_SPECS` (actions.py) has exactly these jobs: brew,
brew_fruit, cook, make_bed, make_table, make_chair, make_door,
make_barrel, make_bucket, make_bin, make_chest, make_cabinet.
Every one is a still, kitchen, or carpenter job. There is no
Collect Sand, no Make Raw Glass, no glass furniture job, no
goblet, toy, window, vial, or trap component job in the list.

The gap is structural, the same one STONEWORKING.md records for
mason jobs. Glass jobs are NOT reactions: there is no
`reaction_glassmaking.txt` in the 0.47.05 raws, and the reaction
catalog has no glass reaction to name. Glass jobs are hardcoded
job types (`CollectSand`, `MakeRawGlass`, `MakeGoblet`,
`MakeWindow`, `MakeFlask`, `MakeTrapComponent`, `Construct*`),
and `queue_workshop_job` today can only express reaction jobs
(`job_type` 211, CustomReaction) and the few plain jobs already
in the list. The fix is a second job shape in JOB_SPECS: a
hardcoded `job_type` name with no reaction, plus a way to say
which grade of glass the job makes. Whether the grade rides on
the job's material fields, and whether `queue_workshop_job` can
set those fields at queue time, is UNVERIFIED until probed live
(section 18).

The one existing route that CAN express a glass job today is
`manager_order_create` (actions.py, `act_order.lua`). It takes a
`df.job_type` name directly and creates a manager order. It was
verified live for a generic order, but no glass job type has been
passed through it, and whether the manager validates and
dispatches a furnace job without a manager noble appointed is
UNVERIFIED (section 18). Manager orders also cannot say which
grade of glass to make, as far as the harness knows today, which
is the same open question in a different shape.

### 11.3 The harness cannot see sand, glass, fuel, or bags today

- `stocks.lua` counts `by_type` for every item type, so BOX
  (bags), ROUGH (raw glass and rough gems), SMALLGEM (cut glass),
  WINDOW, FLASK, GOBLET, and BLOCKS counts exist in the raw
  collect. But `by_material` breaks down only DRINK, FOOD, MEAT,
  FISH, PLANT, SEEDS, BAR, WOOD, CLOTH, and THREAD. Raw glass,
  sand bags, and glass goods get no material breakdown, so the
  harness cannot tell green glass from clear glass in stocks, and
  cannot tell a sand bag from an empty bag. Pearlash bars DO appear
  in the BAR breakdown (pearlash is a BAR item), but mixed with
  charcoal and coke bars, so the harness cannot tell fuel from
  pearlash either.
- The assembler renders no glass number anywhere. The snapshot's
  Stocks line prints drink, food, wood, stone, brewable plants,
  empty barrels, and food stacks. It does not print sand bags, raw
  glass, fuel, pearlash, or glass goods. The agent cannot see any
  part of this industry without a query, and there is no query
  route for it either.
- `survey.py` counts soil tiles by z-level and names the richest
  z-levels, and it reports magma bodies and depth to magma. It
  does not identify sand: a soil tile is a soil tile, and the
  survey cannot say whether a given z-level's soil is sand, clay,
  or loam. The embark helper (`embark.py`) lists "Sand" as a
  feature to check, but the value recorded for it is "N/A",
  which means the embark read does not settle it either.
- `placement.py` scores zones including sand zones, and it scores
  workshops, but it has no furnace affinity rows and no rule for
  putting a furnace near a sand zone or near magma. A glass
  furnace placed by the generic scorer could land anywhere.
- `materials.py` knows the mason's, still's, and kitchen's build
  materials. It knows nothing about furnace build materials, the
  fire-safe rule, or the magma-safe rule, because no JOB_SPECS or
  catalog entry exists for a furnace to hang requirements on.
- `build_furniture` (actions.py, `act_furniture.lua`) places
  furniture from stock by item type: bed, table, chair, door,
  coffin, chest, cabinet, armor stand, weapon rack, statue,
  floodgate, hatch, grate. It takes the item from stock and does
  not name its material. Whether it can pick a glass table over a
  wooden one, or whether it takes whatever is on top of the pile,
  is UNVERIFIED (section 18). There is no Window kind in
  `FURNITURE_ITEMS`, so a glass window cannot be placed by it
  today even if one exists in stock.

### 11.4 What the agent can see today

- The snapshot's Buildings line names each workshop by subtype
  and id. It does not name a missing glass furnace. The agent
  cannot tell from the snapshot whether glassmaking is possible
  at all, or whether the map even has sand.
- The snapshot's Stocks line prints no glass number. The agent
  cannot tell whether the fort holds sand bags, raw glass, fuel,
  or pearlash without asking, and there is no route to ask.
- The labor half is ready: `GLASSMAKER` is in the live labor enum,
  and `act_labor.lua` enables or disables any `df.unit_labor` by
  name on one citizen, verified by read-back. The labor plan
  (LABOR.md) owns who gets it; this doc owns what they produce.
  The Collect Sand labor is HAUL_ITEM, which every hauler already
  has.

### 11.5 The current fort, as far as the record shows

The last verified snapshot state (METALWORKING.md section 9,
2026-11-27) reads: 7 citizens, buildings Carpenters #7 and Still
#8 only. No smelter, no forge, no wood furnace, no kiln, no magma
anything, and no glass furnace. Whether the current embark has
sand is UNVERIFIED: no survey read distinguishes sand, the daemon
and game were down when this doc was written, and the embark
record does not settle it. The first thing phase 1 does, before
any build, is answer that question live.

## 12. The chain, end to end

The chain has six steps, and the harness must be able to run all
six without the agent thinking about tiles.

1. **Confirm sand.** The survey identifies sand tiles (phase 1
   adds the read), or the trade plan buys sand, or the chain stops
   here with the reason named.
2. **Zone.** `create_zone` places a sand collection zone on the
   sand. A paved road or floor grate keeps grass off it.
3. **Bags.** Empty bags in stock, at least one per collecting
   furnace. Bags come from the clothier, the leather works, or
   trade.
4. **Collect.** Collect Sand jobs run at a glass furnace, one
   dwarf per furnace, Item Hauling labor. Filled bags wait in the
   zone, then haul to a furniture stockpile by the furnace.
5. **Make.** The glassmaker turns sand bags (plus fuel, plus
   pearlash for clear and crystal, plus rough rock crystal for
   crystal) into goods at the furnace. The bag comes back empty.
6. **Store or sell.** Raw glass goes to a gems stockpile, glass
   blocks to a bars/blocks stockpile, glass goods to a finished
   goods stockpile, sand bags to a furniture stockpile. Trade
   goods go to the trade stockpile in the season before the
   caravan.

The bottleneck moves. Early on it is bags: no bags, no sand.
Then it is hauling: the sand zone is on the surface, the furnace
is underground, and every bag travels the stairs twice. Then it
is fuel, for a standard furnace. Then it is labor: one glassmaker
cannot keep up with a fort that wants a hundred goblets. The
snapshot must show which bottleneck is binding right now, not
just that a furnace exists.

## 13. Stockpiles and storage

The storage rules live in STOCKPILES.md and are not repeated here.
The glassmaking-specific rules are:

- **Sand bags by the furnace.** A furniture stockpile with only
  sand bags enabled, all quality levels allowed, wrapped around
  the glass furnace. The glassmaker takes a few steps for sand
  instead of crossing the fort. Empty bags live in the same pile
  or next to it, so the collector never walks far either.
- **Raw glass in the gems stockpile.** Raw and cut glass store
  under the Gems sub-menu, bins allowed (STOCKPILES.md section
  10: Gems, bins max, near the jeweler). The jeweler reads from
  this pile; the glassmaker does not need it.
- **Glass blocks in the bars/blocks stockpile.** Glass blocks are
  blocks. They share the pile with stone blocks, bins allowed.
  The bin capacity question (5, 10, or 12 per bin) is the same
  open question STONEWORKING.md section 15 records for stone
  blocks; the live count in phase 2 settles both.
- **Glass goods in finished goods.** Goblets, toys, vials,
  windows, and furniture go to a finished goods stockpile, bins
  on, near the furnace and near the depot route. Trade goods are
  pulled from here to the trade stockpile in caravan season.
- **Never dump sand.** Collected sand listed under powder in the
  stocks menu must never be dumped: dumping it dumps the sand out
  of the bags and drops it in useless piles on the floor (Bug
  3220, Sand page). The harness never issues a dump order on sand,
  and the snapshot never suggests it.
- **Fuel near the furnace.** Charcoal and coke bars live in a
  bars stockpile by the furnace, the same way the smelter keeps
  its fuel. Pearlash bars live in the same pile or next to the
  kiln, and the glassmaker's have/need check reads them from
  wherever they are.

## 14. Labor

Two labors run the chain, and they belong to different dwarves:

- **Glassmaking (GLASSMAKER).** The glassmaker skill. One
  glassmaker is the floor for a 7-citizen fort once sand is
  confirmed and a furnace exists; a second joins when the waiting
  job list stays non-empty across two ticks. Skill sets quality,
  and quality multiplies value, so the skilled glassmaker gets
  the crystal and clear jobs and the novice gets green glass
  blocks. A matching material preference is worth about four
  skill levels on average (Skill page, cited in CLOTHING.md),
  so the labor plan's matching rule already handles that.
- **Item hauling (HAUL_ITEM).** Collect Sand needs a hauler, not
  a glassmaker, and the filled bags need furniture hauling
  (HAUL_FURNITURE) to move. The hauling floors belong to the
  labor plan; this doc only records that a fort with no haulers
  has no sand, however many glassmakers it has.

The kiln labor (furnace operator, for pearlash) and the bag labors
(clothesmaking, leatherworking) belong to CERAMICS and CLOTHING.md
and ANIMAL_HUSBANDRY.md. This doc never assigns them; it only
reads whether their products exist.

## 15. Model presentation

This section is required by the 2026-11-27 presentation
constraint (GOAL.md, coordinator log 2026-11-27 about 17:47 PT):
every new system must state how its information reaches the model,
what it costs, and what it deliberately does not push. The snapshot
stays an index: counts, exceptions, and diffs only, about 4,700
tokens typical, never a replacement for full state. Budgets hold
(target 30K, warning 60K, compaction 100K, hard cap 140K on a 200K
window), enforced by the assembler's token accountant with its cut
order. No system bolts its own dump onto the snapshot.

Token costs below are computed from the exact section text with
the accountant's own rates (3 chars per token for the cap, 4 chars
per token on the wire). They are estimates until the coordinator
verifies them against the live assembler before commit, as the
amendment requires. The numbers are small because the section is
an index: it names counts and exceptions, and the detail lives
behind queries.

### 15.1 Snapshot: the Glassmaking section

The per-tick snapshot gains a short Glassmaking section, built
from the fresh collect, in plain words. Three lines, in this
shape, on a fort with a furnace and no sand yet:

```
Glassmaking: sand 0 bags, raw glass 0, fuel 3, pearlash 0.
GlassFurnace #21: 2 jobs queued (goblets). MagmaGlassFurnace: none.
Sand: no sand source found. Bags: 4 empty.
```

What is in it, and what is not:

- **Line 1, counts.** Sand bags in stock, raw glass in stock
  (split by grade only when more than one grade exists), fuel
  bars, and pearlash bars. These are counts, not a list: the
  snapshot never names every glass item in the fort.
- **Line 2, furnaces.** One short clause per glass furnace that
  exists, capped at 3 clauses, then "and N more furnaces" when
  there are more. Each clause names the furnace subtype and id
  (so the model can queue a job without a query turn), its state
  (idle, collecting sand, or jobs queued with the job kinds), and
  nothing else. When no glass furnace exists, the line says so
  and names the fix: "No glass furnace. Sand present: yes. Build
  one: 1 fire-safe stone in stock." A missing furnace is an
  exception, not a silence. When the map has no sand, the line
  says that instead: "No glass furnace. No sand on map."
- **Line 3, sand and bags.** Whether a sand source is known and
  how many tiles the zone covers, plus empty bags on hand. Empty
  bags at zero with sand uncollected is an attention entry,
  ranked with the other problems, never buried in a list. When
  there is no sand zone at all, the line is one clause: "Sand:
  no zone."
- **Diffs, not repeats.** When nothing in the section changed
  since the last tick, the assembler prints the short form
  ("Glassmaking: unchanged (no sand, no furnace)."), the same way
  the Buildings section already does. The section costs its full
  price only on ticks when glass state actually moves.

**Token cost.** At 7 dwarves, the section as written above is 169
characters: about 56 tokens by the accountant's 3-chars-per-token
rate, 42 on the wire. At 50 dwarves, with two furnaces, a magma
furnace, and two grades of raw glass, it is 266 characters: about
89 tokens by the accountant, 66 on the wire. The cost grows by
about 33 tokens from 7 dwarves to 50, because the section is
capped: 3 furnace clauses maximum, 4 stock counts maximum, one
sand line. It does not grow with population, with the number of
sand bags, or with the number of glass items in the fort. If a
future change makes it grow with any of those, the change is
refused until the section is capped again.

### 15.2 Query route: GET /v1/glassmaking

GET /v1/glassmaking returns the full detail, read from the fresh
collect, not from a cache:

- Sand: tiles by color and z-level, zone position and size, bags
  of sand in stock, empty bags, bags in the zone unhauled.
- Furnaces: each furnace by id, subtype, position, construction
  stage, magma supply state for magma furnaces, queued jobs with
  their job types and grades, and the glassmaker assigned to it,
  with skill level.
- Stocks: raw glass by grade, cut glass, glass goods by kind,
  glass blocks, pearlash bars, rough rock crystal, fuel bars
  split from pearlash bars.
- Trade readiness: glass goblets, toys, and cut glass in the
  trade stockpile with their computed values, split by grade so
  the elf filter can be applied, and the caravan target from
  TRADING.md.
- The chain status: which step is stuck, named in one line.

The snapshot carries the summary and the ids; the route carries
the detail. The agent asks the route when it needs to choose
which grade to make or which furnace is stuck, never as a matter
of routine. A second route, GET /v1/glassmaking/<furnace-id>,
returns one furnace in full: its queued jobs, its grades, and its
worker. Both routes state their cost and staleness on every
response, the same as every other query route.

### 15.3 Briefing: what arrives just in time

Glassmaking has no standing briefing. Two events carry one, both
from the existing briefing system (briefings.py), each a few
hundred tokens at most, each fired once when the event starts:

- **Caravan arrives.** Trigger: the caravan event. Cost: about
  30 tokens by the accountant for the glassmaking paragraph
  (90 characters). It covers what glass goods are in the trade
  stockpile and their approximate value, split by grade, and
  whether any of them are clear or crystal glass the elves will
  refuse. It leaves the per-item values and the depot haggling
  to the query route and to TRADING.md.
- **Strange mood, glassmaker.** Trigger: the mood event, when the
  moody dwarf is a glassmaker or the mood demands raw glass.
  Cost: about 50 tokens. It covers whether raw glass is in stock
  and whether a furnace exists to make more. It leaves the mood
  plan to ADVANCED_MECHANICS.md. A fort with raw glass in stock
  gets no briefing at all: the briefing fires only when the fort
  cannot satisfy the mood.

No other glassmaking event briefs the model. A glassmaker
finishing a masterwork, a sand bag stock hitting zero, or a
furnace running out of fuel are attention entries and
opportunities entries, not briefings. A briefing is for something
the model needs to understand right now, not for something it can
read in the snapshot.

### 15.4 Opportunities: at most 3, facts only

The opportunities section carries at most 3 glassmaking entries,
each one line: facts plus a query route, never a suggestion, never
a pause. Ignoring one costs nothing. Examples of what qualifies:

- "Sand present, no glass furnace. Query /v1/glassmaking for
  the sand tiles."
- "14 sand bags in stock, 0 glass goods in the trade stockpile,
  caravan in autumn. Query /v1/glassmaking for the trade
  readiness."
- "Magma discovered, no magma glass furnace, 22 fuel left.
  Query /v1/glassmaking for the furnace list."

An opportunities entry fires only when the fact is actionable
and the snapshot alone does not already say it. A glass furnace
with jobs queued is not an opportunity; it is the snapshot doing
its job. The entry never names the action to take and never
carries a cost estimate. The model decides.

### 15.5 What the system deliberately does NOT push, and why

- **The full sand tile list.** The map may hold hundreds of sand
  tiles. The snapshot names the zone size; the full list is
  behind GET /v1/glassmaking. A list of sand tiles every tick is
  a dump, and the model cannot act on the 200th sand tile anyway.
- **Per-bag positions.** Where each sand bag sits is survey data,
  pulled by region when the model needs it. Pushing it would grow
  the snapshot with the map, which breaks the index.
- **Per-item glass values.** The snapshot says how many goblets
  are in the trade stockpile. The computed value of each item is
  behind the query route, because values change with quality and
  grade and the snapshot cannot reprice the stock every tick.
- **The whole job queue.** The snapshot says "2 jobs queued
  (goblets)". The full queue, with job ids and grades, is behind
  the furnace query route. A queue dump would grow with every job
  the fort queues.
- **Furnace placement suggestions.** The snapshot never says "put
  a furnace here". Placement is the scored site system, and the
  model asks for a site when it decides to place something. The
  presentation gives the model what it needs to decide, not a
  script to follow (HARNESS_ROLE.md).
- **The kiln's state.** Pearlash bars are counted here because
  glass jobs consume them. How the kiln makes them, and whether
  the kiln is running, belongs to the CERAMICS snapshot section
  when it lands, not to this one. One number crosses the boundary;
  the kiln's whole state does not.

## 16. Refusals

The harness refuses these, and says why in plain words when asked:

1. Never build a glass furnace out of a non-fire-safe material,
   and never build a magma glass furnace out of a non-magma-safe
   material. Fire safety and magma safety are properties of the
   material in the raws, not of the furnace's name.
2. Never queue a glass job without its full inputs: a sand bag
   for green and clear, a rough rock crystal for crystal, a
   pearlash bar for clear and crystal, and one fuel for a standard
   furnace. A job that cannot start is a job that blocks the
   queue.
3. Never burn the last bought bag of sand on a trade good. Bought
   sand is the mood reserve, not production input.
4. Never make clear or crystal glass on a fort with no kiln, and
   never queue a kiln job from this doc. The kiln belongs to
   CERAMICS; this doc reads pearlash and stops there.
5. Never offer clear or crystal glass to elves. They refuse it,
   and one refused item ends the trading session. The elf filter
   runs before the agent sees the offer.
6. Never count raw glass toward the goods target. Raw glass is
   gems, not goods, and it cannot become a goblet.
7. Never dump sand from the stocks menu. Dumping sand dumps it out
   of the bags onto the floor, where it is useless (Bug 3220).
8. Never place a sand zone on sandy loam, loamy sand, sandy clay,
   or sandy clay loam and call it sand. Those soils are not sand,
   and the zone will collect nothing.
9. Never claim a glass job works until a real item has been made
   and read back. A job type name from the enum is not proof the
   game accepts it with the grade the harness asked for, and a
   manager order that sits unvalidated is not proof the game
   dispatched it.
10. Never let the glass furnace eat the last fuel the smelter
    needs, or the last bag the farm needs for seeds. Glass shares
    fuel and bags with industries that cannot wait a season.
11. Never store loose glass goods where magma can reach them.
    Unbuilt glass in magma disappears (Bug 10314).
12. Never claim the fort has a glass industry because it has a
    furnace. A furnace with no sand, no bags, and no fuel is a
    building, not an industry, and the snapshot says which of the
    three is missing.

## 17. Implementation phases

Each phase ends with a live-verification bar. A phase that cannot
be verified live is logged as unverified and re-attempted, per the
standing rule. Nothing unverified gets pushed.

### Phase 1: Sand, fuel, and bags can be seen

- Add the sand read to the survey: which soil tiles are true
  sand (the five `[SOIL_SAND]` materials from
  `inorganic_stone_soil.txt`), by z-level, so the harness can
  tell sand from sandy loam before it zones anything. Record
  whether the current fort's embark has sand, and if it does not,
  record the buy-sand plan from TRADING.md instead of building.
- Split the stocks read: sand bags from empty bags (BOX items by
  material and content), raw glass by grade (ROUGH items by glass
  material), fuel bars from pearlash bars (BAR items by material),
  and glass goods by kind. The `by_type` table already counts
  these; the work is the material breakdown and the headline
  numbers.
- Live bar: on the main fort, the survey names the sand z-levels
  (or reports "no sand" with the evidence), and the stocks read
  reports sand bags, empty bags, fuel, and pearlash as separate
  numbers that match a hand count from the game's stocks screen.

### Phase 2: Probe the glass job types and the grade question

- Probe the exact `df.job_type` names and the grade mechanism
  live against the running game: `CollectSand`, `MakeRawGlass`,
  the glass furniture `Construct*` jobs, `MakeGoblet`, `MakeToy`,
  `MakeFlask`, `MakeWindow`, `MakePipeSection`,
  `MakeTrapComponent`, and the instrument and book jobs if the
  furnace menu shows them. For each job, record how the grade is
  chosen (job material fields, job details, or a separate job
  type per grade), and whether a queued job takes its inputs at
  queue time or picks them when a dwarf starts it. Record the
  answers in the code and in this doc. A name the game does not
  accept is a failed probe, not a job.
- Probe `build_furniture` for material selection: place a glass
  table from stock while a wooden table is also in stock, and
  record which one the action takes and whether the caller can
  choose.
- Live bar: on the scratch fort, each probed job type is accepted
  by `df.job_type` without error, and one green glass goblet is
  made from one sand bag and one fuel and read back in stock with
  its material value; the empty bag is read back empty.

### Phase 3: Build the furnaces

- Generalize `act_build.lua` with a type-aware subtype lookup
  (`df.furnace_type` for furnaces, `df.workshop_type` for
  workshops), shared with METALWORKING.md phase 4. Add the glass
  furnace and the magma glass furnace to the build path with
  their material rules (fire-safe, magma-safe, non-economic).
  Add the fire-safe and magma-safe material checks to the build
  path, reading the property from the raws where possible.
- Add placement affinity for furnaces: a glass furnace near the
  sand zone and near the sand-bag stockpile, a magma glass
  furnace near magma and near the sand-bag route.
- Live bar: on the scratch fort, a glass furnace is built by
  `build_workshop` from fire-safe stone and read back in the
  buildings list with its subtype and id; a build from a
  non-fire-safe material is refused with the reason named; a
  magma glass furnace builds only when magma is discovered and
  4/7 magma sits under an edge tile, and reads back working.

### Phase 4: Sand collection end to end

- Wire the chain: `create_zone` sand zone on surveyed sand,
  Collect Sand queued at a dedicated furnace, filled bags hauled
  to the furniture stockpile by the furnace, and the bag floor
  enforced so collection never eats the farm's last bag.
- Handle the grass failure: when a Collect Sand job cancels,
  the result names grass as the suspect and the fix (paved road
  or floor grate), instead of silently requeueing.
- Live bar: on the scratch fort, a sand zone is placed on surveyed
  sand, a Collect Sand job fills a bag, the filled bag is read
  back in the furniture stockpile by the furnace, and a second
  Collect Sand job runs while a glassmaker works the production
  furnace, proving collection does not block production.

### Phase 5: Queue glass jobs

- Add the hardcoded job shape to `JOB_SPECS`: a `job_type` name
  with no `reaction_name`, for Collect Sand and the glass jobs
  probed in phase 2, with the grade carried the way phase 2 found
  it. Wire the material fail-fast through `materials.py`: each
  job names what it needs (sand bag; fuel for a standard furnace;
  pearlash for clear and crystal; rough rock crystal for
  crystal), and a job whose materials are short is never queued.
  The failure names the exact gathering fix, the same as brew
  and cook do today.
- Add the vial floor (section 5.2) and the raw glass mood reserve
  (section 10) to the planner: vials first, then trade goblets,
  then furniture, then raw glass for the jeweler.
- Live bar: on the scratch fort, a glassmaker queues green glass
  goblets from sand bags and fuel and the goblets are read back;
  a clear glass job queued with no pearlash fails fast with
  pearlash named and the kiln named as the fix; a crystal glass
  job queued with no rough rock crystal fails fast with rock
  crystal named; a vial is made and read back.

### Phase 6: Magma furnace production and the snapshot section

- Move production to the magma furnace once it exists: green
  glass jobs go to the magma furnace (no fuel), the standard
  furnace keeps collecting sand. Wire the fuel saving into the
  planner: a green job queued at a standard furnace while a magma
  furnace sits idle is refused with the reason named.
- Add the Glassmaking snapshot section (section 15.1) and the GET
  /v1/glassmaking route (section 15.2), with the sand read, the
  furnace records, the grade-split stocks, and the trade
  readiness. Add the caravan briefing paragraph and the strange
  mood briefing paragraph (section 15.3), and the opportunities
  entries (section 15.4).
- Live bar: on the main fort, the snapshot's Glassmaking section
  prints true counts (sand bags, raw glass by grade, fuel,
  pearlash) and the token cost is measured against the live
  assembler at 7 dwarves and at the largest population the fort
  reaches; GET /v1/glassmaking returns the full breakdown; a
  caravan-season run produces green glass goblets that reach the
  trade stockpile and read back there, and the fuel count does not
  fall while the magma furnace runs.

### Phase 7: Clear and crystal glass, and the jeweler link

- Wire clear glass through the kiln boundary: the planner queues
  clear glass only when pearlash is above its floor and fuel is
  above its floor, and the snapshot says which floor binds when
  it is not. Wire crystal glass only while rough rock crystal
  lasts, and never from cut crystal.
- Wire the raw glass supply to the jeweler: raw green glass made
  to the jeweler's training target, cut at the jeweler's workshop
  (`CutGlass`), and encrusted (`EncrustWithGlass`) on glass goods
  first, so the value loop closes.
- Live bar: on the scratch fort, a clear glass goblet is made from
  one sand bag, one pearlash bar, and one fuel and read back with
  its grade; a crystal glass item is made from one rough rock
  crystal and one pearlash bar where the map has rock crystal, or
  the phase records that the map has none and crystal glass is
  closed for this fort; a raw green glass is cut at the jeweler's
  workshop and read back as cut glass.

## 18. Open questions

All marked UNVERIFIED until a live probe or a raw read settles
them.

1. How a queued glass job specifies its grade (green, clear,
   crystal). The enum has one `MakeRawGlass` and one set of
   `Construct*` job types, so the grade must ride on job fields
   the harness has not probed. Phase 2 settles it.
2. Whether a sand zone placed by `create_zone` actually yields
   sand when a Collect Sand job runs against it, and whether the
   zone must cover sand tiles or only sit next to them. Phase 4
   settles it live.
3. Whether the current fort's embark has sand at all. The survey
   cannot tell sand from other soil today. Phase 1 settles it.
4. Which materials are fire-safe and magma-safe in 0.47.05, and
   whether the harness can read that from the raws or must carry
   a list. Phase 3 settles it.
5. Whether `queue_workshop_job` can express hardcoded jobs at
   all, or whether glass jobs go only through manager orders.
   The current action assumes `job_type` 211 (CustomReaction).
   Shared with STONEWORKING.md open question 2. Phase 2 settles
   it.
6. Whether a manager order for a glass job dispatches without a
   manager noble appointed, and how the grade is chosen on a
   manager order. Phase 2 settles it.
7. Whether `build_furniture` can choose a glass item over a wood
   or stone item of the same kind, or takes whatever is on top of
   the pile. Phase 2 settles it.
8. Whether a cloth bag and a leather bag are interchangeable for
   sand collection, and whether the harness can tell an empty bag
   from a sand bag in stocks today. Phase 1 settles the count;
   phase 4 settles the interchange live.
9. How many vials the extract chain needs, and whether the
   farmer's workshop reads glass vials the same way it reads
   flasks. Phase 5 settles it with FARMING.md.
10. Whether display cases in 0.47.05 take a glass window the way
    the v50 page says, and whether glass windows have any other
    use. Phase 5 settles it.
11. Which trap component shapes glass can make, and whether a
    glass trap component fights as well as a metal one. Phase 5
    settles it with MILITARY.md.
12. Which screw pump parts glass can make, and whether a glass
    screw exists. The machinery doc settles it when it lands;
    until then the pump claim in section 10 stays UNVERIFIED.
13. Whether the glass instrument and book jobs (instruments,
    instrument pieces, bookcases, book bindings, scroll rollers)
    have enum entries, and what job type names them. Phase 2
    enumerates the furnace menu live.
14. Whether the harness can build a paved road or a floor grate
    over a sand tile to keep grass off, and which action does it.
    Phase 4 settles it.
15. The bin capacity for glass blocks: 5, 10, or 12 per bin. The
    same open question STONEWORKING.md records for stone blocks.
    Phase 2 settles it with a live count.
16. Whether the DF2014 glass pages differ from the v50 pages this
    doc cites on any point that matters: the furnace menu, the
    Collect Sand labor, the grade inputs, or the window and vial
    uses. A DF2014 read settles it; until then every wiki-sourced
    claim in sections 2, 4, and 5 carries that caveat.

## 19. Cross-doc conflicts flagged

None of these are contradictions in the game. They are places
where two docs say things that must agree, and where the agreement
has not been verified yet.

1. **METALWORKING.md vs this doc on the furnace build.** Both
   docs need the same `act_build.lua` generalization
   (`df.furnace_type` lookup). METALWORKING.md phase 4 queues it
   for the smelter; this doc phase 3 queues it for the glass
   furnace. Whichever lands first serves both. No conflict, but
   the two phases must not be implemented twice in different
   shapes.
2. **STONEWORKING.md vs this doc on the hardcoded job shape.**
   Both docs need a JOB_SPECS entry that is a hardcoded `job_type`
   with no reaction. Stone needs it for mason jobs; glass needs
   it for furnace jobs. Same fix, same shape, one implementation.
   STONEWORKING.md open question 2 and this doc open question 5
   are the same question.
3. **STONEWORKING.md vs this doc on what glass replaces.**
   STONEWORKING.md says glass can replace masonry except for
   querns, millstones, slabs, crafts, and stone short swords. The
   Glass industry page says the same, except it lists slabs,
   querns, and millstones as the mason-only items and adds crafts
   and short swords as the craftsdwarf-only items. The two
   accounts agree; the difference is only which workshop the
   exception belongs to. No live check needed.
4. **TRADING.md vs this doc on clear glass and elves.** TRADING.md
   section 6.1 says "Clear glass costs wood and cannot be sold
   to elves." This doc says clear and crystal glass need
   pearlash, which is a wood derivative, and elves refuse both.
   The two agree, and TRADING.md section 2.5 gives the full ban
   list. The "costs wood" phrasing is shorthand for the pearlash
   chain, not a claim that clear glass contains a log.
5. **STOCKPILES.md vs this doc on raw glass storage.** STOCKPILES.md
   puts raw glass under Gems, bins max, near the jeweler. This doc
   agrees. No conflict.
6. **STOCKPILES.md vs this doc on sand bags.** STOCKPILES.md notes
   sand bags appear in furniture stockpiles unless forbidden. This
   doc builds a dedicated sand-bag pile by the furnace. The two
   agree; the dedicated pile is the implementation of the note.
7. **CLOTHING.md vs this doc on bags.** CLOTHING.md owns cloth
   bags; ANIMAL_HUSBANDRY.md owns leather bags. This doc consumes
   bags and never makes them. The bag floor in section 8 is a
   demand on those docs, not a second bag system. If the bag
   floor and the dye bag floor disagree on who gets the last bag,
   the seed floor wins first, then the dye floor, then glass.
   That priority is stated here for the first time and needs the
   owning docs to confirm it.
8. **FARMING.md vs this doc on vials.** FARMING.md owns extracts;
   this doc owns vials. Neither doc states how many vials the
   extract chain needs. Open question 9 is the gap, owned jointly.
9. **METALWORKING.md vs this doc on fuel.** METALWORKING.md owns
   the fuel floor; this doc reads it. No number is stated in
   either doc yet, so there is nothing to disagree on, but the
   first number written in either doc must be checked against the
   other.
10. **ADVANCED_MECHANICS.md vs this doc on moods.** ADVANCED_MECHANICS.md
    says a glassmaker mood demands raw glass. This doc keeps a
    raw glass reserve of 3 for it. The reserve size is a starting
    value from this doc, not from ADVANCED_MECHANICS.md, and the
    mood doc has not confirmed it is enough.

## 20. Failure modes

The ways this industry fails, in the order the harness is most
likely to meet them:

1. **No sand on the map, furnace built anyway.** The fort spends
   stone and labor on a furnace with no work. Prevention: phase 1
   answers the sand question before any build. Detection: the
   snapshot says "no sand on map".
2. **Sand zone on the wrong soil.** Sandy loam zoned as sand,
   Collect Sand cancels, glassmaker waits. Prevention: the survey
   identifies true sand before zoning. Detection: cancelled Collect
   Sand jobs name the soil.
3. **Grass over the sand.** Collection cancels with "Sand
   vanished". Prevention: paved road or floor grate. Detection:
   the cancel message names grass as the suspect.
4. **No bags.** Collection cannot start, and the snapshot blames
   sand. Prevention: the bag floor. Detection: the snapshot names
   bags, not sand, as the binding number.
5. **Collect Sand blocks the production furnace.** One furnace,
   one collector, glassmaker idle. Prevention: a dedicated
   collection furnace. Detection: the furnace clause says
   "collecting sand" while jobs wait.
6. **Fuel runs out mid-season.** Green glass jobs fail, and the
   failure blames sand. Prevention: the fuel check before every
   queue. Detection: the fail-fast names fuel.
7. **Pearlash spent on the wrong grade.** Clear glass made where
   green would do, kiln starved. Prevention: the planner queues
   clear only above the pearlash floor. Detection: the pearlash
   count falls while green jobs wait.
8. **Clear glass offered to elves.** Trading session ends.
   Prevention: the elf filter. Detection: the trade offer is
   filtered before the agent sees it, so there is nothing to
   detect if the filter works; if it fails, the caravan event
   names it.
9. **Raw glass counted as goods.** The trade target looks met
   and the caravan leaves with gems, not goblets. Prevention:
   raw glass never counts toward the goods target. Detection: the
   trade readiness splits raw glass from goods.
10. **Magma furnace goes dry.** The magma supply is cut, the
    furnace stops, even Collect Sand stops. Prevention: the
    snapshot reads the magma supply state. Detection: the furnace
    clause says "no magma" instead of "idle".
11. **Sand dumped from stocks.** A dump order on powder empties
    the bags onto the floor (Bug 3220). Prevention: the harness
    never dumps sand. Detection: sand bags read back empty while
    sand piles appear on the floor.
12. **Glass goods lost to magma.** Unbuilt glass stored where
    magma reaches it disappears (Bug 10314). Prevention: glass
    stockpiles never sit next to open magma. Detection: the goods
    count falls with no job to explain it.

## 21. Sources

Wiki pages, all from the CURRENT (v50) export
(`~/workspace/df-wiki-export/dfq.py`), read 2026-11-27. The DF2014
namespace was not available when this doc was written; see the
sources note at the top and open question 16.

- Glass industry (1,773 words): the chain shape, sand and fuel as
  limiting factors, Collect Sand and its zone, the three grades
  and their inputs, green glass worth twice stone, clear five
  times, crystal ten times, the stoneworking and metalworking
  comparisons, the minecart note.
- Glass furnace (847 words): the job list, the renamed items
  (portal, box, tube, terrarium, vial), the exceptions (beds,
  millstones, querns, slabs), the fire-safe build rule, one fuel
  per job.
- Magma glass furnace (922 words): identical jobs, no fuel, the
  magma discovery rule, 4/7 magma under an edge tile, magma not
  consumed, the furnace stops at once when magma goes away.
- Glass (1,065 words): the three values (2, 5, 10), melting point
  13600, raw glass cannot become glass items, cut glass as gems,
  the glass material reconstructions from disassembly.
- Sand (1,465 words): the five true sands, the four false sands,
  infinite sand per tile, the zone rules, grass failures and the
  road and grate fixes, bags from leather works, clothier, or
  trade, sand bags as furniture, the dump bug (Bug 3220), bought
  sand as a trickle.
- Glassmaker (698 words): the job list, the gem cutter split for
  generic crafts, green glass indefinitely from a magma furnace.
- Kiln (635 words for Pearlash; kiln page): pearlash as the clear
  and crystal input, kiln jobs and their labors, each kiln action
  burning one fuel.
- Gem (5,901 words): cut rock crystals cannot make crystal glass.

0.47.05 raws, read from the install 2026-11-27
(`third_party/df_47_05/raw/objects/`):

- `inorganic_stone_soil.txt`: the five `[SOIL_SAND]` materials
  (SAND_TAN, SAND_YELLOW, SAND_WHITE, SAND_BLACK, SAND_RED) and
  the four non-sand soils (SANDY_CLAY, SANDY_CLAY_LOAM,
  SANDY_LOAM, LOAMY_SAND) with no `[SOIL_SAND]` token.
- `inorganic_stone_gem.txt` line 439: rock crystal carries
  `[CRYSTAL_GLASSABLE]` and `[MATERIAL_VALUE:2]`.
- `reaction_other.txt` lines 59 to 63: `MAKE_PEARLASH`, 1 potash
  bar in, 1 pearlash bar out.
- `reaction_smelter.txt`: BITUMINOUS_COAL_TO_COKE gives 9 coke,
  LIGNITE_TO_COKE gives 5 (cited in METALWORKING.md).
- `entity_default.txt`: `[PERMITTED_JOB:GLASSMAKER]` for the
  dwarven entity.
- No `reaction_glassmaking.txt` exists in the raws: glass jobs
  are hardcoded job types, not reactions. That absence is itself
  the finding.

Live runtime enum fixture, read 2026-11-27
(`tests/fixtures/runtime-enums-0.47.05-r8.json`, 241 job types):

- Job types: `CollectSand`, `MakeRawGlass`, `CutGlass`,
  `EncrustWithGlass`, `MakeWindow`, `MakeTrapComponent`,
  `MakeGoblet`, `MakeToy`, `MakeFlask`, `MakePipeSection`,
  `ConstructBlocks`, `StrangeMoodGlassmaker`.
- Furnace types: `WoodFurnace`, `Smelter`, `GlassFurnace`, `Kiln`,
  `MagmaSmelter`, `MagmaGlassFurnace`, `MagmaKiln`. Furnaces live
  in `furnace_types`; `workshop_types` holds no furnace.
- Labors: `GLASSMAKER`, `HAUL_ITEM`, `HAUL_FURNITURE`.

Harness state verified against the repo 2026-11-27: actions.py
`WORKSHOP_CATALOG` (four workshops, no furnace), `JOB_SPECS`
(no glass jobs), `ZONE_KINDS` and `create_zone` (sand kind
present, verified live on civzone #9 2026-11-26),
`manager_order_create` and `act_order.lua` (takes a
`df.job_type` name), `build_furniture` and `FURNITURE_ITEMS`
(no Window kind, material selection unprobed),
`act_build.lua` (subtype lookup hardcoded to
`df.workshop_type`), `act_labor.lua` (any labor by name),
`stocks.lua` (`by_type` counts all item types, `by_material`
covers only DRINK, FOOD, MEAT, FISH, PLANT, SEEDS, BAR, WOOD,
CLOTH, THREAD), `survey.py` (soil by z-level, magma bodies, no
sand identification), `placement.py` (zone kinds including sand,
no furnace affinity rows), `materials.py` (no furnace materials),
`assembler.py` (no glass numbers in any section),
`briefings.py` (briefing system, no glass kinds),
docs/TRADING.md (glass goblets base 30, elf ban on clear and
crystal glass, sand on the buy list), docs/STONEWORKING.md (the
hardcoded job shape, the furnace-build blocker, the bin capacity
question), docs/METALWORKING.md (furnace table, fuel, the
`act_build.lua` generalization, phase 4), docs/STOCKPILES.md
(sand bags in furniture stockpiles, raw glass under Gems),
docs/ADVANCED_MECHANICS.md (glassmaker moods demand raw glass),
GOAL.md and the coordinator log 2026-11-27 (the presentation
constraint and the breadth-doc amendment).
