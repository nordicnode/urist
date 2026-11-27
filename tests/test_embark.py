"""Offline tests for the embark module (no game needed).

Covers the pure parts: profile formatting and round-trip, fileresult
file parsing, the overlay viewport math (shared with the Lua helper),
screen-to-world conversion, and the scan sweep positions. The live
embark path is tested in tests/test_embark_live.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import embark  # noqa: E402


def test_profile_has_all_fields_in_order(tmp_path):
    path = embark.write_profile(tmp_path, dict(embark.M2_PROFILE))
    lines = path.read_text().splitlines()
    # 51 fields + 4 civ lines (region3's set).
    assert len(lines) == len(embark.PROFILE_FIELDS) + 4
    fields = [ln[1:ln.index(":")] for ln in lines[:len(embark.PROFILE_FIELDS)]]
    assert fields == [f for f, _ in embark.PROFILE_FIELDS]
    # Every line is [Field:Value] with no stray whitespace.
    for ln in lines:
        assert ln.startswith("[") and ln.endswith("]")
        assert ": " not in ln


def test_profile_m2_values(tmp_path):
    embark.write_profile(tmp_path, dict(embark.M2_PROFILE))
    got = embark.read_profile(tmp_path)
    assert got["Metal 1"] == "ZINC"
    assert got["X Dimension"] == "4"
    assert got["Y Dimension"] == "4"
    assert got["Min River"] == "Brook"
    assert got["Aquifer"] == "None"
    assert got["Flux"] == "Present"
    assert got["Min Soil"] == "Shallow"
    assert got["Min Soil Everywhere"] == "All"
    assert got["Freezing"] == "Never Frozen"
    assert got["Min Trees"] == "Woodland"
    assert got["High Savagery"] == "Absent"
    assert got["Evil"] == "Absent"
    assert got["Reanimation"] == "None"
    # Civ lines present.
    assert got["ELF"] == "N/A"
    assert got["HUMAN"] == "N/A"
    assert got["GOBLIN"] == "N/A"
    assert got["SKULKING"] == "N/A"


def test_profile_reuses_existing_civs(tmp_path):
    # A profile saved by the finder on another world keeps its civs.
    existing = tmp_path / embark.PROFILE_NAME
    existing.parent.mkdir(parents=True)
    existing.write_text("[X Dimension:4]\n[DWARF:N/A]\n[ELF:N/A]\n")
    civs = embark.read_profile_civs(tmp_path)
    assert civs == ["DWARF", "ELF"]
    embark.write_profile(tmp_path, dict(embark.M2_PROFILE))
    got = embark.read_profile(tmp_path)
    assert got["DWARF"] == "N/A"
    assert got["ELF"] == "N/A"
    assert "SKULKING" not in got


def test_profile_overrides_a_field(tmp_path):
    prof = dict(embark.M2_PROFILE)
    prof["Metal 1"] = "COPPER"
    embark.write_profile(tmp_path, prof)
    assert embark.read_profile(tmp_path)["Metal 1"] == "COPPER"


def test_read_fileresult_file(tmp_path):
    # The file lives under data/init/ (verified live 2026-11-27),
    # not at the DF root.
    assert embark.read_fileresult_file(tmp_path) is None
    (tmp_path / "data" / "init").mkdir(parents=True)
    (tmp_path / "data" / "init" / embark.FILERESULT_NAME).write_text("42\n")
    assert embark.read_fileresult_file(tmp_path) == 42
    (tmp_path / "data" / "init" / embark.FILERESULT_NAME).write_text("Matching: 0\n")
    assert embark.read_fileresult_file(tmp_path) == 0


def test_viewport_centre_80x50():
    # Cursor (28,42) on an 80x50 grid, 65x65 world (the live case).
    vp = embark.viewport_for_cursor(28, 42, 80, 50, 65, 65)
    assert vp["left_x"] == 20  # 28 - 8
    assert vp["top_y"] == 22   # 42 - 20
    assert vp["right_x"] == 35  # 20 + 15
    assert vp["bottom_y"] == 62  # 22 + 40
    assert vp["span_x"] == 15
    assert vp["span_y"] == 40


def test_viewport_clamps_at_origin():
    vp = embark.viewport_for_cursor(0, 0, 80, 50, 65, 65)
    assert vp["left_x"] == 0
    assert vp["top_y"] == 0
    assert vp["right_x"] == 15
    assert vp["bottom_y"] == 40


def test_viewport_clamps_at_far_edge():
    # Cursor at the far corner: the viewport slides back so the
    # right/bottom edge stays inside the world.
    vp = embark.viewport_for_cursor(64, 64, 80, 50, 65, 65)
    assert vp["right_x"] == 64
    assert vp["left_x"] == 49  # 64 - 15
    assert vp["bottom_y"] == 64
    assert vp["top_y"] == 24  # 64 - 40


def test_screen_to_world_round_trip():
    # The live match: screen (35,35) with cursor (28,42) mapped to
    # world (35,55). Region view origin is (18, 2) on screen.
    vp = embark.viewport_for_cursor(28, 42, 80, 50, 65, 65)
    # World (25,55) is the top-left of the target match; it sits at
    # screen (25 - 20 + 18, 55 - 22 + 2) = (23, 35).
    assert embark.screen_to_world(23, 35, vp) == (25, 55)
    assert embark.screen_to_world(18, 2, vp) == (20, 22)
    assert embark.screen_to_world(33, 42, vp) == (35, 62)


def test_sweep_centres_65x65():
    # 65-wide world, span 16: centres tile the axis, last tile added.
    assert embark.sweep_centres(65, 16) == [8, 24, 40, 56, 64]
    # Span 41: [20, 61] already covers to the edge after clamping,
    # but the append is a safe over-approximation (one redundant
    # read) that guarantees the last tile is covered.
    assert embark.sweep_centres(65, 41) == [20, 61, 64]
    # Exact tiling lands on the last tile already.
    assert embark.sweep_centres(64, 16) == [8, 24, 40, 56, 63]


def test_rect_key_mapping():
    # The rect keys (u/m/h/k) and their directions, as the module
    # uses them in move_rect_to: k=+x, h=-x, m=+y, u=-y.
    # (Exercised here as documentation of the learned mapping;
    # the live test proves it against the game.)
    mapping = {"u": (0, -1), "m": (0, 1), "h": (-1, 0), "k": (1, 0)}
    assert mapping["u"] == (0, -1)
    assert mapping["m"] == (0, 1)
    assert mapping["h"] == (-1, 0)
    assert mapping["k"] == (1, 0)
    # 'l' is NOT a rect key.
    assert "l" not in mapping


def test_fileresult_path_is_under_data_init(tmp_path):
    # Verified live 2026-11-27: the file is at data/init/, not the DF root.
    assert embark.fileresult_path(tmp_path) == (
        tmp_path / "data" / "init" / embark.FILERESULT_NAME)


def test_read_match_grid_normalises_dict_matches(monkeypatch):
    # The Lua JSON encoder returns a Lua array as an object with
    # string numeric keys ({"1": {x, y}, ...}); read_match_grid must
    # normalise it to a list (verified live 2026-11-27, region4).
    fake = {"ok": True, "count": 2,
            "matches": {"2": {"x": 14, "y": 50},
                        "1": {"x": 10, "y": 41}}}
    monkeypatch.setattr(embark, "_run_helper",
                        lambda *a, **k: fake)
    res = embark.read_match_grid(None)
    assert res["matches"] == [{"x": 10, "y": 41}, {"x": 14, "y": 50}]
    assert res["count"] == 2
