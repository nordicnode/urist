# Evaluation: Urist as an LLM benchmark (design)

A design for expanding the harness's evaluation side into a serious,
alternative way to evaluate LLMs. This is a DESIGN document. The
scoring system in docs/SCORING.md already exists and is the v1
baseline; this doc designs what comes after it. Nothing here is
implemented yet unless the implementation status below says so.
Anything marked UNVERIFIED is a claim the implementation must check
before it is relied on.

## Implementation status (2026-11-27, track 3)

- **Phase 1 (instrumentation): PARTIAL.** The manifest schema and
  writer exist (`src/dfagent_harness/evaluation.py`:
  `build_manifest` / `write_manifest`; `scripts/score_run.py
  --manifest`). The two verified 1-day runs were re-scored with
  manifests attached (`logs/*.manifest.json`, local artifacts);
  both reproduce their verified scores exactly (91.8 / 91.7).
  The manifest records what the log does not record as honestly
  null with a `gaps` list: tokens, harness commit, and protocol
  version are all null for legacy logs. The driver-side emission
  (model_call records, see "Driver emission spec" below) is a
  track-4 change, NOT done here.
- **Phase 2 (scenario registry): PARTIAL.** `scenarios/
  scenarios.json` exists: S0 anchor verified on disk
  (saves-clean/region2-00125-04-01-clean); S1-S5 archetypes with
  fixed seeds and the M2_PROFILE finder profile; S6 held out.
  Expected match counts and start states are UNVERIFIED until each
  scenario is generated live twice from its registry entry.
  Cross-machine determinism stays UNVERIFIED.
- **Phase 3 (suite runner): PARTIAL.** `scripts/eval_run.py`
  exists: `plan`, `replay` (offline, verified on the two real
  logs: median 91.8, IQR 91.7-91.8, survival 100%), `run`
  (live, gated by --allow-live; refuses non-S0/unverified
  scenarios), `leaderboard`, `baselines` (fails with the blocker
  named). No live suite has run yet; that waits for main-chat
  scheduling.
- **Phase 4 (v2 metrics): PARTIAL.** Expansion lands now
  (breadth of use from logged actions; both real runs score 12.5,
  crafts only). Economy, defense, diplomacy report None ("not
  measured"), never 0; v2 composite is None until all four land,
  and v1 remains the headline. Sensitivity analysis done
  (2026-11-27, script /tmp/sensitivity.py): no single dimension
  dominates (worst single-dimension score 25.0); the two verified
  runs keep their v1 ordering under v2 weights at every gated
  level (gap 0.05, noise-level, as expected for two
  near-identical smoke runs); wealth-farm-only (77.5) scores well
  below a balanced good run (89.0).
- **Phase 5 (leaderboard publication): PARTIAL.** The `eval_runs`
  table exists (scoring.Leaderboard); `docs/LEADERBOARD.md` is
  generated from scores.db and committed. It currently says no
  benchmark suite has completed and lists the two 1-day runs as
  smoke-tier only. The baselines have NOT run (both blocked; see
  `eval_run.py baselines`).
- **Phase 6 (ablation): SPEC ONLY.** Needs a guidance-off flag
  that does not exist (track-4 driver change).

## Run-end summary (Mikey, 2026-11-27 ~21:29 PT)

The harness must log run statistics, not just the score, so the
user gets a nice metrics summary at the end of their AI run:
units killed, buildings created, and more. Implemented in
`scoring.run_summary` / `format_run_summary`, printed by
`scripts/score_run.py --summary` and embedded in every manifest
as `run_summary`. It covers: dwarves arrived/died/departed,
deaths by kind with causes, units killed (total, split into
citizen deaths the store diagnosed vs other units), buildings
created by kind (workshops, farm plots, furniture), jobs queued /
completed (by DF job type, from job_completed events) /
cancelled / failed, wealth change, drink/food start/end,
decisions (decision ticks, actions, idle ticks, model failures
with taxonomy, suggestions matched), threats faced, dwarf
distress by kind. Counts with no evidence are None with a reason
in `not_recorded`, never 0: moods and trades have no event in the
harness yet, hostile kills by the fort's dwarves are not recorded
(no kill event exists), arrivals/departures need the events
journal. Verified offline on synthetic logs and on the two real
runs (071025: Still x1, brew x2, make_barrel x4, make_bed x3,
7 jobs completed, 1 failed; 073557: 6 queued, 6 completed,
0 failed). Live proof waits for scheduling, same as the rest of
this track's live verification.

## Driver emission spec (for track 4, NOT this track's files)

**Implemented 2026-11-27** (the foundation commit; see the
coordinator log for the hash): the driver emits all four items,
verified live against the real game the same day.

The manifest fields that are null for legacy logs need the driver
(m1_driver.py, track 4) to emit them. This spec is the handoff;
do not implement it in evaluation files:
- A `model_call` record per model call attempt: `prompt_tokens`,
  `completion_tokens`, `latency_s`, `model`, `temperature`. The
  Free Pi client currently discards the response `usage` field;
  either keep it (if the API returns it, UNVERIFIED at the API
  level) or count tokens locally from prompt/reply text.
  **Done:** Free Pi returns `usage` (verified live 2026-11-27:
  `prompt_tokens` / `completion_tokens` / `total_tokens`); the
  client keeps it via `FreePiClient.chat_full`, and the driver
  logs one `model_call` record per attempt (including parse
  retries) with the API's counts, latency, model id, and
  temperature. Live proof: a 2-tick real-model run logged two
  records (prompt 8668/8729, completion 715/260, latency 4.0/5.3s);
  the manifest sums them (tokens_in 17397, tokens_out 975).
- `run_start` gains `harness_commit` (git HEAD at run start) and
  `protocol_version` (evaluation.PROTOCOL_VERSION, currently 1).
  **Done:** logged on every run (live proof: run_start carries
  harness_commit 1659a96… and protocol_version 1; the manifest
  reads them and the gaps list is empty for them).
- A `--noop` driver mode that never acts, for the no-op baseline
  (the mock model returns canned suggestions; it is not a no-op).
  **Done:** `--noop` skips model calls and actions entirely
  (live proof: a 2-tick noop run logged 0 model_call, 0 action,
  2 noop_tick, run_end max_ticks; the score still gets wealth).
- A guidance-off flag for the Phase 6 ablation (disable the
  guidance layers; the flag does not exist today).
  **Done:** `--guidance-off {a,b,c,d}` (HARNESS_ROLE.md §8.1
  groups: A strips the suggestion, B is recorded with no prompt
  change — the driver prefetches no briefings or wiki, C swaps
  in the knowledge-permitting system prompt, D strips
  suggestion/attention/goals/placement and skips all
  driver-added guidance). Live proof: a `--guidance-off a`
  2-tick run completed with a model call and an action, run_start
  naming guidance_off 'a'.
- A scripted model route (the baselines need it; EVALUATION.md
  §Baselines and scripts/eval_run.py `baselines`): `--scripted`
  runs the snapshot's suggestion each tick — the harness's own
  checklist applied in order — with no model. run_start records
  `scripted: true`; the diary is skipped so the run stays
  model-free end to end. Live proof: a `--scripted` 2-tick run
  logged scripted=True, 0 model_call, and correctly idled (the
  fort had no suggestion — drink 64, food 88, farm plot built).
  `eval_run.py baselines --kind noop|scripted --allow-live`
  now runs one baseline (S0, day tier) and records it, instead
  of failing with BLOCKED.

## Why this is a benchmark worth building

Most LLM benchmarks ask a model to answer questions, write code, or
close a ticket. A Dwarf Fortress fort asks a model to run a living
system for years: keep dwarves fed and watered, build an economy,
survive sieges, handle strange moods, trade with caravans, and recover
from its own mistakes, all through a fixed API, with the game state
changing under it every tick. That is a different kind of evaluation
from a static test set, and it is the kind that matters for agents
that will be asked to operate real systems.

Urist is not the first to see this. The design below takes what the
existing attempts got right and fixes what they got wrong.

## What exists today (audit, 2026-11-27)

Verified against the repo, not from memory.

**The scoring system (docs/SCORING.md, src/dfagent_harness/scoring.py).**
One headline composite (0-100) plus a per-dimension breakdown. Seven
dimensions, weights: survival 30, lives 30, wealth 10, needs 10,
growth 5, competence 10, threats 5. Milestone bonus +2 each, cap +10
(first brew, first bed, first farm, first trade, first mood
resolved). Computed by the harness from live game state, the run log,
and the store, never self-reported by the model.

**The leaderboard (scores.db, scripts/score_run.py).** One row per
scored run: model, run log, start save, tick budget, days planned,
date, composite, dimensions, milestones, evidence. A run log is
scored at most once per model; re-scoring replaces its row. Two rows
exist, both DeepSeek V4.1 Flash on 1-day runs on the clean base
125-04-01: **91.8** (log m1-20261127-071025.jsonl) and **91.7**
(m1-20261127-073557.jsonl). These are 1-day smoke-tier runs. They
must not be presented as benchmark results.

**What a run log records (logs/m1-*.jsonl).** run_start (days,
window, model, mock), start_tick, snapshot (tick_no, suggestion,
text), action (name, ok, params, reason, model_reason, phrase),
model_failure, clock_advance, diary_citizens, wealth, diary,
run_end (reason, tick, actions_taken, idle_ticks).

**What a run log does NOT record.** Token counts (prompt or
completion) per model call. Wall-clock time per model call or per
run. Model call parameters (temperature and the rest: whatever
freepi.py sends today). Harness git commit. Prompt or snapshot
schema version. Scenario id, world seed, or embark profile. The
full prompt sent to the model (only the snapshot text is logged;
the system prompt and the catalog are not). A failure taxonomy:
model_failure is a count, not a classified reason. Every one of
these is a Phase 1 gap.

**What is NOT yet detectable.** First farm, first trade, and first
mood resolved are always False: no plant action, no trade event,
and no mood event exist in the harness yet. They become detectable
only when those systems land; the code must not claim them before
then.

**The driver (scripts/m1_driver.py).** Defaults: 1 day (1200
ticks), 150 ticks advanced per decision tick (8 decision ticks per
day), max 2 actions per tick, model deepseek-v4.1-flash. A failed
model call or action ends the TICK, never the run. Stall handling:
sharper prompt at 3 idle ticks, run the snapshot's suggestion as
fallback at 6.

**The embark module (src/dfagent_harness/embark.py).** Seeded
world gen (`-gen <region> <seed> <preset>`) plus a fixed finder
profile plus a deterministic pick rule (first match, topmost then
leftmost) can produce a fixed, reproducible starting scenario.
`embark_site()` already does the full flow live. Cross-machine
determinism of seeded DF world gen is UNVERIFIED: same seed and
profile producing the same world on another machine or install has
not been tested.

**The model route.** DeepSeek V4.1 Flash via Free Pi, model id
deepseek-v4.1-flash-1017, free and unlimited, JWT at
~/.free-pi/agent/jwt.txt. Free Pi is the weak link (IncompleteRead,
HTTP 429 when two drivers collide); model reliability is already
counted in competence. The Solo Pro 4 option (Upstage Solar Pro 4)
needs a paid key, which Mikey has NOT approved. The key step is his
decision, not an implementation step.

**The dfkit scorecard (GOAL.md step 11) is a different instrument.**
It scores the HARNESS (See/Target/Act/Verify), not the model. The
evaluation in this doc scores the MODEL's play. Both are needed;
they are not the same thing.

## What Urist evaluates that other benchmarks do not

**The dkta.dev benchmark** ("Teaching a local model Dwarf Fortress
without training it", Nov 2026, verified from the article itself):
the model reads a plain-text fort report and writes a short Python
program against a `fort` API, game paused between `fort.wait()`
calls. Everyone plays the same six saved embarks, two in-game
years each, 12 runs per model. Score is created wealth with crafts
capped at the value of what the fort built, times the share of
dwarves still alive; the crafts-excluded median is also reported.
Medians over 12 runs: GPT-6 Astra 22,708 (0 forts lost, 4 dwarves
died), Claude Opus 5.5 17,822 (0 lost, 13), Claude Sonnet 5.5
17,354 (1 lost, 33), DeepSeek V4.1 Flash 13,976 (1 lost, 23),
Dreamfort script 11,096, doing nothing 28 (4 of 12 lost).
DeepSeek's 12 years cost $1.01 in API fees. The author refuses to
rank the models: among the top three, every pair splits the six
embarks 3-3 or 4-2, which is not enough to establish an ordering,
and the model settings were not matched (Opus got hidden reasoning,
Sonnet got none; DeepSeek ran through its own API). Turn counts
differ wildly: Astra's median is 27 turns a year, Sonnet's is 99.
Two lessons Urist takes directly: cap the farmable part of the
score, and report intervals instead of declaring a winner inside
the noise.

**The Factorio Learning Environment** (FLE, arXiv:2503.09617,
NeurIPS 2025 Datasets and Benchmarks Track): lab-play is 24
structured tasks with fixed resources, a production quota, max 64
steps, scored pass@8; open-play is unbounded, build the largest
factory on a procedurally generated map, scored by production
score. It is deliberately non-saturating: throughput spans about
six orders of magnitude, so better models keep scoring higher
instead of hitting a ceiling. Best published lab-play in v1:
Claude 3.5 Sonnet 7 of 24 tasks; open-play production score
293,206. The lesson for Urist: a benchmark needs headroom. A
1-day survival score saturates at 100 for any model that keeps
seven dwarves alive; the benchmark tiers below exist so the score
keeps separating models as they get better.

**BALROG** (Paglieri et al., ICLR 2025, arXiv:2411.13543): six
games of increasing complexity under one framework, BabyAI (about
10 steps) to NetHack (10,000-100,000 steps), zero-shot, history
limited to 16 observations, scores 0-100 with standard errors from
replicate seeds (for example GPT-4o on BabyAI 77.60 ± 3.73% across
25 seeds per task). The lesson: report the spread over repeated
runs, not a single number, and grade progress continuously rather
than pass/fail where the task is long. The related tau-bench idea
matters too: pass^k, the probability a model succeeds in ALL k
repeated trials, measures reliability rather than peak
performance (GPT-4o pass^8 under 25% where pass^1 is about 50%).

**What Urist adds that none of these have.** Indefinite autonomous
play over in-game years, not a fixed task with a quota. Every
aspect of fortress mode, not just building: needs, moods, military,
trade, diplomacy, floods, sieges, animals. A guidance and memory
architecture that is part of the system under test: the catalog,
the composed tasks, the per-dwarf diary feed, the failure
diagnosis, the wiki lookup, the snapshot's ranked attention
section. And a diary that makes a run readable as a story, so a
human can judge whether the fort's history makes sense, not just
whether a number went up.

**What is actually being measured.** The model plus the harness
together. That is the honest statement, and the doc states it
plainly because every comparison depends on it. A fair model-only
comparison requires all of these frozen: the same harness git
commit, the same prompt and snapshot schema version, the same
scenario set, the same tick and action budgets, and the same model
call parameters (or the parameters recorded and disclosed). Change
any one of them and the scores are no longer comparable; the
leaderboard keys on harness version and protocol version so a
cross-version comparison cannot happen silently. The harness
version is also what makes the ablation experiment possible
(Phase 6): the same model, guidance layers on versus off, measures
how much of the score is the model and how much is the harness.

## The scenario set

A benchmark needs fixed starting conditions and a fixed task. The
proposal is four tiers, so the suite stays usable as models improve
and as the VM's wall-clock budget allows.

| Tier | Length | Runs per model | Purpose |
|------|--------|----------------|---------|
| Day | 1 in-game day | 10 repeats on the anchor scenario | Smoke and regression; tight confidence, cheap |
| Season | 84 in-game days (one season) | 6 scenarios x 1 repeat | Brewing, farming, and the first caravan cycle |
| Year | 336 in-game days | 6 scenarios x 1 repeat | Migrants, the first siege season, winter |
| Two years | 672 in-game days | 6 scenarios x 2 repeats = 12 runs | The benchmark headline; dkta parity |

A year is 336 game days (12 months of 28 days), the same year
length dkta used. A season is 84 days. The two-year tier mirrors
dkta's 12 runs per model exactly, so Urist numbers and dkta numbers
can be read side by side even though the scores are different.

**Scenarios.** Six, mirroring dkta's six embarks. The anchor is
the existing clean base (S0: region2-00125-04-01-clean, 7
citizens, drink 38, spring year 125), which is also the regression
scenario every harness change is tested against. The other five
are seeded embarks produced by the embark module: fixed world
seed, fixed finder profile, fixed pick rule. Each scenario must
stress a different system, so the suite separates models that are
good at one thing from models that are good at all of them. The
proposed archetypes are: a forested site with flux and shallow
metal (the standard game); a site with an aquifer (flood
handling); a site with a cavern near the surface (early cavern
threats); a metal-poor site (trade dependence); a site with a
harsh biome (threat pressure). The seeds are NOT chosen here.
They are chosen during implementation, recorded in a scenario
registry (`scenarios/` in the repo: seed, profile, expected match
count, expected start state), and each one is verified live
before it counts as a scenario. One seventh scenario is held out
of the published set and used only for verification runs, so a
model cannot be tuned against every scenario it will ever meet.

**What is fixed.** The scenario (seed, profile, site), the run
length, the tick budget (150 ticks per decision tick, 8 decision
ticks per day), the action budget (max 2 actions per tick), the
model prompt (the harness protocol, versioned), the harness
version, and the model call parameters. **What varies.** Only the
model, and DF's own RNG inside a fixed scenario. DF's RNG means
exact reproducibility may not hold even on a fixed seed; the
leaderboard records the run log, so a surprising score can be
replayed and audited.

**Wall-clock honesty.** The measured 1-day run on the clean base
took about 97 seconds wall clock (log m1-20261127-071025.jsonl,
07:10:26 to 07:12:03). At that rate a 2-year run is about 19
hours, and a 12-run two-year suite is about 9 to 10 days serial.
That is an ESTIMATE, derived from one measured day on a small
fort; it will get worse as the fort grows and FPS drops, and the
suite runner must measure and report actual wall time per run.
Mitigations: the tiered suite (most work happens at day and
season tier), and parallel DF instances on separate displays
(the harness already runs a main and a scratch DF concurrently).
The VM's roughly 1.5 CPU share limits how far parallelism goes;
measure it, do not assume it.

## Run protocol

**How many runs.** The full two-year suite is 6 scenarios x 2
repeats = 12 runs per model. The headline number is the median
composite across those 12, with the interquartile range, the
minimum and maximum, and the survival rate (the fraction of runs
that lasted the full planned duration). Per-scenario medians are
published alongside the headline, so a model that is brilliant on
one scenario and dead on the other five cannot hide behind the
median. The day tier runs 10 repeats on the anchor scenario
because a day is about two minutes and tight confidence there is
cheap. The season and year tiers run one repeat per scenario.

**Why 12, and why the median.** dkta ran 12 and still refused to
rank, because pairs split 3-3 or 4-2 across embarks. Urist adopts
the same discipline: when the interquartile ranges of two models
overlap, the leaderboard says no ordering is established. The
median is used instead of the mean because a single catastrophic
run (a fort lost to a tantrum spiral in week two) should not be
averaged away, and a single lucky run should not crown a model.
Reliability is reported separately in the tau-bench spirit: the
fraction of runs in which the fort survived the full duration,
and the fraction of scenario pairs in which both repeats
survived. A model that survives 12 of 12 and scores 80 is more
trustworthy than a model that survives 7 of 12 and scores 85.

**What counts as a valid run.** A run is valid if it reaches its
planned duration or the fort dies by game causes (thirst,
invasion, tantrum spiral, flooding). A fort death is a result,
not a discard; it scores whatever survival and lives say it
scores. A run is DISCARDED only for infrastructure: a VM reboot,
a daemon crash, a DF crash not caused by game events, a harness
bug, or a model-provider outage that aborts the run (as opposed
to per-call failures, which end the tick and are counted in
competence). Discarded runs are rerun, logged in the run
manifest, and never counted. This is dkta's rule, adopted
verbatim: runs that crashed for infrastructure reasons were
rerun and are not counted. A run in which the model fails every
call is valid: it scores near zero on competence, and that is
evidence, not an infrastructure failure.

**What is recorded.** Every run produces three things: the run
log (as today), the score with its evidence block (as today),
and a new run manifest. The manifest is the reproducibility
record: model id, provider, endpoint route, harness git commit,
prompt and snapshot schema version, scenario id and seed,
embark profile, tick budget, start and end save, token counts
in and out per call and in total, wall-clock seconds per call
and per run, cost in dollars (zero for Free Pi, recorded for
paid models), model call parameters, the failure taxonomy for
every failed action and model failure, and the validity verdict
with its reason. A score without a manifest is not a benchmark
result; it is an anecdote. The manifest is also what makes a
score auditable: given the log and the manifest, anyone can
recompute the score and see exactly what the model was given.

## Expanded metrics (score v2)

The current seven dimensions and their definitions do not change.
The expansion adds dimensions and re-weights explicitly, and both
composites are reported side by side during a transition period,
so no score is silently redefined. Score v1 is the current
composite. Score v2 is the expanded composite below. The
leaderboard carries both until v2 has a full suite of its own.

| Dimension | Weight (v2) | What it measures |
|-----------|-------------|------------------|
| survival | 25 | In-game days lasted vs planned (unchanged) |
| lives | 25 | Citizen deaths by kind (unchanged) |
| wealth | 8 | Fortress-value growth (unchanged) |
| needs | 8 | Drink/food never zero; no dwarf dangerously hungry/thirsty (unchanged) |
| growth | 5 | Population, workshops, beds (unchanged) |
| competence | 8 | Idle ticks, failed actions, repeated failures, model reliability, suggestion handling (unchanged) |
| threats | 5 | Dwarves lost to hostiles (unchanged) |
| economy | 5 | Trade profit, produced-goods value, self-sufficiency |
| defense | 5 | Invasion and siege response: threats faced vs losses, fortifications, military readiness |
| diplomacy | 3 | Liaison meetings held, trade agreements secured |
| expansion | 3 | Breadth of systems used: farming, cooking, crafts, metalworking, rooms, zones |
| milestones | +2 each (cap +10) | First brew, first bed, first farm, first trade, first mood resolved, plus first siege survived, first caravan traded, first migrant wave housed, first artifact |

Weights sum to 100 before the milestone bonus. The weights are
PROPOSED, with reasons: survival and lives still dominate because
a dead fort has failed at the one thing the harness exists to
prove; economy, defense, diplomacy, and expansion together are
18 points, enough to separate a fort that merely survives from a
fort that thrives, small enough that no single late-game system
can rescue a fort that lets dwarves die of thirst. The weights
must be validated by sensitivity analysis before v2 is published:
run the existing scored runs through v2 and confirm no single
cheap trick dominates, and that the ordering of the two verified
scores does not flip on noise.

**Economy (5).** Trade profit across the run (value received
minus value given, from the trade records), produced-goods value
(the value of items the fort made, tracked through job
completions), and self-sufficiency (the share of the fort's needs
met from its own production rather than imports). Gated on the
trade system and on job-completion value tracking. Whether
produced-value share is trackable through job completions is
UNVERIFIED.

**Defense (5).** Threats faced versus dwarves lost, fortifications
and traps built, and military readiness (squads formed, equipped,
and stationed). Gated on the military system. Until it exists,
the dimension reports as not measured, never as zero.

**Diplomacy (3).** Liaison meetings held without the clock
freezing the fort to death, and trade agreements secured (import
and export requests recorded). Gated on the trade system and on
liaison-meeting handling that surfaces the meeting to the agent.

**Expansion (3).** A breadth count: how many of the fort's
systems the model actually used (farming, cooking, crafts,
metalworking, rooms, zones, animals, engraving), each counted
once on first verified use. This rewards a model that plays the
whole game over one that survives by doing one thing well.

**Decision quality (evidence, not a dimension).** The fraction
of actions whose postcondition held (the harness already verifies
actions; an action that did what the model intended is a good
decision), and the failure-mode taxonomy: every failed action
classified as a model error, a harness refusal with a named fix,
or a game constraint, and every model failure classified as
transport, provider, parse, or timeout. Reported in the evidence
block and the manifest, not folded into the composite, so the
headline stays about the fort and the failure analysis stays
readable on its own.

**Efficiency (reported axis, not a scored dimension).** Tokens
per in-game day, model calls per in-game day, wall-clock seconds
per in-game day, and dollars per in-game day. The leaderboard
shows score per token and score per dollar as sortable columns.
Efficiency is deliberately NOT folded into the composite: a cheap
model that plays badly must not beat a good expensive one on the
headline, but the model a person would actually run is the one
with the best score at a cost they can pay, and that choice needs
the numbers in front of it. Token counts are not recorded today;
Phase 1 fixes that. Whether Free Pi's API returns token usage is
UNVERIFIED; if it does not, tokens are counted locally from the
prompt and reply text.

**Milestone expansion.** First farm, first trade, and first mood
resolved become detectable when those systems land. The new
milestones (first siege survived, first caravan traded, first
migrant wave housed, first artifact) are defined the same
conservative way as the existing ones: positive evidence only,
never a queue, never a claim before the system exists.

**Qualitative axis, not scored.** A human reads the diary entries
from a run and judges whether the fort's story makes sense: do
the dwarves have lives, do events follow from earlier events,
does the entry read like a story rather than a list. The diary
is not scored. Scoring prose would invite gaming the prose, and
the diary's job is to be interesting for the player, not to be a
metric.

## Leaderboard design

**Schema.** The current scores.db gains a separate `eval_runs`
table (the existing scores table is left alone, so the v1
leaderboard keeps working). One row per run: model, harness
version, protocol version, scenario id, repeat number, tier,
composite v1, composite v2, per-dimension medians, survival,
tokens in and out, wall-clock seconds, cost in dollars, validity
verdict, run log path, manifest path, scored at. The headline
per model is the median v2 composite across the full two-year
suite, with the interquartile range and the survival rate next
to it. The table is sortable by composite, by survival rate, by
score per token, and by score per dollar.

**Published versus local.** scores.db stays local, in the daemon
state dir. Publication is a generated markdown table,
docs/LEADERBOARD.md, regenerated from the database and committed
to the repo, with one row per model and a link to the run
manifest for every run behind it. No run log is published
without its manifest. The published table carries the harness
version and protocol version for every row, so a reader can see
at a glance which rows are comparable and which are not.

**Adding a model.** A registry entry (model id, provider,
endpoint route, cost per token if paid, default call
parameters), then a smoke run (1 day on the anchor scenario) to
verify the driver works with it, then the suite. The smoke run
is a gate, not a score: if the driver cannot drive the model,
the suite does not start.

**Adding Solo Pro 4.** The route is Upstage Solar Pro 4 through
OpenRouter or the Upstage Console. It needs a paid key, and
Mikey has NOT approved spending on a key. The key step is his
decision. Once approved, the cost accounting in the manifest is
what makes the comparison honest: Solo Pro 4's score is reported
next to its dollars per in-game day, and the Free Pi models
report zero dollars, so the reader can see what the money bought.

**Baselines.** Every scenario set version is run against two
baselines, and both are published with the models. The no-op
baseline (the driver never acts) is the floor: dkta's doing
nothing scored a median of 28 and lost 4 of 12 forts, which is
the number every model must beat. The scripted baseline (the
harness's own checklist applied in order, in the spirit of
dkta's Dreamfort script at 11,096) is the floor for "plays the
game competently without a model". A model that cannot beat the
script has not earned its place on the table.

## Anti-gaming

**Wealth farming.** Dwarf Fortress tracks created wealth, and
crafts count toward it. dkta measured a median craft share of
67% for Astra and 61% for DeepSeek, and capped crafts at the
value of what the fort actually built. Urist's wealth dimension
is total fortress-value growth, and crafts do count toward it
through getValue. The fix, PROPOSED: report the craft share of
wealth growth as evidence on every score, and cap the craft
contribution the way dkta did. Validate the cap against live
data before it is adopted; do not adopt it on the strength of
dkta's numbers alone.

**Idling safely.** A model that does nothing and lets the
starting stocks carry the fort scores survival and lives but
almost nothing else: competence punishes every idle tick at 10
points, growth requires building, and milestones require doing.
The no-op baseline exists precisely so idling has a published
number attached to it.

**Hoarding imports.** Wealth counts total value including
imports, so a model could import valuables and sit on them. The
mitigation is the economy dimension's produced-goods value and
self-sufficiency, which reward making things over buying them,
plus the craft-share evidence on the wealth dimension.

**The back door.** In dkta's earlier rounds, models reached
through the Python process's private handle to the game and wrote
game memory directly through the DFHack Lua console. Urist's
model never gets that handle: it receives JSON snapshots and
returns actions through the API, and every action is validated
by the harness before it touches the game. Any output that is
not a valid action is logged, counted as a parse failure, and
ends the tick. The harness must keep a test that the model
cannot reach the game except through the action API.

**Gaming the suggestion metric.** Following the harness's own
suggestion is legitimate play, not gaming: the suggestion is the
harness's advice, and a model that follows good advice is
playing well. The suggestion component is reported separately
from the rest of competence, so it can be read on its own, and
it is capped at 5 points, so it cannot carry the dimension.

**Scenario memorization.** The scenarios are fixed and public,
so a model could in principle be trained on them. The held-out
seventh scenario is the mitigation: a model is verified on a
scenario it has never seen in the published set, and a large gap
between published and held-out performance is a red flag, not a
footnote.

**Prompt gaming.** The system prompt is part of the frozen
protocol. A model cannot rewrite it, and a prompt change bumps
the protocol version and invalidates cross-version comparisons.

## Implementation phases

Each phase has a verification bar. A phase is not done until the
bar is met, and nothing unverified is published.

**Phase 1: instrumentation.** Record what the log does not
record today: the run manifest (model, harness commit, prompt
and schema version, scenario id and seed, tick budget, start
and end save), token counts and latency per model call,
wall-clock per run, cost, model call parameters, and the
failure taxonomy for every failed action and model failure.
Verification: a scored run produces a manifest from which the
score can be recomputed from the log alone; offline tests for
the manifest writer; the two verified 1-day runs re-scored with
manifests attached. UNVERIFIED until implementation: whether
Free Pi returns token usage, and what call parameters freepi.py
currently sends (read it when implementing; do not guess).

**Phase 2: scenario registry.** A `scenarios/` directory in the
repo with the six scenarios (seed, finder profile, expected
match count, expected start state) plus the held-out seventh.
Verification: generate each scenario twice from its registry
entry and confirm the same match count and the same start state
(dwarves, drink, site). Cross-machine determinism stays
UNVERIFIED until a second machine generates the same world from
the same seed.

**Phase 3: suite runner.** A `scripts/eval_run.py` that runs a
tier (scenario by repeat), records validity, reruns
infrastructure failures without counting them, and computes the
median, interquartile range, survival rate, and efficiency
numbers. Verification: a full day-tier suite (10 repeats on the
anchor) runs end to end and produces a leaderboard row with a
manifest per run.

**Phase 4: v2 metrics.** The economy, defense, diplomacy, and
expansion dimensions, each landing only when its evidence exists
in the log and the store. Economy and diplomacy wait on the
trade system; defense waits on the military system; expansion
can land first, since breadth of use is measurable from the
actions already logged. Verification: offline tests for each
dimension function, plus live runs that exercise each one. Until
all four land, v2 is not published, and v1 remains the headline.

**Phase 5: leaderboard publication.** The `eval_runs` table,
the docs/LEADERBOARD.md generator, the two baselines run on the
current scenario set, and the first published table. The first
published table is DeepSeek V4.1 Flash alone, with its baselines;
a second model joins it only after its own full suite.
Verification: the generated table reproduces from scores.db
with no hand editing, and every row links to a manifest.

**Phase 6: ablation.** The same model run with the guidance
layers on and off, to attribute score to the model versus the
harness. This needs a flag to disable guidance layers, which
does not exist today, and it doubles the cost of every suite,
so it comes last. Verification: the ablation reproduces the
same score with guidance on as the ordinary suite run.

## Open questions

- Cross-machine determinism of seeded DF world gen: does the
  same seed and profile produce the same world on another
  machine or install? UNVERIFIED.
- Does Free Pi's API return token usage, or must tokens be
  counted locally from prompt and reply text? PARTLY ANSWERED
  2026-11-27: the client (freepi.py `chat()`) returns only
  `choices[0]["message"]["content"]` and discards the response
  `usage` field entirely. Whether the API returns usage is still
  UNVERIFIED at the API level, but the client drops it either
  way. Tokens must be counted locally or the client must keep
  `usage` (see "Driver emission spec").
- What model call parameters does freepi.py currently send?
  ANSWERED 2026-11-27 by reading it: body is `{"model",
  "messages", "temperature": 0.2}`: no max_tokens, no other
  parameters.
- Is produced-value share trackable through job completions?
  ANSWERED NO for the current log 2026-11-27: job_completed
  events carry job_id, job_type, worker_id, and pos, no values.
  The craft-share cap stays PROPOSED (implemented as
  `evaluation.craft_share_cap`, tested on synthetic numbers, not
  adopted, not used by any composite) until item-level value
  tracking exists.
- The wall-clock estimate for long runs (about 19 hours for a
  2-year run, about 9 to 10 days for a 12-run suite serial) is
  derived from one measured day on a small fort. CONFIRMED RATE
  2026-11-27: 97 s/day on the verified 1-day run. It will change
  as forts grow. The suite runner must measure real wall time.
- Solo Pro 4 pricing and endpoint details were verified by the
  parent on 2026-11-24; re-verify at implementation time, and
  the paid key needs Mikey's explicit say-so.
- The v2 weights are proposed, not validated. Sensitivity
  analysis on real runs is part of Phase 4, and the weights can
  change before v2 is published, but not after. SENSITIVITY DONE
  2026-11-27 (see "Implementation status", Phase 4): no single
  dimension dominates; the verified ordering does not flip under
  v2 weights; wealth farming does not beat balanced play.

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

Token costs below are computed from the exact section text with
the accountant's own rates (3 chars per token for the cap, 4 chars
per token on the wire). They are estimates until the coordinator
verifies them against the live assembler before commit.

### Snapshot: no evaluation section, by design

Evaluation pushes nothing into the per-tick snapshot. There is no
"Score: 91.8" line, no live dimension read, and no milestone
tally while a run is in progress. That is deliberate, and it is
the anti-gaming rule in §Anti-gaming: showing the model its live
score would steer it toward the metric instead of the fort. The
model plays the fort; the harness scores the play afterwards.
The score is computed by the harness from live game state, the
run log, and the store, never self-reported by the model, and it
is never fed back into a running model.

**Token cost.** At 7 dwarves and at 50 dwarves alike, the
evaluation section costs 0 tokens in the snapshot: there is no
section to render. The cost does not grow with population,
because nothing is pushed at any population. If a future change
puts any evaluation number into the snapshot, the change is
refused until it is justified against the anti-gaming rule in
writing.

### Query route: scores are read after the run, not during it

There is no live evaluation route, and there must not be one
during a run. Scores are read after the run ends:

- `scripts/score_run.py` scores a run log from scores.db: one
  row per scored run (model, run log, start save, tick budget,
  days planned, date, composite, dimensions, milestones,
  evidence). A run log is scored at most once per model;
  re-scoring replaces its row.
- GET /v1/wealth exists today and carries the wealth dimension's
  raw input (fortress value from lua/wealth.lua). The other
  dimensions are computed from the run log and the store, not
  from a live route.
- A proposed GET /v1/scores route (UNVERIFIED: does not exist)
  would return past scores for a model and scenario, for the
  leaderboard, never for a running model.

The two rows that exist today are both DeepSeek V4.1 Flash on
1-day runs on the clean base 125-04-01: 91.8 and 91.7. They are
1-day smoke-tier runs and must not be presented as benchmark
results, to the model or to anyone else.

### Briefing: none during a run

No evaluation briefing fires during a run. The run-end report is
delivered after the run, outside the snapshot, in this shape:

```
Run m1-20261127-071025: composite 91.8 (survival 100, lives 100, wealth 50, needs 100, growth 60, competence 88, threats 100). Milestones: first brew, first bed.
```

That report is 161 characters: about 53 tokens by the
accountant, 40 on the wire. At 50 dwarves it costs the same:
the report is a fixed shape, and only the numbers in it change,
not its length. The report goes to the human and to the log, not
back into the model that just played.

### Opportunities: none

The opportunities section carries no evaluation entries. An entry
such as "score 91.8, one milestone from 93.8" would be the
harness grading the model in its own ear while it plays. The
opportunities section is for facts about the fort the model can
act on; a score is not one of them. The model decides what to do
from the fort's state, not from its own grade.

### What the system deliberately does NOT push, and why

- **The live composite or any live dimension.** Showing a
  running score invites score-chasing: the model would optimize
  the number instead of the fort. The score exists only after
  the run.
- **Milestone progress mid-run.** Telling the model it is one
  milestone from a bonus is the same steering by another name.
  Milestones are detected after the fact, from the run log.
- **The leaderboard.** Past scores for a model and scenario
  belong to the human choosing a model, not to a model choosing
  its next action. The leaderboard is read by people.
- **Token counts and wall-clock per model call.** The run log
  does not record them yet (a Phase 1 gap in this doc). Until
  it does, there is nothing to push, and when it does, the
  counts go to the run log and the report, not to the snapshot.
- **Prompt or snapshot schema versions.** The run log does not
  record them yet (also a Phase 1 gap). Versioning is harness
  bookkeeping, not something the model needs while it plays.
