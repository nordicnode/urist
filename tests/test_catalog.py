"""Tests for the self-describing action catalog (GOAL.md step 5,
layer 1). A fresh model with no DF knowledge, given only the harness
protocol, must be able to discover what it can do — the catalog is
the map, built from the code so it cannot drift from what the
harness actually does.
"""

import http.client
import json
import os
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dfagent_harness import actions, catalog  # noqa: E402
from dfagent_harness.events import EventBus  # noqa: E402
from dfagent_harness.server import create_server  # noqa: E402
from dfhack_rpc import DFHackClient, DFHackError  # noqa: E402

HOST = os.environ.get("DFH_TEST_HOST", "127.0.0.1")
PORT = int(os.environ.get("DFH_TEST_PORT", "5000"))
LIVE_DISABLED = os.environ.get("DFH_TEST_LIVE", "1") == "0"


def _game_is_up():
    if LIVE_DISABLED:
        return False
    try:
        with DFHackClient(HOST, PORT, timeout=3.0) as client:
            client.get_version()
    except DFHackError:
        return False
    return True


class TestCatalogOffline(unittest.TestCase):
    def test_every_action_is_described(self):
        cat = catalog.catalog()
        names = [a["name"] for a in cat["actions"]]
        self.assertEqual(sorted(names), sorted(actions.ACTIONS))
        self.assertEqual(cat["count"], len(actions.ACTIONS))

    def test_every_action_has_params_and_about(self):
        for action in catalog.catalog()["actions"]:
            self.assertGreater(len(action["about"]), 10, action["name"])
            self.assertIn("params", action)
            # The 'client' parameter is the harness's, not the agent's.
            self.assertNotIn("client", action["params"])

    def test_catalog_has_wiki_query_route(self):
        # The wiki was missing from the catalog entirely (2026-11-27:
        # zero wiki uses in any M1 run) — the model never knew the
        # lookup existed. It is a query route, not an action, with an
        # example call.
        cat = catalog.catalog()
        routes = {r["route"]: r for r in cat.get("query_routes", [])}
        self.assertIn("/v1/wiki?q=<question>", routes)
        wiki_route = routes["/v1/wiki?q=<question>"]
        self.assertIn("brewing", wiki_route["example"]["route"])
        self.assertIn("q", wiki_route["params"])

    def test_required_params_have_no_default(self):
        desc = catalog.describe("designate_dig")
        self.assertTrue(desc["params"]["box"]["required"])
        self.assertFalse(desc["params"]["mode"]["required"])
        self.assertEqual(desc["params"]["mode"]["default"], "dig")

    def test_box_type_is_a_tuple(self):
        desc = catalog.describe("designate_dig")
        self.assertIn("tuple", desc["params"]["box"]["type"])
        self.assertIn("int", desc["params"]["box"]["type"])

    def test_mode_legal_values_are_named(self):
        desc = catalog.describe("designate_dig")
        self.assertIn("down-stair", str(desc["constraints"]))
        self.assertIn("FLOOR", str(desc["constraints"]))

    def test_dig_to_completion_no_stale_blocker(self):
        # The "KNOWN BLOCKER / will not create Dig jobs" text was
        # removed when f0e8617 fixed digging (2026-11-26). The
        # catalog must not tell the model NOT to dig.
        desc = catalog.describe("dig_to_completion")
        self.assertNotIn("KNOWN BLOCKER", str(desc["constraints"]))
        self.assertNotIn("will not create Dig jobs",
                         str(desc["constraints"]))
        self.assertIn("f0e8617", str(desc["constraints"]))

    def test_manager_order_names_the_noble_requirement(self):
        desc = catalog.describe("manager_order_create")
        self.assertIn("manager noble", str(desc["constraints"]))
        # job_type is a df.job_type name (MakeBarrel), NOT a
        # JOB_SPECS key — the params must say so, and the example
        # must be a real job_type name.
        self.assertIn("MakeBarrel",
                      desc["params"]["job_type"]["about"])
        self.assertNotIn("make_barrel",
                         desc["params"]["job_type"]["about"])
        self.assertEqual(desc["example"]["job_type"], "MakeBarrel")

    def test_every_example_matches_declared_params(self):
        # Every example's keys must be declared params (from the
        # real function signature), and every string example value
        # must appear in its param's "about" text (the legal values
        # the catalog declares). This catches the 2026-11-27
        # mismatches: labor_toggle example used "enable" (param is
        # "on"), build_farm_plot used "w"/"h" (params are
        # "width"/"height"), queue_job used "MakeBarrel" (the
        # JOB_SPECS key is "make_barrel").
        for action in catalog.catalog()["actions"]:
            name = action["name"]
            example = action.get("example") or {}
            params = action.get("params") or {}
            for key in example:
                self.assertIn(key, params,
                              f"{name} example key {key!r} is not a "
                              f"declared param")
            for key, value in example.items():
                if not isinstance(value, str):
                    continue
                about = (params[key].get("about") or "")
                # Only check when the about text names legal values
                # (a list or an "e.g." set); free-text params
                # (unit names) have no list to check against.
                if ("One of:" in about or "e.g." in about
                        or ", " in about):
                    self.assertIn(value, about,
                                  f"{name} example {key}={value!r} "
                                  f"is not among the values its "
                                  f"param declares: {about!r}")

    def test_queue_job_example_is_a_job_specs_key(self):
        # queue_job's "job" is a JOB_SPECS key (lowercase); the
        # example must be one, not a df.job_type name.
        desc = catalog.describe("queue_job")
        self.assertIn(desc["example"]["job"], actions.JOB_SPECS)
        self.assertIn(desc["example"]["job"],
                      desc["params"]["job"]["about"])

    def test_every_action_has_an_example(self):
        for action in catalog.catalog()["actions"]:
            self.assertIn("example", action, action["name"])

    def test_unknown_action_is_none(self):
        self.assertIsNone(catalog.describe("bogus_action"))


@unittest.skipUnless(_game_is_up(), "no live game on %s:%d" % (HOST, PORT))
class TestCatalogLive(unittest.TestCase):
    """The catalog served live (no game read — it works even with
    the game down, but here it is served by the real server)."""

    @classmethod
    def setUpClass(cls):
        cls.client = DFHackClient(HOST, PORT, timeout=180.0)
        cls.client.connect()
        cls.was_paused = actions.get_paused(cls.client)
        if not cls.was_paused:
            actions.set_paused(cls.client, True)
        cls.bus = EventBus()
        cls.server = create_server(
            cls.bus, host="127.0.0.1", port=0, client=cls.client)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(
            target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        if not cls.was_paused:
            actions.set_paused(cls.client, False)
        cls.client.close()

    def _get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                         timeout=60)
        conn.request("GET", path)
        resp = conn.getresponse()
        payload = json.loads(resp.read())
        conn.close()
        return resp.status, payload

    def test_catalog_route(self):
        status, payload = self._get("/v1/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], len(actions.ACTIONS))
        names = [a["name"] for a in payload["actions"]]
        self.assertIn("dig_to_completion", names)
        self.assertIn("how_to_call", payload)

    def test_catalog_one_route(self):
        status, payload = self._get("/v1/catalog/brew")
        # 'brew' is not an action name (brewing is a manager order
        # / custom reaction) — the route says so with the legal names.
        self.assertEqual(status, 404)
        self.assertIn("UNKNOWN_ACTION", str(payload))
        status, payload = self._get("/v1/catalog/designate_dig")
        self.assertEqual(status, 200)
        self.assertEqual(payload["name"], "designate_dig")
        self.assertIn("box", payload["params"])


if __name__ == "__main__":
    unittest.main()
