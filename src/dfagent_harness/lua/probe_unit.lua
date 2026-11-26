-- probe_unit.lua — full record for one unit by id, any class.
-- PARAMS: id. Returns the citizen record (same fields as units.lua),
-- or, for a non-citizen, the compact record plus wounds, job and
-- owner (for livestock, found by a reverse scan: the owner is the
-- unit whose relationship_ids.Pet is this unit's id). Prints one
-- JSON object. A unit that does not exist returns ok=false with
-- kind 'not_found'.
local ok, err = pcall(function()
  local target = nil
  for _, u in ipairs(df.global.world.units.active) do
    if u.id == PARAMS.id then target = u break end
  end
  if target == nil then
    result = {ok = false, probe = 'unit', kind = 'not_found',
      error = 'no unit with id ' .. tostring(PARAMS.id)}
    return
  end
  local u = target
  local is_cit = dfhack.units.isCitizen(u)
  local is_host = dfhack.units.isOpposedToLife(u)
    or dfh_try(function() return u.flags1.active_invader end, false)
  local is_an = dfh_try(function() return dfhack.units.isAnimal(u) end,
                         false)
  local is_tame = false
  if is_an then
    is_tame = dfh_try(function() return dfhack.units.isTame(u) end,
                      false)
  end
  local kind, role
  if is_cit then kind, role = 'citizen', dfhack.units.getProfessionName(u)
  elseif is_host then kind, role = 'hostile', 'hostile'
  elseif is_an then
    kind = is_tame and 'livestock' or 'wildlife'
    role = is_tame and 'pet' or 'wild'
  else
    kind = 'visitor'
    if dfh_try(function() return u.flags1.merchant end, false) then
      role = 'merchant'
    elseif dfh_try(function() return u.flags1.diplomat end, false) then
      role = 'diplomat'
    else role = 'visitor' end
  end
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
  -- Owner (livestock only): the unit whose relationship_ids.Pet is
  -- this unit's id. A stray tame animal has no owner (nil).
  local owner = nil
  if is_an and is_tame then
    for _, other in ipairs(df.global.world.units.active) do
      local pet = dfh_try(
        function() return other.relationship_ids.Pet end, nil)
      if pet == u.id then owner = other.id break end
    end
  end
  local rec = {
    id = u.id,
    name = dfhack.TranslateName(dfhack.units.getVisibleName(u)),
    race = dfhack.units.getRaceName(u),
    pos = dfh_arr({u.pos.x, u.pos.y, u.pos.z}),
    kind = kind, role = role,
    tame = is_an and is_tame or nil,
    hostile = is_host,
    wounds = wounds,
    wound_count = #wounds,
    job = job,
    idle = cur == nil,
    owner = owner,
  }
  if is_cit then
    rec.profession = dfhack.units.getProfessionName(u)
    rec.profession_id = u.profession
    rec.sex = u.sex
    rec.age = dfhack.units.getAge(u)
    rec.mood = u.mood
    rec.mood_name = u.mood == -1 and 'none'
      or tostring(df.mood_type[u.mood])
    local soul = u.status.current_soul
    if soul then
      rec.stress = {
        level = soul.personality.stress_level,
        category = dfhack.units.getStressCategory(u)}
      rec.counters = {
        hunger = u.counters2.hunger_timer,
        thirst = u.counters2.thirst_timer,
        sleepiness = u.counters2.sleepiness_timer}
    end
  end
  result = {ok = true, probe = 'unit', unit = rec}
end)
if not ok then
  result = {ok = false, probe = 'unit', error = tostring(err)}
end
dfh_print(result)
