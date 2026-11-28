# Leatherworking

Design record for the leatherworking system in the Urist harness:
tanning hides into leather at a tanner's shop, making leather goods
at a leather works, and turning hides into parchment for the library.
This is the plan. Implementation follows it phase by phase, each phase
verified live against the real game before it counts as done. Anything
not verified against the wiki, the 0.47.05 raws, the code, or the live
game is marked UNVERIFIED.

Boundary: docs/CLOTHING.md owns the clothing chain, including the
leather clothing versus leather armor split as it affects what dwarves
wear, the three-slot coverage check, and the hospital reserve. This
doc owns tanning and leather production, and it does not duplicate the
clothing content. Where this doc advances a question CLOTHING.md left
open, it says so explicitly in section 18. Where the two docs could
disagree, section 18 names the resolution. The leather chain is part
of the meat industry, not the clothing industry (Leather): the hide
arrives from the butcher, and this doc starts there.

Related docs: docs/CLOTHING.md (leather clothing, coverage, hospital
reserve, the claim order this doc adopts), docs/ANIMAL_HUSBANDRY.md
(butchering, hides as a byproduct, slaughter rules), docs/MILITARY.md
(leather armor, quivers, backpacks, the uniform this doc supplies),
docs/TRADING.md (leather as a trade good, the elf refusal, the
per-dwarf floor), docs/STOCKPILES.md (leather and hide stockpiles),
docs/LABOR.md (labor floors, none yet for tanning or leatherworking),
docs/HARNESS_ROLE.md (snapshot as index, opportunities rules),
docs/SITE_SELECTION.md (scored placement).

## 1. Purpose

Leatherworking answers six questions every tick, from fresh collects,
so the agent never has to:

1. How many raw hides are waiting, how many are rotting, and how much
   leather do we have, by animal?
2. Is the tanner keeping up with the butcher, or are hides rotting
   faster than they are tanned?
3. What leather goods do we still need: quivers, backpacks,
   waterskins, armor, bags, clothing?
4. What must leather never be spent on, and in what order do the
   claimants get it?
5. When is a hide worth parchment instead of leather, and what is
   stopping the parchment chain?
6. What leather can be sold, and what must be kept?

If the harness cannot answer one of those from real state, it says
so instead of inventing an answer.

The headline finding of the research behind this doc is that the
fort is blind to leather, not short of it. The stocks collect counts
leather in its raw by-type table and then never surfaces it: no
headline count, no material breakdown, no hide count, no workshop
that can tan or work it. The first leather job the harness ever
queues will be the first time any of this is visible. The bottleneck
is observation and actuation, not supply: one butchered dog is one
hide is one leather, and the fort already slaughters animals.

## 2. How leatherworking works in DF 0.47.05

All of this section is from the wiki pages listed in Sources, checked
against the 0.47.05 raws shipped with the game where the wiki and the
version can disagree. The local wiki index is a current-wiki export:
some pages carry v50 markers, so a wiki claim is not a 0.47.05 claim
until the raws or a live probe agrees with it. Section 2.4 is the
authoritative split for this version, taken from the raws, not the
wiki. Where the wiki list and the raws disagree, the raws win and
the difference is named.

### 2.1 Skins and hides

Skin is a tissue layer common to most creatures (Skin). Most mundane
creatures have raw hide, which displays in-game as skin. This is the
only type that can be tanned into leather. Arthropods have chitin and
reptiles and fish have scales; neither can be tanned.

Each butchering job produces a single skin, but tanning a hide may
produce multiple pieces of leather, depending on the creature's size
(Skin). Smaller animals never produce a hide: there is no kea or rat
leather (Leather). Very small animals yield only a skull
(docs/ANIMAL_HUSBANDRY.md, section 7.2). A dog, for reference, yields
6 to 13 meat, 6 to 13 fat, 4 to 11 bones, one skull, and a raw hide
(Animal husbandry, section 7.2).

The raw definition is in the raws, not in a creature file:
`third_party/df_47_05/raw/objects/material_template_default.txt`
defines the SKIN_TEMPLATE with two reaction products,
`[MATERIAL_REACTION_PRODUCT:TAN_MAT:LOCAL_CREATURE_MAT:LEATHER]`
and `[MATERIAL_REACTION_PRODUCT:PARCHMENT_MAT:LOCAL_CREATURE_MAT:PARCHMENT]`,
plus `[ROTS]` and `[IMPLIES_ANIMAL_KILL]`. Every creature whose skin
uses that template can be tanned. The template is the authority; no
creature file lists TAN_MAT individually (a grep across all
`creature_*.txt` files finds zero TAN_MAT lines, because the token
lives in the template).

Skins, fresh and rotten, are stored in a refuse stockpile under the
names "fresh raw hide" and "rotten raw hide" (Skin). Rotten hides
cannot be tanned (Leather). A hide left rotting is leather lost, so
the tanner must run promptly after butchering. How long a fresh hide
lasts before it rots is UNVERIFIED (section 17, open question 13);
phase 4 measures it from the fort's own hides.

One wiki detail with live consequences: tanners can turn a skin from
a severed part of an animal into the full-size leather (Leather).
A limb torn off in combat is not a partial hide. Whether that holds
in 0.47.05 is UNVERIFIED (section 17, open question 8); it matters
because combat butchery yields severed parts, not whole animals.

### 2.2 Tanning is a reaction, not a job type

The tanner's shop turns a hide into leather through the TAN_A_HIDE
reaction (`third_party/df_47_05/raw/objects/reaction_other.txt`,
lines 5 to 15):

```
[REACTION:TAN_A_HIDE]
    [NAME:tan a hide]
    [BUILDING:TANNER:CUSTOM_T]
    [REAGENT:A:1:NONE:NONE:NONE:NONE][USE_BODY_COMPONENT][UNROTTEN]
        [HAS_MATERIAL_REACTION_PRODUCT:TAN_MAT]
    [PRODUCT:100:1:SKIN_TANNED:NONE:GET_MATERIAL_FROM_REAGENT:A:TAN_MAT]
    [SKILL:TANNER]
    [AUTOMATIC]
```

Three facts follow from the raw. First, the reagent must be
unrotten: the `[UNROTTEN]` token is the game enforcing what the wiki
says. Second, the product is one SKIN_TANNED item per reaction run
at 100 percent chance, with the material taken from the hide's
creature, so dog hide becomes dog leather and cow hide becomes cow
leather. The yield table in section 3.3 (one hide becomes one or
more leather) is therefore not in this reaction: it comes from the
hide's size, and the mechanism by which a large hide becomes 2 or 7
leather is UNVERIFIED (section 17, open question 5). Third, the
reaction carries `[AUTOMATIC]`, which is the raw side of the
auto-tan behavior in section 3.2.

There is no TanHide entry in the live job enum
(`tests/fixtures/runtime-enums-0.47.05-r8.json`, 241 job types). The
harness queues tanning the same way it queues brewing: job type 211
(CustomReaction) plus the reaction name TAN_A_HIDE. The live
reaction index for TAN_A_HIDE is UNVERIFIED (section 17, open
question 1); the brew reaction was probed live as index 44, and the
tan reaction needs the same probe. The reaction catalog comment in
`actions.py` already documents the pattern: reactions are found by
name through `df.reaction.find`, and the index is a live fact, not a
raw-file fact. TAN_A_HIDE is the first reaction in
`reaction_other.txt`, which says nothing about its live index.

### 2.3 The leather works and what it makes

The leather works (b-o-l-l) is built from any building material by a
dwarf with the Leatherworking labor, and it uses leather (Leather
works). Its goods, from the wiki page, are: leather clothing,
leather armor, leather shield, leather quiver, leather bag, leather
backpack, leather waterskin, leather images (decoration), and leather
instrument pieces (marked v0.42.01). Crafts made from leather are
made at a craftsdwarf's workshop, not here (Leather works).

The leatherworker skill page lists the tasks the same way: Make
Leather Crafts, Make Leather Armor, Make Leather clothes, Construct
Leather Bag, Make Leather Waterskin, Make Leather Backpack, Make
Leather Quiver, Sew Leather Image (Leatherworker). The skill is used
at the leather works and, for crafts, at the craftsdwarf's workshop.
The labor is LEATHER and the skill is LEATHERWORK in the live enum;
the labor is not called LEATHERWORKER (CLOTHING.md, section 6.1).

Every clothing job consumes one whole unit of cloth or leather,
regardless of the size of the piece produced (Clothing). The wiki
states it for clothing jobs generally, and the Leather page states
it for leather armor specifically: leather armor is made in a
leather works and requires one unit of any leather. One leather per
job is therefore the rule for every good in the catalog in section
3.4, including armor with a MATERIAL_SIZE of 6 in the raws. The
MATERIAL_SIZE tokens in the item raws (6 for leather armor, 5 for
leggings, 2 for high boots and helms, 1 for shoes, caps, and low
boots) do not change the consumption: the game charges one whole
unit per job either way. What MATERIAL_SIZE governs instead is
UNVERIFIED (section 17, open question 18); it does not govern how
much leather a job eats, and the harness never plans on any other
number.

To create differently sized clothing or armor, the job details are
set after the job is issued, specifying the species (Leather works).
Whether the harness can specify size on a queued job is UNVERIFIED
(section 17, open question 16); it is the same question CLOTHING.md
asks as its open question 2, and the two docs share the probe.

### 2.4 Leather clothing versus leather armor, from the raws

This section partially resolves CLOTHING.md open question 6, which
asked exactly which leather works menu items are civilian clothing
and which are armor in 0.47.05. The raws settle the split for every
item that carries an ARMORLEVEL token, and CLOTHING.md section 2.1
already states the rule: clothes are the soft items with no
ARMORLEVEL token (armor level 0); armor is ARMORLEVEL 1 and above.
Civilians will not pick up and wear armor, armor does not wear out
over time (but can suffer wear in combat), and armor belongs in armor
stockpiles, not finished goods stockpiles (Clothing). The coverage
check in CLOTHING.md counts armor level 0 items only, so a leather
helm on a dwarf does not cover any of the three slots, and a leather
cap does not either, because headwear is not a coverage slot at all.

Verified against the 0.47.05 raws in the repo:

**Armor (ARMORLEVEL 1 and above), made at the leather works:**

| Item | Raw | ARMORLEVEL | Leather per job |
| --- | --- | --- | --- |
| Leather armor | ITEM_ARMOR_LEATHER | 1 | 1 |
| Leggings | ITEM_PANTS_LEGGINGS | 1 | 1 |
| High boots | ITEM_SHOES_BOOTS | 1 | 1 |
| Low boots | ITEM_SHOES_BOOTS_LOW | 1 | 1 |
| Helm | ITEM_HELM_HELM | 1 | 1 |

**Clothing (no ARMORLEVEL token), made at the leather works:**

| Item | Raw | Leather per job |
| --- | --- | --- |
| Trousers | ITEM_PANTS_PANTS | 1 |
| Skirt, short skirt, long skirt | ITEM_PANTS_SKIRT, SKIRT_SHORT, SKIRT_LONG | 1 |
| Loincloth, thong, braies | ITEM_PANTS_LOINCLOTH, THONG, BRAIES | 1 |
| Shoes | ITEM_SHOES_SHOES | 1 |
| Gloves, mittens | ITEM_GLOVES_GLOVES, MITTENS | 1 |
| Cap, hood | ITEM_HELM_CAP, HOOD | 1 |

**Not leather-makeable, from the same raws:**

| Item | Why not |
| --- | --- |
| Gauntlets | ARMORLEVEL 2, no LEATHER token in item_gloves.txt |
| Greaves | ARMORLEVEL 3, metal only in item_pants.txt |
| Socks | No LEATHER token in item_shoes.txt (woven thread only) |
| Sandals | LEATHER token present, but dwarves cannot produce sandals at all (CLOTHING.md, section 2.5) |

Two gaps remain, and they stay open. First, the raws say which items
can be leather, not which items the leather works menu offers: the
menu enumeration is still a live probe (section 17, open question 4).
A leather-capable item the menu never offers is not producible, and
the harness must not claim it. Second, shields carry no material
tokens at all in `item_shield.txt`: ITEM_SHIELD_SHIELD (ARMORLEVEL 2)
and ITEM_SHIELD_BUCKLER (ARMORLEVEL 1) list BLOCKCHANCE, UPSTEP, and
MATERIAL_SIZE, and no material. Leather shields exist (Leather), so
the material choice for shields is governed somewhere other than the
item raw, and how MakeShield picks leather is UNVERIFIED (section 17,
open question 10).

The mask, turban, veil, and headscarf entries in item_helm.txt all
carry a LEATHER token with no ARMORLEVEL, so they are leather-capable
clothing in the raws. Whether the leather works menu offers them is
part of the same menu probe. The chausse entry in item_shoes.txt was
not confirmed either way from the raws read for this doc; it is
UNVERIFIED (section 17, open question 4).

### 2.5 Parchment

Parchment is the second tanner product: skin plus milk of lime
(Tanner's shop). The reaction is MAKE_PARCHMENT in
`reaction_other.txt` (lines 360 to 371):

```
[REACTION:MAKE_PARCHMENT]
    [NAME:make parchment]
    [BUILDING:TANNER:CUSTOM_P]
    [REAGENT:A:1:NONE:NONE:NONE:NONE][USE_BODY_COMPONENT][UNROTTEN]
        [HAS_MATERIAL_REACTION_PRODUCT:PARCHMENT_MAT]
    [REAGENT:milk of lime:150:LIQUID_MISC:NONE:INORGANIC:MILK_OF_LIME]
    [REAGENT:lime container:1:NONE:NONE:NONE:NONE]
        [CONTAINS:milk of lime]
        [PRESERVE_REAGENT]
        [DOES_NOT_DETERMINE_PRODUCT_AMOUNT]
    [PRODUCT:100:1:SHEET:NONE:GET_MATERIAL_FROM_REAGENT:A:PARCHMENT_MAT]
    [SKILL:TANNER]
```

One unrotten hide plus 150 units of milk of lime makes one sheet of
parchment, and the container holding the milk of lime is preserved.
Milk of lime comes from an ashery: any dwarf with the lye maker labor
converts one bag of quicklime into one unit of milk of lime, and an
empty bucket must be available (Milk of lime). Quicklime comes from a
kiln burning calcium carbonate stone (Paper industry). The full chain
is therefore kiln, ashery, bucket, tanner's shop, and the gate is the
hide: CLOTHING.md section 4.2 already states the rule this doc owns,
never spend a hide on parchment while the fort is short of leather,
and section 6.3 restates it as a refusal with numbers.

Parchment is a library input, not a clothing input. Sheets become
scrolls at a craftsdwarf's workshop (MAKE_SCROLL in
`reaction_other.txt`: one sheet plus scroll rollers) and books for
the library. The parchment work is section 12; it is deliberately
the last production phase, not the first.

### 2.6 Dyeing leather: almost certainly absent in 0.47.05

The v50 wiki says leather can be dyed. The Dyer's shop page lists
thread, cloth, and leather under Materials Used, and says the shop
is used to dye thread, cloth, and leather. The Dye page says dyes
can be applied to woven cloth, raw thread, or leather, with a
version marker attached to leather: "or leather v52.03". That
marker is the tell: leather dyeing was added in v52.03, which is
after 0.47.05. In 0.47.05 the live job enum holds DyeThread and
DyeCloth and no DyeLeather, and no DyeLeather-shaped job exists in
the 241 job types. The conclusion is that leather cannot be dyed in
0.47.05, and the dyer's shop page is describing the current game,
not this one. The conclusion is UNVERIFIED until the dyer's menu is
enumerated live (section 17, open question 3, phase 2), because a
version marker on one page is evidence, not proof. Until the probe
answers it, the harness never queues a leather dye job, never plans
dyed leather trade goods, and never counts dye as a leather input.
If the probe finds a leather dye route after all, this section is
corrected with the live evidence, not argued with.

### 2.7 Value

Leather's base value is 5 (Leather, infobox), from MATERIAL_VALUE 1
in the LEATHER_TEMPLATE. The value of the leather depends on the
critter it comes from: leather made from the skins of rare or
dangerous animals can be quite valuable (Leather). The mechanism by
which a creature raises its leather's value is UNVERIFIED (section
17, open question 18); the doc uses the ordering, rare and dangerous
first for trade, not a number. A finished leather good's value is
the item value times material times quality, the same formula as
cloth goods (CLOTHING.md, section 3.5). Bags are worth 10 and flasks
are worth 10 (Bag; Flask), both before quality. Leather is also a
strange mood material: StrangeMoodTanner exists in the live job enum,
so a moody tanner can claim a tanner's shop and halt production
(section 19).

### 2.8 The sentient leather taboo

Dwarves will not claim and wear clothes made from the leather of
sapient creatures as part of their civilian attire (Leather). The
taboo comes from dwarven ethics, which forbid the butchering of
sentient creatures. Craftsdwarves will fashion the leather of such
creatures into clothing, and such clothes will be collected and
traded normally. Dwarves will wear clothes made of the leather of
sentients if ordered to do so as part of a military uniform.

In fortress mode sentient creatures cannot be butchered under normal
circumstances (Leather, note 1), so the fort should never hold
sentient leather it made itself. It can hold sentient leather from
trade, and the harness must handle that case: leather goods made
from it are trade goods, never civilian clothing, and the coverage
check must never count on a sentient-leather garment being worn.
Whether the stocks read can identify a leather's source creature is
part of phase 1: the material breakdown carries the creature token,
so the read can flag it. How often traded sentient leather actually
arrives is UNVERIFIED (section 17, open question 9).

## 3. The chain in detail

### 3.1 Hide supply

Hides arrive three ways, in order of reliability:

1. **Butchering.** The fort's own animals, slaughtered by rule
   (docs/ANIMAL_HUSBANDRY.md, section 7.3): slaughter the surplus
   of a breeding line once adult, never the breeding pair, never a
   pet, never an animal the fort still needs alive for milk, wool,
   eggs, or war. The clothing system takes the hide as its input
   and never slaughters an animal for hide alone while the fort is
   short of meat (CLOTHING.md, section 4.1). The harness never
   slaughters for leather alone at any point: a hide is a byproduct
   of a meat decision, and the tanner works with what the butcher
   produces.
2. **Hunting.** Hunters return kills to the butcher, and the hide
   follows the same path. Hunting is erratic (Meat industry), and
   the harness never plans a leather floor on hunted hides.
3. **Trade.** Human and dwarven caravans sell leather, often in vast
   quantities (Meat industry). Buying up a caravan's leather is a
   cheap way to get the fort clothed quickly, and the meat industry
   page advises requesting every type of leather so the merchant
   brings a large quantity next year. Elves bring no leather
   (docs/TRADING.md). Trade is the only reliable way to get leather
   before the fort has a breeding herd, and it is the only way to
   get leather from animals the fort does not keep.

The supply the harness plans on is butchered hides plus traded
leather. Hunted hides are a bonus, never a plan.

### 3.2 Tanning

Tanning runs two ways. By default, the "Tan a hide" job is
automatically triggered after the game notices a skin within a
certain distance of the tanner's shop (Tanner's shop). The player
turns it off in standing orders ("Automate tannery" to "Do not
automate tannery"). If auto-tan is off, the manager can manually
queue "Tan a Hide" jobs, which is also useful if auto-tan ignores a
skin. The `[AUTOMATIC]` token on TAN_A_HIDE is the raw side of the
same behavior (section 2.2).

Three things are UNVERIFIED about the automation and need live
probes. First, the trigger distance: "within a certain distance" is
all the wiki says, and the number of tiles is not stated (section
17, open question 6). Second, whether the standing order is readable
and writable from Lua, and where the field lives (section 17, open
question 7; phase 14 probes it). Third, whether auto-tan fires on a
hide that the parchment plan has reserved: the game has no concept
of a reserved hide, so the harness must reserve by controlling
auto-tan itself, turning it off when a hide is earmarked for
parchment and tanning the rest by hand. Until the standing-order
probe answers, the harness assumes auto-tan is on by default and
plans parchment only from hides it can see are surplus after
tanning, never from hides still waiting.

The tanner's skill is TANNER, and the labor is TANNER. Whether skill
changes the yield or only the speed is UNVERIFIED (section 17, open
question 18). The butcher's skill only affects how long the job
takes, never how much comes out (Animal husbandry, section 7.1);
tanning may follow the same rule, but that is an analogy, not a
fact, and the doc does not assert it.

### 3.3 Yields

One butchered animal yields one raw hide, and the hide yields one or
more leather by animal size (Leather). The table is wiki-sourced and
UNVERIFIED live (section 17, open question 5); the tanner page's cow
figure carries a v50.01 marker, so it is the most suspect row, and
CLOTHING.md already flagged it as its open question 14. The
threshold the wiki gives is that more than one leather starts with
animals about the size of an adult mule, size about 150,000 cm3.

| Animal | Leather per adult hide |
| --- | --- |
| Rabbit | 0 |
| Cat, dog, goat, sheep, pig, alpaca, reindeer, llama, donkey | 1 |
| Mule, horse, cow, yak | 2 |
| Water buffalo | 2 to 3 |
| Elephant | 7 |
| Giant elephant | 10 |

The fort's own animals are the ones that matter: dogs, cats, sheep,
goats, pigs, cows, horses, donkeys, mules, llamas, alpacas. A dog
hide is 1 leather. A cow hide is 2 leather if the table holds. The
phase 4 counted batch tans one hide of each animal the fort actually
slaughters and records what comes out, and the table is corrected
from that batch, not from the wiki.

### 3.4 The leather goods catalog

Every good in this table costs one whole unit of leather per job
(section 2.3). The job type column is from the live runtime enum
(`tests/fixtures/runtime-enums-0.47.05-r8.json`). Where the job type
is missing, the table says so; a missing job type is a finding, not
an oversight.

| Good | Job type | Raw item | Armor level | Use | Owner |
| --- | --- | --- | --- | --- | --- |
| Leather armor | MakeArmor | ITEM_ARMOR_LEATHER | 1 | Militia armor | MILITARY.md |
| Leggings | MakePants | ITEM_PANTS_LEGGINGS | 1 | Militia armor | MILITARY.md |
| High boots | MakeShoes | ITEM_SHOES_BOOTS | 1 | Militia armor | MILITARY.md |
| Low boots | MakeShoes | ITEM_SHOES_BOOTS_LOW | 1 | Militia armor | MILITARY.md |
| Helm | MakeHelm | ITEM_HELM_HELM | 1 | Militia armor | MILITARY.md |
| Shield / buckler | MakeShield | ITEM_SHIELD_SHIELD / BUCKLER | 2 / 1 | Militia shield | MILITARY.md |
| Quiver | MakeQuiver | QUIVER | n/a | Holds bolts | MILITARY.md |
| Backpack | MakeBackpack | BACKPACK | n/a | Carries rations | MILITARY.md |
| Waterskin | MakeFlask | FLASK | n/a | Carries water and alcohol | MILITARY.md |
| Bag | UNVERIFIED, no MakeBag in enum | n/a | n/a | Holds seeds, powders | This doc, section 3.5 |
| Trousers, skirts, loincloth, braies, thong | MakePants | ITEM_PANTS_* | 0 | Civilian clothing | CLOTHING.md |
| Shoes | MakeShoes | ITEM_SHOES_SHOES | 0 | Civilian clothing | CLOTHING.md |
| Gloves, mittens | MakeGloves | ITEM_GLOVES_* | 0 | Civilian clothing | CLOTHING.md |
| Cap, hood | MakeHelm | ITEM_HELM_CAP, HOOD | 0 | Civilian clothing | CLOTHING.md |
| Leather image (decoration) | SewImage | n/a | n/a | Decoration | This doc, section 3.8 |
| Leather crafts | MakeCrafts | n/a | n/a | Trade | This doc, section 3.9 |
| Instrument pieces | UNVERIFIED, no job type in enum | n/a | n/a | Instruments | This doc, section 3.10 |

How the game picks which garment a MakeArmor, MakePants, MakeGloves,
MakeHelm, or MakeShoes job makes is UNVERIFIED. CLOTHING.md asks it
as its open question 1, and the working hypothesis there is that the
job carries the item subtype. The phase 2 probe in this doc is the
same probe, run at the leather works instead of the clothier: queue
one of each and read each job struct back. If a garment cannot be
chosen by subtype, the plan adapts and never claims otherwise.

### 3.5 Bags: the hidden dependency

Bags are the quiet reason leather matters before the military does.
A bag holds up to 100 seeds of the same type, as well as quarry bush
leaves and edible and inedible powders: flour, sugar, dye, gypsum
plaster, quicklime, and sand (Bag). Bags can be made at a clothier's
shop out of 1 plant, silk, or yarn cloth, or at a leather works out
of 1 leather. Without bags, one seed takes one tile, and dye powder
has nowhere to go at all: dye is stored as powder in bags, and a
barrel holds up to 60 dye bags (Dye).

Bags containing plant-derived items and powders are stored in Food
stockpiles, and cannot be prevented from being used there so long as
the items contained in the bag are permitted. Empty bags are stored
in Furniture stockpiles under Bags. A bag takes up 100 volume in
storage, empty or full, and 500 fit in a minecart (Bag).

The consequence is a chain the harness must see: no bags means seeds
sprawl across tiles, dye cannot be stockpiled, and flour has no
container. Cloth bags and leather bags substitute for each other,
and the claim order in section 6.3 spends leather on bags only when
cloth is short, because cloth is the cheaper bag material while the
fort is short of leather for quivers. The bag floor in section 6.2
is computed from the seed and powder counts, not guessed: bags
needed is the seed stacks plus powder stacks, divided by what one
bag holds, and the harness counts it from the fresh collect.

The job type that makes a leather bag is UNVERIFIED: there is no
MakeBag in the 241 live job types, and no bag reaction in the raw
reaction files. The leatherworker page lists "Construct Leather Bag"
as a task, so the job exists in the game; the harness does not know
its job type yet. Phase 2 hunts it by queueing a bag at the leather
works and reading the job struct back. Until then, the harness never
claims it can make a leather bag, and cloth bags carry the storage
need alone.

### 3.6 Waterskins, quivers, backpacks: the military three

These three are why leather is practically essential for a
well-rounded military (Leather). Leather is the only sensible option
for quivers and backpacks, the only alternative being adamantine.

* **Quiver.** Dwarves require a quiver to hold their ammo whenever
  engaging in any kind of shooting, so at least one quiver is needed
  for each hunter and each marksdwarf (Equipment). Crossbows require
  bolts and a quiver to fire, otherwise crossbow users will withdraw
  from combat (Crossbow). A marksdwarf without a quiver is not a
  marksdwarf; it is a dwarf holding a crossbow it cannot use. The
  quiver floor in section 6.2 is one per hunter plus one per
  marksdwarf, and a missing quiver is an attention item, not a
  planning note.
* **Backpack.** Backpacks allow dwarves to carry rations (Equipment).
  They matter for squads sent out on missions and for hunters, and
  they are the reason the claim order puts backpacks beside quivers
  rather than behind trade. The backpack floor is one per marksdwarf
  and one per hunter, to be tuned live from whether the military
  plan actually issues them.
* **Waterskin.** Leather flasks are called waterskins, glass ones are
  called vials (Equipment). Flasks allow dwarves to carry water and
  alcohol. A waterskin is made at a leather works out of leather,
  at a forge out of metal, or at a glass furnace out of glass
  (Flask). Leather is the early option. The waterskin floor is one
  per dwarf on active military duty, tuned live.

All three are MakeQuiver, MakeBackpack, and MakeFlask in the live
job enum, all exist, and all cost one leather. There is no job-type
gap here; the gap is that the harness has never queued any of them.

### 3.7 Shields

Leather shields are extremely light and are just as protective as
wooden or metal shields, thus useful for keeping forces mobile
(Leather). That is the whole case for leather shields: same
protection, less weight, faster dwarves. The shield job type is
MakeShield, which exists in the live enum. The material question is
open: `item_shield.txt` carries no material tokens at all, so the
raws do not say how MakeShield picks leather over wood or metal, and
the harness cannot claim to choose until the phase 2 probe queues a
shield at the leather works and reads back what material the job
took. The two shield items are ITEM_SHIELD_SHIELD (ARMORLEVEL 2,
BLOCKCHANCE 20) and ITEM_SHIELD_BUCKLER (ARMORLEVEL 1, BLOCKCHANCE
10). Which one MakeShield makes, and whether the harness can choose,
is part of the same probe.

### 3.8 Decoration: sew leather images

Decorating finished goods with leather is done at the leather works
(Leather works). The job type is SewImage, which exists in the live
enum. At a clothier's shop, cloth images can be sewn onto cloth and
leather items, notably including leather armor, bags, ropes, and
cloth and leather crafts, and that takes clothesmaking (Decoration).
Leather images are a value play, not a need: embroidering almost
always generates less value than making a second piece (CLOTHING.md,
section 3.5, for cloth; the same arithmetic holds for leather, and
the harness never decorates for value while any good on the floor in
section 6.2 is unmet). Decoration sits last in the claim order, and
the harness never queues SewImage before the fort is covered.

### 3.9 Leather crafts at the craftsdwarf's workshop

Crafts made from leather are made at a craftsdwarf's workshop, not
at the leather works (Leather works; Leather). The job type is
MakeCrafts, which exists in the live enum, and the skill is
leatherworking (Leatherworker). Leather crafts are trade goods, and
they are the last claim on leather in section 6.3: surplus only,
after quivers, clothing, bags, armor, and waterskins. The craftsdwarf
workshop is not in WORKSHOP_CATALOG either, so this claim waits on
the same catalog work as the leather works, and on the trade phase.
Leather crafts are also the one leather good elves refuse outright
with everything else animal-derived (docs/TRADING.md), so the trade
phase filters them through the elf rules before any offer.

### 3.10 Instruments

The Leather works page lists leather instruments and leather
instrument pieces as goods, both marked v0.42.01. There is no
instrument-making job type in the live enum: no MakeInstrument, and
the only near matches are MakeToy and MakeCrafts. Whether leather
instrument pieces are makeable in 0.47.05, and under which job type,
is UNVERIFIED (section 17, open question 11). Instruments are a
tavern need, not a survival need, and the harness never plans leather
for them until the probe answers. If the probe finds no route, this
subsection is corrected to say instruments are not makeable from
leather in this version, and the doc stops listing them as goods.

## 4. What the fort needs and when

Leather is claimed by five systems, and the claim order is the whole
design. CLOTHING.md section 7.4 already states the order for three
of them: military quivers and backpacks first, civilian clothing
second, trade crafts last from surplus only. This doc adopts that
order unchanged and extends it to the two claimants CLOTHING.md
does not cover, bags and parchment. The full order, with the owner
of each claim:

1. **Military quivers and backpacks.** A marksdwarf without a quiver
   cannot fight (CLOTHING.md, section 7.4). Owned by MILITARY.md.
2. **Civilian clothing coverings.** The three slots, owned by
   CLOTHING.md. A dwarf uncovered while leather sits in the
   stockpile is a planning failure the harness names with numbers.
3. **Bags for seed, dye, and flour storage.** Section 3.5. Owned by
   this doc, because no other doc counts bags. Cloth bags substitute
   where cloth is plentiful; leather pays only the shortfall.
4. **Leather armor and shields for the uniform.** Owned by
   MILITARY.md; this doc supplies the count. Leather armor is the
   starter tier, replaced by metal as the forge comes up.
5. **Waterskins.** One per dwarf on active duty. Owned by MILITARY.md.
6. **Trade goods.** Leather crafts and surplus leather goods, from
   surplus only, filtered through the elf rules. Owned by TRADING.md.
7. **Parchment.** Only from surplus hides when leather is above the
   floor in section 6.2. Owned by this doc, section 12.
8. **Decoration.** SewImage, last, never before the fort is covered.
   Owned by this doc.

The order is a priority, not a queue: the harness works the highest
unmet claim first each tick, and says which claim it is working and
which claims are still waiting. A fort that makes leather crafts
while a marksdwarf has no quiver has the order backwards, and the
snapshot must show that, not hide it.

## 5. What the harness knows today

Verified against the repo on 2026-11-27. Everything in this section
was read from the code, not remembered. The daemon and the game are
down at the time of writing (VM replacement about 19:37 PT,
2026-11-27, recovery running separately), so no live value in this
section was read from the game. Any live value the doc cites from an
earlier run is named with its date, and anything not read live is
marked UNVERIFIED.

### 5.1 What exists and works

* **Leather is counted, but never surfaced.** `lua/stocks.lua`
  counts every IN_PLAY item type in its `by_type` table, which
  includes SKIN_TANNED, FLASK, BACKPACK, QUIVER, and SHEET. The
  material breakdown in `add_mat` runs only for DRINK, FOOD, MEAT,
  FISH, PLANT, SEEDS, BAR, WOOD, CLOTH, and THREAD, so leather has
  no by-material breakdown, and there is no `leather_units`
  headline. The count exists in the raw collect and dies there.
* **The snapshot does not render leather.** `assembler.py`
  `_stocks` renders drink, food, wood, stone, brewable plants,
  empty barrels, and food stacks only. Leather, hides, and
  parchment never appear in the per-tick snapshot text. The agent
  cannot see leather at all without a query, and no query route
  for it exists.
* **Workshop listing.** `lua/buildings.lua` reports the workshop
  subtype from `df.workshop_type`, so a tanner's shop or leather
  works that exists will appear in the Buildings section. No
  leather workshop exists in the fort today: the 2026-11-27 M1 log
  reads "Carpenters #7 (built), Still: none", and no tanner or
  leather works is named (CLOTHING.md, section 6.1).
* **The build path accepts the subtypes.** `lua/act_build.lua`
  takes a subtype name and resolves it through
  `df.workshop_type[subtype]`, erroring on an unknown name. The
  live workshop enum holds Tanners, Leatherworks, and Ashery, so
  the build call will accept them the moment the catalog lists
  them. Nothing in the build path blocks leather workshops.
* **The queue path accepts the reaction.** `actions.py`
  `queue_job` takes a job type number and a reaction name, and job
  type 211 is CustomReaction. The brew reaction was probed live as
  index 44, and the comment above JOB_SPECS documents the pattern.
  Tanning needs the same shape with reaction name TAN_A_HIDE; the
  only missing piece is the live reaction index, which is a probe,
  not a code change.
* **Labor names.** The live labor enum holds LEATHER, TANNER, and
  LYE_MAKING, and the live skill enum holds LEATHERWORK, TANNER,
  and LYE_MAKING. `labor_toggle` can enable any of them, and
  `units.lua` reads labors and skills per citizen, so the labor
  half of the chain is already actuatable.
* **Job types.** The live job enum holds MakeArmor, MakeHelm,
  MakePants, MakeGloves, MakeShoes, MakeShield, MakeFlask,
  MakeBackpack, MakeQuiver, SewImage, MakeCrafts, DyeThread, and
  DyeCloth. The raw job types for the leather goods exist in the
  game; the harness has not wired any of them up. It also holds
  StrangeMoodTanner, so a moody tanner is a real job type the
  harness may one day see.
* **Catalog introspection.** `catalog.py` builds each action's
  plain-words `about` and `needs` text from the action table, so
  new leather actions get catalog entries automatically and cannot
  drift from the code.
* **Hide supply.** docs/ANIMAL_HUSBANDRY.md already covers
  slaughter and butchering: one hide per animal large enough, a
  dog yields one raw hide, the butcher's skill affects time only.
  The leather system takes hides as its input and does not
  re-decide slaughter.
* **Stockpile rows exist.** docs/STOCKPILES.md has a Leather row
  (Bins max, tanned leather, near tanner and leather works), a
  Refuse usable row that takes hides, and a Finished goods row
  that puts waterskins in their own stockpile. A bin holds 45
  leather (Stockpiles, section on bin capacity). The stockpile
  plan already knows where leather goes; the harness has not built
  any of it.

### 5.2 What is missing (verified gaps)

* **No leather workshop can be built.** `WORKSHOP_CATALOG` in
  `actions.py` holds exactly four workshops: carpenter, mason,
  still, kitchen. There is no tanner's shop, leather works,
  ashery, or craftsdwarf's workshop. The harness cannot build any
  workshop in the leather chain.
* **No leather job can be queued.** `JOB_SPECS` holds brew,
  brew_fruit, cook, and eight carpenter furniture jobs. There is
  no tan-hide, make-quiver, make-backpack, make-flask,
  make-leather-armor, make-shield, sew-image, or make-craft job.
  `queue_job` cannot queue any job in the chain.
* **No leather task exists.** `TASK_DEFS` in `daemon.py` holds
  exactly six composed tasks (brew, cook, make_bed, make_barrel,
  gather, farm). None is leather. The multi-step chain (tan, then
  make) is inexpressible in the current task framework; that
  framework gap is a P0 in gap review 3, and the leather work
  waits on it rather than working around it, the same way the
  clothing work does.
* **No leather, hide, or parchment counts.** `stocks.lua` has no
  `leather_units`, no `hide_units`, no `parchment_units`, and no
  material breakdown for SKIN_TANNED. The harness cannot currently
  answer "how much leather do we have", "how many hides are
  waiting", "how much of it is dog leather", or "how much
  parchment".
* **No quiver, backpack, or waterskin coverage read.** `units.lua`
  collects needs, skills, labors, wounds, relations, and job per
  citizen, but no inventory. The only inventory reads in the repo
  are `probe_picks.lua` and `equip_pick.lua`, both pick-specific.
  The harness cannot currently answer "which marksdwarf has no
  quiver" or "who has no waterskin".
* **No planner coverage.** `planner.py` has no leather thresholds
  and no leather decisions. Nothing queues a quiver, nothing
  watches hides rot, nothing names a tanner-less fort.
* **No attention kinds.** `attention.py` has no leather kinds: no
  rotting hide, no hide without a tanner, no quiver shortage, no
  empty leather stock. A hide rotting beside the butcher is
  invisible to attention today.
* **No briefing.** `briefings.py` has no leather briefing kind.
  Leather appears in guidance only as a trade-floor number in
  docs/TRADING.md.
* **No labor floors.** docs/LABOR.md sets floors for brewer,
  planter, cook, miner, woodcutter, carpenter, mason, haulers, and
  medical, but none for tanner, leatherworker, or lye maker. The
  labor system cannot cover a labor it has no floor for.
* **No manager orders for leather.** `manager_order_create`
  exists, but no leather order is defined, and the reaction and
  job shapes the orders would need are the same UNVERIFIED items
  in section 17.
* **Current fort leather state unknown.** The M1 log from
  2026-11-27 (`logs/m1-20261127-073557.jsonl`) contains no
  SKIN_TANNED mention at all, so the fort's leather and hide stock
  on that date is unknown, not zero. The game is down while this
  doc is written, so the first live leather count comes from the
  first collect after recovery, and this doc does not invent one.

## 6. The leather floor and production targets

### 6.1 The floor

The leather floor is computed from the fresh citizen and military
counts every time, so it moves when migrants arrive or squads form:

* **Quivers:** 1 per hunter plus 1 per marksdwarf, plus 1 spare.
* **Backpacks:** 1 per marksdwarf plus 1 per hunter, plus 1 spare.
* **Waterskins:** 1 per dwarf on active military duty, plus 1 spare.
* **Leather armor sets:** per the military uniform (docs/MILITARY.md),
  1 armor, 1 leggings, 1 helm, 1 pair of boots per militia dwarf in
  the leather tier, until the forge replaces the tier with metal.
* **Shields:** 1 leather shield or buckler per militia dwarf without
  a wooden or metal shield.
* **Bags:** enough bags to hold the seed stacks plus the powder
  stacks (dye, flour, sugar, gypsum plaster, quicklime, sand) on
  hand, minus the cloth bags on hand. One bag holds 100 seeds of
  one type, and one bag holds one powder stack (Bag; Dye).
* **Civilian leather clothing:** per the clothing floor
  (CLOTHING.md, section 7.1), counted in leather only where the
  garment is leather. Cloth garments do not draw on this floor.
* **Trade floor:** never sell below 5 pieces of cloth or leather
  per dwarf (docs/TRADING.md). The floor counts cloth and leather
  together, not each: 7 dwarves means 35 pieces of cloth or
  leather held back, and leather sold below that line is a refusal
  with the numbers named.
* **Parchment floor:** 0 hides reserved for parchment until leather
  is above every floor above. Parchment is made from surplus hides
  only, never from the last hide.

The floor is a target, not a tripwire: the harness works toward it
every season, and treats anything below it as a standing need, not
an emergency. A marksdwarf without a quiver is the emergency, and
it is an attention item, not a floor breach. A hide rotting while
the tanner is idle is the other emergency.

### 6.2 How many hides per season

Leather is consumed by making, not by wear: leather armor does not
wear out over time, and quivers, backpacks, and waterskins have no
wear rate the harness has verified (section 17, open question 14).
Leather clothing wears like cloth clothing and is replaced on the
clothing cycle (CLOTHING.md, section 5.3). The production target
follows from the floor, not from a calendar:

1. Quivers, backpacks, waterskins, armor, and shields needed, minus
   those on hand and in use, equals the goods shortfall.
2. Goods shortfall, in leather units (one per job), minus leather on
   hand, equals the leather to tan.
3. Leather to tan, divided by the yield per hide from the counted
   batch (section 3.3), equals the hides to tan.
4. Hides to tan, minus hides on hand, equals the hides to buy or
   butcher for. The harness never slaughters for hides alone; a
   shortfall here is filled by trade, or it waits for the next
   slaughter the meat plan already scheduled.

Each step names its input, so the agent sees "need 1 quiver: 0
leather on hand, 2 hides un-tanned, tanner idle" instead of "need
leather".

### 6.3 The claim order, with numbers

Section 4 gives the order. This section makes it computable. When
leather arrives, whether by tanning or by trade, the harness spends
it in this order, and the snapshot says where the spending stopped:

1. Quivers and backpacks to the floor in section 6.1.
2. Civilian leather clothing to the clothing floor.
3. Bags to the bag floor, leather paying only the shortfall after
   cloth bags.
4. Leather armor and shields to the uniform.
5. Waterskins to the duty floor.
6. Trade goods, from surplus only, never below the 5-per-dwarf
   floor.
7. Parchment, from surplus hides only, never from the last hide.
8. Decoration, last, never before the fort is covered.

A claim that cannot be met names its blocker: "quiver shortfall 1:
0 leather, 2 hides, no tanner" is three different problems with
three different fixes, and the harness must not collapse them into
one.

## 7. How the harness knows

### 7.1 The stocks read

The observation step extends the stocks collect the same way the
clothing work extends it (CLOTHING.md, phase 1), and the two
extensions land together rather than as two passes over the same
items:

* **Leather headline:** `leather_units` from SKIN_TANNED items in
  IN_PLAY, trader-held excluded the same way `stocks.lua` already
  excludes trader goods. A caravan's leather is not the fort's
  leather.
* **Leather by material:** the `add_mat` breakdown extended to
  SKIN_TANNED, so the read gives dog leather 4, cow leather 2,
  and the rest by creature token. The creature token is what flags
  sentient leather (section 2.8).
* **Hide headline:** `hide_units` from fresh raw hides in IN_PLAY,
  split fresh versus rotten. Rotten hides are counted separately
  and never counted toward the tannable supply: a rotten hide is
  leather already lost, and counting it as supply is a lie.
* **Parchment headline:** `parchment_units` from SHEET items in
  IN_PLAY, plus milk of lime on hand for the chain status.
* **Goods on hand:** quivers, backpacks, waterskins (FLASK),
  leather armor, leggings, boots, helms, shields, and bags, from
  the `by_type` table that already counts them. No new walk is
  needed for the counts; the walk is needed for who holds them.

The read is cheap: it is the same IN_PLAY loop `stocks.lua` already
runs, with three more item types in the breakdown. What is
UNVERIFIED is whether the hide count needs a separate pass, because
hides are body-component items and may not sit in IN_PLAY the way
finished goods do (section 17, open question 19). Phase 1 proves
the read live: tan one hide, watch the hide count fall and the
leather count rise by the yield.

### 7.2 The equipment read

Beside stocks, the harness needs to know who holds a quiver, a
backpack, and a waterskin. That is a per-citizen inventory walk,
built on the pattern `probe_picks.lua` already proves: walking
`u.inventory` and reading each item's type, subtype, and material.
The walk is shared with the clothing coverage read (CLOTHING.md,
section 8.1): one walk per citizen, two consumers, not two walks.
What is UNVERIFIED is the cost of the walk at 50 dwarves and whether
an equipped quiver reads the same way as a stored one (section 17,
open question 19). Phase 1 measures both live.

The computation, per dwarf, from that read:

* **Quivered:** a hunter or marksdwarf holding a quiver. Missing is
  an attention item (section 13.4).
* **Packed:** a marksdwarf or hunter holding a backpack. Missing is
  a planning need, not an attention item, until the military plan
  says the squad is deploying.
* **Watered:** a dwarf on active duty holding a waterskin. Missing
  is a planning need.
* **Armored in leather:** a militia dwarf wearing leather armor,
  leggings, helm, and boots. This is the military plan's read; this
  doc supplies the counts, MILITARY.md owns the uniform check.

Civilians are excluded from the quiver and backpack read: a civilian
with no quiver is correct, not a problem. The read covers hunters,
marksdwarves, and militia only, and the snapshot names the role with
the gap, never just a count.

### 7.3 The chain status

Beside stocks and equipment, the harness computes the chain status
from the fresh collect: hides on hand (fresh versus rotten), leather
on hand by material, parchment and milk of lime on hand, goods on
hand by kind, and which workshops exist with their job counts. The
status names the bottleneck in one line: "2 hides un-tanned, no
tanner" or "6 leather, no leather works" or "1 quiver short, 0
leather, 0 hides". The bottleneck is the next job the planner
queues, and the snapshot carries it every tick.

## 8. Workshops and layout

Layout is scored placement (docs/SITE_SELECTION.md), with
leather-specific factors on top of the shared threat, cover, and
traffic factors:

* **The butcher link.** The tanner's shop sits beside the butcher,
  so hides go from shop to shop with no hauling. The auto-tan
  trigger is distance-based (section 3.2), so a tanner far from
  the butcher is a tanner that never fires. This is the single
  most load-bearing placement fact in the doc: tanner beside
  butcher, or hides rot.
* **The leather cluster.** Leather works beside the tanner, so
  leather goes from shop to shop. The leather stockpile sits
  between them, bins max, and the refuse stockpile for rotting
  hides sits outside the cluster, behind an airlock or outside,
  never in the traffic flow (docs/STOCKPILES.md, section 8).
* **The ashery link.** The ashery sits with the kiln and the wood
  furnace, not with the tanner: its inputs are ash and quicklime,
  and its output (milk of lime) travels in a bucket to the tanner
  only when parchment is made. Parchment is rare; the ashery does
  not need to live beside the tanner.
* **The military link.** The leather works sits within a short walk
  of the barracks, because quivers, backpacks, and armor go from
  the shop to the squad. A leather works at the far end of the
  fort pays the hauling cost on every uniform piece.
* **The depot link.** The trade leather stockpile sits near the
  depot, fed from the bulk leather stockpile, so traded leather
  arrives beside the shop that uses it and surplus leather leaves
  beside the depot that sells it.

Build requirements, from the wiki workshop pages and the live enum:

* **Tanner's shop** (b-o-f-t): any building material, built by a
  dwarf with the Tanning labor. Uses a raw hide, and milk of lime
  for parchment.
* **Leather works** (b-o-l-l): any building material, built by a
  dwarf with the Leatherworking labor. Uses leather.
* **Ashery** (b-o-u-a or b-o-f-a by menu): any building material,
  built by a dwarf with the lye making labor. Uses ash, lye,
  quicklime, and an empty bucket. The ashery shortcut is
  UNVERIFIED from the wiki pages read for this doc (section 17,
  open question 20); the catalog entry takes its shortcut from the
  live build menu, not from memory.

## 9. Stockpiles and storage

### 9.1 The stockpiles

* **Leather stockpile.** Leather category, bins max, near the
  tanner and the leather works. A bin holds 45 leather
  (docs/STOCKPILES.md). Leather in bins is fine: the
  clothier-ignores-bins quirk is specific to the clothier
  (CLOTHING.md, section 3.3), and whether the leather works reads
  leather from bins is a phase 7 probe (section 17, open question
  15), not an assumption either way.
* **Hide stockpile.** Refuse category, usable, hides only, near the
  butcher and the tanner, no bins, no barrels. Hides rot, so this
  stockpile is a transit point, not storage: a hide that sits here
  is a hide the tanner has not collected yet, and the snapshot
  says so.
* **Trade leather stockpile.** Leather category, bins max, near the
  depot, take from the bulk leather stockpile only. Surplus leather
  leaves from here, and traded leather arrives here.
* **Goods stockpile.** Finished goods, armor, footwear, handwear,
  headwear, and legwear categories allowed, take from the leather
  works only for new goods. Leather armor goes to the Armor
  stockpile (armor level above 0), not here (docs/STOCKPILES.md).
  Waterskins go to their own stockpile (docs/STOCKPILES.md).
* **Parchment stockpile.** Where SHEET items are stored is
  UNVERIFIED (section 17, open question 12). The stockpile plan
  has no sheet row, and the phase 9 probe finds which category
  takes parchment before any parchment is made in quantity.

### 9.2 What rots and what does not

Leather does not rot. Raw hides rot, and rotten hides cannot be
tanned, so hides go to the tanner promptly or to a refuse stockpile
the tanner can reach before they rot. Finished leather goods do not
rot. Leather clothing wears in storage at one level per 100 years
(UNVERIFIED for this version, CLOTHING.md section 5.2). Leather
armor does not wear over time, unless it is put in a refuse
stockpile: never store armor in refuse (Wear; docs/STOCKPILES.md,
section 9.1). Milk of lime is a liquid in a bucket; quicklime is a
powder in a bag. Neither rots, but both need their container, and
the parchment chain stalls without an empty bucket (section 12).

### 9.3 No correction to docs/STOCKPILES.md

Unlike the clothing work, which corrects the stockpile plan's cloth
row (CLOTHING.md, section 10.3), the leather work needs no
correction to docs/STOCKPILES.md. The Leather row (Bins max, tanned
leather, near tanner and leather works), the Refuse usable row
(hides), and the Finished goods row (waterskins in their own
stockpile) are all consistent with this doc. The only addition is a
sheet row for parchment, which waits on the phase 9 probe in
section 17, open question 12, and lands as an addition, not a
correction.

## 10. Labor

The leather labors, from the live enum (section 5.1): TANNER
(tanning skill), LEATHER (leatherworking skill, LEATHERWORK), and
LYE_MAKING (lye making skill, for milk of lime). The labor plan
(docs/LABOR.md) owns the assignment machinery; this section sets
the leather floors it must cover.

Proposed floors for a 7-citizen fort, to be tuned live in phase 10,
not taken as wiki fact:

| Labor | Floor | Why |
| --- | --- | --- |
| TANNER | 1 when a hide exists | Hides rot; the tanner must run promptly after butchering |
| LEATHER | 1 when leather exists | No leather, no leatherworker; leather without one is a stuck chain |
| LYE_MAKING | 0, rises to 1 when parchment is planned | Milk of lime is needed only for parchment; a standing lye maker is waste |

Floors scale with population: each production labor gains a second
dwarf when its waiting job list stays non-empty across two ticks.
A floor is a minimum, not a target; the harness never assigns a
dwarf to a labor with no waiting work just to fill a number.

Skill matters twice: it sets the quality of the leather goods (and
therefore their value and the happy thought from a preferred item),
and it sets the speed. A matching material preference is worth
about four skill levels on average (Skill), so a dabbling
leatherworker who loves dog leather can outrank an adequate
leatherworker who does not care, for dog leather work specifically.
The labor plan's matching rule already handles that; this plan only
adds the floors. Whether tanning skill affects yield is UNVERIFIED
(section 17, open question 18); the floors do not assume it does.

## 11. Trade

Leather is a trade good three ways: raw leather, finished leather
goods, and leather crafts.

* **Buying.** Human and dwarven caravans sell leather, often in vast
  quantities, and buying it is the cheap way to clothe the fort
  quickly (Meat industry). Request every type of leather so the
  merchant brings a large quantity next year. The harness buys
  leather when the hide supply cannot meet the floor in section
  6.1, and says which floor the purchase serves.
* **Which goods:** leather crafts first (made for trade), then
  surplus leather armor and clothing from the bulk stock, then raw
  surplus leather. Never a good the fort needs for the floor, never
  below the 5-per-dwarf floor (docs/TRADING.md), never a quiver,
  backpack, or waterskin the military is short of.
* **When:** made in the season before the caravan they serve, not
  stockpiled for a year. Elves come in spring, humans in summer,
  dwarves in autumn, none in winter (docs/TRADING.md). The leather
  system queues trade goods in the season before the caravan,
  filtered through the elf rules.
* **Elf rules.** Elves refuse leather and parchment, and every other
  animal-derived good (docs/TRADING.md). Leather is never in an elf
  offer at all: not raw, not crafted, not worn. One wrong item ends
  the session and can lead to war after repeated offences
  (docs/TRADING.md). The harness filters every elf offer through
  the list before the agent ever sees it.
* **Value check:** the candidate-good computation gives the value
  before making, from the item value formula (section 2.7), so the
  agent can compare making a leather craft against selling the raw
  leather. The harness never makes a trade good whose leather is
  worth more raw than made, and never makes one from the hide
  reserve. Rare and dangerous animal leather is worth more (section
  2.7), so it is sold raw or crafted first, never spent on a quiver
  when dog leather would do. Which leather a job consumes, when
  several kinds are on hand, is UNVERIFIED (section 17, open
  question 21); until the probe answers it, the harness assumes
  the game picks, and the trade plan does not depend on choosing.

## 12. Parchment and the library

Parchment is a separate sub-chain with its own gate, and it runs
last on purpose. The chain, end to end:

1. **Quicklime.** Burn calcium carbonate stone at a kiln. The kiln
   is a furnace, not a workshop, and the stone must be on hand.
   Whether the fort's stone includes calcium carbonate is a survey
   fact, not a plan fact; the chain does not start without it.
2. **Milk of lime.** One bag of quicklime becomes one unit of milk
   of lime at an ashery, by a dwarf with the lye maker labor, with
   an empty bucket available (Milk of lime). The bucket is the
   usual stall: no empty bucket, no milk of lime.
3. **Parchment.** One unrotten hide plus 150 milk of lime at a
   tanner's shop makes one sheet (section 2.5). The container is
   preserved, so the bucket comes back.
4. **Use.** Sheets become scrolls at a craftsdwarf's workshop, and
   books for the library. The library plan owns what the sheets
   become; this doc owns making them.

The gate: parchment is made only from surplus hides when leather is
above every floor in section 6.1, and only when the milk of lime is
already on hand. The harness never buys quicklime for parchment
while leather is short, never spends the last hide on a sheet, and
never queues MAKE_PARCHMENT without 150 milk of lime in stock. The
refusal names the gate it hit, the same way the kitchen refuses to
cook below the seed reserve. Parchment is the only leather-chain
product with a liquid input, and the only one whose chain touches
three workshops (kiln, ashery, tanner) plus a bucket, which is why
it is phase 11, not phase 4.

## 13. How the information reaches the AI

This is the part Mikey asked for explicitly: the information must
be fed to the AI optimally. The rules are the same as the
snapshot's rules everywhere else in the harness: counts and
exceptions, never a dump; named options with a one-line why; full
detail behind a query route.

### 13.1 The snapshot's Leather section

The per-tick snapshot gains a short Leather section, built from the
fresh collect, in plain words. The canonical shape, on a 7-citizen
fort with 2 hides waiting, 6 leather, and no leather works:

```
Leather: hides 2 raw, leather 6 (dog 4, cow 2), parchment 0.
  Shops: tanner 1 (idle), leather works 0. Labor: tanner 1, leatherworker 0.
  Need: 1 quiver, 1 backpack. Chain: 2 hides un-tanned, no leather works.
```

What is in it, and what is not:

* **In it:** hide count (fresh, rotten named separately when any
  are rotten), leather count (by material, top 2), parchment count,
  the workshop and labor state, the goods need by kind, and the
  chain bottleneck in one line.
* **Not in it:** the full per-material leather table, the per-dwarf
  equipment table, the hide ages, the milk of lime count when
  parchment is not planned, or the value arithmetic. Those live
  behind GET /v1/leather.
* **Never in it:** a raw dump of the stocks section, a list of every
  leather item, or a number without its unit and its floor. A
  number without its floor is a number the agent cannot act on.
* **When nothing is wrong:** the section diffs to a one-liner,
  "Leather: unchanged (6 leather, 0 hides waiting).", and costs
  almost nothing (section 14).

The Leather section sits beside the Clothing section, not inside
it: the two chains share a hide and a claim order, but they have
different bottlenecks, and merging them would hide which chain is
stuck. The snapshot carries both sections; the agent reads the one
whose bottleneck is named.

### 13.2 The query route

GET /v1/leather returns the full detail: per-material leather,
hide, and parchment counts with units; fresh versus rotten hides
with ages where the read has them; goods on hand by kind; the
per-dwarf equipment table for hunters, marksdwarves, and militia
(name, quiver, backpack, waterskin, leather armor pieces); the
chain status with the bottleneck named; the workshop list with job
counts; the labor coverage for the leather labors; the claim order
with where the spending stopped; the parchment chain state (milk
of lime, quicklime, bucket). It reads from the fresh collect, not
from a cache. The snapshot carries the summary; the route carries
the detail. The agent asks the route when it needs to choose, never
as a matter of routine.

### 13.3 Named options

The planner's leather decisions carry the option in the decision
itself:

* "Build a tanner's shop beside the butcher (x, y, z): 2 hides
  un-tanned, 0 leather, tanner 0."
* "Tan 2 hides at the tanner's shop (2 hides on hand, 0 leather,
  1 quiver short)."
* "Make 1 quiver at the leather works (6 leather on hand, 1
  marksdwarf without a quiver, oldest need first)."
* "Cannot make a quiver: 0 leather, 0 hides. Butcher a surplus
  animal or buy leather at the next caravan."

The suggestion names the exact tool and parameters, as everywhere
else in the harness. When nothing can be made and no workshop
exists, the leather section says so and names the fix (build,
butcher, trade), instead of going silent.

### 13.4 Attention and briefing

Three new attention kinds, all P2 unless a quiver shortage leaves
a marksdwarf unable to fight during a siege (P1, raised by the
military plan, not this one):

* **Hide rotting:** a fresh hide is aging with no tanner assigned
  or no tanner's shop. P2. Briefing kind `leather`: what this is
  (a hide about to rot), what usually matters (leather lost that
  the butcher already paid for), options (assign a tanner, build
  a tanner's shop beside the butcher), cost of ignoring (the hide
  rots and the leather is gone).
* **No tanner:** hides exist and no dwarf has the TANNER labor, or
  no tanner's shop exists. P2. Same briefing kind, with the missing
  piece named.
* **Quiver shortage:** a hunter or marksdwarf has no quiver. P2.
  Same briefing kind, with the dwarf named and the leather on hand
  stated.

The briefing is a few hundred tokens at most (briefings.py rule),
and it fires only on the event tick, never per tick. The caravan
briefing already names leather as a need; the leather briefing
does not repeat it. A naked dwarf stays CLOTHING.md's P1; leather
never raises it, because coverage is the clothing plan's read.
The hide-rotting briefing reads, in full:

```
What: a fresh hide is rotting beside the butcher with no tanner assigned.
Matters: the hide is leather the butcher already paid for; once rotten it cannot be tanned.
Options: assign a tanner, or build a tanner shop beside the butcher.
Cost: ignoring it loses the hide; the next animal costs a season to replace.
Wiki: Tanner shop, Leather, Skin.
```

### 13.5 Opportunities

The opportunities section (docs/HARNESS_ROLE.md, section 7(e))
carries at most 3 leather entries, each one sentence of fact plus
the query route, never a suggestion, never an action named, no
penalty for ignoring:

* "The fort holds 6 leather and 0 leather works (query
  /v1/leather)."
* "2 hides sit un-tanned beside the butcher (query /v1/leather)."
* "1 marksdwarf has no quiver; the fort holds 6 leather (query
  /v1/leather)."

If there are more than 3 opportunities, the harness picks the 3
with the most concrete facts and drops the rest, and the full list
is behind GET /v1/leather. The opportunities section itself is
still unbuilt (HARNESS_ROLE.md, section 2.3: no opportunities
section exists anywhere in the code), so these entries are designed
for a section that does not exist yet. Section 18 flags this
explicitly, because CLOTHING.md section 14.5 describes its own
opportunity entries without noting the dependency.

## 14. Model presentation

This section is required by the 2026-11-27 presentation constraint,
and it states exactly what the model is shown, what it costs, and
what is deliberately withheld. The snapshot stays an index; the
budgets hold.

### 14.1 Snapshot lines and token cost

The Leather section is 3 lines when fully rendered, 1 line when
diffed unchanged. The exact example lines from section 13.1,
measured by the accountant's rule (3 chars per token,
conservative) and the wire rule (4 chars per token):

* **7 dwarves, full render:** 3 lines, 211 chars, 71
  accountant tokens, 53 wire tokens. The lines are the
  stocks line (hides, leather by material, parchment), the
  shops line (which leather workshops exist, labor coverage),
  and the need line (goods by kind plus the chain bottleneck).
* **7 dwarves, unchanged:** 1 line, "Leather: unchanged (6
  leather, 0 hides waiting).", 48 chars, 16 accountant tokens,
  12 wire tokens. This is the steady state: the section costs
  almost nothing on most ticks, because the diffing rule renders
  an unchanged section as a one-liner (assembler.py).
* **50 dwarves, full render:** 3 lines, 224 chars, 75 accountant
  tokens, 56 wire tokens. The lines do not grow with population:
  the stocks line still names the top 2 leather materials, the
  need line still names goods by kind, not by dwarf. The only
  growth is longer counts ("50 citizens", "40 leather") and a
  second material in the breakdown.
* **50 dwarves, unchanged:** 1 line, "Leather: unchanged (40
  leather, 0 hides waiting).", 49 chars, 17 accountant tokens,
  13 wire tokens.

Against the measured baseline (M1 run 2026-11-27, 7 citizens:
snapshot 10,693 chars, about 3,564 accountant tokens, about
2,673 wire tokens), the Leather section adds about 2.0 percent
at 7 dwarves when fully rendered, and about 0.4 percent when
diffed. At 50 dwarves the Units section is the one that grows,
and the Leather section stays flat by design. The snapshot
budget is target 30K tokens, warning 60K, never over 140K
(assembler.py); the Leather section is about 0.24 percent of the
target at full render, and it is cuttable: its cut priority is
below attention, threats, and failure feedback, which are never
dropped, and its cut form is the one-liner. Together with the
Clothing section (about 2.1 percent at full render), the two
sections add about 4.1 percent at 7 dwarves when both render
fully, and under 1 percent when both diff unchanged.

### 14.2 Query route and cost

GET /v1/leather, on demand only, never per tick. At 7 dwarves
the full detail is about 900 chars, about 300 accountant tokens:
per-material counts, a 3-row equipment table (hunters,
marksdwarves, militia on duty), goods by kind, chain status,
workshops, labor coverage, claim order, parchment chain state.
At 50 dwarves it is about 2,000 chars, about 670 accountant
tokens, because the equipment table grows with the squad sizes
(about 60 chars per dwarf listed). The route is the only place
the per-dwarf equipment table exists in model-facing text. The
agent asks it when the snapshot names a gap it wants to
understand, and the retrieval cap (4K tokens per decision,
assembler.py) covers it at either population.

### 14.3 Briefing trigger and cost

The `leather` briefing (section 13.4) fires only when an
attention item of kind hide-rotting, no-tanner, or
quiver-shortage is raised, and it rides on that attention item
for one tick. Its five fields (what, matters, options, cost,
wiki), measured on the example text in section 13.4, are 345
chars, about 115 accountant tokens. It never fires per tick, and
it never fires when the chain is green. A fort with no leather
problem pays nothing for the briefing.

### 14.4 Opportunities entries

At most 3, one sentence of fact plus the query route each
(section 13.5), about 70 chars each, about 25 accountant tokens
each, 75 at most for the whole block. They are facts the agent
may act on or ignore, and ignoring one costs nothing: no score
component, no attention escalation, no diary note.

### 14.5 What this doc deliberately does NOT push to the model

* The per-material leather table beyond the top 2. The snapshot
  names dog and cow; the rest is behind GET /v1/leather.
* The per-dwarf equipment table. The snapshot never lists what
  each hunter holds; the query route carries the table.
* The hide ages. The snapshot carries fresh versus rotten counts;
  how old each hide is lives behind the route.
* The per-animal leather yield table. The snapshot carries a
  leather count; the yields are query detail.
* The parchment chain detail. The snapshot carries a parchment
  count and names the blocker when parchment is planned; the
  kiln, ashery, and bucket state live behind the route, and only
  then.
* The leather value arithmetic. The snapshot carries a computed
  stack value ("3 crafts, about 90 value"); the formula is never
  shown.
* The workshop build catalog for leather. The snapshot names
  which workshops exist and the one missing workshop the chain
  needs; the build options live in the catalog.
* The slaughter detail. Which animal to slaughter, and when, lives
  in docs/ANIMAL_HUSBANDRY.md; the snapshot carries the hide
  count and the claim, not the animal table.
* The uniform definition. Which armor a militia dwarf wears lives
  in docs/MILITARY.md; the snapshot carries the shortfall count,
  not the uniform.
* The trade detail. Caravan seasons, elf rules, and the per-dwarf
  floor live in docs/TRADING.md; the snapshot carries the surplus
  count and the floor, not the plan.

### 14.6 Freedom preserved

Nothing in this section chooses a strategy for the model. The
snapshot states counts, floors, and the bottleneck; it never says
"tan now" or "make a quiver". The named options in section 13.3
are planner decisions the model can take or leave, each with a
one-line why, and the opportunities in section 13.5 carry no
suggestion and no penalty for ignoring. The claim order in section
6.3 is a priority the harness applies when it spends leather, and
it is stated in the doc so the model can see why a spend was
refused; it is not a script the model must follow, and the model
remains free to spend leather differently through an explicit
action, which the harness then records as a deviation rather than
a violation. The model is never told that leather is the right
answer to a problem the snapshot does not show.

## 15. Implementation phases

Each phase ends with a concrete live-verification bar. Nothing
counts as done until it passes its bar against the real game.
This doc is design-complete when written; it is proven only when
its UNVERIFIED marks are cleared live.

1. **Observation.** Extend the stocks collect so the snapshot can
   see what leather needs: leather (SKIN_TANNED) headline count
   and material breakdown; hide headline count split fresh versus
   rotten; parchment (SHEET) headline count; milk of lime on hand;
   goods on hand by kind from the by-type table. Add the Leather
   section to the snapshot and GET /v1/leather. Share the pass
   with the clothing observation work (CLOTHING.md, phase 1), one
   walk, two consumers. Bar: a live collect on the main fort shows
   a leather count that matches a hand count of the same stock,
   and tanning one hide moves the hide count down and the leather
   count up by the yield.
2. **Job-type probe.** On the scratch fort, queue one of each good
   at a leather works (leather armor, leggings, high boots, low
   boots, helm, shield, quiver, backpack, waterskin, bag, shoes,
   gloves, cap, trousers) and read each job struct back: job type,
   item type, item subtype, material taken. Probe the TAN_A_HIDE
   reaction index the same way the brew reaction was probed
   (index 44). Enumerate the dyer's shop menu for any leather
   option. Bar: the probe names the field (or the absence of one)
   for every good with a live job id, names the job type that
   makes a leather bag or records that none exists, and the doc
   records the answer. If a good cannot be chosen by subtype, the
   plan adapts and never claims otherwise.
3. **Workshops.** Extend WORKSHOP_CATALOG with tanner's shop,
   leather works, ashery, and craftsdwarf's workshop, from the
   live workshop enum (25 types, verified). Bar: each workshop
   builds live on the scratch fort and reads back in the Buildings
   section with its correct subtype.
4. **Tanning.** Add a JOB_SPECS entry for tan hide (CustomReaction
   plus TAN_A_HIDE), with a fail-fast floor (one unrotten hide on
   hand). Measure the hide rot time from the fort's own hides and
   the auto-tan trigger distance. Bar: a queued tan job completes
   live and its leather reads back in stocks; a job queued without
   a hide is refused with the missing input named; the counted
   batch for section 3.3 is recorded with the animals tanned.
5. **Leather goods.** Add JOB_SPECS entries for make quiver,
   make backpack, make flask, make leather armor, make leggings,
   make boots, make helm, make shield, sew image, and make
   leather crafts, each with a fail-fast floor (one leather on
   hand). Bar: each job completes live and its product reads back
   in stocks; a job queued without leather is refused with the
   missing input named.
6. **Claim order and planner.** Implement the floor (section 6.1),
   the per-season arithmetic (section 6.2), the claim order
   (section 6.3), and the trade floor (never sell below 5 pieces
   per dwarf). Bar: a live M1 day keeps the quiver floor green,
   ends with leather above the trade floor, and never spends
   leather on a craft while a quiver is short.
7. **Bags and storage.** Make leather bags (once phase 2 finds the
   job type) and cloth bags, count the bag floor from the seed and
   powder stocks, and verify seeds land in bags. Bar: the seed
   stock sits in bags, not spread across tiles, and the bag count
   matches the floor arithmetic from the fresh collect.
8. **Military supply.** Wire the equipment read (section 7.2) into
   the snapshot Leather section, and queue quivers, backpacks,
   waterskins, and leather armor to the uniform. Bar: on the live
   fort, a marksdwarf without a quiver is named with the leather
   on hand, and is observed equipped with a quiver within the same
   run.
9. **Stockpiles.** Build the leather, hide, trade leather, goods,
   and waterskin stockpiles in section 9.1, prove or disprove the
   leather-works-reads-bins question live, and find the stockpile
   category that takes parchment sheets. Bar: leather placed in a
   bins-max stockpile is picked up by the leather works and made
   into a good, or the quirk is proved live and the doc records
   that instead; parchment has a stockpile row.
10. **Labor.** Add the floors in section 10 to the labor system
    and wire `labor_toggle` to assign them. Bar: the assigned
    tanner is the highest-skill dwarf with the tanning labor,
    verified by read-back, and is observed tanning a hide within
    the same run.
11. **Parchment.** Build the kiln, ashery, and bucket supply, and
    queue MAKE_PARCHMENT only from surplus hides with 150 milk of
    lime on hand. Bar: a sheet of parchment is made live from a
    surplus hide, the milk of lime count falls by the reaction
    amount, and the gate refuses a parchment job while leather is
    below the floor, naming the gate.
12. **Trade.** Queue leather crafts from surplus in the season
    before a caravan, filtered through the elf rules and the
    never-sell floor, with the value check against selling raw;
    buy leather when the hide supply cannot meet the floor. Bar:
    a live trade batch is made, its value is computed before
    making, and no leather is offered to elves.
13. **Attention, briefing, and snapshot.** Wire the chain status
    into the snapshot Leather section, add the hide-rotting,
    no-tanner, and quiver-shortage attention kinds, and add the
    `leather` briefing. Bar: on the live fort, a rotting hide is
    named with the tanner state, and a quiver-less marksdwarf is
    named with the leather on hand; the briefing fires once on
    the event tick and never again while the problem stands.
14. **Standing orders.** Probe whether auto-tan is readable and
    writable from Lua. If it is, the harness owns it: auto-tan on
    by default, off when a hide is reserved for parchment. Bar:
    the standing-order state reads back after a write, and no hide
    reserved for parchment is auto-tanned. If no write route
    exists after a real investigation, the doc records exactly what
    was tried and what blocked it.

Every phase carries offline tests (including malformed-input
tests per the standing rule) and goes through the pre-push
self-review gate before it is committed and pushed.

## 16. Refusals

The leather system refuses, and says why, in plain words:

* Never slaughter an animal for hide alone while the fort is short
  of meat. A hide is a byproduct of a meat decision.
* Never tan a rotten hide. The reaction refuses it anyway; the
  harness refuses it first, with the hide named.
* Never spend leather on a craft while a marksdwarf has no quiver
  or a hunter has no quiver. The claim order is not a suggestion.
* Never make a leather trade good while a dwarf is uncovered and
  the leather could cover them, and never sell below the 5-pieces
  per dwarf floor.
* Never spend a hide on parchment while the fort is short of
  leather, and never queue parchment without 150 milk of lime on
  hand.
* Never offer leather, parchment, or any animal-derived good to
  elves. Elves refuse them, and one wrong item can end the
  session.
* Never make a leather garment for a civilian from sentient
  leather. Dwarves will not wear it, so it is a trade good or
  nothing.
* Never queue a leather dye job. Leather dyeing is a v52.03
  addition, not a 0.47.05 mechanic, until the phase 2 probe proves
  otherwise.
* Never queue a leather bag job until phase 2 finds its job type.
  The harness does not guess job types.
* Never claim a good kind the harness cannot choose. If the phase
  2 probe finds no subtype choice, the harness says the game picks
  the good.
* Never store leather armor in a refuse stockpile. Armor wears
  there and nowhere else over time.
* Never sell, melt, dump, or forbid an artifact leather good.
  Artifacts never wear and must never be sold.
* Never queue a leather job without the leather on hand at job
  start. The fail-fast floor is 1 whole unit per job.
* Never count a rotten hide toward the tannable supply. A rotten
  hide is leather already lost.
* Never count a caravan's leather as the fort's leather. Trader
  goods are excluded from stocks, and the leather count follows
  the same rule.
* Never send the tanner to collect a hide the butcher has not
  produced yet. The tanner works with hides on hand, not hides
  promised.

## 17. Open questions (UNVERIFIED)

1. **TAN_A_HIDE reaction index.** The live index of the tan
   reaction, the same way the brew reaction was probed as index
   44. Phase 2 probes it.
2. **Bag job type.** Which job type makes a leather bag at the
   leather works. There is no MakeBag in the 241 live job types
   and no bag reaction in the raw reaction files, yet the
   leatherworker page lists "Construct Leather Bag" as a task.
   Phase 2 hunts it by queueing a bag and reading the job struct
   back.
3. **Leather dyeing in 0.47.05.** The Dye page carries a v52.03
   marker on leather, and the live enum has no DyeLeather job.
   Phase 2 enumerates the dyer's shop menu live and records
   whether any leather option exists.
4. **Leather works menu enumeration.** Exactly which items the
   leather works menu offers in 0.47.05, how MakeArmor,
   MakePants, MakeGloves, MakeHelm, and MakeShoes pick which
   garment they make, whether the harness can choose by item
   subtype, and whether the menu offers masks, turbans, veils,
   headscarves, and chausses. Phase 2 enumerates the menu live.
   This is the same probe as CLOTHING.md open question 1, run at
   the leather works.
5. **Leather yield table.** Whether the per-animal yields on the
   Leather page (cow 2, giant elephant 10, water buffalo 2 to 3,
   and the rest) hold in 0.47.05, and what mechanism turns one
   hide into several leather. The tanner page's cow figure carries
   a v50.01 marker, so it is suspect. Phase 4 verifies with a
   counted batch. This is the same question as CLOTHING.md open
   question 14; this doc owns the answer.
6. **Auto-tan trigger distance.** How close a skin must be to the
   tanner's shop for auto-tan to fire. The wiki says only "within
   a certain distance". Phase 4 measures it by placing hides at
   known distances.
7. **Standing orders write route.** Whether auto-tan is readable
   and writable from Lua, and where the field lives. Phase 14
   probes it. This is the same shape as CLOTHING.md open question
   3, for the tannery instead of the loom.
8. **Severed-part skins.** Whether a skin from a severed part
   tans into full-size leather in 0.47.05, as the Leather page
   claims. Phase 4 tests it with a combat severed part if one is
   available, or records it as untestable on this fort.
9. **Sentient leather in trade.** Whether traded leather ever
   arrives from a sentient creature, and whether the stocks read
   can identify it by creature token. Phase 1 checks the material
   breakdown; the trade phase watches for it.
10. **Shield material choice.** How MakeShield picks leather over
    wood or metal, given that `item_shield.txt` carries no
    material tokens at all. Phase 2 queues a shield at the leather
    works and reads back the material the job took.
11. **Instrument pieces.** Whether leather instrument pieces are
    makeable in 0.47.05 and under which job type. No instrument
    job type exists in the live enum. Phase 2 probes it.
12. **Parchment stockpile category.** Which stockpile category
    takes SHEET items, and whether parchment needs its own row in
    docs/STOCKPILES.md. Phase 9 finds it live.
13. **Hide rot time.** How long a fresh hide lasts before it rots
    in 0.47.05. Phase 4 measures it from the fort's own hides,
    timed from butchering to rotten.
14. **Wear on leather gear.** Whether quivers, backpacks,
    waterskins, and leather shields wear at all, and at what rate.
    Leather clothing wears like cloth clothing (CLOTHING.md,
    section 5.3); leather armor does not wear over time. Phase 1
    watches the fort's own gear over time.
15. **Leather works and bins.** Whether the leather works takes
    leather from bins, or whether it shares the clothier's
    ignores-bins quirk (CLOTHING.md, section 3.3). Phase 9 proves
    it live.
16. **Size specification.** Whether the harness can specify a
    creature size on a queued leather job, for non-dwarven
    residents. Phase 2 probes it. Same question as CLOTHING.md
    open question 2.
17. **Current fort leather state.** How much leather and how many
    hides the main fort holds right now. The game is down while
    this doc is written, and the 2026-11-27 M1 log contains no
    SKIN_TANNED mention. The first collect after recovery answers
    it.
18. **Skill and value effects.** Whether tanning skill affects
    yield or only speed, whether leatherworking skill affects
    anything beyond quality and speed, what MATERIAL_SIZE governs
    in the item raws given that consumption is one unit per job,
    and by what mechanism a creature's leather is worth more than
    another's. Phase 4 and phase 5 watch for yield differences
    across skill levels.
19. **Observation cost and hide reads.** Whether the per-dwarf
    inventory walk is cheap enough at 50 dwarves, whether an
    equipped quiver reads the same way as a stored one, and
    whether fresh hides sit in IN_PLAY the way finished goods do
    or need a separate pass. Phase 1 measures all three live.
20. **Ashery shortcut.** The build-menu shortcut for the ashery.
    The wiki pages read for this doc do not state it, and the
    catalog entry must take it from the live build menu, not from
    memory.
21. **Leather selection.** When several kinds of leather are on
    hand, which kind a leather works job consumes, and whether the
    harness can choose. Phase 5 tests it with two leather kinds on
    hand and reads back what the job took.

## 18. Cross-doc conflicts flagged

No silent contradictions. Every place this doc touches another
doc's claim is named here.

1. **CLOTHING.md open question 6, partially resolved.** CLOTHING.md
   asked exactly which leather works menu items are civilian
   clothing and which are armor in 0.47.05. Section 2.4 of this
   doc resolves the split from the raws for every item carrying
   an ARMORLEVEL token: leather armor, leggings, high boots, low
   boots, and helm are armor; trousers, skirts, loincloth, thong,
   braies, shoes, gloves, mittens, cap, and hood are clothing;
   gauntlets, greaves, and socks are not leather-makeable. What
   stays open is the menu enumeration (section 17, open question
   4): the raws say which items can be leather, not which items
   the menu offers. CLOTHING.md's question is therefore half
   answered, and this doc does not claim it closed.
2. **CLOTHING.md open question 14, ownership moved.** The leather
   yield table is CLOTHING.md open question 14. This doc owns the
   answer now (section 17, open question 5, phase 4 counted
   batch). CLOTHING.md's table in its section 2.2 stays as a
   summary; this doc's section 3.3 is the authority, and any
   correction from the counted batch lands here and is then
   carried back to CLOTHING.md, not corrected in only one place.
3. **Opportunities section, dependency stated.** CLOTHING.md
   section 14.5 describes opportunity entries as if the
   opportunities section exists. It does not: HARNESS_ROLE.md
   section 2.3 says no opportunities section exists anywhere in
   the code, and section 7(e) is a verdict to add one. This doc
   states the dependency explicitly in section 13.5: its three
   leather opportunity entries are designed for a section that
   does not exist yet, and they land when the section lands. The
   CLOTHING.md entries have the same dependency, unstated there.
4. **TRADING.md floor, adopted as combined.** TRADING.md sets the
   floor at 5 pieces of cloth or leather per dwarf. This doc
   adopts it as a combined count (section 6.1), not 5 cloth plus
   5 leather. If TRADING.md meant each, the floor in section 6.1
   is wrong by a factor of two and the trade phase corrects it
   with the TRADING.md text as authority.
5. **STOCKPILES.md, no correction.** The clothing work corrects
   the stockpile plan's cloth row (CLOTHING.md, section 10.3).
   The leather work needs no correction: the Leather, Refuse
   usable, and Finished goods rows are consistent with this doc
   (section 9.3). The only addition is a parchment sheet row,
   which waits on section 17, open question 12.
6. **MILITARY.md uniform, consistent.** MILITARY.md's starter
   uniform needs a leather quiver, leather armor, leather shield,
   and leather high boots. This doc supplies all four under the
   claim order in section 4, with quivers first. No conflict.
7. **ANIMAL_HUSBANDRY.md hide yield, consistent.** The husbandry
   plan says a dog yields one raw hide. This doc's yield table
   says a dog hide tans to 1 leather. The two agree, and the
   counted batch in phase 4 checks both at once.
8. **HARNESS_ROLE.md snapshot as index, followed.** The Leather
   section follows the same index rule as the Clothing section:
   counts, exceptions, diffs only, flat with population. Section
   14 measures it against the same baseline.

## 19. Failure modes

What goes wrong, in the order the harness is most likely to meet
it:

* **Hides rot before tanning.** No tanner assigned, no tanner's
  shop built, or the tanner's shop built far from the butcher so
  auto-tan never fires. The fix is placement and the floor in
  section 10, not more animals. The attention kind in section
  13.4 names it while the hide is still fresh.
* **Auto-tan eats the parchment hide.** Auto-tan is on, a hide is
  earmarked for parchment, and the tanner tans it before the milk
  of lime arrives. The fix is the phase 14 standing-order probe:
  until auto-tan can be controlled, parchment is made only from
  hides that are surplus after tanning, never from hides still
  waiting.
* **Leather spent down the claim order.** Crafts or decoration made
  while a marksdwarf has no quiver, or trade goods made while a
  dwarf is uncovered. The fix is the claim order in section 6.3
  enforced as refusals, not as guidance.
* **Leather sold below the floor.** Raw leather or goods sold to a
  caravan while the fort holds under 5 pieces per dwarf. The fix
  is the trade floor refusal in phase 6, with the numbers named.
* **Leather armor issued as clothing.** A leather helm or leather
  armor counted toward coverage, leaving a dwarf uncovered in the
  harness's own numbers. The fix is the coverage check counting
  armor level 0 only (CLOTHING.md, section 8.1), which this doc
  does not re-decide.
* **No bags, seeds sprawl.** Leather and cloth both spent on
  clothing while seed storage has no bags, so seeds take one tile
  each and dye has nowhere to go. The fix is the bag floor in
  section 6.1, computed from the seed and powder counts.
* **Quiver shortage in combat.** Marksdwarves without quivers
  withdraw from combat (Crossbow). The fix is the quiver floor
  and the attention kind, not a bigger military.
* **Elf offense.** Leather in an elf offer ends the session and can
  lead to war after repeated offences (docs/TRADING.md). The fix
  is the elf filter before the agent ever sees the offer.
* **Sentient leather clothing.** Traded sentient leather made into
  civilian clothes dwarves refuse to wear, leaving a stockpile of
  unwearable garments the coverage check counts as supply. The
  fix is section 2.8: sentient leather is trade goods only, and
  the material breakdown flags it.
* **Parchment chain stalls.** No calcium carbonate stone, no kiln,
  no empty bucket, no ashery, or milk of lime spent elsewhere.
  The fix is the gate in section 12: parchment starts only when
  every input is on hand, and the snapshot names the missing one.
* **Mood claims the tanner's shop.** A strange mood tanner
  (StrangeMoodTanner exists in the live enum) claims the shop and
  halts tanning while hides rot. The fix is a second tanner's shop
  once the fort can afford one, and an attention item while the
  shop is claimed. Whether a mood can claim a workshop the
  harness built is UNVERIFIED; the phase 4 run watches for it.
* **Stocks blind spot.** Leather counted as stacks instead of
  units, trader leather counted as fort leather, or rotten hides
  counted as tannable supply. The fix is the read design in
  section 7.1: units, trader-held excluded, rotten split out.
* **Dyeing leather attempted.** A job queued for leather dyeing
  that does not exist in this version, failing silently or
  stalling the dyer. The fix is the refusal in section 16 and the
  phase 2 menu probe.
* **Bag job guessed.** A bag job queued under a job type the game
  does not recognize, failing or queueing the wrong job. The fix
  is the refusal in section 16: no bag job until phase 2 finds
  its job type.
* **Tanner's shop built, tanner never arrives.** The labor floor
  exists but no dwarf has the labor, or the labor is assigned to
  a dwarf who is always busy elsewhere. The fix is the labor
  read-back in phase 10: the assigned tanner is verified by
  read-back, not assumed from the assignment call.

## 20. Sources

Wiki pages read from the local index
(`~/workspace/df-wiki-export/dfq.py`, hybrid search default and
page dumps):

* Leather, Tanner's shop, Leather works, Leatherworker, Skin,
  Dye, Dyer's shop, Bag, Flask, Clothing, Meat industry, Armor,
  Paper industry, Milk of lime, Quicklime, Ashery, Equipment,
  Crossbow, Archery, Decoration, Leatherworker (skill page),
  Butcher (via Animal husbandry cross-references).
* Value (leather base value 5, bag value 10, flask value 10, via
  the page infoboxes), Stockpile (bin capacity 45 leather),
  Skill (matching preference worth four skill levels).

0.47.05 raws, read from the repo install:

* `third_party/df_47_05/raw/objects/reaction_other.txt`
  (TAN_A_HIDE lines 5 to 15, MAKE_PARCHMENT lines 360 to 371,
  MAKE_SCROLL, PROCESS_PLANT_TO_BAG; no bag-making reaction,
  no leather dye reaction).
* `third_party/df_47_05/raw/objects/material_template_default.txt`
  (SKIN_TEMPLATE with TAN_MAT and PARCHMENT_MAT, ROTS,
  IMPLIES_ANIMAL_KILL; LEATHER_TEMPLATE with MATERIAL_VALUE 1).
* `third_party/df_47_05/raw/objects/item_armor.txt` (leather
  armor ARMORLEVEL 1, MATERIAL_SIZE 6; nine soft upper-body
  items with none).
* `third_party/df_47_05/raw/objects/item_shoes.txt` (shoes,
  high boots, low boots, sandals with LEATHER; socks without;
  chausse unconfirmed).
* `third_party/df_47_05/raw/objects/item_gloves.txt` (gloves
  and mittens with LEATHER; gauntlets ARMORLEVEL 2 without).
* `third_party/df_47_05/raw/objects/item_helm.txt` (helm
  ARMORLEVEL 1 with LEATHER; cap, hood, turban, mask, veils,
  headscarf with LEATHER and no ARMORLEVEL).
* `third_party/df_47_05/raw/objects/item_pants.txt` (trousers,
  skirts, loincloth, thong, braies with LEATHER and no
  ARMORLEVEL; leggings ARMORLEVEL 1 with LEATHER; greaves metal
  only).
* `third_party/df_47_05/raw/objects/item_shield.txt` (shield
  ARMORLEVEL 2, buckler ARMORLEVEL 1, no material tokens at all).
* `third_party/df_47_05/raw/objects/building_custom.txt` (the
  only workshop definition file; defines SOAP_MAKER and
  SCREW_PRESS only, proving the tanner and leather works are
  hardcoded).

Harness state verified against the repo:

* actions.py WORKSHOP_CATALOG (carpenter, mason, still, kitchen
  only) and JOB_SPECS (brew, brew_fruit, cook, 8 carpenter
  furniture jobs only; CustomReaction 211; brew probed as
  reaction index 44).
* daemon.py TASK_DEFS (6 tasks, none leather).
* lua/stocks.lua (by_type counts every IN_PLAY item type;
  add_mat breakdown for DRINK, FOOD, MEAT, FISH, PLANT, SEEDS,
  BAR, WOOD, CLOTH, THREAD only; no leather_units, hide_units,
  or parchment_units; trader-held exclusion).
* lua/act_build.lua (subtype resolved through
  df.workshop_type, errors on unknown name).
* assembler.py _stocks (renders drink, food, wood, stone,
  brewable plants, empty barrels, food stacks; no leather),
  TokenAccountant (3 chars per token conservative, 4 chars per
  token wire), budgets (target 30K, warning 60K, never 140K),
  retrieval cap 4K, diffing (unchanged section renders as a
  one-liner).
* lua/units.lua (needs, skills, labors, wounds; no inventory),
  lua/probe_picks.lua and lua/equip_pick.lua (the only inventory
  walks in the repo, pick-specific).
* lua/buildings.lua (workshop subtype from df.workshop_type).
* planner.py (no leather thresholds or decisions),
  attention.py (no leather kinds), briefings.py (no leather
  briefing), catalog.py (entries built by introspection from
  the action table).
* tests/fixtures/runtime-enums-0.47.05-r8.json (241 job types,
  including MakeArmor, MakeHelm, MakePants, MakeGloves,
  MakeShoes, MakeShield, MakeFlask, MakeBackpack, MakeQuiver,
  SewImage, MakeCrafts, DyeThread, DyeCloth, StrangeMoodTanner;
  no MakeBag, no DyeLeather, no TanHide, no MakeInstrument;
  25 workshop types including Tanners, Leatherworks, Ashery;
  92 item types including SKIN_TANNED, FLASK, BACKPACK,
  QUIVER, SHEET; labors LEATHER, TANNER, LYE_MAKING; skills
  LEATHERWORK, TANNER, LYE_MAKING).
* logs/m1-20261127-073557.jsonl (real M1 snapshot, 7 citizens:
  10,693 chars, about 3,564 accountant tokens; no SKIN_TANNED
  mention, so the fort's leather stock on that date is unknown,
  not zero; Buildings line shows no leather workshop).
* docs/CLOTHING.md (clothing chain, coverage check, claim order
  section 7.4, open questions 1, 2, 3, 6, 14, hospital reserve),
  docs/ANIMAL_HUSBANDRY.md (slaughter section 7.3, butchering
  section 7.2, dog yield), docs/MILITARY.md (starter uniform,
  quiver requirement), docs/TRADING.md (caravan seasons, elf
  rules, 5-per-dwarf floor), docs/STOCKPILES.md (Leather row
  Bins max, Refuse usable hides, bin holds 45 leather,
  waterskins in their own stockpile), docs/LABOR.md (labor
  floors, no tanner or leatherworker floors), docs/HARNESS_ROLE.md
  (section 2.3 no opportunities section in code, section 7(e)
  opportunities verdict, snapshot as index).
