# Soap Making

Design record for the soap industry in the Urist harness: the soap
maker's workshop, lye production at the ashery, the tallow supply
from butchering and rendering, the oil supply from the screw press,
soap itself, and what the harness needs to observe, build, queue,
and verify for soap. This is the plan. Implementation follows it
phase by phase, each phase verified live against the real game
before it counts as done. Anything not verified against the wiki,
the 0.47.05 raws, the code, or the live game is marked UNVERIFIED.

Related docs: docs/WOODWORKING.md (the wood furnace, ash, and the
ashery chain phase 8, which this doc does not duplicate),
docs/FARMING_PLAN.md (potash fertilizer, the quarry bush oil crop,
ashery phase 3), docs/KITCHEN.md (rendering fat, the tallow cooking
conflict), docs/HUNTING.md (fat from hunting, the soap reserve
claim), docs/ANIMAL_HUSBANDRY.md (butchering, fat, tallow),
docs/TRADING.md (the elf refusal of tallow soap, soap on the buy
list), docs/STOCKPILES.md (soap storage in Bar/Block stockpiles),
docs/PLANNER.md (hospital zones not implemented). This doc builds
on them and does not duplicate them. Where this doc changes a
behavior another doc describes, it says so explicitly, in section
17.

## 1. Purpose

Soap making answers five questions every tick, from fresh
collects, so the agent never has to:

1. How much soap do we have, and is any of it where the wounded
   are?
2. Can we make soap right now (lye, tallow or oil, a soap maker,
   a soaper)?
3. Which input is the bottleneck: the ash for lye, the fat for
   tallow, or the seed for oil?
4. Is the kitchen eating the tallow the hospital needs?
5. Is ash being spent on potash that soap needed instead, or the
   other way round?

The headline finding of the research behind this doc is that the
fort has no soap industry at all, not a stalled one. There is no
soap maker's workshop, no ashery, no wood furnace, no screw press
in the harness catalog, no soap job in JOB_SPECS, and no soap,
lye, tallow, ash, or potash count in the stocks collect. The
fort cannot make soap today by any route the harness can drive,
and it cannot even see whether it holds the inputs. The first
work is observation and builds, not production tuning.

The second finding is that soap is a three-workshop chain with a
fork in the middle, and the harness must own the fork. One bar of
ash becomes either lye (for soap) or potash (for fertilizer and
glass), and lye itself can be turned into potash. Every bar of
ash is one decision, and the farming plan, the glass plan, and
this doc all want it. Without an allocation rule the first
industry to ask gets all the ash.

## 2. How soap making works in DF 0.47.05

All of this section is from the wiki pages listed in Sources,
checked against the 0.47.05 raws shipped with the game where the
wiki and the version can disagree. The local wiki index is a
current-wiki export: some pages carry v50 markers, so a wiki
claim is not a 0.47.05 claim until the raws or a live probe agrees
with it. Section 3 is the authoritative list for this version.
Where the wiki list and the raws disagree, the raws win and the
difference is named.

### 2.1 What soap is

Soap is a bar used for personal cleaning and for cleaning wounds
in hospitals. A soapy bath gives the happy thought "recently took
a soapy bath". Soap lowers the chance of an infection if a dwarf
is injured, and hospital soap is used to clean wounds, sterilizing
them and preventing infection from developing. The wiki calls soap
a vital commodity in dwarven health care (Soap, Health care).

Dwarves do not require soap to clean themselves. Without soap
they wash in murky pools, artificial pools, brooks, or a well.
Soap is a bonus for happiness and a treatment for wounds, not a
survival need like drink. That ranking matters for the budget in
section 6: soap never outranks beds, barrels, drink, or food.

A bar of soap starts with 150 units, and cleaning jobs partly
consume it: each use takes a varying quantity before the bar is
used up (Soap). A soap bar is therefore not one use. How many
washes or wound cleanings one bar covers is UNVERIFIED (section
16, open question 1). Soap is named by its source, so the fort
can hold "rattlesnake tallow soap" or "olive oil soap"; the name
has no gameplay effect (Soap).

Soap is stored in Bar/Block stockpiles with the soap option
enabled (Soap, STOCKPILES.md). Its material value is 1
(material_template_default.txt, SOAP_TEMPLATE). The soap material
carries SOAP_LEVEL 2 and the IMPLIES_ANIMAL_KILL token, which is
why elves refuse tallow soap (section 2.7).

Dwarves have an internal dirtiness level, which builds up over
time, falls when they bathe, and falls further with a soapy bath.
Dirtiness is connected to the chance of infection if the dwarf is
injured, so soap is useful as prevention as well as treatment
(Soap). Whether the harness can read a dwarf's dirtiness is
UNVERIFIED (section 16, open question 2); the doc assumes it
cannot, and sizes soap by citizens and wounds instead.

### 2.2 The chain, end to end

Soap needs two components, lye plus either tallow or oil, combined
at a soap maker's workshop (Soap). The full chain from scratch:

1. **Wood to ash.** One log becomes one bar of ash at a wood
   furnace, with the Wood burning labor. The furnace, the ash
   job, and the log spend belong to WOODWORKING.md (sections 2.4
   and 9, phase 3). This doc consumes ash; it does not produce
   it.
2. **Ash to lye.** One bar of ash becomes lye at an ashery, with
   the Lye making labor, using an empty bucket. Lye is a liquid.
   It is moved from buckets into a barrel when a food stockpile
   has lye enabled and a spare barrel is available (Lye).
3. **Fat to tallow, or seed to oil.** Either path works the same
   in the soap reaction. Tallow comes from butchering an animal
   and rendering its fat at a kitchen. Oil comes from pressing
   seed paste or olives at a screw press. Sections 2.4 and 2.5
   cover each path.
4. **Lye plus tallow or oil to soap.** One soap job at a soap
   maker's workshop takes 150 units of lye and 150 units of
   tallow or oil, and produces one bar of soap (reaction_other.txt,
   MAKE_SOAP_FROM_TALLOW and MAKE_SOAP_FROM_OIL). The lye and oil
   containers are preserved, not consumed.

The chain crosses five buildings (wood furnace, ashery, kitchen
or screw press, soap maker's workshop) and four labors (wood
burning, lye making, cooking or pressing, soap making). No single
workshop makes soap alone, and a gap anywhere in the chain is a
gap in soap. That is why the observation in phase 1 counts every
input, not just soap bars.

### 2.3 The soap maker's workshop

The soap maker's workshop is one of only two workshops defined in
the raws at all. building_custom.txt holds exactly two workshop
definitions, SOAP_MAKER and SCREW_PRESS; every other workshop in
the game is hardcoded (CLOTHING.md, section 2.3, verified the
same way). Its definition, read from the shipped raws:

* 3 by 3 tiles, work location 2,2, built by a dwarf with the
  Soap making labor.
* Build items: 1 empty bucket, plus 1 building material with
  WORTHLESS_STONE_ONLY. The workshop cannot be built from wood.
  It needs stone, and the stone must be worthless stone, the
  game's term for stone with no economic use. What counts as
  worthless stone on this fort's map, and whether the fort holds
  any, is UNVERIFIED (section 16, open question 3). The snapshot
  carried stone 0 on 2026-11-27 (WOODWORKING.md), so the soap
  maker may be unbuildable until the fort digs stone, which is a
  finding, not a detail.
* The bucket is a carpenter product. make_bucket already exists
  in JOB_SPECS, so the build component is one carpenter job away,
  not a new industry.
* Job requirement: Soap making. The soaper is a Farmer profession
  with the job title Soap Maker, labor Soap making, attributes
  strength, toughness, endurance, kinesthetic sense (Soaper).

The workshop runs exactly two reactions, both CustomReaction jobs
in the harness's terms (reaction_other.txt):

* MAKE_SOAP_FROM_TALLOW (CUSTOM_T): 150 lye (LIQUID_MISC, in a
  container, container preserved) plus 150 tallow (GLOB,
  REACTION_CLASS TALLOW, unrotten, must have a SOAP_MAT reaction
  product) makes 1 soap bar, dimension 150, skill SOAP_MAKING.
* MAKE_SOAP_FROM_OIL (CUSTOM_O): 150 lye plus 150 oil
  (LIQUID_MISC, unrotten, SOAP_MAT product, container preserved)
  makes 1 soap bar, dimension 150, skill SOAP_MAKING.

Both reactions take a preserved container for each liquid input:
the lye bucket or barrel is not consumed, and the oil jug is not
consumed. The fail-fast in queue_job must therefore count liquid
units, not containers, and must not claim a container is spent.
Whether materials.py can count lye units in a barrel at all is
UNVERIFIED (section 16, open question 4); the stocks collect does
not count lye today (section 4).

### 2.4 The ashery: lye and potash

The ashery is a hardcoded workshop (workshop type Ashery in the
live runtime enum). It is built from a block, a barrel, and a
bucket, by a dwarf with the Potash making or Lye making labor
(Ashery). The block must be a block, not rough stone or a log
(Ashery, FARMING_PLAN.md section 8). The barrel and bucket are
carpenter products; make_barrel and make_bucket both exist in
JOB_SPECS.

The ashery runs four tasks (Ashery page): make lye, make potash
from lye, make potash from ash, make milk of lime. The first three
are hardcoded job types in the live runtime enum (MakeLye,
MakePotashFromLye, MakePotashFromAsh). There are no MAKE_LYE or
MAKE_POTASH reactions anywhere in the reaction raws: a grep over
every reaction file finds only the LYE_MAKING skill on the milk of
lime reaction and the lye reagents of the soap reactions. That
proves the lye and potash jobs are hardcoded, not reactions, the
same way MakeCharcoal and MakeAsh are (WOODWORKING.md, section
2.4). The harness route for them is therefore a JOB_SPECS entry
with reaction_name None and the job type name, not a reaction
name, and the job type integer the enum fixture names must be
resolved to its df.job_type value live (section 16, open
question 5).

What the raws and wiki together establish for each ashery job:

* **Make lye.** 1 bar of ash plus an empty bucket makes lye
  (Lye page). The lye goes into the bucket, then into a barrel
  in a food stockpile with lye enabled. The exact lye units one
  job produces is UNVERIFIED (section 16, open question 6).
  The wiki Lye page says a barrel holds up to 100 units, while
  the soap reaction consumes 150 lye per bar, and the Soap page
  says a dwarf can take a barrel of lye and a stack of tallow
  and produce up to 10 bars at once. Those three claims do not
  fit together: 10 bars need 1,500 lye units, which is 15 barrels
  at 100 units each. One of the numbers is wrong or means
  something else, and the doc does not guess which. The live
  probe in phase 2 measures lye units per job, lye units per
  barrel, and bars of soap per barrel, and corrects this section.
* **Make potash from ash.** 1 bar of ash makes 1 bar of potash
  (Potash page, FARMING_PLAN.md section 8). This is the direct
  route, and the farming plan notes it takes less time than
  going through lye.
* **Make potash from lye.** 1 unit of lye makes potash (Potash
  page). This is the indirect route, and it exists so lye can be
  converted when soap does not need it. The exact lye units
  consumed per potash bar is UNVERIFIED (section 16, open
  question 6).
* **Make milk of lime.** Quicklime plus water in a bucket at the
  ashery makes milk of lime, skill LYE_MAKING (reaction_other.txt,
  MAKE_MILK_OF_LIME). Milk of lime is for parchment, not soap.
  This doc does not own it; it is named here only so the ashery
  job list is complete and no one mistakes it for a soap input.

Potash is not a soap ingredient. Soap uses lye. The farming plan
says potash is "also used for soap" (FARMING_PLAN.md, section
8.1); that is wrong as stated and is flagged as a cross-doc
conflict in section 17. What is true is that potash and lye
compete for the same ash, and lye can be converted into potash.
Section 7 owns that allocation.

Lye freezes in cold weather (Lye page). Frozen lye cannot be used
to make soap until it thaws, and there is no frozen lye entry in
stockpile menus, so dwarves will not haul a frozen lye barrel to
any stockpile. Whether freezing matters on this fort depends on
the embark climate and whether lye is stored underground, both
UNVERIFIED (section 16, open question 7). The design rule is
simple: lye lives underground, in the food stockpile near the
soap maker, never outside.

### 2.5 Tallow: butcher, render, reserve

Tallow is rendered fat, made from fat by the render fat job in a
kitchen; fat comes from butchering animals (Tallow). The chain:

1. **Kill an animal.** Domestic animal or hunted game. The
   hunting doc owns the kill (HUNTING.md); animal husbandry owns
   domestic animals (ANIMAL_HUSBANDRY.md).
2. **Butcher it at a butcher's shop.** Butchering yields meat,
   fat, hide, bones, and other products. The harness has no
   butcher action today (section 4): no butcher workshop in
   WORKSHOP_CATALOG, no butcher job in JOB_SPECS. Whether
   butchering is automatic under standing orders once a corpse
   reaches the refuse stockpile, or needs a queued job, is
   UNVERIFIED (section 16, open question 8).
3. **Render the fat at a kitchen.** RENDER_FAT (reaction_other.txt):
   150 fat (GLOB, REACTION_CLASS FAT, unrotten, with a RENDER_MAT
   product) makes 1 tallow glob, skill COOK, and the reaction is
   AUTOMATIC. The standing orders workshop menu includes
   Auto-Kitchen, enabled by default, which automatically schedules
   render fat jobs on any available kitchen (Tallow). Rendering
   large units of fat gains cooking skill extremely fast, dozens
   or hundreds of units of tallow per task (KITCHEN.md, section
   2.6). The harness treats rendering as the cook-training route
   today; this doc needs it as a production step with a measured
   output, which is a different claim and needs its own probe.

Tallow is stored in food stockpiles under fat, and dwarves will
fill up to 50 units of tallow in one barrel when barrels are
available (Tallow). It carries the ROTS material token but never
rots, even outside a stockpile (Tallow). Its material value is 1
(TALLOW_TEMPLATE). Tallow is also a low-value solid ingredient
for cooking prepared meals, and cooks prefer it (KITCHEN.md,
section 6). That is the conflict at the heart of the tallow
policy in section 8: the same glob feeds the cook and the soap
maker, and the cook gets to it first unless the harness refuses.

The soap reaction takes 150 tallow per bar. Fat arrives in
stacks of varying size, and one render job takes 150 fat and
makes 1 tallow glob, so the tallow units per animal depend on
the fat stack the animal yields. How much tallow a typical
hunted animal gives is UNVERIFIED (section 16, open question 9).

### 2.6 Oil: mill, press, jug

Oil is the second soap input, for forts short on animals or
rich in oil crops. The chain, from the wiki Soap and Screw press
pages:

1. **Grow or gather oil plants.** Quarry bush (rock nuts), olives
   (fruit), cottonseed, linseed, hempseed, kenafseed. Quarry bush
   is the farming plan's oil crop: spring, summer, autumn, 42
   days, processed to leaves or oil (FARMING_PLAN.md, section 4).
   Olives grow on olive trees; whether the fort's biome has
   olive trees is UNVERIFIED (section 16, open question 10).
2. **Mill seeds to paste.** Seeds are milled at a quern or
   millstone into seed paste. The exact milling reaction name
   for seed paste is UNVERIFIED (section 16, open question 11);
   the farming plan names the quern as the milling building and
   the screw press as the oil building, and this doc does not
   invent the reaction name.
3. **Press paste or fruit at a screw press.** PRESS_OIL
   (reaction_other.txt): 150 seed paste (GLOB, PRESS_LIQUID_MAT,
   not pressed) plus an empty liquid container (a jug, TOOL with
   LIQUID_CONTAINER use, preserved) makes oil (LIQUID_MISC, into
   the jug) plus 1 pressed glob (press cake, a food byproduct),
   skill PRESSING. PRESS_OIL_FRUIT does the same from 1 olive
   fruit (PLANT_GROWTH, PRESS_LIQUID_MAT, unrotten) plus a jug.
   The screw press is 1 by 1, built by a dwarf with the Mechanic
   labor from 2 mechanisms (building_custom.txt, Screw press
   page). Mechanisms come from the mechanic's workshop, which
   the harness cannot build today (WOODWORKING.md, section 3).
   So the oil path depends on the mechanic's workshop first, and
   on jugs, which are a craft good the harness cannot make today
   either. Both dependencies are named in section 5.

Oil is also a cooking ingredient, like tallow, so the same
reserve conflict applies, in smaller form: oil pressed for soap
must not be cooked away. Press cake is food and can be cooked.

### 2.7 Trade and elves

Two trade facts bound the industry:

* **Soap is not traded in caravans, per the wiki.** The Soap page
  says soap is "one not traded in caravans: you are going to have
  to make soap yourself". TRADING.md contradicts this: its buy
  list carries soap as hospital stock with a standing minimum
  (TRADING.md, section 5). One of them is wrong for 0.47.05.
  The live probe in phase 8 checks whether any caravan offers
  soap, and the doc that is wrong is corrected. Until the probe
  answers, the harness plans as if soap must be made, because
  the wiki claim is the one with a mechanism behind it (soap is
  a fortress-made bar, and no caravan good list in the raws was
  found naming it), and a plan that assumes soap can be bought
  fails silently when it cannot.
* **Lye can be ordered in trade agreements** (Lye page), and a
  caravan barrel of lye contains a stack of 10 units. Ten units
  is far short of the 150 the soap reaction consumes, so bought
  lye is at most a top-up, not a supply. Whether the fort can
  order lye, and in what quantity, is UNVERIFIED (section 16,
  open question 12).
* **Elves refuse tallow soap.** The elf ban covers wood
  derivatives including lye and tallow soap, plus meat, fat,
  tallow, and animal products generally (TRADING.md, section
  2.5). Never offer tallow soap, lye, or tallow to elves. Oil
  soap from plants is not named in the ban list; whether elves
  accept plant oil soap is UNVERIFIED (section 16, open
  question 13), and the doc does not claim it. Until the probe
  answers, no soap of any kind goes to elves.

## 3. The authoritative 0.47.05 list for the chain

Workshops in this game are mostly hardcoded: the building type
and the jobs it runs are fixed by the version, not chosen by the
player. The list below is the chain as it stands in 0.47.05,
verified against the shipped raws and the live runtime enum
(tests/fixtures/runtime-enums-0.47.05-r8.json). Do not trust a v50
workshop list for this fort.

| Building | Type in the enum | What it does in the chain | Harness build kind today |
| --- | --- | --- | --- |
| Soap maker's workshop | Workshop, subtype Custom (SOAP_MAKER, building_custom.txt) | MAKE_SOAP_FROM_TALLOW, MAKE_SOAP_FROM_OIL | none |
| Ashery | Workshop, subtype Ashery | MakeLye, MakePotashFromLye, MakePotashFromAsh, MAKE_MILK_OF_LIME | none |
| Wood furnace | Furnace, subtype WoodFurnace | MakeCharcoal, MakeAsh, 1 log per bar | none |
| Kitchen | Workshop, subtype Kitchen | RENDER_FAT (AUTOMATIC), PrepareMeal | kitchen, in WORKSHOP_CATALOG, verified live |
| Butcher's shop | Workshop, subtype Butchers | Butchering (job route UNVERIFIED) | none |
| Screw press | Workshop, subtype Custom (SCREW_PRESS, building_custom.txt) | PRESS_OIL, PRESS_OIL_FRUIT, PRESS_HONEYCOMB | none |
| Quern | Workshop, subtype Quern | Mill seeds to paste (reaction UNVERIFIED) | none |
| Millstone | Workshop, subtype Millstone | Mill seeds to paste (reaction UNVERIFIED) | none |
| Kiln | Furnace, subtype Kiln | MAKE_PEARLASH (potash plus fuel) | none |
| Mechanic's workshop | Workshop, subtype Mechanics | Mechanisms (2 per screw press) | none |
| Carpenter's workshop | Workshop, subtype Carpenters | Buckets, barrels (build components) | carpenter, in WORKSHOP_CATALOG, verified live |
| Mason's workshop | Workshop, subtype Masons | Blocks (ashery component) | mason, in WORKSHOP_CATALOG |

Notes on the list:

* The two Custom workshops are the trap in this chain. SOAP_MAKER
  and SCREW_PRESS are not in df.workshop_type at all: the enum
  lists Carpenters through Tool, with Custom as the catch-all,
  and neither name appears. act_build.lua resolves a subtype
  through df.workshop_type[PARAMS.subtype] and errors on an
  unknown subtype, so passing "SOAP_MAKER" fails at that lookup.
  Whether constructBuilding with subtype Custom plus the custom
  building id builds a soap maker through this route is
  UNVERIFIED (section 16, open question 14). The ashery, by
  contrast, is a named enum subtype, so its build route is the
  same shape as the carpenter's, with different components.
* The kitchen is the only building in the chain the harness can
  build today, and the render job is not in JOB_SPECS.
* The wood furnace and kiln are furnaces, not workshops: the
  build route takes a Workshop type today, and the furnace
  family needs a different building type. WOODWORKING.md phase 3
  owns that probe; this doc depends on its answer for ash.
* The reaction list for the chain is small and fully verified
  against reaction_other.txt: RENDER_FAT, MAKE_SOAP_FROM_TALLOW,
  MAKE_SOAP_FROM_OIL, PRESS_OIL, PRESS_OIL_FRUIT,
  MAKE_MILK_OF_LIME, MAKE_PEARLASH. The lye and potash jobs are
  not reactions and appear in no raw file; they are hardcoded
  job types in the enum.

## 4. What the harness has today

Verified against the repo on 2026-11-27. Everything in this
section was read from the code, not remembered. The daemon and
game were down for a VM replacement at the time of writing, so
no live value in this section was re-read; every live number
carried here is the last known value from the cited run or doc,
flagged UNVERIFIED until the game is back and the collect is
re-run.

### 4.1 The soap-relevant jobs that exist: one, and it is not a soap job

* **JOB_SPECS** (actions.py) holds 12 jobs: brew, brew_fruit,
  cook, and 9 carpenter jobs. There is no make_soap_from_tallow,
  no make_soap_from_oil, no make_lye, no make_potash, no
  make_ash, no make_charcoal, no render_fat, no press_oil.
* **cook** is job_type 115 (PrepareMeal) with reaction_name None.
  Render fat is a separate reaction (RENDER_FAT) and a separate
  mechanism: the game schedules it automatically under
  Auto-Kitchen standing orders, not through a PrepareMeal job.
  Queueing "cook" does not render fat, as far as the code shows,
  and no probe has shown otherwise. UNVERIFIED (section 16,
  open question 15).
* **The carpenter jobs are the only soap inputs the harness can
  make.** make_bucket and make_barrel exist, and the soap maker
  needs a bucket while the ashery needs a block, a barrel, and
  a bucket. The mason exists in WORKSHOP_CATALOG, so the block
  is reachable once the mason can make one; whether a block job
  exists in JOB_SPECS is not the case today (JOB_SPECS holds no
  mason jobs at all), so the ashery block is also blocked. That
  gap belongs to STONEWORKING.md; this doc records the
  dependency.
* **queue_job** (actions.py) refuses a job whose materials are
  short, counts already-queued copies first, and verifies the
  job ids appear in the world jobs list. That mechanism works
  for the two soap reactions as written: they are CustomReaction
  211 with a reaction name, the same shape as make_bed. What it
  cannot do today is count lye units, tallow units, or oil
  units, because materials.py has no rule for any of them
  (section 4.3).

### 4.2 The workshops that exist: the kitchen only

* **WORKSHOP_CATALOG** (actions.py) has exactly four kinds:
  carpenter, mason, still, kitchen. There is no soap_maker, no
  ashery, no wood_furnace, no kiln, no screw_press, no butcher,
  no quern, no millstone, no mechanic.
* **build_workshop** takes a kind from that catalog and a
  position, and waits for the ConstructBuilding job to finish.
  Its Lua route (act_build.lua) passes type Workshop and a
  subtype resolved from df.workshop_type. A furnace needs type
  Furnace, and a custom workshop needs something the route does
  not currently express. Both are UNVERIFIED routes (section 16,
  open questions 5 and 14).
* **The build components are reachable in principle.** A soap
  maker needs 1 empty bucket (carpenter, make_bucket exists)
  and 1 worthless stone (UNVERIFIED whether the fort holds any,
  open question 3). An ashery needs 1 block (no block job in
  JOB_SPECS), 1 barrel (make_barrel exists), 1 bucket
  (make_bucket exists). A screw press needs 2 mechanisms (no
  mechanic's workshop, no mechanism job). The chain of build
  blockers is: stone for the soap maker, blocks for the ashery,
  mechanisms for the screw press.

### 4.3 The stocks read carries no soap number

* **stocks.lua** counts drink, food, seeds, wood, stone, cloth,
  thread, metal bars, barrels, empty barrels, bins, and buckets
  as headline numbers, plus by_type for every item type and
  by_material for DRINK, FOOD, MEAT, FISH, PLANT, SEEDS, BAR,
  WOOD, CLOTH, and THREAD. Soap, lye, tallow, fat, oil, ash,
  potash, and charcoal have no headline number.
* Soap bars are BAR items, so they appear in by_type as BAR
  units mixed with metal bars, and in by_material as BAR entries
  if the material token decodes. Whether the soap material token
  reads as something the harness can filter on is UNVERIFIED
  (section 16, open question 16). The snapshot never renders
  any of it.
* Tallow and fat are GLOB items. GLOB is not in the add_mat
  list, so tallow never reaches by_material, and the snapshot
  never renders it. The raw by_type GLOB count exists in the
  collect but mixes tallow, fat, seed paste, and press cake
  together, so it cannot answer "how much tallow do we have"
  without the material split.
* Lye is LIQUID_MISC. LIQUID_MISC is not in the add_mat list
  either, so lye units never reach by_material. The raw by_type
  LIQUID_MISC count mixes lye, oil, and other liquids.
* Ash, potash, and charcoal are BAR items too (ash and potash
  are bars), so they share the same mixed BAR count as soap and
  metal bars. Nothing in the snapshot can tell 5 ash from 5
  soap from 5 iron bars.
* **The fort's soap, lye, tallow, fat, oil, ash, and potash
  counts are therefore all unknown.** No doc and no run log
  records any of them. The last known wood (117), barrels (15
  total, 3 empty), and drink (33 and falling) are from
  WOODWORKING.md and the 2026-11-27 runs, and they are the only
  chain numbers with any basis at all. UNVERIFIED until the
  game is back and a collect is run.

### 4.4 The planner, tasks, and diagnosis know nothing about soap

* **TASK_DEFS** (daemon.py) has six tasks: brew, cook, make_bed,
  make_barrel, gather, farm. There is no make_soap, make_lye,
  make_potash, render_fat, press_oil, or butcher task.
* **The planner** (planner.py) has no soap decision, no lye
  decision, no tallow decision, and no ash allocation. It queues
  beds and barrels and suggests building a carpenter. Soap is
  invisible to it.
* **diagnose.py** has no soap fix. A soap job that fails for no
  lye, no tallow, or no soap maker produces no diagnosis, because
  no diagnosis names those causes.
* **catalog.py** has no soap, lye, tallow, ashery, soap maker,
  or screw press entry. The catalog is built by introspection
  from ACTIONS and JOB_SPECS, so the absence follows from the
  absence in the code, and a fresh model given only the catalog
  cannot discover soap making at all.
* **briefings.py** has 10 kinds (new_arrival, cavern_creature,
  citizen_new, hostile, invasion, strange_mood, caravan,
  unit_death, low_drink, low_food). There is no low_soap and no
  hospital briefing.
* **placement.py** carries no soap weights: no soap maker, ashery,
  screw press, or wood furnace adjacency, and no lye or soap
  stockpile placement. The triangle the woodworking doc lays out
  (carpenter, wood stockpile, wood furnace) has no soap corner.

### 4.5 What other docs already promise about soap

* **FARMING_PLAN.md phase 3** owns the potash production chain
  (wood furnace ash job, ashery build, potash making job) and
  the fertilize decision. It also says potash is used for soap,
  which is wrong as stated (section 17, conflict 1).
* **WOODWORKING.md phase 8** owns the ashery build kind and the
  lye and potash jobs, shared with FARMING_PLAN.md phase 3,
  and owns the wood side: the ash supply, the log spend, and
  the refusal when ash would spend below the floors. This doc
  accepts that split and owns the soap-maker side plus the
  allocation decision in section 7.
* **HUNTING.md** says the harness keeps a soap reserve and
  refuses to cook tallow below it (section 7.2). No such reserve
  exists in code (section 17, conflict 2). The sentence is a
  design intent in the hunting doc, not a mechanism.
* **KITCHEN.md** treats rendering as the cook-training route and
  tallow as a filler ingredient cooks prefer (sections 2.6 and
  6). This doc needs rendering as production and tallow as a
  reserved input, which reverses the kitchen doc's ranking
  (section 17, conflict 3).
* **TRADING.md** lists soap as hospital stock on the buy list
  and bans tallow soap for elves (sections 2.5 and 5). The buy
  list entry conflicts with the wiki (section 17, conflict 4).
* **PLANNER.md** records hospital zones as not implemented:
  UI-only, no verified path, wounds heal on their own (5 wounded
  to 0 over the window). Soap's hospital use therefore has no
  consumer in the harness yet, and this doc owns production
  only. The hospital work is future work; section 14 phase 8
  states the handoff.
* **STOCKPILES.md** already places soap in Bar/Block stockpiles
  with bins, and lye in food stockpiles. That placement stands
  and this doc does not redo it.

## 5. What is missing (verified gaps)

Every gap below was verified by reading the code, not by guessing
from the wiki.

* **No soap maker build.** No soap_maker kind in WORKSHOP_CATALOG,
  and the Custom subtype route is unproven. The workshop that
  makes soap cannot be built by the harness.
* **No ashery build.** No ashery kind in WORKSHOP_CATALOG. The
  ashery is a named enum subtype, so the route is plausibly the
  same shape as the carpenter's, but no one has built one.
* **No wood furnace build.** No furnace kind exists at all, so
  no ash and no charcoal. WOODWORKING.md phase 3 owns this
  probe; soap depends on it.
* **No screw press build.** No screw_press kind, and the Custom
  subtype route is unproven, and the press needs 2 mechanisms
  from a mechanic's workshop the harness cannot build. The oil
  path is blocked three deep.
* **No butcher build or job.** No butcher kind, no butcher job.
  The tallow path starts with a kill whose butchering the
  harness cannot drive or verify.
* **No quern or millstone build.** No quern or millstone kind.
  Seed milling for the oil path cannot be driven.
* **No soap jobs.** MAKE_SOAP_FROM_TALLOW and MAKE_SOAP_FROM_OIL
  are verified reactions in the raws, and neither is in
  JOB_SPECS. Both are the same mechanism as make_bed
  (CustomReaction 211), so they are the cheapest jobs in this
  doc to add, once the workshop exists.
* **No lye or potash jobs.** MakeLye, MakePotashFromLye, and
  MakePotashFromAsh are hardcoded job types with no reaction
  name. Adding them needs a JOB_SPECS entry with reaction_name
  None and the resolved job type integer, a shape JOB_SPECS
  already has for cook (job_type 115, reaction None), but with
  a job type integer that has never been resolved for these
  three.
* **No render fat job.** RENDER_FAT is a verified reaction with
  the AUTOMATIC flag, and it is not in JOB_SPECS. Whether the
  game auto-schedules it under Auto-Kitchen, and whether
  queueing it as a CustomReaction works at all, are both
  UNVERIFIED.
* **No press oil jobs.** PRESS_OIL and PRESS_OIL_FRUIT are
  verified reactions, and neither is in JOB_SPECS. Both need a
  screw press and a jug, neither of which the harness can make.
* **No soap, lye, tallow, fat, or oil counts.** stocks.lua has no
  headline number for any of them, and by_material excludes
  GLOB and LIQUID_MISC, so the two inputs the soap reaction
  consumes cannot be counted by the harness today even in the
  raw collect.
* **No ash or potash counts.** Both are BAR items mixed with
  metal bars and soap in the BAR count. The ashery allocation
  decision in section 7 cannot be made from any number the
  harness reads today.
* **No tallow reserve.** materials.py has no tallow rule, the
  planner has no tallow floor, and nothing stops a cook from
  turning the soap input into a roast. HUNTING.md claims the
  reserve exists; it does not.
* **No soap floor, no soap suggestion, no soap briefing.** The
  planner never queues soap, the snapshot never shows it, and
  no briefing fires when it runs out.
* **No soaper assignment.** Nothing picks who makes soap. The
  SOAP_MAKING labor is toggled by hand, and the planner never
  checks whether a soaper exists or is alive. The same gap the
  kitchen doc names for the cook exists here for the soaper and
  the lye maker.
* **No soap maker, ashery, or screw press placement.** No
  adjacency weights, no stockpile placement for lye near the
  soap maker or soap near the hospital, and no layout rule for
  the chain.
* **No block job.** The ashery needs a block, and JOB_SPECS has
  no mason job at all. The ashery build is blocked on
  STONEWORKING.md work, not on soap work.

## 6. The soap budget: the ledger

The budget is arithmetic from verified numbers, not a feeling.
Every soap bar costs 150 lye and 150 tallow or 150 oil. Every
lye job costs 1 ash bar and an empty bucket. Every ash bar costs
1 log. Every tallow glob costs 150 fat. Every oil job costs 150
seed paste or 1 olive fruit, plus a jug.

### 6.1 The floors

The fort holds one soap floor, in two parts. A floor is a number
the harness defends: soap below a floor is never spent on
anything below that floor in priority, and inputs below a floor
are never spent on anything else.

1. **Soap floor.** One bar per citizen, plus 2 bars held for the
   hospital. For 7 citizens that is 9 bars. The 1-per-citizen
   part covers bathing; the plus-2 covers wound cleaning when
   someone is hurt. The consumption rate per bar is UNVERIFIED
   (open question 1), so 1 per citizen is a starting floor, not
   a measured one: phase 1 measures how fast soap is consumed
   and the floor is corrected from the measurement. Migrants
   move the floor by 1 bar each.
2. **Tallow reserve.** Enough tallow to make the soap floor from
   nothing: soap floor times 150 tallow units. For 7 citizens
   that is 9 times 150, or 1,350 tallow units. The kitchen may
   not cook tallow below this reserve. The reserve is the fix
   for the conflict in section 8: the cook and the soap maker
   stop racing each other once the reserve is a number the
   material check enforces.

The combined hard floor for 7 dwarves is 9 bars of soap, backed
by 1,350 tallow units (or the same in oil) and 1,350 lye units,
which is 9 ash bars and 9 logs at the wood furnace. That is the
whole chain in one line: 9 logs, 9 ash, 9 lye, 1,350 tallow,
9 soap. Against wood 117 (last known, UNVERIFIED now), the log
cost is trivial. The binding constraints are the workshops that
do not exist and the tallow that is not counted, not the wood.

### 6.2 The lye ledger

Lye exists in three states, and the snapshot must carry all
three, not a total, because the soap reaction consumes units
and the containers are preserved:

* Lye units in buckets: the working stock, at the ashery and the
  soap maker.
* Lye units in barrels: the stored stock, in the food stockpile
  with lye enabled. One barrel's capacity in lye units is
  UNVERIFIED (open question 6).
* Lye units frozen: unusable until thawed. Whether the fort ever
  holds frozen lye is UNVERIFIED (open question 7).

The brew barrel lesson applies here: a count of lye-containing
items is not a count of lye. The wiki work-orders note says the
recommended condition "lye-containing items" is wrong for
exactly this reason, because a barrel holding 10 lye counts as
one item (Soap). The harness counts units, never containers,
for lye, tallow, and oil. A job queue that counts containers
will queue soap that cannot run, the same way brew x5 queued
against 2 empty barrels in M1 run 12.

### 6.3 The tallow ledger

Tallow exists in three states too:

* Fat units, unrendered: the raw input, in the food stockpile
  or on a corpse not yet butchered. Fat rots; tallow does not.
  Unrendered fat is a timer, not a stock.
* Tallow units, rendered: the soap input, in barrels of up to 50
  units in the food stockpile.
* Tallow units committed to cooking: the cook's share, which is
  zero while the reserve in section 6.1 is unmet.

The ledger prevents the repeat of the barrel mistake: the
planner queues soap only up to the soap floor, and the queue
size is the shortfall, not a round number. Three missing bars
means queue 3, not 20.

### 6.4 The burn rate and the days-remaining rule

Soap is consumed, not burned, and the consumption rate is
unknown until measured. Phase 1 measures it: soap bars and soap
units at each collect, divided by days, split by whether any
dwarf was wounded in the window. Until the measurement exists,
the snapshot carries the soap count and the floor, and no
days-remaining figure is printed, because a days-remaining
figure from a guessed rate is a lie in the snapshot. The Store
trends drink, food, wood, and stone today; soap joins the trend
only after the count exists, and the trend is net (soap made
minus soap consumed), not gross.

## 7. Lye versus potash: the allocation rule

One bar of ash has three uses, and the harness must choose
between them in a fixed order, every time, with the numbers
attached. The order is the priority order, and the harness
enforces it. The agent picks the batch size; the harness picks
the order.

1. **Lye, to the soap floor.** Ash becomes lye until the lye
   stock covers the soap floor (soap floor times 150 lye units).
   Soap is health care, and health care outranks fertilizer.
2. **Potash, to the fertilizer need.** Ash becomes potash
   directly (MakePotashFromAsh) until the farming plan's
   fertilizer need for the season is met. The farming plan owns
   the need number (FARMING_PLAN.md, section 8); this doc owns
   the rule that fertilizer waits behind lye. The direct route
   is used, not the route through lye, because the farming plan
   notes it takes less time.
3. **Potash, from surplus lye.** Lye above the soap floor
   becomes potash (MakePotashFromLye) when the fertilizer need
   is still unmet after the direct route. Lye is never converted
   below the soap floor.
4. **Pearlash, last.** Potash becomes pearlash at a kiln for
   glass, only when the fertilizer need is met and the soap
   floor is met. Glass is discretionary against both.

A MakePotashFromAsh job is refused when lye is below the soap
floor, with the floor named: "cannot make potash: lye 0, soap
floor needs 1,350 lye units". A MakePotashFromLye job is refused
when lye is at or below the soap floor, for the same reason. A
MakeLye job is refused when ash is at or below the ash floor
held by WOODWORKING.md (the bed and barrel floors come first:
ash never spends wood below the hard floor).

The allocation is recomputed every tick from the live counts,
because a migrant wave moves the soap floor and a harvest moves
the fertilizer need on the same day. The snapshot carries the
three numbers the decision needs: lye units, ash bars, potash
bars, and the soap floor. The full allocation table lives behind
the query route.

## 8. Tallow policy

* **Tallow is soap first, food second.** The reserve in section
  6.1 is enforced in materials.py: a cook job that would take
  tallow below the reserve is refused with the reserve named.
  The kitchen doc's ranking (tallow as a filler cooks prefer)
  is reversed by this rule, and the reversal is flagged in
  section 17, conflict 3. The cook still gets tallow above the
  reserve; the rule is a floor, not a ban.
* **Render fat promptly.** Fat rots and tallow does not, so
  unrendered fat is converted as soon as a kitchen and a cook
  exist. A fat stack unrendered for a season is a diagnosed
  failure with the cause named (no kitchen, no cook, no
  Auto-Kitchen, or the render job failing).
* **Butcher promptly.** A corpse unbutchered is fat that never
  becomes tallow. The butcher route is UNVERIFIED (open
  question 8); until it is proven, the harness counts corpses
  in the refuse stockpile and reports them, so the agent can
  see the tallow that is rotting.
* **One soaper, one backup.** The soaper is the dwarf with the
  highest soap making skill, with a backup who keeps the labor
  warm. The soaper is not also the brewer or the cook; the
  assignment refuses a choice that would leave the still or the
  kitchen without a worker.
* **Never cook the reserve.** A prepared meal that uses tallow
  as a filler while the reserve is unmet is the failure the
  hunting doc warns about: a fort that cooks all its tallow has
  traded its hospital for a meal. The refusal is in code, not
  in the agent's memory.

## 9. Oil policy

* **Oil is the second path, not the first.** Tallow is the
  default soap input, because the fort hunts and butchers
  already (or will), and the oil path needs a mechanic's
  workshop, mechanisms, jugs, a quern, and an oil crop, none of
  which the harness can drive today. Oil is made when tallow is
  short and the oil chain exists, not before.
* **Quarry bush is the oil crop.** It grows spring, summer, and
  autumn, and its leaves are also food, so the crop serves two
  needs. Olives need olive trees, which the fort may not have
  (open question 10). The farming plan owns the crop choice;
  this doc owns the rule that oil seed is milled for soap only
  above the food need for the same crop.
* **Jugs are the binding constraint.** Every oil job needs an
  empty jug, and jugs are a craft good. Until the harness can
  make or trade for jugs, the oil path cannot run at all, and
  the snapshot must say so rather than show oil 0 as if the
  crop were the problem.
* **Press cake is food.** The pressed glob from PRESS_OIL is
  cooked, not wasted. It does not count toward the tallow
  reserve and does not compete with soap.

## 10. Soap production priorities

The soap maker has one worker and one job at a time. The queue
order is the priority order, and the harness enforces it. The
agent picks the batch size; the harness picks the order.

1. **Soap from tallow, to the soap floor.** The default job.
   Only up to the shortfall, never a round number.
2. **Soap from oil, to the soap floor.** Only when tallow is
   short and oil exists. The two soap jobs are the same product
   from different inputs; the harness queues the one whose
   input is in stock.
3. **Lye, to the lye need.** Ashery work that feeds the soap
   floor, in the allocation order of section 7.
4. **Nothing else.** The soap maker makes soap and nothing else.
   There is no discretionary soap production: soap above the
   floor is not queued, because a bar above the floor is a bar
   the hospital will use eventually, and the inputs are better
   held as lye and tallow than as finished bars the fort cannot
   trade (section 2.7).

A batch is never larger than the inputs above the floors. If the
fort holds 1,350 tallow and 1,350 lye, it can make 9 bars, but
only a batch at a time, because a wounded dwarf can move the
hospital need by 2 bars overnight and a 9 bar queue cannot be
unmade.

## 11. Layout

Layout is scored placement (docs/SITE_SELECTION.md, queued work),
with soap factors on top of the shared threat, cover, and traffic
factors:

* **The chain sits together, underground.** Soap maker, ashery,
  wood furnace, kitchen, and the food stockpile holding lye and
  tallow belong within a few tiles of each other. Lye is carried
  in buckets and barrels, tallow in barrels, ash in bars; every
  step is a haul, and a chain spread across the fort pays the
  hauling cost on every bar of soap. Lye lives underground, so
  it never freezes.
* **The soap maker sits near the food stockpile.** Lye and tallow
  both live in food stockpiles. The soap maker next to the food
  stockpile is a short haul for both inputs and a short haul for
  the finished bars to the Bar/Block stockpile.
* **The ashery sits near the wood furnace and the soap maker.**
  Ash goes from the furnace to the ashery, lye goes from the
  ashery to the soap maker. The ashery is the middle of the
  chain and belongs in the middle of the floor plan.
* **The soap stockpile sits near the hospital.** Finished soap
  goes to the Bar/Block stockpile, with a small soap stockpile
  near the hospital beds once the hospital exists. The hospital
  work is future work; the stockpile placement is designed now
  so the hospital does not need a rebuild to get soap.
* **The wood furnace sits away from the food stockpile.** The
  furnace is a fire risk, and the food stockpile holds wooden
  barrels of drink and lye. WOODWORKING.md already sets this
  rule; the soap chain inherits it, because a fire in the lye
  barrels is a fire in the soap supply.
* **The screw press sits near the quern and the food stockpile.**
  Seed paste goes from the quern to the press, oil goes from the
  press to a jug in the food stockpile, press cake goes to the
  kitchen. The press is 1 by 1 and fits anywhere; it belongs
  next to its inputs, not in a corner.
* **Noise.** No soap building is a bedroom, so the chain can sit
  near the woodcutting. The hospital and the dormitory sit away
  from it, under the 8 tile noise rule (WOODWORKING.md, section
  2.1).

## 12. Failure modes

Every failure mode in this table has a diagnosis the harness must
produce, with the fix named. A silent zero is never acceptable.

| Failure | Cause | Diagnosis | Fix |
| --- | --- | --- | --- |
| No soap, no soap maker | Workshop cannot be built, or never built | "soap 0 bars, soap maker none, worthless stone S" | Build the soap maker once stone exists; queue soap to the floor |
| Soap job fails for no lye | Ashery missing, ash missing, or lye frozen | "lye 0 units, ash A bars, ashery none" | Build the ashery, make ash, make lye, move lye underground |
| Soap job fails for no tallow | No butcher, no render, or the cook ate it | "tallow 0 units, fat F units unrendered, corpses C unbutchered" | Butcher, render, enforce the tallow reserve |
| Soap job queued against containers, not units | Queue counted lye barrels, not lye units | "lye containers N, lye units 0, soap jobs queued M" | Count units; refuse the queue when units are short |
| Tallow cooked below the reserve | Cook took the soap input | "tallow T units, reserve R, cooked C" | Refuse cooking below the reserve; forbid tallow as a cooking ingredient |
| Potash spent the ash soap needed | Allocation ran fertilizer first | "ash A bars, lye L units, soap floor F bars, potash made P" | Enforce section 7 order: lye first, potash second |
| Lye frozen | Lye stored outside in cold weather | "lye frozen, stored outside" | Move lye barrels underground; wait for thaw |
| Fat rots before rendering | No kitchen, no cook, or render never queued | "fat F units, rendered 0, kitchen none" | Build the kitchen, assign a cook, render promptly |
| Oil path blocked on jugs | No jugs in stock, no jug maker | "oil 0, paste P, jugs 0" | Trade for jugs or make them; do not queue press oil without a jug |
| Oil path blocked on mechanisms | No mechanic's workshop, no mechanisms | "screw press none, mechanisms 0" | Build the mechanic's workshop; make 2 mechanisms |
| Soap offered to elves | Trade stockpile held tallow soap in spring | "tallow soap in trade stockpile, elves present" | Remove soap from the trade stockpile; refuse the offer |
| Soap maker unbuildable for no stone | Stone 0, worthless stone 0 | "worthless stone 0, stone 0" | Dig stone; the soap maker cannot be built from wood |
| Hospital has no soap | Soap made but never hauled to the hospital | "soap S bars, hospital soap 0" | Stockpile soap near the hospital beds (future hospital work) |
| Ashery built but idle | No ash, or no lye maker assigned | "ashery idle, ash 0, lye makers 0" | Make ash at the wood furnace; assign a lye maker |
| Soap made but never counted | BAR count mixes soap with metal bars | "BAR units N, soap unknown" | Split the BAR count by material (phase 1) |

## 13. Model presentation

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

### 13.1 The snapshot: what reaches the model every tick

The snapshot gains a Soap section of 4 lines when quiet, 5 when an
attention item fires. It is counts and exceptions, never a dump.
The Stocks line already carries drink, food, wood, and stone
today, so those numbers cost 0 new tokens; the Soap section adds
the soap, lye, tallow, oil, ash, and potash state that the Stocks
line cannot carry, because the Stocks line cannot tell 5 ash from
5 soap from 5 iron bars.

Proposed quiet text. Every number in it is illustrative, showing
the shape: the fort holds no soap number today, so there is no
live value to put here. Phase 1 replaces them with live values
when the section is verified.

```
Soap: soap 9 bars (floor 9), lye 1350 units, tallow 1350, fat 0, oil 0; ash 4, potash 2.
  Soap maker #12 built, idle. Ashery #9 built, idle. Screw press: none. Wood furnace: none.
  Soaper: 1 dwarf; lye maker: 1 dwarf; buckets 2, empty barrels 3.
  Tallow reserve 1350 met; oil path blocked: no jugs.
```

Proposed attention line, added as a fifth line only when it fires:

```
  Attention: soap 0 bars, no lye; make 9 lye then 9 soap from tallow.
```

What each line is:

* Line 1 is a count against a floor (soap bars vs the soap floor)
  plus the three input ledgers in units (lye, tallow, fat, oil)
  and the ash and potash bars the allocation decision needs.
  Lye, tallow, fat, and oil are units, never containers, per
  section 6.2.
* Line 2 is the workshop state with ids, so the model can queue
  a job without a query turn. A workshop that does not exist
  reads "none", so the model never has to guess whether soap can
  be made. The soap maker and ashery ids are repeated here from
  the Buildings line deliberately: the soap decision needs them
  in the same breath as the numbers.
* Line 3 is a count (soapers, lye makers) plus the two build
  components the chain keeps consuming (buckets, empty barrels).
  The lye maker count is the precondition for every lye job,
  and it is invisible today.
* Line 4 is the reserve state and the oil path state, in one
  line: whether the tallow reserve is met, and what blocks the
  oil path, if anything. When the oil path is not blocked it
  reads "oil path open", two words, so the line never grows.
* Line 5 is an exception, present only when it fires: soap
  below the floor with no inputs, lye frozen, or tallow below
  the reserve with cooking underway. It is ranked with the other
  attention entries, never buried in a list.

Token cost, by the accountant's rule (length divided by 3):

* Quiet section: 301 characters, 100 tokens by the accountant,
  75 tokens on the wire. Counted from the proposed text above
  with the accountant's rule, not estimated.
* With the attention line: 371 characters, 124 tokens by the
  accountant, 93 tokens on the wire.
* At 7 dwarves and at 50 dwarves, the cost is the same within
  about 10 tokens. The section carries counts only, no per-dwarf
  lines, so it does not grow with population. The growth at 50
  dwarves lands in the Units section (exceptions capped at 8) and
  the profession counts (top 8), not here. A second soap maker
  or a second ashery adds one short clause to line 2, about 15
  tokens, and only while it exists.
* Against the budgets (target 30K, warning 60K, compaction 100K,
  never over 140K on a 200K window), the quiet section is about
  0.4 percent of the target, and the whole snapshot stays an index
  at about 4,700 tokens typical. The section is a budget decision
  reviewed against the accountant, not a default, and its cost is
  stated here so the review can check it.

What is not in the snapshot, and why:

* Not the soap bar list, with names and sources. A bar named
  "rattlesnake tallow soap" is a flavor string, and a list of
  them grows with the stock. The count is in line 1; the names
  live behind the query route.
* Not lye by container. Containers are a hauling detail, and
  the soap decision needs units. The unit count is in line 1;
  the container split is a query.
* Not tallow by animal. Which animal the tallow came from does
  not change the soap. The unit count is in line 1; the source
  split is a query.
* Not the full ashery job list. The ashery runs four jobs, and
  the snapshot never carries a menu. The catalog carries them,
  read on demand for the action the model needs, per the 6-tool
  surface rule.
* Not soap consumption projections beyond the floor. The floor
  is pushed; the consumption rate is a query until phase 1
  measures it, and then it is a trend line, not a projection.
* Not per-dwarf soap making or lye making skill. The assignment
  (who, and whether a backup exists) is in the query route. The
  snapshot carries the count of soapers, not their skill table.
* Not the elf soap rule every tick. The ban is a standing rule
  the trading plan enforces in code. It arrives as a briefing
  when the elves are coming, and as a line in the query route
  the rest of the year.

The reason in every case is the same: the snapshot is an index,
and an index carries counts, exceptions, and diffs. Anything the
model needs once a season, or once per decision, lives behind the
query route. Pushing it every tick would grow the snapshot toward
the budgets for information the model reads once and forgets.

### 13.2 The query route

GET /v1/soap returns the full detail, read from the fresh
collect, not from a cache. The snapshot carries the summary; the
route carries the detail. The agent asks the route when it needs
to choose, never as a matter of routine.

Response shape:

* Soap: bars in stock, units remaining across bars, the soap
  floor, the shortfall, bars by source animal or plant when the
  collect supports it.
* Lye: units in buckets, units in barrels, units frozen, the lye
  need for the soap floor, the ashery id and job count, or
  "none".
* Tallow: fat units unrendered, tallow units rendered, tallow
  units in barrels, the reserve from section 6.1, corpses
  unbutchered with their positions.
* Oil: seed paste units, oil units, jugs in stock, the screw
  press id or "none", the mechanism count.
* Ash and potash: ash bars, potash bars, pearlash bars, the
  allocation table from section 7 (lye need, fertilizer need,
  what the next ash bar becomes).
* Workshops: the soap maker, ashery, wood furnace, screw press,
  and kitchen with ids, construction stage, current jobs, and
  queued jobs.
* Labor: soapers, lye makers, potash makers, pressers, and cooks
  by name and skill, and whether each assignment has a backup.
* Budget: the soap floor, the tallow reserve, the lye need, the
  soap consumption rate once measured, and the batch size the
  budget recommends, if any.

The snapshot carries the pointer so the model knows the route
exists: the soap maker id in line 2 and the soap and lye counts
in line 1 are the pointer. The route is one query; the existing
/v1/stocks and /v1/buildings routes already answer the BAR total
and the workshop list, and this route adds the soap, lye, tallow,
oil, and allocation detail those routes do not carry.

### 13.3 The briefing

No soap briefing exists today. The briefing kinds in
briefings.py are new_arrival, cavern_creature, citizen_new,
hostile, invasion, strange_mood, caravan, unit_death, low_drink,
and low_food. The soap system adds one kind, low_soap, when
phase 7 lands. It fires on exactly two triggers, and only then:

* Soap falls below the floor while a dwarf is wounded, so the
  hospital has no soap for wound cleaning, or
* Soap is 0 and lye is 0 and tallow is 0, so the whole chain is
  dry and no soap can be made without three steps of work.

The briefing follows the existing shape: what, matters, options,
cost, one or two sentences per field, and the whole briefing is a
few hundred tokens at most (briefings.py). Estimated cost: about
120 to 180 tokens by the accountant, about 90 to 135 on the wire,
for the four fields plus the numbers that name the shortage. The
estimate is computed from the existing low_drink briefing, which
is the same shape and length; the coordinator verifies it against
the live briefing text before commit.

What the briefing covers: the shortage (soap below the floor, or
the chain dry), what it blocks (wound cleaning, or bathing),
and the fix (make lye, render tallow, make soap) with the numbers
attached. What it leaves to a query: the container split, the
source split, and the full allocation table. The briefing never
fires for a discretionary shortage: potash at zero with no
fertilizer need is not a briefing, and oil at zero while tallow
covers the floor is an attention line, not a briefing.

### 13.4 Opportunities

The opportunities section does not exist in the code yet (gap
review 3, P2-3: the only "opportunit" hit in src/ is a briefing
string). Until that gap closes, the entries below have nowhere to
land, and this doc does not pretend otherwise. When the mechanism
lands, soap contributes at most 2 entries, each facts plus a
query route, never a suggestion, never a pause, and ignoring one
costs nothing:

* "Fat 300 units unrendered in the food stockpile. Rendering
  makes tallow for soap. Query: GET /v1/soap."
* "Quarry bush seed paste in stock (150). Pressing makes oil
  for soap. Query: GET /v1/soap."

An opportunity is not a suggestion: it carries no recommended
action and no priority, and the suggestion uptake metrics do not
count it. If the mechanism never lands, the snapshot and the
briefing still carry the system, and nothing is lost except the
low-pressure channel.

### 13.5 What the system deliberately does NOT push

* The full soap bar list, with source names. It grows with the
  stock and the model does not decide from it. The count and the
  floor are the push; the list is a query.
* Lye by container. Units are the push; the bucket and barrel
  split is a query.
* Tallow by animal. Units are the push; the source split is a
  query.
* The full ashery job list. Four jobs are a menu, and a menu in
  the snapshot is a script, not an index. The catalog carries
  them, read on demand.
* Soap consumption projections. The floor is pushed; the rate is
  a query until measured, and then a trend line.
* Per-dwarf soap making or lye making skill. The assignment is
  in the query route. The snapshot carries the count of soapers,
  not their skill table.
* The elf soap ban every tick. It is enforced in code by the
  trading plan, and arrives as a briefing when the elves are
  coming.

## 14. Implementation phases

Each phase ends with a concrete live-verification bar. Nothing counts
as done until it passes its bar against the real game. Every phase
carries offline tests (including malformed-input tests per the
standing rule) and goes through the pre-push self-review gate before
it is committed and pushed. Phases 2 and 3 are shared with
WOODWORKING.md phase 3 and phase 8 and FARMING_PLAN.md phase 3;
the shared phases are done once, in one place, and this doc
records which doc owns each half so the work is not done twice.

### Phase 1: Observation

* Extend the stocks collect so the snapshot can see what soap
  needs: soap bars and soap units by material, lye units in
  buckets and barrels (and frozen, if the collect can tell),
  tallow units, fat units unrendered, oil units, seed paste
  units, ash bars, potash bars, pearlash bars, jugs, and
  mechanisms, each split by material where the collect supports
  it. Add GLOB and LIQUID_MISC to the add_mat list, or an
  equivalent split, so tallow, fat, lye, and oil stop hiding in
  mixed counts.
* Add the Soap section to the snapshot (section 13.1) and the
  GET /v1/soap route (section 13.2).
* Measure the soap consumption rate: soap units at each collect
  over a season, split by wounded and unwounded windows.
* Live bar: a live collect on the main fort shows the true soap,
  lye, tallow, fat, oil, ash, and potash numbers, and each number
  matches a hand check against the game. The snapshot Soap
  section renders, and its token cost matches section 13.1
  within 20 tokens by the accountant's count. The consumption
  rate is recorded from the measurement, not guessed.

### Phase 2: Wood furnace and ash (shared, WOODWORKING.md phase 3 owns)

* Add a furnace build kind to WORKSHOP_CATALOG (wood_furnace,
  built from fire-safe stone or metal) and the build route for
  furnaces, which are a different building family from workshops
  in the enum.
* Add make_charcoal and make_ash to JOB_SPECS as hardcoded job
  types with reaction_name None, 1 log each, with the material
  rule in materials.py.
* This doc contributes the ash acceptance test for soap: the ash
  count the phase produces must be readable by the phase 1
  collect, split from other BAR items.
* Live bar (WOODWORKING.md's bar, repeated here so the shared
  phase is not marked done without it): a wood furnace is built
  live on the scratch fort, 1 log becomes 1 charcoal read back,
  and 1 log becomes 1 ash read back. A MakeCharcoal job is
  refused live when wood is at or below the hard floor, with the
  floor named.

### Phase 3: Ashery, lye, and potash (shared, WOODWORKING.md phase 8 owns the build)

* Add the ashery build kind (block, barrel, bucket components)
  and the MakeLye, MakePotashFromAsh, and MakePotashFromLye jobs
  as hardcoded job types with reaction_name None. Resolve each
  job type name to its df.job_type integer live.
* Implement the allocation rule from section 7 in the planner:
  lye to the soap floor first, potash direct second, potash from
  surplus lye third, pearlash last, with the refusals named.
* Measure the open numbers: lye units per MakeLye job, lye units
  per barrel, lye units per MakePotashFromLye job, and bars of
  soap per barrel of lye. Correct section 2.4 with the measured
  numbers.
* Live bar: an ashery is built live, 1 ash bar plus an empty
  bucket becomes lye read back in units, 1 ash bar becomes 1
  potash bar read back, and a MakePotashFromAsh job is refused
  live when lye is below the soap floor, with the floor named.

### Phase 4: Soap maker build and soap jobs (this doc owns)

* Add the soap_maker build kind to WORKSHOP_CATALOG (3 by 3,
  1 empty bucket plus 1 worthless stone) and prove the Custom
  build route: whether constructBuilding with subtype Custom
  plus the SOAP_MAKER id builds the workshop, or whether the
  route needs a different call. Document what blocked it if it
  cannot be built, and do not pretend otherwise.
* Add make_soap_from_tallow and make_soap_from_oil to JOB_SPECS,
  materials.py, and the catalog, in the same shape as make_bed:
  CustomReaction 211, 150 lye plus 150 tallow or 150 oil, with
  the material rule counting liquid and glob units, not
  containers.
* Add the make_soap task to TASK_DEFS (queue the job at the soap
  maker and wait for the CustomReaction job to leave the job
  list).
* Live bar: a soap maker is built live on the scratch fort, 150
  lye plus 150 tallow becomes 1 soap bar read back with its
  source name, and 150 lye plus 150 oil becomes 1 soap bar read
  back. A soap job is refused live when lye units are short,
  with the units named, and a soap job is refused live when
  tallow units are short, with the units named.

### Phase 5: Tallow supply (this doc owns, with HUNTING.md and ANIMAL_HUSBANDRY.md)

* Prove the butcher route: whether butchering is automatic under
  standing orders once a corpse reaches the refuse stockpile, or
  needs a queued job, and what the harness must do to make it
  happen. Add the butcher build kind and job if a job is needed.
* Add render_fat to JOB_SPECS (RENDER_FAT, CustomReaction 211)
  and probe whether the game auto-schedules it under Auto-Kitchen
  without a queue, and whether queueing it directly works. Add
  the render task to TASK_DEFS.
* Implement the tallow reserve from section 6.1 in materials.py:
  cooking tallow below the reserve is refused with the reserve
  named.
* Live bar: an animal is butchered live, its fat is rendered
  live, the tallow units are read back, and the tallow becomes
  soap through the phase 4 job. A cook job that would take
  tallow below the reserve is refused live with the reserve
  named.

### Phase 6: Oil supply (this doc owns, with FARMING_PLAN.md)

* Prove the milling reaction for seed paste at the quern, and
  add the quern build kind and the milling job.
* Add the screw_press build kind (1 by 1, 2 mechanisms) and prove
  the Custom build route a second time, on the other custom
  workshop. Add press_oil and press_oil_fruit to JOB_SPECS
  (PRESS_OIL, PRESS_OIL_FRUIT, CustomReaction 211, 150 paste or
  1 fruit plus an empty jug).
* Add the jug dependency to the observation: jugs in stock as a
  headline number, because an oil job without a jug cannot run.
* Live bar: quarry bush seeds are milled live to paste read back,
  150 paste plus a jug becomes oil read back, and the oil becomes
  soap through the phase 4 job. A press oil job is refused live
  when no empty jug exists, with the jug named.

### Phase 7: Floors, planner decisions, and briefing

* Implement the soap floor and the tallow reserve from section
  6.1, recomputed every tick from the live citizen count. Wire
  the soap shortfall rule into the planner: queue the shortfall,
  never a round number. Wire the lye need into the planner: queue
  lye when lye units are below the soap floor's need.
* Add the soaper and lye maker assignment: pick the highest
  skilled dwarf for each labor, with a backup, refusing a choice
  that would leave the still or the kitchen without a worker.
* Add the low_soap briefing (section 13.3) on its two triggers.
* Live bar: a live M1 day holds the soap floor without the model
  being asked, the soap queue equals the shortfall (not 20), and
  a soap bar is made because lye and tallow existed when it was
  queued. The low_soap briefing fires live on a forced shortage
  and names the shortage.

### Phase 8: Trade and the hospital handoff (this doc owns the trade half)

* Probe the caravan question: whether any caravan offers soap in
  0.47.05, and whether lye can be ordered in a trade agreement
  and in what quantity. Correct section 2.7 and TRADING.md with
  the answer, whichever way it goes.
* Probe whether elves accept plant oil soap. Correct section 2.7
  with the answer.
* Wire the elf filter: no tallow soap, lye, or tallow enters the
  trade stockpile in spring, enforced in code, not by the agent
  remembering.
* Hospital handoff: the soap stockpile near the hospital beds is
  placed when the hospital work lands, and the soap count the
  hospital holds becomes a line in the query route. The hospital
  itself (zones, wound cleaning, diagnosis) belongs to the
  future hospital work, not to this doc, and this phase does not
  build it.
* Live bar: a wooden item is refused from the spring trade
  stockpile live, with the elf rule named, and the caravan probe
  result is recorded in the doc with the caravan and the goods
  offered. The hospital soap stockpile is placed live once the
  hospital exists, and the query route shows the hospital soap
  count.

## 15. Refusals

The soap system refuses, and says why, in plain words:

* Never make potash from ash while lye is below the soap floor.
  Soap is health care; fertilizer waits.
* Never convert lye to potash at or below the soap floor. The
  floor is the floor.
* Never cook tallow below the tallow reserve. A roast is not
  worth a wound infection.
* Never queue soap by counting containers. Lye, tallow, and oil
  are counted in units; a barrel of lye is not a number of lye.
* Never queue a round-number batch of soap. The queue is the
  shortfall, and 20 soap jobs for a 3 bar problem is a refusal,
  not a strategy.
* Never claim a soap, lye, tallow, ash, or potash stock the
  collect cannot read. An unread number is UNVERIFIED, not zero.
* Never build the soap maker from wood. The raw says worthless
  stone only; a wood build is not a soap maker, it is a failed
  job the harness should have refused.
* Never store lye outside in cold weather. Frozen lye is not
  lye the soap maker can use.
* Never offer tallow soap, lye, or tallow to elves, in any
  season, and never put soap of any kind in the spring trade
  stockpile until the oil soap probe answers.
* Never assume soap can be bought. Until the phase 8 probe
  proves a caravan sells it, the plan is to make it.
* Never claim a butcher, render, press, or mill job the harness
  cannot queue. If the job has no JOB_SPECS entry, the harness
  says it cannot do it, and does not queue a reaction by that
  name.
* Never spend ash below the wood hard floor. The bed and barrel
  floors come before soap, because a dwarf with no bed and no
  drink is worse off than a dwarf with no soap.
* Never put the wood furnace next to the food stockpile full of
  wooden barrels of drink and lye. Fire in that stockpile is a
  fort-ending event.

## 16. Open questions (UNVERIFIED)

1. **Soap consumption rate.** How many soap units does one wash
   or one wound cleaning consume, and how many uses does one 150
   unit bar cover? The wiki says cleaning jobs consume varying
   quantities; the numbers are unmeasured. Phase 1 measures it.
2. **Dirtiness read.** Can the harness read a dwarf's internal
   dirtiness level from the game state? The mechanic is real;
   the read route is unproven. If it cannot be read, the floor
   in section 6.1 stands as the sizing rule.
3. **Worthless stone.** What counts as worthless stone on this
   fort's map, and does the fort hold any? The soap maker build
   needs it, and the snapshot carried stone 0 on 2026-11-27.
   Answered by live observation, not by guessing.
4. **Lye unit counting.** Can materials.py count lye units in a
   bucket or a barrel from the stocks collect, and can the
   collect tell lye apart from oil and other liquids? The
   collect has no LIQUID_MISC split today. Phase 1 proves it.
5. **Hardcoded job type integers.** What are the df.job_type
   integer values for MakeLye, MakePotashFromLye,
   MakePotashFromAsh, MakeAsh, and MakeCharcoal? The enum
   fixture names them; JOB_SPECS needs integers. Phase 2 and
   phase 3 resolve them live.
6. **Lye units per job and per barrel.** How many lye units does
   one MakeLye job produce, how many units does one barrel hold,
   and how many lye units does one MakePotashFromLye job
   consume? The wiki's three numbers (100 per barrel, 150 per
   soap bar, 10 bars per barrel) do not fit together. Phase 3
   measures all three.
7. **Lye freezing on this fort.** Does the embark climate freeze
   lye, and is any lye ever stored outside? The mechanic is real;
   whether it bites here is unproven. Answered by live
   observation.
8. **Butcher route.** Is butchering automatic under standing
   orders once a corpse reaches the refuse stockpile, or does it
   need a queued job at a butcher's shop, and can the harness
   drive it? No butcher job exists in JOB_SPECS. Phase 5 probes
   it.
9. **Tallow per animal.** How much fat, and how much tallow,
   does a typical hunted animal yield? The soap reaction takes
   150 tallow per bar, so the answer decides how many hunts one
   bar of soap costs. Answered by live observation.
10. **Olive trees.** Does the fort's biome have olive trees, and
    can olives be gathered or grown? The oil path through fruit
    depends on it. Answered by live observation and the plant
    raws.
11. **Seed milling reaction.** What is the exact reaction name
    for milling seeds to paste at a quern or millstone? The
    farming plan names the building; the reaction name is
    unverified. Phase 6 proves it.
12. **Lye trade.** Can lye be ordered in a trade agreement in
    0.47.05, in what quantity, and does any caravan actually
    bring it? The wiki says it can be ordered and a caravan
    barrel holds 10 units. Phase 8 probes it.
13. **Oil soap and elves.** Do elves accept plant oil soap, or
    does the ban cover all soap? The ban list names tallow soap
    explicitly; oil soap is not named. Phase 8 probes it, and
    until then no soap goes to elves.
14. **Custom workshop build route.** Can build_workshop build
    SOAP_MAKER and SCREW_PRESS through constructBuilding with
    subtype Custom plus the custom building id, or does the
    custom workshop family need a different call? act_build.lua
    resolves subtypes through df.workshop_type, which has no
    SOAP_MAKER entry. Phase 4 probes it.
15. **Render fat queueing.** Does queueing RENDER_FAT as a
    CustomReaction work, or does the AUTOMATIC flag mean the game
    only schedules it itself under Auto-Kitchen? And does the
    game's Auto-Kitchen already render fat without the harness
    asking? Phase 5 probes both halves.
16. **Soap material token.** What does dfhack.matinfo return for
    a soap bar, and can the stocks collect filter BAR items by
    it to count soap apart from metal bars? The BAR count mixes
    them today. Phase 1 proves it.
17. **Soap quality.** Does soap making skill change anything
    about the bar: quality levels, units, or value? The wiki
    says sheets of paper have quality levels while other screw
    press products do not; for soap it says nothing. Answered by
    live observation, not by guessing.
18. **Hospital soap consumption.** Once the hospital exists, how
    much soap does wound cleaning consume, and does the hospital
    pull soap from the nearest stockpile on its own? The
    hospital work is future work; the question is recorded here
    so it is not lost.

## 17. Cross-doc conflicts flagged

Four conflicts, each with the correction this doc proposes. None
is resolved by this doc alone; each needs the owning doc to
accept the correction or the live probe to settle it.

1. **FARMING_PLAN.md, section 8.1: "Potash is also used for
   soap."** Wrong as stated. Soap uses lye, not potash. What is
   true is that potash and lye compete for the same ash, and lye
   can be converted into potash. Proposed correction: the farming
   plan says potash and soap compete for ash, and points at the
   allocation rule in section 7 of this doc. The fertilizer
   decision stays with the farming plan; the shared input rule
   lives here.
2. **HUNTING.md, section 7.2: "The harness keeps a soap reserve
   and refuses to cook tallow below it."** Not implemented. No
   soap count, no tallow count, and no reserve exist in the code
   (section 4). The sentence is a design intent, not a
   mechanism. Proposed correction: the hunting doc marks the
   sentence as a requirement on this doc's phase 5 and phase 7,
   and this doc implements the reserve there. Until then the
   claim is removed or marked UNVERIFIED.
3. **KITCHEN.md, sections 2.6 and 6: tallow as a filler cooks
   prefer, and rendering as the cook-training route.** This doc
   reverses the ranking: tallow is soap first, food second, and
   rendering is production, not training. Proposed correction:
   the kitchen doc keeps training as a side effect of rendering,
   and this doc's reserve rule in section 8 arbitrates the
   conflict in code. The cook still gets tallow above the
   reserve; the rule is a floor, not a ban.
4. **TRADING.md, section 5: soap on the buy list as hospital
   stock, against the Soap page: "soap is one not traded in
   caravans".** One of them is wrong for 0.47.05. Proposed
   correction: neither doc asserts the answer until the phase 8
   probe checks a caravan's goods. This doc plans as if soap
   must be made; the trading doc marks its soap buy-list entry
   UNVERIFIED until the probe answers.
5. **WOODWORKING.md phase 8 and FARMING_PLAN.md phase 3 both
   claim the ashery build and the potash job.** Two docs own the
   same build. Proposed correction, agreed in section 14: the
   build is done once, owned by WOODWORKING.md phase 8 as the
   wood-side work, the fertilizer decision stays with
   FARMING_PLAN.md phase 3, and the lye allocation and soap jobs
   are owned by this doc. No doc redoes the build.

## 18. Sources

Wiki pages read from the local index
(`~/workspace/df-wiki-export/dfq.py`, hybrid search, 2026-11-27).
The index is a current-wiki export (4,485 pages, built 2026-11-24),
so pages can carry v50 markers; every claim below that depends on
the version was checked against the 0.47.05 raws or the live
runtime enum, and the check is named where it matters.

* Soap: soap as a bar, the happy thought, infection, hospitals,
  150 units per bar with partial consumption, the two-component
  manufacture, the tallow and oil paths, the work-orders warning
  about lye-containing items, the "not traded in caravans" line,
  the name by source, dirtiness, bath-houses, the flowchart.
* Soap maker's workshop: 3 by 3, bucket plus non-economic building
  material, Soap making labor, the tallow or oil tooltip.
* Soaper: Farmer profession, Soap Maker title, Soap making labor,
  strength, toughness, endurance, kinesthetic sense.
* Ashery: block plus barrel plus bucket, Potash making and Lye
  making labors, the four tasks, lye for soap, potash for
  fertilizer and pearlash, milk of lime for parchment.
* Lye: 1 ash bar plus an empty bucket, made by a lye maker at an
  ashery, moved to barrels in a food stockpile, up to 100 units
  per barrel per the page, 10 units per caravan barrel, freezing
  in cold weather, orderable in trade agreements, the work-orders
  condition fix.
* Potash: fertilizer and pearlash, ash to potash directly or
  through lye, less time direct.
* Tallow: rendered fat from a kitchen, fat from butchering,
  Auto-Kitchen enabled by default, tallow eaten by default unless
  unchecked as food, stored under fat up to 50 units per barrel,
  ROTS token but never rots, low-value cooking ingredient.
* Screw press: 2 mechanisms, Mechanic labor, pressing skill,
  seed pastes and olives to oil, empty jugs required, press cake
  byproduct, honey and wax, slurry to paper.
* Health care: soap used to clean wounds, sterilizing and
  preventing infection, water for cleaning and bathing.
* Soap/flowchart: the full procedure table, chop wood to ash to
  lye, butcher to render to tallow, mill to press to oil, combine
  at the soap maker's workshop.

0.47.05 raws, read from the shipped game
(`third_party/df_47_05/raw/objects/`):

* building_custom.txt: the only two raw-defined workshops,
  SOAP_MAKER (3 by 3, BUILD_LABOR SOAP_MAKER, 1 empty bucket
  plus 1 WORTHLESS_STONE_ONLY build material) and SCREW_PRESS
  (1 by 1, BUILD_LABOR MECHANIC, 2 mechanisms).
* reaction_other.txt: RENDER_FAT (kitchen, 150 fat, AUTOMATIC,
  skill COOK), MAKE_SOAP_FROM_TALLOW (150 lye plus 150 tallow,
  1 soap bar dimension 150, skill SOAP_MAKING),
  MAKE_SOAP_FROM_OIL (150 lye plus 150 oil, 1 soap bar,
  skill SOAP_MAKING), PRESS_OIL (150 paste plus empty jug, oil
  plus press cake, skill PRESSING), PRESS_OIL_FRUIT (1 olive
  fruit plus empty jug, oil plus press cake), MAKE_MILK_OF_LIME
  (quicklime plus bucket, skill LYE_MAKING), MAKE_PEARLASH
  (potash plus fuel, skill SMELT). No MAKE_LYE or MAKE_POTASH
  reaction exists in any reaction file, which proves those jobs
  are hardcoded.
* material_template_default.txt: SOAP_TEMPLATE (material value 1,
  SOAP_LEVEL 2, IMPLIES_ANIMAL_KILL), TALLOW_TEMPLATE (material
  value 1, ROTS, SOAP_MAT product), PLANT_SOAP_TEMPLATE for
  plant oil soap, RENDER_MAT on fat.
* entity_default.txt: PERMITTED_JOB SOAP_MAKER and LYE_MAKER,
  PERMITTED_BUILDING SOAP_MAKER, PERMITTED_REACTION
  MAKE_SOAP_FROM_TALLOW and MAKE_SOAP_FROM_OIL, for the
  dwarven entity.
* The live runtime enum
  (tests/fixtures/runtime-enums-0.47.05-r8.json): MakeLye,
  MakePotashFromLye, MakePotashFromAsh, MakeCharcoal, MakeAsh
  as job types; Ashery as a workshop type; WoodFurnace and Kiln
  as furnace types; SOAP_MAKER and SCREW_PRESS absent from
  workshop_types, present only as custom building definitions.

Harness state verified against the repo on 2026-11-27:

* actions.py JOB_SPECS (12 jobs: brew, brew_fruit, cook, 9
  carpenter), WORKSHOP_CATALOG (carpenter, mason, still,
  kitchen), queue_job (material fail-fast, already-queued
  count, job id verification), build_workshop.
* materials.py (no soap, lye, tallow, oil, ash, or potash rule;
  _WOOD_1, _BARREL_1, brew and carpenter checks only).
* planner.py (no soap decision; bed and barrel floors only).
* daemon.py TASK_DEFS (brew, cook, make_bed, make_barrel,
  gather, farm; no soap task).
* stocks.lua (headline counts for drink, food, seeds, wood,
  stone, cloth, thread, metal bars, barrels, empty barrels,
  bins, buckets; by_material for 10 item types only, excluding
  GLOB and LIQUID_MISC; trader-held goods excluded).
* assembler.py TokenAccountant (count at length divided by 3,
  TARGET 30000, WARNING 60000, COMPACTION 100000, NEVER 140000),
  the Stocks line and Buildings line.
* catalog.py (built by introspection from ACTIONS and JOB_SPECS;
  no soap entry).
* briefings.py (10 kinds, low_drink and low_food as the shape
  the low_soap briefing follows).
* diagnose.py (no soap fix).
* placement.py (no soap weights).
* lua/act_job.lua (job_type int plus optional reaction_name;
  CustomReaction 211 with a reaction name).
* lua/act_build.lua (type Workshop, subtype resolved through
  df.workshop_type; unknown subtype errors).
* docs/WOODWORKING.md sections 2.4, 2.5, 3, 9 and phase 8 (ash,
  charcoal, ashery chain, the wood side, the log spend).
* docs/FARMING_PLAN.md section 8 and phase 3 (potash chain,
  fertilizer, quarry bush oil crop).
* docs/KITCHEN.md sections 2.6 and 6 (rendering, tallow as a
  filler cooks prefer).
* docs/HUNTING.md section 7.2 (fat to tallow to soap, the soap
  reserve claim).
* docs/ANIMAL_HUSBANDRY.md (fat rendered to tallow, cooked or
  made into soap).
* docs/TRADING.md sections 2.5 and 5 (elf refusal of tallow soap
  and lye, soap on the buy list).
* docs/STOCKPILES.md (soap in Bar/Block stockpiles, lye in food
  stockpiles).
* docs/PLANNER.md (hospital zones not implemented, UI-only).
* docs/CLOTHING.md section 2.3 (building_custom.txt defines
  exactly two workshops, SOAP_MAKER and SCREW_PRESS).
* Coordinator log 2026-11-27 and the 18:10 PT presentation
  direction (snapshot stays an index at about 4,700 tokens
  typical, budgets hold, Model presentation required in every
  breadth doc, 6 MCP tools, the opportunities mechanism not
  implemented per gap review 3 P2-3).
