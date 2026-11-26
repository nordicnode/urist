-- status.lua — game clock, mode, pause, focus, population headline.
-- Prints one JSON object: {"ok": true, "section": "status", ...}
local ok, err = pcall(function()
  local year_tick = df.global.cur_year_tick
  local month = math.floor(year_tick / 33600) + 1
  local day = math.floor((year_tick % 33600) / 1200) + 1
  local season_idx = df.global.cur_season
  local citizens, jobless, animals, threats = 0, 0, 0, 0
  local total = #df.global.world.units.active
  for _, u in ipairs(df.global.world.units.active) do
    if dfhack.units.isCitizen(u) then
      citizens = citizens + 1
      if u.job.current_job == nil then jobless = jobless + 1 end
    elseif dfhack.units.isAnimal(u) then
      animals = animals + 1
    end
    if dfhack.units.isOpposedToLife(u)
      or dfh_try(function() return u.flags1.active_invader end, false) then
      threats = threats + 1
    end
  end
  local fort_name = dfh_try(function()
    -- The player's fort is the unique site with type 0 in world_data.
    for _, s in ipairs(df.global.world.world_data.sites) do
      if s.type == 0 then
        return dfhack.TranslateName(s.name)
      end
    end
    return nil
  end, nil)
  local save_dir = dfh_try(function()
    return df.global.world.cur_savegame.save_dir
  end, nil)
  result = {
    ok = true, section = 'status',
    status = {
    year = df.global.cur_year,
    year_tick = year_tick,
    season = tostring(df.season[season_idx]),
    season_index = season_idx,
    season_tick = df.global.cur_season_tick,
    month = month, day = day,
    date = string.format('%d-%02d-%02d', df.global.cur_year, month, day),
    paused = df.global.pause_state,
    gametype = tostring(df.game_type[df.global.gametype]),
    focus = dfhack.gui.getCurFocus(true),
    fort_name = fort_name,
    save_dir = save_dir,
    population = {
      citizens = citizens,
      jobless = jobless,
      animals = animals,
      total_active_units = total,
      threats = threats,
    },
    },
  }
end)
if not ok then
  result = {ok = false, section = 'status', error = tostring(err)}
end
dfh_print(result)
