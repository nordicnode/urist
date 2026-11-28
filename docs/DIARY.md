# DIARY.md: the fort diary, what it is, and the bar it has to meet

The diary is one entry per in-game day, written in the first person
as the fort's overseer. It is the fort's own record: what the dwarves
did, what happened to them, how they relate, what the overseer
decided. It is not a report on the numbers. The ledger line below
each entry already carries the numbers.

## How an entry is written

The feed builder (`build_diary_feed` in `src/dfagent_harness/diary.py`)
curates the day's facts: the ledger, one structured record per dwarf,
the day's events from the bus event log and the raw watch log, the
open threads, the last few entries for continuity. The prompt renderer
(`diary_prompt`) turns those facts into plain words with a coverage
block stating what record exists for the day. The model writes the
entry from that prompt (`write_ai_entry`), or the coordinator writes
it directly from the same prompt when Free Pi is down (Mikey's rule,
2026-11-27: an outage changes who writes it, not the standard it has
to meet). `scripts/rebuild_diary.py --ai` rebuilds entries from the
same feed construction. The validator
(`hidden_files/validate_diary.py` in the goal workspace) checks every
checkable number and name against the feed.

## The gate

No diary entry lands without both: the validator passing on all
entries, and an independent re-check judging the entries under the
bars below. The validator passing means no checkable number is wrong,
not that the entry is right. The re-check is a fresh agent with the
feeds and prompts, not the author. A diary commit follows the
pre-push self-review gate like any other push.

## The event-day bar

A day with events in the record is judged on two bars:

(a) Dwarf-focus. The entry is about the dwarves: what they did, what
happened to them, their moods, stress, wounds, needs, and how they
relate. It leads with a dwarf doing something, or something happening
to a dwarf, or a decision the overseer made and what came of it.
Never lead with a stock, a count, or the ledger. Numbers appear only
as the trace of an event.

(b) Events, not stats. The entry is written from what happened today,
not from the ledger. A count without a name and a deed behind it is
not a sentence. The ledger and the counts are background: they are
there so the writer can check a number, not so they can narrate them.

## The eventless-day bar (relaxed, Mikey's ruling 2026-11-27 ~21:18 PT)

"If there's nothing happening, there's nothing happening. We don't
expect the AI to invent something."

A day with no event in any source is NOT judged by the event bar, and
it is NOT required to have an event on the day. An eventless-day
entry passes if it honestly says nothing happened, or reports only
the dated record: no invented events, no false dating, facts and
voice clean. The "must have an event on the day" requirement is
dropped. What a quiet entry looks like:

1. Facts and voice pass, the same standard as any entry.
2. Every claim is dated to the record it comes from. Ledger changes
are stated as intervals with both endpoint dates, never "today"
without an event. A fact from a dated record carries its date in
the same sentence.
3. Dwarf-focus is unchanged: the entry leads with named dwarves, and
a count appears only inside a sentence about named dwarves.
4. No tally disguised as a story: the short two-or-three-line shape,
no padding to look eventful. A quiet day is two or three lines, then
stop.
5. No invented events, causation, or personification. Coverage is
stated honestly: "no bus record exists for this day", not "live and
recorded nothing".
6. Silence is stated once, in fresh words, not as a refrain. The
usual form is inside a fact sentence ("on the 13th, the last day the
record covers"), never as a sentence about what the writer does or
does not know.
7. A same-day first sighting counts as the day's news. A prior-day
sighting reported a day late is not.

The pass conditions are the honesty ones: no invention, no false
dating, facts and voice clean. The shape points (3, 4) are how a
quiet entry is written, not a second event bar: a short honest
record passes even if the day had nothing in it.

## Coverage: what the record says

The prompt's coverage block states, per source, what exists for the
day. The bus event log and the raw watch log end on different days
(the bus runs to 125-07-08; the watch log ends 125-06-14), and the
per-dwarf samples often end days before the day itself. No rows in a
day is stated as "no bus record exists for this day": the bus is
lossy (on 06-12 it captured 1 of 2 Eat completions), so "recorded
nothing" never proves nothing happened, and "live" means rows around
the day. A day with no record in any source gets the short form:
two or three lines from the decisions and the last dated record,
then stop.

## Names: a name is a detection, not an arrival

A dwarf's name is used only from a record at or before the day. A
name first recorded after the day must not name anything on that day.
The migrants arrived 06-02/06-03, but their names were first recorded
at tick 201600, on the 1st of Limestone. The old 06-12 entry named
Litast Aknûnònul eating on the 12th, when the record had him only as
an unnamed migrant: that is the named bad example, and the prompt
rules carry it. The feed gates file-derived names on
`first_seen_tick` (`read_day_events` resolve), and the Store's names
come only from full samples at or before the day end. A completion
names its worker by id, not by name: name a dwarf in an event only
when the feed names them for that event. Never invent a name for an
unnamed migrant.

## Stocks: intervals, never same-day events

A ledger interval is not a same-day event. The 06-20 ledger says
drink 6 -> 0, but no Drink2 completion is recorded 06-15 to 06-20,
and the stock_low event dates the zero to 06-21 (tick 192076). The
CRISIS line therefore states the interval, never the day: "The last
of the drink ran out during this record (6 at the start, none at the
end)." The event-dated form belongs in the prompt's event list, where
the stock_low event itself carries the date ("Ran out: the last of
the drink ran out today" renders only when the event falls in the
day). The same rule covers every ledger change: both endpoint dates
ride with the fact, and the start value is dated to where it came
from (the 06-20 ledger's 6 is the previous entry's end, the 12th's
number, not the 13th's).

## First sightings, and what is not ordered

A wound first recorded on a date was not necessarily taken that day,
and not necessarily from before it: first sighting is not the date of
injury. Write "first recorded", never "taken" or "from before", for a
wound's first sighting. Never say one dwarf has been thirsty longer
than another: the feed carries no since-dates for thirst, and the
thirst counters cannot order two dwarves. Ral and Olon both first
crossed the line on the same day, 04-01. Say who is thirsty today;
never rank them by duration.

## Voice

Plain, concrete, dry. Short sentences and long ones mixed. A detail
beats a flourish. Dry humour is welcome when the facts earn it;
archaic phrasing, elegy, and purple prose are not. Write the way a
tired overseer would write at the end of the day: direct, specific,
a little weary, never reaching for effect. No em dashes. Never close
with a summary of the day, a vow about tomorrow, an aphorism, or an
aside about the writing. Never end an entry on the drink-zero fact:
the ledger line already says it.

## Files

- The live diary: `~/.config/df-agent-harness/diary.md` (and
`diary.html`, regenerated from it).
- Feed and prompt: `src/dfagent_harness/diary.py`
(`build_diary_feed`, `diary_prompt`, `write_ai_entry`,
`_stock_crisis_lines`, `_coverage_lines`); events:
`src/dfagent_harness/day_events.py` (`read_day_events`).
- Rebuild: `scripts/rebuild_diary.py` (`--ai` rewrites from the
same feed construction; `--dry-run` previews the feed).
- Validator: `hidden_files/validate_diary.py` in the goal workspace
(mirrors the rebuild's feed construction, strips the ledger line
first).
- Re-check verdicts: `hidden_files/diary-recheck-N-prompt-*.md`
in the goal workspace.
