-- units_lite.lua — cheap citizen/hostile summary for the event poller.
-- Same shape as units.lua's "units" section but only the fields the
-- diff detector reads: id, name, race, profession, pos, idle, job,
-- mood_name, stress, counters, wound_count. Needs, skills, labors,
-- sex, age and goals are omitted — the full units.lua section has
-- them and the poller only needs the full dump when the daemon asks
-- for it. (Full units.lua costs ~0.9 s; this one exists to make the
-- 2 s fast poll affordable — see docs/EVENTS.md for measured costs.)
-- Prints one JSON object: {"ok": true, "section": "units", ...}
local ok, err = pcall(function()
  local citizens = dfh_arr()
  local hostiles = dfh_arr()
  for _, u in ipairs(df.global.world.units.active) do
    if dfhack.units.isOpposedToLife(u)
      or dfh_try(function() return u.flags1.active_invader end, false) then
      hostiles[#hostiles+1] = {
        id = u.id,
        name = dfhack.TranslateName(dfhack.units.getVisibleName(u)),
        race = dfhack.units.getRaceName(u),
        pos = dfh_arr({u.pos.x, u.pos.y, u.pos.z}),
      }
    end
    if dfhack.units.isCitizen(u) then
      local soul = u.status.current_soul
      local stress_level, stress_category = nil, nil
      if soul then
        stress_level = soul.personality.stress_level
        stress_category = dfhack.units.getStressCategory(u)
      end
      local wounds = 0
      for _, _ in ipairs(u.body.wounds) do wounds = wounds + 1 end
      local job = nil
      local cur = u.job.current_job
      if cur then
        job = {
          type = tostring(df.job_type[cur.job_type]),
          id = cur.id,
          pos = dfh_arr({cur.pos.x, cur.pos.y, cur.pos.z}),
        }
      end
      local mood = u.mood
      citizens[#citizens+1] = {
        id = u.id,
        name = dfhack.TranslateName(dfhack.units.getVisibleName(u)),
        race = dfhack.units.getRaceName(u),
        profession = dfhack.units.getProfessionName(u),
        pos = dfh_arr({u.pos.x, u.pos.y, u.pos.z}),
        idle = cur == nil,
        job = job,
        mood = mood,
        mood_name = mood == -1 and 'none' or tostring(df.mood_type[mood]),
        stress = {level = stress_level, category = stress_category},
        counters = {
          hunger = u.counters2.hunger_timer,
          thirst = u.counters2.thirst_timer,
          sleepiness = u.counters2.sleepiness_timer,
        },
        wound_count = wounds,
      }
    end
  end
  result = {
    ok = true, section = 'units',
    units = {
    citizens = citizens,
    citizen_count = #citizens,
    hostiles = hostiles,
    hostile_count = #hostiles,
    },
  }
end)
if not ok then
  result = {ok = false, section = 'units', error = tostring(err)}
end
dfh_print(result)
