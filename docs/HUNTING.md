# Hunting

Design document for how the Urist harness handles hunting. This is a plan,
not an implementation. Nothing here is built yet. Every game mechanic in
this document comes from the local Dwarf Fortress wiki index (see Sources
at the end) or from live verification against the real game. Anything not
verified against one of those two is marked UNVERIFIED.

## 1. Purpose

Hunting is how a fortress turns the wildlife outside its walls into food,
leather, bone, and fat, without a farm and without a caravan. The harness
must turn hunting from a labor toggle the agent has to babysit into a
thing the harness drives: it picks which dwarves hunt, checks they are
equipped, watches the bolt stock, watches the wildlife, watches the
hunter's safety, and pulls the hunter back when the risk stops being
worth the meat. The agent picks from named options; the harness does the
watching. This document covers the whole loop: the hunter, the equipment,
the prey, the ammunition, the butchering, the safety rules, and the
refusals that keep hunters alive.

## 2. How hunting works in DF 0.47.05

All of this section is from the wiki pages listed in Sources. Where the
wiki itself flags a claim as unverified, this document says so.

### 2.1 The hunting labor and the ambusher skill

Hunting is a labor, not a designation. A dwarf with the hunting labor
enabled is a hunter. There is no order to hunt a specific animal and no
hunting zone: the hunter picks a mark at random, pursues it, and the
harness cannot choose the target. That single fact shapes the whole plan:
the harness controls hunting by deciding whether hunting is on, who hunts,
and when to stop it, never by pointing at a deer.

While hunting outside the fortress, the dwarf uses the ambusher skill to
sneak up on the prey. The higher the skill, the closer the hunter can get
before being spotted and the faster it can move while sneaking. An
unskilled hunter crawls in ambush mode and cannot catch fast animals like
badgers; an experienced one can rapidly bring down even swift prey. Once
the hunter is within shooting range, the ambusher skill stops mattering
and only combat skills are used: the hunter engages with the crossbow.
The skill also grows while hunting, along with marksdwarf and archery.
The attributes behind it are agility, focus, spatial sense, and
kinesthetic sense.

The hunting labor is in the Ranger skill group with animal caretaker,
animal dissector, animal trainer, and trapper. Its profession is Ranger
and its job title is Hunter. Hunters wear green clothes with brown
underclothing, gloves, and shoes.

### 2.2 Equipment

A hunter needs three things: a crossbow, a quiver, and bolts. Only
weapons that use the crossbow/marksdwarf skill work for hunting; bows and
blowguns are not valid. The standard embark load includes 3 quivers, and
immigrating hunters arrive with a full set: a metal crossbow, a quiver,
and some bolts. A hunter without equipment picks it up automatically from
the ammunition stockpile when it goes hunting, including the quiver and
the bolts.

Crossbows are made at a bowyer's workshop from wood or bone, or at a
metalsmith's forge from metal. For ranged combat a wooden or bone crossbow
is identical to a metal one (same accuracy, same range), but when a target
rushes up and forces melee, a light wooden or bone crossbow is
significantly inferior to a metal one, because a crossbow in melee is
used with the hammerdwarf skill. Bolts are made at a craftsdwarf's
workshop or at a forge. Wood and metal bolts come in stacks of 25; bone
bolts come in stacks of 5. Bone bolts are better than wooden ones and
inferior to metal ones. Quivers are made at a leather works.

The food guide recommends more than the minimum: the best armor set the
dwarf can use without slowing down, a weapon of the highest quality
available, a quiver, and a backpack. A waterskin is not recommended: it
carries no alcohol and gives no happiness. Recommended skills beyond
ambusher are marksdwarf (at least novice), hammerdwarf (for when the
crossbow is used in melee), armor user (to reduce encumbrance), and
dodger (for dodging aggressive animals).

### 2.3 The hunt itself

The hunter sneaks toward its mark. As it gets closer, the chance of
being spotted rises; once spotted, the animal flees or fights and the
ambush ends. When the hunter is in range it shoots. A hunter that runs
out of bolts gets a job cancellation and runs away from its target as
fast as it can. A hunter with no bolts assigned will chase its prey and
club it with the crossbow, which the food guide describes as about as
effective as it sounds.

Upon killing the prey, the hunter usually carries it home to the butcher's
shop, where a butcher takes over. The hunter may kill other creatures
that are closer than its fleeing mark; it ignores those accidental
carcasses and brings home only the one it marked beforehand. So a hunt
can leave several dead animals lying around the map, rotting, unless the
fort's standing orders gather refuse from outside. Hunters will also
shoot bolts at carp and other water creatures in a river, and will not
recover the dead fish: bolts spent on fish are bolts wasted.

Hunters fight to the death if engaged. They will not stop their current
hunt if the hunting labor is disabled; the dwarf may end up hunting
whatever creatures spawn next, with potentially suicidal results. The
wiki notes this may be avoidable by disabling the labor while the hunter
is hunting or returning the kill, but the safe reading is that disabling
the labor is not a recall. It is a stop for the next hunt, not the
current one.

### 2.4 Where the animals are

Animals suitable to the biome appear randomly on the edge of the map, on
each layer: the surface and each cavern layer. Dwarves can hunt wild
animals on each of these layers. Only one group of animals appears at any
given time on a layer, and as soon as one group leaves another takes its
place. That is how a marmot hunter can suddenly be face to face with an
elephant, a giant eagle, or worse. A seasoned and well-equipped hunter is
more than a match for a giant eagle, and can be good preemptive defense
for above-ground workers. Ten novice hunters working together can take
down even very large, very fast animals, and a highly skilled and agile
hunter can single-handedly take down nearly anything.

Heavy hunting has a long-run cost: after a period of time, most hunters
will eventually cause the mass extinction of wild animals in the biomes
where the fort is. Two ways to prevent it: make sure some animals always
escape (as long as at least one member of a group survives to leave the
map, the population of that creature does not decrease), or capture the
wild animals, breed them, and release them back or hunt the offspring.

### 2.5 Hunting animals

Animals with the TRAINABLE or TRAINABLE_HUNTING creature token can be
trained for hunting by an animal trainer. Trained hunting animals gain
speed, agility, and possibly ambusher and observer bonuses. Once trained,
they can be assigned to follow specific hunters and accompany them when
hunting. War beasts can also be assigned: they are much stronger and can
help take down bigger game, but cannot sneak and may rush into combat
early. Dogs are the cheap version of both: pet value 30, trainable for
both hunting and war, and they breed fast.

### 2.6 Military hunting

The alternative to civilian hunters is the military. Soldiers can be
ordered to kill wild animals, which is particularly useful if a large
herd appears and the fort wants them all before they leave the map. The
food guide notes it has admitted advantages: a squad can be told to pick
a specific target, and, more conveniently, to stop, which a hunter
cannot. Crossbow military dwarves are the safe version: armored,
disciplined, and their combat skills improve from the fight. Melee
soldiers risk being maimed or killed, must be agile enough to catch a
running animal before it leaves the map edge, and mangle the corpse,
which can make it unfit for butchering. Soldiers also attack the nearest
non-friendly creature in sight when told to move or kill, regardless of
the target given, so a military hunt near the fort's own animals or
workers is a risk. Soldiers will not kill or butcher domestic or tame
animals.

### 2.7 The butchering chain

A hunted animal is only food after it is butchered. The chain is:
butcher's shop, then tanner's shop for the hide, then kitchen for the fat
and the meat. Section 9 covers it in full. The one fact that shapes
planning: the butcher's shop only notices a corpse if it is in a
stockpile or lying on the ground within 20 tiles of the shop's edge on
the same z-level (a 43x43x1 box centered on the workshop). A corpse
further away is never tasked, and rots where it fell.

## 3. What the harness knows today

Verified against the repo on 2026-11-27. Anything the harness cannot do
yet is named here so the plan does not pretend otherwise.

- The labor machinery exists and is verified. `labor_toggle` in
  `actions.py` enables or disables a labor on one citizen by name or
  unit id, through `act_labor.lua`, with a read-back postcondition: the
  citizen's labor list in the observe `units` section must contain (or
  lack) the labor, or the action fails. HUNT, BUTCHER, and TANNER are
  all real `df.unit_labor` enum names in the live runtime fixture
  (`tests/fixtures/runtime-enums-0.47.05-r8.json`), and the job types
  Hunt, ButcherAnimal, and SlaughterAnimal all exist in the same
  fixture. There is no hunt action in the catalog and no composed hunt
  task; the labor toggle is the only hunting control the harness has
  today.
- The units observation sees wildlife. `lua/units.lua` emits every wild
  animal as a compact record: id, name, race, position, kind, role.
  It also computes `dist_nearest_citizen` for each wild animal
  (Chebyshev distance, +10 when the z differs, the same rule as the
  hostile threat distance) and `wildlife_by_race` counts for the
  per-tick push. The harness can therefore answer "what is out there,
  where is it, and how close is it to my dwarves" from a fresh collect.
  What it cannot see: the animal's size, its danger, or its health.
  The compact record carries no size and no hostility flag. Race is the
  only signal, so danger and yield must come from a game table keyed
  by race, built from the creature raws (see 7.3 and 10.2).
- The planner says hunting is not implemented. `docs/PLANNER.md`
  records "Fishing / hunting: Not implemented. Gathering covers the
  same need (raw plants) with a verified path." The diagnosis layer
  already knows the butchering answer: `diagnose.py` tells the agent
  to "gather plants or butcher an animal" when food is short, but
  there is no task behind the second half of that sentence.
- The butcher's shop exists as a workshop type (Butchers) in the
  runtime enum, along with Bowyers, Craftsdwarfs, Tanners, and
  Leatherworks, and the item types AMMO, QUIVER, WEAPON, MEAT, and
  SKIN_TANNED all exist. No composed task builds a butcher's shop, a
  bowyer's workshop, or a tanner's shop, and no task produces bolts.
  The generic build and queue_job machinery can address all of them;
  the hunting work is composition, not new primitives.
- The have/need machinery exists in `materials.py` and answers
  "have X, need Y" for any job from fresh per-tick collects. The
  hunting plan builds the equipment and ammunition checks on top of
  this, not beside it.
- The scoring system has no hunting milestone and the events system
  has no hunting event. A hunter's death is recorded as a unit death
  with a cause; a successful hunt is not recorded anywhere. Phase 5
  adds both.
- The site selection work is queued, not existing.
  `docs/SITE_SELECTION.md` does not exist yet. The butcher's shop,
  the refuse stockpile, and the ammunition stockpile are placed by
  that work once it lands: the butcher's shop near the refuse pile,
  the ammunition stockpile near the fort entrance, neither blocking
  the main corridor.

## 4. When hunting is worth it

Hunting is never the fort's primary food source, and the plan never
pretends it is. The food guide ranks the seven ways to get food:
farming is the most stable and plentiful, usually followed by trading.
Hunting is erratic but, with a skilled ambusher, bountiful. It is a
supplement, and the harness scores it as one.

### 4.1 The comparison, by the numbers the wiki gives

- Farming: a 6x6 field and two planters feed 200 dwarves. It is
  contained, it runs like clockwork once established, and it is the
  only food source that also produces brewable plants. Farming needs
  seeds, soil or mud, and time to get going.
- Hunting: no farm needed, no seeds needed, and the returns are
  usually higher than fishing with more byproducts (bones, tallow,
  leather, skulls). The cost is exposure: hunters work outside the
  defenses, sleep outside, and pick their own marks. The food guide
  calls it "almost like fishing, except there is more spectacle (and
  blood!), the returns are usually higher but the risk is higher as
  well."
- Trading: steadier than hunting and safer, but it needs a depot, a
  caravan, and goods to sell, and no caravan comes in winter.
- Gathering: the quickest fix for a shortage, but the yield is small
  and it thins out as gatherers walk further.

The harness's rule, from those facts: hunting is worth it when the
fort has food pressure and one of the following is true: the farm is
not yet producing, the farm cannot cover the season, or the fort has a
hunter, equipment, and bolts already and the wildlife is safe game.
Hunting is not worth it when the farm covers the food floor with a
margin, when the wildlife is dangerous game, when there is a siege or
ambush in progress, or when the fort has no butcher and no tanner, in
which case the food guide says plainly: "If not, it is a total waste
and you are better off fishing."

### 4.2 The food math the harness uses

The harness does not invent a meals-per-kill number. Yield depends on
the animal's size and on chance, and the wiki gives no fixed table, so
the harness reads yields live from butchering outcomes and builds its
expectation from what it has actually seen, not from a guessed table.
What it does compute, from verified numbers:

- The per-dwarf floor: 5 food per dwarf, the same threshold the game
  itself uses for emergency supplies (see docs/TRADING.md section
  2.6). Below the floor, food is a survival problem and hunting is
  ranked by how fast it can add meat, not by how pleasant it is.
- The season's consumption trend: the store keeps stock trends, so
  the harness knows whether food is falling toward the floor or
  rising away from it. Hunting is scored on the trend, not on a
  single reading.
- The yield class of the game on the map: from the game table in 7.3,
  the harness knows whether the current wildlife is large game
  (several meat stacks, organs, fat, hide, bones, skull), medium game
  (a few stacks), or small game (a skull only, or nothing worth
  butchering at all). Very small animals such as cavies or weasels
  produce only a skull when slaughtered, and a hunter-killed one is
  not butchered at all: the hunter brings home nothing for it.
- The cost side: bolts spent per kill, hunter time outside, and the
  risk of losing the hunter. A hunt that costs a hunter is never
  worth the meat, whatever the yield class.

Hunting never produces booze. The fort still needs farming, gathering,
or trading for brewable plants. A fort that hunts well and brews
nothing still runs out of drink, and the harness says so when it
recommends hunting.

## 5. Hunter assignment and equipment

### 5.1 Who hunts

The harness picks the hunter; the agent approves the pick. The ranking
is a table, not a feeling:

1. Ambusher skill first. A dwarf with ambusher skill sneaks closer,
   moves faster while sneaking, and catches fast animals an unskilled
   hunter cannot reach at all.
2. Marksdwarf skill second. Once the ambush ends, only combat skills
   are used, and the crossbow is the weapon.
3. Hammerdwarf and wrestling third. A crossbow in melee is a hammer,
   and a hunter that gets grabbed needs wrestling to break a jaw-grip.
   The wiki recommends training hunters in both.
4. Dodger and armor user fourth. Both keep the hunter alive when the
   prey fights back.
5. Agility, focus, spatial sense, kinesthetic sense: the attributes
   behind the ambusher skill, read from the citizen record.
6. Never a dwarf the fort cannot spare: not the only planter, not the
   only brewer, not a dwarf already wounded, not a dwarf in a mood.
   A hunter is outside the walls for most of the day; the fort must
   still run without them.

One hunter is the default. Ten novice hunters working together can
take down even very large, very fast animals, so a pack is a real
option when the game is large and the fort has hunters to spare, but
a pack of novices is ten dwarves outside the walls, and the harness
scores that exposure honestly. The agent sees the pack as a named
option with its risk stated, never as a default.

### 5.2 The equipment check

Before hunting is enabled on a dwarf, the harness checks the full kit
through the have/need machinery, and refuses with a named reason when
something is missing:

- Crossbow: one, in the fort's stocks or in the dwarf's hands. Wood
  or bone is acceptable for hunting; metal is preferred when the
  wildlife is dangerous, because the crossbow is a hammer in melee.
  Migrant hunters arrive with one; a fort without one builds it at
  a bowyer's workshop (wood or bone) or a forge (metal).
- Quiver: one. Made at a leather works. A hunter without a quiver
  cannot carry bolts properly.
- Bolts: a stock floor, not a single stack. The harness keeps a
  minimum bolt count in the ammunition stockpile and refuses to
  start a hunt below it, because a hunter that runs out of bolts
  gets a job cancellation and flees, and a hunter with no bolts
  chases its prey and clubs it. The floor is set from the hunter
  count and the bolt stack sizes (wood and metal 25 per stack, bone
  5 per stack): enough stacks that one hunt cannot empty the pile.
- Leather armor if the fort has it, and a backpack. A waterskin is
  not part of the kit.

If the crossbow or the quiver is missing, the harness queues its
production through the normal job machinery with the have/need check
naming the material and the count, and hunting waits. If bolts are
below the floor, the harness queues bolt production first (section 8).
The equipment check is a precondition, not a suggestion: a hunter is
never sent out unequipped.

There is a known bug the harness must work around: a hunter's weapons
might not be assigned properly, and even with a quiver and assigned
ammo the dwarf may not have the right bow. The wiki's fix is to
disable the hunting labor so the dwarf stockpiles the equipment, then
re-enable hunting. The harness does exactly that when a hunter is
observed hunting without a crossbow or without bolts: disable, wait
for the equipment to be stockpiled, re-enable, and verify the kit is
held before the next hunt.

### 5.3 The axe-hunter variant

The food guide names a variant: a dwarf with both woodcutting and
hunting. An axe-hunter will not catch fast creatures, needs no ammo,
and has a better chance against a predator, because the axe is a real
melee weapon and the crossbow is only a hammer. The harness offers
this as a named option when bolts are short or the game is
dangerous, and records which variant the fort is running. It is not
the default: an axe-hunter is a woodcutter that hunts, and the fort
still needs wood cut.

## 6. Hunting zones and where hunters go

The honest finding first: there is no hunting zone in DF. Fishing has
zones; hunting does not. A hunter picks a mark at random anywhere on
the map, on the surface or in a cavern layer, and walks to it. The
harness cannot draw a box and keep the hunter inside it. Everything
in this section is about what the harness can control instead.

### 6.1 What the harness controls

- Whether hunting is on at all, per hunter, through `labor_toggle`.
  This is the only range control the game gives, and it is coarse:
  disabling the labor does not stop the current hunt.
- When hunting starts and stops, by the clock and by the threat
  state. Hunting is enabled when the fort has food pressure, the
  wildlife is safe game, and no hostile is near. It is disabled when
  a siege or ambush is announced, when a hostile is within the threat
  radius, or when the food floor is met with a margin. The disable
  is recorded with its reason, so the agent knows why hunting
  stopped.
- Which layer the hunter works. Dwarves can hunt on the surface and
  on each cavern layer, and the wildlife on each layer is different.
  The harness reads `wildlife_by_race` per collect and knows which
  layer's game is out, because each wild animal carries its position
  including z. A cavern hunt is only offered when the cavern is
  known and the game there is safe; the harness never sends a hunter
  into an unmapped cavern.
- The hunter's exposure, through `dist_nearest_citizen`. The units
  observation already computes how far each wild animal is from the
  nearest citizen. The harness watches the hunter's own distance
  from the fort entrance the same way, and the recall rule in section
  10 fires on it.

### 6.2 What the harness does not have yet

Burrows are the mechanism that would give hunting a real range: a
burrow around the safe area, with the hunter restricted to it, would
keep the hunter near the walls. Burrows are not implemented in the
harness (GOAL.md records the open investigation: inserting a burrow
struct directly into `df.global.ui.burrows` plus a civilian-alert
assignment). Until that investigation lands, the plan does not claim
a hunting zone exists. If the burrow route is proven, the hunting
range becomes a burrow, and this section is rewritten. Until then,
the labor toggle plus the recall rules are the whole of the control,
and the doc says so plainly.

### 6.3 Where the hunter sleeps

A dwarf with the hunting labor enabled sleeps outside, which causes
unhappy thoughts, and can be slaughtered by a wandering wolf pack
while sleeping. The harness watches the hunter's stress and mood
and rotates the hunter off the job before the unhappiness becomes a
problem: hunting is a shift, not a life sentence. When the labor is
toggled off, the dwarf sleeps in its bedroom properly again. The
rotation is recorded in the journal, so the diary can tell the story
of who hunted and when.

## 7. What to hunt and what to leave alone

### 7.1 The problem: the hunter picks, not the harness

The hunter picks a mark at random and pursues it. The harness cannot
veto a single mark. It can only decide, from what is on the map, whether
hunting is safe to have on at all, and whether the hunter on duty is
good enough for what is out there. That makes the game table the central
piece of this plan: the harness must know, for each race it can see,
whether it is food, a fight, or a funeral.

### 7.2 The danger classes

From the wiki, the classes are:

- Safe game: small and medium herbivores and grazers. Marmots,
  cavies, and similar small animals are safe but barely worth it (a
  skull only, or nothing). Deer-sized game is the sweet spot: safe
  for a competent hunter, several meat stacks, organs, fat, hide,
  and bones.
- Fast game: badgers and other swift animals. Safe, but an unskilled
  hunter cannot catch them at all: the hunter crawls in ambush mode
  and the prey outruns it. Fast game is only offered when the hunter's
  ambusher skill is high enough, and the harness says so.
- Dangerous game: lions, wolves in packs, giant eagles, elephants
  and giant elephants, and anything the wiki calls out as a hunter
  killer. A hunter can be maimed hunting lions and killed attacking
  herds of giant elephants. A wolf pack can slaughter a sleeping
  hunter. When dangerous game is on the map, hunting is disabled
  unless the hunter is seasoned, well-equipped, and preferably not
  alone. The harness never enables hunting on a novice when a lion
  is on the map.
- Undead and aggressive animals: they come to the hunter, so agility
  is not needed to catch them, but crossbow bolts and piercing
  weapons are next to useless against them, and even minor zombies
  have been known to shatter bone through adamantine and steel.
  Hunting undead is a military job, not a hunter's job, and only
  when the corpse can be mangled so it cannot reanimate. The
  harness refuses hunting when the wildlife includes undead, and
  says why.
- Water creatures: hunters shoot carp and other water creatures and
  never recover the dead fish. Fish in a river are not game, they
  are wasted bolts. The harness does not count water creatures as
  huntable game.

### 7.3 The game table

The harness needs a table keyed by race: size class, danger class,
expected yield class, and whether it is huntable at all. The table is
built from the creature raws, which carry body size and the tokens
that decide behavior, the same way the catalog is built from the live
runtime enums rather than from a hand-written list. The table is
data, not code, and it is versioned with the harness. Building it is
a phase 1 task, and its source is marked UNVERIFIED until the table
is checked against the live game: the harness must confirm, on the
real fort, that the races it calls safe are the races the hunters
actually kill without injury, and that the races it calls dangerous
are the ones the game spawns in the dangerous slots.

The table is also how the harness answers the agent's question "what
is out there" without dumping the wildlife list: the snapshot carries
the top game on the map ("3 deer, 20 tiles out, safe for our hunter")
and the top danger ("1 lion, 45 tiles out, hunting is off while it
is here").

### 7.4 The extinction rule

Hunting has a long-run cost the harness must track. If the hunters
kill every member of a group, that creature's population falls; if
at least one member survives to leave the map, the population does
not decrease. The harness watches `wildlife_by_race` over time in
the store's trends, and when a race's count falls to one group or
the counts stop appearing, it throttles hunting for that race: the
hunter is pulled off, or hunting is disabled until the counts
recover. The alternative the wiki names, capturing and breeding wild
animals, is out of scope for this plan: it belongs to the animal
husbandry work, and the harness says so rather than pretending
hunting alone is sustainable forever.

## 8. Ammunition production and stock

### 8.1 The bolt economy

Bolts are the consumable hunting runs on, and the harness treats them
as a stock with a floor, the same way it treats drink and food. The
facts, from the wiki:

- Bolts are made at a craftsdwarf's workshop or at a forge, from
  wood, bone, or metal. Crossbows are made at a bowyer's workshop
  (wood or bone) or a forge (metal). Quivers are made at a leather
  works.
- Wood and metal bolts come in stacks of 25; bone bolts come in
  stacks of 5. Bone bolts are better than wooden ones and inferior
  to metal ones; the material matters in combat, because bolts are
  affected by the density of the material and by sharpness, and ammo
  of equal or lesser metal can take over four times as many shots
  to kill.
- A hunter picks up bolts automatically from the ammunition
  stockpile when it goes hunting. The stockpile must exist and must
  hold bolts, or the hunter goes out with an empty quiver.

### 8.2 The loop that makes hunting pay for its own bolts

Butchering a hunted animal produces bones. Bones become bone bolts at
a craftsdwarf's workshop, and bone crossbows at a bowyer's workshop.
So a hunting fort has a closed loop: hunt, butcher, carve bone bolts,
hunt again. The harness tracks the loop as a stock flow: bolts out per
hunt, bones in per kill, bolts back per bone stack. When the loop is
closed, hunting is self-sustaining on ammunition. When it is not, the
harness queues wood or metal bolt production and says which material
it chose and why (wood is free but weak, metal is strong but costs
bars the fort may need for armor).

### 8.3 The stock floor and the refusal

The harness keeps a bolt floor in the ammunition stockpile, set from
the hunter count and the stack sizes. Hunting is refused below the
floor, with the reason named ("12 bolts in stock, floor is 50, queue
bolt production first"). The floor is a number in the snapshot, not a
feeling, and the agent sees it next to the food floor. Bolt production
is queued through the normal job machinery with the have/need check
naming the material: bone from the refuse pile, wood from the wood
stockpile, metal from the bars. If no material exists for any bolt
type, the harness says so and hunting stays off: a hunter without
bolts is a dwarf clubbing an animal with a crossbow.

### 8.4 The ammunition stockpile

The ammunition stockpile sits near the fort entrance, placed by the
scored site selection work, so a hunter arms itself on the way out
and the bolts are not a long haul. It holds bolts and nothing else
the hunter does not need. The harness verifies the stockpile exists
before the first hunt, the same way it verifies the butcher's shop
and the refuse pile.

## 9. Butchering returns and the kitchen chain

### 9.1 The butcher's shop

The butcher's shop is built from any non-economic building material
and operated by any dwarf with the butchery labor. Its jobs:

- Butcher an animal: renders a dead animal into meat, fat, skin,
  bones, skulls, and the rest. The animal must be in a stockpile
  anywhere, or lying on the ground within 20 tiles of the edge of
  the shop on the same z-level. The shop scans about 20 tiles in
  every direction for butcherable corpses; further away, and the
  corpse is never tasked.
- Slaughter a tame animal: instantaneous once the animal is led to
  the shop. This is the livestock half of the meat industry, not
  the hunting half, and the plan does not confuse the two: hunted
  animals are butchered, tame animals are slaughtered, and the
  harness refuses to slaughter a pet.
- Catch live land animal and extract from land animal: the trapper's
  jobs, not the hunter's. They belong to the trapping work.

Butchering is not instantaneous for a hunted corpse: it takes time,
and in a fort with few workers a corpse can rot before anyone
processes it. The butcher's skill affects only the time taken, not
the amount produced or the quality.

### 9.2 What a kill yields

A butchered animal yields one skull (hydras produce seven), and may
also produce raw hide, a number of meat and prepared-organ pieces,
bones, and, depending on the animal, horns, hooves, fat, and
cartilage. Animal size and chance decide the exact yield. Very small
animals produce only a skull, and a hunter-killed one is not
butchered at all.

Each product has a next step, and the harness checks the whole chain
is staffed before hunting starts, because a kill with nowhere to go
is waste:

| Product | Next step | Workshop and labor |
| --- | --- | --- |
| Meat and prepared organs | Eaten raw, or cooked into meals | Kitchen, cook |
| Fat | Rendered to tallow, then soap or cooked | Kitchen, then soap shop |
| Raw hide | Tanned to leather | Tanner's shop, tanner |
| Bones | Bone bolts, bone crafts, bone armor, decorations | Craftsdwarf's workshop, bone carver |
| Skull | Totems for trade | Craftsdwarf's workshop |
| Horns, hooves, teeth, ivory | Crafts and decorations | Craftsdwarf's workshop |
| Hair | Spun into thread for suturing | Farmer's workshop, spinner |
| Wool | Spun into yarn (sheep, llama, alpaca only) | Farmer's workshop |
| Cartilage, nervous tissue | No use; dumped | Refuse pile |

Fat deserves a line of its own: tallow is the input to soap, and soap
is what keeps the hospital from infecting wounds and lets dwarves
clean themselves. A hunting fort that renders its fat is a fort with
soap. A hunting fort that cooks all its tallow has traded its hospital
for a meal. The harness keeps a soap reserve and refuses to cook
tallow below it, the same way it keeps a food floor.

### 9.3 The refuse chain and rot

Hunting produces corpses, and corpses rot. The harness's refuse rules,
from the wiki:

- The fort's standing orders must gather refuse from outside, or the
  hunter's accidental kills and any corpse the hunter does not carry
  home are left to rot on the map. The harness sets and verifies
  this order when hunting is enabled, and says so in the run log.
- A refuse stockpile that accepts corpses and body parts must sit
  close to the butcher's shop, so the shop's 20-tile scan finds the
  corpses. The stockpile is placed by the scored site selection
  work, adjacent to the shop.
- Butchered products must be hauled into stockpiles promptly or the
  food rots and miasma spreads. A butcher's shop that clutters with
  meat, bones, fat, and organs will rot the whole pile if there are
  not enough haulers. The harness watches the shop's clutter through
  the items observation and reports it; a cluttered shop is a reason
  to pause hunting, not to keep killing.
- Corpses left to rot become skeletons. Only wild-animal skeletons
  can be processed at the butcher's shop, and they give bone, skull,
  hoof, and horn only: no meat, no fat, no skin. A skeleton is a
  salvage, not a meal.
- Partial and mutilated corpses do not give the full set: fewer
  bones, missing organs. A military hunt that chops an animal into
  several pieces needs each piece butchered separately, which costs
  more stockpile space for the same total yield. The harness says so
  when it recommends a military hunt over a civilian one.
- Tame animals that die for any reason are unbutcherable (Bug 1275).
  The harness never counts a dead pet or dead livestock as food.

### 9.4 The kitchen

Meat and organs are eaten raw or cooked into meals at the kitchen.
Prepared meals are the highest-value food the fort makes and the best
trade good it has, so the kitchen is where hunting meets trading:
surplus meat above the food floor becomes meals, and meals become
trade goods by the trading plan's pipeline. The harness does not let
the kitchen cook seeds, and it does not let the kitchen cook the
fort's last meat. The cook's skill affects speed; the meal's value
is the sum of its ingredients multiplied by the number of
ingredients, so a lavish meal from hunted meat is worth far more
than the meat alone.

## 10. Hunter safety

Hunting is the most exposed civilian job in the fort, and the safety
rules are the part of this plan the harness enforces hardest. A dead
hunter is a dead dwarf, and the scoring system counts it.

### 10.1 The dangers, from the wiki

- Sleeping outside: a hunter sleeps wherever it falls, not in its
  bedroom, and can be slaughtered by a wandering wolf pack while
  snoozing. The harness rotates hunters and watches stress.
- Dangerous game: lions maim hunters, herds of giant elephants kill
  them, giant eagles are a match for a seasoned hunter and a death
  sentence for a novice.
- Sieges and ambushes: hunters are usually the first to die in a
  siege or ambush, because they are already outside the walls when
  it arrives.
- The hunt that will not stop: disabling the labor does not end the
  current hunt, so a hunter can walk into the next spawn after the
  fort has decided hunting is over.
- No bolts: a hunter that runs out of bolts flees, which is safe,
  but a hunter with no bolts at all chases and clubs, which is not.
- Necromancer hunters: a necromancer hunter will sometimes raise
  the corpses of its prey, which then attack it. The harness checks
  whether the assigned hunter is a necromancer before enabling the
  labor, and refuses if so, with the reason named. UNVERIFIED: the
  exact field the harness reads for this; phase 1 probes it.
- Equipment bugs: a hunter's weapons might not be assigned properly.
  The disable, stockpile, re-enable cycle in 5.2 is the workaround.

### 10.2 The recall rules

The harness pulls the hunter back, by disabling the labor and by
naming the reason, when any of these fires:

- A hostile is within the threat radius of the hunter's position,
  or a siege or ambush is announced. This is the same threat radius
  the site selection work uses for buildings, and the same
  `dist_nearest_citizen` read the units observation already
  computes.
- The hunter is wounded. A wounded hunter is pulled off immediately,
  whatever it was chasing.
- The hunter's stress category rises or its mood turns. A hunter
  that sleeps outside too long is rotated off before the
  unhappiness becomes a spiral.
- The bolt stock hits the floor mid-hunt. The hunter is already
  fleeing at that point; the harness disables the labor so it does
  not go back out.
- The food floor is met with a margin. Hunting stops because it is
  done, not because something went wrong, and the harness says so.

The recall is recorded in the journal with the reason and the
hunter's state. The diary can then tell the story: who hunted, what
they killed, and why they came home.

### 10.3 What the harness never does

- It never enables hunting on a dwarf without the equipment check
  in 5.2 passing.
- It never enables hunting when dangerous game is on the map and the
  hunter is a novice.
- It never enables hunting during a siege, an ambush, or an invasion
  alert.
- It never sends a hunter into an unmapped cavern layer.
- It never treats disabling the labor as a recall for the current
  hunt. The harness says "hunting stops after this hunt" and means
  it.

## 11. Hunting in the fort's food economy, season by season

Hunting is scored against the season it happens in, because the
fort's other food sources move with the seasons.

- Spring: the farm is starting, the elven caravan is coming, and
  the fort is at its most food-fragile after winter. Hunting is
  ranked highest in spring when the farm is not yet producing,
  because a hunter can add meat in days while a crop takes a season.
  The elven caravan brings no meat the fort can use (elves refuse
  animal products), so spring hunting is not competing with trade.
- Summer: the farm is producing and the human caravan arrives with
  food, leather, and domestic animals. Hunting is a supplement in
  summer, ranked below the farm, and it is the season to build the
  bolt stock and the butcher chain for autumn.
- Autumn: the dwarven caravan arrives, the farm is harvested, and
  the fort stocks up for winter. Hunting in autumn is about the
  butcher chain: meat for the winter stockpile, fat for soap, bones
  for bolts. The harness ranks hunting by the winter stockpile gap,
  not by the day's hunger.
- Winter: no caravans come in winter. The farm still produces
  underground, and hunting continues if game is present and the
  weather and the wildlife allow it. Winter hunting is the most
  exposed hunting of the year, and the harness weighs the cold and
  the dark honestly: a winter hunt is offered only when the food
  floor is genuinely at risk.

Across all seasons, the extinction rule in 7.4 applies: the harness
watches the wildlife counts and throttles hunting before a race is
hunted out. A fort that eats its biome bare in year one has no
hunting in year two, and the harness says so in the season summary.

## 12. The harness's role at each step

### 12.1 The decision the harness makes

Each tick, the harness answers five questions from fresh collects,
and the agent sees the answers, not the raw data:

1. Does the fort need meat? Food against the per-dwarf floor and
   the season's consumption trend.
2. Is there game worth hunting? The wildlife list through the game
   table: race, distance, danger class, yield class.
3. Is there a hunter ready? Skill ranking, equipment check, bolt
   stock against the floor, butcher and tanner staffed.
4. Is it safe? Hostiles, siege state, dangerous game on the map,
   the hunter's wounds and stress.
5. Is the chain ready? Butcher's shop built, refuse pile close,
   standing orders gathering refuse from outside, kitchen staffed.

If all five pass, the snapshot carries one suggested action: enable
hunting on the named dwarf, with a one-line why ("Urist has
ambusher skill, 3 deer 20 tiles out, bolts 80, butcher ready").
If any fails, the snapshot carries the blocker with its reason
("hunting is off: 1 lion on the map, hunter is a novice"), and the
agent is not asked to decide.

### 12.2 The agent's decision surface

The agent never sees raw wildlife lists, raw bolt counts, or raw
skill tables. It sees, per tick: the top game on the map with a
one-line why, the top danger with a one-line why, the hunter on
duty or the named candidate, the bolt stock against its floor, and
one suggested action for the most urgent hunting problem (equip
the hunter, make bolts, build the butcher's shop, pull the hunter
back). When a hunt ends, the agent sees the result: what was
killed, what it yielded, what is in the stockpile now. The harness
owns the equipment check, the bolt floor, the safety watch, and
the bookkeeping. That is the standing cognitive load rule,
applied to hunting.

### 12.3 What is recorded

Every hunt is recorded in the journal: the hunter, the prey race,
the yield (meat, organs, fat, hide, bones, skull), the bolts spent,
and the hunter's state on return. That record is what the fortress
history reads (one line per season: how many hunts, what they
brought in), what the scoring system reads (a first-hunt milestone,
once hunting is detectable), and what the diary reads (the story
of the hunt). A hunt that is not recorded is a hunt that did not
happen, as far as the fort's memory is concerned.

## 13. Implementation phases, in order

Each phase is done only when its live-verification bar is met against
the real game. A phase is not done because the code is written.

### Phase 1: The game table and the hunt decision

- Game table keyed by race: size class, danger class, yield class,
  huntable or not, built from the creature raws the way the catalog
  is built from the live runtime enums. Seeded with the races the
  wiki names, checked against the live game.
- Hunt decision in the planner: the five questions from 12.1,
  computed from fresh collects, with the food floor, the wildlife
  list through the game table, the hunter ranking, the equipment
  check, and the safety watch.
- Live bar: on the main fort, the decision names the real game on
  the map (verified against the units observation), names the real
  hunter candidate (verified against the citizens list), and refuses
  with a true reason when a precondition fails. No decision is wrong
  by inspection.

### Phase 2: Hunter assignment and equipment

- Hunter assignment through `labor_toggle`, with the equipment
  check from 5.2 as a precondition: crossbow, quiver, bolts above
  the floor, or the production jobs queued first.
- The disable, stockpile, re-enable cycle for the equipment bug,
  triggered when a hunter is observed hunting without a crossbow
  or without bolts.
- Live bar: a hunter is enabled on the scratch fort, the labor is
  read back in the units observation, the hunter picks up a
  crossbow, a quiver, and bolts from the ammunition stockpile, and
  a Hunt job appears in the hunter's job field. The equipment bug
  cycle is exercised once and logged.

### Phase 3: The butcher chain

- Composed task "have the butcher chain ready": butcher's shop,
  tanner's shop, refuse stockpile accepting corpses within 20
  tiles of the shop, standing orders gathering refuse from
  outside, kitchen staffed. Sites placed by the scored site
  selection work.
- Live bar: on the scratch fort, a hunted corpse is carried to the
  shop, butchered, and the products land in the right stockpiles
  (meat in food, hide to the tanner, bones to the refuse pile for
  carving), verified by the stocks read before and after. A corpse
  left further than 20 tiles from the shop is never tasked, which
  proves the radius rule is real.

### Phase 4: Ammunition

- Bolt floor in the ammunition stockpile, bolt production through
  the normal job machinery (bone at the craftsdwarf's workshop,
  wood and metal at the workshop or forge), and the closed loop
  in 8.2 tracked as a stock flow.
- Live bar: the bolt stock is read from the live game before and
  after a hunt, the loop shows bones in and bolts out, and hunting
  is refused below the floor with the reason named. A hunt that
  empties the quiver ends with the hunter fleeing on the job
  cancellation, which the run log records.

### Phase 5: Safety, recall, and recording

- The recall rules from 10.2, watched every tick: hostiles near
  the hunter, siege or ambush announced, hunter wounded, stress
  rising, bolt floor hit.
- Journal records for every hunt (hunter, prey, yield, bolts,
  hunter state) and the first-hunt milestone in the scoring
  system, detectable from the journal.
- Live bar: on the scratch fort, a hostile near the hunter triggers
  the recall and the labor is read back as disabled; a hunt
  completes and the journal holds the full record, verified by
  reading it back; the scoring system reports the first-hunt
  milestone.

### Phase 6: Military hunting (optional, after phase 5)

- Military hunt as a named option: a crossbow squad ordered to
  kill wild animals, with the mangled-corpse cost stated (pieces
  butchered separately, more stockpile space, same total yield)
  and the nearest-creature risk stated (soldiers attack whatever
  is closest, not just the target).
- Live bar: a squad hunt on the scratch fort kills the named herd,
  the corpses are butchered piece by piece, and no tame animal or
  citizen is harmed. If the bar cannot be met, this phase is cut
  and the doc says so: civilian hunting is the plan, military
  hunting is a bonus.

### Phase 7: Seasons and extinction

- The seasonal ranking from section 11, and the extinction watch:
  wildlife counts trended in the store, hunting throttled when a
  race's counts fall.
- Live bar: a full in-game year on the scratch fort with hunting
  enabled shows the seasonal ranking changing with the food trend,
  and a race hunted to one group triggers the throttle and the
  record of why. This needs a year of game time, so it is the last
  thing proven.

## 14. Open questions

### 14.1 The game table's source

The table is built from the creature raws, but the exact read the
harness uses is UNVERIFIED: whether body size and the behavior
tokens are readable from the game state the way the runtime enums
are, or whether the table must be built once from the raws on disk
and shipped as data. Phase 1 probes it. If the raws on disk are the
source, the table is versioned with the DF version and the doc says
so.

### 14.2 Reading the bolt stock

Whether the ammunition stockpile's bolt count is readable from the
stocks section the way food and drink are is UNVERIFIED. The stocks
section counts items by type; AMMO is an item type in the runtime
enum, so the read should exist, but phase 4 verifies it live before
the floor depends on it. If the count is not readable, the floor is
tracked from production and consumption records instead, and the doc
says which.

### 14.3 The hunter's target and the Hunt job

Whether the hunter's current mark is readable from the game state
is UNVERIFIED. The hunter's job field should show the Hunt job type,
which is in the runtime enum, and the job carries a position; phase
2 checks whether that position is the prey. If the mark is not
readable, the harness watches the hunter's position and the wildlife
positions and infers the hunt from proximity, and the doc says so.

### 14.4 Necromancer check

Whether the harness can read that a dwarf is a necromancer before
assigning the hunting labor is UNVERIFIED. Phase 1 probes the
citizen record for the field. If no field is readable, the refusal
is based on what the harness can see (the dwarf's history, if the
journal holds it), and the doc says which.

### 14.5 Burrows and hunting range

Whether a burrow can restrict a hunter's range is UNVERIFIED, and
burrows themselves are not implemented in the harness. The burrow
investigation in GOAL.md is the prerequisite; until it lands, the
labor toggle plus the recall rules are the whole of the control,
and section 6 says so.

### 14.6 Other open questions

- Cage traps as the alternative to hunting: the meat industry page
  describes trapping as a way to catch animals for breeding or
  slaughter. Whether trapping belongs in this plan or in the animal
  husbandry work is undecided; the plan notes it and does not claim
  it.
- Vermin hunting: the HuntVermin job type exists in the runtime
  enum, but vermin are not food in the hunting sense. Out of scope.
- The exact bolt spend per hunt: the harness reads it live from
  the stock flow in phase 4; no fixed number is assumed.

## 15. Refusals

The harness never does any of the following, whatever the agent asks:

- Enable hunting on a dwarf that fails the equipment check.
- Enable hunting on a novice when dangerous game is on the map.
- Enable hunting during a siege, an ambush, or an invasion alert.
- Send a hunter into an unmapped cavern layer.
- Treat disabling the labor as a recall for the current hunt.
- Count a dead tame animal as food, or slaughter a pet.
- Hunt a race the game table calls unhuntable, or hunt when the
  bolt stock is below the floor.
- Claim a hunting zone exists. There is none, and the harness says
  so until the burrow route is proven.
- Fake a food shortage by forbidding stocks to change any
  threshold. The food floor is read from the real stocks.

## 16. Sources

Wiki pages, read from the local DF wiki index
(`~/workspace/df-wiki-export/dfq.py`) on 2026-11-27:

- Ambusher (2,064 words): the hunting labor, the ambusher skill,
  equipment, mark selection, the kill and the carry home, caveats,
  the equipment bug, the hunt that will not stop.
- Hunting animal (short page): trainable hunting animals, the
  bonuses training gives, assignment to hunters.
- Ammunition (short page): bolt, arrow, blowdart table; bolts
  craftable from metal, wood, bone; material effectiveness.
- Crossbow (1,496 words, via search snippets): migrant hunters
  arrive equipped; hunters pick up crossbow, quiver, and bolts
  from the ammunition stockpile.
- Crossbow/raw: crossbow size 400, material size 3, melee attack
  as a hammer, shoot force 1000.
- Advanced marksdwarf training guide (3,149 words, via search):
  wood and metal bolts in stacks of 25, bone bolts in stacks of 5;
  crossbows from wood or bone at a bowyer's workshop, metal at a
  forge.
- Butcher's shop: construction, the 20-tile butchering radius,
  the product table (meat, fat, skin, bones, skull, horn, wool,
  hair), hauling and rotting, the quantum stockpile note.
- Meat industry (6,187 words): acquisition by embark, trading,
  hunting, military, trapping, breeding; pastures and pens; the
  processing chain; secondary products (eggs, milk, wool);
  automation and the DFHack autobutcher note.
- Food guide (3,695 words): the seven ways to get food, farming
  ranked first, hunting ranked as erratic supplementary, the
  hunting tips (sleep outside, no bolts, tanner and butcher first,
  axe-hunter, soldiers to hunt, hunters first to die in a siege).
- Bowyer's workshop: wood and bone crossbows only; metal crossbows
  at a forge; bolts made elsewhere; quivers at a leather works.
- Bedroom (844 words, via search): dwarves with the hunting labor
  enabled sleep anywhere.

Harness sources, read from the repo on 2026-11-27:

- `src/dfagent_harness/actions.py`: `labor_toggle`, verified,
  with read-back postcondition; no hunt action in the catalog.
- `src/dfagent_harness/lua/units.lua`: wildlife compact records
  (id, name, race, position), `dist_nearest_citizen`,
  `wildlife_by_race` counts; no size or danger field.
- `src/dfagent_harness/materials.py`: have/need machinery.
- `src/dfagent_harness/diagnose.py`: "gather plants or butcher an
  animal" as a food-shortage fix, with no task behind it.
- `docs/PLANNER.md`: fishing and hunting not implemented.
- `docs/TRADING.md`: the per-dwarf food floor (5 food per dwarf),
  the dog as a hunting and war animal (pet value 30).
- `docs/FARMING.md`: farming as the primary food source.
- `tests/fixtures/runtime-enums-0.47.05-r8.json`: job types Hunt,
  ButcherAnimal, SlaughterAnimal, HuntVermin; labors HUNT, BUTCHER,
  TANNER; workshops Bowyers, Craftsdwarfs, Butchers, Tanners,
  Leatherworks, Farmers, Kitchen, Still; item types AMMO, QUIVER,
  WEAPON, MEAT, SKIN_TANNED.

## 16. Model presentation

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
verifies them against the live assembler before commit. The
numbers are small because the section is an index: it names counts
and exceptions, and the detail lives behind queries.

### 16.1 Snapshot: the Hunting section

The per-tick snapshot gains a short Hunting section, built from
the fresh collect, in plain words. Three lines, in this shape:

```
Hunting: 0 hunters. Bolts 0, quivers 0. Butcher's shop: none.
Wildlife: 3 deer (nearest 18 tiles), 1 fox (nearest 42 tiles).
```

What is in it, and what is not:

- **Line 1, hunters and kit.** How many citizens have the HUNT
  labor enabled, how many bolts and quivers are in stock, and
  whether a butcher's shop exists. The labor machinery is
  verified live (`labor_toggle` with read-back), and HUNT,
  BUTCHER, and TANNER are real enum names, so the line names
  real state. The common case on a fort with no hunting yet is
  the example above: three short absences, not silence. A
  missing butcher's shop is an exception, not a blank.
- **Line 2, wildlife.** What wild animals are out there, by
  race, capped at 4 races, with the nearest distance per race.
  The units observation sees wildlife live today (id, name,
  race, position, kind, role, `dist_nearest_citizen`,
  `wildlife_by_race`), so this line is built from a fresh
  collect. What the collect cannot see is the animal's size,
  danger, or health: the compact record carries no size and no
  hostility flag. Race is the only signal, so the line names
  races and distances, never a danger rating. Danger and yield
  come from a game table keyed by race, built from the creature
  raws (§7.3, §10.2), and that table is behind the query route,
  not in the snapshot.
- **Line 3, only when something is wrong.** A third line appears
  only as an exception: a hunter with no bolts, a hunter
  outside the walls with a hostile near, a butcher's shop with
  a corpse rotting unbutchered. When nothing is wrong, there is
  no third line. A quiet fort costs two lines.
- **Diffs, not repeats.** When nothing in the section changed
  since the last tick, the assembler prints the short form
  ("hunting: unchanged"), the same way the Buildings section
  already does. The section costs its full price only on ticks
  when hunting state actually moves.

**Token cost.** At 7 dwarves, the section as written above is
124 characters: about 41 tokens by the accountant's
3-chars-per-token rate, 31 on the wire. At 50 dwarves, with
more hunters and more wildlife races, it is about 300
characters: about 100 tokens by the accountant, 75 on the wire.
The cost grows by about 35 tokens from 7 dwarves to 50, because
the section is capped: 4 wildlife races maximum, 1 hunter
clause, 1 kit clause. It does not grow with population, with
the number of wild animals on the map, or with the number of
bolts in stock. If a future change makes it grow with any of
those, the change is refused until the section is capped again.

### 16.2 Query route: GET /v1/hunting (UNVERIFIED)

GET /v1/hunting returns the full detail, read from the fresh
collect, not from a cache. This route does not exist yet; it is
part of the implementation phases in §13, and the snapshot
section above is written against it as a design target, not
against a live route.

- Wildlife: every wild animal with id, race, position,
  distance to the nearest citizen, and the danger and yield
  from the race table (§7.3).
- Hunters: each citizen with the HUNT labor, their marksdwarf
  skill, their weapon, and their current job.
- Equipment: bolts, quivers, bows, and crossbows in stock, by
  material, with the have/need check for a hunt (§5).
- Butchering: the butcher's shop state, corpses waiting, and
  the meat, bones, and skins each corpse yields (§9).
- Zones: the hunting zones from §6, with their bounds and
  whether a hunter is inside one.

The snapshot carries the summary and the ids; the route carries
the detail. The agent asks the route when it needs to choose
what to hunt or whether hunting is worth it (§4), never as a
matter of routine. Until the route exists, the same detail is
behind GET /v1/units (wildlife is in the units collect) and
GET /v1/stocks (bolts and quivers are stocks), which do exist
today.

### 16.3 Briefing: what arrives just in time

Hunting has no standing briefing. Two events carry one, both
from the existing briefing system (briefings.py), each a few
hundred tokens at most, each fired once when the event starts:

- **Food short, game near.** Trigger: food below the floor and
  huntable wildlife within range. Cost: about 70 tokens by the
  accountant (UNVERIFIED: the briefing text has not been
  measured against the live briefing system). It covers that
  food is short, what game is near, and that hunting is one
  way to close the gap. It leaves the worth-it judgement to
  §4 and the equipment check to §5.
- **Hunter in danger.** Trigger: a hunter outside the walls
  with a hostile near. Cost: about 55 tokens. It covers the
  hunter, the hostile, and the distance. It leaves the recall
  decision to §10.

No other hunting event briefs the model. A successful hunt, a
butchering, or a bolt stock hitting zero are attention entries
and opportunities entries, not briefings. A briefing is for
something the model needs to understand right now, not for
something it can read in the snapshot. Note the gap §3 records:
a successful hunt is not recorded anywhere yet, and there is no
hunting milestone or hunting event in the events system. Phase 5
adds both; until then no briefing can fire on a hunt.

### 16.4 Opportunities: at most 3, facts only

The opportunities section carries at most 3 hunting entries,
each one line: facts plus a query route, never a suggestion, never
a pause. Ignoring one costs nothing. Examples of what qualifies:

- "Hunting: 3 deer 18 tiles out, 0 hunters. Query /v1/hunting
  for the wildlife."
- "Bolts 0, bowyer's workshop idle. Query /v1/hunting for the
  equipment."
- "Corpse waiting at the butcher's shop. Query /v1/hunting for
  the butchering."

An opportunities entry fires only when the fact is actionable
and the snapshot alone does not already say it. A hunter
already out hunting is not an opportunity; it is the snapshot
doing its job. The entry never names the action to take and
never carries a cost estimate. The model decides.

### 16.5 What the system deliberately does NOT push, and why

- **Every wild animal by name.** The snapshot names 4 race
  counts with nearest distances; the full list is behind
  GET /v1/hunting. A list of every animal every tick is a
  dump, and the model cannot act on the 12th deer anyway.
- **Danger ratings in the snapshot.** The collect carries no
  size and no hostility flag, so the snapshot cannot rate
  danger. The race table behind the query route is where
  danger lives. Pushing a rating the collect cannot support
  would be a guess.
- **The whole ammunition ledger.** The snapshot says how many
  bolts and quivers are in stock. The per-material breakdown
  and the production queue are behind the route. A ledger dump
  would grow with every bolt the fort makes.
- **Hunting as a suggestion.** The snapshot never says "hunt
  the deer". Whether hunting is worth it is §4, and the model
  asks for the hunting detail when it decides. The presentation
  gives the model what it needs to decide, not a script to
  follow (HARNESS_ROLE.md).
- **Butchering returns as a promise.** The snapshot says a
  corpse is waiting. The meat, bones, and skins it yields are
  behind the route, because the yield depends on the corpse
  and the butcher's skill. The snapshot never states a yield
  before the butchering happens.
