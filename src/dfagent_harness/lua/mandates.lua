-- mandates.lua — the fort's mandates (noble demands).
-- Prints one JSON object: {"ok": true, "section": "mandates", ...}
-- Mandate struct fields are dumped generically (dfh_dump): no live
-- instance existed to probe field names against (the fort has no
-- mandates yet — no appointed nobles), so named fields are read
-- best-effort and the raw scalar dump is kept.
local ok, err = pcall(function()
  local list = dfh_arr()
  for _, m in ipairs(df.global.world.mandates) do
    local d = dfh_dump(m)
    d.id = dfh_try(function() return m.id end, d.id)
    list[#list+1] = d
  end
  result = {
    ok = true, section = 'mandates',
    mandates = list,
  }
end)
if not ok then
  result = {ok = false, section = 'mandates', error = tostring(err)}
end
dfh_print(result)
