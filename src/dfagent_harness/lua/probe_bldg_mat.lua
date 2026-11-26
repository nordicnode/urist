-- probe_bldg_mat.lua — construction material of one building.
-- PARAMS: building_id. Prints one JSON object.
-- A building placed with mat NONE (-1/-1) can never be constructed:
-- its ConstructBuilding job waits on an item that does not exist
-- (carpenter #22, 2026-11-26). build_workshop fails fast on this
-- instead of burning the whole construction timeout.
local ok, err = pcall(function()
  local target = nil
  for _, b in ipairs(df.global.world.buildings.all) do
    if b.id == PARAMS.building_id then target = b break end
  end
  if target == nil then
    result = {ok = false, error = 'no building #' ..
      tostring(PARAMS.building_id)}
    return
  end
  local mat_type = dfh_try(function() return target.mat_type end, -1)
  local mat_index = dfh_try(function() return target.mat_index end, -1)
  local mat_name = nil
  if mat_type ~= nil and mat_type ~= -1 then
    mat_name = dfh_try(function()
      return tostring(dfhack.matinfo.getToken(
        dfhack.matinfo.decode(mat_type, mat_index))) end, nil)
  end
  result = {ok = true, building_id = target.id,
    mat_type = mat_type, mat_index = mat_index, mat_name = mat_name,
    construction_stage = dfh_try(function()
      return target.construction_stage end, nil)}
end)
if not ok then
  result = {ok = false, error = tostring(err)}
end
dfh_print(result)
