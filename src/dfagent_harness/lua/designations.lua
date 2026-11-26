-- designations.lua — designation counts by type via a full map-block scan.
-- SLOW: ~4 s on a 192x192x58 embark (8352 blocks x 256 tiles). Only run
-- when explicitly requested (--section designations); the default observe
-- skips it. Prints one JSON object.
local ok, err = pcall(function()
  local t0 = os.clock()
  local dig_counts = {}
  local smooth = 0
  local total = 0
  for _, blk in ipairs(df.global.world.map.map_blocks) do
    for x = 0, 15 do
      for y = 0, 15 do
        local d = blk.designation[x][y]
        if d.dig ~= 0 then
          local name = tostring(df.tile_dig_designation[d.dig])
          dig_counts[name] = (dig_counts[name] or 0) + 1
          total = total + 1
        end
        if d.smooth ~= 0 then smooth = smooth + 1 end
      end
    end
  end
  local by_type = dfh_arr()
  for k, v in pairs(dig_counts) do
    by_type[#by_type+1] = {type = k, count = v}
  end
  table.sort(by_type, function(a, b) return a.count > b.count end)
  result = {
    ok = true, section = 'designations',
    designations = {
    dig_total = total,
    smooth_total = smooth,
    dig_by_type = by_type,
    scan_seconds = os.clock() - t0,
    },
  }
end)
if not ok then
  result = {ok = false, section = 'designations', error = tostring(err)}
end
dfh_print(result)
