-- probe_focus.lua: report the current DFHack GUI focus string, so UI
-- helpers can verify the game is back on the main map view after
-- sending keystrokes (a stuck sub-screen freezes the tick even when
-- the pause flag is clear). Prints one JSON object.
local ok, err = pcall(function()
  local focus = dfhack.gui.getCurFocus()
  result = {ok = true, focus = focus}
end)
if not ok then
  result = {ok = false, error = tostring(err)}
end
dfh_print(result)
