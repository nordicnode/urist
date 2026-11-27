# Site selection (scored placement)

Status: design doc. Implementation queued after item 19 (server split,
landed 947b709). This doc is the design record for that implementation
phase; the implementation verifies live and does not re-derive the
design from memory.

## 1. The problem

Placement today verifies and ranks by the wrong thing. `find_sites`
(`src/dfagent_harness/placement.py`) runs five verification layers
(terrain, occupancy, clear, overlap, reachability) and then sorts the
verified sites by distance from the fort centre. The nearest site wins.
Distance is a bad proxy for good:

- The nearest 3x3 can be in the open, inside marksdwarf range of a
  hostile that has not been seen yet, on the main corridor every dwarf
  walks, next to a workshop whose noise keeps the bedroom's sleeper
  awake, or on poor soil that cuts a farm's yield by 75%.
- The model gets `why: "4 tiles north east of the fort"` and no reason
  to prefer one site over another. It cannot tell a good site from a
  merely free one, so it picks the nearest — and the harness, which
  knows better, stays silent.

Scored placement keeps the five verification layers exactly as they
are (a site must still be verified free + reachable before it is
scored) and adds a second pass: `score_site()` ranks the verified
candidates by how good they are for the kind being placed, with hard
gates for the things that must never be placed and weighted factors
for everything else. The model sees the top 3 per kind with a
one-line plain-words why each — never raw columns, radii, or weights.

This is harness heavy-lifting with the model's freedom intact
(docs/HARNESS_ROLE.md §6.3): the harness scores, the model chooses
among the top 3. A scored ranking is a suggestion, not an order; the
model may still pick a lower-ranked site (for a tactic the harness
does not know about) and the harness must not punish it for doing so
— the score is information, and the eval framework's guidance
ablation measures whether it helps.

## 2. Wiki evidence

Every mechanics claim below comes from the DF wiki export
(`~/workspace/df-wiki-export/dfq.py`, hybrid search, 2026-11-27).
Nothing in this section is from memory. Where the wiki does NOT
support a rule the original queue assumed, the doc says so plainly
(§3.2) instead of inventing a requirement.

### 2.1 Threat radius: 20 tiles, three-dimensional

> "Crossbows shoot bolts as their ammunition, and marksdwarves will
> engage targets up to 20 tiles distant, provided they have a clear
> line of sight to them. Z-levels up *or down* count equally
> *against* the distance when measuring this range, subtracting from
> the total x-/y-axis distance, so shooting from a high wall or..."
> — [Crossbow](https://dwarffortresswiki.org/index.php/Crossbow)

A hostile archer threatens any dwarf standing within 20 tiles,
measured in three dimensions: the z-distance subtracts from the
same 20-tile budget as the horizontal distance ("shooting from a
high wall or tower effectively *reduces* that 20-tile maximum"),
so the range is **20 tiles, 3D Manhattan distance**
(|dx| + |dy| + |dz| ≤ 20). A hostile 10 tiles away horizontally
and 10 levels above is 20 tiles away in range terms. Line of sight
is not modelled: the harness cannot cheaply prove line of sight
through walls, so the gate is conservative — any hostile within 20
tiles Manhattan 3D refuses the site, whether or not a wall happens
to stand between them. A walled site inside the radius is still
refused; the wall is not a guarantee the wiki gives us.

### 2.2 Noise: distance only, and it is a cube

> "Neither walls nor doors will insulate dwarves from noise -
> distance and how loud a job is are the only factors determining
> whether a dwarf's sleep will be disturbed."
> — [Noise](https://dwarffortresswiki.org/index.php/Noise)

> "* Digging - 8 tiles
> * Wood cutting - 8 tiles
> * Engraving - 4 tiles
> * Fortification carving - 4 tiles
> * Removing constructions - 8 tiles"
> — [Noise](https://dwarffortresswiki.org/index.php/Noise)

> "Noise radiates across z-levels in the shape of a cube, in all 6
> directions (north/south, east/west, *and* up/down), so noise that
> travels 4 tiles will generate noise in a 9x9 pattern on 9
> successive floors."
> — [Noise](https://dwarffortresswiki.org/index.php/Noise)

> "Putting all your bedrooms 8 levels or lower below ground
> eliminates noise from wood cutting (*and all other relevant
> noise-related concerns, that being beside the point*)."
> — [Noise](https://dwarffortresswiki.org/index.php/Noise)

> "Because noise generated from certain jobs (especially mining and
> woodcutting) can bother sleeping dwarves, doing these jobs within
> 8 tiles of a sleeping dwarf should be avoided (see noise for more
> information)."
> — [Quickstart guide](https://dwarffortresswiki.org/index.php/Quickstart_guide)

> "While dwarves walking through a sleeping dwarf's room (even over
> their heads) will not cause noise, which is important for bedroom
> design."
> — [Noise](https://dwarffortresswiki.org/index.php/Noise)

Consequences for scoring:

- Noise distance is **Chebyshev distance in 3D** (a cube, not a
  sphere): a bedroom 7 tiles away horizontally and 7 levels below a
  dig is inside the noise cube, not outside it. The room factor
  (§4.3) uses Chebyshev distance to the nearest noise source.
- The radii are 8 for digging / woodcutting / removing constructions
  and 4 for engraving / fortification carving. A room inside 8 tiles
  (Chebyshev) of a digging or woodcutting source scores 0 on the
  noise factor; inside 4 of an engraving source likewise.
- Walls and doors give no noise protection, so enclosure (§4.3)
  must not be counted as noise protection — it is a separate
  privacy factor.
- Dwarves walking through a room cause no noise, so through-traffic
  is not a noise penalty for bedrooms (it is still a traffic penalty
  for workshops and stockpiles — §4.1 — because a workshop or
  stockpile on the main corridor blocks hauling, not because it is
  loud).

### 2.3 Farm plots: soil, light, and yield

> "Building uses no resources, and can only be done on soil or
> muddied rock. Mud-free stone will not allow the building of a
> farm plot on top."
> — [Farming](https://dwarffortresswiki.org/index.php/Farming)

> "Depending on where the farm plot is constructed, different crops
> may be planted. Farm plots built Above Ground are not suitable
> for Subterranean crops, and vice versa."
> — [Farming](https://dwarffortresswiki.org/index.php/Farming)

> "An underground plot that has been exposed to sunlight will never
> grow underground plants again. It may be necessary to remove the
> plot and rebuild it so that you can select aboveground crops to
> plant. Farm plots which are partially belowground and aboveground
> will never be fully planted."
> — [Farming](https://dwarffortresswiki.org/index.php/Farming)

> "Farm tiles located in soil layers, except any which are part of a
> cavern, are considered 'poor' (even if covered in mud) and will
> reduce all yields by 75%; farming any where else underground,
> including muddied stone in *any* stone layer, will not reduce
> yields."
> — [Farming](https://dwarffortresswiki.org/index.php/Farming)

> "Additionally, some aboveground biomes (such as mountains and
> glaciers) are unsuitable for farming and will never grow crops."
> — [Farming](https://dwarffortresswiki.org/index.php/Farming)

> "Aboveground farms can simply be built on the surface (though
> this exposes your farmers to attack); subterranean farms will
> need to have a suitable area dug out underground."
> — [Farming](https://dwarffortresswiki.org/index.php/Farming)

> "Keep your farms *small* – 2x2, up to 4x4, or so. Farms are
> surprisingly productive. ... having several small farms lets you
> diversify your crops. (Each farm plot can only grow one kind of
> plant per season.)"
> — [Farming](https://dwarffortresswiki.org/index.php/Farming)

> "If you do not have a potash stockpile near your farm plots,
> your legendary farmers may spend all of their time hauling single
> bars of potash from all the way on the other side of your
> fortress, rather than growing food."
> — [Farming](https://dwarffortresswiki.org/index.php/Farming)

> "You can grow surface plants indoors by channeling out the roof
> above the desired plot and then constructing a floor over the
> open space. Doing this changes the tile from Dark to Light,
> despite there being a roof... A plot with mixed Light and Dark
> tiles may show plants as 'available' when only a tiny fraction
> of the tiles in the farm are valid for planting them."
> — [Farming](https://dwarffortresswiki.org/index.php/Farming)

Consequences for scoring:

- Soil and light are already probed: `find_sites(kind="farm_plot")`
  runs the probe with `farm=True`, and each verified site carries
  its soil/light/biome summary (`site["farm"]`). The scorer
  consumes that summary — it does not re-derive soil or light.
- A mixed Light/Dark footprint is a real defect (never fully
  planted), so the light factor penalises mixed footprints hard
  and the why names it.
- Poor soil (-75% yield) is a scored factor, not a gate: a poor-soil
  site is still a site, just a bad one. The scorer must surface the
  yield penalty in words ("poor soil, a quarter of the yield").
- Above-ground farms expose farmers to attack — that is the threat
  factor (§4.1), not a separate farm rule. A greenhouse (walled
  soil, or channelled + floored) is the wiki's answer to exposed
  above-ground farming; the scorer rewards an enclosed above-ground
  plot for above-ground crops, because enclosure there means
  protection, not just privacy.
- Small plots are better (2x2–4x4): the default farm_plot size is
  3x3, which is already in the sweet spot. The size factor (§4.3)
  does not push farms bigger.

### 2.4 Stockpiles: what needs cover, and what must not have it

> "Food will never spoil while in a stockpile, although it may
> attract and be eaten by vermin."
> — [Stockpile](https://dwarffortresswiki.org/index.php/Stockpile)

> "Many players prefer to place this stockpile outside their
> cavern, usually a small distance from the entrance, as rottable
> items on tiles that are Outside Light Above Ground do not
> generate miasma."
> — [Stockpile](https://dwarffortresswiki.org/index.php/Stockpile)

> "If placed on a Subterranean tile, decaying items will generate
> miasma, which will spread through your fortress and generate a
> small unhappy thought in any dwarf passing through it. For this
> reason, it is sensible to build doors (preferably several,
> separated by a few tiles to create an airlock) to all of your
> indoor refuse stockpiles."
> — [Stockpile](https://dwarffortresswiki.org/index.php/Stockpile)

> "It's a good idea to design all (or at least, many) of these
> workshops and their stockpiles around each other."
> — [Stockpile design](https://dwarffortresswiki.org/index.php/Stockpile_design)

> "Ingredients: Store things that are cookable but not edible,
> like milk and quarry bush leaves, near kitchens."
> — [Stockpile](https://dwarffortresswiki.org/index.php/Stockpile)

> "Also include a barrel stockpile near your still to ensure a
> steady supply of empty barrels."
> — [Stockpile design](https://dwarffortresswiki.org/index.php/Stockpile_design)

> "Finished goods stockpiles near a Trade Depot that includes
> crafts that you want to sell..."
> — [Stockpile](https://dwarffortresswiki.org/index.php/Stockpile)

Consequences for scoring:

- Food does **not** spoil in a stockpile, so there is no
  spoilage-based cover requirement for food stockpiles. Any design
  that gates food stockpiles on cover is inventing a rule the wiki
  does not support (§3.2).
- Refuse is the inverse of cover: a refuse stockpile **must** be in
  the open sky (Outside Light Above Ground) or it generates miasma
  indoors. This is the one stockpile hard gate, and it runs the
  opposite way from the naive "everything needs a roof" rule.
- Adjacency is the stockpile scorer's main factor: the wiki's
  design advice is explicit (workshops and their stockpiles around
  each other; ingredients near the kitchen; barrels near the still;
  finished goods near the depot). The affinity table (§4.2) encodes
  exactly these pairs.

### 2.5 Caverns: breaching one opens a front

> "Opening the caverns will make it possible for your fortress to
> be attacked by forgotten beasts, which range in lethality from
> 'not much' to 'nigh unkillable'."
> — [Cavern](https://dwarffortresswiki.org/index.php/Cavern)

> "One thing you really have to watch out for is having your main
> stairwell lead into a cavern. It doesn't have to be so walking
> creatures can get in, but just so there's an open hole. Any
> hostile creature sitting under your open stairway will spook any
> dwarves trying to use it, causing a flood of job cancellation
> messages as they keep trying to reach their destination. When
> this happens, it can lead to all your dwarves starving themselves
> to death. Only build stairs on the side, preferably with a hatch."
> — [Cavern](https://dwarffortresswiki.org/index.php/Cavern)

> "Leaving caverns open is always an invitation to trouble, and
> monster slayers only reduce this risk slightly. Be sure to keep
> whatever access routes they use well-guarded with traps, doors,
> and dwarven guards in order to intercept the jabberer or cave
> dragon that will inevitably slip on in."
> — [Monster slayer](https://dwarffortresswiki.org/index.php/Monster_slayer)

> "NOTE: walls come with floors above them, which means that
> creatures may still spawn on top of the wall and interrupt jobs,
> or not spawn where you want them to (if you are trying to wall
> off most entrances and leave a few designated entrances with cage
> traps). So fortifications without floors on top of them should be
> built instead to seal an entrance from ground creatures."
> — [Cavern](https://dwarffortresswiki.org/index.php/Cavern)

> "The first cavern usually has few hazardous monsters, apart from
> the occasional giant olm or toad and giant cave spiders, but just
> one giant bat can destroy an early fort, and uninvited guests
> will wander in sooner or later. The subsequent caverns will
> become increasingly fun, so don't dig too deep without making
> adequate preparation."
> — [Cavern](https://dwarffortresswiki.org/index.php/Cavern)

Consequences for scoring: a dig that breaches a cavern is a hard
gate by default (§7). A cavern breach is not a scoring demerit —
it is a refusal, because the breach itself is the threat: it opens
a second front the fort is not defending, and a hostile under an
open stairway can starve the fort through cancellation spam. The
only exception is a deliberate, guarded cavern access (a flag the
planner sets when it wants cavern access — see §7), and even then
the access must be on the side with a hatch, never the main
stairwell.

### 2.6 Traps: the enemy's shortest path, and servicing

> "Enemies will tend to take the shortest path to their target, be
> that your dwarves, an animal, a single valuable item or a child
> to be kidnapped (in the case of thieves), or a door or statue (in
> the case of building destroyers). Putting traps at the inner
> corner of a turn in a hallway, or in front of a door or the start
> of a stairway - or just lining a long hall - gives you the
> highest chance of a victim walking over the trap."
> — [Trap](https://dwarffortresswiki.org/index.php/Trap)

> "Remember that caravan wagons cannot pass over traps, although
> traders with pack animals can."
> — [Trap](https://dwarffortresswiki.org/index.php/Trap)

> "You also have to think about servicing the traps. Stone traps
> need to be reloaded, cage traps need to be collected, and weapon
> traps often need to be un-jammed... Planning the traps so they
> are close to (sealed?) access allows your mechanics to travel
> less distance to get the job done."
> — [Trap](https://dwarffortresswiki.org/index.php/Trap)

> "Making *two* similarly trapped paths, with a hatch or bridge or
> other control system that limits which one is 'open' to
> outsiders, keeps your fortress open while allowing your mechanics
> to safely service the other area that is currently sealed."
> — [Trap](https://dwarffortresswiki.org/index.php/Trap)

> "Cage traps will also alert you to ambushes when triggered by
> hidden invaders, making them a useful forward defense mechanism."
> — [Trap](https://dwarffortresswiki.org/index.php/Trap)

Consequences for scoring: traps are scored on the opposite of
every other kind. They want the enemy's path (the approach from
the entrance to the fort), they want doors / stairway starts /
hallway corners, and they want to be close enough to service —
but not on the caravan's path (wagons cannot pass traps). The
trap factor set (§4.4) is therefore path position, door/stair
proximity, and service distance. Cage traps double as an ambush
alarm, so a forward (outer) cage-trap site scores higher than an
inner one for the alarm role — the subtype (`trap=cage` vs
`trap=weapon`) decides which.

### 2.7 Rooms: enclosure is privacy, size is value

> "As to size, all a dwarf needs to sleep is a 1-tile bed,
> anywhere. However, to be happy, a dwarf wants their own room
> with a bed, and a chest and a cabinet to put stuff in. Dwarves
> consider it a bonus if the room is enclosed by 4 walls (or 3
> and a door) for privacy."
> — [Bedroom design](https://dwarffortresswiki.org/index.php/Bedroom_design)

> "Dwarves suffer no penalties for having other Dwarves travel
> through their bedrooms even when they are sleeping. They also
> don't require doors."
> — [Bedroom design](https://dwarffortresswiki.org/index.php/Bedroom_design)

> "The 3x3 rooms are easy to get up to decent or higher to keep
> your most useful dwarves happy as clams."
> — [Bedroom design](https://dwarffortresswiki.org/index.php/Bedroom_design)

> "If you want an even more decentralized and calm traffic
> pattern, put tables and chairs in all the private rooms;
> dwarves will prefer to eat in their quarters."
> — [Bedroom design](https://dwarffortresswiki.org/index.php/Bedroom_design)

> "Stress considerations: furniture from valuable materials such
> as flux, obsidian, or various metals helps. Decorating the walls
> and floors is also an easy way to make a dining hall more
> valuable."
> — [Dining room](https://dwarffortresswiki.org/index.php/Dining_room)

Consequences for scoring: a room's quality comes from enclosure
(4 walls, or 3 + a door — a privacy bonus), size (3x3 reaches
decent quality easily; 1 tile is enough to sleep but not to be
happy), and quiet (§2.2). Through-traffic is not a penalty for
bedrooms (the wiki says so), so the traffic factor (§4.1) does not
apply to rooms — rooms get the noise factor instead. Dining rooms
want proximity to food and drink (the stockpile affinity, §4.2).

### 2.8 Aquifer: digging through floods the fort

> "Having made an initial hole in the aquifer, you may wish to
> punch another larger hole through, say for example to grow wild
> strawberries in the caverns. Or you may simply want an
> additional (natural stone!) staircase. Once you have access from
> below this is much easier than digging from above, and it has
> the..."
> — [Aquifer](https://dwarffortresswiki.org/index.php/Aquifer)

> "Dig downstairs next to your 2x2 stairs. Dig up/down stairs
> into the aquifer below. Use [pause]. One-Step! When digging the
> up/down stair into the aquifer, pause the game and use One-Step
> to see the revealed tile below the first aquifer level before it
> gets flooded."
> — [Double-slit method](https://dwarffortresswiki.org/index.php/Double-slit_method)

The aquifer rule is already a hard gate in `digging.py`
(`HAZARD_CLASSES = ("magma", "aquifer", "water")`, 3-level
lookahead down). It stays. The doc records it here so the dig
section (§7) does not have to re-derive it.

### 2.9 Traffic: designations steer dwarves

> "The T traffic menu sets **traffic areas**, which are zones used
> to manipulate the movements of dwarves."
> — [Traffic](https://dwarffortresswiki.org/index.php/Traffic)

Traffic designations are the game's own mechanism for keeping
dwarves off a path. The harness does not set traffic areas yet
(that is a later phase, if ever — the model does not ask for them),
but the scoring needs the same concept: a site on the path every
dwarf walks is a bad site for a workshop or stockpile, because it
blocks hauling and congests the fort. The harness measures traffic
from data it already has (§4.1), not from traffic designations.

### 2.10 Workshops: no cover requirement

The [Workshop](https://dwarffortresswiki.org/index.php/Workshop)
page gives no roof or cover requirement: workshops are built
outdoors whenever the player wants, and the only
location-sensitive variants are the magma workshops, which
require magma access. A workshop in the open is exposed (threat
factor) but not invalid. See §3.2.

## 3. Design: score_site()

### 3.1 Shape

```python
score_site(site: dict, kind: str, ctx: ScoreContext) -> dict
# -> {"score": 0..100, "why": "one plain-words line",
#     "factors": {"threat": "far from any hostile", ...},
#     "refused": False, "reason": None}
# A refused site returns score 0, refused True, and reason in
# plain words ("within 20 tiles of a hostile archer").
```

`score_site()` lives in `placement.py` and is a pure function:
given a verified site and a context, it returns a score. It reads
no game state itself and issues no RPC calls — the caller
(`find_sites`, `daemon.get_placement`) builds the context once
per search from state the daemon already holds. Pure means it is
testable offline with fabricated contexts, which is where most of
its tests live (§8).

`ScoreContext` (a dataclass in `placement.py`) carries:

- `threats`: list of hostile positions `[(x, y, z), ...]` — from
  the state's threat list (hostile units with positions). Empty
  when no hostiles are known.
- `buildings`: list of `(type, subtype, pos)` — from the state's
  buildings list. Used for industry grouping, door/stair
  proximity (traps), and workshop positions (noise sources).
- `stockpiles`: list of `(subtype, pos, size)` — from the state's
  stockpile list where the subtype is known (the stockpile section
  of the state carries categories). Used for adjacency.
- `zones`: list of `(subtype, pos)` — from the state's zone list.
  Used for room adjacency (bedroom near dining) and for not
  double-booking a zone.
- `noise_sources`: list of `(pos, radius)` — the current dig box
  (radius 8), woodcutting designations if tracked (radius 8), and
  engraving workshops (radius 4). Phase 1 uses the dig box and
  workshop positions with a conservative radius of 8 for every
  workshop; per-job-type radii are a follow-up when designation
  tracking exists (§6.4).
- `traffic_heatmap`: dict of tile -> count, built from
  `store.unit_history` `pos_json` samples (see §4.1). Built once
  per search by the caller, not by `score_site()`.
- `centre`: the fort centre (x, y), `surface_z`: the surface level,
  `entrance`: the fort entrance position (the Surface area entry /
  the derived dig site), `dining_pos` / `food_pos` / `drink_pos`:
  the dining room and food/drink stockpile positions where known
  (from the buildings/stockpile lists; None when unknown).
- `farm`: the probe's farm summary for this site (soil, light,
  biome, poor) — passed through from `find_sites`, only for
  `kind == "farm_plot"`.

A missing context field is never an exception: the factor that
needs it scores neutral (50) and the why says what was unknown
("no hostiles seen", "no food stockpile known"). A scorer that
crashes on a missing field is a bug — the malformed-input tests
(§8) pin this.

### 3.2 The cover correction (read this before implementing)

The queue for this phase said the hard gates include
"stockpile/workshop/zone in open sky when the kind needs cover".
The wiki evidence (§2) does **not** support a general cover
requirement for those kinds:

- Workshops have no cover requirement (§2.10).
- Food stockpiles do not spoil in a stockpile, so cover does not
  protect food (§2.4).
- Zones (meeting, dining, bedroom) have no cover requirement; a
  room's quality comes from enclosure and size, not from having a
  roof (§2.7).

The only hard cover/light rules the wiki supports are:

- **Farm plots**: the light rule (Dark for subterranean crops,
  Light for above-ground; a mixed footprint never fully plants;
  an underground plot exposed to sunlight is ruined for
  underground crops). This is already enforced by the probe
  (`farm=True`); the scorer consumes the probe's summary as a
  factor (§4.3), it does not add a new gate.
- **Refuse stockpiles**: open sky is REQUIRED (miasma indoors).
  This is a hard gate, and it runs the opposite way from the
  naive rule (§3.3).

Everything else treats open sky as a **scored exposure factor**,
not a gate: a site in the open scores lower on shelter (it is
visible to archers, and the dwarf working there is exposed), and
a site under cover scores higher — but an open-sky workshop is
still a workshop, and the model may still choose it. The design
deliberately corrects the queue's assumption here rather than
implementing a rule the game does not have. If a later live run
shows a cover-related failure the wiki does not predict (for
example, weather damage to a specific stockpile category), that
failure is logged as a new finding and the gate is revisited —
it is not assumed now.

### 3.3 Hard gates (refuse, score 0, reason in plain words)

Hard gates run before any weighting. A gated site is returned in
`blocked` with its reason, never in `sites` — the same contract
`find_sites` already keeps (a site is verified only when free AND
reachable; a gated site is not a candidate).

| Gate | Applies to | Rule | Wiki |
| --- | --- | --- | --- |
| Archer radius | workshop, stockpile, zone, farm_plot, furniture, room | Any hostile within 20 tiles 3D Manhattan (|dx|+|dy|+|dz|) of the site → refuse ("within 20 tiles of a hostile — a marksdwarf can shoot this far") | §2.1 |
| Refuse miasma | stockpile, subtype=refuse | Site is not open sky (not Outside Light Above Ground) → refuse ("refuse rots indoors — miasma; it needs open sky") | §2.4 |
| Farm light | farm_plot | Probe's farm summary says the footprint cannot grow the requested crop class (mixed Light/Dark, or wrong light class for the subtype) → refuse ("half this plot would never grow") | §2.3 |
| Cavern breach | dig (§7) | Dig path hits a cavern-space tile → refuse unless deliberate guarded access | §2.5 |
| New surface entrance | dig (§7) | Dig opens a new hole to open sky where no entrance exists → refuse unless it IS the planned entrance | §2.5 |
| Aquifer / water / magma | dig (§7) | Already a gate in `check_dig_site` (HAZARD_CLASSES, 3-level lookahead) — stays, unchanged | §2.8 |

Traps are exempt from the archer gate: a trap site is unmanned
(the builder visits briefly to build and service it), and traps
are built ahead of an attack, not during one. Builder exposure
is instead a scored factor for traps (§4.4) — a trap far from the
fort's protected interior scores lower on service distance, which
is the honest way to price the same risk. If a hostile is already
within 20 tiles when a trap is being placed, the fort is under
attack and the model is making an emergency decision; the scorer
must not refuse the only defence the fort has.

The farm-light gate needs the requested crop class, which comes
from the subtype (`farm_plot` subtype `subterranean` or
`above-ground`, §5). Without a subtype the gate cannot run and the
scorer says so in the factors ("crop class unknown — light not
checked").

### 3.4 The factor table (weights sum to 100 per kind)

Each factor is measured from the context (§3.1) and scored 0–100
on its own; the kind's score is the weighted sum, rounded to an
integer. Weights are design choices, not wiki facts — they live in
code (`PLACEMENT_WEIGHTS` in `placement.py`), never in the model's
view, and the eval framework's guidance ablation (§9) is how they
earn their keep: if a weight makes the model place worse, it
changes.

Common factors (every kind except where noted):

| Factor | What it measures | 0 | 100 |
| --- | --- | --- | --- |
| threat_distance | 3D Manhattan distance to the nearest hostile, capped at 20+ (beyond 20 is "no threat seen") | hostile within 20 (gated, §3.3) — below the gate this factor is moot | no hostile within 40, or no hostiles known at all |
| shelter | whether the site is under cover (Inside, or roofed) vs open sky | open sky | under cover |
| adjacency | distance to the nearest affinity target (§4.2) for this kind/subtype | no affinity target known, or >25 tiles away | within 5 tiles |
| traffic | foot-traffic heat at the site (§4.1) — for workshops/stockpiles/zones/furniture, high traffic is bad (blocking the corridor); for traps it is inverted (see §4.4); rooms do not use it (§2.7) | on the busiest tiles | no recorded foot traffic nearby |
| z_fit | \|site z − fort main level z\| (the most common building z) | 4+ levels away | same level |

Per-kind factors:

| Factor | Kinds | What it measures | 0 | 100 |
| --- | --- | --- | --- | --- |
| industry_grouping | workshop | distance to the nearest same-industry workshop (carpenter near carpenter, mason near mason; the industry of a workshop is its subtype) | isolated, >20 tiles from any same-industry workshop | within 5 tiles of a same-industry workshop |
| noise_distance | room (bedroom/dining/office) | Chebyshev 3D distance to the nearest noise source (§2.2), radius 8 (dig/woodcutting) or 4 (engraving) | inside the noise cube | 8+ tiles (Chebyshev) from every source, or 8+ levels below ground |
| food_drink_proximity | room (dining especially; bedroom secondarily) | distance to the nearest food stockpile / drink stockpile / dining room | >25 tiles from food and drink | within 5 tiles of food and drink |
| workplace_proximity | room (bedroom) | distance to the fort's workshop cluster (the centroid of workshop positions) — phase 1 proxy for "near the dwarf's workplace"; per-dwarf assignment is not tracked yet (§6.4) | >25 tiles from the workshop cluster | within 8 tiles of the workshop cluster |
| enclosure | room, farm_plot (above-ground) | share of the footprint's perimeter that is solid wall/floor (from the probe extension, §6.2) — for rooms this is the privacy bonus (§2.7); for above-ground farms this is the greenhouse (§2.3) | open on all sides | enclosed on all four sides (or 3 + a door, which the probe reports as enclosed) |
| size_fit | room | footprint vs the kind's preferred size (bedroom 3x3 is the sweet spot, §2.7; bigger is better for a noble's room — out of scope for phase 1) | 1x1 (sleepable, not happy) | 3x3 |
| soil_quality | farm_plot | probe's farm summary: poor soil (-75% yield) vs full yield (§2.3) | poor soil | full-yield ground (muddied stone, or cavern soil) |
| light_match | farm_plot | probe's farm summary: light class matches the requested crop class; mixed Light/Dark penalised hard (§2.3) | mixed footprint | uniform correct light |
| path_position | trap | distance to the enemy approach path — the segment from the fort entrance to the fort centre (straight-line approximation; the harness has no tile pathfinder, §6.4) | >15 tiles from the approach segment | on the approach segment |
| door_stair_proximity | trap | distance to the nearest door, stairway start, or hallway corner (from the buildings list; a corner is approximated by a tile where the corridor turns — phase 1 uses doors and stairways only, §6.4) | no door or stairway within 15 tiles | within 2 tiles of a door or stairway start |
| service_distance | trap | distance from the site to the fort centre (the mechanic's base) — closer is easier to service (§2.6) | >25 tiles from the centre | within 8 tiles of the centre |

Weights per kind (each row sums to 100):

| Kind | threat | shelter | adjacency | traffic | z_fit | extras |
| --- | --- | --- | --- | --- | --- | --- |
| workshop | 20 | 10 | 25 | 15 | 10 | industry_grouping 20 |
| stockpile | 20 | 10 | 30 | 15 | 10 | — (subtype sets the affinity target; refuse inverts shelter, §3.3) |
| zone | 15 | 10 | 25 | 15 | 10 | subtype extras 25 (see below) |
| farm_plot | 25 | 5 | 20 | 10 | 5 | soil_quality 15, light_match 20 |
| furniture | 15 | 10 | 30 | 15 | 10 | — (adjacency is the room it belongs to, §4.2) |
| trap | 0 (exempt, §3.3) | 5 | 10 | 0 (inverted, §4.4) | 5 | path_position 40, door_stair 25, service_distance 15 |
| room | 20 | 10 | 15 | 0 (not used, §2.7) | 10 | noise_distance 20, food_drink 10, workplace 5, enclosure 5, size_fit 5 |

Zone subtypes split the 25 "subtype extras" weight: meeting area
uses food_drink_proximity (15) + shelter (10 extra); pasture uses
shelter (5) + traffic (10 extra, animals need to reach it, and
dwarves should not have to cross it — the two pull in opposite
directions, so pasture scores traffic neutral and the weight goes
to shelter + adjacency to the surface); bedroom/dining zones use
the room extras at the same weights as `room`; barracks uses
path_position (15, near the entrance for defence) + noise_distance
(10, soldiers sleep there too); temple uses noise_distance (15) +
enclosure (10). The subtype table lives in code next to the
weights; a zone without a subtype scores the generic row and the
why says so.

### 3.5 The why line

Every scored site carries one plain-words line, generated from its
two strongest contributing factors (the factors that most raised
or lowered its score), in the model's language, never the
harness's:

- `"near the food stockpile and under cover, but on the main path
  dwarves walk."` (a workshop that scores well on adjacency and
  shelter and badly on traffic)
- `"poor soil — a quarter of the yield — but close to the seed
  stockpile."` (a farm plot)
- `"quiet, 10 tiles from the nearest dig, and enclosed on three
  sides."` (a bedroom)
- `"on the approach from the gate, in front of a door."` (a trap)

The why is generated from a fixed phrase table per factor
(`placement.py`, next to the weights), not by the model and not by
free text. The factors dict that backs it uses the same plain
words (`{"adjacency": "near the food stockpile", "traffic": "on
the main path"}`) — the route returns these words, never the
weights, radii, or raw columns. The score itself (0–100) is
shown: it is the ranking, not a weight, and the model needs it to
compare the top 3.

## 4. The factors in detail

### 4.1 Traffic: what dwarves actually walk

The harness has no tile pathfinder (`spatial.find_path` works on
the area graph, not tiles), and it does not set traffic
designations. So "the main corridor" is defined by observation,
not geometry: the tiles dwarves actually walk.

The daemon already records per-citizen daily samples in
`store.unit_history`, including `pos_json` (verified in
`src/dfagent_harness/store.py`: `INSERT INTO unit_history
(unit_id, tick, pos_json, job, ...)`). The caller builds a
foot-traffic heatmap once per search: for every citizen, take the
most recent 30 samples (about a month of in-game days at the
daemon's daily sampling), and count positions within 5 tiles
(Chebyshev, same z or ±1) of each candidate site. The count is
the traffic factor's input. A site no dwarf has walked near
scores 100 on traffic; a site on the most-walked tiles scores 0.

Limits, stated honestly: daily samples are coarse — a dwarf
crosses the corridor many times a day and is sampled once, so the
heatmap is a relative ranking (which tiles are walked more), not
a true count. That is enough for the purpose: the scorer needs to
know which of three candidate sites sits on the busy path, not
how many feet crossed it. If the store is empty (a fresh fort with
no samples yet), the factor scores neutral and the why says
"no foot-traffic record yet". No new observation machinery is
added for traffic — this is the existing data, used for a new
purpose.

### 4.2 The affinity table

Adjacency is the most heavily weighted factor for workshops,
stockpiles, and furniture, because the wiki's design advice is
explicit (§2.4) and because hauling time is the fort's scarcest
resource. The table lives in code (`PLACEMENT_AFFINITY` in
`placement.py`) as data: `(kind, subtype) -> [(target, weight,
max_distance)]`, where a target is a `(kind, subtype)` in the
state (a stockpile subtype, a workshop subtype, a zone subtype,
or a building type such as the trade depot or the dining room).

| Placed | Wants to be near | Why (wiki) |
| --- | --- | --- |
| workshop:still | stockpile:barrel (empty barrels), stockpile:food-brewable | barrel stockpile near the still (§2.4) |
| workshop:kitchen | stockpile:food, stockpile:food-cookable | ingredients near the kitchen (§2.4) |
| workshop:carpenter | stockpile:wood | design workshops and their stockpiles around each other (§2.4) |
| workshop:mason | stockpile:stone | same |
| workshop:craftsdwarf | stockpile:stone, stockpile:wood | same |
| workshop:butcher | stockpile:food (meat/fish) | butcher output goes to the food stockpile |
| farm_plot | stockpile:seed, stockpile:potash | seeds for planting; potash hauling (§2.3) |
| stockpile:food | workshop:kitchen, workshop:still, zone:dining | food goes to the kitchen, the still, and the table |
| stockpile:finished | building:trade_depot | finished goods near the depot (§2.4) |
| stockpile:refuse | (none — wants open sky and distance from the fort, §2.4) | refuse belongs outside, a small distance from the entrance |
| stockpile:seed | farm_plot | seeds belong by the farm (§2.4) |
| stockpile:barrel | workshop:still | barrels by the still (§2.4) |
| zone:dining | stockpile:food, stockpile:drink | the dining room is where food and drink are eaten |
| zone:bedroom | zone:dining | dwarves eat, then sleep nearby |
| zone:barracks | entrance, trap | soldiers defend the approach |
| zone:pasture | surface, stockpile:food (animals graze; keep it reachable) | pasture needs the surface |
| room:bedroom | zone:dining, workshop cluster | sleep near food and work (§2.7) |
| room:dining | stockpile:food, stockpile:drink | as zone:dining |
| furniture:bed | zone:bedroom | the bed belongs in a bedroom |
| furniture:table/chair | zone:dining, room:dining | tables and chairs belong in the dining room |
| furniture:door | (the doorway it fills — no affinity target; scored on reachability only) | — |
| trap | entrance, door, stairway | §2.6; traps are scored on path_position instead of adjacency (weight 10, §3.4) |

A target the state does not know about scores neutral for that
row (the factor is the best-known target, not the average of all
targets — one near food stockpile is enough). Distance is
Euclidean in 3D, capped at the table's `max_distance` (25 tiles
default): beyond it the affinity contributes nothing.

### 4.3 Rooms: noise, enclosure, size, and the people in them

Room scoring is the most factor-dense kind, because a bedroom is
where a dwarf spends a third of its life and the wiki's rules are
precise (§2.2, §2.7):

- **Noise** (weight 20): Chebyshev 3D distance to the nearest
  noise source. Sources are the current dig box (radius 8), any
  woodcutting designation if tracked (radius 8), and engraving
  workshops (radius 4). Phase 1 uses the dig box + all workshop
  positions at radius 8 (conservative: it treats every workshop
  as loud as digging). The refinement — per-workshop-type radii,
  and woodcutting designations as sources — is a follow-up when
  designation tracking exists (§6.4). A room 8+ levels below the
  surface scores full marks on noise regardless of horizontal
  distance (§2.2).
- **Enclosure** (weight 5): the share of the footprint's perimeter
  that is solid. This needs the probe extension (§6.2): the probe
  returns `enclosure: {north, east, south, west}` (whether that
  side is wall/floor) and the scorer counts enclosed sides. Four
  sides, or three + a door, is the privacy bonus (§2.7); the probe
  reports a door as enclosed. An open-sided room scores low on
  enclosure but is not refused — a dormitory is a legitimate
  choice (§2.7), and the model decides.
- **Size** (weight 5): the requested footprint against the kind's
  preferred size. Bedroom 3x3 is the sweet spot (§2.7); 1x1 is
  sleepable but not happy. Dining rooms "tend to be large" (the
  wiki's words — many tables and chairs raise the room's value),
  so the size factor for dining rewards up to 5x5 and is flat
  beyond it; the 5x5 cap is a design choice, not a wiki number.
  Noble rooms (bigger, with specific furniture) are out of scope
  for phase 1 — the doc notes it, it does not design it.
- **Food/drink and workplace** (weights 10 + 5): distances to the
  dining room / food / drink stockpiles and to the workshop
  cluster (§3.4). Per-dwarf workplace proximity (this dwarf works
  at the mason's shop, so its bedroom should be near the mason's
  shop) is not tracked — the fort has no dwarf→workshop
  assignment data — so phase 1 uses the workshop-cluster centroid
  as the proxy and says so in the why ("near the workshops").

### 4.4 Traps: scored backwards

Traps invert two factors and drop a third (§3.4):

- **Traffic is inverted**: a trap wants the busy path — the
  enemy's path, which is the approach from the entrance to the
  fort centre. The factor is not foot traffic (dwarves walking
  the corridor is the wrong signal for where an enemy will walk)
  but **path_position**: distance to the approach segment
  (entrance → fort centre, straight-line approximation). The
  harness has no tile pathfinder (§4.1), so the segment is the
  approximation and the implementation must demonstrate live that
  the top trap site sits on the entrance corridor (§8).
- **Threat is exempt** (§3.3) and **shelter is near-irrelevant**
  (weight 5): a trap in the open at the gate is a good trap.
- **Door/stair proximity** (weight 25): within 2 tiles of a door
  or stairway start scores full marks (§2.6). Hallway corners are
  approximated by doors and stairways in phase 1; true corner
  detection (a corridor tile where the walkable path turns) is a
  follow-up (§6.4).
- **Service distance** (weight 15): distance to the fort centre —
  the mechanic's base. A trap nobody can reach to service is a
  trap that stays jammed (§2.6).
- **Subtype**: `trap=cage` scores forward (outer) positions higher
  (the ambush-alarm role, §2.6); `trap=weapon` scores the approach
  segment itself. Without a subtype the generic row applies.

Two traps must never be scored as a pair in phase 1 (the wiki's
two-path control system, §2.6, is a fort-layout decision the
model makes, not a scoring rule). The wagon rule is a why-line
note, not a factor: if the top trap site sits on the path to the
trade depot, the why says "on the caravan's path — wagons cannot
pass traps" and the model decides. Computing the depot path needs
the tile pathfinder the harness does not have (§6.4).

## 5. Subtypes: the scorer needs to know what is being placed

`find_sites`, `daemon.get_placement`, and `GET /v1/sites` gain an
optional `subtype` parameter:

- stockpile: `food`, `refuse`, `wood`, `stone`, `barrel`, `seed`,
  `finished` (the stockpile categories the state already knows;
  an unknown subtype is a 400 with the legal list, same as an
  unknown kind).
- zone: `meeting`, `pasture`, `bedroom`, `dining`, `temple`,
  `barracks`, `archery`.
- room: `bedroom`, `dining`, `office`.
- farm_plot: `subterranean`, `above-ground` (the crop class — this
  is what the light gate needs, §3.3).
- trap: `cage`, `weapon`, `stonefall`.
- workshop, furniture: no subtype in phase 1 (the workshop type
  is chosen at build time by the action, and the scorer uses the
  workshop's affinity rows generically; a workshop subtype is a
  follow-up if the build action starts passing it).

Without a subtype, every subtype-dependent gate and factor is
skipped, the factor scores neutral, and the why says what was not
known ("no subtype given — scored generically"). A missing subtype
is never an error and never a crash. The planner passes the
subtype it knows (its stockpile decision knows it is placing a
food stockpile; its farm decision knows the crop class); the
snapshot's placement section uses the generic row (it does not
know subtypes) and the model queries `/v1/sites?kind=...&subtype=...`
for the scored detail.

## 6. What changes in code

### 6.1 `placement.py`: score_site() + tables + wiring

- `ScoreContext` dataclass (§3.1) and `score_site()` (§3.3–§3.5).
- `PLACEMENT_WEIGHTS` (per-kind weights, §3.4) and
  `PLACEMENT_AFFINITY` (the affinity table, §4.2) as data, with a
  comment per row citing the wiki section.
- `find_sites()` gains: a `subtype` parameter (passed through to
  the scorer and the probe where relevant); a `ctx` built once
  per search from the caller's state (the daemon passes its state;
  the route passes the fresh collect); scoring of the verified
  candidates; return of the **top 3** (was 5) with `score`, `why`,
  and `factors` (plain words) per site; `blocked` top 3 with
  reasons (unchanged in shape, now including hard-gate refusals
  with their plain-words reasons). The probe budget and the five
  verification layers are unchanged — scoring runs after
  verification, never instead of it. The `limit` parameter stays
  for callers that want more, but the default return is 3: the
  model gets three named options, not a list to sift.
- `site_why()` is replaced by the scorer's why generation for
  scored sites (the distance-only text stays as the fallback when
  no context is available — e.g. the offline tests that call
  `find_sites` without a context — so existing callers do not
  break; the fallback is marked as such in the why).
- `verify_site()` gains scoring too: verifying one site returns
  its score + why alongside free/reachable, so a build action
  that checks a specific site can report "this site is free but
  scores 22 — the top alternative is (x, y, z)".

### 6.2 `probe_site.lua`: enclosure

The probe gains an `enclosure` field for the footprint's
perimeter: for each of the four sides, whether the tiles just
outside the footprint on that side are solid (wall or floor) —
reported as `{north, east, south, west}` booleans, plus a door
counted as enclosed (a door is a wall with a dwarf-sized hole;
the wiki's privacy bonus counts 3 walls + a door, §2.7). This is
the one new data read the phase adds, and it is a Lua read of
tiles the probe already visits — not a new observation system.
The probe's existing contract (five layers + farm summary) is
unchanged; enclosure is an additional field, ignored by old
callers.

### 6.3 `daemon.py`: context building + cache

- `_derive_sites()` builds the `ScoreContext` once per tick from
  the state it already holds (threats, buildings, stockpiles,
  zones, dig box, unit_history heatmap) and passes it to
  `find_sites`. The placement cache stores scored sites (with
  score/why/factors), so the snapshot and the route serve the same
  scored order.
- `get_placement()` gains the `subtype` parameter and passes it
  through; the cache key becomes `(kind, subtype, width, height)`
  so a generic search does not serve a subtype-scored result.
- The traffic heatmap is built from `store.unit_history` (last 30
  samples per citizen, §4.1) — the daemon already owns the store,
  so no new plumbing.

### 6.4 `routes_spatial.py` + snapshot: the model-facing surface

- `GET /v1/sites` gains `?subtype=` and returns the scored top 3
  (`score`, `why`, `factors` as plain words) plus `blocked` with
  reasons. Unknown kind or subtype → 400 with the legal list
  (the route already does this for kind).
- The snapshot's placement section (`assembler._placement` +
  `placement.format_compact`) keeps its shape — top site per kind,
  capped at 3 — but the order is now the scored order and the why
  lines are the scorer's. The snapshot carries the top site per
  kind only; the full top 3 lives behind `/v1/sites`. The model
  never sees the weights, the radii, or the raw columns — only
  score + why + factors-in-words.

### 6.5 `digging.py`: miner exposure + new-entrance cost

`check_dig_site()` / `derive_dig_site()` gain two checks; the
existing hazard (magma/aquifer/water, `HAZARD_LOOKAHEAD = 3`) and
reachability checks stay exactly as they are (§7).

### 6.6 Not in this phase (explicitly)

- `docs/PLACEMENT.md` does not exist — `placement.py`'s module
  docstring references it ("the creation route differs per kind
  and is documented in PLACEMENT.md"), but the file was never
  written. The implementation writes it as the user-facing
  placement reference (kinds, sizes, creation routes, and a
  pointer to this doc for scoring), or removes the dangling
  reference. It is a small follow-up, not a scoring question.
- Per-dwarf workplace proximity (§4.3), per-workshop-type noise
  radii (§4.3), woodcutting designations as noise sources (§4.3),
  hallway-corner detection for traps (§4.4), the caravan/depot
  path for traps (§4.4), noble rooms (§4.3), trap pairs / the
  two-path control system (§2.6). Each is named here so the
  implementation does not silently invent one of them; each is a
  follow-up with its own verification bar.

## 7. Dig selection: extend, do not replace

`check_dig_site(client, x, y, z, mode, areas, surface_z)` returns
`{"ok", "reachable", "hazards", "reason", "detail"}` today, with
`ok` True only when reachable AND no hazard in the dig path. Two
additions:

### 7.1 Miner exposure

The miner stands where the digging happens — in the open, for a
down-stair/channel, or beside the wall, for a plain dig. A miner
within 20 tiles 3D of a hostile archer is a dead miner (§2.1).
`check_dig_site` gains a `threats` parameter (hostile positions,
same source as the placement context); when a hostile is within
20 tiles 3D Manhattan of the dig tile, the site is refused with reason
"a hostile is within 20 tiles — the miner would be shot digging
here". This is a hard gate, not a score: exposure while digging
is not a tradeoff, it is a death. (The same 20-tile rule as
§3.3, applied to the miner instead of the site's future user.)

### 7.2 New-entrance cost

A dig that opens a new hole to open sky — a channel or up-stair
that breaks the surface — creates an entrance the fort is not
defending (§2.5: every opening is a front). `check_dig_site`
gains an `entrance` parameter (the planned entrance position,
from the daemon's derived dig site / the existing entrance). A
dig whose post-dig column is open to the sky (the column
classifier already knows: `_open_above`) at a position that is
not the planned entrance is refused with reason "this would open
a new entrance to the surface — the fort has an entrance already".
The exception is the planned entrance itself: when the dig IS
the entrance (the daemon's derived dig site), the gate does not
apply — the fort needs one entrance, and this is it. A channel
that opens a dug room to the sky from below (a skylight for a
greenhouse farm, §2.3) is the same gate with the same exception
mechanism: the planner flags the dig as a deliberate skylight
when it wants one, and the refusal names the alternative (dig
the greenhouse channel where the farm is, not here).

### 7.3 Cavern breach as a dig gate

The column classifier already emits a `cavern space` class (used
by `check_dig_site`'s reachability reasoning). A dig whose path
(`HAZARD_LOOKAHEAD` levels, same as the existing hazards) hits a
cavern-space tile is refused with reason "this would break into
a cavern — forgotten beasts and worse come through an open
cavern". The exception is deliberate, guarded cavern access: the
planner sets a flag when it wants cavern access (for wood, water,
or farming, §2.5), and the refusal is lifted only for that
flagged dig — and the doc requires the access to be on the side
with a hatch, never the main stairwell (§2.5). The flag is
per-dig, never a standing permission: a standing "caverns are
okay" flag would let the next dig breach one by accident.

### 7.4 derive_dig_site scores the candidates

`derive_dig_site()` today returns the first workable dig site.
It gains the same treatment as `find_sites`: among candidate dig
tiles, prefer the one with the lowest miner exposure, no new
entrance, and the shortest path from the fort — and return the
top candidate with its reason, not just a position. The existing
callers (`daemon._derive_dig_site`, the dig action's verification)
keep working: the return shape gains `score`/`why` fields and
loses nothing.

## 8. Verification bar

### 8.1 Offline tests

- Pure scoring tests with fabricated contexts (no game): each
  factor in isolation (a site 5 tiles from a hostile vs 30 tiles
  away; poor soil vs full yield; mixed light vs uniform; a
  bedroom inside the noise cube vs outside it; a trap on the
  approach segment vs off it; a refuse site under cover vs open
  sky), each hard gate (archer radius at 19/20/21 tiles; refuse
  under cover; mixed-light farm), and the why generation (the
  two strongest factors appear in words; no weights, radii, or
  raw columns in the output).
- Malformed-input tests (the standing rule): unknown kind,
  unknown subtype, bad sizes (0, negative, >31), missing context
  fields (no threats, no buildings, no stockpiles, no farm
  summary), a site dict missing `pos`, a context that is None.
  Every one of these returns a 400 or a neutral score — never an
  exception, never a crash, never a guessed site.
- Route tests: `/v1/sites?kind=workshop&subtype=...` returns
  scored sites with the new fields; unknown subtype is a 400;
  the cached path serves the right subtype (a generic search must
  not serve a refuse-scored result).
- The offline suite stays at its baseline plus the new tests
  (809 passed at the start of this phase); ruff clean.

### 8.2 Live verification (both forts)

- Main fort Erushtathtat and scratch fort region5, after a daemon
  restart (the standing rule — Python never reloads modules).
- The scored order differs from the distance order in at least
  one demonstrated case per fort: a nearer site that is exposed
  (open sky, near a noise source, on the busy path, or poor soil)
  ranks below a farther sheltered one, and the why names the
  reason. A ranking that never differs from distance is a ranking
  that adds nothing — the live run must show the difference.
- `/v1/sites?kind=workshop`, `?kind=farm_plot`,
  `?kind=stockpile&subtype=refuse`, `?kind=room&subtype=bedroom`,
  `?kind=trap` each return scored top 3 with why lines; the
  refuse search returns open-sky sites only.
- The snapshot carries the top site per kind in scored order.
- Dig: a dig aimed at a cavern-space tile is refused; a dig that
  would open a new surface hole away from the entrance is refused;
  the planned entrance dig still verifies; a normal dig still
  verifies (the existing checks are not broken by the additions).
- The game state is unchanged by the verification itself (tick
  and stocks checked before and after; scoring is a paused read,
  no game time advances).

## 9. Measurement

The weights in §3.4 are design choices. The eval framework
(docs/EVALUATION.md) measures them: the guidance ablation runs
the same model on the same scenario with scored placement versus
distance-only placement and compares the outcome (fort survival,
wealth, needs, and the score v2 dimensions). If scored placement
does not beat distance-only placement, the weights are wrong and
they change — the doc does not defend them, the runs do. The
per-kind weights are also the mechanism by which a discovered
tactic becomes part of the harness (docs/HARNESS_ROLE.md §6.3):
if the model consistently places better by ignoring a factor,
that is evidence about the factor, not disobedience.

## 10. Queue position and dependencies

- This phase implements against this doc only. It does not
  re-derive the design from memory and it does not import rules
  from the other design docs — but it feeds them: the stockpile
  plan (docs/STOCKPILES.md) wants subtype-aware stockpile
  placement; the farming plan (docs/FARMING_PLAN.md) wants
  farm siting by soil/light; the military plan (docs/MILITARY.md)
  wants trap siting; the kitchen plan (docs/KITCHEN.md) wants the
  kitchen/food-stockpile adjacency. Those phases use the scored
  API; they do not re-score.
- The harness-role tension this phase touches: scoring is harness
  heavy-lifting, and the top-3-with-why is the freedom mechanism
  (the model chooses). The eval ablation (§9) is the measurement
  for both.
