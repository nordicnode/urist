# Kitchen and cooking management

The kitchen turns raw stocks into meals, and the still turns plants into
drink. Those two conversions are what keep dwarves alive and happy: a dwarf
eats about 7 units of food and drinks about 7 units of drink per season
(Farm size calculations), and a dwarf without booze works increasingly
slowly (Alcohol). The kitchen is also where the fort's most valuable trade
good is made, and where the seed reserve is most easily destroyed by
accident: cooking a plant destroys its seed, brewing it returns it.

This document is the design record for a smart kitchen system. The harness
does the arithmetic, the permissions, and the scheduling. The agent picks
from a small set of named options with a one-line why. Nothing here is
guessed: every mechanic is cited from the wiki pages in Sources, or from a
live verification against the game, and anything not verified is marked
UNVERIFIED.

Related design records: docs/FARMING_PLAN.md (the split rule, section
10.1, which decides what a harvest becomes), docs/TRADING.md (prepared
meals as trade goods), docs/FISHING.md (the fish-cleaning chain that feeds
the kitchen), docs/ANIMAL_HUSBANDRY.md (meat, milk, eggs, tallow supply).

## 1. Purpose

The kitchen system answers five questions every tick, from fresh collects,
so the agent never has to:

1. What can we cook right now, from the exact stacks on hand?
2. What must we never cook, and why?
3. How much drink do we need, and what is stopping us brewing it?
4. What is rotting, and what do we do about it?
5. What should we cook ahead of the next caravan?

If the harness cannot answer one of those from real state, it says so
instead of inventing an answer.

## 2. How cooking works in DF 0.47.05

All of this section is from the wiki pages listed in Sources.

A kitchen is operated by a dwarf with the cooking labor enabled. It cooks
prepared meals, and it also renders fat from butchered animals into tallow.

### 2.1 The three meal kinds

* **Easy meals** need 2 ingredient stacks, named "{last ingredient}
  **biscuit**".
* **Fine meals** need 3 ingredient stacks, named "{last ingredient}
  **stew**".
* **Lavish meals** need 4 ingredient stacks, named "{last ingredient}
  **roast**".

The cook must have the proper number of *distinct stacks* when the job
starts, or the job is cancelled. The same ingredient may be used more than
once, provided it is in multiple discrete stacks. The finished meal's stack
size is the sum of its ingredient stack sizes, so a cook grabbing "turkey
hen egg [14]", "plump helmets [5]" and "plump helmets [5]" makes a stack
of "plump helmet stew [24]". Prepared meals cannot be used as ingredients
in other prepared meals.

At least one stack going into a meal must be a solid item. If the fort has
only booze, milk, and syrup, cooking jobs are cancelled. A single plump
helmet can be cooked with ten dwarven wine, ten dwarven milk, and ten
dwarven syrup to make a 31-unit roast.

### 2.2 What the meal kind buys

Lavish meals, with 4 ingredient stacks, result in larger stacks of food
and need less final hauling for the same amount of prepared food. They take
a bit longer to produce (more initial hauling, and the workshop is more
likely to become cluttered) and give less experience per ingredient used.
With more variety in a meal, there is a higher probability a dwarf eats
something they like, giving a happy thought.

Easy meals give more experience per ingredient and result in twice as much
hauling after cooking. Fine meals fall between the two. All three kinds
give the same experience gain per job, so making easy meals maximizes
experience gain; if experience does not matter, lavish meals save much more
stockpile space.

### 2.3 Quality and value

Cooking applies a quality modifier to each ingredient, which can modestly
increase the food's value. A legendary cook can theoretically increase
value by up to 34x in the case of cooking seeds. The meal's value is
computed from its ingredients (Item value, Prepared meal table):

* Each ingredient's value is its base value times its material multiplier
  times its minced-quality modifier (normal 1.0x, well-crafted 1.1x,
  finely-crafted 1.2x, and so on), rounded down.
* The meal's per-unit value is the **average** of the ingredients'
  values, plus a flat quality bonus on the meal itself (normal +0,
  well-crafted +3, finely-crafted +6, and so on up the quality ladder).
* The stack's value is the per-unit value times the stack size, and the
  stack size is the sum of the ingredient stack sizes.

Two consequences follow, and both matter for planning. First, the trade
value of a meal comes from its large stack size and its quality, not from
multiplying ingredient values: a lavish meal made from four cheap
ingredients is worth roughly the average of four cheap ingredients, plus
the bonus. Second, the way to make a valuable meal is to include
high-value ingredients (meat, cheese, prepared fish) and to cook with a
skilled cook, not to pile in more cheap ingredients.

**Correction to docs/TRADING.md:** section 5 of the trading plan says
"the meal's value is the sum of its ingredients' values multiplied by the
number of ingredients". That is wrong against the Item value table. The
per-unit value is the average of the ingredient values plus the quality
bonus. The trading plan's conclusion (prepared meals are the best trade
good) still stands, because the stack size is the sum of four stacks and
the quality bonus applies, but the formula must be fixed in TRADING.md
when the kitchen work lands. The coordinator owns that fix.

### 2.4 Variety, preferences, and happiness

Cooked meals count as each of their ingredients for the purpose of
satisfying a dwarf's preferences, increasing the likelihood of happy
thoughts and fulfilling the "eat a good meal" need. Ideally a meal
combines four different ingredients, to maximize the chance a dwarf eats
something they like.

Two limits apply. A high-quality cooked meal only gives a happy thought
if at least one of its ingredients is preferred by the dwarf eating it
(Bug:4661). And cooks are notorious for choosing ingredients poorly: left
alone, a cook will produce an endless string of tallow roasts, because
cooks prefer some of the worst ingredients (single units of low-value
materials like tallow).

The wiki's answer to bad ingredient choice is feeder stockpiles: a series
of single-tile, barrel-less stockpiles, each holding a different type of
cookable food, all set to "give" to the kitchen. That forces variety,
because the cook can only reach what the feeders hold.

### 2.5 Cook quirks the harness must respect

* Cooks only use liquid ingredients (booze, milk, syrup, oil) as a last
  resort, preferring solid foods (Bug:2393). To force fluids into meals,
  limit the possible ingredients through stockpile linkage: a kitchen set
  to accept ingredients from a stockpile will not use other ingredients
  unless they are already stored in the kitchen.
* Cooks prefer ingredients stored in containers, and even more so
  ingredients stored in containers stored in containers (flour, quarry
  bush leaves). Cooks can combine all the ingredients in a barrel into
  one massive meal (Bug:7546).
* Frozen milk gets cooked into prepared meals as a solid, causing the meal
  to melt later (Bug:2787).
* Cooks may occasionally create a meal with more than the required number
  of ingredients (roasts with 5, 6, or even 12 ingredients), apparently
  when many stacks of the same food are available. The plan treats this as
  a quirk, not a mechanism: never plan around it.
* Cooking plants will not preserve the seeds. To retain seeds from plants,
  either brew them, process them, or encourage dwarves to eat them raw.
  This is the single most expensive kitchen mistake, and the split rule
  (section 6) exists to prevent it.

### 2.6 Rendering fat

The kitchen also renders fat into tallow. Rendering large units of fat
(for example from elephants or forgotten beasts) gains cooking skill
extremely quickly, dozens or hundreds of units of tallow per task, even
from dabbling to skilled in a single task. Tallow is also a soap input and
a (poor) cooking ingredient. The harness treats fat rendering as the
cook-training route, not as a food source.

## 3. How brewing works in DF 0.47.05

### 3.1 The reaction

BREW_DRINK_FROM_PLANT (reaction index 44, verified live in
materials.py): 1 PLANT with a DRINK_MAT product plus 1 EMPTY barrel or
pot produces 5 DRINK and 1 SEEDS. BREW_DRINK_FROM_PLANT_GROWTH (index
45) is the same shape for fruit (PLANT_GROWTH). MAKE_MEAD brews 5 mead
from 150 honey plus a container. Each brewing job produces five units of
alcohol per brewable item and deposits it in the container, recovering
any plant seeds in the process. The size of a stack does not affect how
long brewing takes, which is based entirely on the brewer's skill, so
brewing jobs on large stacks are much more efficient than on single
items.

### 3.2 Why drink matters

Alcohol is the favored drink of the dwarves. A dwarf drinks booze an
average of five times per season to satisfy thirst, and although dwarves
can subsist on water, without booze they work increasingly slowly. The
creature token `[ALCOHOL_DEPENDENT]` is the cause. Withdrawal shows in
thoughts as "starting to work slowly due to its scarcity" after 3 months,
"really wants a drink" after 6 months, "has gone without a drink for far,
far too long" after 9 months, and "can't even remember the last time he
had some" after a year.

Dwarves want variety in drink, and get a bad thought if forced to drink
the same variety repeatedly ("has been tired of drinking the same old
booze lately"). Every dwarf has preferences for various drinks, and the
happy thought from a preferred drink depends on the value of the whole
stack. Dwarves prefer to drink out of a mug, cup, or goblet, and get an
unhappy thought for drinking without one.

Alcohol can be used as a meal ingredient, but meals made with alcohol do
not get dwarves drunk and do not sate thirst. Cooked alcohol does not
count as drink. A fort that cooks its booze away is a fort that goes
sober.

### 3.3 The drink floor

The farming plan (docs/FARMING_PLAN.md, section 10.1) sets the drink
floor at population times 5 per season, plus one season of reserve.
Brewable plants are brewed until the floor is met. The planner's current
thresholds are lower (planner.py: drink warn at max(20, citizens), drink
critical at 5, brew x3 at warn), because they are tripwires, not targets.
The kitchen system replaces the tripwire with the floor: brew to the
floor every season, and treat anything below the floor as a standing
need, not an emergency.

The binding constraint on brewing is the empty barrel. Verified live
2026-11-27: the fort had 15 barrels with only 3 empty, so a brew x5
against the total would queue 2 jobs that can never run. materials.py
already fail-fasts on empty barrels, and the snapshot carries the empty
barrel count for exactly this reason.

## 4. What the harness knows today

Verified against the repo on 2026-11-27. Everything in this section was
read from the code, not remembered.

### 4.1 What exists and works

* **Cook job:** `queue_job` job `cook`, job type 115 (PrepareMeal), no
  reaction, in actions.py JOB_SPECS. The fail-fast floor is 2 distinct
  food stacks per meal (`food_stacks` in the stocks section).
* **Cook task:** daemon.py TASK_DEFS `cook` (needs a kitchen, waits on
  PrepareMeal). The planner queues cook x2 when food is at or below the
  warn threshold (FOOD_WARN 15) or the critical threshold (FOOD_CRITICAL
  5), and falls back to gathering when there is no kitchen. It also
  suggests building a kitchen when the fort has stone and no kitchen.
* **Brew job and task:** `brew`, job type 211 CustomReaction with
  BREW_DRINK_FROM_PLANT (and the GROWTH variant), 1 brewable plant + 1
  empty barrel per job, 5 drink + 1 seed back. The planner queues brew x3
  when drink is at or below the warn threshold.
* **Stocks collect:** stocks.lua counts drink_units, drink_stacks,
  food_units, food_stacks, seeds, wood, stone, cloth, thread, metal bars,
  barrels, empty barrels, bins, buckets, plus `by_material` (type and
  material, units) and `category_stacks` (ANY_GOOD_FOOD, ANY_COOKABLE,
  ANY_EDIBLE_RAW, ANY_DRINK, WOOD, BAR, CLOTH, SEEDS). PLANT entries in
  by_material carry a `brewable` flag computed from the plant raw (DRINK
  material present).
* **Snapshot text:** the assembler renders "Stocks: drink 97, food 23,
  wood 117, stone 0. brewable plants 1. empty barrels 3. food stacks N."
  plus burn rates and days-remaining for drink, food, wood, and stone
  from the Store's trends. The agent never computes a burn rate from a
  single snapshot.
* **Catalog entries:** `brew` and `cook` both have plain-words `about`
  and `needs` text in catalog.py, built by introspection from the action
  table so they cannot drift.

### 4.2 What is missing (verified gaps)

* **The snapshot never says how many prepared meals the fort has.**
  `food_units` and `food_stacks` count only MEAT, FISH, FISH_RAW,
  PLANT, CHEESE, and EGG (stocks.lua). Prepared meals (item type FOOD)
  are counted in the collect's `by_type` table and appear in its `items`
  list, and FOOD entries appear in `by_material`, but the snapshot text
  never renders them. A fort with 200 meals and 0 raw food reads as
  "food 0". The planner's cook decision is therefore blind to cooked
  food. This is the first gap the kitchen work closes.
* **Processed ingredients are invisible.** Flour, sugar, dye (powder),
  and milk, syrup, honey, oil (liquid) are not in `by_material` at all:
  the material breakdown only covers DRINK, FOOD, MEAT, FISH, PLANT,
  SEEDS, BAR, WOOD, CLOTH, THREAD. The harness cannot currently answer
  "how much flour do we have" or "how much milk". The collect counts
  them in `by_type` (every item type is counted there), but nothing
  surfaces them.
* **The harness cannot choose easy, fine, or lavish.** The live runtime
  enum (tests/fixtures/runtime-enums-0.47.05-r8.json) contains exactly
  one meal job type, `PrepareMeal`. There are no
  PrepareEasyMeal/PrepareFineMeal/PrepareLavishMeal job types. So the
  meal kind is not a job type, and the harness's `cook` action queues a
  meal without choosing its kind. How the game records the choice is
  UNVERIFIED (see section 14, open question 1). Until the probe in
  phase 2 answers it, the harness controls meal kind only indirectly,
  through the ingredients it makes available (section 9).
* **No kitchen permissions action.** There is no harness action for the
  cook/brew allow list (the y-menu Kitchen subtab). The farming plan
  already marks the write route UNVERIFIED. The kitchen work probes it
  (phase 4) and falls back to feeder stockpiles if no write route exists.
* **No cookable computation.** Nothing computes, from current stocks,
  which meals are cookable, which stacks are blocked, or what a candidate
  meal is worth. The planner only checks the 2-stack floor. The agent is
  never told what is cookable; it is told food is low and a kitchen is
  idle.
* **No rotation or rot surfacing.** Nothing tells the agent which food is
  oldest, which is rotting, or that raw fish rots no matter where it is
  stored. The events system reports cancellations ("needs unrotten
  item") after the fact, but nothing prevents cooking from a doomed
  stack.
* **No drink variety tracking.** Nothing records which drink varieties
  the fort has, so the "same old booze" bad thought is invisible to the
  harness.
* **No cook assignment.** Nothing picks who cooks. The cooking labor is
  toggled by hand, and the planner never checks whether a cook exists.

## 5. Meal planning

Meal planning is a computation over fresh stocks, not a guess. It runs
whenever the kitchen section is built (snapshot) or queried
(GET /v1/kitchen), and it follows these rules in order.

### 5.1 What is cookable

A meal is cookable when the fort holds enough distinct, allowed,
unrotten, solid-containing stacks:

* Count distinct stacks of cookable food (meat, fish, prepared fish,
  plants, cheese, eggs, flour, sugar, syrup, milk, honey, tallow, oil),
  excluding anything on the never-cook list (section 6) and anything at
  or below its seed reserve.
* Easy needs 2 distinct stacks, fine 3, lavish 4. At least one stack
  must be solid.
* The computation names the stacks it would use, in the order the cook
  would reach them (feeder stockpiles first, then the nearest food
  stockpile), so the agent sees "plump helmet [5], cave wheat flour
  [12], turkey egg [14]" rather than "3 stacks".

### 5.2 Easy vs fine vs lavish

The choice is a trade-off the harness makes explicit, per the wiki:

| Kind | Stacks | Best for | Cost |
| --- | --- | --- | --- |
| Easy (biscuit) | 2 | Training the cook (most XP per ingredient), stretching scarce ingredients | Twice the hauling after cooking; smallest stacks |
| Fine (stew) | 3 | The middle ground when variety is limited | Between the two |
| Lavish (roast) | 4 | Feeding the fort (largest stacks, least hauling), trade goods, variety and happy thoughts | Most XP wasted per ingredient; needs 4 distinct allowed stacks |

Rules:

* **Training:** while the cook is below competent, prefer easy meals.
  Same XP per job, more XP per ingredient.
* **Feeding:** once the cook is competent and the fort has 4 distinct
  allowed stacks, prefer lavish. Largest stacks, least hauling, most
  variety per job.
* **Scarcity:** when only 2 distinct allowed stacks exist, cook easy or
  do not cook at all. Never burn a scarce fourth stack to force a lavish
  meal.
* **Trade:** lavish only, from surplus, cooked close to the caravan
  season (section 11). Never cook trade meals from the seed reserve or
  from the last of a scarce ingredient.

If the phase 2 probe finds the harness cannot choose the meal kind at
all, these rules degrade honestly: the harness reports the kind it
*wants* and the ingredients it made available, and the doc records that
the game picks the kind. It never claims a choice it did not make.

### 5.3 Value of a candidate meal

For each candidate meal the harness computes, from the Item value
formula (section 2.3): per-unit value (average of the ingredient values,
quality-modified, plus the quality bonus for the cook's skill) and stack
value (per-unit times the summed stack sizes). The agent sees the stack
value and the variety count ("4 different ingredients, stack value
about 40"), never the formula.

## 6. Ingredient discipline

This is the part of the kitchen system that prevents the expensive
mistakes. It is enforced by the split rule and the permissions list
together, and it is checked before every cook job is queued.

### 6.1 The split rule (from the farming plan)

Every harvested stack goes to exactly one destination, in this priority
order (docs/FARMING_PLAN.md, section 10.1):

1. Brew, to the drink floor (population x 5 per season, plus one season
   of reserve). Brewing returns the seed.
2. Process, for industrial crops (thread, flour, sugar, syrup, leaves,
   oil, dye), only when the workshop exists and the product is needed.
3. Eat raw, for the surplus of eatable crops. Eating returns the seed.
4. Cook, for the surplus above the seed reserve and the brew floor.
   Cooking destroys the seed, so cooking is last.
5. Trade, for the surplus above all of that.

The kitchen system owns step 4. It refuses to cook a crop at or below
its seed reserve (plot tiles of that crop + 5 bank seeds), and it refuses
to cook the last of any crop. A refused cook names the reserve it is
protecting ("cannot cook plump helmets: 6 seeds is the reserve for the
9-tile plot").

### 6.2 The never-cook list

Some things are never cooked, whatever the stocks say:

* Seeds of any kind, and any crop at or below its seed reserve.
* The last stack of a scarce ingredient (a material with only one stack
  in the fort, unless the fort has a production route for it).
* Drink below the drink floor plus one season of reserve. Alcohol may be
  cooked only from the surplus above that floor, because cooked alcohol
  does not count as drink and does not sate thirst.
* Tallow, except as a filler when nothing else is available. Cooks
  prefer it and it is nearly worthless; a tallow roast is the failure
  mode the feeder stockpiles exist to prevent.
* Milk that is frozen (Bug:2787, it melts after cooking).
* Rotting or withered stacks. A cook job that grabs a rotting stack is
  cancelled with "needs unrotten item"; the harness refuses before
  queueing instead of learning from the cancellation.
* Anything forbidden, dumped, or with no path (the game disregards those
  for workshop tasks, so the harness must too).

### 6.3 Variety

The harness tracks, per meal, how many distinct ingredients it used,
and per season, which ingredients have been cooked. It prefers meals
with 4 different ingredients, and it prefers ingredients the fort's
dwarves have preferences for, where the snapshot's per-dwarf records
carry preferences. Where the game gives no preference data, the harness
says so and falls back to raw variety count. It never invents a
preference.

The feeder-stockpile mechanism (section 9) is the enforcement: variety
is produced by what the cook can reach, not by asking the cook nicely.

### 6.4 Liquids

Liquids (booze, milk, syrup, oil) are used as meal ingredients only
when the solid base is secure and the liquid is surplus. The cook's
preference for solids (Bug:2393) means the harness cannot rely on the
cook to use liquids on its own; the feeder-stockpile design in section
9 is what forces them in. A meal's first stack must be solid, and the
harness checks that before queueing.

## 7. Brew scheduling

Brewing is scheduled against the drink floor, not against the planner's
tripwire.

1. **Floor:** population x 5 per season, plus one season of reserve
   (the farming plan's floor). Compute it from the live citizen count
   every time; it moves when migrants arrive.
2. **Brew when below the floor.** Queue brew jobs in proportion to the
   shortfall, one job per brewable plant and one empty barrel each, and
   never more jobs than empty barrels. The barrel count is checked from
   the fresh collect, never from the daemon's cached status (which has
   shown stale zeros).
3. **Barrel pipeline.** When empty barrels are the binding constraint,
   the brew decision names the fix: queue make_barrel at the carpenter,
   1 wood each. The planner already does this for the tripwire case;
   the kitchen system does it for the floor case, and it tracks the
   barrel ledger (empty, full of drink, full of food) so the agent sees
   "3 empty barrels, 12 full of drink" instead of "15 barrels".
4. **Variety.** Track drink varieties on hand (by material in
   by_material). When the fort brews only one variety for a whole season,
   the kitchen section says so, and the farming plan's second-crop rule
   is the fix: grow a second brewable crop for variety. The "same old
   booze" bad thought is a real cost, and the harness surfaces it rather
   than letting it accumulate silently.
5. **Mead.** Honey is brewed to mead only when the fort has beekeeping
   and honey above the amount the kitchen wants for cooking. Mead is
   the only drink not derived from plants or fruit, and it is a variety
   source, not a staple.
6. **Hospital water.** Dwarves resting in a hospital will not accept an
   alcohol ration and must be given fresh water. The kitchen system does
   not brew for the hospital; the hospital plan owns water. This is
   noted here so the drink floor is never inflated by hospital demand.

## 8. Kitchen permissions

The game has a cook/brew allow list for every cookable and brewable item
in the fort, reached in the UI through the labor menu's Kitchen subtab.
Disallowing an item stops it being cooked or brewed, and any cooking job
in progress is cancelled if one of its chosen ingredients is disallowed.
This is the game's own mechanism for protecting seeds and booze, and the
harness should drive it rather than work around it.

### 8.1 The allow list the harness maintains

The harness maintains one allow list, derived from the split rule and
the never-cook list, and applies it whenever stocks change:

* **Cook: allowed:** surplus crops above the seed reserve, meat, fish,
  prepared fish, cheese, eggs, flour, sugar, syrup, milk, honey, oil,
  tallow as a filler only.
* **Cook: forbidden:** seeds, any crop at or below its seed reserve,
  the last stack of a scarce ingredient, rotting stacks, frozen milk.
* **Brew: allowed:** brewable plants above the amount the farm needs
  for seed, fruit with a DRINK product, honey for mead.
* **Brew: forbidden:** drink is never brewed from a plant the fort
  needs for seed; nothing else is forbidden from brewing, because
  brewing returns the seed.

### 8.2 The write route (UNVERIFIED)

Whether the harness can write this allow list is UNVERIFIED. The
farming plan already marks it so, and the kitchen work probes it in
phase 4: read the live game state for the kitchen permission fields
(the liaison meeting was solved by writing game state directly, so a
write route may exist), and write one test change with read-back
verification. If a write route exists, the harness owns the allow list
and the agent never touches it. If no write route exists after a real
investigation, the harness falls back to feeder stockpiles (section 9),
which control ingredients by what the cook can reach, and the doc
records exactly what was tried and what blocked it. The harness never
claims to enforce permissions it cannot write.

## 9. Kitchen layout

Layout is scored placement (docs/SITE_SELECTION.md, queued work), with
kitchen-specific factors on top of the shared threat, cover, and traffic
factors:

* **The triangle.** Kitchen, still, and food stockpile belong together,
  within a few tiles of each other. The still needs the same brewable
  plants the kitchen wants to cook, and the food stockpile is where both
  workshops' outputs go. A kitchen far from its food stockpile pays the
  hauling cost on every meal.
* **Feeder stockpiles.** Around the kitchen, a ring of single-tile,
  barrel-less feeder stockpiles, each holding a different cookable food,
  all set to "give" to the kitchen. One feeder per ingredient kind the
  fort wants in its meals. A larger stockpile links to each feeder to
  refill it. The barrel-less rule matters: once ingredients are in
  barrels, they are never taken out to be moved to a feeder stockpile.
* **Volatile food close.** More volatile foods (meat) are stored closer
  to the kitchen, so cooks use them quickly (Stockpile page).
* **Output stockpile.** The prepared-meal stockpile needs fewer barrels
  than squares: meal stacks can exceed the 60-unit barrel capacity, so
  there must be non-barrel squares for oversized stacks. Prepared meals
  left in the open attract flies and unhappiness, so the output
  stockpile sits in a low-traffic area, not on the main corridor.
* **The still next door.** The still belongs beside the kitchen and the
  food stockpile for the same reason: the brewer hauls plants and
  barrels, and the drink goes into the same storage.
* **Processing workshops nearby.** The farmer's workshop, quern, and
  screw press (flour, sugar, syrup, leaves, oil, dye) sit with the
  kitchen and still, because their products are the kitchen's inputs.

## 10. Food rotation

Food rots, and rotting food underground makes miasma, which makes
dwarves unhappy. The kitchen system manages rotation so the oldest food
is used first and nothing rots in a corridor.

* **What rots where.** Prepared food rots the same as meat, cheese,
  eggs, and prepared fish, but plants wither instead of producing
  miasma. Food does not rot in a stockpile, a trade depot, the embark
  wagon, a minecart, while carried, or as eggs in a nest box. A barrel
  or pot full of meat left in a corridor will rot. Milk, fat, tallow,
  flour, drinks, seeds, and rock nut paste do not rot. Raw fish rots no
  matter where it is stored, which is why fish must be cleaned as
  quickly as possible (docs/FISHING.md).
* **Oldest first.** The harness surfaces the oldest food stacks in the
  kitchen section, and the cookable computation prefers them. A meal
  built from the oldest stacks is a meal that does not rot.
* **Refuse.** Rotting items go to a refuse stockpile, not the food
  stockpile. Miasma spreads only north, south, east, west, up, or down,
  never diagonally, and passes through grates, bars, and open doors but
  not closed ones. The refuse pile belongs in its own room with multiple
  doors, or open to the sky, or down a long chute. The kitchen system
  does not design refuse piles (that is the digging and zone work), but
  it reports rotting stocks so the agent can act.
* **The cook's "needs unrotten item" cancellation** is a symptom, not
  a diagnosis. When a cook job is cancelled that way, the diagnosis
  names the stack that was rotten or unavailable, and the fix is to
  cook from a fresh stack or to clear the rotten one. The harness never
  re-queues the same job against the same doomed stack.

## 11. Prepared meals as trade goods

Prepared meals are the fort's best trade good: renewable, easily
transported, easily sub-divided, and stack quality modifiers. Even a
novice cook has a chance of increasing the value of raw ingredients
somewhat. The trading plan (docs/TRADING.md, section 5) already covers
the trade side; this section covers the kitchen side.

* **Which meals:** lavish meals from surplus, with high-value
  ingredients (meat, cheese, prepared fish) where the fort has them,
  because the per-unit value is the average of the ingredient values
  (section 2.3). A lavish meal of four cheap ingredients is worth
  roughly four cheap ingredients; a lavish meal with meat and cheese in
  it is worth noticeably more.
* **When:** cooked close to the caravan season, not stockpiled for a
  year. Meals rot outside a food stockpile, and the caravan calendar is
  known (elves spring, humans summer, dwarves autumn, none in winter).
  The kitchen system queues trade meals in the season before the caravan
  they serve.
* **What never goes in a trade meal:** anything on the never-cook list,
  anything below the seed reserve, and (for elves) any animal-derived
  ingredient. Elven traders are offended by meals containing
  animal-derived ingredients, and one wrong item ends the session.
* **Value check:** the candidate-meal computation (section 5.3) gives
  the stack value before cooking, so the agent can compare "cook 4
  lavish meals, about 160 value" against "sell the raw ingredients".
  The harness never cooks a trade meal whose ingredients are worth more
  raw than cooked.

## 12. Cook skill

Cooking skill matters twice: it raises meal quality (and therefore value
and happy thoughts), and it shortens brewing time (brewing time is based
entirely on the brewer's skill, not the stack size).

* **Who cooks:** one dedicated cook, chosen from dwarves with the
  highest cooking skill and the attributes the wiki names (agility,
  analytical ability, creativity, kinesthetic sense), with a backup who
  keeps the skill warm. The cook is not also the planter or the brewer;
  the kitchen system refuses a cook assignment that would leave the farm
  or the still without a worker.
* **Training:** easy meals maximize experience per ingredient while the
  cook is below competent. Rendering fat trains cooking extremely fast
  and is the training route when the fort has fat to render. The harness
  queues fat rendering as training, not as food production.
* **Brewer:** the same logic, one dedicated brewer with a backup.
  Brewing on large stacks is more efficient per job, so the brewer works
  the largest brewable stacks first.

## 13. How the information reaches the AI

This is the part Mikey asked for explicitly: the information must be fed
to the AI optimally. The rules are the same as the snapshot's rules
everywhere else in the harness: counts and exceptions, never a dump;
named options with a one-line why; full detail behind a query route.

### 13.1 The snapshot's Kitchen section

The per-tick snapshot gains a short Kitchen section, built from the
fresh collect, in plain words:

```
Kitchen: drink 97 (floor 70, 13 days left), food 23, prepared meals 12.
Cookable now: lavish from plump helmet, cave wheat flour, turkey egg,
  horse meat (4 kinds, stack value about 40); easy from plump helmet,
  pig tail (2 kinds).
Blocked: cannot cook quarry bush leaves (seed reserve 9); cannot cook
  dwarven wine (drink at floor).
Brew: 1 brewable plant, 3 empty barrels; 2 brews to reach the floor.
Oldest food: horse meat [8], 2 seasons old.
```

What is in it, and what is not:

* **In it:** drink and food against their floors, with days remaining
  from the Store's trends; prepared-meal count (new); what is cookable
  now, with the exact stacks named and the meal kind; what is blocked
  and why, in words; brew status against the floor; the oldest food
  stack; the cook's name and skill.
* **Not in it:** the full ingredient table, the per-material breakdown,
  the permissions list, or the meal-value arithmetic. Those live behind
  GET /v1/kitchen.
* **Never in it:** a raw dump of the stocks section, a list of every
  stack, or a number without its unit and its floor. A number without
  its floor is a number the agent cannot act on.

### 13.2 The query route

GET /v1/kitchen returns the full detail: per-material cookable stacks
with units and ages, the seed reserve per crop, the never-cook list with
reasons, the permissions allow list, candidate meals with computed
values, the barrel ledger (empty, full of drink, full of food), drink
varieties on hand, and the cook and brewer assignments. It reads from
the fresh collect, not from a cache. The snapshot carries the summary;
the route carries the detail. The agent asks the route when it needs to
choose, never as a matter of routine.

### 13.3 Named options

The planner's cook and brew decisions become kitchen-aware, and they
carry the option in the decision itself:

* "Cook 2 lavish meals from plump helmet, cave wheat flour, turkey egg,
  horse meat (4 kinds, stack value about 40, oldest meat used first)."
* "Brew 2 at the still (1 brewable plant, 3 empty barrels; 2 brews to
  reach the floor of 70)."
* "Cannot cook: only 1 distinct allowed stack (plump helmet). Gather
  plants or butcher for a second kind."

The suggestion names the exact tool and parameters, as everywhere else
in the harness. When nothing is cookable and nothing is brewable, the
kitchen section says so and names the fix (gather, butcher, farm, trade),
instead of going silent.

## 14. Implementation phases

Each phase ends with a concrete live-verification bar. Nothing counts as
done until it passes its bar against the real game.

1. **Observation.** Extend the stocks collect so the snapshot can see
   what the kitchen needs: prepared-meal count (FOOD type units and
   stacks) as its own headline numbers; flour, sugar, dye, milk, syrup,
   honey, oil, and tallow counts (extend `by_material` to POWDER_MISC
   and LIQUID_MISC, or add a `kitchen` subsection to the collect);
   drink varieties by material. Add the Kitchen section to the
   snapshot. Bar: a live collect on the main fort shows the prepared
   meals the fort actually has, and the snapshot text names them.
2. **Meal-kind probe.** Queue a cook job on the live game and read the
   job struct back: how is easy/fine/lavish recorded, and can the
   harness choose it? Check the manager-order route as well. Bar: the
   probe names the field (or the absence of one) with a live job id,
   and the doc records the answer. If the kind cannot be chosen, the
   plan adapts per section 5.2 and never claims otherwise.
3. **Cookable computation.** Build the distinct-stack counter, the
   seed-reserve and never-cook filters, and the candidate-meal builder
   with value estimates from the Item value formula. Wire it into the
   snapshot Kitchen section and GET /v1/kitchen. Bar: on the live fort,
   the computation's cookable list matches a hand check of the stocks,
   and a cook at or below the seed reserve is refused with the reserve
   named.
4. **Kitchen permissions probe.** Read the live game state for the
   cook/brew allow list, write one test change with read-back
   verification, and restore it. Bar: the probe names the fields and
   the write result. If no write route exists after a real
   investigation, fall back to feeder stockpiles and record exactly
   what was tried and what blocked it.
5. **Brew scheduling.** Replace the planner's tripwire brew with
   floor-based brewing (population x 5 per season, plus one season of
   reserve), the barrel ledger, and the variety tracking. Bar: a live
   M1 day brews to the floor and stops, and the snapshot names the
   barrel count that bound it.
6. **Rotation and rot.** Surface the oldest food stacks, refuse
   rotting stacks before queueing, and diagnose "needs unrotten item"
   cancellations with the stack named. Bar: a live cook job against a
   rotting stack is refused before queueing, and the oldest stack is
   the one the computation picks first.
7. **Trade meals.** Queue lavish meals from surplus in the season
   before a caravan, filtered through the elf rules and the never-cook
   list, with the value check against selling raw. Bar: a live trade
   batch is cooked, its stack value is computed before cooking, and no
   ingredient came from the seed reserve.
8. **Cook assignment and training.** Pick the cook and brewer by skill,
   wire `labor_toggle` to assign them, and queue fat rendering as
   training when fat is available. Bar: the assigned cook is the
   highest-skill dwarf with the cooking labor, verified by read-back,
   and a fat-rendering job raises the cook's skill.

Every phase carries offline tests (including malformed-input tests per
the standing rule) and goes through the pre-push self-review gate before
it is committed and pushed.

## 15. Refusals

The kitchen system refuses, and says why, in plain words:

* Never cook a crop at or below its seed reserve, and never cook the
  last stack of a scarce ingredient.
* Never cook drink below the drink floor plus one season of reserve.
  Cooked alcohol does not count as drink.
* Never cook a rotting or withered stack, and never re-queue a cook job
  cancelled for "needs unrotten item" against the same stack.
* Never offer a meal with animal-derived ingredients to elves.
* Never claim a meal kind the harness cannot choose. If the phase 2
  probe finds no choice, the harness says the game picks the kind.
* Never cook a trade meal whose ingredients are worth more raw than
  cooked.
* Never queue a cook job without the distinct stacks present at job
  start. The fail-fast floor is 2; the computation checks 2, 3, or 4
  for the kind it wants.
* Never cook from a stack the cook cannot reach, or from a forbidden or
  dumped item. The game disregards those, so the harness must too.

## 16. Open questions (UNVERIFIED)

1. **Meal kind.** How easy/fine/lavish is recorded on a PrepareMeal
   job, and can the harness choose it? The live enum has only one
   PrepareMeal type. Phase 2 probes it.
2. **Kitchen permissions write route.** Whether the cook/brew allow
   list can be written from Lua, and where the fields live. Phase 4
   probes it. The farming plan already marks this UNVERIFIED.
3. **Drink variety read.** Whether `by_material` DRINK entries give
   the varieties on hand in enough detail to track the "same old booze"
   thought. Phase 1 verifies it against the live collect.
4. **Oldest-stack read.** Whether the collect can report the age of a
   food stack, or whether "oldest first" must be approximated from the
   stocks order. Phase 6 probes it.
5. **Rot detection.** Whether a rotting stack is readable before the
   cook job is cancelled, or whether the harness must learn it from the
   cancellation. Phase 6 probes it.
6. **Cook assignment read-back.** Whether `labor_toggle` for the
   cooking labor verifies the same way it does for planters. Phase 8
   verifies it live.
7. **Mead demand.** Whether honey above the cooking amount is common
   enough for mead to matter, or whether it stays a variety footnote.
   Answered by live observation, not by guessing.

## 17. Sources

Wiki pages read from the local index (`~/workspace/df-wiki-export/dfq.py`):

* Kitchen, Cook, Food guide, Alcohol, Item value (Prepared meal table),
  Miasma, Stockpile, Stockpile design, Farm size calculations, Brewer.
* Raw reactions read from the wiki's Still/raw page
  (BREW_DRINK_FROM_PLANT, BREW_DRINK_FROM_PLANT_GROWTH, MAKE_MEAD),
  cross-checked against materials.py, which verified them live.

Harness state verified against the repo:

* materials.py (brew reaction, cook floor, empty-barrel fail-fast),
  actions.py JOB_SPECS (`cook` 115, `brew` 211),
  planner.py (FOOD_WARN 15, FOOD_CRITICAL 5, DRINK_WARN max(20,
  citizens), DRINK_CRITICAL 5, cook x2, brew x3),
  daemon.py TASK_DEFS (`cook`, `brew`),
  stocks.lua (food_units and food_stacks count MEAT, FISH, FISH_RAW,
  PLANT, CHEESE, EGG only; `by_material` covers DRINK, FOOD, MEAT,
  FISH, PLANT, SEEDS, BAR, WOOD, CLOTH, THREAD),
  assembler.py (snapshot Stocks line, burn rates, days-remaining),
  catalog.py (`brew` and `cook` entries),
  tests/fixtures/runtime-enums-0.47.05-r8.json (exactly one
  `PrepareMeal` job type),
  docs/FARMING_PLAN.md section 10.1 (the split rule, the drink floor),
  docs/TRADING.md sections 2 and 5 (elf rules, prepared meals as trade
  goods), docs/FISHING.md section 2.4 (the fish-cleaning chain).
