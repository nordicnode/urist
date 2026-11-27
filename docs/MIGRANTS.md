# Migrants

A design record for how the Urist harness handles migrant waves: detecting
them, reading what each migrant brings, assigning them work and a bed,
scaling the fort to feed them, and telling the agent about the wave in a
form it can act on without drowning in detail.

Status: design only. No code in this doc is implemented yet. Anything marked
UNVERIFIED is a claim the wiki or the live game has not confirmed; the phase
that must prove it is named next to it.

Companion docs: `LABOR.md` (labor assignment and training; being drafted in
parallel), `FARMING_PLAN.md` (the season-ahead food rule), `MILITARY.md`
(commander appointment depends on the noble route), `TRADING.md`
(wealth reporting drives wave size; the buy list covers seed and food
shortages), `SITE_SELECTION.md` (queued; bedroom scoring), `HISTORY.md`
(queued; waves belong in the per-season history file), `DIALOGS.md`.

## 1. Purpose

A migrant wave is the fort's main source of growth and its main source of
chaos, in the same arrival. One wave can bring a legendary weaponsmith the
fort could not train in a year, and in the same group bring three children,
a wounded veteran, and a dwarf with no skill the fort needs. The harness
must do the triage: who is who, what the fort gains, what it now owes in
food, drink, and beds, and what the agent should do first. The agent never
reads raw unit records to do this. It gets a per-wave summary naming each
migrant with their skills and the suggested assignment with a one-line why,
the coverage gaps the wave fills, and what is still missing.

## 2. How migration works in 0.47.05

Source: wiki page "Immigration", plus "Children", "Experience", "Noble".
The wiki export tracks v50 in places; where a claim is about the interface
rather than the simulation, it must be verified live against 0.47.05.

- Waves arrive in groups once per season. The group spawns at the edge of
  the map and marches to the nearest meeting hall. A notification is
  received on arrival.
- The first two waves are hardcoded: they arrive in the first two seasons,
  size 2 to 10, minimum 1, maximum 10. They are unaffected by fortress
  wealth, danger, or the extinction of the home civilization.
- There is never a migration in the first winter. Not even a "no migrants
  this season" message.
- After the first two waves, migrants arrive only once the fortress has
  accumulated enough created wealth, and that wealth must be reported by
  visitors such as merchants. A trade does not have to happen, but the
  caravan has to leave. If the caravan fails to make it out, the wealth is
  not reported. If the liaison makes it out but the caravan does not, the
  liaison does not report on fortress wealth.
- Created wealth is what drives wave size after the hardcoded waves, as
  reported by the last outgoing dwarven caravan. Wealth created after the
  caravan leaves has no influence until the next year's caravan leaves.
  Imported wealth, caravan sales figures, absolute caravan profit, and
  profit margin have no effect, or only a percent modification on top of
  the created-wealth number.
- Trading away 100 percent of the fort's created wealth means no
  immigrants will come the next season. This is a trap the harness must
  never walk into blind: selling everything to the caravan can shut off
  migration entirely.
- The number of migrants is also affected by how far below the population
  cap the fort is. One dwarf short of the cap means one migrant at most.
- Wave size is capped by the total size of the fort's units list (dwarves,
  invaders, merchants, and animals, living and dead). At a local
  population of 1000, wave size is limited to 10; the limit drops by 1 at
  1300, 1600, 1800, 2000, 2200, 2400, 2600, 2800, and 2900; at 3000 there
  are no migrants at all. The game culls unimportant dead units
  eventually (`CULL_DEAD_UNITS_AT`); DFHack has `fix/dead-units` to clear
  uninteresting dead units and let migrants arrive again.
- The largest wave reported is 77 dwarves.
- Migrant skills are influenced by the fort's needs: migrants with skills
  the fortress uses a lot, or that the fortress does not have at all, are
  more likely to show up. Important skills (mining, food production, and
  basic crafting) are weighed more heavily than other skills.
- A migrant can arrive with any skill, at levels as high as Legendary,
  including skills that cannot be obtained in fortress mode (tracking,
  pikedwarf) and obscure military skills. Migrants may bring equipment
  matching their skills; a miner migrant may bring a pick.
- Many migrants were pre-existing historical figures, with skills from
  their history, or wounds suffered during world generation. They may even
  be vampires or werebeasts. Necromancers and intelligent undead from
  previous player fortresses may also immigrate.
- Migrants come from all walks of life, including children and domestic
  animals, pets and stray livestock.
- If the fort has no meeting hall, a single migrant can fail to find the
  fort and stand at the edge of the map, not moving at all. Worse, the
  rest of the wave cannot enter the map until that migrant moves out of
  the square, since all migrants in a single wave must enter through the
  same square.
- Dangerousness and unhappiness deter migrants. Dangerousness is the sum
  of recent deaths, executions, and insanities over the past 5 years,
  weighted down each year (1, then 1/2, 1/4, 1/8, 1/16, 1/32). A death
  discourage number of 0 to 9 is normal, 10 or more is "danger" or
  "dangerous", 50 or more is "cursed death trap" or "tomb". Migrants may
  refuse to journey at all, and the refusal message names the reason.
- A civil war in the home civilization blocks standard immigration after
  the two hardcoded waves.
- If the fortress becomes a mountainhome, it receives an additional
  migration wave with the promotion, regardless of the population cap.
- Population Cap and Strict Population Cap are settings in the game tab.
  Population Cap stops immigration at the number; Strict Population Cap
  stops immigration and babies. Neither removes dwarves already present.
  Both can be violated in a few special cases, such as the arrival of a
  monarch. Changing the caps does not change population requirements such
  as the 80 needed for a king.
- A minimum population of 20 is needed before any dwarf will experience a
  strange mood.
- Undesirable migrants can be expelled from their individual preferences
  screen. This is a last resort, not a routine tool; see section 12.
- DFHack has a `list-waves` command to check which wave a dwarf arrived
  in. Useful for verification, not a harness dependency.

## 3. What the harness knows today

Verified against the repo on 2026-11-27.

- Arrival detection exists and works. `events.py` `DiffDetector` emits
  `new_arrival` events for every unit that appears in the "other units"
  set (wildlife, visitors, migrants in transit), and `citizen_new` /
  `citizen_gone` events for citizens joining or leaving the citizen list.
  Both are edge-triggered with a dedup key per unit id. `attention.py`
  lists arrivals in plain words, threats first, then new arrivals. An
  arrival stays in attention for one in-game day after its tick; a
  baseline arrival (already present at the first snapshot) stays for 7
  in-game days.
- The event taxonomy already has `citizen_new` wired into briefings
  (`briefings.py`) and the diary feed (`diary.py`, `dwarves.py`). The
  pipeline for announcing a new citizen exists; nothing yet groups
  several `citizen_new` events into one wave.
- The units collect (`lua/units.lua`) reads per citizen: id, name, race,
  profession and profession id, sex, age, position, idle state, current
  job, mood, stress level and category, hunger/thirst/sleepiness
  counters, needs, skills, enabled labors, relations, wounds, and goal.
  Skills carry the skill name, the rating name, the numeric rating, and
  the exact experience points, but only for skills with rating above 0.
- What it does NOT read: attributes (strength, agility, toughness,
  endurance, recuperation, disease resistance, and the rest). No
  attribute field exists in `units.lua` or `probe_unit.lua`. Skill
  assessment therefore cannot use attributes until a collect for them
  lands. See phase 2.
- `labor_toggle` exists in `actions.py` and is verified with read-back.
  Assigning a labor to a named dwarf is already a working action.
- `appoint_noble` exists in `ui.py`, but it drives the nobles screen
  with xdotool keystrokes, and the Lua-write path was verified live on
  2026-11-26 to NOT register (the nobles screen stays VACANT). The UI
  path works, but it is a keystroke path, and the harness rule is that
  game actions go through the harness API, not the UI. Landing a
  programmatic noble-appointment route is step 2 remainder work and is
  also the blocker for the military plan's commander appointment. Until
  it lands, migrant-driven noble appointments cannot be automatic; the
  harness can only recommend them. See section 11 and phase 3.
- The fort's current state: Erushtathtat, 125-04-12, 7 citizens, no
  migrant wave yet. The fort is 11 days past embark, so no season
  boundary has been crossed and no wave is due yet. The journal has no
  `citizen_new` events. The first hardcoded wave is expected in the
  first two seasons; the first winter will bring none.
- `docs/LABOR.md` and `docs/SITE_SELECTION.md` do not exist yet. Labor
  is being drafted in parallel as a companion doc; site selection is
  queued work. This doc treats both as companions, not as existing work.
- The farming plan (`docs/FARMING_PLAN.md`) already carries the
  season-ahead rule: plan food production a season ahead of migrant
  waves, and grow the system as migrants arrive. This doc owns the wave
  side of that rule; the farming plan owns the food side.
- There is no wave summary, no skill assessment, no assignment
  suggestion, and no housing allocation anywhere in the harness today.
  A wave currently arrives as N separate `citizen_new` events and a set
  of attention lines. That is the gap this plan closes.

## 4. Arrival detection and the alert

The wave is one event, not N events. Detection is grouping, not new
observation.

- The daemon already sees each migrant twice: once as a `new_arrival`
  while they are in transit at the map edge, and once as a `citizen_new`
  when they join the citizen list. The wave detector groups
  `citizen_new` events by in-game season (and by arrival tick proximity:
  same season, within one in-game day of each other) into a single wave
  record. A wave that straddles a season boundary is one wave, not two;
  the grouping key is the arrival tick window, the season is a label.
- The wave record carries: season and year, count, the list of unit ids,
  and per migrant the fields the units collect already provides. The
  record is written to the journal and to the per-season history file
  (see `HISTORY.md`, queued) at the same time the wave is announced.
- The alert the agent sees names the wave as one item: "7 migrants
  arrived in spring 125: 2 planters, a brewer, a miner, 2 children, and
  a dog." The per-migrant detail lives behind the query route, not in
  the snapshot. The snapshot carries the wave summary line and the top
  three suggested assignments; the full per-migrant table is one query
  away.
- The meeting-hall check is a precondition, not an afterthought. Before
  the first wave season, the harness verifies a meeting hall zone
  exists and is reachable from the map edge. If there is none, the
  suggestion is to designate one, with the reason in plain words: a
  migrant with no hall can stand at the edge and block the whole wave
  behind them. This is a standing suggestion, not a wave-time scramble.
- A stuck migrant is a diagnosed failure, not a mystery. If a
  `new_arrival` unit has not become a citizen and has not moved in a
  bounded window, the diagnosis names it: the migrant is stuck at the
  edge, the likely cause is no reachable meeting hall, the fix is to
  designate one or clear the path. UNVERIFIED: the exact tick window
  and the position-history read the diagnosis needs; phase 1 proves it
  against the live game.
- A refused or deterred wave is also an event. If the season passes with
  no wave and the fort is past its hardcoded waves, the harness says so
  plainly and names the most likely cause it can verify: wealth not yet
  reported by a caravan, the population cap reached, or the fort's
  danger/unhappiness level. It never guesses between those; it reports
  the ones it can check (wealth reported, cap distance, recent deaths)
  and says which it cannot.
- Migrants arriving during a siege or crisis are handled by section 12,
  not by the normal path. The wave detector must not suggest bedroom
  construction while the fort is under attack.

## 5. Skill assessment

The assessment answers three questions per migrant: what can they do
better than anyone already here, what do they add that the fort lacks
entirely, and what are they best used for right now.

- Skill levels come from the Experience page, and the harness already
  reads the numeric rating and exact experience per skill. The titles:
  0 Dabbling, 1 Novice (500 XP), 2 Adequate (1100), 3 Competent (1800),
  4 Skilled (2600), 5 Proficient (3500), 6 Talented (4500), 7 Adept
  (5600), 8 Expert (6800), 9 Professional (8100), 10 Accomplished
  (9500), 11 Great (11000), 12 Master (12600), 13 High Master (14300),
  14 Grand Master (16100), 15 Legendary (18000) and beyond. Most
  civilian skills give 30 XP per use, plus 30 more if the item produced
  has quality levels. Mining, engraving, smoothing, and stone blocks
  give 10 XP per use. A strange mood completion grants 20,000 XP in
  the affected skill, enough to take a dabbling dwarf to Legendary.
- Skills above dabbling rust if unused for months. Advanced rust is
  permanent experience loss. A migrant with a high skill the fort never
  uses will lose it. The assessment must therefore weigh the fort's
  actual use of the skill, not just the rating. A legendary engraver in
  a fort with nothing to engrave is a future dabbling engraver.
- The wiki's migrant tier list is the starting point, adapted to the
  fort's needs, never applied blindly. A-tier (valued): weaponsmiths,
  armorsmiths, soldiers, planters, mechanics, cooks. B-tier (stalwarts):
  miners, carpenters, stone carvers, stonecrafters, engravers, brewers,
  healthcare, furnace operators, wood burners, leatherworkers.
  C-tier and below are niche skills. The wiki's own caveat is the rule:
  the most valuable skill is the one the fortress needs most. A
  legendary potter in a fort with no clay is worth less than a competent
  miner in a fort that needs digging.
- The game itself weights migrants toward the fort's needs: skills the
  fort uses a lot, or does not have at all, are more likely to appear.
  The harness reads the wave in the same frame. For each migrant, the
  assessment computes a coverage delta: for each of their skills at
  rating 3 (Competent) or above, whether the fort already has that skill
  at equal or higher rating, whether the fort has it at all, and whether
  the fort's production chains are waiting on it. A skill the fort lacks
  entirely scores highest; a skill that duplicates the fort's best
  scores lowest; a skill in the middle scores on the gap between the
  migrant's rating and the fort's best.
- Specialist vs generalist. A migrant with one skill at 10 or above is a
  specialist: assign them to that skill and protect their time. A
  migrant with several skills at 3 to 5 is a generalist: assign them to
  the fort's thinnest coverage, and they are the first call for new
  workshops. A migrant with no skill above 2 is unskilled for now: they
  haul, they train, they are not a specialist. Children are assessed
  separately (section 10).
- Military skills count. A migrant with combat skills is a soldier
  candidate even if their civilian skills are thin, and an experienced
  soldier can teach. The military plan owns the squad side; this doc
  owns the identification side: the assessment flags combat-rated
  migrants with their weapon skill and rating.
- Social skills count too. A migrant with high social skills is a broker
  or manager candidate (section 11), and a high organizer is the
  manager's real qualification: each approved work order is worth 100
  organizer XP regardless of size.
- Skills that cannot be obtained in fortress mode (tracking, pikedwarf)
  are noted, not scored. They are flavor, not a job.
- Wounds and equipment are part of the assessment. A migrant with wounds
  from world generation goes to the health check first (section 12). A
  migrant who brought a pick is a miner who arrives equipped; the
  assessment says so, because it changes the have/need math for tools.
- The assessment output per migrant is one line: name, top two skills
  with ratings, the coverage verdict ("only brewer", "best miner",
  "duplicates Olon"), and the suggested assignment with a one-line why.
  The full skill table is behind the query route.

## 6. Labor assignment

First assignments happen fast, training happens deliberately, and nobody
is assigned to a job they cannot do or that starves a more urgent need.

- The assignment rule, in order: fill a coverage gap the fort has
  (nobody does it, or the only one doing it is overloaded), then deepen
  the thinnest production chain, then train. A migrant's first labor is
  the highest-scoring coverage gap they can fill at rating 3 or above.
  If they fill no gap, they haul and train toward the fort's next gap.
- Never assign the only planter or the only brewer away from their
  skill. The assessment names single points of failure; the assignment
  rule refuses to create a new one. If the only brewer is a migrant,
  they brew. The fort's drink supply is not a training opportunity.
- The unskilled train on purpose. An unskilled adult gets one training
  labor, chosen from the fort's next gap, and a training source that
  actually produces experience: real jobs, not makework. The labor plan
  (`LABOR.md`, companion doc) owns the training mechanics; this doc
  owns the choice of who trains at what.
- Children get chores only (section 10). They are never assigned a
  production labor, never assigned to a squad, and never given a
  workshop.
- Assignment is a suggestion first, an action second. The agent sees the
  suggested labor per migrant with the one-line why and approves it; the
  harness applies it with `labor_toggle` and verifies the labor stuck
  by read-back, which the action already does. A refused assignment
  names the reason: the labor does not exist, the dwarf is a child, or
  the dwarf is wounded past the point of working.
- Reassignment is a decision with a cost. Moving a dwarf off a skill
  they are good at to cover a gap costs experience in the old skill
  (rust) and time in the new one. The harness says so when it suggests
  a move, and never suggests moving a specialist to cover a gap a
  generalist could cover.
- Migrants who arrive with a pet or livestock are recorded with the
  animal, not separated from it silently. The husbandry plan owns what
  happens to the animal; this doc owns noting the pairing in the wave
  summary so the agent knows the fort gained both.

## 7. Housing

Every migrant needs a bed, and the order beds get built in is a decision,
not a scramble.

- The housing check runs the moment the wave is detected: beds owned vs
  adults needing one, dormitory capacity vs owned-room capacity. The
  numbers come from the live buildings read, not from a count the
  harness remembers.
- Allocation order: wounded first (a bed in or near the hospital), then
  specialists whose work starts immediately (the brewer sleeps near the
  still), then everyone else in arrival order. Nobles get the rooms
  their position demands (section 11); everyone else gets the next
  free owned room, or a dormitory bed if no owned room is free.
- Dormitory vs owned rooms is a real tradeoff, and the harness states
  it. A 1x1 owned room generates happy thoughts; a dormitory carries a
  minor negative. The plan is: dormitory beds first, as the immediate
  answer, owned rooms as the standing build queue, one per new adult.
  The rooms plan (site selection, queued) owns the scoring of where
  those rooms go: quiet, near food and work, enclosed. This doc owns
  the queue: how many rooms, for whom, in what order.
- Bedroom construction is part of the wave response, not a separate
  project. The wave summary carries the bed deficit as a number ("3
  beds short") and the suggestion carries the build: how many beds,
  where, and in what order. The agent approves the build; the scored
  site selection picks the spots.
- A migrant who arrives while the fort has no free bed sleeps on the
  floor. That is a stress cost the harness reports, not a silent
  default. If the deficit is large, the suggestion is a dormitory first
  (fast, many beds) and owned rooms after.
- Children sleep with their parents where the game allows, and get their
  own room when they come of age. The housing check counts children in
  the bed math as sleepers, not as workers.

## 8. Food and drink scaling

Every new dwarf eats and drinks, and the fort's production must grow a
season ahead of them, not a season behind.

- The consumption numbers the plan uses, with sources: a dwarf eats
  about 2 meals per season (Fishing plan, from the wiki). A 3x3 plump
  helmet plot yields about 2,700 alcohol a year, enough for 95 dwarves
  (Farming plan, from the wiki), which is about 7 drink per dwarf per
  season. The trading plan's survival floors are 5 food, 1 log, and 5
  cloth or leather per dwarf. The farming plan's staple sizing is
  ceiling(population / 6) tiles at conservative yield, minimum 9, plus
  small plots per industrial crop. This doc does not invent its own
  consumption numbers; it uses these.
- The season-ahead rule (Farming plan): the fort plans food production
  a season ahead of migrant waves. The wave side of that rule is here:
  the harness forecasts the next wave from the wealth the last caravan
  reported, and sizes the farm and brew plan for the population the
  fort expects to have next season, not the population it has now.
- The wave response recomputes the floors immediately: new population,
  new food floor, new drink floor, new farm tiles needed, new barrels
  needed. The summary carries the delta ("7 to 14 dwarves: drink floor
  35 to 70 per season, farm needs 2 more staple tiles"). The farming
  plan owns the farm change; this doc owns the arithmetic that triggers
  it.
- Brewing to the drink floor comes before cooking the surplus. The
  farming plan's split rule applies: brew to the floor (population x 5
  per season plus one season reserve), process industrial crops, eat
  surplus raw, cook only above the reserve, trade the rest. A wave
  does not change the order; it changes the numbers.
- A wave that arrives when food or drink is already below the floor is
  a crisis, not a routine arrival. The response is the survival
  response first (gather, fish, hunt, trade for food) and the
  assignment response second. Section 12 covers it.
- Babies leech food and drink from their mother, who becomes hungry or
  thirsty at double the usual rate. The scaling math counts a baby as
  a second mouth on the mother, not as a separate consumer.

## 9. Population management

Growth is good until it is not, and the harness must know which side of
that line the fort is on.

- Welcome growth while the fort can feed, house, and employ it. The
  check is the floors: food and drink above the floor for the new
  population, beds for the new adults, and work for the new hands. If
  all three hold, the wave is good news and the summary says so.
- The cap is a setting, not a feeling. Population Cap stops
  immigration at the number; Strict Population Cap also stops babies.
  The harness reports the distance to the cap ("13 of 50") in the wave
  summary. UNVERIFIED: whether the harness can read or set the
  population cap through DFHack in 0.47.05-r8. Phase 4 proves it; if
  there is no route, the cap stays a human setting and the harness
  only reports the distance.
- What breaks first as population grows, in the order the harness
  watches: drink (brewing lags a season behind), beds (construction
  lags), food (farming lags), thenfps and pathing (not a harness
  problem yet at this fort's size, but the plan names it so a later
  phase can watch it), then the units-list cap on wave size (1000 and
  up; far off for this fort, but the mechanism is real and the plan
  records it).
- The wealth trap: trading away 100 percent of created wealth stops
  the next season's migrants. The trading plan already carries the
  never-sell discipline for artifacts and mandated items; this doc
  adds the migration consequence. Before a big sale, the harness checks
  whether the sale would zero the created wealth the caravan reports,
  and says so if it would. The agent decides; the harness makes the
  cost visible.
- The mountainhome wave ignores the cap. The harness notes it when the
  promotion happens, because a wave the cap was supposed to stop will
  still arrive.
- Refused waves are information. If migrants refuse to come, the cause
  is in the fort's own recent history: deaths, insanity, unhappiness.
  The diagnosis names the death-discourage band the fort is in
  (normal, danger, cursed death trap) from the deaths the journal
  already records. Fixing the fort is the fix for migration; there is
  no separate lever.

## 10. Children and babies

Children are not small adults. The plan treats them as a separate
category with their own rules.

- Dwarven childhood runs from age 1 to age 18. Babies are under 1.
  Migrant children may be any age from 1 to 17. Some migrants are
  listed as babies or children incorrectly and fix themselves at their
  next birthday; the harness reads the age the game reports and does
  not try to correct it.
- Children cannot be assigned to squads, cannot use armor or weapons,
  and cannot be given production labors. They can do chores: harvest
  crops if the "All dwarves harvest" order is on, store their own items
  including toys, socialize and perform, watch guild demonstrations,
  and attend meetings to complain if unhappy.
- Harvesting by children increases their planter skill, though rarely
  in the current version. The farming plan owns the harvest order; this
  doc owns noting that children are part of the harvest workforce when
  the order is on.
- Children can enter strange moods, and will attempt an artifact in a
  moodable skill they have watched demonstrated, otherwise bone carver,
  wood crafter, or stonecrafter. A child in a mood is handled by the
  moods work, not by this doc, but the wave assessment flags a child
  with a moodable skill so the fort knows.
- Babies are carried by their mother, who keeps working while carrying
  them. The mother becomes hungry or thirsty at double the usual rate.
  If the mother cannot collect her infant, the baby roams freely and
  generates job-cancellation spam as the game reads it as "insane";
  that stops at 12 months when the baby becomes a child.
- Babies can gain memories, and because they have few memories, the ones
  they gain weigh heavily. Strong negative thoughts in a baby can
  change their values permanently. The practical rule: do not let a
  baby-carrying mother be caught in the rain, and do not leave a baby
  near a hostile creature. The harness flags a baby in the wave summary
  so the agent knows the mother needs watching.
- Mothers can become pregnant again immediately after giving birth, and
  give birth again nine months later. Twins or triplets are exceedingly
  rare (1 in 500). The population forecast counts births as well as
  waves.
- Children respect burrow restrictions, including civilian alerts.
  During a siege, children go to the burrow like everyone else.

## 11. Noble appointments from migrants

A wave can bring the fort its manager, its broker, or its militia
commander. The harness must spot that, not leave it to chance.

- Positions available with an expedition leader: bookkeeper, broker,
  chief medical dwarf, hammerer, manager, militia commander, sheriff.
  With a militia commander, militia captains can be assigned. At
  population 50 a mayor is elected, replacing the expedition leader,
  and captain of the guard (replacing the sheriff) and dungeon master
  become assignable. Landholding nobles (baron at 20 population, 100k
  created wealth, 10k exported wealth; count 20 / 200k / 20k; duke
  20 / 300k / 30k) follow the difficulty triggers.
- A fort lacking a mayor or an expedition leader cannot appoint new
  administrators manually until a new dwarf takes office. The harness
  checks the expedition leader exists before suggesting any
  appointment.
- Selection criteria, per position. Manager: highest organizer skill,
  then social skills. Broker: highest social skills, then appraiser.
  Bookkeeper: the dwarf the fort can spare from production, since
  record-keeping precision is a setting, not a skill. Chief medical
  dwarf: highest healthcare skills (diagnoser, surgeon, wound dresser,
  bone doctor, suturer). Militia commander: highest combat skills,
  then leadership. Sheriff: a dwarf with combat skill and the
  steadiness to hold the post. Hammerer: nobody wants this job; the
  harness says so plainly and suggests the dwarf with the least to
  lose, and only if the justice system is active.
- Noble room demands are real: higher office-holders want expensive,
  well-furnished rooms, chests, cabinets, weapon racks, and armor
  stands, and some do not want a lower-rank dwarf to have a better
  room. An appointment the fort cannot house is an appointment that
  creates a mandate problem. The suggestion carries the room cost with
  the appointment.
- The appointment route is the blocker. Today `appoint_noble` works
  only through the nobles screen with xdotool keystrokes, and the
  Lua-write path was verified live to not register. That is step 2
  remainder work: the researched programmatic route is inserting into
  `ent.positions.assignments` (not `assignments_by_type`), with the id
  from `next_assignment_id`, plus `position_vector_idx`, `histfig2`,
  and a `histfig_entity_link_positionst` on the histfig, with
  read-back through `dfhack.units.getNoblePositions(unit)`. Whether
  `assignments_by_type` also needs an insert is still open. Until that
  route lands and is verified live, the harness recommends
  appointments and a human confirms them through the screen. The plan
  does not pretend the keystroke path is a harness action.
- Mandates and demands: higher nobles make demands and set mandates,
  and unmet mandates upset them, which matters once the justice system
  is active. The appointment suggestion names the mandate risk for
  the position. A wave that brings a baron candidate is not purely
  good news; the harness says what the title costs.

## 12. The unhappy cases

Not every arrival is good news. The plan names the bad cases and the
response to each, so the agent is not surprised by them.

- No useful skills. The migrant is not useless. Every healthy adult can
  haul, can train, and can serve as a low-quality soldier. The
  assignment is haul plus one training labor toward the fort's next
  gap. Expulsion is not the answer for "no useful skills"; it is the
  answer for a dwarf who is a danger or a drain the fort cannot carry,
  and even then only after the other options are named.
- Injured migrants. Migrants arrive with wounds from world generation.
  The wave assessment flags wound count and parts, and the assignment
  is: health check first, no labor until the wounds are assessed, bed
  near the hospital. A migrant with a missing limb or a crippling wound
  is assigned light work or none. The hospital work owns treatment;
  this doc owns the triage flag.
- Vampire, werebeast, or necromancer. The wiki says migrants may be
  any of these. The harness cannot detect a vampire from the units
  collect today. UNVERIFIED: what fields, if any, expose vampirism,
  lycanthropy, or necromancy in 0.47.05-r8, and whether a live probe
  can read them. Phase 5 investigates. Until then, the plan is
  watchfulness, not accusation: the diary and the history file record
  the wave, and unexplained deaths or strange behavior are investigated
  by the death loop, not blamed on the newest arrival. The harness
  never accuses a migrant without evidence.
- Arriving during a siege or crisis. Migrants march to the meeting
  hall through whatever is happening. The wave response during a
  crisis is: get them inside and to the burrow first, assign nothing,
  build nothing, and revisit the wave when the crisis ends. The
  military plan owns the crisis; this doc owns deferring the wave
  work until it is over.
- Arriving when food or drink is below the floor. Survival first:
  gather, fish, hunt, trade for food, in that order of speed. The
  wave summary leads with the shortage, not the skills. Assignment
  waits until the floor is met or a plan to meet it is running.
- A wave blocked by a siege may not show up at all. The harness does
  not treat a missing wave during a siege as a refusal; it treats it
  as blocked, and says so.
- Expulsion. The game allows expelling a migrant from their
  preferences screen. The harness never suggests expulsion for low
  skill, and never performs it. If the agent asks about it, the
  harness names what it costs (the dwarf leaves with their animals
  and equipment) and what it does not fix. Expulsion of an office
  holder is not possible peacefully.

## 13. How the information reaches the AI

The wave summary is the product. Everything else is behind a query.

- The snapshot carries one wave item while a wave is fresh (one
  in-game day, matching the attention window): the season, the count,
  the one-line composition ("2 planters, a brewer, a miner, 2
  children, a dog"), the bed deficit, the new food and drink floors,
  and the top three suggested assignments with a one-line why each.
  That is the whole wave in the snapshot. Nothing more.
- The per-wave summary, behind `GET /v1/waves` (new route; phase 1),
  is one table per migrant: name, age, sex, top two skills with
  ratings, coverage verdict, suggested labor with a why, wounds, and
  children or animals attached. Plus the wave-level section: coverage
  gaps the wave fills, coverage gaps still open after the wave, bed
  deficit and build order, new floors, and noble candidates with the
  position and the room cost.
- The query route answers questions, never dumps. Filters: wave
  (season/year), dwarf (name or id), skill, and "gaps" (what the fort
  still lacks after the wave). The route reads the journal and the
  wave records, not the live game, so asking about a past wave does
  not touch the game.
- The diary gets a wave entry: who arrived, what they brought, and
  what the fort did with them, as a story thread, not a roster. The
  per-season history file (`HISTORY.md`, queued) carries the wave as
  part of the season record, with open threads (a migrant still
  untrained, a noble still unappointed) carried forward.
- The briefing for a wave is a situation briefing, not a suggestion
  list. It states what changed (population, floors, coverage), what
  is urgent (beds, food), and what can wait (training, rooms). The
  agent decides; the harness makes the state visible.
- Counts, never raw state. The snapshot never carries the full skill
  tables, the full labor lists, or the full unit records. The summary
  is bounded: top three assignments in the snapshot, the full table
  behind the route.

## 14. Implementation phases

Each phase lands only when its verification bar is met live against the
real game. A phase that cannot be verified live is logged as unverified
and re-attempted, never pushed as done.

1. **Wave grouping and the wave record.** Group `citizen_new` events
   into a wave record in the journal (season, count, unit ids, per
   migrant fields from the units collect). Add the meeting-hall
   precondition check as a standing suggestion. Verification: a live
   wave on the main fort groups into one record with the right count
   and the right members, and the meeting-hall check reports the true
   state of the hall.
2. **Attributes collect.** Read attributes (strength, agility,
   toughness, endurance, recuperation, disease resistance, and the
   rest) into the units record, from the fields the game exposes.
   Verification: a live collect returns attribute values for a named
   dwarf that match the game's own display, and the values are sane
   across the fort.
3. **Skill assessment and the per-wave summary.** Build the coverage
   delta against the fort's current best per skill, the tier list
   adapted to the fort's needs, the specialist/generalist/unskilled
   classification, and the per-migrant one-line output. Add the
   `GET /v1/waves` route with the filters from section 13. Put the
   wave item in the snapshot. Verification: a live wave produces a
   summary whose coverage verdicts match the fort's real skill table,
   and the route answers a real question ("who is the best miner in
   this wave") from the record alone.
4. **Assignment suggestions and housing queue.** Suggested first labor
   per migrant with the one-line why, applied through `labor_toggle`
   with read-back; the bed deficit and build order from the live
   buildings read; the new food and drink floors recomputed from the
   new population. Verification: a live wave's suggestions are
   applied and verified, the bed math matches the live buildings,
   and the floors match the farming plan's arithmetic.
5. **Population management and the unhappy cases.** Distance to the
   population cap in the summary; the wealth-trap check before big
   sales; wound triage flags; the siege/crisis deferral; the
   vampire/werebeast/necromancer investigation (what fields expose
   them, if any). Verification: the cap distance matches the game
   setting, the wealth-trap check fires on a sale that would zero
   reported created wealth, and the investigation reports exactly
   what was tried and what blocked it.
6. **Noble appointments from migrants.** Land the programmatic
   appointment route (step 2 remainder) and verify it live; then the
   per-position selection criteria and the room-cost note with each
   suggestion. Verification: an appointment made through the route
   appears in the nobles screen on read-back, and the suggested
   candidate matches the criteria.
7. **Children, births, and the long game.** Birth forecasting from
   pregnancies and the population forecast; child chore assignment
   through the harvest order; the wave record carried into the
   per-season history file with open threads. Verification: a birth
   in the fort is recorded with the mother and the date, and the
   history file for the season names the wave and its open threads.

## 15. Refusals

- Never assign a child a production labor or a squad.
- Never assign the only brewer or the only planter away from their
  skill.
- Never suggest expulsion for low skill, and never perform it.
- Never accuse a migrant of vampirism, lycanthropy, or necromancy
  without evidence from the game.
- Never claim a migrant's skills from a stale collect; the assessment
  reads fresh units data at wave time.
- Never trade away 100 percent of created wealth without naming the
  migration consequence first.
- Never assign a wounded migrant a labor before the health check.
- Never suggest a noble appointment the fort cannot house without
  naming the room cost.
- Never present the xdotool noble-appointment path as a harness action.
- Never guess between the causes of a refused wave; report the ones
  the harness can check and say which it cannot.

## 16. Sources and what is still UNVERIFIED

Wiki pages read from the local index
(`~/workspace/df-wiki-export/dfq.py`): Immigration, Children,
Experience, Noble, Skill (skill token list), plus the migrant tier
list inside the Immigration page. Harness state verified against the
repo on 2026-11-27: `src/dfagent_harness/events.py` (arrival and
citizen diffs), `src/dfagent_harness/attention.py` (arrival
wording and windows), `src/dfagent_harness/lua/units.lua` (citizen
record fields), `src/dfagent_harness/lua/probe_unit.lua` (no
attributes), `src/dfagent_harness/actions.py` (`labor_toggle`),
`src/dfagent_harness/ui.py` (`appoint_noble`, xdotool path),
`docs/FARMING_PLAN.md` (season-ahead rule, sizing arithmetic),
`docs/MILITARY.md` (noble appointment blocker),
`docs/TRADING.md` (survival floors, wealth reporting, wealth trap),
`docs/FISHING.md` (meals per season). Fort state: Erushtathtat,
125-04-12, 7 citizens, no wave yet, journal holds no
`citizen_new` events.

UNVERIFIED, each with the phase that must prove it:

- The tick window and position-history read for diagnosing a stuck
  migrant at the map edge (phase 1).
- Whether attributes are readable through DFHack in 0.47.05-r8 and
  which fields carry them (phase 2).
- Whether the population cap is readable or settable through DFHack
  (phase 4).
- What fields, if any, expose vampirism, lycanthropy, or
  necromancy (phase 5).
- The programmatic noble-appointment route and whether
  `assignments_by_type` also needs an insert (phase 6, step 2
  remainder).
- Whether the "All dwarves harvest" order is settable through the
  harness, and how child harvesting is observed (phase 7).
- The exact per-dwarf drink consumption beyond the farming plan's
  derived figure of about 7 per dwarf per season; the plan uses the
  farming plan's arithmetic and the trading plan's floors rather
  than inventing its own numbers.
