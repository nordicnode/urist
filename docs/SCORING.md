# Scoring: benchmarking AI models on Urist (GOAL.md item 15)

A smart, sophisticated scoring system so different AI models can be
benchmarked against each other on the same fort. Computed by the
HARNESS from live game state, the run log, and the store — never
self-reported by the model. Same start conditions for every run
(clean 04-01 base, fixed tick budget), so scores are comparable.

## The score

One headline composite (0–100) plus a per-dimension breakdown, so a
score never hides a tradeoff. Survival and lives dominate; wealth is
low; milestones are a bonus, so building cheap junk to inflate value
cannot win.

| Dimension   | Weight | What it measures |
|-------------|--------|------------------|
| survival    | 30     | In-game days lasted vs the run's planned duration |
| lives       | 30     | Citizen deaths; preventable (thirst/starvation) penalised heaviest, then combat, then mood/other |
| wealth      | 10     | Fortress-value growth (end − start) / start |
| needs       | 10     | Drink/food never hitting zero; no dwarf left dangerously hungry/thirsty |
| growth      | 5      | Population change, workshops built, beds/rooms completed |
| competence  | 10     | Idle ticks, failed actions, repeated failures, model reliability, suggestion handling |
| threats     | 5      | Dwarves lost to hostiles |
| milestones  | +2 each (cap +10) | First brew, first bed, first farm, first trade, first mood resolved |

The composite is the weighted sum (0–100) plus the milestone bonus,
capped at 100.

### Dimension definitions (exact)

- **Survival.** `100 × days_lasted / days_planned`, clamped 0–100.
  A run that lasts its full planned duration scores 100; a fort that
  dies early scores in proportion to how far it got.
- **Lives.** Start at 100; each citizen death penalised by kind:
  preventable (thirst/starvation) −40, combat −20, mood −15,
  other −10; clamped at 0. A fort that lets a dwarf die of thirst
  has failed at the one thing M1 exists to prove.
- **Wealth.** Centred on 50 (no change scores 50, not 0 — a fort
  that held its value did not fail): `50 + growth_pct`, clamped
  0–100. +1 point per percentage point of fortress-value growth.
  Without both a start and an end reading the dimension is neutral
  50 and the breakdown says so (`wealth_known: false`).
- **Needs.** 100 minus 50 if drink or food hit zero at any sampled
  tick, minus up to 50 for the fraction of citizen-time spent
  dangerously hungry/thirsty. "Dangerously" means the counter is far
  above the eat/drink trigger (hunger ≥ 50,000, thirst ≥ 30,000 —
  the triggers are ~40,000 / ~20,000, measured live in phase 1), so
  the dwarf could not eat/drink when it needed to. Normal drinking
  (thirst up to ~20,000) does not penalise.
- **Growth.** 50 base + 10 per workshop built (cap +20) + 5 per bed
  completed (cap +15) + 5 per net population gained (cap +15).
  Population loss does not penalise here — deaths are already
  counted in lives; growth measures what the fort built.
- **Competence.** 100 minus 10 per idle tick, 5 per failed action,
  10 per repeated failure (the same action failing twice or more —
  the failure memory the design demands), 5 per model failure (a
  Free Pi IncompleteRead counts here: model reliability is part of
  competence), and up to 5 for ignoring the snapshot's suggestions
  (proportional to the fraction ignored; no suggestions means no
  penalty). A correct fail-fast that names the fix is still a failed
  action — the model asked for something it could not do — but it is
  only 5 points, and the suggestion penalty is where ignoring the
  named fix shows up.
- **Threats.** 100 minus 20 per dwarf lost to hostiles. Facing a
  threat and surviving it with no losses scores 100 — the dimension
  measures what threats cost, not whether any appeared.
- **Milestones.** +2 each (cap +10): first brew, first bed, first
  farm, first trade, first mood resolved. See "Milestone detection"
  below for what counts as evidence.

### Where each number comes from

- **Survival, actions, model failures, idle ticks, suggestions:**
  the run log (`logs/m1-*.jsonl`).
- **Deaths (kind + cause):** the store's `deaths` table
  (`world.db`), filtered to the run's tick range. The store is the
  authority; the events journal is a cross-check only.
- **Needs (dangerous counters):** the store's `unit_history` in the
  run's tick range. The poller is paused during M1 runs, so trends
  are empty in the run range — the score reads the log's snapshot
  stocks lines for zero-stock ticks and `unit_history` for the
  counters.
- **Wealth:** the run log's `wealth` records (the driver logs
  fortress value at run start and run end via `GET /v1/wealth`),
  or `--wealth-start` / `--wealth-end` on the CLI for an older log.
  The score never probes the live game on its own (the game may have
  moved on from the run's end state).
- **Threats faced** (evidence only, not scored): `threat` /
  `hostile_spawn` events in the run window, from the daemon's
  `events.jsonl`.

Every score carries an `evidence` block with all of these inputs, so
a score can be audited, never just asserted.

## Wealth: what fortress value is (and is not)

There is **no direct wealth read in DFHack 0.47.05-r8**:
`df.global.ui` has no `wealth` field, and `dfhack.economy` is nil
(verified live 2026-11-27). The in-game z-screen "created wealth"
is NOT directly readable.

Fortress value is computed live by `lua/wealth.lua` and served by
`GET /v1/wealth`: the sum of `dfhack.items.getValue` over the fort's
own items — `df.global.world.items.other.IN_PLAY` (the same list
`stocks.lua` uses, NOT `world.items.all`, which holds wild items
and abstract world artifacts), excluding:

- trader-held goods (same container/holder walk `stocks.lua` uses),
- items lying on the ground (`flags.on_ground` — 473 wild items on
  the clean base),
- abstract world artifacts (pos −30000, flagged artifact, no
  `in_inventory` / `in_building` / `in_job` / `owned` flag).

Measured live: clean base 125-04-01 fortress value **5,418☼**
(183 items, created 5); run-end 125-04-02 **5,410☼** (183 items,
created 5). The 5 non-foreign items are five SEEDS at 1☼ each —
noise, not a meaningful "created" sub-number.

`item.flags.owned` is NOT fortress wealth: it marks items owned by
a SPECIFIC dwarf (personal clothing) — 70 items, 3,956☼, all
clothing/armor on the clean base. It does not move with production
and must never be used as wealth.

The scoring wealth dimension uses **fortress value (total item
value, imports + created) and its growth**, NOT the z-screen
created wealth — the module never claims otherwise. The wiki
(Wealth page) confirms created wealth is the sum of all objects of
value in the fortress; the z-screen number itself is not reachable,
so the score uses the total and says so.

## Milestone detection (conservative)

A milestone counts only on positive evidence, never on a queue:

- **First brew:** a brew was queued successfully AND drink rose
  across the run's snapshots (brewing adds 5 drink per brew;
  dwarves drinking pulls it down, so a net rise means brewing
  outpaced drinking).
- **First bed:** a make_bed was queued successfully AND a later
  snapshot shows a BED item available to place (`have ≥ 1` on the
  material-awareness line).
- **First farm / first trade / first mood resolved:** not yet
  detectable from the log (no plant action, no trade event, no mood
  event in the harness) — always False, documented here. They
  become detectable when those systems land; the code must not claim
  them before then.

## Suggestion matching

The snapshot's suggestion is free-form prose ("Suggested action: ...
build_workshop kind=still ...", "run the brew task (POST
/v1/tasks/brew)", "queue make_barrel at the carpenter #7"). Both
sides are normalised to a job string; a tick matches when any action
that tick has the same job. Matching on the job (not the verb) is
deliberate: the tick-2 suggestion says "run the brew task" and the
model queued brew via queue_job — same intent, different verb — and
that counts as followed. A tick whose suggestion has no extractable
job is skipped, not penalised. When a suggestion names two jobs in
sequence ("queue make_barrel ... Only then run the brew task"), the
immediate job wins (the pattern order puts the actionable job
first). The run's final snapshot is excluded: the driver ends the
run on that snapshot (day complete / fort dead / hard error) BEFORE
calling the model, so the model never acts on its suggestion, and
counting it as ignored would be a systematic one-tick penalty on
every run.

## The leaderboard

Scores are stored in `scores.db` in the daemon state dir
(`~/.config/df-agent-harness/scores.db`) with model, start save,
tick budget, and date, so runs accumulate into a real comparison.
A run log is scored at most once per model — re-scoring the same
log replaces its row (the score is a function of the log, not of
when it was computed).

DF's own RNG means exact reproducibility may not hold — the
leaderboard records the date and the run log, and repeat runs
should be averaged where it matters.

## Usage

```sh
# Score a run (wealth from the log's wealth records)
.venv/bin/python scripts/score_run.py logs/m1-20261127-071025.jsonl

# Score an older log without wealth records (measured live)
.venv/bin/python scripts/score_run.py logs/m1-20261127-071025.jsonl \
    --wealth-start 5418 --wealth-end 5410

# Score and record in the leaderboard
.venv/bin/python scripts/score_run.py logs/m1-....jsonl --record

# List the leaderboard
.venv/bin/python scripts/score_run.py --leaderboard
.venv/bin/python scripts/score_run.py --leaderboard --model deepseek-v4.1-flash
```

## First verified scores

Run `m1-20261127-071025.jsonl` (DeepSeek V4.1 Flash, 1 day,
125-04-01, clean base), verified live 2026-11-27:

- **Composite 91.8 / 100.** Survival 100, lives 100, wealth 49.9
  (−0.15% growth), needs 100, growth 60 (Still built, 0 beds,
  pop 7→7), competence 88.0 (1 failed action — the correct
  material-shortage fail-fast — 1 Free Pi IncompleteRead, 3/5
  suggestions followed), threats 100. Milestones: none (no brew
  completed within the run's 1,324 ticks — drink 38→34; no bed —
  "Bed: ... have 0" throughout).

The 3/5 suggestion count is read from the log, not hand-counted:
ticks 1, 2, 4 followed; tick 3 (make_barrel suggested, make_bed
queued) and tick 5 (make_barrel suggested, no action — a model
failure) not followed. The tick-6 snapshot is the run's final one
and is excluded (see "Suggestion matching").

Run `m1-20261127-073557.jsonl` (DeepSeek V4.1 Flash, 1 day,
125-04-01, clean base), verified live 2026-11-27 — the first run
scored with wealth from the log's own `wealth` records (no
`--wealth` arguments):

- **Composite 91.7 / 100.** Survival 100, lives 100, wealth 49.8
  (−0.18% growth, 5418→5408), needs 100, growth 60 (Still built,
  0 beds, pop 7→7), competence 87.5 (0 failed actions, 2 Free Pi
  IncompleteReads, 2/4 suggestions followed), threats 100.
  Milestones: none (drink 38→33; the brews were queued but had not
  completed within the run's ticks).

Both runs are in the leaderboard (`scores.db`).

## Files

- `src/dfagent_harness/scoring.py` — the scoring module (dimensions,
  log parsing, suggestion matching, `compute_score`, `Leaderboard`).
- `src/dfagent_harness/lua/wealth.lua` — the fortress-value probe.
- `src/dfagent_harness/observe.py` — "wealth" section (on-demand
  only, not in the per-tick fast sections).
- `src/dfagent_harness/server/routes_units.py` — `GET /v1/wealth`.
- `scripts/score_run.py` — the CLI.
- `scripts/m1_driver.py` — logs `wealth` records at run start and
  run end (`_fetch_wealth`, mirroring `_fetch_fresh_citizens`).
- `tests/test_scoring.py` — offline tests (synthetic log, fake
  store). `tests/test_scoring_live.py` — live test for `/v1/wealth`.

## What this is not

Distinct from the dfkit See/Target/Act/Verify scorecard (GOAL.md
step 11), which scores the HARNESS, not the model. The scoring
system scores the MODEL's play; the harness scorecard scores the
harness's observation/action quality. Both are needed; they are not
the same thing.
