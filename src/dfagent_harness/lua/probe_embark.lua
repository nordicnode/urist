-- probe_embark.lua: report the embark screen (viewscreen_choose_start_sitest)
-- state: the region cursor, the embark rectangle, and the biome index.
-- Prints one JSON object. The driver uses this to verify every
-- cursor/rect move by keys, and to confirm the game is on the embark
-- screen before starting site selection.
local ok, err = pcall(function()
  local vs = dfhack.gui.getCurViewscreen()
  local s = tostring(vs)
  if not s:find("choose_start_sitest") then
    result = {ok = false, screen = s,
              error = "not on the embark screen (viewscreen_choose_start_sitest)"}
    return
  end
  local loc = vs.location
  result = {
    ok = true,
    screen = "viewscreen_choose_start_sitest",
    cursor = {x = loc.region_pos.x, y = loc.region_pos.y},
    rect_min = {x = loc.embark_pos_min.x, y = loc.embark_pos_min.y},
    rect_max = {x = loc.embark_pos_max.x, y = loc.embark_pos_max.y},
    rect_w = loc.embark_pos_max.x - loc.embark_pos_min.x + 1,
    rect_h = loc.embark_pos_max.y - loc.embark_pos_min.y + 1,
    biome_idx = vs.biome_idx,
  }
end)
if not ok then
  result = {ok = false, error = tostring(err)}
end
dfh_print(result)
