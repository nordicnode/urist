-- act_zone.lua — create an activity zone (civzone) programmatically.
-- Same route as stockpiles: dfhack.buildings.constructBuilding with
-- type=Civzone and abstract=true (the docs: abstract=true is
-- "Required for stockpiles and civzones"). The zone's kind is TWO
-- parts (verified live 2026-11-26): the building's `type` field
-- must be df.civzone_type.ActivityZone (9 — constructBuilding
-- leaves it 0/Home), AND the kind flag in `zone_flags` must be set
-- (meeting_area, pen_pasture, pit_pond, hospital,
-- animal_training, fishing, garbage_dump, gather, clay, sand,
-- water_source), plus zone_flags.active = true. No construction
-- job: a civzone is abstract, it exists at once.
-- PARAMS: x,y,z,width,height,zone_type (a zone_flags kind name,
-- e.g. meeting_area, pen_pasture, pit_pond, hospital).
-- Prints JSON.
local ok, err = pcall(function()
  local zt = PARAMS.zone_type or 'meeting_area'
  local b, err2 = dfhack.buildings.constructBuilding{
    type = df.building_type.Civzone,
    pos = {x = PARAMS.x, y = PARAMS.y, z = PARAMS.z},
    width = PARAMS.width, height = PARAMS.height,
    abstract = true,
  }
  if not b then
    result = {ok = false, error = tostring(err2)}
    return
  end
  if b.zone_flags[zt] == nil then
    result = {ok = false, error = 'unknown zone kind '
      .. tostring(zt), building_id = b.id}
    return
  end
  b.type = df.civzone_type.ActivityZone
  b.zone_flags[zt] = true
  b.zone_flags.active = true
  dfhack.job.checkBuildingsNow()
  result = {ok = true, building_id = b.id,
    zone_type = zt,
    pos = {b.x1, b.y1, b.z},
    width = b.x2 - b.x1 + 1, height = b.y2 - b.y1 + 1}
end)
if not ok then result = {ok = false, error = tostring(err)} end
dfh_print(result)
