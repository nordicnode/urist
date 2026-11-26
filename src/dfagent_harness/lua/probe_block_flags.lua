-- probe_block_flags.lua — dump the map-block flags for the block
-- containing a tile, to see whether Lua-set dig designations mark
-- the block (the sweep may skip unmarked blocks). PARAMS: x, y, z.
-- Also dumps the tile's designation and tiletype for reference.
local ok, err = pcall(function()
  local x, y, z = PARAMS.x, PARAMS.y, PARAMS.z
  local b = dfhack.maps.getTileBlock(x, y, z)
  local des = b.designation[x % 16][y % 16]
  local tt = b.tiletype[x % 16][y % 16]
  local out = {
    ok = true,
    block_flags = dfh_dump(b.flags),
    designation = {dig = des.dig, smooth = des.smooth,
      hidden = des.hidden, flow_size = des.flow_size},
    tiletype = tostring(tt),
    shape = tostring(df.tiletype_shape[df.tiletype.attrs[tt].shape]),
    material = tostring(df.tiletype_material[df.tiletype.attrs[tt].material]),
  }
  dfh_print(out)
end)
if not ok then dfh_print({ok = false, error = tostring(err)}) end
