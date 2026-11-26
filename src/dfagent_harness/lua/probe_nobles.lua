-- probe_nobles.lua — read noble appointments (read-only).
-- Returns, per responsibility, the assigned histfig id and (when the
-- unit is still a citizen) the unit id + name. Responsibilities:
-- MANAGE_PRODUCTION (manager), ACCOUNTING (bookkeeper), TRADE
-- (broker), MEET_WORKERS (expedition leader), MILITARY_GOALS
-- (militia commander). Verified live 2026-11-26: the UI appointment
-- writes assignments_by_type (manager: {id:6, position_id:10,
-- histfig:38919}); a hand-written assignment with a guessed id does
-- NOT register (nobles screen stays VACANT) — appointment is UI-only.
-- Prints one JSON object.
local ok, err = pcall(function()
  local ent = df.global.ui.main.fortress_entity
  local out = {}
  local names = {'MANAGE_PRODUCTION', 'ACCOUNTING', 'TRADE',
    'MEET_WORKERS', 'MILITARY_GOALS', 'MILITARY_STRATEGY'}
  for _, key in ipairs(names) do
    local resp = df.entity_position_responsibility[key]
    local list = {}
    local vec = ent.assignments_by_type[resp]
    if vec ~= nil then
      for _, a in ipairs(vec) do
        local entry = {id = a.id, position_id = a.position_id,
          histfig_id = a.histfig}
        local hf = df.historical_figure.find(a.histfig)
        if hf ~= nil and hf.unit_id ~= -1 then
          local u = df.unit.find(hf.unit_id)
          if u ~= nil then
            entry.unit_id = u.id
            entry.name = dfhack.TranslateName(dfhack.units.getVisibleName(u))
          end
        end
        table.insert(list, entry)
      end
    end
    out[key] = list
  end
  result = {ok = true, nobles = out}
end)
if not ok then
  result = {ok = false, error = tostring(err)}
end
dfh_print(result)
