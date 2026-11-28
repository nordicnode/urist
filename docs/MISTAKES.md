# Mistakes: the mistake ledger

The AI must be able to track the common mistakes it keeps making, write
them down, and refer back to them throughout play. This document designs
that mechanism: a mistake ledger, the rules for what enters it, how a
mistake becomes a lesson, and how the lesson reaches the AI at the exact
tick it matters.

This is the mirror image of the skill library. The skill library is the
positive side: verified ways of doing things that work. The ledger is the
negative side: verified ways of doing things that do not work, and the fix
that does. Both are captured the same way, from live play, and both are
retrieved by relevance, never dumped.

## 1. Why the agent repeats mistakes today

The harness already knows when something fails. It does not remember it.

The evidence is in a real run log. In run `m1-20261127-005919` the model
tried `build_furniture` to place a Bed four times, across tick 1 and tick
4, and failed all four times with the same reason: "no BED item in stock
to place a Bed (make one at the carpenter first)". The reason itself names
the fix. The model repeated the action anyway, twice per tick, because
nothing remembered the failure from one tick to the next.

The driver's feedback window is one tick long. `m1_driver.py` keeps the
previous tick's action outcomes in `last_action_results`, feeds the last
four lines into the next prompt, and then clears the list. A failure is
visible for exactly one tick. A failure from two ticks ago is gone.

The rest of the system has the same shape:

- `diagnose.py` (`diagnose_failure`) matches a failed action and its
  reason against known causes and returns a fix in plain words, or None
  when the cause is unknown. It is stateless: it diagnoses this failure
  and forgets it. Its docstring says the caller records the failure
  "so the loop detector can still see it", but no loop detector exists.
  The only mentions of one in the code are two comments
  (`planner.py:854`, `diagnose.py:13`). GOAL.md step 4 lists the loop
  detector as a missing component.
- The planner records decisions in `journal.db` (`decisions` table: action,
  reason, goal_key, ok, result, tick, year) and waits out a 180 second
  backoff after a failure. The backoff stops the planner retrying, but it
  does not teach the agent anything: the backoff is wall-clock time, not
  memory, and it applies to the planner's goals, not to the model's
  actions.
- The M1 driver never writes to the journal at all. Model actions and
  their outcomes exist only in the run logs (`logs/m1-*.jsonl`). The run
  logs are not queryable: nothing in the harness reads them back, and
  the evaluation doc records that they carry no token counts, no
  wall-clock, no model parameters, no harness commit, and no classified
  failure reason (`model_failure` is a count, not a cause).
- `store.py` (`world.db`) keeps snapshots, areas, survey, trends,
  per-unit history, and deaths. It keeps no failure records at all,
  even though GOAL.md step 4 promises them: "failure records (what was
  tried, why it failed, how many times)".
- Scoring counts repeated failures after the fact (`scoring.py`
  `repeated_failures`: for each (action, job) group that failed twice
  or more, count the failures beyond the first; minus 10 per repeat).
  That is a post-hoc penalty, not a memory. The score knows the agent
  repeated a mistake only after the run is over.

So the harness can diagnose a failure, wait out a backoff, and penalise
a repeat in the score, but it cannot tell the agent, at the tick it is
about to repeat the mistake, "you have done this before, here is why it
failed, here is what works instead". That sentence is what this doc
designs.

## 2. What counts as a mistake

A mistake is a failed attempt whose cause is known and whose fix is
known, or whose cause is knowable from the recorded state. The taxonomy,
in the order the harness meets them:

1. **Failed action.** An action the harness refused or that failed
   verification, with a reason: no empty barrels, no BED item in stock,
   no reachable site. The reason is the cause; `diagnose_failure` names
   the fix. This is the commonest kind and the one the ledger is built
   for first.
2. **Cancelled job with a cause.** A job the game cancelled (no
   material, no path, workshop destroyed) where the cancellation report
   names the cause. The diagnosis machinery is the same as kind 1; the
   difference is the failure is discovered from the game's reports
   rather than from an action result.
3. **A decision whose outcome was bad.** The action succeeded but the
   result was wrong: the agent queued a job that consumed the last of a
   scarce stock, built in a place that blocked a corridor, or sold the
   fort's created wealth and stopped the next migrant wave. Named by
   what it cost: a dwarf, a season, a stockpile, a wave. The cause is
   established after the fact, from the store, not assumed at the time.
4. **A repeated failure.** Kinds 1 to 3 happening again with the same
   pattern after the fix was already known. A repeat is a different
   kind of record from a first failure: it is evidence the first
   diagnosis did not reach the agent, or the agent did not believe it.
5. **A stall.** No actions for 3 ticks (the driver's escalation
   threshold) or 6 ticks (the fallback threshold). A stall is a
   mistake of omission: the agent had a decision to make and made
   none. The record names what the agent was ignoring: the suggestion,
   the attention items, or the last failure.
6. **A model failure.** A bad parse, bad parameters, or a transport
   failure. These are classified the way the evaluation doc proposes:
   transport, provider, parse, or timeout. A parse failure is a
   mistake in the reply; a transport failure is not, but it is still
   recorded, because a model that fails the same way every run is a
   fact the harness needs (see section 2.1).
7. **An ignored suggestion that proved wrong.** The agent declined the
   suggestion, took a different action, and the outcome was worse than
   the suggestion's stated goal. This is the only kind that requires
   judging the agent's choice against an alternative, so it is recorded
   only when the comparison is checkable from the store (the
   suggestion's goal was measurable and the outcome missed it).
8. **A preventable death.** A dwarf died and the cause was in the
   harness's power to name beforehand: thirst with drink at zero and
   no brewer, starvation with food at zero and no cook, a wound left
   untreated with a hospital unbuilt. The death investigation
   (`store.diagnose_death`) already attaches a cause from the unit's
   history; a preventable death is a mistake record that points at the
   death record.

### 2.1 What does NOT count

- **One-off noise.** A single failure with no pattern behind it is a
  candidate record (section 4), not a lesson. The harness records it
  and waits.
- **A failed experiment the AI ran deliberately.** If the agent tried
  something unproven on purpose and it did not work, that is not a
  mistake: it is the cost of learning, and it belongs in the skill
  library's negative evidence, not the ledger. The distinction is
  intent, and intent is only known if the agent says so: an action the
  agent marks as an experiment (see section 4.3) is exempt from the
  ledger even when it fails.
- **A model outage.** A transport failure (Free Pi IncompleteRead,
  HTTP 429) is the provider's failure, not the agent's. It is recorded
  as a model failure for the run's evidence, but it never becomes a
  lesson and it never counts toward a pattern. Run `m1-20261127-073557`
  had two IncompleteRead failures; neither teaches the agent anything
  about the game.
- **A harness bug.** If the failure was the harness's fault (a stale
  cache, a wrong enum, a misread stock), the record belongs in the
  coordinator log and the fix belongs in the code, not in the agent's
  ledger. The ledger is about the agent's mistakes, not the harness's.
  The test is simple: if the fix is a code change, it is a harness
  bug; if the fix is a different action, it is an agent mistake.

## 3. Where mistakes are detected today

| Source | What it sees | What it cannot see |
| --- | --- | --- |
| `diagnose_failure` | This action, this reason, this fix | Any previous failure; whether the fix was tried |
| Death investigation (`diagnose_death`) | This death, its cause from unit history | Whether the same cause killed before; whether the fix was applied |
| Run-log review | Everything, after the run | Nothing during the run; nothing queryable; no classified reasons |
| Driver stall detection | No actions for 3 or 6 ticks | Why the agent stalled; whether it stalled before |
| Planner backoff | A goal failed, wait 180 s | The model's actions; the cause beyond the decision row |
| Scoring (`repeated_failures`) | Repeats, after the run | Nothing the agent can act on; no cause, no fix |
| Attention (`attention.py`) | A problem is developing now | That the same problem developed before, and what fixed it then |

The gaps, stated plainly:

- **No failure table.** `world.db` has no table for failures, so the
  causal memory GOAL.md step 4 promises does not exist yet. The journal
  has `decisions.ok` and `decisions.result`, but those are planner
  decisions, not model actions, and the journal has no cause column, no
  diagnosis column, and no count column.
- **No loop detector.** GOAL.md step 4 names it as a component; it was
  never built. The planner's backoff is the only repetition control,
  and it is time-based, not count-based, and it covers planner goals,
  not model actions.
- **The driver's memory lasts one tick.** `last_action_results` is
  cleared after a single use. A failure two ticks old is invisible.
- **Model actions never reach the store.** The driver writes JSONL run
  logs; the journal and the store never see them. So the store cannot
  answer "how many times has the agent tried to place a bed with no
  bed in stock", and the journal cannot answer it either.
- **Run logs are write-only.** Nothing reads them back. The run-log
  review after every M1 run is done by a human (or the parent agent)
  reading the file. The harness itself learns nothing from its own
  logs.
- **Diagnosis has no memory.** `diagnose_failure` returns the same fix
  for the first failure and the tenth. It cannot say "this fix was
  already given twice and the agent tried it and it did not work", so
  it cannot escalate to a different fix, which is what GOAL.md's
  escalation rule requires.

## 4. The record: the mistake ledger

### 4.1 Where it lives

A `mistakes` table in `world.db`, in the daemon's state dir, next to
the existing tables. The choice is deliberate, against the alternatives:

- **Not a markdown file like `diary.md`.** The diary is a narrative
  rendered for reading; a ledger is queried by pattern, by action, by
  tick, and by count. Markdown cannot answer "how many times has this
  pattern failed" without parsing, and the GOAL.md rule is that state
  lives in the harness's store, not in piles of files.
- **Not a JSON file.** Same objection, plus the store already owns the
  causal memory (unit history, deaths, trends) and the ledger must join
  with it: a mistake record points at the death it caused, the unit
  history that proves the cause, and the journal decisions that show
  the fix was or was not tried. A separate file cannot join.
- **Not a table in `journal.db`.** The journal is the planner's record
  of its own decisions; the ledger is the model's record of its
  mistakes. They are joined by tick, the same way the two databases
  are joined today, and the separation keeps the planner's write path
  untouched. If the two ever merge, that is a separate decision, not
  part of this design.
- **One table, not two.** Candidates, patterns, lessons, and stuck
  records are the same record at different ages (section 5). Splitting
  them into tables would force a migration every time a record is
  promoted, and the promotion history (when it became a pattern, when
  it became a lesson) is itself evidence worth keeping.

### 4.2 What one record holds

| Field | What it is | Source |
| --- | --- | --- |
| `pattern_key` | The stable identity of the mistake: action + failure kind + the failing condition, e.g. `build_furniture:place_bed:no_bed_in_stock`. Built from the action name, the job or item named in the reason, and the diagnosis key. Two failures with the same pattern key are the same mistake. | Harness, from the action and the diagnosis |
| `kind` | One of the eight kinds in section 2. | Harness, from where it was detected |
| `context` | The situation it happened in, in game terms: the fort's stocks at the time, the season, the goal the agent was pursuing, the suggestion it was following or declining. Short, structured, not prose. | Harness, from the snapshot at the tick |
| `cause` | Why it failed, in plain words, traced to a recorded event, decision, or observation. Same grounding rule as the diary: no invented causes. | Diagnosis, death investigation, or the AI (validated, section 4.3) |
| `fix` | What works instead, naming the exact action and parameters, plus what it needs and the current stock of what it needs. The same shape as `diagnose_failure` output. | Diagnosis, or the AI (validated) |
| `fix_source` | Where the fix came from: `diagnosis` (the harness knew it), `agent` (the model proposed it), or `verified` (the fix was tried live and worked). | Harness |
| `count` | How many times the pattern has failed. Incremented on each repeat. | Harness |
| `first_tick`, `last_tick` | First and last occurrence, in game ticks. | Harness |
| `fix_tried_count`, `fix_worked_count` | How many times the fix was tried after the record existed, and how many times it worked. This is what makes the learning loop (section 7) measurable. | Harness, from later action outcomes |
| `status` | `candidate`, `pattern`, `lesson`, `retired`, or `stuck`. See section 5. | Harness |
| `evidence` | Pointers, not copies: journal decision ids, run-log file and line numbers, event ids, death record ids. Enough to re-derive the record from the sources. | Harness |
| `recorded_by` | `harness` or `agent`. AI-recorded lessons are flagged so the harness knows they were proposed, not detected. | Harness |

The record is the pattern, not the instance. Four failed bed
placements with the same reason are one record with `count` 4, not four
records. The instances are the evidence; the record is the lesson.

### 4.3 How a record is created: two routes

**Route 1: harness-detected.** The harness creates a record whenever a
detection source fires (section 3): an action fails with a diagnosis,
a job is cancelled with a cause, a death is diagnosed preventable, a
stall threshold is crossed, a model failure is classified. The record
is created with `status` candidate and `recorded_by` harness. No model
involvement, no extra tokens: the harness already has the action, the
reason, and the diagnosis; recording is a row insert.

**Route 2: AI-recorded.** The model notices its own repeated mistake
and writes it down. This is the route Mikey asked for, and it needs a
real mechanism, not a hope. The mechanism is a catalog action,
`record_lesson`, with parameters: the pattern (what it keeps doing),
the cause (why it fails), the fix (what works instead), and the
evidence (which tick, which action, which outcome). The harness
validates the submission before accepting it:

- The pattern must match at least one recorded failure: the action
  named must appear in the journal or the run log with a failed
  outcome. A lesson about something that never failed is refused.
- The cause must trace to a recorded event, decision, or observation:
  the same grounding rule as the diary. A cause that cannot be traced
  is refused, with the refusal naming what is missing.
- The fix must be a legal catalog action with legal parameters. An
  illegal fix is refused, with the legal values named, the same way
  any action validation works.

A refused `record_lesson` is itself a one-line outcome fed back to the
model, not a run failure. An accepted record is created with
`recorded_by` agent and `status` candidate, and it follows the same
promotion rules as a harness-detected one. The AI never writes
directly to the table: it proposes, the harness validates, the harness
writes. That is the same boundary as every other action, and it is what
keeps the ledger grounded.

The two routes converge on the same table and the same promotion
rules. A record the harness detected and a record the agent proposed
about the same pattern are the same record: the pattern key decides,
not the author.

## 5. When a mistake becomes a lesson

The threshold is count-based, and it is tied to the escalation rule
GOAL.md already states: same fix once, different fix next, then flag
stuck.

- **Once: candidate.** The record exists and is counted. It is not
  surfaced to the agent. One failure is noise: a typo in a parameter,
  a stock that was one unit short, a job that was cancelled for a
  reason that will not recur. Surfacing it would be nagging, and a
  ledger that nags is ignored.
- **Twice: pattern.** The same pattern key fails a second time. The
  record becomes a pattern and is surfaced, but only in the relevant
  context (section 6). Twice is the point where the harness stops
  assuming noise: either the agent did not see the first diagnosis,
  or the diagnosis was wrong, or the agent disagreed with it. All
  three are worth knowing.
- **Three times, or fix verified live: lesson.** A pattern that fails
  a third time becomes a lesson, and so does a pattern whose fix was
  tried live and worked. The two routes to lesson status are
  deliberate: repetition proves the mistake is real, and a verified
  fix proves the lesson is actionable. A lesson is surfaced
  aggressively (section 6) because it has earned it.
- **Stuck.** A lesson whose pattern fails again after the lesson was
  surfaced is escalated to stuck. This is the third step of GOAL.md's
  escalation rule made executable: same fix once, different fix next,
  then flag stuck. The harness cannot enforce that rule today because
  nothing counts repetitions; the ledger is the counting. A stuck
  record becomes a P0 attention item, a journal anomaly, and a diary
  thread (section 6), and it stays stuck until the fix is tried and
  works, or a human clears it. A stuck record is never silently
  retired.
- **Retired.** A lesson retires when its fix has been tried and worked
  three times after the lesson was created (`fix_worked_count` 3), or
  when the pattern has not recurred for a full in-game year. Retirement
  means it stops surfacing, not that it is deleted: it stays in the
  table, queryable, and it is reactivated if the pattern recurs. A
  retired lesson that recurs is a pattern again, not a new candidate:
  the harness remembers that this was once a lesson.

The numbers (2 for pattern, 3 for lesson, 3 successful fixes for
retirement, 1 year for staleness) are starting values, chosen to match
the acceptance rule in GOAL.md: the agent must not repeat a failed
action more than twice without changing approach. The ledger is the
instrument that makes that rule checkable: a repeat count of 3 on a
pattern the harness already surfaced is a failed acceptance, visible
in the run's evidence, not a feeling.

## 6. Model presentation
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

The rest of this section is the presentation design from the
original draft, kept and renumbered: retrieval by relevance, never
a dump. A lesson reaches the agent only when the current tick
matches it, and only in the form the tick needs.


Retrieval by relevance, never a dump. The ledger is never pasted into
the snapshot. A lesson reaches the agent only when the current tick
matches it, and only in the form the tick needs.

**The matching rule.** A lesson matches a tick when one of these is
true:

- The agent's last action, or the action it is about to take, shares
  the lesson's pattern key (same action, same failing condition). This
  is the direct case: the agent is about to place a bed with no bed in
  stock, and the ledger holds that pattern.
- The current suggestion names the action the lesson is about, or the
  lesson's fix is the suggestion. The suggestion and the lesson agree,
  and the lesson is the reason the suggestion is right.
- The current attention list carries an item whose kind matches the
  lesson's context (a low-drink attention item and a brewing lesson,
  a wounded-dwarf item and a bed lesson). The attention item is the
  symptom; the lesson is the history.

**The size cap.** At most 2 lessons per tick, in the snapshot after
the suggestion, one line each, in this shape: "You have tried X 3
times. It fails because Y. Do Z instead." The count, the cause, and
the fix, nothing else. A stuck record counts as one of the two and
always comes first. Full detail is behind the query routes, never in
the snapshot.

**Token cost.** At most 2 lessons per tick, in the snapshot after
the suggestion, one line each, in this shape:

```
Lesson: tried queueing make_bed 3 times. It fails because no bed in stock. Check stocks first.
Lesson: tried building with no free site 2 times. It fails because the site was occupied. Ask /v1/sites first.
```

At 7 dwarves, the two lines as written above are 205
characters: about 68 tokens by the accountant's
3-chars-per-token rate, 51 on the wire. At 50 dwarves the cost
is the same: the cap is 2 lessons per tick regardless of
population, and the lines do not grow with the number of dwarves,
the number of lessons in the ledger, or the number of past runs.
A stuck record counts as one of the two and always comes first.
If a future change makes the section grow with any of those, the
change is refused until the section is capped again.


**The routes.**

- `GET /v1/lessons`: the active lessons (status pattern, lesson, or
  stuck), filterable by action, kind, and status. Returns the record
  fields from section 4.2, one row per lesson.
- `GET /v1/lesson/<id>`: one record in full, with its evidence
  pointers resolved to the journal rows and run-log lines it cites.
- The per-tick snapshot carries at most the 2 matching lessons (above).
  The assembler owns the matching, and the lessons section is in the
  NEVER_CUT set with attention, header, status, and suggestion: a
  lesson that matches is never shed to fit the token budget.
- **Briefings.** When a new situation starts (a strange mood, a siege,
  a caravan, a migrant wave) and a lesson matches that situation's
  kind, the briefing carries the lesson's one line. The briefing is
  the right place for it: the agent is about to act in a new
  situation, and the lesson is what the fort already learned about
  that situation.
- **The diary feed.** A lesson that is still open is an open thread,
  carried the same way the diary's threads are carried today (derived
  from the store, with a since-date). A stuck lesson is a thread that
  does not close until the fix works. A retired lesson closes its
  thread, and the diary entry for the day it retires says so in one
  line: the fort stopped making that mistake.

**What is never surfaced.** Candidates are never surfaced (one failure
is noise). Retired lessons are never surfaced unless the pattern
recurs. The full ledger is never surfaced: the agent asks for it by
query, the way it asks for any other state.

**Opportunities: at most 3, facts only.** The opportunities
section carries at most 3 lesson entries, each one line: facts
plus a query route, never a suggestion, never a pause. Ignoring
one costs nothing. A lesson entry fires only when the fact is
actionable and the snapshot alone does not already say it, and it
never appears when the same lesson is already in the snapshot's
2-lesson slot: the snapshot slot and the opportunities entry are
the same lesson in two places, never two copies. Examples of what
qualifies:

- "Lesson: bed queued 3 times with no bed in stock. Query
  /v1/lessons for the record."
- "Lesson: site occupied twice. Query /v1/sites for a free site."

**What the system deliberately does NOT push, and why.** The
full ledger is never surfaced: the agent asks for it by query,
the way it asks for any other state. Candidates are never
surfaced (one failure is noise). Retired lessons are never
surfaced unless the pattern recurs. A lesson is never pasted
into the snapshot outside the matching rule: the count, the
cause, and the fix, one line each, at most 2 per tick, in the
NEVER_CUT set with attention, header, status, and suggestion,
so a lesson that matches is never shed to fit the token budget.
The presentation gives the model what it needs to decide, not a
script to follow (HARNESS_ROLE.md).


## 7. The learning loop

A lesson is not a plaque on the wall. The harness watches what happens
after it exists, and the record changes with the outcome.

- **The fix is watched.** After a lesson is created, the harness
  watches for the fix action in later ticks. Each time the fix is
  tried, `fix_tried_count` goes up; each time it works (the action
  succeeds and the postcondition holds), `fix_worked_count` goes up.
  This is the same before/after verification the action layer already
  does; the ledger just counts it against the lesson.
- **A lesson that works retires.** Three successful fixes retire it
  (section 5). Retirement is the harness saying the agent has learned
  it. The record stays, so the learning is not lost if the pattern
  recurs under a different model: a new model inherits the retired
  lessons of the old one, because the ledger belongs to the fort, not
  to the model. That is the point of storing it in the harness rather
  than in any model's memory.
- **A lesson that keeps failing escalates.** If the pattern recurs
  after the lesson was surfaced, the record goes stuck (section 5).
  Stuck is the harness admitting its guidance failed: the lesson was
  given, the agent saw it, and the mistake happened anyway. A stuck
  record is a P0 attention item, a journal anomaly, and a diary
  thread, and it is also a signal to the harness's own builders: either
  the diagnosis is wrong, the fix is wrong, or the lesson is not
  reaching the agent in a usable form. The run-log review after every
  M1 run checks stuck records first.
- **Reflection closes the loop.** GOAL.md step 6 defines reflection as
  periodic synthesis over the causal journal, triggered by an
  importance sum. The ledger is reflection's input and its output.
  The reflection pass runs over the mistakes table and the journal
  (not over the whole log) and does three things: it promotes
  candidates to patterns and patterns to lessons when the counts
  demand it (so promotion does not depend on the tick loop noticing);
  it retires lessons whose fixes have held or whose patterns have not
  recurred for a year; and it synthesises new lessons from patterns
  the tick loop never named, where two different pattern keys share a
  cause (for example, bed placement and barrel making both failing on
  "no wood" is one lesson about wood, not two lessons about furniture).
  Reflection runs outside the tick loop, at the day boundary, next to
  the diary write, so it never costs the agent a decision tick. Its
  output is a journal event and, when it promotes or retires a lesson,
  one line in the next snapshot's lessons section.
- **The loop is the acceptance.** GOAL.md's acceptance for failure
  memory is that the agent must not repeat a failed action more than
  twice without changing approach, and must be able to answer "why did
  X happen" from the store. The ledger makes both checkable: the
  repeat count is in the table, and the cause is in the record. A run
  whose ledger shows a pattern reaching count 3 after the lesson was
  surfaced has failed that acceptance, and the evidence block says so.

## 8. The mirror of the skill library

A lesson and a skill are the same kind of object with opposite signs:

- A skill is "do X this way because it works": a named action
  sequence over the typed catalog, with preconditions, a verification
  check, and success evidence attached. It enters the library only
  after a live verified success.
- A lesson is "do not do X because Y": a named pattern, with the
  cause, the fix, and failure evidence attached. It enters the ledger
  after a repeated failure, or after a fix verified live.

They share a store and a namespace. Both live in `world.db` (the
ledger as a `mistakes` table, the library as a `skills` table when it
is built), and both are keyed by the same pattern language: action
names, job names, and the failing or succeeding condition. That shared
namespace is what lets them reference each other: a lesson whose fix
is a verified procedure becomes a skill candidate (the fix, tried
three times and working, is the skill's success evidence), and a skill
whose procedure starts failing becomes a lesson candidate (the skill
stopped working, and the cause is the new lesson).

What must stay consistent between this doc and the companion
`docs/HARNESS_ROLE.md` (being drafted in parallel; it did not exist
when this doc was written, so the contract below is stated here and
must be reconciled when both docs land):

- **The capture route is the same.** Nothing enters either store
  without live verification: a skill enters after a verified success,
  a lesson enters after a repeated failure or a verified fix. No
  invented skills, no invented lessons.
- **The freedom rule is the same.** A lesson is a warning, never a
  block. The harness never refuses an action because a lesson says
  not to. It surfaces the lesson, lets the agent decide, and records
  the outcome either way. If the agent declines a lesson and the
  action works, the ledger records that too: the lesson's
  `fix_worked_count` does not move, but the pattern's count does not
  either, because the pattern did not fail. A lesson the agent
  repeatedly declines successfully is a lesson whose cause is wrong,
  and reflection retires it.
- **The retrieval rule is the same.** Both are retrieved by relevance,
  never dumped, and both are capped per tick. A tick carries at most 2
  lessons and the skill guidance it already carries; the two sections
  do not compete for the same budget, because a lesson and a skill
  about the same action are the same advice from opposite sides, and
  the assembler merges them into one line when they agree.

## 9. Implementation phases

Each phase has a concrete live-verification bar. Nothing is done until
it is verified live.

1. **The table and the harness-detected route.** Add the `mistakes`
   table to `world.db` with the fields in section 4.2. Wire the
   creation points: `diagnose_failure` returns a pattern key alongside
   the fix (it already computes the match; the key is the action plus
   the matched branch), and the caller records a candidate row. The
   driver records model failures classified as transport, provider,
   parse, or timeout. Verification: run an M1 day, force the known
   failure (place a bed with no bed in stock), and read the row back
   from the table with the right pattern key, cause, fix, and count 1.
   Then repeat the failure and read count 2.
2. **Model actions reach the store.** The driver writes each action
   and its outcome to the journal (a new `model_actions` table in
   `journal.db`, or decision rows with a `source` of `model`; decide
   at implementation time, but the journal must gain a way to tell a
   model action from a planner decision). Without this, the ledger
   cannot count model repeats, and the run logs stay write-only.
   Verification: run an M1 day and query the journal for the model's
   actions with their outcomes, matching the run log line for line.
3. **Promotion, surfacing, and the query routes.** Implement the
   thresholds in section 5, the matching rule and the 2-lesson cap in
   section 6, `GET /v1/lessons` and `GET /v1/lesson/<id>`, and the
   lessons section in the snapshot (in the NEVER_CUT set).
   Verification: replay the bed failure from phase 1 to count 3, and
   confirm the lesson appears in the next snapshot in the one-line
   shape, and that `GET /v1/lessons` returns it with the right fields.
   Confirm a candidate (count 1) does not appear.
4. **The AI-recorded route.** Add `record_lesson` to the catalog with
   the validation in section 4.3 (pattern must match a recorded
   failure, cause must trace to recorded state, fix must be a legal
   action). Malformed-input tests for the new action, per the standing
   rule. Verification: live, the model records a lesson about a
   failure it just made, the harness accepts it, and the row appears
   with `recorded_by` agent; then the model submits a lesson about a
   failure that never happened, and the harness refuses it with the
   reason named.
5. **The learning loop.** Implement the fix watching
   (`fix_tried_count`, `fix_worked_count`), retirement, and the stuck
   escalation with its P0 attention item, journal anomaly, and diary
   thread. Verification: live, a lesson's fix is tried three times
   and works, and the lesson retires and stops surfacing; then the
   pattern is forced again, and the lesson reactivates as a pattern
   with its history intact.
6. **Reflection.** The day-boundary synthesis over the mistakes table
   and the journal: promotion, retirement, and synthesis of shared
   causes across pattern keys. Verification: seed two pattern keys
   with the same cause (bed placement and barrel making, both failing
   on no wood), run reflection, and confirm it synthesises the shared
   lesson and records it with the evidence from both patterns.
7. **Deaths and the diary.** Wire preventable deaths (kind 8) into the
   ledger from `diagnose_death`, and carry open lessons as diary
   threads with since-dates, closing them on retirement. Verification:
   live, a preventable death creates a lesson record pointing at the
   death record, and the next diary entry carries the thread.

## 10. Open questions

- **Joining run logs to the journal by tick.** Run logs carry
  `tick_no` (the driver's decision-tick number) and a wall-clock
  timestamp; the journal carries game `tick`. Whether the two can be
  joined reliably for the evidence pointers in section 4.2 is
  UNVERIFIED. Phase 2 must settle it: either the driver writes the
  game tick into each action record, or the evidence pointer is the
  run-log file and line only.
- **Carrying a lesson in the model reply.** The `record_lesson` action
  is a catalog action, so it travels inside the model's normal action
  list. Whether `parse_model_reply` accepts a new action name with
  free-text parameters (pattern, cause, fix) without breaking the
  existing validation is UNVERIFIED until phase 4's malformed-input
  tests prove it. If free text in parameters is a problem, the action
  takes ids (a failed action's journal id, a diagnosis key) instead
  of prose, and the prose is assembled by the harness.
- **The diary's open threads are derived, not stored.** `open_threads`
  derives threads from the current unit-history samples and keeps
  nothing, so a closed condition simply stops appearing. A lesson
  thread needs a stored row to carry a since-date across days when
  the underlying condition is not visible in the samples (a lesson
  about a failure that happened last season has no current sample).
  Whether the diary feed can carry a stored lesson thread without
  changing its derivation is UNVERIFIED; phase 7 may need a small
  stored-threads table, or the lesson thread may be carried by the
  snapshot's lessons section alone.
- **The importance sum for reflection.** GOAL.md step 6 says reflection
  is triggered by an importance sum over cheap heuristics (death,
  threat, failure, goal-relevant events), not LLM-judged per event.
  What the weights are, and whether a day with three repeated failures
  crosses the threshold on its own, is UNVERIFIED. Phase 6 must pick
  weights and prove the trigger fires on a bad day and does not fire
  on a quiet one.
- **The 2-lesson cap against the token budget.** The lessons section is
  proposed for the NEVER_CUT set in the assembler. Whether two
  one-line lessons fit the per-tick budget at 100+ citizens without
  squeezing out attention items is UNVERIFIED; the assembler tests
  must measure it at scale, not at 7 citizens.
- **Skill-library table shape.** This doc assumes the library will be
  a `skills` table in `world.db` with the same pattern language as the
  ledger. The library is not built yet and its doc is the companion
  `docs/HARNESS_ROLE.md`, which did not exist when this doc was
  written. If the library lands with a different store or a different
  key, the shared namespace in section 8 must be revisited.

## 11. Sources

- GOAL.md step 4 (game memory: causal records, failure records,
  escalation "same fix once, different fix next, then flag stuck",
  death investigation loop; acceptance: no failed action repeated
  more than twice without changing approach) and step 6 (skill
  library as verified DATA, reflection as periodic synthesis
  triggered by an importance sum, failure reflection as one short
  sentence surfaced when the same action is considered again).
- `src/dfagent_harness/diagnose.py`: `diagnose_failure`: cause and
  fix in plain words, None when unknown, no invented fix; the loop
  detector it references does not exist.
- `src/dfagent_harness/store.py`: `world.db` tables (snapshots,
  areas, survey, trends, unit_history, deaths); `diagnose_death`;
  no failure table.
- `src/dfagent_harness/planner.py`: `Journal` decisions table
  (action, reason, goal_key, ok, result, tick, year), backoff 180 s,
  `goals_in_backoff`; the loop detector is a comment only.
- `scripts/m1_driver.py`: `last_action_results` (last 4 lines, one
  tick, then cleared); stall thresholds 3 and 6 ticks; model failures
  logged as kind `model_failure` with an error string; the driver
  never writes to the journal.
- `src/dfagent_harness/scoring.py`: `repeated_failures` (failures
  beyond the first per (action, job) group; minus 10 per repeat),
  minus 5 per model failure.
- `docs/EVALUATION.md`: run logs record none of token counts,
  wall-clock, parameters, commit, or scenario; `model_failure` is a
  count, not a classified reason; the proposed failure-mode taxonomy
  (failed action: model error / harness refusal with named fix / game
  constraint; model failure: transport / provider / parse / timeout).
- `logs/m1-20261127-005919.jsonl`: the bed-placement repeat: four
  failed `build_furniture` actions across ticks 1 and 4, same reason
  ("no BED item in stock to place a Bed (make one at the carpenter
  first)"), the fix named in the reason and ignored.
- `logs/m1-20261127-073557.jsonl`: two model failures, both
  IncompleteRead transport, consecutive count 1 each.
- `src/dfagent_harness/assembler.py`: NEVER_CUT set (attention,
  header, status, suggestion); the suggestion is derived from the
  attention list.
- `src/dfagent_harness/attention.py`: attention items P0-first, max
  8, with priority, kind, text, unit_id, pos, tick.
- `src/dfagent_harness/diary.py`: `open_threads` derives threads
  from current samples, stores nothing, closes when the condition
  clears.
- `src/dfagent_harness/server/routes_journal.py`: `GET /v1/journal` serves recent
  decisions and counts only.
- No wiki queries were needed: every game-mechanics claim in this doc
  (the brew chain, bed making, the drink floor) is already verified
  in the harness's own code and docs, so nothing was taken from
  memory or from the wiki second-hand.
