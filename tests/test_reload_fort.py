"""Offline tests for scripts/reload_fort.py's PID-based kill and
deblibs launch environment.

The 2026-11-27 incident: a bare `pkill -9 -x Dwarf_Fortress` killed
the main fort while targeting the scratch DF, because pkill matches
by process name and both DFs share it. The fix kills by PID after
confirming the process's cwd is the DF dir being reloaded, and the
relaunch sets the deblibs LD_LIBRARY_PATH itself (apt is locked;
without it DF dies on missing libSDL).
"""

import importlib.util
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "reload_fort",
    Path(__file__).resolve().parent.parent / "scripts" / "reload_fort.py")
reload_fort = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(reload_fort)


class TestKillDf(unittest.TestCase):
    def _patch_pids(self, pids, cwds):
        """pgrep returns pids; _pid_cwd returns cwds[pid] (None if
        absent, i.e. unreadable). Returns the os.kill mock."""
        pgrep = mock.Mock(return_value=mock.Mock(
            returncode=0,
            stdout="\n".join(str(p) for p in pids) + ("\n" if pids else "")))
        kill = mock.Mock()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(reload_fort.subprocess, "run",
                          return_value=pgrep.return_value).start()
        mock.patch.object(reload_fort, "_pid_cwd",
                          side_effect=lambda pid: cwds.get(pid)).start()
        mock.patch.object(os, "kill", kill).start()
        # The wait loop: os.kill(pid, 0) must raise ProcessLookupError
        # so the pid is seen as gone at once. The mock records every
        # call; the side effect only decides the sig-0 outcome.
        def _kill(pid, sig):
            if sig == 0:
                raise ProcessLookupError(pid)
            return None
        kill.side_effect = _kill
        return kill

    def test_kills_only_pids_in_df_dir(self):
        main = Path("/home/hatch/workspace/df-agent-harness"
                    "/third_party/df_47_05")
        scratch = Path("/home/hatch/workspace/df-agent-harness"
                       "/scratch/m2-embark/df")
        kill = self._patch_pids(
            [6015, 25532], {6015: main, 25532: scratch})
        killed = reload_fort.kill_df(main)
        self.assertEqual(killed, [6015])
        kill.assert_any_call(6015, signal.SIGKILL)
        self.assertNotIn(mock.call(25532, signal.SIGKILL),
                         kill.call_args_list)

    def test_unreadable_cwd_is_left_alone(self):
        main = Path("/home/hatch/workspace/df-agent-harness"
                    "/third_party/df_47_05")
        kill = self._patch_pids([6015, 9999], {6015: main})
        killed = reload_fort.kill_df(main)
        self.assertEqual(killed, [6015])
        self.assertNotIn(mock.call(9999, signal.SIGKILL),
                         kill.call_args_list)

    def test_no_df_running_kills_nothing(self):
        main = Path("/home/hatch/workspace/df-agent-harness"
                    "/third_party/df_47_05")
        kill = self._patch_pids([], {})
        self.assertEqual(reload_fort.kill_df(main), [])
        kill.assert_not_called()

    def test_pgrep_failure_means_no_pids(self):
        main = Path("/home/hatch/workspace/df-agent-harness"
                    "/third_party/df_47_05")
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(reload_fort.subprocess, "run",
                          return_value=mock.Mock(returncode=1,
                                                 stdout="")).start()
        self.assertEqual(reload_fort._df_pids(), [])


class TestDeblibsEnv(unittest.TestCase):
    # Hermetic: every test builds its own fake deblibs tree in a
    # temp dir instead of reading the machine's scratch/deblibs.
    # On a fresh clone that dir does not exist, and these three
    # tests failed there (assertIsNotNone / KeyError) — the suite
    # must pass on a fresh checkout, not only on the author's
    # machine. The "absent" case is already covered by
    # test_deblibs_path_none_when_absent below.
    def _deblibs_tree(self, tmp, pkgs=None):
        base = Path(tmp) / "scratch" / "deblibs"
        for pkg in (reload_fort._DEBLIB_PKGS if pkgs is None else pkgs):
            (base / pkg / "usr" / "lib" / "x86_64-linux-gnu"
             ).mkdir(parents=True)
        return base

    def test_deblibs_path_includes_all_six_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._deblibs_tree(tmp)
            with mock.patch.object(reload_fort, "HARNESS", Path(tmp)):
                ld = reload_fort.deblibs_ld_library_path()
        self.assertIsNotNone(ld)
        for pkg in reload_fort._DEBLIB_PKGS:
            self.assertIn(pkg, ld)
        # libglu1-mesa is the one a hand-listed path once omitted.
        self.assertIn("libglu1-mesa", ld)

    def test_deblibs_path_none_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(reload_fort, "HARNESS",
                                   Path(tmp)):
                self.assertIsNone(reload_fort.deblibs_ld_library_path())

    def test_deblibs_path_partial_extraction(self):
        # Only dirs that exist are included, so a partial
        # extraction never breaks the launch with a dangling entry.
        with tempfile.TemporaryDirectory() as tmp:
            self._deblibs_tree(tmp, pkgs=("libsdl1.2debian",))
            with mock.patch.object(reload_fort, "HARNESS", Path(tmp)):
                ld = reload_fort.deblibs_ld_library_path()
        self.assertIsNotNone(ld)
        self.assertIn("libsdl1.2debian", ld)
        self.assertNotIn("libgl1", ld)

    def test_launch_env_sets_display_and_deblibs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._deblibs_tree(tmp)
            with mock.patch.object(reload_fort, "HARNESS", Path(tmp)):
                env = reload_fort.launch_env()
        self.assertEqual(env["DISPLAY"], ":99")
        self.assertEqual(env["TERM"], "xterm")
        self.assertIn("libsdl1.2debian", env["LD_LIBRARY_PATH"])

    def test_launch_env_preserves_existing_ld_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._deblibs_tree(tmp)
            with mock.patch.dict(os.environ,
                                 {"LD_LIBRARY_PATH": "/opt/extra/lib"}):
                with mock.patch.object(reload_fort, "HARNESS",
                                       Path(tmp)):
                    env = reload_fort.launch_env()
        self.assertTrue(env["LD_LIBRARY_PATH"].endswith(
            ":/opt/extra/lib"))


if __name__ == "__main__":
    unittest.main()
