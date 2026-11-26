"""Tests for the phase-1 observation layer (dfagent_harness.observe).

Run from the repo root:

    .venv/bin/python -m unittest discover -s tests -v

Unit tests run offline against the recorded fixture
(tests/fixtures/observe-athelunol.json) and a fake client; no DF
install needed. The live test (TestLiveObserve) connects to a running
game and skips itself when none is reachable.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness.observe import (  # noqa: E402
    FAST_SECTIONS,
    SECTIONS,
    collect,
    render_text,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_fixture(name="observe-athelunol.json"):
    with open(FIXTURES / name) as fh:
        return json.load(fh)


class FakeClient:
    """Stand-in for DFHackClient serving canned per-section payloads."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.lua_calls: list[str] = []

    def get_version(self):
        return dict(self.fixture["meta"]["version"])

    def run_lua_json(self, code, timeout=None):
        self.lua_calls.append(code)
        # The code is prelude + helper; identify the helper by its
        # section marker line (each helper prints {"ok": true, "section": ...}).
        for section in SECTIONS:
            if f'"section": "{section}"' in code or \
                    f"section = '{section}'" in code:
                return self._payload(section)
        raise AssertionError("fake client could not identify helper")

    def _payload(self, section):
        # Rebuild what the Lua helper prints: the section's data nested
        # under its own name (plus ok/section), exactly as the real
        # helpers do. stocks.lua returns both stocks and items.
        if section in ("stocks", "items"):
            return {"ok": True, "section": "stocks",
                    "stocks": self.fixture["stocks"],
                    "items": self.fixture["items"]}
        return {"ok": True, "section": section,
                section: self.fixture[section]}

    def run_lua(self, code, timeout=None):
        return "21290\n"


class TestFixtureSchema(unittest.TestCase):
    """The recorded fixture is a complete, well-formed state document."""

    def setUp(self):
        self.state = load_fixture()

    def test_top_level_sections(self):
        for section in FAST_SECTIONS:
            self.assertIn(section, self.state, f"missing {section}")
        self.assertIn("meta", self.state)
        self.assertEqual(self.state["meta"]["schema_version"], 1)
        self.assertEqual(self.state["errors"], [])

    def test_status(self):
        st = self.state["status"]
        self.assertEqual(st["fort_name"], "Athelunol")
        self.assertEqual(st["year"], 306)
        self.assertEqual(st["season"], "Spring")
        self.assertTrue(st["paused"])
        self.assertEqual(st["gametype"], "DWARF_MAIN")
        self.assertEqual(st["population"]["citizens"], 7)
        self.assertEqual(st["population"]["jobless"], 7)

    def test_units(self):
        units = self.state["units"]
        self.assertEqual(units["citizen_count"], 7)
        self.assertEqual(units["hostile_count"], 0)
        names = {c["name"] for c in units["citizens"]}
        self.assertIn("Udil Sodelkosh", names)
        # CP437 names survive as real Unicode (ä, ò, â, ë), not \u0084.
        self.assertTrue(any("ä" in n for n in names))
        for c in units["citizens"]:
            for field in ("id", "name", "profession", "pos", "stress",
                          "counters", "needs", "skills", "labors",
                          "wounds"):
                self.assertIn(field, c, f"citizen missing {field}")
            self.assertEqual(c["wound_count"], len(c["wounds"]))
            self.assertTrue(c["needs"], "needs list must not be empty")

    def test_stocks(self):
        stocks = self.state["stocks"]
        self.assertEqual(stocks["drink_units"], 60)
        self.assertEqual(stocks["food_units"], 45)
        self.assertEqual(stocks["wood_units"], 3)
        self.assertEqual(stocks["metal_bar_units"], 0)
        self.assertEqual(stocks["barrels"], 15)

    def test_buildings_jobs_reports_map(self):
        self.assertEqual(self.state["buildings"]["count"], 1)
        self.assertEqual(self.state["buildings"]["list"][0]["type"], "Wagon")
        self.assertEqual(self.state["jobs"]["count"], 0)
        self.assertEqual(self.state["jobs"]["manager_order_count"], 0)
        self.assertEqual(self.state["reports"]["announcement_count"], 0)
        self.assertEqual(self.state["map"]["size_tiles"], [192, 192])
        self.assertEqual(self.state["map"]["trees"], 1027)


class TestRenderText(unittest.TestCase):
    def setUp(self):
        self.state = load_fixture()

    def test_header_and_population(self):
        text = render_text(self.state)
        self.assertIn("Athelunol — 306-01-18 Spring", text)
        self.assertIn("PAUSED", text)
        self.assertIn("Pop: 7 citizens (7 jobless)", text)

    def test_stocks_line(self):
        text = render_text(self.state)
        self.assertIn("drink 60u (12 stacks)", text)
        self.assertIn("food 45u (9 stacks)", text)
        self.assertIn("wood 3", text)

    def test_every_citizen_rendered(self):
        text = render_text(self.state)
        for c in self.state["units"]["citizens"]:
            self.assertIn(c["name"], text)
            self.assertIn(c["profession"], text)

    def test_buildings_jobs_reports_map_lines(self):
        text = render_text(self.state)
        self.assertIn("Buildings (1): Wagon x1", text)
        self.assertIn("Jobs queued: 0", text)
        self.assertIn("Manager orders: 0", text)
        self.assertIn("Map: [192, 192] tiles", text)

    def test_section_failures_are_reported_not_hidden(self):
        state = load_fixture()
        state["errors"] = [{"section": "units",
                            "error": "boom"}]
        text = render_text(state)
        self.assertIn("SECTION FAILED [units]: boom", text)

    def test_render_is_deterministic(self):
        self.assertEqual(render_text(self.state),
                         render_text(load_fixture()))


class TestCollectWithFakeClient(unittest.TestCase):
    """Section -> state-document assembly (the nesting bug from phase 1)."""

    def test_all_fast_sections(self):
        state = collect(FakeClient(load_fixture()))
        for section in FAST_SECTIONS:
            self.assertIn(section, state, f"missing {section}")
        self.assertEqual(state["errors"], [])
        self.assertEqual(state["status"]["fort_name"], "Athelunol")
        self.assertEqual(state["units"]["citizen_count"], 7)

    def test_section_filter(self):
        state = collect(FakeClient(load_fixture()), sections=("units",))
        self.assertEqual(sorted(state.keys()),
                         ["errors", "meta", "units"])

    def test_stocks_and_items_share_one_lua_call(self):
        client = FakeClient(load_fixture())
        state = collect(client, sections=("stocks", "items"))
        self.assertIn("stocks", state)
        self.assertIn("items", state)
        self.assertEqual(len(client.lua_calls), 1)

    def test_items_only_does_not_leak_stocks(self):
        state = collect(FakeClient(load_fixture()), sections=("items",))
        self.assertIn("items", state)
        self.assertNotIn("stocks", state)

    def test_unknown_section_rejected(self):
        with self.assertRaises(ValueError):
            collect(FakeClient(load_fixture()), sections=("bogus",))

    def test_failed_section_recorded_not_fatal(self):
        class FailingClient(FakeClient):
            def run_lua_json(self, code, timeout=None):
                if "section = 'units'" in code:
                    return {"ok": False, "section": "units",
                            "error": "kaboom"}
                return super().run_lua_json(code, timeout)

        state = collect(FailingClient(load_fixture()))
        self.assertNotIn("units", state)
        self.assertIn("stocks", state)
        self.assertEqual(state["errors"],
                         [{"section": "units", "error": "kaboom"}])


if __name__ == "__main__":
    unittest.main()
