# Gemcutting

Design record for the gem industry in the Urist harness. This is
the plan. Implementation follows it phase by phase, each phase
verified live against the real game before it counts as done.
Anything not verified against the 0.47.05 game, its raws, or the
harness code is marked UNVERIFIED.

Related docs: docs/STONEWORKING.md (stone cutting into cabochons
as a stone sink, the jeweler as a stone consumer, mechanisms and
the encrust hazard), docs/METALWORKING.md (the presentation
precedent this doc follows for opportunities), docs/TRADING.md
(trade values and the caravan pipeline; gem goods are not ranked
there yet), docs/STOCKPILES.md (the Gems stockpile, bins, feeder
piles), docs/LABOR.md (the labor plan), docs/ANIMAL_HUSBANDRY.md
(gizzard stones from butchering), docs/EVENTS.md (strange moods
and caravan arrivals). This doc owns the jeweler's workshop and
every job in it. STONEWORKING.md section 3.4 and phase 7 name the
jeweler as a stone sink; that is a consumer requirement on this
doc, not a second owner. The glass industry (raw glass as a gem
training input) has no doc yet; this doc states the boundary and
does not design glassmaking.

## A note on sources, read first

The local wiki export (`~/workspace/df-wiki-export/dfq.py`) holds
the CURRENT wiki, not the 0.47.05 wiki. Its pages describe the
v50 game. Several v50 facts changed after 0.47.05: the Gem
industry page itself notes that in v50.05 large gem cutting is
turned off for normal gems, which is a v50 change whose 0.47.05
status has to be checked live, not assumed. The local export was
used only to find pages; nothing in this doc rests on a v50 page
alone.

Every game claim in this doc rests on one of these instead:

- The 0.47.05 raws in the install itself
  (`third_party/df_47_05/raw/objects/inorganic_stone_gem.txt`),
  read 2026-11-27: 127 gem types, their material values, their
  cluster sizes, and where the rare single gems come from.
- The live runtime-enum fixture
  (`tests/fixtures/runtime-enums-0.47.05-r8.json`), enumerated
  live from DF 0.47.05 + DFHack 0.47.05-r8 on 2026-11-25: the
  job types, item types, labors, skills, workshop type, and
  building types the game actually has.
- The harness code, read 2026-11-27 (section 4).

Where a claim comes from the v50 wiki only, or from memory, it is
marked UNVERIFIED and the phase that proves it is named.

## 1. Why gemcutting decides whether the fort gets rich

Gems are the highest value per unit of work the fort can produce
without fuel, without bars, and without a farm. Mining produces
them for free: every gem tile mined yields a gem, and a fort that
digs at all will have rough gems sitting in a pile within the
first year. A rough gem is already worth something. A cut gem is
worth more than three times the rough gem. A decoration set by a
skilled gem setter multiplies it again. No other industry turns
a byproduct of digging into trade wealth that fast, with no
inputs but a workshop and two labors.

Three failure modes dominate, and the system in this doc exists
to prevent all three:

1. **Gems cut blind.** A cutter given any rough gem will cut the
   fort's only diamond before its pile of tigereye. A setter
   given any cut gem will set a diamond into a wooden table and
   a tigereye into a masterwork statue. Gem value lives in
   choosing which gem goes where, and a harness that cannot
   choose is worse than no harness: it spends the best material
   on the worst target.
2. **Gems invisible.** The harness today lumps rough gems into
   the stone count. The snapshot says "stone 142" and the agent
   cannot tell whether that includes eleven rough gems or none.
   An industry the snapshot cannot see is an industry the agent
   cannot run.
3. **The mood eats the stock.** A dwarf in a strange mood can
   demand a rough gem. A fort that cut every gem it owned has
   nothing to give the mood, and a failed mood is a dead or
   insane dwarf. The gem stock is also the mood reserve, and the
   harness must keep the two from eating each other.

The harness owns this system. The agent never reasons about job
type numbers, item type numbers, or material indexes. It gets
counts, exceptions, and named options with a one-line why. See
section 12.

## 2. How gems work in Dwarf Fortress 0.47.05

### 2.1 Where rough gems come from

Rough gems come from mining, and from nowhere else in the fort's
own production. The Gem page (v50 wiki) states the rule, and it
is consistent with the raws: gem clusters are small clusters in
stone, and every gem tile mined produces a gem. Unlike stone,
which has a 25 percent chance of dropping a boulder per tile
(STONEWORKING.md section 2.1), a gem tile always yields. The
survey can never name a gem vein: ore and gem identity is not in
the tile type (survey.py, section 4.3 below), so a gem cluster is
"mineral vein (unidentified)" until its gems are mined and read.
Identification comes from mined gems, never from the survey.

The other sources, all secondary:

- **Trade.** Cut gems, large gems, and gem crafts come from dwarf
  and human caravans. Rough gems are notably not available for
  trade, with the exception of raw glass (Gem page, v50 wiki,
  UNVERIFIED for 0.47.05). The fort cannot buy its way into a
  rough gem stock; it mines one or it has none.
- **Glass.** Raw glass from a glass furnace is treated in most
  ways as a rough gem. Green glass (value 2), clear glass (5),
  and crystal glass (10) are the three kinds. Glassmaking is a
  separate industry with no design doc yet; this doc treats raw
  glass only as a training input and a cut-glass source, and the
  glass furnace itself is out of scope.
- **Gizzard stones.** Butchering certain animals yields gizzard
  stones, which behave like cut gems, not rough ones
  (ANIMAL_HUSBANDRY.md owns the butchering side). They go
  straight to the setter, never to the cutter.
- **Creatures.** A killed amethyst man drops a rough amethyst.
  Rare enough to ignore in planning.

### 2.2 The 127 gems, verified from the raws

`inorganic_stone_gem.txt` in the 0.47.05 install defines 127 gem
types (128 `[INORGANIC` lines in the file, one of which is the
`[OBJECT:INORGANIC]` header). Every one carries `[IS_GEM:...]`.
Their material values, counted from the raws 2026-11-27:

| Value | Count | Tier |
|---|---|---|
| 2 | 38 | Ornamental, cheapest |
| 3 | 3 | Ornamental |
| 10 | 16 | Ornamental, opals mostly |
| 15 | 5 | Semi-precious |
| 20 | 46 | Semi-precious, the bulk |
| 25 | 2 | Semi-precious |
| 30 | 5 | Semi-precious |
| 40 | 4 | Precious: emerald, faint yellow diamond, ruby, sapphire |
| 60 | 8 | Rare: six diamonds, star ruby, star sapphire |

The v50 wiki's count agrees: 130 kinds of gems, 127 excluding
the three kinds of glass; 57 ornamental, 58 semi-precious, 4
precious, 8 rare. The raws confirm the 127 and the 4/8 split at
the top. The wiki's ornamental and semi-precious counts (57 and
58) against the raws (57 at value 2, 3, or 10; 58 at value 15,
20, 25, or 30) also agree exactly: 38 plus 3 plus 16 is 57, and
5 plus 46 plus 2 plus 5 is 58.

Where gems are found, from the raws:

- Most gems occur as `CLUSTER_SMALL` in named stone: 180
  `CLUSTER_SMALL` entries in the gem file. Some occur in all
  stone, some only in sedimentary, metamorphic, granite, marble,
  bauxite, gabbro, kimberlite, and other hosts. The host stone
  decides which gems a given embark can ever mine, and the fort
  does not choose it.
- The 8 rare gems do not occur as clusters of their own. They
  occur as `CLUSTER_ONE` inside another gem: the six diamonds
  inside faint yellow diamond (`[ENVIRONMENT_SPEC:DIAMOND_FY:
  CLUSTER_ONE:1]`, verified in the raws), star ruby inside ruby,
  star sapphire inside sapphire. A fort mines faint yellow
  diamonds hoping for a clear diamond inside, and the harness
  must not promise rare gems on a map with no faint yellow
  diamond or ruby or sapphire host.
- Kimberlite is the diamond host: faint yellow diamond occurs in
  kimberlite, and the wiki's industry advice names kimberlite as
  the stone to watch for. Whether the current fort's map has
  kimberlite is a survey question the survey cannot answer
  directly (section 4.3); it is answered when a kimberlite
  boulder is mined and read.

### 2.3 Cutting: what a rough gem becomes

Cutting is a job at the jeweler's workshop, done by a dwarf with
the Gem cutting labor. It consumes one rough gem. The v50 wiki
(Gem page, Gem industry page) says the result is one of three
things: a cut gem (by far the most common), a large gem, or a
gem craft. The Gem page gives exact numbers: exactly 5 percent
of all rough gems are cut into a single craft or large gem, with
1 craft for every 8 large gems. The same page says raw glass
differs: 33 percent of glass cutting jobs produce a large gem or
craft, with 11 crafts for every 16 large gems. Both ratios are
UNVERIFIED for 0.47.05 until a live cutting run counts its
outcomes (phase 4). The Gem industry page adds that the v50.05
game turned large gem cutting off for normal gems, which is a
v50 change that must not be read back into 0.47.05: the 0.47.05
behavior is whatever the live run shows.

What the three outcomes are for:

- **Cut gems** are the setting input. They are the only cutting
  outcome a setter can use, and the only outcome that feeds gem
  windows. A cut gem has no quality level (Gem cutter page, v50
  wiki, UNVERIFIED for 0.47.05). If that holds, cutter skill
  does not change the value of a cut gem at all.
- **Large gems** are finished goods. They cannot be set and
  cannot be used for anything but trade and fortress value.
  They have quality levels, set by the cutter's skill.
- **Gem crafts** are crafts (figurines, rings, earrings, amulets,
  bracelets, scepters, crowns) made of a gem type. They have
  quality levels, set by the cutter's skill. They are trade
  goods. Glass cannot be made into crafts at a glass furnace,
  only through a jeweler's workshop (Gem industry page, v50
  wiki, UNVERIFIED for 0.47.05).

Values, from the v50 wiki, all UNVERIFIED for 0.47.05 until a
live read-back prices real items:

- Rough gem: base value 6 times the gem value (2 to 60), so 12
  to 360.
- Cut gem: base value 20 times the gem value, so 40 to 1,200.
- Large gem: base value 10 times the gem value times the quality
  multiplier (1 to 2), so 20 to 1,200, plus 30 for a masterwork
  by the wiki's worked example.
- Gem craft: base value 10 times the gem value times the quality
  multiplier (1 to 2), so 20 to 1,200.
- Gem decoration (setting): base value 10 times the gem value
  times the quality multiplier (1 to 2), so 20 to 1,200 per
  decoration.

The worked example on the Gem page: a rough green zircon is
worth 6 times 20 = 120, a cut green zircon 20 times 20 = 400,
a masterwork large green zircon 10 times 20 times 2 plus 30 =
430. The Gem cutter page states the headline: cutting and
encrusting with a gem more than triples the value of the rough
gem, and a masterwork gem decoration is worth nearly 12 times
the value of the original rough gem. The value ladder is why
the setter matters more than the cutter (section 2.5).

### 2.4 Cutting stone: cabochons

Ordinary stone can be cut at the jeweler's workshop too. A cut
ordinary stone always comes out as a cabochon, not a cut gem
(STONEWORKING.md section 3.4, Jeweler's workshop page, v50
wiki). A cabochon is a cut and polished stone, and it can be
used to encrust furniture and finished goods exactly like a cut
gem. Some rough gems are also always cut as cabochons, depending
on the opacity or transparency of the stone (Jeweler's workshop
page, v50 wiki, UNVERIFIED for 0.47.05: which gems, and by what
rule, is a live question).

The stone-cutting rules that matter for the harness:

- Any boulder can be cut, including clay and ice boulders
  (Jeweler's workshop page). The jeweler's workshop is a stone
  sink and a training ground: gem setters train on cheap cut
  stone before touching real gems, and excess stone can be
  disposed of by cutting it.
- Flux stone and obsidian cabochons are 2 to 3 times as valuable
  as ordinary ones, because their material values are 2 and 3
  (STONEWORKING.md section 2.2, verified from the raws).
- Cutting valuable stone such as obsidian or metal ore into
  cabochons and encrusting crafts with them raises craft value,
  but the wiki notes it is almost always better to smelt the
  ore and stud the crafts instead, or just produce more metal
  crafts. The harness never cuts ore boulders: ore is bars
  (STONEWORKING.md refusal 1, METALWORKING.md).
- The UI menu name for this job is "Polish stones"
  (Jeweler's workshop page). There is no Polish job type in the
  runtime enums (section 4.4), so "Polish stones" must map to
  one of the existing job types, most plausibly CutGems with a
  stone material. Which one is UNVERIFIED until a live probe
  settles it (phase 3).

### 2.5 Setting: what a cut gem becomes

Setting is a job at the jeweler's workshop, done by a dwarf with
the Gem setting labor. It takes one cut gem (or one cabochon, or
one gizzard stone, or one cut glass gem) and encrusts one of
three kinds of target: furniture, finished goods, or ammo. The
menu lists each target three ways: with cut gems, with cut
glass, and with polished stones (cabochons). That is nine
encrust jobs in the UI, and the enum fixture has only two
encrust job types: EncrustWithGems (87) and EncrustWithGlass
(88). How nine UI jobs map to two job types is UNVERIFIED
(phase 3): the likely answer is that the job type names the
gem kind and the job items name the target kind, but that is a
live probe, not a fact.

The setting rules that shape the plan:

- **Skill is the value.** Cut gems have no quality, so the
  cutter's skill does not change a cut gem's value. The
  decoration's quality comes from the setter's skill, and the
  decoration is where the value multiplies. A legendary setter
  is the most valuable dwarf in this industry; a legendary
  cutter is a fast cutter and little more. Training priority
  follows that: train setters on cheap stone and glass, save
  high-value gems for a setter who can make masterworks.
  (Gem cutter page, v50 wiki, UNVERIFIED for 0.47.05.)
- **One decoration per gem type per item.** An item may carry
  multiple decorations, but only one using each type of gem
  (Gem industry page, v50 wiki, UNVERIFIED for 0.47.05). A
  statue encrusted with amethyst cannot take a second amethyst,
  but it can take a ruby as well. The harness counts
  decorations per item per gem type, not just decorations per
  item, when it decides what is left to gain.
- **Weapons and armor cannot be encrusted**, except cloth armor
  (Gem setter page, v50 wiki, UNVERIFIED for 0.47.05). Finished
  goods exclude tools. Ammo includes siege ammo. The harness
  never offers an encrust job on a weapon or a metal armor
  piece.
- **The setter picks the target, not the player.** The UI lets
  the player choose which gem to set, but not which item gets
  it. The dwarf takes the nearest eligible item that is not
  nailed down (Gem industry page, Gem setter page). The wiki's
  control method is stockpile surgery: a small stockpile holding
  only the intended item, linked to the workshop, with
  everything else forbidden. The harness has no stockpile link
  action and no forbid action today (section 4.5), so targeted
  encrusting is blocked until those land. Until then, encrust
  jobs are untargeted, and the harness must say so.
- **Repeat jobs pile onto one item.** If a gem setter enters the
  shop and finds a correct item already there because a hauler
  did not remove it after the last job, the setter encrusts that
  item again instead of waiting for a different one (Jeweler's
  workshop page). This is a hazard for trade variety and a tool
  for room value: the same behavior that wastes ten gems on one
  mug can deliberately stack every gem in the fort onto one
  dining hall statue. The harness treats it as a hazard by
  default and never queues repeat encrust jobs.
- **Discarded clothing can be decorated.** When encrusting
  finished goods, any discarded clothing in the workshop or
  linked stockpiles may be decorated, and the wiki says there
  is no way to avoid it short of tedious micromanagement
  (Gem industry page). The harness keeps worn and discarded
  clothing out of the jeweler's feeder pile. How it does that
  before stockpile settings writes exist is an open question
  (section 13).
- **Mechanisms are furniture.** STONEWORKING.md section 9.1
  records that mechanisms count as furniture for stockpiling,
  so an encrust-furniture job can gem a mechanism instead of a
  statue. The harness keeps mechanisms in their own stockpile
  when the fort has a jeweler, or accepts the occasional gemmed
  mechanism as the cost of a shared pile. A gemmed mechanism
  still works as a mechanism; the loss is the gem, not the trap.

### 2.6 Gem windows

A gem window is furniture built on site, not in a workshop,
from three cut gems of any type, including cut glass gems and
cut stone cabochons (Window page, v50 wiki). It cannot be made
from large gems. The rules:

- **Value is the sum of the gems.** A gem window has no quality
  levels, so its value is the sum of the three gems' values
  (2 to 60 each by gem type, 6 to 180 total by the wiki's
  arithmetic). A glass window, made at a glass furnace, has a
  value multiplier of 25 and quality levels, and is worth more
  in general. For maximizing value, gems are better used for
  decorations than for windows (Window page). The harness
  builds gem windows for rooms and for color, not for value.
- **Mixed colors flash.** A window built of gems of different
  colors flashes between the colors of the individual gems.
  That is the whole point of a gem window as a room feature:
  a dining hall window in three colors is a happy thought with
  a light show.
- **A gem window is reversible.** Disassembling one yields the
  gems that made it up. A glass window does not give its glass
  back. The harness can treat a gem window as stored gems that
  happen to be a window right now.
- **Building destroyers topple, not destroy.** A gem window
  wrecked by a building destroyer is toppled, leaving the gems
  behind. A glass window is destroyed.
- **Nobles do not accept them.** A noble mandate to make windows
  is not satisfied by building a gem window (Window page).
  The harness never counts a gem window against a window
  mandate.
- **Placement needs a floor.** Like all furniture, a window must
  have a floor underneath it to be built, and it blocks water
  flow while letting dwarves see through it. Dwarves get a happy
  thought from passing by a window, and a happier one if it is
  built of a material they like. Civilians seeing a hostile
  creature through a window cancel jobs and run.

The job type MakeWindow (127) exists in the runtime enums, and
the building types WindowGem (18) and WindowGlass (17) exist.
Whether MakeWindow is the on-site gem window construction job,
the glass furnace window job, or both, is UNVERIFIED (phase 6).
`FURNITURE_ITEMS` in the harness has no Window kind today, so
no route places a window at all (section 4.4).

### 2.7 Glass: the training supply

Raw glass is the training input that makes this industry
scalable. A glass furnace with sand and fuel (or magma) makes
raw glass in bulk, and raw glass is treated as a rough gem for
cutting and setting. The Gem industry page is explicit: gem
cutters get the same experience cutting raw glass as cutting
valuable gems, so a beginning jeweler can train by cutting raw
green glass until legendary, and the surplus cut glass can train
gem setting the same way. The ratios differ (section 2.3), and
glass crafts come only from the jeweler, never from the glass
furnace.

The boundaries, stated plainly so no doc claims the other's
work:

- The glass furnace, sand gathering, pearlash, and glass
  products (goblets, windows, blocks) belong to the glass
  industry doc when it lands. This doc owns only what happens
  once raw glass exists: cutting it, setting it, and counting
  it as gem stock.
- Rough rock crystal is the crystal glass ingredient. Rough rock
  crystals are required to make crystal glass goods, and cut
  rock crystals cannot be used for it (Gem page, Jeweler's
  workshop page). The harness never cuts rough rock crystal
  while the fort has any glassmaking ambition, and the snapshot
  names the rough rock crystal count separately so the agent
  can see the reserve (section 12.1).
- Cut glass gems may be used to construct a gem window, although
  the wiki notes this is less valuable than making a window
  directly from glass at a glass furnace (Gem industry page).

### 2.8 Strange moods and the mood reserve

A dwarf seized by a strange mood can demand a rough gem, and a
moody dwarf can take a single gem and cut it into a perfect gem:
an artifact large gem with a base value of 10 times the gem
value times a quality multiplier of 20, plus one free decoration
that effectively doubles the value, for 4,800 to 144,000 by the
wiki's arithmetic (Gem industry page, v50 wiki, UNVERIFIED for
0.47.05). Perfect gems cannot be created on purpose. Keeping a
stockpile of high-value gems near the jeweler's workshop might
increase the chance of a moody dwarf choosing one, and
forbidding low-value gems is an option the wiki names.

The harness rule is simpler and does not depend on the maybe:
never cut all the gems. The fort keeps a mood reserve of rough
gems, starting at 3 of the highest-value rough gems on hand,
untouched by cutting jobs, until a live run says the number
should move. The reserve is a count in the snapshot, not a
feeling. The strange mood briefing (briefings.py
`strange_mood` kind) already fires when a mood starts; the gem
part of it is whether a suitable rough gem is in stock, and
that is a query, not a guess (section 12.3).

## 3. The workshop: the jeweler's workshop

0.47.05 has 31 workshops (STONEWORKING.md section 3, citing
DF2014:Workshop). The gem chain uses one of them, plus the glass
furnace as a supplier and the craftsdwarf's workshop as a
neighbor for large gems from shell, horn, and ivory (MakeGem,
job type 236, section 4.4).

The jeweler's workshop is 3x3. Its shortcut is b-o-j. It is
built from any non-economic building material, and its
construction needs one of the Gem cutting or Gem setting labors
(Jeweler's workshop page, v50 wiki). Its job requirement is Gem
cutting or Gem setting. Its materials used are rough gems and
cut gems. Its goods created are cut gems, gem crafts, and
encrusted objects.

The full UI menu, from the Jeweler's workshop page (v50 wiki):

- Cut Gems
- Cut raw glass into gems
- Encrust ammo with cut gems
- Encrust ammo with cut glass
- Encrust ammo with polished stones
- Encrust finished goods with cut gems
- Encrust finished goods with cut glass
- Encrust finished goods with polished stones
- Encrust furniture with cut gems
- Encrust furniture with cut glass
- Encrust furniture with polished stones
- Polish stones

Twelve menu entries. The runtime enums give five job types that
can plausibly serve them: CutGems (85), CutGlass (86),
EncrustWithGems (87), EncrustWithGlass (88), and MakeWindow
(127) if windows are workshop jobs at all. The mapping from
twelve menu entries to five job types is the central probe of
phase 3, and it is UNVERIFIED until a live run queues each menu
entry and reads back the job type the game created.

The workshop profile matters more here than anywhere else in
the fort. The wiki's industry advice is to use the Workers tab
to set the jeweler's workshop profile so only specific dwarves
can use it, ensuring only the most skilled cutters and setters
work the most valuable gems. The harness has no workshop
profile action today (section 4.5). Until it does, the only
control is labor assignment: enable Gem cutting and Gem setting
on exactly the dwarves meant to do the work, and on no one else.

## 4. What the harness has today

Verified against the repo 2026-11-27. Everything in this section
was read from the code, not assumed. The daemon and game were
down for a VM replacement at the time of writing, so no live
snapshot was read; every live value in this section is marked
UNVERIFIED with its proving bar in section 13.

### 4.1 The jeweler's workshop does not exist in the harness

`WORKSHOP_CATALOG` (actions.py) has exactly four workshops:
carpenter, mason, still, kitchen. The jeweler's workshop is NOT
in the catalog. `build_workshop` cannot build it today. The
catalog entry is small (type Workshop, subtype Jewelers, 3x3,
material BOULDER) and the subtype name is verified: the runtime
fixture lists workshop type 4 as `Jewelers`. The build route is
the existing `build_workshop`; only the catalog entry is new.

`placement.py` has no affinity row for the jeweler's workshop.
The mason and craftsdwarf rows name a stone stockpile at
affinity 25 (STONEWORKING.md section 4.1). The jeweler needs
the same treatment: a gems stockpile at affinity 25, and a
finished-goods stockpile nearby for the encrust targets. That
is a placement gap, not a build gap.

### 4.2 The labors exist; the workers do not

`act_labor.lua` enables or disables any `df.unit_labor` by name
on one citizen, verified by read-back (STONEWORKING.md section
4.3). The fixture confirms the labor names exist on r8:
`CUT_GEM` (51) and `ENCRUST_GEM` (52). The labor action can
already set both. What does not exist is any assignment: the
labor plan (LABOR.md) names no gem cutter and no gem setter,
and no dwarf in the fort is known to have either labor enabled.
Which dwarves have gem skill, and whether any migrant arrived
with it, is UNVERIFIED until the dwarves read lists skills
(section 13).

The skills exist in the fixture too: `CUTGEM` (31) and
`ENCRUSTGEM` (32) in `job_skills`. The diary already knows the
word jeweler: diary.py warns never to write a dwarf working at
a jeweler's bench unless the facts say so.

### 4.3 The harness can see stone, but gems are invisible inside it

- `stocks.lua` counts `stone_units` as BOULDER plus ROUGH plus
  BLOCKS units, and `stone_stacks` the same way. Rough gems are
  inside the stone number. A fort with 142 stone and 11 rough
  gems reports "stone 142" and the agent cannot tell.
- `stocks.lua` builds a `by_material` breakdown, but only for
  DRINK, FOOD, MEAT, FISH, PLANT, SEEDS, BAR, WOOD, CLOTH, and
  THREAD item types. ROUGH, SMALLGEM, and GEM items never enter
  `add_mat`, so there is no per-material gem breakdown anywhere
  in the collect. The full item-type table (`items.by_type`)
  does carry ROUGH, SMALLGEM, and GEM totals by type, so the
  counts exist one level down, without material identity.
- The snapshot's Stocks line prints the stone total and its burn
  rate (assembler.py `_stocks`). It prints no gem number at all.
- `survey.py` counts stone tiles by z-level and names the
  richest z-levels, and reports mineral veins as unidentified:
  ore identity is not in the tile type, so a vein is "mineral
  vein (unidentified)" until its boulders are mined and read.
  The same limit applies to gems, harder: a gem cluster is a
  mineral block, and the survey can never name it as a gem
  vein. Gem discovery happens at mining time, when a ROUGH item
  appears in stock, never at survey time.
- The catalog's stockpile list (catalog.py) includes the Gems
  category in its item-management description, and STOCKPILES.md
  section 3 defines the Gems stockpile: cut and uncut gems plus
  raw glass, bins max, barrels off, near the jeweler. The
  `create_stockpile` action can create it by category today;
  whether the harness can verify its contents by gem type is
  the same stocks gap as above.

### 4.4 The job types exist in the game; the queue route cannot express them

The fixture, enumerated live from r8 on 2026-11-25, gives the
gem job types with their numeric values:

| Job type | Value | Likely UI job |
|---|---|---|
| MakeRawGlass | 82 | Glass furnace: make raw glass |
| CutGems | 85 | Cut Gems |
| CutGlass | 86 | Cut raw glass into gems |
| EncrustWithGems | 87 | Encrust with cut gems |
| EncrustWithGlass | 88 | Encrust with cut glass |
| MakeWindow | 127 | Gem window, or glass window |
| MakeGem | 236 | Large gem from shell, horn, ivory |

Three things are verified here and three are not. Verified: the
names exist, the numbers are live from r8, and the workshop
type `Jewelers` (4), the item types `SMALLGEM` (2), `ROUGH`
(4), `WINDOW` (16), `GEM` (44), and the building types
`WindowGem` (18) and `WindowGlass` (17) all exist. Not
verified: which UI menu entry maps to which job type, what
`MakeGem` (236) actually does and at which workshop, and
whether `MakeWindow` (127) is the on-site gem window job or a
workshop job. The v50 Window page says a gem window is
constructed on site, not in a workshop, which points at
MakeWindow being a construction job, but that page is v50 and
the mapping is UNVERIFIED until a live probe queues a gem
window and reads back the job.

The queue route is the hard gap, and it is structural. `JOB_SPECS`
(actions.py) has no gem job in it. `queue_workshop_job` goes
through `act_job.lua`, which builds job items only for reaction
jobs (job type 211, CustomReaction): it copies the reaction's
reagents into `job.job_items`. For a plain job with no reaction,
it creates a bare job with no job items at all, and its own
comment says a bare job with no job items is never claimed. A
CutGems job needs job items naming a rough gem of a specific
material, and an EncrustWithGems job needs job items naming a
cut gem of a specific material and a target of a specific kind.
`act_job.lua` has no way to build those job items today, and
nobody has probed what the game expects them to look like: a
material filter on the job itself, a job item with a material
token, or something else entirely. That probe is phase 3, and
it is the phase the whole industry stands on.

The one existing route that CAN express a gem job today is
`manager_order_create` (actions.py, `act_order.lua`). It takes
a `df.job_type` name directly and creates a manager order. It
was verified live for a generic order, but no gem job type has
been passed through it, and a manager order carries no material
choice either: an order for CutGems lets the game pick the gem,
which is exactly the blind-cutting failure mode in section 1.
Whether the manager validates and dispatches a jeweler job
without a manager noble appointed is UNVERIFIED
(STONEWORKING.md section 15, question 3, same question).

### 4.5 What the agent can see today, and what it cannot do

- The snapshot's Buildings line names each workshop by subtype
  and id, and says "Still: none" when there is no still. It
  does NOT name a missing jeweler's workshop. The agent cannot
  tell from the snapshot whether gemcutting is possible at all.
- The snapshot's Stocks line prints the stone total, which
  silently includes rough gems. It prints no rough, cut, large,
  cabochon, or encrusted count.
- The snapshot's Materials section (materials.py) knows the
  mason's build material and the still's and kitchen's. It
  knows nothing about gem jobs, because no JOB_SPECS entry
  exists for them to hang requirements on.
- There is no workshop profile action, no stockpile link action,
  no forbid action, and no stockpile settings write anywhere in
  the harness (STOCKPILES.md sections 3.3 and 10). Targeted
  encrusting, the wiki's whole control method, has no harness
  route at all. The encrust guard in section 9 is designed
  around that absence: separate piles and labor discipline now,
  links and forbidding later.
- The diary feed groups queued jobs by workshop, so a jeweler
  job queued through a manager order would appear under its
  workshop once the workshop exists. No diary work is needed
  for gemcutting beyond that.

## 5. The chain, end to end

The chain has six steps, and the harness must be able to run
all six without the agent thinking about tile types.

1. **Dig.** `designate_dig` opens rock. Gem clusters are found
   while mining; every gem tile yields a gem. The survey says
   where the rock is; the dig action says what it opened; the
   stocks read says which gems came out of it.
2. **Haul.** Rough gems are hauled to the Gems stockpile by the
   jeweler's workshop, bins on (STOCKPILES.md section 3:
   "Cut and uncut gems, raw glass", bins max). STOCKPILES.md
   section 2.6 notes the alternative: with no gem stockpile,
   the jeweler fetches fresh gems directly instead of waiting
   for them to be hauled. A young fort with few haulers may be
   better off with no gem stockpile at all until the hauling
   keeps up.
3. **Sort.** High-value rough gems are kept apart from
   low-value ones, and rough rock crystal is kept apart from
   both. Sorting is by value tier (section 2.2), not by each of
   the 127 types: a high pile (precious and rare, value 40
   and 60), a middle pile (semi-precious, 15 to 30), a low pile
   (ornamental, 2 to 10, plus raw glass), and a rock crystal
   reserve. Four piles, not 127. This depends on stockpile
   settings writes, which do not exist yet; until they do, the
   sort is a single Gems pile and the cutting order is the
   control (section 6).
4. **Cut.** The cutter turns rough gems into cut gems, large
   gems, and gem crafts. One rough gem per job. The cutter
   works the low pile first for training and the high pile
   only when the setter is ready for the product.
5. **Set.** The setter encrusts furniture, finished goods, and
   ammo with cut gems and cabochons. One cut gem per
   decoration, one decoration per gem type per item. The setter
   works trade goods before the caravan and room furniture
   before a noble arrives.
6. **Sell or place.** Large gems and gem crafts go to the trade
   stockpile and out with the caravan. Encrusted furniture is
   placed with `build_furniture` from stock, and encrusted
   finished goods go to the trade stockpile. Gem windows are
   built on site from cut gems (section 8).

The bottleneck moves. Early on it is discovery: the fort has
no rough gems because it has not dug into gem-bearing stone.
Later it is labor: one jeweler cannot cut and set at once, and
cutting and setting are two different labors on (usually) two
different dwarves. Later still it is choice: the fort has a
hundred rough gems and the question is which ten are worth
cutting and which one is worth setting into the dining hall
statue. The snapshot must show which bottleneck is binding
right now, not just that gems exist.

## 6. Cutting: the order of work

Cutting order is the whole control system until stockpile
settings writes and workshop profiles exist. The rules:

- **Low first for training.** A new cutter works the low pile:
  ornamental gems, raw glass, and ordinary stone cabochons.
  Cut gems have no quality (if section 2.3 holds), so a novice
  cutter's cut gems are worth exactly as much as a legendary
  cutter's. What the novice lacks is speed and large gem and
  craft quality, and those matter only for the trade goods
  that come out as large gems and crafts. Train on the cheap
  stock, sell the cheap product.
- **Never cut the reserve.** The mood reserve (section 2.8, 3
  highest-value rough gems) is never a cutting input. Rough
  rock crystal is never a cutting input while the fort has any
  glassmaking ambition. Both reserves are counts in the
  snapshot, and a cutting job whose input would breach them
  fails fast with the reserve named.
- **Diamonds last.** Faint yellow diamond (value 40) is cut
  only when the setter is legendary or near it, because a
  diamond decoration set by a dabbling setter wastes the best
  material in the game on a poor decoration. The rare diamonds
  (value 60) are never cut on a schedule: they are cut one at
  a time, when a specific target and a specific setter are
  both ready. Whether a rare diamond should be cut at all,
  rather than kept rough for a mood or for trade, is an agent
  decision, and the snapshot presents it as a count, not a
  recommendation (section 12).
- **Stone is the fallback input.** When there are no rough gems
  to cut and the cutter would otherwise idle, the cutter cuts
  stone into cabochons: flux and obsidian first (2 to 3 times
  the value), ordinary stone last. This is STONEWORKING.md
  phase 7, the stone sink, and it is also setter training:
  cabochons are the cheapest setting input in the game.
- **Glass is the scalable input.** When the glass industry
  exists, raw green glass is the training input that never
  runs out: sand plus fuel makes more. The cutter trains on
  glass, the setter trains on cut glass, and the fort's real
  gems wait for skilled hands. This is the only cutting input
  the harness may queue on repeat, and only for glass.

The cutting job's material question is the open probe of phase
3: the harness must be able to say "cut amethyst", not just
"cut a gem". A CutGems job with no material named is a blind
cut, and the harness refuses blind cuts on any gem above the
low pile (section 11, refusal 2).

## 7. Setting: what gets encrusted, and in what order

Setting order is where the value is made, and where the harm
is done if it is wrong. The rules:

- **Trade goods first, before the caravan.** Encrusted mugs,
  crafts, and goblets are the highest-value portable goods in
  the fort. The season before a caravan, the setter works the
  trade stockpile's finished goods with the best cut gems the
  fort can spare. TRADING.md section 6.2 owns the pipeline;
  this doc owns the setting step inside it.
- **Room furniture second.** A statue or table in the dining
  hall or a noble's room, encrusted with a mid-value gem, raises
  the room value and gives happy thoughts every day the fort
  stands. One decoration per gem type per item means the dining
  hall statue can take an amethyst, a ruby, and a topaz over
  three jobs, and the harness counts what it already has before
  queueing the next.
- **Ammo last, and only with cheap gems.** Encrusted bolts are
  consumed when fired. A diamond on a bolt is a diamond thrown
  at a goblin. Ammo encrusting uses cabochons and cut glass
  only, never a cut gem above value 10, unless the agent
  explicitly orders otherwise. Whether encrusted ammo is worth
  anything at all in combat, beyond its value, is UNVERIFIED
  (section 13): the wiki does not claim a combat effect, and
  the harness must not claim one either.
- **Never the mechanism.** Mechanisms live in their own
  stockpile, away from the jeweler, so an encrust-furniture job
  cannot pick one up (section 2.5). If the piles cannot be
  separated yet, the harness accepts the occasional gemmed
  mechanism and says so in the snapshot, rather than pretending
  the guard exists.
- **Never the masterwork with the cheap gem.** The untargeted
  setter picks the nearest eligible item. Until targeted
  encrusting exists (phase 5), the harness does not queue
  encrust jobs while a masterwork item sits unprotected in the
  jeweler's reach. The protection is labor discipline and pile
  separation, not a promise: the snapshot names the exposure
  when it exists ("masterwork statue in jeweler's reach, no
  target control").
- **One job, one gem, one check.** After each encrust job
  completes, the harness reads back the target item and its
  decorations. A job that decorated the wrong item is logged
  with the item and the gem, and the next job waits for the
  agent to see it. Silent wrong-target setting is how a fort
  loses its diamonds one job at a time.

## 8. Gem windows: rooms, not revenue

Gem windows are built for rooms, not for trade. The plan:

- **Where.** Dining halls, temples, and noble rooms first: the
  rooms where dwarves spend time and where room value pays
  every day. A gem window in a corridor is a wasted window.
- **What.** Three cut gems of different colors, so the window
  flashes. Mixed-color windows are the only reason to build a
  gem window instead of a glass one: for pure value, glass
  wins (section 2.6). The harness picks the three cheapest cut
  gems of three different colors that are not reserved for
  setting, and says which three it used.
- **When.** Only after the setter has the cut gems it needs for
  trade goods. Windows consume cut gems that could have been
  decorations, and decorations are worth more. A window is a
  surplus use, never a first use.
- **How.** The build route is UNVERIFIED: the v50 Window page
  says on-site construction, not a workshop job, and
  `FURNITURE_ITEMS` has no Window kind. Phase 6 probes whether
  MakeWindow (127) is the construction job and what route
  builds a WindowGem building from three cut gems, then adds
  the route. Until then, the harness does not promise a gem
  window.
- **Reversibility.** A gem window can be deconstructed into its
  three gems. The harness treats a built gem window as stored
  gems, and the query route lists windows with their gem
  contents (section 12.2), so the agent can reclaim them.

## 9. Gem stockpiles and hauling

The storage rules live in STOCKPILES.md and are not repeated
here. The gem-specific rules are:

- **One Gems pile by the jeweler, bins on.** STOCKPILES.md
  section 3: cut and uncut gems plus raw glass, bins max,
  barrels off, near the jeweler. Gems are small and light;
  bins hold them, and the bin count for small gems is 305 per
  bin by the STOCKPILES.md bin table (section 3, citing 305
  small gems per bin). That number is taken from STOCKPILES.md
  and is UNVERIFIED here until a live count settles it.
- **Four piles by value when settings writes exist.** High
  (40, 60), middle (15 to 30), low (2 to 10 plus raw glass),
  rock crystal reserve. The cutter draws from low, the setter
  draws cut gems from the cut pile, and the high pile is opened
  only by an explicit decision. This phase depends on the
  settings write and link actions from STOCKPILES.md phases 2
  and 3; if those have not landed, this phase builds the piles
  category-flag-only and records what the missing links cost.
- **Mechanisms apart.** The mechanism stockpile is nowhere near
  the jeweler (section 7). The furniture stockpile that feeds
  encrust-furniture jobs holds statues, tables, and thrones,
  not mechanisms.
- **No pile can be better than a bad pile.** STOCKPILES.md
  section 2.6: with no gem stockpile, the jeweler fetches fresh
  gems directly instead of waiting for them to be hauled. A
  young fort with few haulers runs with no gem stockpile until
  the hauling keeps up. The harness says which mode the fort
  is in, and does not build a pile the fort cannot fill.
- **Loose gems are the discovery signal.** A rough gem on the
  mine floor with no accepting stockpile is a missing stockpile,
  and the harness says so by name. The snapshot's loose-gem
  count is the number that says whether hauling is keeping up
  with mining, and whether a gem vein was struck at all.

## 10. Trade value of gems

TRADING.md section 6.1 ranks trade goods by base value, but it
does not rank gem goods. This section supplies the gem numbers
for that ranking; the ranking itself stays TRADING.md's, and
any change to it is a TRADING.md change, not a change here.

From the v50 wiki values in section 2.3 (all UNVERIFIED for
0.47.05 until live read-back prices real items):

- A cut gem is worth 40 to 1,200, which is 20 times the gem
  value. Even the cheapest cut gem (value 2, worth 40) beats a
  stone mug (base 30). A cut gem is a trade good in its own
  right, not just a setting input, and the fort can sell cut
  gems directly when it has no setter.
- A large gem is worth 20 to 1,200, and a gem craft 20 to
  1,200, both with quality multipliers. A masterwork large
  diamond is worth 1,230 by the wiki's arithmetic, the single
  most valuable portable item the fort can make without metal.
- An encrusted finished good is worth its own value plus 20
  times the gem value times the decoration quality multiplier
  per decoration, and it can carry one decoration per gem type.
  A mug with three decorations is worth the mug plus three
  gem values. This is why encrusted trade goods outrank plain
  ones, and why the setter, not the cutter, is the value
  bottleneck.
- Rough gems are not sold. A rough gem is worth 12 to 360, and
  cutting it more than triples it. Selling a rough gem is
  selling the cutting work undone. The only exception is a
  rough gem the fort cannot cut because it has no jeweler and
  no prospect of one, and even then the agent decides.
- Elves accept all rough and cut gems (TRADING.md, citing the
  trade rules). Dwarves and humans bring cut gems, large gems,
  and gem crafts to sell. The fort buys cut gems it lacks for
  setting, and never buys rough gems, because caravans do not
  bring them.

The trade plan for a young fort is: cut the low pile, set the
trade goods with the best cut gems the fort can spare, and send
large gems and gem crafts out with the caravan. The production
pipeline starts the season before the caravan it serves
(TRADING.md section 6.2). Obsidian and flux cabochons are the
cheap substitute when the fort has no real gems: 2 to 3 times
an ordinary cabochon, and the stone to make them is free.

## 11. Refusals

The harness refuses these, and says why in plain words when asked:

1. Never cut the mood reserve. Three highest-value rough gems
   stay rough until a mood takes one. A fort that cut every gem
   has nothing to give a moody dwarf.
2. Never queue a blind cut on a gem above the low pile. A CutGems
   job with no material named lets the game pick the gem, and
   the game may pick the diamond. Material choice is the job.
3. Never cut rough rock crystal while the fort has any
   glassmaking ambition. Rough rock crystal is the crystal glass
   ingredient, and cut rock crystal cannot be used for it.
4. Never cut ore boulders into cabochons. Ore is bars. The
   jeweler works stone and gems, not ore.
5. Never encrust a weapon or metal armor. The game does not allow
   it, and the harness must not offer a job whose target the
   game refuses.
6. Never encrust ammo with a cut gem above value 10. Ammo is
   consumed when fired. A diamond on a bolt is a diamond thrown
   away.
7. Never queue repeat encrust jobs. A repeat job piles every gem
   onto the one item the hauler did not remove. One job, one
   read-back, then the next.
8. Never sell a rough gem while the fort has a jeweler or a
   prospect of one. Cutting more than triples it. Sell the cut
   gem, or set it and sell the good.
9. Never count a gem window against a noble window mandate. The
   mandate is not satisfied by a gem window, and the snapshot
   must not claim it is.
10. Never claim a gem job works until a real item has been made
    and read back. A job type name from the fixture is not proof
    the game accepts the job items, and a manager order that
    sits unvalidated is not proof the game dispatched it.
11. Never promise targeted encrusting until the link and forbid
    routes exist and are verified live. An untargeted setter
    picks the nearest item, and the harness must say so.
12. Never claim a gem vein was surveyed. The survey can never
    name a gem vein. Identification comes from mined gems.

## 12. Model presentation

This section is required by the 2026-11-27 presentation
constraint (GOAL.md, coordinator log 2026-11-27): every new
system must state how its information reaches the model, what
it costs, and what it deliberately does not push. The snapshot
stays an index: counts, exceptions, and diffs only, about 4,700
tokens typical, never a replacement for full state. Budgets hold
(target 30K, warning 60K, compaction 100K, hard cap 140K on a
200K window), enforced by the assembler's token accountant with
its cut order. No system bolts its own dump onto the snapshot.

Token costs below are computed from the exact section text with
the accountant's own rates (3 chars per token for the cap, 4
chars per token on the wire). They are estimates until the
coordinator verifies them against the live assembler before
commit, as the amendment requires. The numbers are small
because the section is an index: it names counts and exceptions,
and the detail lives behind queries.

### 12.1 Snapshot: the Gemcutting section

The per-tick snapshot gains a short Gemcutting section, built
from the fresh collect, in plain words. Three lines, in this
shape (working industry, 7 dwarves):

```
Gemcutting: rough 11 (amethyst 4, rock crystal 3, diamond 1), cut 6, large gems 1, cabochons 4.
Jeweler #9: 2 jobs queued (cut amethyst). No gem setter assigned.
Encrusted: 3 items (statue, 2 mugs). Gem window: none built.
```

When no gem industry exists, the section is one line:

```
Gemcutting: no jeweler's workshop. Rough gems 0, cut gems 0.
```

What is in it, and what is not:

- **Line 1, counts.** Rough gems in stock, with the three
  numbers that decide cutting order: the most common rough gem,
  the rough rock crystal reserve, and the highest-value rough
  gem on hand. Then cut gems, large gems, and cabochons in
  stock. These are counts, not a list: the fort can hold 127
  gem types and the snapshot never names all of them. When the
  mood reserve is breached or empty, the line says so:
  "mood reserve 0, breached" is an attention entry, not a
  quiet zero.
- **Line 2, workshop.** One short clause per jeweler's workshop
  that exists, capped at 2 clauses, then "and N more jewelers"
  when there are more. Each clause names the workshop subtype
  and id (so the model can queue a job without a query turn),
  its state (idle, or jobs queued with the job kinds), and
  whether a cutter and a setter are assigned, and nothing else.
  When no jeweler's workshop exists, the line says so and names
  the fix: "No jeweler's workshop. Build one: 1 stone in
  stock." A missing workshop is an exception, not a silence.
- **Line 3, products.** Encrusted items in stock with their
  kinds, and gem windows built with their rooms. When there are
  no encrusted items and no windows, the line is one clause:
  "Encrusted: none. Gem window: none built."
- **Diffs, not repeats.** When nothing in the section changed
  since the last tick, the assembler prints the short form
  ("gemcutting: unchanged"), the same way the Buildings section
  already does. The section costs its full price only on ticks
  when gem state actually moves.

**Token cost.** At 7 dwarves, the working section as written
above is 222 characters: about 74 tokens by the accountant's
3-chars-per-token rate, 56 on the wire. The no-industry line is
60 characters: about 20 tokens by the accountant, 15 on the
wire. At 50 dwarves, with two jewelers, more gem kinds, and a
built window, it is 302 characters: about 101 tokens by the
accountant, 76 on the wire. The cost grows by about 27 tokens
from 7 dwarves to 50, because the section is capped: 2 workshop
clauses maximum, 3 rough-gem counts maximum, product counts
only. It does not grow with population, with the number of rough
gems, or with the number of gem types on the map. If a future
change makes it grow with any of those, the change is refused
until the section is capped again.

### 12.2 Query route: GET /v1/gemcutting

GET /v1/gemcutting returns the full detail, read from the fresh
collect, not from a cache:

- Per gem type: rough in stock, rough loose on the ground, cut
  in stock, large gems, cabochons, and the material value. The
  full list, not the top 3. Rough rock crystal is listed
  separately with its reserve status.
- Per jeweler's workshop: id, subtype, position, construction
  stage, queued jobs with their job types and counts, contained
  items (clutter), and the cutter and setter assigned to it,
  with skill levels.
- Encrusted items: each item by id and kind, its decorations
  with gem types and qualities, and whether it is in stock, in
  the trade stockpile, or placed.
- Gem windows: each window by id, position, room, and the three
  gems that made it, so the agent can reclaim them.
- Mood reserve: the reserved rough gems by type, and whether
  the reserve is intact.
- Trade readiness: cut gems, large gems, gem crafts, and
  encrusted goods in the trade stockpile with their computed
  values, and the caravan target from TRADING.md.

The snapshot carries the summary and the ids; the route carries
the detail. The agent asks the route when it needs to choose
which gem to cut or which item to encrust, never as a matter of
routine. A second route, GET /v1/gemcutting/<workshop-id>,
returns one workshop in full: its queued jobs, its clutter, and
its workers. Both routes state their cost and staleness on every
response, the same as every other query route.

### 12.3 Briefing: what arrives just in time

Gemcutting has no standing briefing. Three events carry one,
all from the existing briefing system (briefings.py), each a few
hundred tokens at most, each fired once when the event starts:

- **Caravan arrives.** Trigger: the caravan event (briefings.py
  `caravan` kind). Cost: about 72 tokens by the accountant for
  the gemcutting paragraph (216 characters). It covers what gem
  goods are in the trade stockpile and their approximate value,
  whether any cut gem above value 20 is still uncut in stock,
  and what the fort could still cut before the caravan leaves.
  It leaves the per-item values and the depot haggling to the
  query route and to TRADING.md.
- **Strange mood starts.** Trigger: the strange mood event
  (briefings.py `strange_mood` kind). Cost: about 50 tokens. It
  covers whether a suitable rough gem is in stock for a mood
  that wants one, and whether the mood reserve is intact. It
  leaves the mood plan to the events doc. A fort with an intact
  reserve gets no gem paragraph at all: the briefing fires only
  when the fort cannot meet a gem mood.
- **First rough gem mined.** Trigger: the first ROUGH item
  appearing in stock. Cost: about 50 tokens. It covers the gem
  type and value, and the next step: build a jeweler's workshop
  or hold the gem for a mood. It fires once, for the first gem
  ever mined, not once per gem type.

No other gemcutting event briefs the model. A cutter finishing
a masterwork large gem, a cut gem stock hitting zero, or an
encrust job decorating the wrong item are attention entries and
opportunities entries, not briefings. A briefing is for
something the model needs to understand right now, not for
something it can read in the snapshot.

### 12.4 Opportunities: suggestion and attention only

There is no separate opportunities list in the code today
(verified by grep: no `opportunit` symbol exists in
`src/dfagent_harness/`, per METALWORKING.md section 13.5).
STONEWORKING.md section 12.4 describes an opportunities
section carrying at most 3 entries; that mechanism does not
exist in the code, and this doc follows METALWORKING.md, not
STONEWORKING.md, on this point. Gemcutting opportunities are
expressed through the two mechanisms that already exist:

- **The snapshot suggestion.** The assembler already carries one
  suggestion per tick (NEVER_CUT, assembler.py:71), and the
  planner already writes material-blocker and build suggestions
  through it. The gemcutting suggestion is one line with a
  one-line why, in the existing shape: "Build a jeweler's
  workshop (11 rough gems, no jeweler, the cutter has no bench)"
  or "Cut 4 amethyst (have 4 rough, need 0, the setter has no
  cut gems)" or "Set the dining hall statue (have 6 cut gems,
  the statue has no decoration)". One suggestion per tick, the
  most urgent gemcutting step, and only when a step is actually
  runnable. A suggestion never points at a job the fort cannot
  run, and never names a gem the fort does not have.
- **Attention entries.** The conditions that outrank a quiet
  suggestion become attention entries, ranked with the other
  problems: the mood reserve breached, a masterwork item in the
  jeweler's reach with no target control, rough gems loose with
  no accepting stockpile, a jeweler idle with rough gems in
  stock. Attention is for the things that stop the industry or
  spend its best material, not for the things that would be
  nice.

No other opportunities mechanism is defined here. If a
dedicated opportunities list is built later, it takes these
entries over unchanged; nothing in this doc depends on it
existing.

### 12.5 What the system deliberately does NOT push, and why

- **The full gem list.** The fort can hold 127 gem types. The
  snapshot names 3 rough-gem counts; the full list is behind
  GET /v1/gemcutting. A list of 127 gem types every tick is a
  dump, and the model cannot act on the 40th gem type anyway.
- **Per-gem positions.** Where each rough gem sits is survey
  data, pulled by region when the model needs it. Pushing it
  would grow the snapshot with the map, which breaks the index.
- **Per-item decoration history.** Which gem went onto which
  item, and when, is journal data. The snapshot says how many
  items are encrusted. The history is there when the model asks
  why a statue has three decorations.
- **The whole job queue.** The snapshot says "2 jobs queued
  (cut amethyst)". The full queue, with job ids and positions,
  is behind the workshop query route. A queue dump would grow
  with every job the fort queues.
- **Cutting and setting suggestions.** The snapshot never says
  "cut the diamond" or "set the statue with ruby". The
  suggestion names the runnable step with its have and need;
  the choice of gem and target is the model's, within the
  refusal rules of section 11 (HARNESS_ROLE.md). The
  presentation gives the model what it needs to decide, not a
  script to follow.
- **Trade values per item.** The snapshot says how many cut gems
  are in the trade stockpile. The computed value of each item
  is behind the query route, because values change with quality
  and material and the snapshot cannot reprice the stock every
  tick.
- **The glass industry.** Raw glass counts appear in the gem
  section only as a cutting input ("raw glass 12" in the low
  pile). Sand, fuel, pearlash, and the glass furnace state
  belong to the glass doc when it lands, not to this section.

## 13. Implementation phases

Each phase ends with a live-verification bar. A phase that cannot
be verified live is logged as unverified and re-attempted, per the
standing rule. Nothing unverified gets pushed. Phases 1 and 2
need no game running; phases 3 to 8 need the live game.

### Phase 1: See the gems

- Split ROUGH, SMALLGEM, and GEM out of the stone count in
  `stocks.lua`: report `rough_gems`, `cut_gems`, `large_gems`,
  and `cabochons` as their own counts, with a per-material
  breakdown for ROUGH and SMALLGEM items the way `by_material`
  already works for wood and cloth. Rough rock crystal is its
  own count. The stone count drops ROUGH from its sum, and the
  change is recorded in STONEWORKING.md so the two docs agree
  on what "stone" means.
- Live bar: on the main fort, the snapshot's Stocks line (or the
  new Gemcutting section, if it lands first) prints true rough,
  cut, and large gem counts that match a direct read of the
  game's item list, and the stone count no longer includes
  rough gems. UNVERIFIED until the game is back up: no live
  gem count has been read on this fort yet.

### Phase 2: Build the workshop and assign the labors

- Add `jeweler` to `WORKSHOP_CATALOG` (type Workshop, subtype
  Jewelers, 3x3, material BOULDER). Add the placement affinity
  row: jeweler's workshop wants a Gems stockpile at affinity
  25, the same weight as the mason's stone row.
- Assign the labors through the existing `act_labor.lua` route:
  enable CUT_GEM on the cutter and ENCRUST_GEM on the setter,
  on no one else. Record who holds gem skill in the labor plan
  (LABOR.md).
- Live bar: on the scratch fort, a jeweler's workshop is built
  by `build_workshop` and read back in the buildings list with
  subtype Jewelers and its id; the cutter and setter labors
  read back enabled on the assigned dwarves and disabled on
  everyone else.

### Phase 3: Probe the gem job shape

This is the phase the industry stands on. Probe, on the scratch
fort, what the game needs for each jeweler's workshop job:

- Queue a CutGems job for a named rough gem through
  `act_job.lua` with job items built to name the material, and
  read back whether a dwarf claims it and what it produces.
  If the bare job is never claimed, build the job items the way
  the game builds them from the q-menu and retry. Record the
  exact job item shape in the code and in this doc.
- Do the same for CutGlass, EncrustWithGems (furniture,
  finished goods, and ammo targets), EncrustWithGlass, and the
  "Polish stones" menu entry. Record the mapping from the
  twelve UI menu entries to the five job types.
- Probe `MakeGem` (236): queue it at a craftsdwarf's workshop
  with shell, horn, and ivory inputs and read back what it
  makes and where.
- Probe the manager-order route for CutGems as the fallback:
  whether it dispatches without a manager noble, and whether
  the game picks the gem (blind cut) or the order can name one.
- Live bar: on the scratch fort, a named cut job ("cut
  amethyst") is queued, claimed by a dwarf with the Gem cutting
  labor, and produces a cut amethyst read back in stock; a
  named encrust job produces a decorated item read back with
  its decoration; the twelve-to-five menu mapping is written
  in this doc from the probe results, not from the wiki.

### Phase 4: Cut gems live, and count the outcomes

- Queue cutting jobs across the value tiers on the scratch fort
  and count the outcomes: how many rough gems become cut gems,
  large gems, and gem crafts. Settle the 5 percent figure and
  the 1 craft per 8 large gems ratio from the v50 wiki, and
  whether large gem cutting works at all in 0.47.05.
- Price the products live: read back the value of a rough gem,
  a cut gem, a large gem, and a gem craft of the same type, and
  settle the base values 6, 20, 10, and 10 from the wiki.
  Confirm or refute that cut gems have no quality level, and
  that cutter skill changes only speed and large gem and craft
  quality.
- Confirm or refute that some rough gems always cut as
  cabochons, and by what rule (opacity or transparency).
- Live bar: on the scratch fort, at least 20 rough gems cut
  across at least 3 value tiers, with the outcome counts and
  the read-back values recorded; the cutting ratios and the
  base values in this doc are replaced with the live numbers.

### Phase 5: Set gems live, with the guard

- Queue encrust jobs on the scratch fort for each target kind
  (furniture, finished goods, ammo) and each gem kind (cut gem,
  cut glass, cabochon). Read back the decorated item and its
  decoration quality. Confirm or refute the one-decoration-per-
  gem-type-per-item rule, the weapon and armor exclusion, and
  the finished-goods-excludes-tools rule.
- Build the mechanism separation: a mechanism stockpile away
  from the jeweler, and a furniture stockpile by the jeweler
  holding statues, tables, and thrones. Confirm no mechanism
  is encrusted while the piles are separate.
- Record what untargeted setting actually does: queue an
  encrust job with several eligible items in reach and read
  back which item the setter picked. That read-back is the
  evidence for the exposure warning in the snapshot.
- Live bar: on the scratch fort, one encrusted piece of
  furniture, one encrusted finished good, and one encrusted
  ammo stack are read back with their decorations and
  qualities; no mechanism is encrusted while the separate
  stockpile exists; the target the setter picked is recorded.

### Phase 6: Gem windows

- Probe the gem window route: whether MakeWindow (127) is the
  on-site construction job, what inputs it takes (three cut
  gems), and what building it creates (WindowGem, 18). Add a
  Window kind to the placement route, following the
  `act_furniture.lua` pattern, or a dedicated action if the
  building needs one.
- Build one gem window from three cut gems of different colors
  on the scratch fort, read back its value as the sum of the
  gems, and deconstruct it and read back the three gems.
  Confirm or refute that a noble window mandate is not
  satisfied by it.
- Live bar: on the scratch fort, a gem window is built, read
  back with its three gems and its value, and deconstructed
  with all three gems read back in stock.

### Phase 7: Snapshot section, query route, and briefings

- Add the Gemcutting snapshot section (section 12.1) and the
  GET /v1/gemcutting route (section 12.2), with the per-type
  breakdown, the workshop records, the encrusted-item list,
  the window list, the mood reserve, and the trade readiness.
  Add the three briefing paragraphs (section 12.3): caravan,
  strange mood, first rough gem.
- Wire the suggestion and attention entries (section 12.4)
  through the existing assembler suggestion and the attention
  system. Measure the token cost against the live assembler
  at 7 dwarves and at the largest population the fort reaches,
  and correct the numbers in section 12.1 if they differ.
- Live bar: on the main fort, the snapshot's Gemcutting section
  prints true counts (rough by type, cut, large, cabochons,
  reserve) and the token cost is measured against the live
  assembler; GET /v1/gemcutting returns the full breakdown; a
  caravan-season run produces cut gems that reach the trade
  stockpile and read back there.

### Phase 8: Trade production, mood reserve, and the four piles

- Wire the trade production rule into the planner: the season
  before a caravan, the cutter cuts the low pile and the setter
  encrusts the trade goods, to the trade target from TRADING.md,
  with the mood reserve held out of every job.
- Build the four-tier gem piles (high, middle, low, rock
  crystal reserve) by the network rules in section 9, with the
  jeweler feeder and the links between them. This phase depends
  on the settings write and link actions from STOCKPILES.md
  phases 2 and 3; if those have not landed, this phase builds
  the piles category-flag-only and records what the missing
  links cost.
- Wire the encrust guard into the planner: mechanisms in their
  own stockpile, masterwork exposure named in the snapshot,
  repeat encrust jobs refused.
- Live bar: on the main fort, a caravan-season run cuts and sets
  to the trade target with the mood reserve intact and read
  back intact; the four piles exist with the right gems in
  each; no mechanism is encrusted during the run.

## 14. Cross-doc conflicts

Flagged here so the next reader does not have to find them by
accident. Each names the docs, the disagreement, and which one
this doc follows until the conflict is resolved live.

1. **Opportunities mechanism.** STONEWORKING.md section 12.4
   describes an opportunities section carrying at most 3
   entries. METALWORKING.md section 13.5 says no opportunities
   list exists in the code (no `opportunit` symbol in
   `src/dfagent_harness/`) and expresses opportunities through
   the snapshot suggestion and attention entries only. This doc
   follows METALWORKING.md. STONEWORKING.md's section 12.4
   should be corrected to match, or the list should be built.
2. **Who owns the jeweler's workshop.** STONEWORKING.md section
   3.4 and phase 7 treat the jeweler as a stone sink and plan to
   add it to the catalog with a Cut gems job. This doc owns the
   workshop and all its jobs, including stone cutting into
   cabochons. STONEWORKING.md phase 7 is a consumer requirement
   on this doc, not a second implementation. The catalog entry
   must be added once, by the gem phases, not twice.
3. **What "stone" counts.** `stocks.lua` counts ROUGH gems
   inside `stone_units`. Phase 1 of this doc removes ROUGH from
   the stone sum. STONEWORKING.md section 4.3 describes the
   stone count as it is today; after phase 1 lands, its
   description is stale and must be updated, or a reader will
   think rough gems vanished from the fort.
4. **Bin capacity for small gems.** STOCKPILES.md plans on 305
   small gems per bin. That number is taken from the bin table
   and is UNVERIFIED here; the live count in phase 1 or 8
   decides it. If the live count differs, STOCKPILES.md and
   this doc change together.
5. **Blocks per bin.** STONEWORKING.md section 15, question 5,
   records three disagreeing numbers (5, 10, 12) for blocks per
   bin, and STONEWORKING.md plans on 5 while STOCKPILES.md
   plans on 10. This doc does not touch blocks, but the same
   disagreement pattern applies to the small-gem bin count in
   conflict 4, and the same live count settles both.
6. **Cabochons and the trade target.** STONEWORKING.md section
   15, question 12, asks whether stone cut into cabochons counts
   against the trade target. This doc asks the same question for
   cut gems and encrusted goods: TRADING.md section 6.1 has no
   gem ranking at all, so the trade target computation cannot
   price gem goods until TRADING.md gains one. The ranking is
   TRADING.md's to add; this doc supplies the values in
   section 10.
7. **Glass has no owner.** This doc depends on raw glass as a
   training input, and the glass furnace as its source, but no
   glass industry doc exists. Until one lands, the glass
   boundary in section 2.7 is a stated gap, not a design: the
   harness cannot train on glass it cannot make.

## 15. Failure modes

The ways this industry breaks, in the order the fort will meet
them:

1. **Blind cut.** A CutGems job with no material named cuts the
   best rough gem in reach. The loss is silent: the cut gem is
   worth more than the rough gem, so nothing looks wrong, and
   the fort discovers it only when the diamond is gone. Guard:
   refusal 2, phase 3 material naming, snapshot exposure.
2. **Diamond into a table.** An untargeted setter sets the best
   cut gem into the nearest item, which is a wooden table. The
   loss is the decoration value the statue would have carried.
   Guard: pile separation, masterwork exposure warning, phase 5
   target control.
3. **Repeat pile-on.** A repeat encrust job, or a job queued
   while the last item was never hauled away, stacks every gem
   onto one mug. Guard: refusal 7, one job with one read-back.
4. **Mood with no gem.** The fort cut every rough gem, a mood
   demands one, and the dwarf goes insane or dies. Guard: the
   mood reserve, refusal 1, the strange mood briefing.
5. **Rock crystal cut.** The cutter cuts the fort's rough rock
   crystal, and the glass industry loses its crystal glass
   ingredient permanently for that stock. Guard: refusal 3,
   the separate reserve count in the snapshot.
6. **Ore cut.** A cabochon job consumes an ore boulder, and the
   fort loses a bar of metal for a polished stone. Guard:
   refusal 4, and the mason feeder rule from STONEWORKING.md.
7. **Mechanism gemmed.** An encrust-furniture job gems a
   mechanism. The trap still works, but the gem is spent on an
   item nobody sees. Guard: the separate mechanism stockpile,
   phase 5.
8. **Clothing decorated.** An encrust-finished-goods job
   decorates discarded clothing instead of a trade good.
   Guard: keep worn clothing out of the jeweler's feeder pile;
   the mechanism is an open question (section 16).
9. **Gem window for a mandate.** The fort builds a gem window
   against a noble window mandate, and the mandate fails.
   Guard: refusal 9, and the snapshot never counts a gem window
   toward a mandate.
10. **Invisible gems.** The fort mines gems and the snapshot
    never shows them, because ROUGH is inside the stone count
    and the agent never learns the industry exists. Guard:
    phase 1, the Gemcutting section, the first-gem briefing.
11. **Glass training with no glass.** The plan trains cutters on
    raw glass, but the glass furnace was never built and no raw
    glass exists. The cutter idles and the plan looks like a
    labor problem. Guard: the snapshot names raw glass on hand,
    and the suggestion never points at a glass job with no
    glass in stock.
12. **Large gem surprise.** The cutter produces a large gem
    instead of a cut gem, and the setter's next job fails for
    lack of a cut gem, because the large gem cannot be set.
    Guard: the snapshot counts large gems separately from cut
    gems, and the setter's fail-fast names the cut gem shortage
    instead of failing silently.

## 16. Open questions

All marked UNVERIFIED until a live probe or a wiki page settles
them.

1. The mapping from the twelve jeweler's workshop UI menu
   entries to the five runtime job types (CutGems 85, CutGlass
   86, EncrustWithGems 87, EncrustWithGlass 88, MakeWindow
   127). Phase 3 settles it.
2. What job items a CutGems job needs for the game to claim it,
   and how the material is named in them. Phase 3 settles it.
3. What `MakeGem` (236) does, at which workshop, and with which
   inputs. Phase 3 settles it.
4. Whether `MakeWindow` (127) is the on-site gem window
   construction job, a workshop job, or both. Phase 6 settles
   it.
5. Which job type the "Polish stones" menu entry creates, and
   whether cutting stone uses CutGems with a stone material.
   Phase 3 settles it.
6. Whether a manager order for CutGems dispatches without a
   manager noble appointed, and whether the order can name a
   gem or always cuts blind. Phase 3 settles it.
7. The live cutting ratios: what share of rough gems become cut
   gems, large gems, and gem crafts in 0.47.05, and whether
   large gem cutting works at all. Phase 4 settles it.
8. The live base values: rough 6, cut 20, large 10, craft 10,
   decoration 10, and the masterwork large gem plus 30. Phase 4
   settles them by read-back.
9. Whether cut gems have no quality level in 0.47.05, and
   whether cutter skill changes only speed and large gem and
   craft quality. Phase 4 settles it.
10. Which rough gems always cut as cabochons, and by what rule.
    Phase 4 settles it.
11. Whether the one-decoration-per-gem-type-per-item rule holds
    in 0.47.05, and whether weapons, metal armor, and tools are
    excluded from encrusting as the wiki says. Phase 5 settles
    it.
12. Whether encrusted ammo has any combat effect, or only value.
    Phase 5 settles it by reading the combat result, or records
    that no effect was found.
13. Whether the game counts placed furniture in `stocks.lua` the
    way it counts placed beds (STONEWORKING.md section 15,
    question 10): if so, the encrusted-item and gem-window
    counts in the snapshot must use the accessible probe, not
    the stocks total.
14. How the harness keeps discarded clothing out of the
    jeweler's feeder pile before stockpile settings writes
    exist, and whether a worn-clothing filter is possible at
    all. Phase 5 or 8 settles it.
15. Whether the snapshot's `by_material` top list reliably
    carries gem counts once ROUGH and SMALLGEM enter
    `add_mat`, or whether the Gemcutting section needs its own
    per-type read. Phase 1 settles it.
16. Whether rough gems are available for trade in 0.47.05, or
    only cut gems, large gems, and gem crafts, as the v50 wiki
    says. A caravan-season read of the trade goods settles it.
17. Whether any dwarf in the fort has gem cutting or gem setting
    skill today, and whether any migrant arrived with it.
    UNVERIFIED until the game is back up and the dwarves read
    lists skills.
18. Whether the current fort's map has any gem-bearing stone at
    all, and whether kimberlite (the diamond host) is among
    it. UNVERIFIED until gems are mined and read, or a
    kimberlite boulder is identified; the survey can never
    answer this.

## 17. Sources

Wiki pages, all from the CURRENT (v50) wiki via the local export
(`~/workspace/df-wiki-export/dfq.py`, hybrid search), used only
to find pages and never as authority for 0.47.05. Every v50
claim taken from them is marked UNVERIFIED in the text.

- Gem industry (3,904 words): the workshop, obtaining gems,
  cutting outcomes, large gems, gem crafts, perfect gems, gem
  setting, glass, gem windows, industry management, the
  stockpile and Workers-tab control method, the repeat-job
  pile-on, discarded clothing.
- Gem (5,901 words): 130 kinds including 3 glass, 127 gems, 57
  ornamental, 58 semi-precious, 4 precious, 8 rare; the 5
  percent large gem and craft rate (1 craft per 8 large gems);
  glass ratios (33 percent, 11 crafts per 16 large gems);
  base values (rough 6, cut 20, large 10); the green zircon
  worked example; rock crystal reserve for crystal glass;
  gizzard stones; the full variety table with values and hosts.
- Jeweler's workshop (1,046 words): shortcut b-o-j, job
  requirement, construction, the twelve-entry menu, cutting
  specific gems, the masterwork decoration note, cut gems have
  no quality, ordinary stone cuts to cabochons, any boulder can
  be cut, flux and obsidian cabochons 2 to 3 times as valuable.
- Gem cutter (1,106 words): cutting more than triples rough
  value, masterwork decoration nearly 12 times rough value,
  cutter skill affects speed and large gem and craft quality
  only, training on stone and glass.
- Gem setter (1,131 words): encrusts furniture, finished goods
  excluding tools, and ammo including siege ammo; cannot
  encrust weapons and armor except cloth armor; large gems
  cannot be set; the stockpile, link, and forbid control
  method; training on common stone.
- Window (v50 page): gem window built on site from three cut
  gems, value is the sum of the gems, no quality levels, mixed
  colors flash, disassembly returns the gems, toppled not
  destroyed, noble mandate not satisfied, needs a floor.

0.47.05 raws, read from the install 2026-11-27
(`third_party/df_47_05/raw/objects/`):

- `inorganic_stone_gem.txt`: 127 gem types; material value
  counts (2: 38, 3: 3, 10: 16, 15: 5, 20: 46, 25: 2, 30: 5,
  40: 4, 60: 8); 180 `CLUSTER_SMALL` entries; 8 `CLUSTER_ONE`
  entries for the rare gems inside faint yellow diamond, ruby,
  and sapphire.

Live runtime enums, enumerated from DF 0.47.05 + DFHack
0.47.05-r8 on 2026-11-25
(`tests/fixtures/runtime-enums-0.47.05-r8.json`):

- Job types: MakeRawGlass 82, CutGems 85, CutGlass 86,
  EncrustWithGems 87, EncrustWithGlass 88, MakeWindow 127,
  MakeGem 236.
- Item types: SMALLGEM 2, ROUGH 4, WINDOW 16, GEM 44.
- Labors: CUT_GEM 51, ENCRUST_GEM 52. Skills: CUTGEM 31,
  ENCRUSTGEM 32. Workshop type: Jewelers 4. Building types:
  WindowGem 18, WindowGlass 17.

Harness state verified against the repo 2026-11-27: actions.py
`WORKSHOP_CATALOG` (four workshops, no jeweler), `JOB_SPECS`
(no gem jobs), `manager_order_create` and `act_order.lua`
(takes a `df.job_type` name), `act_job.lua` (job items only for
reaction jobs; a bare job is never claimed), `build_furniture`
and `FURNITURE_ITEMS` (no Window kind), `materials.py` (no gem
jobs), `act_labor.lua` (any labor by name), `stocks.lua`
(`stone_units` includes ROUGH; `by_material` excludes ROUGH,
SMALLGEM, and GEM), `survey.py` (veins unidentified),
`placement.py` (no jeweler affinity row), `assembler.py`
(`_buildings`, `_stocks`, `_materials`, the suggestion at line
71, the token accountant), `briefings.py` (`caravan`,
`strange_mood`, `unit_death` kinds), `catalog.py` (Gems
stockpile category), diary.py (the jeweler warning),
docs/STONEWORKING.md (stone sink, cabochons, mechanisms as
furniture, the encrust hazard, the opportunities conflict in
section 14), docs/METALWORKING.md section 13 (the presentation
precedent this doc follows), docs/TRADING.md (elves accept all
rough and cut gems; section 6.1 has no gem ranking),
docs/STOCKPILES.md (Gems stockpile, bins, no pile better than a
bad pile), docs/LABOR.md (no gem labor assigned), GOAL.md and
the coordinator log 2026-11-27 (the presentation constraint).

The daemon and game were down for a VM replacement at the time
of writing (2026-11-27 ~19:37 PT), so no live snapshot was read.
Every live value in this doc is marked UNVERIFIED with its
proving bar in section 13.
