-- buildings.lua — every building + summary by type.
-- Prints one JSON object: {"ok": true, "section": "buildings", ...}
local ok, err = pcall(function()
  local list = dfh_arr()
  local by_type = {}
  for _, b in ipairs(df.global.world.buildings.all) do
    local t = b:getType()
    local tname = tostring(df.building_type[t])
    by_type[tname] = (by_type[tname] or 0) + 1
    local jobs = dfh_try(function() return #b.jobs end, nil)
    local contained = dfh_try(function() return #b.contained_items end, nil)
    list[#list+1] = {
      id = b.id,
      type = tname,
      type_id = t,
      x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z,
      center = dfh_arr({b.centerx, b.centery, b.z}),
      construction_stage = b.construction_stage,
      jobs = jobs,
      contained_items = contained,
    }
  end
  local summary = dfh_arr()
  for k, v in pairs(by_type) do
    summary[#summary+1] = {type = k, count = v}
  end
  table.sort(summary, function(a, b) return a.count > b.count end)
  result = {
    ok = true, section = 'buildings',
    buildings = {
      list = list,
      count = #list,
      summary = summary,
    },
  }
end)
if not ok then
  result = {ok = false, section = 'buildings', error = tostring(err)}
end
dfh_print(result)
