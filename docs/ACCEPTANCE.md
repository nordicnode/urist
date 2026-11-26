# DF Agent Harness — Acceptance

Measurable criteria for "the harness plays the fort". Measured
against Fort Athelunol (Summer 306, tick 168875 baseline, 15
citizens) with the phase-4 daemon + planner. Numbers, not vibes.

## Criteria and how each is measured

| # | Criterion | How it is measured |
|---|---|---|
| (a) | Fort survives 2+ in-game years with zero starvation/thirst deaths | Game tick advances ≥806,400 (2 × 403,200 ticks/year) with no `unit_death` for a citizen and no "found dead, dehydrated/starved" report. Deaths are read from `events.jsonl` (eventful `unit_death` + reports) and the live citizen list — `citizen_gone` alone is NOT evidence (it fires spuriously on empty-units snapshots after restarts). |
| (b) | Food + drink stocks stay above survival thresholds across the run | `observe.collect` stocks: drink >5u and food >5u at every planner tick's snapshot (thresholds: `drink_critical` 5, `food_critical` 5). |
| (c) | Planner responds to a hostile spawn within N ticks (shelter or military stationing issued + verified) | A new hostile appears in `units.hostiles`; within 1 planner tick (30 s wall, ~1,100 game ticks at 37 t/s) the journal shows a `threat:hold` (pause) or `threat:watch` decision for it, and the game state shows the pause (hold) or the log (watch). |
| (d) | Fort expands — population and/or building count and production grow over the run | Citizens, building count, and drink/food produced (stocks delta + jobs completed) at run start vs run end, from `observe.collect` snapshots. |
| (e) | No dwarf dies of neglect the planner could have prevented (stress spiral / untreated wounds) | Zero citizen deaths attributable to a need the planner covers (drink, food, shelter) during a window in which the daemon ran continuously. Deaths during windows when the daemon was down/stalled are reported separately, not hidden. |

A game year is 403,200 ticks (~3 h wall at 37 t/s with a caravan
present) — a 2-year run is ~6 h wall. The criteria below were
measured over the phase-4 shakedown window (tick 168875 → ~231622,
~62,700 ticks ≈ 0.16 game-years), not a full 2-year run.

## Results (2026-11-26 shakedown window)

| # | Result | Measured evidence |
|---|---|---|
| (a) | **FAIL** | 5 citizens died of dehydration: Kogan Mûthkatost (Dwarven Child, tick 224421), Feb Rilbetfath (Dwarven Child, tick 226373), Datan Erushninur (tick 224971), Nil Idòeton (Bone Carver, tick ~230445), Deler Stûeegilstinthäd (gone, cause unrecorded in the event log). Duration also unmet: the run covered ~0.16 game-years, not 2+. |
| (b) | **FAIL** | Drink 2u at baseline → 0u for the entire window; food 23u → 0u. Never above the 5u critical threshold after the first ticks. The still never brewed (no brewable plants in stock). |
| (c) | **PARTIAL / untested-live for a fresh spawn** | The planner tiered the 3 pre-existing eagles correctly (18 `threat` decisions in the journal: `threat:watch` log + `threat:hold` pause when ≤5 tiles). No NEW hostile spawn was observed during the window, so the spawn-response latency was never measured. |
| (d) | **FAIL (mixed)** | Buildings grew 0 → 6 (still #14, carpenters #15/#17, farm #18, stockpile #20; a 3rd carpenter #21 existed only in memory). Population FELL 15 → 10 (the 5 thirst deaths). Production: 0 drink and 0 food produced (no brew/cook ever completed). |
| (e) | **FAIL** | The 5 thirst deaths in (a) are neglect the planner could have prevented in principle (gather → brew), but the daemon was stalled (planner stall #1, 20+ min liaison freeze) or crashing through the critical window, and the gather → haul → brew chain never produced drink in time. Cause is harness instability, not a planner logic gap. |

## Daemon stability (the blocker under the results above)

| Measure | Value |
|---|---|
| Game crashes in the 2026-11-26 window | 9 (05:36, 05:44, 05:50, 05:55, 06:00, 06:03, ~06:16, ~06:25 load abort, ~06:31) |
| Crash signatures | `free(): double free detected in tcache 2` (×2, after the liaison meeting ended); abort at "Resetting textures" on startup and on map load (×4+); cause unknown for the rest (stderr.log is truncated on each relaunch, so the message is lost) |
| Longest crash-free daemon+game stretch | ~12 min (daemon 25119, 05:48–06:00); the 06:15 and 06:30 restarts each died ~1 min after tick 1 |
| Cell reboot during the window | 1 (06:31, killed DF + daemon + Xvfb, wiped apt packages; recovered via `recover.sh` fallbacks) |
| Acceptance window completed | No — a 15–20 min continuous unpaused run was never achieved |
| **Control test (daemon stopped)** | **06:43: fort loaded cleanly (tick 229288), game unpaused, daemon stopped — DF crashed ~1 min later.** The daemon is exonerated as the crash cause; the crash is in the game/fort state during unpaused play. The game is stable while paused. |
| Correlation (unproven) | The fort ran unpaused with no crashes 05:00–05:44; crashes began exactly when the thirst deaths began (first death tick 224421 ≈ 05:44). Suspect: a dwarf dying (death announcement / DFHack eventful hook) or the death cascade. Next diagnostics: run with the watcher not installed (eventful disabled); load the 04:07 seasonal-autosave backup (`data/save/region1-00306-07-01/world.sav`, pre-deaths, 15 citizens) and run it unpaused — if it survives 5 min, the 06:16:04 save (written by the quicksave seconds before crash #7) is corrupt and the fort should roll back to it. |

## What the fixes changed (verified)

- **Focus-first gate** (poller + planner probe focus before any
  world-state read): the 05:54:34 save loaded cleanly with the
  daemon stopped, and a later load with the daemon running also
  completed — the mid-load RPC crash path is closed, though the
  flaky load abort ("Resetting textures") still occurs with the
  daemon stopped, so it is not solely a daemon trigger.
- **Missing-section rule**: no duplicate builds since the fix (the
  3rd carpenter #21 never made it into a save; the loaded fort has
  2 carpenters).
- **Poll tuning** (fast 2.0→6.0 s, slow 30→60 s): RPC saturation
  ~98% → ~40%; no 30 s timeouts observed after the change.
- **First-tick quicksave fix**: no quicksave on daemon start (was
  firing ~30 s after start).
- **Unit tests**: 129 passed (was 122; +7 new: 4 missing-section
  cases, 3 `fort_loaded` cases).

## Runner

`tests/test_acceptance.py` (unit-level checks of the criteria
logic) + `scripts/acceptance_run.py` (live: starts the daemon
against Athelunol for a bounded window and records before/after
snapshots). The live runner needs the game up and loaded; it exits
non-zero with the reason when the game is down or the run is
interrupted by a crash, rather than reporting a pass.

## What remains before "100% working"

1. **Game stability**: the crash cluster is the blocker. The next
   step is a control test — run the fort unpaused with the daemon
   STOPPED for 5 min. If it crashes, the fort/game state is the
   problem, not the daemon; if it survives, the daemon's RPC load
   is the trigger and the poller needs further throttling.
2. **Brew end-to-end**: gather → haul → brew has never produced a
   unit of drink. Needs a window in which the game stays up long
   enough for plants to be gathered, hauled, and brewed.
3. **Bed placement + manager-order-worked verification**: queued
   but never verified live.
4. **Farm crop configuration** (`q` menu), **military**, **hospital**,
   **bookkeeper/broker**: not implemented (see PLANNER.md).
5. **A full 2-year run** (~6 h wall) with the daemon running
   continuously — requires (1) first.
6. **Daemon restart persistence**: drain-offset no-replay is
   implemented but the replay check is still pending; the daemon
   does not reinstall the watcher into a relaunched DF.
