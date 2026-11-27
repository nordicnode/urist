-- act_labor.lua — enable/disable a labor on one citizen.
-- PARAMS: unit_id (-1 = look up by name), name ('' = look up by id),
-- labor (df.unit_labor name, e.g. 'MINE'), on (bool).
-- Name lookup uses the translated visible name and fails when it matches
-- zero or more than one citizen. Prints one JSON object.
-- The sentinel is -1, not 0 (2026-11-27, external review Table 5
-- row 4): unit ids start at 0, so 0 as the by-name sentinel meant
-- unit id 0 could never be targeted by id.
local ok, err = pcall(function()
  if df.unit_labor[PARAMS.labor] == nil then
    error('unknown labor: ' .. tostring(PARAMS.labor))
  end
  local target = nil
  local matches = 0
  for _, u in ipairs(df.global.world.units.active) do
    if dfhack.units.isCitizen(u) then
      local hit = false
      if PARAMS.unit_id ~= -1 then
        hit = u.id == PARAMS.unit_id
      else
        hit = dfhack.TranslateName(dfhack.units.getVisibleName(u)) == PARAMS.name
      end
      if hit then
        target = u
        matches = matches + 1
      end
    end
  end
  if matches == 0 then
    result = {ok = false, action = 'labor', kind = 'precondition',
      error = 'no such citizen'}
    return
  end
  if matches > 1 then
    result = {ok = false, action = 'labor', kind = 'precondition',
      error = 'ambiguous citizen name (matches ' .. matches .. ')'}
    return
  end
  local before = target.status.labors[PARAMS.labor]
  target.status.labors[PARAMS.labor] = PARAMS.on
  local after = target.status.labors[PARAMS.labor]
  result = {ok = true, action = 'labor', id = target.id,
    name = dfhack.TranslateName(dfhack.units.getVisibleName(target)),
    labor = PARAMS.labor, before = before, after = after}
end)
if not ok then
  result = {ok = false, action = 'labor', error = tostring(err)}
end
dfh_print(result)
