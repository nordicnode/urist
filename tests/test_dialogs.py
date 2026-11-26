"""Offline tests for the dialog-handling module (dialogs.py).

Live verification (a real modal dismissed programmatically, and a
game-committing modal refused) is in the coordinator log
(2026-11-26): textviewer dismissed via dfhack.screen.dismiss, trade
screen (tradegoods/NoTraders) named and returned as a failure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.dialogs import ALLOWLIST, classify_focus


def test_classify_non_modal():
    kind, dismissable, _ = classify_focus("dwarfmode/Default")
    assert kind == "non_modal"
    assert dismissable is False
    kind, dismissable, _ = classify_focus("title")
    assert kind == "non_modal"


def test_classify_dismissable():
    # Every allowlist entry that is dismissable classifies as such.
    for prefix, (ok, _reason) in ALLOWLIST.items():
        if ok:
            kind, dismissable, _ = classify_focus(prefix)
            assert kind == "dismissable", prefix
            assert dismissable is True
    # Sub-screens inherit the parent's classification (prefix match).
    kind, dismissable, _ = classify_focus("topicmeeting_takerequests")
    assert kind == "dismissable"
    assert dismissable is True


def test_classify_unknown_refused():
    # Anything not in the allowlist is refused by default — an unknown
    # modal is never dismissed.
    kind, dismissable, reason = classify_focus("tradegoods/NoTraders")
    assert kind == "unknown"
    assert dismissable is False
    assert "not in the dialog allowlist" in reason
    kind, dismissable, _ = classify_focus("some_new_modal_xyz")
    assert kind == "unknown"
    assert dismissable is False


def test_classify_empty():
    kind, dismissable, _ = classify_focus(None)
    assert kind == "unknown"
    assert dismissable is False
    kind, dismissable, _ = classify_focus("")
    assert kind == "unknown"


def test_allowlist_has_meeting_and_textviewer():
    # The two proven blocking cases are in the allowlist.
    assert "topicmeeting" in ALLOWLIST
    assert ALLOWLIST["topicmeeting"][0] is True
    assert "textviewer" in ALLOWLIST
    assert ALLOWLIST["textviewer"][0] is True
