# Labor management

## 1. Purpose

Labor is how jobs get done in a fortress. Which labors a dwarf is allowed to do decides which jobs they can take, and their skill decides how fast and how well they do them. Get labor wrong and the fort fails in the most boring way possible: the brewer spends the day hauling stone, nobody cooks, the planter is digging, and the drink runs out while seven dwarves stand around with nothing assigned.

This doc is the design for a labor system the harness runs itself. It assigns labors from what it can observe, it keeps coverage of the labors that must never go empty, it trains new skill where the fort needs it, and it re-plans when events change the workforce. The agent sees a short coverage table, named gaps with fixes, and two or three reassignment options with a one-line why. It never sees the raw labor matrix.

Status: design doc. The only labor machinery that exists today is `labor_toggle` (one labor on one dwarf, verified live) and the per-dwarf skill and labor reads. Everything else in this doc is to be built, in the phases in section 10.

## 2. How labor works in Dwarf Fortress 0.47.05

All mechanics in this section come from the local wiki export. Page names are cited so any claim can be re-checked.

### 2.1 Labor is not skill

A labor is permission to do a kind of work. A skill is proficiency at it. A dwarf with the brewing labor enabled and no brewing skill will still brew, slowly and badly. A dwarf with Legendary brewing skill and the labor disabled will never brew. The harness must manage both facts separately: who is allowed, and who is good. (Labor)

There are 84 labors in the live runtime enum (MINE, CUTWOOD, CARPENTER, PLANT, BREWER, COOK, HERBALIST, FISH, HUNT, the eight HAUL_ labors, the medical labors, the crafting labors, and the rest). The full list is in `tests/fixtures/runtime-enums-0.47.05-r8.json` under `unit_labors`.

### 2.2 Work details and specialization

The game groups labors into work details. A detail can be set to "Only selected do this", "Everybody does this", or "Nobody does this". A dwarf can also be marked specialized: a specialized dwarf only accepts tasks from workshops or occupations they are assigned to, plus the labors assigned to them. (Labor)

The wiki's rule for a growing fort: specialize, so each dwarf has a very limited number of labors. A highly skilled dwarf doing one thing well beats a generalist doing everything slowly. But the wiki also warns that some dwarves get minor negative feelings from not being able to practice a craft or martial art for too long, so specialization is not free. (Labor)

Migrants arrive with work details already assigned. The harness must re-evaluate every new arrival instead of trusting what they walked in with. (Labor, Immigration)

### 2.3 Tool labors are exclusive

Mining, woodcutting, and hunting each need a tool (pick, battle axe, crossbow with quiver and bolts). A dwarf can hold only one tool labor at a time. Assigning a second one silently unassigns the first, and the dwarf drops the old tool where they stand. Tool assignment also overrides a squad uniform, so military dwarves must never be assigned any of the three tool labors. (Labor)

The military plan records the same constraint as Bug 1451: mining, woodcutting, and hunting labors conflict with military equipment, and the harness must never draft a dwarf whose labors cannot be cleared. (MILITARY.md)

### 2.4 Hauling

Hauling is the labor that kills forts quietly. The wiki puts it plainly: nothing bogs down production like the distraction of hauling jobs, and losing a fort because all the skilled laborers spend their time hauling is no fun. The wiki's fix is dedicated haulers, and it names the source: migrants who arrive with no skilled labor and poor attributes, the peasants, are best used as dedicated haulers. (Labor)

Hauling has no associated skill and never improves with practice. There is no such thing as a good hauler, only a dwarf whose time is cheap. That is the whole basis for the hauler pool in section 5.4. (Labor, Skill)

### 2.5 Skill levels, experience, and rust

Skill levels run Dabbling, Novice (1), Adequate (2), Competent (3), Skilled (4), Proficient (5), Talented (6), Adept (7), Expert (8), Professional (9), Accomplished (10), Great (11), Master (12), High Master (13), Grand Master (14), Legendary (15 and up). Each level costs 400 + 100 times the new level in experience, so Novice costs 500 and reaching Legendary from Grand Master costs 1,900, or 18,000 total. (Skill)

Higher skill means faster work and, for production labors, better quality. The quality roll adds the effective skill level, attribute bonuses, and flat bonuses for matching item and material preferences. A matching preference is worth, on average, four skill levels, which matters most for low-skill workers. Farming, plant gathering, and fishing use an older formula where skill decides quantity instead of quality, capped in effect at Legendary+10. (Skill)

Skills rust. A skill left unused is labeled rusty, then very rusty, and if it stays very rusty long enough it loses experience permanently. Skills above High Master accumulate rust silently until they are demoted below High Master and the rust becomes visible. The harness cannot see rust directly in the collect today, which is why section 6 needs a rust watch built from skill samples over time. (Skill)

Skills can also be taught in a demonstration, through a guildhall or military training. (Skill)

### 2.6 Attributes

Attributes are the other half of performance. Body attributes include strength, agility, toughness, endurance, and recuperation. Soul attributes include analytical ability, creativity, and social awareness. The dwarven medians are strength 1,250, agility 900, toughness 1,250, endurance 1,000 (humans sit at 1,000 on every attribute, so the medians are directly comparable). Attributes are associated with skills, and using a skill raises the attributes tied to it. (Attribute)

For matching, attributes are a tiebreaker, not the main signal. The wiki's quality formula says it takes about 500 points in a primary attribute, or 1,250 in a secondary one, to equal one skill level. A dwarf with Legendary skill and average attributes still beats a dwarf with Adequate skill and great attributes. (Skill)

### 2.7 Status penalties

Status ailments cut effective skill. Nausea, winded, stunned, dizzy, and fever each cut 50 percent. Blind cuts 75 percent. Extreme pain cuts 75 percent. Tired cuts 25 percent. Dehydrated and starving cut 50 percent. Multiple ailments compound. A dwarf who is famished or hollow-eyed from lack of sleep forges worse goods, so the harness must not judge a dwarf's skill by one bad day, and must not assign fine work to a dwarf in a bad state. (Skill)

### 2.8 Professions are a display, not an assignment

A dwarf's profession is set by their highest skill. It colors their name and tells you at a glance what they are best at, but it does not decide what they do. A dwarf with no skill above dabbling shows as "peasant". The harness must never treat profession as a labor assignment. It is a hint for ranking, nothing more. (Skill)

### 2.9 The manager and work orders

The manager noble is the only way to place bulk work orders across workshops. The relevant skill is organizer, fed by analytical ability, creativity, and social awareness. A manager needs an office (meager, with a chair) and does the work there. Once the fort reaches 20 citizens, work orders are not performed until the manager validates them, so the manager needs free time and must not be assigned to high-demand labors. Manager orders never worked in this harness without a manager noble appointed. (Manager, Labor)

The noble position ids, probed live from the entity raws, are manager 10, broker 12, bookkeeper 13. (actions.py)

### 2.10 Migrants arrive with labors already set

Migrant waves arrive once per season. The first two waves are hardcoded, 2 to 10 dwarves, and there is never a migration in the first winter. Later waves need fortress wealth reported by an outgoing dwarven caravan. Migrant skills are influenced by what the fortress needs: migrants with skills the fort uses a lot, or does not have at all, are more likely to show up, and important skills (mining, food production, basic crafting) are weighed more heavily. A migrant can arrive with skill as high as Legendary, and can bring equipment matching their skill, such as a miner bringing a pick. (Immigration)

That last fact is why labor re-planning on arrival matters twice over: the new dwarf may already be the best brewer in the fort, and may already be carrying the pick the fort is short of.

## 3. What the harness knows today

Verified against the repo, not assumed. Every gap in this section is a phase in section 10.

### 3.1 The actuator exists and is verified: `labor_toggle`

`labor_toggle(unit, labor, on)` enables or disables one labor on one citizen, by exact name or unit id. The Lua helper (`lua/act_labor.lua`) validates the labor name against `df.unit_labor` and fails as a precondition on an unknown name, on zero matching citizens, or on an ambiguous name. The Python action reads the citizen's labor list back from the observe `units` section and fails if the change did not stick. Live evidence: toggling CARPENTER on Deduk Stakudunib off and back on, and toggling MINE on a citizen by id. (ACTIONS.md, actions.py)

The labor names are the `df.unit_labor` enum names, all 84 of them in the live runtime fixture, including PLANT (farming), BREWER, COOK, HERBALIST, FISH, HUNT, and the eight HAUL_ labors. The farming plan's note that the exact labor enum name for farming was UNVERIFIED is resolved here: it is PLANT, present in `tests/fixtures/runtime-enums-0.47.05-r8.json`.

### 3.2 The observation exists, but only on the fresh path

`lua/units.lua` collects, per citizen: skills as (skill name, rating string) pairs from the soul, labors as a sorted list from `u.status.labors`, plus profession, job, idle state, mood, stress, counters, needs, and wounds. `lua/probe_unit.lua` returns the same citizen record for one dwarf by id, so `GET /v1/unit/<id>` carries skills and labors too. (units.lua, probe_unit.lua)

But the daemon's poller uses `units_lite.lua`, which collects only id, name, race, profession, position, idle, job, mood, stress, counters, and wound count. Skills and labors are deliberately absent from the lite collect. The snapshot is built from the poller's state, so the snapshot today carries no skill or labor information at all beyond profession counts. Any labor system must do a fresh full units collect for its decisions, the same way the diary path already does for fresh citizens. (observe.py, assembler.py)

### 3.3 The snapshot has no labor view

The snapshot's Units section lists exceptions (distressed, wounded, or dangerously needy, max 8) and counts by profession (top 8). The full citizen list is never pushed, by design: it grows linearly with population. There is no coverage table, no gap list, and no labor suggestion anywhere in the snapshot today. The planner has no labor domain either; its priorities are threat, needs, nobles, production, expansion, and its per-goal backoff applies to build and production goals, not to labor. (assembler.py, planner.py)

### 3.4 There is no autolabor-like system, and the docs claim otherwise

No autolabor-like system exists in Urist. A grep for `autolabor` across `src/` returns nothing. `TASK_DEFS` in daemon.py has exactly six composed tasks (brew, cook, make_bed, make_barrel, gather, farm). Yet PROTOCOL.md lists `autolabor` in the task list and states a policy rule, "many idlers lead to autolabor". That is doc and code drift, and it is the first thing phase 1 fixes: either the task exists or the doc stops claiming it does. (daemon.py, PROTOCOL.md)

### 3.5 Labor rules already decided elsewhere

Two sibling plans already fix labor rules this plan must not contradict:

- Farming: one dedicated planter (highest skill, other labors disabled), one backup, trainee plots, at most 1 planter per 100 tiles. The farming plan's labor rule exists because farming labor is fairly low priority in the game's job picker, so a planter with other jobs enabled will wander off. (FARMING_PLAN.md)
- Military: never draft a dwarf whose mining, woodcutting, or hunting labors cannot be cleared (Bug 1451), and never assign tool labors to a military dwarf. (MILITARY.md)

### 3.6 Nobles

Manager orders never worked in this harness without a manager noble appointed. The manager position id is 10, broker 12, bookkeeper 13, probed live. `manager_order_create` is verified (the order appears in the jobs section). What is not built is any rule protecting a noble's time: nothing today stops the planner from assigning the manager to hauling. (actions.py)

## 4. Why not DFHack autolabor or labormanager

Both plugins ship with DFHack 0.47.05-r8 and are present in this install (`hack/plugins/autolabor.plug.so`, `labormanager.plug.so`), with full docs in `hack/docs/docs/tools/`. They are the reference design for this plan. They are not the implementation. The reasons are specific to what Urist is:

- Both override any manual labor change while enabled, including changes made through other tools. The harness could not verify or explain a labor state it did not set, which breaks the live-verification discipline and the "harness is teacher" rule. A labor assignment the harness cannot account for is a labor assignment it cannot defend to the agent.
- Both persist across save and reload until explicitly disabled. A plugin left enabled would keep managing labors in a fort the harness is not currently driving, and would fight the harness the next time it starts.
- Both are opaque to the agent. The harness must feed the agent a coverage table with reasons, not a black box that silently reassigns dwarves between ticks.

What is borrowed from each, with the source named:

From autolabor: keep as many dwarves busy as possible while letting dwarves specialize; assign labors in proportion to the jobs waiting; handle tool labors to minimize churn; leave military and burrow dwarves untouched; rank candidates by skill and deprioritize masters of one skill for other skills; never assign hunting without a butchery or fishing without a fishery; rarely assign nobles with diplomat or merchant duties, never the chief medical dwarf, less often the bookkeeper and manager; default to 1 to 200 dwarves per labor (2 to 200 for mining) and a 33 percent hauler share as the starting point, to be tuned live, not taken as gospel.

From labormanager: get jobs done as fast as possible rather than keeping everyone busy; sort needed labors by adjusted priority and assign the best fit dwarf first; always keep at least one dwarf on each hauling labor and on cleaning, because those jobs cannot be reliably detected from the job list; give idle dwarves hauling, lever pulling, and cleaning; reserve healthcare providers automatically when there are wounded; exclude dwarves who cannot work (child, military, wounded, handless, asleep, in a meeting) entirely; avoid assigning females with children to outside jobs; favor tool-carriers for outside jobs; minimize re-equipping.

The Urist design is autolabor's proportions plus labormanager's priority loop, implemented in Python, driven through `labor_toggle`, verified by read-back after every change, and recorded in the journal so the agent can see what changed and why. The DFHack plugins stay off.

## 5. The assignment system

### 5.1 The matching rule

For each labor that needs coverage, the harness ranks every available citizen by:

1. Skill rating in the labor's skill, highest first. Rating is the whole signal at first; experience points within a rating are not observable yet (see section 12).
2. Attribute fit, once attributes are collected. About 500 points in a primary attribute equals one skill level, so attributes only break ties between adjacent ratings, never override a full rating gap. (Skill)
3. Matching item or material preference, once preferences are collected. A match is worth about four skill levels on average, so a Dabbling dwarf who loves oak can outrank an Adequate dwarf who does not care, for oak work specifically. (Skill)
4. Current load: how many labors the dwarf already holds, and whether they are currently idle or mid-job. A dwarf holding one labor beats a dwarf holding five.
5. Exclusions, which are absolute: military dwarves are never assigned tool labors; wounded dwarves are never assigned labors they cannot physically do; dwarves in a strange mood are never touched; the chief medical dwarf is never assigned non-medical labors; children are never assigned until the rule is verified (see section 12).

The output of the match is not a silent reassignment. It is a named option: "Enable COOK on Zulban: Adequate cook, idle, holds no other skilled labor." The agent picks; the harness executes through `labor_toggle` and verifies by read-back.

### 5.2 Coverage: the labors that must never go empty

Coverage is computed from three sources: the live job list (what is waiting), the stock trends (what is running out), and the floors below (what must always have someone). A labor is in one of three states: covered (floor met and no waiting jobs starving), thin (floor met but waiting jobs are aging), or gap (floor unmet).

Proposed floors for a 7-citizen fort, to be tuned live in phase 7, not taken as wiki fact:

| Labor | Floor | Why |
| --- | --- | --- |
| BREWER | 1 | Drink is survival; the brew task needs someone who can brew |
| PLANT | 1 dedicated + 1 backup | Farming plan rule; planter labor is low priority in the game picker |
| COOK | 1 | Food is survival; cook only above the seed and drink reserve |
| MINE | 2 | Digging is the fort's growth; one miner stalls on a single pick |
| CUTWOOD | 1 | Wood feeds beds, barrels, and fuel |
| CARPENTER | 1 | Beds and barrels are the fort's first production |
| MASON | 1 | Stone is the fort's building material |
| HAUL_* (pool) | 2 | The hauler pool, section 5.4 |
| DIAGNOSE + medical | 1 (chief medical dwarf) | Reserved, never assigned other labors |
| HERBALIST | 0, rises to 1 when gathering | Gather task only |
| FISH / HUNT | 0, rises to 1 when the fishing or hunting plan activates | Never assigned without a fishery or butchery |

Floors scale with population: the hauler pool grows, and each production labor gains a second dwarf when its waiting job list stays non-empty across two ticks. A floor is a minimum, not a target; the harness never assigns a dwarf to a labor with no waiting work just to fill a number.

### 5.3 Balancing: specialization against flexibility

The end state is the wiki's: each dwarf holds a very limited number of labors, and the skilled ones hold the fewest. The path there is gradual, because a 7-dwarf fort cannot afford seven specialists on day one. The rule:

- A dwarf's primary labor is the one they are best at. It is never removed to make room for a lesser labor.
- A dwarf holds at most one skilled production labor plus hauling, until the fort passes 20 citizens. After that, skilled dwarves drop hauling entirely and the hauler pool takes it.
- Every critical labor has a named backup, so one death, mood, or injury does not empty it. The backup holds the labor enabled but is not the first pick while the primary lives.
- A dwarf who has not practiced a craft for too long gets a minor negative feeling, so the harness rotates the backup into real work sometimes instead of leaving them as a paper backup. That rotation is also how the backup's skill stays unrusted.

### 5.4 The hauling pool

Hauling is the default filler and the classic failure mode. The rules:

- The hauler pool is drawn from the lowest-skill citizens first, the wiki's peasant rule. A skilled brewer never hauls while a hauler is idle.
- The pool starts at about a third of the workforce, DFHack autolabor's default, and is tuned by observation: if skilled dwarves are still picking up hauling jobs, the pool is too small; if haulers stand idle while production waits, it is too big.
- Idle dwarves get hauling, lever pulling, and cleaning first, per labormanager. Idleness is the trigger, not a schedule.
- Hauling never starves skilled work: when a production job waits and its labor holder is hauling, the harness names the conflict in the snapshot instead of silently letting the job age. That is the coverage "thin" state in section 5.2.

### 5.5 Tool-labor churn protection

Mining, woodcutting, and hunting each need a tool, and switching one silently drops the other. The harness therefore treats tool-labor changes as expensive: it never toggles a tool labor to chase a single job, it never assigns two tool labors to one dwarf, and it never reassigns a tool labor while the dwarf is mid-job with that tool. A dwarf who holds MINE keeps MINE until the fort genuinely needs a woodcutter more, and the change is recorded in the journal with the reason. (Labor, autolabor docs)

## 6. Training

Skill is gained by doing the work. There is no shortcut: a dwarf becomes a better brewer by brewing. The harness's training job is to make sure the doing happens in the right order, and that skill does not rot away unused.

### 6.1 Gain

Every completed job gives experience in its skill. The cost per level rises with level, so the first few levels are cheap and the last ones are expensive. That shapes the training rule: getting a dwarf from Dabbling to Adequate is fast and almost always worth it; pushing Adequate to Competent is worth it for the fort's bottleneck labors; chasing Master is a luxury for a fort that already eats and drinks. (Skill)

Farming, gathering, and fishing gain differently: skill there decides yield quantity, not quality, and the return caps in effect at Legendary+10. A Legendary+5 grower is not meaningfully better than a Legendary grower for yield, so training growers past Legendary is wasted effort. (Skill)

### 6.2 The rust watch

Rust is the silent skill killer. A skill unused long enough is labeled rusty, then very rusty, then loses experience permanently, and skills above High Master rust invisibly until they are demoted. The harness cannot read rust directly from the collect today, and the store does not keep skill samples either: `unit_history` records job, counters, wounds, needs, and relations per dwarf per day, but no skills column exists. So the rust watch is built in two steps. Phase 1 adds a `skills_json` column to `unit_history` and records each dwarf's skill ratings on the daily sample, which gives the watch a series to read. The watch then flags a skill whose rating has not moved in a long time on a dwarf who has not been observed doing that job, and the snapshot names it: "Ral's masonry has not advanced in 40 days; give him a stone job or lose it." The exact staleness threshold is tuned live; the watch itself is phase 5 work. (Skill, store.py)

### 6.3 Apprentice pairing

When the fort needs a second brewer, cook, or planter, it does not wait for a skilled migrant. It pairs the skilled dwarf with an unskilled one: the apprentice holds the same labor enabled, the master keeps priority by skill ranking, and the apprentice takes the overflow jobs. The farming plan already uses this shape with trainee plots. The pairing is recorded in the journal, and the apprentice's progress is visible in the next skill sample. A pairing ends when the apprentice reaches Adequate, or when the fort no longer needs the second dwarf. (FARMING_PLAN.md)

### 6.4 Rotation

Rotation serves two purposes: it keeps backups' skills warm, and it keeps dwarves from the minor negative feeling of never practicing a craft. The rule is narrow: rotate the backup into real work for one job in three, never by swapping the primary out mid-season. Rotation is a suggestion the agent approves, never a silent background change, because a rotation that lands during a siege or a brewing emergency is worse than a rusty backup.

### 6.5 Demonstrations

Skills can be taught in a demonstration through a guildhall or military training. Whether the harness can observe or drive a guildhall demonstration in 0.47.05-r8 is UNVERIFIED (section 12). If it can, demonstrations become the fast path for apprentice training. If it cannot, training stays job-based and the doc says so.

## 7. Labor changes on events

Labor is not set once. It is re-planned whenever the workforce changes. The events that trigger a re-plan, and what the re-plan does:

- **Migrant arrival.** New arrivals walk in with labors already assigned and sometimes with Legendary skill and matching equipment. The harness reads every new citizen's skills on the next fresh collect, ranks them against the current coverage, and proposes assignments within one tick. A migrant who is the best brewer in the fort becomes the brewer; a migrant with no skill becomes a hauler. The arrival itself is already an attention event; the labor proposal rides on it. (Immigration, events.py)
- **Death.** The dead dwarf's labors are checked against coverage immediately. If a floor drops below its minimum, the named backup is promoted and the gap is named in the snapshot with the fix. The death diagnosis already records the cause; the labor re-plan records the consequence.
- **Injury and wounds.** A wounded dwarf may not be able to do some labors, and which ones is not established from the collect today (section 12). Until it is, the rule is conservative: a wounded dwarf keeps only labors that do not need the wounded body part, judged by the wound's parts count, and the harness never assigns new labors to a wounded dwarf. The chief medical dwarf is reserved automatically when there are wounded, per labormanager.
- **Strange mood.** A dwarf in a mood claims a workshop and is unavailable for any labor until the artifact is done, and if they fail they are permanently unable to work. The harness never touches a mood dwarf's labors, never counts them toward coverage, and treats their workshop as blocked. The mood itself is a diary and attention matter; the labor consequence is a coverage gap with a named fix. (Labor)
- **Military muster.** Drafting clears a dwarf's tool labors (Bug 1451) and removes them from the labor pool entirely while on duty. The harness must not count a mustered dwarf toward any floor, and must restore their labors when they stand down, or the fort loses a miner to a squad that no longer exists. (MILITARY.md)
- **Noble appointment.** Appointing a manager, broker, or bookkeeper changes that dwarf's labor rules: the manager needs free time for order validation, the broker needs time for trade, and none of them should hold high-demand labors. Appointment triggers a re-plan of that dwarf's labors the same tick. (Manager)
- **Workshop loss.** If the only still is destroyed, the brewer's labor is not the problem and reassigning the brewer fixes nothing. The labor re-plan checks the facility first: a labor with no workshop to serve is paused, not reassigned, and the gap is reported as a building problem, not a labor problem.

## 8. Noble and manager labors

Nobles are labor assignments with special rules, and getting them wrong costs the fort its production pipeline.

- **Manager.** Organizer skill, fed by analytical ability, creativity, and social awareness. Needs an office (meager, with a chair) and free time: at 20 citizens, work orders are not performed until the manager validates them. Never assign the manager to high-demand labors. The manager is picked by organizer skill first, and if nobody has it, the expedition leader is the reasonable fallback. (Manager, Labor)
- **Broker.** Appraisal skill. Needed for trade; the broker's availability gates the trade agreement and the trading itself. The trading plan's broker appointment is UNVERIFIED live; when it lands, the broker gets the same time protection as the manager. (TRADING.md)
- **Bookkeeper.** Record keeping skill. Assigned less often to other labors, per autolabor's rule, because accurate records feed every decision the harness makes.
- **Chief medical dwarf.** Never assigned non-medical labors. This is autolabor's rule and it is absolute: the dwarf who diagnoses and treats must be free when someone is hurt.

Appointment itself is a separate route (the noble-appointment investigation in the military plan covers the mechanism). This plan only states the labor consequences of appointment, and requires that every appointment trigger the re-plan in section 7.

## 9. What the AI sees

The whole point of the system is that the agent never reasons about the labor matrix. The harness does the reasoning and feeds the agent a short, ranked, plain-words view. The shape:

### 9.1 The snapshot labor section

A compact block in the snapshot, next to the Units section, bounded the same way (counts, exceptions, diffs only, never the full citizen list):

```
Labor: 7 citizens, 1 idle.
  Coverage: BREWER 1/1 (Olon), PLANT 1/1 (Ral) + backup 1 (Zulban),
    COOK 0/1 GAP, MINE 2/2, CUTWOOD 1/1, CARPENTER 1/1, MASON 1/1, HAUL 2/2.
  Gaps: no cook. Fix: enable COOK on Zulban (Adequate cook, idle,
    holds no other skilled labor).
  Suggested: enable COOK on Zulban; disable HAUL_FOOD on Olon
    (brewer pulled into hauling).
  Rust watch: Ral's masonry has not advanced in 40 days.
```

The rules for this block: coverage is a table, not a dump; a gap always carries its fix; suggestions are at most three, each one line with the reason in game terms; the rust watch is at most three entries; nothing in the block grows linearly with population.

### 9.2 The detail routes

- `GET /v1/labor`: the full view, on demand. Per-dwarf table (name, profession, top three skills with ratings, labors held, current job, idle), coverage per labor with the dwarves holding it, the rust watch list, and the recent labor changes from the journal. This is the route the agent queries when the snapshot names a gap it wants to understand.
- `GET /v1/unit/<id>`: already returns the citizen record with skills and labors. No change needed, but the labor doc records that this is where a single dwarf's detail lives.
- The journal records every labor change with the reason, so a later run can see why Zulban stopped hauling and started cooking.

### 9.3 What the agent decides, and what it does not

The agent decides between the named options: which suggested reassignment to take, whether to approve a rotation, whether to accept a migrant's proposed assignment. It never decides the matching rule, the floors, or the hauler share. Those are harness policy, versioned in this doc, and changed only by editing the doc and the code together. If the agent asks for labor information the snapshot does not carry, the answer is a query to `/v1/labor`, never a dump of the matrix into the prompt.

## 10. Implementation phases

Each phase ends with a live verification bar. A phase is not done until the bar is met against the real game.

### Phase 1: Fix the drift, and make labor observable

- Remove or implement the `autolabor` task named in PROTOCOL.md. If the task does not exist, the doc stops claiming it. If it is implemented, it is the phase 3 engine, not a DFHack plugin call.
- Add a labor observation step to the daemon: a fresh full units collect on a schedule the labor system owns (not the lite poller), so skill and labor data is never read from the lite cache. Record skill ratings into `unit_history` on the daily sample so the rust watch has a series to read.
- Live bar: `GET /v1/units?fresh=1` returns skills and labors for every citizen; PROTOCOL.md matches the code; the skill sample series grows by one entry per in-game day.

### Phase 2: Coverage and the snapshot section

- Compute coverage from the fresh collect, the live job list, and the floors in section 5.2. Emit the snapshot labor section in the shape of section 9.1, with gaps carrying fixes and at most three suggestions.
- Add `GET /v1/labor` with the full per-dwarf table, coverage per labor, rust watch list, and recent labor changes.
- Live bar: on the main fort, the coverage table matches a hand-check against the game (every labor's holder named correctly); a real gap (for example no cook) is named with the correct fix; the snapshot stays within its token discipline.

### Phase 3: The assignment engine

- Implement the matching rule (section 5.1), the floors (section 5.2), the hauler pool (section 5.4), and tool-labor churn protection (section 5.5) as daemon-side code. Suggestions flow to the agent; approved changes execute through `labor_toggle` with read-back verification and a journal entry with the reason.
- Live bar: a suggested reassignment executes, the read-back confirms it, and the newly assigned dwarf is observed doing the new job within the same run; a hauling conflict (skilled dwarf hauling while production waits) is named in the snapshot before the fix and gone after it.

### Phase 4: Event-driven re-planning

- Re-plan on migrant arrival, death, injury, strange mood, military muster and stand-down, noble appointment, and workshop loss, per section 7. Each re-plan produces at most three suggestions and a journal entry.
- Live bar: on the scratch fort, a migrant arrival triggers a re-plan within one tick and the new dwarf's best skill is proposed for its matching labor; a muster removes the drafted dwarf from every floor and a stand-down restores their labors.

### Phase 5: Training and the rust watch

- Apprentice pairing (section 6.3) and rotation (section 6.4) as suggestions. The rust watch (section 6.2) from the skill sample series, with the staleness threshold tuned from live data.
- Live bar: an apprentice's skill rating advances across samples after pairing; a genuinely unused skill appears on the rust watch with a true staleness figure.

### Phase 6: Noble labor rules

- Time protection for manager, broker, bookkeeper, and chief medical dwarf: the assignment engine never proposes a high-demand labor for them, and appointment triggers an immediate re-plan of that dwarf's labors.
- Live bar: the manager holds no production labor after appointment, and manager orders validate and flow while the manager is protected.

### Phase 7: Tuning from live runs

- Tune the floors, the hauler share, and the rust threshold from live M1 runs. Feed the results into the scoring system's competence dimension (idle ticks and failed actions already count there; labor coverage becomes part of the evidence).
- Live bar: two live M1 days with labor coverage green throughout, zero skilled-dwarf-hauling conflicts, and the tuning values recorded in this doc with the run ids that justify them.

## 11. Refusals

- Never enable DFHack autolabor or labormanager. The harness implements its own assignment policy and verifies every change.
- Never assign a tool labor to a military dwarf, and never draft a dwarf whose tool labors cannot be cleared.
- Never reassign a dwarf mid-job to chase a single waiting job. Tool-labor changes are expensive and recorded.
- Never touch a dwarf in a strange mood, and never count them toward coverage.
- Never assign a labor to a child until the rule is verified live (section 12).
- Never assign a new labor to a wounded dwarf until the eligibility rule is verified live.
- Never assign the only skilled brewer, planter, or cook to hauling while a hauler exists or could exist.
- Never claim a skill level, a labor, or a coverage state the fresh collect did not show. The lite poller has no skills and no labors.
- Never reassign on stale data. Labor decisions are made from a fresh full units collect, never from the poller's lite state.
- Never let the labor system silently change labors. Every change goes through `labor_toggle` with read-back, and is recorded in the journal with the reason.

## 12. Open questions

All marked UNVERIFIED until proven live. Each names the phase that must prove it.

1. **Children and labors.** Whether children appear in `u.status.labors` and can hold labors at all. Phase 1 must read it live. Until then, children are excluded from assignment.
2. **Attributes in the collect.** Whether body and soul attributes are readable in the citizen collect (the Lua path is not yet written) and whether to add them to the citizen record for the matching rule. Phase 1.
3. **Preferences in the collect.** Whether item and material preferences are readable, for the matching bonus worth about four skill levels. Phase 1.
4. **Skill experience, not just rating.** Whether raw experience points per skill are readable, for rust-watch precision instead of rating movement. Phase 5.
5. **Guildhall demonstrations.** Whether a demonstration can be observed or driven in 0.47.05-r8, and whether it is a viable fast path for apprentice training. Phase 5.
6. **Wounded-dwarf eligibility.** Which labors a wounded dwarf can still do, given the wound's parts. The collect has wounds; the eligibility rule does not exist yet. Phase 4.
7. **Hauler share tuning.** 33 percent is DFHack autolabor's default, not a verified optimum for a 7-dwarf fort. Phase 7 tunes it from live runs.
8. **Manager organizer skill readability.** Whether the organizer skill rating is readable for ranking manager candidates, or whether appointment must rank on attributes alone. Phase 6.
9. **Labor changes during a strange mood.** Whether the game even permits toggling labors on a mood dwarf. The plan forbids it regardless; the question is only whether the guard is needed or the game enforces it. Phase 4.
10. **The farming plan's labor enum note, resolved.** FARMING_PLAN.md marked the exact labor enum name for farming as UNVERIFIED. It is resolved here: PLANT is present in the live runtime enum fixture (`tests/fixtures/runtime-enums-0.47.05-r8.json`, 84 labors). The farming plan should be updated to say so when it is next touched.

## 13. Sources

Wiki pages, read from the local export with `python3 ~/workspace/df-wiki-export/dfq.py`:

- Labor (labor): labor vs skill, work details, specialization, tool exclusivity, hauling, manager caveats, specialization feelings.
- Skill (skill): level names and XP costs, quality formula, legacy yield check, status penalties, rust, professions, demonstrations.
- Attribute (attribute): body and soul attributes, dwarven medians, attribute and skill linkage.
- Immigration (immigration): wave timing and sizes, skill influence, equipment on arrival, population cap, strange mood threshold.
- Manager (manager): organizer skill, office requirement, validation at 20 citizens, work orders.
- Labor token (labor-token): the 84 labor tokens.
- Skill token (skill-token): the 138 skill tokens.

DFHack 0.47.05-r8 plugin docs, read from the local install:

- `third_party/df_47_05/hack/docs/docs/tools/autolabor.txt`: proportional assignment, skill preference order, hauler share, noble rules, persistence.
- `third_party/df_47_05/hack/docs/docs/tools/labormanager.txt`: priority-halving loop, fitness algorithm, always-on hauling and cleaning, medical reservation, pause-on-error.
- `third_party/df_47_05/hack/docs/docs/tools/autolabor-artisans.txt`: exists, not read; a differently tuned autolabor setup, for reference only.

Harness state, verified against the repo:

- `src/dfagent_harness/actions.py` (`labor_toggle`, noble position ids, `manager_order_create`), `src/dfagent_harness/lua/act_labor.lua`, `src/dfagent_harness/lua/units.lua`, `src/dfagent_harness/lua/units_lite.lua`, `src/dfagent_harness/lua/probe_unit.lua`, `src/dfagent_harness/observe.py`, `src/dfagent_harness/assembler.py`, `src/dfagent_harness/planner.py`, `src/dfagent_harness/daemon.py` (`TASK_DEFS`, `run_task`), `docs/ACTIONS.md`, `docs/PROTOCOL.md`, `docs/FARMING_PLAN.md` (section 11 labor rules), `docs/MILITARY.md` (Bug 1451), `docs/TRADING.md` (broker appointment UNVERIFIED), `tests/fixtures/runtime-enums-0.47.05-r8.json` (84 unit labors, 138 job skills).
