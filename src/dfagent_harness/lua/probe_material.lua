-- probe_material.lua — count items of a type, split by accessibility.
-- An item counts as accessible when it is not inside a building (e.g. the
-- embark wagon: its contents cannot be used by jobs until it is
-- deconstructed) and not already reserved by a job.
-- PARAMS: item_type (df.item_type name, e.g. 'WOOD').
-- Prints one JSON object.
local ok, err = pcall(function()
  local itype = df.item_type[PARAMS.item_type]
  if itype == nil then error('unknown item type: ' .. tostring(PARAMS.item_type)) end
  local total, accessible = 0, 0
  for _, it in ipairs(df.global.world.items.other.IN_PLAY) do
    if it:getType() == itype then
      total = total + 1
      if not it.flags.in_building and not it.flags.in_job then
        accessible = accessible + 1
      end
    end
  end
  result = {ok = true, probe = 'material', item_type = PARAMS.item_type,
    total = total, accessible = accessible}
end)
if not ok then
  result = {ok = false, probe = 'material', error = tostring(err)}
end
dfh_print(result)
