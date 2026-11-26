-- act_build.lua — place a workshop via dfhack.buildings.constructBuilding.
-- PARAMS: type (df.building_type name, e.g. 'Workshop'),
-- subtype (e.g. 'Carpenters' — a df.workshop_type name), x, y, z,
-- width, height. (x,y,z) is the building's corner tile.
-- Filters are derived by constructBuilding from the building definition
-- (a carpenter's workshop takes one wood log); the call fails with an
-- error when no matching item is available or the tiles are not free.
-- The building is created with a ConstructBuilding job; construction
-- itself happens on game ticks (the Python side waits for it).
-- Prints one JSON object.
local ok, err = pcall(function()
  local btype = df.building_type[PARAMS.type]
  if btype == nil then error('unknown building type: ' .. tostring(PARAMS.type)) end
  local subtype = -1
  if PARAMS.subtype ~= nil then
    subtype = df.workshop_type[PARAMS.subtype]
    if subtype == nil then
      error('unknown workshop subtype: ' .. tostring(PARAMS.subtype))
    end
  end
  local b, berr = dfhack.buildings.constructBuilding{
    pos = {x = PARAMS.x, y = PARAMS.y, z = PARAMS.z},
    type = btype, subtype = subtype,
    width = PARAMS.width, height = PARAMS.height,
  }
  if not b then
    result = {ok = false, action = 'build',
      error = tostring(berr or 'constructBuilding failed')}
    return
  end
  result = {ok = true, action = 'build', id = b.id,
    center = dfh_arr({b.centerx, b.centery, b.z}),
    x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z,
    construction_stage = b.construction_stage}
end)
if not ok then
  result = {ok = false, action = 'build', error = tostring(err)}
end
dfh_print(result)
