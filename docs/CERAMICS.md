# Ceramics

A plan for giving Urist a ceramics industry: clay collection, the
kiln, earthenware, stoneware, porcelain, glazing, plaster for the
hospital, pearlash for glass, and quicklime for parchment, plus what
the harness needs to observe, build, queue, and verify for all of
it. Everything here is researched from the local DF wiki index, from
the 0.47.05 raw files shipped with the game, and from the harness
code. Nothing is guessed. Anything not verified against the wiki,
the raws, or the live game is marked UNVERIFIED.

Status: design only. No ceramics code exists yet. The coordinator
owns implementation; this doc is the record it builds from.

Related docs: docs/METALWORKING.md (the kiln as a fuel competitor,
and the fuel economy the kiln draws on), docs/WOODWORKING.md
(the ash and potash chain that feeds pearlash and glazing),
docs/STONEWORKING.md (economic stone, the plaster-stone feeder, and
the clay stockpile), docs/STOCKPILES.md (clay, fuel, and bar
stockpiles), docs/TRADING.md (ceramic trade goods and the elf
rules), docs/FARMING_PLAN.md (potash as fertilizer),
docs/SITE_SELECTION.md (scored placement for the kiln),
docs/ANIMAL_HUSBANDRY.md (beehives, which the kiln makes).
Glass furnace products belong to GLASSMAKING.md, which was written
in parallel with this doc (2026-11-27) and draws the same boundary
from the glass side: CERAMICS owns the kiln, pearlash, quicklime,
and pottery; GLASSMAKING owns the glass furnace and consumes
pearlash without making it. This doc builds on the docs above and
does not duplicate them.

## 1. What ceramics is in DF 0.47.05

Ceramics is the chain that turns soil and stone into pots, bricks,
statues, crafts, hives, plaster, pearlash, and quicklime. It has
three raw materials, one building, and three labors at its centre,
plus two crossover products that exist only to feed other
industries:

1. **Clay.** Collected from soil tiles through a clay collection
   zone, by any dwarf with item hauling. It never runs out: one
   clay tile can be harvested indefinitely. Clay boulders fire into
   earthenware (or stoneware, from fire clay).
2. **Kaolinite.** Mined like any stone, in sedimentary clusters.
   It fires into porcelain. It is finite: when the cluster is gone,
   it is gone.
3. **The kiln.** Every ceramics job runs at a kiln (or a magma
   kiln), and every job at a standard kiln burns one unit of fuel.
   The potter fires wares, the glazer glazes them, and the furnace
   operator makes pearlash, plaster powder, and quicklime.
4. **Glazing.** Earthenware containers must be glazed before they
   hold liquid. Glazing needs ash or cassiterite, plus fuel.
   Stoneware and porcelain are waterproof without it.
5. **The crossovers.** Plaster powder feeds the hospital (casts).
   Pearlash feeds the glass furnace (clear and crystal glass).
   Quicklime feeds the ashery (milk of lime) and then the tanner
   (parchment). None of the three is a ceramics product for its
   own sake; each exists because another industry needs it.

Ceramics is a secondary industry, not a survival industry. A fort
with no kiln still drinks, eats, and fights. What a fort without
ceramics lacks is: cheap waterproof containers that weigh less than
stone, a trade good it can make forever from dirt, plaster for
broken bones, and the pearlash its glass industry cannot run
without. The plan respects that order: the first ceramics work is
finding out whether the map has clay at all, and the first kiln job
with a deadline on it is plaster, not a statue.

### 1.1 The 0.47.05 buildings in the chain, verified

The authoritative list is the live runtime enum fixture the harness
already probes against the game,
`tests/fixtures/runtime-enums-0.47.05-r8.json`. Do not trust v50
workshop lists: the v50 wiki pages in the local index describe the
mouse-driven v50 interface and v50 building behavior, and several
details differ. The 0.47.05 list:

| Building | Enum | Kind | Needs to build | Needs to run |
| --- | --- | --- | --- | --- |
| Kiln | `Kiln` | Furnace | Fire-safe material, non-economic | 1 fuel per job |
| Magma kiln | `MagmaKiln` | Furnace | Magma-safe material, magma | No fuel for heat |
| Wood furnace | `WoodFurnace` | Furnace | Fire-safe material | 1 log per job, no fuel |
| Ashery | `Ashery` | Workshop | 1 block, 1 barrel, 1 bucket | Ash or lye, potash maker or lye maker labor |
| Glass furnace | `GlassFurnace` | Furnace | Fire-safe material | 1 fuel per job, plus pearlash for clear and crystal glass. Glass products are GLASSMAKING, not this doc. |

Two traps in that table, both verified against the enum fixture and
the raws:

- The kiln is a **furnace** (`furnace_types`), not a workshop. The
  harness's build action today only knows the workshop enum at all
  (section 15), so a kiln build fails the same way a smelter build
  does until the build action learns the furnace lookup. The trap
  work and the metalworking plan already queued that
  generalization; ceramics rides on it, it does not re-justify it.
- The ashery is a **workshop** (`workshop_types`), and it is not a
  ceramics building at all: it belongs to the wood chain
  (WOODWORKING.md section 2.5), which owns ash, lye, and potash
  production. This doc owns only what the kiln does with potash
  (pearlash) and with quicklime (nothing: quicklime goes back to
  the ashery for milk of lime). The boundary is drawn at the
  building, not at the material, so neither doc queues the other's
  jobs.

Size: the kiln is 3x3 in the game, by the same furnace pattern as
the smelter. UNVERIFIED against the live game on r8: the harness
has never built a kiln, so the footprint is a wiki-pattern claim
the phase 1 build must confirm by read-back, like every other
build.

### 1.2 The chain, end to end, in one example

One clay boulder, collected from a clay zone, plus 1 fuel at a kiln,
becomes 1 large earthenware pot. The pot plus 1 unit of ash (1/150
of an ash bar) plus 1 more fuel, glazed at the same kiln, becomes a
glazed large pot that holds booze. Total from soil to container: 1
clay boulder, 1 unit of ash, 2 fuel, one kiln, and two labors
(hauler, potter, then glazer). Every number in that sentence is
verified below. The harness's job is to keep that whole chain
visible as have/need counts, so the agent never queues a glaze job
for a pot that does not exist, or a firing job the fort cannot fuel.

## 2. The fort today

Verified against the last stored world state
(`~/.config/df-agent-harness/world.db`, snapshot tick 115166,
2026-11-27) and the harness code. The daemon and the game are DOWN
at the time of writing (VM replacement about 19:37 PT, recovery
running separately), so every live value in this section is
last-known, not current, and is marked UNVERIFIED until a fresh
collect re-reads it. Do NOT restart the daemon or the game to check
any of this; the phase 1 probes re-read it when the stack is back.

- 7 citizens. Buildings: Carpenters #7 and Still #8 only. No kiln,
  no wood furnace, no ashery, no glass furnace, no smelter.
- Stocks at tick 115166: drink 97, food 23, wood 117, stone 0. The
  rendered stocks carry no clay, no plaster, no pearlash, and no
  ceramic goods, and the `by_material` list covers only DRINK,
  FOOD, MEAT, FISH, PLANT, SEEDS, BAR, WOOD, CLOTH, THREAD
  (stocks.lua), so a clay boulder would be invisible to it in any
  case (section 15.3).
- No survey is stored in world.db. The clay state of the map is
  completely unknown: no clay tile has been found, and no clay
  tile has been looked for. The survey counts soil tiles per z-level
  (survey.lua) but never names the soil material, so even a survey
  run today could not say whether the fort has clay.
- The embark record does not check clay. `embark.py:106` lists
  ("Clay", "N/A"): the embark screen's clay indicator is not read,
  so the fort may have embarked on clay without any record saying
  so. Whether the map holds clay is UNVERIFIED until phase 1
  probes it.
- Wood is the one input the fort already has: 117 wood is enough to
  bootstrap charcoal for kiln fuel and ash for glazing, and the
  carpenter exists to make the barrels, bins, buckets, and bags the
  chain needs (bags for plaster and quicklime, buckets for lye and
  milk of lime).

The consequence is blunt: the first ceramics milestone is not a
pot. It is a survey that says whether the map holds clay, fire
clay, kaolinite, and gypsum stone, and a fuel stock that says the
fort can fire what it collects. A kiln built before those answers
exist is a 3x3 furnace with nothing to burn and nothing to fire.

## 3. Clay: the soil that never runs out

### 3.1 What clay is, and where it lives

Clay is soil, not stone. Five soil types are classified as clay in
0.47.05 and can be gathered for ceramics: clay, clay loam, sandy
clay, silty clay, and fire clay (Clay page). Two more sound like
clay and are not: sandy clay loam and silty clay loam cannot be
used for ceramics despite their names. The 0.47.05 raws confirm
the split: clay, silty clay, sandy clay, and clay loam in
`inorganic_stone_soil.txt` each carry
`[MATERIAL_REACTION_PRODUCT:FIRED_MAT:INORGANIC:CERAMIC_EARTHENWARE]`,
fire clay carries
`[MATERIAL_REACTION_PRODUCT:FIRED_MAT:INORGANIC:CERAMIC_STONEWARE]`,
and sandy clay loam and silty clay loam carry no FIRED_MAT product
at all. The harness must check the FIRED_MAT token, not the name,
or it will send haulers to dig loam that can never fire.

Clay lives in soil layers, at or near the surface. Aquifers are
never present in clay layers (Clay page). Fire clay is a rare soil
type: the fort either has it or it does not, and the survey has to
say which. Kaolinite is not soil at all (section 4.3).

### 3.2 Collecting clay

Collection needs three things, all verified against the wiki and
the enum fixture:

1. **A clay collection zone.** An activity zone designated over a
   clay-bearing tile. Clay can be collected from adjacent clay
   walls, even diagonally, so the zone does not have to cover the
   whole deposit (Clay page). The harness already has a
   `create_zone` action with a "clay" kind, verified live 2026-11-26
   (actions.py:1891, ZONE_KINDS), so zone placement is a solved
   problem, not a research problem. What is NOT solved is finding
   the clay tile to put the zone on (section 3.4).
2. **A kiln with a Collect Clay order.** The order is issued at a
   kiln (or magma kiln). In the game it behaves like a workshop
   order: the collecting dwarf goes to the zone, digs out a clay
   boulder, and hauls it to a stockpile. The job type is
   `CollectClay` in the live runtime enum fixture, a hardcoded job,
   not a reaction: no COLLECT_CLAY reaction exists in any reaction
   raw, exactly like MakeCharcoal and MakeAsh. How the harness
   queues it is section 15.2.
3. **A dwarf with item hauling.** Collecting clay needs the
   HAUL_ITEM labor, not a craft labor. Any dwarf with hauling
   enabled can collect clay, and the more haulers, the faster the
   supply (Ceramic industry page). The collection zone should sit
   close to the kiln: the wiki's advice is to put the zone right
   on top of the operating kiln with no ill effects, which cuts
   the hauling to almost nothing.

Collected clay appears as a boulder, like a stone boulder, and
needs no container for storage or transport (Ceramic industry
page). It is stockpiled under Stone, one boulder per tile, so a
clay stockpile wants to be large and close to the kiln
(Ceramic industry page). Clay boulders can also be used as a
building material, but they cannot be carved into finished goods,
polished, fired from catapults, or loaded into stone-fall traps
(Clay page). The harness must never count clay boulders as mason
stone: they are kiln feed, and the stone count that matters for
masonry excludes them (section 15.3).

### 3.3 Infinite, with two catches

As long as at least one tile of clay is available on the map, clay
can be harvested infinitely (Ceramic industry page). One tile never
runs dry. That is what makes ceramics the fort's only infinite
trade-good industry: stone crafts run out when the stone runs out,
clay crafts do not. But two catches limit the harvest in practice,
and the harness must handle both:

- **Grass, saplings, and shrubs grow on clay soil.** While a plant
  grows on a clay tile, the clay under it is temporarily
  unavailable for collection, and a Collect Clay job in progress
  cancels with "Clay vanished"; a new job cancels with "Need
  valid, active clay collection zone" (Clay page). The fix the
  wiki names is a dirt road over the grass, or a floor grate over
  the clay floor, after removing the growth first. The harness
  must treat a run of Collect Clay cancellations as a blocked
  zone, not as a missing zone, and say which: a zone that keeps
  cancelling needs its grass cleared, not another zone. Whether
  the harness can read the cancellation reason from the live game
  on r8 is UNVERIFIED (section 19).
- **Collection is slow, and the potter outruns it.** A skilled
  potter fires faster than haulers collect, so a fort that fires
  on repeat sees job cancellations when the clay stockpile empties
  (Ceramic industry page). The wiki's answer is redundant
  collection orders (nine, on the kiln) and several haulers per
  kiln. The harness's answer is a clay floor: keep a minimum clay
  stock on hand before firing on repeat, and queue collection
  first when the stock falls below it. The exact floor is a phase
  3 decision; the rule is that the floor exists and the snapshot
  shows clay against it.

### 3.4 Finding clay: what the survey can and cannot tell the agent

The harness already has a survey (`survey.py`, `lua/survey.lua`):
one full block scan, about 25 seconds wall time, cached, with
soil counted per z-level. But it has a hard limit the doc must not
hide: **the survey counts soil tiles, it never names the soil
material**. A z-level with 400 soil tiles could be all clay, all
loam, or a mix, and the survey cannot say which. The embark
screen shows "Clay" or "Shallow clay" when the site has clay, but
the harness does not read the embark screen, and it cannot say
which clay type (fire clay included) the site holds (Ceramic
industry page).

That shapes the whole clay workflow:

1. Run the survey. It says where soil is and how deep it runs, but
   not whether any of it is clay. Soil depth is still useful: a
   map with no soil layer at all (mountain, glacier) has no clay
   to collect, and the survey proves that in one run.
2. Probe the soil tiles for their material. No harness read does
   this today. The probe is a phase 1 build: a Lua read over the
   surveyed soil tiles reporting each tile's soil material
   (clay, clay loam, sandy clay, silty clay, fire clay, or other),
   or a targeted DFHack query of the same. Until that probe
   exists, clay presence is UNVERIFIED on every map, including
   this fort's.
3. Put the clay zone on a confirmed clay tile, close to the kiln
   site, and queue Collect Clay. The first collected boulder is
   the confirmation: its material names the clay type, and the
   survey record gets its identity in the store.
4. If the map has no clay at all, ceramics does not start from
   soil. The fallbacks are trade (request clay or kaolinite from
   the liaison, buy clay goods), or a created clay tile: when an
   underground plant grows on a muddy stone floor tile and is
   trampled, gathered, cut down, or removed by building a dirt
   road on it, the tile turns into a biome-appropriate soil, which
   on a soil-less biome is random and might be clay (Clay page).
   That route is slow, uncertain, and out of scope for the
   phases here; the doc records it and does not plan on it.

## 4. The three wares

Ceramic goods are divided into three categories (wares) by raw
material. The same six products can be made from any ware (section
7), but the wares differ in value, weight, waterproofing, and
supply, and the harness must never treat them as interchangeable.

| Ware | Raw material | Source | Value | Waterproof | Density |
| --- | --- | --- | --- | --- | --- |
| Earthenware | Clay, clay loam, sandy clay, silty clay | Collected, infinite | 3 | No, needs glazing | 1360 |
| Stoneware | Fire clay | Collected, infinite but rare soil | 4 | Yes | 2000 |
| Porcelain | Kaolinite | Mined, finite clusters | 10 | Yes | 2403 |

Values and densities are from the 0.47.05 raws
(`inorganic_other.txt`: CERAMIC_EARTHENWARE value 3, density 1360;
CERAMIC_STONEWARE value 4, density 2000; CERAMIC_PORCELAIN value
10, density 2403). The wiki agrees on all three values (Ceramic
industry page). Earthenware at value 3 equals the highest-value
stone, obsidian; porcelain at value 10 equals silver.

### 4.1 Earthenware

The default ware: generic clay is the most abundant and available
(Ceramic industry page). Earthenware is the lightest of the three
wares, much lighter than almost every stone and all three types of
glass (Ceramic industry page), which matters for large pots: a pot
full of booze gets hauled all over the fort, and a lighter pot is
a faster haul. Earthenware is also the only ware that needs
glazing before its containers hold liquid (section 5). That extra
step costs ash and fuel, so the earthenware decision is always a
trade: light and infinite against an extra firing per container.
Wood is lighter still, and wooden pots need no glaze, so a fort
with wood to spare and no ash to spare should think twice before
firing earthenware pots at all. The harness must show the glaze
cost beside the pot count, never the pot count alone.

### 4.2 Stoneware

Fire clay only, collected exactly like generic clay (Ceramic
industry page). Stoneware is waterproof without glazing, which
removes the whole ash-and-second-firing cost from the container
chain. Its value (4) beats earthenware (3) by one, and its density
(2000) is heavier. Fire clay is rare soil, so a fort with fire clay
has a strictly better container chain than a fort without it, and
the survey must name it when it finds it: "fire clay present" is
a find worth a briefing (section 16.4), not a footnote. Stoneware
statues and crafts are also the better trade good per firing when
both clays are on hand, for one extra value per item at the same
fuel cost.

### 4.3 Porcelain

Kaolinite only, mined, not collected. The raws confirm it:
kaolinite in `inorganic_stone_mineral.txt` is a sedimentary stone
in clusters (`[ENVIRONMENT:SEDIMENTARY:CLUSTER:100]`) carrying
`[MATERIAL_REACTION_PRODUCT:FIRED_MAT:INORGANIC:CERAMIC_PORCELAIN]`.
It is magma-safe as a stone (melting point 13150), but porcelain
blocks are not magma-safe (Ceramic industry page), and neither is
any other ceramic block: all ceramic bricks are fire-safe but not
magma-safe, even porcelain ones. Porcelain is the wealth ware:
value 10, naturally waterproof, and the only ware whose supply is
finite. A fort that finds a kaolinite cluster can generate wealth
fast (Ceramic industry page), and can also burn through it fast:
every porcelain statue is a boulder of a finite cluster that never
comes back. The harness must count kaolinite boulders against the
porcelain plan the way it counts ore against the steel plan, and
must never let a repeat porcelain order drain the cluster on
statues while the fort still wants porcelain pots. Kaolinite can
also be requested from the liaison or bought (Ceramic industry
page), and a mason can turn one kaolinite boulder into four
low-value, magma-safe kaolinite blocks instead, if kaolinite is
set non-economic (Ceramic industry page). That is a stoneworking
decision, not a ceramics one, and the ceramics plan never spends
kaolinite on blocks without the agent saying so.

### 4.4 Which ware the harness fires

The kiln menu cannot pick a ware directly: the potter fires
whatever clay boulder the game hands the job, and the manager
cannot fine-tune which material a kiln uses either (Ceramic
industry page). Control comes from stockpile links and isolation,
not from the order: one kiln per ware type, each linked to a
dedicated stockpile holding only that ware's raw material, plus a
fuel stockpile link. The harness has no stockpile-link write today
(STONEWORKING.md section 4.4: links do not exist yet), so ware
control is UNVERIFIED as a harness capability until links land.
Until then the rule is simpler: if the fort holds two clay types,
fire from the one the agent names by isolating it (forbid the
other, or keep it in a stockpile the kiln cannot reach), and say
so in the snapshot. Firing blind with mixed clay on hand and
calling the result a plan is not acceptable: the harness must name
the ware it expects before it queues the job, and verify the fired
item's material on read-back.

## 5. Glazing

Glazing re-fires a finished item with a glaze medium, giving it a
glassy, non-porous coating that makes it waterproof and raises its
value (Ceramic industry page). It is the step that makes
earthenware containers work, and the step that most often gets
planned wrong, because the medium, the fuel, and the eligible
items each have their own trap.

### 5.1 The two media, verified against the 0.47.05 raws

| Medium | Source | Per glaze job | Value added | Raw proof |
| --- | --- | --- | --- | --- |
| Ash | 1 log at a wood furnace (MakeAsh) | 1 unit of ash (1/150 of a bar) | +50 | Wiki Ceramic industry page; ash is a hardcoded material, its GLAZE_MAT product is not in the raws |
| Cassiterite | Mined tin ore | 1 boulder | +100 | `inorganic_stone_mineral.txt`: cassiterite carries `[MATERIAL_REACTION_PRODUCT:GLAZE_MAT:INORGANIC:TIN_GLAZE]`; TIN_GLAZE value 10 in `inorganic_other.txt` |

The +50 and +100 figures are wiki claims (Ceramic industry page),
not raw values: the raws give the glaze materials values of 5
(ASH_GLAZE) and 10 (TIN_GLAZE), and the item-value addition is game
behavior. UNVERIFIED against the live game on r8: phase 3 verifies
the added value by read-back on a glazed item. A full ash bar is
required to start an ash glaze job, even though the job consumes
only 1/150 of the bar (Ceramic industry page). Tin bars cannot be
used to make tin glazes: only the raw cassiterite boulder works
(Ceramic industry page). The harness must never smelt the fort's
last cassiterite into tin bars while the glaze plan still needs
it, and must say which medium a glaze job will use before it
queues the job.

### 5.2 What can be glazed

Four glaze reactions exist in `reaction_other.txt`, all with
`[SKILL:GLAZING]`, all burning 1 fuel, all taking one glaze-medium
reagent (`ANY_RAW_MATERIAL` with
`HAS_MATERIAL_REACTION_PRODUCT:GLAZE_MAT`) and one item reagent
with `[REACTION_CLASS:CAN_GLAZE]`, `[EMPTY]`, `[NOT_IMPROVED]`,
`[PRESERVE_REAGENT]`:

- GLAZE_JUG: a jug (TOOL ITEM_TOOL_JUG).
- GLAZE_STATUE: a statue.
- GLAZE_LARGE_POT: a large pot (TOOL ITEM_TOOL_LARGE_POT).
- GLAZE_CRAFT: any craft (ANY_CRAFT).

The item must be empty and not already improved. The stone
template in `material_template_default.txt` carries
`[REACTION_CLASS:CAN_GLAZE]`, so stone jugs, statues, large pots,
and crafts of those four kinds can be glazed too, not only ceramic
ones. Glazes are not products in themselves: no glaze item is made
and then applied; the glaze is an item improvement applied by the
re-firing (Ceramic industry page). The harness tracks glaze jobs
as improvements to named items, never as a glaze stock. Bricks,
hives, and instruments cannot be glazed: there is no reaction for
them, and a glaze plan that names one is a bug.

### 5.3 When glazing is worth it

Glazing is mandatory for earthenware liquid containers and
optional everywhere else. The decision the harness puts in front
of the agent, per item, is: the item's value without glaze, the
glaze medium on hand and its competing use, and the fuel. Ash
glaze competes with the ashery chain (ash to lye or potash) and
with fuel: ash and charcoal both come from logs, so a fort that
glazes heavily and burns charcoal heavily is spending the same
wood twice (Ceramic industry page). Cassiterite glaze competes
with the metal chain: every cassiterite boulder glazed is a
boulder not smelted into tin, and tin is bronze (METALWORKING.md
section 5.3). A fort with no tin and no bronze plan can glaze
freely; a fort short on bronze cannot. The harness never queues a
tin glaze while the bronze have/need is unmet without saying so.
Stoneware and porcelain items gain value from glazing but do not
need it to hold liquid, so glazing them is a trade-value decision,
not a function decision, and it is the agent's call, never the
harness's default.

## 6. The kiln and the magma kiln

### 6.1 Building a kiln

A kiln is built from any fire-safe material, non-economic
(Kiln page). Construction labor is Masonry for stone, or
Blacksmithing, Weaponsmithing, Armoring, or Metalcrafting for
metal (Kiln page). The build goes through the same furnace path
as the smelter: a `df.furnace_type` lookup for `Kiln`, a fire-safe
material check, and a read-back of the built furnace. None of
that exists in the harness today (section 15.1), and the kiln
build waits on the same generalization the trap work and the
metalworking plan already queued. The kiln's overall value helps
decide how strong a good thought a passing dwarf gets from
admiring it (Kiln page), which is decoration, not a reason to
build a kiln from gold. A kiln built from the nearest fire-safe
stone is the right kiln.

A magma kiln needs magma-safe material and magma, and burns no
fuel for heat. The 4/7 magma depth rule the metalworking plan
states for magma smelters and forges is expected to apply to the
magma kiln too, by the same furnace pattern. UNVERIFIED for the
kiln specifically on r8: the harness has never built any magma
building, and the kiln must not be the first one trusted on an
assumption. Magma kilns belong to the late phases with the rest of
the magma work (section 18, phase 9), not to the first kiln build.

### 6.2 One fuel per job

Every job at a standard kiln consumes one unit of fuel (Kiln page;
Ceramic industry page). Every kiln reaction in `reaction_other.txt`
carries a `[FUEL]` tag, including the glaze reactions and the
CollectClay-adjacent firing reactions, and the three operator
reactions (pearlash, plaster, quicklime) carry it too. There is no
fuel-free kiln job at a standard kiln. That single fact is what
makes the kiln a fuel competitor (section 11): a fort firing
twenty pots has spent twenty fuel, the same twenty a smelter
would have spent on twenty ore, and the fuel ledger must show
both draws on the same number.

### 6.3 Clutter and the single-kiln trap

A kiln used for everything clutters like any workshop, and worse:
it is one building serving three labors (potter, glazer, furnace
operator) and a collection order. The wiki's advanced advice is
to run dedicated kilns: a collection kiln on repeat Collect Clay,
a firing kiln, a glaze kiln, each linked to its own stockpile
(Ceramic industry page). The harness cannot do the linking yet
(section 4.4), so the early plan is one kiln with named, ordered
work, not three kilns with no links. The one-kiln rule: collection
first until the clay floor is met, then firing, then glazing, then
operator jobs (plaster, pearlash, quicklime) in the priority the
agent sets. A kiln on repeat firing with an empty clay stockpile
is a kiln producing cancellations, and the snapshot must say the
clay count, not just that the kiln is busy.

## 7. What the kiln makes: the full reaction table

Every kiln reaction in 0.47.05 lives in one file,
`third_party/df_47_05/raw/objects/reaction_other.txt`. There are
13 of them. The table below is copied from that file, not from
the wiki; the wiki agrees with all of them. Each reaction burns 1
fuel for heat at a standard kiln (0 at a magma kiln), on top of
the ingredients listed. Amounts are 1 boulder unless stated.

| Reaction | Code | Skill | Ingredients | Product |
| --- | --- | --- | --- | --- |
| Make clay jug | MAKE_CLAY_JUG | Potter | 1 clay boulder (FIRED_MAT) | 1 jug |
| Make clay bricks | MAKE_CLAY_BRICKS | Potter | 1 clay boulder (FIRED_MAT) | 1 block (brick) |
| Make clay statue | MAKE_CLAY_STATUE | Potter | 1 clay boulder (FIRED_MAT) | 1 statue |
| Make large clay pot | MAKE_LARGE_CLAY_POT | Potter | 1 clay boulder (FIRED_MAT) | 1 large pot |
| Make clay crafts | MAKE_CLAY_CRAFTS | Potter | 1 clay boulder (FIRED_MAT) | 1 craft |
| Make clay hive | MAKE_CLAY_HIVE | Potter | 1 clay boulder (FIRED_MAT) | 1 hive |
| Glaze jug | GLAZE_JUG | Glazer | 1 glaze medium + 1 empty, unimproved jug | Glazed jug |
| Glaze statue | GLAZE_STATUE | Glazer | 1 glaze medium + 1 empty, unimproved statue | Glazed statue |
| Glaze large pot | GLAZE_LARGE_POT | Glazer | 1 glaze medium + 1 empty, unimproved large pot | Glazed large pot |
| Glaze craft | GLAZE_CRAFT | Glazer | 1 glaze medium + 1 empty, unimproved craft | Glazed craft |
| Make pearlash | MAKE_PEARLASH | Furnace operator | 1 potash bar (150 units) | 1 pearlash bar |
| Make plaster powder | MAKE_PLASTER_POWDER | Furnace operator | 1 gypsum-class boulder + 1 empty bag | 1 bag of plaster powder |
| Make quicklime | MAKE_QUICKLIME | Furnace operator | 1 calcium-carbonate boulder + 1 empty bag | 1 bag of quicklime |

Three notes on that table, all verified against the file:

- **The clay reagent is any boulder with FIRED_MAT.** The
  reaction does not name clay: it takes any boulder whose material
  defines a FIRED_MAT reaction product, and the product takes that
  material. That is why the same six reactions make earthenware
  from clay, stoneware from fire clay, and porcelain from
  kaolinite, with no separate recipes. It is also why ware control
  has to happen before the job, by controlling which boulders the
  kiln can reach (section 4.4): the reaction itself will happily
  fire the wrong ware.
- **The bag is preserved.** Both powder reactions take a bag with
  `[PRESERVE_REAGENT]` and put the powder into it
  (`[PRODUCT_TO_CONTAINER:B]`). The bag is not consumed; the
  powder lives in it. A fort with no empty bags cannot make
  plaster or quicklime at any fuel level, and the snapshot must
  show the empty-bag count beside the plaster count.
- **No instrument reaction exists.** The v50 Kiln page lists
  instruments and instrument pieces as kiln goods (marked
  v0.42.01), but no instrument reaction appears in
  `reaction_other.txt`, and no other reaction raw names the kiln.
  Whether kiln-made instruments exist in 0.47.05 at all is
  UNVERIFIED (section 19). The harness must never promise a
  ceramic instrument until a live probe finds the route.

### 7.1 What each product is for

- **Jugs and large pots.** The containers. A jug is a small
  container, like a bag or waterskin; a large pot is treated like
  a barrel (Clay page). Large pots are the product with a job in
  the fort: glazed earthenware, stoneware, or porcelain large pots
  store booze and other liquids, and their light weight (section
  4.1) is the reason to prefer them over stone pots. Jugs hold
  small quantities and are mostly trade goods.
- **Bricks (blocks).** Ceramic blocks, named "brick" in the game
  (BLOCK_NAME:brick:bricks in the raws). Fire-safe, not
  magma-safe, 3 to 10 times as valuable as common stone blocks
  (Ceramic industry page), producible in infinite quantities from
  clay. Their use is room value: roads, bridges, and rooms in soil
  layers. They are not a survival need, and a fort short on fuel
  must never fire bricks while its pots are unglazed.
- **Statues.** The wealth and room-value product. Porcelain
  statues are the high-value room piece when gold, silver, and
  platinum are short (Ceramic industry page); earthenware and
  stoneware statues in quantity do the same work more slowly.
  Statues block passage on their tile, like all statues, so the
  placement plan puts them where dwarves do not walk.
- **Crafts.** The trade good. The kiln is the only place ceramic
  crafts are made, and ceramic crafts are the infinite trade good
  (Ceramic industry page). The kiln cannot make ceramic goblets
  or toys (Ceramic industry page). A craft job is the right job
  when the potter needs skill and the fort needs trade value and
  nothing else is queued.
- **Hives.** Clay hives for beekeeping. The beekeeping plan owns
  what hives are for (ANIMAL_HUSBANDRY.md); the kiln owns making
  them. Whether the beekeeping plan currently needs hives, and
  how many, is UNVERIFIED against that doc at the time of writing:
  phase 1 checks it before any hive job is queued.
- **Pearlash, plaster, quicklime.** Sections 8, 9, 10. They are
  not wares; they are the operator's jobs, and they are scheduled
  by the industries that need them, not by the potter.

## 8. Plaster and the hospital

Gypsum plaster is the kiln product with a deadline, because broken
bones do not wait for a trade good.

### 8.1 Making plaster

MAKE_PLASTER_POWDER: 1 boulder of a gypsum-class stone plus 1
empty bag, furnace operator labor, 1 fuel, gives 1 bag of plaster
powder (`reaction_other.txt`). The gypsum-class stones, verified
in the 0.47.05 raws by `[REACTION_CLASS:GYPSUM]`, are gypsum,
alabaster, selenite, and satinspar (`inorganic_stone_mineral.txt`).
Anhydrite is NOT gypsum-class and cannot be used (Gypsum plaster
page), even though its name suggests otherwise. Alabaster,
selenite, and satinspar all occur as small clusters inside gypsum
(`[ENVIRONMENT_SPEC:GYPSUM:CLUSTER_SMALL:100]`), so a fort with a
gypsum cluster has all four; a fort with none has no plaster stone
of its own. Gypsum itself is a sedimentary cluster stone. The
survey must report gypsum stone the way it reports ore: the
hospital plan depends on it, and the fort cannot improvise plaster
from another stone.

### 8.2 What plaster is for

Plaster powder is used to make orthopedic casts, which a bone
doctor uses to immobilize broken bones, serving the same role as
splints (Gypsum plaster page). Bags of plaster powder are
automatically stored in chests in hospital zones, provided there
is room (Gypsum plaster page). There is no stockpile control for
plaster: no stockpile setting governs it, because no object is
ever made OF plaster; plaster bags are stockpiled as Bags under
Furniture (Gypsum plaster page). That has two consequences for
the harness. First, the plaster count is a bag count, read from
the bags in play, not from a stockpile count; the stocks collect
does not report it today (section 15.3). Second, the hospital
must have a chest in its zone or the plaster has nowhere to go,
and the hospital plan owns that chest. The plaster floor is a
hospital decision: how many bags the hospital holds before the
kiln stops making more. The ceramics plan proposes a floor of
enough bags for the fort's current injuries plus a small reserve,
and the agent sets it; the rule is that the floor exists, because
plaster made without a hospital chest is a bag on the kiln floor.

### 8.3 Plaster priority

Plaster outranks every other kiln job except clay collection when
the hospital is short. The ordering rule: if the hospital holds
fewer plaster bags than its floor and gypsum stone and empty bags
and fuel are all on hand, the next kiln job is plaster. If any
input is missing, the snapshot names the missing input ("plaster
0 bags, no gypsum stone on hand" beats "kiln idle"). Plaster is
also the one kiln product the fort cannot buy its way out of
easily: caravans sell plaster powder rarely, and a fort with a
broken bone and no gypsum stone is a fort waiting on a splint.
The harness never lets the plaster count hit zero without an
attention entry while a dwarf has a fracture, and never fires a
statue while the hospital floor is unmet.

## 9. Pearlash and the glass crossover

### 9.1 Making pearlash

MAKE_PEARLASH: 1 bar of potash (150 units) plus 1 fuel, furnace
operator labor, gives 1 bar of pearlash (`reaction_other.txt`,
`[SKILL:SMELT]`). Pearlash is a bar, stored in bar stockpiles,
with material value 4 and no quality level (Pearlash page). The
chain behind it is the longest in this doc, and it belongs to
WOODWORKING.md section 2.5, which owns it: 1 log at a wood furnace
becomes 1 bar of ash (MakeAsh), 1 bar of ash at an ashery becomes
1 bar of potash (MakePotashFromAsh) or 1 bucket of lye then 1 bar
of potash (MakePotashFromLye), and 1 bar of potash at a kiln
becomes 1 bar of pearlash. One log, one ash bar, one potash bar,
one pearlash bar, one fuel at the kiln, three buildings, three
labors. The ceramics plan never re-derives that chain; it takes
the potash count as an input and reports the pearlash count as an
output. If WOODWORKING.md's chain and this doc ever disagree on a
number, the raws decide, and the disagreement is flagged under
section 21, not silently resolved.

### 9.2 What pearlash is for

Pearlash has one use: clear glass and crystal glass at a glass
furnace or magma glass furnace (Pearlash page). Green glass needs
only sand; clear glass needs sand plus pearlash; crystal glass
needs rock crystal plus pearlash. All glass products, and the
glass furnace itself, belong to GLASSMAKING.md, which owns
counting pearlash bars in stock and refusing a clear or crystal
job when pearlash is short, naming the kiln as the fix. The pearlash plan is small and exact:
make pearlash only when the fort has potash to spare after
fertilizer (FARMING_PLAN.md section 8 owns the fertilizer half)
and fuel to spare after the metal chain and the plaster floor, and
hold it as bars for the glass industry. Pearlash is not a trade good
to chase: elves refuse wood derivatives including pearlash, ash,
and potash (TRADING.md section 4), so pearlash sold to elves is
a refused offer, not a sale. The harness never queues pearlash
as a trade good, and never spends the last potash bar on pearlash
while a farm plot waits for fertilizer without saying so.

### 9.3 The pearlash scheduling rule

Pearlash is the lowest-priority operator job at the kiln. The
order is plaster first (hospital), quicklime second (only when
the parchment chain asks for it, section 10), pearlash third
(only when potash and fuel are surplus). A kiln that makes
pearlash while the hospital floor is unmet has its priorities
backwards, and the snapshot must show it that way: plaster 0
beside pearlash 5 is a finding, not a stock list.

## 10. Quicklime, milk of lime, and parchment

### 10.1 Making quicklime

MAKE_QUICKLIME: 1 boulder of a calcium-carbonate stone plus 1
empty bag, furnace operator labor, 1 fuel, gives 1 bag of
quicklime (`reaction_other.txt`). The calcium-carbonate stones,
verified in the 0.47.05 raws by
`[REACTION_CLASS:CALCIUM_CARBONATE]`, are calcite, chalk,
limestone, and marble (`inorganic_stone_layer.txt` for limestone,
chalk, and marble; `inorganic_stone_mineral.txt` for calcite).
These are also the flux stones (METALWORKING.md section 5.3),
which is the one real conflict in this doc's raw materials: every
limestone boulder burned into quicklime is a boulder not
available as steel flux. The harness must show the flux count
beside the quicklime count when both plans want the same stone,
and must never queue quicklime from the fort's last flux stone
while the steel plan is unmet without the agent saying so.

### 10.2 What quicklime is for

On its own, a bag of quicklime has no practical use (Quicklime
page). It is processed at an ashery into milk of lime
(MAKE_MILK_OF_LIME in `reaction_other.txt`: 150 units of
quicklime powder plus a bucket, lye making labor, gives 1 bucket
of milk of lime), and milk of lime plus a raw hide at a tanner
makes parchment (MAKE_PARCHMENT in `reaction_other.txt`), which
becomes scrolls, quires, and books at a craftsdwarf's workshop
(MAKE_SCROLL, MAKE_QUIRE, MAKE_SHEET_FROM_PLANT, PRESS_PLANT_PAPER,
BIND_BOOK in the same file). Quicklime is therefore a library
input, three buildings downstream, and the kiln's part in it is
one bag at a time. The ashery step is named in SOAP_MAKING.md,
which documents the ashery jobs including milk of lime (skill
LYE_MAKING) and states plainly that milk of lime is for parchment,
not soap. The parchment sheet route itself is covered by
MILLING_AND_PRESSING.md, which assigns parchment to CLOTHING.md's
leather chain. The ceramics plan owns only the kiln step: quicklime
on hand, by bag, against the parchment plan's ask.

### 10.3 Storage

Quicklime is stored under Bags in furniture stockpiles, which
makes it hard to separate from empty bags (Quicklime page). The
wiki's workaround is a kiln dedicated to quicklime with a
furniture stockpile taking only from that kiln, feeding the milk
of lime ashery. The harness has no stockpile-link write today
(section 4.4), so the workaround is UNVERIFIED as a harness
capability. Until links land, quicklime bags mix with empty bags
in the furniture stockpile, and the count comes from the bag
contents read, not from the stockpile. A quicklime count the
harness cannot separate from the empty-bag count is reported as
a combined number with the ambiguity named, never as a clean
number the agent cannot trust.

## 11. Fuel: the kiln as a fuel competitor

This section is the boundary with METALWORKING.md, which owns
the fuel economy. This doc does not re-derive it; it states what
the kiln draws from it, and flags the one point where the two
docs must agree.

### 11.1 What the kiln burns

One unit of fuel per job at a standard kiln (section 6.2), zero
for heat at a magma kiln. Fuel is charcoal (1 log at a wood
furnace, MakeCharcoal) or coke (9 per bituminous coal boulder,
5 per lignite boulder, each minus 1 fuel for heat at a
conventional smelter), per METALWORKING.md section 4. The kiln
competes with the smelter and the forge for the same fuel pile,
and with the wood furnace for the same wood: ash for glazing and
charcoal for fuel both come from logs (section 5.3). A fort that
fires twenty pots, glazes ten of them, and smelts ten ore has
spent forty fuel and the ash from ten logs, and the fuel ledger
must show all three draws on the same numbers. The harness never
reports kiln fuel separately from smelter fuel: there is one fuel
number, one floor, and every consumer draws on it.

### 11.2 The fuel floor, applied to the kiln

METALWORKING.md section 4.3 sets the rule: never burn the last
fuel without a way to make more, and keep a fuel floor high
enough to smelt the ore already mined and forge the bars already
smelted. The kiln obeys the same floor, with its own addition:
the kiln never draws fuel below the floor the metal chain needs,
and the kiln's own reserve is counted inside the floor, not
beside it. In practice: the fuel floor is metal need plus kiln
need (plaster floor plus the next firing batch), and a kiln job
that would breach it is refused with the shortfall named, the
same way a smelt is refused. A kiln job is never more urgent than
a smelt the military waits on, except plaster: a hospital short
on plaster outranks a smelt, because a broken bone is a dwarf
out of work and a smelt is a bar in a pile. That exception is
named here so the planner can implement it without guessing, and
it is the only exception.

### 11.3 The numbers, per job

| Kiln job | Fuel | Other inputs | Output |
| --- | --- | --- | --- |
| Fire 1 clay item | 1 | 1 clay boulder | 1 item |
| Glaze 1 item | 1 | 1 glaze medium unit, 1 finished item | 1 glazed item |
| Make 1 pearlash bar | 1 | 1 potash bar | 1 pearlash bar |
| Make 1 plaster bag | 1 | 1 gypsum boulder, 1 empty bag | 1 plaster bag |
| Make 1 quicklime bag | 1 | 1 calcium-carbonate boulder, 1 empty bag | 1 quicklime bag |
| Collect 1 clay boulder | 0 | 1 clay zone, 1 hauler | 1 clay boulder |

Collect Clay burns no fuel: it is a hauling job, not a firing
job. Everything else at the kiln is exactly 1 fuel. A firing
batch of 10 pots is 10 fuel; glazing all 10 is 10 more. The
harness's have/need check for any kiln batch names the fuel
twice: the fuel the batch burns and the fuel left after it, against
the floor. A batch that fits the fuel but breaches the floor is
refused, and the refusal names the floor.

## 12. Layout and stockpiles

Layout is scored placement (docs/SITE_SELECTION.md), with
ceramics-specific factors on top of the shared threat, cover, and
traffic factors:

- **The triangle, kiln version.** Kiln, wood furnace, and clay
  zone belong together, within a few tiles of each other, inside,
  near the fort entrance but off the main corridor. The potter,
  the glazer, and the hauler all walk between them on every job,
  and the wiki's advice is explicit: the collection zone can sit
  right on top of the operating kiln (section 3.2). The ashery
  sits nearby too, since ash, potash, and pearlash all walk the
  same short route (Ceramic industry page: keep the ceramics and
  glass industries close, since potash and pearlash cross between
  them).
- **Feeder stockpiles.** A clay stockpile by the kiln (Stone
  category, one boulder per tile, large: clay never runs out, so
  the pile is sized by firing rate, not by supply), a fuel
  stockpile (bars/blocks, bins allowed) by the kiln, an ash
  stockpile (bars, bins) by the kiln and the ashery, a kaolinite
  stockpile by the kiln when the fort mines kaolinite, and a
  gypsum-stone stockpile by the kiln. Feeders take from anywhere;
  bulk stores take from links only (Stockpiles section 4). The
  clay stockpile must never fill: a full clay pile leaves fresh
  clay at the collection site, and the harness says so by name
  when the pile fills.
- **The powder problem.** Plaster and quicklime bags cannot be
  separated by stockpile settings (sections 8.2, 10.3). Until
  stockpile links exist, the plan is: one furniture stockpile
  near the kiln for bags, and the hospital chest as the real
  plaster store. The harness never claims a stockpile count for
  plaster or quicklime it cannot separate from empty bags.
- **Fire safety.** The kiln is built from fire-safe material, and
  the build action must enforce it: a wooden kiln is not a kiln,
  it is a fire. The build action today takes whatever material
  the probe finds first (actions.py `build_workshop` takes the
  first accessible material in the spec list), with no fire-safe
  check anywhere. That is a gap the kiln build work closes, not a
  detail to leave to the model. UNVERIFIED: whether the game
  refuses a non-fire-safe material at placement time or lets the
  building stand and burn. The phase 1 build must probe it and
  record the answer. The same gap and the same probe are stated
  in METALWORKING.md section 8 for the smelter; the answer is
  one answer for all furnaces, and this doc takes it from there
  rather than re-probing it.
- **Magma safety.** A magma kiln needs magma-safe material, and
  the open tile over magma is a creature entry point: the v50 wiki
  text says the impassable tile was removed in v50, which means
  in 0.47.05 the magma kiln still has an impassable tile.
  UNVERIFIED on r8: the wiki says it was removed "as of v50",
  which implies it exists in 0.47.05, but the harness has never
  built a magma building to confirm it. Phase 9 verifies it live
  before any magma kiln is trusted as sealed. Same statement,
  same probe as METALWORKING.md section 8.
- **Ware separation.** One kiln per ware type when the fort holds
  more than one clay type (section 4.4), each with its own clay
  stockpile. Without links this is aspirational; with links it
  is the layout. The layout plan records which kiln serves which
  ware, so a potter firing porcelain at the earthenware kiln is
  a visible error, not a quiet one.

## 13. Labor and assignment

Ceramics needs four labors across at least two dwarves, and the
fort has 7 citizens, of whom the miner, the brewer, the carpenter,
and the planter are already spoken for. The assignment rules:

- **Potter (POTTERY).** One dwarf, part time at first. Firing is
  batch work: fire a stack of pots when clay is on hand, then go
  back to other work. Skill changes the item's quality and value,
  not whether the job runs, so any dwarf can start; the best
  potter is the one with nothing else critical to do. Neither the
  potter nor the glazer labor qualifies for strange moods
  (Ceramic industry page), so giving these dwarves experience in
  a moodable skill (for example weaponsmithing) is worth doing
  deliberately, not by accident.
- **Glazer (GLAZING).** One dwarf, part time, usually the same
  dwarf as the potter while the fort is small. Glazing is one
  item at a time and fast, with low resource cost (Ceramic
  industry page). A skilled glazer raises the glazed item's
  value, so the glazing labor goes to the best potter first.
- **Furnace operator (SMELT).** Shared with the metal chain. The
  operator makes pearlash, plaster, and quicklime at the kiln,
  and smelts ore and makes coke at the smelter. One operator
  serves both buildings while the fort is small; the operator
  becomes full time as soon as ore and clay both flow. The
  assignment must say which building the operator is on, because
  an operator at the smelter is not an operator at the kiln, and
  a plaster job queued while the operator smelts is a plaster job
  that never runs.
- **Hauler (HAUL_ITEM).** Several dwarves, not one. Clay
  collection is hauling, and the collection rate is the hauler
  count times the walk (section 3.3). Every citizen hauls by
  default unless the labor plan says otherwise; the ceramics plan
  asks only that hauling stays on for enough dwarves to keep the
  clay floor met, and that the snapshot names the hauler count
  when collection falls behind firing.
- **Wood burner (BURN_WOOD) and potash maker (POTASH_MAKING).**
  Not ceramics labors, but ceramics cannot run without them: the
  burner makes the ash and the charcoal, the potash maker makes
  the potash. Both belong to WOODWORKING.md; this doc names them
  as dependencies and never assigns them.

The labor plan (docs/LABOR.md) owns who holds which labor; this
doc owns which labors the industry needs and what happens when
one is missing. A missing labor is a named blocker ("no potter:
kiln idle", "no furnace operator: no plaster"), never a silent
idle workshop.

## 14. Trade value

Ceramics earns its keep as a trade good, and the trade plan
already knows it:

- **Ceramic crafts are the infinite trade good.** Clay never runs
  out, so a potter can make crafts forever, one clay boulder and
  one fuel per craft, at value 3 to 10 by ware plus quality plus
  glaze. Stone crafts are the trading plan's default because stone
  is free and unlimited (TRADING.md section 5); ceramic crafts
  beat stone crafts on value per job whenever clay is on hand,
  and the trading plan should rank them above stone crafts once
  the kiln runs. The exact ranking is a planner decision; the
  rule is that the ranking exists and the agent sees the numbers.
- **Glazed goods are the high-value trade good.** Ash glaze adds
  50 value, tin glaze adds 100 (section 5.1, wiki claims,
  UNVERIFIED live). A glazed earthenware statue is a small, light,
  high-value trade item, and glazing is fast. The glaze medium
  is the constraint, not the firing: ash is cheap, cassiterite is
  not.
- **Porcelain is the wealth good.** Value 10 per item before
  quality or glaze, equal to silver. Porcelain statues and crafts
  are the fort's best non-metal trade stock while kaolinite lasts,
  and the trading plan must never sell the last kaolinite boulder
  as stone while the porcelain plan still wants it. Kaolinite as
  a trade good itself is a stone sale; porcelain as a trade good
  is a craft sale, and the craft sale is worth more.
- **Elves accept ceramic.** Elves accept stone, metal, green
  glass, ceramic, all rough and cut gems (TRADING.md section 4),
  and refuse wood and animal products entirely, including wood
  derivatives (ash, potash, pearlash, charcoal, lye, tallow soap)
  and clear and crystal glass (TRADING.md section 4). Ceramic
  goods are therefore elf-safe trade stock, and pearlash is not:
  never offer pearlash, potash, or ash to elves. A glazed ceramic
  item is still ceramic; the glaze does not change its trade
  standing. Whether a tin-glazed item counts as elf-acceptable
  (tin is a metal, and the glaze is a metal ore) is UNVERIFIED:
  phase 4 tries one tin-glazed item on an elven caravan only if
  the agent asks, and records the answer.
- **What ceramics never sells.** Never sell the last empty bag
  while plaster or quicklime is unmade; never sell the clay
  stockpile's contents as stone; never sell a glazed large pot
  the fort still needs for booze storage. The never-sell list in
  TRADING.md owns these once the plan lands there; until then
  this section is the record.

## 15. What the harness has today

Verified against the repo 2026-11-27. Everything in this section
was read from the code, not assumed.

### 15.1 What exists and can be reused

- **Zone creation works, including clay zones.** `create_zone`
  (actions.py:1973, act_zone.lua) creates activity zones
  programmatically, and "clay" is in ZONE_KINDS (actions.py:1894),
  verified live on a clay zone 2026-11-26. The zone half of clay
  collection is done.
- **Job queueing works for reactions.** `queue_job` (actions.py
  JOB_SPECS, act_job.lua) queues CustomReaction jobs (job type
  211) by reaction code, which is exactly how the 13 kiln
  reactions run. The brew and carpenter jobs prove the mechanism.
  The kiln reactions only need JOB_SPECS entries naming their
  codes.
- **Labor toggle works.** `labor_toggle` (act_labor.lua) takes a
  `df.unit_labor` name, validates it against the live enum,
  writes it, and reads it back. The ceramics labors (POTTERY,
  GLAZING, SMELT, HAUL_ITEM, BURN_WOOD, POTASH_MAKING) are all in
  the live enum fixture, so assignment is a solved problem, not a
  research problem.
- **Manager orders exist.** `manager_order_create`
  (actions.py:934, act_order.lua) creates manager orders by job
  type and verifies them on re-read. The wiki notes that the
  manager order "make plaster powder" is the fallback when the
  kiln option is unavailable (Gypsum plaster page); whether the
  harness's manager route can order kiln reactions at all is
  UNVERIFIED (section 19), but the route exists to probe.
- **The planner knows ceramics is missing.** `planner.py` names
  the metal industry as deferred; ceramics is not named there at
  all. The deferral for ceramics is implicit, and phase 1 makes
  it explicit: the planner must name ceramics as deferred until
  the clay survey lands, the same way it names metalworking.
- **The ashery chain is already documented.** WOODWORKING.md
  section 2.5 owns ash, lye, and potash production and the kiln
  row for pearlash. The ceramics plan takes that chain as an
  input and does not rebuild it.

### 15.2 What is missing (verified gaps)

- **No furnace build.** WORKSHOP_CATALOG (actions.py:133) has four
  kinds: carpenter, mason, still, kitchen. No kiln, no smelter,
  no wood furnace, no glass furnace, no ashery. `act_build.lua`
  hardcodes its subtype lookup to `df.workshop_type`, so a kiln
  subtype would error as "unknown workshop subtype"
  (ADVANCED_MECHANICS.md section 4). The kiln needs a
  `df.furnace_type` lookup and a `type` of Furnace. This is the
  first build gap, shared with metalworking and the trap work,
  and the ceramics phases ride on it.
- **No fire-safe check.** Nothing in the build path checks that
  the chosen material is fire-safe. The first accessible stone is
  whatever the probe finds, and the fort's stone today is 0, so
  the first kiln build would fail on material anyway. The check
  has to land with the build work, not after a wooden kiln burns.
  Same gap, same fix as METALWORKING.md section 9.2.
- **No kiln jobs in JOB_SPECS.** JOB_SPECS (actions.py) has brew,
  brew_fruit, cook, and nine carpenter jobs. No kiln reaction, no
  CollectClay, no MakeAsh, no MakePotashFromAsh. The 13 kiln
  reaction codes exist in `reaction_other.txt` and the hardcoded
  job types exist in the live enum fixture (`CollectClay`,
  `MakeAsh`, `MakePotashFromAsh`, `MakePotashFromLye`), but no
  harness action names them.
- **No CollectClay queue path.** CollectClay is a plain hardcoded
  job (no reaction, no reagents), issued at a kiln against a clay
  zone. act_job.lua builds job items from reaction reagents, and
  a plain job has no reagents: the cook job (PrepareMeal, job type
  115, no reaction) proves plain jobs queue, but it does not prove
  a plain job tied to a zone attaches to that zone. Whether
  CollectClay needs a zone reference on the job, and whether the
  game fills it when the dwarf takes the job, is UNVERIFIED
  (section 19). The phase 2 probe must show it before any clay
  collection is promised.
- **No clay observation.** The survey counts soil tiles per
  z-level and never names the soil material (survey.lua:71,
  `info.mat == 'SOIL'`). There is no clay read anywhere: no
  survey record, no stocks entry, no site. The fort can stand on
  a clay layer and the model will never know.
- **No clay, plaster, pearlash, or quicklime observation in
  stocks.** `by_material` in stocks.lua covers only DRINK, FOOD,
  MEAT, FISH, PLANT, SEEDS, BAR, WOOD, CLOTH, THREAD. Clay
  boulders are BOULDER items, so they are counted only inside the
  undifferentiated `stone_units` total, beside every other
  boulder. Plaster and quicklime are POWDER_MISC items in bags,
  which no stocks category counts at all. Pearlash is a BAR item,
  counted only inside the undifferentiated `metal_bar_units`
  total, beside charcoal, coke, and every metal bar. The snapshot
  cannot say "12 clay", "2 plaster", or "0 pearlash" today.
- **No empty-bag observation.** Nothing counts empty bags, and
  both powder reactions need one per job. A plaster plan without
  a bag count is a plan that cancels at the kiln.
- **No ash observation.** Ash is a BAR item, counted only inside
  the same undifferentiated bar total as fuel and pearlash. The
  snapshot cannot say how much ash the glaze plan has, and the
  glazer cannot be told to wait for ash.
- **No potter or glazer assignment read.** Nothing says which dwarf
  holds POTTERY or GLAZING, or whether anyone does. The snapshot
  cannot say "no potter: kiln idle" today.
- **No ceramics section in the snapshot.** The model sees no kiln,
  no clay, no plaster, no pearlash, and no glaze state. Section 16
  closes that.
- **No TASK_DEFS entries.** TASK_DEFS (daemon.py:214) has six
  single-job tasks: brew, cook, make_bed, make_barrel, gather,
  farm. No ceramics task exists, and every ceramics chain is
  multi-step (collect then fire then glaze; ash then potash then
  pearlash), which the gap review already names as a foundation
  hole: no multi-step task framework exists at all (gap review 3,
  2026-11-27). Ceramics phases do not build that framework; they
  name the tasks the framework must one day express.

### 15.3 Cross-references already settled

- METALWORKING.md sections 4, 8, 9: the fuel economy, the fuel
  floor, the furnace build gap, the fire-safe check, and the
  magma impassable-tile question. The kiln draws on all of them
  and re-probes none of them.
- WOODWORKING.md sections 2.4, 2.5: the wood furnace (charcoal
  and ash), the ashery chain (lye, potash), and the pearlash row.
  The ceramics plan takes ash and potash as inputs from there.
- STONEWORKING.md sections 2.4, 4.4: economic stone (plaster
  stone, flux, and ore stay out of the mason's reach), and the
  missing stockpile-link write that ware control waits on.
- STOCKPILES.md section 4: feeder stockpiles take from anywhere,
  bulk stores from links only. The clay, fuel, and ash feeders
  follow it.
- TRADING.md sections 4, 5: the elf rules (ceramic accepted,
  wood derivatives refused) and the trade-good ranking (stone
  crafts default, ceramic crafts above them once the kiln runs).
- FARMING_PLAN.md section 8: potash as fertilizer, which competes
  with pearlash for the same potash bars.
- ANIMAL_HUSBANDRY.md: beekeeping, which the clay hive feeds.
  The hive need is checked in phase 1, not assumed here.

## 16. Model presentation

This section is required by the standing presentation constraint
(GOAL.md, 2026-11-27): the snapshot stays an index, budgets hold,
and every new system states how its information reaches the model,
what it costs, and what it deliberately does not push.

### 16.1 The snapshot section

The per-tick snapshot gains a short Ceramics section, built from
the fresh collect, in plain words. Counts and exceptions only,
never a dump. Two states, because the fort lives in the first one
today:

No ceramics industry yet (the fort today):

```
Ceramics: no kiln. Clay: none surveyed. Fuel: 0 charcoal, 0 coke.
Plaster: 0 bags. Pearlash: 0 bars. Next step: survey for clay (no survey on record).
```

Working industry (what the section looks like once the chain runs):

```
Ceramics: kiln #15. Clay: 12 boulders (earthenware), fire clay 0. Fuel: 8 charcoal (about 8 kiln jobs).
Plaster: 2 bags. Pearlash: 0 bars. Next: glaze 3 large pots (have 3 pots, 1 ash bar, 8 fuel, need 3 fuel).
```

What is in it, and what is not:

- **In it:** kiln state (which kilns exist, by building id, and
  whether each has its potter, glazer, and operator), clay on hand
  by ware (earthenware clay, fire clay, kaolinite boulders),
  fuel against the fuel floor, plaster bags against the hospital
  floor, pearlash bars, ash bars, the next kiln step as a
  have/need pair, and the blocker when a step cannot run ("no
  gypsum stone: no plaster" beats "kiln idle").
- **Not in it:** the full reaction table, the glaze value table,
  the full soil table, the survey bitmask, the per-dwarf potter
  skills, or the per-item glaze state. Those live behind the query
  route (section 16.3).
- **Never in it:** a list of every clay boulder, a list of every
  pot, or a number without its floor or its need. A clay count
  without the firing queue it serves is a number the agent cannot
  act on.

### 16.2 Token cost: measured from the section as written

Costs use the assembler's own accountant (assembler.py): the
conservative count is about 3 characters per token, the wire
estimate about 4 characters per token, and the accountant enforces
the budget at the conservative count, so the numbers below are the
accountant numbers first. The two example blocks in section 16.1
were measured character by character from the text as written.

- **No-industry state:** 150 characters, about 50 tokens
  accountant, about 38 tokens wire.
- **Working-industry state:** 210 characters, about 70 tokens
  accountant, about 52 tokens wire.
- **At 7 dwarves:** the section costs 50 tokens in the fort's
  current state (no industry), 70 tokens once the chain runs.
- **At 50 dwarves:** the same, 50 tokens with no industry and 70
  tokens with a working industry. The section reports counts per
  ware, per kiln, and per product, so its size does not grow with
  population. The per-dwarf growth lives in the units section,
  not here. The only way this section grows is by the fort holding
  more ware types at once, one short entry per kind, and a fort
  that holds all three wares at once is a fort with a clay survey
  worth celebrating, not a budget problem.
- **Against the budget:** the snapshot is about 4,700 tokens typical
  (world-model design section 6), with a 30K target, 60K warning,
  100K compaction, and a 140K hard cap on a 200K window, enforced
  by the token accountant with its cut order. This section is about
  1 to 2% of a typical snapshot. It never threatens the budget,
  and it is cut by the same cut order as everything else if the
  snapshot ever runs long: the section is not in NEVER_CUT, and
  the suggestion carries the urgent part if the section itself is
  cut.

### 16.3 The query route

GET /v1/ceramics returns the full detail, read from the fresh
collect, not from a cache: kilns with ids, materials, and labor
assignments; clay on hand by kind with boulder counts; kaolinite
boulders and the cluster state; gypsum stone on hand by kind;
calcium-carbonate stone on hand by kind; fuel split (charcoal
against coke) with the fuel floor; ash bars; potash bars;
pearlash bars; plaster bags and quicklime bags with the empty-bag
count; ceramic goods on hand by ware and kind, glazed against
unglazed; the kiln queue with have/need per job; and the potter,
glazer, and operator assignments with skills. It reuses the
existing read paths where they exist (GET /v1/stockpiles for the
clay, fuel, and ash stockpiles; GET /v1/sites for kiln sites; the
survey record for clay and gypsum stone). The snapshot carries
the summary; the route carries the detail. The agent asks the
route when it needs to choose a ware, a glaze medium, or a kiln
order, never as a matter of routine.

### 16.4 Briefing trigger and cost

Ceramics briefings fire on events, not on ticks. The triggers,
all named from the existing event vocabulary (events.py,
briefings.py):

- **Clay found.** The clay probe confirms a clay tile. The
  briefing names the clay type (earthenware clay, fire clay, or
  both), the nearest tile, and the next step: zone it and collect.
- **Fire clay found.** The probe confirms fire clay. The briefing
  names it separately, because stoneware changes the container
  chain: waterproof pots with no glaze step.
- **Kaolinite found.** The survey or a mined boulder confirms a
  kaolinite cluster. The briefing names the cluster and the
  porcelain plan it unlocks, with the finite-supply warning.
- **First pot fired.** The chain works end to end for the first
  time. The briefing names the ware, the pots on hand, and what
  glazing they still need.
- **Plaster short.** The hospital floor is unmet and a dwarf has
  a fracture. The briefing names the missing input (gypsum stone,
  empty bags, or fuel) and the fix.
- **First pearlash.** The ashery-to-kiln chain completes. The
  briefing names the pearlash on hand and that it waits on the
  glass industry.

Cost: a briefing is a short text plus its options, about 150 to 250
tokens accountant each, and it is delivered once per trigger, not
every tick. A fort that finds clay once pays that cost once. The
briefing never repeats the snapshot section; it names the event
and the choice, and points at the query route for the numbers. The
existing briefing drift rule applies here too (Military phase 1):
a briefing option must name an action the harness can actually
do, or say the action does not exist yet and what to do instead.
A "glaze the pots" option on a fort with no kiln is a bug, not a
briefing.

### 16.5 Opportunities entries

There is no separate opportunities list in the code today (verified
by grep: no `opportunit` symbol exists in `src/dfagent_harness/`).
So ceramics opportunities are expressed through the two mechanisms
that already exist, and this doc does not invent a third:

- **The snapshot suggestion.** The assembler already carries one
  suggestion per tick (NEVER_CUT, assembler.py:71), and the planner
  already writes material-blocker and build suggestions through it.
  The ceramics suggestion is one line with a one-line why, in the
  existing shape: "Zone the clay at (x, y, z) (clay found, no zone
  on record, the kiln cannot collect without one)" or "Fire 5
  large pots (have 12 clay, 8 fuel, need 5 fuel)" or "Make 2
  plaster (hospital floor 2 short, have gypsum and bags)". One
  suggestion per tick, the most urgent ceramics step, and only
  when a step is actually runnable. A suggestion never points at
  a job the fort cannot run.
- **Attention entries.** The conditions that outrank a quiet
  suggestion become attention entries, ranked with the other
  problems: plaster at zero with a fracture in the fort, clay
  collection cancelling repeatedly on a grassed-over zone, the
  kiln drawing fuel below the metal floor, kaolinite running out
  with a repeat porcelain order still on, the last cassiterite
  boulder glazed while the bronze plan is unmet. Attention is for
  the things that stop the industry or waste a finite resource,
  not for the things that would be nice.

No other opportunities mechanism is defined here. If a dedicated
opportunities list is built later, it takes these entries over
unchanged; nothing in this doc depends on it existing.

### 16.6 What this doc deliberately does NOT push to the model

- The full reaction table (section 7). The model needs to know
  which kiln job it can run from current stocks, not all thirteen
  reactions. The query route answers that; the snapshot carries
  only the next step.
- The full soil table (section 3.1). Five clay soils and two
  lookalikes are reference material for the survey, not a per-tick
  fact. The snapshot carries only the clay types the fort holds
  and the tiles it has found.
- The glaze value table. Ash glaze +50 and tin glaze +100 live
  behind the query route. The snapshot carries only "3 pots
  unglazed, 1 ash bar" when glazing is the next step, and nothing
  when it is not.
- The survey bitmask and the clay tile geometry. The survey is an
  area (world-model design section 5); the snapshot carries the
  nearest clay tile and its distance, and the slice and query
  routes carry the map.
- Per-dwarf potter and glazer skills. The snapshot names the
  missing labor ("no potter"), not every potter's skill line.
  Skills live in the units section and the query route.
- The fuel arithmetic. The snapshot carries fuel against its
  floor; the per-job fuel math stays in this doc and in the
  have/need check that refuses a job the fort cannot feed.
- The ashery chain. Ash, lye, and potash production belong to
  WOODWORKING.md, and their numbers live in that doc's snapshot
  section, not here. This section carries only the potash and ash
  counts the kiln consumes, never the chain that made them.
- The glass industry. Pearlash waits on GLASSMAKING.md, which
  exists and owns clear and crystal glass. The snapshot carries
  the pearlash count and nothing about what glass it could become.

The rule, restated from the constraint: the snapshot is an index
into the full state, not a replacement for it. The model pulls
the detail when it needs to decide, and the harness never pushes
a dump to save it the asking. Freedom is preserved: the snapshot
names the next step as a have/need pair and never picks the
strategy. Whether the fort fires pots, statues, or crafts, and
whether it glazes with ash or cassiterite, is the model's call
from the numbers, not the harness's.

## 17. Refusals

The harness refuses these, and says why in plain words when asked:

1. Never build a kiln from a material that is not fire-safe, and
   never build a magma kiln from a material that is not
   magma-safe. The build fails fast naming the material.
2. Never queue a kiln job without the fuel on hand. The fail-fast
   names the fuel shortfall, not a generic error.
3. Never draw kiln fuel below the metal floor, except for plaster
   when the hospital floor is unmet (section 11.2). The refusal
   names the floor and the exception.
4. Never fire a ware the fort does not hold. A firing job names
   the ware it expects, and a read-back that finds another ware
   is reported as an error, not filed as success.
5. Never glaze a brick, a hive, or an instrument. No reaction
   exists for them, and a glaze order naming one is refused.
6. Never smelt the last cassiterite into tin while the glaze plan
   still needs it, and never glaze with cassiterite while the
   bronze have/need is unmet, without the agent saying so.
7. Never spend the last flux stone on quicklime while the steel
   plan is unmet, without the agent saying so.
8. Never spend the last potash bar on pearlash while a farm plot
   waits for fertilizer, without the agent saying so.
9. Never make plaster or quicklime without an empty bag on hand.
   The fail-fast names the bag, not the kiln.
10. Never count clay boulders as mason stone, and never let a
    mason job consume a clay boulder. Clay is kiln feed.
11. Never enable kaolinite for masonry by default. Kaolinite is
    porcelain feed, and any exception is the agent's named
    decision.
12. Never queue a repeat porcelain order without a kaolinite count
    against it. Porcelain is finite, and a repeat order with no
    count drains the cluster silently.
13. Never claim a pot, a glaze, a plaster bag, or a pearlash bar is
    ready without a live read-back: the item exists in stocks,
    the glaze improvement is on the item, the bag holds powder.
14. Never use the kiln as metal industry progress. It burns fuel
    and makes no metal.
15. Never send the model a dump. Section 16.6 is the list, and the
    snapshot stays an index.

## 18. Implementation phases, in order

Each phase lands only when its verification bar is met live. A mock
or a unit test alone is not verification. Phases 1 to 3 are
observation and probes; the kiln cannot be promised before them.
Phases 4 to 6 build the chain; phases 7 to 9 extend it.

1. **Ceramics observation.** Read-only probes: clay tile probe
   (a Lua read over surveyed soil tiles reporting each tile's soil
   material, or a targeted DFHack query of the same), gypsum stone
   and kaolinite in the survey record, clay boulders by material
   (extend the stocks collect to report BOULDER materials), ash
   and pearlash split out of the bar total, empty bags counted,
   plaster and quicklime bags counted, potter and glazer labors
   per dwarf, and the beehive need from the beekeeping plan.
   Add the Ceramics section to the snapshot and the
   GET /v1/ceramics route. Verification: a live collect on the
   main fort reports the true clay state (clay present or absent,
   named by type), the true plaster count (zero, named), and the
   true fuel split, and the snapshot section matches a hand check
   of the stocks.
2. **Kiln job probes.** Queue the 13 kiln reactions as
   CustomReaction jobs on the scratch fort (one firing reaction,
   one glaze reaction, MAKE_PEARLASH, MAKE_PLASTER_POWDER,
   MAKE_QUICKLIME) and read the job structs back; queue
   CollectClay as a plain job at a kiln with a clay zone and read
   it back; record how the zone attaches, whether the game fills
   plain-job items, and the added value of an ash-glazed and a
   tin-glazed item. Verification: each probe names the field or
   the absence of one with a live job id, the glazed items read
   back with their glaze improvement and value, and this doc
   records the answers. If CollectClay cannot take a zone at
   queue time, the plan adapts and never claims otherwise.
3. **Clay first: zone and collection.** Place a clay zone on a
   confirmed clay tile near the kiln site, assign haulers, queue
   CollectClay on repeat, and establish the clay floor.
   Verification: live clay boulders appear in stocks with their
   material named, the clay count reads back against the floor,
   and a grassed-over zone produces the cancellation the doc
   predicts, handled as a blocked zone with the reason named.
4. **Kiln build.** Generalize `act_build.lua` to a type-aware
   subtype lookup (`df.furnace_type` for furnaces,
   `df.workshop_type` for workshops), add the kiln to the build
   path with its fire-safe material rule, and add the kiln to
   WORKSHOP_CATALOG and to materials.WORKSHOP_MATERIALS with its
   have/need text. Verification: a kiln builds live on the
   scratch fort from fire-safe stone, reads back with its
   material and its 3x3 footprint, and a non-fire-safe material
   is refused with the reason named.
5. **Firing pipeline.** JOB_SPECS entries for the six firing
   reactions, the firing have/need check (clay, fuel, potter),
   and the firing decision in the planner: fire the ware the
   agent names, pots first while the fort has no glazed
   containers, then crafts for trade. Verification: a live firing
   of a named clay on the scratch fort produces the named item
   in the named ware, read back in stocks, and the snapshot names
   the ware.
6. **Glazing pipeline.** JOB_SPECS entries for the four glaze
   reactions, the glaze have/need check (finished item, glaze
   medium, fuel, glazer), and the glaze decision: glaze
   earthenware containers first, trade goods second, stoneware
   and porcelain only on the agent's call. Verification: a live
   ash glaze and a live tin glaze each produce a glazed item read
   back with its improvement and its added value, and an
   unglazed earthenware pot refuses a liquid-storage claim until
   glazed.
7. **Operator pipeline: plaster, pearlash, quicklime.** JOB_SPECS
   entries for MAKE_PLASTER_POWDER, MAKE_PEARLASH, and
   MAKE_QUICKLIME, the operator have/need checks (stone, bag,
   potash, fuel, furnace operator), the plaster floor wired to
   the hospital, and the scheduling order (plaster, quicklime on
   ask, pearlash last). Verification: a live plaster job produces
   a bag of plaster powder read back in the hospital chest, a
   live pearlash job produces a pearlash bar read back in the bar
   stockpile, and a live quicklime job produces a bag of
   quicklime, each with its inputs counted down.
8. **Trade and ware control.** The ceramic trade ranking (crafts
   above stone crafts, glazed goods above unglazed, porcelain
   above earthenware) wired into the trading plan, the ware
   control by stockpile isolation or links when links land, and
   the kaolinite budget (porcelain orders counted against the
   cluster). Verification: a live season runs with the kiln
   firing the ware the agent named, the trade goods counted end
   to end, and a repeat porcelain order refusing when the
   kaolinite count runs out.
9. **Magma kiln.** The magma survey (find the magma sea),
   magma-safe material checks, and the magma kiln build with the
   4/7 depth rule and the impassable-tile check from section 12.
   Verification: a magma kiln fires clay with zero heat fuel, a
   glaze at a magma kiln costs zero heat fuel, and a pearlash run
   at magma costs zero heat fuel.

## 19. Open questions (UNVERIFIED)

- **Clay presence on this map.** Whether the fort's map holds any
  clay, fire clay, kaolinite, or gypsum stone at all. No record
  the harness can read today says so. Phase 1 probes it.
- **The clay tile probe.** Whether a Lua read over surveyed soil
  tiles can report each tile's soil material, or whether a new
  DFHack query is needed. Phase 1 builds it.
- **CollectClay zone attachment.** Whether a CollectClay job
  queued by act_job.lua carries its zone reference, or whether
  the game attaches the zone when the dwarf takes the job.
  Phase 2 probes it live.
- **Kiln footprint.** Whether the 0.47.05 kiln is 3x3. The
  footprint is a wiki-pattern claim. Phase 4 confirms it by
  read-back.
- **Fire-safe refusal.** Whether the game refuses a non-fire-safe
  material for a kiln at placement time, or lets the building
  stand. Phase 4 probes it. Shared with metalworking; one answer
  covers all furnaces.
- **Magma impassable tile.** Whether the 0.47.05 magma kiln still
  has the impassable tile the v50 wiki says was removed in v50.
  Phase 9 verifies it live before any magma kiln is trusted as
  sealed.
- **Glaze value added.** Whether an ash glaze adds exactly 50 and
  a tin glaze exactly 100 to an item's value in 0.47.05. The
  figures are wiki claims; the raws give only the glaze material
  values. Phase 2 verifies them by read-back.
- **Kiln instruments.** Whether kiln-made instruments or
  instrument pieces exist in 0.47.05 at all. No reaction names
  the kiln for them. Phase 2 probes it.
- **Manager orders for kiln reactions.** Whether the harness's
  manager_order_create can order kiln reactions (and plaster
  powder in particular, the wiki's named fallback). Phase 2
  probes it.
- **Collect Clay cancellation reasons.** Whether the harness can
  read why a Collect Clay job cancelled (grass on the tile, no
  valid zone), or only that it cancelled. Phase 3 probes it.
- **Ware control without links.** Whether forbidding the unwanted
  clay type, or isolating it in a stockpile the kiln cannot reach,
  reliably controls which ware a kiln fires. Phase 5 probes it
  live with mixed clay on hand.
- **Tin glaze and elves.** Whether a tin-glazed ceramic item is
  accepted by elven traders. Phase 8 tries one only on the
  agent's ask.
- **The beehive need.** How many clay hives the beekeeping plan
  wants, and when. Phase 1 checks ANIMAL_HUSBANDRY.md rather
  than assuming a number.
- **Plaster and quicklime counts.** Whether the stocks collect can
  report powder-in-bag counts, or whether a new Lua read is
  needed. Phase 1 probes it.
- **Kiln shortcuts and the v50 UI.** The shortcut keys and the
  click paths on the wiki pages are v50. The harness never uses
  keystrokes for game actions, so this only matters for human
  verification steps, and any shortcut in a verification step
  must be confirmed against 0.47.05 first.

## 20. Failure modes

The ways this industry fails, named so the harness can recognize
each one instead of reporting "kiln idle":

1. **No clay on the map.** The survey finds soil but no clay
   material, or no soil at all. The kiln never starts, and the
   ceramics plan becomes a trade plan (request clay or kaolinite
   from the liaison). The snapshot says "no clay on this map",
   not "no kiln yet".
2. **Grass on the clay.** Collection cancels again and again on a
   zone that looks fine. The cause is growth on the tile, the fix
   is a dirt road or a floor grate after clearing, and the
   harness must name the cause, not queue another zone.
3. **The potter outruns the haulers.** Firing cancels for lack of
   clay while the zone sits full of uncollected boulders. The
   cause is hauler count and walk, the fix is more haulers and a
   closer zone, and the clay floor is the number that says so.
4. **Fuel starvation.** The kiln fires through the fuel floor and
   the smelter stalls. The cause is an unguarded kiln queue, the
   fix is the floor check on every batch, and the refusal names
   the floor.
5. **Ash starvation.** The glaze plan and the ashery chain both
   want the same ash, and the glazer waits while the potash maker
   takes it. The cause is a shared input with no priority, the
   fix is the agent's named split, and the snapshot shows ash
   against both needs.
6. **Wrong ware fired.** Mixed clay on hand, no links, and the
   kiln fires earthenware when the agent wanted porcelain, or
   porcelain when the agent wanted earthenware. The cause is
   uncontrolled material choice, the fix is isolation before the
   job, and the read-back catches it after the fact.
7. **Porcelain drained.** A repeat porcelain order eats the whole
   kaolinite cluster on statues. The cause is a repeat order with
   no count, the fix is the kaolinite budget, and the refusal
   names the remaining boulders.
8. **Plaster with nowhere to go.** Plaster bags pile at the kiln
   because the hospital has no chest. The cause is a missing
   hospital furnishing, the fix belongs to the hospital plan, and
   the snapshot names the chest, not the kiln.
9. **Powder without bags.** Plaster and quicklime jobs cancel for
   lack of empty bags while the kiln has stone and fuel. The cause
   is an uncounted input, the fix is the empty-bag count in the
   snapshot, and the refusal names the bag.
10. **Tin glaze eats the bronze.** Cassiterite glazed while the
    fort has no tin for bronze. The cause is a glaze job that did
    not check the metal plan, the fix is the shared cassiterite
    count, and the refusal names the bronze need.
11. **Flux eaten by quicklime.** Limestone burned into quicklime
    while the steel plan waits for flux. Same shape as failure 10,
    same fix: one shared count, named in both snapshots.
12. **The kiln as a second smelter.** The agent mistakes kiln jobs
    for metal progress because both burn fuel and both use the
    furnace operator. The cause is a snapshot that lists kiln
    activity under metal, the fix is the separate Ceramics
    section, and the refusal is refusal 14 in section 17.

## 21. Cross-doc conflicts flagged

Conflicts and near-conflicts found while writing this doc, stated
here rather than resolved silently. The coordinator owns the
resolution; this doc records the disagreement and the evidence
for each side.

1. **WOODWORKING.md section 2.5 vs the Ashery wiki page: the lye
   labor.** WOODWORKING.md says one bar of ash makes one bucket
   of lye at an ashery "with the wood burning labor". The Ashery
   wiki page lists the job requirements as Potash Making and Lye
   Making, and the live enum fixture lists a LYE_MAKING labor.
   The wiki and the enum agree against WOODWORKING.md. This doc
   takes the wiki and enum side (lye making labor) and flags
   WOODWORKING.md for correction; the live probe in ceramics
   phase 2 (which queues the ashery jobs for the pearlash chain)
   should confirm the labor and the correction should land in
   WOODWORKING.md, not here.
2. **METALWORKING.md section 1.2 vs this doc: the kiln's fuel
   draw.** METALWORKING.md says the kiln "competes for the same
   fuel" and that a kiln "must never be counted as metal industry
   progress". This doc agrees on both points and adds the only
   exception: plaster outranks a smelt when the hospital floor is
   unmet (section 11.2). That exception is new, and it is stated
   here, not smuggled in: the planner must implement it
   explicitly, and if the metalworking plan disagrees, the
   disagreement is resolved in the planner, not by editing either
   doc quietly.
3. **STONEWORKING.md vs this doc: kaolinite as stone.** The
   ceramic industry page notes a mason can turn one kaolinite
   boulder into four magma-safe kaolinite blocks when kaolinite
   is set non-economic. STONEWORKING.md's economic-stone rule
   keeps ore, flux, plaster stone, and fuel stone out of the
   mason's reach by default; this doc adds kaolinite to the
   do-not-touch list (refusal 11). No direct contradiction was
   found in STONEWORKING.md's text, but the two docs must agree
   on the list: the coordinator should check that kaolinite is
   named as economic in the stone plan, not only here.
4. **GLASSMAKING.md exists and agrees on the recipe, but assigns
   potash production to CERAMICS.** GLASSMAKING.md section 6 says
   "CERAMICS owns: the kiln and magma kiln builds, potash from
   ash and lye at the ashery, pearlash from potash at the kiln".
   This doc and WOODWORKING.md section 2.5 both assign the ashery
   chain (ash, lye, potash) to WOODWORKING, which already
   documents it, and this doc owns only the kiln-side consumption
   of potash. The two boundary statements disagree on who owns
   potash production. The recipe itself is not in dispute: both
   docs agree MAKE_PEARLASH is 1 potash bar in, 1 pearlash bar
   out, furnace operator labor, 1 fuel per job at a standard
   kiln. The coordinator should resolve the ownership in one
   place (this doc's position: ashery production stays with
   WOODWORKING, since it is already documented there, and
   GLASSMAKING.md's boundary line should be corrected to match),
   not by letting each doc claim it.
5. **No parchment doc owns the tanner step, but the route is
   covered.** MAKE_MILK_OF_LIME is documented in SOAP_MAKING.md
   (ashery, skill LYE_MAKING, for parchment, not soap) and the
   parchment sheet route is covered by MILLING_AND_PRESSING.md,
   which assigns parchment to CLOTHING.md's leather chain. No doc
   owns the tanner parchment step itself yet. When one is written,
   it takes the quicklime count as its input and must not
   re-derive the kiln step.

No other conflict was found. METALWORKING.md's fuel numbers,
WOODWORKING.md's ash and potash numbers (except conflict 1), and
STONEWORKING.md's stockpile rules were all checked against the
raws while writing this doc and agree with the tables here.

## 22. Sources

Wiki pages read from the local index
(`~/workspace/df-wiki-export/dfq.py`, hybrid search default):

- Ceramic industry, Kiln, Magma kiln, Ceramic, Earthenware,
  Stoneware, Porcelain, Clay, Fire clay, Glazing (in Ceramic
  industry), Ash glaze, Tin glaze, Potter, Quicklime, Pearlash,
  Potash, Ashery, Gypsum plaster, Health care.
- The local index tracks current DF (v50 and later). Every UI-level
  claim from it (shortcuts, click paths, the magma impassable tile,
  the v0.42.01 instrument note) is treated as v50 text until
  verified live against 0.47.05, and section 19 lists the ones
  that matter.

0.47.05 raws, read from the game files in the repo
(`third_party/df_47_05/raw/objects/`):

- `reaction_other.txt`: all 13 kiln reactions in section 7, with
  exact reagents, skills, and fuel tags; MAKE_MILK_OF_LIME,
  MAKE_PARCHMENT, and the paper chain in section 10.
- `inorganic_stone_soil.txt`: the five clay soils and their
  FIRED_MAT products (section 3.1), and the absence of FIRED_MAT
  on sandy clay loam and silty clay loam.
- `inorganic_stone_mineral.txt`: kaolinite (sedimentary cluster,
  FIRED_MAT porcelain), cassiterite (GLAZE_MAT tin glaze),
  gypsum, alabaster, selenite, satinspar (REACTION_CLASS:GYPSUM),
  calcite (REACTION_CLASS:CALCIUM_CARBONATE, FLUX).
- `inorganic_stone_layer.txt`: limestone, chalk, marble
  (REACTION_CLASS:CALCIUM_CARBONATE, FLUX).
- `inorganic_other.txt`: CERAMIC_EARTHENWARE (value 3, density
  1360), CERAMIC_STONEWARE (value 4, density 2000),
  CERAMIC_PORCELAIN (value 10, density 2403), ASH_GLAZE (value 5),
  TIN_GLAZE (value 10), PLASTER (value 3), QUICKLIME (value 10).
- `material_template_default.txt`: the stone template carries
  REACTION_CLASS:CAN_GLAZE, so stone items of the four glazeable
  kinds can be glazed too.
- CollectClay, MakeAsh, MakePotashFromAsh, and MakePotashFromLye
  appear in NO reaction raw: all four are hardcoded game jobs,
  which is why they are plain job types in the enum fixture and
  not CustomReaction jobs. No instrument reaction names the kiln
  in any reaction raw.

Harness state verified against the repo:

- `tests/fixtures/runtime-enums-0.47.05-r8.json`: `furnace_types`
  (WoodFurnace, Smelter, GlassFurnace, Kiln, MagmaSmelter,
  MagmaGlassFurnace, MagmaKiln), `workshop_types` (Ashery among
  others), `job_types` (CollectClay, MakeAsh, MakePotashFromAsh,
  MakePotashFromLye, MakeCharcoal), `unit_labors` (POTTERY,
  GLAZING, SMELT, HAUL_ITEM, BURN_WOOD, POTASH_MAKING,
  LYE_MAKING), `job_skills` (POTTERY, GLAZING, SMELT,
  POTASH_MAKING).
- `src/dfagent_harness/actions.py`: WORKSHOP_CATALOG (carpenter,
  mason, still, kitchen only), JOB_SPECS (brew, cook, carpenter
  jobs only), `build_workshop` (single material, workshop subtype
  only), `create_zone` with ZONE_KINDS including "clay" (verified
  live 2026-11-26), `manager_order_create`.
- `src/dfagent_harness/daemon.py:214`: TASK_DEFS (brew, cook,
  make_bed, make_barrel, gather, farm only).
- `src/dfagent_harness/lua/act_build.lua`: workshop-only subtype
  lookup, single material.
- `src/dfagent_harness/lua/act_job.lua`: job items from reaction
  reagents; plain-job attachment unverified.
- `src/dfagent_harness/lua/act_zone.lua`: zone creation with kind
  flag and active flag.
- `src/dfagent_harness/lua/stocks.lua`: `metal_bar_units` counted,
  `stone_units` undifferentiated, `by_material` covers DRINK,
  FOOD, MEAT, FISH, PLANT, SEEDS, BAR, WOOD, CLOTH, THREAD only.
- `src/dfagent_harness/survey.py` and `lua/survey.lua`: soil
  counted per z-level, material never named.
- `src/dfagent_harness/assembler.py`: token accountant (3
  chars/token conservative, 4 chars/token wire), NEVER_CUT
  (attention, header, status, suggestion), budgets 30K/60K/100K/140K.
- `src/dfagent_harness/planner.py`: metal industry deferred for
  lack of ore and forge inputs; ceramics not named.
- `src/dfagent_harness/materials.py`: WORKSHOP_MATERIALS
  (carpenter, mason, still, kitchen only).
- `docs/ADVANCED_MECHANICS.md` section 4: the `act_build.lua`
  subtype generalization, already queued by the trap work.
- `docs/METALWORKING.md` sections 1, 4, 8, 9, 13: the kiln as a
  fuel competitor, the fuel economy and floor, fire safety, the
  furnace build gap, the snapshot pattern this doc follows.
- `docs/WOODWORKING.md` sections 2.4, 2.5: the wood furnace, the
  ashery chain, and the pearlash row.
- `docs/STONEWORKING.md` sections 2.4, 4.4: economic stone and
  the missing stockpile-link write.
- `docs/STOCKPILES.md` section 4: feeder stockpiles.
- `docs/TRADING.md` sections 4, 5: the elf rules and the trade-good
  ranking.
- `docs/FARMING_PLAN.md` section 8: potash as fertilizer.
- `docs/GLASSMAKING.md` sections 6, 7: the pearlash boundary
  (CERAMICS owns the kiln and pearlash; glass consumes pearlash
  without making it) and the shared fuel floor. Its boundary line
  assigning potash production to CERAMICS is flagged as conflict
  4 in section 21.
- `docs/SOAP_MAKING.md`: the ashery job list, including milk of
  lime (skill LYE_MAKING, for parchment, not soap), and the
  hardcoded nature of the lye and potash jobs.
- `docs/MILLING_AND_PRESSING.md`: parchment as the third sheet
  route, assigned to CLOTHING.md's leather chain.
- `~/workspace/goals/dwarf-fortress-0-47-05-autonomous-play-harness/GOAL.md`:
  the presentation constraint (2026-11-27) and the breadth order.
- `~/workspace/goals/dwarf-fortress-0-47-05-autonomous-play-harness/hidden_files/gap-review-3-20261127.md`:
  the multi-step task framework gap and the 12-of-13 docs missing
  a Model presentation section.

Fort state: `~/.config/df-agent-harness/world.db`, snapshot tick
115166, 2026-11-27 (7 citizens, Carpenters #7 and Still #8 only,
drink 97, food 23, wood 117, stone 0, no kiln, no clay, no plaster,
no pearlash in the rendered stocks, no survey stored). Last-known
only: the daemon and the game were down at the time of writing
(VM replacement about 19:37 PT, 2026-11-27), so every live value
in section 2 is UNVERIFIED until a fresh collect re-reads it.
