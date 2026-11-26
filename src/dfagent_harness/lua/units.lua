-- units.lua — every citizen in full + hostile units.
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
      local needs = dfh_arr()
      local stress_level, stress_category = nil, nil
      if soul then
        stress_level = soul.personality.stress_level
        stress_category = dfhack.units.getStressCategory(u)
        for _, n in ipairs(soul.personality.needs) do
          needs[#needs+1] = {
            need = tostring(df.need_type[n.id]),
            level = n.need_level,
            focus = n.focus_level,
          }
        end
      end
      local skills = dfh_arr()
      if soul then
        for _, s in ipairs(soul.skills) do
          if s.rating > 0 then
            skills[#skills+1] = {
              skill = tostring(df.job_skill[s.id]),
              rating = tostring(df.skill_rating[s.rating]),
              rating_num = s.rating,
              experience = s.experience,
            }
          end
        end
      end
      local labors = dfh_arr()
      for k, v in pairs(u.status.labors) do
        if v then labors[#labors+1] = tostring(k) end
      end
      table.sort(labors)
      local wounds = dfh_arr()
      for _, w in ipairs(u.body.wounds) do
        wounds[#wounds+1] = {id = w.id, parts = #w.parts}
      end
      local job = nil
      local cur = u.job.current_job
      if cur then
        job = {
          type = tostring(df.job_type[cur.job_type]),
          id = cur.id,
          pos = dfh_arr({cur.pos.x, cur.pos.y, cur.pos.z}),
        }
      end
      local goal = nil
      local gt = dfh_try(function() return dfhack.units.getGoalType(u, 0) end, nil)
      if gt ~= nil then
        goal = {
          type = gt,
          name = dfh_try(function() return dfhack.units.getGoalName(u, 0) end, nil),
        }
      end
      local mood = u.mood
      citizens[#citizens+1] = {
        id = u.id,
        name = dfhack.TranslateName(dfhack.units.getVisibleName(u)),
        race = dfhack.units.getRaceName(u),
        profession = dfhack.units.getProfessionName(u),
        profession_id = u.profession,
        sex = u.sex,
        age = dfhack.units.getAge(u),
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
        needs = needs,
        skills = skills,
        labors = labors,
        wounds = wounds,
        wound_count = #wounds,
        goal = goal,
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
