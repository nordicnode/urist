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
  local wildlife = dfh_arr()
  local visitors = dfh_arr()
  local livestock = dfh_arr()
  local function compact(u, kind, role)
    return {
      id = u.id,
      name = dfhack.TranslateName(dfhack.units.getVisibleName(u)),
      race = dfhack.units.getRaceName(u),
      pos = dfh_arr({u.pos.x, u.pos.y, u.pos.z}),
      kind = kind, role = role,
    }
  end
  local function visitor_role(u)
    if dfh_try(function() return u.flags1.merchant end, false) then
      return 'merchant', 'trading'
    end
    if dfh_try(function() return u.flags1.diplomat end, false) then
      return 'diplomat', 'diplomacy'
    end
    local prof = dfhack.units.getProfessionName(u)
    if prof == 'Performer' or prof == 'Bard' then
      return 'performer', 'performing'
    end
    if prof == 'Scholar' then return 'scholar', 'studying' end
    if prof == 'Mercenary' then return 'mercenary', 'mercenary work' end
    return 'visitor', 'visiting'
  end
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
    -- Neither citizen nor hostile: wildlife, visitor, or livestock.
    local is_host = dfhack.units.isOpposedToLife(u)
      or dfh_try(function() return u.flags1.active_invader end, false)
    if not is_host and not dfhack.units.isCitizen(u) then
      local is_an = dfh_try(
        function() return dfhack.units.isAnimal(u) end, false)
      if is_an then
        if dfh_try(function() return dfhack.units.isTame(u) end,
                   false) then
          livestock[#livestock+1] = compact(u, 'livestock', 'pet')
        else
          wildlife[#wildlife+1] = compact(u, 'wildlife', 'wild')
        end
      else
        local role, purpose = visitor_role(u)
        local rec = compact(u, 'visitor', role)
        rec.purpose = purpose
        visitors[#visitors+1] = rec
      end
    end
  end
  local total = #df.global.world.units.active
  result = {
    ok = true, section = 'units',
    units = {
    citizens = citizens,
    citizen_count = #citizens,
    hostiles = hostiles,
    hostile_count = #hostiles,
    wildlife = wildlife,
    wildlife_count = #wildlife,
    visitors = visitors,
    visitor_count = #visitors,
    livestock = livestock,
    livestock_count = #livestock,
    total_active_units = total,
    reconciled = (#citizens + #hostiles + #wildlife + #visitors
                  + #livestock) == total,
    },
  }
end)
if not ok then
  result = {ok = false, section = 'units', error = tostring(err)}
end
dfh_print(result)
