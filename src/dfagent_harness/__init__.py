"""DF Agent Harness observation layer.

The observation layer is read-only: it dumps game state from a live
Dwarf Fortress 0.47.05 + DFHack game and never changes it. See
:mod:`dfagent_harness.observe` for the collector/renderer and
``docs/OBSERVE.md`` for the schema.
"""

from .observe import SECTIONS, collect, measure_fps, render_text

__all__ = ["SECTIONS", "collect", "measure_fps", "render_text"]
