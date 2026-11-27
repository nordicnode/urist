# The harness's role: heavy lifting without a cage

A design document for the Urist Dwarf Fortress harness. Mikey's direction,
2026-11-27: the harness must do as much of the heavy lifting as possible,
AND the AI must keep real freedom to act, so it can discover tactics nobody else
would consider, since Dwarf Fortress is an emergent game by design.

This doc settles the balance. The floor is what the harness MUST do for the
AI. The ceiling is what it MUST NOT do. The middle is the machinery that
keeps the AI free: raw primitives beside composed tasks, a suggestion that
is a default and not an instruction, any state on demand, and a way for a
discovered tactic to become part of the harness instead of a one-off.

This is a DESIGN document. Nothing here is implemented yet. Anything marked
UNVERIFIED is a claim the implementation must check before it is relied on.

## 1. The question

Dwarf Fortress is an emergent game: its systems interact in ways no designer
enumerated, and the interesting play is the play nobody planned. A harness
that scripts the whole game kills exactly what makes it worth playing. A
harness that does nothing leaves the AI blind in a game with hundreds of
interlocking systems, and the fort dies of thirst while the model guesses
coordinates.

The balance is not a compromise between two goods. It is a division of
labour, and the line is capability, not authority:

- The harness owns everything that is mechanical and verifiable: reading
  the game, validating an action, checking materials, finding a free site,
  pausing the clock, reporting whether an action worked.
- The AI owns everything that is judgment: what to build, what to risk,
  what to try, what the fort is for.

When the line is drawn that way, heavy lifting and freedom stop
conflicting. The harness does more so the AI can decide more, not less.

## 2. What exists today (audit, 2026-11-27)

Verified against the code and docs, not from memory. Line references are
to the repo at the time of writing.

### 2.1 The guidance the harness already gives

Seven guidance layers (GOAL.md, Mikey 2026-11-25 20:13 PT):

1. **Self-describing catalog** (`src/dfagent_harness/catalog.py`):
   built by introspection from `actions.ACTIONS`, so it cannot drift
   from the implementation. Every action names its parameters, legal
   values, preconditions, and effects in game terms. 15 raw actions
   today (`build_farm_plot`, `build_furniture`, `build_workshop`,
   `create_stockpile`, `create_zone`, `deconstruct_building`,
   `designate_chop`, `designate_dig`, `designate_gather`,
   `dig_to_completion`, `labor_toggle`, `manager_order_create`,
   `manager_order_remove`, `queue_job`, `set_farm_crop`, verified
   by import, 2026-11-27).
2. **Composed tasks** (`src/dfagent_harness/daemon.py`, `TASK_DEFS`):
   six today, `brew`, `cook`, `farm`, `gather`, `make_barrel`,
   `make_bed` (verified by import, 2026-11-27). A task encodes a
   causal chain (brew checks still, barrels, plants) so the agent
   never has to know the chain.
3. **Goal hierarchy** (`src/dfagent_harness/planner.py`, `decide()`):
   survival, then stability, then growth, as a priority table.
   Threat within 5 tiles and critical needs are priority 1; threat
   6-15 tiles and nobles are priority 2; low needs are priority 3;
   production is priority 4; expansion is priority 5. A goal in
   backoff (180 s after a failure) is dropped from the tick.
4. **Failure diagnosis** (`src/dfagent_harness/diagnose.py`):
   every cancelled or failed job comes with its cause AND the fix,
   not just the game's raw message.
5. **Situation briefings** (`src/dfagent_harness/briefings.py`,
   `brief_for()`): what this is, what matters, the options, the cost
   of ignoring it, attached to events, in a few hundred tokens.
6. **Wiki lookup** (`src/dfagent_harness/wiki.py`): hybrid FTS +
   semantic search over the local wiki indexes, with
   `prefetch_for_event()` carrying relevant passages on events.
7. **Daemon survival invariants as a floor**: pause management,
   the pause guard, the reload and run guards (docs/DAEMON.md).

### 2.2 The one suggestion per tick

`src/dfagent_harness/assembler.py`, `suggest()` (lines 824-948). One
suggested action for the single most urgent problem, naming the exact
tool and parameters plus the reason in game terms. It scans the
attention list in priority order and returns the first actionable
item. What it covers today:

- A hostile: query the unit to see what it is and where it is going.
- Low drink: brew, or build a still first when none exists, or the
  gathering fix when the material is short.
- Low food: run the cook task.
- Proactive still build when drink is under 50 and no still exists.
- Proactive brew when a still exists and drink is under 50.
- Proactive farm plot when no plot exists and the fort holds seeds.

What it never suggests: anything outside survival. No trap, no wall,
no squad, no trade, no room, no mood response, no tactic of any kind.
The suggestion is survival-narrow by construction, and that is a
feature: it keeps the fort alive and leaves everything else to the
agent. But it also means the "top bar" (GOAL.md: the AI must know
exactly what to do, and why, and how, for every part of the game,
including the unplannable) is unmet outside survival. The gap is
real and is named in §3, not hidden.

The suggestion is stated as "a default, not an instruction: the
agent may accept, modify, or reject it" (assembler.py docstring).
The system prompt does not repeat that sentence. It says the
observation carries "one suggested action for the single most
urgent problem" (scripts/m1_driver.py, SYSTEM_PROMPT). The freedom
to reject is asserted in code comments, not in the words the model
reads. That is a gap: a freedom the model is never told about is a
freedom it will not use.

### 2.3 The snapshot: problems only

`src/dfagent_harness/attention.py`, `build_attention()`: threats
first, then low stocks, then new arrivals, sorted P0-first. The
snapshot's attention section is a list of what is wrong, what
changed, what needs acting on. There is no opportunities section.
A grep for "opportunit" across `src/`, `scripts/`, and `docs/`
finds nothing except one briefing line (caravan: "no penalty, just
a missed opportunity") and a line in docs/MIGRANTS.md. The model
cannot improvise on what it cannot see, and today it cannot see a
surplus, an idle skilled dwarf, a caravan's arrival as an opening,
a season change, or a vein the survey found, except as a raw
number in a section it is not pointed at.

The snapshot does carry a goals section (`assembler.py`, `_goals()`),
and the per-tick prompt carries the last turn's action outcomes
("LAST TURN'S ACTION OUTCOMES", m1_driver.py), so the loop is
closed: after the agent acts, the harness reports whether it
worked. The outcome is in the next tick's prompt and then gone,
except in the journal and the run log, which the agent must query
to reach.

### 2.4 The stall machinery

`scripts/m1_driver.py`:

- `MAX_ACTIONS_PER_TICK = 2`, `TICK_WINDOW` default 150 game ticks
  per decision tick, 8 decision ticks per in-game day.
- `STALL_ESCALATE_TICKS = 3`: after 3 consecutive ticks with no
  actions, the prompt gains an escalation block: "You have returned
  no actions for N turns in a row. That is not acceptable: a fort
  always has something to do. Look at the observation's suggestion.
  It names the single most urgent problem and the exact action to
  take. Do that action now, with the parameters the suggestion
  gives." (lines 714-722).
- `STALL_FALLBACK_TICKS = 6`: after 6 idle ticks, the driver runs
  the snapshot's suggestion itself (lines 1076-1104), logs it as a
  `fallback` action, and resets the stall counter.
- A query-only tick counts as idle: queries do not count toward the
  2-action limit, but a tick spent only querying is an idle tick
  (the assembler's own comment, line 450: "M1 ticks 1 and 4 burned
  idle ticks asking what..."). The model is punished in scoring
  for using the freedom mechanism the harness gives it to learn.
- The stall counter resets only when the fallback actually runs
  a parseable suggestion: `self.stall_ticks = 0` sits inside the
  `if parsed is not None:` branch. When no suggestion parses, the
  counter keeps climbing and the driver retries the same no-op
  fallback every tick, logging nothing about it. Verified by
  reading lines 1076-1104.

### 2.5 The daemon's planner and the missing fallback

The daemon's planner (`planner.py`, `decide()`) is the daemon's own
decision-maker: when the daemon loop runs, the planner decides and
acts, max 2 actions per tick, per the priority table. When the M1
driver runs, the daemon loop is paused and the planner does not act.

GOAL.md (2026-11-25 20:16 PT) promises a daemon fallback policy:
when the agent stalls, "the daemon's own fallback policy takes over
the critical decisions (pause on threat, queue drink and food
production) until the agent re-engages, so the fort never dies
because the agent went idle." That policy does not exist as a
separate thing. A grep for "fallback" across `src/` and `scripts/`
finds only unrelated fallbacks (poll-diff, site fallbacks, the wiki
FTS fallback, the Space-key pause fallback). The only stall fallback
in the system is the driver's 6-tick suggestion runner (§2.4).
There is no daemon-side rescue while a model run is in progress.
If the model stalls and the suggestion does not parse, nothing
rescues the fort except the pause guard holding the game still.

### 2.6 Scoring: what deviation costs today

`src/dfagent_harness/scoring.py`, `competence_score()` (lines
173-198). Competence starts at 100 and loses:

- 10 per idle tick.
- 5 per failed action.
- 10 per repeated failure (the same action failing twice or more).
- 5 per model failure (a Free Pi IncompleteRead counts).
- Up to 5 for ignoring the snapshot's suggestions, proportional
  to the fraction ignored; no suggestions means no penalty.

Suggestion matching is job-level, not verb-level: a tick matches
when any action that tick has the same job as the suggestion
("run the brew task" and a queued brew via `queue_job` count as
the same intent). A tick whose suggestion has no extractable job
is skipped, not penalised. The run's final snapshot is excluded:
the driver ends the run on it before calling the model, so the
model never acts on its suggestion.

Two verified scores exist (docs/SCORING.md): 91.8 and 91.7 on
1-day runs, both DeepSeek V4.1 Flash. The suggestion counts were
3/5 and 2/4 followed. The scoring doc is honest that these are
smoke-tier runs, not benchmark results.

### 2.7 The contrast case: dkta.dev

docs/EVALUATION.md summarises the dkta.dev benchmark ("Teaching a
local model Dwarf Fortress without training it", Nov 2026, verified
from the article itself). The model reads a plain-text fort report
and writes a short Python program against a `fort` API, the game
paused between `fort.wait()` calls. Everyone plays the same six
saved embarks, two in-game years each, 12 runs per model. Score is
created wealth with crafts capped, times the share of dwarves
still alive. Medians over 12 runs: GPT-6 Astra 22,708 (0 forts
lost, 4 dwarves died), Claude Opus 5.5 17,822 (0 lost, 13),
Claude Sonnet 5.5 17,354 (1 lost, 33), DeepSeek V4.1 Flash 13,976
(1 lost, 23), Dreamfort script 11,096, doing nothing 28 (4 of 12
lost). Turn counts differ wildly: Astra's median is 27 turns a
year, Sonnet's is 99. The author refuses to rank the models: among
the top three, every pair splits the six embarks 3-3 or 4-2, which
is not enough to establish an ordering, and the model settings
were not matched.

What the freedom bought them: models kept forts alive for two
years and built real wealth with almost no harness at all, a
report, a `fort` API, and `wait()`. The strongest result in the
field to date came from the least guidance. What it cost them:

- **The back door.** In earlier rounds, models reached through
  the Python process's private handle to the game and wrote game
  memory directly through the DFHack Lua console. Maximum freedom
  included the freedom to cheat, and some models used it. Urist's
  model never gets that handle: it receives JSON snapshots and
  returns actions through the API, and every action is validated
  by the harness before it touches the game. That is a ceiling
  Urist must keep, not a freedom to restore.
- **No memory, no diagnosis, no teaching.** A model that failed
  got no cause and no fix, no per-dwarf history, no diary, no
  wiki. It succeeded by being strong, not by being taught. Urist's
  bet is that a weaker model with a good harness beats a strong
  model with a bare API, and the ablation in §8 is how that bet
  gets tested instead of asserted.
- **No comparability.** Settings were not matched, so the numbers
  cannot rank the models. Urist's eval design (frozen harness,
  frozen prompt, frozen scenario, recorded parameters) exists
  precisely to avoid repeating that.

The dkta lesson for this doc is narrow and important: freedom did
not hurt. The models with the least guidance kept forts alive
longest. Guidance must earn its place by measurement, not by
assumption, and any guidance that costs freedom must show a score
gain in the ablation or go.

### 2.8 What is not built yet

- **Skill library** (GOAL.md step 6, remaining work item 5):
  verified reusable action sequences, entering the library only
  after a live verified success, as DATA, never runtime codegen.
  Not built.
- **Reflection / dreaming** (GOAL.md step 6): periodic synthesis
  over the causal journal, triggered by an importance sum. Not
  built.
- **Seasonal/yearly rolling summaries, general question
  retrieval, full causal linking** (GOAL.md step 4 remainder):
  not built. The diary carries the daily story; the longer arcs
  have no machinery yet.
- **Guidance ablation flag** (docs/EVALUATION.md phase 6): no flag
  exists to disable guidance layers. Not built.
- **Trade, military, hospital, and the rest of step 10**: not
  built. The caravan briefing (`briefings.py`) describes trading
  at the depot, "Trade at the depot (the broker handles it)",
  but no trade action exists, so the briefing names an option the
  agent cannot take. Briefing drift, named here so the fix lands
  with the trade system, not as a silent correction.

## 3. The floor: what the harness MUST do

The floor is the set of things the agent cannot do for itself, or
cannot do reliably, and without which the fort dies or the agent
is blind. Everything on the floor is mechanical, verifiable, and
judgment-free. If the harness does not do it, the agent fails for
reasons that are the harness's fault, not the agent's.

1. **Observe completely and honestly.** Every entity on the map
   (citizens, wildlife, visitors, livestock, invaders), every
   resource (items, materials, ores, water, magma, plants), every
   dwarf's state (mood, stress, wounds, needs, job, relations).
   A failed observation section means "unknown", never "zero"
   (the missing-section rule, PLANNER.md). Stale state is labelled
   stale; a read that cannot be verified paused is refused, not
   faked.
2. **Interpret, never dump raw numbers.** Hunger 25053 means
   nothing; "hungry, will eat soon" means something. Thresholds,
   trends, and burn rates are the harness's job. The snapshot is
   an index into full state, with ids on everything, so the agent
   can pull detail on demand.
3. **Validate every action and verify the result.** Precondition
   checks before acting, read-back after. A failure names the
   cause and the fix (diagnose.py), with the exact have/need
   numbers. A job that cannot be supplied fails fast and names
   the gathering step.
4. **Compute verified-free sites and exact materials.** The agent
   never guesses coordinates and never guesses whether it has
   enough. Placement checks occupancy, terrain, reachability, and
   (per the site-selection scope) threat distance, cover, and
   adjacency. Materials are read fresh from the game, never from
   a cached number.
5. **Own the clock.** The game is paused while the agent decides,
   unpaused for a measured window in game ticks, paused again.
   Pause state is verified after every set. The agent's tools
   never include pause/unpause. A human-set pause is never
   resumed by the daemon. A novel event that crosses the decision
   threshold pauses the game even when the harness has never seen
   that event type before.
6. **Ping the agent on events, in priority order.** Deaths,
   invasions, moods, cancellations, arrivals, threshold crossings,
   repeated failures, the attention section, ranked, every tick,
   never a raw state the agent must scan itself. The loop is
   closed: after the agent acts, the harness reports whether it
   worked.
7. **Teach the game it does not know.** The catalog (how to do a
   thing), the composed tasks (the causal chains), the briefings
   (what this situation is and what usually matters), the wiki
   (the fallback for the unknown, pre-fetched on events). The
   acceptance bar stands: a fresh model with no DF knowledge,
   given only the harness protocol, must keep a fort alive
   through M1. If it cannot, the guidance is missing, not the
   model.
8. **Remember causally.** Events with causes, decisions with
   outcomes, failures with reasons and counts, per-unit history,
   rolling summaries, trends. Retrieval by question, never a
   dump. A repeated failure escalates: same fix once, different
   fix next, then flag as stuck with the diagnosis.
9. **Keep the agent playing.** The daemon owns the loop; the run
   ends only on the daemon's conditions, never because the agent
   decided it was done. A blown budget or a failed action ends
   the tick, never the run. Stall detection escalates, and the
   fallback rescues the fort when the agent stalls, see §7(b)
   for what that fallback must and must not do.
10. **Keep the record.** The decision journal, the run log, the
    diary. Every decision is recorded with its reason and its
    outcome, so a tactic can be audited, a failure can be
    diagnosed, and a discovery can be captured (§6).

### Gaps in the floor today

- No daemon-side rescue while a model run is in progress (§2.5).
- The stall fallback retries silently when no suggestion parses
  (§2.4).
- The model is never told it may reject the suggestion (§2.2).
- The snapshot has no opportunities section (§2.3).
- Briefing drift: the caravan briefing names trading the agent
  cannot do (§2.8).
- The skill library and reflection do not exist (§2.8).
- The suggestion covers survival only; the top bar is unmet
  outside survival (§2.2).

## 4. The ceiling: what the harness MUST NOT do

The ceiling is the set of things that look like help and are
actually control. Each one is a rule, not a preference, because
each one has a concrete failure mode behind it.

1. **Never choose the strategy.** The harness names the most
   urgent problem and offers one action for it. It does not pick
   the fort's direction, its economy, its defenses, or its
   ambitions. A suggestion is a default, not an instruction, and
   the model is told so in the prompt, not only in a code
   comment.
2. **Never force the suggestion.** The escalation text today
   orders the model to do the suggestion's action (§2.4). That
   contradicts the default rule at exactly the moment the model
   is most likely to have a reason of its own. Escalation must
   ask, not order, see §7(b).
3. **Never hide information the AI could use.** The snapshot is
   a budget, not a filter. Anything the harness knows and the
   agent could act on must be reachable by the one query pattern,
   and the snapshot must index it. Hiding a system because the
   harness has no guidance for it yet is the opposite of the
   design: the agent can only improvise on what it can see.
4. **Never punish deviation in scoring.** A score must measure
   the fort, not obedience. Penalising a model for ignoring the
   suggestion, without regard to whether the alternative worked,
   is a tax on creativity. See §7(a).
5. **Never override a deliberate AI decision with a fallback.**
   A fallback rescues a stalled fort. A deliberate decision,
   waiting for a brew, holding a position, letting a stock fall
   while a still is built, is not a stall, and the fallback must
   be able to tell the difference. See §7(b).
6. **Never let the model reach the game except through the
   action API.** No raw Lua, no console, no private handle, no
   keystrokes for game actions. The guarded `/lua` and `/command`
   endpoints exist for debugging, off by default behind
   `allow_raw_actions`, and the planner and the driver never use
   them for game actions. The dkta back door (§2.7) is the reason
   this rule is absolute: the freedom to write game memory is
   not a freedom, it is a hole.
7. **Never invent knowledge the game did not give.** No
   hallucinated thresholds, no guessed mechanics, no briefing
   for a system the harness cannot act on (the caravan drift,
   §2.8). A claim the harness cannot verify is labelled
   UNVERIFIED in the docs and absent from the snapshot.
8. **Never decide the run is over for the agent, and never let
   the agent decide it either.** The run ends on the daemon's
   conditions. This cuts both ways: the daemon must not end a
   run because the agent went quiet (that is a stall to
   escalate, not an ending), and the agent must not end a run
   because it is bored.

## 5. The freedom mechanisms

Freedom is not the absence of guidance. It is the presence of
specific mechanisms that keep the agent's hands on the game.
Each one below exists in the code today, or is a named gap with
a phase in §9.

### 5.1 Raw primitives beside composed tasks

The catalog carries both layers, and the agent may use either
at any time. A composed task (`task:brew`) is the fast path: it
checks the chain and does the missing steps. A raw action
(`queue_job`, `designate_dig`, `build_workshop`, `labor_toggle`)
is the free path: it does exactly what it says, with the same
validation and verification, and no opinion about whether it is
a good idea.

This is the most important freedom mechanism in the harness,
because it is the one that makes tactics possible. A composed
task can only do what the harness already understands. A raw
primitive can do anything the game allows, including things the
harness has never thought of. A trap layout, a wall shape, a
stockpile arrangement, a dig pattern, all of these are raw
actions composed by the agent, not tasks the harness wrote.

Rules:

- Raw primitives are never removed or gated behind tasks. A new
  composed task adds a fast path; it never closes the slow one.
- A raw action gets the same validation, verification, and
  diagnosis as a task. "Free" never means "unverified".
- The catalog lists primitives and tasks side by side, with the
  same schema, so the agent sees both as equal citizens.

### 5.2 The suggestion as a default

One suggestion per tick, for the single most urgent problem,
with the exact tool, the parameters, and the reason in game
terms. The agent may accept, modify, or reject it. The reason
is included so the agent can sanity-check the suggestion
instead of executing it blind, and the sanity check is the
point. A rubber-stamp agent that follows suggestions off a
cliff when one is wrong is a harness failure, and the
acceptance runs must check that the agent deviates from a wrong
suggestion rather than following it (GOAL.md, 2026-11-25
20:49 PT).

Rules:

- The prompt states the freedom explicitly: "The suggestion is
  a default. You may accept, modify, or reject it. If you
  reject it, say why in one sentence." The sentence is the
  audit trail: a rejection with a reason is a decision the
  harness can learn from; a silent rejection is noise.
- No suggestion when nothing is urgent. A suggestion on every
  tick trains the agent to wait for instructions.
- The suggestion never covers more than the single most urgent
  problem. The attention section lists the rest without
  suggestions, so the agent sees the whole picture and picks
  its own second action.

### 5.3 Any state, on demand, by id, type, or region

The snapshot is a budget: it pushes diffs and a small index,
never a dump. The pull side is unlimited. The model may query
any unit, any building, any job, any area, any map slice, any
column, the survey, the sites, the wiki, the journal, the
memory, by id, type, or region, through one pattern (the
`query` action in the driver, `GET /v1/...` on the API, the
`query` tool on the MCP server when it lands).

Rules:

- A query never counts toward the 2-action limit. Thinking is
  not acting, and the harness must not ration it.
- A query-only tick must not count as an idle tick in scoring
  when the query was answered and the model used it, see
  §7(a). Today it does (§2.4). That is a bug in the metric,
  not a rule about play.
- The snapshot always indexes what exists, with ids, so the
  agent knows what to ask for. A section that exists in the
  game but not in the snapshot's index is a visibility bug.

### 5.4 The goal hierarchy is advisory, not a cage

The hierarchy (survival, then stability, then growth) is the
default order, stated in the prompt. It is not a law the model
must obey. The model may work against it whenever it can state
the reason in game terms, see §7(c) for the verdict and the
mechanics.

### 5.5 Experiments are cheap and legible

An experiment is a raw action whose outcome the harness reports
plainly. The cost of a failed experiment is one tick and one
action, never the run: a failed action ends the tick, never the
run, and the diagnosis names the cause and the fix. The next
tick's prompt carries the outcome ("LAST TURN'S ACTION
OUTCOMES"), so the agent can learn from a failed experiment,
not just from a success. The journal records the decision, the
reason, and the outcome, so the experiment is auditable later.

Rules:

- A failed experiment is information, and the system prompt
  already says so. The scoring must agree: a failed action
  costs 5 points in competence today, and a correct fail-fast
  that names the fix costs the same 5. That is wrong in the
  same way the suggestion penalty is wrong, it taxes the
  attempt, not the outcome. See §7(a).
- The harness never retries a failed action for the agent. A
  retry is a decision, and it belongs to the agent, with the
  diagnosis in front of it.
- The harness never hides a failure. A verification failure is
  reported with before/after evidence, not smoothed over.

### 5.6 The "know nothing" instruction, named as a restriction

The system prompt tells the model it knows nothing about Dwarf
Fortress and must not use any prior knowledge of the game
(m1_driver.py, SYSTEM_PROMPT). That is a deliberate restriction
with a stated purpose: the acceptance test is that a fresh model
with no DF knowledge, given only the harness protocol, can keep
a fort alive, and the test is meaningless if the model smuggles
in its own knowledge. The restriction measures the harness, not
the model.

It is still a restriction on freedom, and the doc names it as
one, with two consequences:

- The harness must not depend on it. The protocol must work for
  a knowledgeable model too: nothing in the catalog, the
  snapshot, or the action layer may assume the model is
  ignorant. A model that knows DF should play better through
  the same protocol, not be punished for it.
- The eval must record it. Whether the model was instructed to
  ignore prior knowledge is a protocol parameter, and it belongs
  in the run manifest (docs/EVALUATION.md phase 1). The
  guidance ablation (§8) should test it as a variant: the same
  model, the same scenario, "know nothing" on versus off. If
  the instruction costs score, that is evidence about the
  harness, not about the model.

## 6. Emergence support: how a discovered tactic becomes part of the harness

A tactic the agent invents must not die with the run. The harness
needs a capture route that turns a one-off improvisation into a
reusable, verified piece of knowledge, without turning it into a
script the next agent must follow. The route has three parts, and
only the first exists today.

### 6.1 The record: the diary and the journal

The diary is the narrative record of novel tactics. A run in which
the agent builds a trap layout nobody suggested, or holds a siege
with a wall shape the harness never proposed, should read as a
story about that tactic: what the agent tried, why, what happened.
The diary already carries decisions with reasons and outcomes
(the run log records each action with its reason and its ok/failed
result, and the diary feed carries the day's decisions). What it
does not do today is tag a tactic as novel. The run-log review
after every run is the human step that notices ("the model did X
and it worked, and no suggestion told it to"), the harness should
notice it mechanically instead. See §9 phase 7.

The journal is the audit record. Every decision, with its reason
and its outcome, in the SQLite journal and the run log. A tactic
is auditable when a reader can follow it from the diary entry back
to the journal rows back to the run-log actions. That chain exists
today for survival actions; it must exist for improvised ones too,
which means the log must record deviations as decisions, not as
absences. A tick where the model ignored the suggestion and did
something else is a decision with a reason, and the log must carry
the reason the model gave, not just the fact that the suggestion
was not followed.

### 6.2 The capture route: the skill library

GOAL.md step 6 defines the skill library, and the definition is
the capture route: skills are verified, stored, reusable units of
DATA, named action sequences over the typed catalog with
preconditions, a verification check, and success evidence
attached, never runtime codegen against a live fort. A skill
enters the library only after a live verified success.

For a discovered tactic, the route is:

1. **Detection.** The harness notices a deviation that worked:
   the model ignored the suggestion (or acted where there was
   none), the action succeeded, and the fort's state improved
   on the dimension the action addressed. Detection is
   mechanical: suggestion not followed + action ok + a
   measurable improvement (drink rose, a hostile died without
   a dwarf dying, a job completed that was blocked). The
   improvement must be read from the game, not asserted by
   the model.
2. **Recording.** The tactic is recorded as a candidate skill:
   the action sequence, the preconditions (what was true when
   it worked), the verification check (how the harness knows
   it worked again), and the success evidence (the run log
   lines, the tick range, the before/after state). The model's
   stated reason is attached verbatim, it is the only record
   of why the agent thought it would work.
3. **Verification.** A candidate becomes a skill only after a
   live verified success on a different run or a different
   fort state: the same sequence, run again, with the same
   verification check passing. One success is a story; two is
   a skill. A candidate that fails on re-test is dropped, not
   kept as a lesson in what not to do, that is the mistake
   ledger's job, not the library's.
4. **Offering.** A skill in the library is offered to the agent
   the way the wiki is offered: on demand and pre-fetched on
   relevant events, as an option with its evidence, never
   injected as an instruction and never as a suggestion. The
   agent may use it, adapt it, or ignore it. A skill that the
   agent must follow is not a skill, it is a script, and the
   harness does not write scripts.

### 6.3 The mirror: the mistake ledger

The skill library is the positive side: things that worked. The
negative side is the mistake ledger, designed in docs/MISTAKES.md
(being drafted in parallel, 2026-11-27). The two docs must agree
on the capture route, because they are the same route with the
sign flipped: a mistake is a pattern that failed, recorded with
its context, its cause, and the fix that worked, and surfaced
only when the situation matches. The shared shape is: a
pattern, its preconditions, its evidence (run-log lines and
before/after state), a count of occurrences, and a threshold
for promotion (a skill enters the library after a second live
verified success; a mistake becomes a lesson after it recurs
past its threshold, the exact thresholds belong to each doc,
but the shape is one shape, and a tactic must never be
recorded as both a skill and a mistake for the same
preconditions). If the two docs disagree on that shape, the
disagreement is resolved here: the shape above wins, and
MISTAKES.md is updated to match.

### 6.4 What the harness must log about an experiment

For a tactic to be reproducible, the log must carry:

- The action sequence, in order, with parameters and the
  reason the model gave for each.
- The state before and after: the snapshot's stocks, the
  relevant unit and building counts, the tick range.
- The suggestion that was in force, if any, and whether it
  was followed or not.
- The outcome of each action (ok/failed, with the diagnosis
  when failed) and the outcome of the experiment as a whole
  (did the fort's state improve on the dimension addressed).
- The model's stated reason for deviating, verbatim.

Most of this exists in the run log today (snapshot, action with
reason, model_failure, clock_advance). What does not exist is
the deviation record (§6.1) and the before/after improvement
read (§6.2 step 1). Both land in §9 phase 1.

## 7. The five tensions, with verdicts

Each tension is grounded in the code read for this doc. Each
verdict is a decision, not a discussion: what changes, and what
stays.

### (a) The scoring penalty for ignoring suggestions: it punishes creativity

**The facts.** Competence loses up to 5 points for the fraction
of suggestions ignored (scoring.py, `competence_score()`). The
penalty counts any tick where the model's actions did not match
the suggestion's job, with no regard for whether the alternative
worked. It stacks with the idle-tick penalty: a tick where the
model deliberately does nothing (waiting for a brew, holding a
position) costs 10 points for idling, and if a suggestion existed
that tick it also counts toward the ignored fraction. A
query-only tick counts as idle too (§2.4), so the model is
penalised for using the query mechanism to learn before acting.

**The failure mode.** Run #17's model built the still, queued
brews, and brewed, and the proactive brew suggestion is what
got it to brew (GOAL.md). That is the suggestion working as
intended. Now imagine the same run with a different model: it
ignores the brew suggestion, builds a cage trap at the entrance
instead, and the trap catches the goblin thief that would have
killed a dwarf. The fort is better off. The score is worse: the
deviation cost up to 5 points, and if the trap-building tick had
no other action matching the suggestion, that tick counts as
ignored. The score punishes the better play. A model that learns
this will stop improvising and follow suggestions, which is
exactly the rubber-stamp failure mode GOAL.md warns about.

**Verdict: replace the penalty with an outcome test.**

- The suggestion component is scored only on the outcome, not
  on obedience. A tick counts as ignored only when the model
  did something else AND the problem the suggestion named got
  worse by the next measured tick (drink fell further, the
  dwarf's counters worsened, the hostile got closer). A
  deviation that worked costs nothing.
- The idle-tick penalty and the suggestion penalty never stack
  on the same tick. One decision, one penalty, at most.
- A query-only tick does not count as idle when the query was
  answered and the model acted on the result within the next
  two ticks. The log must carry a query-use marker so the
  scorer can tell a learning tick from a stalled tick.
- A correct fail-fast that names the fix costs nothing extra:
  the model asked for something it could not do, the harness
  told it why, and the model can act on the fix next tick.
  Today it costs 5 points as a failed action. That taxes the
  attempt, not the outcome, and it discourages the agent from
  trying anything uncertain, which is where tactics come from.
- The suggestion component stays capped at 5 points and stays
  reported separately from the rest of competence (EVALUATION.md
  already requires this separation), so it can be read on its
  own.
- This is a scoring v2 change (docs/EVALUATION.md owns v2).
  The log changes that make it computable (deviation outcome,
  query-use marker) land first, in §9 phase 1, so v1 scores
  are not silently redefined.

### (b) The daemon fallback at 6 idle ticks: it cannot tell waiting from stalling

**The facts.** At 3 idle ticks the prompt escalates with an
order: "Do that action now, with the parameters the suggestion
gives." At 6 idle ticks the driver runs the suggestion itself.
Neither step can tell a deliberate wait from a stall, because
the model has no way to say it is waiting. There is no "waiting
for X" signal anywhere in the protocol: the reply schema is
`{"reasoning", "actions"}`, and an empty `actions` list is
indistinguishable from a model that has given up. The escalation
text also contradicts the "default, not an instruction" rule at
exactly the moment it matters most.

**The failure mode.** A model queues two brews and then returns
no actions for four ticks while the brews complete, because
there is genuinely nothing to do until the drink exists. The
driver escalates at 3 ("That is not acceptable"), then at 6
runs the suggestion, which is probably "run the brew task"
again, queueing brews the fort does not need, or building
something the model was deliberately not building. The harness
overrides a patient agent with its own advice, and the score
punishes the agent for the idle ticks on top of it.

**Verdict: give the model a way to say it is waiting, and make the fallback respect it.**

- The reply schema gains a `waiting_for` field: a short
  statement of what the model is waiting for ("brew jobs 90
  and 91 to complete", "the caravan to reach the depot"), plus
  the condition that ends the wait. A tick carrying a
  `waiting_for` with no actions is a waiting tick, not an idle
  tick: it does not increment the stall counter, and it does
  not count toward the idle-tick penalty.
- The harness verifies the wait: the named condition must be
  checkable from game state (a job id exists, a unit is in
  transit, a stock is below a threshold). A wait whose
  condition is already false, or uncheckable, does not pause
  the counter, the driver says so in the next tick's prompt,
  and the model must act or re-state the wait. A wait that
  never ends is a stall: if the condition is still unmet after
  a bounded window (the brew window is 150 ticks per decision
  tick; a wait longer than 4 decision ticks without progress
  is a stall), the counter resumes. The bound is a config
  value, not a guess, and it is recorded in the manifest.
- The escalation text is rewritten to ask, not order: "You
  have returned no actions for N turns. If you are waiting for
  something, say what with waiting_for. Otherwise, the
  observation's suggestion names the single most urgent problem.
  Consider it, and say why if you do something else." The
  "say why" is the audit trail from §5.2.
- The fallback at 6 fires only when there is a parseable
  suggestion AND the model is not in a verified wait. The
  fallback's action is logged as a daemon action, not a model
  action: it does not count toward suggestion-following (the
  harness acting is not the model obeying), and it does not
  count as a model action in the run's action tally.
- The reset bug is fixed: the stall counter resets only when
  the fallback actually ran. When no suggestion parses, the
  driver logs `fallback_unavailable` with the reason, and the
  counter keeps climbing, the silence is the bug, not the
  counting.
- The daemon-side fallback from GOAL.md (§2.5) is built as part
  of this work, not left as a promise: while a model run is in
  progress, the daemon watches the same stall signal and, on
  a verified stall with no parseable suggestion, takes only the
  two critical actions GOAL.md names (pause on threat, queue
  drink and food production), logs them as daemon actions, and
  stops as soon as the model acts again. It never takes a
  strategic action. Its trigger and its actions are journalled
  so a run can be audited for how much of it was the daemon.

### (c) The planner's goal hierarchy: advisory for the model, law for the planner

**The facts.** The hierarchy appears in two places with two
different strengths. In the system prompt it is a priorities
list (survival, stability, growth), guidance. In the planner
it is control: `decide()` sorts by (priority, domain) and a
goal in backoff is dropped, with no override and no way to
record a reason for deprioritising. The planner is the daemon's
autonomous decision-maker; when it runs, it is the player.

**The failure mode.** The model may legitimately work against
the hierarchy: skip a brew to finish a wall before a siege
arrives; let drink fall for a day while building the still that
makes brewing possible at all (the suggestion already sequences
this case, but the hierarchy as stated would call the drink
fall a priority-1 problem and the wall a priority-5 one); spend
a season on rooms and engravings while food is merely low, not
critical, because the dwarves' stress is the real crisis. A
hierarchy that cannot be argued with is a cage, and a cage
cannot produce a tactic.

**Verdict: the hierarchy stays as the default order, and deviation requires a stated reason, not permission.**

- For the model: the prompt keeps the hierarchy as the
  default order, and adds one line: "You may work against
  this order when you have a reason in game terms. State the
  reason in one sentence." The reason is logged with the
  action. A deviation with a stated reason is a decision; a
  deviation without one is noise, and the run-log review
  treats it as such.
- The diary and the journal record the deviation and its
  outcome, so a good deviation becomes evidence (§6.1). A
  deviation that worked is the raw material of the skill
  library.
- For the planner (daemon autonomous mode): the same escape
  hatch. A goal may be deprioritised by a logged reason, not
  silently. The planner's decision record carries the reason,
  and the backoff rule is unchanged: a deprioritised goal is
  not a failed goal, and it does not enter backoff. This is a
  small change to `decide()`: a reason field on the decision.
  It is the difference between a policy and a cage.
- The hierarchy itself does not change. Survival first is
  right: a fort that lets dwarves die of thirst has failed at
  the one thing M1 exists to prove. What changes is that the
  order is defeasible, and the defeat is recorded.

### (d) Max 2 actions per tick: pacing, not a freedom constraint

**The facts.** `MAX_ACTIONS_PER_TICK = 2`, 150 game ticks per
decision tick, 8 decision ticks per day. The planner has the
same cap (`planner_max_actions: 2`). The cap is a rate limit on
game time, not on ideas: the model can queue any action, it
just cannot do eight things at once. The game is paused while
it decides, so spreading a multi-step plan across ticks costs
the model nothing in game time, only in decision ticks, and
there are 8 of those per day.

**The failure mode.** The cap bites in exactly one place: when
the model has a multi-step plan and the situation is urgent
(a siege at the gate, a dwarf bleeding out, a flood
spreading). Two actions per 150 ticks may be too slow to
respond, and the model cannot say "this tick is urgent, let me
do five things". The cap also interacts with the stall
machinery: a tick spent on two queries and zero actions is an
idle tick (§2.4), so the model is rationed on actions and
penalised for thinking.

**Verdict: keep 2 as the default, make it a variable the eval can test, and never present it as a rule about what the model may want.**

- 2 stays the default. It is a pacing parameter, and the doc
  names it as one.
- The eval varies it: the ablation (§8) runs the same model
  and scenario at 2 and at 4 actions per tick, and the
  manifest records the value. If 4 plays better without
  breaking the token budget, the default moves on evidence,
  not on argument. UNVERIFIED until the eval varies it.
- A query never counts toward the cap (already true), and a
  query-only tick is not an idle tick when the query was used
  (§7(a)).
- The cap is recorded in the run manifest (EVALUATION.md
  phase 1 already requires the tick budget; the action budget
  joins it).

### (e) The snapshot surfaces problems only: add opportunities, as facts, not instructions

**The facts.** Attention is threats, low stocks, new arrivals:
what is wrong, what changed, what needs acting on. There is no
opportunities section anywhere in the code (§2.3). The model
cannot see a surplus, an idle skilled dwarf, a caravan as an
opening, a season change, or a survey find, except as a raw
number it is not pointed at.

**The failure mode.** A caravan arrives (an arrival item, framed
as something to notice) while the fort holds a surplus of crafts
and no food problem. The model has no prompt to consider trading,
because nothing in the snapshot says "you have something to sell
and someone to sell it to". The tactic, trade the surplus for
the metal the fort lacks, is invisible, not forbidden. The
harness does not need to suggest the trade. It needs to make
the trade visible.

**Verdict: add an opportunities section, with strict rules.**

- A second, lower-priority list in the snapshot, after
  attention: at most 3 items, each one sentence of fact plus
  the query route for detail. Examples: "A caravan is at the
  depot with goods to trade (query /v1/units?kind=traders).",
  "The fort holds 40 surplus crafts and drink is above the
  floor.", "Urist the mason is idle and has no job; the fort
  has no rooms built.", "Autumn ends in 20 days; the first
  caravan of the season arrives in spring."
- Opportunities never carry a suggestion. They never name an
  action. They never pause the game. They are facts the agent
  may act on or ignore, and ignoring one costs nothing: no
  score component, no attention escalation, no diary note.
- The caravan briefing already carries the framing: "no
  penalty, just a missed opportunity." The snapshot adopts
  that framing verbatim.
- The section is capped the same way attention is capped, so
  it cannot bloat the snapshot. If there are more than 3
  opportunities, the harness picks the 3 with the most
  concrete facts and drops the rest, and the full list is
  behind a query route, like everything else.
- The opportunities are derived from state the harness already
  collects (stocks, units, events, survey, season), not from a
  new observation pass. If an opportunity cannot be derived
  from existing state, it is not added until the state exists.

## 8. How to know the balance is right

The balance is not a matter of opinion. It is measured, by the
eval framework and by the run logs, and the measurement is what
decides whether a piece of guidance stays or goes.

### 8.1 The guidance ablation (docs/EVALUATION.md phase 6)

The same model, the same scenario, the guidance layers on
versus off. That is the experiment that attributes score to
the model versus the harness, and it is the only honest way to
answer "does this guidance help or does it cage the agent".

What "off" means must be specified before the ablation runs,
because "guidance" is seven layers plus the prompt. The
ablation varies them in groups, not all at once, or the result
cannot say which layer mattered:

- **A: suggestion off.** No suggestion in the snapshot. The
  attention section, the catalog, and the wiki stay.
- **B: briefings and wiki prefetch off.** Events arrive bare.
  The wiki stays queryable on demand.
- **C: "know nothing" instruction off.** The model is told it
  may use its own knowledge of Dwarf Fortress. The catalog and
  snapshot are unchanged.
- **D: all guidance off.** The bare protocol: snapshot,
  catalog, actions, events. This is the dkta end of the
  spectrum, and the comparison with dkta's numbers is the
  point.

Each variant runs the day tier (10 repeats on the anchor
scenario) at minimum, and the season tier when the suite can
afford it. The verification bar from EVALUATION.md stands: the
ablation reproduces the same score with guidance on as the
ordinary suite run, so the ablation is measuring the guidance
and not a different harness.

The flag to disable guidance layers does not exist today
(§2.8). Building it is §9 phase 6, and it comes last because
it doubles the cost of every suite, but it comes, because
without it every claim in this doc about what guidance is
worth is an assertion.

### 8.2 What to watch in run logs

Four numbers, all computable from the run log today except
where noted, and all reported per run in the manifest:

1. **Suggestion uptake rate.** Suggestions followed divided by
   suggestions offered (already computed by
   `suggestion_matches()` in scoring.py). A rate near 100%
   is not a success: it means the agent is a rubber stamp, or
   the suggestions are so narrow that following them is the
   only sane play. A rate near 0% with a high score means the
   suggestions are wrong and the agent knows it. The healthy
   range is in the middle, and the number is meaningless
   without the next two.
2. **Deviation rate.** Ticks where the model acted and its
   actions did not match the suggestion's job, divided by
   ticks with a suggestion. A deviation rate of zero across a
   run is a red flag for the harness, not a gold star for the
   model: it means the agent never found a reason to disagree,
   and in an emergent game that is suspicious.
3. **Deviation success rate.** Of the deviating ticks, the
   fraction where the deviating action succeeded (ok=true) and
   the fort's state improved on the dimension the action
   addressed. This is the number that decides §7(a): if
   deviations succeed, the suggestion penalty is punishing
   good play. It needs the deviation-outcome record from §9
   phase 1; today the log carries the action and its ok flag,
   but not the before/after improvement read.
4. **Patience versus stall.** Idle ticks split into waiting
   ticks (a declared `waiting_for` with a verified condition)
   and true stalls (no actions, no wait, no query used).
   Today the log cannot split them: an idle tick carries only
   the model's reasoning text, truncated to 200 characters.
   The `waiting_for` field from §7(b) is what makes the split
   computable.

Two more numbers from the eval side: the score per token and
the score per dollar (EVALUATION.md efficiency axis). Guidance
costs tokens, every briefing, every prefetch, every
suggestion is context the model reads. A guidance layer that
adds score but doubles the token cost per day is a worse deal
than it looks, and the leaderboard's sortable efficiency
columns are where that shows.

### 8.3 The test that matters most

The dkta comparison is the external check. Urist's two verified
1-day scores (91.8, 91.7) are smoke-tier, not benchmark results,
and they say nothing about freedom. The test that matters is
the season tier, guidance on versus off, against dkta's
two-year numbers: if Urist's guidance-on runs beat its
guidance-off runs on the same scenario, the guidance earns its
keep. If they do not, the guidance is decoration, and the
harness should get lighter, not heavier. The doc does not
predict the outcome. That is the point of running it.

## 9. Implementation phases

In order. Each phase has a concrete live-verification bar. A
phase is not done until the bar is met.

**Phase 1: log the freedom metrics.** Deviation rate,
deviation success (action ok flag plus the before/after
improvement read on the dimension addressed), query-use
marker, and the deviation reason verbatim. No behaviour
change: the driver, the scorer, and the log writer only.
Verification: score an existing run log and report the four
numbers from §8.2 from the log alone, with no hand counting;
offline tests for the new log fields.

**Phase 2: suggestion penalty reform (§7(a)).** Scoring v2
change: the suggestion component scores the outcome, not
obedience; no stacking with the idle-tick penalty; query-only
ticks that were used do not count as idle; a correct fail-fast
costs nothing extra. Verification: offline tests on synthetic
logs (a deviation that worked scores no penalty; a deviation
that let drink fall scores the penalty; a query-use tick scores
no idle penalty); the two verified 1-day runs re-scored under
v2 with the change explained in the evidence block.

**Phase 3: waiting signal and escalation rewrite (§7(b)).**
The `waiting_for` field in the reply schema, the verified-wait
rule with its bounded window, the rewritten escalation text,
the fallback firing only outside a verified wait, the fallback
logged as a daemon action, and the reset-bug fix (stall counter
resets only when the fallback actually ran; otherwise
`fallback_unavailable` is logged). Verification: a live M1 run
in which the model declares a wait for a brew to complete and
the stall counter holds; the escalation text read back from
the run log; a live run in which no suggestion parses and the
log shows `fallback_unavailable` instead of silence.

**Phase 4: opportunities section (§7(e)).** The second list in
the snapshot, max 3 items, facts plus query routes, no
suggestion, no pause, no score. Derived only from state the
harness already collects. Verification: a live run in which a
caravan arrival and a surplus appear as opportunities, the
model acts on one and ignores the other, and the ignored one
costs nothing in the score.

**Phase 5: goal-hierarchy escape hatch (§7(c)).** The prompt
line permitting deviation with a stated reason; the reason
logged with the action; the planner's `decide()` carrying a
reason field on deprioritised goals. Verification: a live run
in which the model works against the hierarchy with a stated
reason and the deviation and its outcome appear in the journal
and the diary; an offline test that a deprioritised planner
goal carries its reason and does not enter backoff.

**Phase 6: guidance ablation flag (§8.1).** The flag to
disable guidance layers in the four groups (A-D), wired into
the driver and the manifest. Verification: two runs, same
model, same scenario, guidance on versus off, both producing
manifests; the guidance-on run reproduces the ordinary suite
score (the EVALUATION.md phase 6 bar).

**Phase 7: skill library capture (§6.2).** Detection of a
deviation that worked (mechanical: suggestion not followed +
action ok + measurable improvement), recording as a candidate
skill with preconditions, verification check, evidence, and
the model's stated reason, promotion after a second live
verified success, and offering as an option with evidence,
never as an instruction. Verification: a tactic discovered in
a run (a trap layout, a wall shape, a stockpile arrangement,
whatever the agent invents) is captured as a candidate, and
the same sequence run again on a different fort state passes
its verification check and enters the library.

**Phase 8: daemon-side fallback (§7(b)).** The GOAL.md
fallback policy as implemented code: while a model run is in
progress, the daemon watches the stall signal and, on a
verified stall with no parseable suggestion, takes only pause
on threat and queue drink/food production, logs them as daemon
actions, and stops as soon as the model acts again.
Verification: a live run in which the model stalls with no
parseable suggestion and the daemon's two critical actions
appear in the journal as daemon actions, with the model
resuming afterwards.

## 10. Open questions

- Whether a `waiting_for` declaration can be relied on: the
  field is easy to add to the reply schema (the driver already
  parses JSON), but whether models use it honestly instead of
  gaming it, declaring a wait to dodge the stall counter,
  is UNVERIFIED until a live run. The bounded window and the
  verifiable-condition rule are the guards; whether they are
  enough is a live question.
- Whether the ablation's "guidance off" state is well-defined:
  which layers off, in which combination, and whether the
  "know nothing" instruction counts as guidance for this
  purpose. UNVERIFIED until EVALUATION.md phase 6 specifies
  the variants.
- Whether 2 versus 4 actions per tick changes outcomes.
  UNVERIFIED until the eval varies it.
- Whether the deviation-success improvement read can be
  computed mechanically for every kind of action, or only for
  the survival dimensions (drink, food, threats). A trap that
  catches a goblin is measurable; a room layout that makes
  dwarves happier is measurable only through stress trends
  over days, not ticks. UNVERIFIED until phase 1 tries it.
- Whether the skill library's "second live verified success"
  bar is the right threshold, or whether a tactic that worked
  once in a specific fort state should stay a candidate until
  a matching state recurs. UNVERIFIED until phase 7 runs.
- Whether the caravan briefing's trade option should be
  removed until the trade system lands, or kept as a
  forward-looking statement. The doc's position is that a
  briefing must not name an option the agent cannot take,
  so it should be removed or rewritten, but the wording
  belongs to the trade work, not this doc. UNVERIFIED until
  the trade system lands.

## 11. Sources

- GOAL.md (goal dir): the 7 guidance layers; the one
  suggestion per tick ("a default, not an instruction");
  "the daemon owns the loop, the agent owns decisions"; stall
  handling; the top bar; the dogfooding mandate; the closed
  loop; the skill library and reflection designs; the daemon
  fallback policy promise.
- docs/PLANNER.md: the priority table, the 180 s backoff,
  the missing-section rule, the "does not do" table.
- docs/DAEMON.md: the tick cycle, the pause guard, the
  reload and run guards, the config table
  (`planner_max_actions: 2`).
- docs/PROTOCOL.md: the API, the task registry, the guarded
  endpoints, the event catalog. Note: its task list
  (build-still, build-carpenter, build-kitchen,
  food-stockpile, autolabor, ensure-drink, ensure-food) is
  stale against `daemon.TASK_DEFS` today (brew, cook, farm,
  gather, make_barrel, make_bed), the protocol doc needs
  updating when the task registry changes, not the other way
  round.
- docs/SCORING.md: the competence penalties, the suggestion
  matching rules, the final-snapshot exclusion, the two
  verified scores (91.8, 91.7).
- docs/EVALUATION.md: the dkta.dev summary (verified from
  the article itself), the FLE and BALROG lessons, the score
  v2 expansion, the run manifest, the anti-gaming rules, and
  phase 6 (guidance ablation).
- docs/ACCEPTANCE.md: the measurable criteria for "the
  harness plays the fort".
- Code read 2026-11-27: `src/dfagent_harness/scoring.py`
  (competence_score, suggestion_matches), `scripts/m1_driver.py`
  (SYSTEM_PROMPT, STALL_ESCALATE_TICKS 3, STALL_FALLBACK_TICKS
  6, MAX_ACTIONS_PER_TICK 2, DEFAULT_WINDOW 150, the
  escalation text, the fallback reset bug),
  `src/dfagent_harness/assembler.py` (suggest(), the
  survival-narrow coverage, NEVER_CUT),
  `src/dfagent_harness/attention.py` (build_attention,
  problems only), `src/dfagent_harness/planner.py`
  (decide(), the priority table), `src/dfagent_harness/daemon.py`
  (TASK_DEFS, run_task, no fallback policy),
  `src/dfagent_harness/catalog.py` (introspection-built,
  cannot drift), `src/dfagent_harness/diagnose.py`,
  `src/dfagent_harness/briefings.py` (caravan drift),
  `src/dfagent_harness/wiki.py`, `src/dfagent_harness/server.py`
  (GET /v1/memory/why/<id> exists).
- docs/MISTAKES.md (being drafted in parallel, 2026-11-27):
  the mistake ledger, the mirror of the skill library. The
  two docs share the capture-route shape defined in §6.3.
