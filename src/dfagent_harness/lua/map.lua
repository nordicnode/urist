-- map.lua — embark/map summary (cheap counts only; no block scan).
-- Prints one JSON object: {"ok": true, "section": "map", ...}
local ok, err = pcall(function()
  local trees, shrubs = 0, 0
  for _, p in ipairs(df.global.world.plants.all) do
    if p.flags.is_shrub then shrubs = shrubs + 1 else trees = trees + 1 end
  end
  local m = df.global.world.map
  result = {
    ok = true, section = 'map',
    map = {
    size_tiles = dfh_arr({m.x_count, m.y_count}),
    z_levels = m.z_count,
    region_x = m.region_x,
    region_y = m.region_y,
    plants_total = #df.global.world.plants.all,
    trees = trees,
    shrubs = shrubs,
    },
  }
end)
if not ok then
  result = {ok = false, section = 'map', error = tostring(err)}
end
dfh_print(result)
