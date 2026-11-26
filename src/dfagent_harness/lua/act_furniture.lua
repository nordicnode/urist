-- act_furniture.lua — place a furniture building via constructBuilding.
-- PARAMS: kind (df.building_type name: 'Bed', 'Table', 'Chair',
-- 'Door', 'Coffin', 'Chest', 'Cabinet', 'ArmorStand', 'WeaponRack',
-- 'Statue', 'Floodgate', 'Hatch', 'Grate'), x, y, z.
-- Furniture is 1x1. Placement creates a Construct<kind> job, which a
-- dwarf works only when a matching item exists (e.g. a bed item from
-- the carpenter). Verified live 2026-11-26: Bed #9 placed at
-- (90,80,42) with a ConstructBed job. Furniture structs have no
-- `.type` field — verify via the observe `buildings` section.
-- Prints one JSON object.
local ok, err = pcall(function()
  local btype = df.building_type[PARAMS.kind]
  if btype == nil then error('unknown furniture kind: ' .. tostring(PARAMS.kind)) end
  local b, berr = dfhack.buildings.constructBuilding{
    pos = {x = PARAMS.x, y = PARAMS.y, z = PARAMS.z},
    type = btype, subtype = -1, width = 1, height = 1,
  }
  if not b then
    result = {ok = false, action = 'build-furniture',
      error = tostring(berr or 'constructBuilding failed')}
    return
  end
  result = {ok = true, action = 'build-furniture', kind = PARAMS.kind,
    id = b.id, center = dfh_arr({b.centerx, b.centery, b.z}),
    x1 = b.x1, y1 = b.y1, x2 = b.x2, y2 = b.y2, z = b.z,
    construction_stage = b.construction_stage}
end)
if not ok then
  result = {ok = false, action = 'build-furniture', error = tostring(err)}
end
dfh_print(result)
