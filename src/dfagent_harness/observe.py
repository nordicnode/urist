"""Read-only observation layer for the DF Agent Harness (phase 1).

Collects game state from a live Dwarf Fortress 0.47.05 + DFHack 0.47.05-r8
game over the existing :mod:`dfhack_rpc` transport and assembles one
structured state document (JSON-serialisable dict), plus a compact
human-readable text rendering of the same state — the text form is what
an LLM agent reads first.

Lua helpers live in :mod:`dfagent_harness.lua` (``*.lua`` files next to
this module). Each helper prints exactly one JSON object via
``RunCommand("lua", ...)``; the Python side loads the shared JSON
prelude (``lua/json.lua``) + the helper and parses the printed text.
Helpers are defensive: on any Lua error they print
``{"ok": false, "error": ...}`` and the section is recorded under
``errors`` instead of failing the whole observation.

Sections (``--section`` filter values; ``all`` is the default):
``status``, ``units``, ``stocks``, ``items``, ``buildings``, ``jobs``,
``reports``, ``map``, ``designations``. ``stocks`` and ``items`` come
from one Lua call (``stocks.lua`` returns both). ``designations`` does
a full map-block scan (~4 s) and is only collected when requested.

Read-only: nothing here designates, orders, builds, or otherwise
changes game state. The only RPC calls are GetVersionInfo, GetPauseState
and RunCommand("lua", ...) reads.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from dfhack_rpc import DFHackClient

__all__ = [
    "SECTIONS",
    "FAST_SECTIONS",
    "collect",
    "render_text",
    "measure_fps",
]

#: All section names, in the order they are collected / rendered.
SECTIONS = (
    "status",
    "units",
    "stocks",
    "items",
    "buildings",
    "jobs",
    "reports",
    "map",
    "designations",
)

#: Sections collected by default (``all`` minus the slow block scan).
FAST_SECTIONS = tuple(s for s in SECTIONS if s != "designations")

#: Lua file that backs each section. ``stocks`` and ``items`` share one.
_SECTION_LUA: dict[str, str] = {
    "status": "status.lua",
    "units": "units.lua",
    "stocks": "stocks.lua",
    "items": "stocks.lua",
    "buildings": "buildings.lua",
    "jobs": "jobs.lua",
    "reports": "reports.lua",
    "map": "map.lua",
    "designations": "designations.lua",
}

#: Which top-level keys each Lua file's JSON provides.
_LUA_PROVIDES: dict[str, tuple[str, ...]] = {
    "status.lua": ("status",),
    "units.lua": ("units",),
    "units_lite.lua": ("units",),
    "stocks.lua": ("stocks", "items"),
    "buildings.lua": ("buildings",),
    "jobs.lua": ("jobs",),
    "reports.lua": ("reports",),
    "map.lua": ("map",),
    "designations.lua": ("designations",),
}

_LUA_DIR = Path(__file__).resolve().parent / "lua"

SCHEMA_VERSION = 1


def _load_lua(name: str) -> str:
    """Shared JSON prelude + one helper, as a single Lua chunk."""
    prelude = (_LUA_DIR / "json.lua").read_text()
    helper = (_LUA_DIR / name).read_text()
    return prelude + "\n" + helper


def run_section(client: DFHackClient, section: str,
                timeout: float = 30.0, lite_units: bool = False
                ) -> dict[str, Any]:
    """Run one section's Lua helper; return its parsed JSON dict.

    Returns ``{"ok": False, "section": ..., "error": ...}`` (never raises)
    when the helper fails or its output is not JSON — the caller records
    it under ``errors``.

    ``lite_units`` swaps the full ``units.lua`` helper for the cheap
    ``units_lite.lua`` one (same ``units`` shape, only the fields the
    event diff detector reads). Used by the event poller's fast tick.
    """
    lua_file = _SECTION_LUA[section]
    if lite_units and section == "units":
        lua_file = "units_lite.lua"
    try:
        code = _load_lua(lua_file)
        out = client.run_lua_json(code, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - surfaced as section error
        return {"ok": False, "section": section, "error": str(exc)}
    if not isinstance(out, dict):
        return {"ok": False, "section": section,
                "error": f"helper returned non-object JSON: {out!r:.200}"}
    return out


def measure_fps(client: DFHackClient, sample_seconds: float = 1.0) -> Optional[float]:
    """Estimate game FPS from the tick counter over a wall-clock window.

    DF advances ``cur_year_tick`` once per frame while unpaused, so
    ticks/second ~= FPS. Returns None when the game is paused (ticks do
    not advance) or the reads fail. Costs ``sample_seconds`` of wall time;
    only call when the caller explicitly wants FPS.
    """
    code = "print(df.global.cur_year_tick)"
    try:
        t0 = int(client.run_lua(code).strip())
    except Exception:
        return None
    time.sleep(sample_seconds)
    try:
        t1 = int(client.run_lua(code).strip())
    except Exception:
        return None
    if t1 <= t0:
        return None  # paused (or stalled) during the sample
    return (t1 - t0) / sample_seconds


def collect(client: DFHackClient, sections: tuple[str, ...] = FAST_SECTIONS,
            timeout: float = 30.0, fps: bool = False,
            lite_units: bool = False) -> dict[str, Any]:
    """Collect the requested sections into one state document.

    ``sections`` may contain ``"all"``. Unknown names raise ValueError.
    Always includes ``meta`` (versions, timing) and ``errors`` (possibly
    empty). Sections that fail still appear in ``errors``; the rest of
    the document is unaffected. ``lite_units`` (see :func:`run_section`)
    uses the cheap units helper for the ``units`` section.
    """
    if "all" in sections:
        # "all" = fast sections; designations only when named explicitly.
        wanted = list(FAST_SECTIONS)
        extra = [s for s in sections if s != "all"]
    else:
        wanted = []
        extra = list(sections)
    for s in extra:
        if s not in SECTIONS:
            raise ValueError(f"unknown section: {s!r} "
                             f"(choose from {', '.join(SECTIONS)})")
        if s not in wanted:
            wanted.append(s)

    started = time.time()
    meta: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "collected_at": int(time.time()),
        "fps": None,
        "fps_measured": False,
    }
    try:
        meta["version"] = client.get_version()
    except Exception as exc:  # noqa: BLE001 - version is best-effort
        meta["version"] = {"error": str(exc)}

    state: dict[str, Any] = {"meta": meta, "errors": []}
    ran: dict[str, dict[str, Any]] = {}
    for section in wanted:
        lua_file = _SECTION_LUA[section]
        if lite_units and section == "units":
            lua_file = "units_lite.lua"
        if lua_file in ran:
            out = ran[lua_file]
        else:
            out = run_section(client, section, timeout=timeout,
                              lite_units=lite_units)
            ran[lua_file] = out
        if not out.get("ok", False):
            state["errors"].append(
                {"section": section,
                 "error": out.get("error", "unknown helper failure")})
            continue
        for key in _LUA_PROVIDES[lua_file]:
            # A shared file (stocks.lua) may provide a section that was
            # not requested; only expose requested keys.
            if key in wanted and key in out:
                state[key] = out[key]

    if fps:
        # Only meaningful unpaused; measure after the (fast) sections.
        paused = None
        try:
            status = state.get("status") or {}
            paused = status.get("paused")
        except Exception:
            paused = None
        if paused is False:
            value = measure_fps(client)
            if value is not None:
                meta["fps"] = round(value, 1)
                meta["fps_measured"] = True

    meta["took_ms"] = round((time.time() - started) * 1000)
    return state


# -- text rendering ------------------------------------------------------

def _fmt_pos(pos: Optional[list]) -> str:
    if not pos:
        return "?"
    return f"[{pos[0]},{pos[1]},{pos[2]}]"


def _worst_needs(unit: dict[str, Any], n: int = 3) -> str:
    needs = unit.get("needs") or []
    if not needs:
        return "-"
    worst = sorted(needs, key=lambda x: x.get("focus", 0))[:n]
    return ", ".join(
        f"{w.get('need')} focus {w.get('focus')}" for w in worst)


def render_text(state: dict[str, Any]) -> str:
    """Compact human-readable rendering of a state document from collect().

    Dense but complete: counts first, short lists, no boilerplate. Used
    as the first thing an LLM agent reads; the JSON is the authority.
    """
    lines: list[str] = []
    meta = state.get("meta") or {}
    status = state.get("status") or {}
    ver = meta.get("version") or {}

    if status:
        lines.append(
            f"{status.get('fort_name') or status.get('save_dir') or 'Fort'} "
            f"— {status.get('date')} {status.get('season')}, "
            f"tick {status.get('year_tick')}, "
            f"{'PAUSED' if status.get('paused') else 'RUNNING'}, "
            f"focus {status.get('focus')}, "
            f"DF {ver.get('dwarf_fortress_version', '?')} / "
            f"DFHack {ver.get('dfhack_version', '?')}")
        pop = status.get("population") or {}
        lines.append(
            f"Pop: {pop.get('citizens')} citizens "
            f"({pop.get('jobless')} jobless), {pop.get('animals')} animals, "
            f"{pop.get('total_active_units')} units active, "
            f"{pop.get('threats')} threats")
    if meta.get("fps_measured"):
        lines.append(f"FPS: {meta.get('fps')}")
    elif meta.get("fps") is None and status.get("paused"):
        lines.append("FPS: n/a (paused)")

    stocks = state.get("stocks")
    if stocks:
        lines.append(
            f"Stocks: drink {stocks.get('drink_units')}u "
            f"({stocks.get('drink_stacks')} stacks), "
            f"food {stocks.get('food_units')}u "
            f"({stocks.get('food_stacks')} stacks), "
            f"seeds {stocks.get('seeds_units')}, "
            f"wood {stocks.get('wood_units')}, "
            f"stone {stocks.get('stone_units')}u, "
            f"cloth {stocks.get('cloth_units')}, "
            f"thread {stocks.get('thread_units')}, "
            f"metal bars {stocks.get('metal_bar_units')}, "
            f"barrels {stocks.get('barrels')}, bins {stocks.get('bins')}")
        mats = stocks.get("by_material") or []
        if mats:
            lines.append("  by material: " + ", ".join(
                f"{m['type']} {m['material']} x{m['units']}"
                for m in mats[:12]))

    items = state.get("items")
    if items:
        by_type = items.get("by_type") or []
        lines.append(
            f"Items: {items.get('total_stacks')} stacks / "
            f"{items.get('total_units')} units in play; "
            + ", ".join(
                f"{e['type']} {e['units']}" for e in by_type[:15]))

    units = state.get("units")
    if units:
        lines.append(f"Citizens ({units.get('citizen_count')}):")
        for u in units.get("citizens") or []:
            job = u.get("job")
            job_s = (f"{job['type']} @{_fmt_pos(job.get('pos'))}"
                     if job else "idle")
            stress = u.get("stress") or {}
            ctr = u.get("counters") or {}
            skills = u.get("skills") or []
            top_skills = ", ".join(
                f"{s['skill']} {s['rating']}" for s in skills[:4])
            lines.append(
                f"  {u.get('name')} ({u.get('profession')}, "
                f"{u.get('age'):.0f}y, "
                f"{'F' if u.get('sex') == 0 else 'M'}) "
                f"{job_s} @{_fmt_pos(u.get('pos'))} | "
                f"stress {stress.get('category')}/6 "
                f"(lvl {stress.get('level')}) | "
                f"hunger {ctr.get('hunger')} thirst {ctr.get('thirst')} "
                f"sleep {ctr.get('sleepiness')} | "
                f"mood {u.get('mood_name')} | "
                f"wounds {u.get('wound_count')} | "
                f"needs: {_worst_needs(u)}"
                + (f" | skills: {top_skills}" if top_skills else ""))
            labs = u.get("labors") or []
            if labs:
                lines.append(f"    labors: {', '.join(labs)}")
        hostiles = units.get("hostiles") or []
        if hostiles:
            lines.append("Hostiles:")
            for h in hostiles:
                lines.append(
                    f"  {h.get('name')} ({h.get('race')}) "
                    f"@{_fmt_pos(h.get('pos'))}")

    buildings = state.get("buildings")
    if buildings:
        summary = buildings.get("summary") or []
        lines.append(
            f"Buildings ({buildings.get('count')}): "
            + (", ".join(f"{s['type']} x{s['count']}" for s in summary)
               or "none"))
        for b in (buildings.get("list") or [])[:20]:
            lines.append(
                f"  {b.get('type')} #{b.get('id')} "
                f"@{_fmt_pos(b.get('center'))} "
                f"stage {b.get('construction_stage')} "
                f"jobs {b.get('jobs')} items {b.get('contained_items')}")

    jobs = state.get("jobs")
    if jobs:
        counts = jobs.get("counts_by_type") or []
        lines.append(
            f"Jobs queued: {jobs.get('count')} "
            + (f"({', '.join(f'{c['type']} x{c['count']}' for c in counts)})"
               if counts else "(none)"))
        for j in (jobs.get("list") or [])[:15]:
            lines.append(
                f"  #{j.get('id')} {j.get('type')} "
                f"@{_fmt_pos(j.get('pos'))}")
        orders = jobs.get("manager_orders") or []
        lines.append(f"Manager orders: {jobs.get('manager_order_count')}")
        for o in orders[:10]:
            lines.append(
                f"  {o.get('job_type_name') or o.get('job_type')} "
                f"left {o.get('amount_left')}/{o.get('amount_total')}")

    reports = state.get("reports")
    if reports:
        anns = reports.get("announcements") or []
        lines.append(
            f"Announcements ({reports.get('announcement_count')} total, "
            f"last {len(anns)}):")
        for a in anns:
            lines.append(f"  [{a.get('year')}-{a.get('time')}] "
                         f"{a.get('text')}")
        reps = reports.get("reports") or []
        lines.append(
            f"Combat reports ({reports.get('report_count')} total, "
            f"last {len(reps)}):")
        for r in reps:
            lines.append(f"  {r.get('text')}")

    map_s = state.get("map")
    if map_s:
        lines.append(
            f"Map: {map_s.get('size_tiles')} tiles, "
            f"{map_s.get('z_levels')} z-levels, "
            f"region {map_s.get('region_x')},{map_s.get('region_y')}, "
            f"plants {map_s.get('plants_total')} "
            f"(trees {map_s.get('trees')}, shrubs {map_s.get('shrubs')})")

    des = state.get("designations")
    if des:
        by_type = des.get("dig_by_type") or []
        dig_s = ", ".join(f"{e['type']} x{e['count']}" for e in by_type)
        lines.append(
            f"Designations: {des.get('dig_total')} dig tiles "
            f"({dig_s or 'none'}), "
            f"{des.get('smooth_total')} smooth, "
            f"scan {des.get('scan_seconds'):.1f}s")

    for err in state.get("errors") or []:
        lines.append(
            f"SECTION FAILED [{err.get('section')}]: {err.get('error')}")

    return "\n".join(lines) + "\n"
