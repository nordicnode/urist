# DF Agent Harness — Observation Layer (Phase 1)

Read-only state dump of a live Dwarf Fortress 0.47.05 + DFHack 0.47.05-r8
fort, as structured JSON and as a compact text rendering. Verified live
on the fort **Athelunol** ("Ringedsouls", world "Mitom Kodor", save
`region1`): 7 starting dwarves, Spring 306.

## Running it

```sh
# Full dump (all fast sections), JSON on stdout:
.venv/bin/python scripts/dfh-observe.py

# Compact text (what an LLM agent reads first):
.venv/bin/python scripts/dfh-observe.py --format text

# One section only:
.venv/bin/python scripts/dfh-observe.py --section units
.venv/bin/python scripts/dfh-observe.py --section stocks,items --format text

# Include the slow designation scan (~4 s), and measure FPS (1 s sample,
# only while unpaused):
.venv/bin/python scripts/dfh-observe.py --section all,designations --fps

# Write to a file instead of stdout:
.venv/bin/python scripts/dfh-observe.py --format json --output /tmp/state.json
```

Exit 0 on success (even if individual sections fail — see `errors`).
Exit 1 with a JSON error on stderr when the game is not reachable.
Exit 2 for bad flags (e.g. unknown `--section`).

**Read safety (world-model design §8): the dump runs only while
the game is verified paused.** Every read goes through the
pause-before-read gate (`dfagent_harness.read_safety.paused_read`):
pause (verified), read, restore the prior pause state. If pause
cannot be verified the read is refused ("outcome unknown"), never
performed while running. The earlier claim that the dump "is safe
to run while unpaused" is **retracted** — it is contradicted by the
three DF deaths of 2026-11-25 (one ended `free(): double free
detected in tcache 2`), when RPC reads of game structures while the
game ticked caught a freed struct. While running, the harness
listens (the eventful watcher writes a file); while paused, it reads
(RPC). The `--fps` flag is the one exception: it measures the tick
counter while the game runs (single-value reads, explicitly opt-in).

## How it works

```
scripts/dfh-observe.py
  -> dfagent_harness.observe.collect(client, sections)
    -> one Lua helper per section, via DFHackClient.run_lua_json()
       (RunCommand("lua", <prelude + helper>); helper prints one JSON object)
    -> sections assembled into one state document (dict)
  -> render_text(state) for --format text
```

- **Transport:** the existing `dfhack_rpc` client (no duplication).
  One TCP connection, calls serialized.
- **Lua helpers:** `src/dfagent_harness/lua/*.lua`. Each prints exactly
  one JSON object. A shared prelude (`lua/json.lua`, a minimal JSON
  encoder — DFHack's Lua has no `json` module) is prepended by the
  Python side before execution. Helpers never write files, never call
  mutating APIs, and wrap their body in `pcall`: on any Lua error they
  print `{"ok": false, "error": "..."}` and the Python side records it
  under `errors` instead of failing the whole dump.
- **Dev helper:** `scripts/lua_probe.py <file.lua>` runs an arbitrary Lua
  file against the live game and prints its output (used while probing
  the API; not part of the shipped CLI).

## Schema (state document, `schema_version: 1`)

Top level: `meta`, `errors`, plus one key per collected section.
`errors` is a list of `{"section", "error"}` for helpers that failed;
missing sections are reported there, never silently dropped.

### `meta`

| Field | Meaning |
|---|---|
| `schema_version` | 1 |
| `collected_at` | Unix epoch seconds (wall clock) when collection started |
| `took_ms` | Wall time for the whole collection |
| `version` | RFR `GetVersionInfo`: `dwarf_fortress_version`, `dfhack_version`, `remote_fortress_reader_version` (or `{"error": ...}` if the call failed) |
| `fps` / `fps_measured` | Ticks/second over a 1 s sample, only with `--fps` and only while unpaused; `null`/`false` otherwise (ticks do not advance while paused) |

### `status`

| Field | Meaning |
|---|---|
| `year`, `year_tick` | In-game year and tick within the year (403200 ticks/year) |
| `season`, `season_index`, `season_tick` | Season name (Spring/Summer/Autumn/Winter), 0-3, tick within the season |
| `month`, `day`, `date` | Derived from `year_tick` (28-day months, 1200 ticks/day): `date` is `"306-01-16"` style. Verified against the UI date display. |
| `paused` | `df.global.pause_state` |
| `gametype` | e.g. `DWARF_MAIN` (fortress mode) |
| `focus` | `dfhack.gui.getCurFocus()`, e.g. `dwarfmode/Default` |
| `fort_name` | Fort site name (the unique type-0 site in `world_data`), e.g. `Athelunol` |
| `save_dir` | Save folder, e.g. `region1` |
| `population` | `{citizens, jobless, animals, total_active_units, threats}`. `jobless` = citizens with no `current_job`. `threats` = active units that are `isOpposedToLife` or have `flags1.active_invader`. `animals` = active units where `isAnimal` (includes pets, livestock, and wild animals on the map). |

### `units`

| Field | Meaning |
|---|---|
| `citizens` | One object per citizen (see below), in `world.units.active` order |
| `citizen_count`, `hostiles`, `hostile_count` | Hostiles are active units matching the same threat test as `population.threats`, with `{id, name, race, pos}` |

Per citizen:

| Field | Meaning |
|---|---|
| `id`, `name`, `race`, `profession`, `profession_id` | `name` is the translated visible name; CP437 bytes are decoded to Unicode (ä, ò, â, ë — verified on real names) |
| `sex` | 0 = female, 1 = male (DF convention) |
| `age` | Years (float, from `dfhack.units.getAge`) |
| `pos` | `[x, y, z]` tile coordinates |
| `idle` | `true` when `job.current_job` is null |
| `job` | `null`, or `{type, id, pos}` — `type` is the `df.job_type` name |
| `mood`, `mood_name` | `-1`/`"none"` when no strange mood, else the `df.mood_type` name |
| `stress` | `{level, category}` — raw `personality.stress_level` and `dfhack.units.getStressCategory` (0 = most stressed, 6 = least; cutoffs from `getStressCutoffs`) |
| `counters` | `{hunger, thirst, sleepiness}` — raw `counters2` timers (ticks since last satisfied; thresholds are **not** defined in phase 1 — see Limitations) |
| `needs` | All needs: `{need, level, focus}` — `need` is the `df.need_type` name, `level` is `need_level`, `focus` is `focus_level` (more negative = more unmet). The text renderer shows the 3 worst by `focus`. |
| `skills` | Skills with `rating > 0`: `{skill, rating, rating_num, experience}` — `skill` is the `df.job_skill` name, `rating` the `df.skill_rating` name |
| `labors` | Enabled labor names, sorted |
| `wounds`, `wound_count` | `{id, parts}` per wound in `body.wounds` (count of affected body parts). A healthy dwarf has `[]`. `unit.health` does not exist as a field in this DFHack build — wounds are the health signal. |
| `goal` | `{type, name}` — the dwarf's dream goal via `getGoalType(u, 0)` / `getGoalName(u, 0)`, e.g. `Master a Skill`; `null` when absent |

### `stocks`

Headline fortress stocks, counted over `world.items.other.IN_PLAY`
(items actually in play at the fort, not world-gen leftovers).
`units` = sum of stack sizes; `stacks` = number of item stacks.

| Field | Meaning |
|---|---|
| `drink_stacks`, `drink_units` | Drink items |
| `food_stacks`, `food_units` | MEAT + FISH + FISH_RAW + PLANT + CHEESE + EGG, summed |
| `seeds_stacks`, `seeds_units` | Seeds |
| `wood_stacks`, `wood_units` | Wood logs |
| `stone_stacks`, `stone_units` | BOULDER + ROUGH + BLOCKS |
| `cloth_units`, `thread_units` | Cloth / thread |
| `metal_bar_stacks`, `metal_bar_units` | Metal bars (`BAR`) |
| `barrels`, `bins`, `buckets` | Container counts |
| `category_stacks` | Raw `items.other` category counts for the headline categories DF players use: `ANY_GOOD_FOOD`, `ANY_COOKABLE`, `ANY_EDIBLE_RAW`, `ANY_DRINK`, `WOOD`, `BAR`, `CLOTH`, `SEEDS`. Note `ANY_GOOD_FOOD` (50 stacks at embark) counts more than the `food_*` sum — it is DFHack's own category, not a subset of the food types above. |
| `by_material` | `[{type, material, units}]`, sorted by units desc. `material` is the `dfhack.matinfo` token, e.g. `PLANT:GRASS_WHEAT_CAVE:DRINK`, `CREATURE:SPIDER_CAVE_GIANT:SILK`. Items whose material cannot be decoded (e.g. fish) are omitted here, not guessed. |

### `items`

| Field | Meaning |
|---|---|
| `total_stacks`, `total_units` | Totals over IN_PLAY |
| `by_type` | `[{type, stacks, units}]` for every item type present, sorted by units desc |

### `buildings`

| Field | Meaning |
|---|---|
| `list` | One object per building: `{id, type, type_id, x1, y1, x2, y2, z, center, construction_stage, jobs, contained_items}`. `type` is the `df.building_type` name (e.g. `Wagon`). `jobs` is the count of queued jobs on the building (`null` if the field is absent); `contained_items` the count of items inside it. |
| `count`, `summary` | Total count and `[{type, count}]` sorted by count desc |

### `jobs`

| Field | Meaning |
|---|---|
| `list` | Queued jobs from the `world.jobs` linked list: `{id, type, pos, suspend, repeat_}`. `type` is the `df.job_type` name. Verified on non-empty lists in phase 2 (FellTree, Dig, GatherPlants, Drink2, RecoverWounded, ConstructBuilding jobs all walked). |
| `count`, `counts_by_type` | Total and `[{type, count}]` |
| `manager_orders`, `manager_order_count` | Manager orders from `world.manager_orders`. Each order is a generic scalar dump of its struct fields plus `job_type_name` where readable. Verified on non-empty data in phase 2 (MakeBarrel x5 created and removed; observed fields include `id`, `job_type`, `job_type_name`, `amount_left`, `amount_total`). |

### `reports`

| Field | Meaning |
|---|---|
| `announcements`, `announcement_count` | Last 20 announcements (oldest→newest of the tail) + total count. Each entry is a generic scalar dump of its struct fields plus best-effort `text`, `year`, `time`, `pos` (the struct field is `time`, tick within the year — not `year_tick`). Verified on non-empty lists in phase 2 (build-cancellation and weather announcements; the 0-based `take_tail` fix in `reports.lua` was required for non-empty lists to read at all). |
| `reports`, `report_count` | Same, for combat reports in `world.status.reports`. Combat reports themselves are still unverified on non-empty data (no combat on this fort). |

### `map`

| Field | Meaning |
|---|---|
| `size_tiles` | `[x_count, y_count]` in tiles, e.g. `[192, 192]` (12×12 blocks) |
| `z_levels` | `z_count`, e.g. 58 |
| `region_x`, `region_y` | `world.map` region coordinates (opaque; not world-tile coords) |
| `plants_total`, `trees`, `shrubs` | Plant counts (`is_shrub` splits trees/shrubs) |

### `designations` (opt-in only)

Full map-block scan: counts of `dig` designations by `df.tile_dig_designation`
name (`Default`, `Channel`, `Ramp`, `UpDownStair`, `DownStair`, `UpStair`),
`smooth_total`, `dig_total`, and `scan_seconds`. **~4 s on a 192×192×58
embark** — this is why it is not in the default set.

## Text rendering

`render_text(state)` prints sections in order: header (fort, date,
season, tick, pause, focus, versions), population, FPS line (only when
measured or when paused), stocks + material breakdown (top 12), items
(top 15 types), citizens (one line each: name, profession, age, sex,
job/pos, stress, hunger/thirst/sleepiness timers, mood, wounds, worst 3
needs, top 4 skills; plus a labors line), hostiles if any, buildings,
jobs (+ first 15) and manager orders, announcements/combat reports,
map, designations (if present), then any `SECTION FAILED` lines.
Example dumps: `tests/fixtures/observe-athelunol.txt` (and `.json`).

## Tests

```sh
.venv/bin/python -m unittest discover -s tests -v   # 48 tests
```

- `tests/test_observe.py` — offline unit tests against the recorded
  fixture: schema shape, text rendering, section assembly (incl. the
  shared `stocks.lua` call and the items-only no-leak case), unknown
  section rejection, failed-section handling.
- `tests/test_observe_live.py` — integration test against the live game;
  **skips itself when no game answers on 127.0.0.1:5000**
  (`DFH_TEST_LIVE=0` forces the skip). Asserts the real fort's
  population/stocks, JSON serializability, and the designations scan.
- `tests/test_client.py` — includes the CP437 TEXT-fragment regression
  test (see below).

## Known limitations / quirks found live

1. **Live verification (phase 1).** Handshake + 8-byte framing accepted
   by the real r8 server; `GetVersionInfo` returns DF 0.47.05 / DFHack
   0.47.05-r8 / RFR 0.21.0; `RunCommand("lua", ...)` returns TEXT.
   `SetPauseState` works and sticks (verified by re-reading
   `GetPauseState`). See PROTOCOL.md §8 for the resolved open questions.
   Note: PROTOCOL.md says DFHack r5 in places; the installed server is
   **r8** — the wire protocol is unchanged.
2. **CP437 in RPC TEXT fragments (client bug, fixed).** The protobuf
   runtime returns `bytes` (not `str`) for a `string` field whose bytes
   are not valid UTF-8. DF sends CP437 bytes (dwarf names: 0x84 = ä),
   so `run_lua` crashed with `TypeError: sequence item 0: expected str
   instance, bytes found` on any output containing a non-ASCII name.
   Fixed in `dfhack_rpc/client.py` (`_collect_reply` decodes each
   fragment with `decode_df_string`); regression test in
   `tests/test_client.py`. The Lua JSON encoder maps CP437 bytes to
   Unicode in the JSON itself, so observe output was never affected —
   only raw `print()` output was.
3. **UI "Idlers" ≠ jobless count (open).** The UI status bar shows
   `Idlers: 2` while all 7 citizens have no `current_job` and no path,
   and the count stays 2 after 2.5 game days of running. The UI's
   definition of "idler" is unknown (possibly excludes dwarves in
   non-job activities such as socializing). The layer therefore reports
   `population.jobless` (citizens with no `current_job` — precisely
   defined) and does **not** claim to match the UI number.
4. **Hunger/thirst/sleepiness thresholds unknown.** `counters2` timers
   are reported raw (ticks since last satisfied). What values mean
   "hungry" / "thirsty" / "exhausted" is not established — do not
   invent thresholds until phase 3 measures them on a live fort.
5. **Manager orders and announcements verified on non-empty data
   (phase 2, 2026-11-25/26).** Manager orders were exercised by
   creating/removing a MakeBarrel x5 order; announcements by the
   build-cancellation and weather entries. Combat reports are still
   unverified on non-empty data (no combat on this fort).
6. **Jobs enumeration verified on non-empty lists (phase 2).** The
   `world.jobs` linked-list walk (`.item` / `.next`) was confirmed
   against FellTree, Dig, GatherPlants, Drink2, RecoverWounded and
   ConstructBuilding jobs. One caveat lives in the action layer, not
   the observation layer: see `docs/ACTIONS.md` (FellTree jobs are
   never removed from the list by the game).
7. **Designation scan is slow (~4 s).** Full block scan, 8352 blocks ×
   256 tiles. Opt-in only. Job counts by type are the cheap proxy for
   designation activity in the default dump.
8. **FPS is ticks/second, not a game counter.** No FPS value is exposed
   by DFHack r8's Lua (`df.global.fps` does not exist,
   `dfhack.getFPS` does not exist). `--fps` samples `cur_year_tick`
   twice 1 s apart while unpaused. It measured ~117/s on this VM at
   this fort size (above the nominal 100 cap — the cap setting was not
   investigated). While paused it is `null`.
9. **Quicksave blocks RPC for ~30-40 s.** While a `quicksave` is
   writing, the RPC server stops answering (observed: version call
   timed out after 30 s, a section returned empty text). The collector
   survives this — failed sections land in `errors`, exit code stays
   0 — but do not observe concurrently with a save, and treat a
   timeout during a save as "game busy", not "game dead".
10. **DFHack Lua is slow at function calls.** Measured in-game:
    arithmetic is fast, but each Lua function call costs ~75 µs
    (and per-byte `string.sub` ~80 µs/byte — 10 k subs ≈ 0.8 s).
    Consequences: the JSON encoder uses `gsub` (not per-byte loops)
    and skips key-sorting and array-detection passes. Full default
    observe still takes ~1.6 s (units ~0.9 s, stocks ~0.5 s, the rest
    ~0.1 s). Per-section timings are in the phase-1 log.
11. **Map summary is shallow.** No water-tile counts, no cavern info,
    no site features: those need a block scan (slow, see 7) or struct
    fields that were not found (`world.map.features`,
    `world.map.underground_regions` do not exist in this build).
    `region_x`/`region_y` are reported as-is; they are **not** world
    map tile coordinates (values 12, 92 exceed the 65×65 world).
12. **embark-assistant's info overlay overlaps DF's own panel text**
    at 1024×768, making its resource lines hard to read in
    screenshots. The finder itself works (see the phase-1 log for its
    key bindings — `f` opens the *assistant* finder from the plain
    embark screen, lowercase `f` starts the search, **not** `F`).

## Model presentation

This section is required by the 2026-11-27 presentation constraint
(GOAL.md, coordinator log 2026-11-27 ~17:47 PT): every new system
must state how its information reaches the model, what it costs,
and what it deliberately does not push. The snapshot stays an
index: counts, exceptions, and diffs only, about 4,700 tokens
typical, never a replacement for full state. Budgets hold (target
30K, warning 60K, compaction 100K, hard cap 140K on a 200K
window), enforced by the assembler's token accountant with its
cut order. No system bolts its own dump onto the snapshot.

This doc is the observation layer, so its product IS the
presentation: the state document (§Schema) rendered as the
per-tick snapshot text (§Text rendering). There is no separate
system to present; this section states what the layer pushes,
what it costs, and what it refuses.

### Snapshot: the whole snapshot, in sections

The per-tick snapshot is the observation layer rendered as text:
header, attention, goals, status, materials, stocks, units,
entities, buildings, jobs, placement, reports, areas, events,
history, and the per-system sections each design doc specifies.
Each section is counts, exceptions, and diffs only, built from
the fresh collect, in plain words. Each section is hashed and
compared with the Store's last snapshot for that section; an
unchanged section prints its short form ("buildings: unchanged"),
so the snapshot costs its full price only on ticks when state
actually moves. The assembler drops secondary sections by
priority when the total would exceed the target, and THREATS,
ATTENTION, and FAILURE FEEDBACK are never cut.

**Token cost.** At 7 dwarves the snapshot is about 4,700 tokens
typical (the figure the presentation constraint states). At 50
dwarves it is larger, but it does not grow linearly with
population: the per-section caps (8 exceptions in Units, 3
workshop clauses per system section, 3 opportunities) and the
accountant's cut order hold it under the 30K target, with the
60K warning and 100K compaction thresholds behind it. The exact
cost at 50 dwarves is UNVERIFIED: no 50-dwarf fort has been
assembled and measured live. The invariant is stated in
assembler.py: no section of the per-tick snapshot may grow
linearly with population. If a section does, the section is
capped or cut, not the budget raised.

### Query route: GET /v1/snapshot (live)

GET /v1/snapshot returns the assembled snapshot text, read from
the fresh collect. The full state document behind it is behind
GET /v1/state. The agent asks for the snapshot once per decision
tick and queries the detail routes when it needs to choose, never
as a matter of routine. The schema (`schema_version: 1`) is
versioned so the model can tell when the shape changes.

### Briefing: none from this layer

Observation does not brief. Briefings come from briefings.py,
fired by events, each a few hundred tokens at most. The
observation layer's job is to make the state true and current;
the briefing layer's job is to say what just happened. An
observation section never carries briefing text.

### Opportunities: none from this layer

Observation does not suggest. The opportunities section carries
at most 3 entries per tick, each from a system doc, each facts
plus a query route. The observation layer reports state; the
systems decide what is actionable. An observation entry that
suggested an action would be the layer choosing for the model.

### What the system deliberately does NOT push, and why

- **The full state document.** The state document is behind
  GET /v1/state. The snapshot is the index. A full state dump
  every tick would break the budgets this section states.
- **Per-tile data.** Where each item, boulder, or tile sits is
  survey data, pulled by region when the model needs it. The
  snapshot never carries the map.
- **Raw JSON.** The snapshot is plain words, never raw JSON.
  Numbers carry units and floors. A number without its unit and
  its floor is a number the agent cannot act on.
- **Stale state.** The snapshot is built from the fresh collect,
  never from the daemon's cached status (which shows stale
  zeros). When a collect fails, the section says so ("Stocks:
  unavailable (section failed to collect)"), never a stale
  number presented as fresh.
