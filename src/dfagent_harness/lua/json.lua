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
