"""Offline tests for the dialog-handling module (dialogs.py).

Live verification (a real modal dismissed programmatically, and a
game-committing modal refused) is in the coordinator log
(2026-11-26): textviewer dismissed via dfhack.screen.dismiss, trade
screen (tradegoods/NoTraders) named and returned as a failure.
Topicmeeting resolution (dipscript jump to the farewell step) is
proven live 2026-11-27 on the scratch fort (coordinator log):
cur_step 3 -> 4, bye textviewer appeared, game set cur_step to -1,
liaison left, clock ran 6000+ ticks with no re-presentation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dfagent_harness.dialogs import (
    ALLOWLIST,
    advance,
    classify_focus,
    resolve_topicmeeting,
)


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
    # topicmeeting is UNDISMISSABLE in the plain-dismiss sense
    # (proven live 2026-11-27: screen.dismiss re-creates it every
    # tick) — its sub-screens inherit that refusal. It is still
    # resolvable programmatically via resolve_topicmeeting() (the
    # dipscript jump), which advance() routes to; the allowlist
    # entry only governs plain dismissal.
    kind, dismissable, _ = classify_focus("topicmeeting_takerequests")
    assert kind == "undismissable"
    assert dismissable is False


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
    # The two proven blocking cases are in the allowlist. textviewer
    # is dismissable (proven live); topicmeeting is in the allowlist
    # as UNDISMISSABLE (proven live 2026-11-27: screen.dismiss
    # re-creates it every tick — it needs the menu choice).
    assert "topicmeeting" in ALLOWLIST
    assert ALLOWLIST["topicmeeting"][0] is False
    assert "textviewer" in ALLOWLIST
    assert ALLOWLIST["textviewer"][0] is True


class _FakeClient:
    """Stand-in for DFHackClient: returns a canned Lua result."""

    def __init__(self, result):
        self.result = result
        self.codes = []

    def run_lua_json(self, code, timeout=None):
        self.codes.append(code)
        return dict(self.result)


def test_resolve_topicmeeting_success():
    audit = {"ok": True, "before": {"cur_step": 3, "n_steps": 5},
             "write_readback": 4,
             "dismiss": {"child_dismissed": True,
                         "parent_dismissed": True}}
    client = _FakeClient(audit)
    out = resolve_topicmeeting(client)
    assert out.get("ok") is True
    assert out.get("write_readback") == 4
    # The real Lua helper was sent (not a stub): it carries the
    # dipscript jump (cur_step write + step scan + dismiss).
    code = client.codes[0]
    assert "script_steps" in code
    assert "cur_step" in code
    assert "dfhack.screen.dismiss" in code


def test_resolve_topicmeeting_refusal_passes_through():
    # When the route does not apply (last step is not a farewell
    # textviewer) the helper refuses and nothing is written; the
    # caller must surface the refusal, not dismiss.
    audit = {"ok": False,
             "reason": "last dipscript step is not a farewell textviewer"}
    client = _FakeClient(audit)
    out = resolve_topicmeeting(client)
    assert out.get("ok") is False
    assert "farewell" in out.get("reason", "")


def test_resolve_meeting_lua_refuses_non_bye_last_step():
    # The Lua helper's refusal condition is in the source: a last
    # step whose next_step_idx is not -1, or with no filename, is
    # refused (nothing written). Pins the route's shape.
    lua_path = (Path(__file__).resolve().parent.parent / "src"
                / "dfagent_harness" / "lua" / "resolve_meeting.lua")
    src = lua_path.read_text()
    assert "next_step_idx" in src
    assert "next_idx ~= -1" in src
    assert "filename" in src
    assert "meeting.cur_step = n - 1" in src


def test_advance_routes_topicmeeting_to_resolve(monkeypatch):
    # advance() routes a blocking topicmeeting to resolve_topicmeeting
    # (not to plain dismiss), then re-checks: the bye textviewer is
    # cleared by the next round and the clock runs.
    import dfagent_harness.dialogs as dialogs

    calls = {"resolve": 0, "dismiss": 0, "checks": 0}

    def fake_is_blocking(client, wait_s=2.0):
        calls["checks"] += 1
        if calls["checks"] == 1:
            return {"blocked": True, "focus": "topicmeeting",
                    "kind": "undismissable", "reason": "meeting"}
        return {"blocked": False, "focus": "dwarfmode/Default"}

    def fake_resolve(client):
        calls["resolve"] += 1
        return {"ok": True, "before": {"cur_step": 3, "n_steps": 5},
                "write_readback": 4}

    def fake_dismiss(client):
        calls["dismiss"] += 1
        raise AssertionError("plain dismiss must not run on a meeting")

    monkeypatch.setattr(dialogs, "is_blocking", fake_is_blocking)
    monkeypatch.setattr(dialogs, "resolve_topicmeeting", fake_resolve)
    monkeypatch.setattr(dialogs, "dismiss_current", fake_dismiss)
    out = advance(None)
    assert out.get("ok") is True
    assert calls["resolve"] == 1
    assert calls["dismiss"] == 0
    assert out["cleared"][0].get("focus") == "topicmeeting"
    assert out["cleared"][0].get("write_readback") == 4


def test_advance_topicmeeting_refusal_is_a_failure(monkeypatch):
    # When the resolution route does not apply, advance() fails
    # loudly naming the meeting — it never falls through to a
    # plain dismiss or a keypress.
    import dfagent_harness.dialogs as dialogs

    def fake_is_blocking(client, wait_s=2.0):
        return {"blocked": True, "focus": "topicmeeting",
                "kind": "undismissable", "reason": "meeting"}

    def fake_resolve(client):
        return {"ok": False,
                "reason": "last dipscript step is not a farewell textviewer"}

    monkeypatch.setattr(dialogs, "is_blocking", fake_is_blocking)
    monkeypatch.setattr(dialogs, "resolve_topicmeeting", fake_resolve)
    out = advance(None)
    assert out.get("ok") is False
    assert out.get("blocked_by") == "topicmeeting"
    assert "farewell" in out.get("reason", "")
