-- Minimal JSON encoder (DFHack's Lua has no built-in json module).

local CP437 = {
  [128]="\u{C7}",
  [129]="\u{FC}",
  [130]="\u{E9}",
  [131]="\u{E2}",
  [132]="\u{E4}",
  [133]="\u{E0}",
  [134]="\u{E5}",
  [135]="\u{E7}",
  [136]="\u{EA}",
  [137]="\u{EB}",
  [138]="\u{E8}",
  [139]="\u{EF}",
  [140]="\u{EE}",
  [141]="\u{EC}",
  [142]="\u{C4}",
  [143]="\u{C5}",
  [144]="\u{C9}",
  [145]="\u{E6}",
  [146]="\u{C6}",
  [147]="\u{F4}",
  [148]="\u{F6}",
  [149]="\u{F2}",
  [150]="\u{FB}",
  [151]="\u{F9}",
  [152]="\u{FF}",
  [153]="\u{D6}",
  [154]="\u{DC}",
  [155]="\u{A2}",
  [156]="\u{A3}",
  [157]="\u{A5}",
  [158]="\u{20A7}",
  [159]="\u{192}",
  [160]="\u{E1}",
  [161]="\u{ED}",
  [162]="\u{F3}",
  [163]="\u{FA}",
  [164]="\u{F1}",
  [165]="\u{D1}",
  [166]="\u{AA}",
  [167]="\u{BA}",
  [168]="\u{BF}",
  [169]="\u{2310}",
  [170]="\u{AC}",
  [171]="\u{BD}",
  [172]="\u{BC}",
  [173]="\u{A1}",
  [174]="\u{AB}",
  [175]="\u{BB}",
  [176]="\u{2591}",
  [177]="\u{2592}",
  [178]="\u{2593}",
  [179]="\u{2502}",
  [180]="\u{2524}",
  [181]="\u{2561}",
  [182]="\u{2562}",
  [183]="\u{2556}",
  [184]="\u{2555}",
  [185]="\u{2563}",
  [186]="\u{2551}",
  [187]="\u{2557}",
  [188]="\u{255D}",
  [189]="\u{255C}",
  [190]="\u{255B}",
  [191]="\u{2510}",
  [192]="\u{2514}",
  [193]="\u{2534}",
  [194]="\u{252C}",
  [195]="\u{251C}",
  [196]="\u{2500}",
  [197]="\u{253C}",
  [198]="\u{255E}",
  [199]="\u{255F}",
  [200]="\u{255A}",
  [201]="\u{2554}",
  [202]="\u{2569}",
  [203]="\u{2566}",
  [204]="\u{2560}",
  [205]="\u{2550}",
  [206]="\u{256C}",
  [207]="\u{2567}",
  [208]="\u{2568}",
  [209]="\u{2564}",
  [210]="\u{2565}",
  [211]="\u{2559}",
  [212]="\u{2558}",
  [213]="\u{2552}",
  [214]="\u{2553}",
  [215]="\u{256B}",
  [216]="\u{256A}",
  [217]="\u{2518}",
  [218]="\u{250C}",
  [219]="\u{2588}",
  [220]="\u{2584}",
  [221]="\u{258C}",
  [222]="\u{2590}",
  [223]="\u{2580}",
  [224]="\u{3B1}",
  [225]="\u{DF}",
  [226]="\u{393}",
  [227]="\u{3C0}",
  [228]="\u{3A3}",
  [229]="\u{3C3}",
  [230]="\u{B5}",
  [231]="\u{3C4}",
  [232]="\u{3A6}",
  [233]="\u{398}",
  [234]="\u{3A9}",
  [235]="\u{3B4}",
  [236]="\u{221E}",
  [237]="\u{3C6}",
  [238]="\u{3B5}",
  [239]="\u{2229}",
  [240]="\u{2261}",
  [241]="\u{B1}",
  [242]="\u{2265}",
  [243]="\u{2264}",
  [244]="\u{2320}",
  [245]="\u{2321}",
  [246]="\u{F7}",
  [247]="\u{2248}",
  [248]="\u{B0}",
  [249]="\u{2219}",
  [250]="\u{B7}",
  [251]="\u{221A}",
  [252]="\u{207F}",
  [253]="\u{B2}",
  [254]="\u{25A0}",
  [255]="\u{A0}",
}
-- CP437 byte -> Unicode char (DF names are CP437 bytes; emitting the
-- mapped char keeps names readable: 0x84 -> ä, not U+0084).
-- Prelude: prepended by the Python side to every helper before execution.
-- Only depends on Lua 5.3 stdlib. Bytes >= 0x80 are mapped through the
-- CP437 table above, so the output is always valid UTF-8 JSON.

local function dfh_escape(s)
  -- gsub-based: a per-byte string.sub loop is pathologically slow in
  -- DFHack's Lua (10k subs ~= 0.8 s), while gsub is ~1 ms for the same.
  -- Class (built by concatenation so the decimal escapes stay readable):
  -- NUL, bytes 1-31, backslash, quote, bytes 127-255.
  s = s:gsub('[%z\1-\31\\"' .. '\127-\255]', function(c)
    local b = c:byte(1)
    if b == 34 then return '\\"'
    elseif b == 92 then return '\\\\'
    elseif b == 10 then return '\\n'
    elseif b == 13 then return '\\r'
    elseif b == 9 then return '\\t'
    elseif b == 8 then return '\\b'
    elseif b == 12 then return '\\f'
    elseif b >= 128 then return CP437[b] or string.format('\\u%04x', b)
    else return string.format('\\u%04x', b) end
  end)
  return '"' .. s .. '"'
end

-- Wrap a list table so it encodes as [] when empty.
local function dfh_arr(t)
  return setmetatable(t or {}, {__dfh_array = true})
end

local dfh_encode
dfh_encode = function(v)
  local tv = type(v)
  if tv == 'nil' then return 'null'
  elseif tv == 'boolean' then return v and 'true' or 'false'
  elseif tv == 'number' then
    if v ~= v or v == math.huge or v == -math.huge then return 'null' end
    if v % 1 == 0 and math.abs(v) < 9007199254740992 then
      return string.format('%d', v)
    end
    return string.format('%.6g', v)
  elseif tv == 'string' then return dfh_escape(v)
  elseif tv == 'table' then
    -- Lists are always built with dfh_arr(); anything else is an object.
    -- (A second pairs pass to detect arrays, and sorting object keys,
    -- cost ~0.1-0.7 ms per table in DFHack's Lua — far more than the
    -- encoding itself on big dumps — so both are skipped. JSON objects
    -- are unordered, so key order does not matter.)
    local mt = getmetatable(v)
    if mt and mt.__dfh_array then
      local parts = {}
      for i = 1, #v do parts[#parts+1] = dfh_encode(v[i]) end
      return '[' .. table.concat(parts, ',') .. ']'
    end
    local parts = {}
    for k, val in pairs(v) do
      if val ~= nil then
        parts[#parts+1] = dfh_escape(tostring(k)) .. ':' .. dfh_encode(val)
      end
    end
    return '{' .. table.concat(parts, ',') .. '}'
  else
    return dfh_escape(tostring(v))
  end
end

-- Print exactly one JSON object. Helpers build `result` then call this.
local function dfh_print(result)
  print(dfh_encode(result))
end

-- Safe field read: pcall a getter, fall back to `default` (nil = omit).
local function dfh_try(fn, default)
  local ok, v = pcall(fn)
  if ok then return v end
  return default
end

-- Relations for one unit (citizens): family from relationship_ids
-- (indexed by unit_relationship_type — verified live: the named
-- slots resolve, and probe_unit.lua already reads .Pet) + the
-- histfig social web (histfig_links, type from the link's _type
-- subtype, e.g. histfig_hf_link_deityst -> "deity").
-- hf_to_unit maps histfig id -> the fort unit with that histfig
-- (built once per collect by the caller). Each relation:
-- {type, name, histfig_id, unit_id (nil when not in the fort),
--  in_fort, strength (histfig link strength, nil for family)}.
-- Family slots read: Pet, Spouse, Mother, Father, Lover — the
-- single-valued person relations in relationship_ids. The other
-- slots are transient/mechanical (LastAttacker, GroupLeader,
-- Draggee, Dragger, RiderMount) and are not relations in the
-- diary's sense. Verified live 2026-11-27: the fort's 7 dwarves
-- each carry one deity link (Rakas) and no family links yet
-- (all relationship_ids slots -1); person-link subtype names are
-- derived generically from _type, so a spouse/friend link reads
-- the same way when one appears.
local function dfh_relations(u, hf_to_unit)
  local rels = dfh_arr()
  local seen = {}
  local function add(reltype, hfid, strength)
    if hfid == nil or hfid == -1 then return end
    local key = reltype .. ":" .. tostring(hfid)
    if seen[key] then return end
    seen[key] = true
    local target = hf_to_unit and hf_to_unit[hfid] or nil
    local name = nil
    if target then
      name = dfhack.TranslateName(dfhack.units.getVisibleName(target))
    else
      local hf = dfh_try(function()
        return df.historical_figure.find(hfid) end, nil)
      if hf then name = dfhack.TranslateName(hf.name) end
    end
    rels[#rels+1] = {
      type = reltype,
      name = name,
      histfig_id = hfid,
      unit_id = target and target.id or nil,
      in_fort = target ~= nil,
      strength = strength,
    }
  end
  for _, slot in ipairs({"Pet", "Spouse", "Mother", "Father",
                         "Lover"}) do
    local hfid = dfh_try(function()
      return u.relationship_ids[slot] end, nil)
    add(string.lower(slot), hfid, nil)
  end
  local hf = dfh_try(function()
    return df.historical_figure.find(u.hist_figure_id) end, nil)
  if hf then
    for _, link in ipairs(hf.histfig_links) do
      local subtype = dfh_try(function()
        return tostring(link._type) end, "")
      -- "<type: histfig_hf_link_deityst>" -> "deity". The subtype
      -- name ends in "st" (df-structures struct-subtype suffix);
      -- anything that does not match keeps its raw subtype string
      -- rather than being dropped.
      local rtype = subtype:match("histfig_hf_link_(.+)st>$")
        or subtype
      local target = dfh_try(function()
        return link.target_hf end, nil)
      local strength = dfh_try(function()
        return link.link_strength end, nil)
      add(rtype, target, strength)
    end
  end
  return rels
end

-- Social ties from hf.info.relationships.hf_visual: the friendship /
-- grudge layer the relationship_ids slots and histfig_links do NOT
-- carry. Each entry is one other historical figure this dwarf has met:
-- love (-100..100; >=50 friend, >=75 close friend, >=100 kindred
-- spirit; <=-50 disliked, <=-75 hated, -100 pure hate), trust, fear,
-- respect, loyalty, familiarity, meet_count, and first/last meeting
-- years. Verified in the DFHack r8 structure definitions
-- (HistoricalFigureRelationships.hf_visual, reached via
-- histfig.info.relationships). Added 2026-11-27: the diary audit
-- found the harness blind to friendships, grudges, and meet counts —
-- exactly the material the diary needs. Every field read is guarded:
-- a missing info pointer or an unreadable vector yields an empty
-- list, never an error.
local function dfh_social(u, hf_to_unit)
  local out = dfh_arr()
  local hf = dfh_try(function()
    return df.historical_figure.find(u.hist_figure_id) end, nil)
  if not hf then return out end
  local rels = dfh_try(function()
    return hf.info.relationships end, nil)
  if not rels then return out end
  local visual = dfh_try(function() return rels.hf_visual end, nil)
  if not visual then return out end
  for _, v in ipairs(visual) do
    local hfid = dfh_try(function() return v.histfig_id end, nil)
    if hfid ~= nil and hfid ~= -1 then
      local target = hf_to_unit and hf_to_unit[hfid] or nil
      local name = nil
      if target then
        name = dfhack.TranslateName(dfhack.units.getVisibleName(target))
      else
        local thf = dfh_try(function()
          return df.historical_figure.find(hfid) end, nil)
        if thf then name = dfhack.TranslateName(thf.name) end
      end
      out[#out+1] = {
        histfig_id = hfid,
        unit_id = target and target.id or nil,
        name = name,
        in_fort = target ~= nil,
        love = dfh_try(function() return v.love end, nil),
        trust = dfh_try(function() return v.trust end, nil),
        fear = dfh_try(function() return v.fear end, nil),
        respect = dfh_try(function() return v.respect end, nil),
        loyalty = dfh_try(function() return v.loyalty end, nil),
        familiarity = dfh_try(function() return v.familiarity end, nil),
        meet_count = dfh_try(function() return v.meet_count end, nil),
        last_meet_year = dfh_try(
          function() return v.last_meet_year end, nil),
        first_year = dfh_try(function() return v.first_year end, nil),
      }
    end
  end
  return out
end

-- Personality facets from soul.personality.traits: the 50 int16
-- values (df-structures UnitPersonality, static_array 50), 0-100 with
-- 50 neutral. The facet name comes from the df.personality_facet_type
-- enum; a missing enum yields the numeric fallback "facet_<i>".
-- Every element read is guarded.
local function dfh_traits(u)
  local out = dfh_arr()
  local soul = dfh_try(function() return u.status.current_soul end, nil)
  if not soul then return out end
  local traits = dfh_try(function()
    return soul.personality.traits end, nil)
  if not traits then return out end
  for i = 0, 49 do
    local val = dfh_try(function() return traits[i] end, nil)
    if val ~= nil then
      local fname = dfh_try(function()
        return tostring(df.personality_facet_type[i]) end, nil)
      out[#out+1] = {facet = fname or ("facet_" .. tostring(i)),
                      value = val}
    end
  end
  return out
end

-- Recent emotions from soul.personality.emotions: each entry is one
-- felt emotion (type, strength, thought, severity, year, year_tick).
-- The list is short (a handful at most) and is emitted whole; the
-- Python side caps what the diary feed renders. Guarded throughout.
local function dfh_emotions(u)
  local out = dfh_arr()
  local soul = dfh_try(function() return u.status.current_soul end, nil)
  if not soul then return out end
  local emos = dfh_try(function()
    return soul.personality.emotions end, nil)
  if not emos then return out end
  for _, e in ipairs(emos) do
    -- type/thought arrive as raw numbers; resolve them through the
    -- enum tables (the units.lua pattern). tostring of the indexed
    -- value is the plain name ("ANNOYANCE", "Rain"). Live-verified
    -- 2026-11-27: df.emotion_type and df.unit_thought_type exist;
    -- strength/severity read 0 on every live emotion, so the feed
    -- renders type + thought only, never a strength.
    local etype = dfh_try(function()
      return tostring(df.emotion_type[e.type]) end, nil)
    local thought = dfh_try(function()
      return tostring(df.unit_thought_type[e.thought]) end, nil)
    out[#out+1] = {
      type = etype or ("emotion_" .. tostring(e.type)),
      strength = dfh_try(function() return e.strength end, nil),
      thought = thought or ("thought_" .. tostring(e.thought)),
      severity = dfh_try(function() return e.severity end, nil),
      year = dfh_try(function() return e.year end, nil),
      year_tick = dfh_try(function() return e.year_tick end, nil),
    }
  end
  return out
end

-- Generic scalar dump of a DF struct: all number/string/boolean fields.
-- Used for structs with no live instance to probe (manager orders,
-- announcements, reports are empty on a fresh fort).
local function dfh_dump(o)
  local out = {}
  local ok, _ = pcall(function()
    for k, v in pairs(o) do
      local tv = type(v)
      if tv == 'number' or tv == 'string' or tv == 'boolean' then
        out[tostring(k)] = v
      end
    end
  end)
  if not ok then return {} end
  return out
end
