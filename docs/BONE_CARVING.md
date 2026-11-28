# Bone Carving

Design record for the bone-carving industry in the Urist harness: the
craftsdwarf's workshop as a bone shop, bone/shell/ivory/horn/tooth/pearl
crafts, totems, bone bolts, bone and shell armor, decorations, bone
crossbows at the bowyer's workshop, and the refuse bone supply the
carver draws on. This is the plan. Implementation follows it phase by
phase, each phase verified live against the real game before it counts
as done. Anything not verified against the wiki, the 0.47.05 raws, the
code, or the live game is marked UNVERIFIED.

Related docs: docs/HUNTING.md (hunting yields bones and skulls, the
hunt-butcher-carve bolt loop), docs/ANIMAL_HUSBANDRY.md (slaughter and
tame-animal byproducts), docs/FISHING.md (shell supply, the shell mood
reserve, cooking shelled creatures loses the shell),
docs/STOCKPILES.md (the usable-refuse stockpile, sorting bones from
rotting refuse), docs/STONEWORKING.md (the craftsdwarf's workshop as a
stone shop, the hardcoded-job gap this doc shares), docs/WOODWORKING.md
(wooden bolts at 25 per log, the craftsdwarf's workshop as a wood shop),
docs/MILITARY.md (marksdwarves, bolt stockpiles, bone armor as a
stopgap), docs/TRADING.md (elf refusal of all animal products, trade
values), docs/CLOTHING.md (leather armor at the leather works, the
armor the bone shop does not make). This doc builds on them and does
not duplicate them. Where this doc changes a behavior another doc
describes, it says so explicitly.

Boundary, stated once: the slaughter and butchery supply side belongs
to the animal and hunting work. This doc owns the carver's workshop
and its products, and the read of the bone stock it draws on. It does
not own how an animal dies, how a corpse reaches the butcher's shop,
or how a fishery shells a turtle. It owns what happens to the bone,
skull, shell, horn, tooth, ivory, and pearl once they exist.

## 1. Purpose

Bone carving answers six questions every tick, from fresh collects, so
the agent never has to:

1. How many bones, skulls, shells, horns, teeth, and ivory pieces do
   we have, and are they rotting where they lie?
2. Can the fort make bone bolts right now, and how many would one bone
   buy?
3. Is there a craftsdwarf's workshop, a butcher's shop, and a bowyer,
   and which of them is missing?
4. What bone goods should we make for trade, and who will refuse them?
5. Does a moody dwarf need bone or shell, and is the reserve held back?
6. Is bone armor worth making for anyone, and for whom is it not?

The headline finding of the research behind this doc is that the
industry is free and the harness cannot run any of it. Bones, skulls,
and shells arrive as byproducts of food the fort already produces, so
the material costs nothing but a carver's time. But the harness has no
craftsdwarf's workshop in its build catalog, no bone job in its job
list, and no bone count in its snapshot. Worse, the one route the
harness has for queueing jobs cannot express what a bone job needs:
a bare hardcoded job carries no material, so nothing today can tell
the game "make this craft from bone, not stone". That material
selection problem is the crux of the whole industry, and phase 2
exists to settle it before a single bolt is queued.

## 2. How bone carving works in DF 0.47.05

All of this section is from the wiki pages listed in Sources, checked
against the 0.47.05 raws shipped with the game where the wiki and the
version can disagree. The local wiki index is a current-wiki export:
some pages carry v50 markers (the Refuse page shows a v50 preview
image), so a wiki claim is not a 0.47.05 claim until the raws or a
live probe agrees with it. Section 3 is the authoritative list for
this version. Where the wiki list and the raws disagree, the raws win
and the difference is named.

### 2.1 The bone carver

Bone carver is a skill under the Craftsdwarf profession. The labor is
Bone carving (BONE_CARVE in the live runtime enum). The wiki names
agility, creativity, spatial sense, and kinesthetic sense as the
attributes (Bone carver). The task list on the skill page is the whole
industry in one line: decorate with bone, decorate with shell, make
bone crafts, make shell crafts, make bone bolts, make bone armor, make
totem (Bone carver). The workshop is the craftsdwarf's workshop.

Bone carvers make bone, shell, ivory/tooth, horn, and pearl goods at
a craftsdwarf's workshop. These include bone bolts for crossbows,
lightweight bone and shell armor, and totems from skulls. Bone carvers
can also decorate furniture and goods with these materials (Bone
carver).

### 2.2 The craftsdwarf's workshop

The craftsdwarf's workshop is the cornerstone of trade in Dwarf
Fortress. All crafts can be traded for food, alcohol, weapons, and
other goods (Craftsdwarf's workshop). It is built from any
construction material that is not economic stone, by a dwarf with the
Bone Carving, Stonecrafting, or Woodcrafting labor enabled
(Craftsdwarf's workshop). Its shortcut is b-o-r. One workshop serves
three skills: a stonecrafter, a woodcrafter, and a bone carver all
work at the same building, which is why the harness must never treat
"a craftsdwarf's workshop exists" as "bone carving is possible". The
workshop existing is not the same as a bone carver being assigned to
it.

Materials the workshop uses: stone, wood, bone, shell, ivory, tooth,
horn, pearl, cloth, thread, wax, leather, skull
(Craftsdwarf's workshop). Goods created include rock crafts, mugs,
instruments, toys, jugs, large pots, hives, nest boxes, wood, plant
fiber cloth, silk, shell, ivory, tooth, horn, pearl, bone, and leather
crafts, rock short swords, wooden and bone bolts, bone, shell, ivory,
tooth, horn, and pearl decorations, totems, bone leggings, greaves,
gauntlets, and helms, shell leggings, gauntlets, and helms, adamantine
strands, scrolls, quires, books, wood and stone scroll rollers and
book binding, instruments and instrument pieces
(Craftsdwarf's workshop).

The workshop size is UNVERIFIED: the wiki page does not state it in
the text read, and the harness has never built one. Phase 1 probes it
live. Do not assume 3 by 3 until the probe says so.

### 2.3 Where bones, skulls, and shells come from

Bones come from butchery. Any time an animal with a skeleton is
butchered at a butcher's shop, bones are produced along with several
other products. This applies to full corpses, severed body parts, and
even fully decomposed skeletons. If a severed body part is allowed to
fully rot, it may leave behind a stack of usable bones without ever
needing to be butchered (Bone). Bones are never imported in caravans,
and must be acquired locally (Bone). That last fact matters for
planning: there is no trade route to bone. A fort with no hunting, no
slaughter, and no fishing has no bone industry, and no caravan fixes
it.

A butchered animal yields meat and prepared organs, fat, a skull,
bones, hooves, horns, teeth, shells (from shell-bearing animals),
skin, wool, hair, cartilage, nervous tissue, feathers, scales, chitin,
and nails (Butcher's shop). Of those, the carver uses bones, skulls,
hooves, horns, teeth, and shells. Cartilage, nervous tissue,
feathers, scales, chitin, and nails currently have no uses
(Butcher's shop). The butcher's shop takes tame animals designated
for slaughter and corpses of untamed non-sentient animals. Slaughter
is instantaneous once the animal has been led to the shop. Pets cannot
be slaughtered. Butchering a corpse is not instantaneous. A corpse
must be in a stockpile or lying on the ground within 20 tiles of the
edge of the butcher's shop on the same z-level, a 43 by 43 by 1 box
centered on the workshop (Butcher's shop). The supply mechanics,
slaughter designations, and the butcher's shop build belong to the
animal and hunting work; this doc records only what the carver needs
to know: bones arrive in stacks, one stack per body part set, and a
stack's size does not change what one bone from it can make.

Virtually all animals produce a single skull when they die; the only
exception is the hydra, which produces seven (Meat industry). A skull
is one totem. Skulls of more valuable animals make more valuable
totems (Finished goods).

Shells come mostly from fishing. Dwarves catch shelled vermin such as
turtles, oysters, and mussels, which produce a shell when processed
at a fishery or if left to rot long enough after being caught, and
from butchering a few land animals such as armadillos, desert
tortoises, and giant forms of many shell-bearing vermin (Shell).
Shells cannot easily be acquired by trading: non-caged turtles,
crustaceans, or shellfish purchased from traders have already been
processed, and their shells removed (Shell). A fort with no
naturally occurring above-ground fishing site can struggle to acquire
shells at all. Fishing eventually causes the extinction of
shell-bearing fish, over years or decades depending on how
aggressively the fort fishes (Shell). The shell supply is therefore
finite on a long enough timeline, and shells held for strange moods
are worth more than shells spent on crafts. That is the mood reserve
in section 8, and FISHING.md already holds it back.

Ivory and teeth are the rare end of the family. Ivory tusks come from
butchering elephants, hippos, narwhals, walruses, warthogs, and wild
boars. Usable teeth come from butchering many of the largest animals,
roughly grizzly bear size or larger. Knocked-out teeth are almost
always too small for crafting (Ivory). A fort on a temperate map with
ordinary game will see little ivory and few usable teeth. The harness
must not plan around ivory it does not have.

Horn comes from butchering horned animals. The wiki gives no
creature list as precise as ivory's, and the horn supply on any given
map is whatever the local game provides. The harness counts horn
pieces in stock and plans from the count, never from a list.

Pearl is the rarest of the family. The wiki's finished-goods table
lists pearl as a bone-carver craft material, but the pages read give
no reliable fortress-mode pearl source on a normal map. Pearl is
carried in the material table in section 2.6 for completeness, and
the harness treats a pearl count of zero as normal, not as a
shortage. Whether any pearl source exists on the fort's map is
UNVERIFIED (section 13, open question 9).

### 2.4 Bone bolts

Bone bolts are the industry's most useful product. When making wood
bolts, a single log produces a stack of 25 bolts. When making bone
bolts, an entire stack of bones is brought to the workshop, and then
one bone from that stack becomes a stack of 5 bolts
(Craftsdwarf's workshop). The Bone page states the same rule as a
work order: each work order consumes one unit of bone to produce a
stack of five bolts, as opposed to stacks of 25 from metal or wood.
Bone bolts are better than their wooden counterparts, and while not
as effective as metal bolts, are still able to pierce metal armors
(Bone).

The arithmetic that follows: one bone is 5 bolts, one log is 25
bolts, one metal bar is 25 bolts (MILITARY.md states 25 per bar or
log, 5 per bone, though it names the wrong workshop for them; see
section 12, conflict 1). A hunted animal yields several bone stacks,
so one kill is several bolt stacks. HUNTING.md states the loop
plainly: hunt, butcher, carve bone bolts, hunt again, bones in per
kill, bolts back per bone stack (HUNTING.md, section on the bolt
loop). Bone bolts are a renewable resource for hunting animals, as
animals are a source of bone (Bone). That loop is the reason the
industry matters before the metal industry exists: it turns food
production into ammunition production with no other input.

Bolts are made at a craftsdwarf's workshop or at a forge, from wood,
bone, or metal (HUNTING.md). They are not made at the bowyer's
workshop, which makes only the crossbow itself. The live runtime enum
has no job type named for bolts. The bolt job is MakeAmmo, index 129
in the enum (tests/fixtures/runtime-enums-0.47.05-r8.json). Whether
queueing MakeAmmo at a craftsdwarf's workshop with bone in stock
produces bone bolts, and how the game picks bone over wood or stone
for that job, is UNVERIFIED (section 13, open question 1). It is the
same material-selection problem as crafts, and phase 2 probes both
together.

### 2.5 Bone and shell armor

Bone or shell armor, while vastly inferior to metal armor, is still
better than nothing (Craftsdwarf's workshop). Only four armor parts
may be made from bone: leggings, greaves, gauntlets, and helms. Only
three parts may be made from shell: leggings, gauntlets, and helms
(Craftsdwarf's workshop). There are no bone breastplates, mailshirts,
or boots (Refuse).

The material cost, from the craftsdwarf's workshop page: making bone
leggings or greaves requires 3 stacks of bones, but it only consumes
1 bone from each stack. A stack of 3 bones cannot be used instead;
there must be 3 separate stacks. Making bone gauntlets consumes 1
bone from 1 stack and produces both a right and a left gauntlet.
Making a bone helm consumes 1 bone from 1 stack
(Craftsdwarf's workshop). So a full set of bone armor costs 3 stacks
for leggings, 3 stacks for greaves, 1 bone for gauntlets, and 1 bone
for a helm, 8 bones drawn from at least 7 stacks, and still leaves
the torso and feet bare. That cost is the reason the harness never
queues bone armor as a default: 8 bones is a stack of bolts and a
craft, for armor that loses to copper.

The Bone page is blunt about quality: bone armor is significantly
inferior to even the worst metal counterpart. Even no-quality copper
is far, far better 99 percent of the time. Bone armor is only helpful
against small animal attacks, and even moderately sized animals do
not need much luck to hurt a dwarf in even the best bone armor
(Bone). The usually recommended uses are hunters, who can choose
what they face and need light armor to move quickly, early forts as a
pre-metal better-than-nothing precaution, and personal challenge or
fashion (Bone). Bone armor is adequate protection for military
training: sparring no longer causes direct injuries, so the only
danger is a fall from a rare wrestling throw (Bone). Heavier armor
trains the armor user skill, so metal is preferable even there.

Two details the harness must get right. First, the type of bone
makes no difference to protection: chicken bone and dragon bone offer
equally weak protection (Bone). A dwarf in dragon-bone greaves is
not better protected than one in chicken-bone greaves, only richer
looking. Second, dwarves treat bone armor as metal when equipping
their military uniforms (Bone), so bone pieces can be added to
uniforms by specifying the color, for example "white greaves"
(Bone). Whether the harness's uniform route can express a bone armor
piece at all is UNVERIFIED (section 13, open question 6).

Shell armor follows the same rules with one less piece: no shell
greaves. Shell armor is better than nothing and does not slow the
military like metal armor does, so early production is worth
considering when metal armor cannot be made immediately (Shell).

### 2.6 Crafts, totems, and decorations

Crafts are the trade product. If a specific subtype is ordered, one
item is produced from one resource material. If the general work order
is chosen, to "make crafts", one resource is consumed and produces
one to three random items, two on average. Skill does not affect the
chance to produce multiples (Finished goods). So one bone is 1 to 3
bone crafts, averaging 2, and the carver's skill changes their
quality and therefore their value, not their count. The craft
subtypes are amulets, bracelets, crowns, earrings, rings, figurines,
and scepters (Finished goods).

The live runtime enum carries a job type for each specific craft
subtype: MakeFigurine 229, MakeAmulet 230, MakeScepter 231, MakeCrown
232, MakeRing 233, MakeEarring 234, MakeBracelet 235, MakeGem 236,
plus the general MakeCrafts 83 and MakeToy 123 and MakeGoblet 122
(tests/fixtures/runtime-enums-0.47.05-r8.json). Whether any of these
can be queued at a craftsdwarf's workshop through the harness, and
with bone as the material, is UNVERIFIED (section 13, open question
1). The general MakeCrafts job is the phase 2 probe; the specific
subtype jobs are phase 4, after the general one works.

Totems are made from skulls by a bone carver at a craftsdwarf's
workshop. Although totems have the same base value as all other
crafts, totems made from the skulls of more valuable animals, like
unicorns, will fetch a hefty price (Finished goods). One skull is one
totem. The job type is MakeTotem, index 128 in the enum. Totems do
not fall under any category in the "move trade goods to depot"
screen, so they must be searched for by name when trading (Meat
industry). The harness must remember that when it builds a trade
offer: a totem in the trade stockpile is invisible to a category
filter, and the trade route needs a name search or an explicit item
list to move it.

Decorations add value to an item. Any decoratable item can be
decorated with bone, adding to the item's value (Bone). Shell, ivory,
tooth, horn, and pearl decorations work the same way
(Craftsdwarf's workshop). The job type is DecorateWith, index 130 in
the enum. One bone, shell, or other piece decorates one item. The
FISHING.md plan already leans on this: a fishing fort with mussels or
oysters keeps a craftsdwarf swimming in shells, and sets up craftsdwarf
workshops next to a dedicated shell stockpile with repeating "decorate
with shell" orders (FISHING.md). The harness has no repeating-order
mechanism today, so that plan is a design direction, not a working
route; see section 12, conflict 2.

Material values, verified against the 0.47.05 raws
(material_template_default.txt): bone 1, tooth 1, horn 1, pearl 1,
shell 1. Every bone-family material has base value 1. That fixes the
trade math: a bone craft's value comes from its base value as a craft
(about 20, per the Maximizing value table cited in WOODWORKING.md)
times its quality modifier, not from the material. A masterwork bone
craft is worth real money; a plain one is cheap, and the fort makes
them in volume because the material is free. A totem from an ordinary
skull is worth about the same as a bone craft; a totem from a valuable
animal's skull is worth much more, because the skull's creature value
enters the price.

Bone crafts, shell crafts, horn crafts, ivory crafts, and totems are
all animal products. Elves refuse them entirely, along with every
other animal product (TRADING.md, section 2.5). Never offer a bone
good to elves. One wrong item ends the whole trading session.

### 2.7 Bone crossbows

The bowyer's workshop makes crossbows from wood or bone. Metal
crossbows are made at a metalsmith's forge. Ammo is made elsewhere
(Bowyer's workshop). The tasks are "make bone crossbow" and "make
wooden crossbow" (Bowyer's workshop). A bone crossbow is one of the
few weapons available without access to wood or metal. It is nearly
useless in melee, but just as deadly as a metal crossbow when firing
bolts, and weighs significantly less (Bone). The job requirement is
crossbow-making, and the workshop is built from any building material
by a dwarf with that labor (Bowyer's workshop). The live runtime enum
has Bowyers as a workshop type, index 7, and no job type named for
crossbows; the likely job type is MakeWeapon, index 97, which is the
generic weapon job. Whether MakeWeapon at a bowyer's workshop with
bone in stock produces a bone crossbow is UNVERIFIED (section 13,
open question 5).

A crossbow without bolts is a club, and a crossbow without a quiver
is a crossbow its owner keeps dropping. Quivers are made at a leather
works (Bowyer's workshop; HUNTING.md). The bone crossbow route is
therefore three workshops, not one: bowyer for the crossbow,
craftsdwarf for the bolts, leather works for the quiver. The harness
must check all three exist before it promises a working marksdwarf.

### 2.8 Refuse, rot, and miasma

Bones are counted as body parts in the stocks menu, and have their
own subcategory in the refuse stockpile menu (Bone). Refuse
stockpiles also cause the degradation of stored body parts such as
bones and shells, though at a much slower pace than clothes and armor
(Bone). Bones stored in a refuse stockpile decompose even more
quickly if subjected to vermin such as rats; pasturing a cat over the
stockpile minimizes decay (Bone). Rotting refuse produces miasma when
in a subterranean tile. To avoid miasma, store rotting refuse in a
light and above-ground tile, or destroy it before it rots (Refuse).
Refuse items lying outside the fortress are ignored by default, and
collection is toggled in the standing orders menu (Refuse).

Dwarves looking at bones from non-stray creatures may in the short
term have a negative mood impact. In the medium term this can lead to
them better dealing with death. In the long term it can turn to
apathy. Best practice is to have the bone depot behind a door to make
it less obvious to non-users (Bone). The layout in section 10 follows
that: the usable-refuse stockpile sits near the butcher and the bone
carver, behind a door, not in traffic. STOCKPILES.md already places
it there (STOCKPILES.md, usable-refuse row: near butcher and bone
carver, not in traffic).

Refuse is not trash. The Refuse page lists the industrial uses
directly: a single bone can be used to make a stack of bone bolts
(5), a bone crossbow, 1 to 3 bone crafts, or a bone decoration
(Refuse). Multiple bones can be used to make bone armor, with no
breastplates, mailshirts, or boots (Refuse). The sorting rule follows:
usable refuse (bones, hides, shells, skulls, teeth, horn) is sorted
from rotting refuse with separate stockpiles, or the bone carver's
material rots with the garbage (STOCKPILES.md).

### 2.9 Strange moods and the bone reserve

Dwarves in strange moods will occasionally require bones, sometimes
even multiple stacks of them. These dwarves always take an entire
stack independent of the number of bones in it. As the number of
bones per stack has no influence on the value of the resulting
artifact, it may be worth guiding a moody dwarf to use smaller
stacks. This may be achieved by creating stacks of single bones
before a strange mood happens and forbidding all other stacks of
bones when the notice of the dwarf having claimed a workshop arrives.
There is no direct way to unstack bones, but bigger stacks can be
used to craft goods until only one bone remains (Bone).

Shells are the sharper version of the same risk. Only dwarves with a
preference for shells demand them for artifacts, but shells are hard
to come by, so players occasionally mod the game to make sure
fortresses have shells available (Shell). The FISHING.md plan holds a
shell reserve back for moods and never spends it on crafts
(FISHING.md). This doc adopts that reserve and extends it: the bone
reserve is the same shape, a count of bone stacks and shell pieces
held back from production, spent only when a mood demands them. A
mood that cannot be satisfied because the carver spent the last shell
on a craft is a preventable failure, and the harness must not cause
it. How the harness forbids a stack, or reserves one, through DFHack
on r8 is UNVERIFIED (section 13, open question 7).

Moody dwarves without a moodable skill claim a craftsdwarf's workshop
and produce a legendary stone, wood, or bone craft
(Craftsdwarf's workshop). A craftsdwarf's workshop kept free of
queued jobs is therefore also a mood workshop, and the harness must
not fill every craftsdwarf's workshop with a long queue the day a
mood could strike. The planner keeps one craftsdwarf's workshop
unqueued when the fort has more than one, and never queues a batch
longer than a season on the only one. That rule is cheap insurance
against a mood failing for want of a free workshop.

## 3. The authoritative 0.47.05 workshop and job list for the chain

Workshops in this game are mostly hardcoded: the building type and
the jobs it runs are fixed by the version, not chosen by the player.
The list below is the chain as it stands in 0.47.05, verified against
the shipped raws and the live runtime enum
(tests/fixtures/runtime-enums-0.47.05-r8.json). Do not trust a v50
workshop list for this fort.

| Building | Type in the enum | What it does in the chain | Harness build kind today |
| --- | --- | --- | --- |
| Craftsdwarf's workshop | Workshop, subtype Craftsdwarfs | Bone/shell/ivory/horn/tooth/pearl crafts, totems, bone bolts, bone and shell armor, decorations, toys, instruments | none |
| Butcher's shop | Workshop, subtype Butchers | ButcherAnimal, SlaughterAnimal; yields bones, skulls, shells, horn, teeth, ivory | none |
| Bowyer's workshop | Workshop, subtype Bowyers | Bone and wooden crossbows | none |
| Leather works | Workshop, subtype Leatherworks | Quivers, backpacks, waterskins for the marksdwarf kit | none |
| Fishery | Workshop, subtype Fishery | Shells turtles and shellfish, the shell supply | none |

Notes on the list:

* The harness can build none of these today. WORKSHOP_CATALOG has
  exactly four kinds: carpenter, mason, still, kitchen. Every row
  above is a gap, not a claim.
* The bone jobs are hardcoded job types, not reactions. The enum
  proves them: MakeCrafts 83, MakeTotem 128, DecorateWith 130,
  MakeAmmo 129, MakeArmor 101, MakeHelm 102, MakePants 103,
  MakeGloves 116, MakeWeapon 97, MakeToy 123, MakeGoblet 122,
  MakeFigurine 229, MakeAmulet 230, MakeScepter 231, MakeCrown 232,
  MakeRing 233, MakeEarring 234, MakeBracelet 235, MakeGem 236,
  ButcherAnimal 105, SlaughterAnimal 182.
* The CARVE_BONE reactions in the raws are a trap. reaction_other.txt
  holds CARVE_BONE_FIGURINE, CARVE_BONE_RING, CARVE_BONE_EARRING,
  CARVE_BONE_SCEPTER, CARVE_BONE_AMULET, CARVE_BONE_BRACELET,
  CARVE_BONE_CROWN, and CARVE_BONE_GEM, each with skill BONECARVE and
  one bone reagent. Every one carries CATEGORY:ADV_BONE_CARVING.
  They are adventure-mode reactions, done by an adventurer holding a
  sharp tool over a pile of bones. They are not fortress jobs, and
  adding any of them to JOB_SPECS as a fortress reaction would queue
  a job the fortress game cannot work. The fortress route is the
  hardcoded job types above, never these reactions.
* MakeGoblet is listed because it exists in the enum, not because
  bone can use it: the finished-goods table says bone makes no
  goblets (Finished goods). Do not offer bone goblets.
* There is no MakeInstrument job type in the enum. Instruments and
  instrument pieces from bone are listed on the workshop page, but
  no job type exists to queue them through. Whether they are made
  through MakeCrafts, MakeToy, or a route the enum does not expose
  is UNVERIFIED (section 13, open question 8).
* The workshop list in the enum is Carpenters, Farmers, Masons,
  Craftsdwarfs, Jewelers, MetalsmithsForge, MagmaForge, Bowyers,
  Mechanics, Siege, Butchers, Leatherworks, Tanners, Clothiers,
  Fishery, Still, Loom, Quern, Kennels, Kitchen, Ashery, Dyers,
  Millstone, Custom, Tool. That is the full set the harness can ever
  address by subtype; anything outside it does not exist in 0.47.05.

## 4. What the harness has today

Verified against the repo on 2026-11-27. Everything in this section
was read from the code, not remembered. The daemon and game were down
at the time of writing (VM replacement 2026-11-27 about 19:37 PT,
recovery running separately), so no live value in this section was
re-read against the running game; the code facts below do not need a
live game, and every live value is flagged UNVERIFIED where it
appears.

### 4.1 No bone workshop can be built

WORKSHOP_CATALOG (actions.py) has exactly four kinds: carpenter,
mason, still, kitchen. There is no craftsdwarf, butcher, bowyer,
leather works, or fishery kind. build_workshop cannot build any
building in the bone chain. placement.py already anticipates the
craftsdwarf's workshop: the affinity table has a row for
("workshop", "Craftsdwarf") wanting a stone stockpile at affinity
25 (STONEWORKING.md, section 4.1). Placement is ready; the build
action is not. The same gap blocks the stone and wood sides of the
craftsdwarf's workshop, so the fix is shared: one catalog entry
unlocks three industries, and this doc, STONEWORKING.md, and
WOODWORKING.md all depend on it.

### 4.2 No bone job can be queued

JOB_SPECS (actions.py) has exactly twelve jobs: brew, brew_fruit,
cook, make_bed, make_table, make_chair, make_door, make_barrel,
make_bucket, make_bin, make_chest, make_cabinet. Every one is a
still, kitchen, or carpenter job. There is no bone job, no
craftsdwarf job, no butcher job, and no bowyer job in the list.

The gap is structural, and it is deeper than a missing list.
queue_job (actions.py) takes a JOB_SPECS name and passes its
job_type and reaction_name to act_job.lua. act_job.lua builds job
items only from a reaction's reagents. A job with reaction_name None
gets a bare job with no job items at all. The one plain job that
works today is cook, job_type 115, reaction_name None, and it works
because the game fills in a meal job's materials when a cook claims
it. Whether the game does the same for MakeCrafts, MakeTotem,
MakeAmmo, or DecorateWith, and whether it picks bone when it does,
is the open question the whole industry turns on. A bare MakeCrafts
job could plausibly be claimed by a stonecrafter who makes a stone
craft, or by a woodcrafter who makes a wooden craft, or by nobody,
because the job names no material. Until a live probe queues one and
reads back what was made and from what, no bone job can be claimed
to work. That probe is phase 2, and it is the first probe, because
every later phase assumes its answer.

The one existing route that can express a bone job today is
manager_order_create (actions.py, act_order.lua). It takes a
df.job_type name directly and creates a manager order, which the
game dispatches to any workshop that can do it. It was verified live
for a generic order, but no bone job type has been passed through it,
whether the manager validates and dispatches a bone job without a
manager noble appointed is UNVERIFIED, and whether a manager order
can carry the material choice (bone, not stone) is UNVERIFIED
(STONEWORKING.md, section 4.2, same gap). The manager route is the
fallback if the direct queue route cannot carry a material; it is
not the plan.

### 4.3 The harness can already see bones, and does not report them

stocks.lua counts every item type in by_type, so CORPSEPIECE (bones),
TOTEM, and AMMO are already in the collect. The fixture
observe-athelunol.json proves it: AMMO 48 units in 6 stacks, REMAINS
6 units in 6 stacks, and no CORPSEPIECE row at all, which means that
fort held no bones at that time. But nothing in the harness reports
those numbers. The stocks headline section carries drink, food,
seeds, wood, stone, cloth, thread, metal bars, barrels, empty
barrels, bins, and buckets, and no bone, shell, skull, horn, tooth,
ivory, or totem count. The by_material breakdown, which could say
which creature a bone came from, is built only for DRINK, FOOD,
MEAT, FISH, PLANT, SEEDS, BAR, WOOD, CLOTH, and THREAD items.
CORPSEPIECE is not in that list, so even the collect carries no
bone-by-creature breakdown. The snapshot renders none of it. The
agent cannot tell a fort with 40 bone stacks from a fort with none
without a query, and there is no query route that returns the count.

The labor route already works for the assignment half. act_labor.lua
enables or disables any df.unit_labor by name on one citizen,
verified by read-back, and BONE_CARVE is labor index 55 in the live
runtime enum. The labor plan (LABOR.md) owns who gets it; this doc
owns what they produce. Nothing today picks who carves bone, checks
whether a bone carver exists, or checks whether they are alive. The
same gap the kitchen doc names for the cook exists here for the bone
carver, and for the butcher and the bowyer alongside.

### 4.4 What the agent can see today

* The snapshot's Buildings line names each workshop by subtype and
  id, and says "Still: none" when there is no still. It does NOT
  name a missing craftsdwarf's workshop, butcher's shop, or bowyer's
  workshop. The agent cannot tell from the snapshot whether bone
  carving is possible at all.
* The snapshot's Stocks line prints no bone number. A fort could be
  sitting on a hundred bones with no carver and the snapshot would
  be silent about both halves of that fact.
* The snapshot's Materials section (materials.py) knows the
  carpenter's build material and the still's and kitchen's. It knows
  nothing about bone jobs, because no JOB_SPECS entry exists for
  them to hang requirements on. materials.py carries the 1-log rule
  as _WOOD_1 for the nine carpenter jobs and nothing for bone.
* The diary feed groups queued jobs by workshop, so a bone job
  queued through any route would appear under its workshop once
  the workshop exists. No diary work is needed for bone carving
  beyond that.
* TASK_DEFS (daemon.py) has six tasks: brew, cook, make_bed,
  make_barrel, gather, farm. There is no bone task, no bolt task,
  and no totem task. The planner has no bone threshold, no bolt
  floor, and no craft decision anywhere.

## 5. The bone budget: the ledger

The budget is arithmetic from verified numbers, not a feeling. One
bone is 5 bolts, or 1 to 3 crafts averaging 2, or 1 decoration. One
skull is 1 totem. Bone armor costs 8 bones from at least 7 stacks
for a set with no torso or feet. Every bone-family material has base
value 1, so value comes from the item and its quality, never from
the material.

### 5.1 The reserve

The fort holds one reserve, in priority order, before any bone is
spent on production. A reserve is a number the harness defends: bone
below the reserve is never spent on anything below it in priority.

1. **Mood reserve.** Shells held back for strange moods, per
   FISHING.md, plus bone stacks held back the same way. The reserve
   is 5 shells and 5 bone stacks to start, tuned live. A moody
   dwarf takes an entire stack, so the reserve counts stacks, not
   bones: 5 stacks of 1 bone each is a better reserve than 1 stack
   of 5 bones, because a mood takes the whole stack either way and
   the single-bone stacks waste less. The reserve is spent only
   when a mood demands bone or shell, never for crafts, bolts, or
   armor.
2. **Bolt floor.** Enough bone bolts in stock for the hunters and
   marksdwarves to hunt and train. The floor is 5 bolts per hunter
   and marksdwarf per season of expected use, computed from the
   military and hunting plans, not guessed here. HUNTING.md owns
   the number; this doc owns making the bolts to meet it.
3. **Everything else.** Crafts, totems, decorations, and armor spend
   bone above the reserve and the bolt floor only. A craft made
   from a reserve bone is a mood failed later, and a bolt made from
   a reserve bone is a hunt that cannot happen.

The combined hard reserve for a starting fort is small: 5 shells and
5 bone stacks held back, and the bolt floor on top. The fort that
butchers one animal a week accumulates bone faster than it spends it,
so the reserve is almost always covered and the constraint almost
never binds. Its value is in the week it does bind: the week a mood
strikes and the shells are gone because a carver spent them on crafts
in spring.

### 5.2 The bolt ledger

Bone bolts exist in two states, and the snapshot must carry both,
not a total:

* Bone bolts in stock: AMMO items of bone material, counted by
  stack. One stack is 5 bolts. The fixture fort held 48 AMMO units
  in 6 stacks; whether those were bone, wood, or metal is
  UNVERIFIED, because the snapshot never renders ammo by material.
  Phase 1 makes the split visible.
* Bolts in quivers: carried by hunters and marksdwarves. A bolt in
  a quiver is not a bolt in stock, and a hunter with an empty
  quiver is a hunter who cannot hunt, however big the stockpile
  looks. Whether the harness can read quiver contents per dwarf is
  UNVERIFIED (section 13, open question 10).

The ledger prevents the woodworking repeat: the planner queues bolts
only up to the bolt floor shortfall, never a round number. Five
missing bolts means queue 1 bone job, not 10. A bone job takes
carver time that a totem job needs, and 10 bolt jobs is 10 bones and
a season of carver time spent solving a 1 bone problem.

### 5.3 The decay ledger

Bones rot. The budget counts the loss, not just the stock:

* Bones in the usable-refuse stockpile, counted by stack.
* Bones lying where they were made, in the butcher's shop or on the
  ground, unhauled. A bone unhauled is a bone rotting in the open,
  and the refuse stockpile exists to stop exactly that.
* Bones lost to vermin and decay per season, counted from the job
  events and the stock deltas. A fort losing more bones to rats
  than it carves is a fort that needs a cat on the pile, not a
  bigger hunt.

Whether the collect can distinguish a bone in a stockpile from a
bone on the ground is UNVERIFIED (section 13, open question 11).
Phase 1 verifies it. Until then the decay ledger is a stock delta
over time, not a location count.

## 6. Bone carver production priorities

The carver has one worker and one job at a time. The queue order is
the priority order, and the harness enforces it. The agent picks the
batch size; the harness picks the order.

1. **Bone bolts, to the bolt floor.** Ammunition is survival for a
   hunting fort: no bolts, no hunt, no meat, no more bones. Bolts
   first, always, while the floor is unmet.
2. **Totems, from skulls.** One skull is one totem, and a skull has
   no other use. Skulls never compete with bolts, because bolts
   take bones, not skulls. A totem is free trade value from a part
   that would otherwise rot.
3. **Crafts, from bone above the reserve.** One bone is 1 to 3
   crafts, averaging 2. Crafts are made in the season before the
   caravan they serve, because a craft made in spring for a caravan
   in autumn is a bone that could have been bolts in summer.
4. **Decorations, on demand.** One bone or shell decorates one item.
   Decorations are made when an item worth decorating exists, not
   on a schedule. A masterwork bed or a good statue is worth
   decorating; a plain bin is not.
5. **Bone armor, only on ask.** One set costs 8 bones from 7 stacks
   and leaves the torso and feet bare. It is made when the military
   or hunting plan asks for it by name, for a named dwarf, in the
   numbers it asks for. Never stockpiled, never a default.
6. **Shell crafts, from shells above the reserve.** Shells are
   scarcer than bones and finite over years of fishing, so shell
   crafts spend only above the 5-shell mood reserve, and only when
   bones are short. A shell spent on a craft is a shell the fort
   cannot get back by hunting.
7. **Horn, tooth, and ivory crafts, when they exist.** These are
   rare on most maps. When the count is above zero, they are
   crafted like bone, and their crafts are worth the same as bone
   crafts of the same quality, since every bone-family material has
   value 1. Their value is variety for the caravan, not price.

A batch is never larger than the bone above the reserve and the bolt
floor. If the fort holds 40 bone stacks and the reserve is 5, the
carver can spend 35 stacks on discretionary work, but only a batch
at a time, because a strange mood can claim the workshop and demand
a stack overnight, and a 35-stack queue cannot be unmade.

## 7. Bolt and crossbow policy

* **Bone bolts before wood bolts, when bone is free.** Bone bolts
  pierce metal armor; wooden bolts do not do so as well, and a log
  is also a bed or a barrel. When bones are above the reserve, the
  fort makes bone bolts first and wood bolts only when bones run
  out. When bones are at the reserve, wood bolts carry the hunt.
* **One bone, five bolts, no skill bonus on count.** A dabbling
  carver makes the same 5 bolts as a legendary one. Skill changes
  quality, and quality changes whether a bolt is a plain bolt or a
  fine one, but the count is fixed. So the bolt maker is whoever
  is free with the labor, not a specialist to train, until the
  carver is the bottleneck.
* **Crossbows are three workshops.** A working marksdwarf needs a
  bone or wooden crossbow from the bowyer, bone or wooden bolts
  from the craftsdwarf, and a quiver from the leather works. The
  harness never promises a marksdwarf until all three exist, and
  the snapshot says which of the three is missing, by name.
* **Bone crossbows are for hunters first.** A bone crossbow shoots
  as well as a metal one and weighs less, which suits a hunter who
  walks all day. It is nearly useless in melee, so it never goes
  to a dwarf expected to stand and fight. Marksdwarves get metal
  crossbows when the forge exists; hunters get bone.
* **Bolts are stored apart by material.** Bone bolts and wood bolts
  in separate stockpiles, per MILITARY.md, so the fort knows which
  ammunition it has and the hunter takes the better bolt first.
  Whether the harness's stockpile action can sort ammo by material
  today is UNVERIFIED (section 13, open question 12); STOCKPILES.md
  owns the stockpile settings gap, and this doc does not re-solve
  it.

## 8. Crafts, totems, and trade policy

* **Stone first, bone second, wood third.** The trading plan already
  sets stone mugs and crafts as the default trade good, because
  stone is free and unlimited (TRADING.md). Bone crafts are the
  second fallback, ahead of wood, because bone is also free and
  unlimited while the fort hunts, and a bone craft costs no log.
  Wood crafts stay last, because a log is a bed or a barrel.
* **Never trade bone goods to elves.** Elves refuse bone, shell,
  horn, ivory, hair, chitin, and scales, and one wrong item ends
  the session (TRADING.md, section 2.5). The elf filter in the
  trading plan already refuses animal products for the spring
  caravan; this doc adds that the harness must never put a bone,
  shell, horn, ivory, or totem item in the trade stockpile in
  spring, even by accident, because a totem is a skull and a skull
  is a body part, and the ban covers body parts explicitly.
* **Totems are searched for by name.** Totems do not fall under any
  category in the trade-goods move screen, so a category filter
  misses them (Meat industry). The trade route must move totems by
  name search or explicit item list. A totem left in the finished
  goods stockpile when the caravan leaves is trade value the fort
  grew and never sold.
* **Value is quality, not volume.** A craft's value is its base
  times its material multiplier times its quality modifier, and
  every bone-family material has value 1, so a skilled carver
  making a few good crafts beats many dwarves making poor ones.
  The harness prefers one skilled carver making a few good crafts
  over many dwarves making poor ones, and it never queues crafts
  as a way to use up bone: surplus bone is a stockpile, not a
  production order.
* **Skull value decides the totem, not the carver.** A totem from
  an ordinary skull is worth about the same as a bone craft. A
  totem from a valuable animal's skull is worth much more. The
  harness makes totems from every skull it has, because a skull
  has no competing use, and it makes the valuable-skull totems
  first when the caravan is coming.
* **Decorations are the value multiplier.** A bone decoration on a
  good item raises that item's value for the same one bone a craft
  would cost. When the fort has one good statue and ten spare
  bones, decorating the statue beats making ten more crafts. The
  harness decorates the best item in stock first, not the nearest.

## 9. Armor policy

* **Bone armor is a stopgap, never a uniform.** MILITARY.md already
  places it there: bone helms, bone leggings, bone gauntlets as a
  stopgap alongside wooden or leather shields, before metal exists
  (MILITARY.md). This doc adds the cost that makes the stopgap
  honest: 8 bones from 7 stacks for a set with no torso or feet,
  for armor that loses to copper. A stopgap is one set for one
  hunter, not a uniform for a squad.
* **Hunters first, trainees second, soldiers never.** Hunters get
  bone armor because they choose small prey and need light armor
  to move quickly. Trainees get it because sparring cannot injure
  them and any armor covers a fall. Soldiers expecting metal
  weapons get metal armor or nothing, because bone against a metal
  weapon is hardly better than wearing nothing (Bone).
* **Shell armor when bone is short.** Shell leggings, gauntlets,
  and helms follow the same rules with one less piece. Shell armor
  is better than nothing and does not slow the military like metal
  armor does (Shell). It spends shells above the mood reserve
  only, and only when bone is short, because shells are scarcer
  and finite.
* **Never spend a reserve bone on armor.** Armor is priority 5 in
  section 6, below bolts, totems, crafts, and decorations, and the
  reserve sits above all of them. A bone armor set made from
  reserve bones is a mood failed for a greave that would not have
  saved its wearer anyway.
* **Protect the head and torso first.** The Bone page's own advice:
  avoid helms and chest pieces if any metal is available; protect
  the head, protect the torso. A broken limb heals, and even a
  gimped dwarf can still pull a lever, while a crushed skull or
  organ loss is usually just fatal (Bone). Bone greaves are the
  least bad bone armor item. The harness makes greaves before
  leggings when it makes bone armor at all, and never makes a bone
  helm while a metal helm is available for the same dwarf.

## 10. Layout

Layout is scored placement (docs/SITE_SELECTION.md, queued work),
with bone-carving factors on top of the shared threat, cover, and
traffic factors:

* **The triangle.** Butcher's shop, usable-refuse stockpile, and
  craftsdwarf's workshop belong together, within a few tiles of
  each other. The butcher makes bones, the stockpile holds them,
  the carver takes them. A carver far from the bone stockpile pays
  the hauling cost on every item, and a bone left in the butcher's
  shop rots while the carver walks.
* **The usable-refuse stockpile sits near the butcher and the bone
  carver, not in traffic, behind a door.** Bones in traffic give
  dwarves negative thoughts, and the stockpile's own page says to
  put it behind a door (Bone; STOCKPILES.md, usable-refuse row).
  The door is not decoration: it is the difference between a
  carver who sees bones all day and a fort that does.
* **The fishery feeds the shell pile.** The shell stockpile sits
  near the fishery, and craftsdwarf workshops sit next to the
  shell stockpile (FISHING.md). Shells travel a short distance
  from fish to carver, and the mood reserve shells sit in the same
  pile, marked held, not in a separate pile the carver forgets.
* **The bowyer sits near the craftsdwarf and the leather works.**
  The crossbow, the bolts, and the quiver are one kit, and the
  three workshops belong together so the kit is assembled in one
  place, not hauled across the fort.
* **The carver sits near the trade stockpile.** Crafts, totems, and
  decorations are trade goods, and their destination is the depot.
  A carver far from the finished-goods stockpile pays the hauling
  cost on every craft, twice: once to the stockpile, once to the
  depot.
* **Cats on the pile.** A cat pastured over the bone stockpile
  minimizes vermin decay (Bone). The pasture is part of the
  layout, not an afterthought: a bone pile with no cat loses bone
  to rats faster than a carver with no workshop loses time.

## 11. Failure modes

Every failure mode in this table has a diagnosis the harness must
produce, with the fix named. A silent zero is never acceptable.

| Failure | Cause | Diagnosis | Fix |
| --- | --- | --- | --- |
| No bone bolts, hunters idle | No carver, no craftsdwarf's workshop, or bones at the reserve | "bone bolts N, bones M stacks, reserve R, craftsdwarf none" | Build the workshop, assign a carver, queue bolts to the floor |
| Bolts queued, nothing made | Bare hardcoded job never claimed, or claimed by a stonecrafter | "MakeAmmo jobs N, no bone bolts after a day" | Phase 2 probe result decides the route; do not requeue blind |
| Stone crafts from a bone order | Bare MakeCrafts job picked stone, not bone | "crafts made N, bone crafts 0, stone crafts N" | Material selection route from phase 2; never assume the pick |
| Mood fails for want of bone or shell | Reserve spent on crafts, or no shells on the map | "mood needs bone/shell, stock 0, reserve spent" | Hold the reserve; catch pond turtles before the mood strikes |
| Bones rot in the butcher's shop | No usable-refuse stockpile, or no hauler | "bones unhauled N, refuse stockpile none" | Build the stockpile near the butcher; add haulers |
| Miasma in the fort | Rotting refuse stored subterranean and dark | "miasma at (x, y, z), rotting refuse N" | Move refuse above ground or to light; destroy the rot |
| Bone goods offered to elves | Trade stockpile held bone in spring | "bone items in trade stockpile, elves present" | Remove bone goods from the trade stockpile; refuse the offer |
| Totems never sold | Category filter misses totems at the depot | "totems in stock N, totems traded 0" | Move totems by name search or explicit item list |
| Bone armor made for a squad | Armor queued as a default, 8 bones per set | "bone armor sets N, bones spent M, torso bare" | Armor only on ask, for a named dwarf; greaves first |
| Carver idle, bones in stock | No labor assigned, or carver on another job | "bones N stacks, bone carvers 0" | Assign a bone carver; keep a backup warm |
| Shells gone, no more coming | Fishing fished out the shell-bearing fish | "shells 0, shell fish extinct" | Hold the reserve; trade for tortoises or armadillos |
| Cooked shelled creature loses its shell | Cooking enabled for turtles and shellfish | "turtles cooked N, shells lost N" | Disable cooking for shell-bearing animals (FISHING.md) |
| Moody dwarf takes a whole stack | Reserve held as one big stack, not singles | "mood took stack of N bones, reserve now 0 stacks" | Split the reserve into single-bone stacks before the mood |
| Craftsdwarf's workshop full when a mood strikes | Long queue on the only workshop | "mood claimed workshop, jobs queued N" | Keep one workshop unqueued when the fort has more than one |

## 12. Cross-doc conflicts flagged

1. **MILITARY.md, bolt workshop, wrong.** MILITARY.md says bolts
   come "from a bowyer's workshop in wood or bone, 25 bolts per bar
   or log, 5 per bone". The workshop is wrong: bolts are made at a
   craftsdwarf's workshop or at a forge, from wood, bone, or metal
   (HUNTING.md; Bowyer's workshop page, which says ammo is made
   elsewhere). The bowyer's workshop makes only the crossbow. The
   stack sizes (25 per bar or log, 5 per bone) are right. MILITARY.md
   needs the workshop corrected; this doc and HUNTING.md agree
   against it.
2. **FISHING.md, repeating shell orders, assumed.** FISHING.md plans
   on "repeating 'decorate with shell' orders" at craftsdwarf
   workshops next to the shell stockpile. The harness has no
   repeating-order mechanism today: TASK_DEFS has six tasks, none
   of them repeats a workshop job, and queue_job queues a fixed
   count. The FISHING.md plan is a design direction, not a working
   route, until a repeat mechanism lands. This doc does not
   re-solve it; it flags that the plan assumes a mechanism that
   does not exist.
3. **MILITARY.md, bolt stockpile split, consistent but unbuilt.**
   MILITARY.md wants wood and bone bolts in separate stockpiles.
   This doc agrees, and notes the stockpile settings write to
   enforce it does not exist yet (STOCKPILES.md, section 3.3: no
   settings write anywhere in the harness). The policy is agreed;
   the enforcement is a gap, not a disagreement.
4. **HUNTING.md, bolt loop, consistent.** HUNTING.md states the
   hunt-butcher-carve loop and the 5-bolts-per-bone rule, and names
   the craftsdwarf's workshop as the bolt shop. This doc agrees on
   every point. No correction needed.
5. **STONEWORKING.md and WOODWORKING.md, craftsdwarf's workshop,
   shared gap.** All three docs need the same catalog entry, and
   all three need the same hardcoded-job material-selection answer.
   The gap is filed once, in each doc's phase 2, and the fix lands
   once for all three. No doc should build its own craftsdwarf
   entry or its own job shape.

## 13. Open questions (UNVERIFIED)

1. **Material selection for hardcoded craft jobs.** Can the harness
   queue MakeCrafts, MakeAmmo, MakeTotem, DecorateWith, MakeArmor,
   or MakeHelm with bone as the material, through queue_job with a
   JOB_SPECS entry that has reaction_name None? act_job.lua builds
   job items only from reaction reagents, so a bare job carries no
   material. The game may fill the material in when a dwarf claims
   the job, or the job may sit unclaimed, or a stonecrafter may
   claim it and make stone. Phase 2 probes it live, one job type
   at a time, reading back what was made and from what.
2. **Manager order as the material route.** If the direct queue
   cannot carry a material, can manager_order_create carry it, and
   does the manager dispatch a bone job without a manager noble
   appointed? Phase 2 probes it as the fallback, and records
   whether the order carries a material filter at all.
3. **Craftsdwarf's workshop size and build material.** What are the
   workshop's dimensions, and does it accept any non-economic
   building material like the wiki says? Phase 1 probes it live
   with a build and a read-back.
4. **Armor piece to job type mapping.** Which job types make bone
   leggings, greaves, gauntlets, and helms? MakeHelm 102 is the
   likely helm job and MakeArmor 101 the likely armor job, but
   whether leggings and greaves go through MakePants 103 and
   gauntlets through MakeGloves 116 is unproven. Phase 5 probes
   each piece live and records the mapping.
5. **Bone crossbow job type.** Is MakeWeapon 97 the job that makes
   a bone crossbow at a bowyer's workshop, and does it pick bone
   over wood? Phase 3 probes it live.
6. **Bone armor in uniforms.** Can the harness's uniform route
   express a bone armor piece, for example "white greaves", and
   will a dwarf equip it? Phase 5 probes it live.
7. **Forbidding and reserving stacks.** Can the harness forbid a
   bone stack, or reserve one for moods, through DFHack on r8, and
   does the reserve survive a reload? Phase 6 probes it live.
   Until then the reserve is a planner number, not an enforced
   hold.
8. **Bone instruments.** The workshop page lists bone instruments
   and instrument pieces, but the enum has no MakeInstrument job
   type. Are they made through MakeCrafts, MakeToy, or a route the
   enum does not expose? Phase 4 probes it live, and if no route
   exists the doc records bone instruments as unmakeable by the
   harness.
9. **Pearl source.** Is there any fortress-mode pearl source on the
   fort's map, and if not, does the harness ever need to care about
   pearl? Answered by live observation, not by guessing.
10. **Bolts in quivers.** Can the harness read quiver contents per
    dwarf, so the bolt ledger counts bolts carried as well as bolts
    in stock? Phase 1 probes it live.
11. **Bone location in the collect.** Can the collect distinguish
    a bone in a stockpile from a bone on the ground, for the decay
    ledger? Phase 1 verifies it against the live collect.
12. **Ammo stockpile by material.** Can the harness's stockpile
    action sort ammo by material, so bone bolts and wood bolts sit
    apart? Phase 3 probes it; STOCKPILES.md owns the settings
    gap.
13. **Live bone counts.** The fort's actual bone, skull, shell,
    horn, tooth, and ivory counts are UNVERIFIED: the daemon and
    game were down when this doc was written, and no live snapshot
    could be read. Phase 1 reads them live and replaces every
    illustrative number in this doc.
14. **Bone crossbow melee.** The wiki says a bone crossbow is
    nearly useless in melee. The exact melee penalty, and whether
    a hunter with a bone crossbow survives a forced melee, is
    UNVERIFIED. Answered by live observation, not by guessing.

## 14. Model presentation

This section is required by the 2026-11-27 presentation constraint
(GOAL.md, coordinator log 2026-11-27 about 17:47 PT): every new
system must state how its information reaches the model, what it
costs, and what it deliberately does not push. The snapshot stays an
index: counts, exceptions, and diffs only, about 4,700 tokens
typical, never a replacement for full state. Budgets hold (target
30K, warning 60K, compaction 100K, hard cap 140K on a 200K window),
enforced by the assembler's token accountant with its cut order. No
system bolts its own dump onto the snapshot.

Token costs below are computed from the exact section text with the
accountant's own rates (3 chars per token for the cap, 4 chars per
token on the wire). They are estimates until the coordinator verifies
them against the live assembler before commit, as the amendment
requires. The numbers are small because the section is an index: it
names counts and exceptions, and the detail lives behind queries.

### 14.1 Snapshot: the Bone carving section

The per-tick snapshot gains a short Bone carving section, built from
the fresh collect, in plain words. Four lines when quiet, five when
an attention item fires. It is counts and exceptions, never a dump.

Proposed quiet text. Only two numbers in it are live values from a
real collect: AMMO 48 units in 6 stacks and REMAINS 6, both read
from the fixture observe-athelunol.json. Every other number is
illustrative, showing the shape, and phase 1 replaces it with live
values when the section is verified.

```
Bone carving: bones 14 stacks (7 kinds), skulls 3, shells 9, ivory 0, horn 2.
  Craftsdwarf #18 built, idle; butcher #11 built; bowyer: none.
  Bone bolts 10 (2 stacks), bone crafts 4, totems 1; bone armor 0.
  Mood reserve: shells held 5, bones held 5 stacks; refuse bones rotting 0.
```

Proposed attention line, added as a fifth line only when it fires:

```
  Attention: hunters have 0 bone bolts with 14 bone stacks unworked; queue 2 bolt jobs.
```

What each line is:

* Line 1 is a count (bone stacks with the kind count, skulls,
  shells, ivory, horn). The kind count says whether the fort has
  one kind of bone or many, which decides whether a mood can be
  picky. Teeth and pearl are not in the line: both are rare enough
  to be a query, and a zero for both every tick is noise.
* Line 2 is a count plus a state (the craftsdwarf's workshop id and
  state, the butcher's shop id, the bowyer state). The workshop id
  is repeated from the Buildings line deliberately: the bolt and
  craft decisions need it in the same breath as the numbers. A
  missing workshop is an exception, not a silence: "bowyer: none"
  says the crossbow route is closed.
* Line 3 is a count (bone bolts with stacks, bone crafts, totems,
  bone armor). The bolt stack count is the ledger: 2 stacks is 10
  bolts, and the model never has to divide.
* Line 4 is a count (the mood reserve held, refuse bones rotting).
  The reserve held is the defended number from section 5.1, and
  the rotting count is the decay ledger from section 5.3. While
  there is no refuse pile the line reads "refuse bones rotting:
  unknown", so the model never mistakes an unread number for zero.
* Line 5 is an exception, present only when it fires: hunters with
  no bolts while bones sit unworked, a mood demanding bone or shell
  the fort lacks, or bones rotting faster than they are carved. It
  is ranked with the other attention entries, never buried in a
  list.

Token cost, by the accountant's rule (length divided by 3):

* Quiet section: 285 characters, 95 tokens by the accountant, 71
  tokens on the wire. Counted from the proposed text above with
  the accountant's rule, not estimated.
* With the attention line: 373 characters, 124 tokens by the
  accountant, 93 tokens on the wire.
* At 7 dwarves and at 50 dwarves, the cost is the same within about
  10 tokens. The section carries counts only, no per-dwarf lines,
  so it does not grow with population. The growth at 50 dwarves
  lands in the Units section (exceptions capped at 8) and the
  profession counts (top 8), not here. A second craftsdwarf's
  workshop adds one short clause to line 2, about 12 tokens, and
  only while it exists.
* Against the budgets (target 30K, warning 60K, compaction 100K,
  never over 140K on a 200K window), the quiet section is about
  0.3 percent of the target, and the whole snapshot stays an index
  at about 4,700 tokens typical. The section is a budget decision
  reviewed against the accountant, not a default, and its cost is
  stated here so the review can check it.

What is not in the snapshot, and why:

* Not the bone list by creature. Bones come in many kinds, and a
  list of them grows with the hunt. The kind count is in line 1;
  the breakdown lives behind the query route.
* Not the full finished-goods inventory. Bone bolts, bone crafts,
  totems, and bone armor are the bottleneck goods; shell crafts
  and horn crafts are not, and their counts live behind the query
  route.
* Not the craftsdwarf reaction list. There is no reaction list for
  bone jobs: they are hardcoded job types, and the job names live
  in the catalog, read on demand for the action the model needs,
  per the 6-tool surface rule. The snapshot never carries a menu.
* Not per-dwarf bone carving skill. The assignment (who, and
  whether a backup exists) is in the query route. The snapshot
  carries the workshop state, not the skill table.
* Not the refuse pile contents. Rotting refuse is a count in line
  4; the per-item list is survey data, pulled by region when the
  model needs it.

### 14.2 Query route: GET /v1/bone-carving

GET /v1/bone-carving returns the full detail, read from the fresh
collect, not from a cache. The snapshot carries the summary; the
route carries the detail. The agent asks the route when it needs to
choose, never as a matter of routine.

Response shape:

* Bone: total stacks and units, stacks by creature kind, skulls by
  creature kind, shells, horn pieces, teeth, ivory pieces, pearls,
  and the mood reserve held against each.
* Bolts: bone bolts, wood bolts, and metal bolts in stock by stack,
  bolts in quivers per dwarf where the collect supports it, and
  the bolt floor from the hunting and military plans.
* Goods: bone crafts, shell crafts, horn crafts, totems, and
  decorations in stock, with computed values, and the caravan
  target from TRADING.md.
* Armor: bone and shell armor pieces in stock by type, and which
  dwarves wear them.
* Workshops: the craftsdwarf's workshop, butcher's shop, bowyer's
  workshop, and fishery with ids, construction stage, current
  jobs, and queued jobs, or "none".
* Labor: bone carvers, butchers, and bowyers by name and skill,
  and whether each assignment has a backup.
* Budget: the mood reserve, the bolt floor, the bone burn rate,
  and the decay ledger from section 5.3.

The snapshot carries the pointer so the model knows the route
exists: the craftsdwarf id in line 2 and the bone and bolt counts
in lines 1 and 3 are the pointer. The route is one query; the
existing /v1/stocks and /v1/buildings routes already answer the
ammo total and the workshop list, and this route adds the bone
breakdown, the bolt split by material, and the reserve those routes
do not carry.

### 14.3 Briefing: what arrives just in time

Bone carving has no standing briefing. Two events carry one, both
from the existing briefing system (briefings.py), each a few hundred
tokens at most, each fired once when the event starts:

* **Strange mood claims a craftsdwarf's workshop.** Trigger: the
  strange_mood event. Cost: about 38 tokens by the accountant for
  the bone-carving paragraph (115 characters, counted from the
  example text "Strange mood at the craftsdwarf's workshop. Bone
  in stock 14 stacks, shells 9, reserve held 5 and 5. Workshop
  free."). It covers whether
  the bone or shell the mood demands is in stock and in the
  reserve, and whether the workshop is free. It leaves the stack
  forbidding and the mood plan to the query route and to the mood
  handling in the events doc.
* **Caravan arrives.** Trigger: the caravan event. Cost: about 42
  tokens by the accountant for the bone-carving paragraph (126
  characters, counted from the example text "Bone goods for trade:
  4 bone crafts, 1 totem, value about 100. Totems need a name
  search at the depot. No bone goods to elves."). It covers what bone goods are in the trade
  stockpile and their approximate value, whether totems exist, and
  the elf rule: no bone good goes to elves. It leaves the per-item
  values and the depot haggling to the query route and to
  TRADING.md.

No other bone-carving event briefs the model. A carver finishing a
masterwork, a bolt stock hitting zero, or a bone pile rotting are
attention entries and opportunities entries, not briefings. A
briefing is for something the model needs to understand right now,
not for something it can read in the snapshot.

### 14.4 Opportunities: at most 3, facts only

The opportunities section does not exist in the code yet (gap
review 3, P2-3: the only "opportunit" hit in src/ is a briefing
string). Until that gap closes, the entries below have nowhere to
land, and this doc does not pretend otherwise. When the mechanism
lands, bone carving contributes at most 3 entries, each facts plus
a query route, never a suggestion, never a pause, and ignoring one
costs nothing:

* "Bones 14 stacks in stock, no bone bolts. Query:
  GET /v1/bone-carving."
* "Skulls 3 in stock, no totems made. Query:
  GET /v1/bone-carving."
* "Shells 9 in stock, mood reserve 5 held, 4 above reserve. Query:
  GET /v1/bone-carving."

An opportunity is not a suggestion: it carries no recommended action
and no priority, and the suggestion uptake metrics do not count it.
If the mechanism never lands, the snapshot and the briefing still
carry the system, and nothing is lost except the low-pressure
channel.

### 14.5 What the system deliberately does NOT push, and why

* The full bone list by creature. The fort hunts many kinds, and
  the list grows with the hunt. The kind count is pushed; the list
  is a query.
* Per-bone positions. Where each bone lies is survey data, pulled
  by region when the model needs it. Pushing it would grow the
  snapshot with the map, which breaks the index.
* Per-item trade values. The snapshot says how many bone crafts
  are in the trade stockpile. The computed value of each item is
  behind the query route, because values change with quality and
  material and the snapshot cannot reprice the stock every tick.
* The whole job queue. The snapshot says "2 jobs queued (bolts)".
  The full queue, with job ids and positions, is behind the
  workshop query route. A queue dump would grow with every job
  the fort queues.
* The mood reserve as a standing line. The reserve held is one
  count in line 4, not a per-material table. The full reserve
  table is a query.
* Craft and totem placement suggestions. The snapshot never says
  "decorate this statue". Placement is the scored site system,
  and the model asks for a site when it decides to place
  something. The presentation gives the model what it needs to
  decide, not a script to follow (HARNESS_ROLE.md).

The reason in every case is the same: the snapshot is an index, and
an index carries counts, exceptions, and diffs. Anything the model
needs once a season, or once per decision, lives behind the query
route. Pushing it every tick would grow the snapshot toward the
budgets for information the model reads once and forgets.

## 15. Implementation phases

Each phase ends with a concrete live-verification bar. Nothing counts
as done until it passes its bar against the real game. Every phase
carries offline tests (including malformed-input tests per the
standing rule) and goes through the pre-push self-review gate before
it is committed and pushed.

### Phase 1: Observation

* Extend the stocks collect so the snapshot can see what bone
  carving needs: bone stacks and units by creature kind, skulls,
  shells, horn pieces, teeth, ivory pieces, pearls, totems, bone
  crafts, and bone bolts split from wood and metal bolts, as
  headline numbers. Add CORPSEPIECE to the by_material breakdown
  so the kind split exists at all.
* Add the Bone carving section to the snapshot (section 14.1) and
  the GET /v1/bone-carving route (section 14.2). Read the live
  bone, skull, shell, and bolt counts on the main fort and replace
  every illustrative number in this doc with them.
* Verify whether the collect can distinguish a bone in a stockpile
  from a bone on the ground, and whether quiver contents are
  readable per dwarf (open questions 10 and 11).
* Live bar: a live collect on the main fort shows the true bone,
  skull, shell, and bolt numbers, and each number matches a hand
  check against the game. The snapshot Bone carving section
  renders, and its token cost matches section 14.1 within 20
  tokens by the accountant's count.

### Phase 2: The craftsdwarf's workshop and the material question

* Add `craftsdwarf` to WORKSHOP_CATALOG (material: any
  non-economic building material; dimensions from the live probe)
  and `butcher` for the supply side, shared with the animal and
  hunting work. The build route is the existing build_workshop;
  only the catalog entries are new.
* Probe the hardcoded bone jobs live, one at a time, through
  queue_job with a JOB_SPECS entry that has reaction_name None
  and the enum index as job_type: MakeCrafts 83, MakeAmmo 129,
  MakeTotem 128, DecorateWith 130. For each, record whether the
  job is claimed, who claims it, what is made, and from what
  material. If the direct route cannot carry a material, probe
  manager_order_create as the fallback and record whether the
  order carries a material filter.
* Add the jobs that work to JOB_SPECS, materials.py, and the
  catalog, in the same shape as cook: an int job_type, no
  reaction, a skill of BONECARVE. Document the jobs that do not
  work, with what blocked them, and do not pretend otherwise.
* Live bar: on the scratch fort, a craftsdwarf's workshop is built
  by build_workshop and read back with its subtype and id; a bone
  bolt job is queued and 5 bone bolts are read back in stock; a
  bone craft job is queued and a bone craft is read back, made
  from bone, not stone or wood. A job queued with no bone in stock
  fails fast with the material named.

### Phase 3: Bolts, crossbows, and the marksdwarf kit

* Add the bowyer's workshop build kind and probe MakeWeapon 97
  for the bone crossbow live. Add the bolt floor to the planner:
  queue bolts only up to the shortfall, never a round number.
* Wire the three-workshop check: the harness reports which of the
  bowyer, the craftsdwarf's workshop, and the leather works is
  missing before it promises a working marksdwarf.
* Add the bolt split to the observation: bone, wood, and metal
  bolts counted separately, in stock and in quivers where the
  collect supports it.
* Live bar: a bone crossbow is made live and read back; a stack of
  5 bone bolts is made from 1 bone and read back; a hunter is
  equipped with crossbow, bolts, and quiver and hunts with them.
  A bolt queue above the floor shortfall is refused live with the
  shortfall named.

### Phase 4: Crafts, totems, decorations, and trade

* Add the specific craft-subtype jobs that phase 2 proved
  drivable (MakeFigurine 229, MakeAmulet 230, MakeRing 233, and
  the rest), and the MakeTotem and DecorateWith jobs, wired to the
  production priorities in section 6.
* Wire the elf filter: no bone, shell, horn, ivory, tooth, pearl,
  or totem item enters the trade stockpile in spring, enforced in
  code, not by the agent remembering.
* Wire the totem name search into the trade route, so totems move
  to the depot despite falling outside every trade category.
* Probe bone instruments (open question 8) and record the answer.
* Live bar: a batch of bone crafts is made live and its value is
  read back; a totem is made from a skull and read back; a totem
  reaches the depot by name search and is offered to a non-elf
  caravan. A bone item is refused from the spring trade stockpile
  live, with the elf rule named.

### Phase 5: Bone and shell armor

* Probe the armor piece to job type mapping live (open question
  4): MakeArmor 101, MakeHelm 102, MakePants 103, MakeGloves 116,
  one piece at a time, reading back what each job makes and from
  how many bone stacks.
* Add the armor jobs that work, wired to the military and hunting
  plans' ask only: never a default queue, never a stockpile.
* Probe bone armor in uniforms (open question 6).
* Live bar: a bone helm, a pair of bone gauntlets, and bone greaves
  are made live and read back, with the stack counts matching
  section 2.5 (1 bone for the helm, 1 for the gauntlets, 3 stacks
  for the greaves). A squad is not given bone armor by default.

### Phase 6: Refuse, reserve, and planner decisions

* Add the usable-refuse stockpile placement to the planner, near
  the butcher and the carver, behind a door, with a cat pastured
  over it.
* Implement the mood reserve (5 shells, 5 bone stacks, single-bone
  stacks preferred) and the bolt floor from section 5, recomputed
  every tick from the live bone counts. Wire the reserve into the
  planner: production jobs are refused when they would spend below
  it, with the reserve named.
* Add the strange-mood bone briefing (section 14.3) on its trigger,
  and the decay ledger to the observation.
* Probe stack forbidding and reserving through DFHack (open
  question 7) and record whether the reserve can be enforced or
  stays a planner number.
* Live bar: a live M1 day holds the mood reserve without the model
  being asked, a production job that would spend below the reserve
  is refused live with the reserve named, and the strange-mood
  briefing fires live on a forced mood and names the stock. Bones
  in the usable-refuse stockpile are read back, and the rotting
  count falls after the stockpile is built.

## 16. Refusals

The bone-carving system refuses, and says why, in plain words:

* Never add a CARVE_BONE reaction to JOB_SPECS. They are
  adventure-mode reactions, not fortress jobs. A fortress job
  queued from one of them cannot be worked.
* Never queue a bone job whose material the harness cannot prove.
  If MakeCrafts has no proven bone route, the harness says it
  cannot make bone crafts, and does not queue a job that might
  make stone crafts instead.
* Never spend a reserve bone or shell on crafts, bolts, or armor.
  The reserve is for moods, and a mood failed for a craft is a
  preventable failure.
* Never queue a round-number batch of bolts. The queue is the
  shortfall, and 10 bolt jobs for a 1 bone problem is a refusal,
  not a strategy.
* Never make bone armor as a default or a uniform. Armor is made
  on ask, for a named dwarf, greaves first, never for a squad.
* Never trade bone, shell, horn, ivory, tooth, pearl, or totem
  goods to elves, in any season, and never put one in the spring
  trade stockpile.
* Never claim a bone job works until a real item has been made
  from bone and read back. A job type name from the enum is not
  proof the game accepts it, and a manager order that sits
  unvalidated is not proof the game dispatched it.
* Never let bones rot in the butcher's shop while a carver waits.
  A bone unhauled is a bone lost, and the stockpile is the fix.
* Never store usable bone with rotting refuse. Sorting is the
  whole point of the usable-refuse stockpile, and mixed refuse
  rots the good with the bad.
* Never promise a working marksdwarf until the crossbow, the
  bolts, and the quiver all exist. Two of three is a dwarf with a
  club.

## 17. Sources

Wiki pages read from the local index
(`~/workspace/df-wiki-export/dfq.py`, hybrid search, 2026-11-27).
The index is a current-wiki export (4,485 pages, built 2026-11-24),
so pages can carry v50 markers; every claim below that depends on
the version was checked against the 0.47.05 raws or the live
runtime enum, and the check is named where it matters.

* Bone carver: the task list, the workshop, the attributes, bone
  bolts, lightweight bone and shell armor, totems from skulls,
  decorations.
* Craftsdwarf's workshop: the material list, the goods list, the
  build rule (any non-economic material, Bone Carving,
  Stonecrafting, or Woodcrafting labor), the bolt rule (one bone
  from a stack becomes 5 bolts), the armor costs (3 stacks for
  leggings or greaves, 1 bone for gauntlets as a pair, 1 bone for
  a helm), the mood claim on the workshop.
* Bone: acquiring bones from butchery and rot, bones never
  imported, bolts 1 bone to 5, bone armor inferior to copper,
  hunters and training as the uses, mood stack behavior and the
  single-bone stack guidance, bones as body parts in the stocks
  menu, refuse degradation and vermin, the bone depot behind a
  door.
* Refuse: bones as 5 bolts, a bone crossbow, 1 to 3 crafts, or a
  decoration; bone armor with no breastplates, mailshirts, or
  boots; shells for armor, crafts, decorations, and moods; skulls
  for totems; miasma from rotting refuse underground; refuse
  collection toggles.
* Shell: fishing and butchery sources, no trade source, fishing
  extinction over years, shell armor limited to leggings,
  gauntlets, and helms, shells cannot make bolts, the mood risk.
* Ivory: ivory and tooth as craft and decoration materials,
  elephant, hippo, narwhal, walrus, warthog, and wild boar tusks,
  usable teeth only from the largest animals.
* Butcher's shop: the yield table, slaughter instantaneous and
  pets exempt, butchering not instantaneous, the 20 tile and same
  z-level rule, the 43 by 43 by 1 box.
* Bowyer's workshop: bone and wooden crossbows only, metal at the
  forge, ammo made elsewhere, the quiver from the leather works.
* Finished goods: crafts 1 to 3 per resource averaging 2, skill
  does not affect multiples, totems the same base value as crafts
  with skull value on top, bone makes no goblets, the material
  table (bone, shell, horn craftable).
* Meat industry: one skull per animal, seven for a hydra, totems
  outside every trade-goods category and needing a name search.

0.47.05 raws, read from the shipped game
(`third_party/df_47_05/raw/objects/`):

* material_template_default.txt: BONE_TEMPLATE, TOOTH_TEMPLATE,
  HORN_TEMPLATE, PEARL_TEMPLATE, SHELL_TEMPLATE, each with
  MATERIAL_VALUE 1.
* reaction_other.txt: CARVE_BONE_FIGURINE, CARVE_BONE_RING,
  CARVE_BONE_EARRING, CARVE_BONE_SCEPTER, CARVE_BONE_AMULET,
  CARVE_BONE_BRACELET, CARVE_BONE_CROWN, CARVE_BONE_GEM, each
  with CATEGORY:ADV_BONE_CARVING, which proves they are
  adventure-mode reactions, not fortress jobs.
* The live runtime enum
  (tests/fixtures/runtime-enums-0.47.05-r8.json): MakeCrafts 83,
  MakeTotem 128, DecorateWith 130, MakeAmmo 129, MakeArmor 101,
  MakeHelm 102, MakePants 103, MakeGloves 116, MakeWeapon 97,
  MakeToy 123, MakeGoblet 122, MakeFigurine 229, MakeAmulet 230,
  MakeScepter 231, MakeCrown 232, MakeRing 233, MakeEarring 234,
  MakeBracelet 235, MakeGem 236, ButcherAnimal 105,
  SlaughterAnimal 182; workshop types Craftsdwarfs 3, Bowyers 7,
  Butchers 10; labor BONE_CARVE 55; skill BONECARVE. No
  MakeInstrument job type exists in the enum.

Harness state verified against the repo on 2026-11-27 (daemon and
game down, VM replacement about 19:37 PT; code facts only, no live
reads):

* actions.py JOB_SPECS (12 jobs, none bone), WORKSHOP_CATALOG
  (carpenter, mason, still, kitchen), queue_job (material
  fail-fast, already-queued count), manager_order_create.
* lua/act_job.lua (job items built only from reaction reagents;
  a bare job carries no job items; job_type must be an int).
* lua/stocks.lua (by_type covers CORPSEPIECE, TOTEM, AMMO;
  by_material excludes CORPSEPIECE; headline stocks carry no bone
  number).
* daemon.py TASK_DEFS (brew, cook, make_bed, make_barrel, gather,
  farm; no bone task).
* materials.py (the _WOOD_1 rule for nine carpenter jobs, nothing
  for bone).
* assembler.py TokenAccountant (count at length divided by 3,
  TARGET 30000, WARNING 60000, COMPACTION 100000, NEVER 140000).
* tests/fixtures/observe-athelunol.json (AMMO 48 units in 6
  stacks, REMAINS 6, no CORPSEPIECE row).
* docs/STONEWORKING.md sections 4.1 and 4.2 (craftsdwarf placement
  affinity, the hardcoded-job gap, the manager fallback).
* docs/WOODWORKING.md sections 2.6 and 19 (25 wooden bolts per log,
  5 bone bolts per bone, the craftsdwarf build gap).
* docs/HUNTING.md (the bolt loop, the 5 per bone rule, the
  craftsdwarf's workshop as the bolt shop).
* docs/FISHING.md (shell supply, the shell mood reserve, cooking
  shelled creatures loses the shell, repeating decorate orders).
* docs/TRADING.md section 2.5 (elf refusal of bone, shell, horn,
  ivory, hair, chitin, scales, leather, and the rest).
* docs/MILITARY.md (bone armor as a stopgap, bolt stockpile split,
  the bowyer-workshop bolt error flagged in section 12).
* docs/STOCKPILES.md (usable-refuse stockpile near the butcher and
  bone carver, not in traffic; no settings write anywhere in the
  harness).
