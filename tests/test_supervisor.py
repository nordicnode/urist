"""Offline tests for the systemd supervisor wrapper (run_df.py).

The safety-critical piece is pid identification: the wrapper must
watch exactly the DF in its own dir, never a bare process-name match
(a bare pkill killed the main fort while targeting the scratch DF on
2026-11-27). These tests build a fake /proc tree, so they need no
game and no systemd.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "scripts" / "supervisor"))

import run_df  # noqa: E402


def _fake_proc(tmp: Path, df_dir: Path, other_dir: Path) -> Path:
    """Fake /proc: a main DF (1234), a scratch DF (1235), an Xvfb
    (1236) sitting in the main dir, and a non-numeric entry."""
    proc = tmp / "proc"
    for pid, comm, cwd in (
            (1234, "Dwarf_Fortress", df_dir),
            (1235, "Dwarf_Fortress", other_dir),
            (1236, "Xvfb", df_dir)):
        d = proc / str(pid)
        d.mkdir(parents=True)
        (d / "comm").write_text(comm + "\n")
        os.symlink(cwd, d / "cwd")
    (proc / "self").mkdir(parents=True)
    return proc


class TestFindDfPid(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.df_dir = self.tmp / "df"
        self.other_dir = self.tmp / "other-df"
        self.df_dir.mkdir()
        self.other_dir.mkdir()
        self.proc = _fake_proc(self.tmp, self.df_dir, self.other_dir)

    def tearDown(self):
        self._td.cleanup()

    def test_finds_df_in_its_dir(self):
        self.assertEqual(run_df.find_df_pid(self.df_dir,
                                            str(self.proc)), 1234)

    def test_finds_the_other_df_by_dir(self):
        self.assertEqual(run_df.find_df_pid(self.other_dir,
                                            str(self.proc)), 1235)

    def test_ignores_non_df_process_in_dir(self):
        # Remove both DFs: only Xvfb (1236) is left in df_dir.
        for pid in ("1234", "1235"):
            (self.proc / pid / "comm").write_text("Xvfb\n")
        self.assertIsNone(run_df.find_df_pid(self.df_dir,
                                             str(self.proc)))

    def test_empty_proc(self):
        empty = self.tmp / "empty-proc"
        empty.mkdir()
        self.assertIsNone(run_df.find_df_pid(self.df_dir, str(empty)))

    def test_missing_proc_root(self):
        self.assertIsNone(run_df.find_df_pid(
            self.df_dir, str(self.tmp / "no-such-proc")))

    def test_unreadable_cwd_skipped(self):
        # A DF pid whose cwd link is broken is never assumed.
        d = self.proc / "1237"
        d.mkdir()
        (d / "comm").write_text("Dwarf_Fortress\n")
        os.symlink(self.tmp / "gone", d / "cwd")
        self.assertEqual(run_df.find_df_pid(self.df_dir,
                                            str(self.proc)), 1234)


class TestReadReloadRequest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.req = self.tmp / "reload-request"

    def tearDown(self):
        self._td.cleanup()

    def test_missing_file_is_none(self):
        self.assertIsNone(run_df.read_reload_request(self.req))

    def test_valid_request_consumed_once(self):
        cmd = f"{sys.executable} scripts/reload_fort.py S0 --exact"
        self.req.write_text(cmd + "\n")
        self.assertEqual(run_df.read_reload_request(self.req), cmd)
        self.assertFalse(self.req.exists())
        self.assertIsNone(run_df.read_reload_request(self.req))

    def test_stale_request_ignored(self):
        self.req.write_text(f"{sys.executable} x.py\n")
        os.utime(self.req, (0, 0))
        self.assertIsNone(run_df.read_reload_request(self.req))
        self.assertFalse(self.req.exists())

    def test_empty_request_ignored(self):
        self.req.write_text("\n")
        self.assertIsNone(run_df.read_reload_request(self.req))
        self.assertFalse(self.req.exists())

    def test_multiline_request_ignored(self):
        self.req.write_text(f"{sys.executable} a.py\n"
                            f"{sys.executable} b.py\n")
        self.assertIsNone(run_df.read_reload_request(self.req))
        self.assertFalse(self.req.exists())

    def test_shell_metacharacters_ignored(self):
        self.req.write_text(f"{sys.executable} a.py; rm -rf /\n")
        self.assertIsNone(run_df.read_reload_request(self.req))
        self.assertFalse(self.req.exists())

    def test_non_python_command_ignored(self):
        self.req.write_text("/bin/true\n")
        self.assertIsNone(run_df.read_reload_request(self.req))
        self.assertFalse(self.req.exists())


class TestRequestedReloadMain(unittest.TestCase):
    def test_requested_command_overrides_reload_cmd(self):
        # --reload-cmd is "false" (would fail); the request says
        # "python -c pass" (succeeds, then no DF is found). If the
        # request is honored, the output names it and the failure
        # is the missing DF, not the reload.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            df_dir = Path(d) / "df"
            df_dir.mkdir()
            req = Path(d) / "reload-request"
            req.write_text(f"{sys.executable} -c pass\n")
            r = subprocess.run(
                [sys.executable,
                 str(Path(__file__).resolve().parent.parent
                     / "scripts" / "supervisor" / "run_df.py"),
                 "--df-dir", str(df_dir), "--display", ":99",
                 "--reload-cmd", "false", "--name", "test",
                 "--request-file", str(req)],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 1)
            self.assertIn("using requested reload", r.stdout)
            self.assertIn("reload ok but no DF found", r.stdout)
            self.assertNotIn("reload failed", r.stdout)
            self.assertFalse(req.exists())


class TestWrapperExitCodes(unittest.TestCase):
    def test_failed_reload_exits_one(self):
        # A reload that fails must exit nonzero so systemd restarts
        # it — never silently sit at the title screen. 'false' is
        # the whole reload here; no game involved.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            df_dir = Path(d) / "df"
            df_dir.mkdir()
            r = subprocess.run(
                [sys.executable,
                 str(Path(__file__).resolve().parent.parent
                     / "scripts" / "supervisor" / "run_df.py"),
                 "--df-dir", str(df_dir), "--display", ":99",
                 "--reload-cmd", "false", "--name", "test"],
                capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 1)
            self.assertIn("reload failed", r.stdout)


if __name__ == "__main__":
    unittest.main()
