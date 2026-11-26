"""Unit tests for the dialog handler (ui.dismiss_dialog).

The live keystroke path needs the game window; these tests cover
what can be checked without it: the known-dialog key map (the
liaison meeting keys, verified live) and the no-window early return.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.ui import DIALOG_KEYS, dismiss_dialog, fort_loaded


class TestFortLoaded(unittest.TestCase):
    def test_map_and_dialogs_are_loaded(self):
        # A dialog over a loaded fort is still a loaded fort: the
        # world exists, only the map view is covered.
        self.assertTrue(fort_loaded("dwarfmode/Default"))
        self.assertTrue(fort_loaded("topicmeeting"))
        self.assertTrue(fort_loaded("textviewer"))

    def test_load_title_movie_are_not_loaded(self):
        # While the game is on one of these the world is absent or
        # mid-rebuild; world-state Lua reads crashed DF twice live
        # (2026-11-26, double-free at "Resetting textures").
        for focus in ("movieplayer", "title", "loadgame",
                      "dfhack/lua", "dfhack/lua/load_screen"):
            self.assertFalse(fort_loaded(focus), focus)

    def test_none_is_not_loaded(self):
        self.assertFalse(fort_loaded(None))
        self.assertFalse(fort_loaded(""))


class TestDialogKeys(unittest.TestCase):
    def test_liaison_meeting_keys(self):
        # Verified live 2026-11-26: the outpost liaison meeting opens
        # as textviewer (greeting) then topicmeeting; "a" closes the
        # topic screen ("Finish peeking in on conversation"). Pressing
        # "a" can also advance to the trade-request list, where ESC
        # means Done (footer text, verified by screenshot).
        self.assertEqual(DIALOG_KEYS["topicmeeting"], "a")
        self.assertEqual(DIALOG_KEYS["textviewer"], "Return")
        self.assertEqual(DIALOG_KEYS["topicmeeting_takerequests"],
                         "Escape")
        self.assertEqual(DIALOG_KEYS["requestagreement"], "Escape")

    def test_only_known_dialogs_are_auto_dismissed(self):
        # Anything else must be left alone, never blind-keyed.
        self.assertEqual(sorted(DIALOG_KEYS),
                         ["requestagreement", "textviewer",
                          "topicmeeting",
                          "topicmeeting_takerequests"])

    def test_no_df_window_returns_not_ok(self):
        # No DF window -> give up before probing or keying anything.
        import unittest.mock as mock

        with mock.patch("dfagent_harness.ui.df_window_id",
                        return_value=None):
            out = dismiss_dialog(object(), display=":99")
        self.assertFalse(out["ok"])
        self.assertEqual(out["focus"], "no DF window")
        self.assertEqual(out["steps"], [])


if __name__ == "__main__":
    unittest.main()
