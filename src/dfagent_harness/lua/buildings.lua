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
    -- Stockpiles have no construction_stage field at all (found
    -- live 2026-11-26: one stockpile broke the whole buildings
    -- section) — read it best-effort, omit when unavailable.
    local stage = dfh_try(function() return b.construction_stage end,
                          nil)
    -- Workshop subtype (Carpenters/Still/Kitchen/...) — the planner
    -- needs it to find the still/carpenter by id (phase 4). FarmPlot
    -- and furniture structs have no `.type` field at all, so the
    -- subtype read is best-effort and omitted when unavailable.
    local subtype = dfh_try(function()
      if tname == 'Workshop' then
        local st = b:getSubtype()
        if st ~= nil and st ~= -1 then
          return tostring(df.workshop_type[st])
        end
      end
      return nil
    end, nil)
    local entry = {
      id = b.id,
      type = tname,
      type_id = t,
      x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z,
      center = dfh_arr({b.centerx, b.centery, b.z}),
      jobs = jobs,
      contained_items = contained,
    }
    if stage ~= nil then entry.construction_stage = stage end
    if subtype ~= nil then entry.subtype = subtype end
    list[#list+1] = entry
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
