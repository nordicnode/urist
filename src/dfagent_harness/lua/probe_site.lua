-- probe_site.lua — is a WxH rectangle at (x,y,z) free to build on?
-- Checks: in map bounds, every tile is FLOOR or PEBBLES, no plant, no
-- unit, no overlapping building, and no stale building occupancy.
-- The occupancy check matters: dfhack.buildings.constructBuilding
-- (via Buildings::checkFreeTiles) refuses a tile whose occupancy
-- "building" flag is set, and deconstructing a building does NOT clear
-- that flag — a deconstructed workshop's (or the wagon's) tiles stay
-- unbuildable until the flag is cleared (verified live 2026-11-26:
-- (85,85) and (95,95) probe "free" here without the check yet refuse
-- placement; occupancy.building reads 2 there, 0 elsewhere). Note the
-- field is numeric, not boolean — test it as ~= 0, not "== true".
-- REACHABILITY (placement system, 2026-11-26): when PARAMS.from_x /
-- from_y / from_z are given, the rect centre must be walkable from
-- that point (dfhack.maps.canWalkBetween — the game's own
-- pathfinder; verified live: centre->shrub site True, centre->far
-- corner False, centre->deep stone False). A site with no path is
-- NOT a free site: construction suspends with "Could not find path".
-- When no from-point is given, reachable is nil (unchecked) and the
-- caller must say so explicitly — never silently hand the model an
-- unverified site.
-- PARAMS: x,y,z,width,height[,from_x,from_y,from_z]. Prints one JSON object.
local ok, err = pcall(function()
  local problems = dfh_arr()
  local reachable = nil
  local m = df.global.world.map
  if PARAMS.x < 0 or PARAMS.y < 0
    or PARAMS.x + PARAMS.width > m.x_count
    or PARAMS.y + PARAMS.height > m.y_count
    or PARAMS.z < 0 or PARAMS.z >= m.z_count then
    problems[#problems+1] = 'site out of map bounds'
  else
    for x = PARAMS.x, PARAMS.x + PARAMS.width - 1 do
      for y = PARAMS.y, PARAMS.y + PARAMS.height - 1 do
        local b = dfhack.maps.getTileBlock(x, y, PARAMS.z)
        local tt = b.tiletype[x % 16][y % 16]
        local shape = tostring(df.tiletype_shape[df.tiletype.attrs[tt].shape])
        if shape ~= 'FLOOR' and shape ~= 'PEBBLES' then
          problems[#problems+1] = 'tile ' .. x .. ',' .. y .. ' is ' .. shape
        end
        -- occupancy.building is numeric (0 = free, 2 = occupied here);
        -- a deconstructed building leaves it set, and constructBuilding
        -- refuses the tile until it is cleared.
        if b.occupancy[x % 16][y % 16].building ~= 0 then
          problems[#problems+1] = 'tile ' .. x .. ',' .. y
            .. ' has stale building occupancy'
        end
      end
    end
    for _, p in ipairs(df.global.world.plants.all) do
      if p.pos.z == PARAMS.z
        and p.pos.x >= PARAMS.x and p.pos.x < PARAMS.x + PARAMS.width
        and p.pos.y >= PARAMS.y and p.pos.y < PARAMS.y + PARAMS.height then
        problems[#problems+1] = 'plant at ' .. p.pos.x .. ',' .. p.pos.y
      end
    end
    for _, u in ipairs(df.global.world.units.active) do
      if u.pos.z == PARAMS.z
        and u.pos.x >= PARAMS.x and u.pos.x < PARAMS.x + PARAMS.width
        and u.pos.y >= PARAMS.y and u.pos.y < PARAMS.y + PARAMS.height then
        problems[#problems+1] = 'unit at ' .. u.pos.x .. ',' .. u.pos.y
      end
    end
    for _, bd in ipairs(df.global.world.buildings.all) do
      if bd.z == PARAMS.z
        and bd.x2 >= PARAMS.x and bd.x1 < PARAMS.x + PARAMS.width
        and bd.y2 >= PARAMS.y and bd.y1 < PARAMS.y + PARAMS.height then
        problems[#problems+1] = 'building ' .. tostring(df.building_type[bd:getType()])
          .. ' #' .. bd.id .. ' overlaps site'
      end
    end
    -- Reachability: the rect centre must be walkable from the
    -- from-point (the fort centre, where dwarves stand). The
    -- centre tile is the proxy for the site: if it is walkable,
    -- the site is in the walkable region and a dwarf can reach it
    -- to construct. A shrub on the centre does not block walking
    -- (verified live), but a wall, a disconnected area, or solid
    -- stone does.
    if PARAMS.from_x ~= nil and PARAMS.from_y ~= nil
      and PARAMS.from_z ~= nil then
      local cx = PARAMS.x + math.floor(PARAMS.width / 2)
      local cy = PARAMS.y + math.floor(PARAMS.height / 2)
      reachable = dfhack.maps.canWalkBetween(
        {x = PARAMS.from_x, y = PARAMS.from_y, z = PARAMS.from_z},
        {x = cx, y = cy, z = PARAMS.z})
      if not reachable then
        problems[#problems+1] = 'no path from '
          .. PARAMS.from_x .. ',' .. PARAMS.from_y .. ',' .. PARAMS.from_z
          .. ' to site centre ' .. cx .. ',' .. cy .. ',' .. PARAMS.z
      end
    end
  end
  result = {ok = true, probe = 'site', free = #problems == 0,
    reachable = reachable, problems = problems}
end)
if not ok then
  result = {ok = false, probe = 'site', error = tostring(err)}
end
dfh_print(result)
