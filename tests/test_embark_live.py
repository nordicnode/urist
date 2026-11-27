"""Live tests for the embark module (needs the scratch DF on the
embark screen — region with no fort yet, display :98, RPC 5001).

These tests NEVER embark: they verify the read paths (probe_embark,
read_match_grid, fileresult) and a cursor/rect move that returns to
its start. The live embark itself is proven by the driver run
(scripts/embark.py --full), not by a unit test — an embark creates a
fort and cannot be undone by the test.

Run: .venv/bin/python -m pytest tests/test_embark_live.py -q
Skip: if the scratch DF is not on viewscreen_choose_start_sitest
(the test prints how to get there: kill the scratch DF by PID,
relaunch, navigate Title -> Start Playing -> Dwarf Fortress).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness import embark, ui  # noqa: E402
from dfhack_rpc import DFHackClient, DFHackError  # noqa: E402

DISPLAY = ":98"
PORT = 5001
DF_DIR = Path(__file__).resolve().parent.parent / "scratch" / "m2-embark" / "df"


def _client():
    return DFHackClient("127.0.0.1", PORT, timeout=30.0)


def _on_embark_screen(client) -> bool:
    try:
        return "choose_start_sitest" in embark._screen_name(client)
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(scope="module")
def client():
    try:
        with _client() as c:
            if not _on_embark_screen(c):
                pytest.skip(
                    "scratch DF is not on the embark screen "
                    "(viewscreen_choose_start_sitest); navigate there "
                    "first (Title -> Start Playing -> Dwarf Fortress)")
            yield c
    except DFHackError as exc:
        pytest.skip(f"scratch DF RPC {PORT} unreachable: {exc}")


def test_probe_embark_live(client):
    state = embark.probe_embark(client)
    assert state["ok"], state
    assert state["screen"] == "viewscreen_choose_start_sitest"
    cur = state["cursor"]
    assert 0 <= cur["x"] < 65 and 0 <= cur["y"] < 65
    mn, mx = state["rect_min"], state["rect_max"]
    assert state["rect_w"] == 4 and state["rect_h"] == 4
    assert mx["x"] - mn["x"] == 3 and mx["y"] - mn["y"] == 3


def test_fileresult_live(client):
    wid = ui.df_window_id(DISPLAY)
    assert wid is not None
    embark.write_profile(DF_DIR, dict(embark.M2_PROFILE))
    count = embark.run_fileresult(client, DF_DIR, wid=wid,
                                  display=DISPLAY)
    # Region3 / M2 profile is 42; a fresh world may differ — the
    # assertion is only that screening returns a sane count.
    assert isinstance(count, int) and count >= 0
    # The file and the return value agree.
    assert embark.read_fileresult_file(DF_DIR) == count


def test_match_grid_live(client):
    wid = ui.df_window_id(DISPLAY)
    assert wid is not None
    # Open the overlay (a), full finder (f), Load (l), Find (f).
    ui._keys(wid, DISPLAY, "a", delay=0.5)
    ui._keys(wid, DISPLAY, "f", delay=0.5)
    ui._keys(wid, DISPLAY, "l", delay=0.5)
    ui._keys(wid, DISPLAY, "f", delay=0.5)
    import time
    time.sleep(2.0)
    res = embark.read_match_grid(client)
    assert res["ok"], res
    assert isinstance(res["matches"], list)
    assert res["count"] == len(res["matches"])
    for m in res["matches"]:
        assert 0 <= m["x"] < 65 and 0 <= m["y"] < 65
    # Quit the overlay again so a later fileresult does not hit
    # "already active".
    ui._keys(wid, DISPLAY, "q", delay=0.5)


def test_cursor_and_rect_move_and_return_live(client):
    wid = ui.df_window_id(DISPLAY)
    assert wid is not None
    start = embark.probe_embark(client)
    assert start["ok"], start
    cx, cy = start["cursor"]["x"], start["cursor"]["y"]
    rx, ry = start["rect_min"]["x"], start["rect_min"]["y"]
    # Move the cursor one tile right and back (arrow keys are exact).
    embark.move_cursor_to(client, wid, DISPLAY, cx + 1, cy)
    mid = embark.probe_embark(client)
    assert mid["cursor"]["x"] == cx + 1
    embark.move_cursor_to(client, wid, DISPLAY, cx, cy)
    back = embark.probe_embark(client)
    assert (back["cursor"]["x"], back["cursor"]["y"]) == (cx, cy)
    # Move the rect one tile down and back (u/m keys, flaky — the
    # helper re-reads and retries until it converges).
    embark.move_rect_to(client, wid, DISPLAY, rx, ry + 1)
    mid = embark.probe_embark(client)
    assert (mid["rect_min"]["x"], mid["rect_min"]["y"]) == (rx, ry + 1)
    embark.move_rect_to(client, wid, DISPLAY, rx, ry)
    back = embark.probe_embark(client)
    assert (back["rect_min"]["x"], back["rect_min"]["y"]) == (rx, ry)
