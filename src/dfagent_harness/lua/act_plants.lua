-- act_plants.lua — mark/unmark trees (chop) or shrubs (gather) in a rect.
-- PARAMS: x0,y0,z0,x1,y1,z1, kind ('tree'|'shrub'), mark (bool).
--
-- Mechanism (DFHack 0.47.05-r8, library/modules/Designations.cpp):
-- a plant is designated by setting dig=Default on its *designation tile*
-- and block.flags.designated=true. For shrubs the designation tile is the
-- plant's own tile; for trees it is the SE-most trunk tile of the tree's
-- footprint (DFHack walks SE from the footprint centre while the tile is
-- trunk; the SE-most trunk tile is the same tile for single-trunk trees
-- and a valid trunk tile for multi-trunk trees). Trunk tiles are found by
-- tiletype material TREE at the tree's z-level. Unmarking clears the
-- designation ONLY: it does NOT remove FellTree/GatherPlants jobs.
-- dfhack.job.removeJob was removed 2026-11-25 after two live-suite runs
-- ended in "free(): double free detected in tcache 2" — the crash
-- reproduces when the game is unmarked through this path, and removeJob
-- does not even take the job off the list (it returns true and the job
-- stays listed through thousands of ticks), so the call buys nothing and
-- risks the game. FellTree jobs never leave the list and GatherPlants
-- jobs leave on the game's own cleanup; both are reported in
-- remaining_jobs by the Python side rather than failed on.
--
-- Classification is by structure: a tree has tree_info set, a shrub has
-- is_shrub set, and a *sapling* has neither (is_shrub=false,
-- tree_info=nil) — saplings are excluded from both kinds. (Counting a
-- sapling as a tree set a dig designation on a floor tile, which the
-- game read as a Dig job — found live 2026-11-25.)
--
-- The des_tile() function below is duplicated in probe_plants.lua; keep
-- the two in sync. Prints one JSON object.
local function des_tile(p)
  if p.tree_info == nil then return p.pos.x, p.pos.y, p.pos.z end
  local dx, dy = p.tree_info.dim_x, p.tree_info.dim_y
  local best_x, best_y = nil, nil
  for x = p.pos.x - math.floor(dx / 2), p.pos.x + math.floor(dx / 2) do
    for y = p.pos.y - math.floor(dy / 2), p.pos.y + math.floor(dy / 2) do
      local b = dfhack.maps.getTileBlock(x, y, p.pos.z)
      local tt = b.tiletype[x % 16][y % 16]
      if df.tiletype.attrs[tt].material == df.tiletype_material.TREE then
        if best_x == nil or x > best_x or (x == best_x and y > best_y) then
          best_x, best_y = x, y
        end
      end
    end
  end
  if best_x == nil then return p.pos.x, p.pos.y, p.pos.z end
  return best_x, best_y, p.pos.z
end

local ok, err = pcall(function()
  if PARAMS.kind ~= 'tree' and PARAMS.kind ~= 'shrub' then
    error('unknown plant kind: ' .. tostring(PARAMS.kind))
  end
  local changed = dfh_arr()
  local already = dfh_arr()
  local found = 0
  for _, p in ipairs(df.global.world.plants.all) do
    local is_match = false
    if PARAMS.kind == 'tree' then
      is_match = p.tree_info ~= nil
    elseif PARAMS.kind == 'shrub' then
      is_match = p.flags.is_shrub
    end
    if is_match
      and p.pos.z == PARAMS.z0
      and p.pos.x >= PARAMS.x0 and p.pos.x <= PARAMS.x1
      and p.pos.y >= PARAMS.y0 and p.pos.y <= PARAMS.y1 then
      found = found + 1
      local dx, dy, dz = des_tile(p)
      local b = dfhack.maps.getTileBlock(dx, dy, dz)
      local d = b.designation[dx % 16][dy % 16]
      local entry = {
        pos = dfh_arr({p.pos.x, p.pos.y, p.pos.z}),
        des = dfh_arr({dx, dy, dz}),
      }
      if PARAMS.mark then
        if d.dig == df.tile_dig_designation.Default then
          already[#already+1] = entry
        else
          d.dig = df.tile_dig_designation.Default
          b.flags.designated = true
          changed[#changed+1] = entry
        end
      else
        if d.dig == df.tile_dig_designation.Default then
          d.dig = df.tile_dig_designation.No
          b.flags.designated = true
          changed[#changed+1] = entry
          -- Jobs are NOT removed here. dfhack.job.removeJob on a
          -- FellTree/GatherPlants job is the documented double-free
          -- crash path (see the header comment): it does not take the
          -- job off the list anyway, and the game cleans up
          -- GatherPlants jobs itself while FellTree jobs are reported
          -- in remaining_jobs by the Python side. A dwarf can still
          -- take a stale FellTree job if the tree is reachable; that
          -- is the game's behaviour, not something unmarking can fix.
        else
          already[#already+1] = entry
        end
      end
    end
  end
  if found == 0 then
    result = {ok = false, action = 'plants', kind = 'precondition',
      error = 'no ' .. PARAMS.kind .. 's in area', found = 0}
    return
  end
  result = {ok = true, action = 'plants', kind = PARAMS.kind,
    mark = PARAMS.mark, found = found,
    changed = changed, already = already}
end)
if not ok then
  result = {ok = false, action = 'plants', error = tostring(err)}
end
dfh_print(result)
