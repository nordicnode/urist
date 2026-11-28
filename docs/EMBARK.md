# EMBARK.md — the embark module

The embark module (`src/dfagent_harness/embark.py`, driver
`scripts/embark.py`, Lua helpers `probe_embark.lua`,
`read_match_grid.lua`, `probe_fort_loaded.lua`) takes a generated
world, screens it for a site that meets the criteria, embarks there,
and verifies the fort loaded. It is the M2 entry point: M2's first
season runs start from a fort this module embarked.

## Why this is keystrokes, not API

There is no non-UI way to embark in DFHack 0.47.05-r8. Embark and
save-load keystrokes are the sanctioned exception to the
everything-through-the-harness-API rule (AGENTS.md): they are
pre-game setup, quarantined in this module. Every step verifies its
effect by re-reading game state through the RPC Lua helpers — a
keystroke sequence is never trusted on its own.

## The proven path

```
generate world (seeded -gen)
  -> Title -> "Start Playing" (Down once from Continue Playing)
  -> the world loads (viewscreen_adopt_regionst, a pure loading
     screen) -> viewscreen_choose_start_sitest (the embark screen)
     directly — there is NO mode-selection screen and NO extra
     Return after adopt (an extra Return once selected Adventurer)
  -> write the finder profile
  -> embark-assistant fileresult (quit the overlay first; trust the
     FILE, which lives under data/init/; run it via the Lua
     dfhack.run_command — the direct RPC RunCommand does not deliver
     the "fileresult" argument to this plugin)
  -> the overlay is already active (fileresult activated it);
     full finder (f), Load (l), Find (f)
  -> read the match grid via dfhack.screen.readTile
  -> move the region cursor by arrow keys to a match
  -> quit the overlay (q) — the rect keys are intercepted while it
     is open — then position the embark rectangle by Lua (set_rect)
  -> e -> "Play Now!" -> arrival text -> fortress mode
  -> verify the fort loaded (dwarves, wagon, stocks)
```

"Start Playing" appears on the title screen only when a world
without a fort exists. It was absent while region1/region3 both had
forts, and appeared once region4 was generated. Generate a world
first if it is absent; do not press Down expecting Start Playing.

Verified live 2026-11-27 on region3 (scratch DF): the M2 profile
(ZINC) gives 42 matches; the embark landed at world (25,55)-(28,58),
fort Momuzgdoth ("Cryptbows"), year 189-01-15, 7 citizens, wagon,
drink 60, paused, quicksaved. Verified again the same day on
region4: M2 profile gives 12 matches; the embark landed at world
(10,41), "The Laconic Jungles" (Temperate Conifer Forest, Warm,
Heavily Forested, Thick vegetation, Wilderness, flux stone layer,
shallow + deep metal, sand, soil), year 440-01-15, 7 citizens,
wagon, drink 60, paused, quicksaved.

## The M2 site criteria

The finder screens the must-haves; metal is guaranteed by the finder
itself (no Lua tile read needed):

| Criterion | Value | Why |
|---|---|---|
| X / Y Dimension | 4 | 4x4 embark |
| High Savagery | Absent | no savage wildlife |
| Evil | Absent | no evil/haunted |
| Aquifer | None | no aquifer |
| Min River | Brook | water on site |
| Flux | Present | flux stone for steel |
| Min Soil | Shallow | soil for farming |
| Min Soil Everywhere | All | soil across the whole site |
| Freezing | Never Frozen | temperate |
| Blood Rain / Syndrome Rain | No / No Syndrome | no evil weather |
| Reanimation | None | no reanimation |
| Min Trees | Woodland | wood supply |
| Metal 1 | ZINC | a metal the finder can guarantee |

IRON gives 0 matches on region3 (iron lives in mountains, which lack
soil/trees). The metal sweep (all 11 region3 metals vs the full
profile): COPPER 12, GOLD 14, NICKEL 6, SILVER 12, ZINC 42; the rest
0. ZINC is the pick. On a new world, re-run the metal sweep and pick
the metal with a nonzero intersection.

## Hard-won facts (do not re-litigate)

**The rect and the cursor are independent.** The embark rectangle
(`embark_pos_min/max`) does NOT follow the region cursor. `e`
embarks the rect, so the rect must be positioned on the match.

**Local-area keys are u/m/h/k.** The bottom bar reads "umhk", not
"u/h/k/l". `u` = up, `m` = down, `h` = left, `k` = right; one tile
per key. `l` does nothing. Do not press `l` expecting a move, and
do not press unknown keys on the embark screen (`s` and `j` open
the DFHack "Embark tools" popup).

**Key registration is flaky.** At this VM's ~7 FPS only ~30-50% of
presses register. Send in small batches and re-read the rect after
each batch; never trust a blind count. Single-step arrow keys for
the cursor ARE exact; Shift+arrows move an unreliable distance and
are never used.

**NEVER write `region_pos` via Lua.** Setting the cursor directly
crashed the game. Move the cursor by arrow keys only.

**A Lua rect write is safe, and `e` usually works right after it.**
Writing `embark_pos_min/max` via Lua does not crash. On region3
`e` was silently rejected after a Lua-only set until a `u`+`m` key
round-trip; on region4 `e` worked immediately after the Lua write
with no round-trip. The rect keys (u/m/h/k) do NOT move the rect at
all after a Lua write on region4 (8 keypresses, no movement in any
direction), and the keys-only `move_rect_to()` stalls on long moves
(rect stuck at y=12 after 40 rounds). So: position the rect with
`set_rect()` (Lua write, best-effort u/m round-trip that never
fails), and let the `e` press be the real acceptance test. Do not
rely on the rect keys for positioning.

**`embark-assistant fileresult` activates the overlay.** Every
invocation (with or without `fileresult`) creates the plugin state
and calls `overlay::setup`. A second call fails with "already
active" until the overlay is quit (`q`). The overlay's "Matching
World Tiles" count can disagree with the fileresult FILE — trust
the FILE. `run_fileresult()` retries once after quitting the
overlay. The file lives under `data/init/` (NOT the DF root), and
the plugin must be enabled (`enable embark-assistant` — the scratch
DF's `dfhack-config/enable` file did not exist, so a fresh DF needs
it enabled once). Run fileresult via the Lua
`dfhack.run_command("embark-assistant", "fileresult")`: the direct
RPC `run_command("embark-assistant", "fileresult")` does not
deliver the argument to this plugin command (it comes back
CR_WRONG_USAGE / the help text), while the Lua route writes the
file. The overlay must be quit (`q`) before moving the rect: with
it open the rect keys are intercepted. `dfhack.screen.getWindowSize`
returns (width, height) as two values, not a table — index it and
the helper dies. The Lua JSON encoder returns a Lua array as an
object with string numeric keys, so `read_match_grid` normalises
matches to a list in Python.

**The full Site Finder does not load the profile on open.** It
starts all N/A. Press `l` (Load) in the finder, then `f` (Find).
The `s`/`l` keys live only in the full finder; pressing `s` in the
overlay does nothing. `f` on the embark screen opens DF's vanilla
finder, not embark-assistant.

**Find does not move the cursor to a match.** It builds a match
grid (green X = match, yellow X = preliminary) and moves the cursor
back to where it started. The driver must move the cursor to a
green X. The grid is read off the screen with
`dfhack.screen.readTile` (the region view, 1:1; the minimap is
lossy). The overlay is not a viewscreen, so it cannot be detected
via the viewscreen stack; the fileresult error text is the
detector.

**`region_map` is unreadable from Lua.** It is a
`region_map_entry**`; `region_map[x]` returns the struct at
`region_map[x][0]` and `[y]` on it fails, and a flat index crashed
the game. Do not flat-index it and do not dump an entry obtained by
a suspect access. Read the match grid off the screen instead.

**World-gen gotchas.** The `-gen` preset stanza must be complete
(a truncated copy caused 148k map rejections). A partial
`data/save/region<N>` left by an aborted `-gen` makes later `-gen`
runs abort — delete the partial dir first (or use a fresh region
number). `-gen` generates the world and exits; it does not land on
the embark screen. "Continue Playing" only loads saved forts.

## Module functions

- `write_profile(df_dir, profile, civs)` — writes
  `embark_assistant_profile.txt` (fields in enum order, then one
  `[<CIV>:N/A]` per civ). Civs default to the lines already in the
  file, else `DEFAULT_CIVS`.
- `run_fileresult(client, df_dir, wid, display)` — screens the
  world; returns the match count from the FILE. Retries once after
  quitting an active overlay.
- `probe_embark(client)` — cursor, rect, biome index (Lua).
- `read_match_grid(client)` — matching world tiles in the current
  viewport (green X only; yellow X is preliminary).
- `scan_matches(client, wid, display)` — all matches, by sweeping
  the cursor through viewport centres over the whole world.
- `move_cursor_to(client, wid, display, x, y)` — arrow keys,
  verified, retries the remaining delta.
- `move_rect_to(client, wid, display, x, y)` — u/m/h/k keys in
  small batches with re-reads until the rect converges.
- `set_rect(client, wid, display, x, y, w, h)` — Lua rect write +
  best-effort key round-trip re-sync (never fails on the round-trip;
  `e` is the real acceptance test). The reliable rect positioner;
  prefer over `move_rect_to`.
- `embark(client, wid, display)` — `e` -> setup screen -> "Play
  Now!" -> arrival text -> fortress mode, then `verify_fort_loaded`.
- `verify_fort_loaded(client)` — citizens, wagon, drink/food/wood,
  date, paused (Lua).
- `generate_world(df_dir, region_num, seed, preset)` — seeded
  `-gen` (deletes a stale partial region dir first).
- `navigate_to_embark_screen(client, wid, display)` — Title ->
  Start Playing -> adopt (loading) -> embark screen, verified at
  each step. No extra Return after adopt.
- `embark_site(client, df_dir, wid, display, profile, civs)` —
  the full run: profile -> fileresult -> finder Load/Find ->
  scan -> cursor + rect to the first match -> embark -> verify.

## Driver

```
# Full run: gen + launch + navigate + embark (scratch DF, :98, 5001)
.venv/bin/python scripts/embark.py --df-dir scratch/m2-embark/df \
    --display :98 --port 5001 --region 3 --seed 20261128 --full

# Just screen a world that is already on the embark screen
.venv/bin/python scripts/embark.py --df-dir scratch/m2-embark/df \
    --display :98 --port 5001 --screen-only

# Just generate a world
.venv/bin/python scripts/embark.py --df-dir scratch/m2-embark/df \
    --region 4 --seed 20261128 --gen
```

The driver never touches the main fort's DF (third_party/df_47_05,
:99, 5000) unless you point it at it — do not.

## Tests

- `tests/test_embark.py` — offline: profile formatting and
  round-trip, fileresult file parsing, viewport/match-grid
  coordinate math, key mapping, the scan sweep positions.
- `tests/test_embark_live.py` — live, against the scratch DF on
  the embark screen: probe_embark, read_match_grid, fileresult
  count, and a cursor/rect move that returns to its start (no
  embark — the live embark is proven by the driver run, not the
  unit test).

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

### Snapshot: nothing from embark, except the starting state

Embark is pre-game. Nothing from this doc enters the per-tick
snapshot except the starting state it produces: the fort's
position, its dwarves, its items, and its site, all of which the
snapshot carries through the normal sections (Units, Stocks,
Buildings, Areas). The embark profile, the finder criteria, the
match grid, and the world-gen seed are not pushed. The model
plays the fort it has, not the fort it might have embarked on.

**Token cost.** At 7 dwarves and at 50 dwarves alike, embark
costs 0 tokens in the snapshot: there is no embark section to
render. The starting state is carried by the normal sections,
whose costs are stated in their own docs. Embark adds nothing
on top at any population.

### Query route: none live; the module is the route

There is no embark query route, and there must not be one
during play: embark is over once the fort loads. The embark
module (`embark.py`) is the route, used before play: seeded
world gen, the fixed finder profile, the deterministic pick rule
(first match, topmost then leftmost), and the full flow through
`embark_site()`, proven live. The world seed and profile are
recorded in the run log and the scores.db row, so a run can be
reproduced, never so the model can re-embark mid-run.

### Briefing: none from this layer

Embark does not brief. The first briefing a model gets is the
first event after the fort loads. The embark itself is setup,
not play, and the model is never briefed about setup.

### Opportunities: none from this layer

Embark is not an opportunity. The site criteria (§The M2 site
criteria) are harness policy for choosing a start, not facts
about the fort the model can act on once play begins.

### What the system deliberately does NOT push, and why

- **The match grid.** The finder match grid is setup data. The
  model never sees it. Pushing it would be a dump of a
  decision already made.
- **The world seed as a suggestion.** The seed is recorded for
  reproducibility. It is never presented as something the model
  should use or change.
- **Keystrokes.** Embark is keystrokes by necessity (§Why this
  is keystrokes, not API): it is pre-game setup, quarantined,
  the only exception to the no-keystrokes rule. The keystrokes
  are never presented to the model as actions it can take.
- **The site criteria as advice.** The M2 site criteria are
  harness policy for choosing a start. Once the fort loads,
  the model plays the site it has. The criteria are not advice
  about where to dig.
