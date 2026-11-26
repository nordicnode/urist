-- act_deconstruct.lua — mark a building for deconstruction and clear
-- the stale "building" occupancy on its footprint (phase 2 finding:
-- deconstruction does not clear the occupancy flag, and
-- constructBuilding refuses such tiles until it is cleared).
-- PARAMS: building_id (int).
-- The building vanishes a tick later (almost_deleted); the caller
-- unpauses briefly and waits for it to disappear from the buildings
-- list. Prints one JSON object.
local ok, err = pcall(function()
  local b = df.building.find(PARAMS.building_id)
  if b == nil then error('no building #' .. tostring(PARAMS.building_id)) end
  local x1, y1, z, x2, y2 = b.x1, b.y1, b.z, b.x2, b.y2
  dfhack.buildings.deconstruct(b)
  b.flags.almost_deleted = true
  for x = x1, x2 do
    for y = y1, y2 do
      local block = dfhack.maps.getTileBlock(x, y, z)
      if block then block.occupancy[x % 16][y % 16].building = 0 end
    end
  end
  result = {ok = true, action = 'deconstruct',
    building_id = PARAMS.building_id,
    box = dfh_arr({x1, y1, z, x2, y2, z})}
end)
if not ok then
  result = {ok = false, action = 'deconstruct', error = tostring(err)}
end
dfh_print(result)
