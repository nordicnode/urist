# Fishing

Design document for how the Urist harness handles fishing. This is a plan, not
an implementation. Nothing here is built yet. Every game mechanic in this
document comes from the local Dwarf Fortress wiki index (see Sources at the
end) or from live verification against the real game. Anything not verified
against one of those two is marked UNVERIFIED.

## 1. Purpose

Fishing is the fort's early food bridge and its shell supply. It needs almost
nothing to start: no equipment, no seeds, no workshop chain. A fisherdwarf
walks to the water and pulls fish out with bare hands. But the same
simplicity makes it dangerous to leave unmanaged: fishers wander to the
nearest water whatever is waiting there, raw fish rot fast, cleaners cannot
keep up with catchers, and a pool fished empty stays empty. The harness must
turn fishing from a thing the agent has to remember into a thing the harness
drives: the harness knows where the fishable water is, keeps fishers inside
safe zones, keeps the cleaning chain ahead of the catch, and hands the agent
a small set of named choices. The agent picks; the harness does the
bookkeeping. This document covers the whole loop: water, zones, fishery,
cleaning, shells, underground fishing, and the refusals that keep dwarves
alive.

## 2. How fishing works in DF 0.47.05

All of this section is from the wiki pages listed in Sources. Where the wiki
itself flags a claim as unverified, this document says so.

### 2.1 The catch

Fishing is one of five food-producing industries, alongside farming, the meat
industry, the poultry industry, and the beekeeping industry. It is unique
among food gathering in that dwarves need no special equipment to catch fish;
they pull the creatures right out of the water with their bare hands. The
fish they catch are usually vermin fish (aquatic animals in general, not just
fish). Each fish caught yields one meal, once prepared. Note that the presence
of vermin fish on-screen does not signify there are fish there for fishing.

Fisherdwarf skill level is related to the speed at which the labor is
completed. Dwarves can fish through floor grates and floor bars. That one
fact is what makes safe indoor fishing possible; see 2.7.

A dwarf eats about 2 meals per season (Starting build page), so a fort of 7
dwarves needs about 14 meals per season from all food sources combined. One
cleaned fish is one meal. Fishing can cover a small fort's food on its own
while farms are being established, and stays useful after that as diet
variety and as the shell supply.

### 2.2 Where to fish

Dwarves fish from murky pools, brooks, rivers, lakes, and the ocean, and from
underground water in the caverns. What you catch depends on where the water
is:

- River fish can only be caught from the exact tiles the river originally
  occupied. The same holds for any other biome-specific fish: only tiles
  originally belonging to that biome yield that biome's fish.
- Any other body of water is treated as a murky pool for fishing purposes,
  so you get pond creatures like pond turtles.
- On an ocean embark, if fisherdwarves fish in the caverns from water
  connected to the side of the map the ocean is on, they catch ocean fish,
  including shell-bearing nautiluses. Fish are vermin, so they are not bound
  by continual existence; a fish that could be on any square can be fished
  from any other square, as long as the tile fished from is connected to a
  water source tile on the edge of the map. An indoor pond on an embark with
  a river should provide some river fish.

Brooks are the smallest type of river. Fisherdwarves can stand on the
surface of a brook to fish, and brooks can be crossed safely without
swimming, drowning, or even getting wet. Otherwise brooks function like any
other river. Rivers can freeze. Lakes and the ocean hold the largest fish
populations; rivers hold occasional carp runs; murky pools hold the smallest.

Murky pools are small bodies of stagnant water on the surface, common in any
non-desert, non-freezing biome. They contain a finite amount of water that
can evaporate completely during summer in hot climates and be refilled by
rain. Fish populations in murky pools run out very quickly and can be easily
fished to local extinction. Murky pool tiles cannot be created artificially.
Drinking stagnant water gives dwarves an unhappy thought, and using it to
wash wounds leads to infection, so a murky pool is a fishing spot, not a
water source.

### 2.3 Fishing zones and standing orders

Fishing zones are preferred areas to fish. Designate a zone on shore tiles
adjacent to water. A zone can only be set for fishing if there is some
fish-bearing water inside, or if it is not yet known whether there are any
fish there. If there are no fish in a particular region, you get the
announcement "There is nothing to catch in <biome>", and designating a zone
next to water in that region shows "0" for fishing.

Changing standing orders to zone-only fishing forces all fishing to be done
in the zone. Without zone-only fishing, fisherdwarves fish from any water by
default, which means they walk to the nearest water whatever is waiting
there. Zoning is highly recommended. The wiki's own example: an agile
fisherdwarf assigned to an out-of-the-way fishing spot, with a nearby
lockable escape tunnel, makes an excellent sentry.

Fishing zones are also an effective way to temporarily disable all fishing
without changing labor preferences, which matters when the fisheries cannot
keep up with the catch. Activate zone-only fishing, create a fishing zone,
then toggle the zone's active flag to control fishing. Dwarves that had
already decided to fish will still carry out a single fishing task.

### 2.4 Fish cleaning and the fishery

Freshly caught raw fish cannot be eaten; they must first be cleaned at a
fishery. The presence of raw fish automatically triggers "Prepare a raw fish"
to be queued up at the nearest fishery. So long as there are enough fish
cleaners and fisheries to keep up with the fisherdwarves, fish cleaning is
an automated process. Raw fish is a classification in the stocks menu for
fish that have yet to be cleaned, useful for seeing how backlogged the
fishing industry is.

The chain has a built-in bottleneck the harness must manage. Once a dwarf
catches a fish, it carries it to the nearest stockpile and returns to
fishing; even if the dwarf has fish cleaning enabled, it will almost never
clean its own catch, as fishing is higher priority, even if fish in the
stockpile are in danger of rotting. A rule of thumb is to have twice as many
fish cleaners as fishers, as fishers generally catch fish faster than
cleaners can process them. Mature fortresses have dedicated cooks, brewers,
and fish cleaners tasked to their food preparation areas. It is especially
important to have barrels and large pots in stock, as openly stored fish rot
very quickly.

Once a fish is cleaned, it is a "prepared" fish and can be immediately
eaten. Fish, both raw and prepared, can also be cooked into food at a
kitchen. Raw fish are known as "unprepared fish" in the stockpile settings.

The fishery itself (build shortcut b-o-f-y) takes 1 building material
(non-economic) and a Fishing or Fish cleaning labor to build. Its job
requirement is Fish cleaning.

Cooking rule that must not be missed: cooking unprepared shelled creatures
loses the shell, so disable cooking for animals that have shells (turtles,
mussels, oysters) until after the fish cleaner is done with them.

### 2.5 Shells and the craft economy

Animals with shells (like pond turtles) leave shells behind when processed
at a fishery. Shells are worked by a dwarf with the bone carver skill, for
many of the same purposes as bone: crafts, decorations, and cheap,
lightweight, very low-defense armor (limited to leggings, gauntlets, and
helms only; unlike bones, shells cannot be used to produce bolts). Every
item type can be decorated with shells. A halfway decent fishing industry in
a location with mussels or oysters keeps a craftsdwarf swimming in shells,
and setting up a few craftsdwarf workshops next to a dedicated shell
stockpile near the fishery, with repeating "decorate with shell" orders,
trains bone carving to legendary levels while delighting dwarves and
guaranteeing merchants pay top dollar.

Shells cannot easily be acquired via trading: any non-caged turtles,
crustaceans, or shellfish purchased from traders have already been
processed, and their shells removed. Fortresses with no naturally occurring
above-ground fishing sites struggle to acquire shells. That matters because
a shell-preferring moody dwarf can demand shells for an artifact, and only
dwarves with a preference for shells demand them. Save shells for strange
moods.

Two warnings from the wiki. First, fishing eventually causes extinction of
shell-bearing fish. The process can take years or even decades depending on
how aggressively the fort fishes, but it always happens eventually. If the
economy relies on trading shells and shell crafts, or shells are wanted for
a strange mood, plan ahead for that eventuality. Second, pearls are an
unimplemented mussel and oyster product: telling dwarves to decorate with
pearl at a craftsdwarf's workshop does nothing, as there are no pearls in
the game.

Elven merchants are greatly offended if offered items crafted from shells,
since obtaining shells implies killing the creature that created them. Shell
goods never go to the elves.

### 2.6 Live capture and dissection

Fisheries can also queue a "capture a live fish" task. To fulfill it, a
fisherdwarf grabs an animal trap and sets it in the river, retrieving it
when it catches something. If no animal trap is available, the task occupies
the fishery forever, preventing its other functions. Captured live fish can
serve as an attraction in an aquarium, or be made into extracts with the
"dissect a live fish" task at the fishery, using the fish dissection skill.
Dissected moghoppers yield five units of mog juice, each worth 50 dwarf
bucks, making it lucrative for something that would otherwise have served
little more than a single meal.

### 2.7 Large fish and fish hunting

Larger, non-vermin fish cannot be caught with bare hands. Large fish like
carp and sharks are individual creatures, appearing as such on the unit
list, and must be butchered, producing dozens or, in the case of whales,
hundreds of meat products. Fish hunting is mostly an oceanic activity;
rivers only ever have occasional carp runs. Advanced fortresses near the
ocean, a lake, or large well-occupied sections of river may use a
fishing-adapted drowning chamber: a large room lined with traps into which
water is allowed to filter through via water pump pressure. Building and
operating one is a complex engineering project and is out of scope for this
document. The harness does not hunt large fish; it fishes vermin fish.

### 2.8 Freezing and seasons

Rivers can freeze. Murky pools thaw and freeze instantly. Any dwarf standing
on the ice will plunge into the water when it thaws, with a risk of drowning
if it cannot find a nearby ramp quickly enough. Unless the dwarf has adequate
or better swimming skills, the fall stuns it, increasing the chance of
death. If a dwarf is in a murky pool when winter comes and the water
freezes, the dwarf is encased in the ice and immediately dies. Mitigations
from the wiki: traffic designations (mark the ice restricted, put a high
traffic ring around the pool perimeter), or wall the pool off, or floor over
it if it is not needed for fishing.

Frozen water cannot be fished. A fort in a freezing climate loses its
surface fishing every winter. That is a planning fact, not a failure: the
harness must know the water is frozen and stop sending fishers, not keep
assigning a task that cannot complete.

### 2.9 Overfishing

There is a possibility of overfishing an area. Overfishing can exhaust the
fish population of a pond, river, or ocean both temporarily and permanently.
If a dwarf cannot find fish in a specific area, you get the message "there
is nothing to catch in the [direction] [biome]" and the area is no longer
used for fishing. When the season changes, all areas become available for
fishing once again, though eventually they remain permanently empty and
simply give the above message on the first fishing attempt of every season.
Murky pool populations run out very quickly. Non-flowing water stocks are
renewable now, unlike in the past (Bug 2780), but a fisherdwarf can still
fish a small pool dry.

### 2.10 Dangers

The largest challenge in the fishing industry is ensuring the safety of the
fisherdwarves. When working outdoors, they are susceptible to ambushers.
The specific water dangers from the wiki:

- Carp. King of beasts: extremely aggressive for a fish, teeth that inflict
  three times the damage of an unarmed dwarf. They drag unsuspecting
  fisherdwarves underwater, where the dwarf drowns, is mauled, or both. The
  cancellation message "Dwarf cancels task: Dangerous terrain" often heralds
  another dwarf drowning after being yanked in by fish.
- Giant capybaras. They attack when attacked and are very dangerous around
  unarmed dwarves; they have been known to drag their quarry into the water
  and drown them.
- Crocodile-infested rivers. Named in the wiki as the reason to use
  zone-only fishing: keep fishers out of the dangerous river entirely.
- Freezing and thawing water; see 2.8.
- Rain and the dead. Fisherdwarves often get negative thoughts from being
  caught in the rain outside, or being exposed to dead bodies lying
  underwater. Indoor fishing areas prevent both.

The safe answer, from the wiki: bring the water inside. Create an internal
fishery by channeling down to the river, just like with a well, and building
floor grates. Dwarves have no trouble fishing through them. Doing so removes
the danger of being far from home in case of a siege or ambush and keeps
fisherdwarves happily inside at all times. Hauling is the other inefficiency
solved the same way: bringing the river closer to home can double or triple
production, as dwarves can toss fish right into the nearest food stockpile.

## 3. What the harness knows today

Verified against the repo on 2026-11-27. The fishing pieces that exist:

- The Fish job type exists in the live-verified runtime enums (job_types),
  and the attention layer already labels it "fishing". The Fishing labor and
  the Fish cleaner and Fish dissector labors exist in the labor and skill
  enums, and the Fishery Worker profession exists.
- The fishing activity-zone kind exists: ZONE_KINDS in actions.py includes
  "fishing", and create_zone is verified live (it builds a civzone
  programmatically, sets the kind flag, and calls
  dfhack.job.checkBuildingsNow). A fishing zone can be designated today.
- The Fishery workshop type exists in the live-verified runtime enums
  (workshop_types). No fishery build has been verified live yet; the generic
  build action takes a workshop kind, so the route is expected to work, but
  it is UNVERIFIED until a fishery is actually built and a "Prepare a raw
  fish" job completes in it.
- The daemon has a composed-task pattern to follow: task:farm (daemon.py)
  assesses a need, picks a site, runs the action, and reports the result.
  There is no task:fish.

What does not exist:

- No fishing task, no fishery placement logic, no cleaner-to-fisher ratio
  enforcement, no fish backlog guard, no shell handling. No FISHING_SITE in
  sites.py. No fish handling in materials.py: the have/need machinery does
  not count raw or prepared fish as food, so the planner cannot see a fish
  shortage or a fish surplus today.
- The harness can see water but cannot classify it. The slice has a water
  layer, the column read reports water counts, and the survey reports
  water_block_indices, but nothing in the harness says "this water is a
  river", "this water is a murky pool", or "this water is a cavern lake".
  Frozen-water detection does not exist either. Both are UNVERIFIED routes
  that phase 1 must establish.
- The zone-only standing order toggle is not wired to the harness. The zone
  itself is verified; the standing order that confines all fishing to zones
  is UNVERIFIED as a programmatic route.
- The main fort was embarked with a brook at minimum: the M2 embark profile
  requires water (Min River Brook). Whether that brook is fish-bearing,
  where it runs, and whether it freezes were not read live at the time of
  writing (the daemon was busy with review work), so the main fort's
  fishable water is UNVERIFIED and phase 1 reads it first.

## 4. Where to fish: the water survey

Before any fisher is sent anywhere, the harness must be able to answer four
questions about every water body on the map. Today it can answer none of
them, so phase 1 builds this read.

1. What kind of water is it? River or brook (original river tiles, yields
   river fish), lake or ocean, murky pool (pond creatures only), or cavern
   water (cave fish). The game's own answer is the fishing zone probe: a
   zone next to water shows a fishing count, or "0" when there is nothing to
   catch. The survey must use the game's check, not guess from the tile
   glyph. How the harness reads the zone's fishing count programmatically
   is UNVERIFIED.
2. Is it fish-bearing right now? Populations deplete within a season and
   recover at season change until permanently exhausted. The signal is the
   game's "There is nothing to catch in <biome>" announcement and the zone
   count. A water body that reports nothing to catch is closed until the
   next season, and the harness must not keep sending fishers to it.
3. Is it frozen? A frozen river or pool is not fishable, and a thawing pool
   is a drowning risk. How frozen water reads in the harness's column and
   slice data is UNVERIFIED; phase 1 must establish it live (read a known
   frozen tile and record what the harness sees).
4. Is it safe? Hostiles in or near the water (carp, capybaras, crocodiles,
   ambushers, any hostile unit within the threat radius) and exposure (open
   sky, far from the fort, no escape route). This uses the same threat and
   cover reads as the scored site selection work: hostile positions from
   /v1/units, cover from column reads, reachability from canWalkBetween.

The survey result is a small table, one row per water body: kind, location,
fish-bearing now, frozen, safe, and the recommended zone rectangle. The
agent never sees the raw table; it sees the top options with a one-line why
each. See 8.2.

## 5. Fishery placement and the cleaning chain

The fishery goes where the fish are and where the food is, in that order.
Placement rules, from the wiki and from the harness's own placement
discipline:

- Near the fishing zone, so the carry from water to fishery is short. Fish
  rot quickly when openly stored, so the distance from the catch to the
  fishery and from the fishery to the food stockpile is the whole economy
  of the chain. A fishery a fort's width away from the water is a rotting
  pile, not a food industry.
- Inside, roofed, near the food stockpile and the kitchen. Prepared fish go
  to the food stockpile and then to the kitchen; the fishery belongs with
  the food preparation area, not out by the water.
- The scored site selection work applies: the fishery is a workshop kind in
  the scoring table, with adjacency to the fishing zone and the food
  stockpile as its scored factors, and threat and cover as hard gates.
  UNVERIFIED until the scoring table exists.

The chain, with the ratios the harness enforces:

- 2 fish cleaners per fisher. Fishers catch faster than cleaners clean, and
  a fisher almost never cleans its own catch. The harness counts enabled
  fishers and enabled cleaners from the labor data and refuses to add a
  fisher when the ratio would break, naming the missing cleaners.
- Barrels and large pots in stock before fishing scales up. Openly stored
  fish rot very quickly. The harness checks barrel and pot counts through
  the have/need machinery and refuses to expand fishing when there is
  nowhere safe to put the catch.
- Backlog guard. Raw fish in stocks is the backlog signal. When raw fish
  exceeds what the cleaners can clear, the harness stops fishing first
  (deactivate the fishing zone; the zone toggle is the off switch) and
  says why, instead of adding more fishers to a rotting pile.
- Shelled creatures are never cooked before cleaning. The kitchen's cook
  orders must exclude turtles, mussels, and oysters until the fish cleaner
  is done with them, or the shells are lost. How the harness expresses that
  exclusion in a cook order is UNVERIFIED.

Shell handling, once the chain runs:

- A dedicated shell stockpile near the fishery, and craftsdwarf workshops
  next to it with repeating "decorate with shell" orders, trains bone
  carving and produces trade goods. Shells are a low-value material where
  quantity wins.
- A shell reserve is kept for strange moods and never sold or decorated
  away. Shells cannot be bought back: traders sell shellfish already
  processed, shells removed.
- Shell goods never go to the elves.

## 6. Food math: fishing vs farming vs trading

The three food sources are not interchangeable, and the harness must know
which one the fort needs.

- Fishing: 1 cleaned fish is 1 meal. A dwarf eats about 2 meals per season.
  7 dwarves need about 14 meals per season. Fishing needs no seeds, no
  soil, no season, and almost no setup, which is why it is the early-game
  bridge: it feeds the fort while the first farm plots are being dug and
  planted. Its limits are the water it fishes (finite pools, seasonal
  depletion, permanent extinction), the cleaning bottleneck, and the danger
  of the water. It also adds diet variety and supplies shells.
- Farming: the reliable staple once established. Farm plots produce per
  season from seeds, with crop-per-season rules and soil requirements (see
  docs/FARMING.md). Farming scales with plots and planters; fishing does
  not scale past the water's population. When the farm covers the fort's
  meals with margin, fishing drops to a supplement: variety and shells,
  not the staple.
- Trading: caravans sell processed fish, already prepared, never needing
  preparation and never carrying a shell. Buying fish is often a good idea
  if the fort has no strong fishing industry, and it adds diet variety.
  Trading cannot be the staple either: one caravan a year per race, and
  only if the fort has goods worth trading. See docs/TRADING.md.

The harness's decision rule, in order: if the fort's food (all sources,
fresh counts) covers the season's meals with margin, fishing is a
supplement and the harness says so; if food is short and fishable water
exists, fishing is the bridge and the harness starts it; if food is short
and no fishable water exists, the harness says so and points at farming or
the next caravan instead of pretending fishing will help. The numbers come
from fresh collects, never the cached status.

## 7. When fishing is NOT worth it

The harness refuses to start or continue fishing, with a reason, when any
of these hold:

- No fish-bearing water. The zone probe shows "0", or the announcement
  "There is nothing to catch in <biome>" has fired for every water body.
  Fishing from water with no fish is dwarves standing in a pond.
- Frozen water. Rivers and pools freeze in cold climates. A frozen water
  body is closed until thaw, and a pool about to freeze is a death trap,
  not a fishing spot.
- The cleaning chain cannot keep up. Raw fish backlog growing, no free
  fishery, no available cleaners, no barrels or pots. Adding fishers makes
  the rot worse.
- The water is unsafe and cannot be made safe. Hostiles in or near the
  water, no zone can exclude them, no indoor route exists. An indoor
  fishery through floor grates is the fix when one can be built; when it
  cannot, the water is closed.
- Better food elsewhere. The farm covers meals with margin and the fort
  needs shells only: fish for shells at a low rate, or not at all, and say
  so. Fishing as the staple when the farm already covers food wastes
  labor that could be mining, building, or crafting.
- The pool is fished out. Seasonal depletion is temporary (populations
  return at season change); permanent extinction is not. The harness
  tracks the "nothing to catch" signal per water body and does not re-try
  a permanently empty body every season.

## 8. Underground fishing

The caverns hold ever-regenerating resources: underground forests, animals
to hunt, and fish. Cave fish live in underground caverns (wet), depth 1-2,
and are fishable. Underground fishing is the late-game form of the industry:
once a cavern layer is breached and secured, its pools are fishable water
that never freezes and never sees the sky, which removes the two largest
surface risks (freezing and ambush) at the cost of the cavern's own dangers.

Rules for the underground form:

- The water must be a real cavern pool, reached through a secured route.
  The harness verifies the route the same way it verifies any site:
  reachability, hostiles, cover. A cavern pool next to a forgotten beast
  is not a fishing spot.
- The indoor fishery applies underground too: channel to the cavern water,
  floor grates, fish through them, fishers never leave the fort. How the
  harness builds and verifies that route live is UNVERIFIED; phase 6
  proves it.
- Bug 1854: if a fishing zone is designated in an underground pool,
  fishers never give up fishing there even when there are no fish to
  catch. The harness must detect zero catch over a bounded window and
  deactivate the zone itself, instead of letting fishers stand in a dry
  pool forever. The exact catch-rate signal (fish caught per in-game day
  from the job and stocks data) is UNVERIFIED.
- On an ocean embark, cavern fishing from water connected to the ocean side
  yields ocean fish, including shell-bearing nautiluses. That is a real
  shell source for a fort with no surface shellfish, and the harness should
  say so when it applies.

## 9. The harness's role at each step

### 9.1 Water survey

The harness reads the water bodies, classifies them, checks fish-bearing
status, frozen state, and safety, and keeps the table current. The agent
never does this. The model cannot be asked "is there fishable water?" and
expected to work it out from tile glyphs.

### 9.2 Zone placement

The harness proposes the zone rectangle (shore tiles adjacent to the water,
inside the scored placement rules) and creates it through the verified
create_zone action. The zone-only standing order, once its programmatic
route is proven, confines all fishing to the zone. Until that route is
proven, the harness says plainly that fishers may still wander to other
water, and the zone is a preference, not a fence. It does not claim a
confinement it cannot enforce.

### 9.3 Fishery and chain

The harness builds the fishery at a scored site, enables the labors at the
2:1 cleaner-to-fisher ratio, checks barrels and pots, and watches the raw
fish backlog. When the backlog grows, it stops fishing before it adds
fishers. When shells appear, it routes them to the shell stockpile and the
craftsdwarf workshops, holding the mood reserve back.

### 9.4 The agent's decision surface

The agent sees, per tick, the top 3 fishing options with a one-line why
each, for example "brook 12 tiles from the fort, inside the walls, 2
cleaners free" or "cavern pool, never freezes, 1 cleaner short". Blocked
candidates come with reasons: "murky pool fished out this season", "river
frozen until spring", "carp in the river". The snapshot carries the top
option, raw fish count, prepared fish count, and the cleaner backlog. Full
detail sits behind a query route, never in the snapshot. The model never
sees raw columns, zone rectangles, or ratios; it picks a named option.

### 9.5 The model never does

The model never picks water by coordinates, never enables labors by name
without the harness's ratio check, never orders a fishery build at a
coordinate it guessed, and never decides a water body is safe from a tile
glyph. All of that is the harness's job.

## 10. Implementation phases

Each phase lands only when its live-verification bar is met. Order matters:
no phase starts until the one before it is proven.

### Phase 1: Water survey

Classify every water body on the map (river/brook, lake/ocean, murky pool,
cavern water), read frozen state, and probe fish-bearing status with the
game's own zone check. Live bar: on the main fort, read the real water,
classify the brook the fort was embarked with, and confirm the zone probe
reports fish-bearing or "0" with the reason. On the scratch fort, do the
same for its water. Frozen-state detection is proven by reading a known
frozen tile in winter, or by reading the same water in two seasons and
recording the difference. If the zone's fishing count cannot be read
programmatically, that is a finding, not a workaround: report exactly what
was tried and what blocked it.

### Phase 2: Fishing zone and standing orders

Create fishing zones through the verified create_zone action at scored
sites, and prove the zone-only standing order route (UNVERIFIED) or report
it as blocked with the evidence. Live bar: a zone exists next to fishable
water, a fisher works it, and no fisher works outside the zone while
zone-only is set; or, if the standing order route is blocked, the doc and
the harness state the limit plainly.

### Phase 3: Fishery build and cleaning chain

Build a fishery at a scored site, enable fishers and cleaners at the 2:1
ratio, check barrels and pots, and run the chain. Live bar: a raw fish is
caught, "Prepare a raw fish" completes in the fishery, prepared fish
appears in stocks, and no fish rots while the backlog guard is armed.
Deliberately overload the chain once and confirm the guard stops fishing
before fish rot.

### Phase 4: task:fish

A composed task mirroring task:farm: assess food need from fresh counts,
pick the water, zone, fishery, and labors, run, and report catch rate,
backlog, and the stop condition. Live bar: run on the scratch fort, fish
are caught and cleaned, food count rises by the catch, and the task stops
itself when the water reports nothing to catch or the backlog guard trips.

### Phase 5: Shell economy

Shell stockpile near the fishery, craftsdwarf workshops with repeating
"decorate with shell" orders, the mood reserve held back, shell goods
excluded from elf trades. Live bar: shells appear in stocks, a decorate
job completes, the reserve count is held, and no shell good is offered to
elves.

### Phase 6: Underground fishing

Cavern pool zone, indoor fishery through floor grates, Bug 1854 guard.
Live bar: fish caught from a cavern pool with fishers safe indoors, and a
dry underground pool deactivates its own zone after the bounded zero-catch
window instead of trapping fishers.

### Phase 7: Live capture and dissection (late, optional)

Capture a live fish and dissect it, only with a free animal trap available.
Live bar: the capture completes, the fish is dissected, and the extract
appears in stocks. If no trap is available, the task is refused, never
queued, so the fishery is never blocked.

## 11. Refusals

- Never send fishers to water with hostiles in or near it where the
  harness can see them (carp, capybaras, crocodiles, ambushers). A
  fishing spot next to a predator is a death, not a meal.
- Never fish frozen water, and never fish a pool about to freeze. Frozen
  is closed until thaw.
- Never fish a water body the game says has nothing to catch, and never
  re-try a permanently empty body every season.
- Never add fishers when the cleaning chain cannot keep up, when there are
  no barrels or pots, or when raw fish is already rotting. Stop fishing
  first.
- Never cook shelled creatures before cleaning. The shell is lost.
- Never queue "capture a live fish" without a free animal trap. The task
  occupies the fishery forever.
- Never leave fishers in an underground pool that Bug 1854 has trapped
  them in. Zero catch over the bounded window deactivates the zone.
- Never offer shell goods to elves. Never sell or decorate away the shell
  mood reserve.
- Never claim a water body is fish-bearing, safe, or frozen without the
  game's own check. The harness reads the game; it does not guess from
  glyphs.

## 12. Sources

Local Dwarf Fortress wiki index (~/workspace/df-wiki-export/dfq.py),
pages read for this document:

- Fishing industry (fishing-industry): the catch, zones, cleaning, shells,
  trading, dissection, fish hunting, industry management, Bug 1854.
- Fishery (fishery): build shortcut b-o-f-y, 1 non-economic building
  material, Fishing or Fish cleaning labor, Fish cleaning job requirement.
- Fishery worker (fishery-worker): Fish cleaner, Fish dissector,
  Fisherdwarf skills.
- Fisherdwarf (fisherdwarf): skill is speed, fishes through floor grates
  and bars, zone-only standing orders, overfishing and the "nothing to
  catch" message, biome-origin rule for river fish.
- Shell (shell): acquiring shells, uses, bone carver, shell extinction
  bug, elven offense, mood reserve.
- Brook (brook): dwarves stand on the surface to fish; otherwise like a
  river.
- River (river): can freeze; brooks crossable safely; dwarves will not
  swim across rivers; unskilled dwarves drown in the current.
- Murky pool (murky-pool): finite water, quick extinction, instant
  freeze/thaw, ice plunge and encasement deaths, traffic mitigations.
- Cavern (cavern): ever-regenerating fish in the caverns.
- Cave fish (cave-fish): underground caverns (wet), depth 1-2, fishable.
- Starting build (starting-build): a dwarf eats about 2 meals per season.
- King of beasts (king-of-beasts): carp drag fisherdwarves underwater.
- Dwarf cancels task: Dangerous terrain: carp and drowning.
- Captured live fish (captured-live-fish): capture needs an animal trap.

Harness state verified against the repo on 2026-11-27: runtime enums
(job_types "Fish", workshop_types "Fishery", FISHERY_WORKER profession),
actions.py ZONE_KINDS ("fishing") and create_zone, daemon.py task:farm as
the composed-task pattern, sites.py (no FISHING_SITE), materials.py (no fish
handling), spatial.py and survey.py water reads (no water-body
classification), embark.py M2 profile (water: Min River Brook). Companion
design docs: docs/FARMING.md (the staple food source), docs/TRADING.md
(processed fish from caravans), docs/SITE_SELECTION.md (scored placement;
queued work at the time of writing, not yet existing).

## 13. Model presentation

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

### 13.1 Snapshot: the Fishing section

The per-tick snapshot gains a short Fishing section, built from
the fresh collect, in plain words. Three lines, in this shape:

```
Fishing: 1 fisher (Ral). Fishery: none. Zone: none.
Catch: 0 raw fish. Cleaning: 0 waiting.
```

What is in it, and what is not:

- **Line 1, fishers and buildings.** How many citizens have the
  Fishing labor enabled (named when there are 3 or fewer),
  whether a fishery workshop exists, and whether a fishing zone
  is designated. The Fish job type and the Fishing, Fish
  cleaner, and Fish dissector labors all exist in the live
  runtime enums, and the fishing zone kind exists with
  create_zone verified live, so the line names real state. The
  common case on a fort with no fishing yet is the example
  above: three short absences, not silence. A missing fishery
  is an exception, not a blank: no fishery build has been
  verified live yet (UNVERIFIED), so the line says "Fishery:
  none" until one is built and a "Prepare a raw fish" job
  completes in it.
- **Line 2, catch and cleaning.** How many raw fish are in stock
  and how many are waiting to be cleaned. When the have/need
  machinery cannot count fish as food (it does not today, §3),
  the line says the counts from stocks and names the gap:
  "Fish not counted as food by have/need (gap)." A gap stated
  is better than a count that pretends to know.
- **Line 3, only when something is wrong.** A third line appears
  only as an exception: a fish backlog with no cleaner, a
  fishing zone with no water, water frozen at the zone. When
  nothing is wrong, there is no third line. A quiet fort costs
  two lines.
- **Diffs, not repeats.** When nothing in the section changed
  since the last tick, the assembler prints the short form
  ("fishing: unchanged"), the same way the Buildings section
  already does. The section costs its full price only on ticks
  when fishing state actually moves.

**Token cost.** At 7 dwarves, the section as written above is
91 characters: about 30 tokens by the accountant's
3-chars-per-token rate, 22 on the wire. At 50 dwarves, with
more fishers and more zones, it is about 290 characters: about
96 tokens by the accountant, 72 on the wire. The cost grows by
about 30 tokens from 7 dwarves to 50, because the section is
capped: 3 fisher names maximum, 1 zone clause, 1 catch clause.
It does not grow with population, with the number of fish in
stock, or with the amount of water on the map. If a future
change makes it grow with any of those, the change is refused
until the section is capped again.

### 13.2 Query route: GET /v1/fishing (UNVERIFIED)

GET /v1/fishing returns the full detail, read from the fresh
collect, not from a cache. This route does not exist yet; it is
part of the implementation phases in §10, and the snapshot
section above is written against it as a design target, not
against a live route.

- Water: the water survey from §4, each water body with its
  kind (river, brook, murky pool, cavern lake), whether it is
  fish-bearing, whether it is frozen, and where the fishing
  zones are. The harness can see water today but cannot
  classify it (§3); classification is a phase 1 route, and
  until it lands the route lists water bodies as unclassified,
  never guessed.
- Fishers: each citizen with the Fishing labor, their fishing
  skill, and their current job.
- Fishery: the workshop state, the cleaning queue, and the
  cleaner-to-fisher ratio from §5.
- Catch: raw fish in stock by kind, prepared fish, shells, and
  the backlog guard state from §5.

The snapshot carries the summary and the ids; the route carries
the detail. The agent asks the route when it needs to choose
where to fish or whether fishing is worth it (§6, §7), never as
a matter of routine. Until the route exists, the same detail is
behind GET /v1/units (fishers are citizens), GET /v1/buildings
(the fishery is a building), and GET /v1/stocks (fish are
stocks), which do exist today.

### 13.3 Briefing: what arrives just in time

Fishing has no standing briefing. Two events carry one, both
from the existing briefing system (briefings.py), each a few
hundred tokens at most, each fired once when the event starts:

- **Food short, water near.** Trigger: food below the floor and
  fishable water in range. Cost: about 65 tokens by the
  accountant (UNVERIFIED: the briefing text has not been
  measured against the live briefing system). It covers that
  food is short and that water is near. It leaves the
  worth-it judgement to §6 and §7.
- **Fish backlog.** Trigger: raw fish waiting with no cleaner
  assigned. Cost: about 50 tokens. It covers how many fish are
  waiting and that they rot uncleaned. It leaves the ratio fix
  to §5.

No other fishing event briefs the model. A fishery being built,
a zone being designated, or a catch coming in are attention
entries and opportunities entries, not briefings. A briefing is
for something the model needs to understand right now, not for
something it can read in the snapshot.

### 13.4 Opportunities: at most 3, facts only

The opportunities section carries at most 3 fishing entries,
each one line: facts plus a query route, never a suggestion, never
a pause. Ignoring one costs nothing. Examples of what qualifies:

- "Fishing: brook in range, 0 fishers. Query /v1/fishing for
  the water survey."
- "Raw fish 12 waiting, 0 cleaners. Query /v1/fishing for the
  cleaning queue."
- "Fishery: none built. Query /v1/fishing for the workshop."

An opportunities entry fires only when the fact is actionable
and the snapshot alone does not already say it. A fisher
already fishing is not an opportunity; it is the snapshot doing
its job. The entry never names the action to take and never
carries a cost estimate. The model decides.

### 13.5 What the system deliberately does NOT push, and why

- **Every water tile.** The snapshot names the fishing zones
  and their state; the full water map is behind GET /v1/fishing
  and the survey. A list of water tiles every tick is a dump,
  and the model cannot act on the 40th water tile anyway.
- **Water classification before the route exists.** The harness
  can see water but cannot classify it (§3). The snapshot says
  "water unclassified" until phase 1 establishes the route.
  Pushing a classification the harness cannot support would be
  a guess.
- **Per-fish records.** Which fish was caught, by whom, and
  when, is journal data. The snapshot says how many raw fish
  are in stock. The record is there when the model asks why a
  fisher is idle.
- **Fishing as a suggestion.** The snapshot never says "fish the
  brook". Whether fishing is worth it is §6 and §7, and the
  model asks for the fishing detail when it decides. The
  presentation gives the model what it needs to decide, not a
  script to follow (HARNESS_ROLE.md).
- **Fish as food before have/need counts it.** The have/need
  machinery does not count raw or prepared fish as food today
  (§3). Until it does, the snapshot never claims fish cover
  the food floor. The gap is stated, not papered over.
