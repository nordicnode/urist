-- read_match_grid.lua: read the embark-assistant overlay's match grid
-- off the screen and return the matching world tiles.
--
-- The overlay draws the world map twice: a 1:1 region view (the precise
-- one) and a scaled minimap (lossy). This reads ONLY the region view,
-- via dfhack.screen.readTile (read-only, no memory dereferencing).
-- A green X (ch 'X', fg 0/black, bg 2/green) marks the top-left corner
-- of a matching 4x4 embark placement. Yellow X (bg 14) is preliminary
-- and is NOT returned.
--
-- The viewport math is the overlay's own (plugins/embark-assistant/
-- overlay.cpp, render): the region view is drawn at screen
-- (i - left_x + 18, k - top_y + 2), where left_x/top_y are derived
-- from the region cursor and the window size, clamped to the world.
-- World tile from a region-view screen cell:
--   (sx - 18 + left_x, sy - 2 + top_y).
-- Prints one JSON object: {ok, matches: [{x, y}], count, cursor,
-- viewport, grid}. The caller tracks whether the overlay is open and
-- whether Find has run; this helper only reports what the region view
-- shows right now. A count of 0 means no green X is visible in the
-- current viewport (overlay off, Find not run, or genuinely no match
-- in view) — the caller must distinguish those by its own state.
local ok, err = pcall(function()
  local vs = dfhack.gui.getCurViewscreen()
  local s = tostring(vs)
  if not s:find("choose_start_sitest") then
    result = {ok = false, screen = s,
              error = "not on the embark screen (viewscreen_choose_start_sitest)"}
    return
  end
  local loc = vs.location
  local cx, cy = loc.region_pos.x, loc.region_pos.y
  local width, height = dfhack.screen.getWindowSize()
  -- getWindowSize returns (width, height) as two values, not a table.
  local dim_x = df.global.world.worldgen.worldgen_parms.dim_x
  local dim_y = df.global.world.worldgen.worldgen_parms.dim_y
  -- Overlay viewport (integer division, same as the C++).
  local span_x = math.floor(width / 2) - 7 - 18
  local span_y = height - 8 - 2
  local left_x = cx - math.floor((math.floor(width / 2) - 7 - 18 + 1) / 2)
  local top_y = cy - math.floor((height - 8 - 2 + 1) / 2)
  if left_x < 0 then left_x = 0 end
  if top_y < 0 then top_y = 0 end
  local right_x = left_x + span_x
  local bottom_y = top_y + span_y
  if right_x >= dim_x then
    right_x = dim_x - 1
    left_x = right_x - span_x
  end
  if bottom_y >= dim_y then
    bottom_y = dim_y - 1
    top_y = bottom_y - span_y
  end
  if left_x < 0 then left_x = 0 end
  if top_y < 0 then top_y = 0 end
  local matches = {}
  for sy = 2, 2 + span_y do
    for sx = 18, 18 + span_x do
      local tile = dfhack.screen.readTile(sx, sy)
      if tile and tile.ch == 88 and tile.fg == 0 and tile.bg == 2 then
        -- ch 88 = 'X', fg 0 = black, bg 2 = green: a match.
        local wx = sx - 18 + left_x
        local wy = sy - 2 + top_y
        if wx >= 0 and wx < dim_x and wy >= 0 and wy < dim_y then
          matches[#matches + 1] = {x = wx, y = wy}
        end
      end
    end
  end
  result = {
    ok = true,
    cursor = {x = cx, y = cy},
    viewport = {left_x = left_x, top_y = top_y,
                right_x = right_x, bottom_y = bottom_y},
    grid = {w = width, h = height, dim_x = dim_x, dim_y = dim_y},
    matches = matches,
    count = #matches,
  }
end)
if not ok then
  result = {ok = false, error = tostring(err)}
end
dfh_print(result)
