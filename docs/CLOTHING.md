# Clothing

The clothing chain turns fiber, wool, silk, and hides into clothes,
and keeps dwarves covered as those clothes wear out. It is the
slowest-moving survival system in the fort: a dwarf without drink
slows down in a season, a dwarf without clothes gets unhappy
thoughts that stack until the fort tantrums. The chain is also the
fort's best trade good once it runs, and its raw material is the
same pig tail the still wants to brew.

This document is the design record for a smart clothing system. The
harness does the counting, the coverage check, and the scheduling.
The agent picks from a small set of named options with a one-line
why. Nothing here is guessed: every mechanic is cited from the wiki
pages in Sources, from the 0.47.05 raws in the repo, or from a live
verification against the game, and anything not verified is marked
UNVERIFIED.

Related design records: docs/FARMING_PLAN.md (pig tail and dimple
cup seasons, the split rule that decides what a harvest becomes),
docs/ANIMAL_HUSBANDRY.md (shearing, butchering, hides), docs/KITCHEN.md
(the drink floor pig tail also serves), docs/STOCKPILES.md (cloth
and clothing stockpiles, including one correction in section 10.3),
docs/TRADING.md (dresses and robes as trade goods, worn clothing
sales), docs/LABOR.md (the textile labors), docs/MILITARY.md
(leather armor, uniform wear Bug 6039).

## 1. Purpose

The clothing system answers six questions every tick, from fresh
collects, so the agent never has to:

1. Who is uncovered, barefoot, or wearing tattered clothes, by name?
2. How much cloth, thread, leather, and dye does the fort hold, and
   where is the chain stuck?
3. What should be made next: thread, cloth, or finished clothes?
4. What must the chain never consume, and why?
5. How many garments does the fort need, and what is stopping it
   making them?
6. What worn clothing can be sold, and what must be kept?

If the harness cannot answer one of those from real state, it says
so instead of inventing an answer.

## 2. How clothing works in DF 0.47.05

All of this section is from the wiki pages listed in Sources, checked
against the 0.47.05 raws where the raws settle it. Where the wiki
export tracks v50 and 0.47.05 may differ, the claim is marked
UNVERIFIED and the difference is named.

### 2.1 Clothes are armor level 0

Within the game engine there is no fundamental difference between
clothing and armor. Clothes are the soft items with no ARMORLEVEL
token in the item raws, which means armor level 0. The 0.47.05 raws
(`third_party/df_47_05/raw/objects/item_armor.txt`) list three
armored items with an ARMORLEVEL token (breastplate 3, mail shirt 2,
leather armor 1) and nine soft upper-body items with none: coat,
shirt, cloak, tunic, toga, cape, vest, dress, robe. The same split
holds for the other slots: shoes, socks, and sandals are footwear;
gloves and mittens are handwear; caps, hoods, turbans, masks, and
veils are headwear; trousers, skirts, loincloths, and braies are
legwear. The clothier's shop in 0.47.05 makes cap, cloak, coat,
glove, hood, loincloth, mitten, robe, shirt, shoe, sock, trousers,
tunic, and vest (Clothier's shop).

Two consequences follow. First, the stocks read counts upper-body
clothing under item type ARMOR, not under a CLOTHING type: there is
no CLOTHING item type in the live enum. A count of "clothes on hand"
must sum ARMOR, PANTS, SHOES, GLOVES, and HELM items with armor
level 0, and must exclude armor level 1 and above. Second, the job
types that make clothes are the same five that make armor pieces:
MakeArmor, MakePants, MakeGloves, MakeHelm, MakeShoes. There are no
MakeShirt, MakeDress, or MakeRobe job types in the live runtime enum
(`tests/fixtures/runtime-enums-0.47.05-r8.json`, 241 job types). How
the game picks which garment a MakeArmor job makes is UNVERIFIED
(see section 18, open question 1). The working hypothesis is that
the job carries the item subtype (ITEM_ARMOR_SHIRT and the like),
and phase 2 proves or kills it live.

### 2.2 The chain, end to end

The textile chain has eight jobs (Textile industry): growing, plant
processing, shearing, spinning, weaving, clothes making, milling,
and dyeing. In order:

1. **Grow or gather the fiber.** Pig tail underground (summer and
   autumn), rope reed, flax, hemp, cotton, ramie, jute, kenaf above
   ground. Or shear a sheep, llama, alpaca, or tame troll. Or
   collect spider webs.
2. **Process plants into thread** at a farmer's workshop (thresher
   skill, produces seeds). **Spin wool or hair into thread** at a
   farmer's workshop (spinner skill). **Collect webs** at a loom:
   dwarves with the weaving labor gather webs and spin them into
   silk thread in one step.
3. **Weave thread into cloth** at a loom (weaver skill). Every item
   of thread woven produces one item of cloth.
4. **Make clothes from cloth** at a clothier's shop (clothesmaker
   skill). Each job consumes one whole unit of cloth, regardless of
   the size of the piece produced. Paired items (shoes, gloves,
   socks, mittens) are made in pairs, though the quality levels of
   the two created items can differ.
5. **Dye thread or cloth** at a dyer's shop (dyer skill). Dye cannot
   be applied to finished clothing, so dyeing happens before the
   clothier, never after.

The leather chain runs in parallel (Leather, Tanner's shop):

1. **Butcher an animal.** Each butchered animal yields a single raw
   hide (smaller animals never produce one).
2. **Tan the hide** at a tanner's shop (tanning labor). Each unrotten
   hide yields one or more units of leather by animal size: 1 for
   cat, dog, goat, sheep, pig, alpaca, reindeer, llama, and donkey;
   2 for mule, horse, cow, and yak; 2 to 3 for water buffalo; 7 for
   elephant; 10 for giant elephant.
3. **Make leather goods** at a leather works (leatherworking labor).
   One whole unit of leather per job, same rule as cloth.

### 2.3 Workshops are hardcoded, all but two

The 0.47.05 workshop list for this chain is: loom, clothier's shop,
leather works, tanner's shop, dyer's shop, farmer's workshop, quern,
and millstone. Verified against the 0.47.05 raws in the repo:
`third_party/df_47_05/raw/objects/` holds exactly one workshop
definition file, `building_custom.txt`, and it defines exactly two
workshops, SOAP_MAKER and SCREW_PRESS. Every other workshop in the
chain is hardcoded in the game, not raw-defined, and the live
workshop enum (`tests/fixtures/runtime-enums-0.47.05-r8.json`)
lists all of them: Carpenters, Farmers, Masons, Craftsdwarfs,
Jewelers, MetalsmithsForge, MagmaForge, Bowyers, Mechanics, Siege,
Butchers, Leatherworks, Tanners, Clothiers, Fishery, Still, Loom,
Quern, Kennels, Kitchen, Ashery, Dyers, Millstone, Custom, Tool.
The v50 wiki workshop lists are not the authority here; the raws
and the live enum are.

Build requirements, from the wiki workshop pages:

* **Loom** (b-o-l-o): any building material, built by a dwarf with
  the Weaving labor. Menu: Collect Webs, Weave Cloth (Plant
  Thread), Weave Silk Cloth, Weave Cloth (Wool/Hair Yarn), Weave
  Metal Cloth.
* **Clothier's shop** (b-o-l-k): any building material, built by a
  dwarf with the Clothesmaking labor. Uses cloth, wool cloth
  (called Yarn in the job menu), or silk cloth.
* **Leather works** (b-o-l-l): any building material, built by a
  dwarf with the Leatherworking labor. Uses leather.
* **Tanner's shop** (b-o-f-t): any building material, built by a
  dwarf with the Tanning labor. Uses a raw hide, and milk of lime
  for parchment.
* **Dyer's shop** (b-o-l-y): needs a barrel and a bucket to build,
  built by a dwarf with the Dyeing labor. Uses dye powders plus
  thread, cloth, or leather.
* **Farmer's workshop** (b-o-f-f): any building material, built by
  a dwarf with Plant processing, Milking, Shearer, Spinner, or
  Cheese making enabled. The textile jobs there are Process Plants,
  Shear Creature, and Spin Thread.
* **Quern and millstone**: mill dye plants into dye powder (miller
  skill, produces seeds).

### 2.4 Size

Clothing is sized for the creature that does the job. Equipment
made for one size of creature cannot be worn by a sufficiently
larger or smaller creature: the acceptable range is plus or minus
one seventh of the creature's size (Clothing). Goblins and elves
are the same size as dwarves, so their clothing can be worn by
dwarves; humans and trolls are large, kobolds are small. Clothing
with no large or small marker is one-size-fits-all and can be worn
by any dwarf, child or adult. A dwarf-made garment is dwarf-sized
by default, which is what the fort needs. Making clothes for a
non-dwarven resident needs the size specified on the job, through
the job details in the UI. Whether the harness can specify size
on a queued job is UNVERIFIED (section 18, open question 2).

Dwarven clothing is gender-insensitive: a male dwarf may wear a
dress, a female may wear trousers. The harness never plans
garments by sex.

### 2.5 What dwarves can make, and what they cannot

Dwarves can produce shoes, but not sandals: sandals are in the same
clothing class, but dwarves can produce only shoes, and sandals
must be stripped from dead or captured enemies (Clothing). The
clothier's list in section 2.1 is the producible set. Anything
outside it (sandals, chausses, turbans, greaves, thongs) comes from
trade, migrants, or the dead, never from the clothier.

## 3. The textile chain in detail

### 3.1 Fiber sources

**Plant fiber.** Eight crops process into thread at a farmer's
workshop (Textile industry). The underground crop is pig tail
(summer and autumn, also brewable into dwarven ale). The above
ground crops are rope reed (all seasons, also brewable), flax,
hemp, cotton, ramie, and jute. Flax and hemp can also be milled
into flour, and hemp, rope reed, cotton, and kenaf can be pressed
for oil. Pig tail is the fort's only underground thread crop, and
it is also a brew crop: the split rule (docs/FARMING_PLAN.md,
section 10.1) decides what each harvest becomes, and the clothing
system owns the thread share of that decision (section 7.3).

**Wool.** Sheep, llamas, and alpacas can be sheared at a farmer's
workshop, once every 300 days per animal (Sheep; Textile
industry). Tame trolls can also be sheared. Wool has only half the
value of plant-based thread. Shearing is owned by the animal
husbandry plan (docs/ANIMAL_HUSBANDRY.md, section 6.2); this doc
owns what the yarn becomes. Ewes can also be milked, so a sheep is
wool, milk, and meat in one animal.

**Hair.** Butchering certain animals (horses, yaks, grizzly bears)
yields hair as a byproduct. Hair can only be made into thread, and
never into cloth or clothing. Its use is suturing material for the
hospital, and bookbinding. The harness never weaves hair thread
and never counts it toward the clothing supply.

**Silk.** Raw silk is harvested from spider webs: phantom spiders,
cave spiders, and brown recluse spiders (vermin, webs collected by
the automatic Collect Webs job at a loom) and giant cave spiders
(caverns, dangerous). Vermin silk thread is worth half as much as
plant thread (6 versus 12). Giant cave spider silk thread is worth
twice as much as pig tail thread (24). The current fort holds a
large silk stock already: the 2026-11-27 M1 snapshot's by-material
list shows 163 cave spider silk thread and 107 giant cave spider
silk thread, and no loom to weave it with. That is the chain stuck
at step one, and the first thing the clothing system fixes.

### 3.2 Thread

Plant processing (farmer's workshop, thresher skill) turns a plant
into thread and produces seeds. Spinning (farmer's workshop,
spinner skill) turns wool or hair into thread. Silk thread comes
from webs at the loom, in one step. Thread's uses are suturing at
a hospital, decorating finished clothing, and weaving into cloth.
For animal hair, thread itself is the finished product.

Two standing-order facts matter. First, by default any non-hair
thread produced is automatically queued for weaving at a loom,
and plant fibers are queued as soon as they are processed. The
harness must be able to see and control that automation, or the
loom will eat thread the hospital needs for sutures (section 13).
Whether the standing orders are readable and writable from Lua
is UNVERIFIED (section 18, open question 3). Second, hair thread
cannot become cloth: there is no task that turns hair thread into
usable cloth (Loom).

### 3.3 Cloth

Every item of thread woven produces one item of cloth. Cloth can
be dyed directly, and thread can be dyed before weaving; dyed
objects cannot be redyed. If the fort wants dyed cloth, the dyer
works before the weaver or after the weaver, never after the
clothier.

The clothier ignores cloth in bins. This is a quirk on the
Clothier's shop page, and it is load-bearing for stockpile design:
a cloth stockpile that permits bins starves the clothier. The
stockpile plan must keep the clothier's feed stockpile bins-free
(section 10.3). Whether this quirk holds live in 0.47.05 is
UNVERIFIED (section 18, open question 4); phase 7 proves it.

### 3.4 Dye

Dye plants are milled at a millstone or quern (miller skill,
produces seeds) or processed at a dyer's shop (thresher skill,
does not produce seeds). Each plant processed into dye creates 1
unit of dye, enough to dye 1 unit of thread or cloth, and milling
needs an empty bag to hold the dye. Dye values: dimple dye 20,
emerald dye (blade weed) 20, sliver dye (sliver barb) 20, redroot
dye (hide root) 10. Dimple cups grow underground in all seasons
but slowly; blade weed and hide root grow above ground in all
seasons; sliver barb grows only in evil areas and is also brewable.

Dyeing is a value play, not a need: dwarves do not demand colorful
clothes. A no-quality dye adds 20 value, a masterful dyeing adds
240 (Textile industry). Dyeing happens only from surplus dye
plants, never from the seed reserve, and never before the fort has
cloth to dye. The dyer is the last workshop in the chain to build,
not the first.

### 3.5 Value

Dresses and robes have the highest base value of the cloth goods,
and are the best choice for textile trade goods (Textile
industry). The cloth item value formula sums the item value (type
times material times quality), the cloth quality as a decoration,
the thread value, the dye value, and any embroidery. Skill at three
steps sets the value: weaving, dyeing, and clothesmaking. A
skilled dyer adds more value than a better material at low
quality: the textile page notes that for low-quality production,
skillful dyeing adds more value than giant cave spider silk does.
Embroidering an item almost always generates less value than
making a second piece of clothing, so the harness never
embroideries for value. The exact theoretical maximum quoted on
the wiki (a masterful giant cave spider silk robe at 3064) is
wiki-sourced and UNVERIFIED live; the doc uses the formula and
the ordering (robes and dresses first, dyeing before embroidery),
not the number.

## 4. The leather chain in detail

### 4.1 Hides

A butchered animal yields one raw hide, and only if the animal is
large enough: smaller animals never produce a hide, so there is no
kea or rat leather (Leather). The hide is a byproduct of the meat
industry, owned by the animal husbandry plan; the clothing system
takes the hide as its input and never slaughters an animal for
hide alone while the fort is short of meat. Rotten hides cannot
be tanned, so a hide left rotting is leather lost: the tanner must
run promptly after butchering.

### 4.2 Tanning

The tanner's shop turns a hide into leather. The "Tan a hide" job
is automatically triggered after the game notices a skin within a
certain distance of the tanner's shop, and the automation can be
turned off in standing orders ("Automate tannery"). The manager
can also queue "Tan a Hide" jobs manually. Tanning is a reaction
in the raws, TAN_A_HIDE (`reaction_other.txt`), not a job type:
there is no TanHide entry in the live job enum. The harness queues
it the same way it queues brewing, as CustomReaction (job type
211) plus the reaction name. The live reaction index for
TAN_A_HIDE is UNVERIFIED (section 18, open question 5); the
brew reaction was probed live as index 44, and the tan reaction
needs the same probe.

Parchment is the second tanner product: skin plus milk of lime.
It is a library input, not a clothing input, and the clothing
system never spends a hide on parchment while the fort is short
of leather.

### 4.3 Leather goods

The leather works makes leather clothing, leather armor, shields,
quivers, backpacks, waterskins, bags, and decorations. The split
between leather clothing and leather armor matters, because the
two are stored and worn differently (section 5.4). Leather armor,
leather leggings, leather boots (high and low), and leather helms
are armor: civilians will not pick them up and wear them, they do
not wear out over time (but can suffer wear in combat), and they
belong in armor stockpiles, not finished goods stockpiles
(Clothing). The remaining leather goods are clothing and finished
goods. Exactly which leather works menu items are clothing and
which are armor in 0.47.05 is UNVERIFIED (section 18, open
question 6); phase 2 enumerates the menu live and records the
split.

Leather is practically essential for a well-rounded military even
apart from clothing: it is the only sensible option for quivers
and backpacks, the alternative being adamantine (Leather). The
clothing system owns the civilian leather share; the military plan
owns quivers and backpacks, and the two must not bid against each
other for the same hide. The rule is in section 7.4.

## 5. What dwarves need and when

### 5.1 The three coverings

An adult dwarf gets unhappy thoughts from four clothing failures,
and the thoughts stack (Clothing):

* Total nudity.
* Missing upper body covering: shirt, tunic, vest, dress, robe,
  cloak, or coat.
* Missing lower body covering: trousers or skirts.
* Missing footwear: shoes, sandals, or socks.
* Wearing tattered clothing: items with X or XX wear, but not
  lowercase x wear.

Babies do not wear clothes. All adult and child dwarves claim and
wear clothing when available, automatically. Armor assigned to the
relevant body areas also prevents the negative thoughts, and has
the advantage of not being subject to wear. Footwear has a second
job: it keeps dwarves from stepping barefoot in contaminants that
can be dangerous.

The coverage check the harness runs is exactly these three slots
per dwarf: upper body covered, lower body covered, footwear
covered, plus a tattered flag for anything at X or XX. Headwear
and handwear are not needed for happiness. Gloves, mittens, caps,
and hoods are warmth, protection, and trade value, not coverage.
The harness makes them only after the three coverings are met, or
for trade, never before.

### 5.2 Wear and replacement

Wear is degradation over time, marked x, X, XX. One level of wear
costs 806400 wear points (Wear). Value falls 100 percent, 75
percent, 50 percent, 25 percent across the levels, then the item
is destroyed. Clothing worn by a dwarf wears from normal use,
regardless of material. Items of creature or plant material wear
one level per 100 years even sitting in a stockpile. Artifacts
never wear: their wear level is locked at zero. Armor does not
wear over time, unless it is put in a refuse stockpile. Never
store armor in refuse (Wear; docs/STOCKPILES.md, section 9.1).

The rate at which worn clothing gains wear levels is UNVERIFIED
for 0.47.05, and the wiki is a trap here: the Clothing page in the
v50 export says one level per ten years while worn, and notes
that this is a change from previous versions, where it was one
level per two years. The 0.47.05 rate is therefore most likely two
years, not ten, but that is an inference from the version note,
not a verified fact. Phase 1 measures it live from the fort's own
worn items (section 18, open question 7). Until it is measured,
the harness plans replacement on the observed wear in the
collect, never on a calendar: a garment at X is replaced now,
whatever the calendar says. The stored-clothing rate (one level
per 100 years, or per 20 years under DFHack) is likewise
UNVERIFIED for this DFHack version.

Dwarves try to replace their worn clothing themselves, if
appropriate clothing is available in the fortress (Clothing,
citing a forum post). That claim is wiki-sourced and UNVERIFIED
live; phase 5 watches it happen or not on the live fort. The
harness never assumes self-replacement works: it counts uncovered
and tattered dwarves every tick, and if a dwarf stays tattered
while a replacement sits in the stockpile, that is a named
problem, not a shrug.

Worn clothing issued as a military uniform is NOT replaced
(Bug 6039). The harness must watch uniform wear and reissue, not
assume the game does it (Wear; docs/MILITARY.md). A militia
dwarf in tattered uniform clothing is a clothing problem the
military plan surfaces and this plan fixes by reissue.

### 5.3 The replacement cycle

Clothing is a flow, not a stock. Every garment in the fort is on
its way from new to x to X to XX to destroyed, and the fort must
make new garments at least as fast as old ones cross into X. The
harness tracks the flow in three numbers, all from the fresh
collect:

* **New garments on hand**, by slot (upper, lower, footwear,
  handwear, headwear), unowned and in the finished goods
  stockpile.
* **Worn garments in use**, by wear level, from the per-dwarf
  coverage read.
* **Garments crossing into X per season**, from the wear samples
  the store keeps over time.

The production target follows from the flow: make enough garments
per season to cover new arrivals plus the garments crossing into
X, plus one spare per slot per dwarf as a buffer. Section 7 gives
the arithmetic. A fort that makes clothes only when a dwarf is
already naked is a fort that is always one garment behind.

### 5.4 Owned clothing and the bedroom problem

Dwarves store their personal clothing in their rooms, on the floor
or in cabinets. Owned clothing cannot be claimed or hauled by
other dwarves, though if not currently worn or in the owner's
quarters, it eventually reverts to unowned after one season,
making it available. Owned clothing stored in cabinets zoned as
part of a dwarf bedroom never reverts to unowned in the current
version, so tattered clothing accumulates in bedrooms (Clothing).
Tidy dwarves rarely relinquish their tattered clothing at all,
instead accumulating a large collection of worn clothes in their
rooms. Dwarves drop worn clothing wherever they happen to be when
they decide to pick up replacements, and the discarded clothes are
owned items that cannot be easily moved (Bug 6048, Bug 4403).

Three consequences for the harness. First, the per-dwarf coverage
read must count what a dwarf is wearing, not what the stockpile
holds: a fort with 20 shirts in the stockpile and 5 naked dwarves
is a distribution problem, not a production problem, and the
harness must say which. Second, forbidding an item clears its
ownership after some weeks (forum-sourced, UNVERIFIED live), which
is the only clean way to reclaim a tattered garment from a
bedroom; the harness never forbids a garment a dwarf is currently
wearing. Third, DFHack provides a "cleanowned" command to help
clean up the clutter. Whether the harness may call it is
UNVERIFIED (section 18, open question 8); it is not used until
the probe answers it.

### 5.5 What dwarves need, in order

1. **Footwear first.** Bare feet step in contaminants, and missing
   footwear is one of the three unhappy thoughts. Shoes are also
   the cheapest garment: one cloth makes a pair.
2. **Upper body second.** A shirt, tunic, vest, dress, robe, cloak,
   or coat. One cloth each.
3. **Lower body third.** Trousers or a skirt. One cloth each.
4. **Replacements for X and XX.** A tattered garment is an unhappy
   thought even when the dwarf is covered. Replace at X; never let
   a garment reach XX while a replacement exists.
5. **Handwear and headwear last.** Gloves, mittens, caps, hoods.
   Protection and value, not happiness.
6. **Trade garments.** Dresses and robes for the caravan, from
   surplus only, after the fort is covered.

## 6. What the harness knows today

Verified against the repo on 2026-11-27. Everything in this section
was read from the code, not remembered.

### 6.1 What exists and works

* **Cloth and thread headline counts.** `stocks.lua` counts
  `cloth_units` and `thread_units` from IN_PLAY items, and
  `by_material` breaks CLOTH and THREAD down by material token.
  The 2026-11-27 M1 log proves the collect works: the by-material
  list read 163 cave spider silk thread and 107 giant cave spider
  silk thread on the live fort.
* **The tick snapshot does not render them.** `assembler.py`
  `_stocks` renders drink, food, wood, stone, brewable plants,
  empty barrels, and food stacks only. Cloth and thread never
  appear in the per-tick snapshot text. `observe.py` has a Stocks
  line with cloth and thread, but the assembler is what the model
  reads per tick, so the agent cannot see cloth or thread headline
  numbers without a query. That is the first gap the clothing work
  closes.
* **Workshop listing.** `buildings.lua` reports the workshop
  subtype from `df.workshop_type`, so a loom, clothier, tanner,
  dyer, or leather works that exists will appear in the Buildings
  section. The 2026-11-27 snapshot reads "Carpenters #7 (built),
  Still: none": no clothing workshop exists in the fort today.
* **Labor names.** The live labor enum holds WEAVER, CLOTHESMAKER,
  TANNER, DYER, SHEARER, SPINNER, MILLER, PROCESS_PLANT, MILK,
  MAKE_CHEESE, and LEATHER (the leatherworking labor is LEATHER,
  not LEATHERWORKER). `labor_toggle` can enable any of them, and
  `units.lua` reads labors and skills per citizen, so the labor
  half of the chain is already actuatable.
* **Job types.** The live job enum holds CollectWebs,
  ProcessPlants, ProcessPlantsVial, ProcessPlantsBarrel,
  WeaveCloth, DyeThread, DyeCloth, SewImage, ShearCreature,
  SpinThread, MillPlants, MakeArmor, MakePants, MakeGloves,
  MakeHelm, MakeShoes, MakeBackpack, MakeQuiver, MilkCreature,
  and MakeCheese. The raw job types for the chain exist in the
  game; the harness has not wired any of them up.
* **Catalog introspection.** `catalog.py` builds each action's
  plain-words `about` and `needs` text from the action table, so
  new clothing actions get catalog entries automatically and
  cannot drift from the code.
* **Shearing and butchering.** `docs/ANIMAL_HUSBANDRY.md` already
  covers shearing (sheep, llamas, alpacas, once per 300 days) and
  butchering (one hide per animal). The clothing system takes
  those as inputs and does not re-decide them.

### 6.2 What is missing (verified gaps)

* **No clothing workshop can be built.** `WORKSHOP_CATALOG` in
  `actions.py` holds exactly four workshops: carpenter, mason,
  still, kitchen. There is no loom, clothier, leather works,
  tanner, dyer, farmer's workshop, quern, or millstone. The
  harness cannot build any workshop in the clothing chain.
* **No clothing job can be queued.** `JOB_SPECS` holds brew,
  brew_fruit, cook, and eight carpenter furniture jobs. There is
  no process-plants, weave, shear, spin, tan, dye, or
  make-clothes job. `queue_job` cannot queue any job in the chain.
* **No clothing task exists.** `TASK_DEFS` in `daemon.py` holds
  exactly six composed tasks (brew, cook, make_bed, make_barrel,
  gather, farm). None is clothing. The multi-step chain
  (process, weave, cut) is inexpressible in the current task
  framework; that framework gap is a P0 in gap review 3, and the
  clothing work waits on it rather than working around it.
* **No leather, dye, or clothing counts.** `stocks.lua`
  `by_material` covers DRINK, FOOD, MEAT, FISH, PLANT, SEEDS,
  BAR, WOOD, CLOTH, and THREAD only. SKIN_TANNED (leather),
  POWDER_MISC (dye), ARMOR, PANTS, SHOES, GLOVES, and HELM are
  counted in the `by_type` table and the `items` list, but nothing
  surfaces them: no headline numbers, no material breakdown, no
  wear levels. The harness cannot currently answer "how much
  leather do we have", "how much dye", or "how many shirts".
* **No per-dwarf clothing read.** `units.lua` collects needs,
  skills, labors, wounds, relations, and job per citizen, but no
  inventory and no worn clothing. The only inventory reads in the
  repo are `probe_picks.lua` and `equip_pick.lua`, both
  pick-specific. The harness cannot currently answer "who is
  barefoot" or "who is wearing a tattered shirt".
* **No planner coverage.** `planner.py` has no clothing
  thresholds and no clothing decisions. Nothing queues a garment,
  nothing watches cloth, nothing names a barefoot dwarf.
* **No attention kinds.** `attention.py` has no clothing kinds:
  no naked dwarf, no tattered clothing, no barefoot dwarf, no
  empty cloth stock. A naked dwarf is invisible to attention
  today.
* **No briefing.** `briefings.py` has no clothing briefing kind.
  The caravan briefing mentions cloth as a need ("What you need
  (food, drink, metal, cloth)"), which is the only place clothing
  appears in guidance at all.
* **No labor floors.** `docs/LABOR.md` sets floors for brewer,
  planter, cook, miner, woodcutter, carpenter, mason, haulers,
  and medical, but none for weaver, clothesmaker, tanner, dyer,
  shearer, or spinner. The labor system cannot cover a labor it
  has no floor for.
* **No manager orders for clothing.** `manager_order_create`
  exists, but no clothing order is defined, and the reaction and
  job shapes the orders would need are the same UNVERIFIED items
  in section 18.

## 7. The clothing floor and production targets

### 7.1 The floor

The clothing floor is per dwarf, per slot, from the fresh citizen
count every time, so it moves when migrants arrive:

* **Upper body:** 1 garment per citizen, plus 1 spare per 5
  citizens.
* **Lower body:** 1 garment per citizen, plus 1 spare per 5
  citizens.
* **Footwear:** 1 pair per citizen, plus 1 spare pair per 5
  citizens.
* **Handwear and headwear:** 1 pair or piece per citizen, no
  spare, only after the three coverings are met.
* **Cloth reserve:** enough cloth on hand to make the next
  season's replacements (section 7.2), plus the hospital reserve
  (section 13), before any cloth is spent on trade garments.
* **Thread reserve:** enough thread on hand to weave the cloth
  reserve, before thread is dyed or spent on decoration.

The floor is a target, not a tripwire: the harness works toward it
every season, and treats anything below it as a standing need, not
an emergency. A naked dwarf is the emergency, and it is an
attention item, not a floor breach.

### 7.2 How many garments per season

Garments are consumed by wear, not by use. The replacement rate is
the number of garments crossing into X per season, measured from
the store's wear samples (section 5.3). Until the wear rate is
measured live (open question 7), the harness uses the observed
count, not a calendar: it replaces what is at X now, and it makes
one garment per new citizen on arrival. Once the rate is measured,
the target becomes arrivals plus crossings plus the spare buffer,
and the doc records the measured rate with the run that proved it.

The arithmetic the harness does, per season, from fresh state:

1. Citizens times 3 coverings, minus garments on hand and garments
   in use, equals the coverage shortfall.
2. Garments at X or XX, minus replacements already made, equals
   the replacement need.
3. Shortfall plus replacement need, minus cloth on hand, equals the
   cloth to weave; cloth to weave, minus thread on hand, equals the
   thread to process or spin.
4. Thread to process, minus plants and wool on hand, equals the
   fiber to grow, gather, or shear.

Each step names its input, so the agent sees "need 2 shoes: 0
cloth on hand, 270 silk thread un-woven, loom missing" instead of
"need clothes".

### 7.3 Pig tail: the shared crop

Pig tail is the fort's only underground thread crop and also a
brew crop. The farming plan's split rule (docs/FARMING_PLAN.md,
section 10.1) decides what a harvest becomes, in priority order:
brew to the drink floor, process for industry, eat raw, cook,
trade. The clothing system owns step 2 for pig tail: it claims
the thread share before cooking and before trade, and it never
claims pig tail the still needs to meet the drink floor. The claim
is computed from the floor in section 7.1: thread for the
season's garments first, then the surplus may be brewed. A pig
tail harvest brewed away while dwarves are barefoot is a planning
failure the harness must name, with the numbers, in the snapshot.

Rope reed is the above-ground counterpart: also brewable, also a
thread crop, grown in all seasons. Where the fort has rope reed,
the harness prefers it for thread and leaves pig tail for the
still, because rope reed grows year-round and pig tail grows only
in summer and autumn.

### 7.4 Leather: the shared hide

One hide is one or more leather, and leather is claimed by three
systems: clothing, the military (quivers, backpacks, armor), and
trade (leather crafts at the craftsdwarf's workshop). The claim
order is: military quivers and backpacks first (a marksdwarf
without a quiver cannot fight), civilian clothing second (the
three coverings), trade crafts last, from surplus only. The
clothing system never spends a hide on parchment while the fort
is short of leather, and never makes a leather trade good while a
dwarf is uncovered.

## 8. How the harness knows who needs what

### 8.1 The coverage read

A new observation step reads, per citizen, from the fresh full
units collect plus an inventory walk: what the dwarf is wearing in
each slot, each item's wear level, and whether the dwarf is missing
a slot entirely. The read is built on the pattern
`probe_picks.lua` already proves: walking `u.inventory` and
reading each item's type, subtype, material, and wear. What is
UNVERIFIED is the cost of the walk at 50 dwarves and whether the
wear field reads the same way for worn items as for stored ones
(section 18, open question 9). Phase 1 measures both live.

The coverage computation, per dwarf, from that read:

* **Covered:** upper body, lower body, and footwear all present
  and below X wear.
* **Barefoot:** no footwear. **Uncovered:** missing upper or lower
  body. **Naked:** missing all three.
* **Tattered:** any worn item at X or XX wear. X is replace now;
  XX is replace now and the garment is nearly destroyed.
* **Well dressed:** covered with nothing above x wear, and at
  least one item above normal quality. A well-dressed dwarf is a
  happy thought the harness counts, not a problem to fix.

Babies are excluded: they wear nothing and that is correct.
Children are included: they claim and wear clothing like adults.

### 8.2 Needs and thoughts are not the signal

Clothing neediness does not arrive through the needs system in
any way the harness has verified. `units.lua` collects
`soul.personality.needs` as (need, level, focus) triples, and no
clothing need has been identified in that read. Whether a
clothing-related need type exists in `df.need_type` for 0.47.05
is UNVERIFIED (section 18, open question 10). The harness does
not wait for it: the coverage read in section 8.1 is the signal,
and the unhappy thoughts (section 5.1) are the consequence the
diary and attention systems already know how to report. If a
clothing need is found later, it joins the read as a second
signal; it never replaces the coverage read.

### 8.3 The chain status

Beside coverage, the harness computes the chain status from the
fresh stocks collect: fiber on hand (plants by type, wool, webs),
thread on hand by material, cloth on hand by material, leather
on hand, dye on hand, garments on hand by slot, and which
workshops exist. The status names the bottleneck in one line:
"270 silk thread, 0 cloth, no loom" or "12 cloth, no clothier"
or "4 cloth, clothier idle, 2 dwarves barefoot". The bottleneck
is the next job the planner queues, and the snapshot carries it
every tick.

## 9. Workshops and layout

Layout is scored placement (docs/SITE_SELECTION.md), with
clothing-specific factors on top of the shared threat, cover, and
traffic factors:

* **The textile cluster.** Loom, clothier's shop, dyer's shop,
  farmer's workshop, quern, and the cloth and thread stockpiles
  belong together, within a few tiles of each other. Thread goes
  from the farmer's workshop to the loom, cloth from the loom to
  the clothier, dye from the quern to the dyer. A loom far from
  its thread stockpile pays the hauling cost on every cloth.
* **The leather cluster.** Tanner's shop beside the butcher, so
  hides go from shop to shop with no hauling. Leather works
  beside the tanner. The refuse stockpile for rotting hides sits
  outside the cluster, behind an airlock or outside, never in
  the traffic flow (docs/STOCKPILES.md, section 8).
* **The farm link.** The farmer's workshop sits with the textile
  cluster, not with the farms: its inputs (plants, wool, animals)
  arrive by hauling, and its outputs (thread) feed the loom next
  door. The seed stockpile stays with the farms (docs/FARMING_PLAN.md).
* **The hospital link.** The cloth and thread stockpiles sit
  within a short walk of the hospital, because bandages and
  sutures come from the same stock (section 13).
* **Web collection.** The loom that collects webs must not send
  weavers into the caverns while the caverns are unsafe. The
  standing order for web collection is off until the military
  plan clears the caverns, and the harness says so in the snapshot
  instead of letting a weaver walk into a giant cave spider.
  One loom generates one Collect Webs job; more looms collect
  faster only with enough weavers and enough accessible webs.

## 10. Stockpiles and storage

### 10.1 The stockpiles

* **Thread stockpile.** Cloth category, thread only, bins allowed
  (thread in bins is fine; the loom reads bins). Near the loom.
* **Cloth stockpile, clothier feed.** Cloth category, cloth only,
  bins 0. The clothier ignores cloth in bins (section 3.3), so
  this stockpile must never permit bins. Near the clothier, set
  to take from the loom's output stockpile only.
* **Cloth stockpile, bulk.** Cloth category, cloth only, bins
  allowed. Holds the reserve and the trade cloth. Linked to feed
  the clothier's stockpile.
* **Leather stockpile.** Leather category, bins allowed, near the
  tanner and the leather works.
* **Dye stockpile.** Food category, milled plants (dye powder in
  bags), near the quern and the dyer. Dye powder lives in bags in
  barrels; a barrel holds up to 60 dye bags.
* **New clothes stockpile.** Finished goods, armor, footwear,
  handwear, headwear, and legwear categories allowed, take from
  anywhere off, takes only from the clothier's shop. This is where
  dwarves pick up replacements (Clothing).
* **Used clothes stockpile.** Finished goods, the same categories,
  take from anywhere on, so unowned worn clothes around the fort
  are hauled here. Kept separate from new clothes: there is no
  setting that stockpiles only new clothing, so new clothing is
  taken from the clothier's shop by a link-only stockpile, and
  worn clothing goes to a take-from-anywhere stockpile (Clothing;
  docs/STOCKPILES.md, section 9.1).
* **Trade clothes stockpile.** Finished goods, near the depot,
  take from the used-clothes stockpile only, bins allowed. Worn
  clothing sold from here, while it is still worth good money.

### 10.2 What rots and what does not

Cloth, thread, leather, and dye do not rot. Raw hides rot, and
rotten hides cannot be tanned, so hides go to the tanner promptly
or to a refuse stockpile that the tanner can reach before they
rot. Finished clothing does not rot, but it wears in storage: one
level per 100 years (UNVERIFIED for this version, section 5.2).
Worn clothing left on the ground where a dwarf dropped it is
owned, cannot be hauled, and blocks tiles until it reverts or is
forbidden (Bug 6048, Bug 4403).

### 10.3 Correction to docs/STOCKPILES.md

Section 10 of the stockpile plan says "Cloth | Bins max". That is
wrong for the clothier's feed stockpile: the clothier ignores
cloth in bins (Clothier's shop), so a bins-max cloth stockpile
feeding a clothier starves it. The bulk cloth stockpile keeps
bins max; the clothier feed stockpile is bins 0. The stockpile
plan's conclusion (bins consolidate cloth) still stands for bulk
storage, but the row must be split into feed and bulk when the
clothing work lands. The coordinator owns that fix, the same way
the kitchen plan owns its correction to docs/TRADING.md.

## 11. Labor

The textile labors, from the live enum (section 6.1): WEAVER
(weaving skill), CLOTHESMAKER (clothesmaking), TANNER (tanning),
DYER (dyer), SHEARER (shearing), SPINNER (spinning), MILLER
(milling, for dye), PROCESS_PLANT (plant processing, for thread),
LEATHER (leatherworking). The labor plan (docs/LABOR.md) owns the
assignment machinery; this section sets the clothing floors it
must cover.

Proposed floors for a 7-citizen fort, to be tuned live in phase 8,
not taken as wiki fact:

| Labor | Floor | Why |
| --- | --- | --- |
| WEAVER | 1, rises to 1 when thread exists | No thread, no weaver; thread without a weaver is a stuck chain |
| CLOTHESMAKER | 1, rises to 1 when cloth exists | No cloth, no clothier; cloth without a clothier is a stuck chain |
| TANNER | 1 when a hide exists | Hides rot; the tanner must run promptly after butchering |
| PROCESS_PLANT | 1 when fiber plants are harvested | Shared with the kitchen's plant processing; the split rule decides |
| SHEARER | 0, rises to 1 when a shearable animal is ready | Shearing is once per 300 days per animal; a standing shearer is waste |
| SPINNER | 0, rises to 1 when wool exists | Wool without a spinner is a stuck chain |
| DYER | 0, rises to 1 when dye plants are milled | Dye is a value play, never a need |
| MILLER | 1 when dye plants are harvested | Shared with flour milling; the split rule decides |
| LEATHER | 0, rises to 1 when leather exists | No leather, no leatherworker |

Floors scale with population: each production labor gains a second
dwarf when its waiting job list stays non-empty across two ticks.
A floor is a minimum, not a target; the harness never assigns a
dwarf to a labor with no waiting work just to fill a number.

Skill matters twice: it sets the quality of the cloth and the
clothes (and therefore their value and the happy thought from a
preferred garment), and it sets the speed. A matching material
preference is worth about four skill levels on average (Skill),
so a dabbling weaver who loves pig tail can outrank an adequate
weaver who does not care, for pig tail work specifically. The
labor plan's matching rule already handles that; this plan only
adds the floors.

## 12. Trade

Clothing is a trade good twice over: new garments from surplus
cloth, and worn garments that still hold value.

* **Which garments:** dresses and robes first (highest base
  value), then cloaks and coats, then shirts and trousers. Dyed
  cloth garments before undyed, where the dyer has run. Never a
  garment the fort needs for coverage, never a garment below the
  cloth reserve (section 7.1).
* **When:** made in the season before the caravan they serve, not
  stockpiled for a year. Elves come in spring, humans in summer,
  dwarves in autumn, none in winter (docs/TRADING.md). The
  clothing system queues trade garments in the season before the
  caravan, filtered through the elf rules (no animal-derived
  ingredients for elves; leather garments are animal-derived, so
  elves get cloth only).
* **Worn clothing:** worn garments still fetch a fair price, 1/2
  to 3/4 of their original value (Textile industry; Wear gives
  75 percent at x, 50 percent at X, 25 percent at XX). Sell them
  early, while they are still worth good money, from the trade
  clothes stockpile near the depot (section 10.1). A worn garment
  sold is a garment that never becomes bedroom clutter. Masterful
  items destroyed by atom smasher or magma may generate unhappy
  thoughts for their creator, so trade masterful worn garments
  instead of destroying them (Clothing).
* **Value check:** the candidate-garment computation gives the
  value before making, from the cloth item value formula
  (section 3.5), so the agent can compare "make 4 robes, about
  400 value" against "sell the raw cloth". The harness never
  makes a trade garment whose cloth is worth more raw than made,
  and never makes one from the hospital reserve.

## 13. Healthcare reserve

Cloth and thread are healthcare inputs, not just clothing inputs:
cloth for bandages, thread for suturing (Textile industry). The
hospital needs them on hand when a dwarf is wounded, not after a
season of weaving. The reserve rule:

* **Thread reserve:** 10 thread held back from weaving at all
  times, for sutures. Hair thread counts toward this reserve
  first, since it cannot become cloth anyway.
* **Cloth reserve:** 5 cloth held back from the clothier at all
  times, for bandages.
* **The reserve is a floor, not a suggestion.** The clothing
  system refuses to weave the last 10 thread or cut the last 5
  cloth, and says why when asked. The refusal names the reserve
  it is protecting, the same way the kitchen refuses to cook
  below the seed reserve.

The reserve sizes are starting values, to be tuned live from
hospital use in phase 6, not wiki fact. A fort with no wounded
dwarves and no hospital keeps the reserve anyway: wounds arrive
without warning, and weaving takes a season.

## 14. How the information reaches the AI

This is the part Mikey asked for explicitly: the information must
be fed to the AI optimally. The rules are the same as the
snapshot's rules everywhere else in the harness: counts and
exceptions, never a dump; named options with a one-line why; full
detail behind a query route.

### 14.1 The snapshot's Clothing section

The per-tick snapshot gains a short Clothing section, built from
the fresh collect, in plain words. The canonical shape, on the
live fort today (7 citizens, 270 silk thread, no loom, no
clothier, coverage unknown until phase 1 reads it):

```
Clothing: cloth 0, thread 270 (silk 270), leather 0, dye 0.
  Cover: 7 citizens, 5 covered, 2 barefoot, 1 tattered (X).
  Need: 2 shoes, 1 shirt. Chain: 270 thread un-woven, 0 cloth.
  Shops: loom 0, clothier 0, tanner 0, dyer 0.
```

What is in it, and what is not:

* **In it:** cloth, thread (by material, top 2), leather, and dye
  counts; coverage counts with at most 3 named exceptions; the
  garment need by slot; the chain bottleneck in one line; which
  clothing workshops exist.
* **Not in it:** the full per-dwarf wardrobe, the per-item wear
  table, the per-material breakdown beyond the top 2, the dye
  color table, or the value arithmetic. Those live behind
  GET /v1/clothing.
* **Never in it:** a raw dump of the stocks section, a list of
  every garment, or a number without its unit and its floor. A
  number without its floor is a number the agent cannot act on.
* **When nothing is wrong:** the section diffs to a one-liner,
  "Clothing: unchanged (7 citizens covered).", and costs almost
  nothing (section 15).

### 14.2 The query route

GET /v1/clothing returns the full detail: per-material thread,
cloth, leather, and dye counts with units; the per-dwarf coverage
table (name, upper, lower, footwear, tattered items with wear
levels); garments on hand by slot and wear level; the chain
status with the bottleneck named; the workshop list with job
counts; the labor coverage for the textile labors; the cloth and
thread reserves with what they protect. It reads from the fresh
collect, not from a cache. The snapshot carries the summary; the
route carries the detail. The agent asks the route when it needs
to choose, never as a matter of routine.

### 14.3 Named options

The planner's clothing decisions carry the option in the decision
itself:

* "Build a loom at (x, y, z): 270 silk thread un-woven, 0 cloth,
  2 dwarves barefoot."
* "Weave 5 silk cloth at the loom (270 thread on hand, 0 cloth,
  hospital reserve 10 thread held back)."
* "Make 2 shoes at the clothier (4 cloth on hand, 2 dwarves
  barefoot, oldest need first)."
* "Cannot make shoes: 0 cloth, 0 thread. Gather webs or shear
  the sheep."

The suggestion names the exact tool and parameters, as everywhere
else in the harness. When nothing can be made and no workshop
exists, the clothing section says so and names the fix (build,
gather, shear, trade), instead of going silent.

### 14.4 Attention and briefing

Two new attention kinds, both P2 unless a dwarf is naked (P1):

* **Naked dwarf:** a citizen missing all three coverings. P1.
  Briefing kind `clothing`: what this is (a dwarf with no
  clothes), what usually matters (the unhappy thoughts stack
  toward a tantrum), options (make the missing garments, or
  trade for them), cost of ignoring (stacking unhappy thoughts).
* **Tattered or barefoot:** a citizen at X or XX wear, or missing
  footwear. P2. Same briefing kind, with the wear level named.

The briefing is a few hundred tokens at most (briefings.py rule),
and it fires only on the event tick, never per tick. The caravan
briefing already names cloth as a need; the clothing briefing
does not repeat it.

### 14.5 Opportunities

The opportunities section (docs/HARNESS_ROLE.md, section 7(e))
carries at most 3 clothing entries, each one sentence of fact
plus the query route, never a suggestion, never an action named,
no penalty for ignoring:

* "The fort holds 270 silk thread and 0 cloth (query
  /v1/clothing)."
* "12 worn garments sit in the used-clothes stockpile and a
  caravan is at the depot (query /v1/clothing)."
* "3 dwarves are barefoot; the fort holds 4 cloth (query
  /v1/clothing)."

If there are more than 3 opportunities, the harness picks the 3
with the most concrete facts and drops the rest, and the full
list is behind GET /v1/clothing.

## 15. Model presentation

This section is required by the 2026-11-27 presentation
constraint, and it states exactly what the model is shown, what
it costs, and what is deliberately withheld. The snapshot stays
an index; the budgets hold.

### 15.1 Snapshot lines and token cost

The Clothing section is 4 lines when fully rendered, 1 line when
diffed unchanged. The exact example lines from section 14.1,
measured by the accountant's rule (3 chars per token,
conservative) and the wire rule (4 chars per token):

* **7 dwarves, full render:** 4 lines, 229 chars, 76
  accountant tokens, 57 wire tokens. The lines are the
  stocks line (cloth, thread by material, leather, dye), the
  cover line (counts plus at most 3 named exceptions), the need
  line (garments by slot plus the chain bottleneck), and the
  shops line (which clothing workshops exist).
* **7 dwarves, unchanged:** 1 line, "Clothing: unchanged (7
  citizens covered).", 41 chars, 14 accountant tokens, 10 wire
  tokens. This is the steady state: the section costs almost
  nothing on most ticks, because the diffing rule renders an
  unchanged section as a one-liner (assembler.py).
* **50 dwarves, full render:** 4 lines, 266 chars, 89 accountant
  tokens, 66 wire tokens. The lines do not
  grow with population: the cover line still names at most 3
  exceptions and gives counts for the rest, and the need line
  still names garments by slot, not by dwarf. The only growth is
  longer counts ("50 citizens", "44 covered") and a second
  material in the thread breakdown.
* **50 dwarves, unchanged:** 1 line, "Clothing: unchanged (50
  citizens covered).", 42 chars, 14 accountant tokens, 10 wire
  tokens.

Against the measured baseline (M1 run 2026-11-27, 7 citizens:
snapshot 10,693 chars, about 3,564 accountant tokens, about
2,673 wire tokens), the Clothing section adds about 2.1 percent
at 7 dwarves when fully rendered, and about 0.4 percent when
diffed. At 50 dwarves the Units section is the one that grows
(about 1,007 chars at 7 citizens, roughly 7,000 before diffing),
and the Clothing section stays flat by design. The snapshot
budget is target 30K tokens, warning 60K, never over 140K
(assembler.py); the Clothing section is about 0.25 percent of the
target at full render, and it is cuttable: its cut priority is
below attention, threats, and failure feedback, which are never
dropped, and its cut form is the one-liner.

### 15.2 Query route and cost

GET /v1/clothing, on demand only, never per tick. At 7 dwarves
the full detail is about 1,200 chars, about 400 accountant
tokens: per-material counts, a 7-row coverage table, garments by
slot, chain status, workshops, labor coverage, reserves. At 50
dwarves it is about 3,500 chars, about 1,170 accountant tokens,
because the coverage table is one row per citizen (about 60
chars each). The route is the only place the per-dwarf table
exists in model-facing text. The agent asks it when the snapshot
names a gap it wants to understand, and the retrieval cap (4K
tokens per decision, assembler.py) covers it at either
population.

### 15.3 Briefing trigger and cost

The `clothing` briefing (section 14.4) fires only when an
attention item of kind naked, tattered, or barefoot is raised,
and it rides on that attention item for one tick. Its text is 5
short fields (what, matters, options, cost, wiki), about 550
chars, about 185 accountant tokens. It never fires per tick, and
it never fires when coverage is green. A fort with no clothing
problem pays nothing for the briefing.

### 15.4 Opportunities entries

At most 3, one sentence of fact plus the query route each
(section 14.5), about 70 chars each, about 25 accountant tokens
each, 75 at most for the whole block. They are facts the agent
may act on or ignore, and ignoring one costs nothing: no score
component, no attention escalation, no diary note.

### 15.5 What this doc deliberately does NOT push to the model

* The per-item wear table. Every garment with its wear level
  lives behind GET /v1/clothing; the snapshot carries counts
  and at most 3 named exceptions.
* The per-dwarf wardrobe inventory. The snapshot never lists
  what each dwarf is wearing; the query route carries the table.
* The full by-material breakdown. The snapshot names the top 2
  thread materials; the rest is behind the route.
* The dye color table and the dye values. The snapshot carries a
  dye count; the colors and values are query detail.
* The cloth item value formula. The snapshot carries a computed
  stack value ("4 robes, about 400 value"); the arithmetic is
  never shown.
* The per-animal leather yield table. The snapshot carries a
  leather count; the yields are query detail.
* The workshop build catalog for clothing. The snapshot names
  which workshops exist and the one missing workshop the chain
  needs; the build options live in the catalog.
* The farming detail for fiber and dye crops. Seasons, plot
  sizes, and the split rule live in docs/FARMING_PLAN.md; the
  snapshot carries the fiber count and the claim, not the plan.
* The shearing and butchering detail. That lives in
  docs/ANIMAL_HUSBANDRY.md; the snapshot carries wool and hide
  counts, not the animal table.

## 16. Implementation phases

Each phase ends with a concrete live-verification bar. Nothing
counts as done until it passes its bar against the real game.
This doc is design-complete when written; it is proven only when
its UNVERIFIED marks are cleared live.

1. **Observation.** Extend the stocks collect so the snapshot can
   see what clothing needs: leather (SKIN_TANNED) and dye
   (POWDER_MISC) headline counts and material breakdowns;
   clothing counts by slot (ARMOR, PANTS, SHOES, GLOVES, HELM
   with armor level 0) and by wear level; a per-dwarf coverage
   read from the inventory walk (section 8.1). Add the Clothing
   section to the snapshot and GET /v1/clothing. Bar: a live
   collect on the main fort shows the silk thread the fort
   actually has (163 cave spider silk, 107 giant cave spider
   silk, per the 2026-11-27 log) and the snapshot names it; the
   coverage read matches a hand check of three named dwarves.
2. **Job-type probe.** On the scratch fort, queue one garment of
   each kind at a clothier (shirt, dress, robe, trousers, shoes,
   gloves, hood, cap) and read each job struct back: job type,
   item type, item subtype. Probe the TAN_A_HIDE reaction index
   the same way the brew reaction was probed (index 44). Probe
   WeaveCloth, ProcessPlants, ShearCreature, SpinThread,
   DyeThread, and DyeCloth the same way. Bar: the probe names the
   field (or the absence of one) for every garment with a live
   job id, and the doc records the answer. If a garment cannot
   be chosen by subtype, the plan adapts and never claims
   otherwise.
3. **Workshops.** Extend WORKSHOP_CATALOG with loom, clothier's
   shop, leather works, tanner's shop, dyer's shop, farmer's
   workshop, quern, and millstone, from the live workshop enum
   (25 types, verified). Bar: each workshop builds live on the
   scratch fort and reads back in the Buildings section with its
   correct subtype.
4. **Chain jobs.** Add JOB_SPECS entries for process plants,
   weave cloth, shear creature, spin thread, tan hide
   (CustomReaction plus TAN_A_HIDE), dye thread, dye cloth, and
   make garments, each with a fail-fast floor (fiber on hand,
   thread on hand, cloth on hand, hide on hand). Bar: each job
   completes live and its product reads back in stocks; a job
   queued without its input is refused with the missing input
   named.
5. **Coverage, attention, and briefing.** Wire the coverage
   computation into the snapshot Clothing section, add the naked
   and tattered attention kinds, and add the `clothing`
   briefing. Bar: on the live fort, a barefoot dwarf is named
   with the garment that fixes it, and a dwarf at X wear is
   named with the wear level; the briefing fires once on the
   event tick and never again while the problem stands.
6. **Production targets and planner.** Implement the floor
   (section 7.1), the per-season arithmetic (section 7.2), the
   pig tail claim (section 7.3), the leather claim order
   (section 7.4), and the hospital reserve (section 13). Bar: a
   live M1 day keeps coverage green, ends with cloth above the
   reserve, and never brews pig tail the clothing claim needed.
7. **Stockpiles.** Build the feed and bulk stockpiles in section
   10.1, prove the clothier-ignores-bins quirk live, and fix
   docs/STOCKPILES.md section 10 (split the cloth row into feed
   bins 0 and bulk bins max). Bar: cloth placed in a bins-0
   stockpile is picked up by the clothier and made into a
   garment; the same cloth in a bins-allowed stockpile is not
   picked up, or the quirk is disproved live and the doc records
   that instead.
8. **Labor and training.** Add the floors in section 11 to the
   labor system, wire `labor_toggle` to assign them, and pair an
   apprentice with the clothier. Bar: the assigned clothier is
   the highest-skill dwarf with the clothesmaking labor, verified
   by read-back, and is observed making a garment within the
   same run.
9. **Trade.** Queue dresses and robes from surplus in the season
   before a caravan, filtered through the elf rules and the
   never-spend lists, with the value check against selling raw;
   sell worn garments from the trade stockpile. Bar: a live trade
   batch is made, its value is computed before making, and worn
   garments are sold at the next caravan from the trade
   stockpile.
10. **Standing orders.** Probe whether the loom automation
    (auto-weave, collect webs) and the tannery automation are
    readable and writable from Lua. If they are, the harness owns
    them: auto-weave on, collect webs off while the caverns are
    unsafe, auto-tan on. Bar: the standing-order state reads back
    after a write, and no weaver is sent into unsafe caverns for
    webs. If no write route exists after a real investigation,
    the doc records exactly what was tried and what blocked it.

Every phase carries offline tests (including malformed-input
tests per the standing rule) and goes through the pre-push
self-review gate before it is committed and pushed.

## 17. Refusals

The clothing system refuses, and says why, in plain words:

* Never make a trade garment from cloth below the reserve, and
  never spend the hospital reserve on clothes or trade.
* Never brew pig tail the clothing claim needs, and never cook a
  fiber crop below its seed reserve.
* Never make a leather garment while a dwarf is uncovered and the
  leather could cover them, and never spend a hide on parchment
  while the fort is short of leather.
* Never store armor in a refuse stockpile. Armor wears there and
  nowhere else over time.
* Never claim a garment kind the harness cannot choose. If the
  phase 2 probe finds no subtype choice, the harness says the
  game picks the garment.
* Never forbid a garment a dwarf is currently wearing to reclaim
  it. Forbid only discarded, unowned garments.
* Never sell, melt, dump, or forbid an artifact garment.
  Artifacts never wear and must never be sold.
* Never destroy a masterful worn garment in magma or an atom
  smasher. Trade it instead; destroying it may upset its maker.
* Never send a weaver into the caverns for webs while the caverns
  are unsafe. Collect webs stays off until the military plan
  clears them.
* Never count hair thread toward the clothing supply. Hair thread
  cannot become cloth.
* Never queue a garment job without the cloth or leather on hand
  at job start. The fail-fast floor is 1 whole unit per job.
* Never offer a leather garment to elves. Elves are offended by
  animal-derived goods.

## 18. Open questions (UNVERIFIED)

1. **Garment job shape.** How MakeArmor, MakePants, MakeGloves,
   MakeHelm, and MakeShoes pick which garment they make, and
   whether the harness can choose by item subtype. The live enum
   has no MakeShirt or MakeDress. Phase 2 probes it.
2. **Size specification.** Whether the harness can specify a
   creature size on a queued clothing job, for non-dwarven
   residents. Phase 2 probes it.
3. **Standing orders write route.** Whether loom automation,
   collect webs, and auto-tan are readable and writable from Lua,
   and where the fields live. Phase 10 probes it.
4. **Clothier ignores bins.** Whether the clothier really ignores
   cloth in bins in 0.47.05, or whether that quirk is v50-only.
   Phase 7 proves it live.
5. **TAN_A_HIDE reaction index.** The live index of the tan
   reaction, the same way the brew reaction was probed as index
   44. Phase 2 probes it.
6. **Leather clothing versus leather armor.** Exactly which
   leather works menu items are civilian clothing and which are
   armor in 0.47.05. Phase 2 enumerates the menu live.
7. **Worn wear rate in 0.47.05.** The v50 wiki says one level per
   ten years while worn, changed from one per two years in
   previous versions. The 0.47.05 rate is most likely two years,
   but that is an inference, not a fact. Phase 1 measures it from
   the fort's own worn items over time.
8. **cleanowned.** Whether the harness may call DFHack's
   cleanowned command to clear owned tattered clothing, and
   whether that counts as a game action the harness may take.
   Phase 1 investigates; it is not used until the probe answers.
9. **Coverage read cost.** Whether the per-dwarf inventory walk
   is cheap enough at 50 dwarves, and whether the wear field
   reads the same way for worn items as for stored ones. Phase 1
   measures it live.
10. **Clothing need.** Whether a clothing-related need type exists
    in `df.need_type` for 0.47.05, and whether it shows in the
    needs read. Phase 1 checks the live enum; the coverage read
    does not wait for it.
11. **Self-replacement.** Whether dwarves actually replace their
    own worn clothing when replacements are available, as the
    wiki's forum citation claims. Phase 5 watches it live.
12. **Dye milling seed return.** Whether milling a dye plant at a
    quern returns its seed in 0.47.05, as the Dye page says, and
    whether dyer-shop dye production returns none. Phase 4
    verifies it with a counted batch.
13. **Dwarf producible set.** Whether the clothier's menu in
    0.47.05 matches the wiki's list exactly (cap, cloak, coat,
    glove, hood, loincloth, mitten, robe, shirt, shoe, sock,
    trousers, tunic, vest), or whether the dwarven set differs.
    Phase 2 enumerates the menu live.
14. **Leather yield table.** Whether the per-animal leather yields
    on the Leather page (cow 2, giant elephant 10, and the rest)
    hold in 0.47.05. The tanner page's cow figure carries a
    v50.01 marker, so it is suspect. Phase 4 verifies with a
    counted batch.

## 19. Sources

Wiki pages read from the local index
(`~/workspace/df-wiki-export/dfq.py`, hybrid search default):

* Clothing, Textile industry, Wear, Leather, Dye, Loom,
  Clothier's shop, Leather works, Tanner's shop, Dyer's shop,
  Farmer's workshop, Sheep.
* Value (cloth item value formula, via Textile industry),
  Stockpile (new versus used clothes stockpiles), Skill (matching
  preference worth four skill levels), Manager (work orders).

0.47.05 raws, read from the repo install:

* `third_party/df_47_05/raw/objects/building_custom.txt` (the only
  workshop definition file; defines SOAP_MAKER and SCREW_PRESS
  only, proving the rest of the chain is hardcoded).
* `third_party/df_47_05/raw/objects/item_armor.txt` (ARMORLEVEL
  tokens: breastplate 3, mail shirt 2, leather armor 1; nine soft
  upper-body items with none).
* `third_party/df_47_05/raw/objects/item_shoes.txt`,
  `item_gloves.txt`, `item_helm.txt`, `item_pants.txt` (shoe,
  boot, sandal, sock; glove, mitten, gauntlet; cap, hood, helm;
  trousers, skirt, loincloth, leggings, greaves).
* `third_party/df_47_05/raw/objects/reaction_other.txt`
  (TAN_A_HIDE, MAKE_PARCHMENT, BREW_DRINK_FROM_PLANT).

Harness state verified against the repo:

* actions.py WORKSHOP_CATALOG (carpenter, mason, still, kitchen
  only) and JOB_SPECS (brew, brew_fruit, cook, 8 carpenter
  furniture jobs only).
* daemon.py TASK_DEFS (6 tasks, none clothing).
* lua/stocks.lua (cloth_units, thread_units; by_material covers
  CLOTH and THREAD; SKIN_TANNED, POWDER_MISC, ARMOR, PANTS,
  SHOES, GLOVES, HELM absent from the breakdown).
* assembler.py _stocks (renders drink, food, wood, stone,
  brewable plants, empty barrels, food stacks; no cloth, no
  thread), TokenAccountant (3 chars per token conservative, 4
  chars per token wire), budgets (target 30K, warning 60K, never
  140K), diffing (unchanged section renders as a one-liner).
* observe.py Stocks line (cloth and thread present there, but the
  assembler is the per-tick snapshot).
* lua/units.lua (needs, skills, labors, wounds; no inventory, no
  worn clothing), lua/probe_picks.lua and lua/equip_pick.lua (the
  only inventory walks in the repo, pick-specific).
* lua/buildings.lua (workshop subtype from df.workshop_type).
* planner.py (no clothing thresholds or decisions),
  attention.py (no clothing kinds), briefings.py (no clothing
  briefing; caravan briefing names cloth as a need),
  catalog.py (entries built by introspection from the action
  table).
* tests/fixtures/runtime-enums-0.47.05-r8.json (241 job types;
  25 workshop types; 84 unit labors including WEAVER,
  CLOTHESMAKER, TANNER, DYER, SHEARER, SPINNER, MILLER,
  PROCESS_PLANT, MILK, MAKE_CHEESE, LEATHER; 138 job skills).
* logs/m1-20261127-073557.jsonl (real M1 snapshot, 7 citizens:
  10,693 chars, about 3,564 accountant tokens; by-material list
  shows 163 cave spider silk thread and 107 giant cave spider
  silk thread; Buildings line shows no clothing workshop).
* docs/FARMING_PLAN.md (pig tail summer and autumn, dimple cup
  all seasons, split rule section 10.1, seed reserve),
  docs/ANIMAL_HUSBANDRY.md (shearing section 6.2, butchering
  hides), docs/STOCKPILES.md (section 9.1 wear and new versus
  used clothes, section 10 cloth bins max, corrected in section
  10.3 above), docs/TRADING.md (caravan seasons, elf rules),
  docs/LABOR.md (labor floors, no textile floors), docs/MILITARY.md
  (Bug 6039 uniform wear), docs/KITCHEN.md (drink floor, split
  rule, correction pattern for cross-doc errors),
  docs/HARNESS_ROLE.md (section 7(e) opportunities rules, snapshot
  as index).
