"""Wiki lookup as a runtime tool (GOAL.md step 5, guidance layer 6).

The agent knows nothing about Dwarf Fortress; the harness is the
teacher. When the agent needs DF knowledge (how brewing works, what
a strange mood is, why a dwarf is unhappy), it asks the harness, and
the harness answers from the local DF wiki export — never from the
agent's memory, never from a prompt that only works for one model.

The wiki export is the full DF wiki as markdown (4,485 pages) with
two indexes: an SQLite FTS5 index (fast keyword search, 6-20 ms)
and a semantic vector index (bge-small-en-v1.5). The query tool
``dfq.py`` fuses both (hybrid = FTS top 20 + semantic top 20 via
RRF, k=60) — hybrid is the best default for vague questions, and
plain FTS search is the fast fallback. The semantic model must be
loaded with the NO_PROXY fix (the VM's default NO_PROXY contains
bare IPv6 entries that crash httpx/huggingface_hub) and the venv
python (fastembed lives there).

This module shells out to dfq.py (it is a standalone tool, not a
library) and returns the parsed JSON. A failed lookup is a
transport error, never an empty answer — the agent must know the
wiki did not answer, not guess.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

# The wiki export lives next to the harness workspace.
WIKI_DIR = Path.home() / "workspace" / "df-wiki-export"
DFQ = WIKI_DIR / "dfq.py"
VENV_PYTHON = WIKI_DIR / "venv" / "bin" / "python"
SYSTEM_PYTHON = "python3"

# Modes dfq.py supports. Hybrid is the best default for vague
# questions (FTS + semantic fused); search is the fast keyword
# fallback (~70 ms, no model load).
MODES = ("search", "semantic", "hybrid", "title")

# The VM's default NO_PROXY breaks httpx/huggingface_hub (bare IPv6
# entries -> "InvalidURL: Invalid port"). Override it for the
# embedding-model load (see AGENTS.md).
NO_PROXY_ENV = {
    "NO_PROXY": "localhost,127.0.0.1",
    "no_proxy": "localhost,127.0.0.1",
}


def wiki_search(query: str, mode: str = "hybrid",
                limit: int = 5) -> dict[str, Any]:
    """Search the DF wiki. Returns dfq.py's parsed JSON
    (``query``, ``ms``, ``results`` with slug/title/words/snippet).
    Raises RuntimeError when dfq.py is missing or fails, and
    ValueError for an unknown mode."""
    if mode not in MODES:
        raise ValueError(
            f"unknown wiki mode {mode!r}; legal values: "
            + ", ".join(MODES))
    if not DFQ.exists():
        raise RuntimeError(
            f"wiki query tool not found: {DFQ} (the DF wiki export "
            f"is missing; rebuild it before using wiki lookup)")
    # Semantic modes need the venv python (fastembed); plain FTS
    # search runs on the system python.
    python = str(VENV_PYTHON) if mode in ("semantic", "hybrid") \
        else SYSTEM_PYTHON
    env = dict(os.environ)
    env.update(NO_PROXY_ENV)
    proc = subprocess.run(
        [python, str(DFQ), mode, query, "--limit", str(limit),
         "--json"],
        capture_output=True, text=True, timeout=120, env=env,
        cwd=str(WIKI_DIR))
    if proc.returncode != 0:
        raise RuntimeError(
            f"dfq.py {mode} failed (exit {proc.returncode}): "
            f"{proc.stderr.strip()[:300]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"dfq.py {mode} returned unparsable JSON: {exc}")


def wiki_page(slug: str, lines: int = 0) -> dict[str, Any]:
    """Dump a whole wiki page's markdown by slug. Returns
    ``{slug, text}`` (the page subcommand prints plain markdown,
    not JSON). Raises RuntimeError when dfq.py fails (e.g. no such
    page)."""
    if not DFQ.exists():
        raise RuntimeError(f"wiki query tool not found: {DFQ}")
    env = dict(os.environ)
    env.update(NO_PROXY_ENV)
    args = [SYSTEM_PYTHON, str(DFQ), "page", slug]
    if lines:
        args += ["--lines", str(lines)]
    proc = subprocess.run(args, capture_output=True, text=True,
                          timeout=60, env=env, cwd=str(WIKI_DIR))
    if proc.returncode != 0:
        raise RuntimeError(
            f"dfq.py page {slug!r} failed (exit {proc.returncode}): "
            f"{proc.stderr.strip()[:300]}")
    return {"slug": slug, "text": proc.stdout}


def prefetch_for_event(event_kind: str, detail: str = "") -> list[dict[str, Any]]:
    """Pre-fetch relevant wiki context for an event (guidance layer
    6: relevant wiki context pre-fetched on events). Maps the event
    kind to a query; returns the top results (or [] when the kind
    has no mapping). The caller folds the results into the event's
    briefing."""
    queries = {
        "strange_mood": "strange mood",
        "invasion": "siege goblin invasion defense",
        "hostile_spawn": "hostile creature combat",
        "citizen_new": "migrant wave",
        "unit_death": "dwarf death cause",
        "new_arrival": "migrant visitor",
    }
    query = queries.get(event_kind)
    if not query:
        return []
    try:
        result = wiki_search(query, mode="search", limit=3)
    except RuntimeError:
        return []
    return result.get("results") or []
