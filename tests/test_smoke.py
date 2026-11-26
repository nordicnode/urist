"""End-to-end test of scripts/rpc_smoke.py against the mock server.

Run from the repo root:

    .venv/bin/python -m unittest discover -s tests -v
"""

import json
import socket
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from mock_dfhack_server import MockDFHackServer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SMOKE = ROOT / "scripts" / "rpc_smoke.py"


class TestSmokeScript(unittest.TestCase):
    def test_smoke_against_mock_server(self):
        server = MockDFHackServer(
            lua_responses={'print("dfh-smoke-ok")': "dfh-smoke-ok\n"}
        ).start()
        self.addCleanup(server.stop)
        proc = subprocess.run(
            [sys.executable, str(SMOKE),
             "--host", "127.0.0.1", "--port", str(server.port)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertTrue(out["ok"])
        self.assertEqual(out["version"]["dfhack_version"], "0.47.05-r5")
        self.assertEqual(out["lua_text"], "dfh-smoke-ok\n")

    def test_smoke_fails_cleanly_when_nothing_listens(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        start = time.monotonic()
        proc = subprocess.run(
            [sys.executable, str(SMOKE),
             "--host", "127.0.0.1", "--port", str(port),
             "--timeout", "5"],
            capture_output=True, text=True, timeout=30,
        )
        elapsed = time.monotonic() - start
        self.assertNotEqual(proc.returncode, 0)
        self.assertLess(elapsed, 10, "smoke script must not hang")
        self.assertIn("could not connect", proc.stderr)
        err = json.loads(proc.stderr)
        self.assertFalse(err["ok"])


if __name__ == "__main__":
    unittest.main()
