# Farming plan

Design document for the farming SYSTEM in the Urist harness: crop
strategy, seed management, plot sizing and placement, irrigation,
fertilizer, harvest handling, the farm-to-kitchen/still chain, labor,
scaling, and failure modes. This is a plan, not an implementation.
Nothing in this document is built yet unless it says otherwise.

## Which file holds what

- `docs/FARMING.md` is the mechanics reference: what the harness
  verifies before planting, the refusal matrix, the probe_crop
  off-by-one root cause, and the live verification notes. Read it
  first for how planting works today.
- This document is the system around it: what to plant, how much,
  where, and what happens to the harvest. It builds on FARMING.md
  and does not repeat it. Where this document changes a behavior
  FARMING.md describes, it says so explicitly.

Every game mechanic in this document comes from the local Dwarf
Fortress wiki index (see Sources at the end) or from live
verification against the real game. Anything not verified against
one of those two is marked UNVERIFIED.

## 1. Purpose

The farm task works: a crop is set, PlantSeeds jobs appear, plants
grow, dwarves harvest. That is one planting. A farming system is
everything around it: choosing the right crop for the season and the
fort's needs, keeping enough seeds to plant again, sizing the plots
to the population, getting the harvest to the still and the kitchen
before it withers, and growing the system as migrants arrive. The
harness must drive all of it. The agent picks from named options;
the harness does the counting, the timing, and the refusing.

## 2. How farming works in DF 0.47.05

All of this section is from the wiki pages listed in Sources.

### 2.1 The season and the clock

A season is 3 months of 28 days, 84 days. A year is 336 days. Each
farm plot grows one kind of plant per season, and the crop is chosen
per season. One seed is planted per tile. Plants take a fixed time
to grow: 25 days for plump helmets and pig tails, 42 days (41.666)
for cave wheat, sweet pods, quarry bushes, and dimple cups. A
25-day crop can be harvested 3 times in a season if it is harvested
promptly; a 42-day crop, 2 times.

When the season changes, immature plants of a crop that cannot grow
in the new season are destroyed, yielding neither seed nor plant.
Farmers who "know" a crop will not ripen in time stop planting it
(the game shows such crops in red in the plot menu); a dwarf learns
this by watching seeds die at a season change, or by having enough
Planter skill. The harness must do the same check itself: never set
a 42-day crop with fewer than 42 days left in the season. That check
does not exist in `set_farm_crop` today. It is phase 1 work.

There is no crop rotation in this game. Soil productivity is only
affected by fertilizing, and the same crop may be grown indefinitely
without a decrease in performance, even without fertilizer.
"Rotation" in this plan means covering the fort's needs across
seasons, not resting the soil.

### 2.2 Yield

Each planted tile yields a stack of plants at harvest. Unfertilized,
a stack is 0 to 6 plants, depending on the planter's skill and
random chance; fertilizing adds up to 4 more plants per stack. The
exact mechanics: there is always at least 1 plant, and then up to 8
further checks, each with a 50 percent chance of adding one plant.
Four checks are for fertilization (25, 50, 75, 100 percent
fertilized) and four are skill checks (skill in 5, 10, 15, 20, and
75, capped at Legendary+10). A Legendary+10 farmer on a fully
fertilized plot averages 5.17 plants per seed. A dabbling planter
averages far less, which is why the sizing rule in section 6 plans
on a conservative yield and measures the real one.

Poor soil cuts every yield by 75 percent, with a minimum of 1.
Soil tiles in soil layers are poor, except in caverns. Muddied
stone in any stone layer is NOT poor. That is why the underground
farm room is dug into stone and muddied, not built on the first
soil layer found (FARMING.md documents the harness's poor-soil
note).

### 2.3 What a dwarf needs

A dwarf needs about 2 units of food and 5 units of drink per
season: 8 food and 20 drink per dwarf per year. A starting fort of
7 dwarves needs 56 food and 140 drink a year. Those two numbers
are the whole sizing problem, and they are the numbers the harness
plans against.

Brewing multiplies: one brewable plant plus one empty barrel makes
5 units of drink and returns 1 seed. Processing multiplies too:
quarry bush leaves and sweet pod syrup come out at five times the
plant stack. Milling does not increase stack size. So the drink
supply is a brewing problem as much as a farming problem: the farm
grows plants, the still turns each plant into 5 drink.

### 2.4 The crops

The six dwarven (subterranean) crops, all available on embark:

| Crop | Seasons | Days | Eat raw | Brew | Processed product |
| --- | --- | --- | --- | --- | --- |
| Plump helmet | all | 25 | yes | dwarven wine | none |
| Pig tail | summer, autumn | 25 | no | dwarven ale | thread (farmer's workshop) |
| Cave wheat | summer, autumn | 42 | no | dwarven beer | flour (mill) |
| Sweet pod | spring, summer | 42 | no | dwarven rum | sugar (mill), syrup (farmer's workshop) |
| Quarry bush | spring, summer, autumn | 42 | no | none | leaves (farmer's workshop), oil (screw press) |
| Dimple cup | all | 42 | no | none | dye (mill) |

The useful above-ground crops (all grow in any land biome except
mountains, glaciers, and tundra, unless noted):

| Crop | Seasons | Days | Eat raw | Brew | Processed product |
| --- | --- | --- | --- | --- | --- |
| Wild strawberry | all | 25 | yes | strawberry wine | none |
| Rope reed | all | 25 | no | river spirits | thread (farmer's workshop) |
| Longland grass | all | 25 | no | longland beer | flour (mill) |
| Prickle berry | all | 25 | yes | prickle berry wine | none |
| Fisher berry | all | 25 | yes | fisher berry wine | none |
| Rat weed | all | 25 | yes | sewer brew | none |
| Sun berry | all | 25 | yes | sunshine (25☼) | none, good biomes only |
| Whip vine | all | 25 | no | whip wine | flour (mill), savage only |
| Bloated tuber | all | 25 | yes | tuber beer | none, wetlands only |
| Muck root | all | 25 | yes | swamp whiskey | none, wetlands only |

Garden plants (artichoke, cabbage, potato, and dozens more) are
above-ground, grow year-round, and are biome-specific. They also
produce growths: leaves, buds, flowers, pods, fruits. They are
variety crops for later, not staples. Two wild plants, kobold bulb
and valley herb, have no seeds and cannot be farmed at all.

Crop roles, in one line each: plump helmet is the staple (food and
drink, every season). Pig tail is cloth. Cave wheat is flour for
cooking. Sweet pod is sugar and syrup. Quarry bush is leaves and
oil, and it is the hardest crop to farm early without fertilizer.
Dimple cup is dye only. Strawberry, rope reed, and longland grass
are the above-ground staples. Sun berries are the most valuable
above-ground drink. Everything else is variety.

## 3. What the harness knows and does today

Verified against the repo on 2026-11-27. Anything the harness
cannot do yet is named here so the plan does not pretend otherwise.

- `set_farm_crop` (actions.py) is the verified setter. It refuses
  a wrong crop, wrong season, mixed light, wrong biome, and zero
  seeds, and verifies the write by read-back. The full refusal
  matrix is in FARMING.md. It does NOT check days left in the
  season against growdur, and it does NOT know the fort's needs.
- `build_farm_plot` builds the plot and carries the farm summary
  (soil, light, biome) in its result.
- The `farm` task (daemon.py `_run_farm_task`) finds a built plot,
  picks the crop (dark plots always get plump helmets; light plots
  get the surface crop with the most seeds on hand that grows in
  this biome and season, from a hardcoded list of two: rope reed
  and longland grass), sets it, and waits for PlantSeeds jobs. It
  accepts building_id, plant, and season overrides. It plants one
  plot, once. It does not plan the season, the fort, or the next
  plot.
- The suggestion (assembler.py) fires when no farm plot exists and
  seeds exist: build a plot, then run the farm task.
- The farm task is verified live: plot #5 on the scratch fort,
  summer plump helmet, 9 of 9 tiles planted. The spring harvest on
  plot #2 produced 19 plump helmet plants in stock.
- The brew math is verified live: 1 brewable plant plus 1 empty
  barrel makes 5 drink plus 1 seed (materials.py, and M1 runs #17
  and #18, which brewed drink 33 to 68). The planner already brews
  when drink is low and cooks when food is low.
- `labor_toggle` (actions.py) enables or disables a labor on one
  citizen by name, with read-back verification. The farming plan
  uses it to assign planters. UNVERIFIED: the exact labor enum name
  the action expects for Farming (Fields). Phase 6 verifies it live.
- Fertilizer is not implemented. FARMING.md records the potash
  cost (floor(plot size / 4) + 1) and that a 3x3 plot has a maximum
  fertilization of 3. Nothing sets a plot to fertilize, nothing
  makes potash, nothing hauls it.
- Irrigation is not implemented. FARMING.md records that the
  map-block designation struct has no mud flag, so the harness
  cannot verify mud directly today.
- There is no seed reserve policy, no seed stockpile placement,
  no kitchen cook/brew permission control, no harvest monitoring,
  and no sizing rule. The planner's farm site is a hardcoded
  offset in sites.py (the old Athelunol coordinates), kept as a
  fallback. Farm plot placement must come from the scored site
  selection work (docs/SITE_SELECTION.md does not exist yet; it is
  queued work, not existing work).
- The scoring system records a "first farm" milestone, but
  scoring.py documents it as always False today. Farming work
  makes it detectable.

## 4. Crop selection

Crop selection is a computation over season, light, biome, seeds,
and the fort's needs. The agent never picks a crop from a list of
110. The harness computes the plan for the season and hands the
agent the top options with a one-line why each.

### 4.1 The season plan

The season plan is one crop per plot per season, chosen from what
the fort actually needs. The default plan for a young fort:

| Season | Underground plots | Surface plots |
| --- | --- | --- |
| Spring | plump helmet (staple) + sweet pod + quarry bush | strawberry, rope reed, longland grass |
| Summer | plump helmet + pig tail + cave wheat + sweet pod | strawberry, rope reed, longland grass |
| Autumn | plump helmet + pig tail + cave wheat + quarry bush | strawberry, rope reed, longland grass |
| Winter | plump helmet only | all-season surface crops only |

Rules the plan follows, in order:

1. The staple first. One plot always grows plump helmets (or
   strawberries above ground) every season, because drink is the
   survival need and plump helmets grow in all four seasons. A fort
   with no staple plot is a fort one bad season from thirst.
2. The season's industrial crop second. Pig tail in summer and
   autumn (cloth), cave wheat in summer and autumn (flour), sweet
   pod in spring and summer (sugar, syrup), quarry bush in spring
   through autumn (leaves, oil). A crop is only planted if the
   fort has the workshop to process it: no farmer's workshop, no
   pig tail; no quern or millstone, no cave wheat.
3. Variety third. Dwarves want variety in drink and food for happy
   thoughts, so once the staple and the industrial crop are covered,
   a third plot grows a different brewable (strawberry, fisher
   berry, sweet pod) for drink variety.
4. Dye last. Dimple cup grows only when the fort has a loom and a
   dyer and clothing to dye. It feeds no dwarf.
5. Never plant a crop the fort has no seeds for, no workshop to
   process, or no days left to ripen. A 42-day crop with fewer
   than 42 days left in the season is refused, with the days named.

### 4.2 What the agent sees

Per season, the snapshot carries the farm plan as named options:
"plot #2: plump helmet (staple, drink)", "plot #5: pig tail
(cloth, 26 seeds on hand)", each with one line. The full table
sits behind a query. The agent picks a plot's crop from the top
three options for that plot, or accepts the plan as a whole. It
never sees growdur numbers, biome flags, or seed counts unless it
asks.

## 5. Seed management

Seeds are the fort's future harvests. Losing them is worse than
losing a harvest, because a harvest can be replanted and a lost
seed stock cannot.

### 5.1 How seeds work

One seed is planted per tile. Eating a plant raw, brewing it,
milling it, or processing it returns 1 seed. Cooking a plant
destroys its seed. Cooking a seed makes it unusable for planting.
Each plant type has a fortress-wide seed cap, default 200, and
there is a fortress-wide total cap, default 3000; once the total
cap is reached, the oldest seeds on the map disappear. Seeds are
stored in bags of up to 100, and bags can go in barrels, but
barrels on a seed stockpile cause trouble (see 5.3).

The embark brings 30 seed items: 5 each of dimple cup, pig tail,
quarry bush, plump helmet, sweet pod, and cave wheat, in seed bags
inside the wagon. Above-ground seeds cannot be chosen at embark;
they come from gathering wild plants, or from elven and human
caravans.

### 5.2 The reserve rule

The harness keeps a seed reserve per grown crop: enough seeds to
replant every plot of that crop once, plus a seed bank of a few
seeds forbidden as insurance against disaster (the wiki's own
advice: set aside a few seeds from each type and forbid them).
The reserve is a number, not a feeling:

- Reserve = plot tiles of that crop + 5 bank seeds.
- Seeds above the reserve are spendable: they may be cooked, traded,
  or planted on a new plot.
- Seeds at or below the reserve are never cooked, never traded, and
  never planted on an experimental plot. The harness refuses any
  action that would spend them, and names the reserve in the refusal.
- When a crop's seeds fall below the reserve, the harness says so
  in the snapshot and suggests the acquisition path: gather (if the
  plant grows wild nearby), trade (buy seeds from the next caravan
  that carries them), or brew/eat the harvested plants instead of
  cooking them until the reserve is rebuilt.

### 5.3 The seed stockpile

A custom stockpile that accepts only seeds, placed near the farms
(a ring of farms around a central seed stockpile is the wiki's
layout, because a planter can then reach every plot quickly).
Rules, all from the wiki:

- Barrels set to 0 in the seed stockpile. One seed bag per tile,
  100 seeds per bag. Barrels cause "store item in container" jobs
  to block access to the seeds already inside, which spams job
  cancellations and stalls planting (Bug 9004). The harness must
  never place barrels on a seed stockpile.
- Four tiles hold 20 different crops. The stockpile is small on
  purpose: seeds are dense, and a small stockpile near the plots
  beats a large one across the fort.
- Seeds still in the wagon are named, not counted as available.
  The wagon must be deconstructed so planters can reach them
  (the farm task already reports this; the plan adds deconstructing
  the wagon as a standing early task).
- Seeds in the stockpile are the only seeds the farm task counts
  as plantable. Trader-held seeds are excluded (probe_seeds.lua
  already splits in-play from in-wagon; the plan extends that
  split to in-stockpile).

### 5.4 Acquiring more seeds

When the fort has no seeds for a crop it needs, the harness works
the acquisition paths in order:

1. Gather. Plant gathering on wild shrubs of that plant, if it
   grows in the local biome. The gathered plant is then brewed,
   milled, or eaten to yield seeds. The gather action exists.
2. Trade. Above-ground seeds from elven (spring) and human (summer)
   caravans; subterranean seeds from dwarven caravans (autumn).
   The buy list in docs/TRADING.md carries seeds as a standing
   item when a grown crop is below reserve.
3. Grow. Plant the seeds the fort has, fertilize them, and let the
   extra plants from fertilization rebuild the stock. Fertilizer
   doubles unskilled yields, which is the fastest way to grow a
   seed stock from a small one.

## 6. Plot sizing and placement

### 6.1 How many tiles

The sizing rule is arithmetic from the wiki's numbers, not a fixed
plot size. A dwarf needs 20 drink a year. A tile of plump helmets,
harvested 12 times a year at 5 plants a harvest and brewed at 5
drink a plant, makes 300 drink a year: 15 dwarves' drink per tile,
at full efficiency. A dabbling planter, unfertilized, averages
about 2 plants a harvest: 120 drink a year per tile, 6 dwarves
per tile. The harness plans on the conservative number and measures
the real one:

- Staple tiles = ceil(population / 6), minimum 9 (one 3x3 plot).
- Industrial tiles = one small plot per industrial crop the fort
  runs: pig tail 3 to 9 tiles, cave wheat 3 to 9 tiles, dimple
  cup 1 to 3 tiles. These are small because the fort needs cloth
  and flour in small amounts compared to drink.
- The rule is recomputed every season from the measured yield:
  actual drink produced per staple tile per season, read from the
  store's trends. If the measured yield is better than planned,
  the fort holds its plots; if worse, it adds tiles before the
  next planting, not after the fort runs dry.

The wiki's bounds say the same thing from the other side: a
properly managed 3x3 plot of plump helmets makes up to 2700
alcohol a year, enough for 95 dwarves; a 5x5 makes 7500, enough
for 265. Fifty tiles of farmland should provide all the food a
fortress will ever need. The sizing rule above is the conservative
version of those bounds, and it is deliberately conservative: a
young fort cannot use its tiles to full potential, and a plot that
is too big wastes planter labor that the fort needs elsewhere.

### 6.2 Small plots, not one big plot

Several small plots beat one large one, for four reasons, all from
the wiki:

- Each plot grows one crop per season. Small plots diversify: the
  staple, the cloth crop, and the flour crop grow at once.
- Small plots train new growers. A new planter practices on a
  1x3 or 3x3 plot; a legendary planter works the staple plot.
- Fertilizer is most efficient on plots of 4n - 1 tiles: 1x3, 1x7,
  3x5, 3x9, 5x7, 7x9. A 3x3 is close to efficient; a 4x4 is the
  worst shape.
- A single legendary planter can plant up to 100 tiles if the seed
  stockpile is close and they never harvest themselves. Tiles are
  nearly free; planter labor is the constraint, not land.

The starting layout for a 7-dwarf fort is one 3x3 underground
plot (plump helmet) and, once the fort has a farmer's workshop,
one 1x3 or 3x3 plot for the season's industrial crop. Surface
plots wait until the fort has seeds for them and a reason to risk
farmers outside.

### 6.3 Where the plots go

Placement is scored site selection (docs/SITE_SELECTION.md, queued
work, not existing work). Until it lands, the plan names the
factors a farm site is scored on, so the site work can take them
as requirements:

- Underground plots: dug room, dark, soil or muddied stone, near
  the still, the kitchen, the farmer's workshop, and the food
  stockpile. Hauling distance is the efficiency killer: a harvest
  carried across the fort is a harvest that withers.
- Seed stockpile in the middle of a ring of plots, barrels set to
  0, so planters walk a few tiles, not across the map.
- Potash stockpile near the plots, for the same reason: a
  legendary farmer must not spend the season hauling single bars
  of potash from the other side of the fort.
- Surface plots: protected, not open. The greenhouse trick
  (channel the roof, build a floor over the space: the tile
  becomes Light while roofed) lets the fort grow surface crops
  indoors. An open surface plot exposes farmers to attack, and
  the site score must gate it when hostiles are near, exactly
  like any other exposed site.
- Never on the main corridor, never blocking the only path, never
  in a room that will flood. A farm room that floods is a lost
  season.

## 7. Irrigation and muddying

Irrigation is only needed on stone. All soil can be farmed with
no irrigation, even sand. Irrigation does not improve soil: muddied
sand is still poor soil. Muddied stone in any stone layer is full
yield. Once a floor is muddied, no further irrigation is needed
unless the mud is removed (building a constructed floor or chopping
a tree on it removes it; smoothing a muddied stone floor cleans
the mud off, which destroys the farm plot on it).

### 7.1 Methods, in order of harness complexity

1. Bucket brigade. A water source zone over a body of water, a
   drop-off point above the farm room (a channelled hole in the
   floor above, so water falls through the open space), and a
   pit/pond zone set to pond. Dwarves carry buckets and pour.
   Any amount of water leaves at least a dusting of mud, which
   is enough. Farm plots cannot be built on water deeper than
   1/7, and more mud has no effect, so the minimum water is the
   rule. This needs zone placement machinery the harness does not
   have yet. UNVERIFIED as a harness route.
2. Murky pool drain. Dig into or around a murky pool and drain it
   across the farm room. The final water level must be under 2/7
   for the water to evaporate and leave mud. Use a small pool, or
   leave 5 to 6 times the pool's area for the water to spread and
   evaporate. Digging and channelling exist in the harness; the
   drain design is a composed dig task.
3. Screw pump. A pump lifts water and dumps it into a chamber
   next to the source, with a drain back to the source so the
   chamber never fills. Pumps are part of the advanced mechanics
   library (docs/ADVANCED_MECHANICS.md: wells, then pumps). An
   irrigation chamber is a later application of the pump work,
   not a first one.
4. Reservoir. A walled reservoir with floodgates, hatches, and
   levers feeding several fields. A 7x7 plot needs a floodgate, a
   hatch cover, 4 mechanisms, and a door, plus levers. This is a
   megaproject-scale composed task and comes last, if ever.

The plan starts with the bucket brigade and the murky pool drain,
because they need the least new machinery. A fort on deep soil
needs neither: the underground room is dug into soil and farmed
as-is, at the poor-soil yield, until the fort is ready to muddy
stone properly.

### 7.2 Safety

Irrigation is controlled flooding, and the flood rules apply.
The harness already has flood prevention in digging (aquifer and
water warnings) but no flood detection or response (a known gap,
docs/ADVANCED_MECHANICS.md). An irrigation task must therefore
carry its own safety:

- The water volume is bounded before the task starts: the source
  is named, the room volume is named, and the final water level
  is computed to be under 2/7.
- The drain route exists before the water moves. Water with
  nowhere to go is a flood, not irrigation.
- The farm room is sealed from the living areas while water is
  moving: a door or floodgate that can be closed.
- If water appears where it should not, the task stops and says
  so, with the location and depth. It does not keep pouring.
- Never irrigate with magma. It leaves no mud.

### 7.3 The mud verification gap

The harness cannot verify mud directly today: the map-block
designation struct has no mud flag (FARMING.md lists the fields).
So the irrigation phase must either find a mud read (probe the
tile's material or plant growth state through DFHack and verify
it live) or accept the game's own construction cancellation as
the backstop: if the plot cannot be built, the room is not
muddied, and the task reports that instead of claiming success.
The phase does not claim mud it cannot see. UNVERIFIED until the
probe is built and run live.

## 8. Fertilizer

Fertilizer is potash. The chain is: wood stockpile, wood furnace
makes ash (as bars), ashery makes potash (as bars). An ashery
needs a block, a barrel, and a bucket as components. Fertilizing a
plot costs floor(plot size / 4) + 1 potash, and the plot must be
re-fertilized every season. The fertilizer must be in place when
the seeds reach maturity; it does not matter whether the plot is
fertilized at the time of planting, and fertilizing near the end
of the season wastes potash. Only dwarves with the Planting work
order apply fertilizer, and each unit of potash applied grants 30
XP of farming experience.

### 8.1 When to fertilize

Fertilizer adds up to 4 plants per stack, and for unskilled
planters it can effectively double the yield. The decision rule:

- Fertilize the seed-building crop first. Early on, when the
  seed stock is small, extra plants mean more seeds for next
  season. Fertilizer is how a fort grows a seed stock from 5
  seeds to 200.
- Fertilize the staple plot when potash is plentiful. A fertilized
  staple plot feeds more dwarves per tile, which is what lets the
  fort hold its plot count as the population grows.
- Fertilize quarry bushes before planting them at all. The wiki
  notes they are nearly impossible to farm effectively in the
  beginning without fertilizer.
- Never fertilize when the potash is needed elsewhere and the
  plot would feed the fort anyway. Potash is also used for soap
  and for clear glass. The harness checks the potash stock
  against those uses before spending it on a plot.
- Never fertilize a plot whose crop will not ripen before the
  season ends. That is potash thrown away.

### 8.2 Plot shapes for fertilizer

Potash per plot is floor(size / 4) + 1, so the potash per tile
falls as plots grow, approaching a quarter bar per tile. The
most efficient sizes are one less than a multiple of 4: 1x3, 1x7,
3x5, 3x9, 5x7, 7x9. The worst are multiples of 4: a 2x2 or 4x4
plot uses the most potash per tile. The sizing rule in section
6.1 prefers 3x3 and 1x3 plots, which are close to efficient; the
plan never builds a 4x4 farm plot.

### 8.3 What is not built yet

Nothing in this section exists in the harness. The fertilize
flag on a plot, the potash production chain (wood furnace ash
job, ashery build, potash making job), the potash stockpile
near the plots, and the per-plot fertilize decision are all
phase 3 work. The plot struct already carries
`current/max_fertilization` and `seasonal_fertilize` (FARMING.md),
so the game state exists to read and write; the harness route
does not. UNVERIFIED until built and run live.

## 9. Harvest handling

A harvest is only food when it is in a stockpile. In the field it
is a timer.

### 9.1 Prompt harvest

Ripe plants must be harvested promptly. Unharvested plants wither
and eventually rot away, and withered plants are useless. The
harvest is a job any dwarf can do, and it gives a small amount of
grower experience. The harness watches for ripe plants sitting
unharvested: if a plot has been ripe for a day and no harvest job
has been taken, the snapshot says so, with the reason (no
harvester free, harvesters busy elsewhere, plot unreachable).

The "Everybody harvests" standing order is the default. The wiki
is explicit about the tradeoff: restricting harvesting to farmers
trains the planter faster, but if the lone planter dies, is
injured, or is busy, nobody harvests and the crops rot in the
fields. The harness rule is: everybody harvests, always, unless
the fort has two or more planters with the skill to cover the
work and the agent explicitly asks to train one. Safety beats
training speed.

### 9.2 Hauling and storage

Harvested stacks are hauled to the food stockpile. The stockpile
rules, all from the wiki:

- A custom stockpile that accepts only plants, near the still,
  the farmer's workshop, and the kitchen. Small specialized
  stockpiles near the workshop that uses them (millable plants
  near the quern, for example) save more hauling than one big
  food stockpile far away.
- Barrels hold the food. Food is subject to withering and to
  vermin. Metal barrels are especially effective against vermin.
  Prepared meals rot outside a food stockpile, so meals are
  cooked close to when they are eaten, not stockpiled for a year.
- If the fort has too many plump helmets, make a
  plump-helmet-only stockpile, forbid plump helmets from all
  other food stockpiles, and let the crops in the field die if
  they cannot be picked. Withering crops do not produce miasma,
  so there is no cleanup cost to letting a surplus crop die.

### 9.3 What the harness watches

Per season, per plot: planted, growing, ripe, harvested, withered.
The farm task already waits for PlantSeeds jobs and reports the
planted count. The plan extends that watch to the harvest: the
harness records how many plants were harvested per tile (the
measured yield the sizing rule uses), how many withered, and
whether the harvest reached the stockpile. A plot whose harvest
withers three seasons in a row is a diagnosed failure, not a
mystery: the diagnosis names the cause (no harvesters, no
stockpile space, plot unreachable) and the fix.

## 10. The farm-to-kitchen/still chain

The farm grows plants. The still, the kitchen, the farmer's
workshop, the quern, and the screw press turn plants into drink,
food, cloth, flour, sugar, syrup, leaves, oil, and dye. The chain
is a set of splits, and the splits are decided by the fort's
needs, not by the agent's memory.

### 10.1 The split rule

Every harvested stack goes to exactly one destination, in this
priority order:

1. Brew, to the drink floor. Drink first, because thirst kills
   and because brewing returns the seed. The drink floor is
   population times 5 per season, plus one season of reserve.
   Brewable plants are brewed until the floor is met. The still
   needs an empty barrel per job, and the harness already
   fail-fasts on barrels (materials.py).
2. Process, for the industrial crops. Pig tail and rope reed go
   to the farmer's workshop for thread, cave wheat and longland
   grass to the quern for flour, sweet pods to the mill for sugar
   or the farmer's workshop for syrup, quarry bushes to the
   farmer's workshop for leaves or the screw press for oil,
   dimple cup and dye plants to the mill for dye. Processing is
   only queued when the workshop exists and the product is
   needed: thread when cloth is below the per-dwarf floor,
   flour when the kitchen is short of cookable solids, dye when
   the fort has cloth to dye.
3. Eat raw, for the surplus of eatable crops. Eating returns the
   seed, so raw eating is seed-safe. Plump helmets, strawberries,
   prickle berries, fisher berries, and bloated tubers are eaten
   raw when the fort has more than the brew floor needs.
4. Cook, for the surplus above the seed reserve and the brew
   floor. Cooking destroys the seed, so cooking is last, and the
   harness refuses to cook a crop at or below its seed reserve.
   Lavish meals (4 ingredients) make the largest stacks and the
   most variety per job; easy meals (2 ingredients) train the
   cook faster. The kitchen already exists in the harness's job
   machinery (PrepareMeal, job type 115); the plan adds the
   split rule on top of it.
5. Trade, for the surplus above all of that. Prepared meals are
   the best trade good the fort makes (docs/TRADING.md, section
   6.1). Surplus meals go to the trade stockpile, not to the
   dining hall.

### 10.2 Kitchen permissions

The game has a Kitchen tab where each plant and seed can be
allowed or forbidden for cooking and brewing. Cooks prefer the
worst ingredients (single units of tallow) unless the fort
controls the list. The harness must control these permissions:
forbid cooking of every seed the fort grows, forbid cooking of
any crop at or below its seed reserve, and forbid cooking the
last of a crop. There is no harness action for kitchen
permissions today. UNVERIFIED as a harness route; phase 5 probes
it (the setting is game state, and the liaison meeting was solved
by writing game state directly, so a write route may exist).

### 10.3 Drink and food variety

Dwarves want variety in drink and food for happy thoughts. A
fort that brews only dwarven wine will have unhappy dwarves even
with full barrels. The season plan (section 4.1) grows a second
brewable for variety once the staple is covered, and the kitchen
combines four different ingredients per lavish meal. The snapshot
carries the drink variety count (how many distinct drinks the
fort holds) so the agent can see it without counting barrels.

## 11. Farm labor

### 11.1 Why skill matters so much

Planter skill decides planting speed and harvest stack size, and
stack size compounds through the whole chain. The wiki's example
is exact: to get 25 booze, brewing five stacks of plump helmet
[1] takes five trips to store the plants, five trips to haul
them, five barrels, five brewing jobs, and five tiles of storage.
One stack of plump helmet [5] takes one of each. A skilled
planter saves over 20 tasks per plant product. High-skilled
planters make the whole fort more efficient, not just the farm.

### 11.2 The labor rule

- One dedicated planter for a young fort. The wiki's advice is
  to disable all other labors on the planter, because farming
  labor is fairly low priority and a planter with other jobs
  will not plant. The harness assigns Farming (Fields) to the
  dwarf with the highest Planter skill and disables their other
  labors, through `labor_toggle`, with read-back verification.
- One planter per 100 tiles, at most. A single legendary planter
  can plant up to 100 tiles if the seed stockpile is close and
  they never harvest themselves. The fort adds a second planter
  only when the plots exceed what one planter can plant in a
  season, measured by the farm task's own waits, not by a fixed
  number.
- Trainee plots. New growers practice on small plots (1x3) with
  a cheap crop, so the fort's staple plot is never the training
  ground. Fertilizing the trainee plot gives 30 XP per potash,
  which trains faster than planting alone.
- A backup planter always exists. If the only planter dies, is
  injured, or is taken by a strange mood, the fort's crops rot.
  The harness keeps a second dwarf with Farming (Fields)
  enabled, even if they rarely plant, and says so in the
  snapshot. This is the same rule as the harvest rule: a single
  point of failure in food production is a fort-ending bug.

### 11.3 What the harness checks

Per season: who the planters are, their skill levels, whether
the dedicated planter is alive, idle, and assigned, and whether
any planter is stuck (no seeds reachable, plot unreachable,
labor disabled by a mood or injury). A planter who has not
planted in a season is a diagnosed failure with a named cause,
not a quiet zero.

## 12. Scaling as the fort grows

Farming scales by planning a season ahead, because the lead time
is a season: dig the room, build the plot, plant, wait 25 to 42
days, harvest, haul, brew. A fort that waits until it is hungry
to add plots is already a season late.

### 12.1 Population changes

Migrants arrive in waves, usually after a caravan leaves intact.
A wave can double the fort. The sizing rule (section 6.1) is
recomputed every season from the current population and the
measured yield, and the plan adds plots when the rule says the
fort will be short next season, not when it is short now. The
snapshot carries the forecast: "14 dwarves, drink for 9 days at
current stocks, 2 plots needed by autumn". The agent sees the
forecast, not the arithmetic.

### 12.2 New crops

New crops enter the fort three ways, and each has an onboarding
step in the plan:

- Gathered. A gathered wild plant is brewed, milled, or eaten to
  yield seeds, and the seeds are planted on a small trial plot
  the next season it can grow in. The trial plot is 1x3, so a
  failed crop costs 3 seeds, not 9.
- Traded. Seeds bought from a caravan go to the seed stockpile
  and enter the season plan the same way, subject to the biome
  and light checks (a seed the fort cannot grow is a refused
  purchase, not a surprise).
- Garden plants. Once the staple and industrial crops are
  covered, garden plants add food variety. They are biome
  specific and year-round, so they fill gaps the standard crops
  leave, especially in winter.

### 12.3 When the fort outgrows the farm room

The underground room is dug once and extended in strips (the
digging sequence is in FARMING.md). When the sizing rule needs
more tiles than the room holds, the harness digs the next strip
before the season it is needed, through the normal dig machinery,
and the new plots are built on muddied stone, not on soil, so
they are not poor. A fort that has to choose between digging a
new room and muddying stone picks the room first: soil is faster
to farm, even poor, and muddying is a project for when the fort
has hands to spare.

## 13. Failure modes

Every failure mode in this table has a diagnosis the harness must
produce, with the fix named. A silent zero is never acceptable.

| Failure | Cause | Diagnosis | Fix |
| --- | --- | --- | --- |
| No seeds for the crop | Stock spent, cooked, or traded; seed cap hit | "have 0, need N, reserve 0" | Gather, trade, or brew/eat to rebuild; never cook the reserve |
| Crop will not ripen | 42-day crop set with under 42 days left in the season | "X days left, crop needs 42" | Fallow the plot this season, or plant a 25-day crop |
| Plants wither in the field | No harvester free, or harvest restricted to a dead planter | "ripe for N days, no harvest job taken" | Everybody harvests; check the planter is alive |
| Harvest rots in stockpile | No barrels, no food stockpile space, vermin | "N stacks unhauled, 0 barrels" | Make barrels, build the food stockpile, use metal barrels |
| Plot never fully plants | Mixed light, or sunlit underground plot | "mixed Light/Dark" or "plot exposed to sunlight" | Rebuild the plot wholly one way; a sunlit underground plot never grows underground crops again |
| Seeds locked away | Seeds in a barrel, in the wagon, or behind a forbidden stockpile | "seeds in container / in wagon" | Barrels 0 on the seed stockpile; deconstruct the wagon; check the stockpile links (Bug 9004) |
| Planter does nothing | Labor disabled, no seeds reachable, plot unreachable, planter dead or in a mood | "planter idle, reason" | Re-enable the labor, free the seeds, check the path, promote the backup planter |
| Cooking ate the seed stock | Kitchen permissions allowed cooking the grown crop or its seeds | "seeds cooked, reserve breached" | Forbid cooking the crop and its seeds; rebuild from the bank |
| Irrigation flooded the room | Too much water, no drain, floodgate left open | "water at X/7 in the farm room" | Close the source, open the drain, wall off the living areas |
| Mud cleaned off | A dwarf smoothed the muddied stone floor | "plot unusable, mud gone" | Never smooth a farm floor; re-irrigate |
| Cavern creatures in the farm | Muddied cavern area left open | "hostile in the farm room" | Wall off the farm, post a guard, or move the farm |
| Seed cap reached | 200 per type, or 3000 total; oldest seeds vanish | "seed total at cap" | Stop hoarding; plant, brew, or trade the surplus |

Two failure modes the wiki does not document as game mechanics,
and the plan does not invent: there is no crop blight or disease
mechanic in the farming pages, and there is no soil exhaustion
(the same crop may be grown indefinitely). If a future live run
shows a withering pattern that matches neither rot nor season
change, that is a new finding to investigate, not a blight to
assume. UNVERIFIED: whether any hidden withering mechanic exists
beyond the documented ones.

## 14. The harness's role at each step

The harness owns the counting, the timing, and the refusing. The
agent owns the choice among named options. That division is the
standing cognitive load rule, applied to farming.

- Each season, the harness computes the season plan (section 4.1)
  from fresh collects: plots, light, biome, seeds, stocks, drink
  and food trends, population, and measured yield. It sets the
  crops, or hands the agent the top three options per plot with a
  one-line why each.
- Each day, the snapshot carries the farm state in plain words:
  plots and their crops, days to harvest, drink and food with
  days of supply, seed counts for grown crops against their
  reserves, and the one most urgent farm problem, if any.
- The farm task stays the unit of work: one plot, one planting,
  verified by PlantSeeds jobs appearing and finishing. The plan
  adds the season loop around it, not a replacement for it.
- Refusals name the cause and the fix, in the existing style:
  "have 0 pig tail seeds, need 9; gather pig tails or buy seeds
  from the autumn caravan" is a refusal; "cannot plant" is not.
- The journal records every planting, every harvest, every
  refusal, and every seed reserve breach, so the fortress history
  (docs/HISTORY.md, queued work) can tell the farm's story
  season by season, and the scoring system's "first farm"
  milestone becomes detectable.

## 15. Implementation phases, in order

Each phase is done only when its live-verification bar is met
against the real game. A phase is not done because the code is
written.

### Phase 1: Season plan and crop choice

- The season plan (section 4.1) computed from fresh collects:
  crop per plot per season, with the staple-first rule, the
  industrial-crop rule, and the days-left check (refuse a 42-day
  crop with fewer than 42 days left in the season).
- The farm task takes the plan instead of its hardcoded choice:
  dark plots still default to plump helmets, but light plots
  choose from the full surface crop list the fort has seeds for,
  not just rope reed and longland grass, and the choice is ranked
  by need, not by seed count alone.
- Live bar: on the main fort, the plan names the right crop for
  each plot in the current season, the days-left check refuses a
  late 42-day crop with the days named, and a full season runs
  with the plan's crops planted and harvested.

### Phase 2: Seed management

- Seed reserve policy (section 5.2) enforced in the farm task
  and in every action that spends seeds: refuse to spend below
  the reserve, name the reserve in the refusal.
- Seed stockpile placement: a seeds-only stockpile near the
  plots, barrels set to 0, built through the stockpile machinery
  (the food stockpile route in FARMING.md is the template).
- Seed bank: a few seeds of each grown crop forbidden as
  insurance.
- Live bar: on the scratch fort, the seed stockpile holds the
  fort's seeds in bags with no barrels, the reserve refusal fires
  when an action would spend below it, and a seed count taken
  from the live game matches the harness's count.

### Phase 3: Fertilizer

- Potash chain: wood furnace ash job, ashery build (block,
  barrel, bucket), potash making job, potash stockpile near the
  plots.
- Fertilize decision per plot (section 8.1) and the fertilize
  flag on the plot, with the cost check (floor(size / 4) + 1)
  before the job is queued.
- Live bar: a fertilized plot on the scratch fort yields larger
  stacks than an unfertilized control plot of the same crop in
  the same season, verified by the harvested stack sizes, and
  the potash stock is read back from the game.

### Phase 4: Irrigation

- Bucket brigade first (water source zone, drop-off channel,
  pond zone), then murky pool drain. The mud verification probe
  (section 7.3) is built first, so the phase can prove the room
  is muddied before claiming it.
- Safety rules from section 7.2 enforced in the task: bounded
  water volume, drain route first, room sealed while water moves.
- Live bar: a stone room on the scratch fort is muddied, a farm
  plot is built on it, and a crop grows there. The water level
  never exceeds 1/7 on the farm floor during the task.

### Phase 5: Harvest and the chain

- Harvest watch (section 9.3): ripe-plant age, harvested count
  per tile, withered count, all recorded per plot per season.
- The split rule (section 10.1): brew to the drink floor, process
  the industrial crops, eat the surplus raw, cook only above the
  reserve, trade the rest. The kitchen permission control is
  probed in this phase; if no write route exists, the phase
  reports exactly what was tried and the plan changes to warn
  the agent instead of enforcing the permission.
- Live bar: a full season end to end on the scratch fort: plant,
  grow, harvest, haul, brew, and the drink stock rises by the
  measured amount while the seed stock returns to at least the
  reserve. No harvested stack withers in the field.

### Phase 6: Labor and scaling

- Planter assignment through `labor_toggle`: one dedicated
  planter (highest skill, other labors disabled), one backup,
  trainee plots for new growers. The exact labor enum name is
  verified live in this phase.
- Seasonal re-plan: the sizing rule recomputed every season from
  population and measured yield, with plots added a season ahead
  of need. New-crop onboarding from gathered and traded seeds
  on 1x3 trial plots.
- Live bar: the dedicated planter is verified live with the
  labor enabled and other labors disabled; a season's re-plan
  adds a plot before the population it serves arrives, and the
  trial plot grows a newly acquired crop.

### Phase 7: Failure-mode hardening

- Every row of the table in section 13 demonstrated, live or in
  a controlled test, with the diagnosis naming the fix. The
  flood guard on irrigation, the Bug 9004 watch on the seed
  stockpile, and the seed reserve breach alarm are part of this
  phase.
- Live bar: each failure mode produces the documented diagnosis
  in the run log, and no failure mode produces a silent zero.

## 16. Open questions

- Mud verification. The map-block designation struct has no mud
  flag. The irrigation phase must find a mud read or accept the
  game's construction cancellation as the backstop. UNVERIFIED.
- Kitchen permissions. Whether the harness can write the
  cook/brew allow list for plants and seeds is UNVERIFIED.
  Phase 5 probes it.
- Pond zones for the bucket brigade. Whether the harness can
  place a pit/pond zone and set it to pond is UNVERIFIED. The
  zone machinery does not exist yet.
- Labor enum name. The exact name `labor_toggle` expects for
  Farming (Fields) is UNVERIFIED until phase 6 runs it live.
- "Red crop" state. Whether the game exposes, through DFHack,
  the knowledge that a crop will not ripen before the season
  ends is UNVERIFIED. The plan does the days-left arithmetic
  itself and does not depend on reading the game's flag.
- Seed caps. The 200-per-type and 3000-total caps are the
  defaults from the wiki. Whether the fort's settings differ is
  UNVERIFIED; the harness reads the live counts, not the
  settings.
- Garden plant growths. Garden plants produce leaves, fruits,
  and flowers in addition to the plant itself. Whether those
  growths are harvested and usable through the same jobs is
  UNVERIFIED and out of scope until the staple system works.

## 17. Refusals

The harness never does any of the following, whatever the agent asks:

- Plant a crop with no seeds, in the wrong season, on mixed
  light, or in a biome it cannot grow in. The existing refusal
  matrix stands.
- Plant a 42-day crop with fewer than 42 days left in the season.
- Spend seeds below the reserve, cook a seed, or cook the last
  of a crop.
- Put barrels on a seed stockpile.
- Smooth a muddied farm floor.
- Irrigate without a drain route, or with an unbounded water
  volume.
- Fertilize a plot whose crop will not ripen, or spend potash
  the fort needs for soap or glass without saying so.
- Restrict harvesting to a single planter with no backup.
- Claim a harvest, a yield, or a muddied room it cannot verify
  from the live game.

## 18. Sources

Wiki pages, read from the local DF wiki index
(`~/workspace/df-wiki-export/dfq.py`) on 2026-11-27:

- Farming (5,291 words): the season, light vs dark, soil and
  poor soil, yield mechanics and the exact yield table,
  fertilization costs and potash chain, growth durations,
  seed management and caps, Bug 9004, greenhouse trick.
- Farm size calculations (1,189 words): 2 food and 5 drink per
  dwarf per season, the crop yield table, 3x3 and 5x5 plot
  outputs, the 50-tile bound, the 100-tile planter bound, the
  seed stockpile in the middle of a ring of farms.
- Crop: the six dwarven crops and the above-ground and garden
  crops, with seasons, biomes, drinks, edibility, and processing
  products.
- Irrigation: muddying methods (buckets, murky pool, screw pump,
  reservoir), water levels, smoothing cleans mud, magma leaves
  no mud.
- Kitchen: meal types, cooking destroys seeds, cooks prefer the
  worst ingredients, feeder stockpiles, liquid ingredient rules.
- Still and Alcohol (via search): 1 plant plus 1 empty barrel
  makes 5 drink plus 1 seed; brewing needs a still, a brewable
  plant, and an empty barrel or pot.
- Planter (1,162 words): skill effects on stack size and speed,
  the 20-task saving from large stacks, everybody-harvests vs
  only-farmers-harvest, the lone-planter risk.
- Ashery (via search): potash making, block plus barrel plus
  bucket as components.

Harness sources, read from the repo on 2026-11-27:

- `docs/FARMING.md`: the mechanics reference, the refusal matrix,
  the probe_crop root cause, the live verification notes.
- `src/dfagent_harness/daemon.py` `_run_farm_task`: the farm
  task's crop choice (dark to plump helmets, light to the
  most-seeded of rope reed and longland grass).
- `src/dfagent_harness/actions.py`: `set_farm_crop`,
  `build_farm_plot`, `labor_toggle`, the brew job
  (BREW_DRINK_FROM_PLANT), PrepareMeal.
- `src/dfagent_harness/materials.py`: have/need machinery and the
  brewable-plant rule.
- `src/dfagent_harness/assembler.py`: the farm suggestion.
- `src/dfagent_harness/sites.py`: the hardcoded farm site
  fallback.
- `src/dfagent_harness/planner.py`: brew when drink is low,
  cook when food is low.
- `docs/TRADING.md`: the buy list's seed items, prepared meals
  as trade goods, the per-dwarf emergency thresholds.
- `docs/ADVANCED_MECHANICS.md`: flood detection and response
  gap, wells and pumps.
- `docs/SITE_SELECTION.md`: does not exist yet; farm plot
  scoring is queued work.

## 19. Model presentation

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

### 19.1 Snapshot: the Farm section

The per-tick snapshot gains a short Farm section, built from the
fresh collect, in plain words. Three lines, in this shape:

```
Farm: 2 plots (plump helmet, pig tail). Seeds: plump helmet 41, pig tail 23, cave wheat 18.
Planters: 2 enabled (Olon, Ral). Harvest: 19 plump helmet ready.
```

What is in it, and what is not:

- **Line 1, plots and seeds.** How many farm plots exist and
  what crop each holds, then the seed counts for the crops the
  fort grows, capped at 4 crops. These are counts, not a list:
  the fort's seed stockpile may hold a dozen seed kinds and the
  snapshot never names all of them. When no plot exists, the
  line says so and names the fix: "No farm plot. Seeds on hand:
  plump helmet 41. Build one." A missing plot is an exception,
  not a silence. (The suggestion in assembler.py already fires
  in this case: build a plot, then run the farm task.)
- **Line 2, planters.** How many citizens have the farming labor
  enabled, named when there are 3 or fewer, counted when there
  are more. The labor enum name the action expects for Farming
  (Fields) is UNVERIFIED, so the line names citizens, never the
  enum.
- **Line 3, harvest.** What is ready to harvest now, in counts.
  When nothing is ready, the line says so and names the next
  expected harvest in words ("plump helmet ready in about 3
  weeks", from growdur and the season clock), never as a bare
  number.
- **Diffs, not repeats.** When nothing in the section changed
  since the last tick, the assembler prints the short form
  ("farm: unchanged"), the same way the Buildings section
  already does. The section costs its full price only on ticks
  when farm state actually moves.

**Token cost.** At 7 dwarves, the section as written above is
156 characters: about 52 tokens by the accountant's
3-chars-per-token rate, 39 on the wire. At 50 dwarves, with
more plots and more planters, it is about 340 characters: about
113 tokens by the accountant, 85 on the wire. The cost grows by
about 30 tokens from 7 dwarves to 50, because the section is
capped: 4 seed counts maximum, 3 planter names maximum, 1
harvest clause. It does not grow with population, with the
number of plots, or with the number of seed kinds in stock. If
a future change makes it grow with any of those, the change is
refused until the section is capped again.

### 19.2 Query route: GET /v1/farm (UNVERIFIED)

GET /v1/farm returns the full detail, read from the fresh
collect, not from a cache. This route does not exist yet; it is
part of the implementation phases in §15, and the snapshot
section above is written against it as a design target, not
against a live route.

- Per plot: id, position, size, soil, light, biome, crop set,
  season, fertilized or not, and the PlantSeeds jobs queued
  on it.
- Per crop: seeds in stock, seeds in the ground, growdur, the
  season it grows in, and what it becomes (food, drink, cloth,
  oil).
- Seed reserve: the reserve policy from §5, per crop, and
  whether any crop is below its reserve.
- Harvest: what is ready now, what is growing, and the expected
  harvest dates from growdur and the season clock.
- Fertilizer and irrigation state: potash on hand, plots
  fertilized, and whether each plot is muddied, with the
  verification limits the doc records (the map-block
  designation struct has no mud flag, so mud cannot be
  verified directly today).

The snapshot carries the summary and the ids; the route carries
the detail. The agent asks the route when it needs to choose a
crop or a plot, never as a matter of routine. Until the route
exists, the same detail is behind GET /v1/buildings (plots are
buildings) and GET /v1/stocks (seeds are stocks), which do exist
today.

### 19.3 Briefing: what arrives just in time

Farming has no standing briefing. Two events carry one, both
from the existing briefing system (briefings.py), each a few
hundred tokens at most, each fired once when the event starts:

- **First seeds, no plot.** Trigger: the fort holds seeds and
  has no farm plot. Cost: about 60 tokens by the accountant.
  It covers that seeds exist, which crop the fort has most of,
  and that a plot is the fix. It leaves the plot placement to
  the scored site system and the crop choice to §4.
- **Harvest ready.** Trigger: a crop reaches harvest. Cost:
  about 50 tokens. It covers what is ready and how much, and
  that leaving it unharvested loses it. It leaves the harvest
  labor assignment to §11.

No other farming event briefs the model. A plot being built, a
crop being set, or a planter being assigned are attention entries
and opportunities entries, not briefings. A briefing is for
something the model needs to understand right now, not for
something it can read in the snapshot.

### 19.4 Opportunities: at most 3, facts only

The opportunities section carries at most 3 farming entries,
each one line: facts plus a query route, never a suggestion, never
a pause. Ignoring one costs nothing. Examples of what qualifies:

- "Farm: seeds on hand, no plot. Query /v1/farm for the seed
  counts."
- "Plump helmet 19 ready to harvest. Query /v1/farm for the
  plots."
- "Pig tail seeds 0, reserve breached. Query /v1/farm for the
  seed reserve."

An opportunities entry fires only when the fact is actionable
and the snapshot alone does not already say it. A plot with a
crop growing is not an opportunity; it is the snapshot doing
its job. The entry never names the action to take and never
carries a cost estimate. The model decides.

### 19.5 What the system deliberately does NOT push, and why

- **The full seed list.** The snapshot names 4 seed counts; the
  full list is behind GET /v1/farm. A list of every seed kind
  every tick is a dump, and the model cannot act on the 9th
  seed kind anyway.
- **Per-tile plot state.** Which tile of a plot is planted, and
  when each tile was sown, is survey data, pulled by region
  when the model needs it. Pushing it would grow the snapshot
  with the map, which breaks the index.
- **Fertilizer arithmetic.** The potash cost per plot
  (floor(plot size / 4) + 1) and the fertilization maximum are
  behind the query route. The snapshot says whether a plot is
  fertilized. The arithmetic is there when the model asks.
- **The whole job queue.** The snapshot says how many PlantSeeds
  jobs are queued. The full queue, with job ids and positions,
  is behind the route. A queue dump would grow with every job
  the fort queues.
- **Crop choice as a suggestion.** The snapshot never says "plant
  plump helmet". Crop selection is §4, and the model asks for
  the farm detail when it decides. The presentation gives the
  model what it needs to decide, not a script to follow
  (HARNESS_ROLE.md).
