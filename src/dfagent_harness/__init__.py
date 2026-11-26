"""DF Agent Harness observation + action layers.

The observation layer is read-only: it dumps game state from a live
Dwarf Fortress 0.47.05 + DFHack game and never changes it. See
:mod:`dfagent_harness.observe` for the collector/renderer and
``docs/OBSERVE.md`` for the schema.

The action layer (:mod:`dfagent_harness.actions`, ``docs/ACTIONS.md``)
is the verified-action counterpart: every action checks world state
before and after through the observation layer and reports whether its
effect was actually observed in the game.
"""

from .actions import ACTIONS, ActionResult, act
from .observe import SECTIONS, collect, measure_fps, render_text

__all__ = ["ACTIONS", "ActionResult", "act",
           "SECTIONS", "collect", "measure_fps", "render_text"]
