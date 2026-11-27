"""Offline tests for scripts/dfh.py's flag handling (H11).

The 2026-11-27 bug: _apply_flags mutated the loaded config with
the --no-auth / --allow-raw security flags, and both _cmd_start
and _cmd_daemon saved the config afterwards — so one debug start
with --no-auth persisted into ~/.config/df-agent-harness/config.json
forever, and every later start ran unauthenticated. The fix splits
persisted flags (ports) from runtime-only flags (no_auth,
allow_raw_actions): the security flags are applied AFTER save_config
and warn loudly when used.
"""

import argparse
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "dfh",
    Path(__file__).resolve().parent.parent / "scripts" / "dfh.py")
dfh = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dfh)


def _args(**kwargs):
    base = {"port": None, "df_port": None,
            "no_auth": False, "allow_raw": False}
    base.update(kwargs)
    return argparse.Namespace(**base)


class TestFlagSplit(unittest.TestCase):
    def test_persisted_flags_do_not_touch_security(self):
        config = dfh.DaemonConfig()
        dfh._apply_persisted_flags(
            _args(port=9999, df_port=5001, no_auth=True, allow_raw=True),
            config)
        self.assertEqual(config.http_port, 9999)
        self.assertEqual(config.df_port, 5001)
        self.assertFalse(config.no_auth)
        self.assertFalse(config.allow_raw_actions)

    def test_runtime_flags_apply_in_memory_only(self):
        config = dfh.DaemonConfig()
        dfh._apply_runtime_flags(_args(no_auth=True, allow_raw=True),
                                 config)
        self.assertTrue(config.no_auth)
        self.assertTrue(config.allow_raw_actions)

    def test_runtime_flags_warn(self):
        config = dfh.DaemonConfig()
        with mock.patch.object(sys, "stderr") as err:
            dfh._apply_runtime_flags(
                _args(no_auth=True, allow_raw=True), config)
        text = "".join(call.args[0] for call in err.write.call_args_list)
        self.assertIn("WARNING", text)
        self.assertIn("--no-auth", text)
        self.assertIn("--allow-raw", text)

    def test_runtime_flags_silent_when_unused(self):
        config = dfh.DaemonConfig()
        with mock.patch.object(sys, "stderr") as err:
            dfh._apply_runtime_flags(_args(), config)
        err.write.assert_not_called()

    def test_security_flags_never_reach_config_json(self):
        # The exact bug: save after applying --no-auth/--allow-raw.
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            config = dfh.load_config(state_dir)
            dfh._apply_persisted_flags(
                _args(port=9999, no_auth=True, allow_raw=True), config)
            dfh.save_config(state_dir, config)
            dfh._apply_runtime_flags(
                _args(no_auth=True, allow_raw=True), config)
            reloaded = dfh.load_config(state_dir)
            self.assertEqual(reloaded.http_port, 9999)
            self.assertFalse(reloaded.no_auth)
            self.assertFalse(reloaded.allow_raw_actions)
            # ... but the running config does have them.
            self.assertTrue(config.no_auth)
            self.assertTrue(config.allow_raw_actions)


class TestCmdStartOrdering(unittest.TestCase):
    """_cmd_start must save the config BEFORE applying the runtime
    flags, and must still pass them to the spawned daemon."""

    def test_start_saves_clean_config_but_spawns_insecure(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            spawned = {}

            class _Proc:
                pid = 1234

            def _popen(cmd, **kwargs):
                spawned["cmd"] = cmd
                return _Proc()

            with mock.patch.object(dfh, "_state_dir",
                                   return_value=state_dir), \
                 mock.patch.object(dfh.subprocess, "Popen",
                                   side_effect=_popen), \
                 mock.patch.object(dfh, "_wait_healthy",
                                   return_value=True), \
                 mock.patch.object(dfh, "load_or_create_token",
                                   return_value="tok"):
                rc = dfh._cmd_start(_args(port=9999, df_port=5001,
                                          no_auth=True, allow_raw=True))
            self.assertEqual(rc, 0)
            saved = json.loads(
                (state_dir / "config.json").read_text())
            self.assertEqual(saved["http_port"], 9999)
            self.assertEqual(saved["df_port"], 5001)
            self.assertFalse(saved["no_auth"])
            self.assertFalse(saved["allow_raw_actions"])
            self.assertIn("--no-auth", spawned["cmd"])
            self.assertIn("--allow-raw", spawned["cmd"])


class TestCmdDaemonOrdering(unittest.TestCase):
    """_cmd_daemon must save the config BEFORE applying the runtime
    flags, and must still hand them to the Daemon it builds."""

    def test_daemon_saves_clean_config_but_runs_insecure(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            seen = {}

            class _Daemon:
                def __init__(self, config, state_dir):
                    seen["config"] = config
                    self.token = None
                    self.server = None
                    self._stop = mock.Mock()

                def start(self):
                    pass

                def serve_forever(self):
                    pass

                def stop(self):
                    pass

            old_out, old_err = sys.stdout, sys.stderr
            try:
                with mock.patch.object(dfh, "_state_dir",
                                       return_value=state_dir), \
                     mock.patch.object(dfh, "Daemon", _Daemon), \
                     mock.patch.object(dfh.signal, "signal"):
                    rc = dfh._cmd_daemon(_args(port=9999, no_auth=True,
                                               allow_raw=True))
            finally:
                sys.stdout, sys.stderr = old_out, old_err
            self.assertEqual(rc, 0)
            saved = json.loads(
                (state_dir / "config.json").read_text())
            self.assertEqual(saved["http_port"], 9999)
            self.assertFalse(saved["no_auth"])
            self.assertFalse(saved["allow_raw_actions"])
            self.assertTrue(seen["config"].no_auth)
            self.assertTrue(seen["config"].allow_raw_actions)


if __name__ == "__main__":
    unittest.main()
