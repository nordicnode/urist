# Animal husbandry

## 1. Purpose

This is the design record for how Urist keeps, breeds, and uses animals.
It covers what the fort does with animals it already owns: pastures,
breeding, milk, wool, eggs, butchering, war and hunting training, pets,
cages, and what happens when the fort cannot feed what it owns.

It does not cover buying and selling. That lives in `docs/TRADING.md`
section 7: what to buy, what the fort must have before buying, and what
to sell. The line between the two docs is the moment of ownership. Before
an animal is owned, the trading plan decides. After it is owned, this plan
decides. The trading plan's rule still binds here: an animal is never
bought into a fort that cannot keep it, and the checks in
`TRADING.md` section 7.2 (pasture exists, nest boxes exist, food for
grazers) are the precondition for everything below.

## 2. How animals work in DF 0.47.05

### 2.1 Tame, stray, and pet are three different things

A tame animal belongs to the fort. A stray tame animal belongs to the
fort and to nobody in particular. A pet is a tame animal a dwarf has
adopted, and it follows its owner. The distinction matters because the
rules change with it: a pet cannot be butchered, chained, or caged, and
its owner gets a happiness bonus while it lives and a negative thought
when it dies, even if it dies peacefully of old age.

Dwarves adopt strays on their own, when idle near one, and the choice is
strongly influenced by the dwarf's personal preferences. Cats are the
exception: they assign themselves to dwarves, and cannot be made
available or unavailable for adoption. A dwarf with a preference for an
animal may adopt it even when it is marked unavailable.

### 2.2 Grazers starve without grass

Tame grazing animals (those with the `[STANDARD_GRAZER]` token) need a
constant source of grass, cave moss, floor fungus, or underlichen. A
grazer with no pasture starves to death. The grazer value is computed
from body size: `GRAZER = 20000 x G x (max size)^-3/4`, where G is the
grazing coefficient (100 by default) and max size is the creature's
maximum size divided by 10. Hunger climbs every tick and the creature
dies at 100,000. A larger grazer value means the animal needs less grass:
a creature with ten times the grazer value needs one tenth the pasture.

Non-grazers do not need a pasture. Dogs and cats need no food at all.
Poultry do not graze. Pigs do not graze. That is why poultry and pigs are
the cheap food animals and cows and yaks are the expensive ones: the
pasture is the real cost, not the animal.

### 2.3 Breeding is proximity, plus one male

Live-bearing animals breed when a male and a female of the same species
are adjacent. Only one breeding male is ever needed. A small percentage
of males will not breed, so keeping one or two spare males is sensible.
There is a per-species population cap, observed around 50, past which
animals will not get pregnant; existing pregnancies still come to term,
and the population can rise again once adults are slaughtered. There is
also a cap on the percentage of juveniles, which bites slow-maturing
species hardest.

Babies born to pastured mothers are automatically assigned to their
mother's pasture. Egg-layers are different: the babies do not inherit
their mother's pasture, and the mother must be left undisturbed with her
eggs or they never hatch.

Animals cannot get pregnant in cages, though they can give birth in a
cage if they were already pregnant.

### 2.4 The fort's animals, right now

Verified live 2026-11-27 against the main fort (Erushtathtat, 125-04-12):
six livestock, all roaming the surface at z180, five levels above the
fort, with no pen/pasture zone verified on the fort. Two dogs, two cats,
one yak, one water buffalo. The yak and the water buffalo are milkable
grazers with no pasture. That is the immediate situation this plan has to
fix first: two grazers living on whatever surface grass they can find,
exposed to anything that walks onto the map.

## 3. What the harness knows today

Almost nothing useful about individual animals. That is the first gap,
and it blocks everything else.

- `GET /v1/units?kind=livestock` works live and returns the fort's tame
  animals. But each record is count-only: id, name, race, position, kind,
  role. No sex, no age, no tame or training level, no owner, no
  pregnancy, no pasture assignment, no cage state. The `role` field in
  that record says `pet` for every tame animal, which is a label for
  "tame", not a statement that the animal is adopted. The only place true
  ownership is read is `probe_unit.lua`, which resolves the owner by a
  reverse scan of `relationship_ids.Pet`, one unit at a time.
- `GET /v1/unit/<id>` (probe_unit) already reads tame state, wounds,
  current job, and owner for one animal. It does not read sex, age,
  training level, pregnancy, pasture assignment, or cage state.
- `create_zone` exists and is verified live (civzone #9, 2026-11-26),
  including the `pen_pasture` kind. A pasture can be placed
  programmatically. Assigning animals to it cannot, yet: no route for
  pasture assignment has been found or verified.
- The job types the work needs all exist in the live runtime enums
  (`tests/fixtures/runtime-enums-0.47.05-r8.json`): SlaughterAnimal,
  GeldAnimal, MilkCreature, ShearCreature, ButcherAnimal, TrainAnimal,
  TameAnimal. No Urist action queues any of them yet. The attention layer
  only names them: "butchering an animal", "milking", "shearing".
- The store keeps no per-animal history. A dwarf's wounds, needs, and
  relations are tracked per day; an animal's life is not tracked at all.
- The trading plan (`docs/TRADING.md` section 7) already decides buying
  and selling, including the Bug 10162 risk that a bought animal never
  becomes usable, and the rule that surplus animals are sold, never the
  breeding pair, never the war dogs, never the milk and wool breeding
  stock.

## 4. Pastures

### 4.1 Sizing

Size the pasture from the animals in it, not from a fixed number. The
wiki's rule of thumb is 20000 / grazer value tiles per animal, and the
table below is taken from that page. The numbers ignore biome regrowth
and are generous on purpose; the harness should treat them as the
starting size and watch the grass, not as a number to argue with.

| Animal | Grazer value | Recommended pasture per animal |
| --- | --- | --- |
| Water buffalo | 356 | 10 x 6 |
| Yak | 465 | 9 x 5 |
| Cow | 522 | 8 x 5 |
| Horse | 598 | 7 x 5 |
| Donkey | 877 | 5 x 5 |
| Llama | 1287 | 4 x 4 |
| Reindeer | 1643 | 5 x 3 |
| Alpaca | 2613 | 4 x 2 |
| Goat | 3364 | 3 x 2 |

Larger animals should get a pasture of their own where possible: a yak
eats grass a goat needed, and the goat starves first. Mixed pastures are
allowed, but the harness sizes them for the hungriest animal in them and
flags the mix.

Sheep do not appear in the table above because the grazer page excerpt
the harness read did not include their row. Do not guess it: read the
row from the wiki before the pasture sizer uses it.

### 4.2 Placement

A pasture is a scored site like any other building or zone, under the
rules in `docs/SITE_SELECTION.md`. Pasture scoring adds one factor the
other kinds do not have: grass. A pasture with no grass is a starvation
box. The harness must check the ground cover before it places one, and
must re-check it as the herd grows.

- Outdoor pastures need grass that regrows. Regrowth depends on the
  biome: "Thick" vegetation regrows fast, "Scarce" may not regrow at
  all, and mountain grass never regrows once eaten. If more than half
  the pasture is bare, it is overloaded. Shrubs and saplings nearby are
  a sign the ground can regrow.
- Indoor pastures are the secure answer once the caverns are breached:
  floor fungus and cave moss grow on soil or muddied stone underground,
  and the animals are behind the fort's walls. Dig a large room in a
  soil layer and wait for the fungus to grow dense, or muddy a stone
  floor by irrigation and wait. Keep dwarven traffic out while it
  grows: trampled fungus is eaten fungus.
- Pandas and their relatives need bamboo, not grass. The harness must
  not put a panda on a grass pasture.
- A pasture can be a 1x1 box with a nest box in it for a single hen.
  Battery farming is a legitimate layout, not a hack.

### 4.3 Overcrowding and fights

An overcrowded pasture makes animals enraged and they start fights, the
same way a stressed dwarf throws a tantrum. The fix is a bigger pasture,
fewer animals, or splitting one large pasture into several smaller ones
with the size matched to the animal. Animals only fight each other when
they share tiles, so splitting works.

### 4.4 Sieges and recall

When a siege or ambush hits, deactivate the pasture before the animals
see the invaders. Animals without a pasture gravitate to a meeting area,
so most of them head for the dining hall. An inactive pasture keeps its
occupant list, so reactivating it sends the dwarves to return the animals
afterwards. This is the harness's recall move, and it must happen before
the animals are in danger, not after: a dwarf sent to re-pasture an
animal that fled will walk straight into the fight.

Pastures placed just outside or inside an entrance also work as an
early-warning system and a distraction for invaders and thieves. The
animals will be hurt or killed doing it, and a tame animal that dies any
way other than slaughter cannot be butchered, so the harness must not
treat sacrificial pastures as free.

## 5. Breeding and population control

### 5.1 Targets

Every species the fort keeps gets a population target, set from what the
fort needs from it. The target is a breeding pair plus working stock,
not a number picked for its own sake:

- Milk or wool line: one male, enough females to keep the farmer's
  workshop busy, and no more. Extra females are production, not pets.
- Meat line: one male, several females, and a steady cull of the young
  once they mature. Young animals do not give full returns when
  butchered, so the cull waits for adulthood except for species that
  take years to mature, where butchering the young is the sensible call.
- War dogs: breeding females stay untrained; a few studs; the pups are
  the next generation of war dogs.
- Cats: zero breeding. See 5.3.

### 5.2 Gelding

Gelding is the population control that does not kill anything. A gelder
castrates a male animal at a farmer's workshop, and it can never breed
again. A skilled gelder is less likely to be injured doing it. Only one
geld job is created per workshop at a time. Egg-laying animals are not
geldable. The harness flags males for gelding when a line is over its
target, and gelds tomcats as a matter of routine.

### 5.3 Catsplosion

Cats are the population problem. They adopt themselves as pets, and a
pet cannot be butchered, chained, or caged. Left alone, the cat
population grows exponentially and the frames per second fall with it.
The controls, in order of preference:

1. Geld the tomcats. One gelder ends a catsplosion.
2. Cage the strays. A caged cat cannot adopt. Cage newborn kittens the
   moment they are born, before they adopt anyone.
3. Butcher the strays that are left, quickly, with the cage next to the
   butcher's shop so the walk is short. A cat can adopt a dwarf on the
   way to the butcher's shop.
4. Sell the caged cats to a caravan. This is the only completely safe
   way to be rid of them, and it is already in the trading plan.

A dead pet gives its owner a negative thought, so every cat removed this
way costs a little happiness. That is the price of not gelding early.

### 5.4 Caging the young

A common strategy is to cage all young animals until they mature. Cages
hold an unlimited number of animals, caged animals do not path (which
helps the frame rate), and it is easier to tell breeding stock from
butcherable stock when they are separated. The rule is: cage the young,
never the grazers. A grazer left in a cage starves, because there is no
grass in a cage.

## 6. Milk, wool, and eggs

### 6.1 Milking

Milk is a renewable food that becomes cheese or goes into prepared
meals. It cannot be drunk as it is. To milk, the fort needs a dwarf
with the milking labor, a farmer's workshop, an empty bucket, and a
mature, non-pet, milkable female. Pets cannot be milked. The milker does
not necessarily pick the closest animal, so the harness keeps milkable
animals pastured or restrained near the workshop, or puts the workshop
in the pasture. Milk is ready again every 20,000 ticks, about 17
in-game days, for every milkable creature.

Milkable animals: alpaca, camel, cow, donkey, goat, horse, kangaroo,
llama, pig, reindeer, sheep, tapir, water buffalo, yak. Pigs are on the
list, which surprises people and is worth knowing: a pig is a milk
animal that needs no pasture.

Let milk accumulate before making cheese, so the cheese comes in stacks
of up to five instead of singles. Keep the milking industry underground:
milk freezes at the same temperature as water, frozen milk cannot be
made into cheese, and a barrel of frozen milk shows up as an empty barrel
at the depot.

### 6.2 Shearing

Only three animals can be sheared: sheep, llamas, and alpacas. Shearing
happens at a farmer's workshop and produces yarn, which becomes cloth.
Wool is one of the three shearable animals' whole point: sheep, llamas,
and alpacas are the fort's clothing supply. A breeding pair of any of
them is worth more than a single animal.

### 6.3 Eggs

Egg production needs almost nothing: a tame adult female, a nest box,
and a food hauler. Hens lay 4 to 15 eggs per clutch; turkeys lay the
most per clutch on average, then ducks, then chickens and guineafowl.
One egg is one meat is one meal, and over time poultry produce far more
food as eggs than the same animal produces as meat when butchered. Eggs
must be cooked into prepared meals before dwarves eat them.

The rules that catch people out:

- A female lays a clutch only if she can claim an open nest box. No
  nest box, no eggs.
- A clutch is fertilized only if a male of the same species was
  adjacent. Fertilized eggs hatch only if left undisturbed in the nest
  box. Collecting them, or deconstructing the box, prevents hatching.
- To breed, forbid the clutch while it is still in the box, or lock the
  nest box room, or forbid cooking that egg type and refuse it in every
  food stockpile. A female will sit on an unfertilized clutch forever
  if nobody collects it; eggs that have not hatched after two seasons
  almost certainly never will, and must be collected so she can lay
  again.
- The incubation chamber is the reliable layout: 1x1 rooms with a
  lockable door, one nest box in each, a 1x1 pasture on the nest box
  with one female assigned, and a male pastured somewhere the females
  can reach. Lock the door while the eggs incubate, unlock it when
  they hatch, and cage the chicks so they do not crowd the room and
  fight.
- Poultry become adults one year after hatching. They root around and
  attract vermin, so they are poor pets even though they are good
  livestock.

Nest boxes are made from one piece of wood or stone at a craftsdwarf's
workshop, one bag of sand at a glass furnace, or one bar of metal at a
forge, and then built as furniture. There is no MakeNestBox job type;
the nest box is a building, not a workshop order.

## 7. Butchering and the meat pipeline

### 7.1 Slaughter

A tame animal is marked for slaughter in the Pets/Livestock tab. A
dwarf with the butcher labor drags it to a butcher's shop and puts it
down, and the butchering happens at once. The corpses of hunted or
slain wild animals are butchered separately, and only if they are close
enough: a butcher's shop scans about 20 tiles in every direction for
corpses, so a refuse pile that accepts corpses belongs next to the shop.
The butcher's skill only affects how long the job takes, never how much
comes out of it.

A tame animal that dies any other way, starvation, old age, or violence,
cannot be butchered at all. That is the whole reason slaughter is a
decision the harness makes deliberately: a dead animal is wasted meat,
a slaughtered one is food, leather, bone, and fat.

### 7.2 What comes out

A butchered animal yields one skull, and may also yield raw hide, meat,
prepared organs, fat, bones, horns, hooves, and cartilage, depending on
the animal and its size. Very small animals yield only a skull. The
pipeline after the shop is:

- Meat and organs go to the kitchen or the food stockpile. Meat rots,
  so the butcher's shop needs haulers and a stockpile next to it.
- Raw hide goes to a tanner's shop and becomes leather.
- Fat is rendered into tallow, which is cooked into meals or made into
  soap.
- Bones become bolts or bone crafts; skulls and horns become crafts.
- Hair and wool from butchering go to the cloth chain.

A dog, for reference, yields 6 to 13 meat, 6 to 13 fat, 4 to 11 bones,
one skull, and a raw hide.

### 7.3 What to slaughter, and when

The harness slaughters by rule, not by mood:

- Slaughter the surplus of a breeding line once it is adult, never the
  breeding pair, never a pet, never an animal the fort still needs
  alive for milk, wool, eggs, or war.
- Slaughter the old and the injured when their production has stopped
  and their meat is still worth having. A war dog with serious injuries
  can still be slaughtered.
- Slaughter young animals of slow-maturing species when waiting years
  for full returns is worth less than the meat now.
- Never slaughter an animal the fort cannot reach: if the butcher's
  shop cannot see the corpse, it rots where it falls.

## 8. War and hunting training

Dogs are the training animal. Pet value 30, trainable for both war and
hunting, cheap, breed fast, and need no food. A war dog at the depot
path and at the entrance is the cheapest early defense the fort can
buy, and the trading plan already says so. Nothing else is trained
until dogs are working.

### 8.1 How training works

Training needs an animal training zone or a pasture, and a dwarf with
the animal training labor. The trainer tames a wild animal from its
cage, or trains a tame one for war or hunting. Training levels run wild,
semi-wild, trained, well-trained, skillfully trained, expertly trained,
exceptionally trained, masterfully trained, and finally tame, which for
a domesticated species is permanent.

- Animals with pet value under 100 are easy to train. Over 100 takes
  effort and a few years. Over 1000, such as a dragon, is very slow.
- Adult trained animals slowly revert to wild over time and must be
  re-trained. The last step before fully wild is semi-wild, which
  prompts an announcement. Dwarves know when their animals need
  retraining and prioritize it, but they cannot do it if they are
  injured, in a strange mood, or cannot reach the animal.
- A child that receives training once becomes fully tame forever, and
  never needs training again. That is how a fort builds a permanent
  tame population out of a captured wild species: catch them young.
- Animals without a child state can never be fully tamed and need
  retraining for the rest of their lives. Examples are crundles, giant
  cave spiders, and hydras.
- Animals bought from merchants are fully tame and never revert.
- A single trainer assigned to an animal is the only dwarf who will
  ever train it, so a sick or busy trainer means an untrained animal.

### 8.2 War dogs and hunting dogs

War dogs do more damage than untrained dogs. A pack of them is
dangerous even to armored opponents, and they take hits that would
otherwise land on dwarves. Hunting dogs sneak without a movement
penalty near their hunting owner, notice creatures from farther away,
and target what the owner targets.

The costs are real and the harness must say them plainly. Dogs move
faster than armored dwarves and charge in unassisted, so dogs assigned
to military dwarves die often. A dead pet causes a serious unhappiness
spike in its owner. Once a dog is assigned to a dwarf it cannot be
unassigned or caged, though it can still be pastured. Unassigned war
dogs follow the dwarf who trained them and can still be caged. A
civilian alert stops war dogs following soldiers into combat. Female
war dogs breed as well as any other animal, so the harness does not
train the breeding females.

### 8.3 Guard dogs

A dog on a restraint behind a hall of traps is a guard dog. The traps
keep invaders from reaching the dog, and the dog's presence keeps
thieves from sneaking past the traps. Hunting dogs suit guard duty
because of their improved observation. Dogs spot ambushers and thieves
simply by being friendly creatures that notice them.

### 8.4 Taming wild animals

Wild animals are caught in cage traps, then tamed by a trainer at an
animal training zone. Only creatures with the pet or exotic pet token
can be tamed; sapient creatures, forgotten beasts, and titans never
can. Trapped creatures that cannot be tamed are still useful: they can
be pitted against enemies, or used for live training. Captured war
mounts and other named enemies stay hostile no matter how much they are
trained, and releasing one can cause a loyalty cascade, so the harness
never releases a trained hostile.

## 9. Pets

Pets are a happiness system with a cost. A pet gives its owner a
companionship bonus for as long as both live, scaled by the animal's
pet value: a dog is 30, a jaguar 50, a panda 300, a cave crocodile 700.
A dwarf who adopts a high-value pet is happier than one who adopts a
low-value pet, and both are better off than a dwarf with no pet at all.
That is the whole case for letting adoption happen.

The costs: a pet cannot be butchered, chained, or caged, and its death
gives its owner a negative thought even if it dies of old age. A
migrant's pet mule is clutter the fort cannot remove without making
somebody unhappy. A pet grazer generates a job for its owner to feed
it, and that job is low priority, so a pet grazer can starve while its
owner is busy elsewhere.

The harness's rules for pets:

- Let adoption happen for dogs, cats, and other low-value animals.
  Do not fight it; the happiness is worth more than the control.
- Keep grazers out of the adoption pool where possible. A pet yak is
  a feeding job waiting to be missed.
- Never plan a slaughter around a pet. If it is adopted, it is off the
  butcher's list permanently.
- Cage stray cats before they adopt anyone. A caged cat cannot adopt,
  and a kitten caged at birth never gets the chance.
- A pet's death is recorded in the fort's history like any other death,
  with the owner's name attached, because the diary needs to know whose
  heart broke.

## 10. Cages, traps, and catching wild animals

### 10.1 Cages

A cage is made from a log at a carpenter's workshop, three bars of metal
at a forge, or glass at a glass furnace. Cages are stored in an animal
stockpile. One cage holds an unlimited number of animals. Caged animals
do not path, which helps the frame rate, and cannot be attacked, though
existing attack orders do not cancel on their own. Caged animals age,
so kittens in a cage become adult cats. They cannot get pregnant in a
cage. Grazers starve in a cage. To release an animal, assign it to a
pasture and a dwarf will take it out of the cage and lead it there,
unless the cage is already inside the pasture, in which case the animal
is considered already pastured and stays caged.

A built cage can be linked to a lever. Deconstructing a cage with
creatures in it returns the cage, creatures and all, to the nearest
animal stockpile. Melting a cage releases what is inside.

### 10.2 Cage traps

Wild animals are caught in cage traps, built where animals will walk,
not where they are when the fort decides to trap them. Dwarves sent to
build traps among the animals scare them away or trigger aggression.
The reliable layout is walls and choke points that funnel animals
through a gap one or two tiles wide with the traps in it, and cage
traps cannot be built within four or five tiles of the map edge, so the
funnel needs that buffer. Traps are re-armed by a mechanic hauling a
fresh cage to them. Creatures with the trap-avoid token ignore cage
traps unless there is a web on the same tile.

Catching is how the fort gets animals it cannot buy: egg-layers from
the caverns, breeding pairs of wild species, and the occasional exotic.
Caught animals need taming at an animal training zone before they are
useful, and a caught grazer needs a pasture the moment it is released
or it starves.

### 10.3 Animal traps

Animal traps are a different thing and are not used for creature-sized
animals. They are for live vermin, used by trappers, and the vermin
catcher's shop handles them. The harness must not confuse the two.

## 11. Risks: starvation, sickness, and animals the fort cannot feed

### 11.1 Starvation

Starvation is the main way the fort loses animals, and it is almost
always the harness's fault, not the game's. The causes, in order of
how often they happen:

1. A grazer with no pasture, or a pasture with no grass left in it.
   The check is the grass: if more than half the pasture is bare, it
   is overloaded.
2. A grazer left in a cage. There is no grass in a cage.
3. A pet grazer whose owner is too busy to feed it. The feeding job
   is low priority and can be missed for long enough to kill.
4. A pasture in a biome where grass never regrows, eaten bare.
5. A grazer that fled a fight and was never re-pastured, because the
   dwarf sent to fetch it walked into danger.

The harness watches for all five. A hungry grazer is an attention
entry, not a line in a report.

### 11.2 Sickness and injury

Sickness in animals is marked UNVERIFIED. The wiki search for this
plan found no animal disease mechanics to cite, and the harness has no
observation of animal illness beyond wounds, which the probe already
reads. What is verified is the wound side: the probe reads each wound
with its id and part count, and a wounded animal can still be
slaughtered. What is not verified is whether the animal caretaker labor
does anything observable in 0.47.05-r8, whether sick animals generate
jobs, and whether wounded animals recover on their own. The
implementation phase for animal health must probe those three
questions live before it claims anything about them.

### 11.3 Animals the fort cannot feed

When the fort has animals it cannot feed or house, the harness acts in
this order:

1. Sell the surplus, following the trading plan's rules: never the
   breeding pair, never the war dogs, never the milk and wool breeding
   stock.
2. Butcher the surplus that is worth more dead than alive, following
   section 7.3.
3. Geld the males of a line that is over target, so the problem does
   not come back.
4. Move the grazers to an indoor pasture with fungus, or to a larger
   outdoor pasture, if the grass is the problem rather than the head
   count.
5. If none of that is possible, say so in the snapshot and refuse to
   take more animals. The harness never buys an animal into a fort
   that cannot keep it, and it never lets a herd grow past what the
   grass supports.

## 12. The harness's role at each step

The harness decides; the agent picks from named options with a
one-line why. The agent never reasons about grazer values, pasture
tile counts, training thresholds, or cage states. Those numbers live in
the harness and in this document.

| Step | Harness decides | Agent sees |
| --- | --- | --- |
| Pasture | Size from the animals in it, placement by the scored site rules plus grass cover, indoor or outdoor | "Pasture for the yak and water buffalo, 10x6, inside the cavern, fungus growing" |
| Breeding | Population target per species, which males to geld, which young to cage | "Geld the tomcat, the cats are at 12 and rising" |
| Milk and wool | Which animals are milkable or shearable now, whether the farmer's workshop and buckets exist | "Milk the yak, 17 days since last milking, bucket ready" |
| Eggs | Nest box count against laying females, which clutches to forbid for breeding | "Build 2 nest boxes, 3 hens with none claimed" |
| Butchering | Which animals are surplus by the rules in 7.3, whether the butcher's shop can reach them | "Slaughter the old mule, past breeding, meat 6 to 13" |
| Training | Which dogs to train, which trainer, whether the training zone exists | "Train the dog for war, trainer free, zone ready" |
| Pets | Which animals are available for adoption, which cats to cage before they adopt | "Cage the 3 kittens before they adopt" |
| Cages and traps | Which wild animals are worth catching, where the funnel goes | "Cage trap the elk bird at the north choke point" |
| Risk | Hungry grazers, overcrowded pastures, animals the fort cannot feed | "The yak has not eaten in 3 days, pasture is bare" |

The snapshot carries the top animal item per kind, never a dump of all
animals. Full detail lives behind a query, by species, by animal, or by
pasture.

## 13. Refusals

The harness refuses, with a reason, and the reason is shown to the
agent:

- Never slaughter a pet. A pet is off the butcher's list permanently.
- Never slaughter the breeding pair or the milk and wool breeding stock.
  The trading plan already says this, and it binds here too.
- Never cage a grazer indefinitely. A caged grazer starves.
- Never leave a grazer without a pasture, or on a pasture with no
  grass. If there is no grass, the harness says so and does not place
  the animal there.
- Never release a trained hostile animal. A captured war mount stays
  hostile and can cause a loyalty cascade.
- Never train an animal with no trainer available, and never assign a
  single trainer the fort cannot spare.
- Never buy an animal the fort cannot keep. That rule is in the trading
  plan and it binds here too.
- Never butcher an animal the butcher's shop cannot reach. It rots
  where it falls.
- Never let a cat population grow past what the fort can geld or cage.
  The catsplosion is a failure the harness must prevent, not report.

## 14. Implementation phases, in order

Each phase is done only when its live-verification bar is met. The
phases build on each other; do not start phase 3 before phase 1 is
proven live.

### Phase 1: See the animals

Extend the livestock records in `units.lua` beyond count-only: sex,
age, tame or training level, owner, pregnancy where the game exposes
it, pasture assignment, and cage state. Add the same fields to the
single-unit probe where they are cheap to read. Verify which fields
the game actually exposes in 0.47.05-r8 and record the ones it does
not as UNVERIFIED, rather than guessing them. Add a per-animal history
to the store, the same way citizens get a daily sample.

Live bar: `GET /v1/units?kind=livestock` returns the fort's six
animals with sex, age, and owner filled in, and the values match what
the game shows for those animals.

### Phase 2: Pastures that work

Place a pen/pasture zone by the scored site rules with the grass check
from section 4, and find the programmatic route for assigning animals
to it. The zone placement is proven; the assignment route is the open
question for this phase. Size the pasture from the grazer table in
section 4.1 and watch the grass cover over time.

Live bar: the yak and the water buffalo are assigned to a pasture
with grass, the grass cover is readable afterwards, and the animals
stop losing hunger while pastured. If no assignment route exists in
the game, report exactly what was tried and what blocked it.

### Phase 3: Milk, wool, and eggs

Queue MilkCreature and ShearCreature jobs at a farmer's workshop and
verify they run, and build nest boxes and verify hens claim them and
lay. The job types exist in the runtime enums; the queue route through
the harness's workshop-job machinery is what must be proven live.
Milk needs the bucket and the non-pet rule checked first; shearing
needs the three-species rule checked first.

Live bar: the yak is milked and milk appears in stocks; a sheep,
llama, or alpaca is sheared and yarn appears; a hen claims a nest box
and eggs appear in the food stockpile.

### Phase 4: Breeding control

Geld jobs and population targets. Queue a GeldAnimal job at a farmer's
workshop and verify the male can no longer breed. Track the per-species
count against its target and surface the surplus as a named decision.

Live bar: a tomcat is gelded and the cat population stops growing;
the per-species count is readable and the surplus rule fires on it.

### Phase 5: Butchering

Queue a SlaughterAnimal job and verify the animal is slaughtered and
butchered, with the returns in stocks. Verify the butcher's shop range
rule live: a corpse beyond about 20 tiles is not collected. Verify the
tame-death rule live: an animal that dies any other way cannot be
butchered.

Live bar: a surplus animal is slaughtered, meat and hide appear in
stocks, and the leather and tallow chain runs after it.

### Phase 6: War and hunting dogs

Build an animal training zone, assign a trainer, and train a dog for
war and a dog for hunting. Verify the training level rises and the dog
follows its trainer. Verify the reversion rule: an untrained-for-a-while
dog drops a level and the harness notices.

Live bar: a war dog and a hunting dog exist with training levels
readable, and the harness reports when one needs retraining.

### Phase 7: Cages and catching

Cage assignment and cage traps. Verify the cage route live, verify a
cage trap catches a wild animal, and verify the taming route from the
cage. Verify the grazer rule: a caged grazer's hunger climbs, so the
harness never leaves one caged.

Live bar: a wild animal is caught, tamed, and released to a pasture;
a caged grazer is flagged hungry by the harness before it starves.

### Phase 8: The agent loop

Wire the animal state into the snapshot attention and the suggestion
system: hungry grazers, overcrowded pastures, trainable arrivals,
surplus animals, and cats that need gelding all surface as named
options with a one-line why. The diary carries animal events the same
way it carries dwarf events: births, deaths, training, and the pet
that broke somebody's heart.

Live bar: a full M1 day runs with the animal attention live, and the
model acts on a named animal option from the snapshot alone.

## 15. Open questions

- Pasture assignment: no programmatic route is known for assigning an
  animal to a pasture zone. The zone itself can be created
  programmatically; the assignment is the gap. UNVERIFIED.
- Milk, shear, geld, and slaughter job queueing: the job types exist
  in the runtime enums, but the route for queueing them through the
  harness's workshop-job machinery has not been proven live.
  UNVERIFIED.
- Animal health: whether the animal caretaker labor does anything
  observable, whether sick animals generate jobs, and whether wounded
  animals recover. UNVERIFIED.
- Pregnancy: whether the game exposes a pregnancy flag the harness can
  read, or whether it must be inferred from births. UNVERIFIED.
- Sheep grazer value: the grazer table in section 4.1 has no sheep
  row because the page excerpt read for this plan did not include it.
  Read it from the wiki before the pasture sizer uses it.
- Training assignment: the route for assigning a trainer to a specific
  animal, and for assigning a trained dog to a specific dwarf, has not
  been proven. UNVERIFIED.
- Whether Bug 10162 (bought animals not always usable) reproduces on
  0.47.05-r8, and what the harness does when it does. UNVERIFIED.
- Whether the per-species population cap of about 50 is exact, and how
  the juvenile cap interacts with it. UNVERIFIED.

## 16. Sources

- Pasture (wiki): pastures hold tame animals, grazers need grass or
  cave moss, grass regrowth by biome, mountain grass never regrows,
  overcrowding causes fights, deactivating a pasture recalls animals
  to the meeting area, 1x1 pastures with nest boxes as battery farms.
- Grazer (wiki): the grazer formula, the per-animal pasture table,
  pet feeding as an unreliable alternative to pasture.
- Meat industry (wiki): acquisition, breeding, the per-species cap of
  about 50, pasture management, internal pastures on fungus, pens and
  restraints for frame rate, caging the young, slaughter and
  butchering, the 20-tile butcher's shop range, tame animals that die
  otherwise cannot be butchered (Bug 1275).
- Egg production (wiki): clutch sizes, nest box rules, fertilized
  versus unfertilized eggs, the two-season rule, incubation chambers,
  cage traps for wild egg-layers.
- Milk (wiki): the milkable list, milking requirements, the 20,000
  tick interval, freezing, cheese stacks.
- Shearer and Wool (wiki): only sheep, llamas, and alpacas can be
  sheared; shearing produces yarn at a farmer's workshop.
- Butcher's shop (wiki): slaughter marking, goods produced, hauling
  and stockpile considerations, rotting and miasma.
- Animal trainer (wiki): training levels, taming from cages, reversion,
  taming children, knowledge levels and thresholds, animal AI and
  following behaviour.
- Dog (wiki): pet value 30, war and hunting training, guard dogs,
  assignment rules, butchering returns.
- Gelder (wiki): gelding at a farmer's workshop, one geld job per
  workshop, egg-layers not geldable, the catsplosion fix.
- Pet (wiki): adoption, pet value and happiness, pets cannot be
  butchered, chained, or caged, pet death and negative thoughts.
- Catsplosion (wiki): exponential cat growth, gelding as the fix,
  caging strays, selling caged cats as the only fully safe removal.
- Nest box (wiki): creation at a craftsdwarf's workshop, forge, or
  glass furnace; claimed by one animal; the incubation chamber layout.
- Cage (wiki): unlimited animals per cage, caged animals do not path,
  cannot get pregnant in cages, grazers starve in cages, release by
  pasture assignment.
- `docs/TRADING.md` section 7: buying and selling animals, what the
  fort must have before buying, Bug 10162.
- `docs/SITE_SELECTION.md`: scored site selection, which pasture
  placement builds on. (Queued work at the time of writing; verify it
  exists before implementing phase 2.)
- `src/dfagent_harness/lua/units.lua`, `probe_unit.lua`, `actions.py`
  (create_zone, pen_pasture), `tests/fixtures/runtime-enums-0.47.05-r8.json`
  (SlaughterAnimal, GeldAnimal, MilkCreature, ShearCreature,
  ButcherAnimal, TrainAnimal, TameAnimal): the harness state this plan
  was written against, verified 2026-11-27.
