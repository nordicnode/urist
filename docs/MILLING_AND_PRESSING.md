# Milling and pressing

Design document for the milling and pressing SYSTEM in the Urist
harness: the quern and the millstone, the miller labor, milling
plants into flour, sugar, dye, paste, and slurry, the screw press
(oil pressing, honeycomb pressing, paper pressing), the soap chain
that oil feeds, and what the harness needs to observe, build,
queue, and verify for all of it. This is a plan, not an
implementation. Nothing in this document is built yet unless it
says otherwise.

## Which file holds what

- `docs/FARMING_PLAN.md` owns the farm supply side: which crops
  grow, in which season, and the split rule that decides what a
  harvest becomes. This document owns what happens after the
  harvest reaches a mill or a press. Where the two docs meet is
  the split rule (section 6), and this doc does not re-decide it.
- `docs/KITCHEN.md` owns cooking and brewing, including flour,
  sugar, and oil as meal ingredients. This document owns making
  those ingredients. The kitchen doc's gap (processed ingredients
  are invisible in stocks) is closed by phase 1 here.
- `docs/CLOTHING.md` owns dyeing thread and cloth at the dyer's
  shop. This document owns milling the dye plant into dye powder.
  The boundary is the powder: milling is here, dyeing is there.
- `docs/STONEWORKING.md` owns making the quern and millstone
  items at the mason's workshop. This document owns placing them
  as workshops and running the mill jobs on them.
- `docs/ANIMAL_HUSBANDRY.md` owns hives and honeycombs at the
  source. This document owns pressing a honeycomb at the screw
  press. `docs/HUNTING.md` owns fat and tallow at the source.
  This document owns turning tallow or oil into soap.

Every game mechanic in this document comes from the local Dwarf
Fortress wiki index (see Sources at the end) or from the 0.47.05
raws in the repo, or from a live verification against the game.
Anything not verified against one of those is marked UNVERIFIED.
The wiki export is the v50 wiki, so every wiki claim in this doc
was checked against the 0.47.05 raws or the live runtime-enum
fixture (`tests/fixtures/runtime-enums-0.47.05-r8.json`). Where
the v50 wiki and 0.47.05 differ, the difference is named.

## 1. Purpose

Milling and pressing are the fort's grinding industries. They
turn farm output into things the kitchen, the clothier, the
hospital, and the library need: flour and sugar for cooking, dye
for cloth, oil for cooking and soap, paste as the step between
seed and oil, slurry as the step between plant fiber and paper,
and soap for the hospital. Without a quern, cave wheat is a brew
crop and nothing else. Without a screw press, quarry bush seeds
are food and nothing else. Without soap, a wounded dwarf heals
with a higher chance of infection.

The harness must drive all of it. The agent picks from named
options; the harness does the counting, the timing, and the
refusing.

## 2. How milling works in DF 0.47.05

All of this section is from the wiki pages listed in Sources,
checked against the 0.47.05 raws where the raws settle it.

### 2.1 The quern

A quern is a single-square workshop, hand-powered by the dwarf
using it. It grinds plants into sugar, flour, dye, paste, and
slurry. Its jobs, from the Quern page:

- Mill plants (miller skill).
- Mill seeds/nuts to paste (miller skill).
- Mash plant into slurry (papermaker skill).

Each milling job requires an empty bag, because the product is a
powder that must be stored in a bag, and because milling also
produces seeds from the plant being milled. A quern item must be
created at a stoneworker's workshop by a stone carver before it
can be built as a workshop. In 0.47.05 the stoneworker's
workshop is the mason's workshop (the v50 rename; same
workshop). The live job enum holds `ConstructQuern`, which is
the job that makes the quern item. Whether that job is offered
at the mason's workshop in 0.47.05, as STONEWORKING.md asserts,
is UNVERIFIED until phase 2 probes it live.

A material may be specified for the "Mill plants" task after it
is designated, or via a work order. For milling seeds, there is
no option to choose which plant to use, so specifying a plant
requires a stockpile that only allows those plants and setting
it to give to the quern, plus a furniture stockpile that allows
only bags, also set to give to the quern. Without that linkage
the miller picks the closest random plant, with the usual,
occasionally surprising, definition of closest. That random
pick is the central control problem for this industry (section
7.3). The v50 note that millstones can specify plants since
52.03 does not apply to 0.47.05 and must never be relied on.

### 2.2 The millstone

A millstone grinds the same plants as a quern, faster, but it
needs mechanical power: 10 power units from a water wheel or a
windmill. Before it can be placed as a building, a millstone
item must first be constructed at a stoneworker's workshop. The
live job enum holds `ConstructMillstone`. Building the
millstone workshop takes a millstone item plus a mechanism, and
is done by a dwarf with the Mechanic labor. If the power to the
millstone is interrupted, any jobs must be re-queued when power
returns. A millstone can be placed in a hanging state, but it
will not actually be constructed, because the builder needs to
stand on the square it is being built on. A millstone must
therefore be powered from above or from the side, not from
below. Power (water wheels, windmills, gear assemblies, axles)
belongs to the machinery work, not to this doc; this doc owns
the millstone as a milling workshop and the flag that says it
has no power.

The quern is the first mill. The millstone is the scale mill. A
fort mills at a quern until the mill jobs queue faster than one
miller can work them, and only then spends the mason, mechanic,
and power work on a millstone.

### 2.3 What milling produces

Milling a plant produces one unit of powder per item milled, as
well as 1 or 2 seeds. Milled goods have no quality. The seed
return (1 or 2) is wiki-sourced from the Miller page and
UNVERIFIED live (open question 2). Whether one MillPlants job
consumes a whole plant stack or a single plant, and whether the
powder output scales with the stack, is UNVERIFIED live (open
question 3). Milling does not increase stack size (FARMING_PLAN
section 2.3): one plant in is one powder out, plus seeds. That
is why milling is a conversion, not a multiplier like brewing.

The millable plants, verified against the 0.47.05 plant raws
(`[MILL:LOCAL_PLANT_MAT:MILL]` tokens):

| Product | Plants (0.47.05 raws) |
| --- | --- |
| Dwarven wheat flour | Cave wheat |
| Longland flour | Longland grass |
| Whip vine flour | Whip vine |
| Garden flours | Single-grain wheat, two-grain wheat, soft wheat, hard wheat, spelt, barley, buckwheat, oats, rye, sorghum, rice, maize, quinoa, kaniwa, pendant amaranth, blood amaranth, purple amaranth, pearl millet, white millet, finger millet, foxtail millet, fonio, teff, flax, hemp |
| Dwarven sugar | Sweet pod |
| Dimple dye (20) | Dimple cup |
| Emerald dye (20) | Blade weed |
| Redroot dye (10) | Hide root |
| Sliver dye (20) | Sliver barb |

Flour value is 20 per unit for the common flours, 25 for whip
vine flour. Dye values are in the table. Sugar has no separate
value listed on the Miller page; it cooks like flour. All four
dye plants are verified in the raws. Flax and hemp are dual
purpose: they mill into flour and their seeds press into oil
(section 3.2).

Powder must be stored in a bag. Powder dumped from a bag is not
recoverable. Flour, sugar, dye, and rock nut paste do not rot
(KITCHEN.md section 10). Bug 4371: dwarves occasionally combine
two separate mill products in the same bag.

### 2.4 Milling seeds to paste

The reaction is `MILL_SEEDS_NUTS_TO_PASTE` in
`reaction_other.txt`: quern or millstone, CUSTOM_S, 1 seed with
`PRESS_LIQUID_MAT`, producing 1 GLOB of paste, skill MILLING.
Only the seeds of plants with an associated oil can be milled:
the reaction filter is the `PRESS_LIQUID_MAT` material reaction
product, so a seed without it is refused by the game itself.
Paste is the intermediate between seed and oil. It is stored in
food stockpiles under the Paste category, and it does not rot.
The size of the paste glob one seed produces is UNVERIFIED live
(open question 4): the press reaction takes 150 units of paste,
so the glob size decides how many seeds one press job needs.

### 2.5 The miller

The miller skill is associated with the milling labor, in the
Farmer profession. The live labor enum holds `MILLER` and the
live skill enum holds `MILLING`. The wiki names strength,
agility, endurance, and kinesthetic sense as the relevant
attributes. Milling has no quality output, so skill sets speed,
not value. A dabbling miller mills as good a flour as a
legendary one, only slower. That is why the miller floor is 1
and stays 1 until the mill queue backs up (section 10).

## 3. How pressing works in DF 0.47.05

### 3.1 The screw press

A screw press is a special workshop used to press liquids out
of substances and to press slurry into sheets of paper. It is
one of exactly two workshops defined in the raws. Verified
against the repo: `third_party/df_47_05/raw/objects/` holds
exactly one workshop definition file, `building_custom.txt`,
and it defines exactly two workshops, `SOAP_MAKER` and
`SCREW_PRESS`. Every other workshop is hardcoded in the game,
not raw-defined. The live workshop enum lists 25 types,
including `Custom`, which is the subtype both raw-defined
workshops share. That sharing is a harness problem: the subtype
alone cannot tell a screw press from a soap maker's workshop
(section 8.2).

The screw press raw, from `building_custom.txt`: 1x1,
`[BUILD_LABOR:MECHANIC]`, build key CUSTOM_P, two mechanisms
as build items. Food jobs there use the pressing skill. Slurry
pressing uses the papermaking skill. Sheets of paper have
quality levels; the other screw press products do not.

### 3.2 Oil pressing

The oil crops, verified against the 0.47.05 plant raws
(`PRESS_LIQUID_MAT` on the seed material):

| Plant | Underground | Oil | Oil value |
| --- | --- | --- | --- |
| Quarry bush (rock nuts) | Yes | Rock nut oil | 5 |
| Cotton | No | Cottonseed oil | 5 |
| Flax | No | Linseed oil | 5 |
| Hemp | No | Hempseed oil | 5 |
| Kenaf | No | Kenaf seed oil | 5 |
| Olive (fruit, pressed whole) | No | Olive oil | 5 |

The reactions, from `reaction_other.txt`:

- `PRESS_OIL`: screw press CUSTOM_P, 150 units of paste glob
  with `PRESS_LIQUID_MAT` and `NOT_PRESSED`, plus 1 empty jug
  (liquid container, preserved), producing 1 LIQUID_MISC oil
  into the jug and 1 GLOB press cake, skill PRESSING.
- `PRESS_OIL_FRUIT`: screw press CUSTOM_F, 1 fruit
  (PLANT_GROWTH) with `PRESS_LIQUID_MAT`, plus 1 empty jug,
  producing oil and a pomace glob, skill PRESSING. Olive oil is
  unusual: it is pressed from the whole olive fruit, not from
  seeds, so olives skip the milling step entirely.
- `PRESS_HONEYCOMB`: screw press CUSTOM_H, 1 honeycomb plus 1
  empty jug, producing honey (LIQUID_MISC) and a wax cake
  (GLOB), skill PRESSING.

Press cakes and pomaces are unremarkable ingredients, only used
as filler for a prepared meal. They are stored in food
stockpiles under the Pressed Material category. The value math,
from the Oil page: most seeds can be cooked directly at a base
value of 1, but milling the seeds to paste and pressing them
into oil generates a press cake worth 1 and a unit of oil worth
5, a 500 percent value increase for two labors. Whether the
press produces 1 unit of oil or a 150-unit jug of it is
UNVERIFIED live (open question 5): the reaction product is
`100:1:LIQUID_MISC`, and the jug holds the result.

Oil is a cooking ingredient and a soap input. Cooks use oil
only as a last resort, preferring solid foods (Bug 2393,
KITCHEN.md section 2.5). Oil does not rot.

### 3.3 Honeycomb pressing

Pressing a honeycomb yields honey, which brews into mead, and a
wax cake, which wax workers make into finished goods. The
honeycomb comes from hives (beekeeping), which no harness doc
owns yet: ANIMAL_HUSBANDRY.md does not cover beekeeping. So the
press job is specified here, but its input has no supply chain
until beekeeping lands. The screw press page records a bug:
screw presses sometimes do not allow the "press honeycomb" job
to be added directly, and adding the job through the manager
interface gets the work started. Whether that bug holds in
0.47.05 is UNVERIFIED (open question 6); phase 5 proves it.

### 3.4 Paper pressing

Paper is made from plant fibers mashed into slurry at a quern
or millstone and then pressed on a screw press. Both actions use
the papermaking labor. The reactions, from `reaction_other.txt`:

- `MAKE_SLURRY_FROM_PLANT`: quern or millstone, 1 plant with
  `PRESS_PAPER_MAT`, producing 1 GLOB of slurry and 1 seed,
  skill PAPERMAKING.
- `PRESS_PLANT_PAPER`: screw press, 150 units of slurry glob
  with reaction class `PAPER_SLURRY`, producing 1 SHEET, skill
  PAPERMAKING.
- `MAKE_SHEET_FROM_PLANT`: farmer's workshop, 1 papyrus sedge
  plant with reaction class `PAPER_PLANT`, producing 1 SHEET
  and 1 seed, skill PAPERMAKING. Papyrus skips the slurry step.

The paper plants, from the Sheet page, cross-checked against
the raws (`PRESS_PAPER_MAT` on the thread material): cotton,
flax, hemp, jute, kenaf, pig tail, ramie, rope reed. Pig tail
and rope reed are the fort's own crops: pig tail underground,
rope reed above ground. Parchment is the third sheet route
(hide plus milk of lime at a tanner's shop, value 50) and
belongs to CLOTHING.md's leather chain, not to this doc.
Sheets are stored under the Sheet stockpile category, base
value 5, and are used to make scrolls and books (quires). The
wiki notes sheet quality levels do not seem to affect the value
of resulting books, with a verify tag; that claim is
wiki-uncertain and UNVERIFIED live (open question 10).

Paper is the lowest priority product in this doc. It serves no
survival need. It matters only once the fort has a library and
scholars, which is later work. The phases put it last.

## 4. The soap chain

Soap is made at the soap maker's workshop, the other
raw-defined workshop in `building_custom.txt`: 3x3,
`[BUILD_LABOR:SOAP_MAKER]`, build items 1 bucket and 1 stone
material. The reactions, from `reaction_other.txt`:

- `MAKE_SOAP_FROM_TALLOW`: soap maker CUSTOM_T, 150 lye
  (LIQUID_MISC, material LYE) in a container plus 150 tallow
  (GLOB, reaction class TALLOW) with `SOAP_MAT`, producing 1
  BAR of soap with dimension 150, skill SOAP_MAKING.
- `MAKE_SOAP_FROM_OIL`: soap maker CUSTOM_O, 150 lye plus 150
  oil (LIQUID_MISC) with `SOAP_MAT`, producing 1 BAR of soap
  with dimension 150, skill SOAP_MAKING.

The lye chain: cut a tree, turn one log into ash at a wood
furnace (`MakeAsh`, a live job type in the enum), turn that ash
into lye at an ashery (`MakeLye`, also a live job type). The
ashery is a furnace, not a workshop; the live furnace enum holds
it under the `Custom` furnace type, the same way the workshop
enum holds the raw-defined workshops under `Custom`. Whether the
ashery reads back as a distinct furnace in the collect is
UNVERIFIED (open question 9 covers the Custom distinction for
workshops; the furnace side needs the same probe). Lye is a liquid stored in barrels. The yields at each
step (ash per log, lye per ash bar) are UNVERIFIED live (open
question 7). Potash shares the ash supply: `MakePotashFromAsh`
and `MakePotashFromLye` are live job types, and FARMING_PLAN
section 8 already notes potash is also used for soap and for
clear glass. Ash is the contested input: fertilizer, soap, and
glass all draw on it.

A bar of soap starts with 150 units, and cleaning jobs consume
varying quantities before the bar is used up. Soap is stored in
Bar/Block stockpiles with the soap option enabled. Soap is for
personal cleaning (happy thought "recently took a soapy bath")
and for cleaning wounds in hospitals, preventing infections.
The wiki says soap is not traded in caravans: the fort has to
make it itself. That claim is wiki-sourced and UNVERIFIED live
(open question 8), but the plan does not depend on it: the fort
makes its own soap either way.

Soap is the reason the oil chain matters beyond cooking. A fort
with no animals to butcher has no tallow, and its only soap
route is oil: quarry bush seeds milled to paste, pressed to
oil, combined with lye. That chain is four workshops long
(farm, quern, screw press, ashery, soap maker: five, counting
the farm), and every link must exist before one bar of soap
exists.

## 5. What the fort needs and when

### 5.1 The floors

The milling and pressing floors are per fort, from the fresh
citizen count and the fresh stocks, so they move when migrants
arrive:

- **Flour:** enough flour on hand to cook the kitchen's meals.
  The kitchen needs solid ingredients, and flour is the
  reliable solid the farm grows on purpose. The floor is 5
  flour per citizen, held as a standing stock. Below it, mill
  cave wheat (or longland grass) until the floor is met.
- **Sugar:** 2 per citizen, for cooking variety. Sweet pods
  mill into sugar, but they also brew into dwarven rum and
  process into syrup at the farmer's workshop. The split rule
  decides; sugar is the smallest claim.
- **Dye:** 0 as a floor. Dye is a value play, never a need.
  Mill dimple cups only from surplus, never from the seed
  reserve, and never before the fort has cloth to dye.
- **Oil:** 1 jug per 10 citizens, held for soap, plus cooking
  use from surplus. Oil below the soap floor is never cooked.
- **Paste:** 0 held. Paste is an intermediate, not a stock.
  Mill seeds to paste only when the press is ready to press
  them, or the paste sits in the stockpile doing nothing.
- **Soap:** 1 bar per 10 citizens, held for the hospital, plus
  1 bar in use. A fort with wounded dwarves and 0 soap is a
  hospital problem, and it is an attention item (section 12).
- **Slurry and sheets:** 0 as a floor. Paper is made to order
  for the library, never stockpiled ahead of it.

The floors are targets, not tripwires: the harness works
toward them every season and treats anything below them as a
standing need, not an emergency. A fort with 0 flour and cave
wheat on hand is a stuck chain, and the snapshot names the
missing link.

### 5.2 How much milling per season

Milling is one plant per job, one powder per plant. The
arithmetic the harness does, per season, from fresh state:

1. Citizens times 5, minus flour on hand, equals the flour to
   mill.
2. Flour to mill, minus cave wheat (and longland grass) on hand,
   equals the wheat to grow, which is the farming plan's claim,
   not this doc's.
3. Oil to press, minus paste on hand, equals the seeds to mill
   to paste; seeds to mill, minus oil-plant seeds on hand,
   equals the quarry bushes to grow.
4. Soap to make, minus lye and tallow or oil on hand, equals the
   ash to burn and the animals to butcher or the seeds to press.

Each step names its input, so the agent sees "need 12 flour:
0 on hand, 9 cave wheat, no quern" instead of "need flour".

## 6. The split rule: what a harvest becomes

The farming plan's split rule (FARMING_PLAN.md section 10.1)
decides what every harvested stack becomes, in priority order:
brew to the drink floor, process for industry, eat raw, cook,
trade. This document owns step 2 for the milling and pressing
products, and it owns the claims inside that step. The claims,
in order:

1. **Brew first.** A brewable plant is brewed until the drink
   floor is met. Milling never takes a plant the still needs
   for the drink floor. Cave wheat brews into dwarven beer and
   mills into flour; the still's claim comes first.
2. **Flour second.** Cave wheat and longland grass mill into
   flour up to the flour floor (section 5.1). Flour is the
   kitchen's solid ingredient, and the kitchen cannot cook
   without solids.
3. **Oil third.** Quarry bush seeds mill to paste and press to
   oil up to the oil floor, because oil is the soap route for a
   fort with no tallow. Flax, hemp, cotton, and kenaf seeds are
   surface crops; their oil claim waits until the fort grows
   them.
4. **Sugar fourth.** Sweet pods mill into sugar up to the sugar
   floor, after the syrup claim at the farmer's workshop is
   met. Sugar and syrup share the sweet pod; the farmer's
   workshop takes its share first, because syrup is also a
   drink and a cooking liquid.
5. **Dye last.** Dimple cups mill into dye only from surplus,
   never from the seed reserve, and never before the fort has
   cloth to dye.
6. **Paper never from the food chain.** Pig tail and rope reed
   are thread crops first (CLOTHING.md). Slurry claims them
   only from surplus thread stock, never from the thread the
   loom needs.

Milling returns the seed, so milling is seed-safe the way
brewing is: the seed comes back and the crop can be replanted.
Cooking destroys the seed. That is why milling sits above
cooking in the split rule and why the kitchen never cooks a
millable plant the mill needs.

## 7. What the harness knows today

Verified against the repo on 2026-11-27. The daemon and the
game were down for a VM replacement at the time, so every live
value below is from the last live runs and the code, not from a
fresh live read. Anything the harness cannot do yet is named
here so the plan does not pretend otherwise.

### 7.1 What exists and works

- **Workshop listing.** `buildings.lua` reports the workshop
  subtype from `df.workshop_type`, so a quern, millstone, or
  Custom workshop that exists will appear in the Buildings
  section. The 2026-11-27 snapshot reads no milling workshop
  in the fort: no quern, no millstone, no screw press, no soap
  maker, no ashery.
- **Reaction probing.** The brew reaction was probed live as
  index 44 (`df.reaction.find(44) == BREW_DRINK_FROM_PLANT`,
  actions.py). The same probe route exists for the press, soap,
  slurry, and paste reactions; only the indices are unknown.
- **The tan precedent.** CLOTHING.md already established the
  pattern for queuing a reaction job: CustomReaction (job type
  211) plus the reaction name, the same way brewing is queued.
  The press and soap reactions queue the same way.
- **Labor names.** The live labor enum holds MILLER, PRESSING,
  PAPERMAKING, SOAP_MAKER, MECHANIC, LYE_MAKING, and
  POTASH_MAKING. `labor_toggle` can enable any of them, and
  `units.lua` reads labors and skills per citizen, so the labor
  half of the chain is already actuatable.
- **Job types.** The live job enum (241 types) holds
  MillPlants, ConstructQuern, ConstructMillstone, MakeAsh,
  MakeLye, MakePotashFromAsh, and MakePotashFromLye. The raw
  job types for the chain exist in the game; the harness has
  not wired any of them up. There is no PressOil, MakeSoap, or
  MakeSlurry job type: those are reactions, queued as
  CustomReaction.
- **Catalog introspection.** `catalog.py` builds each action's
  plain-words `about` and `needs` text from the action table,
  so new milling and pressing actions get catalog entries
  automatically and cannot drift from the code.
- **Bags and jugs.** `stocks.lua` counts buckets, bins, and
  barrels. Bags and jugs are counted in the `by_type` table and
  the `items` list, but nothing surfaces them as headline
  numbers, which phase 1 fixes.
- **The stoneworking link.** STONEWORKING.md owns making the
  quern and millstone items at the mason's workshop, and its
  phase 2 live bar already includes "a quern is made and placed
  and mills flour". The mason side of this chain is specified
  there, not here.

### 7.2 What is missing (verified gaps)

- **No milling or pressing workshop can be built.**
  `WORKSHOP_CATALOG` in `actions.py` holds exactly four
  workshops: carpenter, mason, still, kitchen. There is no
  quern, millstone, screw press, soap maker, ashery, or wood
  furnace. `build_workshop` refuses any kind not in the
  catalog. The harness cannot build any workshop in this
  industry.
- **No milling or pressing job can be queued.** `JOB_SPECS`
  holds brew, brew_fruit, cook, and eight carpenter furniture
  jobs. There is no mill plants, mill paste, mash slurry, press
  oil, press fruit, press honeycomb, press paper, make soap,
  make lye, make ash, or make potash job. `queue_job` cannot
  queue any job in the chain.
- **No milling or pressing task exists.** `TASK_DEFS` in
  `daemon.py` holds exactly six composed tasks (brew, cook,
  make_bed, make_barrel, gather, farm). None is milling or
  pressing. The multi-step chains (mill seeds, then press oil;
  mash slurry, then press paper; burn ash, make lye, make soap)
  are inexpressible in the current task framework; that
  framework gap is a P0 in gap review 3, and the milling work
  waits on it rather than working around it, the same way
  CLOTHING.md does.
- **No powder, oil, paste, or soap counts.** `stocks.lua`
  `by_material` covers DRINK, FOOD, MEAT, FISH, PLANT, SEEDS,
  BAR, WOOD, CLOTH, and THREAD only. POWDER_MISC (flour,
  sugar, dye), LIQUID_MISC (oil, lye, honey), GLOB (paste,
  slurry, press cake, tallow), and SHEET are counted in the
  `by_type` table and the `items` list, but nothing surfaces
  them: no headline numbers, no material breakdown. The harness
  cannot currently answer "how much flour do we have", "how
  much oil", or "how much soap". KITCHEN.md section 4.2 already
  flags this gap for flour, sugar, dye, milk, syrup, honey,
  oil, and tallow. Phase 1 here closes it for the milling and
  pressing products.
- **No empty-bag or empty-jug counts.** The mill fail-fast
  needs empty bags and the press fail-fast needs empty jugs.
  Neither is a headline number today.
- **No planner coverage.** `planner.py` has no milling or
  pressing thresholds and no milling decisions. Nothing mills
  flour when the kitchen is short of solids, nothing presses
  oil when soap is at 0.
- **No attention kinds.** `attention.py` has no milling kinds:
  no missing quern with millable plants on hand, no soap at 0
  with a wounded dwarf, no millstone without power.
- **No briefing.** `briefings.py` has no milling briefing kind.
- **No labor floors.** `docs/LABOR.md` sets floors for brewer,
  planter, cook, miner, woodcutter, carpenter, mason, haulers,
  and medical, but none for miller, presser, papermaker, soap
  maker, mechanic, lye maker, or potash maker. The labor system
  cannot cover a labor it has no floor for.
- **No Custom workshop distinction.** `buildings.lua` reports
  the workshop subtype, and both raw-defined workshops share
  the `Custom` subtype. How a screw press is told apart from a
  soap maker's workshop in the collect is UNVERIFIED (open
  question 9). Phase 3 must answer it before either workshop
  can be built and read back reliably.

### 7.3 The plant-choice problem

This is the hardest harness problem in the industry, and it
decides the design of phases 2 and 4. In 0.47.05, a MillPlants
job does not take a plant parameter through `queue_job`: the
action takes a job name and a count, and nothing else. The
game's own routes for choosing the plant are the job detail in
the UI, a manager work order, or a give-to stockpile linkage
(section 2.1). The harness has three candidate routes, in
order of preference:

1. **Give-to stockpile linkage.** A small stockpile holding
   only the target plant, set to give to the quern, plus a
   bags-only furniture stockpile also giving to the quern. The
   miller can then only reach the target plant and an empty
   bag. This is the wiki's own route, and it needs the
   stockpile machinery (`create_stockpile`) plus a give-to
   link the harness does not have yet. Whether the give-to link
   is writable from Lua is UNVERIFIED (open question 1).
2. **Manager orders.** `manager_order_create` exists in the
   harness. A manager order for "Mill plants" with a material
   condition names the plant. Whether manager orders carry a
   material condition the harness can set, and whether the
   order runs at a quern, is UNVERIFIED (open question 1).
3. **Job struct field.** The MillPlants job struct may carry a
   material or reagent field the harness can set when queueing
   through `act_job.lua`. Whether that field exists and is
   writable is UNVERIFIED (open question 1).

Phase 2 probes all three. Until one of them proves out, the
harness mills only when one millable plant is on hand, and
says so. It never queues a mill job while two millable plants
are on hand and the choice is uncontrolled, because the miller
will pick the closest random plant and the wrong one may be the
seed reserve.

## 8. Workshops and layout

Layout is scored placement (docs/SITE_SELECTION.md, queued
work), with milling-specific factors on top of the shared
threat, cover, and traffic factors:

- **The processing cluster.** Quern, screw press, ashery, soap
  maker's workshop, kitchen, still, and farmer's workshop
  belong together, within a few tiles of each other. Flour,
  sugar, and oil are kitchen inputs; leaves and syrup come from
  the farmer's workshop next door; lye and soap serve the
  hospital nearby. A quern far from its plant stockpile pays
  the hauling cost on every mill job.
- **The millstone apart.** A millstone needs power, so it sits
  where the power train reaches it: under a windmill on the
  surface, or beside a water wheel. It does not sit in the
  processing cluster unless the power train reaches there.
  Power is machinery work; the millstone placement waits on it.
- **The quern feed stockpile.** A small stockpile holding only
  the target mill plant, set to give to the quern, plus a
  bags-only furniture stockpile giving to the quern (section
  7.3). One quern per plant the fort mills regularly, or one
  quern whose feed stockpile is switched between plants. The
  fort starts with one quern and switches the feed; it adds a
  second quern only when switching costs more miller time than
  a second quern costs in space and stone.
- **The press feed.** Paste and jugs near the screw press. An
  empty jug is a press job's binding constraint the way an
  empty barrel binds brewing, so the jug stockpile sits beside
  the press, not across the fort.
- **The soap cluster.** Ashery beside the wood furnace (ash
  moves one step), soap maker beside the ashery (lye moves one
  step), soap stockpile beside the hospital (soap moves one
  step to the wounded). The ash stockpile is the shared input
  for fertilizer, soap, and glass, and it sits where all three
  can reach it.

## 9. Stockpiles and storage

- **Powder stockpile.** Food category, powder only (flour,
  sugar, dye), bags in barrels. Powder must be in a bag; a
  barrel holds up to 60 dye bags (CLOTHING.md section 10.1).
  Near the kitchen, so the cook reaches flour without a long
  haul. Cooks prefer ingredients stored in containers, and
  flour in barrels is the case the wiki names (Bug 7546).
- **Paste stockpile.** Food category, Paste only, near the
  quern and the screw press. Paste is an intermediate: it is
  milled only when the press is ready, so this stockpile is
  small on purpose.
- **Oil and jug stockpile.** Food category, liquid only, jugs
  near the screw press. Empty jugs live here too, so the press
  never waits on a jug from across the fort.
- **Soap stockpile.** Bars/Blocks category, soap enabled, near
  the hospital. Soap is a bar; the Bars/Blocks row in
  STOCKPILES.md already lists soap. Bins allowed.
- **Sheet stockpile.** Sheet category, near the library (when
  one exists). Sheets are value 5 and do not rot.
- **Mill feed stockpile.** The plant-choice stockpile from
  section 7.3: one plant type only, set to give to the quern,
  beside the quern. The seed stockpile stays with the farms
  (FARMING_PLAN.md section 5.3); the mill feed is a working
  stockpile, not the seed store, and it never holds seeds the
  fort needs for planting.

What rots and what does not: flour, sugar, dye, paste, oil,
soap, sheets, and press cakes do not rot. Seeds do not rot.
The plants waiting to be milled wither instead of rotting, so
an unmilled harvest is a timer, not a stockpile problem: mill
it before it withers, or brew it and let the mill wait.

## 10. Labor

The milling and pressing labors, from the live enum (section
7.1): MILLER (milling), PRESSING (pressing), PAPERMAKING
(papermaking), SOAP_MAKER (soap making), MECHANIC (mechanic,
builds the screw press and the millstone), LYE_MAKING (lye
making), POTASH_MAKING (potash making). The labor plan
(docs/LABOR.md) owns the assignment machinery; this section
sets the floors it must cover.

Proposed floors for a 7-citizen fort, to be tuned live in phase
8, not taken as wiki fact:

| Labor | Floor | Why |
| --- | --- | --- |
| MILLER | 1, rises to 1 when millable plants are on hand | No millable plants, no miller; plants without a miller wither unmilled |
| PRESSING | 0, rises to 1 when paste or fruit is on hand | No paste, no presser; paste without a presser is a stuck chain |
| PAPERMAKING | 0, rises to 1 when the library exists | Paper serves no survival need; no library, no papermaker |
| SOAP_MAKER | 0, rises to 1 when lye and tallow or oil are on hand | No lye, no soap maker; lye without a soap maker is a stuck chain |
| MECHANIC | 1 when a screw press or millstone is planned | The press and the millstone are both built by a mechanic |
| LYE_MAKING | 0, rises to 1 when ash is on hand | Ash without a lye maker is a stuck chain |
| POTASH_MAKING | 0, rises to 1 when the farming plan calls for fertilizer | Shared with the fertilizer chain; the split rule decides |

Floors scale with population: each production labor gains a
second dwarf when its waiting job list stays non-empty across
two ticks. A floor is a minimum, not a target; the harness
never assigns a dwarf to a labor with no waiting work just to
fill a number.

Skill matters once: milling has no quality output, so miller
skill sets speed only. Pressing has no quality output except
paper sheets, so presser skill sets speed only. Soap making
and papermaking set quality on soap and sheets, so skill sets
value there. The miller is not also the planter or the brewer;
the milling plan refuses an assignment that would leave the
farm or the still without a worker.

## 11. Trade

Milled and pressed goods are trade goods second, fort inputs
first. Nothing is sold while the fort is below its floors.

- **Flour and sugar:** sold only from surplus above the flour
  and sugar floors. A caravan pays for powder the fort milled
  from a crop it grew for free.
- **Oil:** sold only from surplus above the soap floor. Oil
  below the soap floor is never traded, because the fort cannot
  buy soap back: the wiki says caravans do not trade soap.
- **Dye:** sold as powder or as dyed cloth (CLOTHING.md
  section 12). Dye powder is value 10 to 20 per unit and
  weighs nothing in a bag.
- **Soap:** never sold while the hospital is below its floor.
  Soap is the one product in this industry the fort cannot
  replace by trade, so it is the last thing sold, if ever.
- **Sheets:** sold only once the library is stocked. Paper the
  library needs is not trade stock.
- **Press cakes:** sold as filler food from surplus. They are
  worth 1 each and the fort makes them as a byproduct, so any
  sale is free value.

The trading plan (docs/TRADING.md) already lists lye and
tallow soap among the goods the fort makes; this doc sets the
floors that decide when they may leave the fort.

## 12. How the information reaches the AI

This is the part Mikey asked for explicitly: the information
must be fed to the AI optimally. The rules are the same as the
snapshot's rules everywhere else in the harness: counts and
exceptions, never a dump; named options with a one-line why;
full detail behind a query route.

### 12.1 The snapshot's Milling section

The per-tick snapshot gains a short Milling section, built from
the fresh collect, in plain words:

```
Milling: flour 12 (cave wheat), sugar 0, dye 2 (dimple), oil 0, paste 0, soap 0.
  Shops: quern 0, millstone 0, screw press 0, soap maker 0, ashery 0.
  Need: quern (9 cave wheat, 0 flour). Bags 4, jugs 0.
```

What is in it, and what is not:

- **In it:** flour, sugar, dye (top 1 material each), oil,
  paste, and soap counts; which milling workshops exist; the
  one most urgent milling need, with the numbers that prove it;
  empty bag and empty jug counts, because they bind the mill
  and the press.
- **Not in it:** the full per-material powder breakdown, the
  per-plant millable list, the reaction indices, the power
  train layout, or the soap chain detail. Those live behind
  GET /v1/milling.
- **Never in it:** a raw dump of the stocks section, a list of
  every powder stack, or a number without its unit and its
  floor. A number without its floor is a number the agent
  cannot act on.
- **When nothing is wrong:** the section diffs to a one-liner
  (section 13).

### 12.2 The query route

GET /v1/milling returns the full detail: per-material powder,
oil, paste, slurry, press cake, and soap counts with units;
millable plants on hand by type with their seed reserves; the
workshop list with job counts; the labor coverage for the
milling labors; the ash, lye, and jug ledgers; the mill feed
stockpile linkage state. It reads from the fresh collect, not
from a cache. The snapshot carries the summary; the route
carries the detail. The agent asks the route when it needs to
choose, never as a matter of routine.

### 12.3 Named options

The planner's milling and pressing decisions carry the option
in the decision itself:

- "Build a quern at (x, y, z): 9 cave wheat on hand, 0 flour,
  kitchen short of solids."
- "Mill 5 cave wheat flour at the quern (9 wheat, 4 empty bags,
  flour floor 35)."
- "Mill 3 rock nut seeds to paste at the quern (paste 0, oil 0,
  soap floor 1 bar)."
- "Press 1 oil at the screw press (150 paste, 1 empty jug,
  soap floor unmet)."
- "Cannot mill: 0 empty bags. Make bags at the clothier or
  trade for cloth."

The suggestion names the exact tool and parameters, as
everywhere else in the harness. When nothing can be milled and
no workshop exists, the milling section says so and names the
fix (build, gather, make bags, trade), instead of going silent.

### 12.4 Attention and briefing

Three new attention kinds, all P2 unless a dwarf is wounded
and soap is at 0 (P1):

- **No mill, plants on hand:** millable plants are on hand and
  no quern or millstone exists. P2. Briefing kind `milling`:
  what this is (plants the fort cannot use), what usually
  matters (the kitchen is short of solids, the plants wither),
  options (build a quern, brew the plants instead), cost of
  ignoring (withered harvest, no flour).
- **Soap at 0, wounded dwarf:** a citizen is wounded and the
  fort holds 0 soap. P1. Same briefing kind, with the soap
  chain named (ash, lye, tallow or oil) and the missing link
  named.
- **Millstone without power:** a millstone exists and has no
  power. P2. Same briefing kind, with the power fix named
  (windmill, water wheel) and the quern fallback named.

The briefing is a few hundred tokens at most (briefings.py
rule), and it fires only on the event tick, never per tick. It
never fires when the chain is green.

### 12.5 Opportunities

The opportunities section (docs/HARNESS_ROLE.md, section 7(e))
carries at most 3 milling entries, each one sentence of fact
plus the query route, never a suggestion, never an action named,
no penalty for ignoring:

- "The fort holds 9 cave wheat and 0 flour (query /v1/milling)."
- "150 rock nut paste sits unpressed and the fort holds 0 soap
  (query /v1/milling)."
- "A millstone exists with no power; the quern still mills
  (query /v1/milling)."

If there are more than 3 opportunities, the harness picks the 3
with the most concrete facts and drops the rest, and the full
list is behind GET /v1/milling.

## 13. Model presentation

This section is required by the 2026-11-27 presentation
constraint, and it states exactly what the model is shown, what
it costs, and what is deliberately withheld. The snapshot stays
an index; the budgets hold. The harness never chooses the
strategy for the model: it shows the counts, the floors, and
the named options with a one-line why each, and the model
picks. Flour versus sugar versus oil is the model's choice
among options, never the harness's default.

### 13.1 Snapshot lines and token cost

The Milling section is 3 lines when fully rendered, 1 line when
diffed unchanged. The exact example lines from section 12.1,
measured by the accountant's rule (3 chars per token,
conservative) and the wire rule (4 chars per token):

- **7 dwarves, full render:** 3 lines, 205 chars, 69
  accountant tokens, 52 wire tokens. The lines are the stocks
  line (flour, sugar, dye, oil, paste, soap), the shops line
  (which milling workshops exist), and the need line (the one
  most urgent need, with bag and jug counts).
- **7 dwarves, unchanged:** 1 line, "Milling: unchanged
  (flour 12, sugar 0, oil 0, soap 0).", 54 chars, 18
  accountant tokens, 14 wire tokens. This is the steady state:
  the section costs almost nothing on most ticks, because the
  diffing rule renders an unchanged section as a one-liner
  (assembler.py).
- **50 dwarves, full render:** 3 lines, 211 chars, 71
  accountant tokens, 53 wire tokens. The lines do not grow
  with population: the stocks line still names the top 1
  material per powder, the need line still names one need, and
  the shops line is fixed. The only growth is longer counts
  ("flour 48", "50 citizens") and a second workshop in the
  shops line.
- **50 dwarves, unchanged:** 1 line, "Milling: unchanged
  (flour 48, sugar 6, oil 3, soap 4).", 54 chars, 18
  accountant tokens, 14 wire tokens.

Against the measured baseline (M1 run 2026-11-27, 7 citizens:
snapshot 10,693 chars, about 3,564 accountant tokens, about
2,673 wire tokens), the Milling section adds about 1.9 percent
at 7 dwarves when fully rendered, and about 0.5 percent when
diffed. At 50 dwarves the Units section is the one that grows
(about 1,007 chars at 7 citizens, roughly 7,000 before
diffing), and the Milling section stays flat by design. The
snapshot budget is target 30K tokens, warning 60K, never over
140K (assembler.py); the Milling section is about 0.23 percent
of the target at full render, and it is cuttable: its cut
priority is below attention, threats, and failure feedback,
which are never dropped, and its cut form is the one-liner.

### 13.2 Query route and cost

GET /v1/milling, on demand only, never per tick. At 7 dwarves
the full detail is about 1,400 chars, about 470 accountant
tokens: per-material powder, oil, paste, slurry, and soap
counts, millable plants on hand with seed reserves, workshops,
labor coverage, the ash, lye, and jug ledgers, and the mill
feed linkage state. At 50 dwarves it is about 2,000 chars,
about 670 accountant tokens, because the millable-plant table
grows with the crops on hand, not with the population. The
route is the only place the per-material table exists in
model-facing text. The agent asks it when the snapshot names a
gap it wants to understand, and the retrieval cap (4K tokens
per decision, assembler.py) covers it at either population.

### 13.3 Briefing trigger and cost

The `milling` briefing (section 12.4) fires only when an
attention item of kind no-mill-with-plants, soap-zero-wounded,
or millstone-without-power is raised, and it rides on that
attention item for one tick. Its text is 5 short fields (what,
matters, options, cost, wiki), about 550 chars, about 185
accountant tokens. It never fires per tick, and it never fires
when the chain is green. A fort with no milling problem pays
nothing for the briefing.

### 13.4 Opportunities entries

At most 3, one sentence of fact plus the query route each
(section 12.5), about 70 chars each, about 25 accountant
tokens each, 75 at most for the whole block. They are facts the
agent may act on or ignore, and ignoring one costs nothing: no
score component, no attention escalation, no diary note.

### 13.5 What this doc deliberately does NOT push to the model

- The full millable plant table. The snapshot names the top 1
  material per powder; the 30-plus millable plants live behind
  GET /v1/milling.
- The per-stack powder, paste, and oil table. The snapshot
  carries counts; the stacks are query detail.
- The reaction indices. The snapshot never shows a reaction
  number; the probe results live in the doc and the code.
- The power train layout. The snapshot says the millstone has
  no power; the windmill and axle plan lives in the machinery
  work.
- The soap chain detail. The snapshot carries soap, lye, and
  ash counts; the step-by-step chain lives behind the route.
- The paper and sheet detail. The snapshot carries a sheet
  count when the library exists; the slurry and paper plant
  table is query detail.
- The mill-plant choice mechanics. The snapshot names the feed
  stockpile state ("feed: cave wheat"); the linkage rules live
  in this doc.
- The farming detail for millable and oil crops. Seasons, plot
  sizes, and the split rule live in docs/FARMING_PLAN.md; the
  snapshot carries the plant count and the claim, not the plan.
- The kitchen detail for flour, sugar, and oil as ingredients.
  That lives in docs/KITCHEN.md; the snapshot carries the
  flour count and the floor, not the meal plan.
- The dyeing detail. That lives in docs/CLOTHING.md; the
  snapshot carries the dye count, not the dyeing plan.

## 14. Implementation phases

Each phase ends with a concrete live-verification bar. Nothing
counts as done until it passes its bar against the real game.
This doc is design-complete when written; it is proven only
when its UNVERIFIED marks are cleared live.

1. **Observation.** Extend the stocks collect so the snapshot
   can see what milling needs: powder counts by material
   (POWDER_MISC: flour, sugar, dye), oil and lye counts
   (LIQUID_MISC), paste, slurry, and press cake counts (GLOB),
   sheet counts (SHEET), soap counts (BAR by material), empty
   bag and empty jug counts. Add the Milling section to the
   snapshot and GET /v1/milling. Bar: a live collect on the
   main fort shows the flour, oil, and soap the fort actually
   has, and the snapshot text names them; a hand check of three
   named stocks matches the collect.
2. **Reaction and job-type probe.** Probe the live reaction
   indices for MILL_SEEDS_NUTS_TO_PASTE, PRESS_OIL,
   PRESS_OIL_FRUIT, PRESS_HONEYCOMB, PRESS_PLANT_PAPER,
   MAKE_SLURRY_FROM_PLANT, MAKE_SHEET_FROM_PLANT,
   MAKE_SOAP_FROM_TALLOW, and MAKE_SOAP_FROM_OIL, the same way
   the brew reaction was probed as index 44. Probe the
   MillPlants job struct on a live job: which fields carry the
   plant choice, whether the job consumes a whole stack or one
   plant, how many seeds it returns, and how big a paste glob
   one seed makes. Probe ConstructQuern and ConstructMillstone
   for which workshop offers them. Bar: the probe names every
   reaction index and every job field with a live job id, and
   the doc records the answers. If a job cannot be steered by
   any route, the plan adapts per section 7.3 and never claims
   otherwise.
3. **Workshops.** Extend WORKSHOP_CATALOG with quern,
   millstone, screw press, soap maker, ashery, and wood
   furnace, from the live workshop and furnace enums (25
   workshop types, 8 furnace types, verified). Solve the
   Custom subtype problem: a screw press must read back as a
   screw press and a soap maker as a soap maker, by custom
   building type id or another field the probe finds. The
   quern and millstone items come from the mason (STONEWORKING
   phase 2); a millstone placed with no power is flagged in the
   result, not silently built. Bar: each workshop builds live
   on the scratch fort and reads back in the Buildings section
   with its correct subtype or custom type; the screw press and
   the soap maker read back as different buildings.
4. **Mill jobs and plant choice.** Add JOB_SPECS entries for
   mill plants (MillPlants, job type from the live enum), mill
   paste (CustomReaction plus MILL_SEEDS_NUTS_TO_PASTE), and
   mash slurry (CustomReaction plus MAKE_SLURRY_FROM_PLANT),
   each with a fail-fast floor (millable plant on hand, empty
   bag on hand). Build the plant-choice control from whichever
   route phase 2 proved: give-to stockpile linkage, manager
   order, or job struct field. Bar: each job completes live and
   its product reads back in stocks; a job queued without its
   input is refused with the missing input named; a mill job
   queued while two millable plants are on hand mills the
   target plant and no other, proved by the product read-back.
5. **Press jobs.** Add JOB_SPECS entries for press oil
   (PRESS_OIL), press fruit (PRESS_OIL_FRUIT), press honeycomb
   (PRESS_HONEYCOMB), and press paper (PRESS_PLANT_PAPER), each
   with a fail-fast floor (150 paste units or 1 fruit or 1
   honeycomb, plus 1 empty jug). Bar: each job completes live
   and its product reads back in stocks (oil in a jug, press
   cake, honey, wax cake, sheet); a press queued without an
   empty jug is refused with the jug named; the honeycomb bug
   is proved live or disproved live, and the doc records which.
6. **Soap chain.** Add JOB_SPECS entries for make ash
   (MakeAsh at the wood furnace), make lye (MakeLye at the
   ashery), make potash (MakePotashFromAsh, MakePotashFromLye),
   make soap from tallow (MAKE_SOAP_FROM_TALLOW), and make soap
   from oil (MAKE_SOAP_FROM_OIL), each with a fail-fast floor
   (log, ash, lye, tallow or oil). Implement the soap reserve
   (section 5.1) and the tallow refusal: never cook tallow below
   the soap floor. Bar: one bar of soap is made live from
   tallow and one from oil, each reading back as a BAR with a
   soap material; the ash, lye, and tallow stocks are read back
   at each step; a cook job that would spend tallow below the
   soap floor is refused with the floor named.
7. **Planner and split rule.** Implement the floors (section
   5.1), the per-season arithmetic (section 5.2), and the
   milling claims inside the farming plan's split rule (section
   6). The planner mills flour when the kitchen is short of
   solids, presses oil when soap is below its floor, and makes
   soap when the hospital needs it. Bar: a live M1 day mills
   flour when cave wheat is on hand and flour is at 0, presses
   oil when paste is on hand and soap is at 0, and never mills
   a plant the still needs for the drink floor.
8. **Labor and stockpiles.** Add the floors in section 10 to
   the labor system, wire `labor_toggle` to assign them, and
   build the stockpiles in section 9 (powder, paste, oil and
   jugs, soap, mill feed). Bar: the assigned miller is the
   highest-skill dwarf with the milling labor, verified by
   read-back, and is observed milling within the same run; the
   mill feed stockpile holds only its target plant and the
   quern draws from it.
9. **Paper, attention, and briefing.** Add the paper jobs to
   the planner only when a library exists (slurry, then press
   paper), wire the attention kinds and the `milling` briefing
   from section 12.4, and add the opportunities entries from
   section 12.5. Bar: one sheet is pressed live from slurry
   and reads back; the no-mill attention fires once on the
   event tick with the missing workshop named, and the briefing
   fires once and never again while the problem stands.
10. **Failure-mode hardening.** Every row of the table in
    section 15 demonstrated, live or in a controlled test, with
    the diagnosis naming the fix. Bar: each failure mode
    produces the documented diagnosis in the run log, and no
    failure mode produces a silent zero.

Every phase carries offline tests (including malformed-input
tests per the standing rule) and goes through the pre-push
self-review gate before it is committed and pushed.

## 15. Failure modes

Every failure mode in this table has a diagnosis the harness
must produce, with the fix named. A silent zero is never
acceptable.

| Failure | Cause | Diagnosis | Fix |
| --- | --- | --- | --- |
| No flour, wheat on hand | No quern built | "9 cave wheat, 0 flour, no quern" | Build a quern |
| Wrong plant milled | Miller picked the closest random plant | "milled X, wanted Y" | Feed stockpile linkage; mill only one millable plant at a time |
| Mill job cancelled | No empty bag | "0 empty bags" | Make bags at the clothier or trade for cloth |
| Millstone idle | No power | "millstone, 0 power" | Build a windmill or water wheel; fall back to the quern |
| Millstone jobs lost | Power interrupted | "jobs re-queue after power returns" | Re-queue the jobs; keep power uninterrupted |
| Paste never pressed | No screw press, or no jugs | "150 paste, 0 press" or "0 empty jugs" | Build a press; make jugs at the kiln or craftsdwarf |
| Oil never made | Seeds cooked or brewed away | "0 oil seeds, cooked" | Mill seeds to paste before cooking; protect the oil claim |
| Soap never made | No lye, or no tallow or oil | "0 lye" or "0 tallow, 0 oil" | Burn ash, make lye; butcher for tallow or press for oil |
| Tallow cooked away | Kitchen cooked the soap input | "tallow cooked, soap floor breached" | Refuse to cook tallow below the soap floor |
| Ash spent on fertilizer | Potash chain took the ash | "ash 0, potash made N" | Reserve ash for soap before fertilizing |
| Powder lost | Powder dumped from its bag | "powder dumped, unrecoverable" | Never dump powder; keep bags in barrels |
| Mixed bag | Two mill products in one bag (Bug 4371) | "bag holds X and Y" | Mill one plant per quern per batch |
| Honeycomb job refused | Press will not take the job directly | "press honeycomb not offered" | Queue through the manager interface |
| Millstone cannot be built | Powered from below, or no standing room | "millstone hanging, cannot complete" | Power from above or the side |
| Screw press confused with soap maker | Both share the Custom subtype | "Custom workshop, type unknown" | Read the custom building type id, not the subtype |
| Plants wither unmilled | No miller, or miller busy elsewhere | "ripe plants, no mill job taken" | Assign a miller; check the labor is enabled |
| Press cake piling up | Pressed often, cooked never | "N press cakes, 0 cooked" | Cook press cakes as filler, or stop pressing past the oil floor |

Two failure modes the wiki does not document as game mechanics,
and the plan does not invent: there is no mill breakdown or wear
mechanic in the milling pages, and there is no flour spoilage
(flour does not rot). If a future live run shows a mill job
failing in a way that matches neither a missing input nor a
missing workshop, that is a new finding to investigate, not a
breakdown to assume. UNVERIFIED: whether any hidden mill failure
mechanic exists beyond the documented ones.

## 16. Refusals

The milling and pressing system refuses, and says why, in plain
words:

- Never mill a plant the still needs to meet the drink floor.
- Never mill a crop at or below its seed reserve, and never mill
  the last seeds of an oil crop the fort needs for planting.
- Never queue a mill job while two millable plants are on hand
  and the plant choice is uncontrolled. Mill one plant at a
  time until phase 2 proves a control route.
- Never queue a mill job without an empty bag on hand, and never
  queue a press job without an empty jug on hand.
- Never press paste the fort needs for nothing: paste is milled
  only when the press is ready to press it.
- Never cook tallow below the soap floor, and never cook oil
  below the soap floor.
- Never sell oil, soap, or dye below their floors, and never sell
  soap while the hospital is below its floor.
- Never build a millstone with no power plan, and never claim a
  millstone is working when it has no power.
- Never claim a reaction index, a job field, or a yield the probe
  has not proved live. Until phase 2 runs, the indices are
  UNVERIFIED and the doc says so.
- Never dump powder from a bag, and never store powder outside a
  bag.
- Never mill dye plants from the seed reserve, and never mill dye
  before the fort has cloth to dye.

## 17. Open questions (UNVERIFIED)

1. **Plant-choice control.** Which of the three routes in section
   7.3 works in 0.47.05: give-to stockpile linkage writable from
   Lua, manager order with a material condition, or a MillPlants
   job struct field. Phase 2 probes all three.
2. **Seed return from milling.** Whether milling a plant returns
   1 or 2 seeds, as the Miller page says, and whether the count
   varies by plant or by skill. Phase 2 probes it with a counted
   batch.
3. **Stack consumption.** Whether one MillPlants job consumes a
   whole plant stack or a single plant, and whether the powder
   output scales with the stack. Phase 2 probes it.
4. **Paste glob size.** How many units of paste one milled seed
   produces, against the 150 units the press reaction takes.
   Phase 2 probes it.
5. **Oil output size.** Whether one press job produces 1 unit of
   oil or a full 150-unit jug, and how the jug fill is read.
   Phase 5 probes it.
6. **Honeycomb press bug.** Whether the screw press refuses a
   direct "press honeycomb" job in 0.47.05, as the wiki reports,
   and whether the manager interface works around it. Phase 5
   proves it live.
7. **Lye and ash yields.** How much ash one log makes at a wood
   furnace, and how much lye one ash bar makes at an ashery.
   Phase 6 probes it with a counted batch.
8. **Soap in trade.** Whether caravans trade soap in 0.47.05, as
   the wiki denies. The plan does not depend on the answer;
   phase 6 checks the next caravan's goods and records it.
9. **Custom workshop distinction.** How a screw press is told
   apart from a soap maker's workshop in the collect, given
   both share the `Custom` subtype. Phase 3 probes the custom
   building type id.
10. **Sheet quality and book value.** Whether sheet quality
    levels affect the value of resulting books, which the wiki
    notes with a verify tag. Phase 9 checks it if the library
    work ever needs the answer.
11. **Millstone power read.** Whether the collect can read a
    millstone's power state, or whether the harness must infer
    it from idle mill jobs. Phase 3 probes it.
12. **Quern and millstone item source.** Whether ConstructQuern
    and ConstructMillstone are offered at the mason's workshop
    in 0.47.05, as STONEWORKING.md asserts. Phase 2 probes it.

## 18. Cross-doc conflicts flagged

1. **STONEWORKING.md section 3.5: "The full milling chain
   belongs to FARMING.md".** Wrong. FARMING.md covers planting
   mechanics and the refusal matrix; it does not cover milling
   or pressing at all. This document owns the milling and
   pressing chain. STONEWORKING.md must be corrected when this
   doc lands, and the coordinator owns that fix. STONEWORKING.md
   still owns the mason side: making the quern and millstone
   items.
2. **STONEWORKING.md phase 2 live bar: "a quern is made and
   placed and mills flour".** Overlaps this doc's phases 3 and
   4. The split is: STONEWORKING.md proves the mason makes and
   places the quern; this doc proves the mill job runs on it
   and the flour reads back. The two bars must not be counted
   twice, and the coordinator owns reconciling them.
3. **HUNTING.md: "The harness keeps a soap reserve and refuses
   to cook tallow below it, the same way it keeps a food
   floor".** False today. There is no soap in the fort, no soap
   reserve, and no such refusal anywhere in the code. This doc's
   phase 6 creates the reserve and the refusal. HUNTING.md must
   be corrected when phase 6 lands, and the coordinator owns
   that fix.
4. **FARMING_PLAN.md split rule assumes the workshops exist.**
   Section 10.1 sends cave wheat to the quern, sweet pods to
   the mill, quarry bushes to the screw press, and dimple cups
   to the mill, but no harness route builds or runs any of those
   workshops. Not a contradiction, a handoff: this doc supplies
   the route, and the farming plan's step 2 becomes actuatable
   when phase 7 lands.
5. **KITCHEN.md section 4.2 flags processed ingredients as
   invisible.** Consistent with this doc's section 7.2, not a
   conflict. Phase 1 here closes the gap for flour, sugar, dye,
   oil, paste, and soap; KITCHEN.md owns the cookable
   computation that reads them.
6. **CLOTHING.md dye milling.** Consistent: dye milling is owned
   here, dyeing thread and cloth is owned there. The boundary
   is the powder. No fix needed.

## 19. Sources

Wiki pages read from the local index
(`~/workspace/df-wiki-export/dfq.py`, hybrid search default),
on 2026-11-27:

- Quern (531 words), Millstone (1,366 words), Miller (1,152
  words), Screw press (707 words), Powder (605 words), Glob
  (781 words), Sheet (640 words), Oil, Soap, Paper industry.
- Farming, Crop, Kitchen, Textile industry, Dye (via CLOTHING.md
  and FARMING_PLAN.md).

0.47.05 raws, read from the repo install:

- `third_party/df_47_05/raw/objects/building_custom.txt` (the
  only workshop definition file; defines SOAP_MAKER and
  SCREW_PRESS only, proving the rest of the chain is hardcoded).
- `third_party/df_47_05/raw/objects/reaction_other.txt`
  (MILL_SEEDS_NUTS_TO_PASTE, PRESS_OIL, PRESS_OIL_FRUIT,
  PRESS_HONEYCOMB, MAKE_SLURRY_FROM_PLANT, PRESS_PLANT_PAPER,
  MAKE_SHEET_FROM_PLANT, MAKE_SOAP_FROM_TALLOW,
  MAKE_SOAP_FROM_OIL, TAN_A_HIDE, BREW_DRINK_FROM_PLANT).
- `third_party/df_47_05/raw/objects/plant_standard.txt`
  (MILL tokens for cave wheat, sweet pod, longland grass,
  dimple cup, blade weed, hide root, sliver barb, whip vine;
  PRESS_LIQUID_MAT for quarry bush; PRESS_PAPER_MAT for pig
  tail and rope reed).
- `third_party/df_47_05/raw/objects/plant_crops.txt` (MILL
  tokens for the garden grains; PRESS_LIQUID_MAT for flax,
  hemp, cotton, kenaf; PRESS_PAPER_MAT for flax, hemp, jute,
  ramie; PAPER_SLURRY reaction class).
- `third_party/df_47_05/raw/objects/material_template_default.txt`
  (PLANT_POWDER_TEMPLATE, PLANT_OIL_TEMPLATE with SOAP_MAT).

Harness state verified against the repo on 2026-11-27:

- actions.py WORKSHOP_CATALOG (carpenter, mason, still, kitchen
  only) and JOB_SPECS (brew, brew_fruit, cook, 8 carpenter
  furniture jobs only), `build_workshop` (refuses unknown kind),
  `queue_job` (takes job name and count, no material parameter).
- daemon.py TASK_DEFS (6 tasks, none milling or pressing).
- lua/stocks.lua (by_material covers DRINK, FOOD, MEAT, FISH,
  PLANT, SEEDS, BAR, WOOD, CLOTH, THREAD only; POWDER_MISC,
  LIQUID_MISC, GLOB, SHEET counted in by_type only; buckets,
  bins, barrels counted; no empty-bag or empty-jug headline).
- lua/buildings.lua (workshop subtype from df.workshop_type).
- assembler.py (snapshot budgets target 30K, warning 60K, never
  140K; TokenAccountant 3 chars per token conservative, 4 chars
  per token wire; diffing renders an unchanged section as a
  one-liner; retrieval cap 4K tokens per decision).
- materials.py (brew reaction, cook floor, empty-barrel
  fail-fast; no mill or press rules).
- planner.py (no milling thresholds or decisions),
  attention.py (no milling kinds), briefings.py (no milling
  briefing), catalog.py (entries built by introspection from
  the action table).
- tests/fixtures/runtime-enums-0.47.05-r8.json (241 job types,
  including MillPlants, ConstructQuern, ConstructMillstone,
  MakeAsh, MakeLye, MakePotashFromAsh, MakePotashFromLye; no
  PressOil, MakeSoap, or MakeSlurry job type; 25 workshop types
  including Quern, Millstone, Custom; 8 furnace types; 84 unit
  labors including MILLER, PRESSING, PAPERMAKING, SOAP_MAKER,
  MECHANIC, LYE_MAKING, POTASH_MAKING; 138 job skills including
  MILLING, PRESSING, PAPERMAKING, SOAP_MAKING, MECHANICS).
- logs/m1-20261127-073557.jsonl (real M1 snapshot, 7 citizens:
  10,693 chars, about 3,564 accountant tokens; no milling
  workshop in the fort).
- docs/FARMING_PLAN.md (split rule section 10.1, seed reserve,
  potash shared with soap), docs/KITCHEN.md (processed
  ingredients invisible section 4.2, flour does not rot section
  10, cook quirks Bug 2393 and Bug 7546), docs/CLOTHING.md
  (dye milling, clothier feed stockpile pattern, presentation
  constraint section 15), docs/STONEWORKING.md (quern and
  millstone items section 3.5, phase 2 live bar),
  docs/HUNTING.md (soap reserve claim, section 9.2),
  docs/LABOR.md (floors section 5.2, no milling floors),
  docs/STOCKPILES.md (Bars/Blocks row lists soap; powder and
  paste do not rot), docs/TRADING.md (lye and tallow soap as
  goods), docs/PLANNER.md (hospital zone with soap not
  implemented), docs/HARNESS_ROLE.md (opportunities rules
  section 7(e)).
