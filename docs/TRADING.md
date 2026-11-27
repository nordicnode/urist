# Trading

Design document for how the Urist harness handles trade. This is a plan, not
an implementation. Nothing here is built yet. Every game mechanic in this
document comes from the local Dwarf Fortress wiki index (see Sources at the
end) or from live verification against the real game. Anything not verified
against one of those two is marked UNVERIFIED.

## 1. Purpose

Trade is how a fortress gets what it cannot make. The harness must turn
trading from a thing the agent has to remember into a thing the harness
drives: the harness knows the caravan calendar, watches for arrivals, works
out what the fort lacks, values what it can sell, and hands the agent a
small set of named choices. The agent picks; the harness does the
bookkeeping. This document covers the whole loop: depot, caravan, liaison
and agreement, offer, animals, and the refusals that keep the fort safe.

## 2. How trading works in DF 0.47.05

All of this section is from the wiki pages listed in Sources. Where the
wiki itself flags a claim as unverified, this document says so.

### 2.1 The caravan calendar

Each friendly civilization sends one merchant caravan per year, and each
race always trades in one season: elves in spring, humans in summer,
dwarves in autumn. No race trades in winter by default. A fortress founded
in spring will almost certainly see only the dwarven caravan in its first
year. If the fort has friendly contact with several civilizations of the
same race, it can get several caravans in one season.

Caravans only arrive if the race considers the site accessible and worth
the effort, except the home dwarven civilization, which always arrives
unless it is extinct. A caravan appears at the map edge, walks to the
trade depot, unloads, and leaves 30,000 to 40,000 ticks (25 to 33 days)
after arrival. The announcement that it will leave soon comes about 4
days before it departs. If a caravan cannot reach the depot, or there is
no depot at all, it bypasses the site. A caravan that is spooked by
wildlife or corpses, or ambushed, turns around and leaves.

What each race brings:

- Dwarves (autumn): metal bars, leather, weapons and armor, food and
  booze, books. Dwarves alone bring steel and steel goods. The home
  caravan sends an outpost liaison with it. It is heavily guarded. Its
  goods cannot be seized from the trade menu. If the caravan leaves
  intact, it influences how many immigrants arrive.
- Elves (spring): cloth, ropes, above-ground seeds, plants and their
  byproducts, logs, wooden goods and weapons, clothing and armor, and
  sometimes tame exotic creatures. No wagons, only pack animals, so the
  weight limit is much lower. Unguarded. See 2.5 for what they refuse.
- Humans (summer): metal bars, sand, leather, cloth, wood, food and
  booze, books, ropes, waterskins, quivers, backpacks, metal weapons and
  clothing and armor, cages, a few domestic animals. Moderately guarded.
  Humans pay twice as much (base value with quality multiplier only) for
  equippable weapons, wearable armor, helms, gloves, leggings, boots,
  shields, ammo, backpacks, and quivers. A treasurer may arrive to
  negotiate agreements.

Caravan size: a wagon carries 15,000 weight; pack animals carry a
variable amount. Before the fort is a barony, a caravan brings at most
200 items on at most two pack animals, whatever the weight limit would
allow. The number of merchants, and with it the amount of wares, depends
on the fort's status (pre-barony, barony, county, duchy, mountainhome)
and on trade sentiment with that civilization.

### 2.2 The trade depot

The depot is a 5x5 building. It costs 3 building materials (non-economic
stone, wood, or metal; the job type follows the material: masonry,
carpentry, or metalsmithing). It must be at least 10 tiles from the map
edge. Build exactly one: the wiki reports that multiple depots break
caravans (wagons path to one depot, pack animals to the other, both groups
wait for the rest of the party, wagons scuttle).

Wagon access is the hard requirement. A tile is wagon accessible only if
it is navigable both to the depot and to the map edge. Wagons cannot use
stairs, and traps, boulders, and minecart tracks block them (pack animals
can cross traps). Wagons need a 3x4 parking space next to the depot.
Heavily forested maps may have no wagon path at all until a path is
chopped. Forbidding the depot (by forbidding any material used to build
it) makes it inaccessible, and an inaccessible depot makes the caravan
bypass the site.

The depot should be inside the fort, or secured with walls and bridges,
with a 3-tile wide clear path to the entrance. Thieves follow caravans.
The depot is also where purchased goods sit after the caravan leaves, and
the wiki reports a bug: purchased items stay at the depot indefinitely
unless a stockpile exists at the same level as the depot (Bug 12920).

### 2.3 Moving goods and the trade screen

When a caravan arrives, the "move goods to/from depot" screen opens. The
agent marks items to sell; dwarves haul them to the depot (trade good
hauling is a high-priority work detail, done by almost all non-specialized
dwarves, children included). Items in bins, bags, and barrels move as
whole containers; individual items inside a container cannot be marked
separately, though items in bins can be traded individually once at the
depot. Items in bags and barrels can only be traded as a whole. The
screen hides items under an export mandate unless the mandate filter is
switched off.

Once goods are at the depot and the fort's trader is present, the Trade
button opens the trade screen. The trader is the broker if one is
appointed, or anyone if not. The broker's Appraisal skill decides how
accurately values are shown; without a skilled broker, values are
estimates. The trader must be at the depot: "broker requested at depot"
summons only the broker (slow if the broker is busy), "anyone requested
at depot" summons whoever is nearest (fast, but values are inaccurate).

In the trade screen the agent picks items to offer (right) and items to
take (left). Every caravan has a weight limit, shown in the screen.
Merchants will not agree unless they make adequate profit. The displayed
profit color is the rule the harness uses: red is always rejected (when
all items are correctly appraised), green is always accepted, yellow is
uncertain. If any selected item is only estimated in value, the color
rules change: red when the calculated profit is negative, green when the
merchant would accept anyway, yellow otherwise. The wiki states the
merchant always accepts when the real profit is at least 50 percent, even
if the display says red.

Merchants counteroffer. Each counteroffer after the first lowers merchant
mood by 10 times the current haggle-failure count, so mood falls fast
during haggling. A successful deal resets the count to zero and raises
mood in proportion to the profit margin. A deal with zero profit does not
raise mood. Merchant mood starts at 50 each visit and ranges 0 to 100.

Gifts: "offer as gift" gives selected items to the civilization's leaders.
Only items made at the fort can be gifted. Gifts are believed to raise
trade sentiment and the size of next year's caravan, but the wiki flags
the exact effect as unverified. The Monarch requires offerings before
arrival. The harness treats gifts as a deliberate, agent-chosen spend,
never a default.

Seizing: the trade screen has a Seize button. Seizing goods makes the
merchant leave at once, hurts relations, and marks the goods so other
races will not buy them unless laundered by decoration or remaking. The
home dwarven caravan cannot be seized. The harness NEVER seizes. This is
a refusal, not a tactic.

### 2.4 The liaison and the trade agreement

The outpost liaison arrives with the dwarven caravan each autumn and
meets the expedition leader, mayor, baron, count, or duke. The meeting
has two parts: the liaison shares news, then draws up a trade agreement.
In the agreement the fort requests specific items for next year's caravan
and the liaison names prices the civilization will pay for goods it
wants. The fort is not obligated to supply the requested goods.

The agreement changes what next year's caravan brings: the caravan loads
up to four items of each requested type first, then emergency supplies,
then random goods. It also changes prices: both the buying and the selling
price of items in the agreement are raised. Requesting an item therefore
makes it more expensive to buy, so the fort should request only what it
cannot get another way.

Agreements are cleared when a liaison of that civilization appears on
screen, so the current agreement is not readable after the caravan
arrives. The harness must record the agreement in its own journal and
history before the caravan arrives, or the information is lost. Human
civilizations may send a trade representative (a treasurer) with the
summer caravan; the agreement works the same way. The negotiation itself
gives about 500 experience, split among the social skills used, to both
sides.

The liaison also grants noble promotions (baron, then count, then duke)
when the fort qualifies, and only if the liaison leaves the map alive.
If the leader is replaced, killed, or taken by a strange mood, the
liaison may leave unhappy and no agreement is made.

### 2.5 Trading with elves

Elves refuse wood and animal products entirely, and they end the whole
trading session if offered any. The ban covers items made of or decorated
with wood (including tower-cap fungus wood), wood derivatives (ash,
potash, pearlash, charcoal, lye, tallow soap), clear and crystal glass
(they need pearlash), obsidian short swords (wooden handles), body parts
(bone, shell, horn, ivory, hair, chitin, scales), leather and parchment,
wool yarn and cloth, meat, fish, fat, tallow, eggs, prepared meals using
any of those, corpses, and blood. Containers holding a banned item are
also refused, as are acceptable items stored in a banned container.
Wooden bins may be used to haul goods to the depot, but the bins
themselves must not be offered.

Elves accept stone, metal, green glass, ceramic, all rough and cut gems,
blocks of any material, plant and fungus products (crops, seeds, leaves,
plant fiber cloth, booze, dye, flour, sugar, syrup, oil, paper), silk,
honey, royal jelly, mead, wax, cheese, milk, prepared meals made only
from allowed ingredients, grown wood items, and live creatures in cages
made of acceptable materials. The harness must filter every elf offer
through this list before the agent ever sees it. One wrong item ends the
session and can lead to war after repeated offences.

### 2.6 Trade sentiment and the long game

Trade sentiment with a civilization rises with profitable trades and
falls with losses, seizures, destroyed caravans, and offences. Sentiment
decides how much the next caravan brings. The wiki states the relative
profit against the caravan's initial value matters, not the absolute
profit. A fort that squeezes every trade to zero profit gets smaller
caravans next year; a fort that gives a fair profit gets bigger ones.
Sending a messenger to a civilization to improve relations is an option
the wiki names, but it is not available for the home civilization, and
the messenger machinery is not part of this plan (UNVERIFIED as a
harness route).

Caravans also bring emergency supplies on their own: if the fort's
unforbidden stocks are low, they bring extra food, logs, and cloth or
leather. The wiki gives the thresholds per dwarf: 5 pieces of food, 1
wood log, 5 pieces of undamaged cloth, leather, or complete sets of
pristine clothing. This is the game's own safety net. The harness does
not game it by forbidding stocks to fake a shortage; it reads the same
thresholds as the definition of "low" for its own buy list.

## 3. What the harness knows today

Verified against the repo on 2026-11-27. Anything the harness cannot do
yet is named here so the plan does not pretend otherwise.

- There is no trade depot on either fort. The scratch fort has none, and
  a Gatizkadol caravan once bypassed its inaccessible site with the
  announcement "merchants need a trade depot". The main fort has none
  either. No depot-build action exists. The building type does exist in
  the live runtime enum (`TradeDepot` in
  `tests/fixtures/runtime-enums-0.47.05-r8.json`), so the generic build
  machinery can address it, but no composed depot task exists.
- The liaison meeting is handled programmatically. `docs/DIALOGS.md`
  records the verified route: the dipscript jump (`resolve_meeting.lua`)
  ends the meeting by writing the meeting's current step to its farewell
  step and dismissing the screens. It was proven live on 2026-11-27 with
  no keypress. The standing rule (GOAL.md, item 17) is that once trade
  exists, a liaison meeting must be surfaced to the agent instead of
  auto-ended, because a fort with a depot can use the trade agreement.
  Until trade exists, the dipscript jump stays the default, because the
  meeting freezes the clock and there is nothing to gain from it.
- The trade screen is game-committing and the harness refuses it.
  `docs/DIALOGS.md` records the live verification: a trade screen
  (`tradegoods/NoTraders`) was shown, `dialogs.advance` returned
  `ok=false` with `blocked_by="tradegoods/NoTraders"`, and the screen
  was NOT dismissed. The harness names a game-committing modal and
  returns it as a failure, never choosing for the player.
- A caravan briefing exists in `briefings.py`: what a caravan is, what
  usually matters, the options, the cost of ignoring it. It is served
  when a caravan event fires. The event kinds exist in the event system.
  What does NOT exist is caravan detection itself: no live test has
  shown the harness noticing a caravan arrival, because no caravan has
  ever reached a depot on either fort.
- The broker noble exists in the harness: `actions.py` maps broker to
  position id 12, and the noble-appointment machinery is built. No
  broker has been appointed on the main fort. UNVERIFIED: whether
  appointing a broker through the harness's noble route works live for
  the broker position specifically (the route is verified for other
  positions; the broker is one more position id).
- Valuation exists. `lua/wealth.lua` computes fortress value live as the
  sum of `dfhack.items.getValue` over in-play items, excluding
  trader-held goods, items on the ground, and abstract world artifacts.
  That gives the harness a real per-item value read it can reuse for
  offer construction. It does not yet read the caravan's goods, because
  no caravan has ever been at a depot.
- The have/need machinery exists in `materials.py`: `check_requirements`,
  `check_job`, `check_workshop`, `requirements_for_state`, and the
  brewable-plant rule. It answers "have X, need Y" for any job or
  workshop, from fresh per-tick collects. The trading plan builds the
  buy list on top of this, not beside it.
- The scoring system records a "first trade" milestone, but
  `scoring.py` documents it as always False today: no trade has ever
  happened, so the milestone cannot be detected yet. Trading work makes
  it detectable.
- Observation gaps that trade depends on: the units section emits
  citizens in full detail and hostiles, but the fort's animals appear
  only as a count (GOAL.md records this as a verified gap). Livestock
  decisions need named animals, so the animal observation fix is a
  prerequisite for the animal half of this plan, not an afterthought.
- Scored site selection is queued work, not existing work.
  `docs/SITE_SELECTION.md` does not exist yet. The depot site is scored
  like any other building once that work lands: inside, wagon-accessible,
  near the stockpiles, not blocking the main corridor.

## 4. Fortress needs assessment: the buy list

The buy list is computed by the harness, not invented by the agent. It
is rebuilt every season and whenever a caravan is detected, from fresh
collects, and it is ranked. The agent sees the top of the list, not the
whole table.

### 4.1 How the fort's needs are measured

1. Survival floor first. Drink, food, wood, cloth and leather are
   checked against the per-dwarf thresholds the game itself uses for
   emergency supplies: 5 food, 1 log, 5 cloth or leather pieces per
   dwarf, all unforbidden. Below the floor, the need is ranked highest.
   Drink and food are already tracked per tick; the trading plan adds
   wood, cloth, and leather to the same check.
2. Have/need for every active production chain. `materials.py` already
   answers "have X, need Y" for a job. The buy list extends that
   question to the fort level: for each workshop the fort runs, what
   input is short, and can it be produced locally at all? A short input
   that local production cannot supply (no ore on the map, no sand, no
   clay, no flux) becomes a buy-list item. A short input that local
   production can supply becomes a gather or dig task, not a purchase.
   The survey (`/v1/survey`) is the source for what the map lacks.
3. What the fort cannot produce at all. Some goods are unobtainable
   locally by construction: steel (needs iron and flux, and the wiki
   notes dwarves alone bring steel), books, foreign weapons, sand and
   clay if the map has none, above-ground seeds if the biome has none,
   silk if there are no cave spiders. These are standing buy-list items,
   ranked by how much they unblock: steel unblocks armor and weapons,
   sand unblocks glass, clay unblocks pottery.
4. Consumables the fort burns through. Picks, anvils, and other tools
   are one-offs; cloth and leather for clothing wear out and need
   steady replacement; soap, splints, crutches, and traction benches
   are hospital stock. The buy list carries a standing minimum for
   these, derived from the stockpile counts, not from a fixed number.
5. Seasonal timing. The buy list is ranked against the next caravan on
   the calendar, not against all caravans. If the next caravan is the
   elven one, the list is filtered to what elves carry and what elves
   accept in return. If it is the dwarven one, steel and books move up.
   If it is the human one, sand, leather, cloth, and domestic animals
   move up.

### 4.2 Ranking

The ranking is a table in the harness, not a feeling. Each candidate
item gets a rank from four factors, in this order:

1. Survival: does the fort run out of something a dwarf needs to live?
   Drink, food, wood for barrels and beds, cloth for clothes.
2. Unblocking: does the item unlock a production chain or a defense
   that is currently impossible? Steel, sand, flux, an anvil.
3. Scarcity: can the fort make it, gather it, or dig for it? If not,
   it ranks above anything locally obtainable.
4. Value density: for two items that satisfy the same need, the one
   that costs fewer trade goods wins. Value is read live with
   `dfhack.items.getValue`, the same read the wealth system uses.

The snapshot carries the top three buy-list items with a one-line why
each. The full list sits behind a query route. The agent never sees raw
stock counts unless it asks.

## 5. What to sell

### 5.1 Surplus rules

An item is sellable only after the fort's own need is met, with a
reserve. The reserve is a number, not a guess, and it is set per
category:

- Food and drink: never sell below the per-dwarf floor (5 food per
  dwarf) plus one season of consumption. Prepared meals are the
  exception in the other direction: they are the best trade good the
  fort makes, and the kitchen can cook more, so surplus meals above the
  floor are sold freely.
- Wood: never sell below the logs needed for barrels, beds, and bins
  for the next season. Wood is also the elves' red line, so wood is
  never in an elf offer at all.
- Cloth and leather: never sell below the per-dwarf floor (5 pieces per
  dwarf). Clothing wears out; selling the fort's clothes stock is
  selling its own future.
- Stone: stone is effectively unlimited on most maps, so stone goods
  are sold freely. Flux stone is the exception: keep it for steel.
- Metal bars: never sell the last bars of a metal the fort still needs
  for armor, weapons, or mechanisms. Surplus bars of a metal the fort
  has in bulk are sold as finished goods, not as bars (finished goods
  are worth more per bar, see 6.1).
- Seeds: never sell the last seeds of a crop the fort grows. Seeds are
  the fort's future harvests.
- Bins, barrels, and bags: the containers themselves are sold only
  when empty and surplus. A bin full of trade goods is the delivery
  mechanism, not the merchandise.

### 5.2 Value density

The caravan has a weight limit, and the depot has a hauling cost. The
harness ranks sellable goods by value per unit weight, using the live
`dfhack.items.getValue` read, and prefers goods that are light, small,
and high value. The exact ranking is computed at offer time from the
real stocks, not from a fixed table, because quality changes value: a
masterwork stack of bolts is worth far more than a masterwork minecart,
while a plain minecart is worth more than plain bolts. The rule is
mechanical: value divided by weight, highest first, with a preference
for goods the fort can make again next season.

### 5.3 What never to sell

- Artifacts. Trading one away triggers a special notification and the
  fort loses something irreplaceable.
- Anything under an export mandate. The move-goods screen hides these
  by default; the harness must not switch the mandate filter off to
  reach them, and must not let the agent sell a mandated item by
  accident. A mandate violation brings disciplinary action against the
  dwarf who carried the item to the depot.
- Anything the fort has only one of and still uses: the last anvil,
  the last pick, the last bucket for the well.
- Seized or stolen goods. Items marked as stolen from another caravan
  cannot be traded as they are; they must be decorated or remade
  first. The harness does not seize, so this should not arise, but the
  offer builder must refuse red-marked goods.
- Wood and animal products to elves, per 2.5. The offer builder filters
  these out before the agent sees the offer.

## 6. What to build ready for trade

Trade goods are produced on a calendar, not on demand. A caravan stays
25 to 33 days; the fort cannot start producing when it arrives. The
production pipeline starts the season before the caravan it serves.

### 6.1 The goods, by material

All values below are base values from the wiki's Maximizing value page,
before material and quality multipliers. The harness computes real values
live; this table is the plan's starting point, not the final ranking.

- Stone: mugs are the best stone trade good (base 30 for a stack of 3),
  then crafts (about 20), then statues (25). Stone is free and
  unlimited, so stone mugs and crafts are the default trade good for a
  young fort. Obsidian is the most valuable non-ore stone if the map
  has it.
- Metal: for weapon-grade metals, mechanisms are the best trade good
  (base 30 per bar, one hauling job per bar). For other metals, flasks
  and goblets (base 30 per bar). Never sell a bar when a finished good
  from the same bar is worth more, which is almost always.
- Glass: goblets again (base 30). Green glass is nearly free when the
  fort has sand and a magma furnace, so it scales well. Clear glass
  costs wood and cannot be sold to elves.
- Wood: minecarts, stepladders, and wheelbarrows have the highest base
  value (50), cups are 30 for a stack of 3, bolts are 25 per stack of
  25 and scale best with quality. Wood is low value per unit and the
  fort needs it for other things, so wood goods are a fallback, not a
  staple.
- Cloth: crafts (about 20), then paired goods (shoes, mittens, gloves,
  socks) which get the cloth and dye value added to each item of the
  pair.
- Pottery: statues (25), then crafts (about 20). Limited range, useful
  only if the fort has clay.
- Food: prepared meals. The wiki calls their value so high that some
  players consider trading them an exploit. The meal's value is the
  sum of its ingredients' values multiplied by the number of
  ingredients, so lavish meals made from several ingredients are worth
  far more than the ingredients alone. The kitchen accepts crops, meat,
  fish, gathered plants, and many liquids, so almost any surplus food
  becomes a trade good. Meals rot outside a food stockpile, so they are
  cooked close to the caravan season, not stockpiled for a year.

### 6.2 The pipeline

The pipeline is a composed task, in the harness's usual sense: the agent
names the goal ("have trade goods ready for the autumn caravan") and the
harness walks the steps with material checks at each one.

1. At the start of the season before a caravan, the harness computes
   the target: enough goods, by live value, to buy the top of the buy
   list plus a margin for merchant profit. The target is a number in
   the snapshot, not a feeling.
2. The harness picks the production route from what the fort can make:
   stone mugs and crafts first (no inputs but stone and a craftsdwarf),
   then metal mechanisms or goblets if bars are surplus, then glass
   goblets if sand is available, then prepared meals from surplus food.
   The choice is recorded with its reason.
3. Production jobs are queued through the normal job machinery, with
   the have/need check naming the material and the count. If a material
   runs short, the job fails fast and names the gathering step, per the
   standing material-awareness rule.
4. Finished goods go to a trade stockpile near the depot, not scattered
   across the fort. The stockpile is placed by the scored site
   selection work, adjacent to the depot, so hauling to the depot is
   short when the caravan arrives.
5. When the caravan is detected, the harness checks the goods are
   actually at the depot, and reports what is ready and what is still
   in transit. Goods still in transit when the caravan leaves are a
   planning failure, and the harness says so in the run log.

## 7. Animals

### 7.1 What to buy

Animals are bought for what they produce or for what they do, not as
pets. The buy list ranks them by the same survival and unblocking rules
as goods.

- Milk animals: any animal that can be milked gives a renewable food
  and a cheese industry. The wiki notes many animals can be milked
  that players would not expect, including pigs. Milk and cheese are
  also acceptable to elves, which matters for the spring caravan.
- Wool animals: sheep, llamas, and alpacas are the three shearable
  animals. Wool becomes yarn and cloth, which the fort burns through
  as clothing. A breeding pair is worth more than a single animal.
- Egg layers: poultry in nest boxes give eggs, a renewable food that
  needs no pasture. Eggs are refused by elves, so they are a dwarven
  and human caravan purchase.
- War animals: dogs are trainable for war and hunting, cheap, and
  breed fast. A war dog at the depot path and at the entrance is the
  cheapest early defense the fort can buy. The wiki lists dogs with
  pet value 30 and both hunting and war training.
- Pack animals: mules and other pack animals extend the fort's
  hauling, but the caravan's own pack animals are not the fort's. Buy
  pack animals only if the fort has a hauling shortage the harness can
  name.
- Exotic animals: elves sometimes bring tame exotic creatures, and
  humans may bring tamed grizzly bears. These are opportunistic
  purchases only, ranked low, and only when the fort has a pasture and
  a handler to spare. A giant tiger with nowhere to live is a problem,
  not an asset.

### 7.2 What the fort must have before buying animals

An animal purchase is refused by the harness unless the fort can keep
the animal. That means a pasture zone exists (or can be placed by the
scored site work), nest boxes exist for layers, and the fort has food
for grazers. Buying animals into a fort with no pasture is how animals
starve. The harness checks the pasture and nest box state before the
animal ever appears on the buy list.

### 7.3 What to sell

Surplus animals are sold, not butchered, when they are worth more alive
than dead and the fort has no use for them. The rules:

- Sell the surplus of a breeding line, never the breeding pair.
- Sell animals the fort cannot feed or house.
- Sell untrainable, non-producing animals that only eat.
- Never sell the fort's war dogs or its milk and wool breeding stock.
- Caged animals are traded in their cages; the cage material matters
  for elves (a wooden cage holding an acceptable animal is refused if
  the cage itself is offered, so the harness must check the cage
  material separately from the animal).

The wiki reports that animals bought from merchants do not always
become available for use (Bug 10162). The plan treats that as a known
risk: after a purchase, the harness verifies the animal is actually
owned and usable, and reports it if it is not, rather than assuming
the trade worked.

## 8. The harness's role at each step

### 8.1 Depot build

The depot is built by the generic build action once a depot task exists.
Its site is scored like any other building by the site selection work:
inside the fort, wagon accessible from the map edge with a 3-tile clear
path and a 3x4 parking space, at least 10 tiles from the edge, near the
trade stockpile, not blocking the main corridor, not exposed to the
open sky. The site is verified before the build is queued (terrain,
occupancy, reachability, wagon path), and a failure names a verified
alternative site. Exactly one depot is ever built.

### 8.2 Caravan detection and arrival

The event system must notice a caravan the way it notices an invasion:
an announcement fires when a caravan arrives, and the harness turns it
into an attention entry and a briefing. The briefing in `briefings.py`
already exists; what is missing is the detection itself, which has never
been exercised live because no caravan has ever reached a depot. The
detection must also notice the failure case: a caravan that bypasses
the site because the depot is inaccessible. That is an event too, and it
must say why (no depot, no wagon path, depot forbidden), not just that
the caravan left.

On arrival, the harness pauses on the event-pause rule (a caravan is a
decision point, not background noise), surfaces the caravan's race and
season, and starts the trade clock: the caravan leaves in 25 to 33
days, so the agent has a bounded window to move goods, meet the
liaison, and trade.

### 8.3 Liaison meeting and the agreement

When the liaison arrives, the harness surfaces the meeting to the agent
instead of auto-ending it (the standing rule from GOAL.md item 17).
The agent is told what the meeting is for: the agreement, and the noble
promotions if the fort qualifies. The harness records the agreement in
the journal and in the fortress history the moment it is made, because
the game clears it when the next liaison appears. The agreement's
requested items feed the next caravan's buy list directly: the caravan
loads up to four of each requested type first.

The meeting itself is driven by the existing dialog machinery
(`resolve_meeting.lua`, proven live). The agreement negotiation is a
separate depot interaction, not part of the liaison conversation script.
UNVERIFIED: the exact DFHack route for reading the current agreement
from the game and for entering the agreement negotiation. The plan
assumes the agreement is read from the game state the same way other
entity data is read, and flags the probe as a phase 2 task.

### 8.4 Offer construction and valuation

The harness builds the offer; the agent approves it. The steps:

1. The harness lists what is at the depot, with live values from
   `dfhack.items.getValue`, and what the caravan has, as far as the
   game exposes it.
2. It matches the depot goods against the buy list, highest rank
   first, and proposes an exchange that buys the top of the buy list
   with the lowest-value-density surplus goods.
3. It checks the elf filter (2.5) for elven caravans, the mandate
   filter (5.3), and the never-sell list (5.3) before the offer is
   shown.
4. It shows the agent the proposed trade with the merchant profit
   shown in the game's own terms: the profit color rule (green is
   accepted, red is rejected) and the margin. The agent picks from
   named options: accept the proposed trade, trade for a smaller set,
   gift instead, or walk away.
5. It records the trade in the journal: what was sold, what was
   bought, the profit given, and the sentiment effect. That record is
   what next year's caravan size is built on, and it is what the
   scoring system's "first trade" milestone reads.

### 8.5 The agent's decision surface

The agent never sees raw stock tables, raw caravan inventories, or raw
values. It sees, per tick: the next caravan (race, season, days away),
the top three buy-list items with a one-line why, the top trade goods
ready with a one-line why, and one suggested action for the most urgent
trading problem (build the depot, move goods, meet the liaison, trade
now). When a caravan is at the depot, the agent sees the proposed trade
as named options with a one-line why each. The harness owns valuation,
filtering, hauling, and bookkeeping. That is the standing cognitive
load rule, applied to trade.

## 9. Implementation phases, in order

Each phase is done only when its live-verification bar is met against
the real game. A phase is not done because the code is written.

### Phase 1: Depot build

- Depot task in the catalog, built on the generic build action, with
  the 3-material cost, the 5x5 footprint, and the 10-tile edge rule.
- Site scoring for the depot through the site selection work:
  wagon-accessible path, 3x4 parking space, inside, near the trade
  stockpile.
- Live bar: a depot is built on the scratch fort, read back from the
  game as a TradeDepot building, and a caravan path check confirms a
  wagon can reach it from the map edge. The main fort keeps its state;
  the scratch fort is the proving ground.

### Phase 2: Caravan detection and the agreement record

- Caravan arrival detection through the event system, including the
  bypass case with its reason.
- Liaison meeting surfaced to the agent (not auto-ended) once the
  depot exists, per the standing rule.
- Agreement read from the game and recorded in the journal and the
  fortress history before the caravan leaves.
- Live bar: a caravan arrives at the scratch fort's depot, the
  harness reports it with race and season, the liaison meeting is
  surfaced, and an agreement is recorded and read back from the
  journal after the caravan leaves. UNVERIFIED until then: the DFHack
  route for reading the agreement.

### Phase 3: Buy list and sell list

- Needs assessment from fresh collects: per-dwarf floors, have/need
  per production chain, survey-based "cannot produce locally" list,
  seasonal filtering by the next caravan's race.
- Surplus rules with per-category reserves, value-density ranking
  from live `dfhack.items.getValue` reads, elf and mandate filters.
- Live bar: on the main fort, the buy list names a real shortage the
  fort has (verified against the stocks), and the sell list names only
  genuine surplus above the reserves (verified by hand against the
  stockpiles). No item on either list is wrong by inspection.

### Phase 4: Trade-goods production pipeline

- Composed task "have trade goods ready for the next caravan", with
  the per-material route table from 6.1, material checks at each
  step, and the trade stockpile near the depot.
- Live bar: a full season of production on the scratch fort ends with
  the target value of goods in the trade stockpile, verified by the
  wealth read, and the pipeline names its own shortfall when a
  material runs out instead of silently producing less.

### Phase 5: Animals

- Animal observation fixed first (named animals in the units section,
  not just a count), then the pasture and nest box checks, then the
  animal buy and sell lists.
- Live bar: the harness names the fort's animals by id and kind, the
  buy list offers a milk or wool animal only when a pasture exists,
  and a purchased animal is verified owned and usable after the trade
  (or reported as not, per Bug 10162).

### Phase 6: Offer construction and the trade itself

- Offer builder: depot inventory with live values, buy-list matching,
  elf and mandate and never-sell filters, profit margin in the game's
  own terms, named options for the agent, journal record of the trade.
- Live bar: a real trade completes on the scratch fort with a caravan
  at the depot, the bought goods are in the fort's stockpiles
  afterwards, the sold goods are gone, the journal records the trade,
  and the scoring "first trade" milestone becomes detectable. This
  phase is blocked on the open question in section 10. It is the last
  phase for that reason.

### Phase 7: Sentiment and the long game

- Journal-based trade history per civilization, feeding next year's
  buy list and the caravan-size expectation. Gift decisions recorded
  with their cost. The harness reports, each season, what the last
  trade with each civilization was and what it means for the next one.
- Live bar: two consecutive caravans from the same civilization are
  recorded in the journal with profit and sentiment, and the second
  year's buy list reflects the first year's outcome. This needs two
  in-game years, so it is the last thing proven.

## 10. Open questions

### 10.1 How the trade screen itself is driven

This is the biggest open question in the whole plan, and the plan does
not pretend to know the answer. The trade screen is game-committing:
confirming a trade moves goods and money permanently. The harness's
standing rule is that a game-committing modal is named and returned as
a failure, never chosen for the player, and the trade screen was
verified live as refused by `dialogs.advance`. No keystroke route is
assumed. Mikey's no-UI rule forbids UI keystrokes for game actions, and
the liaison meeting was solved programmatically precisely to avoid
them.

The investigation, in order:

1. Read the DFHack 0.47.05-r8 open-source code for anything that
   touches the trade viewscreen (`tradegoods`, `viewscreen_tradegoods`
   if it exists in the DF structures) and for any plugin or Lua
   function that reads or writes trade state. The liaison meeting was
   solved by reading the dipscript structures; the trade screen may
   have an equivalent writable state.
2. Probe the live game on the scratch fort with a caravan at the
   depot: dump the trade screen's structure the way the meeting
   screen's structure was dumped (stack, fields, the two item lists,
   the profit value, the selected sets). Find whether the selection
   and the confirm action are writable fields or whether they only
   exist as UI state.
3. If a writable route exists, build it behind the same allowlist
   discipline as dialogs: the route is only used when a caravan is
   present, the depot is loaded, and the agent has approved a named
   offer. The confirm step is logged with the full offer, before and
   after.
4. If no writable route exists after a real investigation, report
   exactly what was tried and what blocked it, and the plan changes:
   the harness prepares everything up to the trade screen (depot,
   goods at the depot, trader at the depot, proposed offer) and hands
   the final confirm to a human. That is a limitation, not a failure,
   and it must be stated plainly, not worked around with keystrokes.

### 10.2 Other open questions

- Agreement reading: the exact DFHack route for reading the current
  trade agreement from the game is UNVERIFIED. Phase 2 probes it.
- Caravan inventory reading: whether the harness can read what a
  caravan is carrying before the trade screen opens is UNVERIFIED.
  The offer builder needs it; if it cannot be read, the offer is built
  from what the trade screen shows, which pushes the problem into
  10.1.
- Broker appointment: the noble route is verified for other positions;
  the broker position (id 12) specifically is UNVERIFIED live.
- Animal availability: the wiki reports bought animals do not always
  become usable (Bug 10162). The plan verifies each purchase. Whether
  the bug reproduces in 0.47.05-r8 is UNVERIFIED.
- Messenger missions: the wiki names sending a messenger to improve
  trade relations. Whether that is a harness route at all is
  UNVERIFIED and out of scope for this plan.

## 11. Refusals

The harness never does any of the following, whatever the agent asks:

- Seize goods from a caravan.
- Confirm a trade on its own. The agent approves a named offer; the
  harness executes only an approved offer.
- Dismiss or drive a game-committing screen without an approved,
  verified programmatic route.
- Sell an artifact, a mandated item, the last of a needed tool, or the
  last seeds of a grown crop.
- Offer wood or animal products to elves, or any item the elf filter
  refuses.
- Trade away the fort's breeding stock, war dogs, or milk and wool
  animals it still needs.
- Fake a shortage by forbidding stocks to trick a caravan into
  bringing emergency supplies.

## 12. Sources

Wiki pages, read from the local DF wiki index
(`~/workspace/df-wiki-export/dfq.py`) on 2026-11-27:

- Trading (8,659 words): calendar, flowchart, trade screen mechanics,
  merchant mood and haggling, trade agreements and liaisons, caravan
  types, emergency supplies, trade sentiment.
- Trade depot (2,884 words): construction, wagon accessibility,
  depot UI options, move-goods screen, trader request, bugs.
- Caravan (2,185 words): arrival, bypass, departure window, wagon and
  pack animal limits, destruction and relations, caravan delay.
- Trade agreement (575 words): price effects, loading order, duration,
  negotiation experience.
- Outpost liaison (975 words): arrival, agreement, promotions, human
  trade representatives.
- Maximizing value (2,665 words): trade goods by material, base values,
  prepared meals.
- Kitchen: prepared meals as trade goods.
- Meat industry: milk and wool animals.
- Dog: war and hunting training, pet value.

Harness sources, read from the repo on 2026-11-27:

- `docs/DIALOGS.md`: trade screen refusal (verified live), liaison
  meeting resolution via the dipscript jump, allowlist discipline.
- `docs/ADVANCED_MECHANICS.md`: trap placement notes (traps block
  wagons, relevant to the depot path).
- `GOAL.md` items 17 (trading direction), 83 and 99 (step 10 breadth
  systems), 104 (scoring, first-trade milestone).
- `hidden_files/coordinator-log.md`: the depot-build gap, the liaison
  design note (2026-11-27 ~08:50 PT), the caravan bypass on the
  scratch fort.
- `src/dfagent_harness/materials.py`: have/need machinery.
- `src/dfagent_harness/briefings.py`: caravan briefing text.
- `src/dfagent_harness/lua/wealth.lua`: live item valuation.
- `tests/fixtures/runtime-enums-0.47.05-r8.json`: `TradeDepot` in the
  building enum.
