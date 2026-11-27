"""Placement system tests (offline, fake client).

The placement system (Mikey directive 2026-11-26): the harness
computes verified-free sites and the model never guesses
coordinates. A site is verified only when free (terrain,
occupancy, plants, units, overlap) AND reachable (canWalkBetween
from the fort centre). A build failure names a verified
alternative, not just "gather the blocker or move".
"""
from __future__ import annotations

import pytest

from dfagent_harness import placement


class _FakeClient:
    """Minimal DFHack client stub answering run_lua_json.

    The real transport is run_lua_json(code, timeout=...): the
    helpers are loaded by name (_run_helper / _helper_or_fail) and
    the code string contains the helper name. slice.lua returns
    {"slice": {"grid": [...], ...}}; probe_site.lua returns the
    probe dict directly.
    """

    def __init__(self, slices=None, probe_results=None):
        # slices: {(x0, y0, z, x1, y1): [grid rows]}; probe_results:
        # {(x, y, z): probe dict}
        self.slices = slices or {}
        self.probe_results = probe_results or {}
        self.lua_calls = []

    def run_lua_json(self, code, timeout=None):
        self.lua_calls.append(code)
        # Params are embedded as PARAMS = {x = 97, y = 95, ...}
        # (see actions._load_lua). Parse that block, not the
        # helper body.
        import re
        params = {}
        m = re.search(r"PARAMS\s*=\s*\{([^}]*)\}", code, re.S)
        if m:
            for key, val in re.findall(r"(\w+)\s*=\s*([\d.]+)",
                                       m.group(1)):
                params[key] = int(float(val))
        if "probe_site" in code:
            pos = (params.get("x", 0), params.get("y", 0),
                   params.get("z", 0))
            result = self.probe_results.get(pos)
            if result is None:
                return {"ok": True, "free": True, "reachable": True,
                        "problems": []}
            return result
        if "slice" in code:
            x0, y0, z = (params.get("x0", 0), params.get("y0", 0),
                         params.get("z", 0))
            x1, y1 = params.get("x1", 0), params.get("y1", 0)
            key = (x0, y0, z, x1, y1)
            grid = self.slices.get(key)
            if grid is None:
                # Default: all open floor over the requested rect.
                w, h = x1 - x0 + 1, y1 - y0 + 1
                grid = ["." * w for _ in range(h)]
            return {"ok": True,
                    "slice": {"grid": grid, "markers": [],
                              "bbox": {"x0": x0, "y0": y0, "z": z,
                                       "x1": x1, "y1": y1},
                              "counts": [], "hidden": [],
                              "above": None, "below": None,
                              "cost_ms": 1}}
        return {}


def _free_rect_slice(x0, y0, x1, y1):
    """An ASCII slice of all open floor ('.') for the rect."""
    w = x1 - x0 + 1
    h = y1 - y0 + 1
    return "\n".join(["." * w for _ in range(h)])


def test_find_sites_returns_verified_free_and_reachable():
    client = _FakeClient()
    client.slices[(90, 90, 175, 104, 104)] = _free_rect_slice(
        90, 90, 104, 104)
    out = placement.find_sites(
        client, "workshop", 3, 3, centre=(97, 97, 175),
        surface_z=175, from_pos=(97, 97, 175), limit=3)
    assert len(out["sites"]) == 3
    for site in out["sites"]:
        # Verified means free AND reachable (free is implied by
        # being in the verified list — there is no "free" key).
        assert site["reachable"] is True
        assert site["pos"][2] == 175
        assert "why" in site and site["why"]


def test_find_sites_rejects_unreachable_site():
    client = _FakeClient()
    client.slices[(90, 90, 175, 104, 104)] = _free_rect_slice(
        90, 90, 104, 104)
    # Every probe says unreachable: no verified sites, and the
    # blocked list names the reason.
    client.probe_results = {
        (x, y, 175): {"ok": True, "free": True, "reachable": False,
                      "problems": ["no path from (97, 97, 175)"]}
        for x in range(90, 105) for y in range(90, 105)}
    out = placement.find_sites(
        client, "workshop", 3, 3, centre=(97, 97, 175),
        surface_z=175, from_pos=(97, 97, 175), limit=3)
    assert out["sites"] == []
    assert out["blocked"], "unreachable candidates must be reported"
    assert "no path" in out["blocked"][0]["reason"]


def test_find_sites_no_from_pos_marks_reachability_unchecked():
    client = _FakeClient()
    client.slices[(90, 90, 175, 104, 104)] = _free_rect_slice(
        90, 90, 104, 104)
    out = placement.find_sites(
        client, "workshop", 3, 3, centre=(97, 97, 175),
        surface_z=175, from_pos=None, limit=3)
    # Without a from-point the finder must NOT claim reachability:
    # no site is verified, and the result says so.
    assert out["sites"] == []
    assert out["reason"] == "reachability_unchecked"


def test_verify_site_free_and_reachable():
    client = _FakeClient()
    client.slices[(90, 90, 175, 104, 104)] = _free_rect_slice(
        90, 90, 104, 104)
    out = placement.verify_site(
        client, "workshop", (97, 96, 175), 3, 3,
        from_pos=(97, 97, 175))
    assert out["free"] is True
    assert out["reachable"] is True


def test_verify_site_blocked_by_shrub():
    client = _FakeClient()
    client.slices[(90, 90, 175, 104, 104)] = _free_rect_slice(
        90, 90, 104, 104)
    client.probe_results[(96, 95, 175)] = {
        "ok": True, "free": False, "reachable": True,
        "problems": ["SHRUB at 96,95"]}
    out = placement.verify_site(
        client, "workshop", (96, 95, 175), 3, 3,
        from_pos=(97, 97, 175))
    assert out["free"] is False
    assert out["reachable"] is True
    assert any("SHRUB" in r for r in out["problems"])


def test_format_compact_token_light():
    sites = {
        "workshop": [
            {"pos": (97, 96, 175), "kind": "workshop",
             "width": 3, "height": 3, "reachable": True,
             "why": "nearest the fort"},
            {"pos": (96, 96, 175), "kind": "workshop",
             "width": 3, "height": 3, "reachable": True,
             "why": "1 tile west of the fort"},
        ],
        "stockpile": [
            {"pos": (93, 87, 176), "kind": "stockpile",
             "width": 5, "height": 5, "reachable": True,
             "why": "11 tiles north west of the fort"},
        ],
    }
    text = placement.format_compact(sites)
    assert "97,96,175" in text
    assert "93,87,176" in text
    assert "nearest the fort" in text
    # Compact: a handful of lines, not a dump.
    assert len(text.splitlines()) <= 6


def test_site_why_directions():
    centre = (97, 97)
    site = {"pos": (97, 96, 175)}
    assert "nearest" in placement.site_why(site, centre)
    site = {"pos": (100, 97, 175)}
    assert "east" in placement.site_why(site, centre)
    site = {"pos": (97, 90, 175)}
    assert "north" in placement.site_why(site, centre)


def test_placement_kinds_cover_all():
    # Every kind Mikey named (workshop, stockpile, zone,
    # farm_plot, furniture, trap, room) is in the registry.
    for kind in ("workshop", "stockpile", "zone", "farm_plot",
                 "furniture", "trap", "room"):
        assert kind in placement.PLACEMENT_KINDS
        assert placement.PLACEMENT_KINDS[kind]["default_size"]


def test_alternative_site_names_verified_alternative():
    from dfagent_harness import actions
    # A placement cache with a verified workshop site; the failed
    # site (96,95,175) is blocked by a shrub. The alternative must
    # be a DIFFERENT, verified site — never the failed one.
    cache = {
        "workshop": [
            {"pos": (97, 96, 175), "kind": "workshop",
             "width": 3, "height": 3, "reachable": True,
             "why": "nearest the fort"},
            {"pos": (96, 95, 175), "kind": "workshop",
             "width": 3, "height": 3, "reachable": True,
             "why": "nearest the fort"},
        ],
        "from": (97, 97, 175),
    }
    alt = actions._alternative_site(
        None, "workshop", 3, 3, (96, 95, 175), cache,
        from_pos=(97, 97, 175))
    assert alt is not None
    assert "(97,96,175)" in alt
    assert "(96,95,175)" not in alt


def test_alternative_site_none_when_no_verified_site():
    from dfagent_harness import actions
    # An empty cache says so explicitly — never an unverified site.
    alt = actions._alternative_site(
        None, "workshop", 3, 3, (96, 95, 175), {}, from_pos=None)
    assert alt is None or "no verified" in alt.lower() or \
        "cannot" in alt.lower()


def test_planner_no_build_when_sites_none():
    from dfagent_harness.planner import decide
    import copy
    import json
    from pathlib import Path
    # With no sites, the planner must NOT emit a build decision
    # (the stale Athelunol WORKSHOP_SITES fallback is gone). The
    # state comes from the real observe fixture, with drink low
    # enough that the old code would have tried to build a still.
    fixture = (Path(__file__).resolve().parent / "fixtures"
               / "observe-athelunol.json")
    state = json.loads(fixture.read_text())
    state["stocks"]["drink_units"] = 5
    state["buildings"]["list"] = []
    state["buildings"]["summary"] = []
    state["buildings"]["count"] = 0
    decisions = decide(state, sites=None)
    build_actions = [d for d in decisions
                     if d.action in ("build_workshop",
                                     "build_farm_plot",
                                     "build_furniture",
                                     "create_stockpile")]
    assert build_actions == []


def test_assembler_placement_section():
    from dfagent_harness import assembler
    import copy
    import json
    from pathlib import Path
    fixture = (Path(__file__).resolve().parent / "fixtures"
               / "observe-athelunol.json")
    state = json.loads(fixture.read_text())
    placement_cache = {
        "workshop": [
            {"pos": (97, 96, 175), "kind": "workshop",
             "width": 3, "height": 3, "reachable": True,
             "why": "nearest the fort"},
        ],
        "stockpile": [
            {"pos": (93, 87, 176), "kind": "stockpile",
             "width": 5, "height": 5, "reachable": True,
             "why": "11 tiles north west of the fort"},
        ],
    }
    snap = assembler.assemble(state, placement=placement_cache)
    assert "placement" in snap["sections"]
    text = snap["sections"]["placement"]
    assert "97,96,175" in text
    assert "93,87,176" in text


def test_placement_short_form_carries_first_site_per_kind():
    # M1 run #10 ticks 3 and 6 stalled asking for verified free
    # sites the model had already been given on tick 1: the
    # placement short form ("16 verified sites") was just a count,
    # so the coordinates were lost when the section diffed to
    # "unchanged". The short form now carries the first site per
    # kind, compactly.
    from dfagent_harness.assembler import _placement
    placement_cache = {
        "workshop": [
            {"pos": (95, 108, 175), "kind": "workshop",
             "width": 3, "height": 3, "reachable": True,
             "why": "nearest the fort"},
            {"pos": (96, 103, 175), "kind": "workshop",
             "width": 3, "height": 3, "reachable": True,
             "why": "4 tiles north east of the fort"},
        ],
        "stockpile": [
            {"pos": (93, 86, 176), "kind": "stockpile",
             "width": 5, "height": 5, "reachable": True,
             "why": "19 tiles north of the fort"},
        ],
    }
    _text, short = _placement(placement_cache)
    assert "workshop (95,108,175)" in short
    assert "stockpile (93,86,176)" in short
    assert short != "3 verified sites"


def test_assembler_placement_cache_with_centre_and_from():
    # The daemon's placement cache also carries "centre" and
    # "from" (lists of ints, not site lists). The assembler must
    # ignore them — passing them to format_compact used to crash
    # the snapshot with "'int' object has no attribute 'get'"
    # (2026-11-27, live).
    from dfagent_harness import assembler
    import json
    from pathlib import Path
    fixture = (Path(__file__).resolve().parent / "fixtures"
               / "observe-athelunol.json")
    state = json.loads(fixture.read_text())
    placement_cache = {
        "workshop": [
            {"pos": (97, 96, 175), "kind": "workshop",
             "width": 3, "height": 3, "reachable": True,
             "why": "nearest the fort"},
        ],
        "centre": [97, 97, 175],
        "from": [97, 97, 175],
    }
    snap = assembler.assemble(state, placement=placement_cache)
    assert "placement" in snap["sections"]
    text = snap["sections"]["placement"]
    assert "97,96,175" in text
    assert "centre" not in text.lower()


def test_placement_anchor_prefers_buildings():
    # The anchor is the buildings' centroid + most common building
    # z, with the first citizen as the from-point (walkable ground).
    # The old derivation (Surface bbox centre + lowest citizen z)
    # gave (95,95,176) and 0 sites on the hilly map (2026-11-27).
    state = {
        "buildings": {"list": [
            {"center": [93, 105, 175]},
            {"center": [95, 105, 175]},
        ]},
        "units": {"citizens": [
            {"pos": [81, 74, 178]},
            {"pos": [93, 100, 176]},
        ]},
    }
    centre, surface_z, from_pos = placement.placement_anchor(state)
    assert centre == (94, 105)
    assert surface_z == 175
    # The from-point is the citizen NEAREST the building centroid
    # (93,100), not the first citizen in the list (81,74).
    assert from_pos == (93, 100, 176)


def test_placement_anchor_falls_back_to_citizen():
    # No buildings: the first citizen's position is the anchor
    # (walkable ground by definition).
    state = {
        "buildings": {"list": []},
        "units": {"citizens": [{"pos": [97, 97, 175]}]},
    }
    centre, surface_z, from_pos = placement.placement_anchor(state)
    assert centre == (97, 97)
    assert surface_z == 175
    assert from_pos == (97, 97, 175)


def test_placement_anchor_falls_back_to_areas():
    # No buildings, no citizens: the Surface bbox centre + the
    # areas' surface_z (the old behaviour).
    areas = {"surface_z": 175,
             "areas": [{"kind": "surface",
                        "bbox": {"x0": 0, "y0": 0, "x1": 191,
                                 "y1": 191}}]}
    centre, surface_z, from_pos = placement.placement_anchor(
        {"buildings": {"list": []}, "units": {"citizens": []}}, areas)
    assert centre == (95, 95)
    assert surface_z == 175
    assert from_pos == (95, 95, 175)


def test_placement_anchor_raises_with_nothing():
    with pytest.raises(ValueError):
        placement.placement_anchor(
            {"buildings": {"list": []}, "units": {"citizens": []}})
