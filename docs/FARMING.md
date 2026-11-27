# Farming

How the harness grows crops — and, more importantly, how it refuses
to plant the wrong crop in the wrong place. A crop in the wrong place
is a failure the harness must **prevent**, not just report (Mikey,
2026-11-26).

## The rules (wiki "Farming", verified live 2026-11-27)

- A farm plot grows **one kind of plant per season**; the crop is
  chosen per season. Seeds are required — one seed per tile.
- **Above-ground crops** need a sunlit plot (Light, "above ground");
  **subterranean crops** need a dark plot ("below ground"). What
  matters is Light vs Dark, not Inside/Outside: land ever exposed
  to sunlight is permanently "above ground".
- A plot with **mixed Light and Dark tiles may show plants as
  "available" when only a fraction are valid** — it will never be
  fully planted. The harness refuses a mixed plot and tells the
  model to rebuild it wholly one way or the other. An underground
  plot exposed to sunlight will never grow underground plants again.
- Plots need **soil or muddied stone**. Farm tiles in soil layers
  (except cavern parts) are **"poor" — yields reduced 75%**;
  muddied stone in any stone layer is NOT poor. The harness notes
  poor soil in the result; it does not refuse it (a poor harvest
  beats no harvest).
- Planting needs the Farming (Fields) labor / Planter skill.
- Fertilizer is potash, floor(plot_size/4)+1 per plot (verified
  live: a 3x3 plot has max_fertilization 3). Not yet implemented.
- Plump helmets are the beginning cave crop (any season, quick).
  Strawberries are the outdoor field crop; rope reed and longland
  grass grow on swampy ground.

## What the harness verifies before planting

`set_farm_crop` (actions.py) checks, in order, and refuses with the
cause and the fix:

1. The plot exists, is a FarmPlot, and is built.
2. The crop is a known plant raw (`probe_crop.lua` — index,
   depth_min/max, growdur, seasons, BIOME_* flags, current season).
   There is no `biome`/`seasons`/`underground_depth` field on the
   raw; seasons and biomes are flags, depth is
   `underground_depth_min`/`underground_depth_max`, growdur is in
   units of 100 ticks (300 = 25 days).
3. The crop grows in the season (plump helmets: any season; cave
   wheat: summer/autumn only).
4. Light: all-light for an above-ground crop (depth 0–0), all-dark
   for a subterranean crop (depth min ≥ 1). Mixed light is refused.
5. Biome, for above-ground crops only: every tile's biome
   (map-block designation, `biome_type` enum, 51 values) must be one
   the crop grows in. The mapping is positional and name-exact:
   plant flag `BIOME_<NAME>` ↔ biome_type `<NAME>` (verified live:
   tile biome 4 = SWAMP_TEMPERATE_SALTWATER; rope reed carries
   `BIOME_SWAMP_TEMPERATE_SALTWATER`). Subterranean crops skip
   this: underground tiles carry the surface biome above them
   (MOUNTAIN), not the subterranean biome — the wiki's rule for them
   is just "underground plot + soil/mud".
6. Seeds (`probe_seeds.lua` — per plant raw, split in-play vs
   in-wagon; trader-held excluded): 1 per tile. Zero seeds is a
   refusal (have 0, need N). A partial count plants that many tiles
   and says so — it does not refuse. Seeds still in the wagon are
   named in the result (deconstruct the wagon so planters can reach
   them).

The write itself is verified by read-back (`act_farm_crop.lua`
writes `plant_id[season]` — 0-based, -1 = fallow — and reads it
back; the write is only trusted when the read-back matches).
Planting is verified by the caller: PlantSeeds jobs appear once the
crop is set and seeds are reachable. If no job appears, the crop
cannot grow here (seeds locked away, no planter, crop invalid
despite the checks) — the farm task reports that as a failure with
a diagnosis, it does not claim success.

## What the harness cannot verify

- **Mud.** The map-block designation struct has no mud flag
  (fields: flow_size, pile, dig, smooth, hidden, geolayer_index,
  light, subterranean, outside, biome, liquid_type, water_table,
  rained, traffic, flow_forbid, liquid_static, feature_local,
  feature_global, water_stagnant, water_salt). The harness verifies
  SOIL directly (material == SOIL); stone tiles are reported as
  "may be muddied" and the game's own construction cancellation is
  the backstop. Underground soil exists (no muddying needed).
- **Fertilization.** Potash mechanics are not implemented yet.

## Digging the underground room (verified live 2026-11-27)

A down-stair does **not** create an up-stair in the solid tile
below it — verified live (the tile stayed SOIL WALL after the
down-stair was dug). Wiki "Stairs": "Up stairs need to be built
below down stairs." The sequence is:

1. `dig_to_completion` mode `down-stair` on the surface floor.
2. `dig_to_completion` mode `up-stair` on the tile directly below
   (the miner stands on the down-stair above and carves it).
3. `dig_to_completion` mode `dig` for the room — in strips
   flanking the stair column, because the site check needs an open
   tile **beside** the box at the same level, and the stair landing
   only counts when it is outside the box.

The room floor is the dug-out soil at that level — dark, on soil,
ready for a plot. `build_farm_plot` there takes `farm=True` on its
site probe, so the build result carries the soil/light/biome
summary; `find_sites` takes `z_levels` to search a dug level
(e.g. `surface_z - 1`).

## The pieces

- `set_farm_crop` action (actions.py) — the verified setter.
- `build_farm_plot` — builds the plot; its result detail carries
  the `farm` summary (soil/light/biome) from the site probe.
- `farm` task (daemon.py, `POST /v1/tasks/farm`) — self-contained:
  finds a built plot, picks the crop (dark → plump helmets; light
  → the surface crop with the most seeds that grows in this biome
  and season), sets it, waits (bounded) for PlantSeeds jobs to
  appear and finish, reports the planted count or a diagnosis.
  Accepts `building_id` / `plant` / `season` overrides; the action
  still enforces the rules, so a wrong override is refused.
- Suggestion (assembler.py) — when no farm plot exists and seeds
  exist (`category_stacks.SEEDS`, the raw game-category count,
  which includes seeds still in the wagon), and nothing more
  urgent fired, suggest building a plot (naming the `farm_site`
  coordinate when known) and then running the farm task.
- Catalog (catalog.py) — `set_farm_crop` entry; `build_farm_plot`
  constraints carry the soil/light/biome rules and the poor-soil
  note.
- Tests: `tests/test_farming.py` (offline, 14 tests — the refusal
  matrix), `tests/test_tasks.py::TestFarmTaskOffline` (the task's
  choice logic), `tests/test_assembler.py::TestSuggest` (the
  suggestion), `tests/test_farming_live.py` (live, against the
  scratch fort on RPC 5001 — refusals + the write + read-back).

## Live verification (scratch DF, region5 fort, 2026-11-27)

- Surface plot #1 at (90,90,50), 3x3, soil, sunlit, biome
  SWAMP_TEMPERATE_SALTWATER: plump helmet refused (sunlit), cave
  wheat refused (does not grow in spring — summer/autumn only),
  rope reed refused (no seeds on hand: have 0, need 1 per tile).
- Underground room dug at z=49 (down-stair + up-stair + two room
  strips), plot #2 built at (82,82,49), plump helmet set for
  spring — read back as plant_id [171,-1,-1,-1], which is the
  buggy index (171 = WALNUT; see the root-cause note below — the
  spring crop that actually grew was set by a path that wrote the
  correct 172). **Planting is partially verified — see the
  investigation below.** Do not claim planting works end to end
  until a seed is consumed and a plant grows on a plot tile in a
  controlled test.

## Live investigation: why PlantSeeds jobs often do nothing (2026-11-27)

**Proven end to end (spring):** plot #2's spring plump helmet crop
grew and was harvested — 9 plump helmet PLANT items (type PLANT,
token STRUCTURAL) sat on the plot tiles afterwards. So the
mechanism (set crop -> PlantSeeds job -> dwarf plants -> shrub
grows -> harvest) DOES work.

**ROOT CAUSE (found 2026-11-27, fixed): the crop index was off by
one.** `probe_crop.lua` computed `index = i - 1` on the `ipairs`
index, on the wrong assumption that `ipairs` over a DFHack vector
is 1-based. It is 0-based — verified live: `ipairs` gives 172 for
MUSHROOM_HELMET_PLUMP, the same as `raws[172]`; `raws[171]` is
WALNUT. So every crop set through `set_farm_crop` wrote the plant
one earlier in the raw list than intended: plump helmet -> WALNUT
(a tree, never farm-plantable), pig tail -> plump helmet, cave
wheat -> pig tail. That one bug explains all three symptoms:
- Autumn/winter 0 PlantSeeds jobs: the plots' autumn/winter slots
  held 171 (WALNUT), which the game cannot plant, so it correctly
  created no jobs. (Plot #3's autumn slot held 173 = pig tail, a
  real crop, but there were 0 pig tail seeds on hand, so no jobs
  there either — also correct.)
- Summer "wrong seeds": the game planted exactly what was stored.
  Plot #3 was set to cave wheat but stored 173 (pig tail), so it
  fetched pig tail seeds; plot #2 was set to pig tail but stored
  172 (plump helmet), so it fetched plump helmet seeds. The fetch
  was never wrong — the stored crop was.
- The spring success predates the bug: the spring crop must have
  been set by a path that wrote the correct index (172) before
  `set_farm_crop`'s off-by-one was in play; the spring slot reads
  171 today because it was later overwritten through the buggy
  action. (The doc's earlier spring read-back `[171,-1,-1,-1]` is
  the buggy value, not the value that grew.)
The fix is `index = i` in `probe_crop.lua`, pinned by
`TestProbeCropIndex` and by the live test asserting 172. The
`last_season` gate theory is dead twice over: `last_season` is
`fertilize_attempt_season` (fertilizer, not planting), and the
farmplot struct (df-structures `df.building.xml`) has no planting
gate field at all — only `plant_id[4]`, `material_amount`,
`farm_flags.seasonal_fertilize`, `last_season`,
`current/max_fertilization`, `terrain_purge_timer` (trample_count).
The tiles were also ruled out: all plots are 9/9 FurrowedSoil,
dark/subterranean, stage 3. The 26 plump helmet seeds are in one
BOX (#2878) on the ground at (94,92,50), reachable, not forbidden.
Both planters (Melbil 8173, Etur 4981) are idle with PLANT labor.

**What the game does (verified live):**
- PlantSeeds jobs are created SLOWLY / periodically (first job
  ~110 s after a crop is set in one long watch). Short watches
  (20 s) see nothing — that is not evidence of failure. The farm
  task's wait must be LONG (minutes), and must not fail fast.
- jobs.lua reports `worker=None` even for a CLAIMED PlantSeeds
  job (Melbil's own record showed job=PlantSeeds while the jobs
  list showed worker=None). Read the UNIT's current_job to know
  who is working, never the job's worker_id.
- A dwarf doing PlantSeeds goes to the tile, stands ~10 s, leaves.
- Resetting a plot's `last_season` to force re-processing did NOT
  produce jobs in 600 s. Flipping `in_building` + a
  BUILDING_HOLDER ref on the cave wheat seeds did NOT make them
  fetchable (a farm plot is not a valid seed holder).
- A food stockpile accepting seeds (built via
  `dfhack.buildings.constructBuilding{type=Stockpile,
  abstract=true}` + `flags.food=true` + resizing
  `settings.food.seeds` to the plant-raw count (224) and setting
  bits + `checkBuildingsNow()`) DOES get the seed bags hauled in
  (5/6 bags within minutes).

**Verification of the fix (in progress 2026-11-27):** plot #5's
winter crop, plot #2's autumn crop and plot #3's autumn crop were
re-set through the fixed action (plant_index 172, 172, 174 — read
back and correct). A 300 s unpaused watch on the scratch fort is
running to confirm PlantSeeds jobs appear on plot #5. Until a seed
is consumed and a plant grows on a plot tile in that controlled
test, do not claim planting works end to end for the fixed action.
- Embark seeds: 30 seed items, 5 each of dimple cup, pig tail,
  quarry bush, plump helmet, sweet pod, cave wheat — all in seed
  bags inside the wagon (holder building type 32 = Wagon). Four
  more plump helmet seeds appeared later on the ground at
  (97,96,50) — dwarves ate helmets, producing seeds.
