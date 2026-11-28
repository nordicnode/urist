-- units.lua — every citizen in full + hostile units + the other
-- classes (wildlife, visitors, livestock) as compact records.
-- World-model design §4. All classes come from the same iteration
-- over df.global.world.units.active; the fix is additive (new
-- lists), not a new scan. The reconciliation invariant: citizens +
-- hostiles + wildlife + visitors + livestock = total_active_units
-- (no unit is dropped silently).
-- Prints one JSON object: {"ok": true, "section": "units", ...}
local ok, err = pcall(function()
  local citizens = dfh_arr()
  local hostiles = dfh_arr()
  local wildlife = dfh_arr()
  local visitors = dfh_arr()
  local livestock = dfh_arr()
  local citizen_pos = dfh_arr()
  -- Compact record for a non-citizen unit (design §4.1): five
  -- fields, ~15 tokens each.
  local function compact(u, kind, role)
    return {
      id = u.id,
      name = dfhack.TranslateName(dfhack.units.getVisibleName(u)),
      race = dfhack.units.getRaceName(u),
      pos = dfh_arr({u.pos.x, u.pos.y, u.pos.z}),
      kind = kind, role = role,
    }
  end
  -- Visitor role: merchant/diplomat flags first, then profession,
  -- then the generic fallback (the "remaining humanoid" cascade).
  -- Verified live 2026-11-26: flags1.merchant and flags1.diplomat
  -- read cleanly. No visitor is on the fort yet, so the role
  -- mapping is best-effort and is refined when one arrives.
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
  -- Histfig -> fort unit, built once per collect: the relations
  -- reader (dfh_relations) resolves a relation's histfig id to the
  -- fort unit carrying it, so a relation is marked in_fort with
  -- its unit id instead of just a name.
  local hf_to_unit = {}
  for _, v in ipairs(df.global.world.units.active) do
    if v.hist_figure_id and v.hist_figure_id >= 0 then
      hf_to_unit[v.hist_figure_id] = v
    end
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
      citizen_pos[#citizen_pos+1] = {u.pos.x, u.pos.y, u.pos.z}
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
        relations = dfh_relations(u, hf_to_unit),
        social = dfh_social(u, hf_to_unit),
        traits = dfh_traits(u),
        emotions = dfh_emotions(u),
        wounds = wounds,
        wound_count = #wounds,
        goal = goal,
      }
    end
    -- Neither citizen nor hostile: wildlife, visitor, or livestock.
    -- (isCitizen / isOpposedToLife are re-checked here; the calls
    -- are cheap C predicates and the citizen block above is long
    -- enough not to re-indent for the sake of hoisting them.)
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
  -- Distance from each wildlife unit to its nearest citizen
  -- (Chebyshev, +10 when the z differs — the same rule as the
  -- hostile threat distance). The exception list ("eagle 12 tiles
  -- from the woodcutter") reads this field.
  for _, w in ipairs(wildlife) do
    local best = nil
    for _, cp in ipairs(citizen_pos) do
      local d = math.max(math.abs(w.pos[1] - cp[1]),
                         math.abs(w.pos[2] - cp[2]))
      if w.pos[3] ~= cp[3] then d = d + 10 end
      if best == nil or d < best then best = d end
    end
    w.dist_nearest_citizen = best
  end
  -- Counts by race, for the per-tick push (counts, not lists).
  local function counts_by_race(list)
    local counts = {}
    for _, rec in ipairs(list) do
      counts[rec.race] = (counts[rec.race] or 0) + 1
    end
    local out = dfh_arr()
    for race, n in pairs(counts) do
      out[#out+1] = {race = race, count = n}
    end
    table.sort(out, function(a, b) return a.count > b.count end)
    return out
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
    wildlife_by_race = counts_by_race(wildlife),
    visitors = visitors,
    visitor_count = #visitors,
    livestock = livestock,
    livestock_count = #livestock,
    livestock_by_race = counts_by_race(livestock),
    total_active_units = total,
    -- Reconciliation: the class counts sum to the game's count.
    -- If this is false, a unit was dropped silently (a bug).
    reconciled = (#citizens + #hostiles + #wildlife + #visitors
                  + #livestock) == total,
    },
  }
end)
if not ok then
  result = {ok = false, section = 'units', error = tostring(err)}
end
dfh_print(result)
