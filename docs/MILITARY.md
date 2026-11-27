# Military

A plan for giving Urist a military: squads, training, equipment, alerts,
burrows, and invasion response. Everything here is researched from the
local DF wiki index and from the harness's own prior research in
`docs/ADVANCED_MECHANICS.md` section 7. Nothing is guessed. Anything not
verified against the wiki or the live game is marked UNVERIFIED.

Status: design only. No military code exists yet. The coordinator owns
implementation; this doc is the record it builds from.

## 1. What the military is in DF 0.47.05

The military is the fort's fighting force. Traps and walls alone do not
hold a fort: the wiki's Military page says the military "will still need
to fend off goblin sieges, megabeasts, titans, and fiendish underground
beasties", and only the military can take a fight to the enemy. It is
expensive to maintain (metal, labor, food, drink, accommodation) and
soldiers are almost constantly at risk, so the harness must weigh the
cost of every dwarf it puts in uniform against the work that dwarf
would otherwise do.

The military system has four parts the harness must handle:

1. **Squads**: groups of up to 10 soldiers who share a schedule and
   active orders. Led by a militia commander (first squad) and militia
   captains (later squads). (Squad page.)
2. **Training**: barracks, schedules, demonstrations, sparring, drills.
   (Training page.)
3. **Equipment**: uniforms, weapons, armor, shields, ammunition.
   (Armor, Weapon, Military design pages.)
4. **Command**: active orders (move, attack) and passive orders
   (alerts, schedules, patrol routes, stations, defend burrow).
   (Military, Scheduling pages.)

Version note: the local wiki export tracks current DF (v50 and later),
and the squad, scheduling, and armor pages describe the mouse-driven
v50 interface. DF 0.47.05 uses the keyboard military screen, and
civilian alerts exist in 0.47.05 (they were removed from vanilla in
v50, though the underlying functionality is still present there).
Mechanics (squad size, training, armor, siege triggers) are the same
across versions unless noted. Every UI-level claim in this doc must be
verified live against 0.47.05 before it becomes code.

Sources used: Military, Squad, Training, Military design, Military
quickstart, Military F.A.Q., Scheduling, Armor, Weapon, Burrow,
Civilian alert, Defense guide, Security design, Siege, Ambush, Trap
design, Danger room.

## 2. What the harness has today

Detection exists. Response does not. That is the whole gap.

- `events.py` has an INVASION handler that fires a critical event when
  eventful reports an invasion. The planner has threat tiers: near at
  15 tiles, critical at 5 tiles, and at critical it holds the game
  paused until the threat moves away.
- `briefings.py` has invasion, hostile, new_arrival, and
  cavern_creature briefings. They promise things that do not exist:
  "muster the military", "seal the entrance (raise the drawbridge /
  lock the door)", "let the military intercept them away from
  civilians". `planner.py:337` says it plainly: "no military exists;
  shelter by pausing only if it closes in". The only response today
  is pause and wait. This briefing drift is a bug, and fixing it is
  phase 1 of this plan.
- There is no squad creation, no uniform assignment, no barracks
  assignment, no schedule, no alert, no burrow, and no stationing
  anywhere in the harness. `planner.py` notes "military squads
  (UI-only, unimplemented)".
- The prior research in `docs/ADVANCED_MECHANICS.md` section 7
  established the hard facts: there is no `df.squad:new()` creation
  API anywhere in DFHack r8, no create-squad function, no squad tool,
  no `next_squad_id` counter. The `df.squad` fields are known (id,
  name, alias, positions, orders, schedule, cur_alert_idx, rooms,
  rack_combat/rack_training, uniform_priority, activity, ammunition,
  carry_food/water, entity_id, leader_position/assignment), and the
  order structs exist (`SquadOrderMovest`,
  `SquadOrderDefendBurrowsst`, `SquadOrderPatrolRoutest`,
  `SquadOrderTrainst`, `SquadOrderKillHfst`, `SquadOrderKillListst`),
  but no precedent exists for constructing an order and having the
  game execute it. Member assignment would presumably be
  `df.squad_position:new()` with `occupant = unit.hist_figure_id`,
  inserted into `squad.positions`, plus
  `unit.military.squad_id`/`squad_position`. Inferred, not found.
  All unproven; it needs live testing from scratch.
- Burrows are the same story: `dfhack.burrows` offers find, clear,
  assign, and tile queries, but no create command or function
  anywhere. The direct-construction route is written out in
  `ADVANCED_MECHANICS.md` section 7 and is repeated in section 7
  below. It is plausible and unproven.
- Barracks are not a zone type. `CivzoneType` has no barracks. Barracks
  assignment is per furniture, through the room system: beds, armor
  stands, and weapon racks each carry `squads` (a vector of
  `BuildingSquadUse` with squad_id and mode) plus
  `specific_squad`/`specific_position` and `users`; the squad side
  mirrors it in `squad.rooms` (building_id, mode). `SquadUseFlags`
  bits: sleep 0, train 1, indiv_eq 2, squad_eq 3. No write precedent
  exists.

The fort today (world.db snapshot, tick 115166, 2026-11-27): 7 citizens
(miner, stoneworker, jeweler, expedition leader, fish cleaner,
woodcutter, fisherdwarf), 2 buildings (Carpenters #7, Still #8), drink
97, food 23, wood 117, stone 0, 1 brewable plant, 7 empty barrels. No
forge, no barracks, no armor, no metal bars in stocks. The embark
weapons on record are a bow and a war hammer, not picks. There is
nothing to arm a squad with yet, and nobody to spare without stopping
the fort's work. The plan respects that: the first military work is
observation and preparation, not a squad.

## 3. Squad formation

### 3.1 The chain of command

A militia commander must be appointed from the nobles screen before
any squad can be created. The fort has exactly one militia commander,
who leads the first squad and commands the captains of later squads.
Each later squad has its own militia captain, appointed through the
nobles screen or by assigning a dwarf to the first position of the new
squad. (Squad page, Military quickstart.)

The commander does not have to accompany the squad into combat. The
commander can stay in the fort; the squad then fights one body short.
The wiki's recommended trick: give the commander a permanent 1-dwarf
"first" squad of their own, then build real combat squads with their
own captains. The harness should do exactly this, so the commander
never has to be a front-line fighter unless the agent explicitly
chooses it.

Appointing the commander is a noble appointment. The harness's noble
route is still open work (step 2 remainder: insert into
`ent.positions.assignments`, not `assignments_by_type`, id from
`next_assignment_id`, with `position_vector_idx`, `histfig2`, and a
`histfig_entity_link_positionst` on the histfig; read-back via
`dfhack.units.getNoblePositions(unit)`). The military plan depends on
that route landing. Until it does, no squad can be formed at all, and
the plan says so instead of pretending otherwise.

### 3.2 How many dwarves, and which ones

A squad holds at most 10 soldiers, leader included. The quickstart
builds a first squad of 5. With 7 citizens, the first squad is 5 at
most, leaving 2 civilians to keep the fort running, and even 5 is
expensive: every soldier is a worker lost. The harness must size the
squad from the live roster, not from a fixed number:

- Never draft the only dwarf with a critical skill (the only miner,
  the only brewer, the only carpenter) unless the fort is already
  under attack and the choice is between that dwarf fighting or the
  fort dying.
- Prefer dwarves with no useful civilian skill, or with a combat skill
  already (migrants often arrive with competent or better military
  skill; peasants with military skill are the best first recruits).
  The quickstart's rule: look at job titles. A legendary fish cleaner
  in a fort with many fisherdwarves is expendable; the only butcher in
  a fort with no animal industry is expendable. The harness can read
  skills and labors from the units collect and rank candidates the
  same way.
- Married female dwarves carry babies and are poor front-line picks;
  the wiki suggests preferring them for ranged squads behind
  fortifications instead. The harness knows sex and family from the
  relations data, so it can apply this without the agent having to
  think about it.
- Recruits must NOT have the mining, woodcutting, or hunting labors
  enabled. Those labors carry an invisible "civilian uniform" that
  conflicts with all military equipment (Bug 1451). The harness must
  disable those labors on a recruit as part of drafting, and refuse
  to draft a dwarf whose labors cannot be cleared. This is a hard
  precondition, not a warning.

### 3.3 Melee vs marksdwarf mix

The wiki's position (Military design): archers are deadly but
vulnerable in melee, crossbows as clubs are poor weapons, and
fortifications are crucial to any archery platform. Elite enemy
archers can shoot back through fortifications. The mix depends on
what the fort can build:

- Melee first. A melee squad works with whatever metal the fort has
  and needs no ammunition pipeline. Axes and swords cut unarmored
  enemies apart; war hammers and maces smash through armor and break
  bones (Weapon page). Spears and picks pierce armor and organs.
- Marksdwarves second, only once the fort has crossbows, quivers, and
  a bolt supply, plus a fortified archery position for them to shoot
  from. Every marksdwarf needs a quiver, one archery target per dwarf,
  and 100-200 bolts assigned per dwarf, not the default ~200 per
  squad (Military design). Without those three, marksdwarves train by
  bashing each other with crossbows and fight the same way.
- The harness decides the mix from stocks and production, and tells
  the agent the mix as a named option with a one-line why ("melee
  squad of 5, you have 3 axes and no bolts" beats "archer squad, you
  have no quivers").

### 3.4 When the fort is big enough

The fort has 7 citizens. A 5-dwarf squad is the most it can field, and
only by stripping the workforce. The plan's sizing rule:

- Under 10 citizens: at most one squad, at most 5 dwarves, and only
  after the fort has a forge and at least starter equipment. Before
  that, defense is traps, walls, and sealing the entrance, not
  soldiers.
- 10-20 citizens: one full squad of 10, or two squads of 5 (one melee,
  one ranged) once the second has equipment.
- 20+ citizens: multiple squads, with one squad always on training
  rotation and one on patrol or station.

Sieges themselves do not start until the fort reaches 80 citizens
(Siege page), except for the undead, who may attack at any time. That
gives the harness a long runway: ambushes, thieves, and wildlife are
the early threats, and they are handled by a small squad plus traps,
not by a standing army. The harness must not build a military the
fort cannot feed.

## 4. Training

Training is how soldiers get good, and it is slow. Combat skill is
the most important factor in a soldier's effectiveness, ahead of
equipment and attributes (Military design). The harness must start
training early and keep it running, because a squad formed the day a
siege arrives is a dead squad.

### 4.1 How training works

Training happens in a barracks, in three forms (Training page):

- **Demonstrations**: group sessions for a specific skill, led by a
  teacher with experience in it. All students must be present for the
  demonstration to begin; those already present wait or do individual
  training. Dwarves only attend a demonstration if it teaches a
  fighting skill or the weapon they currently carry. A squad with
  mixed weapons gets few useful demonstrations, so the harness should
  keep one weapon type per squad. Wrestling demonstrations happen
  often because every dwarf can wrestle.
- **Sparring**: practice melee combat between two or more squad
  members. It trains every usable combat skill (weapon, Fighting,
  Wrestling, Discipline, and more) and confers skill increases faster
  than demonstrations. Sparring only starts when at least 2 dwarves
  have at least competent (3) fighter skill, and dwarves close in
  skill spar much more often. The wiki's best advice: use 2- or
  3-dwarf squads for training, with the same weapon, so the pair spars
  constantly. The harness should form small training squads, not one
  big squad, until the dwarves are competent.
- **Individual training**: slow self-training, one skill at a time.
  Squad members do it when nobody else is training with them, or in
  spare time. A squad assigned to a barracks will do individual
  training there instead of going idle, but they will never spar or
  demonstrate unless the squad is activated (through the squad menu
  or a routine with training orders).

All weapons are safe for sparring, even the sharpest short sword.
Training weapons are not necessary and can be counterproductive: a
dwarf can grow attached to a wooden training weapon and refuse to
give it up, and a wooden weapon in a real fight is a death sentence
(Training, Military quickstart, Weapon). The harness should skip
training weapons entirely once the fort has any real weapon, and
swap them out before any battle without exception.

### 4.2 Barracks

A barracks is a zone designated for housing and training a squad. Beds,
weapon racks, chests, and armor stands are useful inside it, but none
are required to begin training. The squad is assigned to train in it
from the barracks configuration, and the squad's schedule (see 4.3)
does the rest.

In 0.47.05 there is no barracks zone type; assignment is per furniture
through the room system (section 2). The harness must build that
write path: assign a bed/armor stand/weapon rack to a squad with the
train flag, and mirror it in `squad.rooms`. Until that path is
verified live, no squad can train, and the plan says so.

Safety rules for the barracks, from the wiki: keep it away from high
cliffs, stairs, open water, and wells, because sparring dwarves dodge
and can fall or drown. Spar in open rooms, and make sure every
sparring dwarf wears a helmet: wrestling throws can slam a dwarf's
head into the ground or a wall, and that can be lethal (Training).
The scored site selection work (docs/SITE_SELECTION.md, queued)
applies here: the barracks site is scored like any other room, with
safety as a hard gate.

### 4.3 Schedules and routines

A schedule is the squad's programming: what it does, in which month,
under which alert. The default routines are Off Duty, Staggered
Training, Constant Training, and Ready (Scheduling page). The first
squad should be set to Constant Training until it is competent, then
rotated: training months, patrol months, and off-duty months so the
dwarves eat, drink, sleep, and do not accumulate "long patrol duty"
bad thoughts. Dwarves with Great or better weapon skill stop getting
those thoughts. (Military F.A.Q.)

The monthly orders a schedule can carry: Train, Station, Patrol Route,
Defend Burrow, and Inactive. Each order carries criteria for how many
soldiers follow it at once, so part of a squad can train while part
patrols. The harness builds schedules as data, not as a list of
keypresses, and the agent picks a named routine ("constant training
until competent, then rotate") with a one-line why.

One live bug to plan around: in the current release, when a squad
leader sets up a training class he waits forever for students even if
nobody shows up, and students wait for a leader who is doing
individual training, even until they starve (Military page). The
workaround is to alternate forced training schedules with downtime so
no dwarf waits longer than a game month, or to leave squads off duty
doing individual training only. The harness must alternate; a
Constant Training schedule with no downtime can starve a squad.
UNVERIFIED for 0.47.05 specifically: the wiki text describes the
current release; the harness must confirm live whether the hang
reproduces on r8 before it relies on the workaround.

### 4.4 Danger rooms: not recommended

A danger room (wooden training spears on repeat, or items thrown at
dwarves) used to be the fast way to train armor, shield, and dodging.
The wiki's current position is blunt: changes to combat damage
calculations made danger rooms far more dangerous, even mortally so,
and small-group sparring is the recommended training regimen (Danger
room page). The plan follows that: no danger room. If a future
investigation proves a safe design on 0.47.05-r8, it can be added
then, with live proof, not before.

### 4.5 Live training on prisoners

Fighting a disarmed, caged prisoner with training weapons and full
armor trains defensive skills fast (Armor User, Shield User, Dodger).
It is the fastest training in the game and the most dangerous to set
up: it needs cage traps, a pit, and a way to retrieve corpses. This
is an advanced option, not a first-squad option. It lands only after
squads, barracks, and cage traps all work, and only with a verified
safe arena. Until then, sparring is the training method.

## 5. Equipment

Equipment is where the have/need machinery earns its keep. Every piece
of gear is a material check before it is a uniform entry: the harness
must say "have X, need Y" for each item, fail fast naming both numbers
when the fort is short, and substitute a gathering or production action
when it can. A squad that exists on paper and has no weapons is worse
than no squad: it costs dwarves and delivers nothing.

### 5.1 Uniforms

A uniform is a saved set of equipment applied to a whole squad at
once. The game ships four defaults: No uniform, Leather armor, Metal
armor, Archer (Squad page, Armor page). The harness will define its
own, in two tiers from the Military design page:

**Starter uniform** (what a fort with no metal industry can field):
wooden or bone crossbows with leather quiver and bone or wooden bolts
for archers, or any metal melee weapon (wooden training weapons only
as a stopgap); wooden or leather shields; bone helms, bone leggings,
bone gauntlets; wooden or leather armor, adding a metal mail shirt as
soon as one exists; wooden boots or leather high boots; empty slots
filled with civilian clothes.

**Basic uniform** (what a fort with a working forge fields): metal
weapon (metal bolts for crossbows, leather quiver); wooden shield for
weight or metal shield for bashing; metal mail shirt, metal helm,
metal greaves, metal high boots, metal gauntlets, metal breastplate;
optional silk or yarn dress, robe, trousers, hood, socks.

Two uniform settings matter and the harness must set them
deliberately, not leave them at default:

- **Replace clothing vs over clothing.** The defaults wear the uniform
  over civilian clothes, and civilian caps, gloves, and shoes conflict
  with helms, gauntlets, and boots, so the dwarf shows as assigned
  armor he cannot actually wear. "Replace clothing" avoids this.
  (Armor page.) The harness sets replace clothing on every military
  uniform.
- **Partial matches vs exact matches.** Partial matches let a dwarf
  substitute something close; exact matches leave him without the
  piece rather than making do. The harness uses partial matches while
  the fort is equipping up, and exact matches once the full kit
  exists, so a missing piece is reported instead of silently
  substituted.

### 5.2 Armor: what protects, and what it costs

Armor pieces cover different body areas; there is no single "suit".
Chain (mail shirt, chain leggings) is flexible: good against slashing
weapons, weak against blunt force. Plate (breastplate, helm, greaves,
gauntlets, boots) is rigid: the best all-around protection, but
heavier. For slashing and piercing weapons the metal matters most: a
better metal defeats a lesser armor, a lesser weapon is stopped by a
better armor. For blunt weapons, weight is the rule and all combat
metals weigh roughly the same. (Armor page.)

Material tiers, cheapest first: leather and bone (weak, only good
against small animals and as a first resort before any metal industry;
leather armor is made at a leather works, bone at a craftsdwarf's
workshop); copper (quickly outclassed against almost anything except
silver weapons and animal attacks); bronze and iron (the minimum the
wiki recommends for real fighting); steel (the standard for a serious
military; a full set of exceptional steel can absorb most of a goblin
squad's ammunition). The harness must know the fort's metal: the
survey tells it what ores the map holds, stocks tell it what bars
exist, and the forge tells it what can be made. If the map has no
iron, the plan says so and the buy list (docs/TRADING.md) carries
iron and steel as a trade priority.

Armor user skill matters as much as the armor: untrained dwarves are
encumbered and slowed in armor, and a grand master armor user moves
twice as fast in heavy armor as a dabbling one. Training in armor is
therefore part of training, not an afterthought: the more armor pieces
a dwarf trains in, the faster the skill grows.

### 5.3 Weapons: pick the right damage type

Weapons split into four practical categories (Weapon page):

- **Slashing** (battle axe, short sword): cut gashes, sever body
  parts. Fastest against unarmored enemies; far less effective against
  armor, which converts cuts into weak blunt damage. Short swords are
  jacks of all trades and masters of none, with an occasional piercing
  attack that helps against armor. Obsidian short swords can be made
  at a craftsdwarf's workshop with one obsidian stone plus one log,
  outside the metal industry chain.
- **Crushing** (war hammer, mace): smash through armor, break bones,
  and the pain makes living creatures give in and fall unconscious.
  Slower to kill unarmored enemies than slashing weapons. The right
  choice against armored goblins and trolls.
- **Piercing** (spear, pick, crossbow bolt): punch through armor and
  damage internal organs, but can get stuck in the target. Picks use
  the mining skill, so a miner-drafted squad trains by mining.
- **Ranged** (crossbow): piercing damage from a distance, useless as
  a melee weapon. Needs bolts and a quiver, and the ammunition
  pipeline below.

The harness chooses weapons from what the fort can make (one bar of
metal per weapon at a metalsmith's forge; crossbows and bolts also
from a bowyer's workshop in wood or bone, 25 bolts per bar or log,
5 per bone) and from what the enemy wears. Against unarmored wildlife
and thieves, axes are fine. Against armored siegers, hammers. The
agent never picks a weapon type by name alone; the harness names the
weapon, the material, and the have/need count.

### 5.4 Ammunition

Marksdwarves need a quiver (they will not hold a stack of bolts in
hand), an archery target per dwarf, and 100-200 bolts assigned per
dwarf. Hunters reserve 25 bolts each, so the ammo stockpile must hold
more than 25 per hunter before marksdwarves see any of it. The
dwarves choose their own ammunition and may waste good metal bolts
training and fight with wooden ones; the harness should keep training
bolts (wood/bone) and war bolts (metal) in separate stockpiles and
assign accordingly. UNVERIFIED for 0.47.05: the Squad page describes
a v50 bug where a squad records the fortress ammunition count at
creation and never updates it, so a squad created with no bolts never
uses ammunition until it is disbanded and recreated. The wiki text is
v50-specific; the harness must confirm live on r8 whether the same
behavior exists before it relies on the disband-and-recreate
workaround.

### 5.5 Equipment checks the harness runs

For every uniform item, before the squad is formed: have (exact stock
count from a fresh collect), need (per dwarf times squad size),
source (forge, leather works, craftsdwarf's workshop, trade), and
time (bars, logs, hides on hand). If short, the harness queues the
production (smelt, forge, tan) as a composed task and tells the agent
when the squad will be ready. If the fort cannot make the item at all
(no forge, no metal), the squad is not formed and the agent is told
the blocker and the fix, not given a squad of unarmed dwarves.

## 6. Alerts and burrows

Alerts and burrows are how the fort survives the minutes between
"hostiles spotted" and "squad in position". They are also the part of
the military with the least DFHack support, and the plan is honest
about that.

### 6.1 Alerts

An alert is a named state a squad can be set to, and each alert
carries its own schedule per squad. The defaults are Inactive and
Active/Training, which are useless without more alerts and scheduling
(Military F.A.Q.). The harness defines four alerts:

- **Peacetime**: squads train or patrol on rotation; civilians work
  normally.
- **Invasion**: all squads to their battle stations; civilians to the
  shelter burrow (see 6.2).
- **Caravan Guard**: squads patrol the trade route and defend the
  depot burrow while traders are on the map.
- **Lockdown**: civilians to the shelter burrow, squads to the
  entrance choke point, entrances sealed. Used when the threat is
  inside the fort or the squad cannot win in the open.

Swapping alerts is the whole management interface: one command changes
every squad's programming at once. The agent never edits a schedule
by hand; it picks an alert by name and the harness applies it.

### 6.2 Burrows

A burrow is a user-defined area that restricts which jobs a dwarf
accepts and which items they use. Citizens assigned to an active
burrow only accept jobs inside it, and will not leave it to fetch
materials for a job. Burrows do not restrict movement: an idle dwarf
can stroll out of a burrow, and a dwarf can walk between two parts
of a burrow across ground that is not in it. (Burrow page.)

The pattern the harness uses is the suspended panic burrow: define a
safe burrow (inside the fort, with food, drink, beds, and a well if
one exists), keep it suspended by default so it does nothing, and
activate it when a threat shows up to pull civilians back inside.
The wiki recommends exactly this as the replacement for the old
civilian alert (Burrow page). A burrow must contain everything the
dwarves assigned to it need, or they will cancel jobs in a loop: food,
drink, beds, and the workshops they work at, or they starve inside
their own shelter.

In 0.47.05 a civilian alert is a military alert that confines all
civilians and animals to a set of burrows (Civilian alert page). The
underlying state is `df.global.ui.alerts`: a list of entries with id,
name, and a vector of burrow ids, plus `next_id` and `civ_alert_idx`
(the active alert, -1 for none). Each squad also carries
`cur_alert_idx`. No DFHack API creates an alert, no script creates
one, and the alert entry type is an anonymous compound with no
discoverable Lua constructor name. The live investigation must
determine whether the entry can be constructed, or whether the only
viable path is cloning an existing entry or using whatever default
alert the game creates. It must also read whether a fresh fort
already has a default alert entry.

### 6.3 Burrow creation: the investigation

There is no DFHack create for burrows. The route, from
`ADVANCED_MECHANICS.md` section 7, is direct struct construction,
and it is unproven. The investigation, in order:

1. Create a burrow by hand in the UI on the scratch fort. Read every
   field off it: id, name, the `tile` uint8 field (semantics not
   documented anywhere; do not guess), fg_color, bg_color,
   limit_workshops, and the block_x/block_y/block_z vectors.
2. Construct one in Lua: `df.burrow:new()`, id from
   `df.global.ui.burrows.next_id` (increment it), name, colors copied
   from the UI-created burrow, insert into
   `df.global.ui.burrows.list`.
3. Tiles: do NOT hand-build `BlockBurrow` entries first. Test whether
   `dfhack.burrows.setAssignedTile(burrow, {x, y, z}, true)` per tile
   works on the hand-inserted burrow (it should maintain the
   burrow's block vectors and the block's tile bitmask). Tile
   membership lives per map block (`MapBlock.block_burrows`, a linked
   list of `BlockBurrow` with id and a 16x16 tile bitmask), not in
   the burrow itself, so the setAssignedTile route is the only safe
   first try. If it errors or silently drops tiles, fall back to
   constructing `BlockBurrow` entries in each block's list. That path
   has no precedent and is the riskiest step.
4. Units: `dfhack.burrows.setAssignedUnit(burrow, unit, true)` per
   citizen; it should populate `unit.burrows`.
5. Verify live: the burrow appears in the burrow UI list, its tiles
   highlight, `unit.burrows` is populated, civilians actually
   restrict to it under an alert, and it survives save and load.

If no route exists after that investigation, the plan's fallback is
explicit: report exactly what was tried and what blocked it, as a
finding, not a punt. The harness then cannot create burrows, cannot
use the suspended panic-burrow pattern, and must say so in the
snapshot and the briefing. Shelter then means sealing entrances and
stationing the squad at the choke point, and the agent is told the
burrow option is unavailable and why. The burrow investigation is
phase 4; nothing in the invasion response depends on it succeeding
silently.

## 7. Invasion response as a composed sequence

An invasion is not one action. It is a sequence, and the harness runs
it as a composed task with a step for each stage, end-effect
verification per step, and a named failure at any step. The stages:

1. **Detect.** The INVASION handler fires, or the poller sees a new
   hostile. The event carries what was seen: race, count, position,
   and whether it is a siege (SIEGE tag) or an ambush (invisible
   until spotted). The game pauses at critical threat distance.
2. **Assess.** The harness counts the attackers, reads their equipment
   class where the observation layer allows it, measures distance to
   the entrance and to the nearest citizen, and checks the fort's
   state: squad size and skill, equipment, trap coverage at the
   entrance, whether the entrance can be sealed (drawbridge, doors),
   and whether civilians are outside. The assessment is the agent's
   decision surface: it names the threat and the fort's readiness in
   plain words.
3. **Alert.** Set the Invasion or Lockdown alert, activate the shelter
   burrow if it exists, and recall civilians. This is the step that
   saves lives: dwarves keep working outside unless they are stopped.
4. **Seal or muster.** If the squad cannot win in the open, seal the
   entrance (raise the drawbridge, lock the doors) and wait the siege
   out behind cover. If the squad can win, muster it at the choke
   point behind the traps, not at the map edge. Never send the squad
   to meet a siege in the open field.
5. **Position.** Station the squad at the chosen point: behind
   fortifications for marksdwarves, at the choke point for melee.
   Guard animals at the entrance act as an alarm for thieves and
   ambushers who are invisible until something detects them
   (Security design).
6. **Fight.** Issue the kill order on the named target. The harness
   must be honest here: once dwarves are in combat, they pursue any
   hostile they meet and there is no reliable way to extract them.
   It is do or die (Military page). The harness never issues a kill
   order it has not assessed as winnable, and it says so when it
   refuses one.
7. **Stand down.** When the SIEGE tag clears and the attackers retreat
   to the map edge, or the last attacker dies, cancel the alert, lift
   the burrow, and return squads to their peacetime routine. Do not
   chase retreating attackers off the map.
8. **Treat the wounded.** Hand off to the hospital plan (step 10
   breadth, not yet built): diagnosis, wound care, traction benches.
   Until the hospital lands, the handoff is a named gap: wounded
   dwarves are listed with their wounds and the agent is told the
   hospital does not exist yet.
9. **Clear up.** Corpses to the refuse stockpile (miasma and
   reanimation risk if left), loot collected (goblinite: weapons and
   armor the attackers dropped, which is also the fort's early metal
   supply), traps checked for jamming and reset, and the entrance
   re-opened only after a sweep confirms no hostiles remain.

### 7.1 What the fort is up against

The threat taxonomy comes from the Defense guide, and the response
depends on which one it is:

- **Wild animals**: usually excluded by a door; a lone predator flees
  a stronger force. A single animal is a nuisance, not a battle.
- **Thieves and child snatchers**: invisible until spotted, bypass
  locked doors, avoid traps imperfectly, armed. Guard animals and
  cage traps are the answer, not a squad.
- **Ambushes**: a small force (under 10), invisible until spotted,
  announced as "An ambush! Curse them!". They skulk outside looking
  for wandering dwarves or caravans, and often flee if challenged.
  When the ambush leader is killed or captured, the rest stand around
  waiting for him, which is probably a bug (Ambush page).
- **Sieges**: a large organized force, announced immediately, SIEGE
  tag for the duration. They begin once the fort reaches 80 citizens
  (undead excepted, any time). On normal difficulty, 25% of invasions
  are sieges instead of ambushes. At most 120 soldiers and 40 monsters
  per siege. They bring trolls who dig through walls and build stairs
  over moats, battering rams, and sometimes mounted squads, some of
  which fly. Caravans do not arrive at a besieged fort, and a long
  siege can cost the year's caravan entirely. Invaders avoid traps
  they have seen sprung, and if any flee, their knowledge persists
  into the next siege: traps should be torn down and rebuilt in a new
  place between sieges. In winter, a frozen moat is a road, not a
  barrier (Siege page).
- **Enemy archers**: worth separate mention because they are much more
  threatening than melee attackers. Do not out-shoot them with
  inexperienced marksdwarves and do not charge them with untrained
  melee. Well-trained, well-armored melee, or fortifications.
- **Building destroyers**: tear apart doors and workshops. Only
  constructions (built walls, floors) and bridges are safe.
- **Flying creatures**: melee units cannot reach them. The fort needs
  ranged cover or the fliers must be lured down.
- **Werebeasts**: stealthy, extremely strong, avoid traps, destroy
  buildings, and a bite can infect a dwarf. **Vampires**: disguised
  as ordinary dwarves, drink the blood of sleeping dwarves, and do
  not need food, water, or air. Neither is handled by a squad alone;
  both are named as threats the harness must detect and report, not
  as fights it can win by drafting more soldiers.

## 8. Patrols and stationing

Patrols and stations are the passive orders that keep the fort safe
between battles, and they are cheaper than a standing army at the
gate. A schedule can carry them per month, with criteria for how many
soldiers follow each order at once, so part of a squad can patrol
while part trains (Scheduling page).

- **Station**: the squad stands at one point. Used for the entrance
  choke point, the depot during a caravan, and the archery platform
  above the entrance.
- **Patrol route**: the squad walks a route. Used for the trade route
  while a caravan is on the map, and for the fort's perimeter once
  the fort is big enough to have one.
- **Defend burrow**: the squad defends a burrow. Used for the depot
  burrow and the shelter burrow.
- **Guard animals**: a restrained or pastured animal in a 1- or
  2-tile hallway is a thief-proof alarm: no invisible enemy can pass
  without bumping into it, and the game pauses with the announcement.
  Place them around a corner or behind a U-bend so archers cannot
  shoot them, deeper in the entry behind traps, and inside so fliers
  must come down to their level (Security design). This is the
  cheapest early-warning system in the game and the harness should
  use it before it has any squad at all.

The scored site selection work applies to stations and patrol routes:
a station is scored like any other site, and a patrol route must not
run through the main corridor or block the only path.

## 9. Trap integration at choke points

Traps are the fort's first line, and the military is the second. The
two must be planned together: the choke points between the concentric
circles of the defense are where traps go, and where troops station
(Defense guide). The trap types, from the Trap design page:

- **Stonefall trap**: the easiest to build, one mechanism, no lever.
  Good in numbers around intersections and stairways, and a good way
  to train a mechanic.
- **Weapon trap**: the gold standard, works repeatedly without
  reloading, but jams when a corpse is inside it. Hammers jam less
  than swords or axes, spears jam the most. Crossbows in weapon traps
  do not jam at all, but must be kept loaded with ammunition. Put the
  deadliest traps closest to the fort and the weaker ones further out.
- **Cage trap**: never fails, and even a wooden or glass cage holds
  any creature indefinitely, including trolls and megabeasts. Only
  creatures with the trapavoid tag escape capture unless knocked
  unconscious or webbed. Captured invaders are brought to the animal
  stockpile, but their allies will try to free them.

Trap creation is itself missing work: the harness has no trap build
action yet (ADVANCED_MECHANICS.md section 4: sites already exist,
the creation route is the missing piece, and `act_build.lua`'s
subtype lookup must be generalized first). The military plan depends
on traps existing, so trap creation lands before or alongside the
military, not after it. The harness must also remember that invaders
learn trap locations: after a siege, traps are torn down and rebuilt
elsewhere, and the harness must track which traps have been observed
sprung.

Fortifications matter for the same reason: marksdwarves shoot through
them, and they are the only safe archery platform. A drawbridge over
the entrance stairwell isolates the surface at the pull of a lever
and is the cheapest real defense in the game (Security design). Lever
linking is itself unresolved (no DFHack "link lever" API was found;
`advfort.lua` fake_linking and `lever.rb` are partial precedents), so
the drawbridge plan must include the lever-link investigation, and
must not promise a working drawbridge until the link is verified live.

## 10. After a battle

- **Wounded**: handed to the hospital plan. Until it exists, the
  harness lists wounded dwarves with their wounds (the observation
  layer already collects wounds per citizen) and names the hospital
  as a gap. A dwarf that survives a battle with a broken leg and no
  care will die of infection or thirst in bed; the harness must not
  call a battle "won" while its wounded are untreated.
- **Corpses**: to the refuse stockpile, promptly. Left corpses cause
  miasma indoors and, worse, are raw material for a necromancer
  ambush. The harness must not leave a battlefield unswept.
- **Loot**: weapons and armor dropped by attackers (goblinite) are
  collected and counted. In the early fort this is the main source of
  metal: a dead goblin's iron axe is worth more than the iron the fort
  cannot yet smelt. The loot is checked against the never-sell list
  and the equipment have/need counts before any of it is sold or
  melted.
- **Siege end**: confirmed only when the SIEGE tag is gone and no
  hostile remains on the map. The harness verifies this from a fresh
  collect, not from the absence of new events.
- **After-action**: the battle is recorded in the journal and the
  diary feed (who fought, who was wounded, who died, what was looted),
  and the scoring system's lives and threats dimensions pick it up.
  The harness also records which traps were observed sprung, so they
  can be rebuilt elsewhere before the next siege.

## 11. The harness's role at each step

The harness decides; the agent chooses among named options. The model
never guesses coordinates, never reasons about radii, and never edits
a schedule by hand. What the agent sees, per step:

- **Formation**: "Form a 5-dwarf axe squad (you have 5 spare dwarves,
  3 axes on hand, no bolts)" or "Wait: no forge yet, the squad would
  be unarmed". One line why each.
- **Training**: "Set the squad to constant training (2 dwarves at
  competent, sparring will start)" or "Rotate to patrol this month
  (training is done, the caravan is coming)".
- **Equipment**: "Forge 5 iron axes (have 2 bars, need 5)" or "Buy
  steel from the next caravan (no iron on this map)".
- **Invasion**: "Seal the entrance and wait (squad of 3 cannot hold
  20 goblins)" or "Muster at the choke point (squad of 10, traps
  loaded, archers behind fortifications)". The assessment names the
  numbers on both sides.
- **Aftermath**: "3 wounded, 1 dead, 12 goblin axes looted" with the
  hospital handoff named.

What the harness refuses, or names as a failure:

- Never order a kill the squad cannot win. Once dwarves are in combat
  there is no extraction; the harness refuses an unwinnable attack and
  says why.
- Never send civilians outside during a siege or ambush.
- Never promise a burrow, alert, or trap that does not exist. The
  briefing drift is fixed in phase 1: every briefing option names an
  action the harness can actually do, or says the action does not
  exist yet and what to do instead.
- Never auto-dismiss a game-committing screen. The trade screen rule
  from docs/DIALOGS.md applies to any screen that commits the game.
- Never draft a dwarf with mining, woodcutting, or hunting labors
  without clearing them first, and never draft the fort's only
  specialist into a squad that will get him killed.
- Never claim a squad is trained, equipped, or stationed without a
  live read-back: the squad exists in `df.global.ui.squads.list`,
  its members carry the uniform, and its position matches the order.

## 12. Implementation phases, in order

Each phase lands only when its verification bar is met live. A mock or
a unit test alone is not verification.

1. **Fix the briefing drift.** Rewrite the invasion, hostile,
   new_arrival, and cavern_creature briefings so every option names
   an action the harness can actually do. Until the military lands,
   the honest options are: hold paused, watch, and seal the entrance
   only if a sealing action exists. Verification: offline tests for
   the new text; live attention output shows no promised action that
   does not exist.
2. **Military observation.** Read-only probes: squads from
   `df.global.world.squads.all` and `df.global.ui.squads.list`
   (id, name, members, positions, schedule, alert), burrows from
   `df.global.ui.burrows`, alerts from `df.global.ui.alerts`, and
   equipment per squad member. Expose as `GET /v1/military`.
   Verification: live read on a fort with a hand-made squad and a
   hand-made burrow; the read matches what the UI shows.
3. **Militia commander appointment.** Land the noble appointment
   route (step 2 remainder) and appoint the commander. Verification:
   live read-back via `dfhack.units.getNoblePositions(unit)`; the
   commander appears in the nobles screen.
4. **Burrow investigation.** The five-step investigation in section
   6.3, on the scratch fort, with a UI-created burrow as the
   reference. Verification: burrow in the UI list, tiles highlight,
   `unit.burrows` populated, civilians restrict under an alert, and
   it survives save and load. If no route exists, report the
   evidence and take the fallback in 6.3.
5. **Squad creation investigation.** Direct struct construction from
   section 2: construct a squad in Lua, assign members, insert into
   both squad lists, set `unit.military.squad_id` and
   `squad_position`. Verification: the squad appears in the military
   screen, its members show the squad, and it survives save and
   load. If no route exists, report the evidence. This is the
   hardest step in the plan; it is allowed to take the longest.
6. **Uniforms and equipment.** Write the uniform spec (starter, then
   basic), assign it to the squad, and run the have/need checks per
   item against fresh collects. Verification: live read-back of each
   member's equipped items against the uniform, on the scratch fort
   first, then the main fort.
7. **Barracks and training.** Build the per-furniture room assignment
   write path, designate a barracks, assign the squad to train there,
   and set Constant Training. Verification: live observation of
   demonstrations and sparring over a full in-game day, with skill
   gains recorded; the training-class hang bug checked live and the
   alternating schedule applied if it reproduces.
8. **Alerts and routines.** Create the four alerts (Peacetime,
   Invasion, Caravan Guard, Lockdown), build per-squad monthly
   schedules, and wire alert swapping as a harness action.
   Verification: live swap changes squad behavior as scheduled.
9. **Invasion response task.** The composed sequence from section 7,
   as a `task:military_response` with per-step verification.
   Verification: a live ambush or a synthetic hostile on the scratch
   fort, run end to end, with the after-action record complete.
10. **Patrols, stations, guard animals.** Patrol routes, station
    orders, and pastured guard animals at the entrance.
    Verification: live observation of a squad following a patrol
    route and a guard animal detecting a thief or ambusher.
11. **Trap integration.** Trap creation (from ADVANCED_MECHANICS.md
    section 4) plus choke-point trap placement and the
    rebuild-after-siege rule. Verification: a live trap built, sprung
    by a hostile, and rebuilt elsewhere.
12. **Post-battle.** Hospital handoff, corpse sweep, loot collection,
    siege-end verification, after-action record. Verification: a live
    battle followed end to end, with the diary entry and the score
    reflecting it.

## 13. Open questions (UNVERIFIED)

- Squad creation: no DFHack creation API exists. The direct
  construction route is inferred from struct fields, with no
  precedent. The id source, the two-list insertion, and the member
  assignment are all unproven until phase 5 runs live.
- Burrow creation: the five-step route in 6.3 is plausible and
  unproven. The `tile` uint8 field's meaning, the burrow colors, and
  the `BlockBurrow` fallback are all unknown until the investigation
  reads them off a UI-created burrow.
- Civilian alerts: no constructor name exists for the alert entry.
  Whether it can be constructed, cloned, or must be a default entry
  is unknown until phase 8 investigates live.
- Barracks assignment: the per-furniture write path has no precedent.
  Whether writing `BuildingSquadUse` and mirroring `squad.rooms`
  makes the game accept the assignment is unknown until phase 7.
- Orders: the order structs exist, but no precedent exists for
  inserting one into `squad.orders` and having the game execute it.
  Unknown until phase 5 or 9.
- Marksdwarf ammunition: the v50 bug where a squad records the
  fortress ammunition count at creation and never updates it may or
  may not exist on 0.47.05-r8. Unknown until tested live.
- Training-class hang: the leader-waiting-forever bug is described
  for the current release. Whether it reproduces on 0.47.05-r8 is
  unknown until phase 7 checks.
- Lever linking for drawbridges: no DFHack link API was found.
  Whether a real link can be written, or only the fake_linking
  precedent, is unknown until the trap work investigates it.
- Uniform write path: no script writes a uniform spec or assigns an
  item to a squad member. Whether `SquadPosition.uniform` and
  `SquadUniformSpec` can be written and honored is unknown until
  phase 6.
- The 80-citizen siege trigger, the 120-soldier and 40-monster siege
  cap, and the 25% siege rate on normal difficulty are wiki claims
  from the Siege page. They are consistent with long-standing DF
  behavior, but the harness has not observed a siege live yet, so
  they are UNVERIFIED against this fort.

## 14. Sources

Wiki (local index, `~/workspace/df-wiki-export/dfq.py`): Military,
Squad, Training, Military design, Military quickstart, Military
F.A.Q., Scheduling, Armor, Weapon, Burrow, Civilian alert, Defense
guide, Security design, Siege, Ambush, Trap design, Danger room.

Harness: `docs/ADVANCED_MECHANICS.md` section 7 (squad and burrow
research, lever linking, build order), `src/dfagent_harness/events.py`
INVASION handler, `src/dfagent_harness/briefings.py` (briefing drift),
`src/dfagent_harness/planner.py` threat tiers,
`~/workspace/goals/dwarf-fortress-0-47-05-autonomous-play-harness/GOAL.md`
step 10 (breadth order: military first) and the emergent-gameplay
principle (acceptance: survive an invasion through preparation and
response, not luck).

Fort state: `~/.config/df-agent-harness/world.db` snapshot, tick
115166, 2026-11-27 (7 citizens, Carpenters #7 and Still #8 only,
drink 97, food 23, wood 117, stone 0).
