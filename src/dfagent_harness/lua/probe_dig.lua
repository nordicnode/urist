-- probe_dig.lua — read-back for designate_dig: count dig designations
-- in a rectangle, by type. PARAMS: x0,y0,z0,x1,y1,z1.
-- Reads the same blk.designation structs the game and the UI use, so a
-- count here is the designation as the game sees it. Prints one JSON object.
local ok, err = pcall(function()
  local total = 0
  local by_type = {}
  for x = PARAMS.x0, PARAMS.x1 do
    for y = PARAMS.y0, PARAMS.y1 do
      local b = dfhack.maps.getTileBlock(x, y, PARAMS.z0)
      local d = b.designation[x % 16][y % 16].dig
      if d ~= 0 then
        total = total + 1
        local name = tostring(df.tile_dig_designation[d])
        by_type[name] = (by_type[name] or 0) + 1
      end
    end
  end
  local arr = dfh_arr()
  for k, v in pairs(by_type) do arr[#arr+1] = {type = k, count = v} end
  table.sort(arr, function(a, b) return a.count > b.count end)
  result = {ok = true, probe = 'dig', dig_total = total, dig_by_type = arr}
end)
if not ok then
  result = {ok = false, probe = 'dig', error = tostring(err)}
end
dfh_print(result)
