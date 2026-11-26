-- probe_material.lua — count items of a type, split by accessibility.
-- An item counts as accessible when it is not inside a building (e.g. the
-- embark wagon: its contents cannot be used by jobs until it is
-- deconstructed) and not already reserved by a job.
-- Also returns the material (mat_type/mat_index) of the first
-- accessible item, so build_workshop can pass an EXPLICIT material
-- filter to constructBuilding: without one, the game sometimes
-- creates the building with mat NONE (seen live 2026-11-26:
-- carpenter #22, stage 0 forever, job waiting on an item that
-- does not exist).
-- PARAMS: item_type (df.item_type name, e.g. 'WOOD').
-- Prints one JSON object.
local ok, err = pcall(function()
  local itype = df.item_type[PARAMS.item_type]
  if itype == nil then error('unknown item type: ' .. tostring(PARAMS.item_type)) end
  local total, accessible = 0, 0
  local mat_type, mat_index = nil, nil
  for _, it in ipairs(df.global.world.items.other.IN_PLAY) do
    if it:getType() == itype then
      total = total + 1
      if not it.flags.in_building and not it.flags.in_job then
        accessible = accessible + 1
        if mat_type == nil then
          mat_type = it:getMaterial()
          mat_index = it:getMaterialIndex()
        end
      end
    end
  end
  result = {ok = true, probe = 'material', item_type = PARAMS.item_type,
    total = total, accessible = accessible,
    mat_type = mat_type, mat_index = mat_index}
end)
if not ok then
  result = {ok = false, probe = 'material', error = tostring(err)}
end
dfh_print(result)
